"""Okno przechwytujące nową kombinację klawiszy dla skrótu."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence
from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QLineEdit, QVBoxLayout


class ShortcutCatcher(QLineEdit):
    """Pole, które zamiast tekstu zapisuje naciśniętą kombinację."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setPlaceholderText("naciśnij kombinację klawiszy…")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def keyPressEvent(self, event) -> None:  # noqa: N802 (Qt API)
        key = event.key()
        # Same modyfikatory nie tworzą skrótu – czekamy na klawisz właściwy.
        if key in (Qt.Key.Key_Control, Qt.Key.Key_Shift, Qt.Key.Key_Alt,
                   Qt.Key.Key_Meta, Qt.Key.Key_unknown):
            return
        if key == Qt.Key.Key_Escape:
            self.clear()
            return
        if key in (Qt.Key.Key_Backspace, Qt.Key.Key_Delete) and not event.modifiers():
            self.clear()
            return
        sequence = QKeySequence(key | int(event.modifiers().value))
        self.setText(sequence.toString())


class ShortcutDialog(QDialog):
    """Prosi o nową kombinację dla wskazanego polecenia."""

    def __init__(self, definition, parent=None) -> None:
        super().__init__(parent)
        self.definition = definition
        self.sequence = ""
        self.setWindowTitle("Zmień skrót klawiszowy")
        self.resize(420, 220)

        layout = QVBoxLayout(self)
        title = QLabel(f"<b>{definition.label}</b>")
        title.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(title)
        layout.addWidget(QLabel(f"Domyślnie: {definition.default}"))

        self.catcher = ShortcutCatcher()
        from ...core import shortcuts as _sc

        self.catcher.setText(_sc.get(definition.key))
        layout.addWidget(self.catcher)

        hint = QLabel(
            "Esc lub Backspace czyści pole (skrót zostanie wyłączony).\n"
            "Zatwierdź przyciskiem OK."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(hint)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.catcher.setFocus()

    def _accept(self) -> None:
        self.sequence = self.catcher.text().strip()
        self.accept()
