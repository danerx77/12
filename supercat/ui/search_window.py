"""Okno wyszukiwania – osobne, niemodalne okno w stylu OmegaT.

W OmegaT `Ctrl+F` otwiera samodzielne okno wyszukiwania: można mieć kilka
otwartych naraz (np. jedno dla „STAMP CARD”, drugie dla „System”), `Esc` je
zamyka, a dwuklik na wyniku przenosi do segmentu w edytorze — okno zostaje
otwarte obok. Tutaj działa to tak samo.

Okno używa TEGO SAMEGO widgetu, co zakładka (`SearchTab`), więc obie drogi mają
identyczne możliwości. To, czy `Ctrl+F` otwiera okno czy przełącza na zakładkę,
ustawia się w *Ustawienia → Ogólne*.
"""
from __future__ import annotations

from typing import List, Optional

from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import QCheckBox, QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from ..core.settings import SettingsManager

#: Wszystkie otwarte okna wyszukiwania (jak w OmegaT można mieć kilka naraz).
OPEN_WINDOWS: List["SearchWindow"] = []


class SearchWindow(QWidget):
    """Niemodalne okno z pełnym wyszukiwaniem."""

    def __init__(self, app, initial_text: str = "") -> None:
        super().__init__(None)
        self.app = app
        self.setWindowTitle("🔍 Znajdź i zamień – SuperCAT")
        self.setWindowFlag(Qt.WindowType.Window, True)

        # Widget wyszukiwania jest ten sam, co w zakładce – zero duplikacji logiki.
        from .search_tab import SearchTab

        self.panel = SearchTab(app, owner_window=self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(self.panel)

        bottom = QHBoxLayout()
        self.on_top = QCheckBox("Zawsze na wierzchu")
        self.on_top.setToolTip("Okno pozostaje nad głównym oknem programu")
        self.on_top.setChecked(
            SettingsManager.instance().get_bool("search.window.on.top", False))
        self.on_top.toggled.connect(self._toggle_on_top)
        bottom.addWidget(self.on_top)

        hint = QCheckBox("Zamykaj po przejściu do segmentu")
        hint.setToolTip("Po dwukliku na wyniku okno się zamknie")
        hint.setChecked(SettingsManager.instance().get_bool("search.window.close.on.goto", False))
        hint.toggled.connect(
            lambda on: SettingsManager.instance().set("search.window.close.on.goto", on))
        self.close_on_goto = hint
        bottom.addWidget(hint)

        bottom.addStretch(1)
        new_btn = QPushButton("➕ Nowe okno wyszukiwania")
        new_btn.setToolTip("Jak w OmegaT – kilka wyszukiwań naraz (Ctrl+F)")
        new_btn.clicked.connect(lambda: open_search_window(self.app))
        close_btn = QPushButton("Zamknij (Esc)")
        close_btn.clicked.connect(self.close)
        bottom.addWidget(new_btn)
        bottom.addWidget(close_btn)
        layout.addLayout(bottom)

        esc = QShortcut(QKeySequence("Esc"), self)
        esc.setContext(Qt.ShortcutContext.WindowShortcut)
        esc.activated.connect(self.close)

        self._restore_geometry()
        if self.on_top.isChecked():
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)

        if initial_text:
            self.panel.search_edit.setText(initial_text)
            self.panel.perform_search()
        self.panel.search_edit.setFocus()
        self.panel.search_edit.selectAll()

    # ------------------------------------------------------------------
    def _toggle_on_top(self, on: bool) -> None:
        SettingsManager.instance().set("search.window.on.top", on)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, on)
        self.show()

    def _restore_geometry(self) -> None:
        settings = SettingsManager.instance()
        width = settings.get_int("search.window.width", 1000)
        height = settings.get_int("search.window.height", 620)
        self.resize(max(600, width), max(400, height))
        # kolejne okna przesuwamy, żeby się nie zasłaniały (jak w OmegaT)
        offset = 28 * (len(OPEN_WINDOWS) % 6)
        main = self.app
        if main is not None and main.isVisible():
            geo = main.geometry()
            self.move(geo.x() + 60 + offset, geo.y() + 70 + offset)

    def notify_goto(self) -> None:
        """Wywoływane przez panel po przejściu do segmentu."""
        if self.close_on_goto.isChecked():
            self.close()

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        settings = SettingsManager.instance()
        settings.set("search.window.width", self.width())
        settings.set("search.window.height", self.height())
        # zdejmij podświetlenie wyszukiwania, jeśli nie ma innych okien
        if self in OPEN_WINDOWS:
            OPEN_WINDOWS.remove(self)
        if not OPEN_WINDOWS:
            editor = getattr(self.app, "editor_tab", None)
            if editor is not None:
                editor.clear_search_highlight()
        super().closeEvent(event)


def open_search_window(app, initial_text: str = "") -> SearchWindow:
    """Otwiera nowe okno wyszukiwania i zwraca je."""
    window = SearchWindow(app, initial_text)
    OPEN_WINDOWS.append(window)
    window.show()
    window.raise_()
    window.activateWindow()
    return window


def close_all_search_windows() -> None:
    for window in list(OPEN_WINDOWS):
        window.close()
