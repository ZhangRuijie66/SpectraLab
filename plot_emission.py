"""
荧光发射光谱 CSV 批量绘图工具
适用格式：
  1. Spectracle / FE30 输出的"发射数据组" CSV 文件
  2. LabSolutions RF / RF-6000 输出的 Emission CSV 文件（如 D2O.csv）
  3. PerkinElmer FL WinLab 风格的发射扫描 CSV（如 EmScan1.csv，含 Labels/Type/
     Fixed-Offset/XAxis 字段，纯英文无中文表头）
功能：单图 + 合并图，自动提取 EX WL 等信息，自动检测格式

【多光谱数据直接引用函数】
  具有多个光谱数据时，可直接引用以下函数：
    - load_spectra(files)      ：批量解析多个 CSV → 全部光谱数据集（扁平列表）
    - plot_spectra(files, ...) ：一键画出【每条单独图】+【合并图】，并返回数据集
    - plot_single(dataset, ...)：传单个 dict 或 dict 列表，逐条画出单独图
    - plot_combined(datasets,.):传 dict 列表，画一张合并对比图
  激发光谱（Spectrum Type=Excitation）默认跳过：load_spectra / plot_spectra /
  plot_single / plot_combined 均默认 skip_excitation=True（可传 False 关闭）。
  详见各函数 docstring 与 使用说明。

合并图的颜色按样品身份（label/name）分配并记忆：增删数据集时已有曲线的颜色
不变。换一批数据时调用 reset_curve_colors() 清空，详见 curve_colors.py。
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
from curve_colors import CurveColors

# 导出口径单一来源（v5.0.2）：GUI 与根目录各 plot_*.py 共用同一组 DPI。
try:
    from export_defaults import (EXPORT_DPI_DEFAULT,
                                 EXPORT_DPI_VECTOR_MIN,
                                 EXPORT_DPI_PREVIEW)
except ImportError:                     # 脚本被单独复制出去时退回字面量
    EXPORT_DPI_DEFAULT, EXPORT_DPI_VECTOR_MIN, EXPORT_DPI_PREVIEW = 600, 300, 150


# ======================== 0. 中文字体设置 ========================

def _safe_print(*args):
    """安全打印：在某些终端/编码（如 GBK、ASCII）下避免因非 ASCII 字符崩溃"""
    try:
        print(*args)
    except Exception:
        pass


def setup_chinese_font():
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

def _normalize_intensity(y):
    """把一条光谱归一化到「峰高 = 1」（v4.44）。

    旧写法 ``y / np.nanmax(y)`` 对本底没扣干净、带负基线的谱会爆：
    实测 EtOH 空白谱 min=-66.1 / max=6.04，除完最低到 -10.95，
    整张合并图纵轴被拉到 (-12.15, 2.2)，真实样品(0~1)只剩 8.4% 图高。

    新口径：先减最小值（扣基线）再除峰值。对本来正、基线≈0 的谱结果与旧口径
    几乎一致；对带负基线的谱保证落在 [0, 1]。全常量谱原样返回。
    """
    y = np.asarray(y, dtype=float)
    if y.size == 0:
        return y
    finite = np.isfinite(y)
    if not finite.any():
        return y
    lo = float(np.nanmin(y[finite]))
    hi = float(np.nanmax(y[finite]))
    if not np.isfinite(hi - lo) or (hi - lo) <= 0:
        return y
    return (y - lo) / (hi - lo)


def clean_array(arr):
    """去除 NaN 和 Inf"""
    arr = np.asarray(arr, dtype=float)
    mask = np.isfinite(arr)
    return arr[mask]


def detect_format(filepath):
    """
    自动检测 CSV 格式：
      - 'flwinlab': PerkinElmer FL WinLab 风格（Labels/Type/Fixed-Offset/XAxis）→ 本批新增
      - 'rf6000': LabSolutions RF / RF-6000 格式
      - 'spectracle': Spectracle / FE30 格式
        （返回 'spectracle' 但文件其实是寿命衰减时，由 :func:`detect_decay_file`
         在调用方拦下——见该函数说明）
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

    if 'RF-6000' in head or 'LabSolutions RF' in head or 'D2O - CorrectionData' in head:
        return 'rf6000'
    # PerkinElmer FL WinLab 风格：元数据含 Fixed/Offset、XAxis 字段
    # （如 Labels,EmScan1, / Type,Emission Scan / Fixed/Offset,570.00 / XAxis,Wavelength）
    # 注意：Horiba/DeltaHub 的寿命衰减文件**同样**含 Fully/Offset 与 XAxis 字段
    # （Type,Time Scan / XAxis,Time(ns)），此前被这里一并判成 flwinlab 而当成
    # 发射光谱收下。判别交给 detect_decay_file()，本函数保持"格式族"语义不变。
    elif ('Fixed/Offset' in head or 'Fixed/Offsets' in head) and (
            'XAxis' in head or 'Xaxis' in head):
        return 'flwinlab'
    elif '波长' in head or '发射数据组' in head:
        return 'spectracle'
    else:
        # 尝试更宽松的 RF6000 检测：查找 "Wavelength nm." 或类似
        if re.search(r'Wavelength\s*nm', head, re.IGNORECASE):
            return 'rf6000'
        # 默认尝试 spectracle
        return 'spectracle'


# 时间扫描文件的判别标记：XAxis 声明的量 + Type 声明的扫描类型。
# 两者任一命中即视为"寿命/衰减"数据，不该进发射光谱模式（v5.0.4）。
_DECAY_XAXIS_PAT = re.compile(r'^\s*XAxis\s*,\s*(Time|Temps?|Channel)', re.IGNORECASE)
_DECAY_TYPE_PAT = re.compile(r'(Time\s*Scan|Decay|Lifetime|Phosphorescence\s*Decay)',
                             re.IGNORECASE)


def detect_decay_file(filepath):
    """判断一个 CSV 是不是**时间扫描/衰减**数据（而非光谱）。

    返回 ``(is_decay, evidence)``；``evidence`` 是命中的原文，便于在提示里
    告诉用户"凭什么认为它是衰减文件"。

    v5.0.4 新增。此前 ``detect_format`` 把 Horiba/DeltaHub 的衰减文件判成
    'flwinlab'，``parse_flwinlab_csv`` 又把"前两列都是数值"的行全当光谱点，
    于是一份 400 µs 的衰减曲线被当成"波长 0–399900 nm 的发射光谱"收下，
    ``_load_errors`` 一条不记、弹窗一条不出。实测该文件 header 里
    ``Type,Time Scan`` 与 ``XAxis,Time(ns)`` 都写得明明白白——
    解析器读到了，却没有任何地方消费。

    只读文件头 60 行，不做完整解析，成本可忽略。
    """
    try:
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            head = ''.join(f.readline() for _ in range(60))
    except OSError:
        return False, ''
    for pat in (_DECAY_XAXIS_PAT, _DECAY_TYPE_PAT):
        m = pat.search(head)
        if m:
            return True, m.group(1).strip()
    return False, ''


def parse_rf6000_csv(filepath):
    """
    解析 LabSolutions RF / RF-6000 输出的 Emission CSV
    格式特点：
      - 前半部分是 [Software Information], [Data Information],
        [Instrument Information], Parameter, [Measurement] 等元数据
      - 后半部分是 "D2O - CorrectionData" 后跟 "Wavelength nm.,Intensity"
      - 单通道数据，EX Wavelength 在元数据中
      - 行之间列数不一致，不能直接用 pd.read_csv
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
    ex_wl_val = None
    spectrum_type = ''

    for line in lines:
        # 跳过空行
        stripped = line.strip()
        if not stripped:
            continue

        # 按逗号分割，保留原始列
        parts = [p.strip() for p in stripped.split(',')]

        # Sample Name (单独一行后跟值)
        if 'Sample Name' in parts:
            idx = next((i for i, p in enumerate(parts) if 'Sample Name' in p), -1)
            if idx >= 0 and idx + 1 < len(parts):
                val = parts[idx + 1]
                if val and val.lower() != 'nan':
                    sample_name = val

        # EX Wavelength: 格式 "EX Wavelength:,570.0 nm" 或 "EX Wavelength:570.0 nm"
        for p in parts:
            if 'EX Wavelength' in p:
                match = re.search(r'EX\s*Wavelength[:\s]*([\d.]+)', p)
                if match:
                    ex_wl_val = float(match.group(1))
            # 也可能值在下一列
            if ex_wl_val is None and len(parts) > 1:
                for j, p2 in enumerate(parts):
                    if 'EX Wavelength' in p2 and j + 1 < len(parts):
                        match = re.search(r'([\d.]+)', parts[j + 1])
                        if match:
                            ex_wl_val = float(match.group(1))

        # Spectrum Type
        for p in parts:
            if 'Spectrum Type' in p:
                idx = next((i for i, p2 in enumerate(parts) if 'Spectrum Type' in p2), -1)
                if idx >= 0 and idx + 1 < len(parts):
                    val = parts[idx + 1]
                    if val and val.lower() != 'nan':
                        spectrum_type = val

    # --- 找到数据起始行 ---
    # 特征：包含 "Wavelength nm." 的行（数据表头）
    data_start = None
    for i, line in enumerate(lines):
        if re.search(r'Wavelength\s*nm', line, re.IGNORECASE):
            data_start = i + 1  # 数据从下一行开始
            break

    if data_start is None:
        raise ValueError("未找到 'Wavelength nm.' 数据表头行，文件格式可能不匹配")

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

    wl_clean = np.array(wl_list, dtype=float)
    int_clean = np.array(int_list, dtype=float)

    if len(wl_clean) == 0:
        raise ValueError("未找到有效光谱数据")

    if sample_name == '' or sample_name == 'nan':
        sample_name = Path(filepath).stem

    # 显示标签
    display_label = sample_name
    if spectrum_type and spectrum_type not in ('nan', ''):
        display_label += f" ({spectrum_type})"

    datasets = [{
        'label': display_label,
        'ex_wl': ex_wl_val,
        'wl': wl_clean,
        'intensity': int_clean,
        'spectrum_type': spectrum_type,  # 新增：记录光谱类型
    }]

    return datasets, lines


def parse_spectracle_csv(filepath):
    """
    解析 Spectracle / FE30 输出的发射扫描 CSV，自动定位数据起始行
    """
    # 先读取整个文件（无列名），所有列为字符串避免解析问题
    # 编码回退：pandas 默认 utf-8，仪器导出的 GBK/BOM 文件会直接抛 UnicodeDecodeError
    try:
        raw = pd.read_csv(filepath, header=None, dtype=str)
    except UnicodeDecodeError:
        raw = pd.read_csv(filepath, header=None, dtype=str, encoding='gbk')
    except FileNotFoundError:
        raise FileNotFoundError(f"文件不存在: {filepath}")

    # --- 找到数据起始行：搜索包含"波长"的行 ---
    data_start = None
    for i, row in raw.iterrows():
        if any("波长" in str(v) for v in row.values):
            data_start = i + 1  # 数据从波长行的下一行开始
            break

    if data_start is None:
        raise ValueError("未找到'波长(nm)'行，文件格式可能不匹配")

    # 元数据 = 数据起始行之前的所有行
    meta = raw.iloc[:data_start, :]

    # --- 提取标签（第 1 行，真正的值在 col 1 和 col 4） ---
    labels = []
    for col in [1, 4]:
        raw_val = str(meta.iloc[0, col]).strip()
        labels.append(raw_val if raw_val != 'nan' else 'Unknown')

    # --- 提取 EX WL：搜索包含"EX WL"的行 ---
    ex_wls = [None, None]
    for i, row in meta.iterrows():
        for col_idx, result_idx in [(0, 0), (3, 1)]:
            cell = str(row.iloc[col_idx])
            if "EX WL" in cell:
                try:
                    ex_wls[result_idx] = float(row.iloc[col_idx + 1])
                except (ValueError, IndexError):
                    pass

    # --- 提取评论：搜索包含"评论"的行 ---
    comments = ["", ""]
    for i, row in meta.iterrows():
        for col_idx, result_idx in [(0, 0), (3, 1)]:
            cell = str(row.iloc[col_idx])
            if "评论" in cell:
                comments[result_idx] = str(row.iloc[col_idx + 1]).strip()

    # --- 读取数值数据 ---
    data = raw.iloc[data_start:, :]

    def get_pair(wl_col, int_col):
        """按**行**对齐地取一对 (波长, 强度)。

        旧实现分别对两列做去 NaN 再按 min_len 截断：只要某一列中间有一个空
        单元格，两列删掉的行就不同，截断后 wl[i] 与 intensity[i] 不再对应
        同一行（谱峰位置会整体错位，而曲线看起来仍然"漂亮"）。
        """
        wl = pd.to_numeric(data.iloc[:, wl_col], errors='coerce').to_numpy(
            dtype=float)
        it = pd.to_numeric(data.iloc[:, int_col], errors='coerce').to_numpy(
            dtype=float)
        mask = np.isfinite(wl) & np.isfinite(it)
        return clean_array(wl[mask]), clean_array(it[mask])

    # 列：0=WL1, 1=Int1, 3=WL2, 4=Int2   (2 和 5 是空列)
    datasets = []
    for label, comment, wl_col, int_col in zip(labels, comments, [0, 3], [1, 4]):
        wl_clean, int_clean = get_pair(wl_col, int_col)
        # 构建显示标签：标签名 + 评论
        display_label = label
        if comment and comment not in ('nan', '', ):
            display_label += f" ({comment})"
        datasets.append({
            'label': display_label,
            'ex_wl': ex_wls[len(datasets)],
            'wl': wl_clean,
            'intensity': int_clean,
        })

    return datasets, raw


def parse_flwinlab_csv(filepath):
    """
    解析 PerkinElmer FL WinLab 风格输出的发射扫描 CSV（如 EmScan1.csv）。

    文件结构（纯文本，无中文表头）：
      - 元数据块（每行 kv 对，第三列通常为空）：
          Labels,EmScan1,
          Type,Emission Scan,
          Comment,,
          Start,230.00,
          Stop,850.00,
          Step,0.500,
          Fixed/Offset,570.00,     ← 固定波长（发射扫描时的激发波长）
          XAxis,Wavelength,
          YAxis,Counts,
      - 空行
      - 数据块：<波长>,<强度>,     （每行两列，末尾多有逗号）

    该格式行宽不一致、含非数值元数据行，不能直接用 pd.read_csv，
    因此按行解析：只把"前两列都能转成数值"的行当作光谱数据。
    """
    # --- 读取原始文本（尝试多种编码） ---
    encodings = ['utf-8', 'utf-8-sig', 'gbk', 'latin-1']
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

    # --- 从元数据行中提取字段 ---
    label = ''
    spectrum_type = ''
    ex_wl = None
    xaxis = ''
    yaxis = ''
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        parts = [p.strip() for p in stripped.split(',')]
        if not parts:
            continue
        key = parts[0]
        val = parts[1] if len(parts) > 1 else ''
        if key == 'Labels':
            label = val
        elif key == 'Type':
            spectrum_type = val
        elif key == 'Fixed/Offset':
            try:
                ex_wl = float(val)
            except ValueError:
                ex_wl = None
        elif key == 'XAxis':
            xaxis = val
        elif key == 'YAxis':
            yaxis = val

    # --- 逐行读取数据：只取前两列均为数值的行 ---
    wl_list = []
    int_list = []
    for line in lines:
        stripped = line.strip()
        if not stripped or ',' not in stripped:
            continue
        parts = [p.strip() for p in stripped.split(',')]
        if len(parts) < 2:
            continue
        try:
            wl_val = float(parts[0])
            int_val = float(parts[1])
        except ValueError:
            # 元数据行（如 "Start,230.00," 的 key 不是数值）会被跳过
            continue
        wl_list.append(wl_val)
        int_list.append(int_val)

    wl_clean = clean_array(np.array(wl_list, dtype=float))
    int_clean = clean_array(np.array(int_list, dtype=float))

    if len(wl_clean) == 0:
        raise ValueError("未找到有效光谱数据")

    if not label or label == 'nan':
        label = Path(filepath).stem

    # 显示标签：标签名 +（光谱类型），与 rf6000 解析保持一致
    display_label = label
    if spectrum_type and spectrum_type not in ('nan', ''):
        display_label += f" ({spectrum_type})"

    datasets = [{
        'label': display_label,
        'ex_wl': ex_wl,
        'wl': wl_clean,
        'intensity': int_clean,
        'spectrum_type': spectrum_type,  # 'Emission Scan'，不会触发跳过
        'xaxis': xaxis,
        'yaxis': yaxis,
    }]

    return datasets, lines


def parse_csv(filepath):
    """
    统一入口：自动检测格式并解析。

    v5.0.4：**时间扫描/衰减文件直接抛错**，不再当成发射光谱返回。
    见 :func:`detect_decay_file` 的说明。
    """
    is_decay, ev = detect_decay_file(filepath)
    if is_decay:
        raise ValueError(
            f"这是时间扫描/衰减数据（头部命中「{ev}」），不是发射光谱。"
            f"请用「荧光寿命」模式打开。")
    fmt = detect_format(filepath)
    print(f"  📋 检测到格式: {fmt}")
    if fmt == 'rf6000':
        return parse_rf6000_csv(filepath)
    elif fmt == 'flwinlab':
        return parse_flwinlab_csv(filepath)
    else:
        return parse_spectracle_csv(filepath)


def _expand_files(files):
    """把单个路径或路径列表展开为文件列表；支持通配符（跨 shell 有效）。"""
    if isinstance(files, (str, Path)):
        files = [files]
    out = []
    for f in files:
        s = str(f)
        if any(ch in s for ch in '*?['):
            out.extend(sorted(glob.glob(s)))
        else:
            out.append(s)
    return out


def load_spectra(files, skip_excitation=True, verbose=True, errors=None):
    """批量解析多个 CSV 文件，返回全部光谱数据集（扁平列表）。

    参数
    ----
    files : str / Path / list
        一个或多个 CSV 路径，支持通配符（如 "*.csv"、"data/*.csv"）。
    skip_excitation : bool
        是否跳过 Spectrum Type=Excitation 的激发光谱（默认跳过）。
    verbose : bool
        是否打印解析进度。
    errors : list | None
        v5.0.4：传入列表时，把**每个失败文件**的原因追加进去
        ``(文件名, 原因)``。此前失败原因直接被丢弃，GUI 只能报"跳过 N 个"
        而说不出为什么——衰减文件被误当光谱收下时用户更无从发现。

    返回
    ----
    list[dict]：每个元素为
        {'label', 'ex_wl', 'wl', 'intensity', 'spectrum_type'}
    """
    all_datasets = []
    for f in _expand_files(files):
        if verbose:
            print(f"\n📄 处理: {f}")
        try:
            datasets, _ = parse_csv(f)
        except Exception as e:
            print(f"  ❌ 解析失败: {e}")
            if errors is not None:
                errors.append((Path(f).name, str(e)))
            continue
        for ds in datasets:
            stype = str(ds.get('spectrum_type', ''))
            if skip_excitation and stype.lower() == 'excitation':
                if verbose:
                    print(f"  ⏭️ 跳过 Excitation: {ds.get('label', '')}")
                continue
            if verbose:
                print(f"  → {ds['label']}: λ_ex={ds['ex_wl']} nm, "
                      f"数据点={len(ds['wl'])}")
            all_datasets.append(ds)
    return all_datasets


# ======================== 2. 绘图 ========================

def _is_excitation(ds):
    """判断是否为激发光谱（Spectrum Type=Excitation）。"""
    return str(ds.get('spectrum_type', '')).lower() == 'excitation'


def plot_single(dataset, save_dir=".", show=True, xlim=None, annotate_peaks=True,
                peak_height=0.05, peak_distance=10, peak_prominence=0.03, show_ex=False,
                fname=None, dpi=None, skip_excitation=True):
    """绘制单条光谱图；传入多条（list）时逐条各画一张。

    参数
    ----
    dataset : dict 或 list[dict]
        单个光谱数据，或多条光谱数据的列表（列表时逐条绘制，每条一张图）。
        数据字典键：label（或 name）/ ex_wl（或 ex）/ wl / intensity。
    save_dir : str/Path
        输出目录（自动创建）。
    show : bool
        是否弹出图像窗口（False 时仅保存文件）。
    xlim : tuple/None
        横轴波长范围（nm），如 (400, 700)；None 为全范围。
    annotate_peaks : bool
        是否自动找峰并标注。
    peak_height / peak_distance / peak_prominence
        自动标峰参数，见主程序说明。
    show_ex : bool
        是否用红色虚线标注激发波长位置。
    fname : str/None
        输出文件名；None 时由 label 自动生成（多条时共用该名会互相覆盖，
        建议多条时留空让每条自动命名）。
    dpi : int
        输出分辨率（默认 200）。
    skip_excitation : bool
        是否跳过 Spectrum Type=Excitation 的激发光谱（默认跳过；
        如需单独查看激发光谱可传 False）。

    返回
    ----
    list[Path]：已保存的文件路径列表。
    """
    if isinstance(dataset, (list, tuple)):
        if skip_excitation:
            kept = []
            for ds in dataset:
                if _is_excitation(ds):
                    print(f"  ⏭️ 跳过 Excitation: "
                          f"{ds.get('label') or ds.get('name', '')}")
                else:
                    kept.append(ds)
            dataset = kept
        saved = []
        for ds in dataset:
            saved.extend(plot_single(ds, save_dir=save_dir, show=show, xlim=xlim,
                                     annotate_peaks=annotate_peaks,
                                     peak_height=peak_height,
                                     peak_distance=peak_distance,
                                     peak_prominence=peak_prominence,
                                     show_ex=show_ex, fname=fname, dpi=dpi,
                                     skip_excitation=skip_excitation))
        return saved

    label = dataset.get('label') or dataset.get('name') or 'spectrum'
    ex_wl = dataset.get('ex_wl', dataset.get('ex'))
    wl, intensity = dataset['wl'], dataset['intensity']

    if skip_excitation and _is_excitation(dataset):
        print(f"  ⏭️ 跳过 Excitation: {label}")
        return []

    if len(wl) == 0:
        print(f"  ⚠️  跳过 {label}：无有效数据")
        return []

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(wl, intensity, linewidth=1.2, color='steelblue')

    # --- 自动找峰并标注 ---
    if annotate_peaks:
        y_max = np.nanmax(intensity)
        height = y_max * peak_height
        peaks, props = find_peaks(
            intensity,
            height=height,
            distance=peak_distance,
            prominence=y_max * peak_prominence,
        )
        if len(peaks) > 0:
            peak_wls = wl[peaks]
            peak_ints = intensity[peaks]
            # 竖虚线标记
            for pw in peak_wls:
                ax.axvline(pw, color='darkorange', linestyle=':', alpha=0.6, linewidth=0.8)
            # 文字标注
            for pw, pi in zip(peak_wls, peak_ints):
                ax.annotate(
                    f'{pw:.0f} nm',
                    xy=(pw, pi),
                    xytext=(0, 5),
                    textcoords='offset points',
                    fontsize=10,
                    color='darkorange',
                    ha='center',
                    va='bottom',
                    rotation=0,
                )

            print(f"     🔺 检测到 {len(peaks)} 个峰: {', '.join(f'{p:.0f}' for p in peak_wls)} nm")

    if show_ex and ex_wl is not None:
        ax.axvline(ex_wl, color='red', linestyle='--', alpha=0.6,
                   linewidth=1, label=f'EX = {ex_wl:.0f} nm')
        ax.legend(fontsize=9)

    title = f"{label}"
    if ex_wl is not None:
        title += f"  (EX = {ex_wl:.0f} nm)"
    ax.set_title(title, fontsize=13)
    ax.set_xlabel("波长 (nm)")
    ax.set_ylabel("强度 (AU)")
    ax.grid(True, alpha=0.3)

    x_min, x_max = np.nanmin(wl), np.nanmax(wl)
    ax.set_xlim(x_min, x_max)

    # 根据 xlim 自动调整 y 轴范围
    if xlim is not None:
        ax.set_xlim(xlim)
        mask = (wl >= xlim[0]) & (wl <= xlim[1])
        int_in_zoom = intensity[mask]
        if len(int_in_zoom) > 0:
            y_min = np.nanmin(int_in_zoom)
            y_max = np.nanmax(int_in_zoom)
            y_margin = (y_max - y_min) * 0.15
            ax.set_ylim(y_min - y_margin, y_max + y_margin)
    else:
        y_min, y_max = np.nanmin(intensity), np.nanmax(intensity)
        y_margin = (y_max - y_min) * 0.15
        ax.set_ylim(y_min - y_margin, y_max + y_margin)

    fig.tight_layout()
    if fname is None:
        fname = f"{label.replace('/', '_').replace(' ', '_')}.png"
    fname = Path(fname)
    if not fname.is_absolute():
        fname = Path(save_dir) / fname
    fig.savefig(fname, dpi=EXPORT_DPI_DEFAULT if dpi is None else dpi)
    print(f"  ✔ 已保存: {fname}")

    if show:
        plt.show()
    else:
        plt.close(fig)

    return [fname]


def plot_combined(datasets, save_dir=".", show=True, normalize=False, xlim=None,
                  annotate_peaks=True, peak_height=0.05, peak_distance=10, peak_prominence=0.03,
                  fname=None, dpi=None, skip_excitation=True):
    """绘制合并对比图（多条光谱叠加在一张图上）。

    参数
    ----
    datasets : list[dict]
        多条光谱数据（每条含 label / ex_wl（或 ex）/ wl / intensity）。
    save_dir : str/Path
        输出目录（自动创建）。
    show : bool
        是否弹出图像窗口。
    normalize : bool
        是否将每条光谱归一化到 [0,1]。
    xlim : tuple/None
        横轴波长范围（nm）。
    annotate_peaks / peak_height / peak_distance / peak_prominence
        自动标峰参数。
    fname : str/None
        合并图文件名（默认 combined_emission.png）。
    dpi : int
        输出分辨率（默认 200）。
    skip_excitation : bool
        是否跳过 Spectrum Type=Excitation 的激发光谱（默认跳过）。

    返回
    ----
    Path 或 None：保存的文件路径；有效数据不足 2 条时返回 None。
    """
    valid = [ds for ds in datasets if len(ds['wl']) > 0]
    if skip_excitation:
        for ds in datasets:
            if _is_excitation(ds):
                print(f"  ⏭️ 跳过 Excitation: "
                      f"{ds.get('label') or ds.get('name', '')}")
        valid = [ds for ds in valid if not _is_excitation(ds)]
    if len(valid) < 2:
        print("  ⚠️  有效数据不足 2 条，跳过合并图")
        return None

    fig, ax = plt.subplots(figsize=(10, 6))
    # 按样品身份稳定取色：增删数据集时已有曲线的颜色不变（见 curve_colors.py）
    colors = [_color_assigner.get(ds.get('label') or ds.get('name') or f"spectrum_{j}",
                                  plt.cm.Set1)
              for j, ds in enumerate(valid)]

    for i, ds in enumerate(valid):
        y = ds['intensity'].astype(float)
        if normalize:
            # v4.44：改为「扣基线后按峰高归一」。旧写法 y/nanmax(y) 在带负基线
            # 的谱上会爆（实测 EtOH 空白谱 min=-66.1/max=6.04，除完到 -10.95，
            # 纵轴被撑到 (-12, 2)，真实样品全压成贴零线的细线）。
            # 与 GUI（gui_plot._normalize_intensity）保持同一口径。
            y = _normalize_intensity(y)

        lbl = ds.get('label') or ds.get('name') or f'spectrum_{i}'
        ex_wl = ds.get('ex_wl', ds.get('ex'))
        if ex_wl is not None:
            lbl += f" (EX={ex_wl:.0f}nm)"
        ax.plot(ds['wl'], y, linewidth=1.2, color=colors[i], label=lbl)

        # --- 自动找峰并标注（仅标注最高峰，避免合并图太乱） ---
        if annotate_peaks:
            y_max = np.nanmax(y)
            height = y_max * peak_height
            peaks, props = find_peaks(
                y,
                height=height,
                distance=peak_distance,
                prominence=y_max * peak_prominence,
            )
            if len(peaks) > 0:
                peak_wls = ds['wl'][peaks]
                peak_ints = y[peaks]
                for pw, pi in zip(peak_wls, peak_ints):
                    ax.annotate(
                        f'{pw:.0f}',
                        xy=(pw, pi),
                        xytext=(0, 3),
                        textcoords='offset points',
                        fontsize=10,
                        color=colors[i],
                        ha='center',
                        va='bottom',
                        rotation=0,
                        alpha=0.8,
                    )

    ax.set_title("发射光谱对比", fontsize=13)
    ax.set_xlabel("波长 (nm)")
    ax.set_ylabel("归一化强度" if normalize else "强度 (AU)")
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.3)

    if xlim is not None:
        ax.set_xlim(xlim)
        # 自动调整 y 轴以匹配 xlim 区间内的数据
        zoom_intensities = []
        for ds in valid:
            y = ds['intensity'].astype(float)
            if normalize:
                y = y / np.nanmax(y)
            mask = (ds['wl'] >= xlim[0]) & (ds['wl'] <= xlim[1])
            int_in_zoom = y[mask]
            if len(int_in_zoom) > 0:
                zoom_intensities.append(int_in_zoom)
        if zoom_intensities:
            all_zoom = np.concatenate(zoom_intensities)
            y_min = np.nanmin(all_zoom)
            y_max = np.nanmax(all_zoom)
            y_margin = (y_max - y_min) * 0.10
            ax.set_ylim(y_min - y_margin, y_max + y_margin)

    fig.tight_layout()
    if fname is None:
        fname = "combined_emission.png"
    fname = Path(save_dir) / fname
    fig.savefig(fname, dpi=EXPORT_DPI_DEFAULT if dpi is None else dpi)
    print(f"  ✔ 已保存: {fname}")

    if show:
        plt.show()
    else:
        plt.close(fig)

    return fname


def plot_spectra(files=None, datasets=None, save_dir=".", show=True, normalize=False,
                 xlim=None, show_ex=False, annotate_peaks=True, peak_height=0.05,
                 peak_distance=10, peak_prominence=0.03, single=True, combined=True,
                 skip_excitation=True, combined_fname=None, dpi=None, verbose=True):
    """【多光谱一键】解析 → 每条单独图 → 合并图。

    两种调用方式（二选一）：
      1) 直接传文件：
             plot_spectra(['a.csv', 'b.csv'], save_dir='结果')
         （支持通配符：plot_spectra('*.csv')）
      2) 传已解析好的数据：
             datasets = load_spectra(['a.csv', 'b.csv'])
             plot_spectra(datasets=datasets, save_dir='结果')

    参数
    ----
    files : str/Path/list，可选
        CSV 路径（支持通配符）。与 datasets 二选一，优先用 files。
    datasets : list[dict]，可选
        已解析的光谱数据集（load_spectra / parse_csv 的返回）。
    save_dir : str/Path
        输出目录（自动创建，默认当前目录）。
    show : bool
        是否弹出图像窗口（默认 True；批量建议 False）。
    normalize : bool
        合并图是否归一化到 [0,1]（默认 False）。
    xlim : tuple/None
        横轴波长范围（nm），如 (400, 700)；None 为全范围。
    show_ex : bool
        单独图是否标注激发波长虚线（默认 False）。
    annotate_peaks : bool
        是否自动标峰（默认 True）。
    peak_height / peak_distance / peak_prominence
        自动标峰参数（单独图与合并图共用）。
    single : bool
        是否绘制每条光谱的单独图（默认 True）。
    combined : bool
        是否绘制合并图（默认 True，需 ≥2 条有效数据才生成）。
    skip_excitation : bool
        是否跳过 Spectrum Type=Excitation 的激发光谱（默认 True；
        解析与绘图阶段均生效）。
    combined_fname : str/None
        合并图文件名（默认 combined_emission.png）。
    dpi : int
        输出分辨率（默认 200）。
    verbose : bool
        是否打印进度信息（默认 True）。

    返回
    ----
    list[dict]：解析得到的全部光谱数据集（便于后续继续调用
        plot_combined / export_peak_table 等复用）。
    """
    if datasets is None:
        if files is None:
            raise ValueError("必须提供 files 或 datasets 之一")
        datasets = load_spectra(files, skip_excitation=skip_excitation, verbose=verbose)

    Path(save_dir).mkdir(parents=True, exist_ok=True)

    if single:
        if verbose:
            print(f"\n📈 绘制单独图（共 {len(datasets)} 条光谱）...")
        plot_single(datasets, save_dir=save_dir, show=show, xlim=xlim,
                    annotate_peaks=annotate_peaks,
                    peak_height=peak_height, peak_distance=peak_distance,
                    peak_prominence=peak_prominence, show_ex=show_ex, dpi=dpi,
                    skip_excitation=skip_excitation)

    if combined:
        if verbose:
            print(f"\n📊 绘制合并图（共 {len(datasets)} 条光谱）...")
        plot_combined(datasets, save_dir=save_dir, show=show, normalize=normalize,
                      xlim=xlim, annotate_peaks=annotate_peaks,
                      peak_height=peak_height, peak_distance=peak_distance,
                      peak_prominence=peak_prominence,
                      fname=combined_fname, dpi=dpi,
                      skip_excitation=skip_excitation)

    return datasets


# ======================== 3. 主程序 ========================

def main():
    parser = argparse.ArgumentParser(
        description="荧光发射光谱 CSV → 单图 + 合并图（支持 Spectracle/FE30 和 RF-6000 格式）"
    )
    parser.add_argument(
        "files", nargs="+",
        help="一个或多个 CSV 文件路径（支持通配符）"
    )
    parser.add_argument(
        "-o", "--out", default="plots_emission",
        help="输出目录（默认: plots_emission）"
    )
    parser.add_argument(
        "--no-show", action="store_true",
        help="不弹出图像窗口"
    )
    parser.add_argument(
        "--normalize", action="store_true",
        help="合并图归一化到 [0,1]"
    )
    parser.add_argument(
        "--xlim", type=float, nargs=2, default=None,
        metavar=("XMIN", "XMAX"),
        help="手动指定横轴范围，如: --xlim 500 700"
    )
    parser.add_argument(
        "--show-ex", action="store_true",
        help="在单独图上标注激发波长虚线"
    )
    parser.add_argument(
        "--no-peaks", action="store_true",
        help="不自动标峰"
    )
    parser.add_argument(
        "--peak-height", type=float, default=0.05,
        help="峰高阈值（占最大值的比例，默认 0.05）"
    )
    parser.add_argument(
        "--peak-distance", type=float, default=10,
        help="峰最小间距（nm，默认 10）"
    )
    parser.add_argument(
        "--peak-prominence", type=float, default=0.03,
        help="峰突出度阈值（占最大值的比例，默认 0.03）"
    )
    parser.add_argument(
        "--no-single", action="store_true",
        help="不绘制每条单独图"
    )
    parser.add_argument(
        "--no-combined", action="store_true",
        help="不绘制合并图"
    )

    args = parser.parse_args()

    plot_spectra(
        files=args.files,
        save_dir=args.out,
        show=not args.no_show,
        normalize=args.normalize,
        xlim=args.xlim,
        show_ex=args.show_ex,
        annotate_peaks=not args.no_peaks,
        peak_height=args.peak_height,
        peak_distance=args.peak_distance,
        peak_prominence=args.peak_prominence,
        single=not args.no_single,
        combined=not args.no_combined,
    )

    print("\n✅ 完成！")


if __name__ == "__main__":
    main()
