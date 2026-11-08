# -*- coding: utf-8 -*-
"""
数据混入：负责读取数据文件夹、加载吸收/发射光谱、展示信息、增强图例。
"""

import logging
import re
import sys
from pathlib import Path

import numpy as np
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QCursor
from PyQt5.QtWidgets import (
    QMessageBox, QFileDialog, QListWidgetItem, QApplication,
)

from gui_config import DEFAULT_WORKSPACE, THEMES
from gui_log import log_exception, log_file_path, setup_logging
from plot_absorption import load_absorption_spectra, find_absorption_peaks
from plot_emission import load_spectra as load_emission_spectra
from plot_lifetime import (parse_decay_csv, parse_decay_xlsx,
                           TIME_UNIT_KEYS, unit_symbol, unit_factor)
from read_xlsx_info import load_xlsx_info, match_number

# 将父目录加入 Python 路径，便于独立导入绘图模块
_parent = Path(__file__).resolve().parent.parent
if str(_parent) not in sys.path:
    sys.path.insert(0, str(_parent))

# 停靠布局状态的版本号（v4.29）。QMainWindow.saveState/restoreState 的 version
# 参数：以后若增删/重命名 dock，只要把版本号 +1，旧设置就会被安全忽略。
_DOCK_STATE_VERSION = 1


class DataMixin:
    """数据加载、工作区/文件夹选择、信息展示与说明.xlsx 图例增强。"""

    def on_tree_clicked(self, index):
        """单击目录树：只展开/选中，不加载数据（D2）。

        旧实现在单击时直接解析整个文件夹，用户只想展开子目录也会触发加载，
        还会把空目录写进「最近文件夹」。现在加载改到双击（见 on_tree_double_clicked）。
        """
        try:
            # 点在展开箭头/缩进区域时不强制展开，保留默认的折叠能力
            try:
                pos = self.tree.viewport().mapFromGlobal(QCursor.pos())
                rect = self.tree.visualRect(index)
                if rect.isValid() and pos.x() < rect.left():
                    return
            except Exception:
                pass
            self.tree.setCurrentIndex(index)
            if not self.tree.isExpanded(index):
                self.tree.expand(index)
        except Exception as e:
            log_exception("展开目录失败", e)

    def on_tree_double_clicked(self, index):
        """双击目录树：加载该文件夹的数据（D2）。"""
        try:
            folder_path = self.file_system_model.filePath(index)
            if folder_path and Path(folder_path).is_dir():
                self.load_data_from_folder(folder_path)
        except Exception as e:
            log_exception("加载目录失败", e)

    def _get_saved_workspace(self):
        """读取上次保存的工作区；若已失效则回退到默认工作区"""
        try:
            saved = self.settings.value("workspace", "", str)
            if saved and Path(saved).is_dir():
                return str(saved)
        except Exception:
            pass
        # 默认工作区（可能含 Windows 路径）；若不存在（如在 macOS 上）则回退到用户主目录
        if DEFAULT_WORKSPACE and Path(DEFAULT_WORKSPACE).is_dir():
            return DEFAULT_WORKSPACE
        return str(Path.home())

    @staticmethod
    def _short_path(p, max_parts=2):
        """长路径缩成「…\\父目录\\末级目录」，避免在窄栏里被截断（v4.19）。"""
        try:
            parts = Path(p).parts
            if len(parts) <= max_parts + 1:
                return str(p)
            return "…\\" + "\\".join(parts[-max_parts:])
        except Exception:
            return str(p)

    def _save_settings(self):
        """保存当前设置到 QSettings"""
        try:
            self.settings.sync()
        except Exception:
            pass

    # ---------- D5：最近文件夹 ----------

    RECENT_MAX = 6

    def _get_recent_folders(self):
        """读取最近文件夹列表（自动剔除已失效的路径）"""
        try:
            val = self.settings.value("recent_folders", [], list)
            return [str(v) for v in (val or []) if Path(str(v)).is_dir()]
        except Exception:
            return []

    def _push_recent_folder(self, path):
        """把刚加载的文件夹推到最近列表头部并持久化"""
        try:
            path = str(Path(path))
            items = [p for p in self._get_recent_folders() if p != path]
            items.insert(0, path)
            items = items[:self.RECENT_MAX]
            self.settings.setValue("recent_folders", items)
            self._save_settings()
            self._refresh_recent_combo()
        except Exception as e:
            log_exception("记录最近文件夹失败", e)

    def _refresh_recent_combo(self):
        """把最近文件夹刷进下拉框（第一项为占位「（无）」）"""
        if not hasattr(self, 'recent_combo'):
            return
        items = self._get_recent_folders()
        self.recent_combo.blockSignals(True)
        self.recent_combo.clear()
        self.recent_combo.addItem("（无）")
        for p in items:
            name = Path(p).name or p
            self.recent_combo.addItem(f"{name} — {p}")
        self.recent_combo.blockSignals(False)

    def on_recent_folder_selected(self, index):
        """选择最近文件夹即加载"""
        if index <= 0:
            return
        items = self._get_recent_folders()
        if index - 1 < len(items):
            self.load_data_from_folder(items[index - 1])

    # ---------- D2/E1：会话保存与恢复 ----------

    # 会话白名单：(QSettings 键, 控件属性名, 类型)
    #   "combo" → QComboBox（存索引）；"bool" → QCheckBox
    #   "int" / "float" → QSpinBox / QDoubleSpinBox / SliderSpin（取 value()）
    #   "str" → QLineEdit（取 text()）
    # 只有列在这里的控件才会被保存/恢复。原 _SESSION_KEYS 定义了却从未被引用
    # （死代码），这里改造成真正生效的白名单并循环读写（E1）。
    _SESSION_SPECS = (
        ("param/linewidth", "linewidth_spin", "float"),
        ("param/dpi", "dpi_spin", "int"),
        ("param/export_format", "export_format_combo", "combo"),
        ("param/pub_preset", "pub_preset_combo", "combo"),
        ("param/legend_pos", "legend_pos_combo", "combo"),
        ("param/color", "color_combo", "combo"),
        ("param/ratio", "ratio_combo", "combo"),
        ("param/mark_peaks", "mark_peaks_check", "bool"),
        ("param/peak_value", "peak_value_check", "bool"),
        ("param/normalize", "normalize_check", "bool"),
        ("param/show_ex", "show_ex_check", "bool"),
        ("param/export_white", "export_white_check", "bool"),
        ("param/lifetime_method", "lifetime_method_combo", "combo"),
        ("param/lifetime_nrates", "lifetime_nrates_spin", "int"),
        # 单位必须排在这两个 τ 键**前面**：恢复顺序决定"先切单位再读数值"，
        # 否则会话里按 μs 存的 τ 会先被当成 ns 读进来、再被单位切换换算一次（v4.39）
        ("param/lifetime_unit", "lifetime_unit_combo", "combo"),
        ("param/lifetime_taumin", "lifetime_taumin_spin", "float"),
        ("param/lifetime_taumax", "lifetime_taumax_spin", "float"),
        ("param/lifetime_fixed_taus", "lifetime_fixed_taus_edit", "str"),
        ("param/scan3d_plot", "scan3d_plot_combo", "combo"),
        ("param/scan3d_comb", "scan3d_comb_combo", "combo"),
        ("param/scan3d_despike", "scan3d_despike_spin", "int"),
        ("param/scan3d_sigma_em", "scan3d_sigma_em_spin", "float"),
        ("param/scan3d_sigma_ex", "scan3d_sigma_ex_spin", "float"),
        ("param/scan3d_log", "scan3d_log_check", "bool"),
        ("param/peak_height", "peak_height_spin", "float"),
        ("param/peak_distance", "peak_distance_spin", "float"),
        ("param/subtract_enable", "subtract_enable_check", "bool"),
        ("param/title", "title_edit", "str"),
        ("param/wl_min", "wl_min_spin", "float"),
        ("param/wl_max", "wl_max_spin", "float"),
        ("param/integ_min", "integ_min_spin", "float"),
        ("param/integ_max", "integ_max_spin", "float"),
    )

    # v4.38：寿命拟合范围的输入从速率 k(1/ns) 改成寿命 τ(ns)。旧设置里存的是 k，
    # 这里做一次性换算（τ_min = 1/k_max、τ_max = 1/k_min），否则老用户升级后
    # 会把 k 的数值直接当 τ 用（例如 k_min=0.005 会被当成 τ_max=0.005 ns）。
    _TAU_RANGE_MIGRATION_FLAG = "migrated/tau_range_v438"

    def _migrate_lifetime_range_keys(self, s):
        """把旧版存在 QSettings 里的 lifetime_kmin/kmax 换算成 τ 键（只做一次）。

        同时处理 param/*（上次会话）与 defaults/*（存为默认值）两套键；
        只要新键已存在就跳过，避免覆盖用户升级后新填的 τ。
        """
        try:
            if s.value(self._TAU_RANGE_MIGRATION_FLAG, False, bool):
                return
            for prefix in ("param/", "defaults/"):
                if (s.value(prefix + "lifetime_taumin", None) is not None
                        or s.value(prefix + "lifetime_taumax", None) is not None):
                    continue                       # 已经存过 τ，不动
                try:
                    k_lo = float(s.value(prefix + "lifetime_kmin", None))
                    k_hi = float(s.value(prefix + "lifetime_kmax", None))
                except (TypeError, ValueError):
                    continue
                if 0 < k_lo < k_hi:
                    s.setValue(prefix + "lifetime_taumin", 1.0 / k_hi)
                    s.setValue(prefix + "lifetime_taumax", 1.0 / k_lo)
                    logging.getLogger('spectra').info(
                        "寿命范围设置已从 k 换算为 τ：%s %.6g–%.6g 1/ns → "
                        "%.6g–%.6g ns", prefix, k_lo, k_hi, 1.0 / k_hi, 1.0 / k_lo)
            s.setValue(self._TAU_RANGE_MIGRATION_FLAG, True)
            s.sync()
        except Exception as e:
            log_exception("换算旧版寿命范围设置失败", e)

    # ---------- v4.39：寿命时间单位（全局设置：τ / 时间轴的输入与显示单位） ----------
    # 设计要点：**内部拟合永远按 ns 计算**，单位只作用于「用户输入」与「界面显示」。
    # 因此切换单位只换算输入框里的数值（保持物理量不变）并按新单位重画，
    # 不重新拟合、也不改变任何拟合结果。

    def _lifetime_unit_key(self):
        """当前「时间单位」下拉框对应的键（'ns' / 'us'），异常时回退 'ns'。"""
        combo = getattr(self, 'lifetime_unit_combo', None)
        if combo is None:
            return TIME_UNIT_KEYS[0]
        try:
            idx = int(combo.currentIndex())
        except Exception:
            return TIME_UNIT_KEYS[0]
        return TIME_UNIT_KEYS[idx] if 0 <= idx < len(TIME_UNIT_KEYS) \
            else TIME_UNIT_KEYS[0]

    def _apply_lifetime_tau_spin_ranges(self):
        """按当前单位设置 τ 输入框的小数位与量程（物理范围恒为 1 ps – 1e9 ns）。"""
        f = float(getattr(self, 'lifetime_unit_factor', 1.0) or 1.0)
        # μs 下需要 6 位小数才能表示下限 0.001 ns = 1e-6 μs
        dec = 3 if f <= 1.0 else 6
        for name in ('lifetime_taumin_spin', 'lifetime_taumax_spin'):
            spin = getattr(self, name, None)
            if spin is None:
                continue
            spin.setDecimals(dec)
            spin.setRange(0.001 / f, 1e9 / f)

    def _refresh_lifetime_unit(self, convert=False):
        """同步单位缓存 + 界面文案；convert=True 时把 τ 输入框数值换算到新单位。

        τ(新单位) = τ(旧单位) × 旧因子 ÷ 新因子 —— 保证物理量不变
        （ns → μs：100 ns 变成 0.1 μs）。
        """
        key = self._lifetime_unit_key()
        old_factor = float(getattr(self, 'lifetime_unit_factor', 1.0) or 1.0)
        new_factor = unit_factor(key)
        self.lifetime_unit = key
        self.lifetime_unit_symbol = unit_symbol(key)
        self.lifetime_unit_factor = new_factor
        sym = self.lifetime_unit_symbol
        try:
            if hasattr(self, 'lifetime_taumin_label'):
                self.lifetime_taumin_label.setText(f"τ_min ({sym}):")
            if hasattr(self, 'lifetime_taumax_label'):
                self.lifetime_taumax_label.setText(f"τ_max ({sym}):")
            if hasattr(self, 'lifetime_fixed_tau_label'):
                self.lifetime_fixed_tau_label.setText(f"固定 τ ({sym}):")
            # 信息页「拟合摘要」卡片的 τ 列表头
            if hasattr(self, 'fit_table'):
                self.fit_table.setHorizontalHeaderLabels(
                    ["分量", f"τ ({sym})", "强度占比 (%)", "振幅占比 (%)"])
        except Exception as e:
            log_exception("更新时间单位标签失败", e)
        if not convert or new_factor == old_factor:
            return
        ratio = old_factor / new_factor
        spin_lo = getattr(self, 'lifetime_taumin_spin', None)
        spin_hi = getattr(self, 'lifetime_taumax_spin', None)
        if spin_lo is None or spin_hi is None:
            return
        # 先算好换算后的数值（此时控件还是旧量程，不能让 setRange 提前夹掉旧值）
        lo_new = float(spin_lo.value()) * ratio
        hi_new = float(spin_hi.value()) * ratio
        self._tau_range_syncing = True          # 换算期间不让"越界让路"掺和
        try:
            self._apply_lifetime_tau_spin_ranges()
            spin_lo.setValue(lo_new)
            spin_hi.setValue(hi_new)
            # 固定 τ 文本同步换算
            try:
                raw = self.lifetime_fixed_taus_edit.text().replace('，', ',')
                vals = [float(x) for x in raw.replace(' ', '').split(',')
                        if x.strip()]
                if vals:
                    self.lifetime_fixed_taus_edit.setText(
                        ", ".join(f"{v * ratio:g}" for v in vals))
            except Exception:
                pass
        finally:
            self._tau_range_syncing = False
        # 换算后若越界（极端量程边界）直接兜底，不借用"发送者"判断
        try:
            lo = float(spin_lo.value())
            hi = float(spin_hi.value())
            if not 0 < lo < hi:
                spin_hi.setValue(lo * 10.0)
        except Exception:
            pass

    def on_lifetime_unit_changed(self, *args):
        """「时间单位」切换（v4.39）：换算输入数值 → 刷新标签 → 用缓存结果重画。

        重画走 `_rerender_lifetime_cosmetic`（纯显示），**不触发重新拟合**。
        启动恢复会话时会连本槽一起触发（此时是"把面板默认值从旧单位换算到会话单位"，
        紧接着会话里的 τ 数值会覆盖它），所以恢复期间不弹状态栏提示。
        """
        old_sym = getattr(self, 'lifetime_unit_symbol', 'ns')
        self._refresh_lifetime_unit(convert=True)
        sym = self.lifetime_unit_symbol
        if getattr(self, '_restoring_session', False):
            return                      # 启动恢复阶段：不提示、不重画（也没有结果可重画）
        has_result = bool(getattr(self, '_last_lifetime_result', None))
        if has_result:
            try:
                self._rerender_lifetime_cosmetic()
            except Exception as e:
                log_exception("切换时间单位后重画失败", e)
        if hasattr(self, 'status_bar'):
            tail = ("图/信息页已按新单位刷新，拟合结果本身不变"
                    if has_result else "τ 输入框与坐标轴单位已切换")
            self.status_bar.showMessage(
                f"时间单位：{old_sym} → {sym}（{tail}）", 8000)

    def _apply_lifetime_unit(self):
        """启动时按会话记住的单位刷新缓存与标签。

        （数值本来就是按该单位存的，所以**不换算**，只刷新缓存/文案/量程。）
        """
        self._refresh_lifetime_unit(convert=False)
        try:
            self._apply_lifetime_tau_spin_ranges()
        except Exception as e:
            log_exception("按时间单位设置 τ 量程失败", e)

    def tau_disp(self, tau_ns, fmt='.4g'):
        """ns 的寿命值 → 当前单位下的字符串（不含单位符号）。"""
        try:
            return format(float(tau_ns) / float(self.lifetime_unit_factor), fmt)
        except Exception:
            return "nan"

    def tau_unit_symbol(self):
        """当前单位符号（'ns' / 'μs'）。"""
        return getattr(self, 'lifetime_unit_symbol', 'ns')

    def _sync_mode_groups_visibility(self):
        """按当前 self.spectrum_type 同步各模式专用参数组的显隐（v5.0.7）。

        从 ``on_spectrum_type_changed`` 里抽出来，好让 ``__init__`` 也能复用：
        各选项组建出来时全是 ``setVisible(False)``，只靠信号显示；而初始
        index 就是 0（吸收），``setCurrentIndex(0)`` 不产生变化信号，
        信号永不触发 → 首帧所有模式专用组都停在隐藏态。

        本函数**只动显隐与标定下拉框**，不清缓存、不重载数据——
        所以可以在 ``__init__`` 阶段安全调用。
        """
        is_lifetime = self.spectrum_type == "lifetime"
        is_scan3d = self.spectrum_type == "scan3d"
        is_spectrum = not is_lifetime and not is_scan3d
        if hasattr(self, 'emission_options_group'):
            self.emission_options_group.setVisible(self.spectrum_type == "emission")
        if hasattr(self, 'lifetime_options_group'):
            self.lifetime_options_group.setVisible(is_lifetime)
        if hasattr(self, 'scan3d_options_group'):
            self.scan3d_options_group.setVisible(is_scan3d)
        # 谱带分解与标定只对吸收/发射这种「一条条谱」有意义：
        # 寿命模式的数据是衰减曲线（横轴是时间）、3D 是矩阵，都没有"谱带"概念。
        if hasattr(self, 'bands_options_group'):
            self.bands_options_group.setVisible(is_spectrum)
        if hasattr(self, 'calib_options_group'):
            self.calib_options_group.setVisible(is_spectrum)
        if is_spectrum:
            # 标定的横轴变量来自说明.xlsx；换模式/换文件夹后列可能变，
            # 这里刷一次，避免下拉框里留着上一个文件夹的列名。
            try:
                self._refresh_calib_xvars()
            except Exception as _e:
                log_exception("刷新标定变量列表失败", _e)
        # 寿命专属的导出动作（「导出 ▾」菜单里的四项）跟着模式走。
        # 放在本函数里而不是调用方，是为了让 __init__ 的首帧也正确——
        # 否则吸收模式下这几项会停在"可见"，用户能点到没有意义的菜单项。
        for _attr in ('act_export_sep', 'act_export_fit',
                      'act_summary_plot', 'act_pdf_report'):
            _act = getattr(self, _attr, None)
            if _act is not None:
                try:
                    _act.setVisible(is_lifetime)
                except Exception:
                    pass

    def _refresh_calib_xvars(self):
        """把说明.xlsx 的数值列填进「标定」的横轴变量下拉框（v5.0.7）。

        与「数据比较」共用同一套判定（是不是真的说明表），但**独立一个下拉框**：
        数据比较的横轴与标定的横轴经常不是同一列（比如比较看 RB浓度、
        标定想按 Ce6浓度 做），共用一个会让用户改了一个另一个跟着变。
        """
        combo = getattr(self, 'calib_xvar_combo', None)
        btn = getattr(self, 'calib_run_btn', None)
        if combo is None:
            return
        info = getattr(self, 'xlsx_info', None)
        cols = list(info.numeric_columns()) if (info is not None and info.numbers) else []

        prev = combo.currentText()
        combo.blockSignals(True)
        try:
            combo.clear()
            if cols:
                combo.addItems(cols)
                if prev in cols:
                    combo.setCurrentText(prev)
                if btn is not None:
                    btn.setEnabled(True)
                    btn.setToolTip(
                        "把每条谱压成一个读数（沿用「数据比较」的纵轴口径），"
                        "做线性回归，\n给出斜率 / 截距 / R² / 回归标准误 / "
                        "LOD / LOQ / 线性范围。\n\n"
                        "跑之前先做可比性预检：激发波长或带宽不一致、"
                        "扫描被截断的文件\n会自动排除在回归之外"
                        "（否则 LOD 会被算歪）。")
            else:
                reason = ("未找到说明.xlsx" if info is None
                          else "说明.xlsx 无数值列")
                combo.addItem(f"（{reason}）")
                if btn is not None:
                    btn.setEnabled(False)
                    btn.setToolTip(f"标定需要在数据文件夹里放 说明.xlsx "
                                   f"（当前：{reason}）")
        finally:
            combo.blockSignals(False)

    def _save_session(self):
        """保存会话：模式 / 文件夹 / 窗口几何 / 白名单参数（D2 + E1）。"""
        try:
            s = self.settings
            if hasattr(self, 'spectrum_type_combo'):
                s.setValue("last_mode",
                           int(self.spectrum_type_combo.currentIndex()))
            if getattr(self, 'current_folder', None):
                s.setValue("last_folder", str(self.current_folder))
            try:
                s.setValue("geometry", self.saveGeometry())
            except Exception:
                pass
            # 三栏折叠状态 + 各栏宽度（v4.26：宽度记忆）
            try:
                if hasattr(self, '_col_hidden'):
                    s.setValue("ui/panel_hidden",
                               [1 if h else 0 for h in self._col_hidden])
                    s.setValue("ui/panel_widths",
                               [int(w) for w in self._col_widths])
                # 停靠布局（v4.29）：浮动 / 拖动换位 / 叠成标签页的状态整包存下来。
                # 版本号随 saveState 一起写，将来改了 dock 结构不会读回坏数据。
                if hasattr(self, '_panel_docks'):
                    s.setValue("ui/dock_state", self.saveState(_DOCK_STATE_VERSION))
            except Exception:
                pass
            # 白名单控件循环保存（E1）
            for key, attr, kind in self._SESSION_SPECS:
                w = getattr(self, attr, None)
                if w is None:
                    continue
                try:
                    if kind == "combo":
                        s.setValue(key, int(w.currentIndex()))
                    elif kind == "bool":
                        s.setValue(key, bool(w.isChecked()))
                    elif kind == "int":
                        s.setValue(key, int(w.value()))
                    elif kind == "float":
                        s.setValue(key, float(w.value()))
                    else:
                        s.setValue(key, str(w.text()))
                except Exception:
                    continue
            # 「自动拟合 λ」按用户要求每次启动都强制勾选，这里仍记录当前值供排查，
            # 但恢复时**不读取**（否则旧的 False 会覆盖默认的 True）
            if hasattr(self, 'lifetime_auto_lambda_check'):
                s.setValue("param/lifetime_auto_lambda",
                           bool(self.lifetime_auto_lambda_check.isChecked()))
            s.setValue("theme", getattr(self, 'theme', 'light'))
            self._save_settings()
        except Exception as e:
            log_exception("保存会话失败", e)

    def _restore_session(self):
        """恢复上次会话（D2/E1）。异常一律忽略，保证启动不因旧配置失败。"""
        s = self.settings
        # v4.38：先把旧版（k 单位）的寿命范围设置换算成 τ，再走正常恢复流程
        self._migrate_lifetime_range_keys(s)
        # v4.39：恢复期间抑制「时间单位」切换的提示/重画（见 on_lifetime_unit_changed）
        self._restoring_session = True
        try:
            self._restore_session_body(s)
        finally:
            self._restoring_session = False

    def _restore_session_body(self, s):

        def _flag(key, default):
            v = s.value(key, default)
            if isinstance(v, str):
                return v.strip().lower() in ('true', '1', 'yes')
            return bool(v)

        try:
            # 白名单控件循环恢复（E1）
            # v4.45：τ 的两个框必须**先 τ_max 后 τ_min** 恢复。
            # 反过来的话，先设的 τ_min（比如 500）会触发 _sync_lifetime_tau_range
            # 把 τ_max 抬到 5000，接着设 τ_max=10 又被 τ_min 顶回去，来回互踩；
            # 若两个值恰好相等（如都 0.001）则谁也拆不开，最终停在
            # τ_min == τ_max 的非法状态，而 _collect_plot_params 会静默回退默认
            # 范围 —— 界面显示与实际拟合用的范围不一致（实测复现）。
            specs = list(self._SESSION_SPECS)
            _tau_max_first = []
            _others = []
            for item in specs:
                key = item[0]
                if key.endswith("lifetime_taumax"):
                    _tau_max_first.append(item)
                else:
                    _others.append(item)
            # τ_min 排到 τ_max 之后
            ordered = [it for it in _others
                       if not it[0].endswith("lifetime_taumin")]
            ordered += _tau_max_first
            ordered += [it for it in _others
                        if it[0].endswith("lifetime_taumin")]
            for key, attr, kind in ordered:
                w = getattr(self, attr, None)
                if w is None:
                    continue
                try:
                    if kind == "combo":
                        idx = int(s.value(key, w.currentIndex()))
                        if 0 <= idx < w.count():
                            w.setCurrentIndex(idx)
                    elif kind == "bool":
                        w.setChecked(_flag(key, w.isChecked()))
                    elif kind == "int":
                        w.setValue(int(float(s.value(key, w.value()))))
                    elif kind == "float":
                        w.setValue(float(s.value(key, w.value())))
                    else:
                        w.setText(str(s.value(key, w.text(), str)))
                except Exception:
                    continue
            # 「自动拟合 λ」按用户要求**每次启动都默认勾选**（不从上会话恢复），
            # 否则旧的 False 会覆盖默认值
            if hasattr(self, 'lifetime_auto_lambda_check'):
                self.lifetime_auto_lambda_check.setChecked(True)
            # 窗口几何
            geo = s.value("geometry", None)
            if geo is not None:
                try:
                    self.restoreGeometry(geo)
                except Exception:
                    pass
            # 三栏折叠状态与宽度（v4.26）
            self._restore_panel_state(s)
            # 上次文件夹（不触发加载，等模式设置好后再加载）
            last_folder = s.value("last_folder", "", str)
            if last_folder and Path(last_folder).is_dir():
                self.current_folder = Path(last_folder)
                # E2：会话里已存了用户手填的波长范围，恢复后的首次加载不要再
                # 用数据范围覆盖它（等同「该文件夹本次已自动设过范围」）
                try:
                    self._ranged_folders().add(str(Path(last_folder)))
                except Exception:
                    pass
                if hasattr(self, 'folder_label'):
                    self.folder_label.setText(
                        f"文件夹: {self._short_path(last_folder)}")
                    self.folder_label.setToolTip(str(last_folder))
            # 主题（D3 / v4.30 起三套：light / dark / contrast）
            # v4.46：没有保存过主题时（首次启动）跟随操作系统深浅色，
            # 而不是硬用浅色——否则 Windows 深色用户第一次打开是白界面。
            from gui_config import detect_system_theme
            theme = s.value("theme", detect_system_theme(), str)
            if theme in THEMES:
                self.theme = theme
                if hasattr(self, '_update_theme_btn_tip'):
                    # 图标由 apply_style → _apply_ui_icons 按主题设置，这里只管 tooltip
                    self._update_theme_btn_tip()
                if hasattr(self, 'apply_style'):
                    self.apply_style()
                if hasattr(self, '_apply_mpl_theme'):
                    self._apply_mpl_theme()
            self._refresh_recent_combo()
        except Exception as e:
            log_exception("恢复会话失败", e)

    def _restore_panel_state(self, s):
        """恢复三栏停靠布局、收起状态与宽度（v4.26 建立 / v4.29 Dock 版）。

        顺序：先读整包停靠状态（浮动 / 换位 / 叠标签），再用

            ui/panel_hidden + ui/panel_widths

        覆盖显隐与宽度——这两个键是"每栏最终该多宽/是否显示"的权威记录，
        坏值一律忽略，任何异常都退回默认布局。
        """
        if not hasattr(self, 'toggle_panel'):
            return
        try:
            # 1) 整包停靠状态（v4.29）：失败就当没存过，不影响下面的恢复
            state = s.value("ui/dock_state", None)
            if state is not None and hasattr(self, '_panel_docks'):
                try:
                    if self.restoreState(state, _DOCK_STATE_VERSION):
                        for i, dock in enumerate(self._panel_docks):
                            self._col_hidden[i] = not dock.isVisible()
                except Exception as e:
                    logging.warning("恢复停靠布局失败（忽略，用默认）: %s", e)

            # 2) 各栏宽度
            widths = s.value("ui/panel_widths", None)
            if widths is not None:
                vals = widths if isinstance(widths, (list, tuple)) else [widths]
                for i, v in enumerate(list(vals)[:3]):
                    try:
                        w = int(float(v))
                    except Exception:
                        continue
                    # 只接受合理值：太小/太大一律忽略（防止坏设置把界面搞乱）
                    if 80 <= w <= 1200:
                        self._col_widths[i] = w
            # 3) 收起 / 展开
            hidden = s.value("ui/panel_hidden", None)
            if hidden is not None:
                vals = hidden if isinstance(hidden, (list, tuple)) else [hidden]
                for i, v in enumerate(list(vals)[:3]):
                    flag = str(v).strip().lower() not in ("0", "false", "", "none")
                    self.toggle_panel(i, collapsed=flag)
            self._apply_col_sizes()
        except Exception as e:
            log_exception("恢复栏布局失败", e)

    # 「存为默认值」的荧光寿命拟合参数（v4.22 修订）。
    # 键前缀 defaults/ 与上次会话的 param/ 分开：启动时在 _restore_session 之后
    # 套用，因此**优先级高于上次会话**——用户显式固定过的那组参数说了算。
    _LIFETIME_DEFAULT_SPECS = (
        ("lifetime_method", "lifetime_method_combo", "combo"),
        ("lifetime_nrates", "lifetime_nrates_spin", "int"),
        ("lifetime_taumin", "lifetime_taumin_spin", "float"),
        ("lifetime_taumax", "lifetime_taumax_spin", "float"),
        ("lifetime_fixed_taus", "lifetime_fixed_taus_edit", "str"),
        ("lifetime_lambda", "lifetime_lambda_spin", "float"),
        ("lifetime_auto_lambda", "lifetime_auto_lambda_check", "bool"),
    )

    @staticmethod
    def _convert_taus_text(text, factor):
        """把「逗号分隔的 τ 文本」整体乘 factor（解析不了的项原样保留）。

        v4.39：用于「固定 τ」在 当前时间单位 ↔ ns 之间换算。
        """
        out = []
        for tok in str(text or '').replace('，', ',').split(','):
            s = tok.strip()
            if not s:
                continue
            try:
                out.append(f"{float(s) * factor:g}")
            except ValueError:
                out.append(s)
        return ", ".join(out)

    def _save_lifetime_defaults(self):
        """把当前荧光寿命拟合参数存为默认值（QSettings defaults/*）。

        与「上次会话」的区别：会话是每次关闭自动覆盖的，而默认值只有点这个
        按钮才更新，因此临时试参数不会把默认值改掉。

        v4.39：τ 范围与固定 τ 一律**按 ns 存**（内部规范单位），这样默认值的物理
        含义与「时间单位」无关——用户把显示单位从 ns 换成 μs 后，默认值仍然是
        同一段寿命范围，不会悄悄变 1000 倍。
        """
        s = self.settings
        uf = float(getattr(self, 'lifetime_unit_factor', 1.0) or 1.0)
        try:
            for key, attr, kind in self._LIFETIME_DEFAULT_SPECS:
                w = getattr(self, attr, None)
                if w is None:
                    continue
                try:
                    if kind == "combo":
                        s.setValue("defaults/" + key, int(w.currentIndex()))
                    elif kind == "bool":
                        s.setValue("defaults/" + key, bool(w.isChecked()))
                    elif kind == "int":
                        s.setValue("defaults/" + key, int(w.value()))
                    elif kind == "float":
                        val = float(w.value())
                        if key in ("lifetime_taumin", "lifetime_taumax"):
                            val *= uf                     # 显示单位 → ns
                        s.setValue("defaults/" + key, val)
                    elif key == "lifetime_fixed_taus":
                        # 固定 τ 也按 ns 存（与 τ 范围同一口径）
                        s.setValue("defaults/" + key,
                                   self._convert_taus_text(w.text(), uf))
                    else:
                        s.setValue("defaults/" + key, str(w.text()))
                except Exception:
                    continue
            s.setValue("defaults/lifetime_saved", True)
            s.sync()
            method = str(self.lifetime_method_combo.currentText()).split("（")[0]
            auto = bool(self.lifetime_auto_lambda_check.isChecked())
            lam = "自动" if auto else f"{float(self.lifetime_lambda_spin.value()):g}"
            taus = self.lifetime_fixed_taus_edit.text().strip() or "无"
            sym = getattr(self, 'lifetime_unit_symbol', 'ns')
            msg = (f"已存为默认值：{method} / {int(self.lifetime_nrates_spin.value())} 点"
                   f" / τ {float(self.lifetime_taumin_spin.value()):g}"
                   f"–{float(self.lifetime_taumax_spin.value()):g} {sym}"
                   f" / λ {lam} / 固定 τ {taus}")
            if hasattr(self, 'status_bar'):
                self.status_bar.showMessage(msg, 6000)
            logging.getLogger('spectra').info(msg)
            return True
        except Exception as e:
            log_exception("保存寿命拟合默认值失败", e)
            if hasattr(self, 'status_bar'):
                self.status_bar.showMessage("保存默认值失败，详见日志", 6000)
            return False

    def _apply_lifetime_defaults(self):
        """启动时套用「存为默认值」的寿命拟合参数（须在 _restore_session 之后调用）。"""
        s = self.settings
        raw = s.value("defaults/lifetime_saved", False)
        if isinstance(raw, str):
            saved = raw.strip().lower() in ('true', '1', 'yes')
        else:
            saved = bool(raw)
        if not saved:
            return False
        applied = 0
        for key, attr, kind in self._LIFETIME_DEFAULT_SPECS:
            w = getattr(self, attr, None)
            if w is None:
                continue
            try:
                v = s.value("defaults/" + key, None)
                if v is None:
                    continue
                if kind == "combo":
                    idx = int(v)
                    if 0 <= idx < w.count():
                        w.setCurrentIndex(idx)
                elif kind == "bool":
                    if isinstance(v, str):
                        w.setChecked(v.strip().lower() in ('true', '1', 'yes'))
                    else:
                        w.setChecked(bool(v))
                elif kind == "int":
                    w.setValue(int(float(v)))
                elif kind == "float":
                    val = float(v)
                    if key in ("lifetime_taumin", "lifetime_taumax"):
                        # 默认值按 ns 存（v4.39）→ 换算到当前「时间单位」
                        val /= float(getattr(self, 'lifetime_unit_factor', 1.0) or 1.0)
                    w.setValue(val)
                elif key == "lifetime_fixed_taus":
                    # 默认值按 ns 存 → 换算回当前「时间单位」
                    w.setText(self._convert_taus_text(
                        str(v), 1.0 / float(getattr(self, 'lifetime_unit_factor', 1.0) or 1.0)))
                else:
                    w.setText(str(v))
                applied += 1
            except Exception:
                continue
        return applied > 0

    def _last_mode_index(self):
        """上次使用的模式索引（默认 0）"""
        try:
            return int(self.settings.value("last_mode", 0))
        except Exception:
            return 0

    def _dialog_start_dir(self):
        """文件对话框的起始目录（E4）：当前数据文件夹 → 工作区 → 默认工作区。

        旧实现一律从 Path.home() 开始，用户每次都要重新点回数据目录。
        """
        for cand in (getattr(self, 'current_folder', None),
                     getattr(self, 'workspace', None), DEFAULT_WORKSPACE):
            try:
                if cand and Path(str(cand)).is_dir():
                    return str(cand)
            except Exception:
                continue
        return str(Path.home())

    def _ranged_folders(self):
        """已自动设过显示范围的文件夹集合（E2）。"""
        s = getattr(self, '_auto_ranged_folders', None)
        if s is None:
            s = set()
            self._auto_ranged_folders = s
        return s

    def _cancel_plotting(self, wait_ms=5000):
        """中止正在进行的后台绘图/拟合（D3/D7）。

        v4.45：改为「代次失效 + 非阻塞」为主，wait 只用来争取干净收尾：
        · 先递增代次——即使线程还在跑、wait 超时，它算完后的回调也会因代次
          不匹配被丢弃（旧实现只 wait(5000)，超时后线程成孤儿，会把寿命拟合图
          画到已经切过去的吸收模式画布上，实测复现）；
        · wait 的返回值不再重要，超时也只记一条日志，不阻塞主线程更久。
        """
        # 关键：先让在途结果失效，再尝试停止线程
        if hasattr(self, '_bump_generation'):
            self._bump_generation()
        worker = getattr(self, 'plot_worker', None)
        if worker is not None and worker.isRunning():
            try:
                worker.cancel()
            except Exception:
                pass
            if wait_ms:
                try:
                    finished = worker.wait(wait_ms)
                    if not finished:
                        # 线程仍未停：结果已由代次作废，这里只是如实记一笔
                        log_exception(
                            "后台线程未在 {} ms 内结束，已作废其结果".format(wait_ms),
                            RuntimeError("worker.wait timeout"))
                except Exception:
                    pass
            # 断开信号（若线程稍后才结束，就不会再回调到主线程）
            for sig in ('finished', 'error', 'progress'):
                try:
                    getattr(worker, sig).disconnect()
                except Exception:
                    pass
        self._plotting = False
        self._fit_cancelled = False
        self._long_task = False
        for attr in ('canvas', 'lifetime_canvas', 'diag_canvas', 'compare_canvas'):
            cv = getattr(self, attr, None)
            if cv is not None:
                try:
                    cv.set_busy(False)
                except Exception:
                    pass
        try:
            self.progress_bar.setVisible(False)
        except Exception:
            pass
        if hasattr(self, '_close_progress_dialog'):
            self._close_progress_dialog()

    def select_workspace(self):
        """选择工作区：设置目录树的根目录，并记住下次启动"""
        try:
            start = self._dialog_start_dir()
            folder = QFileDialog.getExistingDirectory(
                self, "选择工作区", start, QFileDialog.ShowDirsOnly
            )
            if folder:
                self.set_workspace(Path(folder))
        except Exception as e:
            log_exception("选择工作区失败", e)

    def set_workspace(self, path):
        """设置工作区（目录树根目录），根目录下显示子文件夹，并持久化"""
        try:
            path = Path(path)
            if not path.is_dir():
                return
            self.workspace = str(path)
            self.file_system_model.setRootPath(str(path))
            self.tree.setRootIndex(self.file_system_model.index(str(path)))
            if hasattr(self, 'workspace_label'):
                # v4.24：单行短路径 + 完整路径 tooltip（原来是长路径自动换行占 3 行）
                self.workspace_label.setText(
                    f"工作区: {self._short_path(path)}")
                self.workspace_label.setToolTip(
                    f"工作区（目录树根目录）:\n{path}")
            # 记住工作区，下次打开仍有效
            self.settings.setValue("workspace", str(path))
            self._save_settings()
            self.status_bar.showMessage(f"工作区已切换到: {path}")
        except Exception as e:
            log_exception("设置工作区失败", e)

    # ---------- D2/D5：关闭保存、拖拽加载 ----------

    def closeEvent(self, event):
        """关闭窗口前保存会话（D2）；正在拟合时先询问（D7）。"""
        if getattr(self, '_plotting', False):
            if getattr(self, '_long_task', False):
                ret = QMessageBox.question(
                    self, "拟合进行中",
                    "拟合尚未完成，关闭窗口将中止本次拟合并放弃本次结果。\n确定关闭？",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                if ret != QMessageBox.Yes:
                    event.ignore()
                    return
            # 短任务直接中止；长任务在用户确认后中止（都会 wait 等线程结束）
            self._cancel_plotting(wait_ms=5000)
        try:
            self._save_session()
        except Exception as e:
            log_exception("保存会话失败", e)
        try:
            super().closeEvent(event)
        except Exception:
            event.accept()

    def dragEnterEvent(self, event):
        """接受拖入的文件夹（D5）。"""
        try:
            if event.mimeData().hasUrls():
                for url in event.mimeData().urls():
                    if (url.isLocalFile()
                            and Path(url.toLocalFile()).is_dir()):
                        event.acceptProposedAction()
                        return
        except Exception:
            pass
        event.ignore()

    def dropEvent(self, event):
        """拖入文件夹即加载（D5）。"""
        try:
            for url in event.mimeData().urls():
                if not url.isLocalFile():
                    continue
                p = Path(url.toLocalFile())
                if p.is_dir():
                    self.set_workspace(p)
                    self.load_data_from_folder(str(p))
                    event.acceptProposedAction()
                    return
        except Exception as e:
            log_exception("拖拽加载失败", e)
        event.ignore()

    def return_to_launcher(self):
        """返回模块选择入口：设置 next_mode 标记并关闭窗口，
        主循环（absorption_gui.run_gui / start_gui）检测到后重新弹出 ModuleLauncher。"""
        if getattr(self, '_plotting', False) and getattr(self, '_long_task', False):
            ret = QMessageBox.question(
                self, "拟合进行中",
                "拟合尚未完成，返回将放弃本次结果显示。\n确定返回模块选择？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if ret != QMessageBox.Yes:
                return
        # 先中止后台线程：否则 closeEvent 会再问一次，且线程仍在读 data_cache
        self._cancel_plotting(wait_ms=5000)
        self.next_mode = "launcher"
        self.close()

    def _confirm_interrupt_plotting(self, action_desc):
        """D3/D7：后台任务进行中，切模式/换文件夹/关窗前的确认。

        返回 True 表示调用方可以继续。
        - 长任务（荧光寿命拟合 1–2 分钟、并行拟合）→ 弹 QMessageBox.question，
          用户选否则完全不改状态；
        - 短任务（普通绘图，几百毫秒）→ 不打扰用户，直接中止后继续：
          为一次瞬时重绘弹模态框既烦人，也会让主线程进嵌套事件循环、
          与正在绘图的 worker 线程同时操作 figure。
        两种情况都会 wait() 等线程真正结束，避免它继续读 data_cache。
        """
        if not getattr(self, '_plotting', False):
            return True
        if getattr(self, '_long_task', False):
            ret = QMessageBox.question(
                self, "拟合进行中",
                f"正在拟合中，{action_desc}会中止当前拟合，确定继续吗？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if ret != QMessageBox.Yes:
                return False
        self._cancel_plotting(wait_ms=5000)
        return True

    def on_spectrum_type_changed(self, index):
        """光谱类型切换（0=吸收, 1=发射, 2=荧光寿命, 3=3D 扫描 EEM）"""
        # D3：后台线程正在拟合时，切模式会 data_cache.clear()，而线程还在读它
        # （报「绘图失败: 'xxx'」且旧结果丢失）。先问用户，选否就完全不改状态。
        if not self._confirm_interrupt_plotting("切换模式"):
            # 下拉框已经变了，改回去才算「不改任何状态」
            try:
                idx = getattr(self, 'MODE_INDEX', {}).get(
                    getattr(self, 'spectrum_type', 'absorption'), 0)
                self.spectrum_type_combo.blockSignals(True)
                self.spectrum_type_combo.setCurrentIndex(idx)
                self.spectrum_type_combo.blockSignals(False)
            except Exception:
                pass
            return
        # v4.45：正在加载文件夹时不允许切模式。
        # 加载过程中会 processEvents（为了让进度条动），期间用户若切模式，
        # 这里会清空 data_cache 并重新加载，而外层加载循环仍在往 data_cache
        # 里塞——两边互相踩，实测 40 个文件会静默丢 5 个（丢的还是随机的）。
        # 做法：把下拉框拨回原值并提示，等这次加载结束再切。
        if getattr(self, '_loading', False):
            try:
                idx = getattr(self, 'MODE_INDEX', {}).get(
                    getattr(self, 'spectrum_type', 'absorption'), 0)
                self.spectrum_type_combo.blockSignals(True)
                self.spectrum_type_combo.setCurrentIndex(idx)
                self.spectrum_type_combo.blockSignals(False)
            except Exception:
                pass
            try:
                self.status_bar.showMessage(
                    "正在加载数据，请等加载完成后再切换模式", 4000)
            except Exception:
                pass
            return
        self.spectrum_type = ("emission" if index == 1
                              else "lifetime" if index == 2
                              else "scan3d" if index == 3
                              else "absorption")
        self._sync_mode_groups_visibility()
        # 下面一大段（参数组显隐 / 标签页 / 主按钮文案 / 信息页）都要用这三个
        # 判定。_sync_mode_groups_visibility 内部也算了一份，但那是局部变量，
        # 不共享——别删这三个，否则后半段全 NameError。
        is_lifetime = self.spectrum_type == "lifetime"
        is_scan3d = self.spectrum_type == "scan3d"
        is_spectrum = not is_lifetime and not is_scan3d
        # 主操作按钮的文字随模式切换（v4.25）：
        # 光谱/3D 模式是"重新绘图"，寿命模式才是真正耗时 1–2 分钟的拟合
        if hasattr(self, 'preview_btn'):
            if is_lifetime:
                self.preview_btn.setText("开始拟合")
                self.preview_btn.setToolTip(
                    "对当前选中文件做 MEM/SESM 寿命拟合（约 1–2 分钟，F5）\n"
                    "已拟合过且参数未变的样品会直接读缓存，秒出")
            else:
                self.preview_btn.setText("实时预览")
                self.preview_btn.setToolTip(
                    "按当前参数重新绘图（F5）\n"
                    "拖滑块/改下拉会 300ms 防抖自动重绘，本按钮用于立即刷新")
        if hasattr(self, 'subtract_group'):
            # 光谱减法只用于吸收/发射模式
            self.subtract_group.setVisible(is_spectrum)
        if hasattr(self, 'integ_group'):
            # 光谱积分（含数据输出区）同样只用于吸收/发射模式
            self.integ_group.setVisible(is_spectrum)
        if hasattr(self, 'peaks_group'):
            self.peaks_group.setVisible(is_spectrum)
        if hasattr(self, 'range_group'):
            self.range_group.setVisible(is_spectrum)
        if hasattr(self, 'plot_type_label'):
            self.plot_type_label.setVisible(is_spectrum)
        if hasattr(self, 'plot_type_combo'):
            self.plot_type_combo.setVisible(is_spectrum)
        # 文件列表提示随模式变化（v4.24：标题保持短，操作说明进 tooltip）
        if hasattr(self, 'file_list_label'):
            if is_lifetime:
                self.file_list_label.setText("已加载文件")
                self.file_list_label.setToolTip(
                    "勾选参与「叠加分布 / 跨样品汇总图 / PDF 报告」的样品（v4.37）；\n"
                    "点一下某个文件＝只拟合查看它")
            elif is_scan3d:
                self.file_list_label.setText("已加载文件")
                self.file_list_label.setToolTip("点选一个文件以绘制该 EEM 图（一次只画一个）")
            else:
                self.file_list_label.setText("已加载文件")
                self.file_list_label.setToolTip("勾选多个文件以绘制合并图；双击/单击查看单个")
        # 「数据比较」参数组与标签页只在吸收/发射模式下出现（v4.37）
        if hasattr(self, 'compare_group'):
            self.compare_group.setVisible(is_spectrum)
        if hasattr(self, '_set_compare_tab_visible'):
            self._set_compare_tab_visible(is_spectrum)
        # 「寿命分布」「拟合诊断」选项卡只在荧光寿命模式下显示
        if hasattr(self, '_set_dist_tab_visible'):
            self._set_dist_tab_visible(is_lifetime)
        if hasattr(self, '_set_diag_tab_visible'):
            self._set_diag_tab_visible(is_lifetime)
        # 切换类型时清空缓存，重新加载当前文件夹
        self.data_cache.clear()
        if hasattr(self, '_lifetime_fit_cache'):
            self._lifetime_fit_cache.clear()
        self._invalidate_results()        # v4.44：派生结果一并作废
        self.file_list.clear()
        self._update_file_count_label()   # v4.26：列表清空后计数归零
        # v4.27：切模式后状态栏徽标跟着走；拟合摘要卡片只属于寿命模式
        self._update_status_badges()
        if hasattr(self, 'fit_card') and not is_lifetime:
            self.fit_card.setVisible(False)
        self._sync_empty_state()
        if hasattr(self, 'current_folder'):
            self.load_data_from_folder(str(self.current_folder))
        else:
            mode_names = {1: "发射光谱", 2: "荧光寿命", 3: "3D 扫描 (EEM)"}
            self.status_bar.showMessage(
                f"已切换到 {mode_names.get(index, '吸收光谱')}，请选择文件夹")

    def _invalidate_results(self):
        """作废所有「派生结果」（v4.44）。

        换文件夹 / 切模式后，``data_cache`` 会被清空，但下面这些结果此前
        **没有任何清空点**，于是导出链路会拿着上一批数据的结果往外写：
        实测切到 B 文件夹后导出，产物里出现 A 文件夹的样品名，
        而弹窗照样提示"导出成功"——用户以为拿到的是当前数据。

        这里集中作废，配合导出入口的「结果名必须在 data_cache 里」防御。
        只清结果、不动用户参数（勾选、颜色、线宽等仍保留）。
        """
        for attr in ('_last_lifetime_result', '_last_integration_results',
                     '_last_compare_result', '_last_scan3d_result',
                     '_overlay_results'):
            try:
                if hasattr(self, attr):
                    setattr(self, attr, None)
            except Exception:
                pass
        # v5.0.2：峰表也是派生结果——不清的话换文件夹后「导出峰表」会写出
        # 上一批数据的样品名（与上面 5 个结果同一类问题）
        try:
            self._last_peaks = []
        except Exception:
            pass
        # 积分结果表 / 拟合摘要卡片 都是上面结果的投影，一并复位
        try:
            if getattr(self, 'integ_table', None) is not None:
                self.integ_table.setRowCount(0)
        except Exception:
            pass
        try:
            card = getattr(self, 'fit_card', None)
            if card is not None:
                card.setVisible(False)
        except Exception:
            pass

    def select_folder(self):
        """选择文件夹（起始目录为当前数据文件夹/工作区，E4）"""
        folder = QFileDialog.getExistingDirectory(
            self,
            "选择数据文件夹",
            self._dialog_start_dir(),
            QFileDialog.ShowDirsOnly
        )

        if folder:
            self.load_data_from_folder(folder)

    def _make_load_progress(self, total):
        """构造逐文件进度回调（D1）：确定模式进度条 + 定期 processEvents。"""
        def _cb(index):
            try:
                self.progress_bar.setValue(min(int(index), int(total)))
                # 每 5 个文件让出一次事件循环：界面不再「未响应」，
                # 进度条也会真的走动（重入由 self._loading 守卫拦住）
                if index % 5 == 0 or index >= total:
                    QApplication.processEvents()
            except Exception:
                pass
        return _cb

    def load_data_from_folder(self, folder_path: str):
        """从文件夹加载数据（根据光谱类型选择解析逻辑）。

        D1：整个加载过程保持确定进度（setRange(0, n) + 逐文件 setValue）、
        等待光标与定期 processEvents，上百个文件时窗口不再「未响应」。
        D3：若后台正在拟合，先询问用户；选否则不改任何状态。
        """
        # 重入保护：processEvents 期间用户可能又点了别的文件夹/双击了目录树
        if getattr(self, '_loading', False):
            return
        # D3：后台线程正在读 data_cache，这里清空会让它报「绘图失败」
        if not self._confirm_interrupt_plotting("切换文件夹"):
            return

        self._loading = True
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.status_bar.showMessage(f"正在加载文件夹: {folder_path}...")
            self.progress_bar.setVisible(True)
            self.progress_bar.setRange(0, 1)
            self.progress_bar.setValue(0)

            folder = Path(folder_path)
            csv_files = list(folder.glob("*.csv"))
            txt_files = list(folder.glob("*.txt"))
            all_files = csv_files + txt_files
            # 寿命模式额外接受多列 xlsx（时间+样品列+IRF，自动按列拆分）
            if self.spectrum_type == "lifetime":
                all_files += list(folder.glob("*.xlsx"))
            # v4.41：吸收模式也接受多列光谱 xlsx（波长列 + 各样品列，自动按列拆成多条）。
            # 「说明.xlsx」是信息表不是数据，排除掉；Excel 打开时生成的 ~$ 临时文件也排除。
            elif self.spectrum_type == "absorption":
                all_files += [f for f in folder.glob("*.xlsx")
                              if '说明' not in f.stem and not f.name.startswith('~$')]
            # 按自然顺序排序（样品1、2、…、10、11），避免 "1,10,11,2" 这类字典序
            all_files = sorted(all_files, key=self._natural_key)

            if not all_files:
                # v4.44：区分「文件夹根本不存在」与「文件夹在但没数据」。
                # 此前两种情况都弹「未找到CSV或TXT文件！」——用户会以为路径没错、
                # 只是没数据，于是反复重试；并且状态栏会永久停在"正在加载…"。
                if not folder.is_dir():
                    QMessageBox.warning(
                        self, "文件夹不存在",
                        f"找不到这个文件夹：\n{folder_path}\n\n"
                        "它可能已被移动、重命名或删除，请重新选择数据文件夹。")
                    self.status_bar.showMessage("加载取消：文件夹不存在")
                else:
                    QMessageBox.warning(
                        self, "未找到数据文件",
                        f"文件夹里没有可解析的数据文件：\n{folder_path}\n\n"
                        "支持 .csv / .txt"
                        + ("（本模式还支持多列光谱 .xlsx）"
                           if self.spectrum_type == "absorption" else ""))
                    self.status_bar.showMessage("加载失败：未找到可解析的数据文件")
                self.progress_bar.setVisible(False)
                return

            # 确定模式：进度条按文件数推进（D1）
            total = len(all_files)
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(0)
            progress_cb = self._make_load_progress(total)

            # 清空缓存和列表（数据重载后旧拟合结果一并作废）
            self.data_cache.clear()
            if hasattr(self, '_lifetime_fit_cache'):
                self._lifetime_fit_cache.clear()
            self._invalidate_results()    # v4.44：派生结果一并作废
            self._load_errors = []        # v4.47：本批解析失败的明细
            self.file_list.clear()
            self.reset_curve_colors()  # 换文件夹即换一批数据，重新分配曲线颜色

            if self.spectrum_type == "emission":
                loaded_count, skipped, errors = self._load_emission_files(
                    all_files, progress_cb)
            elif self.spectrum_type == "lifetime":
                loaded_count, skipped, errors = self._load_lifetime_files(
                    all_files, progress_cb)
            elif self.spectrum_type == "scan3d":
                loaded_count, skipped, errors = self._load_scan3d_files(
                    all_files, progress_cb)
            else:
                loaded_count, skipped, errors = self._load_absorption_files(
                    all_files, progress_cb)

            self.folder_label.setText(
                f"文件夹: {self._short_path(folder_path)}")
            self.folder_label.setToolTip(
                f"已加载文件夹:\n{folder_path}\n共 {loaded_count} 个文件")
            # v4.24：数据栏只有 210px 宽，文件名一律被省略号截断 —— 给每一项挂
            # 完整文件名 tooltip，鼠标悬停即可看全（item.text() 本身没被截断，
            # 截断只发生在绘制阶段）
            self._sync_file_item_tooltips()
            # v4.26：换文件夹后列表全变了，重新套用搜索过滤 + 刷新计数
            self._apply_file_filter()
            self._update_status_badges()     # v4.27：状态栏样品数徽标
            self._sync_empty_state()         # v4.27：有数据了就收起空状态引导页
            self.current_folder = folder
            # 记入最近文件夹（D5）：只在真正加载到 ≥1 个文件时记（D2），
            # 否则浏览过的空目录也会挤进列表
            if loaded_count > 0:
                self._push_recent_folder(folder)

            # 读取文件夹中的 说明.xlsx（若有），用于把样品信息写入图例
            self._load_xlsx_info(folder)

            # 光谱减法的 A/B 下拉框随已加载文件刷新
            if hasattr(self, 'subtract_minuend_combo'):
                self._refresh_subtract_combos()

            self.status_bar.showMessage(
                f"成功加载 {loaded_count} 个文件"
                + (f"（跳过 {skipped} 个）" if skipped else ""))
            self.progress_bar.setVisible(False)

            # 一个文件都没读进来（D6）：明确告诉用户原因与日志位置
            if loaded_count == 0:
                self._warn_no_files_loaded(folder_path, errors, skipped)
            elif errors:
                # v4.47：**部分**文件解析失败时也要说清楚。
                # 此前只有 loaded_count == 0 才提示，成功 3 个、失败 2 个时
                # 状态栏只写"成功加载 3 个文件"，errors 列表直接丢弃——
                # 用户以为这一批就只有 3 个样品，拿去做后续分析。
                # 现在：① 存进 _load_errors 供计数标签悬停查看；
                #       ② 状态栏带上失败数；③ 明细写进日志。
                self._load_errors = list(errors)
                try:
                    n_err = len(errors)
                    self.status_bar.showMessage(
                        f"成功加载 {loaded_count} 个文件"
                        + (f"（跳过 {skipped} 个）" if skipped else "")
                        + f"，另有 {n_err} 个解析失败（把鼠标移到「已加载 N 个」上看明细）")
                    logging.warning("部分文件解析失败（%d 个）: %s",
                                    n_err, "; ".join(str(e) for e in errors[:10]))
                except Exception:
                    pass
                # 计数标签重建（带"N 个失败"与悬停明细）
                if hasattr(self, '_update_file_count_label'):
                    self._update_file_count_label()

            # 自动把波长上下限设为数据实际范围（E2：仅该文件夹首次加载时）
            if self.data_cache:
                key = str(folder)
                if key not in self._ranged_folders():
                    self._ranged_folders().add(key)
                    self._auto_set_range()

            # 自动更新预览
            if self.data_cache:
                self.update_plot()

        except Exception as e:
            log_exception(f"加载文件夹失败: {folder_path}", e)
            QMessageBox.critical(self, "错误", f"加载文件夹失败: {str(e)}")
            self.progress_bar.setVisible(False)
            self.status_bar.showMessage("加载失败")
        finally:
            # D1：无论成功失败都要恢复光标、复位重入标志
            try:
                QApplication.restoreOverrideCursor()
            except Exception:
                pass
            self._loading = False

    def _warn_no_files_loaded(self, folder_path, errors, skipped):
        """加载 0 个文件时的统一提示（D6）：前 3 个失败文件 + 原因 + 日志路径。"""
        lines = [f"文件夹：{folder_path}",
                 f"没有解析出任何可用数据（跳过 {skipped} 个文件）。"]
        if errors:
            lines.append("")
            lines.append("前 3 个失败文件：")
            for name, reason in list(errors)[:3]:
                lines.append(f"  · {name}: {reason}")
        lines.append("")
        lines.append(f"详细日志：{log_file_path()}")
        try:
            QMessageBox.warning(self, "加载失败", "\n".join(lines))
        except Exception:
            pass

    def _auto_set_range(self):
        """根据已加载数据的实际波长范围，自动设置显示范围（波长上下限）。

        E2：调用时机由 load_data_from_folder 控制——只在某个文件夹**首次**
        加载时自动设置，或用户点「自动」按钮时设置；不再每次加载都覆盖用户
        手填的范围（该范围同时会写进会话，见 _SESSION_SPECS）。
        """
        try:
            wl_min_all = []
            wl_max_all = []
            for info in self.data_cache.values():
                data = info['data']
                wl = data.get('wl', data.get('wavelength'))
                if wl is not None and len(wl) > 0:
                    wl_min_all.append(np.nanmin(wl))
                    wl_max_all.append(np.nanmax(wl))
            if wl_min_all and wl_max_all:
                lo = float(np.min(wl_min_all))
                hi = float(np.max(wl_max_all))
                self.wl_min_spin.setValue(lo)
                self.wl_max_spin.setValue(hi)
                try:
                    self.status_bar.showMessage(
                        f"显示范围已按数据设为 {lo:.1f} – {hi:.1f} nm")
                except Exception:
                    pass
        except Exception as e:
            log_exception("自动设置显示范围失败", e)

    def _on_auto_range_clicked(self):
        """「自动（按数据范围）」按钮（E2）。"""
        if not self.data_cache:
            QMessageBox.warning(self, "提示", "请先加载数据")
            return
        self._auto_set_range()
        self.update_plot()

    def _load_xlsx_info(self, folder):
        """读取文件夹中的 说明.xlsx，供图例标签增强 + 「数据比较」变量下拉框使用。"""
        self.xlsx_info = None
        try:
            info = load_xlsx_info(folder)
            self.xlsx_info = info
            if info and info.numbers:
                self.status_bar.showMessage(
                    f"已读取说明.xlsx：{len(info.numbers)} 个样品（浓度等信息自动写入图例）")
            else:
                self.status_bar.showMessage("说明.xlsx 未找到或读取失败，图例使用文件名")
        except Exception as e:
            self.xlsx_info = None
            log_exception("[read_xlsx_info] 读取失败", e)
        finally:
            # 变量下拉框跟着说明.xlsx 走（v4.37）
            self._refresh_compare_combos()

    def _refresh_compare_combos(self):
        """把说明.xlsx 的**数值列**填进「数据比较」的横轴 / 分组下拉框（v4.37）。

        - 没有说明.xlsx、或里面没有数值列时：下拉框给出原因，按钮禁用；
        - 只有一个数值列时：分组变量只有「（不分组）」可选；
        - 尽量保留用户原来的选择。
        """
        combo_x = getattr(self, 'compare_x_combo', None)
        if combo_x is None:
            return
        combo_g = getattr(self, 'compare_group_combo', None)
        btn = getattr(self, 'compare_btn', None)
        csv_btn = getattr(self, 'compare_csv_btn', None)

        info = getattr(self, 'xlsx_info', None)
        cols = list(info.numeric_columns()) if (info is not None and info.numbers) else []
        # 文件夹里那个 .xlsx 可能根本不是"说明表"（寿命模式的多列数据 xlsx 就长这样，
        # 列名是 A0/A6/IRF…）。判定规则（v4.37）：
        #   文件名含「说明」→ 认它是说明表（哪怕编号暂时对不上，也要让用户能试、
        #   并从"匹配不到编号"的跳过明细里看出问题）；
        #   文件名不含「说明」→ 必须在已加载文件里至少匹配到一个编号，才算说明表。
        no_cols_reason = None
        if cols:
            is_info_file = '说明' in Path(str(getattr(info, 'path', ''))).stem
            if not is_info_file:
                cache = getattr(self, 'data_cache', None) or {}
                matched = False
                for key in cache:
                    try:
                        if self._match_sample_number(key) is not None:
                            matched = True
                            break
                    except Exception:
                        continue
                if not matched:
                    cols = []
                    no_cols_reason = "该 .xlsx 不是说明表"        # 太长会把参数栏撑宽
        else:
            no_cols_reason = ("未找到说明.xlsx" if info is None
                              else "说明.xlsx 无数值列")

        prev_x = combo_x.currentText()
        prev_g = combo_g.currentText() if combo_g is not None else ''

        for combo in (combo_x, combo_g):
            if combo is None:
                continue
            combo.blockSignals(True)
            combo.clear()
        if not cols:
            combo_x.addItem(f"（{no_cols_reason}）")
            combo_x.setEnabled(False)
            if combo_g is not None:
                combo_g.addItem("（不可用）")
                combo_g.setEnabled(False)
            if btn is not None:
                btn.setEnabled(False)
                btn.setToolTip(f"数据比较不可用：{no_cols_reason}\n"
                               "需要在数据文件夹里放一份含数值列、且编号与文件名对得上的 说明.xlsx")
            if csv_btn is not None:
                csv_btn.setEnabled(False)
            for combo in (combo_x, combo_g):
                if combo is not None:
                    combo.blockSignals(False)
            return

        combo_x.addItems(cols)
        combo_x.setEnabled(True)
        combo_x.setCurrentText(prev_x if prev_x in cols else cols[0])
        if combo_g is not None:
            combo_g.addItem("（不分组）")
            combo_g.addItems(cols)
            combo_g.setEnabled(len(cols) > 1)
            if prev_g in cols or prev_g == "（不分组）":
                combo_g.setCurrentText(prev_g)
            else:
                combo_g.setCurrentIndex(0)
        if btn is not None:
            btn.setEnabled(True)
            btn.setToolTip("按说明.xlsx 的变量画点线图（只统计左侧勾选的样品）\n"
                           "图在「数据比较」标签页")
        if csv_btn is not None:
            csv_btn.setEnabled(True)
        for combo in (combo_x, combo_g):
            if combo is not None:
                combo.blockSignals(False)

    def _compare_variables(self):
        """当前选择的 (横轴变量, 分组变量或 None)；不可用时抛 ValueError。"""
        combo_x = getattr(self, 'compare_x_combo', None)
        combo_g = getattr(self, 'compare_group_combo', None)
        if combo_x is None or not combo_x.isEnabled():
            raise ValueError("没有可用的说明.xlsx 数值列作为横轴变量")
        x_var = combo_x.currentText()
        g_txt = combo_g.currentText() if combo_g is not None else "（不分组）"
        group_var = None if (not g_txt or g_txt.startswith('（')) else g_txt
        if group_var == x_var:
            group_var = None      # 分组与横轴同列没有意义，按不分组处理
        return x_var, group_var

    # 这些 path 是"没有单一来源文件"的哨兵：此时编号匹配必须用缓存键
    _PATH_SENTINELS = ('', '<emission>', '<xlsx>')

    def _match_name_candidates(self, cache_key):
        """编号匹配的候选名（按优先级）：数据缓存里的真实文件名 → 缓存键。

        多列 xlsx（一个文件拆成多条光谱）没有各自的文件名，只能靠缓存键——
        吸收模式 xlsx 的缓存键就是列名清洗后的样品名（``R1``）；发射模式本来就
        以 label 当缓存键；寿命模式多列 xlsx 也同理。
        """
        cands = []
        try:
            entry = self.data_cache.get(cache_key, {})
            path = entry.get('path') if isinstance(entry, dict) else None
            if path and str(path) not in self._PATH_SENTINELS:
                cands.append(Path(str(path)).name)
        except Exception:
            pass
        cands.append(str(cache_key))
        return cands

    def _filename_for_match(self, cache_key):
        """取该样品用于和 说明.xlsx 编号比对的名称（v4.41 起：**能对上的那个优先**）。

        候选名里第一个能命中编号的就用它；都命中不了就退回第一个候选
        （保持"没有 说明.xlsx 时也只是给个名字"的旧行为）。这样多列 xlsx
        的样品名（在缓存键里）和普通 CSV 的文件名都走同一条规则。
        """
        cands = self._match_name_candidates(cache_key)
        info = getattr(self, 'xlsx_info', None)
        if info is not None and info.numbers:
            for cand in cands:
                try:
                    if match_number(cand, info.numbers) is not None:
                        return cand
                except Exception:
                    continue
        return cands[0]

    def _match_sample_number(self, cache_key):
        """把候选名依次和 说明.xlsx 的编号对一遍，返回命中的编号；都没命中返回 None。"""
        info = getattr(self, 'xlsx_info', None)
        if info is None or not info.numbers:
            return None
        try:
            return match_number(self._filename_for_match(cache_key), info.numbers)
        except Exception:
            return None

    def _sample_name(self, file_name, data=None):
        """样品显示名（不含类型标签与说明信息）。

        优先用数据自带的 label（解析器已附加仪器类型后缀，如 "(Emission)"，
        这里去掉），否则退回数据文件名（缓存里的真实路径或缓存键）。
        """
        name = ''
        if data is not None:
            name = str(data.get('label') or '')
        if not name:
            entry = self.data_cache.get(file_name) if hasattr(self, 'data_cache') else None
            path = entry.get('path') if isinstance(entry, dict) else None
            if path and str(path) not in self._PATH_SENTINELS:
                name = Path(str(path)).stem
            else:
                name = str(file_name)
        # 去掉解析器附加的仪器光谱类型后缀，如 "(Emission)" / "(Emission Scan)"
        name = re.sub(r'\s*\((?:Emission|Excitation|Absorption)(?:\s+Scan)?\)\s*$',
                      '', name, flags=re.IGNORECASE).strip()
        return name or str(file_name)

    @staticmethod
    def _format_info_brief(info, num):
        """把某编号的说明信息格式化为简短字符串。

        「备注」列只显示其内容，不显示「备注=」字样；其余列保持「列名=值」。
        v4.41：编号用 ``info.entry_for`` 取（以前写 ``int(num)``，编号是
        ``R1`` / ``S1`` 这类文本码时 ``int('R1')`` 抛 ValueError，信息整个丢失）。
        """
        entry = info.entry_for(num)
        parts = []
        for col, val in entry.items():
            if val == '' or val is None:
                continue
            if '备注' in str(col):
                parts.append(str(val))
            else:
                parts.append(f'{col}={val}')
        return ', '.join(parts)

    def _xlsx_vars_text(self, file_name):
        """该样品在说明.xlsx 里的变量文字（**只列有值的变量**，v4.37）。

        值为空单元格 / ``null`` / ``N/A`` 的变量直接不出现——以前这种样品会在
        图例或信息页里漏出 ``RB浓度=null`` 之类的字样。
        """
        info = getattr(self, 'xlsx_info', None)
        if info is None or not info.numbers:
            return ''
        try:
            num = self._match_sample_number(file_name)
        except Exception:
            return ''
        if num is None:
            return ''
        parts = []
        for col in info.columns:
            val = info.value_for(num, col)
            if val is None:
                continue
            parts.append(str(val) if '备注' in str(col) else f'{col}={val}')
        return '  '.join(parts)

    def _build_legend_label(self, file_name, data=None, show_all=False):
        """构造图例标签：说明.xlsx 信息或样品名 (+EX)。

        - 说明.xlsx 匹配到编号时：合并图只显示说明信息（不显示原文件名，如
          "ce6-1"）；单图（show_all=True）显示「样品名（说明信息）」；
        - 未匹配到时显示样品名；
        - 发射模式末尾附激发波长；不附光谱类型。
        """
        stype = getattr(self, 'spectrum_type', 'absorption')
        name = self._sample_name(file_name, data)
        info_str = None
        info = getattr(self, 'xlsx_info', None)
        if info is not None and info.numbers:
            try:
                num = self._match_sample_number(file_name)
                if num is not None:
                    info_str = self._format_info_brief(info, num)
            except Exception as e:
                logging.warning("[read_xlsx_info] 匹配编号失败: %s", e)
        ex = ''
        if data is not None and stype == 'emission':
            ex_wl = data.get('ex_wl', data.get('ex'))
            if ex_wl:
                ex = f" (EX={float(ex_wl):.0f} nm)"
        if info_str:
            if show_all:
                return f"{name}（{info_str}）{ex}"
            return f"{info_str}{ex}"
        return f"{name}{ex}"

    def _legend_labels_for(self, file_names):
        """为一组文件批量生成**互不重复**的图例标签（v4.46）。

        问题：合并图为了简短，说明.xlsx 匹配成功时只显示说明信息、不显示样品名
        （见 _build_legend_label）。一批同类样品（比如都是"RB浓度=50"，
        只是测量次序不同）就会得到多条完全相同的标签——实测 26 条曲线里
        只有 8 条唯一标签，图例等于没有。

        这里做两件事：
          1. 先按原规则生成；
          2. 发现重复时，给重复的加上样品名后缀区分（"RB浓度=50 (S3)"）。

        返回 list，与 file_names 等长、同序。
        """
        names = list(file_names)
        labels = []
        for fn in names:
            data = (getattr(self, 'data_cache', {}) or {}).get(fn, {}).get('data')
            labels.append(self._build_legend_label(fn, data))
        # 统计重复
        from collections import Counter
        cnt = Counter(labels)
        if all(c == 1 for c in cnt.values()):
            return labels
        out = []
        seen = Counter()
        for fn, lab in zip(names, labels):
            if cnt[lab] > 1:
                seen[lab] += 1
                data = (getattr(self, 'data_cache', {}) or {}).get(fn, {}).get('data')
                # 优先用样品名区分；样品名也重名时退到序号
                sample = self._sample_name(fn, data)
                if sample and sample != lab:
                    out.append(f"{lab} [{sample}]")
                else:
                    out.append(f"{lab} #{seen[lab]}")
            else:
                out.append(lab)
        # 二次兜底：加后缀后仍可能撞（样品名相同），用序号强区分
        cnt2 = Counter(out)
        if any(c > 1 for c in cnt2.values()):
            seen2 = Counter()
            fixed = []
            for lab in out:
                if cnt2[lab] > 1:
                    seen2[lab] += 1
                    fixed.append(f"{lab} #{seen2[lab]}")
                else:
                    fixed.append(lab)
            out = fixed
        return out

    def _refresh_subtract_combos(self):
        """把已加载文件名填入「光谱减法」的 A/B 下拉框（尽量保留原选择）。

        A 下拉框第一项固定为「所有光谱（各减本底）」（=扣除本底模式），
        其后为各文件（选中即两光谱相减模式）；B 默认选第一个文件。
        """
        names = list(self.data_cache.keys())
        first_item = "所有光谱（各减本底）"

        combo_a = self.subtract_minuend_combo
        prev_a = combo_a.currentText()
        combo_a.blockSignals(True)
        combo_a.clear()
        combo_a.addItem(first_item)
        combo_a.addItems(names)
        if prev_a == first_item or prev_a in names:
            combo_a.setCurrentText(prev_a)
        else:
            combo_a.setCurrentIndex(0)
        combo_a.blockSignals(False)

        combo_b = self.subtract_ref_combo
        prev_b = combo_b.currentText()
        combo_b.blockSignals(True)
        combo_b.clear()
        combo_b.addItems(names)
        if prev_b in names:
            combo_b.setCurrentText(prev_b)
        else:
            combo_b.setCurrentIndex(0)
        combo_b.blockSignals(False)

        # 差谱模式下 A=B 会得到一条零线，回退到「所有光谱」
        if (combo_a.currentText() == combo_b.currentText()
                and combo_a.currentText() != first_item):
            combo_a.blockSignals(True)
            combo_a.setCurrentIndex(0)
            combo_a.blockSignals(False)

    def _load_absorption_files(self, all_files, progress_cb=None):
        """加载吸收光谱。返回 (loaded, skipped, errors)，errors=[(文件名, 原因)]。

        v4.41：一个**多列光谱 xlsx** 会返回多条数据集（每列一条），全部收进来；
        这些数据集的缓存键就是样品名（如 R1），所以 path 记成 ``<xlsx>`` 哨兵，
        让 ``_filename_for_match`` 回退到缓存键去和 说明.xlsx 的编号匹配。
        """
        loaded_count = 0
        skipped = 0
        errors = []
        for i, file_path in enumerate(all_files, 1):
            try:
                data = load_absorption_spectra(file_path, skip_metadata=True, verbose=False)
                if data and len(data) > 0:
                    for ds in data:
                        if not isinstance(ds, dict):
                            skipped += 1
                            continue
                        if 'wl' in ds and 'absorption' in ds:
                            ds['wavelength'] = ds['wl']
                        elif 'wavelength' in ds and 'absorption' in ds:
                            pass
                        else:
                            skipped += 1
                            errors.append((file_path.name, "缺少 wavelength/absorption 列"))
                            continue

                        label = str(ds.get('label') or file_path.stem)
                        base = label
                        counter = 1
                        while base in self.data_cache:
                            counter += 1
                            base = f"{label}_{counter}"
                        # 多列 xlsx：一个文件出多条 —— path 用哨兵，匹配靠缓存键
                        multi = (len(data) > 1
                                 or file_path.suffix.lower() in ('.xlsx', '.xls'))
                        self.data_cache[base] = {
                            'path': Path('<xlsx>') if multi else file_path,
                            'data': ds,
                        }
                        item = QListWidgetItem(base)
                        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                        item.setCheckState(Qt.Checked)
                        self.file_list.addItem(item)
                        loaded_count += 1
                else:
                    skipped += 1
                    errors.append((file_path.name, "解析结果为空"))
            except Exception as e:
                skipped += 1
                errors.append((file_path.name, f"{type(e).__name__}: {e}"))
                logging.warning("加载吸收光谱失败 %s: %s", file_path.name, e)
            finally:
                if progress_cb is not None:
                    progress_cb(i)
        return loaded_count, skipped, errors

    def _load_emission_files(self, all_files, progress_cb=None):
        """加载发射光谱文件（load_emission_spectra 返回数据集列表）。

        返回 (loaded, skipped, errors)。
        """
        loaded_count = 0
        errors = []
        try:
            datasets = load_emission_spectra(all_files, verbose=False)
            for ds in datasets:
                # 生成唯一的缓存键
                label = ds.get('label') or 'emission'
                base = label
                counter = 1
                while base in self.data_cache:
                    base = f"{label}_{counter}"
                    counter += 1
                # 兼容键名（保持与吸收光谱一致使用 wl/intensity 或 wavelength/absorption）
                # v5.0.6：保留真实来源路径。此前一律写死 Path('<emission>')，
                # 于是「可比性预检」想读文件头时无路径可读，元数据/完整性/
                # 散射三项检查静默失效。parse_csv 现在会带上 _source_path。
                _src = ds.get('_source_path')
                self.data_cache[base] = {
                    'path': Path(_src) if _src else Path('<emission>'),
                    'data': ds,
                }
                item = QListWidgetItem(base)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked)
                self.file_list.addItem(item)
                loaded_count += 1
        except Exception as e:
            errors.append(("<文件夹>", f"{type(e).__name__}: {e}"))
            logging.warning("加载发射光谱失败: %s", e)
        if progress_cb is not None:
            progress_cb(len(all_files))
        skipped = max(0, len(all_files) - loaded_count)
        return loaded_count, skipped, errors

    def _load_scan3d_files(self, all_files, progress_cb=None):
        """加载 3D 扫描（EEM）CSV：只有能被 parse_3d_scan_csv 解析的才收。

        目录里混着普通光谱 CSV 是常态，解析失败一律跳过并记日志；
        全部失败由调用方统一提示（含前 3 个失败文件与日志路径）。
        返回 (loaded, skipped, errors)。
        """
        from plot_3d_scan import parse_3d_scan_csv
        loaded_count = 0
        skipped = 0
        errors = []
        for i, file_path in enumerate(all_files, 1):
            try:
                data = parse_3d_scan_csv(str(file_path), verbose=False)
            except Exception as e:
                logging.warning("跳过 %s（3D 扫描解析失败）: %s", file_path.name, e)
                skipped += 1
                errors.append((file_path.name, f"{type(e).__name__}: {e}"))
                continue
            finally:
                if progress_cb is not None:
                    progress_cb(i)
            if data['intensity'].size == 0:
                skipped += 1
                errors.append((file_path.name, "强度矩阵为空"))
                continue
            label = str(data.get('label') or file_path.stem)
            key = label
            counter = 1
            while key in self.data_cache:
                counter += 1
                key = f"{label}({counter})"
            self.data_cache[key] = {'path': file_path, 'data': data}
            item = QListWidgetItem(key)
            # 3D 扫描一次只画一个文件，去掉勾选框
            item.setFlags(item.flags() & ~Qt.ItemIsUserCheckable)
            self.file_list.addItem(item)
            loaded_count += 1
        return loaded_count, skipped, errors

    def _load_lifetime_files(self, all_files, progress_cb=None):
        """加载荧光寿命文件（Horiba/三列 CSV；多列 xlsx 自动按样品列拆分）。

        返回 (loaded, skipped, errors)。
        """
        loaded_count = 0
        skipped = 0
        errors = []
        entries = []  # (期望标签, 路径, 数据 dict)
        for i, file_path in enumerate(all_files, 1):
            try:
                if file_path.suffix.lower() in ('.xlsx', '.xls'):
                    try:
                        datasets = parse_decay_xlsx(file_path)
                    except Exception as e:
                        # 目录里混有的其他 xlsx（如 说明.xlsx）跳过
                        logging.warning("跳过 %s（xlsx 解析失败）: %s",
                                        file_path.name, e)
                        skipped += 1
                        errors.append((file_path.name, f"{type(e).__name__}: {e}"))
                        continue
                    for ds in datasets:
                        entries.append((str(ds['name']), file_path, ds))
                else:
                    try:
                        data = parse_decay_csv(file_path)
                    except Exception as e:
                        # 目录里混有吸收/发射 CSV 时跳过，不视为错误
                        logging.warning("跳过 %s（不是寿命三列数据）: %s",
                                        file_path.name, e)
                        skipped += 1
                        errors.append((file_path.name, f"{type(e).__name__}: {e}"))
                        continue
                    entries.append((file_path.stem, file_path, data))
            finally:
                if progress_cb is not None:
                    progress_cb(i)

        # 标签去重：重名的（如 xlsx 样品列名与某 CSV 同名）加来源文件前缀
        from collections import Counter
        label_counts = Counter(label for label, _, _ in entries)
        seen = {}
        for label, file_path, data in entries:
            key = label if label_counts[label] == 1 else f"{file_path.stem}·{label}"
            if key in seen:
                seen[key] += 1
                key = f"{key}({seen[key]})"
            seen[key] = seen.get(key, 1)
            self.data_cache[key] = {'path': file_path, 'data': data}
            item = QListWidgetItem(key)
            # v4.37：寿命模式**也**给勾选框——「叠加分布 / 跨样品汇总图 / PDF 报告」
            # 现在只处理勾选的样品（以前寿命模式没有合并图，勾选框被去掉了）。
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            self.file_list.addItem(item)
            loaded_count += 1
        return loaded_count, skipped, errors

    def reload_data(self):
        """重新加载数据"""
        if hasattr(self, 'current_folder'):
            self.load_data_from_folder(str(self.current_folder))
        else:
            QMessageBox.warning(self, "警告", "请先选择文件夹！")

    def on_file_selected(self, item):
        """文件选择事件"""
        try:
            file_name = item.text()
            if file_name in self.data_cache:
                data_info = self.data_cache[file_name]
                data = data_info['data']

                # 荧光寿命模式：展示时间/IRF 基本信息
                if self.spectrum_type == "lifetime":
                    self._show_lifetime_info(file_name, data)
                    return

                # 3D 扫描模式：展示 EEM 矩阵基本信息并重绘
                if self.spectrum_type == "scan3d":
                    self._show_scan3d_info(file_name, data)
                    return

                wavelength, intensity = self._extract_xy(data)

                is_emission = self.spectrum_type == "emission"
                y_label = "发射强度" if is_emission else "吸收值"

                # 更新信息标签
                info_text = f"文件名: {file_name}\n\n"
                if is_emission:
                    ex_wl = data.get('ex_wl', data.get('ex'))
                    if ex_wl is not None:
                        info_text += f"激发波长 (EX): {ex_wl:.0f} nm\n"
                info_text += f"波长范围: {wavelength.min():.1f} - {wavelength.max():.1f} nm\n"
                info_text += f"数据点数: {len(wavelength)}\n"
                info_text += f"{y_label}范围: {intensity.min():.4f} - {intensity.max():.4f}\n\n"

                # 说明.xlsx 里这个样品的变量（空值不显示，v4.37）
                xlsx_line = self._xlsx_vars_text(file_name)
                if xlsx_line:
                    info_text += f"说明.xlsx: {xlsx_line}\n\n"

                # 峰信息
                if self.mark_peaks_check.isChecked():
                    try:
                        temp_data = {'wl': wavelength, 'absorption': intensity}
                        peaks_dict = find_absorption_peaks(
                            temp_data,
                            min_height=self.peak_height_spin.value(),
                            min_distance=self.peak_distance_spin.value()
                        )
                        if peaks_dict and 'peak_wavelengths' in peaks_dict:
                            num_peaks = peaks_dict.get('num_peaks', 0)
                            if num_peaks > 0:
                                info_text += f"检测到 {num_peaks} 个峰:\n"
                                for i, (wl, intens) in enumerate(zip(peaks_dict['peak_wavelengths'], peaks_dict['peak_intensities']), 1):
                                    if i > 5:
                                        break
                                    info_text += f"  {i}. {wl:.1f} nm (强度: {intens:.4f})\n"
                                if num_peaks > 5:
                                    info_text += f"  ... 还有 {num_peaks - 5} 个峰\n"
                            else:
                                info_text += "未检测到明显的峰\n"
                        else:
                            info_text += "未检测到明显的峰\n"
                    except Exception as e:
                        info_text += f"峰检测失败: {str(e)}\n"

                self.info_label.setText(info_text)

                # 如果是单图模式，更新预览
                if self.plot_type_combo.currentIndex() == 1:
                    self.update_plot()
        except Exception as e:
            self.info_label.setText(f"错误: {str(e)}")
            QMessageBox.warning(self, "错误", f"选择文件失败: {str(e)}")

    def _show_lifetime_info(self, file_name, data):
        """荧光寿命模式下，在信息页展示文件基本特征。

        v5.0.4：增加「τ 范围建议」。默认 τ 0.01–100 ns 对 μs 级磷光完全不够，
        会把寿命算错到两个数量级（实测 03-Ce6：85.8 ns vs 正确 5653 ns，
        差 65.9 倍），而错值看起来完全正常，用户会直接抄进报告。
        这里在**拟合之前**就把建议范围摆出来，并提供一键采用按钮。
        """
        time = np.asarray(data.get('time'), dtype=float)
        decay = np.asarray(data.get('decay'), dtype=float)
        irf = np.asarray(data.get('irf'), dtype=float)
        info_text = f"文件名: {file_name}\n\n"
        info_text += f"时间范围: {time.min():.3g} - {time.max():.3g} ns\n"
        info_text += f"数据点数: {len(time)}\n"
        info_text += f"时间步长: {(time[1] - time[0]):.4g} ns\n"
        info_text += f"衰减峰计数: {decay.max():.4g}\n"
        if len(irf) == len(time) and irf.max() > 0:
            half = irf.max() / 2
            idx = np.where(irf >= half)[0]
            info_text += f"IRF 峰计数: {irf.max():.4g}\n"
            info_text += f"IRF FWHM: {time[idx[-1]] - time[idx[0]]:.4g} ns\n"

        # ---- τ 范围建议（v5.0.4）----
        self._tau_suggestion = None
        try:
            import plot_lifetime as _pl
            sugg = _pl.suggest_tau_range(time, decay, irf)
            self._tau_suggestion = sugg
            cur_lo = self.lifetime_taumin_spin.value()
            cur_hi = self.lifetime_taumax_spin.value()
            factor = float(getattr(self, 'lifetime_unit_factor', 1.0) or 1.0)
            unit_sym = self.tau_unit_symbol()
            s_lo, s_hi = sugg['tau_min'] * factor, sugg['tau_max'] * factor
            covered = (cur_lo <= s_lo * 1.5) and (cur_hi >= s_hi / 1.5)
            info_text += (f"\n建议 τ 范围: {s_lo:.4g} – {s_hi:.4g} {unit_sym}"
                          f"（{sugg['reason']}）\n")
            if not covered:
                d_lo = cur_lo / s_lo if s_lo > 0 else 0
                d_hi = s_hi / cur_hi if cur_hi > 0 else 0
                info_text += (
                    f"⚠ 当前设置 {cur_lo:g} – {cur_hi:g} 与数据可能不匹配：\n"
                    f"   建议上限至少 {s_hi:.4g}"
                    f"{f'（当前上限的 {d_hi:.0f} 倍）' if d_hi > 1.5 else ''}。\n"
                    f"   范围设窄会把真实寿命截断在网格端点，"
                    f"报出的 τ 偏小且 χ²R 偏大。\n")
            else:
                info_text += "✓ 当前 τ 设置覆盖了建议范围\n"
        except Exception as e:            # 建议失败不能挡住信息页
            logging.debug("τ 范围建议失败: %s", e)

        info_text += "\n点击「开始拟合」按钮启动 MEM 拟合\n（结果将显示在预览图与本页）"
        self.info_label.setText(info_text)
        if self.plot_type_combo.currentIndex() == 1:
            self.update_plot()

    def _show_scan3d_info(self, file_name, data):
        """3D 扫描（EEM）模式下，在信息页展示矩阵基本信息，并立即重绘"""
        Z = np.asarray(data.get('intensity'), dtype=float)
        ex = np.asarray(data.get('ex_wavelengths'), dtype=float)
        em = np.asarray(data.get('em_wavelengths'), dtype=float)
        finite = Z[np.isfinite(Z)]
        info_text = f"文件名: {file_name}\n\n"
        info_text += f"数据矩阵: {Z.shape[0]} (EM) × {Z.shape[1]} (EX)\n"
        if len(ex):
            info_text += f"EX 范围: {ex.min():.0f} - {ex.max():.0f} nm\n"
        if len(em):
            info_text += f"EM 范围: {em.min():.0f} - {em.max():.0f} nm\n"
        if finite.size:
            info_text += (f"强度范围: {finite.min():.4g} - {finite.max():.4g}\n")
            info_text += f"空值/NaN: {int(Z.size - finite.size)} 个\n"
        # 饱和与梳状伪迹提示
        try:
            from plot_3d_scan import _detect_saturation, _detect_comb_period
            sat = _detect_saturation(Z)
            if sat is not None:
                info_text += f"\n⚠️ 检测到饱和上限 {sat:.0f}（绘图时会自动修补）\n"
            period, strength = _detect_comb_period(Z, em)
            if period and strength >= 5:
                info_text += (f"⚠️ 检测到周期梳状伪迹：{period:.2f} nm"
                              f"（峰/底噪 {strength:.1f}，绘图时按所选方式处理）\n")
        except Exception:
            pass
        info_text += "\n在左侧「3D 扫描 (EEM) 选项」里选择绘图类型后重绘。"
        self.info_label.setText(info_text)
        self.update_plot()

    def get_checked_files(self):
        """获取勾选的文件名列表（用于合并图）"""
        checked = []
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            if item.checkState() == Qt.Checked:
                checked.append(item.text())
        return checked

    def _sync_file_item_tooltips(self):
        """给文件列表每一项挂完整文件名 tooltip（v4.24）。

        数据栏默认只有约 210px 宽，`20260826RBL8i.csv` 这类名字在画面上一定被
        省略号截断；`QListWidgetItem.text()` 保存的是完整字符串（截断只发生在
        绘制阶段），所以直接把它作为 tooltip 即可，不必额外存映射。
        """
        try:
            for i in range(self.file_list.count()):
                item = self.file_list.item(i)
                if item is not None:
                    item.setToolTip(item.text())
        except Exception as e:
            log_exception("设置文件列表 tooltip 失败", e)

    # ---------- 文件列表：搜索过滤 / 全选（v4.26）----------

    def _visible_file_items(self):
        """当前未被搜索过滤隐藏的列表项（过滤只影响显示，不改勾选状态）。"""
        out = []
        try:
            for i in range(self.file_list.count()):
                item = self.file_list.item(i)
                if item is not None and not item.isHidden():
                    out.append(item)
        except Exception:
            pass
        return out

    def on_file_search_changed(self, text):
        """搜索框内容变化 → 过滤文件列表（v4.26）。"""
        self._apply_file_filter(text)

    def _apply_file_filter(self, text=None):
        """按搜索词过滤文件列表，返回显示出来的条数（v4.26）。

        用 `QListWidgetItem.setHidden` 实现：只影响显示、**不动勾选状态**，
        所以「筛选出 3 个 → 全选 → 清空搜索词」不会丢掉其它已勾选的样品。
        """
        if not hasattr(self, 'file_list'):
            return 0
        if text is None:
            edit = getattr(self, 'file_search_edit', None)
            text = edit.text() if edit is not None else ""
        query = str(text).strip().lower()
        shown = 0
        try:
            for i in range(self.file_list.count()):
                item = self.file_list.item(i)
                if item is None:
                    continue
                hit = (not query) or (query in item.text().lower())
                item.setHidden(not hit)
                if hit:
                    shown += 1
        except Exception as e:
            log_exception("过滤文件列表失败", e)
        self._update_file_count_label(shown)
        self._update_file_select_btn()
        return shown

    def _update_file_count_label(self, shown=None):
        """计数标签：有过滤时显示「已加载 N 个（显示 M）」（v4.26）。

        v4.47：解析失败的文件数也挂在这里（悬停可看前若干条原因），
        否则"成功 3 个、失败 2 个"和"这批就只有 3 个"在界面上完全一样。
        """
        label = getattr(self, 'file_count_label', None)
        if label is None or not hasattr(self, 'file_list'):
            return
        try:
            total = self.file_list.count()
            if shown is None:
                shown = len(self._visible_file_items())
            n_err = len(getattr(self, '_load_errors', []) or [])
            suffix = f"，{n_err} 个失败" if n_err else ""
            if shown < total:
                label.setText(f"已加载 {total} 个（显示 {shown}）{suffix}")
                tip = f"已在列表中过滤：显示 {shown} / 共 {total} 个文件"
            else:
                label.setText(f"已加载 {total} 个文件{suffix}")
                tip = ""
            if n_err:
                lines = [f"有 {n_err} 个文件解析失败："]
                for name, reason in list(self._load_errors)[:8]:
                    lines.append(f"  · {name}: {reason}")
                if n_err > 8:
                    lines.append(f"  ……其余 {n_err - 8} 个见日志")
                lines.append(f"\n详细日志：{log_file_path()}")
                tip = (tip + "\n\n" if tip else "") + "\n".join(lines)
            label.setToolTip(tip)
            self._update_status_badges()     # v4.27：状态栏样品数徽标同步
        except Exception:
            pass

    def _update_file_select_btn(self):
        """「全选 / 全不选」按钮文字随当前勾选状态切换（v4.26）。"""
        btn = getattr(self, 'file_select_btn', None)
        if btn is None or not hasattr(self, 'file_list'):
            return
        try:
            visible = self._visible_file_items()
            btn.setText("全选" if any(it.checkState() != Qt.Checked
                                      for it in visible) else "全不选")
            btn.setEnabled(bool(visible))
        except Exception:
            pass

    def toggle_select_all_visible(self):
        """勾选 / 取消勾选当前显示的全部文件（受搜索过滤影响，v4.26）。"""
        visible = self._visible_file_items()
        if not visible:
            return
        target = Qt.Checked if any(it.checkState() != Qt.Checked
                                   for it in visible) else Qt.Unchecked
        # 逐项改会各自触发 itemChanged → 合并图重绘 N 次，这里合并成一次
        self.file_list.blockSignals(True)
        try:
            for it in visible:
                it.setCheckState(target)
        finally:
            self.file_list.blockSignals(False)
        self._update_file_select_btn()
        self._update_file_count_label()
        if getattr(self, 'current_plot_type', 'combined') == "combined":
            self._trigger_live_update()
        self.status_bar.showMessage(
            f"已{'勾选' if target == Qt.Checked else '取消勾选'} {len(visible)} 个文件")

    @staticmethod
    def _extract_xy(data):
        """从数据字典中提取波长与强度/吸收值（兼容吸收/发射两种格式）"""
        wl = data.get('wavelength', data.get('wl'))
        # 发射光谱用 intensity，吸收光谱用 absorption
        y = data.get('absorption', data.get('intensity'))
        if wl is None or y is None:
            raise KeyError("数据中缺少波长或 absorption/intensity")
        return np.asarray(wl), np.asarray(y)

    @staticmethod
    def _natural_key(path):
        """自然排序键：把文件名中的数字按数值比较，避免 "1,10,11,2" 字典序。"""
        name = Path(path).name
        return [int(t) if t.isdigit() else t.lower() for t in re.split(r'(\d+)', name)]
