@echo off
REM Spectral Analysis Tool Launcher (hidden window, v2.2)
REM Uses pythonw.exe (no console window) to launch.
title Spectral Analysis Tool

cd /d "%~dp0"

REM Try to launch with pythonw (no console window); fall back to python if needed.
where pythonw >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw.exe launch_hidden.py
) else (
    start "" python launch_hidden.py
)

REM Close this launcher window immediately
exit /b 0