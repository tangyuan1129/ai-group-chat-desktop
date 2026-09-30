# -*- coding: utf-8 -*-
"""深色玻璃质感主题（仿 DSH 的 macOS 风格）。

集中放颜色与样式表，避免样式散落在界面代码里 —— 那样改一次配色要翻十几个文件。

设计语言
--------
深蓝底 + 极淡的白色叠加层做"玻璃"面板，靠 1px 的半透明描边分层，
强调色统一用 #5B8CFF。圆角偏大（8~12px），整体偏紧凑。
"""
from PySide6.QtGui import QColor

# ── 色板 ───────────────────────────────────────────────────────
BG_TOP = "#0B1220"
BG_BOTTOM = "#131C33"
SURFACE = "rgba(255, 255, 255, 0.035)"
SURFACE_HOVER = "rgba(255, 255, 255, 0.07)"
SURFACE_ACTIVE = "rgba(91, 140, 255, 0.16)"
BORDER = "rgba(255, 255, 255, 0.09)"
BORDER_STRONG = "rgba(255, 255, 255, 0.16)"
ACCENT = "#5B8CFF"
ACCENT_HOVER = "#7BA4FF"
ACCENT_DIM = "rgba(91, 140, 255, 0.22)"
TEXT = "#E6ECFF"
TEXT_DIM = "#93A5D8"
TEXT_FAINT = "#6B7CA8"
DANGER = "#F87171"
SUCCESS = "#3DD68C"
WARN = "#FBBF24"

# 聊天区里各种元素的颜色
CHAT_BG = "rgba(0, 0, 0, 0.22)"
CHAT_USER = "#CFE0FF"
CHAT_BODY = "#DDE5F7"
CHAT_META = "#6B7CA8"
CHAT_TOOL = "#7E8DB5"
CHAT_SYS = "#8B9AC4"

ROLE_COLORS = ["#5B8CFF", "#FF9F45", "#3DD68C", "#C084FC",
               "#38BDF8", "#F87171", "#FBBF24", "#F472B6"]

FONT_FAMILY = '"Microsoft YaHei UI", "Segoe UI", system-ui, sans-serif'


def qcolor(value: str) -> QColor:
    return QColor(value)


# ── 全局样式表 ─────────────────────────────────────────────────
def app_stylesheet() -> str:
    return f"""
* {{
    font-family: {FONT_FAMILY};
    outline: none;
}}

QWidget#Root {{
    background: qlineargradient(x1:0, y1:0, x2:0.4, y2:1,
                stop:0 {BG_TOP}, stop:1 {BG_BOTTOM});
    color: {TEXT};
}}

QLabel {{
    color: {TEXT};
    background: transparent;
}}
QLabel[role="title"] {{
    font-size: 19px; font-weight: 700; letter-spacing: .3px;
}}
QLabel[role="subtitle"] {{
    font-size: 12px; color: {TEXT_DIM};
}}
QLabel[role="section"] {{
    font-size: 12px; font-weight: 600; color: {TEXT_DIM};
    letter-spacing: .6px;
}}
QLabel[role="hint"] {{
    font-size: 12px; color: {TEXT_FAINT};
}}
QLabel[role="status"] {{
    font-size: 12px; color: {TEXT_DIM};
}}

/* ── 玻璃面板 ── */
QFrame[panel="true"] {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 12px;
}}
QFrame[panel="flat"] {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 10px;
}}

/* ── 按钮 ── */
QPushButton {{
    background: {SURFACE};
    color: {TEXT};
    border: 1px solid {BORDER_STRONG};
    border-radius: 9px;
    padding: 8px 16px;
    font-size: 13px;
}}
QPushButton:hover {{ background: {SURFACE_HOVER}; border-color: {ACCENT}; }}
QPushButton:pressed {{ background: {ACCENT_DIM}; }}
QPushButton:disabled {{ color: {TEXT_FAINT}; border-color: {BORDER}; background: transparent; }}

QPushButton[role="primary"] {{
    background: {ACCENT}; color: #FFFFFF; border: none; font-weight: 600;
}}
QPushButton[role="primary"]:hover {{ background: {ACCENT_HOVER}; }}
QPushButton[role="primary"]:disabled {{ background: rgba(91,140,255,.28); color: rgba(255,255,255,.55); }}

QPushButton[role="danger"] {{
    background: rgba(248,113,113,.16); color: {DANGER};
    border: 1px solid rgba(248,113,113,.4); font-weight: 600;
}}
QPushButton[role="danger"]:hover {{ background: rgba(248,113,113,.28); }}
QPushButton[role="danger"]:disabled {{ background: transparent; color: {TEXT_FAINT}; border-color: {BORDER}; }}

QPushButton[role="icon"] {{
    padding: 6px 10px; border-radius: 8px; color: {TEXT_DIM};
    border: 1px solid transparent; background: transparent;
}}
QPushButton[role="icon"]:hover {{ background: {SURFACE_HOVER}; color: {TEXT}; }}
QPushButton[role="icon"]:checked {{ background: {ACCENT_DIM}; color: {TEXT}; }}

/* ── 输入 ── */
QLineEdit, QPlainTextEdit, QTextEdit {{
    background: rgba(0, 0, 0, 0.25);
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 9px;
    padding: 8px 11px;
    font-size: 13px;
    selection-background-color: {ACCENT};
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {{ border-color: {ACCENT}; }}
QLineEdit::placeholder {{ color: {TEXT_FAINT}; }}

/* ── 下拉框 ── */
QComboBox {{
    background: rgba(0, 0, 0, 0.25);
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 9px;
    padding: 7px 10px;
    font-size: 13px;
    min-width: 90px;
}}
QComboBox:hover {{ border-color: {BORDER_STRONG}; }}
QComboBox:focus {{ border-color: {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox::down-arrow {{
    image: none; width: 7px; height: 7px; margin-right: 8px;
    border-left: 1.5px solid {TEXT_DIM}; border-bottom: 1.5px solid {TEXT_DIM};
}}
QComboBox QAbstractItemView {{
    background: {BG_BOTTOM}; color: {TEXT};
    border: 1px solid {BORDER_STRONG}; border-radius: 8px;
    selection-background-color: {ACCENT_DIM}; selection-color: {TEXT};
    padding: 4px; outline: none;
}}

/* ── 列表 / 表格 ── */
QListWidget, QTableWidget, QTreeWidget {{
    background: rgba(0, 0, 0, 0.18);
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 10px;
    font-size: 13px;
    outline: none;
}}
QListWidget::item {{ padding: 7px 9px; border-radius: 7px; margin: 1px 3px; }}
QListWidget::item:hover {{ background: {SURFACE_HOVER}; }}
QListWidget::item:selected {{ background: {ACCENT_DIM}; color: {TEXT}; }}

QHeaderView::section {{
    background: rgba(0, 0, 0, 0.3); color: {TEXT_DIM};
    border: none; border-bottom: 1px solid {BORDER};
    padding: 6px 8px; font-size: 12px; font-weight: 600;
}}
QTableWidget {{ gridline-color: {BORDER}; }}
QTableWidget::item {{ padding: 4px 6px; }}
QTableWidget::item:selected {{ background: {ACCENT_DIM}; color: {TEXT}; }}

/* ── 滚动条 ── */
QScrollBar:vertical {{ background: transparent; width: 9px; margin: 2px; }}
QScrollBar::handle:vertical {{
    background: rgba(255,255,255,.16); border-radius: 4px; min-height: 28px;
}}
QScrollBar::handle:vertical:hover {{ background: rgba(255,255,255,.3); }}
QScrollBar:horizontal {{ background: transparent; height: 9px; margin: 2px; }}
QScrollBar::handle:horizontal {{
    background: rgba(255,255,255,.16); border-radius: 4px; min-width: 28px;
}}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ── 聊天区 ── */
QTextBrowser#Chat {{
    background: {CHAT_BG};
    border: 1px solid {BORDER};
    border-radius: 12px;
    padding: 10px 12px;
    font-size: 13.5px;
}}

/* ── 勾选框 ── */
QCheckBox {{ color: {TEXT}; spacing: 7px; font-size: 13px; }}
QCheckBox::indicator {{
    width: 15px; height: 15px; border-radius: 5px;
    border: 1px solid {BORDER_STRONG}; background: rgba(0,0,0,.25);
}}
QCheckBox::indicator:hover {{ border-color: {ACCENT}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}

/* ── 分组框 ── */
QGroupBox {{
    border: 1px solid {BORDER};
    border-radius: 11px;
    margin-top: 14px;
    padding: 12px 12px 10px 12px;
    font-size: 12.5px; font-weight: 600; color: {TEXT_DIM};
}}
QGroupBox::title {{
    subcontrol-origin: margin; subcontrol-position: top left;
    left: 12px; padding: 0 6px; background: transparent;
}}

/* ── 对话框 ── */
QDialog {{ background: {BG_BOTTOM}; color: {TEXT}; }}

/* ── 菜单 ── */
QMenu {{
    background: {BG_BOTTOM}; color: {TEXT};
    border: 1px solid {BORDER_STRONG}; border-radius: 10px; padding: 5px;
}}
QMenu::item {{ padding: 7px 20px 7px 14px; border-radius: 7px; font-size: 13px; }}
QMenu::item:selected {{ background: {ACCENT_DIM}; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 4px 8px; }}

/* ── 提示条 ── */
QFrame[banner="warn"] {{
    background: rgba(251,191,36,.12);
    border: 1px solid rgba(251,191,36,.35);
    border-radius: 10px;
}}
QFrame[banner="info"] {{
    background: {ACCENT_DIM};
    border: 1px solid rgba(91,140,255,.35);
    border-radius: 10px;
}}

QToolTip {{
    background: {BG_BOTTOM}; color: {TEXT};
    border: 1px solid {BORDER_STRONG}; border-radius: 7px; padding: 5px 8px;
}}
"""
