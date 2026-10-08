@echo off
rem Builds a standalone TarkovDisplay.exe in the dist folder.
cd /d "%~dp0"
python -m pip install --upgrade pyinstaller || exit /b 1
python -m PyInstaller --noconfirm --onefile --windowed --name TarkovDisplay launcher.py
