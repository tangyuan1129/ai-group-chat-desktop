# -*- coding: utf-8 -*-
"""主界面端到端流程：发送 → 流式渲染 → 追问 → 停止 → 新对话。

界面按 ChatGPT 布局重做过，控件结构变了：
    输入区  win.composer.input / send_btn / stop_btn
    消息区  win.area（MessageArea，里面是一个个消息控件）
    发送    win.send_task(text)

用仿真团队替掉真实模型，全程不联网。

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

from PySide6.QtWidgets import QApplication, QLabel, QMessageBox     # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import app_config                                            # noqa: E402
import desktop_app                                           # noqa: E402
import team_session                                          # noqa: E402
import theme                                                 # noqa: E402
from fakes import FakeToolEventTeam, make_build_team         # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)
app.setStyleSheet(theme.app_stylesheet())

POPUPS = []
desktop_app.QMessageBox.critical = staticmethod(
    lambda *a, **k: POPUPS.append(a[2] if len(a) > 2 else ""))
desktop_app.QMessageBox.information = staticmethod(
    lambda *a, **k: POPUPS.append(a[2] if len(a) > 2 else ""))
desktop_app.QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)

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


def area_widgets(win):
    out = []
    for i in range(win.area.messages.count()):
        widget = win.area.messages.itemAt(i).widget()
        if widget is not None:
            out.append(widget)
    return out


def area_text(win) -> str:
    parts = []
    for widget in area_widgets(win):
        for lbl in widget.findChildren(QLabel):
            if lbl.text():
                parts.append(lbl.text())
    return "\n".join(parts)


def assistant_texts(win):
    return [w.text for w in area_widgets(win) if isinstance(w, desktop_app.AssistantMessage)]


def new_window(**team_kwargs):
    holder = {}
    team_session.build_team = make_build_team(holder, **team_kwargs)
    load_result = app_config.load_settings(migrate=False)
    win = desktop_app.MainWindow(load_result)
    win.resize(1040, 720)
    return win, holder


print("=" * 72)
print("A. 配置不完整：不弹教程向导，在对话流里给一条可操作的提示")
print("=" * 72)
win, holder = new_window()
check("需要配置（needs_setup）", win.load_result.needs_setup)
check("对话流里有提示", "还差" in area_text(win), area_text(win)[:200])
check("提示里点明缺什么", "API Key" in area_text(win), area_text(win)[:200])
check("有空状态引导", "有什么可以帮你的" in area_text(win), area_text(win)[:200])
check("侧栏有历史分组或为空", win.sidebar.history.count() >= 0)

print()
print("=" * 72)
print("B. 发送任务：流式渲染 + 输入区状态正确")
print("=" * 72)
win.composer.input.setText("推荐大学生宿舍百元内提升幸福感的小东西")
win.composer._submit()
check("发送后输入框禁用", not win.composer.input.isEnabled())
check("发送后进入运行态", win.composer.running)
check("发送后隐藏发送按钮", win.composer.send_btn.isHidden())
check("状态栏显示讨论中", "讨论中" in win.status.text(), win.status.text())

check("本轮跑完", pump(8.0, until=lambda: win.composer.input.isEnabled()),
      "状态=%s" % win.status.text())
text = area_text(win)
check("任务原文在界面上", "推荐大学生宿舍" in text)
check("AI 发言已渲染", any("第1轮发言1" in t for t in assistant_texts(win)),
      str(assistant_texts(win))[:200])
check("发言带角色名", "经理" in text or "策划" in text, text[:200])
check("结束后输入框恢复", win.composer.input.isEnabled())
check("结束后状态提示可追问", "追问" in win.status.text(), win.status.text())
check("会话带着上下文", win.session.has_context)
check("输入框提示改成追问", "追问" in win.composer.input.placeholderText(),
      win.composer.input.placeholderText())
check("历史已落盘", len(os.listdir(app_config.history_dir())) >= 1)
check("侧栏出现了这条会话", win.sidebar.history.count() >= 2,
      "侧栏条目数=%d" % win.sidebar.history.count())

print()
print("=" * 72)
print("C. 追问：同一个会话继续，不重建团队")
print("=" * 72)
team = holder["team"]
before = len(team.history)
win.send_task("把预算再压低 20%")
check("追问跑完", pump(8.0, until=lambda: win.composer.input.isEnabled()))
check("上下文继续累积", len(team.history) > before,
      "before=%d after=%d" % (before, len(team.history)))
check("第二轮发言已渲染", any("第2轮发言1" in t for t in assistant_texts(win)),
      str(assistant_texts(win))[:200])
check("两轮没有报错", not POPUPS or all("出错" not in p for p in POPUPS), str(POPUPS)[:200])

print()
print("=" * 72)
print("D. 停止：界面必须能继续用")
print("=" * 72)
win.close()
win, holder = new_window(per_turn=100000, delay=0.05)
win.send_task("一个很长的任务")
pump(1.0, until=lambda: win.composer.running)
win.stop()
check("停止后本轮结束", pump(15.0, until=lambda: not win.composer.running),
      "状态=%s" % win.status.text())
check("输入框恢复可用", win.composer.input.isEnabled())
check("发送按钮恢复可见", not win.composer.send_btn.isHidden())
check("停止按钮隐藏", win.composer.stop_btn.isHidden())
check("状态栏显示已停止", "已停止" in win.status.text(), win.status.text())
check("提示上下文保留", "上下文保留" in area_text(win), area_text(win)[-200:])

holder["team"].per_turn = 2
win.send_task("停止之后继续问")
check("停止后还能继续追问", pump(10.0, until=lambda: win.composer.input.isEnabled()),
      "状态=%s" % win.status.text())

print()
print("=" * 72)
print("E. 新对话：清空上下文")
print("=" * 72)
win.start_new_conversation()
check("新对话后不再带上下文", not win.session.has_context)
check("回到空状态", "有什么可以帮你的" in area_text(win), area_text(win)[:150])
check("标题回到新对话", win.title_label.text() == "新对话", win.title_label.text())
check("输入框提示改回任务", "追问" not in win.composer.input.placeholderText(),
      win.composer.input.placeholderText())

print()
print("=" * 72)
print("F. 工具过程：调用与返回都要显示出来")
print("=" * 72)
win.close()
holder = {}
team_session.build_team = make_build_team(holder, team_factory=FakeToolEventTeam)
win = desktop_app.MainWindow(app_config.load_settings(migrate=False))
win.send_task("帮我查点资料")
pump(8.0, until=lambda: win.composer.input.isEnabled())
text = area_text(win)
check("显示了工具调用", "调用工具" in text and "web_search" in text, text[-400:])
check("显示了工具返回", "工具返回" in text, text[-400:])
check("显示了工具回合的总结发言", "工程师的总结发言" in text, text[-400:])

print()
print("=" * 72)
print("G. 查看历史记录（只读）")
print("=" * 72)
win.close()
win, holder = new_window(per_turn=1)
win.send_task("会被存进历史的任务")
pump(8.0, until=lambda: win.composer.input.isEnabled())
win.start_new_conversation()
items = [win.sidebar.history.item(i) for i in range(win.sidebar.history.count())]
# 按内容精确匹配：同一秒内可能存了多条，按时间排序会并列，取第一条不稳定
target = next((it for it in items
               if "会被存进历史的任务" in (it.toolTip() or "")), None)
check("侧栏能列出历史条目", target is not None)
if target is not None:
    win.open_history_item(target.data(desktop_app.Qt.UserRole))
    check("历史以只读方式打开", win._reading_history)
    check("历史内容渲染出来", "会被存进历史的任务" in area_text(win), area_text(win)[:200])
    check("只读时输入框禁用", not win.composer.input.isEnabled())
    win.start_new_conversation()
    check("能回到新对话", not win._reading_history and win.composer.input.isEnabled())

print()
print("=" * 72)
print("H. 出错：界面复位并说明原因")
print("=" * 72)
win.close()


def boom(settings, clients, external):
    raise RuntimeError("角色「工程师」的模型配置不可用：401")


team_session.build_team = boom
win = desktop_app.MainWindow(app_config.load_settings(migrate=False))
win.send_task("会失败的任务")
check("出错后界面复位", pump(10.0, until=lambda: win.composer.input.isEnabled()),
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
