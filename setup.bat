@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
 py -3.11 -m venv .venv 2>nul
 if errorlevel 1 py -3 -m venv .venv
 if errorlevel 1 (echo Please install Python 3.11 or newer from python.org & pause & exit /b 1)
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (echo Dependency installation failed. Check internet access. & pause & exit /b 1)
".venv\Scripts\python.exe" scripts\train.py
if errorlevel 1 (echo Training failed. & pause & exit /b 1)
echo Setup complete.
