# -*- coding: utf-8 -*-
"""给界面拍"证据照"：首启引导 / 主界面 / 流式讨论中 / 停止后。

用 QWidget.grab() 让 Qt 自己渲染，不依赖窗口是否在前台，
也不受 PrintWindow 抓不到子控件的限制。

顺带把主界面那一张存成 screenshots/main.png —— README 的「界面预览」用它。
那是真实运行界面的原始截图，没有任何拼接或美化；想更新重跑本脚本即可。

直接运行：python tests/capture_ui_states.py
"""
import os
import sys
import tempfile
import time

_TMP = tempfile.mkdtemp(prefix="aigc_shot_")
os.environ["AIGC_CONFIG_DIR"] = os.path.join(_TMP, "config")
os.environ["AIGC_WORK_ROOT"] = os.path.join(_TMP, "docs")

from PySide6.QtWidgets import QApplication                        # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import app_config                                                 # noqa: E402
import desktop_app                                                # noqa: E402
import team_session                                               # noqa: E402
from fakes import FakeTeam                                        # noqa: E402

OUT_DIR = os.path.join(REPO, "_ui_shots")
os.makedirs(OUT_DIR, exist_ok=True)
README_SHOT = os.path.join(REPO, "screenshots", "main.png")

app = QApplication.instance() or QApplication(sys.argv)
desktop_app.QMessageBox.critical = staticmethod(lambda *a, **k: None)
desktop_app.QMessageBox.information = staticmethod(lambda *a, **k: None)


def pump(seconds, until=None):
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.processEvents()
        if until is not None and until():
            return True
        time.sleep(0.01)
    return until() if until is not None else True


def shot(widget, name, readme=False):
    path = README_SHOT if readme else os.path.join(OUT_DIR, name)
    widget.grab().save(path)
    print("  已保存 %s" % path)


# ── 1. 首启引导 ────────────────────────────────────────────────
print("拍摄界面状态：")
settings = app_config.load_settings(migrate=False).settings
wizard = desktop_app.OnboardingWizard(settings, None, reason="这是第一次启动。")
wizard.resize(660, 500)
wizard.show()
pump(0.6)
shot(wizard, "0_onboarding_step1.png")

wizard.source_box.setCurrentIndex(0)
wizard.zhipu_key.setText("示例Key-不会真的保存")
wizard._show_step(1)
pump(0.4)
shot(wizard, "0_onboarding_step2.png")
wizard.close()

# ── 2. 主界面（README 用图）────────────────────────────────────
# 用**默认的混合配置**（经理/工程师走云端 GLM，策划/评审走本地 Ollama），
# 只补一个占位 Key 让配置校验通过，这样界面显示"已就绪"。
# 展示的是产品默认的角色编排，没有编造任何对话内容。
# 注意：这份配置写在临时目录里，占位 Key 不会进仓库。
_ready = app_config.load_settings(migrate=False).settings
_ready.setdefault("shared", {})["zai_api_key"] = "占位-仅用于截图"
app_config.save_settings(_ready)

holder = {}


def fake_build(settings, clients, external):
    team = FakeTeam(external, per_turn=100000, delay=0.05)
    clients.append(type("C", (), {"close": lambda self: _noop()})())
    holder["team"] = team
    return team


async def _noop():
    return None


team_session.build_team = fake_build
win = desktop_app.MainWindow(app_config.load_settings(migrate=False), auto_onboard=False)
win.resize(1080, 720)
win.show()
pump(1.0)
shot(win, "1_idle.png", readme=True)

# ── 3. 讨论中（流式渲染）──────────────────────────────────────
win.task_input.setText("推荐大学生宿舍百元内提升幸福感的小东西")
win.send()
pump(2.0)
shot(win, "2_running.png")

# ── 4. 停止后 ─────────────────────────────────────────────────
win.stop()
pump(8.0, until=lambda: win.send_btn.isEnabled())
pump(0.4)
shot(win, "3_stopped.png")

print()
print("停止后各控件状态：")
print("  输入框可用   =", win.task_input.isEnabled())
print("  发送按钮可用 =", win.send_btn.isEnabled())
print("  停止按钮可用 =", win.stop_btn.isEnabled())
print("  状态栏       =", win.status.text())
print("  会话带上下文 =", win.session.has_context if win.session else None)
win.close()
