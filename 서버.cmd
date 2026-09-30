@echo off
rem ShuttleBus local run: DB, API, web in one go. Usage: start (default) / stop / status
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run-local.ps1" %*
if errorlevel 1 pause
exit /b
