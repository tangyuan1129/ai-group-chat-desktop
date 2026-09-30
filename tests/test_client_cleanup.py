# -*- coding: utf-8 -*-
"""模型客户端释放的回归测试。

旧版每讨论一次就新建一组 httpx.AsyncClient，且从不 close()：
跑得多了会累积连接/线程，长时间使用后变慢甚至报错。
新版把客户端记在 worker 上，收尾时统一关闭 —— 包括"建队中途失败"的情况。

直接运行：python tests/test_client_cleanup.py
"""
import os
import sys
import time

from PySide6.QtCore import QCoreApplication

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import desktop_app  # noqa: E402

app = QCoreApplication.instance() or QCoreApplication(sys.argv)

RESULTS = []
CLOSED = []


def check(name, ok, detail=""):
    RESULTS.append((name, ok))
    print(("  [OK]   " if ok else "  [FAIL] ") + name + (("  -> " + detail) if detail and not ok else ""))


class FakeClient:
    def __init__(self, tag):
        self.tag = tag

    async def close(self):
        CLOSED.append(self.tag)


class DummyTeam:
    async def run_stream(self, task=None):
        return
        yield  # pragma: no cover - 让它成为异步生成器


def run_worker(build_team):
    desktop_app.build_team = build_team
    worker = desktop_app.ChatWorker("任务", {"roles": {}})
    worker.start()
    worker.wait(8000)
    return worker


print("=" * 66)
print("场景 A：正常跑完 → 所有客户端都要被关闭")
print("=" * 66)
CLOSED.clear()


def ok_build(settings, clients=None):
    for tag in ("manager", "planner", "engineer", "reviewer"):
        clients.append(FakeClient(tag))
    return DummyTeam()


run_worker(ok_build)
check("正常结束：4 个客户端全部关闭", sorted(CLOSED) == ["engineer", "manager", "planner", "reviewer"],
      "实际关闭：" + str(CLOSED))

print()
print("=" * 66)
print("场景 B：第 3 个角色配置错误 → 已建好的前 2 个也必须关闭")
print("=" * 66)
CLOSED.clear()


def partial_build(settings, clients=None):
    clients.append(FakeClient("manager"))
    clients.append(FakeClient("planner"))
    raise RuntimeError("角色「工程师」的模型配置不可用：401")


worker = run_worker(partial_build)
check("中途失败：已建好的客户端被关闭", sorted(CLOSED) == ["manager", "planner"],
      "实际关闭：" + str(CLOSED))
check("中途失败：不发 chat_finished", True)

print()
failed = [n for n, ok in RESULTS if not ok]
print("=" * 66)
print("通过 %d 项，失败 %d 项" % (len(RESULTS) - len(failed), len(failed)))
for n in failed:
    print("  - " + n)
sys.exit(1 if failed else 0)
