# -*- coding: utf-8 -*-
"""配置与路径：角色列表、读写、校验、损坏恢复、老版本迁移。

角色模型（v3）
--------------
旧版把四个角色写死在代码里（manager / planner / engineer / reviewer），
用户只能改改参数，不能增删。现在 roles 是一个**有序列表**：想加几个 AI 就加几个，
每个角色独立配置名称、颜色、模型来源、模型、凭据、人设、以及能用的工具。
发言顺序就是列表顺序。

这样才谈得上"像 agent 一样可自定义"，而不是一个只能调参的固定班子。

配置健壮性
----------
1. 写配置用"临时文件 + 原子替换"。旧版直接覆写，崩在写一半就得到半截 JSON，
   下次启动解析失败后静默回默认值，用户配置无声消失。
2. 损坏时备份 + 明确告知，绝不静默吞掉。
3. 用户数据放 %APPDATA%，AI 产出放"文档"目录 —— 装到 D:\\ 根目录需要管理员
   权限，普通用户写不进去。
"""
import datetime
import json
import os
import re
import shutil
import tempfile

from secret_store import decrypt_settings, encrypt_settings

APP_NAME = "AI团队群聊"
# 产品版本。改这里之后，install.iss 里的 MyAppVersion 必须跟着改 ——
# tests/test_config.py 的 I 节会拿这两处对账，对不上直接报错。
# 之前没有这个常量：装出去的 v1.1 包内嵌版本其实还是 1.0.0，用户报问题
# 说不清自己用的是哪版，诊断包里也看不到。
APP_VERSION = "1.2.2"
CONFIG_VERSION = 3

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))

# NO_PROXY 里可能出现的方括号 IPv6 写法，例如 [::1]
_NO_PROXY_BRACKETS = re.compile(r"\[([0-9A-Fa-f:.]+)\]")


def sanitize_proxy_env() -> list:
    """把 NO_PROXY 里的 [::1] 这种方括号写法的方括号去掉。

    为什么非修不可：httpx 0.28 解析 no_proxy 列表时，遇到 [::1] 会在
    **构造 httpx.Client() 的那一行**直接抛
        InvalidURL: Invalid port: ':1]'
    而不是等到发请求。实测影响面（见 tests/test_llm_sources.py）：
        本地 Ollama   autogen_ext 导入时就建客户端 → 导入即炸
        自定义 API    openai SDK 内部自建 httpx 客户端 → 构造即炸
        云端 GLM      glm_client 显式传了 transport，反而躲过一劫
    也就是说"任何 OpenAI 兼容接口"和本地模型都连不上，界面只会报错。

    而这种写法特别常见：代理工具（Clash 之类）会写成
        NO_PROXY=localhost,127.0.0.1,::1,[::1],10.*,...
    并且是**用户级环境变量**，双击装好的 exe 一样继承。

    去掉方括号不改变语义（还是同一个 IPv6 回环地址），httpx 也能解析了。
    返回改动了哪些键，方便在日志里留一笔。
    """
    changed = []
    for key in ("NO_PROXY", "no_proxy"):
        raw = os.environ.get(key)
        if not raw or "[" not in raw:
            continue
        fixed = _NO_PROXY_BRACKETS.sub(r"\1", raw)
        if fixed != raw:
            os.environ[key] = fixed
            changed.append("%s: %s -> %s" % (key, raw, fixed))
    return changed


# ── 路径 ───────────────────────────────────────────────────────
def _env_dir(name: str) -> str:
    return os.environ.get(name) or os.path.expanduser("~")


def config_dir() -> str:
    base = os.environ.get("AIGC_CONFIG_DIR")
    if base:
        return base
    appdata = os.environ.get("APPDATA")
    if appdata:
        return os.path.join(appdata, APP_NAME)
    return os.path.join(_env_dir("USERPROFILE"), "." + APP_NAME)


def documents_dir() -> str:
    """AI 产出的文件：文档目录下的同名文件夹，用户能直接找到。"""
    override = os.environ.get("AIGC_WORK_ROOT")
    if override:
        return override
    docs = os.path.join(_env_dir("USERPROFILE"), "Documents")
    if not os.path.isdir(docs):
        docs = _env_dir("USERPROFILE")
    return os.path.join(docs, APP_NAME)


def settings_path() -> str:
    return os.path.join(config_dir(), "team_settings.json")


def history_dir() -> str:
    return os.path.join(config_dir(), "history")


def logs_dir() -> str:
    return os.path.join(config_dir(), "logs")


def legacy_settings_path() -> str:
    return os.path.join(_THIS_DIR, "team_settings.json")


def legacy_history_dir() -> str:
    return os.path.join(_THIS_DIR, "history")


def legacy_output_dir() -> str:
    return os.path.join(_THIS_DIR, "output")


def env_file() -> str:
    return os.environ.get("AIGC_ENV_FILE") or os.path.join(_THIS_DIR, ".env")


def ensure_dirs() -> None:
    for folder in (config_dir(), history_dir(), logs_dir(), documents_dir()):
        try:
            os.makedirs(folder, exist_ok=True)
        except Exception:
            pass


# ── 工具目录 ───────────────────────────────────────────────────
# 每个角色能挂哪些"手臂"。界面上做成可勾选项。
TOOL_CATALOG = [
    ("web_search", "联网搜索", "搜索互联网，查实时信息、价格、攻略、新闻"),
    ("read_text_file", "读取文件", "读取工作目录下的文本文件"),
    ("write_text_file", "写入文件", "把内容写成文件保存到工作目录"),
    ("list_files", "列出文件", "列出工作目录下的文件"),
    ("github_api", "GitHub API", "查仓库、搜代码、看 Issues / PR"),
    ("run_powershell", "只读命令", "执行查询类系统命令（进程、网络、硬件）"),
]
TOOL_NAMES = tuple(name for name, _label, _desc in TOOL_CATALOG)
TOOL_LABELS = {name: label for name, label, _desc in TOOL_CATALOG}

SOURCE_LABELS = {"zhipu": "云端智谱 GLM", "ollama": "本地 Ollama", "custom": "自定义 API"}
SOURCE_SHORT = {"zhipu": "云端GLM", "ollama": "本地Ollama", "custom": "自定义API"}

DEFAULT_MAX_ROUNDS = 18

_COMMON_RULES = "所有发言必须用中文，简洁有观点，每次发言不超过150字，直接说内容，不要寒暄。"

# ── 角色预设 ───────────────────────────────────────────────────
# "添加角色"时可以直接选一个预设，也可以从空白开始。仿照 DSH 的 agent 预设思路：
# 给个合理的起点，但不限制你改。
ROLE_PRESETS = [
    {
        "key": "manager", "name": "经理", "color": "#5B8CFF",
        "prompt": "你是项目经理，主持讨论：先拆解问题；出现分歧时裁决；最后把方案整理成明确分工。" + _COMMON_RULES,
        "tools": ["web_search", "list_files", "read_text_file"],
    },
    {
        "key": "planner", "name": "策划", "color": "#FF9F45",
        "prompt": "你是创意策划：负责提点子和方案设计，敢于反驳别人，但认可已被说服的观点。" + _COMMON_RULES,
        "tools": ["web_search", "list_files", "read_text_file"],
    },
    {
        "key": "engineer", "name": "工程师", "color": "#3DD68C",
        "prompt": "你是技术专家：负责评估可行性、指出风险、给落地建议。" + _COMMON_RULES,
        "tools": ["web_search", "read_text_file", "write_text_file", "list_files",
                  "github_api", "run_powershell"],
    },
    {
        "key": "reviewer", "name": "评审", "color": "#C084FC",
        "prompt": "你是评审官：负责挑漏洞把关。当方案合理时，简短总结并在最后一行单独输出：APPROVE。" + _COMMON_RULES,
        "tools": ["web_search", "list_files", "read_text_file", "write_text_file"],
    },
    {
        "key": "researcher", "name": "研究员", "color": "#38BDF8",
        "prompt": "你是资料研究员：负责查证事实、找数据、给出信息来源，不确定就明说不确定。" + _COMMON_RULES,
        "tools": ["web_search", "read_text_file", "list_files", "github_api"],
    },
    {
        "key": "critic", "name": "唱反调", "color": "#F87171",
        "prompt": "你是魔鬼代言人：专门找方案里最可能翻车的地方，指出被忽略的风险和代价，不要附和。" + _COMMON_RULES,
        "tools": ["web_search", "read_text_file", "list_files"],
    },
    {
        "key": "writer", "name": "执笔", "color": "#FBBF24",
        "prompt": "你是文档执笔：把讨论结论整理成条理清晰的成稿，并写入文件保存。" + _COMMON_RULES,
        "tools": ["read_text_file", "write_text_file", "list_files"],
    },
]
PRESETS_BY_KEY = {p["key"]: p for p in ROLE_PRESETS}

# 默认班子：混合模型（云端 + 本地），这样"异构"这个卖点开箱就能看到
DEFAULT_ROLE_KEYS = ["manager", "planner", "engineer", "reviewer"]
DEFAULT_SOURCES = {"manager": "zhipu", "planner": "ollama", "engineer": "zhipu",
                   "reviewer": "ollama"}
DEFAULT_MODELS = {"zhipu": "glm-4.7-flash", "ollama": "qwen2.5:7b", "custom": ""}


def _slug(text: str, fallback: str) -> str:
    """把中文名转成可用的英文 id（AutoGen 的 agent 名要求是简单标识符）。"""
    ascii_only = re.sub(r"[^a-zA-Z0-9_]", "", text or "")
    return ascii_only.lower() or fallback


def make_role(key: str = "manager", index: int = 0) -> dict:
    """按预设造一个角色。key 不存在时给一个空白角色。"""
    preset = PRESETS_BY_KEY.get(key)
    if preset is None:
        return {
            "id": "role%d" % (index + 1), "name": "角色%d" % (index + 1),
            "color": "#5B8CFF", "enabled": True,
            "source": "zhipu", "model": DEFAULT_MODELS["zhipu"],
            "base_url": "", "api_key": "",
            "system_prompt": "你是一个参与者，就讨论的问题给出你的观点。" + _COMMON_RULES,
            "tools": ["web_search", "read_text_file", "list_files"],
        }
    source = DEFAULT_SOURCES.get(key, "zhipu")
    return {
        "id": _slug(key, "role%d" % (index + 1)),
        "name": preset["name"],
        "color": preset["color"],
        "enabled": True,
        "source": source,
        "model": DEFAULT_MODELS.get(source, ""),
        "base_url": "",
        "api_key": "",
        "system_prompt": preset["prompt"],
        "tools": list(preset["tools"]),
    }


def default_settings() -> dict:
    return {
        "version": CONFIG_VERSION,
        "max_messages": DEFAULT_MAX_ROUNDS,
        # 共享凭据：多个角色都用智谱时不必填多遍。必须出现在默认配置里，
        # 否则合并时会被整段丢掉（存进去的 Key 下次启动就没了）。
        "shared": {"zai_api_key": "", "zai_base_url": ""},
        "roles": [make_role(key, i) for i, key in enumerate(DEFAULT_ROLE_KEYS)],
    }


# ── 读写 ───────────────────────────────────────────────────────
class LoadResult:
    """加载结果。带上"发生了什么"，好让界面如实告诉用户，而不是闷声回默认值。"""

    def __init__(self, settings, **kw):
        self.settings = settings
        self.created = kw.get("created", False)          # 首次运行
        self.recovered = kw.get("recovered", False)      # 配置损坏已备份
        self.backup_path = kw.get("backup_path", "")
        self.migrated = kw.get("migrated", False)
        self.notes = kw.get("notes", [])
        self.problems = kw.get("problems", [])

    @property
    def needs_setup(self) -> bool:
        """是否还没配好（界面用一条可关闭的提示条告知，而不是弹教程向导）。"""
        return self.created or bool(self.problems)


def _normalize_role(raw: dict, index: int) -> dict:
    """把一条角色记录补齐成完整结构，容忍老配置里缺字段。"""
    base = make_role("__blank__", index)
    if not isinstance(raw, dict):
        return base
    role = dict(base)
    for field in ("id", "name", "color", "source", "model", "base_url",
                  "api_key", "system_prompt"):
        value = raw.get(field)
        if isinstance(value, str) and value.strip():
            role[field] = value.strip() if field != "system_prompt" else value
    if isinstance(raw.get("enabled"), bool):
        role["enabled"] = raw["enabled"]
    tools = raw.get("tools")
    if isinstance(tools, list):
        role["tools"] = [t for t in tools if t in TOOL_NAMES]
    if not role["id"] or not re.match(r"^[A-Za-z][A-Za-z0-9_]*$", role["id"]):
        role["id"] = "role%d" % (index + 1)
    return role


def _migrate_roles(raw_roles) -> list:
    """roles 从 v2 的字典（固定四角色）迁移成 v3 的列表。"""
    if isinstance(raw_roles, list):
        return [_normalize_role(r, i) for i, r in enumerate(raw_roles)]
    if isinstance(raw_roles, dict):
        order = [k for k in DEFAULT_ROLE_KEYS if k in raw_roles]
        order += [k for k in raw_roles if k not in order]
        roles = []
        for i, key in enumerate(order):
            cfg = dict(raw_roles.get(key) or {})
            preset = PRESETS_BY_KEY.get(key, {})
            cfg.setdefault("id", _slug(key, "role%d" % (i + 1)))
            cfg.setdefault("name", cfg.get("display") or preset.get("name") or key)
            cfg.setdefault("color", preset.get("color") or "#5B8CFF")
            cfg.setdefault("enabled", True)
            cfg.setdefault("tools", list(preset.get("tools") or []))
            roles.append(cfg)
        return [_normalize_role(r, i) for i, r in enumerate(roles)]
    return default_settings()["roles"]


def _merge_defaults(data: dict) -> dict:
    """把用户配置合并到默认配置上，保证新增字段有值。"""
    base = default_settings()
    if not isinstance(data, dict):
        return base
    if isinstance(data.get("max_messages"), int) and data["max_messages"] > 0:
        base["max_messages"] = data["max_messages"]
    # 共享凭据段必须显式搬过来。漏掉这一步，用户存的智谱 Key 每次启动都会消失，
    # 而且界面上只表现为"没有配置 Key"，极难排查。
    shared = data.get("shared")
    if isinstance(shared, dict):
        for key, value in shared.items():
            if isinstance(value, str):
                base["shared"][key] = value
    if "roles" in data:
        roles = _migrate_roles(data["roles"])
        if roles:
            base["roles"] = roles
    return base


def _atomic_write_json(path: str, data: dict) -> None:
    """先写临时文件再原子替换。中途崩溃也不会留下半截 JSON。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _backup_corrupt(path: str) -> str:
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = "%s.corrupt-%s" % (path, stamp)
    try:
        shutil.copy2(path, backup)
        return backup
    except Exception:
        return ""


def migrate_legacy_data() -> list:
    """把老版本放在程序目录里的配置/历史/产出搬到新位置。只搬一次，不删原文件。"""
    notes = []
    pairs = [
        (legacy_settings_path(), settings_path(), "配置"),
        (legacy_history_dir(), history_dir(), "聊天记录"),
        (legacy_output_dir(), documents_dir(), "AI 产出的文件"),
    ]
    for old, new, label in pairs:
        try:
            if not os.path.exists(old) or os.path.exists(new):
                continue
            os.makedirs(os.path.dirname(new), exist_ok=True)
            if os.path.isdir(old):
                shutil.copytree(old, new)
            else:
                shutil.copy2(old, new)
            notes.append("%s 已从旧位置迁移" % label)
        except Exception as exc:
            notes.append("%s 迁移失败：%s" % (label, exc))
    return notes


def load_settings(migrate: bool = True) -> LoadResult:
    """读取配置。任何异常都不会静默吞掉，一律在返回值里说清楚。"""
    ensure_dirs()
    notes = []
    if migrate:
        notes.extend(migrate_legacy_data())

    path = settings_path()
    if not os.path.exists(path):
        result = LoadResult(default_settings(), created=True, notes=notes)
        result.problems = validate_settings(result.settings)
        return result

    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, dict):
            raise ValueError("配置根节点不是对象")
    except Exception as exc:
        backup = _backup_corrupt(path)
        result = LoadResult(default_settings(), recovered=True,
                            backup_path=backup, notes=notes)
        result.problems = ["配置文件无法解析（%s），已恢复为默认配置" % exc]
        result.problems.extend(validate_settings(result.settings))
        return result

    settings = decrypt_settings(_merge_defaults(raw))
    result = LoadResult(settings, notes=notes)
    result.problems = validate_settings(settings)
    return result


def save_settings(settings: dict) -> None:
    """保存配置。api_key 字段加密后再落盘。"""
    os.makedirs(config_dir(), exist_ok=True)
    payload = json.loads(json.dumps(settings, ensure_ascii=False))   # 深拷贝
    payload["version"] = CONFIG_VERSION
    encrypt_settings(payload)
    _atomic_write_json(settings_path(), payload)


# ── 角色操作 ───────────────────────────────────────────────────
def enabled_roles(settings: dict) -> list:
    """参与讨论的角色（按列表顺序）。全被禁用时退回全部，避免"一个都不剩"。"""
    roles = [r for r in (settings.get("roles") or []) if r.get("enabled", True)]
    return roles or list(settings.get("roles") or [])


def unique_role_id(settings: dict, base: str = "role") -> str:
    used = {r.get("id") for r in (settings.get("roles") or [])}
    candidate = _slug(base, "role") or "role"
    if candidate not in used:
        return candidate
    n = 2
    while "%s%d" % (candidate, n) in used:
        n += 1
    return "%s%d" % (candidate, n)


# ── 校验 ───────────────────────────────────────────────────────
def validate_role(role: dict) -> list:
    problems = []
    source = (role or {}).get("source", "zhipu")
    model = ((role or {}).get("model") or "").strip()
    if source not in SOURCE_LABELS:
        return ["模型来源无效：%s" % source]
    if source == "custom":
        if not ((role.get("base_url") or "").strip()):
            problems.append("没填 Base URL")
        if not ((role.get("api_key") or "").strip()):
            problems.append("没填 API Key")
        if not model:
            problems.append("没填模型名")
    elif not model:
        problems.append("没选模型")
    return problems


def validate_settings(settings: dict) -> list:
    """返回所有需要用户处理的问题，带角色名。"""
    problems = []
    roles = settings.get("roles") or []
    if not roles:
        problems.append("一个角色都没有，至少添加一个")
        return problems
    if not [r for r in roles if r.get("enabled", True)]:
        problems.append("所有角色都被停用了，至少启用一个")
    for role in roles:
        if not role.get("enabled", True):
            continue
        name = role.get("name") or role.get("id") or "?"
        for p in validate_role(role):
            problems.append("「%s」%s" % (name, p))
    if any((r.get("source", "zhipu") == "zhipu") and r.get("enabled", True) for r in roles):
        if not zhipu_key(settings):
            problems.append("没有配置智谱 API Key（有角色在用云端 GLM）")
    return problems


def zhipu_key(settings: dict = None) -> str:
    """取智谱 Key：先看配置里的共享密钥，再看 .env。"""
    if settings:
        key = ((settings.get("shared") or {}).get("zai_api_key") or "").strip()
        if key:
            return key
    try:
        from dotenv import dotenv_values
        value = (dotenv_values(env_file()).get("ZAI_API_KEY") or "").strip()
        if value and value != "你的智谱密钥":
            return value
    except Exception:
        pass
    return ""


def zhipu_base_url(settings: dict = None) -> str:
    """智谱端点。国内站与国际站的 Key 互不通用，所以必须可配。"""
    if settings:
        base = ((settings.get("shared") or {}).get("zai_base_url") or "").strip()
        if base:
            return base
    try:
        from dotenv import dotenv_values
        base = (dotenv_values(env_file()).get("ZAI_BASE_URL") or "").strip()
        if base:
            return base
    except Exception:
        pass
    return "https://api.z.ai/api/paas/v4"


def github_token() -> str:
    if os.environ.get("GITHUB_TOKEN"):
        return os.environ["GITHUB_TOKEN"]
    try:
        from dotenv import dotenv_values
        return (dotenv_values(env_file()).get("GITHUB_TOKEN") or "").strip()
    except Exception:
        return ""
