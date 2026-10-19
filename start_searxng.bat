@echo off
rem ============================================================
rem  Start SearXNG (the local metasearch instance vol uses)
rem  Pure ASCII on purpose - see start_companion.bat header.
rem
rem  The real work is in scripts\run_searxng.py, which sets
rem  CURL_CA_BUNDLE / SEARXNG_SETTINGS_PATH and records the PID.
rem ============================================================
setlocal enabledelayedexpansion

set "PY="
set "RUNNER="
for /d %%D in ("%~dp0*") do (
  if exist "%%~fD\companion\.venv\Scripts\python.exe" set "PY=%%~fD\companion\.venv\Scripts\python.exe"
  if exist "%%~fD\companion\scripts\run_searxng.py" set "RUNNER=%%~fD\companion\scripts\run_searxng.py"
)
if not defined PY (
  echo [x] python venv not found next to this script.
  pause
  exit /b 1
)
if not defined RUNNER (
  echo [x] scripts\run_searxng.py not found.
  pause
  exit /b 1
)

echo [*] Starting SearXNG on http://127.0.0.1:8888
echo [*] Keep this window open. vol needs it to search the web.
echo.
"%PY%" "%RUNNER%"
echo.
echo [*] SearXNG exited.
pause
