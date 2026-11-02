@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" call instalar.bat
".venv\Scripts\python.exe" novelavoz\setup_narrator.py
if errorlevel 1 (
  echo No se pudieron preparar las voces locales.
  pause
  exit /b 1
)
pause
