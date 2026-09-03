"""Okno wyboru plików projektu (zakres wyszukiwania)."""
from __future__ import annotations

from typing import List, Optional, Sequence

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QPushButton, QVBoxLayout,
)


class FileSelectDialog(QDialog):
    def __init__(self, names: Sequence[str], preselected: Optional[Sequence[str]] = None,
                 parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Wybierz pliki")
        self.resize(420, 420)
        self.chosen: List[str] = []

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Zaznacz pliki, w których szukać:"))

        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        chosen_set = set(preselected or names)
        for name in names:
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if name in chosen_set
                               else Qt.CheckState.Unchecked)
            self.list.addItem(item)
        layout.addWidget(self.list)

        row = QHBoxLayout()
        all_btn = QPushButton("Zaznacz wszystkie")
        all_btn.clicked.connect(lambda: self._set_all(True))
        none_btn = QPushButton("Odznacz wszystkie")
        none_btn.clicked.connect(lambda: self._set_all(False))
        row.addWidget(all_btn)
        row.addWidget(none_btn)
        row.addStretch(1)
        layout.addLayout(row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _set_all(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for i in range(self.list.count()):
            self.list.item(i).setCheckState(state)

    def _accept(self) -> None:
        self.chosen = [
            self.list.item(i).text() for i in range(self.list.count())
            if self.list.item(i).checkState() == Qt.CheckState.Checked
        ]
        self.accept()
