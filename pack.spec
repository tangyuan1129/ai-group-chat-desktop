# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：AI 团队群聊桌面版"""
from PyInstaller.utils.hooks import collect_all, collect_submodules

# 动态导入的包，全部收集
hidden = []
datas = []
binaries = []

for pkg in ["glm_client", "autogen_agentchat", "autogen_core", "autogen_ext",
            "openai", "dotenv", "PySide6"]:
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hidden += h
    except Exception as e:
        print(f"收集 {pkg} 失败: {e}")

# 补充动态子模块
for mod in ["autogen_ext.models.ollama", "autogen_ext.models.openai",
            "autogen_agentchat.agents", "autogen_agentchat.teams",
            "autogen_agentchat.conditions", "autogen_core.tools",
            "autogen_ext.tools.code_execution", "glm_client"]:
    hidden += collect_submodules(mod)

a = Analysis(
    ["desktop_app.py"],
    pathex=["D:/ai-studio/release/ai-group-chat"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name="AI团队群聊",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon=["app.ico"],
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="AI团队群聊",
)