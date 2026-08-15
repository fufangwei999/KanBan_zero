"""主窗口：日期导航 + 三区（待办/进行中/已完成）+ 日报/周报 + AI + 全局热键召唤。"""
import ctypes
import os
from ctypes import wintypes
from datetime import date, datetime, timedelta

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QCalendarWidget,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from .. import ai as ai_module
from ..database import PRIORITY_LABELS, Database
from .board import TodoListWidget
from .calendar_view import CalendarView
from .dialogs import AiModelDialog, CategoryDialog, ReportDialog, SmartAddDialog, TodoDialog

# 全局热键：Ctrl+J
MOD_CONTROL = 0x0002
VK_J = 0x4A
WM_HOTKEY = 0x0312
HOTKEY_ID = 1


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.db = Database()
        self.current_date = date.today()
        self._last_seen_today = date.today()
        self._selected_todo_id = None
        self.setWindowTitle("帅帅看板")
        self.resize(1000, 920)
        self._build_ui()
        self._setup_shortcuts()
        self._setup_tray()
        self._register_hotkey()
        self.refresh_all()
        self._update_view_btn_style()
        self._start_midnight_timer()
        self._setup_due_reminders()

    # ------------------------------------------------------------ UI 骨架
    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_toolbar())

        self.stacked = QStackedWidget()

        # 看板页
        board_page = QWidget()
        bv = QVBoxLayout(board_page)
        bv.setContentsMargins(0, 0, 0, 0)
        bv.setSpacing(0)
        self.stats_label = QLabel()
        self.stats_label.setObjectName("statsBar")
        bv.addWidget(self.stats_label)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setObjectName("boardArea")
        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(16, 14, 16, 14)
        self.content_layout.setSpacing(12)
        self.content_layout.setAlignment(Qt.AlignTop)
        self.scroll.setWidget(self.content)
        bv.addWidget(self.scroll, 1)
        self.stacked.addWidget(board_page)

        # 日历页
        self.calendar_view = CalendarView(self.db)
        self.stacked.addWidget(self.calendar_view)

        root.addWidget(self.stacked, 1)
        self.setCentralWidget(central)
        self._build_sections()

    def _build_toolbar(self) -> QWidget:
        toolbar = QFrame()
        toolbar.setObjectName("toolbar")
        lay = QHBoxLayout(toolbar)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(8)

        title = QLabel("🍂 帅帅看板")
        title.setObjectName("appTitle")
        lay.addWidget(title)
        lay.addSpacing(10)

        # 视图切换
        self.board_view_btn = QPushButton("📋 看板")
        self.board_view_btn.setCursor(Qt.PointingHandCursor)
        self.board_view_btn.clicked.connect(self.show_board)
        self.cal_view_btn = QPushButton("📅 日历")
        self.cal_view_btn.setCursor(Qt.PointingHandCursor)
        self.cal_view_btn.clicked.connect(self.show_calendar)
        lay.addWidget(self.board_view_btn)
        lay.addWidget(self.cal_view_btn)

        # 日期导航
        self.prev_btn = QPushButton("◀")
        self.prev_btn.setToolTip("前一天")
        self.prev_btn.clicked.connect(self.on_prev_day)
        self.date_btn = QPushButton()
        self.date_btn.setObjectName("dateBtn")
        self.date_btn.setToolTip("点击选择日期（不能选未来）")
        self.date_btn.clicked.connect(self.on_pick_date)
        self.next_btn = QPushButton("▶")
        self.next_btn.setToolTip("后一天（不能选未来）")
        self.next_btn.clicked.connect(self.on_next_day)
        self.today_btn = QPushButton("今天")
        self.today_btn.clicked.connect(self.on_today)
        lay.addWidget(self.prev_btn)
        lay.addWidget(self.date_btn)
        lay.addWidget(self.next_btn)
        lay.addWidget(self.today_btn)

        # 搜索 + 过滤
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("🔍 搜索…")
        self.search_edit.setFixedWidth(130)
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._apply_filter)
        lay.addWidget(self.search_edit)

        self.filter_combo = QComboBox()
        for label, key in [
            ("全部", "all"),
            ("高优先级", "high"),
            ("中优先级", "medium"),
            ("低优先级", "low"),
            ("今日到期", "due_today"),
            ("已逾期", "overdue"),
        ]:
            self.filter_combo.addItem(label, key)
        self.filter_combo.currentIndexChanged.connect(self._apply_filter)
        lay.addWidget(self.filter_combo)

        lay.addStretch(1)

        def add_btn(text, handler, primary=False):
            b = QPushButton(text)
            b.setCursor(Qt.PointingHandCursor)
            if primary:
                b.setObjectName("primaryBtn")
            b.clicked.connect(handler)
            lay.addWidget(b)
            return b

        add_btn("＋ 添加待办", self.on_add_todo, primary=True)
        add_btn("✨ 智能添加", self.on_smart_add)
        add_btn("分类", self.on_manage_categories)
        add_btn("📋 日报", self.on_daily_report)
        add_btn("📅 周报", self.on_weekly_report)
        add_btn("🤖 AI 模型", self.on_ai_settings)
        add_btn("🗑 回收站", self.on_open_trash)

        self._update_date_btn()
        return toolbar

    # ------------------------------------------------------------ 日期导航
    def _update_date_btn(self) -> None:
        today = date.today()
        label = self.current_date.strftime("%Y-%m-%d")
        if self.current_date == today:
            label += "  ·  今天"
        elif self.current_date == today - timedelta(days=1):
            label += "  ·  昨天"
        self.date_btn.setText(label)
        self.next_btn.setEnabled(self.current_date < today)

    def on_prev_day(self) -> None:
        self.current_date -= timedelta(days=1)
        self._update_date_btn()
        self.show_board()
        self.refresh_all()

    def on_next_day(self) -> None:
        if self.current_date < date.today():
            self.current_date += timedelta(days=1)
            self._update_date_btn()
            self.show_board()
            self.refresh_all()

    def on_today(self) -> None:
        self.current_date = date.today()
        self._update_date_btn()
        self.show_board()
        self.refresh_all()

    def on_pick_date(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("选择日期（不能选未来）")
        v = QVBoxLayout(dlg)
        cal = QCalendarWidget()
        cal.setMaximumDate(date.today())
        cal.setSelectedDate(self.current_date)
        v.addWidget(cal)
        btn = QPushButton("确定")
        btn.clicked.connect(dlg.accept)
        v.addWidget(btn)
        if dlg.exec():
            self.current_date = cal.selectedDate().toPython()
            self._update_date_btn()
            self.show_board()
            self.refresh_all()

    # ------------------------------------------------------------ 视图切换
    def show_board(self) -> None:
        self.stacked.setCurrentIndex(0)
        self._update_view_btn_style()

    def show_calendar(self) -> None:
        self.calendar_view.set_selected_date(self.current_date)
        self.calendar_view.refresh()
        self.stacked.setCurrentIndex(1)
        self._update_view_btn_style()

    def _update_view_btn_style(self) -> None:
        active = "background:#4a90d9;border:none;color:#ffffff;font-weight:600;"
        idle = ""
        on_board = self.stacked.currentIndex() == 0
        self.board_view_btn.setStyleSheet(active if on_board else idle)
        self.cal_view_btn.setStyleSheet(active if not on_board else idle)

    # ------------------------------------------------------------ 渲染
    def refresh_all(self) -> None:
        date_str = self.current_date.strftime("%Y-%m-%d")
        todo = self.db.todos_status_on("todo", date_str)
        doing = self.db.todos_status_on("doing", date_str)
        done = self.db.todos_status_on("done", date_str)
        cat_map = {c.id: (c.name, c.color) for c in self.db.list_categories()}

        def get_meta(cid):
            return cat_map.get(cid, ("未分类", "#999999"))

        data = {"todo": todo, "doing": doing, "done": done}
        sub_map = self.db.subtasks_map()
        for status, (title, header, lst, hint) in self._sections.items():
            todos = data[status]
            header.setText(f"{title}  ·  {len(todos)}")
            lst.current_date = date_str
            lst.load_todos(todos, get_meta, hint, sub_map)
            lst.setFixedHeight(self._list_height(len(todos)))
        self._update_stats(todo, doing, done)
        self._apply_filter()

    def _build_sections(self) -> None:
        """固定创建三区（复用 widget，避免反复重建造成的碎片/峰值内存）。"""
        self._sections = {}  # status -> (title, header, list, hint)
        for status, title, hint in [
            ("todo", "📋 待办", "暂无待办"),
            ("doing", "🔄 进行中", "暂无进行中任务"),
            ("done", "✅ 已完成", "暂无已完成"),
        ]:
            header = QLabel(f"{title}  ·  0")
            header.setStyleSheet("font-size:15px;font-weight:600;color:#1f2937;")
            lst = TodoListWidget(target_status=status)
            lst.status_requested.connect(self.on_status_requested)
            lst.edit_requested.connect(self.on_edit_todo)
            lst.delete_requested.connect(self.on_delete_todo)
            lst.item_dropped.connect(self.on_item_dropped)
            lst.selected.connect(self._on_selected)
            self.content_layout.addWidget(header)
            self.content_layout.addWidget(lst)
            self._sections[status] = (title, header, lst, hint)

    @staticmethod
    def _list_height(n: int) -> int:
        if n == 0:
            return 56
        return min(n * 150 + (n - 1) * 6 + 20, 640)

    # ------------------------------------------------------------ 待办事件
    def on_status_requested(self, todo_id: int, new_status: str) -> None:
        self.db.set_todo_status(todo_id, new_status)
        self._after_status_change(new_status)

    def on_item_dropped(self, todo_id: int, target_status: str) -> None:
        self.db.set_todo_status(todo_id, target_status)
        self._after_status_change(target_status)

    def _after_status_change(self, new_status: str) -> None:
        # 完成动作记「真实今天」：若在历史面板完成，自动跳到今天，让任务归到今天已完成区
        if new_status == "done" and self.current_date != date.today():
            self.current_date = date.today()
            self._update_date_btn()
        self.refresh_all()

    def _setup_shortcuts(self) -> None:
        def bind(seq, handler):
            sc = QShortcut(QKeySequence(seq), self)
            sc.setContext(Qt.WidgetShortcut)
            sc.activated.connect(handler)
        bind("Ctrl+N", self.on_add_todo)
        bind("1", lambda: self._status_shortcut("todo"))
        bind("2", lambda: self._status_shortcut("doing"))
        bind("3", lambda: self._status_shortcut("done"))
        bind(QKeySequence.StandardKey.Delete, self._delete_selected)

    def _update_stats(self, todo, doing, done) -> None:
        date_str = self.current_date.strftime("%Y-%m-%d")
        overdue = sum(
            1 for t in list(todo) + list(doing)
            if t.due_date and t.due_date < date_str
        )
        parts = [
            f"📋 待办 {len(todo)}",
            f"🔄 进行中 {len(doing)}",
            f"✅ 已完成 {len(done)}",
        ]
        if overdue:
            parts.append(f"⏰ 逾期 {overdue}")
        self.stats_label.setText("　".join(parts))

    def _on_selected(self, todo_id: int) -> None:
        self._selected_todo_id = todo_id

    def _status_shortcut(self, status: str) -> None:
        if self._selected_todo_id is not None:
            self.db.set_todo_status(self._selected_todo_id, status)
            self.refresh_all()

    def _delete_selected(self) -> None:
        if self._selected_todo_id is not None:
            self.on_delete_todo(self._selected_todo_id)

    def on_add_todo(self) -> None:
        cats = self.db.list_categories()
        if not cats:
            QMessageBox.warning(self, "提示", "请先添加一个分类")
            return
        # 新任务归属「今天」
        if self.current_date != date.today():
            self.current_date = date.today()
            self._update_date_btn()
        dlg = TodoDialog(cats, parent=self)
        if dlg.exec():
            d = dlg.data()
            todo = self.db.add_todo(d["title"], d["category_id"], d["description"], d["priority"], d["due_date"])
            if todo:
                for title, done in d["subtasks"]:
                    self.db.add_subtask(todo.id, title, done)
            self.refresh_all()

    def on_edit_todo(self, todo_id: int) -> None:
        todo = self.db.get_todo(todo_id)
        if not todo:
            return
        subs = self.db.list_subtasks(todo_id)
        dlg = TodoDialog(self.db.list_categories(), todo, subtasks=subs, parent=self)
        if dlg.exec():
            d = dlg.data()
            self.db.update_todo(todo_id, d["title"], d["description"], d["priority"], d["due_date"])
            self.db.move_todo(todo_id, d["category_id"])
            self.db.clear_subtasks(todo_id)
            for title, done in d["subtasks"]:
                self.db.add_subtask(todo_id, title, done)
            self.refresh_all()

    def on_delete_todo(self, todo_id: int) -> None:
        todo = self.db.get_todo(todo_id)
        if not todo:
            return
        if QMessageBox.question(
            self, "移入回收站", f"确定将「{todo.title}」移入回收站吗？\n可在「🗑 回收站」中恢复。"
        ) == QMessageBox.Yes:
            self.db.delete_todo(todo_id)
            self.refresh_all()

    def on_open_trash(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("回收站")
        dlg.resize(520, 420)
        lay = QVBoxLayout(dlg)

        tip = QLabel("已删除的待办都在这里，可恢复或彻底删除。")
        tip.setStyleSheet("color:#666;font-size:12px;")
        lay.addWidget(tip)

        lst = QListWidget()
        lay.addWidget(lst, 1)

        def reload():
            lst.clear()
            for t in self.db.list_deleted_todos():
                item = QListWidgetItem(f"{t.title}  ·  {t.created_at[:10]} 创建")
                item.setData(Qt.UserRole, t.id)
                lst.addItem(item)
            if not lst.count():
                item = QListWidgetItem("（回收站为空）")
                item.setFlags(Qt.NoItemFlags)
                item.setTextAlignment(Qt.AlignCenter)
                item.setForeground(Qt.gray)
                lst.addItem(item)

        btn_row = QHBoxLayout()
        restore_btn = QPushButton("↩ 恢复")
        purge_btn = QPushButton("彻底删除")
        purge_all_btn = QPushButton("清空回收站")
        close_btn = QPushButton("关闭")
        btn_row.addWidget(restore_btn)
        btn_row.addWidget(purge_btn)
        btn_row.addWidget(purge_all_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(close_btn)
        lay.addLayout(btn_row)

        def current_id():
            item = lst.currentItem()
            return item.data(Qt.UserRole) if item else None

        def on_restore():
            tid = current_id()
            if tid:
                self.db.restore_todo(tid)
                reload()
                self.refresh_all()

        def on_purge():
            tid = current_id()
            if tid and QMessageBox.question(dlg, "确认", "彻底删除后无法恢复，确定？") == QMessageBox.Yes:
                self.db.purge_todo(tid)
                reload()

        def on_purge_all():
            if self.db.list_deleted_todos() and QMessageBox.question(dlg, "确认", "清空回收站后无法恢复，确定？") == QMessageBox.Yes:
                self.db.purge_all_deleted()
                reload()

        restore_btn.clicked.connect(on_restore)
        purge_btn.clicked.connect(on_purge)
        purge_all_btn.clicked.connect(on_purge_all)
        close_btn.clicked.connect(dlg.accept)

        reload()
        dlg.exec()

    # ------------------------------------------------------------ 分类管理
    def on_manage_categories(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("分类管理")
        dlg.resize(420, 380)
        lay = QVBoxLayout(dlg)

        tip = QLabel("分类会作为标签显示在待办卡片上。")
        tip.setStyleSheet("color:#666;font-size:12px;")
        lay.addWidget(tip)

        lst = QListWidget()
        lay.addWidget(lst, 1)

        def reload():
            lst.clear()
            for c in self.db.list_categories():
                item = QListWidgetItem(f"● {c.name}")
                item.setForeground(QColor(c.color))
                item.setData(Qt.UserRole, c.id)
                lst.addItem(item)

        btn_row = QHBoxLayout()
        add_btn = QPushButton("＋ 添加")
        edit_btn = QPushButton("✏️ 编辑")
        del_btn = QPushButton("🗑 删除")
        close_btn = QPushButton("关闭")
        btn_row.addWidget(add_btn)
        btn_row.addWidget(edit_btn)
        btn_row.addWidget(del_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(close_btn)
        lay.addLayout(btn_row)

        def current_id():
            item = lst.currentItem()
            return item.data(Qt.UserRole) if item else None

        def on_add():
            d = CategoryDialog(parent=dlg)
            if d.exec():
                data = d.data()
                if any(c.name == data["name"] for c in self.db.list_categories()):
                    QMessageBox.warning(dlg, "提示", "分类名称已存在")
                    return
                self.db.add_category(data["name"], data["color"])
                reload()

        def on_edit():
            cid = current_id()
            cat = next((c for c in self.db.list_categories() if c.id == cid), None)
            if not cat:
                return
            d = CategoryDialog(cat, parent=dlg)
            if d.exec():
                data = d.data()
                dup = [c for c in self.db.list_categories() if c.name == data["name"] and c.id != cid]
                if dup:
                    QMessageBox.warning(dlg, "提示", "分类名称已存在")
                    return
                self.db.rename_category(cid, data["name"], data["color"])
                reload()

        def on_del():
            cid = current_id()
            cat = next((c for c in self.db.list_categories() if c.id == cid), None)
            if not cat:
                return
            if QMessageBox.question(dlg, "确认", f"删除分类「{cat.name}」？其下待办会移到最前分类。") == QMessageBox.Yes:
                self.db.delete_category(cid)
                reload()

        add_btn.clicked.connect(on_add)
        edit_btn.clicked.connect(on_edit)
        del_btn.clicked.connect(on_del)
        close_btn.clicked.connect(dlg.accept)

        reload()
        dlg.exec()
        self.refresh_all()

    # ------------------------------------------------------------ 日报 / 周报
    def on_daily_report(self) -> None:
        d = self.current_date
        day_start = datetime.combine(d, datetime.min.time())
        day_end = day_start + timedelta(days=1)
        created = self.db.todos_created_between(day_start, day_end)
        completed = self.db.todos_completed_between(day_start, day_end)
        text = self.build_daily_report_text(created, completed, d)
        dlg = ReportDialog(
            f"日报 · {d:%Y-%m-%d}",
            text,
            summarize_fn=lambda: self._make_summarize_task(
                [("当日新建", created), ("当日完成", completed)], "当日"
            ),
            parent=self,
        )
        dlg.exec()

    def on_weekly_report(self) -> None:
        monday = self.current_date - timedelta(days=self.current_date.weekday())
        sunday = monday + timedelta(days=6)
        week_start = datetime.combine(monday, datetime.min.time())
        week_end = datetime.combine(sunday + timedelta(days=1), datetime.min.time())
        completed = self.db.todos_completed_between(week_start, week_end)
        pending = self.db.todos_pending_until(sunday.strftime("%Y-%m-%d"))
        text = self.build_weekly_report_text(completed, pending, monday, sunday)
        dlg = ReportDialog(
            f"周报 · {monday:%m-%d} ~ {sunday:%m-%d}",
            text,
            summarize_fn=lambda: self._make_summarize_task(
                [("本周完成", completed), ("本周未完成", pending)], "本周"
            ),
            parent=self,
        )
        dlg.exec()

    def build_daily_report_text(self, created, completed, d) -> str:
        lines = ["# 当日总结", ""]
        lines.append(f"日期：{d:%Y-%m-%d}")
        lines.append(f"当日新建：{len(created)} 项")
        lines.append(f"当日完成：{len(completed)} 项")
        lines.append("")
        lines.append("## 当日新建")
        if created:
            for t in created:
                pri = PRIORITY_LABELS.get(t.priority, t.priority)
                lines.append(f"- [{pri}] {t.title}")
        else:
            lines.append("（无）")
        lines.append("")
        lines.append("## 当日完成")
        if completed:
            for t in completed:
                pri = PRIORITY_LABELS.get(t.priority, t.priority)
                lines.append(f"- [{t.completed_at[5:16]}] [{pri}] {t.title}")
        else:
            lines.append("（无）")
        return "\n".join(lines)

    def build_weekly_report_text(self, completed, pending, monday, sunday) -> str:
        lines = ["# 本周总结", ""]
        lines.append(f"统计周期：{monday:%Y-%m-%d} ~ {sunday:%Y-%m-%d}")
        lines.append(f"本周完成：{len(completed)} 项")
        lines.append(f"本周未完成（遗留）：{len(pending)} 项")
        lines.append("")
        lines.append("## 本周完成")
        if completed:
            for t in completed:
                pri = PRIORITY_LABELS.get(t.priority, t.priority)
                lines.append(f"- [{t.completed_at[5:16]}] [{pri}] {t.title}")
        else:
            lines.append("（无）")
        lines.append("")
        lines.append("## 本周未完成")
        if pending:
            for t in pending:
                pri = PRIORITY_LABELS.get(t.priority, t.priority)
                tag = f"（{t.created_at[:10]} 创建）" if t.created_at[:10] < monday.strftime("%Y-%m-%d") else ""
                lines.append(f"- [{pri}] {t.title}{tag}")
        else:
            lines.append("（无）")
        return "\n".join(lines)

    # ------------------------------------------------------------ AI
    def _pick_model(self):
        models = self.db.list_ai_models()
        if not models:
            raise Exception("尚未配置 AI 模型，请先在「🤖 AI 模型」里添加一个")
        if len(models) == 1:
            return models[0]
        names = [m.name for m in models]
        name, ok = QInputDialog.getItem(self, "选择模型", "选择用于总结的 AI 模型：", names, 0, False)
        if not ok:
            return None
        return next(m for m in models if m.name == name)

    def _make_summarize_task(self, sections, scope_label):
        model = self._pick_model()
        if model is None:
            return None
        return lambda: ai_module.generate_report_summary(model, sections, scope_label)

    # ------------------------------------------------------------ AI 模型管理
    def on_ai_settings(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("AI 模型管理")
        dlg.resize(520, 360)
        lay = QVBoxLayout(dlg)

        tip = QLabel("配置 OpenAI 兼容接口的模型（DeepSeek / OpenAI / 本地 Ollama 等），用于日报周报智能总结。")
        tip.setWordWrap(True)
        tip.setStyleSheet("color:#666;font-size:12px;")
        lay.addWidget(tip)

        lst = QListWidget()
        lay.addWidget(lst, 1)

        def reload_list():
            lst.clear()
            for m in self.db.list_ai_models():
                lst.addItem(f"{m.name}  ·  {m.model}  ·  {m.base_url}")
            if not lst.count():
                lst.addItem("（尚未配置模型）")

        btn_row = QHBoxLayout()
        add_btn = QPushButton("＋ 添加")
        edit_btn = QPushButton("✏️ 编辑")
        del_btn = QPushButton("🗑 删除")
        close_btn = QPushButton("关闭")
        btn_row.addWidget(add_btn)
        btn_row.addWidget(edit_btn)
        btn_row.addWidget(del_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(close_btn)
        lay.addLayout(btn_row)

        def current_model():
            models = self.db.list_ai_models()
            row = lst.currentRow()
            if 0 <= row < len(models):
                return models[row]
            return None

        def on_add():
            d = AiModelDialog(parent=dlg)
            if d.exec():
                data = d.data()
                self.db.add_ai_model(data["name"], data["base_url"], data["api_key"], data["model"])
                reload_list()

        def on_edit():
            m = current_model()
            if not m:
                QMessageBox.information(dlg, "提示", "请先选择一个模型")
                return
            d = AiModelDialog(m, parent=dlg)
            if d.exec():
                data = d.data()
                self.db.update_ai_model(m.id, data["name"], data["base_url"], data["api_key"], data["model"])
                reload_list()

        def on_del():
            m = current_model()
            if not m:
                return
            if QMessageBox.question(dlg, "确认", f"删除模型「{m.name}」？") == QMessageBox.Yes:
                self.db.delete_ai_model(m.id)
                reload_list()

        add_btn.clicked.connect(on_add)
        edit_btn.clicked.connect(on_edit)
        del_btn.clicked.connect(on_del)
        close_btn.clicked.connect(dlg.accept)

        reload_list()
        dlg.exec()

    # ------------------------------------------------------------ 跨天自动刷新
    def _start_midnight_timer(self) -> None:
        self._rollover_timer = QTimer(self)
        self._rollover_timer.timeout.connect(self._check_day_rollover)
        self._rollover_timer.start(60_000)

    def _check_day_rollover(self) -> None:
        today = date.today()
        if today != self._last_seen_today:
            if self.current_date == self._last_seen_today:
                self.current_date = today  # 停留在旧「今天」则自动进入新日期
            self._last_seen_today = today
            self._update_date_btn()
            self.refresh_all()

    # ------------------------------------------------------------ 托盘 + 全局热键
    def _setup_tray(self) -> None:
        self.tray = QSystemTrayIcon(self._make_tray_icon(), self)
        self.tray.setToolTip("帅帅看板 · Ctrl+J 召唤")
        menu = QMenu()
        menu.addAction("显示看板", self.show_window)
        menu.addSeparator()
        menu.addAction("退出", self.quit_app)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    def _on_tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.Trigger:
            self.toggle_window()

    def _make_tray_icon(self):
        # 优先使用项目图标，加载失败则回退到绘制的蓝色圆角方块
        icon_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "assets", "icon.ico",
        )
        if os.path.exists(icon_path):
            return QIcon(icon_path)
        pm = QPixmap(32, 32)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QColor("#4a90d9"))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(2, 2, 28, 28, 6, 6)
        p.end()
        return QIcon(pm)

    def _register_hotkey(self) -> None:
        hwnd = int(self.winId())
        self._hotkey_registered = bool(
            ctypes.windll.user32.RegisterHotKey(hwnd, HOTKEY_ID, MOD_CONTROL, VK_J)
        )
        if not self._hotkey_registered:
            self.tray.showMessage(
                "帅帅看板", "全局热键 Ctrl+J 注册失败（可能被其他程序占用）",
                QSystemTrayIcon.Warning, 3000,
            )

    def nativeEvent(self, eventType, message):
        if eventType in (b"windows_generic_MSG", "windows_generic_MSG"):
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                self.toggle_window()
                return True, 0
        return super().nativeEvent(eventType, message)

    def toggle_window(self) -> None:
        if self.isVisible() and not self.isMinimized():
            self.hide()
        else:
            self.show_window()

    def show_window(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def quit_app(self) -> None:
        self.tray.hide()
        self.db.close()
        QApplication.instance().quit()

    # ------------------------------------------------------------ 搜索 / 过滤
    def _apply_filter(self) -> None:
        keyword = self.search_edit.text().strip().lower()
        mode = self.filter_combo.currentData()
        active = bool(keyword) or mode != "all"
        today = date.today().isoformat()
        id_map = {t.id: t for t in self.db.list_todos()}

        for status, (title, header, lst, hint) in self._sections.items():
            visible = 0
            for i in range(lst.count()):
                item = lst.item(i)
                tid = item.data(Qt.UserRole)
                if tid is None:  # 空提示占位
                    item.setHidden(active)
                    continue
                todo = id_map.get(tid)
                if todo is None:
                    item.setHidden(True)
                    continue
                show = (not active) or self._match_todo(todo, keyword, mode, today)
                item.setHidden(not show)
                if show:
                    visible += 1
            if active:
                header.setText(f"{title}  ·  {visible}")

    def _match_todo(self, todo, keyword: str, mode: str, today: str) -> bool:
        if keyword and keyword not in (todo.title + " " + todo.description).lower():
            return False
        if mode == "high" and todo.priority != "high":
            return False
        if mode == "medium" and todo.priority != "medium":
            return False
        if mode == "low" and todo.priority != "low":
            return False
        if mode == "due_today" and todo.due_date != today:
            return False
        if mode == "overdue" and not (todo.due_date and todo.due_date < today and todo.status != "done"):
            return False
        return True

    # ------------------------------------------------------------ 到期提醒
    def _setup_due_reminders(self) -> None:
        self._reminded = set()
        self._due_timer = QTimer(self)
        self._due_timer.timeout.connect(self._check_due_reminders)
        self._due_timer.start(60_000)
        self._check_due_reminders()

    def _check_due_reminders(self) -> None:
        today = date.today().isoformat()
        msgs = []
        for t in self.db.list_todos():
            if t.status == "done" or not t.due_date:
                continue
            if t.due_date == today and f"d{t.id}" not in self._reminded:
                self._reminded.add(f"d{t.id}")
                msgs.append(f"「{t.title}」今天到期")
            elif t.due_date < today and f"o{t.id}" not in self._reminded:
                self._reminded.add(f"o{t.id}")
                msgs.append(f"「{t.title}」已逾期")
        if msgs:
            self.tray.showMessage(
                "帅帅看板 · 到期提醒", "\n".join(msgs[:5]), QSystemTrayIcon.Warning, 6000
            )

    # ------------------------------------------------------------ 智能添加
    def on_smart_add(self) -> None:
        models = self.db.list_ai_models()
        if not models:
            QMessageBox.warning(self, "提示", "请先在「🤖 AI 模型」里配置一个模型")
            return
        cats = self.db.list_categories()
        if not cats:
            QMessageBox.warning(self, "提示", "请先添加一个分类")
            return
        # 新任务归属今天
        if self.current_date != date.today():
            self.current_date = date.today()
            self._update_date_btn()
        dlg = SmartAddDialog(models, cats, parent=self)
        if dlg.exec() == QDialog.Accepted and dlg.result:
            r = dlg.result
            cat_id = cats[0].id
            for c in cats:
                if c.name == r["category"]:
                    cat_id = c.id
                    break
            prefill = {
                "title": r["title"],
                "description": r["description"],
                "priority": r["priority"],
                "due_date": r["due_date"],
                "category_id": cat_id,
            }
            todo_dlg = TodoDialog(cats, prefill=prefill, parent=self)
            if todo_dlg.exec():
                d = todo_dlg.data()
                todo = self.db.add_todo(
                    d["title"], d["category_id"], d["description"], d["priority"], d["due_date"]
                )
                if todo:
                    for title, done in d["subtasks"]:
                        self.db.add_subtask(todo.id, title, done)
                self.refresh_all()

    # ------------------------------------------------------------ 清理
    def closeEvent(self, event) -> None:
        # 关闭按钮 → 隐藏到托盘，Ctrl+J 可随时召唤
        event.ignore()
        self.hide()
        self.tray.showMessage("帅帅看板", "已隐藏到托盘，Ctrl+J 召唤", QSystemTrayIcon.Information, 2000)
