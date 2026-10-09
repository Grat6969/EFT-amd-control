@echo off
rem Starts RaidReady without a console window ("start" lets this one close).
rem Uses the Python that comes with the RaidReady-windows.zip download if it's
rem here, else the same Python as install.bat: the py launcher if there is one.
cd /d "%~dp0"
if exist "%~dp0python\pythonw.exe" (set "PYTHONHOME=" & set "PYTHONPATH=" & start "" "%~dp0python\pythonw.exe" -m tarkov_display %* & exit /b 0)
where pyw >nul 2>nul && (start "" pyw -3 -m tarkov_display %* & exit /b 0)
where pythonw >nul 2>nul && (start "" pythonw -m tarkov_display %* & exit /b 0)
echo Python wasn't found. The easy fix: download RaidReady-windows.zip, which comes
echo with its own Python, from https://github.com/Grat6969/EFT-amd-control/releases/latest
echo Or install Python 3.9 or newer from https://www.python.org/downloads/ and run install.bat.
pause
