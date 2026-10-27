@echo off
title Reset to sample data
cd /d "%~dp0"
echo This will DELETE all current students and attendance
echo and replace them with the sample data.
echo.
set /p CONFIRM=Type YES and press Enter to continue: 
if /i not "%CONFIRM%"=="YES" (
    echo Cancelled.
    pause
    exit /b 0
)
set "PY="
where python >nul 2>nul && set "PY=python"
if not defined PY (where py >nul 2>nul && set "PY=py")
if not defined PY (
    echo [ERROR] Python is not installed or not in PATH.
    pause
    exit /b 1
)
if exist "venv\Scripts\python.exe" (
    "venv\Scripts\python.exe" scripts\generate_sample_data.py --reset
) else (
    %PY% scripts\generate_sample_data.py --reset
)
echo.
pause
