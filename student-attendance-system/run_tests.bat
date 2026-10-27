@echo off
title Run tests
cd /d "%~dp0"
set "PY="
where python >nul 2>nul && set "PY=python"
if not defined PY (where py >nul 2>nul && set "PY=py")
if not defined PY (
    echo [ERROR] Python is not installed or not in PATH.
    pause
    exit /b 1
)
if not exist "venv\Scripts\python.exe" (
    %PY% -m venv venv
)
if not exist "venv\.installed" (
    "venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
    echo done> "venv\.installed"
)
"venv\Scripts\python.exe" -m unittest discover -s tests -v
echo.
pause
