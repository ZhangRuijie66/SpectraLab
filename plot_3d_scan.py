# -*- coding: utf-8 -*-
"""
3D 扫描光谱 CSV 绘图工具
========================
适用格式：Spectracle / FE30 输出的「3D 扫描 扫描」CSV 文件。
头部含 标签 / EX WL 起点·结束 / EX 读取间隔 / EM WL 起点·结束 / EM 读取间隔，
数据表头为 `EM(nm)\\EX(nm)`：第一列是 EM 波长，其余每列是一个 EX 波长对应的强度。

功能：3D 曲面图 + 等高线图（俯视图）+ Waterfall（堆叠发射谱）图。

【为什么"插值了还是不连续"——v4.16 的数据清洗管线】
原始 3D 扫描数据里混着两类伪迹，直接做三次样条插值只会把它们一起放大：

  1. **饱和点**：强度卡在仪器上限（例如 50000 反复出现，占全矩阵 10% 以上），
     在曲面/等高线上顶出一块平板；
  2. **窄线伪迹**：约 2 nm 宽、强度比邻近高 1~2 个数量级的固定 EM 尖刺
     （杂散光 / 级次光 / 光栅编码器周期性跳变；判据是**它们不随 EX 移动**，
     所以不是样品荧光）。三次样条必须穿过这些点，于是在两侧振铃出负值，
     视觉上就是"断开的尖刺"——插值密度再高也消不掉。

清洗顺序（每步都可用参数关闭，处理量会打印出来）：

    饱和掩膜 → 沿 EM 线性补全 → 中值去窄线 → 高斯平滑 → 三次样条加密显示

颜色范围默认取**稳健分位数**（1%–99.5%）而不是数据极值，否则色标被伪迹独占，
真正的发射带就看不见了。可选对数色标。

【一键用法】
    from plot_3d_scan import plot_3d_all
    plot_3d_all(r"...\\RBLu 1 2026-07-27 07-11.csv", save_dir=r"...\\plots")

【命令行用法】
    python plot_3d_scan.py "文件.csv" -o ./plots --no-show
    python plot_3d_scan.py "文件.csv" -o ./plots --despike 0 --sigma-em 0   # 关掉清洗
    python plot_3d_scan.py "文件.csv" -o ./plots --log --percentile 5,99.9

【GUI 集成】GUI 用 prepare_grid + draw_surface / draw_contour / draw_waterfall
把图直接画到自己的画布上（这三个函数都接受外部 ax，不自己建图）。
"""

import sys
import argparse
from pathlib import Path

import numpy as np
import matplotlib
import matplotlib.pyplot as plt
from scipy.interpolate import (RectBivariateSpline, make_interp_spline,
                               PchipInterpolator)
from scipy.ndimage import gaussian_filter, gaussian_filter1d, median_filter


# ======================== 0. 打印与字体 ========================

def _safe_print(*args, **kwargs):
    """GBK 终端安全打印（emoji / 生僻字不会让程序崩）。"""
    try:
        print(*args, **kwargs)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, 'encoding', None) or 'utf-8'
        msg = " ".join(str(a) for a in args)
        try:
            print(msg.encode(enc, errors='replace').decode(enc, errors='replace'),
                  **kwargs)
        except Exception:
            pass


def setup_chinese_font():
    candidates = [
        'Microsoft YaHei', 'SimHei', 'KaiTi', 'FangSong', 'SimSun',
        'Noto Sans CJK SC', 'WenQuanYi Micro Hei', 'Arial Unicode MS',
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
        _safe_print(f"  🔤 使用中文字体: {chosen}")
    else:
        plt.rcParams['font.sans-serif'] = ['DejaVu Sans']
        _safe_print("  ⚠️  未找到中文字体，将使用英文标签")


setup_chinese_font()


# ======================== 1. 解析 3D 扫描 CSV ========================

def parse_3d_scan_csv(filepath, verbose=True):
    """
    解析 Spectracle / FE30 输出的 3D 扫描 CSV。

    返回 dict: label / ex_wavelengths / em_wavelengths / intensity / ex_start ...
    intensity 形状为 (n_EM, n_EX)。

    解析要点（v4.16 修）：空单元格必须**按位置**保留为 NaN，
    旧实现遇到空值直接 continue，会让后面所有列左移一格——
    这正是曲面出现错位锯齿的元凶之一。
    """
    encodings = ['utf-8-sig', 'utf-8', 'gbk', 'latin-1']
    lines = None
    for enc in encodings:
        try:
            with open(filepath, 'r', encoding=enc) as f:
                lines = f.readlines()
            break
        except (UnicodeDecodeError, FileNotFoundError):
            continue
    if lines is None:
        raise ValueError(f"无法读取文件: {filepath}")

    # --- 元数据 ---
    sample_label = ''
    meta = {'ex_start': None, 'ex_end': None, 'em_start': None, 'em_end': None,
            'ex_step': None, 'em_step': None}
    _keys = {
        'EX WL 起点': 'ex_start', 'EX WL 结束': 'ex_end',
        'EM WL 起点': 'em_start', 'EM WL 结束': 'em_end',
        'EX 读取间隔': 'ex_step', 'EM 读取间隔': 'em_step',
    }
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        parts = [p.strip() for p in stripped.split(',')]
        if not parts:
            continue
        head = parts[0]
        if '标签' in head and len(parts) > 1:
            sample_label = parts[1].strip('"').strip("'")
            continue
        for key, name in _keys.items():
            if key in head and len(parts) > 1:
                try:
                    meta[name] = float(parts[1])
                except (ValueError, IndexError):
                    pass
                break

    # --- 数据表头行 ---
    data_header_row = None
    for i, line in enumerate(lines):
        parts = [p.strip() for p in line.strip().split(',')]
        if parts and 'EM(nm)' in parts[0] and 'EX(nm)' in parts[0]:
            data_header_row = i
            break
    if data_header_row is None:
        raise ValueError("未找到数据表头行 'EM(nm)\\EX(nm)'，文件格式可能不匹配")

    header_parts = [p.strip() for p in lines[data_header_row].strip().split(',')]
    ex_wavelengths = []
    for p in header_parts[1:]:
        try:
            ex_wavelengths.append(float(p))
        except ValueError:
            continue  # 表头尾部的空列
    n_ex = len(ex_wavelengths)
    if n_ex == 0:
        raise ValueError("表头中未解析到任何 EX 波长")

    # --- EM 波长与强度矩阵（按位置对齐，空值→NaN）---
    em_wavelengths = []
    rows = []
    for line in lines[data_header_row + 1:]:
        stripped = line.strip().rstrip(',')
        if not stripped:
            continue
        parts = [p.strip() for p in stripped.split(',')]
        if len(parts) < 2:
            continue
        try:
            em_wl = float(parts[0])
        except ValueError:
            continue
        row = []
        for x in parts[1:n_ex + 1]:
            try:
                row.append(float(x))
            except ValueError:
                row.append(np.nan)      # 空/异常单元格保持原位
        if len(row) < n_ex:
            row.extend([np.nan] * (n_ex - len(row)))
        em_wavelengths.append(em_wl)
        rows.append(row)

    if not rows:
        raise ValueError("数据区为空，未解析到任何强度行")

    em_wavelengths = np.asarray(em_wavelengths, dtype=float)
    ex_wavelengths = np.asarray(ex_wavelengths, dtype=float)
    intensity = np.asarray(rows, dtype=float)

    # EM 轴必须严格递增，否则插值器直接报错
    order = np.argsort(em_wavelengths, kind='stable')
    if not np.array_equal(order, np.arange(em_wavelengths.size)):
        em_wavelengths = em_wavelengths[order]
        intensity = intensity[order, :]

    if verbose:
        _safe_print(f"  📋 样本标签: {sample_label}")
        _safe_print(f"  📐 EX 范围: {ex_wavelengths[0]:.0f} – {ex_wavelengths[-1]:.0f} nm "
                    f"({len(ex_wavelengths)} 个)")
        _safe_print(f"  📐 EM 范围: {em_wavelengths[0]:.0f} – {em_wavelengths[-1]:.0f} nm "
                    f"({len(em_wavelengths)} 个)")
        _safe_print(f"  📊 数据矩阵: {intensity.shape}"
                    f"（空值 {int(np.isnan(intensity).sum())} 个）")

    result = {'label': sample_label,
              'ex_wavelengths': ex_wavelengths,
              'em_wavelengths': em_wavelengths,
              'intensity': intensity}
    result.update(meta)
    return result


# ======================== 2. 数据清洗管线 ========================

def _fill_nan_along_em(Z):
    """补 NaN：先沿 EM（列方向）线性插值，整列无数据时再沿 EX（行方向）插值。

    旧实现把"整列全 NaN"直接置 0——那会在 EEM 里造出一条**人造暗带**，
    随后的中值/高斯/样条平滑会把它变成看起来真实的结构，按 EX 归一化或
    做比值图时就会得到假极小。现在改为：能插就插，实在插不了就保留 NaN
    （由绘图/统计环节跳过），并把处理情况记入返回的统计。
    """
    out = Z.copy()
    idx = np.arange(out.shape[0])
    n_col_em = 0
    n_col_ex = 0
    for j in range(out.shape[1]):
        col = out[:, j]
        good = np.isfinite(col)
        if good.all():
            continue
        if good.any():
            col[~good] = np.interp(idx[~good], idx[good], col[good])
            out[:, j] = col
            n_col_em += 1
            continue
        # 整列无数据：用同一 EM 行上其它 EX 通道的值沿 EX 插值补这一列
        row_idx = np.arange(out.shape[1])
        for i in range(out.shape[0]):
            row = out[i, :]
            g = np.isfinite(row)
            if not g.any():
                continue
            out[i, j] = np.interp(j, row_idx[g], row[g])
        n_col_ex += 1
    stats = {'cols_filled_em': int(n_col_em), 'cols_filled_ex': int(n_col_ex),
             'nan_left': int(np.isnan(out).sum())}
    return out, stats


def _detect_saturation(Z, rel_tol=1e-6, min_count=10, min_fraction=0.001):
    """检测"反复出现的最大值"=仪器饱和上限；返回该值或 None。"""
    finite = Z[np.isfinite(Z)]
    if finite.size == 0:
        return None
    mx = float(np.nanmax(finite))
    if not np.isfinite(mx) or mx <= 0:
        return None
    n = int(np.sum(finite >= mx * (1.0 - rel_tol)))
    if n >= max(min_count, int(min_fraction * finite.size)):
        return mx
    return None


def _comb_profile(Z, em, pmax=30.0):
    """
    返回"归一化梳状剖面" r = 谱包络中位数 / 平滑包络。

    梳状伪迹的幅度会被荧光包络调制（亮的地方条纹也亮），
    必须先归一化，否则阈值只能抓到最亮的几处。
    """
    n = Z.shape[0]
    d = float(np.median(np.diff(em))) if n > 1 else 1.0
    if not np.isfinite(d) or d <= 0:
        d = 1.0
    prof = np.median(Z, axis=1)
    win = max(3, int(round(4.0 * pmax / d)) | 1)
    win = min(win, n | 1)
    env = median_filter(prof, size=win, mode='nearest')
    env = np.maximum(env, 1e-9)
    r = prof / env
    return r - np.median(r), d


def _detect_comb_period(Z, em, pmin=3.0, pmax=30.0):
    """
    检测沿 EM 的**周期性梳状伪迹**（等厚干涉条纹 / 光栅鬼线）的周期。

    做法：各 EM 行的中位数当谱剖面 → 除以平滑包络归一化 → FFT，
    在周期 pmin–pmax nm 的频段里找最强峰。返回 (周期 nm, 峰/底噪比)。
    """
    n = Z.shape[0]
    if n < 16:
        return None, 0.0
    resid, d = _comb_profile(Z, em, pmax)
    F = np.abs(np.fft.rfft(resid))
    span = n * d
    kmin = max(2, int(np.floor(span / pmax)))
    kmax = min(len(F) - 1, int(np.ceil(span / pmin)))
    if kmax <= kmin:
        return None, 0.0
    seg = F[kmin:kmax + 1]
    ki = int(np.argmax(seg)) + kmin
    if ki <= 0:
        return None, 0.0
    period = span / ki
    noise = float(np.median(F[1:])) if len(F) > 1 else 0.0
    strength = float(seg.max() / (noise + 1e-9))
    return float(period), strength


def _keep_comb_minima(Z, em, period, width=2):
    """
    只保留**条纹谷值**所在的 EM 通道（每个周期一个），其余通道沿 EM 插值重建。

    实测这类数据的条纹占 5/7 的通道且峰值饱和，峰谷比可达 30 倍，
    想靠除法还原会因饱和而失真。谷值通道是唯一没被条纹抬高、也没饱和的样本，
    以它做 7 nm 等效采样再插值，得到的曲面必然连续且不引入虚假结构。
    代价：EM 有效采样从 1 nm 降到约 1 个周期（默认 ~7 nm）——
    对 30–50 nm 宽的荧光带完全够用，但会抹掉真正窄于一个周期的发射线。

    返回 (重建后的 Z, 谷值通道索引数组)。
    """
    n = Z.shape[0]
    if n < 16 or not period or period <= 0:
        return Z, None
    d = float(np.median(np.diff(em))) if n > 1 else 1.0
    if not np.isfinite(d) or d <= 0:
        d = 1.0
    span = n * d
    k0 = span / period
    if k0 < 2:
        return Z, None

    prof = np.median(Z, axis=1)
    env = gaussian_filter1d(prof, sigma=max(3.0, 1.5 * period / d), mode='nearest')
    r = prof / np.maximum(env, 1e-9) - 1.0
    F = np.fft.rfft(r)
    keep = np.zeros_like(F)
    for dk in range(-int(width), int(width) + 1):
        ki = int(round(k0)) + dk
        if 0 < ki < len(F):
            keep[ki] = F[ki]
    f = np.fft.irfft(keep, n=n)              # 条纹分量，谷值 = 局部最小

    step = max(2.0, span / max(k0, 1.0))
    idx = []
    pos = 0.0
    while pos < n:
        end = min(n, int(round(pos + step)))
        if end <= int(round(pos)):
            break
        seg = f[int(round(pos)):end]
        if seg.size:
            idx.append(int(round(pos)) + int(np.argmin(seg)))
        pos += step
    idx = sorted(set(idx))
    if len(idx) < 4:
        return Z, None

    ar = np.arange(n)
    out = Z.copy()
    # 用 PCHIP（保形插值）代替 np.interp 的线性插值：谷值通道之间的重建更平滑，
    # 且保形不会像三次样条那样在峰两侧过冲出负值
    pchip = PchipInterpolator(idx, Z[idx, :], axis=0, extrapolate=True)
    out = pchip(ar)
    # 首尾谷值之外的区域用最近的谷值通道常数填充（外推不可信）
    if idx[0] > 0:
        out[:idx[0], :] = Z[idx[0], :]
    if idx[-1] < n - 1:
        out[idx[-1] + 1:, :] = Z[idx[-1], :]
    return np.maximum(out, 0.0), np.asarray(idx)


def _correct_comb(Z, em, period, width=2, gain_range=(0.02, 50.0)):
    """
    把周期梳状伪迹当作**乘性干涉条纹**除掉： Z_meas = I_true × gain(λ)。

    gain 由"行中位数剖面"的**带通**估计——只保留周期 period 附近 ±width 个频点，
    所以只扣周期性成分，宽带发射谱形状完整保留。
    这条比"整行插值替换"更合适：实测条纹占 5/7 的通道，替换掉会丢掉大半数据。

    返回 (修正后的 Z, gain 曲线, 条纹幅度估计)。
    """
    n = Z.shape[0]
    if n < 16 or not period or period <= 0:
        return Z, np.ones(n), 0.0
    d = float(np.median(np.diff(em))) if n > 1 else 1.0
    if not np.isfinite(d) or d <= 0:
        d = 1.0
    span = n * d
    k0 = span / period
    if k0 < 2:
        return Z, np.ones(n), 0.0

    prof = np.median(Z, axis=1)
    env = gaussian_filter1d(prof, sigma=max(3.0, 1.5 * period / d), mode='nearest')
    env = np.maximum(env, 1e-9)
    r = prof / env - 1.0                       # 归一化条纹（相对包络的起伏）

    F = np.fft.rfft(r)
    keep = np.zeros_like(F)
    for dk in range(-int(width), int(width) + 1):
        ki = int(round(k0)) + dk
        if 0 < ki < len(F):
            keep[ki] = F[ki]
    f = np.fft.irfft(keep, n=n)                # 条纹分量

    gain = np.clip(1.0 + f, gain_range[0], gain_range[1])
    out = Z / gain[:, None]
    return out, gain, float(np.max(np.abs(f)))


def _remove_comb_rows(Z, em, period=None, harmonics=3, threshold=1.5):
    """
    把被周期梳状伪迹污染的 **EM 通道行**，沿 EM 用邻近干净行线性插值替换。

    判据（比频域相位法稳健，梳状相位会漂移）：
    沿 EM 取大窗口中值当局部本底 env，则 ratio = Z/env。
    若某一 EM 行在**大多数 EX 列**上都 ratio > threshold，
    说明整行被抬高——这就是伪迹行。

    返回 (处理后的 Z, 被替换行的布尔掩膜)。
    """
    n = Z.shape[0]
    if n < 16:
        return Z, np.zeros(n, dtype=bool)
    d = float(np.median(np.diff(em))) if n > 1 else 1.0
    if not np.isfinite(d) or d <= 0:
        d = 1.0
    win = max(5, int(round(4.0 * (period or 7.0) / d)) | 1)
    win = min(win, n | 1)

    env = median_filter(Z, size=(win, 1), mode='nearest')
    ratio = Z / np.maximum(env, 1e-9)
    score = np.median(ratio, axis=1)          # 该 EM 行整体被抬高多少
    bad = score > float(threshold)

    # 谐波判据（harmonics ≥ 2 时才额外启用）：把周期成分的 1..H 次谐波重建出来，
    # 谐波幅度处于前一半的通道也算伪迹行。旧实现里 harmonics 参数完全没被使用，
    # 用户调它不会有任何反应。
    if int(harmonics) > 1 and period and period > 0:
        span = n * d
        k0 = span / float(period)
        prof = np.median(Z, axis=1)
        env_p = np.maximum(median_filter(prof, size=win, mode='nearest'), 1e-9)
        r = prof / env_p - 1.0
        F = np.fft.rfft(r)
        keep = np.zeros_like(F)
        for h in range(1, int(harmonics) + 1):
            ki = int(round(k0 * h))
            if 0 < ki < len(F):
                keep[ki] = F[ki]
        f = np.fft.irfft(keep, n=n)
        # f 是"相对包络的抬高量"，绝对阈值 0.5 = 被抬高 50% 以上才算伪迹行
        # （不能用相对 max 的比例：那会标记掉约一半通道，触发下面的保护性返回）
        bad = bad | (f > 0.5)
    if bad.sum() == 0 or bad.all() or bad.mean() > 0.6:
        return Z, np.zeros(n, dtype=bool)

    good_idx = np.where(~bad)[0]
    if len(good_idx) < 4:
        return Z, np.zeros(n, dtype=bool)
    idx = np.arange(n)
    out = Z.copy()
    for j in range(Z.shape[1]):
        out[bad, j] = np.interp(idx[bad], good_idx, Z[good_idx, j])
    return out, bad


def _safe_log(*args, verbose=True):
    """仅在 verbose 为真时打印（GUI 里底层告警不该污染控制台）。"""
    if verbose:
        _safe_print(*args)


def _sanitize_axes(ex, em, Z):
    """把 EX/EM 轴整理成"严格递增且无重复"，重复波长取均值合并。

    插值器（RectBivariateSpline）要求坐标严格递增，而实测数据里 EX 递减、
    重复波长的文件都存在；旧实现只对 EM 排序，EX 递减时加密会静默失败。
    返回 (ex, em, Z, info)。
    """
    info = {'axis_uniform': True, 'ex_dedup': 0, 'em_dedup': 0}
    # EX：排序 + 合并重复列
    order = np.argsort(ex, kind='stable')
    ex, Z = ex[order], Z[:, order]
    if len(ex) > 1:
        keep = np.ones(len(ex), dtype=bool)
        keep[1:] = np.diff(ex) > 0
        if not keep.all():
            uniq, inv = np.unique(ex, return_inverse=True)
            Zc = np.zeros((Z.shape[0], len(uniq)))
            for j, u in enumerate(uniq):
                Zc[:, j] = Z[:, inv == j].mean(axis=1)
            info['ex_dedup'] = int(len(ex) - len(uniq))
            ex, Z = uniq, Zc
    # EM：排序 + 合并重复行
    order = np.argsort(em, kind='stable')
    em, Z = em[order], Z[order, :]
    if len(em) > 1:
        keep = np.ones(len(em), dtype=bool)
        keep[1:] = np.diff(em) > 0
        if not keep.all():
            uniq, inv = np.unique(em, return_inverse=True)
            Zr = np.zeros((len(uniq), Z.shape[1]))
            for i, u in enumerate(uniq):
                Zr[i, :] = Z[inv == i, :].mean(axis=0)
            info['em_dedup'] = int(len(em) - len(uniq))
            em, Z = uniq, Zr
    # 等间距检查（非等间距时加密网格会与数据错位，只提示不改数据）
    for arr, key in ((ex, 'ex'), (em, 'em')):
        if len(arr) > 2:
            d = np.diff(arr)
            if not np.allclose(d, np.median(d), rtol=1e-3, atol=1e-9):
                info['axis_uniform'] = False
                info[f'{key}_uniform'] = False
    return ex, em, Z, info


def _scatter_mask(em, ex, rayleigh_width=10.0, raman_shift_cm=3350.0,
                  raman_width=15.0):
    """构造瑞利/拉曼散射带掩膜（True = 判为散射，需要剔除）。

    - **瑞利**：EM ≈ EX（|EM − EX| ≤ rayleigh_width nm），包括一级与（近似的）二级；
    - **拉曼**：水的 O–H 伸缩振动位移 ≈ 3350 cm⁻¹，
      EM = 1 / (1/EX − Δν·1e-7)（nm），± raman_width nm 内判为拉曼带。

    返回 (mask, n_rayleigh, n_raman)，mask 形状 (len(em), len(ex))。
    """
    em = np.asarray(em, dtype=float)
    ex = np.asarray(ex, dtype=float)
    EMg, EXg = np.meshgrid(em, ex, indexing='ij')
    ray = np.abs(EMg - EXg) <= float(rayleigh_width)
    with np.errstate(divide='ignore', invalid='ignore'):
        ram = 1.0 / (1.0 / EXg - float(raman_shift_cm) * 1e-7)
    ram = np.where(np.isfinite(ram) & (ram > 0), ram, np.inf)
    raman = np.abs(EMg - ram) <= float(raman_width)
    return (ray | raman), int(ray.sum()), int(raman.sum())


def inner_filter_correction(data, a_ex, a_em):
    """内滤效应校正：F_corr = F_obs · 10^((A_ex + A_em)/2)。

    内滤效应会让 EEM 在强吸收区被压低（激发光被吸收、发射光再被吸收），
    定量比较峰高/峰位前应当校正。

    Args:
        data: parse_3d_scan_csv 的返回（含 intensity）
        a_ex: 各 EX 波长处的吸光度（长度 = len(ex)）
        a_em: 各 EM 波长处的吸光度（长度 = len(em)）

    Returns:
        (校正后的 intensity 数组, 校正因子矩阵)
    """
    Z = np.asarray(data['intensity'], dtype=float)
    a_ex = np.asarray(a_ex, dtype=float).ravel()
    a_em = np.asarray(a_em, dtype=float).ravel()
    if a_ex.size != Z.shape[1] or a_em.size != Z.shape[0]:
        raise ValueError(
            f"吸光度长度与 EEM 不匹配：a_ex={a_ex.size}（应为 {Z.shape[1]}），"
            f"a_em={a_em.size}（应为 {Z.shape[0]}）")
    if not (np.isfinite(a_ex).all() and np.isfinite(a_em).all()):
        raise ValueError("吸光度含 NaN/Inf，请先清洗")
    factor = 10.0 ** ((a_em[:, None] + a_ex[None, :]) / 2.0)
    return Z * factor, factor


def prepare_grid(data, smooth_factor=3, spike_window=5, sigma_em=1.0, sigma_ex=0.0,
                 clip_saturation=True, log_scale=False, notch_comb=True,
                 notch_period=None, notch_harmonics=4, notch_strength=5.0,
                 comb_mode='minima', verbose=True, remove_scatter=False,
                 rayleigh_width=10.0, raman_shift_cm=3350.0, raman_width=15.0,
                 blank=None):
    """
    清洗 + 加密，返回画图所需的一切。

    参数
    ----
    smooth_factor : 加密倍数（1 = 不加密，直接返回清洗后的原始网格）
    spike_window  : 沿 EM 的中值滤波窗口（去窄线伪迹）；<=1 关闭
    sigma_em      : 沿 EM 的高斯平滑 sigma（单位=原始网格步长）
    sigma_ex      : 沿 EX 的高斯平滑 sigma
    clip_saturation : 自动识别并修补饱和点
    log_scale     : 是否返回 log10 强度（画图时用）
    remove_scatter : 剔除瑞利/拉曼散射带（EM≈EX 与 EM=1/(1/EX−Δν·1e-7)）。
                    **默认关闭**——它会沿对角线插值补洞、在锐利边缘附近让样条
                    轻微振铃，适合"想看真实荧光结构"时显式开启（CLI: --remove-scatter）
    rayleigh_width : 瑞利带半宽（nm，默认 ±10）
    raman_shift_cm / raman_width : 拉曼位移（cm⁻¹，默认 3350）与半宽（nm）
    blank         : 空白（溶剂）数据集 dict（同 parse_3d_scan_csv 的格式），
                    给出时先做 Z − Z_blank 的空白扣除（要求 EX/EM 网格一致）

    返回 dict：
      ex / em        加密后的坐标（1D）
      EX / EM        meshgrid
      Z              加密后的强度（可能已取 log10）
      ex_orig/em_orig/Z_orig  清洗后、未加密的原始网格（waterfall 用）
      stats          清洗统计（饱和值、修补点数、散射剔除数、去窄线前后差异、色标建议）
    """
    ex = np.asarray(data['ex_wavelengths'], dtype=float)
    em = np.asarray(data['em_wavelengths'], dtype=float)
    Z = np.asarray(data['intensity'], dtype=float).copy()

    stats = {'nan_in': int(np.isnan(Z).sum()), 'saturation': None,
             'saturation_points': 0, 'saturation_neighbor_frac': None,
             'despike_window': int(spike_window),
             'despike_delta': 0.0, 'sigma_em': float(sigma_em),
             'sigma_ex': float(sigma_ex), 'log_scale': bool(log_scale),
             'comb_period': None, 'comb_strength': 0.0, 'comb_notched': False,
             'spline_ok': False, 'neg_after_spline': 0, 'axis_uniform': True,
             'cols_filled_em': 0, 'cols_filled_ex': 0, 'nan_left': 0,
             'scatter_removed': 0, 'scatter_rayleigh': 0, 'scatter_raman': 0,
             'blank_subtracted': False}

    # 坐标轴校验：EX/EM 都要求严格递增（插值器要求），重复值取均值合并
    ex, em, Z, axis_info = _sanitize_axes(ex, em, Z)
    stats.update(axis_info)

    # ⓪ 空白（溶剂）扣除：Z − Z_blank
    if blank is not None:
        b_ex = np.asarray(blank['ex_wavelengths'], dtype=float)
        b_em = np.asarray(blank['em_wavelengths'], dtype=float)
        b_Z = np.asarray(blank['intensity'], dtype=float)
        if b_Z.shape != Z.shape or len(b_ex) != len(ex) or len(b_em) != len(em):
            raise ValueError(
                f"空白数据网格与样品不一致：样品 {Z.shape}，空白 {b_Z.shape}；"
                "请先用相同 EX/EM 设置测量空白")
        if not (np.allclose(b_ex, ex) and np.allclose(b_em, em)):
            raise ValueError("空白数据的 EX/EM 波长与样品不一致，无法直接相减")
        Z = Z - b_Z
        stats['blank_subtracted'] = True

    # ① 空值 → NaN → 沿 EM 补全（整列缺失时改沿 EX，实在不行保留 NaN）
    if stats['nan_in']:
        Z, fill_stats = _fill_nan_along_em(Z)
        stats.update(fill_stats)

    # ①' 瑞利/拉曼散射带：掩掉后沿 EM 插值补全（内插，不外推）
    if remove_scatter:
        mask, n_ray, n_ram = _scatter_mask(em, ex, rayleigh_width,
                                           raman_shift_cm, raman_width)
        stats['scatter_rayleigh'] = int(n_ray)
        stats['scatter_raman'] = int(n_ram)
        # 安全阀：掩膜覆盖超过一半数据说明宽度设错了（例如把 raman_width
        # 当成 nm 却按几百 nm 给），此时宁可不动也不要毁掉数据
        if mask.any() and mask.mean() > 0.5:
            stats['scatter_skipped'] = True
            _safe_log(f"  ⚠️  散射掩膜覆盖 {mask.mean():.0%} 的数据，"
                      "已跳过（请检查 rayleigh_width / raman_width）",
                      verbose=verbose)
        elif mask.any():
            Z = Z.copy()
            Z[mask] = np.nan
            Z, fill_stats = _fill_nan_along_em(Z)
            stats['scatter_removed'] = int(n_ray + n_ram)
            stats['nan_left'] = int(np.isnan(Z).sum())

    # ② 饱和点掩膜 + 补全
    if clip_saturation:
        sat = _detect_saturation(Z)
        if sat is not None:
            mask = Z >= sat * (1 - 1e-6)
            # 记录极值的"空间形态"，供人工判断是仪器饱和还是真实峰顶：
            #   neighbor_frac = 候选点在 EM 方向上有同值邻居的比例（饱和平台高）
            #   ex_coverage   = 含候选点的 EX 通道比例（仪器饱和会跨很多 EX）
            nb = np.zeros_like(mask)
            nb[1:, :] |= mask[:-1, :] & mask[1:, :]
            nb[:-1, :] |= mask[:-1, :] & mask[1:, :]
            frac = float(nb.sum() / max(mask.sum(), 1))
            ex_cov = float(np.mean(np.any(mask, axis=0))) if mask.size else 0.0
            stats['saturation'] = sat
            stats['saturation_points'] = int(mask.sum())
            stats['saturation_neighbor_frac'] = frac
            stats['saturation_ex_coverage'] = ex_cov
            stats['saturation_clipped'] = True
            if frac < 0.15 and ex_cov < 0.15:
                _safe_log(f"  ⚠️  极值 {sat:.0f} 的空间连续性很低"
                          f"（EM 邻居 {frac:.0%}、EX 覆盖 {ex_cov:.0%}），"
                          "可能是真实峰顶而非饱和；仍按饱和修补，"
                          "若峰顶被削平请关闭饱和修补", verbose=verbose)
            Z[mask] = np.nan
            Z, fill_stats = _fill_nan_along_em(Z)
            stats.update({k: stats[k] + v for k, v in fill_stats.items()})
        else:
            stats['saturation_clipped'] = False

    # ③ 周期梳状伪迹：定位被污染的 EM 通道并用邻近干净通道插值替换
    if notch_comb:
        period = notch_period
        strength = 1e9
        if period is None:
            period, strength = _detect_comb_period(Z, em)
        stats['comb_period'] = period
        stats['comb_strength'] = float(strength)
        if period and strength >= notch_strength:
            if comb_mode == 'rows':
                Z, bad = _remove_comb_rows(Z, em, period,
                                           harmonics=notch_harmonics)
                stats['comb_notched'] = bool(bad.any())
                stats['comb_rows'] = int(bad.sum())
            elif comb_mode == 'divide':
                Z, gain, amp = _correct_comb(Z, em, period)
                stats['comb_notched'] = True
                stats['comb_amp'] = amp
                stats['comb_gain_min'] = float(np.min(gain))
                stats['comb_gain_max'] = float(np.max(gain))
            else:                              # 'minima'（默认）：只保留谷值通道
                Z, idx = _keep_comb_minima(Z, em, period)
                stats['comb_notched'] = idx is not None
                if idx is not None:
                    stats['comb_kept'] = int(len(idx))
                    stats['comb_kept_step'] = float(np.median(np.diff(idx)))
                    stats['comb_replaced_frac'] = float(
                        1.0 - len(idx) / max(len(em), 1))
            # 校正后的**残余条纹强度**：用同一 FFT 判据复测，与校正前的
            # 峰/底噪比相比。>30% 说明该模式没压住周期性条纹，需要换模式。
            # （不要用剖面残差的 max 当指标：真实窄发射线也会让它很大）
            if stats['comb_notched']:
                _, strength_after = _detect_comb_period(Z, em)
                stats['comb_strength_after'] = float(strength_after)
                stats['comb_residual'] = float(
                    strength_after / max(float(strength), 1e-9))

    # ④ 中值去残余窄线（沿 EM）
    if spike_window and spike_window >= 3:
        Zf = median_filter(Z, size=(int(spike_window), 1), mode='nearest')
        stats['despike_delta'] = float(np.nanmax(np.abs(Zf - Z)))
        Z = Zf

    # ⑤ 高斯平滑
    if sigma_em or sigma_ex:
        Z = gaussian_filter(Z, sigma=(float(sigma_em), float(sigma_ex)),
                            mode='nearest')

    Z_orig = Z.copy()          # 必须 copy：旧实现是别名，后续原地改动会连带改掉它
    ex_orig = ex.copy()
    em_orig = em.copy()

    # ⑤ 稳健色标（在平滑后的数据上算，避免被残留尖峰独占）
    finite = Z[np.isfinite(Z)]
    if finite.size:
        stats['p1'] = float(np.percentile(finite, 1))
        stats['p995'] = float(np.percentile(finite, 99.5))
        stats['vmin_data'] = float(finite.min())
        stats['vmax_data'] = float(finite.max())

    # ⑥ 三次样条加密（数据已平滑，不会再振铃）
    if smooth_factor and smooth_factor > 1 and len(ex) >= 4 and len(em) >= 4:
        try:
            spline = RectBivariateSpline(em, ex, Z, kx=3, ky=3, s=0)
            ex_d = np.linspace(ex[0], ex[-1], len(ex) * int(smooth_factor))
            em_d = np.linspace(em[0], em[-1], len(em) * int(smooth_factor))
            EX, EM = np.meshgrid(ex_d, em_d)
            Z_d = spline(em_d, ex_d, grid=True)
            stats['spline_ok'] = True
            # 插值样条仍可能在尖峰两侧振铃出负值：负强度没有物理意义，
            # 会污染峰高比/比值图，这里显式截断并记录
            neg = int(np.sum(Z_d < 0))
            if neg:
                stats['neg_after_spline'] = neg
                Z_d = np.maximum(Z_d, 0.0)
        except Exception as e:                       # 退化：直接网格
            _safe_log(f"  ⚠️  样条加密失败（{type(e).__name__}），改用原始网格",
                      verbose=verbose)
            EX, EM = np.meshgrid(ex, em)
            ex_d, em_d, Z_d = ex, em, Z
    else:
        EX, EM = np.meshgrid(ex, em)
        ex_d, em_d, Z_d = ex, em, Z

    if log_scale:
        floor = max(float(np.percentile(finite, 1)) if finite.size else 1.0, 1e-9)
        floor = max(floor, float(np.nanmax(Z_d)) * 1e-5)
        Z_d = np.log10(np.maximum(Z_d, floor))
        stats['log_floor'] = float(floor)

    return {'ex': ex_d, 'em': em_d, 'EX': EX, 'EM': EM, 'Z': Z_d,
            'ex_orig': ex_orig, 'em_orig': em_orig, 'Z_orig': Z_orig,
            'stats': stats}


def _robust_limits(prep, percentile=(1.0, 99.5), zlim=None):
    """稳健色标范围：默认 1%–99.5% 分位，避免被伪迹/饱和点独占。"""
    if zlim:
        return float(zlim[0]), float(zlim[1])
    Z = prep['Z']
    finite = Z[np.isfinite(Z)]
    if finite.size == 0:
        return None, None
    lo, hi = np.percentile(finite, percentile)
    if lo == hi:
        hi = lo + 1.0
    return float(lo), float(hi)


# ======================== 3. 绘图（可画到外部 ax，供 GUI 复用）========================

def draw_surface(ax, prep, cmap='viridis', alpha=0.95, elev=25, azim=-60,
                 zlim=None, percentile=(1.0, 99.5), label='', log_scale=False):
    """在给定 3D ax 上画曲面，返回 (mappable, vmin, vmax)。"""
    vmin, vmax = _robust_limits(prep, percentile, zlim)
    Z = prep['Z']
    if vmin is not None:
        Z = np.clip(Z, vmin, vmax)

    # 大网格按步长抽稀渲染，否则几十万四边形会糊成噪点
    n = Z.size
    stride = 1 if n <= 40000 else max(1, int(np.sqrt(n / 40000)))
    surf = ax.plot_surface(prep['EX'], prep['EM'], Z, cmap=cmap, alpha=alpha,
                           linewidth=0, antialiased=True,
                           vmin=vmin, vmax=vmax,
                           rstride=stride, cstride=stride)
    ax.set_xlabel('EX 波长 (nm)', fontsize=11, labelpad=8)
    ax.set_ylabel('EM 波长 (nm)', fontsize=11, labelpad=8)
    ax.set_zlabel('log10 强度' if log_scale else '强度 (AU)',
                  fontsize=11, labelpad=8)
    ax.set_title(f'{label} — 3D 扫描曲面' if label else '3D 扫描曲面', fontsize=13)
    ax.view_init(elev=elev, azim=azim)
    ax.invert_yaxis()
    return surf, vmin, vmax


def draw_contour(ax, prep, cmap='viridis', n_levels=30, fill=True,
                 zlim=None, percentile=(1.0, 99.5), label=''):
    """在给定 2D ax 上画等高线/填色图，返回 (mappable, vmin, vmax)。"""
    vmin, vmax = _robust_limits(prep, percentile, zlim)
    Z = prep['Z']
    if vmin is not None:
        Z = np.clip(Z, vmin, vmax)
    levels = np.linspace(vmin, vmax, int(n_levels)) if vmin is not None else n_levels
    if fill:
        cf = ax.contourf(prep['EX'], prep['EM'], Z, levels=levels, cmap=cmap,
                         vmin=vmin, vmax=vmax)
    else:
        cf = ax.contour(prep['EX'], prep['EM'], Z, levels=levels, cmap=cmap,
                        linewidths=0.8, vmin=vmin, vmax=vmax)
    ax.set_xlabel('EX 波长 (nm)', fontsize=12)
    ax.set_ylabel('EM 波长 (nm)', fontsize=12)
    ax.set_title(f'{label} — 等高线图 (俯视图)' if label else '等高线图 (俯视图)',
                 fontsize=13)
    ax.invert_yaxis()
    ax.grid(True, alpha=0.25, linestyle='--')
    return cf, vmin, vmax


def draw_waterfall(ax, prep, cmap='plasma', n_traces=10, offset_scale=0.08,
                   smooth_factor=3, label=''):
    """在给定 2D ax 上画堆叠发射谱（用清洗后的数据），返回所选 EX 索引。"""
    ex = prep['ex_orig']
    em = prep['em_orig']
    Z = prep['Z_orig']
    if len(ex) <= n_traces:
        indices = list(range(len(ex)))
    else:
        indices = list(np.linspace(0, len(ex) - 1, n_traces, dtype=int))

    zmax = float(np.nanmax(Z)) if Z.size else 1.0
    offset = zmax * offset_scale
    colors = plt.get_cmap(cmap)(np.linspace(0, 1, max(len(indices), 1)))

    for j, idx in enumerate(indices):
        trace = Z[:, idx]
        if smooth_factor and smooth_factor > 1 and np.isfinite(trace).all():
            try:
                xd = np.linspace(em[0], em[-1], len(em) * int(smooth_factor))
                trace = make_interp_spline(em, trace, k=3)(xd)
            except Exception:
                xd = em
        else:
            xd = em
        ax.plot(xd, trace + j * offset, linewidth=1.0, color=colors[j],
                label=f'EX = {ex[idx]:.0f} nm')

    ax.set_xlabel('EM 波长 (nm)', fontsize=12)
    ax.set_ylabel('强度 (AU) + 偏移', fontsize=12)
    ax.set_title(f'{label} — Waterfall 发射光谱' if label else 'Waterfall 发射光谱',
                 fontsize=13)
    ax.legend(fontsize=8, loc='upper right', ncol=2)
    ax.grid(True, alpha=0.25)
    return indices


# ======================== 4. 独立成图的封装（CLI / 脚本用）========================

def _report_stats(stats, verbose=True):
    """打印清洗统计（verbose=False 时静默，供 GUI 调用）。"""
    if not verbose:
        return
    if stats.get('blank_subtracted'):
        _safe_print("  🧪 已做空白（溶剂）扣除")
    if stats.get('scatter_removed'):
        _safe_print(f"  🚫 剔除散射带 {stats['scatter_removed']} 点"
                    f"（瑞利 {stats.get('scatter_rayleigh', 0)}，"
                    f"拉曼 {stats.get('scatter_raman', 0)}），已沿 EM 内插补全")
    if stats.get('cols_filled_em') or stats.get('cols_filled_ex'):
        _safe_print(f"  🧩 空值补全：沿 EM {stats.get('cols_filled_em', 0)} 列，"
                    f"沿 EX {stats.get('cols_filled_ex', 0)} 列，"
                    f"剩余 NaN {stats.get('nan_left', 0)} 个")
    if stats.get('saturation'):
        extra = ''
        if stats.get('saturation_neighbor_frac') is not None:
            extra = (f"，EM 连续度 {stats['saturation_neighbor_frac']:.0%}"
                     f"、EX 覆盖 {stats.get('saturation_ex_coverage', 0):.0%}")
        _safe_print(f"  🩹 检测到饱和上限 {stats['saturation']:.0f}，"
                    f"修补 {stats['saturation_points']} 点{extra}")
    if stats.get('comb_period'):
        if not stats.get('comb_notched'):
            flag = "未达阈值，保留"
        elif 'comb_rows' in stats:
            flag = f"已替换 {stats['comb_rows']} 个通道"
        elif 'comb_kept' in stats:
            flag = (f"只保留 {stats['comb_kept']} 个谷值通道重建"
                    f"（等效采样 {stats.get('comb_kept_step', 0):.1f} nm）")
        else:
            flag = (f"已按乘性条纹扣除（幅度 ±{stats.get('comb_amp', 0):.2f}，"
                    f"增益 {stats.get('comb_gain_min', 1):.2f}–"
                    f"{stats.get('comb_gain_max', 1):.2f}）")
        _safe_print(f"  〰️  周期梳状伪迹：周期 {stats['comb_period']:.2f} nm，"
                    f"峰/底噪 {stats['comb_strength']:.1f} → {flag}")
    if stats.get('despike_window', 0) >= 3:
        _safe_print(f"  🧹 中值去残余窄线窗口 {stats['despike_window']}"
                    f"（最大改动 {stats.get('despike_delta', 0):.1f}）")
    if stats.get('sigma_em') or stats.get('sigma_ex'):
        _safe_print(f"  🌊 高斯平滑 sigma_EM={stats.get('sigma_em')}, "
                    f"sigma_EX={stats.get('sigma_ex')}")
    if stats.get('comb_residual') is not None:
        res = stats['comb_residual']
        tail = "（残余 >30%，建议换清理模式）" if res > 0.30 else ""
        _safe_print(f"  🔎 校正后残余条纹强度比 {res:.2f}"
                    f"（校正前峰/底噪 {stats.get('comb_strength', 0):.1f}）{tail}")
    if stats.get('comb_replaced_frac') is not None:
        _safe_print(f"  📉 谷值重建：{stats['comb_replaced_frac']:.0%} 的 EM 通道"
                    "由插值给出（峰高可能偏低，窄于一个周期的发射线会被抹平）")
    if stats.get('neg_after_spline'):
        _safe_print(f"  ⚠️  样条加密后出现 {stats['neg_after_spline']} 个负值，"
                    "已截断为 0")
    if not stats.get('axis_uniform', True):
        _safe_print("  ⚠️  EX/EM 坐标非等间距，加密网格可能与数据错位"
                    "（建议先用等间距数据）")


def plot_3d_surface(data, save_dir=".", show=True, cmap='viridis',
                    elev=25, azim=-60, alpha=0.95, smooth_factor=3,
                    percentile=(1.0, 99.5), zlim=None, prep=None, **prep_kw):
    """3D 曲面图（内部走清洗管线；传入 prep 可复用已清洗的网格）。"""
    if prep is None:
        prep = prepare_grid(data, smooth_factor=smooth_factor, **prep_kw)
    _report_stats(prep['stats'], verbose=prep_kw.get('verbose', True))
    fig = plt.figure(figsize=(12, 9))
    ax = fig.add_subplot(111, projection='3d')
    surf, vmin, vmax = draw_surface(
        ax, prep, cmap=cmap, alpha=alpha, elev=elev, azim=azim,
        percentile=percentile, zlim=zlim,
        label=data.get('label', ''), log_scale=prep_kw.get('log_scale', False))
    cbar = fig.colorbar(surf, ax=ax, shrink=0.5, aspect=15, pad=0.12)
    cbar.set_label('log10 强度' if prep_kw.get('log_scale') else '强度 (AU)',
                   fontsize=10)
    fig.tight_layout()
    fname = Path(save_dir) / f"{_safe_label(data.get('label', 'scan'))}_3D_surface.png"
    fig.savefig(fname, dpi=200)
    _safe_print(f"  ✔ 已保存: {fname}")
    if show:
        plt.show()
    else:
        plt.close(fig)
    return prep


def plot_contour(data, save_dir=".", show=True, cmap='viridis',
                 n_levels=30, fill=True, smooth_factor=3,
                 percentile=(1.0, 99.5), zlim=None, prep=None, **prep_kw):
    """等高线图（俯视图）。"""
    if prep is None:
        prep = prepare_grid(data, smooth_factor=smooth_factor, **prep_kw)
    _report_stats(prep['stats'], verbose=prep_kw.get('verbose', True))
    fig, ax = plt.subplots(figsize=(10, 8))
    cf, vmin, vmax = draw_contour(ax, prep, cmap=cmap, n_levels=n_levels,
                                  fill=fill, percentile=percentile, zlim=zlim,
                                  label=data.get('label', ''))
    cbar = fig.colorbar(cf, ax=ax, shrink=0.82, pad=0.02)
    cbar.set_label('log10 强度' if prep_kw.get('log_scale') else '强度 (AU)',
                   fontsize=10)
    fig.tight_layout()
    fname = Path(save_dir) / f"{_safe_label(data.get('label', 'scan'))}_contour.png"
    fig.savefig(fname, dpi=200)
    _safe_print(f"  ✔ 已保存: {fname}")
    if show:
        plt.show()
    else:
        plt.close(fig)
    return prep


def plot_waterfall(data, save_dir=".", show=True, cmap='plasma',
                   n_traces=10, offset_scale=0.08, smooth_factor=3,
                   prep=None, **prep_kw):
    """Waterfall / 堆叠发射谱图。"""
    if prep is None:
        prep = prepare_grid(data, smooth_factor=smooth_factor, **prep_kw)
    _report_stats(prep['stats'], verbose=prep_kw.get('verbose', True))
    fig, ax = plt.subplots(figsize=(12, 8))
    draw_waterfall(ax, prep, cmap=cmap, n_traces=n_traces,
                   offset_scale=offset_scale, smooth_factor=smooth_factor,
                   label=data.get('label', ''))
    fig.tight_layout()
    fname = Path(save_dir) / f"{_safe_label(data.get('label', 'scan'))}_waterfall.png"
    fig.savefig(fname, dpi=200)
    _safe_print(f"  ✔ 已保存: {fname}")
    if show:
        plt.show()
    else:
        plt.close(fig)
    return prep


def _safe_label(label):
    return (label or 'scan').replace('/', '_').replace('\\', '_').replace(' ', '_')


def plot_3d_all(filepath, save_dir=".", show=False, cmap='viridis',
                n_traces=10, smooth_factor=3, verbose=True,
                percentile=(1.0, 99.5), zlim=None, **prep_kw):
    """一键：解析 → 曲面 + 等高线 + waterfall。返回 (data, prep)。"""
    if verbose:
        _safe_print(f"\n📄 处理: {filepath}")
    data = parse_3d_scan_csv(filepath, verbose=verbose)
    Path(save_dir).mkdir(parents=True, exist_ok=True)
    prep = plot_3d_surface(data, save_dir=save_dir, show=show, cmap=cmap,
                           smooth_factor=smooth_factor, percentile=percentile,
                           zlim=zlim, verbose=verbose, **prep_kw)
    plot_contour(data, save_dir=save_dir, show=show, cmap=cmap,
                 smooth_factor=smooth_factor, percentile=percentile,
                 zlim=zlim, prep=prep, **prep_kw)
    plot_waterfall(data, save_dir=save_dir, show=show, n_traces=n_traces,
                   smooth_factor=smooth_factor, prep=prep, **prep_kw)
    return data, prep


# ======================== 5. 命令行 ========================

def main():
    parser = argparse.ArgumentParser(
        description="3D 扫描光谱 CSV → 3D 曲面图 + 等高线图 + Waterfall 图")
    parser.add_argument("file", help="3D 扫描 CSV 文件路径")
    parser.add_argument("-o", "--out", default="./plots", help="输出目录")
    parser.add_argument("--no-show", action="store_true", help="不弹窗")
    parser.add_argument("--cmap", default="viridis", help="颜色映射")
    parser.add_argument("--elev", type=float, default=25, help="3D 仰角")
    parser.add_argument("--azim", type=float, default=-60, help="3D 方位角")
    parser.add_argument("--n-contour", type=int, default=30, help="等高线级数")
    parser.add_argument("--n-traces", type=int, default=10, help="Waterfall 曲线数")
    parser.add_argument("--offset-scale", type=float, default=0.08,
                        help="Waterfall 偏移比例")
    parser.add_argument("--no-3d", action="store_true", help="跳过 3D 曲面图")
    parser.add_argument("--no-contour", action="store_true", help="跳过等高线图")
    parser.add_argument("--no-waterfall", action="store_true", help="跳过 Waterfall")
    parser.add_argument("--smooth", type=int, default=3,
                        help="三次样条加密倍数（1=不加密）")
    # ---- 清洗参数 ----
    parser.add_argument("--despike", type=int, default=5,
                        help="沿 EM 的中值去残余窄线窗口（默认 5，0/1=关闭）")
    parser.add_argument("--sigma-em", type=float, default=1.0,
                        help="沿 EM 的高斯平滑 sigma（默认 1.0，0=关闭）")
    parser.add_argument("--no-notch", action="store_true",
                        help="不做周期梳状伪迹陷波（默认自动检测并扣除）")
    parser.add_argument("--comb-period", type=float, default=None,
                        help="手动指定梳状伪迹周期 (nm)；默认自动检测")
    parser.add_argument("--notch-harmonics", type=int, default=4,
                        help="陷波扣除到第几次谐波（默认 4）")
    parser.add_argument("--comb-mode", choices=['minima', 'divide', 'rows'],
                        default='minima',
                        help="梳状伪迹处理：minima=只保留谷值通道重建（默认，最稳）；"
                             "divide=按乘性条纹除法；rows=污染通道整行插值替换")
    parser.add_argument("--sigma-ex", type=float, default=0.0,
                        help="沿 EX 的高斯平滑 sigma（默认 0）")
    parser.add_argument("--no-clip-saturation", action="store_true",
                        help="不自动修补饱和点")
    parser.add_argument("--remove-scatter", action="store_true",
                        help="剔除瑞利/拉曼散射带（默认关闭）")
    parser.add_argument("--rayleigh-width", type=float, default=10.0,
                        help="瑞利带半宽 (nm)，默认 10")
    parser.add_argument("--raman-width", type=float, default=15.0,
                        help="拉曼带半宽 (nm)，默认 15")
    parser.add_argument("--log", action="store_true", help="对数色标/强度")
    parser.add_argument("--percentile", default="1,99.5",
                        help="稳健色标分位（默认 1,99.5）")
    parser.add_argument("--zlim", default=None, help="手动色标范围 lo,hi")
    args = parser.parse_args()

    Path(args.out).mkdir(parents=True, exist_ok=True)
    show = not args.no_show
    percentile = tuple(float(x) for x in args.percentile.split(','))
    zlim = tuple(float(x) for x in args.zlim.split(',')) if args.zlim else None
    prep_kw = dict(spike_window=args.despike, sigma_em=args.sigma_em,
                   sigma_ex=args.sigma_ex,
                   clip_saturation=not args.no_clip_saturation,
                   notch_comb=not args.no_notch,
                   notch_period=args.comb_period,
                   notch_harmonics=args.notch_harmonics,
                   comb_mode=args.comb_mode,
                   remove_scatter=args.remove_scatter,
                   rayleigh_width=args.rayleigh_width,
                   raman_width=args.raman_width,
                   log_scale=args.log)

    _safe_print(f"\n📄 处理: {args.file}")
    data = parse_3d_scan_csv(args.file)
    prep = prepare_grid(data, smooth_factor=args.smooth, **prep_kw)
    _report_stats(prep['stats'])

    if not args.no_3d:
        _safe_print("\n🎨 生成 3D 曲面图...")
        fig = plt.figure(figsize=(12, 9))
        ax = fig.add_subplot(111, projection='3d')
        surf, vmin, vmax = draw_surface(
            ax, prep, cmap=args.cmap, elev=args.elev, azim=args.azim,
            zlim=zlim, percentile=percentile, label=data['label'],
            log_scale=args.log)
        cbar = fig.colorbar(surf, ax=ax, shrink=0.5, aspect=15, pad=0.12)
        cbar.set_label('log10 强度' if args.log else '强度 (AU)', fontsize=10)
        fig.tight_layout()
        fname = Path(args.out) / f"{_safe_label(data['label'])}_3D_surface.png"
        fig.savefig(fname, dpi=200)
        _safe_print(f"  ✔ 已保存: {fname}")
        plt.close(fig) if not show else plt.show()

    if not args.no_contour:
        _safe_print("\n🎨 生成等高线图...")
        fig, ax = plt.subplots(figsize=(10, 8))
        cf, vmin, vmax = draw_contour(ax, prep, cmap=args.cmap,
                                      n_levels=args.n_contour, zlim=zlim,
                                      percentile=percentile, label=data['label'])
        cbar = fig.colorbar(cf, ax=ax, shrink=0.82, pad=0.02)
        cbar.set_label('log10 强度' if args.log else '强度 (AU)', fontsize=10)
        fig.tight_layout()
        fname = Path(args.out) / f"{_safe_label(data['label'])}_contour.png"
        fig.savefig(fname, dpi=200)
        _safe_print(f"  ✔ 已保存: {fname}")
        plt.close(fig) if not show else plt.show()

    if not args.no_waterfall:
        _safe_print("\n🎨 生成 Waterfall 图...")
        fig, ax = plt.subplots(figsize=(12, 8))
        draw_waterfall(ax, prep, cmap='plasma', n_traces=args.n_traces,
                       offset_scale=args.offset_scale,
                       smooth_factor=args.smooth, label=data['label'])
        fig.tight_layout()
        fname = Path(args.out) / f"{_safe_label(data['label'])}_waterfall.png"
        fig.savefig(fname, dpi=200)
        _safe_print(f"  ✔ 已保存: {fname}")
        plt.close(fig) if not show else plt.show()

    _safe_print("\n✅ 完成！")


if __name__ == "__main__":
    main()
