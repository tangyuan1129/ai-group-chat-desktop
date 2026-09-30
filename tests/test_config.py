# -*- coding: utf-8 -*-
"""配置层回归测试：读写往返、密钥加密、损坏恢复、校验。

这里的每一条都对应一个真实踩过的坑：
  · shared 段被 _merge_defaults 丢掉 → 用户存的智谱 Key 下次启动就没了
  · encrypt_settings 只加密 roles[*].api_key，shared 里的 Key 明文落盘
  · 写配置不是原子的 → 崩在写一半，下次启动 json 解析失败、配置静默消失

直接运行：python tests/test_config.py
"""
import json
import os
import shutil
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="aigc_cfg_")
os.environ["AIGC_CONFIG_DIR"] = os.path.join(_TMP, "config")
os.environ["AIGC_WORK_ROOT"] = os.path.join(_TMP, "docs")

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import app_config                                            # noqa: E402
import secret_store                                          # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, ok))
    print(("  [OK]   " if ok else "  [FAIL] ") + name + (("  -> " + detail) if detail and not ok else ""))


print("=" * 72)
print("A. 首次加载")
print("=" * 72)
result = app_config.load_settings(migrate=False)
check("首次加载标记为 created", result.created)
check("默认配置含 shared 段", "shared" in result.settings)
check("默认配置有四个角色", len(result.settings["roles"]) == 4)
check("缺 Key 时报告问题", any("API Key" in p for p in result.problems), str(result.problems))
check("需要引导", result.needs_onboarding)

print()
print("=" * 72)
print("B. 密钥加密：落盘必须是密文，读回必须是明文")
print("=" * 72)
settings = result.settings
settings["shared"]["zai_api_key"] = "abcdef0123456789abcdef0123456789.SECRETPART"
settings["shared"]["zai_base_url"] = "https://open.bigmodel.cn/api/paas/v4"
settings["roles"]["engineer"]["source"] = "custom"
settings["roles"]["engineer"]["base_url"] = "https://api.deepseek.com/v1"
settings["roles"]["engineer"]["api_key"] = "sk-role-level-secret-123456"
settings["roles"]["engineer"]["model"] = "deepseek-chat"
app_config.save_settings(settings)

raw = open(app_config.settings_path(), encoding="utf-8").read()
check("共享智谱 Key 没明文落盘", "SECRETPART" not in raw, "明文出现在文件里")
check("角色 Key 没明文落盘", "sk-role-level-secret" not in raw, "明文出现在文件里")
check("落盘内容带 dpapi 前缀", "dpapi:" in raw)
check("没有残留临时文件",
      not any(n.startswith(".tmp-") for n in os.listdir(app_config.config_dir())),
      str(os.listdir(app_config.config_dir())))

reloaded = app_config.load_settings(migrate=False)
check("共享 Key 能正确解密", reloaded.settings["shared"]["zai_api_key"].endswith("SECRETPART"),
      repr(reloaded.settings["shared"]["zai_api_key"]))
check("共享 Key 完整往返",
      reloaded.settings["shared"]["zai_api_key"] == "abcdef0123456789abcdef0123456789.SECRETPART")
check("共享 base_url 保留",
      reloaded.settings["shared"]["zai_base_url"] == "https://open.bigmodel.cn/api/paas/v4")
check("角色 Key 完整往返",
      reloaded.settings["roles"]["engineer"]["api_key"] == "sk-role-level-secret-123456")
check("配好 Key 后不再报缺 Key",
      not any("API Key" in p for p in reloaded.problems), str(reloaded.problems))

print()
print("=" * 72)
print("C. 二次保存不会把已加密的值再加密一层")
print("=" * 72)
app_config.save_settings(reloaded.settings)
again = app_config.load_settings(migrate=False)
check("幂等：两次保存后仍能解密",
      again.settings["shared"]["zai_api_key"].endswith("SECRETPART"),
      repr(again.settings["shared"]["zai_api_key"])[:80])
check("幂等：角色 Key 仍能解密",
      again.settings["roles"]["engineer"]["api_key"] == "sk-role-level-secret-123456")

print()
print("=" * 72)
print("D. 损坏恢复：备份 + 明确报告，绝不静默重置")
print("=" * 72)
with open(app_config.settings_path(), "w", encoding="utf-8") as f:
    f.write('{"roles": {"manager": ')          # 故意写坏
broken = app_config.load_settings(migrate=False)
check("标记为已恢复", broken.recovered)
check("生成了备份文件", bool(broken.backup_path) and os.path.exists(broken.backup_path),
      broken.backup_path)
check("报告里说明了原因", any("无法解析" in p for p in broken.problems), str(broken.problems))
check("恢复后是完整默认配置",
      bool(broken.settings["roles"]["manager"]["system_prompt"]))
check("恢复后仍含 shared 段", "shared" in broken.settings)

print()
print("=" * 72)
print("E. 校验：能指出具体是哪个角色、缺什么")
print("=" * 72)
bad = app_config.default_settings()
bad["roles"]["engineer"]["source"] = "custom"
bad["roles"]["engineer"]["model"] = "deepseek-chat"
problems = app_config.validate_settings(bad)
check("指出角色名", any("工程师" in p for p in problems), str(problems))
check("指出缺 Base URL", any("Base URL" in p for p in problems), str(problems))
check("指出缺 API Key", any("API Key" in p for p in problems), str(problems))

bad2 = app_config.default_settings()
bad2["shared"]["zai_api_key"] = "x" * 30
check("有智谱 Key 时不再抱怨缺 Key",
      not any("智谱 API Key" in p for p in app_config.validate_settings(bad2)),
      str(app_config.validate_settings(bad2)))

print()
print("=" * 72)
print("F. secret_store 直接测：加密、明文兼容、坏密文不炸")
print("=" * 72)
check("往返一致", secret_store.unprotect(secret_store.protect("中文-key-测试")) == "中文-key-测试")
check("明文原样返回", secret_store.unprotect("old-plaintext-key") == "old-plaintext-key")
check("空值返回空", secret_store.protect("") == "" and secret_store.unprotect("") == "")
# DPAPI 每次加密都带随机盐，密文天然不同，所以不能拿两次 protect() 比；
# 要验的是"已经加密过的不再套一层"（否则二次保存会把配置写坏）。
_blob = secret_store.protect("abc123456")
check("幂等：已加密的不再加密一层", secret_store.encrypt_value(_blob) == _blob)
check("幂等：解回来还是原文",
      secret_store.unprotect(secret_store.encrypt_value(_blob)) == "abc123456")
check("坏密文不抛异常", secret_store.unprotect("dpapi:bm90LWEtcmVhbC1ibG9i") == "")

shutil.rmtree(_TMP, ignore_errors=True)

failed = [n for n, ok in RESULTS if not ok]
print()
print("=" * 72)
print("通过 %d 项，失败 %d 项" % (len(RESULTS) - len(failed), len(failed)))
for n in failed:
    print("  - " + n)
sys.exit(1 if failed else 0)
