# -*- coding: utf-8 -*-
"""深色主题视觉验收：原生平台、不 show()、直接 grab()（offscreen 截图文字会空白）。"""
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
    w.resize(1500, 880)
    w.toggle_theme(True)
    folder = r'D:\北大\QLS Lab\SPC\ESIPT\谱图\吸收&荧光\20260723-ESIPT-1-DMF'
    w.spectrum_type_combo.setCurrentIndex(1)
    w.load_data_from_folder(folder)
    w.update_plot()
    import time
    for _ in range(60):          # 等后台绘图线程画完
        app.processEvents()
        time.sleep(0.1)
    out = os.path.join('plots', '_diag3d', 'dark_theme.png')
    os.makedirs(os.path.dirname(out), exist_ok=True)
    ok = w.grab().save(out)
    print('saved', out, ok, os.path.getsize(out) if ok else 0)
    w.toggle_theme(False)
    w._save_session()
    print('done')


if __name__ == '__main__':
    main()
