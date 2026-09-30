# -*- coding: utf-8 -*-
"""AI 团队群聊 · 桌面版 —— 主程序（界面与交互）。

界面取向：ChatGPT 那种"少即是多"的布局
--------------------------------------
· 左边一条窄侧栏：品牌 + 新对话 + 历史会话 + 设置
· 右边一块内容区，正文居中限宽（约 760px），两侧留白
· 我的发言是右对齐的圆角气泡，AI 的发言是左对齐的纯文本（带头像行）
· 底部一个圆角输入框，发送键是白色圆钮
· 整屏几乎不用彩色，颜色只留给"角色标记"

不搞教程式向导：配置没配好时只在对话流里提示，点「去配置」进面板。
角色是一个可自由增删改的列表，发言顺序就是列表顺序。

模块
----
    desktop_app.py   界面与交互（本文件）
    theme.py         ChatGPT 风格配色与样式表
    team_session.py  会话：多轮追问 / 流式输出 / 优雅停止
    llm.py           模型客户端构造与连接测试
    app_config.py    配置、角色列表、校验、损坏恢复
    secret_store.py  密钥加密（Windows DPAPI）
    app_logging.py   日志、脱敏、诊断包
    tools.py         AI 的"手臂"：搜索 / 文件 / GitHub / 命令
"""
import datetime
import json
import os
import sys

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox,
                               QDialog, QDialogButtonBox, QFormLayout, QFrame, QGroupBox,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMainWindow, QMenu, QMessageBox,
                               QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy,
                               QSpinBox, QVBoxLayout, QWidget)

import app_config
import theme
from app_config import (PRESETS_BY_KEY, ROLE_PRESETS, SOURCE_LABELS, SOURCE_SHORT,
                        TOOL_CATALOG, LoadResult, load_settings, save_settings)
from app_logging import (export_diagnostics, get_logger, install_excepthook,
                         register_secret, setup_logging)
from llm import ZHIPU_BASE_CN, ZHIPU_BASE_INTL, ZHIPU_MODELS, fetch_ollama_models
from team_session import TeamSession

log = get_logger("ui")
APP_DIR = os.path.dirname(os.path.abspath(__file__))


# ── 小工具 ─────────────────────────────────────────────────────
def open_in_explorer(path: str):
    try:
        if sys.platform == "win32":
            os.startfile(path)                                    # noqa: S606
        else:
            import subprocess
            subprocess.Popen(["xdg-open", path])
    except Exception:
        log.exception("打开目录失败：%s", path)


def label(text="", role="", wrap=False, selectable=False) -> QLabel:
    widget = QLabel(text)
    if role:
        widget.setProperty("role", role)
    widget.setWordWrap(wrap)
    if selectable:
        widget.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return widget


def button(text, role="", on_click=None) -> QPushButton:
    widget = QPushButton(text)
    if role:
        widget.setProperty("role", role)
    if on_click:
        widget.clicked.connect(on_click)
    return widget


def dot_pixmap(color: str, size: int = 9) -> QPixmap:
    """画一个实心小圆点，用来做角色标记。"""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(QColor(color))
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(0, 0, size, size)
    painter.end()
    return pixmap


def role_color(role: dict) -> str:
    return (role or {}).get("color") or theme.ROLE_COLORS[0]


# 正文用显式字体：QSS 的 font-size 要等 polish 才生效，构造时量不准宽度，
# 而气泡宽度正是靠字体度量算出来的，两边必须一致。
BODY_FONT_PT = 11
BUBBLE_TEXT_MAX = int(theme.CONTENT_MAX_WIDTH * 0.75) - 32


def body_font() -> QFont:
    return QFont("Microsoft YaHei UI", BODY_FONT_PT)


def measure_text(text: str, limit: int = None) -> int:
    """量一段文字的单行宽度（可夹上限）。"""
    width = QFontMetrics(body_font()).horizontalAdvance(text or "")
    if limit is not None:
        width = min(width, limit)
    return max(24, width)


# ── 消息控件 ───────────────────────────────────────────────────
class UserMessage(QWidget):
    """我的发言：右对齐圆角气泡。"""

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 6, 0, 6)
        row.addStretch(1)
        bubble = QFrame()
        bubble.setObjectName("UserBubble")
        bubble.setMaximumWidth(int(theme.CONTENT_MAX_WIDTH * 0.75))
        inner = QVBoxLayout(bubble)
        inner.setContentsMargins(16, 10, 16, 10)
        body = label(text, "body", wrap=True, selectable=True)
        body.setFont(body_font())
        # 按内容定宽：否则 wordWrap 的 QLabel 会给出偏小的 sizeHint，
        # 气泡被挤窄、文字过早折行。超过上限才交给 wordWrap 折。
        body.setFixedWidth(measure_text(text, BUBBLE_TEXT_MAX))
        inner.addWidget(body)
        row.addWidget(bubble)


class AssistantMessage(QWidget):
    """AI 的发言：左对齐，头一行是角色名（带色点），下面是正文。

    流式输出就靠 append() 往正文里追加，所以正文是一个独立的 QLabel。
    """

    def __init__(self, name: str, color: str, parent=None):
        super().__init__(parent)
        self._buffer = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setSpacing(5)

        head = QHBoxLayout()
        head.setSpacing(7)
        mark = QLabel()
        mark.setPixmap(dot_pixmap(color))
        mark.setFixedSize(9, 9)
        head.addWidget(mark)
        name_label = label(name, "role-name")
        name_label.setStyleSheet("color: %s;" % color)
        head.addWidget(name_label)
        head.addStretch(1)
        layout.addLayout(head)

        self.body = label("", "body", wrap=True, selectable=True)
        self.body.setFont(body_font())
        self.body.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        layout.addWidget(self.body)

    def set_text(self, text: str):
        self._buffer = text
        self.body.setText(text)

    def append(self, chunk: str):
        self._buffer += chunk
        self.body.setText(self._buffer)

    @property
    def text(self) -> str:
        return self._buffer


class ToolMessage(QWidget):
    """工具调用过程：一行小字，不抢注意力。"""

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 1, 0, 1)
        line = label(text, "faint", wrap=True)
        line.setStyleSheet("color: %s; font-size: 9pt;" % theme.TOOL_TEXT)
        layout.addWidget(line)
        layout.addStretch(1)


class SystemMessage(QWidget):
    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 6, 0, 6)
        line = label(text, "faint", wrap=True)
        line.setStyleSheet("color: %s; font-size: 9.5pt;" % theme.SYS_TEXT)
        layout.addWidget(line)
        layout.addStretch(1)


class NoticeMessage(QWidget):
    """带一个动作按钮的提示（例如"配置不完整 → 去配置"）。"""

    def __init__(self, text: str, action_text: str, on_action, parent=None):
        super().__init__(parent)
        frame = QFrame()
        frame.setStyleSheet(
            "QFrame { background: %s; border: 1px solid %s; border-radius: 12px; }"
            % (theme.SURFACE, theme.BORDER))
        inner = QHBoxLayout(frame)
        inner.setContentsMargins(14, 10, 10, 10)
        inner.setSpacing(10)
        inner.addWidget(label(text, "dim", wrap=True), stretch=1)
        inner.addWidget(button(action_text, "primary", on_action))
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 8, 0, 8)
        outer.addWidget(frame)


class CenteredPane(QWidget):
    """让内部控件水平居中并限宽。

    注意：不能用 addStretch 来居中 —— QHBoxLayout 会把可用宽度按 stretch
    因子平分，几个 stretch=1 就会把内容挤成 1/3 宽（setMaximumWidth 只是上限，
    不是目标宽度）。所以这里在 resize 时按可用宽度算实际宽度。
    """

    def __init__(self, inner: QWidget, max_width: int = None,
                 margin: int = 24, parent=None):
        super().__init__(parent)
        self._max_width = max_width or theme.CONTENT_MAX_WIDTH
        self._margin = margin
        self._inner = inner
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addStretch(1)
        row.addWidget(inner)
        row.addStretch(1)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        available = max(280, self.width() - self._margin * 2)
        self._inner.setFixedWidth(min(self._max_width, available))


class MessageArea(QScrollArea):
    """聊天区：可滚动的消息列，居中限宽。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        container = QWidget()
        outer = QHBoxLayout(container)
        outer.setContentsMargins(24, 16, 24, 8)
        outer.setSpacing(0)
        outer.addStretch(1)

        self.column = QWidget()
        self.column.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Minimum)
        self.messages = QVBoxLayout(self.column)
        self.messages.setContentsMargins(0, 0, 0, 0)
        self.messages.setSpacing(0)
        self.messages.addStretch(1)
        outer.addWidget(self.column)
        outer.addStretch(1)

        self.setWidget(container)
        self._empty_state = None

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # 内容列宽度按可用宽度算，别让弹簧把消息挤窄
        available = max(280, self.viewport().width() - 48)
        self.column.setFixedWidth(min(theme.CONTENT_MAX_WIDTH, available))

    # ── 内容 ──
    def _insert(self, widget: QWidget):
        sticky = self.at_bottom()
        self.messages.insertWidget(self.messages.count() - 1, widget)
        if sticky:
            self.scroll_to_bottom()
        return widget

    def add_user(self, text: str):
        return self._insert(UserMessage(text))

    def add_assistant(self, name: str, color: str, text: str = "") -> AssistantMessage:
        widget = AssistantMessage(name, color)
        if text:
            widget.set_text(text)
        return self._insert(widget)

    def add_tool(self, text: str):
        return self._insert(ToolMessage(text))

    def add_system(self, text: str):
        return self._insert(SystemMessage(text))

    def add_notice(self, text: str, action_text: str, on_action):
        return self._insert(NoticeMessage(text, action_text, on_action))

    def show_empty_state(self, title: str, hints: list, on_hint=None):
        """空状态：一句招呼 + 几个可点的示例（像 ChatGPT 那样）。"""
        self.clear()
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 60, 0, 20)
        layout.setSpacing(18)
        heading = label(title, "empty")
        heading.setAlignment(Qt.AlignCenter)
        layout.addWidget(heading)

        chips = QWidget()
        chip_layout = QVBoxLayout(chips)
        chip_layout.setSpacing(8)
        for hint in hints:
            chip = button(hint, on_click=(lambda _=False, h=hint: on_hint and on_hint(h)))
            chip.setStyleSheet(
                "QPushButton { background: transparent; color: %s; border: 1px solid %s;"
                "border-radius: 12px; padding: 10px 14px; font-size: 10pt; text-align: left; }"
                "QPushButton:hover { background: %s; color: %s; }"
                % (theme.TEXT_DIM, theme.BORDER, theme.SURFACE_HOVER, theme.TEXT))
            chip_layout.addWidget(chip)
        row = QHBoxLayout()
        row.addStretch(1)
        chips.setMaximumWidth(520)
        row.addWidget(chips)
        row.addStretch(1)
        layout.addLayout(row)
        self._insert(widget)
        self._empty_state = widget

    def clear(self):
        self._empty_state = None
        while self.messages.count() > 1:
            item = self.messages.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def at_bottom(self) -> bool:
        bar = self.verticalScrollBar()
        return bar.value() >= bar.maximum() - 8

    def scroll_to_bottom(self):
        QTimer.singleShot(0, lambda: self.verticalScrollBar().setValue(
            self.verticalScrollBar().maximum()))


# ── 输入区 ─────────────────────────────────────────────────────
class Composer(QFrame):
    """底部输入框：圆角、聚焦时描边变亮，右侧一个圆形发送钮。"""

    submitted = Signal(str)
    stop_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Composer")
        self.setProperty("focused", "false")

        row = QHBoxLayout(self)
        row.setContentsMargins(18, 10, 10, 10)
        row.setSpacing(10)
        self.input = QLineEdit()
        self.input.setPlaceholderText("给团队发个任务…")
        self.input.returnPressed.connect(self._submit)
        row.addWidget(self.input, stretch=1)

        self.send_btn = QPushButton("↑")
        self.send_btn.setObjectName("SendButton")
        self.send_btn.setToolTip("发送")
        self.send_btn.clicked.connect(self._submit)
        row.addWidget(self.send_btn)

        self.stop_btn = QPushButton("■")
        self.stop_btn.setObjectName("StopButton")
        self.stop_btn.setToolTip("停止")
        self.stop_btn.clicked.connect(self.stop_requested.emit)
        self.stop_btn.hide()
        row.addWidget(self.stop_btn)

        # 显式状态位：不要用控件可见性推断业务状态，
        # 窗口还没 show 的时候子控件的 isVisible() 恒为 False。
        self.running = False
        self.input.installEventFilter(self)

    def eventFilter(self, obj, event):
        if obj is self.input:
            if event.type() == event.Type.FocusIn:
                self._set_focused(True)
            elif event.type() == event.Type.FocusOut:
                self._set_focused(False)
        return super().eventFilter(obj, event)

    def _set_focused(self, focused: bool):
        self.setProperty("focused", "true" if focused else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def _submit(self):
        text = self.input.text().strip()
        if text:
            self.submitted.emit(text)

    def set_running(self, running: bool):
        self.running = running
        self.send_btn.setVisible(not running)
        self.stop_btn.setVisible(running)
        self.input.setEnabled(not running)

    def set_placeholder(self, text: str):
        self.input.setPlaceholderText(text)

    def clear(self):
        self.input.clear()


# ── 侧栏 ───────────────────────────────────────────────────────
class Sidebar(QWidget):
    """左侧会话栏：品牌 / 新对话 / 历史 / 设置。"""

    new_chat = Signal()
    open_settings = Signal()
    history_selected = Signal(str)      # 历史文件路径，空串表示回到当前对话

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Sidebar")
        # QWidget 的子类默认不绘制 QSS 背景，必须显式打开，
        # 否则侧栏和主区会糊成同一个颜色，整屏失去层次。
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedWidth(260)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 12, 10, 12)
        root.setSpacing(6)

        brand = QHBoxLayout()
        brand.setContentsMargins(6, 0, 0, 6)
        brand.addWidget(label("AI 团队群聊", "brand"))
        brand.addStretch(1)
        root.addLayout(brand)

        self.new_btn = button("＋   新对话", "ghost", self.new_chat.emit)
        root.addWidget(self.new_btn)

        # 团队成员：这个应用的核心就是"几个不同模型的 AI"，
        # 团队构成必须一眼可见，不能藏在 tooltip 里。
        root.addWidget(label("团队成员", "section"))
        self.team_box = QWidget()
        self.team_layout = QVBoxLayout(self.team_box)
        self.team_layout.setContentsMargins(0, 0, 0, 6)
        self.team_layout.setSpacing(0)
        root.addWidget(self.team_box)

        root.addWidget(label("历史会话", "section"))
        self.history = QListWidget()
        self.history.setSelectionMode(QAbstractItemView.SingleSelection)
        self.history.itemClicked.connect(self._on_history_clicked)
        root.addWidget(self.history, stretch=1)

        root.addWidget(button("⚙   配置", "ghost", self.open_settings.emit))

    def reload_roles(self, settings):
        """按当前配置刷新团队成员列表。"""
        while self.team_layout.count():
            item = self.team_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        for role in app_config.enabled_roles(settings):
            row = QPushButton("%s    %s" % (
                role.get("name") or "?",
                SOURCE_SHORT.get(role.get("source", ""), "?")))
            row.setProperty("role", "ghost")
            row.setIcon(QIcon(dot_pixmap(role_color(role), 9)))
            row.setStyleSheet("text-align: left; font-size: 9.5pt; padding: 5px 8px;")
            row.setToolTip("%s\n模型：%s\n\n点一下打开配置" % (
                (role.get("system_prompt") or "")[:180],
                role.get("model") or "未选"))
            row.clicked.connect(self.open_settings.emit)
            self.team_layout.addWidget(row)

    def _on_history_clicked(self, item):
        self.history_selected.emit(item.data(Qt.UserRole) or "")

    def reload_history(self, items: list):
        """按 今天 / 昨天 / 更早 分组，像 ChatGPT 那样。"""
        self.history.clear()
        if not items:
            # 没有历史时给一句说明，否则侧栏下半部分是一大块无解释的空白
            hint = QListWidgetItem("   还没有历史记录")
            hint.setFlags(Qt.NoItemFlags)
            hint.setForeground(QColor(theme.TEXT_FAINT))
            self.history.addItem(hint)
            return
        today = datetime.date.today()
        groups = {"今天": [], "昨天": [], "更早": []}
        for item in items:
            try:
                when = datetime.datetime.strptime(item["time"], "%Y-%m-%d %H:%M:%S").date()
            except Exception:
                groups["更早"].append(item)
                continue
            delta = (today - when).days
            groups["今天" if delta <= 0 else "昨天" if delta == 1 else "更早"].append(item)

        for name, group in groups.items():
            if not group:
                continue
            head = QListWidgetItem(name)
            head.setFlags(Qt.NoItemFlags)
            head.setForeground(QColor(theme.TEXT_FAINT))
            head.setData(Qt.UserRole, "")
            self.history.addItem(head)
            for item in group:
                task = item["task"][:22] + ("…" if len(item["task"]) > 22 else "")
                row = QListWidgetItem("   " + task)
                row.setData(Qt.UserRole, item["file"])
                row.setToolTip("%s\n%s" % (item["time"], item["task"]))
                self.history.addItem(row)

    def select_none(self):
        self.history.setCurrentRow(-1)


# ── 模型连通性测试 ─────────────────────────────────────────────
class TestWorker(QThread):
    progress = Signal(str, bool, str)
    finished_all = Signal(int, int)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self._settings = settings

    def run(self):
        import asyncio
        from llm import test_connection
        roles = app_config.enabled_roles(self._settings)
        total = passed = 0
        for role in roles:
            total += 1
            try:
                ok, message = asyncio.run(test_connection(role, self._settings))
            except Exception as exc:
                ok, message = False, str(exc)
            if ok:
                passed += 1
            self.progress.emit(role.get("name") or "?", ok, message)
        self.finished_all.emit(passed, total)


# ── 角色编辑 ───────────────────────────────────────────────────
class RoleDialog(QDialog):
    def __init__(self, role: dict, settings: dict, parent=None, is_new=False):
        super().__init__(parent)
        self.role = dict(role)
        self.settings = settings
        self.is_new = is_new
        self.setWindowTitle("添加角色" if is_new else "编辑角色")
        self.setMinimumSize(600, 640)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(12)
        heading = label("添加角色" if self.is_new else "编辑角色")
        heading.setStyleSheet("font-size: 13pt; font-weight: 600;")
        root.addWidget(heading)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        form = QFormLayout(inner)
        form.setSpacing(11)

        self.name_edit = QLineEdit(self.role.get("name", ""))
        self.name_edit.setStyleSheet(
            "QLineEdit { background: %s; border: 1px solid %s; border-radius: 9px;"
            "padding: 8px 11px; }" % (theme.SURFACE, theme.BORDER))
        self.name_edit.setPlaceholderText("例如：经理 / 策划 / 唱反调")
        form.addRow("名称", self.name_edit)

        self.color_box = QComboBox()
        for value in theme.ROLE_COLORS:
            self.color_box.addItem(dot_pixmap(value), value, value)
        index = self.color_box.findData(self.role.get("color"))
        self.color_box.setCurrentIndex(index if index >= 0 else 0)
        form.addRow("颜色", self.color_box)

        self.source_box = QComboBox()
        for key in ("zhipu", "ollama", "custom"):
            self.source_box.addItem(SOURCE_LABELS[key], key)
        self.source_box.setCurrentIndex(
            max(0, self.source_box.findData(self.role.get("source", "zhipu"))))
        self.source_box.currentIndexChanged.connect(self._on_source_changed)
        form.addRow("模型来源", self.source_box)

        self.model_box = QComboBox()
        self.model_box.setEditable(True)
        form.addRow("模型", self.model_box)

        self.base_edit = QLineEdit(self.role.get("base_url", ""))
        self.base_edit.setPlaceholderText("例如 https://api.deepseek.com/v1")
        form.addRow("Base URL", self.base_edit)

        self.key_edit = QLineEdit(self.role.get("api_key", ""))
        self.key_edit.setEchoMode(QLineEdit.Password)
        self.key_edit.setPlaceholderText("自定义来源才需要；会加密保存")
        form.addRow("API Key", self.key_edit)

        self.prompt_edit = QPlainTextEdit(self.role.get("system_prompt", ""))
        self.prompt_edit.setMinimumHeight(110)
        self.prompt_edit.setStyleSheet(
            "QPlainTextEdit { background: %s; border: 1px solid %s; border-radius: 9px;"
            "padding: 8px 11px; }" % (theme.SURFACE, theme.BORDER))
        form.addRow("人设提示词", self.prompt_edit)

        tools_box = QWidget()
        tools_layout = QVBoxLayout(tools_box)
        tools_layout.setContentsMargins(0, 0, 0, 0)
        tools_layout.setSpacing(6)
        self.tool_checks = {}
        current = set(self.role.get("tools") or [])
        for name, tool_label, desc in TOOL_CATALOG:
            check = QCheckBox("%s —— %s" % (tool_label, desc))
            check.setChecked(name in current)
            self.tool_checks[name] = check
            tools_layout.addWidget(check)
        form.addRow("可用工具", tools_box)

        self.enabled_check = QCheckBox("参与讨论")
        self.enabled_check.setChecked(self.role.get("enabled", True))
        form.addRow("", self.enabled_check)

        scroll.setWidget(inner)
        root.addWidget(scroll, stretch=1)

        self.error_label = label("", "faint", wrap=True)
        self.error_label.setStyleSheet("color: %s;" % theme.DANGER)
        root.addWidget(self.error_label)

        buttons = QDialogButtonBox()
        save = buttons.addButton("保存", QDialogButtonBox.AcceptRole)
        save.setProperty("role", "primary")
        buttons.addButton("取消", QDialogButtonBox.RejectRole)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self._fill_models(keep=self.role.get("model", ""))
        self._on_source_changed()

    def _fill_models(self, keep=""):
        source = self.source_box.currentData()
        self.model_box.blockSignals(True)
        self.model_box.clear()
        if source == "zhipu":
            options = list(ZHIPU_MODELS)
        elif source == "ollama":
            options = fetch_ollama_models() or ["qwen2.5:7b"]
        else:
            options = []
        self.model_box.addItems(options)
        if keep:
            self.model_box.setCurrentText(keep)
        self.model_box.blockSignals(False)

    def _on_source_changed(self):
        is_custom = self.source_box.currentData() == "custom"
        self.base_edit.setVisible(is_custom)
        self.key_edit.setVisible(is_custom)
        self._fill_models(keep=self.model_box.currentText())

    def collect(self) -> dict:
        role = dict(self.role)
        role["name"] = self.name_edit.text().strip() or "角色"
        role["color"] = self.color_box.currentData()
        role["source"] = self.source_box.currentData()
        role["model"] = self.model_box.currentText().strip()
        role["base_url"] = self.base_edit.text().strip()
        role["api_key"] = self.key_edit.text().strip()
        role["system_prompt"] = self.prompt_edit.toPlainText().strip()
        role["tools"] = [n for n, c in self.tool_checks.items() if c.isChecked()]
        role["enabled"] = self.enabled_check.isChecked()
        return role

    def _on_accept(self):
        role = self.collect()
        problems = app_config.validate_role(role)
        if problems:
            self.error_label.setText("还差一点：" + "；".join(problems))
            return
        self.role = role
        self.accept()


class PresetDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("添加角色")
        self.setMinimumSize(460, 460)
        self.chosen = None
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(10)
        root.addWidget(label("挑一个起点", "dim"))
        self.list_widget = QListWidget()
        self.list_widget.itemDoubleClicked.connect(lambda _i: self._choose())
        for preset in ROLE_PRESETS:
            item = QListWidgetItem("%s    %s" % (preset["name"], preset["prompt"][:30] + "…"))
            item.setData(Qt.UserRole, preset["key"])
            item.setIcon(QIcon(dot_pixmap(preset["color"], 10)))
            self.list_widget.addItem(item)
        blank = QListWidgetItem("空白角色    自己写人设，从零开始")
        blank.setData(Qt.UserRole, "__blank__")
        self.list_widget.addItem(blank)
        root.addWidget(self.list_widget, stretch=1)
        buttons = QDialogButtonBox()
        ok = buttons.addButton("添加", QDialogButtonBox.AcceptRole)
        ok.setProperty("role", "primary")
        buttons.addButton("取消", QDialogButtonBox.RejectRole)
        buttons.accepted.connect(self._choose)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self.list_widget.setCurrentRow(0)

    def _choose(self):
        item = self.list_widget.currentItem()
        if item:
            self.chosen = item.data(Qt.UserRole)
            self.accept()


class ConfigDialog(QDialog):
    """配置面板：左边角色列表（可增删改排序），右边共享设置。"""

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("配置")
        self.setMinimumSize(840, 660)
        self._worker = None
        self._build()
        self._reload()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(12)

        head = QHBoxLayout()
        head.addWidget(label("配置", "empty"))
        head.addStretch(1)
        self.test_btn = button("测试全部", on_click=self._on_test)
        head.addWidget(self.test_btn)
        root.addLayout(head)
        root.addWidget(label("角色按列表顺序轮流发言。每个角色的模型、凭据、人设、工具都能单独设。",
                             "dim", wrap=True))

        body = QHBoxLayout()
        body.setSpacing(14)

        left = QVBoxLayout()
        left.setSpacing(8)
        left.addWidget(label("角色（发言顺序）", "dim"))
        self.role_list = QListWidget()
        self.role_list.itemDoubleClicked.connect(lambda _i: self._edit_role())
        left.addWidget(self.role_list, stretch=1)
        row1 = QHBoxLayout()
        row1.setSpacing(6)
        row1.addWidget(button("＋ 添加", "primary", self._add_role))
        row1.addWidget(button("编辑", on_click=self._edit_role))
        row1.addWidget(button("删除", "danger", self._delete_role))
        left.addLayout(row1)
        row2 = QHBoxLayout()
        row2.setSpacing(6)
        row2.addWidget(button("↑ 上移", on_click=lambda: self._move(-1)))
        row2.addWidget(button("↓ 下移", on_click=lambda: self._move(1)))
        row2.addWidget(button("启用/停用", on_click=self._toggle_enabled))
        left.addLayout(row2)
        left_wrap = QWidget()
        left_wrap.setLayout(left)
        left_wrap.setFixedWidth(360)
        body.addWidget(left_wrap)

        right = QVBoxLayout()
        right.setSpacing(12)
        zhipu = QGroupBox("智谱 GLM 共享凭据")
        zhipu_form = QFormLayout(zhipu)
        shared = self.settings.setdefault("shared", {})
        self.zhipu_key = QLineEdit(shared.get("zai_api_key", ""))
        self.zhipu_key.setEchoMode(QLineEdit.Password)
        self.zhipu_key.setPlaceholderText("在 open.bigmodel.cn 或 api.z.ai 申请")
        self.zhipu_key.setStyleSheet(
            "QLineEdit { background: %s; border: 1px solid %s; border-radius: 9px;"
            "padding: 8px 11px; }" % (theme.SURFACE, theme.BORDER))
        zhipu_form.addRow("API Key", self.zhipu_key)
        self.zhipu_base = QComboBox()
        self.zhipu_base.addItem("国内站 open.bigmodel.cn", ZHIPU_BASE_CN)
        self.zhipu_base.addItem("国际站 api.z.ai", ZHIPU_BASE_INTL)
        index = self.zhipu_base.findData(shared.get("zai_base_url") or ZHIPU_BASE_INTL)
        self.zhipu_base.setCurrentIndex(index if index >= 0 else 1)
        zhipu_form.addRow("接口地址", self.zhipu_base)
        right.addWidget(zhipu)

        misc = QGroupBox("讨论")
        misc_form = QFormLayout(misc)
        self.max_messages = QSpinBox()
        self.max_messages.setRange(2, 200)
        self.max_messages.setValue(int(self.settings.get("max_messages") or 18))
        self.max_messages.setSuffix("  条消息")
        misc_form.addRow("单轮上限", self.max_messages)
        right.addWidget(misc)

        self.problems = label("", "dim", wrap=True)
        right.addWidget(self.problems)
        right.addStretch(1)
        body.addLayout(right, stretch=1)
        root.addLayout(body, stretch=1)

        self.test_label = label("", "dim", wrap=True)
        root.addWidget(self.test_label)

        buttons = QDialogButtonBox()
        save = buttons.addButton("保存", QDialogButtonBox.AcceptRole)
        save.setProperty("role", "primary")
        buttons.addButton("取消", QDialogButtonBox.RejectRole)
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _reload(self, select=None):
        self.role_list.clear()
        for role in self.settings.get("roles") or []:
            enabled = role.get("enabled", True)
            text = "%s    %s · %s" % (role.get("name") or "?",
                                      SOURCE_SHORT.get(role.get("source", ""), "?"),
                                      role.get("model") or "未选模型")
            if not enabled:
                text += "    （已停用）"
            item = QListWidgetItem(text)
            item.setIcon(QIcon(dot_pixmap(role_color(role), 10)))
            if not enabled:
                item.setForeground(QColor(theme.TEXT_FAINT))
            self.role_list.addItem(item)
        if self.role_list.count():
            row = 0 if select is None else max(0, min(select, self.role_list.count() - 1))
            self.role_list.setCurrentRow(row)
        self._refresh_problems()

    def _current_role(self):
        index = self.role_list.currentRow()
        roles = self.settings.get("roles") or []
        return roles[index] if 0 <= index < len(roles) else None

    def _add_role(self):
        picker = PresetDialog(self)
        if picker.exec() != QDialog.Accepted or not picker.chosen:
            return
        roles = self.settings.setdefault("roles", [])
        key = "__blank__" if picker.chosen == "__blank__" else picker.chosen
        role = app_config.make_role(key, len(roles))
        role["id"] = app_config.unique_role_id(self.settings, role["id"])
        editor = RoleDialog(role, self.settings, self, is_new=True)
        if editor.exec() != QDialog.Accepted:
            return
        roles.append(editor.role)
        self._reload(len(roles) - 1)

    def _edit_role(self):
        role = self._current_role()
        if role is None:
            return
        index = self.role_list.currentRow()
        editor = RoleDialog(role, self.settings, self)
        if editor.exec() == QDialog.Accepted:
            self.settings["roles"][index] = editor.role
            self._reload(index)

    def _delete_role(self):
        index = self.role_list.currentRow()
        roles = self.settings.get("roles") or []
        if not (0 <= index < len(roles)):
            return
        if len(roles) <= 1:
            QMessageBox.information(self, "删不了", "至少要留一个角色。")
            return
        name = roles[index].get("name") or "?"
        if QMessageBox.question(self, "删除角色", "确定删除「%s」吗？" % name) != QMessageBox.Yes:
            return
        roles.pop(index)
        self._reload(index)

    def _move(self, delta):
        index = self.role_list.currentRow()
        roles = self.settings.get("roles") or []
        target = index + delta
        if not (0 <= index < len(roles)) or not (0 <= target < len(roles)):
            return
        roles[index], roles[target] = roles[target], roles[index]
        self._reload(target)

    def _toggle_enabled(self):
        role = self._current_role()
        if role is None:
            return
        role["enabled"] = not role.get("enabled", True)
        self._reload(self.role_list.currentRow())

    def _refresh_problems(self):
        shared = self.settings.setdefault("shared", {})
        shared["zai_api_key"] = self.zhipu_key.text().strip()
        shared["zai_base_url"] = self.zhipu_base.currentData()
        problems = app_config.validate_settings(self.settings)
        if problems:
            self.problems.setText("还有 %d 项没配好：%s"
                                  % (len(problems), "；".join(problems[:3])))
            self.problems.setStyleSheet("color: %s;" % theme.WARN)
        else:
            self.problems.setText("✓ 配置完整，可以开始讨论。")
            self.problems.setStyleSheet("color: %s;" % theme.SUCCESS)

    def collect(self) -> dict:
        shared = self.settings.setdefault("shared", {})
        shared["zai_api_key"] = self.zhipu_key.text().strip()
        shared["zai_base_url"] = self.zhipu_base.currentData()
        self.settings["max_messages"] = int(self.max_messages.value())
        return self.settings

    def _on_test(self):
        self.collect()
        self.test_btn.setEnabled(False)
        self.test_label.setText("正在逐个测试…（每个角色最多 30 秒）")
        self._worker = TestWorker(self.settings, self)
        self._worker.progress.connect(
            lambda cn, ok, msg: self.test_label.setText(
                "%s %s：%s" % ("✓" if ok else "✗", cn, msg.splitlines()[0][:110])))
        self._worker.finished_all.connect(self._on_test_done)
        self._worker.start()

    def _on_test_done(self, passed, total):
        self.test_btn.setEnabled(True)
        self.test_label.setText("测试完成：%d/%d 个角色可用。" % (passed, total))

    def _on_save(self):
        self.collect()
        problems = app_config.validate_settings(self.settings)
        if problems and QMessageBox.question(
                self, "配置还不完整",
                "还有 %d 项没配好：\n\n%s\n\n仍然保存吗？"
                % (len(problems), "\n".join(problems[:6]))) != QMessageBox.Yes:
            return
        try:
            save_settings(self.settings)
        except Exception as exc:
            QMessageBox.critical(self, "保存失败", "配置没能保存：\n%s" % exc)
            return
        for role in self.settings.get("roles") or []:
            register_secret(role.get("api_key", ""))
        register_secret((self.settings.get("shared") or {}).get("zai_api_key", ""))
        log.info("配置已保存，共 %d 个角色", len(self.settings.get("roles") or []))
        self.accept()


# ── 历史记录读写 ───────────────────────────────────────────────
def list_history() -> list:
    folder = app_config.history_dir()
    if not os.path.isdir(folder):
        return []
    items = []
    for name in os.listdir(folder):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(folder, name), "r", encoding="utf-8") as f:
                data = json.load(f)
            items.append({"id": name[:-5], "time": data.get("time", ""),
                          "task": data.get("task", ""),
                          "file": os.path.join(folder, name)})
        except Exception:
            continue
    items.sort(key=lambda x: x["time"], reverse=True)
    return items


def load_history_file(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_history(entries, task, time_str, meta=None) -> str:
    """写一条历史。先写临时文件再原子替换，避免中途崩溃留下半截 JSON。"""
    try:
        folder = app_config.history_dir()
        os.makedirs(folder, exist_ok=True)
        safe = "".join(c if c not in r'\/:*?"<>|' else "_" for c in task)[:30] or "任务"
        filename = "%s %s.json" % (time_str.replace(":", "-").replace(" ", "_"), safe)
        payload = {"time": time_str, "task": task, "messages": entries}
        if meta:
            payload["meta"] = meta
        tmp = os.path.join(folder, filename + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, os.path.join(folder, filename))
        return filename
    except Exception:
        log.exception("保存历史失败")
        return ""


# ── 主窗口 ─────────────────────────────────────────────────────
EMPTY_HINTS = [
    "推荐大学生宿舍百元内提升幸福感的小东西",
    "设计一个五一成都 3 天旅行方案，4 人人均预算 2500",
    "帮我评估一下这个想法值不值得做：……",
]


class MainWindow(QMainWindow):
    def __init__(self, load_result: LoadResult = None):
        super().__init__()
        self.load_result = load_result or load_settings()
        self.settings = self.load_result.settings
        self.session = None
        self.cur_task = ""
        self.cur_messages = []
        self._streaming = None          # 当前正在流式输出的 AssistantMessage
        self._stream_name = ""           # 当前流式发言的角色名
        self._stream_color = theme.TEXT
        self._reading_history = False

        self.setWindowTitle("AI 团队群聊")
        self.setMinimumSize(940, 660)
        self._set_icon()
        self._build_ui()
        self._register_secrets()
        self._start_fresh_view()

    def _set_icon(self):
        try:
            for name in ("app.ico", "ai_group.ico"):
                path = os.path.join(APP_DIR, name)
                if os.path.exists(path):
                    self.setWindowIcon(QIcon(path))
                    return
        except Exception:
            pass

    def _register_secrets(self):
        for role in (self.settings.get("roles") or []):
            register_secret(role.get("api_key", ""))
        register_secret((self.settings.get("shared") or {}).get("zai_api_key", ""))
        register_secret(app_config.github_token())

    # ── UI ──
    def _build_ui(self):
        central = QWidget()
        central.setObjectName("Root")
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.sidebar = Sidebar()
        self.sidebar.new_chat.connect(self.start_new_conversation)
        self.sidebar.open_settings.connect(self.open_config)
        self.sidebar.history_selected.connect(self.open_history_item)
        root.addWidget(self.sidebar)

        content = QWidget()
        content.setObjectName("Content")
        column = QVBoxLayout(content)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)

        # 顶栏：极薄，只放团队概览和一个菜单
        top = QWidget()
        top.setFixedHeight(50)
        top_row = QHBoxLayout(top)
        top_row.setContentsMargins(24, 10, 16, 6)
        top_row.setSpacing(10)
        self.title_label = label("新对话", "role-name")
        top_row.addWidget(self.title_label)
        top_row.addStretch(1)
        self.more_btn = button("⋯", "ghost")
        self.more_btn.setFixedWidth(36)
        menu = QMenu(self)
        menu.addAction("配置角色与模型", self.open_config)
        menu.addSeparator()
        menu.addAction("导出诊断包（含日志，已脱敏）", self.export_diagnostics_action)
        menu.addAction("打开日志文件夹", lambda: open_in_explorer(app_config.logs_dir()))
        menu.addAction("打开 AI 产出文件夹", lambda: open_in_explorer(app_config.documents_dir()))
        self.more_btn.setMenu(menu)
        top_row.addWidget(self.more_btn)
        column.addWidget(top)

        self.area = MessageArea()
        column.addWidget(self.area, stretch=1)

        # 输入区：居中限宽，和正文对齐
        wrap = QWidget()
        wrap_column = QVBoxLayout(wrap)
        wrap_column.setContentsMargins(0, 0, 0, 0)
        wrap_column.setSpacing(6)
        self.composer = Composer()
        self.composer.submitted.connect(self.send_task)
        self.composer.stop_requested.connect(self.stop)
        wrap_column.addWidget(self.composer)
        self.status = label("就绪", "faint")
        self.status.setAlignment(Qt.AlignCenter)
        wrap_column.addWidget(self.status)
        bottom = CenteredPane(wrap, margin=24)
        bottom.setContentsMargins(0, 6, 0, 14)
        column.addWidget(bottom)

        root.addWidget(content, stretch=1)
        self.setCentralWidget(central)

    def _refresh_team_label(self):
        """刷新侧栏的团队成员列表。"""
        self.sidebar.reload_roles(self.settings)

    def _reload_sidebar(self):
        self.sidebar.reload_history(list_history())

    def _start_fresh_view(self):
        self._refresh_team_label()
        self._reload_sidebar()
        problems = self.load_result.problems
        self.area.clear()
        self.area.show_empty_state("有什么可以帮你的？", EMPTY_HINTS, self._use_hint)
        if self.load_result.recovered:
            self.area.add_system("上次的配置文件损坏了，已备份为 %s 并恢复默认配置。"
                                 % os.path.basename(self.load_result.backup_path or "备份文件"))
        for note in self.load_result.notes:
            self.area.add_system(note)
        if problems:
            self.area.add_notice(
                "还差 %d 项就能开始了：%s" % (len(problems), "；".join(problems[:2])),
                "去配置", self.open_config)
        self._update_placeholder()

    def _use_hint(self, text: str):
        self.composer.input.setText(text)
        self.composer.input.setFocus()

    def _update_placeholder(self):
        if self._reading_history:
            self.composer.set_placeholder("正在查看历史记录…")
            return
        has_context = self.session is not None and self.session.has_context
        self.composer.set_placeholder("继续追问…" if has_context else "给团队发个任务…")

    # ── 会话 ──
    def _ensure_session(self) -> TeamSession:
        if self.session is None or not self.session.isRunning():
            self.session = TeamSession(self.settings, self)
            self.session.message.connect(self._on_message)
            self.session.stream_start.connect(self._on_stream_start)
            self.session.stream_chunk.connect(self._on_stream_chunk)
            self.session.stream_end.connect(self._on_stream_end)
            self.session.tool_event.connect(self._on_tool)
            self.session.turn_finished.connect(self._on_turn_finished)
            self.session.turn_stopped.connect(self._on_turn_stopped)
            self.session.turn_error.connect(self._on_turn_error)
            self.session.session_ready.connect(self._on_session_ready)
            self.session.start()
            self.session.wait_ready(10)
        return self.session

    def send_task(self, text: str = None):
        if self._reading_history:
            return
        task = (text if text is not None else self.composer.input.text()).strip()
        if not task:
            return
        if self.composer.running:
            self.status.setText("正在讨论中，先停止或等它跑完")
            return

        session = self._ensure_session()
        is_followup = session.has_context
        if not is_followup:
            self.area.clear()
            self.cur_task = task
            self.cur_messages = [{"kind": "user", "name": "我", "content": task}]
            self.title_label.setText(task[:26] + ("…" if len(task) > 26 else ""))

        self.composer.clear()
        self.composer.set_running(True)
        self.status.setText("追问中…" if is_followup else "讨论中…")
        self.area.add_user(task)
        if not session.ask(task):
            self._on_turn_error("会话线程没有就绪，请重试或重启程序。")

    def stop(self):
        if self.session is None or not self.composer.running:
            return
        self.composer.stop_btn.setEnabled(False)
        self.status.setText("正在停止…（等当前发言收尾）")
        self.session.stop()

    def start_new_conversation(self):
        if self.composer.running:
            QMessageBox.information(self, "正在讨论中", "先停止当前讨论，再开新对话。")
            return
        self._save_cur_history(ending="用户开了新对话")
        self._reading_history = False
        self.composer.set_running(False)
        self.composer.input.setEnabled(True)
        if self.session is not None:
            self.session.new_conversation()
        self.title_label.setText("新对话")
        self.sidebar.select_none()
        self._start_fresh_view()

    # ── 历史 ──
    def open_history_item(self, path: str):
        if not path:
            return
        data = load_history_file(path)
        if not data:
            return
        if self.composer.running:
            QMessageBox.information(self, "正在讨论中", "先停止当前讨论，再看历史。")
            return
        self._save_cur_history(ending="用户去看了历史记录")
        self._reading_history = True
        self.composer.set_running(False)
        self.composer.input.setEnabled(False)
        self.title_label.setText(data.get("task", "历史记录")[:26])
        self.area.clear()
        self.area.add_system("这是 %s 的历史记录（只读）。点侧栏「＋ 新对话」回到当前对话。"
                             % data.get("time", ""))
        self.area.add_user(data.get("task", ""))
        for msg in data.get("messages", []):
            kind = msg.get("kind", "")
            if kind == "user":
                continue
            if kind == "msg":
                self.area.add_assistant(msg.get("name", ""), msg.get("color") or theme.TEXT,
                                        msg.get("content", ""))
            elif kind == "tool":
                self.area.add_tool("🔧 %s %s：%s" % (msg.get("name", ""), msg.get("phase", ""),
                                                     msg.get("content", "")))
            elif kind == "system":
                self.area.add_system(msg.get("content", ""))
        self._update_placeholder()

    # ── 会话信号 ──
    def _on_session_ready(self):
        log.info("会话已就绪")
        self._update_placeholder()

    def _on_stream_start(self, cn_name, color):
        self._stream_name = cn_name
        self._stream_color = color
        self._streaming = self.area.add_assistant(cn_name, color)

    def _on_stream_chunk(self, chunk):
        if self._streaming is not None:
            self._streaming.append(chunk)
            if self.area.at_bottom():
                self.area.scroll_to_bottom()

    def _on_stream_end(self, final_text):
        if self._streaming is None:
            return
        self._streaming.set_text(final_text)
        if final_text.strip():
            self.cur_messages.append({"kind": "msg",
                                      "name": self._stream_name or "",
                                      "content": final_text,
                                      "color": self._stream_color or theme.TEXT})
        self._streaming = None

    def _on_message(self, cn_name, source, content):
        """没有走流式的完整发言（例如工具回合之后的自然语言总结）。"""
        self._streaming = None
        self.area.add_assistant(cn_name, self._role_color(source), content)
        self.cur_messages.append({"kind": "msg", "name": cn_name,
                                  "content": content, "color": self._role_color(source)})

    def _on_tool(self, cn_name, phase, detail):
        self._streaming = None
        self.area.add_tool("🔧 %s %s：%s" % (cn_name, phase, detail))
        self.cur_messages.append({"kind": "tool", "name": cn_name,
                                  "phase": phase, "content": detail})

    def _on_turn_finished(self, reason):
        self.area.add_system("本轮结束。%s" % reason)
        self._save_cur_history(ending="讨论结束（%s）" % reason)
        self._reset_ui("可以继续追问")
        self._reload_sidebar()

    def _on_turn_stopped(self, context_lost):
        self.area.add_system("已强制停止，上下文已重置 —— 下一次发言会开新对话。"
                             if context_lost else
                             "已停止，上下文保留，可以直接接着追问。")
        self._save_cur_history(ending="用户手动停止了讨论")
        self._reset_ui("已停止")
        self._reload_sidebar()

    def _on_turn_error(self, message):
        self.area.add_system("出错：%s" % message)
        log.error("会话出错：%s", message)
        QMessageBox.critical(self, "出错了", "AI 团队运行出错：\n\n%s" % message)
        self._save_cur_history(ending="出错：%s" % message)
        self._reset_ui("出错，请重试")

    def _reset_ui(self, state_text):
        self._streaming = None
        self.composer.set_running(False)
        self.composer.stop_btn.setEnabled(True)
        self.composer.input.setEnabled(True)
        self.status.setText(state_text)
        self._update_placeholder()
        self.composer.input.setFocus()

    def _role_color(self, source):
        for role in (self.settings.get("roles") or []):
            if role.get("id") == source:
                return role_color(role)
        return theme.TEXT

    # ── 历史保存 ──
    def _save_cur_history(self, ending=""):
        if not self.cur_task or not self.cur_messages:
            return
        entries = list(self.cur_messages)
        if ending:
            entries.append({"kind": "system", "name": "", "content": ending})
        meta = [{"name": r.get("name"), "model": r.get("model"), "source": r.get("source")}
                for r in (self.settings.get("roles") or [])]
        save_history(entries, self.cur_task,
                     datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), meta)
        self.cur_task = ""
        self.cur_messages = []

    # ── 菜单动作 ──
    def open_config(self):
        dialog = ConfigDialog(self.settings, self)
        if dialog.exec() == QDialog.Accepted:
            self.settings = load_settings(migrate=False).settings
            self._register_secrets()
            self._refresh_team_label()
            if self.session is not None:
                self.session.apply_settings(self.settings)
            self.area.add_system("配置已更新。下一次发言会按新配置重建团队，会话上下文重新开始。")

    def export_diagnostics_action(self):
        try:
            path = export_diagnostics()
        except Exception as exc:
            QMessageBox.critical(self, "导出失败", "诊断包没能生成：\n%s" % exc)
            return
        QMessageBox.information(self, "已导出",
                                "诊断包已生成（日志中的密钥已自动脱敏）：\n\n%s" % path)

    def closeEvent(self, event):
        self._save_cur_history(ending="程序关闭")
        if self.session is not None and self.session.isRunning():
            if not self.session.shutdown(8000):
                log.warning("会话线程 8 秒内未退出，强制终止")
                self.session.terminate()
                self.session.wait(1000)
        log.info("程序退出")
        super().closeEvent(event)


def main():
    install_excepthook()
    log_path = setup_logging()
    log.info("启动 %s，日志：%s", app_config.APP_NAME, log_path)

    app = QApplication(sys.argv)
    app.setFont(QFont("Microsoft YaHei UI", 10))
    app.setStyleSheet(theme.app_stylesheet())
    try:
        load_result = load_settings()
    except Exception:
        log.exception("加载配置失败，回退默认配置")
        load_result = LoadResult(app_config.default_settings(), created=True)

    window = MainWindow(load_result)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
