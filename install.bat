@echo off
rem Installs the Windows OCR packages used by the price check (Ctrl+Alt+P).
rem Uses the same Python as run.bat: the py launcher if there is one.
cd /d "%~dp0"
set "PY=python"
where py >nul 2>nul && set "PY=py -3"
%PY% -m pip install --upgrade -r requirements.txt || (echo. & echo Install failed. Is Python 3.9 or newer installed? Get it from https://www.python.org/downloads/ & pause & exit /b 1)
echo.
echo Done. Start the app with run.bat
pause
