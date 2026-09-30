# -*- coding: utf-8 -*-
"""配置层回归测试：角色列表、读写往返、密钥加密、损坏恢复、v2 迁移。

这里的每一条都对应一个真实踩过的坑：
  · shared 段被合并逻辑丢掉 → 用户存的智谱 Key 下次启动就没了
  · encrypt_settings 只加密角色自己的 api_key，shared 里的 Key 明文落盘
  · 写配置不是原子的 → 崩在写一半，下次启动解析失败、配置静默消失
  · 角色从固定四角色改成有序列表后，老配置必须能平滑迁移

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


def role_by(settings, role_id):
    for role in settings.get("roles") or []:
        if role.get("id") == role_id:
            return role
    return None


print("=" * 72)
print("A. 首次加载")
print("=" * 72)
result = app_config.load_settings(migrate=False)
check("首次加载标记为 created", result.created)
check("默认配置含 shared 段", "shared" in result.settings)
check("roles 是列表（可增删）", isinstance(result.settings["roles"], list))
check("默认有 4 个角色", len(result.settings["roles"]) == 4,
      "实际 %d" % len(result.settings["roles"]))
check("每个角色都有 id/name/color/tools",
      all(all(k in r for k in ("id", "name", "color", "tools"))
          for r in result.settings["roles"]))
check("缺 Key 时报告问题", any("API Key" in p for p in result.problems), str(result.problems))
check("需要配置（needs_setup）", result.needs_setup)

print()
print("=" * 72)
print("B. 密钥加密：落盘必须是密文，读回必须是明文")
print("=" * 72)
settings = result.settings
settings["shared"]["zai_api_key"] = "abcdef0123456789abcdef0123456789.SECRETPART"
settings["shared"]["zai_base_url"] = "https://open.bigmodel.cn/api/paas/v4"
engineer = role_by(settings, "engineer")
engineer["source"] = "custom"
engineer["base_url"] = "https://api.deepseek.com/v1"
engineer["api_key"] = "sk-role-level-secret-123456"
engineer["model"] = "deepseek-chat"
app_config.save_settings(settings)

raw = open(app_config.settings_path(), encoding="utf-8").read()
check("共享智谱 Key 没明文落盘", "SECRETPART" not in raw)
check("角色 Key 没明文落盘", "sk-role-level-secret" not in raw)
check("落盘内容带 dpapi 前缀", "dpapi:" in raw)
check("没有残留临时文件",
      not any(n.startswith(".tmp-") for n in os.listdir(app_config.config_dir())),
      str(os.listdir(app_config.config_dir())))

reloaded = app_config.load_settings(migrate=False)
check("共享 Key 完整往返",
      reloaded.settings["shared"]["zai_api_key"] == "abcdef0123456789abcdef0123456789.SECRETPART")
check("共享 base_url 保留",
      reloaded.settings["shared"]["zai_base_url"] == "https://open.bigmodel.cn/api/paas/v4")
check("角色 Key 完整往返",
      role_by(reloaded.settings, "engineer")["api_key"] == "sk-role-level-secret-123456")
check("角色顺序保留",
      [r["id"] for r in reloaded.settings["roles"]] == ["manager", "planner", "engineer", "reviewer"],
      str([r["id"] for r in reloaded.settings["roles"]]))
check("配好 Key 后不再报缺 Key",
      not any("API Key" in p for p in reloaded.problems), str(reloaded.problems))

print()
print("=" * 72)
print("C. 二次保存不会把已加密的值再加密一层")
print("=" * 72)
app_config.save_settings(reloaded.settings)
again = app_config.load_settings(migrate=False)
check("幂等：共享 Key 仍能解密",
      again.settings["shared"]["zai_api_key"].endswith("SECRETPART"))
check("幂等：角色 Key 仍能解密",
      role_by(again.settings, "engineer")["api_key"] == "sk-role-level-secret-123456")

print()
print("=" * 72)
print("D. 角色列表：增删改与发言顺序")
print("=" * 72)
roles = again.settings["roles"]
roles.append(app_config.make_role("critic", len(roles)))
check("能新增角色", len(roles) == 5)
check("新增的角色带预设人设", "魔鬼代言人" in roles[-1]["system_prompt"])
check("新增角色拿到唯一 id",
      len({r["id"] for r in roles}) == len(roles),
      str([r["id"] for r in roles]))

roles.pop(0)
check("能删除角色", len(roles) == 4 and roles[0]["id"] != "manager")

roles[0], roles[1] = roles[1], roles[0]
first_id = roles[0]["id"]
app_config.save_settings(again.settings)
check("调整顺序后能落盘并读回",
      app_config.load_settings(migrate=False).settings["roles"][0]["id"] == first_id)

# 停用的角色不参与讨论，但全停用时退回全部（避免一个都不剩）
again.settings["roles"][0]["enabled"] = False
check("停用的角色被排除",
      all(r["id"] != first_id for r in app_config.enabled_roles(again.settings)))
for role in again.settings["roles"]:
    role["enabled"] = False
check("全停用时退回全部（不至于无人可发言）",
      len(app_config.enabled_roles(again.settings)) == len(again.settings["roles"]))
for role in again.settings["roles"]:
    role["enabled"] = True

print()
print("=" * 72)
print("E. v2 老配置迁移（固定四角色的字典 → 有序列表）")
print("=" * 72)
legacy = {
    "version": 2,
    "roles": {
        "manager": {"display": "老大", "color": "#123456", "source": "zhipu",
                    "model": "glm-4.5", "system_prompt": "你是老大", "api_key": ""},
        "engineer": {"display": "工程", "source": "custom", "model": "deepseek-chat",
                     "base_url": "https://api.deepseek.com/v1", "api_key": "sk-legacy-123456"},
    },
    "shared": {"zai_api_key": "legacy-shared-key-0123456789.abcd"},
}
with open(app_config.settings_path(), "w", encoding="utf-8") as f:
    json.dump(legacy, f, ensure_ascii=False)

migrated = app_config.load_settings(migrate=False).settings
check("迁移后是列表", isinstance(migrated["roles"], list))
check("迁移后保留 2 个角色", len(migrated["roles"]) == 2, str(len(migrated["roles"])))
check("中文显示名保留下来",
      role_by(migrated, "manager")["name"] == "老大",
      str(role_by(migrated, "manager")))
check("颜色保留", role_by(migrated, "manager")["color"] == "#123456")
check("自定义来源的角色 Key 能解出来",
      role_by(migrated, "engineer")["api_key"] == "sk-legacy-123456")
check("老配置里的 shared Key 也迁移过来了",
      migrated["shared"]["zai_api_key"] == "legacy-shared-key-0123456789.abcd")
check("迁移后补齐了 tools 字段",
      isinstance(role_by(migrated, "manager").get("tools"), list))
check("迁移后补齐了 enabled 字段",
      role_by(migrated, "manager").get("enabled") is True)

print()
print("=" * 72)
print("F. 损坏恢复：备份 + 明确报告，绝不静默重置")
print("=" * 72)
with open(app_config.settings_path(), "w", encoding="utf-8") as f:
    f.write('{"roles": [{"id": ')
broken = app_config.load_settings(migrate=False)
check("标记为已恢复", broken.recovered)
check("生成了备份文件", bool(broken.backup_path) and os.path.exists(broken.backup_path),
      broken.backup_path)
check("报告里说明了原因", any("无法解析" in p for p in broken.problems), str(broken.problems))
check("恢复后是完整默认配置",
      bool(broken.settings["roles"][0]["system_prompt"]))
check("恢复后仍含 shared 段", "shared" in broken.settings)

print()
print("=" * 72)
print("G. 校验：能指出具体是哪个角色、缺什么")
print("=" * 72)
bad = app_config.default_settings()
bad["shared"]["zai_api_key"] = "x" * 30
role_by(bad, "engineer")["source"] = "custom"
role_by(bad, "engineer")["model"] = "deepseek-chat"
problems = app_config.validate_settings(bad)
check("指出角色名", any("工程师" in p for p in problems), str(problems))
check("指出缺 Base URL", any("Base URL" in p for p in problems), str(problems))
check("指出缺 API Key", any("API Key" in p for p in problems), str(problems))
check("有智谱 Key 时不再抱怨缺 Key",
      not any("智谱 API Key" in p for p in problems), str(problems))

bad["roles"] = []
check("没有角色时报错", any("一个角色都没有" in p for p in app_config.validate_settings(bad)))

print()
print("=" * 72)
print("H. secret_store：加密、明文兼容、坏密文不炸")
print("=" * 72)
check("往返一致", secret_store.unprotect(secret_store.protect("中文-key-测试")) == "中文-key-测试")
check("明文原样返回", secret_store.unprotect("old-plaintext-key") == "old-plaintext-key")
check("空值返回空", secret_store.protect("") == "" and secret_store.unprotect("") == "")
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
