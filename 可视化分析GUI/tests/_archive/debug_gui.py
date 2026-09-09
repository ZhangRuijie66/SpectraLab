"""
带调试信息的GUI启动脚本
"""

import sys
import os
from pathlib import Path

print("=" * 60)
print("  GUI程序调试启动")
print("=" * 60)
print()

print(f"Python版本: {sys.version}")
print(f"当前目录: {os.getcwd()}")
print(f"脚本目录: {Path(__file__).parent}")
print()

print("检查依赖...")
try:
    import PyQt5.QtCore
    print(f"[OK] PyQt5版本: {PyQt5.QtCore.PYQT_VERSION_STR}")
except ImportError as e:
    print(f"[ERROR] PyQt5导入失败: {e}")
    sys.exit(1)

try:
    import matplotlib
    print(f"[OK] Matplotlib版本: {matplotlib.__version__}")
except ImportError as e:
    print(f"[ERROR] Matplotlib导入失败: {e}")
    sys.exit(1)

try:
    import numpy
    print(f"[OK] NumPy版本: {numpy.__version__}")
except ImportError as e:
    print(f"[ERROR] NumPy导入失败: {e}")
    sys.exit(1)

try:
    import scipy
    print(f"[OK] SciPy版本: {scipy.__version__}")
except ImportError as e:
    print(f"[ERROR] SciPy导入失败: {e}")
    sys.exit(1)

try:
    import pandas
    print(f"[OK] Pandas版本: {pandas.__version__}")
except ImportError as e:
    print(f"[ERROR] Pandas导入失败: {e}")
    sys.exit(1)

print()
print("导入GUI模块...")
try:
    # 切换到正确的目录
    script_dir = Path(__file__).parent
    os.chdir(script_dir)
    print(f"切换到目录: {script_dir}")

    # 导入GUI模块
    from absorption_gui import main
    print("[OK] GUI模块导入成功")
except Exception as e:
    print(f"[ERROR] GUI模块导入失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print()
print("启动GUI程序...")
try:
    main()
except Exception as e:
    print(f"[ERROR] GUI程序启动失败: {e}")
    import traceback
    traceback.print_exc()
    input("按回车键退出...")
    sys.exit(1)