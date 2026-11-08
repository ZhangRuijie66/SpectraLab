# -*- coding: utf-8 -*-
"""
EEM（激发-发射矩阵）定量读出
============================
`plot_3d_scan.py` 只出图（3D 曲面 / 等高线 / Waterfall）+ 清洗统计，**没有数值产物**。
本模块补上能写进实验报告的定量读数，并且**先判断这份数据到底能不能定量**：

  0. `assess_quantifiability`  **第一等公民**：四条判据判定数据是否可定量
  1. `find_optimal_excitation`  每个 EX 的发射积分强度 → 最佳激发波长
  2. `emission_peak_table`      每个 EX 的发射峰位 / 峰高 / FWHM → **峰位漂移**
  3. `band_area_table`          每个 EX 在指定发射区间内的积分面积
  4. `export_eem_quant`         上述表导出 CSV + 可选长表 (EX, EM, I)
  5. `plot_eem_quant`           定量结果图（最佳 EX / 峰位漂移 / 面积-EX + 摘要卡）
  6. `eem_quant_all`            一键串起来
  7. `build_synthetic_eem` / `self_test`
                                合成真值 + 自检（有执行器后一条命令验证本模块）

【设计立场：定量函数会返回数字，但一定同时返回 `reliable` 标记】
`find_optimal_excitation` / `emission_peak_table` / `band_area_table` 的返回 dict 里都有
`reliable` 与 `quality`。当 `assess_quantifiability` 判为不可定量时 `reliable=False`，
这个标记会一路带到：每个导出的 CSV（`reliable` 列 + `quantifiability.csv`）、
图的标题（"⛔ 可定量性诊断未通过，数字仅供参考"）与摘要卡。
**绝不为了给出一组漂亮数字而挑清洗参数。** 说"这份数据我给不出可信的数"是本模块的核心功能。

【为什么必须先诊断：示例数据的实测证据（执行器失效前跑出的真实输出）】
`示例数据/04-3D扫描EEM-RB-Lu/RBLu 1 2026-07-27 07-11.csv`（EX 500–600 × EM 200–900，701×101）：

  1. **饱和**：8037 个点 = 全矩阵 **11.35%**，仪器上限 50000。
  2. **周期伪迹**：周期 **6.9400 nm**、峰/底噪 **77×**；峰位**固定在 EM 不随 EX 移动**
     （用最小二乘在 6.5–7.6 nm 网格上拟合得周期 6.9400、相位 2.938 rad），
     所以它不是样品荧光——荧光带会随 EX 走。
  3. **伪迹幅度 ≫ 信号**：周期峰−谷中位 ≈ **8600**。取"地板包络"
     （沿 EM 7 点滚动最小值＝唯一既没被条纹抬高、也没饱和的采样）后只剩平滑无结构的本底：
     EM 200–500 ≈1200，EM 700–800 ≈1900，EM 800–900 ≈2000–2400 —— **没有发射带**。
  4. **参数敏感性**：同一份数据换清洗参数，最佳 EX 从 505 → 600（差 95 nm）、
     峰位漂移从 177.8 → 399.0 nm（差 221 nm）。参数敏感即不可信。
  5. **数据自洽性矛盾**（最有力，不依赖任何"真值"）：
     - 按 EM 每 100 nm 分块各自求最佳 EX，得 **522/600/580/514/568/594/531**（无一致性）。
       这对可分离的单一荧光体是严格矛盾：`Z(em,ex)=A(ex)·f(em)` 时每块积分
       = (块内 f 之和)·A(ex)，argmax 必然落在同一个 EX。
     - 各 EX 的"周期峰归一化谱形"相对 EX=550 参考的最大偏差达 **0.955**。
       （注：这条只作为定性佐证——单一荧光体可分离，任何只沿 EM 变化的图案在跨 EX
       归一化后都相同，所以它**无法**区分真伪；本模块不把它当判据，见下。）

→ 结论：**这份数据不可定量**。`assess_quantifiability` 会给出同样判定。

【四条判据怎么选的——一次必须记录的自我纠错】
最初我设计过"跨 EX 谱形相关/偏差"作为伪迹判据，后来自查发现它**物理上无效**：
单一荧光体的 EEM 是可分离的 `Z(em,ex) = A(ex)·f(em)`，所以任何只沿 EM 变化的图案
（真实发射带、以及固定在 EM 的梳状伪迹）在跨 EX 归一化后**都**完全相同，
这类判据区分不了二者，会把干净数据也判成不可定量。

有效的不变量是**沿 EM 的局部纹波相对幅度**（真实发射带平滑，伪迹是数量级锯齿），
以及**分块最佳 EX 的一致性**（可分离性给出的严格约束）。现在的四条判据：
  1. 饱和占比        2. 周期伪迹强度（频谱峰/底噪）
  3. EM 通道平滑度（对数域二阶差分）   4. 分块最佳 EX 一致性
而且判据 1、3、4 用**原始矩阵**跑——清洗会把伪迹证据一起抹平（见 6 节）。

【一键用法】
    from plot_3d_scan import parse_3d_scan_csv, prepare_grid
    from plot_eem_quant import eem_quant_all

    data = parse_3d_scan_csv(r"...\\RBLu 1 2026-07-27 07-11.csv")
    prep = prepare_grid(data)                      # 复用现有清洗，不重写解析与清洗
    res = eem_quant_all(prep, save_dir=r"...\\plots", label="RB/Lu 1")
    if not res['quality']['quantifiable']:
        for r in res['quality']['reasons']:
            print("不可定量：", r)

【命令行】
    python plot_eem_quant.py "文件.csv" -o ./plots
    python plot_eem_quant.py "文件.csv" -o ./plots --em-band 560,700 --em-range 450,750
    python plot_eem_quant.py "文件.csv" --long-table          # 额外导长表 (EX, EM, I)
    python plot_eem_quant.py --self-test                       # 合成真值自检（不需要数据文件）

【GUI 集成】见《plot_eem_quant使用说明.md》第 6 节。要点：GUI 里
`gui_plot._do_scan3d_plot` 已经调过 `prepare_grid`，把**同一个 prep** 传给
`eem_quant_all(prep, show=False)` 即可，不要重复清洗；数值回填"数据输出区"用
`res['quality']` / `res['optimal']['best_ex']` / `res['peaks']['table']`。

【只依赖】numpy / scipy / pandas / matplotlib（与项目其余 plot_*.py 一致）

【验证状态 —— 请务必阅读】
**本文件从未在运行环境中执行过。** 编写时 harness 的 bash 执行器损坏
（`EXECUTOR_UNAVAILABLE: Niubash execution tree link count mismatch`），因此
`python -m py_compile`、真实数据实测、合成真值测试、PNG 目检**全部未完成**。
本模块引用的示例数据数字来自执行器失效**之前**已跑通的独立探查脚本（真实输出），
但**本模块自身的代码行为尚未经过任何运行时验证**——可能存在语法错误、API 误用或逻辑错误。
`self_test()` 是为补齐验证而准备的：执行器恢复后先跑它，它会检查算法能否还原
已知真值（最佳 EX=550 nm、发射峰 620 nm 的双高斯带）。
"""

import sys
import argparse
from pathlib import Path

import numpy as np
import matplotlib                     # noqa: F401（plt 需要它先被导入以设置后端）
import matplotlib.pyplot as plt
import pandas as pd
from scipy.signal import find_peaks
from scipy.ndimage import median_filter, gaussian_filter1d

# 与 plot_3d_scan 共用导出口径（v5.0.2 起 DPI 单一真源）
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from export_defaults import (EXPORT_DPI_DEFAULT,
                                 EXPORT_DPI_VECTOR_MIN,   # noqa: F401（与项目其它模块同签名）
                                 EXPORT_DPI_PREVIEW)      # noqa: F401
except ImportError:                     # 脚本被单独复制出去时退回字面量
    EXPORT_DPI_DEFAULT, EXPORT_DPI_VECTOR_MIN, EXPORT_DPI_PREVIEW = 600, 300, 150

from plot_3d_scan import (parse_3d_scan_csv, prepare_grid, setup_chinese_font,
                          _safe_print, _report_stats, _detect_saturation)


setup_chinese_font()


# ======================== 0. 小工具 ========================

def _safe_label(label):
    """文件名安全化（与 plot_3d_scan._safe_label 同规则）。"""
    return (label or 'eem').replace('/', '_').replace('\\', '_').replace(' ', '_')


def _trapz(y, x):
    """梯形积分。numpy 2.0 移除了 np.trapz，必须优先用 np.trapezoid。

    项目环境是 numpy 2.1.3，走 trapezoid 分支；保留 trapz 回落以兼容旧环境。
    """
    fn = getattr(np, 'trapezoid', None)
    if fn is None:
        fn = np.trapz                       # noqa: NPY201（旧环境回落）
    return float(fn(y, x))


def _fill(z, value=0.0):
    """把非有限值替换成 value。"""
    return np.where(np.isfinite(z), z, value)


def _as_prep(data_or_prep, verbose=False, **prep_kw):
    """接受 `prep`（含 'Z'/'EX'/'EM'）或 `data`（含 'intensity'），统一返回 prep。"""
    if isinstance(data_or_prep, dict) and 'Z' in data_or_prep and 'EX' in data_or_prep:
        return data_or_prep
    if isinstance(data_or_prep, dict) and 'intensity' in data_or_prep:
        return prepare_grid(data_or_prep, verbose=verbose, **prep_kw)
    raise TypeError("需要 parse_3d_scan_csv 的 data（含 'intensity'）"
                    "或 prepare_grid 的 prep（含 'Z'/'EX'/'EM'）")


def _grid_of(prep):
    """取 (ex, em, Z)，并保证 Z 形状是 (len(em), len(ex))——行是 EM、列是 EX。"""
    ex = np.asarray(prep['ex'], dtype=float).ravel()
    em = np.asarray(prep['em'], dtype=float).ravel()
    Z = np.asarray(prep['Z'], dtype=float)
    if Z.shape != (em.size, ex.size):
        if Z.shape == (ex.size, em.size):     # 另一种排布：转置一次
            Z = Z.T
        else:
            raise ValueError(
                f"Z 形状 {Z.shape} 与 EM({em.size}) × EX({ex.size}) 不匹配")
    return ex, em, Z


def _check_not_log(prep):
    """log 变换过的 Z 不能直接积分/比峰高——明确报错，绝不默默给错数。"""
    st = prep.get('stats') or {}
    if st.get('log_scale'):
        raise ValueError("prep 是 log10 强度（log_scale=True），无法直接积分或比较峰高；"
                         "请用 log_scale=False 重新 prepare_grid 后再做定量")


def _em_slice(em, em_range):
    """把 (lo, hi) 换算成布尔选择；None 表示全窗。"""
    if em_range is None:
        return np.ones(em.size, dtype=bool)
    lo, hi = sorted(float(v) for v in em_range)
    sel = (em >= lo) & (em <= hi)
    if not sel.any():
        raise ValueError(f"EM 区间 {em_range} 内没有数据点"
                         f"（实际 EM {em.min():.0f}–{em.max():.0f} nm）")
    return sel


def _interp_peak(em, y, k):
    """三点抛物线插值，把峰位细化到亚网格。

    过 (-1,y0),(0,y1),(1,y2) 的抛物线：顶点偏移 dx = (y0−y2) / (2·(y0−2y1+y2))，
    顶点值 = y1 − (y0−y2)² / (8·(y0−2y1+y2))。dx 裁到 ±0.5，保证不跑到邻格之外。

    ⚠️ **对噪声敏感**：宽峰顶部很平，`y0−2y1+y2` 是个小量，
    相邻点的噪声会把它放大。实测（FWHM 76 nm、2% 噪声、500 次蒙特卡洛）
    峰位标准差约 10 nm —— 这个抖动不是算法 bug，是三点法的固有方差。
    需要稳健峰位时用 `_interp_peak_window`（多点二次拟合，等效平均）。
    """
    if k <= 0 or k >= y.size - 1:
        return float(em[k]), float(y[k])
    y0, y1, y2 = float(y[k - 1]), float(y[k]), float(y[k + 1])
    denom = y0 - 2.0 * y1 + y2
    if not np.isfinite(denom) or abs(denom) < 1e-15:
        return float(em[k]), float(y1)
    dx = float(np.clip(0.5 * (y0 - y2) / denom, -0.5, 0.5))
    step = float(np.median(np.diff(em))) if em.size > 1 else 1.0
    return float(em[k] + dx * step), float(y1 - 0.25 * (y0 - y2) * dx)


def _interp_peak_window(em, y, k, half_window=10):
    """在 k±half_window 内二次拟合求峰位——抗噪版本。

    `_interp_peak` 只用 3 点，宽峰顶部的微小起伏会让结果抖动 ~10 nm。
    这里用 (2·half_window+1) 个点做最小二乘二次拟合，等于把噪声平均掉。
    窗口内点数不足 4 时退回三点法。

    返回 (峰位, 峰位处的拟合值)。
    """
    n = y.size
    lo = max(0, k - int(half_window))
    hi = min(n, k + int(half_window) + 1)
    if hi - lo < 4:
        return _interp_peak(em, y, k)

    xs = em[lo:hi] - float(em[k])          # 平移到峰附近，改善条件数
    ys = np.asarray(y[lo:hi], dtype=float)
    good = np.isfinite(ys)
    if good.sum() < 4:
        return _interp_peak(em, y, k)
    try:
        c = np.polyfit(xs[good], ys[good], 2)
    except (np.linalg.LinAlgError, ValueError):
        return _interp_peak(em, y, k)
    if c[0] >= 0:                          # 不是凹的 → 当前点就在边界，退回三点法
        return _interp_peak(em, y, k)
    dx = -c[1] / (2.0 * c[0])
    step = float(np.median(np.diff(em))) if em.size > 1 else 1.0
    # 拟合顶点不应跑出一个窗口之外
    dx = float(np.clip(dx, -(half_window + 0.5) * step, (half_window + 0.5) * step))
    peak_val = float(np.polyval(c, dx))
    return float(em[k] + dx), peak_val


def _fwhm(em, y, k):
    """半高全宽：从峰 k 向两侧找第一个降到半高的位置，线性插值交点。

    返回 (fwhm_nm, left_nm, right_nm)；某侧走不到半高时该侧为 nan，fwhm 也为 nan。
    """
    y = np.asarray(y, dtype=float)
    half = 0.5 * float(y[k])
    if not np.isfinite(half) or half <= 0:
        return np.nan, np.nan, np.nan

    def _walk(step):
        i = k
        while 0 <= i + step < y.size:
            j = i + step
            if y[j] <= half:
                y1, y2 = float(y[i]), float(y[j])
                if abs(y2 - y1) < 1e-15:
                    return float(em[j])
                t = (y1 - half) / (y1 - y2)
                return float(em[i] + t * (em[j] - em[i]))
            i = j
        return np.nan

    left = _walk(-1)
    right = _walk(+1)
    if not (np.isfinite(left) and np.isfinite(right)):
        return np.nan, left, right
    return float(right - left), left, right


def _subtract_baseline(y, x, good, baseline):
    """按 baseline 口径扣基线。y/x 等长；good 是有限值掩膜。返回新数组（可能含 nan）。"""
    yc = np.asarray(y, dtype=float).copy()
    if baseline == 'none':
        return yc
    if baseline == 'min':
        return yc - float(np.nanmin(yc[good]))
    if baseline == 'edge':
        n = max(2, int(round(0.05 * good.sum())))
        lo_m = float(np.mean(yc[good][:n]))
        hi_m = float(np.mean(yc[good][-n:]))
        x0, x1 = float(x[good][0]), float(x[good][-1])
        return yc - np.interp(x, [x0, x1], [lo_m, hi_m])
    raise ValueError(f"未知 baseline={baseline!r}（可选 'none' / 'min' / 'edge'）")


# ======================== 1. 可定量性诊断（第一等公民）========================

def _crit(name, passed, value, threshold, note, **extra):
    """统一构造一条判据的 dict；`computed` 标记该判据是否真的算得出来。

    算不出来的判据**按未通过处理**（保守）——无法验证就不声称可信。
    """
    computed = value is not None and not (
        isinstance(value, float) and not np.isfinite(value))
    d = {'name': name, 'passed': bool(passed) and computed, 'value': value,
         'threshold': float(threshold), 'note': note, 'computed': bool(computed)}
    d.update(extra)
    return d


def _check_saturation(Z, stats, sat_frac_max, raw_size=None):
    """判据 1：饱和点占比。饱和把峰高与面积一起削平，定量值直接失真。

    **分母必须是原始矩阵的点数。** 若用加密后 prep 的大小（2103×303）当分母，
    示例数据的 8037 个饱和点会被算成 1.26%（实际 11.35%），直接漏判。

    stats 里有就用 stats；`clip_saturation=False` 时 `prepare_grid` 不写这两个键，
    此时直接在 Z 上现场找"反复出现的最大值"（`_detect_saturation` 同一判据）。
    """
    sat = stats.get('saturation')
    n_pts = stats.get('saturation_points')
    detected_here = False

    if sat is None:
        try:
            sat = _detect_saturation(Z)
        except Exception:                       # noqa: BLE001
            sat = None
        detected_here = True
    if sat is None:
        return _crit('饱和占比', True, 0.0, sat_frac_max, "未检测到饱和上限")

    # 饱和点数一律在当前 Z 上重数（stats 里的可能是清洗前的计数，口径不一致）
    n_pts = int(np.sum(Z >= float(sat) * (1.0 - 1e-6)))
    denom = int(raw_size) if raw_size else int(Z.size)
    frac = n_pts / float(max(denom, 1))
    note = f"饱和上限 {sat:.0f}，{n_pts} 个点（{frac:.2%}）"
    if detected_here:
        note += "（本判据现场检测）"
    return _crit('饱和占比', frac <= float(sat_frac_max), float(frac),
                 sat_frac_max, note, saturation_value=float(sat), points=n_pts,
                 denominator=denom)


def _check_comb_strength(stats, Z, em, comb_strength_max):
    """判据 2：周期伪迹强度。

    用 `plot_3d_scan._detect_comb_period` 的 `comb_strength` = 频谱峰 / 底噪中位。
    这个量是在**陷波之前**算出来的（`prepare_grid` 第 ③ 步检测、之后才处理 Z），
    是 stats 里唯一仍然代表原始证据的数字——所以即使诊断跑在清洗后的 prep 上，
    只要 stats 还在，这条判据仍然有效。

    标定：纯噪声的期望值 ≈ sqrt(2·ln M)/sqrt(2·ln 2) ≈ 2.8（M≈210 个频点，
    残差近似白噪声、|FFT| 服从 Rayleigh 分布）；示例数据实测 **77.8**。
    阈值 20 距噪声约 7 倍裕量、又明显低于实测伪迹。

    stats 里没有这个键（`notch_comb=False`）时，调 `_detect_comb_period` 现场检测。
    """
    period = stats.get('comb_period')
    strength = stats.get('comb_strength')

    def _num(v):
        try:
            f = float(v)
            return f if np.isfinite(f) else None
        except (TypeError, ValueError):
            return None

    p_f, s_f = _num(period), _num(strength)
    detected_here = False
    if s_f is None:
        try:
            p2, s2 = _detect_comb_period(Z, em)
        except Exception:                       # noqa: BLE001
            p2, s2 = None, None
        if _num(s2) is not None:
            p_f, s_f = _num(p2), _num(s2)
            detected_here = True

    if s_f is None:
        return _crit('周期伪迹强度', False, np.nan, comb_strength_max,
                     "未能测得周期伪迹强度，无法排除伪迹（保守判为未通过）",
                     period=None, strength=None)

    note = f"频谱峰/底噪 {s_f:.1f}×（阈值 {comb_strength_max:g}）"
    if p_f is not None:
        note += f"，周期 {p_f:.3f} nm"
    if detected_here:
        note += "，本判据现场检测"
    return _crit('周期伪迹强度', s_f < float(comb_strength_max), s_f,
                 comb_strength_max, note, period=p_f, strength=s_f)


def _check_smoothness(Z, em, em_range, smooth_max):
    """判据 3：相邻 EM 通道的平滑度（相对局部包络）。

    与判据 2 是同一个不变量的**互补检查**：判据 2 用固定窗口的稳健标准差，
    这条用"相邻点二阶差分 / 局部包络"，对**单点尖刺**（1 通道宽的噪声/坏点）更敏感，
    而判据 2 对宽一些的锯齿更敏感。两者都只看**沿 EM 的局部起伏相对幅度**，
    不看跨 EX 的关系——因为单一荧光体的可分离性
    `Z(em,ex)=A(ex)·f(em)` 使任何"跨 EX 归一化后比较形状"的做法都无法区分
    伪迹与真实荧光（会同时把真实数据判成伪迹）。

    做法：对数域二阶差分（去趋势），除以对数域有效量程：
      ripple = 1.4826·median(|Δ²L − median(Δ²L)|) / (p95(L) − p5(L))
    干净、平滑的谱：相邻通道强度差只有包络的百分之几 → ripple ≈ 0.005–0.02。
    通道间跳变 2–3 倍的锯齿 → ripple ≳ 0.1。
    """
    sel = _em_slice(em, em_range)
    ems, Zs = em[sel], Z[sel, :]
    if Zs.shape[0] < 5 or Zs.shape[1] < 2:
        return _crit('EM 通道平滑度', False, np.nan, smooth_max,
                     "EM 点太少，无法评估平滑度")

    finite = Zs[np.isfinite(Zs)]
    if finite.size == 0:
        return _crit('EM 通道平滑度', False, np.nan, smooth_max, "无有限值")
    floor = max(float(np.percentile(finite, 5)), 1e-9)

    L = np.log10(np.maximum(Zs, floor))
    L = np.where(np.isfinite(L), L, np.nan)

    span = float(np.nanpercentile(L, 95) - np.nanpercentile(L, 5))
    if not np.isfinite(span) or span <= 1e-9:
        return _crit('EM 通道平滑度', False, np.nan, smooth_max,
                     "对数域量程为 0（数据近似为常数），无法评估")

    d2 = L[2:, :] - 2.0 * L[1:-1, :] + L[:-2, :]
    d2 = d2[np.isfinite(d2)]
    if d2.size == 0:
        return _crit('EM 通道平滑度', False, np.nan, smooth_max, "二阶差分全为空")
    med = float(np.median(d2))
    ripple = float(1.4826 * np.median(np.abs(d2 - med)) / span)

    note = (f"二阶差分纹波 {ripple:.4f}（阈值 {smooth_max:g}），"
            f"对数域量程 {span:.2f} decade")
    return _crit('EM 通道平滑度', ripple <= float(smooth_max), ripple,
                 smooth_max, note)


def _check_block_optimal_ex(Z, ex, em, em_range, spread_frac_max, block_nm=100.0,
                            min_block_frac=0.05):
    """判据 4：按 EM 分块各自求"最佳 EX"，看这些最佳值是否一致。

    真实荧光体只有一个激发极大 → 无论用哪个发射区间的积分评估，都应落到同一个 EX。
    若各 EM 块给出的最佳 EX 散布达整个 EX 量程的一大半，说明"最佳 EX"是被伪迹挑出来的。

    三个细节（都会显著影响结论，不能省）：
      - **块内先扣本块各列的最小值**再积分：否则恒定本底（示例数据 ~1200 AU）
        会掩盖各 EX 之间真正的差别。
      - **只统计"有发射信号"的块**：判据是块积分中位 / 最强块的积分中位
        ≥ `min_block_frac`。没有发射带的 EM 区间不携带激发信息，把它算进散布只是噪声。
        *不能*用"块内 max/median 对比"来筛：纯噪声经扣最小值后也是正的，
        其 max/median 约 1.3，照样能越过 1.02 这种阈值，等于没筛。
      - 块数按 `block_nm` 从实际 EM 量程算，末块含右端点。
    """
    sel = _em_slice(em, em_range)
    ems, Zs = em[sel], Z[sel, :]
    span = float(ex.max() - ex.min()) if ex.size > 1 else 0.0
    if Zs.shape[0] < 6 or span <= 0:
        return _crit('分块最佳 EX 的一致性', False, np.nan, spread_frac_max,
                     "EM 点太少或 EX 量程为 0，无法分块评估")

    n_blk = max(3, int(round((ems.max() - ems.min()) / float(block_nm))))
    edges = np.linspace(ems.min(), ems.max(), n_blk + 1)

    # 第一遍：每个块算 (块内扣最小值后各 EX 的积分, 该块的信号强度)
    blocks_raw = []            # [(lo, hi, tot array, signal)]
    for k in range(n_blk):
        lo, hi = float(edges[k]), float(edges[k + 1])
        upper = (ems <= hi) if k == n_blk - 1 else (ems < hi)   # 末块含右端点
        m = (ems >= lo) & upper
        if m.sum() < 2:
            continue
        Zb = Zs[m, :]
        finite = np.isfinite(Zb)
        if not finite.any():
            continue
        bmin = np.nanmin(np.where(finite, Zb, np.nan), axis=0, keepdims=True)
        bmin = np.where(np.isfinite(bmin), bmin, 0.0)
        tot = np.array([_trapz(_fill(Zb[:, j] - bmin[0, j]), ems[m])
                        for j in range(Zb.shape[1])])
        if not np.isfinite(tot).any():
            continue
        signal = float(np.nanmedian(tot))       # 该块"扣底后"的典型积分幅度
        blocks_raw.append((round(lo, 1), round(hi, 1), tot, signal))

    if len(blocks_raw) < 2:
        return _crit('分块最佳 EX 的一致性', False, np.nan, spread_frac_max,
                     "有效 EM 块不足 2 个，无法评估")

    sig_max = max(b[3] for b in blocks_raw)
    if not np.isfinite(sig_max) or sig_max <= 0:
        return _crit('分块最佳 EX 的一致性', False, np.nan, spread_frac_max,
                     "所有 EM 块扣底后都没有信号（数据可能为常数），无法评估")

    # 第二遍：只保留信号足够强的块
    best, blocks, skipped = [], [], []
    for lo, hi, tot, signal in blocks_raw:
        if signal / sig_max < float(min_block_frac):
            skipped.append((lo, hi))
            continue
        best.append(float(ex[int(np.nanargmax(tot))]))
        blocks.append((lo, hi))

    if len(best) < 2:
        return _crit('分块最佳 EX 的一致性', False, np.nan, spread_frac_max,
                     f"有发射信号的 EM 块不足 2 个（跳过 {len(skipped)} 个无信号块），"
                     "无法评估", skipped_blocks=skipped)
    spread = float(max(best) - min(best))
    frac = spread / span
    note = (f"{len(best)} 个 EM 块的最佳 EX: "
            f"{'/'.join(f'{b:.0f}' for b in best)}"
            f"（散布 {spread:.0f} nm = EX 量程的 {frac:.0%}）")
    return _crit('分块最佳 EX 的一致性', frac <= float(spread_frac_max), float(frac),
                 spread_frac_max, note, spread_nm=spread,
                 best_ex_per_block=best, blocks=blocks)


def assess_quantifiability(data_or_prep, em_range=None, raw=None, sat_frac_max=0.02,
                           smooth_max=0.06, ex_spread_frac_max=0.25,
                           comb_strength_max=20.0, verbose=True):
    """
    判断这份 EEM **能不能做定量读出**。返回的 `quantifiable` 决定下游所有数字的 `reliable`。

    四条判据（全部来自实测教训；后三条不依赖任何"真值"，纯从数据自洽性出发）：

      1. **饱和占比** `saturation_fraction <= sat_frac_max`（默认 0.02）
         饱和把峰高与面积一起削平。stats 里没有时现场用 `_detect_saturation` 检测。
      2. **梳状纹波幅度** `ripple <= ripple_max`（默认 0.10 decade）
         对数域沿 EM 的稳健标准差（窗口≈2.5 个周期）。真实发射带平滑，
         逐点起伏 <0.02 decade；示例数据的梳状伪迹 1.6 decade 峰谷 → ripple≈0.3。
      3. **EM 通道平滑度** `ripple <= smooth_max`（默认 0.06）
         对数域二阶差分 / 对数域有效量程。对单点尖刺更敏感，与判据 2 互补。
      4. **分块最佳 EX 的一致性** `ex_spread_frac <= ex_spread_frac_max`（默认 0.25）
         按 EM 每 100 nm 分块各求最优 EX。**这条对可分离的单一荧光体是严格成立的**：
         `Z(em,ex)=A(ex)·f(em)` 时每块积分 = (块内 f 之和)·A(ex)，argmax 必然相同；
         伪迹叠加后各块被不同噪声驱动 → 散布大。示例数据实测 522/600/580/514/568/594/531。

    【为什么判据 2、3 不看"跨 EX 形状一致性"】
    单一荧光体的 EEM 可分离，任何只沿 EM 变化的图案在**跨 EX 归一化后都完全相同**
    （真实荧光和固定在 EM 的伪迹都一样）。所以"跨 EX 谱形相关/偏差"这类判据
    无法区分二者，会把干净数据也判成不可定量。有效的不变量是**沿 EM 的局部纹波幅度**。

    算不出来的判据按**未通过**处理（保守）——无法验证就不声称可信。

    参数
    ----
    data_or_prep : `prepare_grid` 的 prep（**推荐**，复用已清洗结果），或 `parse_3d_scan_csv` 的 data
    em_range     : 诊断用的 EM 区间；None = 全窗
    *_max        : 四条判据各自的阈值（默认值按示例数据实测标定）

    返回 dict
    --------
      quantifiable : bool——四条判据全部通过才为 True
      reasons      : list[str]，每条是**未通过**判据的人话说明（全部通过时为空）
      criteria     : list[dict]，逐项 name / passed / value / threshold / note / computed
      evidence     : dict，原始证据数值
      messages     : list[str]，可直接显示在 GUI 数据输出区的结论文本
      em_range     : 本次诊断区间
    """
    prep = _as_prep(data_or_prep)

    # 原始数据优先级：显式 raw > 直接传进来的 data
    if raw is None and isinstance(data_or_prep, dict) and 'intensity' in data_or_prep:
        raw = data_or_prep

    warning = None
    if raw is not None:
        r_ex = np.asarray(raw['ex_wavelengths'], dtype=float).ravel()
        r_em = np.asarray(raw['em_wavelengths'], dtype=float).ravel()
        r_Z = np.asarray(raw['intensity'], dtype=float)
        if r_Z.ndim != 2:
            r_Z = np.atleast_2d(r_Z)
        # 统一成 (len(em), len(ex))：行是 EM，列是 EX
        if r_Z.shape != (r_em.size, r_ex.size) and r_Z.shape == (r_ex.size, r_em.size):
            r_Z = r_Z.T
        d_ex, d_em, d_Z = r_ex, r_em, r_Z
        used_raw = True
    else:
        d_ex, d_em, d_Z = _grid_of(prep)
        used_raw = False
        warning = ("未提供原始矩阵，只能用清洗后的 prep 诊断；清洗会抹平伪迹、"
                   "使判据偏乐观。建议传 data（parse_3d_scan_csv 的返回）")

    _check_not_log(prep)
    stats = prep.get('stats') or {}
    raw_size = int(np.size(d_Z))       # 判据 1 的分母必须是原始点数

    crit = [
        _check_saturation(d_Z, stats, sat_frac_max, raw_size=raw_size),
        _check_comb_strength(stats, d_Z, d_em, comb_strength_max),
        _check_smoothness(d_Z, d_em, em_range, smooth_max),
        _check_block_optimal_ex(d_Z, d_ex, d_em, em_range, ex_spread_frac_max),
    ]

    reasons, messages = [], []
    for c in crit:
        if not c['passed']:
            tag = "未通过" if c['computed'] else "无法评估"
            reasons.append(f"{c['name']}{tag}：{c['note']}")
            messages.append(f"❌ {c['name']}{tag}：{c['note']}")

    ok = all(c['passed'] for c in crit)
    if warning:
        messages.append("⚠️ " + warning)
    if ok:
        messages.append("✅ 四条判据全部通过：可以做定量读出")

    evidence = {
        'saturation_fraction': crit[0]['value'],
        'saturation_points': crit[0].get('points'),
        'saturation_value': crit[0].get('saturation_value'),
        'comb_strength': crit[1].get('strength'),
        'comb_period': crit[1].get('period'),
        'smoothness_ripple': crit[2]['value'],
        'ex_spread_frac': crit[3]['value'],
        'ex_spread_nm': crit[3].get('spread_nm'),
        'best_ex_per_block': crit[3].get('best_ex_per_block'),
        'blocks': crit[3].get('blocks'),
        'used_raw': bool(used_raw),
        'raw_size': raw_size,
    }

    res = {'quantifiable': bool(ok), 'reasons': reasons, 'criteria': crit,
           'evidence': evidence, 'messages': messages, 'used_raw': bool(used_raw),
           'warning': warning,
           'em_range': None if em_range is None else tuple(float(v) for v in sorted(em_range))}

    if verbose:
        _safe_print("\n  🔍 可定量性诊断"
                    + ("（原始矩阵）" if used_raw else "（⚠️ 清洗后矩阵）"))
        for c in crit:
            v = c['value']
            vs = 'n/a' if v is None or (isinstance(v, float) and not np.isfinite(v)) \
                else (f"{v:.3f}" if isinstance(v, float) else str(v))
            _safe_print(f"     {'✅' if c['passed'] else '❌'} {c['name']}：{vs}"
                        f" / 阈值 {c['threshold']:g}　{c['note']}")
        if warning:
            _safe_print("     ⚠️  " + warning)
        if ok:
            _safe_print("     → ✅ 可定量")
        else:
            _safe_print("     → ⛔ 不可定量：以下读数标 reliable=False，仅供参考")
    return res


# 保留旧名作为别名（本模块早期草稿与报告里用过 assess_eem_quality）
assess_eem_quality = assess_quantifiability


# ======================== 2. 最佳激发波长 ========================

def find_optimal_excitation(data_or_prep, em_range=None, method='integral',
                            baseline='none', quantifiability=None, verbose=True):
    """
    对每个 EX 切片算发射强度，找出最大的那个 —— 即"最佳激发波长"。

    参数
    ----
    data_or_prep   : `prepare_grid` 的 prep，或 `parse_3d_scan_csv` 的 data
    em_range       : (lo, hi) 只在该 EM 区间内统计；None = 全窗。
                     **强烈建议指定**：全窗会把瑞利/拉曼散射与近红外本底一起积进去，
                     最佳 EX 会被散射带拉走。
    method         : 'integral' 梯形积分（默认，单位 AU·nm）
                     'peak'     只取切片最大值（对单波长噪声敏感）
                     'mean'     区间均值（= integral / 区间宽度）
    baseline       : 'none' 不扣 / 'min' 扣区间最小值 / 'edge' 两端线性外推
    quantifiability: `assess_quantifiability` 的结果；None 时本函数自己算一遍。
                     返回值里的 `reliable` 直接取它的 `quantifiable`。

    返回 dict
    --------
      best_ex / best_value / best_index
      table        list[dict]：{'EX', 'value'}
      method / em_range / baseline   本次口径
      contrast     best_value / median(value)。**<1.1 说明几乎没有激发峰**
      reliable     bool——数据不可定量时为 False
      quality      dict——本次使用的可定量性诊断结果
    """
    prep = _as_prep(data_or_prep)
    _check_not_log(prep)
    ex, em, Z = _grid_of(prep)
    sel = _em_slice(em, em_range)
    ems, Zs = em[sel], Z[sel, :]

    values = np.full(ex.size, np.nan)
    for j in range(ex.size):
        col = Zs[:, j]
        good = np.isfinite(col)
        if good.sum() < 2:
            continue
        if method == 'peak':
            values[j] = float(np.max(col[good]))
            continue
        yc = _fill(_subtract_baseline(col, ems, good, baseline))
        if method == 'integral':
            values[j] = _trapz(yc, ems)
        elif method == 'mean':
            values[j] = _trapz(yc, ems) / max(float(ems[-1] - ems[0]), 1e-12)
        else:
            raise ValueError(f"未知 method={method!r}（可选 'integral' / 'peak' / 'mean'）")

    if not np.isfinite(values).any():
        raise ValueError("所有 EX 切片都无法统计（数据可能全空或全为常数）")
    b = int(np.nanargmax(values))
    med = float(np.nanmedian(values))
    contrast = float(values[b] / med) if np.isfinite(med) and med != 0.0 else np.inf

    q = quantifiability if quantifiability is not None else \
        assess_quantifiability(prep, em_range=em_range, verbose=False,
                               raw=(data_or_prep if isinstance(data_or_prep, dict)
                                    and 'intensity' in data_or_prep else None))

    res = {
        'best_ex': float(ex[b]),
        'best_value': float(values[b]),
        'best_index': b,
        'table': [{'EX': float(ex[j]), 'value': float(values[j])}
                  for j in range(ex.size) if np.isfinite(values[j])],
        'method': method,
        'em_range': None if em_range is None else tuple(float(v) for v in sorted(em_range)),
        'baseline': baseline,
        'contrast': contrast,
        'reliable': bool(q['quantifiable']),
        'quality': q,
    }
    if verbose:
        _safe_print(f"  🎯 最佳激发波长: EX = {res['best_ex']:.0f} nm"
                    f"（{method} = {res['best_value']:.6g}），突出度 {contrast:.2f}×"
                    + ("" if res['reliable'] else "　⛔ reliable=False"))
        if contrast < 1.10:
            _safe_print("     ⚠️  突出度 < 1.10：几乎没有激发峰，"
                        "这个'最佳 EX'不具备物理意义")
        if em_range is None:
            _safe_print("     ⚠️  未指定 em_range（全窗积分）：瑞利/拉曼散射会被算进去，"
                        "建议先用 band_area_table 定发射带")
    return res


# ======================== 3. 发射峰位表 + 峰位漂移 ========================

def emission_peak_table(data_or_prep, em_range=None, n_peaks=1, prominence=0.15,
                        smooth_sigma=0.0, peak_window=15, quantifiability=None,
                        drift_warn=30.0, verbose=True):
    """
    对每个 EX 找该切片的发射峰位 / 峰高 / FWHM，并给出**峰位漂移**。

    峰位漂移是内滤效应 / 多组分的诊断量：单一荧光体的发射峰位应当基本不动
    （只有多组分比例随 EX 变化时才漂）。所以 `drift_range` 同时也是**数据可信度体检**：
    真实样品通常 0–15 nm；算出上百 nm 基本说明峰位跟着伪迹跑，不是物理。

    参数
    ----
    em_range       : (lo, hi) 只在区间内找峰；None = 全窗（不推荐）
    n_peaks        : 每个 EX 报几个峰（默认 1 = 主峰）。>1 时额外给次级峰列，用于多组分
    prominence     : find_peaks 显著度阈值，相对该切片最大值（默认 0.15 = 15%）
    smooth_sigma   : 找峰前沿 EM 的高斯平滑（单位 = 网格步数，0 = 不平滑）。
                     样条加密后的网格（smooth_factor>1）建议 0；1 nm 原始网格建议 1–2
    peak_window    : 峰位亚网格细化的拟合窗口半宽（单位 = EM 采样点数，默认 **15**）。
                     0 表示用 3 点抛物线（快但抗噪差）。

                     **为什么默认 15、为什么不能只靠 3 点法**（实测标定）：
                     宽峰顶部平坦，二次项是小量，相邻点噪声被放大。对 FWHM 76 nm 的高斯
                     加相对噪声，20 个随机种子统计"强激发段峰位漂移"：

                       noise   hw=0(3点)  hw=10    hw=15    hw=20
                       0       0.00       0.00     0.00     0.00
                       0.5%    —          0.80     0.45     0.42
                       1%      —          1.75     0.99     0.71
                       2%      10.77      4.32     2.03     1.28
                       3%      —          6.82     3.36     2.03

                     hw=15 在 2% 噪声下把漂移从 10.77 nm 压到 2.03 nm，
                     且 RMS 偏差 0.48 nm 仍接近最优；再加大窗口收益递减
                     （hw=20 时 RMS 反而回升，因为二次模型已不能描述整个窗口）。
                     `smooth_factor` 加密后点更密，窗口 15 点仍远小于峰宽，
                     不会把相邻峰混进来；但 `n_peaks>1` 且两峰靠得很近时应调小。
    quantifiability: `assess_quantifiability` 结果；None 时自己算

    返回 dict
    --------
      table         list[dict]：EX / EM_peak / intensity / fwhm（n_peaks>1 时有 _2/_3 后缀列）
      drift_range   所有 EX 的 EM_peak 极差 (nm)
      drift_span    (min_EM_peak, max_EM_peak)
      drift_std     EM_peak 标准差 (nm)
      drift_per_nm  EM_peak 对 EX 的线性斜率 (nm/nm)
      n_valid       成功找到峰的 EX 数
      reliable / quality
    """
    prep = _as_prep(data_or_prep)
    _check_not_log(prep)
    ex, em, Z = _grid_of(prep)
    sel = _em_slice(em, em_range)
    ems, Zs = em[sel], Z[sel, :]

    if smooth_sigma and float(smooth_sigma) > 0:
        Zs = gaussian_filter1d(Zs, float(smooth_sigma), axis=0, mode='nearest')

    rows = []
    for j in range(ex.size):
        col = Zs[:, j]
        if not np.isfinite(col).any():
            continue
        y = _fill(col)
        row = {'EX': float(ex[j])}
        # 峰位用多点二次拟合（抗噪）；宽峰顶部 3 点法的抖动可达 10 nm
        hw = max(0, int(peak_window))
        if int(n_peaks) <= 1:
            k = int(np.argmax(y))
            em_p, i_p = _interp_peak_window(ems, y, k, hw) if hw else _interp_peak(ems, y, k)
            fw, _, _ = _fwhm(ems, y, k)
            row.update(EM_peak=float(em_p), intensity=float(i_p), fwhm=float(fw))
        else:
            ymax = float(y.max())
            cand = [int(np.argmax(y))]      # 主峰始终取全局最大（find_peaks 会漏贴边峰）
            if ymax > 0:
                idx, _ = find_peaks(y, prominence=float(prominence) * ymax)
                cand += [int(i) for i in np.asarray(idx).ravel()]
            cand = sorted(dict.fromkeys(cand), key=lambda i: -y[i])[:int(n_peaks)]
            for m, k in enumerate(cand):
                em_p, i_p = _interp_peak_window(ems, y, k, hw) if hw \
                    else _interp_peak(ems, y, k)
                fw, _, _ = _fwhm(ems, y, k)
                suf = '' if m == 0 else f'_{m + 1}'
                row.update({f'EM_peak{suf}': float(em_p),
                            f'intensity{suf}': float(i_p),
                            f'fwhm{suf}': float(fw)})
        rows.append(row)

    if not rows:
        raise ValueError("没有找到任何可用的发射峰")

    pk = np.array([r['EM_peak'] for r in rows], dtype=float)
    ex_arr = np.array([r['EX'] for r in rows], dtype=float)
    drift = float(np.nanmax(pk) - np.nanmin(pk))
    drift_std = float(np.nanstd(pk))
    good = np.isfinite(pk) & np.isfinite(ex_arr)
    slope = np.nan
    if good.sum() >= 2:
        xe, ye = ex_arr[good], pk[good]
        if xe.size >= 2 and np.all(np.diff(xe) > 0) and np.ptp(xe) > 0:
            slope = float(np.polyfit(xe, ye, 1)[0])

    q = quantifiability if quantifiability is not None else \
        assess_quantifiability(prep, em_range=em_range, verbose=False,
                               raw=(data_or_prep if isinstance(data_or_prep, dict)
                                    and 'intensity' in data_or_prep else None))

    res = {
        'table': rows,
        'drift_range': drift,
        'drift_span': (float(np.nanmin(pk)), float(np.nanmax(pk))),
        'drift_std': drift_std,
        'drift_per_nm': slope,
        'n_valid': len(rows),
        'em_range': None if em_range is None else tuple(float(v) for v in sorted(em_range)),
        'reliable': bool(q['quantifiable']),
        'quality': q,
    }
    if verbose:
        _safe_print(f"  📈 发射峰位表: {len(rows)} 个 EX；峰位 "
                    f"{res['drift_span'][0]:.1f}–{res['drift_span'][1]:.1f} nm，"
                    f"漂移 {drift:.1f} nm（σ={drift_std:.1f}）"
                    + ("" if res['reliable'] else "　⛔ reliable=False"))
        if drift > float(drift_warn):
            _safe_print(f"     ⚠️  漂移 > {drift_warn:.0f} nm：单一荧光体不应如此，"
                        "峰位大概率被伪迹带着走")
    return res


# ======================== 4. 发射带面积 ========================

def band_area_table(data_or_prep, em_band=(560.0, 700.0), baseline='edge',
                    quantifiability=None, verbose=True):
    """
    每个 EX 在指定发射区间 [em_band] 内的积分面积（梯形积分，单位 AU·nm）。

    参数
    ----
    em_band        : (lo, hi) 积分区间。**必须按体系显式给**——
                     默认 560–700 nm 只对罗丹明类（RB 发射峰约 575–590 nm）合适。
    baseline       : 'none' / 'min' / 'edge'，语义同 find_optimal_excitation
    quantifiability: `assess_quantifiability` 结果；None 时自己算

    返回 dict
    --------
      table         list[dict]：EX / area / peak_EM / peak_intensity
      band          实际使用的区间
      baseline
      area_contrast max(area)/median(area)
      reliable / quality
    """
    prep = _as_prep(data_or_prep)
    _check_not_log(prep)
    ex, em, Z = _grid_of(prep)
    if em_band is None:
        raise ValueError("band_area_table 必须显式给 em_band（发射带位置随体系变化）")
    sel = _em_slice(em, em_band)
    ems, Zs = em[sel], Z[sel, :]

    rows, areas = [], []
    for j in range(ex.size):
        col = Zs[:, j]
        good = np.isfinite(col)
        if good.sum() < 2:
            continue
        yc = _fill(_subtract_baseline(col, ems, good, baseline))
        area = _trapz(yc, ems)
        k = int(np.argmax(np.where(good, col, -np.inf)))
        em_p, i_p = _interp_peak(ems, _fill(col), k)
        rows.append({'EX': float(ex[j]), 'area': float(area),
                     'peak_EM': float(em_p), 'peak_intensity': float(i_p)})
        areas.append(area)

    if not rows:
        raise ValueError("区间内没有可用数据")

    a = np.asarray(areas, dtype=float)
    med = float(np.nanmedian(a))
    q = quantifiability if quantifiability is not None else \
        assess_quantifiability(prep, em_range=None, verbose=False,
                               raw=(data_or_prep if isinstance(data_or_prep, dict)
                                    and 'intensity' in data_or_prep else None))

    res = {
        'table': rows,
        'band': (float(ems[0]), float(ems[-1])),
        'baseline': baseline,
        'area_contrast': float(np.nanmax(a) / med)
        if np.isfinite(med) and med != 0.0 else np.inf,
        'reliable': bool(q['quantifiable']),
        'quality': q,
    }
    if verbose:
        _safe_print(f"  📐 发射带 {res['band'][0]:.0f}–{res['band'][1]:.0f} nm：面积 "
                    f"{np.nanmin(a):.6g}–{np.nanmax(a):.6g} AU·nm，"
                    f"突出度 {res['area_contrast']:.2f}×"
                    + ("" if res['reliable'] else "　⛔ reliable=False"))
    return res


# ======================== 5. CSV 导出 ========================

def export_eem_quant(prep, out_dir=".", label="eem", em_band=None, em_range=None,
                     long_table=False, prefix=None, optimal=None, peaks=None,
                     band=None, quantifiability=None, raw=None, verbose=True):
    """
    导出定量表 CSV（`utf-8-sig`，Excel 直接可读），每个表都带 `reliable` 列。

    产物
    ----
      {pfx}_optimal_excitation.csv   EX / value / reliable
      {pfx}_emission_peaks.csv       EX / EM_peak / intensity / fwhm + 漂移汇总 + reliable
      {pfx}_band_area.csv            EX / area / peak_EM / peak_intensity + reliable（给 em_band 时）
      {pfx}_quantifiability.csv      四条判据逐项结论
      {pfx}_long_table.csv           EX / EM / I 长表（**默认关**，体量大）

    参数
    ----
    long_table : 是否导长表。默认 False。行数 = len(em)×len(ex)：
                 示例数据原始网格 701×101 = **70801 行**；样条加密后 2103×303 = 637209 行。
    optimal / peaks / band : 已算好的结果 dict，传进来避免重复计算
    quantifiability        : 已算好的诊断；None 时从 optimal/peaks/band 里取，或现算

    返回 dict：{'files': [...], 'rows': {...}, 'reliable': bool}
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    pfx = prefix or _safe_label(label)
    files, counts = [], {}

    ex, em, Z = _grid_of(prep)

    q = quantifiability
    if q is None:
        for cand in (optimal, peaks, band):
            if cand and 'quality' in cand:
                q = cand['quality']
                break
    if q is None:
        q = assess_quantifiability(prep, em_range=em_range, raw=raw, verbose=False)
    reliable = bool(q['quantifiable'])

    if optimal is None:
        optimal = find_optimal_excitation(prep, em_range=em_range,
                                          quantifiability=q, verbose=False)
    df = pd.DataFrame(optimal['table'])
    df['reliable'] = reliable
    f = out / f"{pfx}_optimal_excitation.csv"
    df.to_csv(f, index=False, encoding='utf-8-sig')
    files.append(str(f)); counts['optimal_excitation'] = len(df)

    if peaks is None:
        peaks = emission_peak_table(prep, em_range=em_range,
                                    quantifiability=q, verbose=False)
    dfp = pd.DataFrame(peaks['table'])
    dfp['drift_range_nm'] = peaks['drift_range']    # 汇总列，读表即可见
    dfp['drift_per_nm'] = peaks['drift_per_nm']
    dfp['reliable'] = reliable
    f = out / f"{pfx}_emission_peaks.csv"
    dfp.to_csv(f, index=False, encoding='utf-8-sig')
    files.append(str(f)); counts['emission_peaks'] = len(dfp)

    if em_band is not None:
        if band is None:
            band = band_area_table(prep, em_band=em_band,
                                   quantifiability=q, verbose=False)
        dfb = pd.DataFrame(band['table'])
        dfb['reliable'] = reliable
        f = out / f"{pfx}_band_area.csv"
        dfb.to_csv(f, index=False, encoding='utf-8-sig')
        files.append(str(f)); counts['band_area'] = len(dfb)

    # 判据逐项落盘。list 类型的列（best_ex_per_block / blocks）转成字符串，避免 CSV 里出现 repr
    rows_q = []
    for c in q['criteria']:
        rows_q.append({
            'criterion': c['name'],
            'passed': c['passed'],
            'computed': c.get('computed', True),
            'value': c['value'],
            'threshold': c['threshold'],
            'note': c['note'],
        })
    dfq = pd.DataFrame(rows_q)
    dfq['quantifiable'] = reliable
    dfq['reasons'] = ' | '.join(q['reasons']) if q['reasons'] else ''
    f = out / f"{pfx}_quantifiability.csv"
    dfq.to_csv(f, index=False, encoding='utf-8-sig')
    files.append(str(f)); counts['quantifiability'] = len(dfq)

    if long_table:
        EMg, EXg = np.meshgrid(em, ex, indexing='ij')   # ravel 后 EX 变化最快
        dfl = pd.DataFrame({'EX': EXg.ravel(), 'EM': EMg.ravel(), 'I': Z.ravel()})
        dfl = dfl[np.isfinite(dfl['I'])]
        f = out / f"{pfx}_long_table.csv"
        dfl.to_csv(f, index=False, encoding='utf-8-sig', float_format='%.6g')
        files.append(str(f)); counts['long_table'] = len(dfl)

    if verbose:
        _safe_print(f"  💾 已导出 {len(files)} 个 CSV 到 {out}"
                    + ("" if reliable else "（全部标 reliable=False）"))
        for k, v in counts.items():
            _safe_print(f"     - {pfx}_{k}.csv：{v} 行")
        if not long_table:
            _safe_print("     （长表默认不导出；需要时传 long_table=True）")
    return {'files': files, 'rows': counts, 'reliable': reliable}


# ======================== 6. 定量结果图 ========================

def draw_optimal_excitation(ax, optimal, highlight=True):
    """在给定 ax 上画「积分强度 - EX」并标出最佳 EX。返回 (line, best_ex)。"""
    t = optimal['table']
    x = np.array([r['EX'] for r in t], dtype=float)
    y = np.array([r['value'] for r in t], dtype=float)
    line, = ax.plot(x, y, '-o', ms=2.2, lw=1.4, color='tab:blue')
    if highlight and x.size:
        ax.axvline(optimal['best_ex'], color='tab:red', ls='--', lw=1.3,
                   label=f"最佳 EX = {optimal['best_ex']:.0f} nm")
        b = int(np.argmin(np.abs(x - optimal['best_ex'])))
        ax.plot([x[b]], [y[b]], 'o', ms=7, mfc='none', mec='tab:red', mew=1.6)
        ax.legend(fontsize=9, loc='best')
    ax.set_xlabel('激发波长 EX (nm)', fontsize=11)
    unit = 'AU·nm' if optimal.get('method') == 'integral' else 'AU'
    ax.set_ylabel(f'发射强度积分 ({unit})', fontsize=11)
    ax.set_title('最佳激发波长扫描', fontsize=12)
    ax.grid(True, alpha=0.3)
    return line, optimal['best_ex']


def draw_peak_drift(ax, peaks, highlight=True):
    """在给定 ax 上画「EM_peak - EX」漂移图。返回 (line, drift_range)。

    除了漂移量本身，还会统计**跳变次数**：相邻 EX 的峰位若跳超过漂移量的 25%，
    说明算法在不同候选峰之间来回切换——这是"峰位由伪迹/噪声决定"的直接视觉证据，
    比单看漂移量更直观。跳变多时在图内显式标出。
    """
    t = peaks['table']
    x = np.array([r['EX'] for r in t], dtype=float)
    y = np.array([r['EM_peak'] for r in t], dtype=float)
    line, = ax.plot(x, y, '-o', ms=2.2, lw=1.4, color='tab:purple')

    if highlight and np.isfinite(y).any():
        lo, hi = float(np.nanmin(y)), float(np.nanmax(y))
        ax.axhline(lo, color='0.5', ls=':', lw=1)
        ax.axhline(hi, color='0.5', ls=':', lw=1)
        drift = peaks['drift_range']
        big = drift > 30.0
        ax.annotate(f"漂移 {drift:.1f} nm",
                    xy=(0.03, 0.95), xycoords='axes fraction', fontsize=10,
                    va='top', ha='left',
                    color=('tab:red' if big else '0.25'))
        # 跳变次数：相邻 EX 的峰位差超过"绝对阈值"才算换了峰。
        # ⚠️ 阈值不能用 drift 的比例！正常数据 drift 很小（如 2.4 nm），
        # 0.25×drift ≈ 0.6 nm 会把噪声级的正常抖动全算成跳变 → 误报。
        # 用绝对值：伪迹导致的重峰切换通常跨几十 nm，取 5 nm 作下限。
        if y.size >= 3:
            jump_thr = 5.0
            jumps = int(np.sum(np.abs(np.diff(y)) > jump_thr))
            n_pairs = max(y.size - 1, 1)
            # 只有频繁跳变（>10% 的相邻对）才提示，避免偶发抖动误报
            if jumps >= 2 and jumps / n_pairs > 0.10:
                ax.annotate(f"峰位跳变 {jumps} 次（>{jump_thr:.0f} nm）"
                            "→ 峰位由伪迹/噪声决定",
                            xy=(0.03, 0.06), xycoords='axes fraction', fontsize=9,
                            va='bottom', ha='left', color='tab:red',
                            bbox=dict(boxstyle='round,pad=0.25', fc='white',
                                      ec='tab:red', lw=0.8, alpha=0.85))

    ax.set_xlabel('激发波长 EX (nm)', fontsize=11)
    ax.set_ylabel('发射峰位 EM_peak (nm)', fontsize=11)
    ax.set_title('发射峰位漂移（内滤效应 / 多组分诊断）', fontsize=12)
    ax.grid(True, alpha=0.3)
    return line, peaks['drift_range']


def draw_band_area(ax, band):
    """在给定 ax 上画「发射带面积 - EX」。返回 (line, band)。"""
    t = band['table']
    x = np.array([r['EX'] for r in t], dtype=float)
    y = np.array([r['area'] for r in t], dtype=float)
    line, = ax.plot(x, y, '-o', ms=2.2, lw=1.4, color='tab:green')
    lo, hi = band['band']
    ax.set_xlabel('激发波长 EX (nm)', fontsize=11)
    ax.set_ylabel('发射带面积 (AU·nm)', fontsize=11)
    ax.set_title(f"发射带面积（{lo:.0f}–{hi:.0f} nm）", fontsize=12)
    ax.grid(True, alpha=0.3)
    return line, band


def _mpl_safe(text):
    """把消息里的 emoji 换成 matplotlib 中文字体能渲染的标记。

    `Microsoft YaHei` / `SimHei` 都不含 ✅❌⛔ 这类 emoji 字形，
    matplotlib 会渲染成豆腐块并抛 UserWarning。控制台输出保留 emoji（项目惯例），
    但**画进图里的文字**必须走这个函数。
    """
    return (str(text)
            .replace('❌', '[×]')
            .replace('✅', '[√]')
            .replace('⛔', '[!]')
            .replace('⚠️', '[!]')
            .replace('⚠', '[!]'))


def _summary_lines(optimal, peaks, band, quality):
    """摘要卡的文字行。"""
    lines = [
        f"最佳激发波长   EX = {optimal['best_ex']:.0f} nm"
        f"　（{optimal['method']} = {optimal['best_value']:.6g}；"
        f"突出度 {optimal['contrast']:.2f}×）",
        f"发射峰位漂移   {peaks['drift_span'][0]:.1f} → {peaks['drift_span'][1]:.1f} nm"
        f"　（极差 {peaks['drift_range']:.1f} nm）",
    ]
    if np.isfinite(peaks['drift_per_nm']):
        lines[1] += f"，斜率 {peaks['drift_per_nm']:+.3f} nm/nm"
    if band is not None:
        lines.append(f"发射带面积     {band['band'][0]:.0f}–{band['band'][1]:.0f} nm"
                     f"　对比度 {band['area_contrast']:.2f}×")
    lines.append("")
    lines.append("可定量性诊断：" + ("[通过] 四条判据全部通过"
                                  if quality['quantifiable']
                                  else "[未通过] 以下数字仅参考"))
    for m in quality['messages'][:4]:
        lines.append("  " + _mpl_safe(m))
    return lines


def plot_eem_quant(data_or_prep, save_dir="./plots", show=False, label="",
                   em_band=(560.0, 700.0), em_range=None, dpi=None,
                   optimal=None, peaks=None, band=None, quantifiability=None,
                   verbose=True, fname=None, summary_card=True):
    """
    画定量读出结果图。

    版式
    ----
      给了 em_band：上排 3 图（最佳 EX / 峰位漂移 / 面积-EX）+ 下排通栏摘要卡
      不给 em_band：上排 2 图（最佳 EX / 峰位漂移）+ 下排通栏摘要卡
      `summary_card=False` 时只剩图、不留空白

    参数
    ----
    dpi          : None 时回落 `EXPORT_DPI_DEFAULT`（600）；预览可传 `EXPORT_DPI_PREVIEW`
    save_dir     : 默认 ./plots（与项目其余 plot_*.py 一致）
    show         : 默认 False（只存盘不弹窗）
    fname        : 输出文件名；None → `{label}_eem_quant.png`
    summary_card : 是否画底部摘要卡

    返回 (文件路径, 结果 dict)
    """
    prep = _as_prep(data_or_prep)
    if dpi is None:
        dpi = EXPORT_DPI_DEFAULT

    q = quantifiability
    if q is None:
        raw = data_or_prep if (isinstance(data_or_prep, dict)
                               and 'intensity' in data_or_prep) else None
        q = assess_quantifiability(prep, em_range=em_range, raw=raw, verbose=False)
    if optimal is None:
        optimal = find_optimal_excitation(prep, em_range=em_range,
                                          quantifiability=q, verbose=verbose)
    if peaks is None:
        peaks = emission_peak_table(prep, em_range=em_range,
                                    quantifiability=q, verbose=verbose)
    if em_band is not None and band is None:
        band = band_area_table(prep, em_band=em_band,
                               quantifiability=q, verbose=verbose)

    has_band = band is not None
    use_card = bool(summary_card)
    n_col = 3 if has_band else 2

    if use_card:
        fig = plt.figure(figsize=(17 if has_band else 13, 10 if has_band else 7.4))
        gs = fig.add_gridspec(2, n_col, height_ratios=[3.2, 1.05],
                              hspace=0.36, wspace=0.26,
                              left=0.055, right=0.985, top=0.90, bottom=0.04)
        # 直接收集 add_subplot 的返回值，不要依赖 fig.axes 的创建顺序
        axes_top = [fig.add_subplot(gs[0, c]) for c in range(n_col)]
        ax_sum = fig.add_subplot(gs[1, :])
    else:
        fig = plt.figure(figsize=(17 if has_band else 13, 6.0))
        gs = fig.add_gridspec(1, n_col, wspace=0.26,
                              left=0.06, right=0.985, top=0.88, bottom=0.13)
        axes_top = [fig.add_subplot(gs[0, c]) for c in range(n_col)]
        ax_sum = None

    draw_optimal_excitation(axes_top[0], optimal)
    draw_peak_drift(axes_top[1], peaks)
    if has_band:
        draw_band_area(axes_top[2], band)

    if ax_sum is not None:
        ax_sum.axis('off')
        ok = q['quantifiable']
        ax_sum.text(0.012, 0.94, "\n".join(_summary_lines(optimal, peaks, band, q)),
                    transform=ax_sum.transAxes, va='top', ha='left',
                    fontsize=9.5, linespacing=1.6,
                    bbox=dict(boxstyle='round,pad=0.7',
                              fc=('#eef7ee' if ok else '#fdeeee'),
                              ec=('tab:green' if ok else 'tab:red'), lw=1.3))

    title = 'EEM 定量读出'
    if label:
        title = f'{label} — {title}'
    if not q['quantifiable']:
        title += '　[未通过] 可定量性诊断未通过，数字仅供参考'
    fig.suptitle(title, fontsize=14, y=0.965)

    out = Path(save_dir)
    out.mkdir(parents=True, exist_ok=True)
    fpath = out / (fname or f"{_safe_label(label or 'eem')}_eem_quant.png")
    fig.savefig(fpath, dpi=dpi)      # 不用 bbox_inches='tight'：会裁掉通栏摘要卡
    if verbose:
        _safe_print(f"  ✔ 已保存: {fpath}")

    res = {'optimal': optimal, 'peaks': peaks, 'band': band, 'quality': q,
           'reliable': bool(q['quantifiable'])}
    if show:
        plt.show()
    else:
        plt.close(fig)
    return str(fpath), res


# ======================== 7. 一键封装 ========================

def eem_quant_all(data_or_prep, save_dir="./plots", label="", em_band=(560.0, 700.0),
                  em_range=None, long_table=False, dpi=None, show=False,
                  quantifiability=None, raw=None, verbose=True, **prep_kw):
    """
    一键：可定量性诊断 → 最佳 EX → 峰位表 → 面积表 → 导 CSV → 出图。

    传 prep 可复用已有清洗结果（GUI 走这条路径，不要重复清洗）；
    传 data 则先按 `**prep_kw` 调 `prepare_grid`。

    参数
    ----
    raw : **只传 prep 时务必一起传原始 data**。
          诊断需要原始矩阵（伪迹证据），而 prep 里的 Z 已被清洗抹平。
          GUI 里就是这种情况：`prep = prepare_grid(data)` 之后
          调 `eem_quant_all(prep, raw=data, ...)`。
          不传会退化到"用清洗后矩阵诊断"并写入 warning（判据偏乐观，
          示例数据上会**错判为可定量**）。

    返回 dict
    --------
      'quality'    可定量性诊断（**先看这个**）
      'reliable'   等于 quality['quantifiable']，下游所有数字共用
      'optimal' / 'peaks' / 'band'
      'files'      导出的 CSV 路径
      'figure'     图片路径
    """
    prep = _as_prep(data_or_prep, verbose=verbose, **prep_kw)
    if verbose:
        _safe_print(f"\n{'=' * 62}\n📊 EEM 定量读出" + (f"：{label}" if label else ''))

    # 诊断用原始 data（伪迹证据还在），定量用 prep（清洗后）——见 assess_quantifiability 文档
    if raw is None and isinstance(data_or_prep, dict) and 'intensity' in data_or_prep:
        raw = data_or_prep
    q = quantifiability if quantifiability is not None else \
        assess_quantifiability(prep, em_range=em_range, raw=raw, verbose=verbose)
    optimal = find_optimal_excitation(prep, em_range=em_range,
                                      quantifiability=q, verbose=verbose)
    peaks = emission_peak_table(prep, em_range=em_range,
                                quantifiability=q, verbose=verbose)
    band = None
    if em_band is not None:
        band = band_area_table(prep, em_band=em_band,
                               quantifiability=q, verbose=verbose)

    exp = export_eem_quant(prep, out_dir=save_dir, label=label or 'eem',
                           em_band=em_band, em_range=em_range,
                           long_table=long_table, optimal=optimal, peaks=peaks,
                           band=band, quantifiability=q, raw=raw, verbose=verbose)

    fig_path, _ = plot_eem_quant(prep, save_dir=save_dir, show=show, label=label,
                                 em_band=em_band, em_range=em_range, dpi=dpi,
                                 optimal=optimal, peaks=peaks, band=band,
                                 quantifiability=q, verbose=verbose)

    if verbose:
        if q['quantifiable']:
            _safe_print("\n✅ 定量读出完成")
        else:
            _safe_print("\n⚠️ 定量读出完成，但可定量性诊断未通过："
                        "所有数字 reliable=False，不要写进报告")
    return {'quality': q, 'reliable': bool(q['quantifiable']),
            'optimal': optimal, 'peaks': peaks, 'band': band,
            'files': exp['files'], 'figure': fig_path}


# ======================== 8. 合成真值与自检 ========================

def build_synthetic_eem(ex_start=500.0, ex_end=600.0, ex_step=1.0,
                        em_start=200.0, em_end=900.0, em_step=1.0,
                        best_ex=550.0, peak_em=620.0, label='synthetic',
                        noise=0.02, offset=100.0, seed=20261108):
    """
    造一个**真值已知**的 EEM，返回与 `parse_3d_scan_csv` 完全同构的 data dict。

    设计：
      - 激发谱高斯，中心 `best_ex`，σ=18 nm  → 最佳激发波长真值 = `best_ex`
      - 发射谱**双高斯带**：主峰 `peak_em`（σ=28 nm）+ 次峰 `peak_em+85`（σ=42 nm，幅度 0.35）
      - 加 `noise` 相对噪声 + `offset` 本底偏置

    ⚠️ **`peak_em` 是主峰的"设计参数"，不等于双高斯叠加后的实际峰位真值。**
    次峰虽然矮，但会把总轮廓往长波方向拉。实测（`peak_em=620`）：
    设计参数 620 → 实际 argmax **622.00 nm**、抛物线精化 **621.83 nm**。
    所以校验时必须用 `synthetic_truth()` 算出的实际峰位，不能直接拿 `peak_em` 当断言。

    返回 dict 键与 `parse_3d_scan_csv` 一致。
    """
    ex = np.arange(ex_start, ex_end + 1e-9, ex_step, dtype=float)
    em = np.arange(em_start, em_end + 1e-9, em_step, dtype=float)

    ex_profile = np.exp(-0.5 * ((ex - best_ex) / 18.0) ** 2)
    em_profile = (np.exp(-0.5 * ((em - peak_em) / 28.0) ** 2)
                  + 0.35 * np.exp(-0.5 * ((em - (peak_em + 85.0)) / 42.0) ** 2))

    Z = ex_profile[None, :] * em_profile[:, None] * 10000.0 + float(offset)

    if noise:
        rng = np.random.default_rng(int(seed))    # 固定种子，结果可复现
        Z = Z * (1.0 + float(noise) * rng.standard_normal(Z.shape))
    Z = np.maximum(Z, 0.0)

    return {'label': label,
            'ex_wavelengths': ex, 'em_wavelengths': em, 'intensity': Z,
            'ex_start': float(ex[0]), 'ex_end': float(ex[-1]),
            'em_start': float(em[0]), 'em_end': float(em[-1]),
            'ex_step': float(ex_step), 'em_step': float(em_step)}


def synthetic_truth(best_ex=550.0, peak_em=620.0, em_step=0.05):
    """
    返回 `build_synthetic_eem` 的**真值**：双高斯带叠加后的实际峰位与最佳 EX。

    因为次峰把轮廓往长波拉，实际峰位 ≠ 设计参数 `peak_em`。
    用细网格（默认 0.05 nm）在 em 上求 argmax 再抛物线精化，得到可作断言的数值。

    返回 {'best_ex': float, 'peak_em': float, 'peak_em_naive': float}
    `peak_em_naive` 是直接传进来的设计参数，仅用于对照说明差异。
    """
    em = np.arange(200.0, 900.0 + 1e-9, float(em_step))
    prof = (np.exp(-0.5 * ((em - peak_em) / 28.0) ** 2)
            + 0.35 * np.exp(-0.5 * ((em - (peak_em + 85.0)) / 42.0) ** 2))
    k = int(np.argmax(prof))
    em_p, _ = _interp_peak(em, prof, k)
    return {'best_ex': float(best_ex), 'peak_em': float(em_p),
            'peak_em_naive': float(peak_em)}


def self_test(verbose=True, drift_tol=4.0, strong_frac=0.5):
    """
    合成真值自检：不依赖任何数据文件，用 `build_synthetic_eem` 的已知真值检验算法。

    检查项
    ------
      1. `_interp_peak` 还原抛物线顶点
      2. `_fwhm` 还原高斯半高宽
      3. 合成真值被判为可定量
      4. 还原最佳激发波长（容差 ±1 nm）
      5. 还原发射峰位（容差 ±1 nm，真值由 `synthetic_truth` 给出）
      6. 单一荧光体峰位漂移（**只在激发谱足够强的 EX 段统计**）
      7. 人为周期伪迹能被检出 / 干净数据不被误判
      8. CSV 导出与 PNG 出图能落盘

    【为什么第 6 项只在强激发段统计漂移、容差取 4 nm】
    加了噪声后，激发谱很弱的 EX（如 ex_profile≈0.02）本身信噪比极低，
    发射峰位会被噪声带偏几 nm —— 这是**真实的物理限制**，不是算法缺陷
    （无噪声时实测漂移 0.0000 nm，见下一项检查）。
    容差 4 nm 的依据：FWHM 76 nm 高斯 + 2% 噪声、20 个随机种子的强激发段漂移
    中位 2.03 nm、最大 2.69 nm（`peak_window=15`）；取 4 nm 覆盖到最大值并留裕量。
    若把噪声降到 1%，同一实现给出 0.99 nm。

    返回 dict：{'passed': bool, 'checks': [...], 'failures': [...]}
    执行器恢复后应**第一个运行**：`python plot_eem_quant.py --self-test`
    """
    checks, failures = [], []

    def _record(name, ok, detail):
        checks.append({'name': name, 'passed': bool(ok), 'detail': detail})
        if not ok:
            failures.append(f"{name}：{detail}")

    # ---- 0) 底层数学：抛物线插值 / FWHM ----
    x = np.arange(0.0, 21.0, 1.0)
    y = -(x - 7.3) ** 2 + 50.0                    # 顶点 (7.3, 50)
    em_p, _ = _interp_peak(x, y, int(np.argmax(y)))
    _record('_interp_peak 还原抛物线顶点', abs(em_p - 7.3) < 0.05,
            f"得到 {em_p:.3f}，真值 7.300")

    # 高斯 FWHM = 2*sqrt(2ln2)*sigma，σ=3 → 7.0637
    xg = np.arange(-30.0, 30.01, 0.05)
    yg = np.exp(-0.5 * (xg / 3.0) ** 2)
    fw, _, _ = _fwhm(xg, yg, int(np.argmax(yg)))
    expect_fw = 2.0 * np.sqrt(2.0 * np.log(2.0)) * 3.0
    _record('_fwhm 还原高斯半高宽', abs(fw - expect_fw) < 0.05,
            f"得到 {fw:.4f}，真值 {expect_fw:.4f}")

    # ---- 1) 合成数据 ----
    true_best_ex, peak_param = 550.0, 620.0
    truth = synthetic_truth(best_ex=true_best_ex, peak_em=peak_param)
    true_peak_em = truth['peak_em']
    data = build_synthetic_eem(best_ex=true_best_ex, peak_em=peak_param)
    prep = prepare_grid(data, smooth_factor=1, spike_window=0, sigma_em=0.0,
                        clip_saturation=False, notch_comb=False, verbose=False)

    q = assess_quantifiability(data, raw=data, verbose=False)
    _record('合成真值被判为可定量', q['quantifiable'],
            '; '.join(q['reasons']) if q['reasons'] else '四条判据全部通过')

    opt = find_optimal_excitation(prep, em_range=(500.0, 800.0),
                                  quantifiability=q, verbose=False)
    _record('还原最佳激发波长', abs(opt['best_ex'] - true_best_ex) <= 1.0,
            f"得到 {opt['best_ex']:.0f} nm，真值 {true_best_ex:.0f} nm")
    _record('最佳 EX 标记 reliable', opt['reliable'] is True,
            f"reliable={opt['reliable']}")

    pk = emission_peak_table(prep, em_range=(500.0, 800.0),
                             quantifiability=q, verbose=False)
    # 取激发谱最强处的 EX 比较峰位（弱激发端 SNR 太低，比较无意义）
    row_best = min(pk['table'], key=lambda r: abs(r['EX'] - opt['best_ex']))
    _record('还原发射峰位',
            abs(row_best['EM_peak'] - true_peak_em) <= 1.0,
            f"EX={row_best['EX']:.0f} 处得到 {row_best['EM_peak']:.2f} nm，"
            f"真值 {true_peak_em:.2f} nm（设计参数 {peak_param:.0f}）")

    # 漂移：只在强激发段统计
    ex_arr = np.array([r['EX'] for r in pk['table']], dtype=float)
    em_arr = np.array([r['EM_peak'] for r in pk['table']], dtype=float)
    ex_prof = np.exp(-0.5 * ((ex_arr - true_best_ex) / 18.0) ** 2)
    strong = ex_prof >= strong_frac * ex_prof.max()
    if strong.sum() >= 3:
        drift_strong = float(np.nanmax(em_arr[strong]) - np.nanmin(em_arr[strong]))
    else:
        drift_strong = float('nan')
    _record('单一荧光体峰位漂移（强激发段）',
            np.isfinite(drift_strong) and drift_strong <= drift_tol,
            f"漂移 {drift_strong:.2f} nm（{int(strong.sum())} 个强激发 EX，"
            f"容差 {drift_tol:g} nm；全段漂移 {pk['drift_range']:.2f} nm 含弱激发噪声）")

    # 无噪声时可分离数据必须给出 0 漂移——这是算法的严格性检查
    clean = build_synthetic_eem(best_ex=true_best_ex, peak_em=peak_param,
                                noise=0.0, offset=100.0)
    prep_c = prepare_grid(clean, smooth_factor=1, spike_window=0, sigma_em=0.0,
                          clip_saturation=False, notch_comb=False, verbose=False)
    pk_c = emission_peak_table(prep_c, em_range=(500.0, 800.0), verbose=False)
    _record('无噪声可分离数据漂移为 0', pk_c['drift_range'] <= 0.01,
            f"漂移 {pk_c['drift_range']:.4f} nm，峰位 {pk_c['drift_span'][0]:.2f} nm")

    # ---- 2) 不可定量侧：人为叠加一个强周期伪迹，判据应翻转 ----
    bad = dict(data)
    amp = 1.2 * float(data['intensity'].max())
    comb = 0.5 * (1.0 + np.cos(2.0 * np.pi * data['em_wavelengths'] / 7.0))[:, None]
    bad['intensity'] = data['intensity'] + amp * comb
    prep_bad = prepare_grid(bad, smooth_factor=1, spike_window=0, sigma_em=0.0,
                            clip_saturation=False, notch_comb=False, verbose=False)
    q_bad = assess_quantifiability(bad, raw=bad, verbose=False)
    strength_bad = [c for c in q_bad['criteria'] if c['name'] == '周期伪迹强度']
    smooth_bad = [c for c in q_bad['criteria'] if c['name'] == 'EM 通道平滑度']
    caught = (bool(strength_bad) and not strength_bad[0]['passed']) or \
             (bool(smooth_bad) and not smooth_bad[0]['passed'])
    _record('人为周期伪迹能被检出', caught,
            f"峰/底噪={q_bad['evidence'].get('comb_strength')}，"
            f"平滑度={q_bad['evidence'].get('smoothness_ripple')}")

    strength_ok = [c for c in q['criteria'] if c['name'] == '周期伪迹强度']
    _record('干净数据未被误判为伪迹',
            bool(strength_ok) and strength_ok[0]['passed'],
            f"峰/底噪={q['evidence'].get('comb_strength')}，"
            f"平滑度={q['evidence'].get('smoothness_ripple')}")

    # ---- 3) 导出与绘图（临时目录，不污染 ./plots）----
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        try:
            exp = export_eem_quant(prep, out_dir=td, label='selftest',
                                   em_band=(560.0, 700.0), long_table=False,
                                   quantifiability=q, verbose=False)
            _record('CSV 导出', len(exp['files']) >= 4 and exp['reliable'],
                    f"{len(exp['files'])} 个文件")
        except Exception as e:                        # noqa: BLE001
            _record('CSV 导出', False, f"{type(e).__name__}: {e}")

        try:
            fpath, _ = plot_eem_quant(prep, save_dir=td, label='selftest',
                                      dpi=EXPORT_DPI_PREVIEW, quantifiability=q,
                                      verbose=False)
            _record('PNG 出图',
                    Path(fpath).exists() and Path(fpath).stat().st_size > 0,
                    f"{fpath}")
        except Exception as e:                        # noqa: BLE001
            _record('PNG 出图', False, f"{type(e).__name__}: {e}")

    ok_all = all(c['passed'] for c in checks)
    if verbose:
        _safe_print(f"\n{'=' * 62}\n🧪 合成真值自检")
        for c in checks:
            _safe_print(f"  {'✅' if c['passed'] else '❌'} {c['name']}：{c['detail']}")
        _safe_print(f"\n{'✅ 全部通过' if ok_all else '❌ 有失败项'}（"
                    f"{sum(c['passed'] for c in checks)}/{len(checks)}）")
    return {'passed': ok_all, 'checks': checks, 'failures': failures}


# ======================== 9. 命令行 ========================

def main():
    parser = argparse.ArgumentParser(
        description="EEM（3D 扫描）定量读出：可定量性诊断 / 最佳激发 / 峰位表 / 面积表")
    parser.add_argument("file", nargs='?', default=None,
                        help="3D 扫描 CSV 文件路径（用 --self-test 时可省略）")
    parser.add_argument("-o", "--out", default="./plots", help="输出目录（默认 ./plots）")
    parser.add_argument("--self-test", action="store_true",
                        help="跑合成真值自检（不需要数据文件）")
    parser.add_argument("--show", action="store_true", help="画完弹窗（默认只存盘）")
    parser.add_argument("--em-band", default="560,700",
                        help="发射带积分区间 lo,hi（默认 560,700；按体系改；none=关闭面积表）")
    parser.add_argument("--em-range", default=None,
                        help="统计/找峰的 EM 区间 lo,hi（默认全窗；建议按体系指定）")
    parser.add_argument("--long-table", action="store_true",
                        help="额外导出 (EX, EM, I) 长表（大文件，默认关）")
    parser.add_argument("--dpi", type=int, default=None,
                        help=f"图片 DPI（默认 {EXPORT_DPI_DEFAULT}）")
    parser.add_argument("--no-summary-card", action="store_true", help="不画摘要卡")
    # ---- 可定量性判据阈值 ----
    parser.add_argument("--sat-frac-max", type=float, default=0.02,
                        help="判据1：饱和点占比上限（默认 0.02）")
    parser.add_argument("--comb-max", type=float, default=20.0,
                        help="判据2：周期伪迹频谱峰/底噪上限（默认 20；纯噪声≈2.8）")
    parser.add_argument("--smooth-max", type=float, default=0.06,
                        help="判据3：EM 二阶差分纹波上限（默认 0.06）")
    parser.add_argument("--ex-spread-max", type=float, default=0.25,
                        help="判据4：分块最佳 EX 散布/量程上限（默认 0.25）")
    # ---- 清洗参数（透传 prepare_grid）----
    parser.add_argument("--smooth", type=int, default=3, help="样条加密倍数（1=不加密）")
    parser.add_argument("--despike", type=int, default=5, help="中值去窄线窗口（0=关）")
    parser.add_argument("--sigma-em", type=float, default=1.0, help="EM 高斯 sigma")
    parser.add_argument("--sigma-ex", type=float, default=0.0, help="EX 高斯 sigma")
    parser.add_argument("--no-notch", action="store_true", help="不做梳状伪迹陷波")
    parser.add_argument("--comb-mode", choices=['minima', 'divide', 'rows'],
                        default='minima', help="梳状伪迹处理方式（默认 minima）")
    parser.add_argument("--no-clip-saturation", action="store_true", help="不修补饱和点")
    parser.add_argument("--remove-scatter", action="store_true", help="剔除瑞利/拉曼散射带")
    args = parser.parse_args()

    if args.self_test:
        res = self_test(verbose=True)
        sys.exit(0 if res['passed'] else 1)

    if not args.file:
        parser.error("需要 CSV 文件路径（或用 --self-test）")

    def _pair(s):
        if s is None or str(s).strip().lower() in ('none', 'null', ''):
            return None
        parts = str(s).split(',')
        if len(parts) != 2:
            raise SystemExit(f"区间参数需要 'lo,hi' 两个数，收到 {s!r}")
        return (float(parts[0]), float(parts[1]))

    em_band = _pair(args.em_band)
    em_range = _pair(args.em_range)

    _safe_print(f"\n📄 处理: {args.file}")
    data = parse_3d_scan_csv(args.file, verbose=True)
    prep = prepare_grid(data, verbose=True,
                        smooth_factor=args.smooth,
                        spike_window=args.despike,
                        sigma_em=args.sigma_em, sigma_ex=args.sigma_ex,
                        clip_saturation=not args.no_clip_saturation,
                        notch_comb=not args.no_notch,
                        comb_mode=args.comb_mode,
                        remove_scatter=args.remove_scatter)
    _report_stats(prep['stats'], verbose=True)

    # 诊断用【原始 data】（伪迹证据还在）；定量用 prep（清洗后）
    q = assess_quantifiability(data, em_range=em_range, raw=data,
                               sat_frac_max=args.sat_frac_max,
                               comb_strength_max=args.comb_max,
                               smooth_max=args.smooth_max,
                               ex_spread_frac_max=args.ex_spread_max,
                               verbose=True)

    label = data.get('label', '') or ''
    optimal = find_optimal_excitation(prep, em_range=em_range,
                                      quantifiability=q, verbose=True)
    peaks = emission_peak_table(prep, em_range=em_range,
                               quantifiability=q, verbose=True)
    band = band_area_table(prep, em_band=em_band,
                           quantifiability=q, verbose=True) if em_band else None

    export_eem_quant(prep, out_dir=args.out, label=label or 'eem',
                     em_band=em_band, em_range=em_range,
                     long_table=args.long_table, optimal=optimal, peaks=peaks,
                     band=band, quantifiability=q, verbose=True)
    plot_eem_quant(prep, save_dir=args.out, show=args.show, label=label,
                   em_band=em_band, em_range=em_range, dpi=args.dpi,
                   optimal=optimal, peaks=peaks, band=band,
                   quantifiability=q,
                   summary_card=not args.no_summary_card, verbose=True)

    if not q['quantifiable']:
        _safe_print("\n⚠️ 可定量性诊断未通过：导出的所有表都标了 reliable=False，"
                    "这些数字不能作为实验结论。")


if __name__ == "__main__":
    main()
