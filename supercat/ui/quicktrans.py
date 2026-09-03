"""QuickTrans – błyskawiczne tłumaczenie z wielu silników naraz.

Odpowiednik `modules/quicktrans.py` z Supervertaler Workbench: jedno okno
pokazuje propozycje ze wszystkich dostępnych silników MT równolegle.
Wybór klawiszem 1-9 lub podwójnym kliknięciem, Esc zamyka.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPlainTextEdit,
    QPushButton, QVBoxLayout, QWidget,
)

from ..core.mt import ENGINE_CODES, ENGINES

#: Kolory „pigułek” dostawców – jak w Supervertaler QuickTrans.
PROVIDER_COLORS = {
    "GT": "#4285F4", "DL": "#042B48", "MM": "#2ECC71", "LT": "#F59E0B",
    "GPT": "#10A37F", "IBM": "#0F62FE", "AI": "#9C27B0", "LOC": "#666666",
    "MS": "#00A4EF", "AZ": "#0078D4", "GEM": "#8E75B2", "PUT": "#E67E22",
    "DLW": "#0F2B46",
}


class _MultiWorker(QThread):
    """Odpytuje wszystkie silniki równolegle, poza wątkiem interfejsu."""

    ready = pyqtSignal(list)

    def __init__(self, mt, text: str, sl: str, tl: str, engines: List[str], parent=None) -> None:
        super().__init__(parent)
        self.mt, self.text, self.sl, self.tl, self.engines = mt, text, sl, tl, engines

    def run(self) -> None:
        try:
            results = self.mt.translate_multi(self.text, self.sl, self.tl, self.engines)
        except Exception as exc:
            results = [("!", "Błąd", str(exc), True)]
        self.ready.emit(results)


class QuickTransDialog(QDialog):
    """Popup z propozycjami tłumaczenia ze wszystkich silników."""

    def __init__(self, app, text: str, source_lang: str, target_lang: str, parent=None) -> None:
        super().__init__(parent)
        self.app = app
        self.chosen: Optional[str] = None
        self._worker: Optional[_MultiWorker] = None

        self.setWindowTitle("⚡ QuickTrans – tłumaczenie z wielu silników")
        self.resize(880, 560)

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("<b>Tekst źródłowy</b> (możesz edytować i tłumaczyć ponownie):"))
        self.source_edit = QPlainTextEdit(text)
        self.source_edit.setMaximumHeight(110)
        layout.addWidget(self.source_edit)

        row = QHBoxLayout()
        self.lang_label = QLabel(f"{source_lang} → {target_lang}")
        self.lang_label.setStyleSheet("font-weight: bold;")
        row.addWidget(self.lang_label)
        row.addStretch(1)
        from ..core.settings import SettingsManager

        self.free_only = QCheckBox("Tylko silniki bez klucza API")
        self.free_only.setToolTip(
            "Działa, gdy w Ustawieniach → Tłumaczenie maszynowe nie wskazano\n"
            "własnej listy silników QuickTrans.")
        self.free_only.setChecked(SettingsManager.instance().get_bool("mt.quicktrans.free_only", True))
        self.free_only.stateChanged.connect(
            lambda st: (SettingsManager.instance().set("mt.quicktrans.free_only", bool(st)), self.fetch())
        )
        row.addWidget(self.free_only)
        refresh = QPushButton("🔄 Tłumacz ponownie")
        refresh.clicked.connect(self.fetch)
        row.addWidget(refresh)
        layout.addLayout(row)

        self.status = QLabel("⏳ Pobieranie tłumaczeń…")
        layout.addWidget(self.status)

        self.results = QListWidget()
        self.results.setWordWrap(True)
        self.results.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.results.itemDoubleClicked.connect(lambda _i: self.accept_selected())
        layout.addWidget(self.results, 1)

        hint = QLabel("💡 Klawisze 1–9 wybierają propozycję • Enter wstawia zaznaczoną • Esc zamyka")
        hint.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(hint)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        insert_btn = QPushButton("⤵ Wstaw zaznaczone")
        insert_btn.clicked.connect(self.accept_selected)
        close_btn = QPushButton("Zamknij")
        close_btn.clicked.connect(self.reject)
        self.retry_failed_btn = QPushButton("🔁 Ponów nieudane")
        self.retry_failed_btn.setToolTip(
            "Próbuje jeszcze raz tylko tymi silnikami, które zgłosiły błąd")
        self.retry_failed_btn.setEnabled(False)
        self.retry_failed_btn.clicked.connect(self.retry_failed)
        buttons.addWidget(self.retry_failed_btn)
        buttons.addWidget(insert_btn)
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)

        for n in range(1, 10):
            QShortcut(QKeySequence(str(n)), self, lambda i=n - 1: self._pick(i))
        QShortcut(QKeySequence("Return"), self, self.accept_selected)

        self.source_lang, self.target_lang = source_lang, target_lang
        self._failed_engines: List[str] = []
        self.fetch()

    # ------------------------------------------------------------------
    def fetch(self) -> None:
        text = self.source_edit.toPlainText().strip()
        self.results.clear()
        if not text:
            self.status.setText("Wpisz tekst do przetłumaczenia.")
            return
        engines = self.app.mt.quicktrans_engines(only_free=self.free_only.isChecked())
        if not engines:
            self.status.setText("Brak dostępnych silników – skonfiguruj je w Ustawieniach.")
            return
        self.status.setText(f"⏳ Pobieranie z {len(engines)} silników…")
        worker = _MultiWorker(self.app.mt, text, self.source_lang, self.target_lang, engines, self)
        worker.ready.connect(self._show_results)
        self._worker = worker
        worker.start()

    #: Skrócone, zrozumiałe opisy typowych awarii silników MT.
    ERROR_HINTS = [
        ("429", "limit zapytań wyczerpany – odczekaj kilka minut"),
        ("Too Many Requests", "limit zapytań wyczerpany – odczekaj kilka minut"),
        ("10061", "brak połączenia z serwerem (czy jest uruchomiony?)"),
        ("niedostępny", ""),          # komunikat jest już czytelny
        ("Brak klucza", ""),
        ("timed out", "serwer nie odpowiedział na czas"),
        ("Name or service not known", "brak połączenia z internetem"),
        ("getaddrinfo", "brak połączenia z internetem"),
    ]

    def _friendly_error(self, message: str) -> str:
        """Zamienia surowy komunikat wyjątku na zdanie zrozumiałe dla tłumacza."""
        text = (message or "").replace("[Błąd MT:", "").strip().rstrip("]")
        for needle, hint in self.ERROR_HINTS:
            if needle.lower() in text.lower():
                return f"⚠️ {hint}" if hint else f"⚠️ {text}"
        return f"⚠️ {text[:160]}"

    def _show_results(self, results: List[Tuple[str, str, str, bool]]) -> None:
        self.results.clear()
        self._failed_engines = []
        ok = 0
        for code, name, translation, is_error in results:
            number = self.results.count() + 1
            shown = self._friendly_error(translation) if is_error else translation
            item = QListWidgetItem(f"{number}. [{code}] {name}\n     {shown}")
            item.setData(Qt.ItemDataRole.UserRole, "" if is_error else translation)
            if is_error:
                item.setForeground(QColor("#ef5350"))
                item.setToolTip(translation)      # pełna treść błędu pod kursorem
                self._failed_engines.append(name)
            else:
                item.setForeground(QColor(PROVIDER_COLORS.get(code, "#81c784")))
                ok += 1
            self.results.addItem(item)

        summary = f"Otrzymano {ok} tłumaczeń z {len(results)} silników"
        if self._failed_engines:
            summary += f"  •  nie odpowiedziały: {len(self._failed_engines)}"
        self.status.setText(summary)
        self.retry_failed_btn.setEnabled(bool(self._failed_engines))
        if self.results.count():
            # Zaznaczamy pierwszy DZIAŁAJĄCY wynik, nie wiersz z błędem.
            for row in range(self.results.count()):
                if self.results.item(row).data(Qt.ItemDataRole.UserRole):
                    self.results.setCurrentRow(row)
                    break
            else:
                self.results.setCurrentRow(0)

    def retry_failed(self) -> None:
        """Ponawia tłumaczenie tylko tymi silnikami, które zawiodły."""
        text = self.source_edit.toPlainText().strip()
        if not text or not getattr(self, "_failed_engines", None):
            return
        labels = dict(self.app.mt.available_engines(only_free=False))
        engines = [(key, name) for key, name in labels.items()
                   if name in self._failed_engines]
        if not engines:
            engines = self.app.mt.quicktrans_engines(only_free=self.free_only.isChecked())
        self.status.setText(f"⏳ Ponawianie {len(engines)} silników…")
        worker = _MultiWorker(self.app.mt, text, self.source_lang, self.target_lang,
                              engines, self)
        worker.ready.connect(self._merge_retry)
        self._worker = worker
        worker.start()

    def _merge_retry(self, results: List[Tuple[str, str, str, bool]]) -> None:
        """Podmienia wiersze silników, które przy ponowieniu się udały."""
        fixed = {name: (code, translation, is_error)
                 for code, name, translation, is_error in results}
        rebuilt: List[Tuple[str, str, str, bool]] = []
        for row in range(self.results.count()):
            text = self.results.item(row).text()
            name = text.split("] ", 1)[-1].split("\n")[0] if "] " in text else ""
            code = text.split("[", 1)[-1].split("]", 1)[0] if "[" in text else ""
            value = self.results.item(row).data(Qt.ItemDataRole.UserRole)
            if name in fixed:
                new_code, new_text, new_error = fixed[name]
                rebuilt.append((new_code, name, new_text, new_error))
            else:
                rebuilt.append((code, name, value or "", not value))
        self._show_results(rebuilt)

    def _pick(self, index: int) -> None:
        if 0 <= index < self.results.count():
            self.results.setCurrentRow(index)
            self.accept_selected()

    def accept_selected(self) -> None:
        item = self.results.currentItem()
        if not item:
            return
        value = item.data(Qt.ItemDataRole.UserRole)
        if not value:
            return  # wiersz z błędem
        self.chosen = value
        self.accept()

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._worker is not None and self._worker.isRunning():
            self._worker.wait(2000)
        event.accept()
