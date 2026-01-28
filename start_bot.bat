@echo off
setlocal

REM === Go to folder where this .bat is located ===
cd /d "%~dp0"

REM === Create venv if not exists ===
if not exist ".venv\Scripts\python.exe" (
  echo [INFO] Creating venv...
  py -3 -m venv .venv
  if errorlevel 1 (
    echo [ERROR] Failed to create venv. Install Python 3.11+ and ensure "py" launcher exists.
    pause
    exit /b 1
  )
)

REM === Install/Update dependencies ===
echo [INFO] Installing dependencies...
".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo [ERROR] pip install failed.
  pause
  exit /b 1
)

REM === Check .env ===
if not exist ".env" (
  echo [WARN] .env not found. Creating from .env.example...
  if exist ".env.example" (
    copy /y ".env.example" ".env" >nul
    echo [INFO] Please open .env and fill BOT_TOKEN and GROUP_*_ID, then run again.
  ) else (
    echo [ERROR] .env.example not found. Create .env manually.
  )
  pause
  exit /b 1
)

REM === Run bot ===
echo [INFO] Starting bot...
".venv\Scripts\python.exe" main.py

REM If bot exits, keep console open to see the error
echo.
echo [INFO] Bot stopped.
pause
endlocal
