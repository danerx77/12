"""Zakładka Ustawienia – ogólne, TM, MT, segmentacja, QA."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QColorDialog, QComboBox, QFormLayout, QGridLayout,
    QGroupBox, QHBoxLayout,
    QHeaderView, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSpinBox, QTableWidget,
    QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from ..core.mt import ENGINES, FREE_ENGINES
from ..core.settings import SettingsManager
from ..core.textutil import DEFAULT_MARKER_STYLE, MARKER_STYLES


MAX_FORM_WIDTH = 720


def _wide_scroll(widget: QWidget) -> QScrollArea:
    """Przewijany obszar na PEŁNĄ szerokość (dla tabel, nie formularzy)."""
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setWidget(widget)
    return area


def _scroll(widget: QWidget) -> QScrollArea:
    """Umieszcza formularz w przewijanym obszarze, wyrównany do lewej i o czytelnej szerokości."""
    widget.setMaximumWidth(MAX_FORM_WIDTH)
    holder = QWidget()
    holder_layout = QHBoxLayout(holder)
    holder_layout.setContentsMargins(0, 0, 0, 0)
    holder_layout.addWidget(widget)
    holder_layout.addStretch(1)
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setWidget(holder)
    return area


class SettingsTab(QTabWidget):
    def __init__(self, app) -> None:
        super().__init__()
        self.app = app
        self.settings = SettingsManager.instance()
        self.addTab(_scroll(self._general_tab()), "⚙️ Ogólne")
        self.addTab(_scroll(self._appearance_tab()), "🎨 Wygląd")
        self.addTab(_scroll(self._tm_tab()), "💾 Pamięć TM")
        self.addTab(_scroll(self._mt_tab()), "🤖 Tłumaczenie maszynowe")
        self.addTab(_scroll(self._language_tab()), "🔤 Pisownia i język")
        self.addTab(_scroll(self._segmentation_tab()), "✂️ Segmentacja")
        self.addTab(_scroll(self._exclusions_tab()), "🚫 Wykluczenia")
        # Tabela skrótów potrzebuje pełnej szerokości okna – zwykły _scroll
        # ogranicza formularze do MAX_FORM_WIDTH i ucinał ostatnie kolumny.
        self.addTab(_wide_scroll(self._shortcuts_tab()), "⌨️ Skróty")

    # ------------------------------------------------------------------
    def _appearance_tab(self) -> QWidget:
        """Wygląd: motyw, czcionki, znaki specjalne, panel prawy."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        appearance = QGroupBox("🎨 Motyw i czcionki")
        form = QFormLayout(appearance)
        self.theme_combo = QComboBox()
        self.theme_combo.setMaximumWidth(220)
        self.theme_combo.addItems(["Ciemny", "Jasny"])
        self.theme_combo.setCurrentIndex(0 if self.settings.get_bool("theme.dark", True) else 1)
        self.theme_combo.currentIndexChanged.connect(self._change_theme)
        form.addRow("Motyw:", self.theme_combo)

        self.time_unit = QComboBox()
        self.time_unit.setMaximumWidth(220)
        for label, key in (("automatycznie", "auto"), ("milisekundy (ms)", "ms"),
                           ("sekundy (s)", "s"), ("minuty (min)", "min")):
            self.time_unit.addItem(label, key)
        saved_unit = self.settings.get_str("ui.time.unit", "auto")
        self.time_unit.setCurrentIndex(
            next((i for i in range(self.time_unit.count())
                  if self.time_unit.itemData(i) == saved_unit), 0)
        )
        self.time_unit.setToolTip("Jednostki licznika czasu wyszukiwania w edytorze.")
        self.time_unit.currentIndexChanged.connect(self._change_time_unit)
        form.addRow("Jednostki czasu:", self.time_unit)

        self.ui_font_size = QSpinBox()
        self.ui_font_size.setMaximumWidth(140)
        self.ui_font_size.setRange(0, 28)
        self.ui_font_size.setSuffix(" pkt")
        self.ui_font_size.setValue(self.settings.get_int("ui.font.size", 0))
        self.ui_font_size.setToolTip(
            "Wielkość czcionki w CAŁYM programie: menu, zakładki, tabele,\n"
            "przyciski, listy plików. Zero = rozmiar domyślny motywu.\n"
            "Skróty: Ctrl+Shift++ i Ctrl+Shift+− (menu Widok).")
        self.ui_font_size.valueChanged.connect(
            lambda v: (self.settings.set("ui.font.size", v), self._apply_ui_font()))
        form.addRow("Czcionka interfejsu (0 = domyślna):", self.ui_font_size)

        self.font_size = QSpinBox()
        self.font_size.setMaximumWidth(140)
        self.font_size.setRange(8, 28)
        self.font_size.setValue(self.settings.get_int("editor.font.size", 12))
        self.font_size.valueChanged.connect(lambda v: (self.settings.set("editor.font.size", v), self.app.apply_font()))
        form.addRow("Rozmiar czcionki edytora:", self.font_size)
        layout.addWidget(appearance)

        # --- czcionki paneli po prawej: wszystkie naraz i każdy z osobna ---
        panels_font = QGroupBox("🔤 Czcionka paneli po prawej (dopasowania TM, zdania, …)")
        pf_l = QVBoxLayout(panels_font)
        pf_l.setContentsMargins(8, 8, 8, 8)
        pf_hint = QLabel("Zero = czcionka interfejsu (czyli „normalnie”). "
                         "Własny rozmiar panelu jest ważniejszy niż wspólny.")
        pf_hint.setWordWrap(True)
        pf_hint.setStyleSheet("color: gray;")
        pf_l.addWidget(pf_hint)

        self.panel_font_sizes: dict = {}
        for key, label in (("", "Wszystkie panele (wspólna)"),
                           ("matches", "Dopasowania TM"),
                           ("sentences", "Dopasowanie zdań"),
                           ("terms", "Terminy / glosariusz"),
                           ("conc", "Konkordancja"),
                           ("mt", "Tłumaczenie maszynowe"),
                           ("lang", "Język"),
                           ("notes", "Notatki")):
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.addWidget(QLabel(label))
            spin = QSpinBox()
            spin.setRange(0, 32)
            spin.setSuffix(" pkt")
            setting_key = "tm.panel.font.size" if not key else f"tm.panel.font.{key}"
            spin.setValue(self.settings.get_int(setting_key, 0))
            spin.setToolTip(f"{label}: 0 = rozmiar z motywu / całego interfejsu")
            spin.valueChanged.connect(
                lambda v, k=setting_key: (self.settings.set(k, v),
                                          self._apply_panel_font()))
            row.addWidget(spin, 1)
            self.panel_font_sizes[setting_key] = spin
            pf_l.addLayout(row)

        reset_fonts = QPushButton("↺ Domyślne (wszędzie zero)")
        reset_fonts.setToolTip("Wstawia 0 wszędzie — panele wracają do czcionki interfejsu.")
        reset_fonts.clicked.connect(self._reset_panel_fonts)
        pf_l.addWidget(reset_fonts)
        layout.addWidget(panels_font)

        markers_box = QGroupBox("Znaki specjalne w tabelach")
        mform = QFormLayout(markers_box)
        # znaki specjalne (przeniesione do zakładki Wygląd)
        self.markers_spaces = QCheckBox("Pokazuj znaki spacji i tabulatora (␣ →) na brzegach")
        self.markers_spaces.setToolTip(
            "Wcięcie z pliku źródłowego jest oznaczane widocznym znakiem w siatce segmentów.\n"
            "Wyłącz, jeśli wolisz czysty tekst."
        )
        self.markers_spaces.setChecked(self.settings.get_bool("ui.markers.spaces", True))
        self.markers_spaces.stateChanged.connect(
            lambda st: self._set_marker_option("ui.markers.spaces", bool(st)))
        mform.addRow(self.markers_spaces)

        self.markers_newlines = QCheckBox("Pokazuj znak końca wiersza (⏎) w tabelach")
        self.markers_newlines.setToolTip(
            "Twardy koniec wiersza w segmencie jest pokazywany jako ⏎.\n"
            "Wyłączony – w jego miejscu pojawia się zwykła spacja."
        )
        self.markers_newlines.setChecked(self.settings.get_bool("ui.markers.newlines", True))
        self.markers_newlines.stateChanged.connect(
            lambda st: self._set_marker_option("ui.markers.newlines", bool(st)))
        mform.addRow(self.markers_newlines)

        self.markers_style = QComboBox()
        self.markers_style.addItems(list(MARKER_STYLES.keys()))
        self.markers_style.setCurrentText(
            self.settings.get("ui.markers.style", DEFAULT_MARKER_STYLE))
        self.markers_style.setToolTip(
            "Zestaw znaków: spacja, tabulator, koniec wiersza.\n"
            "„Tylko ASCII” przydaje się, gdy czcionka nie ma symboli Unicode."
        )
        self.markers_style.currentTextChanged.connect(
            lambda text: self._set_marker_option("ui.markers.style", text))
        mform.addRow("Zestaw znaków specjalnych:", self.markers_style)

        self.highlight_ws = QCheckBox("Podświetlaj spacje na brzegach segmentu (wcięcia)")
        self.highlight_ws.setToolTip(
            "Wcięcie z pliku źródłowego dostaje kolorowe tło w polu źródła i tłumaczenia.\n"
            "Czerwone tło = w źródle jest wcięcie, a w tłumaczeniu go brakuje."
        )
        self.highlight_ws.setChecked(self.settings.get_bool("ui.whitespace.highlight", True))
        self.highlight_ws.stateChanged.connect(self._toggle_whitespace_highlight)
        mform.addRow(self.highlight_ws)

        layout.addWidget(markers_box)

        self.panel_layout_combo = QComboBox()
        self.panel_layout_combo.addItem("Wszystko naraz (jedno pod drugim)", "stacked")
        self.panel_layout_combo.addItem("Zakładki", "tabs")
        self.panel_layout_combo.setToolTip(
            "Jak wyglądają panele po prawej stronie edytora.\n"
            "„Wszystko naraz” — wszystkie pod spodem, bez klikania;\n"
            "„Zakładki” — klasyczne karty do przełączania.")
        cur = self.settings.get_str("tm.panel.layout", "stacked")
        self.panel_layout_combo.setCurrentIndex(
            1 if cur == "tabs" else 0)
        self.panel_layout_combo.currentIndexChanged.connect(
            lambda i: (self.settings.set("tm.panel.layout",
                                         self.panel_layout_combo.itemData(i)),
                       self._apply_panel_layout()))

        self._panel_show_checks = {}
        for key, label in (("matches", "Dopasowania TM"),
                           ("sentences", "Dopasowanie zdań"),
                           ("terms", "Terminy"),
                           ("conc", "Konkordancja"),
                           ("mt", "MT"),
                           ("lang", "Język"),
                           ("notes", "Notatki")):
            cb = QCheckBox(label)
            cb.setChecked(self.settings.get_bool(f"tm.panel.show.{key}", True))
            cb.stateChanged.connect(
                lambda st, k=key: (self.settings.set(f"tm.panel.show.{k}", bool(st)),
                                   self._apply_panel_layout()))
            self._panel_show_checks[key] = cb

        right_box = QGroupBox("Panel prawy edytora (układ i zawartość)")
        rb_l = QVBoxLayout(right_box)
        rb_l.setContentsMargins(8, 4, 8, 4)
        rb_row = QHBoxLayout()
        rb_row.addWidget(QLabel("Układ:"))
        rb_row.addWidget(self.panel_layout_combo)
        rb_row.addStretch(1)
        rb_l.addLayout(rb_row)
        show_row = QHBoxLayout()
        for key in ("matches", "sentences", "terms", "conc", "mt", "lang", "notes"):
            show_row.addWidget(self._panel_show_checks[key])
        show_row.addStretch(1)
        rb_l.addLayout(show_row)
        layout.addWidget(right_box)

        layout.addStretch(1)
        return widget

    def _general_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)


        editor = QGroupBox("Edytor i zapis")
        eform = QFormLayout(editor)
        self.autosave = QCheckBox("Włącz automatyczny zapis tłumaczeń")
        self.autosave.setChecked(self.settings.get_bool("auto.save.enabled", True))
        self.autosave.stateChanged.connect(lambda s: self.settings.set("auto.save.enabled", bool(s)))
        eform.addRow(self.autosave)

        self.autosave_interval = QSpinBox()
        self.autosave_interval.setMaximumWidth(140)
        self.autosave_interval.setRange(10, 600)
        self.autosave_interval.setSuffix(" s")
        self.autosave_interval.setValue(self.settings.get_int("auto.save.interval", 30))
        self.autosave_interval.valueChanged.connect(lambda v: self.settings.set("auto.save.interval", v))
        eform.addRow("Odstęp auto-zapisu:", self.autosave_interval)

        self.arrow_nav = QCheckBox(
            "Strzałki ↑/↓ w polu tłumaczenia przechodzą między segmentami")
        self.arrow_nav.setToolTip(
            "Włączone: gdy kursor stoi w pierwszym lub ostatnim wierszu tekstu,\n"
            "strzałka przechodzi do sąsiedniego segmentu (jak w OmegaT).\n"
            "W środku dłuższego tłumaczenia strzałki nadal chodzą po liniach.\n"
            "Wyłączone: strzałki poruszają wyłącznie kursorem — do zmiany\n"
            "segmentu służą wtedy Ctrl+↑/↓ oraz Alt+↑/↓."
        )
        self.arrow_nav.setChecked(
            self.settings.get_bool("editor.arrows.change.segment", True))
        self.arrow_nav.stateChanged.connect(
            lambda s: self.settings.set("editor.arrows.change.segment", bool(s)))
        eform.addRow(self.arrow_nav)

        self.search_window = QCheckBox("Ctrl+F otwiera osobne okno wyszukiwania (jak w OmegaT)")
        self.search_window.setToolTip(
            "Włączone: Ctrl+F otwiera samodzielne okno – można mieć kilka naraz,\n"
            "Esc je zamyka, a dwuklik na wyniku przenosi do segmentu.\n"
            "Wyłączone: Ctrl+F przełącza na zakładkę „Znajdź i zamień”."
        )
        self.search_window.setChecked(self.settings.get_bool("search.window.enabled", True))
        self.search_window.stateChanged.connect(
            lambda s: self.settings.set("search.window.enabled", bool(s)))
        eform.addRow(self.search_window)


        self.highlight_terms = QCheckBox("Podświetlaj terminy glosariusza w tekście źródłowym")
        self.highlight_terms.setChecked(self.settings.get_bool("glossary.highlight", True))
        self.highlight_terms.stateChanged.connect(lambda s: self.settings.set("glossary.highlight", bool(s)))
        eform.addRow(self.highlight_terms)

        self.load_last = QCheckBox("Otwieraj ostatni projekt przy starcie")
        self.load_last.setChecked(self.settings.get_bool("auto.load.last.project", False))
        self.load_last.stateChanged.connect(lambda s: self.settings.set("auto.load.last.project", bool(s)))
        eform.addRow(self.load_last)
        layout.addWidget(editor)

        reset_btn = QPushButton("↺ Przywróć ustawienia domyślne")
        reset_btn.setMaximumWidth(300)
        reset_btn.clicked.connect(self._reset)
        layout.addWidget(reset_btn)
        layout.addStretch(1)
        return widget

    def _set_marker_option(self, key: str, value) -> None:
        """Zapisuje ustawienie znaków specjalnych i od razu odświeża widoki."""
        self.settings.set(key, value)
        editor = getattr(self.app, "editor_tab", None)
        if editor is not None:
            editor.refresh_grid()
        search_tab = getattr(self.app, "search_tab", None)
        if search_tab is not None and search_tab.search_edit.text().strip():
            search_tab.perform_search()
        # odśwież także otwarte okna wyszukiwania
        try:
            from .search_window import OPEN_WINDOWS

            for window in OPEN_WINDOWS:
                if window.panel.search_edit.text().strip():
                    window.panel.perform_search()
        except Exception:
            pass

    def _toggle_lang_auto(self, state) -> None:
        self.settings.set("lang.check.auto", bool(state))
        editor = getattr(self.app, "editor_tab", None)
        if editor is not None and hasattr(editor, "lang_auto"):
            editor.lang_auto.blockSignals(True)
            editor.lang_auto.setChecked(bool(state))
            editor.lang_auto.blockSignals(False)
            if state:
                editor.check_language(force=True)

    def _toggle_lang_lt(self, state) -> None:
        self.settings.set("lang.check.languagetool", bool(state))
        editor = getattr(self.app, "editor_tab", None)
        if editor is not None and hasattr(editor, "lang_lt"):
            editor.lang_lt.blockSignals(True)
            editor.lang_lt.setChecked(bool(state))
            editor.lang_lt.blockSignals(False)

    def _toggle_whitespace_highlight(self, state) -> None:
        self.settings.set("ui.whitespace.highlight", bool(state))
        editor = getattr(self.app, "editor_tab", None)
        if editor is not None:
            editor.highlight_whitespace()

    def _shortcuts_tab(self) -> QWidget:
        """Edycja skrótów klawiszowych – każdy można zmienić."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        info = QLabel(
            "Kliknij dwukrotnie w kolumnie <b>Skrót</b> i naciśnij nową kombinację. "
            "Puste pole przywraca wartość domyślną. Program ostrzeże, gdy kombinacja "
            "jest już zajęta."
        )
        info.setWordWrap(True)
        info.setTextFormat(Qt.TextFormat.RichText)
        info.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(info)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("🔎 Szukaj:"))
        self.sc_filter = QLineEdit()
        self.sc_filter.setPlaceholderText("filtruj polecenia lub kombinacje…")
        self.sc_filter.textChanged.connect(self._filter_shortcuts)
        filter_row.addWidget(self.sc_filter, 1)
        layout.addLayout(filter_row)

        self.sc_table = QTableWidget(0, 4)
        self.sc_table.setHorizontalHeaderLabels(["Grupa", "Polecenie", "Skrót", "Domyślny"])
        self.sc_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch)
        self.sc_table.setColumnWidth(0, 130)
        self.sc_table.setColumnWidth(2, 190)
        self.sc_table.setColumnWidth(3, 170)
        self.sc_table.horizontalHeader().setStretchLastSection(False)
        self.sc_table.verticalHeader().setVisible(False)
        self.sc_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.sc_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.sc_table.setAlternatingRowColors(True)
        self.sc_table.setMinimumHeight(480)
        self.sc_table.setSizePolicy(self.sc_table.sizePolicy().horizontalPolicy(),
                                    self.sc_table.sizePolicy().verticalPolicy())
        self.sc_table.doubleClicked.connect(self._edit_shortcut)
        layout.addWidget(self.sc_table, 1)

        buttons = QHBoxLayout()
        change_btn = QPushButton("✏️ Zmień skrót")
        change_btn.clicked.connect(self._edit_shortcut)
        clear_btn = QPushButton("🚫 Wyłącz skrót")
        clear_btn.setToolTip("Usuwa kombinację – polecenie zostanie tylko w menu")
        clear_btn.clicked.connect(self._clear_shortcut)
        default_btn = QPushButton("↺ Przywróć domyślny")
        default_btn.clicked.connect(self._default_shortcut)
        reset_btn = QPushButton("↺ Przywróć wszystkie domyślne")
        reset_btn.clicked.connect(self._reset_shortcuts)
        for button in (change_btn, clear_btn, default_btn, reset_btn):
            buttons.addWidget(button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self.sc_status = QLabel("")
        self.sc_status.setWordWrap(True)
        layout.addWidget(self.sc_status)

        self.load_shortcuts()
        return widget

    # ------------------------------------------------------------------
    def load_shortcuts(self) -> None:
        from ..core import shortcuts as _sc

        if not hasattr(self, "sc_table"):
            return
        self.sc_table.setRowCount(len(_sc.SHORTCUTS))
        for row, definition in enumerate(_sc.SHORTCUTS):
            current = _sc.get(definition.key)
            group = QTableWidgetItem(definition.group)
            group.setForeground(QColor("#64b5f6"))
            self.sc_table.setItem(row, 0, group)
            self.sc_table.setItem(row, 1, QTableWidgetItem(definition.label))

            shown = current or "(wyłączony)"
            value = QTableWidgetItem(shown)
            if current != definition.default:
                value.setForeground(QColor("#ffb74d"))     # zmieniony przez użytkownika
            value.setData(Qt.ItemDataRole.UserRole, definition.key)
            self.sc_table.setItem(row, 2, value)

            default_item = QTableWidgetItem(definition.default)
            default_item.setForeground(QColor("#90a4ae"))
            self.sc_table.setItem(row, 3, default_item)

    def _filter_shortcuts(self, text: str) -> None:
        """Ukrywa wiersze niepasujące do wpisanej frazy."""
        needle = (text or "").strip().lower()
        for row in range(self.sc_table.rowCount()):
            if not needle:
                self.sc_table.setRowHidden(row, False)
                continue
            haystack = " ".join(
                (self.sc_table.item(row, col).text() if self.sc_table.item(row, col) else "")
                for col in range(4)
            ).lower()
            self.sc_table.setRowHidden(row, needle not in haystack)

    def _selected_shortcut(self):
        from ..core import shortcuts as _sc

        row = self.sc_table.currentRow()
        if not (0 <= row < len(_sc.SHORTCUTS)):
            return None
        return _sc.SHORTCUTS[row]

    def _edit_shortcut(self) -> None:
        from .dialogs.shortcut_dialog import ShortcutDialog

        definition = self._selected_shortcut()
        if definition is None:
            QMessageBox.information(self, "Skróty", "Zaznacz polecenie w tabeli.")
            return
        dialog = ShortcutDialog(definition, self)
        if not dialog.exec():
            return
        self._apply_shortcut(definition.key, dialog.sequence)

    def _apply_shortcut(self, key: str, sequence: str) -> None:
        from ..core import shortcuts as _sc

        if _sc.blocks_polish_letters(sequence):
            if QMessageBox.question(
                self, "Skrót blokuje polskie znaki",
                f"Kombinacja „{sequence}” używa Alt z literą. Na polskiej "
                "klawiaturze AltGr z tą literą wpisuje polski znak "
                "(np. ę, ś, ń), więc skrót będzie „zjadał” wpisywane litery.\n\n"
                "Zapisać mimo to?",
            ) != QMessageBox.StandardButton.Yes:
                return
        conflict = _sc.find_conflict(key, sequence)
        if conflict:
            if QMessageBox.question(
                self, "Zajęty skrót",
                f"Kombinacja „{sequence}” jest już przypisana do:\n„{conflict}”.\n\n"
                "Przypisać ją mimo to? (poprzednie polecenie straci skrót)",
            ) != QMessageBox.StandardButton.Yes:
                return
            for other in _sc.SHORTCUTS:
                if other.key != key and _sc.get(other.key).lower() == sequence.lower():
                    _sc.set_key(other.key, " ")     # spacja = wyłączony
        _sc.set_key(key, sequence)
        self.load_shortcuts()
        self.app.reload_shortcuts()
        self.sc_status.setText(f"✅ Zapisano: {sequence or '(wyłączony)'}")

    def _clear_shortcut(self) -> None:
        definition = self._selected_shortcut()
        if definition is None:
            return
        from ..core import shortcuts as _sc

        _sc.set_key(definition.key, " ")            # spacja odróżnia „brak” od „domyślny”
        self.load_shortcuts()
        self.app.reload_shortcuts()
        self.sc_status.setText(f"Wyłączono skrót: {definition.label}")

    def _default_shortcut(self) -> None:
        definition = self._selected_shortcut()
        if definition is None:
            return
        from ..core import shortcuts as _sc

        _sc.set_key(definition.key, "")
        self.load_shortcuts()
        self.app.reload_shortcuts()
        self.sc_status.setText(f"Przywrócono: {definition.default}")

    def _reset_shortcuts(self) -> None:
        from ..core import shortcuts as _sc

        if QMessageBox.question(
            self, "Skróty klawiszowe",
            "Przywrócić domyślne kombinacje dla wszystkich poleceń?",
        ) != QMessageBox.StandardButton.Yes:
            return
        _sc.reset_all()
        self.load_shortcuts()
        self.app.reload_shortcuts()
        self.sc_status.setText("Przywrócono wszystkie domyślne skróty")

    def _exclusions_tab(self) -> QWidget:
        """Reguły wykluczania segmentów z tłumaczenia i statystyk."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        header = QGroupBox("🚫 Wykluczanie i automatyczne oznaczanie segmentów")
        hform = QVBoxLayout(header)
        self.excl_enabled = QCheckBox("Włącz automatyczne oznaczanie segmentów")
        self.excl_enabled.setToolTip(
            "Segmenty pasujące do reguł są oznaczane zgodnie z działaniem\n"
            "reguły:\n"
            "  🚫 pominięte — nie trafiają do tłumaczenia maszynowego, do\n"
            "     pamięci TM ani do statystyk „pozostało do zrobienia”\n"
            "  ★ przetłumaczone — uznawane za gotowe (np. wzorce CHEM*,\n"
            "     które nie wymagają tłumaczenia)\n\n"
            "Treść zawsze zostaje nietknięta i wraca do pliku przy eksporcie."
        )
        self.excl_enabled.stateChanged.connect(self._toggle_exclusions)
        hform.addWidget(self.excl_enabled)

        info = QLabel(
            "Reguły są <b>uniwersalne</b>: dowolny wzorzec (tekst, gwiazdka, zakres "
            "typu <code>TM01-TM66</code>, regex) i dowolne działanie — <b>pominięte</b> albo "
            "<b>przetłumaczone</b>. Przykład z plików gier: "
            "<code>&lt;&lt;&lt; FILE: CeladonCity/text.inc &gt;&gt;&gt;</code> to wiersz techniczny "
            "→ reguła <code>&lt;&lt;&lt; FILE:*&gt;&gt;&gt;</code> (działanie: pominięte). "
            "Inny przykład: <code>CHEM*</code> (działanie: przetłumaczone) oznacza wszystkie "
            "wzory chemiczne jako gotowe."
        )
        info.setWordWrap(True)
        info.setTextFormat(Qt.TextFormat.RichText)
        info.setStyleSheet("color: gray; font-size: 11px;")
        hform.addWidget(info)
        layout.addWidget(header)

        # --- tabela reguł -------------------------------------------------
        self.excl_group = QGroupBox("Reguły")
        rules_layout = QVBoxLayout(self.excl_group)

        self.excl_table = QTableWidget(0, 6)
        self.excl_table.setHorizontalHeaderLabels(
            ["✓", "Wzorzec", "Dopasowanie", "Działanie", "Trafienia", "Opis"])
        self.excl_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch)
        self.excl_table.horizontalHeader().setSectionResizeMode(
            5, QHeaderView.ResizeMode.Stretch)
        self.excl_table.setColumnWidth(0, 34)
        self.excl_table.setColumnWidth(2, 150)
        self.excl_table.setColumnWidth(3, 140)
        self.excl_table.setColumnWidth(4, 80)
        self.excl_table.verticalHeader().setVisible(False)
        self.excl_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.excl_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.excl_table.setAlternatingRowColors(True)
        self.excl_table.setMinimumHeight(220)
        self.excl_table.setMinimumWidth(700)
        self.excl_table.itemChanged.connect(self._on_excl_item_changed)
        self.excl_table.doubleClicked.connect(self._edit_exclusion)
        rules_layout.addWidget(self.excl_table)

        buttons = QHBoxLayout()
        add_btn = QPushButton("➕ Dodaj regułę")
        add_btn.clicked.connect(self._add_exclusion)
        edit_btn = QPushButton("✏️ Edytuj")
        edit_btn.clicked.connect(self._edit_exclusion)
        del_btn = QPushButton("🗑️ Usuń")
        del_btn.clicked.connect(self._remove_exclusion)
        preset_btn = QPushButton("📋 Gotowe wzorce…")
        preset_btn.setToolTip("Zestaw reguł typowych dla plików gier")
        preset_btn.clicked.connect(self._add_preset_exclusion)
        for button in (add_btn, edit_btn, del_btn, preset_btn):
            buttons.addWidget(button)
        buttons.addStretch(1)
        rules_layout.addLayout(buttons)
        layout.addWidget(self.excl_group)

        # --- podgląd trafień ----------------------------------------------
        preview_box = QGroupBox("👁️ Podgląd — segmenty, które zostaną wykluczone")
        pv = QVBoxLayout(preview_box)
        self.excl_preview = QListWidget()
        self.excl_preview.setAlternatingRowColors(True)
        pv.addWidget(self.excl_preview)

        self.excl_summary = QLabel("")
        self.excl_summary.setWordWrap(True)
        pv.addWidget(self.excl_summary)

        pv_row = QHBoxLayout()
        refresh_btn = QPushButton("🔄 Odśwież podgląd")
        refresh_btn.clicked.connect(self._refresh_exclusions_preview)
        apply_btn = QPushButton("✅ Zastosuj do projektu")
        apply_btn.setToolTip(
            "Oznacza pasujące segmenty zgodnie z działaniem każdej reguły "
            "(pominięte lub przetłumaczone) i przywraca te, które przestały pasować")
        apply_btn.clicked.connect(self._apply_exclusions)
        restore_btn = QPushButton("↩️ Przywróć wszystkie pominięte")
        restore_btn.setToolTip(
            "Cofa pominięcie wszystkich segmentów — także tych wykluczonych regułą.\n"
            "Reguły nie zabiorą ich ponownie, dopóki nie klikniesz „Zastosuj do projektu”."
        )
        restore_btn.clicked.connect(self._restore_all_excluded)
        reset_btn = QPushButton("🧹 Skasuj ręczne wyjątki")
        reset_btn.setToolTip(
            "Zapomina o ręcznych decyzjach (pominięciach i przywróceniach)\n"
            "i stosuje reguły od nowa."
        )
        reset_btn.clicked.connect(self._clear_manual_decisions)
        for button in (refresh_btn, restore_btn, reset_btn, apply_btn):
            button.setMinimumWidth(190)
            pv_row.addWidget(button)
        pv_row.addStretch(1)
        pv.addLayout(pv_row)
        layout.addWidget(preview_box, 1)

        self.load_exclusions()
        return widget

    # ------------------------------------------------------------------
    def _exclusions(self):
        return self.app.exclusion_set()

    def load_exclusions(self) -> None:
        """Wczytuje reguły z projektu do tabeli."""
        if not hasattr(self, "excl_table"):
            return
        rules = self._exclusions()
        self.excl_enabled.blockSignals(True)
        self.excl_enabled.setChecked(rules.enabled)
        self.excl_enabled.blockSignals(False)
        self._fill_exclusions_table()
        self._refresh_exclusions_preview()

    def _apply_panel_font(self) -> None:
        editor = getattr(self.app, "editor_tab", None)
        if editor is not None and hasattr(editor, "apply_panel_font"):
            editor.apply_panel_font()

    def _reset_panel_fonts(self) -> None:
        """Wszystkie czcionki paneli na 0 — wracają do czcionki interfejsu."""
        for key, spin in getattr(self, "panel_font_sizes", {}).items():
            self.settings.set(key, 0)
            spin.blockSignals(True)
            spin.setValue(0)
            spin.blockSignals(False)
        self._apply_panel_font()

    def _apply_ui_font(self) -> None:
        """Zmiana rozmiaru czcionki całego interfejsu (od razu, bez restartu)."""
        window = getattr(self.app, "apply_ui_font", None)
        if callable(window):
            window()
            # Spinboxy w Ustawieniach też muszą pokazać nowy stan.
            if hasattr(self, "ui_font_size"):
                self.ui_font_size.blockSignals(True)
                self.ui_font_size.setValue(self.settings.get_int("ui.font.size", 0))
                self.ui_font_size.blockSignals(False)

    def _apply_panel_layout(self) -> None:
        editor = getattr(self.app, "editor_tab", None)
        if editor is not None and hasattr(editor, "apply_panel_layout"):
            editor.apply_panel_layout()

    def _detect_codes_from_files(self) -> None:
        """Skanuje źródła otwartego projektu i wypełnia listę kodów gry."""
        from ..core.tags import detect_codes

        editor = getattr(self.app, "editor_tab", None)
        segments = editor.segments if editor and editor.segments else []
        found: dict[str, int] = {}
        for seg in segments:
            for text in (seg.source or "", seg.target or ""):
                for code in detect_codes(text):
                    found[code] = found.get(code, 0) + 1
        if not found:
            self.game_code_list.setPlaceholderText(
                "W otwartym projekcie nie znaleziono żadnych kodów")
            self.game_code_list.setFocus()
            return
        ordered = [c for c, _ in sorted(found.items(), key=lambda kv: (-kv[1], kv[0]))]
        self.game_code_list.setText(" ".join(ordered))
        self.settings.set("tm.codes.list", " ".join(ordered))

    def _fill_exclusions_table(self) -> None:
        from ..core.exclusions import MATCH_TYPES, RULE_ACTIONS

        rules = self._exclusions()
        counts = {}
        segments = self.app.editor_tab.segments if self.app.editor_tab.segments else []
        if segments:
            counts = rules.counts(segments)

        self.excl_table.blockSignals(True)
        self.excl_table.setRowCount(len(rules.rules))
        for row, rule in enumerate(rules.rules):
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            check.setCheckState(Qt.CheckState.Checked if rule.enabled
                                else Qt.CheckState.Unchecked)
            self.excl_table.setItem(row, 0, check)

            pattern_item = QTableWidgetItem(rule.pattern)
            error = rule.error()
            if error:
                pattern_item.setForeground(QColor("#ef5350"))
                pattern_item.setToolTip(error)
            self.excl_table.setItem(row, 1, pattern_item)
            self.excl_table.setItem(
                row, 2, QTableWidgetItem(MATCH_TYPES.get(rule.match_type, rule.match_type)))

            action_item = QTableWidgetItem(
                RULE_ACTIONS.get(rule.action, rule.action))
            if rule.action == "translated":
                action_item.setForeground(QColor("#66bb6a"))
            else:
                action_item.setForeground(QColor("#ef5350"))
            self.excl_table.setItem(row, 3, action_item)

            hits = QTableWidgetItem(str(counts.get(rule.pattern, 0)) if segments else "—")
            hits.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.excl_table.setItem(row, 4, hits)

            note = rule.comment + (f"  (tylko {rule.file_filter})" if rule.file_filter else "")
            self.excl_table.setItem(row, 5, QTableWidgetItem(note))
        self.excl_table.blockSignals(False)

    def _on_excl_item_changed(self, item) -> None:
        """Kliknięcie w kratkę „✓” włącza lub wyłącza regułę."""
        if item.column() != 0:
            return
        rules = self._exclusions()
        if 0 <= item.row() < len(rules.rules):
            rules.rules[item.row()].enabled = item.checkState() == Qt.CheckState.Checked
            self.app.save_exclusions()
            self._fill_exclusions_table()
            self._refresh_exclusions_preview()

    def _toggle_exclusions(self, state) -> None:
        rules = self._exclusions()
        rules.enabled = bool(state)
        self.excl_group.setEnabled(bool(state))
        self.app.save_exclusions()
        self._refresh_exclusions_preview()

    def _add_exclusion(self) -> None:
        from .dialogs.exclusion_dialog import ExclusionDialog

        dialog = ExclusionDialog(parent=self, files=self._project_file_names())
        if dialog.exec() and dialog.rule is not None:
            self._exclusions().rules.append(dialog.rule)
            self.app.save_exclusions()
            self._fill_exclusions_table()
            self._refresh_exclusions_preview()

    def _edit_exclusion(self) -> None:
        from .dialogs.exclusion_dialog import ExclusionDialog

        row = self.excl_table.currentRow()
        rules = self._exclusions()
        if not (0 <= row < len(rules.rules)):
            QMessageBox.information(self, "Wykluczenia", "Zaznacz regułę w tabeli.")
            return
        dialog = ExclusionDialog(rules.rules[row], self, self._project_file_names())
        if dialog.exec() and dialog.rule is not None:
            rules.rules[row] = dialog.rule
            self.app.save_exclusions()
            self._fill_exclusions_table()
            self._refresh_exclusions_preview()

    def _remove_exclusion(self) -> None:
        row = self.excl_table.currentRow()
        rules = self._exclusions()
        if not (0 <= row < len(rules.rules)):
            QMessageBox.information(self, "Wykluczenia", "Zaznacz regułę w tabeli.")
            return
        if QMessageBox.question(
            self, "Usuń regułę",
            f"Usunąć regułę „{rules.rules[row].pattern}”?",
        ) != QMessageBox.StandardButton.Yes:
            return
        rules.rules.pop(row)
        self.app.save_exclusions()
        self._fill_exclusions_table()
        self._refresh_exclusions_preview()

    def _add_preset_exclusion(self) -> None:
        """Dodaje regułę z listy gotowych wzorców."""
        from ..core.exclusions import BUILTIN_PRESETS, ExclusionRule

        labels = [name for name, _rule in BUILTIN_PRESETS]
        choice, ok = QInputDialog.getItem(
            self, "Gotowe wzorce", "Wybierz wzorzec do dodania:", labels, 0, False)
        if not ok or not choice:
            return
        template = BUILTIN_PRESETS[labels.index(choice)][1]
        rule = ExclusionRule.from_dict(template.to_dict())
        rule.enabled = True
        self._exclusions().rules.append(rule)
        self.app.save_exclusions()
        self._fill_exclusions_table()
        self._refresh_exclusions_preview()

    def _project_file_names(self):
        return sorted({(s.file_name or "") for s in self.app.editor_tab.segments if s.file_name})

    def _refresh_exclusions_preview(self) -> None:
        """Pokazuje, które segmenty obejmą reguły – zanim je zastosujesz."""
        if not hasattr(self, "excl_preview"):
            return
        self.excl_preview.clear()
        segments = self.app.editor_tab.segments
        if not segments:
            self.excl_summary.setText("Brak wczytanych segmentów.")
            return
        rules = self._exclusions()
        hits = rules.preview(segments)
        for index, text, description in hits[:300]:
            shown = text.replace("\n", " ⏎ ")
            item = QListWidgetItem(f"#{index + 1}   {shown}")
            item.setToolTip(description)
            self.excl_preview.addItem(item)
        percent = len(hits) * 100 / len(segments) if segments else 0
        self.excl_summary.setText(
            f"Pasuje {len(hits)} z {len(segments)} segmentów ({percent:.1f}%)"
            + ("  — wykluczanie wyłączone" if not rules.enabled else ""))
        self.excl_group.setEnabled(rules.enabled)

    def _restore_all_excluded(self) -> None:
        """Cofa pominięcie wszystkich segmentów (działanie w drugą stronę)."""
        if not self.app.editor_tab.segments:
            QMessageBox.information(self, "Wykluczenia", "Najpierw wczytaj pliki projektu.")
            return
        self.app.editor_tab.restore_all_ignored()
        self._fill_exclusions_table()
        self._refresh_exclusions_preview()

    def _clear_manual_decisions(self) -> None:
        """Kasuje ręczne wyjątki i stosuje reguły od nowa."""
        if not self.app.editor_tab.segments:
            QMessageBox.information(self, "Wykluczenia", "Najpierw wczytaj pliki projektu.")
            return
        if QMessageBox.question(
            self, "Skasuj ręczne wyjątki",
            "Zapomnieć o wszystkich ręcznych pominięciach i przywróceniach,\n"
            "a następnie zastosować reguły od nowa?",
        ) != QMessageBox.StandardButton.Yes:
            return
        self.app.editor_tab.clear_manual_exclusion_decisions()
        self._fill_exclusions_table()
        self._refresh_exclusions_preview()

    def _apply_exclusions(self) -> None:
        if not self.app.editor_tab.segments:
            QMessageBox.information(self, "Wykluczenia", "Najpierw wczytaj pliki projektu.")
            return
        self.app.save_exclusions()
        count = self.app.apply_exclusions()
        self._fill_exclusions_table()
        self._refresh_exclusions_preview()
        QMessageBox.information(
            self, "Wykluczenia",
            f"Oznaczono {count} segmentów jako pominięte.\n\n"
            "Nie trafią do tłumaczenia maszynowego, pamięci TM ani statystyk.")

    def _language_tab(self) -> QWidget:
        """Wszystkie przełączniki kontroli pisowni, języka i znaków specjalnych."""
        self._lt_worker = None
        self._lt_test_worker = None
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # --- główny wyłącznik -------------------------------------------
        master_box = QGroupBox("Kontrola języka w tłumaczeniu")
        master_form = QFormLayout(master_box)

        self.lang_master = QCheckBox("Włącz kontrolę poprawności języka")
        self.lang_master.setToolTip(
            "Główny wyłącznik. Wyłączony – żadna kontrola językowa nie działa\n"
            "(ani panel „🔤 Język”, ani kategorie „Język:” w QA)."
        )
        self.lang_master.setChecked(self.settings.get_bool("lang.check.enabled", True))
        self.lang_master.stateChanged.connect(self._toggle_lang_master)
        master_form.addRow(self.lang_master)

        note = QLabel(
            "Kontrola dotyczy <b>wyłącznie tekstu tłumaczenia</b> – tekst źródłowy "
            "nigdy nie jest sprawdzany."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: gray; font-size: 11px;")
        master_form.addRow(note)
        layout.addWidget(master_box)

        # --- zakres kontroli --------------------------------------------
        self.lang_group = QGroupBox("Co sprawdzać")
        checks_form = QFormLayout(self.lang_group)

        self.lang_auto = QCheckBox("Sprawdzaj na bieżąco (w trakcie pisania)")
        from ..core import shortcuts as _sc
        self.lang_auto.setToolTip(
            _sc.with_shortcut("check_language", "Wyłączone – kontrola tylko po naciśnięciu skrótu"))
        self.lang_auto.setChecked(self.settings.get_bool("lang.check.auto", True))
        self.lang_auto.stateChanged.connect(self._toggle_lang_auto)
        checks_form.addRow(self.lang_auto)

        self.lang_underline = QCheckBox("Podkreślaj błędy wprost w polu tłumaczenia")
        self.lang_underline.setToolTip(
            "Czerwona falka – błąd i pisownia, pomarańczowa – ostrzeżenie,\n"
            "niebieska kropkowana – uwaga. Prawy przycisk myszy pokazuje propozycje."
        )
        self.lang_underline.setChecked(self.settings.get_bool("lang.check.underline", True))
        self.lang_underline.stateChanged.connect(self._toggle_lang_underline)
        checks_form.addRow(self.lang_underline)

        self.underline_box = QGroupBox("Wygląd podkreślenia w polu tłumaczenia")
        ul_form = QFormLayout(self.underline_box)
        self.ul_style = QComboBox()
        self.ul_style.setMaximumWidth(260)
        for key, label in (
            ("wave", "Falka (jak w edytorze tekstu)"),
            ("solid", "Linia ciągła"),
            ("dash", "Kreski"),
            ("dot", "Kropki"),
            ("spell", "Falka pisowni systemu"),
        ):
            self.ul_style.addItem(label, key)
        saved_style = self.settings.get_str("lang.underline.style", "wave")
        idx = max(0, self.ul_style.findData(saved_style))
        self.ul_style.setCurrentIndex(idx)
        self.ul_style.currentIndexChanged.connect(self._on_underline_style)
        ul_form.addRow("Styl:", self.ul_style)

        self.ul_thickness = QSpinBox()
        self.ul_thickness.setRange(1, 8)
        self.ul_thickness.setSuffix(" px")
        self.ul_thickness.setMaximumWidth(120)
        self.ul_thickness.setValue(self.settings.get_int("lang.underline.thickness", 2))
        self.ul_thickness.setToolTip(
            "Grubość kreski pod błędem. Falka Qt jest zawsze cienka —\n"
            "program dorysowuje własną linię o wybranej grubości.")
        self.ul_thickness.valueChanged.connect(self._on_underline_thickness)
        ul_form.addRow("Grubość:", self.ul_thickness)

        colors_row = QHBoxLayout()
        self.ul_error_btn = self._make_underline_color_button(
            "lang.underline.error.color", "#ff5252", "Błąd")
        self.ul_warn_btn = self._make_underline_color_button(
            "lang.underline.warning.color", "#ffa726", "Ostrzeżenie")
        self.ul_info_btn = self._make_underline_color_button(
            "lang.underline.info.color", "#64b5f6", "Uwaga")
        colors_row.addWidget(QLabel("Błąd:"))
        colors_row.addWidget(self.ul_error_btn)
        colors_row.addSpacing(8)
        colors_row.addWidget(QLabel("Ostrzeżenie:"))
        colors_row.addWidget(self.ul_warn_btn)
        colors_row.addSpacing(8)
        colors_row.addWidget(QLabel("Uwaga:"))
        colors_row.addWidget(self.ul_info_btn)
        colors_row.addStretch(1)
        ul_form.addRow("Kolory:", colors_row)

        self.ul_background = QCheckBox("Dodatkowo podświetl tło wyrazu")
        self.ul_background.setToolTip(
            "Lekkie tło w kolorze podkreślenia — błąd widać także z daleka.")
        self.ul_background.setChecked(self.settings.get_bool("lang.underline.background", False))
        self.ul_background.stateChanged.connect(
            lambda st: self._set_underline_option("lang.underline.background", bool(st)))
        ul_form.addRow(self.ul_background)

        ul_hint = QLabel(
            "Zmiana jest od razu widoczna w polu tłumaczenia "
            "(czerwona falka przy literówce, grubsza linia przy większej wartości)."
        )
        ul_hint.setWordWrap(True)
        ul_hint.setStyleSheet("color: gray; font-size: 11px;")
        ul_form.addRow(ul_hint)
        self.underline_box.setEnabled(self.lang_underline.isChecked())
        checks_form.addRow(self.underline_box)

        self.lang_spelling = QCheckBox("Pisownia (na podstawie wczytanych słowników)")
        self.lang_spelling.setToolTip(
            "Wymaga słownika w zakładce „📖 Słowniki”.\n"
            "Z plikiem .aff rozpoznaje też formy odmienione."
        )
        self.lang_spelling.setChecked(self.settings.get_bool("lang.check.spelling", True))
        self.lang_spelling.stateChanged.connect(
            lambda st: self._set_lang_option("lang.check.spelling", bool(st)))
        checks_form.addRow(self.lang_spelling)

        self.lang_grammar = QCheckBox("Odmiana i gramatyka (liczebniki, zaimki, przypadki)")
        self.lang_grammar.setChecked(self.settings.get_bool("lang.check.grammar", True))
        self.lang_grammar.stateChanged.connect(
            lambda st: self._set_lang_option("lang.check.grammar", bool(st)))
        checks_form.addRow(self.lang_grammar)

        self.lang_punct = QCheckBox("Interpunkcja, spacje i powtórzenia")
        self.lang_punct.setChecked(self.settings.get_bool("lang.check.punctuation", True))
        self.lang_punct.stateChanged.connect(
            lambda st: self._set_lang_option("lang.check.punctuation", bool(st)))
        checks_form.addRow(self.lang_punct)

        self.lang_skip_caps = QCheckBox("Pomijaj wyrazy WERSALIKAMI (nazwy własne w grach)")
        self.lang_skip_caps.setToolTip(
            "MYSTERY, GIFT, STAMP CARD nie występują w słownikach –\n"
            "bez tej opcji byłyby zgłaszane przy każdym segmencie."
        )
        self.lang_skip_caps.setChecked(self.settings.get_bool("lang.check.skip.uppercase", True))
        self.lang_skip_caps.stateChanged.connect(
            lambda st: self._set_lang_option("lang.check.skip.uppercase", bool(st)))
        checks_form.addRow(self.lang_skip_caps)
        layout.addWidget(self.lang_group)

        # --- LanguageTool OFFLINE (osobna sekcja) --------------------------
        self.lt_local_group = QGroupBox("💻 LanguageTool offline — silnik na tym komputerze")
        local_form = QFormLayout(self.lt_local_group)

        self.lang_lt_local = QCheckBox("Włącz sprawdzanie offline (bez internetu)")
        self.lang_lt_local.setToolTip(
            "Silnik działa lokalnie: tekst nie opuszcza komputera, brak limitu zapytań,\n"
            "sprawdzenie zdania ~100 ms.\n"
            "Wymaga Javy oraz pakietu „language-tool-python”."
        )
        self.lang_lt_local.setChecked(self.settings.get_bool("lang.check.lt.local", False))
        self.lang_lt_local.stateChanged.connect(self._toggle_lt_local)
        local_form.addRow(self.lang_lt_local)

        self.lt_local_status = QLabel("")
        self.lt_local_status.setWordWrap(True)
        self.lt_local_status.setStyleSheet("font-size: 11px;")
        local_form.addRow(self.lt_local_status)

        self.lt_progress = QProgressBar()
        self.lt_progress.setVisible(False)
        self.lt_progress.setRange(0, 0)          # transfer bez znanego rozmiaru
        self.lt_progress.setFormat("Pobieranie silnika…")
        local_form.addRow(self.lt_progress)

        # --- wykryta Java -------------------------------------------------
        self.java_label = QLabel("")
        self.java_label.setWordWrap(True)
        self.java_label.setStyleSheet("font-size: 11px;")
        local_form.addRow("Java:", self.java_label)

        java_row = QHBoxLayout()
        self.java_path = QLineEdit(self.settings.get("lang.check.java.path", ""))
        self.java_path.setPlaceholderText("puste = wykryj automatycznie (najnowsza zainstalowana)")
        self.java_path.setToolTip(
            "Ścieżka do pliku java (np. C:\\Program Files\\Java\\jdk-26\\bin\\java.exe).\n"
            "Przydatne, gdy w PATH jest stara Java, a chcesz użyć nowszej."
        )
        self.java_path.editingFinished.connect(self._save_java_path)
        browse_java = QPushButton("📂 Wskaż…")
        browse_java.clicked.connect(self._browse_java)
        rescan_java = QPushButton("🔄 Wykryj ponownie")
        rescan_java.clicked.connect(self._refresh_lt_local_status)
        java_row.addWidget(self.java_path, 1)
        java_row.addWidget(browse_java)
        java_row.addWidget(rescan_java)
        local_form.addRow("Własna ścieżka:", java_row)

        local_buttons = QHBoxLayout()
        self.lt_download_btn = QPushButton("⬇ Pobierz silnik offline (~230 MB)")
        self.lt_download_btn.setToolTip(
            "Pobiera LanguageTool na dysk. Jednorazowo; potem działa bez internetu."
        )
        self.lt_download_btn.clicked.connect(self._download_lt_engine)
        self.lt_test_local_btn = QPushButton("🔌 Sprawdź silnik offline")
        self.lt_test_local_btn.clicked.connect(lambda: self._test_languagetool(local=True))
        self.lt_remove_btn = QPushButton("🗑️ Usuń silnik z dysku")
        self.lt_remove_btn.setToolTip("Zwalnia miejsce zajęte przez pobrany silnik")
        self.lt_remove_btn.clicked.connect(self._remove_lt_engine)
        for button in (self.lt_download_btn, self.lt_test_local_btn, self.lt_remove_btn):
            local_buttons.addWidget(button)
        local_buttons.addStretch(1)
        local_form.addRow(local_buttons)
        layout.addWidget(self.lt_local_group)

        # --- LanguageTool ONLINE (osobna sekcja) ---------------------------
        self.lt_group = QGroupBox("🌐 LanguageTool online — serwer w internecie")
        lt_form = QFormLayout(self.lt_group)

        self.lang_lt = QCheckBox("Włącz sprawdzanie przez internet")
        self.lang_lt.setToolTip(
            "Publiczne api.languagetool.org: bez klucza, limit ok. 20 zapytań na minutę.\n"
            "Tekst jest wysyłany na serwer LanguageTool."
        )
        self.lang_lt.setChecked(self.settings.get_bool("lang.check.languagetool", False))
        self.lang_lt.stateChanged.connect(self._toggle_lang_lt)
        lt_form.addRow(self.lang_lt)

        self.lang_url = QLineEdit(self.settings.get("lang.check.url", ""))
        self.lang_url.setPlaceholderText("puste = api.languagetool.org (publiczne)")
        self.lang_url.setToolTip(
            "Adres własnego serwera LanguageTool, np. http://localhost:8081/v2/check.\n"
            "Własny serwer nie ma limitu zapytań."
        )
        self.lang_url.editingFinished.connect(
            lambda: self.settings.set("lang.check.url", self.lang_url.text().strip()))
        lt_form.addRow("Serwer:", self.lang_url)

        online_buttons = QHBoxLayout()
        self.lt_test_online_btn = QPushButton("🔌 Sprawdź połączenie z serwerem")
        self.lt_test_online_btn.clicked.connect(lambda: self._test_languagetool(local=False))
        online_buttons.addWidget(self.lt_test_online_btn)
        online_buttons.addStretch(1)
        lt_form.addRow(online_buttons)

        self.lt_status = QLabel("")
        self.lt_status.setWordWrap(True)
        lt_form.addRow(self.lt_status)
        layout.addWidget(self.lt_group)

        # --- QA i tłumaczenie maszynowe ------------------------------------
        extra = QGroupBox("Kontrola języka w innych miejscach")
        extra_form = QFormLayout(extra)

        self.qa_language = QCheckBox("Zgłaszaj uwagi językowe w zakładce „✅ QA”")
        self.qa_language.setChecked(self.settings.get_bool("qa.check.language", True))
        self.qa_language.stateChanged.connect(
            lambda st: self.settings.set("qa.check.language", bool(st)))
        extra_form.addRow(self.qa_language)

        self.mt_polish = QCheckBox("Popraw interpunkcję i spacje w wyniku tłumaczenia MT")
        self.mt_polish.setToolTip(
            "Spacja przed przecinkiem, brak spacji po nim, podwójne spacje.\n"
            "Poprawki mechaniczne – nie zmieniają doboru słów."
        )
        self.mt_polish.setChecked(self.settings.get_bool("mt.polish.output", True))
        self.mt_polish.stateChanged.connect(
            lambda st: self._sync_mt_option("mt.polish.output", bool(st)))
        extra_form.addRow(self.mt_polish)

        self.ai_grammar_lang = QCheckBox("AI: wymagaj poprawnej odmiany i naturalnego stylu")
        self.ai_grammar_lang.setChecked(self.settings.get_bool("mt.ai.grammar.rules", True))
        self.ai_grammar_lang.stateChanged.connect(
            lambda st: self._sync_mt_option("mt.ai.grammar.rules", bool(st)))
        extra_form.addRow(self.ai_grammar_lang)
        layout.addWidget(extra)

        reset_row = QHBoxLayout()
        all_on = QPushButton("✅ Włącz wszystko")
        all_on.clicked.connect(lambda: self._set_all_language(True))
        all_off = QPushButton("🚫 Wyłącz wszystko")
        all_off.clicked.connect(lambda: self._set_all_language(False))
        reset_row.addWidget(all_on)
        reset_row.addWidget(all_off)
        reset_row.addStretch(1)
        layout.addLayout(reset_row)

        layout.addStretch(1)
        self._update_language_enabled()
        self._refresh_lt_local_status()
        return widget

    # ------------------------------------------------------------------
    def _set_lang_option(self, key: str, value: bool) -> None:
        self.settings.set(key, value)
        editor = getattr(self.app, "editor_tab", None)
        if editor is not None and hasattr(editor, "check_language"):
            editor.check_language(force=True)

    def _toggle_lang_underline(self, state) -> None:
        enabled = bool(state)
        self.settings.set("lang.check.underline", enabled)
        if hasattr(self, "underline_box"):
            self.underline_box.setEnabled(self.lang_master.isChecked() and enabled)
        self._refresh_lang_underline()

    def _make_underline_color_button(self, key: str, default: str, title: str) -> QPushButton:
        btn = QPushButton()
        btn.setFixedSize(64, 28)
        btn.setToolTip(f"Kliknij, aby zmienić kolor: {title}")
        btn.setProperty("sc_key", key)
        btn.setProperty("sc_default", default)
        self._paint_color_button(btn, self.settings.get_str(key, default) or default)
        btn.clicked.connect(lambda _=False, b=btn, t=title: self._pick_underline_color(b, t))
        return btn

    @staticmethod
    def _paint_color_button(btn: QPushButton, color: str) -> None:
        btn.setProperty("sc_color", color)
        btn.setText(color)
        btn.setStyleSheet(
            f"QPushButton {{ background: {color}; color: #fff; border: 1px solid #666;"
            f" border-radius: 4px; padding: 2px 6px; }}"
        )

    def _pick_underline_color(self, btn: QPushButton, title: str) -> None:
        current = QColor(btn.property("sc_color") or btn.property("sc_default") or "#ff5252")
        chosen = QColorDialog.getColor(current, self, f"Kolor podkreślenia — {title}")
        if not chosen.isValid():
            return
        hex_color = chosen.name()
        self.settings.set(btn.property("sc_key"), hex_color)
        self._paint_color_button(btn, hex_color)
        self._refresh_lang_underline()

    def _on_underline_style(self, _index: int) -> None:
        key = self.ul_style.currentData()
        if isinstance(key, str) and key:
            self.settings.set("lang.underline.style", key)
            self._refresh_lang_underline()

    def _on_underline_thickness(self, value: int) -> None:
        self.settings.set("lang.underline.thickness", int(value))
        self._refresh_lang_underline()

    def _set_underline_option(self, key: str, value) -> None:
        self.settings.set(key, value)
        self._refresh_lang_underline()

    def _refresh_lang_underline(self) -> None:
        editor = getattr(self.app, "editor_tab", None)
        if editor is None:
            return
        issues = getattr(editor, "_lang_issues", None) or []
        if hasattr(editor, "highlight_language_issues"):
            editor.highlight_language_issues(issues)

    def _sync_mt_option(self, key: str, value: bool) -> None:
        """Ustawienie występuje w dwóch zakładkach – utrzymujemy zgodność."""
        self.settings.set(key, value)
        twin = {"mt.polish.output": getattr(self, "polish_output", None),
                "mt.ai.grammar.rules": getattr(self, "ai_grammar", None)}.get(key)
        if twin is not None and twin.isChecked() != value:
            twin.blockSignals(True)
            twin.setChecked(value)
            twin.blockSignals(False)

    def _toggle_lang_master(self, state) -> None:
        self.settings.set("lang.check.enabled", bool(state))
        self._update_language_enabled()
        editor = getattr(self.app, "editor_tab", None)
        if editor is not None and hasattr(editor, "check_language"):
            if state:
                editor.check_language(force=True)
            else:
                editor.lang_list.clear()
                editor.clear_language_highlight()
                editor.lang_status.setText("Kontrola języka wyłączona w Ustawieniach")

    def _update_language_enabled(self) -> None:
        """Wyszarza opcje szczegółowe, gdy główny wyłącznik jest wyłączony."""
        on = self.lang_master.isChecked()
        self.lang_group.setEnabled(on)
        self.lt_group.setEnabled(on)
        self.lt_local_group.setEnabled(on)
        if hasattr(self, "underline_box"):
            self.underline_box.setEnabled(on and self.lang_underline.isChecked())

    def _set_all_language(self, enabled: bool) -> None:
        """Jeden przycisk włącza/wyłącza wszystkie kontrole językowe."""
        self.lang_master.setChecked(enabled)
        for box, key in (
            (self.lang_auto, "lang.check.auto"),
            (self.lang_underline, "lang.check.underline"),
            (self.lang_spelling, "lang.check.spelling"),
            (self.lang_grammar, "lang.check.grammar"),
            (self.lang_punct, "lang.check.punctuation"),
            (self.qa_language, "qa.check.language"),
        ):
            box.setChecked(enabled)
            self.settings.set(key, enabled)
        # LanguageTool zostawiamy wyłączony – wymaga internetu albo pobrania silnika
        if not enabled:
            self.lang_lt.setChecked(False)
            self.lang_lt_local.setChecked(False)
        self._update_language_enabled()

    def _toggle_lt_local(self, state) -> None:
        """Włącza tryb offline. Offline i online wykluczają się wzajemnie."""
        from ..core.langcheck import LocalLanguageTool

        enabled = bool(state)
        self.settings.set("lang.check.lt.local", enabled)
        if enabled:
            # Włączony offline oznacza, że LanguageTool ma działać – ustawiamy
            # wspólny przełącznik, a wersję sieciową wyłączamy.
            self.settings.set("lang.check.languagetool", True)
            if self.lang_lt.isChecked():
                self.lang_lt.blockSignals(True)
                self.lang_lt.setChecked(False)
                self.lang_lt.blockSignals(False)
        else:
            LocalLanguageTool.shutdown()
            if not self.lang_lt.isChecked():
                self.settings.set("lang.check.languagetool", False)
        self._refresh_lt_local_status()
        self._sync_editor_lt()

    def _toggle_lang_lt(self, state) -> None:
        """Włącza tryb online (i wyłącza offline, żeby nie działały naraz)."""
        from ..core.langcheck import LocalLanguageTool

        enabled = bool(state)
        if enabled and self.lang_lt_local.isChecked():
            self.lang_lt_local.blockSignals(True)
            self.lang_lt_local.setChecked(False)
            self.lang_lt_local.blockSignals(False)
            self.settings.set("lang.check.lt.local", False)
            LocalLanguageTool.shutdown()
            self._refresh_lt_local_status()
        self.settings.set("lang.check.languagetool", enabled)
        self._sync_editor_lt()

    def _sync_editor_lt(self) -> None:
        """Utrzymuje zgodność z przełącznikiem w panelu „🔤 Język”."""
        editor = getattr(self.app, "editor_tab", None)
        if editor is not None and hasattr(editor, "lang_lt"):
            active = self.settings.get_bool("lang.check.languagetool", False)
            editor.lang_lt.blockSignals(True)
            editor.lang_lt.setChecked(active)
            editor.lang_lt.blockSignals(False)

    def _save_java_path(self) -> None:
        self.settings.set("lang.check.java.path", self.java_path.text().strip())
        self._refresh_lt_local_status()

    def _browse_java(self) -> None:
        """Pozwala wskazać konkretny plik wykonywalny Javy."""
        from PyQt6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getOpenFileName(
            self, "Wskaż plik java", "",
            "java.exe (java.exe);;Plik java (java);;Wszystkie pliki (*)")
        if not path:
            return
        from ..core.langcheck import LocalLanguageTool

        major, _minor = LocalLanguageTool.java_version(path)
        if not major:
            QMessageBox.warning(self, "Java",
                                "Nie udało się odczytać wersji z tego pliku.")
            return
        self.java_path.setText(path)
        self._save_java_path()
        QMessageBox.information(self, "Java", f"Wybrano Javę {major}.")

    def _refresh_lt_local_status(self) -> None:
        """Opisuje stan silnika offline i dostosowuje przyciski."""
        from ..core.langcheck import LocalLanguageTool

        report = LocalLanguageTool.java_report()
        self.java_label.setText(report)
        self.java_label.setStyleSheet(
            "font-size: 11px; color: %s;" % ("#ef5350" if report.startswith("❌")
                                             else "#ffa726" if "⚠️" in report else "#66bb6a"))

        available, message = LocalLanguageTool.is_available()
        downloaded = LocalLanguageTool.is_downloaded()

        if not available:
            self.lt_local_status.setText(f"⚠️ {message}")
            self.lt_local_status.setStyleSheet("color: #ffa726; font-size: 11px;")
        elif downloaded:
            size = LocalLanguageTool.installed_size_mb()
            self.lt_local_status.setText(
                f"✅ Silnik pobrany ({size:.0f} MB) — sprawdzanie działa bez internetu.")
            self.lt_local_status.setStyleSheet("color: #66bb6a; font-size: 11px;")
        else:
            self.lt_local_status.setText(
                "ℹ️ Silnik nie jest jeszcze pobrany. Kliknij „⬇ Pobierz silnik offline” — "
                "jednorazowy transfer ok. 230 MB.")
            self.lt_local_status.setStyleSheet("color: gray; font-size: 11px;")

        self.lt_download_btn.setEnabled(available and not downloaded)
        self.lt_download_btn.setText(
            "✅ Silnik pobrany" if downloaded else "⬇ Pobierz silnik offline (~230 MB)")
        self.lt_remove_btn.setEnabled(downloaded)
        self.lt_test_local_btn.setEnabled(available)

    def _download_lt_engine(self) -> None:
        """Pobiera silnik offline w tle (okno pozostaje responsywne)."""
        from ..core.langcheck import LocalLanguageTool
        from .workers import LTDownloadWorker

        available, message = LocalLanguageTool.is_available()
        if not available:
            QMessageBox.warning(self, "LanguageTool offline", message)
            return
        if QMessageBox.question(
            self, "Pobierz silnik offline",
            "Pobrać silnik LanguageTool (~230 MB, po rozpakowaniu ok. 500 MB)?\n\n"
            "Jednorazowo — potem sprawdzanie działa bez internetu i bez limitów.",
        ) != QMessageBox.StandardButton.Yes:
            return

        self.lt_progress.setVisible(True)
        self.lt_progress.setRange(0, 0)          # dopóki nie znamy rozmiaru
        self.lt_progress.setFormat("Łączenie z serwerem…")
        self.lt_download_btn.setEnabled(False)
        self.lt_local_status.setText("⏳ Pobieranie silnika… to może potrwać kilka minut.")
        self.lt_local_status.setStyleSheet("color: gray; font-size: 11px;")

        worker = LTDownloadWorker(parent=self)

        def on_progress(done: int, total: int) -> None:
            """Pokazuje rzeczywisty postęp: procenty i megabajty."""
            done_mb = done / 1024 / 1024
            if total > 0:
                total_mb = total / 1024 / 1024
                percent = int(done * 100 / total)
                self.lt_progress.setRange(0, total)
                self.lt_progress.setValue(done)
                self.lt_progress.setFormat(
                    f"Pobieranie silnika: %p%   ({done_mb:.1f} / {total_mb:.1f} MB)")
                self.lt_local_status.setText(
                    f"⏳ Pobieranie… {percent}%  ({done_mb:.1f} / {total_mb:.1f} MB)")
            else:
                # serwer nie podał rozmiaru – pokazujemy same megabajty
                self.lt_progress.setRange(0, 0)
                self.lt_progress.setFormat(f"Pobieranie silnika… {done_mb:.1f} MB")
                self.lt_local_status.setText(f"⏳ Pobieranie… {done_mb:.1f} MB")

        def on_done(ok: bool, error: str) -> None:
            if ok:
                self.lt_progress.setRange(0, 100)
                self.lt_progress.setValue(100)
                self.lt_progress.setFormat("Rozpakowywanie… gotowe")
            self.lt_progress.setVisible(False)
            self._lt_worker = None
            self._refresh_lt_local_status()
            if ok:
                QMessageBox.information(
                    self, "LanguageTool offline",
                    "Silnik pobrany. Zaznacz „Włącz sprawdzanie offline”, aby z niego korzystać.")
                self.lang_lt_local.setChecked(True)
            else:
                QMessageBox.warning(self, "LanguageTool offline",
                                    f"Nie udało się pobrać silnika:\n\n{error}")

        worker.progress.connect(on_progress)
        worker.finished_download.connect(on_done)
        self._lt_worker = worker
        worker.start()

    def _remove_lt_engine(self) -> None:
        """Usuwa pobrany silnik, zwalniając miejsce na dysku."""
        from ..core.langcheck import LocalLanguageTool

        size = LocalLanguageTool.installed_size_mb()
        if QMessageBox.question(
            self, "Usuń silnik offline",
            f"Usunąć pobrany silnik LanguageTool ({size:.0f} MB)?\n"
            "Sprawdzanie offline przestanie działać do czasu ponownego pobrania.",
        ) != QMessageBox.StandardButton.Yes:
            return
        if LocalLanguageTool.remove_engine():
            self.lang_lt_local.setChecked(False)
            self.app.show_status("Usunięto silnik LanguageTool offline")
        self._refresh_lt_local_status()

    def _test_languagetool(self, local: bool = False) -> None:
        """Sprawdza działanie wybranego trybu – w tle, bez zamrażania okna."""
        from ..core.langcheck import LocalLanguageTool
        from .workers import LTTestWorker

        if local:
            available, message = LocalLanguageTool.is_available()
            if not available:
                self.lt_local_status.setText(f"❌ {message}")
                self.lt_local_status.setStyleSheet("color: #ef5350; font-size: 11px;")
                return
            if not LocalLanguageTool.is_downloaded():
                self.lt_local_status.setText(
                    "⏳ Pierwsze uruchomienie pobiera silnik (~230 MB) – to może potrwać…")
            else:
                self.lt_local_status.setText("⏳ Uruchamianie silnika offline…")
            self.lt_local_status.setStyleSheet("color: gray; font-size: 11px;")
            self.lt_test_local_btn.setEnabled(False)
        else:
            self.lt_status.setText("⏳ Sprawdzanie połączenia z serwerem…")
            self.lt_test_online_btn.setEnabled(False)

        worker = LTTestWorker(local, self.lang_url.text().strip(), parent=self)

        def on_done(ok: bool, count: int, error: str) -> None:
            self._lt_test_worker = None
            if local:
                self.lt_test_local_btn.setEnabled(True)
                if ok:
                    self.lt_local_status.setText(
                        f"✅ Silnik offline działa — {count} uwag dla zdania testowego. "
                        "Internet nie jest potrzebny.")
                    self.lt_local_status.setStyleSheet("color: #66bb6a; font-size: 11px;")
                else:
                    self.lt_local_status.setText(f"❌ {error}")
                    self.lt_local_status.setStyleSheet("color: #ef5350; font-size: 11px;")
                self.lt_download_btn.setEnabled(
                    LocalLanguageTool.is_available()[0] and not LocalLanguageTool.is_downloaded())
                self.lt_remove_btn.setEnabled(LocalLanguageTool.is_downloaded())
            else:
                self.lt_test_online_btn.setEnabled(True)
                self.lt_status.setText(
                    f"✅ Połączenie działa — serwer zwrócił {count} uwag dla zdania testowego."
                    if ok else f"❌ {error}")

        worker.finished_test.connect(on_done)
        self._lt_test_worker = worker
        worker.start()

    def _tm_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        box = QGroupBox("🔍 Podpowiedzi z pamięci TM (dopasowania rozmyte)")
        form = QFormLayout(box)

        self.fuzzy = QSpinBox()
        self.fuzzy.setMaximumWidth(140)
        self.fuzzy.setRange(30, 100)
        self.fuzzy.setSuffix(" %")
        self.fuzzy.setValue(self.settings.get_int("fuzzy.threshold", 70))
        self.fuzzy.valueChanged.connect(lambda v: self.settings.set("fuzzy.threshold", v))
        form.addRow("Próg dopasowania:", self.fuzzy)

        self.max_results = QSpinBox()
        self.max_results.setMaximumWidth(140)
        self.max_results.setRange(1, 50)
        self.max_results.setValue(self.settings.get_int("tm.max.results", 10))
        self.max_results.valueChanged.connect(lambda v: self.settings.set("tm.max.results", v))
        form.addRow("Maks. liczba wyników:", self.max_results)

        self.tm_enabled = QCheckBox("Włącz podpowiedzi z pamięci TM")
        self.tm_enabled.setToolTip(
            "Główny wyłącznik podpowiedzi. Wyłączony – panel „💡 Dopasowania TM”\n"
            "pozostaje pusty, a program nie przeszukuje pamięci przy zmianie segmentu."
        )
        self.tm_enabled.setChecked(self.settings.get_bool("tm.lookup.enabled", True))
        self.tm_enabled.stateChanged.connect(
            lambda st: self.settings.set("tm.lookup.enabled", bool(st)))
        form.insertRow(0, self.tm_enabled)

        self.autosave_tmx = QCheckBox("Zapisuj pamięć projektu do pliku TMX przy zapisie (Ctrl+S)")
        self.autosave_tmx.setToolTip(
            "Baza SQLite jest formatem roboczym (szybkie wyszukiwanie).\n"
            "Ta opcja dodatkowo zrzuca pamięć do tm/project_tm.tmx – formatu,\n"
            "który otworzysz w innym narzędziu CAT."
        )
        self.autosave_tmx.setChecked(self.settings.get_bool("tm.autosave.tmx", True))
        self.autosave_tmx.stateChanged.connect(
            lambda st: self.settings.set("tm.autosave.tmx", bool(st))
        )
        form.addRow(self.autosave_tmx)

        self.adapt_tags = QCheckBox("Dopasowuj tagi i znaczniki do bieżącego segmentu")
        self.adapt_tags.setChecked(self.settings.get_bool("tm.adapt.tags", True))
        self.adapt_tags.stateChanged.connect(lambda s: self.settings.set("tm.adapt.tags", bool(s)))
        form.addRow(self.adapt_tags)

        self.adapt_codes = QCheckBox("Dopasowuj przełamania (\\n, \\p) w podpowiedziach do oryginału")
        self.adapt_codes.setToolTip(
            "Wpis w TM ma np. angielski z przełamaniami, a polskie tłumaczenie\n"
            "bez znaczników. Gdy ta opcja jest włączona, program wstawia \\n i \\p\n"
            "do podpowiedzi tak, aby linie miały zbliżoną szerokość co oryginał.\n\n"
            "Możesz też dopasować ręcznie: klik prawym w siatce →\n"
            "„⇢ Dopasuj znaczniki do oryginału” (działa na zaznaczonych wierszach).")
        self.adapt_codes.setChecked(self.settings.get_bool("tm.adapt.codes", True))
        self.adapt_codes.stateChanged.connect(lambda s: self.settings.set("tm.adapt.codes", bool(s)))
        form.addRow(self.adapt_codes)

        codes_row = QWidget()
        codes_form = QHBoxLayout(codes_row)
        codes_form.setContentsMargins(0, 0, 0, 0)
        self.adapt_line_codes = QLineEdit()
        self.adapt_line_codes.setPlaceholderText("\\n \\l")
        self.adapt_line_codes.setToolTip(
            "Kody przełamania WIERSZA — do wyboru, w zależności od gry.\n"
            "Wpisz literalne znaczniki rozdzielone spacjami (backslash + znak):\n"
            "domyślnie \\n i \\l. Np. dla innej gry: \\N \\L albo \\nl")
        self.adapt_para_codes = QLineEdit()
        self.adapt_para_codes.setPlaceholderText("\\p")
        self.adapt_para_codes.setToolTip(
            "Kody przełamania AKAPITU / strony dialogu — do wyboru.\n"
            "Domyślnie \\p. Np. dla innej gry: \\P albo \\page")
        codes_form.addWidget(QLabel("Wiersz:"))
        codes_form.addWidget(self.adapt_line_codes, 1)
        codes_form.addWidget(QLabel("Akapit:"))
        codes_form.addWidget(self.adapt_para_codes, 1)
        self.adapt_line_codes.setText(self.settings.get_str("tm.adapt.line.codes", "\\n \\l"))
        self.adapt_para_codes.setText(self.settings.get_str("tm.adapt.para.codes", "\\p"))
        self.adapt_line_codes.editingFinished.connect(
            lambda: self.settings.set("tm.adapt.line.codes", self.adapt_line_codes.text().strip()))
        self.adapt_para_codes.editingFinished.connect(
            lambda: self.settings.set("tm.adapt.para.codes", self.adapt_para_codes.text().strip()))
        codes_list_row = QWidget()
        codes_list_form = QHBoxLayout(codes_list_row)
        codes_list_form.setContentsMargins(0, 0, 0, 0)
        self.game_code_list = QLineEdit()
        self.game_code_list.setPlaceholderText(
            "np. \\n \\l {VAR} <<TAG>> — spacjami albo liniami")
        self.game_code_list.setToolTip(
            "Lista wszystkich kodów gry, które mają znaczenie (do wklejenia).\\n"
            "Wklej np. skopiowaną z dokumentacji listę — program rozpozna kody\\n"
            "escape (\\n, \\N, \\x1B) oraz znaczniki w klamrach/nawiasach ({VAR},\\n"
            "<<TAG>>). Jeśli pole jest puste, kody są WYKRYWANE AUTOMATYCZNIE\\n"
            "z tekstu źródłowego bieżącego segmentu — nic nie musisz wpisywać.")
        self.detect_codes_btn = QPushButton("Auto-wykryj z pliku")
        self.detect_codes_btn.setToolTip(
            "Skanuje tekst źródłowy otwartego projektu i wpisywa tu wszystkie\\n"
            "znaczniki, które program rozpoznał jako kody gry.")
        self.detect_codes_btn.clicked.connect(self._detect_codes_from_files)
        codes_list_form.addWidget(QLabel("Lista kodów:"))
        codes_list_form.addWidget(self.game_code_list, 1)
        codes_list_form.addWidget(self.detect_codes_btn)
        self.game_code_list.setText(self.settings.get_str("tm.codes.list", ""))
        self.game_code_list.editingFinished.connect(
            lambda: self.settings.set("tm.codes.list", self.game_code_list.text().strip()))

        self.adapt_codes_smart = QCheckBox(
            "Ulepszona lokalizacja przełamania: dopasuj wyrazy tłumaczenia do wierszy oryginału")
        self.adapt_codes_smart.setToolTip(
            "Włączone (domyślnie): program pasuje wyrazy tłumaczenia do wierszy\n"
            "oryginału i wstawia kod tam, gdzie faktycznie leży ich odpowiednik.\n"
            "Wyłączone: klasyczny podział proporcjonalny do długości wierszy.")
        self.adapt_codes_smart.setChecked(
            self.settings.get_bool("tm.adapt.codes.smart", True))
        self.adapt_codes_smart.stateChanged.connect(
            lambda s: self.settings.set("tm.adapt.codes.smart", bool(s)))

        self.fix_double_bs = QCheckBox(
            "Poprawiaj podwójne backslashy przed kodami (\\\\n → \\n) przy wczytywaniu plików")
        self.fix_double_bs.setToolTip(
            "Niektóre ekstraktyory zapisują kody z podwójnym backslashem\n"
            "(\\\\n zamiast \\n). Włączona opcja kurczy je do jednego już przy\n"
            "otwieraniu pliku — kody są potem dopasowywane i zapisywane\n"
            "w prawidłowej postaci.")
        self.fix_double_bs.setChecked(
            self.settings.get_bool("tm.codes.fix.double", True))
        self.fix_double_bs.stateChanged.connect(
            lambda s: self.settings.set("tm.codes.fix.double", bool(s)))

        self.fix_long_lines = QCheckBox(
            "Doklejaj kod wiersza (\n), gdy tłumaczenie jest dłuższe niż najdłuższa linia oryginału")
        self.fix_long_lines.setToolTip(
            "Oryginał bez przełamania, a tłumaczenie mu wyrosło? Program łamie\n"
            "tłumaczenie przy spacji tak, by każda linia mieściła się w szerokości\n"
            "oryginału — w grze za długi wiersz nie wyświetli się w całości.\n"
            "Działa w podpowiedziach TM, w dopasowaniu zdań i w akcji „⇢ Dopasuj\n"
            "znaczniki do oryginału”.")
        self.fix_long_lines.setChecked(
            self.settings.get_bool("tm.adapt.long.lines", True))
        self.fix_long_lines.stateChanged.connect(
            lambda s: self.settings.set("tm.adapt.long.lines", bool(s)))


        codes_box = QGroupBox("Kody do dopasowania (dowolne, zależne od gry)")
        cb_l = QVBoxLayout(codes_box)
        cb_l.setContentsMargins(8, 4, 8, 4)
        cb_l.addWidget(codes_row)
        cb_l.addWidget(codes_list_row)
        cb_l.addWidget(self.adapt_codes_smart)
        cb_l.addWidget(self.fix_double_bs)
        cb_l.addWidget(self.fix_long_lines)
        form.addRow(codes_box)

        # --- panel prawy: układ + widoczność ---

        self.filter_english = QCheckBox("Ukrywaj wpisy nieprzetłumaczone (tłumaczenie ≈ źródło)")
        self.filter_english.setToolTip(
            "Dotyczy PODPOWIEDZI: wpisy, gdzie tłumaczenie jest kopią źródła,\n"
            "nie pojawią się na liście dopasowań. Same wpisy zostają w pamięci.")
        self.filter_english.setChecked(self.settings.get_bool("tm.filter.english", True))
        self.filter_english.stateChanged.connect(lambda s: self.settings.set("tm.filter.english", bool(s)))
        form.addRow(self.filter_english)

        self.reject_untranslated = QCheckBox(
            "Nie zapisuj do TM tekstów, które zostały w języku źródłowym")
        self.reject_untranslated.setToolTip(
            "Pilnuje, żeby w pamięci były wyłącznie prawdziwe tłumaczenia.\n"
            "Program rozpoznaje język po polskich znakach i typowych wyrazach:\n"
            "„Save the game” nie trafi do TM, ale „CINNABAR GYM” albo\n"
            "„inni TRENERZY” już tak — nazwy własne nie są odrzucane.\n\n"
            "Działa przy zapisie segmentu (Ctrl+Shift+S), imporcie TMX\n"
            "i w generatorze TM z plików."
        )
        self.reject_untranslated.setChecked(
            self.settings.get_bool("tm.reject.untranslated", False))
        self.reject_untranslated.stateChanged.connect(
            lambda s: self.settings.set("tm.reject.untranslated", bool(s)))
        form.addRow(self.reject_untranslated)

        layout.addWidget(box)

        # ---- Dopasowanie zdań (osobna, opisana sekcja) ----------------
        sentence_box = QGroupBox("🔗 Dopasowanie zdań (fragmenty i linie \\n, \\p)")
        sform = QFormLayout(sentence_box)

        desc = QLabel(
            "Szuka w pamięci fragmentów i pojedynczych linii bieżącego segmentu — przydatne, "
            "gdy zdanie zostało rozbite inaczej niż w TM (pliki gier, napisy).\n"
            "⚠️ Przy dużych pamięciach funkcja jest kosztowna, dlatego domyślnie jest wyłączona."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: gray;")
        sform.addRow(desc)

        self.sentence_matching = QCheckBox(
            "Włącz składanie tłumaczenia z fragmentów (dopasowanie zdań)")
        self.sentence_matching.setChecked(
            self.settings.get_bool("tm.sentence.matching.enabled", False)
        )
        self.sentence_matching.stateChanged.connect(self._on_sentence_toggled)
        sform.addRow(self.sentence_matching)

        self.line_threshold = QSpinBox()
        self.line_threshold.setMaximumWidth(140)
        self.line_threshold.setRange(40, 100)
        self.line_threshold.setSuffix(" %")
        self.line_threshold.setValue(self.settings.get_int("tm.sentence.line.threshold", 65))
        self.line_threshold.setToolTip(
            "Jak podobna musi być linia z pamięci, aby pojawiła się w podpowiedziach."
        )
        self.line_threshold.valueChanged.connect(
            lambda v: self.settings.set("tm.sentence.line.threshold", v)
        )
        sform.addRow("Minimalne podobieństwo fragmentu:", self.line_threshold)

        self.sentence_max_units = QSpinBox()
        self.sentence_max_units.setMaximumWidth(160)
        self.sentence_max_units.setRange(1000, 500000)
        self.sentence_max_units.setSingleStep(5000)
        self.sentence_max_units.setValue(self.settings.get_int("tm.sentence.max.units", 20000))
        self.sentence_max_units.setToolTip(
            "Powyżej tylu wpisów w pamięci dopasowanie zdań jest pomijane,\n"
            "aby program pozostał płynny."
        )
        self.sentence_max_units.valueChanged.connect(
            lambda v: self.settings.set("tm.sentence.max.units", v)
        )
        sform.addRow("Wyłącz, gdy pamięć przekracza:", self.sentence_max_units)

        self.use_translated = QCheckBox(
            "Szukaj fragmentów także w segmentach już przetłumaczonych w tym projekcie")
        self.use_translated.setToolTip(
            "Segmenty przetłumaczone w bieżącej sesji są widoczne w podpowiedziach\n"
            "jeszcze zanim zapiszesz je do pamięci TM. Zwiększa obciążenie."
        )
        self.use_translated.setChecked(self.settings.get_bool("tm.sentence.use.translated", False))
        self.use_translated.stateChanged.connect(
            lambda st: self.settings.set("tm.sentence.use.translated", bool(st))
        )
        sform.addRow(self.use_translated)

        self.sentence_auto = QCheckBox(
            "Wstawiaj złożone tłumaczenie automatycznie do pustego segmentu")
        self.sentence_auto.setChecked(self.settings.get_bool("tm.sentence.auto.insert", False))
        self.sentence_auto.stateChanged.connect(
            lambda st: self.settings.set("tm.sentence.auto.insert", bool(st))
        )
        sform.addRow(self.sentence_auto)

        self.sentence_auto_threshold = QSpinBox()
        self.sentence_auto_threshold.setMaximumWidth(140)
        self.sentence_auto_threshold.setRange(50, 100)
        self.sentence_auto_threshold.setSuffix(" %")
        self.sentence_auto_threshold.setValue(
            self.settings.get_int("tm.sentence.auto.threshold", 90)
        )
        self.sentence_auto_threshold.valueChanged.connect(
            lambda v: self.settings.set("tm.sentence.auto.threshold", v)
        )
        sform.addRow("   ↳ minimalna zgodność złożenia:", self.sentence_auto_threshold)

        layout.addWidget(sentence_box)
        self._sentence_widgets = [
            self.line_threshold, self.sentence_max_units, self.use_translated,
            self.sentence_auto, self.sentence_auto_threshold,
        ]
        self._update_sentence_enabled()


        auto = QGroupBox("✍️ Automatyczne wstawianie podpowiedzi do segmentu")
        aform = QFormLayout(auto)
        self.auto_insert = QCheckBox(
            "Wstawiaj najlepsze dopasowanie TM do pustego segmentu przy jego otwarciu")
        self.auto_insert.setChecked(self.settings.get_bool("auto.insert.enabled", True))
        self.auto_insert.stateChanged.connect(lambda s: self.settings.set("auto.insert.enabled", bool(s)))
        aform.addRow(self.auto_insert)

        self.auto_threshold = QSpinBox()
        self.auto_threshold.setMaximumWidth(140)
        self.auto_threshold.setRange(50, 100)
        self.auto_threshold.setSuffix(" %")
        self.auto_threshold.setValue(self.settings.get_int("auto.insert.threshold", 80))
        self.auto_threshold.valueChanged.connect(lambda v: self.settings.set("auto.insert.threshold", v))
        aform.addRow("   ↳ minimalna zgodność dopasowania:", self.auto_threshold)

        self.auto_insert_overwrite = QCheckBox(
            "Nadpisuj istniejące tłumaczenie (domyślnie tylko puste segmenty)")
        self.auto_insert_overwrite.setToolTip(
            "Ostrożnie: włączone – automat zastąpi tekst, który już wpisałeś."
        )
        self.auto_insert_overwrite.setChecked(
            self.settings.get_bool("auto.insert.overwrite", False))
        self.auto_insert_overwrite.stateChanged.connect(
            lambda st: self.settings.set("auto.insert.overwrite", bool(st)))
        aform.addRow(self.auto_insert_overwrite)

        self.auto_save_tm = QCheckBox(
            "Zapisuj zatwierdzony segment do pamięci TM (Ctrl+Enter)")
        self.auto_save_tm.setToolTip(
            "Wyłączone – Ctrl+Enter tylko zatwierdza segment, bez dopisywania do pamięci."
        )
        self.auto_save_tm.setChecked(self.settings.get_bool("tm.auto.add", True))
        self.auto_save_tm.stateChanged.connect(
            lambda st: self.settings.set("tm.auto.add", bool(st)))
        aform.addRow(self.auto_save_tm)

        layout.addWidget(auto)

        onload = QGroupBox("⚡ Automatyka po wczytaniu plików do projektu")
        oform = QFormLayout(onload)

        self.auto_apply = QCheckBox("Uzupełnij tłumaczenia z pamięci TM dla wszystkich segmentów")
        self.auto_apply.setChecked(self.settings.get_bool("auto.apply.on.load", False))
        self.auto_apply.stateChanged.connect(lambda st: self.settings.set("auto.apply.on.load", bool(st)))
        oform.addRow(self.auto_apply)

        self.auto_apply_threshold = QSpinBox()
        self.auto_apply_threshold.setMaximumWidth(140)
        self.auto_apply_threshold.setRange(50, 100)
        self.auto_apply_threshold.setSuffix(" %")
        self.auto_apply_threshold.setValue(self.settings.get_int("auto.apply.on.load.threshold", 80))
        self.auto_apply_threshold.valueChanged.connect(
            lambda v: self.settings.set("auto.apply.on.load.threshold", v)
        )
        oform.addRow("   ↳ minimalna zgodność dopasowania:", self.auto_apply_threshold)

        self.auto_mt = QCheckBox("Następnie przetłumacz maszynowo segmenty bez dopasowania")
        self.auto_mt.setToolTip("Używa silnika wybranego w zakładce „Tłumaczenie maszynowe”.")
        self.auto_mt.setChecked(self.settings.get_bool("auto.mt.on.load", False))
        self.auto_mt.stateChanged.connect(lambda st: self.settings.set("auto.mt.on.load", bool(st)))
        oform.addRow(self.auto_mt)

        self.auto_confirm = QCheckBox("Pytaj o zgodę przed uruchomieniem automatyki")
        self.auto_confirm.setChecked(self.settings.get_bool("auto.load.confirm", True))
        self.auto_confirm.stateChanged.connect(lambda st: self.settings.set("auto.load.confirm", bool(st)))
        oform.addRow(self.auto_confirm)

        layout.addWidget(onload)
        layout.addStretch(1)
        return widget

    def _on_sentence_toggled(self, state) -> None:
        self.settings.set("tm.sentence.matching.enabled", bool(state))
        self._update_sentence_enabled()
        editor = getattr(self.app, "editor_tab", None)
        if editor is not None and hasattr(editor, "sync_sentence_toggle"):
            editor.sync_sentence_toggle()

    def _update_sentence_enabled(self) -> None:
        """Wygasza ustawienia szczegółowe, gdy dopasowanie zdań jest wyłączone."""
        on = self.sentence_matching.isChecked()
        for widget in getattr(self, "_sentence_widgets", []):
            widget.setEnabled(on)

    def _mt_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        box = QGroupBox("Silnik tłumaczenia maszynowego")
        form = QFormLayout(box)
        self.engine_combo = QComboBox()
        for key, label in ENGINES:
            self.engine_combo.addItem(label, key)
        current = self.app.mt.engine
        idx = next((i for i, (k, _l) in enumerate(ENGINES) if k == current), 0)
        self.engine_combo.setCurrentIndex(idx)
        self.engine_combo.currentIndexChanged.connect(self._change_engine)
        # Ten sam silnik da się wybrać w Edytorze – lista ma za nim nadążać.
        self.app.mt.add_engine_listener(self._sync_engine_combo)
        form.addRow("Silnik:", self.engine_combo)

        self.batch_engine = QComboBox()
        self.batch_engine.setMaximumWidth(320)
        self.batch_engine.addItem("(ten sam co wyżej)", "")
        for key, label in ENGINES:
            self.batch_engine.addItem(label, key)
        saved_batch = self.settings.get_str("mt.batch.engine", "")
        bidx = next((i for i in range(self.batch_engine.count())
                     if self.batch_engine.itemData(i) == saved_batch), 0)
        self.batch_engine.setCurrentIndex(bidx)
        self.batch_engine.setToolTip(
            "Silnik używany przez „Tłumacz wszystko” i automatyczne tłumaczenie po wczytaniu plików."
        )
        self.batch_engine.currentIndexChanged.connect(
            lambda i: self.settings.set("mt.batch.engine", self.batch_engine.itemData(i))
        )
        form.addRow("Silnik operacji zbiorczych:", self.batch_engine)

        self.by_line = QCheckBox("Tłumacz każdą linię (\\n, \\p) osobno")
        self.by_line.setToolTip(
            "Zapobiega przestawianiu znaczników końca wiersza przez silniki MT.\n"
            "Zalecane dla plików gier i napisów."
        )
        self.by_line.setChecked(self.settings.get_bool("mt.translate.by.line", True))
        self.by_line.stateChanged.connect(lambda st: self.settings.set("mt.translate.by.line", bool(st)))
        form.addRow(self.by_line)

        self.polish_output = QCheckBox("Popraw interpunkcję i spacje w wyniku tłumaczenia")
        self.polish_output.setToolTip(
            "Po tłumaczeniu maszynowym program porządkuje: spację przed przecinkiem,\n"
            "brak spacji po przecinku, podwójne spacje, nawiasy i cudzysłowy.\n"
            "To poprawki mechaniczne – nie zmieniają doboru słów."
        )
        self.polish_output.setChecked(self.settings.get_bool("mt.polish.output", True))
        self.polish_output.stateChanged.connect(
            lambda st: self.settings.set("mt.polish.output", bool(st)))
        form.addRow(self.polish_output)

        self.ai_grammar = QCheckBox("AI: wymagaj poprawnej odmiany i naturalnego stylu")
        self.ai_grammar.setToolTip(
            "Dokłada do polecenia dla modelu AI wymagania dotyczące odmiany\n"
            "(przypadki, liczba, rodzaj), uzgodnienia przymiotników, szyku zdania\n"
            "oraz poprawnej budowy zdań ze zmiennymi typu {PLAYER}."
        )
        self.ai_grammar.setChecked(self.settings.get_bool("mt.ai.grammar.rules", True))
        self.ai_grammar.stateChanged.connect(
            lambda st: self.settings.set("mt.ai.grammar.rules", bool(st)))
        form.addRow(self.ai_grammar)

        self.deepl_fallback = QCheckBox(
            "DeepL przez stronę: gdy limit wyczerpany, tłumacz Microsoftem")
        self.deepl_fallback.setToolTip(
            "DeepL bez klucza szybko odcina automaty (błąd 429).\n"
            "Zamiast zwracać błąd, program tłumaczy wtedy silnikiem Microsoft\n"
            "i pisze o tym w pasku informacji. Wyłącz, jeśli wolisz sam błąd."
        )
        self.deepl_fallback.setChecked(
            self.settings.get_bool("mt.deepl.web.fallback", True))
        self.deepl_fallback.stateChanged.connect(
            lambda st: self.settings.set("mt.deepl.web.fallback", bool(st)))
        form.addRow(self.deepl_fallback)

        self.formality = QComboBox()
        self.formality.setMaximumWidth(220)
        self.formality.addItems(["default", "more", "less"])
        self.formality.setCurrentText(self.settings.get_str("mt.deepl.formality", "default"))
        self.formality.currentTextChanged.connect(lambda v: self.settings.set("mt.deepl.formality", v))
        form.addRow("Formalność (DeepL):", self.formality)
        layout.addWidget(box)

        layout.addWidget(self._quicktrans_box())

        free_note = QLabel(
            "✅ Silniki <b>Google Translate</b>, <b>Microsoft Translator (Bing)</b> "
            "i <b>MyMemory</b> działają bez klucza API.<br>"
            "🔷 <b>DeepL przez stronę</b> — jakość prawdziwego DeepL bez klucza, ale to "
            "<b>nieoficjalna</b> droga (program udaje przeglądarkę) i ma <b>bardzo ostry "
            "limit</b>: DeepL potrafi odciąć adres IP już po kilku zapytaniach, nawet "
            "przy pierwszym użyciu, i blokada trzyma kilka minut. Do stałej pracy "
            "pewniejszy jest <b>Microsoft (bez klucza)</b> albo darmowy klucz "
            "DeepL API Free.<br>"
            "🔑 <b>Google Gemini</b> – darmowy klucz bez karty płatniczej: "
            "<a href='https://aistudio.google.com/apikey'>aistudio.google.com/apikey</a> "
            "(limit ok. 10 zapytań/min i 250/dobę – zużycie widać w liczniku).<br>"
            "🤖 <b>Puter AI</b> daje darmowy dostęp do modeli Gemma, GPT i Claude — wystarczy "
            "bezpłatne konto na <a href='https://puter.com'>puter.com</a>: zaloguj się, otwórz "
            "ustawienia konta i skopiuj tutaj swój token.<br>"
            "Pozostałe silniki wymagają własnego klucza API."
        )
        free_note.setWordWrap(True)
        free_note.setOpenExternalLinks(True)
        layout.addWidget(free_note)

        # --- własny serwer LibreTranslate --------------------------------
        self.lt_box = QGroupBox("🖥️ LibreTranslate — własny silnik na tym komputerze")
        lt_form = QFormLayout(self.lt_box)

        lt_info = QLabel(
            "Tłumaczenie <b>bez limitów i bez internetu</b> — tekst nie opuszcza komputera. "
            "Wymaga jednorazowej instalacji pakietu i pobrania modeli językowych "
            "(kilkaset MB przy pierwszym uruchomieniu)."
        )
        lt_info.setWordWrap(True)
        lt_info.setTextFormat(Qt.TextFormat.RichText)
        lt_info.setStyleSheet("color: gray; font-size: 11px;")
        lt_form.addRow(lt_info)

        self.lt_state = QLabel("")
        self.lt_state.setWordWrap(True)
        lt_form.addRow("Stan:", self.lt_state)

        self.lt_langs = QLineEdit(self.settings.get("mt.lt.languages", "en,pl"))
        self.lt_langs.setPlaceholderText("en,pl")
        self.lt_langs.setToolTip(
            "Kody języków po przecinku. Możesz też zaznaczyć je na liście poniżej."
        )
        self.lt_langs.editingFinished.connect(self._on_lt_langs_typed)
        lt_form.addRow("Języki do pobrania:", self.lt_langs)

        # Lista języków z zaznaczaniem – wpisywanie kodów „z głowy” kończyło się
        # literówkami i błędem „Unavailable language codes”.
        self.lt_lang_list = QListWidget()
        self.lt_lang_list.setMaximumHeight(190)
        self.lt_lang_list.setAlternatingRowColors(True)
        self.lt_lang_list.setToolTip(
            "✅ = modele już pobrane. Zaznacz języki, które mają być dostępne.")
        self.lt_lang_list.itemChanged.connect(self._on_lt_lang_checked)
        lt_form.addRow("Dostępne języki:", self.lt_lang_list)

        lang_row = QHBoxLayout()
        self.lt_lang_filter = QLineEdit()
        self.lt_lang_filter.setPlaceholderText("szukaj języka…")
        self.lt_lang_filter.textChanged.connect(self._filter_lt_languages)
        lang_row.addWidget(self.lt_lang_filter, 1)
        refresh_langs = QPushButton("↻ Odśwież listę")
        refresh_langs.setToolTip("Pobiera aktualny spis języków z repozytorium")
        refresh_langs.clicked.connect(lambda: self._load_lt_languages(refresh=True))
        lang_row.addWidget(refresh_langs)
        only_installed = QPushButton("✅ Tylko pobrane")
        only_installed.setToolTip("Zaznacza wyłącznie języki, które już masz na dysku")
        only_installed.clicked.connect(self._select_installed_languages)
        lang_row.addWidget(only_installed)
        lt_form.addRow("", lang_row)

        self.lt_lang_summary = QLabel("")
        self.lt_lang_summary.setStyleSheet("color: gray; font-size: 11px;")
        self.lt_lang_summary.setWordWrap(True)
        lt_form.addRow("", self.lt_lang_summary)

        # Uwaga: nazwa MUSI być inna niż `lt_progress` z zakładki „Pisownia
        # i język” (pasek LanguageTool) — obie zakładki żyją w tym samym
        # obiekcie, więc wspólna nazwa powodowała, że postęp instalacji
        # LibreTranslate sterował paskiem LanguageTool i nigdzie się nie pokazywał.
        self.ltr_progress = QProgressBar()
        self.ltr_progress.setVisible(False)
        self.ltr_progress.setRange(0, 0)
        lt_form.addRow(self.ltr_progress)

        self.lt_log = QLabel("")
        self.lt_log.setWordWrap(True)
        self.lt_log.setStyleSheet("color: gray; font-size: 10px;")
        lt_form.addRow(self.lt_log)

        # Znane, nieszkodliwe ostrzeżenie „RequestsDependencyWarning” —
        # wyjaśniamy je od razu, żeby nie wyglądało na awarię.
        from ..core.libretranslate_setup import dependency_warning_info

        occurs, explanation = dependency_warning_info()
        if occurs:
            self.lt_warning = QLabel(
                "ℹ️ Przy starcie może pojawić się <b>RequestsDependencyWarning</b> "
                "(urllib3/chardet). <b>To nie jest błąd</b> — pobieranie i tłumaczenie "
                "działają normalnie. Aby je usunąć: <code>pip install -U requests</code>."
            )
            self.lt_warning.setWordWrap(True)
            self.lt_warning.setTextFormat(Qt.TextFormat.RichText)
            self.lt_warning.setToolTip(explanation)
            self.lt_warning.setStyleSheet("color: #90a4ae; font-size: 11px;")
            lt_form.addRow(self.lt_warning)

        lt_buttons = QHBoxLayout()
        self.lt_install_btn = QPushButton("⬇ Zainstaluj LibreTranslate")
        self.lt_install_btn.setToolTip("Uruchamia: pip install libretranslate")
        self.lt_install_btn.clicked.connect(self._install_libretranslate)
        self.lt_start_btn = QPushButton("▶ Uruchom serwer")
        self.lt_start_btn.clicked.connect(self._start_libretranslate)
        self.lt_stop_btn = QPushButton("⏹ Zatrzymaj")
        self.lt_stop_btn.clicked.connect(self._stop_libretranslate)
        self.lt_check_btn = QPushButton("🔌 Sprawdź")
        self.lt_check_btn.setToolTip(
            "Sprawdza teraz: czy pakiet jest zainstalowany, czy serwer odpowiada,\n"
            "jakie modele są na dysku i ile zajmują.")
        self.lt_check_btn.clicked.connect(self._check_libretranslate)
        for button in (self.lt_install_btn, self.lt_start_btn,
                       self.lt_stop_btn, self.lt_check_btn):
            lt_buttons.addWidget(button)
        lt_buttons.addStretch(1)
        lt_form.addRow(lt_buttons)
        layout.addWidget(self.lt_box)

        keys_box = QGroupBox("Klucze API i adresy (zapisywane w ~/.supercat/api_keys.json)")
        kform = QFormLayout(keys_box)
        self.key_fields = {}
        for key, label, echo in (
            ("deepl", "Klucz DeepL (darmowy plan API Free):", True),
            ("openai", "Klucz OpenAI:", True),
            ("openai_model", "Model OpenAI:", False),
            ("openai_url", "Endpoint OpenAI:", False),
            ("libretranslate_url", "URL LibreTranslate:", False),
            ("libretranslate_key", "Klucz LibreTranslate:", True),
            ("azure_key", "Klucz Azure Translator:", True),
            ("azure_region", "Region zasobu Azure (np. westeurope):", False),
            ("azure_endpoint", "Endpoint Azure:", False),
            ("ibm_watson_key", "Klucz IBM Watson:", True),
            ("ibm_watson_url", "URL IBM Watson:", False),
            ("ai_offline_url", "URL AI Offline:", False),
            ("gemini", "Klucz Google Gemini:", True),
            ("puter_token", "Token Puter AI:", True),
            ("puter_model", "Model Puter (np. google/gemma-3-27b-it):", False),
            ("mymemory", "Klucz MyMemory (opcjonalny):", True),
            ("mymemory_email", "E-mail MyMemory (większy limit):", False),
        ):
            field = QLineEdit(self.app.mt.keys.get(key, ""))
            if echo:
                field.setEchoMode(QLineEdit.EchoMode.Password)
            kform.addRow(label, field)
            self.key_fields[key] = field
            if key == "deepl":
                deepl_hint = QLabel(
                    'DeepL nie tłumaczy bez klucza. <b>Plan API Free</b> daje '
                    '<b>500 000 znaków miesięcznie za darmo</b> — '
                    '<a href="https://www.deepl.com/pro-api">załóż konto</a> '
                    'i wklej klucz powyżej.'
                )
                deepl_hint.setWordWrap(True)
                deepl_hint.setOpenExternalLinks(True)
                deepl_hint.setTextFormat(Qt.TextFormat.RichText)
                deepl_hint.setStyleSheet("color: gray; font-size: 11px;")
                kform.addRow("", deepl_hint)
            if key == "azure_endpoint":
                azure_hint = QLabel(
                    'Azure ma <b>najhojniejszą warstwę darmową: 2 000 000 znaków '
                    'miesięcznie</b> (plan <b>F0</b>, bez opłat, ale wymaga konta Azure) — '
                    '<a href="https://portal.azure.com/#create/Microsoft.CognitiveServicesTextTranslation">'
                    'utwórz zasób Translator</a>. Po wyczerpaniu limitu API po prostu '
                    'przestaje odpowiadać, nie nalicza opłat.<br>'
                    'Nie chcesz zakładać konta? Wybierz silnik '
                    '<b>„Microsoft Translator / Bing (bez klucza API)”</b> — to ten sam '
                    'model neuronowy, działa od razu.'
                )
                azure_hint.setWordWrap(True)
                azure_hint.setOpenExternalLinks(True)
                azure_hint.setTextFormat(Qt.TextFormat.RichText)
                azure_hint.setStyleSheet("color: gray; font-size: 11px;")
                kform.addRow("", azure_hint)
            if key == "gemini":
                kform.addRow("Model Gemini:", self._build_gemini_model_row())

        self._refresh_lt_state()
        self._load_lt_languages()

        save_row = QHBoxLayout()
        save_btn = QPushButton("💾 Zapisz klucze")
        save_btn.clicked.connect(self._save_keys)
        test_btn = QPushButton("🧪 Test tłumaczenia")
        test_btn.clicked.connect(self._test_mt)
        save_row.addWidget(save_btn)
        save_row.addWidget(test_btn)
        save_row.addStretch(1)
        kform.addRow(save_row)
        layout.addWidget(keys_box)
        layout.addStretch(1)
        return widget

    #: Tryby segmentacji z czytelnymi nazwami (klucz techniczny → opis).
    SEG_MODES = [
        ("sentence", "Zdania — dzieli po . ! ? z obsługą skrótów (zalecane)"),
        ("line", "Wiersze — każdy wiersz to osobny segment"),
        ("paragraph", "Akapity — dzieli po pustej linii"),
        ("custom_delimiter", "Własny separator — np. <<KON>>"),
        ("regex", "Wyrażenie regularne — pełna kontrola"),
    ]

    def _segmentation_tab(self) -> QWidget:
        """Reguły segmentacji z podglądem na żywo (układ wzorowany na OmegaT)."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # --- tryb --------------------------------------------------------
        box = QGroupBox("✂️ Sposób dzielenia tekstu na segmenty")
        form = QFormLayout(box)

        self.seg_enabled = QCheckBox("Włącz segmentację (wyłączona = cały plik jednym segmentem)")
        self.seg_enabled.stateChanged.connect(self._update_segmentation_preview)
        form.addRow(self.seg_enabled)

        self.seg_mode = QComboBox()
        for key, label in self.SEG_MODES:
            self.seg_mode.addItem(label, key)
        self.seg_mode.currentIndexChanged.connect(self._on_seg_mode_changed)
        form.addRow("Tryb:", self.seg_mode)

        self.seg_delims = QLineEdit()
        self.seg_delims.setToolTip("Znaki kończące zdanie. Domyślnie: .!?:;")
        self.seg_delims.textChanged.connect(self._update_segmentation_preview)
        self.seg_delims_row = form.rowCount()
        form.addRow("Znaki końca zdania:", self.seg_delims)

        self.seg_custom = QLineEdit()
        self.seg_custom.setToolTip("Ciąg rozdzielający segmenty, np. <<KON>>")
        self.seg_custom.textChanged.connect(self._update_segmentation_preview)
        form.addRow("Własny separator:", self.seg_custom)

        self.seg_regex = QLineEdit()
        self.seg_regex.setToolTip("Wyrażenie regularne wskazujące miejsce podziału")
        self.seg_regex.textChanged.connect(self._update_segmentation_preview)
        form.addRow("Wyrażenie regularne:", self.seg_regex)
        layout.addWidget(box)

        # --- reguły szczegółowe ------------------------------------------
        rules = QGroupBox("📐 Reguły szczegółowe (kiedy NIE dzielić zdania)")
        rform = QFormLayout(rules)

        self.seg_upper = QCheckBox("Dziel tylko wtedy, gdy po kropce jest wielka litera")
        self.seg_upper.setToolTip(
            "Reguła znana z OmegaT. Zapobiega dzieleniu w miejscach typu\n"
            "„wersja 2.0 działa” czy „str. 15 mówi”."
        )
        self.seg_upper.stateChanged.connect(self._update_segmentation_preview)
        rform.addRow(self.seg_upper)

        self.seg_numbers = QCheckBox("Nie dziel po liczbie z kropką (np. „w 1999. roku”)")
        self.seg_numbers.stateChanged.connect(self._update_segmentation_preview)
        rform.addRow(self.seg_numbers)

        self.seg_abbrev = QLineEdit()
        self.seg_abbrev.setPlaceholderText("np., itd., zał., rys.  — oddzielone przecinkami")
        self.seg_abbrev.setToolTip(
            "Własne skróty, po których kropka NIE kończy zdania.\n"
            "Lista wbudowana (np., itd., dr, prof., mgr…) działa zawsze."
        )
        self.seg_abbrev.textChanged.connect(self._update_segmentation_preview)
        rform.addRow("Dodatkowe skróty:", self.seg_abbrev)

        self.seg_codes = QCheckBox("Dziel także po znacznikach \\n, \\p, <<KON>> (pliki gier)")
        self.seg_codes.setToolTip(
            "Każdy znacznik kończy segment. Przydatne, gdy tłumaczysz\n"
            "wiersz po wierszu; domyślnie wyłączone, bo znacznik zwykle\n"
            "przełamuje zdanie w środku."
        )
        self.seg_codes.stateChanged.connect(self._update_segmentation_preview)
        rform.addRow(self.seg_codes)

        self.seg_min_len = QSpinBox()
        self.seg_min_len.setRange(0, 200)
        self.seg_min_len.setSuffix(" znaków")
        self.seg_min_len.setMaximumWidth(160)
        self.seg_min_len.setToolTip(
            "Segmenty krótsze niż podana wartość są doklejane do poprzedniego.\n"
            "0 = bez scalania."
        )
        self.seg_min_len.valueChanged.connect(self._update_segmentation_preview)
        rform.addRow("Scalaj segmenty krótsze niż:", self.seg_min_len)

        self.seg_preserve_ws = QCheckBox("Zachowuj spacje na początku i końcu wiersza")
        self.seg_preserve_ws.setToolTip(
            "W plikach gier wiersz często zaczyna się spacją (wcięcie dialogu).\n"
            "Gdy opcja jest włączona, segment zachowuje ją dokładnie tak, jak w pliku,\n"
            "a tłumaczenie dostaje takie same spacje na brzegach."
        )
        self.seg_preserve_ws.stateChanged.connect(self._update_segmentation_preview)
        rform.addRow(self.seg_preserve_ws)
        layout.addWidget(rules)

        # --- podgląd na żywo ---------------------------------------------
        preview_box = QGroupBox("👁️ Podgląd na żywo — jak zostanie podzielony tekst")
        pv = QVBoxLayout(preview_box)

        self.seg_sample = QPlainTextEdit()
        self.seg_sample.setPlaceholderText("Wklej tu fragment tekstu, aby zobaczyć podział…")
        self.seg_sample.setMaximumHeight(90)
        self.seg_sample.setPlainText(
            "Thank you for using the STAMP CARD\\nSystem.\\pYou have 3 more to collect.\n"
            "Zobacz str. 15 oraz rys. 2. To jest kolejne zdanie."
        )
        self.seg_sample.textChanged.connect(self._update_segmentation_preview)
        pv.addWidget(self.seg_sample)

        sample_row = QHBoxLayout()
        from_project = QPushButton("📄 Wstaw tekst z projektu")
        from_project.setToolTip("Bierze kilka pierwszych segmentów z otwartego pliku")
        from_project.clicked.connect(self._load_sample_from_project)
        sample_row.addWidget(from_project)
        sample_row.addStretch(1)
        self.seg_count_label = QLabel("")
        sample_row.addWidget(self.seg_count_label)
        pv.addLayout(sample_row)

        self.seg_preview = QListWidget()
        self.seg_preview.setAlternatingRowColors(True)
        pv.addWidget(self.seg_preview)
        layout.addWidget(preview_box, 1)

        # --- zapis ---------------------------------------------------------
        buttons = QHBoxLayout()
        apply_btn = QPushButton("💾 Zapisz w projekcie i podziel pliki ponownie")
        apply_btn.setToolTip("Zapisuje reguły i od nowa wczytuje pliki z folderu source/")
        apply_btn.clicked.connect(self._save_segmentation)
        reset_btn = QPushButton("↺ Ustawienia domyślne")
        reset_btn.clicked.connect(self._reset_segmentation)
        buttons.addWidget(apply_btn)
        buttons.addWidget(reset_btn)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self.load_segmentation()
        self._on_seg_mode_changed()
        return widget

    # ------------------------------------------------------------------
    def _current_seg_mode(self) -> str:
        return self.seg_mode.currentData() or "sentence"

    def _on_seg_mode_changed(self) -> None:
        """Pokazuje tylko pola istotne dla wybranego trybu."""
        mode = self._current_seg_mode()
        self.seg_delims.setEnabled(mode == "sentence")
        self.seg_custom.setEnabled(mode == "custom_delimiter")
        self.seg_regex.setEnabled(mode == "regex")
        for widget in (self.seg_upper, self.seg_numbers, self.seg_abbrev):
            widget.setEnabled(mode == "sentence")
        self._update_segmentation_preview()

    def _settings_to_segmentation(self):
        """Buduje obiekt ustawień z pól formularza (bez zapisu w projekcie)."""
        from ..core.project import SegmentationSettings

        return SegmentationSettings(
            enabled=self.seg_enabled.isChecked(),
            mode=self._current_seg_mode(),
            delimiters=self.seg_delims.text(),
            custom_delimiter=self.seg_custom.text(),
            regex_pattern=self.seg_regex.text(),
            preserve_whitespace=self.seg_preserve_ws.isChecked(),
            custom_abbreviations=self.seg_abbrev.text(),
            require_uppercase_after=self.seg_upper.isChecked(),
            skip_after_numbers=self.seg_numbers.isChecked(),
            split_on_codes=self.seg_codes.isChecked(),
            min_segment_length=self.seg_min_len.value(),
        )

    def _update_segmentation_preview(self) -> None:
        """Przelicza podgląd po każdej zmianie reguły."""
        if not hasattr(self, "seg_preview"):
            return
        from ..core.segmentation import segment_text

        sample = self.seg_sample.toPlainText()
        self.seg_preview.clear()
        if not sample.strip():
            self.seg_count_label.setText("")
            return
        try:
            parts = segment_text(sample, self._settings_to_segmentation())
        except Exception as exc:
            self.seg_count_label.setText(f"❌ {exc}")
            return
        for i, part in enumerate(parts, start=1):
            shown = part.replace("\n", " ⏎ ")
            item = QListWidgetItem(f"{i:>3}.  {shown}")
            item.setToolTip(repr(part))
            self.seg_preview.addItem(item)
        words = sum(len(p.split()) for p in parts)
        self.seg_count_label.setText(f"Segmentów: {len(parts)}  •  słów: {words}")

    def _load_sample_from_project(self) -> None:
        segments = self.app.editor_tab.segments
        if not segments:
            QMessageBox.information(self, "Segmentacja",
                                    "Najpierw zaimportuj pliki do projektu.")
            return
        sample = "\n".join((s.source or "") for s in segments[:6])
        self.seg_sample.setPlainText(sample)

    def _reset_segmentation(self) -> None:
        self.seg_enabled.setChecked(True)
        self.seg_mode.setCurrentIndex(0)
        self.seg_delims.setText(".!?:;")
        self.seg_custom.setText("<<KON>>")
        self.seg_regex.clear()
        self.seg_abbrev.clear()
        self.seg_upper.setChecked(True)
        self.seg_numbers.setChecked(True)
        self.seg_codes.setChecked(False)
        self.seg_min_len.setValue(0)
        self.seg_preserve_ws.setChecked(True)
        self._update_segmentation_preview()

    # ------------------------------------------------------------------
    def load_segmentation(self) -> None:
        project = self.app.project
        seg = project.segmentation if project else None
        widgets = (self.seg_enabled, self.seg_mode, self.seg_delims, self.seg_custom,
                   self.seg_regex, self.seg_preserve_ws, self.seg_abbrev, self.seg_upper,
                   self.seg_numbers, self.seg_codes, self.seg_min_len, self.seg_sample)
        for widget in widgets:                 # bez tego każde pole przeliczałoby podgląd
            widget.blockSignals(True)
        try:
            if not seg:
                self.seg_enabled.setChecked(True)
                self._select_seg_mode("sentence")
                self.seg_delims.setText(".!?:;")
                self.seg_custom.setText("<<KON>>")
                self.seg_regex.setText("")
                self.seg_preserve_ws.setChecked(True)
                self.seg_abbrev.setText("")
                self.seg_upper.setChecked(True)
                self.seg_numbers.setChecked(True)
                self.seg_codes.setChecked(False)
                self.seg_min_len.setValue(0)
                return
            self.seg_enabled.setChecked(seg.enabled)
            self._select_seg_mode(seg.mode)
            self.seg_delims.setText(seg.delimiters)
            self.seg_custom.setText(seg.custom_delimiter)
            self.seg_regex.setText(seg.regex_pattern)
            self.seg_preserve_ws.setChecked(getattr(seg, "preserve_whitespace", True))
            self.seg_abbrev.setText(getattr(seg, "custom_abbreviations", ""))
            self.seg_upper.setChecked(getattr(seg, "require_uppercase_after", True))
            self.seg_numbers.setChecked(getattr(seg, "skip_after_numbers", True))
            self.seg_codes.setChecked(getattr(seg, "split_on_codes", False))
            self.seg_min_len.setValue(getattr(seg, "min_segment_length", 0))
        finally:
            for widget in widgets:
                widget.blockSignals(False)
        self._update_segmentation_preview()

    def _select_seg_mode(self, mode: str) -> None:
        index = self.seg_mode.findData(mode)
        self.seg_mode.setCurrentIndex(index if index >= 0 else 0)

    def _save_segmentation(self) -> None:
        project = self.app.project
        if not project:
            QMessageBox.information(self, "Segmentacja", "Najpierw otwórz projekt.")
            return
        project.segmentation = self._settings_to_segmentation()
        self.settings.set("segment.keep.edge.spaces", self.seg_preserve_ws.isChecked())
        self.app.project_manager.save_project()

        if self.app.editor_tab.segments and QMessageBox.question(
            self, "Segmentacja",
            "Zapisano reguły.\n\nPodzielić pliki projektu ponownie według nowych reguł?\n"
            "(wpisane tłumaczenia zostaną dopasowane po treści segmentu)",
        ) == QMessageBox.StandardButton.Yes:
            self.app.load_source_files()
            self.app.show_status("✂️ Pliki podzielone ponownie według nowych reguł")
        else:
            QMessageBox.information(
                self, "Segmentacja",
                "Zapisano ustawienia. Zmiany zadziałają po ponownym wczytaniu plików (F5).")

    def _build_gemini_model_row(self):
        """Lista modeli Gemini + przycisk pobrania tych dostępnych dla klucza."""
        from ..core.mt import GEMINI_MODELS

        self.gemini_model = QComboBox()
        self.gemini_model.setEditable(True)
        self.gemini_model.setMinimumWidth(260)
        self.gemini_model.addItems(GEMINI_MODELS)
        self.gemini_model.setCurrentText(
            self.app.mt.keys.get("gemini_model", "") or GEMINI_MODELS[0]
        )
        self.gemini_model.setToolTip(
            "Google blokuje starsze modele (2.5) dla nowo utworzonych projektów.\n"
            "Kliknij „Pobierz modele”, aby zobaczyć, co działa dla Twojego klucza."
        )
        fetch_btn = QPushButton("🔄 Pobierz modele")
        fetch_btn.setToolTip("Pobiera z API listę modeli dostępnych dla wpisanego klucza")
        fetch_btn.clicked.connect(self._fetch_gemini_models)
        row = QHBoxLayout()
        row.addWidget(self.gemini_model, 1)
        row.addWidget(fetch_btn)
        holder = QWidget()
        holder.setLayout(row)
        return holder

    def _fetch_gemini_models(self) -> None:
        """Pobiera listę modeli dostępnych dla wpisanego klucza Gemini."""
        key_field = self.key_fields.get("gemini")
        if key_field is not None:
            self.app.mt.keys["gemini"] = key_field.text().strip()
        try:
            models = self.app.mt.list_gemini_models()
        except Exception as exc:
            QMessageBox.critical(self, "Modele Gemini", str(exc))
            return
        if not models:
            QMessageBox.information(self, "Modele Gemini",
                                    "API nie zwróciło modeli obsługujących generowanie tekstu.")
            return
        current = self.gemini_model.currentText().strip()
        self.gemini_model.clear()
        self.gemini_model.addItems(models)
        # zachowaj wybór, jeśli nadal dostępny; inaczej weź pierwszy „flash”
        self.gemini_model.setCurrentText(current if current in models else models[0])
        self._save_keys()
        QMessageBox.information(
            self, "Modele Gemini",
            f"Znaleziono {len(models)} dostępnych modeli.\n\nWybrany: {self.gemini_model.currentText()}",
        )

    def _change_time_unit(self, index: int) -> None:
        self.settings.set("ui.time.unit", self.time_unit.itemData(index))
        editor = getattr(self.app, "editor_tab", None)
        if editor is not None and hasattr(editor, "_update_timing_label"):
            editor._update_timing_label()

    def _change_theme(self, index: int) -> None:
        self.settings.set("theme.dark", index == 0)
        self.app.apply_theme()

    # ---------------------------------------------------- QuickTrans
    def _quicktrans_box(self) -> QGroupBox:
        """Wybór silników, które ma odpytywać QuickTrans.

        Domyślnie program bierze wszystkie gotowe silniki. Kto woli porównywać
        tylko dwa–trzy konkretne (bo reszta zwraca błędy albo zużywa limit),
        zaznacza je tutaj — zaznaczenia zapisujemy jako listę kluczy.
        """
        box = QGroupBox("⚡ QuickTrans — które silniki porównywać")
        layout = QVBoxLayout(box)

        info = QLabel(
            "Zaznacz silniki odpytywane równolegle w oknie QuickTrans. "
            "Gdy nic nie zaznaczysz, program użyje wszystkich dostępnych "
            "(z uwzględnieniem przełącznika poniżej)."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(info)

        self.qt_engine_boxes = {}
        chosen = {item.strip() for item
                  in self.settings.get_str("mt.quicktrans.engines", "").split(",")
                  if item.strip()}
        # Dwie równe kolumny – w układzie z QHBoxLayout etykiety różnej długości
        # rozjeżdżały się i lista była nieczytelna.
        grid = QGridLayout()
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        for position, (key, label) in enumerate(ENGINES):
            checkbox = QCheckBox(label)
            checkbox.setChecked(key in chosen)
            checkbox.stateChanged.connect(self._save_quicktrans_engines)
            self.qt_engine_boxes[key] = checkbox
            grid.addWidget(checkbox, position // 2, position % 2)
        layout.addLayout(grid)

        self.qt_free_only = QCheckBox(
            "Gdy nic nie zaznaczono: pytaj tylko silniki bez klucza API")
        self.qt_free_only.setChecked(self.settings.get_bool("mt.quicktrans.free_only", True))
        self.qt_free_only.stateChanged.connect(
            lambda st: self.settings.set("mt.quicktrans.free_only", bool(st))
        )
        layout.addWidget(self.qt_free_only)

        buttons = QHBoxLayout()
        all_free = QPushButton("Zaznacz darmowe")
        all_free.setToolTip("Silniki działające bez klucza API")
        all_free.clicked.connect(lambda: self._set_quicktrans_engines(FREE_ENGINES))
        clear = QPushButton("Wyczyść (automatycznie)")
        clear.clicked.connect(lambda: self._set_quicktrans_engines([]))
        buttons.addWidget(all_free)
        buttons.addWidget(clear)
        buttons.addStretch(1)
        self.qt_summary = QLabel("")
        self.qt_summary.setStyleSheet("color: gray; font-size: 11px;")
        buttons.addWidget(self.qt_summary)
        layout.addLayout(buttons)

        self._update_quicktrans_summary()
        return box

    def _set_quicktrans_engines(self, engines) -> None:
        wanted = set(engines)
        for key, checkbox in self.qt_engine_boxes.items():
            checkbox.blockSignals(True)
            checkbox.setChecked(key in wanted)
            checkbox.blockSignals(False)
        self._save_quicktrans_engines()

    def _save_quicktrans_engines(self) -> None:
        selected = [key for key, box in self.qt_engine_boxes.items() if box.isChecked()]
        self.settings.set("mt.quicktrans.engines", ",".join(selected))
        self._update_quicktrans_summary()

    def _update_quicktrans_summary(self) -> None:
        count = sum(1 for box in self.qt_engine_boxes.values() if box.isChecked())
        if count:
            self.qt_summary.setText(f"Wybrano {count} silników")
        else:
            self.qt_summary.setText("Tryb automatyczny")

    def _sync_engine_combo(self, engine: str) -> None:
        """Ustawia listę na silnik wybrany gdzie indziej (bez pętli sygnałów)."""
        combo = getattr(self, "engine_combo", None)
        if combo is None or combo.currentData() == engine:
            return
        position = next((i for i in range(combo.count())
                         if combo.itemData(i) == engine), -1)
        if position >= 0:
            combo.blockSignals(True)
            combo.setCurrentIndex(position)
            combo.blockSignals(False)

    def _change_engine(self, index: int) -> None:
        key = self.engine_combo.itemData(index)
        self.app.mt.set_engine(key)   # słuchacze odświeżą pozostałe widoki
        self.app.update_status()

    # ------------------------------------------------ LibreTranslate lokalnie
    def _lt_server(self):
        """Wspólna instancja serwera – żeby dało się go potem zatrzymać."""
        if getattr(self.app, "_lt_server", None) is None:
            from ..core.libretranslate_setup import LibreTranslateServer

            self.app._lt_server = LibreTranslateServer()
        return self.app._lt_server

    def _refresh_lt_state(self) -> None:
        """Opisuje stan pakietu i serwera, dostosowując przyciski."""
        from ..core import libretranslate_setup as lt

        installed = lt.is_installed()
        running = lt.is_running()

        models = lt.models_size_bytes()
        codes = lt.installed_language_codes()
        models_note = ""
        if models:
            models_note = f"  •  modele: {', '.join(codes)} ({lt.format_size(models)})" \
                if codes else f"  •  modele: {lt.format_size(models)}"

        if running:
            languages = lt.available_languages()
            self.lt_state.setText(
                f"✅ Serwer działa pod adresem {lt.server_url()}"
                + (f"  •  języki: {', '.join(languages[:8])}" if languages else "")
                + models_note)
            self.lt_state.setStyleSheet("color: #66bb6a;")
        elif installed:
            self.lt_state.setText(
                f"⏸️ Pakiet zainstalowany (wersja {lt.installed_version()}"
                f"{self._lt_version_note()}), serwer nie jest uruchomiony."
                + models_note)
            self.lt_state.setStyleSheet("color: #ffb74d;")
        else:
            self.lt_state.setText(
                "❌ Pakiet nie jest zainstalowany. Kliknij „⬇ Zainstaluj LibreTranslate”.")
            self.lt_state.setStyleSheet("color: gray;")

        self.lt_install_btn.setEnabled(not installed)
        self.lt_install_btn.setText(
            "✅ Zainstalowany" if installed else "⬇ Zainstaluj LibreTranslate")
        self.lt_start_btn.setEnabled(installed and not running)
        self.lt_stop_btn.setEnabled(running and self._lt_server().is_ours)

        # Adres w polu klucza ma wskazywać działający serwer.
        field = self.key_fields.get("libretranslate_url") if hasattr(self, "key_fields") else None
        if field is not None and running and not field.text().strip():
            field.setText(lt.server_url())

    def _install_libretranslate(self) -> None:
        from .workers import LTInstallWorker

        if QMessageBox.question(
            self, "Zainstaluj LibreTranslate",
            "Zainstalować pakiet „libretranslate”?\n\n"
            "• sam pakiet: ok. 1,1 MB, z zależnościami zwykle 200–400 MB\n"
            "• modele językowe: ok. 163 MB na parę (pobiorą się przy pierwszym "
            "uruchomieniu serwera)\n"
            "• pełny zestaw wszystkich języków: ok. 4 GB\n\n"
            "Instalacja może potrwać kilka minut.",
        ) != QMessageBox.StandardButton.Yes:
            return

        self.ltr_progress.setVisible(True)
        self.ltr_progress.setRange(0, 0)          # nieokreślony, póki pip nie poda %
        self.ltr_progress.setFormat("Przygotowanie…")
        self.lt_install_btn.setEnabled(False)
        self.lt_state.setText("⏳ Instalowanie pakietu…")
        self.lt_state.setStyleSheet("color: gray;")

        worker = LTInstallWorker(parent=self)
        worker.output.connect(lambda line: self.lt_log.setText(line[-120:]))
        worker.progress.connect(self._on_lt_install_progress)

        def done(ok: bool, message: str) -> None:
            self.ltr_progress.setVisible(False)
            self.ltr_progress.setRange(0, 0)
            self.ltr_progress.setFormat("")
            self.lt_log.setText("")
            self._lt_worker = None
            self._refresh_lt_state()
            if ok:
                QMessageBox.information(self, "LibreTranslate", message
                                        + "\n\nTeraz kliknij „▶ Uruchom serwer”.")
            else:
                QMessageBox.warning(self, "LibreTranslate", message)

        worker.finished_install.connect(done)
        self._lt_worker = worker
        worker.start()

    def _start_libretranslate(self) -> None:
        from .workers import LTStartWorker

        languages = self.lt_langs.text().strip() or "en,pl"
        from ..core import libretranslate_setup as _lt

        pairs = max(1, len([x for x in languages.split(",") if x.strip()]) - 1)
        expected = _lt.LANGUAGE_PAIR_MB * pairs
        self.ltr_progress.setVisible(True)
        self.ltr_progress.setRange(0, 0)
        self.ltr_progress.setFormat("Uruchamianie…")
        self.lt_start_btn.setEnabled(False)
        self.lt_state.setText(
            f"⏳ Uruchamianie serwera… pierwszy raz pobiera modele "
            f"(ok. {expected} MB dla „{languages}”)")
        self.lt_state.setStyleSheet("color: gray;")

        worker = LTStartWorker(self._lt_server(), languages, parent=self)
        worker.output.connect(lambda line: self.lt_log.setText(line[-120:]))
        worker.bytes_progress.connect(self._on_lt_bytes)

        def done(ok: bool, message: str) -> None:
            self.ltr_progress.setVisible(False)
            self.ltr_progress.setRange(0, 0)
            self.ltr_progress.setFormat("")
            self.lt_log.setText("")
            self._lt_worker = None
            self._refresh_lt_state()
            if ok:
                from ..core import libretranslate_setup as lt

                field = self.key_fields.get("libretranslate_url")
                if field is not None:
                    field.setText(lt.server_url())
                    self.app.mt.keys["libretranslate_url"] = lt.server_url()
                    self.app.mt.save_keys()
                QMessageBox.information(self, "LibreTranslate", message)
            else:
                # Komunikat jest już przetłumaczony na ludzki język przez
                # explain_start_error(); pokazujemy go w całości.
                box = QMessageBox(QMessageBox.Icon.Warning, "LibreTranslate",
                                  message, QMessageBox.StandardButton.Ok, self)
                box.setTextInteractionFlags(
                    Qt.TextInteractionFlag.TextSelectableByMouse)
                box.exec()

        worker.finished_start.connect(done)
        self._lt_worker = worker
        worker.start()

    # ------------------------------------------------- lista języków LibreTranslate
    def _selected_lt_languages(self) -> list:
        """Kody wpisane w polu tekstowym (źródło prawdy dla pobierania)."""
        return [c.strip().lower() for c in self.lt_langs.text().split(",") if c.strip()]

    def _load_lt_languages(self, refresh: bool = False) -> None:
        """Wypełnia listę języków; ✅ oznacza modele już pobrane."""
        from ..core import libretranslate_setup as lt

        if refresh:
            self.lt_lang_summary.setText("⏳ Pobieranie spisu języków…")
            QApplication.processEvents()
        catalog = lt.language_catalog(refresh=refresh)
        chosen = set(self._selected_lt_languages())

        self.lt_lang_list.blockSignals(True)
        self.lt_lang_list.clear()
        for entry in catalog:
            mark = "✅" if entry["installed"] else "⬇"
            item = QListWidgetItem(
                f"{mark} {entry['name']} ({entry['code']}) — "
                f"{lt.plural_pairs(entry['pairs'])}")
            item.setData(Qt.ItemDataRole.UserRole, entry["code"])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if entry["code"] in chosen
                               else Qt.CheckState.Unchecked)
            if entry["installed"]:
                item.setForeground(QColor("#66bb6a"))
            self.lt_lang_list.addItem(item)
        self.lt_lang_list.blockSignals(False)

        if not catalog:
            self.lt_lang_summary.setText(
                "⚠️ Nie udało się pobrać spisu języków (brak internetu?). "
                "Możesz wpisać kody ręcznie, np. en,pl")
            return
        self._update_lt_lang_summary()
        self._filter_lt_languages(self.lt_lang_filter.text())

    def _filter_lt_languages(self, text: str) -> None:
        needle = (text or "").strip().lower()
        for row in range(self.lt_lang_list.count()):
            item = self.lt_lang_list.item(row)
            item.setHidden(bool(needle) and needle not in item.text().lower())

    def _on_lt_lang_checked(self, _item) -> None:
        """Zaznaczenie na liście przepisuje kody do pola tekstowego."""
        codes = [self.lt_lang_list.item(r).data(Qt.ItemDataRole.UserRole)
                 for r in range(self.lt_lang_list.count())
                 if self.lt_lang_list.item(r).checkState() == Qt.CheckState.Checked]
        self.lt_langs.setText(",".join(codes))
        self.settings.set("mt.lt.languages", ",".join(codes))
        self._update_lt_lang_summary()

    def _on_lt_langs_typed(self) -> None:
        """Ręcznie wpisane kody odznaczają/zaznaczają pozycje na liście."""
        self.settings.set("mt.lt.languages", self.lt_langs.text().strip())
        chosen = set(self._selected_lt_languages())
        self.lt_lang_list.blockSignals(True)
        for row in range(self.lt_lang_list.count()):
            item = self.lt_lang_list.item(row)
            item.setCheckState(
                Qt.CheckState.Checked
                if item.data(Qt.ItemDataRole.UserRole) in chosen
                else Qt.CheckState.Unchecked)
        self.lt_lang_list.blockSignals(False)
        self._update_lt_lang_summary()

    def _select_installed_languages(self) -> None:
        from ..core import libretranslate_setup as lt

        codes = lt.installed_language_codes()
        if not codes:
            QMessageBox.information(
                self, "LibreTranslate",
                "Nie masz jeszcze żadnych modeli. Zaznacz języki i kliknij "
                "„▶ Uruchom serwer” — pobiorą się automatycznie.")
            return
        self.lt_langs.setText(",".join(codes))
        self._on_lt_langs_typed()

    def _update_lt_lang_summary(self) -> None:
        """Podsumowanie: ile zaznaczono, co już jest, ile trzeba dociągnąć."""
        from ..core import libretranslate_setup as lt

        chosen = self._selected_lt_languages()
        have = set(lt.installed_language_codes())
        missing = [c for c in chosen if c not in have]
        if not chosen:
            self.lt_lang_summary.setText(
                "Nie wybrano języków — zostanie użyte domyślne „en,pl”.")
            return
        parts = [f"Wybrano {len(chosen)}: {', '.join(chosen)}"]
        if have:
            parts.append(f"już pobrane: {', '.join(sorted(have))}")
        if missing:
            pairs = max(1, len(chosen) * (len(chosen) - 1))
            parts.append(f"do pobrania: {', '.join(missing)} "
                         f"(ok. {pairs * lt.LANGUAGE_PAIR_MB // 2} MB)")
        else:
            parts.append("wszystko już jest na dysku")
        self.lt_lang_summary.setText("  •  ".join(parts))

    def _check_libretranslate(self) -> None:
        """Przycisk „🔌 Sprawdź” — teraz widać, że coś się wydarzyło.

        Wcześniej odświeżał tylko etykietę stanu; gdy nic się nie zmieniło,
        klikanie wyglądało jak brak reakcji.
        """
        from ..core import libretranslate_setup as lt

        self.lt_check_btn.setEnabled(False)
        self.lt_state.setText("⏳ Sprawdzanie…")
        self.lt_state.setStyleSheet("color: gray;")
        QApplication.processEvents()
        try:
            self._refresh_lt_state()
            self._load_lt_languages()
            running = lt.is_running()
            details = [f"Pakiet: {lt.installed_version() or 'niezainstalowany'}"]
            if lt.is_installed():
                latest = lt.latest_version()
                if latest:
                    details.append("Najnowsza wersja: " + latest
                                   + (" (masz aktualną)"
                                      if latest == lt.installed_version() else ""))
            codes = lt.installed_language_codes()
            details.append("Pobrane modele: "
                           + (", ".join(codes) if codes else "brak"))
            details.append("Miejsce na dysku: " + lt.format_size(lt.models_size_bytes()))
            details.append(f"Katalog modeli: {lt.models_dir()}")
            if running:
                langs = lt.available_languages()
                details.append(f"Serwer: ✅ działa pod {lt.server_url()}")
                if langs:
                    details.append("Serwer udostępnia: " + ", ".join(langs))
            else:
                details.append("Serwer: ⏸️ nie odpowiada pod "
                               + lt.server_url())
            occurs, explanation = lt.dependency_warning_info()
            if occurs:
                # Pełne wyjaśnienie jest długie i ma własne akapity – dajemy je
                # jako osobną sekcję, żeby nie zlewało się z listą powyżej.
                details.append("\n— — —\n" + explanation)
            QMessageBox.information(self, "LibreTranslate — stan",
                                    "\n".join(details))
        finally:
            self.lt_check_btn.setEnabled(True)

    def _lt_version_note(self) -> str:
        """Dopisek „najnowsza” / „dostępna nowsza X” — sprawdzane raz na sesję.

        Odpytanie PyPI trwa chwilę, więc wynik zapamiętujemy; brak sieci nie
        może blokować odświeżania stanu.
        """
        from ..core import libretranslate_setup as lt

        if not hasattr(self, "_lt_latest"):
            self._lt_latest = lt.latest_version()
        latest = self._lt_latest
        if not latest:
            return ""
        if latest == lt.installed_version():
            return " — najnowsza"
        return f" — dostępna nowsza: {latest}"

    def _on_lt_bytes(self, done: int, total: int) -> None:
        """Pokazuje pobrane megabajty modeli — «42 MB / 133 MB (31%)»."""
        from ..core.libretranslate_setup import format_size

        if total <= 0:
            self.ltr_progress.setRange(0, 0)
            self.ltr_progress.setFormat(f"Pobrano {format_size(done)}")
            return
        self.ltr_progress.setRange(0, 100)
        self.ltr_progress.setValue(min(100, int(done / total * 100)))
        self.ltr_progress.setFormat(
            f"Modele: {format_size(done)} / {format_size(total)}  (%p%)")

    def _on_lt_install_progress(self, percent: int, text: str) -> None:
        """Przełącza pasek w tryb procentowy, gdy pip poda konkretne liczby."""
        if percent < 0:                       # znamy tylko nazwę pakietu
            self.ltr_progress.setRange(0, 0)
            self.ltr_progress.setFormat(text)
            return
        self.ltr_progress.setRange(0, 100)
        self.ltr_progress.setValue(percent)
        self.ltr_progress.setFormat(f"{text}  (%p%)")

    def _stop_libretranslate(self) -> None:
        if self._lt_server().stop():
            self.app.show_status("Zatrzymano serwer LibreTranslate")
        self._refresh_lt_state()

    def _save_keys(self) -> None:
        for key, field in self.key_fields.items():
            self.app.mt.keys[key] = field.text().strip()
        if hasattr(self, "gemini_model"):
            self.app.mt.keys["gemini_model"] = self.gemini_model.currentText().strip()
        self.app.mt.save_keys()
        # Nowy klucz może odblokować silnik – odświeżamy listę w edytorze.
        editor = getattr(self.app, "editor_tab", None)
        if editor is not None and hasattr(editor, "reload_engine_picker"):
            editor.reload_engine_picker()
        QMessageBox.information(self, "Klucze API", "Zapisano ustawienia kluczy API.")

    def _test_mt(self) -> None:
        self._save_keys()
        result = self.app.mt.translate("This is a test sentence.", "en", "pl")
        QMessageBox.information(self, "Test tłumaczenia maszynowego", f"Wynik:\n\n{result}")

    def _reset(self) -> None:
        if QMessageBox.question(self, "Ustawienia", "Przywrócić wszystkie ustawienia domyślne?") == QMessageBox.StandardButton.Yes:
            self.settings.reset_to_defaults()
            QMessageBox.information(self, "Ustawienia", "Przywrócono domyślne. Uruchom program ponownie.")
