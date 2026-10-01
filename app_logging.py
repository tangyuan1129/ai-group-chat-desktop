# -*- coding: utf-8 -*-
"""日志、脱敏与诊断包。

产品级要求里"出问题能查"和"别把密钥写进日志"是一体的：日志文件经常被用户
直接发给开发者，所以**日志本身就是一条泄露渠道**。这里在 Formatter 层做脱敏，
而不是靠调用方自觉。

三层脱敏
--------
1. 运行时登记：配置里出现的真实 Key 一律登记，按字面量替换（最可靠）。
2. 格式兜底：sk- / ghp_ / Bearer / 智谱的 id.secret 形式等常见格式。
3. 导出时再洗一遍：诊断包里的配置只保留结构，密钥字段直接抹掉。
"""
import datetime
import io
import json
import logging
import logging.handlers
import os
import platform
import re
import sys
import traceback
import zipfile

from app_config import (APP_NAME, APP_VERSION, config_dir, documents_dir,
                        logs_dir, settings_path)

__all__ = ["setup_logging", "get_logger", "register_secret", "redact",
           "export_diagnostics", "install_excepthook", "log_file_path"]

MASK = "***已隐藏***"

_secrets = set()

# 常见密钥格式兜底
_PATTERNS = [
    (re.compile(r"\b(?:sk|ghp|gho|ghu|ghs|ghr|glpat)-[A-Za-z0-9_\-]{8,}"), "sk-***"),
    (re.compile(r"\bghp_[A-Za-z0-9]{20,}"), "ghp_***"),
    # 智谱 Key 形如 32位hex.16位字母数字
    (re.compile(r"\b[0-9a-fA-F]{16,}\.[A-Za-z0-9]{8,}\b"), "***.***"),
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-]{8,}"), "Bearer " + MASK),
    # key 名可能自带引号（JSON 就是），所以名字和分隔符之间要允许一个引号：
    #   api_key=xxx  /  "api_key": "xxx"  /  api-key: xxx
    (re.compile(r"(?i)\b(api[_-]?key|apikey|access[_-]?token|auth[_-]?token|authorization"
                r"|secret|password|passwd|credential)\b[\"']?\s*[=:]\s*[\"']?([^\s\"',}]{6,})"),
     r"\1=" + MASK),
]


def register_secret(value: str) -> None:
    """登记一个真实密钥，之后所有日志里出现它都会被替换掉。"""
    if isinstance(value, str) and len(value.strip()) >= 6:
        _secrets.add(value.strip())


def redact(text) -> str:
    """把文本里的密钥抹掉。任何要落盘/外发的内容都应该先过这里。"""
    if text is None:
        return ""
    text = str(text)
    for secret in sorted(_secrets, key=len, reverse=True):
        if secret in text:
            text = text.replace(secret, MASK)
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    return text


class _RedactingFormatter(logging.Formatter):
    """在格式化出口统一脱敏，调用方写什么都不会漏。"""

    def format(self, record: logging.LogRecord) -> str:
        try:
            return redact(super().format(record))
        except Exception:
            return "[日志格式化失败] %s" % redact(record.getMessage())


_log_file = ""


def log_file_path() -> str:
    return _log_file


def setup_logging(level=logging.INFO, console=False) -> str:
    """初始化日志：轮转文件 + 可选控制台。返回日志文件路径。"""
    global _log_file
    os.makedirs(logs_dir(), exist_ok=True)
    _log_file = os.path.join(logs_dir(), "app.log")

    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    fmt = _RedactingFormatter(
        "%(asctime)s %(levelname)-7s [%(name)s] %(message)s", "%Y-%m-%d %H:%M:%S")

    # 5 个文件 × 1MB，够定位问题又不会把用户磁盘写满
    file_handler = logging.handlers.RotatingFileHandler(
        _log_file, maxBytes=1_000_000, backupCount=5, encoding="utf-8")
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    if console or os.environ.get("AIGC_LOG_CONSOLE") == "1":
        stream = logging.StreamHandler(sys.stderr)
        stream.setFormatter(fmt)
        root.addHandler(stream)

    # 第三方库太吵，压一压
    for noisy in ("httpx", "httpcore", "openai", "autogen_core", "autogen_agentchat",
                  "urllib3", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    return _log_file


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def install_excepthook() -> None:
    """未捕获异常也要进日志——否则用户只看到闪退，什么都查不到。"""
    log = get_logger("crash")
    previous = sys.excepthook

    def hook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            previous(exc_type, exc_value, exc_tb)
            return
        log.critical("未捕获异常\n%s",
                     redact("".join(traceback.format_exception(exc_type, exc_value, exc_tb))))
        previous(exc_type, exc_value, exc_tb)

    sys.excepthook = hook


# ── 诊断包 ─────────────────────────────────────────────────────
def _sanitized_settings() -> str:
    """配置的"只留结构不留密钥"版本。"""
    try:
        with open(settings_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        return "（配置读取失败：%s）" % redact(exc)
    for cfg in (data.get("roles") or {}).values():
        if isinstance(cfg, dict):
            for field in ("api_key", "base_url"):
                if cfg.get(field):
                    cfg[field] = MASK
    for key in list((data.get("shared") or {}).keys()):
        data["shared"][key] = MASK
    return json.dumps(data, ensure_ascii=False, indent=2)


def _environment_report() -> str:
    lines = [
        "%s 诊断报告" % APP_NAME,
        "程序版本: %s" % APP_VERSION,
        "生成时间: %s" % datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "操作系统: %s %s (%s)" % (platform.system(), platform.release(), platform.version()),
        "Python  : %s" % sys.version.replace("\n", " "),
        "可执行文件: %s" % sys.executable,
        "打包运行: %s" % getattr(sys, "frozen", False),
        "配置目录: %s" % config_dir(),
        "产出目录: %s" % documents_dir(),
        "",
        "依赖版本:",
    ]
    for mod in ("PySide6", "autogen_agentchat", "autogen_core", "autogen_ext", "openai", "httpx"):
        try:
            m = __import__(mod)
            lines.append("  %-18s %s" % (mod, getattr(m, "__version__", "?")))
        except Exception as exc:
            lines.append("  %-18s 缺失 (%s)" % (mod, type(exc).__name__))

    lines += ["", "本机 Ollama:"]
    try:
        import urllib.request
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open("http://127.0.0.1:11434/api/tags", timeout=3) as r:
            data = json.loads(r.read().decode("utf-8"))
        models = [m.get("name") for m in data.get("models", [])]
        lines.append("  可连接，模型: %s" % (", ".join(models) if models else "（无）"))
    except Exception as exc:
        lines.append("  不可连接 (%s)" % type(exc).__name__)

    lines += ["", "配置文件（已脱敏）:", _sanitized_settings()]
    return "\n".join(lines)


def export_diagnostics(dest_path: str = None) -> str:
    """把日志 + 环境信息打成一个 zip，方便用户直接发给你排查。"""
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    if not dest_path:
        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        folder = desktop if os.path.isdir(desktop) else documents_dir()
        os.makedirs(folder, exist_ok=True)
        dest_path = os.path.join(folder, "%s-诊断包-%s.zip" % (APP_NAME, stamp))

    os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
    with zipfile.ZipFile(dest_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("环境信息.txt", redact(_environment_report()))
        logs = logs_dir()
        if os.path.isdir(logs):
            for name in sorted(os.listdir(logs)):
                if name.endswith(".log") or ".log." in name:
                    try:
                        with open(os.path.join(logs, name), "r",
                                  encoding="utf-8", errors="replace") as f:
                            zf.writestr("logs/" + name, redact(f.read()))
                    except Exception:
                        pass
        zf.writestr("说明.txt",
                    "这是 %s 的诊断包，用于排查问题。\n"
                    "其中所有密钥已自动脱敏（替换为 %s），可以放心发送。\n" % (APP_NAME, MASK))
    return dest_path


if __name__ == "__main__":
    import tempfile
    os.environ["AIGC_CONFIG_DIR"] = tempfile.mkdtemp(prefix="aigc_log_")
    path = setup_logging(console=True)
    log = get_logger("demo")
    log.info("日志文件在 %s", path)

    fake_zhipu = "abcdef0123456789abcdef0123456789.AbCdEf123456"
    fake_openai = "sk-proj-ABCDEFGHIJKLMNOPQRSTUVWXYZ012345"
    fake_json = "another-secret-value"
    register_secret(fake_zhipu)
    log.info("智谱 Key 是 %s（应被隐藏）", fake_zhipu)
    log.info("OpenAI Key 是 %s（应被隐藏）", fake_openai)
    log.info("请求头 Authorization: Bearer %s", fake_openai)
    log.info('配置内容 {"api_key": "%s"}', fake_json)
    log.info("YAML 形式 api_key: %s", fake_json)
    log.info("命令行形式 --token=%s", fake_openai)
    log.info("普通信息：模型 glm-4.7-flash，轮次 18，max_tokens 4096")

    content = open(path, encoding="utf-8").read()
    print()
    print("=" * 66)
    print("日志实际落盘内容：")
    print(content)
    print("=" * 66)
    # 三个都要查，漏一个就等于没测
    leaked = [s for s in (fake_zhipu, fake_openai, fake_json) if s in content]
    print("泄露的密钥:", leaked if leaked else "无 ✅")
    zip_path = export_diagnostics()
    print("诊断包:", zip_path)
    with zipfile.ZipFile(zip_path) as zf:
        print("包含:", zf.namelist())
        blob = "\n".join(zf.read(n).decode("utf-8", "replace") for n in zf.namelist())
    leaked2 = [s for s in (fake_zhipu, fake_openai, fake_json) if s in blob]
    print("诊断包里泄露的密钥:", leaked2 if leaked2 else "无 ✅")
    print("正常信息没被误伤:", "glm-4.7-flash" in content and "4096" in content)
