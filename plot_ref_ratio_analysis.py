# -*- coding: utf-8 -*-
"""
参照比值分析：以参照物峰值为内标，对浓度系列做局部放大 / 找峰 / 归一化浓度图
================================================================================
封装通用分析绘图能力（不绑定具体体系——换参照物、换待测物用法不变）：
  1. 单独光谱图（多光谱数据逐条成图，可选）：plot_individual
  2. 合并光谱图（默认 300-500 nm 局部放大），参照物自动标注为 "RB（参照）"：
     plot_combined_zoom
  3. 指定区间（默认 400-500 nm）峰值查找 + 峰表 CSV 导出：export_peak_table
  4. 以参照物峰值作为 1 归一化，作浓度图：plot_rb_normalized_concentration

历史说明（v5.0.0）：本模块原名 plot_zn_rb_analysis，因旧名把两个具体化学品
（Zn / RB）写进了文件名、与"通用能力"不符而改名；**公开函数名一律未改**
（analyze_zn_rb_folder 等），旧调用方只需改 import 的模块名即可。

【多光谱数据直接引用函数】
  具有多个光谱数据时：
    - 单独图：plot_individual(datasets, out_dir, ...) 逐条各画一张
    - 合并图：plot_combined_zoom(datasets, out_path, ...) 合并局部放大
    - 一键全出（含单独图）：analyze_zn_rb_folder(..., individual=True)
  也可直接用 plot_emission 的 plot_spectra / plot_combined 画合并图。

激发光谱（Spectrum Type=Excitation）默认跳过，不参与绘图与峰表。

典型调用（一键完成三张输出，加 individual=True 再多出每条单独图）：
    from plot_zn_rb_analysis import analyze_zn_rb_folder
    analyze_zn_rb_folder(
        data_dir=r"...\\20260731",
        out_dir=r"...\\20260731\\plots_emission",
        samples=[
            {"file": "RB.csv",   "name": "RB",   "zn_conc": 0.0},
            {"file": "Zn-5.csv", "name": "Zn-5", "zn_conc": 100.0},
            {"file": "Zn-6.csv", "name": "Zn-6", "zn_conc": 50.0},
            {"file": "Zn-7.csv", "name": "Zn-7", "zn_conc": 500.0},
        ],
        individual=True,          # 同时输出每条单独图 + 合并图
    )

也可单独调用 plot_individual / plot_combined_zoom / export_peak_table /
plot_rb_normalized_concentration，见各函数 docstring。
"""

import sys
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.signal import find_peaks

sys.path.insert(0, str(Path(__file__).resolve().parent))
from plot_emission import (  # noqa: E402
    parse_rf6000_csv,
    plot_single,
    setup_chinese_font,
)

setup_chinese_font()


# ======================== 默认配色 ========================
DEFAULT_COLORS = {
    'RB': 'black',
    'Zn-5': '#d62728',
    'Zn-6': '#ff7f0e',
    'Zn-7': '#2ca02c',
    'Zn-8': '#8c564b',
    'Zn-1': '#1f77b4',
    'Zn-2': '#9467bd',
    'Zn-3': '#17becf',
    'Zn-4': '#bcbd22',
}


def _color_for(name, idx=0):
    if name in DEFAULT_COLORS:
        return DEFAULT_COLORS[name]
    return plt.cm.tab10(idx % 10)


def _label_of(sample):
    """显示名：RB 固定为 RB（参照）；Zn 样品带说明.xlsx 全部信息。"""
    name = sample['name']
    if sample.get('label'):
        return sample['label']
    if name == 'RB':
        return 'RB（参照）'
    parts = []
    zn = sample.get('zn_conc')
    if zn is not None:
        parts.append(f'ZnPcS4={zn:.0f} μM')
    l8i = sample.get('l8i')
    if l8i is not None:
        parts.append(f'L8i={l8i:.0f} μM')
    cpc = sample.get('cpc')
    if cpc is not None:
        parts.append(f'CPC={cpc:.0f} μM')
    if not parts:
        return name
    label = f"{name}（{', '.join(parts)}"
    note = sample.get('note')
    if note:
        label += f"，{note}"
    return label + '）'


def read_zn_info(excel_path, num_col='编号', zn_col='ZnPcS4浓度',
                 l8i_col='L8i浓度', cpc_col='CPC浓度', note_col='备注'):
    """读取 说明.xlsx，返回 {编号: {zn_conc, l8i, cpc, note}}。

    可直接展开进 samples 字典使用，例如：
        info = read_zn_info(DATA_DIR / '说明.xlsx')
        {'file': 'Zn-5.csv', 'name': 'Zn-5', **info[5]}
    """
    df = pd.read_excel(excel_path, header=0)
    info = {}
    for _, r in df.iterrows():
        num = int(r[num_col])
        note = r.get(note_col, '')
        note = str(note).strip() if pd.notna(note) else ''
        if note.lower() == 'nan':
            note = ''
        info[num] = {
            'zn_conc': float(r[zn_col]),
            'l8i': float(r[l8i_col]),
            'cpc': float(r[cpc_col]),
            'note': note,
        }
    return info


# ======================== 1. 数据加载 ========================
def load_emission_datasets(data_dir, samples, skip_excitation=True):
    """按 samples 列表加载 CSV，跳过激发光谱。

    参数
    ----
    data_dir : str/Path
        数据文件夹；samples 里的 file 相对于该目录。
    samples : list[dict]
        每个元素至少含 file、name；可选 zn_conc / l8i / cpc / note
        （说明.xlsx 信息，用于图例）或 label（完全自定义显示名）。
    skip_excitation : bool
        是否跳过 Spectrum Type=Excitation 的文件（默认跳过）。

    返回
    ----
    list[dict]：每个元素含
        name, label, zn_conc, wl, intensity, ex, stype, file
    """
    data_dir = Path(data_dir)
    datasets = []
    for sample in samples:
        fpath = data_dir / sample['file'] if not Path(sample['file']).is_absolute() \
            else Path(sample['file'])
        ds_list, _ = parse_rf6000_csv(str(fpath))
        for ds in ds_list:
            stype = str(ds.get('spectrum_type', ''))
            if skip_excitation and stype.lower() == 'excitation':
                print(f"  ⏭️ 跳过激发光谱: {fpath.name} ({ds['label']})")
                continue
            datasets.append({
                'name': sample['name'],
                'label': _label_of(sample),
                'zn_conc': sample.get('zn_conc'),
                'wl': np.asarray(ds['wl'], dtype=float),
                'intensity': np.asarray(ds['intensity'], dtype=float),
                'ex': ds['ex_wl'],
                'stype': stype,
                'file': fpath.name,
            })
    if not datasets:
        raise ValueError("没有可用数据（可能全部为激发光谱）")
    return datasets


# ======================== 2. 峰值查找 ========================
def find_main_peak(wl, intensity, wl_min=400, wl_max=500):
    """返回区间 [wl_min, wl_max] 内主峰 (波长, 强度)。"""
    mask = (wl >= wl_min) & (wl <= wl_max)
    if not mask.any():
        return np.nan, np.nan
    i = int(np.argmax(intensity[mask]))
    return float(wl[mask][i]), float(intensity[mask][i])


def find_aux_peaks(wl, intensity, wl_min=400, wl_max=500, main_wl=None,
                   height_frac=0.05, prominence_frac=0.03):
    """区间内的次要峰列表 [(波长, 强度), ...]，排除主峰。"""
    mask = (wl >= wl_min) & (wl <= wl_max)
    y_max = float(np.nanmax(intensity[mask])) if mask.any() else 0.0
    peaks, _ = find_peaks(
        intensity[mask],
        height=y_max * height_frac,
        distance=5,
        prominence=y_max * prominence_frac,
    )
    out = []
    for p in peaks:
        pw = wl[mask][p]
        if main_wl is None or abs(pw - main_wl) > 1e-9:
            out.append((float(pw), float(intensity[mask][p])))
    return out


# ======================== 3. 合并局部放大图 ========================
def plot_combined_zoom(datasets, out_path, xlim=(300, 500), peak_range=(400, 500),
                       title=None, annotate_peaks=True, rb_name='RB', dpi=200,
                       normalize_to=None):
    """合并光谱局部放大图，自动标注峰位；RB 加粗显示并标注为参照。

    参数
    ----
    datasets : list[dict]
        load_emission_datasets 的返回结果。
    out_path : str/Path
        输出 PNG 路径。
    xlim : tuple
        横轴波长范围（局部放大区间）。
    peak_range : tuple
        峰位标注的查找区间。
    title : str
        图标题；None 时自动生成。
    normalize_to : str/None
        归一化基准样品名（如 'RB'）：将所有曲线除以该样品在 peak_range
        内的峰值强度，使该样品峰值 = 1；None 表示不归一化。
    """
    if len(datasets) < 1:
        print("  ⚠️ 无数据，跳过合并图")
        return

    norm_factor = 1.0
    if normalize_to is not None:
        base = next((d for d in datasets if d['name'] == normalize_to), None)
        if base is None:
            raise ValueError(f"找不到归一化基准样品 {normalize_to}")
        _, base_peak = find_main_peak(base['wl'], base['intensity'],
                                      peak_range[0], peak_range[1])
        if np.isnan(base_peak) or base_peak == 0:
            raise ValueError(f"归一化基准样品 {normalize_to} 在 "
                             f"{peak_range} 区间内无有效峰值")
        norm_factor = base_peak

    fig, ax = plt.subplots(figsize=(11.5, 6.8))
    for i, ds in enumerate(datasets):
        lw = 2.2 if ds['name'] == rb_name else 1.6
        y = ds['intensity'] / norm_factor
        ax.plot(ds['wl'], y, linewidth=lw,
                color=_color_for(ds['name'], i), label=ds['label'], zorder=3)

        if annotate_peaks:
            pw, pv = find_main_peak(ds['wl'], y,
                                    peak_range[0], peak_range[1])
            if not np.isnan(pw):
                ax.annotate(f"{pw:.1f} nm", xy=(pw, pv), xytext=(0, 7),
                            textcoords='offset points', fontsize=9,
                            color=_color_for(ds['name'], i),
                            ha='center', va='bottom')
                ax.axvline(pw, color=_color_for(ds['name'], i), linestyle=':',
                           alpha=0.45, linewidth=0.9)

    ax.set_xlim(xlim)
    if title is None:
        title = f"{'、'.join(ds['label'] for ds in datasets)} 光谱对比" \
                f"（{xlim[0]}–{xlim[1]} nm 局部放大）"
    ax.set_title(title, fontsize=14)
    ax.set_xlabel('波长 (nm)', fontsize=12)
    if normalize_to is not None:
        ax.set_ylabel(f'归一化强度（{_label_of({"name": normalize_to})}峰值 = 1）',
                      fontsize=12)
    else:
        ax.set_ylabel('强度 (AU)', fontsize=12)
    ax.legend(fontsize=10, loc='upper left', framealpha=0.9)
    ax.grid(True, alpha=0.3)

    zoom_ints = [(ds['intensity'] / norm_factor)[(ds['wl'] >= xlim[0]) & (ds['wl'] <= xlim[1])]
                 for ds in datasets]
    all_zoom = np.concatenate(zoom_ints)
    y_min, y_max = np.nanmin(all_zoom), np.nanmax(all_zoom)
    ax.set_ylim(y_min - (y_max - y_min) * 0.08, y_max + (y_max - y_min) * 0.16)

    fig.tight_layout()
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=dpi)
    plt.close(fig)
    print(f"  ✔ 合并图已保存: {out_path.name}")


# ======================== 3.5 单独光谱图（多光谱逐条成图） ========================
def plot_individual(datasets, out_dir, xlim=None, annotate_peaks=True,
                    peak_height=0.05, peak_distance=10, peak_prominence=0.03,
                    show_ex=False, dpi=200, suffix=''):
    """逐条光谱单独成图（每个样品一张 PNG，复用 plot_emission.plot_single）。

    具有多个光谱数据时，直接引用本函数即可为每条光谱各画一张单独图；
    合并图请用 plot_combined_zoom（局部放大合并）或 plot_emission.plot_combined。

    参数
    ----
    datasets : list[dict]
        load_emission_datasets 的返回结果。
    out_dir : str/Path
        输出目录（自动创建）。
    xlim : tuple/None
        横轴波长范围（nm）；None 为全范围。
    annotate_peaks : bool
        是否自动标峰。
    peak_height / peak_distance / peak_prominence
        自动标峰参数（见 plot_emission.plot_single）。
    show_ex : bool
        是否标注激发波长虚线。
    dpi : int
        输出分辨率（默认 200）。
    suffix : str
        文件名后缀，如 '_单独'（默认空），仅影响文件名不影响图标题。

    返回
    ----
    list[Path]：已保存的文件路径列表。
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    for ds in datasets:
        single_ds = {
            'label': ds['label'],
            'ex_wl': ds['ex'],
            'wl': ds['wl'],
            'intensity': ds['intensity'],
        }
        fname = f"{ds['name']}{suffix}_emission.png"
        saved.extend(plot_single(single_ds, save_dir=out_dir, show=False, xlim=xlim,
                                 annotate_peaks=annotate_peaks,
                                 peak_height=peak_height, peak_distance=peak_distance,
                                 peak_prominence=peak_prominence, show_ex=show_ex,
                                 fname=fname, dpi=dpi))
    return saved


# ======================== 4. 峰表 ========================
def export_peak_table(datasets, out_path, peak_range=(400, 500), rb_name='RB'):
    """生成峰表 DataFrame 并保存 CSV（含相对 RB 的归一化列）。

    返回 (DataFrame, rb_peak)。RB 峰值为 1 的基准。
    """
    records = []
    for ds in datasets:
        pw, pv = find_main_peak(ds['wl'], ds['intensity'],
                                peak_range[0], peak_range[1])
        aux = find_aux_peaks(ds['wl'], ds['intensity'],
                             peak_range[0], peak_range[1], main_wl=pw)
        records.append({
            '样品': ds['label'],
            '文件': ds['file'],
            '类型': ds['stype'] or 'Emission',
            'EX(nm)': ds['ex'],
            'ZnPcS4浓度(μmol/L)': ds['zn_conc'],
            '峰值波长(nm)': round(pw, 1),
            '峰值强度(AU)': round(pv, 2),
            '次要峰': '; '.join(f"{w:.1f}nm/{i:.0f}" for w, i in aux) or '',
        })

    df = pd.DataFrame(records)
    rb_row = df[df['样品'].astype(str).str.contains(rb_name)]
    if len(rb_row) == 0:
        raise ValueError(f"峰表中找不到参考样品 {rb_name}")
    rb_peak = float(rb_row.iloc[0]['峰值强度(AU)'])
    df['相对RB(峰值/RB峰)'] = df['峰值强度(AU)'] / rb_peak
    df = df.round({'相对RB(峰值/RB峰)': 4})

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False, encoding='utf-8-sig')
    print(f"  ✔ 峰表已保存: {out_path.name}")
    return df, rb_peak


# ======================== 5. RB 归一化浓度图 ========================
def plot_rb_normalized_concentration(datasets, out_path, peak_range=(400, 500),
                                     rb_name='RB', title=None, dpi=200):
    """以 RB 峰值为 1，作 400-500 nm 峰强度 vs ZnPcS4 浓度的图。

    - 横轴：ZnPcS4 浓度（μmol/L），RB 作为 0 浓度点
    - 纵轴：各样品峰值强度 / RB 峰值（RB = 1）
    - 只绘制 zn_conc 不为空的样品；数据点间用细线连接辅助观察
    """
    ratios = []
    for ds in datasets:
        if ds['zn_conc'] is None:
            continue
        pw, pv = find_main_peak(ds['wl'], ds['intensity'],
                                peak_range[0], peak_range[1])
        ratios.append({**ds, 'peak_int': pv})

    rb_peak = None
    for r in ratios:
        if r['name'] == rb_name:
            rb_peak = r['peak_int']
            break
    if rb_peak is None:
        raise ValueError(f"找不到参考样品 {rb_name}")

    for r in ratios:
        r['ratio'] = r['peak_int'] / rb_peak

    ratios.sort(key=lambda r: r['zn_conc'])

    fig, ax = plt.subplots(figsize=(9.5, 6.2))
    ax.axhline(1.0, color='black', linestyle='--', linewidth=1.2, alpha=0.7,
               label=f"{_label_of({'name': rb_name})} = 1")

    xs = [r['zn_conc'] for r in ratios]
    ys = [r['ratio'] for r in ratios]
    ax.plot(xs, ys, color='gray', linestyle='-', linewidth=1.0, alpha=0.5,
            zorder=1)

    for i, r in enumerate(ratios):
        marker = 's' if r['name'] == rb_name else 'o'
        ms = 10 if r['name'] == rb_name else 8
        ax.scatter(r['zn_conc'], r['ratio'], marker=marker, s=ms ** 2,
                   color=_color_for(r['name'], i), edgecolor='black',
                   zorder=5, label=r['label'])
        ax.annotate(f"{r['ratio']:.3f}", xy=(r['zn_conc'], r['ratio']),
                    xytext=(6, 5), textcoords='offset points', fontsize=9,
                    color=_color_for(r['name'], i))

    ax.set_xlabel('ZnPcS4 浓度 (μmol/L)', fontsize=12)
    ax.set_ylabel(f'{peak_range[0]}–{peak_range[1]} nm 峰值强度 / RB峰值（RB = 1）',
                  fontsize=11)
    if title is None:
        title = (f"相对 RB 的 {peak_range[0]}–{peak_range[1]} nm 峰强度 "
                 "vs ZnPcS4 浓度")
    ax.set_title(title, fontsize=13)
    x_max = max(xs) if xs else 100
    ax.set_xlim(min(xs) - x_max * 0.05, x_max * 1.05)
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=9, loc='upper right', framealpha=0.9)

    fig.tight_layout()
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=dpi)
    plt.close(fig)
    print(f"  ✔ 浓度图已保存: {out_path.name}")


# ======================== 6. 一键入口 ========================
def analyze_zn_rb_folder(data_dir, out_dir, samples, xlim=(300, 500),
                         peak_range=(400, 500), rb_name='RB',
                         zoom_fname='combined_zoom_300_500.png',
                         table_fname='peaks_400_500.csv',
                         conc_fname='ZnPcS4_concentration_RB_normalized.png',
                         title=None, conc_title=None, annotate_peaks=True,
                         normalize_to=None, individual=False, dpi=200):
    """一键完成：加载数据 → 合并局部放大图 → 峰表 → 归一化浓度图。

    参数
    ----
    data_dir : str/Path
        数据文件夹（CSV + 说明.xlsx 所在目录）。
    out_dir : str/Path
        输出目录（自动创建）。
    samples : list[dict]
        样品列表，每项含 file、name、zn_conc，可选 label。
    xlim : tuple
        合并图横轴范围。
    peak_range : tuple
        峰值查找区间。
    rb_name : str
        参照样品名（默认 RB）。
    zoom_fname / table_fname / conc_fname : str
        三个输出文件名。
    title / conc_title : str
        合并图 / 浓度图标题（None 自动生成）。
    annotate_peaks : bool
        合并图是否标注峰位。
    normalize_to : str/None
        合并图归一化基准样品名（如 'RB'），None 不归一化。
    individual : bool
        是否额外为每条光谱单独成图（默认 False）。
        多光谱数据时传 True，即可同时得到"每条单独图 + 合并放大图"。
    dpi : int
        输出分辨率（默认 200）。
    """
    data_dir = Path(data_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("加载光谱数据...")
    print("=" * 60)
    datasets = load_emission_datasets(data_dir, samples)
    for ds in datasets:
        print(f"  → {ds['label']:<16} EX={ds['ex']}  点={len(ds['wl'])}")

    if individual:
        print("\n绘制各样品单独光谱图...")
        plot_individual(datasets, out_dir, xlim=xlim,
                        annotate_peaks=annotate_peaks, dpi=dpi)

    print("\n绘制合并局部放大图...")
    plot_combined_zoom(datasets, out_dir / zoom_fname, xlim=xlim,
                       peak_range=peak_range, title=title, rb_name=rb_name,
                       annotate_peaks=annotate_peaks, normalize_to=normalize_to)

    print("\n导出峰表...")
    df, rb_peak = export_peak_table(datasets, out_dir / table_fname,
                                    peak_range=peak_range, rb_name=rb_name)
    print(df.to_string(index=False))

    print("\n绘制 RB 归一化浓度图...")
    plot_rb_normalized_concentration(datasets, out_dir / conc_fname,
                                     peak_range=peak_range, rb_name=rb_name,
                                     title=conc_title)

    print("\n✅ 全部完成！输出目录:", out_dir)
