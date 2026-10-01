# -*- coding: utf-8 -*-
"""模型来源回归测试：三条通道都必须真的能建出客户端。

这两条都是打包验证时现场踩出来的，任何一条复发都等于"装出去连不上模型"：

  · NO_PROXY 里带 [::1]（代理工具很爱这么写，而且是**用户级环境变量**，
    双击 exe 一样继承）→ httpx 0.28 在构造客户端那行直接抛
    InvalidURL: Invalid port: ':1]'。本地 Ollama 和 OpenAI 兼容接口全废：
        本地 Ollama   autogen_ext 导入时就建客户端 → 导入即炸
        自定义 API    openai SDK 内部自建 httpx 客户端 → 构造即炸
        云端 GLM      glm_client 显式传了 transport，反而躲过一劫
  · 自定义 API 不给 model_info → deepseek-chat 这类名字不在 autogen 的已知
    模型表里，直接 ValueError，README 承诺的"任何 OpenAI 兼容接口"形同虚设。

这里不发任何网络请求，只验"客户端建得起来"。真的连通性由界面上的「测试全部」负责。

直接运行：python tests/test_llm_sources.py
"""
import os
import shutil
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="aigc_llm_")
os.environ["AIGC_CONFIG_DIR"] = os.path.join(_TMP, "config")
os.environ["AIGC_WORK_ROOT"] = os.path.join(_TMP, "docs")

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import app_config                                              # noqa: E402
import llm                                                     # noqa: E402

RESULTS = []

# 代理工具写出来的那种 NO_PROXY（方括号 IPv6）
BAD_NO_PROXY = "localhost,127.0.0.1,::1,[::1],10.*,172.16.*,192.168.*,.local,.cn,*.cn"
SAVED_PROXY = {k: os.environ.get(k) for k in ("NO_PROXY", "no_proxy")}

SOURCES = [
    ("本地 Ollama", {"source": "ollama", "model": "qwen2.5:7b"}),
    ("云端 GLM", {"source": "zhipu", "model": "glm-4.7-flash", "api_key": "占位-key"}),
    ("自定义 API", {"source": "custom", "model": "deepseek-chat",
                    "base_url": "https://api.deepseek.com/v1", "api_key": "占位-key"}),
    ("冷门兼容名", {"source": "custom", "model": "moonshot-v1-8k",
                    "base_url": "https://api.moonshot.cn/v1", "api_key": "占位-key"}),
]


def check(name, ok, detail=""):
    RESULTS.append((name, ok))
    print(("  [OK]   " if ok else "  [FAIL] ") + name + (("  -> " + detail) if detail and not ok else ""))


def build(role_cfg):
    """建一个客户端，返回 (成功?, 说明)；成功的话顺手关掉，别漏连接池。"""
    try:
        client, label = llm.make_client(role_cfg, settings=_settings)
    except Exception as exc:
        return False, "%s: %s" % (type(exc).__name__, exc)
    try:
        http_client = getattr(getattr(client, "_client", None), "_client", None)
        closer = getattr(http_client, "close", None)
        if closer:
            closer()
    except Exception:
        pass
    return True, label


_settings = app_config.default_settings()
_settings.setdefault("shared", {})["zai_api_key"] = "占位-key"

print("=" * 72)
print("A. 先证明坑是真的：坏 NO_PROXY、还没自救")
print("=" * 72)
for key in SAVED_PROXY:
    os.environ[key] = BAD_NO_PROXY

broken = {}
for label, role in SOURCES:
    ok, detail = build(role)
    broken[label] = ok
    print("  %-12s %s" % (label, "建起来了" if ok else detail))

check("本地 Ollama 在坏 NO_PROXY 下确实建不起来（autogen_ext 导入即炸）",
      not broken["本地 Ollama"])
check("自定义 API 在坏 NO_PROXY 下确实建不起来",
      not broken["自定义 API"])
check("云端 GLM 反而不受影响（glm_client 显式传了 transport）—— 别以后误当成三路全废",
      broken["云端 GLM"])

print()
print("=" * 72)
print("B. 自救：main() 启动时调的那一下")
print("=" * 72)
_changed = app_config.sanitize_proxy_env()
check("NO_PROXY 被就地修正", len(_changed) >= 1, str(_changed))

for label, role in SOURCES:
    ok, detail = build(role)
    check("自救后 %s 能建出客户端" % label, ok, detail)

print()
print("=" * 72)
print("C. 干净环境下四条通道都建得起来（基线）")
print("=" * 72)
# 注意：不能"还原成机器原样"当基线 —— 这台机器的原样就是坏的。
# 基线必须是真正干净的值。
CLEAN_NO_PROXY = "localhost,127.0.0.1,::1,10.*,172.16.*,192.168.*,.local,.cn,*.cn"
for key in SAVED_PROXY:
    os.environ[key] = CLEAN_NO_PROXY

for label, role in SOURCES:
    ok, detail = build(role)
    check("%s 建出客户端" % label, ok, detail)

# 收工，把机器的原始值还回去，别影响别人
for key, value in SAVED_PROXY.items():
    if value is None:
        os.environ.pop(key, None)
    else:
        os.environ[key] = value

shutil.rmtree(_TMP, ignore_errors=True)

failed = [n for n, ok in RESULTS if not ok]
print()
print("=" * 72)
print("通过 %d 项，失败 %d 项" % (len(RESULTS) - len(failed), len(failed)))
for n in failed:
    print("  - " + n)
sys.exit(1 if failed else 0)
