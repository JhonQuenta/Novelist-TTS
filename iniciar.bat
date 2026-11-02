@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" call instalar.bat
if not exist ".venv\Scripts\python.exe" exit /b 1
".venv\Scripts\python.exe" app.py
if errorlevel 1 pause
