"""数据层：SQLite 存储 + 数据模型定义。

任务三态：todo（待办）/ doing（进行中）/ done（已完成）。
撤销恢复到「完成前状态」：进入 done 时记录 prev_status，撤销时恢复。
"""
import glob
import os
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "kanban.db")
ATTACH_DIR = os.path.join(DATA_DIR, "attachments")


def attach_dir_for(db_path: str) -> str:
    """附件根目录跟随数据库文件名（不同库互不干扰，测试天然隔离）。

    data/kanban.db      → data/kanban_attachments/
    Temp/xxx123.db      → Temp/xxx123_attachments/
    """
    base = os.path.splitext(os.path.basename(os.path.abspath(db_path)))[0]
    return os.path.join(os.path.dirname(os.path.abspath(db_path)), f"{base}_attachments")


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@dataclass
class Category:
    id: int
    name: str
    color: str = "#4A90D9"
    position: int = 0
    created_at: str = ""


@dataclass
class Todo:
    id: int
    title: str
    category_id: int
    description: str = ""
    priority: str = "medium"       # high / medium / low
    due_date: str = ""             # YYYY-MM-DD
    status: str = "todo"           # todo / doing / done
    prev_status: str = ""          # 进入 done 前的状态，撤销时恢复
    completed_at: str = ""         # 完成时间（status=done 时记录）
    created_at: str = ""
    updated_at: str = ""
    sort_order: int = 0
    deleted: bool = False          # 软删除标记（回收站）


@dataclass
class Subtask:
    id: int
    todo_id: int
    title: str
    done: bool = False
    sort_order: int = 0
    created_at: str = ""


@dataclass
class Attachment:
    id: int
    todo_id: int
    file_name: str
    stored_path: str
    file_size: int = 0
    summary: str = ""          # AI 摘要（docx/txt）
    created_at: str = ""


@dataclass
class AiModel:
    id: int
    name: str
    base_url: str
    api_key: str
    model: str
    created_at: str = ""


PRIORITY_LABELS = {"high": "高", "medium": "中", "low": "低"}
PRIORITY_COLORS = {"high": "#E53935", "medium": "#F5A623", "low": "#4A90D9"}
STATUS_LABELS = {"todo": "待办", "doing": "进行中", "done": "已完成"}


class Database:
    """封装所有 SQLite 读写操作。"""

    def __init__(self, path: str = DB_PATH):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._init_schema()
        self._migrate()
        self._seed_defaults()

    # ---------- schema ----------
    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                color TEXT NOT NULL DEFAULT '#4A90D9',
                position INTEGER NOT NULL DEFAULT 0,
                created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS todos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                category_id INTEGER NOT NULL,
                priority TEXT NOT NULL DEFAULT 'medium',
                due_date TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'todo',
                prev_status TEXT NOT NULL DEFAULT '',
                completed_at TEXT,
                created_at TEXT,
                updated_at TEXT,
                sort_order INTEGER NOT NULL DEFAULT 0,
                deleted INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS ai_models (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                base_url TEXT NOT NULL,
                api_key TEXT NOT NULL,
                model TEXT NOT NULL,
                created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS subtasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                todo_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                done INTEGER NOT NULL DEFAULT 0,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT,
                FOREIGN KEY (todo_id) REFERENCES todos(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS attachments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                todo_id INTEGER NOT NULL,
                file_name TEXT NOT NULL,
                stored_path TEXT NOT NULL,
                file_size INTEGER NOT NULL DEFAULT 0,
                summary TEXT NOT NULL DEFAULT '',
                created_at TEXT,
                FOREIGN KEY (todo_id) REFERENCES todos(id) ON DELETE CASCADE
            );
            """
        )
        self.conn.commit()

    def _migrate(self) -> None:
        """旧库平滑迁移：done→status、补 prev_status 列。"""

        def cols():
            return [r[1] for r in self.conn.execute("PRAGMA table_info(todos)").fetchall()]

        if "status" not in cols():
            self.conn.execute(
                "ALTER TABLE todos ADD COLUMN status TEXT NOT NULL DEFAULT 'todo'"
            )
            if "done" in cols():
                self.conn.execute("UPDATE todos SET status='done' WHERE done=1")
        if "prev_status" not in cols():
            self.conn.execute(
                "ALTER TABLE todos ADD COLUMN prev_status TEXT NOT NULL DEFAULT ''"
            )
        if "deleted" not in cols():
            self.conn.execute(
                "ALTER TABLE todos ADD COLUMN deleted INTEGER NOT NULL DEFAULT 0"
            )
        self.conn.commit()

    def _seed_defaults(self) -> None:
        row = self.conn.execute("SELECT COUNT(*) AS c FROM categories").fetchone()
        if row["c"] == 0:
            defaults = [("待办", "#4A90D9"), ("进行中", "#F5A623"), ("已完成", "#7ED321")]
            for i, (name, color) in enumerate(defaults):
                self.conn.execute(
                    "INSERT INTO categories(name, color, position, created_at) VALUES(?,?,?,?)",
                    (name, color, i, now_str()),
                )
            self.conn.commit()

    # ---------- categories ----------
    def list_categories(self) -> List[Category]:
        rows = self.conn.execute(
            "SELECT * FROM categories ORDER BY position ASC, id ASC"
        ).fetchall()
        return [Category(**dict(r)) for r in rows]

    def add_category(self, name: str, color: str = "#4A90D9") -> Optional[Category]:
        name = name.strip()
        if not name:
            return None
        max_pos = self.conn.execute(
            "SELECT COALESCE(MAX(position), -1) AS m FROM categories"
        ).fetchone()["m"]
        cur = self.conn.execute(
            "INSERT INTO categories(name, color, position, created_at) VALUES(?,?,?,?)",
            (name, color, max_pos + 1, now_str()),
        )
        self.conn.commit()
        return Category(id=cur.lastrowid, name=name, color=color, position=max_pos + 1, created_at=now_str())

    def rename_category(self, cat_id: int, name: str, color: str) -> None:
        self.conn.execute(
            "UPDATE categories SET name=?, color=? WHERE id=?",
            (name.strip(), color, cat_id),
        )
        self.conn.commit()

    def delete_category(self, cat_id: int) -> None:
        remaining = [c for c in self.list_categories() if c.id != cat_id]
        if not remaining:
            remaining = [self.add_category("待办")]
        target = min(remaining, key=lambda c: c.position).id
        self.conn.execute(
            "UPDATE todos SET category_id=? WHERE category_id=?", (target, cat_id)
        )
        self.conn.execute("DELETE FROM categories WHERE id=?", (cat_id,))
        self.conn.commit()

    def reorder_categories(self, ordered_ids: List[int]) -> None:
        for i, cid in enumerate(ordered_ids):
            self.conn.execute("UPDATE categories SET position=? WHERE id=?", (i, cid))
        self.conn.commit()

    # ---------- todos ----------
    def list_todos(self) -> List[Todo]:
        rows = self.conn.execute(
            "SELECT * FROM todos WHERE deleted=0 ORDER BY created_at ASC, id ASC"
        ).fetchall()
        return [Todo(**dict(r)) for r in rows]

    def add_todo(
        self,
        title: str,
        category_id: int,
        description: str = "",
        priority: str = "medium",
        due_date: str = "",
    ) -> Optional[Todo]:
        title = title.strip()
        if not title:
            return None
        ts = now_str()
        max_order = self.conn.execute(
            "SELECT COALESCE(MAX(sort_order), -1) AS m FROM todos WHERE category_id=?",
            (category_id,),
        ).fetchone()["m"]
        cur = self.conn.execute(
            """INSERT INTO todos(title, description, category_id, priority, due_date,
                                 status, prev_status, completed_at, created_at, updated_at, sort_order)
               VALUES(?,?,?,?,?,'todo','',NULL,?,?,?)""",
            (title, description, category_id, priority, due_date, ts, ts, max_order + 1),
        )
        self.conn.commit()
        return self.get_todo(cur.lastrowid)

    def get_todo(self, todo_id: int) -> Optional[Todo]:
        row = self.conn.execute("SELECT * FROM todos WHERE id=?", (todo_id,)).fetchone()
        return Todo(**dict(row)) if row else None

    def update_todo(
        self, todo_id: int, title: str, description: str, priority: str, due_date: str
    ) -> None:
        self.conn.execute(
            """UPDATE todos SET title=?, description=?, priority=?, due_date=?, updated_at=?
               WHERE id=?""",
            (title.strip(), description, priority, due_date, now_str(), todo_id),
        )
        self.conn.commit()

    def move_todo(self, todo_id: int, category_id: int) -> None:
        self.conn.execute(
            "UPDATE todos SET category_id=?, updated_at=? WHERE id=?",
            (category_id, now_str(), todo_id),
        )
        self.conn.commit()

    def set_todo_status(self, todo_id: int, status: str) -> None:
        """设置状态。

        - 进入 done：记录完成时间与「完成前状态」（prev_status），供撤销时恢复。
        - 离开 done：清空 completed_at 与 prev_status。
        """
        current = self.get_todo(todo_id)
        if current is None:
            return
        if status == "done":
            completed_at = now_str()
            prev_status = (
                current.prev_status if current.status == "done" else (current.status or "todo")
            )
        else:
            completed_at = ""
            prev_status = ""
        self.conn.execute(
            "UPDATE todos SET status=?, completed_at=?, prev_status=?, updated_at=? WHERE id=?",
            (status, completed_at, prev_status, now_str(), todo_id),
        )
        self.conn.commit()

    def delete_todo(self, todo_id: int) -> None:
        """软删除：移入回收站，可恢复。"""
        self.conn.execute(
            "UPDATE todos SET deleted=1, updated_at=? WHERE id=?",
            (now_str(), todo_id),
        )
        self.conn.commit()

    # ---------- ai models ----------
    def list_ai_models(self) -> List[AiModel]:
        rows = self.conn.execute("SELECT * FROM ai_models ORDER BY id ASC").fetchall()
        return [AiModel(**dict(r)) for r in rows]

    def add_ai_model(self, name: str, base_url: str, api_key: str, model: str) -> Optional[AiModel]:
        name = name.strip()
        if not name or not base_url.strip() or not model.strip():
            return None
        cur = self.conn.execute(
            "INSERT INTO ai_models(name, base_url, api_key, model, created_at) VALUES(?,?,?,?,?)",
            (name, base_url.strip(), api_key, model.strip(), now_str()),
        )
        self.conn.commit()
        return AiModel(id=cur.lastrowid, name=name, base_url=base_url.strip(),
                       api_key=api_key, model=model.strip(), created_at=now_str())

    def update_ai_model(self, mid: int, name: str, base_url: str, api_key: str, model: str) -> None:
        self.conn.execute(
            "UPDATE ai_models SET name=?, base_url=?, api_key=?, model=? WHERE id=?",
            (name.strip(), base_url.strip(), api_key, model.strip(), mid),
        )
        self.conn.commit()

    def delete_ai_model(self, mid: int) -> None:
        self.conn.execute("DELETE FROM ai_models WHERE id=?", (mid,))
        self.conn.commit()

    # ---------- 报告 / 看板查询 ----------
    def todos_completed_between(self, start: datetime, end: datetime) -> List[Todo]:
        """status=done 且 completed_at 落在 [start, end) 区间。"""
        rows = self.conn.execute(
            """SELECT * FROM todos
               WHERE status='done' AND deleted=0 AND completed_at >= ? AND completed_at < ?
               ORDER BY completed_at ASC""",
            (start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S")),
        ).fetchall()
        return [Todo(**dict(r)) for r in rows]

    def todos_created_between(self, start: datetime, end: datetime) -> List[Todo]:
        """created_at 落在 [start, end) 区间（不限状态）。"""
        rows = self.conn.execute(
            """SELECT * FROM todos
               WHERE deleted=0 AND created_at >= ? AND created_at < ?
               ORDER BY created_at ASC""",
            (start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S")),
        ).fetchall()
        return [Todo(**dict(r)) for r in rows]

    def list_pending_todos(self) -> List[Todo]:
        """所有未完成（todo + doing）。"""
        rows = self.conn.execute(
            "SELECT * FROM todos WHERE status != 'done' AND deleted=0 ORDER BY created_at ASC, id ASC"
        ).fetchall()
        return [Todo(**dict(r)) for r in rows]

    def todos_pending_until(self, date_str: str) -> List[Todo]:
        """未完成（todo + doing）且创建日期 <= date_str（含历史滚动）。"""
        rows = self.conn.execute(
            """SELECT * FROM todos
               WHERE status != 'done' AND deleted=0 AND substr(created_at, 1, 10) <= ?
               ORDER BY created_at ASC, id ASC""",
            (date_str,),
        ).fetchall()
        return [Todo(**dict(r)) for r in rows]

    def todos_status_on(self, status: str, date_str: str) -> List[Todo]:
        """某状态在某日显示的内容。todo/doing 按 created<=date 滚动，done 按完成日。"""
        if status == "done":
            rows = self.conn.execute(
                """SELECT * FROM todos
                   WHERE status='done' AND deleted=0 AND substr(completed_at, 1, 10) = ?
                   ORDER BY completed_at ASC, id ASC""",
                (date_str,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                """SELECT * FROM todos
                   WHERE status=? AND deleted=0 AND substr(created_at, 1, 10) <= ?
                   ORDER BY created_at ASC, id ASC""",
                (status, date_str),
            ).fetchall()
        return [Todo(**dict(r)) for r in rows]

    # ---------- 子任务 / 检查清单 ----------
    def list_subtasks(self, todo_id: int) -> List[Subtask]:
        rows = self.conn.execute(
            "SELECT * FROM subtasks WHERE todo_id=? ORDER BY sort_order ASC, id ASC",
            (todo_id,),
        ).fetchall()
        return [Subtask(**dict(r)) for r in rows]

    def subtasks_map(self) -> dict:
        """返回 {todo_id: [Subtask, ...]} 映射，供看板批量加载。"""
        rows = self.conn.execute(
            "SELECT * FROM subtasks ORDER BY sort_order ASC, id ASC"
        ).fetchall()
        m = {}
        for r in rows:
            s = Subtask(**dict(r))
            m.setdefault(s.todo_id, []).append(s)
        return m

    def add_subtask(self, todo_id: int, title: str, done: bool = False) -> Optional[Subtask]:
        title = title.strip()
        if not title:
            return None
        max_order = self.conn.execute(
            "SELECT COALESCE(MAX(sort_order), -1) AS m FROM subtasks WHERE todo_id=?",
            (todo_id,),
        ).fetchone()["m"]
        cur = self.conn.execute(
            "INSERT INTO subtasks(todo_id, title, done, sort_order, created_at) VALUES(?,?,?,?,?)",
            (todo_id, title, 1 if done else 0, max_order + 1, now_str()),
        )
        self.conn.commit()
        return Subtask(id=cur.lastrowid, todo_id=todo_id, title=title,
                       done=done, sort_order=max_order + 1, created_at=now_str())

    def set_subtask_done(self, subtask_id: int, done: bool) -> None:
        self.conn.execute(
            "UPDATE subtasks SET done=? WHERE id=?", (1 if done else 0, subtask_id)
        )
        self.conn.commit()

    def delete_subtask(self, subtask_id: int) -> None:
        self.conn.execute("DELETE FROM subtasks WHERE id=?", (subtask_id,))
        self.conn.commit()

    def clear_subtasks(self, todo_id: int) -> None:
        self.conn.execute("DELETE FROM subtasks WHERE todo_id=?", (todo_id,))
        self.conn.commit()

    # ---------- 附件 ----------
    def list_attachments(self, todo_id: int) -> List[Attachment]:
        rows = self.conn.execute(
            "SELECT * FROM attachments WHERE todo_id=? ORDER BY id ASC",
            (todo_id,),
        ).fetchall()
        return [Attachment(**dict(r)) for r in rows]

    def attachments_map(self) -> dict:
        """返回 {todo_id: [Attachment, ...]} 映射，供看板批量加载。"""
        rows = self.conn.execute("SELECT * FROM attachments ORDER BY id ASC").fetchall()
        m = {}
        for r in rows:
            a = Attachment(**dict(r))
            m.setdefault(a.todo_id, []).append(a)
        return m

    def add_attachment(self, todo_id: int, src_path: str, summary: str = "") -> Optional[Attachment]:
        """复制文件到 data/attachments/<todo_id>/ 并入库。

        src_path 不存在时返回 None。同名文件自动加序号（不覆盖）。
        复制/入库失败时抛出带上下文信息的异常（不静默失败）。
        """
        if not os.path.isfile(src_path):
            return None
        file_name = os.path.basename(src_path) or "attachment"
        folder = os.path.join(attach_dir_for(self.path), str(todo_id))
        os.makedirs(folder, exist_ok=True)
        # 同名冲突 → 追加 (1)、(2)
        base, ext = os.path.splitext(file_name)
        stored = os.path.join(folder, file_name)
        n = 1
        while os.path.exists(stored):
            stored = os.path.join(folder, f"{base} ({n}){ext}")
            n += 1
        try:
            shutil.copy2(src_path, stored)
        except OSError as e:
            # 复制失败：清理可能残留的半成品文件，避免空目录假象
            try:
                if os.path.exists(stored):
                    os.remove(stored)
                if os.path.isdir(folder) and not os.listdir(folder):
                    os.rmdir(folder)
            except OSError:
                pass
            raise OSError(f"附件复制失败（{file_name}）: {e}") from e
        size = os.path.getsize(stored)
        try:
            cur = self.conn.execute(
                "INSERT INTO attachments(todo_id, file_name, stored_path, file_size, summary, created_at)"
                " VALUES(?,?,?,?,?,?)",
                (todo_id, file_name, stored, size, summary, now_str()),
            )
            self.conn.commit()
        except Exception:
            # 入库失败：删除已复制的文件，保持一致性
            try:
                if os.path.isfile(stored):
                    os.remove(stored)
            except OSError:
                pass
            raise
        return Attachment(id=cur.lastrowid, todo_id=todo_id, file_name=file_name,
                          stored_path=stored, file_size=size, summary=summary,
                          created_at=now_str())

    def delete_attachment(self, attach_id: int) -> None:
        """删除附件记录，并删除磁盘上的副本文件（及空目录）。"""
        row = self.conn.execute(
            "SELECT todo_id, stored_path FROM attachments WHERE id=?", (attach_id,)
        ).fetchone()
        folder = None
        if row:
            folder = os.path.dirname(row["stored_path"])
            if os.path.isfile(row["stored_path"]):
                try:
                    os.remove(row["stored_path"])
                except OSError:
                    pass
        self.conn.execute("DELETE FROM attachments WHERE id=?", (attach_id,))
        self.conn.commit()
        # 清理空目录
        if folder and os.path.isdir(folder):
            try:
                if not os.listdir(folder):
                    os.rmdir(folder)
            except OSError:
                pass

    def set_attachment_summary(self, attach_id: int, summary: str) -> None:
        self.conn.execute(
            "UPDATE attachments SET summary=? WHERE id=?", (summary, attach_id)
        )
        self.conn.commit()

    def delete_todo_attachments(self, todo_id: int) -> None:
        """彻底删除待办时清理其全部附件（记录 + 磁盘文件 + 目录）。"""
        for a in self.list_attachments(todo_id):
            if os.path.isfile(a.stored_path):
                try:
                    os.remove(a.stored_path)
                except OSError:
                    pass
        self.conn.execute("DELETE FROM attachments WHERE todo_id=?", (todo_id,))
        self.conn.commit()
        folder = os.path.join(attach_dir_for(self.path), str(todo_id))
        try:
            if os.path.isdir(folder) and not os.listdir(folder):
                os.rmdir(folder)
        except OSError:
            pass

    # ---------- 回收站 ----------
    def list_deleted_todos(self) -> List[Todo]:
        """回收站：已软删除的待办。"""
        rows = self.conn.execute(
            "SELECT * FROM todos WHERE deleted=1 ORDER BY updated_at DESC"
        ).fetchall()
        return [Todo(**dict(r)) for r in rows]

    def restore_todo(self, todo_id: int) -> None:
        self.conn.execute(
            "UPDATE todos SET deleted=0, updated_at=? WHERE id=?", (now_str(), todo_id)
        )
        self.conn.commit()

    def purge_todo(self, todo_id: int) -> None:
        """彻底删除单条（含附件文件）。"""
        self.delete_todo_attachments(todo_id)
        self.conn.execute("DELETE FROM todos WHERE id=?", (todo_id,))
        self.conn.commit()

    def purge_all_deleted(self) -> None:
        """清空回收站（含附件文件）。"""
        for t in self.list_deleted_todos():
            self.delete_todo_attachments(t.id)
        self.conn.execute("DELETE FROM todos WHERE deleted=1")
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()


def backup_database(keep: int = 7):
    """每天首次启动时备份数据库到 data/backup/，保留最近 keep 份。"""
    if not os.path.exists(DB_PATH):
        return None
    backup_dir = os.path.join(os.path.dirname(DB_PATH), "backup")
    os.makedirs(backup_dir, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    target = os.path.join(backup_dir, f"kanban-{today}.db")
    if os.path.exists(target):
        return None  # 今天已备份
    shutil.copy2(DB_PATH, target)
    backups = sorted(glob.glob(os.path.join(backup_dir, "kanban-*.db")))
    while len(backups) > keep:
        os.remove(backups.pop(0))
    return target
