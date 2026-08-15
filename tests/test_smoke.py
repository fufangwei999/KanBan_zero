"""Zero看板 冒烟测试（回归）。

运行方式（项目根目录）：
    venv\\Scripts\\python tests/test_smoke.py
"""
import os
import sys
import tempfile
import unittest
from datetime import date

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from app.database import Database, Todo
from app import ai as ai_module
from app.ai import build_report_prompt, parse_natural_language_todo
from app.ui.dialogs import SmartAddDialog, TodoDialog

_app = None


def _qapp():
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication([])
    return _app


def _tmp_db():
    path = tempfile.mktemp(suffix=".db")
    return Database(path), path


class DatabaseTest(unittest.TestCase):
    def setUp(self):
        self.db, self.path = _tmp_db()

    def tearDown(self):
        self.db.close()
        os.remove(self.path)

    def test_status_flow_with_undo(self):
        cats = self.db.list_categories()
        tid = self.db.add_todo("任务", cats[0].id).id
        self.db.set_todo_status(tid, "doing")
        self.assertEqual(self.db.get_todo(tid).status, "doing")
        self.db.set_todo_status(tid, "done")
        t = self.db.get_todo(tid)
        self.assertEqual(t.status, "done")
        self.assertTrue(t.completed_at)
        self.assertEqual(t.prev_status, "doing")

    def test_status_on_and_between(self):
        cats = self.db.list_categories()
        self.db.add_todo("A", cats[0].id)
        b = self.db.add_todo("B", cats[1].id).id
        self.db.set_todo_status(b, "done")
        today = date.today().isoformat()
        self.assertEqual(len(self.db.todos_status_on("todo", today)), 1)
        self.assertEqual(len(self.db.todos_status_on("done", today)), 1)

    def test_soft_delete_restore_purge(self):
        cats = self.db.list_categories()
        tid = self.db.add_todo("任务", cats[0].id).id
        self.db.delete_todo(tid)
        self.assertNotIn(tid, [t.id for t in self.db.list_todos()])          # 正常列表隐藏
        self.assertIn(tid, [t.id for t in self.db.list_deleted_todos()])     # 进入回收站
        self.db.restore_todo(tid)
        self.assertIn(tid, [t.id for t in self.db.list_todos()])             # 恢复
        self.assertEqual(self.db.list_deleted_todos(), [])
        self.db.delete_todo(tid)
        self.db.purge_todo(tid)                                              # 彻底删除
        self.assertEqual(self.db.list_deleted_todos(), [])
        self.assertIsNone(self.db.get_todo(tid))

    def test_backup_database(self):
        import app.database as dbmod

        orig = dbmod.DB_PATH
        dbmod.DB_PATH = self.path  # 指向临时库，隔离真实数据
        try:
            cats = self.db.list_categories()
            self.db.add_todo("备份测试", cats[0].id)
            result = dbmod.backup_database(keep=3)
            self.assertIsNotNone(result)          # 首次备份成功
            self.assertIsNone(dbmod.backup_database(keep=3))  # 同日二次调用跳过
            self.assertTrue(os.path.exists(result))
            import glob
            backup_dir = os.path.dirname(result)
            for f in glob.glob(os.path.join(backup_dir, "kanban-*.db")):
                os.remove(f)
        finally:
            dbmod.DB_PATH = orig

    def test_subtasks_crud(self):
        cats = self.db.list_categories()
        tid = self.db.add_todo("大任务", cats[0].id).id
        s1 = self.db.add_subtask(tid, "步骤1")
        s2 = self.db.add_subtask(tid, "步骤2", done=True)
        subs = self.db.list_subtasks(tid)
        self.assertEqual(len(subs), 2)
        self.assertTrue(subs[1].done)
        self.assertEqual(len(self.db.subtasks_map().get(tid, [])), 2)
        self.db.set_subtask_done(s1.id, True)
        self.assertTrue(next(s for s in self.db.list_subtasks(tid) if s.id == s1.id).done)
        self.db.delete_subtask(s1.id)
        self.assertEqual(len(self.db.list_subtasks(tid)), 1)
        self.db.clear_subtasks(tid)
        self.assertEqual(self.db.list_subtasks(tid), [])


class AiTest(unittest.TestCase):
    def test_report_prompt_sections(self):
        msgs = build_report_prompt(
            [("当日新建", [Todo(1, "A", 1)]), ("当日完成", [Todo(2, "B", 1)])], "当日"
        )
        content = msgs[1]["content"]
        self.assertIn("当日新建", content)
        self.assertIn("A", content)

    def test_parse_natural_language(self):
        db, path = _tmp_db()
        try:
            cats = db.list_categories()
            m = db.add_ai_model("本地", "http://localhost:11434/v1", "ollama", "qwen3:8b")
        finally:
            db.close()
            os.remove(path)
        orig = ai_module.call_chat_completion
        ai_module.call_chat_completion = lambda *a, **k: (
            '{"title":"交周报","priority":"high","due_date":"2026-08-15","category":"待办","description":""}'
        )
        try:
            r = parse_natural_language_todo(m, "明天交周报高优先级", cats, "2026-08-14")
        finally:
            ai_module.call_chat_completion = orig
        self.assertEqual(r["title"], "交周报")
        self.assertEqual(r["priority"], "high")
        self.assertEqual(r["due_date"], "2026-08-15")


class UiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _qapp()

    def test_todo_dialog_prefill(self):
        db, path = _tmp_db()
        try:
            cats = db.list_categories()
        finally:
            db.close()
            os.remove(path)
        dlg = TodoDialog(
            cats,
            prefill={"title": "预填", "priority": "low", "due_date": "2026-08-20",
                     "category_id": cats[1].id, "description": ""},
        )
        self.assertEqual(dlg.title_edit.text(), "预填")
        self.assertEqual(dlg.priority_combo.currentData(), "low")

    def test_smart_add_dialog(self):
        db, path = _tmp_db()
        try:
            cats = db.list_categories()
            m = db.add_ai_model("本地", "http://localhost:11434/v1", "ollama", "qwen3:8b")
        finally:
            db.close()
            os.remove(path)
        dlg = SmartAddDialog([m], cats)
        self.assertIsNotNone(dlg.input_edit)
        self.assertIsNone(dlg.model_combo)  # 单模型不显示选择器

    def test_match_todo_filter(self):
        from app.ui.main_window import MainWindow

        win = MainWindow()
        win.db.close()
        db, path = _tmp_db()
        win.db = db
        cats = db.list_categories()
        t = Todo(100, "测试任务", cats[0].id, priority="high", due_date="2026-08-15")
        self.assertTrue(win._match_todo(t, "", "high", "2026-08-14"))
        self.assertFalse(win._match_todo(t, "不存在", "all", "2026-08-14"))
        self.assertFalse(win._match_todo(t, "", "low", "2026-08-14"))
        overdue = Todo(101, "逾期", cats[0].id, due_date="2026-08-01", status="todo")
        self.assertTrue(win._match_todo(overdue, "", "overdue", "2026-08-14"))
        win.db.close()
        os.remove(path)

    def test_todo_dialog_subtasks(self):
        db, path = _tmp_db()
        try:
            cats = db.list_categories()
        finally:
            db.close()
            os.remove(path)
        dlg = TodoDialog(cats)
        dlg.subtask_edit.setText("子任务A")
        dlg._add_subtask()
        dlg.subtask_edit.setText("子任务B")
        dlg._add_subtask()
        self.assertEqual(len(dlg.subtasks), 2)
        dlg.subtask_list.item(0).setCheckState(Qt.Checked)
        self.assertTrue(dlg.subtasks[0][1])
        self.assertEqual(len(dlg.data()["subtasks"]), 2)

    def test_calendar_view(self):
        from app.ui.calendar_view import CalendarView

        db, path = _tmp_db()
        try:
            cats = db.list_categories()
            db.add_todo("带日期任务", cats[0].id, due_date=date.today().isoformat())
            view = CalendarView(db)
            view.refresh()
            self.assertIsNotNone(view.cal)
            self.assertEqual(view.task_list.count(), 1)
        finally:
            db.close()
            os.remove(path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
