@echo off
chcp 65001 >nul
title Finance AI - frontend
cd /d "%~dp0..\frontend"
call npm run dev
echo.
echo Frontend stopped.
pause
