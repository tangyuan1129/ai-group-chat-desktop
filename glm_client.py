# -*- coding: utf-8 -*-
"""AutoGen Studio 用的智谱 GLM 模型客户端。

放在 site-packages 里，Studio 的组件加载器按 provider 路径
"glm_client.GLMStudioClient" 导入本类。
作用：在传输层给对话请求注入 thinking=disabled，避免 GLM 思考
模型的草稿漏进正文（create() 层禁传 extra_body，httpx 事件钩子
改不到数据流，所以用自定义 transport 重建请求体）。
免费 glm-4.7-flash 偶发 429（服务瞬时过载），本类在外层加
指数退避重试，避免一次限流中断整个群聊。
"""
import asyncio
import json

import httpx
from autogen_ext.models.openai import OpenAIChatCompletionClient
from openai import RateLimitError


class _ThinkingOffTransport(httpx.AsyncHTTPTransport):
    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/chat/completions"):
            body = await request.aread()
            data = json.loads(body)
            if isinstance(data, dict):
                data["thinking"] = {"type": "disabled"}
                new_body = json.dumps(data, ensure_ascii=False).encode("utf-8")
                new_req = httpx.Request(
                    request.method, request.url,
                    content=new_body, headers=request.headers,
                )
                new_req.headers["content-length"] = str(len(new_body))
                request = new_req
        return await super().handle_async_request(request)


class GLMStudioClient(OpenAIChatCompletionClient):
    def __init__(self, **kwargs):
        # 429 退避重试参数（不进组件 config，仅外层包装用）
        self._retry_429 = int(kwargs.pop("retry_429", 6))
        self._retry_429_base = float(kwargs.pop("retry_429_base", 4.0))
        kwargs.setdefault(
            "http_client",
            httpx.AsyncClient(transport=_ThinkingOffTransport()),
        )
        super().__init__(**kwargs)

    async def _call_with_429_retry(self, coro_factory):
        """429 限流时指数退避重试；其它错误直接抛。"""
        for attempt in range(self._retry_429 + 1):
            try:
                return await coro_factory()
            except RateLimitError:
                if attempt >= self._retry_429:
                    raise
                wait = self._retry_429_base * (2 ** attempt)
                print(f"[GLM] 429 限流，{wait:.0f}s 后重试 ({attempt + 1}/{self._retry_429})", flush=True)
                await asyncio.sleep(wait)

    async def create(self, *args, **kwargs):
        return await self._call_with_429_retry(
            lambda: super(GLMStudioClient, self).create(*args, **kwargs))

    async def create_stream(self, *args, **kwargs):
        return await self._call_with_429_retry(
            lambda: super(GLMStudioClient, self).create_stream(*args, **kwargs))
