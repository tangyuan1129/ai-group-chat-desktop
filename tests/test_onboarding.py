# -*- coding: utf-8 -*-
"""首启引导向导的回归测试。

写这个是因为踩过：`_show_step` 引用了却忘了实现，首次启动直接 AttributeError 崩溃。
而 UI 测试用 auto_onboard=False 跳过了引导，所以没发现 —— 没人走的路一定会烂。

直接运行：python tests/test_onboarding.py
"""
import os
import shutil
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="aigc_ob_")
os.environ["AIGC_CONFIG_DIR"] = os.path.join(_TMP, "config")
os.environ["AIGC_WORK_ROOT"] = os.path.join(_TMP, "docs")

from PySide6.QtWidgets import QApplication, QDialog, QMessageBox     # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import app_config                                                    # noqa: E402
from onboarding import OnboardingWizard                              # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

WARNINGS = []
QMessageBox.warning = staticmethod(lambda *a, **k: WARNINGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.information = staticmethod(lambda *a, **k: None)

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, ok))
    print(("  [OK]   " if ok else "  [FAIL] ") + name + (("  -> " + detail) if detail and not ok else ""))


def new_wizard():
    settings = app_config.load_settings(migrate=False).settings
    return OnboardingWizard(settings, None, reason="测试"), settings


print("=" * 72)
print("A. 构造与分步导航（这里曾经直接崩过）")
print("=" * 72)
wizard, settings = new_wizard()
check("向导能构造出来", wizard is not None)
check("停在第 1 步", wizard.stack.currentIndex() == 0)
check("第 1 步禁用上一步", not wizard.back_btn.isEnabled())
check("第 1 步按钮是下一步", wizard.next_btn.text() == "下一步")

wizard._go_next()
check("能进到第 2 步", wizard.stack.currentIndex() == 1, "index=%d" % wizard.stack.currentIndex())
check("第 2 步启用上一步", wizard.back_btn.isEnabled())

wizard._go_back()
check("能退回第 1 步", wizard.stack.currentIndex() == 0)

print()
print("=" * 72)
print("B. 校验：缺什么就说什么，不能默默放过")
print("=" * 72)
wizard, settings = new_wizard()
wizard.source_box.setCurrentIndex(wizard.source_box.findData("zhipu"))
wizard._show_step(1)
wizard.zhipu_key.setText("")
WARNINGS.clear()
wizard._go_next()
check("智谱缺 Key 时被拦下", wizard.stack.currentIndex() == 1)
check("提示了要填 Key", any("API Key" in w for w in WARNINGS), str(WARNINGS))

wizard.zhipu_key.setText("abcdef0123456789abcdef0123456789.AbCdEf123456")
wizard.zhipu_model.setCurrentText("glm-4.7-flash")
wizard._go_next()
check("填好后能进第 3 步", wizard.stack.currentIndex() == 2,
      "index=%d warnings=%s" % (wizard.stack.currentIndex(), WARNINGS))
check("第 3 步按钮是完成", wizard.next_btn.text() == "完成")

wizard, settings = new_wizard()
wizard.source_box.setCurrentIndex(wizard.source_box.findData("custom"))
wizard._show_step(1)
WARNINGS.clear()
wizard._go_next()
check("自定义 API 缺 Base URL 时被拦下", wizard.stack.currentIndex() == 1)
check("提示了要填 Base URL", any("Base URL" in w for w in WARNINGS), str(WARNINGS))

print()
print("=" * 72)
print("C. 保存：写进配置、密钥加密落盘、返回 Accepted")
print("=" * 72)
wizard, settings = new_wizard()
wizard.source_box.setCurrentIndex(wizard.source_box.findData("zhipu"))
wizard._show_step(1)
KEY = "abcdef0123456789abcdef0123456789.AbCdEf123456"
wizard.zhipu_key.setText(KEY)
wizard.zhipu_model.setCurrentText("glm-4.7-flash")
wizard._show_step(2)
wizard._save_and_close()
check("向导返回 Accepted", wizard.result() == QDialog.Accepted, "result=%s" % wizard.result())

raw = open(app_config.settings_path(), encoding="utf-8").read()
check("Key 没明文落盘", "AbCdEf123456" not in raw)

saved = app_config.load_settings(migrate=False).settings
check("共享 Key 存下来了", saved["shared"]["zai_api_key"] == KEY,
      repr(saved["shared"]["zai_api_key"])[:60])
check("四个角色都套用了选的来源",
      all(saved["roles"][n]["source"] == "zhipu" for n in app_config.ROLE_ORDER),
      str([saved["roles"][n]["source"] for n in app_config.ROLE_ORDER]))
check("模型名套用到了角色上",
      all(saved["roles"][n]["model"] == "glm-4.7-flash" for n in app_config.ROLE_ORDER))
check("配好后校验通过", app_config.validate_settings(saved) == [],
      str(app_config.validate_settings(saved)))

print()
print("=" * 72)
print("D. 稍后再说：能退出且不写坏配置")
print("=" * 72)
before = open(app_config.settings_path(), encoding="utf-8").read()
wizard, _ = new_wizard()
wizard.skip_btn.click()
check("跳过时返回 Rejected", wizard.result() != QDialog.Accepted)
after = open(app_config.settings_path(), encoding="utf-8").read()
check("跳过没有改动配置", before == after)

shutil.rmtree(_TMP, ignore_errors=True)

failed = [n for n, ok in RESULTS if not ok]
print()
print("=" * 72)
print("通过 %d 项，失败 %d 项" % (len(RESULTS) - len(failed), len(failed)))
for n in failed:
    print("  - " + n)
sys.exit(1 if failed else 0)
