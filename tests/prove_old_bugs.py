# -*- coding: utf-8 -*-
"""证明这些漏洞在修复前是真实存在的：把修复前的 tools.py 取出来跑同样的用例。

固定到修复前最后一个提交，而不是 HEAD —— 否则修复提交之后对照组就失效了。
直接运行：python tests/prove_old_bugs.py
"""
import os
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRE_FIX_COMMIT = "faeb65986a1bf813454037e69011dec40b69c9d3"
OLD = os.path.join(tempfile.mkdtemp(prefix="aigc_old_"), "old_tools.py")

with open(OLD, "wb") as f:
    f.write(subprocess.check_output(
        ["git", "show", "%s:tools.py" % PRE_FIX_COMMIT], cwd=REPO))

SANDBOX = tempfile.mkdtemp(prefix="aigc_sandbox_")
os.environ["AIGC_WORK_ROOT"] = SANDBOX
sys.path.insert(0, os.path.dirname(OLD))
sys.modules.pop("old_tools", None)

import old_tools  # noqa: E402

print("旧版 tools.py（git HEAD）实测：")
print()

# 1. 前缀匹配绕过
evil = os.path.join(os.path.dirname(SANDBOX), os.path.basename(SANDBOX) + "_backup", "secret.txt")
try:
    got = old_tools._safe_path(evil)
    print("  [漏洞确认] _safe_path 放行了沙箱外的路径：")
    print("             %s" % got)
except ValueError as e:
    print("  [未复现] _safe_path 拦住了：%s" % e)

# 2. 命令工具读取 .env
env_path = os.path.join(REPO, ".env.example")
os.environ["AIGC_ENV_FILE"] = env_path
for cmd in ["type %s" % env_path, "Get-Content %s" % env_path]:
    out = old_tools.run_powershell(cmd)
    leaked = "ZAI_API_KEY" in out
    print("  [%s] %s" % ("漏洞确认" if leaked else "未复现", cmd))
    if leaked:
        print("             → 内容真的被读出来了：%s" % out.strip().splitlines()[0][:60])

# 3. .NET 文件 API
out = old_tools.run_powershell("[System.IO.File]::ReadAllText('%s')" % env_path)
print("  [%s] [System.IO.File]::ReadAllText(...)" % ("漏洞确认" if "ZAI_API_KEY" in out else "未复现"))

# 4. 跳出工作目录
out = old_tools.run_powershell("Get-ChildItem ..")
print("  [%s] Get-ChildItem ..（读取工作目录之外）" % ("漏洞确认" if "已拒绝" not in out else "未复现"))
