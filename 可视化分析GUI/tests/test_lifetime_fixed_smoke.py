# -*- coding: utf-8 -*-
"""C6 离屏冒烟测试：固定寿命分量。"""
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
folder = r'D:\北大\QLS Lab\SPC\ESIPT\谱图\吸收&荧光\20260724lifetime\20260724\esipt-1'
w.load_data_from_folder(folder)
w.lifetime_nrates_spin.setValue(201)

# --- 固定主分量 6.2 ns ---
w.lifetime_fixed_taus_edit.setText("6.2")
w._do_lifetime_plot()
r = w._last_lifetime_result
info = r['info']
print('fixed_taus =', info.get('fixed_taus'))
print('fixed_amplitudes =', [round(a, 3) for a in info.get('fixed_amplitudes', [])])
print('chi2R =', round(float(info['chi_sqr']), 5))
print('peak_result =', [[round(p[0], 3), round(p[1], 4)] for p in (r.get('peak_result') or [])])
print('k_dist len =', len(r['k_distribution']), 'k len =', len(r['k']))

# --- 非法输入不应崩溃 ---
w.lifetime_fixed_taus_edit.setText("abc, 3.6, , -1")
w._lifetime_fit_cache.clear()
w._do_lifetime_plot()
r2 = w._last_lifetime_result
print('after bad input fixed_taus =', r2['info'].get('fixed_taus'))

# --- 中文逗号也能解析 ---
w.lifetime_fixed_taus_edit.setText("0.5，3.6")
w._lifetime_fit_cache.clear()
w._do_lifetime_plot()
r3 = w._last_lifetime_result
print('multi fixed =', r3['info'].get('fixed_taus'),
      'amps =', [round(a, 3) for a in r3['info'].get('fixed_amplitudes', [])])
print('SMOKE TEST PASSED')
