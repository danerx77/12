"""Zakładka Pamięci tłumaczeń – lista TM, przeglądanie i edycja w miejscu.

Układ wzorowany na sekcji „TMs” z Supervertaler Workbench:
  • **TM List**  – wykaz pamięci projektu (bazy .db i pliki .tmx w folderze tm/),
  • **Browse**   – przeglądanie i edycja wpisów bezpośrednio w tabeli (bez okien),
  • pamięć bieżącego tłumaczenia jest tworzona i zapisywana automatycznie.
"""
from __future__ import annotations

import os
import shutil
from typing import List, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QFileDialog, QGroupBox, QHBoxLayout,
    QHeaderView, QInputDialog, QLabel, QLineEdit, QMessageBox, QProgressDialog,
    QPushButton, QSpinBox, QSplitter, QTableWidget, QTableWidgetItem, QTabWidget,
    QComboBox, QVBoxLayout, QWidget,
)

from ..core import tm_builder


class FileDropTable(QTableWidget):
    """Tabela par plików przyjmująca upuszczone pliki i katalogi.

    Ramka podświetla się na niebiesko, gdy przeciągane pliki nadają się
    do wczytania — inaczej nie wiadomo, czy upuszczenie zadziała.
    """

    files_dropped = pyqtSignal(list)

    def __init__(self, rows: int = 0, columns: int = 0, parent=None) -> None:
        super().__init__(rows, columns, parent)
        self.setAcceptDrops(True)
        self._normal_style = ""

    @staticmethod
    def _usable_paths(event) -> List[str]:
        paths = []
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if not path:
                continue
            if os.path.isdir(path) or path.lower().endswith(tm_builder.TEXT_EXTENSIONS):
                paths.append(path)
        return paths

    def _highlight(self, active: bool) -> None:
        self.setStyleSheet(
            "QTableWidget { border: 2px dashed #2f7fd1;"
            " background: rgba(47,127,209,0.08); }"
            if active else self._normal_style)

    def dragEnterEvent(self, event) -> None:  # noqa: N802 (Qt API)
        if event.mimeData().hasUrls() and self._usable_paths(event):
            event.acceptProposedAction()
            self._highlight(True)
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self._highlight(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802
        self._highlight(False)
        paths = self._usable_paths(event)
        if paths:
            event.acceptProposedAction()
            self.files_dropped.emit(paths)
        else:
            event.ignore()


class TMTab(QWidget):
    def __init__(self, app) -> None:
        super().__init__()
        self.app = app
        self._import_worker = None
        self._loading = False
        self._build_ui()

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_list_tab(), "📋 Lista pamięci")
        self.tabs.addTab(self._build_browse_tab(), "📖 Przeglądaj i edytuj")
        self.tabs.addTab(self._build_generator_tab(), "🏗️ Generator TM z plików")
        self.tabs.currentChanged.connect(lambda _i: self.refresh())
        layout.addWidget(self.tabs)

    # --- zakładka: lista pamięci --------------------------------------
    def _build_list_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        self.list_info = QLabel("Pamięci tłumaczeń projektu")
        self.list_info.setStyleSheet("font-weight: bold;")
        layout.addWidget(self.list_info)

        self.tm_list = QTableWidget(0, 4)
        self.tm_list.setHorizontalHeaderLabels(["Pamięć", "Typ", "Jednostek / rozmiar", "Ścieżka"])
        self.tm_list.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tm_list.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tm_list.setAlternatingRowColors(True)
        self.tm_list.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.tm_list.setColumnWidth(0, 260)
        self.tm_list.setColumnWidth(1, 150)
        self.tm_list.setColumnWidth(2, 170)
        layout.addWidget(self.tm_list)

        buttons = QHBoxLayout()
        for text, tip, slot in (
            ("📥 Dołącz plik TMX", "Zaimportuj plik TMX do pamięci projektu", self.import_tmx),
            ("📂 Dodaj TMX do folderu tm/", "Skopiuj plik TMX do projektu", self.attach_tmx_file),
            ("📤 Eksportuj TMX", "Zapisz pamięć projektu jako plik TMX", self.export_tmx),
            ("📝 Edytor TMX", "Pełny edytor pamięci / plików TMX", lambda: self.app.open_tmx_editor()),
            ("🔄 Odśwież", "", self.refresh),
        ):
            btn = QPushButton(text)
            if tip:
                btn.setToolTip(tip)
            btn.clicked.connect(slot)
            buttons.addWidget(btn)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        note = QLabel(
            "💡 Pamięć bieżącego tłumaczenia (<b>project_tm.db</b>) tworzona jest automatycznie "
            "przy zakładaniu projektu. Każdy zatwierdzony segment (Ctrl+Enter) jest do niej "
            "zapisywany, a pliki TMX z folderu <b>tm/</b> wczytywane przy otwarciu projektu."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        return widget

    # --- zakładka: przeglądanie i edycja ------------------------------
    def _build_browse_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        top = QHBoxLayout()
        self.info = QLabel("Pamięć tłumaczeń: brak projektu")
        self.info.setStyleSheet("font-weight: bold;")
        top.addWidget(self.info)
        top.addStretch(1)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("szukaj w TM (źródło lub tłumaczenie)…")
        self.search_edit.textChanged.connect(self.refresh)
        self.search_edit.setMaximumWidth(360)
        top.addWidget(self.search_edit)
        layout.addLayout(top)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Tekst źródłowy", "Tłumaczenie", "Język źr.", "Język doc.", "Użycia"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        # Edycja w miejscu: dwuklik lub Enter, bez okien dialogowych.
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.AnyKeyPressed
        )
        self.table.itemChanged.connect(self._on_item_changed)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)

        hint = QLabel("💡 Kliknij dwukrotnie komórkę, aby edytować wpis bezpośrednio w tabeli.")
        hint.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(hint)

        buttons = QHBoxLayout()
        for text, slot in (
            ("➕ Dodaj wpis", self.add_entry),
            ("🗑️ Usuń", self.delete_entry),
            ("📥 Importuj TMX", self.import_tmx),
            ("📤 Eksportuj TMX", self.export_tmx),
            ("📝 Edytor TMX", lambda: self.app.open_tmx_editor()),
            ("🔄 Odśwież", self.refresh),
            ("🧹 Wyczyść TM", self.clear_tm),
        ):
            btn = QPushButton(text)
            btn.clicked.connect(slot)
            buttons.addWidget(btn)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        return widget

    # ------------------------------------------------------------------
    # --- zakładka: generator TM z plików -------------------------------
    def _build_generator_tab(self) -> QWidget:
        """Tworzenie pamięci TM z par plików: jeden język na plik.

        Najczęstszy scenariusz przy tłumaczeniu gier: `text_en.txt` i
        `text_pl.txt` z tym samym tekstem, wiersz w wiersz. Program paruje
        pliki po nazwie, sprawdza, czy liczba wierszy się zgadza, i dopiero
        wtedy pozwala zapisać wpisy do pamięci.
        """
        widget = QWidget()
        layout = QVBoxLayout(widget)

        intro = QLabel(
            "Tworzy pamięć TM z <b>par plików</b>: jeden plik w języku źródłowym, "
            "drugi z tłumaczeniem. <b>Wiersz N musi odpowiadać wierszowi N</b>, "
            "więc liczba wierszy w obu plikach musi być taka sama.<br>"
            "<b>Nazwy plików mogą być dowolne</b> — <code>1.txt</code> i "
            "<code>2.txt</code> też zadziałają. Język i kodowanie każdej strony "
            "ustawisz w tabeli; nazwy typu <code>text_en.txt</code> są tylko "
            "podpowiedzią przy automatycznym parowaniu."
        )
        intro.setWordWrap(True)
        intro.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(intro)

        self.gen_table = FileDropTable(0, 6)
        self.gen_table.setHorizontalHeaderLabels([
            "Plik źródłowy", "Język", "Plik z tłumaczeniem", "Język",
            "Kodowanie", "Stan"])
        self.gen_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        self.gen_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch)
        # „Stan” niesie najważniejszą informację (np. „różnica 1 wiersz (2 / 3)”),
        # więc dostaje tyle miejsca, ile potrzebuje – ucinany był bezużyteczny.
        for column in (1, 3, 4, 5):
            self.gen_table.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents)
        self.gen_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.gen_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.gen_table.files_dropped.connect(self.add_generator_files)
        self.gen_table.itemSelectionChanged.connect(self._preview_generator_pair)
        layout.addWidget(self.gen_table, 2)

        self.gen_hint = QLabel(
            "⬇ Przeciągnij tutaj pliki lub katalog — albo użyj przycisku „➕ Dodaj pliki”.")
        self.gen_hint.setStyleSheet("color: gray;")
        layout.addWidget(self.gen_hint)

        buttons = QHBoxLayout()
        add_btn = QPushButton("➕ Dodaj pliki…")
        add_btn.clicked.connect(self.pick_generator_files)
        add_dir = QPushButton("📁 Dodaj katalog…")
        add_dir.clicked.connect(self.pick_generator_folder)
        swap_btn = QPushButton("⇄ Zamień strony")
        swap_btn.setToolTip("Zamienia plik źródłowy z docelowym w zaznaczonych wierszach")
        swap_btn.clicked.connect(self.swap_generator_sides)
        remove_btn = QPushButton("➖ Usuń zaznaczone")
        remove_btn.clicked.connect(self.remove_generator_rows)
        clear_btn = QPushButton("🧹 Wyczyść")
        clear_btn.clicked.connect(self.clear_generator)
        for button in (add_btn, add_dir, swap_btn, remove_btn, clear_btn):
            buttons.addWidget(button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        options = QGroupBox("Co pominąć przy zestawianiu")
        opt_layout = QHBoxLayout(options)
        self.gen_skip_technical = QCheckBox("wiersze techniczne")
        self.gen_skip_technical.setToolTip(
            "Pomija „<<< FILE: … >>>”, komentarze (#, //), [sekcje] i separatory.")
        self.gen_skip_technical.setChecked(True)
        self.gen_skip_identical = QCheckBox("identyczne po obu stronach")
        self.gen_skip_identical.setToolTip(
            "Wiersz nieprzetłumaczony (np. „OK”) nie wniesie nic do pamięci.")
        self.gen_skip_untranslated = QCheckBox("nieprzetłumaczone (wciąż po angielsku)")
        self.gen_skip_untranslated.setToolTip(
            "Pomija wiersze, w których „tłumaczenie” zostało w języku źródłowym.\n"
            "Program rozpoznaje to po polskich znakach i typowych wyrazach —\n"
            "nazwy własne (CINNABAR GYM, PP UP) nie są przez to odrzucane.")
        self.gen_skip_strict = QCheckBox("wymagaj zgodnej liczby wierszy")
        self.gen_skip_strict.setToolTip(
            "Zalecane. Przy różnej liczbie wierszy tłumaczenia przesuwają się\n"
            "o jeden i cała pamięć staje się bezużyteczna.")
        self.gen_skip_strict.setChecked(True)
        self.gen_min_len = QSpinBox()
        self.gen_min_len.setRange(1, 100)
        self.gen_min_len.setValue(1)
        self.gen_min_len.setMaximumWidth(70)
        self.gen_min_len.setToolTip("Pomija bardzo krótkie teksty źródłowe.")
        for widget_ in (self.gen_skip_technical, self.gen_skip_identical,
                        self.gen_skip_untranslated, self.gen_skip_strict):
            widget_.stateChanged.connect(self._preview_generator_pair)
            opt_layout.addWidget(widget_)
        opt_layout.addWidget(QLabel("min. długość:"))
        opt_layout.addWidget(self.gen_min_len)
        opt_layout.addStretch(1)
        layout.addWidget(options)

        preview_row = QHBoxLayout()
        preview_row.addWidget(QLabel("Podgląd zestawienia (zaznacz parę powyżej):"))
        preview_row.addStretch(1)
        self.gen_show_skipped = QCheckBox("pokaż pomijane wiersze")
        self.gen_show_skipped.setToolTip(
            "Wyświetla także wiersze, które NIE trafią do pamięci —\n"
            "puste, techniczne, identyczne i nieprzetłumaczone —\n"
            "wraz z powodem pominięcia.")
        self.gen_show_skipped.setChecked(True)
        self.gen_show_skipped.stateChanged.connect(self._preview_generator_pair)
        preview_row.addWidget(self.gen_show_skipped)
        layout.addLayout(preview_row)

        self.gen_preview = QTableWidget(0, 4)
        self.gen_preview.setHorizontalHeaderLabels(
            ["#", "Źródło", "Tłumaczenie", "Stan"])
        self.gen_preview.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch)
        self.gen_preview.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch)
        self.gen_preview.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.ResizeToContents)
        self.gen_preview.setColumnWidth(0, 50)
        self.gen_preview.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.gen_preview, 1)

        run_row = QHBoxLayout()
        self.gen_summary = QLabel("")
        self.gen_summary.setWordWrap(True)
        run_row.addWidget(self.gen_summary, 1)
        build_btn = QPushButton("🏗️ Zbuduj pamięć TM")
        build_btn.setToolTip("Dopisuje zestawione pary do pamięci projektu")
        build_btn.clicked.connect(self.build_tm_from_files)
        export_btn = QPushButton("💾 Zapisz jako TMX…")
        export_btn.setToolTip("Zapisuje zestawienie do pliku TMX bez dopisywania do pamięci")
        export_btn.clicked.connect(self.export_generated_tmx)
        run_row.addWidget(build_btn)
        run_row.addWidget(export_btn)
        layout.addLayout(run_row)

        self._gen_pairs: List[tm_builder.FilePair] = []
        #: Pliki wczytane, ale jeszcze bez partnera — czekają na drugi język.
        self._gen_waiting: List[str] = []
        return widget

    # --- generator: obsługa listy plików -------------------------------
    def _project_langs(self):
        project = getattr(self.app, "project", None)
        return ((project.source_lang if project else "en") or "en",
                (project.target_lang if project else "pl") or "pl")

    def pick_generator_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Wybierz pliki dwujęzyczne", "",
            "Pliki tekstowe (*.txt *.inc *.po *.csv *.tsv *.md *.srt *.lang *.ini);;"
            "Wszystkie pliki (*)")
        if paths:
            self.add_generator_files(paths)

    def pick_generator_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Wybierz katalog z plikami")
        if folder:
            self.add_generator_files([folder])

    def add_generator_files(self, paths) -> None:
        """Dodaje pliki (lub zawartość katalogów) i paruje je po nazwie."""
        collected: List[str] = []
        for path in paths:
            if os.path.isdir(path):
                for root, _dirs, files in os.walk(path):
                    collected.extend(
                        os.path.join(root, name) for name in files
                        if name.lower().endswith(tm_builder.TEXT_EXTENSIONS))
            elif os.path.isfile(path):
                collected.append(path)

        known = {p.source_path for p in self._gen_pairs}
        known |= {p.target_path for p in self._gen_pairs}
        # Pliki bez pary trzymamy osobno: gdy użytkownik przeciąga po jednym
        # (np. wersję EN, a chwilę potem PL z innego katalogu), pierwszy musi
        # doczekać na partnera. Wcześniej przepadał i parowanie nigdy nie
        # dochodziło do skutku — lista zostawała pusta.
        known |= set(self._gen_waiting)
        collected = [p for p in collected if p not in known]
        if not collected:
            self.gen_hint.setText("Nie znaleziono nowych plików tekstowych.")
            return

        source_lang, target_lang = self._project_langs()
        # Parujemy razem z już wczytanymi – plik dorzucony później musi
        # znaleźć partnera wśród wcześniejszych.
        all_paths = sorted(known | set(collected))
        pairs, unmatched = tm_builder.pair_files(all_paths, source_lang, target_lang)
        self._gen_pairs = pairs
        self._gen_waiting = list(unmatched)
        self._fill_generator_table()

        if unmatched:
            names = ", ".join(os.path.basename(p) for p in unmatched[:5])
            more = f" i {len(unmatched) - 5} więcej" if len(unmatched) > 5 else ""
            waiting = (f"⏳ Czeka na parę: {names}{more}. "
                       "Przeciągnij drugi plik (może być z innego katalogu).")
            if pairs:
                waiting = f"✅ Sparowano {len(pairs)} par.  •  {waiting}"
            self.gen_hint.setText(waiting)
            self.gen_hint.setStyleSheet("color: #ffb74d;")
        else:
            self.gen_hint.setText(
                f"✅ Sparowano {len(pairs)} par. Sprawdź języki i kodowanie "
                "w tabeli, potem zaznacz parę, aby zobaczyć podgląd.")
            self.gen_hint.setStyleSheet("color: #66bb6a;")

    #: Języki proponowane na listach – kolejność od najczęstszych.
    LANG_CHOICES = [
        ("en", "angielski"), ("pl", "polski"), ("de", "niemiecki"),
        ("fr", "francuski"), ("es", "hiszpański"), ("it", "włoski"),
        ("nl", "niderlandzki"), ("cs", "czeski"), ("sk", "słowacki"),
        ("uk", "ukraiński"), ("ru", "rosyjski"), ("pt", "portugalski"),
        ("sv", "szwedzki"), ("da", "duński"), ("fi", "fiński"),
        ("no", "norweski"), ("hu", "węgierski"), ("ro", "rumuński"),
        ("tr", "turecki"), ("el", "grecki"), ("ja", "japoński"),
        ("ko", "koreański"), ("zh", "chiński"), ("ar", "arabski"),
    ]

    def _language_combo(self, current: str, row: int, side: str) -> QComboBox:
        """Lista wyboru języka dla jednej strony pary (edytowalna)."""
        combo = QComboBox()
        combo.setEditable(True)          # można wpisać kod spoza listy
        combo.setMaximumWidth(150)
        for code, name in self.LANG_CHOICES:
            combo.addItem(f"{code} — {name}", code)
        code = (current or "").lower()
        index = next((i for i in range(combo.count())
                      if combo.itemData(i) == code), -1)
        if index >= 0:
            combo.setCurrentIndex(index)
        else:
            combo.setEditText(code)
        combo.currentTextChanged.connect(
            lambda _t, r=row, s=side, c=combo: self._on_lang_changed(r, s, c))
        return combo

    def _encoding_combo(self, current: str, row: int, side: str) -> QComboBox:
        """Lista wyboru kodowania; „auto” rozpoznaje je z zawartości pliku."""
        combo = QComboBox()
        combo.setMaximumWidth(150)
        for code, name in tm_builder.ENCODING_CHOICES:
            combo.addItem(name, code)
        index = next((i for i in range(combo.count())
                      if combo.itemData(i) == (current or tm_builder.AUTO_ENCODING)), 0)
        combo.setCurrentIndex(index)
        combo.currentIndexChanged.connect(
            lambda _i, r=row, s=side, c=combo: self._on_encoding_changed(r, s, c))
        return combo

    def _on_lang_changed(self, row: int, side: str, combo: QComboBox) -> None:
        if row >= len(self._gen_pairs):
            return
        data = combo.currentData()
        # Pole jest edytowalne: gdy użytkownik wpisał własny kod, bierzemy tekst.
        code = data if data and combo.currentText().startswith(str(data)) \
            else combo.currentText().strip().split(" ")[0].lower()
        pair = self._gen_pairs[row]
        if side == "source":
            pair.source_lang = code
        else:
            pair.target_lang = code

    def _on_encoding_changed(self, row: int, side: str, combo: QComboBox) -> None:
        """Zmiana kodowania wymaga przeliczenia wierszy – plik czyta się inaczej."""
        if row >= len(self._gen_pairs):
            return
        pair = self._gen_pairs[row]
        value = combo.currentData() or tm_builder.AUTO_ENCODING
        if side in ("source", "both"):
            pair.source_encoding = value
        if side in ("target", "both"):
            pair.target_encoding = value
        try:
            pair.recount()
        except Exception as exc:
            self.gen_hint.setText(f"⚠️ Nie udało się odczytać pliku: {exc}")
            self.gen_hint.setStyleSheet("color: #ef5350;")
            return
        self._refresh_generator_status(row)
        self._preview_generator_pair()

    def _refresh_generator_status(self, row: int) -> None:
        """Odświeża samą kolumnę „Stan” – bez przebudowy całej tabeli."""
        if row >= len(self._gen_pairs):
            return
        pair = self._gen_pairs[row]
        status = QTableWidgetItem(pair.status)
        status.setForeground(QColor("#66bb6a" if pair.matches else "#ef5350"))
        self.gen_table.setItem(row, 5, status)
        self._update_generator_summary()

    def _fill_generator_table(self) -> None:
        self.gen_table.setRowCount(len(self._gen_pairs))
        source_lang, target_lang = self._project_langs()
        for row, pair in enumerate(self._gen_pairs):
            source_item = QTableWidgetItem(os.path.basename(pair.source_path))
            source_item.setToolTip(pair.source_path)
            self.gen_table.setItem(row, 0, source_item)
            self.gen_table.setCellWidget(row, 1, self._language_combo(
                pair.source_lang or source_lang, row, "source"))

            target_item = QTableWidgetItem(os.path.basename(pair.target_path))
            target_item.setToolTip(pair.target_path)
            self.gen_table.setItem(row, 2, target_item)
            self.gen_table.setCellWidget(row, 3, self._language_combo(
                pair.target_lang or target_lang, row, "target"))

            # Jedna lista kodowania na parę – w praktyce oba pliki pochodzą
            # z tego samego źródła; „auto” i tak rozpoznaje je osobno.
            self.gen_table.setCellWidget(row, 4, self._encoding_combo(
                pair.source_encoding, row, "both"))

            status = QTableWidgetItem(pair.status)
            status.setForeground(QColor("#66bb6a" if pair.matches else "#ef5350"))
            self.gen_table.setItem(row, 5, status)
        if self._gen_pairs and not self.gen_table.selectedItems():
            self.gen_table.selectRow(0)
        self._update_generator_summary()

    def _generator_options(self) -> "tm_builder.BuildOptions":
        return tm_builder.BuildOptions(
            skip_identical=self.gen_skip_identical.isChecked(),
            skip_technical=self.gen_skip_technical.isChecked(),
            skip_untranslated=self.gen_skip_untranslated.isChecked(),
            require_equal_lines=self.gen_skip_strict.isChecked(),
            min_length=self.gen_min_len.value(),
        )

    def _preview_generator_pair(self) -> None:
        rows = self.gen_table.selectionModel().selectedRows() \
            if self.gen_table.selectionModel() else []
        self.gen_preview.setRowCount(0)
        if not rows or not self._gen_pairs:
            self._update_generator_summary()
            return
        index = rows[0].row()
        if index >= len(self._gen_pairs):
            return
        pair = self._gen_pairs[index]
        show_skipped = self.gen_show_skipped.isChecked()
        try:
            preview = tm_builder.preview_alignment(
                pair, 80, self._generator_options(), show_skipped=show_skipped)
        except Exception as exc:
            self.gen_summary.setText(f"⚠️ Nie udało się odczytać pliku: {exc}")
            return
        self.gen_preview.setRowCount(len(preview))
        for row, (number, source, target, reason) in enumerate(preview):
            self.gen_preview.setItem(row, 0, QTableWidgetItem(str(number)))
            self.gen_preview.setItem(row, 1, QTableWidgetItem(source))
            self.gen_preview.setItem(row, 2, QTableWidgetItem(target))
            state = tm_builder.SKIP_REASONS.get(reason, reason) if reason else "✅ do TM"
            self.gen_preview.setItem(row, 3, QTableWidgetItem(state))
            # Pomijane wiersze na szaro, żeby od razu było widać, co wejdzie
            # do pamięci, a co nie — bez liczenia w podsumowaniu.
            colour = QColor("#8a8f98") if reason else QColor("#81c784")
            for column in range(4):
                item = self.gen_preview.item(row, column)
                if item is not None:
                    item.setForeground(colour)
        self._update_generator_summary()

    def _update_generator_summary(self) -> None:
        if not self._gen_pairs:
            self.gen_summary.setText("Brak plików — przeciągnij je na tabelę powyżej.")
            return
        good = [p for p in self._gen_pairs if p.matches]
        bad = [p for p in self._gen_pairs if not p.matches]
        lines = sum(p.source_lines for p in good)
        text = f"Par plików: {len(self._gen_pairs)}  •  gotowych: {len(good)} " \
               f"({tm_builder.plural_lines(lines)})"
        if bad:
            text += f"  •  ⚠️ z niezgodną liczbą wierszy: {len(bad)}"
        self.gen_summary.setText(text)

    def swap_generator_sides(self) -> None:
        """Zamienia miejscami plik źródłowy i docelowy w zaznaczonych parach."""
        model = self.gen_table.selectionModel()
        rows = [i.row() for i in model.selectedRows()] if model else []
        if not rows:
            QMessageBox.information(self, "Generator TM",
                                    "Zaznacz wiersze, które chcesz odwrócić.")
            return
        for row in rows:
            if row >= len(self._gen_pairs):
                continue
            pair = self._gen_pairs[row]
            pair.source_path, pair.target_path = pair.target_path, pair.source_path
            pair.source_lines, pair.target_lines = pair.target_lines, pair.source_lines
            pair.source_lang, pair.target_lang = pair.target_lang, pair.source_lang
            pair.source_encoding, pair.target_encoding = (
                pair.target_encoding, pair.source_encoding)
        self._fill_generator_table()
        self._preview_generator_pair()

    def remove_generator_rows(self) -> None:
        model = self.gen_table.selectionModel()
        rows = sorted((i.row() for i in model.selectedRows()), reverse=True) \
            if model else []
        for row in rows:
            if row < len(self._gen_pairs):
                self._gen_pairs.pop(row)
        self._fill_generator_table()
        self._preview_generator_pair()

    def clear_generator(self) -> None:
        self._gen_pairs = []
        self._gen_waiting = []
        self.gen_table.setRowCount(0)
        self.gen_preview.setRowCount(0)
        self.gen_hint.setText(
            "⬇ Przeciągnij tutaj pliki lub katalog — albo użyj przycisku „➕ Dodaj pliki”.")
        self.gen_hint.setStyleSheet("color: gray;")
        self._update_generator_summary()

    def _generate_rows(self):
        """Wspólne zestawianie dla „Zbuduj” i „Zapisz jako TMX”."""
        if not self._gen_pairs:
            QMessageBox.information(self, "Generator TM",
                                    "Najpierw dodaj pliki — przeciągnij je na tabelę.")
            return None
        source_lang, target_lang = self._project_langs()
        progress = QProgressDialog("Zestawianie plików…", "Anuluj", 0,
                                   len(self._gen_pairs), self)
        progress.setWindowTitle("Generator TM")
        progress.setMinimumDuration(0)

        def report(done: int, total: int, name: str) -> None:
            progress.setMaximum(total)
            progress.setValue(done)
            if name:
                progress.setLabelText(f"Zestawianie: {name}")
            QApplication.processEvents()

        try:
            result = tm_builder.build_pairs(
                self._gen_pairs, source_lang, target_lang,
                self._generator_options(), report)
        except Exception as exc:
            progress.close()
            QMessageBox.warning(self, "Generator TM",
                                f"Nie udało się zestawić plików:\n{exc}")
            return None
        progress.close()

        if not result.rows:
            details = "\n".join(result.problems[:8]) if result.problems else ""
            QMessageBox.warning(
                self, "Generator TM",
                "Nie powstała żadna para do zapisania.\n\n"
                + (details or "Sprawdź, czy pliki mają zgodną liczbę wierszy."))
            return None
        return result

    def build_tm_from_files(self) -> None:
        """Dopisuje zestawione pary do pamięci projektu."""
        if not self._require_tm():
            return
        result = self._generate_rows()
        if result is None:
            return
        added = self.app.tm.add_many(result.rows)
        self.app.tm.flush()
        self.refresh()
        self.app.update_status()

        message = [f"Dopisano do pamięci: {added} par.", "", result.summary()]
        if result.problems:
            message.extend(["", "Pominięte pliki:"] + result.problems[:8])
        QMessageBox.information(self, "Generator TM", "\n".join(message))

    def export_generated_tmx(self) -> None:
        """Zapisuje zestawienie do pliku TMX, bez ruszania pamięci projektu."""
        result = self._generate_rows()
        if result is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Zapisz jako TMX", "pamiec.tmx", "Pliki TMX (*.tmx)")
        if not path:
            return
        try:
            from ..core.tm import write_tmx

            write_tmx(path, result.rows)
        except Exception as exc:
            QMessageBox.warning(self, "Generator TM", f"Nie udało się zapisać:\n{exc}")
            return
        QMessageBox.information(
            self, "Generator TM",
            f"Zapisano {result.total} par do pliku:\n{path}\n\n{result.summary()}")

    def refresh(self) -> None:
        self._refresh_list()
        self._refresh_browse()

    def _refresh_list(self) -> None:
        project = self.app.project
        rows: List[tuple] = []
        if project:
            db_path = os.path.join(project.tm_path, "project_tm.db")
            if os.path.exists(db_path):
                rows.append((
                    "Pamięć projektu (bieżące tłumaczenie)", "baza SQLite",
                    f"{self.app.tm.size()} jednostek", db_path,
                ))
            listed: set[str] = set()
            if os.path.isdir(project.tm_path):
                for name in sorted(os.listdir(project.tm_path)):
                    if name.lower().endswith(".tmx"):
                        full = os.path.join(project.tm_path, name)
                        size_kb = os.path.getsize(full) / 1024
                        rows.append((name, "plik TMX (folder tm/)", f"{size_kb:,.0f} KB", full))
                        listed.add(os.path.abspath(full))
            # pamięci zaimportowane spoza folderu tm/ – inaczej „znikały” z listy
            for entry in getattr(project, "tm_sources", []) or []:
                full = entry.get("path", "")
                if not full or os.path.abspath(full) in listed:
                    continue
                exists = os.path.exists(full)
                rows.append((
                    os.path.basename(full),
                    "zaimportowany TMX" if exists else "zaimportowany (brak pliku)",
                    f"{entry.get('units', 0)} jednostek", full,
                ))
        self.tm_list.setRowCount(len(rows))
        for r, values in enumerate(rows):
            for c, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if c == 2:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.tm_list.setItem(r, c, item)
        self.list_info.setText(
            f"Pamięci tłumaczeń projektu: {len(rows)}" if rows else "Brak pamięci – otwórz projekt"
        )

    def _refresh_browse(self) -> None:
        tm = self.app.tm
        self._loading = True
        if not tm.is_initialized:
            self.table.setRowCount(0)
            self.info.setText("Pamięć tłumaczeń: brak otwartego projektu")
            self._loading = False
            return
        query = self.search_edit.text().strip()
        rows = tm.search(query, 1000) if query else tm.all_entries(1000)
        self.table.setRowCount(len(rows))
        for r, (src, tgt, sl, tl, uc) in enumerate(rows):
            for c, value in enumerate((src, tgt, sl, tl, str(uc))):
                item = QTableWidgetItem(str(value))
                if c > 1:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if c == 4:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if c == 0:
                    # zapamiętaj oryginał, by wiedzieć, który wpis podmienić
                    item.setData(Qt.ItemDataRole.UserRole, (src, tgt))
                self.table.setItem(r, c, item)
        total = tm.size()
        self.info.setText(
            f"Pamięć tłumaczeń: {total} wpisów"
            + (f" (wyświetlono {len(rows)})" if len(rows) != total else "")
        )
        self._loading = False

    # --------------------------------------------------- edycja w miejscu
    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        """Zapisuje zmianę wprowadzoną bezpośrednio w tabeli."""
        if self._loading or not self.app.tm.is_initialized:
            return
        row = item.row()
        key_item = self.table.item(row, 0)
        if key_item is None:
            return
        original = key_item.data(Qt.ItemDataRole.UserRole)
        if not original:
            return
        old_src, old_tgt = original
        new_src = self.table.item(row, 0).text().strip()
        new_tgt = self.table.item(row, 1).text().strip()
        new_sl = self.table.item(row, 2).text().strip() or "en"
        new_tl = self.table.item(row, 3).text().strip() or "pl"
        if new_src == old_src and new_tgt == old_tgt:
            return
        if not new_src or not new_tgt:
            QMessageBox.information(self, "Edycja TM", "Źródło i tłumaczenie nie mogą być puste.")
            self._refresh_browse()
            return
        self.app.tm.delete(old_src, old_tgt)
        self.app.tm.add(new_src, new_tgt, new_sl, new_tl)
        key_item.setData(Qt.ItemDataRole.UserRole, (new_src, new_tgt))
        self.app.update_status()

    # ------------------------------------------------------------------
    def _selected_row(self):
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows:
            return None
        r = rows[0].row()
        return self.table.item(r, 0).text(), self.table.item(r, 1).text()

    def add_entry(self) -> None:
        if not self._require_tm():
            return
        source, ok = QInputDialog.getText(self, "Nowy wpis TM", "Tekst źródłowy:")
        if not ok or not source.strip():
            return
        target, ok = QInputDialog.getText(self, "Nowy wpis TM", "Tłumaczenie:")
        if not ok or not target.strip():
            return
        project = self.app.project
        self.app.tm.add(source, target,
                        project.source_lang if project else "en",
                        project.target_lang if project else "pl")
        self.refresh()

    def delete_entry(self) -> None:
        selected = self._selected_row()
        if not selected:
            return
        src, tgt = selected
        if QMessageBox.question(self, "Usuń wpis", f"Usunąć wpis?\n\n{src}\n→ {tgt}") \
                == QMessageBox.StandardButton.Yes:
            self.app.tm.delete(src, tgt)
            self.refresh()

    def attach_tmx_file(self) -> None:
        """Kopiuje plik TMX do folderu tm/ projektu i wczytuje go."""
        if not self._require_tm():
            return
        path, _ = QFileDialog.getOpenFileName(self, "Wybierz plik TMX", "", "Pliki TMX (*.tmx)")
        if not path:
            return
        dest = os.path.join(self.app.project.tm_path, os.path.basename(path))
        try:
            if os.path.abspath(path) != os.path.abspath(dest):
                shutil.copy2(path, dest)
            count = self.app.tm.import_tmx(dest)
            self.app.register_tm_source(dest, count)
            self.refresh()
            self.app.update_status()
            QMessageBox.information(
                self, "Dołączono TMX",
                f"Skopiowano do folderu tm/ i zaimportowano {count} jednostek.",
            )
        except Exception as exc:
            QMessageBox.critical(self, "Błąd", str(exc))

    def import_tmx(self) -> None:
        if not self._require_tm():
            return
        path, _ = QFileDialog.getOpenFileName(self, "Importuj TMX", "", "Pliki TMX (*.tmx);;Wszystkie pliki (*)")
        if not path:
            return

        from .workers import TMXImportWorker

        progress = QProgressDialog(f"Import TMX: {os.path.basename(path)}…", None, 0, 100, self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(300)

        worker = TMXImportWorker(self.app.tm, path, parent=self)
        worker.progress.connect(progress.setValue)

        def on_done(count: int, error: str):
            progress.close()
            if not error:
                self.app.register_tm_source(path, count)
            self.refresh()
            self.app.update_status()
            if error:
                QMessageBox.critical(self, "Błąd importu", error)
            else:
                QMessageBox.information(self, "Import TMX", f"Zaimportowano {count} jednostek tłumaczeniowych.")
            self._import_worker = None

        worker.finished_import.connect(on_done)
        self._import_worker = worker
        worker.start()

    def export_tmx(self) -> None:
        if not self._require_tm():
            return
        project = self.app.project
        default = os.path.join(project.export_path, f"{project.name}.tmx") if project else "export.tmx"
        path, _ = QFileDialog.getSaveFileName(self, "Eksportuj TMX", default, "Pliki TMX (*.tmx)")
        if not path:
            return
        try:
            count = self.app.tm.export_tmx(
                path,
                project.source_lang if project else "en",
                project.target_lang if project else "pl",
            )
            QMessageBox.information(self, "Eksport TMX", f"Zapisano {count} jednostek do:\n{path}")
        except Exception as exc:
            QMessageBox.critical(self, "Błąd eksportu", str(exc))

    def clear_tm(self) -> None:
        if not self._require_tm():
            return
        if QMessageBox.question(
            self, "Wyczyść TM", "Czy na pewno usunąć WSZYSTKIE wpisy z pamięci tłumaczeń tego projektu?"
        ) == QMessageBox.StandardButton.Yes:
            self.app.tm.clear()
            self.refresh()
            self.app.update_status()

    def _require_tm(self) -> bool:
        if not self.app.tm.is_initialized:
            QMessageBox.information(self, "Pamięć TM", "Najpierw otwórz lub utwórz projekt.")
            return False
        return True
