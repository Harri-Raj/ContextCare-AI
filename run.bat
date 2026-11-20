@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" call setup.bat
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m streamlit run app.py --server.headless true
if errorlevel 1 pause
