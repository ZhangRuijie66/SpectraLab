@echo off
REM 吸收光谱可视化分析工具启动脚本（调试版 - 保持窗口打开）
chcp 65001 >nul
title 吸收光谱可视化分析工具 - 调试模式

echo ========================================
echo   吸收光谱可视化分析工具 (调试版)
echo ========================================
echo.

cd /d "%~dp0"

echo 当前目录: %cd%
echo.

echo [1/4] 检查Python...
python --version
if errorlevel 1 (
    echo [错误] Python未安装或不在PATH中
    echo.
    pause
    exit /b 1
)
echo.

echo [2/4] 检查依赖...
python -c "import PyQt5, matplotlib, numpy, scipy, pandas" 2>nul
if errorlevel 1 (
    echo [错误] 缺少必要的依赖库！
    echo 请运行以下命令安装:
    echo   pip install PyQt5 matplotlib numpy scipy pandas
    echo.
    pause
    exit /b 1
)
echo [OK] 依赖检查通过
echo.

echo [3/4] 检查启动脚本...
if not exist start_gui.py (
    echo [错误] 找不到 start_gui.py
    echo 当前目录: %cd%
    echo.
    dir *.py
    echo.
    pause
    exit /b 1
)
echo [OK] 找到 start_gui.py
echo.

echo [4/4] 启动GUI程序...
echo 提示：如果窗口没有立即出现，请检查任务栏或按Alt+Tab
echo 提示：此窗口将保持打开，GUI窗口应该在另一个窗口中打开
echo.
echo 正在启动...
echo.

python start_gui.py

echo.
echo ========================================
if errorlevel 1 (
    echo [错误] 程序异常退出，错误代码: %errorlevel%
) else (
    echo [OK] 程序正常退出，错误代码: %errorlevel%
)
echo ========================================
echo.
echo 如果GUI窗口没有出现，请：
echo 1. 查看任务栏是否有"吸收光谱可视化分析工具 v1.0"
echo 2. 按Alt+Tab切换窗口
echo 3. 查看上方的错误信息（如果有）
echo.
pause