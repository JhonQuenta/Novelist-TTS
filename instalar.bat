@echo off
setlocal
cd /d "%~dp0"
if not exist "data\temp" mkdir "data\temp"
set "TEMP=%~dp0data\temp"
set "TMP=%~dp0data\temp"
python -m venv .venv
if errorlevel 1 goto failure
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failure
echo Instalacion de Novelist TTS terminada. Abre iniciar.bat.
exit /b 0
:failure
echo No se pudo instalar. Se necesita Python de 64 bits, version 3.10 o superior, e internet.
pause
exit /b 1
