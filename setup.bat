@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ==========================================
echo   Finance AI - first-time setup
echo ==========================================
echo.

where py >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python launcher "py" not found.
  echo Install Python 3.11+ from https://www.python.org/downloads/
  echo and enable "Add Python to PATH" during installation.
  goto :fail
)

where npm >nul 2>nul
if errorlevel 1 (
  echo [ERROR] npm not found. Install Node.js 20+ from https://nodejs.org/
  goto :fail
)

echo [1/5] Creating Python virtual environment...
if exist "backend\.venv\Scripts\python.exe" (
  echo       already exists, keeping it
  goto :venv_ready
)

rem Pick an interpreter version that has prebuilt wheels for our
rem dependencies. "py -3" selects the newest installed Python, which
rem on a machine with 3.14 or 3.15 forces pip to compile pydantic-core
rem from Rust sources and fails. Ask for known-good versions first.
set "PY_CMD="
for %%v in (3.11 3.12 3.13) do (
  if not defined PY_CMD (
    py -%%v -c "import sys" >nul 2>&1 && set "PY_CMD=py -%%v"
  )
)
if not defined PY_CMD (
  echo       [WARNING] Python 3.11-3.13 not found, falling back to the
  echo                 newest installed version. If pip fails while
  echo                 building pydantic-core, install Python 3.11 from
  echo                 https://www.python.org/downloads/ and run this again.
  set "PY_CMD=py -3"
)
echo       using %PY_CMD%
%PY_CMD% -m venv "backend\.venv"
if errorlevel 1 goto :fail

:venv_ready
echo       interpreter version:
"backend\.venv\Scripts\python.exe" --version

echo [2/5] Installing backend dependencies...
"backend\.venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
if errorlevel 1 goto :fail
"backend\.venv\Scripts\python.exe" -m pip install -r "backend\requirements.txt" --quiet
if errorlevel 1 goto :fail

echo [3/5] Preparing configuration...
if exist "backend\.env" (
  echo       backend\.env already exists, keeping it
) else (
  copy "backend\.env.example" "backend\.env" >nul
  echo       created backend\.env
)

echo [4/5] Applying database migrations...
pushd backend
"..\backend\.venv\Scripts\python.exe" -m alembic upgrade head
if errorlevel 1 (
  popd
  goto :fail
)
popd

echo [5/5] Installing frontend dependencies...
pushd frontend
call npm install --no-audit --no-fund
if errorlevel 1 (
  popd
  goto :fail
)
popd

echo.
echo ==========================================
echo   Setup complete. Now run start.bat
echo ==========================================
pause
exit /b 0

:fail
echo.
echo Setup failed. See the message above.
pause
exit /b 1
