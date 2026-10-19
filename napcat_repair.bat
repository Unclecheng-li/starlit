@echo off
rem ============================================================
rem  NapCat auto-repair, run by scheduled task
rem  "Vol_NapCat_AutoRepair" at HIGHEST privilege (no UAC).
rem
rem  Why this exists: NTQQ silently recycles its process tree
rem  at night; NapCat is injected INTO the QQ process, so it
rem  dies with the old one and NEVER reconnects (the new QQ
rem  has no injection). The companion watchdog detects the
rem  dead channel and triggers this task.
rem
rem  Steps:
rem    1. Kill stale QQ.exe / NapCatWinBootMain.exe whose exe
rem       path is under vol\napcat (NEVER touches the user's
rem       own QQ client installed elsewhere).
rem    2. Pop the QR login window (async; waits up to 10 min
rem       for a code to appear, self-closes after login).
rem    3. Relaunch NapCat in this window (already elevated).
rem
rem  Pure ASCII on purpose (cmd.exe garbles UTF-8 .bat files).
rem ============================================================
setlocal enabledelayedexpansion

set "LOG=%~dp0napcat_repair_log.txt"
echo ===== %date% %time% auto-repair start ===== >> "%LOG%"

rem ---- 1) kill stale napcat-scoped processes (path-filtered) ----
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { ($_.Name -eq 'QQ.exe' -or $_.Name -eq 'NapCatWinBootMain.exe') -and ($_.ExecutablePath -like '%~dp0napcat*') } | ForEach-Object { Write-Host ('kill ' + $_.ProcessId); Stop-Process -Id $_.ProcessId -Force }" >> "%LOG%" 2>&1

timeout /t 3 /nobreak >nul

rem ---- 2) QR window first (async, self-closes on login) ----
set "PY="
set "SHOW="
for /d %%D in ("%~dp0*") do (
  if exist "%%~fD\companion\.venv\Scripts\python.exe" set "PY=%%~fD\companion\.venv\Scripts\python.exe"
  if exist "%%~fD\companion\scripts\show_qr.py" set "SHOW=%%~fD\companion\scripts\show_qr.py"
)
if defined PY if defined SHOW (
  start "" "%PY%" "%SHOW%" --wait 600
)

rem ---- 3) relaunch NapCat (elevated context, no UAC prompt) ----
cd /d "%~dp0"
call start_napcat.bat
echo ===== %date% %time% auto-repair done ===== >> "%LOG%"
