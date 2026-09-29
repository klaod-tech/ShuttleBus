@echo off
cd /d "%~dp0"
python --version >nul 2>&1
if errorlevel 1 goto usepy
python launch.py --stop
goto done
:usepy
py -3 launch.py --stop
:done
timeout /t 3 >nul
