# -*- coding: utf-8 -*-
"""
绘图混入：负责实时预览、合并图/单独图、发射光谱、颜色方案与导出。
"""

import csv
import logging
import re
import sys
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.figure import Figure
from matplotlib.gridspec import GridSpec
from scipy.signal import find_peaks
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QMessageBox, QFileDialog, QApplication, QProgressDialog, QTableWidgetItem,
)

from gui_components import PlotWorker
from gui_log import log_exception, log_file_path
from plot_absorption import find_absorption_peaks
from curve_colors import CurveColors
import plot_compare as _pc

# 将父目录加入 Python 路径，便于独立导入绘图模块
_parent = Path(__file__).resolve().parent.parent
if str(_parent) not in sys.path:
    sys.path.insert(0, str(_parent))


class NumericTableItem(QTableWidgetItem):
    """按**数值**排序的表格项（v4.26 积分结果表用）。

    `QTableWidgetItem` 默认比较 DisplayRole 的**字符串**：会把 9 排在 100 后面，
    也不认科学计数法。积分值列必须按数值排，所以覆盖 `__lt__`；文本列仍走
    默认的字符串比较（父类实现），因此同一张表里两种排序都对。
    """

    def __lt__(self, other):
        try:
            return float(self.text()) < float(other.text())
        except (TypeError, ValueError):
            return super().__lt__(other)


class PlotMixin:
    """绘图、颜色方案、导出图片。"""

    # ---------- v4.45：统一后台任务启动器 + 代次校验 ----------
    #
    # 改造前有三条各自手写线程启动的路径（update_plot / _run_overlay_lifetime /
    # _run_batch_export），其中后两条把 ``self._plotting = True`` 写在 try 之外，
    # 一旦 start() 抛异常（线程对象创建失败、参数收集出错等），_plotting 就**永久
    # 停在 True**：此后 update_plot 在开头直接 return，实时预览彻底失效且没有任何
    # 提示，用户只能重启程序。
    #
    # 另外 _cancel_plotting 只 wait(5000)，超时后线程成孤儿——它计算完了仍会回写
    # 画布与 _last_*_result，把旧模式的结果画到新模式的界面上（实测：切到吸收模式
    # 后，寿命拟合图被画到了吸收模式的画布上）。
    #
    # 这里用「代次（generation）」一次性解决三个问题：
    #   · 启动：_begin_task() 递增代次、置 _plotting，且由调用方用 try/finally 保证复位；
    #   · 取消/切模式：_bump_generation() 让所有在途结果失效（不依赖 wait 是否成功）；
    #   · 回调：_is_stale(gen) 为真就直接丢弃，绝不写画布/写 _last_*。
    def _begin_task(self, long_task=False):
        """开始一个后台任务：递增代次、占用 _plotting，返回本次任务代次。"""
        self._plot_gen = int(getattr(self, '_plot_gen', 0)) + 1
        self._plotting = True
        self._fit_cancelled = False
        self._long_task = bool(long_task)
        try:
            self.progress_bar.setVisible(True)
            self.progress_bar.setRange(0, 0)
        except Exception:
            pass
        return self._plot_gen

    def _bump_generation(self):
        """让所有在途后台任务的结果失效（切模式 / 换文件夹 / 取消时调用）。"""
        self._plot_gen = int(getattr(self, '_plot_gen', 0)) + 1
        return self._plot_gen

    def _is_stale(self, gen):
        """该代次的结果是否已过期（任务已被更新的任务取代）。"""
        return gen is not None and gen != getattr(self, '_plot_gen', None)

    @staticmethod
    def _dispose_fig(fig):
        """释放一张临时 Figure（v4.46）。

        批量导出改为后台线程后，导出用的 fig 由 ``Figure()`` 直建（不注册到
        pyplot），对这类 fig 调 ``plt.close()`` 会报「Figure is not managed by
        pyplot」。这里按类型分派：能关就关，不能关就 clear 掉引用，绝不抛异常
        把导出流程带崩。
        """
        if fig is None:
            return
        try:
            plt.close(fig)
            return
        except Exception:
            pass
        try:
            fig.clear()
        except Exception:
            pass

    def _start_worker(self, func, params, on_finished, *, long_task=False,
                      dialog_text="正在生成图表…", indeterminate=True):
        """统一的后台任务启动：保证 _plotting 在任何异常路径下都能复位。

        返回本次任务代次；回调需自行携带并在开头用 ``_is_stale(gen)`` 判断。
        注意 ``params`` 会被就地塞入 ``worker`` 键（既有 _do_* 函数依赖它）。
        """
        gen = self._begin_task(long_task=long_task)
        try:
            params['worker'] = None          # 先占位，便于异常时统一清理
            worker = PlotWorker(func, params)
            params['worker'] = worker
            worker.finished.connect(lambda fig, g=gen: on_finished(fig, g))
            worker.error.connect(lambda msg, g=gen: self._on_plot_error(msg, g))
            worker.progress.connect(self._on_worker_progress)
            self.plot_worker = worker
            self._set_canvas_busy(True)
            self._start_progress_dialog(dialog_text, indeterminate=indeterminate)
            worker.start()
            return gen
        except Exception as e:
            # 任何启动期异常都必须把状态复位，否则 _plotting 泄漏 = 预览永久失效
            self._plotting = False
            self._fit_cancelled = False
            self._long_task = False
            self._bump_generation()          # 让可能已启动的部分结果失效
            try:
                self._set_canvas_busy(False)
                self.progress_bar.setVisible(False)
                self._close_progress_dialog()
            except Exception:
                pass
            log_exception("启动后台任务失败", e)
            QMessageBox.critical(self, "错误", f"启动绘图失败: {str(e)}")
            return None

    def on_plot_type_changed(self, index):
        """图表类型改变事件"""
        self.current_plot_type = "combined" if index == 0 else "single"
        self._trigger_live_update()

    def on_title_changed(self, text):
        """标题修改事件"""
        self._trigger_live_update()

    def on_item_checked(self, item):
        """文件勾选状态改变事件"""
        # 合并图模式下刷新
        if self.current_plot_type == "combined":
            self._trigger_live_update()

    def _get_y_label(self):
        """根据光谱类型返回 Y 轴标签"""
        if self.spectrum_type == "emission":
            return "发射强度 (AU)"
        return "吸收值 (AU)"

    def _get_xlim(self):
        """获取显示范围（波长上/下限）。上下限无效时返回 None"""
        lo = self.wl_min_spin.value()
        hi = self.wl_max_spin.value()
        if hi > lo:
            return (lo, hi)
        return None

    def _apply_xlim(self, ax, xlim):
        """应用 X 轴显示范围，并让 Y 轴跟随该区间内的数据重新缩放（加边距）"""
        if not xlim:
            return
        ax.set_xlim(xlim)
        # 收集 X 区间内的所有数据点，计算新的 Y 范围
        y_vals = []
        for line in ax.get_lines():
            xd = np.asarray(line.get_xdata(), dtype=float)
            yd = np.asarray(line.get_ydata(), dtype=float)
            # 跳过数据不完整（如 axvline 竖线：xdata 常数、ydata 含 ±inf）的线条
            if xd.ndim != 1 or yd.ndim != 1 or xd.size != yd.size or xd.size < 2:
                continue
            # v4.44：跳过竖线/横线这类"标注线"。axvline 的 xdata 恒为常数、
            # ydata 恒为 [0, 1]（轴坐标分母），它**不是数据**。此前只按 ndim/size
            # 过滤，竖线能顺利通过 → 它的 ydata=[0,1] 把 Y 下限拉到 0，
            # 于是「标注 EX」+「填显示范围」同时启用时，曲线被压到纵轴中部：
            # 实测曲线占纵轴比例从 83% 掉到 41.7%（纵轴跨度被撑大 2.4 倍）。
            if xd.size >= 2 and np.allclose(xd, xd[0], equal_nan=False):
                continue
            if yd.size >= 2 and np.allclose(yd, yd[0], equal_nan=False):
                continue
            mask = (xd >= xlim[0]) & (xd <= xlim[1]) & np.isfinite(yd)
            if mask.any():
                y_vals.append(yd[mask])
        if y_vals:
            all_y = np.concatenate(y_vals)
            y_min = np.nanmin(all_y)
            y_max = np.nanmax(all_y)
            margin = (y_max - y_min) * 0.10 if (y_max - y_min) > 0 else 0.1
            ax.set_ylim(y_min - margin, y_max + margin)
        # 锁定缩放，避免被重新 auto 缩放
        ax.set_autoscale_on(False)

    def _apply_ratio(self):
        """根据所选长宽比设置图形尺寸（"自动"则随窗口缩放）。

        荧光寿命模式下「寿命分布」画布与主画布一起应用；其余模式只应用主画布
        （寿命分布页在那些模式下本来就隐藏）。
        """
        try:
            ratio_text = self.ratio_combo.currentText()
            ratio_map = {
                "16:9": 16.0 / 9.0,
                "16:10": 16.0 / 10.0,
                "4:3": 4.0 / 3.0,
                "3:2": 3.0 / 2.0,
                "1:1": 1.0,
                "2:1": 2.0,
            }
            ratio = ratio_map.get(ratio_text)
            self.canvas.set_ratio(ratio)
            if getattr(self, 'spectrum_type', '') == 'lifetime':
                self.lifetime_canvas.set_ratio(ratio)
        except Exception:
            pass

    def _on_ratio_changed(self, *args):
        """「图形比例」改变：直接应用到画布尺寸。

        纯显示层面的调整（不重算数据、不重绘曲线），因此荧光寿命模式下也能
        立即生效，无需重新拟合。
        """
        self._apply_ratio()
        for cv in (self.canvas, getattr(self, 'lifetime_canvas', None)):
            if cv is None:
                continue
            try:
                cv._fit_to_widget()
                cv.draw_idle()
            except Exception:
                pass

    def get_color_map(self):
        """获取颜色映射"""
        color_scheme = self.color_combo.currentText()

        if "Blue-Red" in color_scheme:
            return plt.cm.Blues_r
        elif "Green-Purple" in color_scheme:
            return plt.cm.viridis
        elif "Rainbow" in color_scheme:
            return plt.cm.rainbow
        else:
            # 默认与 plot_emission 风格一致：Set1
            return plt.cm.Set1

    @staticmethod
    def _palette(color_map, n):
        """基于所选颜色方案生成 n 个颜色（最少 3 个，保证颜色丰富）。

        只用于单条/固定条数的图；合并图请用 _stable_colors，避免增删曲线时串色。
        """
        try:
            return color_map(np.linspace(0, 1, max(int(n), 3)))
        except Exception:
            return plt.cm.Set1(np.linspace(0, 1, max(int(n), 3)))

    def _color_assigner(self):
        """曲线颜色分配器（按文件身份记色，见 curve_colors.CurveColors）"""
        assigner = getattr(self, '_curve_color_assigner_obj', None)
        if assigner is None:
            assigner = self._curve_color_assigner_obj = CurveColors()
        return assigner

    def reset_curve_colors(self):
        """清空已记住的曲线颜色（换文件夹、换配色方案时调用）"""
        self._curve_color_assigner_obj = CurveColors()

    def _stable_colors(self, file_names, color_map):
        """按文件身份取色：已画过的文件沿用原色，新文件取色带上最远的新位置。

        这样在合并图里勾选/取消勾选、或增删数据文件，已有曲线的颜色都不变。

        v4.46：把**总条数**传给分配器。Set1 只有 9 色，26 条曲线时第 10 条起
        颜色重复（实测只有 9 种颜色），合并图无法区分；传入总数后分配器会自动
        降级到连续色带，保证任意条数下颜色互不相同。
        """
        assigner = self._color_assigner()
        total = len(file_names)
        return [assigner.get(name, color_map, total=total) for name in file_names]

    def on_color_scheme_changed(self, *args):
        """「颜色方案」改变：颜色随方案变，因此清空记忆后重画"""
        self.reset_curve_colors()
        self._trigger_live_update()

    def _legend_params(self):
        """根据「图例位置」选项返回 (loc, 额外kwargs)。图外选项用 bbox_to_anchor 移出坐标区。"""
        pos = getattr(self, 'legend_pos_combo', None)
        text = pos.currentText() if pos is not None else '右上 (Upper Right)'
        if '隐藏' in text:
            return None, {}
        if '自动' in text:
            return 'best', {}
        if '图外' in text and '右' in text:   # 图外右上
            return 'upper left', {'bbox_to_anchor': (1.02, 1.0), 'borderaxespad': 0.0}
        if '图外' in text and '下' in text:   # 图外下方
            return 'upper center', {'bbox_to_anchor': (0.5, -0.13), 'ncol': 4, 'borderaxespad': 0.0}
        if '右上' in text:
            return 'upper right', {}
        if '左上' in text:
            return 'upper left', {}
        if '右下' in text:
            return 'lower right', {}
        if '左下' in text:
            return 'lower left', {}
        return 'best', {}

    def _apply_legend(self, ax):
        """按所选图例位置应用图例，避免遮挡曲线。

        v4.46：**按曲线条数自适应**。此前固定 fontsize=9、单栏、坐标区内，
        26 条曲线时图例变成一整块盖住几乎全部数据区（实测图例占坐标区
        35%+，26 条标签只能显示到第 20 条左右、后面的直接溢出画布外）。
        现在按条数分档：
          ≤6 条：保持原样（单栏、9pt）；
          7–12 条：8pt，坐标区内改为两栏候选；
          >12 条：7.5pt，坐标区内**强制移到坐标区外右侧**并排成多栏，
                  宁可压缩绘图区宽一点，也不能把图盖死。
        """
        loc, extra = self._legend_params()
        if loc is None:     # 隐藏
            return
        try:
            n = len([ln for ln in ax.get_lines() if ln.get_label()
                     and not ln.get_label().startswith('_')])
        except Exception:
            n = 0
        extra = dict(extra)

        if n > 12:
            # 条数太多：一律外置到右侧、分栏、缩字号（不管用户选了哪个"图内"位置）
            size = 7.5
            if not extra.get('bbox_to_anchor'):
                extra.update({'bbox_to_anchor': (1.02, 1.0),
                              'borderaxespad': 0.0})
                loc = 'upper left'
            else:
                # 用户已选"图外"位置：沿用其锚点
                pass
            extra.setdefault('ncol', 3 if n > 24 else 2)
            extra.setdefault('handlelength', 1.2)
            extra.setdefault('labelspacing', 0.25)
            extra.setdefault('columnspacing', 0.9)
            extra.setdefault('framealpha', 0.85)
        elif n > 6:
            size = 8
            extra.setdefault('ncol', 2)
            extra.setdefault('labelspacing', 0.3)
        else:
            size = 9

        try:
            ax.legend(fontsize=size, loc=loc, **extra)
        except Exception:
            try:
                ax.legend(fontsize=size, loc=loc)
            except Exception:
                pass

    def _legend_outside_by_count(self, ax):
        """条数过多时图例已移到坐标区外，需要额外放宽右边距（v4.46）。"""
        try:
            n = len([ln for ln in ax.get_lines() if ln.get_label()
                     and not ln.get_label().startswith('_')])
        except Exception:
            return False
        return n > 12

    def _legend_needs_room(self):
        """图外选项需要为图例留出边距（True 时在 subplots_adjust 中放宽 bottom/right）。"""
        pos = getattr(self, 'legend_pos_combo', None)
        text = pos.currentText() if pos is not None else ''
        return '图外' in text

    # ---- 主题感知的绘图细节（v4.20）----

    def _mpl_colors(self):
        """当前主题的绘图配色（深色主题下坐标轴/网格/零线都要提亮才看得见）。"""
        P = self.theme_palette()
        return {
            'spine': P.get('MPL_SPINE', P['MPL_GRID']),
            'grid': P.get('MPL_GRID', P['MPL_GRID']),
            'grid_alpha': float(P.get('MPL_GRID_ALPHA', 0.3)),
            'zero': P.get('MPL_ZERO', 'gray'),
            'fg': P.get('MPL_FG', 'black'),
            'note_bg': P.get('MPL_NOTE_BG', 'white'),
            'note_fg': P.get('MPL_NOTE_FG', P.get('MPL_FG', 'black')),
            'muted': P.get('MUTED', 'gray'),
            # v5.0.2：荧光寿命图的 6 个语义色（原为硬编码，浅色/打印友好主题下
            # 对白底只有 1.74–3.09:1，几乎隐形）。缺键时退回本主题前景色，
            # 不会画不出线，但会失去语义区分——tests 里要求三套主题都齐全。
            'life_data': P.get('MPL_LIFE_DATA', P.get('MPL_FG', 'black')),
            'life_irf': P.get('MPL_LIFE_IRF', P.get('MPL_FG', 'black')),
            'life_irf_raw': P.get('MPL_LIFE_IRF_RAW', P.get('MUTED', 'gray')),
            'life_fit': P.get('MPL_LIFE_FIT', P.get('MPL_FG', 'black')),
            'life_mark': P.get('MPL_LIFE_MARK', P.get('MPL_FG', 'black')),
            'life_acf': P.get('MPL_LIFE_ACF', P.get('MPL_FG', 'black')),
            'life_ci': P.get('MPL_LIFE_CI', P.get('MPL_FG', 'black')),
        }

    def _grid(self, ax, dashed=False):
        """按当前主题画网格：深色主题网格线不透明度更高，否则压在深底上等于没有。"""
        C = self._mpl_colors()
        kw = {'alpha': C['grid_alpha']}
        if dashed:
            kw['linestyle'] = '--'
        try:
            ax.grid(True, **kw)
        except Exception:
            pass

    def _needed_left_px(self, fig, ax, renderer=None):
        """y 轴标题 + 刻度数字一共需要多少像素的左边距（不含最小留白）。"""
        r = renderer if renderer is not None else fig.canvas.get_renderer()
        labels = [t for t in ax.get_yticklabels() if t.get_text()]
        tick_w = max((float(t.get_window_extent(r).width) for t in labels),
                     default=0.0)
        lab_w = float(ax.yaxis.label.get_window_extent(r).width)
        # 刻度线 + labelpad + 一点留白
        return tick_w + lab_w + 22.0

    def _fit_left_margin(self, fig, ax, base=0.09):
        """把左边距撑到放得下 y 轴标题（画图时调用一次，并记住该轴的基准边距）。

        画布较窄时固定的 left=0.09 不够用：刻度数字 + 旋转 90° 的轴标题会被推出
        figure 左边界（实测轴标题 bbox 起点 x = -9.4px，屏幕上只剩 1–2px 竖条，
        深浅两种主题都中招）。这里按实测宽度重算，只加不减，最多到 0.45。
        缩放窗口后边距会再次不够，由 MplCanvas 的 resize 钩子调
        `_refit_canvas_margins()` 重算。
        """
        try:
            if getattr(ax, 'name', '') == '3d':
                return
            ax._spectra_base_left = float(base)
            fig_w = float(fig.get_size_inches()[0]) * float(fig.get_dpi())
            if fig_w <= 0:
                return
            left = min(0.45, max(float(base), self._needed_left_px(fig, ax) / fig_w))
            if abs(left - ax.get_position().x0) > 0.0015:
                fig.subplots_adjust(left=left)
        except Exception:
            pass

    def _refit_canvas_margins(self, cv):
        """按当前画布尺寸重算左边距（窗口缩放后调用，避免轴标题又被裁）。

        同一张画布上可能有多个子图（寿命拟合是上下两个），取所有子图里
        最大的需求，别让后算的那个把边距又缩回去。
        """
        try:
            fig = getattr(cv, 'fig', None)
            if fig is None or not fig.axes:
                return
            if any(getattr(ax, 'name', '') == '3d' for ax in fig.axes):
                return                      # 3D 轴标题不走这套平面边距逻辑
            fig_w = float(fig.get_size_inches()[0]) * float(fig.get_dpi())
            if fig_w <= 0:
                return
            r = fig.canvas.get_renderer()
            left = 0.0
            for ax in fig.axes:
                base = float(getattr(ax, '_spectra_base_left', 0.09))
                left = max(left, min(0.45, max(base,
                                               self._needed_left_px(fig, ax, r) / fig_w)))
            if left > 0 and abs(left - fig.axes[0].get_position().x0) > 0.0015:
                fig.subplots_adjust(left=left)
        except Exception:
            pass

    # ---- 光谱减法（两光谱相减 / 扣除本底） ----

    def _get_subtract_config(self):
        """读取「光谱减法」设置；未启用或参数不全时返回 None。

        A 选「所有光谱（各减本底）」→ mode='bg'（每条光谱都减去本底）；
        A 选具体文件 → mode='diff'（只绘制 A − B 差谱）。
        返回 {'mode': 'bg'|'diff', 'a': 文件名或 None, 'b': 文件名}。
        """
        chk = getattr(self, 'subtract_enable_check', None)
        if chk is None or not chk.isChecked():
            return None
        try:
            a = self.subtract_minuend_combo.currentText()
            b = self.subtract_ref_combo.currentText()
        except AttributeError:
            return None
        if not b or b not in self.data_cache:
            return None
        if a and a in self.data_cache:
            return {'mode': 'diff', 'a': a, 'b': b}
        return {'mode': 'bg', 'a': None, 'b': b}

    def _subtract_ref(self, wl, y, ref_name):
        """把本底光谱插值到当前波长网格后相减，裁剪到两者重叠的波长区间。"""
        ref_wl, ref_y = self._extract_xy(self.data_cache[ref_name]['data'])
        ref_wl = np.asarray(ref_wl, dtype=float)
        ref_y = np.asarray(ref_y, dtype=float)
        wl_arr = np.asarray(wl, dtype=float)
        lo = max(np.nanmin(wl_arr), np.nanmin(ref_wl))
        hi = min(np.nanmax(wl_arr), np.nanmax(ref_wl))
        if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
            raise ValueError(f"本底「{ref_name}」与数据波长范围无重叠，无法相减")
        mask = (wl_arr >= lo) & (wl_arr <= hi)
        wl2 = wl_arr[mask]
        y2 = np.asarray(y, dtype=float)[mask] - np.interp(wl2, ref_wl, ref_y)
        return wl2, y2

    def _get_plot_xy(self, file_name, sub_cfg=None):
        """取某文件绘图用的 (波长, 强度)；启用减法时先减去本底 B。"""
        wl, y = self._extract_xy(self.data_cache[file_name]['data'])
        if sub_cfg:
            wl, y = self._subtract_ref(wl, y, sub_cfg['b'])
        return np.asarray(wl), np.asarray(y)

    def _reset_subtract_skips(self):
        """清空「无法扣除本底」跳过清单（每次重绘前调用一次）。"""
        self._subtract_skipped = []

    def _checked_scope(self):
        """当前要处理的样品：左侧**勾选** ∩ 已加载（顺序与文件列表一致）。

        v4.37 起统一口径：光谱积分、寿命「叠加分布 / 跨样品汇总图 / PDF 报告」、
        「数据比较」点线图都只统计勾选项 —— 图上看不到的数据不再偷偷参与统计。
        """
        cache = getattr(self, 'data_cache', None) or {}
        try:
            return [f for f in self.get_checked_files() if f in cache]
        except Exception:
            return list(cache.keys())

    def _get_plot_xy_checked(self, file_name, sub_cfg=None, record=True):
        """宽容版 `_get_plot_xy`：返回 (波长, 强度) 或 (None, 原因)。

        「光谱减法」要求样品与本底的波长范围有**重叠**。一批数据里常混着用不同
        发射窗口测的光谱（例：300–540 nm 的样品能和 300–548 nm 的水本底相减，
        而 560–800 nm 的样品与本底毫无重叠）。v4.35 及以前这里让 ValueError 一路
        抛出，会把**整张图、整张积分结果表**一起带崩——现象就是"启用减法之后无法
        积分"（结果表整个清空、状态栏也没有任何解释）。

        现在改成：扣不了本底的那一条**只跳过自己**并记入 `_subtract_skipped`，
        其余光谱照常绘制/积分（`record=False` 供积分自己收集明细）。
        """
        try:
            wl, y = self._get_plot_xy(file_name, sub_cfg)
        except Exception as e:
            reason = str(e) or e.__class__.__name__
            if record:
                if getattr(self, '_subtract_skipped', None) is None:
                    self._subtract_skipped = []
                self._subtract_skipped.append((file_name, reason))
            logging.warning("光谱减法跳过 %s：%s", file_name, reason)
            return None, reason
        return (np.asarray(wl, dtype=float), np.asarray(y, dtype=float)), None

    def _subtract_skip_note(self, base="图表更新完成"):
        """状态栏文案：跳过了无法扣除本底的光谱时附上条数与原因。"""
        skips = getattr(self, '_subtract_skipped', None) or []
        if not skips:
            return base
        names = "、".join(n for n, _ in skips[:3])
        more = f" 等 {len(skips)} 条" if len(skips) > 3 else ""
        return (f"{base}；已跳过 {len(skips)} 条无法扣除本底的光谱"
                f"（{names}{more}，波长范围与本底无重叠）")

    # ---- 光谱积分（绘图区下方的数据输出区） ----

    @staticmethod
    def _integrate_band(wl, y, lo, hi):
        """梯形法计算 [lo, hi] 波长区间内的曲线下面积。

        v4.37 起实现搬进 `plot_compare.integrate_band`（独立模块 + 命令行可用），
        这里保留同名薄封装：积分结果表与「数据比较」的峰面积由此**共用同一实现**，
        两个数字不会因为两份代码而分叉。
        """
        return _pc.integrate_band(wl, y, lo, hi)

    def _compute_integration_results(self, sub_cfg=None):
        """对所有已加载样品计算积分，供数据输出区显示。

        返回 {'lo', 'hi', 'rows': [(样品名, 积分值)], 'skipped': [(样品名, 原因)],
        'unchecked': bool}；范围无效返回 None。
        范围是**左侧勾选的样品**（v4.37 起；与图上画出来的曲线一一对应——
        以前是"所有已加载样品"，会出现表里有、图上却没有的样品）。
        减法口径与绘图一致：启用光谱减法时按扣本底后的曲线积分（本底文件本身跳过）；
        差谱模式只输出 A − B 一行；积分用原始强度，不受「归一化」显示影响。

        v4.36：单条光谱扣不了本底（波长范围与本底无重叠）时**只跳过这一条**，
        不再让整张结果表整个清空——v4.35 的「启用减法之后无法积分」正是这么来的：
        一条 560–800 nm 的样品配 300–548 nm 的水本底，抛出的 ValueError 被
        `_do_plot` 里的 try/except 吞掉，`_last_integration_results` 直接置 None。
        """
        lo = float(self.integ_min_spin.value())
        hi = float(self.integ_max_spin.value())
        if hi <= lo:
            return None
        rows, skipped = [], []
        if sub_cfg and sub_cfg['mode'] == 'diff':
            name_a, name_b = sub_cfg['a'], sub_cfg['b']
            data_a = self.data_cache[name_a]['data']
            label = (f"{self._sample_name(name_a, data_a)} − "
                     f"{self._sample_name(name_b)}")
            xy, reason = self._get_plot_xy_checked(name_a, sub_cfg, record=False)
            if xy is None:
                skipped.append((label, reason))
            else:
                rows.append((label, self._integrate_band(xy[0], xy[1], lo, hi)))
        else:
            scope = self._checked_scope()
            if not scope:
                # 一个样品都没勾：不猜、也不偷偷按全部算（v4.37）
                return {'lo': lo, 'hi': hi, 'rows': [], 'skipped': [],
                        'unchecked': True}
            for file_name in scope:
                if sub_cfg and file_name == sub_cfg['b']:
                    continue  # 本底文件自身不参与积分（与绘图一致）
                data = self.data_cache[file_name]['data']
                name = self._sample_name(file_name, data)
                xy, reason = self._get_plot_xy_checked(file_name, sub_cfg,
                                                       record=False)
                if xy is None:
                    skipped.append((name, reason))
                    continue
                rows.append((name, self._integrate_band(xy[0], xy[1], lo, hi)))
        return {'lo': lo, 'hi': hi, 'rows': rows, 'skipped': skipped,
                'unchecked': False}

    def _integration_rows(self, results):
        """把积分结果整理成 [(样品, 区间, 积分值)]，跳过与积分区间无重叠的样品。"""
        if not results:
            return []
        lo, hi = results['lo'], results['hi']
        rows = []
        for name, value in results['rows']:
            if value is None or not np.isfinite(value):
                continue
            rows.append((str(name), f"{lo:g}–{hi:g}", f"{value:.6g}"))
        return rows

    def _update_integration_output(self):
        """把最近一次积分结果写进绘图区下方的**结果表**（主线程调用，v4.26）。

        原来是写入 QPlainTextEdit：等宽文本像调试输出、不能排序、只能整块复制。
        现在填 QTableWidget（样品 / 区间 / 积分值）。
        """
        table = getattr(self, 'integ_table', None)
        results = getattr(self, '_last_integration_results', None)
        if table is None:
            return
        rows = self._integration_rows(results)
        # 填充期间必须关掉排序：开着排序时逐行 setItem 会让行号乱跳、内容错位
        table.setSortingEnabled(False)
        try:
            table.clearContents()
            table.setRowCount(len(rows))
            for r, (name, band, val) in enumerate(rows):
                name_item = QTableWidgetItem(name)
                name_item.setToolTip(name)
                table.setItem(r, 0, name_item)
                table.setItem(r, 1, QTableWidgetItem(band))
                val_item = NumericTableItem(val)      # 数值排序
                val_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                table.setItem(r, 2, val_item)
        finally:
            table.setSortingEnabled(True)
        # 默认按样品名排（重新打开排序会沿用上次的排序指示器，行序不可控）
        table.sortItems(0, Qt.AscendingOrder)
        count_label = getattr(self, 'integ_count_label', None)
        if count_label is not None:
            sub_skips = (results or {}).get('skipped') or []
            unchecked = bool((results or {}).get('unchecked'))
            if results is None:
                # 原来这两句提示是写进文本框正文的，改表格后放进计数标签；
                # 注意区分「没加载数据」（未计算）和「范围填反了」（无效范围）
                if getattr(self, 'data_cache', None):
                    count_label.setText("积分范围无效（结束需大于起始）")
                else:
                    count_label.setText("未计算")
            elif unchecked:
                # v4.37：积分只统计勾选项，没勾就明确说清楚（而不是给一张空表）
                count_label.setText("未勾选任何样品（积分只统计左侧勾选项）")
            elif not rows:
                if sub_skips:
                    count_label.setText(
                        f"无可用积分结果（{len(sub_skips)} 个无法扣除本底，见悬停提示）")
                else:
                    count_label.setText(f"{results['lo']:g}–{results['hi']:g} nm 无数据重叠")
            else:
                skipped = len(results['rows']) - len(rows)
                text = (f"共 {len(rows)} 个样品 · "
                        f"{results['lo']:g}–{results['hi']:g} nm")
                if skipped:
                    text += f"（{skipped} 个无重叠未列出）"
                if sub_skips:
                    text += f"（{len(sub_skips)} 个无法扣本底已跳过）"
                count_label.setText(text)
            # 跳过明细放悬停提示：哪些样品、为什么（v4.36）
            if sub_skips:
                count_label.setToolTip(
                    "已跳过（无法扣除本底）：\n" +
                    "\n".join(f"· {n}：{r}" for n, r in sub_skips))
            else:
                count_label.setToolTip("")

    def _integration_tsv(self):
        """结果表的制表符文本（可直接粘进 Excel / Origin）。"""
        table = getattr(self, 'integ_table', None)
        if table is None:
            return ""
        lines = []
        heads = [table.horizontalHeaderItem(c).text()
                 if table.horizontalHeaderItem(c) is not None else ""
                 for c in range(table.columnCount())]
        lines.append("\t".join(heads))
        for r in range(table.rowCount()):
            cells = []
            for c in range(table.columnCount()):
                item = table.item(r, c)
                cells.append(item.text() if item is not None else "")
            lines.append("\t".join(cells))
        return "\n".join(lines)

    def _copy_integration_results(self):
        """复制积分结果表到剪贴板（制表符分隔，可直接粘贴进 Excel/Origin）"""
        table = getattr(self, 'integ_table', None)
        if table is None or table.rowCount() == 0:
            QMessageBox.warning(self, "提示", "暂无可复制的积分结果，请先加载数据")
            return
        text = self._integration_tsv().strip()
        if not text:
            QMessageBox.warning(self, "提示", "暂无可复制的积分结果，请先加载数据")
            return
        QApplication.clipboard().setText(text)
        self.status_bar.showMessage(
            f"已复制 {table.rowCount()} 行积分结果到剪贴板（可直接粘进 Excel）")

    def _export_integration_csv(self, save_dir=None):
        """把积分结果导出为 CSV（v4.26）。

        `save_dir=None`（按钮点击）时弹目录选择框；测试可传目录直接落地。
        编码用 utf-8-sig：Excel 双击打开中文不乱码。
        """
        table = getattr(self, 'integ_table', None)
        results = getattr(self, '_last_integration_results', None)
        if table is None or not results or table.rowCount() == 0:
            QMessageBox.warning(self, "提示", "暂无可导出的积分结果，请先加载数据")
            return None
        if save_dir is None:
            save_dir = QFileDialog.getExistingDirectory(
                self, "选择积分结果导出目录",
                self._dialog_start_dir(), QFileDialog.ShowDirsOnly)
        if not save_dir:
            return None
        try:
            out_dir = Path(save_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            out = out_dir / (f"积分结果_{results['lo']:g}-{results['hi']:g}nm.csv")
            with open(out, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f)
                writer.writerow(["样品", "起始波长 (nm)", "结束波长 (nm)", "积分值"])
                for r in range(table.rowCount()):
                    name = table.item(r, 0).text() if table.item(r, 0) else ""
                    val = table.item(r, 2).text() if table.item(r, 2) else ""
                    writer.writerow([name, f"{results['lo']:g}",
                                     f"{results['hi']:g}", val])
            self.status_bar.showMessage(f"积分结果已导出: {out}")
            return str(out)
        except Exception as e:
            log_exception("导出积分结果 CSV 失败", e)
            QMessageBox.critical(self, "错误", f"导出积分结果失败：{e}")
            return None

    # ---- 数据比较：说明.xlsx 的变量 vs 峰强度/峰面积/指定波长（v4.37） ----

    def _compare_config(self):
        """读「数据比较」参数（主线程）。返回 dict；参数不完整时抛 ValueError。"""
        x_var, group_var = self._compare_variables()
        text = self.compare_metric_combo.currentText()
        if text.startswith('峰面积'):
            metric = 'peak_area'
        elif text.startswith('指定波长'):
            metric = 'at_wavelength'
        else:
            metric = 'peak_intensity'
        lo = float(self.compare_peak_lo_spin.value())
        hi = float(self.compare_peak_hi_spin.value())
        band = (lo, hi) if (lo > 0 and hi > lo) else None
        at_wl = float(self.compare_wl_spin.value()) or None
        if metric == 'peak_area' and band is None:
            # 峰面积必须有区间：退回下方「光谱积分」的起止波长，保证与结果表同口径
            ilo = float(self.integ_min_spin.value())
            ihi = float(self.integ_max_spin.value())
            if ihi <= ilo:
                raise ValueError("「峰面积」需要波长区间：请填「峰强区间」，"
                                 "或把下方「光谱积分」的起止波长设成有效值")
            band = (ilo, ihi)
        if metric == 'at_wavelength' and at_wl is None:
            raise ValueError("纵轴选「指定波长处的值」时，请填「指定波长」")
        return {'x_var': x_var, 'group_var': group_var, 'metric': metric,
                'band': band, 'at_wl': at_wl}

    def _compare_y_label(self, cfg):
        """纵轴标签：按模式换用吸收/发射的措辞（模块里给的是发射口径）。"""
        metric, band, at_wl = cfg['metric'], cfg['band'], cfg['at_wl']
        absorption = self.spectrum_type == 'absorption'
        rng = f"{band[0]:g}–{band[1]:g} nm" if band else None
        if metric == 'peak_area':
            return (f'吸收峰面积 ({rng})' if absorption and rng
                    else (f'峰面积 ({rng})' if rng else '峰面积'))
        if metric == 'at_wavelength':
            return (f'吸光度 A@{at_wl:g} nm' if absorption
                    else f'发射强度@{at_wl:g} nm')
        if absorption:
            return f'最大吸收 ({rng})' if rng else '最大吸收（全谱）'
        return f'峰强度 ({rng})' if rng else '峰强度（全谱最大）'

    def _do_compare_plot(self, cfg=None):
        """画「指标 - 变量」点线图（同步执行；数据量小，无需后台线程）。

        只统计**勾选**的样品；曲线口径与预览图一致（启用减法时用扣本底后的曲线）。
        缺变量值的样品不进入图，并记进 `skipped`（v4.37 需求：null 不显示）。
        结果存 `self._last_compare_result`。
        """
        if cfg is None:
            cfg = self._compare_config()
        sub_cfg = self._get_subtract_config()
        scope = self._checked_scope()

        samples, broken = [], []
        for file_name in scope:
            data = self.data_cache[file_name]['data']
            name = self._sample_name(file_name, data)
            match_name = self._filename_for_match(file_name)
            try:
                wl, y = self._get_plot_xy(file_name, sub_cfg)
            except Exception as e:
                broken.append((name, f'曲线取不到（{e}）'))
                continue
            samples.append((name, match_name, np.asarray(wl, float),
                            np.asarray(y, float)))

        res = _pc.collect_points(samples, getattr(self, 'xlsx_info', None),
                                 cfg['x_var'], group_var=cfg['group_var'],
                                 metric=cfg['metric'], band=cfg['band'],
                                 at_wl=cfg['at_wl'])
        res['skipped'] = list(res['skipped']) + broken
        res['n_scope'] = len(scope)
        res['n_samples'] = len(samples)
        res['y_label'] = self._compare_y_label(cfg)
        res['x_label'] = cfg['x_var']

        title = f"{res['y_label']} - {cfg['x_var']}"
        if cfg['group_var']:
            title += f"（按 {cfg['group_var']} 分组）"
        res['title'] = title

        fig, summary = _pc.make_compare_figure(
            res['points'], res['x_label'], res['y_label'], title,
            linewidth=float(self.linewidth_spin.value()),
            color_map=self.get_color_map(),
            legend_prefix=cfg['group_var'],
            fig=self.compare_canvas.fig)
        res['summary'] = summary
        self._last_compare_result = res
        return res

    def _compare_status_text(self, res):
        """状态栏文案：点线图取了多少点、跳过了哪些（含缺变量值 / 未匹配编号）。"""
        txt = (f"数据比较：{res['summary']['n_points']} 个点"
               f"（{res['x_label']}"
               + (f" / 按 {res['group_var']} 分组" if res['group_var'] else '')
               + f"，取自勾选的 {res['n_scope']} 个样品）")
        if res['skipped']:
            txt += f"；跳过 {len(res['skipped'])} 个（详见「数据比较」页悬停提示）"
        return txt

    def _update_compare_output(self, res):
        """把跳过明细挂到「数据比较」画布 tooltip 上（哪些样品、为什么没进图）。"""
        canvas = getattr(self, 'compare_canvas', None)
        if canvas is None:
            return
        if res and res.get('skipped'):
            canvas.setToolTip("未进入点线图的样品：\n" +
                              "\n".join(f"· {n}：{r}" for n, r in res['skipped']))
        else:
            canvas.setToolTip("")

    def _run_compare(self):
        """「数据比较」按钮：画点线图并切到该标签页（v4.37）。"""
        if self.spectrum_type not in ('absorption', 'emission'):
            return
        try:
            cfg = self._compare_config()
        except Exception as e:
            QMessageBox.warning(self, "提示", str(e))
            return
        if not self._checked_scope():
            QMessageBox.warning(self, "提示",
                                "请先在左侧勾选至少一个样品\n（数据比较只统计勾选的样品）")
            return
        try:
            res = self._do_compare_plot(cfg)
        except Exception as e:
            log_exception("数据比较失败", e)
            QMessageBox.critical(self, "错误", f"数据比较失败：{e}")
            return
        self._update_compare_output(res)
        try:
            self.tab_widget.setCurrentWidget(self.compare_tab)
        except Exception:
            pass
        try:
            self.compare_canvas._fit_to_widget()
            self.compare_canvas.draw()
        except Exception:
            pass
        self.status_bar.showMessage(self._compare_status_text(res))

    def _export_compare_csv(self, save_dir=None):
        """把点线图的取点结果导出 CSV（与积分结果导出一致的习惯，v4.37）。"""
        res = getattr(self, '_last_compare_result', None)
        if not res or not res.get('points'):
            QMessageBox.warning(self, "提示", "暂无可导出的数据比较结果，请先点「数据比较」")
            return None
        if save_dir is None:
            save_dir = QFileDialog.getExistingDirectory(
                self, "选择数据比较结果导出目录",
                self._dialog_start_dir(), QFileDialog.ShowDirsOnly)
        if not save_dir:
            return None
        try:
            out = _pc.points_to_csv(
                res['points'], res['x_label'], res['y_label'],
                Path(save_dir) / f"数据比较_{res['x_label']}_{res['metric']}.csv")
            self.status_bar.showMessage(f"数据比较结果已导出: {out}")
            return str(out)
        except Exception as e:
            log_exception("导出数据比较 CSV 失败", e)
            QMessageBox.critical(self, "错误", f"导出数据比较结果失败：{e}")
            return None

    # ---- 单图目标与标题（供绘图与导出共用，保证导出文件名=标题） ----

    def _single_plot_target(self):
        """单图模式当前绘制的文件名：选中项优先，否则第一个。"""
        items = self.file_list.selectedItems()
        if items:
            return items[0].text()
        return next(iter(self.data_cache), None)

    def _type_prefix(self):
        """标题用中文前缀：发射/吸收/3D 扫描。"""
        if self.spectrum_type == 'emission':
            return '发射'
        if self.spectrum_type == 'scan3d':
            return '3D扫描'
        return '吸收'

    def _current_plot_title(self):
        """当前预览图的标题（与各 _plot_* 的标题逻辑一致），用作导出默认文件名。"""
        custom = self.title_edit.text().strip()
        if custom:
            return custom
        prefix = self._type_prefix()
        if self.spectrum_type == 'scan3d':
            target = self._single_plot_target()
            name = self._sample_name(target) if target else ''
            # v4.44：标题里带上绘图类型（3D 曲面 / 等高线 / Waterfall）。
            # 此前不含类型，三种视图导出到同一目录时会**互相同名覆盖**——
            # 实测连导 3 次只剩 1 个 PNG（留下的是最后一次的 Waterfall），
            # 用户以为三种图都导出了。
            try:
                plot_type = self.scan3d_plot_combo.currentText().strip()
            except Exception:
                plot_type = ''
            base = f"{prefix} - {name}" if name else prefix
            return f"{base} - {plot_type}" if plot_type else base
        sub_cfg = self._get_subtract_config()
        if sub_cfg and sub_cfg['mode'] == 'diff':
            name_a = self._sample_name(sub_cfg['a'])
            name_b = self._sample_name(sub_cfg['b'])
            return f"{prefix}光谱相减 - {name_a} − {name_b}"
        if self.current_plot_type == 'single':
            target = self._single_plot_target()
            name = self._sample_name(target) if target else ''
            return f"{prefix}光谱 - {name}" if name else f"{prefix}光谱"
        return f"{prefix}光谱对比"

    @staticmethod
    def _safe_filename(name):
        """把标题转成安全的文件名（替换 Windows 非法字符，统一减号）。"""
        name = str(name).replace('−', '-')
        name = re.sub(r'[\\/:*?"<>|]', '_', name).strip()
        return name or 'plot'

    def update_plot(self, explicit=False):
        """更新绘图预览

        Args:
            explicit: 是否由「实时预览」按钮显式触发。荧光寿命模式下拟合耗时较长，
                      仅显式触发时才真正拟合，其余情况只画提示文字。
        """
        if not self.data_cache:
            # 无数据时，在画布显示提示文本（避免空坐标轴）
            try:
                self.canvas.clear_fig()
                self.canvas.axes = self.canvas.fig.add_subplot(111)
                self.canvas.axes.text(0.5, 0.5, "请选择数据文件夹加载光谱",
                                      transform=self.canvas.axes.transAxes,
                                      ha='center', va='center', fontsize=16,
                                      color=self._mpl_colors()['muted'])
                self.canvas.axes.set_axis_off()
                self.canvas.draw()
            except Exception:
                pass
            return

        # 荧光寿命：非显式触发时只画提示（拟合耗时 1–2 分钟，不宜自动进行）
        if self.spectrum_type == "lifetime" and not explicit:
            try:
                self.canvas.clear_fig()
                self.canvas.axes = self.canvas.fig.add_subplot(111)
                self.canvas.axes.text(
                    0.5, 0.5,
                    "已在文件列表中选中寿命文件\n点击「开始拟合」按钮启动 MEM 拟合\n（约 1–2 分钟/文件）",
                    transform=self.canvas.axes.transAxes,
                    ha='center', va='center', fontsize=15,
                    color=self._mpl_colors()['muted'])
                self.canvas.axes.set_axis_off()
                self.canvas.draw()
            except Exception:
                pass
            return

        # 避免频繁改动时线程堆积：上次绘图未完成则跳过本次
        if getattr(self, '_plotting', False):
            return

        try:
            # v4.45：改用统一启动器——_plotting 的置位与复位都由它保证，
            # 不再依赖外层的 try/except（旧写法下若非启动期异常，_plotting 仍会泄漏）。
            is_lifetime = (self.spectrum_type == "lifetime")
            if is_lifetime:
                self.status_bar.showMessage(
                    "正在拟合荧光寿命（MEM 最大熵，可能需要 1–2 分钟，请耐心等待）...")
            else:
                self.status_bar.showMessage("正在生成图表...")
            # D4：控件值在主线程先读成参数字典，worker 内部不再碰 Qt 控件
            params = self._collect_plot_params()
            self._start_worker(
                self._do_plot, params, self._on_plot_finished,
                long_task=is_lifetime,
                dialog_text=("正在拟合荧光寿命…" if is_lifetime
                             else "正在生成图表…"),
                indeterminate=(not is_lifetime))

        except Exception as e:
            # _start_worker 内部已复位状态；这里只兜住「参数收集」阶段抛出的异常
            self._plotting = False
            self._bump_generation()
            self._set_canvas_busy(False)
            log_exception("启动绘图线程失败", e)
            QMessageBox.critical(self, "错误", f"绘图失败: {str(e)}")
            self.progress_bar.setVisible(False)
            self._close_progress_dialog()

    # ---------- D4：主线程参数快照 / 画布忙标记 ----------

    def _collect_plot_params(self):
        """在主线程里把后台绘图需要的所有控件值读成一个字典（D4）。

        工作线程只读这个字典，不再访问 self.xxx_spin.value() 之类的 Qt 控件
        （跨线程读控件是未定义行为；窗口缩放时尤其容易撞上）。
        """
        P = {}
        try:
            P['spectrum_type'] = getattr(self, 'spectrum_type', 'absorption')
            P['plot_type'] = getattr(self, 'current_plot_type', 'combined')
            P['linewidth'] = float(self.linewidth_spin.value())
            P['dpi'] = float(self.dpi_spin.value())
            P['mark_peaks'] = bool(self.mark_peaks_check.isChecked())
            P['peak_height'] = float(self.peak_height_spin.value())
            P['peak_distance'] = float(self.peak_distance_spin.value())
            P['custom_title'] = self.title_edit.text().strip()
            P['color_map'] = self.get_color_map()
            P['xlim'] = self._get_xlim()
            P['subtract'] = self._get_subtract_config()
        except Exception as e:
            log_exception("读取绘图参数失败", e)
        # 寿命参数（v4.38：界面输入的是寿命 τ 范围，这里换算成 plot_lifetime
        # 使用的速率网格 k = 1/τ：k_min = 1/τ_max、k_max = 1/τ_min）
        # v4.39：输入框里的数值单位由「时间单位」下拉框决定（ns / μs），这里统一
        # 换算回 ns —— 拟合与结果字典**始终是 ns**，单位只影响输入与显示。
        try:
            method = ("SESM" if "SESM" in self.lifetime_method_combo.currentText()
                      else "MEM")
            unit_factor = float(getattr(self, 'lifetime_unit_factor', 1.0) or 1.0)
            unit_symbol = getattr(self, 'lifetime_unit_symbol', 'ns')
            tau_min_in = float(self.lifetime_taumin_spin.value())
            tau_max_in = float(self.lifetime_taumax_spin.value())
            if not (0 < tau_min_in < tau_max_in):
                # 界面已用 _sync_lifetime_tau_range 保证 τ_min < τ_max，这里是
                # 兜底（例如设置里存了坏值）：回退默认范围，但**要说出来**，
                # 不能静默拟合出用户没要的范围。
                logging.getLogger('spectra').warning(
                    "寿命范围非法（τ_min=%s ≥ τ_max=%s %s），本次按默认 0.01–100 ns 拟合",
                    tau_min_in, tau_max_in, unit_symbol)
                if hasattr(self, 'status_bar'):
                    self.status_bar.showMessage(
                        "⚠️ 寿命范围需满足 τ_min < τ_max，本次按默认 0.01–100 ns 拟合",
                        8000)
                tau_min_in, tau_max_in = 0.01, 100.0
                unit_factor = 1.0
            tau_min = tau_min_in * unit_factor      # ns（内部规范单位）
            tau_max = tau_max_in * unit_factor
            k_min = 1.0 / tau_max
            k_max = 1.0 / tau_min
            fixed_taus = []
            try:
                raw = self.lifetime_fixed_taus_edit.text().replace('，', ',')
                fixed_taus = [float(x) for x in raw.replace(' ', '').split(',')
                              if x.strip()]
                fixed_taus = [t * unit_factor for t in fixed_taus if t > 0]
            except Exception:
                fixed_taus = []
            P.update({
                'lifetime_method': method,
                'lifetime_nrates': int(self.lifetime_nrates_spin.value()),
                'lifetime_lambda': float(self.lifetime_lambda_spin.value()),
                'lifetime_auto_lambda': bool(
                    self.lifetime_auto_lambda_check.isChecked()),
                'lifetime_taumin': tau_min_in,
                'lifetime_taumax': tau_max_in,
                'lifetime_unit': getattr(self, 'lifetime_unit', 'ns'),
                'lifetime_unit_factor': float(getattr(self, 'lifetime_unit_factor', 1.0) or 1.0),
                'lifetime_kmin': k_min,
                'lifetime_kmax': k_max,
                'lifetime_fixed_taus': fixed_taus,
            })
        except Exception as e:
            log_exception("读取寿命参数失败", e)
        # 3D 扫描参数
        try:
            comb_text = self.scan3d_comb_combo.currentText()
            if comb_text.startswith('只保留'):
                comb_mode = 'minima'
            elif comb_text.startswith('按乘性'):
                comb_mode = 'divide'
            elif comb_text.startswith('污染'):
                comb_mode = 'rows'
            else:
                comb_mode = 'off'
            P.update({
                'scan3d_mode': self.scan3d_plot_combo.currentText(),
                'scan3d_comb_mode': comb_mode,
                'scan3d_despike': int(self.scan3d_despike_spin.value()),
                'scan3d_sigma_em': float(self.scan3d_sigma_em_spin.value()),
                'scan3d_sigma_ex': float(self.scan3d_sigma_ex_spin.value()),
                'scan3d_log': bool(self.scan3d_log_check.isChecked()),
            })
        except Exception as e:
            log_exception("读取 3D 扫描参数失败", e)
        # 选中的文件（主线程读，后台线程只用字符串）
        try:
            selected = self.file_list.selectedItems()
            P['selected_file'] = selected[0].text() if selected else None
        except Exception:
            P['selected_file'] = None
        try:
            checked = self.get_checked_files()
            P['checked_files'] = list(checked)
        except Exception:
            P['checked_files'] = []
        return P

    def _set_canvas_busy(self, busy):
        """标记三个画布「后台线程正在绘制」（D4）。"""
        for attr in ('canvas', 'lifetime_canvas', 'diag_canvas', 'compare_canvas'):
            cv = getattr(self, attr, None)
            if cv is None:
                continue
            try:
                cv.set_busy(busy)
            except Exception:
                pass

    # ---------- D5：进度框 ----------

    def _start_progress_dialog(self, label, indeterminate=False):
        """为后台任务显示可取消的进度框（D5）。"""
        try:
            self._close_progress_dialog()
            dlg = QProgressDialog(label, "取消", 0, 100, self)
            dlg.setWindowTitle("请稍候")
            dlg.setWindowModality(Qt.WindowModal)
            dlg.setMinimumDuration(0)
            dlg.setAutoClose(False)
            dlg.setAutoReset(False)
            if indeterminate:
                # 不确定模式：普通绘图/3D 扫描无法给出百分比
                dlg.setRange(0, 0)
            else:
                dlg.setRange(0, 100)
                dlg.setValue(0)
            dlg.canceled.connect(self._on_progress_cancelled)
            dlg.show()
            self._progress_dialog = dlg
        except Exception as e:
            log_exception("创建进度框失败", e)

    def _on_worker_progress(self, value, message):
        """worker.progress 信号 → 进度框（D5）。"""
        dlg = getattr(self, '_progress_dialog', None)
        if dlg is None:
            return
        try:
            if dlg.maximum() > 0:
                dlg.setValue(int(value))
            if message:
                dlg.setLabelText(str(message))
        except Exception:
            pass

    def _on_progress_cancelled(self):
        """进度框「取消」按钮：请 worker 中止（D5）。"""
        worker = getattr(self, 'plot_worker', None)
        if worker is None:
            return
        try:
            worker.cancel()
        except Exception:
            pass
        dlg = getattr(self, '_progress_dialog', None)
        if dlg is not None:
            try:
                dlg.setLabelText("正在取消…")
            except Exception:
                pass
        try:
            self.status_bar.showMessage("正在取消拟合…")
        except Exception:
            pass

    def _close_progress_dialog(self, label=None):
        """关闭并释放进度框（D5）。"""
        dlg = getattr(self, '_progress_dialog', None)
        self._progress_dialog = None
        if dlg is None:
            return
        try:
            if label:
                dlg.setLabelText(str(label))
            dlg.canceled.disconnect()
        except Exception:
            pass
        try:
            dlg.close()
            dlg.deleteLater()
        except Exception:
            pass

    def _do_plot(self, params=None):
        """实际绘图逻辑（在后台线程执行）。

        params 由 _collect_plot_params 在主线程生成（D4）；直接调用（测试）时
        缺省自行采集一次，保证既能后台跑也能同步调用。
        """
        if params is None:
            params = self._collect_plot_params()
        self._params = params
        # 荧光寿命：后台线程中完成整个拟合过程（约 1–2 分钟）
        if params.get('spectrum_type', self.spectrum_type) == "lifetime":
            return self._do_lifetime_plot(params)

        # 3D 扫描（EEM）：曲面 / 等高线 / Waterfall
        if params.get('spectrum_type', self.spectrum_type) == "scan3d":
            return self._do_scan3d_plot(params)

        # 安全清空画布（保留 constrained_layout 设置，避免 KeyError）
        self.canvas.clear_fig()
        self.canvas.axes = self.canvas.fig.add_subplot(111)
        self._reset_subtract_skips()
        # v5.0.2：每张图重画前清空峰表缓存，避免「导出峰表」导出的是上一张图的峰
        self._last_peaks = []

        # 设置中文字体
        self.setup_chinese_font()

        # 获取参数（全部来自主线程快照，D4）
        linewidth = params['linewidth']
        mark_peaks = params['mark_peaks']
        peak_height = params['peak_height']
        peak_distance = params['peak_distance']
        custom_title = params['custom_title']
        color_map = params['color_map']
        xlim = params['xlim']
        sub_cfg = params['subtract']
        spectrum_type = params.get('spectrum_type', self.spectrum_type)
        plot_type = params.get('plot_type', 'combined')

        if sub_cfg and sub_cfg['mode'] == 'diff':
            # 两光谱相减：只绘制 A − B 差谱
            self._plot_diff(linewidth, mark_peaks, peak_height, peak_distance,
                            color_map, custom_title, xlim, sub_cfg)
        elif spectrum_type == "emission":
            # 发射光谱绘图
            if plot_type == "combined":
                self._plot_emission_combined(linewidth, mark_peaks, peak_height, peak_distance, color_map, custom_title, xlim, sub_cfg)
            else:
                self._plot_emission_single(linewidth, mark_peaks, peak_height, peak_distance, color_map, custom_title, xlim, sub_cfg)
        else:
            # 吸收光谱绘图
            if plot_type == "combined":
                self._plot_combined(linewidth, mark_peaks, peak_height, peak_distance, color_map, custom_title, xlim, sub_cfg)
            else:
                self._plot_single(linewidth, mark_peaks, peak_height, peak_distance, color_map, custom_title, xlim, sub_cfg)

        # 紧凑布局：留出坐标轴标签空间，同时尽量铺满画布；
        # 图例在图外时放宽 bottom/right 边距，避免图例被裁切或盖住坐标轴标签。
        # v4.46：曲线条数 > 12 时图例已被 _apply_legend 自动移到坐标区外右侧，
        # 这里也要相应放宽右边距，否则外置图例会被画布裁掉一半。
        try:
            need_room = (self._legend_needs_room()
                         or self._legend_outside_by_count(self.canvas.axes))
            if need_room:
                self.canvas.fig.subplots_adjust(left=0.09, right=0.72, top=0.92, bottom=0.26)
            else:
                self.canvas.fig.subplots_adjust(left=0.09, right=0.98, top=0.92, bottom=0.14)
            # 窄画布下 0.09 放不下旋转的 y 轴标题，按实测再撑一点
            self._fit_left_margin(self.canvas.fig, self.canvas.axes, base=0.09)
        except Exception:
            pass

        # 光谱积分：对所有已加载样品计算所选波长区间的曲线下面积
        # （结果存入 _last_integration_results，绘图完成后由数据输出区显示）
        try:
            self._last_integration_results = self._compute_integration_results(sub_cfg)
        except Exception as e:
            logging.warning("积分计算失败: %s", e)
            self._last_integration_results = None

        return self.canvas.fig

    def _do_scan3d_plot(self, params=None):
        """3D 扫描（EEM）绘图：3D 曲面 / 等高线 / Waterfall（后台线程执行）。

        params 为主线程快照（D4），控件值一律从字典取。
        """
        import plot_3d_scan as _p3
        if params is None:
            params = self._collect_plot_params()

        self.canvas.clear_fig()
        self.setup_chinese_font()

        # 目标文件：当前选中项 → 第一个（选中项已在主线程解析成字符串）
        file_name = params.get('selected_file')
        if not file_name or file_name not in self.data_cache:
            file_name = next(iter(self.data_cache), None)
        if file_name is None or file_name not in self.data_cache:
            ax = self.canvas.fig.add_subplot(111)
            ax.text(0.5, 0.5, "请先在文件列表中选择 3D 扫描数据文件",
                    transform=ax.transAxes, ha='center', va='center',
                    fontsize=14, color=self._mpl_colors()['muted'])
            ax.set_axis_off()
            return self.canvas.fig

        data = self.data_cache[file_name]['data']

        mode_text = params.get('scan3d_mode') or '3D 曲面'
        comb_mode = params.get('scan3d_comb_mode', 'off')

        prep = _p3.prepare_grid(
            data,
            spike_window=int(params.get('scan3d_despike', 3)),
            sigma_em=float(params.get('scan3d_sigma_em', 1.0)),
            sigma_ex=float(params.get('scan3d_sigma_ex', 0.0)),
            log_scale=bool(params.get('scan3d_log', False)),
            notch_comb=(comb_mode != 'off'),
            comb_mode=('minima' if comb_mode == 'off' else comb_mode),
            verbose=False,
        )
        label = data.get('label') or file_name
        log_scale = bool(params.get('scan3d_log', False))
        cbar_label = 'log10 强度' if log_scale else '强度 (AU)'

        if mode_text.startswith('3D 曲面'):
            ax = self.canvas.fig.add_subplot(111, projection='3d')
            surf, _, _ = _p3.draw_surface(ax, prep, label=label,
                                          log_scale=log_scale)
            # v5.0.1：调大色标占比。原来 shrink=0.55 + aspect=18 让 colorbar
            # 只剩约 15px 宽、右侧还空出 224px（实测 3D 曲面只占画布 56% 宽），
            # 而窄到那个程度的色标根本读不出刻度。改为 shrink=0.85 + aspect=12。
            cbar = self.canvas.fig.colorbar(surf, ax=ax, shrink=0.85,
                                            aspect=12, pad=0.06)
            cbar.set_label(cbar_label)
            self.canvas.fig.subplots_adjust(left=0.02, right=0.93,
                                            top=0.95, bottom=0.06)
        elif mode_text.startswith('等高线'):
            ax = self.canvas.fig.add_subplot(111)
            cf, _, _ = _p3.draw_contour(ax, prep, label=label)
            cbar = self.canvas.fig.colorbar(cf, ax=ax, shrink=0.85, pad=0.02)
            cbar.set_label(cbar_label)
            self.canvas.fig.subplots_adjust(left=0.10, right=0.92,
                                            top=0.93, bottom=0.14)
        else:
            ax = self.canvas.fig.add_subplot(111)
            _p3.draw_waterfall(ax, prep, label=label)
            self.canvas.fig.subplots_adjust(left=0.10, right=0.97,
                                            top=0.93, bottom=0.14)

        self._last_scan3d_result = {
            'name': file_name,
            'label': label,
            'plot_type': mode_text,
            'comb_mode': comb_mode,
            'stats': prep['stats'],
            'ex_range': [float(data['ex_wavelengths'].min()),
                         float(data['ex_wavelengths'].max())],
            'em_range': [float(data['em_wavelengths'].min()),
                         float(data['em_wavelengths'].max())],
            'shape': list(data['intensity'].shape),
        }
        return self.canvas.fig

    def _export_formats(self):
        """按「导出格式」下拉框返回扩展名列表（含点）。"""
        text = (self.export_format_combo.currentText()
                if hasattr(self, 'export_format_combo') else 'PNG (位图)')
        if text.startswith('PDF'):
            return ['.pdf']
        if text.startswith('SVG'):
            return ['.svg']
        if text.startswith('PNG + PDF'):
            return ['.png', '.pdf']
        if text.startswith('PNG + SVG'):
            return ['.png', '.svg']
        if text.startswith('全部'):
            return ['.png', '.pdf', '.svg']
        return ['.png']

    # ---------- C1 + C8：并行拟合全部 + 寿命分布叠加 ----------

    def _run_overlay_lifetime(self):
        """并行拟合**勾选**的样品，并在「寿命分布」页叠加对比（v4.37）。"""
        if self.spectrum_type != "lifetime":
            return
        if not self.data_cache:
            QMessageBox.warning(self, "提示", "请先加载寿命数据")
            return
        if not self._checked_scope():
            QMessageBox.warning(
                self, "提示",
                "请先在左侧勾选至少一个样品\n（「叠加分布」只处理勾选的样品）")
            return
        if getattr(self, '_plotting', False):
            return
        # v4.45：改用统一启动器（原来 _plotting=True 写在 try 外，启动期抛异常
        # 会永久泄漏，导致实时预览彻底失效且无提示）。
        # D4：参数在主线程读好
        params = self._collect_plot_params()
        msg = self._batch_fit_status_text(params)
        self.status_bar.showMessage(msg)
        self._start_worker(
            self._do_overlay_lifetime, params, self._on_overlay_finished,
            long_task=True, dialog_text=msg.rstrip('.'), indeterminate=True)

    def _batch_fit_status_text(self, params):
        """批量拟合前的提示文案：说明有多少样品可以直接复用已有结果（v4.23）。

        v4.37：只统计**勾选**的样品，文案里给出「勾选 N / 共 M」。
        """
        scope = self._checked_scope()
        total = len(scope)
        n_all = len(self.data_cache)
        n_cached = self._lifetime_cached_count(params)
        head = f"勾选 {total}/{n_all} 个样品："
        if total and n_cached >= total:
            return f"{head}已全部复用已有拟合结果，正在出图..."
        if n_cached:
            return (f"{head}正在拟合 {total - n_cached} 个"
                    f"（复用 {n_cached} 个已有拟合结果）...")
        return f"{head}正在并行拟合 {total} 个文件（多进程，请稍候）..."

    # ---------- v4.22：跨样品汇总图 / 多页 PDF 报告 ----------

    def _run_summary_plot(self):
        """并行拟合全部文件 → 画 τ/α/χ²R 随样品变化的三联图。"""
        self._run_batch_export('summary')

    def _run_pdf_report(self):
        """并行拟合全部文件 → 导出多页 PDF 报告。"""
        self._run_batch_export('pdf')

    def _run_batch_export(self, kind):
        if self.spectrum_type != "lifetime":
            return
        if not self.data_cache:
            QMessageBox.warning(self, "提示", "请先加载寿命数据")
            return
        if not self._checked_scope():
            QMessageBox.warning(
                self, "提示",
                "请先在左侧勾选至少一个样品\n（跨样品汇总图 / PDF 报告只处理勾选的样品）")
            return
        if getattr(self, '_plotting', False):
            QMessageBox.information(self, "提示", "正在拟合中，请稍候…")
            return
        save_dir = QFileDialog.getExistingDirectory(
            self, "选择保存目录", self._dialog_start_dir(),
            QFileDialog.ShowDirsOnly)
        if not save_dir:
            return
        # v4.45：改用统一启动器（理由同 _run_overlay_lifetime）
        params = self._collect_plot_params()
        params['kind'] = kind
        params['save_dir'] = save_dir
        msg = self._batch_fit_status_text(params)
        self.status_bar.showMessage(msg)
        self._start_worker(
            self._do_batch_export, params, self._on_batch_export_finished,
            long_task=True, dialog_text=msg.rstrip('.'), indeterminate=True)

    def _lifetime_fit_kwargs(self, params):
        """把主线程参数快照转成 plot_lifetime 的拟合参数（fit_many / MEMFitter.fit）。"""
        return dict(
            method=params.get('lifetime_method', 'MEM'),
            n_rates=int(params.get('lifetime_nrates', 201)),
            k_min=float(params.get('lifetime_kmin', 0.01)),
            k_max=float(params.get('lifetime_kmax', 100.0)),
            lambda_coeff=float(params.get('lifetime_lambda', 1e-3)),
            auto_lambda=bool(params.get('lifetime_auto_lambda', True)),
            fixed_taus=params.get('lifetime_fixed_taus') or None,
        )

    def _lifetime_cache_key(self, file_name, params):
        """单文件寿命拟合的缓存键：文件名 + 全部影响结果的参数。

        v4.23：`_do_lifetime_plot`（单文件拟合）与批量操作（叠加分布 / 跨样品
        汇总图 / PDF 报告）**必须用同一个键**，否则批量操作认不出单文件已经
        拟合过的结果，会把所有样品重新拟合一遍（用户反馈的问题）。
        """
        k_min = float(params.get('lifetime_kmin', 0.01))
        k_max = float(params.get('lifetime_kmax', 100.0))
        if k_max <= k_min:
            k_min, k_max = 0.01, 100.0
        return (file_name,
                params.get('lifetime_method', 'MEM'),
                int(params.get('lifetime_nrates', 201)),
                float(params.get('lifetime_lambda', 1e-3)),
                bool(params.get('lifetime_auto_lambda', True)),
                k_min, k_max,
                tuple(params.get('lifetime_fixed_taus') or []))

    def _lifetime_cached_count(self, params):
        """当前参数下有多少个样品的寿命拟合结果可直接复用（主线程调用，用于提示文案）。"""
        cache = getattr(self, '_lifetime_fit_cache', None) or {}
        try:
            return sum(1 for name in self.data_cache
                       if self._lifetime_cache_key(name, params) in cache)
        except Exception:
            return 0

    def _fit_all_with_cache(self, params, worker=None):
        """对**勾选的**文件做寿命拟合（v4.37），已有的拟合结果直接复用。

        v4.23：此前叠加分布 / 跨样品汇总图 / PDF 报告都无条件调用 fit_many，
        即使用户刚在单文件里拟合过、或刚导出过一次汇总图，也要把全部样品
        重新拟合一遍（每样品 1–2 分钟）。现在改为按 `_lifetime_fit_cache`
        查表复用，并把新拟合的结果回写缓存，于是「汇总图 → PDF 报告」这类
        连续操作只需拟合一次。

        v4.37：处理范围从"全部已加载"改为"左侧勾选的样品"，于是「叠加分布」
        可以只画部分样品对比；没勾选任何样品时返回空结果，由按钮处已给的
        提示兜住。

        Returns:
            (results, n_reused, n_fitted)：results 与勾选顺序一致，
            拟合失败的样品为 None。
        """
        import plot_lifetime as _pl
        names = self._checked_scope()
        cache = getattr(self, '_lifetime_fit_cache', None)
        if cache is None:
            cache = {}
            self._lifetime_fit_cache = cache

        results = [None] * len(names)
        todo_idx, todo = [], []
        n_reused = 0
        for i, name in enumerate(names):
            key = self._lifetime_cache_key(name, params)
            hit = cache.get(key)
            if hit is not None:
                results[i] = hit
                n_reused += 1
                continue
            d = self.data_cache[name]['data']
            todo_idx.append(i)
            todo.append({'name': name, 'time': d['time'], 'decay': d['decay'],
                         'irf': d['irf'], 'meta': d.get('meta')})

        if todo:
            fit_kwargs = self._lifetime_fit_kwargs(params)
            # v4.45：把「取消」与「进度」真正传进 fit_many。
            # 此前只在 fit_many **全部返回之后**才检查 worker.is_cancelled()，
            # 于是点取消后 7/7 个样品照样全部算完（用户等了全程）。
            cancel_cb = (worker.is_cancelled
                         if worker is not None and hasattr(worker, 'is_cancelled')
                         else None)
            progress_cb = None
            if worker is not None and hasattr(worker, 'report'):
                total_todo = len(todo)

                def progress_cb(done, _total, _w=worker, _n=total_todo):
                    try:
                        _w.report(done / max(_n, 1),
                                  f"已拟合 {done}/{_n} 个样品…")
                    except Exception:
                        pass
            try:
                fitted = _pl.fit_many(todo, fit_kwargs=fit_kwargs,
                                      cancel_cb=cancel_cb,
                                      progress_cb=progress_cb)
            except (OSError, RuntimeError) as e:
                log_exception("并行拟合不可用，退回串行", e)
                fitted = _pl.fit_many(todo, max_workers=1, fit_kwargs=fit_kwargs,
                                      cancel_cb=cancel_cb,
                                      progress_cb=progress_cb)
            for i, r in zip(todo_idx, fitted):
                results[i] = r
                if r:
                    # 回写缓存：之后单文件查看 / 再次导出可直接命中
                    cache[self._lifetime_cache_key(names[i], params)] = r
        # 被取消时：未启动的样品结果为 None，如实上报（不再谎报"全部完成"）
        n_cancelled = sum(1 for i in todo_idx if results[i] is None)
        if n_cancelled and worker is not None and worker.is_cancelled():
            # v4.45：_fit_cancelled 在 _begin_task 里才初始化；回归测试会绕过
            # 启动器直接调本函数，这里用赋值而不是依赖属性已存在。
            self._fit_cancelled = True
        self._fit_skipped = n_cancelled if getattr(self, '_fit_cancelled', False) else 0
        return results, n_reused, len(todo)

    def _do_batch_export(self, params=None):
        """后台线程：fit_many 并行拟合（复用缓存）→ 汇总图 / PDF 报告，返回提示文字。"""
        import plot_lifetime as _pl
        if params is None:
            params = {}
        worker = params.get('worker')
        results, n_reused, n_fitted = self._fit_all_with_cache(params, worker)
        if worker is not None and worker.is_cancelled():
            self._fit_cancelled = True
            return "已取消"
        results = [r for r in results if r]
        if not results:
            raise RuntimeError("没有成功拟合的样品（请检查数据与拟合参数）")
        save_dir = params.get('save_dir') or '.'
        # v4.39：汇总图 / PDF 报告的 τ 与时间轴跟随「时间单位」全局设置
        unit = getattr(self, 'lifetime_unit', 'ns')
        if params.get('kind') == 'pdf':
            path = _pl.export_report_pdf(results, save_dir=save_dir,
                                         verbose=False, time_unit=unit)
        else:
            path = _pl.plot_summary(results, save_dir=save_dir, verbose=False,
                                    time_unit=unit)
        detail = (f"复用 {n_reused} 个已有拟合结果"
                  if n_fitted == 0 else
                  f"复用 {n_reused} + 新拟合 {n_fitted}")
        return f"已保存（{len(results)} 个样品，{detail}）：\n{path}"

    def _on_batch_export_finished(self, msg, gen=None):
        """批量导出完成（v4.45：过期任务不再弹"成功"框）"""
        if self._is_stale(gen):
            logging.info("丢弃过期的批量导出回调（代次 %s）", gen)
            return
        self._plotting = False
        self._long_task = False
        self._set_canvas_busy(False)
        self._close_progress_dialog()
        self.progress_bar.setVisible(False)
        if getattr(self, '_fit_cancelled', False):
            self.status_bar.showMessage("已取消")
            return
        QMessageBox.information(self, "成功", str(msg))
        self.status_bar.showMessage(str(msg).splitlines()[-1])

    def _do_overlay_lifetime(self, params=None):
        """后台线程：fit_many 并行拟合（复用缓存）+ 画叠加分布图。"""
        import plot_lifetime as _pl
        if params is None:
            params = self._collect_plot_params()
        worker = params.get('worker')

        results, n_reused, n_fitted = self._fit_all_with_cache(params, worker)

        # 用户中途取消：不覆盖「寿命分布」页上已有的图
        if worker is not None and worker.is_cancelled():
            self._fit_cancelled = True
            return self.lifetime_canvas.fig

        self._overlay_reuse = (n_reused, n_fitted)

        # 画叠加图：**不再逐条按自身最大值归一**（v4.32）。
        # k_distribution 是各速率分量的**幅度**（峰高，与 decay_max 同刻度），
        # 逐条归一会把分布之间的幅度差抹掉、所有曲线峰高都被拉到 1，只剩形状。
        # 改为所有曲线共用**同一个**比例因子（全部曲线的全局最大值），
        # 于是曲线间的高度差得以保留；同一尺度下也比得出形状。
        # 图例只留样品名（v4.34）：叠加图是"看形状对比"用的，逐条挂振幅/强度
        # 会把图例撑成一大片、遮住右侧空间；组分级的振幅/强度占比见单独拟合的
        # 「寿命分布」页图例（8.8 节），那里才是逐组分读数的地方。
        fig = self.lifetime_canvas.fig
        fig.clf()
        ax = fig.add_subplot(111)
        entries = []        # (tau, dist, amp, name)
        # v4.39：叠加分布横轴按「时间单位」全局设置显示（内部仍是 ns）
        ltu = float(getattr(self, 'lifetime_unit_factor', 1.0) or 1.0)
        lts = getattr(self, 'lifetime_unit_symbol', 'ns')
        for r in results:
            if not r:
                continue
            k = np.asarray(r['k'], dtype=float)
            dist = np.asarray(r['k_distribution'], dtype=float)
            tau = 1.0 / np.maximum(k, 1e-12) / ltu
            amp = float(np.max(dist)) if dist.size else 0.0
            entries.append((tau, dist, amp, str(r.get('name', ''))))
        scale = max((e[2] for e in entries), default=0.0)
        ok = 0
        for tau, dist, amp, name in entries:
            ax.plot(tau, dist / scale if scale > 0 else dist, linewidth=1.0,
                    label=name)
            ok += 1
        ax.set_xscale('log')
        ax.set_xlabel(rf'$\tau$ ({lts})')
        ylab = '分布强度（同刻度，未逐条归一）'
        # 有样品的输入是归一化数据（preprocess 自动还原到各自 1e4 刻度）时，
        # 各曲线的绝对刻度并不统一 → 纵向刻度不可跨样品直接比较。
        # 只加一行短警告：文字太长会变成 3 行纵轴标签、高度不够会被裁掉（实测）。
        if any((r or {}).get('info', {}).get('rescaled_from_normalized')
               for r in results):
            ylab += '\n⚠ 含归一化输入（各自还原），纵向不可跨样品比'
            # 两行纵轴标签会紧贴刻度数字（实测间距仅 ~10px），补一点间隙
            ax.yaxis.labelpad = 10
        ax.set_ylabel(ylab, fontsize=9)
        ax.set_title(f'寿命分布叠加对比（{ok}/{len(results)} 个样品）',
                     fontsize=12)
        if ok:
            ax.legend(fontsize=8, loc='center left', bbox_to_anchor=(1.01, 0.5),
                      frameon=False)
        self._grid(ax, dashed=True)
        fig.subplots_adjust(left=0.10, right=0.80, top=0.90, bottom=0.17)
        self._fit_left_margin(fig, ax, base=0.10)

        self._overlay_results = results
        return fig

    def _on_overlay_finished(self, fig, gen=None):
        """并行叠加拟合完成（主线程）。v4.45：过期结果丢弃。"""
        if self._is_stale(gen):
            logging.info("丢弃过期的叠加拟合结果（代次 %s）", gen)
            return
        cancelled = getattr(self, '_fit_cancelled', False)
        self._fit_cancelled = False
        self._plotting = False
        self._long_task = False
        self.progress_bar.setVisible(False)
        self._set_canvas_busy(False)
        self._close_progress_dialog()
        if cancelled:
            self.status_bar.showMessage("已取消拟合")
            return
        self.lifetime_canvas._fit_to_widget()
        self.lifetime_canvas.draw()
        # 自动切到「寿命分布」页展示叠加结果
        try:
            self.tab_widget.setCurrentWidget(self.dist_tab)
        except Exception:
            pass
        results = getattr(self, '_overlay_results', []) or []
        ok = sum(1 for r in results if r)
        n_reused, n_fitted = getattr(self, '_overlay_reuse', (0, 0))
        detail = (f"（复用 {n_reused} 个已有结果）" if n_fitted == 0 and n_reused
                  else f"（复用 {n_reused} + 新拟合 {n_fitted}）"
                  if n_reused else "")
        self.status_bar.showMessage(
            f"并行拟合完成：{ok}/{len(results)} 个样品{detail}，"
            "叠加分布见「寿命分布」页")
        self.info_label.setText(
            f"并行拟合完成：{ok}/{len(results)} 个样品{detail}\n\n"
            + "\n".join(f"  {r.get('name')}: χ²R = {r['info']['chi_sqr']:.4g}"
                        for r in results if r))

    def _peak_label(self, pw):
        """峰位标注文本（D7）：「峰位标数值」未勾选时返回空串（不写数字）。"""
        chk = getattr(self, 'peak_value_check', None)
        if chk is not None and not chk.isChecked():
            return ''
        return f'{pw:.0f}'

    def _annotate_peak(self, ax, pw, pi, **kwargs):
        """峰位标注，未勾选「峰位标数值」时**根本不创建 Text 对象**（v5.0.2）。

        此前 `_peak_label` 返回空串、调用方仍无条件 `ax.annotate('')`，实测
        每次重绘在图里留下 6 个空 Text：肉眼看不到，但它们参与 bbox 计算、
        导出时被序列化，也让「自动避让重叠标注」类逻辑失效（空串的 bbox 是
        退化矩形，避让算法会把它当成一个占了位置的标注）。
        """
        lbl = self._peak_label(pw)
        if not lbl:
            return None
        try:
            return ax.annotate(lbl, xy=(pw, pi), **kwargs)
        except Exception:
            return None

    def _record_peaks(self, rows):
        """**覆盖**本张图的峰检测结果，供「导出峰表」使用（v5.0.2）。

        以前 `find_absorption_peaks` / `find_peaks` 返回的峰位峰高在
        `_plot_*` 里用完即弃——图上能看到「548」「564」，但程序从不产出
        峰位/峰高表，用户只能用眼睛抄。这里在画峰的同时把结果留下。
        只保留**真正画出来的**峰（被条数裁剪规则丢掉的峰不进表，
        否则"表和图对不上"比没有表更糟）。
        """
        self._last_peaks = list(rows or [])

    def _add_peak(self, sample, pw, pi):
        """往本张图的峰表里追加一行（多曲线合并图逐条累加）。"""
        if not hasattr(self, '_last_peaks') or self._last_peaks is None:
            self._last_peaks = []
        self._last_peaks.append({'样品': sample,
                                 '峰位(nm)': float(pw),
                                 '峰高': float(pi)})

    def _export_peak_table(self):
        """把最近一次绘图检测到的峰导出成 CSV/XLSX（v5.0.2）。"""
        rows = getattr(self, '_last_peaks', None) or []
        if not rows:
            QMessageBox.warning(
                self, "没有峰数据",
                "当前没有可导出的峰检测结果。\n\n"
                "请先勾选「标记峰」并完成一次绘图，再导出峰表。")
            self.status_bar.showMessage("导出峰表取消：暂无峰数据")
            return
        try:
            from PyQt5.QtWidgets import QFileDialog
            import pandas as pd
            base = self._safe_filename(self._current_plot_title() or 'peaks')
            default = str(Path(self._dialog_start_dir()) / f"{base}_peaks.csv")
            path, _flt = QFileDialog.getSaveFileName(
                self, "导出峰表", default,
                "CSV 表格 (*.csv);;Excel 工作簿 (*.xlsx)")
            if not path:
                return
            out = Path(path)
            out.parent.mkdir(parents=True, exist_ok=True)
            df = pd.DataFrame(rows)
            # 相对峰高：以本表最大峰为 1，跨样品快速比较用（不用心算）
            try:
                ymax = float(pd.to_numeric(df['峰高'], errors='coerce').max())
                df['相对峰高'] = (pd.to_numeric(df['峰高'], errors='coerce')
                                  / ymax).round(4) if ymax > 0 else np.nan
            except Exception:
                pass
            if out.suffix.lower() == '.xlsx':
                df.to_excel(out, index=False)
            else:
                # utf-8-sig：Excel 直接双击打开中文不乱码
                df.to_csv(out, index=False, encoding='utf-8-sig')
            self.status_bar.showMessage(
                f"已导出 {len(rows)} 个峰 → {out.name}")
            # 「表比图上的数字多」是正常的：合并图为了标注不糊成一团，
            # 单条曲线通常只标最强的一个峰（v4.46 的显示优化），而峰表是
            # 完整的数据产物。这一点要主动讲清楚，否则用户会以为表算错了。
            n_samples = len({r.get('样品', '') for r in rows})
            QMessageBox.information(
                self, "成功",
                f"已导出 {len(rows)} 个峰位到:\n{out}\n\n"
                f"覆盖 {n_samples} 个样品，口径与图上标注同源（同一次峰检测）。\n"
                f"注：合并图为了让标注不重叠，每条曲线通常只标最强的一个峰，"
                f"所以表里的行数可能比图上数字多——表是完整的检测结果。")
        except Exception as e:
            log_exception("导出峰表失败", e)
            QMessageBox.critical(self, "错误", f"导出峰表失败：{e}")

    # ---------- 出版图预设（D6） ----------

    def _pub_preset(self):
        """返回出版图预设的 (宽, 高) 英寸；「无」返回 None。"""
        text = (self.pub_preset_combo.currentText()
                if hasattr(self, 'pub_preset_combo') else '无')
        if text.startswith('单栏'):
            return (3.5, 2.6)
        if text.startswith('双栏'):
            return (7.0, 4.5)
        if text.startswith('幻灯片'):
            return (10.0, 6.0)
        return None

    def _pub_font_scale(self):
        """字号缩放系数：小图要缩小字号，否则字挤成一团。"""
        p = self._pub_preset()
        if p is None:
            return 1.0
        if p[0] <= 4.0:
            return 0.62
        if p[0] <= 8.0:
            return 0.78
        return 1.0

    def _pub_figsize(self, default=(10.0, 6.0)):
        p = self._pub_preset()
        return p if p else default

    def _apply_pub_rc(self, *args):
        """按出版图预设调整 matplotlib 默认字号（影响此后新建的图，含导出图）。"""
        import matplotlib as mpl
        scale = self._pub_font_scale()
        base = {'font.size': 10.0, 'axes.titlesize': 12.0,
                'axes.labelsize': 10.0, 'xtick.labelsize': 9.0,
                'ytick.labelsize': 9.0, 'legend.fontsize': 9.0}
        for k, v in base.items():
            mpl.rcParams[k] = max(4.0, v * scale)
        if hasattr(self, '_live_timer'):
            self._live_timer.start()

    def _savefig_pub(self, fig, path, dpi=None):
        """按出版图预设临时改尺寸后保存，再恢复（D6）。

        同时处理「导出用白底」：深色主题下界面是深底，但投稿/PPT 要白底深字，
        勾选后临时把 figure / axes / 文字 / 图例改成白底深字，保存完再恢复，
        界面外观不受影响。
        """
        import matplotlib as mpl
        if dpi is None:
            dpi = self.dpi_spin.value()
        preset = self._pub_preset()
        old_size = fig.get_size_inches()
        if preset:
            fig.set_size_inches(*preset)

        white = bool(getattr(self, 'export_white_check', None)
                     and self.export_white_check.isChecked())
        restore = []          # [恢复闭包]

        def _set(obj, getter, setter, new):
            """临时改属性并记录恢复动作（任一步失败就跳过，不影响导出）。"""
            try:
                old = getter(obj)
            except Exception:
                return
            try:
                setter(obj, new)
            except Exception:
                return
            restore.append(lambda: setter(obj, old))

        if white:
            # 「导出用白底」= 强制切到**打印样式**：白底 + 深色文字 + 浅灰描边。
            # v4.30 收敛：这几个颜色原来写死（'white' / '#cbd5e1' / '#1e293b'），
            # 现在直接引用浅色主题的绘图令牌——它就是"白底出版图"那套配色，
            # 改令牌不会漏掉导出这条路径。
            from gui_config import THEMES as _T
            _print = _T['light']
            _set(fig.patch, lambda o: o.get_facecolor(),
                 lambda o, c: o.set_facecolor(c), _print['MPL_FIG'])
            for ax in fig.axes:
                _set(ax.patch, lambda o: o.get_facecolor(),
                     lambda o, c: o.set_facecolor(c), _print['MPL_AX'])
                for sp in getattr(ax, 'spines', {}).values():
                    _set(sp, lambda o: o.get_edgecolor(),
                         lambda o, c: o.set_color(c), _print['MPL_SPINE'])
                for gl in (ax.xaxis.get_gridlines() + ax.yaxis.get_gridlines()):
                    _set(gl, lambda o: o.get_color(),
                         lambda o, c: o.set_color(c), _print['MPL_GRID'])
                texts = [getattr(ax, 'title', None),
                         getattr(ax.xaxis, 'label', None),
                         getattr(ax.yaxis, 'label', None)]
                texts += list(getattr(ax, 'texts', []))
                texts += list(ax.get_xticklabels()) + list(ax.get_yticklabels())
                for t in texts:
                    try:
                        if t is not None and t.get_text():
                            _set(t, lambda o: o.get_color(),
                                 lambda o, c: o.set_color(c), _print['MPL_FG'])
                    except Exception:
                        pass
                leg = ax.get_legend()
                if leg is not None:
                    try:
                        fr = leg.get_frame()
                        _set(fr, lambda o: o.get_facecolor(),
                             lambda o, c: o.set_facecolor(c), _print['MPL_AX'])
                        for t in leg.get_texts():
                            _set(t, lambda o: o.get_color(),
                                 lambda o, c: o.set_color(c), _print['MPL_FG'])
                    except Exception:
                        pass

        try:
            # v4.44：必须显式传 facecolor —— 只用 fig.patch 设白底不管用。
            # gui_ui._apply_mpl_theme 把 rcParam ``savefig.facecolor`` 设成了主题色
            # （深色主题是 #0b1220），而 rcParam 优先级**高于** fig.patch，
            # 于是深色主题下"导出用白底"（默认勾选）产出的仍是黑底图，
            # 而文字已被换成浅色主题的深灰 → 深底深字几乎全黑。
            # 浅色主题恰好也是白底，所以这个 bug 只在深色下暴露。
            try:
                _fc = fig.get_facecolor()
            except Exception:
                _fc = 'white'
            fig.savefig(path, dpi=dpi, bbox_inches='tight', facecolor=_fc)
        except TypeError:
            fig.savefig(path, dpi=dpi)
        finally:
            for fn in reversed(restore):
                try:
                    fn()
                except Exception:
                    pass
            if preset:
                fig.set_size_inches(*old_size)

    def _export_lifetime_plots(self, save_dir):
        """荧光寿命模式导出：拟合+残差合并图、寿命分布图（+ 结果 json）。

        导出格式由「导出格式」下拉框决定（PNG / PDF / SVG 或其组合）。
        """
        try:
            self.progress_bar.setVisible(True)
            self.progress_bar.setRange(0, 0)
            out_dir = Path(save_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            dpi = self.dpi_spin.value()
            exts = self._export_formats()
            result = getattr(self, '_last_lifetime_result', None)
            # v4.44：没拟合过就导出，只会得到两张写着「请点击开始拟合」的提示图，
            # 而弹窗却说"已导出"——用户以为拿到了拟合结果。此处明确拒绝。
            if not result:
                self.progress_bar.setVisible(False)
                QMessageBox.warning(
                    self, "还没有拟合结果",
                    "当前还没有荧光寿命拟合结果，导出的会是一张提示图。\n\n"
                    "请先点击「⏱ 开始拟合」，完成后再导出。")
                self.status_bar.showMessage("导出取消：尚未拟合")
                return
            name = result.get('name') if result else 'lifetime'

            exported = []
            for ext in exts:
                fit_path = out_dir / f"{name}_lifetime_fit{ext}"
                self._savefig_pub(self.canvas.fig, fit_path, dpi)
                peaks_path = out_dir / f"{name}_lifetime_peaks{ext}"
                self._savefig_pub(self.lifetime_canvas.fig, peaks_path, dpi)
                exported += [fit_path, peaks_path]
            msg = "已导出:\n" + "\n".join(str(p) for p in exported)
            if result:
                json_path, curve_path = self._write_lifetime_result_files(
                    result, out_dir, name)
                msg += f"\n{json_path}"
                if curve_path is not None:
                    msg += f"\n{curve_path}（原始曲线，json 里不再重复存）"
            self.progress_bar.setVisible(False)
            QMessageBox.information(self, "成功", msg)
            self.status_bar.showMessage(
                f"已导出寿命拟合图与寿命分布图到: {out_dir}（格式 {'/'.join(exts)}）")
        except Exception as e:
            self.progress_bar.setVisible(False)
            QMessageBox.critical(self, "错误", f"导出失败: {str(e)}")

    def _write_lifetime_result_files(self, result, out_dir, name):
        """把寿命拟合结果写盘：**瘦身 json** + 原始曲线 csv（v5.0.2）。

        原实现把 `result` 整体 dump：单个样品 149 KB，其中 `time`/`decay`
        各 4000 点是原始测量数据（能从源文件重读），`info` 里还塞着
        `y_fitted`/`residuals`/`irf_shifted` 三条同长度曲线，真正结论字段
        只有几十个。批量 20 个样品就是 3 MB 纯冗余。

        现在拆成两个产物：
          · ``*_fit_result.json`` —— 只留结论（τ、占比、χ²R、拟合区间…）；
          · ``*_curve.csv`` —— 曲线（时间/衰减/IRF/拟合/残差/τ 分布），
            给想复核拟合质量的人用，Excel 直接可读。
        两者都在同一目录，json 里用 ``_curve_file`` 指过去。
        """
        import csv as _csv
        import json as _json
        from plot_lifetime import NumpyTypeEncoder

        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        HEAVY_TOP = ('time', 'decay', 'irf', 'k', 'k_distribution')
        HEAVY_INFO = ('y_fitted', 'residuals', 'irf_shifted', 'peak_fit',
                      'lambda_scan_chi2')

        # ---- ① 曲线 csv ----
        info = result.get('info', {}) or {}
        time = np.asarray(result.get('time', []), dtype=float)
        columns = []           # [(列名, 数组)]
        for key, col in (('time', 'time'), ('decay', 'decay'), ('irf', 'irf')):
            arr = result.get(key)
            if arr is not None and np.size(arr):
                columns.append((col, np.asarray(arr, dtype=float)))
        if time.size:
            fs = int(info.get('fit_start', 0) or 0)
            fe = int(info.get('fit_end', 0) or 0)
            for key, col in (('irf_shifted', 'irf_shifted'),
                             ('y_fitted', 'y_fitted'), ('residuals', 'residuals')):
                arr = info.get(key)
                if arr is None or not np.size(arr):
                    continue
                a = np.asarray(arr, dtype=float)
                # y_fitted / residuals 只覆盖拟合区间，前面补空对齐到 time
                if col in ('y_fitted', 'residuals') and a.size == max(fe - fs, 0):
                    buf = np.full(time.size, np.nan)
                    buf[fs:fs + a.size] = a
                    a = buf
                elif a.size < time.size:
                    buf = np.full(time.size, np.nan)
                    buf[:a.size] = a
                    a = buf
                else:
                    a = a[:time.size]
                columns.append((col, a))
        curve_path = None
        if columns:
            n = max(len(a) for _c, a in columns)
            curve_path = out_dir / f"{name}_curve.csv"
            with open(curve_path, 'w', newline='', encoding='utf-8-sig') as f:
                w = _csv.writer(f)
                w.writerow([c for c, _a in columns])
                for i in range(n):
                    w.writerow([
                        (f"{a[i]:.10g}" if i < len(a) and np.isfinite(a[i])
                         else '')
                        for _c, a in columns])

        # ---- ② 瘦身 json ----
        slim = {k: v for k, v in result.items() if k not in HEAVY_TOP}
        slim_info = {k: v for k, v in (result.get('info') or {}).items()
                     if k not in HEAVY_INFO}
        slim['info'] = slim_info
        # τ 分布（k + 分布强度）是结论本身，不能全丢——抽稀到 ≤200 点保留形状
        k = np.asarray(result.get('k', []), dtype=float)
        dist = np.asarray(result.get('k_distribution', []), dtype=float)
        if k.size and dist.size == k.size:
            step = max(int(np.ceil(k.size / 200.0)), 1)
            slim['k_thinned'] = k[::step].tolist()
            slim['k_distribution_thinned'] = dist[::step].tolist()
        if curve_path is not None:
            slim['_curve_file'] = curve_path.name
        slim['_note'] = ('v5.0.2 起 json 只存结论；原始曲线/拟合曲线/残差'
                         '见同目录 *_curve.csv（time/decay/irf 等大数组已移出）')
        json_path = out_dir / f"{name}_fit_result.json"
        with open(json_path, 'w', encoding='utf-8') as f:
            # v4.44：ensure_ascii=False —— 否则中文样品名/单位会被转义成
            # \uXXXX，产物无法直接阅读或用 grep 检索。
            _json.dump(slim, f, cls=NumpyTypeEncoder,
                       ensure_ascii=False, indent=2)
        return json_path, curve_path

    def _do_lifetime_plot(self, params=None):
        """荧光寿命拟合绘图（后台线程执行：解析→预处理→MEM 拟合→高斯分解→出图）。

        D4：控件值全部来自主线程快照 params。
        D5：拟合过程接 progress_cb / cancel_cb，支持进度显示与中途取消；
        取消时**不清画布**，保留上一次已画出的结果。
        """
        import plot_lifetime as _pl
        if params is None:
            params = self._collect_plot_params()
        worker = params.get('worker')

        # 注意：这里不 clear_fig()——取消拟合时要保留上一次的结果，
        # 清画布的动作放到 _render_lifetime_result 里（只在真正出图前清）。
        self.setup_chinese_font()

        # 目标文件：当前选中项 → 第一个勾选 → 第一个（主线程已解析成字符串）
        file_name = params.get('selected_file')
        if not file_name or file_name not in self.data_cache:
            checked = params.get('checked_files') or []
            file_name = checked[0] if checked else next(iter(self.data_cache), None)
        if file_name is None or file_name not in self.data_cache:
            self.canvas.clear_fig()
            ax = self.canvas.fig.add_subplot(111)
            ax.text(0.5, 0.5, "请先在文件列表中选择寿命文件",
                    transform=ax.transAxes, ha='center', va='center',
                    fontsize=14, color=self._mpl_colors()['muted'])
            ax.set_axis_off()
            return self.canvas.fig

        entry = self.data_cache[file_name]['data']
        method = params.get('lifetime_method', 'MEM')
        n_rates = int(params.get('lifetime_nrates', 201))
        lambda_coeff = float(params.get('lifetime_lambda', 1e-3))
        auto_lambda = bool(params.get('lifetime_auto_lambda', True))
        k_min = float(params.get('lifetime_kmin', 0.01))
        k_max = float(params.get('lifetime_kmax', 100.0))
        if k_max <= k_min:
            k_min, k_max = 0.01, 100.0
        fixed_taus = list(params.get('lifetime_fixed_taus') or [])
        linewidth = float(params.get('linewidth', 1.5))
        custom_title = params.get('custom_title', '')

        # ---- 拟合结果缓存：同文件 + 同方法 + 同速率点数 + λ 设置 → 直接加载上次结果 ----
        # （缓存随数据重载/模式切换清空，见 gui_data；键由 _lifetime_cache_key
        #   统一生成，保证与批量操作（叠加分布/汇总图/PDF 报告）共用同一份缓存）
        cache_key = self._lifetime_cache_key(file_name, params)
        cache = getattr(self, "_lifetime_fit_cache", {})
        cached = cache.get(cache_key)
        if cached is not None:
            self._render_lifetime_result(cached, linewidth, custom_title)
            self.status_bar.showMessage(
                f"{file_name}: 直接加载上次拟合结果（缓存）", 5000)
            return self.canvas.fig

        # ---- 进度 / 取消回调（D5）：worker 在主线程里更新进度框 ----
        progress_cb = worker.report if worker is not None else None
        cancel_cb = worker.is_cancelled if worker is not None else None

        # ---- 拟合（纯 numpy/scipy，最大熵 + IRF 重卷积；auto_lambda 时扫描 λ） ----
        fitter = _pl.MEMFitter(verbose=False, name=file_name)
        fitter.load(entry['time'], entry['decay'], entry['irf'], entry.get('meta'))
        fitter.preprocess()
        try:
            fitter.fit(method=method, n_rates=n_rates,
                       k_min=k_min, k_max=k_max, fixed_taus=fixed_taus or None,
                       lambda_coeff=lambda_coeff, auto_lambda=auto_lambda,
                       progress_cb=progress_cb, cancel_cb=cancel_cb)
        except _pl.FitCancelled:
            # 用户取消：不弹错误框、不清画布，保留上一次结果（D5）
            self._fit_cancelled = True
            logging.info("用户取消了寿命拟合：%s", file_name)
            return self.canvas.fig
        fitter.postprocess()
        result = fitter.serialize(None)
        if hasattr(self, "_lifetime_fit_cache"):
            self._lifetime_fit_cache[cache_key] = result
        self._render_lifetime_result(result, linewidth, custom_title)
        return self.canvas.fig

    def _rerender_lifetime_cosmetic(self):
        """寿命模式：只把**上一次的拟合结果**重画一遍，不重新拟合（v4.39）。

        背景：寿命模式的实时更新被整体关掉（重算 1–2 分钟），于是用户改「绘图标题」
        后画布毫无变化——连导出的 PNG 也还是旧标题（用户实际反馈）。
        标题 / 线宽 / 颜色这类**纯外观**参数不需要重算，直接复用缓存结果重画，
        耗时几十毫秒。
        """
        if getattr(self, 'spectrum_type', None) != "lifetime":
            return
        if getattr(self, '_plotting', False) or getattr(self, '_long_task', False):
            return                      # 正在拟合：别和后台线程抢画布
        result = getattr(self, '_last_lifetime_result', None)
        if not result:
            return
        try:
            self._render_lifetime_result(
                result, float(self.linewidth_spin.value()),
                self.title_edit.text().strip())
            self.canvas._fit_to_widget()
            self.canvas.draw()
            self.lifetime_canvas._fit_to_widget()
            self.lifetime_canvas.draw()
            if hasattr(self, 'diag_canvas'):
                self.diag_canvas._fit_to_widget()
                self.diag_canvas.draw()
        except Exception as e:
            log_exception("按外观参数重画寿命拟合结果失败", e)

    def _render_lifetime_result(self, result, linewidth, custom_title=""):
        """把一份拟合结果（serialize dict）画到主画布（拟合+残差）与「寿命分布」标签页"""
        self._last_lifetime_result = result  # 供信息页/导出使用

        # 真正出图前才清画布（D5：取消拟合时不能清，否则上次结果消失）
        self.canvas.clear_fig()

        # ---- 主画布：上=拟合曲线（log），下=残差，共享横轴 ----
        info = result['info']
        file_name = result.get('name', '')
        time = np.asarray(result['time'], dtype=float)
        decay = np.asarray(result['decay'], dtype=float)
        irf_shifted = np.asarray(info['irf_shifted'], dtype=float)
        y_fitted = np.asarray(info['y_fitted'], dtype=float)
        residuals = np.asarray(info['residuals'], dtype=float)
        fit_time = time[info['fit_start']:info['fit_end']]
        dt = time[1] - time[0] if len(time) > 1 else 1.0
        qshift_ns = info['qshift_suggested'] * dt
        chi2 = info['chi_sqr']

        # v4.39：时间轴与 τ 按「时间单位」全局设置显示（内部仍是 ns）
        ltu = float(getattr(self, 'lifetime_unit_factor', 1.0) or 1.0)
        lts = getattr(self, 'lifetime_unit_symbol', 'ns')
        time_d = time / ltu                     # 显示用时间轴
        fit_time_d = fit_time / ltu
        qshift_disp = qshift_ns / ltu
        # 注意：**只换算"时间"量**（横轴 / qshift / τ）。IRF 与衰减、拟合曲线都是
        # 强度（counts），绝不能除以单位因子——否则 log 轴下曲线会掉到 ylim 以下
        # 整条看不见（v4.39 初版把 irf_shifted 也除了 1000，μs 模式下 IRF 消失）。

        fig = self.canvas.fig
        gs = GridSpec(2, 1, height_ratios=[7, 3])
        ax1 = fig.add_subplot(gs[0])

        # v5.0.2：颜色改从主题取。此前是硬编码的 #66ccee/#ccbb44/#ee6677，
        # 只按「深色够亮」挑过，没对白底核算：对 #ffffff 只有 1.84/1.95/3.09:1，
        # 低于图形元素 3:1 门槛，浅色与打印友好主题下散点和 IRF 几乎看不见。
        _LC = self._mpl_colors()
        n_fit = max(int(info['fit_end']) - int(info['fit_start']), 1)
        ax1.scatter(time_d, decay, s=2, alpha=0.6, marker='o',
                    edgecolors='none', color=_LC['life_data'],
                    label='实验数据')
        ax1.plot(time_d, irf_shifted, linewidth=0.8, color=_LC['life_irf'],
                 label=f'IRF（平移 {self._fmt_shift(qshift_disp)} {lts}）')
        ax1.plot(fit_time_d, y_fitted, linewidth=max(1.0, linewidth),
                 color=_LC['life_fit'], label=f"{info.get('method', 'MEM')} 拟合")
        ax1.set_yscale('log')
        ax1.set_ylim(bottom=1)
        # v5.0.2：log 轴的上限显式按数据定，不吃 matplotlib 的自动缩放。
        # 原因：IRF 是高斯型，两翼会衰减到 ≈0 的正数；log 轴自动缩放遇到
        # 「下限被 ylim(bottom=1) 钉死、数据又趋近 0」会给出荒谬的上界
        # （实测 5.97e19，纵轴跨 19 个数量级，衰减曲线被压成一条贴 1e3 的
        # 直线，寿命图完全读不出来）。上限取所有曲线最大值的 3 倍即可。
        try:
            _all_y = [np.asarray(decay, dtype=float),
                      np.asarray(irf_shifted, dtype=float),
                      np.asarray(y_fitted, dtype=float)]
            _pos = [a[a > 0] for a in _all_y if np.size(a)]
            _ymax = max((float(np.nanmax(a)) for a in _pos if a.size),
                        default=1.0)
            if np.isfinite(_ymax) and _ymax > 1:
                ax1.set_ylim(1.0, _ymax * 3.0)
        except Exception as e:
            logging.debug("设定寿命主轴 y 上限失败，保留自动缩放: %s", e)
        ax1.set_ylabel('Counts (log)')
        ax1.legend(fontsize=9)
        ax1.set_title(custom_title or f"荧光寿命拟合 - {file_name}", fontsize=13)
        # 拟合窗口画成浅色阴影带：即使不看诊断页也知道"哪一段参与了拟合"
        try:
            ax1.axvspan(fit_time_d[0], fit_time_d[-1],
                        color=_LC['life_mark'], alpha=0.07, zorder=0,
                        label='拟合窗口')
        except Exception:
            pass

        # v5.0.2：按拟合区间裁时间轴。此前直接用原始通道全长的 xlim，Ce6 数据
        # 轴 0–399 900 ns 而拟合只用 23 300–89 400 ns，图上右侧 78% 的面积全是
        # 平的噪声地板，衰减曲线被挤在左边不到 1/4，IRF 只剩一条竖线。
        # 前留 15%（看清基线）、后留 40%（看清衰减拖尾），至少各留 20 个点。
        _pad_lo = max(int(0.15 * n_fit), 20)
        _pad_hi = max(int(0.40 * n_fit), 20)
        _i_lo = max(0, int(info['fit_start']) - _pad_lo)
        _i_hi = min(len(time_d) - 1, int(info['fit_end']) + _pad_hi)
        if _i_hi > _i_lo:
            ax1.set_xlim(time_d[_i_lo], time_d[_i_hi])
        # ⚠️ 只锁 X，**不要** set_autoscale_on(False)：那会在 y 自动缩放尚未
        # 计算时就把它冻住（matplotlib 是延到绘制时才算的），log 轴于是从默认
        # 区间 (0,1) 推出 1e0–1e18 —— 实测纵轴跨 18 个数量级、曲线被压成一条
        # 贴在 1e3 的直线。set_xlim 本身已经关掉 X 的自动缩放，Y 交给它自己算。

        ax2 = fig.add_subplot(gs[1], sharex=ax1)
        ax2.plot(fit_time_d, residuals, linewidth=0.3, color=_LC['life_fit'])
        ax2.axhline(0, color=self._mpl_colors()['zero'], linewidth=0.5)
        ax2.set_xlabel(f'Time ({lts})')
        ax2.set_ylabel('残差')
        # 数值框底色随主题（原为白底：深色主题下浅色文字压在白底上看不见）
        _C = self._mpl_colors()
        ax2.text(0.97, 0.9, r'$\chi_{\rm R}^2 = ' + f'{chi2:.4g}$',
                 ha='right', va='top', transform=ax2.transAxes,
                 color=_C['note_fg'],
                 bbox=dict(boxstyle='square,pad=0.3', edgecolor='none',
                           facecolor=_C['note_bg']))

        # MplCanvas 初始把子图边距设为 0（提示文字铺满用），清空画布后不会自动恢复；
        # 不在这里显式恢复边距的话，坐标轴标签会被裁在图外（左轴内容看不到）
        fig.subplots_adjust(left=0.10, right=0.97, top=0.93, bottom=0.14)
        self._fit_left_margin(fig, ax1, base=0.10)

        # ---- 副画布（「寿命分布」标签页）：寿命分布单独一张图 ----
        dfig = self.lifetime_canvas.fig
        dfig.clf()
        ax3 = dfig.add_subplot(111)
        k = np.asarray(result['k'], dtype=float)
        dist = np.asarray(result['k_distribution'], dtype=float)
        tau = 1.0 / np.maximum(k, 1e-12)
        tau_d = tau / ltu                       # 显示单位下的 τ 轴
        # 曲线颜色随主题（原为黑色：深色主题下黑线压在深底上完全看不见）
        ax3.plot(tau_d, dist, linewidth=0.8, color=self._mpl_colors()['fg'],
                 label='MEM 分布')
        ax3.set_xscale('log')
        if dist.max() > 0:
            ax3.set_ylim(top=dist.max() * 1.4)
        # v5.0.2：按分布质量分位裁 τ 轴。τ 网格默认 0.01–100 ns 跨 4 个数量级，
        # 而 Ce6 的 MEM 分布 99% 质量只落在 69.2–100 ns（0.16 个数量级）——
        # 图上左边 99% 的横轴是紧贴零线的一条直线，真正的峰挤在最右端贴着边框。
        # 取 0.2% / 99.8% 分位各放宽 2 倍，最多仍保留原始网格范围。
        try:
            _d = np.asarray(dist, dtype=float)
            _tot = float(np.nansum(_d))
            if _tot > 0 and np.isfinite(_tot) and tau_d.size > 4:
                _cdf = np.cumsum(np.nan_to_num(_d, nan=0.0)) / _tot
                _lo = float(tau_d[min(int(np.searchsorted(_cdf, 0.002)),
                                      tau_d.size - 1)])
                _hi = float(tau_d[min(int(np.searchsorted(_cdf, 0.998)),
                                      tau_d.size - 1)])
                _lo, _hi = min(_lo, _hi), max(_lo, _hi)
                if _lo > 0 and _hi > _lo:
                    _g_lo = float(np.min(tau_d[tau_d > 0])) if np.any(tau_d > 0) else _lo
                    _g_hi = float(np.max(tau_d))
                    ax3.set_xlim(max(_g_lo, _lo / 2.0), min(_g_hi, _hi * 2.0))
        except Exception as e:
            logging.debug("按分布质量裁 τ 轴失败，保留默认范围: %s", e)
        ax3.set_xlabel(rf'$\tau$ ({lts})')
        ax3.set_ylabel('分布强度')
        ax3.set_title(f"{custom_title} - 寿命分布" if custom_title
                      else f"寿命分布 - {file_name}", fontsize=12)
        peak_fit = info.get('peak_fit')
        peak_result = result.get('peak_result') or []
        if peak_fit is not None and len(peak_result) > 0:
            weights = np.array([p[3] for p in peak_result], dtype=float)
            weights = weights / max(weights.sum(), 1e-12)
            # 振幅占比（v4.33）：第 5 项；旧结果/旧 json 没有则回退按分量峰高自算
            amps = np.array([p[4] if len(p) > 4 else 0.0 for p in peak_result],
                            dtype=float)
            if not np.any(amps > 0):
                pf = np.asarray(peak_fit, dtype=float)
                amps = pf[:, 0] / max(float(np.max(pf[:, 0])), 1e-12)
            for n, peak in enumerate(np.asarray(peak_fit)):
                comp = peak[0] * np.exp(-((k - peak[1]) / peak[2]) ** 2)
                ax3.fill_between(tau_d, 0, comp, alpha=0.5,
                                 label=(fr'$\tau_{{{n + 1}}} = '
                                        fr'{1 / peak[1] / ltu:.3g}$ {lts}, '
                                        fr'振幅 {amps[n] * 100:.1f}%, '
                                        fr'强度 {weights[n] * 100:.1f}%'))
            ax3.legend(fontsize=8)
        dfig.subplots_adjust(left=0.12, right=0.97, top=0.90, bottom=0.17)
        self._fit_left_margin(dfig, ax3, base=0.12)

        # ---- 第三张画布（「拟合诊断」标签页）：IRF/拟合区间 + 残差自相关 ----
        try:
            self._render_lifetime_diagnostics(result)
        except Exception as e:
            logging.warning("绘制拟合诊断图失败: %s", e)

        return fig

    # ---------- C4/C5：拟合诊断图 + 拟合质量指标 ----------

    @staticmethod
    def _fmt_shift(v):
        """IRF 平移量的可读格式（v5.0.2）。

        此前用 ``:.2g``：qshift = 22.4 ch × 66.9 ns/ch = 1499 ns 被格式化成
        ``2.2e+03``。这是给人看、给人抄的参数，科学计数法既难读也难输。
        现在按量级选：≥1000 用千位分隔（2,240），≥1 用 3 位有效数字，
        极小值退回科学计数法（保持 ≤3 字符宽度，不撑爆图例）。
        """
        try:
            v = float(v)
        except Exception:
            return str(v)
        if not np.isfinite(v):
            return '—'
        a = abs(v)
        if a >= 1000:
            return f"{v:,.0f}"
        if a >= 1:
            return f"{v:.3g}"
        if a == 0:
            return '0'
        return f"{v:.2g}"

    @staticmethod
    def _fit_quality_metrics(result):
        """从拟合结果计算质量指标（C5）。

        返回 dict：npts / chi2 / chi2r / res_mean / res_std / dw /
        acf（残差自相关，滞后 0..N）/ acf_lag1 / acf_ci / pearson_outliers。
        """
        info = result.get('info', {})
        res = np.asarray(info.get('residuals', []), dtype=float)
        y = np.asarray(info.get('y_fitted', []), dtype=float)
        decay = np.asarray(result.get('decay', []), dtype=float)
        fit_start = int(info.get('fit_start', 0))
        fit_end = int(info.get('fit_end', len(res)))
        npts = max(1, fit_end - fit_start)
        # 注意：plot_lifetime 的 info['chi_sqr'] 已经是 χ²/M（分母是点数 M，
        # 不是自由度 ν），也就是主画布上显示的 χ²R；据此还原总量 χ²。
        chi2r = float(info.get('chi_sqr', float('nan')))
        m = {'npts': npts, 'chi2r': chi2r,
             'chi2': chi2r * npts if npts else float('nan'),
             'chi2_type': info.get('chi2_type', 'neyman_obs_denominator_over_M'),
             'chi2r_pearson': float(info.get('chi_sqr_pearson', float('nan')))}

        if res.size:
            r = res - np.mean(res)
            m['res_mean'] = float(np.mean(res))
            m['res_std'] = float(np.std(res))
            denom = max(float(np.sum(res ** 2)), 1e-12)
            m['dw'] = float(np.sum(np.diff(res) ** 2) / denom)
            ac = np.correlate(r, r, mode='full')[r.size - 1:]
            ac = ac / max(float(r @ r), 1e-12)
            m['acf'] = ac[:min(25, ac.size)]
            m['acf_lag1'] = float(ac[1]) if ac.size > 1 else 0.0
            m['acf_ci'] = float(1.96 / np.sqrt(max(res.size, 1)))
            # 离群占比直接用模块给出的残差（Neyman 口径，与 χ²R 同一分母），
            # 旧实现在这里另算一套 Pearson 残差，同一份结果里出现两种定义
            m['residual_outliers'] = float(np.mean(np.abs(res) > 3))
        return m

    def _render_lifetime_diagnostics(self, result):
        """把 IRF/拟合区间与残差自相关画到「拟合诊断」标签页（C4 + C5）。"""
        if not hasattr(self, 'diag_canvas'):
            return
        info = result['info']
        time = np.asarray(result['time'], dtype=float)
        decay = np.asarray(result['decay'], dtype=float)
        irf = np.asarray(result.get('irf', []), dtype=float)
        irf_shifted = np.asarray(info.get('irf_shifted', []), dtype=float)
        y_fitted = np.asarray(info.get('y_fitted', []), dtype=float)
        fit_start = int(info.get('fit_start', 0))
        fit_end = int(info.get('fit_end', len(decay)))
        dt = float(time[1] - time[0]) if len(time) > 1 else 1.0
        qshift = float(info.get('qshift_suggested', 0.0))
        metrics = self._fit_quality_metrics(result)

        # v4.39：诊断页的时间轴同样跟随「时间单位」全局设置
        ltu = float(getattr(self, 'lifetime_unit_factor', 1.0) or 1.0)
        lts = getattr(self, 'lifetime_unit_symbol', 'ns')
        time_d = time / ltu

        fig = self.diag_canvas.fig
        fig.clf()
        # v5.0.2：两图间距从 0.35 提到 0.55。原值下图 xlabel 的 bbox 是
        # y=(239,255)、上图（残差自相关）title 的 bbox 是 y=(222,239)，
        # **间距 0 px** —— 两行字上下紧贴，视觉上糊成一句乱文。
        gs = GridSpec(2, 1, height_ratios=[3, 2], hspace=0.55)
        ax1 = fig.add_subplot(gs[0])
        ax2 = fig.add_subplot(gs[1])

        # 辅助元素按主题取色（v5.0.2：改从 THEMES 的 MPL_LIFE_* 取。
        # 原先是硬编码。注意旧实现的判据是 `theme == 'dark'` 二分支，
        # 而仓库有**三套**主题——contrast（打印友好）走的是 light 分支，
        # 但它的语义要求更高对比度，二分支根本表达不出来。）
        _LC = self._mpl_colors()
        c_irf_raw = _LC['life_irf_raw']
        c_marker = _LC['life_mark']
        c_acf = _LC['life_acf']
        c_ci = _LC['life_ci']

        # ---- 上：IRF（原始/平移后）+ 衰减 + 拟合区间 ----
        scale = float(np.nanmax(decay)) if decay.size else 0.0
        scale = scale if scale > 0 else 1.0

        def _n(a):
            return a / scale

        if irf.size:
            irf_s = _n(irf)
            ax1.plot(time_d[:len(irf)], irf_s, linewidth=0.9, color=c_irf_raw,
                     label='IRF（原始）')
        if irf_shifted.size:
            ax1.plot(time_d[:len(irf_shifted)], _n(irf_shifted), linewidth=0.9,
                     color=_LC['life_irf'],
                     label=f'IRF（平移 {self._fmt_shift(qshift)} ch = '
                           f'{self._fmt_shift(qshift * dt / ltu)} {lts}）')
        ax1.plot(time_d, _n(decay), linewidth=0.8, color=_LC['life_data'],
                 label='衰减数据')
        if y_fitted.size:
            ax1.plot(time_d[fit_start:fit_start + len(y_fitted)], _n(y_fitted),
                     linewidth=1.1, color=_LC['life_fit'], label='拟合')
        # v5.0.2：两个标注重叠时上下错开。拟合区间相对全长常常很窄
        # （实测 233–894 ch 落在 0–400000 ns 上，只占左边 22%），两个文字
        # 会挤成「拟合起..合终点」读不出来。
        # 判据不依赖 transData（出图前画布还没拿到真实尺寸，换算出来的像素
        # 距离不可靠——实测同一条轴上"出图前算 104 px、draw 后算 104 px"却
        # 给出了相反的判定）。改用**数据尺度**：拟合区间跨度占全时间轴的
        # 比例小于 35% 时，两个 4 字标注（约 100 px @ 900 px 宽画布）必然相撞。
        _x_start = time_d[fit_start]
        _x_end = time_d[min(fit_end, len(time) - 1)]
        _t_lo = float(np.nanmin(time_d)) if time_d.size else 0.0
        _t_hi = float(np.nanmax(time_d)) if time_d.size else 1.0
        _total = (_t_hi - _t_lo) or 1.0
        _too_close = abs(_x_end - _x_start) < 0.35 * _total
        for x, lab, ha, ypos in (
                (_x_start, '拟合起点', 'left', 0.94),
                (_x_end, '拟合终点', 'right', 0.80 if _too_close else 0.94)):
            ax1.axvline(x, color=c_marker, linestyle='--', linewidth=0.8)
            ax1.annotate(lab, xy=(x, ypos), xycoords=('data', 'axes fraction'),
                         xytext=(4 if ha == 'left' else -4, 0),
                         textcoords='offset points',
                         ha=ha, va='top', fontsize=9, color=c_marker)
        # v5.0.2：上图不再单独给 xlabel —— 它与下图标题只隔 0.55 行距，
        # 此前就是"上图 xlabel"压"下图 title"（间距实测 0 px）。上图有标题
        # 「IRF / 拟合区间诊断」已足够说明内容，横轴量纲由下图 xlabel 承担。
        ax1.set_ylabel('归一化强度')
        ax1.set_title('IRF / 拟合区间诊断', fontsize=12)
        ax1.legend(fontsize=8, loc='upper right')
        self._grid(ax1, dashed=True)

        # ---- 下：残差自相关 ----
        acf = metrics.get('acf')
        if acf is not None and len(acf) > 1:
            lag = np.arange(len(acf))
            ax2.bar(lag, acf, width=0.7, color=c_acf, alpha=0.75)
            ci = metrics.get('acf_ci', 0.0)
            ax2.axhline(ci, color=c_ci, linestyle='--', linewidth=0.8)
            ax2.axhline(-ci, color=c_ci, linestyle='--', linewidth=0.8)
            ax2.axhline(0, color=self._mpl_colors()['zero'], linewidth=0.5)
            n_exceed = int(np.sum(np.abs(acf[1:]) > ci))
            # 标题缩短：原字符串带「→ 越多说明残差越有结构」，宽度接近整张画布，
            # 既压上图 xlabel 又在窄画布上被裁掉。判读口径移到 ylabel 旁说明。
            ax2.set_title(
                f"残差自相关（|ACF| > {ci:.3g} 的超限滞后点：{n_exceed} 个）",
                fontsize=11)
        else:
            ax2.text(0.5, 0.5, "无残差数据", ha='center', va='center',
                     transform=ax2.transAxes,
                     color=self._mpl_colors()['muted'])
        ax2.set_xlabel(f'滞后 (通道)　横轴 = 滞后阶数，纵轴 = 自相关；'
                       f'超出虚线带的滞后点越多，说明残差越有结构')
        ax2.set_ylabel('ACF')
        self._grid(ax2, dashed=True)

        fig.subplots_adjust(left=0.10, right=0.97, top=0.93, bottom=0.11)
        self._fit_left_margin(fig, ax1, base=0.10)

    def _show_lifetime_fit_info(self):
        """把最近一次寿命拟合的结果写入信息页（主线程调用）"""
        result = getattr(self, '_last_lifetime_result', None)
        if not result:
            return
        info = result['info']
        lines = [f"文件名: {result.get('name', '')}", ""]
        # v4.39：信息页里的时间/寿命数值按「时间单位」显示（内部仍是 ns）
        ltu = float(getattr(self, 'lifetime_unit_factor', 1.0) or 1.0)
        lts = getattr(self, 'lifetime_unit_symbol', 'ns')
        lines.append(f"拟合方法: {info.get('method', 'MEM')}")
        lines.append(f"简化卡方 χ²R = {info['chi_sqr']:.4g}")
        # v4.32：数据被归一化过时，程序会自动还原到计数刻度再拟合。
        # 这会影响拟合窗口与 χ²R 的绝对量级，必须让用户看得见，不能静默发生。
        if info.get('rescaled_from_normalized'):
            lines.append(
                f"⚠ 输入为归一化数据（衰减峰值 "
                f"{info.get('decay_peak_before_rescale', float('nan')):.4g}），"
                f"已 ×{info.get('rescale_factor', float('nan')):.4g} 还原到计数刻度"
                f"（峰值 → {info.get('decay_max', float('nan')):.4g}）；"
                "该换算只恢复噪声判据的物理量级，不改动 τ")
        lam_mode = '自动拟合' if info.get('lambda_auto') else '手动'
        lambda_used = info.get('lambda_coeff_used', info.get('lambda_coeff'))
        lines.append(f"熵权重 λ = {lambda_used:.5g}（{lam_mode}）")
        if info.get('lambda_auto'):
            grid = info.get('lambda_scan_grid') or []
            lines.append(f"λ 扫描: {len(grid)} 个网格点 "
                         f"{min(grid) if grid else 0:.2g} – "
                         f"{max(grid) if grid else 0:.2g}，"
                         f"取 χ²R ≤ {info.get('lambda_target', 1.1):.2g} 的最大 λ")
        dt = (np.asarray(result['time'])[1] - np.asarray(result['time'])[0]
              if len(result['time']) > 1 else 1.0)
        lines.append(f"IRF 位移 qshift = {info['qshift_suggested']:.4g} ch"
                     f"（{info['qshift_suggested'] * dt / ltu:.4g} {lts}）")
        lines.append(f"IRF FWHM = {info.get('irf_FWHM', float('nan')) / ltu:.4g} {lts}")
        lines.append("")
        peaks = result.get('peak_result') or []
        if peaks:
            lines.append(f"检测到 {len(peaks)} 个寿命分量:")
            for n, p in enumerate(peaks, 1):
                tau, area = float(p[0]), float(p[1])
                amp = (float(p[4]) if len(p) > 4 else float('nan'))
                amp_txt = f"，振幅占比 = {amp * 100:.2f}%" if np.isfinite(amp) else ""
                lines.append(f"  τ{n} = {tau / ltu:.4g} {lts}, "
                             f"强度占比 = {area * 100:.2f}%{amp_txt}")
            lines.append("（强度占比 = 发光强度贡献，各分量和 100%；"
                         "振幅占比 = 分量峰高，按最大者归一）")
        else:
            lines.append("未分离出明显寿命分量（分布过宽）")
        fixed = info.get('fixed_taus') or []
        if fixed:
            amps = info.get('fixed_amplitudes') or []
            lines.append("")
            lines.append("固定分量（不受熵约束，幅度自动求解）:")
            for t, a in zip(fixed, amps):
                lines.append(f"  τ = {t / ltu:.4g} {lts}，幅度 = {a:.4g} counts")
        lines.append("")
        # ---- 拟合质量报告（C5）----
        m = self._fit_quality_metrics(result)
        lines.append("— 拟合质量 —")
        lines.append(f"拟合点数 M = {m['npts']}（本程序的 χ²R 分母口径是 M，不是自由度 ν）")
        lines.append(f"χ²R = {m['chi2r']:.4g}（χ² = {m['chi2']:.4g}）")
        if np.isfinite(m.get('chi2r_pearson', float('nan'))):
            lines.append(f"  · 同数据 Pearson 口径 χ²R = {m['chi2r_pearson']:.4g}"
                         "（分母取模型值，供与文献对照）")
        if 'dw' in m:
            dw_note = ('残差有正相关/模型不足' if m['dw'] < 1.5
                       else '残差无明显自相关')
            lines.append(f"Durbin–Watson = {m['dw']:.3f}（{dw_note}）")
            lines.append(f"残差均值 / 标准差 = {m['res_mean']:.3g} / {m['res_std']:.3g}")
            lines.append(f"残差自相关 lag1 = {m['acf_lag1']:.3f}"
                         f"（95% 置信带 ±{m['acf_ci']:.3g}）")
        if 'residual_outliers' in m:
            lines.append(f"残差 |r| > 3 的通道占比 = "
                         f"{m['residual_outliers'] * 100:.2f}%"
                         "（与 χ²R 同一残差口径）")
        if info.get('quality') and info['quality'] != 'ok':
            notes = '；'.join(info.get('quality_notes', [])) or '见日志'
            lines.append(f"⚠️ 拟合质量：{info['quality'].upper()} —— {notes}")
        if info.get('peaks_dropped'):
            lines.append(f"⚠️ 有 {info['peaks_dropped']} 个分量因超出 max_peaks 被丢弃")
        if info.get('intensity_share_grid_edges', 0) > 0.05:
            lines.append(f"⚠️ {info['intensity_share_grid_edges'] * 100:.1f}% 的发光强度"
                         "落在寿命范围两端（可能为边界堆积，建议放宽 τ 范围复算）")
        kmin, kmax = info.get('k_min'), info.get('k_max')
        if kmin and kmax:
            lines.append(f"寿命范围 τ = {info.get('tau_max_ns', 0) / ltu:.4g}–"
                         f"{info.get('tau_min_ns', 0) / ltu:.4g} {lts}"
                         f"（速率网格 k = {kmin:g}–{kmax:g} /ns），"
                         f"{info.get('n_rates', 0)} 点")
        lines.append("IRF 平移 / 拟合区间 / 残差自相关见「拟合诊断」标签页")
        lines.append("")
        lines.append("点「导出图片」保存预览图；「导出当前拟合结果」出汇总表+报告")
        self.info_label.setText("\n".join(lines))
        # v4.27：信息页的「拟合摘要」卡片（分量表 + 质量徽标）
        self._update_info_fit_card(result)

    # ---------- 信息页「拟合摘要」卡片（v4.27）----------

    # 拟合质量 → 徽标状态（plot_lifetime 的 quality：ok / poor / failed）
    _QUALITY_BADGE = {
        'ok': ('ok', 'ok'),
        'poor': ('poor', 'warn'),
        'failed': ('failed', 'bad'),
    }

    def _update_info_fit_card(self, result=None):
        """把拟合结果写进信息页的「拟合摘要」卡片（主线程调用，v4.27）。

        卡片内容：质量徽标（ok/poor/failed）+ 一句话摘要 + 寿命分量表（τ / 占比）。
        没有结果时整张卡片隐藏（包括它占的空间）。
        """
        card = getattr(self, 'fit_card', None)
        if card is None:
            return
        if result is None:
            result = getattr(self, '_last_lifetime_result', None)
        if not result:
            card.setVisible(False)
            return
        try:
            info = result.get('info', {}) or {}
            m = self._fit_quality_metrics(result)
            quality = str(info.get('quality', 'ok') or 'ok')
            label, state = self._QUALITY_BADGE.get(quality, (quality, 'warn'))
            self.fit_badge.setText(f"拟合质量 {label}")
            self.set_badge_state(self.fit_badge, state)

            chi2r = m.get('chi2r', float('nan'))
            bits = [f"χ²R = {chi2r:.3g}" if np.isfinite(chi2r) else "χ²R 非有限"]
            bits.append(f"拟合点数 M = {m.get('npts', 0)}")
            if 'dw' in m:
                bits.append(f"Durbin–Watson = {m['dw']:.2f}")
            notes = info.get('quality_notes') or []
            if quality != 'ok' and notes:
                bits.append("；".join(str(n) for n in notes))
            self.fit_quality_label.setText(" · ".join(bits))

            peaks = result.get('peak_result') or []
            fixed = info.get('fixed_taus') or []
            # v4.39：卡片里的 τ 数值按「时间单位」显示（表头见 _update_info_fit_card 的调用方）
            ltu = float(getattr(self, 'lifetime_unit_factor', 1.0) or 1.0)

            def _amp_of(p):
                """振幅占比：第 5 项（v4.33 新增）；旧结果没有 → nan。"""
                return float(p[4]) * 100.0 if len(p) > 4 else float('nan')

            rows = [(f"τ{n}", float(p[0]) / ltu, float(p[1]) * 100.0, _amp_of(p))
                    for n, p in enumerate(peaks, 1)]
            for t in fixed:                      # 固定分量单独标注，避免与分离峰混看
                rows.append((f"固定 τ = {t / ltu:.4g}", float(t) / ltu,
                             float('nan'), float('nan')))

            table = getattr(self, 'fit_table', None)
            if table is not None:
                try:
                    table.setSortingEnabled(False)
                    table.clearContents()
                    table.setRowCount(len(rows))
                    for r, (name, tau, share, amp) in enumerate(rows):
                        table.setItem(r, 0, QTableWidgetItem(str(name)))
                        for col, val in ((1, tau), (2, share), (3, amp)):
                            item = (NumericTableItem(f"{val:.4g}") if col == 1
                                    else QTableWidgetItem(
                                        "—" if not np.isfinite(val) else f"{val:.2f}"))
                            item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                            table.setItem(r, col, item)
                finally:
                    table.setSortingEnabled(True)
                # 重新打开排序会按“当前排序指示器”自动排一遍，行序就不可控了；
                # 这里显式按分量列排，保证默认是 τ1 / τ2 / … / 固定分量 的自然顺序
                table.sortItems(0, Qt.AscendingOrder)
            card.setVisible(True)
        except Exception as e:
            log_exception("填充拟合摘要卡片失败", e)

    # ---------- 荧光寿命拟合结果导出（表格 + 单文件报告） ----------

    def _export_lifetime_fit_results(self):
        """导出当前拟合结果（CSV/XLSX 汇总表 + 该文件的 md 报告；仅寿命模式）。"""
        try:
            import plot_lifetime as _pl
            results = getattr(self, '_last_lifetime_result', None)
            results = [results] if results else []
            if not results:
                QMessageBox.warning(self, "提示",
                                    "请先在寿命模式下预览 / 拟合一个文件")
                return

            # getExistingDirectory 的目录参数必须是 str（current_folder 是 Path）；
            # 起始目录与「选择文件夹」一致（E4）
            default_dir = self._dialog_start_dir()
            save_dir = QFileDialog.getExistingDirectory(
                self, "选择拟合结果保存目录", default_dir)
            if not save_dir:
                return

            written = _pl.export_fit_results(
                results, save_dir, name="lifetime_fit_results",
                time_unit=getattr(self, 'lifetime_unit', 'ns'))
            if not written:
                QMessageBox.warning(self, "提示", "没有可导出的拟合结果")
                return
            QMessageBox.information(
                self, "成功",
                "已导出拟合结果:\n" + "\n".join(written))
            self.status_bar.showMessage(
                f"已导出拟合结果到: {save_dir}（{len(written)} 个文件）")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"导出失败: {str(e)}")

    def _plot_diff(self, linewidth, mark_peaks, peak_height, peak_distance,
                   color_map, custom_title="", xlim=None, sub_cfg=None):
        """绘制两光谱相减的差谱（A − B；波长网格不齐时插值对齐并取重叠区间）"""
        ax = self.canvas.axes
        if not sub_cfg:
            return
        name_a, name_b = sub_cfg['a'], sub_cfg['b']
        data_a = self.data_cache[name_a]['data']
        wl_a, y_a = self._extract_xy(data_a)
        try:
            wl, y = self._subtract_ref(wl_a, y_a, name_b)
        except ValueError as e:
            # 画布写原因，同时记进跳过清单让状态栏也说明（v4.36）
            if getattr(self, '_subtract_skipped', None) is None:
                self._subtract_skipped = []
            self._subtract_skipped.append((f"{name_a} − {name_b}", str(e)))
            ax.text(0.5, 0.5, str(e), transform=ax.transAxes,
                    ha='center', va='center', fontsize=13,
                    color=self._mpl_colors()['muted'])
            return

        name_a_disp = self._sample_name(name_a, data_a)
        name_b_disp = self._sample_name(name_b)
        colors = self._palette(color_map, 3)
        ax.plot(wl, y, linewidth=linewidth, color=colors[0],
                label=f"{name_a_disp} − {name_b_disp}")

        # 标记差谱上的峰（发射用 find_peaks，吸收沿用 find_absorption_peaks）
        if mark_peaks:
            _diff_label = f"{name_a_disp} − {name_b_disp}"
            try:
                if self.spectrum_type == 'emission':
                    y_scale = np.nanmax(np.abs(y))
                    if y_scale > 0:
                        peaks, _ = find_peaks(
                            np.abs(y), height=y_scale * peak_height,
                            distance=peak_distance, prominence=y_scale * 0.03)
                        for pw, pi in zip(wl[peaks], y[peaks]):
                            self._add_peak(_diff_label, pw, pi)
                            self._annotate_peak(ax, pw, pi, xytext=(0, 5),
                                                textcoords='offset points', fontsize=9,
                                                color=colors[0], ha='center', va='bottom')
                else:
                    temp_data = {'wl': wl, 'absorption': y}
                    peaks = find_absorption_peaks(temp_data, min_height=peak_height,
                                                  min_distance=peak_distance)
                    for pw, pi in zip(peaks.get('peak_wavelengths', []),
                                      peaks.get('peak_intensities', [])):
                        self._add_peak(_diff_label, pw, pi)
                        self._annotate_peak(ax, pw, pi, xytext=(0, 6),
                                            textcoords='offset points', fontsize=11,
                                            color=colors[0], ha='center', va='bottom',
                                            fontweight='bold')
            except Exception:
                pass

        if custom_title:
            ax.set_title(custom_title, fontsize=13)
        else:
            ax.set_title(f"{self._type_prefix()}光谱相减 - {name_a_disp} − {name_b_disp}",
                         fontsize=13)
        ax.set_xlabel("波长 (nm)")
        ax.set_ylabel(self._get_y_label())
        ax.axhline(0, color=self._mpl_colors()['zero'], linewidth=0.6, alpha=0.5)
        self._apply_legend(ax)
        self._grid(ax)
        if xlim:
            self._apply_xlim(ax, xlim)

    def _plot_combined(self, linewidth, mark_peaks, peak_height, peak_distance, color_map, custom_title="", xlim=None, sub_cfg=None):
        """绘制合并图（仅绘制勾选的数据，风格与plot_emission一致）"""
        ax = self.canvas.axes

        # 只绘制勾选的文件
        checked_files = self.get_checked_files()
        if not checked_files:
            ax.text(0.5, 0.5, "请勾选至少一个文件", transform=ax.transAxes,
                    ha='center', va='center', fontsize=14,
                    color=self._mpl_colors()['muted'])
            return

        valid_files = [f for f in checked_files if f in self.data_cache]
        if sub_cfg:
            # 扣除本底模式下本底文件自身不再绘制
            valid_files = [f for f in valid_files if f != sub_cfg['b']]
        if not valid_files:
            ax.text(0.5, 0.5, "没有可用的数据", transform=ax.transAxes,
                    ha='center', va='center', fontsize=14,
                    color=self._mpl_colors()['muted'])
            return

        # 按文件身份取色：增删/勾选其它文件时，已有曲线的颜色保持不变
        colors = self._stable_colors(valid_files, color_map)
        # v4.46：批量生成去重标签，避免图例出现多条完全相同的文字
        labels = self._legend_labels_for(valid_files)

        # v4.46：曲线多时只给最强的那条标峰（理由见循环内注释）
        top_curve_idx = -1
        if mark_peaks and len(valid_files) > 6:
            best = -np.inf
            for j, fn in enumerate(valid_files):
                xyj, _rj = self._get_plot_xy_checked(fn, sub_cfg)
                if xyj is None:
                    continue
                try:
                    m = float(np.nanmax(xyj[1]))
                except Exception:
                    continue
                if np.isfinite(m) and m > best:
                    best, top_curve_idx = m, j

        for i, file_name in enumerate(valid_files):
            data = self.data_cache[file_name]['data']
            xy, _reason = self._get_plot_xy_checked(file_name, sub_cfg)
            if xy is None:
                continue          # 扣不了本底的那条只跳过自己（v4.36）
            wavelength, absorption = xy

            ax.plot(wavelength, absorption,
                    label=labels[i] if i < len(labels)
                    else self._build_legend_label(file_name, data),
                    linewidth=linewidth,
                    color=colors[i])

            # 标记峰（annotate 标注，与 plot_emission 一致）
            if mark_peaks:
                temp_data = {'wl': wavelength, 'absorption': absorption}
                peaks = find_absorption_peaks(temp_data,
                                              min_height=peak_height,
                                              min_distance=peak_distance)
                if 'peak_wavelengths' in peaks and 'peak_intensities' in peaks:
                    peak_wls = peaks['peak_wavelengths']
                    peak_intens = peaks['peak_intensities']
                    # 峰表记录**全部检出的峰**（下面裁剪之前）。
                    # v5.0.2：这里的裁剪是为「标注不糊成一团」做的**显示优化**
                    # （v4.46：曲线多时只标最强那条；单条也常只标最强一个，
                    # 因为每条曲线的峰位往往重合）。但峰表是**数据产物**，
                    # 用户拿它做后续计算，若跟着显示规则一起裁，就会出现
                    # 「这条曲线明明有两个峰，表里只有一行」——比没有表更糟。
                    for _pw, _pi in zip(peak_wls, peak_intens):
                        self._add_peak(self._sample_name(file_name, data),
                                       _pw, _pi)
                    # v4.46：曲线多时只标**最强那条曲线**的峰。
                    # 26 条同类样品峰位几乎重合，逐条标注会让数字堆在一处糊成
                    # 一团（实测 188 对两两重叠）。注意判据是"整体只标一条曲线"，
                    # 而不是"每条曲线少标几个峰"——每条曲线通常就一个峰，
                    # 后者根本减少不了标签总数。
                    if len(valid_files) > 6 and i != top_curve_idx:
                        peak_wls, peak_intens = [], []
                    elif len(peak_intens) > 1:
                        k = int(np.argmax(np.asarray(peak_intens, dtype=float)))
                        peak_wls = [peak_wls[k]]
                        peak_intens = [peak_intens[k]]
                    for pw, pi in zip(peak_wls, peak_intens):
                        self._annotate_peak(
                            ax, pw, pi,
                            xytext=(0, 3),
                            textcoords='offset points',
                            fontsize=9 if len(valid_files) > 6 else 10,
                            color=colors[i],
                            ha='center',
                            va='bottom',
                            rotation=0,
                            alpha=0.9,
                            fontweight='bold' if len(valid_files) > 6 else 'normal',
                        )

        # 标题（自定义或默认）
        if custom_title:
            ax.set_title(custom_title, fontsize=13)
        else:
            ax.set_title("吸收光谱对比", fontsize=13)
        ax.set_xlabel("波长 (nm)")
        ax.set_ylabel("吸收值 (AU)")
        self._apply_legend(ax)
        self._grid(ax)
        if xlim:
            self._apply_xlim(ax, xlim)

    def _plot_single(self, linewidth, mark_peaks, peak_height, peak_distance, color_map, custom_title="", xlim=None, sub_cfg=None):
        """绘制单独图（风格与plot_emission一致）"""
        ax = self.canvas.axes

        # 获取当前选中的文件
        file_name = self._single_plot_target()
        if file_name not in self.data_cache:
            return

        data = self.data_cache[file_name]['data']
        xy, reason = self._get_plot_xy_checked(file_name, sub_cfg)
        if xy is None:
            # 单图模式：把原因写在画布上，不再弹「绘图失败」（v4.36）
            ax.text(0.5, 0.5, f"无法扣除本底：\n{reason}", transform=ax.transAxes,
                    ha='center', va='center', fontsize=13, wrap=True,
                    color=self._mpl_colors()['muted'])
            return
        wavelength, absorption = xy

        # 使用所选颜色方案生成颜色
        colors = self._palette(color_map, 3)

        # 绘制曲线（单图图例显示全部信息：样品名 + 说明信息）
        label = self._build_legend_label(file_name, data, show_all=True)
        ax.plot(wavelength, absorption,
               linewidth=linewidth,
               color=colors[0],
               label=label)

        # 标记峰
        if mark_peaks:
            temp_data = {'wl': wavelength, 'absorption': absorption}
            peaks = find_absorption_peaks(temp_data,
                                          min_height=peak_height,
                                          min_distance=peak_distance)
            # 使用返回的波长和强度数组（annotate 标注，与 plot_emission 一致）
            if 'peak_wavelengths' in peaks and 'peak_intensities' in peaks:
                peak_wls = peaks['peak_wavelengths']
                peak_intens = peaks['peak_intensities']
                _sname = self._sample_name(file_name, data)
                for pw, pi in zip(peak_wls, peak_intens):
                    self._add_peak(_sname, pw, pi)
                    self._annotate_peak(
                        ax, pw, pi,
                        xytext=(0, 6),
                        textcoords='offset points',
                        fontsize=11,
                        color=colors[0],
                        ha='center',
                        va='bottom',
                        rotation=0,
                        alpha=0.9,
                        fontweight='bold',
                    )

        # 标题（自定义或默认；单图标题用样品名，与图例标签无关）
        if custom_title:
            ax.set_title(custom_title, fontsize=13)
        else:
            ax.set_title(f"吸收光谱 - {self._sample_name(file_name, data)}", fontsize=13)
        ax.set_xlabel("波长 (nm)")
        ax.set_ylabel("吸收值 (AU)")
        self._apply_legend(ax)
        self._grid(ax)
        if xlim:
            self._apply_xlim(ax, xlim)

    @staticmethod
    def _normalize_intensity(y):
        """把一条光谱归一化到「峰高 = 1」（v4.44）。

        旧写法是 ``y / np.nanmax(y)``，对**本底没扣干净、带负基线**的谱会爆：
        实测 EtOH 空白谱 min=-66.1 / max=6.04，除完最低到 -10.95，
        整张合并图的纵轴被拉到 (-12.15, 2.2)，真实样品(0~1)只剩 8.4% 图高，
        全被压成贴着零线的细线。

        新口径：先减去最小值（扣掉基线），再除以扣完之后的峰值。
        对本来就是正、基线≈0 的谱，结果与旧口径几乎一致（不影响历史图）；
        对带负基线的谱则保证结果落在 [0, 1] 内，不会被撑爆。
        全常量谱原样返回（归一化无意义）。
        """
        y = np.asarray(y, dtype=float)
        if y.size == 0:
            return y
        finite = np.isfinite(y)
        if not finite.any():
            return y
        lo = float(np.nanmin(y[finite]))
        hi = float(np.nanmax(y[finite]))
        if not np.isfinite(hi - lo) or (hi - lo) <= 0:
            return y
        return (y - lo) / (hi - lo)

    def _plot_emission_combined(self, linewidth, mark_peaks, peak_height, peak_distance, color_map, custom_title="", xlim=None, sub_cfg=None):
        """绘制发射光谱合并图（仅勾选的数据，含峰标注/EX标注，可选归一化）"""
        ax = self.canvas.axes
        checked_files = self.get_checked_files()
        if not checked_files:
            ax.text(0.5, 0.5, "请勾选至少一个文件", transform=ax.transAxes,
                    ha='center', va='center', fontsize=14,
                    color=self._mpl_colors()['muted'])
            return
        valid_files = [f for f in checked_files if f in self.data_cache]
        if sub_cfg:
            # 扣除本底模式下本底文件自身不再绘制
            valid_files = [f for f in valid_files if f != sub_cfg['b']]
        if not valid_files:
            ax.text(0.5, 0.5, "没有可用的数据", transform=ax.transAxes,
                    ha='center', va='center', fontsize=14,
                    color=self._mpl_colors()['muted'])
            return

        # 按文件身份取色：增删/勾选其它文件时，已有曲线的颜色保持不变
        colors = self._stable_colors(valid_files, color_map)
        # v4.46：批量去重标签
        labels = self._legend_labels_for(valid_files)
        normalize = getattr(self, 'normalize_check', None) is not None and self.normalize_check.isChecked()

        # v4.46：曲线多时只给"最强的那条"标峰（见循环内注释）。
        # 先扫一遍找峰高最大的曲线下标。
        top_curve_idx = -1
        if mark_peaks and len(valid_files) > 6:
            best = -np.inf
            for j, fn in enumerate(valid_files):
                xyj, _rj = self._get_plot_xy_checked(fn, sub_cfg)
                if xyj is None:
                    continue
                yj = xyj[1]
                if normalize:
                    yj = self._normalize_intensity(yj)
                try:
                    m = float(np.nanmax(yj))
                except Exception:
                    continue
                if np.isfinite(m) and m > best:
                    best, top_curve_idx = m, j

        for i, file_name in enumerate(valid_files):
            data = self.data_cache[file_name]['data']
            xy, _reason = self._get_plot_xy_checked(file_name, sub_cfg)
            if xy is None:
                continue          # 扣不了本底的那条只跳过自己（v4.36）
            wl, intensity = xy
            # v4.44：改为扣基线后按峰高归一（见 _normalize_intensity 的说明）。
            # 旧口径 y/nanmax(y) 在带负基线的谱上会把纵轴撑到 -12 倍，
            # 所有真实样品被压成贴零线的细线。
            if normalize:
                intensity = self._normalize_intensity(intensity)

            # 图例标签：说明.xlsx 信息或样品名 + EX（v4.46 去重）
            label = (labels[i] if i < len(labels)
                     else self._build_legend_label(file_name, data))
            ex_wl = data.get('ex_wl', data.get('ex'))

            ax.plot(wl, intensity, linewidth=linewidth, color=colors[i], label=label)

            # 标注激发波长竖线
            if getattr(self, 'show_ex_check', None) is not None and self.show_ex_check.isChecked() and ex_wl is not None:
                ax.axvline(ex_wl, color=colors[i], linestyle='--', linewidth=1, alpha=0.5)

            # 峰检测标注（annotate）
            if mark_peaks:
                try:
                    y_max = np.nanmax(intensity)
                    height = y_max * peak_height if y_max > 0 else 0.05
                    peaks, props = find_peaks(
                        intensity, height=height, distance=peak_distance,
                        prominence=y_max * 0.03
                    )
                    # 峰表记录**全部检出的峰**（下面裁剪之前）。
                    # v5.0.2：下面的裁剪是为「标注不糊成一团」做的显示优化；
                    # 峰表是数据产物，跟着裁会变成"曲线有两个峰、表里只有一行"。
                    for _pw, _pi in zip(wl[peaks], intensity[peaks]):
                        self._add_peak(self._sample_name(file_name, data),
                                       _pw, _pi)
                    # v4.46：曲线多时**只给最强的那条曲线标峰**。
                    # 26 条同类样品的峰位几乎重合在同一波长上，逐条标注会让
                    # 26 个数字堆在一处糊成一团（实测 188 对两两重叠，整块不可读）。
                    # 判据：不是"每条曲线保留几个峰"，而是"整体只标一条曲线"——
                    # 因为每条曲线通常只有一个峰，逐条瘦身根本减少不了标签数。
                    if len(valid_files) > 6:
                        is_top = (i == top_curve_idx)
                        if not is_top:
                            peaks = []
                    if len(peaks) > 1:
                        peaks = [int(peaks[int(np.argmax(intensity[peaks]))])]
                    for pw, pi in zip(wl[peaks], intensity[peaks]):
                        self._annotate_peak(ax, pw, pi, xytext=(0, 5),
                                            textcoords='offset points', fontsize=9,
                                            color=colors[i], ha='center', va='bottom',
                                            fontweight='bold' if len(valid_files) > 6 else 'normal')
                except Exception:
                    pass

        if custom_title:
            ax.set_title(custom_title, fontsize=13)
        else:
            ax.set_title("发射光谱对比", fontsize=13)
        ax.set_xlabel("波长 (nm)")
        ax.set_ylabel("归一化强度" if normalize else "发射强度 (AU)")
        self._apply_legend(ax)
        self._grid(ax)
        if xlim:
            self._apply_xlim(ax, xlim)

    def _plot_emission_single(self, linewidth, mark_peaks, peak_height, peak_distance, color_map, custom_title="", xlim=None, sub_cfg=None):
        """绘制发射光谱单独图"""
        ax = self.canvas.axes
        file_name = self._single_plot_target()
        if file_name not in self.data_cache:
            return

        data = self.data_cache[file_name]['data']
        xy, reason = self._get_plot_xy_checked(file_name, sub_cfg)
        if xy is None:
            # 单图模式：把原因写在画布上，不再弹「绘图失败」（v4.36）
            ax.text(0.5, 0.5, f"无法扣除本底：\n{reason}", transform=ax.transAxes,
                    ha='center', va='center', fontsize=13, wrap=True,
                    color=self._mpl_colors()['muted'])
            return
        wl, intensity = xy
        ex_wl = data.get('ex_wl', data.get('ex'))
        # 图例标签：单图显示全部信息（样品名 + 说明信息）+ EX
        label = self._build_legend_label(file_name, data, show_all=True)

        colors = self._palette(color_map, 3)
        ax.plot(wl, intensity, linewidth=linewidth, color=colors[0], label=label)

        if getattr(self, 'show_ex_check', None) is not None and self.show_ex_check.isChecked() and ex_wl is not None:
            ax.axvline(ex_wl, color=colors[1], linestyle='--', linewidth=1.2, alpha=0.8, label=f"EX={ex_wl:.0f} nm")

        if mark_peaks:
            try:
                y_max = np.nanmax(intensity)
                height = y_max * peak_height if y_max > 0 else 0.05
                peaks, props = find_peaks(intensity, height=height, distance=peak_distance,
                                          prominence=y_max * 0.03)
                for pw, pi in zip(wl[peaks], intensity[peaks]):
                    self._add_peak(self._sample_name(file_name, data), pw, pi)
                    self._annotate_peak(ax, pw, pi, xytext=(0, 8),
                                        textcoords='offset points', fontsize=11,
                                        color=colors[0], ha='center', va='bottom',
                                        fontweight='bold')
            except Exception:
                pass

        if custom_title:
            ax.set_title(custom_title, fontsize=13)
        else:
            ax.set_title(f"发射光谱 - {self._sample_name(file_name, data)}", fontsize=13)
        ax.set_xlabel("波长 (nm)")
        ax.set_ylabel("发射强度 (AU)")
        self._apply_legend(ax)
        self._grid(ax)
        if xlim:
            self._apply_xlim(ax, xlim)

    def _on_plot_finished(self, fig, gen=None):
        """绘图完成回调（主线程）。

        v4.45：``gen`` 是发起本次任务时的代次。切模式/换文件夹/取消都会递增
        代次，于是**过期任务的结果被直接丢弃**——不再出现「旧线程算完后把
        寿命拟合图画到吸收模式画布上」。gen 为 None 时按当前任务处理（兼容
        回归测试直接调用本函数）。
        """
        if self._is_stale(gen):
            logging.info("丢弃过期的绘图结果（代次 %s，当前 %s）",
                         gen, getattr(self, '_plot_gen', None))
            return
        cancelled = getattr(self, '_fit_cancelled', False)
        self._fit_cancelled = False
        self._plotting = False
        self._long_task = False
        # D4：清忙标记并补一次绘制（后台线程绘制期间画布跳过了缩放重绘）
        self._set_canvas_busy(False)
        self._close_progress_dialog()
        # D5：用户取消了拟合——不弹错误框，只改文案，保留上一次已画出的结果
        if cancelled:
            self.progress_bar.setVisible(False)
            self.status_bar.showMessage("已取消拟合")
            return
        # 主线程里设置长宽比与画布尺寸适配（后台线程读尺寸不可靠），确保铺满
        self._apply_ratio()
        self.canvas._fit_to_widget()
        self.canvas.draw()
        self.progress_bar.setVisible(False)
        if self.spectrum_type == "lifetime":
            # 把拟合结果（χ²R、寿命分量等）写入信息页，并刷新寿命分布画布
            self._show_lifetime_fit_info()
            self.lifetime_canvas._fit_to_widget()
            self.lifetime_canvas.draw()
            if hasattr(self, 'diag_canvas'):
                self.diag_canvas._fit_to_widget()
                self.diag_canvas.draw()
            self.status_bar.showMessage(
                "寿命拟合完成（寿命分布在「寿命分布」页，诊断在「拟合诊断」页）")
        elif self.spectrum_type == "scan3d":
            st = (getattr(self, '_last_scan3d_result', None) or {}).get('stats', {})
            msg = "3D 扫描图已更新"
            if st.get('comb_notched'):
                if 'comb_kept' in st:
                    msg += f"（梳状伪迹：保留 {st['comb_kept']} 个谷值通道重建）"
                else:
                    msg += f"（梳状伪迹：周期 {st.get('comb_period', 0):.2f} nm 已处理）"
            self.status_bar.showMessage(msg)
        else:
            # 把积分结果写入绘图区下方的数据输出区
            self._update_integration_output()
            self.status_bar.showMessage(self._subtract_skip_note())
        # v4.27：画布/空状态切换 + 状态栏徽标（有数据了就把引导页收起来）
        self._sync_empty_state()
        self._update_status_badges()

    def _on_plot_error(self, error_msg, gen=None):
        """绘图错误回调（v4.45：过期任务的错误同样丢弃，避免切模式后弹旧错误）"""
        if self._is_stale(gen):
            logging.info("丢弃过期的错误回调（代次 %s）", gen)
            return
        self._plotting = False
        self._fit_cancelled = False
        self._long_task = False
        self._set_canvas_busy(False)
        self._close_progress_dialog()
        log_exception("绘图失败", error_msg)
        QMessageBox.critical(
            self, "错误",
            f"绘图失败: {error_msg}\n\n详细信息已写入日志：\n{log_file_path()}")
        self.progress_bar.setVisible(False)

    # 标签页属性 → 该页画布属性（v4.42：「导出当前图」按当前页取图）
    _TAB_CANVAS_PAIRS = (
        ('compare_tab', 'compare_canvas'),
        ('diag_tab', 'diag_canvas'),
        ('dist_tab', 'lifetime_canvas'),
        ('preview_tab', 'canvas'),
    )

    def _current_export_canvas(self):
        """当前标签页对应的画布（预览 / 数据比较 / 拟合诊断 / 寿命分布）。

        v4.42 修：以前 ``export_plot`` 写死 ``self.canvas.fig``——在「数据比较」
        页点「导出当前图」导出的还是光谱预览图。这里按 `currentWidget()` 认页，
        不按索引（标签页会随模式显隐，索引会漂）。
        """
        tw = getattr(self, 'tab_widget', None)
        cur = tw.currentWidget() if tw is not None else None
        for tab_attr, canvas_attr in self._TAB_CANVAS_PAIRS:
            tab = getattr(self, tab_attr, None)
            canvas = getattr(self, canvas_attr, None)
            if tab is not None and cur is tab and canvas is not None:
                return canvas
        return getattr(self, 'canvas', None)

    def _current_export_title(self, canvas=None):
        """「导出当前图」的默认文件名（跟着当前标签页走）。"""
        if canvas is None:
            canvas = self._current_export_canvas()
        if canvas is getattr(self, 'compare_canvas', None):
            res = getattr(self, '_last_compare_result', None)
            if res and res.get('points'):
                return f"数据比较_{res.get('x_label', '')}_{res.get('metric', '')}"
            return "数据比较"
        if canvas is getattr(self, 'diag_canvas', None):
            return "拟合诊断"
        if canvas is getattr(self, 'lifetime_canvas', None):
            return "寿命分布"
        return self._current_plot_title()

    def _canvas_is_placeholder(self):
        """当前导出画布上是否只有提示文字、没有任何真实数据（v4.44）。

        判断依据：画布上存在坐标轴，但**所有** ax 都没有 data 线、
        也没有图像/集合（3D 用）。空画布、未勾选、未拟合都属于这种情况。
        返回 True 表示"没有可导出的图"。
        """
        try:
            canvas = self._current_export_canvas()
            fig = getattr(canvas, 'fig', None)
            if fig is None:
                return True
            for ax in fig.axes:
                # 2D 折线
                if ax.get_lines():
                    return False
                # 散点 / 柱 / 图像 / 3D 集合
                for coll in getattr(ax, 'collections', []) or []:
                    return False
                if getattr(ax, 'images', None):
                    return False
                if getattr(ax, 'patches', None):
                    return False
            return True
        except Exception:
            # 判断本身失败时不要拦住导出（宁可放过，不可错杀）
            return False

    def export_plot(self):
        """导出**当前标签页**的图（预览 / 数据比较 / 拟合诊断 / 寿命分布）。

        v4.42：以前不管在哪个标签页都导出预览画布——「数据比较」页导出的
        是光谱全图，而不是那张点线图。
        """
        if not self.data_cache:
            QMessageBox.warning(self, "警告", "请先加载数据并生成图表！")
            return

        # v4.44：画布上只剩占位提示文字时（未勾选任何样品 / 未拟合）拒绝导出。
        # 此前照样"成功"写出提示图，弹窗却说"已保存"，用户以为拿到了结果图。
        if self._canvas_is_placeholder():
            QMessageBox.warning(
                self, "没有可导出的内容",
                "当前画布上还没有可导出的图（只有提示文字）。\n\n"
                "请先勾选至少一个样品，或先完成拟合。")
            self.status_bar.showMessage("导出取消：画布上没有图")
            return

        # 荧光寿命模式：一次导出两张图（拟合+残差合并图、寿命分布图）与 json
        if self.spectrum_type == "lifetime":
            default_dir = self._dialog_start_dir()
            save_dir = QFileDialog.getExistingDirectory(
                self, "选择保存目录", default_dir, QFileDialog.ShowDirsOnly)
            if save_dir:
                self._export_lifetime_plots(save_dir)
            return

        canvas = self._current_export_canvas()
        if canvas is None:
            QMessageBox.warning(self, "警告", "当前没有可导出的画布")
            return

        # 选择保存路径（默认指向当前数据文件夹；默认文件名 = 当前图表标题）
        default_dir = self._dialog_start_dir()
        default_name = (f"{self._safe_filename(self._current_export_title(canvas))}"
                        f"{self._export_formats()[0]}")
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "导出图片",
            str(Path(default_dir) / default_name),
            "PNG文件 (*.png);;PDF文件 (*.pdf);;SVG文件 (*.svg);;所有文件 (*.*)"
        )

        if file_path:
            try:
                fig = self._make_current_export_fig(canvas)
                if fig is not None:
                    # 重画路径：自己新建的 fig，用完要释放
                    try:
                        self._savefig_pub(fig, file_path)
                    finally:
                        self._dispose_fig(fig)
                else:
                    self._savefig_pub(canvas.fig, file_path)
                QMessageBox.information(self, "成功", f"图片已保存到:\n{file_path}")
                self.status_bar.showMessage(f"图片已保存: {file_path}")
            except Exception as e:
                log_exception(f"导出图片失败: {file_path}", e)
                QMessageBox.critical(self, "错误", f"导出失败: {str(e)}")

    def _make_current_export_fig(self, canvas):
        """为「导出当前图」新建一张与「导出全部」同口径的 fig（v4.45）。

        背景：此前 ``export_plot`` 直接 ``savefig(canvas.fig)``，而画布的 fig 是
        按屏幕尺寸建的、字号也停在界面字号；``_apply_pub_rc`` 只影响**此后新建**
        的 fig。于是选了「单栏 3.5 in」预设后，画布 fig 被 ``set_size_inches(3.5, 2.6)``
        硬塞进去、字号仍是 13pt，``bbox_inches='tight'`` 一膨胀就变成 4.013 in，
        **超出 3.5 in 栏宽 15%**，投稿排版放不进；而「导出全部」走重画路径得到
        3.508 in（正确）。同一张图两个按钮给出两种物理尺寸，且峰标注/显示范围
        也可能不同。

        解决：吸收/发射的「预览」页走与「导出全部」完全相同的渲染函数，
        画布只当预览、不当导出源。其他页（数据比较 / 诊断 / 寿命分布）没有
        对应渲染器，仍存画布 fig（返回 None 表示"用画布"）。

        返回新建的 fig；返回 None 表示调用方应回退到 canvas.fig。
        """
        try:
            if canvas is not getattr(self, 'canvas', None):
                return None                      # 其它标签页：没有独立渲染器
            if self.spectrum_type not in ('absorption', 'emission'):
                return None                      # 3D 等由各自的导出路径处理
            sub_cfg = self._get_subtract_config()
            if sub_cfg and sub_cfg.get('mode') == 'diff':
                return None                      # 差谱只有画布那一张
            export_files = [f for f in self.get_checked_files()
                            if f in self.data_cache]
            if not export_files:
                return None
            linewidth = self.linewidth_spin.value()
            mark_peaks = self.mark_peaks_check.isChecked()
            peak_height = self.peak_height_spin.value()
            peak_distance = self.peak_distance_spin.value()
            custom_title = self.title_edit.text().strip()
            xlim = self._get_xlim()
            if self.current_plot_type == 'single':
                target = self._single_plot_target()
                if not target or target not in self.data_cache:
                    return None
                fig, _t = self._render_single_export_fig(
                    target, linewidth, mark_peaks, peak_height, peak_distance,
                    sub_cfg, custom_title, xlim=xlim)
                return fig
            fig, _t = self._render_combined_export_fig(
                export_files, linewidth, sub_cfg, custom_title,
                mark_peaks=mark_peaks, peak_height=peak_height,
                peak_distance=peak_distance, xlim=xlim)
            return fig
        except Exception as e:
            # 重画失败就回退到画布（宁可尺寸不准，也不要导不出图）
            logging.warning("重画导出图失败，回退到画布 fig: %s", e)
            return None

    def export_all_plots(self):
        """导出所有图表"""
        if not self.data_cache:
            QMessageBox.warning(self, "警告", "请先加载数据！")
            return

        # 默认保存目录指向当前数据文件夹/工作区（E4）
        default_dir = self._dialog_start_dir()

        # 选择保存目录
        save_dir = QFileDialog.getExistingDirectory(
            self,
            "选择保存目录",
            default_dir,
            QFileDialog.ShowDirsOnly
        )

        if not save_dir:
            return

        # 荧光寿命模式：导出拟合+残差合并图与寿命分布图
        if self.spectrum_type == "lifetime":
            self._export_lifetime_plots(save_dir)
            return
        # 3D 扫描模式：单独处理（旧实现会落到光谱分支、写 0 个文件却弹「成功」）
        if self.spectrum_type == "scan3d":
            self._export_scan3d_plots(save_dir)
            return

        try:
            save_path = Path(save_dir)
            # v4.46：导出改为**后台线程**执行。
            # 旧实现在主线程里逐张渲染 + savefig，40 文件 PNG+PDF 实测 18.17 s，
            # 期间事件循环存活率只有 11%（最长 538 ms 无响应），且完全不可取消。
            # 现在把全部参数在主线程读成快照，交给 _do_export_all_spread 在
            # PlotWorker 里跑，UI 保持响应、可取消、有进度。
            params = self._collect_export_params(save_dir)
            self._start_worker(
                self._do_export_all, params, self._on_export_all_finished,
                long_task=False,
                dialog_text=f"正在导出 {len(params['export_files'])} 张图…",
                indeterminate=False)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"导出失败: {str(e)}")
            self.progress_bar.setVisible(False)

    def _collect_export_params(self, save_dir):
        """把「导出全部」需要的控件值在主线程读成快照（v4.46）。

        后台线程里**不能**碰 Qt 控件（跨线程读控件是未定义行为），
        所以这里一次性读全，后面 _do_export_all 只用这个 dict。
        """
        sub_cfg = self._get_subtract_config()
        checked_files = self.get_checked_files()
        export_files = [f for f in checked_files if f in self.data_cache]
        if not export_files:
            export_files = list(self.data_cache.keys())
        if sub_cfg:
            export_files = [f for f in export_files if f != sub_cfg['b']]
        return {
            'save_dir': str(save_dir),
            'dpi': self.dpi_spin.value(),
            'linewidth': self.linewidth_spin.value(),
            'mark_peaks': self.mark_peaks_check.isChecked(),
            'peak_height': self.peak_height_spin.value(),
            'peak_distance': self.peak_distance_spin.value(),
            'sub_cfg': sub_cfg,
            'custom_title': self.title_edit.text().strip(),
            'exts': self._export_formats(),
            'xlim': self._get_xlim(),
            'spectrum_type': self.spectrum_type,
            'current_plot_type': self.current_plot_type,
            'export_files': export_files,
            'single_target': self._single_plot_target(),
            'compare_result': (
                dict(getattr(self, '_last_compare_result', None) or {})
                if getattr(self, '_last_compare_result', None) else None),
        }

    def _do_export_all(self, params=None):
        """后台线程：执行「导出全部」的全部渲染与落盘，返回提示文字（v4.46）。

        只读 ``params`` 快照，不碰任何 Qt 控件；进度通过 ``params['worker']``
        上报（PlotWorker.report），取消通过 ``worker.is_cancelled()`` 轮询。
        """
        params = params or {}
        worker = params.get('worker')
        save_path = Path(params['save_dir'])
        dpi = params['dpi']
        exts = params['exts']
        sub_cfg = params['sub_cfg']
        custom_title = params['custom_title']
        linewidth = params['linewidth']
        mark_peaks = params['mark_peaks']
        peak_height = params['peak_height']
        peak_distance = params['peak_distance']
        xlim = params['xlim']
        export_files = list(params['export_files'])
        total_steps = len(export_files) + 2

        def _tick(step, text=""):
            if worker is not None and hasattr(worker, 'report'):
                try:
                    worker.report(step / max(total_steps, 1), text)
                except Exception:
                    pass

        def _cancelled():
            return (worker is not None and hasattr(worker, 'is_cancelled')
                    and worker.is_cancelled())

        plots_dir = save_path / "plots"
        plots_dir.mkdir(parents=True, exist_ok=True)

        # 差谱模式（A − B）：预览画布上就是差谱，按标题导出这一张
        if sub_cfg and sub_cfg.get('mode') == 'diff':
            base = self._safe_filename(self._current_plot_title())
            out_paths = []
            for ext in exts:
                out_path = plots_dir / f"{base}{ext}"
                self._savefig_pub(self.canvas.fig, out_path, dpi)
                out_paths.append(out_path)
            return ("差谱图已保存到:\n" + "\n".join(str(p) for p in out_paths),
                    f"已导出差谱图: {out_paths[0]}", [])

        used = {}

        def _unique(base):
            n = used.get(base, 0) + 1
            used[base] = n
            return base if n == 1 else f"{base}_{n}"

        n_ok, failures = 0, []
        for i, file_name in enumerate(export_files):
            if _cancelled():
                failures.append("用户取消：其余文件未导出")
                break
            try:
                fig, title = self._render_single_export_fig(
                    file_name, linewidth, mark_peaks, peak_height,
                    peak_distance, sub_cfg, custom_title, xlim=xlim)
                base = self._safe_filename(title)
                if custom_title:
                    base = (f"{base}_"
                            f"{self._safe_filename(self._sample_name(file_name))}")
                base = _unique(base)
                for ext in exts:
                    self._savefig_pub(fig, plots_dir / f"{base}{ext}", dpi)
                self._dispose_fig(fig)
                n_ok += 1
            except Exception as e:
                failures.append(f"{file_name}: {e}")
                logging.warning("导出 %s 失败: %s", file_name, e)
            _tick(i + 1, f"已导出 {i + 1}/{len(export_files)}")

        # 合并图（只导出勾选的数据）
        if not _cancelled():
            try:
                fig, title = self._render_combined_export_fig(
                    export_files, linewidth, sub_cfg, custom_title,
                    mark_peaks=mark_peaks, peak_height=peak_height,
                    peak_distance=peak_distance, xlim=xlim)
                base = _unique(self._safe_filename(title))
                for ext in exts:
                    self._savefig_pub(fig, plots_dir / f"{base}{ext}", dpi)
                self._dispose_fig(fig)
                n_ok += 1
            except Exception as e:
                failures.append(f"合并图: {e}")
                logging.warning("导出合并图失败: %s", e)

        # 数据比较点线图（v4.37）：画过就一起导出
        # 注意：compare_canvas.fig 属于 GUI 线程的 Figure，在后台线程 savefig
        # 有风险；改为在主线程侧先复制引用、后台只做 savefig（matplotlib 的
        # Agg 渲染对"只读一个静止 Figure"是安全的，且这页不会同时重绘）。
        cmp_res = params.get('compare_result')
        if cmp_res and cmp_res.get('points') and not _cancelled():
            try:
                base = _unique(self._safe_filename(
                    f"数据比较_{cmp_res['x_label']}_{cmp_res['metric']}"))
                for ext in exts:
                    self._savefig_pub(self.compare_canvas.fig,
                                      plots_dir / f"{base}{ext}", dpi)
                n_ok += 1
            except Exception as e:
                failures.append(f"数据比较图: {e}")
                logging.warning("导出数据比较图失败: %s", e)

        msg = (f"所有图片已保存到:\n{plots_dir}\n"
               f"格式 {'/'.join(e.lstrip('.') for e in exts)}\n"
               f"成功 {n_ok} 张，失败 {len(failures)} 张")
        if failures:
            msg += "\n\n失败明细（前 5 条）:\n" + "\n".join(failures[:5])
        return msg, f"已导出所有图片到: {plots_dir}", failures

    def _on_export_all_finished(self, result, gen=None):
        """「导出全部」完成回调（主线程）。v4.46：过期结果丢弃。"""
        if self._is_stale(gen):
            logging.info("丢弃过期的导出完成回调（代次 %s）", gen)
            return
        self._plotting = False
        self._long_task = False
        self._set_canvas_busy(False)
        self._close_progress_dialog()
        self.progress_bar.setVisible(False)
        try:
            msg, status, failures = result
        except Exception:
            msg, status, failures = (str(result), "导出完成", [])
        if getattr(self, '_fit_cancelled', False):
            self.status_bar.showMessage("导出已取消")
            return
        if failures:
            QMessageBox.warning(self, "部分失败", msg)
        else:
            QMessageBox.information(self, "成功", msg)
        self.status_bar.showMessage(status)

    def _export_scan3d_plots(self, save_dir):
        """3D 扫描模式导出：当前绘图类型 + 清洗统计 json。"""
        import json as _json
        plots_dir = Path(save_dir) / "plots"
        plots_dir.mkdir(parents=True, exist_ok=True)
        dpi = self.dpi_spin.value()
        exts = self._export_formats()
        base = self._safe_filename(self._current_plot_title())
        exported = []
        for ext in exts:
            out = plots_dir / f"{base}{ext}"
            self._savefig_pub(self.canvas.fig, out, dpi)
            exported.append(out)
        res = getattr(self, '_last_scan3d_result', None)
        if res and res.get('stats'):
            jp = plots_dir / f"{base}_stats.json"
            # v4.44：把绘图类型一并写进 stats，否则只拿到 json 时无法判断
            # 它对应 3D 曲面 / 等高线 / Waterfall 中的哪一种。
            stats_out = dict(res['stats'])
            try:
                stats_out.setdefault('plot_type',
                                     self.scan3d_plot_combo.currentText().strip())
            except Exception:
                pass
            with open(jp, 'w', encoding='utf-8') as f:
                _json.dump(stats_out, f, ensure_ascii=False, indent=2,
                           default=float)
            exported.append(jp)
        QMessageBox.information(
            self, "成功", "已导出:\n" + "\n".join(str(p) for p in exported))
        self.status_bar.showMessage(f"已导出 3D 扫描图到: {plots_dir}")

    def _render_single_export_fig(self, file_name, linewidth, mark_peaks,
                                  peak_height, peak_distance, sub_cfg,
                                  custom_title="", xlim=None):
        """「导出全部」用：渲染单个文件的光谱图（吸收/发射风格与预览一致）。

        返回 (fig, 标题)；标题同时用作导出文件名。
        v4.45：补 xlim —— 此前导出图丢失画布的显示范围（画布 500–600 nm，
        导出却是全谱 361–926 nm）。
        """
        # v4.46：用 Figure() 直建而不是 plt.subplots()。
        # 本函数在**后台线程**里被调用（批量导出已异步化），而 plt.subplots()
        # 会走 pyplot 的图形管理器/当前后端（本项目是 Qt5Agg = GUI 后端），
        # 在非主线程里这样做 matplotlib 会警告
        # "Starting a Matplotlib GUI outside of the main thread will likely fail"，
        # 并有崩溃风险。Figure() 是纯 Agg 对象、不注册到 pyplot，线程安全。
        fig = Figure(figsize=self._pub_figsize((8.0, 5.0)))
        ax = fig.add_subplot(111)
        self.setup_chinese_font()
        data = self.data_cache[file_name]['data']
        xy, reason = self._get_plot_xy_checked(file_name, sub_cfg, record=False)
        if xy is None:
            # 让「导出全部」把这一条记进失败明细（原因写清楚），其余照常导出
            raise ValueError(f"无法扣除本底：{reason}")
        wl, y = xy
        colors = self._palette(self.get_color_map(), 3)

        if self.spectrum_type == "emission":
            ax.plot(wl, y, linewidth=linewidth, color=colors[0],
                    label=self._build_legend_label(file_name, data, show_all=True))
            ex_wl = data.get('ex_wl', data.get('ex'))
            if (getattr(self, 'show_ex_check', None) is not None
                    and self.show_ex_check.isChecked() and ex_wl is not None):
                ax.axvline(ex_wl, color=colors[1], linestyle='--', linewidth=1.2,
                           alpha=0.8, label=f"EX={ex_wl:.0f} nm")
            ax.set_ylabel('发射强度 (AU)')
            title = f"发射光谱 - {self._sample_name(file_name, data)}"
            if mark_peaks:
                try:
                    y_max = np.nanmax(y)
                    height = y_max * peak_height if y_max > 0 else 0.05
                    peaks, _props = find_peaks(
                        y, height=height, distance=peak_distance,
                        prominence=y_max * 0.03)
                    for pw, pi in zip(wl[peaks], y[peaks]):
                        self._annotate_peak(ax, pw, pi, xytext=(0, 8),
                                            textcoords='offset points', fontsize=11,
                                            color=colors[0], ha='center', va='bottom',
                                            fontweight='bold')
                except Exception:
                    pass
        else:
            ax.plot(wl, y, linewidth=linewidth, color=colors[0],
                    label=self._build_legend_label(file_name, data, show_all=True))
            ax.set_ylabel('吸收值 (AU)')
            title = f"吸收光谱 - {self._sample_name(file_name, data)}"
            if mark_peaks:
                temp_data = {'wl': wl, 'absorption': y}
                peaks = find_absorption_peaks(temp_data, min_height=peak_height,
                                              min_distance=peak_distance)
                for pw, pi in zip(peaks.get('peak_wavelengths', []),
                                  peaks.get('peak_intensities', [])):
                    self._annotate_peak(
                        ax, pw, pi, xytext=(0, 6),
                        textcoords='offset points', fontsize=11,
                        color=colors[0], ha='center', va='bottom',
                        rotation=0, alpha=0.9, fontweight='bold')

        self._apply_legend(ax)
        ax.set_xlabel('波长 (nm)')
        if custom_title:
            title = custom_title
        ax.set_title(title)
        self._grid(ax)
        # v4.45：与预览一致地应用显示范围（放在 grid 之后、tight_layout 之前）
        if xlim:
            self._apply_xlim(ax, xlim)
        fig.tight_layout()
        return fig, title

    def _render_combined_export_fig(self, export_files, linewidth, sub_cfg,
                                    custom_title="", mark_peaks=False,
                                    peak_height=0.05, peak_distance=20,
                                    xlim=None):
        """「导出全部」用：渲染合并图（吸收/发射风格与预览一致）。返回 (fig, 标题)。

        v4.45：补 mark_peaks / peak_height / peak_distance / xlim。
        此前这个函数**根本没有峰标注代码**（调用点 :export_all_plots 读了
        mark_peaks 等三个变量却只喂给单图渲染），于是「导出全部」得到的合并图
        上一个峰标注都没有，而画布上明明有；显示范围同样丢失（画布 500–600 nm，
        导出却是全谱 361–926 nm）。两套渲染逻辑不一致 = 同一张图两个结果。
        """
        # v4.46：同 _render_single_export_fig —— 后台线程里不能走 plt.subplots()
        fig = Figure(figsize=self._pub_figsize())
        ax = fig.add_subplot(111)
        self.setup_chinese_font()
        is_emission = self.spectrum_type == "emission"
        normalize = (is_emission
                     and getattr(self, 'normalize_check', None) is not None
                     and self.normalize_check.isChecked())
        # 与预览图同一套取色规则（按文件身份），保证导出的图和预览一致
        colors = self._stable_colors(export_files, self.get_color_map())
        # v4.46：与预览同一套去重标签
        labels = self._legend_labels_for(export_files)

        for i, file_name in enumerate(export_files):
            data = self.data_cache[file_name]['data']
            xy, _reason = self._get_plot_xy_checked(file_name, sub_cfg, record=False)
            if xy is None:
                continue          # 扣不了本底的不进导出图（v4.36）
            wl, y = xy
            # v4.44：与预览同一口径（扣基线后按峰高归一），保证导出的图
            # 和画布上看到的一致，也避免负基线把纵轴撑爆。
            if normalize:
                y = self._normalize_intensity(y)
            ax.plot(wl, y, linewidth=linewidth, color=colors[i],
                    label=(labels[i] if i < len(labels)
                           else self._build_legend_label(file_name, data)))
            if is_emission:
                ex_wl = data.get('ex_wl', data.get('ex'))
                if (getattr(self, 'show_ex_check', None) is not None
                        and self.show_ex_check.isChecked() and ex_wl is not None):
                    ax.axvline(ex_wl, color=colors[i], linestyle='--',
                               linewidth=1, alpha=0.5)
            # v4.45：合并图的峰标注（与预览 _plot_*_combined 同一套判据）
            if mark_peaks:
                try:
                    if is_emission:
                        y_max = np.nanmax(y) if y.size else 0
                        height = y_max * peak_height if y_max > 0 else 0.05
                        pk, _p = find_peaks(
                            y, height=height, distance=peak_distance,
                            prominence=y_max * 0.03 if y_max > 0 else None)
                        for pw, pi in zip(wl[pk], y[pk]):
                            self._annotate_peak(ax, pw, pi,
                                                xytext=(0, 6),
                                                textcoords='offset points', fontsize=10,
                                                color=colors[i], ha='center',
                                                va='bottom', alpha=0.8)
                    else:
                        pk = find_absorption_peaks(
                            {'wl': wl, 'absorption': y},
                            min_height=peak_height,
                            min_distance=peak_distance)
                        for pw, pi in zip(pk.get('peak_wavelengths', []),
                                          pk.get('peak_intensities', [])):
                            self._annotate_peak(ax, pw, pi,
                                                xytext=(0, 5),
                                                textcoords='offset points', fontsize=10,
                                                color=colors[i], ha='center',
                                                va='bottom', alpha=0.8)
                except Exception:
                    pass          # 单条标峰失败不影响整张导出图

        ax.set_xlabel('波长 (nm)')
        ax.set_ylabel('归一化强度' if normalize
                      else ('发射强度 (AU)' if is_emission else '吸收值 (AU)'))
        title = custom_title or ('发射光谱对比' if is_emission else '吸收光谱对比')
        ax.set_title(title)
        self._apply_legend(ax)
        self._grid(ax)
        # v4.45：与预览一致地应用显示范围
        if xlim:
            self._apply_xlim(ax, xlim)
        fig.tight_layout()
        return fig, title
