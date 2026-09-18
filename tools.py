# -*- coding: utf-8 -*-
"""
AI 团队群聊 · 工具模块
======================
给 Agent 提供四类"手臂"：
  1. web_search    联网搜索（DuckDuckGo，无需 API Key）
  2. read_text_file / write_text_file / list_files  文件读写
  3. github_api     GitHub REST API（无 token 走公开接口）
  4. run_powershell 执行 PowerShell 命令（只读保护）
每个函数包装成 autogen FunctionTool 供 Agent 调用。
"""
import json
import os
import re
import subprocess
import urllib.parse
import urllib.request

# ── 1. 联网搜索（Bing，免 Key 可爬）────────────────────────────
def web_search(query: str, max_results: int = 6) -> str:
    """联网搜索。query 为搜索词；返回标题+真实链接+摘要列表，适合查实时信息。"""
    last_err = None
    for attempt in range(2):
        try:
            url = ("https://www.bing.com/search?q=" + urllib.parse.quote(query)
                   + "&setlang=zh-hans&cc=CN")
            req = urllib.request.Request(url, headers={"User-Agent": _UA})
            with urllib.request.urlopen(req, timeout=20) as r:
                html = r.read().decode("utf-8", errors="ignore")
            items = re.findall(r'<h2[^>]*><a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html, re.S)
            caps = re.findall(r'<p[^>]*class="[^"]*b_lineclamp[^"]*"[^>]*>(.*?)</p>', html, re.S)
            if not items:
                return "搜索无结果，可以换关键词再试。"
            results = []
            for i, (href, title) in enumerate(items[:max_results]):
                t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", title)).strip()
                snip = ""
                if i < len(caps):
                    snip = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", caps[i])).strip()
                results.append(f"{i+1}. {t}\n   链接: {href}\n   摘要: {snip}")
            return "\n\n".join(results)
        except Exception as e:
            last_err = e
    return f"搜索失败：{last_err}"

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")


# ── 2. 文件读写（限定在工作根目录内）────────────────────────────
# 工作目录为程序同目录下的 output 文件夹；可用环境变量 AIGC_WORK_ROOT 覆盖，
# 这样开发版与发布版可以共用同一份源码（发布版不需要任何路径改写）。
WORK_ROOT = os.path.normpath(
    os.environ.get("AIGC_WORK_ROOT")
    or os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
)

def _safe_path(path: str) -> str:
    """把相对路径限制在 WORK_ROOT 下，防止越权访问任意系统文件。"""
    if not os.path.isabs(path):
        path = os.path.join(WORK_ROOT, path)
    path = os.path.normpath(path)
    if not path.startswith(WORK_ROOT):
        raise ValueError(f"路径越界：{path}（限定在 {WORK_ROOT} 内）")
    return path


def read_text_file(path: str) -> str:
    """读取文本文件内容。path 相对工作目录，例如 'report.md'。"""
    full = _safe_path(path)
    if not os.path.exists(full):
        return f"文件不存在：{path}"
    with open(full, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


def write_text_file(path: str, content: str) -> str:
    """写入文本文件（自动创建目录）。path 相对工作目录，例如 'plan.md'。"""
    full = _safe_path(path)
    os.makedirs(os.path.dirname(full) or WORK_ROOT, exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(content)
    return f"已写入 {path}（{len(content)} 字符）"


def list_files(dir_path: str = ".") -> str:
    """列出工作目录下的文件。dir_path 相对工作目录。"""
    full = _safe_path(dir_path)
    if not os.path.isdir(full):
        return f"目录不存在：{dir_path}"
    names = sorted(os.listdir(full))
    if not names:
        return "（空目录）"
    return "\n".join(names)


# ── 3. GitHub REST API（无 token 走公开接口，限流较低）───────────
def github_api(method: str, endpoint: str, payload: dict = None) -> str:
    """调用 GitHub REST API。
    method: GET/POST/PATCH/DELETE
    endpoint: 以 / 开头的 API 路径，如 /search/repositories?q=autogen
    payload: 可选 JSON 请求体（写操作时）
    说明：无 token 时走公开接口（搜索/读取可用，写操作 401）；可读公开仓库、搜代码/项目。
    """
    token = os.environ.get("GITHUB_TOKEN", "") or _read_plugin_token()
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "dsh-agent-team",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = "https://api.github.com" + endpoint
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, method=method.upper(), data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            body = r.read().decode("utf-8", errors="ignore")
            if not body:
                return f"HTTP {r.status}（无内容）"
            obj = json.loads(body)
            return _summarize_github(obj)
    except urllib.error.HTTPError as e:
        try:
            msg = e.read().decode("utf-8", errors="ignore")[:400]
        except Exception:
            msg = ""
        return f"GitHub API 错误 HTTP {e.code}：{msg}"
    except Exception as e:
        return f"GitHub API 调用失败：{e}"


def _read_plugin_token() -> str:
    """GitHub Token 读取优先级（取第一个非空）：
    1) 环境变量 GITHUB_TOKEN
    2) 程序同目录 .env 里的 GITHUB_TOKEN=
    3) 环境变量 DSH_GITHUB_AUTH_FILE 指向的插件凭据 json（可选；用变量传路径以免硬编码）
    """
    t = os.environ.get("GITHUB_TOKEN", "")
    if t:
        return t
    try:
        env_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
        if os.path.exists(env_file):
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("GITHUB_TOKEN="):
                        v = line.split("=", 1)[1].strip().strip('"').strip("'")
                        if v:
                            return v
    except Exception:
        pass
    auth_file = os.environ.get("DSH_GITHUB_AUTH_FILE", "")
    if auth_file and os.path.exists(auth_file):
        try:
            with open(auth_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            t = data.get("token", "")
            return t if isinstance(t, str) else ""
        except Exception:
            return ""
    return ""


def _summarize_github(obj) -> str:
    """把 GitHub API 返回压成简洁文本，避免刷屏。"""
    if isinstance(obj, dict):
        # 仓库
        if obj.get("full_name") and ("stargazers_count" in obj or "description" in obj):
            return (f"仓库: {obj.get('full_name')}\n"
                    f"描述: {obj.get('description') or '（无）'}\n"
                    f"Star: {obj.get('stargazers_count', 0)} | Fork: {obj.get('forks_count', 0)}\n"
                    f"语言: {obj.get('language') or '未知'} | 更新: {obj.get('updated_at') or '?'}\n"
                    f"链接: {obj.get('html_url') or '?'}")
        if "total_count" in obj:  # 搜索结果
            items = obj.get("items", [])[:6]
            if not items:
                return f"搜索无结果（total={obj.get('total_count', 0)}）"
            lines = [f"共 {obj.get('total_count', 0)} 条，前 {len(items)} 条："]
            for it in items:
                lines.append(
                    f"  - {it.get('full_name')} [★{it.get('stargazers_count', 0)}] "
                    f"{str(it.get('description') or '')[:80]}"
                )
            return "\n".join(lines)
        # 一般字典：挑常见键
        keep = {k: v for k, v in obj.items()
                if k in ("name", "id", "title", "state", "message", "login", "html_url")}
        return json.dumps(keep, ensure_ascii=False)[:800]
    if isinstance(obj, list):
        return json.dumps(obj[:8], ensure_ascii=False)[:800]
    return str(obj)[:800]


# ── 4. 执行 PowerShell（危险命令只读保护）────────────────────────
DANGEROUS_PATTERNS = [
    r"\brm\s+-rf\b", r"\bRemove-Item\b", r"\bdel\s+/",
    # 注意：不可写成 \bformat\s —— 会误杀 `Get-Date -Format yyyy-MM-dd` 这类只读命令
    r"\bformat-(volume|disk)\b", r"\bformat\s+[a-z]:",
    # 同理，\bkill\b 会误杀含 kill 字样的路径/进程名，改为精确匹配
    r"\btaskkill\b", r"\bkill\s+-9\b",
    r"\bStop-Process\b", r"\breg\s+delete\b", r"\bshutdown\b", r"\brmdir\b",
    r"\bClear-Content\b", r"\bSet-Content\b", r"\bAdd-Content\b", r"\bOut-File\b",
    r"\bMove-Item\b", r"\bCopy-Item\b", r"\bNew-Item\b", r"\bRemove-Item\b",
]

# ── 只读白名单：只放行查询类指令 ────────────────────────────────
# 黑名单只能"已知的坏"，白名单才能挡住"未知的坏"（比如 Start-Process 拉起程序）。
# 策略：能识别出 cmdlet 就必须全部在白名单内；识别不出（表达式、纯文本、外部命令）
# 则退回黑名单兜底，避免误伤正常命令。可用环境变量 AIGC_CMD_WHITELIST=0 关闭白名单。
ALLOWED_CMDLETS = (
    "Get-*",              # 所有查询类 Get-*
    "Select-Object", "Where-Object", "Sort-Object", "Measure-Object",
    "Group-Object", "Compare-Object", "ForEach-Object",
    "Format-Table", "Format-List", "Format-Wide", "Format-Custom",
    "Out-String", "Out-Default", "Out-Null",
    "ConvertTo-Json", "ConvertFrom-Json", "ConvertTo-Csv", "ConvertTo-Html",
    "Write-Output", "Write-Host",
    "Test-Path", "Test-Connection", "Test-NetConnection",
    "Resolve-Path", "Join-Path", "Split-Path", "Select-String",
)

# 白名单之外的常见只读外部命令（不带 Verb-Noun 形式，单独列出）
EXTERNAL_READONLY = (
    "ping", "ipconfig", "netstat", "whoami", "systeminfo", "hostname",
    "type", "echo", "dir", "findstr", "where",
)


def _iter_command_tokens(command: str):
    """把命令按 | ; & 换行分段，取每段开头的指令名。"""
    for seg in re.split(r"[|;&\n]+", command):
        seg = seg.strip()
        while seg.startswith("("):        # 去掉 (Get-...).Property 这类左括号
            seg = seg[1:].lstrip()
        m = re.match(r"^\$[A-Za-z0-9_]+\s*=\s*", seg)   # 去掉 $x = ... 赋值前缀
        if m:
            seg = seg[m.end():].lstrip()
        if seg:
            yield re.split(r"\s", seg, 1)[0]


def _is_cmdlet_like(token: str) -> bool:
    """判断 token 是否是可判定的指令（Verb-Noun 形式，或已知外部命令）。"""
    if re.match(r"^[A-Za-z][A-Za-z0-9]*(-[A-Za-z0-9]+)+$", token):
        return True
    return token.lower() in EXTERNAL_READONLY


def _allowed_cmdlet(token: str) -> bool:
    low = token.lower()
    if low in EXTERNAL_READONLY:
        return True
    for pat in ALLOWED_CMDLETS:
        if pat.endswith("-*"):
            if low.startswith(pat[:-1].lower()):
                return True
        elif low == pat.lower():
            return True
    return False


def run_powershell(command: str) -> str:
    """执行 PowerShell 命令并返回输出。仅允许只读/查询类命令（删除、写入等危险操作被拒绝）。"""
    if not command or not command.strip():
        return "（命令为空）"
    lower = command.strip().lower()
    if lower in ("exit", "quit"):
        return "（该命令已拒绝）"
    for pat in DANGEROUS_PATTERNS:
        if re.search(pat, command, re.I):
            return f"已拒绝危险命令：{command}（工具为只读保护，不允许删除/写入/关机等操作）"
    # 白名单：识别不出任何指令时（表达式、纯文本等）跳过，由上面的黑名单兜底
    if os.environ.get("AIGC_CMD_WHITELIST", "1") != "0":
        judged = [t for t in _iter_command_tokens(command) if _is_cmdlet_like(t)]
        if judged:
            bad = sorted({t for t in judged if not _allowed_cmdlet(t)})
            if bad:
                return (f"已拒绝非只读命令：{command}\n"
                        f"未获许可的指令：{', '.join(bad)}\n"
                        f"该工具只允许查询类命令（Get-*、Select-Object、Where-Object、"
                        f"Format-*、ping、ipconfig 等）。")
    try:
        # 强制 PowerShell 以 UTF-8 输出：中文 Windows 默认 GBK，不指定 encoding
        # 会让 subprocess 的读线程抛 UnicodeDecodeError，stdout 静默变空（工具恒返回"无输出"）
        ps_cmd = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
                  "$OutputEncoding=[Text.Encoding]::UTF8;" + command)
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=60,
        )
        out = (result.stdout or "")[:4000]
        err = (result.stderr or "")[:1000]
        if result.returncode != 0 and not out.strip():
            out = f"（退出码 {result.returncode}）"
        if err.strip():
            out += f"\n[stderr] {err}"
        return out.strip() or "（无输出）"
    except subprocess.TimeoutExpired:
        return "命令超时（>60 秒）"
    except Exception as e:
        return f"执行失败：{e}"


# ── 打包为 autogen 工具 ─────────────────────────────────────────
def build_tools():
    """返回 {工具名: FunctionTool} 字典。"""
    from autogen_core.tools import FunctionTool
    tools = {}
    tools["web_search"] = FunctionTool(web_search, description="联网搜索互联网，适合查询实时信息、价格、攻略、新闻等。参数：query 搜索词, max_results 可选结果数。")
    tools["read_text_file"] = FunctionTool(read_text_file, description="读取工作目录下的文本文件内容（如报告、计划、清单）。参数：path 相对路径，如 'report.md'。")
    tools["write_text_file"] = FunctionTool(write_text_file, description="把内容写入工作目录下的文本文件（自动建目录）。参数：path 相对路径, content 完整内容。可用于保存方案、行程、清单。")
    tools["list_files"] = FunctionTool(list_files, description="列出工作目录下的文件。参数：dir_path 可选子目录。")
    tools["github_api"] = FunctionTool(github_api, description="调用 GitHub REST API：查仓库、搜代码/项目、看 Issues/PR。参数：method(GET等), endpoint(如 /search/repositories?q=xxx), payload(可选)。")
    tools["run_powershell"] = FunctionTool(run_powershell, description="执行只读命令查系统信息（看进程/文件/网络等）。只允许查询类指令：Get-*、Select-Object、Where-Object、Format-*、ping、ipconfig 等；写入/删除/启动程序类一律拒绝。")
    return tools