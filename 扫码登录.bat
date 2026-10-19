@echo off
rem ============================================================
rem  Show the QQ login QR code in a window that auto-refreshes
rem  and closes itself once login is confirmed.
rem
rem  Use when: the QR expired and the launcher's window got
rem  closed, or NapCat was started on its own.
rem
rem  Pure ASCII content on purpose. Logic + Chinese output live
rem  in scripts\show_qr.py / scripts\qr_login.py.
rem ============================================================
setlocal enabledelayedexpansion

set "PY="
set "SHOW="
for /d %%D in ("%~dp0*") do (
  if exist "%%~fD\companion\.venv\Scripts\python.exe" set "PY=%%~fD\companion\.venv\Scripts\python.exe"
  if exist "%%~fD\companion\scripts\show_qr.py" set "SHOW=%%~fD\companion\scripts\show_qr.py"
)
if not defined PY (
  echo [x] companion folder not found next to this script.
  pause
  exit /b 1
)
if not defined SHOW (
  echo [x] scripts\show_qr.py not found.
  pause
  exit /b 1
)

"%PY%" "%SHOW%"
echo.
pause
