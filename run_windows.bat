@echo off
REM ============================================================
REM  Scheme Saathi - one-click run for Windows
REM  Double-click this file. It installs dependencies (first time
REM  only) and starts the app at http://localhost:8000
REM ============================================================
title Scheme Saathi
cd /d "%~dp0"

echo.
echo   ==========================================
echo    ^|  Scheme Saathi - स्कीम साथी          ^|
echo   ==========================================
echo.

REM --- find Python (tries 'py', then 'python') ---
py --version >nul 2>&1
if %errorlevel%==0 (set "PY=py") else (set "PY=python")
%PY% --version >nul 2>&1
if not %errorlevel%==0 (
    echo [ERROR] Python not found!
    echo         Install Python 3.10+ from https://python.org/downloads
    echo         IMPORTANT: tick "Add Python to PATH" while installing.
    pause
    exit /b 1
)

echo [1/3] Python found:
%PY% --version
echo.

REM --- install dependencies if not installed yet ---
%PY% -m pip show fastapi >nul 2>&1
if not %errorlevel%==0 (
    echo [2/3] Installing dependencies... (one-time, needs internet)
    %PY% -m pip install -r requirements.txt
    if not %errorlevel%==0 (
        echo [ERROR] pip install failed. Check internet connection and retry.
        pause
        exit /b 1
    )
) else (
    echo [2/3] Dependencies already installed - skipping.
)
echo.

echo [3/3] Starting Scheme Saathi...
echo.
echo       App will open at  ^>^>  http://localhost:8000
echo       Type a doubt like "BPL kya hai?" in chat anytime!
echo.
start "" http://localhost:8000
echo       Press CTRL+C to stop the server.
%PY% run.py
pause
