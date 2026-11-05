# -*- coding: utf-8 -*-
"""v4.38 τ 范围输入 → 速率网格 k 的端到端验证（离屏，真实数据拟合）。

用法（在 可视化分析GUI 目录下）：
    python tests\test_tau_range_smoke.py
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.dirname(os.getcwd()))

from PyQt5.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication(sys.argv)
for fn in ('information', 'warning', 'critical'):
    setattr(QMessageBox, fn, staticmethod(lambda *a, **k: None))

from absorption_gui import AbsorptionGUI  # noqa: E402

FOLDER = r'D:\北大\光谱工具\示例数据\测试数据\esipt-1'

w = AbsorptionGUI()
w.spectrum_type_combo.setCurrentIndex(2)
print('mode =', w.spectrum_type, '| 面板标签 =',
      [w.lifetime_taumin_spin.value(), w.lifetime_taumax_spin.value()])
w.load_data_from_folder(FOLDER)
print('loaded:', list(w.data_cache))
if not w.data_cache:
    raise SystemExit('SKIP：样例数据不可用 ' + FOLDER)

# --- 0) 隔离会话记忆：本测试全部断言以 ns 为单位 ---
# 时间单位是会话级记忆（param/lifetime_unit），上一轮用 μs 会让 τ→k 换算差 1000 倍，
# 使下面的断言看起来「失败」。测试必须把单位钉死为 ns，不能依赖本机记忆状态。
w.lifetime_unit_combo.setCurrentIndex(0)      # 0 = ns
assert w.lifetime_unit_combo.currentIndex() == 0, '无法设为 ns 单位'

# --- 1) 默认 τ 0.01–100 ns（= 旧 k 100–0.01 /ns）---
w.lifetime_nrates_spin.setValue(201)
w.lifetime_taumin_spin.setValue(0.01)
w.lifetime_taumax_spin.setValue(100.0)
p = w._collect_plot_params()
print('params: tau =', p['lifetime_taumin'], p['lifetime_taumax'],
      '| k =', p['lifetime_kmin'], p['lifetime_kmax'])
assert abs(p['lifetime_kmin'] - 0.01) < 1e-12 and abs(p['lifetime_kmax'] - 100.0) < 1e-9
w._do_lifetime_plot()
info = w._last_lifetime_result['info']
print('[τ 0.01–100 ns] chi2R =', round(float(info['chi_sqr']), 4),
      '| info tau', info.get('tau_min_ns'), info.get('tau_max_ns'),
      '| info k', info.get('k_min'), info.get('k_max'))
assert abs(info['k_max'] - 100.0) < 1e-9 and abs(info['k_min'] - 0.01) < 1e-12

# --- 2) 拉长到 τ_max = 1000 ns（μs 级长寿命）---
w.lifetime_taumax_spin.setValue(1000.0)
p = w._collect_plot_params()
print('params: k_min =', p['lifetime_kmin'], '（应为 0.001）')
assert abs(p['lifetime_kmin'] - 0.001) < 1e-12
w._do_lifetime_plot()
info = w._last_lifetime_result['info']
print('[τ 0.01–1000 ns] chi2R =', round(float(info['chi_sqr']), 4),
      '| info tau', info.get('tau_min_ns'), info.get('tau_max_ns'),
      '| info k', info.get('k_min'), info.get('k_max'))
assert abs(info['k_min'] - 0.001) < 1e-12 and abs(info['tau_max_ns'] - 1000.0) < 1e-9
assert float(info['chi_sqr']) < 5.0, 'χ²R 异常大'

# --- 3) τ_min = 20 ns（用户诉求：下界可以大于 10 ns，只看长寿命成分）---
w.lifetime_taumin_spin.setValue(20.0)
w.lifetime_taumax_spin.setValue(1000.0)
assert abs(w.lifetime_taumin_spin.value() - 20.0) < 1e-9, 'τ_min 被上限夹住了'
p = w._collect_plot_params()
print('params: tau =', p['lifetime_taumin'], p['lifetime_taumax'],
      '| k =', p['lifetime_kmin'], p['lifetime_kmax'])
assert abs(p['lifetime_kmin'] - 0.001) < 1e-12 and abs(p['lifetime_kmax'] - 0.05) < 1e-12
w._do_lifetime_plot()
info = w._last_lifetime_result['info']
print('[τ 20–1000 ns] chi2R =', round(float(info['chi_sqr']), 4),
      '| info tau', info.get('tau_min_ns'), info.get('tau_max_ns'),
      '| info k', info.get('k_min'), info.get('k_max'))
assert abs(info['tau_min_ns'] - 20.0) < 1e-9 and abs(info['k_max'] - 0.05) < 1e-12
# 这份样品的真实寿命 ~3.6 ns，被 τ_min=20 ns 排除在外 → χ²R 必然爆炸。
# 这恰好证明"20–1000 ns"真的传进了拟合（若静默回退默认 0.01–100 ns，χ²R 会是 ~1.09）。
assert float(info['chi_sqr']) > 10.0, \
    f"范围没生效？χ²R={info['chi_sqr']:.4g}（期望远大于 1，因为真实寿命被排除在外）"

# --- 4) 信息页文本（用户实际看到的那一行）---
w._show_lifetime_fit_info()
for line in w.info_label.text().splitlines():
    if '寿命范围' in line or '速率网格' in line:
        print('INFO LINE:', line)

print('TAU RANGE SMOKE TEST PASSED')
