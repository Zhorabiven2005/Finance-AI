@echo off
chcp 65001 >nul
title Finance AI - tests
cd /d "%~dp0..\backend"
".venv\Scripts\python.exe" -m pytest
pause
