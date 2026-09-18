@echo off
chcp 65001 >nul
:: AI 团队群聊 · 桌面版 启动器（无黑窗）
:: 用 %%~dp0 定位脚本自身所在目录，开发版与发布版共用同一份文件
cd /d "%~dp0"
if exist "%~dp0venv\Scripts\pythonw.exe" (
  start "" "%~dp0venv\Scripts\pythonw.exe" "%~dp0desktop_app.py"
) else (
  start "" pythonw "%~dp0desktop_app.py"
)
