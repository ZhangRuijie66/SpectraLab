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

from gui_config import DEFAULT_WORKSPACE
from gui_log import log_exception, log_file_path, setup_logging
from plot_absorption import load_absorption_spectra, find_absorption_peaks
from plot_emission import load_spectra as load_emission_spectra
from plot_lifetime import parse_decay_csv, parse_decay_xlsx
from read_xlsx_info import load_xlsx_info, match_number

# 将父目录加入 Python 路径，便于独立导入绘图模块
_parent = Path(__file__).resolve().parent.parent
if str(_parent) not in sys.path:
    sys.path.insert(0, str(_parent))


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
        ("param/lifetime_kmin", "lifetime_kmin_spin", "float"),
        ("param/lifetime_kmax", "lifetime_kmax_spin", "float"),
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

        def _flag(key, default):
            v = s.value(key, default)
            if isinstance(v, str):
                return v.strip().lower() in ('true', '1', 'yes')
            return bool(v)

        try:
            # 白名单控件循环恢复（E1）
            for key, attr, kind in self._SESSION_SPECS:
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
            # 主题（D3）
            theme = s.value("theme", "light", str)
            if theme in ("light", "dark"):
                self.theme = theme
                if hasattr(self, 'theme_btn'):
                    self.theme_btn.setText("☀️ 浅色主题" if theme == "dark"
                                           else "🌙 深色主题")
                if hasattr(self, 'apply_style'):
                    self.apply_style()
                if hasattr(self, '_apply_mpl_theme'):
                    self._apply_mpl_theme()
            self._refresh_recent_combo()
        except Exception as e:
            log_exception("恢复会话失败", e)

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

        先请 worker 取消（寿命拟合内部会轮询 cancel 标志），再 wait 等线程结束，
        然后断开信号——调用方接下来会清缓存/切模式，旧结果不该再回调回来。
        """
        worker = getattr(self, 'plot_worker', None)
        if worker is not None and worker.isRunning():
            try:
                worker.cancel()
            except Exception:
                pass
            if wait_ms:
                try:
                    worker.wait(wait_ms)
                except Exception:
                    pass
            try:
                worker.finished.disconnect()
            except Exception:
                pass
            try:
                worker.error.disconnect()
            except Exception:
                pass
            try:
                worker.progress.disconnect()
            except Exception:
                pass
        self._plotting = False
        self._fit_cancelled = False
        self._long_task = False
        for attr in ('canvas', 'lifetime_canvas', 'diag_canvas'):
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
                self.workspace_label.setText(f"工作区: {path}")
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
        self.spectrum_type = ("emission" if index == 1
                              else "lifetime" if index == 2
                              else "scan3d" if index == 3
                              else "absorption")
        # 显示/隐藏各模式专用选项
        is_lifetime = self.spectrum_type == "lifetime"
        is_scan3d = self.spectrum_type == "scan3d"
        is_spectrum = not is_lifetime and not is_scan3d
        if hasattr(self, 'emission_options_group'):
            self.emission_options_group.setVisible(self.spectrum_type == "emission")
        if hasattr(self, 'lifetime_options_group'):
            self.lifetime_options_group.setVisible(is_lifetime)
        if hasattr(self, 'scan3d_options_group'):
            self.scan3d_options_group.setVisible(is_scan3d)
        # 寿命专属的「导出拟合结果」按钮：仅寿命模式显示
        if hasattr(self, 'export_current_fit_btn'):
            self.export_current_fit_btn.setVisible(is_lifetime)
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
        # 文件列表提示随模式变化
        if hasattr(self, 'file_list_label'):
            if is_lifetime:
                self.file_list_label.setText("已加载的文件（点选一个以拟合查看）:")
            elif is_scan3d:
                self.file_list_label.setText("已加载的文件（点选一个以绘制 EEM）:")
            else:
                self.file_list_label.setText("已加载的文件（勾选以绘制合并图）:")
        # 「寿命分布」「拟合诊断」选项卡只在荧光寿命模式下显示
        if hasattr(self, '_set_dist_tab_visible'):
            self._set_dist_tab_visible(is_lifetime)
        if hasattr(self, '_set_diag_tab_visible'):
            self._set_diag_tab_visible(is_lifetime)
        # 切换类型时清空缓存，重新加载当前文件夹
        self.data_cache.clear()
        if hasattr(self, '_lifetime_fit_cache'):
            self._lifetime_fit_cache.clear()
        self.file_list.clear()
        if hasattr(self, 'current_folder'):
            self.load_data_from_folder(str(self.current_folder))
        else:
            mode_names = {1: "发射光谱", 2: "荧光寿命", 3: "3D 扫描 (EEM)"}
            self.status_bar.showMessage(
                f"已切换到 {mode_names.get(index, '吸收光谱')}，请选择文件夹")

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
            # 按自然顺序排序（样品1、2、…、10、11），避免 "1,10,11,2" 这类字典序
            all_files = sorted(all_files, key=self._natural_key)

            if not all_files:
                QMessageBox.warning(self, "警告", "未找到CSV或TXT文件！")
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
                f"文件夹: {self._short_path(folder_path)}\n"
                f"已加载 {loaded_count} 个文件")
            self.folder_label.setToolTip(str(folder_path))
            if hasattr(self, 'file_count_label'):
                self.file_count_label.setText(f"已加载 {loaded_count} 个文件")
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
        """读取文件夹中的 说明.xlsx，供图例标签增强使用；找不到则为 None。"""
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

    def _filename_for_match(self, cache_key):
        """取用于编号匹配的文件名：优先数据缓存里的真实文件名，否则用缓存键。"""
        try:
            entry = self.data_cache.get(cache_key, {})
            path = entry.get('path') if isinstance(entry, dict) else None
            if path and str(path) not in ('', '<emission>'):
                return Path(path).name
        except Exception:
            pass
        return str(cache_key)

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
            if path and str(path) not in ('', '<emission>'):
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
        """
        entry = info.info.get(int(num), {})
        parts = []
        for col, val in entry.items():
            if val == '' or val is None:
                continue
            if '备注' in str(col):
                parts.append(str(val))
            else:
                parts.append(f'{col}={val}')
        return ', '.join(parts)

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
                num = match_number(self._filename_for_match(file_name), info.numbers)
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
        """加载吸收光谱。返回 (loaded, skipped, errors)，errors=[(文件名, 原因)]。"""
        loaded_count = 0
        skipped = 0
        errors = []
        for i, file_path in enumerate(all_files, 1):
            try:
                data = load_absorption_spectra(file_path, skip_metadata=True, verbose=False)
                if data and len(data) > 0:
                    first_data = data[0]
                    if isinstance(first_data, dict):
                        if 'wl' in first_data and 'absorption' in first_data:
                            first_data['wavelength'] = first_data['wl']
                        elif 'wavelength' in first_data and 'absorption' in first_data:
                            pass
                        else:
                            skipped += 1
                            errors.append((file_path.name, "缺少 wavelength/absorption 列"))
                            continue

                        label = str(first_data.get('label') or file_path.stem)
                        self.data_cache[label] = {'path': file_path, 'data': first_data}
                        item = QListWidgetItem(label)
                        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                        item.setCheckState(Qt.Checked)
                        self.file_list.addItem(item)
                        loaded_count += 1
                    else:
                        skipped += 1
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
                self.data_cache[base] = {'path': Path('<emission>'), 'data': ds}
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
            # 寿命模式没有合并图，去掉勾选框（QListWidgetItem 默认 flags 含
            # ItemIsUserCheckable，必须显式清除，否则仍会绘制勾选框）
            if self.spectrum_type != "lifetime":
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked)
            else:
                item.setFlags(item.flags() & ~Qt.ItemIsUserCheckable)
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
        """荧光寿命模式下，在信息页展示文件基本特征"""
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
        info_text += "\n点击「⏱ 开始拟合」按钮启动 MEM 拟合\n（结果将显示在预览图与本页）"
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
