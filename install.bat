@echo off
rem Installs the Windows OCR packages used by the price check (Ctrl+Alt+P).
cd /d "%~dp0"
python -m pip install --upgrade -r requirements.txt || (echo. & echo Install failed. Is Python installed and on PATH? & pause & exit /b 1)
echo.
echo Done. Start the app with run.bat
pause
