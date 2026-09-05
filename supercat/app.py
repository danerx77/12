"""SuperCAT Workbench – uruchamianie aplikacji."""
from __future__ import annotations

import sys
import traceback


_ICON = None


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
