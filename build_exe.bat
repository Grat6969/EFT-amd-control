@echo off
rem Builds a standalone RaidReady.exe in the dist folder.
cd /d "%~dp0"
set "PY=python"
where py >nul 2>nul && set "PY=py -3"
%PY% -m pip install --upgrade pyinstaller -r requirements.txt || exit /b 1
%PY% -m PyInstaller --noconfirm --onefile --windowed --name RaidReady --collect-all winrt ^
  --add-data "tarkov_display/web;tarkov_display/web" launcher.py
