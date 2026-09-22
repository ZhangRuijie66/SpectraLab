# -*- coding: utf-8 -*-
"""C2/C7/B4 离屏冒烟测试（临时脚本）。"""
import os
import sys

sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.dirname(os.getcwd()))

from PyQt5.QtWidgets import QApplication, QMessageBox

app = QApplication(sys.argv)
for fn in ('information', 'warning', 'critical'):
    setattr(QMessageBox, fn, staticmethod(lambda *a, **k: None))

from absorption_gui import AbsorptionGUI  # noqa: E402

w = AbsorptionGUI()
w.spectrum_type_combo.setCurrentIndex(2)
print('mode =', w.spectrum_type)

folder = r'D:\北大\QLS Lab\SPC\ESIPT\谱图\吸收&荧光\20260724lifetime\20260724\esipt-1'
w.load_data_from_folder(folder)
print('loaded:', list(w.data_cache))

# --- C7: 自定义寿命范围 τ（→ k 网格）+ C2: 本底中位数 ---
w.lifetime_nrates_spin.setValue(201)
w.lifetime_taumin_spin.setValue(0.01)     # → k_max = 100 /ns
w.lifetime_taumax_spin.setValue(100.0)    # → k_min = 0.01 /ns
fig = w._do_lifetime_plot()
r = w._last_lifetime_result
info = r['info']
print('chi2 =', round(float(info['chi_sqr']), 4))
print('bg_stat =', info.get('decay_background_stat'),
      '| bg_median =', round(float(info['decay_background']), 2),
      '| bg_mean =', round(float(info['decay_background_mean']), 2))
print('info keys:', sorted(info.keys()))
for k in ('k_min', 'k_max', 'n_rates', 'rates'):
    if k in info:
        v = info[k]
        print(f'  {k} =', (v if not hasattr(v, '__len__') else f'len={len(v)}'))

# --- B4: 导出格式 ---
print('--- export formats ---')
for i in range(6):
    w.export_format_combo.setCurrentIndex(i)
    print(f'  {i} {w.export_format_combo.currentText():22s} -> {w._export_formats()}')

tmp = r'D:\北大\QLS Lab\.dsh-tmp\exp_test'
os.makedirs(tmp, exist_ok=True)
for f in os.listdir(tmp):
    os.remove(os.path.join(tmp, f))
w.export_format_combo.setCurrentIndex(4)   # PNG + SVG
w._export_lifetime_plots(tmp)
print('exported:', sorted(os.listdir(tmp)))
w.export_format_combo.setCurrentIndex(5)   # 全部
w._export_lifetime_plots(tmp)
print('exported all:', sorted(os.listdir(tmp)))
print('SMOKE TEST PASSED')
