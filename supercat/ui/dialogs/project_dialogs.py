"""Dialogi: nowy projekt, ustawienia projektu, podgląd segmentacji, O programie."""
from __future__ import annotations

import os

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QMessageBox, QPlainTextEdit, QPushButton, QSpinBox,
    QTextBrowser, QVBoxLayout, QWidget,
)

LANGUAGES = [
    ("pl", "polski"), ("en", "angielski"), ("de", "niemiecki"), ("fr", "francuski"),
    ("es", "hiszpański"), ("it", "włoski"), ("nl", "niderlandzki"), ("cs", "czeski"),
    ("sk", "słowacki"), ("uk", "ukraiński"), ("ru", "rosyjski"), ("pt", "portugalski"),
    ("sv", "szwedzki"), ("no", "norweski"), ("da", "duński"), ("fi", "fiński"),
    ("zh", "chiński"), ("ja", "japoński"), ("ko", "koreański"), ("ar", "arabski"),
    ("tr", "turecki"), ("hu", "węgierski"), ("ro", "rumuński"), ("lt", "litewski"),
]


def _lang_combo(default: str) -> QComboBox:
    combo = QComboBox()
    for code, name in LANGUAGES:
        combo.addItem(f"{name} ({code})", code)
    idx = next((i for i, (c, _n) in enumerate(LANGUAGES) if c == default), 0)
    combo.setCurrentIndex(idx)
    return combo


class NewProjectDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Nowy projekt")
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)

        form = QFormLayout()
        self.name_edit = QLineEdit("Nowy projekt")
        form.addRow("Nazwa projektu:", self.name_edit)

        self.source_lang = _lang_combo("en")
        self.target_lang = _lang_combo("pl")
        form.addRow("Język źródłowy:", self.source_lang)
        form.addRow("Język docelowy:", self.target_lang)

        path_row = QHBoxLayout()
        default_base = os.path.join(os.path.expanduser("~"), "SuperCAT_Projects")
        self.path_edit = QLineEdit(default_base)
        browse = QPushButton("📂 Przeglądaj")
        browse.clicked.connect(self._browse)
        path_row.addWidget(self.path_edit, 1)
        path_row.addWidget(browse)
        form.addRow("Lokalizacja:", path_row)

        self.seg_mode = QComboBox()
        self.seg_mode.addItems(["sentence", "line", "paragraph", "custom_delimiter", "regex"])
        form.addRow("Tryb segmentacji:", self.seg_mode)

        layout.addLayout(form)

        info = QLabel(
            "W katalogu projektu powstaną foldery: <b>source/</b>, <b>target/</b>, <b>tm/</b>, "
            "<b>glossary/</b>, <b>dictionary/</b>, <b>export/</b>.<br>"
            "Skopiuj pliki do przetłumaczenia do folderu <b>source/</b> lub użyj „Importuj pliki”."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _browse(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Wybierz katalog na projekty", self.path_edit.text())
        if path:
            self.path_edit.setText(path)

    def _validate(self) -> None:
        if not self.name_edit.text().strip():
            QMessageBox.warning(self, "Nowy projekt", "Podaj nazwę projektu.")
            return
        if not self.path_edit.text().strip():
            QMessageBox.warning(self, "Nowy projekt", "Wskaż lokalizację projektu.")
            return
        os.makedirs(self.path_edit.text().strip(), exist_ok=True)
        self.accept()

    def values(self) -> dict:
        return {
            "name": self.name_edit.text().strip(),
            "source_lang": self.source_lang.currentData(),
            "target_lang": self.target_lang.currentData(),
            "base_path": self.path_edit.text().strip(),
            "seg_mode": self.seg_mode.currentText(),
        }


class ProjectSettingsDialog(QDialog):
    def __init__(self, project, parent=None) -> None:
        super().__init__(parent)
        self.project = project
        self.setWindowTitle("Ustawienia projektu")
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.name_edit = QLineEdit(project.name)
        form.addRow("Nazwa:", self.name_edit)
        self.source_lang = _lang_combo(project.source_lang)
        self.target_lang = _lang_combo(project.target_lang)
        form.addRow("Język źródłowy:", self.source_lang)
        form.addRow("Język docelowy:", self.target_lang)

        self.seg_enabled = QCheckBox("Włącz segmentację")
        self.seg_enabled.setChecked(project.segmentation.enabled)
        form.addRow(self.seg_enabled)

        self.seg_mode = QComboBox()
        self.seg_mode.addItems(["sentence", "line", "paragraph", "custom_delimiter", "regex"])
        self.seg_mode.setCurrentText(project.segmentation.mode)
        form.addRow("Tryb segmentacji:", self.seg_mode)

        self.delims = QLineEdit(project.segmentation.delimiters)
        form.addRow("Znaki końca zdania:", self.delims)
        self.custom_delim = QLineEdit(project.segmentation.custom_delimiter)
        form.addRow("Własny separator:", self.custom_delim)
        self.regex = QLineEdit(project.segmentation.regex_pattern)
        form.addRow("Wyrażenie regularne:", self.regex)

        self.fuzzy = QSpinBox()
        self.fuzzy.setRange(30, 100)
        self.fuzzy.setValue(project.tm.fuzzy_threshold)
        form.addRow("Próg dopasowania TM (%):", self.fuzzy)

        self.auto_add = QCheckBox("Automatycznie dodawaj zatwierdzone segmenty do TM")
        self.auto_add.setChecked(project.tm.auto_add_to_tm)
        form.addRow(self.auto_add)

        layout.addLayout(form)
        layout.addWidget(QLabel(f"<i>Katalog projektu: {project.project_path}</i>"))

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def apply(self) -> None:
        p = self.project
        p.name = self.name_edit.text().strip() or p.name
        p.source_lang = self.source_lang.currentData()
        p.target_lang = self.target_lang.currentData()
        p.segmentation.enabled = self.seg_enabled.isChecked()
        p.segmentation.mode = self.seg_mode.currentText()
        p.segmentation.delimiters = self.delims.text()
        p.segmentation.custom_delimiter = self.custom_delim.text()
        p.segmentation.regex_pattern = self.regex.text()
        p.tm.fuzzy_threshold = self.fuzzy.value()
        p.tm.auto_add_to_tm = self.auto_add.isChecked()


class SegmentationPreviewDialog(QDialog):
    """Podgląd wyniku segmentacji dla wklejonego tekstu."""

    def __init__(self, segmentation_settings, parent=None) -> None:
        super().__init__(parent)
        self.settings = segmentation_settings
        self.setWindowTitle("Podgląd segmentacji")
        self.resize(760, 560)
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Wklej tekst, aby zobaczyć, jak zostanie podzielony na segmenty:"))
        self.input = QPlainTextEdit()
        self.input.setPlainText(
            "To jest pierwsze zdanie. To drugie, np. z użyciem skrótu! A to trzecie?\n"
            "Kolejny wiersz tekstu."
        )
        layout.addWidget(self.input)

        row = QHBoxLayout()
        self.mode = QComboBox()
        self.mode.addItems(["sentence", "line", "paragraph", "custom_delimiter", "regex"])
        self.mode.setCurrentText(segmentation_settings.mode)
        row.addWidget(QLabel("Tryb:"))
        row.addWidget(self.mode)
        preview_btn = QPushButton("▶ Podgląd")
        preview_btn.clicked.connect(self.run_preview)
        row.addWidget(preview_btn)
        row.addStretch(1)
        layout.addLayout(row)

        self.result = QListWidget()
        layout.addWidget(self.result)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
        self.run_preview()

    def run_preview(self) -> None:
        from copy import copy

        from ...core.segmentation import segment_text

        settings = copy(self.settings)
        settings.mode = self.mode.currentText()
        self.result.clear()
        for i, seg in enumerate(segment_text(self.input.toPlainText(), settings), start=1):
            self.result.addItem(f"{i}. {seg}")


class AboutDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("O programie SuperCAT")
        self.resize(620, 520)
        layout = QVBoxLayout(self)
        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        from ...core import shortcuts as _sc

        rows = []
        for definition in _sc.SHORTCUTS:
            seq = _sc.get(definition.key) or definition.default
            if not seq.strip():
                continue
            rows.append(f"<tr><td><b>{seq}</b></td><td>{definition.label}</td></tr>")
        rows.append("<tr><td><b>Alt+↑ / Alt+↓</b></td><td>poprzedni / następny segment (w edytorze)</td></tr>")
        table = "\n".join(rows)
        browser.setHtml(
            f"""
            <h2>SuperCAT Workbench 1.0</h2>
            <p>Narzędzie CAT (Computer-Aided Translation) napisane w Pythonie (PyQt6).</p>
            <p>Interfejs w stylu <b>Supervertaler Workbench</b> – jedno okno, zakładki
            Edytor / TM / Glosariusz / Słowniki / Szukaj / QA / Ustawienia.</p>
            <h3>Funkcje</h3>
            <ul>
              <li>Projekty ze strukturą folderów (source, target, tm, glossary, dictionary, export)</li>
              <li>Import: TXT, DOCX, XLSX, XLIFF/XLF, PO, SRT, HTML, MD, CSV</li>
              <li>Segmentacja: zdania / wiersze / akapity / własny separator / regex</li>
              <li>Pamięć tłumaczeń SQLite, dopasowania rozmyte, import i eksport TMX</li>
              <li>Adaptacja tagów w podpowiedziach TM</li>
              <li>Glosariusz z podświetlaniem terminów, słowniki i sprawdzanie pisowni</li>
              <li>Tłumaczenie maszynowe: lokalne, DeepL, OpenAI, LibreTranslate, Google, IBM Watson, własny endpoint</li>
              <li>Kontrola jakości QA + statystyki, raport do pliku</li>
              <li>Znajdź i zamień (zawiera / całe słowo / dokładne / regex), konkordancja</li>
              <li>Eksport: odtworzenie oryginału, DOCX, XLSX, XLIFF, PO, SRT, HTML dwujęzyczny, TXT</li>
            </ul>
            <h3>Skróty klawiszowe</h3>
            <p>Kombinacje można zmienić w <b>Ustawienia → Skróty</b>.
            Żaden domyślny skrót nie używa Alt z literą, żeby nie blokować polskich znaków
            (AltGr = Ctrl+Alt w Qt).</p>
            <table cellpadding="4">
              {table}
            </table>
            """
        )
        layout.addWidget(browser)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
