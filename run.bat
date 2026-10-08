@echo off
rem Starts Tarkov Companion without a console window ("start" lets this one close).
rem Uses the same Python as install.bat: the py launcher if there is one.
cd /d "%~dp0"
where pyw >nul 2>nul && (start "" pyw -3 -m tarkov_display %* & exit /b 0)
where pythonw >nul 2>nul && (start "" pythonw -m tarkov_display %* & exit /b 0)
echo Python wasn't found. Install Python 3.9 or newer from https://www.python.org/downloads/
echo (tick "Add python.exe to PATH" in the installer), then run install.bat.
pause
