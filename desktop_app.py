# -*- coding: utf-8 -*-
"""
AI 团队群聊 · 桌面版（可配置版）
================================
四个 AI 在同一窗口里讨论并分工，每个角色的模型都可以自己配置：
  来源可选：云端智谱 GLM / 本地 Ollama / 自定义 OpenAI 兼容 API（如 DeepSeek、Kimi）
配置保存在 team_settings.json，启动时加载；界面全中文。
"""
import asyncio
import json
import os
import sys
import traceback
import urllib.request

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont, QTextCursor, QTextCharFormat, QColor, QIcon
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTextBrowser, QMessageBox,
    QDialog, QComboBox, QPlainTextEdit, QGroupBox, QFormLayout, QScrollArea,
    QListWidget,
)

# ── 路径与常量 ─────────────────────────────────────────────────
APP_DIR = os.path.dirname(os.path.abspath(__file__))
# 智谱 API Key 放在程序同目录的 .env 文件中（格式见 .env.example）；
# 本地开发时可用环境变量 AIGC_ENV_FILE 指向其它位置的 .env
ENV_FILE = os.environ.get("AIGC_ENV_FILE") or os.path.join(APP_DIR, ".env")
SETTINGS_FILE = os.path.join(APP_DIR, "team_settings.json")
HISTORY_DIR = os.path.join(APP_DIR, "history")
# 智谱有两个互不通用的站点：国内站 open.bigmodel.cn、国际站 api.z.ai。
# 两边的 Key 不能混用，所以端点允许在 .env 里用 ZAI_BASE_URL 覆盖。
ZHIPU_BASE = "https://api.z.ai/api/paas/v4"
OLLAMA_API = "http://127.0.0.1:11434"

# 智谱常见的可用模型（可自行编辑补充）
ZHIPU_MODELS = [
    "glm-4.7-flash", "glm-4.5", "glm-4.5-air", "glm-4.6", "glm-4.7",
    "glm-5", "glm-5-turbo", "glm-5.1", "glm-5.2", "glm-5.3", "glm-5.3-flash",
]

# 默认角色定义：name, 中文名, 颜色, 默认模型源, 默认模型, 人设
DEFAULT_ROLES = [
    ("manager",   "经理",   "#2D7DFF", "zhipu",  "glm-4.7-flash",
     "你是项目经理，主持讨论：先拆解问题；出现分歧时裁决；最后把方案整理成明确分工。所有发言必须用中文，简洁有观点，每次发言不超过150字，直接说内容，不要寒暄。"),
    ("planner",   "策划",   "#FF7A2D", "ollama", "qwen2.5:7b",
     "你是创意策划：负责提点子和方案设计，敢于反驳别人，但认可已被说服的观点。所有发言必须用中文，简洁有观点，每次发言不超过150字，直接说内容，不要寒暄。"),
    ("engineer",  "工程师", "#2EA84B", "zhipu",  "glm-4.7-flash",
     "你是技术专家：负责评估可行性、指出风险、给落地建议。所有发言必须用中文，简洁有观点，每次发言不超过150字，直接说内容，不要寒暄。"),
    ("reviewer",  "评审",   "#9B59D0", "ollama", "qwen2.5:7b",
     "你是评审官：负责挑漏洞把关。当经理给出明确分工且方案合理时，简短总结并在最后一行单独输出：APPROVE。所有发言必须用中文，简洁有观点，每次发言不超过150字，直接说内容，不要寒暄。"),
]


# ── 配置读写 ───────────────────────────────────────────────────
def default_settings():
    """返回默认配置（与旧版行为一致：GLM×2 + Qwen×2）。"""
    return {
        "roles": {
            name: {
                "display": cn, "color": color,
                "source": src, "model": model,
                "base_url": "", "api_key": "",
                "system_prompt": prompt,
            }
            for name, cn, color, src, model, prompt in DEFAULT_ROLES
        }
    }


def load_settings():
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        # 与默认配置合并，保证新增角色/字段有值
        base = default_settings()
        for name in base["roles"]:
            if name in data.get("roles", {}):
                base["roles"][name].update(data["roles"][name])
        return base
    except Exception:
        return default_settings()


def save_settings(settings):
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)


# ── 历史记录读写 ───────────────────────────────────────────────
def list_history():
    """返回历史记录列表（新的在前）：[{id, time, task, file}...]"""
    if not os.path.isdir(HISTORY_DIR):
        return []
    items = []
    for fn in os.listdir(HISTORY_DIR):
        if not fn.endswith(".json"):
            continue
        try:
            with open(os.path.join(HISTORY_DIR, fn), "r", encoding="utf-8") as f:
                data = json.load(f)
            items.append({
                "id": fn[:-5],
                "time": data.get("time", ""),
                "task": data.get("task", ""),
                "file": os.path.join(HISTORY_DIR, fn),
            })
        except Exception:
            continue
    items.sort(key=lambda x: x["time"], reverse=True)
    return items


def save_history(entries, task, time_str):
    """把一次会话存为 JSON 历史文件。"""
    try:
        os.makedirs(HISTORY_DIR, exist_ok=True)
        safe = "".join(c if c not in r'\/:*?"<>|' else "_" for c in task)[:30] or "任务"
        ts = time_str.replace(":", "-").replace(" ", "_")  # 冒号在文件名中非法
        fn = f"{ts} {safe}.json"
        data = {"time": time_str, "task": task, "messages": entries}
        with open(os.path.join(HISTORY_DIR, fn), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return fn
    except Exception:
        return ""


def get_ollama_models():
    """查询本地 Ollama 的模型列表，失败返回空列表。"""
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # 本地直连，不走代理
        req = urllib.request.Request(f"{OLLAMA_API}/api/tags")
        with opener.open(req, timeout=5) as r:
            data = json.loads(r.read().decode("utf-8"))
        return [m["name"] for m in data.get("models", [])]
    except Exception:
        return []


# ── 模型客户端工厂 ─────────────────────────────────────────────
def read_env_value(name: str, default: str = "") -> str:
    """从 .env 里取一个值（不存在就返回默认值）。"""
    try:
        from dotenv import dotenv_values
        value = dotenv_values(ENV_FILE).get(name)
        return (value or "").strip() or default
    except Exception:
        return default


def format_error(exc: BaseException) -> str:
    """把异常压成一句人话，并尽量带上底层原因（裸 401 对用户毫无信息量）。"""
    parts = []
    cur = exc
    depth = 0
    while cur is not None and depth < 4:
        text = "".join(traceback.format_exception_only(type(cur), cur)).strip()
        if text and text not in parts:
            parts.append(text)
        cur = cur.__cause__ or cur.__context__
        depth += 1
    text = "\n".join(parts) or exc.__class__.__name__
    low = text.lower()
    if "401" in text or "authentication" in low or "invalid api key" in low or "unauthorized" in low:
        text += ("\n提示：Key 或接口地址不匹配。智谱国内站（open.bigmodel.cn）和国际站"
                 "（api.z.ai）的 Key 互不通用，可在 .env 里用 ZAI_BASE_URL 指定端点。")
    return text


def stop_reason_cn(reason: str) -> str:
    """把 AutoGen 的英文终止原因翻成中文（界面全中文，混一句英文很突兀）。"""
    low = (reason or "").lower()
    if "maximum number of messages" in low:
        return "已达最大发言轮数"
    if "mentioned" in low:
        return "评审通过（提到 APPROVE）"
    if "external" in low or "cancel" in low:
        return "被外部终止"
    return reason or "未知"


def make_client(role_cfg):
    """按角色配置构建模型客户端。
    返回 (client, 来源描述)。来源: zhipu / ollama / custom

    注意：调用方必须负责 close()，否则每次讨论都会漏掉一组 HTTP 连接。
    """
    source = role_cfg.get("source", "zhipu")
    model = (role_cfg.get("model") or "").strip()
    if source == "ollama":
        if not model:
            raise RuntimeError("没有选本地模型（先在命令行执行 ollama pull qwen2.5:7b）")
        from autogen_ext.models.ollama import OllamaChatCompletionClient
        return OllamaChatCompletionClient(model=model), "本地 Ollama"
    if source == "custom":
        from autogen_ext.models.openai import OpenAIChatCompletionClient
        base = (role_cfg.get("base_url") or "").strip()
        key = (role_cfg.get("api_key") or "").strip()
        if not base:
            raise RuntimeError("选了「自定义 API」但没填 Base URL（例如 https://api.deepseek.com/v1）")
        if not key:
            raise RuntimeError("选了「自定义 API」但没填 API Key")
        if not model:
            raise RuntimeError("选了「自定义 API」但没填模型名（例如 deepseek-chat）")
        return OpenAIChatCompletionClient(
            model=model, base_url=base, api_key=key,
            max_retries=6, timeout=240,
        ), "自定义 API"
    # 默认：智谱 GLM
    from glm_client import GLMStudioClient
    key = read_env_value("ZAI_API_KEY")
    if not key:
        raise RuntimeError(
            f"未找到智谱 API Key：请把 .env.example 复制为 .env，并填入 ZAI_API_KEY\n"
            f"（当前读取的路径：{ENV_FILE}）"
        )
    base_url = read_env_value("ZAI_BASE_URL", ZHIPU_BASE)
    return GLMStudioClient(
        model=model or "glm-4.7-flash",
        base_url=base_url, api_key=key,
        max_retries=6, timeout=240, retry_429=8, retry_429_base=5.0,
        model_info={"vision": False, "function_calling": True, "json_output": True,
                    "structured_output": True, "family": "unknown"},
    ), "云端智谱 GLM"


def build_team(settings, clients=None):
    """按配置构建团队，并为各角色挂载工具（定义为"手臂"）。

    clients 是出参列表：每建好一个模型客户端就追加进去。
    之所以用出参而不是返回值，是因为建队中途失败时（比如第 3 个角色 Key 配错），
    调用方仍然要能拿到前两个客户端并关掉它们，否则连接就漏了。
    """
    from autogen_agentchat.agents import AssistantAgent
    from autogen_agentchat.conditions import MaxMessageTermination, TextMentionTermination
    from autogen_agentchat.teams import RoundRobinGroupChat
    from tools import build_tools

    if clients is None:
        clients = []

    # 每个角色的工具分配（团队整体拥有搜索/文件/GitHub/命令全部能力）
    ROLE_TOOLS = {
        "manager":   ["web_search", "list_files", "read_text_file"],
        "planner":   ["web_search", "list_files", "read_text_file"],
        "engineer":  ["web_search", "read_text_file", "write_text_file", "list_files",
                      "github_api", "run_powershell"],
        "reviewer":  ["web_search", "list_files", "read_text_file", "write_text_file"],
    }
    tools = build_tools()

    roles = settings["roles"]
    agents = []
    for name in ("manager", "planner", "engineer", "reviewer"):
        cfg = roles.get(name) or {}
        cn = cfg.get("display", name)
        try:
            client, _ = make_client(cfg)
        except Exception as exc:
            # 说清楚是哪个角色配错了。旧版只抛一句 401，用户根本不知道该改哪一格。
            raise RuntimeError(f"角色「{cn}」的模型配置不可用：\n{format_error(exc)}") from exc
        clients.append(client)
        role_tools = [tools[t] for t in ROLE_TOOLS.get(name, []) if t in tools]
        agents.append(AssistantAgent(
            name=name, model_client=client,
            system_message=cfg.get("system_prompt", ""),
            tools=role_tools,
        ))
    return RoundRobinGroupChat(
        agents,
        termination_condition=MaxMessageTermination(18) | TextMentionTermination("APPROVE"),
    )


# ── 后台线程：跑一次团队对话 ────────────────────────────────────
class ChatWorker(QThread):
    msg_received = Signal(str, str, str)     # 中文角色名, 来源, 内容
    tool_event = Signal(str, str, str)       # 中文角色名, 工具名, 结果摘要（🔧 工具过程）
    chat_finished = Signal(str)              # 正常结束（带终止原因）
    chat_stopped = Signal()                  # 用户主动停止
    chat_error = Signal(str)                 # 错误信息

    def __init__(self, task: str, settings, parent=None):
        super().__init__(parent)
        self.task = task
        self.settings = settings
        self._stop_requested = False
        self._loop = None        # 本线程的 event loop
        self._aio_task = None    # 正在跑的 asyncio 任务，供主线程跨线程取消
        self._clients = []       # 本轮的模型客户端，收尾时统一 close
        self._name_to_cn = {
            name: (cfg.get("display") or name)
            for name, cfg in (settings.get("roles") or {}).items()
        }

    def stop(self):
        """请求停止（主线程调用）。

        旧版只把 _stop 置 True，等循环自己转一圈才 break —— 正在飞的模型请求
        （timeout=240s）根本不会醒，用户点了"停止"最长要干等 4 分钟；而且 break 之后
        不发任何信号，主界面永远停在"正在停止…"，输入框和发送按钮再也不会解禁。
        这里直接 cancel 掉 asyncio 任务：await 立刻中断，HTTP 请求随之取消。
        """
        self._stop_requested = True
        loop, task = self._loop, self._aio_task
        if loop is None or task is None:
            return
        try:
            loop.call_soon_threadsafe(task.cancel)   # 唯一线程安全的跨线程取消方式
        except RuntimeError:
            pass    # loop 已关闭，说明任务本来也结束了

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        stopped = False
        try:
            if self._stop_requested:
                # 极端时序：线程还没起来，用户就点了停止
                self.chat_stopped.emit()
                return
            self._aio_task = loop.create_task(self._run_team())
            loop.run_until_complete(self._aio_task)
        except asyncio.CancelledError:
            stopped = True
        except Exception as exc:
            self.chat_error.emit(format_error(exc))
        finally:
            self._shutdown_loop(loop)
        # 关键：无论正常结束、被取消还是出错，都必须有一个终态信号出去，
        # 否则主界面卡在"讨论中"，按钮永久禁用，只能重启程序。
        if stopped:
            self.chat_stopped.emit()

    def _shutdown_loop(self, loop):
        """收尾：取消残留任务 → 关闭模型客户端 → 收掉异步生成器 → 关闭 loop。

        这些动作放在被取消的任务之外执行，避免在已取消的上下文里 await 又被中断。
        """
        try:
            pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
            for t in pending:
                t.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            if self._clients:
                loop.run_until_complete(self._close_clients())
            loop.run_until_complete(loop.shutdown_asyncgens())
        except Exception:
            pass
        finally:
            self._aio_task = None
            self._loop = None
            try:
                loop.close()
            except Exception:
                pass

    async def _close_clients(self):
        """关掉本轮的模型客户端。不关的话每讨论一次就漏一组 HTTP 连接。"""
        clients, self._clients = self._clients, []
        for client in clients:
            try:
                await client.close()
            except Exception:
                pass

    async def _run_team(self):
        """建队并跑一轮讨论。客户端的释放统一交给 _shutdown_loop。"""
        team = build_team(self.settings, self._clients)
        async for event in team.run_stream(task=self.task):
            self._handle_event(event)

    def _cn(self, src):
        return self._name_to_cn.get(src, src)

    def _handle_event(self, event):
        kind = event.__class__.__name__
        if kind == "TextMessage":
            src = getattr(event, "source", "")
            self.msg_received.emit(self._cn(src), src, str(getattr(event, "content", "")))
        elif kind == "ToolCallRequestEvent":
            # 某个角色要调用工具：显示 工具名(参数)
            src = getattr(event, "source", "")
            parts = []
            for fc in (getattr(event, "content", []) or []):
                fc_name = getattr(fc, "name", "?")
                fc_args = getattr(fc, "arguments", "") or ""
                if isinstance(fc_args, str) and len(fc_args) > 120:
                    fc_args = fc_args[:120] + "…"      # 参数可能很长
                parts.append(f"{fc_name}({fc_args})")
            if parts:
                self.tool_event.emit(self._cn(src), "→ 调用工具", " ".join(parts))
        elif kind == "ToolCallExecutionEvent":
            # 工具执行完成：显示简短结果摘要
            src = getattr(event, "source", "")
            for res in (getattr(event, "content", []) or []):
                res_name = getattr(res, "name", "?")
                res_out = getattr(res, "content", "")
                if isinstance(res_out, str) and len(res_out) > 300:
                    res_out = res_out[:300] + "…"
                self.tool_event.emit(self._cn(src), "✓ 工具返回", f"{res_name}: {res_out}")
        elif kind == "TaskResult":
            self.chat_finished.emit(getattr(event, "stop_reason", ""))


# ── 设置对话框：逐角色配置模型 ───────────────────────────────────
class SettingsDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("模型与角色设置")
        self.setMinimumSize(720, 620)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        title = QLabel("配置每个角色的 AI 模型")
        title.setStyleSheet("font-size: 17px; font-weight: 700; color: #1E293B;")
        hint = QLabel(
            "来源说明：\n"
            "· 云端智谱 GLM —— 智谱免费/付费 API（Key 来自 ai-group-chat\\.env）\n"
            "· 本地 Ollama —— 你自己电脑上跑的开源模型（无需联网）\n"
            "· 自定义 API —— 任何 OpenAI 兼容接口，如 DeepSeek / Kimi（需填 Base URL 和 Key）"
        )
        hint.setStyleSheet("font-size: 12px; color: #64748B;")
        root.addWidget(title)
        root.addWidget(hint)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        vbox = QVBoxLayout(inner)
        self.role_boxes = {}

        for name, cn, color, _, _, _ in DEFAULT_ROLES:
            cfg = self.settings["roles"].get(name, {})
            group = QGroupBox(f"{cn}（{name}）")
            form = QFormLayout(group)

            src_box = QComboBox()
            src_box.addItem("云端智谱 GLM", "zhipu")
            src_box.addItem("本地 Ollama", "ollama")
            src_box.addItem("自定义 API（DeepSeek/Kimi 等）", "custom")
            src_box.setCurrentIndex(max(0, src_box.findData(cfg.get("source", "zhipu"))))
            src_box.currentIndexChanged.connect(lambda _i, n=name: self._on_source_changed(n))
            form.addRow("模型来源：", src_box)

            model_box = QComboBox()
            model_box.setEditable(True)
            form.addRow("模型：", model_box)

            base_edit = QLineEdit(cfg.get("base_url", ""))
            base_edit.setPlaceholderText("例如 https://api.deepseek.com/v1")
            base_edit.setVisible(cfg.get("source", "zhipu") == "custom")
            form.addRow("Base URL（自定义时填）：", base_edit)

            key_edit = QLineEdit(cfg.get("api_key", ""))
            key_edit.setPlaceholderText("API Key（自定义时填）")
            key_edit.setEchoMode(QLineEdit.Password)
            key_edit.setVisible(cfg.get("source", "zhipu") == "custom")
            form.addRow("API Key（自定义时填）：", key_edit)

            prompt_edit = QPlainTextEdit(cfg.get("system_prompt", ""))
            prompt_edit.setPlaceholderText("这个角色的说话风格、职责……")
            prompt_edit.setMaximumHeight(72)
            form.addRow("人设提示词：", prompt_edit)

            vbox.addWidget(group)
            self.role_boxes[name] = {
                "source": src_box, "model": model_box,
                "base_url": base_edit, "api_key": key_edit, "prompt": prompt_edit,
            }
            self._fill_models(name, keep=cfg.get("model", ""))

        vbox.addStretch(1)
        scroll.setWidget(inner)
        root.addWidget(scroll, stretch=1)

        btns = QHBoxLayout()
        save_btn = QPushButton("保存配置")
        save_btn.setStyleSheet(
            "QPushButton { background: #2D7DFF; color: white; border: none;"
            "border-radius: 8px; padding: 9px 26px; font-size: 14px; font-weight: 600; }"
            "QPushButton:hover { background: #1E6AE6; }"
        )
        save_btn.clicked.connect(self._on_save)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btns.addStretch(1)
        btns.addWidget(save_btn)
        btns.addWidget(cancel_btn)
        root.addLayout(btns)

    def _fill_models(self, name, keep=""):
        """按来源填充模型下拉选项。"""
        box = self.role_boxes[name]
        source = box["source"].currentData()
        model_box = box["model"]
        model_box.blockSignals(True)
        model_box.clear()
        if source == "zhipu":
            options = ZHIPU_MODELS
        elif source == "ollama":
            local = get_ollama_models()
            options = local if local else ["（未发现本地模型，先下载 qwen2.5:7b）"]
        else:
            options = []
        model_box.addItems(options)
        if keep and keep in options:
            model_box.setCurrentText(keep)
        elif keep and options:
            model_box.setCurrentText(keep)  # 保持旧值（可编辑，允许手动输入）
        model_box.blockSignals(False)
        # 自定义时显示 base/key
        is_custom = source == "custom"
        box["base_url"].setVisible(is_custom)
        box["api_key"].setVisible(is_custom)

    def _on_source_changed(self, name):
        self._fill_models(name)

    def _on_save(self):
        for name, box in self.role_boxes.items():
            self.settings["roles"][name]["source"] = box["source"].currentData()
            self.settings["roles"][name]["model"] = box["model"].currentText().strip()
            self.settings["roles"][name]["base_url"] = box["base_url"].text().strip()
            self.settings["roles"][name]["api_key"] = box["api_key"].text().strip()
            self.settings["roles"][name]["system_prompt"] = box["prompt"].toPlainText().strip()
        save_settings(self.settings)
        QMessageBox.information(self, "已保存", "配置已保存，下次发送任务时生效。")
        self.accept()


# ── 历史记录对话框 ─────────────────────────────────────────────
class HistoryDialog(QDialog):
    """左侧历史列表，右侧显示所选会话的完整记录。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("历史聊天记录")
        self.resize(900, 600)
        self._build()

    def _build(self):
        root = QHBoxLayout(self)

        # 左侧：列表
        left = QVBoxLayout()
        tip = QLabel("点一条记录查看当时完整对话")
        tip.setStyleSheet("font-size: 12px; color: #64748B;")
        left.addWidget(tip)
        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet(
            "QListWidget { border: 1px solid #E2E8F0; border-radius: 8px; font-size: 13px; }"
            "QListWidget::item { padding: 8px; }"
            "QListWidget::item:selected { background: #DBEAFE; color: #1E40AF; }"
        )
        self.list_widget.currentRowChanged.connect(self._show_item)
        left.addWidget(self.list_widget, stretch=1)
        count_label = QLabel()
        self.count_label = count_label
        self.count_label.setStyleSheet("font-size: 12px; color: #94A3B8;")
        left.addWidget(count_label)
        root.addLayout(left, stretch=2)

        # 右侧：内容
        self.view = QTextBrowser()
        self.view.setOpenLinks(False)
        self.view.setStyleSheet(
            "QTextBrowser { background: #FAFBFC; border: 1px solid #E2E8F0;"
            "border-radius: 8px; padding: 10px; font-size: 14px; }"
        )
        root.addWidget(self.view, stretch=3)

        self._load()

    def _load(self):
        self.items = list_history()
        self.list_widget.clear()
        for it in self.items:
            task = it["task"][:36] + ("…" if len(it["task"]) > 36 else "")
            self.list_widget.addItem(f"{it['time']}\n📋 {task}")
        n = len(self.items)
        self.count_label.setText(f"共 {n} 条记录，保存在 {HISTORY_DIR}")
        if self.items:
            self.list_widget.setCurrentRow(0)

    def _show_item(self, row):
        if row < 0 or row >= len(self.items):
            return
        it = self.items[row]
        try:
            with open(it["file"], "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            self.view.setPlainText("（记录读取失败）")
            return
        self.view.clear()
        task = data.get("task", "")
        self.view.append("📝 任务：" + task)
        self.view.append("")
        for m in data.get("messages", []):
            kind = m.get("kind", "")
            name = m.get("name", "")
            content = m.get("content", "")
            if kind == "user":
                cursor = self.view.textCursor()
                fmt = QTextCharFormat()
                fmt.setForeground(QColor("#0F172A"))
                fmt.setFontWeight(QFont.Bold)
                cursor.movePosition(QTextCursor.End)
                cursor.insertText("📝 我的任务：" + content + "\n\n", fmt)
            elif kind == "msg":
                color = m.get("color", "#334155")
                cursor = self.view.textCursor()
                fmt = QTextCharFormat()
                fmt.setForeground(QColor(color))
                fmt.setFontWeight(QFont.Bold)
                cursor.movePosition(QTextCursor.End)
                cursor.insertText(f"【{name}】{content}", fmt)
                cursor.insertText("\n\n")
            elif kind == "tool":
                cursor = self.view.textCursor()
                fmt = QTextCharFormat()
                fmt.setForeground(QColor("#7C8AA5"))
                fmt.setFontItalic(True)
                fmt.setFontPointSize(12)
                cursor.movePosition(QTextCursor.End)
                cursor.insertText(f"🔧 {name} {m.get('phase','')}：{content}", fmt)
                cursor.insertText("\n\n")
            elif kind == "system":
                cursor = self.view.textCursor()
                fmt = QTextCharFormat()
                fmt.setForeground(QColor("#64748B"))
                fmt.setFontItalic(True)
                cursor.movePosition(QTextCursor.End)
                cursor.insertText(f"⚙️ {content}", fmt)
                cursor.insertText("\n\n")
        self.view.moveCursor(QTextCursor.Start)


# ── 主窗口 ──────────────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.worker = None
        self.settings = load_settings()
        self.cur_task = ""
        self.cur_messages = []   # 当前会话消息记录：{kind, name, content, detail}
        self.setWindowTitle("AI 团队群聊 · 桌面版")
        self.setMinimumSize(880, 660)
        try:
            # 兼容两种图标命名：v1.1 起打包的是 app.ico，旧版曾引用 ai_group.ico
            icon_path = next(
                (p for p in (os.path.join(APP_DIR, "app.ico"),
                             os.path.join(APP_DIR, "ai_group.ico"))
                 if os.path.exists(p)),
                None,
            )
            if icon_path:
                self.setWindowIcon(QIcon(icon_path))
        except Exception:
            pass
        self._build_ui()
        self._append_system("已就绪：四个 AI 已装载不同模型，输入任务即可开始群聊。点右上「配置模型」可自由切换每个角色的 AI。")

    # ── UI ──
    def _build_ui(self):
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 14, 16, 12)
        root.setSpacing(10)

        # 标题行（含设置按钮）
        head = QHBoxLayout()
        title_col = QVBoxLayout()
        title = QLabel("🎙️ AI 团队群聊 · 异构模型")
        title.setStyleSheet("font-size: 20px; font-weight: 700; color: #1E293B;")
        subtitle = QLabel("同一窗口里，四个不同模型的 AI 讨论并分工 —— 每个角色的 AI 可自由配置")
        subtitle.setStyleSheet("font-size: 12px; color: #64748B;")
        title_col.addWidget(title)
        title_col.addWidget(subtitle)
        head.addLayout(title_col, stretch=1)
        self.settings_btn = QPushButton("⚙ 配置模型")
        self.settings_btn.setStyleSheet(
            "QPushButton { background: white; color: #2D7DFF; border: 1.5px solid #2D7DFF;"
            "border-radius: 8px; padding: 8px 18px; font-size: 13px; font-weight: 600; }"
            "QPushButton:hover { background: #EEF4FF; }"
        )
        self.settings_btn.clicked.connect(self.open_settings)
        head.addWidget(self.settings_btn)
        self.history_btn = QPushButton("📜 历史记录")
        self.history_btn.setStyleSheet(
            "QPushButton { background: white; color: #475569; border: 1.5px solid #CBD5E1;"
            "border-radius: 8px; padding: 8px 18px; font-size: 13px; font-weight: 600; }"
            "QPushButton:hover { background: #F1F5F9; }"
        )
        self.history_btn.clicked.connect(self.open_history)
        head.addWidget(self.history_btn)
        root.addLayout(head)

        # 角色徽章行（动态刷新）
        self.badge_row = QHBoxLayout()
        self.badge_row.addStretch(1)
        root.addLayout(self.badge_row)
        self._refresh_badges()

        # 对话区
        self.chat_view = QTextBrowser()
        self.chat_view.setOpenLinks(False)
        self.chat_view.setStyleSheet(
            "QTextBrowser { background: #FAFBFC; border: 1px solid #E2E8F0;"
            "border-radius: 10px; padding: 8px; font-size: 14px; }"
        )
        root.addWidget(self.chat_view, stretch=1)

        # 输入区
        input_row = QHBoxLayout()
        self.task_input = QLineEdit()
        self.task_input.setPlaceholderText("输入任务，例如：设计一个五一成都 3 天旅行方案，4 人人均预算 2500……")
        self.task_input.setStyleSheet(
            "QLineEdit { padding: 10px 12px; border: 1px solid #CBD5E1; border-radius: 8px;"
            "font-size: 14px; background: white; }"
            "QLineEdit:focus { border-color: #2D7DFF; }"
        )
        self.task_input.returnPressed.connect(self.start_chat)
        self.send_btn = QPushButton("发送任务")
        self.send_btn.setStyleSheet(
            "QPushButton { background: #2D7DFF; color: white; border: none; border-radius: 8px;"
            "padding: 10px 22px; font-size: 14px; font-weight: 600; }"
            "QPushButton:hover { background: #1E6AE6; }"
            "QPushButton:disabled { background: #94A3B8; }"
        )
        self.send_btn.clicked.connect(self.start_chat)
        self.stop_btn = QPushButton("停止")
        self.stop_btn.setEnabled(False)
        self.stop_btn.setStyleSheet(
            "QPushButton { background: #EF4444; color: white; border: none; border-radius: 8px;"
            "padding: 10px 18px; font-size: 14px; font-weight: 600; }"
            "QPushButton:hover { background: #DC2626; }"
            "QPushButton:disabled { background: #CBD5E1; color: #64748B; }"
        )
        self.stop_btn.clicked.connect(self.stop_chat)
        input_row.addWidget(self.task_input, stretch=1)
        input_row.addWidget(self.send_btn)
        input_row.addWidget(self.stop_btn)
        root.addLayout(input_row)

        # 状态栏
        self.status = QLabel("状态：空闲")
        self.status.setStyleSheet("font-size: 12px; color: #64748B;")
        root.addWidget(self.status)

        self.setCentralWidget(central)

    def _refresh_badges(self):
        """按当前配置刷新角色徽章。"""
        # 清空旧徽章
        while self.badge_row.count():
            item = self.badge_row.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        for name, cn, color, _, _, _ in DEFAULT_ROLES:
            cfg = self.settings["roles"].get(name, {})
            src_txt = {"zhipu": "云端GLM", "ollama": "本地Ollama", "custom": "自定义API"}.get(
                cfg.get("source", "zhipu"), "?")
            color = cfg.get("color", color)
            badge = QLabel(f" {cn} · {src_txt} · {cfg.get('model', '')} ")
            badge.setStyleSheet(
                f"background: {color}22; color: {color}; border: 1px solid {color}55;"
                "border-radius: 12px; padding: 4px 12px; font-size: 12px; font-weight: 600;"
            )
            self.badge_row.addWidget(badge)
        self.badge_row.addStretch(1)

    # ── 行为 ──
    def open_settings(self):
        dlg = SettingsDialog(self.settings, self)
        if dlg.exec() == QDialog.Accepted:
            self.settings = load_settings()
            self._refresh_badges()
            self._append_system("模型配置已更新，发送新任务将使用新配置。")

    def open_history(self):
        dlg = HistoryDialog(self)
        dlg.exec()

    def _dispose_worker(self):
        """回收上一轮的线程对象。

        QThread 还在跑就被覆盖/回收会直接崩（QThread: Destroyed while thread is
        still running）。这里调用前已经确认线程不在运行，所以 wait 会立刻返回。
        """
        old, self.worker = self.worker, None
        if old is None:
            return
        old.wait(3000)
        old.deleteLater()

    def start_chat(self):
        task = self.task_input.text().strip()
        if not task:
            self.status.setText("状态：请先输入任务")
            return
        if self.worker is not None and self.worker.isRunning():
            self.status.setText("状态：正在讨论中，请先停止")
            return
        self._dispose_worker()

        self.chat_view.clear()
        self.cur_task = task
        self.cur_messages = [{"kind": "user", "name": "我", "content": task}]
        self.task_input.setEnabled(False)
        self.send_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.status.setText("状态：讨论中…")
        self._append_user(task)

        self.worker = ChatWorker(task, self.settings)
        self.worker.msg_received.connect(self._on_msg)
        self.worker.tool_event.connect(self._on_tool)
        self.worker.chat_finished.connect(self._on_finished)
        self.worker.chat_stopped.connect(self._on_stopped)
        self.worker.chat_error.connect(self._on_error)
        self.worker.start()

    def stop_chat(self):
        if self.worker is None or not self.worker.isRunning():
            return
        self.stop_btn.setEnabled(False)      # 防连点，也表明请求已收到
        self.status.setText("状态：正在停止…")
        self.worker.stop()

    def closeEvent(self, event):
        """关窗口前先把后台线程停干净，否则 QThread 被销毁时程序会崩。"""
        if self.worker is not None and self.worker.isRunning():
            self.worker.stop()
            if not self.worker.wait(5000):
                self.worker.terminate()      # 兜底：真停不下来就别让它拖着进程
                self.worker.wait(1000)
        super().closeEvent(event)

    def _on_tool(self, cn_name, phase, detail):
        """显示工具调用过程（灰色小字，夹在发言之间）。"""
        self.chat_view.append("")
        cursor = self.chat_view.textCursor()
        fmt = QTextCharFormat()
        fmt.setForeground(QColor("#7C8AA5"))
        fmt.setFontItalic(True)
        fmt.setFontPointSize(12)
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(f"🔧 {cn_name} {phase}：{detail}", fmt)
        self.chat_view.moveCursor(QTextCursor.End)
        self.cur_messages.append({"kind": "tool", "name": cn_name,
                                  "phase": phase, "content": detail})

    def _on_msg(self, cn_name, src, content):
        role = next((r for r in DEFAULT_ROLES if r[0] == src), None)
        cfg = self.settings["roles"].get(src, {})
        color = cfg.get("color") or (role[2] if role else "#334155")
        src_label = {"zhipu": "云端GLM", "ollama": "本地Ollama", "custom": "自定义API"}.get(
            cfg.get("source", "zhipu"), "")
        self.chat_view.append("")
        cursor = self.chat_view.textCursor()
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        fmt.setFontWeight(QFont.Bold)
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(f"【{cn_name}】", fmt)
        fmt2 = QTextCharFormat()
        fmt2.setForeground(QColor("#94A3B8"))
        fmt2.setFontPointSize(11)
        cursor.insertText(f"  （{src_label}）", fmt2)
        cursor.insertText("\n")
        cursor.insertText(content)
        self.chat_view.moveCursor(QTextCursor.End)
        self.cur_messages.append({"kind": "msg", "name": cn_name,
                                  "content": content, "color": color})

    def _save_cur_history(self, ending=""):
        """把当前会话保存为历史记录。"""
        if not self.cur_task or not self.cur_messages:
            return
        entries = list(self.cur_messages)
        if ending:
            entries.append({"kind": "system", "name": "", "content": ending})
        import datetime
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        save_history(entries, self.cur_task, now)
        self.cur_task = ""
        self.cur_messages = []

    def _on_finished(self, reason):
        self._append_system(f"讨论结束。终止原因：{stop_reason_cn(reason)}")
        self._save_cur_history(ending=f"讨论结束（{stop_reason_cn(reason)}）")
        self._reset_ui("空闲（可发送新任务）")

    def _on_stopped(self):
        """用户点了停止。旧版没有这个分支，界面会永久卡在"正在停止…"。"""
        self._append_system("已停止本次讨论，对话过程已存入历史记录。")
        self._save_cur_history(ending="用户手动停止了讨论")
        self._reset_ui("已停止（可发送新任务）")

    def _on_error(self, err):
        self._append_system(f"发生错误：{err}")
        QMessageBox.critical(self, "出错了", f"AI 团队运行出错：\n\n{err}")
        self._save_cur_history(ending=f"发生错误：{err}")
        self._reset_ui("出错，请重试")

    def _reset_ui(self, state_text):
        self.task_input.setEnabled(True)
        self.send_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.status.setText(f"状态：{state_text}")

    def _append_system(self, text):
        self.chat_view.append("")
        cursor = self.chat_view.textCursor()
        fmt = QTextCharFormat()
        fmt.setForeground(QColor("#64748B"))
        fmt.setFontItalic(True)
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(f"⚙️ {text}", fmt)
        self.chat_view.moveCursor(QTextCursor.End)

    def _append_user(self, text):
        self.chat_view.append("")
        cursor = self.chat_view.textCursor()
        fmt = QTextCharFormat()
        fmt.setForeground(QColor("#0F172A"))
        fmt.setFontWeight(QFont.Bold)
        cursor.movePosition(QTextCursor.End)
        cursor.insertText("📝 我的任务：", fmt)
        cursor.insertText(text)
        self.chat_view.moveCursor(QTextCursor.End)


def main():
    app = QApplication(sys.argv)
    app.setFont(QFont("Microsoft YaHei UI", 10))
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()