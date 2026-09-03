"""Edytor TMX / pamięci TM – wzorowany na TMX Editor z Supervertaler Workbench.

Możliwości:
* otwieranie i zapisywanie plików TMX (oraz edycja pamięci bieżącego projektu),
* siatka dwujęzyczna z filtrowaniem i stronicowaniem,
* panel edycji nad siatką (bez okien modalnych),
* dodawanie, usuwanie, kopiowanie źródła do celu,
* wyszukiwanie i zamiana w całej pamięci,
* czyszczenie: usuwanie duplikatów, pustych wpisów, przycinanie spacji,
  usuwanie tagów formatowania,
* statystyki i edycja nagłówka TMX.
"""
from __future__ import annotations

import os
import re
from typing import Dict, List, Optional, Tuple

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
    QPlainTextEdit, QProgressDialog, QPushButton, QSpinBox, QSplitter, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from .theme import setup_splitter

PAGE_SIZE = 100

#: Wzorce „śmieci” usuwanych przy czyszczeniu pamięci.
CLEAN_PATTERNS = {
    "Tagi HTML/XML (<b>, </i>)": re.compile(r"</?[A-Za-z][^>]*>"),
    "Znaczniki {ZMIENNA}": re.compile(r"\{[^}]{0,60}\}"),
    "Nawiasy [TAG]": re.compile(r"\[[^\]]{0,60}\]"),
    "Podwójne spacje": re.compile(r"[ \t]{2,}"),
}


class TMXEditorDialog(QDialog):
    """Okno edytora pamięci tłumaczeń."""

    def __init__(self, app, parent=None) -> None:
        super().__init__(parent)
        self.app = app
        #: Robocza lista wpisów: [source, target, source_lang, target_lang]
        self.entries: List[List[str]] = []
        self.filtered: List[int] = []
        self.page = 0
        self.current_file: Optional[str] = None
        self.dirty = False
        self._loading = False

        self.setWindowTitle("📝 Edytor pamięci TM / TMX")
        self.resize(1250, 780)
        self._build_ui()
        self.load_from_project()

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        # --- pasek narzędzi -------------------------------------------
        toolbar = QHBoxLayout()
        for text, tip, slot in (
            ("📂 Otwórz TMX", "Wczytaj plik TMX do edycji", self.open_tmx),
            ("💾 Zapisz jako TMX", "Zapisz zawartość do pliku TMX", self.save_as_tmx),
            ("⬇ Wczytaj z projektu", "Wczytaj pamięć bieżącego projektu", self.load_from_project),
            ("⬆ Zapisz do projektu", "Nadpisz pamięć projektu zawartością edytora", self.save_to_project),
        ):
            btn = QPushButton(text)
            btn.setToolTip(tip)
            btn.clicked.connect(slot)
            toolbar.addWidget(btn)
        toolbar.addStretch(1)
        self.header_label = QLabel("")
        toolbar.addWidget(self.header_label)
        layout.addLayout(toolbar)

        # --- filtr ------------------------------------------------------
        filter_box = QGroupBox("🔍 Filtrowanie")
        fl = QHBoxLayout(filter_box)
        self.filter_source = QLineEdit()
        self.filter_source.setPlaceholderText("filtruj tekst źródłowy…")
        self.filter_source.textChanged.connect(self.apply_filters)
        self.filter_target = QLineEdit()
        self.filter_target.setPlaceholderText("filtruj tłumaczenie…")
        self.filter_target.textChanged.connect(self.apply_filters)
        self.case_sensitive = QCheckBox("Wielkość liter")
        self.case_sensitive.stateChanged.connect(self.apply_filters)
        self.only_problems = QCheckBox("Tylko problematyczne")
        self.only_problems.setToolTip("Puste wpisy, duplikaty lub tłumaczenie identyczne ze źródłem")
        self.only_problems.stateChanged.connect(self.apply_filters)
        fl.addWidget(QLabel("Źródło:"))
        fl.addWidget(self.filter_source, 1)
        fl.addWidget(QLabel("Cel:"))
        fl.addWidget(self.filter_target, 1)
        fl.addWidget(self.case_sensitive)
        fl.addWidget(self.only_problems)
        clear_btn = QPushButton("Wyczyść")
        clear_btn.clicked.connect(self.clear_filters)
        fl.addWidget(clear_btn)
        layout.addWidget(filter_box)

        splitter = QSplitter(Qt.Orientation.Vertical)

        # --- panel edycji (nad siatką, jak w Supervertaler) -------------
        edit_box = QGroupBox("✏️ Edycja zaznaczonej jednostki")
        el = QVBoxLayout(edit_box)
        row = QHBoxLayout()
        row.addWidget(QLabel("Źródło:"))
        self.edit_source = QPlainTextEdit()
        self.edit_source.setMaximumHeight(70)
        row.addWidget(self.edit_source, 1)
        row.addWidget(QLabel("Tłumaczenie:"))
        self.edit_target = QPlainTextEdit()
        self.edit_target.setMaximumHeight(70)
        row.addWidget(self.edit_target, 1)
        el.addLayout(row)

        buttons = QHBoxLayout()
        for text, slot in (
            ("💾 Zapisz zmiany", self.save_current_edit),
            ("➕ Dodaj wpis", self.add_entry),
            ("🗑️ Usuń zaznaczone", self.delete_selected),
            ("📋 Kopiuj źródło → cel", self.copy_source_to_target),
        ):
            b = QPushButton(text)
            b.clicked.connect(slot)
            buttons.addWidget(b)
        buttons.addStretch(1)
        el.addLayout(buttons)
        splitter.addWidget(edit_box)

        # --- siatka -----------------------------------------------------
        grid_widget = QWidget()
        gl = QVBoxLayout(grid_widget)
        gl.setContentsMargins(0, 0, 0, 0)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Tekst źródłowy", "Tłumaczenie", "Język źr.", "Język doc."])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(2, 90)
        self.table.setColumnWidth(3, 90)
        self.table.itemSelectionChanged.connect(self._on_selection)
        gl.addWidget(self.table)

        # --- stronicowanie ---------------------------------------------
        pager = QHBoxLayout()
        first = QPushButton("⏮")
        prev = QPushButton("◀ Poprzednia")
        nxt = QPushButton("Następna ▶")
        last = QPushButton("⏭")
        first.clicked.connect(lambda: self.go_page(0))
        prev.clicked.connect(lambda: self.go_page(self.page - 1))
        nxt.clicked.connect(lambda: self.go_page(self.page + 1))
        last.clicked.connect(lambda: self.go_page(self.page_count - 1))
        self.page_label = QLabel("")
        for wdg in (first, prev):
            pager.addWidget(wdg)
        pager.addWidget(self.page_label)
        for wdg in (nxt, last):
            pager.addWidget(wdg)
        pager.addStretch(1)
        self.status = QLabel("")
        pager.addWidget(self.status)
        gl.addLayout(pager)
        splitter.addWidget(grid_widget)
        splitter.setStretchFactor(1, 4)
        setup_splitter(splitter, minimums=[120, 160])
        layout.addWidget(splitter, 1)

        # --- narzędzia porządkowe --------------------------------------
        tools = QHBoxLayout()
        for text, tip, slot in (
            ("🧹 Usuń duplikaty", "Usuwa powtórzone pary źródło/tłumaczenie", self.remove_duplicates),
            ("🚮 Usuń puste", "Usuwa wpisy bez źródła lub tłumaczenia", self.remove_empty),
            ("✂️ Przytnij spacje", "Usuwa zbędne spacje na początku i końcu", self.trim_spaces),
            ("🏷️ Wyczyść tagi…", "Usuwa wybrane znaczniki formatowania", self.clean_tags),
            ("🔄 Znajdź i zamień…", "Zamiana tekstu w całej pamięci", self.find_replace),
            ("📊 Statystyki", "Podsumowanie zawartości pamięci", self.show_statistics),
        ):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(slot)
            tools.addWidget(b)
        tools.addStretch(1)
        layout.addLayout(tools)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(self.reject)
        layout.addWidget(bb)

    # ------------------------------------------------------------ dane
    @property
    def page_count(self) -> int:
        return max(1, (len(self.filtered) + PAGE_SIZE - 1) // PAGE_SIZE)

    def load_from_project(self) -> None:
        if not self.app.tm.is_initialized:
            QMessageBox.information(self, "Edytor TM", "Najpierw otwórz projekt.")
            return
        self.entries = [
            [src, tgt, sl or "en", tl or "pl"]
            for src, tgt, sl, tl, _uc in self.app.tm.all_entries()
        ]
        self.current_file = None
        self.dirty = False
        self.header_label.setText("Źródło: pamięć bieżącego projektu")
        self.apply_filters()

    def save_to_project(self) -> None:
        if not self.app.tm.is_initialized:
            QMessageBox.information(self, "Edytor TM", "Brak otwartego projektu.")
            return
        if QMessageBox.question(
            self, "Zapis do projektu",
            f"Zastąpić pamięć projektu zawartością edytora ({len(self.entries)} wpisów)?",
        ) != QMessageBox.StandardButton.Yes:
            return
        self.app.tm.clear()
        rows = [(e[0], e[1], e[2], e[3]) for e in self.entries if e[0].strip() and e[1].strip()]
        self.app.tm.add_many(rows)
        self.dirty = False
        self.app.tm_tab.refresh()
        self.app.update_status()
        QMessageBox.information(self, "Edytor TM", f"Zapisano {len(rows)} wpisów do pamięci projektu.")

    def open_tmx(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Otwórz plik TMX", "", "Pliki TMX (*.tmx)")
        if not path:
            return
        from ..core.tm import TranslationMemory

        temp = TranslationMemory()
        import tempfile

        temp.init_for_project(tempfile.mkdtemp())
        progress = QProgressDialog("Wczytywanie TMX…", None, 0, 100, self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        try:
            temp.import_tmx(path, lambda p: (progress.setValue(p)))
            self.entries = [
                [src, tgt, sl or "en", tl or "pl"] for src, tgt, sl, tl, _uc in temp.all_entries()
            ]
            self.current_file = path
            self.dirty = False
            self.header_label.setText(f"Plik: {os.path.basename(path)}")
            self.apply_filters()
        except Exception as exc:
            QMessageBox.critical(self, "Błąd", f"Nie udało się wczytać pliku:\n{exc}")
        finally:
            progress.close()
            temp.close()

    def save_as_tmx(self) -> None:
        project = self.app.project
        default = os.path.join(project.export_path, "pamiec.tmx") if project else "pamiec.tmx"
        path, _ = QFileDialog.getSaveFileName(self, "Zapisz jako TMX", default, "Pliki TMX (*.tmx)")
        if not path:
            return
        from ..core.tm import _xml_attr, _xml_escape

        try:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write('<?xml version="1.0" encoding="UTF-8"?>\n<tmx version="1.4">\n')
                srclang = self.entries[0][2] if self.entries else "en"
                fh.write(
                    '  <header creationtool="SuperCAT" creationtoolversion="1.0" segtype="sentence" '
                    f'o-tmf="SuperCAT" adminlang="en" srclang="{_xml_attr(srclang)}" datatype="plaintext"/>\n'
                    "  <body>\n"
                )
                for src, tgt, sl, tl in self.entries:
                    fh.write("    <tu>\n")
                    fh.write(f'      <tuv xml:lang="{_xml_attr(sl)}"><seg>{_xml_escape(src)}</seg></tuv>\n')
                    fh.write(f'      <tuv xml:lang="{_xml_attr(tl)}"><seg>{_xml_escape(tgt)}</seg></tuv>\n')
                    fh.write("    </tu>\n")
                fh.write("  </body>\n</tmx>\n")
            self.dirty = False
            QMessageBox.information(self, "Zapis TMX", f"Zapisano {len(self.entries)} jednostek:\n{path}")
        except Exception as exc:
            QMessageBox.critical(self, "Błąd", str(exc))

    # ----------------------------------------------------------- filtry
    def apply_filters(self) -> None:
        fs = self.filter_source.text().strip()
        ft = self.filter_target.text().strip()
        cs = self.case_sensitive.isChecked()
        problems_only = self.only_problems.isChecked()

        seen: Dict[Tuple[str, str], int] = {}
        duplicates: set[int] = set()
        if problems_only:
            for i, (src, tgt, _sl, _tl) in enumerate(self.entries):
                key = (src.strip().lower(), tgt.strip().lower())
                if key in seen:
                    duplicates.add(i)
                else:
                    seen[key] = i

        self.filtered = []
        for i, (src, tgt, _sl, _tl) in enumerate(self.entries):
            hay_s, hay_t = (src, tgt) if cs else (src.lower(), tgt.lower())
            needle_s, needle_t = (fs, ft) if cs else (fs.lower(), ft.lower())
            if fs and needle_s not in hay_s:
                continue
            if ft and needle_t not in hay_t:
                continue
            if problems_only:
                bad = (not src.strip() or not tgt.strip()
                       or src.strip() == tgt.strip() or i in duplicates)
                if not bad:
                    continue
            self.filtered.append(i)
        self.page = 0
        self.refresh_table()

    def clear_filters(self) -> None:
        self.filter_source.clear()
        self.filter_target.clear()
        self.only_problems.setChecked(False)
        self.apply_filters()

    def go_page(self, page: int) -> None:
        self.page = max(0, min(page, self.page_count - 1))
        self.refresh_table()

    def refresh_table(self) -> None:
        self._loading = True
        start = self.page * PAGE_SIZE
        chunk = self.filtered[start:start + PAGE_SIZE]
        self.table.setRowCount(len(chunk))
        for row, index in enumerate(chunk):
            src, tgt, sl, tl = self.entries[index]
            items = [QTableWidgetItem(src), QTableWidgetItem(tgt),
                     QTableWidgetItem(sl), QTableWidgetItem(tl)]
            items[0].setData(Qt.ItemDataRole.UserRole, index)
            if not tgt.strip() or src.strip() == tgt.strip():
                for it in items:
                    it.setForeground(QColor("#ef5350"))
            for col, item in enumerate(items):
                self.table.setItem(row, col, item)
        self._loading = False
        self.page_label.setText(f"Strona {self.page + 1} / {self.page_count}")
        self.status.setText(
            f"Wyświetlono {len(chunk)} z {len(self.filtered)} (w pamięci: {len(self.entries)})"
            + ("  •  niezapisane zmiany" if self.dirty else "")
        )

    # ------------------------------------------------------------ edycja
    def _selected_indices(self) -> List[int]:
        out = []
        for model_index in self.table.selectionModel().selectedRows() if self.table.selectionModel() else []:
            item = self.table.item(model_index.row(), 0)
            if item is not None:
                out.append(item.data(Qt.ItemDataRole.UserRole))
        return out

    def _on_selection(self) -> None:
        if self._loading:
            return
        indices = self._selected_indices()
        if len(indices) == 1:
            src, tgt, _sl, _tl = self.entries[indices[0]]
            self.edit_source.setPlainText(src)
            self.edit_target.setPlainText(tgt)

    def save_current_edit(self) -> None:
        indices = self._selected_indices()
        if len(indices) != 1:
            QMessageBox.information(self, "Edycja", "Zaznacz dokładnie jeden wiersz.")
            return
        i = indices[0]
        self.entries[i][0] = self.edit_source.toPlainText()
        self.entries[i][1] = self.edit_target.toPlainText()
        self.dirty = True
        self.refresh_table()

    def add_entry(self) -> None:
        src = self.edit_source.toPlainText().strip()
        tgt = self.edit_target.toPlainText().strip()
        if not src or not tgt:
            QMessageBox.information(self, "Dodaj wpis", "Wypełnij pole źródłowe i tłumaczenie.")
            return
        project = self.app.project
        self.entries.append([src, tgt,
                             project.source_lang if project else "en",
                             project.target_lang if project else "pl"])
        self.dirty = True
        self.apply_filters()

    def delete_selected(self) -> None:
        indices = sorted(self._selected_indices(), reverse=True)
        if not indices:
            return
        if QMessageBox.question(self, "Usuń", f"Usunąć {len(indices)} zaznaczonych wpisów?") \
                != QMessageBox.StandardButton.Yes:
            return
        for i in indices:
            del self.entries[i]
        self.dirty = True
        self.apply_filters()

    def copy_source_to_target(self) -> None:
        indices = self._selected_indices()
        for i in indices:
            self.entries[i][1] = self.entries[i][0]
        if indices:
            self.dirty = True
            self.refresh_table()

    # -------------------------------------------------------- porządki
    def remove_duplicates(self) -> None:
        seen: set[Tuple[str, str]] = set()
        kept: List[List[str]] = []
        for entry in self.entries:
            key = (entry[0].strip().lower(), entry[1].strip().lower())
            if key in seen:
                continue
            seen.add(key)
            kept.append(entry)
        removed = len(self.entries) - len(kept)
        self.entries = kept
        self.dirty = self.dirty or removed > 0
        self.apply_filters()
        QMessageBox.information(self, "Duplikaty", f"Usunięto {removed} powtórzonych wpisów.")

    def remove_empty(self) -> None:
        before = len(self.entries)
        self.entries = [e for e in self.entries if e[0].strip() and e[1].strip()]
        removed = before - len(self.entries)
        self.dirty = self.dirty or removed > 0
        self.apply_filters()
        QMessageBox.information(self, "Puste wpisy", f"Usunięto {removed} pustych wpisów.")

    def trim_spaces(self) -> None:
        count = 0
        for entry in self.entries:
            new_src = re.sub(r"[ \t]{2,}", " ", entry[0].strip())
            new_tgt = re.sub(r"[ \t]{2,}", " ", entry[1].strip())
            if new_src != entry[0] or new_tgt != entry[1]:
                entry[0], entry[1] = new_src, new_tgt
                count += 1
        self.dirty = self.dirty or count > 0
        self.refresh_table()
        QMessageBox.information(self, "Spacje", f"Poprawiono {count} wpisów.")

    def clean_tags(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Wyczyść znaczniki")
        dl = QVBoxLayout(dialog)
        dl.addWidget(QLabel("Zaznacz elementy do usunięcia z pamięci:"))
        boxes = {}
        for label in CLEAN_PATTERNS:
            cb = QCheckBox(label)
            dl.addWidget(cb)
            boxes[label] = cb
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dialog.accept)
        bb.rejected.connect(dialog.reject)
        dl.addWidget(bb)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        chosen = [CLEAN_PATTERNS[k] for k, cb in boxes.items() if cb.isChecked()]
        if not chosen:
            return
        count = 0
        for entry in self.entries:
            src, tgt = entry[0], entry[1]
            for pattern in chosen:
                src = pattern.sub(" " if pattern.pattern.startswith("[ ") else "", src)
                tgt = pattern.sub(" " if pattern.pattern.startswith("[ ") else "", tgt)
            src, tgt = re.sub(r"\s{2,}", " ", src).strip(), re.sub(r"\s{2,}", " ", tgt).strip()
            if src != entry[0] or tgt != entry[1]:
                entry[0], entry[1] = src, tgt
                count += 1
        self.dirty = self.dirty or count > 0
        self.refresh_table()
        QMessageBox.information(self, "Czyszczenie", f"Zmieniono {count} wpisów.")

    def find_replace(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Znajdź i zamień w pamięci")
        form = QFormLayout(dialog)
        find_edit = QLineEdit()
        repl_edit = QLineEdit()
        scope = QComboBox()
        scope.addItems(["Źródło i tłumaczenie", "Tylko źródło", "Tylko tłumaczenie"])
        use_regex = QCheckBox("Wyrażenie regularne")
        form.addRow("Znajdź:", find_edit)
        form.addRow("Zamień na:", repl_edit)
        form.addRow("Zakres:", scope)
        form.addRow(use_regex)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dialog.accept)
        bb.rejected.connect(dialog.reject)
        form.addRow(bb)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        needle, replacement = find_edit.text(), repl_edit.text()
        if not needle:
            return
        pattern = needle if use_regex.isChecked() else re.escape(needle)
        try:
            rx = re.compile(pattern)
        except re.error as exc:
            QMessageBox.critical(self, "Błąd", f"Nieprawidłowe wyrażenie: {exc}")
            return

        mode = scope.currentIndex()
        count = 0
        for entry in self.entries:
            changed = False
            if mode in (0, 1):
                new = rx.sub(replacement, entry[0])
                if new != entry[0]:
                    entry[0], changed = new, True
            if mode in (0, 2):
                new = rx.sub(replacement, entry[1])
                if new != entry[1]:
                    entry[1], changed = new, True
            if changed:
                count += 1
        self.dirty = self.dirty or count > 0
        self.apply_filters()
        QMessageBox.information(self, "Zamiana", f"Zmieniono {count} wpisów.")

    def show_statistics(self) -> None:
        total = len(self.entries)
        if not total:
            QMessageBox.information(self, "Statystyki", "Pamięć jest pusta.")
            return
        empty = sum(1 for e in self.entries if not e[0].strip() or not e[1].strip())
        same = sum(1 for e in self.entries if e[0].strip() and e[0].strip() == e[1].strip())
        keys = [(e[0].strip().lower(), e[1].strip().lower()) for e in self.entries]
        duplicates = len(keys) - len(set(keys))
        avg_src = sum(len(e[0]) for e in self.entries) / total
        avg_tgt = sum(len(e[1]) for e in self.entries) / total
        pairs: Dict[str, int] = {}
        for e in self.entries:
            pairs[f"{e[2]} → {e[3]}"] = pairs.get(f"{e[2]} → {e[3]}", 0) + 1
        lines = [
            f"Jednostek tłumaczeniowych: {total}",
            f"Puste (brak źródła lub celu): {empty}",
            f"Tłumaczenie identyczne ze źródłem: {same}",
            f"Duplikaty: {duplicates}",
            f"Średnia długość źródła: {avg_src:.1f} znaków",
            f"Średnia długość tłumaczenia: {avg_tgt:.1f} znaków",
            "",
            "Pary językowe:",
        ]
        lines += [f"   {k}: {v}" for k, v in sorted(pairs.items(), key=lambda kv: -kv[1])]
        QMessageBox.information(self, "Statystyki pamięci", "\n".join(lines))

    # ------------------------------------------------------------------
    def reject(self) -> None:
        if self.dirty:
            answer = QMessageBox.question(
                self, "Niezapisane zmiany",
                "W edytorze są niezapisane zmiany. Zapisać je do pamięci projektu?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                | QMessageBox.StandardButton.Cancel,
            )
            if answer == QMessageBox.StandardButton.Cancel:
                return
            if answer == QMessageBox.StandardButton.Yes:
                self.save_to_project()
        super().reject()
