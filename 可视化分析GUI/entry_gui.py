# -*- coding: utf-8 -*-
"""轻量启动入口（打包 exe 的入口脚本，见 打包便携版.ps1）。

双击 exe 后的时间线：
  1. PyInstaller bootloader splash（splash.png 静态图）——覆盖解压与 Python 初始化；
  2. 本入口弹出 Qt 启动画面（gui_splash.StartupSplash），分阶段显示：
     加载绘图引擎/科学计算库 → 检查绘图模块依赖 → 启动入口界面；
  3. 关闭启动画面，弹出模块选择（ModuleLauncher）。

本文件必须保持轻量：重量级导入只允许出现在 main() 内部（import absorption_gui 一步），
否则启动画面会迟迟弹不出来。
"""
import os
import sys
from pathlib import Path

# 设置 UTF-8 输出，避免绘图模块打印中文/emoji 时 GBK 报错
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    try:
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass

# --windowed 打包时 stdout/stderr 可能为 None，统一重定向到空设备
if sys.stdout is None:
    sys.stdout = open(os.devnull, 'w', encoding='utf-8')
if sys.stderr is None:
    sys.stderr = open(os.devnull, 'w', encoding='utf-8')

# 将父目录加入 Python 路径，以便导入 plot_absorption / plot_emission 等
_parent = Path(__file__).resolve().parent.parent
if str(_parent) not in sys.path:
    sys.path.insert(0, str(_parent))

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QApplication

from gui_splash import StartupSplash


def _bootloader_splash_text(text):
    """更新 PyInstaller bootloader splash 上的文字（仅打包运行时存在本模块）"""
    try:
        import pyi_splash
        pyi_splash.update_text(text)
    except Exception:
        pass


def _close_bootloader_splash():
    """关闭 bootloader splash（Qt 启动画面已接管；不关闭会一直压在最上层）"""
    try:
        import pyi_splash
        pyi_splash.close()
    except Exception:
        pass


def check_modules():
    """检查科学计算库与绘图模块是否齐全，返回 (是否通过, 描述文字)"""
    import importlib
    lib_names = ["numpy", "scipy", "pandas", "matplotlib"]
    plot_names = ["plot_absorption", "plot_emission", "plot_lifetime", "read_xlsx_info"]
    versions = {}
    missing = []
    for name in lib_names + plot_names:
        try:
            mod = importlib.import_module(name)
            ver = getattr(mod, "__version__", "")
            if ver:
                versions[name] = ver
        except Exception as exc:
            missing.append(f"{name}（{exc}）")
    if missing:
        return False, "依赖缺失：" + "；".join(missing)
    libs = "、".join(f"{n} {versions[n]}" for n in lib_names)
    return True, f"依赖检查通过（{libs}）"


def main():
    # D8：必须在任何重活之前调用（PyInstaller onefile 下子进程会重跑主程序）
    import multiprocessing
    multiprocessing.freeze_support()
    # D6：日志落盘（打包后 stdout 被丢弃，异常只能进日志）
    from gui_log import setup_logging, install_excepthook
    setup_logging()
    install_excepthook()

    # 高分屏属性必须在 QApplication 创建前设置
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)

    from gui_config import APP_NAME, APP_VERSION, UI_FONT_FAMILY
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setStyle("Fusion")
    # 全局字体：按平台自动选择（Windows 微软雅黑 / macOS 苹方）
    font = app.font()
    font.setFamily(UI_FONT_FAMILY)
    app.setFont(font)

    # 启动画面接管 bootloader splash
    splash = StartupSplash()
    splash.show_centered()
    app.processEvents()
    _close_bootloader_splash()

    # 重量级导入：matplotlib / numpy / scipy / pandas / 三个绘图模块都在这一步加载
    splash.stage("正在加载绘图引擎与科学计算库\n（matplotlib / numpy / scipy / pandas）…")
    app.processEvents()
    _bootloader_splash_text("正在加载科学计算库…")
    try:
        import absorption_gui  # noqa: F401
    except Exception as exc:
        splash.stage(f"加载失败：{exc}")
        app.processEvents()
        raise

    # 依赖检查（absorption_gui 已带起大部分库，这里逐个确认并汇报版本）
    splash.stage("正在检查绘图模块依赖…")
    app.processEvents()
    _bootloader_splash_text("正在检查依赖…")
    ok, msg = check_modules()
    splash.stage(msg)
    app.processEvents()
    if not ok:
        # 依赖缺失：把错误留在画面上，稍候弹出崩溃提示
        from PyQt5.QtWidgets import QMessageBox
        QMessageBox.critical(None, "依赖检查失败", msg)
        splash.finish()
        sys.exit(1)

    # 进入主流程（入口界面循环）；主流程会在界面就绪后关闭启动画面
    splash.stage("正在启动入口界面…")
    app.processEvents()
    absorption_gui.main(app=app, startup_splash=splash)


if __name__ == "__main__":
    main()
