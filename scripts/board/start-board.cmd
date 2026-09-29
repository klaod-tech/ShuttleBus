@echo off
cd /d "%~dp0"
python --version >nul 2>&1
if errorlevel 1 goto usepy
python launch.py %*
if errorlevel 1 pause
exit /b
:usepy
py -3 launch.py %*
if errorlevel 1 pause
