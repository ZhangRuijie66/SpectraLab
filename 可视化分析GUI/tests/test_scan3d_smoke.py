# -*- coding: utf-8 -*-
"""3D 扫描 (EEM) 模式的离屏冒烟测试（临时脚本，可删）。"""
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
w.spectrum_type_combo.setCurrentIndex(3)
print('mode =', w.spectrum_type)
print('scan3d group visible =', w.scan3d_options_group.isVisible(),
      '| lifetime group =', w.lifetime_options_group.isVisible(),
      '| peaks group =', w.peaks_group.isVisible())

folder = r'D:\北大\QLS Lab\SPC\1O2+luminol\谱图\光谱\20260727-RB-Lu'
w.load_data_from_folder(folder)
print('loaded files:', list(w.data_cache))

for i in range(3):
    w.scan3d_plot_combo.setCurrentIndex(i)
    fig = w._do_scan3d_plot()
    r = w._last_scan3d_result
    st = r['stats']
    print(f'  type {i} ({r["plot_type"]}) axes={len(fig.axes)} '
          f'kept={st.get("comb_kept")} notched={st.get("comb_notched")}')

w.scan3d_comb_combo.setCurrentIndex(3)   # 不处理
w.scan3d_plot_combo.setCurrentIndex(1)
w._do_scan3d_plot()
print('  no-comb mode ok, comb_notched =',
      w._last_scan3d_result['stats'].get('comb_notched'))

w.scan3d_comb_combo.setCurrentIndex(1)   # 乘性除法
w._do_scan3d_plot()
print('  divide mode ok, gain =',
      w._last_scan3d_result['stats'].get('comb_gain_min'),
      w._last_scan3d_result['stats'].get('comb_gain_max'))

w.spectrum_type_combo.setCurrentIndex(0)
print('back to', w.spectrum_type, '| integ group visible =', w.integ_group.isVisible())
print('SMOKE TEST PASSED')
