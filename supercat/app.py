"""SuperCAT Workbench – uruchamianie aplikacji."""
from __future__ import annotations

import sys
import traceback


_ICON = None
_ALTGR_FILTER = None


def _install_altgr_filter(app) -> None:
    """Oddaje AltGr+literę polom tekstowym, zanim skrót programu ją zje.

    Na polskiej klawiaturze AltGr to w Qt ``Ctrl+Alt``. Bez tego filtra
    skrót ``Ctrl+Alt+S`` zamiast „ś” uruchamiałby polecenie.
    """
    from PyQt6.QtCore import QEvent, QObject, Qt
    from PyQt6.QtWidgets import QApplication, QLineEdit, QPlainTextEdit, QTextEdit

    global _ALTGR_FILTER

    class _AltGrFilter(QObject):
        def eventFilter(self, obj, event):  # noqa: N802
            if event.type() != QEvent.Type.ShortcutOverride:
                return False
            mods = event.modifiers()
            if not (mods & Qt.KeyboardModifier.ControlModifier
                    and mods & Qt.KeyboardModifier.AltModifier):
                return False
            if mods & Qt.KeyboardModifier.ShiftModifier:
                return False
            key = event.key()
            if not (Qt.Key.Key_A <= key <= Qt.Key.Key_Z):
                return False
            focus = QApplication.focusWidget()
            if isinstance(focus, (QLineEdit, QPlainTextEdit, QTextEdit)):
                event.accept()
                return True
            return False

    _ALTGR_FILTER = _AltGrFilter(app)
    app.installEventFilter(_ALTGR_FILTER)


def _app_icon_path() -> str | None:
    """Ścieżka do ikony aplikacji (supercat/assets/supercat.ico), jeśli jest."""
    from pathlib import Path

    p = Path(__file__).resolve().parent / "assets" / "supercat.ico"
    return str(p) if p.exists() else None


def _app_icon():
    """QIcon aplikacji (lub None, gdy pliku nie ma)."""
    global _ICON
    if _ICON is None:
        from PyQt6.QtGui import QIcon

        path = _app_icon_path()
        if path:
            _ICON = QIcon(path)
    return _ICON


def main() -> int:
    from PyQt6.QtGui import QFont
    from PyQt6.QtWidgets import QApplication, QMessageBox

    app = QApplication(sys.argv)
    app.setApplicationName("SuperCAT Workbench")
    app.setOrganizationName("SuperCAT")
    app.setFont(QFont("Segoe UI", 10))
    _install_altgr_filter(app)

    icon = _app_icon()
    if icon is not None:
        app.setWindowIcon(icon)

    def excepthook(exc_type, exc_value, exc_tb):
        text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        print(text, file=sys.stderr)
        QMessageBox.critical(None, "Błąd aplikacji", f"Wystąpił błąd:\n\n{exc_value}\n\nSzczegóły w konsoli.")

    sys.excepthook = excepthook

    from .ui.main_window import MainWindow

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
