# -*- coding: utf-8 -*-
"""ChatGPT 风格主题。

集中放颜色与样式表，避免样式散落在界面代码里 —— 那样改一次配色要翻十几个文件。

设计要点（对着 ChatGPT 的暗色界面来）
-------------------------------------
· 几乎不用彩色：整屏是几个灰阶层次，颜色只留给"角色标记"这一处
· 靠层次分层，不靠边框：侧栏 #171717、主区 #212121、气泡与输入框 #303030
· 圆角大而克制：气泡 18px、输入框 26px、按钮 8px
· 没有粗边框、没有阴影、没有渐变
· 排版优先：正文比按钮重要，字号层次少而清晰
"""
from PySide6.QtGui import QColor

# ── 色板（ChatGPT 暗色）────────────────────────────────────────
SIDEBAR = "#171717"
MAIN = "#212121"
SURFACE = "#303030"
SURFACE_HOVER = "#2F2F2F"
SURFACE_ACTIVE = "#383838"
BORDER = "#3A3A3A"
BORDER_STRONG = "#4A4A4A"

TEXT = "#ECECEC"
TEXT_DIM = "#B4B4B4"
TEXT_FAINT = "#8E8E8E"

# ChatGPT 的"强调色"其实是白色：发送按钮是白圆黑箭头
ACCENT = "#FFFFFF"
ACCENT_TEXT = "#0D0D0D"
DANGER = "#F16A6A"
SUCCESS = "#5FBF8F"
WARN = "#D9A44A"

# 消息区
BUBBLE_USER = "#303030"
ROLE_NAME = "#B4B4B4"
TOOL_TEXT = "#8E8E8E"
SYS_TEXT = "#8E8E8E"

FONT_FAMILY = '"Microsoft YaHei UI", "Segoe UI", system-ui, sans-serif'
MONO_FAMILY = '"Cascadia Mono", "Consolas", monospace'

# 角色标记色：整屏唯一允许出现彩色的地方，但也要够灰、够克制
ROLE_COLORS = ["#7EA6F0", "#E0A36A", "#6FC79B", "#B79BE0",
               "#6FC0D8", "#E08A8A", "#D8C46F", "#E09BC4"]

CONTENT_MAX_WIDTH = 760


def qcolor(value: str) -> QColor:
    return QColor(value)


def app_stylesheet() -> str:
    return f"""
* {{
    font-family: {FONT_FAMILY};
    outline: none;
}}

QWidget#Root {{ background: {MAIN}; color: {TEXT}; }}
QWidget#Sidebar {{ background: {SIDEBAR}; }}
QWidget#Content {{ background: {MAIN}; }}

QLabel {{ color: {TEXT}; background: transparent; }}
QLabel[role="brand"] {{ font-size: 14px; font-weight: 600; }}
QLabel[role="role-name"] {{ font-size: 13px; font-weight: 600; }}
QLabel[role="body"] {{ color: {TEXT}; }}
QLabel[role="dim"] {{ font-size: 12.5px; color: {TEXT_DIM}; }}
QLabel[role="faint"] {{ font-size: 12px; color: {TEXT_FAINT}; }}
QLabel[role="section"] {{
    font-size: 11.5px; font-weight: 600; color: {TEXT_FAINT};
    padding: 10px 10px 4px 10px;
}}
QLabel[role="empty"] {{ font-size: 22px; font-weight: 600; color: {TEXT}; }}

/* ── 按钮：默认是"文字按钮"，几乎没有视觉重量 ── */
QPushButton {{
    background: transparent; color: {TEXT};
    border: none; border-radius: 8px;
    padding: 7px 10px; font-size: 13.5px;
}}
QPushButton:hover {{ background: {SURFACE_HOVER}; }}
QPushButton:pressed {{ background: {SURFACE_ACTIVE}; }}
QPushButton:disabled {{ color: {TEXT_FAINT}; background: transparent; }}

QPushButton[role="ghost"] {{
    text-align: left; padding: 9px 10px; border-radius: 9px; color: {TEXT_DIM};
}}
QPushButton[role="ghost"]:hover {{ background: {SURFACE_HOVER}; color: {TEXT}; }}

QPushButton[role="primary"] {{
    background: {ACCENT}; color: {ACCENT_TEXT}; font-weight: 600;
    padding: 9px 16px;
}}
QPushButton[role="primary"]:hover {{ background: #D9D9D9; }}
QPushButton[role="primary"]:disabled {{ background: {SURFACE}; color: {TEXT_FAINT}; }}

QPushButton[role="danger"] {{
    background: transparent; color: {DANGER};
    border: 1px solid {BORDER_STRONG};
}}
QPushButton[role="danger"]:hover {{ background: rgba(241,106,106,.12); }}
QPushButton[role="danger"]:disabled {{ color: {TEXT_FAINT}; border-color: {BORDER}; }}

/* 发送按钮：白圆 */
QPushButton#SendButton {{
    background: {ACCENT}; color: {ACCENT_TEXT};
    border: none; border-radius: 17px; font-size: 15px; font-weight: 700;
    min-width: 34px; max-width: 34px; min-height: 34px; max-height: 34px;
}}
QPushButton#SendButton:hover {{ background: #D9D9D9; }}
QPushButton#SendButton:disabled {{ background: {SURFACE_ACTIVE}; color: {TEXT_FAINT}; }}

/* 停止按钮：同尺寸的方块 */
QPushButton#StopButton {{
    background: {TEXT}; color: {ACCENT_TEXT};
    border: none; border-radius: 17px; font-size: 11px;
    min-width: 34px; max-width: 34px; min-height: 34px; max-height: 34px;
}}
QPushButton#StopButton:hover {{ background: #D9D9D9; }}

/* ── 输入 ── */
QLineEdit, QPlainTextEdit, QTextEdit {{
    background: transparent; color: {TEXT};
    border: none; padding: 0;
    font-size: 14.5px;
    selection-background-color: #4A4A4A;
}}

QComboBox {{
    background: transparent; color: {TEXT};
    border: 1px solid {BORDER}; border-radius: 8px;
    padding: 6px 10px; font-size: 13px; min-width: 80px;
}}
QComboBox:hover {{ border-color: {BORDER_STRONG}; }}
QComboBox::drop-down {{ border: none; width: 20px; }}
QComboBox::down-arrow {{
    image: none; width: 6px; height: 6px; margin-right: 8px;
    border-left: 1.5px solid {TEXT_DIM}; border-bottom: 1.5px solid {TEXT_DIM};
}}
QComboBox QAbstractItemView {{
    background: {SURFACE}; color: {TEXT};
    border: 1px solid {BORDER_STRONG}; border-radius: 10px;
    selection-background-color: {SURFACE_ACTIVE}; selection-color: {TEXT};
    padding: 4px; outline: none;
}}

QSpinBox {{
    background: {SURFACE}; color: {TEXT};
    border: 1px solid {BORDER}; border-radius: 8px;
    padding: 6px 8px; font-size: 13px;
}}

/* ── 侧栏列表 ── */
QListWidget {{
    background: transparent; color: {TEXT_DIM};
    border: none; outline: none; font-size: 13.5px;
}}
QListWidget::item {{
    padding: 9px 10px; border-radius: 9px; margin: 1px 6px; color: {TEXT_DIM};
}}
QListWidget::item:hover {{ background: {SURFACE_HOVER}; color: {TEXT}; }}
QListWidget::item:selected {{ background: {SURFACE_ACTIVE}; color: {TEXT}; }}

/* ── 滚动区 ── */
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{
    background: rgba(255,255,255,.14); border-radius: 5px; min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: rgba(255,255,255,.26); }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{
    background: rgba(255,255,255,.14); border-radius: 5px; min-width: 30px;
}}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ── 气泡 ── */
QFrame#UserBubble {{
    background: {BUBBLE_USER};
    border: none; border-radius: 18px;
}}
QFrame#Composer {{
    background: {SURFACE};
    border: 1px solid transparent; border-radius: 26px;
}}
QFrame#Composer[focused="true"] {{ border-color: {BORDER_STRONG}; }}

QFrame#Divider {{ background: {BORDER}; max-height: 1px; min-height: 1px; border: none; }}

/* ── 勾选框 ── */
QCheckBox {{ color: {TEXT}; spacing: 8px; font-size: 13.5px; }}
QCheckBox::indicator {{
    width: 16px; height: 16px; border-radius: 4px;
    border: 1px solid {BORDER_STRONG}; background: transparent;
}}
QCheckBox::indicator:hover {{ border-color: {TEXT_DIM}; }}
QCheckBox::indicator:checked {{ background: {TEXT}; border-color: {TEXT}; }}

/* ── 分组框 ── */
QGroupBox {{
    border: 1px solid {BORDER}; border-radius: 12px;
    margin-top: 14px; padding: 14px 14px 12px 14px;
    font-size: 13px; font-weight: 600; color: {TEXT_DIM};
}}
QGroupBox::title {{
    subcontrol-origin: margin; subcontrol-position: top left;
    left: 12px; padding: 0 6px; background: {MAIN};
}}

/* ── 对话框 ── */
QDialog {{ background: {MAIN}; color: {TEXT}; }}

/* ── 菜单 ── */
QMenu {{
    background: {SURFACE}; color: {TEXT};
    border: 1px solid {BORDER_STRONG}; border-radius: 10px; padding: 5px;
}}
QMenu::item {{ padding: 8px 22px 8px 14px; border-radius: 7px; font-size: 13.5px; }}
QMenu::item:selected {{ background: {SURFACE_ACTIVE}; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 4px 8px; }}

QToolTip {{
    background: {SURFACE}; color: {TEXT};
    border: 1px solid {BORDER_STRONG}; border-radius: 8px; padding: 6px 9px;
}}
"""
