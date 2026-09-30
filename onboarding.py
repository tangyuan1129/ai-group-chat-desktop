# -*- coding: utf-8 -*-
"""首次启动引导向导。

产品与玩具的分水岭之一
----------------------
旧版装完打开就是主界面，新用户输入任务 → 弹一个"未找到智谱 API Key"的错误框，
然后不知道去哪申请、填哪里、填对没有。公开发布的产品不能这样。

这里做成三步向导：**选来源 → 填凭据 → 真的测一次连接**。
第三步是关键：直接发一次最小请求，避免"填完以为好了、一发任务就报错"。
"""
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QMessageBox, QPushButton, QStackedWidget,
                               QVBoxLayout, QWidget)

from app_config import ROLE_ORDER, SOURCE_LABELS, save_settings
from app_logging import get_logger
from llm import ZHIPU_BASE_CN, ZHIPU_BASE_INTL, ZHIPU_MODELS, fetch_ollama_models

log = get_logger("onboarding")

STYLE_TITLE = "font-size: 20px; font-weight: 700; color: #1E293B;"
STYLE_HINT = "font-size: 12px; color: #64748B;"
STYLE_PRIMARY = (
    "QPushButton { background: #2D7DFF; color: white; border: none; border-radius: 8px;"
    "padding: 9px 26px; font-size: 14px; font-weight: 600; }"
    "QPushButton:hover { background: #1E6AE6; }"
    "QPushButton:disabled { background: #94A3B8; }"
)
STYLE_SECONDARY = (
    "QPushButton { background: white; color: #475569; border: 1.5px solid #CBD5E1;"
    "border-radius: 8px; padding: 9px 20px; font-size: 14px; }"
    "QPushButton:hover { background: #F1F5F9; }"
)


class _TestWorker(QThread):
    """在后台线程里真的发一次请求，别把界面卡住。"""

    done = Signal(bool, str)

    def __init__(self, role_cfg, settings, parent=None):
        super().__init__(parent)
        self._role_cfg = role_cfg
        self._settings = settings

    def run(self):
        import asyncio
        from llm import test_connection
        try:
            ok, message = asyncio.run(test_connection(self._role_cfg, self._settings))
        except Exception as exc:
            ok, message = False, "测试过程出错：%s" % exc
        self.done.emit(ok, message)


class OnboardingWizard(QDialog):
    """三步引导。exec() 返回 Accepted 表示用户完成了配置。"""

    def __init__(self, settings, parent=None, reason=""):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("欢迎使用 AI 团队群聊")
        self.setMinimumSize(620, 470)
        self._build(reason)

    # ── 界面 ──
    def _build(self, reason):
        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 20)
        root.setSpacing(12)

        self.title = QLabel("先花一分钟配好模型")
        self.title.setStyleSheet(STYLE_TITLE)
        root.addWidget(self.title)

        hint = QLabel(reason or "四个 AI 需要至少一个能用的模型才能开始讨论。")
        hint.setStyleSheet(STYLE_HINT)
        hint.setWordWrap(True)
        root.addWidget(hint)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._page_source())
        self.stack.addWidget(self._page_credentials())
        self.stack.addWidget(self._page_test())
        root.addWidget(self.stack, stretch=1)

        self.step_label = QLabel()
        self.step_label.setStyleSheet(STYLE_HINT)
        root.addWidget(self.step_label)

        buttons = QHBoxLayout()
        self.skip_btn = QPushButton("稍后再说")
        self.skip_btn.setStyleSheet(STYLE_SECONDARY)
        self.skip_btn.clicked.connect(self.reject)
        self.back_btn = QPushButton("上一步")
        self.back_btn.setStyleSheet(STYLE_SECONDARY)
        self.back_btn.clicked.connect(self._go_back)
        self.next_btn = QPushButton("下一步")
        self.next_btn.setStyleSheet(STYLE_PRIMARY)
        self.next_btn.clicked.connect(self._go_next)
        buttons.addWidget(self.skip_btn)
        buttons.addStretch(1)
        buttons.addWidget(self.back_btn)
        buttons.addWidget(self.next_btn)
        root.addLayout(buttons)

        self._show_step(0)

    def _show_step(self, index: int):
        """切到第 index 步（0 起）。同时更新按钮文案与可用状态。"""
        index = max(0, min(index, self.stack.count() - 1))
        self.stack.setCurrentIndex(index)
        self.step_label.setText("第 %d / %d 步" % (index + 1, self.stack.count()))
        self.back_btn.setEnabled(index > 0)
        self.next_btn.setText("完成" if index == self.stack.count() - 1 else "下一步")
        if index == 0:
            self._refresh()

    def _page_source(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel("第 1 步：选一个模型来源"))

        self.source_box = QComboBox()
        self.source_box.addItem("云端智谱 GLM —— 有免费额度，最省事（推荐）", "zhipu")
        self.source_box.addItem("自定义 API —— DeepSeek / Kimi 等 OpenAI 兼容接口", "custom")
        self.source_box.addItem("本地 Ollama —— 完全离线，需要先装 Ollama", "ollama")
        self.source_box.currentIndexChanged.connect(lambda _i: self._refresh())
        layout.addWidget(self.source_box)

        self.source_hint = QLabel()
        self.source_hint.setStyleSheet(STYLE_HINT)
        self.source_hint.setWordWrap(True)
        layout.addWidget(self.source_hint)
        layout.addStretch(1)
        return page

    def _page_credentials(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel("第 2 步：填写凭据"))

        self.cred_form = QFormLayout()
        self.zhipu_key = QLineEdit()
        self.zhipu_key.setEchoMode(QLineEdit.Password)
        self.zhipu_key.setPlaceholderText("在 open.bigmodel.cn 或 api.z.ai 申请")
        self.zhipu_base = QComboBox()
        self.zhipu_base.addItem("国内站 open.bigmodel.cn", ZHIPU_BASE_CN)
        self.zhipu_base.addItem("国际站 api.z.ai", ZHIPU_BASE_INTL)
        self.zhipu_model = QComboBox()
        self.zhipu_model.setEditable(True)
        self.zhipu_model.addItems(ZHIPU_MODELS)

        self.custom_base = QLineEdit()
        self.custom_base.setPlaceholderText("例如 https://api.deepseek.com/v1")
        self.custom_key = QLineEdit()
        self.custom_key.setEchoMode(QLineEdit.Password)
        self.custom_model = QLineEdit()
        self.custom_model.setPlaceholderText("例如 deepseek-chat")

        self.ollama_model = QComboBox()
        self.ollama_model.setEditable(True)

        self._rows = {
            "zhipu": [("API Key：", self.zhipu_key), ("接口地址：", self.zhipu_base),
                      ("模型：", self.zhipu_model)],
            "custom": [("Base URL：", self.custom_base), ("API Key：", self.custom_key),
                       ("模型名：", self.custom_model)],
            "ollama": [("本地模型：", self.ollama_model)],
        }
        for rows in self._rows.values():
            for label, widget in rows:
                self.cred_form.addRow(label, widget)
        layout.addLayout(self.cred_form)

        self.cred_hint = QLabel()
        self.cred_hint.setStyleSheet(STYLE_HINT)
        self.cred_hint.setWordWrap(True)
        layout.addWidget(self.cred_hint)
        layout.addStretch(1)
        return page

    def _page_test(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel("第 3 步：测一下能不能用"))
        self.test_result = QLabel("点「开始测试」发一次最小请求，确认配置真的能用。")
        self.test_result.setWordWrap(True)
        self.test_result.setStyleSheet("font-size: 13px; color: #334155;")
        layout.addWidget(self.test_result)
        self.test_btn = QPushButton("开始测试")
        self.test_btn.setStyleSheet(STYLE_SECONDARY)
        self.test_btn.clicked.connect(self._run_test)
        row = QHBoxLayout()
        row.addWidget(self.test_btn)
        row.addStretch(1)
        layout.addLayout(row)
        layout.addStretch(1)
        return page

    # ── 逻辑 ──
    def _refresh(self):
        source = self.source_box.currentData()
        for key, rows in self._rows.items():
            for _label, widget in rows:
                widget.setVisible(key == source)

        if source == "zhipu":
            self.source_hint.setText(
                "智谱新用户有免费额度。注意国内站和国际站的 Key 互不通用，"
                "申请哪个站就选哪个接口地址。")
            self.cred_hint.setText("Key 会加密保存在本机（Windows 凭据保护），不会明文落盘。")
        elif source == "custom":
            self.source_hint.setText(
                "任何 OpenAI 兼容接口都能接：DeepSeek、Kimi、通义、本地 vLLM 等。")
            self.cred_hint.setText("Key 会加密保存在本机。Base URL 一般以 /v1 结尾。")
        else:
            models = fetch_ollama_models()
            self.ollama_model.clear()
            self.ollama_model.addItems(models or ["qwen2.5:7b"])
            self.source_hint.setText(
                "本地模型不联网、不花钱，但需要先装 Ollama 并下载模型。"
                "没装也能继续，只是这一项用不了。")
            self.cred_hint.setText(
                "检测到的本地模型：%s" % ("、".join(models) if models else "无（Ollama 未运行）"))

    def _collect_role_cfg(self) -> dict:
        source = self.source_box.currentData()
        if source == "zhipu":
            return {"source": "zhipu", "model": self.zhipu_model.currentText().strip(),
                    "base_url": "", "api_key": ""}
        if source == "custom":
            return {"source": "custom", "model": self.custom_model.text().strip(),
                    "base_url": self.custom_base.text().strip(),
                    "api_key": self.custom_key.text().strip()}
        return {"source": "ollama", "model": self.ollama_model.currentText().strip(),
                "base_url": "", "api_key": ""}

    def _apply_to_settings(self):
        """把向导里选的来源套用到全部四个角色。想混搭可以去「配置模型」细调。"""
        cfg = self._collect_role_cfg()
        for name in ROLE_ORDER:
            role = self.settings["roles"][name]
            role["source"] = cfg["source"]
            role["model"] = cfg["model"]
            if cfg["source"] == "custom":
                role["base_url"] = cfg["base_url"]
                role["api_key"] = cfg["api_key"]
        if cfg["source"] == "zhipu":
            self.settings.setdefault("shared", {})["zai_api_key"] = self.zhipu_key.text().strip()
            self.settings["shared"]["zai_base_url"] = self.zhipu_base.currentData()
        save_settings(self.settings)

    def _go_back(self):
        self._show_step(max(0, self.stack.currentIndex() - 1))

    def _go_next(self):
        index = self.stack.currentIndex()
        if index == 0:
            self._refresh()
            self._show_step(1)
            return
        if index == 1:
            problem = self._validate()
            if problem:
                QMessageBox.warning(self, "还差一点", problem)
                return
            self._show_step(2)
            self.test_result.setText("点「开始测试」发一次最小请求，确认配置真的能用。")
            return
        # 第三步：没测过也允许保存，但提醒一句
        self._save_and_close()

    def _validate(self) -> str:
        source = self.source_box.currentData()
        if source == "zhipu":
            if not self.zhipu_key.text().strip():
                return "请填写智谱 API Key。没有的话可以去 open.bigmodel.cn 免费申请。"
            if not self.zhipu_model.currentText().strip():
                return "请选择或填写一个模型名。"
        elif source == "custom":
            if not self.custom_base.text().strip():
                return "请填写 Base URL，例如 https://api.deepseek.com/v1"
            if not self.custom_key.text().strip():
                return "请填写 API Key。"
            if not self.custom_model.text().strip():
                return "请填写模型名，例如 deepseek-chat。"
        else:
            if not self.ollama_model.currentText().strip():
                return "请选择本地模型，或先在命令行执行 ollama pull qwen2.5:7b。"
        return ""

    def _run_test(self):
        problem = self._validate()
        if problem:
            QMessageBox.warning(self, "还差一点", problem)
            return
        self.test_btn.setEnabled(False)
        self.test_result.setText("正在测试…（最多等 30 秒）")
        self._worker = _TestWorker(self._collect_role_cfg(), self.settings, self)
        self._worker.done.connect(self._on_test_done)
        self._worker.start()

    def _on_test_done(self, ok, message):
        self.test_btn.setEnabled(True)
        if ok:
            self.test_result.setText("✅ %s\n\n可以点「完成」保存了。" % message)
            self.test_result.setStyleSheet("font-size: 13px; color: #15803D;")
            self.next_btn.setText("完成")
        else:
            self.test_result.setText("❌ %s\n\n可以改完再测，也可以直接保存稍后再调。" % message)
            self.test_result.setStyleSheet("font-size: 13px; color: #B91C1C;")

    def _save_and_close(self):
        try:
            self._apply_to_settings()
        except Exception as exc:
            QMessageBox.critical(self, "保存失败", "配置没能保存：\n%s" % exc)
            return
        log.info("引导向导完成，模型来源：%s", self.source_box.currentData())
        self.accept()
