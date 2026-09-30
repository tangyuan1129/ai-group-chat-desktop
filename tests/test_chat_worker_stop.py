# -*- coding: utf-8 -*-
"""「停止」按钮的回归测试 —— 这是让程序废掉的那个 bug。

同时跑新版和 git HEAD 的旧版，用同一套用例对比：
  · 旧版：stop() 只置标志位，正在飞的模型请求不会醒 → 线程停不下来；
          而且 break 之后不发任何终态信号 → 界面永久卡在"正在停止…"。
  · 新版：stop() 直接 cancel asyncio 任务 → 立刻中断，并必发 chat_stopped。

直接运行：python tests/test_chat_worker_stop.py
"""
import asyncio
import os
import subprocess
import sys
import tempfile
import time

from PySide6.QtCore import Qt, QCoreApplication

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

app = QCoreApplication.instance() or QCoreApplication(sys.argv)

# 修复前最后一个提交。固定哈希而不是用 HEAD —— 否则修复提交之后，
# 对照组就变成"自己跟自己比"，测试会静默失去意义。
PRE_FIX_COMMIT = "faeb65986a1bf813454037e69011dec40b69c9d3"

# 把修复前的旧版取出来，作为对照组
_TMP = tempfile.mkdtemp(prefix="aigc_old_")
with open(os.path.join(_TMP, "old_desktop_app.py"), "wb") as f:
    f.write(subprocess.check_output(
        ["git", "show", "%s:desktop_app.py" % PRE_FIX_COMMIT], cwd=REPO))
sys.path.insert(0, _TMP)

import desktop_app as new_mod          # noqa: E402
import old_desktop_app as old_mod      # noqa: E402

SLOW_SECONDS = 30          # 模拟一个"很慢的模型请求"（真实场景里 timeout=240s）
FAKE_SETTINGS = {"roles": {"manager": {"display": "经理"}}}


class SlowTeam:
    """run_stream 先睡 SLOW_SECONDS 才产出事件，模拟正在飞的 HTTP 请求。"""

    def __init__(self, seconds):
        self.seconds = seconds
        self.cancelled = False

    async def run_stream(self, task=None):
        try:
            await asyncio.sleep(self.seconds)
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        yield object()


def fake_build_team_new(settings, clients=None):
    return SlowTeam(SLOW_SECONDS)


def fake_build_team_old(settings):
    return SlowTeam(SLOW_SECONDS)


def connect(worker, events):
    """DirectConnection：信号在发射线程里同步触发，测试不需要跑事件循环。"""
    for name in ("chat_finished", "chat_error", "chat_stopped"):
        sig = getattr(worker, name, None)
        if sig is None:
            continue
        sig.connect(lambda *a, n=name: events.append(n), Qt.ConnectionType.DirectConnection)


def run_case(module, fake_build_team, label):
    module.build_team = fake_build_team
    worker = module.ChatWorker("测试任务", FAKE_SETTINGS)
    events = []
    connect(worker, events)

    worker.start()
    time.sleep(0.8)                      # 让它进入"模型请求中"
    t0 = time.time()
    worker.stop()
    stopped_in_time = worker.wait(6000)  # 最多等 6 秒
    elapsed = time.time() - t0
    print("  %-6s stop() 后线程结束：%-5s  耗时 %.2fs   收到信号：%s"
          % (label, stopped_in_time, elapsed, events or "（无）"))
    return worker, stopped_in_time, elapsed, events


def cleanup(worker):
    """旧版线程停不下来，测试结束前必须强杀，否则进程退出时 QThread 被销毁会崩。"""
    if worker is not None and worker.isRunning():
        worker.terminate()
        worker.wait(2000)


print("=" * 66)
print("场景：用户点了「停止」，但此刻有一个模型请求正在飞（模拟 %d 秒）" % SLOW_SECONDS)
print("=" * 66)
old_worker, old_ok, old_elapsed, old_events = run_case(old_mod, fake_build_team_old, "旧版")
cleanup(old_worker)
new_worker, new_ok, new_elapsed, new_events = run_case(new_mod, fake_build_team_new, "新版")
cleanup(new_worker)
print()

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(("  [OK]   " if ok else "  [FAIL] ") + name + (("  -> " + detail) if detail and not ok else ""))


print("[旧版] 应该复现两个 bug")
check("旧版：停止后线程卡住（复现 bug）", not old_ok, "旧版居然停了，用例失效")
check("旧版：不发任何终态信号（复现 bug）", old_events == [], "旧版发了信号：" + str(old_events))
print()
print("[新版] 应该都修好")
check("新版：停止后线程及时结束", new_ok, "6 秒内没停下来")
check("新版：1 秒内响应停止", new_elapsed < 1.0, "耗时 %.2fs" % new_elapsed)
check("新版：发出了 chat_stopped 信号", new_events == ["chat_stopped"], "实际：" + str(new_events))

print()
failed = [n for n, ok, _ in results if not ok]
print("=" * 66)
print("通过 %d 项，失败 %d 项" % (len(results) - len(failed), len(failed)))
sys.exit(1 if failed else 0)
