# -*- coding: utf-8 -*-
"""直接测试本地视觉服务：把界面截图喂给 llama-server，看它能不能描述出来。

这一步只验证"模型真的能看图"，不经过 DSH 插件。
"""
import base64
import json
import sys
import urllib.request

ENDPOINT = "http://127.0.0.1:8080/v1/chat/completions"
IMAGE = sys.argv[1] if len(sys.argv) > 1 else "screenshots/main.png"
PROMPT = sys.argv[2] if len(sys.argv) > 2 else (
    "这是一个桌面软件的界面截图。请客观描述你看到的：整体布局、"
    "左侧有什么、中间有什么、底部有什么、配色是什么样。不要客套，直接说事实。")

with open(IMAGE, "rb") as f:
    b64 = base64.b64encode(f.read()).decode("ascii")

payload = {
    "model": "qwen2.5-vl",
    "messages": [{
        "role": "user",
        "content": [
            {"type": "text", "text": PROMPT},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + b64}},
        ],
    }],
    "max_tokens": 700,
    "temperature": 0.2,
}

req = urllib.request.Request(
    ENDPOINT, data=json.dumps(payload).encode("utf-8"),
    headers={"Content-Type": "application/json"})

print("图片: %s (%.0f KB)" % (IMAGE, len(b64) * 3 / 4 / 1024))
print("提问: %s" % PROMPT[:80])
print("-" * 70)
try:
    with urllib.request.urlopen(req, timeout=300) as r:
        data = json.loads(r.read().decode("utf-8"))
    print(data["choices"][0]["message"]["content"])
except Exception as exc:
    print("失败: %s" % exc)
    if hasattr(exc, "read"):
        print(exc.read().decode("utf-8", "replace")[:500])
