# -*- coding: utf-8 -*-
"""ChatGPT 桌面版风格主题。

对着 ChatGPT 桌面版的实际界面调过：
· 整屏近纯黑（#0D0D0D），层次靠"比背景略亮一点的面板"分，不靠边框
· 左侧是一条窄图标栏，和主区同色 —— 靠"选中项有个圆角亮块"来指示，不是靠色差
· 输入框是一大块圆角面板（#212121），比背景亮一档，是画面里最大的实体
· 几乎没有彩色：颜色只出现在角色标记和"完全访问"这类状态提示上
· 圆角大而克制：输入框 26px、按钮 10px、选中块 12px
"""
from PySide6.QtGui import QColor

# ── 色板（对着 ChatGPT 桌面版取）────────────────────────────────
MAIN = "#0D0D0D"          # 主区背景：近纯黑
RAIL = "#0D0D0D"          # 图标栏：和主区同色
SURFACE = "#212121"       # 输入框等实体面板
SURFACE_HOVER = "#2A2A2A"
SURFACE_ACTIVE = "#303030"
BORDER = "#2A2A2A"
BORDER_STRONG = "#3A3A3A"

TEXT = "#ECECEC"
TEXT_DIM = "#B4B4B4"
TEXT_FAINT = "#8E8E8E"
TEXT_DISABLED = "#5A5A5A"

ACCENT = "#FFFFFF"        # ChatGPT 的"强调色"其实是白色
ACCENT_TEXT = "#0D0D0D"
DANGER = "#F16A6A"
SUCCESS = "#5FBF8F"
WARN = "#E0A030"

BUBBLE_USER = "#2A2A2A"
TOOL_TEXT = "#8E8E8E"
SYS_TEXT = "#8E8E8E"

FONT_FAMILY = '"Microsoft YaHei UI", "Segoe UI", system-ui, sans-serif'

RAIL_WIDTH = 76
CONTENT_MAX_WIDTH = 1100     # 输入框宽度上限，对齐 ChatGPT 那个大输入框
CHAT_MAX_WIDTH = 820         # 消息列窄一些，读起来更舒服

# 角色标记色：整屏唯一允许出现彩色的地方，压得比较灰
ROLE_COLORS = ["#7EA6F0", "#E0A36A", "#6FC79B", "#B79BE0",
               "#6FC0D8", "#E08A8A", "#D8C46F", "#E09BC4"]


def qcolor(value: str) -> QColor:
    return QColor(value)


def app_stylesheet() -> str:
    return f"""
* {{
    font-family: {FONT_FAMILY};
    outline: none;
}}

QWidget#Root {{ background: {MAIN}; color: {TEXT}; }}
QWidget#Rail {{ background: {RAIL}; }}
QWidget#Content {{ background: {MAIN}; }}

QLabel {{ color: {TEXT}; background: transparent; }}
QLabel[role="heading"] {{ font-size: 21pt; font-weight: 600; color: {TEXT}; }}
QLabel[role="title"] {{ font-size: 10pt; font-weight: 600; }}
QLabel[role="body"] {{ color: {TEXT}; }}
QLabel[role="role-name"] {{ font-size: 9.5pt; font-weight: 600; }}
QLabel[role="dim"] {{ font-size: 9pt; color: {TEXT_DIM}; }}
QLabel[role="faint"] {{ font-size: 8.5pt; color: {TEXT_FAINT}; }}
QLabel[role="section"] {{
    font-size: 8pt; font-weight: 600; color: {TEXT_FAINT};
    padding: 10px 12px 4px 12px;
}}

/* ── 按钮 ── */
QPushButton {{
    background: transparent; color: {TEXT};
    border: none; border-radius: 10px;
    padding: 7px 12px; font-size: 9.5pt;
}}
QPushButton:hover {{ background: {SURFACE_HOVER}; }}
QPushButton:pressed {{ background: {SURFACE_ACTIVE}; }}
QPushButton:disabled {{ color: {TEXT_DISABLED}; background: transparent; }}

/* 图标栏按钮：正方形、圆角，选中时有个亮块 */
QPushButton#RailButton {{
    background: transparent; border: none; border-radius: 12px;
    min-width: 44px; max-width: 44px; min-height: 44px; max-height: 44px;
    padding: 0;
}}
QPushButton#RailButton:hover {{ background: {SURFACE_HOVER}; }}
QPushButton#RailButton:checked {{ background: {SURFACE_ACTIVE}; }}

QPushButton[role="primary"] {{
    background: {ACCENT}; color: {ACCENT_TEXT}; font-weight: 600;
    padding: 9px 18px;
}}
QPushButton[role="primary"]:hover {{ background: #D9D9D9; }}
QPushButton[role="primary"]:disabled {{ background: {SURFACE_ACTIVE}; color: {TEXT_DISABLED}; }}

QPushButton[role="danger"] {{
    background: transparent; color: {DANGER};
    border: 1px solid {BORDER_STRONG};
}}
QPushButton[role="danger"]:hover {{ background: rgba(241,106,106,.12); }}
QPushButton[role="danger"]:disabled {{ color: {TEXT_DISABLED}; border-color: {BORDER}; }}

/* 输入框里那个圆形发送/停止钮 */
QPushButton#SendButton {{
    background: {ACCENT}; border: none; border-radius: 19px; padding: 0;
    min-width: 38px; max-width: 38px; min-height: 38px; max-height: 38px;
}}
QPushButton#SendButton:hover {{ background: #D9D9D9; }}
QPushButton#SendButton:disabled {{ background: {SURFACE_ACTIVE}; }}

QPushButton#StopButton {{
    background: {TEXT}; border: none; border-radius: 19px; padding: 0;
    min-width: 38px; max-width: 38px; min-height: 38px; max-height: 38px;
}}
QPushButton#StopButton:hover {{ background: #D9D9D9; }}

/* 输入框下方那排小工具 */
QPushButton[role="tool"] {{
    background: transparent; color: {TEXT_DIM};
    border: none; border-radius: 9px;
    padding: 6px 10px; font-size: 9pt;
}}
QPushButton[role="tool"]:hover {{ background: {SURFACE_HOVER}; color: {TEXT}; }}

/* ── 输入 ── */
QLineEdit, QPlainTextEdit, QTextEdit {{
    background: transparent; color: {TEXT};
    border: none; padding: 0; font-size: 10.5pt;
    selection-background-color: #4A4A4A;
}}

QComboBox {{
    background: transparent; color: {TEXT};
    border: 1px solid {BORDER}; border-radius: 9px;
    padding: 6px 10px; font-size: 9pt; min-width: 80px;
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
    border: 1px solid {BORDER}; border-radius: 9px;
    padding: 6px 8px; font-size: 9pt;
}}

/* ── 列表 ── */
QListWidget {{
    background: transparent; color: {TEXT_DIM};
    border: none; outline: none; font-size: 9.5pt;
}}
QListWidget::item {{
    padding: 9px 12px; border-radius: 10px; margin: 1px 8px; color: {TEXT_DIM};
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

/* ── 面板 ── */
QFrame#UserBubble {{ background: {BUBBLE_USER}; border: none; border-radius: 18px; }}
QFrame#Composer {{ background: {SURFACE}; border: 1px solid transparent; border-radius: 26px; }}
QFrame#Composer[focused="true"] {{ border-color: {BORDER_STRONG}; }}
QFrame#ToolRow {{ background: {SURFACE}; border: 1px solid transparent; border-radius: 18px; }}

/* ── 勾选框 ── */
QCheckBox {{ color: {TEXT}; spacing: 8px; font-size: 9.5pt; }}
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
    font-size: 9.5pt; font-weight: 600; color: {TEXT_DIM};
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
    border: 1px solid {BORDER_STRONG}; border-radius: 12px; padding: 5px;
}}
QMenu::item {{ padding: 8px 24px 8px 14px; border-radius: 8px; font-size: 9.5pt; }}
QMenu::item:selected {{ background: {SURFACE_ACTIVE}; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 4px 8px; }}

QToolTip {{
    background: {SURFACE}; color: {TEXT};
    border: 1px solid {BORDER_STRONG}; border-radius: 8px; padding: 6px 9px;
}}
"""
