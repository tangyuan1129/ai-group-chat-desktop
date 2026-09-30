# -*- coding: utf-8 -*-
"""配置与路径：读写、校验、损坏恢复、老版本数据迁移。

这里修掉旧版的三个产品级缺陷
----------------------------
1. **写配置不是原子的**。旧版直接 ``open(..., "w")`` 覆写 team_settings.json，
   崩在写一半就得到一个半截 JSON；下次启动 json.load 失败 → 静默回默认值，
   用户配置无声消失。这里改成"写临时文件 + 原子替换"，并且损坏时**备份 + 明确
   告诉用户**，绝不静默吞掉。
2. **配置和产出都塞在程序目录**。装到 D:\\ 根目录需要管理员权限，普通用户写不
   进去就整个功能失效。现在用户数据放 %APPDATA%，AI 产出的文件放"文档"目录，
   用户找得到、也不依赖安装位置。
3. **密钥明文落盘**。见 secret_store.py，这里负责接上。
"""
import datetime
import json
import os
import shutil
import tempfile

from secret_store import decrypt_settings, encrypt_settings

APP_NAME = "AI团队群聊"

# 打包成 exe 后 __file__ 指向解包临时目录，所以只在开发态用它定位老数据
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))


# ── 路径 ───────────────────────────────────────────────────────
def _env_dir(name: str) -> str:
    return os.environ.get(name) or os.path.expanduser("~")


def config_dir() -> str:
    """配置、历史、日志：%APPDATA%\\AI团队群聊（不需要管理员权限）。"""
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
    """开发/高级用户仍可用 .env 提供 Key（优先级低于加密存储）。"""
    return os.environ.get("AIGC_ENV_FILE") or os.path.join(_THIS_DIR, ".env")


def ensure_dirs() -> None:
    for d in (config_dir(), history_dir(), logs_dir(), documents_dir()):
        try:
            os.makedirs(d, exist_ok=True)
        except Exception:
            pass


# ── 默认配置 ───────────────────────────────────────────────────
# 顺序即发言顺序：经理主持 → 策划提方案 → 工程师评估 → 评审把关
DEFAULT_ROLES = [
    ("manager",   "经理",   "#2D7DFF", "zhipu",  "glm-4.7-flash",
     "你是项目经理，主持讨论：先拆解问题；出现分歧时裁决；最后把方案整理成明确分工。"
     "所有发言必须用中文，简洁有观点，每次发言不超过150字，直接说内容，不要寒暄。"),
    ("planner",   "策划",   "#FF7A2D", "ollama", "qwen2.5:7b",
     "你是创意策划：负责提点子和方案设计，敢于反驳别人，但认可已被说服的观点。"
     "所有发言必须用中文，简洁有观点，每次发言不超过150字，直接说内容，不要寒暄。"),
    ("engineer",  "工程师", "#2EA84B", "zhipu",  "glm-4.7-flash",
     "你是技术专家：负责评估可行性、指出风险、给落地建议。"
     "所有发言必须用中文，简洁有观点，每次发言不超过150字，直接说内容，不要寒暄。"),
    ("reviewer",  "评审",   "#9B59D0", "ollama", "qwen2.5:7b",
     "你是评审官：负责挑漏洞把关。当经理给出明确分工且方案合理时，简短总结并在最后一行单独输出：APPROVE。"
     "所有发言必须用中文，简洁有观点，每次发言不超过150字，直接说内容，不要寒暄。"),
]

ROLE_ORDER = tuple(r[0] for r in DEFAULT_ROLES)

SOURCE_LABELS = {"zhipu": "云端智谱 GLM", "ollama": "本地 Ollama", "custom": "自定义 API"}
SOURCE_SHORT = {"zhipu": "云端GLM", "ollama": "本地Ollama", "custom": "自定义API"}

DEFAULT_MAX_ROUNDS = 18


def default_settings() -> dict:
    return {
        "version": 2,
        "max_messages": DEFAULT_MAX_ROUNDS,
        # 共享凭据：四个角色都用智谱时不必填四遍。必须出现在默认配置里，
        # 否则 _merge_defaults 会把它整段丢掉（引导向导存的 Key 下次启动就没了）。
        "shared": {"zai_api_key": "", "zai_base_url": ""},
        "roles": {
            name: {
                "display": cn, "color": color,
                "source": src, "model": model,
                "base_url": "", "api_key": "",
                "system_prompt": prompt,
            }
            for name, cn, color, src, model, prompt in DEFAULT_ROLES
        },
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
        self.notes = kw.get("notes", [])                 # 给用户看的说明
        self.problems = kw.get("problems", [])           # 校验发现的问题

    @property
    def needs_onboarding(self) -> bool:
        """是否该弹首次引导。"""
        return self.created or bool(self.problems)


def _merge_defaults(data: dict) -> dict:
    """把用户配置合并到默认配置上，保证新增角色/字段有值。"""
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
    user_roles = data.get("roles")
    if isinstance(user_roles, dict):
        for name, cfg in user_roles.items():
            if name in base["roles"] and isinstance(cfg, dict):
                base["roles"][name].update(cfg)
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
        os.replace(tmp, path)          # 同一分区上的原子替换
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
        result = LoadResult(
            default_settings(), recovered=True, backup_path=backup, notes=notes,
            problems=["配置文件无法解析（%s），已恢复为默认配置" % exc],
        )
        result.problems.extend(validate_settings(result.settings))
        return result

    settings = _merge_defaults(raw)
    settings = decrypt_settings(settings)
    result = LoadResult(settings, notes=notes)
    result.problems = validate_settings(settings)
    return result


def save_settings(settings: dict) -> None:
    """保存配置。api_key 字段加密后再落盘。"""
    os.makedirs(config_dir(), exist_ok=True)
    payload = json.loads(json.dumps(settings, ensure_ascii=False))   # 深拷贝，别改调用方的对象
    payload["version"] = 2
    encrypt_settings(payload)
    _atomic_write_json(settings_path(), payload)


# ── 校验 ───────────────────────────────────────────────────────
def validate_role(cfg: dict) -> list:
    """校验单个角色，返回问题列表（空列表表示没问题）。"""
    problems = []
    source = (cfg or {}).get("source", "zhipu")
    model = ((cfg or {}).get("model") or "").strip()
    if source not in SOURCE_LABELS:
        return ["模型来源无效：%s" % source]
    if source == "custom":
        if not ((cfg.get("base_url") or "").strip()):
            problems.append("没填 Base URL")
        if not ((cfg.get("api_key") or "").strip()):
            problems.append("没填 API Key")
        if not model:
            problems.append("没填模型名")
    elif not model:
        problems.append("没选模型")
    return problems


def validate_settings(settings: dict) -> list:
    """返回所有需要用户处理的问题，带角色中文名。"""
    problems = []
    roles = settings.get("roles") or {}
    for name in ROLE_ORDER:
        cfg = roles.get(name) or {}
        cn = cfg.get("display") or name
        for p in validate_role(cfg):
            problems.append("「%s」%s" % (cn, p))
    # 智谱 Key：加密存储里没有就看 .env
    if any((roles.get(n) or {}).get("source", "zhipu") == "zhipu" for n in ROLE_ORDER):
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


if __name__ == "__main__":
    import tempfile
    os.environ["AIGC_CONFIG_DIR"] = tempfile.mkdtemp(prefix="aigc_cfg_")
    os.environ["AIGC_WORK_ROOT"] = tempfile.mkdtemp(prefix="aigc_out_")
    print("配置目录:", config_dir())
    print("产出目录:", documents_dir())

    r = load_settings(migrate=False)
    print("首次加载 → created=%s problems=%s" % (r.created, r.problems))

    s = r.settings
    s["roles"]["engineer"]["source"] = "custom"
    s["roles"]["engineer"]["base_url"] = "https://api.deepseek.com/v1"
    s["roles"]["engineer"]["api_key"] = "sk-secret"
    s["roles"]["engineer"]["model"] = "deepseek-chat"
    save_settings(s)
    print("已保存，落盘内容里是否还有明文 Key:",
          "sk-secret" in open(settings_path(), encoding="utf-8").read())

    r2 = load_settings(migrate=False)
    print("重新加载 Key 正确解密:", r2.settings["roles"]["engineer"]["api_key"] == "sk-secret")
    print("校验问题:", r2.problems)

    with open(settings_path(), "w", encoding="utf-8") as f:
        f.write('{"roles": {"manager": ')          # 故意写坏
    r3 = load_settings(migrate=False)
    print("损坏恢复 → recovered=%s 备份=%s" % (r3.recovered, os.path.basename(r3.backup_path)))
    print("损坏后仍是完整默认配置:", bool(r3.settings["roles"]["manager"]["system_prompt"]))
