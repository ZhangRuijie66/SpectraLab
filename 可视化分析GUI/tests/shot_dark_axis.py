# -*- coding: utf-8 -*-
"""深色主题坐标轴对比度视觉验收（v4.20）。

原生平台、不 show()、直接 grab()（offscreen 截图文字会空白）。
产出 plots/_diag3d/ 下若干 PNG 供人工目检：
    dark_axis_emission.png   深色·发射合并图（坐标轴/刻度/网格）
    dark_axis_single.png     深色·吸收单独图（曾因 _palette 同名而报错）
    dark_axis_lifetime.png   深色·寿命拟合（含 χ²R 数值框）
    dark_axis_peaks.png      深色·寿命分布页（曾为黑色曲线）
    dark_axis_diag.png       深色·拟合诊断页（网格线）
    light_axis_emission.png  浅色对照（应与 v4.19 一致）

用法（在 可视化分析GUI 目录下）：
    python tests/shot_dark_axis.py
"""
import os
import sys
import time

OUT_DIR = os.path.join('plots', '_diag3d')
EMISSION_DIR = (r'D:\北大\光谱工具\示例数据\测试数据\20260723-ESIPT-1-DMF')
LIFETIME_DIR = (r'D:\北大\光谱工具\示例数据\测试数据\esipt-1')


def _wait(app, seconds=6.0):
    """等后台绘图线程画完。"""
    for _ in range(int(seconds * 10)):
        app.processEvents()
        time.sleep(0.1)


def _save(widget, name):
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, name)
    ok = widget.grab().save(path)
    print(f'  saved {path} ({os.path.getsize(path) if ok else 0} bytes)')


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

    # ---- 1. 深色 · 发射合并图 ----
    print('--- dark / emission combined ---')
    w.toggle_theme(True)
    w.spectrum_type_combo.setCurrentIndex(1)
    if os.path.isdir(EMISSION_DIR):
        w.load_data_from_folder(EMISSION_DIR)
        w.update_plot()
        _wait(app)
        _save(w.canvas, 'dark_axis_emission.png')

        # ---- 2. 深色 · 单独图（v4.19 因 _palette 同名会报错）----
        print('--- dark / single plot ---')
        if w.file_list.count():
            w.file_list.setCurrentRow(0)          # 单独图按选中文件绘制
        w.plot_type_combo.setCurrentIndex(1)
        fig = w._do_plot()
        print('  single plot axes =', len(fig.axes),
              'lines =', [len(a.lines) for a in fig.axes])
        _wait(app, 2.0)
        _save(w.canvas, 'dark_axis_single.png')
        w.plot_type_combo.setCurrentIndex(0)
    else:
        print('  （跳过：发射样例数据不存在）')

    # ---- 3. 深色 · 寿命拟合 / 寿命分布 / 拟合诊断 ----
    print('--- dark / lifetime ---')
    if os.path.isdir(LIFETIME_DIR):
        w.spectrum_type_combo.setCurrentIndex(2)
        w.load_data_from_folder(LIFETIME_DIR)
        if w.data_cache:
            w.lifetime_nrates_spin.setValue(201)
            # 关掉实时预览防抖定时器：否则它在拟合完成后触发 update_plot()，
            # 会把画布换成「点击开始拟合」的提示文字，截图就不是拟合结果了
            w._live_timer.stop()
            app.processEvents()
            w._do_lifetime_plot()
            r = w._last_lifetime_result or {}
            print('  chi2R =', r.get('info', {}).get('chi_sqr'))
            w._live_timer.stop()
            _wait(app, 3.0)
            _save(w.canvas, 'dark_axis_lifetime.png')
            w.tab_widget.setCurrentWidget(w.dist_tab)
            app.processEvents()
            _save(w.lifetime_canvas, 'dark_axis_peaks.png')
            w.tab_widget.setCurrentWidget(w.diag_tab)
            app.processEvents()
            _save(w.diag_canvas, 'dark_axis_diag.png')
            w.tab_widget.setCurrentIndex(0)
        else:
            print('  （跳过：寿命样例数据未加载）')
    else:
        print('  （跳过：寿命样例数据不存在）')

    # ---- 4. 浅色对照 ----
    print('--- light / emission combined ---')
    w.toggle_theme(False)
    if os.path.isdir(EMISSION_DIR):
        w.spectrum_type_combo.setCurrentIndex(1)
        w.load_data_from_folder(EMISSION_DIR)
        w.update_plot()
        _wait(app)
        _save(w.canvas, 'light_axis_emission.png')

    print('DONE')


if __name__ == '__main__':
    main()
