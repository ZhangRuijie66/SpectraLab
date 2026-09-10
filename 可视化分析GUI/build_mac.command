#!/bin/bash
# ============================================================================
# 光谱可视化分析工具 —— macOS 打包脚本
# ----------------------------------------------------------------------------
# 用法：双击本文件（Finder 里会打开终端自动执行），或在终端里
#       chmod +x build_mac.command && ./build_mac.command
#
# 打包出一个**独立**的 .app：目标机器不需要装 Python / 任何库。
#
# 与 Windows 的 打包便携版.ps1 是同一套参数，平台差异只有两处：
#   1) --add-data 的分隔符：macOS 用「:」（Windows 用「;」）
#   2) 图标：macOS 要 .icns（本脚本用 Pillow + iconutil 从 app_icon.ico 转）
#
# 首次运行会建虚拟环境并装依赖（约 3–5 分钟）；之后重跑只做打包（约 2 分钟）。
# 产物：
#   dist-mac/光谱可视化分析工具.app      双击运行（推荐）
#   dist-mac/光谱可视化分析工具          命令行可执行文件
# ============================================================================
set -euo pipefail
cd "$(dirname "$0")"

APP_NAME="SpectralAnalysisTool"        # 内部名（英文：打包工具对中文名支持不稳）
OUT_NAME="光谱可视化分析工具"            # 对外显示名
VENV=".venv-mac"
BUILD="_packaging_mac"
DIST="$BUILD/dist"
PY="${PYTHON:-python3}"

echo "============================================================"
echo "  光谱可视化分析工具 —— macOS 打包"
echo "  工作目录: $(pwd)"
echo "============================================================"

# ---------------------------------------------------------------- 1. 环境
if ! command -v "$PY" >/dev/null 2>&1; then
    echo "[失败] 找不到 $PY。请先安装 Python 3.11+：https://www.python.org/downloads/"
    echo "       或先 export PYTHON=/path/to/python3 再运行本脚本。"
    exit 1
fi
"$PY" - <<'PYCHK'
import sys
if sys.version_info < (3, 10):
    sys.exit("需要 Python 3.10 以上（当前 %d.%d）" % sys.version_info[:2])
print("Python:", sys.version.split()[0])
PYCHK

if [ ! -d "$VENV" ]; then
    echo "--- 建虚拟环境 $VENV ---"
    "$PY" -m venv "$VENV"
fi
VPY="$VENV/bin/python"
"$VPY" -m pip install --upgrade pip >/dev/null

echo "--- 安装依赖（PyQt5 / numpy / scipy / pandas / matplotlib / openpyxl / pyinstaller）---"
"$VPY" -m pip install -r requirements.txt
"$VPY" -m pip install --upgrade pyinstaller pillow

# ---------------------------------------------------------------- 2. 图标
# macOS 只认 .icns。用 Pillow 把 .ico 转成 iconset，再用系统自带的 iconutil 打包。
ICON_ARG=()
if [ -f app_icon.ico ] && command -v iconutil >/dev/null 2>&1; then
    echo "--- 生成 app_icon.icns ---"
    if "$VPY" - <<'PYICON'
from pathlib import Path
from PIL import Image
src = Image.open("app_icon.ico")
try:                                   # .ico 里通常有多档，取最大那档做源图
    src.size = max(src.info.get("sizes", {src.size}))
except Exception:
    pass
src = src.convert("RGBA")
out = Path("app_icon.iconset")
out.mkdir(exist_ok=True)
for size, name in ((16, "icon_16x16.png"), (32, "icon_16x16@2x.png"),
                   (32, "icon_32x32.png"), (64, "icon_32x32@2x.png"),
                   (128, "icon_128x128.png"), (256, "icon_128x128@2x.png"),
                   (256, "icon_256x256.png"), (512, "icon_256x256@2x.png"),
                   (512, "icon_512x512.png"), (1024, "icon_512x512@2x.png")):
    src.resize((size, size), Image.LANCZOS).save(out / name)
print("iconset ok")
PYICON
    then
        iconutil -c icns app_icon.iconset -o app_icon.icns && ICON_ARG=(--icon app_icon.icns)
    else
        echo "[提示] 图标转换失败，本次不带图标打包（不影响功能）"
    fi
else
    echo "[提示] 没有 app_icon.ico 或没有 iconutil，跳过图标"
fi

# ---------------------------------------------------------------- 3. 打包
# --exclude-module：砍掉 PyQt5 里用不到的子模块与各库自带的测试包，体积减不少
EXCLUDES=(
    PyQt5.QtWebEngineWidgets PyQt5.QtWebEngineCore PyQt5.QtWebEngine
    PyQt5.QtWebChannel PyQt5.QtWebSockets PyQt5.QtQuick PyQt5.QtQuickWidgets
    PyQt5.QtQml PyQt5.QtMultimedia PyQt5.QtMultimediaWidgets PyQt5.QtBluetooth
    PyQt5.QtNfc PyQt5.QtPositioning PyQt5.QtLocation PyQt5.QtSensors
    PyQt5.QtSerialPort PyQt5.QtSql PyQt5.QtTest PyQt5.QtXmlPatterns
    PyQt5.QtHelp PyQt5.QtDesigner PyQt5.QtOpenGL PyQt5.QtDBus
    PyQt5.QtNetworkAuth PyQt5.QtRemoteObjects PyQt5.QtScript
    PyQt5.QtScriptTools PyQt5.QtTextToSpeech PyQt5.QtXml
    PyQt5.Qt3DCore PyQt5.Qt3DRender PyQt5.Qt3DInput PyQt5.Qt3DLogic
    PyQt5.Qt3DAnimation PyQt5.Qt3DExtras
    pytest matplotlib.tests numpy.tests pandas.tests scipy.tests
    tkinter torch rich IPython notebook jupyter
)
EXCLUDE_ARGS=()
for m in "${EXCLUDES[@]}"; do EXCLUDE_ARGS+=(--exclude-module "$m"); done

echo "--- PyInstaller 打包中（约 2 分钟）---"
"$VPY" -m PyInstaller \
    --noconfirm --clean --onefile --windowed \
    --name "$APP_NAME" \
    --optimize 2 \
    --paths . \
    "${ICON_ARG[@]+"${ICON_ARG[@]}"}" \
    --add-data "app_icon.ico:." \
    --add-data "icons:icons" \
    --splash splash.png \
    --splash-center primary \
    --hidden-import plot_absorption \
    --hidden-import curve_colors \
    --hidden-import plot_emission \
    --hidden-import plot_lifetime \
    --hidden-import plot_3d_scan \
    --hidden-import read_xlsx_info \
    --hidden-import openpyxl \
    --hidden-import absorption_gui \
    --hidden-import gui_launcher \
    --hidden-import gui_splash \
    --hidden-import gui_config \
    --hidden-import gui_components \
    --hidden-import gui_ui \
    --hidden-import gui_data \
    --hidden-import gui_plot \
    --hidden-import gui_help \
    --hidden-import gui_icons \
    --hidden-import gui_log \
    --hidden-import matplotlib.backends.backend_qt5agg \
    --hidden-import matplotlib.backends.backend_qtagg \
    "${EXCLUDE_ARGS[@]}" \
    --workpath "$BUILD/build" \
    --distpath "$DIST" \
    --specpath "$BUILD" \
    entry_gui.py

# ---------------------------------------------------------------- 4. 产物
mkdir -p dist-mac
if [ -d "$DIST/$APP_NAME.app" ]; then
    rm -rf "dist-mac/$OUT_NAME.app"
    cp -R "$DIST/$APP_NAME.app" "dist-mac/$OUT_NAME.app"
fi
if [ -f "$DIST/$APP_NAME" ]; then
    cp -f "$DIST/$APP_NAME" "dist-mac/$OUT_NAME"
    chmod +x "dist-mac/$OUT_NAME"
fi

echo ""
echo "[完成] 打包成功！"
if [ -d "dist-mac/$OUT_NAME.app" ]; then
    echo "  应用：dist-mac/$OUT_NAME.app      （双击运行）"
fi
if [ -f "dist-mac/$OUT_NAME" ]; then
    echo "  可执行：dist-mac/$OUT_NAME        （命令行运行）"
fi
echo ""
echo "  首次启动会解压到临时目录，慢 20–30 秒属正常。"
echo "  如果 macOS 提示「已损坏 / 无法验证开发者」（从网盘或 U 盘拷过来的文件会被打上隔离标记），"
echo "  在终端里执行一次即可：  xattr -dr com.apple.quarantine \"dist-mac/$OUT_NAME.app\""
echo ""
