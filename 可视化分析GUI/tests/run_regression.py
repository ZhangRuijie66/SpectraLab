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


# ---------------------------------------------------------------- 数据路径
TEST_DIR = os.path.join(GUI_DIR, 'test')
LIFETIME_CSV = os.path.join(TEST_DIR, 'Fig9_FoldedRNA.csv')
# 3D 样例优先用仓库内副本（test\RBLu_1_3d_scan.csv），
# 这样换机器/数据盘变动时不会静默跳过 3D 检查
SCAN3D_LOCAL = os.path.join(TEST_DIR, 'RBLu_1_3d_scan.csv')
SCAN3D_EXTERNAL = (r'D:\北大\QLS Lab\SPC\1O2+luminol\谱图\光谱'
                   r'\20260727-RB-Lu\RBLu 1 2026-07-27 07-11.csv')
SCAN3D_CSV = SCAN3D_LOCAL if os.path.exists(SCAN3D_LOCAL) else SCAN3D_EXTERNAL
EMISSION_DIR = (r'D:\北大\QLS Lab\SPC\ESIPT\谱图\吸收&荧光'
                r'\20260723-ESIPT-1-DMF')


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
                 'Ctrl+D', 'F1'):
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


@check("GUI：寿命拟合参数「存为默认值」下次启动生效")
def t_gui_lifetime_defaults():
    app, w = _make_gui()
    if not w.settings.isWritable():
        raise Skip("QSettings 不可写，注册表被限制")
    keys = ["defaults/" + k for k, _, _ in w._LIFETIME_DEFAULT_SPECS]
    keys.append("defaults/lifetime_saved")
    old = {k: w.settings.value(k, None) for k in keys}
    try:
        w.lifetime_method_combo.setCurrentIndex(0)          # MEM（λ 才有意义）
        w.lifetime_nrates_spin.setValue(123)
        w.lifetime_kmin_spin.setValue(0.005)
        w.lifetime_kmax_spin.setValue(50.0)
        w.lifetime_fixed_taus_edit.setText("3.6, 0.5")
        w.lifetime_lambda_spin.setValue(0.01)
        w.lifetime_auto_lambda_check.setChecked(False)
        assert w._save_lifetime_defaults(), "保存默认值失败"
        app2, w2 = _make_gui()
        assert w2.lifetime_nrates_spin.value() == 123, "网格点数未套用默认值"
        assert abs(w2.lifetime_kmin_spin.value() - 0.005) < 1e-9
        assert abs(w2.lifetime_kmax_spin.value() - 50.0) < 1e-9
        assert w2.lifetime_fixed_taus_edit.text() == "3.6, 0.5"
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
    long_path = (r'D:\北大\QLS Lab\SPC\1O2+luminol\谱图\光谱'
                 r'\20260727-RB-Lu')
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
    out_dir = tempfile.mkdtemp(prefix='qls3d_')
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
    out = tempfile.mkdtemp(prefix='qls_rep_')
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


def main():
    strict = '--strict' in sys.argv
    print("=" * 72)
    print("  QLS Lab 光谱可视化分析工具 —— 回归测试集（E3）")
    print(f"  GUI 目录: {GUI_DIR}")
    if strict:
        print("  模式: --strict（跳过计为失败）")
    print("=" * 72)
    passed = failed = skipped = 0
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
    print("-" * 72)
    print(f"  共 {len(RESULTS)} 项：通过 {passed}，跳过 {skipped}，失败 {failed}")
    if strict and skipped:
        print("  [--strict] 存在跳过项 → 视为失败")
        failed += skipped
    print("=" * 72)
    return 0 if failed == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
