# -*- coding: utf-8 -*-
"""D2/D3/D4/D5 离屏冒烟测试：会话恢复、深色主题、快捷键、最近文件夹。"""
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

    # ---------- D4 快捷键 ----------
    print('--- D4 shortcuts ---')
    seqs = [s.key().toString() for s in w._shortcuts]
    print('  registered:', seqs)
    print('  has show_help:', hasattr(w, 'show_help'))

    # ---------- D3 深色主题 ----------
    print('--- D3 theme ---')
    print('  default:', w.theme, '| BG =', w.theme_palette()['BG'])
    w.toggle_theme()
    print('  after toggle:', w.theme, '|', w.theme_btn.text(),
          '| BG =', w.theme_palette()['BG'], '| card =', w.theme_palette()['CARD'])
    import matplotlib as mpl
    print('  mpl fig facecolor =', mpl.rcParams['figure.facecolor'])
    w.toggle_theme()
    print('  back to:', w.theme, '| BG =', w.theme_palette()['BG'])

    # ---------- D5 最近文件夹 ----------
    print('--- D5 recent folders ---')
    folder = r'D:\北大\QLS Lab\SPC\1O2+luminol\谱图\光谱\20260727-RB-Lu'
    w._push_recent_folder(folder)
    print('  combo:', [w.recent_combo.itemText(i)
                       for i in range(w.recent_combo.count())])
    print('  drag methods:', hasattr(w, 'dragEnterEvent'),
          hasattr(w, 'dropEvent'), '| acceptDrops =', w.acceptDrops())

    # ---------- D2 会话恢复 ----------
    print('--- D2 session ---')
    w.spectrum_type_combo.setCurrentIndex(3)      # 3D 扫描
    w.load_data_from_folder(folder)               # 设置 current_folder
    w.pub_preset_combo.setCurrentIndex(2)         # 双栏
    w.dpi_spin.setValue(300)
    w.peak_value_check.setChecked(False)
    w.toggle_theme(True)                          # 深色
    w._save_session()
    print('  saved: mode=3 pub=双栏 dpi=300 peakval=False theme=dark')

    w2 = AbsorptionGUI()
    print('  restored: mode =', w2.spectrum_type,
          '| pub =', w2.pub_preset_combo.currentText(),
          '| dpi =', w2.dpi_spin.value(),
          '| peak_value =', w2.peak_value_check.isChecked(),
          '| theme =', w2.theme,
          '| folder =', getattr(w2, 'current_folder', None))
    # 复位，避免影响后续人工使用
    w2.toggle_theme(False)
    w2.pub_preset_combo.setCurrentIndex(0)
    w2.dpi_spin.setValue(600)
    w2.peak_value_check.setChecked(True)
    w2._save_session()
    print('SMOKE TEST PASSED')


if __name__ == '__main__':
    main()
