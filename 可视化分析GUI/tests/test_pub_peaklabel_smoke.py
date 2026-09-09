# -*- coding: utf-8 -*-
"""D6 + D7 离屏冒烟测试：出版图预设 + 峰位数值标注开关。"""
import os
import sys


def main():
    sys.path.insert(0, os.getcwd())
    sys.path.insert(0, os.path.dirname(os.getcwd()))

    from PyQt5.QtWidgets import QApplication, QMessageBox
    app = QApplication(sys.argv)
    for fn in ('information', 'warning', 'critical'):
        setattr(QMessageBox, fn, staticmethod(lambda *a, **k: None))
    from absorption_gui import AbsorptionGUI

    w = AbsorptionGUI()

    # ---------- D6：出版图预设 ----------
    print('--- D6 presets ---')
    for i in range(4):
        w.pub_preset_combo.setCurrentIndex(i)
        import matplotlib as mpl
        print(f'  {w.pub_preset_combo.currentText():22s} -> figsize={w._pub_preset()} '
              f'scale={w._pub_font_scale():.2f} rc_font={mpl.rcParams["font.size"]:.1f}')

    # 保存时临时改尺寸并恢复
    w.pub_preset_combo.setCurrentIndex(1)          # 单栏
    fig = w.canvas.fig
    before = tuple(round(v, 2) for v in fig.get_size_inches())
    tmp = os.path.join('plots', '_diag3d', 'pub_test.png')
    os.makedirs(os.path.dirname(tmp), exist_ok=True)
    w._savefig_pub(fig, tmp, dpi=100)
    after = tuple(round(v, 2) for v in fig.get_size_inches())
    print(f'  savefig: before={before} after={after} file={os.path.getsize(tmp)}B')
    assert before == after, '导出后尺寸未恢复！'

    # ---------- D7：峰位标数值 ----------
    print('--- D7 peak labels ---')
    w.pub_preset_combo.setCurrentIndex(0)
    w.spectrum_type_combo.setCurrentIndex(1)       # 发射
    folder = r'D:\北大\QLS Lab\SPC\ESIPT\谱图\吸收&荧光\20260723-ESIPT-1-DMF'
    w.load_data_from_folder(folder)
    print('loaded:', list(w.data_cache))
    w.mark_peaks_check.setChecked(True)

    w.peak_value_check.setChecked(True)
    fig = w._do_plot()
    texts_on = [t.get_text() for t in fig.axes[0].texts if t.get_text()]
    print('  标注开 ->', len(texts_on), '个文本，例:', texts_on[:5])

    w.peak_value_check.setChecked(False)
    fig = w._do_plot()
    texts_off = [t.get_text() for t in fig.axes[0].texts if t.get_text()]
    print('  标注关 ->', len(texts_off), '个文本，例:', texts_off[:5])

    print('  _peak_label 开/关:', end=' ')
    w.peak_value_check.setChecked(True)
    a = w._peak_label(451.7)
    w.peak_value_check.setChecked(False)
    b = w._peak_label(451.7)
    print(repr(a), repr(b))
    print('SMOKE TEST PASSED')


if __name__ == '__main__':
    main()
