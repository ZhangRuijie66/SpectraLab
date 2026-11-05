# -*- coding: utf-8 -*-
"""冒烟测试（v4.23）：跨样品汇总图 / PDF 报告是否复用已有寿命拟合结果。

场景复现用户反馈：
  拟合 1 个文件 → 点「跨样品汇总图」→ 点「导出 PDF 报告」
  修复前：两次操作都把 7 个样品全部重新拟合（共 14 次拟合）
  修复后：汇总图只拟合剩余的 6 个；PDF 报告 0 个新拟合（全部复用）

注意：脚本必须有 __main__ 保护——fit_many 用 ProcessPoolExecutor（spawn），
没有保护时子进程会重新执行整个脚本（既浪费又干扰结论）。
"""
import os
import shutil
import sys

_GUI_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _GUI_DIR)                      # 可视化分析GUI
sys.path.insert(0, os.path.dirname(_GUI_DIR))     # 画图（plot_lifetime 所在）
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

LIFE = r'D:\北大\光谱工具\示例数据\测试数据\lifetime-test2'


def main():
    from PyQt5.QtWidgets import QApplication, QMessageBox

    app = QApplication(sys.argv)
    for fn in ('information', 'warning', 'critical'):
        setattr(QMessageBox, fn, staticmethod(lambda *a, **k: None))

    import plot_lifetime as pl
    from absorption_gui import AbsorptionGUI

    # 监视 fit_many 实际收到多少个数据集
    calls = []
    _real_fit_many = pl.fit_many

    def spy(datasets, **kw):
        calls.append([d['name'] for d in datasets])
        return _real_fit_many(datasets, **kw)

    pl.fit_many = spy

    out_dir = os.path.join(_GUI_DIR, 'tests', '_diag', 'cache_out')
    shutil.rmtree(out_dir, ignore_errors=True)
    os.makedirs(out_dir, exist_ok=True)

    w = AbsorptionGUI()
    w.spectrum_type_combo.setCurrentIndex(2)
    w.load_data_from_folder(LIFE)
    n_files = len(w.data_cache)
    print('已加载寿命文件数 =', n_files, flush=True)
    assert n_files >= 3, '需要至少 3 个寿命文件'

    # 小参数快跑（缓存键含这些参数，前后保持一致即可）
    w.lifetime_auto_lambda_check.setChecked(False)
    w.lifetime_nrates_spin.setValue(51)
    params = w._collect_plot_params()
    print('fit 参数:',
          {k: v for k, v in params.items() if k.startswith('lifetime')},
          flush=True)

    first = list(w.data_cache.keys())[0]

    # ---------- 1) 单文件拟合（走真实路径，写入缓存）----------
    # 单文件路径用 MEMFitter 直接拟合，不经过 fit_many，所以这里不看 calls
    p1 = dict(params)
    p1.update({'selected_file': first, 'linewidth': 1.5, 'custom_title': ''})
    w._do_lifetime_plot(p1)
    assert len(w._lifetime_fit_cache) == 1, '单文件结果应进缓存'
    key = w._lifetime_cache_key(first, params)
    assert key in w._lifetime_fit_cache, '缓存键必须与 _lifetime_cache_key 一致'
    print('[1] 单文件拟合', first, '→ 缓存条目数 =',
          len(w._lifetime_fit_cache), flush=True)

    # ---------- 2) 跨样品汇总图：应只拟合剩下的 n-1 个 ----------
    calls.clear()
    msg = w._do_batch_export(dict(params, kind='summary', save_dir=out_dir))
    print('[2] 汇总图:', msg.replace('\n', ' | '), flush=True)
    print('    fit_many 收到 =', calls, flush=True)
    assert len(calls) == 1, f'应只调用一次 fit_many，实际 {len(calls)}'
    assert len(calls[0]) == n_files - 1, \
        f'汇总图应只拟合 {n_files - 1} 个（复用 1 个），实际 {len(calls[0])}'
    assert len(w._lifetime_fit_cache) == n_files, '汇总图结果应回写缓存'
    assert w._lifetime_cached_count(params) == n_files

    # ---------- 3) PDF 报告：应 0 个新拟合 ----------
    calls.clear()
    msg = w._do_batch_export(dict(params, kind='pdf', save_dir=out_dir))
    print('[3] PDF 报告:', msg.replace('\n', ' | '), flush=True)
    print('    fit_many 收到 =', calls, flush=True)
    assert calls == [], f'PDF 报告应全部复用缓存，实际新拟合 {calls}'
    assert '复用' in msg and '新拟合' not in msg, '提示文案应说明全部复用'

    # ---------- 4) 叠加分布：同样 0 个新拟合 ----------
    calls.clear()
    w._do_overlay_lifetime(dict(params))
    print('[4] 叠加分布 fit_many 收到 =', calls, flush=True)
    assert calls == [], '叠加分布应全部复用缓存'

    # ---------- 5) 改参数后缓存失效（键不同 → 重新拟合）----------
    calls.clear()
    w.lifetime_nrates_spin.setValue(61)
    params2 = w._collect_plot_params()
    w._do_batch_export(dict(params2, kind='summary', save_dir=out_dir))
    print('[5] 改速率点数后 fit_many 各批大小 =',
          [len(c) for c in calls], flush=True)
    assert len(calls) == 1 and len(calls[0]) == n_files, \
        f'参数变了应全部重新拟合，实际 {calls}'

    # ---------- 6) 产物检查 ----------
    made = sorted(os.listdir(out_dir))
    print('[6] 产出文件:', made, flush=True)
    assert any(f.endswith('.pdf') for f in made), 'PDF 报告未生成'
    assert any(f.endswith('.png') for f in made), '汇总图未生成'

    print('SMOKE TEST PASSED（fit_many 调用次数已按缓存最小化）', flush=True)


if __name__ == '__main__':
    import multiprocessing
    multiprocessing.freeze_support()
    main()
