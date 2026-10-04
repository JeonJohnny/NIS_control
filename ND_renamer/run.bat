@echo off
rem ND2Tools (nd2 rename). Needs only Python 3 with tkinter. Uses hjeon env, falls back to python on PATH
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
set "PY=C:\Users\user\anaconda3\envs\hjeon\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" -c "import tkinter" >nul 2>nul
if errorlevel 1 (
    echo Python 3 with tkinter was not found. Used: %PY%
    pause
    exit /b 1
)
"%PY%" ND2Tools.py
if errorlevel 1 pause
