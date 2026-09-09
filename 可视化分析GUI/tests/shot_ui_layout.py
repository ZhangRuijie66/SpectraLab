# -*- coding: utf-8 -*-
"""UI 修复视觉验收：默认窗口尺寸下截参数栏（原生平台，不 show()）。"""
import os
import sys


def main():
    sys.path.insert(0, os.getcwd())
    sys.path.insert(0, os.path.dirname(os.getcwd()))
    from PyQt5.QtCore import QSettings
    from PyQt5.QtWidgets import QApplication, QMessageBox

    app = QApplication(sys.argv)
    for fn in ('information', 'warning', 'critical'):
        setattr(QMessageBox, fn, staticmethod(lambda *a, **k: None))

    # 清掉会话/几何，测「默认布局」
    from gui_config import APP_ORG, APP_NAME
    s = QSettings(APP_ORG, APP_NAME)
    for k in ('geometry', 'last_mode', 'last_folder', 'theme'):
        s.remove(k)
    s.sync()

    from absorption_gui import AbsorptionGUI
    w = AbsorptionGUI()
    w.resize(1500, 880)

    out_dir = os.path.join('plots', '_diag3d')
    os.makedirs(out_dir, exist_ok=True)

    # ---- 3D 扫描模式 ----
    w.spectrum_type_combo.setCurrentIndex(3)
    w.load_data_from_folder(
        r'D:\北大\QLS Lab\SPC\1O2+luminol\谱图\光谱\20260727-RB-Lu')
    for _ in range(40):
        app.processEvents()
    p1 = os.path.join(out_dir, 'ui_scan3d.png')
    w.grab().save(p1)
    print('saved', p1)

    # 参数栏单独截一张（看清是否还有横向截断）
    p1b = os.path.join(out_dir, 'ui_scan3d_param.png')
    w.param_panel.grab().save(p1b)
    print('saved', p1b)
    p1c = os.path.join(out_dir, 'ui_scan3d_group.png')
    w.scan3d_options_group.grab().save(p1c)
    print('saved', p1c, 'size', w.scan3d_options_group.width(),
          w.scan3d_options_group.sizeHint().width())

    # ---- 荧光寿命模式（看自动 λ 是否默认勾选 + 参数栏宽度）----
    w.spectrum_type_combo.setCurrentIndex(2)
    for _ in range(10):
        app.processEvents()
    print('auto_lambda checked =', w.lifetime_auto_lambda_check.isChecked())
    print('lambda spin enabled =', w.lifetime_lambda_spin.isEnabled())
    p2 = os.path.join(out_dir, 'ui_lifetime_param.png')
    w.param_panel.grab().save(p2)
    print('saved', p2)

    p3 = os.path.join(out_dir, 'ui_tree_panel.png')
    w.tree_panel.grab().save(p3)
    print('saved', p3)
    print('folder label text =', repr(w.folder_label.text()))
    print('folder tooltip =', repr(w.folder_label.toolTip()))
    print('done')


if __name__ == '__main__':
    main()
