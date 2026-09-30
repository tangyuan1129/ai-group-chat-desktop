# -*- coding: utf-8 -*-
"""AI 团队群聊 · 桌面版 —— 主程序（界面 + 会话调度）。

架构
----
    desktop_app.py   界面与交互（本文件）
    team_session.py  会话：多轮追问 / 流式输出 / 优雅停止
    llm.py           模型客户端构造与连接测试
    onboarding.py    首次启动引导
    app_config.py    配置、路径、校验、损坏恢复
    secret_store.py  密钥加密（Windows DPAPI）
    app_logging.py   日志、脱敏、诊断包
    tools.py         AI 的"手臂"：搜索 / 文件 / GitHub / 命令

与旧版的关键差别：这里不再"每发一个任务就重建团队"，而是维持一个长期存活的
TeamSession —— 所以能追问、能流式显示、也不会每轮漏一组 HTTP 连接。
"""
import datetime
import json
import os
import sys

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QFormLayout, QGroupBox,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget, QMainWindow,
                               QMenu, QMessageBox, QPlainTextEdit, QPushButton,
                               QScrollArea, QTextBrowser, QVBoxLayout, QWidget)

import app_config
from app_config import LoadResult, SOURCE_LABELS, SOURCE_SHORT, load_settings, save_settings
from app_logging import (export_diagnostics, get_logger, install_excepthook,
                         register_secret, setup_logging)
from llm import ZHIPU_BASE_CN, ZHIPU_BASE_INTL, ZHIPU_MODELS, fetch_ollama_models
from onboarding import OnboardingWizard
from team_session import TeamSession

log = get_logger("ui")

APP_DIR = os.path.dirname(os.path.abspath(__file__))
COLOR_USER = "#0F172A"
COLOR_BODY = "#1E293B"
COLOR_META = "#94A3B8"
COLOR_TOOL = "#7C8AA5"
COLOR_SYS = "#64748B"

STYLE_PRIMARY = (
    "QPushButton { background: #2D7DFF; color: white; border: none; border-radius: 8px;"
    "padding: 10px 22px; font-size: 14px; font-weight: 600; }"
    "QPushButton:hover { background: #1E6AE6; }"
    "QPushButton:disabled { background: #94A3B8; }"
)
STYLE_DANGER = (
    "QPushButton { background: #EF4444; color: white; border: none; border-radius: 8px;"
    "padding: 10px 18px; font-size: 14px; font-weight: 600; }"
    "QPushButton:hover { background: #DC2626; }"
    "QPushButton:disabled { background: #CBD5E1; color: #64748B; }"
)
STYLE_GHOST_BLUE = (
    "QPushButton { background: white; color: #2D7DFF; border: 1.5px solid #2D7DFF;"
    "border-radius: 8px; padding: 8px 16px; font-size: 13px; font-weight: 600; }"
    "QPushButton:hover { background: #EEF4FF; }"
)
STYLE_GHOST_GRAY = (
    "QPushButton { background: white; color: #475569; border: 1.5px solid #CBD5E1;"
    "border-radius: 8px; padding: 8px 16px; font-size: 13px; font-weight: 600; }"
    "QPushButton:hover { background: #F1F5F9; }"
)
STYLE_BODY = (
    "QTextBrowser { background: #FAFBFC; border: 1px solid #E2E8F0;"
    "border-radius: 10px; padding: 8px; font-size: 14px; }"
)


# ── 设置对话框 ─────────────────────────────────────────────────
class TestWorker(QThread):
    """逐个测试各角色能否连通。真的发请求，所以放后台线程。"""

    progress = Signal(str, bool, str)      # 角色中文名, 是否成功, 说明
    finished_all = Signal(int, int)        # 通过数, 总数

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self._settings = settings

    def run(self):
        import asyncio
        from llm import test_connection
        roles = self._settings.get("roles") or {}
        total = passed = 0
        for name in app_config.ROLE_ORDER:
            cfg = roles.get(name) or {}
            cn = cfg.get("display") or name
            total += 1
            try:
                ok, message = asyncio.run(test_connection(cfg, self._settings))
            except Exception as exc:
                ok, message = False, str(exc)
            if ok:
                passed += 1
            self.progress.emit(cn, ok, message)
        self.finished_all.emit(passed, total)


class SettingsDialog(QDialog):
    """逐角色配置模型。顶部是智谱的共享凭据，省得四个角色各填一遍。"""

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("模型与角色设置")
        self.setMinimumSize(760, 640)
        self._worker = None
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        title = QLabel("配置每个角色的 AI 模型")
        title.setStyleSheet("font-size: 17px; font-weight: 700; color: #1E293B;")
        root.addWidget(title)
        hint = QLabel(
            "来源说明：云端智谱 GLM（有免费额度）／ 本地 Ollama（离线）／ "
            "自定义 API（任何 OpenAI 兼容接口，如 DeepSeek、Kimi）。\n"
            "API Key 会加密保存在本机，不会明文落盘。"
        )
        hint.setStyleSheet("font-size: 12px; color: #64748B;")
        hint.setWordWrap(True)
        root.addWidget(hint)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        vbox = QVBoxLayout(inner)

        # 智谱共享凭据：四个角色都用智谱时不必填四遍
        shared = self.settings.setdefault("shared", {})
        zhipu_group = QGroupBox("智谱 GLM 共享凭据（所有用智谱的角色共用）")
        zhipu_form = QFormLayout(zhipu_group)
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
        vbox.addWidget(zhipu_group)

        self.role_boxes = {}
        for name, cn, _color, _src, _model, _prompt in app_config.DEFAULT_ROLES:
            cfg = self.settings["roles"].get(name, {})
            group = QGroupBox("%s（%s）" % (cn, name))
            form = QFormLayout(group)

            src_box = QComboBox()
            for key in ("zhipu", "ollama", "custom"):
                src_box.addItem(SOURCE_LABELS[key], key)
            src_box.setCurrentIndex(max(0, src_box.findData(cfg.get("source", "zhipu"))))
            src_box.currentIndexChanged.connect(lambda _i, n=name: self._fill_models(n))
            form.addRow("模型来源：", src_box)

            model_box = QComboBox()
            model_box.setEditable(True)
            form.addRow("模型：", model_box)

            base_edit = QLineEdit(cfg.get("base_url", ""))
            base_edit.setPlaceholderText("例如 https://api.deepseek.com/v1")
            form.addRow("Base URL：", base_edit)

            key_edit = QLineEdit(cfg.get("api_key", ""))
            key_edit.setEchoMode(QLineEdit.Password)
            key_edit.setPlaceholderText("自定义来源才需要")
            form.addRow("API Key：", key_edit)

            prompt_edit = QPlainTextEdit(cfg.get("system_prompt", ""))
            prompt_edit.setPlaceholderText("这个角色的说话风格、职责……")
            prompt_edit.setMaximumHeight(74)
            form.addRow("人设提示词：", prompt_edit)

            vbox.addWidget(group)
            self.role_boxes[name] = {"source": src_box, "model": model_box,
                                     "base_url": base_edit, "api_key": key_edit,
                                     "prompt": prompt_edit}
            self._fill_models(name, keep=cfg.get("model", ""))

        vbox.addStretch(1)
        scroll.setWidget(inner)
        root.addWidget(scroll, stretch=1)

        self.test_label = QLabel()
        self.test_label.setStyleSheet("font-size: 12px; color: #64748B;")
        self.test_label.setWordWrap(True)
        root.addWidget(self.test_label)

        buttons = QHBoxLayout()
        self.test_btn = QPushButton("测试全部")
        self.test_btn.setStyleSheet(STYLE_GHOST_GRAY)
        self.test_btn.clicked.connect(self._on_test)
        save_btn = QPushButton("保存配置")
        save_btn.setStyleSheet(STYLE_PRIMARY)
        save_btn.clicked.connect(self._on_save)
        cancel_btn = QPushButton("取消")
        cancel_btn.setStyleSheet(STYLE_GHOST_GRAY)
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(self.test_btn)
        buttons.addStretch(1)
        buttons.addWidget(save_btn)
        buttons.addWidget(cancel_btn)
        root.addLayout(buttons)

    def _fill_models(self, name, keep=""):
        box = self.role_boxes[name]
        source = box["source"].currentData()
        model_box = box["model"]
        model_box.blockSignals(True)
        model_box.clear()
        if source == "zhipu":
            options = list(ZHIPU_MODELS)
        elif source == "ollama":
            options = fetch_ollama_models() or ["qwen2.5:7b"]
        else:
            options = []
        model_box.addItems(options)
        if keep:
            model_box.setCurrentText(keep)     # 可编辑，允许手填
        model_box.blockSignals(False)
        is_custom = source == "custom"
        box["base_url"].setVisible(is_custom)
        box["api_key"].setVisible(is_custom)

    def collect(self) -> dict:
        """把界面上的值写回 settings（不落盘）。"""
        shared = self.settings.setdefault("shared", {})
        shared["zai_api_key"] = self.zhipu_key.text().strip()
        shared["zai_base_url"] = self.zhipu_base.currentData()
        for name, box in self.role_boxes.items():
            role = self.settings["roles"][name]
            role["source"] = box["source"].currentData()
            role["model"] = box["model"].currentText().strip()
            role["base_url"] = box["base_url"].text().strip()
            role["api_key"] = box["api_key"].text().strip()
            role["system_prompt"] = box["prompt"].toPlainText().strip()
        return self.settings

    def _on_test(self):
        self.collect()
        self.test_btn.setEnabled(False)
        self.test_label.setText("正在逐个测试…（每个角色最多 30 秒）")
        self._worker = TestWorker(self.settings, self)
        self._worker.progress.connect(
            lambda cn, ok, msg: self.test_label.setText(
                "%s %s：%s" % ("✅" if ok else "❌", cn, msg.splitlines()[0][:120])))
        self._worker.finished_all.connect(self._on_test_done)
        self._worker.start()

    def _on_test_done(self, passed, total):
        self.test_btn.setEnabled(True)
        self.test_label.setText("测试完成：%d/%d 个角色可用。%s"
                                % (passed, total,
                                   "" if passed == total else "不可用的角色请检查来源与凭据。"))

    def _on_save(self):
        self.collect()
        try:
            save_settings(self.settings)
        except Exception as exc:
            QMessageBox.critical(self, "保存失败", "配置没能保存：\n%s" % exc)
            return
        for role in self.settings["roles"].values():
            register_secret((role or {}).get("api_key", ""))
        register_secret((self.settings.get("shared") or {}).get("zai_api_key", ""))
        log.info("配置已保存")
        self.accept()


# ── 历史记录对话框 ─────────────────────────────────────────────
class HistoryDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("历史聊天记录")
        self.resize(940, 620)
        self.items = []
        self._build()

    def _build(self):
        root = QHBoxLayout(self)

        left = QVBoxLayout()
        tip = QLabel("点一条记录查看当时完整对话")
        tip.setStyleSheet("font-size: 12px; color: #64748B;")
        left.addWidget(tip)
        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet(
            "QListWidget { border: 1px solid #E2E8F0; border-radius: 8px; font-size: 13px; }"
            "QListWidget::item { padding: 8px; }"
            "QListWidget::item:selected { background: #DBEAFE; color: #1E40AF; }")
        self.list_widget.currentRowChanged.connect(self._show_item)
        left.addWidget(self.list_widget, stretch=1)
        self.count_label = QLabel()
        self.count_label.setStyleSheet("font-size: 12px; color: #94A3B8;")
        self.count_label.setWordWrap(True)
        left.addWidget(self.count_label)
        open_btn = QPushButton("打开记录文件夹")
        open_btn.setStyleSheet(STYLE_GHOST_GRAY)
        open_btn.clicked.connect(self._open_folder)
        left.addWidget(open_btn)
        root.addLayout(left, stretch=2)

        self.view = QTextBrowser()
        self.view.setOpenLinks(False)
        self.view.setStyleSheet(
            "QTextBrowser { background: #FAFBFC; border: 1px solid #E2E8F0;"
            "border-radius: 8px; padding: 10px; font-size: 14px; }")
        root.addWidget(self.view, stretch=3)
        self._load()

    def _open_folder(self):
        folder = app_config.history_dir()
        os.makedirs(folder, exist_ok=True)
        open_in_explorer(folder)

    def _load(self):
        self.items = list_history()
        self.list_widget.clear()
        for item in self.items:
            task = item["task"][:36] + ("…" if len(item["task"]) > 36 else "")
            self.list_widget.addItem("%s\n📋 %s" % (item["time"], task))
        self.count_label.setText("共 %d 条记录\n%s" % (len(self.items), app_config.history_dir()))
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
        self._append("📝 任务：" + data.get("task", ""), COLOR_USER, bold=True)
        meta = data.get("meta")
        if meta:
            summary = "、".join("%s=%s" % (k, (v or {}).get("model") or "?")
                               for k, v in list(meta.items())[:4])
            self._append("🧩 当时配置：" + summary, COLOR_META, size=11)
        for msg in data.get("messages", []):
            kind = msg.get("kind", "")
            if kind == "user":
                self._append("📝 我的任务：" + msg.get("content", ""), COLOR_USER, bold=True)
            elif kind == "msg":
                self._append("【%s】%s" % (msg.get("name", ""), msg.get("content", "")),
                             msg.get("color", "#334155"), bold=True)
            elif kind == "tool":
                self._append("🔧 %s %s：%s" % (msg.get("name", ""), msg.get("phase", ""),
                                               msg.get("content", "")),
                             COLOR_TOOL, italic=True, size=12)
            elif kind == "system":
                self._append("⚙️ " + msg.get("content", ""), COLOR_SYS, italic=True)
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


def save_history(entries, task, time_str, meta=None) -> str:
    """写一条历史。先写临时文件再原子替换，避免中途崩溃留下半截 JSON。"""
    try:
        folder = app_config.history_dir()
        os.makedirs(folder, exist_ok=True)
        safe = "".join(c if c not in r'\/:*?"<>|' else "_" for c in task)[:30] or "任务"
        filename = "%s %s.json" % (time_str.replace(":", "-").replace(" ", "_"), safe)
        payload = {"time": time_str, "task": task, "messages": entries}
        if meta:
            payload["meta"] = meta      # 记下当时用的模型，回看时才知道是什么配置跑的
        tmp = os.path.join(folder, filename + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, os.path.join(folder, filename))
        return filename
    except Exception:
        log.exception("保存历史失败")
        return ""


def open_in_explorer(path: str):
    try:
        if sys.platform == "win32":
            os.startfile(path)                                    # noqa: S606
        else:
            import subprocess
            subprocess.Popen(["xdg-open", path])
    except Exception:
        log.exception("打开目录失败：%s", path)


# ── 主窗口 ─────────────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self, load_result: LoadResult = None, auto_onboard: bool = True):
        super().__init__()
        self.auto_onboard = auto_onboard
        self.load_result = load_result or load_settings()
        self.settings = self.load_result.settings
        self.session = None
        self.cur_task = ""
        self.cur_messages = []
        self._stream_pos = None
        self._stream_buf = ""
        self._stream_open = False
        self._stream_name = ""

        self.setWindowTitle("AI 团队群聊 · 桌面版")
        self.setMinimumSize(900, 680)
        self._set_icon()
        self._build_ui()
        self._register_secrets()
        self._greet()
        self._maybe_onboard()

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
        """把已知密钥登记进日志脱敏器 —— 之后日志里再出现就会被替换掉。"""
        for role in (self.settings.get("roles") or {}).values():
            register_secret((role or {}).get("api_key", ""))
        register_secret((self.settings.get("shared") or {}).get("zai_api_key", ""))
        register_secret(app_config.github_token())

    # ── UI ──
    def _build_ui(self):
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 14, 16, 12)
        root.setSpacing(10)

        head = QHBoxLayout()
        title_col = QVBoxLayout()
        title = QLabel("🎙️ AI 团队群聊 · 异构模型")
        title.setStyleSheet("font-size: 20px; font-weight: 700; color: #1E293B;")
        subtitle = QLabel("四个不同模型的 AI 讨论并分工，可以一直追问下去")
        subtitle.setStyleSheet("font-size: 12px; color: #64748B;")
        title_col.addWidget(title)
        title_col.addWidget(subtitle)
        head.addLayout(title_col, stretch=1)

        self.new_btn = QPushButton("🧹 新会话")
        self.new_btn.setStyleSheet(STYLE_GHOST_GRAY)
        self.new_btn.clicked.connect(self.start_new_conversation)
        head.addWidget(self.new_btn)

        self.settings_btn = QPushButton("⚙ 配置模型")
        self.settings_btn.setStyleSheet(STYLE_GHOST_BLUE)
        self.settings_btn.clicked.connect(self.open_settings)
        head.addWidget(self.settings_btn)

        self.history_btn = QPushButton("📜 历史记录")
        self.history_btn.setStyleSheet(STYLE_GHOST_GRAY)
        self.history_btn.clicked.connect(self.open_history)
        head.addWidget(self.history_btn)

        self.more_btn = QPushButton("⋯ 更多")
        self.more_btn.setStyleSheet(STYLE_GHOST_GRAY)
        menu = QMenu(self)
        menu.addAction("导出诊断包（含日志，已脱敏）", self.export_diagnostics_action)
        menu.addAction("打开日志文件夹", lambda: open_in_explorer(app_config.logs_dir()))
        menu.addAction("打开 AI 产出文件夹", lambda: open_in_explorer(app_config.documents_dir()))
        menu.addAction("重新运行配置向导", self.run_onboarding)
        self.more_btn.setMenu(menu)
        head.addWidget(self.more_btn)
        root.addLayout(head)

        self.badge_row = QHBoxLayout()
        root.addLayout(self.badge_row)
        self._refresh_badges()

        self.chat_view = QTextBrowser()
        self.chat_view.setOpenLinks(False)
        self.chat_view.setStyleSheet(STYLE_BODY)
        root.addWidget(self.chat_view, stretch=1)

        input_row = QHBoxLayout()
        self.task_input = QLineEdit()
        self.task_input.setPlaceholderText(
            "输入任务，例如：设计一个五一成都 3 天旅行方案，4 人人均预算 2500……")
        self.task_input.setStyleSheet(
            "QLineEdit { padding: 10px 12px; border: 1px solid #CBD5E1; border-radius: 8px;"
            "font-size: 14px; background: white; }"
            "QLineEdit:focus { border-color: #2D7DFF; }")
        self.task_input.returnPressed.connect(self.send)
        self.send_btn = QPushButton("发送任务")
        self.send_btn.setStyleSheet(STYLE_PRIMARY)
        self.send_btn.clicked.connect(self.send)
        self.stop_btn = QPushButton("停止")
        self.stop_btn.setEnabled(False)
        self.stop_btn.setStyleSheet(STYLE_DANGER)
        self.stop_btn.clicked.connect(self.stop)
        input_row.addWidget(self.task_input, stretch=1)
        input_row.addWidget(self.send_btn)
        input_row.addWidget(self.stop_btn)
        root.addLayout(input_row)

        self.status = QLabel("状态：空闲")
        self.status.setStyleSheet("font-size: 12px; color: #64748B;")
        root.addWidget(self.status)
        self.setCentralWidget(central)

    def _refresh_badges(self):
        while self.badge_row.count():
            item = self.badge_row.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        for name, cn, color, _src, _model, _prompt in app_config.DEFAULT_ROLES:
            cfg = self.settings["roles"].get(name, {})
            source = cfg.get("source", "zhipu")
            color = cfg.get("color", color)
            badge = QLabel(" %s · %s · %s " % (cn, SOURCE_SHORT.get(source, "?"),
                                               cfg.get("model", "")))
            badge.setStyleSheet(
                "background: %s22; color: %s; border: 1px solid %s55;"
                "border-radius: 12px; padding: 4px 12px; font-size: 12px; font-weight: 600;"
                % (color, color, color))
            self.badge_row.addWidget(badge)
        self.badge_row.addStretch(1)

    def _greet(self):
        if self.load_result.recovered:
            self._append_system(
                "上次的配置文件损坏了，已备份为 %s 并恢复默认配置。"
                % os.path.basename(self.load_result.backup_path or "备份文件"))
        for note in self.load_result.notes:
            self._append_system(note)
        if self.load_result.problems:
            self._append_system("配置还需要完善：" + "；".join(self.load_result.problems))
        else:
            self._append_system(
                "已就绪：四个 AI 已装载不同模型。输入任务开始，之后可以继续追问，"
                "上下文会一直保留。")

    def _maybe_onboard(self):
        # 测试里要关掉：引导是模态对话框，会卡住自动化流程
        if not self.auto_onboard or not self.load_result.needs_onboarding:
            return
        reason = ("检测到配置还不完整：%s" % "；".join(self.load_result.problems)
                  if self.load_result.problems else "这是第一次启动。")
        dialog = OnboardingWizard(self.settings, self, reason=reason)
        if dialog.exec() == QDialog.Accepted:
            self.settings = load_settings(migrate=False).settings
            self._register_secrets()
            self._refresh_badges()
            self._append_system("配置完成，可以开始了。")

    # ── 会话生命周期 ──
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
            self.status.setText("状态：请先输入内容")
            return
        if self.stop_btn.isEnabled():
            self.status.setText("状态：正在讨论中，请先停止")
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
        self.status.setText("状态：%s…" % ("追问中" if is_followup else "讨论中"))
        self._append_user(task, followup=is_followup)
        if not session.ask(task):
            self._on_turn_error("会话线程没有就绪，请重试或重启程序。")

    def stop(self):
        if self.session is None or not self.stop_btn.isEnabled():
            return
        self.stop_btn.setEnabled(False)
        self.status.setText("状态：正在停止…（等当前发言收尾）")
        self.session.stop()

    def start_new_conversation(self):
        if self.stop_btn.isEnabled():
            QMessageBox.information(self, "正在讨论中", "请先停止当前讨论，再开新会话。")
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
            "继续追问，例如：把方案里的预算再压低 20%……" if has_context
            else "输入任务，例如：设计一个五一成都 3 天旅行方案，4 人人均预算 2500……")

    # ── 会话信号 ──
    def _on_session_ready(self):
        log.info("会话已就绪")
        self._update_input_hint()

    def _on_message(self, cn_name, source, content):
        """没有走流式的完整发言（例如工具回合之后的自然语言总结）。"""
        self._finish_stream_block()
        self._insert_speaker(cn_name, source)
        cursor = self.chat_view.textCursor()
        cursor.movePosition(QTextCursor.End)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(COLOR_BODY))
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
        cursor.insertText("【%s】" % cn_name, fmt)
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
                                      "color": self._role_color(self._stream_name)})
        self._stream_buf = ""

    def _render_stream(self, text):
        """整体重写流式区块。发言有字数上限，重写成本可以忽略。"""
        sticky = self._at_bottom()
        cursor = self.chat_view.textCursor()
        cursor.setPosition(self._stream_pos)
        cursor.movePosition(QTextCursor.End, QTextCursor.KeepAnchor)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(COLOR_BODY))
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
        fmt.setForeground(QColor(COLOR_TOOL))
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
        self._reset_ui("空闲（可以继续追问）")

    def _on_turn_stopped(self, context_lost):
        if context_lost:
            self._append_system("已强制停止，会话上下文已重置 —— 下一次发言会开新会话。")
        else:
            self._append_system("已停止本次讨论，上下文保留，可以直接接着追问。")
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
        self.status.setText("状态：%s" % state_text)
        self._update_input_hint()
        self.task_input.setFocus()

    # ── 渲染辅助 ──
    def _role_color(self, source):
        cfg = (self.settings.get("roles") or {}).get(source) or {}
        if cfg.get("color"):
            return cfg["color"]
        for name, _cn, color, _s, _m, _p in app_config.DEFAULT_ROLES:
            if name == source:
                return color
        return COLOR_BODY

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
        cursor.insertText("【%s】" % cn_name, fmt)
        cfg = (self.settings.get("roles") or {}).get(source) or {}
        meta = QTextCharFormat()
        meta.setForeground(QColor(COLOR_META))
        meta.setFontPointSize(11)
        cursor.insertText("  （%s）" % SOURCE_SHORT.get(cfg.get("source", ""), ""), meta)
        cursor.insertText("\n")

    def _append_user(self, text, followup=False):
        self.chat_view.append("")
        cursor = self.chat_view.textCursor()
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(COLOR_USER))
        fmt.setFontWeight(QFont.Bold)
        cursor.movePosition(QTextCursor.End)
        cursor.insertText("💬 追问：" if followup else "📝 我的任务：", fmt)
        cursor.insertText(text)
        self._scroll_to_bottom()

    def _append_system(self, text):
        self.chat_view.append("")
        cursor = self.chat_view.textCursor()
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(COLOR_SYS))
        fmt.setFontItalic(True)
        cursor.movePosition(QTextCursor.End)
        cursor.insertText("⚙️ %s" % text, fmt)
        self._scroll_to_bottom()

    # ── 历史 ──
    def _save_cur_history(self, ending=""):
        if not self.cur_task or not self.cur_messages:
            return
        entries = list(self.cur_messages)
        if ending:
            entries.append({"kind": "system", "name": "", "content": ending})
        meta = {name: {"source": (cfg or {}).get("source"),
                       "model": (cfg or {}).get("model")}
                for name, cfg in (self.settings.get("roles") or {}).items()}
        save_history(entries, self.cur_task,
                     datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), meta)
        self.cur_task = ""
        self.cur_messages = []

    # ── 菜单动作 ──
    def open_settings(self):
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec() == QDialog.Accepted:
            self.settings = load_settings(migrate=False).settings
            self._register_secrets()
            self._refresh_badges()
            if self.session is not None:
                self.session.apply_settings(self.settings)
            self._append_system("模型配置已更新。下一次发言会按新配置重建团队，"
                                "会话上下文会重新开始。")

    def open_history(self):
        HistoryDialog(self).exec()

    def run_onboarding(self):
        dialog = OnboardingWizard(self.settings, self, reason="重新配置模型来源。")
        if dialog.exec() == QDialog.Accepted:
            self.settings = load_settings(migrate=False).settings
            self._register_secrets()
            self._refresh_badges()
            if self.session is not None:
                self.session.apply_settings(self.settings)
            self._append_system("配置已更新。")

    def export_diagnostics_action(self):
        try:
            path = export_diagnostics()
        except Exception as exc:
            QMessageBox.critical(self, "导出失败", "诊断包没能生成：\n%s" % exc)
            return
        QMessageBox.information(self, "已导出",
                                "诊断包已生成（日志中的密钥已自动脱敏）：\n\n%s" % path)

    def closeEvent(self, event):
        """关窗口前把会话停干净，否则 QThread 被销毁时程序会崩。"""
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
