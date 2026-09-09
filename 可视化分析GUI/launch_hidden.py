"""
无窗口启动入口（供 pythonw 使用，无 print，避免无 stdout 时报错）
"""
import sys
import os
from pathlib import Path

# 确保能导入同目录模块
script_dir = Path(__file__).resolve().parent
if str(script_dir) not in sys.path:
    sys.path.insert(0, str(script_dir))
_parent = script_dir.parent
if str(_parent) not in sys.path:
    sys.path.insert(0, str(_parent))

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt
from absorption_gui import AbsorptionGUI
from gui_config import APP_VERSION, UI_FONT_FAMILY

QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
app = QApplication(sys.argv)
app.setApplicationName("光谱可视化分析工具")
app.setStyle('Fusion')
# 全局字体：按平台自动选择（Windows 微软雅黑 / macOS 苹方）
_font = app.font()
_font.setFamily(UI_FONT_FAMILY)
app.setFont(_font)
window = AbsorptionGUI()
window.setWindowTitle(f"光谱可视化分析工具 v{APP_VERSION}")
window.setWindowFlags(window.windowFlags() | Qt.WindowStaysOnTopHint)
window.showMaximized()  # 最大化打开，让图片预览区占满屏幕
window.raise_()
window.activateWindow()
sys.exit(app.exec_())