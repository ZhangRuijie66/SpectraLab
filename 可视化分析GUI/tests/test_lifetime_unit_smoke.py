# -*- coding: utf-8 -*-
"""v4.39 寿命「时间单位」（ns / μs）端到端冒烟测试（离屏，真实数据拟合）。

覆盖：
  1. 选「微秒」后 τ 输入 → 速率网格 k 的换算（k = 1/τ(ns)）；
  2. 真跑一次 MEM 拟合，检查拟合图时间轴 / 寿命分布 τ 轴 / 信息页都按 μs 显示；
  3. 改「绘图标题」后走纯外观重绘（v4.39 修的 bug：以前改标题画面不动）；
  4. 导出 PNG（标题与坐标轴单位应写进图里）。

用法（在 可视化分析GUI 目录下）：
    python tests\\test_lifetime_unit_smoke.py
"""
import os
import sys
import tempfile

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.dirname(os.getcwd()))

from PyQt5.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication(sys.argv)
for fn in ('information', 'warning', 'critical'):
    setattr(QMessageBox, fn, staticmethod(lambda *a, **k: None))

from absorption_gui import AbsorptionGUI  # noqa: E402

FOLDER = (r'D:\北大\光谱工具\示例数据\03-荧光寿命-Ce6')

w = AbsorptionGUI()
w.spectrum_type_combo.setCurrentIndex(2)                 # 荧光寿命模式
w.load_data_from_folder(FOLDER)
print('loaded:', list(w.data_cache))
if not w.data_cache:
    raise SystemExit('SKIP：样例数据不可用 ' + FOLDER)

# --- 1) 切到微秒，τ 范围 1–1000 μs ---
w.lifetime_unit_combo.setCurrentIndex(1)
assert w.lifetime_unit == 'us' and abs(w.lifetime_unit_factor - 1000.0) < 1e-9
print('单位标签:', w.lifetime_taumin_label.text(), w.lifetime_taumax_label.text(),
      w.lifetime_fixed_tau_label.text())
w.lifetime_nrates_spin.setValue(201)
w.lifetime_taumin_spin.setValue(1.0)          # = 1000 ns
w.lifetime_taumax_spin.setValue(1000.0)       # = 1e6 ns
p = w._collect_plot_params()
print('params: tau(us) =', p['lifetime_taumin'], p['lifetime_taumax'],
      '| k(1/ns) =', p['lifetime_kmin'], p['lifetime_kmax'],
      '| unit =', p['lifetime_unit'])
assert abs(p['lifetime_kmax'] - 1e-3) < 1e-18, p['lifetime_kmax']
assert abs(p['lifetime_kmin'] - 1e-6) < 1e-21, p['lifetime_kmin']

# --- 2) 真跑一次拟合 ---
w._do_lifetime_plot()
result = w._last_lifetime_result
info = result['info']
print('chi2R =', round(float(info['chi_sqr']), 4),
      '| 分量 τ(ns) =', [round(float(x[0]), 2) for x in (result.get('peak_result') or [])])
assert (info['tau_min_ns'], info['tau_max_ns']) == (1000.0, 1e6), \
    (info['tau_min_ns'], info['tau_max_ns'])

# 主画布：残差轴 = Time (μs)；寿命分布轴 = τ (μs)
main_axes = w.canvas.fig.axes
print('主画布轴标签:', [a.get_xlabel() for a in main_axes])
assert any('μs' in a.get_xlabel() for a in main_axes), \
    [a.get_xlabel() for a in main_axes]
dist_ax = w.lifetime_canvas.fig.axes[0]
print('寿命分布轴标签:', dist_ax.get_xlabel())
assert 'μs' in dist_ax.get_xlabel(), dist_ax.get_xlabel()

# IRF 必须真的画出来（v4.39 初版在 μs 模式把 IRF 强度也除以 1000 → 整条看不见）
ax1 = w.canvas.fig.axes[0]
irf_line = next((ln for ln in ax1.get_lines()
                 if ln.get_label().startswith('IRF')), None)
assert irf_line is not None, '拟合图上没有 IRF 曲线'
irf_y = np.asarray(irf_line.get_ydata(), float)
irf_ns = np.asarray(info['irf_shifted'], float)
print('IRF: ymax = %.4g（原始 %d 点，ymax=%.4g）, ylim = %s'
      % (np.nanmax(irf_y), irf_ns.size, np.nanmax(irf_ns),
         tuple(round(v, 2) for v in ax1.get_ylim())))
assert np.allclose(irf_y, irf_ns), 'µs 模式下 IRF 强度被误换算'
assert np.nanmax(irf_y) >= ax1.get_ylim()[0] * 1.5, 'IRF 掉到 y 轴范围外（看不见）'

# 信息页：τ 与寿命范围都应是 μs
w._show_lifetime_fit_info()
info_lines = [ln for ln in w.info_label.text().splitlines()
              if ('τ' in ln and ('=' in ln or '寿命范围' in ln))]
for ln in info_lines[:6]:
    print('INFO:', ln.strip())
assert any('μs' in ln for ln in info_lines), info_lines
assert not any(' ns' in ln for ln in info_lines), info_lines

# --- 3) 改标题 → 纯外观重绘（不重新拟合）---
w.title_edit.setText('Ce6 1O2 磷光（μs）')
w._rerender_lifetime_cosmetic()
title_main = w.canvas.fig.axes[0].get_title()
title_dist = w.lifetime_canvas.fig.axes[0].get_title()
print('重绘后标题:', title_main, '|', title_dist)
assert title_main == 'Ce6 1O2 磷光（μs）', title_main
assert title_dist.startswith('Ce6 1O2 磷光（μs）'), title_dist

# --- 4) 导出 PNG（标题/单位写进图里）---
tmp = tempfile.mkdtemp(prefix='spectra_unit_smoke_')
w.export_format_combo.setCurrentIndex(0)                 # PNG
w._export_lifetime_plots(tmp)
files = sorted(os.listdir(tmp))
print('导出:', files)
assert any(f.endswith('_lifetime_fit.png') for f in files), files
assert any(f.endswith('_fit_result.json') for f in files), files
assert all(os.path.getsize(os.path.join(tmp, f)) > 10240
           for f in files if f.endswith('.png')), '导出的 PNG 太小'

print('LIFETIME UNIT SMOKE TEST PASSED')
