@echo off
set "START_DIR=%CD%"
cd /d "%~dp0"
call .venv\Scripts\activate.bat
set "CMD=%~1"
set "REPO=%~2"
if "%CMD%"=="" set "CMD=run"
if /I "%CMD%"=="run" goto dispatch
if /I "%CMD%"=="chat" goto dispatch
if /I "%CMD%"=="check" goto dispatch
if /I "%CMD%"=="devices" goto dispatch
if /I "%CMD%"=="index" goto dispatch
set "REPO=%~1"
set "CMD=run"
:dispatch
if "%REPO%"=="" set "REPO=%START_DIR%"
python -m codebox %CMD% --repo "%REPO%"
