@echo off
rem Builds dist\DivoomHub\DivoomHub.exe
cd /d "%~dp0"

if not exist .venv\Scripts\python.exe py -3.13 -m venv .venv || goto :error
.venv\Scripts\python -m pip install -q -r requirements.txt "pyinstaller>=6.10" || goto :error
.venv\Scripts\python -m pytest -q || goto :error
.venv\Scripts\python tools\make_icon.py || goto :error

rem Never terminate the user's active app to replace its files.
powershell -NoProfile -Command "if (Get-Process DivoomHub,DitooSpotify -ErrorAction SilentlyContinue) { Write-Host 'Exit Divoom Hub from the tray before rebuilding'; exit 1 }" || goto :error

.venv\Scripts\pyinstaller --noconfirm --clean DivoomHub.spec || goto :error
echo.
echo Built: %~dp0dist\DivoomHub\DivoomHub.exe
exit /b 0

:error
echo Build FAILED
exit /b 1
