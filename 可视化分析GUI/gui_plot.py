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
        """
        assigner = self._color_assigner()
        return [assigner.get(name, color_map) for name in file_names]

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
        """按所选图例位置应用图例，避免遮挡曲线。"""
        loc, extra = self._legend_params()
        if loc is None:     # 隐藏
            return
        try:
            ax.legend(fontsize=9, loc=loc, **extra)
        except Exception:
            ax.legend(fontsize=9)

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
            ax._qls_base_left = float(base)
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
                base = float(getattr(ax, '_qls_base_left', 0.09))
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

    # ---- 光谱积分（绘图区下方的数据输出区） ----

    @staticmethod
    def _integrate_band(wl, y, lo, hi):
        """梯形法计算 [lo, hi] 波长区间内的曲线下面积。

        区间边界处对光谱做线性插值（避免半步长误差）；
        数据与区间无重叠时返回 NaN。
        """
        wl = np.asarray(wl, dtype=float)
        y = np.asarray(y, dtype=float)
        mask = np.isfinite(wl) & np.isfinite(y)
        wl, y = wl[mask], y[mask]
        if wl.size < 2 or not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
            return float('nan')
        order = np.argsort(wl)
        wl, y = wl[order], y[order]
        grid_lo = max(lo, float(wl[0]))
        grid_hi = min(hi, float(wl[-1]))
        if grid_hi <= grid_lo:
            return float('nan')
        wg = np.concatenate(([grid_lo], wl[(wl > grid_lo) & (wl < grid_hi)], [grid_hi]))
        yg = np.interp(wg, wl, y)
        # numpy 2 起 trapz 更名为 trapezoid（兼容旧版）
        trapz = getattr(np, 'trapezoid', np.trapz)
        return float(trapz(yg, wg))

    def _compute_integration_results(self, sub_cfg=None):
        """对所有已加载样品计算积分，供数据输出区显示。

        返回 {'lo', 'hi', 'rows': [(样品名, 积分值)]}；范围无效返回 None。
        与绘图口径一致：启用光谱减法时按扣本底后的曲线积分（本底文件本身跳过）；
        差谱模式只输出 A − B 一行；积分用原始强度，不受「归一化」显示影响。
        """
        lo = float(self.integ_min_spin.value())
        hi = float(self.integ_max_spin.value())
        if hi <= lo:
            return None
        rows = []
        if sub_cfg and sub_cfg['mode'] == 'diff':
            data_a = self.data_cache[sub_cfg['a']]['data']
            wl_a, y_a = self._extract_xy(data_a)
            wl, y = self._subtract_ref(wl_a, y_a, sub_cfg['b'])
            label = (f"{self._sample_name(sub_cfg['a'], data_a)} − "
                     f"{self._sample_name(sub_cfg['b'])}")
            rows.append((label, self._integrate_band(wl, y, lo, hi)))
        else:
            for file_name in self.data_cache:
                if sub_cfg and file_name == sub_cfg['b']:
                    continue  # 本底文件自身不参与积分（与绘图一致）
                data = self.data_cache[file_name]['data']
                wl, y = self._get_plot_xy(file_name, sub_cfg)
                rows.append((self._sample_name(file_name, data),
                             self._integrate_band(wl, y, lo, hi)))
        return {'lo': lo, 'hi': hi, 'rows': rows}

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
            if results is None:
                # 原来这两句提示是写进文本框正文的，改表格后放进计数标签；
                # 注意区分「没加载数据」（未计算）和「范围填反了」（无效范围）
                if getattr(self, 'data_cache', None):
                    count_label.setText("积分范围无效（结束需大于起始）")
                else:
                    count_label.setText("未计算")
            elif not rows:
                count_label.setText(f"{results['lo']:g}–{results['hi']:g} nm 无数据重叠")
            else:
                skipped = len(results['rows']) - len(rows)
                text = (f"共 {len(rows)} 个样品 · "
                        f"{results['lo']:g}–{results['hi']:g} nm")
                if skipped:
                    text += f"（{skipped} 个无重叠未列出）"
                count_label.setText(text)

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
            return f"{prefix} - {name}" if name else prefix
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
            self._plotting = True
            self._fit_cancelled = False
            # 寿命拟合是长任务（1–2 分钟）：切模式/关窗时要问用户；
            # 普通绘图是短任务，静默中止即可（见 gui_data._confirm_interrupt_plotting）
            self._long_task = (self.spectrum_type == "lifetime")
            if self.spectrum_type == "lifetime":
                self.status_bar.showMessage(
                    "正在拟合荧光寿命（MEM 最大熵，可能需要 1–2 分钟，请耐心等待）...")
            else:
                self.status_bar.showMessage("正在生成图表...")
            self.progress_bar.setVisible(True)
            self.progress_bar.setRange(0, 0)

            # D4：控件值在主线程先读成参数字典，worker 内部不再碰 Qt 控件
            params = self._collect_plot_params()
            # 在后台线程中绘图
            self.plot_worker = PlotWorker(self._do_plot, params)
            params['worker'] = self.plot_worker
            self.plot_worker.finished.connect(self._on_plot_finished)
            self.plot_worker.error.connect(self._on_plot_error)
            self.plot_worker.progress.connect(self._on_worker_progress)
            self._set_canvas_busy(True)
            self._start_progress_dialog(
                "正在拟合荧光寿命…" if self.spectrum_type == "lifetime"
                else "正在生成图表…",
                indeterminate=(self.spectrum_type != "lifetime"))
            self.plot_worker.start()

        except Exception as e:
            self._plotting = False
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
        # 寿命参数
        try:
            method = ("SESM" if "SESM" in self.lifetime_method_combo.currentText()
                      else "MEM")
            k_min = float(self.lifetime_kmin_spin.value())
            k_max = float(self.lifetime_kmax_spin.value())
            if k_max <= k_min:
                k_min, k_max = 0.01, 100.0
            fixed_taus = []
            try:
                raw = self.lifetime_fixed_taus_edit.text().replace('，', ',')
                fixed_taus = [float(x) for x in raw.replace(' ', '').split(',')
                              if x.strip()]
                fixed_taus = [t for t in fixed_taus if t > 0]
            except Exception:
                fixed_taus = []
            P.update({
                'lifetime_method': method,
                'lifetime_nrates': int(self.lifetime_nrates_spin.value()),
                'lifetime_lambda': float(self.lifetime_lambda_spin.value()),
                'lifetime_auto_lambda': bool(
                    self.lifetime_auto_lambda_check.isChecked()),
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
        for attr in ('canvas', 'lifetime_canvas', 'diag_canvas'):
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
        try:
            if self._legend_needs_room():
                self.canvas.fig.subplots_adjust(left=0.09, right=0.80, top=0.92, bottom=0.26)
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
            cbar = self.canvas.fig.colorbar(surf, ax=ax, shrink=0.55,
                                            aspect=18, pad=0.10)
            cbar.set_label(cbar_label)
            self.canvas.fig.subplots_adjust(left=0.02, right=0.86,
                                            top=0.95, bottom=0.05)
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
        """并行拟合全部已加载文件，并在「寿命分布」页叠加对比。"""
        if self.spectrum_type != "lifetime":
            return
        if not self.data_cache:
            QMessageBox.warning(self, "提示", "请先加载寿命数据")
            return
        if getattr(self, '_plotting', False):
            return
        self._plotting = True
        self._fit_cancelled = False
        self._long_task = True   # 并行拟合同样是长任务（D3）
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        # D4：参数在主线程读好
        params = self._collect_plot_params()
        msg = self._batch_fit_status_text(params)
        self.status_bar.showMessage(msg)
        self.plot_worker = PlotWorker(self._do_overlay_lifetime, params)
        params['worker'] = self.plot_worker
        self.plot_worker.finished.connect(self._on_overlay_finished)
        self.plot_worker.error.connect(self._on_plot_error)
        self.plot_worker.progress.connect(self._on_worker_progress)
        self._set_canvas_busy(True)
        self._start_progress_dialog(msg.rstrip('.'), indeterminate=True)
        self.plot_worker.start()

    def _batch_fit_status_text(self, params):
        """批量拟合前的提示文案：说明有多少样品可以直接复用已有结果（v4.23）。"""
        total = len(self.data_cache)
        n_cached = self._lifetime_cached_count(params)
        if total and n_cached >= total:
            return f"已复用全部 {total} 个样品的已有拟合结果，正在出图..."
        if n_cached:
            return (f"正在拟合 {total - n_cached} 个样品"
                    f"（复用 {n_cached} 个已有拟合结果）...")
        return f"正在并行拟合 {total} 个文件（多进程，请稍候）..."

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
        if getattr(self, '_plotting', False):
            QMessageBox.information(self, "提示", "正在拟合中，请稍候…")
            return
        save_dir = QFileDialog.getExistingDirectory(
            self, "选择保存目录", self._dialog_start_dir(),
            QFileDialog.ShowDirsOnly)
        if not save_dir:
            return
        self._plotting = True
        self._long_task = True
        self._fit_cancelled = False
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        params = self._collect_plot_params()
        params['kind'] = kind
        params['save_dir'] = save_dir
        msg = self._batch_fit_status_text(params)
        self.status_bar.showMessage(msg)
        self.plot_worker = PlotWorker(self._do_batch_export, params)
        params['worker'] = self.plot_worker
        self.plot_worker.finished.connect(self._on_batch_export_finished)
        self.plot_worker.error.connect(self._on_plot_error)
        self.plot_worker.progress.connect(self._on_worker_progress)
        self._set_canvas_busy(True)
        self._start_progress_dialog(msg.rstrip('.'), indeterminate=True)
        self.plot_worker.start()

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
        """对全部已加载文件做寿命拟合，**已有的拟合结果直接复用**，只拟合缺的。

        v4.23：此前叠加分布 / 跨样品汇总图 / PDF 报告都无条件调用 fit_many，
        即使用户刚在单文件里拟合过、或刚导出过一次汇总图，也要把全部样品
        重新拟合一遍（每样品 1–2 分钟）。现在改为按 `_lifetime_fit_cache`
        查表复用，并把新拟合的结果回写缓存，于是「汇总图 → PDF 报告」这类
        连续操作只需拟合一次。

        Returns:
            (results, n_reused, n_fitted)：results 与 self.data_cache 同序，
            拟合失败的样品为 None。
        """
        import plot_lifetime as _pl
        names = list(self.data_cache.keys())
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
            try:
                fitted = _pl.fit_many(todo, fit_kwargs=fit_kwargs)
            except (OSError, RuntimeError) as e:
                log_exception("并行拟合不可用，退回串行", e)
                fitted = _pl.fit_many(todo, max_workers=1, fit_kwargs=fit_kwargs)
            for i, r in zip(todo_idx, fitted):
                results[i] = r
                if r:
                    # 回写缓存：之后单文件查看 / 再次导出可直接命中
                    cache[self._lifetime_cache_key(names[i], params)] = r
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
        if params.get('kind') == 'pdf':
            path = _pl.export_report_pdf(results, save_dir=save_dir,
                                         verbose=False)
        else:
            path = _pl.plot_summary(results, save_dir=save_dir, verbose=False)
        detail = (f"复用 {n_reused} 个已有拟合结果"
                  if n_fitted == 0 else
                  f"复用 {n_reused} + 新拟合 {n_fitted}")
        return f"已保存（{len(results)} 个样品，{detail}）：\n{path}"

    def _on_batch_export_finished(self, msg):
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
        fig = self.lifetime_canvas.fig
        fig.clf()
        ax = fig.add_subplot(111)
        entries = []        # (tau, dist, amp, name, r)
        for r in results:
            if not r:
                continue
            k = np.asarray(r['k'], dtype=float)
            dist = np.asarray(r['k_distribution'], dtype=float)
            tau = 1.0 / np.maximum(k, 1e-12)
            amp = float(np.max(dist)) if dist.size else 0.0
            entries.append((tau, dist, amp, str(r.get('name', '')), r))
        scale = max((e[2] for e in entries), default=0.0)
        ok = 0
        for tau, dist, amp, name, r in entries:
            ax.plot(tau, dist / scale if scale > 0 else dist, linewidth=1.0,
                    label=self._overlay_entry_label(r, amp, scale))
            ok += 1
        ax.set_xscale('log')
        ax.set_xlabel(r'$\tau$ (ns)')
        ylab = '分布强度（同刻度，未逐条归一）'
        # 有样品的输入是归一化数据（preprocess 自动还原到各自 1e4 刻度）时，
        # 各曲线的绝对刻度并不统一，图例里的 I 也随之不可直接互比。只加一行短警告：
        # 文字太长会变成 3 行纵轴标签，高度不够会被裁掉（实测），详情见按钮 tooltip。
        if any((r or {}).get('info', {}).get('rescaled_from_normalized')
               for r in results):
            ylab += '\n⚠ 含归一化输入，I 不可跨样品比'
            # 两行纵轴标签会紧贴刻度数字（实测间距仅 ~10px），补一点间隙
            ax.yaxis.labelpad = 10
        ax.set_ylabel(ylab, fontsize=9)
        ax.set_title(f'寿命分布叠加对比（{ok}/{len(results)} 个样品）',
                     fontsize=12)
        if ok:
            ax.legend(fontsize=7, loc='center left', bbox_to_anchor=(1.01, 0.5),
                      frameon=False)
        self._grid(ax, dashed=True)
        fig.subplots_adjust(left=0.10, right=0.68, top=0.90, bottom=0.17)
        self._fit_left_margin(fig, ax, base=0.10)

        self._overlay_results = results
        return fig

    @staticmethod
    def _overlay_entry_label(r, amp, amp_max):
        """叠加分布图例的一条：样品名 + 振幅 + 实际强度（v4.32）。

        两个量口径不同，缺一不可：

        - **振幅 A（a.u.）**：该样品 `k_distribution` 的峰值，即图上这条曲线
          （未经共用因子缩放）的最高点。它反映分布的"集中程度"——熵正则越强、
          分布越弥散，A 越小。拟合内部已按 decay_max 归一（x_fit = 峰高/decay_max），
          所以 A 与样品的整体亮度无关，只描述分布形状。
        - **实际强度 I（counts）**：该样品衰减曲线在**拟合窗口内**的总计数。
          这是各样品之间真正可比、也真正代表"亮不亮"的量——整体衰减倍数会在
          振幅里被约掉，只有总计数留得住。它同时决定统计噪声水平（I 越大，
          χ²R 越可信）。

        振幅按占比给出（A/A_max，%）：分布是形状量，绝对刻度没有物理意义，
        百分比才看得出"集中/弥散"；强度给绝对值（counts），便于跨样品直接比较。

        统一到**拟合实际使用的刻度**：preprocess 若把归一化数据还原过
        （`info['rescale_factor']`），这里同样乘上该因子。否则图例读的是未还原的
        原始列，I 会比拟合所用的计数小好几个量级，与振幅、与图上曲线自相矛盾。
        """
        info = r.get('info', {}) or {}
        fs = int(info.get('fit_start', 0) or 0)
        fe = int(info.get('fit_end', 0) or 0)
        decay = np.asarray(r.get('decay', []), dtype=float)
        factor = float(info.get('rescale_factor', 1.0) or 1.0)
        if decay.size and fe > fs:
            total = float(np.sum(decay[fs:fe])) * factor
        else:
            total = float(np.sum(decay)) * factor
        share = (100.0 * amp / amp_max) if amp_max > 0 else 0.0
        return (f"{r.get('name', '')}\n"
                f"    A={amp:.4g} a.u.（{share:.1f}%）  I={total:.4g} counts")

    def _on_overlay_finished(self, fig):
        """并行叠加拟合完成（主线程）"""
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
            fig.savefig(path, dpi=dpi, bbox_inches='tight')
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
                import json as _json
                from plot_lifetime import NumpyTypeEncoder
                json_path = out_dir / f"{name}_fit_result.json"
                with open(json_path, 'w', encoding='utf-8') as f:
                    _json.dump(result, f, cls=NumpyTypeEncoder)
                msg += f"\n{json_path}"
            self.progress_bar.setVisible(False)
            QMessageBox.information(self, "成功", msg)
            self.status_bar.showMessage(
                f"已导出寿命拟合图与寿命分布图到: {out_dir}（格式 {'/'.join(exts)}）")
        except Exception as e:
            self.progress_bar.setVisible(False)
            QMessageBox.critical(self, "错误", f"导出失败: {str(e)}")

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

        fig = self.canvas.fig
        gs = GridSpec(2, 1, height_ratios=[7, 3])
        ax1 = fig.add_subplot(gs[0])
        ax1.scatter(time, decay, s=2, alpha=0.6, marker='o',
                    edgecolors='none', color="#66ccee", label='实验数据')
        ax1.plot(time, irf_shifted, linewidth=0.8, color="#ccbb44",
                 label=f'IRF（平移 {qshift_ns:.2g} ns）')
        ax1.plot(fit_time, y_fitted, linewidth=max(1.0, linewidth),
                 color="#ee6677", label=f"{info.get('method', 'MEM')} 拟合")
        ax1.set_yscale('log')
        ax1.set_ylim(bottom=1)
        ax1.set_ylabel('Counts (log)')
        ax1.legend(fontsize=9)
        ax1.set_title(custom_title or f"荧光寿命拟合 - {file_name}", fontsize=13)

        ax2 = fig.add_subplot(gs[1], sharex=ax1)
        ax2.plot(fit_time, residuals, linewidth=0.3, color="#ee6677")
        ax2.axhline(0, color=self._mpl_colors()['zero'], linewidth=0.5)
        ax2.set_xlabel('Time (ns)')
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
        # 曲线颜色随主题（原为黑色：深色主题下黑线压在深底上完全看不见）
        ax3.plot(tau, dist, linewidth=0.8, color=self._mpl_colors()['fg'],
                 label='MEM 分布')
        ax3.set_xscale('log')
        if dist.max() > 0:
            ax3.set_ylim(top=dist.max() * 1.4)
        ax3.set_xlabel(r'$\tau$ (ns)')
        ax3.set_ylabel('分布强度')
        ax3.set_title(f"寿命分布 - {file_name}", fontsize=12)
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
                ax3.fill_between(tau, 0, comp, alpha=0.5,
                                 label=(fr'$\tau_{{{n + 1}}} = {1 / peak[1]:.3g}$ ns, '
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

        fig = self.diag_canvas.fig
        fig.clf()
        gs = GridSpec(2, 1, height_ratios=[3, 2], hspace=0.35)
        ax1 = fig.add_subplot(gs[0])
        ax2 = fig.add_subplot(gs[1])

        # 辅助元素按主题取色（深色底上原来的 #7C3AED 只有 2.75:1，看不见）
        dark = getattr(self, 'theme', 'light') == 'dark'
        c_irf_raw = '#94a3b8' if dark else '#888888'
        c_marker = '#4ade80' if dark else '#16A34A'
        c_acf = '#a78bfa' if dark else '#7C3AED'
        c_ci = '#fb923c' if dark else '#EA580C'

        # ---- 上：IRF（原始/平移后）+ 衰减 + 拟合区间 ----
        scale = float(np.nanmax(decay)) if decay.size else 0.0
        scale = scale if scale > 0 else 1.0

        def _n(a):
            return a / scale

        if irf.size:
            irf_s = _n(irf)
            ax1.plot(time[:len(irf)], irf_s, linewidth=0.9, color=c_irf_raw,
                     label='IRF（原始）')
        if irf_shifted.size:
            ax1.plot(time[:len(irf_shifted)], _n(irf_shifted), linewidth=0.9,
                     color='#ccbb44',
                     label=f'IRF（平移 {qshift:.3g} ch = {qshift * dt:.3g} ns）')
        ax1.plot(time, _n(decay), linewidth=0.8, color='#66ccee', label='衰减数据')
        if y_fitted.size:
            ax1.plot(time[fit_start:fit_start + len(y_fitted)], _n(y_fitted),
                     linewidth=1.1, color='#ee6677', label='拟合')
        for x, lab, ha in ((time[fit_start], '拟合起点', 'left'),
                           (time[min(fit_end, len(time) - 1)], '拟合终点', 'right')):
            ax1.axvline(x, color=c_marker, linestyle='--', linewidth=0.8)
            ax1.annotate(lab, xy=(x, 0.94), xycoords=('data', 'axes fraction'),
                         xytext=(4 if ha == 'left' else -4, 0),
                         textcoords='offset points',
                         ha=ha, va='top', fontsize=9, color=c_marker)
        ax1.set_xlabel('Time (ns)')
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
            ax2.set_title(
                f"残差自相关（|ACF| > {ci:.3g} 的滞后点: {n_exceed} 个"
                f" → 越多说明残差越有结构）", fontsize=11)
        else:
            ax2.text(0.5, 0.5, "无残差数据", ha='center', va='center',
                     transform=ax2.transAxes,
                     color=self._mpl_colors()['muted'])
        ax2.set_xlabel('滞后 (通道)')
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
                     f"（{info['qshift_suggested'] * dt:.4g} ns）")
        lines.append(f"IRF FWHM = {info.get('irf_FWHM', float('nan')):.4g} ns")
        lines.append("")
        peaks = result.get('peak_result') or []
        if peaks:
            lines.append(f"检测到 {len(peaks)} 个寿命分量:")
            for n, (tau, area, _fwhm, _w) in enumerate(peaks, 1):
                lines.append(f"  τ{n} = {tau:.4g} ns, 占比 = {area * 100:.2f}%")
        else:
            lines.append("未分离出明显寿命分量（分布过宽）")
        fixed = info.get('fixed_taus') or []
        if fixed:
            amps = info.get('fixed_amplitudes') or []
            lines.append("")
            lines.append("固定分量（不受熵约束，幅度自动求解）:")
            for t, a in zip(fixed, amps):
                lines.append(f"  τ = {t:.4g} ns，幅度 = {a:.4g} counts")
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
                         "落在速率网格两端（可能为边界堆积，建议放宽 k 范围复算）")
        kmin, kmax = info.get('k_min'), info.get('k_max')
        if kmin and kmax:
            lines.append(f"速率网格 k = {kmin:g}–{kmax:g} /ns"
                         f"（τ {info.get('tau_max_ns', 0):.4g}–"
                         f"{info.get('tau_min_ns', 0):.4g} ns），"
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
            rows = [(f"τ{n}", tau, area * 100.0)
                    for n, (tau, area, _f, _w) in enumerate(peaks, 1)]
            for t in fixed:                      # 固定分量单独标注，避免与分离峰混看
                rows.append((f"固定 τ = {t:.4g}", float(t), float('nan')))

            table = getattr(self, 'fit_table', None)
            if table is not None:
                table.setSortingEnabled(False)
                try:
                    table.clearContents()
                    table.setRowCount(len(rows))
                    for r, (name, tau, share) in enumerate(rows):
                        name_item = QTableWidgetItem(str(name))
                        table.setItem(r, 0, name_item)
                        tau_item = NumericTableItem(f"{tau:.4g}")
                        tau_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                        table.setItem(r, 1, tau_item)
                        share_item = QTableWidgetItem(
                            "—" if not np.isfinite(share) else f"{share:.2f}")
                        share_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                        table.setItem(r, 2, share_item)
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

            written = _pl.export_fit_results(results, save_dir,
                                            name="lifetime_fit_results")
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
            try:
                if self.spectrum_type == 'emission':
                    y_scale = np.nanmax(np.abs(y))
                    if y_scale > 0:
                        peaks, _ = find_peaks(
                            np.abs(y), height=y_scale * peak_height,
                            distance=peak_distance, prominence=y_scale * 0.03)
                        for pw, pi in zip(wl[peaks], y[peaks]):
                            ax.annotate(self._peak_label(pw), xy=(pw, pi), xytext=(0, 5),
                                        textcoords='offset points', fontsize=9,
                                        color=colors[0], ha='center', va='bottom')
                else:
                    temp_data = {'wl': wl, 'absorption': y}
                    peaks = find_absorption_peaks(temp_data, min_height=peak_height,
                                                  min_distance=peak_distance)
                    for pw, pi in zip(peaks.get('peak_wavelengths', []),
                                      peaks.get('peak_intensities', [])):
                        ax.annotate(self._peak_label(pw), xy=(pw, pi), xytext=(0, 6),
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

        for i, file_name in enumerate(valid_files):
            data = self.data_cache[file_name]['data']
            wavelength, absorption = self._get_plot_xy(file_name, sub_cfg)

            ax.plot(wavelength, absorption,
                    label=self._build_legend_label(file_name, data),
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
                    for pw, pi in zip(peak_wls, peak_intens):
                        ax.annotate(
                            self._peak_label(pw),
                            xy=(pw, pi),
                            xytext=(0, 3),
                            textcoords='offset points',
                            fontsize=10,
                            color=colors[i],
                            ha='center',
                            va='bottom',
                            rotation=0,
                            alpha=0.8,
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
        wavelength, absorption = self._get_plot_xy(file_name, sub_cfg)

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
                for pw, pi in zip(peak_wls, peak_intens):
                    ax.annotate(
                        self._peak_label(pw),
                        xy=(pw, pi),
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
        normalize = getattr(self, 'normalize_check', None) is not None and self.normalize_check.isChecked()

        for i, file_name in enumerate(valid_files):
            data = self.data_cache[file_name]['data']
            wl, intensity = self._get_plot_xy(file_name, sub_cfg)
            if normalize and np.nanmax(intensity) > 0:
                intensity = intensity / np.nanmax(intensity)

            # 图例标签：说明.xlsx 信息或样品名 + EX
            label = self._build_legend_label(file_name, data)
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
                    for pw, pi in zip(wl[peaks], intensity[peaks]):
                        ax.annotate(self._peak_label(pw), xy=(pw, pi), xytext=(0, 5),
                                    textcoords='offset points', fontsize=9,
                                    color=colors[i], ha='center', va='bottom')
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
        wl, intensity = self._get_plot_xy(file_name, sub_cfg)
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
                    ax.annotate(self._peak_label(pw), xy=(pw, pi), xytext=(0, 8),
                                textcoords='offset points', fontsize=11,
                                color=colors[0], ha='center', va='bottom', fontweight='bold')
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

    def _on_plot_finished(self, fig):
        """绘图完成回调（主线程）"""
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
            self.status_bar.showMessage("图表更新完成")
        # v4.27：画布/空状态切换 + 状态栏徽标（有数据了就把引导页收起来）
        self._sync_empty_state()
        self._update_status_badges()

    def _on_plot_error(self, error_msg):
        """绘图错误回调"""
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

    def export_plot(self):
        """导出当前图表"""
        if not self.data_cache:
            QMessageBox.warning(self, "警告", "请先加载数据并生成图表！")
            return

        # 荧光寿命模式：一次导出两张图（拟合+残差合并图、寿命分布图）与 json
        if self.spectrum_type == "lifetime":
            default_dir = self._dialog_start_dir()
            save_dir = QFileDialog.getExistingDirectory(
                self, "选择保存目录", default_dir, QFileDialog.ShowDirsOnly)
            if save_dir:
                self._export_lifetime_plots(save_dir)
            return

        # 选择保存路径（默认指向当前数据文件夹；默认文件名 = 当前图表标题）
        default_dir = self._dialog_start_dir()
        default_name = (f"{self._safe_filename(self._current_plot_title())}"
                        f"{self._export_formats()[0]}")
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "导出图片",
            str(Path(default_dir) / default_name),
            "PNG文件 (*.png);;PDF文件 (*.pdf);;SVG文件 (*.svg);;所有文件 (*.*)"
        )

        if file_path:
            try:
                self._savefig_pub(self.canvas.fig, file_path)
                QMessageBox.information(self, "成功", f"图片已保存到:\n{file_path}")
                self.status_bar.showMessage(f"图片已保存: {file_path}")
            except Exception as e:
                log_exception(f"导出图片失败: {file_path}", e)
                QMessageBox.critical(self, "错误", f"导出失败: {str(e)}")

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
            dpi = self.dpi_spin.value()
            linewidth = self.linewidth_spin.value()
            mark_peaks = self.mark_peaks_check.isChecked()
            peak_height = self.peak_height_spin.value()
            peak_distance = self.peak_distance_spin.value()
            sub_cfg = self._get_subtract_config()
            custom_title = self.title_edit.text().strip()
            exts = self._export_formats()

            # 差谱模式（A − B）：预览画布上就是差谱，直接按标题导出这一张
            if sub_cfg and sub_cfg['mode'] == 'diff':
                plots_dir = save_path / "plots"
                plots_dir.mkdir(exist_ok=True)
                base = self._safe_filename(self._current_plot_title())
                out_paths = []
                for ext in exts:
                    out_path = plots_dir / f"{base}{ext}"
                    self._savefig_pub(self.canvas.fig, out_path, dpi)
                    out_paths.append(out_path)
                QMessageBox.information(
                    self, "成功",
                    "差谱图已保存到:\n" + "\n".join(str(p) for p in out_paths))
                self.status_bar.showMessage(f"已导出差谱图: {out_paths[0]}")
                return

            # 导出单独图（只导出勾选的文件；扣除本底时本底文件自身跳过）
            checked_files = self.get_checked_files()
            export_files = [f for f in checked_files if f in self.data_cache]
            if not export_files:
                export_files = list(self.data_cache.keys())
            if sub_cfg:
                export_files = [f for f in export_files if f != sub_cfg['b']]

            # 创建保存目录
            plots_dir = save_path / "plots"
            plots_dir.mkdir(exist_ok=True)

            # 文件名去重：自定义标题时每张单图曾共用同一名字，互相覆盖后只剩 1 张
            used = {}

            def _unique(base):
                n = used.get(base, 0) + 1
                used[base] = n
                return base if n == 1 else f"{base}_{n}"

            self.progress_bar.setVisible(True)
            self.progress_bar.setRange(0, len(export_files) + 1)
            n_ok, failures = 0, []

            for i, file_name in enumerate(export_files):
                try:
                    fig, title = self._render_single_export_fig(
                        file_name, linewidth, mark_peaks, peak_height,
                        peak_distance, sub_cfg, custom_title)
                    base = self._safe_filename(title)
                    if custom_title:      # 自定义标题时补上样品名，避免同名
                        base = f"{base}_{self._safe_filename(self._sample_name(file_name))}"
                    base = _unique(base)
                    for ext in exts:
                        self._savefig_pub(fig, plots_dir / f"{base}{ext}", dpi)
                    plt.close(fig)
                    n_ok += 1
                    self.progress_bar.setValue(i + 1)
                    QApplication.processEvents()

                except Exception as e:
                    failures.append(f"{file_name}: {e}")
                    logging.warning("导出 %s 失败: %s", file_name, e)

            # 导出合并图（只导出勾选的数据）
            try:
                fig, title = self._render_combined_export_fig(
                    export_files, linewidth, sub_cfg, custom_title)
                base = _unique(self._safe_filename(title))
                for ext in exts:
                    self._savefig_pub(fig, plots_dir / f"{base}{ext}", dpi)
                plt.close(fig)
                n_ok += 1
                self.progress_bar.setValue(len(export_files) + 1)

            except Exception as e:
                failures.append(f"合并图: {e}")
                logging.warning("导出合并图失败: %s", e)

            self.progress_bar.setVisible(False)
            msg = (f"所有图片已保存到:\n{plots_dir}\n"
                   f"格式 {'/'.join(e.lstrip('.') for e in exts)}\n"
                   f"成功 {n_ok} 张，失败 {len(failures)} 张")
            if failures:
                msg += "\n\n失败明细（前 5 条）:\n" + "\n".join(failures[:5])
                QMessageBox.warning(self, "部分失败", msg)
            else:
                QMessageBox.information(self, "成功", msg)
            self.status_bar.showMessage(f"已导出所有图片到: {plots_dir}")

        except Exception as e:
            QMessageBox.critical(self, "错误", f"导出失败: {str(e)}")
            self.progress_bar.setVisible(False)

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
            with open(jp, 'w', encoding='utf-8') as f:
                _json.dump(res['stats'], f, ensure_ascii=False, indent=2,
                           default=float)
            exported.append(jp)
        QMessageBox.information(
            self, "成功", "已导出:\n" + "\n".join(str(p) for p in exported))
        self.status_bar.showMessage(f"已导出 3D 扫描图到: {plots_dir}")

    def _render_single_export_fig(self, file_name, linewidth, mark_peaks,
                                  peak_height, peak_distance, sub_cfg,
                                  custom_title=""):
        """「导出全部」用：渲染单个文件的光谱图（吸收/发射风格与预览一致）。

        返回 (fig, 标题)；标题同时用作导出文件名。
        """
        fig, ax = plt.subplots(figsize=self._pub_figsize((8.0, 5.0)))
        self.setup_chinese_font()
        data = self.data_cache[file_name]['data']
        wl, y = self._get_plot_xy(file_name, sub_cfg)
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
                        ax.annotate(self._peak_label(pw), xy=(pw, pi), xytext=(0, 8),
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
                    ax.annotate(
                        self._peak_label(pw), xy=(pw, pi), xytext=(0, 6),
                        textcoords='offset points', fontsize=11,
                        color=colors[0], ha='center', va='bottom',
                        rotation=0, alpha=0.9, fontweight='bold')

        self._apply_legend(ax)
        ax.set_xlabel('波长 (nm)')
        if custom_title:
            title = custom_title
        ax.set_title(title)
        self._grid(ax)
        fig.tight_layout()
        return fig, title

    def _render_combined_export_fig(self, export_files, linewidth, sub_cfg,
                                    custom_title=""):
        """「导出全部」用：渲染合并图（吸收/发射风格与预览一致）。返回 (fig, 标题)。"""
        fig, ax = plt.subplots(figsize=self._pub_figsize())
        self.setup_chinese_font()
        is_emission = self.spectrum_type == "emission"
        normalize = (is_emission
                     and getattr(self, 'normalize_check', None) is not None
                     and self.normalize_check.isChecked())
        # 与预览图同一套取色规则（按文件身份），保证导出的图和预览一致
        colors = self._stable_colors(export_files, self.get_color_map())

        for i, file_name in enumerate(export_files):
            data = self.data_cache[file_name]['data']
            wl, y = self._get_plot_xy(file_name, sub_cfg)
            if normalize and np.nanmax(y) > 0:
                y = y / np.nanmax(y)
            ax.plot(wl, y, linewidth=linewidth, color=colors[i],
                    label=self._build_legend_label(file_name, data))
            if is_emission:
                ex_wl = data.get('ex_wl', data.get('ex'))
                if (getattr(self, 'show_ex_check', None) is not None
                        and self.show_ex_check.isChecked() and ex_wl is not None):
                    ax.axvline(ex_wl, color=colors[i], linestyle='--',
                               linewidth=1, alpha=0.5)

        ax.set_xlabel('波长 (nm)')
        ax.set_ylabel('归一化强度' if normalize
                      else ('发射强度 (AU)' if is_emission else '吸收值 (AU)'))
        title = custom_title or ('发射光谱对比' if is_emission else '吸收光谱对比')
        ax.set_title(title)
        self._apply_legend(ax)
        self._grid(ax)
        fig.tight_layout()
        return fig, title
