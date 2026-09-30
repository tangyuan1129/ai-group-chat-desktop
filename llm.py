# -*- coding: utf-8 -*-
"""模型客户端构造与连通性测试。

为什么单独一个模块
------------------
客户端构造既被会话用（team_session），也被首启引导用（onboarding 要"测试连接"）。
放在 UI 里会让 UI 依赖具体模型实现，放在会话里会让引导依赖会话，都不合适。

这里还修了一个产品体验问题：旧版没开 reflect_on_tool_use，导致 AI 调用工具之后
界面上直接糊一段原始的 [FunctionCall]/[FunctionExecutionResult] 文本，而不是让
模型读完工具结果后用自然语言回答。产品不该把内部协议暴露给用户。
"""
import json
import urllib.request

from app_config import SOURCE_LABELS, zhipu_base_url, zhipu_key

__all__ = ["make_client", "test_connection", "fetch_ollama_models", "OLLAMA_API",
           "format_error", "ClientBuildError", "ZHIPU_MODELS",
           "ZHIPU_BASE_INTL", "ZHIPU_BASE_CN"]

OLLAMA_API = "http://127.0.0.1:11434"

# 智谱常见的可用模型（可自行编辑补充）
ZHIPU_MODELS = [
    "glm-4.7-flash", "glm-4.5", "glm-4.5-air", "glm-4.6", "glm-4.7",
    "glm-5", "glm-5-turbo", "glm-5.1", "glm-5.2", "glm-5.3", "glm-5.3-flash",
]

ZHIPU_BASE_INTL = "https://api.z.ai/api/paas/v4"
ZHIPU_BASE_CN = "https://open.bigmodel.cn/api/paas/v4"


class ClientBuildError(RuntimeError):
    """配置问题导致客户端建不起来。消息是给用户看的中文，可直接显示。"""


def format_error(exc: BaseException) -> str:
    """把异常压成一句人话，尽量带上底层原因（裸 401 对用户毫无信息量）。"""
    import traceback
    parts, cur, depth = [], exc, 0
    while cur is not None and depth < 4:
        text = "".join(traceback.format_exception_only(type(cur), cur)).strip()
        if text and text not in parts:
            parts.append(text)
        cur = cur.__cause__ or cur.__context__
        depth += 1
    text = "\n".join(parts) or exc.__class__.__name__
    low = text.lower()
    if "401" in text or "authentication" in low or "invalid api key" in low or "unauthorized" in low:
        text += ("\n提示：Key 或接口地址不匹配。智谱国内站（open.bigmodel.cn）和国际站"
                 "（api.z.ai）的 Key 互不通用，请确认申请 Key 的站点与接口地址一致。")
    return text


def fetch_ollama_models() -> list:
    """查询本地 Ollama 的模型列表，失败返回空列表。"""
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # 本地直连，不走代理
        with opener.open("%s/api/tags" % OLLAMA_API, timeout=5) as r:
            data = json.loads(r.read().decode("utf-8"))
        return [m["name"] for m in data.get("models", [])]
    except Exception:
        return []


def make_client(role_cfg, settings=None):
    """按角色配置构建模型客户端，返回 (client, 来源描述)。

    注意：调用方必须负责 close()，否则每次讨论都会漏掉一组 HTTP 连接。
    """
    source = (role_cfg or {}).get("source", "zhipu")
    model = ((role_cfg or {}).get("model") or "").strip()

    if source == "ollama":
        if not model:
            raise ClientBuildError("没有选本地模型（先在命令行执行 ollama pull qwen2.5:7b）")
        from autogen_ext.models.ollama import OllamaChatCompletionClient
        return OllamaChatCompletionClient(model=model), SOURCE_LABELS["ollama"]

    if source == "custom":
        from autogen_ext.models.openai import OpenAIChatCompletionClient
        base = (role_cfg.get("base_url") or "").strip()
        key = (role_cfg.get("api_key") or "").strip()
        if not base:
            raise ClientBuildError("选了「自定义 API」但没填 Base URL（例如 https://api.deepseek.com/v1）")
        if not key:
            raise ClientBuildError("选了「自定义 API」但没填 API Key")
        if not model:
            raise ClientBuildError("选了「自定义 API」但没填模型名（例如 deepseek-chat）")
        return OpenAIChatCompletionClient(
            model=model, base_url=base, api_key=key,
            max_retries=6, timeout=240,
        ), SOURCE_LABELS["custom"]

    # 默认：智谱 GLM
    from glm_client import GLMStudioClient
    key = zhipu_key(settings)
    if not key:
        raise ClientBuildError(
            "没有配置智谱 API Key。请点「⚙ 配置模型」填写，"
            "或把 .env.example 复制为 .env 并填入 ZAI_API_KEY。")
    return GLMStudioClient(
        model=model or "glm-4.7-flash",
        base_url=zhipu_base_url(settings), api_key=key,
        max_retries=6, timeout=240, retry_429=8, retry_429_base=5.0,
        model_info={"vision": False, "function_calling": True, "json_output": True,
                    "structured_output": True, "family": "unknown"},
    ), SOURCE_LABELS["zhipu"]


async def test_connection(role_cfg, settings=None, timeout=30) -> tuple:
    """真的发一次最小请求，确认这个角色的配置能用。

    返回 (是否成功, 说明文字)。引导向导靠它避免"填完以为好了、一发任务就报错"。
    """
    import asyncio

    client = None
    try:
        client, label = make_client(role_cfg, settings)
    except ClientBuildError as exc:
        return False, str(exc)
    except Exception as exc:
        return False, format_error(exc)

    try:
        from autogen_core.models import UserMessage

        async def call():
            return await client.create(
                messages=[UserMessage(content="请只回复两个字：正常", source="user")])

        result = await asyncio.wait_for(call(), timeout=timeout)
        content = str(getattr(result, "content", "")).strip()
        return True, "连接正常，模型回复：%s" % (content[:40] or "（空）")
    except asyncio.TimeoutError:
        return False, "连接超时（%d 秒无响应）。检查网络、代理，或本地模型是否已启动。" % timeout
    except Exception as exc:
        return False, format_error(exc)
    finally:
        if client is not None:
            try:
                await client.close()
            except Exception:
                pass
