"""Zakładka Edytor – siatka segmentów + edytory + panele pomocnicze.

Układ inspirowany Supervertaler Workbench:
  [pliki] | [siatka segmentów + edytor źródło/cel] | [dopasowania TM / terminy / konkordancja]
"""
from __future__ import annotations

import os
import re
import time as _time
from typing import List, Optional, Sequence

from PyQt6.QtCore import QEvent, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (QAction, QBrush, QColor, QFont, QKeySequence, QPalette, QShortcut,
                         QTextCharFormat, QTextCursor)
from PyQt6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QFileDialog, QFrame, QHBoxLayout,
    QHeaderView, QLabel,
    QApplication, QStyle, QStyledItemDelegate, QStyleOptionViewItem,
    QInputDialog, QLineEdit, QListWidget, QListWidgetItem, QMenu, QMessageBox, QPlainTextEdit,
    QProgressBar,
    QPushButton, QSplitter, QTableWidget, QTableWidgetItem, QTabWidget, QTextEdit, QToolButton, QVBoxLayout,
    QWidget,
)

from ..core.fileparser import Segment
from ..core.tm import SentenceMatch, TranslationMatch
from ..core.qa import segment_statistics, word_count
from ..core.settings import SettingsManager
from ..core.textutil import DEFAULT_MARKER_STYLE
from ..core.tags import adapt_translation
from ..core.textutil import (copy_edge_whitespace, describe_edges, display_text, find_matches,
                             markers_for_style, split_edges)
from .theme import Colors, setup_splitter
from ..core.langcheck import MIN_DICTIONARY_FOR_SPELLCHECK as MIN_DICT_FOR_SPELL
from ..core.langcheck import LanguageToolClient, apply_first_suggestions
from ..core.langcheck import summarize as summarize_lang
from .workers import LangCheckWorker, SuggestionWorker, TMLookupWorker

def format_duration(ms: float, unit: str = "auto") -> str:
    """Formatuje czas w wybranej jednostce (ms / s / min / auto)."""
    if unit == "ms":
        return f"{ms:.0f} ms"
    if unit == "s":
        return f"{ms / 1000:.2f} s"
    if unit == "min":
        return f"{ms / 60000:.2f} min"
    # auto – dobierz czytelną jednostkę
    if ms < 1000:
        return f"{ms:.0f} ms"
    if ms < 60000:
        return f"{ms / 1000:.2f} s"
    return f"{ms / 60000:.2f} min"


class DropFileList(QListWidget):
    """Lista plików projektu: import przeciągnięciem i zmiana kolejności.

    Obsługuje **dwa różne** przeciągnięcia:

    * z pulpitu — pliki i katalogi trafiają do projektu (`files_dropped`),
    * wewnątrz listy — zmiana kolejności plików (`order_changed`).

    Rozróżniamy je po tym, czy zdarzenie niesie adresy URL (pulpit) czy
    pochodzi z tego samego widżetu. Pozycja „Wszystkie pliki” jest
    nieruchoma — nie da się jej przeciągnąć ani wstawić nad nią pliku.
    """

    files_dropped = pyqtSignal(list)
    order_changed = pyqtSignal(list)      # nowa kolejność nazw plików

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragEnabled(True)
        self.setDropIndicatorShown(True)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self._normal_style = ""

    # --- rozróżnianie źródła przeciągnięcia ---------------------------
    def _is_internal(self, event) -> bool:
        """Czy przeciągamy pozycje tej samej listy (a nie pliki z pulpitu)."""
        return event.source() is self and not event.mimeData().hasUrls()

    def _movable_rows(self) -> List[int]:
        """Wiersze, które wolno przesuwać (bez „Wszystkie pliki”)."""
        return [row for row in range(self.count())
                if self.item(row).data(Qt.ItemDataRole.UserRole)]

    def startDrag(self, actions) -> None:  # noqa: N802 (Qt API)
        # „Wszystkie pliki” to filtr widoku, nie plik – nie ma czego przesuwać.
        if not any(item.data(Qt.ItemDataRole.UserRole)
                   for item in self.selectedItems()):
            return
        super().startDrag(actions)

    def _drop_row(self, event) -> int:
        """Wiersz, przed którym wstawiamy przeciągane pliki."""
        position = event.position().toPoint()
        item = self.itemAt(position)
        if item is None:
            return self.count()
        row = self.row(item)
        rect = self.visualItemRect(item)
        if position.y() > rect.center().y():
            row += 1
        # Nigdy nad pozycją „Wszystkie pliki”.
        first = self._movable_rows()
        return max(row, first[0] if first else 0)

    def _apply_internal_move(self, event) -> None:
        """Przenosi zaznaczone pliki w miejsce upuszczenia."""
        target = self._drop_row(event)
        moving = sorted(self.row(item) for item in self.selectedItems()
                        if item.data(Qt.ItemDataRole.UserRole))
        if not moving:
            return
        # Ile przesuwanych pozycji jest nad miejscem docelowym – o tyle
        # przesunie się cel po ich wyjęciu z listy.
        target -= sum(1 for row in moving if row < target)
        taken = [self.takeItem(row) for row in reversed(moving)]
        taken.reverse()
        for offset, item in enumerate(taken):
            self.insertItem(target + offset, item)
        self.clearSelection()
        for offset in range(len(taken)):
            self.item(target + offset).setSelected(True)
        self.order_changed.emit(
            [self.item(row).data(Qt.ItemDataRole.UserRole)
             for row in self._movable_rows()])

    @staticmethod
    def _usable_paths(event) -> List[str]:
        from ..core.fileparser import SUPPORTED_EXTENSIONS

        paths = []
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if not path:
                continue
            if os.path.isdir(path) or path.lower().endswith(SUPPORTED_EXTENSIONS):
                paths.append(path)
        return paths

    def _highlight(self, active: bool) -> None:
        self.setStyleSheet(
            "QListWidget { border: 2px dashed #2f7fd1; background: rgba(47,127,209,0.08); }"
            if active else self._normal_style
        )

    def dragEnterEvent(self, event) -> None:  # noqa: N802 (Qt API)
        if self._is_internal(event):
            event.acceptProposedAction()
            return
        if event.mimeData().hasUrls() and self._usable_paths(event):
            event.acceptProposedAction()
            self._highlight(True)
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if self._is_internal(event):
            # Wskaźnik wstawiania rysuje Qt – pokazuje, gdzie plik wyląduje.
            super().dragMoveEvent(event)
            event.acceptProposedAction()
            return
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self._highlight(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802
        self._highlight(False)
        if self._is_internal(event):
            self._apply_internal_move(event)
            event.acceptProposedAction()
            return
        paths = self._usable_paths(event)
        if paths:
            event.acceptProposedAction()
            self.files_dropped.emit(paths)
        else:
            event.ignore()


class SegmentGrid(QTableWidget):
    """Siatka segmentów z poprawioną obsługą Ctrl+↑/↓.

    Qt traktuje Ctrl+↑/↓ w tabeli jako „przesuń kursor bez zmiany zaznaczenia”,
    a przy `ExtendedSelection` kolejne naciśnięcia **dokładają wiersze** do
    zaznaczenia. Użytkownik oczekuje zwykłego przejścia do sąsiedniego segmentu,
    więc obsługujemy te kombinacje sami. `Shift+↑/↓` zostaje bez zmian —
    zaznaczanie zakresu nadal działa.
    """

    move_requested = pyqtSignal(int)      # +1 = następny, -1 = poprzedni

    #: Klawisze, które w tabeli rozszerzałyby zaznaczenie zamiast przechodzić.
    _NAV_KEYS = (Qt.Key.Key_Down, Qt.Key.Key_Up,
                 Qt.Key.Key_PageDown, Qt.Key.Key_PageUp,
                 Qt.Key.Key_Home, Qt.Key.Key_End)

    def event(self, event):
        """Przechwytuje Ctrl+↑/↓ **zanim** Qt odda je skrótowi menu.

        Kombinacja jest zarejestrowana jako skrót okna („Następny segment”),
        więc trafiała jednocześnie do menu (zmiana segmentu) i do tabeli
        (rozszerzenie zaznaczenia) — po kilku naciśnięciach zaznaczonych było
        pół projektu. `ShortcutOverride` pozwala przejąć klawisz na wyłączność.
        """
        if event.type() == QEvent.Type.ShortcutOverride:
            modifiers = event.modifiers()
            if (event.key() in self._NAV_KEYS
                    and modifiers & Qt.KeyboardModifier.ControlModifier
                    and not modifiers & Qt.KeyboardModifier.ShiftModifier):
                event.accept()          # obsłużymy to w keyPressEvent
                return True
        return super().event(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802 (Qt API)
        modifiers = event.modifiers()
        if (event.key() in self._NAV_KEYS
                and modifiers & Qt.KeyboardModifier.ControlModifier
                and not modifiers & Qt.KeyboardModifier.ShiftModifier):
            if event.key() in (Qt.Key.Key_Down, Qt.Key.Key_PageDown):
                self.move_requested.emit(1)
            elif event.key() in (Qt.Key.Key_Up, Qt.Key.Key_PageUp):
                self.move_requested.emit(-1)
            elif event.key() == Qt.Key.Key_Home:
                self.move_requested.emit(-10 ** 9)
            else:
                self.move_requested.emit(10 ** 9)
            event.accept()
            return
        super().keyPressEvent(event)


class SelectionTextDelegate(QStyledItemDelegate):
    """Maluje zaznaczony wiersz czytelnie: jednolite tło i biały tekst.

    Wiersze siatki mają własne kolory tła (status segmentu). Qt maluje wtedy
    to tło zamiast koloru zaznaczenia, a tekst zostaje ciemny – na niebieskim
    tle robi się nieczytelny. Dlatego rysujemy element samodzielnie:
    `initStyleOption` uruchamiamy raz, podmieniamy tło i kolory palety,
    a następnie rysujemy przez styl (bez `super().paint()`, które
    zresetowałoby paletę).
    """

    def __init__(self, colors, parent=None):
        super().__init__(parent)
        self.colors = colors

    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)

        hovered = bool(opt.state & QStyle.StateFlag.State_MouseOver)
        selected = bool(opt.state & QStyle.StateFlag.State_Selected)

        if hovered and not selected:
            # Najechanie myszą: delikatne tło, tekst pozostaje ciemny/jasny wg motywu.
            # Bez tego Qt maluje własne niebieskie tło pod ciemnym tekstem.
            hover_bg = QColor(self.colors.hover_bg)
            opt.backgroundBrush = QBrush(hover_bg)
            painter.save()
            painter.fillRect(opt.rect, hover_bg)
            painter.restore()
            opt.state &= ~QStyle.StateFlag.State_MouseOver
            for group in (QPalette.ColorGroup.Normal, QPalette.ColorGroup.Inactive,
                          QPalette.ColorGroup.Active):
                opt.palette.setColor(group, QPalette.ColorRole.Text, QColor(self.colors.row_fg))

        if selected:
            sel_bg = QColor(self.colors.selection_hover_bg if hovered else self.colors.selection_bg)
            sel_fg = QColor(self.colors.selection_fg)
            opt.backgroundBrush = QBrush(sel_bg)
            for group in (QPalette.ColorGroup.Normal, QPalette.ColorGroup.Inactive,
                          QPalette.ColorGroup.Active):
                opt.palette.setColor(group, QPalette.ColorRole.Highlight, sel_bg)
                opt.palette.setColor(group, QPalette.ColorRole.HighlightedText, sel_fg)
                opt.palette.setColor(group, QPalette.ColorRole.Text, sel_fg)
            # tekst pobrany z modelu ma własny kolor – usuwamy go, by nie wygrał
            opt.state |= QStyle.StateFlag.State_Active

        widget = opt.widget
        style = widget.style() if widget is not None else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, widget)

        # Wcięcie w siatce oznacza sam znak „␣” w tekście komórki.
        # Kolorowy blok z ramką był tu zbyt natarczywy (zwłaszcza na zaznaczonym
        # wierszu), dlatego domyślnie go NIE malujemy – od pokazywania wcięcia
        # są pola edytora, gdzie faktycznie poprawia się tekst.
        if SettingsManager.instance().get_bool("ui.whitespace.grid.blocks", False):
            marks = index.data(WHITESPACE_ROLE)
            if marks:
                self._paint_whitespace(painter, opt, index, marks)

    def _paint_whitespace(self, painter, opt, index, marks) -> None:
        """Maluje tło pod wiodącymi/końcowymi znakami białymi w komórce."""
        lead, trail = marks
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        if not text:
            return
        metrics = opt.fontMetrics
        rect = opt.rect.adjusted(4, 0, -4, 0)   # margines komórki jak w Qt
        # Na zaznaczonym (niebieskim) wierszu fiolet ginie – tam używamy
        # jasnego, półprzezroczystego bloku, który widać na każdym tle.
        selected = bool(opt.state & QStyle.StateFlag.State_Selected)
        color = QColor("#ffffff") if selected else QColor(self.colors.whitespace_bg)
        color.setAlpha(110 if selected else 210)

        painter.save()
        painter.setClipRect(opt.rect)

        def block(x: int, width: int) -> None:
            if width <= 0:
                return
            # bez ramki – samo tło, żeby nie robić „obwódek” w tabeli
            painter.fillRect(x, rect.y() + 2, width, max(1, rect.height() - 4), color)

        if lead:
            block(rect.x(), metrics.horizontalAdvance(text[:lead]))
        if trail:
            full = metrics.horizontalAdvance(text)
            before = metrics.horizontalAdvance(text[:len(text) - trail])
            if rect.x() + full <= rect.right():
                block(rect.x() + before, full - before)
        painter.restore()


#: Rola danych: (liczba znaków wcięcia z przodu, liczba z tyłu) – dla delegata.
WHITESPACE_ROLE = int(Qt.ItemDataRole.UserRole) + 17

#: Statusy oznaczające segment domknięty — liczą się jako wykonana praca,
#: nawet gdy pole tłumaczenia jest puste (np. tekst celowo bez zmian).
DONE_STATUSES = ("translated", "approved")


def _is_done(seg) -> bool:
    """Czy segment jest gotowy — ma tłumaczenie albo domykający status.

    Samo oznaczenie „przetłumaczony” lub „zatwierdzony” wystarczy: użytkownik
    świadomie uznał segment za skończony. Wcześniej licznik patrzył wyłącznie
    na treść tłumaczenia, więc zmiana oznaczenia nic w nim nie zmieniała.
    """
    if getattr(seg, "status", "") in DONE_STATUSES:
        return True
    return bool((getattr(seg, "target", "") or "").strip())


STATUS_LABELS = {
    "new": "○ nowy",
    "draft": "✎ roboczy",
    "translated": "✓ przetłumaczony",
    "approved": "★ zatwierdzony",
    "ignored": "🚫 pominięty",
}


def marker_settings() -> dict:
    """Bieżące ustawienia znaków specjalnych (␣ → ⏎) z Ustawień."""
    settings = SettingsManager.instance()
    space, tab, newline = markers_for_style(
        settings.get("ui.markers.style", DEFAULT_MARKER_STYLE))
    return {
        "show_spaces": settings.get_bool("ui.markers.spaces", True),
        "show_newlines": settings.get_bool("ui.markers.newlines", True),
        "space_marker": space,
        "tab_marker": tab,
        "newline_marker": newline,
    }


def _set_whitespace_hint(item: QTableWidgetItem, text: str, cfg: Optional[dict] = None) -> None:
    """Zapisuje w komórce, ile znaków białych jest na brzegach – dla delegata."""
    cfg = cfg or marker_settings()
    lead, _core, trail = split_edges(text)
    if lead or trail:
        item.setData(WHITESPACE_ROLE, (len(lead), len(trail)))
        if cfg["show_spaces"]:
            item.setToolTip(
                f"{cfg['space_marker']} = spacja na brzegu wiersza (tak jest w pliku źródłowym)\n"
                f"{cfg['tab_marker']} = tabulator   •   {cfg['newline_marker']} = koniec wiersza\n"
                "Znaki można zmienić lub wyłączyć w Ustawieniach → Ogólne."
            )
        else:
            item.setToolTip(
                "Segment ma spacje na brzegu wiersza (tak jest w pliku źródłowym).\n"
                "Pokazywanie znaku ␣ włączysz w Ustawieniach → Ogólne."
            )
    else:
        item.setData(WHITESPACE_ROLE, None)


class EditorTab(QWidget):
    """Główna zakładka pracy tłumacza."""

    segment_changed = pyqtSignal(int)
    status_message = pyqtSignal(str)

    def __init__(self, app) -> None:
        super().__init__()
        self.app = app  # MainWindow
        self.segments: List[Segment] = []
        self.current_index: int = -1
        self._loading = False
        self._file_filter: Optional[str] = None
        self.colors = Colors(SettingsManager.instance().get_bool("theme.dark", True))
        self.alt_translations: dict[str, List[str]] = {}
        self._lookup_worker: Optional[TMLookupWorker] = None
        self._last_timing: dict = {}
        self._segment_changed_at: float = 0.0
        self._pending_lookup_index: int = -1
        #: Co już trafiło do „pamięci w locie” – zapobiega ponownemu przetwarzaniu
        self._volatile_sent: dict[int, tuple[str, str]] = {}
        #: Podświetlenia w polu źródłowym: terminy glosariusza + trafienia wyszukiwania
        self._term_selections: list = []
        self._search_source_selections: list = []
        self._ws_source_selections: list = []
        self._ws_target_selections: list = []
        self._search_target_selections: list = []
        self._search_needle: str = ""
        #: Kontrola języka tłumaczenia (panel „🔤 Język”)
        self._lang_worker = None
        self._lang_issues: list = []
        self._lang_selections: list = []
        #: Historia zmian oznaczeń (Ctrl+Z / Ctrl+Y)
        self._undo_stack: list = []
        self._redo_stack: list = []
        self._suggest_worker = None
        self._lang_client = LanguageToolClient(
            url=SettingsManager.instance().get("lang.check.url", "") or None)

        # Odświeżanie podświetlenia spacji jest odroczone – przy szybkim pisaniu
        # przeliczanie zaznaczeń przy każdym znaku niepotrzebnie obciążało pole.
        # Timer musi powstać PRZED _build_ui, bo tam podpinany jest textChanged.
        self._ws_timer = QTimer(self)
        self._ws_timer.setSingleShot(True)
        self._ws_timer.timeout.connect(self.highlight_whitespace)

        # Kontrola języka też jest odroczona – LanguageTool chodzi po sieci,
        # więc sprawdzamy dopiero, gdy użytkownik przestanie pisać.
        self._lang_timer = QTimer(self)
        self._lang_timer.setSingleShot(True)
        self._lang_timer.timeout.connect(self.check_language)

        self._build_ui()
        self._build_shortcuts()

        self._tm_timer = QTimer(self)
        self._tm_timer.setSingleShot(True)
        self._tm_timer.timeout.connect(self._refresh_helpers)
        # Odstęp przed startem wyszukiwania. Jest ADAPTACYJNY: gdy poprzednie
        # szukanie było szybkie, ruszamy niemal natychmiast; gdy trwało długo
        # (bardzo duża pamięć), czekamy dłużej, by nie liczyć segmentów,
        # które użytkownik tylko „mija” strzałką.
        self._tm_debounce_ms = 60
        self._last_lookup_ms = 0.0

        self._autosave = QTimer(self)
        self._autosave.timeout.connect(self._auto_save)
        interval = max(10, SettingsManager.instance().get_int("auto.save.interval", 30))
        if SettingsManager.instance().get_bool("auto.save.enabled", True):
            self._autosave.start(interval * 1000)

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # --- lewy panel: pliki -----------------------------------------
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(2, 2, 2, 2)
        left_layout.addWidget(QLabel("<b>📁 Pliki projektu</b>"))
        self.files_list = DropFileList()
        self.files_list.setToolTip(
            "Przeciągnij tutaj pliki (np. .txt), aby dodać je do projektu.\n"
            "Ctrl+klik lub Shift+klik zaznacza wiele plików naraz.\n"
            "Przeciągnij plik NA LIŚCIE, aby zmienić jego kolejność."
        )
        # Wiele plików naraz – żeby dało się usunąć albo przestawić kilka
        # jednym ruchem, zamiast klikać każdy z osobna.
        self.files_list.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection)
        self.files_list.itemClicked.connect(self._on_file_selected)
        self.files_list.files_dropped.connect(self._on_files_dropped)
        self.files_list.order_changed.connect(self._on_files_reordered)
        self.files_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.files_list.customContextMenuRequested.connect(self._files_context_menu)
        left_layout.addWidget(self.files_list)

        drop_hint = QLabel("⬇ Przeciągnij pliki tutaj")
        drop_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        drop_hint.setWordWrap(True)
        drop_hint.setToolTip(
            "Przeciągnij pliki (.txt, .docx, .xlsx, .po, .srt…) lub cały folder,\n"
            "aby dodać je do projektu."
        )
        drop_hint.setStyleSheet("color: gray; font-size: 11px; padding: 2px;")
        left_layout.addWidget(drop_hint)

        # Kolejność plików – wpływa na numerację segmentów i eksport.
        order_row = QHBoxLayout()
        order_row.setContentsMargins(0, 0, 0, 0)
        self.file_up_btn = QToolButton()
        self.file_up_btn.setText("▲")
        self.file_up_btn.setToolTip(
            "Przesuń zaznaczone pliki w górę\n"
            "(kolejność zmienisz też, przeciągając pliki na liście)")
        self.file_up_btn.clicked.connect(lambda: self.move_files(-1))
        self.file_down_btn = QToolButton()
        self.file_down_btn.setText("▼")
        self.file_down_btn.setToolTip("Przesuń zaznaczone pliki w dół")
        self.file_down_btn.clicked.connect(lambda: self.move_files(1))
        self.file_sort_btn = QToolButton()
        self.file_sort_btn.setText("🔤")
        self.file_sort_btn.setToolTip("Przywróć kolejność alfabetyczną")
        self.file_sort_btn.clicked.connect(self.sort_files_alphabetically)
        self.file_remove_btn = QToolButton()
        self.file_remove_btn.setText("🗑️")
        self.file_remove_btn.setToolTip("Usuń zaznaczone pliki z projektu")
        self.file_remove_btn.clicked.connect(self.remove_selected_files)
        for button in (self.file_up_btn, self.file_down_btn,
                       self.file_sort_btn, self.file_remove_btn):
            order_row.addWidget(button)
        order_row.addStretch(1)
        self.files_selection_label = QLabel("")
        self.files_selection_label.setStyleSheet("color: gray; font-size: 11px;")
        order_row.addWidget(self.files_selection_label)
        left_layout.addLayout(order_row)
        self.files_list.itemSelectionChanged.connect(self._on_files_selection_changed)

        file_btns = QHBoxLayout()
        add_btn = QPushButton("➕ Importuj")
        add_btn.setToolTip("Importuj pliki do projektu (Ctrl+I)")
        add_btn.clicked.connect(lambda: self.app.import_files())
        all_btn = QPushButton("Wszystkie")
        all_btn.clicked.connect(self._show_all_files)
        file_btns.addWidget(add_btn)
        file_btns.addWidget(all_btn)
        left_layout.addLayout(file_btns)

        self.progress = QProgressBar()
        self.progress.setFormat("%p% przetłumaczone")
        left_layout.addWidget(self.progress)

        # --- środek: siatka + edytory -----------------------------------
        center = QSplitter(Qt.Orientation.Vertical)

        grid_box = QWidget()
        grid_layout = QVBoxLayout(grid_box)
        grid_layout.setContentsMargins(2, 2, 2, 2)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("🔎 Filtr:"))
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("filtruj segmenty (źródło lub tłumaczenie)…")
        self.filter_edit.textChanged.connect(self.refresh_grid)
        filter_row.addWidget(self.filter_edit, 1)
        self.status_filter = QComboBox()
        self.status_filter.addItems(["Wszystkie", "Nieprzetłumaczone", "Przetłumaczone", "Zatwierdzone", "Pominięte"])
        self.status_filter.currentIndexChanged.connect(self.refresh_grid)
        filter_row.addWidget(self.status_filter)
        grid_layout.addLayout(filter_row)

        self.grid = SegmentGrid(0, 4)
        self.grid.setHorizontalHeaderLabels(["#", "Tekst źródłowy", "Tłumaczenie", "Status"])
        self.grid.verticalHeader().setVisible(False)
        self.grid.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        # Wiele wierszy naraz – pozwala grupowo pomijać/przywracać segmenty
        # (Ctrl+klik, Shift+klik, Ctrl+A).
        self.grid.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.grid.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.grid.setAlternatingRowColors(True)
        self.grid.setWordWrap(False)
        header = self.grid.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.grid.setColumnWidth(0, 55)
        self.grid.setColumnWidth(3, 150)
        self.grid.itemSelectionChanged.connect(self._on_grid_selection)
        # Ctrl+↑/↓ w tabeli domyślnie „rozciąga” zaznaczenie zamiast po prostu
        # przejść do sąsiedniego wiersza — obsługuje to SegmentGrid.
        self.grid.move_requested.connect(self._on_grid_move)
        self.grid.setItemDelegate(SelectionTextDelegate(self.colors, self.grid))
        self.grid.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.grid.customContextMenuRequested.connect(self._grid_context_menu)
        grid_layout.addWidget(self.grid)

        editors = QWidget()
        ed_layout = QVBoxLayout(editors)
        ed_layout.setContentsMargins(2, 2, 2, 2)

        seg_row = QHBoxLayout()
        self.segment_label = QLabel("Brak segmentów – otwórz projekt i zaimportuj pliki")
        self.segment_label.setStyleSheet("font-weight: bold;")
        seg_row.addWidget(self.segment_label)
        seg_row.addStretch(1)
        # Pomiar czasu wyszukiwania – widoczny, żeby łatwo zgłosić spowolnienie
        self.timing_label = QLabel("")
        self.timing_label.setStyleSheet("color: gray; font-size: 11px;")
        self.timing_label.setToolTip(
            "Czas ostatniego wyszukiwania w pamięci TM.\n"
            "TM = dopasowania rozmyte, ZD = dopasowanie zdań, ⏱ = od zmiany segmentu.\n"
            "Kliknij, aby skopiować pomiar do schowka."
        )
        self.timing_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.timing_label.mousePressEvent = lambda _e: self.copy_timing()
        self._timing_plain = ""
        seg_row.addWidget(self.timing_label)
        ed_layout.addLayout(seg_row)

        self.source_edit = QPlainTextEdit()
        self.source_edit.setReadOnly(True)
        self.source_edit.setPlaceholderText("Tekst źródłowy")
        ed_layout.addWidget(self.source_edit)

        # --- szybki wybór silnika MT tuż nad polem tłumaczenia -----------
        # Zmiana silnika bez wchodzenia w Ustawienia: gdy Google odmówi albo
        # wynik brzmi źle, wystarczy wybrać inny z listy i kliknąć „Tłumacz”.
        mt_bar = QHBoxLayout()
        mt_bar.setContentsMargins(0, 0, 0, 0)
        mt_bar.addWidget(QLabel("🤖 Silnik MT:"))
        self.engine_picker = QComboBox()
        self.engine_picker.setToolTip(
            "Silnik używany przez „🤖 Tłumacz” (Ctrl+M).\n"
            "Wybór zapisuje się od razu — jest wspólny z Ustawieniami."
        )
        self.engine_picker.setMinimumWidth(260)
        self.engine_picker.currentIndexChanged.connect(self._on_engine_picked)
        mt_bar.addWidget(self.engine_picker)

        self.engine_free_only = QCheckBox("tylko bez klucza")
        self.engine_free_only.setToolTip(
            "Skraca listę do silników, które działają bez klucza API.")
        self.engine_free_only.setChecked(
            SettingsManager.instance().get_bool("editor.engine.free_only", False))
        self.engine_free_only.stateChanged.connect(self._on_engine_filter_changed)
        mt_bar.addWidget(self.engine_free_only)

        translate_btn = QPushButton("🤖 Tłumacz")
        translate_btn.setToolTip("Ctrl+M – tłumaczy segment wybranym silnikiem")
        translate_btn.clicked.connect(self.machine_translate_current)
        mt_bar.addWidget(translate_btn)

        compare_btn = QPushButton("⚡ Porównaj")
        compare_btn.setToolTip("Ctrl+Alt+Q – QuickTrans: kilka silników naraz")
        compare_btn.clicked.connect(lambda: self.app.open_quicktrans())
        mt_bar.addWidget(compare_btn)
        mt_bar.addStretch(1)
        ed_layout.addLayout(mt_bar)
        self.reload_engine_picker()
        # Silnik można przestawić także z Ustawień lub panelu AI – wtedy
        # lista musi to pokazać, inaczej wprowadza w błąd.
        self.app.mt.add_engine_listener(lambda _e: self.reload_engine_picker())

        self.target_edit = QPlainTextEdit()
        self.target_edit.setPlaceholderText("Tutaj wpisz tłumaczenie…  (Ctrl+Enter = zatwierdź i dalej)")
        self.target_edit.textChanged.connect(self._on_target_changed)
        self.target_edit.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.target_edit.customContextMenuRequested.connect(self._target_context_menu)
        ed_layout.addWidget(self.target_edit)

        nav = QHBoxLayout()
        for text, tip, slot in (
            ("◀ Poprzedni", "Alt+Up", self.prev_segment),
            ("Następny ▶", "Alt+Down", self.next_segment),
            ("◀◀", "Ctrl+Alt+U – poprzedni NIEPRZETŁUMACZONY segment",
             self.prev_untranslated),
            ("▶▶", "Ctrl+U – następny NIEPRZETŁUMACZONY segment",
             self.next_untranslated),
            ("✔ Zatwierdź i dalej", "Ctrl+Enter", self.confirm_and_next),
            ("💾 Do TM", "Ctrl+Shift+S – zapisz segment do pamięci", self.save_to_tm),
            # „🤖 Tłumacz” przeniesiony wyżej – obok wyboru silnika MT.
            ("📋 Kopiuj źródło", "Ctrl+D", self.copy_source_to_target),
            ("␣ Wcięcie", "Ctrl+Alt+W – nadaj tłumaczeniu takie same spacje na brzegach jak w źródle",
             self.restore_source_indent),
            ("🚫 Pomiń", "Ctrl+Shift+I – pomiń zaznaczone segmenty (nie będą liczone)",
             self.ignore_selected),
            ("🧹 Wyczyść", "Wyczyść tłumaczenie", self.clear_target),
        ):
            btn = QPushButton(text)
            btn.setToolTip(tip)
            btn.clicked.connect(slot)
            if text in ("◀◀", "▶▶"):
                btn.setMaximumWidth(46)      # skoki do nieprzetłumaczonych
            btn.setMinimumWidth(0)
            nav.addWidget(btn)
        nav.addStretch(1)
        self.info_label = QLabel("")
        nav.addWidget(self.info_label)
        ed_layout.addLayout(nav)

        center.addWidget(grid_box)
        center.addWidget(editors)
        center.setStretchFactor(0, 3)
        center.setStretchFactor(1, 2)
        setup_splitter(center, minimums=[120, 160])
        self.center_splitter = center

        # --- prawy panel: pomoc tłumacza --------------------------------
        right = QTabWidget()

        self.matches_list = QListWidget()
        self.matches_list.setWordWrap(True)
        self.matches_list.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.matches_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.matches_list.itemDoubleClicked.connect(self._insert_match)
        matches_box = QWidget()
        mb_layout = QVBoxLayout(matches_box)
        mb_layout.setContentsMargins(4, 4, 4, 4)
        self.matches_info = QLabel("Dopasowania z pamięci tłumaczeń")
        mb_layout.addWidget(self.matches_info)
        mb_layout.addWidget(self.matches_list)
        insert_btn = QPushButton("⤵ Wstaw zaznaczone dopasowanie (Ctrl+Spacja)")
        insert_btn.clicked.connect(self._insert_selected_match)
        mb_layout.addWidget(insert_btn)
        right.addTab(matches_box, "💡 Dopasowania TM")

        # Dopasowanie zdań (fragmenty) – odpowiednik SentenceMatchingPanel z repo `5`
        self.sentence_list = QListWidget()
        self.sentence_list.setWordWrap(True)
        self.sentence_list.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.sentence_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.sentence_list.itemDoubleClicked.connect(self._insert_sentence_match)
        sentence_box = QWidget()
        sb_layout = QVBoxLayout(sentence_box)
        sb_layout.setContentsMargins(4, 4, 4, 4)
        self.sentence_toggle = QCheckBox("Włącz dopasowanie zdań")
        self.sentence_toggle.setToolTip(
            "Szuka w pamięci fragmentów i linii bieżącego segmentu.\n"
            "Przy bardzo dużych pamięciach bywa kosztowne – można wyłączyć."
        )
        self.sentence_toggle.setChecked(
            SettingsManager.instance().get_bool("tm.sentence.matching.enabled", False)
        )
        self.sentence_toggle.stateChanged.connect(self._toggle_sentence_matching)
        sb_layout.addWidget(self.sentence_toggle)

        self.sentence_info = QLabel("Fragmenty zdań znalezione w TM")
        sb_layout.addWidget(self.sentence_info)
        sb_layout.addWidget(self.sentence_list)
        sent_btn = QPushButton("⤵ Wstaw złożone tłumaczenie")
        sent_btn.clicked.connect(self._insert_selected_sentence_match)
        sb_layout.addWidget(sent_btn)
        hint = QLabel(
            "💡 Gdy segment jest dłuższy niż wpisy w TM, program szuka pasujących "
            "fragmentów i podstawia ich tłumaczenia w zdaniu."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray; font-size: 11px;")
        sb_layout.addWidget(hint)
        right.addTab(sentence_box, "🔗 Dopasowanie zdań")

        self.terms_list = QListWidget()
        self.terms_list.itemDoubleClicked.connect(self._insert_term)
        terms_box = QWidget()
        tb_layout = QVBoxLayout(terms_box)
        tb_layout.setContentsMargins(4, 4, 4, 4)
        tb_layout.addWidget(QLabel("Terminy znalezione w segmencie (2× klik = wstaw)"))
        tb_layout.addWidget(self.terms_list)
        add_term_btn = QPushButton("➕ Dodaj zaznaczenie do glosariusza")
        add_term_btn.clicked.connect(self._add_selection_to_glossary)
        tb_layout.addWidget(add_term_btn)
        right.addTab(terms_box, "🏷️ Terminy")

        self.concordance_list = QListWidget()
        conc_box = QWidget()
        cb_layout = QVBoxLayout(conc_box)
        cb_layout.setContentsMargins(4, 4, 4, 4)
        conc_row = QHBoxLayout()
        self.conc_edit = QLineEdit()
        self.conc_edit.setPlaceholderText("szukaj w pamięci tłumaczeń…")
        self.conc_edit.returnPressed.connect(self.run_concordance)
        conc_btn = QPushButton("🔍")
        conc_btn.clicked.connect(self.run_concordance)
        conc_row.addWidget(self.conc_edit, 1)
        conc_row.addWidget(conc_btn)
        cb_layout.addLayout(conc_row)
        cb_layout.addWidget(self.concordance_list)
        right.addTab(conc_box, "🔍 Konkordancja")

        self.mt_view = QPlainTextEdit()
        self.mt_view.setReadOnly(True)
        mt_box = QWidget()
        mt_layout = QVBoxLayout(mt_box)
        mt_layout.setContentsMargins(4, 4, 4, 4)
        mt_layout.addWidget(QLabel("Propozycja tłumaczenia maszynowego"))
        mt_layout.addWidget(self.mt_view)
        mt_row = QHBoxLayout()
        gen_btn = QPushButton("🤖 Generuj")
        gen_btn.clicked.connect(self.machine_translate_preview)
        quick_btn = QPushButton("⚡ QuickTrans")
        quick_btn.setToolTip("Porównaj tłumaczenia z wielu silników naraz (Ctrl+Alt+Q)")
        quick_btn.clicked.connect(lambda: self.app.open_quicktrans())
        use_btn = QPushButton("⤵ Wstaw do tłumaczenia")
        use_btn.clicked.connect(lambda: self.set_target_text(self.mt_view.toPlainText()))
        mt_row.addWidget(gen_btn)
        mt_row.addWidget(quick_btn)
        mt_row.addWidget(use_btn)
        mt_layout.addLayout(mt_row)
        right.addTab(mt_box, "🤖 MT")

        # --- panel kontroli języka (tylko tłumaczenie) -------------------
        self.lang_list = QListWidget()
        self.lang_list.setWordWrap(True)
        self.lang_list.itemDoubleClicked.connect(self._apply_lang_suggestion)
        lang_box = QWidget()
        lang_layout = QVBoxLayout(lang_box)
        lang_layout.setContentsMargins(4, 4, 4, 4)
        self.lang_status = QLabel("Kontrola języka tłumaczenia")
        self.lang_status.setWordWrap(True)
        lang_layout.addWidget(self.lang_status)
        lang_layout.addWidget(self.lang_list)

        lang_opts = QHBoxLayout()
        self.lang_auto = QCheckBox("Sprawdzaj na bieżąco")
        self.lang_auto.setToolTip("Kontroluje tłumaczenie w trakcie pisania (z opóźnieniem)")
        self.lang_auto.setChecked(
            SettingsManager.instance().get_bool("lang.check.auto", True))
        self.lang_auto.toggled.connect(self._toggle_lang_auto)
        self.lang_lt = QCheckBox("LanguageTool (przez internet)")
        self.lang_lt.setToolTip(
            "Pełna kontrola gramatyki i odmiany przez api.languagetool.org.\n"
            "Wyłączone – działają tylko reguły wbudowane (bez internetu)."
        )
        self.lang_lt.setChecked(
            SettingsManager.instance().get_bool("lang.check.languagetool", False))
        self.lang_lt.toggled.connect(self._toggle_lang_lt)
        lang_opts.addWidget(self.lang_auto)
        lang_opts.addWidget(self.lang_lt)
        lang_opts.addStretch(1)
        lang_layout.addLayout(lang_opts)

        lang_btns = QHBoxLayout()
        check_now = QPushButton("🔤 Sprawdź teraz")
        check_now.setToolTip("Ctrl+Alt+J")
        check_now.clicked.connect(lambda: self.check_language(force=True))
        fix_btn = QPushButton("✨ Popraw automatycznie")
        fix_btn.setToolTip("Wstawia pierwszą propozycję dla uwag, które ją mają")
        fix_btn.clicked.connect(self.apply_language_fixes)
        lang_btns.addWidget(check_now)
        lang_btns.addWidget(fix_btn)
        lang_layout.addLayout(lang_btns)
        right.addTab(lang_box, "🔤 Język")

        self.notes_edit = QPlainTextEdit()
        self.notes_edit.setPlaceholderText("Notatki do segmentu…")
        self.notes_edit.textChanged.connect(self._on_notes_changed)
        right.addTab(self.notes_edit, "📝 Notatki")

        splitter.addWidget(left)
        splitter.addWidget(center)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 5)
        splitter.setStretchFactor(2, 2)
        splitter.setSizes([220, 900, 350])
        # Bez tego panel „Pliki projektu” albo prawa kolumna dają się
        # przeciągnąć do zera i znikają bez możliwości przywrócenia.
        setup_splitter(splitter, minimums=[150, 320, 180])
        self.main_splitter = splitter
        layout.addWidget(splitter)

    def eventFilter(self, obj, event):  # noqa: N802 (Qt API)
        """Przechwytuje skróty nawigacji w polach tekstowych.

        QPlainTextEdit sam obsługuje Ctrl+↑/↓ (przewijanie) i Ctrl+Home/End
        (skok w tekście), więc zwykły QShortcut nigdy by się nie uruchomił.
        Tutaj łapiemy te kombinacje wcześniej i zamieniamy na zmianę segmentu.
        """
        if event.type() == QEvent.Type.KeyPress:
            mods = event.modifiers()
            key = event.key()


            ctrl = mods & Qt.KeyboardModifier.ControlModifier
            alt = mods & Qt.KeyboardModifier.AltModifier
            shift = mods & Qt.KeyboardModifier.ShiftModifier

            # Same strzałki: przechodzimy do sąsiedniego segmentu dopiero wtedy,
            # gdy kursor stoi na skraju tekstu. Dzięki temu w wielowierszowym
            # tłumaczeniu ↑/↓ nadal poruszają się po liniach, a na końcu
            # „wychodzą” do następnego segmentu — jak w OmegaT.
            if (not ctrl and not alt and not shift
                    and key in (Qt.Key.Key_Down, Qt.Key.Key_Up)
                    and SettingsManager.instance().get_bool(
                        "editor.arrows.change.segment", True)):
                if self._cursor_at_text_edge(obj, key):
                    if key == Qt.Key.Key_Down:
                        self.next_segment()
                    else:
                        self.prev_segment()
                    return True

            if ctrl or alt:
                if key == Qt.Key.Key_Down:
                    self.next_segment()
                    return True
                if key == Qt.Key.Key_Up:
                    self.prev_segment()
                    return True
                if ctrl and key == Qt.Key.Key_Home:
                    self.first_segment()
                    return True
                if ctrl and key == Qt.Key.Key_End:
                    self.last_segment()
                    return True

                # Cofanie: pole tekstowe przechwytuje Ctrl+Z zanim zadziała
                # zwykły skrót, więc obsługujemy je tutaj. Najpierw oddajemy
                # cofnięcie samemu polu (wpisany tekst), a gdy nie ma już czego
                # cofać – wracamy do historii oznaczeń.
                if ctrl and key == Qt.Key.Key_Z and not shift:
                    document = getattr(obj, "document", None)
                    if document is not None and obj.document().isUndoAvailable():
                        obj.undo()
                    else:
                        self.undo_last()
                    return True
                if ctrl and (key == Qt.Key.Key_Y or (key == Qt.Key.Key_Z and shift)):
                    document = getattr(obj, "document", None)
                    if document is not None and obj.document().isRedoAvailable():
                        obj.redo()
                    else:
                        self.redo_last()
                    return True
        return super().eventFilter(obj, event)

    @staticmethod
    def _cursor_at_text_edge(widget, key) -> bool:
        """Czy kursor jest w pierwszym (↑) lub ostatnim (↓) wierszu pola.

        Bez tego strzałki nie dałyby się użyć do poruszania po dłuższym
        tłumaczeniu — każde naciśnięcie wyrzucałoby do innego segmentu.
        """
        cursor = getattr(widget, "textCursor", None)
        if cursor is None:
            return True
        cursor = widget.textCursor()
        if cursor.hasSelection():
            return False          # zaznaczanie tekstu ma pierwszeństwo
        block = cursor.block()
        if key == Qt.Key.Key_Up:
            return not block.previous().isValid()
        return not block.next().isValid()

    #: Powiązanie identyfikatorów skrótów z metodami edytora.
    def _shortcut_actions(self) -> dict:
        return {
            "confirm_next": self.confirm_and_next,
            "next_segment": self.next_segment,
            "prev_segment": self.prev_segment,
            "next_untranslated": self.next_untranslated,
            "prev_untranslated": self.prev_untranslated,
            "next_translated": self.next_translated,
            "next_unapproved": self.next_unapproved,
            "copy_source": self.copy_source_to_target,
            "insert_match": self._insert_best_match,
            "machine_translate": self.machine_translate_current,
            "save_to_tm": self.save_to_tm,
            "restore_indent": self.restore_source_indent,
            "check_language": lambda: self.check_language(force=True),
            "find_selected": self.find_selected_word,
            "find_in_file": lambda: self.find_selected_word("Tylko przeglądany plik"),
            "copy_timing": self.copy_timing,
            "mark_new": self.mark_new,
            "mark_draft": self.mark_draft,
            "mark_translated": self.mark_translated,
            "mark_approved": self.approve_current,
            "ignore_selected": self.ignore_selected,
            "restore_selected": self.restore_selected,
        }

    def _build_shortcuts(self) -> None:
        """Rejestruje skróty edytora na podstawie centralnego rejestru.

        Każda kombinacja jest przypisana TYLKO TUTAJ albo tylko w menu –
        podwójna rejestracja powodowała, że Qt uznawało skrót za niejednoznaczny
        i nie wywoływało żadnej akcji (tak przestał działać `Ctrl+U`).
        """
        from ..core import shortcuts as _sc

        self._shortcut_objects = {}
        actions = self._shortcut_actions()
        for definition in _sc.SHORTCUTS:
            if not definition.editor:
                continue            # obsługiwane przez menu głównego okna
            slot = actions.get(definition.key)
            if slot is None:
                continue
            sequence = _sc.get(definition.key)
            if not sequence:
                continue
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(slot)
            self._shortcut_objects[definition.key] = shortcut

        # Ctrl+Enter to na części klawiatur osobna kombinacja niż Ctrl+Return.
        enter = QShortcut(QKeySequence("Ctrl+Enter"), self)
        enter.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        enter.activated.connect(self.confirm_and_next)

        # Ctrl+↑/↓ i Ctrl+Home/End przechwytuje eventFilter – pola tekstowe
        # obsługują te klawisze same i nie oddałyby ich zwykłemu skrótowi.
        for widget in (self.target_edit, self.source_edit, self.notes_edit):
            widget.installEventFilter(self)

    def reload_shortcuts(self) -> None:
        """Stosuje zmienione kombinacje bez restartu programu."""
        for shortcut in getattr(self, "_shortcut_objects", {}).values():
            shortcut.setEnabled(False)
            shortcut.setKey(QKeySequence())     # natychmiast zwalnia kombinację
            shortcut.setParent(None)
            shortcut.deleteLater()
        self._shortcut_objects = {}
        self._build_shortcuts()

    # -------------------------------------------------------------- dane
    def set_segments(self, segments: List[Segment]) -> None:
        self.segments = segments
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._volatile_sent.clear()
        self.current_index = 0 if segments else -1
        self.refresh_files_list()
        self.refresh_grid()
        if segments:
            self.load_segment(0)
        else:
            self.source_edit.clear()
            self.target_edit.clear()
        self.update_progress()

    def _file_counters(self) -> "dict[str, tuple[int, int, int]]":
        """Zlicza (przetłumaczone, do zrobienia, pominięte) dla każdego pliku.

        Segmenty pominięte (ręcznie albo regułą wykluczania) NIE wchodzą do
        mianownika — inaczej licznik pokazywałby pracę, której nikt nie wykona.
        """
        counters: dict[str, list] = {}
        for seg in self.segments:
            name = seg.file_name or "(bez pliku)"
            entry = counters.setdefault(name, [0, 0, 0])
            if seg.ignored:
                entry[2] += 1
                continue
            entry[1] += 1
            if _is_done(seg):
                entry[0] += 1
        return {name: (done, total, skipped)
                for name, (done, total, skipped) in counters.items()}

    @staticmethod
    def _file_label(name: str, done: int, total: int, skipped: int = 0) -> str:
        # Pominięte wypadają z licznika – same liczby wystarczą, bez dodatkowych
        # oznaczeń, żeby lista plików pozostała czytelna.
        percent = int(done * 100 / total) if total else 0
        mark = "✅" if total and done == total else "📄"
        return f"{mark} {name}  ({done}/{total} • {percent}%)"

    def refresh_files_list(self) -> None:
        """Buduje listę plików od nowa (po imporcie / usunięciu pliku)."""
        selected = self._file_filter
        self.files_list.blockSignals(True)
        self.files_list.clear()
        counters = self._file_counters()
        total_done = sum(done for done, _t, _s in counters.values())
        total_todo = sum(total for _d, total, _s in counters.values())
        total_skip = sum(skipped for _d, _t, skipped in counters.values())

        item = QListWidgetItem(self._all_files_label(total_done, total_todo, total_skip))
        item.setData(Qt.ItemDataRole.UserRole, None)
        self.files_list.addItem(item)
        # Kolejność bierzemy z projektu – ręczne ustawienie musi być widoczne
        # na liście, inaczej przyciski ▲▼ nie miałyby żadnego efektu.
        project = getattr(self.app, "project", None)
        preferred = list(getattr(project, "file_order", []) or [])
        if preferred:
            from ..core.project import order_files

            names = order_files(sorted(counters), preferred)
        else:
            names = sorted(counters)
        for name in names:
            done, total, skipped = counters[name]
            it = QListWidgetItem(self._file_label(name, done, total, skipped))
            it.setData(Qt.ItemDataRole.UserRole, name)
            self.files_list.addItem(it)
            if name == selected:
                self.files_list.setCurrentItem(it)
        if selected is None and self.files_list.count():
            self.files_list.setCurrentRow(0)
        self.files_list.blockSignals(False)

    @staticmethod
    def _all_files_label(done: int, total: int, skipped: int) -> str:
        return f"📚 Wszystkie pliki ({done}/{total})"

    def update_file_counters(self) -> None:
        """Odświeża same LICZNIKI na liście plików, bez przebudowy widoku.

        Wywoływane po każdej zmianie tłumaczenia (również masowej, jak
        „Zastosuj TM”), dlatego musi być tanie: podmieniamy wyłącznie tekst
        pozycji, zachowując zaznaczenie i pozycję przewijania.
        """
        if self.files_list.count() == 0:
            return
        counters = self._file_counters()
        # Zmiana liczby plików wymaga pełnej przebudowy (import / usunięcie).
        listed = {self.files_list.item(i).data(Qt.ItemDataRole.UserRole)
                  for i in range(self.files_list.count())} - {None}
        if listed != set(counters):
            self.refresh_files_list()
            return

        total_done = sum(done for done, _t, _s in counters.values())
        total_todo = sum(total for _d, total, _s in counters.values())
        total_skip = sum(skipped for _d, _t, skipped in counters.values())
        for row in range(self.files_list.count()):
            item = self.files_list.item(row)
            name = item.data(Qt.ItemDataRole.UserRole)
            if name is None:
                text = self._all_files_label(total_done, total_todo, total_skip)
            else:
                done, total, skipped = counters.get(name, (0, 0, 0))
                text = self._file_label(name, done, total, skipped)
            if item.text() != text:            # bez zbędnego przerysowania
                item.setText(text)

    # ------------------------------------------------- kolejność i wybór plików
    def selected_file_names(self) -> List[str]:
        """Nazwy zaznaczonych plików (pomija pozycję „Wszystkie pliki”)."""
        names = []
        for item in self.files_list.selectedItems():
            name = item.data(Qt.ItemDataRole.UserRole)
            if name:
                names.append(name)
        return names

    def _on_files_selection_changed(self) -> None:
        """Aktualizuje licznik zaznaczenia i dostępność przycisków."""
        names = self.selected_file_names()
        count = len(names)
        if count > 1:
            self.files_selection_label.setText(f"zaznaczono {count}")
        else:
            self.files_selection_label.setText("")
        for button in (self.file_up_btn, self.file_down_btn, self.file_remove_btn):
            button.setEnabled(count > 0)

    def current_file_order(self) -> List[str]:
        """Kolejność plików widoczna na liście (bez „Wszystkie pliki”)."""
        order = []
        for row in range(self.files_list.count()):
            name = self.files_list.item(row).data(Qt.ItemDataRole.UserRole)
            if name:
                order.append(name)
        return order

    def _on_files_reordered(self, order: List[str]) -> None:
        """Zapisuje kolejność ustawioną przeciągnięciem pliku na liście."""
        if not self.app.project or not order:
            return
        self.app.project.file_order = list(order)
        self.app.project_manager.save_project()
        self._reorder_segments(order)
        # Listy nie przebudowujemy — Qt już przeniosło wiersze, a odświeżenie
        # skasowałoby zaznaczenie tuż po upuszczeniu.
        self.update_progress()
        self.app.show_status(f"↕️ Zmieniono kolejność plików ({len(order)})")

    def move_files(self, offset: int) -> None:
        """Przesuwa zaznaczone pliki o jedną pozycję w górę (-1) lub w dół (+1).

        Kolejność wpływa na numerację segmentów i kolejność eksportu, więc
        zapisujemy ją w projekcie — przetrwa zamknięcie programu i F5.
        """
        names = self.selected_file_names()
        if not names or not self.app.project:
            return
        order = self.current_file_order()
        positions = sorted(order.index(n) for n in names if n in order)
        if not positions:
            return
        # Przy ruchu w dół idziemy od końca, żeby elementy nie wchodziły na siebie.
        if offset > 0:
            positions.reverse()
        for index in positions:
            target = index + offset
            if target < 0 or target >= len(order):
                return          # blok dotarł do krawędzi – nie ruszamy nic
            order[index], order[target] = order[target], order[index]

        self.app.project.file_order = order
        self.app.project_manager.save_project()
        self._reorder_segments(order)
        self.refresh_files_list()
        self._reselect_files(names)
        self.app.show_status(f"↕️ Zmieniono kolejność plików ({len(names)})")

    def sort_files_alphabetically(self) -> None:
        """Przywraca porządek alfabetyczny (kasuje ręczną kolejność)."""
        if not self.app.project:
            return
        order = sorted(self.current_file_order())
        self.app.project.file_order = []
        self.app.project_manager.save_project()
        self._reorder_segments(order)
        self.refresh_files_list()
        self.app.show_status("🔤 Przywrócono kolejność alfabetyczną")

    def _reorder_segments(self, order: List[str]) -> None:
        """Układa segmenty zgodnie z kolejnością plików, zachowując ich układ w pliku."""
        rank = {name: position for position, name in enumerate(order)}
        current = self.current_segment()
        self.segments.sort(
            key=lambda s: rank.get(s.file_name or "(bez pliku)", len(rank)))
        self.refresh_grid()
        if current is not None and current in self.segments:
            self.current_index = self.segments.index(current)

    def _reselect_files(self, names: List[str]) -> None:
        wanted = set(names)
        self.files_list.clearSelection()
        for row in range(self.files_list.count()):
            item = self.files_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) in wanted:
                item.setSelected(True)

    def remove_selected_files(self) -> None:
        """Usuwa z projektu wszystkie zaznaczone pliki (jedno pytanie na całość)."""
        names = self.selected_file_names()
        if not names:
            QMessageBox.information(self, "Pliki projektu",
                                    "Zaznacz pliki, które chcesz usunąć.")
            return
        if len(names) == 1:
            self.app.remove_project_file(names[0])
            self._on_files_selection_changed()
            return
        self.app.remove_project_files(names)
        self._on_files_selection_changed()

    def _files_context_menu(self, pos) -> None:
        """Menu podręczne listy plików (prawy przycisk myszy)."""
        item = self.files_list.itemAt(pos)
        if item is None:
            return
        file_name = item.data(Qt.ItemDataRole.UserRole)   # None = „Wszystkie pliki”
        segments = [s for s in self.segments
                    if file_name is None or (s.file_name or "(bez pliku)") == file_name]
        pending = sum(1 for s in segments if not s.is_translated and not s.ignored)
        label = file_name or "wszystkich plików"

        menu = QMenu(self)
        act_tm = menu.addAction(f"💡 Zastosuj TM do „{label}” ({pending} pustych)")
        act_tm.setEnabled(pending > 0 and self.app.tm.is_initialized)
        act_mt = menu.addAction(f"🤖 Przetłumacz maszynowo „{label}” ({pending} pustych)")
        act_mt.setEnabled(pending > 0)
        menu.addSeparator()
        act_show = menu.addAction("👁️ Pokaż tylko ten plik" if file_name else "👁️ Pokaż wszystkie")
        act_find = menu.addAction(f"🔍 Szukaj w „{label}”…")
        act_stats = menu.addAction("📊 Statystyki pliku")
        menu.addSeparator()
        act_add = menu.addAction("➕ Dodaj pliki…")
        selected = self.selected_file_names()
        if len(selected) > 1:
            act_remove = menu.addAction(
                f"🗑️ Usuń zaznaczone pliki ({len(selected)}) z projektu")
        else:
            act_remove = menu.addAction(f"🗑️ Usuń „{file_name}” z projektu"
                                        if file_name else "🗑️ Usuń plik z projektu")
        act_remove.setEnabled(bool(selected) or file_name is not None)
        menu.addSeparator()
        act_up = menu.addAction("▲ Przesuń w górę")
        act_down = menu.addAction("▼ Przesuń w dół")
        act_sort = menu.addAction("🔤 Kolejność alfabetyczna")
        for action in (act_up, act_down):
            action.setEnabled(bool(selected))

        chosen = menu.exec(self.files_list.viewport().mapToGlobal(pos))
        if chosen is None:
            return
        if chosen == act_tm:
            self.app.apply_tm_to_all(only_file=file_name)
        elif chosen == act_mt:
            self.app.translate_all_mt(only_file=file_name)
        elif chosen == act_show:
            self._file_filter = file_name
            self.refresh_grid()
        elif chosen == act_find:
            search_tab = self.app.search_tab
            if file_name:
                search_tab._selected_files = [file_name]
                search_tab.scope.blockSignals(True)
                search_tab.scope.setCurrentText("Wybrane pliki…")
                search_tab.scope.blockSignals(False)
            else:
                search_tab.scope.setCurrentText("Cały projekt")
            self.app.tabs.setCurrentWidget(search_tab)
            search_tab.search_edit.setFocus()
            search_tab.search_edit.selectAll()
        elif chosen == act_stats:
            self._show_file_statistics(file_name, segments)
        elif chosen == act_add:
            self.app.import_files()
        elif chosen == act_up:
            self.move_files(-1)
        elif chosen == act_down:
            self.move_files(1)
        elif chosen == act_sort:
            self.sort_files_alphabetically()
        elif chosen == act_remove:
            if len(selected) > 1:
                self.app.remove_project_files(selected)
                self._on_files_selection_changed()
            elif file_name:
                self.app.remove_project_file(file_name)

    def _show_file_statistics(self, file_name: Optional[str], segments: List[Segment]) -> None:
        from ..core.qa import project_statistics

        stats = project_statistics(segments, self.app.tm.size() if self.app.tm.is_initialized else 0)
        title = file_name or "Wszystkie pliki"
        QMessageBox.information(
            self, f"Statystyki – {title}",
            "\n".join(f"{k}: {v}" for k, v in stats.items()),
        )

    def _on_files_dropped(self, paths: List[str]) -> None:
        """Obsługuje pliki upuszczone na listę plików projektu."""
        if not self.app.project:
            QMessageBox.information(
                self, "Import plików",
                "Najpierw utwórz lub otwórz projekt (Ctrl+N / Ctrl+O).",
            )
            return
        self.app.import_file_paths(paths)

    def _on_file_selected(self, item: QListWidgetItem) -> None:
        self._file_filter = item.data(Qt.ItemDataRole.UserRole)
        self.refresh_grid()

    def _show_all_files(self) -> None:
        self._file_filter = None
        if self.files_list.count():
            self.files_list.setCurrentRow(0)
        self.refresh_grid()

    # ------------------------------------------------------------- siatka
    def _visible_indices(self) -> List[int]:
        text = self.filter_edit.text().strip().lower()
        status = self.status_filter.currentText()
        out = []
        for i, seg in enumerate(self.segments):
            if self._file_filter and (seg.file_name or "(bez pliku)") != self._file_filter:
                continue
            if text and text not in (seg.source or "").lower() and text not in (seg.target or "").lower():
                continue
            if status == "Nieprzetłumaczone" and seg.is_translated:
                continue
            if status == "Przetłumaczone" and not seg.is_translated:
                continue
            if status == "Zatwierdzone" and seg.status != "approved":
                continue
            if status == "Pominięte" and not seg.ignored:
                continue
            out.append(i)
        return out

    def refresh_grid(self) -> None:
        self._loading = True
        marks_cfg = marker_settings()
        indices = self._visible_indices()
        self.grid.setRowCount(len(indices))
        for row, idx in enumerate(indices):
            seg = self.segments[idx]
            num = QTableWidgetItem(str(idx + 1))
            num.setData(Qt.ItemDataRole.UserRole, idx)
            num.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            src = QTableWidgetItem(display_text(seg.source or "", **marks_cfg))
            tgt = QTableWidgetItem(display_text(seg.target or "", **marks_cfg))
            _set_whitespace_hint(src, seg.source or "", marks_cfg)
            _set_whitespace_hint(tgt, seg.target or "", marks_cfg)
            status_key = "ignored" if seg.ignored else (
                seg.status if seg.status in STATUS_LABELS else ("translated" if seg.is_translated else "new")
            )
            st = QTableWidgetItem(STATUS_LABELS.get(status_key, status_key))
            bg = QColor(
                self.colors.ignored_bg if seg.ignored else
                self.colors.approved_bg if seg.status == "approved" else
                self.colors.translated_bg if seg.is_translated else
                self.colors.untranslated_bg
            )
            fg = QColor(self.colors.row_fg)
            for item in (num, src, tgt, st):
                item.setBackground(bg)
                item.setForeground(fg)
            self.grid.setItem(row, 0, num)
            self.grid.setItem(row, 1, src)
            self.grid.setItem(row, 2, tgt)
            self.grid.setItem(row, 3, st)
        self._loading = False
        self._select_row_for_index(self.current_index)
        self.update_progress()

    def _select_row_for_index(self, index: int) -> None:
        """Zaznacza w siatce wiersz bieżącego segmentu — tylko jego.

        `QTableWidget.selectRow()` w trybie `ExtendedSelection` **przełącza**
        zaznaczenie zamiast je zastąpić: przy przechodzeniu między segmentami
        zaznaczone wiersze się kumulowały (po kilku ↓ pół projektu było
        podświetlone). Dlatego wybieramy wiersz wprost przez model, z jawną
        flagą `ClearAndSelect`.
        """
        from PyQt6.QtCore import QItemSelectionModel

        for row in range(self.grid.rowCount()):
            item = self.grid.item(row, 0)
            if item and item.data(Qt.ItemDataRole.UserRole) == index:
                self._loading = True
                model = self.grid.selectionModel()
                if model is not None:
                    model.setCurrentIndex(
                        self.grid.model().index(row, 0),
                        QItemSelectionModel.SelectionFlag.ClearAndSelect
                        | QItemSelectionModel.SelectionFlag.Rows)
                else:
                    self.grid.selectRow(row)
                self.grid.scrollToItem(item, QAbstractItemView.ScrollHint.EnsureVisible)
                self._loading = False
                return

    def reveal_segment(self, index: int) -> bool:
        """Odsłania segment w siatce, zdejmując filtry, które go ukrywają.

        Bez tego przejście do wyniku wyszukiwania z INNEGO pliku kończyło się
        rozjazdem: edytor pokazywał właściwy segment, ale siatka nadal
        filtrowała poprzedni plik i podświetlała zupełnie inny wiersz.
        Zwraca ``True``, gdy trzeba było coś zmienić.
        """
        if not (0 <= index < len(self.segments)):
            return False
        if index in self._visible_indices():
            return False        # segment i tak jest widoczny – nic nie ruszamy

        seg = self.segments[index]
        changed = []

        # 1) filtr pliku – przełącz na plik, w którym leży segment
        file_name = seg.file_name or "(bez pliku)"
        if self._file_filter and self._file_filter != file_name:
            self._file_filter = file_name
            self._select_file_in_list(file_name)
            changed.append(f"plik → {file_name}")

        # 2) filtr tekstowy siatki
        text = self.filter_edit.text().strip().lower()
        if text and text not in (seg.source or "").lower() and text not in (seg.target or "").lower():
            self.filter_edit.blockSignals(True)
            self.filter_edit.clear()
            self.filter_edit.blockSignals(False)
            changed.append("wyczyszczono filtr siatki")

        # 3) filtr statusu
        status = self.status_filter.currentText()
        hidden_by_status = (
            (status == "Nieprzetłumaczone" and seg.is_translated)
            or (status == "Przetłumaczone" and not seg.is_translated)
            or (status == "Zatwierdzone" and seg.status != "approved")
            or (status == "Pominięte" and not seg.ignored)
        )
        if hidden_by_status:
            self.status_filter.blockSignals(True)
            self.status_filter.setCurrentText("Wszystkie")
            self.status_filter.blockSignals(False)
            changed.append("status → Wszystkie")

        self.refresh_grid()
        if changed:
            self.status_message.emit("Pokazano ukryty segment (" + ", ".join(changed) + ")")
        return bool(changed)

    def _select_file_in_list(self, file_name: Optional[str]) -> None:
        """Zaznacza plik na liście plików projektu (bez wywoływania sygnałów)."""
        self.files_list.blockSignals(True)
        for i in range(self.files_list.count()):
            item = self.files_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == file_name:
                self.files_list.setCurrentItem(item)
                break
        self.files_list.blockSignals(False)

    def _on_grid_move(self, step: int) -> None:
        """Nawigacja klawiaturą z siatki — bez rozszerzania zaznaczenia."""
        if step <= -10 ** 9:
            self.first_segment()
        elif step >= 10 ** 9:
            self.last_segment()
        elif step > 0:
            self.next_segment()
        else:
            self.prev_segment()

    def _on_grid_selection(self) -> None:
        if self._loading:
            return
        rows = self.grid.selectionModel().selectedRows() if self.grid.selectionModel() else []
        if not rows:
            return
        item = self.grid.item(rows[0].row(), 0)
        if item is None:
            return
        index = item.data(Qt.ItemDataRole.UserRole)
        if index is not None and index != self.current_index:
            self._store_current()
            self.load_segment(index)

    def _grid_context_menu(self, pos) -> None:
        menu = QMenu(self)
        act_copy = menu.addAction("📋 Kopiuj źródło do tłumaczenia")
        act_mt = menu.addAction("🤖 Przetłumacz maszynowo")
        act_tm = menu.addAction("💾 Zapisz do TM")
        menu.addSeparator()
        act_alt = menu.addAction("📝 Dodaj jako tłumaczenie alternatywne")
        act_show_alt = menu.addAction("🔍 Pokaż tłumaczenia alternatywne")
        menu.addSeparator()
        act_find = menu.addAction("🔍 Szukaj zaznaczonego wyrazu w projekcie (Ctrl+Shift+F)")
        act_find_file = menu.addAction("🔎 Szukaj tylko w tym pliku (Ctrl+Alt+F)")
        menu.addSeparator()
        selected_now = self.selected_indices()
        many = f" ({len(selected_now)})" if len(selected_now) > 1 else ""
        status_menu = menu.addMenu(f"🏷️ Oznacz jako…{many}")
        act_new = status_menu.addAction("○ nowy")
        act_draft = status_menu.addAction("✎ roboczy")
        act_translated = status_menu.addAction("✓ przetłumaczony")
        act_approve = status_menu.addAction("★ zatwierdzony")
        menu.addSeparator()

        selected = self.selected_indices()
        count = len(selected)
        suffix = f" ({count} zaznaczonych)" if count > 1 else ""
        act_ignore = menu.addAction(f"🚫 Pomiń zaznaczone{suffix}")
        act_restore = menu.addAction(f"↩️ Przywróć zaznaczone{suffix}")
        act_toggle = menu.addAction("🔁 Odwróć pominięcie")
        menu.addSeparator()
        act_ignore_file = menu.addAction("🚫 Pomiń nieprzetłumaczone w tym pliku…")
        act_ignore_match = menu.addAction("🚫 Pomiń pasujące do wzorca…")
        act_bulk = menu.addAction("🏷️ Oznacz pasujące do wzorca… (zakresy, CJK)")
        act_adapt = menu.addAction(f"⇢ Dopasuj znaczniki do oryginału{many}")
        menu.addSeparator()
        skipped_total = sum(1 for s in self.segments if s.ignored)
        act_restore_all = menu.addAction(
            f"↩️ Przywróć WSZYSTKIE pominięte ({skipped_total})")
        act_restore_all.setEnabled(skipped_total > 0)
        act_restore_file = menu.addAction("↩️ Przywróć pominięte w tym pliku")
        action = menu.exec(self.grid.viewport().mapToGlobal(pos))
        if action == act_new:
            self.mark_new()
            return
        if action == act_draft:
            self.mark_draft()
            return
        if action == act_translated:
            self.mark_translated()
            return
        if action == act_restore_all:
            self.restore_all_ignored()
            return
        if action == act_restore_file:
            self.restore_ignored_in_file()
            return
        if action == act_restore:
            self.restore_selected()
            return
        if action == act_toggle:
            self.toggle_ignore()
            return
        if action == act_ignore_file:
            self.ignore_untranslated_in_file()
            return
        if action == act_ignore_match:
            self.ignore_matching()
            return
        if action == act_bulk:
            self.bulk_mark_matching()
            return
        if action == act_adapt:
            self.adapt_codes_selected()
            return
        if action == act_find:
            self.find_selected_word()
            return
        if action == act_find_file:
            self.find_selected_word("Tylko przeglądany plik")
            return
        if action == act_copy:
            self.copy_source_to_target()
        elif action == act_mt:
            self.machine_translate_current()
        elif action == act_tm:
            self.save_to_tm()
        elif action == act_alt:
            self.add_alternative_translation()
        elif action == act_show_alt:
            self.show_alternative_translations()
        elif action == act_approve:
            self.approve_current()
        elif action == act_ignore:
            self.ignore_selected()

    # ---------------------------------------------------------- segmenty
    def load_segment(self, index: int) -> None:
        if not (0 <= index < len(self.segments)):
            return
        self._loading = True
        self.current_index = index
        seg = self.segments[index]
        self.source_edit.setPlainText(seg.source)
        self.target_edit.setPlainText(seg.target)
        self.notes_edit.setPlainText(seg.notes)
        edges = describe_edges(seg.source)
        edge_note = f"  •  ␣ wcięcie: {edges}" if edges else ""
        self.segment_label.setText(
            f"Segment {index + 1} / {len(self.segments)}  •  {seg.file_name or '—'}  •  "
            f"{word_count(seg.source)} słów  •  status: {STATUS_LABELS.get('ignored' if seg.ignored else seg.status, seg.status)}"
            + edge_note
        )
        self.segment_label.setToolTip(
            "Segment zaczyna się lub kończy spacją – tak jest w pliku źródłowym.\n"
            "Tłumaczenie dostanie takie same spacje na brzegach."
            if edges else ""
        )
        self._loading = False
        self._select_row_for_index(index)
        self.target_edit.setFocus()
        self._search_source_selections = []
        self._highlight_terms()
        self.highlight_whitespace()
        if self._search_needle:
            # utrzymaj podświetlenie szukanej frazy przy przechodzeniu F3
            options = None
            search_tab = getattr(self.app, "search_tab", None)
            if search_tab is not None:
                options = search_tab.current_options()
            self.highlight_search(self._search_needle, options)

        # Natychmiast usuń wyniki poprzedniego segmentu – bez tego stare
        # podpowiedzi wisiały na ekranie przez cały czas szukania i wyglądały
        # jak dopasowania bieżącego segmentu.
        self._clear_helper_results()

        self._lang_issues = []
        self._lang_selections = []
        self.lang_list.clear()
        _lang_settings = SettingsManager.instance()
        if (_lang_settings.get_bool("lang.check.enabled", True)
                and _lang_settings.get_bool("lang.check.auto", True)):
            self._lang_timer.start(400)
        else:
            self.lang_status.setText("Kontrola na bieżąco wyłączona")

        self._segment_changed_at = _time.perf_counter()
        self._tm_timer.start(self._tm_debounce_ms)
        self.segment_changed.emit(index)

    def _toggle_sentence_matching(self, state) -> None:
        """Szybkie włączanie/wyłączanie dopasowania zdań wprost z edytora."""
        enabled = bool(state)
        SettingsManager.instance().set("tm.sentence.matching.enabled", enabled)
        # utrzymaj zgodność z przełącznikiem w Ustawieniach
        settings_tab = getattr(self.app, "settings_tab", None)
        box = getattr(settings_tab, "sentence_matching", None)
        if box is not None and box.isChecked() != enabled:
            box.blockSignals(True)
            box.setChecked(enabled)
            box.blockSignals(False)
            if hasattr(settings_tab, "_update_sentence_enabled"):
                settings_tab._update_sentence_enabled()
        if enabled:
            self._refresh_helpers()
        else:
            self.sentence_list.clear()
            self.sentence_info.setText("Dopasowanie zdań wyłączone")

    def sync_sentence_toggle(self) -> None:
        """Odświeża przełącznik po zmianie ustawienia w zakładce Ustawienia."""
        enabled = SettingsManager.instance().get_bool("tm.sentence.matching.enabled", False)
        if self.sentence_toggle.isChecked() != enabled:
            self.sentence_toggle.blockSignals(True)
            self.sentence_toggle.setChecked(enabled)
            self.sentence_toggle.blockSignals(False)

    @staticmethod
    def format_duration(ms: float, unit: str = "auto") -> str:
        """Formatuje czas w wybranej jednostce (ms / s / min / auto)."""
        return format_duration(ms, unit)

    def _update_timing_label(self) -> None:
        """Pokazuje, ile trwało ostatnie wyszukiwanie (do zgłaszania spowolnień)."""
        t = self._last_timing or {}
        if not t:
            self.timing_label.setText("")
            self._timing_plain = ""
            return
        unit = SettingsManager.instance().get_str("ui.time.unit", "auto")
        fmt = self.format_duration
        parts = [f"TM {fmt(t.get('fuzzy_ms', 0), unit)}"]
        if t.get("sentence_ms"):
            parts.append(f"ZD {fmt(t['sentence_ms'], unit)}")
        if self._segment_changed_at:
            waited = (_time.perf_counter() - self._segment_changed_at) * 1000
            parts.append(f"⏱ {fmt(waited, unit)}")
        parts.append(f"TM: {self.app.tm.size()}")
        self._timing_plain = "  •  ".join(parts)
        self.timing_label.setText(self._timing_plain + "  📋")

    def copy_timing(self) -> None:
        """Kopiuje pomiar czasu do schowka (do zgłaszania spowolnień)."""
        from PyQt6.QtWidgets import QApplication as _QApp

        text = getattr(self, "_timing_plain", "")
        if not text:
            return
        seg = self.current_segment()
        details = [
            "SuperCAT – pomiar wydajności",
            text,
            f"segment: {self.current_index + 1}/{len(self.segments)}",
            f"dopasowanie zdań: "
            f"{'włączone' if SettingsManager.instance().get_bool('tm.sentence.matching.enabled', False) else 'wyłączone'}",
        ]
        if seg is not None:
            details.append(f"długość segmentu: {len(seg.source)} znaków")
        _QApp.clipboard().setText("\n".join(details))
        self.info_label.setText("📋 Skopiowano pomiar czasu do schowka")

    def _clear_helper_results(self) -> None:
        """Czyści panele podpowiedzi i pokazuje stan „szukam”."""
        settings = SettingsManager.instance()
        self.matches_list.clear()
        self.sentence_list.clear()
        if self.app.tm.is_initialized:
            self.matches_info.setText("⏳ Szukanie dopasowań…")
        else:
            self.matches_info.setText("Brak pamięci TM (otwórz projekt)")
        if settings.get_bool("tm.sentence.matching.enabled", False):
            self.sentence_info.setText("⏳ Szukanie fragmentów zdań…")
        else:
            self.sentence_info.setText(
                "Dopasowanie zdań jest wyłączone — włącz w Ustawieniach → Pamięć TM"
            )

    def _store_current(self) -> None:
        if 0 <= self.current_index < len(self.segments):
            seg = self.segments[self.current_index]
            seg.target = self.target_edit.toPlainText()
            if seg.target.strip() and seg.status in ("new", ""):
                seg.status = "draft"

    def next_untranslated(self) -> None:
        """Ctrl+U – następny segment bez tłumaczenia (jak w OmegaT)."""
        self._jump_to(lambda seg: not _is_done(seg) and not seg.ignored,
                      forward=True, what="nieprzetłumaczonego")

    def prev_untranslated(self) -> None:
        self._jump_to(lambda seg: not _is_done(seg) and not seg.ignored,
                      forward=False, what="nieprzetłumaczonego")

    def next_translated(self) -> None:
        """Ctrl+Shift+U – następny segment z tłumaczeniem (jak w OmegaT)."""
        self._jump_to(lambda seg: _is_done(seg) and not seg.ignored,
                      forward=True, what="przetłumaczonego")

    def next_unapproved(self) -> None:
        """Następny segment, który nie został jeszcze zatwierdzony."""
        self._jump_to(lambda seg: seg.status != "approved" and not seg.ignored,
                      forward=True, what="niezatwierdzonego")

    def _jump_to(self, predicate, forward: bool = True, what: str = "") -> None:
        """Skacze do najbliższego segmentu spełniającego warunek – z zawijaniem.

        Gdy przeglądasz pojedynczy plik, skok **zostaje w tym pliku**. Dopiero
        kiedy nie ma w nim już celu, program pyta, czy przejść do innego pliku —
        wcześniej po cichu podmieniał filtr i wyrzucał do zupełnie innego tekstu.
        """
        total = len(self.segments)
        if not total:
            return
        start = self.current_index if self.current_index >= 0 else 0
        step = 1 if forward else -1

        # Zakres podstawowy: bieżący plik, jeśli lista jest nim filtrowana.
        scope = self._file_filter
        if scope is None and 0 <= start < total:
            seg = self.segments[start]
            scope = None if self.files_list.currentRow() <= 0 else (seg.file_name or "(bez pliku)")

        def in_scope(seg) -> bool:
            return scope is None or (seg.file_name or "(bez pliku)") == scope

        def search(check_scope: bool):
            for offset in range(1, total + 1):
                index = (start + step * offset) % total
                candidate = self.segments[index]
                if check_scope and not in_scope(candidate):
                    continue
                if predicate(candidate):
                    return index
            return -1

        index = search(check_scope=True)
        if index >= 0:
            self._store_current()
            self.reveal_segment(index)
            self.load_segment(index)
            if (forward and index <= start) or (not forward and index >= start):
                where = f" w pliku {scope}" if scope else ""
                self.status_message.emit(f"Przewinięto na początek listy{where}")
            return

        # W bieżącym pliku nie ma celu – pytamy przed wyjściem poza niego.
        if scope is not None:
            other = search(check_scope=False)
            if other < 0:
                self.status_message.emit(f"Brak segmentu {what}".strip())
                return
            target_file = self.segments[other].file_name or "(bez pliku)"
            if QMessageBox.question(
                self, "Koniec pliku",
                f"W pliku „{scope}” nie ma już segmentu {what}.\n\n"
                f"Przejść do pliku „{target_file}”?",
            ) != QMessageBox.StandardButton.Yes:
                return
            self._store_current()
            self.reveal_segment(other)
            self.load_segment(other)
            return
        self.status_message.emit(f"Brak segmentu {what}".strip())

    def next_segment(self) -> None:
        self._store_current()
        if self.current_index + 1 < len(self.segments):
            self.load_segment(self.current_index + 1)
            self._update_row(self.current_index - 1)
        else:
            self.info_label.setText("To już ostatni segment")

    def prev_segment(self) -> None:
        self._store_current()
        if self.current_index > 0:
            self.load_segment(self.current_index - 1)
            self._update_row(self.current_index + 1)

    def first_segment(self) -> None:
        """Przechodzi do pierwszego segmentu (Ctrl+Home)."""
        if self.segments:
            self._store_current()
            self.load_segment(0)

    def last_segment(self) -> None:
        """Przechodzi do ostatniego segmentu (Ctrl+End)."""
        if self.segments:
            self._store_current()
            self.load_segment(len(self.segments) - 1)

    def confirm_and_next(self) -> None:
        """Zatwierdza segment: status = przetłumaczony, zapis do TM, przejście dalej."""
        if not (0 <= self.current_index < len(self.segments)):
            return
        self._store_current()
        seg = self.segments[self.current_index]
        # Zatwierdzenie ZAWSZE zmienia oznaczenie – także dla segmentu celowo
        # pustego. Wcześniej pusty segment przechodził dalej bez żadnej zmiany.
        target_status = SettingsManager.instance().get(
            "editor.confirm.status", "translated") or "translated"
        if seg.status != target_status:
            self._push_undo("zatwierdzenie segmentu",
                            [(self.current_index, "status", seg.status)])
        seg.status = target_status
        if seg.is_translated and SettingsManager.instance().get_bool("tm.auto.add", True):
            self.save_to_tm(silent=True)
        idx = self.current_index
        self._update_row(idx)
        self.update_progress()
        if self.app.project:
            try:
                self.app.save_translations(silent=True)
            except Exception:
                pass

        # Po zatwierdzeniu przechodzimy do kolejnego segmentu DO ZROBIENIA,
        # a nie po prostu do następnego w kolejności.
        if SettingsManager.instance().get_bool("editor.confirm.skip.done", True):
            for offset in range(1, len(self.segments) + 1):
                nxt = (idx + offset) % len(self.segments)
                if nxt == idx:
                    break
                candidate = self.segments[nxt]
                if not candidate.ignored and not _is_done(candidate):
                    self.load_segment(nxt)
                    return
            self.refresh_grid()
            self.info_label.setText("✅ Wszystkie segmenty zrobione")
            return
        if idx + 1 < len(self.segments):
            self.load_segment(idx + 1)
        else:
            self.refresh_grid()
            self.info_label.setText("✅ Ostatni segment zatwierdzony")

    def approve_current(self) -> None:
        """Oznacza zaznaczone segmenty jako zatwierdzone (działa też grupowo)."""
        self.set_status(self.selected_indices(), "approved")

    # ----------------------------------------------------------- historia
    def _push_undo(self, label: str, changes: "list[tuple]") -> None:
        """Zapamiętuje zmianę, żeby dało się ją cofnąć (Ctrl+Z).

        `changes` to lista krotek (indeks, pole, poprzednia_wartość).
        Historia obejmuje operacje na oznaczeniach i pominięciach — pole tekstowe
        ma własne cofanie wbudowane w Qt.
        """
        if not changes:
            return
        self._undo_stack.append((label, changes))
        if len(self._undo_stack) > 100:
            self._undo_stack.pop(0)
        self._redo_stack.clear()

    def undo_last(self) -> bool:
        """Cofa ostatnią zmianę oznaczeń. Zwraca True, gdy coś cofnięto."""
        if not self._undo_stack:
            return False
        label, changes = self._undo_stack.pop()
        redo: list = []
        for index, field, previous in changes:
            if not (0 <= index < len(self.segments)):
                continue
            seg = self.segments[index]
            redo.append((index, field, getattr(seg, field, None)))
            setattr(seg, field, previous)
            self._update_row(index)
        self._redo_stack.append((label, redo))
        self.update_progress()
        self._save_quietly()
        self.status_message.emit(f"↶ Cofnięto: {label}")
        return True

    def redo_last(self) -> bool:
        """Ponawia cofniętą zmianę oznaczeń."""
        if not self._redo_stack:
            return False
        label, changes = self._redo_stack.pop()
        undo: list = []
        for index, field, value in changes:
            if not (0 <= index < len(self.segments)):
                continue
            seg = self.segments[index]
            undo.append((index, field, getattr(seg, field, None)))
            setattr(seg, field, value)
            self._update_row(index)
        self._undo_stack.append((label, undo))
        self.update_progress()
        self._save_quietly()
        self.status_message.emit(f"↷ Ponowiono: {label}")
        return True

    def _save_quietly(self) -> None:
        if self.app.project:
            try:
                self.app.save_translations(silent=True)
            except Exception:
                pass

    def set_status(self, indices: Sequence[int], status: str) -> int:
        """Ustawia status wielu segmentów naraz. Zwraca liczbę zmian.

        Wcześniej każde oznaczenie działało tylko na segmencie w edytorze —
        zaznaczenie dziesięciu wierszy zmieniało jeden.
        """
        if not indices:
            return 0
        self._store_current()
        changed = 0
        history: list = []
        for index in indices:
            if not (0 <= index < len(self.segments)):
                continue
            seg = self.segments[index]
            if seg.status == status:
                continue
            history.append((index, "status", seg.status))
            seg.status = status
            if status == "new":
                # „nowy” oznacza segment do zrobienia od początku
                seg.extra.pop("auto_excluded", None)
            changed += 1
            self._update_row(index)
        if changed:
            label = STATUS_LABELS.get(status, status)
            self._push_undo(f"oznaczenie „{label}” ({changed})", history)
            self.update_progress()
            self._save_quietly()
            self.status_message.emit(f"Oznaczono {changed} segmentów: {label}")
        return changed

    def mark_new(self) -> None:
        """Cofa segmenty do stanu „nowy” (do ponownego zrobienia)."""
        self.set_status(self.selected_indices(), "new")

    def mark_translated(self) -> None:
        self.set_status(self.selected_indices(), "translated")

    def mark_draft(self) -> None:
        self.set_status(self.selected_indices(), "draft")

    def selected_indices(self) -> List[int]:
        """Numery segmentów zaznaczonych w siatce (albo bieżący, gdy brak zaznaczenia)."""
        indices: List[int] = []
        model = self.grid.selectionModel()
        if model is not None:
            for row in model.selectedRows():
                item = self.grid.item(row.row(), 0)
                if item is not None:
                    index = item.data(Qt.ItemDataRole.UserRole)
                    if index is not None:
                        indices.append(int(index))
        if not indices and 0 <= self.current_index < len(self.segments):
            indices = [self.current_index]
        return sorted(set(indices))

    def toggle_ignore(self) -> None:
        """Pomija lub przywraca zaznaczone segmenty (działa też grupowo)."""
        indices = self.selected_indices()
        if not indices:
            return
        # Gdy w zaznaczeniu jest choć jeden aktywny segment – pomijamy wszystkie.
        # Dopiero gdy wszystkie są już pominięte, przywracamy je.
        make_ignored = any(not self.segments[i].ignored for i in indices)
        self.set_ignored(indices, make_ignored)

    def set_ignored(self, indices: Sequence[int], ignored: bool) -> int:
        """Ustawia stan „pominięty” dla wskazanych segmentów. Zwraca liczbę zmian."""
        changed = 0
        history: list = []
        for index in indices:
            if not (0 <= index < len(self.segments)):
                continue
            seg = self.segments[index]
            if seg.ignored == ignored:
                continue
            history.append((index, "ignored", seg.ignored))
            seg.ignored = ignored
            if isinstance(getattr(seg, "extra", None), dict):
                # Ręczna decyzja ma pierwszeństwo przed regułami — w OBIE strony:
                # „manual_skip” chroni przed przywróceniem, „manual_keep” przed
                # ponownym wykluczeniem przy następnym wczytaniu plików.
                seg.extra.pop("auto_excluded", None)
                if ignored:
                    seg.extra["manual_skip"] = True
                    seg.extra.pop("manual_keep", None)
                else:
                    seg.extra["manual_keep"] = True
                    seg.extra.pop("manual_skip", None)
            self._update_row(index)
            changed += 1
        if changed:
            word_label = "pominięcie" if ignored else "przywrócenie"
            self._push_undo(f"{word_label} ({changed})", history)
            self.update_progress()
            # Zapis od razu: decyzja ma przetrwać ponowne wczytanie plików (F5).
            self._save_quietly()
            word = "pominięto" if ignored else "przywrócono"
            self.status_message.emit(f"🚫 {word} {changed} segmentów")
        return changed

    def ignore_selected(self) -> None:
        self.set_ignored(self.selected_indices(), True)

    def restore_selected(self) -> None:
        self.set_ignored(self.selected_indices(), False)

    def restore_all_ignored(self) -> None:
        """Cofa pominięcie WSZYSTKICH segmentów w projekcie (także z reguł)."""
        indices = [i for i, s in enumerate(self.segments) if s.ignored]
        if not indices:
            self.status_message.emit("Brak pominiętych segmentów")
            return
        if QMessageBox.question(
            self, "Przywróć pominięte",
            f"Przywrócić {len(indices)} pominiętych segmentów?\n\n"
            "Wrócą do tłumaczenia i statystyk. Reguły wykluczania nie zabiorą "
            "ich ponownie, dopóki sam nie użyjesz „Zastosuj reguły wykluczania”.",
        ) != QMessageBox.StandardButton.Yes:
            return
        self.set_ignored(indices, False)

    def restore_ignored_in_file(self) -> None:
        """Cofa pominięcie w bieżącym pliku."""
        seg = self.current_segment()
        if seg is None:
            return
        name = seg.file_name or "(bez pliku)"
        indices = [i for i, s in enumerate(self.segments)
                   if (s.file_name or "(bez pliku)") == name and s.ignored]
        if not indices:
            self.status_message.emit(f"Brak pominiętych segmentów w „{name}”")
            return
        self.set_ignored(indices, False)

    def clear_manual_exclusion_decisions(self) -> None:
        """Kasuje ręczne wyjątki – reguły znów działają w pełni."""
        from ..core.exclusions import ExclusionSet

        cleared = ExclusionSet.clear_manual_decisions(self.segments)
        if not cleared:
            self.status_message.emit("Brak ręcznych wyjątków")
            return
        self.status_message.emit(f"Skasowano {cleared} ręcznych wyjątków")
        self.app.apply_exclusions()

    def ignore_untranslated_in_file(self) -> None:
        """Pomija wszystkie nieprzetłumaczone segmenty w bieżącym pliku."""
        seg = self.current_segment()
        if seg is None:
            return
        name = seg.file_name or "(bez pliku)"
        indices = [i for i, s in enumerate(self.segments)
                   if (s.file_name or "(bez pliku)") == name
                   and not s.is_translated and not s.ignored]
        if not indices:
            self.status_message.emit("Brak nieprzetłumaczonych segmentów w tym pliku")
            return
        if QMessageBox.question(
            self, "Pomiń segmenty",
            f"Pominąć {len(indices)} nieprzetłumaczonych segmentów z pliku „{name}”?",
        ) != QMessageBox.StandardButton.Yes:
            return
        self.set_ignored(indices, True)

    #: Tryby masowego oznaczania – opis dla okna „Oznacz pasujące…”.
    BULK_ACTIONS = [
        ("translated", "✓ oznacz jako PRZETŁUMACZONE"),
        ("approved", "★ oznacz jako ZATWIERDZONE"),
        ("ignored", "🚫 oznacz jako POMINIĘTE"),
        ("draft", "✎ oznacz jako ROBOCZE"),
    ]

    #: Gotowe wzorce – najczęstsze przypadki w plikach gier.
    BULK_PRESETS = [
        ("TM01-TM66", "range", "translated", "Zakres TM01–TM66 (nazwy maszyn)"),
        ("HM01-HM28", "range", "translated", "Zakres HM01–HM28 (ukryte maszyny)"),
        ("", "cjk", "ignored", "Teksty po japońsku / chińsku / koreańsku"),
    ]

    def bulk_mark_matching(self) -> None:
        """Masowe oznaczanie segmentów pasujących do wzorca.

        Jedno okno obsługuje trzy typowe zadania:

        * **zakres numerowany** — `TM01-TM66` obejmuje wszystkie 66 nazw naraz,
        * **znaki CJK** — segmenty pozostawione po japońsku/chińsku,
        * zwykły wzorzec z gwiazdką albo fragment tekstu.

        Wynik można od razu zapisać jako stałą regułę, żeby działał także po
        ponownym wczytaniu plików.
        """
        from ..core.exclusions import (CJK_PATTERN, ExclusionRule, contains_cjk,
                                       expand_ranges)

        dialog = QDialog(self)
        dialog.setWindowTitle("Oznacz pasujące segmenty")
        dialog.resize(560, 0)
        layout = QVBoxLayout(dialog)

        info = QLabel(
            "Oznacza wszystkie segmenty pasujące do wzorca — bez klikania po jednym.\n"
            "Przykłady: <code>TM01-TM66</code> (zakres), <code>&lt;&lt;&lt; FILE:*&gt;&gt;&gt;</code> "
            "(gwiazdka), albo znaki japońskie."
        )
        info.setTextFormat(Qt.TextFormat.RichText)
        info.setWordWrap(True)
        layout.addWidget(info)

        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel("Gotowe:"))
        preset_box = QComboBox()
        preset_box.addItem("— wpisz własny wzorzec —", None)
        for pattern, kind, status, label in self.BULK_PRESETS:
            preset_box.addItem(label, (pattern, kind, status))
        preset_row.addWidget(preset_box, 1)
        layout.addLayout(preset_row)

        pattern_row = QHBoxLayout()
        pattern_row.addWidget(QLabel("Wzorzec:"))
        pattern_edit = QLineEdit()
        pattern_edit.setPlaceholderText("np. TM01-TM66  albo  <<< FILE:*>>>")
        pattern_row.addWidget(pattern_edit, 1)
        layout.addLayout(pattern_row)

        kind_row = QHBoxLayout()
        kind_row.addWidget(QLabel("Dopasuj:"))
        kind_box = QComboBox()
        for key, label in (("auto", "automatycznie (zakres / gwiazdka / tekst)"),
                           ("range", "zakres numerowany (TM01-TM66)"),
                           ("wildcard", "wzorzec z gwiazdką (*)"),
                           ("contains", "zawiera tekst"),
                           ("cjk", "znaki japońskie / chińskie / koreańskie"),
                           ("regex", "wyrażenie regularne")):
            kind_box.addItem(label, key)
        kind_row.addWidget(kind_box, 1)
        layout.addLayout(kind_row)

        action_row = QHBoxLayout()
        action_row.addWidget(QLabel("Oznacz jako:"))
        action_box = QComboBox()
        for key, label in self.BULK_ACTIONS:
            action_box.addItem(label, key)
        action_row.addWidget(action_box, 1)
        layout.addLayout(action_row)

        copy_source = QCheckBox(
            "Wstaw tekst źródłowy jako tłumaczenie (dla nazw, które zostają bez zmian)")
        copy_source.setToolTip(
            "Przydatne przy nazwach typu TM01: segment ma być „gotowy”,\n"
            "a jego tłumaczenie to dokładnie ten sam tekst.")
        copy_source.setChecked(True)
        layout.addWidget(copy_source)

        found_label = QLabel("")
        found_label.setWordWrap(True)
        found_label.setStyleSheet("color: gray;")
        layout.addWidget(found_label)

        preview = QListWidget()
        preview.setMaximumHeight(180)
        layout.addWidget(preview)

        buttons = QHBoxLayout()
        save_rule = QCheckBox("zapisz jako stałą regułę wykluczania")
        save_rule.setToolTip(
            "Reguła zadziała automatycznie przy każdym wczytaniu plików.\n"
            "Dotyczy tylko oznaczenia „pominięte”.")
        buttons.addWidget(save_rule)
        buttons.addStretch(1)
        apply_btn = QPushButton("Oznacz")
        cancel_btn = QPushButton("Anuluj")
        buttons.addWidget(apply_btn)
        buttons.addWidget(cancel_btn)
        layout.addLayout(buttons)
        cancel_btn.clicked.connect(dialog.reject)

        def resolve_kind() -> str:
            kind = kind_box.currentData()
            if kind != "auto":
                return kind
            text = pattern_edit.text().strip()
            if not text:
                return "contains"
            if len(expand_ranges(text)) > 1:
                return "range"
            return "wildcard" if "*" in text else "contains"

        def find_indices() -> List[int]:
            kind = resolve_kind()
            text = pattern_edit.text().strip()
            if kind == "cjk":
                return [i for i, sg in enumerate(self.segments)
                        if contains_cjk(sg.source or "")]
            if not text:
                return []
            rule = ExclusionRule(text, kind, True, False)
            if rule.compiled() is None:
                return []
            return [i for i, sg in enumerate(self.segments)
                    if rule.matches(sg.source or "")]

        def refresh_preview() -> None:
            indices = find_indices()
            preview.clear()
            for index in indices[:200]:
                seg = self.segments[index]
                preview.addItem(f"{index + 1}. {(seg.source or '')[:90]}")
            kind = resolve_kind()
            extra = ""
            if kind == "range":
                names = expand_ranges(pattern_edit.text().strip())
                if len(names) > 1:
                    extra = f"  •  zakres obejmuje {len(names)} nazw"
            found_label.setText(f"Pasuje {len(indices)} segmentów{extra}")
            apply_btn.setEnabled(bool(indices))

        def on_preset(_index: int) -> None:
            data = preset_box.currentData()
            if not data:
                return
            pattern, kind, status = data
            pattern_edit.setText(pattern)
            kind_box.setCurrentIndex(
                next(i for i in range(kind_box.count())
                     if kind_box.itemData(i) == kind))
            action_box.setCurrentIndex(
                next(i for i in range(action_box.count())
                     if action_box.itemData(i) == status))
            refresh_preview()

        preset_box.currentIndexChanged.connect(on_preset)
        pattern_edit.textChanged.connect(lambda _t: refresh_preview())
        kind_box.currentIndexChanged.connect(lambda _i: refresh_preview())
        apply_btn.clicked.connect(dialog.accept)
        refresh_preview()

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        indices = find_indices()
        if not indices:
            return

        status = action_box.currentData()
        # Najpierw zrzucamy zawartość pola edycji do segmentu — inaczej
        # `set_status` zrobiłby to później i nadpisał świeżo wstawiony tekst
        # pustą treścią edytora (segment otwarty w edytorze tracił tłumaczenie).
        self._store_current()
        if copy_source.isChecked() and status in ("translated", "approved"):
            # Nazwy typu TM01 zostają bez zmian – wpisujemy je jako tłumaczenie,
            # żeby segment naprawdę był gotowy, a nie tylko oznaczony.
            for index in indices:
                seg = self.segments[index]
                if not (seg.target or "").strip():
                    seg.target = seg.source
            # Segment otwarty w edytorze: pole tekstowe musi pokazać nową treść,
            # zanim kolejne `_store_current()` odczyta z niego pustkę.
            current_index = self.current_index
            if current_index in set(indices) and 0 <= current_index < len(self.segments):
                self.set_target_text(self.segments[current_index].target)

        if status == "ignored":
            changed = self.set_ignored(indices, True)
        else:
            changed = self.set_status(indices, status)

        if save_rule.isChecked() and status == "ignored":
            kind = resolve_kind()
            pattern = (CJK_PATTERN if kind == "cjk"
                       else pattern_edit.text().strip())
            rule = ExclusionRule(pattern, "regex" if kind == "cjk" else kind,
                                 comment="dodane z edytora")
            self.app.exclusion_set().rules.append(rule)
            self.app.save_exclusions()

        self.refresh_grid()
        self.update_progress()
        QMessageBox.information(
            self, "Oznacz pasujące segmenty",
            f"Oznaczono {changed} segmentów jako "
            f"{dict(self.BULK_ACTIONS).get(status, status)}.")

    def ignore_matching(self) -> None:
        """Pomija segmenty pasujące do wpisanego wzorca (jak filtr siatki)."""
        from ..core.textutil import find_matches

        text, ok = QInputDialog.getText(
            self, "Pomiń pasujące segmenty",
            "Pomiń segmenty, których ŹRÓDŁO zawiera:\n"
            "(gwiazdka * zastępuje dowolny ciąg, np. „<<< FILE:*>>>”)")
        if not ok or not text.strip():
            return
        pattern = text.strip()
        indices = []
        for i, seg in enumerate(self.segments):
            if seg.ignored:
                continue
            source = seg.source or ""
            if "*" in pattern:
                import re as _re
                regex = ".*".join(_re.escape(p) for p in pattern.split("*"))
                if _re.search(regex, source, _re.IGNORECASE):
                    indices.append(i)
            elif find_matches(source, pattern, ignore_codes=True):
                indices.append(i)
        if not indices:
            QMessageBox.information(self, "Pomiń segmenty", "Nic nie pasuje do wzorca.")
            return
        if QMessageBox.question(
            self, "Pomiń segmenty",
            f"Znaleziono {len(indices)} pasujących segmentów.\n\nPominąć je?",
        ) != QMessageBox.StandardButton.Yes:
            return
        count = self.set_ignored(indices, True)
        if count and QMessageBox.question(
            self, "Zapisz jako regułę",
            "Zapisać ten wzorzec jako stałą regułę wykluczania?\n"
            "(będzie działać automatycznie przy każdym wczytaniu plików)",
        ) == QMessageBox.StandardButton.Yes:
            from ..core.exclusions import ExclusionRule

            rule = ExclusionRule(pattern, "wildcard" if "*" in pattern else "contains",
                                 comment="dodane z edytora")
            self.app.exclusion_set().rules.append(rule)
            self.app.save_exclusions()
            if hasattr(self.app.settings_tab, "load_exclusions"):
                self.app.settings_tab.load_exclusions()
            self.status_message.emit("Dodano regułę wykluczania")

    def adapt_codes_selected(self) -> None:
        """Dopasowuje znaczniki (\\n/\\l/\\p) tłumaczenia do oryginału.

        Działa na zaznaczonych wierszach siatki (albo bieżącym segmencie).
        Tłumaczenie przełamuje się w zbliżonych miejscach co tekst źródłowy —
        dzięki temu w grze linie mają zbliżoną szerokość jak w oryginale.
        """
        from ..core.tags import adapt_codes

        self._store_current()
        indices = self.selected_indices()
        if not indices:
            return
        changed = 0
        history: list = []
        for index in indices:
            if not (0 <= index < len(self.segments)):
                continue
            seg = self.segments[index]
            if seg.ignored or not (seg.target or "").strip():
                continue
            new_text = adapt_codes(seg.source, seg.target)
            if new_text != seg.target:
                history.append((index, "target", seg.target))
                seg.target = new_text
                changed += 1
                self._update_row(index)
        if not changed:
            self.status_message.emit("Znaczniki już pasują do oryginału")
            return
        # Segment otwarty w edytorze musi od razu pokazać nową treść, bo
        # kolejne _store_current() odczyta tekst prosto z pola.
        if self.current_index in set(indices) and 0 <= self.current_index < len(self.segments):
            self.set_target_text(self.segments[self.current_index].target)
        self._push_undo(f"dopasowanie znaczników ({changed})", history)
        self.update_progress()
        self._save_quietly()
        self.status_message.emit(f"⇢ Dopasowano znaczniki do oryginału: {changed} segmentów")

    def _update_row(self, index: int) -> None:
        for row in range(self.grid.rowCount()):
            item = self.grid.item(row, 0)
            if item and item.data(Qt.ItemDataRole.UserRole) == index:
                seg = self.segments[index]
                self._loading = True
                marks_cfg = marker_settings()
                target_item = self.grid.item(row, 2)
                target_item.setText(display_text(seg.target or "", **marks_cfg))
                _set_whitespace_hint(target_item, seg.target or "", marks_cfg)
                status_key = "ignored" if seg.ignored else (
                    seg.status if seg.status in STATUS_LABELS else ("translated" if seg.is_translated else "new")
                )
                self.grid.item(row, 3).setText(STATUS_LABELS.get(status_key, status_key))
                bg = QColor(
                    self.colors.ignored_bg if seg.ignored else
                    self.colors.approved_bg if seg.status == "approved" else
                    self.colors.translated_bg if seg.is_translated else
                    self.colors.untranslated_bg
                )
                fg = QColor(self.colors.row_fg)
                for col in range(4):
                    if self.grid.item(row, col):
                        self.grid.item(row, col).setBackground(bg)
                        self.grid.item(row, col).setForeground(fg)
                self._loading = False
                return

    # ----------------------------------------------------------- edytory
    def _on_target_changed(self) -> None:
        if self._loading or not (0 <= self.current_index < len(self.segments)):
            return
        # odśwież podświetlenie wcięcia (użytkownik mógł je skasować lub dopisać)
        self._ws_timer.start(150)
        _settings = SettingsManager.instance()
        if (_settings.get_bool("lang.check.enabled", True)
                and _settings.get_bool("lang.check.auto", True)):
            self._lang_timer.start(900)
        seg = self.segments[self.current_index]
        seg.target = self.target_edit.toPlainText()
        if seg.target.strip() and seg.status in ("new", ""):
            seg.status = "draft"
        self._update_row(self.current_index)
        self.update_progress()

    def _on_notes_changed(self) -> None:
        if self._loading or not (0 <= self.current_index < len(self.segments)):
            return
        self.segments[self.current_index].notes = self.notes_edit.toPlainText()

    def set_target_text(self, text: str) -> None:
        if not text:
            return
        # Podpowiedzi z TM/MT wracają przycięte, a w pliku źródłowym wiodąca
        # spacja bywa istotna (wcięcie wiersza dialogu w grze) – przenosimy ją.
        if SettingsManager.instance().get_bool("segment.keep.edge.spaces", True):
            seg = self.current_segment()
            if seg is not None:
                text = copy_edge_whitespace(seg.source, text)
        self.target_edit.setPlainText(text)
        self._on_target_changed()

    def copy_source_to_target(self) -> None:
        self.set_target_text(self.source_edit.toPlainText())

    def clear_target(self) -> None:
        self.target_edit.clear()

    def current_segment(self) -> Optional[Segment]:
        if 0 <= self.current_index < len(self.segments):
            return self.segments[self.current_index]
        return None

    # -------------------------------------------------------- TM / terminy
    def _refresh_helpers(self) -> None:
        """Uruchamia wyszukiwanie w TM w tle – interfejs pozostaje responsywny."""
        self._refresh_terms()

        if not SettingsManager.instance().get_bool("tm.lookup.enabled", True):
            # Podpowiedzi wyłączone w Ustawieniach – nie ruszamy pamięci wcale.
            self.matches_list.clear()
            self.sentence_list.clear()
            self.matches_info.setText("Podpowiedzi z pamięci TM wyłączone w Ustawieniach")
            return

        seg = self.current_segment()
        tm = self.app.tm
        if not seg or not tm.is_initialized:
            self.matches_list.clear()
            self.sentence_list.clear()
            self.matches_info.setText("Brak pamięci TM (otwórz projekt)")
            self.sentence_info.setText("Brak pamięci TM")
            return

        # przerwij poprzednie szukanie – wynik i tak jest już nieaktualny
        if self._lookup_worker is not None and self._lookup_worker.isRunning():
            self._lookup_worker.cancel()

        settings = SettingsManager.instance()

        # Segmenty przetłumaczone w tej sesji traktujemy jak pamięć „w locie”.
        # Dokładamy TYLKO te, które zmieniły się od ostatniego razu – przeglądanie
        # wszystkich segmentów przy każdym ruchu zamrażało program w dużych projektach.
        if settings.get_bool("tm.sentence.use.translated", False):
            volatile = []
            for i, sg in enumerate(self.segments):
                if i == self.current_index or sg.ignored or not sg.is_translated:
                    continue
                stamp = (sg.source, sg.target)
                if self._volatile_sent.get(i) == stamp:
                    continue
                self._volatile_sent[i] = stamp
                volatile.append(stamp)
            if volatile:
                tm.add_volatile_pairs(volatile)
        self.matches_info.setText("⏳ Szukanie dopasowań…")
        if settings.get_bool("tm.sentence.matching.enabled", False):
            self.sentence_info.setText("⏳ Szukanie fragmentów zdań…")
        else:
            self.sentence_list.clear()
            self.sentence_info.setText(
                "Dopasowanie zdań jest wyłączone — włącz w Ustawieniach → Pamięć TM"
            )
        worker = TMLookupWorker(
            tm, seg.source, self.current_index,
            settings.get_int("fuzzy.threshold", 70),
            settings.get_int("tm.max.results", 10),
            settings.get_bool("tm.sentence.matching.enabled", False),
            parent=self,
        )
        worker.finished_lookup.connect(self._on_lookup_ready)
        self._lookup_worker = worker
        self._pending_lookup_index = self.current_index
        self._lookup_started_at = _time.perf_counter()
        worker.start()

    def _on_lookup_ready(self, index: int, matches: list, sentences: list,
                         timing: dict | None = None) -> None:
        """Odbiera wyniki z wątku roboczego (odrzuca spóźnione)."""
        if index != self.current_index:
            return  # użytkownik zdążył przejść dalej
        self._lookup_worker = None
        # dostrój opóźnienie do realnego czasu wyszukiwania
        started = getattr(self, "_lookup_started_at", None)
        if started is not None:
            self._last_lookup_ms = (_time.perf_counter() - started) * 1000
            self._tm_debounce_ms = int(min(400, max(60, self._last_lookup_ms * 1.5)))
        self._show_matches(matches)
        self._show_sentence_matches(sentences)
        self._last_timing = timing or {}
        self._update_timing_label()

    def _show_matches(self, matches: List[TranslationMatch]) -> None:
        self.matches_list.clear()
        tm = self.app.tm
        threshold = SettingsManager.instance().get_int("fuzzy.threshold", 70)
        if not matches:
            self.matches_info.setText(f"Brak dopasowań ≥ {threshold}%  (TM: {tm.size()} wpisów)")
            return
        self.matches_info.setText(
            f"Znaleziono {len(matches)} dopasowań (najlepsze {matches[0].similarity}%)"
        )
        for match in matches:
            item = QListWidgetItem(
                f"[{match.similarity}%] {match.text}\n        źródło TM: {match.original_source}"
            )
            item.setData(Qt.ItemDataRole.UserRole, match.text)
            if match.similarity >= 95:
                item.setForeground(QColor("#ffd54f"))
            elif match.similarity >= 85:
                item.setForeground(QColor("#81c784"))
            self.matches_list.addItem(item)

        seg = self.current_segment()
        settings = SettingsManager.instance()
        may_overwrite = settings.get_bool("auto.insert.overwrite", False)
        if (
            seg is not None
            and settings.get_bool("auto.insert.enabled", True)
            and (may_overwrite or not (seg.target or "").strip())
            and matches[0].similarity >= settings.get_int("auto.insert.threshold", 80)
        ):
            self.set_target_text(matches[0].text)
            self.info_label.setText(f"✅ Auto-wstawiono dopasowanie {matches[0].similarity}%")

    def _show_sentence_matches(self, sentences: List[SentenceMatch]) -> None:
        settings = SettingsManager.instance()
        if not settings.get_bool("tm.sentence.matching.enabled", False):
            return
        self.sentence_list.clear()
        if not sentences:
            self.sentence_info.setText("Brak pasujących fragmentów zdań")
            return
        self.sentence_info.setText(f"Znaleziono {len(sentences)} fragmentów zdań w TM")
        for match in sentences:
            if match.line_pairs:
                # rozbicie linia po linii – najczytelniejsza postać dla plików gier
                lines = "\n".join(
                    f"      {src}\n          → {tgt}" for src, tgt in match.line_pairs
                )
                text = (
                    f"[{match.label}]\n"
                    f"{lines}\n"
                    f"      ⤵ całość: {match.assembled}"
                )
            else:
                label = "złożenie z kilku fragmentów" if " + " in match.fragment_source else "fragment z TM"
                text = (
                    f"[{match.label}] {match.assembled}\n"
                    f"      {label}: {match.fragment_source} → {match.fragment_target}"
                )
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, match.assembled)
            if getattr(match, "partial", False):
                # Złożenie zostawia tekst źródłowy — na pomarańczowo, żeby nie
                # dało się go wziąć za gotowe tłumaczenie.
                item.setForeground(QColor("#ffb74d"))
                item.setToolTip(
                    "W tej propozycji została część tekstu źródłowego "
                    "(podmieniono tylko znaleziony fragment).")
            elif match.coverage >= 60:
                item.setForeground(QColor("#81c784"))
            self.sentence_list.addItem(item)

        # automatyczne wstawienie najlepszego złożenia do pustego segmentu
        seg = self.current_segment()
        if (
            seg is not None
            and settings.get_bool("tm.sentence.auto.insert", False)
            and not (seg.target or "").strip()
            and sentences[0].coverage >= settings.get_int("tm.sentence.auto.threshold", 90)
            # Nigdy nie wstawiamy automatycznie propozycji, w której został
            # angielski — to trafiłoby do pliku wynikowego niezauważone.
            and not getattr(sentences[0], "partial", False)
        ):
            self.set_target_text(sentences[0].assembled)
            self.info_label.setText(
                f"🔗 Auto-wstawiono złożenie zdań ({sentences[0].coverage}%)"
            )

    def _insert_sentence_match(self, item: QListWidgetItem) -> None:
        self.set_target_text(item.data(Qt.ItemDataRole.UserRole))

    def _insert_selected_sentence_match(self) -> None:
        item = self.sentence_list.currentItem()
        if item:
            self.set_target_text(item.data(Qt.ItemDataRole.UserRole))

    def _insert_selected_match(self) -> None:
        item = self.matches_list.currentItem()
        if item:
            self.set_target_text(item.data(Qt.ItemDataRole.UserRole))

    def _insert_match(self, item: QListWidgetItem) -> None:
        self.set_target_text(item.data(Qt.ItemDataRole.UserRole))

    def _insert_best_match(self) -> None:
        if self.matches_list.count():
            self.set_target_text(self.matches_list.item(0).data(Qt.ItemDataRole.UserRole))

    def _refresh_terms(self) -> None:
        self.terms_list.clear()
        seg = self.current_segment()
        glossary = self.app.glossary
        if not seg or not glossary.entries:
            return
        for term in glossary.find_terms(seg.source):
            desc = f"  – {term.description}" if term.description else ""
            item = QListWidgetItem(f"{term.source} → {term.target}{desc}")
            item.setData(Qt.ItemDataRole.UserRole, term.target)
            self.terms_list.addItem(item)

    def _insert_term(self, item: QListWidgetItem) -> None:
        cursor = self.target_edit.textCursor()
        cursor.insertText(item.data(Qt.ItemDataRole.UserRole))
        self.target_edit.setFocus()

    def _highlight_terms(self) -> None:
        """Podświetla terminy glosariusza w polu źródłowym."""
        self._term_selections = []
        if not SettingsManager.instance().get_bool("glossary.highlight", True):
            self._apply_source_selections()
            return
        seg = self.current_segment()
        if not seg or not self.app.glossary.entries:
            self._apply_source_selections()
            return
        doc_text = self.source_edit.toPlainText().lower()
        fmt = QTextCharFormat()
        fmt.setBackground(QColor("#7e5b1f" if self.colors.dark else "#fff59d"))
        for term in self.app.glossary.find_terms(seg.source):
            start = doc_text.find(term.source.lower())
            while start >= 0:
                self._term_selections.append(
                    self._selection(self.source_edit, start, start + len(term.source), fmt))
                start = doc_text.find(term.source.lower(), start + 1)
        self._apply_source_selections()

    @staticmethod
    def _selection(editor, start: int, end: int, fmt) -> "QTextEdit.ExtraSelection":
        cursor = editor.textCursor()
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        selection = QTextEdit.ExtraSelection()
        selection.cursor = cursor
        selection.format = fmt
        return selection

    def _apply_source_selections(self) -> None:
        """Skleja wszystkie podświetlenia pola źródłowego w jedną listę.

        Kolejność ma znaczenie: spacje najpierw, żeby trafienia wyszukiwania
        i terminy glosariusza rysowały się na wierzchu.
        """
        self.source_edit.setExtraSelections(
            list(self._ws_source_selections)
            + list(self._term_selections)
            + list(self._search_source_selections))

    def _apply_target_selections(self) -> None:
        self.target_edit.setExtraSelections(
            list(self._ws_target_selections)
            + list(self._lang_selections)
            + list(self._search_target_selections))

    # ------------------------------------------------- widoczność spacji
    def highlight_whitespace(self) -> None:
        """Zaznacza kolorem spacje na brzegach segmentu w obu polach.

        Sama kropka `·` w siatce jest mało widoczna, a w polu tłumaczenia nie ma
        jej wcale (tam trzeba widzieć prawdziwy tekst, bo się go edytuje).
        Dlatego wcięcie dostaje wyraźne, kolorowe tło:

        * fioletowe – wcięcie zgodne ze źródłem,
        * czerwonawe – w źródle wcięcie jest, a w tłumaczeniu go brakuje
          (miejsce, gdzie POWINNA być spacja, jest zaznaczone na początku tekstu).
        """
        self._ws_source_selections = []
        self._ws_target_selections = []
        if not SettingsManager.instance().get_bool("ui.whitespace.highlight", True):
            self._apply_source_selections()
            self._apply_target_selections()
            return

        seg = self.current_segment()
        if seg is None:
            self._apply_source_selections()
            self._apply_target_selections()
            return

        fmt = QTextCharFormat()
        fmt.setBackground(QColor(self.colors.whitespace_bg))
        warn = QTextCharFormat()
        warn.setBackground(QColor(self.colors.whitespace_missing_bg))
        warn.setUnderlineStyle(QTextCharFormat.UnderlineStyle.WaveUnderline)
        warn.setUnderlineColor(QColor("#ff5252"))

        src = seg.source or ""
        tgt = self.target_edit.toPlainText()
        s_lead, _core, s_trail = split_edges(src)
        t_lead, t_core, t_trail = split_edges(tgt)

        if s_lead:
            self._ws_source_selections.append(
                self._selection(self.source_edit, 0, len(s_lead), fmt))
        if s_trail:
            self._ws_source_selections.append(
                self._selection(self.source_edit, len(src) - len(s_trail), len(src), fmt))

        if t_lead:
            self._ws_target_selections.append(
                self._selection(self.target_edit, 0, len(t_lead), fmt))
        elif s_lead and t_core:
            # brakuje wcięcia – zaznacz pierwszy znak jako ostrzeżenie
            self._ws_target_selections.append(
                self._selection(self.target_edit, 0, 1, warn))
        if t_trail:
            self._ws_target_selections.append(
                self._selection(self.target_edit, len(tgt) - len(t_trail), len(tgt), fmt))

        self._apply_source_selections()
        self._apply_target_selections()

    def restore_source_indent(self) -> None:
        """Nadaje tłumaczeniu takie wcięcie, jakie ma źródło (przycisk / Ctrl+Alt+W)."""
        seg = self.current_segment()
        if seg is None:
            return
        current = self.target_edit.toPlainText()
        if not current.strip():
            self.status_message.emit("Najpierw wpisz tłumaczenie")
            return
        fixed = copy_edge_whitespace(seg.source, current)
        if fixed == current:
            self.status_message.emit("Spacje na brzegach już zgadzają się ze źródłem")
            return
        cursor_pos = self.target_edit.textCursor().position()
        self.target_edit.setPlainText(fixed)
        cursor = self.target_edit.textCursor()
        cursor.setPosition(min(len(fixed), cursor_pos + (len(fixed) - len(current))))
        self.target_edit.setTextCursor(cursor)
        self._on_target_changed()
        self.status_message.emit("Przywrócono wcięcie ze źródła")

    def highlight_search(self, needle: str, options=None, where: str = "źródło") -> None:
        """Podświetla trafienia wyszukiwania w źródle i tłumaczeniu.

        Wywoływane z zakładki „Znajdź i zamień” po przejściu do segmentu –
        użytkownik od razu widzi, GDZIE w segmencie jest szukany wyraz, także
        gdy fraza jest przełamana znacznikiem `\n`.
        """
        self._search_source_selections = []
        self._search_target_selections = []
        self._search_needle = needle or ""
        target_selections = []
        if not needle:
            self._apply_source_selections()
            self._apply_target_selections()
            return

        kwargs = options.as_kwargs() if options is not None else {}
        fmt = QTextCharFormat()
        fmt.setBackground(QColor("#8d6e00" if self.colors.dark else "#ffe082"))
        fmt_active = QTextCharFormat()
        fmt_active.setBackground(QColor("#c77800" if self.colors.dark else "#ffb300"))

        seg = self.current_segment()
        if seg is None:
            return
        try:
            src_spans = find_matches(seg.source or "", needle, **kwargs)
            tgt_spans = find_matches(seg.target or "", needle, **kwargs)
        except Exception:
            return
        for i, (s, e) in enumerate(src_spans):
            style = fmt_active if (where == "źródło" and i == 0) else fmt
            self._search_source_selections.append(self._selection(self.source_edit, s, e, style))
        for i, (s, e) in enumerate(tgt_spans):
            style = fmt_active if (where == "tłumaczenie" and i == 0) else fmt
            target_selections.append(self._selection(self.target_edit, s, e, style))

        self._search_target_selections = target_selections
        self._apply_source_selections()
        self._apply_target_selections()

        # przewiń do pierwszego trafienia we wskazanym polu
        spans = src_spans if where == "źródło" else tgt_spans
        editor = self.source_edit if where == "źródło" else self.target_edit
        if spans:
            cursor = editor.textCursor()
            cursor.setPosition(spans[0][0])
            editor.setTextCursor(cursor)
            editor.ensureCursorVisible()

    def clear_search_highlight(self) -> None:
        self._search_source_selections = []
        self._search_target_selections = []
        self._search_needle = ""
        self._apply_source_selections()
        self._apply_target_selections()

    # ------------------------------------------------- kontrola języka
    def _toggle_lang_auto(self, enabled: bool) -> None:
        SettingsManager.instance().set("lang.check.auto", bool(enabled))
        if enabled:
            self.check_language()
        else:
            self.lang_list.clear()
            self.lang_status.setText("Kontrola na bieżąco wyłączona")

    def _toggle_lang_lt(self, enabled: bool) -> None:
        SettingsManager.instance().set("lang.check.languagetool", bool(enabled))
        self.check_language(force=True)

    def check_language(self, force: bool = False) -> None:
        """Sprawdza poprawność językową TŁUMACZENIA bieżącego segmentu."""
        # Główny wyłącznik sprawdzamy PIERWSZY i od razu zatrzymujemy wątek
        # w locie – inaczej wynik poprzedniego sprawdzenia nadpisywał komunikat
        # o wyłączeniu i wyglądało to tak, jakby przełącznik nie działał.
        settings_now = SettingsManager.instance()
        if not settings_now.get_bool("lang.check.enabled", True):
            if self._lang_worker is not None:
                self._lang_worker.cancel()
                self._lang_worker = None
            self._lang_issues = []
            self.lang_list.clear()
            self.clear_language_highlight()
            self.lang_status.setText("Kontrola języka wyłączona w Ustawieniach")
            return

        text = self.target_edit.toPlainText()
        if not text.strip():
            self._lang_issues = []
            self.lang_list.clear()
            self.clear_language_highlight()
            self.lang_status.setText("Brak tłumaczenia do sprawdzenia")
            return
        if not force and not settings_now.get_bool("lang.check.auto", True):
            return

        settings = SettingsManager.instance()
        use_lt = settings.get_bool("lang.check.languagetool", False)
        # adres serwera można zmienić w Ustawieniach bez restartu programu
        custom_url = settings.get("lang.check.url", "") or None
        if custom_url and self._lang_client.url != custom_url:
            self._lang_client = LanguageToolClient(url=custom_url)
        if self._lang_worker is not None:
            self._lang_worker.cancel()
        self.lang_status.setText("⏳ Sprawdzanie…" if use_lt else "Sprawdzanie…")

        worker = LangCheckWorker(
            text, self.current_index,
            dictionary=self.app.dictionary,
            use_languagetool=use_lt,
            client=self._lang_client,
            parent=self,
        )
        worker.finished_check.connect(self._on_language_checked)
        self._lang_worker = worker
        worker.start()

    def _on_language_checked(self, index: int, issues: list, error: str) -> None:
        self._lang_worker = None
        if index != self.current_index:
            return          # użytkownik zdążył przejść dalej
        if not SettingsManager.instance().get_bool("lang.check.enabled", True):
            return          # moduł wyłączono w trakcie sprawdzania
        self._lang_issues = issues
        self.highlight_language_issues(issues)
        self.lang_list.clear()
        for issue in issues:
            label = {"błąd": "❌", "ostrzeżenie": "⚠️", "info": "ℹ️"}.get(issue.severity, "•")
            item = QListWidgetItem(f"{label} {issue.describe()}")
            item.setData(Qt.ItemDataRole.UserRole, issue)
            if issue.suggestions and issue.offset >= 0:
                item.setToolTip("Kliknij dwukrotnie, aby wstawić: " + issue.suggestions[0])
            self.lang_list.addItem(item)
        # Propozycje pisowni liczymy dopiero teraz, w osobnym wątku – Hunspell
        # potrzebuje ok. sekundy na wyraz, a podkreślenia mają być natychmiast.
        if self._suggest_worker is not None:
            self._suggest_worker.cancel()
        if any(i.rule_id == "PISOWNIA" and not i.suggestions for i in issues):
            suggester = SuggestionWorker(issues, self.app.dictionary, index, parent=self)
            suggester.finished_suggestions.connect(self._on_suggestions_ready)
            self._suggest_worker = suggester
            suggester.start()

        status = summarize_lang(issues)
        dictionary = self.app.dictionary
        if not dictionary.is_initialized:
            status += ("   •   ⚠️ brak słownika – pisownia NIE jest sprawdzana "
                       "(Słowniki → „⬇ Pobierz słownik…”)")
        elif dictionary.size < MIN_DICT_FOR_SPELL:
            status += (f"   •   ⚠️ słownik ma tylko {dictionary.size} słów – "
                       f"pisownia sprawdzana od {MIN_DICT_FOR_SPELL}")
        elif not dictionary.has_morphology and dictionary.size < 1_000_000:
            status += ("   •   ⚠️ słownik zna tylko formy podstawowe – pobierz "
                       "„polski – pełna odmiana (SJP.pl)” w zakładce Słowniki")
        if error:
            status += f"   ({error})"
        self.lang_status.setText(status)

    def highlight_language_issues(self, issues) -> None:
        """Podkreśla błędy WPROST w polu tłumaczenia — jak w edytorze tekstu.

        Czerwona falka = błąd lub pisownia, pomarańczowa = ostrzeżenie,
        niebieska kropkowana = uwaga. Bez tego uwagi były widoczne wyłącznie
        na liście obok i trudno było znaleźć, którego wyrazu dotyczą.
        """
        self._lang_selections = []
        if not SettingsManager.instance().get_bool("lang.check.underline", True):
            self._apply_target_selections()
            return

        text = self.target_edit.toPlainText()
        styles = {
            "błąd": ("#ff5252", QTextCharFormat.UnderlineStyle.WaveUnderline),
            "ostrzeżenie": ("#ffa726", QTextCharFormat.UnderlineStyle.WaveUnderline),
            "info": ("#64b5f6", QTextCharFormat.UnderlineStyle.DotLine),
        }
        for issue in issues or []:
            start, length = issue.offset, issue.length
            if start < 0 or length <= 0:
                # Uwagi bez pozycji (np. pisownia ze słownika) – znajdź wyraz w tekście.
                if not issue.fragment:
                    continue
                found = re.search(rf"(?<!\w){re.escape(issue.fragment)}(?!\w)", text)
                if not found:
                    continue
                start, length = found.start(), found.end() - found.start()
            if start + length > len(text):
                continue
            color, style = styles.get(issue.severity, styles["info"])
            fmt = QTextCharFormat()
            fmt.setUnderlineStyle(style)
            fmt.setUnderlineColor(QColor(color))
            fmt.setToolTip(issue.describe())
            self._lang_selections.append(
                self._selection(self.target_edit, start, start + length, fmt))
        self._apply_target_selections()

    def _on_suggestions_ready(self, index: int, issues: list) -> None:
        """Uzupełnia listę uwag o doliczone w tle propozycje."""
        self._suggest_worker = None
        if index != self.current_index:
            return
        self._lang_issues = issues
        for row in range(self.lang_list.count()):
            item = self.lang_list.item(row)
            issue = item.data(Qt.ItemDataRole.UserRole)
            if issue is None:
                continue
            label = {"błąd": "❌", "ostrzeżenie": "⚠️", "info": "ℹ️"}.get(issue.severity, "•")
            item.setText(f"{label} {issue.describe()}")
            if issue.suggestions:
                item.setToolTip("Kliknij dwukrotnie, aby wstawić: " + issue.suggestions[0])

    def clear_language_highlight(self) -> None:
        """Zdejmuje podkreślenia błędów językowych z pola tłumaczenia."""
        self._lang_selections = []
        self._apply_target_selections()

    def _target_context_menu(self, pos) -> None:
        """Prawy przycisk w polu tłumaczenia – propozycje poprawek dla wyrazu."""
        menu = self.target_edit.createStandardContextMenu()
        cursor = self.target_edit.cursorForPosition(pos)
        offset = cursor.position()

        matching = [
            issue for issue in self._lang_issues
            if issue.offset >= 0 and issue.offset <= offset <= issue.offset + issue.length
        ]
        if not matching:
            cursor.select(QTextCursor.SelectionType.WordUnderCursor)
            word = cursor.selectedText().strip()
            matching = [i for i in self._lang_issues if i.fragment == word]

        if matching:
            issue = matching[0]
            menu.addSeparator()
            header = menu.addAction(f"🔤 {issue.message[:60]}")
            header.setEnabled(False)
            suggestions = list(issue.suggestions)
            if not suggestions and issue.fragment:
                # Jeszcze nie doliczone – bierzemy SZYBKĄ ścieżkę (~0,1 s),
                # żeby menu otworzyło się od razu, a nie po trzech sekundach.
                QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
                try:
                    suggestions = self.app.dictionary.suggest_corrections(
                        issue.fragment, 6, fast=True)
                    issue.suggestions = suggestions
                except TypeError:
                    suggestions = self.app.dictionary.suggest_corrections(issue.fragment, 6)
                finally:
                    QApplication.restoreOverrideCursor()
            for suggestion in suggestions[:6]:
                action = menu.addAction(f"✏️  {suggestion}")
                action.triggered.connect(
                    lambda _checked=False, i=issue, sgt=suggestion:
                    self._replace_issue(i, sgt))
            if not suggestions:
                none_action = menu.addAction("(brak propozycji)")
                none_action.setEnabled(False)
            if issue.fragment:
                menu.addSeparator()
                add_action = menu.addAction(f"➕ Dodaj „{issue.fragment}” do słownika")
                add_action.triggered.connect(lambda _c=False, wrd=issue.fragment:
                                             self.add_word_to_dictionary(wrd))
        menu.exec(self.target_edit.viewport().mapToGlobal(pos))

    def _replace_issue(self, issue, replacement: str) -> None:
        """Podmienia fragment wskazany przez uwagę na wybraną propozycję."""
        text = self.target_edit.toPlainText()
        start, length = issue.offset, issue.length
        if start < 0 or length <= 0:
            found = re.search(rf"(?<!\w){re.escape(issue.fragment)}(?!\w)", text)
            if not found:
                return
            start, length = found.start(), found.end() - found.start()
        if start + length > len(text):
            return
        self.target_edit.setPlainText(text[:start] + replacement + text[start + length:])
        self._on_target_changed()
        self.status_message.emit(f"Poprawiono: „{issue.fragment}” → „{replacement}”")
        self.check_language(force=True)

    def add_word_to_dictionary(self, word: str) -> None:
        """Dopisuje wyraz do słownika użytkownika (plik `uzytkownika.txt`)."""
        word = (word or "").strip()
        if not word or not self.app.project:
            return
        folder = self.app.project.dictionary_path
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, "uzytkownika.txt")
        try:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(word + "\n")
        except Exception as exc:
            QMessageBox.warning(self, "Słownik", f"Nie udało się zapisać:\n{exc}")
            return
        self.app.dictionary.words.add(word.lower())
        self.app.dictionary_tab.refresh()
        self.status_message.emit(f"Dodano „{word}” do słownika użytkownika")
        self.check_language(force=True)

    def _apply_lang_suggestion(self, item: QListWidgetItem) -> None:
        """Dwuklik na uwadze wstawia proponowaną poprawkę."""
        issue = item.data(Qt.ItemDataRole.UserRole)
        if issue is None or not issue.suggestions or issue.offset < 0 or issue.length <= 0:
            return
        text = self.target_edit.toPlainText()
        end = issue.offset + issue.length
        if end > len(text):
            return
        fixed = text[:issue.offset] + issue.suggestions[0] + text[end:]
        self.target_edit.setPlainText(fixed)
        self._on_target_changed()
        self.status_message.emit(f"Poprawiono: „{issue.fragment}” → „{issue.suggestions[0]}”")
        self.check_language(force=True)

    def apply_language_fixes(self) -> None:
        """Wstawia wszystkie jednoznaczne propozycje naraz."""
        if not self._lang_issues:
            self.status_message.emit("Brak propozycji do zastosowania")
            return
        text = self.target_edit.toPlainText()
        fixed, count = apply_first_suggestions(text, self._lang_issues)
        if not count:
            self.status_message.emit("Żadna uwaga nie ma gotowej propozycji")
            return
        self.target_edit.setPlainText(fixed)
        self._on_target_changed()
        self.status_message.emit(f"Zastosowano {count} poprawek językowych")
        self.check_language(force=True)

    def find_selected_word(self, scope: str | None = None) -> None:
        """Szuka zaznaczonego (lub bieżącego) wyrazu w projekcie – Ctrl+Shift+F."""
        text = self.source_edit.textCursor().selectedText().strip()
        if not text:
            text = self.target_edit.textCursor().selectedText().strip()
        if not text:
            cursor = self.source_edit.textCursor()
            cursor.select(QTextCursor.SelectionType.WordUnderCursor)
            text = cursor.selectedText().strip()
        if not text:
            self.status_message.emit("Zaznacz wyraz, aby go wyszukać (Ctrl+Shift+F)")
            return
        self.app.tabs.setCurrentWidget(self.app.search_tab)
        self.app.search_tab.search_for(text, scope)

    def _add_selection_to_glossary(self) -> None:
        source_term = self.source_edit.textCursor().selectedText().strip()
        target_term = self.target_edit.textCursor().selectedText().strip()
        if not source_term or not target_term:
            QMessageBox.information(
                self, "Glosariusz",
                "Zaznacz termin w polu źródłowym ORAZ jego odpowiednik w polu tłumaczenia.",
            )
            return
        self.app.glossary.add(source_term, target_term)
        self.app.glossary_tab.refresh()
        self._refresh_terms()
        self.status_message.emit(f"Dodano do glosariusza: {source_term} → {target_term}")

    def run_concordance(self, query: str | None = None) -> None:
        text = query if isinstance(query, str) and query else self.conc_edit.text().strip()
        if not text:
            seg = self.current_segment()
            text = (seg.source[:40] if seg else "")
            self.conc_edit.setText(text)
        self.concordance_list.clear()
        if not text or not self.app.tm.is_initialized:
            return
        results = self.app.tm.search(text, 100)
        for src, tgt, _sl, _tl, _uc in results:
            item = QListWidgetItem(f"{src}\n    → {tgt}")
            item.setData(Qt.ItemDataRole.UserRole, tgt)
            self.concordance_list.addItem(item)
        if not results:
            self.concordance_list.addItem("(brak wyników w pamięci TM)")

    # --------------------------------------------------------------- akcje
    def save_to_tm(self, silent: bool = False) -> None:
        seg = self.current_segment()
        if not seg:
            return
        self._store_current()
        if not seg.is_translated:
            if not silent:
                self.info_label.setText("⚠️ Brak tłumaczenia do zapisania")
            return
        project = self.app.project
        added = self.app.tm.add(
            seg.source, seg.target,
            project.source_lang if project else "en",
            project.target_lang if project else "pl",
        )
        if added and not silent:
            self.info_label.setText("💾 Zapisano segment do pamięci TM")
        # Nie odświeżamy tabeli TM, gdy zakładka jest niewidoczna – przebudowa
        # tysiąca wierszy przy każdym Ctrl+Enter powodowała zacinanie edytora.
        # Zakładka odświeży się sama przy przejściu na nią.
        if self.app.tabs.currentWidget() is self.app.tm_tab:
            self.app.tm_tab.refresh()
        else:
            self.app.update_status()

    # ------------------------------------------------- szybki wybór silnika
    def reload_engine_picker(self) -> None:
        """Wypełnia listę silników nad polem tłumaczenia.

        Silniki wymagające klucza, którego nie ma, pokazujemy z ikoną 🔑 i bez
        możliwości wyboru filtrowanego — użytkownik od razu widzi, co zadziała.
        """
        from ..core.mt import ENGINES, FREE_ENGINES

        picker = self.engine_picker
        picker.blockSignals(True)
        picker.clear()
        ready = set(self.app.mt.available_engines(only_free=False))
        only_free = self.engine_free_only.isChecked()
        for key, label in ENGINES:
            if only_free and key not in FREE_ENGINES:
                continue
            prefix = "" if key in ready else "🔑 "
            picker.addItem(f"{prefix}{label}", key)
        current = self.app.mt.engine
        index = next((i for i in range(picker.count())
                      if picker.itemData(i) == current), -1)
        if index < 0:                      # bieżący silnik odfiltrowany – dopisz go
            label = dict(ENGINES).get(current, current)
            picker.addItem(label, current)
            index = picker.count() - 1
        picker.setCurrentIndex(index)
        picker.blockSignals(False)

    def _on_engine_picked(self, index: int) -> None:
        key = self.engine_picker.itemData(index)
        if not key or key == self.app.mt.engine:
            return
        self.app.mt.set_engine(key)   # słuchacze odświeżą Ustawienia i panel AI
        self.info_label.setText(f"🤖 Silnik MT: {self.app.mt.engine_label}")
        self.app.update_status()

    def _on_engine_filter_changed(self, state) -> None:
        SettingsManager.instance().set("editor.engine.free_only", bool(state))
        self.reload_engine_picker()

    def machine_translate_current(self) -> None:
        seg = self.current_segment()
        if not seg:
            return
        project = self.app.project
        sl = project.source_lang if project else "en"
        tl = project.target_lang if project else "pl"
        self.info_label.setText("🤖 Tłumaczenie maszynowe…")
        ai_tab = getattr(self.app, "ai_tab", None)
        if ai_tab is not None:
            ai_tab.begin_activity(f"Tłumaczenie segmentu {self.current_index + 1}")
        QApplication.processEvents()
        result = self.app.mt.translate(seg.source, sl, tl)
        self.set_target_text(result)
        self.mt_view.setPlainText(result)
        # Gdy silnik był niedostępny i zadziałał zamiennik, użytkownik musi
        # o tym wiedzieć – inaczej myśli, że tłumaczył DeepL.
        note = getattr(self.app.mt, "_last_fallback", "")
        if note:
            self.info_label.setText(f"⚠️ {note}")
            self.info_label.setToolTip(note)
        else:
            self.info_label.setText(f"🤖 MT ({self.app.mt.engine_label})")
            self.info_label.setToolTip("")
        if ai_tab is not None:
            failed = result.startswith("[Błąd")
            ai_tab.end_activity(
                result[:120] if failed else f"Wstawiono tłumaczenie ({len(result)} znaków)",
                "error" if failed else "ok",
            )
            from ..core.mt import LAST_RESTORE_STATS
            if not failed and LAST_RESTORE_STATS.get("missing"):
                ai_tab.log(
                    f"⚠️ Model zgubił {LAST_RESTORE_STATS['missing']} z "
                    f"{LAST_RESTORE_STATS['expected']} znaczników – dopisano je na końcu. "
                    "Sprawdź rozmieszczenie \\n i \\p.",
                    "error",
                )

    def machine_translate_preview(self) -> None:
        seg = self.current_segment()
        if not seg:
            return
        project = self.app.project
        result = self.app.mt.translate(
            seg.source,
            project.source_lang if project else "en",
            project.target_lang if project else "pl",
        )
        self.mt_view.setPlainText(result)

    def add_alternative_translation(self) -> None:
        seg = self.current_segment()
        if not seg or not seg.is_translated:
            self.info_label.setText("⚠️ Najpierw wpisz tłumaczenie")
            return
        self.alt_translations.setdefault(seg.source, []).append(seg.target)
        self.info_label.setText("📝 Dodano tłumaczenie alternatywne")

    def show_alternative_translations(self) -> None:
        seg = self.current_segment()
        if not seg:
            return
        alts = self.alt_translations.get(seg.source, [])
        if not alts:
            QMessageBox.information(self, "Tłumaczenia alternatywne", "Brak zapisanych alternatyw dla tego segmentu.")
            return
        from PyQt6.QtWidgets import QInputDialog

        choice, ok = QInputDialog.getItem(
            self, "Tłumaczenia alternatywne", "Wybierz wariant:", alts, 0, False
        )
        if ok and choice:
            self.set_target_text(choice)

    # ------------------------------------------------------------- postęp
    def update_progress(self) -> None:
        # Pominięte segmenty (wykluczone regułą albo ręcznie) nie są pracą
        # do wykonania, więc nie wchodzą do mianownika postępu.
        active = [s for s in self.segments if not s.ignored]
        total = len(active)
        done = sum(1 for s in active if _is_done(s))
        skipped = len(self.segments) - total
        percent = int(done * 100 / total) if total else 0
        self.progress.setValue(percent)
        self.progress.setFormat(f"{percent}%  ({done}/{total})")
        # Liczniki przy plikach muszą iść w parze z paskiem postępu – wcześniej
        # lista pokazywała stan sprzed „Zastosuj TM” aż do przełączenia projektu.
        self.update_file_counters()
        self.app.update_status()

    def _auto_save(self) -> None:
        if self.app.project and self.segments:
            self.app.save_translations(silent=True)
