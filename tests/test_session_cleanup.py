# -*- coding: utf-8 -*-
"""模型客户端释放的回归测试。

旧版每讨论一次就新建一组 httpx.AsyncClient，且从不 close()：跑得多了会累积
连接和线程，长时间使用后变慢甚至报错。现在客户端由会话持有，在"开新会话"、
"重建团队"、"关闭程序"三个时机统一关闭，**包括建队中途失败的情况**。

直接运行：python tests/test_session_cleanup.py
"""
import os
import sys
import time

from PySide6.QtCore import QCoreApplication

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import team_session                                          # noqa: E402
from fakes import FakeClient, FakeTeam, Recorder             # noqa: E402

app = QCoreApplication.instance() or QCoreApplication(sys.argv)

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, ok))
    print(("  [OK]   " if ok else "  [FAIL] ") + name + (("  -> " + detail) if detail and not ok else ""))


SETTINGS = {
    "max_messages": 18,
    "roles": [
        {"id": "manager", "name": "经理", "color": "#2D7DFF", "enabled": True,
         "source": "zhipu", "model": "glm-4.7-flash", "tools": []},
        {"id": "planner", "name": "策划", "color": "#FF7A2D", "enabled": True,
         "source": "zhipu", "model": "glm-4.7-flash", "tools": []},
    ],
}


def pump(seconds, until=None):
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.processEvents()
        if until is not None and until():
            return True
        time.sleep(0.01)
    return until() if until is not None else True


def start_session(build_team):
    team_session.build_team = build_team
    session = team_session.TeamSession(dict(SETTINGS))
    rec = Recorder(session)
    session.start()
    session.wait_ready(5)
    return session, rec


print("=" * 72)
print("A. 会话存活期间客户端保持打开，开新会话时被关闭")
print("=" * 72)
created = []


def build_tracking(settings, clients, external):
    client = FakeClient()
    clients.append(client)
    created.append(client)
    return FakeTeam(external, per_turn=1, delay=0.01)


session, rec = start_session(build_tracking)
session.ask("第一轮")
check("第一轮跑完", pump(8.0, until=lambda: len(rec.finished) >= 1),
      "errors=%s" % rec.errors)
check("建了一个客户端", len(created) == 1, "created=%d" % len(created))
check("会话存活期间客户端没被关", not created[0].closed)

session.new_conversation()
check("开新会话后旧客户端被关闭", pump(5.0, until=lambda: created[0].closed),
      "closed=%s" % created[0].closed)

rec.finished.clear()
session.ask("第二轮")
check("新会话重新建了客户端", pump(8.0, until=lambda: len(created) == 2),
      "created=%d" % len(created))
check("第二轮跑完", pump(8.0, until=lambda: len(rec.finished) >= 1),
      "errors=%s" % rec.errors)
check("新客户端在会话存活期间没被关", not created[1].closed)

print()
print("=" * 72)
print("B. 关闭会话：客户端必须全部释放")
print("=" * 72)
session.shutdown()
check("关闭后最后一个客户端也被释放", pump(5.0, until=lambda: created[1].closed),
      "closed=%s" % created[1].closed)
check("会话线程已退出", not session.isRunning())

print()
print("=" * 72)
print("C. 建队中途失败：已经建好的客户端也必须关掉，不能漏")
print("=" * 72)
partial = []


def build_then_fail(settings, clients, external):
    for _ in range(2):
        client = FakeClient()
        clients.append(client)
        partial.append(client)
    raise RuntimeError("角色「工程师」的模型配置不可用：401")


session, rec = start_session(build_then_fail)
session.ask("会失败的任务")
check("失败被上报", pump(8.0, until=lambda: len(rec.errors) >= 1),
      "errors=%s finished=%s" % (rec.errors, rec.finished))
check("中途建好的客户端被关闭", pump(5.0, until=lambda: all(c.closed for c in partial)),
      "partial=%s" % [c.closed for c in partial])
check("没有把失败当成正常结束", rec.finished == [], "finished=%s" % rec.finished)
session.shutdown()

print()
failed = [n for n, ok in RESULTS if not ok]
print("=" * 72)
print("通过 %d 项，失败 %d 项" % (len(RESULTS) - len(failed), len(failed)))
for n in failed:
    print("  - " + n)
sys.exit(1 if failed else 0)
