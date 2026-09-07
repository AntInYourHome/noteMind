@echo off
rem 后台服务包装：uvicorn 退出后 5 秒自动重启（由计划任务 SuperTools 在开机时拉起）
set PORT=8000
cd /d "%~dp0..\..\server"
:loop
"venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port %PORT% >> "..\logs\backend.log" 2>&1
timeout /t 5 /nobreak >nul
goto loop
