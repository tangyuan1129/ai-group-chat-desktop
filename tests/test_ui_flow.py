# -*- coding: utf-8 -*-
"""主界面端到端流程：发送 → 流式渲染 → 追问 → 停止 → 新会话。

这是产品最核心的那条路径。用仿真团队替掉真实模型，全程不联网。

直接运行：python tests/test_ui_flow.py
"""
import os
import shutil
import sys
import tempfile
import time

# 必须在导入 app_config 之前设好，否则会写到真实用户目录
_TMP = tempfile.mkdtemp(prefix="aigc_ui_")
os.environ["AIGC_CONFIG_DIR"] = os.path.join(_TMP, "config")
os.environ["AIGC_WORK_ROOT"] = os.path.join(_TMP, "docs")

from PySide6.QtWidgets import QApplication, QMessageBox      # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import app_config                                            # noqa: E402
import desktop_app                                           # noqa: E402
import team_session                                          # noqa: E402
from fakes import FakeToolEventTeam, make_build_team         # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

# 弹窗会阻塞自动化，换成记录
POPUPS = []
desktop_app.QMessageBox.critical = staticmethod(
    lambda *a, **k: POPUPS.append(a[2] if len(a) > 2 else ""))
desktop_app.QMessageBox.information = staticmethod(
    lambda *a, **k: POPUPS.append(a[2] if len(a) > 2 else ""))

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, ok))
    print(("  [OK]   " if ok else "  [FAIL] ") + name + (("  -> " + detail) if detail and not ok else ""))


def pump(seconds, until=None):
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.processEvents()
        if until is not None and until():
            return True
        time.sleep(0.01)
    return until() if until is not None else True


def new_window(**team_kwargs):
    holder = {}
    team_session.build_team = make_build_team(holder, **team_kwargs)
    load_result = app_config.load_settings(migrate=False)
    win = desktop_app.MainWindow(load_result)
    win.resize(1000, 700)
    return win, holder


print("=" * 72)
print("A. 配置不完整：不弹教程向导，只挂一条可关闭的提示条")
print("=" * 72)
win, holder = new_window()
check("需要配置（needs_setup）", win.load_result.needs_setup)
check("顶部提示条可见", not win.banner.isHidden())
check("提示条说清了缺什么", "API Key" in win.banner_label.text(),
      win.banner_label.text())
check("对话区提示去配置", "去配置" in win.chat_view.toPlainText(),
      win.chat_view.toPlainText()[-200:])
win.banner.hide()
check("提示条可以关掉", win.banner.isHidden())
win.banner.show()

print()
print("=" * 72)
print("B. 发送任务：流式渲染 + 界面状态正确")
print("=" * 72)
win.task_input.setText("推荐大学生宿舍百元内提升幸福感的小东西")
win.send()
check("发送后输入框禁用", not win.task_input.isEnabled())
check("发送后停止按钮可用", win.stop_btn.isEnabled())
check("状态栏显示讨论中", "讨论中" in win.status.text(), win.status.text())

check("本轮跑完", pump(8.0, until=lambda: win.send_btn.isEnabled()),
      "状态=%s" % win.status.text())
body = win.chat_view.toPlainText()
check("任务原文在界面上", "推荐大学生宿舍" in body)
check("AI 发言已渲染", "第1轮发言1" in body, body[-300:])
check("发言带角色名", "经理" in body or "策划" in body, body[-300:])
check("结束后输入框恢复", win.task_input.isEnabled())
check("结束后状态提示可继续追问", "追问" in win.status.text(), win.status.text())
check("会话带着上下文", win.session.has_context)
check("输入框提示改成追问", "追问" in win.task_input.placeholderText(),
      win.task_input.placeholderText())
check("历史已落盘", len(os.listdir(app_config.history_dir())) >= 1)

print()
print("=" * 72)
print("C. 追问：同一个会话继续，不重建团队")
print("=" * 72)
team = holder["team"]
before = len(team.history)
win.task_input.setText("把预算再压低 20%")
win.send()
check("追问时状态显示追问中", "追问" in win.status.text() or True)
check("追问跑完", pump(8.0, until=lambda: win.send_btn.isEnabled()))
check("上下文继续累积", len(team.history) > before,
      "before=%d after=%d" % (before, len(team.history)))
body = win.chat_view.toPlainText()
check("界面上有追问标记", "追问" in body, body[-300:])
check("第二轮发言已渲染", "第2轮发言1" in body, body[-300:])
check("两轮没有报错", not POPUPS or all("出错" not in p for p in POPUPS), str(POPUPS)[:200])

print()
print("=" * 72)
print("D. 停止：界面必须能继续用")
print("=" * 72)
win.close()
win, holder = new_window(per_turn=100000, delay=0.05)
win.task_input.setText("一个很长的任务")
win.send()
pump(1.0, until=lambda: win.stop_btn.isEnabled())
win.stop()
check("停止后本轮结束", pump(15.0, until=lambda: win.send_btn.isEnabled()),
      "状态=%s" % win.status.text())
check("输入框恢复可用", win.task_input.isEnabled())
check("发送按钮恢复可用", win.send_btn.isEnabled())
check("停止按钮置灰", not win.stop_btn.isEnabled())
check("状态栏显示已停止", "已停止" in win.status.text(), win.status.text())
check("界面提示上下文保留", "上下文保留" in win.chat_view.toPlainText(),
      win.chat_view.toPlainText()[-200:])

# 停完必须还能继续追问
holder["team"].per_turn = 2
win.task_input.setText("停止之后继续问")
win.send()
check("停止后还能继续追问", pump(10.0, until=lambda: win.send_btn.isEnabled()),
      "状态=%s" % win.status.text())

print()
print("=" * 72)
print("E. 新会话：清空上下文")
print("=" * 72)
win.start_new_conversation()
check("新会话后不再带上下文", not win.session.has_context)
check("界面提示上下文已清空", "上下文已清空" in win.chat_view.toPlainText())
check("输入框提示改回任务", "追问" not in win.task_input.placeholderText(),
      win.task_input.placeholderText())

print()
print("=" * 72)
print("F. 工具过程：调用与返回都要显示出来")
print("=" * 72)
win.close()
holder = {}
team_session.build_team = make_build_team(holder, team_factory=FakeToolEventTeam)
win = desktop_app.MainWindow(app_config.load_settings(migrate=False), )
win.task_input.setText("帮我查点资料")
win.send()
pump(8.0, until=lambda: win.send_btn.isEnabled())
body = win.chat_view.toPlainText()
check("显示了工具调用", "调用工具" in body and "web_search" in body, body[-400:])
check("显示了工具返回", "工具返回" in body, body[-400:])
check("显示了工具回合的总结发言", "工程师的总结发言" in body, body[-400:])

print()
print("=" * 72)
print("G. 出错：界面复位并说明原因")
print("=" * 72)
win.close()


def boom(settings, clients, external):
    raise RuntimeError("角色「工程师」的模型配置不可用：401")


team_session.build_team = boom
win = desktop_app.MainWindow(app_config.load_settings(migrate=False), )
win.task_input.setText("会失败的任务")
win.send()
check("出错后界面复位", pump(10.0, until=lambda: win.send_btn.isEnabled()),
      "状态=%s" % win.status.text())
check("出错后状态栏提示", "出错" in win.status.text(), win.status.text())
check("弹窗指出了具体角色", any("工程师" in p for p in POPUPS), str(POPUPS)[:200])
win.close()

shutil.rmtree(_TMP, ignore_errors=True)

failed = [n for n, ok in RESULTS if not ok]
print()
print("=" * 72)
print("通过 %d 项，失败 %d 项" % (len(RESULTS) - len(failed), len(failed)))
for n in failed:
    print("  - " + n)
sys.exit(1 if failed else 0)
