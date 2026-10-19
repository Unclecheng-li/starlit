@echo off
rem ============================================================
rem  One-click stop: only kills the companion + searxng python
rem  processes (by recorded PID, not taskkill /IM python.exe).
rem  Pure ASCII content on purpose. Chinese output lives in
rem  scripts\stop_all.py.
rem ============================================================
setlocal enabledelayedexpansion

set "PY="
set "STOPPER="
for /d %%D in ("%~dp0*") do (
  if exist "%%~fD\companion\.venv\Scripts\python.exe" set "PY=%%~fD\companion\.venv\Scripts\python.exe"
  if exist "%%~fD\companion\scripts\stop_all.py" set "STOPPER=%%~fD\companion\scripts\stop_all.py"
)
if not defined PY (
  echo [x] companion folder not found next to this script.
  pause
  exit /b 1
)
if not defined STOPPER (
  echo [x] scripts\stop_all.py not found.
  pause
  exit /b 1
)

"%PY%" "%STOPPER%"
