@echo off
rem Builds a standalone TarkovCompanion.exe in the dist folder.
cd /d "%~dp0"
python -m pip install --upgrade pyinstaller -r requirements.txt || exit /b 1
python -m PyInstaller --noconfirm --onefile --windowed --name TarkovCompanion --collect-all winrt ^
  --add-data "tarkov_display/web;tarkov_display/web" launcher.py
