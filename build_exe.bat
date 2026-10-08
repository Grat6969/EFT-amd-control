@echo off
rem Builds a standalone TarkovDisplay.exe in the dist folder.
cd /d "%~dp0"
python -m pip install --upgrade pyinstaller -r requirements.txt || exit /b 1
python -m PyInstaller --noconfirm --onefile --windowed --name TarkovDisplay --collect-all winrt launcher.py
