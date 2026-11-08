# -*- coding: utf-8 -*-
"""线性标定 / 检出限 / Stern–Volmer 模块（plot_calibration）
==========================================================
适用数据
--------
一批**同类型**光谱（发射或吸收的 CSV / TXT，一行一个波长点）+ 同目录下的
``说明.xlsx``（列名如 ``编号 / RB浓度 / Ce6浓度 / L8i浓度``，见 read_xlsx_info）。

``plot_compare`` 能把每条谱压成一个读数并画成点线图，但**止步于点线图**——
没有回归、没有 R²、没有 LOD。而标定实验的产出物恰恰是
「斜率 / 截距 / R² / 检出限 / 线性范围」。本模块补上这一段。

功能
----
1. :func:`linear_calibration` —— 最小二乘（可选加权）拟合 ``y = a + b·x``，
   给出斜率和截距的**标准误**（用正确的回归公式，不是除以 n）、R²、校正 R²、
   回归标准误 ``s_yx``、残差。
2. :func:`lod_loq` —— 按 IUPAC 口径 ``LOD = k·s_yx/|b|``、``LOQ = 10·s_yx/|b|``，
   另外给出**空白标准差的估计**与**线性范围**（按残差判据从两端剔除非线性层级）。
3. :func:`lack_of_fit_test` —— 有重复测量时做**失拟检验**（ANOVA），
   定量回答"直线到底够不够"，而不是只看 R²。
4. :func:`stern_volmer` —— ``I0/I = 1 + Ksv[Q]``（线性）与
   ``I0/I = 1 + K1[Q] + K2[Q]²``（静态+动态混合猝灭）两个模型**同时拟合**，
   并用 **F 检验 + AICc** 给出"哪个模型更合适"的判据。
5. :func:`plot_calibration` —— 标定图（数据点 + 拟合线 + 95% 置信带 +
   95% 预测带 + LOD/LOQ 标线）+ 残差图。
6. :func:`calibrate_from_folder` —— 一键：读光谱 → **可比性预检** →
   压成读数（复用 ``plot_compare.collect_points``）→ 回归 → 出图 → 出表。

一键用法
--------
::

    from plot_calibration import calibrate_from_folder

    out = calibrate_from_folder(
        folder=r'D:\\...\\示例数据\\05-数据比较-浓度梯度',
        x_var='RB浓度',
        metric='peak_intensity',
        band=(555, 620),          # 不给则按谱峰自动定带（会打印选了哪段）
        save_dir=r'./plots',
    )
    print(out['slope'], out['r2'], out['lod'], out['loq'])

命令行用法
----------
::

    python plot_calibration.py "D:\\data\\05" --x RB浓度 --band 555 620
    python plot_calibration.py "D:\\data\\05" --x Ce6浓度 --band 655 685 --dpi 300
    python plot_calibration.py "D:\\data\\05" --list-vars
    python plot_calibration.py --demo          # 合成真值自检（不需要数据）

统计口径（这三条最常被写错）
----------------------------
* 回归标准误 ``s_yx = sqrt(RSS/(n-2))`` —— 残差平方和除以**自由度**，
  不是除以 n，也不是 ``s_yx/sqrt(n)``。
* ``SE(b) = s_yx / sqrt(Σ(x-x̄)²)``；``SE(a) = s_yx·sqrt(1/n + x̄²/Σ(x-x̄)²)``。
* ``LOD = 3·s_yx/|b|``、``LOQ = 10·s_yx/|b|`` —— **单位是 x 的单位**（浓度），
  不是响应值单位；写报告时别写成强度。

边界情况（都有明确行为，不会静默返回 nan）
------------------------------------------
============================  ==========================================
情形                          行为
============================  ==========================================
有效点 < 2                     ``CalibrationError`` 明确报错，消息含实际
                              个数与丢弃个数
只有 2 个点                    降级：``s_yx`` / ``SE`` / 置信区间 /
                              ``LOD`` 全部返回 ``None``（自由度 0，
                              估不出来），``status='degraded'``，
                              并在 ``warnings`` 里写明原因；不返回 nan
所有 x 相同                     ``CalibrationError``（Σ(x-x̄)²=0，
                              斜率无定义），消息列出重复的那个 x
y 全部相同                     降级：斜率 = 0、``r2`` 返回 ``None``、
                              ``LOD`` 无定义并写明"响应值没有随浓度变化"
含 NaN / inf                  默认丢弃并**记录丢了几点、丢在哪**
                              （``n_dropped`` / ``dropped_index``）；
                              剩下的点 < 2 才报错。``nan_policy='raise'``
                              可改成直接报错
============================  ==========================================

依赖：只用 numpy / scipy / matplotlib（另加同目录的 ``read_xlsx_info``、
``plot_compare``、``plot_emission`` / ``plot_absorption``、``export_defaults``）。
"""

import argparse
import contextlib
import csv
import datetime
import io
import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from scipy import stats

# ---- 同目录模块（独立运行本文件时也能找到；做法同 plot_compare） ----
try:
    from read_xlsx_info import load_xlsx_info
    from plot_compare import (METRIC_ORDER, _safe_print, collect_points,
                              describe_metric, setup_chinese_font)
except ImportError:                                     # pragma: no cover
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from read_xlsx_info import load_xlsx_info
    from plot_compare import (METRIC_ORDER, _safe_print, collect_points,
                              describe_metric, setup_chinese_font)

# 导出口径单一来源（v5.0.2）：`dpi=None` 时回落到这里，和 GUI / 其它 plot_*.py
# 用同一组 DPI，避免"同一份数据从两条路径导出的图分辨率差 2–3 倍"。
try:
    from export_defaults import EXPORT_DPI_DEFAULT
except ImportError:                                     # pragma: no cover
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from export_defaults import EXPORT_DPI_DEFAULT
    except ImportError:
        EXPORT_DPI_DEFAULT = 600

# 中文字体：plot_compare 在导入时已经设过一次；这里再设一次不产生副作用，
# 但保证本模块被单独 import（不经 plot_compare）时图上的中文也正常。
setup_chinese_font()


# ======================== 0. 常量 / 异常 ========================

#: 置信带 / 预测带 / 区间估计用的默认水平
CI_LEVEL = 0.95

#: 默认"离群点"判据：标准化残差绝对值超过它就在图上标红圈
DEFAULT_OUTLIER_SIGMA = 3.0

#: 收缩线性范围时至少要保留几个不同的 x 值
MIN_LEVELS_FOR_RANGE = 3

#: 判定"两个 x 相同"的相对容差（浮点浓度常有 1e-16 级噪声）
X_RTOL = 1e-9


class CalibrationError(ValueError):
    """标定无法进行（数据不足 / 除零 / 斜率为 0 等），消息里写明原因与修法。

    单独一个异常类的作用：调用方可以 ``except CalibrationError`` 精确区分
    "数据本身不够 / 不合理"（可以提示用户去改数据）与 "代码 bug"。
    """


# ======================== 1. 数值小工具 ========================

def _as_float_array(v, name='值'):
    """转成 1 维 float ndarray；转不动就明确报错（不静默变 nan）。"""
    try:
        arr = np.asarray(v, dtype=float).ravel()
    except (TypeError, ValueError) as e:
        raise CalibrationError(f'{name} 无法转成数值数组：{e}') from e
    if arr.size == 0:
        raise CalibrationError(f'{name} 是空数组，没法标定')
    return arr


def _finite_filter(x, y, nan_policy='drop'):
    """按 ``nan_policy`` 处理非有限值。

    返回 ``(x, y, 保留掩码, {'n_dropped': int, 'dropped_index': [int]})``。
    ``drop`` 是默认：丢弃但**记录**（报告里能说清丢了几点、哪几点）；
    ``raise`` 直接报错并列出位置。
    """
    bad = ~(np.isfinite(x) & np.isfinite(y))
    n_bad = int(bad.sum())
    if n_bad == 0:
        return x, y, np.ones(x.size, bool), {'n_dropped': 0, 'dropped_index': []}
    if nan_policy == 'raise':
        idx = [int(i) for i in np.flatnonzero(bad)]
        raise CalibrationError(
            f'x/y 里有 {n_bad} 个非有限值（NaN 或 inf），位置（0 起）：{idx}。'
            '传 nan_policy=\'drop\' 可以自动丢弃并记录，或先把数据清洗干净。')
    keep = ~bad
    return (x[keep], y[keep], keep,
            {'n_dropped': n_bad,
             'dropped_index': [int(i) for i in np.flatnonzero(bad)]})


def _fmt_num(v, sig=4):
    """把数字排成"给人看"的短字符串；None / nan 显示「—」。"""
    if v is None:
        return '—'
    try:
        fv = float(v)
    except (TypeError, ValueError):
        return str(v)
    if not np.isfinite(fv):
        return '—'
    if fv == 0:
        return '0'
    a = abs(fv)
    if a >= 1e5 or a < 1e-3:
        return f'{fv:.{sig - 1}e}'
    return f'{fv:.{sig}g}'


def _fmt_pm(v, se, sig=4):
    """``值 ± 标准误``；标准误估不出来时只写值。"""
    if v is None:
        return '—'
    if se is None:
        return _fmt_num(v, sig)
    return f'{_fmt_num(v, sig)} ± {_fmt_num(se, max(sig - 1, 2))}'


def _same_x(a, b):
    """两个浓度值是否算"同一个 x"（相对容差）。"""
    return abs(float(a) - float(b)) <= X_RTOL * max(1.0, abs(float(a)))


# ======================== 2. 线性回归（核心） ========================

def linear_calibration(x, y, weights=None, nan_policy='drop',
                       ci_level=CI_LEVEL):
    """最小二乘（或加权最小二乘）拟合 ``y = a + b·x``，返回统计量字典。

    参数
    ----
    x, y : array-like
        自变量（浓度等）与响应值（峰强度 / 峰面积 / I0/I…）。长度必须一致。
    weights : array-like | None
        权重 ``w = 1/σ_i²``（标准 WLS 口径：第 i 点按 ``√w`` 加权）。
        None = 普通最小二乘。**同一浓度有重复测量时不要只传均值**：
        直接传全部逐点数据，普通最小二乘对不等重复数是无偏的。
    nan_policy : {'drop', 'raise'}
        见 :func:`_finite_filter`。
    ci_level : float
        斜率 / 截距置信区间的水平，默认 0.95。

    返回
    ----
    dict：

    ``slope`` / ``intercept``          斜率 b、截距 a
    ``slope_se`` / ``intercept_se``    标准误；自由度 ≤ 0 或估不出时为 ``None``
    ``slope_ci`` / ``intercept_ci``    置信区间 ``(lo, hi)``，同上为 ``None``
    ``s_yx``                           **回归标准误** ``sqrt(RSS/(n-2))``
    ``rmse``                           ``sqrt(RSS/n)``（未做自由度修正）
    ``r2`` / ``adj_r2``                y 全相同时 ``r2`` 为 ``None``
    ``slope_t`` / ``slope_p``          斜率异于 0 的 t 检验
    ``n`` / ``n_input`` / ``n_dropped`` / ``dropped_index``
    ``residuals`` / ``fitted`` / ``x`` / ``y`` / ``weights``
    ``xbar`` / ``ybar`` / ``sxx`` / ``sxy`` / ``rss`` / ``tss`` / ``dof``
    ``status``（``'ok'`` / ``'degraded'``）/ ``ok`` / ``warnings``

    公式
    ----
    ``b = Sxy/Sxx``，``a = ȳ − b·x̄``（加权时为加权均值），
    ``s_yx = sqrt(RSS/(n−2))``，
    ``SE(b) = s_yx/sqrt(Sxx)``，
    ``SE(a) = s_yx·sqrt(1/Σw + x̄²/Sxx)``（``w`` 全 1 时即 ``1/n``）。
    """
    x = _as_float_array(x, 'x').copy()
    y = _as_float_array(y, 'y').copy()
    if x.size != y.size:
        raise CalibrationError(
            f'x 与 y 长度不一致（{x.size} vs {y.size}），无法逐点配对')

    n_input = x.size
    w = None
    if weights is not None:
        w = _as_float_array(weights, 'weights').copy()
        if w.size != n_input:
            raise CalibrationError(
                f'weights 长度（{w.size}）与 x（{n_input}）不一致')
        if np.any(~np.isfinite(w)) or np.any(w <= 0):
            raise CalibrationError('weights 必须是有限正数（w = 1/σ²）')

    x, y, keep, dropped = _finite_filter(x, y, nan_policy=nan_policy)
    if w is not None:
        w = w[keep]
    n = x.size
    if n < 2:
        raise CalibrationError(
            f'有效点只有 {n} 个（输入 {n_input} 个，丢弃 {dropped["n_dropped"]} 个），'
            '至少要 2 个点才能拟合直线')

    # ---- 加权口径统一：w=None 时全 1，与普通最小二乘完全等价 ----
    if w is None:
        w = np.ones(n)
    sw = float(w.sum())
    xbar = float((w * x).sum() / sw)
    ybar = float((w * y).sum() / sw)
    dx = x - xbar
    dy = y - ybar
    sxx = float((w * dx * dx).sum())
    sxy = float((w * dx * dy).sum())

    warnings = []
    ok = True

    if not np.isfinite(sxx) or sxx <= 0:
        # 所有 x 相同（或权重全压在同一个 x 上）→ Σ(x-x̄)²=0 → 斜率除以 0
        uniq = np.unique(x)
        raise CalibrationError(
            f'所有点的 x 都相同（不同的 x 只有 {uniq.size} 个：'
            f'{", ".join(_fmt_num(u) for u in uniq[:6])}），'
            'Σ(x-x̄)²=0，斜率无法定义。标定至少要 2 个**不同**的浓度。')

    slope = sxy / sxx
    intercept = ybar - slope * xbar
    fitted = intercept + slope * x
    residuals = y - fitted
    rss = float((w * residuals ** 2).sum())
    tss = float((w * dy ** 2).sum())
    dof = n - 2

    # ---- 回归标准误 s_yx = sqrt(RSS/(n-2))，再由此得两个标准误 ----
    if dof > 0:
        s_yx = float(np.sqrt(rss / dof))
        rmse = float(np.sqrt(rss / n))
        slope_se = float(s_yx / np.sqrt(sxx))
        intercept_se = float(s_yx * np.sqrt(1.0 / sw + xbar ** 2 / sxx))
        tcrit = float(stats.t.ppf(0.5 + ci_level / 2.0, dof))
        slope_ci = (float(slope - tcrit * slope_se),
                    float(slope + tcrit * slope_se))
        intercept_ci = (float(intercept - tcrit * intercept_se),
                        float(intercept + tcrit * intercept_se))
    else:
        # n == 2：直线必然穿过两点，RSS=0、自由度 0 → 标准误估不出来。
        # 明确返回 None 并说明，而不是返回 0 或 nan 让人误以为"很准"。
        s_yx = None
        rmse = float(np.sqrt(rss / n))
        slope_se = intercept_se = None
        slope_ci = intercept_ci = None
        ok = False
        warnings.append(
            f'只有 {n} 个有效点：直线必然过两点，残差恒为 0，'
            '标准误 / 置信区间 / LOD 都无法估计（自由度 n−2=0）。'
            '至少补到 3 个点再看统计量。')

    # ---- R² ----
    if tss > 0:
        r2 = 1.0 - rss / tss
        if abs(r2) < 1e-12:            # 纯数值噪声，规范化成 0
            r2 = 0.0
        adj_r2 = (1.0 - (1.0 - r2) * (n - 1) / dof) if dof > 0 else None
    else:
        r2 = None
        adj_r2 = None
        ok = False
        warnings.append(
            'y 全部相同（TSS=0）：R² 无定义，斜率为 0；'
            '这种数据不能做标定（响应值没有随浓度变化）。')

    # ---- 斜率显著性 t = b/SE(b) ----
    if slope_se is not None and slope_se > 0:
        t_val = float(slope / slope_se)
        p_val = float(2.0 * stats.t.sf(abs(t_val), dof))
    else:
        t_val, p_val = None, None

    return {
        'slope': float(slope),
        'intercept': float(intercept),
        'slope_se': slope_se,
        'intercept_se': intercept_se,
        'slope_ci': slope_ci,
        'intercept_ci': intercept_ci,
        's_yx': s_yx,
        'rmse': rmse,
        'r2': r2,
        'adj_r2': adj_r2,
        'slope_t': t_val,
        'slope_p': p_val,
        'n': int(n),
        'n_input': int(n_input),
        'n_dropped': int(dropped['n_dropped']),
        'dropped_index': dropped['dropped_index'],
        'xbar': xbar, 'ybar': ybar,
        'sxx': sxx, 'sxy': sxy,
        'rss': rss, 'tss': tss, 'dof': int(dof),
        'x': x, 'y': y, 'fitted': fitted, 'residuals': residuals,
        'weights': w,
        'ci_level': float(ci_level),
        'status': 'ok' if ok else 'degraded',
        'ok': bool(ok),
        'warnings': warnings,
    }


def predict_interval(calib, x_new, level=CI_LEVEL):
    """给定拟合结果，算 ``x_new`` 处的拟合值、均值置信区间与**预测区间**。

    预测区间比置信区间宽，因为还要容纳"下一次测量"的随机误差：
    ``ŷ ± t·s_yx·sqrt(1 + 1/n + (x−x̄)²/Sxx)``。
    报告"某个信号对应浓度的不确定度"用的是预测区间，不是置信带。
    """
    if calib.get('s_yx') is None or calib.get('dof', 0) <= 0:
        raise CalibrationError(
            '没有回归标准误（自由度 ≤ 0，通常是点太少），算不出区间')
    xs = _as_float_array(x_new, 'x_new')
    b, a = calib['slope'], calib['intercept']
    s, sxx, xbar = calib['s_yx'], calib['sxx'], calib['xbar']
    sw = float(np.sum(calib['weights'])) if calib.get('weights') is not None \
        else float(calib['n'])
    tcrit = float(stats.t.ppf(0.5 + level / 2.0, calib['dof']))
    yhat = a + b * xs
    d2 = (xs - xbar) ** 2
    half_mean = tcrit * s * np.sqrt(1.0 / sw + d2 / sxx)
    half_pred = tcrit * s * np.sqrt(1.0 + 1.0 / sw + d2 / sxx)
    return {
        'x': xs, 'yhat': yhat,
        'mean_lo': yhat - half_mean, 'mean_hi': yhat + half_mean,
        'pred_lo': yhat - half_pred, 'pred_hi': yhat + half_pred,
    }


def aggregate_replicates(x, y, rtol=X_RTOL):
    """把同一 x 上的重复测量聚成一个"浓度点"：``[{x, n, mean, sd, sem}]``。

    用途：图上"均值 ± 标准差"误差棒、标定表里的逐浓度汇总。

    **注意**：不要用这些均值再去拟合**并**以此估 ``s_yx``——那会把重复测量的
    纯误差抹掉，``s_yx`` 被人为压小、LOD 假性变好。要拟合就直接用逐点数据
    （:func:`linear_calibration` 对不等重复数是无偏的），纯误差由
    :func:`lack_of_fit_test` 单独估。
    """
    x = _as_float_array(x, 'x')
    y = _as_float_array(y, 'y')
    if x.size != y.size:
        raise CalibrationError(f'x 与 y 长度不一致（{x.size} vs {y.size}）')
    keep = np.isfinite(x) & np.isfinite(y)
    x, y = x[keep], y[keep]
    if x.size == 0:
        return []
    order = np.argsort(x, kind='stable')
    x, y = x[order], y[order]
    out = []
    start = 0
    for i in range(1, x.size + 1):
        if i == x.size or not _same_x(x[i], x[i - 1]):
            sub = y[start:i]
            m = int(sub.size)
            mean = float(sub.mean())
            sd = float(sub.std(ddof=1)) if m > 1 else None
            sem = (sd / np.sqrt(m)) if sd is not None else None
            out.append({'x': float(x[start]), 'n': m, 'mean': mean,
                        'sd': sd, 'sem': sem})
            start = i
    return out


def lack_of_fit_test(x, y, nan_policy='drop'):
    """**失拟检验**（lack-of-fit, ANOVA）：直线模型够不够，R² 说了不算。

    只有同一 x 上有重复测量时才做得了——纯误差由重复测量的离散给出：

    ``SS_pe = Σ_i Σ_j (y_ij − ȳ_i)²``，``df_pe = n − k``
    ``SS_lof = Σ_i n_i·(ȳ_i − ŷ_i)²``，``df_lof = k − 2``
    ``F = (SS_lof/df_lof) / (SS_pe/df_pe)``，k = 不同 x 的个数

    F 显著（p < 0.05）说明"直线与数据的偏离明显大于纯测量误差"，
    即**存在系统弯曲**——此时 R² 再高也不能把线性关系外推到整个区间。

    返回 ``f`` / ``p`` / ``df_lof`` / ``df_pe`` / ``ss_lof`` / ``ss_pe`` /
    ``n_levels`` / ``n`` / ``usable`` / ``reason`` / ``verdict``（中文一句话）。
    """
    x = _as_float_array(x, 'x')
    y = _as_float_array(y, 'y')
    if x.size != y.size:
        raise CalibrationError(f'x 与 y 长度不一致（{x.size} vs {y.size}）')
    x, y, _keep, _d = _finite_filter(x, y, nan_policy=nan_policy)
    levels = aggregate_replicates(x, y)
    k = len(levels)
    n = x.size
    if k < 3:
        return {'f': None, 'p': None, 'df_lof': 0, 'df_pe': 0,
                'ss_lof': None, 'ss_pe': None, 'n_levels': k, 'n': int(n),
                'usable': False,
                'reason': f'只有 {k} 个不同的 x（<3），做不了失拟检验',
                'verdict': '无法判断（浓度点太少）'}
    df_pe = n - k
    df_lof = k - 2
    if df_pe <= 0:
        return {'f': None, 'p': None, 'df_lof': int(df_lof), 'df_pe': 0,
                'ss_lof': None, 'ss_pe': None, 'n_levels': int(k), 'n': int(n),
                'usable': False,
                'reason': '每个浓度都只有 1 次测量，没有纯误差可估（df_pe=0）',
                'verdict': '无法判断（没有重复测量）'}

    calib = linear_calibration(x, y, nan_policy=nan_policy)
    ss_pe = 0.0
    ss_lof = 0.0
    for lv in levels:
        sel = np.array([_same_x(xi, lv['x']) for xi in x])
        sub = y[sel]
        if lv['n'] > 1:
            ss_pe += float(((sub - sub.mean()) ** 2).sum())
        fitted_level = calib['intercept'] + calib['slope'] * lv['x']
        ss_lof += lv['n'] * float((lv['mean'] - fitted_level) ** 2)

    if ss_pe <= 0:
        f_val, p_val = float('inf'), 0.0
    else:
        f_val = (ss_lof / df_lof) / (ss_pe / df_pe)
        p_val = float(stats.f.sf(f_val, df_lof, df_pe))
    if p_val < 0.05:
        verdict = (f'直线模型**不充分**（F={f_val:.2f}，p={p_val:.3g} < 0.05）：'
                   '数据存在系统性弯曲，超出线性范围外推会算错浓度')
    elif p_val < 0.20:
        verdict = (f'有弯曲倾向（F={f_val:.2f}，p={p_val:.3g}，0.05–0.20）：'
                   '线性关系勉强成立，建议检查高浓度端是否已进入非线性区')
    else:
        verdict = f'直线模型可以接受（F={f_val:.2f}，p={p_val:.3g} ≥ 0.05）'
    return {'f': float(f_val), 'p': p_val, 'df_lof': int(df_lof),
            'df_pe': int(df_pe), 'ss_lof': float(ss_lof),
            'ss_pe': float(ss_pe), 'n_levels': int(k), 'n': int(n),
            'usable': True, 'reason': '', 'verdict': verdict}


# ======================== 3. LOD / LOQ / 线性范围 ========================

def _blank_sd(x, y):
    """估**空白（本底）标准差** ``s0``。

    优先用 x=0 的重复点；其次用最低浓度处的重复点（同一浓度重复测量 = 纯误差）；
    再次用多点合并（pooled）标准差；都没有就返回 ``None``。

    为什么不能只用 ``s_yx``：``s_yx`` 混进了"拟合不完美"（弯曲、浓度误差）这一项，
    会比真实仪器噪声大；IUPAC 的 ``s0`` 严格指**空白测量的标准差**。
    有空白/重复测量时用纯误差估更接近定义，没有才退回 ``s_yx``。

    返回 ``(s0, 来源说明, 自由度)``。
    """
    levels = aggregate_replicates(x, y)
    if not levels:
        return None, '没有可用数据', 0
    # ① x=0 的重复测量（真正的空白）
    for lv in levels:
        if abs(lv['x']) <= X_RTOL and lv['n'] >= 2:
            return lv['sd'], f'空白（x=0）{lv["n"]} 次重复测量的标准差', lv['n'] - 1
    # ② 最低浓度处的重复测量：同浓度重复 = 纯测量误差
    lowest = levels[0]
    if lowest['n'] >= 2:
        return (lowest['sd'],
                f'最低浓度点（x={_fmt_num(lowest["x"])}）{lowest["n"]} 次重复的'
                '标准差（同浓度重复 = 纯测量误差）', lowest['n'] - 1)
    # ③ 多点合并（pooled）标准差
    num, den = 0.0, 0
    for lv in levels:
        if lv['n'] >= 2:
            num += (lv['n'] - 1) * lv['sd'] ** 2
            den += lv['n'] - 1
    if den > 0:
        return float(np.sqrt(num / den)), f'{den} 个自由度的合并（pooled）标准差', den
    return None, '每个浓度都只有 1 次测量，估不出纯误差', 0


def _trim_linear_range(x, y, calib, sigma=3.0,
                       min_levels=MIN_LEVELS_FOR_RANGE, max_iter=10):
    """按残差判据从**两端**剔除非线性层级，给出线性范围。

    判据：用当前保留点拟合直线，算**标准化残差** ``r_i/s_yx``；只在最左 / 最右
    两个浓度层级里找 ``|r_i/s_yx| > sigma`` 的层级，剔除偏离更大的那一端，
    重拟合，直到两端都不超限或剩余层级 ≤ ``min_levels``。

    为什么按"层级"整体剔除而不是逐点：同一个浓度的重复测量是同一份样品，
    只扔其中一个是自欺欺人（会让那一点凭空贴合直线）。

    .. warning::
       **本函数未经实测验证，点数少时可能过于激进。**
       每剔除一层都要重拟合，``s_yx`` 随之变小，下一轮判据更严——这是个会自我
       加强的循环。浓度层级只有 5–6 个时，它可能连着剔掉 2 层，把本来只是
       "两端略有弯曲"的数据收缩成很窄的区间。
       **当 ``n_levels < 6`` 时请人工核对返回的 ``linear_range``**，
       不要直接按它写"本方法线性范围为 x–y"。
       保守用法：先把 ``sigma`` 调大（如 4.0）再看会不会剔；或直接忽略
       ``linear_range``，用实验设计的浓度区间作线性范围并附失拟检验结论。
    """
    x = _as_float_array(x, 'x')
    y = _as_float_array(y, 'y')
    keep = np.isfinite(x) & np.isfinite(y)
    dropped = []
    if calib.get('s_yx') in (None, 0):
        vals = x[keep]
        return {'x_min': float(vals.min()) if vals.size else None,
                'x_max': float(vals.max()) if vals.size else None,
                'n_levels': len(aggregate_replicates(x[keep], y[keep])),
                'n_points': int(vals.size), 'dropped_levels': [],
                'sigma': float(sigma),
                'reason': '没有回归标准误，无法用残差判据收缩线性范围'}
    reason = f'两端点的标准化残差都在 ±{sigma:g} 以内，线性范围即全部数据区间'

    for _ in range(max_iter):
        levels = aggregate_replicates(x[keep], y[keep])
        if len(levels) <= min_levels:
            reason = (f'剩余浓度层级 {len(levels)} 个，已到下限'
                      f'（至少保留 {min_levels} 个不同浓度），停止收缩')
            break
        fit = linear_calibration(x[keep], y[keep])
        if fit.get('s_yx') in (None, 0):
            reason = '重拟合后没有回归标准误，停止收缩'
            break
        std_resid = fit['residuals'] / fit['s_yx']
        lo_x, hi_x = levels[0]['x'], levels[-1]['x']
        lo_sel = np.array([_same_x(v, lo_x) for v in fit['x']])
        hi_sel = np.array([_same_x(v, hi_x) for v in fit['x']])
        lo_max = float(np.max(np.abs(std_resid[lo_sel]))) if lo_sel.any() else -1.0
        hi_max = float(np.max(np.abs(std_resid[hi_sel]))) if hi_sel.any() else -1.0
        lo_bad = lo_max > sigma
        hi_bad = hi_max > sigma
        if not (lo_bad or hi_bad):
            reason = (f'两端的最低 / 最高浓度点标准化残差都在 ±{sigma:g} 以内，'
                      '线性范围就是全部数据覆盖的区间')
            break
        if lo_bad and (not hi_bad or lo_max >= hi_max):
            target, side, worst = lo_x, '低浓度端', lo_max
        else:
            target, side, worst = hi_x, '高浓度端', hi_max
        sel = np.array([_same_x(v, target) for v in x])
        keep &= ~sel
        dropped.append({'x': float(target), 'side': side,
                        'max_abs_std_resid': float(worst),
                        'n_points': int(sel.sum())})
        reason = (f'从{side}（x={_fmt_num(target)}，|标准化残差| 最大 '
                  f'{worst:.2f} > {sigma:g}）开始剔除；共剔除 '
                  f'{len(dropped)} 个浓度层级')

    kept_x = x[keep]
    levels = aggregate_replicates(x[keep], y[keep])
    return {'x_min': float(kept_x.min()) if kept_x.size else None,
            'x_max': float(kept_x.max()) if kept_x.size else None,
            'n_levels': len(levels), 'n_points': int(kept_x.size),
            'dropped_levels': dropped, 'sigma': float(sigma),
            'reason': reason}


def lod_loq(x, y, k_lod=3.0, k_loq=10.0, weights=None, nan_policy='drop',
            blank_sd=None, calibrate=None):
    """按 IUPAC 口径算检出限 / 定量限，并给出空白标准差与线性范围。

    ``LOD = k_lod·s_yx/|b|``，``LOQ = k_loq·s_yx/|b|`` —— **单位是 x 的单位**
    （浓度 / 活度），不是强度。``s_yx`` 是回归标准误 ``sqrt(RSS/(n−2))``。

    参数
    ----
    x, y : array-like     标定数据（逐点，含重复测量）
    k_lod, k_loq : float  IUPAC 默认 3 与 10
    blank_sd : float | None
        已知空白标准差时直接给（例如同一空白测了 10 次算出的）。
        不给则用 :func:`_blank_sd` 从数据估。
    calibrate : dict | None
        已算好的 :func:`linear_calibration` 结果，避免重复拟合。

    返回
    ----
    dict：``lod`` / ``loq`` / ``lod_conc`` / ``loq_conc``（同义键）/
    ``k_lod`` / ``k_loq`` / ``s_yx`` / ``slope`` / ``blank_sd`` /
    ``blank_sd_source`` / ``blank_sd_dof`` / ``lod_from_blank`` /
    ``loq_from_blank`` / ``linear_range`` / ``calibration`` / ``warnings`` / ``ok``

    估不出时（只有 2 点、斜率为 0）``lod`` / ``loq`` 为 ``None`` 并在
    ``warnings`` 写明原因，**不返回 nan 也不返回 0**。
    """
    if calibrate is None:
        calibrate = linear_calibration(x, y, weights=weights,
                                      nan_policy=nan_policy)
    b = calibrate['slope']
    s = calibrate['s_yx']
    warnings = []
    ok = True

    if s is None:
        ok = False
        warnings.append('自由度 n−2=0（只有 2 个点），s_yx 估不出来 → '
                        'LOD / LOQ 无法计算（返回 None，不是 nan 也不是 0）')
    if b is None or abs(b) <= 0:
        ok = False
        warnings.append('斜率为 0：响应值与浓度无关，'
                        'LOD = k·s/|b| 变成除以 0，无法定义检出限')

    lod = loq = None
    if ok:
        lod = k_lod * s / abs(b)
        loq = k_loq * s / abs(b)

    # ---- 空白标准差 ----
    if blank_sd is not None:
        s0 = float(blank_sd)
        s0_src = '调用方直接给出的空白标准差'
        s0_dof = None
    else:
        s0, s0_src, s0_dof = _blank_sd(np.asarray(x, float),
                                       np.asarray(y, float))
    lod_blank = loq_blank = None
    if s0 is not None and abs(b) > 0:
        lod_blank = k_lod * float(s0) / abs(b)
        loq_blank = k_loq * float(s0) / abs(b)

    lr = _trim_linear_range(np.asarray(x, float), np.asarray(y, float),
                            calibrate)

    xa = np.asarray(x, float)
    xa = xa[np.isfinite(xa)]
    lowest_std = float(np.min(xa)) if xa.size else None
    if lod is not None and lowest_std is not None and lod > lowest_std:
        warnings.append(
            f'LOD（{_fmt_num(lod)}）**高于**最低标准点（{_fmt_num(lowest_std)}）：'
            '说明这条标定曲线在最低点附近的噪声已大于 3 倍标准差，'
            '真实检出限其实落在标准曲线覆盖范围之外——要么降低标准点浓度，'
            '要么增加重复测量次数，不能直接引用这个 LOD 号码。')

    return {
        'lod': None if lod is None else float(lod),
        'loq': None if loq is None else float(loq),
        'lod_conc': None if lod is None else float(lod),
        'loq_conc': None if loq is None else float(loq),
        'k_lod': float(k_lod), 'k_loq': float(k_loq),
        's_yx': None if s is None else float(s),
        'slope': float(b) if b is not None else None,
        'blank_sd': None if s0 is None else float(s0),
        'blank_sd_source': s0_src,
        'blank_sd_dof': s0_dof,
        'lod_from_blank': lod_blank,
        'loq_from_blank': loq_blank,
        'linear_range': lr,
        'calibration': calibrate,
        'warnings': warnings,
        'ok': bool(ok),
    }


# ======================== 4. Stern–Volmer ========================

def _aic(rss, n, k_params):
    """AIC = n·ln(RSS/n) + 2(k+1)（k+1 把残差方差也算作一个参数）。"""
    if rss <= 0:
        rss = 1e-300          # RSS=0（完美拟合）时取一个极小值，避免 log(0)
    return float(n * np.log(rss / n) + 2.0 * (k_params + 1))


def _aicc(rss, n, k_params):
    """小样本校正 AIC：AICc = AIC + 2k(k+1)/(n−k−1)；n 太小返回 None。"""
    k = k_params + 1
    if n - k - 1 <= 0:
        return None
    return float(_aic(rss, n, k_params) + 2.0 * k * (k + 1) / (n - k - 1))


def _fit_poly(x, y, deg):
    """最小二乘多项式拟合，返回 ``(coef 低次在前, residuals, rss)``。"""
    coef_hi = np.polyfit(x, y, deg)          # numpy 给的是高次在前
    coef = coef_hi[::-1]                     # 转成低次在前：c0 + c1 x + c2 x²
    resid = y - np.polyval(coef_hi, x)
    return coef, resid, float((resid ** 2).sum())


def _f_test_nested(rss_reduced, df_reduced, rss_full, df_full):
    """嵌套模型 F 检验（reduced 是 full 的特例）：``(F, p, df1, df2)``。"""
    df1 = df_reduced - df_full
    df2 = df_full
    if df1 <= 0 or df2 <= 0:
        return None, None, df1, df2
    if rss_full <= 0:
        return float('inf'), 0.0, df1, df2
    f_val = ((rss_reduced - rss_full) / df1) / (rss_full / df2)
    if f_val < 0:                    # 数值噪声：full 反而更差，按 0 处理
        f_val = 0.0
    return float(f_val), float(stats.f.sf(f_val, df1, df2)), df1, df2


def stern_volmer(x, y, model='linear', i0=None, nan_policy='drop',
                 alpha=0.05):
    """Stern–Volmer 分析：``I0/I = 1 + Ksv·[Q]``，并做一阶/二阶模型比较。

    参数
    ----
    x : array-like            猝灭剂浓度 ``[Q]``
    y : array-like            已算好的 ``I0/I``；或原始强度 ``I``（此时须给 ``i0``）
    model : {'linear', 'quadratic'}
        ``linear``：``I0/I = 1 + Ksv[Q]``
        ``quadratic``：``I0/I = 1 + K1[Q] + K2[Q]²``（动态+静态混合猝灭，
        或存在表观静态项时上翘）
        **两个模型总是一起拟合**——"哪个更合适"只能靠比较回答，
        只报一个模型的 R² 是判断不了的。
    i0 : float | None         不给 ``[Q]=0`` 的 I0 时：``y`` 传原始强度、这里传 I0
    alpha : float             F 检验显著性水平

    返回
    ----
    dict：

    ``ksv``                一阶（自由截距）拟合的斜率
    ``ksv_through_origin`` ``y−1`` 过原点拟合的 Ksv（强制截距=1，SV 的标准写法）
    ``intercept_linear``   一阶拟合截距（理论上应为 1）
    ``intercept_p_value``  检验"截距 = 1"的 p 值；显著说明有静态猝灭或 I0 取值不当
    ``k1`` / ``k2``        二阶模型的 K1 / K2
    ``r2`` / ``r2_linear`` / ``r2_quadratic``
    ``comparison``         模型比较（F 检验 + AICc + ``preferred`` + 中文 ``verdict``）
    ``n`` / ``x`` / ``y`` / ``fitted_*`` / ``residuals_*``
    ``ok`` / ``warnings``
    """
    if model not in ('linear', 'quadratic'):
        raise CalibrationError(
            f"model 只能是 'linear' 或 'quadratic'，收到 {model!r}")
    x = _as_float_array(x, 'x')
    y = _as_float_array(y, 'y')
    if x.size != y.size:
        raise CalibrationError(f'x 与 y 长度不一致（{x.size} vs {y.size}）')

    warnings = []
    if i0 is not None:
        i0v = float(i0)
        if not np.isfinite(i0v) or i0v <= 0:
            raise CalibrationError(f'i0 必须是有限正数，收到 {i0!r}')
        fin = np.isfinite(y)
        if np.any(fin) and np.any(y[fin] <= 0):
            raise CalibrationError(
                'y 传原始强度时每个值都必须是正的有限数（I0/I 要除以它）')
        y = np.where(fin, i0v / np.where(fin, y, 1.0), np.nan)
    else:
        fin = np.isfinite(y)
        if np.any(fin) and np.any(y[fin] <= 0):
            warnings.append('y 里有 ≤0 的值；I0/I 按定义应为正数，'
                            '请确认传的确实是 I0/I')

    x, y, _keep, dropped = _finite_filter(x, y, nan_policy=nan_policy)
    n = x.size
    if n < 2:
        raise CalibrationError(
            f'有效点只有 {n} 个（丢弃 {dropped["n_dropped"]} 个），'
            '做不了 Stern–Volmer 拟合')

    # ---- 一阶模型 ----
    coef1, resid1, rss1 = _fit_poly(x, y, 1)
    a1, b1 = float(coef1[0]), float(coef1[1])
    tss = float(((y - y.mean()) ** 2).sum())
    r2_1 = (1.0 - rss1 / tss) if tss > 0 else None

    # 强制截距 = 1（过 (0,1)）：min Σ(y−1−Kx)² → K = Σx(y−1)/Σx²
    denom = float((x * x).sum())
    ksv_origin = (float((x * (y - 1.0)).sum() / denom)
                  if denom > 0 else None)

    # "截距 = 1" 检验
    intercept_p = None
    if n > 2:
        cal1 = linear_calibration(x, y, nan_policy='drop')
        if cal1['intercept_se'] not in (None, 0):
            t_int = (cal1['intercept'] - 1.0) / cal1['intercept_se']
            intercept_p = float(2.0 * stats.t.sf(abs(t_int), cal1['dof']))

    # ---- 二阶模型 ----
    # c0 是二次拟合的自由截距（理论上应接近 1，但不强制为 1）——下面画曲线、
    # 算 fitted 都必须用它，不能写死 1.0，否则 fitted 与 residuals 对不上
    # （residuals 来自 numpy.polyfit 的残差，fitted 却按截距=1 重算）。
    c0 = k1 = k2 = None
    resid2 = rss2 = r2_2 = None
    if n >= 3:
        coef2, resid2, rss2 = _fit_poly(x, y, 2)
        c0, k1, k2 = float(coef2[0]), float(coef2[1]), float(coef2[2])
        r2_2 = (1.0 - rss2 / tss) if tss > 0 else None
    else:
        warnings.append(f'只有 {n} 个点，二阶模型至少需要 3 个点，'
                        '本次只给线性结果（不做模型比较）')

    # ---- 模型比较：F 检验 + AICc，两个判据都要看 ----
    comparison = {'available': False, 'preferred': 'linear',
                  'verdict': '点数不足，无法比较一阶与二阶模型'}
    if n >= 4 and rss2 is not None:
        f_val, p_val, dfn, dfd = _f_test_nested(rss1, n - 2, rss2, n - 3)
        aic1, aic2 = _aic(rss1, n, 2), _aic(rss2, n, 3)
        aicc1, aicc2 = _aicc(rss1, n, 2), _aicc(rss2, n, 3)
        delta = ((aicc2 - aicc1) if (aicc1 is not None and aicc2 is not None)
                 else (aic2 - aic1))
        f_sig = (p_val is not None and p_val < alpha)
        aic_quad = (delta is not None and delta < -2.0)
        aic_lin = (delta is not None and delta > 2.0)
        if f_sig and aic_quad:
            preferred = 'quadratic'
            verdict = (f'二阶模型更合适：F={f_val:.2f}，p={p_val:.3g} < {alpha:g}，'
                       f'且 AICc 比一阶低 {abs(delta):.2f}。'
                       '说明 I0/I 随 [Q] 上翘（静态猝灭并存或存在表观静态项），'
                       '只用 Ksv 描述会低估高浓度端的猝灭。')
        elif (not f_sig) and aic_lin:
            preferred = 'linear'
            verdict = (f'一阶（线性）模型就够了：F={f_val:.2f}，'
                       f'p={p_val:.3g} ≥ {alpha:g}，'
                       f'且 AICc 比二阶低 {abs(delta):.2f}。'
                       '加一个 K2 并没有真正改善拟合，按简约原则报 Ksv。')
        elif not f_sig:
            preferred = 'linear'
            verdict = (f'两个判据不完全一致：F 检验不显著（p={p_val:.3g}），'
                       f'但 AICc 略偏二阶（Δ={_fmt_num(delta)}）。'
                       '倾向一阶（简约原则），建议补做高浓度点确认。')
        else:
            preferred = 'quadratic'
            verdict = (f'两个判据不完全一致：F 检验显著（p={p_val:.3g}），'
                       f'但 AICc 差值 {_fmt_num(delta)} 未达 −2。'
                       '倾向二阶，建议补点确认。')
        comparison = {
            'available': True, 'preferred': preferred,
            'f': f_val, 'p': p_val, 'df1': dfn, 'df2': dfd,
            'alpha': float(alpha),
            'aic_linear': aic1, 'aic_quadratic': aic2,
            'aicc_linear': aicc1, 'aicc_quadratic': aicc2,
            'delta_aicc': delta,
            'rss_linear': rss1, 'rss_quadratic': rss2,
            'r2_linear': r2_1, 'r2_quadratic': r2_2,
            'verdict': verdict,
        }
    elif n == 3:
        warnings.append('只有 3 个点：二次曲线必过三点（残差恒为 0），'
                        'R² 与 F 检验都失去意义，只能报参数不能选模型')

    if model == 'quadratic' and k2 is None:
        raise CalibrationError(
            f'选了二次模型但只有 {n} 个点，二次拟合至少要 3 个点')

    if model == 'quadratic':
        fitted_main = c0 + k1 * x + k2 * x ** 2
        resid_main = resid2
        r2_main = r2_2
    else:
        fitted_main = a1 + b1 * x
        resid_main = resid1
        r2_main = r2_1

    return {
        'model': model,
        'ksv': b1,
        'ksv_through_origin': ksv_origin,
        'intercept_linear': a1,
        'intercept_p_value': intercept_p,
        'intercept_quadratic': c0,
        'k1': k1, 'k2': k2,
        'r2': r2_main,
        'r2_linear': r2_1, 'r2_quadratic': r2_2,
        'rss_linear': rss1, 'rss_quadratic': rss2,
        'fitted_linear': a1 + b1 * x,
        'residuals_linear': resid1,
        'fitted_quadratic': (None if resid2 is None else (y - resid2)),
        'residuals_quadratic': resid2,
        'fitted': fitted_main, 'residuals': resid_main,
        'comparison': comparison,
        'n': int(n), 'n_input': int(x.size),
        'n_dropped': int(dropped['n_dropped']),
        'x': x, 'y': y,
        'ok': True, 'warnings': warnings,
    }


# ======================== 5. 画图 ========================

def _put_text_box(ax, text, loc='upper left', fontsize=9):
    """把一个多行文本块放到图的角落（半透明白底，避免压住数据看不清）。

    **不指定 family**：标注里混着中文（如「线性范围」「无法估计」），必须让
    ``setup_chinese_font()`` 设好的 ``font.sans-serif`` 生效；写死 'DejaVu Sans'
    会让中文全部变成方框（DejaVu 没有 CJK 字形）。
    """
    ha = 'right' if 'right' in loc else 'left'
    va = 'bottom' if 'lower' in loc else 'top'
    ax.text(0.028 if ha == 'left' else 0.972,
            0.97 if va == 'top' else 0.03, text, transform=ax.transAxes,
            ha=ha, va=va, fontsize=fontsize, linespacing=1.55,
            bbox=dict(boxstyle='round,pad=0.45', facecolor='white',
                      edgecolor='#cbd5e1', alpha=0.92))


def _annotate_fit(ax, calib, lod=None, extra_lines=None, fontsize=9):
    """把"斜率 ± SE / 截距 ± SE / R² / n / s_yx / LOD / LOQ"写进图的角落。"""
    lines = [f"b = {_fmt_pm(calib['slope'], calib['slope_se'])}",
             f"a = {_fmt_pm(calib['intercept'], calib['intercept_se'])}"]
    if calib.get('r2') is not None:
        adj = calib.get('adj_r2')
        lines.append(f"R² = {calib['r2']:.5f}"
                     + (f"  (adj {adj:.5f})" if adj is not None else ''))
    else:
        lines.append('R² = —（y 全同，无定义）')
    lines.append(f"s_yx = {_fmt_num(calib.get('s_yx'))}   n = {calib['n']}")
    if lod:
        if lod.get('lod') is not None:
            lines.append(f"LOD = {_fmt_num(lod['lod'])}"
                         f"   LOQ = {_fmt_num(lod['loq'])}"
                         f"（k={lod['k_lod']:g}/{lod['k_loq']:g}）")
        else:
            lines.append('LOD / LOQ = —（无法估计）')
    if extra_lines:
        lines.extend(extra_lines)
    _put_text_box(ax, '\n'.join(lines), loc='upper left', fontsize=fontsize)


def plot_calibration(x, y, x_label='x', y_label='y', title=None,
                     exclude_mask=None, exclude_labels=None,
                     weights=None, lod=None, calib=None,
                     outlier_sigma=DEFAULT_OUTLIER_SIGMA,
                     show_bands=True, show_lod=True, annotate=True,
                     figsize=(7.6, 8.6), dpi=None, save_path=None,
                     verbose=True):
    """画标定图（数据点 + 拟合线 + 95% 带 + LOD/LOQ 标线）+ 残差图。

    参数
    ----
    x, y : array-like          全部候选点（含要被剔除的点）
    exclude_mask : array-like[bool] | None
        True = 该点**不参与回归**（图上画成灰色空心叉，仍显示出来，
        并标注"已剔除"）。这样图既诚实又好看：看得到被扔掉的是什么。
    exclude_labels : list[str] | None   与 ``y`` 等长的样品名
    lod : dict | None          :func:`lod_loq` 的结果；给了才画 LOD/LOQ 竖线
    calib : dict | None        已算好的回归结果（在**参与回归的点**上算的）
    outlier_sigma : float      标准化残差超它就用红圈标出（只提示，不剔除）
    show_bands : bool          画 95% 置信带（拟合线本身多准）与 95% 预测带
                               （再测一个点会落在哪）——两件事，都画
    dpi : int | float | None   保存 DPI；``None`` 回落 ``EXPORT_DPI_DEFAULT``

    返回 ``(fig, summary)``，``summary`` 含 ``calib`` / ``levels`` /
    ``n_excluded`` / ``outliers``。
    """
    x = _as_float_array(x, 'x')
    y = _as_float_array(y, 'y')
    if x.size != y.size:
        raise CalibrationError(f'x 与 y 长度不一致（{x.size} vs {y.size}）')
    n_all = x.size

    if exclude_mask is None:
        excl = np.zeros(n_all, bool)
    else:
        excl = np.asarray(exclude_mask, bool).ravel()
        if excl.size != n_all:
            raise CalibrationError(
                f'exclude_mask 长度（{excl.size}）与 x（{n_all}）不一致')
    excl = excl | ~(np.isfinite(x) & np.isfinite(y))

    # 样品名列表统一转成 ndarray，才能用布尔掩码挑"参与回归的那几个"
    if exclude_labels is None:
        labels_arr = np.array([f'点{i + 1}' for i in range(n_all)], dtype=object)
    else:
        labels_arr = np.asarray(list(exclude_labels), dtype=object).ravel()
        if labels_arr.size != n_all:
            labels_arr = np.array([f'点{i + 1}' for i in range(n_all)],
                                  dtype=object)

    xk, yk = x[~excl], y[~excl]
    # weights 是按**全部候选点**给的，剔除点后要同步挑出参与回归的那几个，
    # 否则长度对不上会直接报错（或更糟：把权重错配到别的点上）。
    wk = None
    if weights is not None:
        w_all = _as_float_array(weights, 'weights')
        if w_all.size != n_all:
            raise CalibrationError(
                f'weights 长度（{w_all.size}）与 x（{n_all}）不一致')
        wk = w_all[~excl]
    if calib is None:
        calib = linear_calibration(xk, yk, weights=wk, nan_policy='drop')

    fig = plt.figure(figsize=figsize, dpi=150)
    gs = fig.add_gridspec(2, 1, height_ratios=[2.35, 1.0], hspace=0.28,
                          left=0.13, right=0.97, top=0.93, bottom=0.075)
    ax = fig.add_subplot(gs[0])
    axr = fig.add_subplot(gs[1])

    levels = aggregate_replicates(xk, yk)
    has_rep = any(lv['n'] > 1 for lv in levels)

    # ---------- 上面：标定图 ----------
    xlo, xhi = float(np.min(x)), float(np.max(x))
    if xhi <= xlo:
        raise CalibrationError('所有 x 相同，画不出标定图')
    pad = 0.06 * (xhi - xlo)
    # LOD / LOQ 若落在数据范围外，把横轴延长到能看见标线为止
    if show_lod and lod:
        for key in ('loq', 'lod'):
            v = lod.get(key)
            if v is None or not np.isfinite(v) or v <= 0:
                continue
            if v < xlo - pad:
                xlo = min(xlo, float(v) - 0.25 * pad)
            if v > xhi + pad:
                xhi = max(xhi, float(v) + 0.25 * pad)
    x_dense = np.linspace(xlo - pad, xhi + pad, 400)
    b, a = calib['slope'], calib['intercept']

    if show_bands and calib.get('s_yx') is not None and calib.get('dof', 0) > 0:
        pi = predict_interval(calib, x_dense, level=calib.get('ci_level',
                                                              CI_LEVEL))
        ax.fill_between(x_dense, pi['pred_lo'], pi['pred_hi'],
                        color='#93c5fd', alpha=0.22, linewidth=0,
                        label='95% 预测带（单次测量）', zorder=1)
        ax.fill_between(x_dense, pi['mean_lo'], pi['mean_hi'],
                        color='#2563eb', alpha=0.24, linewidth=0,
                        label='95% 置信带（拟合线）', zorder=2)

    ax.plot(x_dense, a + b * x_dense, color='#1d4ed8', linewidth=1.9,
            zorder=4, label='最小二乘拟合')

    # 参与拟合的点：有重复时画"均值 ± SD"误差棒 + 原始点淡色叠加
    if has_rep:
        lx = [lv['x'] for lv in levels]
        ly = [lv['mean'] for lv in levels]
        le = [lv['sd'] if lv['sd'] is not None else 0.0 for lv in levels]
        ax.errorbar(lx, ly, yerr=le, fmt='none', ecolor='#0f172a',
                    elinewidth=1.2, capsize=4, capthick=1.2, zorder=5,
                    label=f'均值 ± 标准差（{len(levels)} 个浓度）')
        ax.plot(lx, ly, 'o', color='#0f172a', markersize=5.6, zorder=6,
                label='浓度点均值')
        ax.plot(_jitter(xk, xhi - xlo), yk, 'o', markersize=4.2,
                color='#64748b', alpha=0.62, markeredgewidth=0, zorder=5,
                label=f'原始测量（{xk.size} 条谱）')
    else:
        ax.plot(xk, yk, 'o', markersize=5.6, color='#0f172a', zorder=6,
                label=f'数据点（{xk.size} 个）')

    # 被剔除的点：灰色空心叉，图上看得到但很轻
    if excl.any():
        ax.plot(x[excl], y[excl], 'x', markersize=6.6, mew=1.5,
                color='#94a3b8', alpha=0.9, zorder=3,
                label=f'已剔除（{int(excl.sum())} 个，不参与回归）')

    # 离群提示：参与拟合的点里 |标准化残差| > sigma
    outliers = []
    s = calib.get('s_yx')
    if s not in (None, 0):
        kept_labels = labels_arr[~excl]
        for i, sr in enumerate(calib['residuals'] / s):
            if abs(sr) > outlier_sigma:
                outliers.append({
                    'i': int(i),
                    'x': float(calib['x'][i]), 'y': float(calib['y'][i]),
                    'std_resid': float(sr),
                    'label': (str(kept_labels[i])
                              if i < kept_labels.size else '')})
        if outliers:
            ax.plot([o['x'] for o in outliers], [o['y'] for o in outliers],
                    'o', markersize=12, markerfacecolor='none',
                    markeredgecolor='#dc2626', markeredgewidth=1.4, zorder=7)

    # LOD / LOQ 竖线
    if show_lod and lod:
        for key, color, text in (('lod', '#dc2626', 'LOD'),
                                 ('loq', '#d97706', 'LOQ')):
            v = lod.get(key)
            if v is None or not np.isfinite(v) or v <= 0:
                continue
            ax.axvline(v, color=color, linestyle='--', linewidth=1.25,
                       alpha=0.9, zorder=3)
            if x_dense[0] <= v <= x_dense[-1]:
                ax.annotate(f'{text} = {_fmt_num(v)}',
                            xy=(v, 0.965), xycoords=('data', 'axes fraction'),
                            xytext=(4 if key == 'lod' else -4, 0),
                            textcoords='offset points',
                            ha='left' if key == 'lod' else 'right',
                            va='top', fontsize=8.5, color=color,
                            bbox=dict(boxstyle='round,pad=0.22',
                                      facecolor='white', edgecolor=color,
                                      alpha=0.85, linewidth=0.8))
            else:
                ax.annotate(f'{text} = {_fmt_num(v)}（在图外）',
                            xy=(0.985, 0.55 if key == 'lod' else 0.43),
                            xycoords='axes fraction', ha='right', va='center',
                            fontsize=8.5, color=color)

    ax.set_xlabel(x_label)
    ax.set_ylabel(y_label)
    ax.set_title(title or f'标定曲线：{y_label} – {x_label}', fontsize=12.5)
    ax.grid(True, linestyle='--', alpha=0.3)
    ax.set_xlim(x_dense[0], x_dense[-1])
    if annotate:
        extra = []
        lr = (lod or {}).get('linear_range')
        if lr:
            extra.append(f"线性范围：{_fmt_num(lr.get('x_min'))} – "
                         f"{_fmt_num(lr.get('x_max'))}"
                         + ('（已收缩）' if lr.get('dropped_levels') else ''))
        _annotate_fit(ax, calib, lod=lod, extra_lines=extra)
    ax.legend(fontsize=8, frameon=False, loc='lower right')

    # 纵轴量级到 1e5 时用科学刻度，避免 6 位数 tick 读错位（同 plot_compare）
    try:
        ys = np.abs(y[np.isfinite(y)])
        if ys.size and ys.max() >= 1e5:
            from matplotlib.ticker import ScalarFormatter
            fmt = ScalarFormatter(useMathText=True)
            fmt.set_powerlimits((-3, 4))
            ax.yaxis.set_major_formatter(fmt)
            ax.yaxis.get_offset_text().set_fontsize(9)
    except Exception:
        pass

    # ---------- 下面：残差图 ----------
    rx, ry = calib['x'], calib['residuals']
    axr.axhline(0.0, color='#334155', linewidth=1.1, zorder=2)
    axr.plot(_jitter(rx, xhi - xlo), ry, 'o', markersize=4.8,
             color='#0f172a', markerfacecolor='#ffffff', markeredgewidth=1.2,
             zorder=3, label='残差')
    if s not in (None, 0):
        axr.axhspan(-2 * s, 2 * s, color='#22c55e', alpha=0.10, linewidth=0,
                    zorder=1, label='±2 s_yx')
        for sign in (1, -1):
            axr.axhline(sign * 2 * s, color='#16a34a', linestyle=':',
                        linewidth=1.0, zorder=2)
        if outliers:
            axr.plot([o['x'] for o in outliers],
                     [o['std_resid'] * s for o in outliers], 'o',
                     markersize=11, markerfacecolor='none',
                     markeredgecolor='#dc2626', markeredgewidth=1.3, zorder=4)
        ylim = max(float(np.max(np.abs(ry))), 2.4 * s) * 1.22
        axr.set_ylim(-ylim, ylim)
    axr.set_xlabel(x_label)
    axr.set_ylabel('残差')
    axr.set_title('残差图（该是随机散布；出现趋势说明直线不够）', fontsize=10.5)
    axr.grid(True, linestyle='--', alpha=0.3)
    axr.set_xlim(ax.get_xlim())
    axr.legend(fontsize=8, frameon=False, loc='lower right')

    fig.align_ylabels([ax, axr])

    summary = {
        'calib': calib, 'lod': lod, 'levels': levels,
        'n_points': int(n_all), 'n_fit': int((~excl).sum()),
        'n_excluded': int(excl.sum()), 'outliers': outliers,
        'has_replicates': has_rep,
    }
    if save_path is not None:
        summary['figure'] = str(save_figure(fig, save_path, dpi=dpi))
    if verbose:
        _safe_print(f'  [OK] 标定图：{summary["n_fit"]} 点拟合，'
                    f'{summary["n_excluded"]} 点剔除'
                    + (f' → {summary["figure"]}' if save_path else ''))
    return fig, summary


def _jitter(xs, span, frac=0.012):
    """同一 x 上的重复点在横轴方向轻微散开，避免完全重叠看不出重复次数。

    偏移量在 ``±frac·span`` 内按重复序号均分——**只影响显示**，不参与任何计算。
    """
    xs = np.asarray(xs, float)
    if span <= 0 or not xs.size:
        return xs
    out = xs.copy()
    groups = {}
    for i, v in enumerate(xs):
        groups.setdefault(float(v), []).append(i)
    w = frac * span
    for v, idxs in groups.items():
        m = len(idxs)
        if m < 2:
            continue
        for k, i in enumerate(idxs):
            out[i] = v + np.linspace(-w, w, m)[k]
    return out


def plot_stern_volmer(sv, x_label='[Q]', y_label='I$_0$/I', title=None,
                      annotate=True, figsize=(7.6, 7.4), dpi=None,
                      save_path=None, verbose=True):
    """画 Stern–Volmer 图：上=数据 + 一阶/二阶拟合，下=两模型的残差对比。

    ``sv`` 必须是 :func:`stern_volmer` 的返回值——两个模型的结果都在里面，
    所以能同时画出来比较，这正是"不能只说都拟合了"的落点。
    """
    if not isinstance(sv, dict) or 'x' not in sv:
        raise CalibrationError('plot_stern_volmer 需要 stern_volmer() 的返回字典')
    x, y = sv['x'], sv['y']
    fig = plt.figure(figsize=figsize, dpi=150)
    gs = fig.add_gridspec(2, 1, height_ratios=[2.3, 1.0], hspace=0.30,
                          left=0.13, right=0.97, top=0.93, bottom=0.085)
    ax = fig.add_subplot(gs[0])
    axr = fig.add_subplot(gs[1])

    xlo, xhi = float(np.min(x)), float(np.max(x))
    pad = 0.06 * (xhi - xlo) if xhi > xlo else 0.1
    xd = np.linspace(xlo - pad, xhi + pad, 300)

    ax.plot(x, y, 'o', markersize=6.2, color='#0f172a', zorder=6,
            label=f'数据（{len(x)} 个）')
    pref = (sv.get('comparison') or {}).get('preferred', 'linear')
    ax.axhline(1.0, color='#94a3b8', linestyle=':', linewidth=1.0, zorder=1)
    ax.plot(xd, sv['intercept_linear'] + sv['ksv'] * xd, '-',
            color='#1d4ed8', linewidth=1.9, zorder=4,
            label=f"一阶：Ksv = {_fmt_num(sv['ksv'])}"
                  + ('  ←采用' if pref == 'linear' else ''))
    if sv.get('k2') is not None:
        # 用二次拟合自己的自由截距（sv['intercept_quadratic']），不要写死 1.0：
        # 写死会让曲线与 residuals_quadratic 不是同一条模型。
        c0 = sv.get('intercept_quadratic')
        if c0 is None:
            c0 = 1.0
        ax.plot(xd, c0 + sv['k1'] * xd + sv['k2'] * xd ** 2, '--',
                color='#dc2626', linewidth=1.8, zorder=5,
                label=f"二阶：K1 = {_fmt_num(sv['k1'])}，"
                      f"K2 = {_fmt_num(sv['k2'])}"
                      + ('  ←采用' if pref == 'quadratic' else ''))

    if annotate:
        cmp_ = sv.get('comparison') or {}
        lines = []
        r2l, r2q = sv.get('r2_linear'), sv.get('r2_quadratic')
        lines.append('一阶 R² = ' + (f'{r2l:.5f}' if r2l is not None else '—'))
        if r2q is not None:
            lines.append(f'二阶 R² = {r2q:.5f}')
        if cmp_.get('available'):
            lines.append(f"F = {_fmt_num(cmp_.get('f'))}，"
                         f"p = {_fmt_num(cmp_.get('p'))}")
            d = cmp_.get('delta_aicc')
            lines.append('ΔAICc(二阶−一阶) = '
                         + (f'{d:+.2f}' if d is not None else '—'))
            lines.append(f"判据倾向：{'二阶' if pref == 'quadratic' else '一阶'}")
        else:
            lines.append(cmp_.get('verdict', '无法比较模型'))
        _put_text_box(ax, '\n'.join(lines), loc='upper left', fontsize=8.8)

    ax.set_xlabel(x_label)
    ax.set_ylabel(y_label)
    ax.set_title(title or 'Stern–Volmer 分析（一阶 vs 二阶）', fontsize=12.5)
    ax.grid(True, linestyle='--', alpha=0.3)
    ax.legend(fontsize=8, frameon=False, loc='lower right')

    axr.axhline(0.0, color='#334155', linewidth=1.1, zorder=2)
    axr.plot(x, sv['residuals_linear'], 'o', markersize=5, color='#1d4ed8',
             markerfacecolor='white', markeredgewidth=1.2, zorder=3,
             label='一阶残差')
    if sv.get('residuals_quadratic') is not None:
        axr.plot(x, sv['residuals_quadratic'], 's', markersize=4.6,
                 color='#dc2626', markerfacecolor='white',
                 markeredgewidth=1.1, zorder=3, label='二阶残差')
    axr.set_xlabel(x_label)
    axr.set_ylabel('残差')
    axr.set_title('两模型残差对比（残差里还剩趋势 = 模型没抓全）', fontsize=10.5)
    axr.grid(True, linestyle='--', alpha=0.3)
    axr.legend(fontsize=8, frameon=False, loc='best')

    fig.align_ylabels([ax, axr])

    summary = {'sv': sv, 'preferred': pref}
    if save_path is not None:
        summary['figure'] = str(save_figure(fig, save_path, dpi=dpi))
    if verbose:
        _safe_print('  [OK] Stern–Volmer 图'
                    + (f' → {summary["figure"]}' if save_path else ''))
    return fig, summary


def save_figure(fig, path, dpi=None):
    """保存图片（自动建目录）；``dpi=None`` 回落 ``EXPORT_DPI_DEFAULT``。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=EXPORT_DPI_DEFAULT if dpi is None else dpi,
                bbox_inches='tight')
    return path


# ======================== 6. 出表（CSV / JSON） ========================

def _cell(v):
    """CSV 单元格：None → 空串；浮点按 10 位有效数字；bool → 是/否。"""
    if v is None:
        return ''
    if isinstance(v, (bool, np.bool_)):
        return '是' if v else '否'
    if isinstance(v, (int, np.integer)):
        return str(int(v))
    if isinstance(v, (float, np.floating)):
        fv = float(v)
        return '' if not np.isfinite(fv) else f'{fv:.10g}'
    return str(v)


def _json_safe(obj, _depth=0):
    """递归把 numpy 类型转成可 JSON 序列化的值（nan/inf → None）。"""
    if _depth > 12:
        return str(obj)
    if isinstance(obj, dict):
        return {str(k): _json_safe(v, _depth + 1) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v, _depth + 1) for v in obj]
    if isinstance(obj, np.ndarray):
        return [_json_safe(t, _depth + 1) for t in obj.tolist()]
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, (np.floating, float)):
        fv = float(obj)
        return fv if np.isfinite(fv) else None
    if isinstance(obj, np.integer):
        return int(obj)
    return obj


def _now_iso():
    """当前本地时间 ISO 串（秒精度），写进 JSON 的 meta。"""
    return datetime.datetime.now().replace(microsecond=0).isoformat()


def calibration_to_csv(x, y, path, x_name='x', y_name='y',
                       exclude_mask=None, labels=None, numbers=None,
                       reasons=None, levels=None):
    """把逐点标定数据写成 CSV（UTF-8 BOM，Excel 直接打开中文不乱码）。

    列：``样品, 编号, <x>, <y>, 参与回归, 剔除原因``；末尾附逐浓度汇总表。
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    x = _as_float_array(x, 'x')
    y = _as_float_array(y, 'y')
    n = x.size
    excl = (np.zeros(n, bool) if exclude_mask is None
            else np.asarray(exclude_mask, bool).ravel())
    labels = list(labels) if labels is not None else [f'点{i + 1}' for i in range(n)]
    numbers = list(numbers) if numbers is not None else [''] * n
    reasons = list(reasons) if reasons is not None else [
        ('不参与回归' if e else '') for e in excl]
    level_of = {}
    for lv in (levels or []):
        level_of[round(float(lv['x']), 10)] = lv
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['样品', '编号', x_name, y_name, '参与回归', '剔除原因',
                    '所属浓度均值'])
        for i in range(n):
            lv = level_of.get(round(float(x[i]), 10))
            w.writerow([labels[i] if i < len(labels) else '',
                        numbers[i] if i < len(numbers) else '',
                        f'{x[i]:.10g}', f'{y[i]:.10g}',
                        '否' if excl[i] else '是',
                        reasons[i] if i < len(reasons) else '',
                        '' if lv is None else f"{lv['mean']:.10g}"])
        if levels:
            w.writerow([])
            w.writerow([f'== 逐浓度汇总（x = {x_name}）=='])
            w.writerow([x_name, '重复数', '均值', '标准差', '标准误'])
            for lv in levels:
                w.writerow([f"{lv['x']:.10g}", lv['n'], f"{lv['mean']:.10g}",
                            _cell(lv['sd']), _cell(lv['sem'])])
    return path


def fit_to_csv(calib, lod, path, x_name='x', y_name='y', extra_rows=None):
    """把回归 / 检出限统计量写成四列 CSV（``项目, 值, 标准误, 说明``）。

    竖排而不是横排：Excel 里一眼读完，也方便直接粘进实验报告。
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    sc = calib.get('slope_ci') or (None, None)
    ic = calib.get('intercept_ci') or (None, None)
    rows = [
        ('x 变量', x_name, '', '横轴（浓度等）'),
        ('y 变量', y_name, '', '纵轴（峰强度 / 峰面积 / I0/I…）'),
        ('参与拟合点数 n', calib.get('n'), '', ''),
        ('丢弃/剔除点数', calib.get('n_dropped'), '', '含 NaN'),
        ('斜率 b', calib.get('slope'), calib.get('slope_se'), ''),
        ('截距 a', calib.get('intercept'), calib.get('intercept_se'), ''),
        ('回归标准误 s_yx', calib.get('s_yx'), '',
         'sqrt(RSS/(n-2))，LOD 公式用的就是它'),
        ('RMSE', calib.get('rmse'), '', 'sqrt(RSS/n)，未做自由度修正'),
        ('R²', calib.get('r2'), '', ''),
        ('校正 R²', calib.get('adj_r2'), '', ''),
        ('自由度', calib.get('dof'), '', 'n-2'),
        ('斜率 95% CI 下限', sc[0], '', ''),
        ('斜率 95% CI 上限', sc[1], '', ''),
        ('截距 95% CI 下限', ic[0], '', ''),
        ('截距 95% CI 上限', ic[1], '', ''),
    ]
    if lod:
        rows += [
            (f"LOD（k={lod.get('k_lod', 3.0):g}）", lod.get('lod'), '',
             'k·s_yx/|b|，单位同 x'),
            (f"LOQ（k={lod.get('k_loq', 10.0):g}）", lod.get('loq'), '',
             'k·s_yx/|b|，单位同 x'),
            ('空白标准差 s0', lod.get('blank_sd'), '',
             lod.get('blank_sd_source', '')),
            ('LOD（用 s0）', lod.get('lod_from_blank'), '',
             '以空白标准差代替 s_yx'),
            ('LOQ（用 s0）', lod.get('loq_from_blank'), '',
             '以空白标准差代替 s_yx'),
        ]
        lr = lod.get('linear_range') or {}
        rows += [
            ('线性范围下限', lr.get('x_min'), '', ''),
            ('线性范围上限', lr.get('x_max'), '', ''),
            ('线性范围保留浓度数', lr.get('n_levels'), '', ''),
            ('线性范围剔除层级数', len(lr.get('dropped_levels') or []), '',
             lr.get('reason', '')),
        ]
    if extra_rows:
        rows.extend(extra_rows)
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['项目', '值', '标准误', '说明'])
        for name, val, se, note in rows:
            w.writerow([name, _cell(val), _cell(se), note])
    return path


def result_to_json(result, path, meta=None):
    """把结果 dict 写成 JSON（``ensure_ascii=False``，numpy 类型已转换）。

    带 ``meta``（版本 / 导出时间 / 参数快照），这样"这张图是哪个版本、用什么
    参数导出的"以后能回答——与项目 gui_provenance 的口径一致。
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(result)
    if meta is not None:
        payload['meta'] = dict(meta)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(_json_safe(payload), f, ensure_ascii=False, indent=2)
    return path


# ======================== 7. 纯文本报告 ========================

def format_calibration_report(calib, lod=None, x_name='x', y_name='y',
                              levels=None, title=None):
    """把标定结果排成给人看的中文纯文本（终端 / 信息页 / 报告附录都可用）。"""
    lines = []
    if title:
        lines.append(title)
        lines.append('=' * max(len(title), 12))
    lines.append(f'横轴：{x_name}　　纵轴：{y_name}')
    lines.append(f"参与拟合：{calib['n']} 个测量点"
                 + (f"（含 {calib['n_dropped']} 个非有限值已丢弃）"
                    if calib.get('n_dropped') else ''))
    lines.append('')
    lines.append(f"  斜率 b    = {_fmt_pm(calib['slope'], calib['slope_se'])}")
    lines.append(f"  截距 a    = {_fmt_pm(calib['intercept'], calib['intercept_se'])}")
    if calib.get('r2') is not None:
        r2_line = f"  R²        = {calib['r2']:.6f}"
        if calib.get('adj_r2') is not None:
            r2_line += f"   校正 R² = {calib['adj_r2']:.6f}"
        lines.append(r2_line)
    else:
        lines.append('  R²        = —（y 全相同，无定义）')
    lines.append(f"  s_yx      = {_fmt_num(calib.get('s_yx'))}"
                 f"　（自由度 {calib['dof']}；LOD 公式里用的就是这个 s）")
    lines.append(f"  RMSE      = {_fmt_num(calib.get('rmse'))}（sqrt(RSS/n)）")
    if calib.get('slope_p') is not None:
        lines.append(f"  斜率显著性 t = {_fmt_num(calib['slope_t'])}，"
                     f"p = {calib['slope_p']:.3g}")
    if calib.get('slope_ci'):
        lo, hi = calib['slope_ci']
        lines.append(f"  斜率 95% CI = [{_fmt_num(lo)}, {_fmt_num(hi)}]")
    if levels:
        lines.append('')
        lines.append('  逐浓度汇总：')
        lines.append(f"    {'x':>10s} {'重复数':>5s} {'均值':>14s} "
                     f"{'标准差':>13s} {'RSD%':>7s}")
        for lv in levels:
            sd = lv['sd']
            rsd = (100.0 * sd / lv['mean']) if (sd is not None and lv['mean']) \
                else None
            lines.append(f"    {lv['x']:>10.6g} {lv['n']:>5d} "
                         f"{lv['mean']:>14.6g} "
                         f"{(f'{sd:.4g}' if sd is not None else '—'):>13s} "
                         f"{(f'{rsd:.2f}' if rsd is not None else '—'):>7s}")
    if lod:
        lines.append('')
        lines.append(f"  LOD = {lod['k_lod']:g}·s_yx/|b| = {_fmt_num(lod.get('lod'))}"
                     f"　（单位同 {x_name}）")
        lines.append(f"  LOQ = {lod['k_loq']:g}·s_yx/|b| = {_fmt_num(lod.get('loq'))}"
                     f"　（单位同 {x_name}）")
        if lod.get('blank_sd') is not None:
            lines.append(f"  空白标准差 s0 = {_fmt_num(lod['blank_sd'])}"
                         f"（{lod.get('blank_sd_source', '')}）")
            if lod.get('lod_from_blank') is not None:
                lines.append(f"  改用 s0：LOD = {_fmt_num(lod['lod_from_blank'])}，"
                             f"LOQ = {_fmt_num(lod['loq_from_blank'])}")
        lr = lod.get('linear_range') or {}
        if lr:
            lines.append(f"  线性范围 = {_fmt_num(lr.get('x_min'))} – "
                         f"{_fmt_num(lr.get('x_max'))}"
                         f"（{lr.get('n_levels')} 个浓度 / "
                         f"{lr.get('n_points')} 点）")
            for d in (lr.get('dropped_levels') or []):
                lines.append(f"    剔除 {d['side']} x={_fmt_num(d['x'])}"
                             f"（|标准化残差| 最大 {d['max_abs_std_resid']:.2f}）")
            lines.append(f"    判据：{lr.get('reason', '')}")
    for wmsg in (calib.get('warnings') or []):
        lines.append(f'  [注意] {wmsg}')
    for wmsg in (lod.get('warnings') if lod else []) or []:
        if wmsg not in (calib.get('warnings') or []):
            lines.append(f'  [注意] {wmsg}')
    return '\n'.join(lines)


# ======================== 8. 从文件夹一键标定 ========================

def _load_samples(files, kind='emission', verbose=False):
    """逐文件读光谱，返回 ``(samples, errors)``；samples 是
    ``[(显示名, 文件名, wl, y)]``。

    为什么按文件循环而不一次性喂 ``load_spectra``：本模块要拿**文件名**去对齐
    ``read_measurement_header`` 的测量条件元数据（可比性预检要用），而
    ``plot_emission.load_spectra`` 的返回里没有源文件路径。
    取点本身（``measure_metric`` / ``collect_points``）仍然复用 ``plot_compare``，
    这里只负责"读"这一层。
    """
    samples, errors = [], []
    for fp in files:
        fp = str(fp)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                if kind == 'absorption':
                    from plot_absorption import load_absorption_spectra
                    data = list(load_absorption_spectra(
                        fp, skip_metadata=True, verbose=False) or [])
                    for d in data:
                        wl = d.get('wavelength', d.get('wl'))
                        yy = d.get('absorption', d.get('intensity'))
                        if wl is None or yy is None:
                            continue
                        label = (d.get('label') or d.get('name')
                                 or Path(fp).stem)
                        samples.append((str(label), Path(fp).name,
                                        np.asarray(wl, float),
                                        np.asarray(yy, float)))
                else:
                    from plot_emission import load_spectra
                    for d in load_spectra([fp], verbose=False):
                        wl = d.get('wavelength', d.get('wl'))
                        yy = d.get('intensity', d.get('absorption'))
                        if wl is None or yy is None:
                            continue
                        label = (d.get('label') or d.get('name')
                                 or Path(fp).stem)
                        samples.append((str(label), Path(fp).name,
                                        np.asarray(wl, float),
                                        np.asarray(yy, float)))
        except Exception as e:               # 一个坏文件不该中断整批
            errors.append((Path(fp).name, str(e)))
            if verbose:
                _safe_print(f'  [SKIP] {Path(fp).name}: {e}')
    return samples, errors


def _read_headers(files):
    """读每个文件的测量条件头：``{文件名: header dict}``（读不到就跳过）。"""
    out = {}
    try:
        from plot_emission import read_measurement_header
    except Exception:                                    # pragma: no cover
        return out
    for fp in files:
        try:
            out[Path(str(fp)).name] = read_measurement_header(str(fp))
        except Exception:
            continue
    return out


def _group_key_from_name(fname):
    """从文件名取"编号"（``R1-2.csv`` → ``R1``），给可比性检查分组用。"""
    stem = Path(str(fname)).stem
    head = ''
    for ch in stem:
        if ch.isalnum() or ch == '_':
            head += ch
        else:
            break
    if not head:
        return stem
    return head


def auto_band(samples, margin=15.0, cluster_nm=5.0, verbose=True):
    """按谱峰自动定一个"取峰强度"的波长区间 ``(lo, hi)``。

    做法：先取每条谱的峰位，按 ``cluster_nm`` 分箱，选**占比最大的那一簇**
    （一堆谱共有的峰才是有意义的信号；单条谱的散射峰不该把中心拉走），
    用簇内峰位中位数当中心，向两侧各展 ``margin`` nm。

    为什么不用全体中位数：一批数据里常常混着两组不同激发波长的谱
    （实测 05 数据 RB 系列峰在 570 nm、Ce6 系列在 665 nm），中位数会落在
    两者之间、取到谁都不是的波长上。按最大簇取至少能落在一组真实峰上。

    这只是省事的默认值——**报告里必须写清用了哪一段**，因为它直接决定读数。
    混有两组谱时请显式给 ``band``。
    """
    positions = []
    for s in samples:
        wl = np.asarray(s[2], float)
        yy = np.asarray(s[3], float)
        m = np.isfinite(wl) & np.isfinite(yy)
        if not m.any():
            continue
        positions.append(float(wl[m][int(np.argmax(yy[m]))]))
    if not positions:
        raise CalibrationError('没有可用光谱，无法自动定波段，请显式给 band=(lo, hi)')
    buckets = {}
    for p in positions:
        buckets.setdefault(int(round(p / cluster_nm)), []).append(p)
    biggest = max(buckets.values(), key=len)
    center = float(np.median(biggest))
    allmin = min(float(np.min(np.asarray(s[2], float))) for s in samples)
    allmax = max(float(np.max(np.asarray(s[2], float))) for s in samples)
    lo = max(center - margin, allmin)
    hi = min(center + margin, allmax)
    if hi <= lo:
        raise CalibrationError(
            f'自动定带失败（峰位 {center:.1f} nm 附近数据不足），'
            '请显式给 band=(lo, hi)')
    if verbose:
        _safe_print(f'  [INFO] 自动选定峰强度区间：{lo:g}–{hi:g} nm'
                    f'（{len(biggest)}/{len(positions)} 条谱峰位在 '
                    f'{center:.1f} nm 附近 ±{margin:g} nm）。'
                    '这个区间直接决定读数，写报告时请写明；'
                    '若数据里混有多组峰，请改用 --band 显式指定。')
    return (float(lo), float(hi))


def calibrate_from_folder(folder, x_var, metric='peak_intensity', band=None,
                          at_wl=None, kind='emission', save_dir='./plots',
                          name=None, dpi=None, comparability=True,
                          outlier_sigma=DEFAULT_OUTLIER_SIGMA,
                          drop_outliers=False, verbose=True,
                          figsize=(7.6, 8.6), band_margin=15.0):
    """一键：读光谱 → 可比性预检 → 压成读数 → 回归 → 出图 → 出表。

    流程与"为什么这么排"
    --------------------
    1. **可比性预检**（``plot_compare.check_comparability``，v5.0.6+）：
       同一编号下多个文件若激发波长 / 带宽 / 扫描范围不一致、扫描被截断、
       或读数取到散射峰，就不能当平行样。用全量文件直接回归会把 LOD 算歪——
       本函数默认把 **error 级**问题涉及的文件排除在回归之外。
       例外：「谱形不一致（峰位）」这条**不**一票否决，改由第 3 步的读数质检
       判断（波段已经限定时，谱形差异可能只是散射峰位置不同，波段内的峰仍可用）。
    2. **取点**：复用 ``plot_compare.collect_points`` + ``measure_metric``，
       把每条谱压成一个读数（峰强度 / 峰面积 / 指定波长值）。
    3. **读数质检**：``peak_intensity`` 且给了 band 时，检查带内最大值是否
       贴着波段边缘——贴着说明可能取到散射/拉曼带而不是荧光峰。
       这种点**只提示、不剔除**（区间是人定的，判据在人手里）。
    4. **回归**：``linear_calibration``（逐点，含重复测量，不先平均）。
    5. **失拟检验 + LOD/LOQ + 线性范围**。
    6. 出图（``plot_calibration``）、出逐点 CSV、出统计 CSV、出 JSON。

    参数
    ----
    folder : str | Path        含 ``说明.xlsx`` 与 CSV/TXT 的文件夹
    x_var : str                ``说明.xlsx`` 里作横轴的**数值列**（如 ``'RB浓度'``）
    metric / band / at_wl      纵轴口径，同 ``plot_compare.measure_metric``。
                               ``band=None`` 时按谱峰自动定带（见 :func:`auto_band`）
    kind : {'emission', 'absorption'}
    save_dir : str | Path      输出目录（默认 ``./plots``）
    comparability : bool       是否跑可比性预检（默认开）
    outlier_sigma : float      标准化残差超过它会**被报告**；``drop_outliers=True``
                               才剔除并重拟合
    band_margin : float        自动定带时的半宽（nm）

    返回
    ----
    dict：``slope`` / ``intercept`` / ``r2`` / ``s_yx`` / ``lod`` / ``loq`` /
    ``calibration`` / ``lod_detail`` / ``lack_of_fit`` / ``levels`` / ``points`` /
    ``excluded`` / ``exclude_reasons`` / ``comparability`` / ``qc_notes`` /
    ``band`` / ``figure`` / ``csv`` / ``fit_csv`` / ``json`` / ``report_text``。
    """
    folder = Path(folder)
    if not folder.is_dir():
        raise CalibrationError(f'文件夹不存在：{folder}')
    files = sorted({str(p) for p in folder.iterdir()
                    if p.is_file() and p.suffix.lower() in ('.csv', '.txt')})
    if not files:
        raise CalibrationError(f'{folder} 里没有 CSV / TXT 光谱文件')

    info = load_xlsx_info(folder)
    if info is None:
        raise CalibrationError(
            f'{folder} 里没找到 / 读不出 说明.xlsx，无法取横轴变量 {x_var!r}')
    numeric = list(info.numeric_columns())
    if x_var not in numeric:
        raise CalibrationError(
            f'说明.xlsx 里没有数值列 {x_var!r}；'
            f'可用的数值列：{numeric or "（无）"}')

    samples, load_errors = _load_samples(files, kind=kind, verbose=verbose)
    if not samples:
        raise CalibrationError(
            '所有文件都解析失败：'
            + '；'.join(f'{n}: {r}' for n, r in load_errors[:5]))

    # ---------- ① 可比性预检 ----------
    comp, hard_excluded = None, {}
    if comparability:
        comp = check_comparability_safe(
            samples, headers=_read_headers(files),
            group_of=_group_key_from_name, kind=kind)
        for it in comp.get('issues', []):
            if it.get('level') != 'error':
                continue
            if it.get('code') == 'peak_shift':
                continue                 # 交给第 ③ 步的读数质检判断
            snippet = str(it.get('detail', ''))[:80]
            for fn in it.get('samples', []):
                hard_excluded.setdefault(fn, f'{it.get("title", "")}：{snippet}…')
    if verbose and comp is not None:
        _safe_print(f'  [预检] {comp.get("summary", "")}')
        for fn, why in hard_excluded.items():
            _safe_print(f'  [排除] {fn} —— {why}')

    # ---------- ② 取点 ----------
    if band is None and metric in ('peak_intensity', 'peak_area'):
        band = auto_band(samples, margin=band_margin, verbose=verbose)
    res = collect_points(samples, info, x_var, group_var=None, metric=metric,
                         band=band, at_wl=at_wl)
    if not res['points']:
        raise CalibrationError(
            f'没有样品能取到「{x_var}」与读数；跳过原因：'
            + '；'.join(f'{n}: {w}' for n, w in res['skipped'][:6]))

    pts = sorted(res['points'], key=lambda p: (p[1], str(p[3])))
    # 样品短名：collect_points 给的 name 是 label（发射是 "R1-2 (Emission)" 这种
    # 带后缀的），取空格前那段当短名；同时记住对应的**真实文件名**，
    # 后面按文件名对齐可比性预检结果（不能靠"短名 + '.csv'"猜，扩展名可能是 .txt）。
    labels = [str(p[3]).split(' ')[0] for p in pts]
    numbers = [p[4] for p in pts]
    xs = np.array([p[1] for p in pts], float)
    ys = np.array([p[2] for p in pts], float)

    # 短名 → 真实文件名（一个短名可能对应多条谱，取第一条）
    file_of_label = {}
    for s in samples:
        fname = str(s[1])
        file_of_label.setdefault(Path(fname).stem, fname)
        file_of_label.setdefault(str(s[0]).split(' ')[0], fname)

    # ---------- ③ 读数质检：带内最大值是否贴着波段边缘 ----------
    qc_notes = {}
    if metric == 'peak_intensity' and band is not None:
        lo, hi = float(band[0]), float(band[1])
        edge_warn = max(2.0, 0.04 * (hi - lo))
        by_stem = {}
        for s in samples:
            by_stem.setdefault(Path(s[1]).stem, s)
        for lb in labels:
            s = by_stem.get(lb)
            if s is None:
                continue
            wl, yy = np.asarray(s[2], float), np.asarray(s[3], float)
            m = (wl >= lo) & (wl <= hi) & np.isfinite(yy)
            if not m.any():
                continue
            peak = float(wl[m][int(np.argmax(yy[m]))])
            if peak - lo <= edge_warn or hi - peak <= edge_warn:
                qc_notes[lb] = (f'带内最大值落在 {peak:g} nm，贴着区间边缘'
                                f'（{lo:g}–{hi:g}），读数可能取到散射/拉曼带')

    excl = np.zeros(xs.size, bool)
    reasons = [''] * xs.size
    for i, lb in enumerate(labels):
        # 按真实文件名比对（可比性预检的 samples 存的就是文件名）
        fname = file_of_label.get(lb, lb + '.csv')
        if fname in hard_excluded:
            excl[i] = True
            reasons[i] = hard_excluded[fname]
        elif lb in qc_notes:
            reasons[i] = qc_notes[lb]        # 只提示，默认不剔

    if verbose:
        for i, r in enumerate(reasons):
            if r and not excl[i]:
                _safe_print(f'  [留意] {labels[i]}：{r}')
    if excl.all():
        raise CalibrationError(
            '所有样品都在可比性预检里被判为 error，没有可用于回归的点。'
            '可以传 comparability=False 跳过预检，或检查测量条件是否一致。')
    if np.unique(xs[~excl]).size < 2:
        raise CalibrationError(
            f'可用于回归的样品只覆盖 {np.unique(xs[~excl]).size} 个不同的 '
            f'{x_var} 值，至少要 2 个才能拟合直线')

    # ---------- ④ 回归 ----------
    calib = linear_calibration(xs[~excl], ys[~excl])
    lo_fit = lack_of_fit_test(xs[~excl], ys[~excl])

    outlier_dropped = []
    if drop_outliers and calib.get('s_yx') not in (None, 0):
        kept_idx = np.flatnonzero(~excl)
        for j, sr in enumerate(calib['residuals'] / calib['s_yx']):
            if abs(sr) > outlier_sigma:
                k = int(kept_idx[j])
                excl[k] = True
                reasons[k] = (f'标准化残差 {sr:+.2f} 超过 ±{outlier_sigma:g}'
                              '（drop_outliers=True 剔除）')
                outlier_dropped.append({'label': labels[k],
                                        'x': float(xs[k]),
                                        'y': float(ys[k]),
                                        'std_resid': float(sr),
                                        'reason': reasons[k]})
        if outlier_dropped:
            if verbose:
                for o in outlier_dropped:
                    _safe_print(f'  [剔除] {o["label"]}：{o["reason"]}')
            calib = linear_calibration(xs[~excl], ys[~excl])
            lo_fit = lack_of_fit_test(xs[~excl], ys[~excl])

    # ---------- ⑤ LOD / LOQ / 线性范围 ----------
    # 用**全部参与拟合的逐点数据**（含重复测量）算 s_yx，绝不"先平均再拟合"：
    # 平均会抹掉纯误差，s_yx 假性变小，LOD 假性变好。
    lod = lod_loq(xs[~excl], ys[~excl], calibrate=calib)

    # ---------- ⑥ 出图 ----------
    save_dir = Path(save_dir)
    stem = f'calibration_{name or x_var}_{metric}'
    y_label = describe_metric(metric, band, at_wl)
    title = f'{y_label} – {x_var} 标定' + (f'（{name}）' if name else '')
    fig, fsum = plot_calibration(
        xs, ys, x_label=x_var, y_label=y_label, title=title,
        exclude_mask=excl, exclude_labels=labels, lod=lod, calib=calib,
        outlier_sigma=outlier_sigma, figsize=figsize, dpi=dpi,
        save_path=save_dir / f'{stem}.png', verbose=verbose)
    plt.close(fig)

    # ---------- ⑦ 出表 ----------
    levels = aggregate_replicates(xs[~excl], ys[~excl])
    csv_path = calibration_to_csv(
        xs, ys, save_dir / f'{stem}_points.csv', x_name=x_var,
        y_name=y_label, exclude_mask=excl, labels=labels, numbers=numbers,
        reasons=reasons, levels=levels)
    fit_csv = fit_to_csv(
        calib, lod, save_dir / f'{stem}_fit.csv', x_name=x_var,
        y_name=y_label,
        extra_rows=[('失拟检验 F', lo_fit.get('f'), '',
                     lo_fit.get('verdict', '')),
                    ('有效样品数', int((~excl).sum()), '',
                     f'共 {xs.size} 个样品'),
                    ('峰强区间', str(tuple(band)) if band else '', '',
                     '读数取自这一段波长')])
    out_dpi = EXPORT_DPI_DEFAULT if dpi is None else dpi
    json_path = result_to_json(
        {'x_var': x_var, 'metric': metric,
         'band': list(band) if band else None,
         'n_points': int((~excl).sum()), 'n_excluded': int(excl.sum()),
         'slope': calib['slope'], 'intercept': calib['intercept'],
         'slope_se': calib['slope_se'],
         'intercept_se': calib['intercept_se'],
         'r2': calib['r2'], 'adj_r2': calib['adj_r2'],
         's_yx': calib['s_yx'], 'rmse': calib['rmse'],
         'lod': lod.get('lod'), 'loq': lod.get('loq'),
         'linear_range': lod.get('linear_range'),
         'lack_of_fit': lo_fit,
         'excluded': [{'label': labels[i], 'x': float(xs[i]),
                       'y': float(ys[i]), 'reason': reasons[i]}
                      for i in range(xs.size) if excl[i]],
         'levels': levels},
        save_dir / f'{stem}.json',
        meta={'module': 'plot_calibration', 'exported_at': _now_iso(),
              'params': {'folder': str(folder), 'x_var': x_var,
                         'metric': metric, 'band': band, 'at_wl': at_wl,
                         'kind': kind, 'outlier_sigma': outlier_sigma,
                         'comparability': comparability, 'dpi': out_dpi}})

    return {
        'slope': calib['slope'], 'intercept': calib['intercept'],
        'r2': calib['r2'], 's_yx': calib['s_yx'],
        'lod': lod.get('lod'), 'loq': lod.get('loq'),
        'calibration': calib, 'lod_detail': lod,
        'lack_of_fit': lo_fit, 'levels': levels,
        'points': pts,
        'excluded': [labels[i] for i in range(xs.size) if excl[i]],
        'exclude_reasons': {labels[i]: reasons[i] for i in range(xs.size)
                            if reasons[i]},
        'outlier_dropped': outlier_dropped,
        'comparability': comp, 'qc_notes': qc_notes,
        'band': band, 'x_var': x_var, 'metric': metric,
        'figure': str(save_dir / f'{stem}.png'),
        'csv': str(csv_path), 'fit_csv': str(fit_csv), 'json': str(json_path),
        'summary': fsum, 'load_errors': load_errors,
        'report_text': format_calibration_report(
            calib, lod, x_name=x_var, y_name=y_label, levels=levels,
            title=title),
    }


def check_comparability_safe(samples, **kwargs):
    """:func:`plot_compare.check_comparability` 的容错包装。

    老版本 ``plot_compare`` 没有可比性检查（v5.0.6 才加）时返回"跳过"结构
    而不是 AttributeError——本模块要能单独复制到旧仓库里跑；
    检查本身抛异常也不该挡住标定。
    """
    try:
        from plot_compare import check_comparability
    except ImportError:
        return {'issues': [], 'groups': {}, 'n_ok': len(samples),
                'n_flagged': 0,
                'summary': '当前 plot_compare 没有可比性检查（需 v5.0.6+），已跳过'}
    try:
        return check_comparability(samples, **kwargs)
    except Exception as e:
        return {'issues': [], 'groups': {}, 'n_ok': len(samples),
                'n_flagged': 0, 'summary': f'可比性检查执行失败，已跳过：{e}'}


# ======================== 9. 合成数据自检 ========================

def demo(save_dir=None, verbose=True, seed=20261108):
    """合成真值自检：已知斜率/截距、已知 Ksv，看能不能还原回来。

    这不是"跑通就行"的冒烟测试——每项都对着**已知真值**比：
    斜率截距还原、``s_yx`` 与已知噪声 σ 一致、``LOD`` 与 ``3σ/|b|`` 一致、
    ``Ksv`` 还原、二阶模型能抓到 ``K2``、以及四种边界情况的行为。
    返回 dict，便于调用方自行断言。
    """
    rng = np.random.default_rng(seed)
    out = {}

    # ---- ① 线性回归还原 ----
    b_true, a_true, sigma = 250.0, 1500.0, 400.0
    x = np.repeat(np.array([2.0, 5.0, 10.0, 20.0, 40.0]), 4)
    y = a_true + b_true * x + rng.normal(0, sigma, x.size)
    cal = linear_calibration(x, y)
    lod = lod_loq(x, y, calibrate=cal)
    out['linear'] = {'true': {'slope': b_true, 'intercept': a_true,
                              'sigma': sigma}, 'fit': cal, 'lod': lod}
    if verbose:
        _safe_print('① 线性回归还原（真值 b=250, a=1500, σ=400）')
        _safe_print(f"   b = {_fmt_pm(cal['slope'], cal['slope_se'])}"
                    f"（真值 {b_true}，偏差 "
                    f"{100 * (cal['slope'] / b_true - 1):+.2f}%）")
        _safe_print(f"   a = {_fmt_pm(cal['intercept'], cal['intercept_se'])}"
                    f"（真值 {a_true}，偏差 "
                    f"{100 * (cal['intercept'] / a_true - 1):+.2f}%）")
        _safe_print(f"   R² = {cal['r2']:.6f}   "
                    f"s_yx = {_fmt_num(cal['s_yx'])}"
                    f"（真值 σ = {sigma}，比值 "
                    f"{cal['s_yx'] / sigma:.3f}，应≈1）")
        _safe_print(f"   LOD = {_fmt_num(lod['lod'])}（= 3·s_yx/|b| = "
                    f"{3.0 * cal['s_yx'] / cal['slope']:.3f}）")
        _safe_print(f"   若用真实 σ 则应得 3σ/|b| = "
                    f"{3.0 * sigma / abs(b_true):.3f}")
        _safe_print(f"   LOQ = {_fmt_num(lod['loq'])}；线性范围 "
                    f"{_fmt_num(lod['linear_range']['x_min'])}–"
                    f"{_fmt_num(lod['linear_range']['x_max'])}")

    # ---- ② 失拟检验：真线性 vs 真弯曲 ----
    xl = np.repeat([1.0, 2.0, 4.0, 8.0], 5)
    t_lin = lack_of_fit_test(xl, 100 + 50 * xl + rng.normal(0, 20, xl.size))
    t_cur = lack_of_fit_test(
        xl, 100 + 50 * xl + 6.0 * xl ** 2 + rng.normal(0, 20, xl.size))
    out['lack_of_fit'] = {'linear_data': t_lin, 'curved_data': t_cur}
    if verbose:
        _safe_print('')
        _safe_print('② 失拟检验（每浓度 5 次重复；期望：真线性不显著、'
                    '真弯曲显著）')
        _safe_print(f"   真线性数据：F={_fmt_num(t_lin['f'])}，"
                    f"p={_fmt_num(t_lin['p'])} → {t_lin['verdict']}")
        _safe_print(f"   真弯曲数据：F={_fmt_num(t_cur['f'])}，"
                    f"p={_fmt_num(t_cur['p'])} → {t_cur['verdict']}")

    # ---- ③ Stern–Volmer ----
    q = np.array([0.0, 2.0, 5.0, 10.0, 20.0, 30.0, 40.0, 50.0])
    ksv_true = 0.032
    sv_lin = stern_volmer(q, 1.0 + ksv_true * q + rng.normal(0, 0.008, q.size))
    k1_true, k2_true = 0.020, 0.0006
    sv_quad = stern_volmer(
        q, 1.0 + k1_true * q + k2_true * q ** 2 + rng.normal(0, 0.008, q.size),
        model='quadratic')
    out['stern_volmer'] = {'linear': sv_lin, 'quadratic': sv_quad,
                           'true': {'ksv': ksv_true, 'k1': k1_true,
                                    'k2': k2_true}}
    if verbose:
        _safe_print('')
        _safe_print('③ Stern–Volmer 还原')
        _safe_print(f"   纯动态猝灭（真 Ksv={ksv_true}）："
                    f"Ksv={_fmt_num(sv_lin['ksv'])}"
                    f"（偏差 {100 * (sv_lin['ksv'] / ksv_true - 1):+.2f}%）"
                    f"；强制截距=1 → "
                    f"{_fmt_num(sv_lin['ksv_through_origin'])}")
        _safe_print(f"   模型比较：{sv_lin['comparison']['verdict']}")
        _safe_print(f"   混合猝灭（真 K1={k1_true}, K2={k2_true}）："
                    f"K1={_fmt_num(sv_quad['k1'])}，"
                    f"K2={_fmt_num(sv_quad['k2'], 3)}")
        _safe_print(f"   模型比较：{sv_quad['comparison']['verdict']}")

    # ---- ④ 四种边界情况 ----
    edge = {}
    try:
        c2 = linear_calibration([1.0, 2.0], [3.0, 5.0])
        l2 = lod_loq([1.0, 2.0], [3.0, 5.0], calibrate=c2)
        edge['两点'] = (f"降级不报错：status={c2['status']}，"
                        f"slope={_fmt_num(c2['slope'])}，"
                        f"slope_se={c2['slope_se']}，s_yx={c2['s_yx']}，"
                        f"r2={c2['r2']}，lod={l2['lod']}")
    except CalibrationError as e:
        edge['两点'] = f'CalibrationError：{e}'
    try:
        linear_calibration([5.0, 5.0, 5.0], [1.0, 2.0, 3.0])
        edge['x全同'] = '没报错（异常！）'
    except CalibrationError as e:
        edge['x全同'] = f'CalibrationError（预期）：{e}'
    cy = linear_calibration([1.0, 2.0, 3.0], [7.0, 7.0, 7.0])
    ly = lod_loq([1.0, 2.0, 3.0], [7.0, 7.0, 7.0], calibrate=cy)
    edge['y全同'] = (f"降级：slope={_fmt_num(cy['slope'])}，"
                     f"r2={cy['r2']}，s_yx={_fmt_num(cy['s_yx'])}，"
                     f"lod={ly['lod']}，status={cy['status']}")
    cn = linear_calibration([1.0, np.nan, 3.0, 4.0],
                            [2.0, 5.0, np.nan, 9.0])
    edge['含NaN'] = (f"丢弃并记录：n={cn['n']}，"
                     f"n_dropped={cn['n_dropped']}，"
                     f"dropped_index={cn['dropped_index']}，"
                     f"slope={_fmt_num(cn['slope'])}")
    out['edge_cases'] = edge
    if verbose:
        _safe_print('')
        _safe_print('④ 边界情况（期望：两点/y全同 → 降级返回 None；'
                    'x全同 → 报错；含NaN → 丢弃并记录）')
        for k, v in edge.items():
            _safe_print(f'   {k}: {v}')

    # ---- ⑤ 出图 ----
    if save_dir is not None:
        save_dir = Path(save_dir)
        fig, _ = plot_calibration(
            x, y, x_label='浓度 (μmol/L)', y_label='峰强度 (a.u.)',
            title='合成数据自检：已知 b=250, a=1500, σ=400',
            lod=lod, calib=cal,
            save_path=save_dir / 'demo_calibration.png', verbose=verbose)
        plt.close(fig)
        fig2, _ = plot_stern_volmer(
            sv_quad, x_label='[Q] (mmol/L)', y_label='I$_0$/I',
            title='合成数据自检：混合猝灭（真 K1=0.020, K2=0.0006）',
            save_path=save_dir / 'demo_stern_volmer.png', verbose=verbose)
        plt.close(fig2)
        out['figures'] = [str(save_dir / 'demo_calibration.png'),
                          str(save_dir / 'demo_stern_volmer.png')]
    return out


# ======================== 10. 命令行 ========================

def _build_parser():
    ap = argparse.ArgumentParser(
        description='线性标定 + 检出限/定量限 + Stern–Volmer'
                    '（读同目录 说明.xlsx 取浓度变量）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='例：\n'
               '  python plot_calibration.py "D:\\data\\05" --x RB浓度 --band 555 620\n'
               '  python plot_calibration.py "D:\\data\\05" --x Ce6浓度 --band 655 685 --dpi 300\n'
               '  python plot_calibration.py "D:\\data\\05" --list-vars\n'
               '  python plot_calibration.py --demo\n')
    ap.add_argument('folder', nargs='?', default=None,
                    help='数据文件夹（含 说明.xlsx 与 CSV/TXT）')
    ap.add_argument('--x', default=None, help='横轴变量列名（缺省用第一个数值列）')
    ap.add_argument('--metric', default='peak_intensity',
                    choices=list(METRIC_ORDER),
                    help='纵轴口径：峰强度 / 峰面积 / 指定波长处的值')
    ap.add_argument('--band', nargs=2, type=float, default=None,
                    metavar=('LO', 'HI'),
                    help='峰强度/峰面积的波长区间（nm）；不给则按谱峰自动定带')
    ap.add_argument('--at', type=float, default=None,
                    help='at_wavelength 用的波长（nm）')
    ap.add_argument('--kind', default='emission',
                    choices=['emission', 'absorption'])
    ap.add_argument('--save-dir', default='./plots', help='输出目录（默认 ./plots）')
    ap.add_argument('--name', default=None,
                    help='输出文件名里用的标签（如 RB / Ce6）')
    ap.add_argument('--dpi', type=float, default=None,
                    help=f'导出 DPI（默认 {EXPORT_DPI_DEFAULT}）')
    ap.add_argument('--outlier-sigma', type=float, default=DEFAULT_OUTLIER_SIGMA,
                    help='标准化残差超过它就在图上标红圈（默认 3.0）')
    ap.add_argument('--drop-outliers', action='store_true',
                    help='把超过 --outlier-sigma 的点剔除后重拟合')
    ap.add_argument('--no-comparability', action='store_true',
                    help='跳过可比性预检（确信所有文件测量条件一致时才用）')
    ap.add_argument('--list-vars', action='store_true',
                    help='只列出说明.xlsx 里可作横轴的数值列')
    ap.add_argument('--demo', action='store_true',
                    help='跑合成真值自检（不需要数据文件夹）')
    ap.add_argument('--json', action='store_true',
                    help='把关键结果 JSON 打到标准输出（便于脚本取数）')
    return ap


def main(argv=None):
    """命令行入口；返回退出码（0 成功 / 1 数据问题 / 2 参数问题）。"""
    args = _build_parser().parse_args(argv)

    if args.demo:
        demo(save_dir=args.save_dir, verbose=True)
        return 0

    if not args.folder:
        _safe_print('缺少数据文件夹。用法见 --help，或用 --demo 先自检。')
        return 2

    if args.list_vars:
        info = load_xlsx_info(args.folder)
        if info is None:
            _safe_print('没找到 / 读不出 说明.xlsx')
            return 1
        _safe_print(f'说明.xlsx: {info.path}')
        cols = list(info.numeric_columns())
        if not cols:
            _safe_print('  没有数值列可作横轴变量')
            return 1
        for c in cols:
            _safe_print(f'  数值列: {c}')
        return 0

    band = tuple(args.band) if args.band else None
    x_var = args.x
    if x_var is None:
        info = load_xlsx_info(args.folder)
        cols = list(info.numeric_columns()) if info is not None else []
        if not cols:
            _safe_print('没指定 --x，且说明.xlsx 里没有数值列。先跑 --list-vars。')
            return 2
        x_var = cols[0]
        _safe_print(f'  [INFO] 未指定 --x，自动使用第一个数值列：{x_var}')

    try:
        out = calibrate_from_folder(
            folder=args.folder, x_var=x_var, metric=args.metric, band=band,
            at_wl=args.at, kind=args.kind, save_dir=args.save_dir,
            name=args.name, dpi=args.dpi,
            comparability=not args.no_comparability,
            outlier_sigma=args.outlier_sigma,
            drop_outliers=args.drop_outliers, verbose=True)
    except CalibrationError as e:
        _safe_print(f'[失败] {e}')
        return 1

    _safe_print('')
    _safe_print(out['report_text'])
    _safe_print('')
    _safe_print(f"  图：{out['figure']}")
    _safe_print(f"  逐点表：{out['csv']}")
    _safe_print(f"  统计表：{out['fit_csv']}")
    _safe_print(f"  JSON：{out['json']}")
    if out['exclude_reasons']:
        _safe_print('  被排除 / 需留意的样品：')
        for lb, why in out['exclude_reasons'].items():
            _safe_print(f'    {lb}: {why}')
    if args.json:
        _safe_print(json.dumps(_json_safe(
            {'slope': out['slope'], 'intercept': out['intercept'],
             'r2': out['r2'], 's_yx': out['s_yx'],
             'lod': out['lod'], 'loq': out['loq']}), ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
