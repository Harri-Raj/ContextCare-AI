@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" call setup.bat
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m uvicorn contextcare.api:app --host 127.0.0.1 --port 8000
