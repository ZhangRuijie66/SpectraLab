# -*- coding: utf-8 -*-
"""
光谱「强度-变量」相关性点线图模块（plot_compare）
================================================
适用数据
--------
一批**同类型**光谱（吸收或发射的 CSV / TXT，一行一个波长点）+ 同目录下的
``说明.xlsx``（列名如 ``编号 / RB浓度 / L8i浓度 / 备注``，见 read_xlsx_info）。

功能
----
把每条光谱压缩成**一个纵轴读数**，再按 ``说明.xlsx`` 中某个变量的值散点连线：

* 纵轴三种口径（``metric``）：
  - ``peak_intensity``：**峰强度** —— 指定区间（``band``，缺省全谱）内的最大强度；
  - ``peak_area``     ：**峰面积** —— 指定区间的梯形积分（与 GUI「光谱积分」同一实现）；
  - ``at_wavelength`` ：**指定波长处的值** —— 在 ``at_wl`` 处线性插值取值。
* 横轴：``说明.xlsx`` 中某个**数值列**的值（如 RB浓度）。
* 分组（可选）：另一个数值列，每组画一条点线（如固定 L8i浓度、画强度 vs RB浓度）。

**空值不显示**：``说明.xlsx`` 里某样品缺某个变量（NaN / 空单元格 / 文本 ``null``、
``N/A`` 等）时，该样品**不进入图**，并记进返回值 ``skipped`` 说明原因——
不会出现 ``nan`` 点或凭空补 0。

一键用法
--------
::

    from plot_compare import run_compare

    out = run_compare(
        folder=r'D:\\...\\20260825',        # 数据文件夹（自动找 说明.xlsx）
        x_var='RB浓度',                     # 横轴变量
        group_var='L8i浓度',                # 可选分组变量
        metric='peak_intensity',            # 峰强度 / 峰面积 / at_wavelength
        band=(560, 620),                    # 峰强度/峰面积的区间（nm）
        save_dir=r'./plots',
    )
    print(out['figure'], out['points'])

命令行用法
----------
::

    python plot_compare.py "D:\\data\\20260825" --x RB浓度 --group L8i浓度 \\
        --metric peak_intensity --band 560 620
    python plot_compare.py "D:\\data\\20260825" --x RB浓度 --metric peak_area \\
        --band 400 510 --list-vars

依赖：只用到 numpy / pandas / matplotlib（另用同目录的 read_xlsx_info 读说明.xlsx）。
"""

import argparse
import glob
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import numpy as np

try:                                    # 同目录模块；独立运行本文件时也能找到
    from read_xlsx_info import load_xlsx_info, match_number
except ImportError:                     # pragma: no cover
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from read_xlsx_info import load_xlsx_info, match_number

# 导出口径单一来源（v5.0.2）。根目录各 plot_*.py 与 GUI 共用同一组 DPI，
# 避免"同一份数据从 GUI 和命令行导出的图分辨率差 2–3 倍"。找不到时退回字面量，
# 保证脚本能脱离仓库单独复制出去运行。
try:
    from export_defaults import (EXPORT_DPI_DEFAULT,
                                 EXPORT_DPI_VECTOR_MIN,
                                 EXPORT_DPI_PREVIEW)
except ImportError:                     # pragma: no cover
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        from export_defaults import (EXPORT_DPI_DEFAULT,
                                     EXPORT_DPI_VECTOR_MIN,
                                     EXPORT_DPI_PREVIEW)
    except ImportError:
        EXPORT_DPI_DEFAULT, EXPORT_DPI_VECTOR_MIN, EXPORT_DPI_PREVIEW = 600, 300, 150


# ======================== 0. 中文字体 / 打印 ========================

def _safe_print(*args):
    """安全打印：在某些终端/编码（如 GBK、ASCII）下避免因非 ASCII 字符崩溃"""
    try:
        print(*args)
    except Exception:
        pass


def setup_chinese_font():
    """挑一个可用的中文字体（Windows/macOS/Linux 依次尝试）。"""
    candidates = [
        'Microsoft YaHei', 'SimHei', 'KaiTi', 'FangSong', 'SimSun',
        'PingFang SC', 'Hiragino Sans GB', 'Songti SC', 'STHeiti',
        'Heiti SC', 'Arial Unicode MS',
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
        _safe_print(f"  [FONT] 使用中文字体: {chosen}")
    else:
        plt.rcParams['font.sans-serif'] = ['DejaVu Sans']


setup_chinese_font()


# ======================== 1. 纵轴三种口径 ========================

METRIC_LABELS = {
    'peak_intensity': '峰强度',
    'peak_area': '峰面积',
    'at_wavelength': '指定波长处的值',
}

METRIC_ORDER = ('peak_intensity', 'peak_area', 'at_wavelength')


def integrate_band(wl, y, lo, hi):
    """梯形法计算 [lo, hi] 区间内的曲线下面积（GUI「光谱积分」用的是同一实现）。

    区间边界处对光谱做线性插值（避免半步长误差）；
    数据与区间无重叠、或区间无效时返回 NaN。
    """
    wl = np.asarray(wl, dtype=float)
    y = np.asarray(y, dtype=float)
    mask = np.isfinite(wl) & np.isfinite(y)
    wl, y = wl[mask], y[mask]
    if wl.size < 2 or not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        return float('nan')
    order = np.argsort(wl)
    wl, y = wl[order], y[order]
    grid_lo = max(float(lo), float(wl[0]))
    grid_hi = min(float(hi), float(wl[-1]))
    if grid_hi <= grid_lo:
        return float('nan')
    wg = np.concatenate(([grid_lo], wl[(wl > grid_lo) & (wl < grid_hi)], [grid_hi]))
    yg = np.interp(wg, wl, y)
    # numpy 2 起 trapz 更名为 trapezoid（兼容旧版）
    trapz = getattr(np, 'trapezoid', np.trapz)
    return float(trapz(yg, wg))


def measure_metric(wl, y, metric='peak_intensity', band=None, at_wl=None):
    """把一条光谱压成一个纵轴读数；算不出（区间无重叠等）返回 NaN。

    参数
    ----
    wl, y : array-like
        波长与强度/吸收值。
    metric : str
        ``peak_intensity``（区间内最大强度）/ ``peak_area``（区间积分）/
        ``at_wavelength``（指定波长处插值）。
    band : (lo, hi) | None
        峰强度 / 峰面积的波长区间；None 表示全谱（峰强度）或不适用（峰面积→NaN）。
    at_wl : float | None
        ``at_wavelength`` 用的波长；落在数据范围之外返回 NaN（不外推）。
    """
    wl = np.asarray(wl, dtype=float)
    y = np.asarray(y, dtype=float)
    mask = np.isfinite(wl) & np.isfinite(y)
    wl, y = wl[mask], y[mask]
    if wl.size == 0:
        return float('nan')

    if metric == 'peak_area':
        if not band:
            return float('nan')
        return integrate_band(wl, y, float(band[0]), float(band[1]))

    if metric == 'at_wavelength':
        if at_wl is None or not np.isfinite(float(at_wl)):
            return float('nan')
        x = float(at_wl)
        if x < float(wl.min()) or x > float(wl.max()):
            return float('nan')          # 不外推：范围外算不出
        return float(np.interp(x, wl, y))

    # peak_intensity（默认）
    if band:
        lo, hi = float(band[0]), float(band[1])
        sel = (wl >= lo) & (wl <= hi)
        if not sel.any():
            return float('nan')
        return float(np.nanmax(y[sel]))
    return float(np.nanmax(y))


def describe_metric(metric, band=None, at_wl=None):
    """纵轴标签文字，如 ``'峰强度 (560–620 nm)'`` / ``'A@450 nm'``。"""
    if metric == 'peak_area':
        if band:
            return f'峰面积 ({band[0]:g}–{band[1]:g} nm)'
        return '峰面积'
    if metric == 'at_wavelength':
        return f'指定波长处的值 ({at_wl:g} nm)' if at_wl is not None else '指定波长处的值'
    if band:
        return f'峰强度 ({band[0]:g}–{band[1]:g} nm)'
    return '峰强度 (全谱最大)'


# ======================== 2. 取点（含空值过滤） ========================

def _clean_var_value(raw):
    """把说明.xlsx 的变量值转成可比较的标量；空/非数值返回 None。

    文本形式的空值（``null`` / ``N/A`` / ``-`` 等）由 read_xlsx_info 统一清洗成
    空串，这里再把空串、NaN 一并返回 None —— 即"这个样品没有该变量的值"。
    """
    if raw is None:
        return None
    if isinstance(raw, str):
        s = raw.strip()
        return s if s else None
    try:
        if not np.isfinite(float(raw)):
            return None
    except (TypeError, ValueError):
        return str(raw) if str(raw).strip() else None
    return raw


def collect_points(samples, info, x_var, group_var=None, metric='peak_intensity',
                   band=None, at_wl=None, numbers=None):
    """把若干条光谱压成 ``(分组, x值, 指标值)`` 点集。

    参数
    ----
    samples : list[tuple]
        ``(显示名, 用于匹配编号的文件名, wl, y)`` 四元组；``wl``/``y`` 已是
        最终要测量的曲线（例如已扣过本底）。
    info : read_xlsx_info.XlsxInfo
        说明.xlsx 的结构化信息（``None`` 时全部样品都算缺变量）。
    x_var : str
        横轴变量列名（必须是数值列）。
    group_var : str | None
        分组变量列名；None = 不分组。
    metric, band, at_wl :
        见 :func:`measure_metric`。

    返回
    ----
    dict:
        ``points``  : list[(group, x, y, name, number)]，按 (组, x) 升序；
        ``skipped`` : list[(name, reason)]，缺变量 / 指标算不出的样品；
        ``x_var`` / ``group_var`` / ``metric`` : 原样回传，便于调用方拼标签。
    """
    nums = numbers if numbers is not None else (info.numbers if info else [])
    points, skipped = [], []
    for item in samples:
        name, match_name, wl, y = item[0], item[1], item[2], item[3]

        if not info or not nums:
            skipped.append((name, '没有说明.xlsx（无法取变量）'))
            continue
        try:
            num = match_number(match_name, nums)
        except Exception:
            num = None
        if num is None:
            skipped.append((name, '说明.xlsx 中匹配不到编号'))
            continue

        entry = info.entry_for(num)
        x_val = _clean_var_value(entry.get(x_var))
        if x_val is None:
            skipped.append((name, f'「{x_var}」为空'))
            continue
        try:
            x_num = float(x_val)
        except (TypeError, ValueError):
            skipped.append((name, f'「{x_var}」不是数值：{x_val!r}'))
            continue

        group = None
        if group_var:
            g_val = _clean_var_value(entry.get(group_var))
            if g_val is None:
                skipped.append((name, f'「{group_var}」为空'))
                continue
            group = g_val

        val = measure_metric(wl, y, metric=metric, band=band, at_wl=at_wl)
        if not np.isfinite(val):
            skipped.append((name, '该指标在当前波长范围内算不出'))
            continue
        points.append((group, x_num, float(val), str(name), num))

    points.sort(key=lambda p: (str(p[0]) if p[0] is not None else '', p[1]))
    return {'points': points, 'skipped': skipped, 'x_var': x_var,
            'group_var': group_var, 'metric': metric}


def group_points(points):
    """把点按分组归类：返回 ``[(组标签, [(x, y, name, number), ...]), ...]``。

    不分组（group 全为 None）时返回单个组，标签为 ``None``。
    """
    groups = {}
    for group, x, y, name, num in points:
        groups.setdefault(group, []).append((x, y, name, num))
    out = []
    for key in sorted(groups, key=lambda k: (k is None, _num_or_str(k))):
        rows = sorted(groups[key], key=lambda r: r[0])
        out.append((key, rows))
    return out


def _num_or_str(v):
    """分组排序键：数值优先按数值排，字符串按字典序。"""
    try:
        return (0, float(v))
    except (TypeError, ValueError):
        return (1, str(v))


# ======================== 3. 画图 ========================

def make_compare_figure(points, x_label, y_label, title,
                        linewidth=1.5, marker='o', markersize=5,
                        color_map=None, colors=None, figsize=(7.2, 4.6),
                        dpi=150, log_x=False, annotate=False,
                        legend_prefix=None, fig=None):
    """按点集画「指标 - 变量」点线图，返回 ``(fig, summary)``。

    ``summary`` = ``{'groups': [(组标签, 点数), ...], 'n_points': n}``。
    ``colors`` 给了颜色列表就按顺序取；``color_map`` 是 matplotlib 色带
    （GUI 的「颜色方案」），交由 curve_colors.CurveColors 按组标签稳定分配。
    ``legend_prefix`` 给分组变量名时，图例写成 ``L8i浓度=1000`` 而不是光秃秃的
    ``1000``。``fig`` 传入现成画布（GUI 的「数据比较」页）时就在它上面重画，
    不再新建 figure。多条曲线（分组）时图例在轴外右上；单条曲线时图例给出样品数。
    """
    from curve_colors import CurveColors

    if fig is None:
        fig, ax = plt.subplots(figsize=figsize, dpi=dpi)
    else:
        fig.clf()
        ax = fig.add_subplot(111)
    grouped = group_points(points)
    n_points = len(points)

    # 颜色：显式给了列表就按顺序取；否则用 CurveColors 按**组标签**稳定分配
    # （同一组在增删样品后颜色不变，和合并图的取色规则一致）
    assigner = None if colors is not None else CurveColors()

    def _color(i, label):
        if colors is not None:
            return colors[i % len(colors)]
        return assigner.get(label, color_map)

    for i, (key, rows) in enumerate(grouped):
        xs = [r[0] for r in rows]
        ys = [r[1] for r in rows]
        if key is None:
            label = f'全部样品（{len(rows)} 个）'
        elif legend_prefix:
            label = f'{legend_prefix}={key}'
        else:
            label = f'{key}'
        color = _color(i, label)

        # v5.0.2：同一 x 上重复测量的点**不要用折线顺序连起来**。
        # 原实现直接 ax.plot(xs, ys)：05 数据 12 个点只落在 3 个 x 值上
        # （x=10 有 6 个点、20 有 3 个、50 有 3 个），折线把这些同 x 的点按
        # 读入顺序串起来，在图上画出一条条**竖直的"假趋势"**，看起来像
        # 数据在某个浓度上下剧烈跳动，实际只是重复测量的离散。
        # 现在：不排序、按 x 聚合，画「均值 ± 标准差」误差棒，原始点仍以
        # 散点叠在同样的位置（不丢信息，但不再伪造趋势线）。
        agg = {}
        for x, y in zip(xs, ys):
            if not (np.isfinite(x) and np.isfinite(y)):
                continue
            agg.setdefault(x, []).append(y)
        has_replicates = any(len(v) > 1 for v in agg.values())
        if has_replicates:
            ux = sorted(agg)
            uy = [float(np.mean(agg[x])) for x in ux]
            ue = [float(np.std(agg[x], ddof=1)) if len(agg[x]) > 1 else 0.0
                  for x in ux]
            ax.errorbar(ux, uy, yerr=ue, marker=marker,
                        markersize=markersize, linewidth=linewidth,
                        capsize=3, color=color, label=label,
                        elinewidth=0.9, alpha=0.95)
            # 原始点淡色叠在均值位置上，保留逐点离散（重复测量多时看得出散布）
            ax.plot(xs, ys, linestyle='none', marker=marker,
                    markersize=max(markersize * 0.55, 2.0), color=color,
                    alpha=0.35, markeredgewidth=0)
        else:
            ax.plot(xs, ys, marker=marker, markersize=markersize,
                    linewidth=linewidth, color=color, label=label)
        if annotate:
            for x, y, name, _num in rows:
                ax.annotate(str(name), xy=(x, y), xytext=(4, 4),
                            textcoords='offset points', fontsize=8, color=color)

    if log_x and all(p[1] > 0 for p in points):
        ax.set_xscale('log')
    ax.set_xlabel(x_label)
    ax.set_ylabel(y_label)
    ax.set_title(title, fontsize=13)
    ax.grid(True, linestyle='--', alpha=0.35)

    # v5.0.2：纵轴量级大时用科学刻度。峰面积量级可到 3.8×10⁵，原图上 tick
    # 直接写「383400」这类 6 位数，读数容易错位；改成「3.8」+ 顶部 ×10⁵ 偏移。
    try:
        _ys = [abs(float(r[1])) for _k, _rows in grouped for r in _rows
               if np.isfinite(r[1])]
        if _ys and max(_ys) >= 1e5:
            from matplotlib.ticker import ScalarFormatter
            fmt = ScalarFormatter(useMathText=True)
            fmt.set_powerlimits((-3, 4))
            ax.yaxis.set_major_formatter(fmt)
            ax.yaxis.get_offset_text().set_fontsize(9)
    except Exception:
        pass

    if n_points:
        ax.legend(fontsize=8, frameon=False, loc='upper left',
                  bbox_to_anchor=(1.01, 1.0))
        fig.subplots_adjust(left=0.12, right=0.80, top=0.90, bottom=0.16)
    else:
        # v5.0.2：空图也要恢复正常边距。MplCanvas 初始把边距设成 0
        # （提示文字铺满用），不恢复的话 xlabel/ylabel/title 会被算到画布外，
        # 触发大量越界 bbox 计算（实测 top +23px、left -51px）。
        fig.subplots_adjust(left=0.12, right=0.97, top=0.90, bottom=0.16)
        ax.text(0.5, 0.5, '没有可画的样品\n（检查说明.xlsx 的变量与勾选情况）',
                transform=ax.transAxes, ha='center', va='center',
                fontsize=13, color='#64748b', wrap=True)
        ax.set_axis_off()
    summary = {'groups': [(k, len(v)) for k, v in grouped if v],
               'n_points': n_points}
    # v5.0.2：把重复测量聚成的浓度点数与各点重复次数报出来，
    # 状态栏才能说明「N 个样品聚成 M 个点，误差棒 = 标准差」
    try:
        _all_agg = {}
        for _g, _rows in grouped:
            for _x, _y in ((r[0], r[1]) for r in _rows):
                if np.isfinite(_x) and np.isfinite(_y):
                    _all_agg.setdefault(_x, []).append(_y)
        if _all_agg:
            summary['aggregated'] = {
                'n_unique_x': len(_all_agg),
                'has_replicates': any(len(v) > 1 for v in _all_agg.values()),
                'replicates': {k: len(v) for k, v in sorted(_all_agg.items())},
            }
    except Exception:
        pass
    return fig, summary


def save_figure(fig, path, dpi=None):
    """保存图片（自动建目录），返回保存路径。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=EXPORT_DPI_DEFAULT if dpi is None else dpi,
                bbox_inches='tight')
    return path


def points_to_csv(points, x_var, metric_label, path):
    """把点集写成 CSV（UTF-8 BOM，Excel 直接打开不乱码）。"""
    import csv
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['样品', '编号', x_var, '分组', metric_label])
        for group, x, y, name, num in points:
            w.writerow([name, num, f'{x:g}', '' if group is None else group, f'{y:.6g}'])
    return path


# ======================== 4. 数据可比性预检（v5.0.6） ========================

# 检查级别的严重度（数字越大越严重），供排序与 UI 配色用
_SEV_RANK = {'info': 0, 'warn': 1, 'error': 2}


def _fmt_num(v, unit=''):
    """把元数据值格式化成短字符串；None 显示「未声明」。"""
    if v is None:
        return '未声明'
    try:
        s = f'{float(v):g}'
    except (TypeError, ValueError):
        s = str(v)
    return f'{s}{unit}' if unit else s


def check_comparability(samples, headers=None, group_of=None, kind='emission',
                        peak_tol_nm=20.0, scatter_tol_nm=15.0,
                        completeness_tol=0.01):
    """检查一批光谱**能不能放在一起求均值**（v5.0.6）。

    为什么需要它
    ------------
    ``说明.xlsx`` 只给编号（R1/R2/S1…），同编号的多个 CSV 会被自动当成
    "同一条件的平行测量"，画成均值 ± 标准差。但现实里同编号的文件常常
    **不是**同一种测量。实测 ``示例数据/05-数据比较-浓度梯度`` 的 x=10 一组
    6 个文件，其中 4 个各有一类问题：

        R1.csv      header 声明 320–800nm/0.5nm（应 961 点），实际只有 294 点（截断）
        R1.csv      带宽 3.0 nm，其余 5 个是 5.0 nm
        R1-3.csv    激发波长 650 nm，其余 5 个是 520 nm
        R1-5/6.csv  全谱最大点紧贴 EX（Δ≈−1nm）→ 峰强取到了瑞利散射峰

    软件把它们统一算成 mean=11706.9 / RSD=55.5%，用户的全部信息只有一句
    「12 个样品 → 3 个点」。而**Grubbs 离群检验抓不到**：实测 G=1.78 < 临界
    1.887（离群点自己把 SD 撑大了，这是单变量离群检验的经典盲区）。
    必须靠「测量条件元数据 + 谱形一致性」判断，不能靠数值统计。

    参数
    ----
    samples : list
        每条为 ``(显示名, 文件名, wl, y)`` 或带更多字段的 tuple/dict。
        只需要 ``wl`` 与 ``y``（用来做谱形与散射检查）。
    headers : dict | None
        ``{文件名: read_measurement_header() 的结果}``。给了才做元数据/完整性
        两项检查；为 None 时只做谱形与散射检查。
    group_of : callable | None
        ``group_of(文件名) -> 分组键``（通常是说明.xlsx 的编号）。
        为 None 时全部算同一组。
    kind : str
        ``'emission'`` 时做散射检查（用 EX 波长），``'absorption'`` 时跳过。
    peak_tol_nm : float
        组内峰位偏离中位数超过该值 → 判为"谱形不一致"。
    scatter_tol_nm : float
        全谱最大点距 EX 小于该值 → 判为"峰强可能取到散射峰"。
    completeness_tol : float
        实际点数比声明点数少超过该比例 → 判为"扫描被截断"。

    返回
    ----
    dict::

        {'issues':    [{'level', 'code', 'title', 'detail', 'samples'}, ...],
         'groups':    {组键: {'n', 'issues': [...], 'comparable_n'}},
         'n_ok':      可比的样品数,
         'n_flagged': 被标记的样品数,
         'summary':   一行中文结论}

    每个 issue 的 ``level`` 取 ``'error'``（不该参与平均）/ ``'warn'``
    （可以平均但要记着）/ ``'info'``（仅提示）。
    """
    issues = []
    samples = list(samples or [])

    def _parts(s):
        """把 sample 统一成 (name, filename, wl, y)。"""
        if isinstance(s, dict):
            wl = s.get('wl', s.get('wavelength'))
            y = s.get('y', s.get('intensity', s.get('absorption')))
            return (s.get('name') or s.get('label') or '',
                    s.get('file') or s.get('filename') or '', wl, y)
        name = s[0] if len(s) > 0 else ''
        fname = s[1] if len(s) > 1 else ''
        wl = s[2] if len(s) > 2 else None
        y = s[3] if len(s) > 3 else None
        return name, fname, wl, y

    norm = [_parts(s) for s in samples]
    if not norm:
        return {'issues': [], 'groups': {}, 'n_ok': 0, 'n_flagged': 0,
                'summary': '没有样品可检查'}

    def _grp(fname, name):
        if group_of is None:
            return None
        try:
            return group_of(fname or name)
        except Exception:
            return None

    groups = {}
    for name, fname, wl, y in norm:
        groups.setdefault(_grp(fname, name), []).append((name, fname, wl, y))

    flagged = set()         # 被标为 error 的样品名（用于算 comparable_n）

    def _add(level, code, title, detail, who):
        issues.append({'level': level, 'code': code, 'title': title,
                       'detail': detail, 'samples': list(who)})
        if level == 'error':
            flagged.update(who)

    # ---------- ① 元数据一致性（同组内测量条件必须相同） ----------
    if headers:
        fields = [('ex_wl', '激发波长', ' nm'),
                  ('em_bw', '发射带宽', ' nm'),
                  ('ex_bw', '激发带宽', ' nm'),
                  ('em_start', '扫描起点', ' nm'),
                  ('em_end', '扫描终点', ' nm'),
                  ('interval', '数据间隔', ' nm')]
        for gkey, members in groups.items():
            if len(members) < 2:
                continue
            for fkey, label, unit in fields:
                vals = {}
                for _n, fname, _wl, _y in members:
                    h = headers.get(fname) or {}
                    v = h.get(fkey)
                    if v is None:
                        continue
                    vals.setdefault(_fmt_num(v, unit), []).append(fname)
                if len(vals) < 2:
                    continue
                # 多数派 = 出现次数最多的取值
                major = max(vals.items(), key=lambda kv: len(kv[1]))
                odd = [fn for val, fns in vals.items() if val != major[0]
                       for fn in fns]
                if not odd:
                    continue
                detail = ('同一编号（' + str(gkey) + '）下的文件'
                          + f'{label}不一致：多数为 {major[0]}'
                          + f'（{len(major[1])} 个），'
                          + '；'.join(f'{val}（{", ".join(fns)}）'
                                      for val, fns in vals.items()
                                      if val != major[0])
                          + '。条件不同的测量不能当作平行样平均。')
                _add('error', 'meta_' + fkey, f'{label}不一致', detail, odd)

    # ---------- ② 数据完整性（声明点数 vs 实际点数） ----------
    if headers:
        for name, fname, wl, _y in norm:
            h = headers.get(fname) or {}
            start, end, step = h.get('em_start'), h.get('em_end'), h.get('interval')
            if not (start is not None and end is not None and step
                    and float(step) > 0 and float(end) > float(start)):
                continue
            try:
                expect = int(round((float(end) - float(start)) / float(step))) + 1
            except (TypeError, ValueError, ZeroDivisionError):
                continue
            try:
                actual = int(np.asarray(wl, float).size)
            except Exception:
                continue
            if expect <= 0 or actual <= 0:
                continue
            missing = 1.0 - actual / expect
            if missing > completeness_tol:
                detail = (f'文件头声明 {_fmt_num(start, " nm")}–'
                          f'{_fmt_num(end, " nm")}、步长 {_fmt_num(step, " nm")}，'
                          f'应为 {expect} 点，实际只有 {actual} 点'
                          f'（缺 {missing * 100:.0f}%）。'
                          '扫描被截断时数据"是真的但残缺"，'
                          '区间积分与峰面积会整体偏小，'
                          '而且不会报任何错。')
                _add('error', 'truncated', '扫描数据不完整', detail, [fname])

    # ---------- ③ 谱形一致性（同组峰位不能差太远） ----------
    # 判据说明：只在**多数派内部**找离群，而不是把整组中位数当基准。
    # 早期实现用「组内中位数」，实测在 05 数据的 R1 组上误报 6 个文件：
    # 该组谱形分成两派（570 nm 与 519 nm 各一半），中位数落在两派之间的
    # 544.5 nm，于是**两派都被判偏离**——真正该标的是少数派，不是所有人。
    for gkey, members in groups.items():
        if len(members) < 3:          # 少于 3 个无法区分多数派/少数派
            continue
        peaks = {}
        for name, fname, wl, y in members:
            try:
                arr_wl = np.asarray(wl, float)
                arr_y = np.asarray(y, float)
                if arr_wl.size == 0 or arr_wl.size != arr_y.size:
                    continue
                finite = np.isfinite(arr_y)
                if not finite.any():
                    continue
                i = int(np.nanargmax(np.where(finite, arr_y, -np.inf)))
                peaks[fname] = float(arr_wl[i])
            except Exception:
                continue
        if len(peaks) < 3:
            continue
        med = float(np.median(list(peaks.values())))
        # 先取「距中位数最近的那一批」当参考簇，再找偏离参考簇的点
        near = {fn: p for fn, p in peaks.items() if abs(p - med) <= peak_tol_nm}
        if len(near) < 2:
            # 两派各占一半、谁都不在容差内：用最密的一派（按 2×tol 聚类）
            buckets = {}
            for fn, p in peaks.items():
                key = int(round(p / (2 * peak_tol_nm)))
                buckets.setdefault(key, []).append(fn)
            biggest = max(buckets.values(), key=len)
            if len(biggest) < 2 or len(biggest) == len(peaks):
                continue
            ref_med = float(np.median([peaks[fn] for fn in biggest]))
            near = {fn: peaks[fn] for fn in biggest}
        else:
            ref_med = float(np.median(list(near.values())))
        odd = [fn for fn, p in peaks.items()
               if fn not in near and abs(p - ref_med) > peak_tol_nm]
        if not odd:
            continue
        detail = ('同一编号（' + str(gkey) + '）下的文件谱形不一致：'
                  f'{len(near)} 个文件的峰位集中在 {ref_med:.1f} nm，'
                  + '；'.join(f'{fn} 却在 {peaks[fn]:.1f} nm'
                              f'（偏离 {peaks[fn] - ref_med:+.1f} nm）'
                              for fn in odd)
                  + f'。偏离超过 ±{peak_tol_nm:g} nm 通常意味着测的不是同一个东西'
                    '（激发波长不同 / 样品不同 / 串了别的谱），'
                    '不该当作同一条件的平行样。')
        _add('error', 'peak_shift', '谱形不一致（峰位）', detail, odd)

    # ---------- ④ 散射污染（发射谱：峰强是否取到了散射/拉曼峰） ----------
    # 两类都要报，但成因不同、修法也不同：
    #   · 瑞利线：峰位几乎压着 EX（实测 R1-5/R1-6 在 EX−1.0/−1.5 nm）；
    #   · 拉曼/散射带：峰位在 EX 之后十几 nm，且**是一条有宽度的带**
    #     （实测 S3/S4 系列在 EX+13.5~14.5 nm、半高宽约 23 nm、
    #      强度 9.3~11.6 万，而荧光区只有 1.4~1.7 万——是散射带不是荧光）。
    # 只看"距 EX < 15 nm"会把后者当成宽度为零的瑞利线，也把 EX+13 这种
    # 真实散射带误判成"紧贴"；所以两者合并成一个「贴近 EX 的强带」判据，
    # 但按距离给不同措辞。
    if kind == 'emission' and headers:
        scatter_hits = []          # [(fname, peak_wl, ex, delta, ratio)]
        for name, fname, wl, y in norm:
            h = headers.get(fname) or {}
            ex = h.get('ex_wl')
            if ex is None:
                continue
            try:
                arr_wl = np.asarray(wl, float)
                arr_y = np.asarray(y, float)
                if arr_wl.size == 0 or arr_wl.size != arr_y.size:
                    continue
                finite = np.isfinite(arr_y)
                if not finite.any():
                    continue
                arr_y = np.where(finite, arr_y, -np.inf)
                i = int(np.argmax(arr_y))
                peak_wl = float(arr_wl[i])
                delta = peak_wl - float(ex)
            except Exception:
                continue
            if abs(delta) > scatter_tol_nm:
                continue
            try:
                far = arr_wl > float(ex) + 40.0
                fluor = float(arr_y[far].max()) if far.any() else float('nan')
            except Exception:
                fluor = float('nan')
            ratio = (arr_y[i] / fluor) if np.isfinite(fluor) and fluor > 0 else float('nan')
            scatter_hits.append((fname, peak_wl, float(ex), delta, ratio, fluor))

        # 按 (成因类型, EX 波长) 归类合并：S3/S4 各 4 个文件其实是同一件事，
        # 逐个报 8 条会把信息页刷满，反而不容易看出「这批全中招了」。
        buckets = {}
        for hit in scatter_hits:
            fname, peak_wl, ex, delta, ratio, fluor = hit
            tag = 'rayleigh' if abs(delta) <= 3.0 else 'raman'
            buckets.setdefault((tag, round(ex, 1)), []).append(hit)

        for (tag, ex), hits in sorted(buckets.items()):
            fnames = [h[0] for h in hits]
            deltas = [h[3] for h in hits]
            peaks = [h[1] for h in hits]
            ratios = [h[4] for h in hits if np.isfinite(h[4])]
            fluor = hits[0][5]
            d_lo, d_hi = min(deltas), max(deltas)
            d_txt = (f'{d_lo:+.1f}' if abs(d_hi - d_lo) < 0.2
                     else f'{d_lo:+.1f} ~ {d_hi:+.1f}')
            if tag == 'rayleigh':
                cause = '几乎压在激发波长上，是瑞利（激发）散射线'
            else:
                cause = ('落在激发波长之后十几 nm，通常对应溶剂拉曼峰'
                         '（水的 Raman 位移约 3350 cm⁻¹）或杂散散射带')
            ratio_txt = ''
            if ratios:
                r_lo, r_hi = min(ratios), max(ratios)
                r_txt = (f'{r_lo:.1f}' if abs(r_hi - r_lo) < 0.15
                         else f'{r_lo:.1f}~{r_hi:.1f}')
                ratio_txt = (f'它的强度是荧光区最大值（约 {fluor:.0f}）的 '
                             f'{r_txt} 倍，')
            detail = (f'{len(fnames)} 个文件的全谱最大点都落在 '
                      f'{min(peaks):.1f}–{max(peaks):.1f} nm，'
                      f'距激发波长 {ex:g} nm 为 {d_txt} nm——{cause}。'
                      + ratio_txt
                      + '「峰强度（全谱最大）」会把它们当成发光强度，'
                        '做浓度标定时斜率是错的，而图上看不出异常。'
                        f'建议纵轴口径改成「指定区间内的最大值」，'
                        f'区间下限取 {ex + 30:g} nm 之后。')
            _add('warn', 'scatter_' + tag, '峰强可能取到散射/拉曼峰',
                 detail, fnames)

    # ---------- 汇总 ----------
    all_names = set()
    for name, fname, _wl, _y in norm:
        all_names.add(fname or name)
    flagged = {f for f in flagged if f in all_names}

    by_group = {}
    for gkey, members in groups.items():
        gfiles = {fn or nm for nm, fn, _w, _y in members}
        g_issues = [it for it in issues if gfiles & set(it['samples'])]
        bad = set()
        for it in g_issues:
            if it['level'] == 'error':
                bad |= (gfiles & set(it['samples']))
        by_group[str(gkey)] = {
            'n': len(members),
            'issues': g_issues,
            'comparable_n': len(members) - len(bad),
        }

    n_err = sum(1 for it in issues if it['level'] == 'error')
    n_warn = sum(1 for it in issues if it['level'] == 'warn')
    if not issues:
        summary = f'{len(all_names)} 个样品通过可比性检查（未发现条件差异）'
    else:
        bits = []
        if n_err:
            bits.append(f'{n_err} 项会影响结论（error）')
        if n_warn:
            bits.append(f'{n_warn} 项需留意（warn）')
        summary = (f'{len(all_names)} 个样品中发现 {len(issues)} 个可比性问题：'
                   + '，'.join(bits) + f'；{len(flagged)} 个样品存在条件差异')
    return {'issues': issues, 'groups': by_group,
            'n_ok': len(all_names) - len(flagged),
            'n_flagged': len(flagged), 'summary': summary}


def format_comparability_report(result, max_detail=6):
    """把 check_comparability() 的结果排成给人看的纯文本（供 GUI 信息页/日志）。

    ``max_detail`` 限制最多展开几项（其余只报个数），避免信息页被几十条
    「带宽不一致」刷屏——同一种问题常常每个文件各报一条。
    """
    if not result or not result.get('issues'):
        return (result or {}).get('summary', '') or '未发现问题'
    lines = [result.get('summary', ''), '']
    order = {'error': 0, 'warn': 1, 'info': 2}
    mark = {'error': '❌', 'warn': '⚠️', 'info': 'ℹ️'}
    shown = 0
    for it in sorted(result['issues'], key=lambda x: order.get(x['level'], 9)):
        if shown >= max_detail:
            break
        lines.append(f"{mark.get(it['level'], '')} {it['title']}")
        lines.append(f"   涉及：{', '.join(it['samples'])}")
        lines.append(f"   {it['detail']}")
        lines.append('')
        shown += 1
    if len(result['issues']) > shown:
        lines.append(f"… 另有 {len(result['issues']) - shown} 项未展开")
    return '\n'.join(lines).rstrip()


# ======================== 5. 一键 / 命令行 ========================

def _load_spectra(files, kind='emission'):
    """懒加载光谱（避免模块导入就拉起绘图模块）。返回 [(显示名, 文件名, wl, y)]。"""
    samples = []
    if kind == 'absorption':
        from plot_absorption import load_absorption_spectra
        for fp in files:
            try:
                data = load_absorption_spectra(fp, skip_metadata=True, verbose=False)
            except Exception as e:
                _safe_print(f'  [SKIP] {Path(fp).name}: {e}')
                continue
            for d in data or []:
                wl = d.get('wavelength', d.get('wl'))
                y = d.get('absorption', d.get('intensity'))
                if wl is None or y is None:
                    continue
                samples.append((Path(fp).stem, Path(fp).name,
                                np.asarray(wl, float), np.asarray(y, float)))
    else:
        from plot_emission import load_spectra
        for d in load_spectra(list(files), verbose=False):
            wl = d.get('wavelength', d.get('wl'))
            y = d.get('intensity', d.get('absorption'))
            if wl is None or y is None:
                continue
            name = d.get('label') or d.get('name') or 'spectrum'
            samples.append((str(name), str(d.get('path') or name),
                            np.asarray(wl, float), np.asarray(y, float)))
    return samples


def run_compare(folder=None, files=None, x_var=None, group_var=None,
                metric='peak_intensity', band=None, at_wl=None,
                kind='emission', save_dir='./plots', name=None,
                figsize=(7.2, 4.6), dpi=None, verbose=True,
                y_label=None, legend_prefix=None):
    """一键：读光谱 + 读说明.xlsx + 取点 + 画图 + 存盘。

    ``folder`` 给文件夹（自动找 ``说明.xlsx`` 与所有 CSV/TXT），也可直接给
    ``files`` 列表。``x_var=None`` 时自动取说明.xlsx 的第一个数值列。
    返回 ``dict(figure, csv, points, skipped, summary, x_var, ...)``。
    """
    if folder is not None:
        folder = Path(folder)
        files = sorted(glob.glob(str(folder / '*.csv')) + glob.glob(str(folder / '*.txt')))
    files = [str(f) for f in (files or [])]
    if not files:
        raise ValueError('没有可用的光谱文件（folder/files 都没给）')

    info = load_xlsx_info(folder) if folder is not None else None
    if info is None and verbose:
        _safe_print('  [WARN] 没找到/读不出 说明.xlsx，无法取横轴变量')

    if x_var is None and info is not None:
        cols = numeric_columns(info)
        if not cols:
            raise ValueError('说明.xlsx 里没有数值列可作横轴变量')
        x_var = cols[0]
        if verbose:
            _safe_print(f'  [INFO] 未指定 --x，自动使用第一个数值列：{x_var}')

    samples = _load_spectra(files, kind=kind)
    res = collect_points(samples, info, x_var, group_var=group_var,
                         metric=metric, band=band, at_wl=at_wl)
    x_label = x_var or '变量'
    y_label = y_label or describe_metric(metric, band, at_wl)
    title = name or f'{y_label} - {x_label}'
    if group_var:
        title += f'（按 {group_var} 分组）'
    fig, summary = make_compare_figure(res['points'], x_label, y_label, title,
                                       figsize=figsize,
                                       legend_prefix=legend_prefix or group_var)
    stem = f"compare_{x_label}_{metric}"
    fig_path = save_figure(fig, Path(save_dir) / f'{stem}.png', dpi=dpi)
    csv_path = points_to_csv(res['points'], x_label, y_label,
                             Path(save_dir) / f'{stem}.csv')
    if verbose:
        _safe_print(f'  [OK] {summary["n_points"]} 个样品 → {fig_path}')
        for nm, why in res['skipped']:
            _safe_print(f'  [SKIP] {nm}: {why}')
    plt.close(fig)
    out = dict(res)
    out.update({'figure': str(fig_path), 'csv': str(csv_path),
                'summary': summary, 'samples': len(samples)})
    return out


def numeric_columns(info):
    """说明.xlsx 里可作横轴/分组的数值列（至少一个非空数值）。

    优先用 ``XlsxInfo.numeric_columns()``；老版本对象没有该方法时自己扫一遍。
    """
    if info is None:
        return []
    if hasattr(info, 'numeric_columns'):
        return list(info.numeric_columns())
    cols = []
    for col in getattr(info, 'columns', []):
        vals = []
        for _num, entry in info.info.items():
            v = entry.get(col)
            try:
                vals.append(float(v))
            except (TypeError, ValueError):
                continue
        if vals:
            cols.append(col)
    return cols


def main(argv=None):
    ap = argparse.ArgumentParser(
        description='光谱「强度-变量」相关性点线图（读同目录 说明.xlsx 取变量）')
    ap.add_argument('folder', help='数据文件夹（含 说明.xlsx 与 CSV/TXT）')
    ap.add_argument('--x', default=None, help='横轴变量列名（缺省用第一个数值列）')
    ap.add_argument('--group', default=None, help='分组变量列名（可选）')
    ap.add_argument('--metric', default='peak_intensity',
                    choices=list(METRIC_ORDER),
                    help='纵轴口径：峰强度 / 峰面积 / 指定波长处的值')
    ap.add_argument('--band', nargs=2, type=float, default=None,
                    metavar=('LO', 'HI'), help='峰强度/峰面积的区间（nm）')
    ap.add_argument('--at', type=float, default=None, help='at_wavelength 用的波长（nm）')
    ap.add_argument('--kind', default='emission', choices=['emission', 'absorption'])
    ap.add_argument('--save-dir', default='./plots')
    ap.add_argument('--list-vars', action='store_true', help='只列出可用的数值列')
    args = ap.parse_args(argv)

    if args.list_vars:
        info = load_xlsx_info(args.folder)
        if info is None:
            _safe_print('没找到/读不出 说明.xlsx')
            return 1
        _safe_print(f'说明.xlsx: {info.path}')
        for c in numeric_columns(info):
            _safe_print(f'  数值列: {c}')
        return 0

    band = tuple(args.band) if args.band else None
    out = run_compare(folder=args.folder, x_var=args.x, group_var=args.group,
                      metric=args.metric, band=band, at_wl=args.at,
                      kind=args.kind, save_dir=args.save_dir)
    _safe_print(f"完成：{out['summary']['n_points']} 个点，跳过 {len(out['skipped'])} 个")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
