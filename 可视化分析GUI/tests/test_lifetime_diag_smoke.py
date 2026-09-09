# -*- coding: utf-8 -*-
"""C4/C5 离屏冒烟测试：拟合诊断图 + 拟合质量报告。"""
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

print('tabs before fit:', [w.tab_widget.tabText(i)
                           for i in range(w.tab_widget.count())])
print('diag tab visible:', w.tab_widget.tabBar().isTabVisible(
    w.tab_widget.indexOf(w.diag_tab)))

w.lifetime_nrates_spin.setValue(201)
w._do_lifetime_plot()
r = w._last_lifetime_result
m = w._fit_quality_metrics(r)
print('--- quality metrics ---')
for k in ('npts', 'chi2', 'chi2r', 'dw', 'res_mean', 'res_std',
          'acf_lag1', 'acf_ci', 'pearson_outliers'):
    if k in m:
        v = m[k]
        print(f'  {k:16s} = {v:.5g}' if isinstance(v, float) else f'  {k:16s} = {v}')
print('  acf len =', len(m.get('acf', [])))
print('diag canvas axes after fit =', len(w.diag_canvas.fig.axes))
w._show_lifetime_fit_info()
txt = w.info_label.text()
print('--- info tail ---')
print('\n'.join(txt.splitlines()[-14:]))

# 切回吸收模式，两个寿命标签页应隐藏
w.spectrum_type_combo.setCurrentIndex(0)
print('diag hidden in absorption:',
      not w.tab_widget.tabBar().isTabVisible(w.tab_widget.indexOf(w.diag_tab)))
print('SMOKE TEST PASSED')
