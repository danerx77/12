"""SuperCAT Workbench – uruchamianie aplikacji."""
from __future__ import annotations

import sys
import traceback


def _app_icon_path() -> str | None:
    """Ścieżka do ikony aplikacji (supercat/assets/supercat.ico), jeśli jest."""
    from pathlib import Path

    p = Path(__file__).resolve().parent / "assets" / "supercat.ico"
    return str(p) if p.exists() else None


def main() -> int:
    from PyQt6.QtGui import QFont, QIcon
    from PyQt6.QtWidgets import QApplication, QMessageBox

    app = QApplication(sys.argv)
    app.setApplicationName("SuperCAT Workbench")
    app.setOrganizationName("SuperCAT")
    app.setFont(QFont("Segoe UI", 10))

    icon_path = _app_icon_path()
    if icon_path:
        app.setWindowIcon(QIcon(icon_path))

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
