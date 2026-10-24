@echo off
chcp 65001 >nul
title Finance AI - migrations
cd /d "%~dp0..\backend"
if "%~1"=="" (
  ".venv\Scripts\python.exe" -m alembic upgrade head
) else (
  ".venv\Scripts\python.exe" -m alembic revision --autogenerate -m "%~1"
)
pause
