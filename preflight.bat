@echo off
rem  Preflight check. Pure ASCII on purpose.
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
".venv\Scripts\python.exe" scripts\preflight.py
echo.
pause
