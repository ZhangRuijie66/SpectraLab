"""
吸收光谱 CSV / 多列 xlsx 批量绘图工具
适用格式：
  1. LabSolutions UV-Vis 输出的吸收光谱 CSV 文件
  2. **多列光谱 xlsx**（v4.41）：一列波长(nm) + 若干样品列，按列拆成多条吸收光谱
     （仪器的 Excel 多光谱导出，如 20261010.xlsx；见 read_xlsx_info.parse_spectrum_xlsx）
功能：单图 + 合并图，自动提取样品信息等，支持多种吸收光谱数据处理

【多光谱数据直接引用函数】
  具有多个光谱数据时，可直接引用以下函数：
    - load_absorption_spectra(files)      ：批量解析多个 CSV/xlsx → 全部光谱数据集（扁平列表）
    - plot_absorption_spectra(files, ...) ：一键画出【每条单独图】+【合并图】，并返回数据集
    - plot_single_absorption(dataset, ...) ：传单个 dict 或 dict 列表，逐条画出单独图
    - plot_combined_absorption(datasets,.)：传 dict 列表，画一张合并对比图

合并图的颜色按样品身份（label）分配并记忆：增删数据集时已有曲线的颜色不变。
换一批数据时调用 reset_curve_colors() 清空，详见 curve_colors.py。
"""

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib
import numpy as np
from pathlib import Path
import argparse
import re
import glob
from scipy.signal import find_peaks
from scipy.interpolate import CubicSpline
from curve_colors import CurveColors
from read_xlsx_info import parse_spectrum_xlsx


# ======================== 0. 中文字体设置 ========================

def _safe_print(*args):
    """安全打印：在某些终端/编码（如 GBK、ASCII）下避免因非 ASCII 字符崩溃"""
    try:
        print(*args)
    except Exception:
        pass


def setup_chinese_font():
    """设置中文字体支持（跨平台：Windows / macOS / Linux）"""
    candidates = [
        # Windows
        'Microsoft YaHei', 'SimHei', 'KaiTi', 'FangSong', 'SimSun',
        # macOS
        'PingFang SC', 'Hiragino Sans GB', 'Songti SC', 'STHeiti', 'Heiti SC', 'Arial Unicode MS',
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
        _safe_print(f"  [FONT] 使用中文字体: {chosen}")
    else:
        _safe_print("  [WARN] 未找到中文字体，将使用英文标签")
        plt.rcParams['font.sans-serif'] = ['DejaVu Sans']

setup_chinese_font()


# ======================== 0.1 曲线颜色 ========================
# 模块级颜色分配器：同一次运行内，同一份数据（按样品名标识）始终拿到同一个
# 颜色——合并图里增删数据集时，已有曲线的颜色不变。换一批数据时调用
# reset_curve_colors() 清空。实现见 curve_colors.py。
_color_assigner = CurveColors()


def reset_curve_colors():
    """清空已记住的曲线颜色（换一批数据时调用）"""
    _color_assigner.reset()


# ======================== 1. 读取解析 ========================

def clean_array(arr):
    """去除 NaN 和 Inf"""
    arr = np.asarray(arr, dtype=float)
    mask = np.isfinite(arr)
    return arr[mask]


def detect_absorption_format(filepath):
    """
    自动检测吸收光谱 CSV 格式：
      - 'uvvis': LabSolutions UV-Vis 格式
    """
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            head = ''.join(f.readline() for _ in range(60))
    except UnicodeDecodeError:
        try:
            with open(filepath, 'r', encoding='gbk') as f:
                head = ''.join(f.readline() for _ in range(60))
        except UnicodeDecodeError:
            with open(filepath, 'r', encoding='latin-1') as f:
                head = ''.join(f.readline() for _ in range(60))

    if 'LabSolutions UV-Vis' in head or '波长(nm),吸收值' in head:
        return 'uvvis'
    else:
        # 默认尝试 uvvis
        return 'uvvis'


def parse_uvvis_csv(filepath):
    """
    解析 LabSolutions UV-Vis 输出的吸收光谱 CSV
    格式特点：
      - 前半部分是 [样品信息], [软件信息], [仪器信息], [测定], [附件], [高级设置] 等元数据
      - 后半部分是 "波长(nm),吸收值" 后跟数值数据
      - 单通道数据，按波长递减排列（从高波长到低波长）
    """
    # --- 读取原始文本 ---
    encodings = ['utf-8', 'gbk', 'latin-1']
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

    # --- 从文本行中提取元数据 ---
    sample_name = ''
    analyst = ''
    creation_date = ''
    instrument_name = ''
    start_wl = None
    end_wl = None
    interval = None
    
    for line in lines:
        # 跳过空行
        stripped = line.strip()
        if not stripped:
            continue

        # 按逗号分割，保留原始列
        parts = [p.strip() for p in stripped.split(',')]

        # 样品名称
        if '样品名称' in parts:
            idx = next((i for i, p in enumerate(parts) if '样品名称' in p), -1)
            if idx >= 0 and idx + 1 < len(parts):
                val = parts[idx + 1]
                if val and val.lower() != 'nan':
                    sample_name = val

        # 分析者
        if '分析者' in parts:
            idx = next((i for i, p in enumerate(parts) if '分析者' in p), -1)
            if idx >= 0 and idx + 1 < len(parts):
                val = parts[idx + 1]
                if val and val.lower() != 'nan':
                    analyst = val

        # 创建日期和时间
        if '创建日期和时间' in parts:
            idx = next((i for i, p in enumerate(parts) if '创建日期和时间' in p), -1)
            if idx >= 0 and idx + 1 < len(parts):
                val = parts[idx + 1]
                if val and val.lower() != 'nan':
                    creation_date = val

        # 仪器名称
        if '仪器名称' in parts:
            idx = next((i for i, p in enumerate(parts) if '仪器名称' in p), -1)
            if idx >= 0 and idx + 1 < len(parts):
                val = parts[idx + 1]
                if val and val.lower() != 'nan':
                    instrument_name = val

        # 测定参数 - 开始波长
        if '开始(nm)' in parts:
            idx = next((i for i, p in enumerate(parts) if '开始(nm)' in p), -1)
            if idx >= 0 and idx + 1 < len(parts):
                val = parts[idx + 1]
                if val and val.lower() != 'nan':
                    start_wl = float(val.replace('nm', '').strip())

        # 测定参数 - 结束波长
        if '结束(nm)' in parts:
            idx = next((i for i, p in enumerate(parts) if '结束(nm)' in p), -1)
            if idx >= 0 and idx + 1 < len(parts):
                val = parts[idx + 1]
                if val and val.lower() != 'nan':
                    end_wl = float(val.replace('nm', '').strip())

        # 测定参数 - 数据间隔
        if '数据间隔(nm)' in parts:
            idx = next((i for i, p in enumerate(parts) if '数据间隔(nm)' in p), -1)
            if idx >= 0 and idx + 1 < len(parts):
                val = parts[idx + 1]
                if val and val.lower() != 'nan':
                    interval = float(val.replace('nm', '').strip())

    # --- 找到数据起始行 ---
    # 特征：包含 "波长(nm),吸收值" 的行（数据表头）
    data_start = None
    for i, line in enumerate(lines):
        if '波长(nm),吸收值' in line:
            data_start = i + 1  # 数据从下一行开始
            break

    if data_start is None:
        raise ValueError("未找到 '波长(nm),吸收值' 数据表头行，文件格式可能不匹配")

    # --- 读取数值数据（从文本行解析） ---
    wl_list = []
    int_list = []
    for line in lines[data_start:]:
        stripped = line.strip()
        if not stripped:
            continue
        parts = stripped.split(',')
        if len(parts) < 2:
            continue
        try:
            wl_val = float(parts[0].strip())
            int_val = float(parts[1].strip())
            wl_list.append(wl_val)
            int_list.append(int_val)
        except ValueError:
            continue

    # --- 波长处理：UV-Vis 数据通常是递减排列，需要转为递增 ---
    wl_clean = np.array(wl_list, dtype=float)
    int_clean = np.array(int_list, dtype=float)
    
    # 检查波长是否递减，如果是则反转
    if len(wl_clean) > 1 and wl_clean[0] > wl_clean[-1]:
        wl_clean = wl_clean[::-1]
        int_clean = int_clean[::-1]

    if len(wl_clean) == 0:
        raise ValueError("未找到有效光谱数据")

    if sample_name == '' or sample_name == 'nan':
        sample_name = Path(filepath).stem

    # 显示标签
    display_label = sample_name
    if analyst:
        display_label += f" ({analyst})"
    if creation_date:
        # 只提取日期部分
        date_part = creation_date.split()[0] if ' ' in creation_date else creation_date
        display_label += f" {date_part}"

    # 返回结构化的光谱数据字典
    return {
        'label': display_label,
        'sample_name': sample_name,
        'analyst': analyst,
        'creation_date': creation_date,
        'instrument': instrument_name,
        'start_wavelength': start_wl,
        'end_wavelength': end_wl,
        'interval': interval,
        'wl': wl_clean,
        'absorption': int_clean,
        'filepath': str(filepath),
        'data_type': 'absorption'
    }


def parse_absorption_csv(filepath):
    """统一入口：根据格式自动选择解析函数"""
    format_type = detect_absorption_format(filepath)
    if format_type == 'uvvis':
        return parse_uvvis_csv(filepath)
    else:
        raise ValueError(f"不支持的格式: {format_type}")


def load_absorption_spectra(files, skip_metadata=False, verbose=True):
    """
    批量解析多个吸收光谱文件（CSV，或多列光谱 xlsx）

    参数:
        files: str/list/Path - 一个或多个路径，支持通配符
        skip_metadata: bool - 是否跳过元数据解析，默认 False
        verbose: bool - 是否打印进度信息，默认 True

    返回:
        list[dict] - 每个 dict 一条吸收光谱。**一个多列 xlsx 会展开成多条**
        （v4.41：列名清洗后作 label，如 '20261010R1 - RawData' -> 'R1'）。
    """
    if isinstance(files, str):
        # 支持通配符
        files = glob.glob(files)
    
    if isinstance(files, Path):
        files = [str(files)]
    
    datasets = []
    
    for file in files:
        # v4.41：多列光谱 xlsx —— 一个文件拆成多条光谱
        if Path(file).suffix.lower() in ('.xlsx', '.xls'):
            try:
                sheets = parse_spectrum_xlsx(file)
            except Exception as e:
                if verbose:
                    print(f"   [ERROR] xlsx 解析失败: {e}")
                continue
            for sh in sheets:
                ds = {
                    'label': sh['label'],
                    'sample_name': sh['label'],
                    'analyst': '', 'creation_date': '', 'instrument': '',
                    'start_wavelength': float(sh['wl'][0]),
                    'end_wavelength': float(sh['wl'][-1]),
                    'interval': (float(sh['wl'][1] - sh['wl'][0])
                                 if len(sh['wl']) > 1 else 0.0),
                    'wl': sh['wl'],
                    'absorption': sh['y'],
                    'filepath': str(file),
                    'data_type': 'absorption',
                    'format': 'xlsx-multicolumn',
                    'source_column': sh.get('column', ''),
                }
                datasets.append(ds)
                if verbose:
                    print(f"   [OK] 样品: {ds['label']}"
                          f"（{len(ds['wl'])} 点，"
                          f"{ds['start_wavelength']:.1f}–{ds['end_wavelength']:.1f} nm）")
            continue

        if verbose:
            print(f" [FILE] 正在解析: {Path(file).name}")
        
        try:
            data = parse_absorption_csv(file)
            datasets.append(data)
            
            if verbose:
                print(f"   [OK] 样品: {data['label']}")
                if skip_metadata:
                    print(f"   [RANGE] 波长范围: {data['wl'][0]:.1f} - {data['wl'][-1]:.1f} nm")
                    print(f"   [DATA] 数据点数: {len(data['wl'])}")
                else:
                    print(f"   [RANGE] 波长范围: {data['start_wavelength']} - {data['end_wavelength']} nm")
                    print(f"   [RANGE] 数据间隔: {data['interval']} nm")
                    print(f"   [DATA] 数据点数: {len(data['wl'])}")
                    print(f"   [USER] 分析者: {data['analyst']}")
                    print(f"   [DATE] 日期: {data['creation_date']}")
                    
        except Exception as e:
            if verbose:
                print(f"   [ERROR] 解析失败: {e}")
            continue
    
    if verbose:
        print(f"\n [TOTAL] 成功加载 {len(datasets)} 个吸收光谱数据集")
    
    return datasets


# ======================== 2. 绘图函数 ========================

def plot_single_absorption(dataset, save_dir=".", show=False, dpi=200,
                         xlim=None, ylim=None, annotate_peaks=True,
                         peak_height=0.1, peak_distance=10, peak_prominence=0.05,
                         smooth=False, smooth_factor=1, figsize=(10, 6),
                         title=None, xlabel="波长 (nm)", ylabel="吸收值",
                         grid=True, legend=True, linewidth=2, alpha=1.0):
    """
    绘制单个吸收光谱图
    
    参数:
        dataset: dict 或 list[dict] - 单个或多个光谱数据
        save_dir: str/Path - 保存目录，默认当前目录
        show: bool - 是否显示图像，默认 True
        dpi: int - 图像分辨率，默认 200
        xlim: tuple - 横轴范围 (xmin, xmax)
        ylim: tuple - 纵轴范围 (ymin, ymax)
        annotate_peaks: bool - 是否标注峰，默认 True
        peak_height: float - 峰高阈值，默认 0.1
        peak_distance: int - 峰间距最小点数，默认 10
        peak_prominence: float - 峰突出度阈值，默认 0.05
        smooth: bool - 是否平滑曲线，默认 False
        smooth_factor: int - 平滑倍数，默认 1
        figsize: tuple - 图像大小，默认 (10, 6)
        title: str - 自定义标题，如果为 None 使用样品名
        xlabel: str - x轴标签，默认 "波长 (nm)"
        ylabel: str - y轴标签，默认 "吸收值"
        grid: bool - 是否显示网格，默认 True
        legend: bool - 是否显示图例，默认 True
        linewidth: int - 线宽，默认 2
        alpha: float - 透明度，默认 1.0
    
    返回:
        list[Path] - 保存的文件路径列表
    """
    if isinstance(dataset, dict):
        dataset = [dataset]
    
    save_dir = Path(save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)
    
    saved_files = []
    
    for data in dataset:
        fig, ax = plt.subplots(figsize=figsize)
        
        # 数据准备
        x = data['wl']
        y = data['absorption']
        
        # 平滑处理
        if smooth and smooth_factor > 1:
            # 增加数据点
            x_new = np.linspace(x.min(), x.max(), len(x) * smooth_factor)
            cs = CubicSpline(x, y)
            y_smooth = cs(x_new)
            ax.plot(x_new, y_smooth, linewidth=linewidth, alpha=alpha, 
                   label=data['label'], color='blue')
        else:
            ax.plot(x, y, linewidth=linewidth, alpha=alpha, 
                   label=data['label'], color='blue')
        
        # 峰值标注
        if annotate_peaks:
            peaks, properties = find_peaks(y, height=peak_height, 
                                         distance=peak_distance, 
                                         prominence=peak_prominence)
            if len(peaks) > 0:
                peak_x = x[peaks]
                peak_y = y[peaks]
                ax.scatter(peak_x, peak_y, color='red', s=50, zorder=5)
                
                # 添加峰标签
                for px, py in zip(peak_x, peak_y):
                    ax.annotate(f'{px:.1f}', (px, py), 
                              xytext=(5, 5), textcoords='offset points',
                              fontsize=8, color='red')
        
        # 设置坐标轴范围
        if xlim is None:
            xlim = (x.min(), x.max())
        
        # 改进的Y轴范围计算
        if ylim is None:
            max_y = float(np.max(y))
            min_y = float(np.min(y))
            y_range = max_y - min_y
            # 只有在**全为正**且动态范围确实很大时才切对数轴：
            # 吸光度常有负值/接近 0 的基线，旧实现用 max_y/min_y 判断，
            # 除零得 inf、负值比值为负，都会静默把纵轴换成对数并裁掉负值区
            positive = bool(np.all(y > 0))
            use_log = positive and min_y > 0 and (max_y / min_y) > 100
            if use_log:
                ax.set_yscale('log')
                ylim = (min_y * 0.5, max_y * 2)
            elif y_range > 0:
                ylim = (min_y - y_range * 0.1, max_y + y_range * 0.1)
            else:
                ylim = (max_y * 0.9, max_y * 1.1)
        
        ax.set_xlim(xlim)
        ax.set_ylim(ylim)
        
        # 设置标题和标签
        if title is None:
            title = f"吸收光谱 - {data['label']}"
        ax.set_title(title, fontsize=14, fontweight='bold')
        ax.set_xlabel(xlabel, fontsize=12)
        
        # 根据坐标轴类型设置y轴标签
        if isinstance(ax.get_yscale(), str) and ax.get_yscale() == 'log':
            ax.set_ylabel(f"{ylabel} (对数坐标)", fontsize=12)
        else:
            ax.set_ylabel(ylabel, fontsize=12)
        
        # 网格和图例
        if grid:
            ax.grid(True, alpha=0.3)
        if legend:
            ax.legend()
        
        plt.tight_layout()
        
        # 保存文件
        filename = f"{data['label']}_absorption.png"
        filename = filename.replace('/', '_').replace('\\', '_')  # 替换路径分隔符
        save_path = save_dir / filename
        
        plt.savefig(save_path, dpi=dpi, bbox_inches='tight')
        saved_files.append(save_path)
        
        if show:
            plt.show()
        else:
            plt.close()
    
    return saved_files


def plot_combined_absorption(datasets, save_dir=".", normalize=False, dpi=200,
                            xlim=None, ylim=None, annotate_peaks=True,
                            peak_height=0.1, peak_distance=10, peak_prominence=0.05,
                            smooth=False, smooth_factor=1, figsize=(12, 8),
                            title="吸收光谱对比", xlabel="波长 (nm)", ylabel="吸收值",
                            grid=True, legend=True, linewidth=2, alpha=0.8,
                            colors=None, linestyle='-', markers=None,
                            show_individual_info=True, show=False):
    """
    绘制多个吸收光谱合并对比图
    
    参数:
        datasets: list[dict] - 多个光谱数据
        save_dir: str/Path - 保存目录，默认当前目录
        normalize: bool - 是否归一化，默认 False
        dpi: int - 图像分辨率，默认 200
        xlim: tuple - 横轴范围 (xmin, xmax)
        ylim: tuple - 纵轴范围 (ymin, ymax)
        annotate_peaks: bool - 是否标注峰，默认 True
        peak_height: float - 峰高阈值，默认 0.1
        peak_distance: int - 峰间距最小点数，默认 10
        peak_prominence: float - 峰突出度阈值，默认 0.05
        smooth: bool - 是否平滑曲线，默认 False
        smooth_factor: int - 平滑倍数，默认 1
        figsize: tuple - 图像大小，默认 (12, 8)
        title: str - 图表标题，默认 "吸收光谱对比"
        xlabel: str - x轴标签，默认 "波长 (nm)"
        ylabel: str - y轴标签，默认 "吸收值"
        grid: bool - 是否显示网格，默认 True
        legend: bool - 是否显示图例，默认 True
        linewidth: int - 线宽，默认 2
        alpha: float - 透明度，默认 0.8
        colors: list - 颜色列表；None 时按样品身份稳定分配（增删数据集时已有曲线的颜色不变，
                       见 curve_colors.py）
        linestyle: str/strs - 线型
        markers: str/strs - 标记样式
        show_individual_info: bool - 是否在图上显示单个样品信息
        show: bool - 是否显示图像，默认 True
    
    返回:
        Path - 合并图保存路径
    """
    if not datasets:
        raise ValueError("没有提供光谱数据")
    
    save_dir = Path(save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)
    
    fig, ax = plt.subplots(figsize=figsize)
    
    # 默认颜色：按样品身份稳定分配（增删数据集时已有曲线的颜色不变）
    if colors is None:
        colors = [_color_assigner.get(d.get('label') or f"dataset_{j}", plt.cm.tab10)
                  for j, d in enumerate(datasets)]
    
    # 准备数据
    all_wl = []
    all_abs = []
    for data in datasets:
        all_wl.extend(data['wl'])
        all_abs.extend(data['absorption'])
    
    if xlim is None:
        xlim = (min(all_wl), max(all_wl))
    
    # 改进的Y轴范围计算 - 考虑所有数据并添加适当的边距
    max_abs = float(np.max(all_abs))
    min_abs = float(np.min(all_abs))

    if ylim is None:
        # 只有全为正、且动态范围确实很大时才用对数轴（见单独图处的说明）
        use_log = bool(np.all(np.asarray(all_abs) > 0)) and max_abs / min_abs > 100
        if use_log:  # 大动态范围
            # 对数坐标
            ax.set_yscale('log')
            ylim = (min_abs * 0.5, max_abs * 2)
        else:
            # 线性坐标，添加适当边距
            y_range = max_abs - min_abs
            if y_range > 0:
                # 使用固定边距策略，避免小数据时边距过大
                margin = max(y_range * 0.1, 0.1)  # 至少0.1的边距
                ylim = (max(0, min_abs - margin), max_abs + margin)
            else:
                ylim = (max(0, min_abs * 0.9), max_abs * 1.1)
    
    # 绘制每个光谱
    for i, data in enumerate(datasets):
        x = data['wl']
        y = data['absorption']
        
        # 归一化处理
        if normalize:
            y = y / max(y) if max(y) > 0 else y
        
        # 线型样式
        if isinstance(linestyle, str):
            ls = linestyle
        else:
            ls = linestyle[i % len(linestyle)] if linestyle else '-'
        
        # 标记样式
        if isinstance(markers, str):
            marker = markers
        else:
            marker = markers[i % len(markers)] if markers else None
        
        # 颜色
        color = colors[i % len(colors)]
        
        # 平滑处理
        if smooth and smooth_factor > 1:
            x_new = np.linspace(x.min(), x.max(), len(x) * smooth_factor)
            cs = CubicSpline(x, y)
            y_smooth = cs(x_new)
            ax.plot(x_new, y_smooth, linewidth=linewidth, alpha=alpha,
                   color=color, linestyle=ls, marker=marker,
                   label=data['label'])
        else:
            ax.plot(x, y, linewidth=linewidth, alpha=alpha,
                   color=color, linestyle=ls, marker=marker,
                   label=data['label'])
        
        # 峰值标注
        if annotate_peaks:
            peaks, properties = find_peaks(y, height=peak_height,
                                         distance=peak_distance,
                                         prominence=peak_prominence)
            if len(peaks) > 0:
                peak_x = x[peaks]
                peak_y = y[peaks]
                ax.scatter(peak_x, peak_y, color=color, s=50, zorder=5)
                
                # 添加峰标签（仅对第一个数据集）
                if i == 0 and len(datasets) > 1:
                    for px, py in zip(peak_x, peak_y):
                        if isinstance(ax.get_yscale(), str) and ax.get_yscale() == 'log':
                            # 对数坐标下调整标签位置
                            ax.annotate(f'{px:.1f}', (px, py),
                                      xytext=(5, 5), textcoords='offset points',
                                      fontsize=8, color=color)
                        else:
                            ax.annotate(f'{px:.1f}', (px, py),
                                      xytext=(5, 5), textcoords='offset points',
                                      fontsize=8, color=color)
        
        # 显示单个样品信息
        if show_individual_info and len(datasets) == 1:
            info_text = f"分析者: {data['analyst']}\n"
            info_text += f"仪器: {data['instrument']}\n"
            info_text += f"日期: {data['creation_date']}"
            ax.text(0.02, 0.98, info_text, transform=ax.transAxes,
                   verticalalignment='top', bbox=dict(boxstyle='round', 
                   facecolor='wheat', alpha=0.8), fontsize=8)
    
    # 设置坐标轴
    ax.set_xlim(xlim)
    ax.set_ylim(ylim)
    ax.set_title(title, fontsize=16, fontweight='bold')
    ax.set_xlabel(xlabel, fontsize=12)
    
    # 根据坐标轴类型设置y轴标签
    if isinstance(ax.get_yscale(), str) and ax.get_yscale() == 'log':
        ax.set_ylabel(f"{ylabel} (对数坐标)", fontsize=12)
    else:
        ax.set_ylabel(ylabel, fontsize=12)
    
    # 网格和图例
    if grid:
        ax.grid(True, alpha=0.3)
    if legend:
        ax.legend()
    
    plt.tight_layout()
    
    # 保存文件
    save_path = save_dir / "combined_absorption_spectra.png"
    plt.savefig(save_path, dpi=dpi, bbox_inches='tight')
    
    # 不显示图像窗口
    if not show:
        plt.close()
    else:
        plt.show()
    
    return save_path


def plot_absorption_spectra(files=None, datasets=None, save_dir=".",
                           plot_individual=True, plot_combined=True,
                           normalize=False, skip_metadata=False, verbose=True, **kwargs):
    """
    一键绘制吸收光谱：单独图 + 合并图

    参数:
        files: str/list/Path - CSV 文件路径或通配符
        datasets: list[dict] - 已解析的数据集（优先于 files）
        save_dir: str/Path - 保存目录，默认当前目录
        plot_individual: bool - 是否绘制单独图，默认 True
        plot_combined: bool - 是否绘制合并图，默认 True
        normalize: bool - 合并图是否归一化，默认 False
        skip_metadata: bool - 是否跳过元数据解析，默认 False
        verbose: bool - 是否打印进度信息，默认 True
        **kwargs: 其他传递给绘图函数的参数

    返回:
        list[dict] - 全部光谱数据集
    """
    if datasets is None:
        if files is None:
            raise ValueError("必须提供 files 或 datasets 参数")
        # 只传递数据加载相关的参数
        load_kwargs = {
            'skip_metadata': skip_metadata,
            'verbose': verbose
        }
        datasets = load_absorption_spectra(files, **load_kwargs)
    
    save_dir = Path(save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)
    
    saved_files = []

    # show 只从 kwargs 里取一次：旧实现取了两次，第二次拿到的是默认 False，
    # 导致「合并图」永远不弹窗（单独图弹、合并图不弹）
    show_value = kwargs.pop('show', False)

    # 绘制单独图
    if plot_individual:
        individual_files = plot_single_absorption(datasets, save_dir=save_dir, show=show_value, **kwargs)
        saved_files.extend(individual_files)
        print(f" [DONE] 单独图已保存: {len(individual_files)} 个文件")

    # 绘制合并图
    if plot_combined:
        combined_file = plot_combined_absorption(datasets, save_dir=save_dir,
                                               normalize=normalize, show=show_value, **kwargs)
        saved_files.append(combined_file)
        print(f" [DONE] 合并图已保存: {combined_file}")
    
    return datasets


# ======================== 3. 吸收光谱分析函数 ========================

def find_absorption_peaks(data, peak_range=None, min_height=0.05, 
                         min_distance=5, min_prominence=0.02):
    """
    查找吸收光谱的吸收峰
    
    参数:
        data: dict - 光谱数据
        peak_range: tuple - 查找范围 (min_wl, max_wl)
        min_height: float - 最小峰高
        min_distance: int - 最小峰间距（数据点数）
        min_prominence: float - 最小峰突出度
    
    返回:
        dict - 包含峰位置、强度等信息
    """
    wl = data['wl']
    absorption = data['absorption']
    
    # 限制查找范围
    if peak_range is not None:
        min_wl, max_wl = peak_range
        mask = (wl >= min_wl) & (wl <= max_wl)
        wl_subset = wl[mask]
        absorption_subset = absorption[mask]
    else:
        wl_subset = wl
        absorption_subset = absorption
    
    # 查找峰
    peaks, properties = find_peaks(absorption_subset, 
                                 height=min_height,
                                 distance=min_distance,
                                 prominence=min_prominence)
    
    # 转换为原始波长坐标
    peak_wavelengths = wl_subset[peaks]
    peak_intensities = absorption_subset[peaks]
    
    # 按强度排序
    sorted_indices = np.argsort(peak_intensities)[::-1]
    
    return {
        'peak_wavelengths': peak_wavelengths[sorted_indices],
        'peak_intensities': peak_intensities[sorted_indices],
        'all_peaks': list(zip(peak_wavelengths, peak_intensities)),
        'num_peaks': len(peaks)
    }


def calculate_absorption_coefficient(data, concentration, path_length=1.0):
    """
    计算摩尔吸光系数 ε = A / (c · l)

    参数:
        data: dict - 光谱数据（需含 'absorption' 与 'wl'）
        concentration: float - 浓度（mol/L）。**必填**：解析器不会给出浓度，
            旧实现默认按 1 mol/L 计算，等于把 A/l 冒充成 ε（差 1/c 倍，
            而 c 未知时误差任意大）。
        path_length: float - 光程（cm），默认为 1.0

    返回:
        dict - 包含吸光系数光谱（'units': 'M^-1 cm^-1'）
    """
    absorption = np.asarray(data['absorption'], dtype=float)
    try:
        concentration = float(concentration)
    except (TypeError, ValueError):
        raise ValueError(f"浓度必须是数值（当前 {concentration!r}）")
    if concentration <= 0:
        raise ValueError(f"浓度必须为正数（当前 {concentration}）")
    path_length = float(path_length)
    if path_length <= 0:
        raise ValueError(f"光程必须为正数（当前 {path_length}）")

    # 摩尔吸光系数 ε = A / (c * l)
    epsilon = absorption / (concentration * path_length)

    return {
        'absorption_coefficient': epsilon,
        'wavelengths': data['wl'],
        'path_length': path_length,
        'concentration': concentration,
        'units': 'M^-1 cm^-1',
    }


# ======================== 4. 命令行接口 ========================

def main():
    """命令行接口"""
    parser = argparse.ArgumentParser(description='吸收光谱批量绘图工具')
    parser.add_argument('files', nargs='+', help='CSV 文件路径或通配符')
    parser.add_argument('-o', '--output', default='./plots', help='输出目录')
    parser.add_argument('--no-show', action='store_true', help='不显示图像')
    parser.add_argument('--normalize', action='store_true', help='合并图归一化')
    parser.add_argument('--no-peaks', action='store_true', help='不标注峰')
    parser.add_argument('--no-single', action='store_true', help='不绘制单独图')
    parser.add_argument('--no-combined', action='store_true', help='不绘制合并图')
    parser.add_argument('--peak-height', type=float, default=0.1, help='峰高阈值')
    parser.add_argument('--peak-distance', type=int, default=10, help='峰间距')
    parser.add_argument('--peak-prominence', type=float, default=0.05, help='峰突出度')
    parser.add_argument('--smooth', action='store_true', help='曲线平滑')
    parser.add_argument('--smooth-factor', type=int, default=1, help='平滑倍数')
    parser.add_argument('--xlim', type=float, nargs=2, help='波长范围 XMIN XMAX')
    parser.add_argument('--ylim', type=float, nargs=2, help='吸收值范围 YMIN YMAX')
    parser.add_argument('--title', type=str, help='图表标题')
    
    args = parser.parse_args()
    
    # 读取数据
    datasets = load_absorption_spectra(args.files)
    
    # 绘图参数
    plot_kwargs = {
        'save_dir': args.output,
        'show': not args.no_show,
        'annotate_peaks': not args.no_peaks,
        'peak_height': args.peak_height,
        'peak_distance': args.peak_distance,
        'peak_prominence': args.peak_prominence,
        'smooth': args.smooth,
        'smooth_factor': args.smooth_factor,
        'xlim': tuple(args.xlim) if args.xlim else None,
        'ylim': tuple(args.ylim) if args.ylim else None,
        'title': args.title,
        'plot_individual': not args.no_single,
        'plot_combined': not args.no_combined,
        'normalize': args.normalize,
    }
    
    # 执行绘图
    plot_absorption_spectra(datasets=datasets, **plot_kwargs)


if __name__ == "__main__":
    main()