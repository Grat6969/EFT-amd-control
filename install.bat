@echo off
rem Installs the Windows OCR packages used by the price check (Ctrl+Alt+P).
rem Not needed with the RaidReady-windows.zip download: its Python has them.
rem Uses the same Python as run.bat.
cd /d "%~dp0"
set "PY=python"
where py >nul 2>nul && set "PY=py -3"
if exist "%~dp0python\python.exe" set PY="%~dp0python\python.exe"
%PY% -m pip install --upgrade -r requirements.txt || (echo. & echo Install failed. Is Python 3.9 or newer installed? Get it from https://www.python.org/downloads/ & pause & exit /b 1)
echo.
echo Done. Start the app with run.bat
pause
