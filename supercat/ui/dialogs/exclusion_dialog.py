"""Okno dodawania i edycji reguły wykluczania segmentu."""
from __future__ import annotations

from typing import List, Optional, Sequence

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit,
    QPlainTextEdit, QVBoxLayout,
)

from ...core.exclusions import MATCH_TYPES, ExclusionRule


class ExclusionDialog(QDialog):
    """Edytor pojedynczej reguły – ze sprawdzaniem wzorca na żywo."""

    def __init__(self, rule: Optional[ExclusionRule] = None, parent=None,
                 files: Optional[Sequence[str]] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Reguła wykluczania" if rule else "Nowa reguła wykluczania")
        self.resize(620, 460)
        self.rule: Optional[ExclusionRule] = None

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.match_type = QComboBox()
        for key, label in MATCH_TYPES.items():
            self.match_type.addItem(label, key)
        self.match_type.currentIndexChanged.connect(self._update_preview)
        form.addRow("Sposób dopasowania:", self.match_type)

        self.pattern = QLineEdit()
        self.pattern.setPlaceholderText("np.  <<< FILE:*>>>")
        self.pattern.textChanged.connect(self._update_preview)
        form.addRow("Wzorzec:", self.pattern)

        self.comment = QLineEdit()
        self.comment.setPlaceholderText("do czego służy ta reguła (opcjonalnie)")
        form.addRow("Opis:", self.comment)

        self.file_filter = QComboBox()
        self.file_filter.addItem("(wszystkie pliki)", "")
        for name in files or []:
            self.file_filter.addItem(name, name)
        form.addRow("Dotyczy pliku:", self.file_filter)

        self.case_sensitive = QCheckBox("Rozróżniaj wielkość liter")
        self.case_sensitive.stateChanged.connect(self._update_preview)
        form.addRow(self.case_sensitive)

        self.enabled = QCheckBox("Reguła włączona")
        self.enabled.setChecked(True)
        form.addRow(self.enabled)
        layout.addLayout(form)

        hint = QLabel(
            "💡 <b>Gwiazdka (*)</b> zastępuje dowolny ciąg znaków — wzorzec "
            "<code>&lt;&lt;&lt; FILE:*&gt;&gt;&gt;</code> pasuje do każdego wiersza "
            "<code>&lt;&lt;&lt; FILE: cokolwiek &gt;&gt;&gt;</code>, niezależnie od nazwy pliku."
        )
        hint.setWordWrap(True)
        hint.setTextFormat(Qt.TextFormat.RichText)
        hint.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(hint)

        layout.addWidget(QLabel("Sprawdź na przykładach (każdy wiersz to osobny segment):"))
        self.sample = QPlainTextEdit()
        self.sample.setPlainText(
            "<<< FILE: CeladonCity_Condominiums_RoofRoom/text.inc >>>\n"
            "<<< FILE: PalletTown/scripts.inc >>>\n"
            "Thank you for using the STAMP CARD System.\n"
            "#org @8005A2\n"
            "{STR_VAR_1}"
        )
        self.sample.setMaximumHeight(110)
        self.sample.textChanged.connect(self._update_preview)
        layout.addWidget(self.sample)

        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        layout.addWidget(self.preview)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        self.ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        layout.addWidget(buttons)

        if rule is not None:
            index = self.match_type.findData(rule.match_type)
            self.match_type.setCurrentIndex(index if index >= 0 else 0)
            self.pattern.setText(rule.pattern)
            self.comment.setText(rule.comment)
            self.case_sensitive.setChecked(rule.case_sensitive)
            self.enabled.setChecked(rule.enabled)
            file_index = self.file_filter.findData(rule.file_filter)
            if file_index >= 0:
                self.file_filter.setCurrentIndex(file_index)
        self._update_preview()

    # ------------------------------------------------------------------
    def _current_rule(self) -> ExclusionRule:
        return ExclusionRule(
            pattern=self.pattern.text(),
            match_type=self.match_type.currentData() or "contains",
            enabled=self.enabled.isChecked(),
            case_sensitive=self.case_sensitive.isChecked(),
            comment=self.comment.text().strip(),
            file_filter=self.file_filter.currentData() or "",
        )

    def _update_preview(self) -> None:
        """Pokazuje, które przykładowe wiersze zostaną wykluczone."""
        rule = self._current_rule()
        error = rule.error()
        if error:
            self.status.setText(f"❌ {error}")
            self.status.setStyleSheet("color: #ef5350;")
            self.preview.setPlainText("")
            self.ok_button.setEnabled(False)
            return

        lines = [l for l in self.sample.toPlainText().splitlines() if l.strip()]
        matched: List[str] = []
        kept: List[str] = []
        for line in lines:
            (matched if rule.matches(line) else kept).append(line)

        report = []
        if matched:
            report.append("🚫 WYKLUCZONE:")
            report += [f"    {l}" for l in matched]
        if kept:
            report.append("")
            report.append("✅ DO TŁUMACZENIA:")
            report += [f"    {l}" for l in kept]
        self.preview.setPlainText("\n".join(report))

        self.status.setText(f"Pasuje {len(matched)} z {len(lines)} przykładów")
        self.status.setStyleSheet("color: #66bb6a;" if matched else "color: gray;")
        self.ok_button.setEnabled(True)

    def _accept(self) -> None:
        rule = self._current_rule()
        if rule.error():
            return
        self.rule = rule
        self.accept()
