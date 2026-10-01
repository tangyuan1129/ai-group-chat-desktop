# -*- coding: utf-8 -*-
"""ChatGPT 桌面版风格主题 + 设计系统。

为什么要先立尺度
----------------
之前字号用了 8/8.5/9/9.5/10/10.5/12/26 八个档次，间距用了十几种零散数值 ——
那不是设计，是随手写的。界面显得"业余"的根子就在这：**没有体系**。
专业界面靠的是克制的、成体系的尺度，所以这里先把三套尺度定死，
所有样式只能从里面取值。

尺度
----
间距（8pt 栅格）  SPACE_XS 4 / SM 8 / MD 12 / LG 16 / XL 24 / XXL 32
字号（6 档）      FONT_CAPTION 8 / SMALL 9.5 / BODY 11 / TITLE 13 / HEADING 20 / DISPLAY 28
圆角（4 档）      RADIUS_SM 8 / MD 12 / LG 18 / XL 26

配色
----
· 整屏近纯黑（#0D0D0D），层次靠"比背景略亮的面板"分，不靠边框
· 左侧窄图标栏和主区同色，靠"选中项有个圆角亮块"指示
· 输入框是画面里最大的实体，比背景亮一档
· 几乎没有彩色：颜色只留给角色标记
"""
from PySide6.QtGui import QColor

# ── 间距（8pt 栅格）──────────────────────────────────────────
SPACE_XS = 4
SPACE_SM = 8
SPACE_MD = 12
SPACE_LG = 16
SPACE_XL = 24
SPACE_XXL = 32

# ── 字号（pt）───────────────────────────────────────────────
FONT_CAPTION = 8      # 极次要：分组标题
FONT_SMALL = 9.5      # 次要：说明文字、按钮
FONT_BODY = 11        # 正文、输入
FONT_TITLE = 13       # 小标题
FONT_HEADING = 20     # 面板标题
FONT_DISPLAY = 28     # 空状态大标题

# ── 圆角 ────────────────────────────────────────────────────
RADIUS_SM = 8
RADIUS_MD = 12
RADIUS_LG = 18
RADIUS_XL = 26

# ── 色板 ────────────────────────────────────────────────────
MAIN = "#0D0D0D"
RAIL = "#0D0D0D"
SURFACE = "#212121"
SURFACE_HOVER = "#2A2A2A"
SURFACE_ACTIVE = "#303030"
BORDER = "#2A2A2A"
BORDER_STRONG = "#3A3A3A"

TEXT = "#ECECEC"
TEXT_DIM = "#B4B4B4"
TEXT_FAINT = "#8E8E8E"
TEXT_DISABLED = "#5A5A5A"

ACCENT = "#FFFFFF"
ACCENT_TEXT = "#0D0D0D"
DANGER = "#F16A6A"
SUCCESS = "#5FBF8F"
WARN = "#E0A030"

BUBBLE_USER = "#2A2A2A"
TOOL_TEXT = "#8E8E8E"
SYS_TEXT = "#8E8E8E"

FONT_FAMILY = '"Microsoft YaHei UI", "Segoe UI", system-ui, sans-serif'

RAIL_WIDTH = 76
CONTENT_MAX_WIDTH = 1100
CHAT_MAX_WIDTH = 820

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

/* ── 文字层次：只用 FONT_* 这几档 ── */
QLabel {{ color: {TEXT}; background: transparent; }}
QLabel[role="display"] {{
    font-size: {FONT_DISPLAY}pt; font-weight: 500; color: {TEXT};
}}
QLabel[role="heading"] {{
    font-size: {FONT_HEADING}pt; font-weight: 600; color: {TEXT};
}}
QLabel[role="title"] {{
    font-size: {FONT_TITLE}pt; font-weight: 600; color: {TEXT};
}}
QLabel[role="body"] {{ font-size: {FONT_BODY}pt; color: {TEXT}; }}
QLabel[role="role-name"] {{
    font-size: {FONT_SMALL}pt; font-weight: 600; color: {TEXT};
}}
QLabel[role="dim"] {{ font-size: {FONT_SMALL}pt; color: {TEXT_DIM}; }}
QLabel[role="faint"] {{ font-size: {FONT_SMALL}pt; color: {TEXT_FAINT}; }}
QLabel[role="section"] {{
    font-size: {FONT_CAPTION}pt; font-weight: 600; color: {TEXT_FAINT};
    padding: {SPACE_LG}px {SPACE_MD}px {SPACE_XS}px {SPACE_MD}px;
}}

/* ── 按钮 ── */
QPushButton {{
    background: transparent; color: {TEXT};
    border: none; border-radius: {RADIUS_SM}px;
    padding: {SPACE_SM}px {SPACE_MD}px; font-size: {FONT_SMALL}pt;
}}
QPushButton:hover {{ background: {SURFACE_HOVER}; }}
QPushButton:pressed {{ background: {SURFACE_ACTIVE}; }}
QPushButton:disabled {{ color: {TEXT_DISABLED}; background: transparent; }}

QPushButton#RailButton {{
    background: transparent; border: none; border-radius: {RADIUS_MD}px;
    min-width: 44px; max-width: 44px; min-height: 44px; max-height: 44px;
    padding: 0;
}}
QPushButton#RailButton:hover {{ background: {SURFACE_HOVER}; }}
QPushButton#RailButton:checked {{ background: {SURFACE_ACTIVE}; }}

QPushButton[role="primary"] {{
    background: {ACCENT}; color: {ACCENT_TEXT}; font-weight: 600;
    padding: {SPACE_SM}px {SPACE_LG}px;
}}
QPushButton[role="primary"]:hover {{ background: #D9D9D9; }}
QPushButton[role="primary"]:disabled {{
    background: {SURFACE_ACTIVE}; color: {TEXT_DISABLED};
}}

QPushButton[role="danger"] {{
    background: transparent; color: {DANGER};
    border: 1px solid {BORDER_STRONG};
}}
QPushButton[role="danger"]:hover {{ background: rgba(241,106,106,.12); }}
QPushButton[role="danger"]:disabled {{ color: {TEXT_DISABLED}; border-color: {BORDER}; }}

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

QPushButton[role="tool"] {{
    background: transparent; color: {TEXT_DIM};
    border: none; border-radius: {RADIUS_SM}px;
    padding: {SPACE_XS}px {SPACE_SM}px; font-size: {FONT_SMALL}pt;
    text-align: left;
}}
QPushButton[role="tool"]:hover {{ background: {SURFACE_HOVER}; color: {TEXT}; }}

/* ── 输入 ── */
QLineEdit, QPlainTextEdit, QTextEdit {{
    background: transparent; color: {TEXT};
    border: none; padding: 0; font-size: {FONT_BODY}pt;
    selection-background-color: #4A4A4A;
}}

QComboBox {{
    background: transparent; color: {TEXT};
    border: 1px solid {BORDER}; border-radius: {RADIUS_SM}px;
    padding: {SPACE_XS}px {SPACE_SM}px; font-size: {FONT_SMALL}pt; min-width: 80px;
}}
QComboBox:hover {{ border-color: {BORDER_STRONG}; }}
QComboBox::drop-down {{ border: none; width: 20px; }}
QComboBox::down-arrow {{
    image: none; width: 6px; height: 6px; margin-right: {SPACE_SM}px;
    border-left: 1.5px solid {TEXT_DIM}; border-bottom: 1.5px solid {TEXT_DIM};
}}
QComboBox QAbstractItemView {{
    background: {SURFACE}; color: {TEXT};
    border: 1px solid {BORDER_STRONG}; border-radius: {RADIUS_MD}px;
    selection-background-color: {SURFACE_ACTIVE}; selection-color: {TEXT};
    padding: {SPACE_XS}px; outline: none;
}}

QSpinBox {{
    background: {SURFACE}; color: {TEXT};
    border: 1px solid {BORDER}; border-radius: {RADIUS_SM}px;
    padding: {SPACE_XS}px {SPACE_SM}px; font-size: {FONT_SMALL}pt;
}}

/* ── 列表 ── */
QListWidget {{
    background: transparent; color: {TEXT_DIM};
    border: none; outline: none; font-size: {FONT_SMALL}pt;
}}
QListWidget::item {{
    padding: {SPACE_SM}px {SPACE_MD}px; border-radius: {RADIUS_SM}px;
    margin: 1px {SPACE_SM}px; color: {TEXT_DIM};
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

/* ── 分段控件（仿 ChatGPT 顶部 聊天/工作）── */
QFrame#Segmented {{
    background: rgba(255, 255, 255, 0.06);
    border: none; border-radius: 18px;
}}
QPushButton#SegmentButton {{
    background: transparent; color: {TEXT_DIM};
    border: none; border-radius: 15px;
    padding: 0 18px; font-size: 9.5pt; font-weight: 600;
    min-height: 30px;
}}
QPushButton#SegmentButton:hover {{ color: {TEXT}; }}
QPushButton#SegmentButton:checked {{ background: {SURFACE_ACTIVE}; color: {TEXT}; }}

/* ── 面板 ── */
QFrame#UserBubble {{
    background: {BUBBLE_USER}; border: none; border-radius: {RADIUS_LG}px;
}}
QFrame#Composer {{
    background: {SURFACE}; border: 1px solid {BORDER};
    border-radius: {RADIUS_XL}px;
}}
QFrame#Composer[focused="true"] {{ border-color: {BORDER_STRONG}; }}
QFrame#ToolRow {{
    background: transparent; border: none; border-radius: {RADIUS_LG}px;
}}

/* ── 勾选框 ── */
QCheckBox {{ color: {TEXT}; spacing: {SPACE_SM}px; font-size: {FONT_SMALL}pt; }}
QCheckBox::indicator {{
    width: 16px; height: 16px; border-radius: 4px;
    border: 1px solid {BORDER_STRONG}; background: transparent;
}}
QCheckBox::indicator:hover {{ border-color: {TEXT_DIM}; }}
QCheckBox::indicator:checked {{ background: {TEXT}; border-color: {TEXT}; }}

/* ── 分组框 ── */
QGroupBox {{
    border: 1px solid {BORDER}; border-radius: {RADIUS_MD}px;
    margin-top: {SPACE_LG}px; padding: {SPACE_LG}px {SPACE_LG}px {SPACE_MD}px {SPACE_LG}px;
    font-size: {FONT_SMALL}pt; font-weight: 600; color: {TEXT_DIM};
}}
QGroupBox::title {{
    subcontrol-origin: margin; subcontrol-position: top left;
    left: {SPACE_MD}px; padding: 0 {SPACE_XS}px; background: {MAIN};
}}

/* ── 对话框 / 菜单 ── */
QDialog {{ background: {MAIN}; color: {TEXT}; }}

QMenu {{
    background: {SURFACE}; color: {TEXT};
    border: 1px solid {BORDER_STRONG}; border-radius: {RADIUS_MD}px;
    padding: {SPACE_XS}px;
}}
QMenu::item {{
    padding: {SPACE_SM}px {SPACE_XL}px {SPACE_SM}px {SPACE_MD}px;
    border-radius: {RADIUS_SM}px; font-size: {FONT_SMALL}pt;
}}
QMenu::item:selected {{ background: {SURFACE_ACTIVE}; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: {SPACE_XS}px {SPACE_SM}px; }}

QToolTip {{
    background: {SURFACE}; color: {TEXT};
    border: 1px solid {BORDER_STRONG}; border-radius: {RADIUS_SM}px;
    padding: {SPACE_XS}px {SPACE_SM}px;
}}
"""
