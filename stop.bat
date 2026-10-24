@echo off
setlocal EnableExtensions
title Finance AI - stop

cd /d "%~dp0"
set "BACKEND_PORT=8000"
set "FRONTEND_PORT=5173"
set "BACKEND_TITLE=Finance AI - backend"
set "FRONTEND_TITLE=Finance AI - frontend"

echo ==========================================
echo   Finance AI - stopping
echo ==========================================
echo.

set "STOPPED=0"

rem ---------------------------------------------------------------
rem 1. Close the launcher windows together with everything they
rem    spawned. /T kills the whole process tree, so the uvicorn
rem    reloader and its worker, and npm together with node, all go
rem    down in one step.
rem ---------------------------------------------------------------
call :kill_window "%BACKEND_TITLE%"  backend
call :kill_window "%FRONTEND_TITLE%" frontend

rem Windows releases a listening socket a moment after the owning
rem process dies. Without this pause the check below can still see a
rem dead PID and report a false failure.
timeout /t 2 /nobreak >nul

rem ---------------------------------------------------------------
rem 2. Release the ports. Catches services started by hand and
rem    orphans left behind when a window was closed abruptly.
rem ---------------------------------------------------------------
call :kill_port %BACKEND_PORT%  backend
call :kill_port %FRONTEND_PORT% frontend

rem ---------------------------------------------------------------
rem 3. Report the result.
rem ---------------------------------------------------------------
echo.
call :get_port_pid %BACKEND_PORT% LEFT_BACKEND
call :get_port_pid %FRONTEND_PORT% LEFT_FRONTEND

if defined LEFT_BACKEND goto :still_running
if defined LEFT_FRONTEND goto :still_running

if "%STOPPED%"=="0" (
  echo Finance AI was not running. Nothing to stop.
) else (
  echo Finance AI stopped. Ports %BACKEND_PORT% and %FRONTEND_PORT% are free.
)
echo.
timeout /t 4 /nobreak >nul
exit /b 0

:still_running
echo [WARNING] Some processes are still holding the ports:
if defined LEFT_BACKEND  echo   port %BACKEND_PORT%  : PID %LEFT_BACKEND%
if defined LEFT_FRONTEND echo   port %FRONTEND_PORT% : PID %LEFT_FRONTEND%
echo.
echo Close the remaining windows manually, or run stop.bat again.
echo.
pause
exit /b 1


rem ===============================================================
rem Subroutines
rem ===============================================================

rem Kills a console window and its children by title.
rem   %1 = window title (quoted), %2 = label for the log
:kill_window
tasklist /FI "WINDOWTITLE eq %~1*" /NH 2>nul | findstr /I /C:"cmd.exe" >nul
if errorlevel 1 exit /b 0
taskkill /FI "WINDOWTITLE eq %~1*" /T /F >nul 2>&1
echo   closed %~2 window
set "STOPPED=1"
exit /b 0

rem Kills whatever is listening on a port.
rem   %1 = port number, %2 = label for the log
:kill_port
call :get_port_pid %~1 _pid
if not defined _pid exit /b 0
taskkill /PID %_pid% /T /F >nul 2>&1
timeout /t 1 /nobreak >nul
rem Trust the port, not the taskkill exit code: the process was very
rem likely already terminated as part of a window's process tree,
rem which is a success, not an error.
call :get_port_pid %~1 _pid_left
if defined _pid_left (
  echo   could not free port %~1 ^(%~2^), still held by PID %_pid_left%
) else (
  echo   stopped %~2 process %_pid% on port %~1
  set "STOPPED=1"
)
exit /b 0

rem Finds the PID listening on a TCP port.
rem   %1 = port number, %2 = name of the variable that receives the PID
rem
rem Deliberately no "-p TCP": that flag hides IPv6 sockets, and Vite
rem binds to ::1 by default.
:get_port_pid
set "%~2="
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /C:":%~1 " ^| findstr /I "LISTENING"') do (
  if not defined %~2 set "%~2=%%p"
)
exit /b 0
