@echo off
chcp 65001 >nul
:: AI 团队群聊 · 桌面版 启动器
:: 用 %~dp0 定位脚本自身所在目录，开发版与发布版共用同一份文件。
::
:: 用 pythonw 而不是 python —— python 是控制台程序，会一直挂着一个黑窗。
:: 想要完全不闪黑窗，双击「启动（无黑窗）.vbs」。
setlocal
cd /d "%~dp0"

set "PYW=%~dp0venv\Scripts\pythonw.exe"
if not exist "%PYW%" for %%I in (pythonw.exe) do set "PYW=%%~$PATH:I"

if not defined PYW (
  echo.
  echo   找不到 pythonw.exe。
  echo.
  echo   请先安装 Python 3.10+，安装时记得勾选 "Add Python to PATH"；
  echo   或者在程序目录下建好 venv 并执行 pip install -r requirements.txt。
  echo.
  pause
  exit /b 1
)

start "" "%PYW%" "%~dp0desktop_app.py"
