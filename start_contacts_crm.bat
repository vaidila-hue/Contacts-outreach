@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\activate.bat" (
    echo Virtual environment not found at .venv
    echo Create it with: python -m venv .venv
    echo Then install dependencies: pip install -r requirements.txt
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat
python src/run.py outreach --open

if errorlevel 1 (
    echo.
    echo Failed to start Contacts CRM.
    pause
)
