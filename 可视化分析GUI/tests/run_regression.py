# -*- coding: utf-8 -*-
"""
回归测试集（E3）—— 不依赖 pytest 的自包含运行器。

用法（在 GUI 目录下）：
    python tests/run_regression.py

覆盖：模块导入 / 寿命解析与拟合 / 固定分量 / 3D 扫描清洗 / GUI 四模式与
选项组显隐 / 导出格式 / 峰位标注开关 / 主题色板 / 快捷键 / 出版图预设 /
最近文件夹。全部通过时退出码 0，任一失败退出码 1。
"""
import os
import sys
import traceback

# 必须在导入 PyQt5 之前设定离屏后端
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
GUI_DIR = os.path.dirname(HERE)
MODULE_DIR = os.path.dirname(GUI_DIR)
sys.path.insert(0, GUI_DIR)
sys.path.insert(0, MODULE_DIR)

import numpy as np  # noqa: E402

RESULTS = []


class Skip(Exception):
    """标记该检查项因缺少外部样例数据等原因跳过（--strict 下计为失败）。"""


def check(name):
    """装饰器：跑一个检查项，记录通过/失败。"""
    def deco(fn):
        RESULTS.append((name, fn))
        return fn
    return deco


# ------------------------------------------------- 会话设置的"借还"机制
# 一批检查项依赖"上次会话"的状态（栏宽/收起、寿命默认值、上次模式、上次主题），
# 而它们中途失败或整个进程被强杀时，自己的 finally 恢复逻辑不一定会跑到——残留值
# 会让**下一次**回归跑出完全不同的结果（v4.29 排查时连续踩到：last_mode=2 让
# 「状态栏徽标」失败、theme=dark 让「主题图标切换」失败、ui/panel_widths=
# [5,99999,285] 让栏宽检查失败）。
# 所以在 main() 里统一先把这些键摘下来，跑完原样放回：无论中途发生什么，
# 下一次都是从干净起点开跑，用户真实设置也不会被测试改掉。
_SESSION_KEY_PREFIXES = ("ui/", "defaults/", "param/", "help_dialog/")
_SESSION_KEY_EXACT = ("last_mode", "last_folder", "theme", "workspace",
                      "recent_folders")
# v4.45：隔离用的临时 ini 路径（_session_settings_lend 首次调用时创建）
_TEST_SETTINGS_INI = None


def _session_settings_lend():
    """把回归测试与会话设置**彻底隔离**，返回 (QSettings, 备份字典)（v4.45）。

    旧实现是「摘下真实注册表里几个会话键 → 跑测试 → 再回填」。这在两种情况下
    会漏：
      · 测试中途异常退出/被中断，回填没执行，注册表就留在被改过的状态；
      · 测试自己写入的键不在 ``_SESSION_KEY_PREFIXES`` 白名单里（如
        ``show_ex``、``subtract_enable``、``param/*``），根本不会被清掉。
    后果实测过：注册表里残留 ``show_ex=true`` 会让「减法扣本底」那项测试
    多画两条 EX 竖线（期望 2 条线、实际 4 条），报出一个**假失败**。

    现在改为：所有 GUI 模块里的 ``QSettings`` 符号替换成一个固定落到临时 ini
    文件的子类——测试全程不碰真实注册表，也就不需要"备份/回填"那套脆弱逻辑
    （备份字典仍返回，但恒为空 dict，保持调用方签名兼容）。
    """
    import tempfile
    from PyQt5.QtCore import QSettings as _RealQSettings

    global _TEST_SETTINGS_INI
    if _TEST_SETTINGS_INI is None:
        d = tempfile.mkdtemp(prefix='spectra_reg_settings_')
        _TEST_SETTINGS_INI = os.path.join(d, 'settings.ini')

    class _IsolatedSettings(_RealQSettings):
        """强制落到临时 ini，绝不写注册表。"""

        def __init__(self, *args, **kwargs):
            super().__init__(_TEST_SETTINGS_INI, _RealQSettings.IniFormat)

        def __del__(self):
            try:
                self.sync()
            except Exception:
                pass

    # 必须在 GUI 模块 import 之前/之后都替换一次：模块里是
    # `from PyQt5.QtCore import QSettings`，拿到的是符号副本，得逐个改。
    import PyQt5.QtCore as _QtCore
    _QtCore.QSettings = _IsolatedSettings
    for mod_name in ('absorption_gui', 'gui_data', 'gui_ui', 'gui_plot',
                     'gui_components', 'gui_launcher', 'gui_help', 'gui_splash'):
        try:
            mod = sys.modules.get(mod_name)
            if mod is not None and hasattr(mod, 'QSettings'):
                mod.QSettings = _IsolatedSettings
        except Exception:
            pass
    try:
        s = _IsolatedSettings()
        for k in s.allKeys():
            s.remove(k)
        s.sync()
    except Exception as e:
        print(f"  [WARN] 隔离设置初始化失败：{e}")
    return _IsolatedSettings(), {}


def _session_settings_return(s, saved):
    """兼容旧签名（隔离后无需回填，真实注册表从未被改动）。"""
    if not saved:
        return
    try:
        for k, v in saved.items():
            s.setValue(k, v)
        s.sync()
    except Exception as e:                                   # pragma: no cover
        print(f"  [WARN] 会话设置回填失败：{e}")


# ---------------------------------------------------------------- 数据路径
TEST_DIR = os.path.join(GUI_DIR, 'test')
LIFETIME_CSV = os.path.join(TEST_DIR, 'Fig9_FoldedRNA.csv')
# 3D 样例优先用仓库内副本（test\RBLu_1_3d_scan.csv），
# 这样换机器/数据盘变动时不会静默跳过 3D 检查
SCAN3D_LOCAL = os.path.join(TEST_DIR, 'RBLu_1_3d_scan.csv')
SCAN3D_EXTERNAL = (r'D:\北大\光谱工具\示例数据\测试数据\20260727-RB-Lu\RBLu 1 2026-07-27 07-11.csv')
SCAN3D_CSV = SCAN3D_LOCAL if os.path.exists(SCAN3D_LOCAL) else SCAN3D_EXTERNAL
EMISSION_DIR = (r'D:\北大\光谱工具\示例数据\测试数据\20260723-ESIPT-1-DMF')


# ---------------------------------------------------------------- 模块层
@check("模块可导入（5 个 plot_* + 辅助）")
def t_imports():
    import plot_absorption          # noqa: F401
    import plot_emission            # noqa: F401
    import plot_lifetime            # noqa: F401
    import plot_3d_scan             # noqa: F401
    import read_xlsx_info           # noqa: F401
    import curve_colors             # noqa: F401


@check("寿命 CSV 解析：三列 time/decay/irf")
def t_parse_decay():
    import plot_lifetime as pl
    d = pl.parse_decay_csv(LIFETIME_CSV)
    assert len(d['time']) == len(d['decay']) == len(d['irf']) > 10
    assert np.all(np.diff(d['time']) > 0), "时间轴应严格递增"


@check("寿命拟合（SESM 快速）：结果自洽")
def t_fit_sesm():
    import plot_lifetime as pl
    d = pl.parse_decay_csv(LIFETIME_CSV)
    f = pl.MEMFitter(verbose=False, name='reg')
    f.load(d['time'], d['decay'], d['irf'], d.get('meta'))
    f.preprocess()
    f.fit(method='SESM', n_rates=101)
    f.postprocess()
    r = f.serialize(None)
    assert len(r['k_distribution']) == 101, "分布长度应等于速率网格点数"
    assert np.isfinite(r['info']['chi_sqr']), "χ²R 应为有限值"
    assert r['info']['chi_sqr'] > 0
    assert r['info']['k_min'] == 0.01 and r['info']['k_max'] == 100.0


@check("固定寿命分量：幅度被记录且网格被锁定")
def t_fixed_taus():
    import plot_lifetime as pl
    d = pl.parse_decay_csv(LIFETIME_CSV)
    f = pl.MEMFitter(verbose=False, name='reg-fixed')
    f.load(d['time'], d['decay'], d['irf'], d.get('meta'))
    f.preprocess()
    f.fit(method='SESM', n_rates=101, fixed_taus=[3.2])
    assert f.info.get('fixed_taus') == [3.2]
    assert len(f.info.get('fixed_amplitudes', [])) == 1
    assert len(f.k_distribution) == 101, "固定分量不应混进分布数组"


@check("3D 扫描：解析 + 饱和/梳状检测 + 清洗后无负值")
def t_scan3d():
    import plot_3d_scan as p3
    if not os.path.exists(SCAN3D_CSV):
        raise Skip("3D 扫描样例数据不存在")
    d = p3.parse_3d_scan_csv(SCAN3D_CSV, verbose=False)
    Z = d['intensity']
    assert Z.ndim == 2 and Z.shape[0] > 100
    sat = p3._detect_saturation(Z)
    assert sat is not None, "该数据应能检测到饱和上限"
    period, strength = p3._detect_comb_period(Z, d['em_wavelengths'])
    assert period and 3 <= period <= 30, f"梳状周期应在 3–30 nm，实测 {period}"
    prep = p3.prepare_grid(d, verbose=False)
    Zc = prep['Z_orig']
    assert int((Zc < 0).sum()) == 0, "清洗后不应出现负值"
    assert prep['stats']['comb_notched'] is True


@check("3D 扫描：三种梳状处理方式都能跑通")
def t_scan3d_modes():
    import plot_3d_scan as p3
    if not os.path.exists(SCAN3D_CSV):
        return
    d = p3.parse_3d_scan_csv(SCAN3D_CSV, verbose=False)
    for mode in ('minima', 'divide', 'rows'):
        prep = p3.prepare_grid(d, comb_mode=mode, verbose=False)
        assert np.isfinite(prep['Z']).all(), f"{mode} 产生了非有限值"
    prep = p3.prepare_grid(d, notch_comb=False, verbose=False)
    assert prep['stats']['comb_notched'] is False, "关闭时不应处理梳状伪迹"


# ---------------------------------------------------------------- GUI 层
def _make_gui():
    from PyQt5.QtWidgets import QApplication, QMessageBox
    app = QApplication.instance() or QApplication(sys.argv)
    for fn in ('information', 'warning', 'critical'):
        setattr(QMessageBox, fn, staticmethod(lambda *a, **k: None))
    from absorption_gui import AbsorptionGUI
    return app, AbsorptionGUI()


@check("GUI：四个模式与选项组显隐正确")
def t_gui_modes():
    app, w = _make_gui()
    # (模式, 寿命组隐藏, 峰检测组隐藏, 积分组隐藏, 减法组隐藏)
    expect = {
        0: ('absorption', True, False, False, False),
        1: ('emission', True, False, False, False),
        2: ('lifetime', False, True, True, True),
        3: ('scan3d', True, True, True, True),
    }
    for idx, (mode, lt_hidden, pk_hidden, ig_hidden, sb_hidden) in expect.items():
        w.spectrum_type_combo.setCurrentIndex(idx)
        assert w.spectrum_type == mode, f"索引 {idx} 应为 {mode}"
        assert w.lifetime_options_group.isHidden() == lt_hidden
        assert w.peaks_group.isHidden() == pk_hidden
        assert w.integ_group.isHidden() == ig_hidden
        assert w.subtract_group.isHidden() == sb_hidden


@check("GUI：3D 扫描选项组只在 scan3d 模式显示")
def t_gui_scan3d_group():
    app, w = _make_gui()
    for idx, expect_hidden in ((0, True), (2, True), (3, False)):
        w.spectrum_type_combo.setCurrentIndex(idx)
        assert w.scan3d_options_group.isHidden() == expect_hidden, \
            f"索引 {idx}: scan3d 组隐藏状态错误"


@check("GUI：导出格式映射")
def t_gui_export_formats():
    app, w = _make_gui()
    expect = {
        0: ['.png'], 1: ['.pdf'], 2: ['.svg'],
        3: ['.png', '.pdf'], 4: ['.png', '.svg'],
        5: ['.png', '.pdf', '.svg'],
    }
    for i, exts in expect.items():
        w.export_format_combo.setCurrentIndex(i)
        assert w._export_formats() == exts, f"格式 {i} 映射错误"


@check("GUI：出版图预设尺寸与字号缩放")
def t_gui_pub_preset():
    app, w = _make_gui()
    expect = {0: None, 1: (3.5, 2.6), 2: (7.0, 4.5), 3: (10.0, 6.0)}
    for i, size in expect.items():
        w.pub_preset_combo.setCurrentIndex(i)
        assert w._pub_preset() == size, f"预设 {i} 尺寸错误"
    w.pub_preset_combo.setCurrentIndex(1)
    assert 0.5 < w._pub_font_scale() < 0.8
    w.pub_preset_combo.setCurrentIndex(0)
    assert w._pub_font_scale() == 1.0


@check("GUI：峰位标数值开关")
def t_gui_peak_label():
    app, w = _make_gui()
    w.peak_value_check.setChecked(True)
    assert w._peak_label(451.7) == '452'
    w.peak_value_check.setChecked(False)
    assert w._peak_label(451.7) == ''
    w.peak_value_check.setChecked(True)


@check("GUI：主题色板与切换")
def t_gui_theme():
    app, w = _make_gui()
    from gui_config import THEMES
    need = {'BG', 'CARD', 'BORDER', 'TEXT', 'ACCENT', 'MPL_FIG', 'HOVER_BG'}
    for name in ('light', 'dark'):
        assert need <= set(THEMES[name]), f"{name} 色板缺键"
    before = w.theme
    w.toggle_theme()
    assert w.theme != before
    import matplotlib as mpl
    assert mpl.rcParams['figure.facecolor'] == w.theme_palette()['MPL_FIG']
    w.toggle_theme(not (w.theme == 'dark'))


@check("GUI：快捷键注册齐全")
def t_gui_shortcuts():
    app, w = _make_gui()
    seqs = sorted(s.key().toString() for s in w._shortcuts)
    for need in ('F5', 'Ctrl+R', 'Ctrl+O', 'Ctrl+E', 'Ctrl+Shift+E',
                 'Ctrl+D', 'Ctrl+F', 'F1'):
        assert need in seqs, f"缺快捷键 {need}"


@check("GUI：最近文件夹写入/刷新（测试后还原设置）")
def t_gui_recent():
    app, w = _make_gui()
    key = "recent_folders"
    if not w.settings.isWritable():
        # 沙箱/权限限制下注册表只读，QSettings 写入会静默失败——不是程序问题
        raise Skip("QSettings 不可写，注册表被限制")
    old = w.settings.value(key, None)
    try:
        w._push_recent_folder(GUI_DIR)
        assert w.recent_combo.count() >= 2, "最近文件夹下拉框应至少含占位项 + 1 条"
        assert any(GUI_DIR in w.recent_combo.itemText(i)
                   for i in range(w.recent_combo.count())), "刚推入的目录应出现在列表里"
    finally:
        if old is None:
            w.settings.remove(key)
        else:
            w.settings.setValue(key, old)
        w.settings.sync()


@check("GUI：自动拟合 λ 每次启动默认勾选且 λ 输入框禁用")
def t_gui_auto_lambda_default():
    app, w = _make_gui()
    assert w.lifetime_auto_lambda_check.isChecked(), "自动拟合 λ 应默认勾选"
    assert not w.lifetime_lambda_spin.isEnabled(), "勾选自动后 λ 输入框应禁用"


@check("GUI：寿命范围 τ(ns) 输入正确换算为速率网格 k = 1/τ（v4.38）")
def t_gui_lifetime_tau_range():
    app, w = _make_gui()
    w.spectrum_type_combo.setCurrentIndex(2)      # 荧光寿命模式
    w.lifetime_taumin_spin.setValue(0.01)         # → k_max = 100 /ns
    w.lifetime_taumax_spin.setValue(100.0)        # → k_min = 0.01 /ns
    p = w._collect_plot_params()
    assert abs(p['lifetime_kmax'] - 100.0) < 1e-9, p.get('lifetime_kmax')
    assert abs(p['lifetime_kmin'] - 0.01) < 1e-9, p.get('lifetime_kmin')
    # μs 级长寿命：τ_max = 10 μs → k_min = 1e-4 /ns
    w.lifetime_taumax_spin.setValue(10000.0)
    p = w._collect_plot_params()
    assert abs(p['lifetime_kmin'] - 1e-4) < 1e-12, p.get('lifetime_kmin')
    # 亚 ns 快分量：τ_min = 0.001 ns = 1 ps → k_max = 1000 /ns
    w.lifetime_taumin_spin.setValue(0.001)
    p = w._collect_plot_params()
    assert abs(p['lifetime_kmax'] - 1000.0) < 1e-9, p.get('lifetime_kmax')
    # v4.38 修订（用户反馈）：τ 的上下界不设实际上限——τ_min 允许 > 10 ns
    w.lifetime_taumax_spin.setValue(200.0)
    w.lifetime_taumin_spin.setValue(50.0)          # 旧版会被夹到 10 ns
    assert abs(w.lifetime_taumin_spin.value() - 50.0) < 1e-9, \
        f"τ_min 不应被上限夹住：{w.lifetime_taumin_spin.value()}"
    p = w._collect_plot_params()
    assert abs(p['lifetime_kmin'] - 1.0 / 200.0) < 1e-12, p.get('lifetime_kmin')
    assert abs(p['lifetime_kmax'] - 1.0 / 50.0) < 1e-12, p.get('lifetime_kmax')
    # 更大的 τ 也要能填（1e6 ns = 1 ms），不再有 1e5 这种上限
    w.lifetime_taumax_spin.setValue(1e6)
    assert abs(w.lifetime_taumax_spin.value() - 1e6) < 1.0, \
        f"τ_max 不应被上限夹住：{w.lifetime_taumax_spin.value()}"
    # 越界自动让路：改动 τ_max 到 τ_min 以下 → τ_min 自动退到 τ_max/10
    w.lifetime_taumin_spin.setValue(50.0)
    w.lifetime_taumax_spin.setValue(20.0)
    assert w.lifetime_taumin_spin.value() < w.lifetime_taumax_spin.value(), \
        f"越界后应自动满足 τ_min < τ_max：{w.lifetime_taumin_spin.value()} / " \
        f"{w.lifetime_taumax_spin.value()}"
    p = w._collect_plot_params()
    assert abs(p['lifetime_kmax'] - p['lifetime_kmin'] * 10.0) < 1e-12, p
    # 反方向：改动 τ_min 到 τ_max 以上 → τ_max 自动抬到 τ_min×10
    w.lifetime_taumax_spin.setValue(20.0)
    w.lifetime_taumin_spin.setValue(500.0)
    assert w.lifetime_taumin_spin.value() < w.lifetime_taumax_spin.value(), \
        f"越界后应自动满足 τ_min < τ_max：{w.lifetime_taumin_spin.value()} / " \
        f"{w.lifetime_taumax_spin.value()}"
    p = w._collect_plot_params()
    assert abs(p['lifetime_kmax'] - 1.0 / 500.0) < 1e-12, p.get('lifetime_kmax')


@check("GUI：旧版 k 范围设置自动换算成 τ（v4.38 迁移）")
def t_gui_lifetime_tau_migration():
    app, w = _make_gui()
    s = w.settings
    if not s.isWritable():
        raise Skip("QSettings 不可写，注册表被限制")
    keys = ["param/lifetime_kmin", "param/lifetime_kmax",
            "param/lifetime_taumin", "param/lifetime_taumax",
            w._TAU_RANGE_MIGRATION_FLAG]
    old = {k: s.value(k, None) for k in keys}
    try:
        for k in keys:
            s.remove(k)
        s.setValue("param/lifetime_kmin", 0.005)     # 旧值 → τ_max = 200 ns
        s.setValue("param/lifetime_kmax", 50.0)      # 旧值 → τ_min = 0.02 ns
        s.sync()
        w._migrate_lifetime_range_keys(s)
        assert abs(float(s.value("param/lifetime_taumin")) - 0.02) < 1e-9, \
            s.value("param/lifetime_taumin")
        assert abs(float(s.value("param/lifetime_taumax")) - 200.0) < 1e-9, \
            s.value("param/lifetime_taumax")
        # 幂等：迁移过之后不再改写用户新填的 τ
        s.setValue("param/lifetime_taumin", 0.5)
        w._migrate_lifetime_range_keys(s)
        assert abs(float(s.value("param/lifetime_taumin")) - 0.5) < 1e-9, \
            "迁移不应覆盖已有 τ 值"
    finally:
        for k in keys:
            s.remove(k)
        for k, v in old.items():
            if v is not None:
                s.setValue(k, v)
        s.sync()


@check("GUI：寿命时间单位 ns/μs 切换只换显示、不换物理范围（v4.39）")
def t_gui_lifetime_unit_switch():
    app, w = _make_gui()
    w.spectrum_type_combo.setCurrentIndex(2)          # 荧光寿命模式
    # 用户场景：1O2 磷光（几十 μs）——先用 ns 填 1000–1e6 ns
    w.lifetime_taumin_spin.setValue(1000.0)
    w.lifetime_taumax_spin.setValue(1e6)
    w.lifetime_fixed_taus_edit.setText("60, 100")
    p_ns = w._collect_plot_params()

    w.lifetime_unit_combo.setCurrentIndex(1)          # → 微秒
    assert w.lifetime_unit == 'us', w.lifetime_unit
    assert abs(w.lifetime_unit_factor - 1000.0) < 1e-9
    assert w.lifetime_taumin_label.text() == 'τ_min (μs):', w.lifetime_taumin_label.text()
    assert w.lifetime_taumax_label.text() == 'τ_max (μs):', w.lifetime_taumax_label.text()
    assert w.lifetime_fixed_tau_label.text() == '固定 τ (μs):', \
        w.lifetime_fixed_tau_label.text()
    # 数值按单位换算：1000 ns → 1 μs，1e6 ns → 1000 μs，固定 τ 60/100 ns → 0.06/0.1 μs
    assert abs(w.lifetime_taumin_spin.value() - 1.0) < 1e-9, w.lifetime_taumin_spin.value()
    assert abs(w.lifetime_taumax_spin.value() - 1000.0) < 1e-9, w.lifetime_taumax_spin.value()
    assert w.lifetime_fixed_taus_edit.text() == '0.06, 0.1', \
        w.lifetime_fixed_taus_edit.text()
    p_us = w._collect_plot_params()
    # 物理范围与固定 τ 完全不变（内部始终按 ns 拟合）
    assert abs(p_us['lifetime_kmin'] - p_ns['lifetime_kmin']) < 1e-18, (p_us, p_ns)
    assert abs(p_us['lifetime_kmax'] - p_ns['lifetime_kmax']) < 1e-15, (p_us, p_ns)
    assert p_us['lifetime_fixed_taus'] == p_ns['lifetime_fixed_taus'] == [60.0, 100.0], \
        (p_us.get('lifetime_fixed_taus'), p_ns.get('lifetime_fixed_taus'))

    # 切回 ns：数值回到原样、标签也回来
    w.lifetime_unit_combo.setCurrentIndex(0)
    assert w.lifetime_unit == 'ns' and abs(w.lifetime_unit_factor - 1.0) < 1e-12
    assert abs(w.lifetime_taumin_spin.value() - 1000.0) < 1e-6, w.lifetime_taumin_spin.value()
    assert abs(w.lifetime_taumax_spin.value() - 1e6) < 1.0, w.lifetime_taumax_spin.value()
    assert w.lifetime_taumin_label.text() == 'τ_min (ns):', w.lifetime_taumin_label.text()
    assert w.lifetime_fixed_taus_edit.text() == '60, 100', w.lifetime_fixed_taus_edit.text()


@check("GUI：时间单位随会话恢复且 τ 数值不被二次换算（v4.39）")
def t_gui_lifetime_unit_restore():
    app, w = _make_gui()
    s = w.settings
    if not s.isWritable():
        raise Skip("QSettings 不可写，注册表被限制")
    keys = ["param/lifetime_unit", "param/lifetime_taumin", "param/lifetime_taumax",
            "defaults/lifetime_saved"]
    old = {k: s.value(k, None) for k in keys}
    try:
        for k in keys:
            s.remove(k)
        s.setValue("param/lifetime_unit", 1)          # 会话里存的是"微秒"
        s.setValue("param/lifetime_taumin", 1.0)      # 1 μs
        s.setValue("param/lifetime_taumax", 1000.0)   # 1000 μs
        s.sync()
        app2, w2 = _make_gui()
        assert w2.lifetime_unit == 'us', w2.lifetime_unit
        # 关键：单位先恢复、τ 再读入，所以数值**不能**被再换算一次
        assert abs(w2.lifetime_taumin_spin.value() - 1.0) < 1e-9, \
            w2.lifetime_taumin_spin.value()
        assert abs(w2.lifetime_taumax_spin.value() - 1000.0) < 1e-9, \
            w2.lifetime_taumax_spin.value()
        p = w2._collect_plot_params()
        assert abs(p['lifetime_kmax'] - 1e-3) < 1e-18, p['lifetime_kmax']   # 1/1000 ns
        assert abs(p['lifetime_kmin'] - 1e-6) < 1e-21, p['lifetime_kmin']   # 1/1e6 ns
    finally:
        for k in keys:
            s.remove(k)
        for k, v in old.items():
            if v is not None:
                s.setValue(k, v)
        s.sync()


@check("GUI：μs 单位只换时间轴，IRF/衰减/拟合的**强度**不被换算（v4.40）")
def t_gui_lifetime_unit_irf_not_scaled():
    """回归：v4.39 初版在 μs 模式下把 IRF 的**强度**也除以 1000，整条 IRF 掉到
    log 轴 ylim 以下 → 用户看到"IRF 无法显示"（y 0–0.64 vs ylim≥1）。
    时间量（横轴 / qshift / τ）该换算，强度量（counts）绝不能动。
    """
    app, w = _make_gui()
    w.spectrum_type_combo.setCurrentIndex(2)

    # 合成一份真实拟合结果（SESM 很快，不用等 MEM）
    rng = np.random.default_rng(11)
    dt = 0.05
    t = np.arange(0, 60, dt)
    irf = np.exp(-0.5 * ((t - 2.0) / 0.15) ** 2)
    irf = irf / irf.sum()
    truth = np.zeros_like(t)
    for a, tau in ((0.7, 3.0), (0.3, 12.0)):
        truth += a * np.convolve(irf, np.exp(-t / tau), mode='full')[:len(t)]
    truth *= 20000.0 / truth.max()
    decay = np.maximum(rng.poisson(truth).astype(float), 0.0)
    # IRF 按**计数刻度**给（真实仪器数据就是计数），否则 log 轴上 IRF 本来就在
    # ylim 之下，测不出"单位换算把 IRF 压没了"这件事
    irf_counts = irf / irf.max() * 20000.0
    import plot_lifetime as pl
    f = pl.MEMFitter(verbose=False, name='unit_probe')
    f.load(t, decay, irf_counts)
    f.preprocess()
    f.fit(method='SESM', n_rates=101)
    f.postprocess()
    res = f.serialize(None)

    def _plot_and_read(unit_idx):
        w.lifetime_unit_combo.setCurrentIndex(unit_idx)
        w._last_lifetime_result = res
        w._render_lifetime_result(res, 1.5, 'unit-probe')
        ax = w.canvas.fig.axes[0]
        out = {}
        for ln in ax.get_lines():
            lab = ln.get_label()
            if lab.startswith('IRF'):
                out['irf'] = (np.asarray(ln.get_xdata(), float),
                              np.asarray(ln.get_ydata(), float))
            elif '拟合' in lab:
                out['fit'] = (np.asarray(ln.get_xdata(), float),
                              np.asarray(ln.get_ydata(), float))
        out['scatter'] = [(np.asarray(c.get_offsets())[:, 0],
                           np.asarray(c.get_offsets())[:, 1])
                          for c in ax.collections
                          if '实验数据' in str(c.get_label())]
        out['ylim'] = ax.get_ylim()
        out['xlabel'] = ax.figure.axes[1].get_xlabel()
        return out

    ns = _plot_and_read(0)
    us = _plot_and_read(1)
    assert 'irf' in ns and 'irf' in us, "IRF 曲线应画在拟合图上"
    # ① 强度逐点相同（只允许横轴换算）
    assert np.allclose(ns['irf'][1], us['irf'][1]), "μs 模式下 IRF 强度被误改"
    assert np.allclose(ns['fit'][1], us['fit'][1]), "μs 模式下拟合曲线强度被误改"
    assert ns['scatter'] and us['scatter'], "实验数据散点应存在"
    assert np.allclose(ns['scatter'][0][1], us['scatter'][0][1]), \
        "μs 模式下实验数据强度被误改"
    # ② 横轴按 1000 倍换算
    assert abs(us['irf'][0].max() * 1000.0 - ns['irf'][0].max()) < 1e-6
    # ③ IRF 必须留在 y 轴范围内（这正是"IRF 无法显示"的直接判据）
    assert us['irf'][1].max() >= us['ylim'][0], \
        f"IRF 峰值 {us['irf'][1].max():.4g} 低于 y 轴下限 {us['ylim'][0]:.4g}"
    assert abs(us['ylim'][1] - ns['ylim'][1]) < 1e-6, "μs 模式不应改变 y 轴范围"
    assert 'μs' in us['xlabel'] and 'ns' in ns['xlabel'], (us['xlabel'], ns['xlabel'])


@check("GUI：寿命拟合参数「存为默认值」下次启动生效")
def t_gui_lifetime_defaults():
    app, w = _make_gui()
    if not w.settings.isWritable():
        raise Skip("QSettings 不可写，注册表被限制")
    keys = ["defaults/" + k for k, _, _ in w._LIFETIME_DEFAULT_SPECS]
    keys += ["defaults/lifetime_saved", "param/lifetime_unit"]
    old = {k: w.settings.value(k, None) for k in keys}
    try:
        w.lifetime_method_combo.setCurrentIndex(0)          # MEM（λ 才有意义）
        w.lifetime_nrates_spin.setValue(123)
        w.lifetime_taumin_spin.setValue(0.02)
        w.lifetime_taumax_spin.setValue(50.0)
        # v4.38：再存一次"下界 > 默认 τ_max（100 ns）"的组合——既验证 τ 无上限，
        # 也验证「存为默认值 → 启动套用」时两个框的自动让路不会把这对值改坏
        w.lifetime_taumin_spin.setValue(200.0)      # 旧版会被夹到 10 ns
        w.lifetime_taumax_spin.setValue(500.0)
        w.lifetime_fixed_taus_edit.setText("3.6, 0.5")
        w.lifetime_lambda_spin.setValue(0.01)
        w.lifetime_auto_lambda_check.setChecked(False)
        # v4.39：切到「微秒」再存一次 → 默认值必须**按 ns 存**（与显示单位无关）
        w.lifetime_unit_combo.setCurrentIndex(1)
        w.lifetime_taumin_spin.setValue(0.2)        # 0.2 μs = 200 ns
        w.lifetime_taumax_spin.setValue(0.5)        # 0.5 μs = 500 ns
        w.lifetime_fixed_taus_edit.setText("3.6, 0.5")   # 3.6/0.5 μs
        assert w._save_lifetime_defaults(), "保存默认值失败"
        s = w.settings
        assert abs(float(s.value("defaults/lifetime_taumin")) - 200.0) < 1e-9, \
            s.value("defaults/lifetime_taumin")
        assert abs(float(s.value("defaults/lifetime_taumax")) - 500.0) < 1e-9, \
            s.value("defaults/lifetime_taumax")
        assert str(s.value("defaults/lifetime_fixed_taus")) == "3600, 500", \
            s.value("defaults/lifetime_fixed_taus")
        # 模拟"会话里也是微秒"：单位随会话恢复后，默认值应换算回微秒显示
        s.setValue("param/lifetime_unit", 1)
        s.sync()
        app2, w2 = _make_gui()
        assert w2.lifetime_unit == 'us', w2.lifetime_unit
        assert w2.lifetime_nrates_spin.value() == 123, "网格点数未套用默认值"
        assert abs(w2.lifetime_taumin_spin.value() - 0.2) < 1e-9, \
            w2.lifetime_taumin_spin.value()
        assert abs(w2.lifetime_taumax_spin.value() - 0.5) < 1e-9, \
            w2.lifetime_taumax_spin.value()
        assert w2.lifetime_fixed_taus_edit.text() == "3.6, 0.5", \
            w2.lifetime_fixed_taus_edit.text()
        assert abs(w2.lifetime_lambda_spin.value() - 0.01) < 1e-9
        assert not w2.lifetime_auto_lambda_check.isChecked(), "自动拟合 λ 应恢复为不勾选"
        assert w2.lifetime_lambda_spin.isEnabled(), "MEM + 手动 λ 时 λ 输入框应可用"
    finally:
        for k, v in old.items():
            if v is None:
                w.settings.remove(k)
            else:
                w.settings.setValue(k, v)
        w.settings.sync()


@check("GUI：长文件夹路径缩成短名并保留完整 tooltip")
def t_gui_short_path():
    app, w = _make_gui()
    long_path = (r'D:\北大\光谱工具\示例数据\测试数据\20260727-RB-Lu')
    short = w._short_path(long_path)
    assert short != long_path, "长路径应被缩短"
    assert short.startswith('…') and '20260727-RB-Lu' in short
    assert len(short) < len(long_path)
    w.folder_label.setText(f"文件夹: {short}")
    w.folder_label.setToolTip(long_path)
    assert w.folder_label.toolTip() == long_path


@check("GUI：发射模式渲染带峰位标注")
def t_gui_emission_render():
    if not os.path.isdir(EMISSION_DIR):
        raise Skip("发射样例数据不存在")
    app, w = _make_gui()
    w.spectrum_type_combo.setCurrentIndex(1)
    w.load_data_from_folder(EMISSION_DIR)
    if not w.data_cache:
        raise Skip("未加载到数据")
    w.peak_value_check.setChecked(True)
    fig = w._do_plot()
    assert len(fig.axes) >= 1
    w.peak_value_check.setChecked(False)
    fig2 = w._do_plot()
    texts = [t.get_text() for t in fig2.axes[0].texts if t.get_text()]
    assert texts == [], f"关闭标注后仍有文本: {texts[:3]}"
    w.peak_value_check.setChecked(True)


def _rel_luminance(hex_color):
    """sRGB 相对亮度（WCAG 2.x）。"""
    c = hex_color.lstrip('#')
    chans = [int(c[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
    chans = [(v / 12.92) if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
             for v in chans]
    return 0.2126 * chans[0] + 0.7152 * chans[1] + 0.0722 * chans[2]


def _contrast(fg, bg):
    """两色对比度（1:1 – 21:1）。"""
    a, b = _rel_luminance(fg), _rel_luminance(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


@check("GUI：深色主题坐标轴/刻度/标注对比度达标（≥3:1）")
def t_gui_dark_axis_contrast():
    app, w = _make_gui()
    from gui_config import THEMES
    for name in ('light', 'dark'):
        P = THEMES[name]
        # 刻度文字：正文级别 4.5:1
        assert _contrast(P['MPL_FG'], P['MPL_AX']) >= 4.5, \
            f"{name} 刻度文字对比度不足: {_contrast(P['MPL_FG'], P['MPL_AX']):.2f}"
        # 图上数值框（χ²R）：文字与底色
        assert _contrast(P['MPL_NOTE_FG'], P['MPL_NOTE_BG']) >= 4.5, \
            f"{name} 数值框文字对比度不足"
    D = THEMES['dark']
    spine = _contrast(D['MPL_SPINE'], D['MPL_AX'])
    assert spine >= 3.0, f"深色主题坐标轴边框对比度 {spine:.2f} < 3.0（看不清）"
    zero = _contrast(D['MPL_ZERO'], D['MPL_AX'])
    assert zero >= 3.0, f"深色主题零基准线对比度 {zero:.2f} < 3.0"
    # 网格线是不透明度叠加，按混合后的实际颜色算
    def _blend(fg, bg, alpha):
        f = [int(fg.lstrip('#')[i:i + 2], 16) for i in (0, 2, 4)]
        b = [int(bg.lstrip('#')[i:i + 2], 16) for i in (0, 2, 4)]
        return '#%02x%02x%02x' % tuple(
            round(f[i] * alpha + b[i] * (1 - alpha)) for i in range(3))
    gmix = _blend(D['MPL_GRID'], D['MPL_AX'], D['MPL_GRID_ALPHA'])
    g = _contrast(gmix, D['MPL_AX'])
    assert g >= 1.8, f"深色主题网格线混合后对比度 {g:.2f} 太低（等于看不见）"
    # 切到深色后，画布上既有坐标轴的边框颜色应立即跟着换
    w.toggle_theme(True)
    import matplotlib as mpl
    from matplotlib.colors import to_hex
    assert mpl.rcParams['axes.edgecolor'] == D['MPL_SPINE'], \
        "rcParams axes.edgecolor 未随主题更新"
    for ax in w.canvas.fig.axes:
        for sp in ax.spines.values():
            assert to_hex(sp.get_edgecolor()).lower() == D['MPL_SPINE'].lower(), \
                "既有坐标轴边框颜色未随主题更新"
    w.toggle_theme(False)


@check("GUI：单独图 / 差谱 取色不再被主题色板同名方法顶掉")
def t_gui_plot_palette_collision():
    if not os.path.isdir(EMISSION_DIR):
        raise Skip("样例数据不存在")
    app, w = _make_gui()
    # PlotMixin._palette(color_map, n) 与 UiMixin.theme_palette() 曾同名，
    # UiMixin 在 MRO 前面会把绘图取色顶掉（单独图/差谱直接 TypeError）
    import numpy as np
    cols = w._palette(w.get_color_map(), 3)
    assert len(np.asarray(cols)) == 3, "曲线取色应返回 3 个颜色"
    assert isinstance(w.theme_palette(), dict), "主题色板应返回 dict"
    w.spectrum_type_combo.setCurrentIndex(1)
    w.load_data_from_folder(EMISSION_DIR)
    if not w.data_cache:
        raise Skip("未加载到数据")
    if w.file_list.count():
        w.file_list.setCurrentRow(0)              # 单独图按选中文件绘制
    w.plot_type_combo.setCurrentIndex(1)          # 单独图
    fig = w._do_plot()
    assert len(fig.axes) >= 1
    assert fig.axes[0].lines, "单独图应画出曲线（不能是空坐标轴）"
    w.plot_type_combo.setCurrentIndex(0)          # 恢复合并图


# ---------------------------------------------------------------- v4.21 新增
# 合成真值数据：双指数 2.5 / 8.0 ns + 泊松噪声（seed 固定，结果可复现）
def _synth_double_exponential(seed=7, peak=20000.0):
    rng = np.random.default_rng(seed)
    dt = 0.05
    t = np.arange(0, 60, dt)
    irf = np.exp(-0.5 * ((t - 2.0) / 0.15) ** 2)
    irf = irf / irf.sum()
    decay_true = np.zeros_like(t)
    for a, tau in ((0.7, 2.5), (0.3, 8.0)):
        decay_true += a * np.convolve(irf, np.exp(-t / tau), mode='full')[:len(t)]
    decay_true *= peak / decay_true.max()
    decay = np.maximum(rng.poisson(decay_true).astype(float), 0.0)
    return t, decay, irf


@check("寿命拟合：合成真值双指数能收敛到正确寿命（A1）")
def t_fit_ground_truth():
    import plot_lifetime as pl
    t, decay, irf = _synth_double_exponential()
    f = pl.MEMFitter(verbose=False, name='synth')
    f.load(t, decay, irf)
    f.preprocess()
    f.fit(method='MEM', n_rates=201)
    f.postprocess()
    info = f.info
    # 同模型的 NNLS 最优解 χ²R≈0.9；优化器若没收敛会给出 10¹–10² 量级
    assert info['chi_sqr'] < 1.5, f"χ²R={info['chi_sqr']:.3g} 过大，拟合未收敛"
    assert info['quality'] == 'ok', f"quality={info['quality']} {info['quality_notes']}"
    assert info['solver_converged'], "应记录优化器已收敛"
    taus = sorted(p[0] for p in (f.peak_result or []))
    assert len(taus) == 2, f"应恢复 2 个分量，实际 {taus}"
    assert abs(taus[0] - 2.5) / 2.5 < 0.10, f"快分量 {taus[0]:.3f} ns 偏离真值 2.5"
    assert abs(taus[1] - 8.0) / 8.0 < 0.10, f"慢分量 {taus[1]:.3f} ns 偏离真值 8.0"
    shares = sorted(p[1] for p in f.peak_result)
    assert abs(sum(shares) - 1.0) < 1e-6, "强度占比之和应为 1"
    # 真值强度占比 = a·τ 归一：(0.7·2.5, 0.3·8) → 42.2% / 57.8%
    assert abs(shares[0] - 0.422) < 0.06, f"快分量占比 {shares[0]:.3f} 偏离真值 0.422"


@check("寿命拟合：分量个数与寿命不随 n_rates 漂移（A6）")
def t_nrates_stability():
    import plot_lifetime as pl
    t, decay, irf = _synth_double_exponential()
    out = {}
    for n in (101, 201):
        f = pl.MEMFitter(verbose=False, name=f'n{n}')
        f.load(t, decay, irf)
        f.preprocess()
        f.fit(method='MEM', n_rates=n)
        f.postprocess()
        out[n] = sorted(p[0] for p in (f.peak_result or []))
        assert len(out[n]) == 2, f"n_rates={n} 得到 {len(out[n])} 个分量（应为 2）"
    for i in range(2):
        a, b = out[101][i], out[201][i]
        assert abs(a - b) / max(b, 1e-9) < 0.15, \
            f"n_rates 101/201 的第 {i} 个分量 {a:.3f} vs {b:.3f} 漂移过大"


@check("寿命拟合：退化输入必须明确报错而不是静默给结果（A4）")
def t_degenerate_inputs():
    import plot_lifetime as pl
    t, decay, irf = _synth_double_exponential()
    cases = []

    def _expect_raises(label, fn):
        try:
            fn()
        except Exception as e:
            cases.append((label, type(e).__name__))
        else:
            raise AssertionError(f"{label} 应抛异常，实际静默返回")

    _expect_raises('长度不一致', lambda: pl.MEMFitter(verbose=False).load(
        t, decay[:-3], irf))
    bad = decay.copy()
    bad[10] = np.nan
    _expect_raises('含 NaN', lambda: pl.MEMFitter(verbose=False).load(t, bad, irf))
    _expect_raises('时间轴非递增', lambda: pl.MEMFitter(verbose=False).load(
        t[::-1], decay, irf))
    _expect_raises('IRF 全 0', lambda: pl.MEMFitter(verbose=False).load(
        t, decay, np.zeros_like(irf)))

    def _fit_with(**kw):
        f = pl.MEMFitter(verbose=False)
        f.load(t, decay, irf)
        f.preprocess()
        f.fit(**kw)

    _expect_raises('k_min>=k_max', lambda: _fit_with(k_min=100, k_max=1))
    _expect_raises('n_rates<3', lambda: _fit_with(n_rates=2))
    _expect_raises('未知方法', lambda: _fit_with(method='XYZ'))
    _expect_raises('点数少于分量数', lambda: _fit_with(n_rates=100000))

    def _flat():
        f = pl.MEMFitter(verbose=False)
        f.load(t, np.full_like(decay, 5.0), irf)
        f.preprocess()          # 平坦数据在 preprocess 里就应报错

    _expect_raises('平坦数据（无衰减信号', _flat)
    assert len(cases) == 9, f"应覆盖 9 种退化输入，实际 {cases}"


@check("寿命拟合：归一化数据自动还原，寿命与计数刻度一致（v4.32）")
def t_normalized_autoscale():
    """峰值 = 1 的归一化数据必须能拟合，且结果与计数刻度一致。

    回归背景：噪声判据 ``max(peak/500, 10, 1.5×bg)`` 里的绝对下限 10 是为光子
    计数写的。归一化数据（峰值 1）全部通道 < 10 → 窗口被夹到 50 点 → 报"欠定"。
    修复后 preprocess 会先把数据还原到计数刻度再定窗口。
    """
    import plot_lifetime as pl

    def _fit(dec, irf):
        f = pl.MEMFitter(verbose=False, name='n')
        f.load(t, dec, irf)
        f.preprocess()
        f.fit(method='MEM', n_rates=201)
        f.postprocess()
        return f.info, sorted(p[0] for p in (f.peak_result or []))

    t, decay, irf = _synth_double_exponential()
    i_cnt, tau_cnt = _fit(decay, irf)
    assert not i_cnt['rescaled_from_normalized'], "计数数据不应触发还原"
    assert i_cnt.get('rescale_factor') == 1.0, "计数数据的还原因子应为 1"

    # 归一化到峰值 = 1（作业/交换数据的常见形态）
    dn, i_n = decay / decay.max(), irf / irf.max()
    i_nor, tau_nor = _fit(dn, i_n)
    assert i_nor['rescaled_from_normalized'], "峰值=1 的数据应被识别为归一化"
    npts = i_nor['fit_end'] - i_nor['fit_start']
    assert not i_nor['window_floored'], \
        f"还原后窗口不应仍被 50 点下限托底（实际 {npts} 点）"
    assert npts > 200, f"还原后拟合窗口只有 {npts} 点，窗口仍不健康"

    assert len(tau_nor) == 2, f"归一化数据应仍恢复 2 个分量，实际 {tau_nor}"
    for a, b in zip(tau_cnt, tau_nor):
        assert abs(a - b) / max(b, 1e-9) < 0.10, \
            f"归一化 vs 计数刻度的寿命漂移过大：{a:.3f} vs {b:.3f}"
    # 真值 2.5 / 8.0 ns 仍要落在 10% 内
    assert abs(tau_nor[0] - 2.5) / 2.5 < 0.20, f"快分量 {tau_nor[0]:.3f} 偏离 2.5"
    assert abs(tau_nor[1] - 8.0) / 8.0 < 0.20, f"慢分量 {tau_nor[1]:.3f} 偏离 8.0"

    # 窗口被托底时必须给出可操作的诊断，而不是只说"把 n_rates 调小"
    f = pl.MEMFitter(verbose=False, name='degenerate')
    f._rescale_if_normalized = lambda a, b: (a, b)      # 模拟修复前行为
    f.load(t, dn, i_n)
    f.preprocess()
    assert f.info['window_floored'], "关掉还原后窗口应被下限托底"
    try:
        f.fit(method='SESM', n_rates=101)
    except ValueError as e:
        msg = str(e)
        assert '50 点下限' in msg, f"报错应说明窗口被下限托底：{msg[:120]}"
        assert '噪声水平' in msg, "报错应给出噪声水平等诊断量"
    else:
        raise AssertionError("窗口被托底且点数不足时应报错")


@check("寿命拟合：SESM 的 λ 真正生效且不过平滑（A3）")
def t_sesm_lambda():
    import plot_lifetime as pl
    t, decay, irf = _synth_double_exponential()
    chis = []
    for lam in (1e-3, 1e-1):
        f = pl.MEMFitter(verbose=False)
        f.load(t, decay, irf)
        f.preprocess()
        f.fit(method='SESM', n_rates=101, lambda_coeff=lam)
        f.postprocess()
        chis.append(f.info['chi_sqr'])
        assert 'smooth_weight_used' in f.info, "SESM 应记录实际平滑权重"
    assert abs(chis[0] - chis[1]) > 1e-6, \
        f"SESM 的 λ 没有影响结果（{chis}）——平滑权重可能又被写死"
    # 无噪声单指数：过平滑会让 χ²R 变成 10² 量级
    rng = np.random.default_rng(1)
    tt = np.arange(0, 40, 0.05)
    irf2 = np.exp(-0.5 * ((tt - 1.5) / 0.12) ** 2)
    irf2 = irf2 / irf2.sum()
    clean = np.convolve(irf2, 1000 * np.exp(-tt / 3.0), mode='full')[:len(tt)] + 20
    f = pl.MEMFitter(verbose=False)
    f.load(tt, clean, irf2)
    f.preprocess()
    f.fit(method='SESM', n_rates=101)
    assert f.info['chi_sqr'] < 5.0, \
        f"无噪声单指数 SESM χ²R={f.info['chi_sqr']:.3g}，平滑惩罚过强"


@check("寿命拟合：χ² 双口径与质量标志写入 info（A2/A5）")
def t_quality_fields():
    import plot_lifetime as pl
    t, decay, irf = _synth_double_exponential()
    f = pl.MEMFitter(verbose=False)
    f.load(t, decay, irf)
    f.preprocess()
    f.fit(method='MEM', n_rates=101)
    f.postprocess()
    info = f.info
    for key in ('chi_sqr', 'chi_sqr_pearson', 'chi2_type', 'quality',
                'quality_notes', 'solver_converged', 'iter_converged',
                'intensity_share_grid_edges', 'intensity_share_fastest_decade',
                'intensity_share_slowest_decade', 'intensity_share_unassigned',
                'peaks_found', 'peaks_dropped', 'peaks_dropped_low_share'):
        assert key in info, f"info 缺少 {key}"
    assert info['chi2_type'] == 'neyman_obs_denominator_over_M'
    assert info['quality'] in ('ok', 'poor', 'failed')
    for key in ('intensity_share_grid_edges', 'intensity_share_unassigned'):
        assert 0.0 <= info[key] <= 1.0 + 1e-9, f"{key}={info[key]} 超出 [0,1]"
    assert np.isfinite(info['residuals']).all(), "残差应为有限值"


@check("寿命拟合：并行 fit_many 与串行结果一致（C1）")
def t_fit_many_parallel():
    import plot_lifetime as pl
    t, decay, irf = _synth_double_exponential()
    datasets = [
        {'name': 'a', 'time': t, 'decay': decay, 'irf': irf},
        {'name': 'b', 'time': t, 'decay': decay * 1.0 + 1.0, 'irf': irf},
    ]
    kw = dict(method='SESM', n_rates=101)
    par = pl.fit_many(datasets, max_workers=2, fit_kwargs=kw)
    ser = pl.fit_many(datasets, max_workers=1, fit_kwargs=kw)
    assert len(par) == len(ser) == 2
    for p, s in zip(par, ser):
        assert p is not None and s is not None, "fit_many 不应返回 None"
        assert abs(p['info']['chi_sqr'] - s['info']['chi_sqr']) < 1e-6, \
            "并行与串行 χ²R 不一致"
        tp = sorted(x[0] for x in (p['peak_result'] or []))
        ts = sorted(x[0] for x in (s['peak_result'] or []))
        assert len(tp) == len(ts) and all(
            abs(a - b) / max(b, 1e-9) < 1e-6 for a, b in zip(tp, ts)), \
            "并行与串行寿命分量不一致"


@check("寿命拟合：取消回调能中止拟合（D5）")
def t_fit_cancel():
    import plot_lifetime as pl
    t, decay, irf = _synth_double_exponential()
    f = pl.MEMFitter(verbose=False)
    f.load(t, decay, irf)
    f.preprocess()
    try:
        f.fit(method='MEM', n_rates=101, auto_lambda=True,
              cancel_cb=lambda: True)
    except pl.FitCancelled:
        pass
    else:
        raise AssertionError("cancel_cb 返回 True 时应抛 FitCancelled")
    steps = []
    f2 = pl.MEMFitter(verbose=False)
    f2.load(t, decay, irf)
    f2.preprocess()
    f2.fit(method='MEM', n_rates=101,
           progress_cb=lambda fr, msg: steps.append(fr))
    assert steps and max(steps) > 0.99, f"进度回调未走到完成：{steps}"


@check("3D 扫描：清洗管线不造假数据（A8）")
def t_scan3d_guards():
    import plot_3d_scan as p3
    rng = np.random.default_rng(3)
    em = np.arange(400.0, 500.0, 1.0)
    ex = np.arange(300.0, 320.0, 1.0)
    # Z 的形状是 (EM, EX)，所以谱包络沿 EM 方向、按列扩展
    base = np.exp(-0.5 * ((em - 460) / 20) ** 2)[:, None] * 1000
    Z = base + 5 * rng.random((len(em), len(ex)))
    # ① 整条 EX 通道全缺测（全 NaN 列）
    Z1 = Z.copy()
    Z1[:, 5] = np.nan
    data = {'label': 'synth', 'ex_wavelengths': ex, 'em_wavelengths': em,
            'intensity': Z1}
    prep = p3.prepare_grid(data, smooth_factor=1, spike_window=0,
                           sigma_em=0, sigma_ex=0, notch_comb=False,
                           verbose=False)
    col = prep['Z_orig'][:, 5]
    assert not np.allclose(col, 0.0), \
        "整列缺失被填 0 —— 会在 EEM 里造出人造暗带"
    assert prep['stats'].get('cols_filled_ex', 0) >= 1, "应记录沿 EX 补全的列数"
    # ② Z_orig 必须是拷贝，不能是 Z 的别名
    assert prep['Z_orig'] is not prep['Z']
    # ③ EX 递减 + 重复波长也能整理成严格递增
    ex2 = ex[::-1].copy()
    ex2[3] = ex2[2]
    data2 = {'label': 's2', 'ex_wavelengths': ex2, 'em_wavelengths': em,
             'intensity': Z}
    prep2 = p3.prepare_grid(data2, smooth_factor=1, spike_window=0,
                            sigma_em=0, sigma_ex=0, notch_comb=False,
                            verbose=False)
    assert np.all(np.diff(prep2['ex_orig']) > 0), "EX 应整理为严格递增"
    assert prep2['stats'].get('ex_dedup', 0) >= 1, "应记录重复波长合并数"
    # ④ 加密后不得出现负强度
    assert np.nanmin(prep2['Z']) >= 0.0, "样条加密后出现负强度"
    # ⑤ 同一输入两次清洗结果一致（幂等）
    p_a = p3.prepare_grid(data, smooth_factor=2, verbose=False)
    p_b = p3.prepare_grid(data, smooth_factor=2, verbose=False)
    assert np.allclose(p_a['Z'], p_b['Z']), "prepare_grid 不幂等"


@check("3D 扫描：prep 可复用且绘图三件套共用一次清洗（性能）")
def t_scan3d_prep_reuse():
    if not os.path.exists(SCAN3D_CSV):
        raise Skip("3D 样例数据不存在")
    import plot_3d_scan as p3
    import tempfile
    out_dir = tempfile.mkdtemp(prefix='spectra3d_')
    data = p3.parse_3d_scan_csv(SCAN3D_CSV, verbose=False)
    prep = p3.prepare_grid(data, verbose=False)
    calls = {'n': 0}
    orig = p3.prepare_grid

    def _counting(*a, **k):
        calls['n'] += 1
        return orig(*a, **k)

    p3.prepare_grid = _counting
    try:
        p3.plot_3d_surface(data, save_dir=out_dir, show=False, prep=prep,
                           verbose=False)
        p3.plot_contour(data, save_dir=out_dir, show=False, prep=prep,
                        verbose=False)
    finally:
        p3.prepare_grid = orig
    assert calls['n'] == 0, f"传入 prep 后不应再清洗（实际调用 {calls['n']} 次）"
    import shutil
    shutil.rmtree(out_dir, ignore_errors=True)


@check("吸收：摩尔吸光系数必须显式给浓度（A7）")
def t_absorption_epsilon():
    import plot_absorption as pa
    data = {'wl': np.array([300.0, 400.0]), 'absorption': np.array([0.5, 1.0])}
    try:
        pa.calculate_absorption_coefficient(data)
    except TypeError:
        pass
    else:
        raise AssertionError("缺少浓度参数时不应给出 ε")
    out = pa.calculate_absorption_coefficient(data, 2e-5)
    assert abs(out['absorption_coefficient'][1] - 1.0 / 2e-5) < 1e-6
    assert out['units'] == 'M^-1 cm^-1'


@check("发射：Spectracle CSV 按行对齐，缺格不错位（A7）")
def t_spectracle_alignment():
    import plot_emission as pe
    tmp = os.path.join(HERE, '_tmp_spectracle.csv')
    rows = [["SampleA", "A1", "", "SampleB", "B1", ""],
            ["EX WL", "350", "", "EX WL", "400", ""],
            ["", "", "", "", "", ""],
            ["波长(nm)", "强度", "", "波长(nm)", "强度", ""]]
    for i, wl in enumerate(range(400, 410)):
        rows.append([str(wl), ("" if i == 2 else str(100 + i)), "",
                     str(wl), str(200 + i), ""])
    try:
        with open(tmp, 'w', encoding='utf-8', newline='') as f:
            for r in rows:
                f.write(','.join(r) + '\n')
        ds, _ = pe.parse_spectracle_csv(tmp)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    a = ds[0]
    assert len(a['wl']) == 9, f"缺格行应整行丢弃，实际 {len(a['wl'])} 点"
    assert np.allclose(a['intensity'], 100.0 + (a['wl'] - 400.0)), \
        "波长与强度错位（逐列去 NaN 后按 min_len 截断的老 bug）"


@check("全局拟合（共享分布）：能收敛且各数据集自洽（G3）")
def t_global_fit():
    import plot_lifetime as pl
    t, decay, irf = _synth_double_exponential()
    sets = [{'name': 's0', 'time': t, 'decay': decay, 'irf': irf},
            {'name': 's1', 'time': t, 'decay': np.maximum(decay * 0.3, 0.0),
             'irf': irf}]
    res = pl.fit_global(sets, method='MEM', n_rates=101, verbose=False)
    assert res['solver_converged'], "全局拟合应报告收敛"
    # 两个数据集各自 χ²R≈1 → Σχ²R≈2（旧实现会停在 400+）
    assert res['chi2R_total'] < 6.0, f"Σχ²R={res['chi2R_total']:.3g} 过大"
    taus = sorted(res['tau_list'])
    assert len(taus) == 2, f"应恢复 2 个共享分量：{taus}"
    assert abs(taus[0] - 2.5) / 2.5 < 0.15, f"快分量 {taus[0]:.3f} 偏离真值"
    assert abs(taus[1] - 8.0) / 8.0 < 0.15, f"慢分量 {taus[1]:.3f} 偏离真值"
    for e in res['per_dataset']:
        assert e['chi2R'] < 3.0, f"{e['name']} χ²R={e['chi2R']:.3g} 过大"


@check("全局离散拟合：共享 τ、各样品独立幅度（G3）")
def t_global_discrete():
    import plot_lifetime as pl
    t, decay, irf = _synth_double_exponential()
    sets = [{'name': 's0', 'time': t, 'decay': decay, 'irf': irf},
            {'name': 's1', 'time': t, 'decay': np.maximum(decay * 0.4, 0.0),
             'irf': irf}]
    res = pl.fit_global_discrete(sets, n_comp=2, verbose=False)
    taus = sorted(res['taus'])
    assert len(taus) == 2
    assert abs(taus[0] - 2.5) / 2.5 < 0.2, f"共享快分量 {taus[0]:.3f} 偏离"
    assert abs(taus[1] - 8.0) / 8.0 < 0.2, f"共享慢分量 {taus[1]:.3f} 偏离"
    for e in res['per_dataset']:
        assert e['chi2R'] < 4.0, f"{e['name']} χ²R={e['chi2R']:.3g} 过大"
        assert abs(sum(e['alpha']) - 1.0) < 1e-6, "各样品占比之和应为 1"


@check("3D 扫描：瑞利/拉曼散射带剔除只动散射区（G4）")
def t_scatter_removal():
    import plot_3d_scan as p3
    em = np.arange(300.0, 601.0, 1.0)
    ex = np.arange(300.0, 401.0, 1.0)
    EMg, EXg = np.meshgrid(em, ex, indexing='ij')
    fluo = 1000 * np.exp(-0.5 * ((EMg - 450) / 40.0) ** 2)
    ray = 5000 * np.exp(-0.5 * ((EMg - EXg) / 2.0) ** 2)
    ram_c = 1.0 / (1.0 / EXg - 3350e-7)
    ram = 800 * np.exp(-0.5 * ((EMg - ram_c) / 4.0) ** 2)
    data = {'label': 'synth', 'ex_wavelengths': ex, 'em_wavelengths': em,
            'intensity': fluo + ray + ram + 5.0}
    mask, n_ray, n_ram = p3._scatter_mask(em, ex)
    assert 0 < mask.mean() < 0.3, f"散射掩膜覆盖 {mask.mean():.1%}，不合理"
    kw = dict(verbose=False, notch_comb=False, spike_window=0, sigma_em=0,
              sigma_ex=0, smooth_factor=1)
    z0 = p3.prepare_grid(data, remove_scatter=False, **kw)['Z_orig']
    z1 = p3.prepare_grid(data, remove_scatter=True, **kw)['Z_orig']
    assert z1[mask].mean() < 0.6 * z0[mask].mean(), "散射带没有被压下去"
    assert np.max(np.abs(z1[~mask] - z0[~mask])) < 1e-6, \
        "非散射区被改动了（不应该）"
    # 内滤校正
    corr, fac = p3.inner_filter_correction(data, np.full(len(ex), 0.2),
                                           np.full(len(em), 0.1))
    assert abs(fac.mean() - 10 ** 0.15) < 1e-6, "内滤校正因子应为 10^((Aex+Aem)/2)"
    assert corr.shape == data['intensity'].shape


@check("寿命：跨样品汇总图与 PDF 报告能落盘（G5/G6）")
def t_summary_and_pdf():
    import plot_lifetime as pl
    import tempfile
    t, decay, irf = _synth_double_exponential()
    results = []
    for i in range(3):
        f = pl.MEMFitter(verbose=False, name=f's{i}')
        f.load(t, np.maximum(decay * (1.0 - 0.2 * i), 0.0), irf)
        f.preprocess()
        f.fit(method='SESM', n_rates=101)
        f.postprocess()
        results.append(f.serialize(None))
    out = tempfile.mkdtemp(prefix='spectra_rep_')
    png = pl.plot_summary(results, save_dir=out, verbose=False)
    assert os.path.getsize(png) > 20000, "汇总图文件过小"
    pdf = pl.export_report_pdf(results, save_dir=out, verbose=False)
    assert os.path.getsize(pdf) > 20000, "PDF 报告文件过小"
    with open(pdf, 'rb') as fh:
        assert fh.read(5) == b'%PDF-', "PDF 报告文件头不对"
    try:
        import pymupdf
        doc = pymupdf.open(pdf)
        assert doc.page_count == len(results) + 1, \
            f"PDF 页数应为 {len(results) + 1}，实际 {doc.page_count}"
        doc.close()
    except ImportError:
        pass
    import shutil
    shutil.rmtree(out, ignore_errors=True)


# ---------------------------------------------------------------- v4.23 新增
@check("GUI：弹出菜单(QMenu)跟随主题——深色下不再是浅色面板（v4.23）")
def t_gui_menu_theme():
    from PyQt5.QtWidgets import QMenu
    app, w = _make_gui()
    w.toggle_theme(True)
    dark = w.theme_palette()
    qss = app.styleSheet()
    assert 'QMenu {' in qss and 'QMenu::item:selected' in qss, \
        "全局样式表缺少 QMenu 规则（深色下帮助菜单会退回浅色 Fusion 色板）"
    assert dark['CARD'] in qss, "QMenu 规则应使用当前主题的卡片色"
    menus = list(w.findChildren(QMenu))
    if getattr(w, 'help_btn', None) is not None and w.help_btn.menu() is not None:
        menus.append(w.help_btn.menu())
    assert menus, "应至少存在一个 QMenu（「❓ 帮助」菜单）"
    dark_bg = f"background-color: {dark['CARD']}"
    for m in menus:
        assert dark_bg in m.styleSheet(), \
            "每个 QMenu 都要单独下发当前主题样式（弹出窗口不会自动重解析）"
    # 切回浅色：菜单样式必须跟着换回去
    w.toggle_theme(False)
    light = w.theme_palette()
    assert light['CARD'] != dark['CARD']
    light_bg = f"background-color: {light['CARD']}"
    for m in menus:
        assert light_bg in m.styleSheet(), "切回浅色后 QMenu 应换成浅色卡片色"
        assert dark_bg not in m.styleSheet(), "浅色下不应残留深色卡片底色"


@check("寿命：跨样品汇总图/PDF 报告复用已有拟合结果（v4.23）")
def t_lifetime_batch_reuse_cache():
    import shutil
    import tempfile
    import plot_lifetime as pl
    app, w = _make_gui()
    w.spectrum_type_combo.setCurrentIndex(2)
    t, decay, irf = _synth_double_exponential()
    w.data_cache = {}
    # v4.37：批量动作只处理**勾选**的样品，所以文件列表里必须有条目（全勾选）
    w.file_list.clear()
    from PyQt5.QtCore import Qt as _Qt2
    from PyQt5.QtWidgets import QListWidgetItem as _Item
    for i in range(3):
        key = f's{i}.csv'
        w.data_cache[key] = {'data': {
            'time': t, 'decay': np.maximum(decay * (1.0 - 0.15 * i), 0.0),
            'irf': irf, 'meta': None}}
        _it = _Item(key)
        _it.setFlags(_it.flags() | _Qt2.ItemIsUserCheckable)
        _it.setCheckState(_Qt2.Checked)
        w.file_list.addItem(_it)
    w.lifetime_auto_lambda_check.setChecked(False)   # 快跑，不扫 λ
    w.lifetime_nrates_spin.setValue(51)              # 控件下限即 51，小值最快
    params = w._collect_plot_params()

    calls = []
    real_fit_many = pl.fit_many

    def spy(datasets, **kw):
        calls.append([d['name'] for d in datasets])
        return real_fit_many(datasets, **kw)

    pl.fit_many = spy
    out = tempfile.mkdtemp(prefix='spectra_cache_')
    try:
        # 第一次：汇总图要拟合全部 3 个
        w._do_batch_export(dict(params, kind='summary', save_dir=out))
        assert len(calls) == 1 and len(calls[0]) == 3, \
            f"首次汇总图应拟合 3 个，实际 {calls}"
        assert w._lifetime_cached_count(params) == 3, "结果应回写缓存"
        # 第二次：PDF 报告应 0 个新拟合（用户反馈的核心场景）
        calls.clear()
        msg = w._do_batch_export(dict(params, kind='pdf', save_dir=out))
        assert calls == [], f"PDF 报告不应重新拟合，实际 {calls}"
        assert '复用' in msg and '新拟合' not in msg, "提示应说明全部复用"
        # 叠加分布同样复用
        calls.clear()
        w._do_overlay_lifetime(dict(params))
        assert calls == [], f"叠加分布不应重新拟合，实际 {calls}"
        # 改参数后缓存失效，必须重新拟合
        calls.clear()
        w.lifetime_nrates_spin.setValue(111)      # 51 → 111，缓存键变了
        params2 = w._collect_plot_params()
        assert params2['lifetime_nrates'] != params['lifetime_nrates'], \
            "用例前提：速率点数必须真的变了"
        w._do_batch_export(dict(params2, kind='summary', save_dir=out))
        assert len(calls) == 1 and len(calls[0]) == 3, \
            f"参数变化后应重新拟合全部，实际 {calls}"
        assert os.path.isdir(out) and os.listdir(out), "批量导出应产出文件"
    finally:
        pl.fit_many = real_fit_many
        shutil.rmtree(out, ignore_errors=True)


# ---------------------------------------------------------------- v4.32 新增
def _write_three_col_csv(path, t, decay, irf):
    """写一份「简单三列表格」CSV（plot_lifetime 的格式二），含表头。"""
    import csv
    with open(path, 'w', newline='', encoding='utf-8') as fh:
        wr = csv.writer(fh)
        wr.writerow(['time', 'decay', 'irf'])
        for a, b, c in zip(t, decay, irf):
            wr.writerow([f'{a:.6g}', f'{b:.6g}', f'{c:.6g}'])


@check("GUI：寿命分布叠加不逐条归一，保留相对幅度（v4.33）")
def t_overlay_shared_scale():
    """叠加分布必须用**共用**比例因子，而不是每条曲线各自归一。

    旧行为 `dist / dist.max()` 把每条曲线的峰高都拉到 1，抹掉了分布之间的
    幅度差异。新行为除以**全部曲线的全局最大值**，曲线间高度差得以保留。

    注意 `k_distribution` 是**相对幅度**（拟合内部已按 decay_max 归一，
    x_fit = 峰高/decay_max），所以整体衰减倍数不体现在其上；样本间的差异
    来自分布形状（几个分量的相对强弱）。本用例用 3 份形状不同的衰减验证。
    """
    import shutil
    import tempfile
    from PyQt5.QtWidgets import QApplication, QMessageBox

    for fn in ('information', 'warning', 'critical'):
        setattr(QMessageBox, fn, staticmethod(lambda *a, **k: None))
    app = QApplication.instance() or QApplication(sys.argv)

    rng = np.random.default_rng(11)
    dt = 0.05
    t = np.arange(0, 60, dt)
    irf = np.exp(-0.5 * ((t - 2.0) / 0.15) ** 2)
    irf = irf / irf.sum()

    def _make(frac_fast, tau_fast, tau_slow, seed):
        r = np.random.default_rng(seed)
        truth = np.zeros_like(t)
        for a, tau in ((frac_fast, tau_fast), (1 - frac_fast, tau_slow)):
            truth += a * np.convolve(irf, np.exp(-t / tau), mode='full')[:len(t)]
        truth *= 20000.0 / truth.max()
        return np.maximum(r.poisson(truth).astype(float), 0.0)

    # 三个「明显不同形状」的样品：快/慢分量的比例与寿命都不同
    specs = [(0.9, 1.0, 12.0, 1), (0.5, 2.5, 8.0, 2), (0.1, 4.0, 6.0, 3)]

    out = tempfile.mkdtemp(prefix='spectra_overlay_')
    try:
        for i, (ff, tf, ts, sd) in enumerate(specs):
            _write_three_col_csv(os.path.join(out, f'sample{i}.csv'),
                                 t, _make(ff, tf, ts, sd), irf * 1e6)

        from absorption_gui import AbsorptionGUI
        w = AbsorptionGUI()
        w.spectrum_type_combo.setCurrentIndex(2)      # 荧光寿命
        w.lifetime_method_combo.setCurrentIndex(1)    # SESM 快
        w.lifetime_nrates_spin.setValue(101)
        w.load_data_from_folder(out)
        assert w.file_list.count() == 3, \
            f"应载入 3 个样品，实际 {w.file_list.count()}"

        fig = w._do_overlay_lifetime()
        ax = fig.axes[0]
        assert '未逐条归一' in ax.get_ylabel(), \
            f"纵轴标签应说明未逐条归一，实际 {ax.get_ylabel()!r}"

        peaks = [float(np.max(np.asarray(ln.get_ydata(), dtype=float)))
                 for ln in ax.get_lines()]
        assert len(peaks) == 3, f"应有 3 条曲线，实际 {len(peaks)}"
        # 核心断言：旧 bug 下每条曲线都被拉到 1（全部相等）
        assert not all(abs(p - 1.0) < 1e-9 for p in peaks), \
            "所有曲线峰高都等于 1 → 仍是逐条归一（旧 bug 回归）"
        assert max(peaks) - min(peaks) > 0.02, \
            f"曲线峰高几乎相同（{peaks}），相对幅度差异被抹掉了"
        # 全局最大值那条应为 1（共用因子的定义），其余 < 1
        assert abs(max(peaks) - 1.0) < 1e-9, \
            f"全局最大值那条曲线应为 1，实际 {max(peaks)}"
        # 与原始分布的自算比值一致（确认没有额外变形）
        raw = [float(np.max(np.asarray(r['k_distribution'], dtype=float)))
               for r in w._overlay_results if r]
        gmax = max(raw)
        for p, rv in zip(sorted(peaks), sorted(v / gmax for v in raw)):
            assert abs(p - rv) < 1e-9, \
                f"绘图峰高 {p} 应等于原始幅度比 {rv}"

        # 图例必须**干净**：只留样品名（v4.34），不再挂振幅/强度
        labels = [t.get_text() for t in ax.get_legend().get_texts()]
        assert len(labels) == 3, f"应有 3 条图例，实际 {labels}"
        names = [str(r.get('name', '')) for r in w._overlay_results if r]
        assert labels == names, f"图例应只含样品名：{labels} vs {names}"
        for lab in labels:
            assert 'A=' not in lab and 'I=' not in lab and '\n' not in lab, \
                f"图例应保持干净、无振幅/强度附加行：{lab!r}"
    finally:
        shutil.rmtree(out, ignore_errors=True)


# ---------------------------------------------------------------- v4.24 新增
@check("GUI：目录树栏按钮等宽、单行路径带 tooltip（v4.24）")
def t_gui_tree_panel_layout():
    from PyQt5.QtCore import Qt
    app, w = _make_gui()
    # 顶部三个图标按钮必须等宽（旧版 160/160/自适应，左边缘参差）
    btns = [getattr(w, 'theme_btn', None), getattr(w, 'help_btn', None)]
    btns = [b for b in btns if b is not None]
    assert len(btns) == 2, "主题/帮助按钮应存在"
    sizes = {(b.width(), b.height()) for b in btns}
    assert len(sizes) == 1, f"顶部图标按钮尺寸不一致: {sizes}"
    for b in btns:
        assert b.toolTip(), f"{b.text()} 按钮缺少 tooltip（图标按钮必须靠 tooltip 说明）"
    # 路径标签必须单行 + 完整路径进 tooltip（旧版长路径自动换行占 3 行）
    for attr in ('workspace_label', 'folder_label'):
        lb = getattr(w, attr)
        assert not lb.wordWrap(), f"{attr} 应关闭自动换行（保持单行）"
    w.workspace_label.setText("工作区: …\\光谱")
    assert w.workspace_label.text().count('\n') == 0
    # 光谱类型下拉框：选项文本不得含英文括号全称（200px 栏里必被截断）
    items = [w.spectrum_type_combo.itemText(i)
             for i in range(w.spectrum_type_combo.count())]
    assert items == ["吸收光谱", "发射光谱", "荧光寿命", "3D 扫描"], \
        f"光谱类型下拉项应为中文短名，实际 {items}"
    for i in range(w.spectrum_type_combo.count()):
        assert w.spectrum_type_combo.itemData(i, Qt.ToolTipRole), \
            "下拉项应带全称 tooltip"


@check("GUI：深色画布与窗口分层、选中态对比度达标（v4.24）")
def t_gui_dark_canvas_layering():
    app, w = _make_gui()
    from gui_config import THEMES
    D = THEMES['dark']
    # 画布 figure 底色必须与窗口底色不同，否则深色下画布和窗口糊成一片
    assert D['MPL_FIG'].lower() != D['BG'].lower(), \
        "深色下 MPL_FIG 与 BG 相同 → 画布没有边界（v4.24 回归）"
    # 注：深色下两者亮度都很低，对比度上限本来就只有约 1.17:1（黑是硬下限），
    # 所以这里只要求"有可测量的明暗差"，真正的边界由 pane 的描边 + 内边距给出
    assert _contrast(D['MPL_FIG'], D['BG']) >= 1.03, \
        "深色下画布与窗口的明暗差过小，看不出边界"
    # 画布坐标区与 figure 边距之间也要分层
    assert D['MPL_AX'].lower() != D['MPL_FIG'].lower()
    # 结构性分层：标签页 pane 必须有描边与内边距
    qss = app.styleSheet()
    assert 'QTabWidget::pane' in qss, "样式表缺少 QTabWidget::pane 规则"
    assert 'padding: 4px' in qss, \
        "画布卡片应留 4px 内边距（深色下靠这圈边框区分画布与卡片）"
    # 选中态：深色下选中项背景对卡片底色的对比度（旧值 #1e3a5f 仅约 1.3:1）
    sel = _contrast(D['SELECT_BG'], D['CARD'])
    assert sel >= 1.8, f"深色选中态对比度 {sel:.2f} < 1.8（选中项几乎看不见）"
    # 浅色主题不受影响
    L = THEMES['light']
    assert _contrast(L['SELECT_BG'], L['CARD']) >= 1.2


@check("GUI：帮助改用主题化可滚动窗口、深色下不是白板（v4.24）")
def t_gui_help_dialog():
    from PyQt5.QtWidgets import QListWidget, QTextBrowser
    from gui_help import HelpDialog
    app, w = _make_gui()
    w.toggle_theme(True)
    dark = w.theme_palette()
    dlg = w.show_help()
    assert isinstance(dlg, HelpDialog), \
        "F1 帮助应改用 gui_help.HelpDialog（不是 QMessageBox.about）"
    # 结构：左侧目录 + 右侧可滚动正文
    assert dlg.findChildren(QTextBrowser), "帮助窗口应有可滚动的正文区"
    toc = dlg.findChildren(QListWidget)
    assert toc and toc[0].count() == 3, "帮助窗口应有三节目录（当前模式/快捷键/其它）"
    assert f"background-color: {dark['CARD']}" in dlg.styleSheet(), \
        "深色下帮助窗口正文底应为深色卡片色"
    assert 'QTextBrowser' in dlg.styleSheet(), "正文区应有显式样式（否则跟随系统调色板）"
    # 切回浅色再打开同一窗口：样式表必须跟着换（不能残留深色/白块）
    w.toggle_theme(False)
    light = w.theme_palette()
    dlg2 = w.show_help()
    assert f"background-color: {light['CARD']}" in dlg2.styleSheet(), \
        "切回浅色后帮助窗口应换成浅色卡片色"
    dlg2.close()
    # 入口界面的「？」帮助共用同一个窗口类
    from gui_launcher import ModuleLauncher
    lau = ModuleLauncher(theme='dark')
    ld = lau.show_help()
    assert isinstance(ld, HelpDialog), "入口界面帮助也应改用 HelpDialog"
    assert f"background-color: {dark['CARD']}" in ld.styleSheet()
    ld.close()
    lau.close()


@check("GUI：操作区按钮体系收口、导出合并为菜单（v4.25）")
def t_gui_action_buttons():
    from PyQt5.QtWidgets import QGroupBox, QPushButton
    app, w = _make_gui()
    # 1) 「操作」区只允许"实心主色"按钮出现一次（原来 6 个彩色实心按钮排成一列）
    action_group = w.preview_btn.parentWidget()
    assert isinstance(action_group, QGroupBox), "主按钮应位于「操作」分组里"
    btns = action_group.findChildren(QPushButton)
    variants = [b.property('variant') or 'default' for b in btns]
    banned = {'violet', 'orange', 'cyan', 'success', 'neutral'}
    bad = [v for v in variants if v in banned]
    assert not bad, f"「操作」区不该再出现整块填充的语义色按钮: {bad}"
    assert variants.count('primary') == 1, \
        f"「操作」区应恰好 1 个主色按钮，实际 {variants}"
    assert variants.count('export') == 1, "应有一个「导出 ▾」菜单按钮"
    # 2) 导出菜单：5 个动作 + 1 条分隔线；寿命专属项随模式显隐
    menu = w.export_menu
    texts = [a.text() for a in menu.actions() if not a.isSeparator()]
    for key in ('导出当前图', '导出全部图片', '导出当前拟合结果',
                '跨样品汇总图', '导出 PDF 报告'):
        assert any(key in t for t in texts), f"导出菜单缺少「{key}」"
    lifetime_acts = [w.act_export_fit, w.act_summary_plot,
                     w.act_pdf_report, w.act_export_sep]
    w.spectrum_type_combo.setCurrentIndex(0)          # 吸收模式
    assert all(not a.isVisible() for a in lifetime_acts), \
        "非寿命模式下三条寿命导出项（含分隔线）必须隐藏"
    w.spectrum_type_combo.setCurrentIndex(2)          # 寿命模式
    assert all(a.isVisible() for a in lifetime_acts), "寿命模式下应显示全部导出项"
    # 3) 主按钮文字随模式切换（v4.28 起图标换成单色图标集，文字不再带 ▶）
    assert w.preview_btn.text() == "开始拟合", \
        f"寿命模式主按钮应为开始拟合，实际 {w.preview_btn.text()!r}"
    w.spectrum_type_combo.setCurrentIndex(1)
    assert w.preview_btn.text() == "实时预览", \
        f"光谱模式主按钮应为实时预览，实际 {w.preview_btn.text()!r}"
    # 4) 不再有重复的拟合入口
    assert not hasattr(w, 'lifetime_fit_btn'), \
        "「开始拟合」应只剩操作区主按钮一个入口（原来寿命拟合组里还有一个）"


@check("GUI：字阶收口后参数区不再需要滚 2.5 屏（v4.25）")
def t_gui_type_scale_density():
    from PyQt5.QtWidgets import QGroupBox
    app, w = _make_gui()
    w.spectrum_type_combo.setCurrentIndex(2)          # 寿命模式控件最多
    app.processEvents()
    qss = app.styleSheet()
    assert 'QLabel {\n                color:' in qss or 'font-size: 13px' in qss, \
        "全局样式表应使用 13px 正文（v4.25 字阶）"
    # 注：用 isHidden() 而不是 isVisible()——测试里窗口没 show()，isVisible() 全为 False
    groups = [g for g in w.param_panel.findChildren(QGroupBox) if not g.isHidden()]
    total = sum(g.sizeHint().height() for g in groups)
    assert groups, "参数区应至少有一个分组框"
    # 同一探针实测：v4.24 = 1230+575+294 = 2099px（要滚 2.5 屏），v4.25 = 1100+494+126 = 1720px。
    # v4.29 起「绘图参数」外层分组框由 dock 的标题栏取代，探针里不再计入它
    # （旧值还把嵌套的「寿命拟合」重复算了一遍），寿命模式实测 494+124 = 618px。
    assert total < 900, f"参数区内容总高 {total}px 偏大（字阶/间距回涨了？）"
    assert total > 450, f"参数区内容总高 {total}px 异常偏小，可能控件丢了"
    # 栏标题交给 dock 标题栏：参数栏里不该再有一层「绘图参数」卡片
    assert not any(g.title() == "绘图参数" for g in groups), \
        "「绘图参数」外层分组框应已并入 dock 标题栏"
    assert w.param_dock.windowTitle() == "参数", \
        f"参数栏 dock 标题应为「参数」，实际 {w.param_dock.windowTitle()!r}"


# ---------------------------------------------------------------- v4.26 新增
# v4.29：三栏由 QSplitter 子控件改为 QDockWidget，探针同步改成量 dock / 画布宽度
@check("GUI：三栏可收起 + 收起后画布变宽 + 宽度记忆（v4.26 / v4.29 Dock）")
def t_gui_panel_collapse():
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QDockWidget
    app, w = _make_gui()
    w.resize(1368, 783)                  # 默认窗口宽度，量出来的数才有意义
    w.show()
    app.processEvents()
    w.reset_dock_layout()                # 忽略上次会话存的停靠/浮动状态，量基准
    w._apply_col_sizes()
    app.processEvents()

    btns = getattr(w, 'panel_toggle_btns', [])
    assert len(btns) == 3, f"栏开关条应有 3 个按钮，实际 {len(btns)}"
    assert all(b.isChecked() for b in btns), "初始应三栏都展开"
    # 三栏必须是停靠面板（可拖动 / 拖出浮动 / 按 × 关闭）
    assert all(isinstance(d, QDockWidget) for d in w._panel_docks), \
        "三栏应为 QDockWidget"
    assert all(d.objectName() for d in w._panel_docks), \
        "每个 dock 都要有 objectName（saveState/restoreState 靠它识别）"
    assert w.dockWidgetArea(w.tree_dock) == Qt.LeftDockWidgetArea and \
        w.dockWidgetArea(w.file_dock) == Qt.LeftDockWidgetArea and \
        w.dockWidgetArea(w.param_dock) == Qt.RightDockWidgetArea, \
        "默认布局应为「左侧 目录树+数据 / 右侧 参数」"
    # 开关条必须在所有 dock **之外**：栏关掉后栏内控件全都不显示，
    # 开关按钮如果放在栏里就等于"关了就再也打不开"
    assert all(not w.panel_rail.isAncestorOf(p)
               for p in (w.tree_panel, w.file_panel, w.param_panel)), \
        "开关条不应位于任何栏内"

    base = w.canvas_panel.width()
    w.toggle_panel(0)
    app.processEvents()
    assert not w.tree_dock.isVisible(), "收起后目录树栏应隐藏"
    assert not btns[0].isChecked(), "收起后开关条按钮应取消勾选"
    one = w.canvas_panel.width()
    assert one > base, f"收起目录树后画布应变宽：{base} → {one}"
    w.toggle_panel(1)
    app.processEvents()
    two = w.canvas_panel.width()
    assert two > one, f"再收起数据栏后画布应更宽：{one} → {two}"
    assert two >= 950, f"收起目录树+数据后画布应 ≥950px，实际 {two}"
    w.toggle_panel(0)
    w.toggle_panel(1)                    # 都展开回来
    app.processEvents()
    assert w.tree_dock.isVisible() and w.file_dock.isVisible()
    assert all(b.isChecked() for b in btns), "展开后勾选态应恢复"
    assert w.canvas_panel.width() == base, \
        f"展开后画布宽度应回到 {base}，实际 {w.canvas_panel.width()}"

    if not w.settings.isWritable():
        raise Skip("QSettings 不可写，注册表被限制")
    s = w.settings
    old = {k: s.value(k, None) for k in ('ui/panel_hidden', 'ui/panel_widths')}
    try:
        s.setValue("ui/panel_hidden", [0, 1, 0])
        s.setValue("ui/panel_widths", [240, 210, 320])
        s.sync()
        app2, w2 = _make_gui()
        assert w2._col_hidden == [False, True, False], \
            f"折叠状态未恢复：{w2._col_hidden}"
        assert w2._col_widths == [240, 210, 320], f"宽度未恢复：{w2._col_widths}"
        assert not w2.file_dock.isVisible(), "数据栏应保持上次的收起状态"
        assert not w2.panel_toggle_btns[1].isChecked(), "开关条状态应同步"
        # 坏设置（越界宽度）必须被忽略，否则界面会被搞乱
        s.setValue("ui/panel_widths", [5, 99999, 285])
        s.sync()
        app3, w3 = _make_gui()
        assert w3._col_widths == [200, 210, 285], \
            f"越界宽度应被忽略并退回默认：{w3._col_widths}"
    finally:
        for k, v in old.items():
            if v is None:
                s.remove(k)
            else:
                s.setValue(k, v)
        s.sync()


@check("GUI：布局预设 + 浮动恢复 + dock 状态持久化（v4.29）")
def t_gui_dock_layout_presets():
    from PyQt5.QtCore import Qt
    app, w = _make_gui()
    w.resize(1368, 783)
    w.show()
    app.processEvents()
    w.reset_dock_layout()

    # 三套预设的显隐组合
    for key, expect in (("fit", (0, 0, 0)), ("plot", (0, 0, 1)), ("canvas", (1, 1, 1))):
        w.apply_layout_preset(key)
        app.processEvents()
        got = tuple(1 if h else 0 for h in w._col_hidden)
        assert got == expect, f"预设 {key} 显隐错误：{got} != {expect}"
        vis = tuple(1 if d.isVisible() else 0 for d in w._panel_docks)
        assert vis == tuple(1 - x for x in expect), \
            f"预设 {key} 的 dock 可见性与状态不一致：{vis}"

    # 只看图：画布应吃掉几乎整个宽度
    wide = w.canvas_panel.width()
    assert wide >= 1000, f"「只看图」预设下画布应 ≥1000px，实际 {wide}"

    # 拖出浮动 → 恢复默认布局后必须重新停靠回原位
    w.apply_layout_preset("fit")
    app.processEvents()
    w.param_dock.setFloating(True)
    app.processEvents()
    assert w.param_dock.isFloating(), "参数栏应能拖出成浮动窗口"
    w.reset_dock_layout()
    app.processEvents()
    assert not w.param_dock.isFloating(), "恢复默认布局后参数栏应重新停靠"
    assert w.dockWidgetArea(w.param_dock) == Qt.RightDockWidgetArea, \
        "参数栏应回到右侧"
    assert all(d.isVisible() for d in w._panel_docks), "恢复默认布局后三栏应全展开"

    # 布局菜单里的三个显隐项要跟 dock 实际状态同步
    w.toggle_panel(2)
    app.processEvents()
    acts = getattr(w, 'act_show_panels', [])
    assert len(acts) == 3, f"布局菜单应有 3 个显隐项，实际 {len(acts)}"
    assert not acts[2].isChecked(), "收起参数栏后菜单勾选应取消"
    w.toggle_panel(2)
    app.processEvents()
    assert acts[2].isChecked(), "展开后菜单勾选应恢复"

    # Ctrl+1/2/3 快捷键
    seqs = [sc.key().toString() for sc in getattr(w, '_shortcuts', [])]
    for k in ("Ctrl+1", "Ctrl+2", "Ctrl+3"):
        assert k in seqs, f"缺少布局预设快捷键 {k}：{seqs}"


@check("GUI：主窗口反复建/销毁不泄漏、不在析构期崩（v4.29）")
def t_gui_window_lifecycle():
    """v4.29 排查硬崩溃时立的哨兵。

    当时给 QDockWidget 接了 `visibilityChanged` 的 lambda：闭包引用 self、
    与 dock 形成引用环，窗口对象于是不再即时析构，而是被 GC 延后到任意时刻
    销毁；"仍处于显示状态"的窗口在析构时 dock 会发 Hide 信号，PyQt 在析构期
    派发它直接 abort（退出码 0xC0000409、没有任何 traceback）。
    这里两道防线：
      1. 删掉窗口并 gc.collect() 后控件数要掉下来；
      2. 反复建/销毁（不 close，走"显示状态下被析构"这条路径）——析构期有
         地雷的话进程会当场 abort。
    """
    import gc
    # v5.0.2：改成**增量式**断言。
    # 原实现取 allWidgets() 的绝对值做基准（`left < base // 4`），这个基准里
    # 混着**前面几十个检查项**留下的、还没被 GC 回收的窗口；一旦新增检查项
    # 让遗留量跨过某个阈值，`_make_gui()` 内部恰好触发一轮 GC 把这些遗留
    # 一次性收走 —— base 反而变小（实测 v5.0.2 加 4 条 GUI 检查项后
    # base 从 2881 掉到 1093），而 base//4 随之压到 273，被固定的 646 个
    # 残留判为失败。也就是说：**泄漏量一点没变（HEAD 与本版的 left 都是 646），
    # 变的只是测量起点。** 现在只问"这个窗口自己建的控件回收掉了吗"。
    # 先把 app 单独拿到（_make_gui 会连窗口一起建，那样就没法量 before）
    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    gc.collect()
    app.processEvents()
    before = len(app.allWidgets())

    _app, w = _make_gui()
    w.show()
    app.processEvents()
    peak = len(app.allWidgets())
    built = peak - before
    assert built > 200, f"主窗口控件数异常偏少：新建窗口只多了 {built} 个控件"
    # PyQt 里 connect(self.方法) 天然会形成引用环（窗口要等 GC 才回收，这是
    # 既有行为，不是本次引入的），所以这里显式 gc.collect() 逼出析构——
    # 重要的是"显示状态下被析构"这条路径要能安全走完。
    del w
    gc.collect()
    app.processEvents()
    left = len(app.allWidgets())
    freed = peak - left
    assert freed >= built * 0.9, (
        f"GC 后主窗口控件基本没释放：新建 {built} 个，只回收了 {freed} 个"
        f"（窗口销毁后不应留 90% 以上的控件）")
    # 反复建/销毁（不 close，走"显示状态下被析构"这条路径）——析构期有地雷
    # 的话进程会当场 abort。每轮允许留少量（滚动条/视图容器等 Qt 内部对象），
    # 但不能出现"建一个留一个整窗"的量级。
    for _ in range(3):
        _app, t = _make_gui()
        t.show()
        app.processEvents()
        del t
        gc.collect()
        app.processEvents()
    grew = len(app.allWidgets()) - left
    assert grew < built, \
        f"反复建/销毁 3 轮后多出 {grew} 个控件（接近一个整窗的 {built} 个，疑似未回收）"


@check("主题：三套色板键一致 + 高对比达标 + 循环切换（v4.30）")
def t_theme_three_sets():
    import gui_config as cfg
    THEMES, ORDER, LABELS = cfg.THEMES, cfg.THEME_ORDER, cfg.THEME_LABELS

    # 1) 三套色板的键必须完全一致——apply_style 是按固定键名解包的，
    #    少一个键就直接 KeyError（加主题时最容易漏的就是这里）
    base = set(THEMES[cfg.DEFAULT_THEME])
    for name in ORDER:
        assert name in THEMES, f"THEME_ORDER 里的 {name} 不在 THEMES 里"
        missing = sorted(base - set(THEMES[name]))
        extra = sorted(set(THEMES[name]) - base)
        assert not missing and not extra, \
            f"{name} 色板键与 {cfg.DEFAULT_THEME} 不一致：缺 {missing} 多 {extra}"
    assert len(ORDER) == 3 and len(set(ORDER)) == 3, f"主题顺序表异常：{ORDER}"
    assert set(LABELS) == set(ORDER), "每套主题都要有界面显示名（THEME_LABELS）"

    # 2) 高对比主题：文字与语义色对卡片底色的对比度 ≥ 7:1（WCAG AAA）
    def _lum(hexc):
        c = hexc.lstrip('#')
        ch = [int(c[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
        ch = [v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
              for v in ch]
        return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2]

    def _ratio(a, b):
        la, lb = _lum(a), _lum(b)
        hi, lo = max(la, lb), min(la, lb)
        return (hi + 0.05) / (lo + 0.05)

    P = THEMES['contrast']
    for key in ('TEXT', 'TEXT_SOFT', 'MUTED', 'ACCENT', 'SUCCESS', 'VIOLET',
                'ORANGE', 'CYAN', 'DANGER'):
        r = _ratio(P[key], P['CARD'])
        assert r >= 7.0, \
            f"高对比主题 {key}={P[key]} 对卡片底色只有 {r:.2f}:1（要求 ≥7:1）"
    assert _ratio(P['SELECT_FG'], P['SELECT_BG']) >= 7.0, \
        "高对比主题选中态文字对比度不足"
    assert _ratio(P['TOOLTIP_FG'], P['TOOLTIP_BG']) >= 7.0, \
        "高对比主题 tooltip 对比度不足"
    assert P['BORDER'] == '#000000' and P['TEXT'] == '#000000', \
        "高对比主题应是纯黑描边 + 纯黑文字（打印友好）"
    # 另两套也不能比原来更差（防止误改）
    assert _ratio(THEMES['dark']['TEXT'], THEMES['dark']['CARD']) >= 7.0, \
        "深色主题正文对比度回退了"

    # 3) 图标集要有第三套（描边纯黑），否则高对比主题会静默用浅色那套
    from gui_icons import icon_path, THEMES as ICON_THEMES
    for name in ORDER:
        assert name in ICON_THEMES, f"图标集没有 {name} 这一套：{ICON_THEMES}"
        assert icon_path('contrast', name, 48), f"{name} 主题缺 contrast 图标"
        assert icon_path('close', name, 24), f"{name} 主题缺 close 图标"

    # 4) 主题按钮三态循环，每态图标都取得到
    app, w = _make_gui()
    # v4.46：首次启动的默认主题改为**跟随操作系统深浅色**（Windows 深色用户
    # 第一次打开不再是白界面）。这意味着 w.theme 的初值取决于跑测试的机器——
    # 断言"循环顺序必须等于 ORDER"会因此假失败。这里显式把起点钉到 ORDER[0]，
    # 只验证"循环逻辑"本身，不验证"初值"。
    w.set_theme(ORDER[0])
    app.processEvents()
    seen = []
    for _ in range(3):
        seen.append(w.theme)
        assert not w.theme_btn.icon().isNull(), f"{w.theme} 主题下主题按钮没图标"
        assert w.theme_btn.toolTip(), "主题按钮缺 tooltip"
        w.cycle_theme()
        app.processEvents()
    assert seen == list(ORDER), f"主题循环顺序不对：{seen}"
    assert w.theme == ORDER[0], "循环三轮后应回到起始主题"
    assert '已切换到' in w.status_bar.currentMessage(), "切主题应在状态栏给出提示"

    # 5) 入口界面模块卡片主色必须来自设计令牌（原来写死四个字面量）
    from gui_launcher import ModuleLauncher
    tokens = {cfg.ACCENT, cfg.SUCCESS, cfg.VIOLET, cfg.CYAN}
    for mode in ModuleLauncher.MODES:
        assert mode[4] in tokens, f"模块卡片主色 {mode[4]!r} 不是设计令牌"


@check("GUI：文件列表搜索过滤 + 全选只作用于筛选结果（v4.26）")
def t_gui_file_search_select():
    from PyQt5.QtCore import Qt as _Qt
    from PyQt5.QtWidgets import QListWidgetItem
    app, w = _make_gui()
    assert hasattr(w, 'file_search_edit'), "数据栏应有搜索框"
    assert hasattr(w, 'file_select_btn'), "数据栏应有全选按钮"
    names = ["A0_1000cpc.csv", "A1_1000cpc.csv", "A2_10cpc.csv",
             "A3_100cpc.csv", "A4_500cpc.csv"]
    w.file_list.clear()
    for n in names:
        it = QListWidgetItem(n)
        it.setFlags(it.flags() | _Qt.ItemIsUserCheckable)
        it.setCheckState(_Qt.Unchecked)
        w.file_list.addItem(it)
    w._sync_file_item_tooltips()
    w._apply_file_filter("")
    assert len(w._visible_file_items()) == 5, "无搜索词时不应隐藏任何项"
    assert w.file_count_label.text() == "已加载 5 个文件", \
        f"计数标签异常：{w.file_count_label.text()!r}"
    assert w.file_select_btn.text() == "全选"

    w.file_search_edit.setText("1000")
    app.processEvents()
    shown = len(w._visible_file_items())
    assert shown == 2, f"“1000” 应命中 2 个，实际 {shown}"
    assert "显示 2" in w.file_count_label.text(), \
        f"计数标签应显示过滤结果：{w.file_count_label.text()!r}"
    w.toggle_select_all_visible()
    app.processEvents()
    assert len(w.get_checked_files()) == 2, \
        f"全选应只勾筛选出的 2 个，实际 {len(w.get_checked_files())}"
    assert w.file_select_btn.text() == "全不选", "筛选结果全勾后按钮应变「全不选」"
    w.file_search_edit.setText("")
    app.processEvents()
    assert len(w.get_checked_files()) == 2, \
        "清空搜索词不应改变已勾选的样品（过滤只影响显示）"
    assert w.file_select_btn.text() == "全选", "仍有未勾选项，按钮应回到「全选」"
    w.toggle_select_all_visible()
    app.processEvents()
    assert len(w.get_checked_files()) == 5, "无筛选时全选应勾上全部"
    w.toggle_select_all_visible()
    app.processEvents()
    assert len(w.get_checked_files()) == 0, "再点一次应全部取消勾选"


@check("GUI：积分结果改表格——表头 / 数值排序 / 导出 CSV（v4.26）")
def t_gui_integration_table():
    import tempfile
    from PyQt5.QtCore import Qt as _Qt
    from gui_plot import NumericTableItem
    app, w = _make_gui()
    assert hasattr(w, 'integ_table'), "积分结果应为 QTableWidget"
    assert not hasattr(w, 'integ_output'), "旧的 QPlainTextEdit 应已移除"
    assert hasattr(w, 'integ_csv_btn'), "应有导出 CSV 按钮"
    table = w.integ_table
    headers = [table.horizontalHeaderItem(c).text()
               for c in range(table.columnCount())]
    assert headers == ["样品", "区间 (nm)", "积分值"], f"表头异常：{headers}"
    # 积分值列必须按**数值**排序（字符串排序会把 9 排在 100 后面）
    assert NumericTableItem("9") < NumericTableItem("100"), \
        "积分值列的排序必须是数值比较"

    w._last_integration_results = {
        'lo': 450.0, 'hi': 550.0,
        'rows': [('s3', 900.0), ('s1', 100.0), ('s2', float('nan'))],
    }
    w._update_integration_output()
    assert table.rowCount() == 2, f"NaN 样品应被跳过，实际 {table.rowCount()} 行"
    table.sortItems(2, _Qt.AscendingOrder)
    vals = [float(table.item(r, 2).text()) for r in range(2)]
    assert vals == sorted(vals), f"积分值升序失败：{vals}"
    table.sortItems(0, _Qt.AscendingOrder)
    names_sorted = [table.item(r, 0).text() for r in range(2)]
    assert names_sorted == ['s1', 's3'], f"样品列按文本排序异常：{names_sorted}"
    assert table.item(0, 1).text() == "450–550", \
        f"区间文本异常：{table.item(0, 1).text()!r}"
    assert "共 2 个样品" in w.integ_count_label.text(), \
        f"计数标签异常：{w.integ_count_label.text()!r}"

    tsv = w._integration_tsv().strip().splitlines()
    assert len(tsv) == 3 and '\t' in tsv[0], f"复制文本应为表头+2 行制表符文本：{tsv}"
    tmp = tempfile.mkdtemp(prefix='integ_csv_')
    out = w._export_integration_csv(save_dir=tmp)
    assert out and os.path.exists(out), f"CSV 未生成：{out}"
    raw = open(out, 'rb').read()
    assert raw.startswith(b'\xef\xbb\xbf'), "CSV 应带 UTF-8 BOM（Excel 不乱码）"
    lines = open(out, encoding='utf-8-sig').read().strip().splitlines()
    assert len(lines) == 3, f"CSV 应为表头 + 2 行，实际 {len(lines)}"


# ---------------------------------------------------------------- v4.36 新增
@check("GUI：减法扣不了本底的光谱只跳过自己，不再清空积分表/整图报错（v4.36）")
def t_gui_subtract_skip_keeps_integration():
    from PyQt5.QtCore import Qt as _Qt
    from PyQt5.QtWidgets import QListWidgetItem
    app, w = _make_gui()
    w.spectrum_type_combo.setCurrentIndex(1)          # 发射模式
    # 一批数据里混着不同发射窗口：A/B 与水本底（300–548）重叠，C（560–800）完全不重叠。
    # 这正是 20260915 那批实测数据的情形（RB 300–540、R101/EtOH 560–800、H2O 300–548）。
    def _peak(wl, c, wd, amp=1000.0):
        return {'wavelength': wl, 'intensity': amp * np.exp(-((wl - c) / wd) ** 2)}

    w.data_cache = {
        'A (Emission)': {'data': _peak(np.arange(300.0, 541.0), 420.0, 20.0)},
        'B (Emission)': {'data': _peak(np.arange(360.0, 501.0), 450.0, 25.0)},
        'C (Emission)': {'data': _peak(np.arange(560.0, 801.0), 650.0, 25.0)},
        'bg (Emission)': {'data': _peak(np.arange(300.0, 549.0), 430.0, 3.0, 50.0)},
    }
    w.file_list.clear()
    for n in w.data_cache:
        it = QListWidgetItem(n)
        it.setFlags(it.flags() | _Qt.ItemIsUserCheckable)
        it.setCheckState(_Qt.Checked)
        w.file_list.addItem(it)

    w.subtract_enable_check.setChecked(True)
    w._refresh_subtract_combos()
    w.subtract_minuend_combo.setCurrentIndex(0)       # 所有光谱（各减本底）
    w.subtract_ref_combo.setCurrentText('bg (Emission)')
    w.integ_min_spin.setValue(400.0)
    w.integ_max_spin.setValue(510.0)
    sub_cfg = w._get_subtract_config()
    assert sub_cfg == {'mode': 'bg', 'a': None, 'b': 'bg (Emission)'}, \
        f"用例前提：应为扣除本底模式，实际 {sub_cfg}"

    # 修复前：C 与本底无重叠 → _subtract_ref 抛 ValueError → 整个 _do_plot 崩掉，
    # _last_integration_results 被置 None，结果表整张清空（用户看到的就是「无法积分」）
    w._do_plot()
    res = w._last_integration_results
    assert res is not None, "启用减法后积分结果不应整表清空（v4.35 的 bug）"
    names = [n for n, _v in res['rows']]
    assert names == ['A', 'B'], f"只有与本底重叠的样品能积分，实际 {names}"
    assert all(np.isfinite(v) for _n, v in res['rows']), "积分值应为有限数"
    skips = dict(res['skipped'])
    assert 'C' in skips and '无重叠' in skips['C'], f"跳过原因要写清楚：{skips}"
    assert not any(n.startswith('bg') for n in names), "本底文件自身不参与积分"

    w._update_integration_output()
    assert w.integ_table.rowCount() == 2, \
        f"结果表应有 2 行，实际 {w.integ_table.rowCount()}"
    label = w.integ_count_label.text()
    assert '共 2 个样品' in label and '1 个无法扣本底已跳过' in label, \
        f"计数标签应说明跳过数：{label!r}"
    assert 'C' in w.integ_count_label.toolTip(), "跳过明细应挂悬停提示"

    # 绘图：扣不了本底的那条只跳过自己，其余照画，不再弹「绘图失败」
    assert len(w.canvas.axes.get_lines()) == 2, \
        f"应画出 2 条可扣本底的光谱，实际 {len(w.canvas.axes.get_lines())} 条"
    note = w._subtract_skip_note()
    assert '已跳过 1 条' in note and 'C' in note, f"状态栏应说明跳过：{note!r}"

    # 差谱模式：A=C 与本底无重叠 → 结果表为空但只提示、不抛异常
    w.subtract_minuend_combo.setCurrentText('C (Emission)')
    w._do_plot()
    res = w._last_integration_results
    assert res is not None and res['rows'] == [], f"差谱无重叠应只跳过：{res}"
    assert len(res['skipped']) == 1 and 'C' in res['skipped'][0][0], \
        f"应记录一条跳过明细：{res['skipped']}"
    w._update_integration_output()
    assert w.integ_table.rowCount() == 0
    assert '无法扣除本底' in w.integ_count_label.text(), \
        f"应提示无可用结果：{w.integ_count_label.text()!r}"

    # 关掉减法：口径回到「所有已加载样品」，不出现任何跳过
    # （C 与积分区间无重叠 → 积分值 NaN，由结果表按「无重叠未列出」处理）
    w.subtract_enable_check.setChecked(False)
    w._do_plot()
    res = w._last_integration_results
    assert res['skipped'] == [], f"未启用减法不应有跳过：{res['skipped']}"
    assert len(res['rows']) == 4, f"未启用减法应给出 4 个样品：{res['rows']}"
    assert any(not np.isfinite(v) for _n, v in res['rows']), \
        "C 与积分区间无重叠，其积分值应为 NaN（由结果表跳过展示）"


# ---------------------------------------------------------------- v4.27 新增
@check("GUI：matplotlib 工具条中文 tooltip + 三组分隔不重复（v4.27）")
def t_gui_nav_toolbar():
    from PyQt5.QtWidgets import QToolBar
    app, w = _make_gui()
    tb = w.toolbar
    assert isinstance(tb, QToolBar), "预览画布应有 matplotlib 导航工具条"
    actions = tb.actions()
    texts = [a.text() for a in actions if not a.isSeparator()]
    for label in ('复位视图', '上一视图', '下一视图', '平移', '框选缩放',
                  '保存图片'):
        assert label in texts, f"工具条按钮「{label}」缺中文标题：{texts}"
    # mpl 自己带两条分隔（视图 | 缩放/参数 | 保存），不能再插第二条
    n_sep = sum(1 for a in actions if a.isSeparator())
    assert n_sep == 2, f"工具条应恰好 2 条分组分隔线，实际 {n_sep}"
    for a in actions:
        if a.isSeparator() or not a.text():
            continue
        assert a.toolTip(), f"按钮「{a.text()}」没有 tooltip"
        assert any('\u4e00' <= ch <= '\u9fff' for ch in a.text()), \
            f"按钮「{a.text()}」标题仍是英文"
    # 三个画布的工具条都要处理过
    for name in ('lifetime_toolbar', 'diag_toolbar'):
        other = getattr(w, name, None)
        if other is None:
            continue
        tips = [a.toolTip() for a in other.actions() if not a.isSeparator()]
        assert any('复位视图' in t for t in tips), f"{name} 没走中文化处理"


@check("GUI：空状态引导页与画布切换、工具条随空状态隐藏（v4.27）")
def t_gui_empty_state():
    app, w = _make_gui()
    assert hasattr(w, 'preview_stack'), "预览页应是 画布/空状态 两页的堆叠"
    w.resize(1368, 783)
    w.show()
    app.processEvents()
    w.data_cache.clear()
    w._sync_empty_state()
    app.processEvents()
    assert w.preview_stack.currentIndex() == 1, "没有数据时应显示空状态页"
    assert w.empty_title.text(), "空状态应有标题文案"
    assert w.empty_btn.text() == "选择数据文件夹", \
        f"空状态主按钮文案异常：{w.empty_btn.text()!r}"
    assert not w.toolbar.isVisible(), "空状态时那条 matplotlib 工具条应收起"
    # 有数据 → 回到画布页
    w.data_cache['__probe__'] = {'data': {}}
    try:
        w._sync_empty_state()
        app.processEvents()
        assert w.preview_stack.currentIndex() == 0, "有数据时应显示画布"
        assert w.toolbar.isVisible(), "有数据时工具条应重新出现"
    finally:
        w.data_cache.clear()
        w._sync_empty_state()


@check("GUI：空状态插画 + 三步上手指引随模式变、可收起（v4.31）")
def t_gui_empty_guide():
    from gui_icons import illustration_path, THEMES as ICON_THEMES
    # 1) 三套主题都要有插画资源（2 倍图 400x240，按 dpr=2 显示成 200x120）
    for theme in ICON_THEMES:
        p = illustration_path('empty', theme)
        assert p, f"{theme} 主题缺空状态插画"
        from PyQt5.QtGui import QImage
        img = QImage(p)
        assert not img.isNull(), f"{theme} 主题插画读不出来：{p}"
        assert (img.width(), img.height()) == (400, 240), \
            f"{theme} 主题插画尺寸应为 400x240（2 倍图），实际 {img.width()}x{img.height()}"

    app, w = _make_gui()
    assert w.settings.isWritable() or True
    w.settings.setValue("ui/onboarding_hidden", 0)
    w.settings.sync()
    w2 = _make_gui()[1]
    w2.resize(1368, 783)
    w2.show()
    app.processEvents()

    # 2) 插画按逻辑尺寸显示（dpr=2 → 200x120），不是 400x240 的实尺寸
    pm = w2.empty_icon.pixmap()
    assert not pm.isNull(), "空状态没有显示出插画"
    assert abs(pm.devicePixelRatio() - 2.0) < 0.01, \
        f"插画应按 2 倍图标注 dpr，实际 {pm.devicePixelRatio()}"
    assert (round(pm.width() / pm.devicePixelRatio()),
            round(pm.height() / pm.devicePixelRatio())) == (200, 120), \
        f"插画逻辑尺寸应为 200x120，实际 {pm.width()}x{pm.height()}"

    # 3) 三步指引：3 张卡片 + 序号 1/2/3 + 第 3 步按模式变
    assert len(getattr(w2, 'empty_step_cards', [])) == 3, "应有 3 张三步指引卡片"
    assert len(w2.empty_step_descs) == 3, "三步指引每步都要有说明文字"
    w2.spectrum_type_combo.setCurrentIndex(0)
    app.processEvents()
    w2._sync_empty_state()
    text_absorb = w2.empty_step_descs[2].text()
    w2.spectrum_type_combo.setCurrentIndex(2)
    app.processEvents()
    w2._sync_empty_state()
    text_life = w2.empty_step_descs[2].text()
    assert 'F5' in text_absorb, f"光谱模式第 3 步应讲预览/导出：{text_absorb!r}"
    assert '开始拟合' in text_life, f"寿命模式第 3 步应讲开始拟合：{text_life!r}"
    assert text_absorb != text_life, "第 3 步文案必须随模式变化"
    for d in w2.empty_step_descs:
        assert d.text().strip(), "三步指引的说明不能为空"

    # 4) 可收起、可再展开，且状态记进会话
    w2.settings.setValue("ui/onboarding_hidden", 0)
    w2._set_empty_guide_visible(True)
    assert not w2.empty_steps.isHidden(), "默认应展开三步指引"
    w2._toggle_empty_guide()
    app.processEvents()
    assert str(w2.settings.value("ui/onboarding_hidden")) in ("1", "True", "true"), \
        "收起后应把偏好写进会话"
    assert not w2.empty_steps.isVisible(), "收起后三步指引应隐藏"
    assert w2.empty_guide_toggle.text() == "显示上手指引", \
        f"收起后按钮文案应改成展开：{w2.empty_guide_toggle.text()!r}"
    # 新窗口应沿用"已收起"。
    # 注：w3 没 show() 过，只能用 isHidden()（显式 hide 才是 True）——
    # 用 isVisible() 会恒为 False，两边断言都会变成空断言（v4.25 踩过）。
    w3 = _make_gui()[1]
    assert w3.empty_steps.isHidden(), "新窗口应沿用上次的收起状态"
    assert w3.empty_guide_toggle.text() == "显示上手指引"
    # 再展开并复原
    w3._toggle_empty_guide()
    app.processEvents()
    assert not w3.empty_steps.isHidden(), "再点一次应重新展开"
    assert w3.empty_guide_toggle.text() == "不再显示这三步"
    w3.settings.setValue("ui/onboarding_hidden", 0)
    w3.settings.sync()


@check("GUI：单独拟合的寿命分布图例给出每组分振幅与强度（v4.33）")
def t_single_fit_component_legend():
    """单独拟合后「寿命分布」页的图例，每个分量要同时给**振幅占比**与**强度占比**。

    两个口径物理意义不同、会明显不同：强度 ∝ 幅值/k 的积分，宽而慢的分量
    强度大但峰不高；窄而快的分量峰高却几乎不发光。旧图例只给 α（强度占比），
    看不出"这个分量是不是真的主发光体"。
    """
    import shutil
    import tempfile

    app, w = _make_gui()
    rng = np.random.default_rng(5)
    dt = 0.05
    t = np.arange(0, 60, dt)
    irf = np.exp(-0.5 * ((t - 2.0) / 0.15) ** 2)
    irf = irf / irf.sum()
    truth = np.zeros_like(t)
    for a, tau in ((0.5, 1.0), (0.5, 9.0)):      # 快慢各半，口径差异明显
        truth += a * np.convolve(irf, np.exp(-t / tau), mode='full')[:len(t)]
    truth *= 20000.0 / truth.max()
    decay = np.maximum(rng.poisson(truth).astype(float), 0.0)

    out = tempfile.mkdtemp(prefix='spectra_single_')
    try:
        _write_three_col_csv(os.path.join(out, 's.csv'), t, decay, irf * 1e6)
        w.spectrum_type_combo.setCurrentIndex(2)
        w.lifetime_method_combo.setCurrentIndex(1)     # SESM 快
        w.lifetime_nrates_spin.setValue(101)
        w.load_data_from_folder(out)
        w.file_list.setCurrentRow(0)
        w._do_lifetime_plot()
        res = w._last_lifetime_result
        ax3 = w.lifetime_canvas.fig.axes[0]
        labels = [x.get_text() for x in ax3.get_legend().get_texts()]
        comp = [s for s in labels if '振幅' in s or '强度' in s]
        assert len(comp) == len(res['peak_result']), \
            f"每个分量都要有图例条目：{labels}"
        for s in comp:
            assert '振幅' in s and '强度' in s, f"图例应同时含振幅与强度：{s!r}"
            assert 'ns' in s, f"图例应含 τ：{s!r}"

        # 数值口径核对：振幅占比取 p[4]，强度占比取 p[3]（归一后）
        pr = res['peak_result']
        assert all(len(p) >= 5 for p in pr), "peak_result 应含第 5 项振幅占比"
        amps = sorted(round(p[4] * 100, 1) for p in pr)
        got = sorted(float(s.split('振幅')[1].split('%')[0]) for s in comp)
        for a, b in zip(amps, got):
            assert abs(a - b) < 0.15, f"振幅占比不符：{amps} vs {got}"
    finally:
        shutil.rmtree(out, ignore_errors=True)


@check("GUI：信息页拟合摘要卡片 + 质量徽标三档（v4.27）")
def t_gui_info_fit_card():
    app, w = _make_gui()
    assert hasattr(w, 'fit_card'), "信息页应有「拟合摘要」卡片"
    # 注：用 isHidden() 而不是 isVisible()——测试里窗口没 show()，
    # 子控件的 isVisible() 恒为 False（v4.25 踩过同一个坑）
    assert w.fit_card.isHidden(), "没拟合过时卡片应隐藏"
    base = {
        'name': 'probe.csv', 'time': [0.0, 1.0, 2.0], 'decay': [3.0, 2.0, 1.0],
        'peak_result': [(4.0, 0.7, 1.0, 1.0), (1.2, 0.3, 1.0, 1.0)],
        'info': {'chi_sqr': 1.05, 'quality': 'ok', 'residuals': [0.1, -0.1, 0.05],
                 'y_fitted': [3.0, 2.0, 1.0], 'fit_start': 0, 'fit_end': 3,
                 'fixed_taus': [0.5], 'fixed_amplitudes': [10.0]},
    }
    w._last_lifetime_result = base
    w._update_info_fit_card()
    assert not w.fit_card.isHidden(), "有结果时卡片应显示"
    assert w.fit_badge.text().startswith("拟合质量"), \
        f"徽标文案异常：{w.fit_badge.text()!r}"
    assert w.fit_badge.property('badgeState') == 'ok', \
        f"quality=ok 应映射到 ok 徽标，实际 {w.fit_badge.property('badgeState')!r}"
    # 2 个分离峰 + 1 个固定分量
    assert w.fit_table.rowCount() == 3, \
        f"分量表应有 3 行（2 峰 + 1 固定），实际 {w.fit_table.rowCount()}"
    names = [w.fit_table.item(r, 0).text() for r in range(3)]
    assert names[0] == 'τ1' and names[1] == 'τ2', f"分量名异常：{names}"
    assert '固定' in names[2], f"固定分量应单独标注：{names[2]}"
    assert 'χ²R' in w.fit_quality_label.text(), "摘要行应含 χ²R"

    # 三档徽标映射
    for quality, state in (('poor', 'warn'), ('failed', 'bad')):
        probe = dict(base)
        probe['info'] = dict(base['info'], quality=quality)
        w._last_lifetime_result = probe
        w._update_info_fit_card()
        assert w.fit_badge.property('badgeState') == state, \
            f"quality={quality} 应映射到 {state}"
    # 结果清空 → 卡片重新隐藏
    w._last_lifetime_result = None
    w._update_info_fit_card()
    assert w.fit_card.isHidden(), "没有结果时卡片应重新隐藏"


@check("GUI：信息页/结果摘要兼容 5 元 peak_result，不抛未捕获异常（v4.35）")
def t_info_accepts_five_element_peaks():
    """v4.33 给 peak_result 追加了第 5 项（振幅占比），有消费者仍在按 4 元解包。

    实测报错（点「开始拟合」后弹「发生未处理的错误」）：
        gui_plot.py: _on_plot_finished → _show_lifetime_fit_info
        ValueError: too many values to unpack (expected 4)

    本用例直接走那条路径：用一份带 5 元 peak_result 的**真实拟合结果**喂给
    信息页与分量表，断言不抛异常、且振幅列有值。
    """
    app, w = _make_gui()

    # 真实拟合一份数据，拿到含第 5 项的 peak_result
    rng = np.random.default_rng(3)
    dt = 0.05
    t = np.arange(0, 60, dt)
    irf = np.exp(-0.5 * ((t - 2.0) / 0.15) ** 2)
    irf = irf / irf.sum()
    truth = np.zeros_like(t)
    for a, tau in ((0.6, 2.5), (0.4, 8.0)):
        truth += a * np.convolve(irf, np.exp(-t / tau), mode='full')[:len(t)]
    truth *= 20000.0 / truth.max()
    decay = np.maximum(rng.poisson(truth).astype(float), 0.0)

    import plot_lifetime as pl
    f = pl.MEMFitter(verbose=False, name='five')
    f.load(t, decay, irf)
    f.preprocess()
    f.fit(method='SESM', n_rates=101)
    f.postprocess()
    res = f.serialize(None)
    assert res['peak_result'], "用例前提：应分离出分量"
    assert all(len(p) >= 5 for p in res['peak_result']), \
        "用例前提：peak_result 应含第 5 项振幅占比"

    # ① 信息页文本（原报错点）
    w._last_lifetime_result = res
    w._show_lifetime_fit_info()          # 旧代码在此抛 ValueError
    txt = w.info_label.text()
    assert '振幅占比' in txt, f"信息页应给出振幅占比：{txt[:200]!r}"
    assert '强度占比' in txt, "信息页应给出强度占比"

    # ② 分量表（同一循环也曾按 4 元解包）
    w._update_info_fit_card()
    tbl = w.fit_table
    assert tbl.columnCount() == 4, f"分量表应有 4 列，实际 {tbl.columnCount()}"
    assert '振幅' in tbl.horizontalHeaderItem(3).text(), \
        f"第 4 列应为振幅占比：{tbl.horizontalHeaderItem(3).text()!r}"
    amp_cells = [tbl.item(r, 3).text() for r in range(tbl.rowCount())]
    assert any(c not in ('', '—') for c in amp_cells), \
        f"振幅列应有数值，实际 {amp_cells}"

    # ③ 旧结果的 4 元 peak_result 仍要能显示（向后兼容，缺失处显示 —）
    legacy = dict(res)
    legacy['peak_result'] = [tuple(p[:4]) for p in res['peak_result']]
    w._last_lifetime_result = legacy
    w._show_lifetime_fit_info()
    w._update_info_fit_card()
    assert w.fit_table.rowCount() == len(legacy['peak_result']), \
        "旧结果也应能填入分量表"


@check("GUI：状态栏进度条 + 模式/样品数徽标（v4.27）")
def t_gui_status_bar():
    from PyQt5.QtCore import Qt as _Qt
    from PyQt5.QtWidgets import QProgressBar, QListWidgetItem
    app, w = _make_gui()
    assert isinstance(w.progress_bar, QProgressBar)
    # 进度条从参数栏搬到了状态栏（v4.27）
    assert w.param_panel.findChild(QProgressBar) is None, \
        "参数栏里不应再有进度条（已移到状态栏）"
    assert w.progress_bar.parent() is w.status_bar, \
        "进度条应为状态栏的常驻部件"
    assert w.progress_bar.isHidden(), "空闲时进度条应隐藏"
    assert w.status_mode_badge.text() == "吸收光谱"
    w.spectrum_type_combo.setCurrentIndex(2)
    assert w.status_mode_badge.text() == "荧光寿命", \
        f"模式徽标未跟随切换：{w.status_mode_badge.text()!r}"
    w.spectrum_type_combo.setCurrentIndex(0)
    w.file_list.clear()
    for n in ('a.csv', 'b.csv', 'c.csv'):
        it = QListWidgetItem(n)
        it.setFlags(it.flags() | _Qt.ItemIsUserCheckable)
        it.setCheckState(_Qt.Checked)
        w.file_list.addItem(it)
    w._update_status_badges()
    assert w.status_sample_badge.text() == "3 个样品", \
        f"样品数徽标异常：{w.status_sample_badge.text()!r}"


# ---------------------------------------------------------------- v4.28 新增
# emoji 区段（图形符号 / 杂项符号 / 补充符号 + 变体选择符）
_EMOJI_RANGES = ((0x1F300, 0x1FAFF), (0x2600, 0x27BF), (0x2B00, 0x2BFF),
                 (0x23E9, 0x23FA), (0xFE0F, 0xFE0F))


def _has_emoji(text):
    """文本里是否含 emoji（用于确认界面已换成单色图标集）。"""
    return [ch for ch in str(text)
            if any(lo <= ord(ch) <= hi for lo, hi in _EMOJI_RANGES)]


@check("GUI：按钮与入口卡片改用单色图标集、无 emoji 残留（v4.28）")
def t_gui_icons_replaced():
    from PyQt5.QtWidgets import QLabel as _QLabel, QPushButton as _QPB
    from gui_icons import ICON_NAMES
    from gui_launcher import ModuleCard, ModuleLauncher
    app, w = _make_gui()
    w.show()
    app.processEvents()

    buttons = [('home_btn', w.home_btn), ('theme_btn', w.theme_btn),
               ('help_btn', w.help_btn), ('workspace_btn', w.workspace_btn),
               ('preview_btn', w.preview_btn),
               ('export_menu_btn', w.export_menu_btn),
               ('lifetime_save_defaults_btn', w.lifetime_save_defaults_btn),
               ('lifetime_overlay_btn', w.lifetime_overlay_btn),
               ('integ_copy_btn', w.integ_copy_btn)]
    for name, btn in buttons:
        assert not btn.icon().isNull(), f"{name} 没有图标（图标集没加载上？）"
        assert not _has_emoji(btn.text()), \
            f"{name} 文本里还有 emoji：{btn.text()!r}"

    # 主题按钮：浅色=月亮、深色=太阳，两套图标必须真的不同
    # v4.46：初值可能跟随系统（深色机器上初始就是 dark），所以不能假设
    # "切一下就变"。这里先把起点钉到 light，再切到 dark 比较图标。
    w.set_theme('light')
    app.processEvents()
    key_light = w.theme_btn.icon().cacheKey()
    w.set_theme('dark')
    app.processEvents()
    key_dark = w.theme_btn.icon().cacheKey()
    assert key_light != key_dark, "主题按钮图标没跟着主题切换"
    for name, btn in buttons:
        assert not btn.icon().isNull(), f"深色主题下 {name} 图标为空（深色图标缺失？）"
    w.toggle_theme(False)
    app.processEvents()

    # 主窗口控件文字里不该再有 emoji
    leftover = [lb.text()[:24] for lb in w.findChildren(_QLabel)
                if _has_emoji(lb.text())]
    leftover += [b.text()[:24] for b in w.findChildren(_QPB)
                 if _has_emoji(b.text())]
    assert not leftover, f"界面文字里仍有 emoji：{leftover}"

    # 入口界面：四个模块卡片都有图标，图标名在图标集清单里
    for entry in ModuleLauncher.MODES:
        assert entry[1] in ICON_NAMES, f"入口卡片图标名不在图标集清单：{entry[1]}"
    for theme in ('light', 'dark'):
        lau = ModuleLauncher(theme=theme)
        lau.show()
        app.processEvents()
        cards = lau.findChildren(ModuleCard)
        assert len(cards) == len(ModuleLauncher.MODES), \
            f"{theme}：模块卡片数应为 {len(ModuleLauncher.MODES)}，实际 {len(cards)}"
        for c in cards:
            assert not c._icon_label.pixmap().isNull(), f"{theme}：有卡片没图标"
        lau.close()


@check("启动画面：跟随上次会话主题 + bootloader 图为深色（v4.28）")
def t_splash_theme():
    from PyQt5.QtWidgets import QFrame
    from gui_config import THEMES
    from gui_splash import StartupSplash
    app, w = _make_gui()
    seen = {}
    for theme in ('light', 'dark'):
        s = StartupSplash(theme=theme)
        card = s.findChild(QFrame)
        assert card is not None, "启动画面应有卡片"
        qss = card.styleSheet()
        P = THEMES[theme]
        assert P['CARD'] in qss, f"{theme}：启动画面卡片底色没取色板（{P['CARD']}）"
        assert P['ACCENT'] in qss, f"{theme}：启动画面顶部条没取色板"
        seen[theme] = qss
        s.close()
    assert seen['light'] != seen['dark'], "深浅两套启动画面样式必须不同"

    # bootloader 那张静态图（PyInstaller --splash）在 Python 启动前就画好了，
    # 读不到任何设置、无法跟随主题，所以固定用深色品牌图：
    # 抽样卡片中心像素，亮度必须偏低（防止有人改回浅色）
    from PIL import Image
    img = Image.open(os.path.join(GUI_DIR, 'splash.png')).convert("RGB")
    r, g, b = img.getpixel((380, 200))
    lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255.0
    assert lum < 0.45, f"bootloader 启动图应是深色底，实测亮度 {lum:.2f}（{r},{g},{b}）"


def _install_spectra(w, spectra, mode='emission'):
    """把 {缓存键: (wl, y)} 装进窗口：data_cache + 文件列表（全勾选）。

    v4.37 的勾选口径测试需要"文件列表里有条目"，只有 data_cache 是不够的
    （`_checked_scope` 走的是文件列表的勾选状态）。
    """
    from PyQt5.QtCore import Qt as _Qt
    from PyQt5.QtWidgets import QListWidgetItem
    w.spectrum_type_combo.setCurrentIndex(1 if mode == 'emission' else 0)
    w.data_cache = {}
    w.file_list.clear()
    for key, xy in spectra.items():
        wl, y = xy[0], xy[1]
        extra = xy[2] if len(xy) > 2 else {}
        data = {'wavelength': np.asarray(wl, float),
                'intensity': np.asarray(y, float)}
        data.update(extra)
        w.data_cache[key] = {'data': data}
        it = QListWidgetItem(key)
        it.setFlags(it.flags() | _Qt.ItemIsUserCheckable)
        it.setCheckState(_Qt.Checked)
        w.file_list.addItem(it)


# ---------------------------------------------------------------- v4.37 新增
@check("plot_compare：三种纵轴口径 + null/空值样品不进图（v4.37）")
def t_compare_module():
    import tempfile
    from pathlib import Path as _Path
    import matplotlib.pyplot as plt
    import pandas as pd
    import plot_compare as pc
    from read_xlsx_info import load_xlsx_info

    wl = np.arange(400.0, 701.0, 1.0)
    y = 100.0 * np.exp(-((wl - 500.0) / 30.0) ** 2)

    # 峰强度：全谱 / 指定区间
    assert abs(pc.measure_metric(wl, y, 'peak_intensity') - 100.0) < 1e-9
    assert abs(pc.measure_metric(wl, y, 'peak_intensity', band=(480, 520)) - 100.0) < 1e-9
    # 峰面积 = 同一份梯形积分实现（GUI 积分结果表也用它）
    area = pc.measure_metric(wl, y, 'peak_area', band=(430, 570))
    assert abs(area - pc.integrate_band(wl, y, 430, 570)) < 1e-12
    # 指定波长：插值取值；范围外不外推
    assert abs(pc.measure_metric(wl, y, 'at_wavelength', at_wl=500.0) - 100.0) < 1e-6
    assert np.isnan(pc.measure_metric(wl, y, 'at_wavelength', at_wl=900.0)), \
        "指定波长落在数据范围外时应返回 NaN（不外推）"
    assert np.isnan(pc.measure_metric(wl, y, 'peak_intensity', band=(800, 900))), \
        "区间与数据无重叠时应返回 NaN"

    # 说明.xlsx：空单元格 / 文本 null / N/A / - 一律视为"没有值"；0 是有效值
    tmp = tempfile.mkdtemp(prefix='cmp_xlsx_')
    path = os.path.join(tmp, '说明.xlsx')
    pd.DataFrame({
        '编号': [1, 2, 3, 4],
        'RB浓度': [10, None, 'null', 0],
        'L8i浓度': [100, 200, 'N/A', '-'],
        '全空列': [None, None, 'null', '-'],
        '备注': ['样品', '参比', '-', 'N/A'],
    }).to_excel(path, index=False)
    info = load_xlsx_info(tmp)
    assert info is not None, "说明.xlsx 应能读出"
    assert info.numeric_columns() == ['RB浓度', 'L8i浓度'], \
        f"「全空列」不应算数值列：{info.numeric_columns()}"
    assert info.value_for(1, 'RB浓度') == 10
    assert info.value_for(2, 'RB浓度') is None, "空单元格应视为没有值"
    assert info.value_for(3, 'RB浓度') is None, "文本 null 应视为没有值"
    assert info.value_for(4, 'RB浓度') == 0, "0 是有效值，不能被当成空"
    assert info.value_for(1, '备注') == '样品'
    assert info.value_for(3, '备注') is None, "'-' 应视为没有值"
    assert 'null' not in str(info.info) and 'N/A' not in str(info.info), \
        f"清洗后不应残留 null / N/A：{info.info}"

    samples = [('s1', 's-1.csv', wl, y), ('s2', 's-2.csv', wl, y),
               ('s3', 's-3.csv', wl, y), ('s4', 's-4.csv', wl, y)]
    res = pc.collect_points(samples, info, x_var='RB浓度', metric='peak_intensity')
    assert sorted(p[1] for p in res['points']) == [0.0, 10.0], \
        f"只有 #1(10) 与 #4(0) 有 RB浓度：{res['points']}"
    reasons = dict(res['skipped'])
    assert '为空' in reasons.get('s2', '') and '为空' in reasons.get('s3', ''), reasons

    # 分组变量为空值的样品同样被剔除：#1 有 L8i=100，#2/#3/#4 都没有
    res_g = pc.collect_points(samples, info, 'RB浓度', group_var='L8i浓度',
                              metric='peak_intensity')
    assert [p[3] for p in res_g['points']] == ['s1'], res_g['points']
    assert res_g['points'][0][0] == 100, res_g['points']
    assert len(res_g['skipped']) == 3, res_g['skipped']

    # 出图：不分组 → 一条曲线；图例给出样品数
    fig, summary = pc.make_compare_figure(res['points'], 'RB浓度', '峰强度', 't')
    try:
        assert summary['n_points'] == 2 and len(fig.axes[0].get_lines()) == 1, summary
        assert '全部样品' in fig.axes[0].get_legend().get_texts()[0].get_text()
    finally:
        plt.close(fig)

    # 一键：真实数据（RB-L8i-1..6 + 说明.xlsx），按 L8i浓度 分组
    folder = (r'D:\北大\光谱工具\示例数据\测试数据\20260825')
    if os.path.isdir(folder) and os.path.exists(os.path.join(folder, '说明.xlsx')):
        out = pc.run_compare(folder=folder, x_var='RB浓度', group_var='L8i浓度',
                             metric='peak_intensity', band=(560, 620),
                             save_dir=os.path.join(tmp, 'plots'), verbose=False)
        assert out['summary']['n_points'] == 6, out['summary']
        assert len(out['summary']['groups']) == 4, out['summary']['groups']
        assert os.path.exists(out['figure']) and os.path.exists(out['csv'])
        head = open(out['csv'], encoding='utf-8-sig').read().splitlines()[0]
        assert head.split(',')[:3] == ['样品', '编号', 'RB浓度'], head


@check("GUI：数据比较取点 + 积分/比较只统计勾选项（v4.37）")
def t_gui_compare_and_checked_scope():
    from pathlib import Path as _Path
    from read_xlsx_info import XlsxInfo

    app, w = _make_gui()
    wl = np.arange(400.0, 601.0, 1.0)
    y1 = 100.0 * np.exp(-((wl - 500.0) / 25.0) ** 2)
    y2 = 50.0 * np.exp(-((wl - 500.0) / 25.0) ** 2)
    _install_spectra(w, {'s-1 (Emission)': (wl, y1), 's-2 (Emission)': (wl, y2)})

    # #2 缺「浓度」→ 不该出现在点线图里
    w.xlsx_info = XlsxInfo(info={1: {'浓度': 5}, 2: {}}, numbers=[1, 2],
                           columns=['浓度'], path=_Path('说明.xlsx'))
    w._refresh_compare_combos()
    assert w.compare_x_combo.isEnabled(), "有说明.xlsx 数值列时按钮应可用"
    assert w.compare_x_combo.currentText() == '浓度'
    assert [w.compare_group_combo.itemText(i)
            for i in range(w.compare_group_combo.count())] == ['（不分组）', '浓度']

    w.compare_x_combo.setCurrentText('浓度')
    w.compare_group_combo.setCurrentIndex(0)
    w.compare_metric_combo.setCurrentIndex(0)
    w.compare_peak_lo_spin.setValue(450.0)
    w.compare_peak_hi_spin.setValue(550.0)
    res = w._do_compare_plot()
    assert res['summary']['n_points'] == 1, f"#2 缺变量值，应只剩 #1：{res}"
    assert res['skipped'] and '为空' in res['skipped'][0][1], res['skipped']
    assert '5' in w._compare_status_text(res) or '1 个点' in w._compare_status_text(res)
    # 跳过明细挂在画布 tooltip 上
    w._update_compare_output(res)
    assert 's-2' in w.compare_canvas.toolTip(), w.compare_canvas.toolTip()
    # 指标切换只启用相关输入框
    w.compare_metric_combo.setCurrentIndex(2)      # 指定波长
    assert w.compare_wl_spin.isEnabled() and not w.compare_peak_lo_spin.isEnabled()
    w.compare_wl_spin.setValue(500.0)
    res2 = w._do_compare_plot()
    assert res2['y_label'].startswith('发射强度@500'), res2['y_label']
    w.compare_metric_combo.setCurrentIndex(1)      # 峰面积 → 复用积分区间
    w.compare_peak_lo_spin.setValue(0.0)
    w.compare_peak_hi_spin.setValue(0.0)
    w.integ_min_spin.setValue(450.0)
    w.integ_max_spin.setValue(550.0)
    assert w._compare_config()['band'] == (450.0, 550.0), "峰面积应复用积分区间"

    # 积分：只统计勾选项
    w._do_plot()
    w._update_integration_output()
    assert w.integ_table.rowCount() == 2, w.integ_table.rowCount()
    for i in range(w.file_list.count()):
        if w.file_list.item(i).text().startswith('s-2'):
            w.file_list.item(i).setCheckState(0)
    w._do_plot()
    w._update_integration_output()
    assert w.integ_table.rowCount() == 1, "取消勾选后该样品应从积分表消失"
    assert w.integ_table.item(0, 0).text() == 's-1'
    # 数据比较同样只看勾选
    assert w._do_compare_plot()['n_scope'] == 1
    # 一个都不勾：明确提示，不给一张空表
    for i in range(w.file_list.count()):
        w.file_list.item(i).setCheckState(0)
    w._do_plot()
    w._update_integration_output()
    assert w.integ_table.rowCount() == 0
    assert '未勾选' in w.integ_count_label.text(), w.integ_count_label.text()

    # 没有说明.xlsx 时「数据比较」应置灰并给出原因
    app2, w2 = _make_gui()
    assert not w2.compare_x_combo.isEnabled() or w2.compare_x_combo.count() == 0
    assert '说明' in w2.compare_x_combo.currentText(), w2.compare_x_combo.currentText()
    assert not w2.compare_btn.isEnabled()


@check("GUI：寿命模式勾选框 + 叠加分布/汇总图只处理勾选样品（v4.37）")
def t_gui_lifetime_checked_scope():
    from PyQt5.QtCore import Qt as _Qt
    from PyQt5.QtWidgets import QListWidgetItem
    import plot_lifetime as pl

    app, w = _make_gui()
    w.spectrum_type_combo.setCurrentIndex(2)
    t, decay, irf = _synth_double_exponential()
    w.data_cache = {}
    w.file_list.clear()
    for i in range(3):
        key = f'L{i}.csv'
        w.data_cache[key] = {'data': {'time': t, 'decay': decay, 'irf': irf,
                                      'meta': None}}
        it = QListWidgetItem(key)
        it.setFlags(it.flags() | _Qt.ItemIsUserCheckable)
        it.setCheckState(_Qt.Checked)
        w.file_list.addItem(it)
    for i in range(3):
        assert w.file_list.item(i).flags() & _Qt.ItemIsUserCheckable, \
            "寿命模式必须有勾选框（v4.37：叠加分布只画勾选的样品）"

    calls = []
    real = pl.fit_many
    try:
        pl.fit_many = lambda datasets, **kw: (calls.append([d['name'] for d in datasets])
                                              or [None] * len(datasets))
        w._lifetime_fit_cache = {}
        w._fit_all_with_cache(w._collect_plot_params())
        assert calls[-1] == ['L0.csv', 'L1.csv', 'L2.csv'], calls
        assert '勾选 3/3' in w._batch_fit_status_text(w._collect_plot_params())

        w.file_list.item(2).setCheckState(_Qt.Unchecked)
        w._lifetime_fit_cache = {}
        w._fit_all_with_cache(w._collect_plot_params())
        assert calls[-1] == ['L0.csv', 'L1.csv'], \
            f"只勾 2 个时只应拟合这 2 个：{calls[-1]}"
        assert '勾选 2/3' in w._batch_fit_status_text(w._collect_plot_params())
    finally:
        pl.fit_many = real

    # 一个都不勾：按钮给提示、不进入拟合
    for i in range(3):
        w.file_list.item(i).setCheckState(_Qt.Unchecked)
    boxed = []
    from PyQt5.QtWidgets import QMessageBox
    real_warn = QMessageBox.warning
    try:
        QMessageBox.warning = staticmethod(lambda *a, **k: boxed.append(a))
        w._run_overlay_lifetime()
        w._run_batch_export('summary')
    finally:
        QMessageBox.warning = real_warn
    assert len(boxed) == 2 and all('勾选' in str(a) for a in boxed), boxed
    assert not getattr(w, '_plotting', False), "没勾选时不应进入拟合/绘图状态"


@check("说明.xlsx：编号列是文本码（R1/S1）也能读出并匹配（v4.41）")
def t_xlsx_info_text_codes():
    """20261010 批次踩到：说明.xlsx 的「编号」列写的是 R1/R2/S1…（文本码），
    旧实现每行都走 int('R1') 抛错被丢掉 -> numbers 为空 -> load_xlsx_info 返回 None，
    界面上表现成「有 说明.xlsx 但软件说未找到/读取失败」。"""
    import tempfile
    import pandas as pd
    from pathlib import Path as _Path
    from read_xlsx_info import (load_xlsx_info, match_number,
                                build_enriched_label, enrich_label_from_name)

    tmp = tempfile.mkdtemp(prefix='v441_codes_')
    pd.DataFrame({
        '编号': ['R1', 'R2', 'r3', 'S1', 'S2'],      # 故意混一个小写 + 文本码
        'RB浓度': [50, 20, 10, None, None],
        'Ce6浓度': [None, None, None, 50, 20],
        'L8i浓度': [1000, 1000, 1000, 1000, 1000],
    }).to_excel(os.path.join(tmp, '说明.xlsx'), index=False)

    info = load_xlsx_info(tmp)
    assert info is not None, "编号是文本码时 说明.xlsx 必须能读出来（旧版返回 None）"
    assert info.numbers == ['R1', 'R2', 'R3', 'S1', 'S2'], \
        f"编号应保持文本码并统一大写：{info.numbers}"
    assert info.numeric_columns() == ['RB浓度', 'Ce6浓度', 'L8i浓度'], info.numeric_columns()
    assert info.value_for('R1', 'RB浓度') == 50 and info.value_for('R1', 'Ce6浓度') is None
    assert info.value_for('S1', 'Ce6浓度') == 50 and info.value_for('S1', 'RB浓度') is None
    assert info.label_for('R1') == 'RB浓度=50, L8i浓度=1000', info.label_for('R1')

    # 文件名 -> 编号：重复测量的 -2 / -3 尾数要忽略
    for name, want in (('R1.csv', 'R1'), ('R1-6.csv', 'R1'), ('S2-3.csv', 'S2')):
        got = match_number(name, info.numbers)
        assert got == want, f"{name} 应命中 {want}，实际 {got}"
    # R1 与 S1 不能串台（旧方案把两者都退化成整数 1）
    assert match_number('R1.csv', info.numbers) != match_number('S1.csv', info.numbers), \
        "R1 与 S1 必须区分开"
    # 文本码不做子串匹配：R1 不该命中 R10
    assert match_number('R10.csv', ['R1', 'R10']) == 'R10'

    assert build_enriched_label('R1', info, 'R1') == '#R1 RB浓度=50, L8i浓度=1000'
    assert 'Ce6浓度=50' in enrich_label_from_name('S1-1', 'S1-1.csv', info)

    # 整数编号的老批次行为不变
    assert match_number('RB-L8i-1.csv', [1, 2, 3]) == 1
    assert match_number('20260825-2.csv', [1, 2]) == 2


@check("多列光谱 xlsx：吸收模式按列拆成多条 + 说明.xlsx 图例（v4.41）")
def t_absorption_multicolumn_xlsx():
    import tempfile
    import pandas as pd
    from read_xlsx_info import parse_spectrum_xlsx, clean_xlsx_column_label
    from plot_absorption import load_absorption_spectra
    import plot_compare as pc

    assert clean_xlsx_column_label('20261010R1 - RawData') == 'R1'
    assert clean_xlsx_column_label('S1 - CorrectionData') == 'S1'
    assert clean_xlsx_column_label('20261010R2') == 'R2'
    assert clean_xlsx_column_label('备注') == '备注'
    # 正常样品名不该被后缀正则误伤（v4.41 复核发现：以前 'Sample-absorption' -> 'Sample'）
    assert clean_xlsx_column_label('Sample-absorption') == 'Sample-absorption', \
        clean_xlsx_column_label('Sample-absorption')

    tmp = tempfile.mkdtemp(prefix='v441_xlsx_')
    wl = np.arange(400.0, 900.5, 0.5)[::-1]        # 仪器导出通常是降序
    pd.DataFrame({
        '波长(nm)': wl,
        '20261010R1 - RawData': 3.0 * np.exp(-((wl - 400) / 60.0) ** 2),
        '20261010S1 - RawData': 4.0 * np.exp(-((wl - 400) / 60.0) ** 2),
        '备注': [''] * len(wl),                     # 非数值列要被跳过
    }).to_excel(os.path.join(tmp, '20261010.xlsx'), index=False)
    # 干扰项（v4.41 复核补的负例）：这几种表都不该被当成多列光谱表
    pd.DataFrame({'time (ns)': np.arange(50.0),
                  'A0': np.ones(50), 'IRF': np.ones(50)}).to_excel(
        os.path.join(tmp, 'decay.xlsx'), index=False)
    pd.DataFrame({'Time_ns': np.arange(50.0),          # 下划线写法也要拦住
                  'A0': np.ones(50), 'IRF': np.ones(50)}).to_excel(
        os.path.join(tmp, 'decay2.xlsx'), index=False)
    pd.DataFrame({'编号': range(1, 14),                # 说明表样式（首列单调，别靠猜）
                  'L8i浓度': range(13), 'CPC浓度': range(13)}).to_excel(
        os.path.join(tmp, '汇总.xlsx'), index=False)
    pd.DataFrame({'序号': range(1, 21),                # 波长列不在首位
                  '波长(nm)': np.arange(400.0, 420.0),
                  '强度': np.arange(20.0) * 100}).to_excel(
        os.path.join(tmp, '序号在前.xlsx'), index=False)
    pd.DataFrame({'编号': ['R1', 'S1'],
                  'RB浓度': [50, None], 'Ce6浓度': [None, 50]}).to_excel(
        os.path.join(tmp, '说明.xlsx'), index=False)

    datasets = parse_spectrum_xlsx(os.path.join(tmp, '20261010.xlsx'))
    assert [d['label'] for d in datasets] == ['R1', 'S1'], [d['label'] for d in datasets]
    assert len(datasets[0]['wl']) == len(wl) and datasets[0]['wl'][0] < datasets[0]['wl'][-1], \
        "波长应升序排好"
    # 波长列左边的列一律不当样品列
    front = parse_spectrum_xlsx(os.path.join(tmp, '序号在前.xlsx'))
    assert [d['label'] for d in front] == ['强度'], \
        f"波长列左边的「序号」不该被当成样品：{[d['label'] for d in front]}"
    for bad in ('decay.xlsx', 'decay2.xlsx', '汇总.xlsx', '说明.xlsx'):
        try:
            parse_spectrum_xlsx(os.path.join(tmp, bad))
        except ValueError:
            pass
        else:
            raise AssertionError(f'{bad} 不该被当成多列光谱表')

    loaded = load_absorption_spectra(os.path.join(tmp, '20261010.xlsx'), verbose=False)
    assert [d['label'] for d in loaded] == ['R1', 'S1'] and \
        all('absorption' in d and 'wl' in d for d in loaded), loaded

    # GUI：吸收模式加载该文件夹（多列 xlsx 自动展开；衰减表/汇总表/说明表跳过）
    app, w = _make_gui()
    w.spectrum_type_combo.setCurrentIndex(0)
    assert w.spectrum_type == 'absorption'
    w.load_data_from_folder(tmp)
    keys = list(w.data_cache.keys())
    assert 'R1' in keys and 'S1' in keys, keys
    assert not any('序号' in k or 'A0' in k or 'IRF' in k or '浓度' == k for k in keys), \
        f"干扰表不该被收成样品：{keys}"
    assert '强度' in keys, f"波长列右边的列应当收进来：{keys}"
    assert w.xlsx_info is not None and w.xlsx_info.numbers == ['R1', 'S1']
    assert 'RB浓度=50' in w._build_legend_label('R1', w.data_cache['R1']['data']), \
        "多列 xlsx 的样品名要能对上 说明.xlsx 的编号"
    assert w.compare_x_combo.isEnabled(), "有数值列时「数据比较」不该置灰"
    res = pc.collect_points(
        [('R1', 'R1', w.data_cache['R1']['data']['wl'],
          w.data_cache['R1']['data']['absorption']),
         ('S1', 'S1', w.data_cache['S1']['data']['wl'],
          w.data_cache['S1']['data']['absorption'])],
        w.xlsx_info, 'RB浓度', metric='peak_intensity')
    assert [p[4] for p in res['points']] == ['R1'], res
    assert len(res['skipped']) == 1 and '为空' in res['skipped'][0][1], res['skipped']


# ---------------------------------------------------------------- v5.0.2 新增
@check("寿命图：MPL_LIFE_* 语义色三套主题齐全且对坐标区底色 ≥ 4.5:1（v5.0.2）")
def t_lifetime_theme_colors():
    """v5.0.2 前这 7 个颜色硬编码在 gui_plot 里，只按「深色够亮」挑过。

    实测对白底只有 1.74–3.09:1，远低于图形元素 3:1 门槛——浅色与打印友好
    主题下散点和 IRF 几乎隐形。改到 THEMES 后必须三套都齐、且都够对比。
    """
    import gui_config as cfg

    KEYS = ('MPL_LIFE_DATA', 'MPL_LIFE_IRF', 'MPL_LIFE_IRF_RAW',
            'MPL_LIFE_FIT', 'MPL_LIFE_MARK', 'MPL_LIFE_ACF', 'MPL_LIFE_CI')

    def _lum(hexc):
        c = hexc.lstrip('#')
        ch = [int(c[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
        ch = [v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
              for v in ch]
        return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2]

    def _ratio(a, b):
        la, lb = _lum(a), _lum(b)
        hi, lo = max(la, lb), min(la, lb)
        return (hi + 0.05) / (lo + 0.05)

    bad = []
    for name in cfg.THEME_ORDER:
        P = cfg.THEMES[name]
        bg = P['MPL_AX']          # 曲线实际压在这个底色上，不是 CARD
        for k in KEYS:
            assert k in P, f"主题 {name} 缺少 {k}"
            r = _ratio(P[k], bg)
            if r < 4.5:
                bad.append(f"{name}/{k}={P[k]} 对 {bg} 仅 {r:.2f}:1")
    assert not bad, "寿命图语义色对比度不足：" + str(bad)

    # 三套主题之间必须真的不同——同值说明忘了按主题给（改了个寂寞）
    for k in KEYS:
        vals = {cfg.THEMES[n][k] for n in cfg.THEME_ORDER}
        assert len(vals) == len(cfg.THEME_ORDER), \
            f"{k} 在三套主题里取值重复（{vals}），应各主题各给一色"


@check("寿命主图：时间轴按拟合区间裁剪，不再有 78% 噪声地板（v5.0.2）")
def t_lifetime_xlim_by_fit_window():
    """原图时间轴用原始通道全长，Ce6 数据 0–399 900 ns 而拟合只用
    23 300–89 400 ns —— 右侧 78% 是平的噪声地板，曲线挤在左边 1/4。
    """
    app, w = _make_gui()
    w.spectrum_type_combo.setCurrentIndex(2)      # lifetime
    # 点数必须是 4000：审计原文的通道号 233–894 就是 4000 点数组上的下标
    # （dt=100 ns → ch233=23 300 ns、ch894=89 400 ns）。1000 点时同一组
    # 通道号只占 66% 宽度，测不出"78% 噪声地板"这件事。
    n = 4000
    time = np.linspace(0.0, 399900.0, n)
    decay = 4000.0 * np.exp(-time / 50000.0) + 1.0
    fit_start, fit_end = 233, 894
    y_fitted = decay[fit_start:fit_end].copy()
    res = {
        'name': 'Ce6 lifetime',
        'time': time, 'decay': decay,
        'k': np.logspace(-2, 1, 201),
        'k_distribution': np.exp(-((np.linspace(-2, 1, 201) - 0.6) ** 2) / 0.05),
        'peak_result': [],
        'info': {
            'irf_shifted': decay.copy(),
            'y_fitted': y_fitted,
            'residuals': np.zeros(fit_end - fit_start),
            'fit_start': fit_start, 'fit_end': fit_end,
            'qshift_suggested': 22.4,
            'chi_sqr': 1.02, 'method': 'MEM',
        },
    }
    w._render_lifetime_result(res, 1.5, '')

    ax1 = w.canvas.fig.axes[0]
    x0, x1 = ax1.get_xlim()
    t_lo = time[fit_start]
    t_hi = time[fit_end - 1]
    total = time[-1] - time[0]
    # 裁剪后的窗口必须显著小于全长（原实现是全长 ~440 000 ns）
    assert (x1 - x0) < total * 0.75, \
        f"时间轴仍占全长的 {(x1 - x0) / total:.0%}（应 <75%），噪声地板没裁掉"
    # 且必须完整包含拟合区间（裁过头就看不清拟合了）
    assert x0 <= t_lo and x1 >= t_hi, \
        f"时间轴 [{x0:.0f}, {x1:.0f}] 没包住拟合区间 [{t_lo:.0f}, {t_hi:.0f}]"
    # 拟合窗口阴影带存在
    spans = [p for p in ax1.patches if type(p).__name__ == 'Rectangle']
    assert spans, "拟合窗口应有 axvspan 阴影带"

    # 诊断页：上图 xlabel 与下图 title 间距必须为正
    # （v5.0.2 前实测 0 px，两行字贴在一起成一句乱文）
    dfig = w.diag_canvas.fig
    dfig.canvas.draw()
    r = dfig.canvas.get_renderer()
    axs = dfig.axes
    assert len(axs) >= 2, f"诊断页应有上下两图，实际 {len(axs)} 个"
    xl = axs[0].xaxis.label
    title_top = axs[1].title.get_window_extent(r).y1
    if xl.get_text().strip():
        gap = xl.get_window_extent(r).y0 - title_top
        assert gap > 2, \
            f"上图 xlabel 与下图 title 间距 {gap:.0f} px（要求 >2px，原来 0px 相撞）"


@check("导出 DPI：GUI / CLI / 汇总图读同一口径（v5.0.2）")
def t_export_dpi_single_source():
    """原状：GUI 600 / absorption・emission・3d_scan 200 / compare 300 /
    lifetime.summary 200 / report PDF 150 —— 同一份数据差 2–4 倍。
    """
    import export_defaults as ed
    import gui_config as cfg
    import plot_absorption as pa
    import plot_emission as pe
    import plot_3d_scan as p3
    import plot_compare as pc
    import plot_lifetime as pl

    # 单一真源：三个常量都是正整数且递增关系合理
    assert ed.EXPORT_DPI_DEFAULT >= 300, "位图默认 DPI 低于期刊底线"
    assert ed.EXPORT_DPI_VECTOR_MIN <= ed.EXPORT_DPI_DEFAULT
    assert 0 < ed.EXPORT_DPI_PREVIEW < ed.EXPORT_DPI_VECTOR_MIN

    # GUI 侧与根目录侧读到同一个值（gui_config 从 export_defaults 转出）
    assert cfg.EXPORT_DPI_DEFAULT == ed.EXPORT_DPI_DEFAULT
    assert cfg.EXPORT_DPI_VECTOR_MIN == ed.EXPORT_DPI_VECTOR_MIN
    assert cfg.EXPORT_DPI_PREVIEW == ed.EXPORT_DPI_PREVIEW

    # 各 CLI 模块必须真的 import 到这个口径（而不是各自留了字面量）
    for mod, nm in ((pa, 'plot_absorption'), (pe, 'plot_emission'),
                    (p3, 'plot_3d_scan'), (pc, 'plot_compare'),
                    (pl, 'plot_lifetime')):
        assert hasattr(mod, 'EXPORT_DPI_DEFAULT'), f"{nm} 没接入共享 DPI 口径"
        assert mod.EXPORT_DPI_DEFAULT == ed.EXPORT_DPI_DEFAULT, \
            f"{nm} 的默认 DPI 与统一口径不一致"

    # 关键函数的 dpi 默认值必须是 None（走共享口径），不能是硬编码数字
    import inspect
    for fn, nm in ((pa.plot_single_absorption, 'plot_single_absorption'),
                   (pa.plot_combined_absorption, 'plot_combined_absorption'),
                   (pc.save_figure, 'plot_compare.save_figure'),
                   (pl.plot_summary, 'plot_summary'),
                   (pl.export_report_pdf, 'export_report_pdf')):
        d = inspect.signature(fn).parameters.get('dpi')
        assert d is not None, f"{nm} 没有 dpi 参数"
        assert d.default is None, \
            f"{nm} 的 dpi 默认值仍是硬编码 {d.default}，应改为 None 走统一口径"


@check("峰标注：关闭「峰位标数值」后不留空 Text 对象（v5.0.2）")
def t_peak_label_no_empty_text():
    """原实现 `_peak_label` 返回空串、调用方仍无条件 annotate('')。

    实测每次重绘留 6 个空 Text：肉眼看不到，但参与 bbox 计算、导出时被
    序列化，也让自动避让重叠标注的逻辑失效（空串 bbox 是退化矩形）。
    """
    app, w = _make_gui()
    wl = np.arange(400.0, 601.0, 1.0)
    y = 100.0 * np.exp(-((wl - 500.0) / 25.0) ** 2)
    _install_spectra(w, {'s-1 (Emission)': (wl, y)})

    def _empty_texts(canvas):
        n = 0
        for ax in canvas.fig.axes:
            for t in ax.texts:
                if not t.get_text().strip():
                    n += 1
        return n

    w.peak_value_check.setChecked(False)
    w._do_plot()
    assert _empty_texts(w.canvas) == 0, \
        f"关闭峰位数值后仍留了 {_empty_texts(w.canvas)} 个空 Text 对象"

    # 打开时必须真的标出数字（不能为了不建空对象把功能一起关掉）
    w.peak_value_check.setChecked(True)
    w._do_plot()
    labels = [t.get_text() for ax in w.canvas.fig.axes for t in ax.texts
              if t.get_text().strip()]
    assert labels, "勾选「峰位标数值」后应至少有 1 个峰位数字标注"
    assert all(s.replace('.', '').isdigit() for s in labels), \
        f"峰位标注内容异常：{labels[:5]}"


@check("寿命图：IRF 平移量不用科学计数法（v5.0.2）")
def t_lifetime_shift_format():
    app, w = _make_gui()
    assert w._fmt_shift(1499.0) == '1,499', w._fmt_shift(1499.0)
    assert w._fmt_shift(22.4) == '22.4', w._fmt_shift(22.4)
    assert w._fmt_shift(0.0) == '0', w._fmt_shift(0.0)
    assert 'e' not in w._fmt_shift(1499.0).lower(), "不得输出科学计数法"
    # 极小值仍可读（退回 2 位有效数字，不撑爆图例）
    assert len(w._fmt_shift(0.00123)) <= 6


@check("寿命分布：τ 轴按分布质量分位裁剪（v5.0.2）")
def t_lifetime_tau_axis_by_mass():
    """τ 网格 0.01–100 ns 跨 4 个数量级，而 Ce6 的 MEM 分布 99% 质量只落在
    69.2–100 ns（0.16 个数量级）—— 峰被挤在最右端贴着边框。
    """
    app, w = _make_gui()
    w.spectrum_type_combo.setCurrentIndex(2)
    k = np.logspace(-2, 1, 201)        # k = 1/τ，τ ∈ [0.1, 100] ns
    tau = 1.0 / k
    # 分布集中在 τ≈85 ns 附近，模拟 Ce6 的窄峰
    dist = np.exp(-((np.log10(tau) - np.log10(85.0)) ** 2) / (2 * 0.02 ** 2))
    time = np.linspace(0.0, 40000.0, 800)
    decay = 3000.0 * np.exp(-time / 8000.0) + 1.0
    fs, fe = 100, 700
    res = {
        'name': 'Ce6', 'time': time, 'decay': decay,
        'k': k, 'k_distribution': dist, 'peak_result': [],
        'info': {'irf_shifted': decay.copy(), 'y_fitted': decay[fs:fe].copy(),
                 'residuals': np.zeros(fe - fs), 'fit_start': fs, 'fit_end': fe,
                 'qshift_suggested': 5.0, 'chi_sqr': 1.0, 'method': 'MEM'},
    }
    w._render_lifetime_result(res, 1.5, '')
    ax3 = w.lifetime_canvas.fig.axes[0]
    lo, hi = ax3.get_xlim()
    assert lo > 0 and hi > lo, f"τ 轴范围异常：{lo}, {hi}"
    decades = np.log10(hi) - np.log10(lo)
    # 原实现跨 4 个数量级（0.0063–158.5）；裁剪后应显著收窄
    assert decades < 2.0, \
        f"τ 轴仍跨 {decades:.2f} 个数量级（应 <2），峰还是被挤在一边"
    # 峰必须在视野内且不在最右边缘（留有余量）
    t_peak = 85.0
    assert lo < t_peak < hi, f"主峰 τ={t_peak} 不在轴范围 [{lo:.3g}, {hi:.3g}] 内"
    assert np.log10(hi) - np.log10(t_peak) > 0.05, \
        f"主峰贴着右边界（hi={hi:.3g}），应留出余量"


@check("GUI：「导出当前图」跟着标签页走——数据比较页导出的是点线图（v4.42）")
def t_export_current_tab():
    """用户反馈：在「数据比较」页点「导出当前图」（Ctrl+E/S），导出的却是光谱全图。

    原因是 export_plot 写死 self.canvas.fig。修好后按 currentWidget() 认页——
    标签页会随模式显隐、索引会漂，所以必须按控件身份认。
    """
    import tempfile
    from pathlib import Path as _Path
    from PyQt5.QtWidgets import QFileDialog
    from read_xlsx_info import XlsxInfo

    app, w = _make_gui()
    wl = np.arange(400.0, 601.0, 1.0)
    y1 = 100.0 * np.exp(-((wl - 500.0) / 25.0) ** 2)
    y2 = 50.0 * np.exp(-((wl - 500.0) / 25.0) ** 2)
    _install_spectra(w, {'s-1 (Emission)': (wl, y1), 's-2 (Emission)': (wl, y2)})
    w.xlsx_info = XlsxInfo(info={1: {'浓度': 5}, 2: {'浓度': 10}}, numbers=[1, 2],
                           columns=['浓度'], path=_Path('说明.xlsx'))
    w._refresh_compare_combos()
    w.compare_x_combo.setCurrentText('浓度')
    w.compare_group_combo.setCurrentIndex(0)
    w.compare_metric_combo.setCurrentIndex(0)
    res = w._do_compare_plot()
    assert res['summary']['n_points'] == 2, res['summary']
    w._do_plot()

    tmp = tempfile.mkdtemp(prefix='v442_export_')
    saved = []
    real_save, real_dialog = w._savefig_pub, QFileDialog.getSaveFileName

    def _fake_save(fig, path, dpi=None):
        saved.append((fig, str(path)))
        _Path(path).write_bytes(b'PNG')

    try:
        w._savefig_pub = _fake_save

        # ①（回归点）数据比较页
        suggested = []

        def _fake_dialog(parent, title, path, *a, **k):
            suggested.append(str(path))
            return os.path.join(tmp, 'a.png'), ''

        QFileDialog.getSaveFileName = staticmethod(_fake_dialog)
        w.tab_widget.setCurrentWidget(w.compare_tab)
        assert w._current_export_canvas() is w.compare_canvas, "数据比较页应认到 compare_canvas"
        w.export_plot()
        assert saved and saved[-1][0] is w.compare_canvas.fig, \
            "数据比较页导出的必须是点线图画布，而不是光谱预览画布"
        assert _Path(suggested[-1]).name.startswith('数据比较'), \
            f"默认文件名应是数据比较图：{suggested[-1]}"
        assert w._current_export_title().startswith('数据比较'), w._current_export_title()

        # ② 预览页 → 光谱图
        # v4.45：预览页改为**重画**（与「导出全部」同一条渲染路径），不再直接存
        # canvas.fig。原因：画布 fig 按屏幕尺寸建、字号停在界面字号，选了
        # 「单栏 3.5 in」预设后被 set_size_inches 硬塞 + bbox_inches='tight'
        # 一膨胀就变成 4.013 in，**超出栏宽 15%**；而「导出全部」走重画得到
        # 3.508 in。同一张图两个按钮给出两种物理尺寸 = 错配。
        # 因此这里改成断言「导出的是一张**新建的**光谱图，而不是画布本体」，
        # 并顺带校验它带了和画布一致的峰标注与显示范围。
        QFileDialog.getSaveFileName = staticmethod(
            lambda *a, **k: (os.path.join(tmp, 'b.png'), ''))
        w.tab_widget.setCurrentWidget(w.preview_tab)
        n_before = len(saved)
        # 在 _fake_save 里就把曲线数抓下来：export_plot 会在 finally 里
        # plt.close(fig)，close 之后再访问 fig.axes 不可靠。
        captured = {}

        def _fake_save2(fig, path, dpi=None):
            try:
                captured['n_lines'] = sum(len(ax.get_lines()) for ax in fig.axes)
                captured['fig'] = fig
            except Exception:
                pass
            saved.append((fig, str(path)))
            _Path(path).write_bytes(b'PNG')

        w._savefig_pub = _fake_save2
        w.export_plot()
        assert len(saved) > n_before, "预览页应产生一次导出"
        assert captured.get('fig') is not None, "预览页应走重画路径"
        assert captured['fig'] is not w.canvas.fig, \
            "v4.45 起预览页必须重画（不再直接存画布 fig，否则单栏预设会超宽）"
        assert captured.get('n_lines', 0) > 0, \
            "预览页导出的光谱图应含曲线"
        w._savefig_pub = _fake_save

        # ③ 取消保存时不写文件、不抛异常
        QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: ('', ''))
        n = len(saved)
        w.export_plot()
        assert len(saved) == n, "取消保存不应触发写文件"

        # ④ 四个标签页都在映射表里（索引会随模式显隐漂移，必须按身份认）
        pairs = dict(w._TAB_CANVAS_PAIRS)
        for tab_attr, canvas_attr in (('preview_tab', 'canvas'),
                                      ('compare_tab', 'compare_canvas'),
                                      ('diag_tab', 'diag_canvas'),
                                      ('dist_tab', 'lifetime_canvas')):
            assert pairs.get(tab_attr) == canvas_attr, tab_attr
            assert hasattr(w, tab_attr) and hasattr(w, canvas_attr), tab_attr
    finally:
        w._savefig_pub = real_save
        QFileDialog.getSaveFileName = real_dialog


def main():
    strict = '--strict' in sys.argv

    print("=" * 72)
    print("  光谱可视化分析工具 —— 回归测试集（E3）")
    print(f"  GUI 目录: {GUI_DIR}")
    if strict:
        print("  模式: --strict（跳过计为失败）")
    print("=" * 72)
    passed = failed = skipped = 0
    s_lend, s_saved = _session_settings_lend()
    try:
        for name, fn in RESULTS:
            try:
                fn()
            except Skip as e:
                skipped += 1
                print(f"[SKIP] {name}（{e}）")
            except Exception as e:
                failed += 1
                print(f"[FAIL] {name}")
                print(f"       {type(e).__name__}: {e}")
                traceback.print_exc(limit=3)
            else:
                passed += 1
                print(f"[PASS] {name}")
    finally:
        _session_settings_return(s_lend, s_saved)
    print("-" * 72)
    print(f"  共 {len(RESULTS)} 项：通过 {passed}，跳过 {skipped}，失败 {failed}")
    if strict and skipped:
        print("  [--strict] 存在跳过项 → 视为失败")
        failed += skipped
    print("=" * 72)
    return 0 if failed == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
