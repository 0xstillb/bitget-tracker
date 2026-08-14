@echo off
setlocal
cd /d "%~dp0"

echo.
echo  Bitget Tracker ESP32 Wi-Fi Provisioning
echo  ----------------------------------------
echo.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0provision-wifi.ps1" %*
set "exitCode=%ERRORLEVEL%"

echo.
if not "%exitCode%"=="0" echo Provisioning failed. Read the message above.
if "%exitCode%"=="0" echo Provisioning finished. The ESP32 will restart and connect to Wi-Fi.
pause
exit /b %exitCode%
