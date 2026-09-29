@echo off
rem ShuttleBus work board (scripts\board). Plan: md\PLAN-project-board.md
cd /d "%~dp0scripts\board"
python --version >nul 2>&1
if errorlevel 1 goto usepy
python launch.py %*
if errorlevel 1 pause
exit /b
:usepy
py -3 launch.py %*
if errorlevel 1 pause
