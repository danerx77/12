"""Okno główne SuperCAT Workbench – układ jednookienny z zakładkami."""
from __future__ import annotations

import json
import os
import shutil
import traceback
from typing import List, Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QAction, QColor, QFont, QKeySequence
from PyQt6.QtWidgets import (
    QApplication, QFileDialog, QLabel, QMainWindow, QMenu, QMessageBox, QProgressDialog,
    QStatusBar, QTabWidget, QToolBar, QWidget,
)

from ..core.fileparser import (
    SUPPORTED_EXTENSIONS, Segment, export_by_replacement, export_docx, export_html_bilingual,
    export_po, export_srt, export_txt, export_xliff, export_xlsx, parse_file,
)
from ..core.glossary import Dictionary, Glossary
from ..core.mt import MachineTranslation
from ..core.project import (PROJECT_EXT, Project, ProjectManager, RecentProjects,
                            order_files)
from ..core.qa import project_statistics
from ..core.usage import UsageTracker
from ..core.settings import SettingsManager
from ..core.textutil import copy_edge_whitespace
from ..core.tm import TranslationMemory
from .dialogs.project_dialogs import (
    AboutDialog, DownloadRemoteProjectDialog, NewProjectDialog, ProjectSettingsDialog,
    SegmentationPreviewDialog,
)
from .ai_panel import AIPanel
from .editor_tab import EditorTab
from .glossary_tab import DictionaryTab, GlossaryTab
from .qa_tab import QATab
from .search_tab import SearchTab
from .settings_tab import SettingsTab
from .theme import restyle_splitters, stylesheet
from .workers import MTWorker, PreTranslateWorker, TMWarmupWorker, TMXImportWorker

APP_NAME = "SuperCAT Workbench"
VERSION = "1.0"
TRANSLATIONS_FILE = "translations.json"


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings = SettingsManager.instance()
        # Ikona okna = ikona na pasku zadań (nie zostawia domyślnej Pytona).
        from ..app import _app_icon as _set_icon
        _ic = _set_icon()
        if _ic is not None:
            self.setWindowIcon(_ic)
        self.project_manager = ProjectManager.instance()
        self._exclusions = None
        self._menu_actions = {}
        self._toolbar_tips = []
        self._lt_server = None
        self.tm = TranslationMemory()
        self.glossary = Glossary()
        self.dictionary = Dictionary()
        self.mt = MachineTranslation()
        # referencje na aktywne wątki – bez tego GC potrafi je zebrać w trakcie pracy
        self._workers: set = set()

        self.setWindowTitle(f"{APP_NAME} {VERSION}")
        self.setAcceptDrops(True)   # pliki można upuścić w dowolnym miejscu okna
        self.resize(1500, 920)
        self.setMinimumSize(1100, 700)

        self._build_tabs()
        self._build_menu()
        self._build_toolbar()
        self.setStatusBar(QStatusBar())
        self.status_label = QLabel("Gotowy – brak otwartego projektu")
        self.statusBar().addWidget(self.status_label)
        # Wskaźnik zużycia silników MT (limity darmowych planów)
        self.usage_label = QLabel("")
        self.usage_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.usage_label.mousePressEvent = lambda _e: self.show_usage_report()
        self.statusBar().addPermanentWidget(self.usage_label)

        self.apply_theme()
        self.apply_font()

        if self.settings.get_bool("auto.load.last.project", False):
            last = self.settings.get_str("last.project.path", "")
            if last and os.path.exists(last):
                QTimer.singleShot(200, lambda: self.open_project_path(last))

    # ------------------------------------------------------------------ UI
    @property
    def project(self) -> Optional[Project]:
        return self.project_manager.current

    def _build_tabs(self) -> None:
        self.tabs = QTabWidget()
        self.tabs.tabBar().setExpanding(False)

        self.editor_tab = EditorTab(self)
        self.editor_tab.status_message.connect(self.show_status)
        self.tm_tab = TMTabWrapper(self)
        self.glossary_tab = GlossaryTab(self)
        self.dictionary_tab = DictionaryTab(self)
        self.search_tab = SearchTab(self)
        self.qa_tab = QATab(self)
        self.ai_tab = AIPanel(self)
        self.settings_tab = SettingsTab(self)

        self.tabs.addTab(self.editor_tab, "📝 Edytor")
        self.tabs.addTab(self.tm_tab, "💾 Pamięć TM")
        self.tabs.addTab(self.glossary_tab, "🏷️ Glosariusz")
        self.tabs.addTab(self.dictionary_tab, "📖 Słowniki")
        self.tabs.addTab(self.search_tab, "🔍 Znajdź i zamień")
        self.tabs.addTab(self.ai_tab, "🤖 AI")
        self.tabs.addTab(self.qa_tab, "✅ QA i statystyki")
        self.tabs.addTab(self.settings_tab, "⚙️ Ustawienia")
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.setCentralWidget(self.tabs)

    def _on_tab_changed(self, index: int) -> None:
        """Odświeża zawartość zakładki przy jej otwarciu (dane mogły się zmienić w edytorze)."""
        widget = self.tabs.widget(index)
        if widget is self.tm_tab:
            self.tm_tab.refresh()
        elif widget is self.glossary_tab:
            self.glossary_tab.refresh()
        elif widget is self.dictionary_tab:
            self.dictionary_tab.refresh()
        elif widget is self.qa_tab:
            self.qa_tab.refresh_stats()
        elif widget is self.ai_tab:
            self.ai_tab.refresh()
        elif widget is self.settings_tab:
            self.settings_tab.load_segmentation()
        self.update_status()

    def _build_menu(self) -> None:
        menu = self.menuBar()

        file_menu = menu.addMenu("📁 Plik")
        self._add_action(file_menu, "Nowy projekt…", None, self.new_project, shortcut_key="new_project")
        self._add_action(file_menu, "Otwórz projekt…", None, self.open_project, shortcut_key="open_project")
        self._add_action(file_menu, "Pobierz projekt z internetu…", None, self.download_remote_project)
        self.recent_menu = file_menu.addMenu("📂 Ostatnie projekty")
        self._refresh_recent_menu()
        file_menu.addSeparator()
        self._add_action(file_menu, "Zapisz projekt i tłumaczenia", None, self.save_all, shortcut_key="save_all")
        self._add_action(file_menu, "Zamknij projekt", None, self.close_project, shortcut_key="close_project")
        file_menu.addSeparator()
        self._add_action(file_menu, "Importuj pliki…", None, self.import_files, shortcut_key="import_files")
        self._add_action(file_menu, "Wczytaj ponownie folder source/", None, self.reload_source_folder, shortcut_key="reload_source")
        file_menu.addSeparator()
        export_menu = file_menu.addMenu("📤 Eksportuj")
        self._add_action(export_menu, "Przetłumaczone pliki do target/", None, self.export_target_files, shortcut_key="export_files")
        self._add_action(export_menu, "XLIFF…", None, lambda: self.export_as("xliff"))
        self._add_action(export_menu, "TMX (pamięć TM)…", None, self.export_tmx)
        self._add_action(export_menu, "PO…", None, lambda: self.export_as("po"))
        self._add_action(export_menu, "SRT…", None, lambda: self.export_as("srt"))
        self._add_action(export_menu, "HTML dwujęzyczny…", None, lambda: self.export_as("html"))
        self._add_action(export_menu, "TXT…", None, lambda: self.export_as("txt"))
        file_menu.addSeparator()
        self._add_action(file_menu, "Zakończ", None, self.close, shortcut_key="quit")

        edit_menu = menu.addMenu("✏️ Edycja")
        self._add_action(edit_menu, "Cofnij", None, self.undo_action, shortcut_key="undo")
        self._add_action(edit_menu, "Ponów", None, self.redo_action, shortcut_key="redo")
        edit_menu.addSeparator()
        nav_menu = edit_menu.addMenu("↕️ Nawigacja po segmentach")
        self._add_action(nav_menu, "Następny segment", None,
                         lambda: self.editor_tab.next_segment(), shortcut_key="next_segment")
        self._add_action(nav_menu, "Poprzedni segment", None,
                         lambda: self.editor_tab.prev_segment(), shortcut_key="prev_segment")
        nav_menu.addSeparator()
        self._add_action(nav_menu, "Pierwszy segment", None,
                         lambda: self.editor_tab.first_segment(), shortcut_key="first_segment")
        self._add_action(nav_menu, "Ostatni segment", None,
                         lambda: self.editor_tab.last_segment(), shortcut_key="last_segment")
        nav_menu.addSeparator()
        self._add_action(nav_menu, "Następny nieprzetłumaczony", None,
                         lambda: self.editor_tab.next_untranslated(), shortcut_key="next_untranslated")
        self._add_action(nav_menu, "Poprzedni nieprzetłumaczony", None,
                         lambda: self.editor_tab.prev_untranslated(), shortcut_key="prev_untranslated")
        self._add_action(nav_menu, "Następny przetłumaczony", None,
                         lambda: self.editor_tab.next_translated(), shortcut_key="next_translated")
        self._add_action(nav_menu, "Następny niezatwierdzony", None,
                         lambda: self.editor_tab.next_unapproved(), shortcut_key="next_unapproved")
        edit_menu.addSeparator()
        self._add_action(edit_menu, "Kopiuj źródło do tłumaczenia", "Ctrl+D", self.editor_tab.copy_source_to_target, shortcut_key="copy_source")
        self._add_action(edit_menu, "Wstaw najlepsze dopasowanie TM", "Ctrl+Space", self.editor_tab._insert_best_match, shortcut_key="insert_match")
        self._add_action(edit_menu, "Znajdź i zamień", "Ctrl+F", self.open_search, shortcut_key="find_replace")
        self._add_action(edit_menu, "Szukaj zaznaczonego wyrazu w projekcie", None,
                         lambda: self.find_in_project(), shortcut_key="find_selected")
        self._add_action(edit_menu, "Szukaj zaznaczonego wyrazu w tym pliku", None,
                         lambda: self.find_in_project("Tylko przeglądany plik"), shortcut_key="find_in_file")
        self._add_action(edit_menu, "Nowe okno wyszukiwania", None,
                         lambda: self.open_search_window(self.selected_editor_text()), shortcut_key="new_search_window")
        self._add_action(edit_menu, "Wyszukiwanie w zakładce", None,
                         lambda: self.tabs.setCurrentWidget(self.search_tab))
        self._add_action(edit_menu, "Następny wynik wyszukiwania", None,
                         lambda: self._active_search_panel().next_result(), shortcut_key="next_result")
        self._add_action(edit_menu, "Poprzedni wynik wyszukiwania", None,
                         lambda: self._active_search_panel().prev_result(), shortcut_key="prev_result")

        project_menu = menu.addMenu("📦 Projekt")
        self._add_action(project_menu, "Ustawienia projektu…", None, self.open_project_settings)
        self._add_action(project_menu, "Podgląd segmentacji…", None, self.open_segmentation_preview)
        project_menu.addSeparator()
        status_menu = project_menu.addMenu("🏷️ Oznacz zaznaczone jako")
        self._add_action(status_menu, "○ nowy", None, lambda: self.editor_tab.mark_new(), shortcut_key="mark_new")
        self._add_action(status_menu, "🔵 do przetłumaczenia", None,
                         lambda: self.editor_tab.mark_todo(), shortcut_key="mark_todo")
        self._add_action(status_menu, "✎ roboczy", None, lambda: self.editor_tab.mark_draft(), shortcut_key="mark_draft")
        self._add_action(status_menu, "✓ przetłumaczony", None,
                         lambda: self.editor_tab.mark_translated(), shortcut_key="mark_translated")
        self._add_action(status_menu, "★ zatwierdzony", None,
                         lambda: self.editor_tab.approve_current(), shortcut_key="mark_approved")
        self._add_action(project_menu, "Pomiń zaznaczone segmenty", None,
                         lambda: self.editor_tab.ignore_selected(), shortcut_key="ignore_selected")
        self._add_action(project_menu, "Przywróć zaznaczone segmenty", None,
                         lambda: self.editor_tab.restore_selected(), shortcut_key="restore_selected")
        self._add_action(project_menu, "Usuń zaznaczone (tłumaczenie → nowy)", None,
                         lambda: self.editor_tab.clear_selected(), shortcut_key="clear_selected")
        self._add_action(project_menu, "🏷️ Oznacz pasujące do wzorca…", None,
                         lambda: self.editor_tab.bulk_mark_matching())
        self._add_action(project_menu, "Pomiń pasujące do wzorca…", None,
                         lambda: self.editor_tab.ignore_matching())
        self._add_action(project_menu, "Przywróć wszystkie pominięte", None,
                         lambda: self.editor_tab.restore_all_ignored())
        self._add_action(project_menu, "Zastosuj reguły wykluczania", None,
                         lambda: self.apply_exclusions())
        project_menu.addSeparator()
        self._add_action(project_menu, "Zastosuj TM do wszystkich segmentów", None, self.apply_tm_to_all)
        self._add_action(
            project_menu, "Zastosuj TM ponownie (także do przetłumaczonych)", None,
            lambda: self.editor_tab._reapply_tm_to_file(None))
        self._add_action(project_menu, "Przetłumacz maszynowo wszystkie segmenty", None, self.translate_all_mt)
        self._add_action(project_menu, "Zapisz wszystkie segmenty do TM", None, self.save_all_to_tm)
        project_menu.addSeparator()
        folders = project_menu.addMenu("📂 Otwórz folder")
        for label, attr in (
            ("Katalog projektu", "project_path"), ("source/", "source_path"), ("target/", "target_path"),
            ("tm/", "tm_path"), ("glossary/", "glossary_path"), ("dictionary/", "dictionary_path"),
            ("export/", "export_path"),
        ):
            self._add_action(folders, label, None, lambda checked=False, a=attr: self.open_folder(a))

        tools_menu = menu.addMenu("🛠️ Narzędzia")
        self._add_action(tools_menu, "⚡ QuickTrans (wiele silników)…", None, self.open_quicktrans, shortcut_key="quicktrans")
        self._add_action(tools_menu, "Tłumacz wszystko darmowymi silnikami", None,
                         lambda: self.translate_all_mt(free_only=True))
        tools_menu.addSeparator()
        self._add_action(tools_menu, "Kontrola jakości QA", None, self.run_qa, shortcut_key="run_qa")
        self._add_action(tools_menu, "Statystyki projektu", None, self.show_statistics, shortcut_key="statistics")
        self._add_action(tools_menu, "⚡ Zużycie silników MT", None, self.show_usage_report)
        self._add_action(tools_menu, "📋 Kopiuj pomiar czasu", None,
                         lambda: self.editor_tab.copy_timing(), shortcut_key="copy_timing")
        tools_menu.addSeparator()
        self._add_action(tools_menu, "📝 Edytor pamięci TM / TMX…", None, self.open_tmx_editor, shortcut_key="tmx_editor")
        tools_menu.addSeparator()
        self._add_action(tools_menu, "Importuj TMX…", None, self.import_tmx)
        self._add_action(tools_menu, "Eksportuj TMX…", None, self.export_tmx)
        self._add_action(tools_menu, "Zapisz pamięć projektu do TMX", None,
                         lambda: self.export_project_tm_to_tmx(silent=False))
        self._add_action(tools_menu, "Importuj glosariusz…", None, lambda: self.glossary_tab.import_glossary())

        view_menu = menu.addMenu("👁️ Widok")
        self.sentence_action = QAction("🔗 Dopasowanie zdań", self)
        self.sentence_action.setCheckable(True)
        self.sentence_action.setChecked(
            self.settings.get_bool("tm.sentence.matching.enabled", False)
        )
        from ..core import shortcuts as _sc
        _sent = _sc.get("toggle_sentence")
        if _sent:
            self.sentence_action.setShortcut(QKeySequence(_sent))
            self.sentence_action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        self.sentence_action.toggled.connect(self._toggle_sentence_from_menu)
        view_menu.addAction(self.sentence_action)
        self._menu_actions["toggle_sentence"] = self.sentence_action
        view_menu.addSeparator()
        self._add_action(view_menu, "Przełącz motyw (ciemny/jasny)", None, self.toggle_theme, shortcut_key="toggle_theme")
        self._add_action(view_menu, "Powiększ czcionkę edytora", None, lambda: self.change_font(1), shortcut_key="font_plus")
        self._add_action(view_menu, "Zmniejsz czcionkę edytora", None, lambda: self.change_font(-1), shortcut_key="font_minus")
        self._add_action(view_menu, "Powiększ czcionkę interfejsu", None,
                         lambda: self.change_ui_font(1), shortcut_key="ui_font_plus")
        self._add_action(view_menu, "Zmniejsz czcionkę interfejsu", None,
                         lambda: self.change_ui_font(-1), shortcut_key="ui_font_minus")
        view_menu.addSeparator()
        self._add_action(view_menu, "↺ Przywróć układ paneli", "",
                         self.reset_panel_layout)

        help_menu = menu.addMenu("❓ Pomoc")
        self._add_action(help_menu, "O programie / skróty klawiszowe", None, self.show_about, shortcut_key="about")

    def _add_action(self, menu: QMenu, text: str, shortcut: Optional[str], slot,
                    shortcut_key: Optional[str] = None) -> QAction:
        """Dodaje pozycję menu.

        `shortcut_key` wskazuje wpis w centralnym rejestrze – wtedy kombinacja
        pochodzi z Ustawień. Jeśli skrót obsługuje już edytor, menu pokazuje go
        wyłącznie jako podpowiedź (bez rejestrowania), żeby Qt nie uznało go
        za niejednoznaczny.
        """
        from ..core import shortcuts as _sc

        action = QAction(text, self)
        definition = _sc.BY_KEY.get(shortcut_key) if shortcut_key else None
        if definition is not None:
            sequence = _sc.get(definition.key)
            if definition.editor:
                # Skrót żyje w edytorze – w menu tylko go pokazujemy.
                action.setShortcut(QKeySequence(sequence))
                action.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
                action.setShortcutVisibleInContextMenu(True)
            elif sequence:
                action.setShortcut(QKeySequence(sequence))
            self._menu_actions[definition.key] = action
        elif shortcut:
            action.setShortcut(QKeySequence(shortcut))
        action.triggered.connect(slot)
        menu.addAction(action)
        return action

    def reload_shortcuts(self) -> None:
        """Odświeża kombinacje w menu i w edytorze po zmianie w Ustawieniach."""
        from ..core import shortcuts as _sc

        for key, action in getattr(self, "_menu_actions", {}).items():
            sequence = _sc.get(key)
            action.setShortcut(QKeySequence(sequence))
            definition = _sc.BY_KEY.get(key)
            if definition is not None and definition.editor:
                action.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        for action, key, text in getattr(self, "_toolbar_tips", []):
            action.setToolTip(_sc.with_shortcut(key, text) if key else text)
        self.editor_tab.reload_shortcuts()
        self.show_status("Zastosowano nowe skróty klawiszowe")

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Główny")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        from ..core import shortcuts as _sc
        self._toolbar_tips = []
        for text, key, tip, slot in (
            ("📁 Nowy", "new_project", "Nowy projekt", self.new_project),
            ("📂 Otwórz", "open_project", "Otwórz projekt", self.open_project),
            ("💾 Zapisz", "save_all", "Zapisz projekt i tłumaczenia", self.save_all),
            (None, None, None, None),
            ("➕ Importuj pliki", "import_files", "Importuj pliki do projektu", self.import_files),
            ("📤 Eksportuj", "export_files", "Eksportuj przetłumaczone pliki", self.export_target_files),
            (None, None, None, None),
            ("🤖 Tłumacz segment", "machine_translate", "Tłumaczenie maszynowe", lambda: self.editor_tab.machine_translate_current()),
            ("⚡ QuickTrans", "quicktrans", "Tłumaczenie z wielu silników naraz", self.open_quicktrans),
            ("🤖 Tłumacz wszystko", None, "Tłumaczenie maszynowe całego projektu", self.translate_all_mt),
            ("💡 Zastosuj TM", None, "Wstaw dopasowania TM do pustych segmentów", self.apply_tm_to_all),
            (None, None, None, None),
            ("✅ QA", "run_qa", "Kontrola jakości", self.run_qa),
            ("📊 Statystyki", "statistics", "Statystyki projektu", self.show_statistics),
            ("⚙️ Ustawienia", None, "Ustawienia programu", lambda: self.tabs.setCurrentWidget(self.settings_tab)),
        ):
            if text is None:
                toolbar.addSeparator()
                continue
            action = QAction(text, self)
            shown = _sc.with_shortcut(key, tip) if key else tip
            action.setToolTip(shown)
            action.triggered.connect(slot)
            toolbar.addAction(action)
            self._toolbar_tips.append((action, key, tip))

    # ------------------------------------------------------------- motywy
    def _ui_font_px(self) -> int:
        """Rozmiar czcionki interfejsu w pikselach (0 = wartość z motywu)."""
        points = self.settings.get_int("ui.font.size", 0)
        return int(round(points * 96 / 72)) if points > 0 else 0

    def apply_theme(self) -> None:
        dark = self.settings.get_bool("theme.dark", True)
        QApplication.instance().setStyleSheet(stylesheet(dark, self._ui_font_px()))
        restyle_splitters(self, dark)
        self.editor_tab.colors.dark = dark
        self.editor_tab.refresh_grid()

    def _toggle_sentence_from_menu(self, checked: bool) -> None:
        """Włącza/wyłącza dopasowanie zdań z menu Widok."""
        self.settings.set("tm.sentence.matching.enabled", checked)
        self.editor_tab.sync_sentence_toggle()
        box = getattr(self.settings_tab, "sentence_matching", None)
        if box is not None and box.isChecked() != checked:
            box.blockSignals(True)
            box.setChecked(checked)
            box.blockSignals(False)
            self.settings_tab._update_sentence_enabled()
        if checked:
            self.editor_tab._refresh_helpers()
        else:
            self.editor_tab.sentence_list.clear()
            self.editor_tab.sentence_info.setText("Dopasowanie zdań wyłączone")
        self.show_status(
            "🔗 Dopasowanie zdań włączone" if checked else "Dopasowanie zdań wyłączone"
        )

    def reset_panel_layout(self) -> None:
        """Przywraca domyślne szerokości paneli w Edytorze.

        Ratunek, gdy ktoś zwęzi panel do minimum i nie chce mu się go
        rozciągać z powrotem myszą.
        """
        editor = getattr(self, "editor_tab", None)
        main = getattr(editor, "main_splitter", None)
        center = getattr(editor, "center_splitter", None)
        if main is not None:
            total = max(900, main.width())
            main.setSizes([int(total * 0.16), int(total * 0.62), int(total * 0.22)])
        if center is not None:
            height = max(400, center.height())
            center.setSizes([int(height * 0.6), int(height * 0.4)])
        # Wysokości paneli po prawej (przeciągane osobno) też wracają do
        # równego podziału — inaczej „przywrócenie układu” działało połowicznie.
        editor_reset = getattr(editor, "reset_panel_heights", None)
        if editor_reset is not None:
            editor_reset()
        self.show_status("↺ Przywrócono domyślny układ paneli")

    def toggle_theme(self) -> None:
        self.settings.set("theme.dark", not self.settings.get_bool("theme.dark", True))
        self.apply_theme()

    def apply_font(self, also_theme: bool = False) -> None:
        """Czcionka całego programu (`ui.font.size`) + pól edytora.

        Sam `setFont` na aplikacji nie wystarcza: motyw narzuca
        `QWidget { font-size }`, który jest ważniejszy dla kontrolki. Dlatego
        przy zmianie rozmiaru interfejsu (`also_theme`) przebudowujemy też
        arkusz stylów i czcionkę paneli po prawej.
        """
        app = QApplication.instance()
        size = self.settings.get_int("ui.font.size", 0)
        base = getattr(self, "_base_app_font", None)
        if base is None:
            # Czcionka z systemu — zapamiętana raz, żeby powrót do „0”
            # przywrócił ją zamiast ostatnio ustawionej.
            self._base_app_font = base = QFont(app.font())
        if size > 0:
            font = QFont(base)
            font.setPointSize(size)
            app.setFont(font)
        else:
            app.setFont(base)

        editor_font = QFont(self.settings.get_str("editor.font.family", "Segoe UI"),
                            self.settings.get_int("editor.font.size", 12))
        for widget in (self.editor_tab.source_edit, self.editor_tab.target_edit):
            widget.setFont(editor_font)
        if also_theme:
            self.apply_theme()
            self.editor_tab.apply_panel_font()

    def apply_ui_font(self) -> None:
        """Zmiana rozmiaru czcionki całego interfejsu (Ustawienia → Wygląd)."""
        self.apply_font(also_theme=True)

    def change_font(self, delta: int) -> None:
        size = max(8, min(28, self.settings.get_int("editor.font.size", 12) + delta))
        self.settings.set("editor.font.size", size)
        self.apply_font()

    def change_ui_font(self, delta: int) -> None:
        """Powiększa / zmniejsza czcionkę CAŁEGO programu (menu Widok)."""
        current = self.settings.get_int("ui.font.size", 0) or 10
        size = max(8, min(28, current + delta))
        self.settings.set("ui.font.size", size)
        self.apply_ui_font()
        self.show_status(f"🔠 Czcionka interfejsu: {size} pkt")

    # ------------------------------------------------------------ projekt
    def new_project(self) -> None:
        dialog = NewProjectDialog(self)
        if dialog.exec() != NewProjectDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        try:
            project = self.project_manager.create_project(
                values["name"], values["source_lang"], values["target_lang"], values["base_path"]
            )
            project.segmentation.mode = values["seg_mode"]
            self.project_manager.save_project()
            self._load_project_resources(project)
            self.editor_tab.set_segments([])
            self.show_status(f"Utworzono projekt: {project.name}")
            QMessageBox.information(
                self, "Nowy projekt",
                f"Projekt „{project.name}” został utworzony.\n\n{project.project_path}\n\n"
                "Skopiuj pliki do folderu source/ albo użyj „Importuj pliki…” (Ctrl+I).",
            )
        except Exception as exc:
            QMessageBox.critical(self, "Błąd", f"Nie udało się utworzyć projektu:\n{exc}")

    def download_remote_project(self) -> None:
        """Ściąga projekt z GitHuba / gita (jak zespół w OmegaT) i otwiera go."""
        dialog = DownloadRemoteProjectDialog(self)
        if dialog.exec() != DownloadRemoteProjectDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        url = values.get("url") or ""
        if not url:
            QMessageBox.warning(self, "Pobierz projekt", "Podaj adres URL repozytorium.")
            return
        token = values.get("token") or ""
        if token:
            self.settings.set("git.github.token", token)
        folder = values.get("folder") or ""
        if folder:
            self.settings.set("git.clone.folder", folder)
        progress = QProgressDialog("Pobieranie projektu…", None, 0, 0, self)
        progress.setWindowTitle("Projekt z internetu")
        progress.setMinimumDuration(0)
        progress.show()
        QApplication.processEvents()
        try:
            from ..core.remote_project import fetch_remote_project, find_or_create_scproj
            dest, err = fetch_remote_project(url, folder, token)
        finally:
            progress.close()
        if err:
            QMessageBox.warning(self, "Pobierz projekt", err)
            return
        try:
            scproj = find_or_create_scproj(
                dest,
                source_lang="en",
                target_lang="pl",
            )
        except Exception as exc:
            QMessageBox.warning(self, "Pobierz projekt", str(exc))
            return
        self.open_project_path(scproj)
        self.show_status(f"Pobrano projekt z sieci: {dest}")

    def open_project(self) -> None:
        base = os.path.join(os.path.expanduser("~"), "SuperCAT_Projects")
        path, _ = QFileDialog.getOpenFileName(
            self, "Otwórz projekt", base if os.path.exists(base) else "",
            f"Projekt SuperCAT (*{PROJECT_EXT});;Wszystkie pliki (*)",
        )
        if path:
            self.open_project_path(path)

    def open_project_path(self, path: str) -> None:
        """Otwiera projekt, pokazując okno postępu z etapami wczytywania."""
        from .dialogs.loading_dialog import LoadingDialog

        steps = ["Wczytywanie projektu", "Pamięć tłumaczeń", "Glosariusz i słowniki",
                 "Parsowanie plików źródłowych", "Wczytywanie tłumaczeń", "Kończenie"]
        dialog = LoadingDialog("Otwieranie projektu", steps, self)
        dialog.show()
        QApplication.processEvents()
        try:
            dialog.start_step("Wczytywanie projektu…", os.path.basename(path))
            project = self.project_manager.open_project(path)
            dialog.set_detail(f"{project.name}  [{project.source_lang} → {project.target_lang}]")

            self._load_project_resources(project, dialog)

            dialog.start_step("Wczytywanie tłumaczeń…")
            self.load_translations()

            dialog.start_step("Kończenie…")
            self.settings.set("last.project.path", path)
            self._refresh_recent_menu()
            dialog.finish()

            self.show_status(f"Otwarto projekt: {project.name}")
            self.run_on_load_automation()
        except Exception as exc:
            dialog.close()
            traceback.print_exc()
            QMessageBox.critical(self, "Błąd", f"Nie udało się otworzyć projektu:\n{exc}")

    def _load_project_resources(self, project: Project, dialog=None) -> None:
        """Wczytuje zasoby projektu. `dialog` (opcjonalny) pokazuje postęp."""
        def step(text: str, detail: str = "") -> None:
            if dialog is not None:
                dialog.start_step(text, detail)

        def detail(text: str) -> None:
            if dialog is not None:
                dialog.set_detail(text)

        self._exclusions = None          # reguły należą do projektu

        step("Pamięć tłumaczeń…")
        self.tm.init_for_project(project.tm_path)
        detail(f"{self.tm.size()} jednostek w pamięci")

        step("Glosariusz i słowniki…")
        self.glossary.init_for_project(project.glossary_path)
        self.dictionary.init_for_project(project.dictionary_path)
        # Silnik lokalny korzysta z terminów projektu, nie tylko z 25 wbudowanych.
        self.mt.tm_provider = self.tm
        self.mt.glossary_provider = self.glossary
        detail(f"glosariusz: {self.glossary.size} terminów  •  "
               f"słowniki: {self.dictionary.size} słów")
        imported = self.tm.auto_import_folder(project.tm_path)
        if imported:
            self.show_status(f"Zaimportowano {imported} jednostek TMX z folderu tm/")
        # Indeksy pamięci budujemy w TLE zaraz po otwarciu projektu – dzięki temu
        # pierwsze wyszukiwanie nie płaci jednorazowego kosztu w trakcie pracy.
        warmup = TMWarmupWorker(self.tm, parent=self)

        def on_warm(count: int) -> None:
            self._workers.discard(warmup)
            self.show_status(f"Pamięć TM gotowa ({count} jednostek)")

        warmup.finished_warmup.connect(on_warm)
        self._workers.add(warmup)
        warmup.start()
        self.setWindowTitle(
            f"{APP_NAME} {VERSION} – {project.name} [{project.source_lang} → {project.target_lang}]"
        )
        self.tm_tab.refresh()
        self.glossary_tab.refresh()
        self.dictionary_tab.refresh()
        self.settings_tab.load_segmentation()

        step("Parsowanie plików źródłowych…")
        self.load_source_files(auto=True, dialog=dialog)
        self.update_status()

    def close_project(self) -> None:
        if self.project:
            self.save_all(silent=True)
        self.project_manager.close_project()
        self.tm.close()
        self.glossary = Glossary()
        self.dictionary = Dictionary()
        self.editor_tab.set_segments([])
        self.tm_tab.refresh()
        self.glossary_tab.refresh()
        self.setWindowTitle(f"{APP_NAME} {VERSION}")
        self.update_status()

    def open_project_settings(self) -> None:
        if not self._require_project():
            return
        dialog = ProjectSettingsDialog(self.project, self)
        if dialog.exec() == ProjectSettingsDialog.DialogCode.Accepted:
            dialog.apply()
            self.project_manager.save_project()
            self.settings_tab.load_segmentation()
            self.setWindowTitle(
                f"{APP_NAME} {VERSION} – {self.project.name} "
                f"[{self.project.source_lang} → {self.project.target_lang}]"
            )
            self.show_status("Zapisano ustawienia projektu")

    def open_segmentation_preview(self) -> None:
        from ..core.project import SegmentationSettings

        settings = self.project.segmentation if self.project else SegmentationSettings()
        SegmentationPreviewDialog(settings, self).exec()

    def open_folder(self, attr: str) -> None:
        if not self._require_project():
            return
        path = getattr(self.project, attr)
        os.makedirs(path, exist_ok=True)
        import subprocess
        import sys

        try:
            if sys.platform.startswith("win"):
                os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception:
            QMessageBox.information(self, "Folder", path)

    # -------------------------------------------------------------- pliki
    def import_files(self) -> None:
        if not self._require_project():
            return
        patterns = " ".join(f"*{ext}" for ext in SUPPORTED_EXTENSIONS)
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Importuj pliki do projektu", "",
            f"Obsługiwane pliki ({patterns});;Wszystkie pliki (*)",
        )
        if not paths:
            return
        self.import_file_paths(paths)

    def import_file_paths(self, paths: List[str]) -> int:
        """Kopiuje wskazane pliki do folderu source/ i wczytuje je.

        Wspólne dla menu „Importuj pliki…” oraz przeciągania plików na listę.
        """
        if not self._require_project():
            return 0

        supported, skipped = [], []
        for path in paths:
            if os.path.isdir(path):
                # z katalogu bierzemy pliki obsługiwanych typów (bez wchodzenia głębiej)
                for name in sorted(os.listdir(path)):
                    full = os.path.join(path, name)
                    if os.path.isfile(full) and name.lower().endswith(SUPPORTED_EXTENSIONS):
                        supported.append(full)
            elif path.lower().endswith(SUPPORTED_EXTENSIONS):
                supported.append(path)
            else:
                skipped.append(os.path.basename(path))

        if not supported:
            QMessageBox.information(
                self, "Import plików",
                "Żaden z przeciągniętych plików nie jest obsługiwany.\n\n"
                f"Obsługiwane rozszerzenia: {', '.join(SUPPORTED_EXTENSIONS)}",
            )
            return 0

        os.makedirs(self.project.source_path, exist_ok=True)
        copied, overwritten = 0, []
        for path in supported:
            dest = os.path.join(self.project.source_path, os.path.basename(path))
            if os.path.abspath(path) == os.path.abspath(dest):
                copied += 1          # plik już jest w projekcie
                continue
            if os.path.exists(dest):
                overwritten.append(os.path.basename(path))
            try:
                shutil.copy2(path, dest)
                copied += 1
            except Exception as exc:
                skipped.append(f"{os.path.basename(path)} ({exc})")

        if overwritten:
            answer = QMessageBox.question(
                self, "Plik już istnieje",
                f"Zastąpiono pliki o tych samych nazwach:\n{', '.join(overwritten[:8])}\n\n"
                "Wczytać projekt ponownie?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return copied

        self.load_source_files()
        message = f"Zaimportowano {copied} plików"
        if skipped:
            message += f" (pominięto {len(skipped)}: {', '.join(skipped[:4])})"
        self.show_status(message)
        self.run_on_load_automation()
        return copied

    def remove_project_file(self, file_name: str) -> bool:
        """Usuwa plik z projektu: z folderu source/, z segmentów i z zapisu tłumaczeń."""
        if not self._require_project() or not file_name:
            return False

        segments = [s for s in self.editor_tab.segments
                    if (s.file_name or "(bez pliku)") == file_name]
        translated = sum(1 for s in segments if s.is_translated)
        warning = (f"\n\n⚠️ {translated} z {len(segments)} segmentów ma tłumaczenia — "
                   "zostaną utracone.") if translated else ""
        if QMessageBox.question(
            self, "Usuń plik z projektu",
            f"Usunąć „{file_name}” z projektu?\n\n"
            f"Plik zostanie skasowany z folderu source/ ({len(segments)} segmentów)."
            f"{warning}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return False

        # 1) plik źródłowy
        source_file = os.path.join(self.project.source_path, file_name)
        if os.path.exists(source_file):
            try:
                os.remove(source_file)
            except Exception as exc:
                QMessageBox.critical(self, "Błąd", f"Nie udało się usunąć pliku:\n{exc}")
                return False

        # 2) zapisane tłumaczenia tego pliku
        stored = self._read_translations()
        if stored:
            remaining = {k: v for k, v in stored.items()
                         if not k.startswith(f"{file_name}::")}
            if len(remaining) != len(stored):
                with open(self._translations_path(), "w", encoding="utf-8") as fh:
                    json.dump(remaining, fh, ensure_ascii=False, indent=1)

        # 3) segmenty w pamięci
        kept = [s for s in self.editor_tab.segments
                if (s.file_name or "(bez pliku)") != file_name]
        self.editor_tab.set_segments(kept)
        if file_name in (self.project.source_files or []):
            self.project.source_files.remove(file_name)
        if file_name in (self.project.file_order or []):
            self.project.file_order.remove(file_name)
        self.project_manager.save_project()
        self.show_status(f"🗑️ Usunięto „{file_name}” ({len(segments)} segmentów)")
        return True

    def remove_project_files(self, file_names: List[str]) -> int:
        """Usuwa kilka plików naraz — jedno pytanie zamiast serii okien.

        Zwraca liczbę faktycznie usuniętych plików.
        """
        if not self._require_project() or not file_names:
            return 0

        wanted = set(file_names)
        segments = [s for s in self.editor_tab.segments
                    if (s.file_name or "(bez pliku)") in wanted]
        translated = sum(1 for s in segments if s.is_translated)
        listing = "\n".join(f"  • {name}" for name in sorted(wanted)[:12])
        if len(wanted) > 12:
            listing += f"\n  • …i {len(wanted) - 12} więcej"
        warning = (f"\n\n⚠️ {translated} z {len(segments)} segmentów ma tłumaczenia — "
                   "zostaną utracone.") if translated else ""
        if QMessageBox.question(
            self, "Usuń pliki z projektu",
            f"Usunąć {len(wanted)} plików z projektu?\n\n{listing}\n\n"
            f"Pliki zostaną skasowane z folderu source/ "
            f"({len(segments)} segmentów).{warning}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return 0

        removed, failed = [], []
        for name in sorted(wanted):
            path = os.path.join(self.project.source_path, name)
            if os.path.exists(path):
                try:
                    os.remove(path)
                except Exception as exc:
                    failed.append(f"{name}: {exc}")
                    continue
            removed.append(name)

        if not removed:
            QMessageBox.critical(self, "Błąd",
                                 "Nie udało się usunąć plików:\n" + "\n".join(failed))
            return 0

        # zapisane tłumaczenia usuniętych plików
        stored = self._read_translations()
        if stored:
            prefixes = tuple(f"{name}::" for name in removed)
            remaining = {k: v for k, v in stored.items() if not k.startswith(prefixes)}
            if len(remaining) != len(stored):
                with open(self._translations_path(), "w", encoding="utf-8") as fh:
                    json.dump(remaining, fh, ensure_ascii=False, indent=1)

        gone = set(removed)
        kept = [s for s in self.editor_tab.segments
                if (s.file_name or "(bez pliku)") not in gone]
        self.editor_tab.set_segments(kept)
        self.project.source_files = [f for f in (self.project.source_files or [])
                                     if f not in gone]
        self.project.file_order = [f for f in (self.project.file_order or [])
                                   if f not in gone]
        self.project_manager.save_project()

        message = f"🗑️ Usunięto {len(removed)} plików ({len(segments)} segmentów)"
        if failed:
            message += f"  •  nie udało się: {len(failed)}"
            QMessageBox.warning(self, "Usuwanie plików",
                                "Nie udało się usunąć:\n" + "\n".join(failed))
        self.show_status(message)
        return len(removed)

    def reload_source_folder(self) -> None:
        """F5 – ponowne wczytanie plików źródłowych, z oknem postępu."""
        if not self._require_project():
            return
        from .dialogs.loading_dialog import LoadingDialog

        dialog = LoadingDialog("Przeładowywanie plików",
                               ["Parsowanie plików źródłowych"], self)
        dialog.show()
        QApplication.processEvents()
        try:
            dialog.start_step("Parsowanie plików źródłowych…")
            self.load_source_files(dialog=dialog)
            dialog.finish()
        except Exception:
            dialog.close()
            raise

    def load_source_files(self, auto: bool = False, dialog=None) -> None:
        """Parsuje wszystkie pliki z folderu source/ na segmenty.

        `dialog` (opcjonalny) pokazuje, który plik jest właśnie przetwarzany –
        parsowanie to najdłuższy etap otwierania projektu.
        """
        if not self.project:
            return
        folder = self.project.source_path
        os.makedirs(folder, exist_ok=True)
        files = order_files(
            [f for f in sorted(os.listdir(folder))
             if f.lower().endswith(SUPPORTED_EXTENSIONS)
             and os.path.isfile(os.path.join(folder, f))],
            self.project.file_order,
        )
        if not files:
            if not auto:
                QMessageBox.information(
                    self, "Import", f"Folder source/ jest pusty.\n\n{folder}\n\nUżyj „Importuj pliki…” (Ctrl+I)."
                )
            self.editor_tab.set_segments([])
            return

        existing = {(s.file_name, s.seg_id): s.target for s in self.editor_tab.segments}
        stored = self._read_translations()
        segments: List[Segment] = []
        errors = []
        for number, name in enumerate(files, start=1):
            path = os.path.join(folder, name)
            if dialog is not None:
                dialog.set_detail(f"plik {number}/{len(files)}: {name}")
            try:
                parsed = parse_file(path, self.project.segmentation)
                for seg in parsed:
                    key = f"{seg.file_name}::{seg.seg_id}"
                    if key in stored:
                        seg.target = stored[key].get("target", "")
                        seg.status = stored[key].get("status", "new")
                        seg.notes = stored[key].get("notes", "")
                        seg.ignored = stored[key].get("ignored", False)
                        # ręczne decyzje o pominięciu przetrwają F5
                        for flag in ("manual_skip", "manual_keep", "auto_excluded"):
                            if stored[key].get(flag):
                                seg.extra[flag] = True
                    elif (seg.file_name, seg.seg_id) in existing:
                        seg.target = existing[(seg.file_name, seg.seg_id)]
                segments.extend(parsed)
            except Exception as exc:
                errors.append(f"{name}: {exc}")

        self.project.source_files = files
        # Kolejność zapisujemy tylko, gdy użytkownik ją ustawił – inaczej
        # plik projektu puchłby o listę powielającą zawartość folderu.
        if self.project.file_order:
            self.project.file_order = [f for f in files]
        self.project_manager.save_project()

        # Oznacz automatycznie segmenty pasujące do reguł (wiersze
        # techniczne → pominięte; np. CHEM* → przetłumaczone) – reguły są
        # zapisane w projekcie.
        excluded = 0
        rules = self.exclusion_set()
        if rules.enabled and rules.active_rules:
            excluded, _restored = rules.apply(segments)

        self.editor_tab.set_segments(segments)
        self.qa_tab.refresh_stats()
        msg = f"Wczytano {len(segments)} segmentów z {len(files)} plików"
        if excluded:
            only_skip = all(r.action == "skip" for r in rules.active_rules)
            if only_skip:
                msg += f"  •  wykluczono {excluded} wierszy technicznych"
            else:
                msg += f"  •  oznaczono wg reguł {excluded} segmentów"
        if errors:
            msg += f" (błędy: {len(errors)})"
            QMessageBox.warning(self, "Import", "Nie udało się wczytać niektórych plików:\n\n" + "\n".join(errors))
        self.show_status(msg)

    # -------------------------------------------------- zapis tłumaczeń
    def _translations_path(self) -> str:
        return os.path.join(self.project.project_path, TRANSLATIONS_FILE)

    def _read_translations(self) -> dict:
        if not self.project:
            return {}
        path = self._translations_path()
        if not os.path.exists(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            return {}

    def save_translations(self, silent: bool = False) -> None:
        if not self.project:
            return
        data = {}
        for seg in self.editor_tab.segments:
            entry = {
                "source": seg.source,
                "target": seg.target,
                "status": seg.status,
                "notes": seg.notes,
                "ignored": seg.ignored,
            }
            # Ręczne decyzje o pominięciu muszą przetrwać ponowne wczytanie
            # plików (F5) – inaczej reguły znów zabrałyby cofnięte segmenty.
            extra = getattr(seg, "extra", None)
            if isinstance(extra, dict):
                for flag in ("manual_skip", "manual_keep", "auto_excluded"):
                    if extra.get(flag):
                        entry[flag] = True
                nick = extra.get("translator")
                if nick:
                    entry["translator"] = nick
            data[f"{seg.file_name}::{seg.seg_id}"] = entry
        with open(self._translations_path(), "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=1)
        if not silent:
            self.show_status("Zapisano tłumaczenia")

    def load_translations(self) -> None:
        stored = self._read_translations()
        if not stored:
            return
        for seg in self.editor_tab.segments:
            key = f"{seg.file_name}::{seg.seg_id}"
            if key in stored:
                seg.target = stored[key].get("target", "")
                seg.status = stored[key].get("status", "new")
                seg.notes = stored[key].get("notes", "")
                seg.ignored = stored[key].get("ignored", False)
                for flag in ("manual_skip", "manual_keep", "auto_excluded"):
                    if stored[key].get(flag):
                        seg.extra[flag] = True
                nick = stored[key].get("translator")
                if nick:
                    seg.extra["translator"] = nick
        self.editor_tab.refresh_grid()
        if self.editor_tab.segments:
            self.editor_tab.load_segment(self.editor_tab.current_index if self.editor_tab.current_index >= 0 else 0)

    def export_project_tm_to_tmx(self, silent: bool = True) -> Optional[str]:
        """Zapisuje pamięć projektu do pliku TMX w folderze tm/.

        Baza SQLite jest formatem roboczym (szybkie wyszukiwanie), ale TMX to
        format wymienny – dlatego pamięć jest do niego automatycznie zrzucana
        przy zapisie projektu. Plik można otworzyć w innym narzędziu CAT.
        """
        if not self.project or not self.tm.is_initialized:
            return None
        if not self.settings.get_bool("tm.autosave.tmx", True):
            return None
        name = self.settings.get_str("tm.autosave.tmx.name", "project_tm.tmx") or "project_tm.tmx"
        path = os.path.join(self.project.tm_path, name)
        try:
            count = self.tm.export_tmx(path, self.project.source_lang, self.project.target_lang)
            # plik jest naszym własnym zrzutem – nie importuj go ponownie przy starcie
            try:
                stat = os.stat(path)
                self.tm._conn.execute(
                    "INSERT OR REPLACE INTO tm_files (path, size, mtime, units) VALUES (?, ?, ?, ?)",
                    (os.path.abspath(path), stat.st_size, stat.st_mtime, count),
                )
                self.tm._conn.commit()
            except Exception:
                pass
            if not silent:
                self.show_status(f"💾 Zapisano pamięć do {name} ({count} jednostek)")
            return path
        except Exception as exc:
            print(f"⚠️ Nie udało się zapisać TMX: {exc}")
            return None

    def save_all(self, silent: bool = False) -> None:
        if not self.project:
            if not silent:
                QMessageBox.information(self, "Zapis", "Brak otwartego projektu.")
            return
        self.editor_tab._store_current()
        self.tm.flush()
        self.project_manager.save_project()
        self.save_translations(silent=True)
        self.export_project_tm_to_tmx(silent=True)
        if not silent:
            self.show_status("💾 Zapisano projekt, tłumaczenia i pamięć TMX")

    # -------------------------------------------------------------- akcje
    def apply_tm_to_all(self, silent: bool = False, threshold: Optional[int] = None,
                        then=None, only_file: Optional[str] = None,
                        include_translated: bool = False) -> None:
        """Uzupełnia segmenty z TM – wsadowo i w tle (nie blokuje okna).

        `only_file` ogranicza działanie do jednego pliku projektu (opcja z menu
        podręcznego listy plików).

        `include_translated` włącza też segmenty, które mają już tłumaczenie —
        wtedy najlepsze dopasowanie z TM je **podmienia** (przydatne, gdy do
        pamięci doszły nowe, lepsze wpisy). Segmentów ★ zatwierdzonych nie
        ruszamy, żeby nie stracić gotowej pracy.
        """
        if not self._require_project():
            return
        segments = self.editor_tab.segments
        if not segments or not self.tm.is_initialized:
            return
        self.editor_tab._store_current()

        if include_translated:
            todo = [
                (i, s.source) for i, s in enumerate(segments)
                if not s.ignored and s.status != "approved"
                and (only_file is None or (s.file_name or "(bez pliku)") == only_file)
            ]
        else:
            todo = [
                (i, s.source) for i, s in enumerate(segments)
                if not s.is_translated and not s.ignored
                and (only_file is None or (s.file_name or "(bez pliku)") == only_file)
            ]
        if not todo:
            if not silent:
                QMessageBox.information(
                    self, "Zastosuj TM",
                    "Wszystkie segmenty mają już tłumaczenie."
                    if not include_translated
                    else "Nie ma segmentów, w których można podmienić tłumaczenie.")
            if then is not None:
                then()
            return

        indices = [i for i, _s in todo]
        sources = [s for _i, s in todo]
        if threshold is None:
            threshold = self.settings.get_int("auto.insert.threshold", 80)

        scope = f" – {only_file}" if only_file else ""
        progress = QProgressDialog(
            f"Dopasowywanie z pamięci TM{scope} ({len(sources)} segmentów)…",
            "Anuluj", 0, len(sources), self,
        )
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(300)

        worker = PreTranslateWorker(self.tm, sources, indices, threshold, parent=self)
        worker.progress.connect(lambda done, total: progress.setValue(done))
        progress.canceled.connect(worker.cancel)

        def on_done(idx_list, matches):
            progress.close()
            filled = 0      # wstawione w puste segmenty
            replaced = 0    # podmienione istniejące tłumaczenia
            for seg_index, match in zip(idx_list, matches):
                if match is None:
                    continue
                seg = segments[seg_index]
                new_text = copy_edge_whitespace(seg.source, match.text)
                old_text = seg.target or ""
                if not old_text.strip():
                    if not new_text.strip():
                        continue
                    seg.target = new_text
                    seg.status = "draft"
                    filled += 1
                elif old_text.strip() != new_text.strip():
                    # Tłumaczenie już było — podmieniamy treść, ale ZOSTAWIAMY
                    # dotychczasowy status (żeby przetłumaczone nie spadały
                    # do „roboczego” i nie psuły licznika postępu).
                    seg.target = new_text
                    replaced += 1
            self.editor_tab.refresh_grid()
            if self.editor_tab.current_index >= 0:
                self.editor_tab.load_segment(self.editor_tab.current_index)
            applied = filled + replaced
            summary = ", ".join(part for part in (
                f"wstawiono {filled}" if filled else "",
                f"podmieniono {replaced}" if replaced else "",
            ) if part) or "nic do zmiany"
            self.show_status(f"💡 TM: {summary}")
            if not silent:
                QMessageBox.information(self, "Zastosuj TM",
                                        f"Zrobione — {summary}.")
            self._workers.discard(worker)
            if then is not None:
                then()

        worker.finished_batch.connect(on_done)
        self._workers.add(worker)
        worker.start()

    def translate_all_mt(self, free_only: bool = False, skip_confirm: bool = False,
                         only_file: Optional[str] = None) -> None:
        """Tłumaczenie maszynowe wszystkich pustych segmentów – w tle.

        `free_only=True` wymusza pierwszy dostępny silnik bez klucza API
        (Google/MyMemory), nie zmieniając ustawienia domyślnego.
        """
        if not self._require_project():
            return
        self.editor_tab._store_current()
        todo = [
            (i, s.source) for i, s in enumerate(self.editor_tab.segments)
            if not s.is_translated and not s.ignored
            and (only_file is None or (s.file_name or "(bez pliku)") == only_file)
        ]
        if not todo:
            QMessageBox.information(self, "Tłumaczenie maszynowe", "Wszystkie segmenty są już przetłumaczone.")
            return
        engine = self.settings.get_str("mt.batch.engine", "") or self.mt.engine
        if free_only:
            free = [e for e in self.mt.available_engines(only_free=True) if e != "local"]
            if not free:
                QMessageBox.information(self, "Tłumaczenie maszynowe", "Brak dostępnych silników darmowych.")
                return
            engine = free[0]
        engine_label = dict(__import__("supercat.core.mt", fromlist=["ENGINES"]).ENGINES).get(engine, engine)

        scope = f" z pliku „{only_file}”" if only_file else ""
        if not skip_confirm and QMessageBox.question(
            self, "Tłumaczenie maszynowe",
            f"Przetłumaczyć {len(todo)} segmentów{scope} silnikiem „{engine_label}”?",
        ) != QMessageBox.StandardButton.Yes:
            return

        indices = [i for i, _s in todo]
        sources = [s for _i, s in todo]
        segments = self.editor_tab.segments

        progress = QProgressDialog("Tłumaczenie maszynowe…", "Anuluj", 0, len(sources), self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(300)

        worker = MTWorker(
            self.mt, sources, indices, self.project.source_lang, self.project.target_lang,
            engine=engine, parent=self,
        )
        progress.canceled.connect(worker.cancel)
        self.ai_tab.begin_activity(f"Tłumaczenie {len(sources)} segmentów silnikiem „{engine}”")

        def on_progress(done: int, total: int, text: str) -> None:
            progress.setValue(done)
            progress.setLabelText(f"Tłumaczenie {done + 1}/{total}…\n{text}")
            # co 10 segmentów zapisz ślad w dzienniku AI
            if done and done % 10 == 0:
                self.ai_tab.log(f"Przetłumaczono {done}/{total} segmentów", "info")

        worker.progress.connect(on_progress)

        def on_translated(seg_index: int, text: str):
            segments[seg_index].target = copy_edge_whitespace(segments[seg_index].source, text)
            segments[seg_index].status = "draft"

        def on_finished(count: int):
            progress.close()
            self.ai_tab.end_activity(f"Zakończono: {count} segmentów", "ok")
            self.editor_tab.refresh_grid()
            if self.editor_tab.current_index >= 0:
                self.editor_tab.load_segment(self.editor_tab.current_index)
            self.show_status(f"🤖 Przetłumaczono maszynowo {count} segmentów")
            self._workers.discard(worker)

        worker.translated.connect(on_translated)
        worker.finished_all.connect(on_finished)
        self._workers.add(worker)
        worker.start()

    def save_all_to_tm(self) -> None:
        if not self._require_project():
            return
        count = 0
        for seg in self.editor_tab.segments:
            if seg.is_translated and not seg.ignored:
                if self.tm.add(seg.source, seg.target, self.project.source_lang, self.project.target_lang):
                    count += 1
        self.tm_tab.refresh()
        QMessageBox.information(self, "Pamięć TM", f"Zapisano {count} segmentów do pamięci tłumaczeń.")

    def run_on_load_automation(self) -> None:
        """Automatyczne uzupełnianie po wczytaniu tekstu (wg Ustawień → Pamięć TM).

        Kolejno: wstawienie dopasowań z TM, a następnie – opcjonalnie –
        tłumaczenie maszynowe segmentów, dla których TM nic nie znalazła.
        """
        if not self.project or not self.editor_tab.segments:
            return
        use_tm = self.settings.get_bool("auto.apply.on.load", False)
        use_mt = self.settings.get_bool("auto.mt.on.load", False)
        if not use_tm and not use_mt:
            return

        pending = sum(1 for s in self.editor_tab.segments if not s.is_translated and not s.ignored)
        if not pending:
            return

        if self.settings.get_bool("auto.load.confirm", True):
            steps = []
            if use_tm:
                steps.append("uzupełnić z pamięci TM")
            if use_mt:
                steps.append("przetłumaczyć maszynowo resztę")
            if QMessageBox.question(
                self, "Automatyczne uzupełnianie",
                f"Wczytano {pending} nieprzetłumaczonych segmentów.\n\n"
                f"Czy {' oraz '.join(steps)}?",
            ) != QMessageBox.StandardButton.Yes:
                return

        if use_tm:
            threshold = self.settings.get_int("auto.apply.on.load.threshold", 80)
            self.apply_tm_to_all(silent=True, threshold=threshold,
                                 then=self._auto_mt_after_tm if use_mt else None)
        elif use_mt:
            self.translate_all_mt(skip_confirm=True)

    def _auto_mt_after_tm(self) -> None:
        """Druga faza automatyki – MT dla segmentów, których TM nie pokryła."""
        if self.settings.get_bool("auto.mt.on.load", False):
            self.translate_all_mt(skip_confirm=True)

    def register_tm_source(self, path: str, units: int) -> None:
        """Zapamiętuje zaimportowaną pamięć, aby była widoczna na liście TM."""
        if not self.project:
            return
        sources = list(getattr(self.project, "tm_sources", []) or [])
        target = os.path.abspath(path)
        for entry in sources:
            if os.path.abspath(entry.get("path", "")) == target:
                entry["units"] = units
                break
        else:
            sources.append({"name": os.path.basename(path), "path": target, "units": units})
        self.project.tm_sources = sources
        try:
            self.project_manager.save_project()
        except Exception:
            pass

    def open_tmx_editor(self) -> None:
        """Edytor pamięci TM / plików TMX (wzorowany na TMX Editor z Supervertaler)."""
        from .tmx_editor import TMXEditorDialog

        dialog = TMXEditorDialog(self, parent=self)
        dialog.exec()
        self.tm_tab.refresh()
        self.update_status()

    def open_quicktrans(self) -> None:
        """Popup z tłumaczeniami ze wszystkich dostępnych silników (jak w Supervertaler)."""
        from .quicktrans import QuickTransDialog

        seg = self.editor_tab.current_segment()
        text = ""
        if self.editor_tab.source_edit.textCursor().hasSelection():
            text = self.editor_tab.source_edit.textCursor().selectedText()
        elif seg is not None:
            text = seg.source
        if not text.strip():
            QMessageBox.information(self, "QuickTrans", "Brak tekstu – otwórz projekt i wybierz segment.")
            return

        dialog = QuickTransDialog(
            self, text,
            self.project.source_lang if self.project else "en",
            self.project.target_lang if self.project else "pl",
            parent=self,
        )
        if dialog.exec() == QuickTransDialog.DialogCode.Accepted and dialog.chosen:
            self.tabs.setCurrentWidget(self.editor_tab)
            self.editor_tab.set_target_text(dialog.chosen)
            self.show_status("⚡ Wstawiono tłumaczenie z QuickTrans")

    def run_qa(self) -> None:
        self.tabs.setCurrentWidget(self.qa_tab)
        self.qa_tab.run_checks()

    def show_usage_report(self) -> None:
        """Zestawienie zużycia wszystkich silników MT."""
        from PyQt6.QtWidgets import (QDialog, QDialogButtonBox, QHeaderView,
                                     QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout)

        tracker = UsageTracker.instance()
        rows = tracker.report()

        dialog = QDialog(self)
        dialog.setWindowTitle("⚡ Zużycie silników tłumaczenia maszynowego")
        dialog.resize(880, 460)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(
            f"Dzień: <b>{tracker.day}</b> — liczniki dobowe zerują się o północy. "
            "Limity dotyczą darmowych planów."
        ))

        table = QTableWidget(len(rows), 7)
        table.setHorizontalHeaderLabels(
            ["Silnik", "Zapytań dziś", "Limit dobowy", "Na minutę", "Tokeny dziś",
             "Znaki dziś", "Błędy"]
        )
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        table.setEditTriggers(table.EditTrigger.NoEditTriggers)
        table.setAlternatingRowColors(True)
        labels = dict(__import__("supercat.core.mt", fromlist=["ENGINES"]).ENGINES)
        for r, row in enumerate(rows):
            rpd = row["rpd_limit"]
            rpm_txt = f"{row['rpm']}/{row['rpm_limit']}" if row["rpm_limit"] else str(row["rpm"])
            values = [
                labels.get(row["engine"], row["engine"]),
                str(row["requests_today"]),
                f"{rpd} ({row['percent']}%)" if rpd else "bez limitu",
                rpm_txt,
                f"{row['tokens_today']:,}".replace(",", " ") if row["tokens_today"] else "—",
                f"{row['chars_today']:,}".replace(",", " "),
                str(row["errors_today"]),
            ]
            for c, value in enumerate(values):
                item = QTableWidgetItem(value)
                if c and row["percent"] is not None and row["percent"] >= 80:
                    item.setForeground(QColor("#ef5350" if row["percent"] >= 95 else "#ffb74d"))
                table.setItem(r, c, item)
        layout.addWidget(table)

        if not rows:
            layout.addWidget(QLabel("Brak zarejestrowanego użycia w tym dniu."))

        reset_btn = QPushButton("🧹 Wyzeruj liczniki")
        reset_btn.clicked.connect(lambda: (tracker.reset_all(), dialog.accept(),
                                           self._update_usage_label()))
        layout.addWidget(reset_btn)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()

    def show_statistics(self) -> None:
        stats = project_statistics(self.editor_tab.segments, self.tm.size() if self.tm.is_initialized else 0)
        text = "\n".join(f"{k}: {v}" for k, v in stats.items())
        QMessageBox.information(self, "Statystyki projektu", text)

    def import_tmx(self) -> None:
        self.tabs.setCurrentWidget(self.tm_tab)
        self.tm_tab.import_tmx()

    def export_tmx(self) -> None:
        self.tabs.setCurrentWidget(self.tm_tab)
        self.tm_tab.export_tmx()

    # ------------------------------------------------------------- eksport
    def export_target_files(self) -> None:
        if not self._require_project():
            return
        segments = self.editor_tab.segments
        if not segments:
            QMessageBox.information(self, "Eksport", "Brak segmentów do wyeksportowania.")
            return
        self.editor_tab._store_current()
        target_folder = self.project.target_path
        os.makedirs(target_folder, exist_ok=True)

        by_file: dict[str, List[Segment]] = {}
        for seg in segments:
            by_file.setdefault(seg.file_name, []).append(seg)

        exported, errors = 0, []
        for file_name, file_segments in by_file.items():
            source_file = os.path.join(self.project.source_path, file_name)
            target_file = os.path.join(target_folder, file_name)
            try:
                lower = file_name.lower()
                if lower.endswith(".docx") and os.path.exists(source_file):
                    export_docx(source_file, target_file, file_segments)
                elif lower.endswith(".xlsx") and os.path.exists(source_file):
                    export_xlsx(source_file, target_file, file_segments)
                elif lower.endswith(".srt"):
                    export_srt(file_segments, target_file)
                elif lower.endswith((".po", ".pot")):
                    export_po(file_segments, target_file)
                elif lower.endswith((".xliff", ".xlf")):
                    export_xliff(file_segments, target_file, self.project.source_lang, self.project.target_lang)
                elif os.path.exists(source_file):
                    export_by_replacement(source_file, target_file, file_segments)
                else:
                    export_txt(file_segments, target_file)
                exported += 1
            except Exception as exc:
                errors.append(f"{file_name}: {exc}")

        self.save_all(silent=True)
        message = f"Wyeksportowano {exported} plików do:\n{target_folder}"
        if errors:
            message += "\n\nBłędy:\n" + "\n".join(errors)
        QMessageBox.information(self, "Eksport", message)
        self.show_status(f"📤 Wyeksportowano {exported} plików do target/")

    def export_as(self, fmt: str) -> None:
        if not self._require_project():
            return
        segments = self.editor_tab.segments
        if not segments:
            QMessageBox.information(self, "Eksport", "Brak segmentów.")
            return
        self.editor_tab._store_current()
        ext_map = {"xliff": "xlf", "po": "po", "srt": "srt", "html": "html", "txt": "txt"}
        ext = ext_map.get(fmt, "txt")
        default = os.path.join(self.project.export_path, f"{self.project.name}.{ext}")
        os.makedirs(self.project.export_path, exist_ok=True)
        path, _ = QFileDialog.getSaveFileName(self, f"Eksportuj {fmt.upper()}", default, f"*.{ext}")
        if not path:
            return
        try:
            if fmt == "xliff":
                export_xliff(segments, path, self.project.source_lang, self.project.target_lang)
            elif fmt == "po":
                export_po(segments, path)
            elif fmt == "srt":
                export_srt(segments, path)
            elif fmt == "html":
                export_html_bilingual(segments, path)
            else:
                export_txt(segments, path)
            QMessageBox.information(self, "Eksport", f"Zapisano:\n{path}")
        except Exception as exc:
            QMessageBox.critical(self, "Błąd eksportu", str(exc))

    # -------------------------------------------------------------- różne
    def selected_editor_text(self) -> str:
        """Tekst zaznaczony w polu źródłowym lub w tłumaczeniu."""
        editor = self.editor_tab
        for field in (editor.source_edit, editor.target_edit):
            text = field.textCursor().selectedText().strip()
            if text:
                return text
        return ""

    def undo_action(self) -> None:
        """Cofa ostatnią zmianę: najpierw tekst w edytorze, potem oznaczenia.

        Wcześniej „Cofnij” działało wyłącznie na polu tłumaczenia — zmiany
        statusów i pominięć nie dało się odwrócić.
        """
        editor = self.editor_tab.target_edit
        if editor.hasFocus() and editor.document().isUndoAvailable():
            editor.undo()
            return
        if not self.editor_tab.undo_last():
            if editor.document().isUndoAvailable():
                editor.undo()
            else:
                self.show_status("Nie ma czego cofnąć")

    def redo_action(self) -> None:
        editor = self.editor_tab.target_edit
        if editor.hasFocus() and editor.document().isRedoAvailable():
            editor.redo()
            return
        if not self.editor_tab.redo_last():
            if editor.document().isRedoAvailable():
                editor.redo()
            else:
                self.show_status("Nie ma czego ponowić")

    def open_search(self) -> None:
        """Ctrl+F – okno wyszukiwania (jak w OmegaT) albo zakładka.

        Wybór należy do użytkownika: *Ustawienia → Ogólne → „Ctrl+F otwiera
        osobne okno wyszukiwania”*. Domyślnie okno, bo tak działa OmegaT.
        """
        selected = self.selected_editor_text()
        if SettingsManager.instance().get_bool("search.window.enabled", True):
            self.open_search_window(selected)
            return
        self.tabs.setCurrentWidget(self.search_tab)
        if selected:
            self.search_tab.search_edit.setText(selected)
            self.search_tab.perform_search()
        self.search_tab.search_edit.setFocus()
        self.search_tab.search_edit.selectAll()

    def open_search_window(self, text: str = "") -> None:
        """Otwiera osobne, niemodalne okno wyszukiwania (można mieć kilka)."""
        from .search_window import open_search_window

        open_search_window(self, text)

    def find_in_project(self, scope: Optional[str] = None) -> None:
        """Szuka zaznaczonego wyrazu – w oknie albo w zakładce, wg ustawienia."""
        if SettingsManager.instance().get_bool("search.window.enabled", True):
            text = self.selected_editor_text()
            if not text:
                self.editor_tab.find_selected_word(scope)
                return
            from .search_window import open_search_window

            window = open_search_window(self, "")
            if scope:
                window.panel.scope.setCurrentText(scope)
            window.panel.search_edit.setText(text)
            window.panel.perform_search()
            return
        self.editor_tab.find_selected_word(scope)

    def _active_search_panel(self):
        """Panel, na którym mają działać F3 / Shift+F3.

        Priorytet ma aktywne okno wyszukiwania – gdy użytkownik ma otwarte
        kilka okien, klawisz działa na tym, z którego korzysta.
        """
        from .search_window import OPEN_WINDOWS

        for window in reversed(OPEN_WINDOWS):
            if window.isActiveWindow():
                return window.panel
        if OPEN_WINDOWS and self.tabs.currentWidget() is not self.search_tab:
            return OPEN_WINDOWS[-1].panel
        return self.search_tab

    def exclusion_set(self):
        """Reguły wykluczania segmentów dla bieżącego projektu."""
        from ..core.exclusions import ExclusionSet, default_rules

        if self._exclusions is None:
            data = getattr(self.project, "exclusions", None) if self.project else None
            self._exclusions = (ExclusionSet.from_dict(data) if data
                                else ExclusionSet(default_rules()))
        return self._exclusions

    def save_exclusions(self) -> None:
        """Zapisuje reguły wykluczania w pliku projektu."""
        if not self.project or self._exclusions is None:
            return
        self.project.exclusions = self._exclusions.to_dict()
        self.project_manager.save_project()

    def apply_exclusions(self, silent: bool = False) -> int:
        """Stosuje reguły do wczytanych segmentów. Zwraca liczbę wykluczonych."""
        segments = self.editor_tab.segments
        if not segments:
            return 0
        excluded, restored = self.exclusion_set().apply(segments)
        self.editor_tab.refresh_grid()
        self.editor_tab.update_progress()
        self.qa_tab.refresh_stats()
        if not silent:
            self.show_status(
                f"Zastosowano reguły: oznaczono {excluded}, przywrócono {restored}")
        return excluded

    def go_to_editor_segment(self, index: int) -> None:
        """Przechodzi do segmentu – także takiego, który jest ukryty filtrem.

        Wyniki wyszukiwania obejmują CAŁY projekt, więc trafienie może leżeć
        w pliku innym niż aktualnie przeglądany. Najpierw odsłaniamy segment
        (zdejmujemy filtr pliku / tekstu / statusu), dopiero potem go wczytujemy –
        inaczej siatka podświetlała inny wiersz niż ten w edytorze.
        """
        self.tabs.setCurrentWidget(self.editor_tab)
        self.editor_tab.reveal_segment(index)
        self.editor_tab.load_segment(index)

    def show_about(self) -> None:
        AboutDialog(self).exec()

    def show_status(self, message: str) -> None:
        self.statusBar().showMessage(message, 6000)
        self.update_status()

    def update_status(self) -> None:
        if not self.project:
            self.status_label.setText("Brak otwartego projektu  •  Plik → Nowy projekt (Ctrl+N)")
            return
        segments = self.editor_tab.segments
        done = sum(1 for s in segments if s.is_translated)
        total = len(segments)
        percent = int(done * 100 / total) if total else 0
        self.status_label.setText(
            f"📦 {self.project.name}  [{self.project.source_lang} → {self.project.target_lang}]  •  "
            f"segmenty: {done}/{total} ({percent}%)  •  TM: {self.tm.size()} wpisów  •  "
            f"glosariusz: {self.glossary.size}  •  MT: {self.mt.engine_label}"
        )
        self._update_usage_label()

    def _update_usage_label(self) -> None:
        """Pokazuje zużycie bieżącego silnika MT (limity darmowych planów)."""
        tracker = UsageTracker.instance()
        engine = self.mt.engine
        summary = tracker.summary(engine)
        code = self.mt.engine_label.split(" ")[0]
        text = f"⚡ {code}: {summary}"
        percent = tracker.percent_used(engine)
        if percent is not None:
            text += f"  ({percent}%)"
            if percent >= 95:
                color = "#ef5350"
            elif percent >= 80:
                color = "#ffb74d"
            else:
                color = ""
            self.usage_label.setStyleSheet(f"color: {color};" if color else "")
        else:
            self.usage_label.setStyleSheet("")
        self.usage_label.setText(text)
        self.usage_label.setToolTip(
            "Zużycie bieżącego silnika tłumaczenia maszynowego.\n"
            "Kliknij, aby zobaczyć pełne zestawienie."
        )

    def _refresh_recent_menu(self) -> None:
        self.recent_menu.clear()
        recent = RecentProjects.get()
        if not recent:
            action = self.recent_menu.addAction("(brak)")
            action.setEnabled(False)
            return
        for path in recent:
            name = os.path.basename(path).replace(PROJECT_EXT, "")
            action = self.recent_menu.addAction(f"{name}  –  {os.path.dirname(path)}")
            action.triggered.connect(lambda checked=False, p=path: self.open_project_path(p))
        self.recent_menu.addSeparator()
        clear = self.recent_menu.addAction("🧹 Wyczyść listę")
        clear.triggered.connect(lambda: (RecentProjects.clear(), self._refresh_recent_menu()))

    def _require_project(self) -> bool:
        if not self.project:
            QMessageBox.information(self, "Projekt", "Najpierw utwórz lub otwórz projekt (Ctrl+N / Ctrl+O).")
            return False
        return True

    # ------------------------------------------------- przeciąganie plików
    def _dropped_paths(self, event) -> List[str]:
        paths = []
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path and (os.path.isdir(path) or path.lower().endswith(SUPPORTED_EXTENSIONS)):
                paths.append(path)
        return paths

    def dragEnterEvent(self, event) -> None:  # noqa: N802 (Qt API)
        if event.mimeData().hasUrls() and self._dropped_paths(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        paths = self._dropped_paths(event)
        if not paths:
            event.ignore()
            return
        event.acceptProposedAction()
        if not self.project:
            QMessageBox.information(
                self, "Import plików",
                "Najpierw utwórz lub otwórz projekt (Ctrl+N / Ctrl+O).",
            )
            return
        self.tabs.setCurrentWidget(self.editor_tab)
        self.import_file_paths(paths)

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        try:
            self.editor_tab._last_seg_timer.stop()
            self.editor_tab._save_last_segment()
        except Exception:
            pass
        if self.project:
            answer = QMessageBox.question(
                self, "Zakończ",
                "Zapisać projekt i tłumaczenia przed zamknięciem?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
            )
            if answer == QMessageBox.StandardButton.Cancel:
                event.ignore()
                return
            if answer == QMessageBox.StandardButton.Yes:
                self.save_all(silent=True)
        # zamknij otwarte okna wyszukiwania, żeby nie zostały „wiszące”
        from .search_window import close_all_search_windows

        close_all_search_windows()
        # zatrzymaj serwer LibreTranslate, jeśli to my go uruchomiliśmy
        server = getattr(self, "_lt_server", None)
        if server is not None:
            try:
                server.stop()
            except Exception:
                pass

        # zatrzymaj lokalny serwer LanguageTool (proces Javy w tle)
        try:
            from ..core.langcheck import LocalLanguageTool

            LocalLanguageTool.shutdown()
        except Exception:
            pass
        for worker in list(self._workers):
            try:
                worker.cancel()
                worker.wait(3000)
            except Exception:
                pass
        self._workers.clear()
        # zatrzymaj też kontrolę języka (LanguageTool potrafi czekać na sieć)
        lang = getattr(self.editor_tab, "_lang_worker", None)
        if lang is not None:
            try:
                lang.cancel()
                lang.wait(3000)
            except Exception:
                pass
        lookup = getattr(self.editor_tab, "_lookup_worker", None)
        if lookup is not None:
            try:
                lookup.cancel()
                lookup.wait(3000)
            except Exception:
                pass
        self.tm.close()
        event.accept()


class TMTabWrapper(QWidget):
    """Cienka otoczka na TMTab, aby uniknąć cyklicznych importów."""

    def __init__(self, app) -> None:
        super().__init__()
        from PyQt6.QtWidgets import QVBoxLayout

        from .tm_tab import TMTab

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.inner = TMTab(app)
        layout.addWidget(self.inner)

    def refresh(self) -> None:
        self.inner.refresh()

    def import_tmx(self) -> None:
        self.inner.import_tmx()

    def export_tmx(self) -> None:
        self.inner.export_tmx()

    def __getattr__(self, name: str):
        """Przekazuje nieznane atrybuty do właściwej zakładki.

        Bez tego każda nowa metoda czy widżet TMTab (np. generator TM)
        wymagałaby ręcznego dopisania kolejnej metody-przekaźnika.
        """
        # Blokujemy tylko atrybuty specjalne (__dunder__) i sam „inner”,
        # żeby nie wpaść w nieskończoną rekurencję przy odtwarzaniu obiektu.
        # Pola jednopodkreślnikowe (np. _gen_pairs) muszą być dostępne,
        # bo testy i kod pomocniczy z nich korzystają.
        if name.startswith("__") or name == "inner" or "inner" not in self.__dict__:
            raise AttributeError(name)
        return getattr(self.__dict__["inner"], name)
