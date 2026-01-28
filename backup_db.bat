@echo off
setlocal

cd /d "%~dp0"

set "DB_FILE=db.sqlite3"
set "BACKUP_DIR=backups"

if not exist "%DB_FILE%" (
  echo [ERROR] Database file "%DB_FILE%" not found in: %CD%
  pause
  exit /b 1
)

if not exist "%BACKUP_DIR%" (
  mkdir "%BACKUP_DIR%"
)

REM === Build timestamp YYYY-MM-DD_HH-MM-SS (locale-independent via PowerShell) ===
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd_HH-mm-ss"') do set "TS=%%i"

set "BACKUP_FILE=%BACKUP_DIR%\db_%TS%.sqlite3"

copy /y "%DB_FILE%" "%BACKUP_FILE%" >nul
if errorlevel 1 (
  echo [ERROR] Backup failed.
  pause
  exit /b 1
)

echo [OK] Backup created: %BACKUP_FILE%
pause
endlocal
