@echo off
chcp 65001 >nul
title Finance AI - alembic check (isolated)
rem Безопасный alembic check: основная backend\data\finance.db не открывается.
rem Без аргументов - пустая временная БД; "copy" - проверка копии рабочей БД.
cd /d "%~dp0..\backend"
if "%~1"=="" (
  ".venv\Scripts\python.exe" "%~dp0alembic_check_isolated.py"
) else (
  ".venv\Scripts\python.exe" "%~dp0alembic_check_isolated.py" --mode %~1
)
pause
