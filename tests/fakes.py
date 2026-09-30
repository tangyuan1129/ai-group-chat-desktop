# -*- coding: utf-8 -*-
"""测试用的仿真团队与信号记录器（多个测试共用）。

仿真团队刻意复刻 AutoGen 的真实语义，否则测试会给出假阳性/假阴性：
  · run_stream 每轮**自己重置终止条件**（真实实现就是这么做的）
  · 终止由外部 ExternalTermination 驱动，任务消息 source="user"
  · 上下文跨轮累积
  · 流式分片拼起来 = 最终 TextMessage 的内容
"""
import asyncio

from PySide6.QtCore import Qt

from autogen_agentchat.base import TaskResult
from autogen_agentchat.messages import ModelClientStreamingChunkEvent, TextMessage


class FakeClient:
    """假的模型客户端，只关心 close() 有没有被调用。"""

    def __init__(self, tag="client"):
        self.tag = tag
        self.closed = False

    async def close(self):
        self.closed = True


class FakeTeam:
    """仿真团队。

    per_turn        本轮产出多少条发言
    delay           每条发言的"模型耗时"（秒）
    streaming       是否发流式分片
    ignore_external True = 无视外部终止（模拟网络挂死，用来验强制停止兜底）
    mismatch        True = 最终文本与流式分片不一致（用来验"以最终文本为准"）
    """

    def __init__(self, external, per_turn=2, delay=0.03, streaming=True,
                 ignore_external=False, mismatch=False):
        self.external = external
        self.per_turn = per_turn
        self.delay = delay
        self.streaming = streaming
        self.ignore_external = ignore_external
        self.mismatch = mismatch
        self.history = []
        self.reset_count = 0
        self.tool_events = False

    async def run_stream(self, task=None):
        await self.external.reset()        # 真实 AutoGen 每轮都会重置终止条件
        self.history.append(("task", task))
        produced = 0
        stop_reason = "Maximum number of messages reached!"
        while produced < self.per_turn:
            await asyncio.sleep(self.delay)
            if not self.ignore_external:
                stop = await self.external([])
                if stop is not None:
                    stop_reason = stop.content
                    break
            produced += 1
            source = "manager" if produced % 2 else "planner"
            turn_no = len([h for h in self.history if h[0] == "task"])
            streamed = "【第%d轮发言%d】" % (turn_no, produced)
            if self.streaming:
                for piece in ("【", "第%d轮发言%d" % (turn_no, produced), "】"):
                    yield ModelClientStreamingChunkEvent(content=piece, source=source)
            final = streamed + "（最终）" if self.mismatch else streamed
            yield TextMessage(content=final, source=source)
            self.history.append(("msg", final))
        yield TaskResult(messages=[], stop_reason=stop_reason)

    async def reset(self):
        self.reset_count += 1


class FakeToolEventTeam(FakeTeam):
    """额外产出工具调用事件，用来验证工具过程也能渲染。"""

    async def run_stream(self, task=None):
        await self.external.reset()
        self.history.append(("task", task))
        from autogen_agentchat.messages import (ToolCallExecutionEvent,
                                                ToolCallRequestEvent)
        from autogen_core import FunctionCall
        from autogen_core.models import FunctionExecutionResult

        yield ToolCallRequestEvent(
            source="engineer",
            content=[FunctionCall(id="1", name="web_search", arguments='{"query": "测试"}')])
        yield ToolCallExecutionEvent(
            source="engineer",
            content=[FunctionExecutionResult(call_id="1", name="web_search",
                                             content="搜索到了 3 条结果", is_error=False)])
        yield TextMessage(content="工程师的总结发言", source="engineer")
        yield TaskResult(messages=[], stop_reason="Maximum number of messages reached!")


def make_build_team(holder, **kwargs):
    """返回一个可替换 team_session.build_team 的假函数，并把团队存进 holder。"""

    def fake_build(settings, clients, external):
        team = kwargs.pop("team_factory", FakeTeam)(external, **kwargs)
        clients.append(FakeClient())
        holder["team"] = team
        return team

    return fake_build


def make_build_team_with_clients(holder, clients_out, **kwargs):
    """同上，但把 FakeClient 也暴露出来，方便断言客户端有没有被关闭。"""

    def fake_build(settings, clients, external):
        team = FakeTeam(external, **kwargs)
        client = FakeClient()
        clients.append(client)
        clients_out.append(client)
        holder["team"] = team
        return team

    return fake_build


class Recorder:
    """收集会话发出的信号。DirectConnection 让记录在发射线程里同步发生。"""

    def __init__(self, session):
        self.messages, self.chunks, self.ends = [], [], []
        self.starts, self.tools, self.finished = [], [], []
        self.stopped, self.errors, self.ready = [], [], []
        d = Qt.ConnectionType.DirectConnection
        session.message.connect(lambda *a: self.messages.append(a), d)
        session.stream_start.connect(lambda *a: self.starts.append(a), d)
        session.stream_chunk.connect(lambda c: self.chunks.append(c), d)
        session.stream_end.connect(lambda t: self.ends.append(t), d)
        session.tool_event.connect(lambda *a: self.tools.append(a), d)
        session.turn_finished.connect(lambda r: self.finished.append(r), d)
        session.turn_stopped.connect(lambda f: self.stopped.append(f), d)
        session.turn_error.connect(lambda e: self.errors.append(e), d)
        session.session_ready.connect(lambda: self.ready.append(True), d)
