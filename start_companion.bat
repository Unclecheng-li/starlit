@echo off
rem ============================================================
rem  Start the AI companion (QQ channel mode)
rem  Pure ASCII on purpose: cmd.exe garbles non-ASCII .bat files
rem  written as UTF-8, so we locate the Chinese-named folder by
rem  pattern instead of hardcoding it.
rem ============================================================
setlocal enabledelayedexpansion
set "APP="
for /d %%D in ("%~dp0*") do (
  if exist "%%~fD\companion\.venv\Scripts\python.exe" set "APP=%%~fD\companion"
)
if not defined APP (
  echo [x] companion folder not found next to this script.
  pause
  exit /b 1
)
cd /d "%APP%"
echo [*] Starting companion from %CD%
echo.
".venv\Scripts\python.exe" -m app.main
echo.
echo [*] companion exited.
pause
