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

        entry = info.info.get(int(num), {})
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
        points.append((group, x_num, float(val), str(name), int(num)))

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
    if n_points:
        ax.legend(fontsize=8, frameon=False, loc='upper left',
                  bbox_to_anchor=(1.01, 1.0))
        fig.subplots_adjust(left=0.12, right=0.80, top=0.90, bottom=0.16)
    else:
        ax.text(0.5, 0.5, '没有可画的样品\n（检查说明.xlsx 的变量与勾选情况）',
                transform=ax.transAxes, ha='center', va='center',
                fontsize=13, color='#64748b', wrap=True)
        ax.set_axis_off()
    summary = {'groups': [(k, len(v)) for k, v in grouped if v],
               'n_points': n_points}
    return fig, summary


def save_figure(fig, path, dpi=300):
    """保存图片（自动建目录），返回保存路径。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=dpi, bbox_inches='tight')
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


# ======================== 4. 一键 / 命令行 ========================

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
                figsize=(7.2, 4.6), dpi=300, verbose=True,
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
