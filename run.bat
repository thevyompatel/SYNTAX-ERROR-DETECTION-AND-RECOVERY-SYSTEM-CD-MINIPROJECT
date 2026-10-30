@echo off
cd /d "%~dp0"
python main.py %*
if errorlevel 9009 echo Python is not installed or not on PATH. & pause
