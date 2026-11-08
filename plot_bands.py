# -*- coding: utf-8 -*-
"""
谱带分解与定量模块（plot_bands）
=================================
适用数据
--------
吸收或发射光谱（CSV / TXT，一行一个波长点），支持本项目已有的全部格式：

* 发射：Spectracle / FE30「发射数据组」、LabSolutions RF-6000、PerkinElmer
  FL WinLab（解析直接用 ``plot_emission.parse_csv`` / ``load_spectra``）；
* 吸收：LabSolutions UV-Vis（解析直接用 ``plot_absorption.load_absorption_spectra``）。

也可以不经文件，直接给 ``(label, wl, y)`` 或 ``{'label','wl','y'}`` 形式的数组。

功能
----
吸收/发射谱常常是**多条谱带叠在一起**，单看 ``find_peaks`` 只能拿到局部极大：
ESIPT 的 enol*/keto* 双发射要面积比、罗丹明的 515 nm 振动肩峰根本不是局部极大、
稀土多带彼此重叠——这些都定不出"每一条带各占多少"。

本模块用**非线性最小二乘 + 解析积分**把一条谱分解成若干条谱带，给出每条带的
**峰位 / 峰高 / 半高宽 / 面积 / 面积占比**，并能对一批样品做两带面积比：

* 峰形三种：``gaussian``（高斯，仪器展宽为主）、``lorentzian``（洛伦兹，
  均匀展宽/寿命展宽为主）、``pseudo_voigt``（两者线性组合，η 可调，谱带两翼
  重时用它，否则尾部会被高斯截断而低估面积）。
* **面积用解析式，不做数值积分**：高斯 ``A=√(2π)·σ·h``、洛伦兹 ``A=π·γ·h``、
  伪 Voigt 按 η 加权平均（三种峰形的 FWHM 定义一致，可直接互比）。
* **自动定阶**：``n_peaks=None`` 时按 BIC（``BIC=n·ln(RSS/n)+k·ln(n)``）
  在 1…``max_peaks`` 里选峰数，并报告整条 BIC 曲线（``order_scan``）——
  判据是"看曲线的拐点"而不是盲信最小值。
* **拟合受约束**：峰宽 > 0、峰高 ≥ 0、峰位落在拟合窗口内、半高宽不小于
  3 个数据点；多起点重启后取残差最小者，避免收敛到非物理解。
* 本底可选 ``none / const / linear``；散射峰可用 ``exclude_scatter``
  按激发波长自动挖掉（含 2λ 二级衍射），避免把瑞利散射当谱带。

一键用法
--------
::

    from plot_bands import run_bands, compare_band_ratios, decompose_bands

    # 1) 一条谱：分解 + 出图 + 出峰表
    res = decompose_bands(wl, y, model='gaussian', max_peaks=6)
    [print(p['center'], p['area_share']) for p in res['peaks']]

    # 2) 一个文件夹：逐条分解 + 汇总图（ESIPT 双发射，挖掉 350/700 nm 散射）
    out = run_bands(folder=r'D:\\...\\20260723-ESIPT-1-DMF',
                    kind='emission', wl_range=(390, 660),
                    exclude_scatter=350,
                    save_dir=r'./plots')

    # 3) 两带面积比随样品变化（keto* / enol*）
    rat = compare_band_ratios(out['datasets'], band_a=(400, 510), band_b=(520, 660),
                              save_dir=r'./plots')
    print(rat['table'])

命令行用法
----------
::

    # 分解一个文件夹里所有发射谱（自动定阶），图与峰表存 ./plots
    python plot_bands.py "D:\\data\\20260723-ESIPT-1-DMF" --kind emission \\
        --range 390 660 --exclude-scatter 350

    # 指定两条带，输出面积比曲线（keto*/enol*）
    python plot_bands.py "D:\\data\\ESIPT" --range 390 660 --exclude-scatter 350 \\
        --band-a 400 510 --band-b 520 660

    # 吸收谱的罗丹明肩峰：窗口收紧到可见带，两峰分解
    python plot_bands.py "D:\\data\\uvvis" --kind absorption --range 470 620 \\
        --n-peaks 2 --model gaussian

    # 只看文件清单一列，不拟合
    python plot_bands.py "D:\\data\\uvvis" --list

依赖：只用到 numpy / scipy / matplotlib（解析委托同目录的 plot_emission /
plot_absorption，用到时懒加载）。导出 DPI 取 ``export_defaults.EXPORT_DPI_DEFAULT``。
"""

import argparse
import csv
import glob
import math
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
from scipy.optimize import curve_fit
from scipy.signal import find_peaks

# 导出口径单一来源（v5.0.2）：GUI 与根目录各 plot_*.py 共用同一组 DPI。
try:
    from export_defaults import (EXPORT_DPI_DEFAULT,
                                 EXPORT_DPI_VECTOR_MIN,
                                 EXPORT_DPI_PREVIEW)
except ImportError:                     # 脚本被单独复制出去时退回字面量
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        from export_defaults import (EXPORT_DPI_DEFAULT,
                                     EXPORT_DPI_VECTOR_MIN,
                                     EXPORT_DPI_PREVIEW)
    except ImportError:                 # pragma: no cover
        EXPORT_DPI_DEFAULT, EXPORT_DPI_VECTOR_MIN, EXPORT_DPI_PREVIEW = 600, 300, 150


# ======================== 0. 中文字体 / 打印 ========================

_FONT_READY = False


def _safe_print(*args):
    """安全打印：在某些终端/编码（如 GBK、ASCII）下避免因非 ASCII 字符崩溃"""
    try:
        print(*args)
    except Exception:
        pass


def setup_chinese_font(verbose=False):
    """挑一个可用的中文字体（Windows/macOS/Linux 依次尝试）。

    模块导入时已调用一次；本函数可重复调用（幂等），``verbose=True`` 时才打印。
    不打印的理由：一条命令里 ``plot_bands`` 与 ``plot_emission`` 都会被导入，
    每个模块各打一行 "[FONT]" 只是噪声。
    """
    global _FONT_READY
    candidates = [
        # Windows
        'Microsoft YaHei', 'SimHei', 'KaiTi', 'FangSong', 'SimSun',
        # macOS
        'PingFang SC', 'Hiragino Sans GB', 'Songti SC', 'STHeiti',
        'Heiti SC', 'Arial Unicode MS',
        # Linux / 其它
        'Noto Sans CJK SC', 'WenQuanYi Micro Hei',
    ]
    available = {f.name for f in matplotlib.font_manager.fontManager.ttflist}
    chosen = None
    for font in candidates:
        if font in available:
            chosen = font
            break
    if chosen:
        plt.rcParams['font.sans-serif'] = [chosen, 'DejaVu Sans']
        plt.rcParams['axes.unicode_minus'] = False
        if verbose:
            _safe_print(f"  [FONT] 使用中文字体: {chosen}")
    else:
        plt.rcParams['font.sans-serif'] = ['DejaVu Sans']
        if verbose:
            _safe_print("  [WARN] 未找到中文字体，将使用英文标签")
    _FONT_READY = True
    return chosen


setup_chinese_font()


# ======================== 1. 峰形与解析面积 ========================

#: 支持的峰形。三者用**同一套参数**（峰位 center、半高宽 fwhm、峰高 height），
#: 因此同一个拟合结果换峰形后仍可直接比较峰位与 FWHM。
MODELS = ('gaussian', 'lorentzian', 'pseudo_voigt')

MODEL_LABELS = {
    'gaussian': '高斯',
    'lorentzian': '洛伦兹',
    'pseudo_voigt': '伪Voigt',
}

#: 本底模型。``const`` 只拟合一个常数，``linear`` 拟合 a+b·x（以窗口中心归一化，
#: 避免 x 的量级（~500）把法方程条件数拉坏）。
BASELINES = ('none', 'const', 'linear')

_SQRT_2PI = math.sqrt(2.0 * math.pi)
#: FWHM = _FWHM_K · σ（高斯）。2√(2ln2) = 2.354820045…
_FWHM_K = 2.0 * math.sqrt(2.0 * math.log(2.0))

_EPS = 1e-12


def fwhm_to_sigma(fwhm):
    """高斯：半高宽 → 标准差 σ = FWHM / (2√(2ln2))。"""
    return np.asarray(fwhm, dtype=float) / _FWHM_K


def sigma_to_fwhm(sigma):
    """高斯：标准差 → 半高宽 FWHM = 2√(2ln2)·σ。"""
    return np.asarray(sigma, dtype=float) * _FWHM_K


def peak_profile(x, model='gaussian', center=0.0, fwhm=1.0, height=1.0, eta=0.5):
    """单条谱带的**形状**（峰值 = height，半高宽 = fwhm）。

    三种峰形的 FWHM 定义一致，所以 fwhm 永远是"半高全宽"，与峰形无关：

    * ``gaussian``    ：``h·exp(-(x-c)²/(2σ²))``，σ = fwhm/(2√(2ln2))
    * ``lorentzian``  ：``h·γ²/((x-c)²+γ²)``，γ = fwhm/2（半高半宽）
    * ``pseudo_voigt``：``h·[(1-η)·G + η·L]``，G/L 各自单独都是峰值 h、
      半高 = fwhm/2，所以**加权和依然是峰值 h、FWHM = fwhm**（η 不改变半高宽，
      只改变两翼权重），η=0 退化为高斯、η=1 退化为洛伦兹。
    """
    x = np.asarray(x, dtype=float)
    if model not in MODELS:
        raise ValueError(f"未知峰形 {model!r}，可选：{', '.join(MODELS)}")
    fwhm = np.maximum(np.asarray(fwhm, dtype=float), _EPS)
    dx = x - np.asarray(center, dtype=float)
    if model == 'gaussian':
        sigma = fwhm / _FWHM_K
        return height * np.exp(-0.5 * (dx / sigma) ** 2)
    gamma = 0.5 * fwhm
    lor = gamma ** 2 / (dx ** 2 + gamma ** 2)
    if model == 'lorentzian':
        return height * lor
    sigma = fwhm / _FWHM_K
    gau = np.exp(-0.5 * (dx / sigma) ** 2)
    return height * ((1.0 - eta) * gau + eta * lor)


def peak_area(model='gaussian', height=1.0, fwhm=1.0, eta=0.0):
    """单条谱带的**解析面积**（不做数值积分）。

    ===============  ==========================  ==========================
    峰形             面积公式                    说明
    ===============  ==========================  ==========================
    ``gaussian``     ``√(2π)·σ·h``               σ = fwhm/(2√(2ln2))
    ``lorentzian``   ``π·γ·h``                   γ = fwhm/2
    ``pseudo_voigt`` ``(1-η)·A_G + η·A_L``       两翼权重加权；η 越大面积越大
    ===============  ==========================  ==========================

    为什么坚持解析式：梯形积分对**宽洛伦兹尾**会按窗口截断而系统性偏小，
    对**窄高峰**又受采样点数限制；解析式只依赖三个拟合参数，且峰形外推到
    ±∞ 的面积是有限的、可比的。峰形选错（真谱是洛伦兹却用高斯拟合）时
    解析式仍会给出"该峰形下的等效面积"，这一点在报告里必须说明。
    """
    h = np.asarray(height, dtype=float)
    f = np.maximum(np.asarray(fwhm, dtype=float), _EPS)
    if model == 'gaussian':
        area = _SQRT_2PI * (f / _FWHM_K) * h
    elif model == 'lorentzian':
        area = math.pi * 0.5 * f * h
    elif model == 'pseudo_voigt':
        a_g = _SQRT_2PI * (f / _FWHM_K) * h
        a_l = math.pi * 0.5 * f * h
        area = (1.0 - np.asarray(eta, dtype=float)) * a_g + np.asarray(eta, dtype=float) * a_l
    else:
        raise ValueError(f"未知峰形 {model!r}，可选：{', '.join(MODELS)}")
    return float(area) if np.ndim(area) == 0 else area


# ======================== 2. 拟合内核 ========================

def _n_base_params(baseline):
    """本底占几个参数。"""
    return {'none': 0, 'const': 1, 'linear': 2}.get(baseline, 1)


def _n_peak_params(model, pseudo):
    """每条谱带占几个参数：center / fwhm / height (+ eta)。"""
    return 4 if pseudo else 3


def _baseline_values(x, coeffs, baseline, x_ref):
    """按本底模型算本底曲线。``x_ref=(中心, 半宽)`` 用于线性项归一化。"""
    out = np.zeros_like(np.asarray(x, dtype=float))
    if baseline == 'none' or not len(coeffs):
        return out
    out = out + float(coeffs[0])
    if baseline == 'linear' and len(coeffs) > 1:
        mid, half = x_ref
        out = out + float(coeffs[1]) * (np.asarray(x, dtype=float) - mid) / half
    return out


def _model_curve(x, params, model, baseline, n_peaks, x_ref):
    """完整模型 = 本底 + 各谱带之和。"""
    nb = _n_base_params(baseline)
    pseudo = (model == 'pseudo_voigt')
    per = _n_peak_params(model, pseudo)
    total = _baseline_values(x, params[:nb], baseline, x_ref)
    for i in range(n_peaks):
        seg = params[nb + i * per: nb + (i + 1) * per]
        center, fwhm, height = seg[0], seg[1], seg[2]
        eta = seg[3] if pseudo else 0.0
        total = total + peak_profile(x, model, center, fwhm, height, eta)
    return total


def _moving_average(y, window):
    """端点归一化的滑动平均（用于挑初值的峰位，不参与拟合）。"""
    y = np.asarray(y, dtype=float)
    window = int(max(1, window))
    if window <= 1 or y.size < 3:
        return y.copy()
    window = min(window, y.size if y.size % 2 else y.size - 1)
    if window < 3:
        return y.copy()
    kernel = np.ones(window, dtype=float)
    num = np.convolve(y, kernel, mode='same')
    den = np.convolve(np.ones_like(y), kernel, mode='same')
    return num / np.maximum(den, _EPS)


def _half_max_fwhm(x, y, i):
    """从平滑曲线在峰位 i 处向两侧找半高交点，估一个 FWHM（初值用）。"""
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    base = float(np.min(y))
    half = base + 0.5 * (float(y[i]) - base)
    left = i
    while left > 0 and y[left] > half:
        left -= 1
    right = i
    while right < y.size - 1 and y[right] > half:
        right += 1
    if right > left:
        return float(abs(x[right] - x[left]))
    return float('nan')


def _guess_peaks(x, y, n_want, span, fwhm_min, fwhm_max, min_height):
    """给 ``n_want`` 条谱带挑初值：先在平滑谱上找局部极大，不够再补位置。

    返回 ``[(center, fwhm, height), ...]``，按峰高从大到小。
    """
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    step = float(np.median(np.diff(x))) if x.size > 1 else 1.0
    win = int(max(3, round(span / 60.0 / max(step, _EPS))))
    ys = _moving_average(y, win)
    base0 = float(np.min(y))
    rng_y = float(np.max(ys) - min(base0, float(np.min(ys))))
    prom = max(0.02 * rng_y, min_height * 1e-3)
    dist = int(max(2, round(max(fwhm_min, 2 * step) / max(step, _EPS))))
    idx, props = find_peaks(ys, prominence=prom, distance=dist)

    picked = []
    order = np.argsort(ys[idx])[::-1] if idx.size else np.array([], dtype=int)
    for j in order:
        i = int(idx[j])
        c = float(x[i])
        if any(abs(c - p[0]) < fwhm_min for p in picked):
            continue
        fw = _half_max_fwhm(x, ys, i)
        if not np.isfinite(fw) or fw <= 0:
            fw = span / max(3.0, 2.0 * n_want)
        fw = float(np.clip(fw, fwhm_min, fwhm_max))
        picked.append((c, fw, max(float(y[i] - base0), min_height)))
        if len(picked) >= n_want:
            break

    # 局部极大不够 n_want 条时，按"当前模型解释不了的残差"补位置：
    # 直接用平滑谱上尚未被覆盖的最高点，比均匀撒点更靠近真实谱带。
    guard = 0
    while len(picked) < n_want and guard < n_want * 8:
        guard += 1
        mask = np.ones(x.size, dtype=bool)
        for c, _fw, _h in picked:
            mask &= np.abs(x - c) > max(2.0 * fwhm_min, span / (4.0 * n_want))
        if not mask.any():
            break
        cand = np.where(mask)[0]
        i = int(cand[np.argmax(ys[cand])])
        if ys[i] <= base0 + min_height and picked:
            break
        fw = float(np.clip(span / max(3.0, 2.0 * n_want), fwhm_min, fwhm_max))
        picked.append((float(x[i]), fw, max(float(y[i] - base0), min_height)))
    # 仍不够（例如 n_want > 可用点数）时均匀铺开，保证参数个数与 n_peaks 一致
    while len(picked) < n_want:
        k = len(picked)
        c = float(x[0] + span * (k + 1) / (n_want + 1.0))
        picked.append((c, float(np.clip(span / (2.0 * n_want + 1),
                                        fwhm_min, fwhm_max)),
                       max(float(np.interp(c, x, y) - base0), min_height)))
    return picked[:n_want]


def _pack_initial(x, y, n_peaks, model, baseline, fwhm_min, fwhm_max, x_ref):
    """把初值打成 curve_fit 用的参数向量 ``p0``。"""
    span = float(x[-1] - x[0]) if x.size > 1 else 1.0
    base0 = float(np.min(y))
    guesses = _guess_peaks(x, y, n_peaks, span, fwhm_min, fwhm_max,
                           max(float(np.max(y) - base0), 0.0) * 0.01)
    nb = _n_base_params(baseline)
    p0 = []
    if baseline in ('const', 'linear'):
        p0.append(base0)
        if baseline == 'linear':
            p0.append(0.0)
    pseudo = (model == 'pseudo_voigt')
    for center, fwhm, height in guesses:
        p0.extend([center, fwhm, max(height, _EPS)])
        if pseudo:
            p0.append(0.5)
    return np.asarray(p0, dtype=float), nb


def _pack_bounds(x, y, n_peaks, model, baseline, fwhm_min, fwhm_max):
    """参数边界——**必须有**：无边界时 curve_fit 会收敛到负峰宽/峰位跑到窗外。"""
    lo_x, hi_x = float(x[0]), float(x[-1])
    base0 = float(np.min(y))
    ymax = float(np.max(y))
    ylo = min(base0, 0.0) - 10.0 * (abs(base0) + abs(ymax) + _EPS)
    yhi = 2.0 * abs(ymax) + abs(base0) + _EPS
    nb = _n_base_params(baseline)
    lower, upper = [], []
    if baseline in ('const', 'linear'):
        lower.append(ylo)
        upper.append(yhi)
        if baseline == 'linear':
            # 斜率项乘的 (x-mid)/half 落在 [-1, 1]，所以边界按纵轴量级给
            lower.append(-10.0 * yhi)
            upper.append(10.0 * yhi)
    pseudo = (model == 'pseudo_voigt')
    for _ in range(n_peaks):
        lower.extend([lo_x, max(fwhm_min, _EPS), 0.0])
        upper.extend([hi_x, max(fwhm_max, fwhm_min * 1.01), yhi])
        if pseudo:
            lower.append(0.0)
            upper.append(1.0)
    return np.asarray(lower, float), np.asarray(upper, float)


def _fit_once(x, y, n_peaks, model, baseline, p0, lower, upper, maxfev):
    """一次带边界的曲线拟合；失败返回 ``(None, inf, msg)``。

    注意 ``curve_fit`` 要的是 ``f(x, *params)`` 而不是残差函数——直接把残差函数
    传进去会算成"残差的残差"，拟合必然失败（实测所有峰数都返回 None）。
    """
    x_ref = _x_ref_of(x)

    def _curve(xx, *params):
        return _model_curve(xx, np.asarray(params, float), model, baseline,
                            n_peaks, x_ref)

    try:
        popt, _pcov = curve_fit(_curve, x, y, p0=p0, bounds=(lower, upper),
                                method='trf', maxfev=maxfev,
                                x_scale='jac')
    except Exception as e:              # RuntimeError: 迭代上限 / 参数退化
        return None, float('inf'), str(e)[:120]
    rss = float(np.sum((_curve(x, *popt) - y) ** 2))
    if not np.isfinite(rss):
        return None, float('inf'), 'RSS 非有限'
    return np.asarray(popt, float), rss, ''


def _x_ref_of(x):
    """线性本底的归一化参考：窗口中心与半宽。"""
    lo, hi = float(np.min(x)), float(np.max(x))
    half = 0.5 * (hi - lo)
    return 0.5 * (hi + lo), (half if half > 0 else 1.0)


def _unpack_result(x, y, params, n_peaks, model, baseline, rss, criterion,
                   order_scan=None, extra=None):
    """把参数向量整理成对外返回的 dict（含每峰的解析面积与占比）。"""
    nb = _n_base_params(baseline)
    pseudo = (model == 'pseudo_voigt')
    per = _n_peak_params(model, pseudo)
    x_ref = _x_ref_of(x)
    baseline_y = _baseline_values(x, params[:nb], baseline, x_ref)
    fit = _model_curve(x, params, model, baseline, n_peaks, x_ref)

    peaks = []
    for i in range(n_peaks):
        seg = params[nb + i * per: nb + (i + 1) * per]
        center, fwhm, height = float(seg[0]), float(seg[1]), float(seg[2])
        eta = float(seg[3]) if pseudo else 0.0
        area = peak_area(model, height, fwhm, eta)
        peaks.append({
            'center': center,
            'height': height,
            'fwhm': fwhm,
            'sigma': float(fwhm / _FWHM_K),
            'area': area,
            'area_share': float('nan'),     # 下面统一填
            'eta': eta if pseudo else None,
            'model': model,
            'component': peak_profile(x, model, center, fwhm, height, eta),
            # 峰位是否贴在拟合窗口边界——贴住了说明"这条带中心在窗外"，
            # 面积只能当成下限，报告里必须提示。
            'at_bound': bool(min(abs(center - float(x[0])),
                                 abs(center - float(x[-1]))) <= 1.5 * _step_of(x)),
        })
    peaks.sort(key=lambda p: p['center'])
    total_area = float(sum(p['area'] for p in peaks))
    for p in peaks:
        p['area_share'] = (p['area'] / total_area) if total_area > 0 else float('nan')

    residual = y - fit
    rss = float(np.sum(residual ** 2)) if not np.isfinite(rss) else rss
    n = int(x.size)
    tss = float(np.sum((y - float(np.mean(y))) ** 2))
    r2 = float(1.0 - rss / tss) if tss > 0 else float('nan')
    k = int(params.size)
    rmse = float(math.sqrt(rss / n)) if n else float('nan')
    # 完美拟合（无噪声合成数据）时 RSS=0，ln(0) 会把 BIC 变成 NaN 或 -inf，
    # 于是"多一个峰永远更好"。给方差加一个**相对精度下限**：RSS=0 的各档
    # 方差都被拉平到同一地板，BIC 的差别只剩 k·ln(n) 的罚项，从而选最少峰数。
    # 报告里的 rss 仍是真值，只有 BIC/AIC 用这个地板。
    var = (rss / n) if n else float('nan')
    scale = float(np.max(np.abs(y))) if y.size else 0.0
    var_floor = (1e-10 * max(scale, _EPS)) ** 2
    var_used = max(var, var_floor) if np.isfinite(var) else var_floor
    ln_term = math.log(var_used) if var_used > 0 else -math.inf
    bic = n * ln_term + k * math.log(n) if np.isfinite(ln_term) else float('nan')
    aic = n * ln_term + 2.0 * k if np.isfinite(ln_term) else float('nan')

    base_params = {nm: float(v) for nm, v in
                   zip(('offset', 'slope')[:nb], params[:nb])}
    out = {
        'ok': True,
        'message': '',
        'model': model,
        'model_label': MODEL_LABELS.get(model, model),
        'baseline_model': baseline,
        'baseline': base_params,
        'baseline_y': baseline_y,
        'n_peaks': n_peaks,
        'peaks': peaks,
        'total_area': total_area,
        'x': x,
        'y': y,
        'fit': fit,
        'residual': residual,
        'r2': r2,
        'rmse': rmse,
        'rss': rss,
        'bic': bic,
        'aic': aic,
        'n_points': n,
        'n_params': k,
        'criterion': criterion,
        'params': np.asarray(params, float),
        'order_scan': order_scan or [],
    }
    if extra:
        out.update(extra)
    return out


def _failed(message, model='gaussian', criterion='bic'):
    """返回一个"没做成"的结果，调用方不必写 try/except 也能安全取字段。"""
    return {'ok': False, 'message': str(message), 'model': model,
            'model_label': MODEL_LABELS.get(model, model),
            'n_peaks': 0, 'peaks': [], 'total_area': float('nan'),
            'r2': float('nan'), 'rmse': float('nan'), 'bic': float('nan'),
            'aic': float('nan'), 'rss': float('nan'), 'n_points': 0,
            'n_params': 0, 'criterion': criterion, 'baseline': {},
            'baseline_model': 'none', 'order_scan': [],
            'separation': float('nan'), 'min_separation': float('nan'),
            'separation_limited': False, 'pruned': False,
            'x': np.array([]), 'y': np.array([]), 'fit': np.array([]),
            'baseline_y': np.array([]), 'residual': np.array([]),
            'params': np.array([])}


def _step_of(x):
    """数据点间隔（取中位数，容忍不等间距）。"""
    x = np.asarray(x, float)
    if x.size < 2:
        return 1.0
    d = np.diff(x)
    d = d[np.isfinite(d) & (d > 0)]
    return float(np.median(d)) if d.size else 1.0


def detect_clipped(wl, y, tol_rel=1e-6, min_points=3):
    """找**削顶/饱和平台**：连续 ≥ ``min_points`` 个点强度相同且接近全谱最大值。

    为什么必须找出来
    ----------------
    FE30 这类仪器的强度是整数且量程上限 50000。实测
    ``示例数据/测试数据/20260723-ESIPT-1-DMF/发射数据组 2026-07-23 08-11.csv``
    的 460 nm 激发谱在 **459–463 nm 连续 5 个点都是 50000**（拉曼/瑞利散射峰顶
    到量程），350 nm 激发谱在 **346–355 nm 连续 10 个点是 50000**。

    这个平台不是谱带：它的"峰高"由量程决定、真实高度未知，"峰宽"由饱和点数
    决定、真实宽度也未知。拟合若把它当一条带，会给出一个**又高又窄**的假峰，
    并且把它的面积算进总面积/占比里。实测这一条（同一份 ESIPT 数据、
    同样 ``wl_range=(390, 660)``）：460 nm 激发谱被判成 3 峰、给出 460.9 nm
    的"带"且面积占比 30.9%，双发射比值 2.24。但这条谱**本来就没有 enol*
    带**——挖掉饱和段后 400–490 nm 只剩本底量级。也就是说，漏挖饱和不是让
    比值"略有偏差"，而是让它**指向一条不存在的谱带**，比值随之失去物理意义。

    返回 ``[(lo, hi), ...]``：每个平台覆盖的波长区间（两端各外扩一个数据步长，
    把平台的"肩"也挖掉）。没有平台时返回空列表。
    """
    wl = np.asarray(wl, dtype=float)
    y = np.asarray(y, dtype=float)
    if wl.size < int(min_points) or wl.size < 3:
        return []
    lo_all = float(np.nanmin(y))
    hi_all = float(np.nanmax(y))
    span = hi_all - lo_all
    if not np.isfinite(span) or span <= 0:
        return []
    tol = max(float(tol_rel) * abs(hi_all), 1e-12)
    # 只认"贴在全谱最大值上"的平台：低处的偶然重复（整数量化）不算饱和
    at_max = np.abs(y - hi_all) <= tol
    step = _step_of(wl)
    out = []
    i = 0
    n = int(at_max.sum())
    if n < int(min_points):
        return []
    idx = np.where(at_max)[0]
    # 按连续段切分（相邻下标差 1 视为同一段）
    runs = []
    start = prev = int(idx[0])
    for j in idx[1:]:
        j = int(j)
        if j == prev + 1:
            prev = j
            continue
        runs.append((start, prev))
        start = prev = j
    runs.append((start, prev))
    for a, b in runs:
        if b - a + 1 < int(min_points):
            continue
        out.append((float(wl[a] - step), float(wl[b] + step)))
    return out


def _prepare_xy(wl, y, wl_range=None, exclude=None, exclude_scatter=None,
                scatter_width=12.0, drop_clipped=True, clipped_min_points=3):
    """清洗 + 裁剪 + 挖掉散射峰与饱和平台，返回 ``(x, y, info)``。

    顺序很关键：**先按 ``wl_range`` 裁窗口**，再在窗口内挖 ``exclude`` /
    散射区间 / 饱和平台。反过来的话，挖掉区间会让窗口两端的点被误删。
    """
    wl = np.asarray(wl, dtype=float).ravel()
    y = np.asarray(y, dtype=float).ravel()
    if wl.size != y.size:
        raise ValueError(f'波长与强度长度不一致：{wl.size} vs {y.size}')
    good = np.isfinite(wl) & np.isfinite(y)
    n_bad = int((~good).sum())
    wl, y = wl[good], y[good]
    if wl.size < 2:
        return np.array([]), np.array([]), {'dropped': n_bad,
                                            'dropped_in_ranges': 0,
                                            'excluded_ranges': []}
    order = np.argsort(wl)
    wl, y = wl[order], y[order]
    # 同一波长出现多次时保留最后一个（仪器重扫/拼接处常见）
    uniq = np.concatenate(([True], np.diff(wl) > 0))
    wl, y = wl[uniq], y[uniq]

    # ---- 1) 裁拟合窗口 ----
    if wl_range is not None:
        lo, hi = float(wl_range[0]), float(wl_range[1])
        if hi < lo:
            lo, hi = hi, lo
        keep = (wl >= lo) & (wl <= hi)
        wl, y = wl[keep], y[keep]

    # ---- 2) 在窗口内挖掉指定区间 ----
    hole_ranges = []
    for rng in (exclude or []):
        try:
            lo, hi = float(rng[0]), float(rng[1])
        except (TypeError, IndexError, ValueError):
            continue
        hole_ranges.append((min(lo, hi), max(lo, hi)))
    # 激发波长处的瑞利散射 + 2λ 二级衍射：不挖掉会被当成谱带拟合
    if exclude_scatter is not None:
        for k in (1, 2):
            c = float(exclude_scatter) * k
            hole_ranges.append((c - scatter_width, c + scatter_width))
    # 探测器饱和平台（y 顶到量程的连续多点）：峰高由量程决定，不能当谱带
    clipped = detect_clipped(wl, y, min_points=clipped_min_points) if drop_clipped else []
    hole_ranges.extend(clipped)

    dropped_in_ranges = 0
    for lo, hi in hole_ranges:
        hit = (wl >= lo) & (wl <= hi)
        dropped_in_ranges += int(hit.sum())
        wl, y = wl[~hit], y[~hit]

    return wl, y, {'dropped': n_bad,
                   'dropped_in_ranges': dropped_in_ranges,
                   'excluded_ranges': hole_ranges,
                   'clipped_ranges': clipped}


def decompose_bands(wl, y, n_peaks=None, model='gaussian', baseline='const',
                    wl_range=None, exclude=None, exclude_scatter=None,
                    scatter_width=12.0, drop_clipped=True,
                    clipped_min_points=3, max_peaks=6, criterion='bic',
                    min_separation=0.45, min_share=0.01, max_r2_drop=0.01,
                    min_fwhm_pts=3.0, n_starts=6, seed=0, maxfev=40000,
                    verbose=False):
    """把一条光谱分解成若干条谱带，返回每条带的峰位/峰高/半高宽/**面积**/占比。

    参数
    ----
    wl, y : array_like
        波长与强度（吸收值或荧光强度）。不等间距、含 NaN 都能处理。
    n_peaks : int | None
        ``None``（默认）= 自动定阶：在 1…``max_peaks`` 里按 ``criterion`` 选。
        给了整数就**只**拟合该峰数（不再扫描，结果里 ``order_scan`` 为空）。
    model : {'gaussian','lorentzian','pseudo_voigt'}
        峰形。仪器展宽为主用 ``gaussian``；谱带两翼拖很长（稀土、固态谱）
        用 ``lorentzian`` 或 ``pseudo_voigt``，否则高斯会把尾巴截断。
    baseline : {'none','const','linear'}
        本底模型。已扣本底给 ``none``；常规给 ``const``；有线性漂移给 ``linear``。
    wl_range : (lo, hi) | None
        拟合窗口（nm）。**强烈建议给**：把散射峰、倍频峰、别的色带排除在外，
        窗口越窄，"几条带"这个问题越明确。
    exclude : list[(lo, hi)] | None
        额外挖掉的数据区间（如 2λ 二级衍射峰）。
    exclude_scatter : float | None
        给激发波长 λ_ex 时，自动挖掉 ``λ_ex ± scatter_width`` 与
        ``2λ_ex ± scatter_width``（瑞利散射 + 二级衍射）。

        **已知限制**：这是**整批统一**的一个值，不会按每条谱自己的 λ_ex
        分别处理。一个文件夹里混着多个激发波长时（例如实测的
        ``20260723-ESIPT-1-DMF`` 同一个 CSV 里既有 EX=460 又有 EX=350），
        给单个数值只能挖掉其中一条的散射位置，另一条的散射峰会被留在
        拟合窗口里。此时应当：① 按 λ_ex 分组、分几次调用；或
        ② 用 ``exclude=[(lo, hi), ...]`` 把所有散射区间一次列全。
        （想做"按每条谱自动取 λ_ex"需要 ``load_bands_spectra`` 返回的
        ``ex_wl`` 字段逐条驱动，本模块**目前没有**实现这条链路。）
    drop_clipped : bool
        **默认开启**。自动检测探测器**饱和平台**（连续 ≥ ``clipped_min_points``
        个点的强度都等于全谱最大值）并整段挖掉。FE30 量程上限 50000，
        实测 ESIPT 的 460 nm 激发谱在 459–463 nm 连续 5 个点全顶到 50000
        （350 nm 激发谱在 346–355 nm 连续 10 个点）——那是散射峰被削平，
        不是谱带。拟合会把它当成一条"又高又窄"的带并分走一大块面积占比，
        使双发射比值指向一条不存在的谱带（实测该样品因此得到 460.9 nm 的
        假带、占比 30.9%）。真要在饱和数据上强行拟合，传 ``False``。
    clipped_min_points : int
        判饱和所需的最少连续点数（默认 3）。设 1 会把所有"等于最大值"的点
        都当饱和，慎用。
    max_peaks : int
        自动定阶的峰数上限（默认 6）。别设太大：带数超过真实谱带数时，
        多出来的峰会去分噪声，面积占比虽然小但会污染比值。
    criterion : {'bic','aic'}
        定阶判据。``BIC=n·ln(RSS/n)+k·ln(n)``，``k`` 是**参数总个数**
        （每带 3 个：峰位/半高宽/峰高；伪 Voigt 4 个；再加本底参数）。
        BIC 对参数个数罚得比 AIC 重，默认用它。
    min_separation : float
        相邻峰的**最小可分辨比** ``sep / mean(FWHM)``（默认 0.45）。
        自动定阶时，低于它的峰数方案不参与 BIC 比选——实测真实光谱被过采样
        （0.5 nm 步长、残差 ρ≈0.995）时 BIC 会单调偏向峰数上限，选出的解里
        相邻峰挤成 0.2（同一条带被劈成两半）。设 0 可关闭该守卫、退回纯 BIC。
    min_share : float
        最小面积占比（默认 0.01）。BIC 选出的峰数里若有带子的面积占比
        低于此值且把它们去掉后 R² 下降不超过 ``max_r2_drop``，就当作"分噪声"
        删掉并重拟合——否则比值里会混进一片噪声带。
    max_r2_drop : float
        允许剔除微小谱带时 R² 的最大下降（默认 0.01）。
    min_fwhm_pts : float
        半高宽下限，单位是**数据点个数**（默认 3）。防止拟合去咬单点毛刺。
    n_starts : int
        多起点重启次数（默认 6，含初值本身）。取残差最小的解。
    seed : int
        多起点抖动的随机种子（固定种子 → 同样数据出同样结果）。
    verbose : bool
        打印定阶过程。

    返回
    ----
    dict
        ``ok`` / ``message``；每峰一个 dict 的 ``peaks`` 列表（按峰位排序），
        每项含 ``center / height / fwhm / sigma / area / area_share / eta /
        component / at_bound``；整体 ``r2 / rmse / rss / bic / aic /
        n_points / n_params / baseline / baseline_y / fit / residual /
        total_area``；自动定阶时还有 ``order_scan``（每个峰数的 BIC 等）。
        输入不可拟合时返回 ``ok=False``，其余字段为 NaN / 空列表（不会抛错）。

    示例
    ----
    >>> res = decompose_bands(wl, y, wl_range=(470, 620), n_peaks=2)
    >>> [(round(p['center'], 1), round(p['area_share'], 3)) for p in res['peaks']]
    """
    if model not in MODELS:
        raise ValueError(f"未知峰形 {model!r}，可选：{', '.join(MODELS)}")
    if baseline not in BASELINES:
        raise ValueError(f"未知本底 {baseline!r}，可选：{', '.join(BASELINES)}")
    if criterion not in ('bic', 'aic'):
        raise ValueError("criterion 只能是 'bic' 或 'aic'")

    try:
        x, yy, prep = _prepare_xy(wl, y, wl_range=wl_range, exclude=exclude,
                                  exclude_scatter=exclude_scatter,
                                  scatter_width=scatter_width,
                                  drop_clipped=drop_clipped,
                                  clipped_min_points=clipped_min_points)
    except ValueError as e:
        return _failed(str(e), model, criterion)
    if x.size < 8:
        return _failed(f'可用数据点太少（{x.size} 个），无法做谱带分解',
                       model, criterion)
    span = float(x[-1] - x[0])
    if span <= 0:
        return _failed('波长窗口宽度为 0', model, criterion)
    step = _step_of(x)
    fwhm_min = max(float(min_fwhm_pts) * step, span * 1e-3)
    fwhm_max = span * 1.5

    # 逐点权重：等权。这里显式保留接口位置，将来若要按仪器噪声加权。
    fixed = {'prep': prep, 'wl_range': (float(x[0]), float(x[-1]))}

    if n_peaks is not None:
        n_list = [int(n_peaks)]
        if n_list[0] < 1:
            return _failed('n_peaks 必须 ≥ 1', model, criterion)
    else:
        n_list = list(range(1, int(max(1, max_peaks)) + 1))

    best_by_n = {}
    warm = None
    for n in n_list:
        res_n = _fit_order(x, yy, n, model, baseline, fwhm_min, fwhm_max,
                           n_starts=n_starts, seed=seed, maxfev=maxfev,
                           warm=warm)
        if res_n is None:
            if verbose:
                _safe_print(f'  [WARN] {n} 峰拟合失败，跳过')
            best_by_n[n] = None
            continue
        best_by_n[n] = res_n
        warm = res_n['params']
        if verbose:
            _safe_print(f'  峰数 {n}: R²={res_n["r2"]:.5f} RMSE={res_n["rmse"]:.4g} '
                        f'BIC={res_n["bic"]:.2f}')

    ok_ns = [n for n, r in best_by_n.items() if r is not None]
    if not ok_ns:
        return _failed('所有峰数的拟合都失败了（数据可能过噪或窗口过窄）',
                       model, criterion)

    if n_peaks is not None:
        chosen = int(n_peaks)
        scan = []
        limited = False
    else:
        chosen, scan, limited = _select_by_criterion(
            ok_ns, best_by_n, criterion, min_separation)

    final = best_by_n[chosen]
    final = dict(final)
    final['order_scan'] = scan
    final['prep'] = prep
    final['wl_range'] = (float(x[0]), float(x[-1]))
    final['model'] = model
    final['model_label'] = MODEL_LABELS.get(model, model)
    final['criterion'] = criterion
    final['n_scan'] = len(scan)
    final['separation_limited'] = bool(limited)
    final['separation'] = _peak_separation(final['peaks'])
    final['min_separation'] = float(min_separation)

    # ---- 剔除"分噪声"的微小谱带（面积占比 < min_share 且 R² 掉得不多）----
    if n_peaks is None and min_share is not None and chosen > 1:
        pruned = final
        while pruned['n_peaks'] > 1:
            shares = [p['area_share'] for p in pruned['peaks']]
            if not shares or not np.isfinite(min(shares)) or min(shares) >= min_share:
                break
            # 按当前峰位重挑初值，拟合峰数 - 1（用 warm start 会带进一条多余带）
            alt = _fit_order(x, yy, pruned['n_peaks'] - 1, model, baseline,
                             fwhm_min, fwhm_max, n_starts=n_starts, seed=seed,
                             maxfev=maxfev, warm=None)
            if alt is None:
                break
            if pruned['r2'] - alt['r2'] > max_r2_drop:
                break
            alt['order_scan'] = scan
            alt['prep'] = prep
            alt['wl_range'] = final['wl_range']
            alt['model'] = model
            alt['model_label'] = MODEL_LABELS.get(model, model)
            alt['criterion'] = criterion
            alt['n_scan'] = len(scan)
            alt['separation_limited'] = final['separation_limited']
            alt['separation'] = _peak_separation(alt['peaks'])
            alt['min_separation'] = float(min_separation)
            alt['pruned_from'] = pruned['n_peaks']
            pruned = alt
        if pruned is not final:
            pruned['pruned'] = True
            final = pruned
    final.setdefault('pruned', False)
    return final


def _peak_separation(peaks):
    """相邻峰的最小平移/平均半高宽比 ``sep / mean(FWHM)``。

    这是**可分辨性**的常用判据：比值 ≳ 1 时两带在图上能看出（至少一个肩峰），
    比值 ≲ 0.4 时两个峰挤在同一个鼓包里，只有靠拟合才能分开——而拟合给出的
    峰位/面积此时对初值、噪声、本底模型都极敏感，不能再当作物理谱带使用。

    单峰返回 ``inf``；峰数 ≥ 2 但峰宽退化时返回 0。
    """
    peaks = sorted(peaks, key=lambda p: p['center'])
    if len(peaks) < 2:
        return float('inf')
    worst = float('inf')
    for a, b in zip(peaks[:-1], peaks[1:]):
        sep = float(b['center']) - float(a['center'])
        mean_fwhm = 0.5 * (float(a['fwhm']) + float(b['fwhm']))
        if not np.isfinite(mean_fwhm) or mean_fwhm <= 0:
            return 0.0
        worst = min(worst, sep / mean_fwhm)
    return float(worst)


def _select_by_criterion(ok_ns, best_by_n, criterion, min_separation):
    """自动定阶：先在"物理上分得开"的候选里按 BIC/AIC 选，再退让。

    为什么不能只用 BIC
    ------------------
    真实光谱是**过采样**的（LabSolutions 0.5 nm 步长，一条 150 nm 的带上有
    300 个点，相邻点残差相关系数实测 ρ≈0.995）。这时 ``n`` 远大于独立信息量，
    ``n·ln(RSS/n)`` 这一项把"多塞一个峰去咬残差纹理"的收益放大了几十倍，
    BIC 于是单调偏向峰数上限。实测罗丹明的甘油/水溶液谱：BIC 在 n=1..6 上
    单调下降，选出的 6 峰方案里相邻峰 ``sep/FWHM`` 只有 0.20（同一条带被劈成
    两半），而物理上合理的 2 峰解是主峰 548.5 + 肩峰 521.0。

    判据分两级：

    1. **可分辨性**（``min_separation``，默认 0.45）：候选解的相邻峰
       ``sep/mean(FWHM)`` 必须 ≥ 该值。低于它的峰数直接判为"不可分辨"，
       不参与比选——这一步与噪声水平无关，只看几何。
    2. 在剩下的候选里取 BIC 最小。若**没有任何**候选满足可分辨性
       （窄峰叠在宽带上等极端情形），退回全体候选取 BIC 最小，并在结果里
       标记 ``separation_limited=True``，提示用户"这次选中的峰数里有挤在一起的峰"。

    返回 ``(chosen_n, scan_rows, separation_limited)``。
    """
    key = 'bic' if criterion == 'bic' else 'aic'
    scan = []
    for n in sorted(ok_ns):
        r = best_by_n[n]
        sep = _peak_separation(r['peaks'])
        scan.append({'n_peaks': n, 'r2': r['r2'], 'rmse': r['rmse'],
                     'bic': r['bic'], 'aic': r['aic'],
                     'separation': sep,
                     'resolvable': bool(sep >= min_separation)})
    candidates = [s for s in scan if s['resolvable']]
    limited = False
    if not candidates:
        candidates = scan
        limited = True
    chosen = min(candidates, key=lambda s: s[key])['n_peaks']
    return chosen, scan, limited


def _fit_order(x, y, n_peaks, model, baseline, fwhm_min, fwhm_max,
               n_starts=6, seed=0, maxfev=40000, warm=None):
    """固定峰数 n_peaks 做多起点拟合，返回最佳结果 dict（失败返回 None）。"""
    lower, upper = _pack_bounds(x, y, n_peaks, model, baseline, fwhm_min, fwhm_max)
    p0, _nb = _pack_initial(x, y, n_peaks, model, baseline,
                            fwhm_min, fwhm_max, _x_ref_of(x))
    starts = []
    if warm is not None and len(warm) == len(p0):
        starts.append(np.asarray(warm, float))
    starts.append(p0)

    rng = np.random.default_rng(int(seed) + 1000 * n_peaks)
    nb = _n_base_params(baseline)
    per = _n_peak_params(model, model == 'pseudo_voigt')
    span = float(x[-1] - x[0])
    for _ in range(max(0, int(n_starts) - len(starts))):
        p = p0.copy()
        # 本底项不动，只抖峰参数：本底抖大了容易把谱带吃掉
        for i in range(n_peaks):
            b = nb + i * per
            p[b + 0] += rng.normal(0.0, 0.03 * span)
            p[b + 1] *= float(np.exp(rng.normal(0.0, 0.35)))
            p[b + 2] *= float(np.exp(rng.normal(0.0, 0.25)))
            if model == 'pseudo_voigt':
                p[b + 3] = float(np.clip(p[b + 3] + rng.normal(0.0, 0.2), 0.0, 1.0))
        p = np.clip(p, lower + 1e-9, upper - 1e-9)
        starts.append(p)

    best = None
    best_rss = float('inf')
    for p in starts:
        popt, rss, msg = _fit_once(x, y, n_peaks, model, baseline, p,
                                   lower, upper, maxfev)
        if popt is None:
            continue
        if rss < best_rss:
            best, best_rss = popt, rss
    if best is None:
        return None
    return _unpack_result(x, y, best, n_peaks, model, baseline, best_rss, 'bic')


# ======================== 3. 两带面积与比值 ========================

def band_areas(res, band_a=None, band_b=None):
    """在分解结果里按**峰位落在哪个窗口**归并面积，返回两带面积与比值。

    ``band_a`` / ``band_b`` 是 ``(lo, hi)`` 波长窗口（nm），也可以是
    ``None``（= 全部谱带，常用于"占全谱的份额"）或整数（第几条带，按下标 0 起）。
    比值定义为 **A_B / A_A**（B 除 A），与"keto*/enol*"这类写法一致。
    """
    if not res or not res.get('ok'):
        return {'a': float('nan'), 'b': float('nan'), 'ratio': float('nan'),
                'peaks_a': [], 'peaks_b': []}

    def _pick(spec):
        peaks = res['peaks']
        if spec is None:
            return list(range(len(peaks)))
        if isinstance(spec, (int, np.integer)):
            i = int(spec)
            return [i] if 0 <= i < len(peaks) else []
        lo, hi = float(spec[0]), float(spec[1])
        lo, hi = min(lo, hi), max(lo, hi)
        return [i for i, p in enumerate(peaks) if lo <= p['center'] <= hi]

    ia, ib = _pick(band_a), _pick(band_b)
    # 同一峰落在两个窗口（窗口重叠时）会重复计数，剔除掉 B 里的重复项
    ib = [i for i in ib if i not in ia]
    area_a = float(sum(res['peaks'][i]['area'] for i in ia))
    area_b = float(sum(res['peaks'][i]['area'] for i in ib)) if band_b is not None else float('nan')
    ratio = float(area_b / area_a) if (area_a > 0 and np.isfinite(area_b)) else float('nan')
    return {'a': area_a, 'b': area_b, 'ratio': ratio,
            'peaks_a': ia, 'peaks_b': ib}


def band_ratio_table(datasets, band_a, band_b, model='gaussian', n_peaks=None,
                     baseline='const', wl_range=None, exclude=None,
                     exclude_scatter=None, scatter_width=12.0,
                     drop_clipped=True, clipped_min_points=3, max_peaks=6,
                     criterion='bic', min_separation=0.45, normalize=False,
                     verbose=False):
    """对一批光谱逐条分解并算两带面积比，返回 ``(rows, results, skipped)``。

    ``rows`` 每项是 dict：``label / n_peaks / area_a / area_b / ratio / r2 /
    centers / shares``。``results`` 是对应的完整分解结果，``skipped`` 是
    没能分解的样品 ``(label, 原因)``。
    """
    rows, results, skipped = [], [], []
    for ds in _coerce_datasets(datasets):
        label = ds['label']
        y = ds['y']
        if normalize:
            m = float(np.nanmax(np.abs(y))) if y.size else 0.0
            if m > 0:
                y = y / m
        res = decompose_bands(ds['wl'], y, n_peaks=n_peaks, model=model,
                              baseline=baseline, wl_range=wl_range,
                              exclude=exclude, exclude_scatter=exclude_scatter,
                              scatter_width=scatter_width,
                              drop_clipped=drop_clipped,
                              clipped_min_points=clipped_min_points,
                              max_peaks=max_peaks,
                              criterion=criterion,
                              min_separation=min_separation, verbose=verbose)
        if not res.get('ok'):
            skipped.append((label, res.get('message', '分解失败')))
            continue
        ba = band_areas(res, band_a, band_b)
        results.append((label, res))
        rows.append({
            'label': label,
            'n_peaks': res['n_peaks'],
            'area_a': ba['a'],
            'area_b': ba['b'],
            'ratio': ba['ratio'],
            'r2': res['r2'],
            'centers': [p['center'] for p in res['peaks']],
            'shares': [p['area_share'] for p in res['peaks']],
            'peaks_in_a': ba['peaks_a'],
            'peaks_in_b': ba['peaks_b'],
        })
    return rows, results, skipped


# ======================== 4. 数据加载 ========================

def detect_spectrum_kind(filepath):
    """判断一个光谱文件是吸收还是发射（读前 60 行表头，编码依次试 utf-8/gbk/latin-1）。

    判别依据是仪器输出表头里的固定字样：吸收 = ``LabSolutions UV-Vis`` /
    ``波长(nm),吸收值``；发射 = ``发射数据组`` / ``Fixed/Offset`` / ``Wavelength nm``。
    都认不出时返回 ``'emission'``（与 ``plot_emission`` 的宽松默认一致）。
    """
    head = ''
    for enc in ('utf-8', 'gbk', 'latin-1'):
        try:
            with open(filepath, 'r', encoding=enc) as f:
                head = ''.join(f.readline() for _ in range(60))
            break
        except UnicodeDecodeError:
            continue
        except OSError:
            return 'emission'
    if 'LabSolutions UV-Vis' in head or '吸收值' in head or '吸收光谱' in head:
        return 'absorption'
    if '发射数据组' in head or 'Fixed/Offset' in head or 'Fixed/Offsets' in head:
        return 'emission'
    if 'Wavelength nm' in head or 'EX WL' in head or '发射 扫描' in head:
        return 'emission'
    return 'emission'


def _expand_files(files):
    """单个路径 / 路径列表 / 通配符 → 文件列表（文件夹会被展开成其中的 CSV/TXT）。"""
    if isinstance(files, (str, Path)):
        files = [files]
    out = []
    for f in files or []:
        p = Path(f)
        if p.is_dir():
            out.extend(sorted(glob.glob(str(p / '*.csv')) + glob.glob(str(p / '*.txt'))))
            continue
        s = str(f)
        if any(ch in s for ch in '*?['):
            out.extend(sorted(glob.glob(s)))
        else:
            out.append(s)
    return out


def load_bands_spectra(files, kind='auto', verbose=False, errors=None):
    """读一批光谱，返回 ``[{'label','wl','y','kind','ex_wl','path'}, ...]``。

    ``files`` 可以是文件、文件夹或通配符；``kind`` 取 ``'auto'``（逐文件判吸收/
    发射）、``'emission'`` 或 ``'absorption'``。解析**全部委托**给现成模块
    （``plot_emission.load_spectra`` / ``plot_absorption.load_absorption_spectra``），
    本函数只做统一字段整理与失败跳过——一个文件夹里混着别的类型文件是常态。

    ``errors`` 传列表时把 ``(文件名, 原因)`` 追加进去，便于 GUI 说明"为什么少了几个"。
    """
    out = []
    for fp in _expand_files(files):
        try:
            k = detect_spectrum_kind(fp) if kind == 'auto' else kind
            if k == 'absorption':
                from plot_absorption import load_absorption_spectra
                data = load_absorption_spectra(fp, skip_metadata=True, verbose=False)
                for d in data or []:
                    wl = d.get('wl', d.get('wavelength'))
                    y = d.get('absorption', d.get('intensity'))
                    if wl is None or y is None:
                        continue
                    out.append({'label': str(d.get('label') or Path(fp).stem),
                                'wl': np.asarray(wl, float),
                                'y': np.asarray(y, float),
                                'kind': 'absorption', 'ex_wl': None,
                                'path': str(fp)})
            else:
                from plot_emission import load_spectra
                for d in load_spectra([fp], verbose=False):
                    wl = d.get('wl', d.get('wavelength'))
                    y = d.get('intensity', d.get('absorption'))
                    if wl is None or y is None:
                        continue
                    out.append({'label': str(d.get('label') or Path(fp).stem),
                                'wl': np.asarray(wl, float),
                                'y': np.asarray(y, float),
                                'kind': 'emission', 'ex_wl': d.get('ex_wl'),
                                'path': str(fp)})
            if verbose:
                _safe_print(f'  [OK] {Path(fp).name}: {k}')
        except Exception as e:          # 寿命衰减、别的仪器的文件……静默跳过
            if errors is not None:
                errors.append((Path(fp).name, str(e)))
            if verbose:
                _safe_print(f'  [SKIP] {Path(fp).name}: {e}')
    return out


def _coerce_datasets(datasets):
    """把多种写法统一成 ``[{'label','wl','y'}, ...]``。

    接受：``dict``（含 ``wl``/``y``，或 ``wavelength``/``intensity``/
    ``absorption``）、``(label, wl, y)`` 三元组、或它们的列表。
    """
    if datasets is None:
        return []
    if isinstance(datasets, dict):
        datasets = [datasets]
    out = []
    for item in datasets:
        if isinstance(item, dict):
            wl = item.get('wl', item.get('wavelength'))
            y = item.get('y', item.get('intensity', item.get('absorption')))
            if wl is None or y is None:
                raise ValueError('数据集 dict 缺 wl/y（或 wavelength/intensity/absorption）')
            out.append({'label': str(item.get('label') or item.get('name') or 'spectrum'),
                        'wl': np.asarray(wl, float),
                        'y': np.asarray(y, float),
                        'ex_wl': item.get('ex_wl')})
            continue
        if isinstance(item, (tuple, list)) and len(item) == 3:
            label, wl, y = item
            out.append({'label': str(label), 'wl': np.asarray(wl, float),
                        'y': np.asarray(y, float), 'ex_wl': None})
            continue
        raise ValueError('数据集格式不对：应为 dict 或 (label, wl, y) 三元组')
    return out


# ======================== 5. 绘图 ========================

#: 分峰配色（避开 matplotlib 默认循环里那两个偏浅的颜色，保证黑白打印也分得开）
_PEAK_COLORS = ['#1f77b4', '#d62728', '#2ca02c', '#ff7f0e',
                '#9467bd', '#8c564b', '#17becf', '#e377c2']


def save_figure(fig, path, dpi=None):
    """保存图片（自动建目录）；``dpi=None`` 时用 ``EXPORT_DPI_DEFAULT``。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=EXPORT_DPI_DEFAULT if dpi is None else dpi,
                bbox_inches='tight')
    return path


def _fmt(v, digits=4, unit=''):
    """把数值格式化成短字符串（大数用科学计数法）；非有限值显示 '—'。"""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    if not np.isfinite(f):
        return '—'
    if f == 0:
        s = '0'
    elif abs(f) >= 1e5 or abs(f) < 1e-3:
        s = f'{f:.{max(1, digits - 1):g}e}'
        mant, _, exp = s.partition('e')
        s = f'{mant}×10^{int(exp)}'
    else:
        s = f'{f:.{digits}g}'
    return f'{s} {unit}'.strip()


def plot_decomposition(wl, y, res, label='', save_path=None, figsize=(8.8, 5.6),
                       dpi=None, xlabel='波长 (nm)', ylabel='强度',
                       annotate=True, show_residual=True, fig=None):
    """画单条谱的分解图：实测 + 总拟合 + 各分峰 + 本底（下方面板画残差）。

    ``fig`` 传入现成画布（GUI 的画布）时就在它上面重画、不新建 figure，
    并**自己恢复边距**——MplCanvas 初始把 subplots 边距设成 0，不恢复的话
    坐标轴标签会被算到画布外。``save_path=None`` 时不存盘。
    返回 ``(fig, summary)``。
    """
    from matplotlib.lines import Line2D

    x = np.asarray(res.get('x', wl), float)
    yv = np.asarray(res.get('y', y), float)
    ok = bool(res.get('ok'))
    peaks = res.get('peaks', []) if ok else []

    if fig is None:
        fig = plt.figure(figsize=figsize)
    else:
        fig.clf()
    if show_residual:
        gs = fig.add_gridspec(2, 1, height_ratios=[3.4, 1.0], hspace=0.09)
        ax = fig.add_subplot(gs[0])
        axr = fig.add_subplot(gs[1], sharex=ax)
    else:
        ax = fig.add_subplot(111)
        axr = None

    ax.plot(x, yv, lw=1.1, color='#333333', label='实测数据', zorder=3)
    if ok and x.size:
        base = np.asarray(res.get('baseline_y', np.zeros_like(x)), float)
        handles = [Line2D([], [], color='#333333', lw=1.4, label='实测数据'),
                   Line2D([], [], color='#d62728', lw=1.8, label='总拟合')]
        ax.plot(x, res['fit'], lw=1.6, color='#d62728', label='总拟合', zorder=4)
        if res.get('baseline_model', 'none') != 'none':
            ax.plot(x, base, lw=1.0, ls='--', color='#7f7f7f', label='本底', zorder=2)
            handles.append(Line2D([], [], color='#7f7f7f', lw=1.0, ls='--', label='本底'))
        for i, p in enumerate(peaks):
            c = _PEAK_COLORS[i % len(_PEAK_COLORS)]
            comp = np.asarray(p['component'], float) + base
            ax.fill_between(x, base, comp, color=c, alpha=0.16, lw=0, zorder=1)
            ax.plot(x, comp, lw=1.2, ls='-', color=c, alpha=0.95, zorder=2)
            if annotate:
                txt = (f"分峰 {i + 1}: {p['center']:.1f} nm  "
                       f"FWHM {p['fwhm']:.1f} nm  占比 {p['area_share'] * 100:.1f}%")
            else:
                txt = f"分峰 {i + 1}"
            handles.append(Line2D([], [], color=c, lw=1.4, label=txt))
        # 图例放在**轴外右侧**：分峰数多时轴内一定会压住曲线
        ax.legend(handles=handles, fontsize=7.2, frameon=False, loc='upper left',
                  bbox_to_anchor=(1.012, 1.0), borderaxespad=0.0)
        stats = (f"模型 {res.get('model_label', '')} · {res['n_peaks']} 峰 · "
                 f"R² = {res['r2']:.5f}\n"
                 f"RMSE = {_fmt(res['rmse'])} · BIC = {_fmt(res['bic'], 5)}\n"
                 f"总面积 = {_fmt(res['total_area'])}")
        sep = res.get('separation')
        if sep is not None and np.isfinite(sep) and res['n_peaks'] > 1:
            stats += f"\n相邻峰 sep/FWHM = {sep:.2f}"
            if res.get('separation_limited'):
                stats += "（偏近）"
        ax.text(1.012, -0.02, stats, transform=ax.transAxes, fontsize=7.2,
                va='top', ha='left', color='#374151')
    elif x.size:
        ax.text(0.5, 0.5, f"未能分解：{res.get('message', '未知原因')}",
                transform=ax.transAxes, ha='center', va='center',
                fontsize=12, color='#b91c1c', wrap=True)

    ax.set_ylabel(ylabel)
    if axr is None:
        ax.set_xlabel(xlabel)
    ax.set_title(label or '谱带分解', fontsize=11.5, pad=7)
    ax.grid(True, ls='--', alpha=0.32)

    if axr is not None:
        if ok and x.size:
            axr.axhline(0.0, color='#9ca3af', lw=0.9, ls='-')
            axr.plot(x, res['residual'], lw=0.9, color='#1f77b4')
            rng = float(np.nanmax(np.abs(res['residual']))) if x.size else 0.0
            if rng > 0:
                axr.set_ylim(-1.25 * rng, 1.25 * rng)
        axr.set_ylabel('残差', fontsize=9)
        axr.set_xlabel(xlabel)
        axr.grid(True, ls='--', alpha=0.28)
        axr.tick_params(labelsize=8)
    ax.tick_params(labelsize=8.5)

    # 边距：右侧给图例+统计留位置（轴外元素太多时 bbox_inches='tight' 也兜不住）
    right = 0.72 if (ok and peaks) else 0.97
    if axr is not None:
        fig.subplots_adjust(left=0.10, right=right, top=0.93, bottom=0.13)
    else:
        fig.subplots_adjust(left=0.10, right=right, top=0.92, bottom=0.14)

    summary = {
        'label': label,
        'n_peaks': res.get('n_peaks', 0) if ok else 0,
        'r2': res.get('r2', float('nan')),
        'centers': [p['center'] for p in peaks],
    }
    if save_path is not None:
        save_figure(fig, save_path, dpi=dpi)
    return fig, summary


def plot_order_scan(res, save_path=None, figsize=(6.4, 3.8), dpi=None,
                    xlabel='峰数', ylabel='BIC'):
    """画自动定阶的 BIC 曲线（标明选中了哪个峰数、哪些峰数不可分辨）。

    不可分辨的峰数（``sep/FWHM`` 低于阈值）用灰色空心点画，并在图例里说明——
    只把"可分辨"的候选连成实线，避免读者误以为 BIC 的最小值一定被选中。
    没扫描过返回 ``(None, {})``。
    """
    scan = res.get('order_scan') or []
    if len(scan) < 2:
        return None, {}
    ns = [s['n_peaks'] for s in scan]
    bic = [s['bic'] for s in scan]
    fig, ax = plt.subplots(figsize=figsize)
    ok_pts = [(n, b) for n, b, s in zip(ns, bic, scan) if s.get('resolvable', True)]
    bad_pts = [(n, b) for n, b, s in zip(ns, bic, scan) if not s.get('resolvable', True)]
    if ok_pts:
        ax.plot([p[0] for p in ok_pts], [p[1] for p in ok_pts], 'o-',
                color='#1f77b4', lw=1.6, ms=5, label='可分辨')
    if bad_pts:
        ax.plot([p[0] for p in bad_pts], [p[1] for p in bad_pts], 'o',
                mfc='none', mec='#9ca3af', ms=5, mew=1.2,
                label='相邻峰过近（不参与比选）')
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.grid(True, ls='--', alpha=0.32)
    chosen = int(res.get('n_peaks', ns[0]))
    if chosen in ns:
        ax.plot([chosen], [bic[ns.index(chosen)]], 'o', ms=10, mfc='none',
                mec='#d62728', mew=1.6, label=f'选中 {chosen} 峰')
    ax.set_xticks(ns)
    ax.legend(fontsize=8, frameon=False, loc='upper right')
    ax.set_title('峰数选择（BIC 越小越好；相邻峰过近的方案不参与比选）', fontsize=10)
    fig.subplots_adjust(left=0.12, right=0.97, top=0.89, bottom=0.17)
    if save_path is not None:
        save_figure(fig, save_path, dpi=dpi)
    return fig, {'chosen_n': chosen}


def plot_bands_summary(records, save_path=None, figsize=None, dpi=None,
                       normalize=True, annotate=True, title='谱带分解汇总',
                       xlabel='波长 (nm)', ylabel='强度'):
    """把多条谱的分解结果排成网格画一张汇总图。

    ``records`` 是 ``[(label, res), ...]``。默认把每条谱按自身最大值归一化，
    这样不同浓度的样品能放在一起比较**谱形**（绝对强度另行看峰表）。
    """
    records = [(lb, r) for lb, r in records if r and r.get('ok')]
    if not records:
        return None, {}
    n = len(records)
    ncols = 1 if n == 1 else (2 if n <= 4 else 3)
    nrows = int(math.ceil(n / ncols))
    if figsize is None:
        figsize = (4.3 * ncols + 1.2, 2.9 * nrows + 0.7)
    fig, axes = plt.subplots(nrows, ncols, figsize=figsize, squeeze=False)
    flat = axes.ravel()
    for ax, (label, res) in zip(flat, records):
        x = np.asarray(res['x'], float)
        yv = np.asarray(res['y'], float)
        fit = np.asarray(res['fit'], float)
        base = np.asarray(res['baseline_y'], float)
        scale = 1.0
        if normalize:
            m = float(np.max(yv)) if yv.size else 0.0
            if m > 0:
                scale = m
        ax.plot(x, yv / scale, lw=0.9, color='#333333')
        ax.plot(x, fit / scale, lw=1.3, color='#d62728', alpha=0.92)
        for i, p in enumerate(res['peaks']):
            c = _PEAK_COLORS[i % len(_PEAK_COLORS)]
            ax.plot(x, (np.asarray(p['component'], float) + base) / scale,
                    lw=1.0, ls='--', color=c, alpha=0.9)
            if annotate:
                ypk = (p['height'] + float(np.interp(p['center'], x, base))) / scale
                ax.annotate(f"{p['center']:.0f}nm/{p['area_share'] * 100:.0f}%",
                            xy=(p['center'], ypk), xytext=(2, 4),
                            textcoords='offset points', fontsize=6.6,
                            color=c)
        ax.set_title(f'{label}\n{res["n_peaks"]} 峰   R²={res["r2"]:.4f}',
                     fontsize=8, pad=3)
        ax.grid(True, ls='--', alpha=0.28)
        ax.tick_params(labelsize=7)
        if normalize:
            ax.set_ylim(-0.04, 1.18)
        ax.set_xlabel(xlabel, fontsize=8)
        ax.set_ylabel(f'{ylabel}（归一化）' if normalize else ylabel, fontsize=8)
    for ax in flat[n:]:
        ax.set_visible(False)
    fig.suptitle(title, fontsize=12)
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    if save_path is not None:
        save_figure(fig, save_path, dpi=dpi)
    return fig, {'n': n, 'ncols': ncols}


def plot_bands(datasets, save_dir='./plots', model='gaussian', n_peaks=None,
               baseline='const', wl_range=None, exclude=None,
               exclude_scatter=None, scatter_width=12.0,
               drop_clipped=True, clipped_min_points=3, max_peaks=6,
               criterion='bic', min_separation=0.45, min_share=0.01,
               normalize=False,
               dpi=None, figsize=(8.8, 5.6), verbose=True, name=None,
               xlabel='波长 (nm)', ylabel='强度', summary=True,
               order_scan_figure=False):
    """一键：逐条分解 + 每条一张分解图 + 一张汇总图 + 峰表 CSV。

    ``datasets`` 可以是 ``load_bands_spectra`` 的输出、dict 列表，或
    ``(label, wl, y)`` 三元组列表。图默认存 ``save_dir``、**不弹窗**。

    返回 ``dict(figures, summary_figure, order_scan_figure, results, csv,
    skipped, peaks_csv, summary)``。
    """
    save_dir = Path(save_dir)
    items = _coerce_datasets(datasets)
    figures, results, skipped, order_figs = [], [], [], []
    for ds in items:
        label = ds['label']
        y = ds['y']
        if normalize:
            m = float(np.nanmax(np.abs(y))) if y.size else 0.0
            if m > 0:
                y = y / m
        res = decompose_bands(ds['wl'], y, n_peaks=n_peaks, model=model,
                              baseline=baseline, wl_range=wl_range,
                              exclude=exclude, exclude_scatter=exclude_scatter,
                              scatter_width=scatter_width,
                              drop_clipped=drop_clipped,
                              clipped_min_points=clipped_min_points,
                              max_peaks=max_peaks,
                              criterion=criterion,
                              min_separation=min_separation,
                              min_share=min_share, verbose=False)
        if not res.get('ok'):
            skipped.append((label, res.get('message', '分解失败')))
            if verbose:
                _safe_print(f'  [SKIP] {label}: {res.get("message", "")}')
            continue
        results.append((label, res))
        stem = f'bands_{_sanitize(label)}'
        fp = save_dir / f'{stem}.png'
        fig, _s = plot_decomposition(ds['wl'], y, res, label=label,
                                     save_path=fp, figsize=figsize, dpi=dpi,
                                     xlabel=xlabel, ylabel=ylabel)
        plt.close(fig)
        figures.append(str(fp))
        if order_scan_figure and res.get('order_scan'):
            ofig, _ = plot_order_scan(res, save_path=save_dir / f'{stem}_order.png',
                                      dpi=dpi)
            if ofig is not None:
                plt.close(ofig)
                order_figs.append(str(save_dir / f'{stem}_order.png'))
        if verbose:
            _safe_print(f'  [OK] {label}: {res["n_peaks"]} 峰  '
                        f'R²={res["r2"]:.5f} → {fp.name}')
            for i, p in enumerate(res['peaks']):
                _safe_print(f'       #{i + 1} {p["center"]:.2f} nm  '
                            f'FWHM {p["fwhm"]:.2f} nm  '
                            f'面积 {_fmt(p["area"])}  '
                            f'占比 {p["area_share"] * 100:.2f}%')

    summary_fig = None
    if summary and results:
        sfp = save_dir / f'bands汇总_{name or "all"}.png'
        sfig, _ = plot_bands_summary(results, save_path=sfp, dpi=dpi,
                                     normalize=normalize or True,
                                     title=title_of(name) if name else '谱带分解汇总',
                                     xlabel=xlabel, ylabel=ylabel)
        if sfig is not None:
            plt.close(sfig)
            summary_fig = str(sfp)

    peaks_csv = None
    if results:
        peaks_csv = peaks_to_csv(results, save_dir / f'bands峰表_{name or "all"}.csv')
    return {
        'figures': figures,
        'summary_figure': summary_fig,
        'order_scan_figures': order_figs,
        'results': results,
        'skipped': skipped,
        'peaks_csv': str(peaks_csv) if peaks_csv else None,
        'datasets': items,
        'summary': {
            'n_spectra': len(results),
            'n_skipped': len(skipped),
            'n_peaks': [r[1]['n_peaks'] for r in results],
            'r2': [r[1]['r2'] for r in results],
        },
    }


def title_of(name):
    """把文件名/批名整理成图标题（去掉扩展名与多余下划线）。"""
    s = str(name)
    for ext in ('.csv', '.txt', '.xlsx', '.png'):
        if s.lower().endswith(ext):
            s = s[: -len(ext)]
    return s.replace('_', ' ').strip() or '谱带分解'


def compare_band_ratios(datasets, band_a, band_b, save_dir='./plots', name=None,
                        x_values=None, x_label='样品序号', y_label=None,
                        model='gaussian', n_peaks=None, baseline='const',
                        wl_range=None, exclude=None, exclude_scatter=None,
                        scatter_width=12.0, drop_clipped=True,
                        clipped_min_points=3,
                        max_peaks=6, criterion='bic',
                        min_separation=0.45, normalize=False,
                        figsize=(7.8, 5.2), dpi=None,
                        show_areas=True, annotate=False, verbose=True):
    """两带面积比随样品变化（ESIPT 的 keto*/enol* 就是这一条曲线）。

    对每个样品先做 :func:`decompose_bands`，再把**峰位落在 ``band_a`` 窗口内
    的谱带面积加起来**得 A_A、落在 ``band_b`` 内的加起来得 A_B，比值 = A_B/A_A。

    用"按峰位归窗"而不是"对原始曲线做梯形积分"的原因：两带重叠时窗口积分
    会把邻带的尾巴算进来（ESIPT 的 enol* 尾巴一直拖到 keto* 峰顶下面），
    分解后每条带的面积是解析的、互不重叠的。

    参数
    ----
    datasets : 同 :func:`plot_bands`
    band_a, band_b : (lo, hi) 或 int 或 None
        波长窗口（nm），或第几条带的下标，``None`` = 全部谱带。
    save_dir : str | None
        存盘的目录；``None`` 表示不存图（只返回数据，GUI 里用）。
    x_values : array_like | None
        横轴值（如浓度、时间）。不给就用样品序号 1…n。
    show_areas : bool
        为真时下方多一个面板画两带绝对面积（柱状）——比值在变时能分清是
        "分子涨"还是"分母跌"，这是只看比值看不出来的。

    返回
    ----
    dict: ``table``（每样品一行）、``rows``、``ratios``、``figure``、
    ``csv``、``results``、``skipped``、``band_a``、``band_b``、``summary``。
    """
    save_dir = Path(save_dir) if save_dir is not None else None
    rows, results, skipped = band_ratio_table(
        datasets, band_a, band_b, model=model, n_peaks=n_peaks,
        baseline=baseline, wl_range=wl_range, exclude=exclude,
        exclude_scatter=exclude_scatter, scatter_width=scatter_width,
        max_peaks=max_peaks, criterion=criterion,
        min_separation=min_separation, normalize=normalize)
    if verbose:
        for (label, why) in skipped:
            _safe_print(f'  [SKIP] {label}: {why}')
        for r in rows:
            _safe_print(f'  [RATIO] {r["label"]}: A={_fmt(r["area_a"])} '
                        f'B={_fmt(r["area_b"])} B/A={_fmt(r["ratio"])} '
                        f'({r["n_peaks"]} 峰, R²={r["r2"]:.5f})')
    if not rows:
        return {'table': [], 'rows': [], 'ratios': [], 'figure': None,
                'csv': None, 'results': [], 'skipped': skipped,
                'band_a': band_a, 'band_b': band_b,
                'summary': {'n': 0}}

    labels = [r['label'] for r in rows]
    if x_values is None:
        xs = list(range(1, len(rows) + 1))
        x_label = x_label or '样品序号'
    else:
        xs = [float(v) for v in x_values][:len(rows)]
        while len(xs) < len(rows):
            xs.append(float(len(xs) + 1))
    ratios = [r['ratio'] for r in rows]
    y_label = y_label or f'面积比 B/A（{_band_name(band_b)} / {_band_name(band_a)}）'

    if show_areas:
        fig, (ax, ax2) = plt.subplots(2, 1, figsize=figsize, sharex=True,
                                      gridspec_kw={'height_ratios': [2.1, 1.0],
                                                   'hspace': 0.12})
    else:
        fig, ax = plt.subplots(figsize=figsize)
        ax2 = None
    ax.plot(xs, ratios, 'o-', lw=1.6, ms=5.5, color='#d62728', label='面积比 B/A')
    for xi, yi, lb in zip(xs, ratios, labels):
        if np.isfinite(yi) and annotate:
            ax.annotate(lb, xy=(xi, yi), xytext=(4, 5), textcoords='offset points',
                        fontsize=7, color='#4b5563')
    ax.set_ylabel(y_label)
    ax.grid(True, ls='--', alpha=0.32)
    ax.set_title(name or '两带面积比', fontsize=11.5)
    if ax2 is None:
        ax.set_xlabel(x_label)
    if ax2 is not None:
        w = 0.38
        ax2.bar([v - w / 2 for v in xs], [r['area_a'] for r in rows], width=w,
                color='#1f77b4', alpha=0.85, label=f'A: {_band_name(band_a)}')
        ax2.bar([v + w / 2 for v in xs], [r['area_b'] for r in rows], width=w,
                color='#ff7f0e', alpha=0.85, label=f'B: {_band_name(band_b)}')
        ax2.set_ylabel('面积', fontsize=9)
        ax2.set_xlabel(x_label)
        ax2.grid(True, axis='y', ls='--', alpha=0.28)
        ax2.legend(fontsize=7.5, frameon=False, ncol=2, loc='upper left')
        ax2.tick_params(labelsize=8)
    ax.legend(fontsize=8, frameon=False, loc='best')
    fig.subplots_adjust(left=0.11, right=0.97, top=0.92, bottom=0.11)
    # save_dir=None 表示"只在内存里算、不落盘"（GUI 直接拿 figure 对象用）。
    # 此时 csv 也返回 None —— 早先的实现为了凑一个 csv 路径往系统临时目录
    # 写了个 bands_ratio.csv，等于"说好不落盘却偷偷落了盘"，还会和别的
    # 并发调用互相覆盖同名文件。
    fig_path = None
    csv_path = None
    if save_dir is not None:
        fp = save_dir / f'bands比值_{_sanitize(name or "all")}.png'
        fig_path = str(save_figure(fig, fp, dpi=dpi))
        csv_path = ratio_to_csv(
            rows, xs, x_label,
            save_dir / f'bands比值_{_sanitize(name or "all")}.csv')
    table = [{'label': r['label'], 'x': x, 'area_a': r['area_a'],
              'area_b': r['area_b'], 'ratio': r['ratio'],
              'n_peaks': r['n_peaks'], 'r2': r['r2']}
             for r, x in zip(rows, xs)]
    return {'table': table, 'rows': rows, 'ratios': ratios, 'figure': fig_path,
            'csv': None if csv_path is None else str(csv_path),
            'results': results, 'skipped': skipped,
            'band_a': band_a, 'band_b': band_b,
            'summary': {'n': len(rows), 'n_skipped': len(skipped),
                        'ratio_mean': float(np.nanmean(ratios)),
                        'ratio_min': float(np.nanmin(ratios)),
                        'ratio_max': float(np.nanmax(ratios))}}


def _band_name(spec):
    """把窗口/下标/None 变成图例里能看懂的名字。"""
    if spec is None:
        return '全部'
    if isinstance(spec, (int, np.integer)):
        return f'峰{int(spec) + 1}'
    try:
        lo, hi = float(spec[0]), float(spec[1])
        return f'{min(lo, hi):g}–{max(lo, hi):g} nm'
    except (TypeError, IndexError, ValueError):
        return str(spec)


def _sanitize(name):
    """文件名清洗：去掉 Windows 不允许的字符。"""
    s = str(name)
    for ch in '\\/:*?"<>|\n\r\t':
        s = s.replace(ch, '_')
    s = s.strip(' .')
    return s[:80] or 'spectrum'


# ======================== 6. CSV ========================

def peaks_to_csv(results, path):
    """把每峰一行的峰表写成 CSV（UTF-8 BOM，Excel 直接打开不乱码）。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['样品', '峰序号', '峰位(nm)', '峰高', '半高宽FWHM(nm)',
                    '面积', '面积占比', '峰形', 'eta', '峰位贴边界',
                    '总峰数', 'R2', 'RMSE', 'BIC', '本底模型', '本底参数'])
        for label, res in results:
            for i, p in enumerate(res['peaks'], 1):
                w.writerow([label, i, f'{p["center"]:.4f}', f'{p["height"]:.6g}',
                            f'{p["fwhm"]:.4f}', f'{p["area"]:.6g}',
                            f'{p["area_share"]:.6f}', p['model'],
                            '' if p['eta'] is None else f'{p["eta"]:.4f}',
                            '是' if p['at_bound'] else '否',
                            res['n_peaks'], f'{res["r2"]:.6f}',
                            f'{res["rmse"]:.6g}', f'{res["bic"]:.4f}',
                            res['baseline_model'],
                            '; '.join(f'{k}={v:.6g}'
                                      for k, v in res['baseline'].items())])
    return path


def ratio_to_csv(rows, xs, x_label, path):
    """把两带面积比写成 CSV（UTF-8 BOM）。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['样品', x_label, 'A区面积', 'B区面积', '面积比B/A', '总峰数',
                    'R2', '峰位(nm)'])
        for r, x in zip(rows, xs):
            w.writerow([r['label'], f'{x:g}', f'{r["area_a"]:.6g}',
                        f'{r["area_b"]:.6g}', f'{r["ratio"]:.6g}',
                        r['n_peaks'], f'{r["r2"]:.6f}',
                        '; '.join(f'{c:.2f}' for c in r['centers'])])
    return path


# ======================== 7. 文字摘要 ========================

def format_decomposition(res, max_peaks=8):
    """把分解结果写成多行中文摘要（供 GUI 信息栏 / 终端打印）。"""
    if not res or not res.get('ok'):
        return f"谱带分解失败：{(res or {}).get('message', '未知原因')}"
    lines = [f"谱带分解（{res.get('model_label', res.get('model'))}，"
             f"{res['n_peaks']} 峰）  R²={res['r2']:.5f}  "
             f"RMSE={_fmt(res['rmse'])}  BIC={_fmt(res['bic'], 5)}"]
    base = res.get('baseline') or {}
    if base and res.get('baseline_model', 'none') != 'none':
        lines.append(f"  本底({res['baseline_model']}): " +
                     ', '.join(f'{k}={_fmt(v)}' for k, v in base.items()))
    for i, p in enumerate(res['peaks'][:max_peaks], 1):
        extra = '' if p['eta'] is None else f"  η={p['eta']:.2f}"
        flag = '  ⚠峰位贴窗口边界' if p['at_bound'] else ''
        lines.append(f"  #{i} {p['center']:.2f} nm | 峰高 {_fmt(p['height'])} | "
                     f"FWHM {p['fwhm']:.2f} nm | 面积 {_fmt(p['area'])} | "
                     f"占比 {p['area_share'] * 100:.2f}%{extra}{flag}")
    if len(res['peaks']) > max_peaks:
        lines.append(f"  … 另有 {len(res['peaks']) - max_peaks} 峰未列出")
    lines.append(f"  合计面积 {_fmt(res['total_area'])}")
    if res.get('order_scan'):
        best = min(res['order_scan'], key=lambda s: s['bic'])
        lines.append(f"  定阶：峰值数扫描 {len(res['order_scan'])} 档，"
                     f"BIC 最小在 {best['n_peaks']} 峰"
                     f"{'（已按 min_share 精简）' if res.get('pruned') else ''}")
        sep = res.get('separation')
        if sep is not None and np.isfinite(sep):
            flag = '（相邻峰偏近，可分辨性存疑）' if res.get('separation_limited') else ''
            lines.append(f"  可分辨性：相邻峰最小 sep/FWHM = {sep:.2f}{flag}")
    return '\n'.join(lines)


# ======================== 8. 一键 / 命令行 ========================

def run_bands(folder=None, files=None, kind='auto', save_dir='./plots',
              model='gaussian', n_peaks=None, baseline='const', wl_range=None,
              exclude=None, exclude_scatter=None, scatter_width=12.0,
              drop_clipped=True, clipped_min_points=3,
              max_peaks=6, criterion='bic', min_separation=0.45,
              min_share=0.01, normalize=False,
              band_a=None, band_b=None, name=None, dpi=None, verbose=True,
              order_scan_figure=False):
    """一键：读文件夹（或文件列表）→ 逐条分解出图 → 可选两带面积比。

    ``folder`` 给文件夹，或直接给 ``files`` 列表/通配符。
    ``band_a``/``band_b`` 都给了才做比值图。返回 dict 里带上 ``datasets``，
    便于随后调用 :func:`compare_band_ratios` 换窗口再算。
    """
    if folder is not None:
        files = [str(folder)]
    files = _expand_files(files)
    if not files:
        raise ValueError('没有可用的光谱文件（folder/files 都没给）')
    if verbose:
        _safe_print(f'  [INFO] 共 {len(files)} 个文件，kind={kind}')
    errors = []
    datasets = load_bands_spectra(files, kind=kind, verbose=verbose, errors=errors)
    if not datasets:
        raise ValueError('一个光谱都没读进来（检查文件类型；'
                         + ('; '.join(f'{n}: {e}' for n, e in errors[:3]) if errors else '')
                         + '）')
    out = plot_bands(datasets, save_dir=save_dir, model=model, n_peaks=n_peaks,
                     baseline=baseline, wl_range=wl_range, exclude=exclude,
                     exclude_scatter=exclude_scatter, scatter_width=scatter_width,
                     drop_clipped=drop_clipped,
                     clipped_min_points=clipped_min_points,
                     max_peaks=max_peaks, criterion=criterion,
                     min_separation=min_separation,
                     min_share=min_share, normalize=normalize, dpi=dpi,
                     verbose=verbose, name=name,
                     order_scan_figure=order_scan_figure)
    out['datasets'] = datasets
    out['errors'] = errors
    if band_a is not None and band_b is not None and out['results']:
        rat = compare_band_ratios(datasets, band_a, band_b, save_dir=save_dir,
                                  name=name, model=model, n_peaks=n_peaks,
                                  baseline=baseline, wl_range=wl_range,
                                  exclude=exclude,
                                  exclude_scatter=exclude_scatter,
                                  scatter_width=scatter_width,
                                  drop_clipped=drop_clipped,
                                  clipped_min_points=clipped_min_points,
                                  max_peaks=max_peaks, criterion=criterion,
                                  min_separation=min_separation,
                                  normalize=normalize, dpi=dpi, verbose=verbose)
        out['ratios'] = rat
    return out


def main(argv=None):
    """命令行入口。``python plot_bands.py <文件夹|文件...> [选项]``"""
    ap = argparse.ArgumentParser(
        description='谱带分解与定量（多峰分解 + 两带面积比）',
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('paths', nargs='+', help='光谱文件、文件夹或通配符（可多个）')
    ap.add_argument('--kind', default='auto',
                    choices=['auto', 'emission', 'absorption'],
                    help='数据类型；auto = 逐文件按表头判断')
    ap.add_argument('--model', default='gaussian', choices=list(MODELS),
                    help='峰形（默认 gaussian）')
    ap.add_argument('--n-peaks', type=int, default=None,
                    help='峰数；不给则按 BIC 自动定阶')
    ap.add_argument('--max-peaks', type=int, default=6, help='自动定阶的峰数上限')
    ap.add_argument('--baseline', default='const', choices=list(BASELINES),
                    help='本底模型（默认 const）')
    ap.add_argument('--range', nargs=2, type=float, default=None,
                    metavar=('LO', 'HI'), help='拟合波长窗口（nm）')
    ap.add_argument('--exclude', nargs=2, type=float, action='append',
                    default=None, metavar=('LO', 'HI'),
                    help='挖掉的数据区间（可重复，如 --exclude 690 710）')
    ap.add_argument('--exclude-scatter', type=float, default=None,
                    metavar='EX', help='激发波长 λex：自动挖掉 λex 与 2λex 处的散射/倍频峰')
    ap.add_argument('--scatter-width', type=float, default=12.0,
                    help='--exclude-scatter 的挖除半宽（nm，默认 12）')
    ap.add_argument('--keep-clipped', action='store_true',
                    help='不自动挖掉探测器饱和平台（默认会自动挖掉；'
                         '顶到量程的平顶是散射被削，不是谱带）')
    ap.add_argument('--clipped-min-points', type=int, default=3,
                    help='判饱和所需的最少连续点数（默认 3）')
    ap.add_argument('--criterion', default='bic', choices=['bic', 'aic'],
                    help='定阶判据（默认 bic）')
    ap.add_argument('--min-separation', type=float, default=0.45,
                    help='相邻峰最小可分辨比 sep/mean(FWHM)，低于它的峰数方案'
                         '不参与 BIC 比选（默认 0.45；设 0 = 纯 BIC）')
    ap.add_argument('--min-share', type=float, default=0.01,
                    help='最小面积占比，低于此值的带子会被精简掉（默认 0.01）')
    ap.add_argument('--normalize', action='store_true', help='先把每条谱归一化再拟合')
    ap.add_argument('--band-a', nargs=2, type=float, default=None,
                    metavar=('LO', 'HI'), help='A 带窗口（nm），配 --band-b 出比值图')
    ap.add_argument('--band-b', nargs=2, type=float, default=None,
                    metavar=('LO', 'HI'), help='B 带窗口（nm）')
    ap.add_argument('--save-dir', default='./plots', help='图片与 CSV 输出目录')
    ap.add_argument('--name', default=None, help='输出文件名前缀 / 图标题')
    ap.add_argument('--dpi', type=float, default=None,
                    help=f'导出 DPI（缺省用 {EXPORT_DPI_DEFAULT}）')
    ap.add_argument('--order-figure', action='store_true',
                    help='额外输出每个样品的 BIC 定阶曲线图')
    ap.add_argument('--list', action='store_true', help='只列出读到的光谱，不拟合')
    args = ap.parse_args(argv)

    files = _expand_files(args.paths)
    if not files:
        _safe_print('没有找到任何光谱文件')
        return 1

    if args.list:
        errors = []
        datasets = load_bands_spectra(files, kind=args.kind, verbose=False,
                                      errors=errors)
        for d in datasets:
            wl = d['wl']
            _safe_print(f"  {d['label']}  [{d['kind']}]  {wl.size} 点  "
                        f"{wl.min():.1f}–{wl.max():.1f} nm  "
                        f"EX={d.get('ex_wl')}")
        for n, e in errors:
            _safe_print(f'  [SKIP] {n}: {e}')
        _safe_print(f'共 {len(datasets)} 条光谱（跳过 {len(errors)} 个文件）')
        return 0

    exclude = [tuple(r) for r in args.exclude] if args.exclude else None
    band_a = tuple(args.band_a) if args.band_a else None
    band_b = tuple(args.band_b) if args.band_b else None
    if (band_a is None) != (band_b is None):
        _safe_print('[WARN] --band-a 与 --band-b 需要同时给，否则不算比值')

    out = run_bands(files=files, kind=args.kind, save_dir=args.save_dir,
                    model=args.model, n_peaks=args.n_peaks,
                    baseline=args.baseline,
                    wl_range=tuple(args.range) if args.range else None,
                    exclude=exclude, exclude_scatter=args.exclude_scatter,
                    scatter_width=args.scatter_width,
                    drop_clipped=not args.keep_clipped,
                    clipped_min_points=args.clipped_min_points,
                    max_peaks=args.max_peaks, criterion=args.criterion,
                    min_separation=args.min_separation,
                    min_share=args.min_share, normalize=args.normalize,
                    band_a=band_a, band_b=band_b, name=args.name,
                    dpi=args.dpi, order_scan_figure=args.order_figure)
    _safe_print('')
    for label, res in out['results']:
        _safe_print(f'[{label}]')
        _safe_print(format_decomposition(res))
    _safe_print('')
    _safe_print(f"完成：{len(out['results'])} 条谱，跳过 {len(out['skipped'])} 条；"
                f"输出目录 {args.save_dir}")
    if out.get('ratios'):
        s = out['ratios']['summary']
        _safe_print(f"两带面积比：n={s['n']}，均值 {_fmt(s['ratio_mean'])}，"
                    f"范围 {_fmt(s['ratio_min'])}–{_fmt(s['ratio_max'])}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
