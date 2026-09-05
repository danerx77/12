"""Zakładka Glosariusz (termbaza) oraz Słowniki."""
from __future__ import annotations

import os

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QProgressBar, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget,
)

from ..core.glossary import DOWNLOADABLE_DICTIONARIES, GlossaryEntry
from .workers import DictionaryDownloadWorker


class TermDialog(QDialog):
    def __init__(self, parent=None, entry: GlossaryEntry | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Termin glosariusza")
        self.setMinimumWidth(420)
        layout = QFormLayout(self)
        self.source = QLineEdit(entry.source if entry else "")
        self.target = QLineEdit(entry.target if entry else "")
        self.description = QLineEdit(entry.description if entry else "")
        self.pos = QLineEdit(entry.part_of_speech if entry else "")
        self.gender = QLineEdit(entry.gender if entry else "")
        layout.addRow("Termin źródłowy:", self.source)
        layout.addRow("Tłumaczenie:", self.target)
        layout.addRow("Opis:", self.description)
        layout.addRow("Część mowy:", self.pos)
        layout.addRow("Rodzaj:", self.gender)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def entry(self) -> GlossaryEntry:
        return GlossaryEntry(
            self.source.text().strip(), self.target.text().strip(),
            self.description.text().strip(), self.pos.text().strip(), self.gender.text().strip(),
        )


class GlossaryTab(QWidget):
    def __init__(self, app) -> None:
        super().__init__()
        self.app = app
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        self.info = QLabel("Glosariusz: brak projektu")
        self.info.setStyleSheet("font-weight: bold;")
        top.addWidget(self.info)
        top.addStretch(1)
        self.search = QLineEdit()
        self.search.setPlaceholderText("szukaj terminu…")
        self.search.setMaximumWidth(320)
        self.search.textChanged.connect(self.refresh)
        top.addWidget(self.search)
        layout.addLayout(top)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Termin źródłowy", "Tłumaczenie", "Opis", "Część mowy", "Rodzaj"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.doubleClicked.connect(self.edit_term)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)

        buttons = QHBoxLayout()
        for text, slot in (
            ("➕ Dodaj termin", self.add_term),
            ("✏️ Edytuj", self.edit_term),
            ("🗑️ Usuń", self.delete_term),
            ("📥 Importuj CSV", self.import_glossary),
            ("📤 Eksportuj CSV", self.export_glossary),
            ("🔄 Odśwież", self.refresh),
        ):
            btn = QPushButton(text)
            btn.clicked.connect(slot)
            buttons.addWidget(btn)
        buttons.addStretch(1)
        layout.addLayout(buttons)

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        glossary = self.app.glossary
        entries = glossary.search(self.search.text())
        self.table.setRowCount(len(entries))
        for r, e in enumerate(entries):
            for c, value in enumerate((e.source, e.target, e.description, e.part_of_speech, e.gender)):
                self.table.setItem(r, c, QTableWidgetItem(value))
        self.info.setText(f"Glosariusz: {glossary.size} terminów" + (f" (wyświetlono {len(entries)})" if len(entries) != glossary.size else ""))

    def _selected_entry(self) -> GlossaryEntry | None:
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows:
            return None
        r = rows[0].row()
        source = self.table.item(r, 0).text()
        target = self.table.item(r, 1).text()
        for e in self.app.glossary.entries:
            if e.source == source and e.target == target:
                return e
        return None

    def add_term(self) -> None:
        if not self._require_project():
            return
        dialog = TermDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            entry = dialog.entry()
            if entry.source and entry.target:
                self.app.glossary.add(entry.source, entry.target, entry.description, entry.part_of_speech, entry.gender)
                self.refresh()

    def edit_term(self) -> None:
        entry = self._selected_entry()
        if not entry:
            return
        dialog = TermDialog(self, entry)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_entry = dialog.entry()
            idx = self.app.glossary.entries.index(entry)
            self.app.glossary.update(idx, new_entry)
            self.refresh()

    def delete_term(self) -> None:
        entry = self._selected_entry()
        if not entry:
            return
        if QMessageBox.question(self, "Usuń termin", f"Usunąć „{entry.source} → {entry.target}”?") == QMessageBox.StandardButton.Yes:
            self.app.glossary.remove(entry)
            self.refresh()

    def import_glossary(self) -> None:
        if not self._require_project():
            return
        path, _ = QFileDialog.getOpenFileName(self, "Importuj glosariusz", "", "Pliki CSV/TSV/TXT (*.csv *.tsv *.txt);;Wszystkie pliki (*)")
        if not path:
            return
        count = self.app.glossary.import_file(path)
        self.refresh()
        QMessageBox.information(self, "Import glosariusza", f"Zaimportowano {count} terminów.")

    def export_glossary(self) -> None:
        project = self.app.project
        default = f"{project.export_path}/glosariusz.csv" if project else "glosariusz.csv"
        path, _ = QFileDialog.getSaveFileName(self, "Eksportuj glosariusz", default, "Pliki CSV (*.csv)")
        if not path:
            return
        count = self.app.glossary.export_file(path)
        QMessageBox.information(self, "Eksport glosariusza", f"Zapisano {count} terminów do:\n{path}")

    def _require_project(self) -> bool:
        if not self.app.glossary.is_initialized:
            QMessageBox.information(self, "Glosariusz", "Najpierw otwórz lub utwórz projekt.")
            return False
        return True


class DictionaryTab(QWidget):
    """Słowniki (pliki .dic/.txt) – dodawanie, pobieranie i sprawdzanie pisowni."""

    def __init__(self, app) -> None:
        super().__init__()
        self.app = app
        self._download_worker = None
        layout = QVBoxLayout(self)

        # --- nagłówek + ścieżka folderu --------------------------------
        self.info = QLabel("Słowniki: brak projektu")
        self.info.setStyleSheet("font-weight: bold;")
        layout.addWidget(self.info)

        path_row = QHBoxLayout()
        self.folder_label = QLabel("—")
        self.folder_label.setStyleSheet("color: gray;")
        self.folder_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        path_row.addWidget(QLabel("📁 Folder słowników:"))
        path_row.addWidget(self.folder_label, 1)
        open_btn = QPushButton("📂 Otwórz folder słowników")
        open_btn.setToolTip("Otwiera katalog, w którym program szuka plików .dic i .txt")
        open_btn.clicked.connect(self.open_folder)
        path_row.addWidget(open_btn)
        layout.addLayout(path_row)

        # --- zarządzanie plikami ---------------------------------------
        manage = QGroupBox("Zainstalowane słowniki")
        manage_layout = QVBoxLayout(manage)
        self.files_list = QListWidget()
        self.files_list.setToolTip("Pliki słowników wczytane z folderu projektu")
        manage_layout.addWidget(self.files_list)

        buttons = QHBoxLayout()
        add_btn = QPushButton("➕ Dodaj słownik z pliku…")
        add_btn.setToolTip("Skopiuj plik .dic lub .txt do folderu słowników projektu")
        add_btn.clicked.connect(self.add_from_file)
        download_btn = QPushButton("⬇ Pobierz słownik…")
        download_btn.setToolTip("Pobiera gotowy słownik Hunspell (m.in. polski, 350 tys. słów)")
        download_btn.clicked.connect(self.download_dictionary)
        remove_btn = QPushButton("🗑️ Usuń zaznaczony")
        remove_btn.clicked.connect(self.remove_selected)
        reload_btn = QPushButton("🔄 Przeładuj")
        reload_btn.clicked.connect(self.reload)
        for b in (add_btn, download_btn, remove_btn, reload_btn):
            buttons.addWidget(b)
        buttons.addStretch(1)
        manage_layout.addLayout(buttons)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        manage_layout.addWidget(self.progress)
        layout.addWidget(manage)

        # --- sprawdzanie słowa ------------------------------------------
        check_box = QGroupBox("Sprawdź pisownię wyrazu")
        check_layout = QVBoxLayout(check_box)
        row = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setPlaceholderText("wpisz słowo, aby sprawdzić pisownię / zobaczyć podobne formy…")
        self.query.returnPressed.connect(self.lookup)
        btn = QPushButton("🔍 Sprawdź")
        btn.clicked.connect(self.lookup)
        row.addWidget(self.query, 1)
        row.addWidget(btn)
        check_layout.addLayout(row)

        self.result = QLabel("")
        check_layout.addWidget(self.result)
        self.list = QListWidget()
        check_layout.addWidget(self.list)
        layout.addWidget(check_box, 1)

        hint = QLabel(
            "💡 Zalecany słownik: <b>„polski – pełna odmiana, 4,5 mln form (SJP.pl)”</b> – "
            "zawiera wszystkie formy odmienione, więc wyrazy takie jak „Witamy”, "
            "„Dziękujemy” czy „Systemu” nie są zgłaszane jako błędy. "
            "Zwykły plik <code>.dic</code> ma tylko formy podstawowe.<br>"
            "Słowniki działają w kontroli pisowni (panel „🔤 Język” i zakładka „✅ QA”)."
        )
        hint.setWordWrap(True)
        hint.setTextFormat(Qt.TextFormat.RichText)
        hint.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(hint)

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        d = self.app.dictionary
        folder = self.app.project.dictionary_path if self.app.project else None
        self.folder_label.setText(folder or "— (najpierw otwórz projekt)")
        self.folder_label.setToolTip(folder or "")
        if d.is_initialized:
            if d.has_morphology:
                engine = f"✅ pełna odmiana (Hunspell: {d.hunspell_source})"
            elif d.has_inflected_forms():
                # Lista SJP.pl ma już wszystkie formy odmienione wypisane wprost.
                engine = "✅ pełna odmiana (lista zawiera formy odmienione)"
            else:
                engine = ("⚠️ tylko formy podstawowe – poprawne słowa („ofiarę”, "
                          "„zamrozić”, „jeźdząc”) będą zgłaszane jako błędy. "
                          "Pobierz „polski – pełna odmiana (SJP.pl)”.")
            self.info.setText(
                f"Słowniki: {d.size} słów • plików: {len(d.sources)} • {engine}")
        elif folder:
            self.info.setText("Słowniki: brak plików w folderze dictionary/")
        else:
            self.info.setText("Słowniki: brak projektu")

        self.files_list.clear()
        for name in d.sources:
            count = d.source_counts.get(name, 0)
            encoding = d.encodings.get(name, "")
            extra = f", {encoding}" if encoding and encoding != "utf-8" else ""
            item = QListWidgetItem(f"📖 {name}   ({count} słów{extra})")
            item.setData(Qt.ItemDataRole.UserRole, name)
            self.files_list.addItem(item)
        if not d.sources:
            placeholder = QListWidgetItem("(brak słowników – użyj „⬇ Pobierz słownik…”)")
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self.files_list.addItem(placeholder)

    def open_folder(self) -> None:
        """Otwiera folder słowników w menedżerze plików systemu."""
        if not self.app.project:
            QMessageBox.information(self, "Słowniki", "Najpierw otwórz lub utwórz projekt.")
            return
        folder = self.app.project.dictionary_path
        os.makedirs(folder, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
        self.app.show_status(f"Otwarto folder słowników: {folder}")

    def add_from_file(self) -> None:
        """Kopiuje wskazany plik słownika do folderu projektu."""
        if not self.app.project:
            QMessageBox.information(self, "Słowniki", "Najpierw otwórz lub utwórz projekt.")
            return
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Wybierz pliki słownika", "",
            "Słowniki (*.dic *.txt);;Hunspell (*.dic);;Lista słów (*.txt);;Wszystkie pliki (*)",
        )
        if not paths:
            return
        added, errors = 0, []
        for path in paths:
            try:
                self.app.dictionary.install_file(path, self.app.project.dictionary_path)
                added += 1
            except Exception as exc:
                errors.append(f"{os.path.basename(path)}: {exc}")
        self.reload()
        if errors:
            QMessageBox.warning(self, "Słowniki",
                                "Nie udało się dodać:\n\n" + "\n".join(errors))
        if added:
            self.app.show_status(f"Dodano słowniki: {added}")

    def download_dictionary(self) -> None:
        """Pobiera gotowy słownik Hunspell z repozytorium LibreOffice."""
        if not self.app.project:
            QMessageBox.information(self, "Słowniki", "Najpierw otwórz lub utwórz projekt.")
            return
        if self._download_worker is not None:
            QMessageBox.information(self, "Słowniki", "Pobieranie już trwa.")
            return

        labels = [f"{name}   ({size})" for name, _f, _u, size in DOWNLOADABLE_DICTIONARIES]
        choice, ok = QInputDialog.getItem(
            self, "Pobierz słownik",
            "Wybierz słownik do pobrania:\n(pliki pochodzą z repozytorium LibreOffice)",
            labels, 0, False,
        )
        if not ok or not choice:
            return
        index = labels.index(choice)
        _name, filename, url, _size = DOWNLOADABLE_DICTIONARIES[index]

        folder = self.app.project.dictionary_path
        os.makedirs(folder, exist_ok=True)
        target = os.path.join(folder, filename)
        if os.path.exists(target):
            if QMessageBox.question(
                self, "Pobierz słownik",
                f"Plik „{filename}” już istnieje. Pobrać ponownie i nadpisać?",
            ) != QMessageBox.StandardButton.Yes:
                return

        self.progress.setVisible(True)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat(f"Pobieranie {filename}… %p%")

        # Plik .aff (obok .dic) deklaruje kodowanie słownika – pobieramy go
        # w tle, bo bez niego polskie znaki wczytują się jako „�”.
        aff_url = url[:-4] + ".aff" if url.endswith(".dic") else ""
        aff_target = target[:-4] + ".aff" if target.endswith(".dic") else ""

        worker = DictionaryDownloadWorker(url, target, parent=self,
                                          extra_url=aff_url, extra_path=aff_target)

        def on_progress(done: int, total: int) -> None:
            if total > 0:
                self.progress.setRange(0, total)
                self.progress.setValue(done)
            else:
                self.progress.setRange(0, 0)      # nieokreślony postęp

        def on_finished(path: str, error: str) -> None:
            self.progress.setVisible(False)
            self._download_worker = None
            if error:
                QMessageBox.warning(self, "Pobieranie słownika",
                                    f"Nie udało się pobrać słownika:\n\n{error}")
                return
            self.reload()
            size_mb = os.path.getsize(path) / 1024 / 1024
            QMessageBox.information(
                self, "Pobieranie słownika",
                f"Pobrano „{os.path.basename(path)}” ({size_mb:.1f} MB).\n"
                f"Słownik liczy teraz {self.app.dictionary.size} słów.")
            self.app.show_status(f"Pobrano słownik: {os.path.basename(path)}")

        worker.progress.connect(on_progress)
        worker.finished_download.connect(on_finished)
        self._download_worker = worker
        worker.start()

    def remove_selected(self) -> None:
        item = self.files_list.currentItem()
        name = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not name:
            QMessageBox.information(self, "Słowniki", "Zaznacz słownik na liście.")
            return
        if QMessageBox.question(
            self, "Usuń słownik", f"Usunąć plik „{name}” z folderu projektu?",
        ) != QMessageBox.StandardButton.Yes:
            return
        if self.app.dictionary.remove_file(name, self.app.project.dictionary_path):
            self.reload()
            self.app.show_status(f"Usunięto słownik: {name}")

    def reload(self) -> None:
        if self.app.project:
            self.app.dictionary.init_for_project(self.app.project.dictionary_path)
        self.refresh()

    def lookup(self) -> None:
        word = self.query.text().strip()
        self.list.clear()
        if not word:
            return
        d = self.app.dictionary
        if not d.is_initialized:
            self.result.setText("⚠️ Brak wczytanych słowników – pobierz lub dodaj słownik.")
            return
        ok = d.is_correct(word)
        if ok:
            self.result.setText("✅ Słowo poprawne")
            for suggestion in d.lookup(word):
                self.list.addItem(suggestion)
            return
        self.result.setText("❌ Słowa nie ma w słowniku – propozycje poprawnej pisowni:")
        for suggestion in d.suggest_corrections(word, 10):
            self.list.addItem(f"✏️ {suggestion}")
        for suggestion in d.lookup(word)[:15]:
            self.list.addItem(suggestion)
