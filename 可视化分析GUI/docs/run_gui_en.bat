@echo off
REM Absorption Spectrum Visualization Tool Launcher
REM UTF-8 encoding fix: avoid Chinese characters in batch files

echo ========================================
echo   Absorption Spectrum Visualization Tool
echo ========================================
echo.

cd /d "%~dp0"

echo [1/4] Checking Python...
python --version
if errorlevel 1 (
    echo [ERROR] Python not found
    echo Please install Python or add it to PATH
    echo.
    pause
    exit /b 1
)
echo.

echo [2/4] Checking dependencies...
python -c "import PyQt5, matplotlib, numpy, scipy, pandas" 2>nul
if errorlevel 1 (
    echo [ERROR] Missing dependencies!
    echo Please run: pip install PyQt5 matplotlib numpy scipy pandas
    echo.
    pause
    exit /b 1
)
echo [OK] Dependencies found
echo.

echo [3/4] Checking startup script...
if not exist start_gui.py (
    echo [ERROR] start_gui.py not found
    echo Current directory: %cd%
    echo.
    dir *.py
    echo.
    pause
    exit /b 1
)
echo [OK] start_gui.py found
echo.

echo [4/4] Starting GUI program...
echo TIP: If window does not appear, check taskbar or press Alt+Tab
echo TIP: This window will stay open, GUI window should open separately
echo.
echo Starting...
echo.

python start_gui.py

echo.
echo ========================================
if errorlevel 1 (
    echo [ERROR] Program exited with error code: %errorlevel%
) else (
    echo [OK] Program exited normally, code: %errorlevel%
)
echo ========================================
echo.
echo If GUI window did not appear:
echo 1. Check taskbar for "Absorption Spectrum Visualization Tool"
echo 2. Press Alt+Tab to switch windows
echo 3. Check error messages above (if any)
echo.
pause