@echo off
rem ============================================================
rem  One-time setup: register the NapCat auto-repair task.
rem
rem  Creates scheduled task "Vol_NapCat_AutoRepair" that runs
rem  napcat_repair.bat at HIGHEST privilege. The companion's
rem  channel watchdog triggers it with plain `schtasks /Run`
rem  (no UAC popup) whenever NapCat dies and stops reconnecting.
rem
rem  Run this ONCE. Needs one UAC confirmation, then it's
rem  fully unattended forever.
rem
rem  Pure ASCII on purpose.
rem ============================================================
setlocal

net session >nul 2>&1
if errorlevel 1 (
  echo [*] Administrator rights required. Requesting elevation...
  powershell -NoProfile -Command "Start-Process -Verb RunAs -FilePath '%~f0'"
  exit /b
)

schtasks /Create /TN "Vol_NapCat_AutoRepair" /TR "\"%~dp0napcat_repair.bat\"" /SC ONCE /ST 00:00 /SD 2020/01/01 /RL HIGHEST /F
echo.
schtasks /Query /TN "Vol_NapCat_AutoRepair"
echo.
echo [*] Done. NapCat now self-heals after silent deaths.
echo     The companion watchdog triggers the repair automatically.
pause
