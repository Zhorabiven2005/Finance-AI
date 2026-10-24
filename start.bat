@echo off
setlocal EnableExtensions
title Finance AI - launcher

rem Project root is the folder containing this file, so a double-click
rem in Explorer works regardless of the current working directory.
cd /d "%~dp0"
set "ROOT=%~dp0"
set "BACKEND_PORT=8000"
set "FRONTEND_PORT=5173"
set "BACKEND_URL=http://127.0.0.1:8000/api/v1/health"
set "FRONTEND_URL=http://localhost:5173"
set "APP_URL=http://localhost:5173"
set "BACKEND_TITLE=Finance AI - backend"
set "FRONTEND_TITLE=Finance AI - frontend"

rem curl.exe ships with Windows 10 1803 and later. When present it gives
rem a far more reliable readiness signal than a port scan, because it
rem resolves localhost exactly the way the browser will.
set "HAVE_CURL="
where curl.exe >nul 2>&1 && set "HAVE_CURL=1"

echo ==========================================
echo   Finance AI
echo ==========================================
echo.

rem ---------------------------------------------------------------
rem 1. Environment checks. Nothing is installed or created here.
rem ---------------------------------------------------------------
if not exist "%ROOT%backend\.venv\Scripts\python.exe" goto :err_no_venv
if not exist "%ROOT%frontend\node_modules\."          goto :err_no_modules
if not exist "%ROOT%backend\.env"                     goto :err_no_env
if not exist "%ROOT%scripts\run_backend.bat"          goto :err_no_scripts
if not exist "%ROOT%scripts\run_frontend.bat"         goto :err_no_scripts

if not exist "%ROOT%backend\data\finance.db" (
  echo [WARNING] Database file not found:
  echo           %ROOT%backend\data\finance.db
  echo           Run setup.bat once to apply migrations.
  echo.
)

rem ---------------------------------------------------------------
rem 2. Port checks before starting anything.
rem ---------------------------------------------------------------
call :get_port_pid %BACKEND_PORT% BUSY_BACKEND
call :get_port_pid %FRONTEND_PORT% BUSY_FRONTEND

if defined BUSY_BACKEND (
  set "BUSY_PORT=%BACKEND_PORT%"
  set "BUSY_PID=%BUSY_BACKEND%"
  goto :err_port_busy
)
if defined BUSY_FRONTEND (
  set "BUSY_PORT=%FRONTEND_PORT%"
  set "BUSY_PID=%BUSY_FRONTEND%"
  goto :err_port_busy
)

rem ---------------------------------------------------------------
rem 3. Launch. Two independent minimized windows: closing or
rem    crashing one does not affect the other. Both wrappers end
rem    with pause, so a crashed service leaves its log on screen.
rem ---------------------------------------------------------------
echo Starting backend  on 127.0.0.1:%BACKEND_PORT% ...
start "%BACKEND_TITLE%" /min "%ROOT%scripts\run_backend.bat"

echo Starting frontend on localhost:%FRONTEND_PORT% ...
start "%FRONTEND_TITLE%" /min "%ROOT%scripts\run_frontend.bat"

rem ---------------------------------------------------------------
rem 4. Wait until each service actually accepts connections.
rem ---------------------------------------------------------------
echo.
echo Waiting for backend ...
call :wait_for_service %BACKEND_PORT% 60 "%BACKEND_URL%"
if errorlevel 1 goto :err_backend_timeout
echo   backend ready

echo Waiting for frontend ...
call :wait_for_service %FRONTEND_PORT% 120 "%FRONTEND_URL%"
if errorlevel 1 goto :err_frontend_timeout
echo   frontend ready

rem ---------------------------------------------------------------
rem 5. Open the browser.
rem ---------------------------------------------------------------
echo.
echo Opening %APP_URL%
start "" "%APP_URL%"

echo.
echo ==========================================
echo   Finance AI is running
echo ==========================================
echo   UI        %APP_URL%
echo   API       http://127.0.0.1:%BACKEND_PORT%
echo   API docs  http://127.0.0.1:%BACKEND_PORT%/docs
echo.
echo   To stop:  double-click stop.bat
echo.
timeout /t 6 /nobreak >nul
exit /b 0


rem ===============================================================
rem Subroutines
rem ===============================================================

rem Finds the PID listening on a TCP port.
rem   %1 = port number
rem   %2 = name of the variable that receives the PID (empty if free)
rem
rem No "-p TCP" here on purpose. On Windows that flag restricts the
rem output to TCP over IPv4, which hides Vite: Node resolves the
rem default "localhost" host to ::1 and binds an IPv6 socket only.
rem Plain "netstat -ano" covers IPv4 and IPv6, and the LISTENING
rem filter keeps UDP rows out.
:get_port_pid
set "%~2="
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /C:":%~1 " ^| findstr /I "LISTENING"') do (
  if not defined %~2 set "%~2=%%p"
)
exit /b 0

rem HTTP probe. errorlevel 0 means the service answered.
rem   %1 = url
:probe_http
if not defined HAVE_CURL exit /b 1
curl.exe -s -o nul --max-time 3 "%~1"
exit /b %errorlevel%

rem Polls a service once per second until it responds.
rem   %1 = port, %2 = timeout in seconds, %3 = url to probe
rem   errorlevel 0 = ready, 1 = timed out
:wait_for_service
set /a "_left=%~2"
:wait_for_service_loop
call :probe_http %3
if not errorlevel 1 exit /b 0
call :get_port_pid %~1 _found
if defined _found exit /b 0
timeout /t 1 /nobreak >nul
set /a "_left=_left-1"
if %_left% GTR 0 goto :wait_for_service_loop
exit /b 1

rem Prints whatever is listening on a port, for diagnostics.
rem   %1 = port
:show_port
echo   Listening sockets on port %~1:
netstat -ano | findstr /C:":%~1 " | findstr /I "LISTENING"
if errorlevel 1 echo     (none)
exit /b 0


rem ===============================================================
rem Errors
rem ===============================================================

:err_no_venv
echo [ERROR] Python virtual environment not found:
echo         %ROOT%backend\.venv
echo.
echo Run setup.bat first. It creates the environment, installs
echo dependencies and applies database migrations.
goto :halt

:err_no_modules
echo [ERROR] Frontend dependencies not found:
echo         %ROOT%frontend\node_modules
echo.
echo Run setup.bat first.
goto :halt

:err_no_env
echo [ERROR] Configuration file not found:
echo         %ROOT%backend\.env
echo.
echo Copy backend\.env.example to backend\.env, or run setup.bat.
goto :halt

:err_no_scripts
echo [ERROR] Launch scripts missing from:
echo         %ROOT%scripts
echo.
echo Expected run_backend.bat and run_frontend.bat.
goto :halt

:err_port_busy
echo [ERROR] Port %BUSY_PORT% is already in use by process %BUSY_PID%:
echo.
tasklist /FI "PID eq %BUSY_PID%" /NH 2>nul
echo.
echo This usually means Finance AI is already running.
echo   - to open it:  http://localhost:%FRONTEND_PORT%
echo   - to stop it:  double-click stop.bat, then start.bat again
goto :halt

:err_backend_timeout
echo.
echo [ERROR] Backend did not answer within 60 seconds.
echo.
call :show_port %BACKEND_PORT%
echo.
echo Open the minimized window "%BACKEND_TITLE%" in the taskbar
echo to read the error. The frontend window is still running;
echo stop.bat closes everything.
goto :halt

:err_frontend_timeout
echo.
echo [ERROR] Frontend did not answer within 120 seconds.
echo.
call :show_port %FRONTEND_PORT%
echo.
echo Open the minimized window "%FRONTEND_TITLE%" in the taskbar
echo to read the error. The backend is running at
echo http://127.0.0.1:%BACKEND_PORT%
goto :halt

:halt
echo.
pause
exit /b 1
