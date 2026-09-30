# -*- coding: utf-8 -*-
"""tools.py 沙箱与命令守卫的回归测试。

直接运行（不需要 pytest）：python tests/test_tools_sandbox.py
每一条都对应一个真实的绕过手法，改动 tools.py 后请重跑。
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 用临时目录当沙箱，避免污染真实 output/
_SANDBOX = tempfile.mkdtemp(prefix="aigc_sandbox_")
os.environ["AIGC_WORK_ROOT"] = _SANDBOX

import tools  # noqa: E402

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  [OK]   " if ok else "  [FAIL] ") + name + (("  -> " + detail) if detail and not ok else ""))


def rejected(text):
    """命令被拒绝时会返回带"已拒绝"的说明，而不是真实输出。"""
    return "已拒绝" in text


print("沙箱目录:", _SANDBOX)
print()

# ── 1. _safe_path：目录边界与越权 ────────────────────────────────
print("[1] 文件路径沙箱")
ok_cases = ["report.md", "sub/dir/plan.md", "./a.txt", _SANDBOX]
for p in ok_cases:
    try:
        tools._safe_path(p)
        check("放行合法路径 %r" % p, True)
    except ValueError as e:
        check("放行合法路径 %r" % p, False, str(e))

# 前缀匹配漏洞：output 与 output_backup 只差一个下划线，旧版 startswith 会放行
evil_prefix = os.path.join(os.path.dirname(_SANDBOX), os.path.basename(_SANDBOX) + "_backup", "x.txt")
for p in [evil_prefix, os.path.join("..", os.path.basename(_SANDBOX) + "_backup", "x.txt"),
          "..\\..\\Windows\\win.ini", "C:\\Windows\\win.ini",
          os.path.join(_SANDBOX, "..", "..", "secrets.txt")]:
    try:
        got = tools._safe_path(p)
        check("拦截越界路径 %r" % p, False, "被放行到 " + got)
    except ValueError:
        check("拦截越界路径 %r" % p, True)

try:
    tools._safe_path("")
    check("拦截空路径", False, "空路径被放行")
except ValueError:
    check("拦截空路径", True)

# 真实读写仍然可用
msg = tools.write_text_file("sub/hello.txt", "内容")
check("沙箱内写入正常", "已写入" in msg, msg)
check("沙箱内读取正常", tools.read_text_file("sub/hello.txt") == "内容")
check("列目录正常", "hello.txt" in tools.list_files("sub"))

print()

# ── 2. run_powershell：密钥泄露与危险命令 ────────────────────────
print("[2] 命令工具守卫")
must_reject = [
    ("Get-Content .env", "直接读 .env"),
    ("type .env", "type 是 Get-Content 的别名"),
    ("Get-Content D:\\app\\.env", "绝对路径读 .env"),
    ("Get-Content team_settings.json", "读自定义 API Key 文件"),
    ("[System.IO.File]::ReadAllText('.env')", ".NET 文件 API"),
    ("[IO.File]::ReadAllText('.env')", ".NET 文件 API 简写"),
    ("Get-Content $env:USERPROFILE\\.ssh\\id_rsa", "读 SSH 私钥"),
    ("Get-ChildItem ..\\", "跳出工作目录"),
    ("Remove-Item output\\a.txt", "删除文件"),
    ("Set-Content a.txt hi", "写入文件"),
    ("Start-Process calc", "启动程序"),
    ("Invoke-Expression 'Get-Content .env'", "动态执行"),
    ("taskkill /f /im notepad.exe", "杀进程"),
]
for cmd, why in must_reject:
    out = tools.run_powershell(cmd)
    check("拒绝 %-45s (%s)" % (cmd[:45], why), rejected(out), "实际返回: " + out[:120])

print()
must_allow = [
    "Get-Date -Format yyyy-MM-dd",
    "Get-Process | Select-Object -First 3 -ExpandProperty ProcessName",
    "ping 127.0.0.1 -n 1",
]
for cmd in must_allow:
    out = tools.run_powershell(cmd)
    check("放行 %-45s" % cmd[:45], not rejected(out), "被误拦: " + out[:120])

print()

# ── 3. 工作目录已锁在沙箱内 ──────────────────────────────────────
print("[3] 子进程工作目录")
out = tools.run_powershell("(Get-Location).Path")
check("命令在沙箱目录下执行", os.path.normcase(_SANDBOX) in os.path.normcase(out), out[:200])

print()
shutil.rmtree(_SANDBOX, ignore_errors=True)

print("=" * 60)
print("通过 %d 项，失败 %d 项" % (len(PASS), len(FAIL)))
if FAIL:
    print("失败项：")
    for f in FAIL:
        print("  -", f)
    sys.exit(1)
print("全部通过 ✅")
