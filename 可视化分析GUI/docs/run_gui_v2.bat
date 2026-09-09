@echo off
REM 吸收光谱可视化分析工具启动脚本（改进版）
chcp 65001 >nul
echo ========================================
echo   吸收光谱可视化分析工具
echo ========================================
echo.

cd /d "%~dp0"

echo [1/3] 检查依赖...
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

echo [2/3] 启动GUI程序...
echo 提示：如果窗口没有出现，请检查任务栏或按Alt+Tab
echo.
echo 启动中...

python start_gui.py

if errorlevel 1 (
    echo.
    echo [错误] 程序异常退出
    echo.
    pause
    exit /b 1
)

echo.
echo [OK] 程序正常退出
echo.
pause