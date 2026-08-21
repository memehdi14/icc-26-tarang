@echo off
TITLE TARANG Clinical Hub
echo ===================================================
echo   STARTING TARANG CLINICAL HUB (WINDOWS)
echo ===================================================

cd /d "%~dp0"
powershell -ExecutionPolicy Bypass -File "%~dp0start_all.ps1"
pause
