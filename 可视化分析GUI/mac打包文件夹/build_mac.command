#!/bin/bash
# ============================================================
#  Spectral Analysis Tool (QLS Lab) - macOS portable .app build
#
#  Version 4.6 - builds the FULL app (absorption / emission /
#  lifetime modes, launcher, xlsx sample info).
#
#  This script is intentionally ASCII/English only, and forces
#  a UTF-8 locale, so it can NEVER be corrupted by a non-UTF-8
#  terminal (which previously showed Chinese as "?" and broke).
#
#  Run it on macOS.  Either:
#    - double-click this .command in Finder,  or
#    - in Terminal:  bash build_mac.command
# ============================================================
set -e
cd "$(dirname "$0")"

# Force UTF-8 for this shell and for Python (handles any non-ASCII path)
export LANG=en_US.UTF-8
export LC_ALL=en_US.UTF-8
export LC_CTYPE=en_US.UTF-8
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

APP_DIR="$(pwd)"
PY="python3"

echo "============================================================"
echo " Building the macOS portable app (Spectral Analysis Tool)"
echo " Version 4.6 (absorption / emission / lifetime)"
echo " Directory: $APP_DIR"
echo "============================================================"

# ---- [1/5] virtualenv ----
if [ ! -d ".venv_mac" ]; then
  echo "[1/5] Creating virtualenv .venv_mac ..."
  "$PY" -m venv .venv_mac
fi
source .venv_mac/bin/activate

# ---- [2/5] dependencies ----
# NOTE: openpyxl is REQUIRED (pandas reads the sample-info
# xlsx files with the openpyxl engine).
echo "[2/5] Installing dependencies (PyQt5 matplotlib scipy pandas numpy openpyxl pyinstaller) ..."
python -m pip install --upgrade pip
python -m pip install PyQt5 matplotlib scipy pandas numpy openpyxl pyinstaller

# ---- [3/5] app icon (.icns) ----
# PyInstaller on macOS needs an .icns icon; convert our PNG with
# the built-in sips tool.  If it fails we simply build without one.
ICON_ARG=""
if [ -f "app_icon.icns" ] || [ -f "app_icon.png" ]; then
  echo "[3/5] Preparing app_icon.icns ..."
  if [ ! -f "app_icon.icns" ] && [ -f "app_icon.png" ]; then
    sips -s format icns app_icon.png --out app_icon.icns >/dev/null 2>&1 || true
  fi
  if [ -f "app_icon.icns" ]; then
    ICON_ARG="--icon $APP_DIR/app_icon.icns"
  fi
fi
echo "      icon: ${ICON_ARG:-none}"

# ---- [4/5] PyInstaller (windowed + onedir => .app for this machine) ----
echo "[4/5] Running PyInstaller ..."
echo "      For an Intel+ARM universal build, add  --target-architecture universal2"
rm -rf build_mac dist_mac spec_mac
# shellcheck disable=SC2086
python -m PyInstaller --noconfirm --clean --windowed --onedir \
  --name "SpectralAnalysisTool" \
  --osx-bundle-identifier "com.qlslab.spectral-analysis" \
  $ICON_ARG \
  --paths "$APP_DIR" \
  --add-data "$APP_DIR/app_icon.ico:." \
  --add-data "$APP_DIR/splash.png:." \
  --add-data "$APP_DIR/icons:icons" \
  --hidden-import plot_absorption \
  --hidden-import plot_emission \
  --hidden-import plot_lifetime \
  --hidden-import plot_3d_scan \
  --hidden-import read_xlsx_info \
  --hidden-import curve_colors \
  --hidden-import openpyxl \
  --hidden-import absorption_gui \
  --hidden-import entry_gui \
  --hidden-import gui_launcher \
  --hidden-import gui_splash \
  --hidden-import gui_config \
  --hidden-import gui_components \
  --hidden-import gui_log \
  --hidden-import gui_ui \
  --hidden-import gui_data \
  --hidden-import gui_plot \
  --hidden-import matplotlib.backends.backend_qt5agg \
  --hidden-import matplotlib.backends.backend_qtagg \
  --exclude-module torch --exclude-module torchvision --exclude-module tensorflow \
  --exclude-module sympy --exclude-module IPython --exclude-module jedi \
  --exclude-module lxml --exclude-module zmq \
  --exclude-module rich --exclude-module notebook --exclude-module ipykernel \
  --exclude-module nbconvert --exclude-module nbformat --exclude-module jupyter_core \
  --exclude-module prompt_toolkit --exclude-module matplotlib_inline --exclude-module ipython_genutils \
  --exclude-module tkinter \
  --exclude-module matplotlib.backends.backend_tkagg \
  --exclude-module matplotlib.backends._tkagg \
  --exclude-module matplotlib.backends.backend_tk \
  --workpath build_mac --distpath dist_mac --specpath spec_mac \
  "$APP_DIR/absorption_gui.py"

# ---- [5/5] place the .app into ./portable_mac ----
echo "[5/5] Moving the .app to ./portable_mac ..."
mkdir -p portable_mac
rm -rf portable_mac/SpectralAnalysisTool.app
cp -Rf dist_mac/SpectralAnalysisTool.app portable_mac/SpectralAnalysisTool.app

# Ad-hoc signature: required on Apple Silicon so the app is not
# reported as "damaged"; harmless on Intel.
codesign --force --deep -s - portable_mac/SpectralAnalysisTool.app 2>/dev/null || true

# best-effort: drop quarantine flag (only matters if the build was quarantined)
xattr -dr com.apple.quarantine portable_mac/SpectralAnalysisTool.app 2>/dev/null || true

echo ""
echo "[DONE] Build finished."
echo "  App bundle : $APP_DIR/portable_mac/SpectralAnalysisTool.app"
echo "  Copy the whole 'SpectralAnalysisTool.app' to any Mac (same architecture) to use it."
echo "  Tip: rename the .app in Finder if you want a different (e.g. Chinese) name."
