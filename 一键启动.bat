@echo off
rem ============================================================
rem  One-click start: search -> companion -> QQ channel
rem  Pure ASCII content on purpose (cmd.exe garbles non-ASCII
rem  .bat files written as UTF-8). All Chinese output and the
rem  actual logic live in scripts\launch_all.py.
rem ============================================================
setlocal enabledelayedexpansion

set "PY="
set "LAUNCH="
for /d %%D in ("%~dp0*") do (
  if exist "%%~fD\companion\.venv\Scripts\python.exe" set "PY=%%~fD\companion\.venv\Scripts\python.exe"
  if exist "%%~fD\companion\scripts\launch_all.py" set "LAUNCH=%%~fD\companion\scripts\launch_all.py"
)
if not defined PY (
  echo [x] companion folder not found next to this script.
  pause
  exit /b 1
)
if not defined LAUNCH (
  echo [x] scripts\launch_all.py not found.
  pause
  exit /b 1
)

"%PY%" "%LAUNCH%"
