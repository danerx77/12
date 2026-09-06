"""Zakładka Edytor – siatka segmentów + edytory + panele pomocnicze.

Układ inspirowany Supervertaler Workbench:
  [pliki] | [siatka segmentów + edytor źródło/cel] | [dopasowania TM / terminy / konkordancja]
"""
from __future__ import annotations

import json
import os
import re
import time as _time
from typing import List, Optional, Sequence

from PyQt6.QtCore import QEvent, QMimeData, QPoint, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (QAction, QBrush, QColor, QDrag, QFont, QKeySequence, QPainter, QPainterPath,
                         QPalette, QPen, QShortcut, QTextCharFormat, QTextCursor)
from PyQt6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QFileDialog, QFrame, QHBoxLayout,
    QHeaderView, QLabel,
    QApplication, QStyle, QStyledItemDelegate, QStyleOptionViewItem,
    QInputDialog, QLineEdit, QListWidget, QListWidgetItem, QMenu, QMessageBox, QPlainTextEdit,
    QGroupBox, QGridLayout, QProgressBar, QScrollArea, QStyle,
    QPushButton, QSizePolicy, QSplitter, QSplitterHandle, QTableWidget, QTableWidgetItem, QTabWidget, QTextEdit, QToolButton, QVBoxLayout,
    QWidget,
)

from ..core.fileparser import Segment
from ..core.tm import (SentenceMatch, TranslationMatch,
                       strip_codes_for_display as _strip_codes)
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


_CSS_FONT_SIZE_RE = re.compile(r"font-size\s*:\s*(\d+)\s*(px|pt)", re.IGNORECASE)


def _scale_css_font_size(sheet: str, new_points: int, base_font: QFont) -> str:
    """Skaluje rozmiary w regułach CSS wg proporcji nowej czcionki do bazowej.

    Kontrolki z własnym arkuszem stylów (np. szare podpowiedzi
    „font-size: 11px”) nie reagują na ``setFont`` — arkusz jest ważniejszy.
    Takie kontrolki zwracają rozmiar w PIKSELACH (``pointSize() == -1``),
    więc trzeba go najpierw przeliczyć na punkty.
    """
    base_points = base_font.pointSize()
    if base_points <= 0:
        pixels = base_font.pixelSize()
        base_points = pixels * 72 / 96 if pixels > 0 else 0
    ratio = (new_points / base_points) if base_points > 0 else 1.0

    def replace(match) -> str:
        value = int(match.group(1))
        return f"font-size: {max(6, int(round(value * ratio)))}px"

    return _CSS_FONT_SIZE_RE.sub(replace, sheet)


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

    #: Kolumny, które wypełniają wolne miejsce: „Tekst źródłowy” i „Tłumaczenie”.
    STRETCH_COLUMNS = (1, 2)
    #: Najmniejsza sensowna szerokość kolumny rozciągliwej (px).
    MIN_STRETCH = 60

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        #: Prawda, gdy sami przeliczamy szerokości (żeby nie zapisać ich
        #: jako „zmiana użytkownika” i nie wejść w rekurencję).
        self._fitting = False

    def is_fitting(self) -> bool:
        """Czy trwa właśnie własne rozmieszczanie kolumn."""
        return self._fitting

    def fill_width(self, keep: Optional[int] = None) -> None:
        """Dociąga kolumny rozciągliwe do szerokości okna.

        Qt potrafi to robić samo — tryb ``Stretch`` — ale wtedy **nie wolno**
        przesuwać krawędzi kolumny myszą (Qt ignoruje nawet ``resizeSection``).
        Dlatego kolumny są ``Interactive`` (pełna swoboda przeciągania), a
        wyrównanie do szerokości okna robimy tutaj.

        ``keep`` — kolumna, której szerokość właśnie ustawił użytkownik:
        ona zostaje bez zmian, a różnicę przejmuje jej sąsiad — dokładnie tak
        jak w arkuszu (przesuwasz krawędź, sąsiad się zwęża). Dzięki temu
        da się ustawić każdą kolumnę, także ostatnią.
        Bez ``keep`` (zmiana szerokości okna) wolne miejsce dzielone jest
        proporcjonalnie do tego, jak użytkownik ustawił kolumny ostatnio.
        """
        if self._fitting or self.columnCount() <= 0:
            return
        available = self.viewport().width()
        if available <= 0:
            return
        stretch = [c for c in self.STRETCH_COLUMNS if c < self.columnCount()]
        if not stretch:
            return
        header = self.horizontalHeader()
        base_min = max(1, header.minimumSectionSize())
        columns = self.columnCount()

        def minimum_for(col: int) -> int:
            return max(base_min, self.MIN_STRETCH if col in stretch else 0)

        widths = [self.columnWidth(c) for c in range(columns)]
        other = sum(w for c, w in enumerate(widths) if c not in stretch)
        target = available - other
        new: dict[int, int] = {}

        neighbour = -1
        if keep is not None and 0 <= keep < columns and columns > 1:
            neighbour = keep + 1 if keep + 1 < columns else keep - 1

        if neighbour >= 0:
            # Miejsce dla sąsiada = cała szerokość okna minus wszystko poza
            # przesuwaną kolumną i jej sąsiadem.
            rest_width = sum(w for c, w in enumerate(widths)
                             if c != keep and c != neighbour)
            room = available - rest_width - widths[keep]
            n_min = base_min
            if room < n_min:
                # Sąsiad nie ma już czego oddać – kolumna dojechała do krawędzi.
                new[keep] = max(n_min, available - rest_width - n_min)
                new[neighbour] = n_min
            else:
                new[keep] = widths[keep]
                new[neighbour] = room
        else:
            current = sum(widths[c] for c in stretch)
            if current <= 0:
                new = {c: max(minimum_for(c), target // len(stretch)) for c in stretch}
            elif abs(current - target) <= 2:
                return                              # już pasuje – nie ruszaj
            else:
                scaled = {c: widths[c] * target / current for c in stretch}
                new = {c: max(minimum_for(c), int(scaled[c])) for c in stretch}
                # Reszta z zaokrągleń idzie do kolumn z największą częścią
                # ułamkową. Bez tego 1–2 px lądowało zawsze w ostatniej
                # kolumnie i proporcje „uciekały” po każdym przeliczeniu
                # (widać to było przy przełączaniu układu panelu).
                missing = target - sum(new.values())
                if missing > 0:
                    order = sorted(stretch, key=lambda c: scaled[c] - int(scaled[c]),
                                   reverse=True)
                    i = 0
                    while missing > 0:
                        new[order[i % len(order)]] += 1
                        missing -= 1
                        i += 1
                excess = sum(new.values()) - target
                if excess > 0:
                    # Po nałożeniu minimów miejsca może zabraknąć – zdejmij
                    # nadmiar z najszerszej kolumny, żeby nie wyszedł pasek.
                    for col in sorted(stretch, key=lambda c: new[c], reverse=True):
                        give = min(excess, new[col] - minimum_for(col))
                        if give > 0:
                            new[col] -= give
                            excess -= give
                        if excess <= 0:
                            break

        self._fitting = True
        try:
            for col, width in new.items():
                if width != widths[col]:
                    self.setColumnWidth(col, width)
        finally:
            self._fitting = False

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        super().resizeEvent(event)
        self.fill_width()

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
    "todo": "🔵 do przetłumaczenia",
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



_UNDERLINE_STYLES = {
    "wave": QTextCharFormat.UnderlineStyle.WaveUnderline,
    "solid": QTextCharFormat.UnderlineStyle.SingleUnderline,
    "dash": QTextCharFormat.UnderlineStyle.DashUnderline,
    "dot": QTextCharFormat.UnderlineStyle.DotLine,
    "spell": QTextCharFormat.UnderlineStyle.SpellCheckUnderline,
}


def language_underline_settings():
    """Kolor / styl / grubość podkreślenia z Ustawień."""
    sm = SettingsManager.instance()
    style = sm.get_str("lang.underline.style", "wave") or "wave"
    if style not in _UNDERLINE_STYLES:
        style = "wave"
    thickness = sm.get_int("lang.underline.thickness", 2)
    thickness = max(1, min(8, thickness))
    colors = {
        "błąd": sm.get_str("lang.underline.error.color", "#ff5252") or "#ff5252",
        "ostrzeżenie": sm.get_str("lang.underline.warning.color", "#ffa726") or "#ffa726",
        "info": sm.get_str("lang.underline.info.color", "#64b5f6") or "#64b5f6",
    }
    return {
        "style": style,
        "qt_style": _UNDERLINE_STYLES[style],
        "thickness": thickness,
        "colors": colors,
        "background": sm.get_bool("lang.underline.background", False),
        "enabled": sm.get_bool("lang.check.underline", True),
        "custom": sm.get_bool("lang.underline.custom", False),
    }


class TargetEdit(QPlainTextEdit):
    """Pole tłumaczenia — potrafi narysować grubszą falkę niż ExtraSelections."""

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        tab = self.parent()
        while tab is not None and not hasattr(tab, "_paint_language_underlines"):
            tab = tab.parent()
        if tab is None:
            return
        # Wyjątek / drugi QPainter w paintEvent zamykał całą aplikację
        # w momencie, gdy w tekście pojawiał się błąd językowy.
        try:
            tab._paint_language_underlines(self)
        except Exception:
            return


class ExpandingSplitter(QSplitter):
    """Pionowy splitter, który nie zgniata paneli.

    Przeciągnięcie uchwytu zmienia TYLKO panel nad nim. Reszta zjeżdża w dół
    i wydłuża się pasek przewijania kolumny — sąsiad nie maleje.
    """

    def __init__(self, orientation=Qt.Orientation.Vertical, parent=None) -> None:
        super().__init__(orientation, parent)
        self._panel_min = 280
        self.setChildrenCollapsible(False)

    def createHandle(self):  # noqa: N802
        return ExpandingHandle(self.orientation(), self)

    def apply_panel_sizes(self, sizes) -> None:
        sizes = [max(0, int(v)) for v in sizes]
        extra = self.handleWidth() * max(0, self.count() - 1)
        height = sum(sizes) + extra
        if getattr(self, "_soft_min", False):
            # Dolny pas: treść może być wyższa niż okno (suwak), ale
            # NIE blokuje zmniejszania pasa.
            self.setMinimumHeight(max(1, int(getattr(self, "_panel_min", 80))))
        else:
            self.setMinimumHeight(max(1, height))
        self.resize(max(1, self.width()), max(1, height))
        self.setSizes(sizes)


class ExpandingHandle(QSplitterHandle):
    def __init__(self, orientation, parent) -> None:
        super().__init__(orientation, parent)
        self._drag_y = 0.0
        self._drag_sizes: list[int] = []

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_y = event.globalPosition().y()
            self._drag_sizes = list(self.splitter().sizes())
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        splitter = self.splitter()
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        if not isinstance(splitter, ExpandingSplitter) or not self._drag_sizes:
            super().mouseMoveEvent(event)
            return
        dy = int(event.globalPosition().y() - self._drag_y)
        # W QSplitter handle(i) siedzi NAD widgetem i, czyli POD panelem i-1.
        # Uchwyt pod TM (pierwszy widoczny) ma i=1 → powiększa TM (0),
        # nie panel poniżej.
        handle_index = -1
        for i in range(splitter.count()):
            if splitter.handle(i) is self:
                handle_index = i
                break
        if handle_index < 0:
            return
        target = handle_index - 1 if handle_index > 0 else 0
        sizes = list(self._drag_sizes)
        if target < 0 or target >= len(sizes):
            return
        widget = splitter.widget(target)
        if widget is not None and widget.objectName() == "sc_right_tail":
            return
        minimum = splitter._panel_min
        sizes[target] = max(minimum, self._drag_sizes[target] + dy)
        for i in range(len(sizes)):
            child = splitter.widget(i)
            if child is not None and child.objectName() == "sc_right_tail":
                sizes[i] = 0
        splitter.apply_panel_sizes(sizes)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        super().mouseReleaseEvent(event)
        splitter = self.splitter()
        # splitterMoved nie zawsze idzie, gdy nie wołamy super().mouseMove
        try:
            splitter.splitterMoved.emit(0, 0)
        except Exception:
            pass


PANEL_KEYS = ("matches", "sentences", "terms", "conc", "mt", "lang", "notes")
PANEL_MIME = "application/x-supercat-panel"
PANEL_LABELS = {
    "matches": "Dopasowania TM",
    "sentences": "Dopasowanie zdań",
    "terms": "Terminy",
    "conc": "Konkordancja",
    "mt": "MT",
    "lang": "Język",
    "notes": "Notatki",
}


class DockableGroup(QGroupBox):
    """Panel z tytułem do chwycenia: przeciągnij, żeby zmienić miejsce."""

    def __init__(self, title: str, key: str, editor: "EditorTab") -> None:
        super().__init__(title)
        self._panel_key = key
        self._editor = editor
        self._drag_start: QPoint | None = None
        self._drop_side: str | None = None
        self.setAcceptDrops(True)
        self.setProperty("sc_panel_key", key)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setFlat(True)
        self.setStyleSheet(
            "DockableGroup { margin-top: 4px; padding: 0 2px 2px 2px; }"
            "DockableGroup::title { subcontrol-origin: margin; left: 6px;"
            " padding: 0 4px; }")
        self.setToolTip(
            "Chwyć tytuł i przeciągnij. Podświetlenie pokazuje, co się stanie:\n"
            "bok = obok, góra/dół = kolejność (jeden pod drugim).\n"
            "Prawy przycisk — menu miejsca.")

    def _title_height(self) -> int:
        return max(22, self.fontMetrics().height() + 10)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and event.position().y() <= self._title_height():
            self._drag_start = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_start is None or not (event.buttons() & Qt.MouseButton.LeftButton):
            super().mouseMoveEvent(event)
            return
        if (event.position().toPoint() - self._drag_start).manhattanLength() < QApplication.startDragDistance():
            return
        mime = QMimeData()
        mime.setData(PANEL_MIME, self._panel_key.encode("utf-8"))
        mime.setText(self._panel_key)
        drag = QDrag(self)
        drag.setMimeData(mime)
        self._drag_start = None
        drag.exec(Qt.DropAction.MoveAction)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._drag_start = None
        super().mouseReleaseEvent(event)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasFormat(PANEL_MIME):
            event.acceptProposedAction()
            self._set_drop_side(event)
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasFormat(PANEL_MIME):
            event.acceptProposedAction()
            self._set_drop_side(event)
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self._drop_side = None
        self.update()
        super().dragLeaveEvent(event)

    def _set_drop_side(self, event) -> None:
        zone = self._editor.panel_zone(self._panel_key)
        if zone != "below":
            self._drop_side = "before"
        else:
            self._drop_side = self._side_at(event.position())
        self.update()

    def _side_at(self, pos) -> str:
        w = max(1.0, float(self.width()))
        h = max(1.0, float(self.height()))
        x, y = float(pos.x()), float(pos.y())
        # Wąskie pasy po bokach = obok; środek / góra / dół = kolejność.
        if x < w * 0.20:
            return "left"
        if x > w * 0.80:
            return "right"
        if y < h * 0.40:
            return "above"
        return "below"

    def dropEvent(self, event) -> None:  # noqa: N802
        raw = bytes(event.mimeData().data(PANEL_MIME)).decode("utf-8")
        side = self._drop_side
        self._drop_side = None
        self.update()
        if raw and raw != self._panel_key:
            zone = self._editor.panel_zone(self._panel_key)
            if zone == "below":
                self._editor.place_panel(
                    raw, zone="below", beside=self._panel_key,
                    side=side or self._side_at(event.position()))
            else:
                self._editor.place_panel(raw, zone=zone, before=self._panel_key)
        event.acceptProposedAction()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        side = self._drop_side
        if not side:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.rect()
        painter.fillRect(rect, QColor(0, 0, 0, 70))

        def _label(area, text, active, fill):
            if area.width() < 8 or area.height() < 8:
                return
            painter.fillRect(area, fill)
            if active:
                painter.setPen(QPen(QColor(255, 255, 255, 230), 3))
                painter.drawRect(area.adjusted(3, 3, -3, -3))
            painter.setPen(QColor(255, 255, 255) if active else QColor(220, 220, 220, 180))
            font = QFont(self.font())
            font.setBold(True)
            font.setPointSize(max(9, self.font().pointSize()))
            painter.setFont(font)
            painter.drawText(area, int(Qt.AlignmentFlag.AlignCenter), text)

        if side == "before":
            _label(rect, "Wstaw tutaj\n(kolejność)", True, QColor(76, 175, 80, 150))
            painter.end()
            return
        w, h = rect.width(), rect.height()
        left = rect.adjusted(0, 0, int(w * 0.20) - w, 0)
        right = rect.adjusted(int(w * 0.80), 0, 0, 0)
        mid = rect.adjusted(int(w * 0.20), 0, int(w * 0.20) - w, 0)
        top = mid.adjusted(0, 0, 0, int(mid.height() * 0.40) - mid.height())
        bot = mid.adjusted(0, int(mid.height() * 0.40), 0, 0)
        zones = (
            ("left", left, "OBOK\n←", QColor(33, 150, 243, 90), QColor(33, 150, 243, 190)),
            ("right", right, "OBOK\n→", QColor(33, 150, 243, 90), QColor(33, 150, 243, 190)),
            ("above", top, "NAD\n(kolejność)", QColor(255, 152, 0, 80), QColor(255, 152, 0, 190)),
            ("below", bot, "POD\n(kolejność)", QColor(255, 152, 0, 80), QColor(255, 152, 0, 190)),
        )
        for name, area, text, faint, strong in zones:
            _label(area, text, name == side, strong if name == side else faint)
        painter.end()

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        menu = QMenu(self)
        zone = self._editor.panel_zone(self._panel_key)
        menu.addAction(
            "Umieść na dole (cała szerokość)",
            lambda: self._editor.place_panel(self._panel_key, zone="below"))
        others = [k for k in ("matches", "sentences", "terms", "conc", "mt", "lang", "notes")
                  if k != self._panel_key]
        beside_menu = menu.addMenu("Umieść obok")
        labels = {
            "matches": "Dopasowania TM", "sentences": "Dopasowanie zdań",
            "terms": "Terminy", "conc": "Konkordancja", "mt": "MT",
            "lang": "Język", "notes": "Notatki",
        }
        for other in others:
            beside_menu.addAction(
                labels.get(other, other),
                lambda _=False, o=other: self._editor.place_panel(
                    self._panel_key, zone="below", beside=o, side="right"))
        if zone != "right":
            menu.addAction("Umieść w prawej kolumnie",
                           lambda: self._editor.place_panel(self._panel_key, zone="right"))
        menu.addSeparator()
        menu.addAction("Wyżej / w lewo", lambda: self._editor.nudge_panel(self._panel_key, -1))
        menu.addAction("Niżej / w prawo", lambda: self._editor.nudge_panel(self._panel_key, 1))
        menu.exec(event.globalPos())


class BandHeightGrip(QFrame):
    """Kreska na górze dolnego pasa — przeciągnij w górę, żeby go powiększyć."""

    def __init__(self, editor: "EditorTab") -> None:
        super().__init__()
        self._editor = editor
        self._drag_y = 0.0
        self._sizes: list[int] = []
        self.setFixedHeight(8)
        self.setCursor(Qt.CursorShape.SizeVerCursor)
        self.setToolTip("Przeciągnij w GÓRĘ, żeby powiększyć dolny pas (TM / zdania).")
        self.setStyleSheet(
            "BandHeightGrip { background: #4a5a75; border-radius: 3px; }"
            "BandHeightGrip:hover { background: #2f7fd1; }")

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_y = event.globalPosition().y()
            root = getattr(self._editor, "_root_split", None)
            self._sizes = list(root.sizes()) if root is not None else []
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if not (event.buttons() & Qt.MouseButton.LeftButton) or len(self._sizes) != 2:
            return
        root = getattr(self._editor, "_root_split", None)
        if root is None:
            return
        dy = int(self._drag_y - event.globalPosition().y())
        total = self._sizes[0] + self._sizes[1]
        bottom = max(70, min(self._sizes[1] + dy, total - 100))
        top = total - bottom
        root.setSizes([top, bottom])
        self._editor._sync_below_stack_size()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        super().mouseReleaseEvent(event)
        saver = getattr(self._editor, "_save_split_sizes", None)
        if callable(saver):
            saver()


class PanelDropHost(QWidget):
    """Miejsce, na które można upuścić panel (prawa kolumna albo pod tłumaczeniem)."""

    def __init__(self, editor: "EditorTab", zone: str, parent=None) -> None:
        super().__init__(parent)
        self._editor = editor
        self._zone = zone
        self._armed = False
        self.setAcceptDrops(True)

    def _arm(self, on: bool) -> None:
        self._armed = on
        self.setStyleSheet(
            "PanelDropHost { border: 2px dashed #42a5f5; background: rgba(66,165,245,40); }"
            if on else "")
        self.update()

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasFormat(PANEL_MIME):
            event.acceptProposedAction()
            self._arm(True)
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasFormat(PANEL_MIME):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self._arm(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802
        self._arm(False)
        raw = bytes(event.mimeData().data(PANEL_MIME)).decode("utf-8")
        if raw:
            self._editor.place_panel(raw, zone=self._zone)
        event.acceptProposedAction()


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
        self.status_filter.addItems(["Wszystkie", "Nieprzetłumaczone", "Do przetłumaczenia",
                                         "Przetłumaczone", "Zatwierdzone", "Pominięte"])
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
        # Wszystkie kolumny przesuwne myszą. Wcześniej dwie środkowe były
        # w trybie Stretch, a wtedy Qt w ogóle nie pozwala zmienić szerokości
        # — nawet programowo — więc kolumn „nie dało się” rozciągnąć.
        # Wolne miejsce rozkłada SegmentGrid.fill_width() (zachowuje proporcje
        # ustawione przez użytkownika).
        for col in range(self.grid.columnCount()):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)
        header.setMinimumSectionSize(40)
        header.setToolTip(
            "Przeciągnij krawędź nagłówka, żeby zmienić szerokość kolumny.\n"
            "Szerokości są zapamiętywane między sesjami (prawy przycisk = Reset).")
        self.grid.setColumnWidth(0, 55)
        self.grid.setColumnWidth(1, 400)
        self.grid.setColumnWidth(2, 400)
        self.grid.setColumnWidth(3, 150)
        self._restore_grid_columns()
        header.sectionResized.connect(self._on_grid_column_resized)
        header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(self._grid_header_menu)
        # Pionowy pasek przewijania zmienia szerokość okna roboczego siatki —
        # bez tego po dodaniu segmentów zostawał pusty pasek poziomy.
        self.grid.verticalScrollBar().rangeChanged.connect(
            lambda *_a: self.grid.fill_width())
        # Zapis szerokości jest odroczony: przeciąganie wywołuje sectionResized
        # dziesiątki razy, a każdy zapis to osobny plik na dysku.
        self._grid_col_timer = QTimer(self)
        self._grid_col_timer.setSingleShot(True)
        self._grid_col_timer.timeout.connect(self._save_grid_columns)
        # Ostatni segment, na którym stanęliśmy — zapis odroczony, bo
        # strzałkami po siatce przechodzi się dziesiątki segmentów na minutę.
        self._last_seg_timer = QTimer(self)
        self._last_seg_timer.setSingleShot(True)
        self._last_seg_timer.timeout.connect(self._save_last_segment)
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
        from ..core import shortcuts as _sc_qt
        compare_btn.setToolTip(_sc_qt.with_shortcut("quicktrans", "QuickTrans: kilka silników naraz"))
        compare_btn.clicked.connect(lambda: self.app.open_quicktrans())
        mt_bar.addWidget(compare_btn)
        mt_bar.addStretch(1)
        ed_layout.addLayout(mt_bar)
        self.reload_engine_picker()
        # Silnik można przestawić także z Ustawień lub panelu AI – wtedy
        # lista musi to pokazać, inaczej wprowadza w błąd.
        self.app.mt.add_engine_listener(lambda _e: self.reload_engine_picker())

        self.target_edit = TargetEdit()
        self.target_edit.setPlaceholderText("Tutaj wpisz tłumaczenie…  (Ctrl+Enter = zatwierdź i dalej)")
        self.target_edit.textChanged.connect(self._on_target_changed)
        self.target_edit.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.target_edit.customContextMenuRequested.connect(self._target_context_menu)
        ed_layout.addWidget(self.target_edit)

        from ..core import shortcuts as _sc
        nav = QHBoxLayout()
        for text, tip, slot in (
            ("◀ Poprzedni", "Alt+↑ – poprzedni segment", self.prev_segment),
            ("Następny ▶", "Alt+↓ – następny segment", self.next_segment),
            ("◀◀", _sc.with_shortcut("prev_untranslated", "poprzedni NIEPRZETŁUMACZONY segment"),
             self.prev_untranslated),
            ("▶▶", _sc.with_shortcut("next_untranslated", "następny NIEPRZETŁUMACZONY segment"),
             self.next_untranslated),
            ("✔ Zatwierdź i dalej", _sc.with_shortcut("confirm_next", "zatwierdź i dalej"), self.confirm_and_next),
            ("💾 Do TM", _sc.with_shortcut("save_to_tm", "zapisz segment do pamięci"), self.save_to_tm),
            # „🤖 Tłumacz” przeniesiony wyżej – obok wyboru silnika MT.
            ("📋 Kopiuj źródło", _sc.with_shortcut("copy_source", "kopiuj źródło do tłumaczenia"), self.copy_source_to_target),
            ("␣ Wcięcie", _sc.with_shortcut("restore_indent", "nadaj tłumaczeniu takie same spacje na brzegach jak w źródle"),
             self.restore_source_indent),
            ("🚫 Pomiń", _sc.with_shortcut("ignore_selected", "pomiń zaznaczone segmenty (nie będą liczone)"),
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
        # Boxy budujemy RAZ (stan pozostaje przy przełączaniu układu); sam
        # kontener (wszystko naraz / zakładki) odświeża apply_panel_layout().
        # Ustawienia: tm.panel.layout (stacked/tabs) + tm.panel.show.<panel>.
        self._right_panels: list[tuple[str, QWidget, str]] = []

        def _right_panel(title: str, content: QWidget, key: str) -> None:
            self._right_panels.append((title, content, key))

        self.matches_list = QListWidget()
        self.matches_list.setWordWrap(True)
        self.matches_list.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.matches_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.matches_list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.matches_list.setMinimumHeight(72)
        self.matches_list.itemDoubleClicked.connect(self._insert_match)
        matches_box = QWidget()
        mb_layout = QVBoxLayout(matches_box)
        mb_layout.setContentsMargins(4, 4, 4, 4)
        self.matches_info = QLabel("")
        self.matches_info.setWordWrap(False)
        self.matches_info.setStyleSheet("color: gray; font-size: 11px;")
        self.matches_info.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.matches_info.setMaximumHeight(16)
        mb_layout.setContentsMargins(2, 0, 2, 2)
        mb_layout.setSpacing(2)
        mb_layout.addWidget(self.matches_info)
        self.matches_info.hide()
        mb_layout.addWidget(self.matches_list, 1)
        insert_btn = QPushButton("⤵ Wstaw zaznaczone\ndopasowanie")
        from ..core import shortcuts as _sc_ins
        insert_btn.setToolTip(_sc_ins.with_shortcut("insert_match", "Wstaw zaznaczone dopasowanie"))
        insert_btn.setMinimumHeight(40)
        insert_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        insert_btn.clicked.connect(self._insert_selected_match)
        mb_layout.addWidget(insert_btn)
        _right_panel("💡 Dopasowania TM", matches_box, "matches")

        # Dopasowanie zdań (fragmenty) – odpowiednik SentenceMatchingPanel z repo `5`
        self.sentence_list = QListWidget()
        self.sentence_list.setWordWrap(True)
        self.sentence_list.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.sentence_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.sentence_list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.sentence_list.setMinimumHeight(72)
        self.sentence_list.itemDoubleClicked.connect(self._insert_sentence_match)
        sentence_box = QWidget()
        sb_layout = QVBoxLayout(sentence_box)
        sb_layout.setContentsMargins(4, 4, 4, 4)
        self.sentence_toggle = QCheckBox("Włącz dopasowanie zdań")
        self.sentence_toggle.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
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
        self.sentence_info.setWordWrap(True)
        self.sentence_info.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        sb_layout.addWidget(self.sentence_info)
        sb_layout.addWidget(self.sentence_list, 1)
        sent_btn = QPushButton("⤵ Wstaw złożone tłumaczenie")
        sent_btn.setMinimumHeight(36)
        sent_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        sent_btn.clicked.connect(self._insert_selected_sentence_match)
        sb_layout.addWidget(sent_btn)
        hint = QLabel(
            "💡 Gdy segment jest dłuższy niż wpisy w TM, program szuka pasujących "
            "fragmentów i podstawia ich tłumaczenia w zdaniu."
        )
        hint.setWordWrap(True)
        hint.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        hint.setStyleSheet("color: gray; font-size: 11px;")
        sb_layout.addWidget(hint)
        _right_panel("🔗 Dopasowanie zdań", sentence_box, "sentences")

        self.terms_list = QListWidget()
        self.terms_list.setWordWrap(True)
        self.terms_list.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.terms_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.terms_list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.terms_list.setMinimumHeight(64)
        self.terms_list.itemDoubleClicked.connect(self._insert_term)
        terms_box = QWidget()
        tb_layout = QVBoxLayout(terms_box)
        tb_layout.setContentsMargins(4, 4, 4, 4)
        terms_hint = QLabel("Terminy znalezione w segmencie (2× klik = wstaw)")
        terms_hint.setWordWrap(True)
        terms_hint.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        tb_layout.addWidget(terms_hint)
        tb_layout.addWidget(self.terms_list, 1)
        add_term_btn = QPushButton("➕ Dodaj zaznaczenie\ndo glosariusza")
        add_term_btn.setToolTip("Dodaj zaznaczenie do glosariusza")
        add_term_btn.setMinimumHeight(40)
        add_term_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        add_term_btn.clicked.connect(self._add_selection_to_glossary)
        tb_layout.addWidget(add_term_btn)
        _right_panel("🏷️ Terminy", terms_box, "terms")

        self.concordance_list = QListWidget()
        self.concordance_list.setWordWrap(True)
        self.concordance_list.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.concordance_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.concordance_list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.concordance_list.setMinimumHeight(64)
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
        _right_panel("🔍 Konkordancja", conc_box, "conc")

        self.mt_view = QPlainTextEdit()
        self.mt_view.setReadOnly(True)
        self.mt_view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.mt_view.setMinimumHeight(64)
        mt_box = QWidget()
        mt_layout = QVBoxLayout(mt_box)
        mt_layout.setContentsMargins(4, 4, 4, 4)
        mt_caption = QLabel("Propozycja tłumaczenia maszynowego")
        mt_caption.setWordWrap(True)
        mt_caption.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        mt_layout.addWidget(mt_caption)
        mt_layout.addWidget(self.mt_view, 1)
        mt_row = QGridLayout()
        mt_row.setContentsMargins(0, 0, 0, 0)
        mt_row.setSpacing(6)
        gen_btn = QPushButton("🤖 Generuj")
        gen_btn.setMinimumHeight(32)
        gen_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        gen_btn.clicked.connect(self.machine_translate_preview)
        quick_btn = QPushButton("⚡ QuickTrans")
        from ..core import shortcuts as _sc_qt2
        quick_btn.setToolTip(_sc_qt2.with_shortcut("quicktrans", "Porównaj tłumaczenia z wielu silników naraz"))
        quick_btn.setMinimumHeight(32)
        quick_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        quick_btn.clicked.connect(lambda: self.app.open_quicktrans())
        use_btn = QPushButton("⤵ Wstaw do tłumaczenia")
        use_btn.setMinimumHeight(32)
        use_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        use_btn.clicked.connect(lambda: self.set_target_text(self.mt_view.toPlainText()))
        mt_row.addWidget(gen_btn, 0, 0)
        mt_row.addWidget(quick_btn, 0, 1)
        mt_row.addWidget(use_btn, 1, 0, 1, 2)
        mt_layout.addLayout(mt_row)
        _right_panel("🤖 MT", mt_box, "mt")

        # --- panel kontroli języka (tylko tłumaczenie) -------------------
        self.lang_list = QListWidget()
        self.lang_list.setWordWrap(True)
        self.lang_list.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.lang_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.lang_list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.lang_list.setMinimumHeight(64)
        self.lang_list.itemDoubleClicked.connect(self._apply_lang_suggestion)
        lang_box = QWidget()
        lang_layout = QVBoxLayout(lang_box)
        lang_layout.setContentsMargins(4, 4, 4, 4)
        self.lang_status = QLabel("Kontrola języka tłumaczenia")
        self.lang_status.setWordWrap(True)
        self.lang_status.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        lang_layout.addWidget(self.lang_status)
        lang_layout.addWidget(self.lang_list, 1)

        lang_opts = QVBoxLayout()
        lang_opts.setSpacing(2)
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
        self.lang_auto.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        self.lang_lt.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        lang_opts.addWidget(self.lang_auto)
        lang_opts.addWidget(self.lang_lt)
        lang_layout.addLayout(lang_opts)

        lang_btns = QVBoxLayout()
        lang_btns.setSpacing(4)
        check_now = QPushButton("🔤 Sprawdź teraz")
        from ..core import shortcuts as _sc_lang
        check_now.setToolTip(_sc_lang.with_shortcut("check_language", "Sprawdź teraz"))
        check_now.setMinimumHeight(32)
        check_now.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        check_now.clicked.connect(lambda: self.check_language(force=True))
        fix_btn = QPushButton("✨ Popraw automatycznie")
        fix_btn.setToolTip("Wstawia pierwszą propozycję dla uwag, które ją mają")
        fix_btn.setMinimumHeight(32)
        fix_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        fix_btn.clicked.connect(self.apply_language_fixes)
        lang_btns.addWidget(check_now)
        lang_btns.addWidget(fix_btn)
        lang_layout.addLayout(lang_btns)
        _right_panel("🔤 Język", lang_box, "lang")

        self.notes_edit = QPlainTextEdit()
        self.notes_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.notes_edit.setPlaceholderText("Notatki do segmentu…")
        self.notes_edit.textChanged.connect(self._on_notes_changed)
        _right_panel("📝 Notatki", self.notes_edit, "notes")
        self.apply_panel_font()

        splitter.addWidget(left)
        splitter.addWidget(center)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 5)
        splitter.setStretchFactor(2, 2)
        # Bez tego panel „Pliki projektu” albo prawa kolumna dają się
        # przeciągnąć do zera i znikają bez możliwości przywrócenia.
        setup_splitter(splitter, minimums=[150, 320, self._right_column_min_width()])
        self.main_splitter = splitter

        # Pas NA CAŁĄ SZEROKOŚĆ — musi istnieć zanim apply_panel_layout
        # włoży do niego panele.
        self._below_host = PanelDropHost(self, "below")
        below_l = QVBoxLayout(self._below_host)
        below_l.setContentsMargins(2, 0, 2, 2)
        below_l.setSpacing(1)
        self._below_grip = BandHeightGrip(self)
        below_l.addWidget(self._below_grip)
        self._below_grip.hide()
        self._below_hint = QLabel("⬇ Upuść panel")
        self._below_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._below_hint.setStyleSheet("color: gray; font-size: 10px; padding: 0;")
        self._below_hint.setToolTip(
            "Upuść tu na całą szerokość. Bok panelu = obok, góra/dół = kolejność.")
        below_l.addWidget(self._below_hint)
        self._below_stack = None
        self._below_host.setMinimumHeight(28)
        self._below_host.setMaximumHeight(36)
        self._below_host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        self.apply_panel_layout()
        # Szerokości kolumn: zapamiętane z poprzedniej sesji albo domyślne.
        splitter.setSizes([220, 820, 420])
        self._restore_split_sizes()
        splitter.splitterMoved.connect(self._save_split_sizes)
        self.center_splitter.splitterMoved.connect(self._save_split_sizes)

        self._root_split = QSplitter(Qt.Orientation.Vertical)
        self._root_split.addWidget(splitter)
        self._root_split.addWidget(self._below_host)
        self._root_split.setStretchFactor(0, 5)
        self._root_split.setStretchFactor(1, 2)
        self._root_split.setHandleWidth(10)
        self._root_split.setCollapsible(0, True)
        self._root_split.setCollapsible(1, True)
        from ..ui.theme import style_splitter_handle
        handle = self._root_split.handle(1)
        style_splitter_handle(handle)
        if handle is not None:
            handle.setToolTip("Wysokość dolnego pasa — przeciągnij w górę, żeby powiększyć")
        self._root_split.splitterMoved.connect(self._on_root_split_moved)
        layout.addWidget(self._root_split)

    def eventFilter(self, obj, event):  # noqa: N802 (Qt API)
        """Przechwytuje skróty nawigacji w polach tekstowych.

        QPlainTextEdit sam obsługuje Ctrl+↑/↓ (przewijanie) i Ctrl+Home/End
        (skok w tekście), więc zwykły QShortcut nigdy by się nie uruchomił.
        Tutaj łapiemy te kombinacje wcześniej i zamieniamy na zmianę segmentu.
        """
        container = getattr(self, "_right_container", None)
        if (event.type() == QEvent.Type.Resize and container is not None
                and obj in (container, getattr(container, "viewport", lambda: None)())):
            self._sync_right_stack_size()
        below_scroll = getattr(self, "_below_scroll", None)
        if (event.type() == QEvent.Type.Resize and below_scroll is not None
                and obj in (below_scroll, getattr(below_scroll, "viewport", lambda: None)())):
            self._sync_below_stack_size()
        if event.type() in (QEvent.Type.DragEnter, QEvent.Type.Drop) and obj is container:
            mime = getattr(event, "mimeData", lambda: None)()
            if mime is not None and mime.hasFormat(PANEL_MIME):
                if event.type() == QEvent.Type.DragEnter:
                    event.acceptProposedAction()
                    return True
                raw = bytes(mime.data(PANEL_MIME)).decode("utf-8")
                if raw:
                    self.place_panel(raw, zone="right")
                event.acceptProposedAction()
                return True
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
            "next_todo": self.next_todo,
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
            "mark_todo": self.mark_todo,
            "mark_draft": self.mark_draft,
            "mark_translated": self.mark_translated,
            "mark_approved": self.approve_current,
            "ignore_selected": self.ignore_selected,
            "restore_selected": self.restore_selected,
            "first_segment": self.first_segment,
            "last_segment": self.last_segment,
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
        self.current_index = -1
        self.refresh_files_list()
        self.refresh_grid()
        if segments:
            if not self._restore_last_segment():
                self.load_segment(0)
        else:
            self.source_edit.clear()
            self.target_edit.clear()
        self.update_progress()

    # --------------------------------------- pamięć miejsca pracy w pliku
    LAST_SEGMENT_KEY = "editor.last.segment"

    def _remember_last_segment(self) -> None:
        """Zapamiętuje bieżący segment dla jego pliku (zapis odroczony).

        Program wraca potem do tego samego miejsca, zamiast zaczynać plik
        od początku — przy kilkuset segmentach oszczędza to szukanie.
        """
        if getattr(self, "_loading", False):
            return
        self._last_seg_timer.start(800)

    def _save_last_segment(self) -> None:
        """Zapisuje mapę {plik: numer segmentu} do ustawień."""
        import json

        if not (0 <= getattr(self, "current_index", -1) < len(self.segments)):
            return
        seg = self.segments[self.current_index]
        name = getattr(seg, "file_name", None) or "(bez pliku)"
        try:
            raw = SettingsManager.instance().get(self.LAST_SEGMENT_KEY)
            remembered = json.loads(raw) if isinstance(raw, str) and raw else {}
            if not isinstance(remembered, dict):
                remembered = {}
        except (ValueError, TypeError):
            remembered = {}
        # Numer względny w pliku — kolejność segmentów w pliku jest stała,
        # a numer w całym projekcie zmienia się po dołożeniu plików.
        offset = sum(1 for s in self.segments[:self.current_index]
                     if (s.file_name or "(bez pliku)") == name)
        remembered[name] = offset
        # "*" = miejsce w całym projekcie (widok „wszystkie pliki” i restart).
        remembered["*"] = {"file": name, "offset": offset}
        meta = {k: v for k, v in remembered.items() if k in ("*", "_filter")}
        files = {k: v for k, v in remembered.items() if k not in meta}
        if len(files) > 200:
            files = dict(list(files.items())[-200:])
        remembered = {**files, **meta}
        try:
            SettingsManager.instance().set(self.LAST_SEGMENT_KEY,
                                           json.dumps(remembered))
        except Exception:
            pass

    def _restore_last_segment(self) -> bool:
        """Wracam do segmentu, na którym skończono pracę w tym pliku.

        Wywoływane przy wejściu w plik (i po wczytaniu projektu). Filtr
        tekstu nie kasuje zapamiętanego miejsca — tylko je przykrywa,
        dopóki filtr jest włączony.
        """
        import json

        if not self.segments:
            return False
        try:
            raw = SettingsManager.instance().get(self.LAST_SEGMENT_KEY)
            remembered = json.loads(raw) if isinstance(raw, str) and raw else {}
        except (ValueError, TypeError):
            return False
        if not isinstance(remembered, dict):
            return False

        def _load_in_file(file_name: str, offset: int) -> bool:
            seen = -1
            wanted_name = file_name or "(bez pliku)"
            for index, seg in enumerate(self.segments):
                if (seg.file_name or "(bez pliku)") != wanted_name:
                    continue
                seen += 1
                if seen == offset:
                    self.load_segment(index)
                    return True
            return False

        if self._file_filter:
            name = self._file_filter
            if name not in remembered:
                return False
            try:
                wanted = int(remembered[name])
            except (TypeError, ValueError):
                return False
            return _load_in_file(name, wanted)

        # Widok wszystkich plików / ponowne otwarcie projektu: klucz "*".
        star = remembered.get("*")
        if isinstance(star, dict):
            try:
                return _load_in_file(str(star.get("file") or "(bez pliku)"),
                                     int(star.get("offset")))
            except (TypeError, ValueError):
                return False
        if isinstance(star, int) and 0 <= star < len(self.segments):
            self.load_segment(star)
            return True
        return False

    def _set_file_marker(self, name: str, marker: str) -> None:
        """Ustawia własny znacznik pliku (✓ sprawdzone / ⚠️ uwaga / ✗ problem)."""
        proj = getattr(self.app, "project", None)
        if proj is None or getattr(proj, "file_markers", None) is None:
            return
        if marker:
            proj.file_markers[name] = marker
        else:
            proj.file_markers.pop(name, None)
        self.app.project_manager.save_project()
        self.update_file_counters()

    # ------------------------------------------------- szerokość kolumn siatki
    DEFAULT_GRID_COLUMNS = (55, 400, 400, 150)

    def _on_grid_column_resized(self, logical, _old, _new) -> None:
        """Użytkownik przesunął kolumnę: dociągnij resztę i zapamiętaj.

        Zapis jest odroczony – przeciąganie wywołuje ten sygnał dziesiątki
        razy, a każdy zapis to osobny plik na dysku.
        """
        if self.grid.is_fitting():
            return                      # to my przeliczamy – nie nadpisuj
        self.grid.fill_width(keep=logical)
        self._grid_col_timer.start(500)

    def _save_grid_columns(self) -> None:
        import json

        try:
            widths = [self.grid.columnWidth(c) for c in range(self.grid.columnCount())]
            SettingsManager.instance().set("editor.grid.columns", json.dumps(widths))
        except Exception:
            pass

    def _restore_grid_columns(self) -> None:
        """Wczytuje szerokości kolumn zapisane w poprzedniej sesji."""
        import json

        raw = SettingsManager.instance().get("editor.grid.columns")
        if not isinstance(raw, str) or not raw:
            return
        try:
            widths = json.loads(raw)
        except ValueError:
            return
        if not isinstance(widths, list) or len(widths) != self.grid.columnCount():
            return
        for col, value in enumerate(widths):
            try:
                width = int(value)
            except (TypeError, ValueError):
                continue
            if width > 0:
                self.grid.setColumnWidth(col, width)

    def reset_grid_columns(self) -> None:
        """Domyślne szerokości kolumn siatki (menu nagłówka)."""
        for col, width in enumerate(self.DEFAULT_GRID_COLUMNS):
            if col < self.grid.columnCount():
                self.grid.setColumnWidth(col, width)
        self.grid.fill_width()
        self._save_grid_columns()
        self.status_message.emit("↺ Przywrócono domyślne szerokości kolumn")

    def _grid_header_menu(self, pos) -> None:
        """Menu nagłówka siatki: dopasowanie i powrót do domyślnych szerokości."""
        menu = QMenu(self.grid)
        act_fit = menu.addAction("↔ Dopasuj kolumny do okna")
        act_reset = menu.addAction("↺ Domyślne szerokości kolumn")
        menu.addSeparator()
        act_info = menu.addAction("ℹ️ Przeciągnij krawędź nagłówka, aby zmienić szerokość")
        act_info.setEnabled(False)
        chosen = menu.exec(self.grid.horizontalHeader().mapToGlobal(pos))
        if chosen == act_fit:
            self.grid.fill_width()
            self._save_grid_columns()
        elif chosen == act_reset:
            self.reset_grid_columns()

    def _on_root_split_moved(self, *_a) -> None:
        self._sync_below_stack_size()
        self._save_split_sizes()

    def _save_split_sizes(self, *_a) -> None:
        """Pamięta szerokości kolumn (pliki | edytor | panel) między sesjami."""
        try:
            import json

            payload = {
                "main": self.main_splitter.sizes(),
                "center": self.center_splitter.sizes(),
            }
            root = getattr(self, "_root_split", None)
            if root is not None:
                payload["root"] = root.sizes()
            SettingsManager.instance().set("editor.split.sizes", json.dumps(payload))
        except Exception:
            pass

    def _set_split_sizes(self, left: int, center: int, right: int) -> None:
        """Ustawia szerokości [pliki | edytor | panel] z zachowaniem proporcji.

        Używane po przełączaniu układu panelu: splitter po wstawieniu nowego
        kontenera sam przelicza rozmiary i zwęża prawą kolumnę do minimum.
        """
        splitter = self.main_splitter
        if splitter.count() < 3:
            return
        total = sum(splitter.sizes()) or splitter.width()
        right = max(int(right), splitter.widget(2).minimumWidth())
        rest = max(0, total - right)
        base = left + center
        if base > 0:
            new_left = int(rest * left / base)
        else:
            new_left = int(rest * 0.22)
        new_center = max(0, rest - new_left)
        splitter.setSizes([new_left, new_center, right])

    def _on_right_stack_moved(self, *_a) -> None:
        """Po przeciągnięciu: nie zgniataj sąsiadów — wydłuż przewijany stos."""
        self._sync_right_stack_size()
        self._save_panel_heights()

    def _save_panel_heights(self, *_a) -> None:
        """Zapamiętuje wysokości paneli po prawej (przeciąganie myszą)."""
        import json

        stack = getattr(self, "_right_stack", None)
        if stack is None:
            return
        try:
            SettingsManager.instance().set("editor.panel.heights",
                                           json.dumps(stack.sizes()))
        except Exception:
            pass

    def _restore_panel_heights(self) -> bool:
        """Wczytuje wysokości paneli zapisane w poprzedniej sesji.

        Zwraca True, gdy udało się odtworzyć sensowny układ. Stare sesje
        z panelami po 60 px są pomijane — inaczej przyciski znowu znikają.
        """
        import json

        stack = getattr(self, "_right_stack", None)
        if stack is None:
            return False
        raw = SettingsManager.instance().get("editor.panel.heights")
        if not isinstance(raw, str) or not raw:
            return False
        try:
            sizes = json.loads(raw)
        except ValueError:
            return False
        if not isinstance(sizes, list):
            return False
        # Stary zapis bez atrapy na końcu — dopasuj długość.
        if len(sizes) == stack.count() - 1 and stack.count() > 0:
            tail = stack.widget(stack.count() - 1)
            if tail is not None and tail.objectName() == "sc_right_tail":
                sizes = list(sizes) + [0]
        if len(sizes) != stack.count():
            return False                      # inny zestaw paneli – zostaw równo
        try:
            values = [max(0, int(v)) for v in sizes]
        except (TypeError, ValueError):
            return False
        preferred = self._right_panel_preferred_height()
        # Układ z poprzedniej, zgniecionej wersji (wszystko poniżej wygodnej
        # wysokości) — lepiej zacząć od preferowanych rozmiarów.
        if values and max(values) < int(preferred * 0.75):
            return False
        clamped = []
        for index, value in enumerate(values):
            child = stack.widget(index)
            dummy = (child is not None and child.objectName() == "sc_right_tail")
            clamped.append(0 if dummy else max(preferred, value))
        stack.setSizes(clamped)
        return True

    def reset_panel_heights(self) -> None:
        """Równy podział wysokości paneli (↺ Przywróć układ paneli)."""
        stack = getattr(self, "_right_stack", None)
        if stack is None or not stack.count():
            return
        self._fit_right_stack()
        preferred = self._right_panel_preferred_height()
        sizes = []
        for index in range(stack.count()):
            child = stack.widget(index)
            dummy = (child is not None and child.objectName() == "sc_right_tail")
            sizes.append(0 if dummy else preferred)
        stack.setSizes(sizes)
        self._sync_right_stack_size()
        self._save_panel_heights()

    def _restore_split_sizes(self) -> None:
        import json

        raw = SettingsManager.instance().get("editor.split.sizes")
        if not isinstance(raw, str):
            return
        try:
            data = json.loads(raw)
        except ValueError:
            return
        root_sizes = data.get("root")
        root = getattr(self, "_root_split", None)
        if (root is not None and isinstance(root_sizes, list)
                and len(root_sizes) == root.count()):
            try:
                root.setSizes([max(0, int(v)) for v in root_sizes])
            except (TypeError, ValueError):
                pass
        main = data.get("main")
        if isinstance(main, list) and len(main) == self.main_splitter.count():
            sizes = [max(0, int(v)) for v in main]
            if len(sizes) >= 3:
                need = self._right_column_min_width()
                if sizes[2] < need:
                    extra = need - sizes[2]
                    sizes[2] = need
                    from_center = min(extra, max(0, sizes[1] - 320))
                    sizes[1] -= from_center
                    extra -= from_center
                    if extra:
                        sizes[0] = max(0, sizes[0] - extra)
            self.main_splitter.setSizes(sizes)
        center = data.get("center")
        if isinstance(center, list) and len(center) == self.center_splitter.count():
            self.center_splitter.setSizes([max(0, int(v)) for v in center])


    def _panel_em_px(self) -> int:
        """Wysokość wiersza czcionki prawego panelu (px)."""
        settings = SettingsManager.instance()
        points = settings.get_int("tm.panel.font.size", 0)
        if points <= 0:
            points = settings.get_int("ui.font.size", 0)
        if points <= 0:
            app = QApplication.instance()
            if app is not None:
                font = app.font()
                points = font.pointSize()
                if points <= 0:
                    pixels = font.pixelSize()
                    if pixels > 0:
                        return max(16, pixels)
        if points <= 0:
            points = 10
        return max(16, int(round(points * 4 / 3)))

    def _right_panel_min_height(self) -> int:
        """Najmniejsza wysokość panelu: tytuł, kawałek listy i przycisk."""
        em = self._panel_em_px()
        return max(140, em * 7 + 40)

    def _right_panel_preferred_height(self) -> int:
        """Wygodna wysokość panelu (tytuł + treść + przycisk, bez obcinania)."""
        em = self._panel_em_px()
        # Dopasowanie zdań ma checkbox, listę, przycisk i podpowiedź —
        # 168 px zostawiało przyciski i hint obcięte.
        return max(280, em * 15 + 80)

    def _right_column_min_width(self) -> int:
        """Szerokość prawej kolumny, w której etykiety i przyciski się mieszczą."""
        em = self._panel_em_px()
        return max(300, em * 18)

    def _fit_right_stack(self) -> None:
        """Minima stacked-paneli = wygodna wysokość; nadmiar idzie w pasek."""
        stack = getattr(self, "_right_stack", None)
        if stack is None or not stack.count():
            return
        preferred = self._right_panel_preferred_height()
        if isinstance(stack, ExpandingSplitter):
            stack._panel_min = preferred
        em = self._panel_em_px()
        for widget in (
            getattr(self, "matches_list", None),
            getattr(self, "sentence_list", None),
            getattr(self, "terms_list", None),
            getattr(self, "concordance_list", None),
            getattr(self, "lang_list", None),
            getattr(self, "mt_view", None),
            getattr(self, "notes_edit", None),
        ):
            if widget is not None:
                widget.setMinimumHeight(max(80, em * 5))
        visible_keys = [
            key for _title, _w, key in self._right_panels
            if SettingsManager.instance().get_bool(f"tm.panel.show.{key}", True)
        ]
        real = 0
        for index in range(stack.count()):
            child = stack.widget(index)
            if child is None:
                continue
            if child.objectName() == "sc_right_tail" or child.maximumHeight() == 0:
                child.setMinimumHeight(0)
                child.setMaximumHeight(0)
                stack.setStretchFactor(index, 0)
                continue
            child.setMinimumHeight(preferred)
            child.setSizePolicy(QSizePolicy.Policy.Preferred,
                                QSizePolicy.Policy.Minimum)
            key = visible_keys[real] if real < len(visible_keys) else ""
            real += 1
            stack.setStretchFactor(index, 0)
        extra = stack.handleWidth() * max(0, stack.count() - 1)
        stack.setMinimumHeight(preferred * max(1, real) + extra)
        self._sync_right_stack_size()

    def _sync_right_stack_size(self) -> None:
        """QScrollArea nie kurczy splittera: szerokość = viewport, wysokość = suma paneli.

        Przy ``widgetResizable=True`` Qt wciska 7 paneli w okno i Język/Notatki
        znikają. Tu splitter ma własną wysokość, a obszar się przewija.
        Powiększenie panelu (np. notatek) wydłuża zawartość, nie zgniata sąsiadów.
        """
        if getattr(self, "_syncing_right_stack", False):
            return
        stack = getattr(self, "_right_stack", None)
        container = getattr(self, "_right_container", None)
        if stack is None or not stack.count():
            return
        self._syncing_right_stack = True
        try:
            self._sync_right_stack_size_body(stack, container)
        finally:
            self._syncing_right_stack = False

    def _sync_right_stack_size_body(self, stack, container) -> None:
        preferred = self._right_panel_preferred_height()
        extra = stack.handleWidth() * max(0, stack.count() - 1)
        raw = list(stack.sizes())
        sizes = []
        for index in range(stack.count()):
            child = stack.widget(index)
            dummy = (child is not None and (
                child.objectName() == "sc_right_tail" or child.maximumHeight() == 0))
            if dummy:
                sizes.append(0)
            elif index < len(raw) and raw[index] > 0:
                sizes.append(max(preferred, int(raw[index])))
            else:
                sizes.append(preferred)
        height = sum(sizes) + extra
        stack.setMinimumHeight(height)
        width = stack.width() or self._right_column_min_width()
        if isinstance(container, QScrollArea) and container.viewport() is not None:
            vw = container.viewport().width()
            if vw > 0:
                width = vw
        if stack.width() != width or stack.height() != height:
            stack.resize(max(1, width), height)
        if list(stack.sizes()) != sizes:
            stack.setSizes(sizes)

    def _panel_order(self) -> list[str]:
        known = [key for _t, _w, key in self._right_panels]
        raw = SettingsManager.instance().get_str("tm.panel.order", "")
        order: list[str] = []
        try:
            loaded = json.loads(raw) if raw else []
            if isinstance(loaded, list):
                order = [str(k) for k in loaded if str(k) in known]
        except (TypeError, ValueError):
            order = []
        for key in PANEL_KEYS:
            if key in known and key not in order:
                order.append(key)
        for key in known:
            if key not in order:
                order.append(key)
        return order

    def _save_panel_order(self, order: list[str]) -> None:
        SettingsManager.instance().set("tm.panel.order", json.dumps(order))

    def panel_zone(self, key: str) -> str:
        zones = self._panel_zones()
        zone = zones.get(key, "right")
        return zone if zone in ("right", "below") else "right"

    def _panel_zones(self) -> dict:
        raw = SettingsManager.instance().get_str("tm.panel.zones", "{}")
        try:
            data = json.loads(raw) if raw else {}
        except (TypeError, ValueError):
            data = {}
        return data if isinstance(data, dict) else {}

    def _set_panel_zone(self, key: str, zone: str) -> None:
        zones = self._panel_zones()
        zones[key] = zone if zone in ("right", "below") else "right"
        SettingsManager.instance().set("tm.panel.zones", json.dumps(zones))

    def _panels_by_zone(self):
        sm = SettingsManager.instance()
        by_key = {key: (title, w, key) for title, w, key in self._right_panels}
        right, below = [], []
        for key in self._panel_order():
            if key not in by_key:
                continue
            if not sm.get_bool(f"tm.panel.show.{key}", True):
                continue
            item = by_key[key]
            if self.panel_zone(key) == "below":
                below.append(item)
            else:
                right.append(item)
        return right, below

    def _below_rows(self) -> list[list[str]]:
        raw = SettingsManager.instance().get_str("tm.panel.below.rows", "[]")
        try:
            data = json.loads(raw) if raw else []
        except (TypeError, ValueError):
            data = []
        if not isinstance(data, list):
            return []
        rows = []
        seen = set()
        for row in data:
            if not isinstance(row, list):
                continue
            clean = []
            for key in row:
                key = str(key)
                if key in seen:
                    continue
                seen.add(key)
                clean.append(key)
            if clean:
                rows.append(clean)
        return rows

    def _save_below_rows(self, rows: list[list[str]]) -> None:
        SettingsManager.instance().set(
            "tm.panel.below.rows",
            json.dumps([[k for k in row] for row in rows if row]))

    def _remove_from_below_rows(self, key: str) -> list[list[str]]:
        rows = []
        for row in self._below_rows():
            row = [k for k in row if k != key]
            if row:
                rows.append(row)
        return rows

    def place_panel(self, key: str, zone: str | None = None, before: str | None = None,
                    beside: str | None = None, side: str | None = None) -> None:
        """Przenosi panel: kolejność, strefa, oraz obok/pod innym panelem."""
        known = {k for _t, _w, k in self._right_panels}
        if key not in known:
            return
        order = self._panel_order()
        if key in order:
            order.remove(key)
        if before and before in order:
            order.insert(order.index(before), key)
        elif beside and beside in order:
            idx = order.index(beside)
            order.insert(idx if side in ("left", "above") else idx + 1, key)
        elif zone:
            zones = self._panel_zones()
            last = -1
            for i, k in enumerate(order):
                if zones.get(k, "right") == zone:
                    last = i
            order.insert(last + 1, key)
        else:
            order.append(key)
        self._save_panel_order(order)

        rows = self._remove_from_below_rows(key)
        if zone == "right":
            self._set_panel_zone(key, "right")
            self._save_below_rows(rows)
        elif zone == "below" or beside:
            self._set_panel_zone(key, "below")
            if beside:
                self._set_panel_zone(beside, "below")
                if not any(beside in row for row in rows):
                    rows.append([beside])
                placed = False
                new_rows = []
                for row in rows:
                    if beside not in row:
                        new_rows.append(row)
                        continue
                    if side in ("left", "right"):
                        pos = row.index(beside)
                        row = [k for k in row if k != key]
                        pos = row.index(beside)
                        row.insert(pos if side == "left" else pos + 1, key)
                        new_rows.append(row)
                    elif side == "above":
                        new_rows.append([key])
                        new_rows.append(row)
                    else:
                        new_rows.append(row)
                        new_rows.append([key])
                    placed = True
                if not placed:
                    new_rows.append([key])
                rows = new_rows
            else:
                # Cała szerokość — własny rząd.
                rows.append([key])
            self._save_below_rows(rows)
        self.apply_panel_layout()

    def nudge_panel(self, key: str, delta: int) -> None:
        if self.panel_zone(key) == "below":
            rows = [list(r) for r in self._below_rows()]
            for r, row in enumerate(rows):
                if key not in row:
                    continue
                i = row.index(key)
                j = i + int(delta)
                if 0 <= j < len(row):
                    row[i], row[j] = row[j], row[i]
                    rows[r] = row
                    self._save_below_rows(rows)
                    self.apply_panel_layout()
                    return
            return
        order = self._panel_order()
        zone = self.panel_zone(key)
        group = [k for k in order if self.panel_zone(k) == zone]
        if key not in group:
            return
        i = group.index(key)
        j = i + int(delta)
        if j < 0 or j >= len(group):
            return
        group[i], group[j] = group[j], group[i]
        it = iter(group)
        merged = []
        for k in order:
            if self.panel_zone(k) == zone:
                merged.append(next(it))
            else:
                merged.append(k)
        self._save_panel_order(merged)
        self.apply_panel_layout()

    def _rebuild_below_panels(self, visible_below) -> None:
        host = getattr(self, "_below_host", None)
        if host is None:
            return
        layout = host.layout()
        keep = {getattr(self, "_below_hint", None), getattr(self, "_below_grip", None)}
        if layout is not None:
            for index in range(layout.count() - 1, -1, -1):
                item = layout.itemAt(index)
                widget = item.widget() if item is not None else None
                if widget is not None and widget not in keep:
                    layout.takeAt(index)
                    widget.setParent(None)
                    widget.deleteLater()
        self._below_stack = None
        self._below_scroll = None
        if not visible_below:
            if getattr(self, "_below_grip", None) is not None:
                self._below_grip.hide()
            self._below_hint.show()
            host.setMinimumHeight(22)
            host.setMaximumHeight(28)
            root = getattr(self, "_root_split", None)
            if root is not None and root.count() == 2:
                total = sum(root.sizes()) or 600
                root.setSizes([max(200, total - 36), 36])
            return
        self._below_hint.hide()
        if getattr(self, "_below_grip", None) is not None:
            self._below_grip.show()
        host.setMaximumHeight(16777215)
        host.setMinimumHeight(64)
        host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        by_key = {key: (title, w, key) for title, w, key in visible_below}
        rows = []
        used = set()
        for row in self._below_rows():
            clean = [k for k in row if k in by_key and k not in used]
            if clean:
                rows.append(clean)
                used.update(clean)
        leftover = [k for title, w, k in visible_below if k not in used]
        for k in leftover:
            rows.append([k])
        if not rows:
            return

        preferred = self._right_panel_preferred_height()
        row_min = 72
        outer = ExpandingSplitter(Qt.Orientation.Vertical)
        outer._panel_min = row_min
        outer._soft_min = True
        outer.setChildrenCollapsible(False)
        outer.setHandleWidth(max(8, outer.handleWidth()))
        for row in rows:
            hs = QSplitter(Qt.Orientation.Horizontal)
            hs.setChildrenCollapsible(False)
            hs.setHandleWidth(max(8, hs.handleWidth()))
            hs.setMinimumHeight(row_min)
            hs.setMaximumHeight(16777215)
            hs.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            for key in row:
                title, w, _k = by_key[key]
                grp = DockableGroup(title, key, self)
                grp.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
                grp.setMinimumHeight(row_min)
                grp.setMaximumHeight(16777215)
                gl = QVBoxLayout(grp)
                gl.setContentsMargins(4, 2, 4, 4)
                gl.setSpacing(3)
                gl.addWidget(w)
                hs.addWidget(grp)
            for i in range(hs.count()):
                hs.setStretchFactor(i, 1)
                hs.setCollapsible(i, False)
            outer.addWidget(hs)
        tail = QWidget()
        tail.setObjectName("sc_right_tail")
        tail.setMinimumHeight(0)
        tail.setMaximumHeight(0)
        outer.addWidget(tail)
        outer.setCollapsible(outer.count() - 1, True)
        mins = [row_min] * (outer.count() - 1) + [0]
        setup_splitter(outer, minimums=mins)
        outer.setCollapsible(outer.count() - 1, True)
        init = [max(row_min, preferred)] * (outer.count() - 1) + [0]
        outer.setSizes(init)

        scroll = QScrollArea()
        scroll.setWidgetResizable(False)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setWidget(outer)
        scroll.installEventFilter(self)
        if scroll.viewport() is not None:
            scroll.viewport().installEventFilter(self)
        layout.addWidget(scroll, 1)
        self._below_stack = outer
        self._below_scroll = scroll
        extra = outer.handleWidth() * max(0, outer.count() - 1)
        outer.setMinimumHeight(row_min)
        outer.splitterMoved.connect(lambda *_a: self._sync_below_stack_size())
        self._sync_below_stack_size()
        root = getattr(self, "_root_split", None)
        if root is not None and root.count() == 2:
            sizes = root.sizes()
            total = sum(sizes) or 700
            if sizes[1] < 160:
                root.setSizes([max(240, total - 240), 240])

    def _sync_below_stack_size(self) -> None:
        """Suwak na dole: panele zachowują wysokość, nadmiar się przewija."""
        stack = getattr(self, "_below_stack", None)
        scroll = getattr(self, "_below_scroll", None)
        if stack is None or not stack.count():
            return
        row_min = int(getattr(stack, "_panel_min", 72) or 72)
        extra = stack.handleWidth() * max(0, stack.count() - 1)
        raw = list(stack.sizes())
        sizes = []
        real = 0
        for index in range(stack.count()):
            child = stack.widget(index)
            dummy = (child is not None and child.objectName() == "sc_right_tail")
            if dummy:
                sizes.append(0)
                continue
            if child is not None:
                child.setMinimumHeight(row_min)
            real += 1
            if index < len(raw) and raw[index] > 0:
                sizes.append(max(row_min, int(raw[index])))
            else:
                sizes.append(row_min)
        content = sum(sizes) + extra
        width = stack.width() or self.width()
        viewport_h = 0
        if scroll is not None and scroll.viewport() is not None:
            vw = scroll.viewport().width()
            viewport_h = scroll.viewport().height()
            if vw > 0:
                width = vw
        # Wolne miejsce w pasie (np. jeden rząd TM | zdania) → powiększ
        # rzędy, zamiast zostawiać pustkę. Gdy brakuje miejsca — suwak.
        spare = max(0, viewport_h - content)
        if spare and real:
            add, rem = divmod(spare, real)
            filled = []
            given = 0
            for index, value in enumerate(sizes):
                child = stack.widget(index)
                dummy = (child is not None and child.objectName() == "sc_right_tail")
                if dummy:
                    filled.append(0)
                    continue
                extra_px = add + (1 if given < rem else 0)
                given += 1
                filled.append(value + extra_px)
            sizes = filled
            content = sum(sizes) + extra
        height = max(content, viewport_h or content)
        stack.setMinimumHeight(row_min)
        if stack.width() != width or stack.height() != height:
            stack.resize(max(1, width), max(1, height))
        if list(stack.sizes()) != sizes:
            stack.setSizes(sizes)

    def apply_panel_layout(self) -> None:
        """Układa panele po prawej: wszystko naraz (stacked) lub zakładki.

        Układ: ``tm.panel.layout``; widoczność poszczególnych paneli:
        ``tm.panel.show.<klucz>``. Boxy są budowane raz — przy przełączeniu
        tylko przenosimy je do nowego kontenera, więc stan (lista wyników,
        notatki) zostaje.
        """
        sm = SettingsManager.instance()
        mode = sm.get_str("tm.panel.layout", "stacked")
        visible_right, visible_below = self._panels_by_zone()
        visible = [(title, w) for title, w, _k in visible_right]
        # Szerokość prawej kolumny PRZED przełączaniem. Nowy kontener wchodzi
        # do splittera z minimalną szerokością (180 px), więc bez tego panel
        # po każdej zmianie układu zwężał się do minimum i wyglądał na pusty.
        prev = self.main_splitter.sizes()
        prev_left = prev[0] if len(prev) > 0 else 0
        prev_center = prev[1] if len(prev) > 1 else 0
        prev_right = prev[2] if len(prev) > 2 else 0
        # wypnij boxy ze starego kontenera (przeżyją deleteLater)
        for _title, w, _key in self._right_panels:
            w.setParent(None)
        old = getattr(self, "_right_container", None)
        if old is not None:
            # QSplitter nie ma removeWidget — odpinamy rodzica, splitter
            # samo oczyści handle (childEvent), a kontener idzie do kosza.
            old.setParent(None)
            old.deleteLater()
        self._right_stack = None
        if mode == "tabs":
            container = QTabWidget()
            # zakładki PO LEWEJ (pionowo) — w jednym rzędzie (North)
            # 7 kart się nie mieści i się przycina; pionowo są „3 i poniżej 3”
            container.setTabPosition(QTabWidget.TabPosition.West)
            container.tabBar().setExpanding(False)
            for title, w in visible:
                container.addTab(w, title)
        else:
            container = QScrollArea()
            container.setWidgetResizable(False)
            container.setFrameShape(QFrame.Shape.NoFrame)
            container.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            container.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            # Pionowy splitter, który NIE zgniata sąsiadów: przeciągnięcie
            # powiększa jeden panel, reszta zjeżdża w dół, a pasek
            # QScrollArea (ten od kolumny) się wydłuża.
            stack = ExpandingSplitter(Qt.Orientation.Vertical)
            for title, w, key in visible_right:
                grp = DockableGroup(title, key, self)
                grp.setSizePolicy(QSizePolicy.Policy.Preferred,
                                  QSizePolicy.Policy.Minimum)
                gl = QVBoxLayout(grp)
                gl.setContentsMargins(4, 2, 4, 4)
                gl.setSpacing(3)
                gl.addWidget(w)
                stack.addWidget(grp)
            # Atrapa pod spodem — uchwyt POD notatkami, żeby dało się je
            # powiększyć (zwykły splitter nie ma uchwytu za ostatnim panelem).
            tail = QWidget()
            tail.setObjectName("sc_right_tail")
            tail.setMinimumHeight(0)
            tail.setMaximumHeight(0)
            tail.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            stack.addWidget(tail)
            stack.setCollapsible(stack.count() - 1, True)
            preferred = self._right_panel_preferred_height()
            stack._panel_min = preferred
            mins = [preferred] * (stack.count() - 1) + [0]
            setup_splitter(stack, minimums=mins)
            stack.setCollapsible(stack.count() - 1, True)
            stack.setHandleWidth(max(8, stack.handleWidth()))
            for handle_index in range(1, stack.count()):
                handle = stack.handle(handle_index)
                if handle is None:
                    continue
                handle.setToolTip(
                    "Przeciągnij w dół, żeby powiększyć panel NAD kreską "
                    "(TM — kreska pod TM). Reszta zjedzie niżej.")
            container.setWidget(stack)
            container.installEventFilter(self)
            if container.viewport() is not None:
                container.viewport().installEventFilter(self)
            self._right_stack = stack
            self._fit_right_stack()
        self._right_container = container
        container.setAcceptDrops(True)
        viewport = getattr(container, "viewport", lambda: None)()
        if viewport is not None:
            viewport.setAcceptDrops(True)
        container.installEventFilter(self)
        self.main_splitter.insertWidget(self.main_splitter.count(), container)
        # Kontener wchodzi do splittera PO setup_splitter() — musi sam
        # zadbać o minimum i niemożność zwinięcia (inaczej znika do zera).
        idx = self.main_splitter.count() - 1
        self.main_splitter.setCollapsible(idx, False)
        container.setMinimumWidth(self._right_column_min_width())
        self.main_splitter.setStretchFactor(idx, 2)
        from ..ui.theme import style_splitter_handle
        style_splitter_handle(self.main_splitter.handle(idx - 1))
        # Rozmiary kolumn po przełączeniu układu — bez tego nowy kontener
        # startuje z zerem i panele „przestają pokazywać wartości”.
        self._restore_split_sizes()
        if prev_right > container.minimumWidth():
            # Mamy żywą szerokość sprzed przełączenia — jest wiarygodniejsza
            # niż zapisana w ustawieniach (tę Qt i tak właśnie nadpisał).
            self._set_split_sizes(prev_left, prev_center, prev_right)
            # Przełączanie nie emituje splitterMoved, więc zapisujemy sami
            # (tylko tutaj — przy pierwszym budowaniu okna nie ma jeszcze
            # czego zapisywać, a zapis nadpisałby domyślne proporcje).
            self._save_split_sizes()
        # Panele PO przełączeniu muszą być pokazane z powrotem:
        # * setParent(None) chowa widget „na sztywno” – Qt zapamiętuje, że
        #   został ukryty, i nie pokazuje go, gdy trafi do nowego kontenera,
        # * w zakładkach QTabWidget chowa wszystkie karty poza bieżącą.
        # Bez tego po zmianie układu prawa strona była pusta.
        if self._right_stack is not None:
            # Wysokości paneli: zapamiętane z poprzedniej sesji i na bieżąco.
            # Złapane TUTAJ (po wstawieniu do splittera), bo dopiero teraz
            # splitter ma prawdziwą wysokość i setSizes() ma się do czego
            # odnieść — Qt i tak zachowa proporcje, gdy okno jest inne.
            if not self._restore_panel_heights():
                preferred = self._right_panel_preferred_height()
                init = []
                for index in range(self._right_stack.count()):
                    child = self._right_stack.widget(index)
                    dummy = (child is not None and child.objectName() == "sc_right_tail")
                    init.append(0 if dummy else preferred)
                self._right_stack.setSizes(init)
            self._right_stack.splitterMoved.connect(self._on_right_stack_moved)
            self._sync_right_stack_size()
        for _title, widget in visible:
            widget.show()
        for _title, widget, _k in visible_below:
            widget.show()
        if isinstance(container, QTabWidget):
            current = container.currentIndex()
            for page_index in range(container.count()):
                page = container.widget(page_index)
                if page is not None:
                    page.setVisible(page_index == current)
        self.apply_panel_font()
        self._rebuild_below_panels(visible_below)
        # Na wszelki wypadek odśwież panele podpowiedzi dla bieżącego
        # segmentu (przenoszenie widжетów nie powinno nic gubić, ale przy
        # przełączaniu układu wartości muszą wrócić na pewno).
        if self.current_index >= 0 and len(self.segments) > self.current_index:
            self.load_segment(self.current_index)

    def apply_panel_font(self) -> None:
        """Wielkość czcionki w prawym panelu (TM / zdania / terminy / …).

        Ustawienia: ``tm.panel.font.size`` dla wszystkich paneli naraz oraz
        ``tm.panel.font.<klucz>`` (matches, sentences, terms, conc, mt, lang,
        notes) dla każdego z osobna. Zero = czcionka aplikacji. Obejmuje
        wszystko w panelu — listy, etykiety, przyciski, podgląd MT, notatki
        (dawniej tylko cztery listy, więc zmiana była ledwo widoczna).

        Oryginalna czcionka każdej kontrolki jest zapisana w jej właściwości
        Qt — dzięki temu powrót do zera przywraca wyjściowy wygląd, a
        przeliczenie można powtórzyć dowolną liczbę razy.
        """
        settings = SettingsManager.instance()
        size = settings.get_int("tm.panel.font.size", 0)
        # Najpierw wspólny rozmiar dla CAŁEGO kontenera (obejmuje też ramki
        # i tytuły paneli), a potem — nad nim — rozmiary poszczególnych
        # paneli. Odwrotna kolejność kasowałaby ustawienia per panel,
        # bo kontener jest rodzicem wszystkich paneli naraz.
        # _build_ui woła to jeszcze przed zbudowaniem kontenera.
        container = getattr(self, "_right_container", None)
        if container is not None:
            self._apply_font_to_panel(container, size)
        for title, root, key in self._right_panels:
            own = settings.get_int(f"tm.panel.font.{key}", 0)
            self._apply_font_to_panel(root, own if own > 0 else size)
        # Po zmianie czcionki panele muszą dostać nowe minima — inaczej
        # większy tekst znowu wychodzi poza ramkę.
        self._fit_right_stack()

    def _apply_font_to_panel(self, root: QWidget, size: int) -> None:
        """Ustawia czcionkę w jednym panelu (i wszystkim, co w nim siedzi)."""
        for widget in [root, *root.findChildren(QWidget)]:
            base = widget.property("sc_base_font")
            if not isinstance(base, QFont):
                base = QFont(widget.font())
                widget.setProperty("sc_base_font", base)
            if size > 0:
                font = QFont(base)
                font.setPointSize(size)
                widget.setFont(font)
            else:
                # Zero = czcionka programu. Bierzemy ją na żywo, żeby panel
                # rósł razem z całym interfejsem (ustawienie „Czcionka
                # interfejsu”), a nie zostawał przy tej z pierwszego startu.
                application = QApplication.instance()
                widget.setFont(QFont(application.font())
                               if application is not None else QFont(base))
            # Etykiety z własnym arkuszem („font-size: 11px”) ignorują
            # setFont — im zmieniamy rozmiar w samym arkuszu stylów.
            sheet = widget.styleSheet()
            if "font-size" in sheet:
                original = widget.property("sc_base_sheet")
                if not isinstance(original, str):
                    original = sheet
                    widget.setProperty("sc_base_sheet", original)
                new_sheet = (_scale_css_font_size(original, size, base)
                             if size > 0 else original)
                if new_sheet != sheet:
                    widget.setStyleSheet(new_sheet)

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

    FILE_MARKER_SYMBOLS = {"ok": "✓", "warn": "⚠️", "bad": "✗"}

    @staticmethod
    def _file_label(name: str, done: int, total: int, skipped: int = 0,
                    marker: str = "") -> str:
        # Pominięte wypadają z licznika – same liczby wystarczą, bez dodatkowych
        # oznaczeń, żeby lista plików pozostała czytelna.
        percent = int(done * 100 / total) if total else 0
        mark = "✅" if total and done == total else "📄"
        msym = EditorTab.FILE_MARKER_SYMBOLS.get(marker, "")
        return f"{msym} {mark} {name}  ({done}/{total} • {percent}%)".strip()

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
        markers = (getattr(project, "file_markers", None) or {}) if project else {}
        for name in names:
            done, total, skipped = counters[name]
            it = QListWidgetItem(
                self._file_label(name, done, total, skipped, markers.get(name, "")))
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
        project = getattr(self.app, "project", None)
        markers = (getattr(project, "file_markers", None) or {}) if project else {}
        for row in range(self.files_list.count()):
            item = self.files_list.item(row)
            name = item.data(Qt.ItemDataRole.UserRole)
            if name is None:
                text = self._all_files_label(total_done, total_todo, total_skip)
            else:
                done, total, skipped = counters.get(name, (0, 0, 0))
                text = self._file_label(name, done, total, skipped,
                                        markers.get(name, ""))
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

    def _reapply_tm_to_file(self, file_name: Optional[str]) -> None:
        """TM jeszcze raz po WSZYSTKICH segmentach — także przetłumaczonych.

        Zwykłe „Zastosuj TM” pomija to, co już przetłumaczone. Ta opcja
        podmienia istniejące tłumaczenia na najlepsze dopasowanie z pamięci,
        więc najpierw pytamy, ile segmentów to obejmie i czy na pewno
        (★ zatwierdzonych nie ruszamy).
        """
        sm = SettingsManager.instance()
        threshold = sm.get_int("auto.insert.threshold", 80)
        label = file_name or "wszystkich plików"
        count = sum(
            1 for s in self.segments
            if not s.ignored and s.status != "approved" and (s.target or "").strip()
            and (file_name is None or (s.file_name or "(bez pliku)") == file_name))
        if not count:
            QMessageBox.information(
                self, "Zastosuj TM ponownie",
                "Nie ma segmentów z tłumaczeniem, które można podmienić.")
            return
        answer = QMessageBox.question(
            self, "Zastosuj TM ponownie",
            f"W „{label}” jest <b>{count}</b> segmentów z tłumaczeniem.\n\n"
            f"Każde z nich zostanie podmienione na najlepsze dopasowanie z TM "
            f"(próg {threshold}% — zmienisz go w <i>Ustawienia → Pamięć TM</i>).\n"
            "• segmenty ★ zatwierdzone zostaną pominięte,\n"
            "• to, co wpisałeś ręcznie, może zostać nadpisane.\n\n"
            "Kontynuować?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            self.status_message.emit("Zastosuj TM ponownie — przerwane")
            return
        self.app.apply_tm_to_all(only_file=file_name, include_translated=True)

    def _files_context_menu(self, pos) -> None:
        """Menu podręczne listy plików (prawy przycisk myszy)."""
        item = self.files_list.itemAt(pos)
        if item is None:
            return
        file_name = item.data(Qt.ItemDataRole.UserRole)   # None = „Wszystkie pliki”
        segments = [s for s in self.segments
                    if file_name is None or (s.file_name or "(bez pliku)") == file_name]
        pending = sum(1 for s in segments if not s.is_translated and not s.ignored)
        # Segmenty, w których TM może PODMIENIĆ istniejące tłumaczenie
        # (zatwierdzonych ★ nie ruszamy — to gotowa, sprawdzona praca).
        done = sum(1 for s in segments
                   if not s.ignored and s.status != "approved" and (s.target or "").strip())
        label = file_name or "wszystkich plików"

        menu = QMenu(self)
        act_tm = menu.addAction(f"💡 Zastosuj TM do „{label}” ({pending} pustych)")
        act_tm.setEnabled(pending > 0 and self.app.tm.is_initialized)
        act_tm_again = menu.addAction(
            f"🔁 Zastosuj TM ponownie – „{label}” ({done} z tłumaczeniem)")
        act_tm_again.setToolTip(
            "Podmienia istniejące tłumaczenia na najlepsze dopasowania z TM.\n"
            "Przydatne, gdy do pamięci doszły lepsze wpisy.\n"
            "Segmenty ★ zatwierdzone są pomijane.")
        act_tm_again.setEnabled(done > 0 and self.app.tm.is_initialized)
        act_mt = menu.addAction(f"🤖 Przetłumacz maszynowo „{label}” ({pending} pustych)")
        act_mt.setEnabled(pending > 0)
        menu.addSeparator()
        act_show = menu.addAction("👁️ Pokaż tylko ten plik" if file_name else "👁️ Pokaż wszystkie")
        act_find = menu.addAction(f"🔍 Szukaj w „{label}”…")
        act_stats = menu.addAction("📊 Statystyki pliku")
        menu.addSeparator()
        if file_name:
            proj = getattr(self.app, "project", None)
            if proj is not None and getattr(proj, "file_markers", None) is not None:
                cur = proj.file_markers.get(file_name, "")
                for key, title in (("", "🏷️ Znacznik: brak"),
                                   ("ok", "🏷️ Znacznik: ✓ sprawdzone"),
                                   ("warn", "🏷️ Znacznik: ⚠️ uwaga"),
                                   ("bad", "🏷️ Znacznik: ✗ problem")):
                    act_mk = menu.addAction(
                        ("✓ " if cur == key else "   ") + title)
                    act_mk.triggered.connect(
                        lambda _c, k=key, n=file_name: self._set_file_marker(n, k))
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
        elif chosen == act_tm_again:
            self._reapply_tm_to_file(file_name)
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
        self._restore_last_segment()

    def _show_all_files(self) -> None:
        self._file_filter = None
        if self.files_list.count():
            self.files_list.setCurrentRow(0)
        self.refresh_grid()
        self._restore_last_segment()

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
            if status == "Do przetłumaczenia" and seg.status != "todo":
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
        from ..core import shortcuts as _sc_find
        act_find_file = menu.addAction(_sc_find.with_shortcut("find_in_file", "🔎 Szukaj tylko w tym pliku"))
        menu.addSeparator()
        selected_now = self.selected_indices()
        many = f" ({len(selected_now)})" if len(selected_now) > 1 else ""
        status_menu = menu.addMenu(f"🏷️ Oznacz jako…{many}")
        act_new = status_menu.addAction("○ nowy")
        act_todo = status_menu.addAction("🔵 do przetłumaczenia")
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
        if action == act_todo:
            self.mark_todo()
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
        self._remember_last_segment()
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
            self.matches_info.show(); self.matches_info.setText("⏳ Szukanie dopasowań…")
        else:
            self.matches_info.show(); self.matches_info.setText("Brak pamięci TM (otwórz projekt)")
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

    def next_todo(self) -> None:
        """Następny segment oznaczony „do przetłumaczenia” (skok między nimi)."""
        self._jump_to(lambda seg: seg.status == "todo" and not seg.ignored,
                      forward=True, what="„do przetłumaczenia”")

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

    def mark_todo(self) -> None:
        """Oznacza segmenty „do przetłumaczenia” — wrócę do nich później."""
        self.set_status(self.selected_indices(), "todo")

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
        ("todo", "🔵 oznacz jako DO PRZETŁUMACZENIA"),
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
            from ..core.tags import (DEFAULT_LINE_BREAKS, DEFAULT_PARA_BREAKS,
                                     parse_break_codes)
            _sm_codes = SettingsManager.instance()
            _line = parse_break_codes(
                _sm_codes.get_str("tm.adapt.line.codes", "\\n \\l"),
                DEFAULT_LINE_BREAKS)
            _para = parse_break_codes(
                _sm_codes.get_str("tm.adapt.para.codes", "\\p"),
                DEFAULT_PARA_BREAKS)
            from ..core.tags import effective_break_codes, parse_code_list
            _esc, _inl = parse_code_list(_sm_codes.get_str("tm.codes.list", ""))
            _line, _para = effective_break_codes(
                seg.source, _line, _para,
                extra_codes=_esc, auto_detect=not (_esc or _inl))
            new_text = adapt_codes(seg.source, seg.target, _line, _para,
                                   smart=_sm_codes.get_bool("tm.adapt.codes.smart", True))
            if _sm_codes.get_bool("tm.adapt.long.lines", True):
                from ..core.tags import ensure_line_widths
                new_text = ensure_line_widths(seg.source, new_text, _line, _para)
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
            self.matches_info.show(); self.matches_info.setText("Podpowiedzi z pamięci TM wyłączone w Ustawieniach")
            return

        seg = self.current_segment()
        tm = self.app.tm
        if not seg or not tm.is_initialized:
            self.matches_list.clear()
            self.sentence_list.clear()
            self.matches_info.show(); self.matches_info.setText("Brak pamięci TM (otwórz projekt)")
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
        self.matches_info.show(); self.matches_info.setText("⏳ Szukanie dopasowań…")
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
            self.matches_info.show(); self.matches_info.setText(f"Brak dopasowań ≥ {threshold}%  (TM: {tm.size()} wpisów)")
            return
        self.matches_info.show(); self.matches_info.setText(
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
            # Na ekranie tekst BEZ znaczników (<<kon>>, {PLAYER}) — do
            # wstawienia idzie pełna wersja, żeby plik zachował kodowanie
            # oryginału. Znaczniki widać w podpowiedzi po najechaniu myszą.
            shown = _strip_codes(match.assembled)
            if match.line_pairs:
                # rozbicie linia po linii – najczytelniejsza postać dla plików gier
                lines = "\n".join(
                    f"      {_strip_codes(src)}\n          → {_strip_codes(tgt)}"
                    for src, tgt in match.line_pairs
                )
                text = (
                    f"[{match.label}]\n"
                    f"{lines}\n"
                    f"      ⤵ całość: {shown}"
                )
            else:
                label = "złożenie z kilku fragmentów" if " + " in match.fragment_source else "fragment z TM"
                text = (
                    f"[{match.label}] {shown}\n"
                    f"      {label}: {_strip_codes(match.fragment_source)}"
                    f" → {_strip_codes(match.fragment_target)}"
                )
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, match.assembled)
            item.setToolTip(
                f"{match.assembled}\n\n(fragment: {match.fragment_source}"
                f" → {match.fragment_target})")
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
        # characterCount() liczy też znak końca akapitu — max pozycja to count-1.
        limit = max(0, editor.document().characterCount() - 1)
        try:
            start_i = max(0, min(int(start), limit))
            end_i = max(start_i, min(int(end), limit))
        except (TypeError, ValueError):
            start_i = end_i = 0
        cursor.setPosition(start_i)
        if end_i != start_i:
            cursor.setPosition(end_i, QTextCursor.MoveMode.KeepAnchor)
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
        """Nadaje tłumaczeniu takie wcięcie, jakie ma źródło (przycisk / skrót)."""
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
        try:
            opts = language_underline_settings()
            if not opts["enabled"]:
                self._apply_target_selections()
                return

            body = self.target_edit.toPlainText()
            for issue in issues or []:
                try:
                    start = int(getattr(issue, "offset", -1))
                    length = int(getattr(issue, "length", 0) or 0)
                except (TypeError, ValueError):
                    start, length = -1, 0
                if start < 0 or length <= 0:
                    fragment = getattr(issue, "fragment", "") or ""
                    if not fragment:
                        continue
                    found = re.search(rf"(?<!\w){re.escape(fragment)}(?!\w)", body)
                    if not found:
                        continue
                    start, length = found.start(), found.end() - found.start()
                if start < 0 or length <= 0 or start >= len(body):
                    continue
                if start + length > len(body):
                    length = len(body) - start
                color = opts["colors"].get(getattr(issue, "severity", ""), opts["colors"]["info"])
                fmt = QTextCharFormat()
                # Stare podkreślenie Qt zostaje, gdy nowe (grube) jest wyłączone.
                # Przy włączonym nowym nie dublujemy cienkiej falki pod grubą.
                if opts.get("custom"):
                    fmt.setUnderlineStyle(QTextCharFormat.UnderlineStyle.NoUnderline)
                else:
                    fmt.setUnderlineStyle(opts["qt_style"])
                fmt.setUnderlineColor(QColor(color))
                try:
                    fmt.setToolTip(issue.describe())
                except Exception:
                    pass
                if opts["background"]:
                    bg = QColor(color)
                    bg.setAlpha(55)
                    fmt.setBackground(bg)
                self._lang_selections.append(
                    self._selection(self.target_edit, start, start + length, fmt))
            self._apply_target_selections()
        except Exception:
            self._lang_selections = []
            try:
                self._apply_target_selections()
            except Exception:
                pass

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
        if hasattr(self, "target_edit"):
            self.target_edit.viewport().update()

    def _paint_language_underlines(self, editor: QPlainTextEdit) -> None:
        """Rysuje podkreślenie o wybranej grubości (falka Qt jest zawsze cienka)."""
        opts = language_underline_settings()
        if not opts["enabled"] or not opts.get("custom") or opts["thickness"] < 1:
            return
        issues = getattr(self, "_lang_issues", None) or []
        if not issues:
            return
        viewport = editor.viewport()
        painter = QPainter()
        if not painter.begin(viewport):
            return
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            thickness = opts["thickness"]
            style = opts["style"]
            body = editor.toPlainText()
            limit = len(body)
            for issue in issues:
                try:
                    start = int(getattr(issue, "offset", -1))
                    length = int(getattr(issue, "length", 0) or 0)
                except (TypeError, ValueError):
                    continue
                if start < 0 or length <= 0:
                    fragment = getattr(issue, "fragment", "") or ""
                    if not fragment:
                        continue
                    found = re.search(rf"(?<!\w){re.escape(fragment)}(?!\w)", body)
                    if not found:
                        continue
                    start, length = found.start(), found.end() - found.start()
                end = start + length
                if start < 0 or start >= limit or start >= end:
                    continue
                end = min(end, limit)
                color = opts["colors"].get(getattr(issue, "severity", ""), opts["colors"]["info"])
                self._paint_range_underline(editor, painter, start, end, color, thickness, style)
        finally:
            if painter.isActive():
                painter.end()

    def _paint_range_underline(self, editor, painter, start: int, end: int,
                               color: str, thickness: int, style: str) -> None:
        document = editor.document()
        block = document.findBlock(start)
        offset = editor.contentOffset()
        while block.isValid() and block.position() < end:
            layout = block.layout()
            if layout is None:
                block = block.next()
                continue
            block_pos = block.position()
            if block.length() <= 0 or layout.lineCount() <= 0:
                block = block.next()
                continue
            origin = editor.blockBoundingGeometry(block).translated(offset).topLeft()
            local_start = max(0, start - block_pos)
            local_end = min(max(0, block.length() - 1), end - block_pos)
            for line_index in range(layout.lineCount()):
                line = layout.lineAt(line_index)
                if not line.isValid():
                    continue
                ls = line.textStart()
                ll = line.textLength()
                a = max(local_start, ls)
                b = min(local_end, ls + ll)
                if a >= b:
                    continue
                x1 = origin.x() + self._line_cursor_x(line, a)
                x2 = origin.x() + self._line_cursor_x(line, b)
                y = origin.y() + line.y() + line.height() - max(2, thickness)
                self._stroke_underline(painter, x1, x2, y, color, thickness, style)
            block = block.next()

    @staticmethod
    def _line_cursor_x(line, pos: int) -> float:
        """cursorToX w PyQt6 bywa liczbą albo krotką (x, pos) — obie wersje."""
        try:
            value = line.cursorToX(int(pos))
        except Exception:
            return 0.0
        if isinstance(value, (tuple, list)):
            value = value[0] if value else 0.0
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _stroke_underline(painter, x1, x2, y, color: str, thickness: int, style: str) -> None:
        if x2 - x1 < 1:
            return
        pen = QPen(QColor(color), float(max(1, thickness)))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        if style == "dash":
            pen.setStyle(Qt.PenStyle.DashLine)
        elif style == "dot":
            pen.setStyle(Qt.PenStyle.DotLine)
        else:
            pen.setStyle(Qt.PenStyle.SolidLine)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if style == "wave":
            amp = max(2.0, thickness * 1.15)
            step = max(3.5, thickness * 2.2)
            path = QPainterPath()
            path.moveTo(x1, y)
            x = float(x1)
            sign = 1
            while x < x2:
                nx = min(float(x2), x + step)
                path.quadTo((x + nx) / 2, y + sign * amp, nx, y)
                x = nx
                sign *= -1
            painter.drawPath(path)
        else:
            painter.drawLine(int(x1), int(y), int(x2), int(y))

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
