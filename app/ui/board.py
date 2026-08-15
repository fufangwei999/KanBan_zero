"""待办列表组件：三区（待办/进行中/已完成），拖拽切换状态 + 选中追踪。"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QAbstractItemView, QListWidget, QListWidgetItem

from .card import CardWidget


class TodoListWidget(QListWidget):
    item_dropped = Signal(int, str)      # todo_id, target_status
    status_requested = Signal(int, str)  # todo_id, new_status
    edit_requested = Signal(int)         # todo_id
    delete_requested = Signal(int)       # todo_id
    selected = Signal(int)               # todo_id，当前选中

    def __init__(self, target_status: str, parent=None):
        super().__init__(parent)
        self.target_status = target_status
        self.current_date = ""  # 由外部在刷新前设置
        self.setObjectName("todoList")
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setSpacing(6)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setStyleSheet(
            "QListWidget#todoList{background:#f4f6f9;border:none;border-radius:8px;}"
            "QListWidget#todoList::item{border:none;}"
        )
        self.currentItemChanged.connect(self._on_current_changed)

    def _on_current_changed(self, current, previous) -> None:
        if current is not None and (current.flags() & Qt.ItemIsDragEnabled):
            self.selected.emit(current.data(Qt.UserRole))

    # ---------- 填充 ----------
    def load_todos(self, todos, get_meta, empty_hint: str, subtasks_map=None) -> None:
        self.clear()
        if not todos:
            item = QListWidgetItem(empty_hint)
            item.setFlags(Qt.NoItemFlags)
            item.setTextAlignment(Qt.AlignCenter)
            item.setForeground(Qt.gray)
            self.addItem(item)
            return
        for t in todos:
            subs = (subtasks_map or {}).get(t.id, [])
            self.add_todo(t, get_meta, subs)

    def add_todo(self, todo, get_meta, subtasks=None) -> None:
        cat_name, cat_color = get_meta(todo.category_id)
        card = CardWidget(todo, cat_name, cat_color, self.current_date, subtasks)
        card.status_requested.connect(self.status_requested)
        card.edit_requested.connect(self.edit_requested)
        card.delete_requested.connect(self.delete_requested)

        item = QListWidgetItem()
        item.setData(Qt.UserRole, todo.id)
        item.setFlags(item.flags() | Qt.ItemIsDragEnabled)
        self.addItem(item)
        self.setItemWidget(item, card)
        item.setSizeHint(card.sizeHint())
        self._update_item_widths()

    # ---------- 拖拽 ----------
    def _active_item(self):
        item = self.currentItem()
        if item is None and self.selectedItems():
            item = self.selectedItems()[0]
        return item

    def dropEvent(self, event) -> None:
        source = event.source()
        if source is self:
            event.ignore()
            return
        if isinstance(source, TodoListWidget):
            item = source._active_item()
            if item is None:
                event.ignore()
                return
            todo_id = item.data(Qt.UserRole)
            source.takeItem(source.row(item))
            self.item_dropped.emit(todo_id, self.target_status)
            event.accept()
            return
        event.ignore()

    # ---------- 布局 ----------
    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_item_widths()

    def _update_item_widths(self) -> None:
        w = max(60, self.viewport().width() - 12)
        for i in range(self.count()):
            item = self.item(i)
            card = self.itemWidget(item)
            if card is not None:
                card.setFixedWidth(w)
                item.setSizeHint(card.sizeHint())
