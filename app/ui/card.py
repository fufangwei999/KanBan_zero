"""待办卡片组件：三态（待办/进行中/已完成），含状态切换、编辑、删除。"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QToolButton,
    QVBoxLayout,
)

from ..database import PRIORITY_COLORS, PRIORITY_LABELS, Todo

_BASE_STYLE = (
    "QFrame#todoCard{background:#ffffff;border:1px solid #e3e6ea;border-radius:8px;}"
)
_DOING_STYLE = (
    "QFrame#todoCard{background:#eef4ff;border:1px solid #4a90d9;border-radius:8px;}"
)
_DONE_STYLE = (
    "QFrame#todoCard{background:#f2f4f7;border:1px solid #e0e4ea;border-radius:8px;}"
)


class CardWidget(QFrame):
    status_requested = Signal(int, str)  # todo_id, new_status
    edit_requested = Signal(int)         # todo_id
    delete_requested = Signal(int)       # todo_id
    download_requested = Signal(int, int)  # todo_id, attachment_id

    def __init__(self, todo: Todo, category_name: str, category_color: str,
                 current_date: str, subtasks=None, attachments=None, parent=None):
        super().__init__(parent)
        self.todo = todo
        self.category_name = category_name
        self.category_color = category_color
        self.current_date = current_date  # "YYYY-MM-DD"
        self.subtasks = subtasks or []
        self.attachments = attachments or []
        self.setObjectName("todoCard")
        self._build()

    def _build(self) -> None:
        t = self.todo
        if t.status == "doing":
            self.setStyleSheet(_DOING_STYLE)
        elif t.status == "done":
            self.setStyleSheet(_DONE_STYLE)
        else:
            self.setStyleSheet(_BASE_STYLE)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # 左侧优先级色条
        bar = QFrame()
        bar.setFixedWidth(5)
        bar.setStyleSheet(
            f"background:{PRIORITY_COLORS.get(t.priority, '#999999')};border:none;"
        )
        outer.addWidget(bar)

        inner = QVBoxLayout()
        inner.setContentsMargins(12, 9, 12, 9)
        inner.setSpacing(5)

        # 顶行：标题 + 优先级标签
        top = QHBoxLayout()
        top.setSpacing(6)
        self.title_lbl = QLabel(t.title)
        self.title_lbl.setWordWrap(True)
        self.title_lbl.setStyleSheet("font-weight:600;font-size:14px;")
        top.addWidget(self.title_lbl, 1)
        badge = QLabel(PRIORITY_LABELS.get(t.priority, t.priority))
        badge.setStyleSheet(
            f"background:{PRIORITY_COLORS.get(t.priority, '#999999')};color:#ffffff;"
            "border-radius:9px;padding:1px 8px;font-size:11px;"
        )
        top.addWidget(badge, 0, Qt.AlignTop)
        inner.addLayout(top)

        # 分类标签 + 状态标签
        meta = QHBoxLayout()
        meta.setSpacing(6)
        if self.category_name:
            cat = QLabel(f"● {self.category_name}")
            cat.setStyleSheet(f"color:{self.category_color};font-size:11px;")
            meta.addWidget(cat)
        if t.status == "doing":
            doing_lbl = QLabel("🔄 进行中")
            doing_lbl.setStyleSheet("color:#4a90d9;font-size:11px;font-weight:600;")
            meta.addWidget(doing_lbl)
        meta.addStretch(1)
        inner.addLayout(meta)

        # 描述
        if t.description.strip():
            desc = QLabel(t.description.strip())
            desc.setWordWrap(True)
            desc.setStyleSheet("color:#666666;font-size:12px;")
            inner.addWidget(desc)

        # 子任务进度
        if self.subtasks:
            done_count = sum(1 for s in self.subtasks if s.done)
            prog = QLabel(f"☑ 子任务 {done_count}/{len(self.subtasks)}")
            prog.setStyleSheet("color:#4a90d9;font-size:11px;font-weight:600;")
            inner.addWidget(prog)

        # 附件信息
        if self.attachments:
            for a in self.attachments:
                row = QHBoxLayout()
                row.setSpacing(6)
                attach_lbl = QLabel(f"📎 {a.file_name}")
                attach_lbl.setWordWrap(True)
                attach_lbl.setStyleSheet("color:#8a94a6;font-size:11px;")
                if a.summary:
                    attach_lbl.setToolTip(f"✨ {a.summary}")
                    attach_lbl.setStyleSheet(
                        "color:#8a94a6;font-size:11px;border-bottom:1px dashed #c4ccd6;"
                    )
                row.addWidget(attach_lbl, 1)
                dl_btn = QToolButton()
                dl_btn.setText("⬇")
                dl_btn.setToolTip(f"下载 {a.file_name}")
                dl_btn.setCursor(Qt.PointingHandCursor)
                dl_btn.setStyleSheet(
                    "QToolButton{border:1px solid #d7dce3;border-radius:4px;"
                    "background:#ffffff;color:#4a90d9;font-size:12px;padding:1px 6px;}"
                    "QToolButton:hover{background:#eef4ff;border-color:#4a90d9;}"
                )
                dl_btn.clicked.connect(
                    lambda _=False, aid=a.id: self.download_requested.emit(self.todo.id, aid)
                )
                row.addWidget(dl_btn, 0, Qt.AlignTop)
                inner.addLayout(row)

        # 日期信息行
        info = QHBoxLayout()
        info.setSpacing(8)
        if t.status != "done":
            created_date = t.created_at[:10]
            if created_date < self.current_date:
                pend = QLabel(f"📌 {created_date} 未完成")
                pend.setStyleSheet("color:#e67e22;font-size:11px;font-weight:600;")
                info.addWidget(pend)
            if t.due_date:
                overdue = t.due_date < self.current_date
                dc = "#E53935" if overdue else "#999999"
                due = QLabel(f"📅 期望 {t.due_date}")
                due.setStyleSheet(f"color:{dc};font-size:11px;")
                info.addWidget(due)
        else:
            done_lbl = QLabel(f"✓ 完成于 {t.completed_at[5:16]}")
            done_lbl.setStyleSheet("color:#7ed321;font-size:11px;font-weight:600;")
            info.addWidget(done_lbl)
        info.addStretch(1)
        inner.addLayout(info)

        # 底部按钮行（三态）
        btns = QHBoxLayout()
        btns.setSpacing(4)
        if t.status == "todo":
            self.start_btn = self._make_btn("▶ 开始", "startBtn", "doing")
            self.done_btn = self._make_btn("✓ 完成", "doneBtn", "done")
            btns.addWidget(self.start_btn)
            btns.addWidget(self.done_btn)
        elif t.status == "doing":
            self.done_btn = self._make_btn("✓ 完成", "doneBtn", "done")
            self.undo_btn = self._make_btn("↩ 待办", "undoBtn", "todo")
            btns.addWidget(self.done_btn)
            btns.addWidget(self.undo_btn)
        else:
            # 撤销：恢复到「完成前状态」（待办里完成的回待办，进行中里完成的回进行中）
            self.undo_btn = self._make_btn("↩ 撤销", "undoBtn", self.todo.prev_status or "todo")
            btns.addWidget(self.undo_btn)
        btns.addStretch(1)

        self.edit_btn = QToolButton()
        self.edit_btn.setText("编辑")
        self.edit_btn.setCursor(Qt.PointingHandCursor)
        self.edit_btn.clicked.connect(lambda: self.edit_requested.emit(self.todo.id))
        self.del_btn = QToolButton()
        self.del_btn.setText("删除")
        self.del_btn.setCursor(Qt.PointingHandCursor)
        self.del_btn.clicked.connect(lambda: self.delete_requested.emit(self.todo.id))
        for b in (self.edit_btn, self.del_btn):
            b.setStyleSheet(
                "QToolButton{border:none;background:transparent;color:#8a94a6;"
                "font-size:11px;padding:2px 5px;border-radius:4px;}"
                "QToolButton:hover{background:#f0f2f5;color:#4a90d9;}"
            )
        btns.addWidget(self.edit_btn)
        btns.addWidget(self.del_btn)
        inner.addLayout(btns)

        outer.addLayout(inner, 1)

        if t.status == "done":
            self.title_lbl.setStyleSheet(
                "font-weight:600;font-size:14px;color:#aab2bf;text-decoration:line-through;"
            )

    def _make_btn(self, text, obj_name, target_status):
        b = QPushButton(text)
        b.setObjectName(obj_name)
        b.setCursor(Qt.PointingHandCursor)
        b.clicked.connect(lambda: self.status_requested.emit(self.todo.id, target_status))
        return b
