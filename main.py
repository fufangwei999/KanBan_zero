"""Zero看板 入口。"""
import ctypes
import os
import sys

from PySide6.QtGui import QColor, QIcon, QPalette
from PySide6.QtWidgets import QApplication

from app.database import backup_database
from app.ui.main_window import MainWindow

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
ICON_PATH = os.path.join(PROJECT_DIR, "assets", "icon.ico")

APP_QSS = """
QWidget { color: #1f2937; font-family: "Microsoft YaHei", "Segoe UI", sans-serif; font-size: 13px; }
QMainWindow, QWidget#qt_scrollarea_viewport { background: #eef1f5; }

QLabel { color: #1f2937; }

QFrame#toolbar {
    background: #ffffff;
    border-bottom: 1px solid #e3e6ea;
}
QLabel#appTitle { font-size: 18px; font-weight: 700; color: #1f2937; }

QPushButton {
    background: #ffffff;
    border: 1px solid #d7dce3;
    border-radius: 6px;
    padding: 6px 14px;
    color: #1f2937;
}
QPushButton:hover { background: #f5f7fa; border-color: #b9c2cf; }
QPushButton:pressed { background: #e9edf2; }
QPushButton#primaryBtn {
    background: #4a90d9;
    border: none;
    color: #ffffff;
    font-weight: 600;
}
QPushButton#primaryBtn:hover { background: #3d7fc4; }
QPushButton#primaryBtn:pressed { background: #3570ae; }
QPushButton#doneBtn {
    background: #7ed321;
    border: none;
    color: #ffffff;
    padding: 4px 14px;
    border-radius: 5px;
    font-size: 12px;
    font-weight: 600;
}
QPushButton#doneBtn:hover { background: #6cc51c; }
QPushButton#doneBtn:pressed { background: #5fb315; }
QPushButton#startBtn {
    background: #4a90d9;
    border: none;
    color: #ffffff;
    padding: 4px 14px;
    border-radius: 5px;
    font-size: 12px;
    font-weight: 600;
}
QPushButton#startBtn:hover { background: #3d7fc4; }
QPushButton#startBtn:pressed { background: #3570ae; }
QPushButton#undoBtn {
    background: #e9edf2;
    border: none;
    color: #55606e;
    padding: 4px 14px;
    border-radius: 5px;
    font-size: 12px;
}
QPushButton#undoBtn:hover { background: #dde3ea; }
QPushButton#dateBtn {
    font-weight: 600;
    font-size: 14px;
    padding: 6px 16px;
    background: #f0f4ff;
    border: 1px solid #4a90d9;
    color: #4a90d9;
}
QPushButton#dateBtn:hover { background: #e3edfd; }

QLabel#statsBar {
    background: #ffffff;
    border-bottom: 1px solid #e3e6ea;
    padding: 8px 16px;
    color: #1f2937;
    font-size: 13px;
    font-weight: 600;
}

QScrollArea#boardArea { border: none; }

QListWidget#kanbanColumn { outline: none; }
QListWidget#kanbanColumn::item { border: none; }

QDialog { background: #ffffff; }
QMessageBox { background: #ffffff; }
QLineEdit, QTextEdit, QComboBox {
    border: 1px solid #d7dce3;
    border-radius: 6px;
    padding: 5px 8px;
    background: #ffffff;
    color: #1f2937;
}
QLineEdit:focus, QTextEdit:focus, QComboBox:focus { border-color: #4a90d9; }

QScrollBar:vertical { background: transparent; width: 8px; margin: 0; }
QScrollBar::handle:vertical { background: #c4ccd6; border-radius: 4px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #a8b2bf; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: transparent; height: 8px; margin: 0; }
QScrollBar::handle:horizontal { background: #c4ccd6; border-radius: 4px; min-width: 30px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

QListWidget { background: #ffffff; border: 1px solid #d7dce3; border-radius: 6px; color: #1f2937; }
"""


def apply_light_palette(app: QApplication) -> None:
    """强制浅色调色板，避免系统深色模式下文字变白。"""
    p = QPalette()
    p.setColor(QPalette.Window, QColor("#f4f6f9"))
    p.setColor(QPalette.WindowText, QColor("#1f2937"))
    p.setColor(QPalette.Base, QColor("#ffffff"))
    p.setColor(QPalette.AlternateBase, QColor("#f4f6f9"))
    p.setColor(QPalette.ToolTipBase, QColor("#ffffff"))
    p.setColor(QPalette.ToolTipText, QColor("#1f2937"))
    p.setColor(QPalette.Text, QColor("#1f2937"))
    p.setColor(QPalette.Button, QColor("#ffffff"))
    p.setColor(QPalette.ButtonText, QColor("#1f2937"))
    p.setColor(QPalette.BrightText, QColor("#e53935"))
    p.setColor(QPalette.Highlight, QColor("#4a90d9"))
    p.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    p.setColor(QPalette.Disabled, QPalette.WindowText, QColor("#b0b7c3"))
    p.setColor(QPalette.Disabled, QPalette.Text, QColor("#b0b7c3"))
    p.setColor(QPalette.Disabled, QPalette.ButtonText, QColor("#b0b7c3"))
    app.setPalette(p)


def main() -> None:
    # 启动时备份数据库（每天一份，保留最近 7 份）
    backup_database()

    # 让 Windows 任务栏用自定义图标分组（而非 python.exe 图标）
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("zero.kanban")
    except Exception:
        pass

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    apply_light_palette(app)
    app.setStyleSheet(APP_QSS)

    if os.path.exists(ICON_PATH):
        app.setWindowIcon(QIcon(ICON_PATH))

    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
