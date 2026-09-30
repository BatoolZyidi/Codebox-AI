@echo off
cd /d "%~dp0"
python -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
if not exist .env copy .env.example .env
echo.
echo Setup finished. Next:
echo   1. Open .env in Notepad and paste your ASSEMBLYAI_API_KEY and GEMINI_API_KEY
echo   2. run.bat check
echo   3. run.bat run "C:\path\to\your\project"
