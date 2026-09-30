# -*- coding: utf-8 -*-
"""TeamSession 回归测试：多轮追问 / 流式输出 / 优雅停止 / 强制停止兜底。

用一个仿真团队替掉真实模型，全程不联网。仿真团队刻意复刻 AutoGen 的真实语义：
  · run_stream 每轮**自己重置终止条件**（真实实现就是这么做的，不重置会误报）
  · 终止由外部 ExternalTermination 驱动，任务消息 source="user"
  · 上下文跨轮累积（history 一直长）
  · 流式分片拼起来 = 最终 TextMessage 的内容

直接运行：python tests/test_team_session.py
"""
import asyncio
import os
import sys
import time

from PySide6.QtCore import QCoreApplication, Qt

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from autogen_agentchat.base import TaskResult                    # noqa: E402
from autogen_agentchat.messages import (ModelClientStreamingChunkEvent,  # noqa: E402
                                        TextMessage)

import team_session                                              # noqa: E402

app = QCoreApplication.instance() or QCoreApplication(sys.argv)

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, ok))
    print(("  [OK]   " if ok else "  [FAIL] ") + name + (("  -> " + detail) if detail and not ok else ""))


SETTINGS = {
    "max_messages": 18,
    # 角色是有序列表：发言顺序就是列表顺序
    "roles": [
        {"id": "manager", "name": "经理", "color": "#2D7DFF", "enabled": True,
         "source": "zhipu", "model": "glm-4.7-flash", "tools": []},
        {"id": "planner", "name": "策划", "color": "#FF7A2D", "enabled": True,
         "source": "zhipu", "model": "glm-4.7-flash", "tools": []},
    ],
}


class FakeTeam:
    """仿真团队。

    per_turn      本轮产出多少条发言
    delay         每条发言的"模型耗时"
    ignore_external  True = 无视外部终止（模拟网络挂死，用来验强制停止兜底）
    mismatch       True = 最终文本与流式分片不一致（用来验"以最终文本为准"）
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

    async def run_stream(self, task=None):
        # 真实 AutoGen 每轮开跑时会重置终止条件，这里必须照做
        await self.external.reset()
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
            # 真实情况下分片拼起来就等于最终文本；mismatch 时故意不一致，
            # 用来验证"以最终文本为准"这条兜底
            final = streamed + "（最终）" if self.mismatch else streamed
            yield TextMessage(content=final, source=source)
            self.history.append(("msg", final))
        yield TaskResult(messages=[], stop_reason=stop_reason)

    async def reset(self):
        self.reset_count += 1


class _FakeClient:
    async def close(self):
        return None


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


def make_session(**kwargs):
    holder = {}

    def fake_build(settings, clients, external):
        team = FakeTeam(external, **kwargs)
        clients.append(_FakeClient())
        holder["team"] = team
        return team

    team_session.build_team = fake_build
    session = team_session.TeamSession(dict(SETTINGS))
    rec = Recorder(session)
    session.start()
    session._ready.wait(5)
    return session, rec, holder


def wait_for(predicate, timeout=8.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


print("=" * 72)
print("A. 多轮追问：上下文跨轮延续，且能一直问下去")
print("=" * 72)
session, rec, holder = make_session(per_turn=2)
check("首轮任务被接受", session.ask("第一个问题"))
check("首轮跑完", wait_for(lambda: len(rec.finished) >= 1),
      "finished=%s errors=%s" % (rec.finished, rec.errors))
team = holder["team"]
n1 = len(team.history)

check("追问被接受", session.ask("追问一"))
check("追问跑完", wait_for(lambda: len(rec.finished) >= 2), "errors=%s" % rec.errors)
n2 = len(team.history)
check("上下文跨轮累积", n2 > n1, "n1=%d n2=%d" % (n1, n2))
check("追问没有重建团队（上下文没丢）", not session._needs_rebuild)
check("会话带着上下文", session.has_context)
check("两轮共 4 条发言（走流式收口）", len(rec.ends) == 4, "ends=%d" % len(rec.ends))
check("两轮都没报错", not rec.errors, str(rec.errors)[:200])

print()
print("=" * 72)
print("B. 流式输出：先开流、逐段推送、最后收口")
print("=" * 72)
check("有流式开始信号", len(rec.starts) > 0, "starts=%d" % len(rec.starts))
check("有流式分片", len(rec.chunks) > 0, "chunks=%d" % len(rec.chunks))
check("有流式收口", len(rec.ends) == 4, "ends=%d" % len(rec.ends))
check("分片拼起来等于收口文本", "".join(rec.chunks[:3]) == rec.ends[0],
      "chunks[:3]=%r ends[0]=%r" % (rec.chunks[:3], rec.ends[0] if rec.ends else None))
check("流式内容不再重复走 message 信号", len(rec.messages) == 0,
      "message=%d" % len(rec.messages))
check("开流次数 = 发言条数", len(rec.starts) == 4, "starts=%d" % len(rec.starts))
session.shutdown()

print()
print("=" * 72)
print("B2. 最终文本与流式分片不一致时，以最终文本为准")
print("=" * 72)
session, rec, holder = make_session(per_turn=1, mismatch=True)
session.ask("问一句")
wait_for(lambda: len(rec.ends) >= 1)
check("收口文本用的是最终内容", rec.ends and rec.ends[0].endswith("（最终）"),
      "ends=%r" % rec.ends)
check("流式分片本身不含最终标记", rec.chunks and "（最终）" not in "".join(rec.chunks),
      "chunks=%r" % rec.chunks)
session.shutdown()

print()
print("=" * 72)
print("C. 优雅停止：停得下来，会话还能继续用")
print("=" * 72)
session, rec, holder = make_session(per_turn=100000, delay=0.05)   # 长任务
session.ask("一个很长的任务")
wait_for(lambda: len(rec.chunks) >= 1, timeout=5)

t0 = time.time()
session.stop()
ok = wait_for(lambda: len(rec.stopped) + len(rec.finished) >= 1, timeout=15)
elapsed = time.time() - t0
print("   停止耗时 %.2fs，stopped=%s finished=%s" % (elapsed, rec.stopped, rec.finished))
check("停止后本轮结束了", ok)
check("走的是优雅停止（False=上下文仍在）", rec.stopped == [False],
      "stopped=%s（[False]=优雅，[True]=强制并重置了上下文）" % rec.stopped)
check("优雅停止不报成'讨论结束'", rec.finished == [], "finished=%s" % rec.finished)
check("优雅停止后会话没坏", not session._needs_rebuild)

rec.finished.clear()
rec.stopped.clear()
rec.errors.clear()
holder["team"].per_turn = 2          # 仿真团队本来在"跑 10 万轮"，追问前调小
session.ask("停止之后的追问")
check("停止后还能追问", wait_for(lambda: len(rec.finished) >= 1 or rec.errors, timeout=10),
      "finished=%s errors=%s" % (rec.finished, rec.errors))
check("追问没有报错", not rec.errors, str(rec.errors)[:200])
check("追问是正常结束，没被误报成停止", rec.finished == ["已达最大发言轮数"],
      "finished=%s stopped=%s" % (rec.finished, rec.stopped))
session.shutdown()

print()
print("=" * 72)
print("D. 强制停止兜底：优雅停不下来时必须强制，并如实告知上下文已重置")
print("=" * 72)
team_session.GRACE_SECONDS = 1.0        # 缩短等待，让测试跑得快
session, rec, holder = make_session(per_turn=100000, delay=0.05, ignore_external=True)

session.ask("会卡住的任务")
wait_for(lambda: len(rec.chunks) >= 1, timeout=5)

t0 = time.time()
session.stop()
ok = wait_for(lambda: len(rec.stopped) >= 1, timeout=20)
elapsed = time.time() - t0
print("   兜底触发耗时 %.2fs，stopped=%s" % (elapsed, rec.stopped))
check("优雅停止超时后触发了兜底", ok, "20 秒内没等到 stopped")
check("兜底标记为强制停止（True=上下文已重置）", rec.stopped == [True], "stopped=%s" % rec.stopped)
check("兜底后团队被重置过", holder["team"].reset_count >= 1,
      "reset_count=%d" % holder["team"].reset_count)

# 关键：强制停止之后会话必须还能用，不能就此废掉
rec.finished.clear()
rec.stopped.clear()
rec.errors.clear()
holder["team"].ignore_external = False
holder["team"].per_turn = 2          # 同上：追问前把"跑不完的轮数"调小
session.ask("强制停止之后的追问")
check("强制停止后仍能继续追问",
      wait_for(lambda: len(rec.finished) >= 1 or rec.errors, timeout=12),
      "finished=%s errors=%s" % (rec.finished, rec.errors))
check("继续追问没有报错", not rec.errors, str(rec.errors)[:200])
session.shutdown()
team_session.GRACE_SECONDS = 12.0

print()
failed = [n for n, ok in RESULTS if not ok]
print("=" * 72)
print("通过 %d 项，失败 %d 项" % (len(RESULTS) - len(failed), len(failed)))
for n in failed:
    print("  - " + n)
sys.exit(1 if failed else 0)
