# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：AI 团队群聊桌面版

在项目根目录执行：pyinstaller pack.spec --noconfirm
产物在 dist/AI团队群聊/。

注意：这里刻意不写任何绝对路径。旧版把 pathex 硬编码成作者本机的
"D:/ai-studio/release/ai-group-chat"，换台机器或换个人就构建不出来 ——
这是"能发布"和"只有我能跑"的分界线。
"""
import os

from PyInstaller.utils.hooks import collect_all, collect_submodules

# SPECPATH 由 PyInstaller 注入，指向本 spec 文件所在目录
PROJECT_DIR = SPECPATH
APP_NAME = "AI团队群聊"

hidden = []
datas = []
binaries = []

# 这些包在代码里是运行时动态导入的（比如按来源选客户端），静态分析扫不到，
# 必须整包收集，否则打包后一用就 ModuleNotFoundError。
for pkg in ["glm_client", "autogen_agentchat", "autogen_core", "autogen_ext",
            "openai", "dotenv", "PySide6", "httpx"]:
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hidden += h
    except Exception as e:
        print("收集 %s 失败: %s" % (pkg, e))

# 补充动态子模块
for mod in ["autogen_ext.models.ollama", "autogen_ext.models.openai",
            "autogen_agentchat.agents", "autogen_agentchat.teams",
            "autogen_agentchat.conditions", "autogen_agentchat.messages",
            "autogen_core.tools", "autogen_core.models",
            "autogen_ext.tools.code_execution", "glm_client"]:
    hidden += collect_submodules(mod)

# 本项目自己的模块，显式列一遍更保险
hidden += ["app_config", "app_logging", "secret_store", "team_session",
           "llm", "onboarding", "tools"]

# 图标随包带上，运行时按文件名查找
for asset in ("app.ico", "logo.png"):
    path = os.path.join(PROJECT_DIR, asset)
    if os.path.exists(path):
        datas.append((path, "."))

a = Analysis(
    [os.path.join(PROJECT_DIR, "desktop_app.py")],
    pathex=[PROJECT_DIR],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # 砍掉用不到的大块头，安装包体积能小一截
    excludes=[
        "tkinter", "unittest", "pydoc_data", "test",
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
        "PySide6.Qt3DCore", "PySide6.QtMultimedia", "PySide6.QtQuick",
        "PySide6.QtQml", "PySide6.QtDesigner", "PySide6.QtCharts",
        "PySide6.QtDataVisualization", "PySide6.QtBluetooth",
        "PySide6.QtNetworkAuth", "PySide6.QtRemoteObjects",
        "PySide6.QtSensors", "PySide6.QtSerialPort", "PySide6.QtSql",
        "PySide6.QtTest", "PySide6.QtWebChannel", "PySide6.QtWebSockets",
        "matplotlib", "numpy", "pandas", "scipy", "PIL",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon=[os.path.join(PROJECT_DIR, "app.ico")],
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name=APP_NAME,
)
