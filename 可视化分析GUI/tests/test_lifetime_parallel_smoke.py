# -*- coding: utf-8 -*-
"""C1 + C8 离屏冒烟测试：并行拟合 + 寿命分布叠加。

注意：用多进程必须在 `if __name__ == "__main__"` 里跑（Windows spawn 会重新
导入 __main__），所以这个脚本带 main 保护。
"""
import os
import sys
import time


def main():
    sys.path.insert(0, os.getcwd())
    sys.path.insert(0, os.path.dirname(os.getcwd()))

    import numpy as np
    import plot_lifetime as pl

    folder = os.path.join(os.getcwd(), 'test')
    names = ['Fig9_FoldedRNA.csv', 'Fig9_DenaturedRNA.csv',
             'Fig5_1M_Acrylamide.csv']
    datasets = []
    for n in names:
        d = pl.parse_decay_csv(os.path.join(folder, n))
        datasets.append({'name': n.replace('.csv', ''), 'time': d['time'],
                         'decay': d['decay'], 'irf': d['irf'],
                         'meta': d.get('meta')})
    print('datasets:', [d['name'] for d in datasets])

    kw = dict(method='SESM', n_rates=101)

    t0 = time.time()
    serial = pl.fit_many(datasets, max_workers=1, fit_kwargs=kw)
    t_serial = time.time() - t0

    t0 = time.time()
    par = pl.fit_many(datasets, max_workers=3, fit_kwargs=kw)
    t_par = time.time() - t0

    print(f'serial  {t_serial:6.1f}s  -> {sum(1 for r in serial if r)} ok')
    print(f'parallel{t_par:6.1f}s  -> {sum(1 for r in par if r)} ok')
    print(f'speedup = {t_serial / max(t_par, 1e-9):.2f}x')
    for r in par:
        if r:
            print(f"  {r['name']}: χ²R = {r['info']['chi_sqr']:.4g}, "
                  f"peaks = {[(round(p[0], 3), round(p[1], 3)) for p in (r.get('peak_result') or [])]}")

    # ---- GUI 叠加按钮 ----
    from PyQt5.QtWidgets import QApplication, QMessageBox
    app = QApplication(sys.argv)
    for fn in ('information', 'warning', 'critical'):
        setattr(QMessageBox, fn, staticmethod(lambda *a, **k: None))
    from absorption_gui import AbsorptionGUI

    w = AbsorptionGUI()
    w.spectrum_type_combo.setCurrentIndex(2)
    w.load_data_from_folder(folder)
    print('loaded for GUI:', list(w.data_cache))
    w.lifetime_method_combo.setCurrentIndex(1)   # SESM 快
    w.lifetime_nrates_spin.setValue(101)
    fig = w._do_overlay_lifetime()
    res = w._overlay_results
    print('overlay ok:', sum(1 for r in res if r), '/', len(res))
    print('overlay axes:', len(fig.axes))
    out = os.path.join('plots', '_diag3d', 'overlay.png')
    os.makedirs(os.path.dirname(out), exist_ok=True)
    fig.savefig(out, dpi=110, bbox_inches='tight')
    print('saved', out)
    print('SMOKE TEST PASSED')


if __name__ == '__main__':
    main()
