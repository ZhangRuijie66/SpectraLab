# -*- coding: utf-8 -*-
"""可复用的界面组件：后台绘图线程、自定义控件、Matplotlib 画布、资源定位等。"""

import math
import sys
import tempfile
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QApplication, QWidget, QHBoxLayout, QSizePolicy, QDoubleSpinBox,
    QSlider, QStyledItemDelegate, QStyle,
)

# 将父目录加入 Python 路径，便于独立导入绘图模块（源自 absorption_gui）
_parent = Path(__file__).resolve().parent.parent
if str(_parent) not in sys.path:
    sys.path.insert(0, str(_parent))


def resource_path(name):
    """定位资源文件：
    - PyInstaller 打包后：解压目录 sys._MEIPASS
    - 源码运行：脚本所在目录
    """
    candidates = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / name)
    script_dir = Path(__file__).resolve().parent
    candidates.append(script_dir / name)
    for c in candidates:
        try:
            if c.is_file():
                return str(c)
        except Exception:
            pass
    return None


class PlotWorker(QThread):
    """后台绘图线程，避免界面卡顿。

    进度/取消（D5）：耗时的寿命拟合通过 ``progress`` 信号把百分比与文案
    送到主线程的 QProgressDialog；``cancel()`` 置位后由计算函数通过
    ``is_cancelled()`` 轮询（plot_lifetime 的 cancel_cb）主动中止。
    """
    finished = pyqtSignal(object)
    error = pyqtSignal(str)
    progress = pyqtSignal(int, str)   # (百分比 0–100, 文案)

    def __init__(self, func, *args, **kwargs):
        super().__init__()
        self.func = func
        self.args = args
        self.kwargs = kwargs
        self._cancel_flag = False

    # ---------- 取消 ----------

    def cancel(self):
        """请求取消（线程安全：只置一个 bool，计算方轮询它）。"""
        self._cancel_flag = True

    def is_cancelled(self):
        """是否已被请求取消（传给 plot_lifetime 的 cancel_cb）。"""
        return bool(self._cancel_flag)

    def report(self, frac, message=""):
        """把 0~1 的进度比例转成 0~100 的整数并 emit（供 progress_cb 调用）。"""
        try:
            value = int(round(float(frac) * 100.0))
        except Exception:
            value = 0
        self.progress.emit(max(0, min(100, value)), str(message or ""))

    def run(self):
        try:
            result = self.func(*self.args, **self.kwargs)
            self.finished.emit(result)
        except Exception as e:
            # v4.27：只 emit str(e) 会把堆栈丢掉，日志里只剩一句
            # 「wrapped C/C++ object ... has been deleted」这种没法定位的信息。
            # 这里把完整堆栈写进程序日志（错误框文案不变，仍是 str(e)）。
            try:
                from gui_log import log_exception
                log_exception("后台绘图线程异常", e)
            except Exception:
                pass
            self.error.emit(str(e))


# 下拉弹窗取色表（由 gui_ui.apply_style 按当前主题写入）。
# delegate 在 paint() 时实时读取，所以切换主题后无需重建 delegate 就能立即换色；
# 深色主题下若沿用写死的白色，弹出的列表会是一整块刺眼白板。
_COMBO_COLORS = {
    'selected_bg': '#2563EB', 'selected_fg': '#ffffff',
    'hover_bg': '#eff6ff', 'hover_fg': '#1e293b',
    'bg': '#ffffff', 'fg': '#1e293b',
}
# 画布占位提示文字的初始颜色。真实颜色由 gui_ui._apply_mpl_theme 按主题刷新，
# 这里只取浅色主题的 MUTED 令牌（v4.30 收敛：原来写死 #64748b）
try:
    from gui_config import THEMES as _THEMES, DEFAULT_THEME as _DEFAULT_THEME
    _PLACEHOLDER_COLOR = _THEMES[_DEFAULT_THEME]['MUTED']
except Exception:                                   # pragma: no cover
    _PLACEHOLDER_COLOR = '#64748b'


def set_combo_palette(palette):
    """按主题色板更新下拉弹窗配色（palette 为 gui_config.THEMES 的一项）。"""
    if not palette:
        return
    _COMBO_COLORS.update({
        'selected_bg': palette.get('ACCENT', _COMBO_COLORS['selected_bg']),
        # 选中项文字取 CARD（v4.30 收敛）：浅色主题下即白色，高对比主题下
        # 也是白字压在深蓝实心选中条上；跟着色板走才不会有"白字压浅底"的组合
        'selected_fg': palette.get('CARD', _COMBO_COLORS['selected_fg']),
        'hover_bg': palette.get('HOVER_BG', _COMBO_COLORS['hover_bg']),
        'hover_fg': palette.get('TEXT', _COMBO_COLORS['hover_fg']),
        'bg': palette.get('CARD', _COMBO_COLORS['bg']),
        'fg': palette.get('TEXT', _COMBO_COLORS['fg']),
    })


class ComboItemDelegate(QStyledItemDelegate):
    """自定义下拉列表项的渲染：可靠地控制背景与文字颜色（避免 QSS 白框问题）。

    配色来自模块级 ``_COMBO_COLORS``（随主题变化），不再写死浅色。
    """

    def paint(self, painter, option, index):
        painter.save()
        text = index.data(Qt.DisplayRole)
        if not text:
            text = ""

        if option.state & QStyle.State_Selected:
            bg = QColor(_COMBO_COLORS['selected_bg'])
            fg = QColor(_COMBO_COLORS['selected_fg'])
        elif option.state & QStyle.State_MouseOver:
            bg = QColor(_COMBO_COLORS['hover_bg'])
            fg = QColor(_COMBO_COLORS['hover_fg'])
        else:
            bg = QColor(_COMBO_COLORS['bg'])
            fg = QColor(_COMBO_COLORS['fg'])

        painter.fillRect(option.rect, bg)
        painter.setPen(fg)
        # 垂直居中、左边距
        rect = option.rect.adjusted(8, 0, -8, 0)
        painter.drawText(rect, Qt.AlignVCenter | Qt.AlignLeft, text)
        painter.restore()

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        size.setHeight(max(size.height(), 30))
        return size


class SliderSpin(QWidget):
    """滑块 + 数值框 联动控件

    兼容现有 spin 的接口：value() / valueChanged / setRange / setValue / setSingleStep
    数值框与滑块双向同步，选择任意一方都更新另一方。
    logscale=True 时滑块在线性对数空间（10 的指数）工作——适用于跨多个数量级
    的参数（如 MEM 熵权重 λ），数值框仍显示真实值。
    """
    valueChanged = pyqtSignal(float)

    def __init__(self, min_val, max_val, value, step, scale=1, decimals=2,
                 suffix="", logscale=False, parent=None):
        super().__init__(parent)
        self._scale = scale  # 滑块整数缩放（分辨率=10*single_step 及以上）
        self._logscale = logscale
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # 数值框
        self.spin = QDoubleSpinBox()
        self.spin.setRange(min_val, max_val)
        self.spin.setSingleStep(step)
        self.spin.setDecimals(decimals)  # 先设小数位再设值：默认 2 位会把 1e-3 舍成 0
        self.spin.setValue(value)
        if suffix:
            self.spin.setSuffix(suffix)
        # 压低最小宽度：参数栏变窄时 SliderSpin 不应把整组控件顶出可视区（v4.19）
        self.spin.setMinimumWidth(74)

        # 滑块（整数范围映射到数值范围）
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setMinimumWidth(46)
        if logscale:
            # 对数空间：滑块值 = log10(数值) × 1000（分辨率 0.001 个数量级）
            self.slider.setRange(int(math.log10(min_val) * 1000),
                                 int(math.log10(max_val) * 1000))
            self.slider.setValue(int(math.log10(max(value, min_val)) * 1000))
            self.slider.setSingleStep(20)  # 0.02 个数量级
        else:
            self.slider.setRange(int(min_val * scale), int(max_val * scale))
            self.slider.setValue(int(value * scale))
            self.slider.setSingleStep(max(1, int(step * scale)))

        layout.addWidget(self.spin, 2)
        layout.addWidget(self.slider, 3)

        # 双向联动（用内置标志避免死循环）
        self._updating = False
        self.slider.valueChanged.connect(self._on_slider)
        self.spin.valueChanged.connect(self._on_spin)

    def _on_slider(self, val):
        if self._updating:
            return
        self._updating = True
        if self._logscale:
            self.spin.setValue(10 ** (val / 1000))
        else:
            self.spin.setValue(val / self._scale)
        self._updating = False
        self.valueChanged.emit(self.spin.value())

    def _on_spin(self, val):
        if self._updating:
            return
        self._updating = True
        if self._logscale:
            self.slider.setValue(int(math.log10(max(val, 1e-300)) * 1000))
        else:
            self.slider.setValue(int(val * self._scale))
        self._updating = False
        self.valueChanged.emit(val)

    # 兼容接口
    def value(self):
        return self.spin.value()

    def setValue(self, v):
        self.spin.setValue(v)

    def setRange(self, lo, hi):
        self.spin.setRange(lo, hi)
        if self._logscale:
            self.slider.setRange(int(math.log10(lo) * 1000),
                                 int(math.log10(hi) * 1000))
        else:
            self.slider.setRange(int(lo * self._scale), int(hi * self._scale))

    def setSingleStep(self, step):
        self.spin.setSingleStep(step)
        if self._logscale:
            self.slider.setSingleStep(max(1, int(step)))
        else:
            self.slider.setSingleStep(max(1, int(step * self._scale)))


class MplCanvas(FigureCanvas):
    """Matplotlib画布（随窗口自动缩放，支持固定长宽比，高分屏自适应）"""
    def __init__(self, parent=None, width=5, height=4, dpi=None):
        # 让 figure dpi 跟随屏幕逻辑 dpi（高分屏下图形清晰、尺寸正确）
        if dpi is None:
            screen = QApplication.primaryScreen()
            dpi = screen.logicalDotsPerInch() if screen is not None else 100
            # 避免 dpi 过大（高分屏缩放下 dpi 可能很高），限制在 96~144 之间
            dpi = max(96.0, min(144.0, float(dpi)))
        self.fig = Figure(figsize=(width, height), dpi=dpi)
        self.axes = self.fig.add_subplot(111)
        # 初始即显示提示并让 axes 铺满（避免空 coordinate 只占一小块）
        self._placeholder = None
        try:
            self.axes.set_axis_off()
            # 占位文字登记在 _placeholder 上，主题切换时由 _apply_mpl_theme 统一换色
            self._placeholder = self.axes.text(
                0.5, 0.5, "请选择数据文件夹加载光谱",
                transform=self.axes.transAxes,
                ha='center', va='center', fontsize=16, color=_PLACEHOLDER_COLOR)
            self.fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
        except Exception:
            pass
        self._ratio = None  # 固定长宽比 (w/h)，None 表示随窗口
        # D4：后台线程正在往 figure 里画时置 True——此时窗口缩放事件只记录
        # 尺寸，不触发 draw_idle()（并发绘制会画出半成品甚至崩溃），
        # 渲染方结束后调 end_busy() 补一次绘制。
        self.busy = False
        self._pending_fit = False
        super().__init__(self.fig)
        self.setParent(parent)
        FigureCanvas.setSizePolicy(
            self,
            QSizePolicy.Expanding,
            QSizePolicy.Expanding
        )
        FigureCanvas.updateGeometry(self)

    def set_ratio(self, ratio):
        """设置固定长宽比（ratio = width/height）。None 表示随窗口缩放并铺满"""
        self._ratio = ratio
        # 让 figure 尺寸跟随画布 widget（自动铺满，或按固定比例）
        self._fit_to_widget()

    def _fit_to_widget(self):
        """让 figure 尺寸适配画布 widget 当前大小（设备像素/dpi → 英寸），保证铺满。

        高分屏（Windows 缩放 125%/150%/200%）下 devicePixelRatio > 1，必须用
        “逻辑像素 × devicePixelRatio”得到的设备像素去设置 figure 尺寸；
        否则 figure 会偏小，matplotlib 默认贴左上角绘制，导致右侧/下方留白。
        """
        try:
            # devicePixelRatio == 0 或负数时按 1 处理
            dpr = float(self.devicePixelRatio() or 1.0)
            dev_w = self.width() * dpr
            dev_h = self.height() * dpr
            if dev_w <= 0 or dev_h <= 0:
                return
            dpi = self.fig.get_dpi()
            if self._ratio:
                # 固定长宽比（ratio = w/h）：在 widget 内尽量铺满（letterbox），不超出边界
                fig_w = dev_w / dpi
                fig_h = dev_h / dpi
                if fig_w / fig_h >= self._ratio:
                    # 画布相对更宽：限制高度，宽度按比例
                    new_h = fig_h
                    new_w = new_h * self._ratio
                else:
                    # 画布相对更高：限制宽度，高度按比例
                    new_w = fig_w
                    new_h = new_w / self._ratio
                self.fig.set_size_inches(new_w, new_h)
            else:
                # 自动：直接跟随 widget 尺寸铺满
                self.fig.set_size_inches(dev_w / dpi, dev_h / dpi)
        except Exception:
            pass

    def clear_fig(self):
        """安全清空 figure 的所有 axes（避免 constrained_layout 下 clear 的 KeyError）"""
        while self.fig.axes:
            try:
                self.fig.delaxes(self.fig.axes[-1])
            except Exception:
                break
        try:
            self.fig.clf()
        except Exception:
            pass

    def _fit_and_draw(self):
        """适配 figure 尺寸并重绘（防止图形消失/错位）

        缩放后先跑一次可选钩子 `on_after_fit`（GUI 用它按新尺寸重算子图边距，
        否则窗口变小后 y 轴标题又会被裁到图外）。

        D4：后台线程绘制期间（busy）只记录待处理标记并返回，由 end_busy()
        在渲染结束后统一补一次，避免主线程与工作线程同时操作 figure。
        """
        if getattr(self, 'busy', False):
            self._pending_fit = True
            return
        self._fit_to_widget()
        hook = getattr(self, 'on_after_fit', None)
        if hook is not None:
            try:
                hook()
            except Exception:
                pass
        if hasattr(self, 'draw'):
            try:
                self.draw_idle()
            except Exception:
                pass

    def set_busy(self, busy=True):
        """标记「后台线程正在绘制该画布」（D4）。"""
        self.busy = bool(busy)
        if not busy:
            self._pending_fit = False

    def end_busy(self, draw=True):
        """渲染结束：清 busy，若期间收到过缩放事件则补一次适配+绘制（D4）。"""
        pending = bool(getattr(self, '_pending_fit', False))
        self.busy = False
        self._pending_fit = False
        if pending and draw:
            self._fit_and_draw()
        elif draw:
            try:
                self.draw_idle()
            except Exception:
                pass

    def resizeEvent(self, event):
        """窗口缩放时，让图形跟随自适应并重绘（若设定了固定长宽比则保持比例）

        D4：后台绘制进行中只记录，不重绘（见 _fit_and_draw / end_busy）。
        """
        super().resizeEvent(event)
        if getattr(self, 'busy', False):
            self._pending_fit = True
            return
        # 延迟到事件处理完后，用最新的 widget 尺寸适配 figure 并重绘
        QTimer.singleShot(0, self._fit_and_draw)

    def showEvent(self, event):
        """首次显示时，让画布适配并铺满"""
        super().showEvent(event)
        if getattr(self, 'busy', False):
            self._pending_fit = True
            return
        QTimer.singleShot(0, self._fit_and_draw)
