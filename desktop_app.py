# -*- coding: utf-8 -*-
"""AI 团队群聊 · 桌面版 —— 主程序（界面与交互）。

架构
----
    desktop_app.py   界面与交互（本文件）
    theme.py         深色玻璃质感主题
    team_session.py  会话：多轮追问 / 流式输出 / 优雅停止
    llm.py           模型客户端构造与连接测试
    app_config.py    配置、角色列表、校验、损坏恢复
    secret_store.py  密钥加密（Windows DPAPI）
    app_logging.py   日志、脱敏、诊断包
    tools.py         AI 的"手臂"：搜索 / 文件 / GitHub / 命令

设计取向
--------
**不搞教程式向导**。角色是一个可以自由增删改的列表：想加几个 AI 就加几个，
每个角色独立配名称、颜色、模型来源、凭据、人设和工具，发言顺序就是列表顺序。
配置没配好时不弹教程，只在顶部挂一条可关闭的提示条，点「去配置」直接进配置面板。
"""
import datetime
import json
import os
import sys

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox,
                               QDialog, QDialogButtonBox, QFormLayout, QFrame,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMainWindow, QMenu, QMessageBox,
                               QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy,
                               QSpinBox, QStackedWidget, QTextBrowser, QVBoxLayout,
                               QWidget)

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


def label(text, role="", wrap=False) -> QLabel:
    widget = QLabel(text)
    if role:
        widget.setProperty("role", role)
    widget.setWordWrap(wrap)
    return widget


def button(text, role="", on_click=None) -> QPushButton:
    widget = QPushButton(text)
    if role:
        widget.setProperty("role", role)
    if on_click:
        widget.clicked.connect(on_click)
    return widget


def panel(framed=True) -> QFrame:
    frame = QFrame()
    frame.setProperty("panel", "true" if framed else "flat")
    return frame


def color_dot(color: str, size: int = 10) -> QLabel:
    dot = QLabel()
    dot.setFixedSize(size, size)
    dot.setStyleSheet("background: %s; border-radius: %dpx;" % (color, size // 2))
    return dot


# ── 模型连通性测试 ─────────────────────────────────────────────
class TestWorker(QThread):
    """后台逐个测试角色能否连通。真的发请求，别把界面卡住。"""

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
            self.progress.emit(role.get("name") or role.get("id") or "?", ok, message)
        self.finished_all.emit(passed, total)


# ── 角色编辑对话框 ─────────────────────────────────────────────
class RoleDialog(QDialog):
    """编辑单个角色。改的是传入的 dict 的副本，确认后才由调用方写回。"""

    def __init__(self, role: dict, settings: dict, parent=None, is_new=False):
        super().__init__(parent)
        self.role = dict(role)
        self.settings = settings
        self.is_new = is_new
        self.setWindowTitle("添加角色" if is_new else "编辑角色")
        self.setMinimumSize(620, 620)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(12)

        head = QHBoxLayout()
        head.addWidget(color_dot(self.role.get("color", theme.ACCENT), 12))
        head.addWidget(label("角色设置", "title"))
        head.addStretch(1)
        root.addLayout(head)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        form = QFormLayout(inner)
        form.setSpacing(10)

        self.name_edit = QLineEdit(self.role.get("name", ""))
        self.name_edit.setPlaceholderText("例如：经理 / 策划 / 唱反调")
        form.addRow("名称：", self.name_edit)

        color_row = QHBoxLayout()
        self.color_box = QComboBox()
        for value in theme.ROLE_COLORS:
            self.color_box.addItem("●", value)
            self.color_box.setItemData(self.color_box.count() - 1,
                                       QColor(value), Qt.DecorationRole)
        index = self.color_box.findData(self.role.get("color"))
        self.color_box.setCurrentIndex(index if index >= 0 else 0)
        color_row.addWidget(self.color_box)
        color_row.addStretch(1)
        color_wrap = QWidget()
        color_wrap.setLayout(color_row)
        form.addRow("颜色：", color_wrap)

        self.source_box = QComboBox()
        for key in ("zhipu", "ollama", "custom"):
            self.source_box.addItem(SOURCE_LABELS[key], key)
        self.source_box.setCurrentIndex(
            max(0, self.source_box.findData(self.role.get("source", "zhipu"))))
        self.source_box.currentIndexChanged.connect(self._on_source_changed)
        form.addRow("模型来源：", self.source_box)

        self.model_box = QComboBox()
        self.model_box.setEditable(True)
        form.addRow("模型：", self.model_box)

        self.base_edit = QLineEdit(self.role.get("base_url", ""))
        self.base_edit.setPlaceholderText("例如 https://api.deepseek.com/v1")
        self.base_row = self.base_edit
        form.addRow("Base URL：", self.base_edit)

        self.key_edit = QLineEdit(self.role.get("api_key", ""))
        self.key_edit.setEchoMode(QLineEdit.Password)
        self.key_edit.setPlaceholderText("自定义来源才需要；会加密保存")
        form.addRow("API Key：", self.key_edit)

        self.prompt_edit = QPlainTextEdit(self.role.get("system_prompt", ""))
        self.prompt_edit.setPlaceholderText("这个角色的职责与说话风格……")
        self.prompt_edit.setMinimumHeight(110)
        form.addRow("人设提示词：", self.prompt_edit)

        # 工具：这个角色能用的"手臂"
        tools_box = QFrame()
        tools_box.setProperty("panel", "flat")
        tools_layout = QVBoxLayout(tools_box)
        tools_layout.setContentsMargins(12, 10, 12, 10)
        tools_layout.setSpacing(6)
        tools_layout.addWidget(label("可用工具", "section"))
        self.tool_checks = {}
        current_tools = set(self.role.get("tools") or [])
        for name, tool_label, desc in TOOL_CATALOG:
            check = QCheckBox("%s —— %s" % (tool_label, desc))
            check.setChecked(name in current_tools)
            self.tool_checks[name] = check
            tools_layout.addWidget(check)
        form.addRow("", tools_box)

        self.enabled_check = QCheckBox("参与讨论")
        self.enabled_check.setChecked(self.role.get("enabled", True))
        form.addRow("", self.enabled_check)

        scroll.setWidget(inner)
        root.addWidget(scroll, stretch=1)

        self.error_label = label("", "hint", wrap=True)
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
        source = self.source_box.currentData()
        is_custom = source == "custom"
        self.base_edit.setVisible(is_custom)
        self.key_edit.setVisible(is_custom)
        label_for_base = self.base_edit.parentWidget()
        del label_for_base
        self._fill_models(keep=self.model_box.currentText())

    def collect(self) -> dict:
        role = dict(self.role)
        role["name"] = self.name_edit.text().strip() or role.get("id") or "角色"
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


# ── 添加角色：选预设 ───────────────────────────────────────────
class PresetDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("添加角色")
        self.setMinimumSize(480, 480)
        self.chosen = None

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(10)
        root.addWidget(label("挑一个起点", "title"))
        root.addWidget(label("选个预设，进去之后随便改。也可以从空白角色开始。", "hint", wrap=True))

        self.list_widget = QListWidget()
        self.list_widget.itemDoubleClicked.connect(lambda _i: self._choose())
        for preset in ROLE_PRESETS:
            item = QListWidgetItem("%s   %s" % (preset["name"], preset["prompt"][:34] + "…"))
            item.setData(Qt.UserRole, preset["key"])
            item.setForeground(QColor(preset["color"]))
            self.list_widget.addItem(item)
        blank = QListWidgetItem("空白角色   自己写人设，从零开始")
        blank.setData(Qt.UserRole, "__blank__")
        blank.setForeground(QColor(theme.TEXT_DIM))
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
        if item is None:
            return
        self.chosen = item.data(Qt.UserRole)
        self.accept()


# ── 配置面板（角色列表 + 共享设置）─────────────────────────────
class ConfigDialog(QDialog):
    """配置面板。

    角色是一个可增删改的列表 —— 仿 DSH 的 Skills/MCP 管理那种"表格 + 增删改"，
    而不是让用户跟着向导一步步走。发言顺序就是列表顺序。
    """

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("配置")
        self.setMinimumSize(820, 660)
        self._worker = None
        self._build()
        self._reload()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(12)

        head = QHBoxLayout()
        head.addWidget(label("配置", "title"))
        head.addStretch(1)
        self.test_btn = button("测试全部", on_click=self._on_test)
        head.addWidget(self.test_btn)
        root.addLayout(head)
        root.addWidget(label("角色按列表顺序轮流发言。每个角色的模型、凭据、人设、工具都可以单独设。",
                             "hint", wrap=True))

        body = QHBoxLayout()
        body.setSpacing(12)

        # 左：角色列表
        left = QVBoxLayout()
        left.setSpacing(8)
        left.addWidget(label("角色（发言顺序）", "section"))
        self.role_list = QListWidget()
        self.role_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.role_list.itemDoubleClicked.connect(lambda _i: self._edit_role())
        self.role_list.currentRowChanged.connect(self._on_select)
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
        left_wrap.setFixedWidth(340)
        body.addWidget(left_wrap)

        # 右：共享设置
        right = QVBoxLayout()
        right.setSpacing(10)

        zhipu = panel()
        zhipu_layout = QVBoxLayout(zhipu)
        zhipu_layout.setContentsMargins(14, 12, 14, 12)
        zhipu_layout.setSpacing(8)
        zhipu_layout.addWidget(label("智谱 GLM 共享凭据", "section"))
        zhipu_layout.addWidget(label("所有用智谱的角色共用这一份，不用每个角色填一遍。",
                                     "hint", wrap=True))
        zhipu_form = QFormLayout()
        shared = self.settings.setdefault("shared", {})
        self.zhipu_key = QLineEdit(shared.get("zai_api_key", ""))
        self.zhipu_key.setEchoMode(QLineEdit.Password)
        self.zhipu_key.setPlaceholderText("在 open.bigmodel.cn 或 api.z.ai 申请")
        zhipu_form.addRow("API Key：", self.zhipu_key)
        self.zhipu_base = QComboBox()
        self.zhipu_base.addItem("国内站 open.bigmodel.cn", ZHIPU_BASE_CN)
        self.zhipu_base.addItem("国际站 api.z.ai", ZHIPU_BASE_INTL)
        index = self.zhipu_base.findData(shared.get("zai_base_url") or ZHIPU_BASE_INTL)
        self.zhipu_base.setCurrentIndex(index if index >= 0 else 1)
        zhipu_form.addRow("接口地址：", self.zhipu_base)
        zhipu_layout.addLayout(zhipu_form)
        zhipu_layout.addWidget(label("两个站点的 Key 互不通用，申请哪个就选哪个。", "hint", wrap=True))
        right.addWidget(zhipu)

        misc = panel()
        misc_layout = QVBoxLayout(misc)
        misc_layout.setContentsMargins(14, 12, 14, 12)
        misc_layout.setSpacing(8)
        misc_layout.addWidget(label("讨论", "section"))
        misc_form = QFormLayout()
        self.max_messages = QSpinBox()
        self.max_messages.setRange(2, 200)
        self.max_messages.setValue(int(self.settings.get("max_messages") or 18))
        self.max_messages.setSuffix("  条消息")
        misc_form.addRow("单轮上限：", self.max_messages)
        misc_layout.addLayout(misc_form)
        misc_layout.addWidget(label("达到上限或评审说出 APPROVE 就结束本轮。", "hint", wrap=True))
        right.addWidget(misc)

        self.problems = label("", "hint", wrap=True)
        right.addWidget(self.problems)
        right.addStretch(1)
        body.addLayout(right, stretch=1)
        root.addLayout(body, stretch=1)

        self.test_label = label("", "hint", wrap=True)
        root.addWidget(self.test_label)

        buttons = QDialogButtonBox()
        save = buttons.addButton("保存", QDialogButtonBox.AcceptRole)
        save.setProperty("role", "primary")
        buttons.addButton("取消", QDialogButtonBox.RejectRole)
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    # ── 列表 ──
    def _reload(self, select=None):
        self.role_list.blockSignals(True)
        self.role_list.clear()
        for role in self.settings.get("roles") or []:
            enabled = role.get("enabled", True)
            source = SOURCE_SHORT.get(role.get("source", ""), "?")
            text = "%s  ·  %s · %s" % (role.get("name") or "?", source,
                                       role.get("model") or "未选模型")
            if not enabled:
                text += "   （已停用）"
            item = QListWidgetItem(text)
            item.setForeground(QColor(role.get("color") or theme.TEXT) if enabled
                               else QColor(theme.TEXT_FAINT))
            self.role_list.addItem(item)
        self.role_list.blockSignals(False)
        if self.role_list.count():
            row = 0 if select is None else max(0, min(select, self.role_list.count() - 1))
            self.role_list.setCurrentRow(row)
        self._refresh_problems()

    def _current_index(self) -> int:
        return self.role_list.currentRow()

    def _current_role(self):
        index = self._current_index()
        roles = self.settings.get("roles") or []
        if 0 <= index < len(roles):
            return roles[index]
        return None

    def _on_select(self, _row):
        role = self._current_role()
        if role:
            self.role_list.setToolTip((role.get("system_prompt") or "")[:300])

    def _add_role(self):
        picker = PresetDialog(self)
        if picker.exec() != QDialog.Accepted or not picker.chosen:
            return
        roles = self.settings.setdefault("roles", [])
        if picker.chosen == "__blank__":
            role = app_config.make_role("__blank__", len(roles))
        else:
            role = app_config.make_role(picker.chosen, len(roles))
        role["id"] = app_config.unique_role_id(self.settings, role["id"])
        # 新角色的来源跟随第一个角色的常见选择，省得每次都改
        editor = RoleDialog(role, self.settings, self, is_new=True)
        if editor.exec() != QDialog.Accepted:
            return
        roles.append(editor.role)
        self._reload(len(roles) - 1)

    def _edit_role(self):
        role = self._current_role()
        if role is None:
            return
        index = self._current_index()
        editor = RoleDialog(role, self.settings, self)
        if editor.exec() == QDialog.Accepted:
            self.settings["roles"][index] = editor.role
            self._reload(index)

    def _delete_role(self):
        index = self._current_index()
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
        index = self._current_index()
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
        self._reload(self._current_index())

    # ── 共享设置 ──
    def _refresh_problems(self):
        self.settings.setdefault("shared", {})["zai_api_key"] = self.zhipu_key.text().strip()
        self.settings["shared"]["zai_base_url"] = self.zhipu_base.currentData()
        problems = app_config.validate_settings(self.settings)
        if problems:
            self.problems.setText("⚠ 还有 %d 项没配好：%s" % (len(problems), "；".join(problems[:3])))
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
                "%s %s：%s" % ("✅" if ok else "❌", cn, msg.splitlines()[0][:110])))
        self._worker.finished_all.connect(self._on_test_done)
        self._worker.start()

    def _on_test_done(self, passed, total):
        self.test_btn.setEnabled(True)
        self.test_label.setText("测试完成：%d/%d 个角色可用。%s"
                                % (passed, total, "" if passed == total
                                   else "不可用的角色请检查来源与凭据。"))

    def _on_save(self):
        self.collect()
        problems = app_config.validate_settings(self.settings)
        if problems:
            answer = QMessageBox.question(
                self, "配置还不完整",
                "还有 %d 项没配好：\n\n%s\n\n仍然保存吗？" % (len(problems), "\n".join(problems[:6])))
            if answer != QMessageBox.Yes:
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


class HistoryDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("历史记录")
        self.resize(940, 620)
        self.items = []
        self._build()

    def _build(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        left = QVBoxLayout()
        left.setSpacing(8)
        left.addWidget(label("历史记录", "section"))
        self.list_widget = QListWidget()
        self.list_widget.currentRowChanged.connect(self._show_item)
        left.addWidget(self.list_widget, stretch=1)
        self.count_label = label("", "hint", wrap=True)
        left.addWidget(self.count_label)
        left.addWidget(button("打开记录文件夹", on_click=self._open_folder))
        left_wrap = QWidget()
        left_wrap.setLayout(left)
        left_wrap.setFixedWidth(330)
        root.addWidget(left_wrap)

        self.view = QTextBrowser()
        self.view.setObjectName("Chat")
        self.view.setOpenLinks(False)
        root.addWidget(self.view, stretch=1)
        self._load()

    def _open_folder(self):
        folder = app_config.history_dir()
        os.makedirs(folder, exist_ok=True)
        open_in_explorer(folder)

    def _load(self):
        self.items = list_history()
        self.list_widget.clear()
        for item in self.items:
            task = item["task"][:28] + ("…" if len(item["task"]) > 28 else "")
            self.list_widget.addItem("%s\n%s" % (item["time"], task))
        self.count_label.setText("共 %d 条\n%s" % (len(self.items), app_config.history_dir()))
        if self.items:
            self.list_widget.setCurrentRow(0)

    def _show_item(self, row):
        if row < 0 or row >= len(self.items):
            return
        try:
            with open(self.items[row]["file"], "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            self.view.setPlainText("（记录读取失败）")
            return
        self.view.clear()
        self._append("📝 任务：" + data.get("task", ""), theme.CHAT_USER, bold=True)
        meta = data.get("meta")
        if meta:
            if isinstance(meta, list):
                summary = "、".join("%s=%s" % (m.get("name"), m.get("model")) for m in meta[:6])
            else:
                summary = "、".join("%s=%s" % (k, (v or {}).get("model") or "?")
                                   for k, v in list(meta.items())[:6])
            self._append("🧩 当时配置：" + summary, theme.CHAT_META, size=11)
        for msg in data.get("messages", []):
            kind = msg.get("kind", "")
            if kind == "user":
                self._append("📝 我的任务：" + msg.get("content", ""), theme.CHAT_USER, bold=True)
            elif kind == "msg":
                self._append("【%s】%s" % (msg.get("name", ""), msg.get("content", "")),
                             msg.get("color") or theme.CHAT_BODY, bold=True)
            elif kind == "tool":
                self._append("🔧 %s %s：%s" % (msg.get("name", ""), msg.get("phase", ""),
                                               msg.get("content", "")),
                             theme.CHAT_TOOL, italic=True, size=12)
            elif kind == "system":
                self._append("⚙️ " + msg.get("content", ""), theme.CHAT_SYS, italic=True)
        self.view.moveCursor(QTextCursor.Start)

    def _append(self, text, color, bold=False, italic=False, size=None):
        cursor = self.view.textCursor()
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        if bold:
            fmt.setFontWeight(QFont.Bold)
        if italic:
            fmt.setFontItalic(True)
        if size:
            fmt.setFontPointSize(size)
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(text, fmt)
        cursor.insertText("\n\n")


# ── 主窗口 ─────────────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self, load_result: LoadResult = None):
        super().__init__()
        self.load_result = load_result or load_settings()
        self.settings = self.load_result.settings
        self.session = None
        self.cur_task = ""
        self.cur_messages = []
        self._stream_pos = None
        self._stream_buf = ""
        self._stream_open = False
        self._stream_name = ""

        self.setWindowTitle("AI 团队群聊")
        self.setMinimumSize(920, 680)
        self._set_icon()
        self._build_ui()
        self._register_secrets()
        self._greet()

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
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        head = QHBoxLayout()
        head.setSpacing(8)
        title_col = QVBoxLayout()
        title_col.setSpacing(1)
        title_col.addWidget(label("AI 团队群聊", "title"))
        self.subtitle = label("", "subtitle")
        title_col.addWidget(self.subtitle)
        head.addLayout(title_col, stretch=1)

        head.addWidget(button("🧹 新会话", on_click=self.start_new_conversation))
        head.addWidget(button("⚙ 配置", "primary", self.open_config))
        head.addWidget(button("🕘 历史", on_click=self.open_history))

        self.more_btn = button("⋯")
        self.more_btn.setProperty("role", "icon")
        menu = QMenu(self)
        menu.addAction("导出诊断包（含日志，已脱敏）", self.export_diagnostics_action)
        menu.addAction("打开日志文件夹", lambda: open_in_explorer(app_config.logs_dir()))
        menu.addAction("打开 AI 产出文件夹", lambda: open_in_explorer(app_config.documents_dir()))
        self.more_btn.setMenu(menu)
        head.addWidget(self.more_btn)
        root.addLayout(head)

        # 配置不完整时的提示条（替代教程向导：只提示，不拦路）
        self.banner = QFrame()
        self.banner.setProperty("banner", "warn")
        banner_layout = QHBoxLayout(self.banner)
        banner_layout.setContentsMargins(12, 8, 8, 8)
        banner_layout.setSpacing(10)
        self.banner_label = label("", "hint", wrap=True)
        banner_layout.addWidget(self.banner_label, stretch=1)
        banner_layout.addWidget(button("去配置", "primary", self.open_config))
        close_btn = button("✕", "icon", self.banner.hide)
        banner_layout.addWidget(close_btn)
        self.banner.hide()
        root.addWidget(self.banner)

        self.chip_row = QHBoxLayout()
        self.chip_row.setSpacing(6)
        root.addLayout(self.chip_row)
        self._refresh_chips()

        self.chat_view = QTextBrowser()
        self.chat_view.setObjectName("Chat")
        self.chat_view.setOpenLinks(False)
        root.addWidget(self.chat_view, stretch=1)

        input_row = QHBoxLayout()
        input_row.setSpacing(8)
        self.task_input = QLineEdit()
        self.task_input.setPlaceholderText("说点什么…")
        self.task_input.returnPressed.connect(self.send)
        self.send_btn = button("发送", "primary", self.send)
        self.send_btn.setMinimumWidth(84)
        self.stop_btn = button("停止", "danger", self.stop)
        self.stop_btn.setEnabled(False)
        input_row.addWidget(self.task_input, stretch=1)
        input_row.addWidget(self.send_btn)
        input_row.addWidget(self.stop_btn)
        root.addLayout(input_row)

        self.status = label("就绪", "status")
        root.addWidget(self.status)
        self.setCentralWidget(central)

    def _refresh_chips(self):
        while self.chip_row.count():
            item = self.chip_row.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        roles = app_config.enabled_roles(self.settings)
        for role in roles:
            color = role.get("color") or theme.ACCENT
            source = SOURCE_SHORT.get(role.get("source", ""), "?")
            chip = QLabel(" %s · %s " % (role.get("name") or "?", source))
            chip.setStyleSheet(
                "background: %s; color: %s; border: 1px solid %s;"
                "border-radius: 11px; padding: 3px 10px; font-size: 11.5px;"
                % (_rgba(color, 0.16), color, _rgba(color, 0.4)))
            chip.setToolTip("%s\n模型：%s" % (role.get("system_prompt", "")[:200],
                                            role.get("model") or "未选"))
            self.chip_row.addWidget(chip)
        self.chip_row.addStretch(1)
        self.subtitle.setText("%d 个角色 · 轮流发言 · 可以一直追问" % len(roles))

    def _greet(self):
        if self.load_result.recovered:
            self._append_system("上次的配置文件损坏了，已备份为 %s 并恢复默认配置。"
                                % os.path.basename(self.load_result.backup_path or "备份文件"))
        for note in self.load_result.notes:
            self._append_system(note)
        problems = self.load_result.problems
        if problems:
            self.banner_label.setText("还有 %d 项没配好：%s"
                                      % (len(problems), "；".join(problems[:3])))
            self.banner.show()
            self._append_system("配置还没完成，点上方「去配置」填好模型和密钥就能开始了。")
        else:
            self._append_system("已就绪。输入任务开始，之后可以继续追问，上下文会一直保留。")

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

    def send(self):
        task = self.task_input.text().strip()
        if not task:
            self.status.setText("先输入点什么")
            return
        if self.stop_btn.isEnabled():
            self.status.setText("正在讨论中，先停止或等它跑完")
            return

        session = self._ensure_session()
        is_followup = session.has_context
        if not is_followup:
            self.chat_view.clear()
            self.cur_task = task
            self.cur_messages = [{"kind": "user", "name": "我", "content": task}]

        self.task_input.clear()
        self.task_input.setEnabled(False)
        self.send_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.status.setText("追问中…" if is_followup else "讨论中…")
        self._append_user(task, followup=is_followup)
        if not session.ask(task):
            self._on_turn_error("会话线程没有就绪，请重试或重启程序。")

    def stop(self):
        if self.session is None or not self.stop_btn.isEnabled():
            return
        self.stop_btn.setEnabled(False)
        self.status.setText("正在停止…（等当前发言收尾）")
        self.session.stop()

    def start_new_conversation(self):
        if self.stop_btn.isEnabled():
            QMessageBox.information(self, "正在讨论中", "先停止当前讨论，再开新会话。")
            return
        self._save_cur_history(ending="用户开了新会话")
        if self.session is not None:
            self.session.new_conversation()
        self.chat_view.clear()
        self._append_system("已开新会话，之前的上下文已清空。")
        self._update_input_hint()

    def _update_input_hint(self):
        has_context = self.session is not None and self.session.has_context
        self.task_input.setPlaceholderText(
            "继续追问…" if has_context else "说点什么…")

    # ── 会话信号 ──
    def _on_session_ready(self):
        log.info("会话已就绪")
        self._update_input_hint()

    def _on_message(self, cn_name, source, content):
        self._finish_stream_block()
        self._insert_speaker(cn_name, source)
        cursor = self.chat_view.textCursor()
        cursor.movePosition(QTextCursor.End)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(theme.CHAT_BODY))
        cursor.insertText(content, fmt)
        self._scroll_to_bottom()
        self.cur_messages.append({"kind": "msg", "name": cn_name,
                                  "content": content, "color": self._role_color(source)})

    def _on_stream_start(self, cn_name, color):
        self._finish_stream_block()
        self._stream_name = cn_name
        self._stream_buf = ""
        self._stream_open = True
        sticky = self._at_bottom()

        self.chat_view.append("")
        cursor = self.chat_view.textCursor()
        cursor.movePosition(QTextCursor.End)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        fmt.setFontWeight(QFont.Bold)
        cursor.insertText("%s  " % cn_name, fmt)
        self._stream_pos = cursor.position()
        if sticky:
            self._scroll_to_bottom()

    def _on_stream_chunk(self, chunk):
        if not self._stream_open:
            return
        self._stream_buf += chunk
        self._render_stream(self._stream_buf)

    def _on_stream_end(self, final_text):
        if not self._stream_open:
            return
        self._render_stream(final_text)
        self._stream_open = False
        self._stream_pos = None
        if final_text.strip():
            self.cur_messages.append({"kind": "msg", "name": self._stream_name,
                                      "content": final_text,
                                      "color": self._role_color_by_name(self._stream_name)})
        self._stream_buf = ""

    def _render_stream(self, text):
        """整体重写流式区块。发言有字数上限，重写成本可以忽略。"""
        sticky = self._at_bottom()
        cursor = self.chat_view.textCursor()
        cursor.setPosition(self._stream_pos)
        cursor.movePosition(QTextCursor.End, QTextCursor.KeepAnchor)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(theme.CHAT_BODY))
        cursor.insertText(text, fmt)
        if sticky:
            self._scroll_to_bottom()

    def _finish_stream_block(self):
        if self._stream_open:
            self._on_stream_end(self._stream_buf)

    def _on_tool(self, cn_name, phase, detail):
        self._finish_stream_block()
        self.chat_view.append("")
        cursor = self.chat_view.textCursor()
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(theme.CHAT_TOOL))
        fmt.setFontItalic(True)
        fmt.setFontPointSize(12)
        cursor.movePosition(QTextCursor.End)
        cursor.insertText("🔧 %s %s：%s" % (cn_name, phase, detail), fmt)
        self._scroll_to_bottom()
        self.cur_messages.append({"kind": "tool", "name": cn_name,
                                  "phase": phase, "content": detail})

    def _on_turn_finished(self, reason):
        self._append_system("本轮结束。%s" % reason)
        self._save_cur_history(ending="讨论结束（%s）" % reason)
        self._reset_ui("可以继续追问")

    def _on_turn_stopped(self, context_lost):
        if context_lost:
            self._append_system("已强制停止，上下文已重置 —— 下一次发言会开新会话。")
        else:
            self._append_system("已停止，上下文保留，可以直接接着追问。")
        self._save_cur_history(ending="用户手动停止了讨论")
        self._reset_ui("已停止")

    def _on_turn_error(self, message):
        self._append_system("出错：%s" % message)
        log.error("会话出错：%s", message)
        QMessageBox.critical(self, "出错了", "AI 团队运行出错：\n\n%s" % message)
        self._save_cur_history(ending="出错：%s" % message)
        self._reset_ui("出错，请重试")

    def _reset_ui(self, state_text):
        self.task_input.setEnabled(True)
        self.send_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.status.setText(state_text)
        self._update_input_hint()
        self.task_input.setFocus()

    # ── 渲染辅助 ──
    def _role_color(self, source):
        for role in (self.settings.get("roles") or []):
            if role.get("id") == source:
                return role.get("color") or theme.CHAT_BODY
        return theme.CHAT_BODY

    def _role_color_by_name(self, name):
        for role in (self.settings.get("roles") or []):
            if role.get("name") == name:
                return role.get("color") or theme.CHAT_BODY
        return theme.CHAT_BODY

    def _at_bottom(self) -> bool:
        """用户往上翻看历史时不要强行把他拽回底部。"""
        bar = self.chat_view.verticalScrollBar()
        return bar.value() >= bar.maximum() - 4

    def _scroll_to_bottom(self):
        self.chat_view.moveCursor(QTextCursor.End)

    def _insert_speaker(self, cn_name, source):
        self.chat_view.append("")
        cursor = self.chat_view.textCursor()
        cursor.movePosition(QTextCursor.End)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(self._role_color(source)))
        fmt.setFontWeight(QFont.Bold)
        cursor.insertText("%s  " % cn_name, fmt)
        cursor.insertText("\n")

    def _append_user(self, text, followup=False):
        self.chat_view.append("")
        cursor = self.chat_view.textCursor()
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(theme.CHAT_USER))
        fmt.setFontWeight(QFont.Bold)
        cursor.movePosition(QTextCursor.End)
        cursor.insertText("追问：" if followup else "我：", fmt)
        cursor.insertText(text)
        self._scroll_to_bottom()

    def _append_system(self, text):
        self.chat_view.append("")
        cursor = self.chat_view.textCursor()
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(theme.CHAT_SYS))
        fmt.setFontItalic(True)
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(text, fmt)
        self._scroll_to_bottom()

    # ── 历史 ──
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
            self._refresh_chips()
            if self.session is not None:
                self.session.apply_settings(self.settings)
            self.banner.hide()
            self._append_system("配置已更新。下一次发言会按新配置重建团队，会话上下文重新开始。")

    def open_history(self):
        HistoryDialog(self).exec()

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


def _rgba(hex_color: str, alpha: float) -> str:
    """#RRGGBB → rgba()，用于给角色色做半透明底。"""
    try:
        value = hex_color.lstrip("#")
        r, g, b = int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)
        return "rgba(%d, %d, %d, %.2f)" % (r, g, b, alpha)
    except Exception:
        return "rgba(91, 140, 255, %.2f)" % alpha


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
