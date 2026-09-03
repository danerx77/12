"""Zakładka AI – widoczny podgląd pracy modelu.

Wzorowana na sekcji AI z Supervertaler Workbench, ale ograniczona do tego,
co potrzebne przy tłumaczeniu:

* **Dziennik pracy** – na żywo widać, co program robi w danej chwili
  (wysyłanie, oczekiwanie, odpowiedź, czas), więc nie wygląda na zawieszony,
* **Zmienne i polecenie** – podgląd polecenia wysyłanego do modelu wraz
  z własnymi wytycznymi użytkownika,
* **Test tłumaczenia** – szybkie sprawdzenie, czy model odpowiada poprawnie.
"""
from __future__ import annotations

import time
from typing import Optional

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QComboBox, QGroupBox, QHBoxLayout, QLabel, QPlainTextEdit, QProgressBar,
    QPushButton, QSplitter, QTextEdit, QVBoxLayout, QWidget,
)

from ..core.ai_clean import build_translation_prompt
from ..core.settings import SettingsManager
from .theme import setup_splitter

#: Kolory wpisów dziennika wg rodzaju zdarzenia.
LEVEL_COLORS = {
    "info": "#8ab4f8",
    "send": "#ffd54f",
    "ok": "#81c784",
    "error": "#ef5350",
    "wait": "#b0bec5",
}


class _TestWorker(QThread):
    """Pojedyncze tłumaczenie testowe wykonywane poza wątkiem interfejsu."""

    step = pyqtSignal(str, str)          # (komunikat, poziom)
    done = pyqtSignal(str, float, str)   # (wynik, czas_ms, surowa_odpowiedź)

    def __init__(self, mt, text: str, sl: str, tl: str, engine: str, parent=None) -> None:
        super().__init__(parent)
        self.mt, self.text, self.sl, self.tl, self.engine = mt, text, sl, tl, engine

    def run(self) -> None:
        started = time.perf_counter()
        self.step.emit(f"Wysyłanie do silnika „{self.engine}”…", "send")
        try:
            out = self.mt.translate_with(self.engine, self.text, self.sl, self.tl)
        except Exception as exc:
            out = f"[Błąd: {exc}]"
        elapsed = (time.perf_counter() - started) * 1000
        self.done.emit(out, elapsed, out)


class AIPanel(QWidget):
    """Zakładka „🤖 AI” – podgląd pracy modelu i konfiguracja polecenia."""

    def __init__(self, app) -> None:
        super().__init__()
        self.app = app
        self._worker: Optional[_TestWorker] = None
        self._active_since: Optional[float] = None
        self._active_label = ""
        self._build_ui()

        # „tętno” – aktualizuje licznik czasu trwającej operacji, żeby było
        # widać, że program pracuje, a nie zawiesił się
        self._pulse = QTimer(self)
        self._pulse.timeout.connect(self._tick)
        self._pulse.start(200)

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        # --- pasek stanu operacji ---------------------------------------
        status_box = QGroupBox("⚙️ Bieżąca praca AI")
        sl = QVBoxLayout(status_box)
        row = QHBoxLayout()
        self.state_label = QLabel("Bezczynny")
        self.state_label.setStyleSheet("font-weight: bold;")
        row.addWidget(self.state_label)
        row.addStretch(1)
        self.elapsed_label = QLabel("")
        row.addWidget(self.elapsed_label)
        sl.addLayout(row)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setMaximumHeight(6)
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        sl.addWidget(self.progress)
        layout.addWidget(status_box)

        splitter = QSplitter(Qt.Orientation.Vertical)

        # --- dziennik pracy ---------------------------------------------
        log_box = QGroupBox("📜 Dziennik pracy (co robi program w tej chwili)")
        ll = QVBoxLayout(log_box)
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setFont(QFont("Consolas", 10))
        ll.addWidget(self.log_view)
        log_row = QHBoxLayout()
        clear_btn = QPushButton("🧹 Wyczyść")
        clear_btn.clicked.connect(self.log_view.clear)
        copy_btn = QPushButton("📋 Kopiuj dziennik")
        copy_btn.clicked.connect(self._copy_log)
        log_row.addWidget(clear_btn)
        log_row.addWidget(copy_btn)
        log_row.addStretch(1)
        ll.addLayout(log_row)
        splitter.addWidget(log_box)

        # --- polecenie i wytyczne ---------------------------------------
        prompt_box = QGroupBox("✨ Polecenie wysyłane do modelu")
        pl = QVBoxLayout(prompt_box)
        pl.addWidget(QLabel(
            "Własne wytyczne (np. „styl gry retro”, „zwracaj się per Ty”) — "
            "dopisywane do polecenia:"
        ))
        self.instructions = QPlainTextEdit()
        self.instructions.setMaximumHeight(70)
        self.instructions.setPlainText(
            SettingsManager.instance().get_str("mt.ai.instructions", "")
        )
        self.instructions.textChanged.connect(self._save_instructions)
        pl.addWidget(self.instructions)

        pl.addWidget(QLabel("Podgląd pełnego polecenia (zmienne podstawiane automatycznie):"))
        self.prompt_preview = QPlainTextEdit()
        self.prompt_preview.setReadOnly(True)
        pl.addWidget(self.prompt_preview)

        vars_label = QLabel(
            "Dostępne zmienne: <b>{źródło}</b> i <b>{cel}</b> — języki projektu, "
            "<b>@#0#@</b> — chronione znaczniki (\\n, \\p, {ZMIENNA}, &lt;tag&gt;), "
            "które model musi zwrócić bez zmian."
        )
        vars_label.setWordWrap(True)
        vars_label.setStyleSheet("color: gray; font-size: 11px;")
        pl.addWidget(vars_label)
        splitter.addWidget(prompt_box)

        # --- test tłumaczenia -------------------------------------------
        test_box = QGroupBox("🧪 Test tłumaczenia")
        tl = QVBoxLayout(test_box)
        test_row = QHBoxLayout()
        self.engine_combo = QComboBox()
        test_row.addWidget(QLabel("Silnik:"))
        test_row.addWidget(self.engine_combo, 1)
        run_btn = QPushButton("▶ Przetłumacz próbkę")
        run_btn.clicked.connect(self.run_test)
        seg_btn = QPushButton("↧ Wstaw bieżący segment")
        seg_btn.clicked.connect(self._load_current_segment)
        test_row.addWidget(seg_btn)
        test_row.addWidget(run_btn)
        tl.addLayout(test_row)

        self.test_input = QPlainTextEdit(
            r"Thank you for using the MYSTERY\nGIFT System."
        )
        self.test_input.setMaximumHeight(70)
        tl.addWidget(self.test_input)
        self.test_output = QPlainTextEdit()
        self.test_output.setReadOnly(True)
        self.test_output.setMaximumHeight(70)
        self.test_output.setPlaceholderText("Tutaj pojawi się oczyszczone tłumaczenie…")
        tl.addWidget(self.test_output)
        splitter.addWidget(test_box)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 3)
        splitter.setStretchFactor(2, 2)
        setup_splitter(splitter, minimums=[140, 140])
        layout.addWidget(splitter)

        self.refresh()

    # ------------------------------------------------------------- logika
    def refresh(self) -> None:
        """Odświeża listę silników i podgląd polecenia."""
        from ..core.mt import ENGINES

        current = self.engine_combo.currentData()
        self.engine_combo.blockSignals(True)
        self.engine_combo.clear()
        for key, label in ENGINES:
            self.engine_combo.addItem(label, key)
        target = current or self.app.mt.engine
        index = next((i for i in range(self.engine_combo.count())
                      if self.engine_combo.itemData(i) == target), 0)
        self.engine_combo.setCurrentIndex(index)
        self.engine_combo.blockSignals(False)
        self.update_prompt_preview()

    def update_prompt_preview(self) -> None:
        project = self.app.project
        sl = project.source_lang if project else "en"
        tl = project.target_lang if project else "pl"
        glossary = None
        if getattr(self.app, "glossary", None) and self.app.glossary.entries:
            glossary = [(e.source, e.target) for e in self.app.glossary.entries[:40]]
        self.prompt_preview.setPlainText(
            build_translation_prompt(sl, tl, self.instructions.toPlainText().strip(), glossary)
        )

    def _save_instructions(self) -> None:
        text = self.instructions.toPlainText().strip()
        SettingsManager.instance().set("mt.ai.instructions", text)
        self.app.mt.ai_instructions = text
        self.update_prompt_preview()

    def _load_current_segment(self) -> None:
        seg = self.app.editor_tab.current_segment()
        if seg:
            self.test_input.setPlainText(seg.source)
        else:
            self.log("Brak wybranego segmentu.", "error")

    def _copy_log(self) -> None:
        from PyQt6.QtWidgets import QApplication

        QApplication.clipboard().setText(self.log_view.toPlainText())
        self.log("Skopiowano dziennik do schowka.", "info")

    # -------------------------------------------------------- dziennik
    def log(self, message: str, level: str = "info") -> None:
        """Dopisuje wpis do dziennika pracy (widoczny dla użytkownika)."""
        color = LEVEL_COLORS.get(level, LEVEL_COLORS["info"])
        stamp = time.strftime("%H:%M:%S")
        self.log_view.append(
            f'<span style="color:#888">{stamp}</span> '
            f'<span style="color:{color}">{message}</span>'
        )
        scroll = self.log_view.verticalScrollBar()
        scroll.setValue(scroll.maximum())

    def begin_activity(self, label: str) -> None:
        """Sygnalizuje rozpoczęcie długiej operacji AI."""
        self._active_since = time.perf_counter()
        self._active_label = label
        self.state_label.setText(f"⏳ {label}")
        self.state_label.setStyleSheet("font-weight: bold; color: #ffd54f;")
        self.progress.setRange(0, 0)      # pasek nieokreślony = „pracuję”
        self.log(label, "send")

    def end_activity(self, message: str = "Gotowe", level: str = "ok") -> None:
        elapsed = ""
        if self._active_since is not None:
            ms = (time.perf_counter() - self._active_since) * 1000
            elapsed = f" ({self._format(ms)})"
        self._active_since = None
        self.state_label.setText("Bezczynny")
        self.state_label.setStyleSheet("font-weight: bold;")
        self.elapsed_label.setText("")
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.log(f"{message}{elapsed}", level)

    def _tick(self) -> None:
        if self._active_since is None:
            return
        ms = (time.perf_counter() - self._active_since) * 1000
        self.elapsed_label.setText(f"⏱ {self._format(ms)}")
        # po dłuższym czasie dopisz uspokajającą informację
        if ms > 15000 and int(ms) % 5000 < 220:
            self.log("Nadal czekam na odpowiedź modelu…", "wait")

    @staticmethod
    def _format(ms: float) -> str:
        from .editor_tab import EditorTab

        unit = SettingsManager.instance().get_str("ui.time.unit", "auto")
        return EditorTab.format_duration(ms, unit)

    # ------------------------------------------------------------- test
    def run_test(self) -> None:
        text = self.test_input.toPlainText().strip()
        if not text:
            self.log("Wpisz tekst do przetłumaczenia.", "error")
            return
        if self._worker is not None and self._worker.isRunning():
            self.log("Poprzedni test jeszcze trwa…", "wait")
            return
        engine = self.engine_combo.currentData() or self.app.mt.engine
        project = self.app.project
        sl = project.source_lang if project else "en"
        tl = project.target_lang if project else "pl"

        self.test_output.clear()
        self.begin_activity(f"Tłumaczenie próbki silnikiem „{engine}”")
        worker = _TestWorker(self.app.mt, text, sl, tl, engine, parent=self)
        worker.step.connect(lambda msg, lvl: self.log(msg, lvl))
        worker.done.connect(self._on_test_done)
        self._worker = worker
        worker.start()

    def _on_test_done(self, result: str, elapsed_ms: float, raw: str) -> None:
        self.test_output.setPlainText(result)
        if result.startswith("[Błąd"):
            self.end_activity(f"Niepowodzenie: {result[:120]}", "error")
        else:
            self.end_activity(f"Otrzymano tłumaczenie ({len(result)} znaków)", "ok")
        self._worker = None
