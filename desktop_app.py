# -*- coding: utf-8 -*-
"""AI 团队群聊 · 桌面版 —— 主程序（界面与交互）。

界面取向：ChatGPT 桌面版
------------------------
· 左侧一条 76px 的窄图标栏（新对话 / 历史 / 团队 / 设置），不是宽文本侧栏
· 整屏近纯黑，层次靠"比背景略亮的面板"分
· 空状态只有一个大标题 + 一大块圆角输入框，输入框下方还有一排小工具
· 输入框宽度上限 1100px，是画面里最大的实体

模块
----
    desktop_app.py   界面与交互（本文件）
    icons.py         用 QPainter 画的线性图标
    theme.py         ChatGPT 桌面版风格配色与样式表
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
from PySide6.QtGui import QColor, QFont, QFontMetrics, QIcon
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox,
                               QDialog, QDialogButtonBox, QFormLayout, QFrame, QGroupBox,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMainWindow, QMenu, QMessageBox,
                               QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy,
                               QSpinBox, QVBoxLayout, QWidget)

import app_config
import icons
import theme
from app_config import (PRESETS_BY_KEY, ROLE_PRESETS, SOURCE_LABELS, SOURCE_SHORT,
                        TOOL_CATALOG, LoadResult, load_settings, save_settings)
from app_logging import (export_diagnostics, get_logger, install_excepthook,
                         register_secret, setup_logging)
from llm import ZHIPU_BASE_CN, ZHIPU_BASE_INTL, ZHIPU_MODELS, fetch_ollama_models
from team_session import TeamSession

log = get_logger("ui")
APP_DIR = os.path.dirname(os.path.abspath(__file__))

BODY_FONT_PT = 10.5
BUBBLE_TEXT_MAX = int(theme.CHAT_MAX_WIDTH * 0.72) - 32
EMPTY_HINTS = [
    "推荐大学生宿舍百元内提升幸福感的小东西",
    "设计一个五一成都 3 天旅行方案，4 人人均预算 2500",
]


# ── 通用小工具 ─────────────────────────────────────────────────
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


def icon_button(pixmap, tooltip, on_click=None, checkable=False) -> QPushButton:
    widget = QPushButton()
    widget.setObjectName("RailButton")
    widget.setIcon(QIcon(pixmap))
    widget.setIconSize(pixmap.size())
    widget.setToolTip(tooltip)
    widget.setCheckable(checkable)
    if on_click:
        widget.clicked.connect(on_click)
    return widget


def body_font() -> QFont:
    return QFont("Microsoft YaHei UI", BODY_FONT_PT)


def measure_text(text: str, limit: int = None) -> int:
    """量一段文字的单行宽度（可夹上限）。

    开了 wordWrap 的 QLabel 会给出偏小的 sizeHint，气泡会被挤窄、文字过早折行，
    所以宽度得自己量。
    """
    width = QFontMetrics(body_font()).horizontalAdvance(text or "")
    if limit is not None:
        width = min(width, limit)
    return max(24, width)


def role_color(role: dict) -> str:
    return (role or {}).get("color") or theme.ROLE_COLORS[0]


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
        bubble.setMaximumWidth(int(theme.CHAT_MAX_WIDTH * 0.72))
        inner = QVBoxLayout(bubble)
        inner.setContentsMargins(16, 10, 16, 10)
        body = label(text, "body", wrap=True, selectable=True)
        body.setFont(body_font())
        body.setFixedWidth(measure_text(text, BUBBLE_TEXT_MAX))
        inner.addWidget(body)
        row.addWidget(bubble)


class AssistantMessage(QWidget):
    """AI 的发言：左对齐，头一行是角色名（带色点），下面是正文。

    流式输出靠 append() 往正文里追加，所以正文是独立的 QLabel。
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
        mark.setPixmap(icons.dots(color, 12))
        mark.setFixedSize(12, 12)
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
    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 1, 0, 1)
        line = label(text, "faint", wrap=True)
        layout.addWidget(line)
        layout.addStretch(1)


class SystemMessage(QWidget):
    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 6, 0, 6)
        line = label(text, "faint", wrap=True)
        layout.addWidget(line)
        layout.addStretch(1)


class NoticeMessage(QWidget):
    """带一个动作按钮的提示。width 不为空时整体限宽并按可用空间折行。"""

    def __init__(self, text: str, action_text: str, on_action,
                 width: int = None, parent=None):
        super().__init__(parent)
        frame = QFrame()
        frame.setStyleSheet(
            "QFrame { background: %s; border: 1px solid %s; border-radius: 14px; }"
            % (theme.SURFACE, theme.BORDER))
        inner = QHBoxLayout(frame)
        inner.setContentsMargins(16, 12, 12, 12)
        inner.setSpacing(10)
        body = label(text, "dim", wrap=True)
        if width:
            self.setFixedWidth(width)
            body.setFixedWidth(max(120, width - 170))
        inner.addWidget(body, stretch=1)
        inner.addWidget(button(action_text, "primary", on_action))
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 8, 0, 8)
        outer.addWidget(frame)


class CenteredPane(QWidget):
    """让内部控件水平居中并限宽。

    注意：不能用 addStretch 居中 —— QHBoxLayout 会把可用宽度按 stretch 因子
    平分，几个 stretch=1 就会把内容挤成 1/3 宽。所以这里在 resize 时算实际宽度。
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

    def resizeEvent(self, event):
        super().resizeEvent(event)
        available = max(280, self.viewport().width() - 48)
        self.column.setFixedWidth(min(theme.CHAT_MAX_WIDTH, available))

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

    def clear(self):
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


# ── 左侧图标栏 ─────────────────────────────────────────────────
class IconRail(QWidget):
    """76px 窄图标栏（仿 ChatGPT 桌面版）。

    和主区同色，靠"选中项有个圆角亮块"来指示，不是靠色差。
    """

    new_chat = Signal()
    open_history = Signal()
    open_config = Signal()
    open_output = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Rail")
        # QWidget 的子类默认不绘制 QSS 背景，必须显式打开
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedWidth(theme.RAIL_WIDTH)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(6)

        self.home_btn = icon_button(icons.plus(theme.TEXT, 20), "新对话",
                                    self.new_chat.emit, checkable=True)
        self.home_btn.setChecked(True)
        root.addWidget(self.home_btn, alignment=Qt.AlignHCenter)

        root.addWidget(icon_button(icons.clock(theme.TEXT_DIM, 20), "历史记录",
                                   self.open_history.emit), alignment=Qt.AlignHCenter)
        root.addWidget(icon_button(icons.people(theme.TEXT_DIM, 20), "团队成员与配置",
                                   self.open_config.emit), alignment=Qt.AlignHCenter)
        root.addWidget(icon_button(icons.folder(theme.TEXT_DIM, 20), "打开 AI 产出文件夹",
                                   self.open_output.emit), alignment=Qt.AlignHCenter)

        self.more_btn = icon_button(icons.dots(theme.TEXT_DIM, 20), "更多")
        menu = QMenu(self)
        menu.addAction("导出诊断包（含日志，已脱敏）", self._emit_more)
        menu.addAction("打开日志文件夹", self._emit_more)
        self.more_btn.setMenu(menu)
        root.addWidget(self.more_btn, alignment=Qt.AlignHCenter)

        root.addStretch(1)

        root.addWidget(icon_button(icons.sliders(theme.TEXT_DIM, 20), "设置",
                                   self.open_config.emit), alignment=Qt.AlignHCenter)

    def _emit_more(self):
        self.open_output.emit()

    def set_active(self, name: str):
        self.home_btn.setChecked(name == "home")


# ── 底部输入区 ─────────────────────────────────────────────────
class Composer(QFrame):
    """一大块圆角输入面板：上面一行输入，下面一行控制。

    仿 ChatGPT 桌面版那个大输入框 —— 它是画面里最大的实体，
    placeholder 在上、工具行在下，右侧一个白色圆形发送钮。
    """

    submitted = Signal(str)
    stop_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Composer")
        self.setProperty("focused", "false")
        self.running = False

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 16, 12)
        root.setSpacing(10)

        self.input = QLineEdit()
        self.input.setPlaceholderText("给团队发个任务…")
        self.input.returnPressed.connect(self._submit)
        root.addWidget(self.input)

        controls = QHBoxLayout()
        controls.setSpacing(8)

        self.new_btn = QPushButton()
        self.new_btn.setIcon(QIcon(icons.plus(theme.TEXT_DIM, 18)))
        self.new_btn.setIconSize(icons.plus(theme.TEXT_DIM, 18).size())
        self.new_btn.setFixedSize(30, 30)
        self.new_btn.setToolTip("新对话")
        controls.addWidget(self.new_btn)

        self.team_label = label("", "dim")
        controls.addWidget(self.team_label)
        controls.addStretch(1)

        self.send_btn = QPushButton()
        self.send_btn.setObjectName("SendButton")
        self.send_btn.setIcon(QIcon(icons.arrow_up(theme.ACCENT_TEXT, 18)))
        self.send_btn.setIconSize(icons.arrow_up(theme.ACCENT_TEXT, 18).size())
        self.send_btn.setToolTip("发送")
        self.send_btn.clicked.connect(self._submit)
        controls.addWidget(self.send_btn)

        self.stop_btn = QPushButton()
        self.stop_btn.setObjectName("StopButton")
        self.stop_btn.setIcon(QIcon(icons.square_stop(theme.ACCENT_TEXT, 16)))
        self.stop_btn.setIconSize(icons.square_stop(theme.ACCENT_TEXT, 16).size())
        self.stop_btn.setToolTip("停止")
        self.stop_btn.clicked.connect(self.stop_requested.emit)
        self.stop_btn.hide()
        controls.addWidget(self.stop_btn)

        root.addLayout(controls)
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

    def set_team_text(self, text: str):
        self.team_label.setText(text)

    def clear(self):
        self.input.clear()


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
        heading = label("添加角色" if self.is_new else "编辑角色", "title")
        heading.setStyleSheet("font-size: 13pt; font-weight: 600;")
        root.addWidget(heading)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        form = QFormLayout(inner)
        form.setSpacing(11)

        field_qss = ("background: %s; border: 1px solid %s; border-radius: 9px;"
                     "padding: 8px 11px;" % (theme.SURFACE, theme.BORDER))

        self.name_edit = QLineEdit(self.role.get("name", ""))
        self.name_edit.setStyleSheet("QLineEdit { %s }" % field_qss)
        self.name_edit.setPlaceholderText("例如：经理 / 策划 / 唱反调")
        form.addRow("名称", self.name_edit)

        self.color_box = QComboBox()
        for value in theme.ROLE_COLORS:
            self.color_box.addItem(QIcon(icons.dots(value, 12)), value, value)
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
        self.base_edit.setStyleSheet("QLineEdit { %s }" % field_qss)
        self.base_edit.setPlaceholderText("例如 https://api.deepseek.com/v1")
        form.addRow("Base URL", self.base_edit)

        self.key_edit = QLineEdit(self.role.get("api_key", ""))
        self.key_edit.setStyleSheet("QLineEdit { %s }" % field_qss)
        self.key_edit.setEchoMode(QLineEdit.Password)
        self.key_edit.setPlaceholderText("自定义来源才需要；会加密保存")
        form.addRow("API Key", self.key_edit)

        self.prompt_edit = QPlainTextEdit(self.role.get("system_prompt", ""))
        self.prompt_edit.setMinimumHeight(110)
        self.prompt_edit.setStyleSheet("QPlainTextEdit { %s }" % field_qss)
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
            item.setIcon(QIcon(icons.dots(preset["color"], 12)))
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
        heading = label("配置", "title")
        heading.setStyleSheet("font-size: 13pt; font-weight: 600;")
        head.addWidget(heading)
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
            item.setIcon(QIcon(icons.dots(role_color(role), 12)))
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


# ── 历史记录 ───────────────────────────────────────────────────
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


class HistoryPanel(QDialog):
    """历史记录面板（图标栏那个时钟图标打开它）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("历史记录")
        self.setMinimumSize(560, 620)
        self.items = []
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(10)
        heading = label("历史记录", "title")
        heading.setStyleSheet("font-size: 13pt; font-weight: 600;")
        root.addWidget(heading)
        self.list_widget = QListWidget()
        self.list_widget.itemClicked.connect(self._on_clicked)
        root.addWidget(self.list_widget, stretch=1)
        self.count_label = label("", "faint", wrap=True)
        root.addWidget(self.count_label)
        row = QHBoxLayout()
        row.addWidget(button("打开记录文件夹", "tool", self._open_folder))
        row.addStretch(1)
        row.addWidget(button("关闭", on_click=self.reject))
        root.addLayout(row)
        self._load()

    def _open_folder(self):
        folder = app_config.history_dir()
        os.makedirs(folder, exist_ok=True)
        open_in_explorer(folder)

    def _load(self):
        self.items = list_history()
        self.list_widget.clear()
        for item in self.items:
            task = item["task"][:30] + ("…" if len(item["task"]) > 30 else "")
            row = QListWidgetItem("%s\n%s" % (item["time"], task))
            row.setData(Qt.UserRole, item["file"])
            self.list_widget.addItem(row)
        self.count_label.setText("共 %d 条记录 · %s" % (len(self.items), app_config.history_dir()))

    def _on_clicked(self, item):
        path = item.data(Qt.UserRole)
        if path:
            self.selected_path = path
            self.accept()

    selected_path = ""


# ── 主窗口 ─────────────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self, load_result: LoadResult = None):
        super().__init__()
        self.load_result = load_result or load_settings()
        self.settings = self.load_result.settings
        self.session = None
        self.cur_task = ""
        self.cur_messages = []
        self._streaming = None
        self._stream_name = ""
        self._stream_color = theme.TEXT
        self._reading_history = False

        self.setWindowTitle("AI 团队群聊")
        self.setMinimumSize(940, 660)
        self._set_icon()
        self._build_ui()
        self._apply_default_geometry()
        self._register_secrets()
        self._start_fresh_view()

    def _apply_default_geometry(self):
        """按屏幕比例给一个像样的默认尺寸并居中。

        不这么做的话 Qt 会直接用布局 sizeHint，那个值恰好贴着 setMinimumSize，
        窗口开出来又小又挤在左上角。
        """
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        width = max(self.minimumWidth(), min(1280, int(available.width() * 0.82)))
        height = max(self.minimumHeight(), min(900, int(available.height() * 0.88)))
        self.resize(min(width, available.width()), min(height, available.height()))
        frame = self.frameGeometry()
        frame.moveCenter(available.center())
        self.move(frame.topLeft())

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

        self.rail = IconRail()
        self.rail.new_chat.connect(self.start_new_conversation)
        self.rail.open_history.connect(self.open_history)
        self.rail.open_config.connect(self.open_config)
        self.rail.open_output.connect(lambda: open_in_explorer(app_config.documents_dir()))
        root.addWidget(self.rail)

        content = QWidget()
        content.setObjectName("Content")
        column = QVBoxLayout(content)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        self.column = column

        # 布局骨架：弹簧 / 空状态 / 消息区 / 输入区 / 弹簧
        # 空状态时两个弹簧都撑开，把「大标题 + 输入框 + 工具行」顶到竖直居中；
        # 开始对话后上弹簧收掉、消息区撑开，输入框自然落到底部。
        column.addStretch(1)
        self._i_stretch_top = column.count() - 1

        self.empty_block = QWidget()
        self.empty_layout = QVBoxLayout(self.empty_block)
        self.empty_layout.setContentsMargins(24, 0, 24, 0)
        self.empty_layout.setSpacing(0)
        column.addWidget(self.empty_block)

        self.area = MessageArea()
        column.addWidget(self.area, stretch=1)
        self._i_area = column.count() - 1

        self._build_composer_area(column)
        self._i_bottom = column.count() - 1

        column.addStretch(1)
        self._i_stretch_bottom = column.count() - 1

        root.addWidget(content, stretch=1)
        self.setCentralWidget(central)

    def _build_composer_area(self, column):
        holder = QWidget()
        holder_layout = QVBoxLayout(holder)
        holder_layout.setContentsMargins(0, 6, 0, 14)
        holder_layout.setSpacing(8)

        inner = QWidget()
        inner_layout = QVBoxLayout(inner)
        inner_layout.setContentsMargins(0, 0, 0, 0)
        inner_layout.setSpacing(8)

        self.composer = Composer()
        self.composer.submitted.connect(self.send_task)
        self.composer.stop_requested.connect(self.stop)
        self.composer.new_btn.clicked.connect(self.start_new_conversation)
        inner_layout.addWidget(self.composer)

        # 输入框下方那排小工具（仿 ChatGPT 的 文件 / 插件 那一行）
        tool_row = QFrame()
        tool_row.setObjectName("ToolRow")
        tools = QHBoxLayout(tool_row)
        tools.setContentsMargins(14, 6, 14, 6)
        tools.setSpacing(4)
        tools.addWidget(button("AI 产出文件夹", "tool",
                               lambda: open_in_explorer(app_config.documents_dir())))
        tools.addWidget(button("历史记录", "tool", self.open_history))
        tools.addWidget(button("配置角色", "tool", self.open_config))
        tools.addStretch(1)
        self.status = label("就绪", "faint")
        tools.addWidget(self.status)
        inner_layout.addWidget(tool_row)

        pane = CenteredPane(inner, margin=24)
        holder_layout.addWidget(pane)
        column.addWidget(holder)

    def _refresh_team_label(self):
        roles = app_config.enabled_roles(self.settings)
        names = "、".join(r.get("name") or "?" for r in roles)
        self.composer.set_team_text("%d 个角色 · %s" % (len(roles), names))

    # ── 空状态 / 对话中 两种骨架 ──
    def _set_empty_layout(self, empty: bool):
        self.empty_block.setVisible(empty)
        self.area.setVisible(not empty)
        self.column.setStretch(self._i_stretch_top, 1 if empty else 0)
        self.column.setStretch(self._i_stretch_bottom, 1 if empty else 0)
        self.column.setStretch(self._i_area, 0 if empty else 1)

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def _build_empty_state(self):
        """空状态：一句大标题 + 缺配置时的提示条。

        输入框不在这里 —— 它在同一条竖直布局里紧跟其后，靠弹簧一起居中。
        """
        self._clear_layout(self.empty_layout)

        heading = label("我们要做什么？", "heading")
        heading.setAlignment(Qt.AlignCenter)
        self.empty_layout.addWidget(heading)
        self.empty_layout.addSpacing(26)

        problems = self.load_result.problems
        if problems:
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.addStretch(1)
            notice = NoticeMessage(
                "还差 %d 项就能开始了：%s" % (len(problems), "；".join(problems[:2])),
                "去配置", self.open_config, width=min(620, theme.CONTENT_MAX_WIDTH))
            row.addWidget(notice)
            row.addStretch(1)
            self.empty_layout.addLayout(row)

    def _start_fresh_view(self):
        self._refresh_team_label()
        self.area.clear()
        self._build_empty_state()
        self._set_empty_layout(True)
        self.rail.set_active("home")
        if self.load_result.recovered:
            self.status.setText("配置损坏，已恢复默认")
        elif self.load_result.notes:
            self.status.setText(self.load_result.notes[0])
        else:
            self.status.setText("就绪")
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
            self._set_empty_layout(False)
            self.cur_task = task
            self.cur_messages = [{"kind": "user", "name": "我", "content": task}]

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
        self.status.setText("正在停止…")
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
        self._start_fresh_view()

    # ── 历史 ──
    def open_history(self):
        if self.composer.running:
            QMessageBox.information(self, "正在讨论中", "先停止当前讨论，再看历史。")
            return
        panel = HistoryPanel(self)
        if panel.exec() == QDialog.Accepted and panel.selected_path:
            self.open_history_item(panel.selected_path)

    def open_history_item(self, path: str):
        data = load_history_file(path)
        if not data:
            return
        self._save_cur_history(ending="用户去看了历史记录")
        self._reading_history = True
        self.composer.set_running(False)
        self.composer.input.setEnabled(False)
        self.area.clear()
        self._set_empty_layout(False)
        self.area.add_system("这是 %s 的历史记录（只读）。点左侧「＋」回到新对话。"
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
        self.status.setText("正在查看历史记录（只读）")
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
            self.cur_messages.append({"kind": "msg", "name": self._stream_name or "",
                                      "content": final_text,
                                      "color": self._stream_color or theme.TEXT})
        self._streaming = None

    def _on_message(self, cn_name, source, content):
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

    def _on_turn_stopped(self, context_lost):
        self.area.add_system("已强制停止，上下文已重置 —— 下一次发言会开新对话。"
                             if context_lost else
                             "已停止，上下文保留，可以直接接着追问。")
        self._save_cur_history(ending="用户手动停止了讨论")
        self._reset_ui("已停止")

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
            self._build_empty_state()
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
