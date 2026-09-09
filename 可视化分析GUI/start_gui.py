"""
改进的GUI启动脚本
确保窗口在前台显示
"""

import sys
import os
from pathlib import Path

# 确保在正确的目录
script_dir = Path(__file__).parent
os.chdir(script_dir)

# 将脚本目录加入路径（找到同目录的 absorption_gui）
if str(script_dir) not in sys.path:
    sys.path.insert(0, str(script_dir))
# 将父目录加入路径（找到父目录的 plot_absorption）
_parent_dir = script_dir.parent
if str(_parent_dir) not in sys.path:
    sys.path.insert(0, str(_parent_dir))

print("正在启动光谱可视化分析工具...")
print(f"工作目录: {os.getcwd()}")
print()

try:
    from PyQt5.QtWidgets import QApplication
    from PyQt5.QtCore import Qt
    from gui_config import APP_VERSION, UI_FONT_FAMILY
    from gui_launcher import ModuleLauncher
    from absorption_gui import AbsorptionGUI

    # 创建应用
    app = QApplication(sys.argv)
    app.setApplicationName("光谱可视化分析工具")
    app.setStyle('Fusion')
    # 全局字体：按平台自动选择（Windows 微软雅黑 / macOS 苹方）
    _font = app.font()
    _font.setFamily(UI_FONT_FAMILY)
    app.setFont(_font)

    # 先显示入口界面，选择模块后再进入主窗口
    print("显示模块选择界面...")
    launcher = ModuleLauncher()
    if not launcher.exec_() or not launcher.selected_mode:
        print("已取消，退出。")
        sys.exit(0)

    # 主窗口循环：窗口内点「返回模块选择」会重新弹出入口界面
    mode = launcher.selected_mode
    while mode:
        print(f"创建主窗口（模块: {mode}）...")
        window = AbsorptionGUI(initial_mode=mode)

        # 确保窗口在前台显示
        window.setWindowFlags(window.windowFlags() | Qt.WindowStaysOnTopHint)
        window.show()
        window.raise_()
        window.activateWindow()

        # 强制刷新界面
        from PyQt5.QtCore import QTimer
        QTimer.singleShot(100, window.raise_)

        print("GUI程序已启动！")
        print("如果看不到窗口，请检查任务栏或按Alt+Tab切换窗口")
        print()

        app.exec_()
        mode = getattr(window, 'next_mode', None)
        if mode == "launcher":
            print("返回模块选择界面...")
            launcher = ModuleLauncher()
            mode = (launcher.selected_mode
                    if launcher.exec_() == ModuleLauncher.Accepted else None)

    sys.exit(0)

except Exception as e:
    print(f"[错误] 启动失败: {e}")
    import traceback
    traceback.print_exc()
    input("\n按回车键退出...")
    sys.exit(1)