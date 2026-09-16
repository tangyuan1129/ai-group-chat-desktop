@echo off
chcp 65001 >nul
:: AI 团队群聊 · 桌面版 启动器（无黑窗）
cd /d D:\ai-studio
start "" "D:\ai-studio\venv\Scripts\pythonw.exe" "D:\ai-studio\desktop_app.py"