"""日历视图：月历 + 截止日期标记 + 选中日任务列表。"""
from datetime import date

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QColor, QFont, QTextCharFormat
from PySide6.QtWidgets import (
    QCalendarWidget,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..database import PRIORITY_LABELS, STATUS_LABELS


class CalendarView(QWidget):
    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self._selected = date.today()
        self._marked_dates = []
        self._build()

    def _build(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 14, 16, 14)
        v.setSpacing(10)

        self.cal = QCalendarWidget()
        self.cal.setGridVisible(True)
        self.cal.setVerticalHeaderFormat(QCalendarWidget.NoVerticalHeader)
        self.cal.setMinimumHeight(380)
        self.cal.clicked.connect(self._on_date_clicked)
        v.addWidget(self.cal)

        self.date_lbl = QLabel()
        self.date_lbl.setStyleSheet("font-size:14px;font-weight:600;color:#1f2937;")
        v.addWidget(self.date_lbl)

        self.task_list = QListWidget()
        v.addWidget(self.task_list, 1)

    def set_selected_date(self, d: date) -> None:
        self._selected = d
        self.cal.setSelectedDate(QDate(d.year, d.month, d.day))

    def refresh(self) -> None:
        self._mark_dates()
        self._show_day(self._selected)

    # ---------- 日期标记 ----------
    def _mark_dates(self) -> None:
        # 清除旧标记
        for qd in self._marked_dates:
            self.cal.setDateTextFormat(qd, QTextCharFormat())
        self._marked_dates = []

        date_counts = {}
        for t in self.db.list_todos():
            if t.due_date:
                date_counts[t.due_date] = date_counts.get(t.due_date, 0) + 1

        for ds, _cnt in date_counts.items():
            qd = QDate.fromString(ds, "yyyy-MM-dd")
            if qd.isValid():
                fmt = QTextCharFormat()
                fmt.setBackground(QColor("#4a90d9"))
                fmt.setForeground(QColor("#ffffff"))
                fmt.setFontWeight(QFont.Bold)
                self.cal.setDateTextFormat(qd, fmt)
                self._marked_dates.append(qd)

    # ---------- 选中日任务 ----------
    def _on_date_clicked(self, qdate: QDate) -> None:
        self._selected = qdate.toPython()
        self._show_day(self._selected)

    def _show_day(self, d: date) -> None:
        ds = d.strftime("%Y-%m-%d")
        self.date_lbl.setText(f"{ds} 的任务")
        self.task_list.clear()

        day = []
        for t in self.db.list_todos():
            if t.due_date == ds or t.created_at[:10] == ds:
                day.append(t)

        for t in day:
            pri = PRIORITY_LABELS.get(t.priority, t.priority)
            status = STATUS_LABELS.get(t.status, t.status)
            mark = "✓" if t.status == "done" else ("·" if t.status == "doing" else "○")
            self.task_list.addItem(f"{mark} [{pri}] {t.title}（{status}）")

        if not day:
            item = QListWidgetItem("（当天无任务）")
            item.setFlags(Qt.NoItemFlags)
            item.setTextAlignment(Qt.AlignCenter)
            item.setForeground(Qt.gray)
            self.task_list.addItem(item)
