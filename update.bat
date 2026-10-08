@echo off
rem Downloads the latest Tarkov Display from GitHub. Settings are kept.
rem Kept on one line: this file can be replaced by the update while it runs.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0update.ps1" & pause & exit /b
