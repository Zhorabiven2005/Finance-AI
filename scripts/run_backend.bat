@echo off
chcp 65001 >nul
title Finance AI - backend
cd /d "%~dp0..\backend"
".venv\Scripts\python.exe" -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
echo.
echo Backend stopped.
pause
