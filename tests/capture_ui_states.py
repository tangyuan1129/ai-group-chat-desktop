# -*- coding: utf-8 -*-
"""给界面拍几张"证据照"：空闲 / 讨论中 / 停止后。

用 QWidget.grab() 让 Qt 自己渲染，不依赖窗口是否在前台，
也不受 PrintWindow 抓不到子控件的限制。

顺带把"空闲"那一张存成 screenshots/main.png —— README 的「界面预览」用它。
那是真实运行界面的原始截图，没有任何拼接或美化；想更新重跑本脚本即可。

直接运行：python tests/capture_ui_states.py
"""
import asyncio
import os
import sys
import time

from PySide6.QtWidgets import QApplication

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import desktop_app  # noqa: E402

OUT_DIR = os.path.join(REPO, "_ui_shots")
os.makedirs(OUT_DIR, exist_ok=True)
README_SHOT = os.path.join(REPO, "screenshots", "main.png")

app = QApplication.instance() or QApplication(sys.argv)
desktop_app.HISTORY_DIR = os.path.join(OUT_DIR, "history")


class SlowTeam:
    async def run_stream(self, task=None):
        await asyncio.sleep(60)
        yield object()


def pump(seconds, until=None):
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.processEvents()
        if until is not None and until():
            return True
        time.sleep(0.02)
    return until() if until is not None else True


desktop_app.build_team = lambda settings, clients=None: SlowTeam()
win = desktop_app.MainWindow()
win.resize(1000, 700)
win.show()
pump(1.0)

shots = []


def shot(name):
    path = os.path.join(OUT_DIR, name)
    win.grab().save(path)
    shots.append(path)
    print("  已保存 %s" % path)


print("拍摄界面状态：")
shot("1_idle.png")
# README 用的主界面图就取这一张（默认配置下的真实初始界面）
os.makedirs(os.path.dirname(README_SHOT), exist_ok=True)
win.grab().save(README_SHOT)
print("  已保存 %s（README 界面预览用）" % README_SHOT)

win.task_input.setText("推荐大学生宿舍百元内提升幸福感的小东西")
win.start_chat()
pump(0.5)
shot("2_running.png")

win.stop_chat()
pump(5.0, until=lambda: not (win.worker and win.worker.isRunning()))
pump(0.4)
shot("3_stopped.png")

print()
print("停止后各控件状态：")
print("  输入框可用   =", win.task_input.isEnabled())
print("  发送按钮可用 =", win.send_btn.isEnabled())
print("  停止按钮可用 =", win.stop_btn.isEnabled())
print("  状态栏       =", win.status.text())
win.close()
