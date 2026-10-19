@echo off
rem ============================================================
rem  Start NapCat (needs Administrator to inject into QQ)
rem  Pure ASCII on purpose - see start_companion.bat header.
rem ============================================================
setlocal enabledelayedexpansion
set "SHELL="
for /d %%D in ("%~dp0napcat\NapCat.*.Shell") do set "SHELL=%%~fD"
if not defined SHELL (
  echo [x] NapCat not found under napcat\NapCat.*.Shell
  pause
  exit /b 1
)

net session >nul 2>&1
if errorlevel 1 (
  echo [*] Administrator rights required. Requesting elevation...
  powershell -NoProfile -Command "Start-Process -Verb RunAs -FilePath '%~f0'"
  exit /b
)

cd /d "%SHELL%"
echo [*] Starting NapCat from %CD%
echo [*] First run: a QR code will appear. Scan it with the BOT's QQ account.
echo     Use a SECONDARY account, never your main one.
echo.
call napcat.bat
pause
