# -*- coding: utf-8 -*-
"""光谱可视化分析工具 —— 主程序入口。

本文件仅负责组装界面（UiMixin）、数据（DataMixin）、绘图（PlotMixin）三个混入，
并把自定义控件（gui_components）与常量（gui_config）接入。
"""
import os
import sys
from pathlib import Path

# 设置 UTF-8 输出，避免 plot_emission 等模块打印 emoji 时 GBK 报错
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    try:
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass

# PyInstaller 打包为 --windowed（无控制台）时，stdout/stderr 可能为 None，
# 后续 setup_chinese_font 等 print() 会报错；这里统一重定向到空设备，保证程序不崩溃。
if sys.stdout is None:
    sys.stdout = open(os.devnull, 'w', encoding='utf-8')
if sys.stderr is None:
    sys.stderr = open(os.devnull, 'w', encoding='utf-8')

# 将父目录加入 Python 路径，以便导入 plot_absorption / plot_emission / read_xlsx_info
_parent = Path(__file__).resolve().parent.parent
if str(_parent) not in sys.path:
    sys.path.insert(0, str(_parent))

from PyQt5.QtCore import Qt, QTimer, QSettings
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QApplication, QMainWindow

from gui_config import (APP_ORG, APP_NAME, APP_VERSION, APP_ICON_FILENAME,
                        UI_FONT_FAMILY, DEFAULT_THEME)
from gui_components import resource_path
from gui_launcher import ModuleLauncher
from gui_ui import UiMixin
from gui_data import DataMixin
from gui_plot import PlotMixin


class AbsorptionGUI(UiMixin, DataMixin, PlotMixin, QMainWindow):
    """吸收光谱 / 发射光谱 / 荧光寿命可视化交互程序主窗口。"""

    # 光谱类型标识 → 下拉框索引（与 gui_ui 中 addItems 顺序一致）
    MODE_INDEX = {"absorption": 0, "emission": 1, "lifetime": 2, "scan3d": 3}

    def __init__(self, initial_mode=None):
        super().__init__()
        self.data_cache = {}  # 数据缓存
        self._lifetime_fit_cache = {}  # 寿命拟合结果缓存：{(文件, 方法, 速率点数): serialize dict}
        self.current_data = None
        self.current_plot_type = "combined"  # combined, single
        self.spectrum_type = "absorption"  # absorption / emission / lifetime
        # 当前文件夹的说明.xlsx 信息（读取到后用于增强图例标签）
        self.xlsx_info = None
        # 持久化设置（记住上次工作区等）
        self.settings = QSettings(APP_ORG, APP_NAME)
        # 主题初始值（v4.46）：setup_ui 里 apply_style 会立刻用到 self.theme，
        # 而 _restore_session 在 setup_ui 之后才跑。以前这里没有初值，于是
        # setup_ui 阶段一律按 DEFAULT_THEME 画一遍（系统深色用户会看到白闪），
        # 恢复后再重画。现在先按"保存的主题 → 否则跟随系统"定好初值，
        # 让首帧就是对的主题。
        try:
            from gui_config import detect_system_theme, THEMES as _THEMES
            _t = self.settings.value("theme", detect_system_theme(), str)
            self.theme = _t if _t in _THEMES else detect_system_theme()
        except Exception:
            self.theme = "light"
        # 工作区（目录树根目录）：优先取上次保存的，否则用默认
        self.workspace = self._get_saved_workspace()
        # 实时预览防抖定时器（避免频繁重绘）
        self._live_timer = QTimer()
        self._live_timer.setSingleShot(True)
        self._live_timer.setInterval(300)
        self._live_timer.timeout.connect(self.update_plot)
        self.setup_ui()
        self.setup_chinese_font()
        # 恢复上次会话（窗口/参数/文件夹，D2）；失败不影响启动
        try:
            self._restore_session()
        except Exception as e:
            from gui_log import log_exception
            log_exception("恢复会话失败", e)
        # 「💾 存为默认值」固定的寿命拟合参数优先于上次会话（v4.22 修订）
        try:
            self._apply_lifetime_defaults()
        except Exception as e:
            from gui_log import log_exception
            log_exception("套用默认值失败", e)
        # v4.39：按会话记住的「时间单位」刷新 τ 输入框的单位文案/量程
        # （数值本身就是按该单位存的，只刷新缓存与标签，不换算）
        try:
            self._apply_lifetime_unit()
        except Exception as e:
            from gui_log import log_exception
            log_exception("应用时间单位设置失败", e)
        # 入口界面选择的模块优先；未指定则沿用上次模式
        if initial_mode in self.MODE_INDEX:
            idx = self.MODE_INDEX[initial_mode]
        else:
            idx = self._last_mode_index()
        if 0 <= idx < self.spectrum_type_combo.count():
            self.spectrum_type_combo.setCurrentIndex(idx)


def main(app=None, startup_splash=None):
    """主函数

    Args:
        app: 已创建的 QApplication（由轻量入口 entry_gui 传入；源码直跑时为 None）
        startup_splash: gui_splash.StartupSplash 启动画面（entry_gui 传入），
                        入口界面就绪后由本函数关闭
    """
    # D8：必须在任何重活之前调用——PyInstaller onefile 下 fit_many 用
    # ProcessPoolExecutor 起子进程，没有 freeze_support() 子进程会重跑主程序
    import multiprocessing
    multiprocessing.freeze_support()
    # D6：日志落盘（%LOCALAPPDATA%\SpectraLab\logs\gui.log）+ 未捕获异常钩子
    from gui_log import setup_logging, install_excepthook
    setup_logging()
    install_excepthook(app)

    if app is None:
        # 开启高分屏支持（自动适配屏幕分辨率与DPI缩放）
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
        app = QApplication(sys.argv)
    app.setApplicationName("光谱可视化分析工具")
    app.setApplicationVersion(APP_VERSION)
    # v5.0.5：把 Qt 内置标准按钮（OK/Cancel/Yes/No…）译成中文。
    # PyQt5 wheel 只带 qtbase_zh_TW.qm 不带 zh_CN，installTranslator 装 .qm
    # 走不通，改用内存 translator（详见 gui_i18n 的说明）。
    # 必须在任何对话框创建之前装，否则先建出来的按钮文字不会刷新。
    try:
        from gui_i18n import install_zh_standard_buttons
        install_zh_standard_buttons(app)
    except Exception as e:
        from gui_log import log_exception
        log_exception("安装中文按钮翻译器失败", e)
    # 设置应用图标（任务栏/Dock/标题栏）
    try:
        icon_path = resource_path(APP_ICON_FILENAME)
        if icon_path:
            app.setWindowIcon(QIcon(icon_path))
    except Exception:
        pass

    # 设置应用样式
    app.setStyle('Fusion')

    # 全局字体：按平台自动选择（Windows 微软雅黑 / macOS 苹方）；根据屏幕分辨率/DPI自动调整基础字号
    screen = app.primaryScreen()
    if screen is not None:
        dpi = screen.logicalDotsPerInch()
        # 基准DPI为96，字体按 DPI/96 比例缩放（最小1.0倍，最大1.5倍）
        scale = min(max(dpi / 96.0, 1.0), 1.5)
        base_pt = int(12 * scale)
    else:
        base_pt = 12
    font = app.font()
    font.setFamily(UI_FONT_FAMILY)
    font.setPointSize(base_pt)
    app.setFont(font)

    # 入口界面选择模块（弹出后关闭启动画面）
    if startup_splash is not None:
        startup_splash.stage("正在启动入口界面…")
        app.processEvents()
    launcher = ModuleLauncher()
    if startup_splash is not None:
        startup_splash.finish()
    if launcher.exec_() != ModuleLauncher.Accepted or not launcher.selected_mode:
        return

    # 主窗口循环：窗口内点「返回模块选择」会设置 next_mode="launcher" 并关闭窗口，
    # 此时重新弹出入口界面；直接关闭窗口则退出程序
    mode = launcher.selected_mode
    while mode:
        window = AbsorptionGUI(initial_mode=mode)
        window.show()
        app.exec_()
        mode = getattr(window, 'next_mode', None)
        if mode == "launcher":
            # 传入主窗口当前主题，避免深色会话里弹出全白入口界面
            launcher = ModuleLauncher(
                theme=getattr(window, 'theme', DEFAULT_THEME))
            mode = (launcher.selected_mode
                    if launcher.exec_() == ModuleLauncher.Accepted else None)

    sys.exit(0)


if __name__ == '__main__':
    main()
