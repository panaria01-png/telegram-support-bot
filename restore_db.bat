@echo off
setlocal

cd /d "%~dp0"

set "DB_FILE=db.sqlite3"
set "BACKUP_DIR=backups"

echo.
echo === Restore SQLite DB ===
echo DB file   : %DB_FILE%
echo Backup dir: %BACKUP_DIR%
echo.

if not exist "%BACKUP_DIR%" (
  echo [ERROR] Backup folder "%BACKUP_DIR%" not found.
  pause
  exit /b 1
)

echo Available backups:
dir /b /o:-n "%BACKUP_DIR%\db_*.sqlite3"
echo.

set /p "BKP=Enter backup filename to restore (example: db_2026-01-28_10-30-00.sqlite3): "

if "%BKP%"=="" (
  echo [ERROR] No filename entered.
  pause
  exit /b 1
)

set "SRC=%BACKUP_DIR%\%BKP%"

if not exist "%SRC%" (
  echo [ERROR] Backup file not found: %SRC%
  pause
  exit /b 1
)

echo.
echo IMPORTANT:
echo 1) Stop the bot before restore (close start_bot window / stop service).
echo 2) Current DB will be overwritten.
echo.
set /p "CONFIRM=Type YES to continue: "

if /i not "%CONFIRM%"=="YES" (
  echo [INFO] Restore cancelled.
  pause
  exit /b 0
)

REM Optional: create a safety copy of current DB before overwrite
if exist "%DB_FILE%" (
  for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd_HH-mm-ss"') do set "TS=%%i"
  copy /y "%DB_FILE%" "%BACKUP_DIR%\pre_restore_%TS%.sqlite3" >nul
)

copy /y "%SRC%" "%DB_FILE%" >nul
if errorlevel 1 (
  echo [ERROR] Restore failed.
  pause
  exit /b 1
)

echo [OK] Restored "%DB_FILE%" from "%SRC%"
pause
endlocal
