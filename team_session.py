# -*- coding: utf-8 -*-
"""团队会话：多轮追问 + 流式输出 + 优雅停止。

与旧版 ChatWorker 的根本区别
----------------------------
旧版每发一个任务就 build_team 一次，跑完连客户端一起丢掉 —— 结果是**不能追问**，
而且每轮漏一组 HTTP 连接。这里是**长期存活的会话**：团队、模型客户端、事件循环
都常驻，同一个 team 连续 run_stream，上下文自然延续（实测：第 2 轮 agent 上下文
从 4 条涨到 7 条，第一轮内容仍在）。

停止为什么不能用"取消 asyncio 任务"
-----------------------------------
AutoGen 文档原话：*Setting the cancellation token potentially put the team in an
inconsistent state... To gracefully stop the team, use ExternalTermination instead.*
单次任务里取消无所谓（团队用完就丢），但多轮会话里取消会污染状态，下一轮直接坏。
所以这里：**先 ExternalTermination 优雅停**（状态一致、上下文保留），
超过 GRACE_SECONDS 还没停（比如网络挂死）才强制取消，并**如实告诉用户上下文已重置**。

线程模型
--------
本类是一个 QThread，独占一个 asyncio 事件循环。主线程只通过 _post() 往
loop 里投递命令（call_soon_threadsafe 是唯一线程安全的跨线程手段），
所有 asyncio 对象都只在这个线程里碰。
"""
import asyncio
import threading

from PySide6.QtCore import QThread, Signal

from app_config import ROLE_ORDER, SOURCE_SHORT
from app_logging import get_logger, register_secret
from llm import format_error, make_client

log = get_logger("session")

# 优雅停止的等待上限。正常情况一次模型调用几秒钟就结束，用不到兜底；
# 这个值只在网络挂死时兜住"点了停止却永远停不下来"。
GRACE_SECONDS = 12.0

STOP_REASON_CN = (
    ("maximum number of messages", "已达最大发言轮数"),
    ("external termination", "手动停止"),
    ("mentioned", "评审通过（提到 APPROVE）"),
    ("external", "被外部终止"),
)


def stop_reason_cn(reason: str) -> str:
    low = (reason or "").lower()
    for needle, cn in STOP_REASON_CN:
        if needle in low:
            return cn
    return reason or "未知"


def build_team(settings, clients, external):
    """按配置建队。clients 是出参列表：建到一半失败时调用方仍能拿到已建好的客户端。

    reflect_on_tool_use=True 是刻意的：否则 AI 调完工具后，界面上会出现一段原始的
    [FunctionCall]/[FunctionExecutionResult] 文本，而不是模型读懂结果后的自然语言回答。
    产品不该把内部协议暴露给用户。
    """
    from autogen_agentchat.agents import AssistantAgent
    from autogen_agentchat.conditions import MaxMessageTermination, TextMentionTermination
    from autogen_agentchat.teams import RoundRobinGroupChat
    from tools import build_tools

    ROLE_TOOLS = {
        "manager":  ["web_search", "list_files", "read_text_file"],
        "planner":  ["web_search", "list_files", "read_text_file"],
        "engineer": ["web_search", "read_text_file", "write_text_file", "list_files",
                     "github_api", "run_powershell"],
        "reviewer": ["web_search", "list_files", "read_text_file", "write_text_file"],
    }

    tools = build_tools()
    roles = settings.get("roles") or {}
    agents = []
    for name in ROLE_ORDER:
        cfg = roles.get(name) or {}
        cn = cfg.get("display") or name
        try:
            client, _ = make_client(cfg, settings)
        except Exception as exc:
            raise RuntimeError("角色「%s」的模型配置不可用：\n%s" % (cn, format_error(exc))) from exc
        clients.append(client)
        agents.append(AssistantAgent(
            name=name, model_client=client,
            system_message=cfg.get("system_prompt", ""),
            tools=[tools[t] for t in ROLE_TOOLS.get(name, []) if t in tools],
            model_client_stream=True,      # 流式：逐字显示，用户不用盯着空屏等
            reflect_on_tool_use=True,      # 让模型读懂工具结果再回答
        ))

    max_messages = settings.get("max_messages") or 18
    return RoundRobinGroupChat(
        agents,
        termination_condition=(
            MaxMessageTermination(max_messages)
            | TextMentionTermination("APPROVE")
            | external
        ),
    )


class TeamSession(QThread):
    # ── 消息 ──
    message = Signal(str, str, str)        # 中文角色名, 内部名, 内容
    stream_start = Signal(str, str)        # 中文角色名, 颜色
    stream_chunk = Signal(str)             # 文本片段
    stream_end = Signal(str)               # 该条发言的最终文本
    tool_event = Signal(str, str, str)     # 中文角色名, 阶段, 详情
    # ── 轮次 ──
    turn_finished = Signal(str)            # 终止原因（中文）
    turn_stopped = Signal(bool)            # True = 强制停止，上下文已重置
    turn_error = Signal(str)
    # ── 会话 ──
    session_ready = Signal()               # 首次成功建队（UI 可以提示"可以追问了"）

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._loop = None
        self._queue = None
        self._ready = threading.Event()
        self._team = None
        self._clients = []
        self._external = None
        self._turn_task = None
        self._stop_timer = None
        self._needs_rebuild = True
        self._context_lost = False
        self._stop_requested = False
        self._stream_source = None
        self._stream_buf = ""
        self._first_build_done = False
        self._closing = False

    # ── 主线程可调用的接口 ──────────────────────────────────────
    def ask(self, task: str) -> bool:
        """提交一轮任务。首轮即新会话，之后即为追问（上下文延续）。"""
        if not self._ready.wait(timeout=10):
            return False
        return self._post("ask", task)

    def stop(self):
        """请求停止：先优雅，超时才强制。

        _external.set() 只是置一个 bool，跨线程安全，所以立刻做（让本轮尽快停）；
        "本轮是否被用户停过" 这个标记则交给事件循环去设，避免主线程读到半截状态、
        也避免上一轮的停止标记漏到下一轮去。
        """
        if self._external is not None:
            self._external.set()
        self._post("mark_stop")
        self._arm_force_timer()

    def apply_settings(self, settings):
        """配置变了。下一轮会重建团队 —— 上下文会丢，UI 需如实告知。"""
        self._settings = settings
        self._needs_rebuild = True

    def new_conversation(self):
        """开新会话：丢掉上下文，下一轮重新建队。

        _context_lost 在主线程**同步**置位，不等事件循环处理命令 —— 否则界面刚点完
        "新会话"就去读 has_context，读到的还是旧值，输入框提示不会跟着变。
        """
        self._context_lost = True
        self._needs_rebuild = True
        self._post("new")

    def shutdown(self, wait_ms: int = 8000) -> bool:
        """关闭会话并释放客户端。窗口关闭时必须调用，否则 QThread 被销毁会崩。"""
        self._closing = True
        if self._external is not None:
            self._external.set()
        self._post("quit")
        if self.isRunning():
            return self.wait(wait_ms)
        return True

    def wait_ready(self, timeout: float = 10.0) -> bool:
        """等待事件循环就绪（主线程调用，供 UI 启动会话后同步）。"""
        return self._ready.wait(timeout)

    @property
    def has_context(self) -> bool:
        """当前是否带着上一轮的上下文（决定"新会话"按钮要不要亮）。"""
        return (self._team is not None) and not self._needs_rebuild and not self._context_lost

    # ── 跨线程投递 ─────────────────────────────────────────────
    def _post(self, cmd, payload=None) -> bool:
        loop, queue = self._loop, self._queue
        if loop is None or queue is None:
            return False
        try:
            loop.call_soon_threadsafe(queue.put_nowait, (cmd, payload))
            return True
        except RuntimeError:
            return False       # loop 已关闭

    def _arm_force_timer(self):
        self._cancel_force_timer()
        timer = threading.Timer(GRACE_SECONDS, self._force_cancel)
        timer.daemon = True
        self._stop_timer = timer
        timer.start()

    def _cancel_force_timer(self):
        timer, self._stop_timer = self._stop_timer, None
        if timer is not None:
            timer.cancel()

    def _force_cancel(self):
        """优雅停止超时了。强制取消本轮，并如实标记上下文已丢。"""
        if self._closing:
            return
        log.warning("优雅停止 %.0f 秒未生效，强制取消本轮", GRACE_SECONDS)
        self._post("force_cancel")

    # ── 线程主体 ───────────────────────────────────────────────
    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        try:
            loop.run_until_complete(self._main())
        except Exception:
            log.exception("会话线程异常退出")
        finally:
            self._teardown_loop(loop)

    def _teardown_loop(self, loop):
        try:
            pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
            for t in pending:
                t.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.run_until_complete(loop.shutdown_asyncgens())
        except Exception:
            pass
        self._loop = None
        self._queue = None
        try:
            loop.close()
        except Exception:
            pass

    async def _main(self):
        self._queue = asyncio.Queue()
        self._ready.set()
        try:
            while True:
                cmd, payload = await self._queue.get()
                if cmd == "quit":
                    break
                if cmd == "ask":
                    if self._turn_task is not None and not self._turn_task.done():
                        self.turn_error.emit("上一轮还没结束，请等它跑完或先点停止。")
                        continue
                    self._turn_task = asyncio.create_task(self._turn(payload))
                    self._turn_task.add_done_callback(self._on_turn_done)
                elif cmd == "mark_stop":
                    # 只有真的有一轮在跑才算"用户停了这一轮"。
                    # 否则停止标记会留到下一轮，把正常结束误报成"已停止"。
                    if self._turn_task is not None and not self._turn_task.done():
                        self._stop_requested = True
                    else:
                        self._cancel_force_timer()
                elif cmd == "new":
                    if self._turn_task is not None and not self._turn_task.done():
                        self.turn_error.emit("正在讨论中，请先停止再开新会话。")
                        continue
                    self._needs_rebuild = True
                    self._context_lost = True
                    await self._close_team()
                    log.info("已开新会话，上下文清空")
                elif cmd == "force_cancel":
                    if self._turn_task is not None and not self._turn_task.done():
                        self._turn_task.cancel()
        finally:
            await self._close_team()

    def _on_turn_done(self, task):
        self._cancel_force_timer()
        if task.cancelled():
            asyncio.create_task(self._after_forced_stop())
            return
        exc = task.exception()
        if exc is not None:
            log.error("本轮出错：%s", format_error(exc))
            self.turn_error.emit(format_error(exc))

    async def _after_forced_stop(self):
        """强制停止之后必须让团队回到可用状态，否则下一次追问会直接报错。"""
        reset_ok = await self._try_reset()
        if not reset_ok:
            self._needs_rebuild = True
        self._context_lost = True
        self.turn_stopped.emit(True)

    async def _try_reset(self) -> bool:
        if self._team is None:
            return True
        for attempt in range(3):
            try:
                await asyncio.wait_for(self._team.reset(), timeout=10)
                return True
            except Exception as exc:
                log.warning("重置会话第 %d 次失败：%s", attempt + 1, exc)
                await asyncio.sleep(0.3)
        return False

    async def _ensure_team(self):
        if self._team is not None and not self._needs_rebuild:
            return
        await self._close_team()
        clients = []
        external = None
        from autogen_agentchat.conditions import ExternalTermination
        external = ExternalTermination()
        try:
            team = build_team(self._settings, clients, external)
        except Exception:
            for client in clients:      # 建到一半失败也要把已建的关掉
                try:
                    await client.close()
                except Exception:
                    pass
            raise
        self._team, self._clients, self._external = team, clients, external
        self._needs_rebuild = False
        self._context_lost = False
        if not self._first_build_done:
            self._first_build_done = True
            self.session_ready.emit()

    async def _close_team(self):
        team, self._team = self._team, None
        self._external = None
        clients, self._clients = self._clients, []
        for client in clients:
            try:
                await client.close()
            except Exception:
                pass
        del team

    async def _turn(self, task: str):
        await self._ensure_team()
        # 防御性重置：AutoGen 每轮开跑时会自己重置终止条件，但显式重置一次更稳，
        # 免得上一轮的"外部终止"残留把这一轮一启动就判定为结束。
        if self._external is not None:
            try:
                await self._external.reset()
            except Exception:
                pass
        self._stop_requested = False
        log.info("开始一轮：%s", task[:60])
        stream = self._team.run_stream(task=task)
        try:
            async for event in stream:
                self._handle(event)
        finally:
            self._cancel_force_timer()
            self._close_stream()
            try:
                await stream.aclose()     # 让 run_stream 的 finally 复位 _is_running
            except Exception:
                pass
        log.info("本轮结束")

    # ── 事件分发 ───────────────────────────────────────────────
    def _cn(self, source: str) -> str:
        cfg = (self._settings.get("roles") or {}).get(source) or {}
        return cfg.get("display") or source

    def _color(self, source: str) -> str:
        cfg = (self._settings.get("roles") or {}).get(source) or {}
        return cfg.get("color") or "#334155"

    def _close_stream(self, final_text=None):
        if self._stream_source is None:
            return
        text = self._stream_buf if final_text is None else final_text
        self._stream_source = None
        self._stream_buf = ""
        self.stream_end.emit(text)

    def _handle(self, event):
        name = event.__class__.__name__

        if name == "ModelClientStreamingChunkEvent":
            source = getattr(event, "source", "")
            chunk = str(getattr(event, "content", "") or "")
            if not chunk:
                return
            if self._stream_source != source:
                self._close_stream()
                self._stream_source = source
                self._stream_buf = ""
                self.stream_start.emit(self._cn(source), self._color(source))
            self._stream_buf += chunk
            self.stream_chunk.emit(chunk)
            return

        if name == "ToolCallRequestEvent":
            self._close_stream()
            source = getattr(event, "source", "")
            parts = []
            for call in (getattr(event, "content", []) or []):
                tool = getattr(call, "name", "?")
                args = getattr(call, "arguments", "") or ""
                if isinstance(args, str) and len(args) > 120:
                    args = args[:120] + "…"
                parts.append("%s(%s)" % (tool, args))
            if parts:
                self.tool_event.emit(self._cn(source), "→ 调用工具", " ".join(parts))
            return

        if name == "ToolCallExecutionEvent":
            self._close_stream()
            source = getattr(event, "source", "")
            for result in (getattr(event, "content", []) or []):
                tool = getattr(result, "name", "?")
                out = getattr(result, "content", "")
                if isinstance(out, str) and len(out) > 300:
                    out = out[:300] + "…"
                self.tool_event.emit(self._cn(source), "✓ 工具返回", "%s: %s" % (tool, out))
            return

        if name in ("TextMessage", "ToolCallSummaryMessage"):
            source = getattr(event, "source", "")
            if source == "user":
                return                     # 用户的任务界面已经显示过了，不重复
            content = str(getattr(event, "content", "") or "")
            if self._stream_source == source and self._stream_buf:
                self._close_stream(content)          # 流式收口，用最终文本对齐
            else:
                self._close_stream()
                if content.strip():
                    self.message.emit(self._cn(source), source, content)
            return

        if name == "TaskResult":
            self._close_stream()
            # 用户点过停止的这一轮，走"已停止"而不是"讨论结束"。
            # 光靠 stop_reason 的英文字符串去猜太脆，这里用显式标记。
            if self._stop_requested:
                self.turn_stopped.emit(False)     # False = 优雅停止，上下文仍在
            else:
                self.turn_finished.emit(stop_reason_cn(getattr(event, "stop_reason", "")))
