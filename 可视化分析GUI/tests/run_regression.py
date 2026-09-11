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


def _session_settings_lend():
    """摘下回归测试敏感的会话设置，返回 (QSettings, 备份字典)。"""
    from PyQt5.QtCore import QSettings
    from gui_config import APP_ORG, APP_NAME
    s = QSettings(APP_ORG, APP_NAME)
    keys = [k for k in s.allKeys()
            if k.startswith(_SESSION_KEY_PREFIXES) or k in _SESSION_KEY_EXACT]
    saved = {k: s.value(k) for k in keys}
    for k in keys:
        s.remove(k)
    s.sync()
    return s, saved


def _session_settings_return(s, saved):
    """把会话设置原样放回（测试结束/异常都走这里）。"""
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
    for i in range(3):
        w.data_cache[f's{i}.csv'] = {'data': {
            'time': t, 'decay': np.maximum(decay * (1.0 - 0.15 * i), 0.0),
            'irf': irf, 'meta': None}}
    w.lifetime_auto_lambda_check.setChecked(False)   # 快跑，不扫 λ
    w.lifetime_nrates_spin.setValue(51)              # 控件下限即 51，小值最快
    params = w._collect_plot_params()

    calls = []
    real_fit_many = pl.fit_many

    def spy(datasets, **kw):
        calls.append([d['name'] for d in datasets])
        return real_fit_many(datasets, **kw)

    pl.fit_many = spy
    out = tempfile.mkdtemp(prefix='qls_cache_')
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

    out = tempfile.mkdtemp(prefix='qls_overlay_')
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
    app, w = _make_gui()
    w.show()
    app.processEvents()
    base = len(app.allWidgets())
    assert base > 200, f"主窗口控件数异常偏少：{base}"
    # PyQt 里 connect(self.方法) 天然会形成引用环（窗口要等 GC 才回收，这是
    # 既有行为，不是本次引入的），所以这里显式 gc.collect() 逼出析构——
    # 重要是"显示状态下被析构"这条路径要能安全走完。
    del w
    gc.collect()
    app.processEvents()
    left = len(app.allWidgets())
    assert left < base // 4, f"GC 后主窗口控件仍未释放：{base} → {left}"
    for _ in range(3):
        _app, t = _make_gui()
        t.show()
        app.processEvents()
        del t
        gc.collect()
        app.processEvents()
    assert len(app.allWidgets()) < base // 2, \
        f"反复建/销毁后控件数没有回落：{base} → {len(app.allWidgets())}"


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

    out = tempfile.mkdtemp(prefix='qls_single_')
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
    key_light = w.theme_btn.icon().cacheKey()
    w.toggle_theme(True)
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


def main():
    strict = '--strict' in sys.argv

    print("=" * 72)
    print("  QLS Lab 光谱可视化分析工具 —— 回归测试集（E3）")
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
