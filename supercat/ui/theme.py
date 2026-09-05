"""Motywy (ciemny / jasny) w stylu Supervertaler Workbench."""
from __future__ import annotations

from PyQt6.QtCore import Qt

DARK = """
QWidget { background-color: #1f2126; color: #e6e6e6; font-size: 13px; }
QMainWindow, QDialog { background-color: #1b1d21; }
QMenuBar { background-color: #23262b; padding: 2px; }
QMenuBar::item { padding: 5px 10px; background: transparent; }
QMenuBar::item:selected { background: #2f7fd1; border-radius: 4px; }
QMenu { background-color: #23262b; border: 1px solid #3a3f46; padding: 4px; }
QMenu::item { padding: 6px 24px 6px 20px; }
QMenu::item:selected { background: #2f7fd1; border-radius: 4px; }
QToolBar { background: #23262b; border: 0; spacing: 4px; padding: 4px; }
QToolButton { padding: 5px 9px; border-radius: 6px; }
QToolButton:hover { background: #32363d; }
QTabWidget::pane { border: 1px solid #3a3f46; border-radius: 6px; }
QTabBar::tab { padding: 8px 15px; background: transparent; border: 0; }
QTabBar::tab:selected { border-bottom: 2px solid #2196F3; background: rgba(33,150,243,0.10); }
QTabBar::tab:hover { background: rgba(255,255,255,0.05); }
QPushButton { background: #2d3138; border: 1px solid #3f444c; border-radius: 6px; padding: 6px 12px; }
QPushButton:hover { background: #3a4049; }
QPushButton:pressed { background: #2f7fd1; }
QPushButton:disabled { color: #777; }
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QComboBox {
    background: #262a30; border: 1px solid #3f444c; border-radius: 6px; padding: 5px;
    color: #e6e6e6;
    selection-background-color: #2f7fd1; selection-color: #ffffff;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus { border: 1px solid #2196F3; }
QTableWidget, QTableView, QTreeWidget, QListWidget {
    background: #232730; alternate-background-color: #262b34; gridline-color: #363b44;
    border: 1px solid #3a3f46; border-radius: 6px;
    selection-background-color: #2f7fd1; selection-color: #ffffff;
}
QTableWidget::item:selected, QTableView::item:selected,
QListWidget::item:selected, QTreeWidget::item:selected {
    background: #2f7fd1; color: #ffffff;
}
QTableWidget::item:selected:!active, QTableView::item:selected:!active,
QListWidget::item:selected:!active, QTreeWidget::item:selected:!active {
    background: #37536f; color: #ffffff;
}
QTableWidget::item:hover, QTableView::item:hover,
QListWidget::item:hover, QTreeWidget::item:hover {
    background: #313842; color: #ffffff;
}
QTableWidget::item:selected:hover, QTableView::item:selected:hover,
QListWidget::item:selected:hover, QTreeWidget::item:selected:hover {
    background: #3d8ee0; color: #ffffff;
}
QComboBox QAbstractItemView {
    background: #262a30; color: #e6e6e6;
    selection-background-color: #2f7fd1; selection-color: #ffffff;
}
QComboBox QAbstractItemView::item:hover { background: #313842; color: #ffffff; }
QHeaderView::section { background: #2b3038; padding: 6px; border: 0; border-right: 1px solid #363b44; }
QGroupBox { border: 1px solid #3a3f46; border-radius: 6px; margin-top: 14px; padding-top: 8px; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; color: #8ab4f8; }
QStatusBar { background: #23262b; }
QProgressBar { border: 1px solid #3f444c; border-radius: 6px; text-align: center; background: #262a30; }
QProgressBar::chunk { background: #2f7fd1; border-radius: 5px; }
QSplitter::handle { background: #2b3038; }
QSplitter::handle:hover { background: #2f7fd1; }
QSplitter::handle:horizontal { width: 6px; }
QSplitter::handle:vertical { height: 6px; }
QScrollBar:vertical { background: #1f2126; width: 12px; }
QScrollBar::handle:vertical { background: #3f444c; border-radius: 6px; min-height: 30px; }
QScrollBar:horizontal { background: #1f2126; height: 12px; }
QScrollBar::handle:horizontal { background: #3f444c; border-radius: 6px; min-width: 30px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
QCheckBox::indicator, QRadioButton::indicator { width: 15px; height: 15px; }
"""

LIGHT = """
QWidget { background-color: #f5f6f8; color: #1c1c1c; font-size: 13px; }
QMainWindow, QDialog { background-color: #eef0f3; }
QMenuBar { background-color: #ffffff; padding: 2px; }
QMenuBar::item:selected { background: #2f7fd1; color: white; border-radius: 4px; }
QMenu { background-color: #ffffff; border: 1px solid #d0d4da; padding: 4px; }
QMenu::item { padding: 6px 24px 6px 20px; }
QMenu::item:selected { background: #2f7fd1; color: white; border-radius: 4px; }
QToolBar { background: #ffffff; border: 0; spacing: 4px; padding: 4px; }
QToolButton { padding: 5px 9px; border-radius: 6px; }
QToolButton:hover { background: #e3e8ef; }
QTabWidget::pane { border: 1px solid #d0d4da; border-radius: 6px; background: #ffffff; }
QTabBar::tab { padding: 8px 15px; background: transparent; border: 0; }
QTabBar::tab:selected { border-bottom: 2px solid #1976d2; background: rgba(25,118,210,0.08); }
QPushButton { background: #ffffff; border: 1px solid #c6ccd4; border-radius: 6px; padding: 6px 12px; }
QPushButton:hover { background: #e8eef7; }
QPushButton:pressed { background: #cfe0f5; }
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QComboBox {
    background: #ffffff; border: 1px solid #c6ccd4; border-radius: 6px; padding: 5px;
    color: #1c1c1c;
    selection-background-color: #1976d2; selection-color: #ffffff;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus { border: 1px solid #1976d2; }
QTableWidget, QTableView, QTreeWidget, QListWidget {
    background: #ffffff; alternate-background-color: #f3f6fa; gridline-color: #dde1e7;
    border: 1px solid #d0d4da; border-radius: 6px;
    color: #1c1c1c;
    selection-background-color: #1976d2; selection-color: #ffffff;
}
/* Zaznaczony wiersz: biały tekst na niebieskim tle – także gdy lista straci fokus */
QTableWidget::item:selected, QTableView::item:selected,
QListWidget::item:selected, QTreeWidget::item:selected {
    background: #1976d2; color: #ffffff;
}
QTableWidget::item:selected:!active, QTableView::item:selected:!active,
QListWidget::item:selected:!active, QTreeWidget::item:selected:!active {
    background: #5b9bd5; color: #ffffff;
}
/* Najechanie myszą: jasne tło i CIEMNY tekst (nie niebieskie tło + czarny tekst) */
QTableWidget::item:hover, QTableView::item:hover,
QListWidget::item:hover, QTreeWidget::item:hover {
    background: #dbe9f8; color: #1c1c1c;
}
/* Najechanie na zaznaczony wiersz – tekst zostaje biały */
QTableWidget::item:selected:hover, QTableView::item:selected:hover,
QListWidget::item:selected:hover, QTreeWidget::item:selected:hover {
    background: #1565c0; color: #ffffff;
}
QComboBox QAbstractItemView {
    background: #ffffff; color: #1c1c1c;
    selection-background-color: #1976d2; selection-color: #ffffff;
}
QComboBox QAbstractItemView::item:hover { background: #dbe9f8; color: #1c1c1c; }
QMenu::item:disabled { color: #9aa0a6; }
QHeaderView::section { background: #eaeef4; padding: 6px; border: 0; border-right: 1px solid #dde1e7; }
QGroupBox { border: 1px solid #d0d4da; border-radius: 6px; margin-top: 14px; padding-top: 8px; background: #ffffff; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; color: #1565c0; }
QStatusBar { background: #ffffff; }
QProgressBar { border: 1px solid #c6ccd4; border-radius: 6px; text-align: center; background: #ffffff; }
QProgressBar::chunk { background: #1976d2; border-radius: 5px; }
"""


class Colors:
    """Kolory stanów segmentów – zależne od motywu."""

    def __init__(self, dark: bool = True) -> None:
        self.dark = dark

    @property
    def untranslated_bg(self):
        return "#3a3320" if self.dark else "#fff8e1"

    @property
    def translated_bg(self):
        return "#22331f" if self.dark else "#e8f5e9"

    @property
    def approved_bg(self):
        return "#1f2f3a" if self.dark else "#e3f2fd"

    @property
    def ignored_bg(self):
        return "#2a2a2a" if self.dark else "#eeeeee"

    @property
    def row_fg(self):
        """Kolor tekstu wiersza – kontrastowy do kolorowanych teł statusu."""
        return "#e6e6e6" if self.dark else "#1c1c1c"

    @property
    def selection_bg(self):
        return "#2f7fd1" if self.dark else "#1976d2"

    @property
    def selection_fg(self):
        return "#ffffff"

    @property
    def hover_bg(self):
        """Tło pod kursorem myszy (bez zaznaczenia)."""
        return "#313842" if self.dark else "#dbe9f8"

    @property
    def selection_hover_bg(self):
        """Tło zaznaczonego wiersza, gdy jest pod kursorem."""
        return "#3d8ee0" if self.dark else "#1565c0"

    @property
    def whitespace_bg(self):
        """Tło pod spacją na brzegu segmentu (wcięcie z pliku źródłowego).

        Sama kropka `·` w polu tekstowym była ledwo widoczna, dlatego wcięcie
        dostaje wyraźne, kolorowe tło – widać je nawet przy jednej spacji.
        """
        return "#6a4b8a" if self.dark else "#e1bee7"

    @property
    def whitespace_missing_bg(self):
        """Tło ostrzegawcze: w źródle jest wcięcie, a w tłumaczeniu go brak."""
        return "#7a3030" if self.dark else "#ffcdd2"

    @property
    def whitespace_marker_fg(self):
        """Kolor znaku `·` / `→` oznaczającego biały znak."""
        return "#d8b4fe" if self.dark else "#6a1b9a"


def style_splitter_handle(handle) -> None:
    """Widoczny uchwyt splittera (tylko uchwyt — bez efektu na dzieci)."""
    if handle is None:
        return
    handle.setStyleSheet(
        "QSplitterHandle { background: #46536b; }"
        "QSplitterHandle:horizontal { border-left: 1px solid #2b3547;"
        " border-right: 1px solid #2b3547; }"
        "QSplitterHandle:vertical { border-top: 1px solid #2b3547;"
        " border-bottom: 1px solid #2b3547; }"
    )


def setup_splitter(splitter, minimums=None, collapsible: bool = False) -> None:
    """Ustawia splitter tak, żeby paneli nie dało się zgubić.

    Domyślnie Qt pozwala przeciągnąć uchwyt do samej krawędzi — panel znika
    wtedy całkowicie i **nie ma jak go przywrócić**, bo uchwyt zlewa się
    z brzegiem okna. Dlatego:

    * `setChildrenCollapsible(False)` — panel nie schowa się do zera,
    * `minimums` — najmniejsza sensowna szerokość/wysokość każdego panelu,
    * szerszy uchwyt (6 px) — łatwiej go złapać myszą.
    """
    splitter.setChildrenCollapsible(collapsible)
    splitter.setHandleWidth(8)
    # Uchwyt MUSI być widoczny — w motywie ciemnym zlewał się z tłem i
    # wyglądało, że kolumn „nie da się rozciągać”. Uwaga: styl NADAJEMY
    # samemu uchwytowi, a NIE splitterowi — stylesheet na splitterze
    # włącza tryb arkusza dla wszystkich dzieci i motywowy
    # „QWidget { font-size: 13px }” przegrywał z jawną setFont().
    for i in range(splitter.count() - 1):
        style_splitter_handle(splitter.handle(i))
    horizontal = splitter.orientation() == Qt.Orientation.Horizontal
    for index in range(splitter.count()):
        splitter.setCollapsible(index, collapsible)
        widget = splitter.widget(index)
        if widget is None:
            continue
        size = None
        if minimums and index < len(minimums):
            size = minimums[index]
        if size:
            if horizontal:
                widget.setMinimumWidth(size)
            else:
                widget.setMinimumHeight(size)


def stylesheet(dark: bool, font_px: int = 0) -> str:
    """Arkusz stylów motywu.

    ``font_px`` — wymuszony rozmiar czcionki interfejsu w pikselach
    (0 = zostaje wartość z motywu). Arkusz ma regułę ``QWidget { font-size }``,
    która dla kontrolki jest ważniejsza niż ``setFont()`` — dlatego zmiana
    wielkości całego interfejsu musi przejść właśnie przez ten tekst.
    """
    text = DARK if dark else LIGHT
    if font_px and font_px > 0:
        text = text.replace("font-size: 13px", f"font-size: {int(font_px)}px", 1)
    return text
