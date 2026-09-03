"""Małe okno pokazywane podczas wczytywania projektu.

Otwarcie projektu to kilka etapów (pamięć TM, glosariusz, słowniki, parsowanie
plików, wczytanie tłumaczeń). Przy większych projektach trwa to na tyle długo,
że bez informacji zwrotnej wygląda, jakby program się zawiesił.

Okno jest **modalne, bez przycisku zamknięcia** – nie da się przypadkiem kliknąć
w połowie wczytywania. Znika samo po zakończeniu.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication, QDialog, QLabel, QProgressBar, QVBoxLayout,
)


class LoadingDialog(QDialog):
    """Okno postępu z listą etapów wczytywania."""

    def __init__(self, title: str, steps: Optional[List[str]] = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        # Bez przycisku zamknięcia i bez paska systemowego – okno znika samo.
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.CustomizeWindowHint
                            | Qt.WindowType.WindowTitleHint)
        self.setModal(True)
        self.setFixedWidth(430)

        self._steps = list(steps or [])
        self._current = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        self.header = QLabel(f"<b>{title}</b>")
        self.header.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(self.header)

        self.step_label = QLabel("Przygotowywanie…")
        self.step_label.setWordWrap(True)
        layout.addWidget(self.step_label)

        self.bar = QProgressBar()
        self.bar.setRange(0, max(1, len(self._steps)))
        self.bar.setValue(0)
        self.bar.setTextVisible(True)
        self.bar.setFormat("%p%")
        layout.addWidget(self.bar)

        self.detail = QLabel("")
        self.detail.setWordWrap(True)
        self.detail.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(self.detail)

    # ------------------------------------------------------------------
    def start_step(self, text: str, detail: str = "") -> None:
        """Rozpoczyna kolejny etap i odświeża okno."""
        self._current += 1
        self.step_label.setText(f"{self._current}/{max(len(self._steps), self._current)}  {text}")
        self.detail.setText(detail)
        self.bar.setValue(min(self._current, self.bar.maximum()))
        # Okno rysuje się w tym samym wątku co praca, więc trzeba je odświeżyć
        # ręcznie – inaczej zostałoby puste do samego końca.
        QApplication.processEvents()

    def set_detail(self, text: str) -> None:
        self.detail.setText(text)
        QApplication.processEvents()

    def finish(self) -> None:
        self.bar.setValue(self.bar.maximum())
        QApplication.processEvents()
        self.close()

    def keyPressEvent(self, event) -> None:  # noqa: N802 (Qt API)
        # Esc nie może przerwać wczytywania w połowie.
        if event.key() == Qt.Key.Key_Escape:
            return
        super().keyPressEvent(event)


def run_with_progress(parent, title: str, steps: List[Tuple[str, callable]],
                      detail_of=None) -> Optional[Exception]:
    """Wykonuje etapy po kolei, pokazując postęp. Zwraca wyjątek albo None.

    `steps` to lista par (opis, funkcja). Funkcja może zwrócić tekst, który
    zostanie pokazany jako szczegół etapu.
    """
    dialog = LoadingDialog(title, [name for name, _fn in steps], parent)
    dialog.show()
    QApplication.processEvents()
    try:
        for name, function in steps:
            dialog.start_step(name)
            result = function()
            if isinstance(result, str) and result:
                dialog.set_detail(result)
        dialog.finish()
        return None
    except Exception as exc:      # okno musi zniknąć nawet przy błędzie
        dialog.close()
        return exc
