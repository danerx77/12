"""Zakładka „Znajdź i zamień” – wyszukiwanie w bieżącym pliku i we wszystkich.

Możliwości:
  • tryby: zawiera / całe słowo / dokładne / regex,
  • ignorowanie znaczników (``\\n``, ``\\p``, ``<<KON>>``) – fraza „STAMP CARD System”
    znajdzie ``STAMP CARD\\nSystem``,
  • ignorowanie polskich ogonków (szukasz „zolw”, znajdzie „żółw”),
  • zakres: cały projekt / tylko przeglądany plik / wybrane pliki,
  • grupowanie wyników po pliku (drzewo) z licznikiem trafień,
  • podgląd fragmentu z kontekstem, przejście do segmentu (Enter / F3 / 2× klik),
  • zamiana w zaznaczonych wynikach albo w całym zakresie,
  • wyszukiwanie także w pamięci TM i w glosariuszu.
"""
from __future__ import annotations

import re
import time as _time
from typing import Dict, List, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QBrush, QColor, QFont, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QMenu, QMessageBox, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
    QWidget,
)

from ..core.search import (MODE_LABELS, STATUS_FILTERS, WHITESPACE_FILTERS,
                           SearchOptions, SearchResult, replace_in_segments,
                           search_segments, search_whitespace)
from ..core.textutil import context_snippet
from .editor_tab import format_duration, marker_settings

#: Wyjaśnienia filtrów białych znaków (dymki przy polach wyboru).
WHITESPACE_HINTS = {
    "leading": "Segment zaczyna się od spacji — w plikach gier przesuwa wcięcie "
               "dialogu, a w edytorze wygląda identycznie jak tekst bez niej.",
    "trailing": "Segment kończy się spacją — zwykle zbędna, czasem znacząca.",
    "double": "Dwie lub więcej spacji WEWNĄTRZ tekstu (wcięcie na brzegu "
              "nie jest tu liczone).",
    "tab": "Tabulator w tekście — łatwo pomylić go ze spacjami.",
    "mismatch": "Tłumaczenie ma inne spacje na brzegach niż źródło — "
                "tekst przesunie się w oknie gry.",
}

SCOPE_ALL = "Cały projekt"
SCOPE_CURRENT = "Tylko przeglądany plik"
SCOPE_SELECTED = "Wybrane pliki…"


class SearchTab(QWidget):
    """Panel wyszukiwania. Używany i jako zakładka, i jako osobne okno.

    ``owner_window`` ustawiane jest tylko wtedy, gdy panel siedzi w oknie
    (``SearchWindow``) – wtedy przejście do segmentu nie przełącza zakładek,
    bo wyniki i tak są widoczne w osobnym oknie.
    """

    def __init__(self, app, owner_window=None) -> None:
        super().__init__()
        self.app = app
        self.owner_window = owner_window
        self.result = SearchResult()
        self._selected_files: Optional[List[str]] = None
        self._live_delay_ms = 200
        self._last_search_ms = 0.0
        self._build_ui()
        self._build_shortcuts()

    # ---------------------------------------------------------------- UI
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        box = QGroupBox("🔍 Znajdź i zamień")
        grid = QGridLayout(box)

        grid.addWidget(QLabel("Szukaj:"), 0, 0)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("wpisz wyraz lub frazę i naciśnij Enter…")
        self.search_edit.returnPressed.connect(self.perform_search)
        grid.addWidget(self.search_edit, 0, 1)
        find_btn = QPushButton("🔍 Szukaj")
        find_btn.setToolTip("Szukaj w segmentach (Enter). F3 – następny wynik.")
        find_btn.clicked.connect(self.perform_search)
        grid.addWidget(find_btn, 0, 2)

        grid.addWidget(QLabel("Zamień na:"), 1, 0)
        self.replace_edit = QLineEdit()
        self.replace_edit.setPlaceholderText("tekst zastępujący…")
        grid.addWidget(self.replace_edit, 1, 1)
        replace_row = QHBoxLayout()
        replace_sel_btn = QPushButton("🔄 Zamień w zaznaczonych")
        replace_sel_btn.setToolTip("Zamienia tylko w wynikach zaznaczonych na liście poniżej")
        replace_sel_btn.clicked.connect(self.replace_selected)
        replace_btn = QPushButton("🔄 Zamień wszystkie")
        replace_btn.clicked.connect(self.replace_all)
        replace_row.addWidget(replace_sel_btn)
        replace_row.addWidget(replace_btn)
        grid.addLayout(replace_row, 1, 2)

        grid.addWidget(QLabel("Tryb:"), 2, 0)
        mode_row = QHBoxLayout()
        self.mode = QComboBox()
        self.mode.addItems(list(MODE_LABELS.keys()))
        self.mode.setToolTip(
            "Zawiera – dowolne wystąpienie\n"
            "Całe słowo – tylko samodzielny wyraz\n"
            "Dokładne – cały segment równy frazie\n"
            "Regex – wyrażenie regularne"
        )
        mode_row.addWidget(self.mode)
        mode_row.addWidget(QLabel("Zakres:"))
        self.scope = QComboBox()
        self.scope.addItems([SCOPE_ALL, SCOPE_CURRENT, SCOPE_SELECTED])
        self.scope.setToolTip("Gdzie szukać: we wszystkich plikach projektu czy tylko w jednym")
        self.scope.currentTextChanged.connect(self._on_scope_changed)
        mode_row.addWidget(self.scope, 1)
        grid.addLayout(mode_row, 2, 1, 1, 2)

        options = QHBoxLayout()
        self.case_check = QCheckBox("Wielkość liter")
        self.source_check = QCheckBox("Źródło")
        self.source_check.setChecked(True)
        self.target_check = QCheckBox("Tłumaczenie")
        self.target_check.setChecked(True)
        self.codes_check = QCheckBox("Ignoruj znaczniki (\\n, \\p, <<KON>>)")
        self.codes_check.setChecked(True)
        self.codes_check.setToolTip(
            "Znaczniki liczą się jak spacja, więc fraza „STAMP CARD System”\n"
            "znajdzie tekst „STAMP CARD\\nSystem”."
        )
        self.accents_check = QCheckBox("Ignoruj ogonki")
        self.accents_check.setToolTip("Szukasz „zolw” – znajdzie także „żółw”.")
        for w in (self.case_check, self.source_check, self.target_check,
                  self.codes_check, self.accents_check):
            options.addWidget(w)
        options.addStretch(1)
        grid.addLayout(options, 3, 0, 1, 3)

        options2 = QHBoxLayout()
        self.untranslated_check = QCheckBox("Tylko nieprzetłumaczone")
        self.translated_check = QCheckBox("Tylko przetłumaczone")
        self.untranslated_check.toggled.connect(
            lambda on: on and self.translated_check.setChecked(False))
        self.translated_check.toggled.connect(
            lambda on: on and self.untranslated_check.setChecked(False))
        self.skip_ignored_check = QCheckBox("Pomijaj wykluczone")
        self.skip_ignored_check.setToolTip("Nie pokazuj segmentów oznaczonych jako pominięte")
        self.tm_check = QCheckBox("Szukaj także w pamięci TM")
        self.gloss_check = QCheckBox("Szukaj także w glosariuszu")
        self.live_check = QCheckBox("Szukaj w trakcie pisania")
        self.live_check.setChecked(True)
        self.live_check.toggled.connect(self._on_live_toggled)
        for w in (self.untranslated_check, self.translated_check, self.skip_ignored_check,
                  self.tm_check, self.gloss_check, self.live_check):
            options2.addWidget(w)
        options2.addStretch(1)
        grid.addLayout(options2, 4, 0, 1, 3)

        status_row = QHBoxLayout()
        status_row.addWidget(QLabel("🏷️ Status:"))
        self.status_boxes = {}
        for key, label in STATUS_FILTERS.items():
            box_item = QCheckBox(label)
            box_item.setToolTip(
                f"Pokazuj segmenty o statusie „{label}”.\n"
                "Gdy nic nie zaznaczysz, wyszukiwarka bierze wszystkie."
            )
            box_item.toggled.connect(self._on_status_filter_changed)
            self.status_boxes[key] = box_item
            status_row.addWidget(box_item)
        clear_status = QPushButton("✖ Wyczyść")
        clear_status.setToolTip("Odznacza wszystkie statusy")
        clear_status.clicked.connect(self._clear_status_filter)
        status_row.addWidget(clear_status)
        status_row.addStretch(1)
        grid.addLayout(status_row, 5, 0, 1, 3)

        # Białe znaki – szukanie tego, czego w tekście nie widać.
        ws_row = QHBoxLayout()
        ws_label = QLabel("␣ Białe znaki:")
        ws_label.setToolTip(
            "Znajduje segmenty ze spacją na początku lub końcu, podwójną spacją,\n"
            "tabulatorem albo z brzegami innymi niż w źródle.\n"
            "Działa bez wpisywania frazy — można też połączyć z frazą.")
        ws_row.addWidget(ws_label)
        self.whitespace_boxes = {}
        for key, label in WHITESPACE_FILTERS.items():
            box_item = QCheckBox(label)
            box_item.setToolTip(WHITESPACE_HINTS.get(key, ""))
            box_item.toggled.connect(self._on_status_filter_changed)
            self.whitespace_boxes[key] = box_item
            ws_row.addWidget(box_item)
        clear_ws = QPushButton("✖ Wyczyść")
        clear_ws.setToolTip("Odznacza wszystkie filtry białych znaków")
        clear_ws.clicked.connect(self._clear_whitespace_filter)
        ws_row.addWidget(clear_ws)
        ws_row.addStretch(1)
        grid.addLayout(ws_row, 6, 0, 1, 3)

        layout.addWidget(box)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Plik / segment", "Gdzie", "Trafienia", "Fragment"])
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setAlternatingRowColors(True)
        self.tree.setUniformRowHeights(True)
        self.tree.itemDoubleClicked.connect(lambda *_: self.goto_result())
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._context_menu)
        self.tree.setColumnWidth(0, 260)
        self.tree.setColumnWidth(1, 100)
        self.tree.setColumnWidth(2, 80)
        layout.addWidget(self.tree)

        bottom = QHBoxLayout()
        self.status = QLabel("Wpisz frazę i naciśnij Enter")
        bottom.addWidget(self.status)
        bottom.addStretch(1)
        prev_btn = QPushButton("⬆ Poprzedni")
        prev_btn.setToolTip("Shift+F3")
        prev_btn.clicked.connect(self.prev_result)
        next_btn = QPushButton("⬇ Następny")
        next_btn.setToolTip("F3")
        next_btn.clicked.connect(self.next_result)
        goto_btn = QPushButton("↪ Przejdź do segmentu")
        goto_btn.clicked.connect(self.goto_result)
        for b in (prev_btn, next_btn, goto_btn):
            bottom.addWidget(b)
        if self.owner_window is None:
            window_btn = QPushButton("🗗 Otwórz w osobnym oknie")
            window_btn.setToolTip("Osobne okno wyszukiwania, jak w OmegaT (można mieć kilka naraz)")
            window_btn.clicked.connect(self._open_in_window)
            bottom.addWidget(window_btn)
        layout.addLayout(bottom)

        self.live_timer = None
        self.search_edit.textChanged.connect(self._on_text_changed)

    def _build_shortcuts(self) -> None:
        from ..core import shortcuts as _sc

        for key, slot in (("next_result", self.next_result),
                          ("prev_result", self.prev_result)):
            seq = _sc.get(key)
            if not seq:
                continue
            sc = QShortcut(QKeySequence(seq), self)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(slot)

    # ------------------------------------------------------------ opcje
    def _on_scope_changed(self, text: str) -> None:
        if text == SCOPE_SELECTED:
            self._choose_files()

    def _choose_files(self) -> None:
        from .dialogs.file_select import FileSelectDialog

        names = sorted({(s.file_name or "(bez pliku)") for s in self.app.editor_tab.segments})
        if not names:
            return
        dialog = FileSelectDialog(names, self._selected_files, self)
        if dialog.exec() and dialog.chosen:
            self._selected_files = dialog.chosen
            self.status.setText(f"Zakres: {len(self._selected_files)} plików")
        else:
            self.scope.setCurrentText(SCOPE_ALL)

    def _on_live_toggled(self, on: bool) -> None:
        if on and self.search_edit.text().strip():
            self.perform_search()

    def _on_text_changed(self, text: str) -> None:
        """Szukanie „w locie” – dopiero od 2 znaków, żeby nie mielić projektu."""
        if not self.live_check.isChecked():
            return
        from PyQt6.QtCore import QTimer

        if self.live_timer is None:
            self.live_timer = QTimer(self)
            self.live_timer.setSingleShot(True)
            self.live_timer.timeout.connect(self.perform_search)
        if len(text.strip()) >= 2:
            # Odstęp jest ADAPTACYJNY: w małym projekcie wyniki pojawiają się
            # od razu, w dużym czekamy dłużej, żeby pisanie nie zacinało okna.
            self.live_timer.start(self._live_delay_ms)
        elif self.selected_statuses() or self.selected_whitespace():
            # Filtr statusu i białych znaków działa bez frazy – nie kasujemy wyników.
            self.live_timer.stop()
            self.perform_search()
        else:
            self.live_timer.stop()
            self.tree.clear()
            self.result = SearchResult()
            self.status.setText("Wpisz co najmniej 2 znaki")

    def current_options(self) -> SearchOptions:
        files: Optional[List[str]] = None
        scope = self.scope.currentText()
        if scope == SCOPE_CURRENT:
            current = self.app.editor_tab._file_filter
            if not current:
                seg = self.app.editor_tab.current_segment()
                current = (seg.file_name if seg else None) or None
            files = [current] if current else None
        elif scope == SCOPE_SELECTED and self._selected_files:
            files = list(self._selected_files)
        return SearchOptions(
            mode=MODE_LABELS.get(self.mode.currentText(), "contains"),
            case_sensitive=self.case_check.isChecked(),
            ignore_accents=self.accents_check.isChecked(),
            ignore_codes=self.codes_check.isChecked(),
            in_source=self.source_check.isChecked(),
            in_target=self.target_check.isChecked(),
            only_untranslated=self.untranslated_check.isChecked(),
            only_translated=self.translated_check.isChecked(),
            statuses=self.selected_statuses(),
            include_ignored=not self.skip_ignored_check.isChecked(),
            whitespace=self.selected_whitespace(),
            files=files,
        )

    # ---------------------------------------------------------- szukanie
    def perform_search(self) -> None:
        needle = self.search_edit.text()
        self.tree.clear()
        self.result = SearchResult()
        statuses = self.selected_statuses()
        whitespace = self.selected_whitespace()
        if not needle and not statuses and not whitespace:
            self.status.setText("Wpisz frazę, zaznacz status albo filtr białych znaków")
            return
        if not needle.strip():
            if whitespace:
                # Same białe znaki – szukamy tego, czego w tekście nie widać.
                self._show_whitespace_only(whitespace)
            else:
                # Sam filtr statusu – wypisujemy wszystkie pasujące segmenty.
                self._show_status_only(statuses)
            return

        options = self.current_options()
        segments = self.app.editor_tab.segments
        started = _time.perf_counter()
        cfg = marker_settings()
        nl_marker = cfg["newline_marker"] if cfg["show_newlines"] else None
        self.result = search_segments(segments, needle, options, newline_marker=nl_marker)
        if whitespace and not self.result.error:
            # Fraza + filtr: zostawiamy tylko trafienia w segmentach, które
            # mają też wskazany problem z białymi znakami.
            self.result.hits = self._filter_hits_by_whitespace(
                self.result.hits, segments, whitespace)
        self._last_search_ms = (_time.perf_counter() - started) * 1000
        # 4× czas ostatniego szukania (200 ms – 1,5 s) – tyle czekamy przy pisaniu
        self._live_delay_ms = int(min(1500, max(200, self._last_search_ms * 4)))
        if self.result.error:
            self.status.setText(f"❌ {self.result.error}")
            return

        bold = QFont()
        bold.setBold(True)
        current_file = None
        if self.scope.currentText() == SCOPE_CURRENT and options.files:
            current_file = options.files[0]

        for file_name, hits in sorted(self.result.by_file().items()):
            total = sum(h.count for h in hits)
            marker = "📂" if file_name == current_file else "📄"
            parent = QTreeWidgetItem([
                f"{marker} {file_name}", "", str(total),
                f"{len(hits)} segmentów",
            ])
            parent.setFont(0, bold)
            parent.setData(0, Qt.ItemDataRole.UserRole, None)
            self.tree.addTopLevelItem(parent)
            for hit in hits:
                child = QTreeWidgetItem([
                    f"segment {hit.index + 1}", hit.where, str(hit.count), hit.snippet,
                ])
                child.setData(0, Qt.ItemDataRole.UserRole, hit.index)
                child.setData(1, Qt.ItemDataRole.UserRole, hit.where)
                if hit.where == "tłumaczenie":
                    child.setForeground(1, QBrush(QColor("#2e7d32")))
                parent.addChild(child)
            parent.setExpanded(True)

        extra = []
        if self.tm_check.isChecked() and self.app.tm.is_initialized:
            tm_rows = self.app.tm.search(needle, 200)
            if tm_rows:
                node = QTreeWidgetItem([f"💾 Pamięć TM", "", str(len(tm_rows)), "wyniki z TM"])
                node.setFont(0, bold)
                for src, tgt, *_ in tm_rows:
                    pair = f"{(src or '')[:70]} → {(tgt or '')[:70]}"
                    if nl_marker:
                        pair = pair.replace("\n", f" {nl_marker} ")
                    else:
                        pair = pair.replace("\n", " ")
                    item = QTreeWidgetItem(["", "TM", "", pair])
                    item.setData(0, Qt.ItemDataRole.UserRole, None)
                    node.addChild(item)
                self.tree.addTopLevelItem(node)
                node.setExpanded(False)
                extra.append(f"TM: {len(tm_rows)}")

        if self.gloss_check.isChecked() and getattr(self.app.glossary, "entries", None):
            terms = self.app.glossary.search(needle)
            if terms:
                node = QTreeWidgetItem(["🏷️ Glosariusz", "", str(len(terms)), "terminy"])
                node.setFont(0, bold)
                for term in terms:
                    item = QTreeWidgetItem(["", "termin", "", f"{term.source} → {term.target}"])
                    item.setData(0, Qt.ItemDataRole.UserRole, None)
                    node.addChild(item)
                self.tree.addTopLevelItem(node)
                node.setExpanded(False)
                extra.append(f"glosariusz: {len(terms)}")

        summary = self.result.summary()
        if extra:
            summary += "  •  " + "  •  ".join(extra)
        summary += f"  •  ⏱ {format_duration(self._last_search_ms)}"
        self.status.setText(summary)

    # ------------------------------------------------------- nawigacja
    def _hit_items(self) -> List[QTreeWidgetItem]:
        items: List[QTreeWidgetItem] = []
        for i in range(self.tree.topLevelItemCount()):
            parent = self.tree.topLevelItem(i)
            for j in range(parent.childCount()):
                child = parent.child(j)
                if child.data(0, Qt.ItemDataRole.UserRole) is not None:
                    items.append(child)
        return items

    def _step(self, delta: int) -> None:
        items = self._hit_items()
        if not items:
            return
        current = self.tree.currentItem()
        try:
            pos = items.index(current)
        except ValueError:
            pos = -1 if delta > 0 else 0
        pos = (pos + delta) % len(items)
        self.tree.setCurrentItem(items[pos])
        self.goto_result(stay=True)

    def next_result(self) -> None:
        self._step(1)

    def prev_result(self) -> None:
        self._step(-1)

    def goto_result(self, stay: bool = False) -> None:
        item = self.tree.currentItem()
        if item is None:
            return
        index = item.data(0, Qt.ItemDataRole.UserRole)
        if index is None:
            return
        where = item.data(1, Qt.ItemDataRole.UserRole) or "źródło"
        self.app.go_to_editor_segment(int(index))
        self.app.editor_tab.highlight_search(self.search_edit.text(),
                                             self.current_options(), where)
        if self.owner_window is not None:
            # osobne okno: główne okno pokazuje edytor, wyniki zostają w oknie
            self.owner_window.raise_()
            self.owner_window.notify_goto()
            self.tree.setFocus()
        elif stay:
            self.app.tabs.setCurrentWidget(self)
            self.tree.setFocus()

    def _context_menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        if item is None:
            return
        menu = QMenu(self)
        act_goto = menu.addAction("↪ Przejdź do segmentu")
        act_copy = menu.addAction("📋 Kopiuj fragment")
        act_filter = menu.addAction("👁️ Pokaż ten plik w edytorze")
        chosen = menu.exec(self.tree.viewport().mapToGlobal(pos))
        if chosen == act_goto:
            self.tree.setCurrentItem(item)
            self.goto_result()
        elif chosen == act_copy:
            from PyQt6.QtWidgets import QApplication

            QApplication.clipboard().setText(item.text(3))
        elif chosen == act_filter:
            top = item if item.parent() is None else item.parent()
            name = top.text(0).lstrip("📂📄 ").strip()
            editor = self.app.editor_tab
            editor._file_filter = name
            editor.refresh_grid()
            if self.owner_window is None:
                self.app.tabs.setCurrentWidget(editor)

    # ---------------------------------------------------------- zamiana
    def _do_replace(self, only_indices: Optional[List[int]]) -> None:
        needle = self.search_edit.text()
        replacement = self.replace_edit.text()
        if not needle:
            return
        segments = self.app.editor_tab.segments
        if not segments:
            return
        options = self.current_options()
        target_segments = segments
        if only_indices is not None:
            target_segments = [segments[i] for i in sorted(set(only_indices))
                               if 0 <= i < len(segments)]
            if not target_segments:
                QMessageBox.information(self, "Zamiana", "Zaznacz najpierw wyniki na liście.")
                return
            options.files = None
        where = "zaznaczonych wynikach" if only_indices is not None else "całym zakresie"
        if QMessageBox.question(
            self, "Zamień",
            f"Zamienić „{needle}” na „{replacement}” w {where}?\n"
            f"Segmentów do sprawdzenia: {len(target_segments)}",
        ) != QMessageBox.StandardButton.Yes:
            return

        try:
            changed, total = replace_in_segments(
                target_segments, needle, replacement, options,
                in_target=self.target_check.isChecked(),
                in_source=False,
            )
        except re.error as exc:
            QMessageBox.critical(self, "Błąd", f"Błędne wyrażenie regularne: {exc}")
            return

        for seg in target_segments:
            if seg.target and seg.status == "new":
                seg.status = "draft"
        self.app.editor_tab.refresh_grid()
        if self.app.editor_tab.current_index >= 0:
            self.app.editor_tab.load_segment(self.app.editor_tab.current_index)
        self.status.setText(f"Zamieniono {total} wystąpień w {changed} segmentach")
        QMessageBox.information(self, "Zamiana",
                                f"Zamieniono {total} wystąpień w {changed} segmentach.")
        self.perform_search()

    def replace_all(self) -> None:
        self._do_replace(None)

    def replace_selected(self) -> None:
        indices = []
        for item in self.tree.selectedItems():
            idx = item.data(0, Qt.ItemDataRole.UserRole)
            if idx is not None:
                indices.append(int(idx))
            else:
                for j in range(item.childCount()):
                    child_idx = item.child(j).data(0, Qt.ItemDataRole.UserRole)
                    if child_idx is not None:
                        indices.append(int(child_idx))
        self._do_replace(indices)

    def selected_statuses(self):
        """Zaznaczone statusy (pusta lista = wszystkie)."""
        return [key for key, box in self.status_boxes.items() if box.isChecked()]

    def _clear_status_filter(self) -> None:
        for box in self.status_boxes.values():
            box.blockSignals(True)
            box.setChecked(False)
            box.blockSignals(False)
        self.perform_search()

    def _on_status_filter_changed(self, _checked: bool) -> None:
        if (self.search_edit.text().strip() or self.selected_statuses()
                or self.selected_whitespace()):
            self.perform_search()
        else:
            # Odznaczenie ostatniego filtru czyści listę – inaczej zostałyby
            # nieaktualne wyniki bez żadnego aktywnego kryterium.
            self.tree.clear()
            self.result = SearchResult()
            self.status.setText("Wpisz frazę, zaznacz status albo filtr białych znaków")

    def selected_whitespace(self) -> List[str]:
        """Zaznaczone filtry białych znaków."""
        return [key for key, box in self.whitespace_boxes.items() if box.isChecked()]

    def _clear_whitespace_filter(self) -> None:
        for box in self.whitespace_boxes.values():
            box.setChecked(False)

    def _filter_hits_by_whitespace(self, hits, segments, kinds):
        """Zostawia trafienia z segmentów mających wskazany problem."""
        from ..core.search import edges_differ, whitespace_issues

        wanted = set(kinds)
        kept = []
        for hit in hits:
            if hit.index >= len(segments):
                continue
            seg = segments[hit.index]
            text = (seg.source if hit.where == "źródło" else seg.target) or ""
            found = set(whitespace_issues(text))
            if ("mismatch" in wanted and hit.where == "tłumaczenie"
                    and edges_differ(seg.source or "", seg.target or "")):
                found.add("mismatch")
            if found & wanted:
                kept.append(hit)
        return kept

    def _show_whitespace_only(self, kinds) -> None:
        """Wypisuje segmenty z problemami białych znaków – bez szukania frazy."""
        options = self.current_options()
        segments = self.app.editor_tab.segments
        cfg = marker_settings()
        nl_marker = cfg["newline_marker"] if cfg["show_newlines"] else None
        started = _time.perf_counter()
        self.result = search_whitespace(segments, kinds, options,
                                        newline_marker=nl_marker)
        self._last_search_ms = (_time.perf_counter() - started) * 1000

        bold = QFont()
        bold.setBold(True)
        for file_name, hits in sorted(self.result.by_file().items()):
            parent = QTreeWidgetItem([
                f"📄 {file_name}", "", str(len(hits)), f"{len(hits)} segmentów"])
            parent.setFont(0, bold)
            parent.setData(0, Qt.ItemDataRole.UserRole, None)
            self.tree.addTopLevelItem(parent)
            for hit in hits:
                child = QTreeWidgetItem([
                    f"segment {hit.index + 1}", hit.where, str(hit.count), hit.snippet])
                child.setData(0, Qt.ItemDataRole.UserRole, hit.index)
                child.setData(1, Qt.ItemDataRole.UserRole, hit.where)
                if hit.where == "tłumaczenie":
                    child.setForeground(1, QBrush(QColor("#2e7d32")))
                parent.addChild(child)
            parent.setExpanded(True)

        labels = ", ".join(WHITESPACE_FILTERS.get(k, k) for k in kinds)
        if self.result.hits:
            self.status.setText(
                f"␣ Znaleziono {len(self.result.hits)} segmentów ({labels})"
                f"  •  {format_duration(self._last_search_ms)}")
        else:
            self.status.setText(f"Brak segmentów z problemem: {labels}")

    def _show_status_only(self, statuses) -> None:
        """Wypisuje segmenty o wybranych statusach – bez szukania frazy."""
        from ..core.search import segment_status

        options = self.current_options()
        segments = self.app.editor_tab.segments
        allowed = set(options.files) if options.files is not None else None
        wanted = set(statuses)

        by_file = {}
        total = 0
        for index, seg in enumerate(segments):
            name = seg.file_name or "(bez pliku)"
            if allowed is not None and name not in allowed:
                continue
            status = segment_status(seg)
            if status not in wanted:
                continue
            if not options.include_ignored and status == "ignored":
                continue
            by_file.setdefault(name, []).append((index, seg, status))
            total += 1

        bold = QFont()
        bold.setBold(True)
        for name, rows in sorted(by_file.items()):
            parent = QTreeWidgetItem([f"📄 {name}", "", str(len(rows)), "segmentów"])
            parent.setFont(0, bold)
            parent.setData(0, Qt.ItemDataRole.UserRole, None)
            self.tree.addTopLevelItem(parent)
            for index, seg, status in rows:
                child = QTreeWidgetItem([
                    f"segment {index + 1}", STATUS_FILTERS.get(status, status), "",
                    (seg.source or "").replace("\n", " ⏎ ")[:120],
                ])
                child.setData(0, Qt.ItemDataRole.UserRole, index)
                child.setData(1, Qt.ItemDataRole.UserRole, "źródło")
                parent.addChild(child)
            parent.setExpanded(True)

        labels = ", ".join(STATUS_FILTERS.get(s, s) for s in statuses)
        self.status.setText(
            f"Status: {labels}  •  znaleziono {total} segmentów w {len(by_file)} plikach"
            if total else f"Brak segmentów o statusie: {labels}")

    def _open_in_window(self) -> None:
        """Przenosi bieżące wyszukiwanie do osobnego okna."""
        from .search_window import open_search_window

        open_search_window(self.app, self.search_edit.text())

    # -------------------------------------------------- wywołania z zewnątrz
    def search_for(self, text: str, scope: Optional[str] = None) -> None:
        """Uruchamia wyszukiwanie zadanej frazy (np. z menu edytora)."""
        if scope:
            self.scope.setCurrentText(scope)
        self.search_edit.setText(text)
        self.perform_search()
