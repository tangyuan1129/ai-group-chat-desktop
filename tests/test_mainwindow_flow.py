# -*- coding: utf-8 -*-
"""端到端 GUI 实测：真起一个主窗口，走完整的「发送任务 → 停止」流程。

验的是用户真正会遇到的后果：停止之后输入框和发送按钮还能不能用。
旧版会永久卡死，只能重启程序。

直接运行：python tests/test_mainwindow_flow.py
"""
import asyncio
import os
import shutil
import sys
import tempfile
import time

from PySide6.QtWidgets import QApplication, QMessageBox

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import desktop_app  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)
app.setFont(app.font())

# 历史记录写到临时目录，别污染仓库
_TMP_HISTORY = tempfile.mkdtemp(prefix="aigc_history_")
desktop_app.HISTORY_DIR = _TMP_HISTORY
# 出错弹窗会阻塞测试，换成记录
_POPUPS = []
desktop_app.QMessageBox.critical = staticmethod(
    lambda *a, **k: _POPUPS.append(a[2] if len(a) > 2 else ""))

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, ok))
    print(("  [OK]   " if ok else "  [FAIL] ") + name + (("  -> " + detail) if detail and not ok else ""))


def pump(seconds, until=None):
    """跑 Qt 事件循环 seconds 秒；until() 为真则提前结束。返回是否满足 until。"""
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.processEvents()
        if until is not None and until():
            return True
        time.sleep(0.02)
    return until() if until is not None else True


class SlowTeam:
    """模型请求一直不返回，用来模拟"点了停止但请求还在飞"。"""

    async def run_stream(self, task=None):
        await asyncio.sleep(60)
        yield object()


class TalkyTeam:
    """正常产出：一条发言 + 一个 TaskResult。"""

    async def run_stream(self, task=None):
        yield TextMessage()
        yield TaskResult()


# 注意：ChatWorker._handle_event 是按 event.__class__.__name__ 分发的，
# 所以假事件类的类名必须和 AutoGen 的真实事件类一致。
class TextMessage:
    source = "manager"
    content = "这是经理的发言"


class TaskResult:
    stop_reason = "Maximum number of messages reached!"


def new_window():
    win = desktop_app.MainWindow()
    win.task_input.setText("测试任务")
    return win


print("=" * 66)
print("场景 A：发送任务 → 中途点停止 → 界面必须能继续用")
print("=" * 66)
desktop_app.build_team = lambda settings, clients=None: SlowTeam()
win = new_window()
win.start_chat()
pump(0.3)
check("发送后：输入框禁用", not win.task_input.isEnabled())
check("发送后：停止按钮可用", win.stop_btn.isEnabled())

pump(0.8)                       # 让工作线程进入"模型请求中"
win.stop_chat()
finished = pump(6.0, until=lambda: not (win.worker and win.worker.isRunning()))
check("停止后：工作线程已退出", finished)

pump(0.3)
check("停止后：输入框恢复可用", win.task_input.isEnabled(), "输入框仍被禁用")
check("停止后：发送按钮恢复可用", win.send_btn.isEnabled(), "发送按钮仍被禁用")
check("停止后：停止按钮置灰", not win.stop_btn.isEnabled())
check("停止后：状态栏显示已停止", "已停止" in win.status.text(), win.status.text())
check("停止后：对话区提示已停止", "已停止本次讨论" in win.chat_view.toPlainText())
check("停止后：历史已落盘", len(os.listdir(_TMP_HISTORY)) == 1,
      "历史目录里有 %d 个文件" % len(os.listdir(_TMP_HISTORY)))

# 停完之后必须还能再发一条 —— 旧版就是死在这里
win.task_input.setText("第二个任务")
win.start_chat()
pump(0.3)
check("停止后可再次发送任务", not win.task_input.isEnabled() and win.worker.isRunning())
win.stop_chat()
pump(6.0, until=lambda: not (win.worker and win.worker.isRunning()))
win.close()

print()
print("=" * 66)
print("场景 B：正常讨论结束 → 界面复位")
print("=" * 66)
desktop_app.build_team = lambda settings, clients=None: TalkyTeam()
win = new_window()
win.start_chat()
pump(6.0, until=lambda: win.send_btn.isEnabled())
check("正常结束后：输入框恢复可用", win.task_input.isEnabled())
check("正常结束后：发送按钮恢复可用", win.send_btn.isEnabled())
check("正常结束后：状态栏回到空闲", "空闲" in win.status.text(), win.status.text())
check("正常结束后：显示了角色发言", "这是经理的发言" in win.chat_view.toPlainText())
check("终止原因已翻成中文", "已达最大发言轮数" in win.chat_view.toPlainText(),
      win.chat_view.toPlainText()[-120:])
win.close()

print()
print("=" * 66)
print("场景 C：某个角色配置坏了 → 界面复位 + 指出是哪个角色")
print("=" * 66)


def boom(settings, clients=None):
    raise RuntimeError("角色「工程师」的模型配置不可用：\nAuthenticationError: 401")


desktop_app.build_team = boom
win = new_window()
win.start_chat()
pump(6.0, until=lambda: win.send_btn.isEnabled())
check("出错后：发送按钮恢复可用", win.send_btn.isEnabled())
check("出错后：状态栏提示重试", "出错" in win.status.text(), win.status.text())
check("出错后：弹窗指出了具体角色", any("工程师" in p for p in _POPUPS), str(_POPUPS)[:120])
check("出错后：对话区保留错误详情", "401" in win.chat_view.toPlainText())
win.close()

shutil.rmtree(_TMP_HISTORY, ignore_errors=True)

failed = [n for n, ok in RESULTS if not ok]
print()
print("=" * 66)
print("通过 %d 项，失败 %d 项" % (len(RESULTS) - len(failed), len(failed)))
for n in failed:
    print("  - " + n)
sys.exit(1 if failed else 0)
