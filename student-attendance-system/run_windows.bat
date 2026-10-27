@echo off
title Student Attendance System
cd /d "%~dp0"

echo ============================================
echo   Student Attendance Management System
echo ============================================
echo.

rem --- find Python (python or the py launcher) ---
set "PY="
where python >nul 2>nul && set "PY=python"
if not defined PY (where py >nul 2>nul && set "PY=py")
if not defined PY (
    echo [ERROR] Python is not installed or not in PATH.
    echo         Install it from https://www.python.org/downloads/
    echo         and tick "Add python.exe to PATH" during installation.
    echo.
    pause
    exit /b 1
)

rem --- first run: create virtual environment and install Flask ---
if not exist "venv\Scripts\python.exe" (
    echo [1/2] Creating virtual environment - first run only...
    %PY% -m venv venv
    if errorlevel 1 (
        echo [ERROR] Could not create the virtual environment.
        pause
        exit /b 1
    )
)
if not exist "venv\.installed" (
    echo [2/2] Installing Flask - first run only, needs internet...
    "venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] Installing packages failed. Check your internet connection.
        pause
        exit /b 1
    )
    echo done> "venv\.installed"
)

echo.
echo Starting the app. Your browser will open in a moment.
echo Login:  admin  /  admin123   (change the password after logging in)
echo Keep this window open while you use the app. Close it to stop.
echo.
start "" /min cmd /c "timeout /t 3 /nobreak >nul & start http://127.0.0.1:5000"
"venv\Scripts\python.exe" app.py
echo.
pause
