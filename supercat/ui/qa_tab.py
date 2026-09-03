"""Zakładka QA – kontrola jakości i statystyki projektu."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QFileDialog, QGroupBox, QHBoxLayout, QHeaderView,
    QLabel, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout,
    QWidget,
)

from ..core.qa import (SEVERITY_ERROR, SEVERITY_WARNING, file_statistics, project_statistics,
                       qa_report_text, run_qa)
from ..core.settings import SettingsManager


class QATab(QWidget):
    def __init__(self, app) -> None:
        super().__init__()
        self.app = app
        self.issues = []
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        checks = QGroupBox("✅ Kontrole do wykonania")
        checks_layout = QHBoxLayout(checks)
        settings = SettingsManager.instance()
        self.check_boxes = {}
        for key, label in (
            ("qa.check.empty", "Puste segmenty"),
            ("qa.check.numbers", "Liczby"),
            ("qa.check.tags", "Tagi"),
            ("qa.check.length", "Długość"),
            ("qa.check.punctuation", "Interpunkcja"),
            ("qa.check.capitalization", "Wielkość liter"),
            ("qa.check.consistency", "Spójność"),
            ("qa.check.whitespace", "Spacje na brzegach"),
            ("qa.check.language", "Poprawność języka (tłumaczenie)"),
        ):
            cb = QCheckBox(label)
            cb.setChecked(settings.get_bool(key, True))
            cb.stateChanged.connect(lambda state, k=key: SettingsManager.instance().set(k, bool(state)))
            checks_layout.addWidget(cb)
            self.check_boxes[key] = cb
        checks_layout.addStretch(1)
        layout.addWidget(checks)

        buttons = QHBoxLayout()
        run_btn = QPushButton("▶ Uruchom QA (F8)")
        run_btn.clicked.connect(self.run_checks)
        export_btn = QPushButton("📄 Eksportuj raport")
        export_btn.clicked.connect(self.export_report)
        stats_btn = QPushButton("📊 Odśwież statystyki")
        stats_btn.clicked.connect(self.refresh_stats)
        buttons.addWidget(run_btn)
        buttons.addWidget(export_btn)
        buttons.addWidget(stats_btn)
        buttons.addStretch(1)
        self.summary = QLabel("Brak uruchomionej kontroli")
        buttons.addWidget(self.summary)
        layout.addLayout(buttons)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Segment", "Waga", "Kategoria", "Problem", "Szczegóły"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.doubleClicked.connect(self.goto_issue)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 90)
        self.table.setColumnWidth(1, 110)
        self.table.setColumnWidth(2, 150)
        layout.addWidget(self.table, 2)

        stats_box = QGroupBox("📊 Statystyki")
        stats_layout = QVBoxLayout(stats_box)
        stats_tabs = QTabWidget()

        # --- statystyki całego projektu, pogrupowane -------------------
        self.stats_table = QTableWidget(0, 2)
        self.stats_table.setHorizontalHeaderLabels(["Miara", "Wartość"])
        self.stats_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.stats_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.stats_table.setAlternatingRowColors(True)
        self.stats_table.verticalHeader().setVisible(False)
        self.stats_table.setMinimumHeight(320)
        stats_tabs.addTab(self.stats_table, "📦 Projekt")

        # --- rozbicie na pliki ------------------------------------------
        self.file_stats_table = QTableWidget(0, 7)
        self.file_stats_table.setHorizontalHeaderLabels([
            "Plik", "Segmenty", "Przetłumaczone", "Postęp (%)",
            "Słowa (źródło)", "Znaki ze spacjami", "Znaki bez spacji",
        ])
        self.file_stats_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        self.file_stats_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.file_stats_table.setAlternatingRowColors(True)
        self.file_stats_table.verticalHeader().setVisible(False)
        stats_tabs.addTab(self.file_stats_table, "📄 Pliki")
        stats_layout.addWidget(stats_tabs)

        copy_row = QHBoxLayout()
        copy_btn = QPushButton("📋 Kopiuj statystyki")
        copy_btn.setToolTip("Kopiuje zestawienie do schowka (do wklejenia w wycenie)")
        copy_btn.clicked.connect(self.copy_statistics)
        copy_row.addWidget(copy_btn)
        copy_row.addStretch(1)
        stats_layout.addLayout(copy_row)
        layout.addWidget(stats_box, 3)

    # ------------------------------------------------------------------
    def run_checks(self) -> None:
        segments = self.app.editor_tab.segments
        if not segments:
            QMessageBox.information(self, "QA", "Brak segmentów – zaimportuj pliki do projektu.")
            return
        self.issues = run_qa(segments, self.app.glossary, self.app.dictionary)
        self.table.setRowCount(len(self.issues))
        errors = warnings = 0
        for r, issue in enumerate(self.issues):
            num = QTableWidgetItem(str(issue.segment_index + 1))
            num.setData(Qt.ItemDataRole.UserRole, issue.segment_index)
            num.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            sev = QTableWidgetItem(issue.severity)
            if issue.severity == SEVERITY_ERROR:
                sev.setForeground(QColor("#ef5350"))
                errors += 1
            elif issue.severity == SEVERITY_WARNING:
                sev.setForeground(QColor("#ffb74d"))
                warnings += 1
            else:
                sev.setForeground(QColor("#64b5f6"))
            self.table.setItem(r, 0, num)
            self.table.setItem(r, 1, sev)
            self.table.setItem(r, 2, QTableWidgetItem(issue.category))
            self.table.setItem(r, 3, QTableWidgetItem(issue.message))
            self.table.setItem(r, 4, QTableWidgetItem(issue.detail))
        self.summary.setText(
            f"Znaleziono {len(self.issues)} problemów  •  błędy: {errors}  •  ostrzeżenia: {warnings}"
        )
        self.refresh_stats()

    #: Nagłówki grup w tabeli statystyk – ułatwiają czytanie długiej listy.
    STAT_GROUPS = {
        "Segmenty (razem)": "▸ POSTĘP",
        "Słowa (źródło)": "▸ SŁOWA",
        "Znaki ze spacjami (źródło)": "▸ ZNAKI",
        "Strony rozliczeniowe (1800 zn.)": "▸ ROZLICZENIE I DŁUGOŚĆ",
        "Segmenty powtórzone": "▸ POZOSTAŁE",
    }

    def refresh_stats(self) -> None:
        segments = self.app.editor_tab.segments
        stats = project_statistics(segments, self.app.tm.size() if self.app.tm.is_initialized else 0)

        rows = []
        for key, value in stats.items():
            if key in self.STAT_GROUPS:
                rows.append((self.STAT_GROUPS[key], None))
            rows.append((key, value))

        self.stats_table.setRowCount(len(rows))
        header_font = QFont()
        header_font.setBold(True)
        for r, (key, value) in enumerate(rows):
            name = QTableWidgetItem(str(key))
            if value is None:                      # wiersz nagłówka grupy
                name.setFont(header_font)
                name.setForeground(QColor("#64b5f6"))
                self.stats_table.setItem(r, 0, name)
                self.stats_table.setItem(r, 1, QTableWidgetItem(""))
                continue
            self.stats_table.setItem(r, 0, name)
            item = QTableWidgetItem(f"{value:,}".replace(",", " ")
                                    if isinstance(value, int) else str(value))
            item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.stats_table.setItem(r, 1, item)

        # --- rozbicie na pliki ---
        file_rows = file_statistics(segments)
        self.file_stats_table.setRowCount(len(file_rows))
        for r, row in enumerate(file_rows):
            for c, key in enumerate(["Plik", "Segmenty", "Przetłumaczone", "Postęp (%)",
                                     "Słowa (źródło)", "Znaki ze spacjami", "Znaki bez spacji"]):
                value = row[key]
                item = QTableWidgetItem(str(value))
                if c > 0:
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if key == "Postęp (%)":
                    item.setForeground(QColor("#66bb6a" if value >= 99 else
                                              "#ffb74d" if value > 0 else "#90a4ae"))
                self.file_stats_table.setItem(r, c, item)

    def copy_statistics(self) -> None:
        """Kopiuje zestawienie do schowka – gotowe do wklejenia w wycenie."""
        segments = self.app.editor_tab.segments
        stats = project_statistics(segments, self.app.tm.size() if self.app.tm.is_initialized else 0)
        lines = [f"Statystyki projektu: {self.app.project.name if self.app.project else '—'}", ""]
        lines += [f"{key}: {value}" for key, value in stats.items()]
        lines += ["", "Rozbicie na pliki:"]
        for row in file_statistics(segments):
            lines.append(
                f"  {row['Plik']}: {row['Segmenty']} segm., {row['Słowa (źródło)']} słów, "
                f"{row['Znaki ze spacjami']} zn. ze spacjami / "
                f"{row['Znaki bez spacji']} bez spacji, {row['Postęp (%)']}%"
            )
        QApplication.clipboard().setText("\n".join(lines))
        self.app.show_status("📋 Skopiowano statystyki do schowka")

    def goto_issue(self) -> None:
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows:
            return
        idx = self.table.item(rows[0].row(), 0).data(Qt.ItemDataRole.UserRole)
        if idx is not None:
            self.app.go_to_editor_segment(idx)

    def export_report(self) -> None:
        if not self.issues:
            QMessageBox.information(self, "Raport QA", "Najpierw uruchom kontrolę QA.")
            return
        project = self.app.project
        default = f"{project.export_path}/raport_qa.txt" if project else "raport_qa.txt"
        path, _ = QFileDialog.getSaveFileName(self, "Zapisz raport QA", default, "Pliki tekstowe (*.txt)")
        if not path:
            return
        text = qa_report_text(self.issues, self.app.editor_tab.segments)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        QMessageBox.information(self, "Raport QA", f"Zapisano raport:\n{path}")
