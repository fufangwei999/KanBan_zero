"""各类对话框：待办编辑、分类编辑、AI 模型配置、报告展示。"""
import os
import threading
from datetime import date, datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from .. import ai as ai_module
from ..ai import PRESET_MODELS
from ..database import AiModel, Category, Todo

COLOR_PALETTE = [
    "#4A90D9", "#F5A623", "#7ED321", "#E53935",
    "#9B59B6", "#1ABC9C", "#E67E22", "#34495E",
]


# ---------------------------------------------------------------- 待办
def _fmt_size(n: int) -> str:
    """文件大小人类可读格式。"""
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.1f} MB"


class TodoDialog(QDialog):
    def __init__(self, categories, todo: Todo = None, prefill: dict = None, subtasks=None,
                 attachments=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("编辑待办" if todo else "添加待办")
        self.setMinimumWidth(460)
        self.categories = categories
        self.subtasks = [(s.title, s.done) for s in (subtasks or [])]
        # 附件：新增项 {"src_path":..., "file_name":..., "file_size":..., "summary":""}
        #       已有项 {"id":..., "file_name":..., "stored_path":..., "file_size":..., "summary":...}
        self.attachments = []
        for a in (attachments or []):
            self.attachments.append({
                "id": getattr(a, "id", None),
                "file_name": a.file_name,
                "stored_path": getattr(a, "stored_path", ""),
                "file_size": getattr(a, "file_size", 0),
                "summary": getattr(a, "summary", ""),
            })

        form = QFormLayout()
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("要做什么？")
        form.addRow("标题", self.title_edit)

        self.desc_edit = QTextEdit()
        self.desc_edit.setFixedHeight(72)
        self.desc_edit.setPlaceholderText("补充说明（可选）")
        form.addRow("描述", self.desc_edit)

        self.category_combo = QComboBox()
        for c in categories:
            self.category_combo.addItem(c.name, c.id)
        form.addRow("分类", self.category_combo)

        self.priority_combo = QComboBox()
        for key, label in [("high", "高"), ("medium", "中"), ("low", "低")]:
            self.priority_combo.addItem(label, key)
        self.priority_combo.setCurrentIndex(1)
        form.addRow("优先级", self.priority_combo)

        self.due_edit = QLineEdit()
        self.due_edit.setPlaceholderText("YYYY-MM-DD（非必填）")
        form.addRow("期望完成时间", self.due_edit)

        # 子任务 / 检查清单
        form.addRow("子任务", QLabel("勾选即完成，可拆解大任务"))
        self.subtask_list = QListWidget()
        self.subtask_list.setFixedHeight(110)
        self.subtask_list.itemChanged.connect(self._on_subtask_changed)
        form.addRow("", self.subtask_list)

        sub_row = QHBoxLayout()
        self.subtask_edit = QLineEdit()
        self.subtask_edit.setPlaceholderText("添加子任务，回车确认")
        self.subtask_edit.returnPressed.connect(self._add_subtask)
        add_sub_btn = QPushButton("＋ 添加")
        add_sub_btn.clicked.connect(self._add_subtask)
        del_sub_btn = QPushButton("删除选中")
        del_sub_btn.clicked.connect(self._del_subtask)
        sub_row.addWidget(self.subtask_edit, 1)
        sub_row.addWidget(add_sub_btn)
        sub_row.addWidget(del_sub_btn)
        form.addRow("", sub_row)
        self._refresh_subtasks()

        # 附件
        form.addRow("附件", QLabel("支持任意文件；docx/txt 配置 AI 后自动总结精髓"))
        self.attach_list = QListWidget()
        self.attach_list.setFixedHeight(96)
        self.attach_list.setSelectionMode(QListWidget.SingleSelection)
        form.addRow("", self.attach_list)
        attach_row = QHBoxLayout()
        add_attach_btn = QPushButton("＋ 添加附件")
        add_attach_btn.clicked.connect(self._add_attachment)
        dl_attach_btn = QPushButton("⬇ 下载")
        dl_attach_btn.clicked.connect(self._download_attachment)
        del_attach_btn = QPushButton("🗑 移除")
        del_attach_btn.clicked.connect(self._remove_attachment)
        attach_row.addWidget(add_attach_btn)
        attach_row.addWidget(dl_attach_btn)
        attach_row.addWidget(del_attach_btn)
        form.addRow("", attach_row)
        self._refresh_attachments()

        if todo:
            self.title_edit.setText(todo.title)
            self.desc_edit.setPlainText(todo.description)
            idx = self.category_combo.findData(todo.category_id)
            if idx >= 0:
                self.category_combo.setCurrentIndex(idx)
            pidx = self.priority_combo.findData(todo.priority)
            if pidx >= 0:
                self.priority_combo.setCurrentIndex(pidx)
            self.due_edit.setText(todo.due_date)
        elif prefill:
            self.title_edit.setText(prefill.get("title", ""))
            self.desc_edit.setPlainText(prefill.get("description", ""))
            idx = self.category_combo.findData(prefill.get("category_id"))
            if idx >= 0:
                self.category_combo.setCurrentIndex(idx)
            pidx = self.priority_combo.findData(prefill.get("priority", "medium"))
            if pidx >= 0:
                self.priority_combo.setCurrentIndex(pidx)
            self.due_edit.setText(prefill.get("due_date", ""))

        buttons = QDialogButtonBox()
        ok = buttons.addButton("确定", QDialogButtonBox.AcceptRole)
        cancel = buttons.addButton("取消", QDialogButtonBox.RejectRole)
        ok.setDefault(True)
        ok.clicked.connect(self._on_ok)
        cancel.clicked.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _on_ok(self) -> None:
        if not self.title_edit.text().strip():
            QMessageBox.warning(self, "提示", "标题不能为空")
            return
        if self.due_edit.text().strip():
            try:
                datetime.strptime(self.due_edit.text().strip(), "%Y-%m-%d")
            except ValueError:
                QMessageBox.warning(self, "提示", "日期格式应为 YYYY-MM-DD")
                return
        self.accept()

    def data(self) -> dict:
        return {
            "title": self.title_edit.text().strip(),
            "description": self.desc_edit.toPlainText().strip(),
            "category_id": self.category_combo.currentData(),
            "priority": self.priority_combo.currentData(),
            "due_date": self.due_edit.text().strip(),
            "subtasks": [(t, d) for t, d in self.subtasks],
            "attachments": list(self.attachments),
        }

    def _refresh_subtasks(self) -> None:
        self.subtask_list.blockSignals(True)
        self.subtask_list.clear()
        for title, done in self.subtasks:
            item = QListWidgetItem(title)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if done else Qt.Unchecked)
            self.subtask_list.addItem(item)
        self.subtask_list.blockSignals(False)

    def _add_subtask(self) -> None:
        title = self.subtask_edit.text().strip()
        if not title:
            return
        self.subtasks.append([title, False])
        self.subtask_edit.clear()
        self._refresh_subtasks()

    def _del_subtask(self) -> None:
        row = self.subtask_list.currentRow()
        if 0 <= row < len(self.subtasks):
            self.subtasks.pop(row)
            self._refresh_subtasks()

    def _on_subtask_changed(self, item) -> None:
        row = self.subtask_list.row(item)
        if 0 <= row < len(self.subtasks):
            self.subtasks[row][1] = (item.checkState() == Qt.Checked)

    # ---------- 附件 ----------
    def _refresh_attachments(self) -> None:
        self.attach_list.clear()
        for a in self.attachments:
            size = _fmt_size(a.get("file_size", 0))
            if a.get("summary"):
                label = f"📄 {a['file_name']}  ·  {size}  ·  ✨ {a['summary']}"
            else:
                ext = os.path.splitext(a["file_name"])[1].lower()
                if ext in (".docx", ".txt", ".md", ".markdown"):
                    label = f"📄 {a['file_name']}  ·  {size}  ·  ⏳ 待 AI 总结"
                else:
                    label = f"📄 {a['file_name']}  ·  {size}"
            item = QListWidgetItem(label)
            item.setToolTip(label)
            self.attach_list.addItem(item)

    def _add_attachment(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择附件", "", "所有文件 (*.*)"
        )
        for p in paths:
            self.attachments.append({
                "src_path": p,
                "file_name": os.path.basename(p),
                "file_size": os.path.getsize(p) if os.path.isfile(p) else 0,
                "summary": "",
            })
        self._refresh_attachments()

    def _download_attachment(self) -> None:
        row = self.attach_list.currentRow()
        if not (0 <= row < len(self.attachments)):
            QMessageBox.information(self, "提示", "请先选中一个附件")
            return
        a = self.attachments[row]
        if not a.get("stored_path") or not os.path.isfile(a["stored_path"]):
            QMessageBox.information(self, "提示", "该附件尚未保存（保存待办后即可下载）")
            return
        target, _ = QFileDialog.getSaveFileName(
            self, "下载附件", a["file_name"], "所有文件 (*.*)"
        )
        if target:
            try:
                import shutil
                shutil.copy2(a["stored_path"], target)
                QMessageBox.information(self, "下载完成", f"已保存到：\n{target}")
            except OSError as e:
                QMessageBox.warning(self, "下载失败", str(e))

    def _remove_attachment(self) -> None:
        row = self.attach_list.currentRow()
        if 0 <= row < len(self.attachments):
            self.attachments.pop(row)
            self._refresh_attachments()


# ---------------------------------------------------------------- 分类
class CategoryDialog(QDialog):
    def __init__(self, category: Category = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("编辑分类" if category else "添加分类")
        self.setMinimumWidth(360)
        self.color = category.color if category else COLOR_PALETTE[0]

        form = QFormLayout()
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("分类名称，如：待办 / 进行中 / 已完成")
        form.addRow("名称", self.name_edit)
        if category:
            self.name_edit.setText(category.name)

        # 颜色选择
        color_row = QHBoxLayout()
        self._color_buttons = []
        for c in COLOR_PALETTE:
            btn = QPushButton()
            btn.setFixedSize(26, 26)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(
                f"background:{c};border-radius:13px;border:2px solid "
                + ("#1f2937" if c == self.color else "transparent")
                + ";"
            )
            btn.clicked.connect(lambda _=False, col=c: self._pick_color(col))
            self._color_buttons.append((btn, c))
            color_row.addWidget(btn)
        custom_btn = QPushButton("自定义")
        custom_btn.clicked.connect(self._pick_custom)
        color_row.addWidget(custom_btn)
        color_row.addStretch(1)
        form.addRow("颜色", color_row)

        buttons = QDialogButtonBox()
        ok = buttons.addButton("确定", QDialogButtonBox.AcceptRole)
        cancel = buttons.addButton("取消", QDialogButtonBox.RejectRole)
        ok.setDefault(True)
        ok.clicked.connect(self._on_ok)
        cancel.clicked.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _refresh_color_buttons(self) -> None:
        for btn, c in self._color_buttons:
            btn.setStyleSheet(
                f"background:{c};border-radius:13px;border:2px solid "
                + ("#1f2937" if c == self.color else "transparent")
                + ";"
            )

    def _pick_color(self, color: str) -> None:
        self.color = color
        self._refresh_color_buttons()

    def _pick_custom(self) -> None:
        color = QColorDialog.getColor(parent=self)
        if color.isValid():
            self.color = color.name()
            self._refresh_color_buttons()

    def _on_ok(self) -> None:
        if not self.name_edit.text().strip():
            QMessageBox.warning(self, "提示", "分类名称不能为空")
            return
        self.accept()

    def data(self) -> dict:
        return {"name": self.name_edit.text().strip(), "color": self.color}


# ---------------------------------------------------------------- AI 模型
class AiModelDialog(QDialog):
    def __init__(self, model_cfg: AiModel = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("编辑 AI 模型" if model_cfg else "添加 AI 模型")
        self.setMinimumWidth(480)

        form = QFormLayout()

        self.preset_combo = QComboBox()
        self.preset_combo.addItem("自定义", None)
        for p in PRESET_MODELS:
            self.preset_combo.addItem(p["name"], p)
        self.preset_combo.currentIndexChanged.connect(self._on_preset)
        form.addRow("预设服务", self.preset_combo)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("显示名称，如 DeepSeek / 我的模型")
        form.addRow("名称", self.name_edit)

        self.base_edit = QLineEdit()
        self.base_edit.setPlaceholderText("https://api.deepseek.com/v1")
        form.addRow("Base URL", self.base_edit)

        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.Password)
        self.key_edit.setPlaceholderText("sk-...（本地 Ollama 可随意填）")
        form.addRow("API Key", self.key_edit)

        self.model_edit = QLineEdit()
        self.model_edit.setPlaceholderText("模型名，如 deepseek-chat / gpt-4o-mini / qwen3:8b")
        form.addRow("模型名", self.model_edit)

        hint = QLabel("💡 任意 OpenAI 兼容接口都可用：DeepSeek、OpenAI、通义、本地 Ollama 等。")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#8a94a6;font-size:12px;")
        form.addRow("", hint)

        if model_cfg:
            self.name_edit.setText(model_cfg.name)
            self.base_edit.setText(model_cfg.base_url)
            self.key_edit.setText(model_cfg.api_key)
            self.model_edit.setText(model_cfg.model)

        buttons = QDialogButtonBox()
        ok = buttons.addButton("确定", QDialogButtonBox.AcceptRole)
        cancel = buttons.addButton("取消", QDialogButtonBox.RejectRole)
        ok.setDefault(True)
        ok.clicked.connect(self._on_ok)
        cancel.clicked.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _on_preset(self, _idx: int) -> None:
        preset = self.preset_combo.currentData()
        if not preset:
            return
        self.name_edit.setText(preset["name"])
        self.base_edit.setText(preset["base_url"])
        self.model_edit.setText(preset["model"])
        if preset["name"] == "本地 Ollama":
            self.key_edit.setText("ollama")

    def _on_ok(self) -> None:
        if not self.name_edit.text().strip():
            QMessageBox.warning(self, "提示", "名称不能为空")
            return
        if not self.base_edit.text().strip():
            QMessageBox.warning(self, "提示", "Base URL 不能为空")
            return
        if not self.model_edit.text().strip():
            QMessageBox.warning(self, "提示", "模型名不能为空")
            return
        self.accept()

    def data(self) -> dict:
        return {
            "name": self.name_edit.text().strip(),
            "base_url": self.base_edit.text().strip(),
            "api_key": self.key_edit.text().strip(),
            "model": self.model_edit.text().strip(),
        }


# ---------------------------------------------------------------- 报告
class ReportDialog(QDialog):
    ai_finished = Signal(str)
    ai_failed = Signal(str)

    def __init__(self, title: str, report_text: str, summarize_fn=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(640, 640)
        self.summarize_fn = summarize_fn

        layout = QVBoxLayout(self)

        self.title_lbl = QLabel(title)
        self.title_lbl.setStyleSheet("font-size:16px;font-weight:600;")
        layout.addWidget(self.title_lbl)

        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setPlainText(report_text)
        layout.addWidget(self.text_edit, 1)

        btn_row = QHBoxLayout()
        self.ai_btn = QPushButton("✨ AI 智能总结")
        self.ai_btn.setToolTip("选择一个已配置的 AI 模型，生成智能总结")
        self.copy_btn = QPushButton("复制全文")
        self.export_btn = QPushButton("导出 Markdown")
        self.close_btn = QPushButton("关闭")
        self.ai_btn.clicked.connect(self._run_ai)
        self.copy_btn.clicked.connect(self._copy)
        self.export_btn.clicked.connect(self._export)
        self.close_btn.clicked.connect(self.accept)
        btn_row.addWidget(self.ai_btn)
        btn_row.addWidget(self.copy_btn)
        btn_row.addWidget(self.export_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(self.close_btn)
        layout.addLayout(btn_row)

        self.ai_finished.connect(self._show_ai_result)
        self.ai_failed.connect(self._show_ai_error)
        if summarize_fn is None:
            self.ai_btn.setEnabled(False)
            self.ai_btn.setToolTip("尚未配置 AI 模型，请先在「AI 模型」里添加")

    def _run_ai(self) -> None:
        if self.summarize_fn is None:
            return
        # 先在主线程调用 summarize_fn，它返回一个后台任务闭包（期间可能弹模型选择框）
        try:
            task = self.summarize_fn()
        except Exception as e:  # noqa: BLE001
            self._show_ai_error(str(e))
            return
        if task is None:  # 用户取消选择
            return
        self.ai_btn.setEnabled(False)
        self.ai_btn.setText("AI 生成中…")

        def worker():
            try:
                result = task()
                self.ai_finished.emit(result)
            except Exception as e:  # noqa: BLE001
                self.ai_failed.emit(str(e))

        threading.Thread(target=worker, daemon=True).start()

    def _show_ai_result(self, text: str) -> None:
        self.ai_btn.setEnabled(True)
        self.ai_btn.setText("✨ AI 智能总结")
        self.text_edit.append("\n\n" + "=" * 40 + "\n🤖 AI 智能总结\n" + "=" * 40 + "\n")
        self.text_edit.append(text)

    def _show_ai_error(self, msg: str) -> None:
        self.ai_btn.setEnabled(True)
        self.ai_btn.setText("✨ AI 智能总结")
        QMessageBox.warning(self, "AI 生成失败", msg)

    def _copy(self) -> None:
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(self.text_edit.toPlainText())

    def _export(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getSaveFileName(self, "导出报告", f"报告_{datetime.now():%Y%m%d}.md", "Markdown (*.md)")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.text_edit.toPlainText())
            QMessageBox.information(self, "导出成功", f"已保存到：\n{path}")


# ---------------------------------------------------------------- 智能添加
class SmartAddDialog(QDialog):
    parse_finished = Signal(dict)
    parse_failed = Signal(str)

    def __init__(self, models, categories, parent=None):
        super().__init__(parent)
        self.models = models
        self.categories = categories
        self.result = None
        self.setWindowTitle("✨ 智能添加待办")
        self.setMinimumWidth(500)

        layout = QVBoxLayout(self)

        hint = QLabel(
            "用一句话描述任务，AI 自动解析标题、优先级、分类和期望完成时间。\n"
            "例如：明天下午交周报，高优先级"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#666;font-size:12px;")
        layout.addWidget(hint)

        self.input_edit = QTextEdit()
        self.input_edit.setPlaceholderText("例如：明天下午交周报，高优先级")
        self.input_edit.setFixedHeight(88)
        layout.addWidget(self.input_edit)

        if len(models) > 1:
            row = QHBoxLayout()
            row.addWidget(QLabel("模型："))
            self.model_combo = QComboBox()
            for m in models:
                self.model_combo.addItem(m.name, m)
            row.addWidget(self.model_combo, 1)
            layout.addLayout(row)
        else:
            self.model_combo = None

        self.status_lbl = QLabel("")
        self.status_lbl.setWordWrap(True)
        layout.addWidget(self.status_lbl)

        btn_row = QHBoxLayout()
        self.parse_btn = QPushButton("✨ AI 解析")
        cancel_btn = QPushButton("取消")
        self.parse_btn.clicked.connect(self._parse)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(self.parse_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

        self.parse_finished.connect(self._on_finished)
        self.parse_failed.connect(self._on_failed)

    def _parse(self) -> None:
        text = self.input_edit.toPlainText().strip()
        if not text:
            QMessageBox.warning(self, "提示", "请先输入任务描述")
            return
        if not self.models:
            QMessageBox.warning(self, "提示", "尚未配置 AI 模型")
            return
        model = self.models[0] if self.model_combo is None else self.model_combo.currentData()
        self.parse_btn.setEnabled(False)
        self.status_lbl.setText("AI 解析中…")
        today = date.today().isoformat()
        cats = self.categories

        def worker():
            try:
                result = ai_module.parse_natural_language_todo(model, text, cats, today)
                self.parse_finished.emit(result)
            except Exception as e:  # noqa: BLE001
                self.parse_failed.emit(str(e))

        threading.Thread(target=worker, daemon=True).start()

    def _on_finished(self, result: dict) -> None:
        self.result = result
        self.accept()

    def _on_failed(self, msg: str) -> None:
        self.parse_btn.setEnabled(True)
        self.status_lbl.setText("")
        QMessageBox.warning(self, "解析失败", msg)
