@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" call instalar.bat
if not exist ".venv\Scripts\python.exe" exit /b 1
".venv\Scripts\python.exe" novelavoz\setup_supertonic.py
if errorlevel 1 (
  echo No se pudo preparar Supertonic.
  pause
  exit /b 1
)
pause
