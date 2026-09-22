"""
荧光寿命拟合模块：最大熵算法（MEM）+ IRF 重卷积
================================================

参考 FluoIt（Edward Kerman, MIT License）的算法移植而来，纯 numpy/scipy 实现，
不依赖 pyTorch / GPU。算法流程：

  1. preprocess  预处理：统计 IRF / 衰减曲线特征（峰位、FWHM、背景、上升沿），
                 并用 tail-fitting 粗略估计 IRF 与衰减曲线之间的时间位移 qshift，
                 同时确定参与拟合的数据区间 [fit_start, fit_end)
  2. fit         主拟合：
                 - 在对数坐标上取 n_rates 个速率 k（k = 1/tau）作为基函数，
                   预先与 IRF 卷积得到 201 条单指数衰减曲线 A
                 - 多起点粗估：SLSQP 最小化简化卡方，得到速率分布初值
                 - 最大熵迭代：轮流优化 (a) IRF 位移 qshift，(b) 速率分布 p，
                   目标函数为 chi^2 - lambda * S（S 为 Shannon 熵，
                   即在拟合数据的前提下最大化熵 → 最平滑/最fewest-assumption 的分布），
                   相邻两轮目标函数差 < res_tol 时终止
                 - lambda = lambda_coeff 为熵项权重（默认 1e-3，手动指定）；
                   勾选 auto_lambda 时自动拟合 λ：先按当前 λ 完整 MEM →
                   网格扫描 χ²R 不超过 lambda_target（默认 1.1）的最大 λ
                   （warm-start 轻量迭代）→ 用最优 λ 重新完整 MEM
  3. postprocess 对速率分布做多重高斯拟合，提取各寿命分量的 tau / 强度占比 / FWHM
  4. 绘图        衰减曲线拟合图（含残差、chi^2_R）+ 寿命分布图（含各高斯分量）

数据幅度：拟合窗口的噪声判据含绝对下限 10 计数，因此**输入应为光子计数**。
若数据是被归一化成峰值 ≈ 1 的相对强度（作业/交换数据的常见形态），
preprocess 会先自动还原到计数刻度再定窗口（v4.32，见
MEMFitter._rescale_if_normalized），否则整个衰减会被判成噪声、窗口退化成 50 点。

适用数据格式（自动检测）：
  1. Horiba / DeltaHub 时间扫描 CSV（如 Decay2.csv）：
       文件头部含 Labels,Decay2,IR1 / Type,Time Scan,Instrument Response... 等元数据，
       数据区为三列：time, decay, irf（行尾允许有多余逗号）
  2. 简单三列表格 CSV：第一列 time，第二列 decay，第三列 irf，可有表头
  3. 多列衰减 xlsx（见 parse_decay_xlsx）：首行表头含时间列 + 样品列 + IRF 列，
       支持「多样品共用单个 IRF」与「每样品各配一份 IRF（成对交替）」两种布局，
       后者的典型表头如：Time (ns) | 0nM | IRF | 50nM | IRF | ... | 500nM | IRF

【一键使用】
  import plot_lifetime
  results = plot_lifetime.fit_lifetime(
      files="D:/.../Decay2.csv",   # 支持通配符 / 列表
      save_dir="./plots",          # 图与 json 结果的保存目录
      method="MEM",                # "MEM"（最大熵）或 "SESM"（平滑指数序列，更快）
      show=False,                  # 是否弹出窗口
  )
  返回 list[dict]，每个 dict 含 k、k_distribution、peak_result、info 等全部结果

【导出拟合结果（表格 + 报告）】
  # 把一批拟合结果整理成汇总表（CSV + XLSX）与每个文件的 Markdown 报告：
  written = plot_lifetime.export_fit_results(
      results, save_dir="./plots", name="lifetime_fit_results")
  # 字段：文件名 / 方法 / χ²R / qshift(ch,ns) / IRF_FWHM(ns) / 各 τ_i(ns) / 占比_i(%)

【时间单位（v4.39）】
  所有绘图 / 报告 / 汇总表接口都有 time_unit 关键字参数（'ns' 或 'us'，默认 'ns'）。
  它**只影响显示与坐标轴/表头标签**：选 'us' 时以 ns 为单位的数值会除以 1000、标签换成 μs；
  内部一切计算、结果 dict 与 json 输出始终用 ns（单位换算见 to_ns / from_ns）。
  time_unit='ns' 时所有输出与旧版逐字一致。

【命令行】
  python plot_lifetime.py -i "D:/.../Decay2.csv" [-o ./plots] [-m MEM] [--show]
                          [--time-unit {ns,us}]   # 仅影响显示/输入，内部仍用 ns
                          [--export]            # 拟合后额外导出 CSV/XLSX 汇总表 + md 报告

依赖：numpy, scipy, pandas, matplotlib
"""

import argparse
import glob
import json
import math
import io
import os
import re
from pathlib import Path

import numpy as np
import pandas as pd
import scipy.interpolate
import scipy.optimize
import scipy.signal

import matplotlib
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec


# ======================== 0. 基础设置 ========================

# ---- 归一化数据自动还原（v4.32）----
# 衰减峰值低于 _NORMALIZED_PEAK_MAX 视为"已归一化的相对强度"而非光子计数。
# 真实 TCSPC 计数数据峰值在 10³~10⁵（工作区实测最低 3×10³），所以 10 这个门槛
# 既不会误伤真实数据，又能抓住峰值 = 1 的归一化数据。
# 触发后把数据整体乘到 _RESCALE_TARGET_PEAK——一个典型的中等计数峰值，
# 使噪声判据里的绝对下限 10 与 1.5×本底重新落在有物理意义的量级上。
_NORMALIZED_PEAK_MAX = 10.0
_RESCALE_TARGET_PEAK = 10000.0

# 拟合窗口噪声判据里的绝对下限，以及"它还算地板"的判定倍率。
# 峰值 ≥ _NOISE_FLOOR × _NOISE_FLOOR_SAFE_RATIO（= 100）时下限才是地板；
# 更低的峰值下它成了天花板（全部通道都低于它 → 窗口退化），改用纯相对判据。
_NOISE_FLOOR = 10.0
_NOISE_FLOOR_SAFE_RATIO = 10.0


def _safe_print(*args):
    """安全打印：在 GBK / ASCII 终端下避免因非 ASCII 字符崩溃"""
    try:
        print(*args)
    except Exception:
        pass


# ---- v4.39：时间单位（仅影响显示/输入；内部计算始终用 ns）----
# 说明：time_unit 只用于「数值显示」与「坐标轴 / 表头标签」，所有内部计算、
# 数据结构与 json 输出仍然一律使用 ns；time_unit='ns' 时结果与旧版逐字一致。
TIME_UNIT_KEYS = ('ns', 'us')
TIME_UNIT_SYMBOLS = {'ns': 'ns', 'us': 'μs'}
TIME_UNIT_FACTORS = {'ns': 1.0, 'us': 1000.0}      # 1 个显示单位 = 多少 ns
TIME_UNIT_NAMES = {'ns': '纳秒 (ns)', 'us': '微秒 (μs)'}


def _normalize_time_unit(time_unit):
    """把 time_unit 归一化到 TIME_UNIT_KEYS 之一；未知值（含 None）一律回退 'ns'。"""
    if time_unit is None:
        return 'ns'
    key = str(time_unit).strip().lower()
    return key if key in TIME_UNIT_FACTORS else 'ns'


def unit_symbol(time_unit='ns'):
    """返回时间单位的显示符号：'ns' 或 'μs'（未知值一律回退 'ns'）。

    time_unit 只影响显示/输入，内部计算始终用 ns。
    """
    return TIME_UNIT_SYMBOLS[_normalize_time_unit(time_unit)]


def unit_factor(time_unit='ns'):
    """返回换算因子：1 个显示单位等于多少 ns（'ns'→1.0，'us'→1000.0）。

    未知值一律回退 'ns'（即 1.0）。time_unit 只影响显示/输入，内部计算始终用 ns。
    """
    return float(TIME_UNIT_FACTORS[_normalize_time_unit(time_unit)])


def to_ns(value, time_unit='ns'):
    """显示单位 → ns（内部单位）。支持 float / list / numpy 数组。

    标量输入返回 float，数组 / 列表输入返回 np.ndarray；
    time_unit 只影响显示/输入，内部计算始终用 ns。
    """
    out = np.asarray(value, dtype=float) * unit_factor(time_unit)
    return float(out) if np.ndim(out) == 0 else out


def from_ns(value, time_unit='ns'):
    """ns（内部单位）→ 显示单位。支持 float / list / numpy 数组。

    标量输入返回 float，数组 / 列表输入返回 np.ndarray；
    time_unit 只影响显示/输入，内部计算始终用 ns。
    """
    out = np.asarray(value, dtype=float) / unit_factor(time_unit)
    return float(out) if np.ndim(out) == 0 else out


def setup_chinese_font():
    candidates = [
        'Microsoft YaHei', 'SimHei', 'KaiTi', 'FangSong', 'SimSun',
        'PingFang SC', 'Hiragino Sans GB', 'Songti SC', 'STHeiti', 'Heiti SC',
        'Arial Unicode MS',
        'Noto Sans CJK SC', 'WenQuanYi Micro Hei',
    ]
    available = {f.name for f in matplotlib.font_manager.fontManager.ttflist}
    chosen = next((f for f in candidates if f in available), None)
    if chosen:
        plt.rcParams['font.sans-serif'] = [chosen, 'DejaVu Sans']
        plt.rcParams['axes.unicode_minus'] = False
        _safe_print(f"  [FONT] 使用中文字体: {chosen}")
    else:
        _safe_print("  [WARN] 未找到中文字体，将使用英文标签")
        plt.rcParams['font.sans-serif'] = ['DejaVu Sans']


setup_chinese_font()


class NumpyTypeEncoder(json.JSONEncoder):
    """让 numpy 数组/标量可以被 json 序列化"""
    def default(self, obj):
        if isinstance(obj, np.generic):
            return obj.item()
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return json.JSONEncoder.default(self, obj)


# ======================== 1. 数据读取 ========================

def _read_text_lines(filepath):
    """尝试多种编码读入文本行（自动处理 BOM / UTF-8 / GBK）。"""
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"文件不存在: {filepath}")
    for enc in ('utf-8-sig', 'utf-8', 'gbk'):
        try:
            with open(filepath, 'r', encoding=enc) as f:
                return f.read().splitlines()
        except UnicodeDecodeError:
            continue
    # latin-1 对任意字节都不会抛 UnicodeDecodeError，只能作为最后兜底
    with open(filepath, 'r', encoding='latin-1', errors='replace') as f:
        return f.read().splitlines()


def parse_decay_csv(filepath):
    """
    解析荧光衰减数据文件，自动检测格式。

    返回 dict：
      time  : (N,) 时间轴（ns）
      decay : (N,) 荧光衰减计数
      irf   : (N,) 仪器响应函数计数
      meta  : dict，包含 labels / 列名 / Step / Stop 等元数据（尽力而为）
    """
    lines = _read_text_lines(filepath)

    # ---- 格式一：Horiba / DeltaHub 时间扫描格式（含 Labels/Type/... 头部） ----
    labels_idx = None
    for i, line in enumerate(lines[:80]):
        first = line.split(',')[0].strip().strip('"')
        if first.lower() == 'labels':
            labels_idx = i
            break

    if labels_idx is not None:
        labels = [s.strip() for s in lines[labels_idx].split(',')[1:] if s.strip()]
        meta = {'labels': labels, 'format': 'horiba'}

        # 收集 Labels 行之后的 "key,value" 元数据（Start/Stop/Step/XAxis/...）
        for line in lines[labels_idx + 1:]:
            parts = [s.strip() for s in line.split(',')]
            if not parts[0]:
                break
            if parts[0].lower() == 'labels':
                continue
            meta[parts[0]] = parts[1] if len(parts) > 1 else ''

        # 数据区：Labels 行之后第一个首字段可解析为 float 的行
        start_idx = None
        for i in range(labels_idx + 1, len(lines)):
            first = lines[i].split(',')[0].strip()
            try:
                float(first)
                start_idx = i
                break
            except ValueError:
                continue
        if start_idx is None:
            raise ValueError(f"{filepath}: 找不到数据区")

        rows = []
        for line in lines[start_idx:]:
            parts = line.split(',')
            if len(parts) < 3:
                break
            try:
                rows.append([float(parts[0]), float(parts[1]), float(parts[2])])
            except ValueError:
                break  # 空行或尾部元数据 → 数据结束
        if len(rows) < 10:
            raise ValueError(f"{filepath}: 数据行过少 ({len(rows)})")
        arr = np.asarray(rows, dtype=float)
        if not np.all(np.diff(arr[:, 0]) > 0):
            arr = arr[np.argsort(arr[:, 0])]
        return {
            'time': arr[:, 0], 'decay': arr[:, 1], 'irf': arr[:, 2],
            'meta': meta,
        }

    # ---- 格式二：简单三列表格（自动跳过表头） ----
    # 用已按多编码读出的文本行解析（pandas 直接读文件会默认 utf-8，
    # GBK/BOM 文件会抛 UnicodeDecodeError），并按前三列对齐后再删空行，
    # 避免「第 4 列有文本备注」时整表被 dropna 清空
    body = '\n'.join(ln for ln in lines if not ln.lstrip().startswith('#'))
    try:
        df = pd.read_csv(io.StringIO(body), header=None)
    except Exception:
        df = pd.read_csv(io.StringIO(body), skiprows=1, header=None)
    df = df.apply(pd.to_numeric, errors='coerce')
    if df.shape[1] < 3:
        raise ValueError(
            f"{filepath}: 至少需要 3 列数据 (time, decay, irf)，"
            f"实际只有 {df.shape[1]} 列；若文件无 IRF 列则无法进行重卷积拟合"
        )
    arr = df.iloc[:, :3].dropna().to_numpy(dtype=float)
    if len(arr) < 10:
        raise ValueError(f"{filepath}: 前三列有效数据行过少 ({len(arr)})")
    order = np.argsort(arr[:, 0])
    arr = arr[order]
    return {
        'time': arr[:, 0], 'decay': arr[:, 1], 'irf': arr[:, 2],
        'meta': {'format': 'plain3col',
                 'columns_used': ('first3' if df.shape[1] > 3 else 'all')},
    }


def parse_decay_xlsx(filepath):
    """
    解析多列衰减 xlsx（作业数据格式）：首行表头 = 时间列 + 若干样品列 + IRF 列。

    支持两种布局（表头不区分大小写，含 "time" 的是时间轴，含 "irf" 的是
    仪器响应列）：

    1. 单 IRF 列（旧格式）::

        Time (ns) | S1 | S2 | S3 | IRF       # 所有样品共用一份 IRF

    2. 每样品各配一份 IRF（成对交替，如 FAM-aptamer 结合实验）::

        Time (ns) | 0nM | IRF | 50nM | IRF | ... | 500nM | IRF

       多个 IRF 列时优先按 (样品列, 紧随其后的 IRF 列) 配成对；
       非严格交替的表头则退回通用规则：每个样品列取「后紧邻 IRF 列」，
       没有则取「前紧邻 IRF 列」，再无则共用第一个 IRF 列。

    返回 list[dict]，每行:
      name  : 样品列名
      time  : (N,) 时间轴（ns）
      decay : (N,) 该样品的荧光衰减计数
      irf   : (N,) 该样品配对的仪器响应函数计数
      meta  : labels / 来源文件等
    """
    df = pd.read_excel(filepath, header=0)
    cols = [str(c).strip() for c in df.columns]
    time_idx = next((i for i, c in enumerate(cols) if 'time' in c.lower()), None)
    if time_idx is None:
        raise ValueError(f"{filepath}: 表头未找到时间列（列名需含 time）")
    irf_indices = [i for i, c in enumerate(cols) if 'irf' in c.lower()]
    if not irf_indices:
        raise ValueError(f"{filepath}: 表头未找到 IRF 列（列名需含 IRF）")

    # 只做数值化，不在这里整表 dropna：表里若有一列纯文本（备注/单位），
    # 整表 dropna 会把所有行删光，报「有效数据行过少」而与真实原因无关。
    # 真正的对齐在下面按 (时间列, 样品列, IRF 列) 三元组逐样品做。
    data = df.apply(pd.to_numeric, errors='coerce')

    if len(irf_indices) == 1:
        # 旧格式：所有样品共用唯一的 IRF 列
        irf_idx = irf_indices[0]
        pairs = [(i, irf_idx) for i in range(len(cols))
                 if i not in (time_idx, irf_idx)]
    else:
        # 多 IRF 列：优先识别「样品,IRF,样品,IRF,…」交替布局
        other = [i for i in range(len(cols)) if i != time_idx]
        irf_set = set(irf_indices)
        alternating = (len(other) == 2 * len(irf_indices)
                       and all(other[2 * k + 1] in irf_set
                               and other[2 * k] not in irf_set
                               for k in range(len(irf_indices))))
        if alternating:
            pairs = [(other[2 * k], other[2 * k + 1])
                     for k in range(len(irf_indices))]
        else:
            # 通用回退：每个样品列配「后紧邻 IRF 列 → 前紧邻 IRF 列 → 第一个」
            pairs = []
            for i in other:
                if i in irf_set:
                    continue
                if i + 1 in irf_set:
                    j = i + 1
                elif i - 1 in irf_set:
                    j = i - 1
                else:
                    j = irf_indices[0]
                pairs.append((i, j))

    datasets = []
    for i, irf_idx in pairs:
        cname = cols[i]
        # 按行对齐：同一行的时间 / 样品 / IRF 三个值都必须是有效数字
        sub = data.iloc[:, [time_idx, i, irf_idx]].dropna()
        if len(sub) < 10:
            continue  # 空列/说明列
        sub = sub.sort_values(by=sub.columns[0])
        t = sub.iloc[:, 0].to_numpy(dtype=float)
        decay = sub.iloc[:, 1].to_numpy(dtype=float)
        if not np.any(decay > 0):
            continue
        irf = sub.iloc[:, 2].to_numpy(dtype=float)
        meta = {'labels': [cname, cols[irf_idx]], 'format': 'xlsx-multicolumn',
                'source': str(filepath)}
        datasets.append({'name': cname, 'time': t, 'decay': decay,
                         'irf': irf, 'meta': meta})
    if not datasets:
        raise ValueError(f"{filepath}: 未找到可用的样品数据列"
                         "（需要时间列、样品列、IRF 列同时为有效数字且 ≥10 行）")
    return datasets


# ======================== 2. 求解器 ========================

class FitCancelled(Exception):
    """用户取消了拟合（由 cancel_cb 抛出）。"""


class MEMFitter:
    """
    最大熵荧光寿命拟合求解器（带 IRF 重卷积）

    用法:
        fitter = MEMFitter()
        fitter.from_file("Decay2.csv")   # 或 fitter.load(time, decay, irf)
        fitter.preprocess()
        fitter.fit()                     # method="MEM" 或 "SESM"
        fitter.postprocess()
        result = fitter.serialize("out.json")
    """

    def __init__(self, verbose=True, name=None):
        self.verbose = verbose
        self.name = name
        self.time = None
        self.decay = None
        self.irf = None
        self.k = None                # 速率轴 k = 1/tau
        self.k_distribution = None   # 速率分布（归一化权重）
        self.peak_result = None      # 各高斯分量: [tau, 强度占比, FWHM(k), 强度占比, 振幅占比]
        self.info = {}
        self.meta = {}

    # ---------- 数据载入 ----------

    def load(self, time, decay, irf, meta=None):
        """载入数据并做**入口校验**：长度一致、数值有限、时间轴单调递增。

        宁可在这里明确报错，也不要让 NaN/长度错位的数据一路走到拟合，
        最后给出 χ²R=nan 或"100% 单分量"这类看起来正常的错误结论。
        """
        time = np.asarray(time, dtype=float).ravel()
        decay = np.asarray(decay, dtype=float).ravel()
        irf = np.asarray(irf, dtype=float).ravel()
        if not (len(time) == len(decay) == len(irf)):
            raise ValueError(
                f"数据长度不一致: time={len(time)}, decay={len(decay)}, "
                f"irf={len(irf)}")
        if len(time) < 20:
            raise ValueError(f"数据点过少 ({len(time)})，无法做重卷积拟合")
        for tag, arr in (('time', time), ('decay', decay), ('irf', irf)):
            bad = ~np.isfinite(arr)
            if bad.any():
                raise ValueError(
                    f"{tag} 含 {int(bad.sum())} 个 NaN/Inf（首个位于第 "
                    f"{int(np.argmax(bad))} 个点），请先清洗数据")
        if not np.all(np.diff(time) > 0):
            raise ValueError("时间轴必须严格递增（存在重复或递减的时间点）")
        if not np.any(irf > 0):
            raise ValueError("IRF 全为 0，无法做重卷积拟合")
        self.time = time
        self.decay = decay
        self.irf = irf
        if meta is not None:
            self.meta = meta

    def from_file(self, filepath):
        data = parse_decay_csv(filepath)
        self.name = self.name or Path(filepath).stem
        self.load(data['time'], data['decay'], data['irf'], data['meta'])

    def _log(self, *args):
        if self.verbose:
            _safe_print(*args)

    # ---------- 预处理 ----------

    def _rescale_if_normalized(self, decay, irf):
        """把被归一化过的衰减数据还原到计数刻度（v4.32）。

        背景：拟合窗口的噪声判据是
        ``noise_level = max(decay_max/500, 10, 1.5×本底)``，其中 **10** 这个绝对
        下限是针对原始 TCSPC 光子计数写的——真实计数数据峰值在 10³~10⁵，本底几十，
        该下限几乎不生效。但作业/交换数据常被归一化成峰值 = 1 的**相对强度**，
        此时全部通道都 < 10，"低于噪声水平"的第一段就从衰减峰位开始触发，
        于是 ``fit_end = decay_max_pos - 1 < fit_start``，窗口被夹到 50 点下限，
        报"拟合点数不足（欠定）"——与真实数据质量无关。

        还原的依据：重卷积模型是幅度的线性函数、χ² 的 Neyman 权重取观测计数，
        二者同步缩放 → 近似不变。之所以只说"近似"：噪声判据里那个**绝对**下限 10
        在两种刻度下的相对强度不同（归一化刻度上峰值只到 1e4，下限相对更强），
        窗口端点会差几个通道，拟合参数随之有零点几个百分点的偏移。实测同一份数据
        用真实计数刻度与"归一化后自动还原"两种输入，主寿命差 0.07%
        （6.1053 ns vs 6.1007 ns）；而**不还原**时窗口退化成 50 点、τ 偏到 200 ns。
        所以还原恢复的是"噪声判据的物理量级"，不是逐位复现。

        判据：衰减峰值 < ``_NORMALIZED_PEAK_MAX`` 视为归一化（真实计数数据峰值
        远高于此，工作区实测最低 3×10³）。返回 (decay, irf)。
        """
        peak = float(np.max(np.abs(decay))) if decay.size else 0.0
        irf_peak = float(np.max(np.abs(irf))) if irf.size else 0.0
        normalized = peak < _NORMALIZED_PEAK_MAX
        self.info['decay_peak_before_rescale'] = peak
        self.info['irf_peak_before_rescale'] = irf_peak
        self.info['rescaled_from_normalized'] = bool(normalized)
        if not normalized:
            self.info['rescale_factor'] = 1.0
            return decay, irf
        if peak <= 0:
            # 全零/全非正：交给下游"峰值不超过本底"的检查报错，这里不动
            self.info['rescale_factor'] = 1.0
            return decay, irf
        factor = _RESCALE_TARGET_PEAK / peak
        self.info['rescale_factor'] = float(factor)
        self._log(f"[预处理] 检测到归一化数据（衰减峰值 {peak:.4g} < "
                  f"{_NORMALIZED_PEAK_MAX:g}），按 ×{factor:g} 还原到计数刻度"
                  f"（峰值 → {_RESCALE_TARGET_PEAK:g}）；"
                  "该换算不改变拟合结果，仅恢复噪声判据的物理意义")
        return decay * factor, irf * factor

    def preprocess(self, background_length=30):
        """
        预处理：统计 IRF / decay 特征，tail-fitting 估计时间位移 qshift，
        并确定拟合区间 [fit_start, fit_end)。

        **归一化数据自动还原（v4.32）**：见 _rescale_if_normalized。输入若是被
        归一化过的相对强度（峰值 ≤ 1）而非光子计数，会先整体还原到计数刻度，
        否则噪声判据里的 ``10`` 下限会把整个衰减判成噪声、把拟合窗口压到 50 点。
        """
        time = self.time.copy()
        irf = self.irf.copy()
        decay = self.decay.copy()
        # 先还原被归一化的数据，再做本底/噪声统计（两者都依赖绝对计数刻度）
        decay, irf = self._rescale_if_normalized(decay, irf)
        # 卡方与对数运算需要正值，把非正计数抬到 0.1
        decay[decay <= 0] = 0.1

        info = self.info
        data_len = len(decay)
        irf_max_pos = int(irf.argmax())
        irf_max = irf.max()
        decay_max_pos = int(decay.argmax())
        decay_max = decay.max()

        # IRF 半高宽
        irf_half = irf_max / 2
        irf_half_l_pos = int(np.argmax(irf >= irf_half))
        irf_half_r_pos = len(irf) - 1 - int(np.argmax((irf >= irf_half)[::-1]))
        info['irf_FWHM'] = time[irf_half_r_pos] - time[irf_half_l_pos]

        # 背景与上升沿
        # 本底窗口按定义只能取 IRF 上升（半高first crossing）之前的部分：
        # 短时间窗数据（如数字化谱图）IRF 峰可能落在默认 30 通道内，
        # 否则会把 IRF 峰圈进本底、导致上升沿检测失效
        bg_n = max(2, min(background_length, data_len // 4, irf_half_l_pos - 2))
        # IRF 与 decay 的本底统一用**中位数**：均值会被数字化谱图的本底尖峰抬高
        # （实测 Fig5_0M 前 11 通道均值 52.7，真实本底仅 ~10），中位数更接近真实
        # 本底，避免 fit_end 判据被噪声拽长。均值一并记录在 info 里便于回溯。
        irf_background = float(np.median(irf[0:bg_n]))
        decay_background = float(np.median(decay[0:bg_n]))
        info['irf_background_mean'] = float(irf[0:bg_n].mean())
        info['decay_background_mean'] = float(decay[0:bg_n].mean())
        info['decay_background_stat'] = 'median'
        if decay_max - decay_background <= 0:
            raise ValueError(
                f"衰减峰值 ({decay_max:.4g}) 不超过本底 ({decay_background:.4g})，"
                "数据中没有可拟合的衰减信号")
        decay_rise_level = decay_max / 1000 + decay_background
        irf_rise_level = irf_max / 1000 + irf_background

        def _rise_pos(curve, level, max_pos, bg):
            for i in range(5, len(curve)):
                if i - 2 >= max_pos:  # 已越过峰位仍未触发（异常情况）→ 直接取峰位
                    return max_pos
                if curve[i] > level and curve[i - 2:max_pos].min() > bg:
                    return i
            return max_pos

        decay_rise_pos = _rise_pos(decay, decay_rise_level, decay_max_pos, decay_background)
        irf_rise_pos = _rise_pos(irf, irf_rise_level, irf_max_pos, irf_background)

        # tail-fitting：粗略估计 IRF 与 decay 之间的时间位移（channels）
        qshift_fit_slice = slice(max(decay_rise_pos, irf_rise_pos), decay_max_pos + 2)
        qshift_scan = np.arange(-30, 30, 0.2)
        pchiped_irf = scipy.interpolate.PchipInterpolator(
            np.arange(0, len(irf)), irf, extrapolate=True
        )
        guess_decay = np.zeros(data_len)
        guess_decay[:data_len - decay_max_pos] = decay[decay_max_pos:]
        guess_decay -= decay_background
        guess_decay[guess_decay < 0] = 0
        guess_decay = (guess_decay * (decay_max / max(guess_decay.max(), 1e-12))
                       ).astype(int)
        chi_sqr_best = np.inf
        qshift_suggested = 0.0
        # 位移不可辨识的判定：拟合切片太短，或所有候选位移的 χ² 几乎相同
        # （旧行为会把 qshift 静默顶到扫描下界 -30 并继续拟合，给出 χ²R≈0 的假完美结果）
        n_qslice = qshift_fit_slice.stop - qshift_fit_slice.start
        qshift_degenerate = n_qslice < 5 or guess_decay.max() <= 0
        chi2_candidates = []
        if not qshift_degenerate:
            for qshift in qshift_scan:
                irf_shifted = pchiped_irf(np.arange(-qshift, len(irf) - qshift - 0.01))
                irf_shifted = irf_shifted / irf_shifted.sum()
                conv = scipy.signal.convolve(irf_shifted, guess_decay, mode='full')[
                    :len(guess_decay)]
                conv = conv * ((decay_max - decay_background) / max(conv.max(), 1e-12)) \
                    + decay_background
                chi_sqr = (((decay[qshift_fit_slice] - conv[qshift_fit_slice]) ** 2)
                           / decay[qshift_fit_slice]).sum()
                chi2_candidates.append(chi_sqr)
                if chi_sqr < chi_sqr_best:
                    chi_sqr_best = chi_sqr
                    qshift_suggested = float(qshift)
            if chi2_candidates and np.ptp(chi2_candidates) <= 1e-9 * max(
                    abs(chi_sqr_best), 1e-12):
                qshift_degenerate = True
        if qshift_degenerate:
            qshift_suggested = 0.0
            info['qshift_degenerate'] = True
            self._log("[预处理] 警告：IRF 位移不可辨识"
                      f"（拟合切片 {n_qslice} 点），qshift 固定为 0；"
                      "请检查 IRF 是否与衰减同窗、衰减是否有明显上升沿")

        # 确定拟合区间：从 IRF 峰位开始，到 decay 降至噪声水平为止
        irf_shifted = pchiped_irf(
            np.arange(-qshift_suggested, len(irf) - qshift_suggested - 0.01))
        irf_shifted = irf_shifted / irf_shifted.sum()
        # 噪声水平取「峰高/500」「1.5×本底」「10」的最大值：数字化谱图数据的
        # 本底可能远高于 10，只按峰高比例判断会把信号并入本底之后的纯噪声区
        # 继续拖进拟合窗（模型含本底项，在该区域必然失配）；再要求连续 5 通道
        # 低于阈值才认定进入噪声区，避免个别下探把窗口提前截断
        #
        # v4.32：绝对下限 10 只在**峰值确实远高于它**时才有意义。它原本是给光子
        # 计数数据当"探测本底地板"用的，一旦峰值降到该量级（归一化数据、或弱信号
        # 数据），`10` 就不再是地板而是天花板——全部通道都低于它，窗口必然退化。
        # 此时改用纯相对判据 max(峰值/500, 1.5×本底)：它天然尺度无关，对峰值远大于
        # 10 的**正常计数数据**（工作区实测峰值 ≥ 3×10³）则保持旧式判据逐位不变。
        noise_relative = max(decay_max / 500, 1.5 * decay_background)
        noise_level = max(noise_relative, _NOISE_FLOOR)
        info['noise_level_relative'] = float(noise_relative)
        fit_start = int(irf_shifted.argmax())
        low = decay[decay_max_pos:] < noise_level
        below_start = None
        run = 0
        for i, v in enumerate(low):
            run = run + 1 if v else 0
            if run >= 5:
                below_start = i - 4
                break
        fit_end = (int(below_start + decay_max_pos - 1) if below_start is not None
                   else int(round(0.95 * data_len)))
        fit_end_raw = int(fit_end)
        fit_end = min(max(fit_end, fit_start + 50), data_len)
        # 窗口是否被 50 点下限托底（而非由噪声判据自然给出）。为 True 说明
        # "低于噪声水平"在衰减峰附近就触发了——通常是幅度刻度/本底判据不匹配，
        # 而不是数据真的只有这么短。fit() 会据此给出可操作的报错提示。
        window_floored = bool(fit_end_raw < fit_start + 50)

        info.update({
            'data_len': data_len,
            'irf_background': irf_background,
            'irf_max_pos': irf_max_pos,
            'irf_max': irf_max,
            'irf_rise_pos': irf_rise_pos,
            'decay_background': decay_background,
            'decay_max': decay_max,
            'decay_max_pos': decay_max_pos,
            'decay_rise_pos': decay_rise_pos,
            'qshift_suggested': qshift_suggested,
            'qshift_degenerate': bool(qshift_degenerate),
            'fit_start': fit_start,
            'fit_end': fit_end,
            'fit_end_raw': fit_end_raw,
            'window_floored': window_floored,
            'noise_level': float(noise_level),
        })
        self.decay = decay
        self.time = time
        self.irf = irf

        self._log(f"[预处理] IRF FWHM = {info['irf_FWHM']:.3g} ns, "
                  f"qshift ≈ {qshift_suggested:.3g} ch, "
                  f"拟合区间 [{fit_start}, {fit_end}) / {data_len}")

    # ---------- 主拟合 ----------

    def fit(self, method='MEM', n_rates=201, k_min=0.01, k_max=100.0,
            res_tol=1e-2, lambda_coeff=1e-3, max_runs=10, n_starts=5, seed=0,
            auto_lambda=False, lambda_scan_range=(-5.0, -1.0), lambda_n_grid=9,
            lambda_scan_runs=4, lambda_target=1.1, fixed_taus=None,
            fixed_exclude_dex=0.15, progress_cb=None, cancel_cb=None,
            weight_mode='neyman'):
        """
        最大熵主拟合。

        Args:
            method: "MEM"（最大熵）或 "SESM"（平滑指数序列，以二阶差分平滑约束
                    代替熵项，速度更快、更稳，但分辨率略低）
            n_rates: 速率网格点数（对数均匀分布于 [k_min, k_max]，单位 1/ns）
            res_tol: 终止条件——相邻两轮目标函数差小于该值即停止
            lambda_coeff: 熵项权重 λ（MEM）；SESM 时为平滑项权重的参考系数
            max_runs: 交替优化的最大轮数（保险丝）
            n_starts: 粗估阶段的多起点数量
            auto_lambda: 自动拟合 λ（仅 MEM 生效）。流程 = 先按 lambda_coeff
                完整 MEM（得到寿命分布矩阵）→ 网格扫描（warm-start 轻量迭代，
                选取 χ²R 不超过 lambda_target 的最大 λ）→ 用最优 λ 重新完整 MEM
            lambda_scan_range: λ 扫描的 log10 范围（默认 1e-5 ~ 1e-1）
            lambda_n_grid: 扫描网格点数
            lambda_scan_runs: 扫描时每个 λ 的轻量迭代轮数（不优化 qshift）
            lambda_target: χ²R 可接受阈值（默认 1.1）——λ 的选择规则：取
                χ²R 不超过该阈值的最大 λ（拟合可接受前提下熵正则最强）；
                所有点都超过阈值时退化为取 χ²R 最小的 λ
            fixed_taus: 固定寿命分量列表（单位 ns）。每个分量作为一条**不受熵
                约束**的基函数（exp(-t/τ)⊛IRF）加入模型，其幅度自由拟合；
                同时把速率网格上该 τ 附近（±fixed_exclude_dex 个数量级）的
                网格点**锁定为 0**，否则熵分布会自己把这段吃掉、固定分量退化为 0。
                用于扣除参照染料寿命、IRF 拖尾等已知分量。默认 None（不固定）。
            fixed_exclude_dex: 固定 τ 周围锁定的 log10(k) 半宽（默认 0.15 个
                数量级 ≈ ±41%）
            progress_cb: 可选回调 progress_cb(frac, message)，frac ∈ [0,1]，
                用于 GUI 显示进度（λ 扫描/每轮迭代都会调用）
            cancel_cb: 可选回调 cancel_cb() → bool，返回 True 时抛
                FitCancelled 中止拟合（GUI 的「取消」按钮用）
            weight_mode: χ² 权重口径 'neyman'（默认，分母=观测计数）/
                'pearson'（分母=模型值，与多数文献一致）/ 'poisson'
                （Poisson 对数似然比，低计数最优）。三种口径都会在 info 里
                记录，`chi_sqr` 用所选口径，`chi_sqr_pearson` 始终是 Pearson 值。
        """
        if self.decay is None or 'fit_start' not in self.info:
            raise RuntimeError("请先调用 preprocess()")

        # ---- 参数合法性校验（旧行为是带着非法参数一路算下去）----
        n_rates = int(n_rates)
        if n_rates < 3:
            raise ValueError(f"n_rates 至少为 3（当前 {n_rates}）")
        if not (0 < k_min < k_max):
            raise ValueError(f"速率网格必须满足 0 < k_min < k_max（当前 "
                             f"{k_min}, {k_max}）")
        if method.upper() not in ('MEM', 'SESM'):
            raise ValueError(f"未知拟合方法 {method!r}（只支持 MEM / SESM）")
        weight_mode = str(weight_mode).lower()
        if weight_mode not in ('neyman', 'pearson', 'poisson'):
            raise ValueError(f"未知权重口径 {weight_mode!r}"
                             "（只支持 neyman / pearson / poisson）")

        fit_start = self.info['fit_start']
        fit_end = self.info['fit_end']
        decay_background = self.info['decay_background']
        decay_max = self.info['decay_max']
        npts = fit_end - fit_start
        n_free = n_rates + len([t for t in (fixed_taus or []) if float(t) > 0])
        if npts < n_free:
            hint = (f"请把速率网格点数降到 ≤ {max(3, npts - 1)}，或扩大拟合区间"
                    f"（当前 n_rates={n_rates}）")
            if self.info.get('window_floored'):
                # 窗口是被 50 点下限托底的：噪声判据在衰减峰附近就判定"进入噪声区"，
                # 说明幅度刻度或本底与判据不匹配，而不是数据真的只有这么短。
                hint = (
                    "本次拟合窗口是被 50 点下限托底的（噪声判据在衰减峰附近即触发），\n"
                    f"依据：噪声水平 = {self.info.get('noise_level', float('nan')):.4g}，"
                    f"衰减峰值 = {decay_max:.4g}，本底 = {decay_background:.4g}；\n"
                    "请依次检查：\n"
                    "  1) 衰减列是否为计数（峰值过低/被归一化会导致判据失效）；\n"
                    "  2) IRF 是否与衰减同窗、且有明显上升沿；\n"
                    "  3) 数据是否需要先去背景/去尖峰。\n"
                    f"若确认数据正常，可把速率网格点数降到 ≤ {max(3, npts - 1)}"
                    f"（当前 n_rates={n_rates}）。")
            raise ValueError(
                f"拟合点数不足：拟合窗口 {npts} 点，自由分量 {n_free} 个"
                "（欠定问题，无法给出唯一解）；" + hint)
        npts_per_component = npts / max(n_free, 1)

        # 进度 / 取消回调（GUI 用它更新进度条并支持中途取消）
        def _tick(frac, msg):
            if progress_cb is not None:
                try:
                    progress_cb(float(frac), str(msg))
                except Exception:
                    pass

        def _check_cancel():
            if cancel_cb is not None and cancel_cb():
                raise FitCancelled("用户取消了拟合")

        _check_cancel()
        _tick(0.02, "预处理完成，构建基函数")

        # 基函数：先把 n_rates 条单指数衰减与 IRF 卷好，后面只需线性组合
        time1 = self.time[:fit_end]
        irf1 = self.irf[:fit_end]
        # 先扣掉 IRF 基线再归一化：数字化谱图的 IRF 常有恒定基底，
        # 不扣会把等效 IRF 均匀化、抹平上升沿（τ 偏长、χ²R 偏大）
        irf_base = float(self.info.get('irf_background', 0.0))
        irf1 = np.maximum(irf1 - irf_base, 0.0)
        if not np.any(irf1 > 0):
            raise ValueError("扣除 IRF 基线后 IRF 全为 0，请检查 IRF 数据")
        irf_norm = irf1 / max(irf1.sum(), 1e-12)
        def_rates = np.logspace(math.log10(k_min), math.log10(k_max), n_rates)
        # 固定寿命分量（不受熵约束的额外基函数）
        fixed_taus = [float(t) for t in (fixed_taus or []) if float(t) > 0]
        fixed_rates = np.asarray([1.0 / t for t in fixed_taus], dtype=float)
        n_fixed = int(fixed_rates.size)
        all_rates = (np.concatenate([def_rates, fixed_rates])
                     if n_fixed else def_rates)
        n_total = n_rates + n_fixed
        # 记录速率网格设置，供报告/复现使用
        self.info['k_min'] = float(k_min)
        self.info['k_max'] = float(k_max)
        self.info['n_rates'] = int(n_rates)
        self.info['tau_min_ns'] = float(1.0 / k_max) if k_max > 0 else None
        self.info['tau_max_ns'] = float(1.0 / k_min) if k_min > 0 else None
        if n_fixed:
            self.info['fixed_taus'] = fixed_taus
        # 固定 τ 附近的网格点锁定为 0（否则熵分布会自己吃掉这一段，
        # 固定分量的幅度被压到 0，失去意义）
        grid_active = np.ones(n_rates, dtype=bool)
        if n_fixed:
            log_def = np.log10(def_rates)
            for kf in fixed_rates:
                grid_active &= (np.abs(log_def - math.log10(kf))
                                > float(fixed_exclude_dex))
        a_ij = np.exp(-all_rates[None, :] * time1[:, None])       # (fit_end, n_total)
        A = scipy.signal.fftconvolve(a_ij, irf_norm[:, None],
                                     mode='full', axes=0)[:fit_end]
        # 插值器：用于把卷积结果按 qshift（channels）平移
        pchip_A = scipy.interpolate.PchipInterpolator(
            np.arange(fit_end), A, axis=0, extrapolate=True)

        decay1 = self.decay[fit_start:fit_end]
        # χ² 分母的观测值下限取 1（而不是 0.1）：本底扣除后的低计数点若按 0.1
        # 作方差，单个点就能贡献 (y-d)²/0.1 量级、主导整个 χ²R；Poisson 方差在
        # 0 计数处本就是 1 量级。
        decay1_t = np.maximum(decay1, 1.0)

        def _A_shifted(qshift):
            return pchip_A(np.arange(fit_start - qshift, fit_end - qshift - 0.01))

        def _model(p, Ash):
            return Ash @ p * decay_max + decay_background

        def _chi2(p, Ash, mode=None):
            """χ²R = Σ w(d,y) / M。三种权重口径（weight_mode）：

            - 'neyman'（默认）：Σ(y−d)²/d，分母用**观测**计数（低计数点权重小）；
            - 'pearson'：Σ(d−y)²/y，分母用**模型**值（与多数文献一致）；
            - 'poisson'：2Σ[d·ln(d/y) − (d−y)]，Poisson 对数似然比（低计数最优）。

            注意除数始终是**点数 M**，不是自由度 ν，所以 χ²R≈1 只是量级参考。
            """
            m = (mode or weight_mode).lower()
            y = _model(p, Ash)
            if m == 'pearson':
                return np.sum((decay1_t - y) ** 2 / np.maximum(y, 1.0)) / npts
            if m == 'poisson':
                ys = np.maximum(y, 1e-9)
                return 2.0 * np.sum(decay1_t * np.log(decay1_t / ys)
                                    - (decay1_t - ys)) / npts
            return np.sum((y - decay1_t) ** 2 / decay1_t) / npts

        def _chi2_pearson(p, Ash):
            """Pearson 口径 χ²R（无论 weight_mode 是什么，都算出来供对照）。"""
            return _chi2(p, Ash, mode='pearson')

        def _grad_chi2(p, Ash):
            """∂χ²R/∂p：解析梯度（避免 SLSQP 对 n_rates 维做有限差分）。"""
            m = weight_mode.lower()
            y = _model(p, Ash)
            if m == 'pearson':
                # ∂/∂y Σ(d−y)²/y = −2(d−y)/y − (d−y)²/y²
                # （漏掉第二项会让梯度不准，SLSQP 收敛慢到不可用——实测 0.6s→190s）
                ys = np.maximum(y, 1.0)
                u = decay1_t - ys
                r = -(u / ys) - 0.5 * (u / ys) ** 2
            elif m == 'poisson':
                r = 1.0 - decay1_t / np.maximum(y, 1e-9)
            else:
                r = (y - decay1_t) / decay1_t
            return 2.0 * decay_max * (Ash.T @ r) / npts

        def _grad_entropy(p):
            """∂S/∂p_j，S = −Σ p log(p/Σp)（对整体缩放不变）。

            熵只作用于速率分布部分，**固定寿命分量不受约束**，因此梯度向量必须
            补齐到 n_total 长度并在固定分量处置 0（否则与 _grad_chi2 长度不匹配，
            MEM + fixed_taus 会直接抛 broadcast 错误）。
            """
            dist = np.maximum(p[:n_rates], 1e-12)
            total = max(dist.sum(), 1e-12)
            g = np.zeros_like(p)
            g[:n_rates] = np.log(total / dist)
            return g

        # 分量幅度上限：基函数列峰值归一后 p 就是"相对峰高的幅度"，
        # 留出余量（p>1 表示该分量峰高超过数据峰值，窄快分量可能发生）
        p_ub = 5.0
        bounds = [(0.0, p_ub) if act else (0.0, 0.0) for act in grid_active]
        bounds += [(0.0, p_ub)] * n_fixed

        def _nnls_solve(Ash):
            """固定 qshift 下的**精确**非负最小二乘解（该线性问题的最优解）。

            SLSQP 在 200 维近共线基函数上容易停在"报告成功但远非最优"的点：
            实测合成双指数数据（τ=2.5/8.0 ns）同一基函数下 SLSQP 给 χ²R≈134，
            而 NNLS 解给 0.91。用 NNLS 做粗估与每轮起点，保证不会更差。
            """
            try:
                p, _ = scipy.optimize.nnls(Ash * decay_max,
                                           decay1_t - decay_background)
            except Exception as e:                       # pragma: no cover
                self._log(f"[粗估] NNLS 求解失败（{e}），退回纯 SLSQP")
                return None
            out = np.zeros(n_total)
            out[:min(len(p), n_total)] = p[:n_total]
            out[:n_rates][~grid_active] = 0.0   # grid_active 只覆盖速率网格部分
            return np.clip(out, 0.0, p_ub)

        # ---- 第一阶段：NNLS 精确解 + 多起点 SLSQP，取 χ² 最小者 ----
        self._log(f"[粗估] NNLS + {n_starts} 起点 SLSQP, {n_rates} 个速率分量"
                  + (f" + {n_fixed} 个固定分量" if n_fixed else "") + " ...")
        rng = np.random.default_rng(seed)
        starts = np.zeros((n_starts, n_total))
        starts[0, :n_rates] = 1.0 / n_rates
        if n_starts > 1:
            starts[1, :n_rates] = rng.random(n_rates)
        if n_starts > 2:
            starts[2, :n_rates] = 0.0
        if n_starts > 3:
            starts[3, :n_rates] = 0.5
        if n_starts > 4:
            starts[4, :n_rates] = 1.0
        # 拟合窗口内剔掉过慢（tau > ~100 ns）与过快（tau < 0.1 ns）的分量
        starts[:, 0:3] = 0.0
        starts[:, np.where(def_rates > 10)[0]] = 0.0
        starts[:, np.where(~grid_active)[0]] = 0.0
        if n_fixed:
            starts[:, n_rates:] = 0.1

        A0 = _A_shifted(self.info['qshift_suggested'])
        x_nnls = _nnls_solve(A0)
        _tick(0.10, "NNLS 粗估完成，多起点优化中")
        nnls_chi2 = float(_chi2(x_nnls, A0)) if x_nnls is not None else float('inf')
        best_p = x_nnls
        best_fun = nnls_chi2
        best_res = None
        coarse_ok = 0
        for p0 in starts:
            res = scipy.optimize.minimize(
                _chi2, p0, args=(A0,), jac=_grad_chi2, method='SLSQP',
                bounds=bounds, options={'maxiter': 20000, 'ftol': 1e-12})
            if bool(res.success):
                coarse_ok += 1
            if float(res.fun) < best_fun:
                best_p, best_fun, best_res = np.asarray(res.x, dtype=float), \
                    float(res.fun), res
        if best_p is None:
            raise RuntimeError("粗估失败：NNLS 与 SLSQP 都未给出可用解")
        x_estimate = np.asarray(best_p, dtype=float)
        self.info['coarse_solver'] = {
            'n_starts': int(n_starts),
            'n_success': int(coarse_ok),
            'nnls_chi2': nnls_chi2,
            'best_chi2': float(best_fun),
            'best_from': ('nnls' if best_res is None else 'slsqp'),
            'best_success': bool(best_res.success) if best_res is not None else True,
            'best_status': int(best_res.status) if best_res is not None else 0,
            'best_nit': int(getattr(best_res, 'nit', 0)) if best_res is not None else 0,
            'best_message': (str(getattr(best_res, 'message', ''))
                             if best_res is not None else 'nnls'),
        }
        if best_res is not None and not bool(best_res.success):
            self._log(f"[粗估] 警告：最优 SLSQP 起点未收敛（status={best_res.status}, "
                      f"nit={getattr(best_res, 'nit', 0)}）："
                      f"{getattr(best_res, 'message', '')}")

        # 平滑粗估结果（savgol），窗口自动收缩以适配 n_rates；固定分量不平滑。
        # 平滑只作为"好起点"的锦上添花：若它把 χ² 明显弄差就放弃平滑。
        win = min(50, (n_rates // 2) * 2 - 1)
        if win >= 5:
            smoothed = scipy.signal.savgol_filter(x_estimate[:n_rates], win, 3)
            smoothed[~grid_active] = 0.0
            cand = np.clip(np.concatenate([smoothed, x_estimate[n_rates:]]),
                           0.0, p_ub)
            if _chi2(cand, A0) <= 1.2 * best_fun:
                x_estimate = cand
        x_estimate[:n_rates][~grid_active] = 0.0   # 锁定点保持 0
        x_estimate = np.clip(x_estimate, 0.0, p_ub)
        self._log(f"[粗估] 完成, chi2_R = {_chi2(x_estimate, A0):.4g}"
                  f"（NNLS {nnls_chi2:.4g}）")

        # ---- 第二阶段：交替优化 qshift 与速率分布 ----
        qshift = self.info['qshift_suggested']
        lb_q, ub_q = qshift - 4.0, qshift + 4.0
        preexp_tol = 1e-10
        # 二阶差分算子（SESM 平滑项的解析梯度用）
        D2 = np.zeros((max(n_rates - 2, 0), n_rates))
        for _i in range(D2.shape[0]):
            D2[_i, _i:_i + 3] = (1.0, -2.0, 1.0)
        solver_log = []          # 每轮 SLSQP 的收敛信息，用于最后的自检
        iter_log = []            # 每轮的目标函数与改进量

        def _mem_round(x_in, q_in, lam_c, adaptive=True):
            """单轮主迭代：(a) 优化 IRF 位移 qshift（可选）→ (b) SLSQP 优化分布。

            返回 (x, qshift, chi2R, 目标函数值)。lam_c 为 MEM 熵项权重 λ。
            """
            x = np.asarray(x_in, dtype=float).copy()
            x[x < 1e-4] = preexp_tol
            x = np.clip(x, 0.0, p_ub)
            q = q_in
            if adaptive:
                def qshift_cost(s):
                    return _chi2(x, _A_shifted(s))

                best_q = None
                for s0 in (q - 0.1, q, q + 0.1):
                    r = scipy.optimize.minimize_scalar(
                        qshift_cost, bounds=(lb_q, ub_q), method='bounded',
                        options={'xatol': 1e-3})
                    if best_q is None or r.fun < best_q.fun:
                        best_q = r
                q = float(best_q.x)

            Ash = _A_shifted(q)
            # NNLS 热启动：纯 χ² 子问题的精确最优解，保证每轮起点不比它差
            p_nnls = _nnls_solve(Ash)
            if p_nnls is not None and _chi2(p_nnls, Ash) < _chi2(x, Ash):
                x = p_nnls

            if method.upper() == 'MEM':
                def main_cost(p):
                    # 熵只作用在速率分布部分；固定分量不受正则约束
                    dist = p[:n_rates]
                    S = -(dist * np.log((dist + 1e-10) / (dist.sum() + 1e-10))).sum()
                    return _chi2(p, Ash) - lam_c * S

                def main_jac(p):
                    return _grad_chi2(p, Ash) - lam_c * _grad_entropy(p)
            else:  # SESM：以二阶差分平滑项代替熵项
                def main_cost(p):
                    smooth = (np.diff(p[:n_rates], 2) ** 2).sum()
                    # λ 必须真正生效（旧代码把权重写死为 1e-1，界面上调 λ 毫无反应），
                    # 并除以 n_rates，使等效平滑强度不随网格点数漂移
                    return _chi2(p, Ash) + lam_c * smooth / max(n_rates, 1)

                def main_jac(p):
                    g = _grad_chi2(p, Ash)
                    d2 = np.zeros(n_total)
                    d2[:n_rates] = (2.0 * lam_c / max(n_rates, 1)
                                    * (D2.T @ (D2 @ p[:n_rates])))
                    return g + d2

            res = scipy.optimize.minimize(main_cost, x, jac=main_jac,
                                          method='SLSQP', bounds=bounds,
                                          options={'maxiter': 20000, 'ftol': 1e-12})
            solver_log.append({
                'success': bool(res.success),
                'status': int(res.status),
                'nit': int(getattr(res, 'nit', 0)),
                'message': str(getattr(res, 'message', '')),
            })
            x_new = np.asarray(res.x, dtype=float)
            chi2_new = _chi2(x_new, Ash)
            return x_new, q, chi2_new, res.fun

        def _mem_full(x0, q0, lam_c, adapt=True, tol=res_tol, n_rounds=max_runs):
            """完整主迭代（带终止条件）。返回 (x, qshift, chi2R, 目标函数值)。"""
            x = np.asarray(x0, dtype=float).copy()
            q = q0
            prev_fun = np.inf
            fun = np.inf
            chi2_now = np.inf
            for run in range(1, n_rounds + 1):
                _check_cancel()
                x, q, chi2_now, fun = _mem_round(x, q, lam_c, adaptive=adapt)
                diff = prev_fun - fun
                prev_fun = fun
                iter_log.append((int(run), float(fun), float(diff)))
                self._log(f"[主迭代] 第 {run} 轮: qshift = {q:.4g} ch, "
                          f"目标函数 = {fun:.5g}, 改进量 = {diff:.3g}")
                if run > 1 and diff < tol:
                    break
            return x, q, chi2_now, fun

        if auto_lambda and method.upper() == 'MEM':
            # 第 1 步：按当前（手动）λ 完整 MEM —— 得到寿命分布矩阵与 qshift
            self._log(f"[λ 自动拟合] 第 1 步: MEM, λ = {lambda_coeff:.5g}")
            x1, q1, chi2_1, fun1 = _mem_full(x_estimate, qshift, lambda_coeff)

            # 第 2 步：λ 网格扫描（warm-start，固定 qshift 的轻量迭代）
            lambda_grid = np.logspace(lambda_scan_range[0],
                                      lambda_scan_range[1], lambda_n_grid)
            scan_chi2 = []
            for i_lam, lam_c in enumerate(lambda_grid):
                _check_cancel()
                _tick(0.30 + 0.55 * i_lam / max(len(lambda_grid), 1),
                      f"λ 扫描 {i_lam + 1}/{len(lambda_grid)}（λ = {lam_c:.3g}）")
                xs, _, chi2_s, _ = _mem_full(x1, q1, lam_c, adapt=False,
                                             tol=0.0, n_rounds=lambda_scan_runs)
                scan_chi2.append(chi2_s)
                self._log(f"[λ 扫描] λ = {lam_c:.3g} → χ²R = {chi2_s:.4g}")
            lambda_best = self._pick_lambda(lambda_grid,
                                            np.asarray(scan_chi2, dtype=float),
                                            target=lambda_target)
            self._log(f"[λ 扫描] 最优 λ = {lambda_best:.5g} "
                      f"(χ²R ≤ {lambda_target:.3g} 的最大 λ, 初始 {lambda_coeff:.5g})")

            # 第 3 步：用最优 λ 重新完整 MEM
            self._log(f"[λ 自动拟合] 第 3 步: MEM, λ = {lambda_best:.5g}")
            x_final, q_final, chi2_final, fun_final = _mem_full(
                x1, q1, lambda_best)
        else:
            x_final, q_final, chi2_final, fun_final = _mem_full(
                x_estimate, qshift, lambda_coeff)
            lambda_best = lambda_coeff

        # ---- 提取结果 ----
        _tick(0.95, "整理结果")
        if not np.isfinite(x_final).all():
            raise RuntimeError("拟合失败：速率分布含 NaN/Inf（优化器未收敛）")
        A_shifted = _A_shifted(q_final)
        y_fitted = A_shifted @ x_final * decay_max + decay_background
        pchiped_irf = scipy.interpolate.PchipInterpolator(
            np.arange(0, len(self.irf)), self.irf, extrapolate=True)
        irf_shifted = pchiped_irf(
            np.arange(-q_final, len(self.irf) - q_final - 0.01))

        chi_sqr = _chi2(x_final, A_shifted)
        if os.environ.get('QLS_DEBUG_CHI2'):
            _safe_print("[DEBUG] chi_sqr=%.6g  recompute=%.6g  npts=%d len(d1)=%d "
                        "dmax=%.6g bg=%.6g  x_sum=%.6g"
                        % (chi_sqr,
                           float(np.sum((y_fitted - decay1_t) ** 2 / decay1_t) / npts),
                           npts, len(decay1_t), decay_max, decay_background,
                           float(np.sum(x_final))))
            _safe_print("[DEBUG] y_fitted[:4]=", np.asarray(y_fitted)[:4],
                        " decay1_t[:4]=", np.asarray(decay1_t)[:4],
                        " q_final=", q_final)
        chi_sqr_pearson = _chi2_pearson(x_final, A_shifted)
        # 残差按所选权重口径给出，保证「残差 / ACF / 离群占比 / χ²R」口径一致
        if weight_mode == 'pearson':
            residuals = (decay1_t - y_fitted) / np.sqrt(np.maximum(y_fitted, 1.0))
        elif weight_mode == 'poisson':
            ys = np.maximum(y_fitted, 1e-9)
            dev = 2.0 * (decay1_t * np.log(decay1_t / ys) - (decay1_t - ys))
            residuals = np.sign(decay1_t - ys) * np.sqrt(np.maximum(dev, 0.0))
        else:
            residuals = (y_fitted - decay1_t) / np.sqrt(decay1_t)

        # ---- 收敛自检：任何一轮 SLSQP 未收敛都要显式记录下来 ----
        n_rounds = len(solver_log)
        n_ok = sum(1 for s in solver_log if s['success'])
        last_round = solver_log[-1] if solver_log else {}
        solver_converged = bool(last_round.get('success', False))
        iter_converged = bool(iter_log) and len(iter_log) > 1 and \
            iter_log[-1][2] < res_tol
        quality = 'ok'
        quality_notes = []
        if not solver_converged:
            quality = 'poor'
            quality_notes.append(
                f"优化器未收敛 (status={last_round.get('status')}, "
                f"nit={last_round.get('nit')})")
        if self.info.get('qshift_degenerate'):
            quality = 'poor'
            quality_notes.append("IRF 位移不可辨识")
        if not np.isfinite(chi_sqr):
            quality = 'failed'
            quality_notes.append("χ²R 非有限")
        elif chi_sqr > 5.0:
            quality = 'poor'
            quality_notes.append(f"χ²R={chi_sqr:.3g} 远大于 1")
        elif chi_sqr > 1.5:
            quality_notes.append(f"χ²R={chi_sqr:.3g} 偏大")
        if not iter_converged:
            quality_notes.append("主迭代未达到 res_tol 收敛判据")
        if npts_per_component < 3.0:
            quality_notes.append(
                f"每分量仅 {npts_per_component:.1f} 个数据点（建议 ≥3），"
                "结果对网格点数可能敏感")

        # ---- 边界堆积诊断：分布是否堆在速率网格两端 ----
        dist_final = x_final[:n_rates]
        inten_final = dist_final / np.maximum(def_rates, 1e-12)
        tot_inten = max(float(inten_final.sum()), 1e-12)
        fast_mask = def_rates >= k_max / 10.0        # 最快一个数量级
        slow_mask = def_rates <= k_min * 10.0        # 最慢一个数量级
        edge_n = max(1, int(round(0.02 * n_rates)))
        edge_inten = (inten_final[:edge_n].sum()
                      + inten_final[-edge_n:].sum()) / tot_inten

        self.info.update({
            'qshift_suggested': q_final,
            'chi_sqr': chi_sqr,
            'chi_sqr_pearson': chi_sqr_pearson,
            'chi2_type': ('neyman_obs_denominator_over_M' if weight_mode == 'neyman'
                          else f'{weight_mode}_weight_over_M'),
            'weight_mode': weight_mode,
            'y_fitted': y_fitted,
            'irf_shifted': irf_shifted,
            'residuals': residuals,
            'method': method.upper(),
            'regularizer': 'entropy' if method.upper() == 'MEM' else 'smoothing',
            'cost_final': float(fun_final),
            'lambda_coeff': float(lambda_coeff),          # 用户输入/默认值
            'lambda_auto': bool(auto_lambda and method.upper() == 'MEM'),
            'lambda_coeff_used': float(lambda_best),      # 实际使用的正则权重
            'lambda_target': float(lambda_target),
            'solver_converged': solver_converged,
            'solver_rounds': int(n_rounds),
            'solver_success_rounds': int(n_ok),
            'solver_last_status': int(last_round.get('status', -1)),
            'solver_last_nit': int(last_round.get('nit', 0)),
            'iter_converged': iter_converged,
            'quality': quality,
            'quality_notes': quality_notes,
            'n_fit_points': int(npts),
            'n_free_components': int(n_free),
            'intensity_share_fastest_decade': float(
                inten_final[fast_mask].sum() / tot_inten),
            'intensity_share_slowest_decade': float(
                inten_final[slow_mask].sum() / tot_inten),
            'intensity_share_grid_edges': float(edge_inten),
            'fit_kwargs': {
                'method': method.upper(), 'n_rates': int(n_rates),
                'k_min': float(k_min), 'k_max': float(k_max),
                'lambda_coeff': float(lambda_coeff),
                'auto_lambda': bool(auto_lambda),
                'lambda_target': float(lambda_target),
                'fixed_taus': list(fixed_taus) or None,
                'weight_mode': weight_mode,
            },
        })
        if method.upper() == 'SESM':
            self.info['smooth_weight_used'] = float(lambda_best)
        if auto_lambda and method.upper() == 'MEM':
            self.info['lambda_scan_grid'] = [float(v) for v in lambda_grid]
            self.info['lambda_scan_chi2'] = [float(v) for v in scan_chi2]
        self.k = def_rates
        self.k_distribution = dist_final
        if n_fixed:
            self.info['fixed_amplitudes'] = [
                float(v * decay_max) for v in x_final[n_rates:]]
            self._log("[固定分量] " + ", ".join(
                f"τ={t:.4g} ns → 幅度 {a:.4g}"
                for t, a in zip(fixed_taus, self.info['fixed_amplitudes'])))

        self._log(f"[主迭代] chi2_R = {chi_sqr:.4g}（Pearson {chi_sqr_pearson:.4g}）, "
                  f"qshift = {q_final:.4g} ch "
                  f"({q_final * (self.time[1] - self.time[0]):.4g} ns), "
                  f"λ = {lambda_best:.5g}, 收敛 = {solver_converged}")
        if quality_notes:
            self._log("[拟合质量] " + quality.upper() + "：" + "；".join(quality_notes))
        if edge_inten > 0.05:
            self._log(f"[拟合质量] 注意：{edge_inten:.1%} 的发光强度落在速率网格"
                      "两端（可能是边界堆积伪影，可尝试放宽 k_min/k_max 后复算）")
        _tick(1.0, "拟合完成")

    # ---------- 不确定度：残差 bootstrap（v4.21 新增） ----------

    def bootstrap_ci(self, n_boot=20, seed=0, ci=0.95, progress_cb=None,
                     cancel_cb=None, **fit_kw):
        """用残差 bootstrap 给出各寿命分量 τ 与强度占比的置信区间。

        原理：把当前拟合当作"真值模型"，从残差池 (data − y_fitted) 中有放回地
        重采样，加到 y_fitted 上生成 n_boot 组伪数据，各自用**完全相同的参数**
        重新拟合，统计每个分量的 τ / α 分位数。跨轮次的分量按"与参考 τ 最接近
        且比值 < 1.6"匹配，并给出该分量的命中率（hit_rate）——命中率低说明该
        分量本身不稳定，其区间仅供参考。

        Args:
            n_boot: 重采样次数（默认 20）。代价 ≈ n_boot × 单次拟合耗时；
                auto_lambda 时单次约 1–2 分钟，请谨慎设大。
            ci: 置信水平（默认 0.95 → 2.5% / 97.5% 分位）
            progress_cb / cancel_cb: 同 fit()
            **fit_kw: 覆盖拟合参数（默认沿用本次拟合记录在 info['fit_kwargs'] 的值）

        Returns:
            dict: {'components': [{'tau','tau_lo','tau_hi','alpha','alpha_lo',
                   'alpha_hi','tau_std','alpha_std','hit_rate'}...],
                   'n_boot', 'n_success', 'ci'}
        """
        if self.k_distribution is None or 'y_fitted' not in self.info:
            raise RuntimeError("请先调用 fit() 与 postprocess()")
        info = self.info
        base_kw = dict(info.get('fit_kwargs', {}))
        base_kw.update(fit_kw)
        time = np.asarray(self.time, float)
        decay = np.asarray(self.decay, float)
        irf = np.asarray(self.irf, float)
        y_fit = np.asarray(info['y_fitted'], float)
        fit_start, fit_end = int(info['fit_start']), int(info['fit_end'])
        resid_pool = decay[fit_start:fit_end] - y_fit[:fit_end - fit_start]
        ref = list(self.peak_result or [])
        if not ref:
            raise RuntimeError("没有可统计的寿命分量（peak_result 为空）")

        rng = np.random.default_rng(seed)
        tau_samples = [[] for _ in ref]
        alpha_samples = [[] for _ in ref]
        n_ok = 0
        n_boot = int(n_boot)
        for b in range(n_boot):
            if cancel_cb is not None and cancel_cb():
                raise FitCancelled("用户取消了 bootstrap")
            if progress_cb is not None:
                try:
                    progress_cb(b / max(n_boot, 1), f"bootstrap {b + 1}/{n_boot}")
                except Exception:
                    pass
            fake = decay.copy()
            drawn = rng.choice(resid_pool, size=len(resid_pool), replace=True)
            fake[fit_start:fit_end] = y_fit[:fit_end - fit_start] + drawn
            fake = np.maximum(fake, 0.0)
            f = MEMFitter(verbose=False, name=f"{self.name}-boot{b}")
            try:
                f.load(time, fake, irf, self.meta)
                f.preprocess()
                f.fit(**base_kw)
                f.postprocess()
            except Exception:
                continue
            peaks = list(f.peak_result or [])
            n_ok += 1
            for i, row in enumerate(ref):
                tau_ref = float(row[0])
                best, best_ratio = None, 1.6
                for p in peaks:
                    ratio = max(float(p[0]) / tau_ref, tau_ref / float(p[0]))
                    if ratio < best_ratio:
                        best, best_ratio = p, ratio
                if best is not None:
                    tau_samples[i].append(float(best[0]))
                    alpha_samples[i].append(float(best[1]))

        lo_q, hi_q = 100 * (1 - ci) / 2, 100 * (1 + ci) / 2
        comps = []
        for i, row in enumerate(ref):
            tau_ref, alpha_ref = float(row[0]), float(row[1])
            ts = np.asarray(tau_samples[i], dtype=float)
            als = np.asarray(alpha_samples[i], dtype=float)
            comp = {'tau': tau_ref, 'alpha': alpha_ref,
                    'hit_rate': float(ts.size / max(n_ok, 1))}
            # 命中率低 = 该分量在重采样数据里时有时无 → 区间不可信
            comp['unstable'] = bool(comp['hit_rate'] < 0.5)
            if ts.size >= 3:
                comp.update({
                    'tau_lo': float(np.percentile(ts, lo_q)),
                    'tau_hi': float(np.percentile(ts, hi_q)),
                    'alpha_lo': float(np.percentile(als, lo_q)),
                    'alpha_hi': float(np.percentile(als, hi_q)),
                    'tau_std': float(np.std(ts, ddof=1)),
                    'alpha_std': float(np.std(als, ddof=1)),
                })
                # 区间不覆盖点估计 = 重采样把邻近分量挤掉了（常见于相邻分量
                # 一强一弱），此时区间不能当误差棒用
                if not (comp['tau_lo'] <= tau_ref <= comp['tau_hi']):
                    comp['ci_inconsistent'] = True
            comps.append(comp)
        out = {'components': comps, 'n_boot': n_boot, 'n_success': int(n_ok),
               'ci': float(ci)}
        self.info['bootstrap'] = out
        parts = []
        for c in comps:
            if c['unstable']:
                parts.append(f"τ={c['tau']:.3g} ns → 命中率仅 "
                             f"{c['hit_rate']:.0%}，该分量不稳定（区间不可信）")
            elif 'tau_lo' in c:
                tag = "（区间未覆盖点估计，疑受邻近分量影响）" \
                    if c.get('ci_inconsistent') else ""
                parts.append(f"τ={c['tau']:.3g} ns [{c['tau_lo']:.3g}, "
                             f"{c['tau_hi']:.3g}]{tag}，α={c['alpha']:.3g} "
                             f"[{c['alpha_lo']:.3g}, {c['alpha_hi']:.3g}]")
            else:
                parts.append(f"τ={c['tau']:.3g} ns → 重采样样本不足")
        self._log(f"[bootstrap] {n_ok}/{n_boot} 次成功；" + "；".join(parts))
        return out

    @staticmethod
    def _pick_lambda(grid, chi2s, target=1.1):
        """从 λ 扫描网格中挑选熵正则最强、拟合仍可接受的 λ。

        规则：χ²R 随 λ 单调增（λ 增大 → 熵正则增强 → 拟合变差），
        「拟合可接受」定义为 χ²R 不超过 target（默认 1.1）：
          - 全部点 ≤ target：取最大网格点的 λ（熵最大，拟合均可接受）；
          - 全部点 > target：取 χ²R 最小的 λ（网格下界，拟合最优）；
          - 其余：找跨过 target 的相邻两点，在 log10(λ)-χ²R 图上线性插值。
        这样好数据不会被推向 λ→0（熵项消失、分布贴噪声），
        而噪声大的数据则回到拟合最优的小 λ 端。
        """
        arr = np.asarray(chi2s, dtype=float)
        if np.all(arr <= target):
            return float(grid[-1])
        if np.all(arr > target):
            return float(grid[0])
        for i in range(len(arr) - 1):
            a, b = i, i + 1
            if (arr[a] - target) * (arr[b] - target) <= 0 and arr[a] != arr[b]:
                t = (target - arr[a]) / (arr[b] - arr[a])
                log_lam = (np.log10(grid[a])
                           + t * (np.log10(grid[b]) - np.log10(grid[a])))
                return float(10.0 ** log_lam)
        return float(grid[-1])

    # ---------- 后处理：多重高斯分解 ----------

    def postprocess(self, max_peaks=5, height=None, distance=None,
                    height_frac=0.02, distance_dex=0.08, min_share=0.005):
        """
        对速率分布做多重高斯拟合，得到各寿命分量的
        [tau, 强度占比, FWHM(k 空间), 强度占比]。
        强度占比 = 分量分布峰面积 / k 中心后归一（∝ 1/k），
        与分量的发光强度贡献成正比，避免快分量被 k 空间面积高估。

        判峰口径（v4.21 起）：阈值取**相对**峰高的 ``height_frac``、
        最小间距取 **log-k 空间**的 ``distance_dex``（dex），这样"找到几个
        分量"不再随 n_rates 漂移（旧实现用绝对值 0.005 + 点数距离 5，
        同一份数据在 n_rates=101/201/401 下分别给出 2/3/4 个分量）。
        传入 ``height`` / ``distance`` 可显式覆盖（向后兼容）；
        ``min_share`` 为分量发光强度占比的下限（默认 0.5%），低于它的
        噪声分量会被丢弃并记录在 ``info['peaks_dropped_low_share']``。
        """
        if self.k_distribution is None:
            raise RuntimeError("请先调用 fit()")
        k_distribution = np.asarray(self.k_distribution, dtype=float)
        k = np.asarray(self.k, dtype=float)
        if not np.isfinite(k_distribution).all():
            raise RuntimeError("速率分布含 NaN/Inf，拟合失败，无法做分量分解")

        if height is None:
            height = height_frac * max(float(k_distribution.max()), 1e-12)
        if distance is None:
            log_k_all = np.log10(np.maximum(k, 1e-12))
            dk = float(np.median(np.diff(log_k_all))) if len(k) > 1 else 0.01
            distance = max(1, int(round(float(distance_dex) / max(dk, 1e-6))))

        idx = list(scipy.signal.find_peaks(k_distribution, height=height,
                                          distance=distance)[0])
        # 网格端点处的堆积不会形成局部极大（find_peaks 只找内部峰），
        # 端点值若超过阈值就补进来，避免"分布明显有质量却报告不出分量"
        if len(k) >= 2:
            for i in (0, len(k) - 1):
                if k_distribution[i] >= height and i not in idx:
                    idx.append(i)
        if len(idx) == 0:
            idx = [int(np.argmax(k_distribution))]
            self._log("[后处理] 未找到明显峰位，退化为取分布最大值处作为单一分量")
        idx = np.asarray(sorted(idx), dtype=int)

        peaks = np.array([[k[i], k_distribution[i]] for i in idx])
        peaks = peaks[np.argsort(peaks[:, 1])[::-1]]
        n_found = len(peaks)
        if n_found > max_peaks:
            peaks = peaks[:max_peaks]
        self.info['peaks_found'] = int(n_found)
        self.info['peaks_dropped'] = int(max(0, n_found - max_peaks))

        guess = np.array([[p[1], p[0], p[0]] for p in peaks]).flatten()
        lb = np.array([[0, p[0] / 2, 0] for p in peaks]).flatten()
        ub = np.array([[k_distribution.max() * 2, p[0] * 1.5, k.max()]
                       for p in peaks]).flatten()

        def _gauss(x, *pars):
            out = np.zeros_like(x)
            for i in range(0, len(pars), 3):
                out += pars[i] * np.exp(-((x - pars[i + 1]) / pars[i + 2]) ** 2)
            return out

        try:
            fit_pars, _ = scipy.optimize.curve_fit(
                _gauss, k, k_distribution, p0=guess, bounds=(lb, ub), maxfev=20000)
        except Exception as e:
            self._log(f"[后处理] 高斯拟合失败 ({e})，改用峰位初值")
            fit_pars = guess

        fit_pars = fit_pars.reshape(len(peaks), 3)
        fit_pars = fit_pars[np.argsort(fit_pars[:, 1])[::-1]]

        # 占比按发光强度计。底层离散模型的强度贡献 ∝ 幅值/k（单指数 ∫exp(-kt)dt = 1/k），
        # 把每个网格点按 log-k 最近中心归属到各高斯分量后对 q/k 求和归一。
        # 注意不能用高斯在线性 k 空间的面积换算：速率网格是对数均匀的，
        # 把分布当线性密度积分会高估跨度宽的快分量（快峰多为上升沿形状失配的
        # 吸收器，实际几乎不发光：溶液 2AP 的伪快峰光强占比 <1%，k 空间面积却
        # 显示 77%+）
        log_k = np.log(np.maximum(k, 1e-12))
        assign = np.argmin(
            np.abs(log_k[:, None]
                   - np.log(np.maximum(fit_pars[:, 1], 1e-12))[None, :]),
            axis=1)
        intensity = np.array([
            (k_distribution[assign == i]
             / np.maximum(k[assign == i], 1e-12)).sum()
            for i in range(len(fit_pars))])
        intensity = intensity / max(intensity.sum(), 1e-12)
        peak_FWHM = 2 * math.sqrt(math.log(2)) * fit_pars[:, 2]
        # 各分量**振幅占比**（v4.33）：振幅 = 该高斯分量在 k 空间的峰高
        # （fit_pars[:,0]，与 k_distribution 同刻度），按最大者归一为百分比。
        # 与"强度占比"口径不同：强度 ∝ 幅值/k 的积分，宽而慢的分量强度大、
        # 峰却不高；窄而快的分量峰高但几乎不发光。两个口径都给，才看得出
        # "这个分量是主发光体还是仅一个窄峰"。
        amp_share = fit_pars[:, 0] / max(float(np.max(fit_pars[:, 0])), 1e-12)
        # 丢掉发光强度占比可忽略的"噪声分量"（阈值 min_share，默认 0.5%）：
        # 它们对曲线毫无贡献，却会让报告多出 0.04 ns 这类无意义分量
        keep = intensity >= float(min_share)
        if keep.sum() == 0:
            keep = np.ones_like(keep, dtype=bool)
        n_low = int((~keep).sum())
        if n_low:
            fit_pars = fit_pars[keep]
            intensity = intensity[keep]
            peak_FWHM = peak_FWHM[keep]
            amp_share = amp_share[keep]
            intensity = intensity / max(intensity.sum(), 1e-12)
            # 丢弃分量后重新归一振幅占比，保证最大者仍为 1（图例显示 100%）
            amp_share = amp_share / max(float(np.max(amp_share)), 1e-12)
        self.info['peaks_dropped_low_share'] = n_low
        self.info['peak_amplitude_share'] = [float(v) for v in amp_share]
        # 每项: [tau, 强度占比, FWHM(k-space), 强度占比, 振幅占比(v4.33 新增)]
        # 第 5 项是**追加**的：既有消费者都用 p[0..3] 或 4 元解包（末尾 _），
        # 追加不破坏它们。
        self.peak_result = [
            [1 / p[1], w, f, w, a]
            for p, w, f, a in zip(fit_pars, intensity, peak_FWHM, amp_share)
        ]

        # 未归属质量诊断：距任何分量中心都超过 0.5 dex 的网格点，其发光强度
        # 占比有多大。占比之和恒为 100%，但若有相当一部分强度来自"谁都不像"的
        # 区域（常见于堆在网格端点的伪快分量），读者需要知道。
        log_centers = np.log(np.maximum(fit_pars[:, 1], 1e-12))
        dmin = np.min(np.abs(log_k[:, None] - log_centers[None, :]), axis=1)
        far = dmin > 0.5 * math.log(10)
        inten_all = k_distribution / np.maximum(k, 1e-12)
        self.info['intensity_share_unassigned'] = float(
            inten_all[far].sum() / max(float(inten_all.sum()), 1e-12))

        self.info['peak_fit'] = fit_pars
        self._log("[后处理] 寿命分量:")
        for n, (tau, area, fwhm, _, ampv) in enumerate(self.peak_result):
            self._log(f"    tau_{n + 1} = {tau:.4g} ns, "
                      f"强度占比 = {area * 100:.2f}%, "
                      f"振幅占比 = {ampv * 100:.2f}%, FWHM(k) = {fwhm:.3g}")

    # ---------- 序列化 ----------

    def serialize(self, out_path=None):
        """把结果整理为 dict（并可写入 json）"""
        result = {
            'name': self.name,
            'meta': self.meta,
            'time': self.time,
            'irf': self.irf,
            'decay': self.decay,
            'k': self.k,
            'k_distribution': self.k_distribution,
            'peak_result': self.peak_result,
            'info': self.info,
        }
        if out_path is not None:
            out_path = Path(out_path)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with open(out_path, 'w', encoding='utf-8') as f:
                json.dump(result, f, cls=NumpyTypeEncoder)
            self._log(f"[保存] 拟合结果 → {out_path}")
        return result


# ======================== 2.5 导出拟合结果 ========================

def _scalar(x, default=float('nan')):
    """把 numpy 标量 / 数组 / 列表安全转成 python float（取首项）；失败返回 default。"""
    try:
        if isinstance(x, (list, tuple)) and len(x):
            x = x[0]
        if isinstance(x, dict):
            return default
        a = np.asarray(x, dtype=float)
        if a.size == 0:
            return default
        return float(a.flat[0])
    except Exception:
        return default


def build_summary_table(results, time_unit='ns'):
    """把一批拟合结果（serialize() dict 列表）整理成汇总表（pandas DataFrame）。

    每行一个文件，列：文件名、方法、拟合区间起/止(时间单位)、χ²R、qshift(ch)、
    qshift(时间单位)、IRF_FWHM(时间单位)、分量数，以及各寿命分量 τ_i / 占比_i(%)。
    分量数不一致的，少的分量列填 NaN。

    time_unit 只影响显示（'ns' / 'us'，默认 'ns'）：以 ns 为单位的列会换算成该单位，
    列名里的 (ns) 也随之变成 (unit_symbol)；qshift(ch) 是通道数，不换算不改名。
    内部计算始终用 ns；time_unit='ns' 时列名与数值与旧版完全一致。
    """
    sym = unit_symbol(time_unit)
    rows, max_peaks = [], 0
    for r in results:
        info = r.get('info', {})
        peaks = r.get('peak_result') or []
        max_peaks = max(max_peaks, len(peaks))
        time = np.asarray(r.get('time', []), dtype=float)
        dt = float(time[1] - time[0]) if len(time) > 1 else 1.0
        fs, fe = int(info.get('fit_start', 0)), int(info.get('fit_end', 0))
        fit_lo = time[fs] if 0 <= fs < len(time) else float('nan')
        fit_hi = time[min(fe, len(time) - 1)] if fe > 0 else float('nan')
        row = {
            '文件名': r.get('name', ''),
            '方法': info.get('method', ''),
            'λ模式': ('自动' if info.get('lambda_auto') else '手动'),
            'λ(熵权重)': _scalar(info.get('lambda_coeff_used',
                                         info.get('lambda_coeff'))),
            f'拟合区间起({sym})': from_ns(fit_lo, time_unit),
            f'拟合区间止({sym})': from_ns(fit_hi, time_unit),
            'χ²R': _scalar(info.get('chi_sqr')),
            'qshift(ch)': _scalar(info.get('qshift_suggested')),
            f'qshift({sym})': from_ns(
                _scalar(info.get('qshift_suggested')) * dt, time_unit),
            f'IRF_FWHM({sym})': from_ns(_scalar(info.get('irf_FWHM')), time_unit),
            '分量数': len(peaks),
        }
        for i, p in enumerate(peaks):
            row[f'τ{i + 1}({sym})'] = from_ns(float(p[0]), time_unit)
            row[f'占比{i + 1}(%)'] = float(p[1]) * 100.0
        rows.append(row)
    cols = ['文件名', '方法', 'λ模式', 'λ(熵权重)',
            f'拟合区间起({sym})', f'拟合区间止({sym})',
            'χ²R', 'qshift(ch)', f'qshift({sym})', f'IRF_FWHM({sym})', '分量数']
    for i in range(1, max_peaks + 1):
        cols.append(f'τ{i}({sym})')
        cols.append(f'占比{i}(%)')
    df = pd.DataFrame(rows)
    for c in cols:                      # 补缺失的分量列（部分文件分量更少）
        if c not in df.columns:
            df[c] = float('nan')
    return df[cols]


def _format_report(r, time_unit='ns'):
    """单个拟合结果的 Markdown 报告文本。

    time_unit 只影响显示（'ns' / 'us'，默认 'ns'）：所有时间数值按该单位换算，
    标签用它对应的符号；内部计算始终用 ns。
    """
    sym = unit_symbol(time_unit)
    info = r.get('info', {})
    peaks = r.get('peak_result') or []
    time = np.asarray(r.get('time', []), dtype=float)
    dt = float(time[1] - time[0]) if len(time) > 1 else 1.0
    q = _scalar(info.get('qshift_suggested'))
    lines = [f"# 荧光寿命拟合结果 - {r.get('name', '')}", ""]
    lines.append(f"- 方法: {info.get('method', 'MEM')}")
    lam_mode = '自动拟合' if info.get('lambda_auto') else '手动'
    lines.append(f"- 熵权重 λ = {_scalar(info.get('lambda_coeff_used', info.get('lambda_coeff'))):.5g}（{lam_mode}）")
    lines.append(f"- 简化卡方 χ²R = {_scalar(info.get('chi_sqr')):.4g}")
    lines.append(f"- IRF 位移 qshift = {q:.4g} ch "
                 f"({from_ns(q * dt, time_unit):.4g} {sym})")
    lines.append(f"- IRF FWHM = "
                 f"{from_ns(_scalar(info.get('irf_FWHM')), time_unit):.4g} {sym}")
    fs, fe = int(info.get('fit_start', 0)), int(info.get('fit_end', 0))
    if len(time) > 1:
        lines.append(f"- 拟合区间: "
                     f"{from_ns(time[fs], time_unit):.3g} ~ "
                     f"{from_ns(time[min(fe, len(time) - 1)], time_unit):.3g} {sym}")
    lines.append("")
    if peaks:
        lines.append(f"## 寿命分量（共 {len(peaks)} 个）")
        for i, p in enumerate(peaks, 1):
            lines.append(f"- τ{i} = {from_ns(float(p[0]), time_unit):.4g} {sym}, "
                         f"强度占比 = {float(p[1]) * 100:.2f}%")
    else:
        lines.append("未分离出明显寿命分量（分布过宽）。")
    return "\n".join(lines)


def export_fit_results(results, save_dir, name="lifetime_fit_results",
                       write_csv=True, write_xlsx=True, write_report=True,
                       time_unit='ns'):
    """导出荧光寿命拟合结果。

    Args:
        results: serialize() dict 组成的列表（可来自 fit_lifetime / GUI 缓存）。
        save_dir: 输出目录。
        name: 文件名字前缀。
        write_csv / write_xlsx / write_report: 分别控制输出
            {name}_summary.csv、{name}_summary.xlsx、{name}_{文件名}_report.md。
        time_unit: 只影响显示（'ns' / 'us'，默认 'ns'）：汇总表列名/数值与 md 报告
            中的时间量按该单位换算；内部计算始终用 ns。

    Returns:
        list[str]：实际写出的文件路径。
    """
    out = Path(save_dir)
    out.mkdir(parents=True, exist_ok=True)
    written = []
    results = [r for r in (results or []) if r]
    if not results:
        return written

    df = build_summary_table(results, time_unit=time_unit)
    if write_csv:
        csv_path = out / f"{name}_summary.csv"
        df.to_csv(csv_path, index=False, encoding='utf-8-sig')
        written.append(str(csv_path))
    if write_xlsx:
        try:
            import openpyxl  # noqa: F401  —— pandas.to_excel 需要
            xlsx_path = out / f"{name}_summary.xlsx"
            df.to_excel(xlsx_path, index=False)
            written.append(str(xlsx_path))
        except Exception as e:
            _safe_print(f"[导出] 跳过 xlsx（openpyxl 不可用）: {e}")
    if write_report:
        for r in results:
            nm = r.get('name', 'fit')
            rp = out / f"{name}_{nm}_report.md"
            with open(rp, 'w', encoding='utf-8') as f:
                f.write(_format_report(r, time_unit=time_unit))
            written.append(str(rp))
    return written


# ======================== 3. 绘图 ========================

def plot_summary(results, save_dir='./plots', name='lifetime_summary',
                 x=None, xlabel='样品序号', show=False, dpi=200, fmt='.png',
                 verbose=True, time_unit='ns'):
    """跨样品汇总图（v4.22 新增）：把一批拟合结果画成「参数 vs 样品」曲线。

    三个面板（共享横轴）：
      ① 各寿命分量 τ_i（每条分量一条折线，点标注数值）
      ② 各分量强度占比 α_i
      ③ χ²R（对数纵轴，>1 的点一目了然）

    适合滴定/系列样品：直接看 τ 或 α 随浓度/样品的变化，不用手动导 Excel。

    Args:
        results: serialize() dict 列表（可含 None，会被跳过）
        x: 横轴数值（如浓度）；默认用 1..N
        xlabel: 横轴标题
        time_unit: 只影响显示（'ns' / 'us'，默认 'ns'）：τ 轴标签与数值按该单位换算
            （内部计算与结果数据始终用 ns）；time_unit='ns' 时与旧版完全一致。
    Returns:
        写出的图片路径（str）
    """
    import matplotlib.pyplot as plt
    sym = unit_symbol(time_unit)
    results = [r for r in (results or []) if r and r.get('peak_result')]
    if not results:
        raise ValueError("没有可汇总的拟合结果（peak_result 为空）")
    setup_chinese_font()
    n_max = max(len(r['peak_result']) for r in results)
    xs = np.arange(1, len(results) + 1, dtype=float) if x is None else \
        np.asarray(x, dtype=float)
    if xs.size != len(results):
        raise ValueError(f"x 长度 {xs.size} 与结果数 {len(results)} 不一致")

    fig, axes = plt.subplots(3, 1, figsize=(max(7.0, 0.9 * len(results)), 9.0),
                             sharex=True)
    ax_tau, ax_alpha, ax_chi = axes
    cmap = plt.get_cmap('tab10')
    for i in range(n_max):
        taus, alphas = [], []
        for r in results:
            pk = r['peak_result']
            # τ 存的是 ns，画图前换算到显示单位（ns 时数值不变）
            taus.append(from_ns(pk[i][0], time_unit) if i < len(pk) else np.nan)
            alphas.append(pk[i][1] * 100 if i < len(pk) else np.nan)
        ax_tau.plot(xs, taus, 'o-', color=cmap(i % 10), label=f'τ{i + 1}')
        ax_alpha.plot(xs, alphas, 's-', color=cmap(i % 10), label=f'α{i + 1}')
    ax_tau.set_ylabel(f'寿命 τ ({sym})')
    ax_tau.set_yscale('log')
    ax_tau.set_title('各寿命分量 vs ' + xlabel)
    ax_tau.legend(fontsize=9, ncol=min(n_max, 4))
    ax_alpha.set_ylabel('强度占比 α (%)')
    ax_alpha.set_ylim(0, 105)
    ax_alpha.legend(fontsize=9, ncol=min(n_max, 4))
    chi = [float(r['info'].get('chi_sqr', np.nan)) for r in results]
    ax_chi.semilogy(xs, chi, 'd-', color='#cc6677')
    ax_chi.axhline(1.0, color='#888888', linestyle='--', linewidth=0.8)
    ax_chi.set_ylabel('χ²R (对数轴)')
    ax_chi.set_xlabel(xlabel)
    names = [str(r.get('name', f'#{i + 1}')) for i, r in enumerate(results)]
    ax_chi.set_xticks(xs)
    ax_chi.set_xticklabels(names, rotation=30, ha='right', fontsize=8)
    for ax in axes:
        ax.grid(True, alpha=0.3)
    fig.tight_layout()
    out = Path(save_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{name}{fmt}"
    fig.savefig(path, dpi=dpi, bbox_inches='tight')
    if show:
        plt.show()
    else:
        plt.close(fig)
    if verbose:
        _safe_print(f"  ✔ 汇总图已保存: {path}")
    return str(path)


def export_report_pdf(results, save_dir='./plots', name='lifetime_report',
                      title=None, dpi=150, verbose=True, time_unit='ns'):
    """把一批拟合结果导出成**多页 PDF 报告**（v4.22 新增）。

    第 1 页：汇总表（文件名 / 方法 / χ²R / 拟合区间 / 各分量 τ 与占比）+ χ²R 柱状图；
    之后每个样品一页：衰减+拟合（对数纵轴）+ 残差 + 寿命分布。

    Args:
        results: serialize() dict 列表
        time_unit: 只影响显示（'ns' / 'us'，默认 'ns'）：汇总表表头/数值与样品页里
            以 ns 为单位的坐标轴（τ 轴）按该单位换算；内部计算始终用 ns。
    Returns:
        写出的 PDF 路径（str）
    """
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages
    sym = unit_symbol(time_unit)
    results = [r for r in (results or []) if r]
    if not results:
        raise ValueError("没有可导出的拟合结果")
    setup_chinese_font()
    out = Path(save_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{name}.pdf"

    with PdfPages(path) as pdf:
        # ---------- 第 1 页：汇总表 + χ²R 柱状图 ----------
        fig = plt.figure(figsize=(8.27, 11.69))     # A4 纵向
        fig.suptitle(title or "荧光寿命拟合报告", fontsize=15, y=0.97)
        ax_t = fig.add_axes([0.06, 0.52, 0.88, 0.40])
        ax_t.axis('off')
        n_max = max(len(r.get('peak_result') or []) for r in results)
        head = ['样品', '方法', 'χ²R', f'拟合区间({sym})']
        head += [f'τ{i + 1} ({sym})' for i in range(n_max)]
        head += [f'α{i + 1} (%)' for i in range(n_max)]
        rows = []
        for r in results:
            info = r.get('info', {})
            pk = r.get('peak_result') or []
            t = np.asarray(r.get('time', []), dtype=float)
            dt = (t[1] - t[0]) if len(t) > 1 else 1.0
            fs, fe = int(info.get('fit_start', 0)), int(info.get('fit_end', 0))
            row = [str(r.get('name', '')), str(info.get('method', '')),
                   f"{info.get('chi_sqr', float('nan')):.3g}",
                   f"{from_ns(t[fs], time_unit):.2f}–"
                   f"{from_ns(t[min(fe, len(t) - 1)], time_unit):.2f}"
                   if len(t) else '-']
            row += [f"{from_ns(pk[i][0], time_unit):.3g}" if i < len(pk) else '-'
                    for i in range(n_max)]
            row += [f"{pk[i][1] * 100:.1f}" if i < len(pk) else '-'
                    for i in range(n_max)]
            rows.append(row)
        tbl = ax_t.table(cellText=rows, colLabels=head, loc='upper center',
                         cellLoc='center')
        tbl.auto_set_font_size(False)
        tbl.set_fontsize(max(5.5, min(9.0, 90.0 / max(len(head), 1))))
        tbl.scale(1.0, 1.25)
        for j in range(len(head)):
            tbl[0, j].set_facecolor('#dbeafe')
            tbl[0, j].set_text_props(weight='bold')
        ax_c = fig.add_axes([0.12, 0.08, 0.78, 0.34])
        chi = [float(r.get('info', {}).get('chi_sqr', np.nan)) for r in results]
        names = [str(r.get('name', '')) for r in results]
        ax_c.bar(range(len(chi)), chi, color='#66ccee')
        ax_c.axhline(1.0, color='#888888', linestyle='--', linewidth=0.8)
        ax_c.set_ylabel('χ²R')
        ax_c.set_title('各样品拟合优度（虚线 = 1）')
        ax_c.set_xticks(range(len(names)))
        ax_c.set_xticklabels(names, rotation=30, ha='right', fontsize=8)
        ax_c.grid(True, axis='y', alpha=0.3)
        pdf.savefig(fig, dpi=dpi)
        plt.close(fig)

        # ---------- 每个样品一页 ----------
        for r in results:
            info = r.get('info', {})
            time = np.asarray(r.get('time', []), dtype=float)
            decay = np.asarray(r.get('decay', []), dtype=float)
            y_fit = np.asarray(info.get('y_fitted', []), dtype=float)
            resid = np.asarray(info.get('residuals', []), dtype=float)
            k = np.asarray(r.get('k', []), dtype=float)
            dist = np.asarray(r.get('k_distribution', []), dtype=float)
            if time.size == 0 or k.size == 0:
                continue
            fs, fe = int(info.get('fit_start', 0)), int(info.get('fit_end', len(time)))
            fig, axes = plt.subplots(2, 1, figsize=(8.27, 11.69),
                                     gridspec_kw={'height_ratios': [2, 1]})
            ax = axes[0]
            # 时间轴同样按显示单位绘制（v4.39：time_unit='ns' 时数值与旧版一致）
            time_disp = from_ns(time, time_unit)
            ax.semilogy(time_disp, np.maximum(decay, 0.5), '.', ms=2, alpha=0.5,
                        color='#66ccee', label='实验数据')
            ax.semilogy(time_disp[fs:fs + len(y_fit)], np.maximum(y_fit, 0.5),
                        '-', lw=1.4, color='#ee6677', label='拟合')
            irf_s = np.asarray(info.get('irf_shifted', []), dtype=float)
            if irf_s.size:
                sc = decay.max() / max(irf_s.max(), 1e-9) * 0.9
                ax.semilogy(time_disp[:len(irf_s)], np.maximum(irf_s * sc, 0.5),
                            '-', lw=0.8, color='#ccbb44', label='IRF（平移后）')
            ax.axvline(time_disp[fs], color='#16A34A', ls='--', lw=0.8)
            ax.axvline(time_disp[min(fe, len(time) - 1)], color='#16A34A', ls='--',
                       lw=0.8)
            pk_txt = "，".join(
                f"τ{i + 1}={from_ns(p[0], time_unit):.3g} {sym} ({p[1] * 100:.1f}%)"
                              for i, p in enumerate(r.get('peak_result') or []))
            ax.set_title(f"{r.get('name', '')} — {info.get('method', '')}"
                         f"，χ²R={info.get('chi_sqr', float('nan')):.3g}\n{pk_txt}",
                         fontsize=11)
            ax.set_ylabel('计数（对数）')
            ax.set_xlabel(f'时间 ({sym})')
            ax.legend(fontsize=8)
            ax.grid(True, which='both', alpha=0.25)
            ax2 = axes[1]
            ax2.semilogx(from_ns(1.0 / np.maximum(k, 1e-12), time_unit), dist,
                         '-', color='#1e293b', label='寿命分布')
            for p in (r.get('peak_result') or []):
                tau_disp = from_ns(p[0], time_unit)
                ax2.axvline(tau_disp, color='#ee6677', ls='--', lw=0.8, alpha=0.8)
                ax2.annotate(f"τ={tau_disp:.3g} {sym}\n{p[1] * 100:.1f}%",
                             xy=(tau_disp, dist.max() * 0.9 if dist.size else 1),
                             fontsize=8, color='#ee6677', ha='center')
            ax2.set_xlabel(f'τ ({sym})')
            ax2.set_ylabel('分布强度')
            ax2.legend(fontsize=8)
            ax2.grid(True, alpha=0.25)
            if resid.size:
                ax2.set_title(f"残差均值 {resid.mean():.3g}，标准差 {resid.std():.3g}",
                              fontsize=9)
            fig.tight_layout()
            pdf.savefig(fig, dpi=dpi)
            plt.close(fig)

    if verbose:
        _safe_print(f"  ✔ PDF 报告已保存: {path}")
    return str(path)


def plot_result(result, save_dir='./plots', name=None, show=False,
                dpi=600, fmt='png', time_unit='ns'):
    """
    画拟合结果的两张图：
      1) {name}_decay.png : 衰减曲线 + 移动后 IRF + 拟合曲线（log 轴）+ 残差
      2) {name}_peaks.png : 寿命分布 + 各高斯分量（对数 tau 轴）
    result 可为 MEMFitter.serialize() 返回的 dict，或一个这样的 dict 组成的列表。

    time_unit 只影响显示（'ns' / 'us'，默认 'ns'）：时间轴刻度、IRF 平移量与 τ 数值
    按该单位换算；内部计算与结果数据始终用 ns，time_unit='ns' 时与旧版完全一致。
    """
    results = result if isinstance(result, (list, tuple)) else [result]
    saved = []
    for res in results:
        _plot_one(res, save_dir, name or res.get('name'), show, dpi, fmt,
                  time_unit=time_unit)
        saved.append(save_dir)
    if show:
        plt.show()
    plt.close('all')
    return saved


def _plot_one(res, save_dir, name, show, dpi, fmt, time_unit='ns'):
    """画单个结果的两张图；time_unit 只影响显示，内部数据始终是 ns。"""
    sym = unit_symbol(time_unit)
    info = res['info']
    time = np.asarray(res['time'])
    decay = np.asarray(res['decay'])
    irf_shifted = np.asarray(info['irf_shifted'])
    y_fitted = np.asarray(info['y_fitted'])
    residuals = np.asarray(info['residuals'])
    fit_time = time[info['fit_start']:info['fit_end']]
    dt = time[1] - time[0] if len(time) > 1 else 1.0
    qshift_ns = info['qshift_suggested'] * dt
    # 绘图用的时间轴：ns → 显示单位（time_unit='ns' 时数值不变）
    time_disp = from_ns(time, time_unit)
    fit_time_disp = from_ns(fit_time, time_unit)

    # ---- 图 1：衰减 + 拟合 + 残差 ----
    fig = plt.figure(figsize=(6, 5))
    gs = GridSpec(2, 1, height_ratios=[7, 3])
    ax1 = fig.add_subplot(gs[0])
    ax1.scatter(time_disp, decay, s=2, alpha=0.6, marker='o',
                edgecolors='none', color="#66ccee", label='实验数据')
    ax1.plot(time_disp, irf_shifted, linewidth=0.8, color="#ccbb44",
             label=f'IRF（平移 {from_ns(qshift_ns, time_unit):.2g} {sym}）')
    ax1.plot(fit_time_disp, y_fitted, linewidth=1.5, color="#ee6677", label='MEM 拟合')
    ax1.set_yscale('log')
    ax1.set_ylim(bottom=1)
    ax1.set_ylabel('Counts (log)')
    ax1.legend()
    ax1.set_title(name or '')

    ax2 = fig.add_subplot(gs[1], sharex=ax1)
    ax2.plot(fit_time_disp, residuals, linewidth=0.3, color="#ee6677")
    ax2.axhline(0, color='gray', linewidth=0.5)
    ax2.set_xlabel(f'Time ({sym})')
    ax2.set_ylabel('残差')
    ax2.text(0.97, 0.9, r'$\chi_{\rm R}^2 = ' + f"{info['chi_sqr']:.4g}$",
             ha='right', va='top', transform=ax2.transAxes,
             bbox=dict(boxstyle='square,pad=0.3', edgecolor='none',
                       facecolor='white'))

    out1 = None
    if save_dir is not None:
        out_dir = Path(save_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        out1 = out_dir / f"{name or 'lifetime'}_decay.{fmt}"
        fig.savefig(out1, bbox_inches='tight', dpi=dpi)
        _safe_print(f"  [保存] {out1}")

    # ---- 图 2：寿命分布 ----
    k = np.asarray(res['k'])
    dist = np.asarray(res['k_distribution'])
    tau = 1.0 / k
    tau_disp = from_ns(tau, time_unit)      # 显示单位下的 τ（k 仍为 1/ns）
    fig2, ax = plt.subplots(figsize=(6, 2.8))
    ax.set_xlabel(rf'$\tau$ ({sym})')
    ax.set_ylabel('分布强度')
    ax.set_xscale('log')
    ax.set_ylim(top=dist.max() * 1.4 if dist.max() > 0 else 1)
    ax.plot(tau_disp, dist, linewidth=0.8, color='black', label='MEM 分布')

    peak_fit = info.get('peak_fit')
    peak_result = res.get('peak_result') or []
    if peak_fit is not None and len(peak_result) > 0:
        weights = np.array([p[3] for p in peak_result], dtype=float)
        weights = weights / max(weights.sum(), 1e-12)
        # 振幅占比（v4.33）：第 5 项；旧结果没有则回退按分量峰高自算
        amps = np.array([p[4] if len(p) > 4 else 0.0 for p in peak_result],
                        dtype=float)
        if not np.any(amps > 0):
            pf = np.asarray(peak_fit, dtype=float)
            amps = pf[:, 0] / max(float(np.max(pf[:, 0])), 1e-12)
        for n, peak in enumerate(np.asarray(peak_fit)):
            comp = peak[0] * np.exp(-((k - peak[1]) / peak[2]) ** 2)
            ax.fill_between(tau_disp, 0, comp, alpha=0.5,
                            label=(fr'$\tau_{{{n + 1}}} = '
                                   fr'{from_ns(1 / peak[1], time_unit):.3g}$ {sym}, '
                                   fr'振幅 {amps[n] * 100:.1f}%, '
                                   fr'强度 {weights[n] * 100:.1f}%'))
        ax.legend(fontsize=8)

    out2 = None
    if save_dir is not None:
        out2 = Path(save_dir) / f"{name or 'lifetime'}_peaks.{fmt}"
        fig2.savefig(out2, bbox_inches='tight', dpi=dpi)
        _safe_print(f"  [保存] {out2}")

    if show:
        plt.show()


# ======================== 4. 一键接口 ========================

def _expand_files(files):
    if isinstance(files, (str, Path)):
        files = [files]
    out = []
    for f in files:
        f = str(f)
        matched = sorted(glob.glob(f))
        out.extend(matched if matched else [f])
    return out


def _fit_single(task):
    """并行拟合的 worker：必须是**模块级**函数，Windows spawn 才能 pickle。"""
    time, decay, irf, meta, name, fit_kwargs, post_kwargs = task
    fitter = MEMFitter(verbose=False, name=name)
    fitter.load(time, decay, irf, meta)
    fitter.preprocess()
    fitter.fit(**(fit_kwargs or {}))
    fitter.postprocess(**(post_kwargs or {}))
    return fitter.serialize(None)


def _safe_fit_one(task):
    try:
        return _fit_single(task)
    except Exception as e:                      # 单个失败不影响整批
        _safe_print(f"  [错误] 拟合失败: {e}")
        return None


def fit_many(datasets, max_workers=None, fit_kwargs=None, post_kwargs=None,
             verbose=True):
    """
    并行拟合多个数据集（多进程），用于批量/多样品对比。

    Args:
        datasets: [{'name', 'time', 'decay', 'irf', 'meta'}, ...]
        max_workers: 进程数；默认 CPU 核数 - 1（至少 1）
        fit_kwargs: 传给 MEMFitter.fit 的参数（method/n_rates/k_min/…）
        post_kwargs: 传给 MEMFitter.postprocess 的参数

    返回与输入同序的结果列表（单条失败的位置为 None）。
    多进程不可用时（打包环境/权限限制等）自动退回串行，不会让整批失败。
    """
    tasks = []
    for d in datasets:
        tasks.append((np.asarray(d['time'], dtype=float),
                      np.asarray(d['decay'], dtype=float),
                      np.asarray(d['irf'], dtype=float),
                      d.get('meta'), d.get('name'),
                      dict(fit_kwargs or {}), post_kwargs))
    if not tasks:
        return []
    if max_workers is None:
        max_workers = max(1, (os.cpu_count() or 2) - 1)
    if len(tasks) == 1 or max_workers <= 1:
        return [_safe_fit_one(t) for t in tasks]
    try:
        import concurrent.futures as _cf
        with _cf.ProcessPoolExecutor(max_workers=max_workers) as ex:
            return list(ex.map(_safe_fit_one, tasks))
    except Exception as e:
        if verbose:
            _safe_print(f"  [WARN] 并行拟合不可用（{type(e).__name__}: {e}），"
                        f"退回串行")
        return [_safe_fit_one(t) for t in tasks]


def fit_global(datasets, method='MEM', n_rates=201, k_min=0.01, k_max=100.0,
               lambda_coeff=1e-3, auto_lambda=False, max_runs=10, res_tol=1e-6,
               weight_mode='neyman', verbose=True, progress_cb=None,
               cancel_cb=None, _debug_grad=False):
    """全局（多数据集）寿命分析：**共享速率分布形状，各数据集只有幅度不同**。

    适用场景：同一体系的多次测量 / 多波长衰减 / 滴定序列（如 FRET A0→A24）。
    逐个独立拟合时噪声会让 τ 抖动，全局拟合把所有数据集的信息合起来约束分布形状。

    模型（每个数据集 d 有自己的时间轴、IRF、拟合窗与本底）::

        y_d(t) = (A_d @ p) · decay_max_d · s_d + bg_d

        A_d : 第 d 个数据集自己的 IRF 重卷积基函数（n_rates 列）
        p   : 共享的速率分布，约束 Σp = 1
        s_d : 第 d 个数据集的幅度（自由参数，与 p 的尺度不再简并）

    目标函数 ``Σ_d χ²R_d − λ·S(p)``，SLSQP + 解析梯度 + 等式约束 Σp=1。
    （auto_lambda 时对 λ 做一次粗扫描，取 Σχ²R 不超过 target 的最大 λ。）

    Args:
        datasets: [{'name','time','decay','irf','meta'}, ...]（至少 2 个）
        method: 'MEM'（熵正则）或 'SESM'（二阶差分平滑）
        n_rates / k_min / k_max: 共享速率网格
        lambda_coeff: 正则权重；auto_lambda=True 时作为扫描起点
        weight_mode: 'neyman'（默认）/ 'pearson' / 'poisson'

    Returns:
        dict: {
          'k', 'k_distribution', 'peak_result', 'info',
          'scales': [s_1..s_D], 'per_dataset': [{'name','chi2R','scale',
             'alpha': [...], 'time','decay','y_fitted','irf_shifted'}, ...],
          'chi2R_total', 'tau_list'
        }
    """
    datasets = list(datasets or [])
    if len(datasets) < 2:
        raise ValueError("全局拟合至少需要 2 个数据集（单数据集请用 MEMFitter）")
    if not (0 < k_min < k_max):
        raise ValueError("速率网格必须满足 0 < k_min < k_max")
    n_rates = int(n_rates)
    if n_rates < 3:
        raise ValueError("n_rates 至少为 3")
    method = method.upper()
    if method not in ('MEM', 'SESM'):
        raise ValueError(f"未知拟合方法 {method!r}（只支持 MEM / SESM）")
    weight_mode = str(weight_mode).lower()
    if weight_mode not in ('neyman', 'pearson', 'poisson'):
        raise ValueError(f"未知权重口径 {weight_mode!r}")

    def _tick(frac, msg):
        if progress_cb is not None:
            try:
                progress_cb(float(frac), str(msg))
            except Exception:
                pass

    def _check_cancel():
        if cancel_cb is not None and cancel_cb():
            raise FitCancelled("用户取消了全局拟合")

    rates = np.logspace(math.log10(k_min), math.log10(k_max), n_rates)

    # ---------- 为每个数据集准备基函数 ----------
    sets = []
    for d in datasets:
        _check_cancel()
        f = MEMFitter(verbose=False, name=d.get('name', 'dataset'))
        f.load(d['time'], d['decay'], d['irf'], d.get('meta'))
        f.preprocess()
        info = f.info
        fit_start, fit_end = int(info['fit_start']), int(info['fit_end'])
        npts = fit_end - fit_start
        if npts < 3:
            raise ValueError(f"{f.name}: 拟合窗口只有 {npts} 点，无法参与全局拟合")
        time1 = f.time[:fit_end]
        irf1 = np.maximum(f.irf[:fit_end] - float(info.get('irf_background', 0.0)),
                          0.0)
        if not np.any(irf1 > 0):
            raise ValueError(f"{f.name}: 扣除基线后 IRF 全为 0")
        irf_norm = irf1 / irf1.sum()
        a_ij = np.exp(-rates[None, :] * time1[:, None])
        A = scipy.signal.fftconvolve(a_ij, irf_norm[:, None], mode='full',
                                     axes=0)[:fit_end]
        pchip = scipy.interpolate.PchipInterpolator(
            np.arange(fit_end), A, axis=0, extrapolate=True)
        sets.append({
            'name': f.name, 'fit_start': fit_start, 'fit_end': fit_end,
            'bg': float(info['decay_background']),
            'dmax': float(info['decay_max']),
            'd': np.maximum(f.decay[fit_start:fit_end], 1.0),
            'q': float(info['qshift_suggested']), 'pchip': pchip, 'npts': npts,
            'time': f.time, 'decay': f.decay, 'irf': f.irf,
            'info': dict(info), 'fitter': f,
        })
    n_sets = len(sets)

    def _A(s, q=None):
        q = s['q'] if q is None else q
        return s['pchip'](np.arange(s['fit_start'] - q, s['fit_end'] - q - 0.01))

    def _model(s, p, scale):
        return (_A(s) @ p) * s['dmax'] * scale + s['bg']

    def _chi2_one(s, p, scale):
        y = _model(s, p, scale)
        if weight_mode == 'pearson':
            return float(np.sum((s['d'] - y) ** 2 / np.maximum(y, 1.0)) / s['npts'])
        if weight_mode == 'poisson':
            ys = np.maximum(y, 1e-9)
            dev = 2.0 * (s['d'] * np.log(s['d'] / ys) - (s['d'] - ys))
            return float(np.sum(dev) / s['npts'])
        r = (y - s['d']) / s['d']
        return float(np.sum(r ** 2 * s['d']) / s['npts'])   # = Σ(y−d)²/d

    # ---------- 目标函数与解析梯度 ----------
    # p 用 softmax 参数化（Σp ≡ 1，无需等式约束；SLSQP 在这类问题上会
    # 停在"报告成功但没动"的点，实测 L-BFGS-B 从 522.7 降到 2.19）
    lam_holder = [float(lambda_coeff)]
    D2 = np.zeros((max(n_rates - 2, 0), n_rates))
    for _i in range(D2.shape[0]):
        D2[_i, _i:_i + 3] = (1.0, -2.0, 1.0)

    def _softmax(z):
        e = np.exp(np.clip(z - np.max(z), -50.0, 50.0))
        return e / e.sum()

    def _cost_grad(x):
        z = np.clip(x[:n_rates], -30.0, 30.0)
        p = _softmax(z)
        scales = np.clip(x[n_rates:], 1e-12, None)
        lam_c = lam_holder[0]
        total = 0.0
        gp = np.zeros(n_rates)
        gs = np.zeros(n_sets)
        for k, s in enumerate(sets):
            Ash = _A(s)
            Ap = Ash @ p
            y = Ap * s['dmax'] * scales[k] + s['bg']
            if weight_mode == 'pearson':
                ys = np.maximum(y, 1.0)
                u = s['d'] - ys
                r = -(u / ys) - 0.5 * (u / ys) ** 2      # 见 fit() 的说明
                total += float(np.sum(u ** 2 / ys) / s['npts'])
            elif weight_mode == 'poisson':
                ys = np.maximum(y, 1e-9)
                dev = 2.0 * (s['d'] * np.log(s['d'] / ys) - (s['d'] - ys))
                r = 1.0 - s['d'] / ys
                total += float(np.sum(dev) / s['npts'])
            else:
                r = (y - s['d']) / s['d']
                # Neyman：χ² = Σ(y−d)²/d = Σ r²·d（注意不是 Σ r²！）
                # cost 与 gradient 必须同口径，否则优化器会沿错误方向游走
                total += float(np.sum(r ** 2 * s['d']) / s['npts'])
            gp += 2.0 * s['dmax'] * scales[k] * (Ash.T @ r) / s['npts']
            gs[k] = 2.0 * s['dmax'] * float(np.dot(Ap, r)) / s['npts']
        pn = np.maximum(p, 1e-300)
        if method == 'MEM':
            total -= lam_c * float(-(pn * np.log(pn)).sum())
            gp += lam_c * (np.log(pn) + 1.0)
        else:
            total += lam_c * float((np.diff(p, 2) ** 2).sum()) / max(n_rates, 1)
            gp += (2.0 * lam_c / max(n_rates, 1)) * (D2.T @ (D2 @ p))
        # 链式法则：∂cost/∂z_j = p_j (g_j − Σ_i p_i g_i)
        gz = p * (gp - float(np.dot(p, gp)))
        return total, np.concatenate([gz, gs])

    def _optimize(x_start, lam_c):
        lam_holder[0] = float(lam_c)
        return scipy.optimize.minimize(
            lambda x: _cost_grad(x)[0], x_start,
            jac=lambda x: _cost_grad(x)[1], method='L-BFGS-B',
            bounds=[(-30.0, 30.0)] * n_rates + [(1e-12, None)] * n_sets,
            options={'maxiter': 20000, 'ftol': float(res_tol), 'gtol': 1e-10})

    # 起点：① 均匀分布 ② 数据量最大的数据集单独拟合出的分布（warm start）
    starts = [np.concatenate([np.zeros(n_rates), np.ones(n_sets)])]
    try:
        best_s = max(sets, key=lambda s: s['dmax'])
        f1 = best_s['fitter']
        f1.fit(method=method, n_rates=n_rates, k_min=k_min, k_max=k_max,
               lambda_coeff=float(lambda_coeff))
        p_warm = np.asarray(f1.k_distribution, dtype=float)
        if p_warm.size == n_rates and np.isfinite(p_warm).all() and p_warm.sum() > 0:
            p_warm = np.maximum(p_warm / p_warm.sum(), 1e-6)
            starts.append(np.concatenate([np.log(p_warm), np.ones(n_sets)]))
    except Exception as e:
        if verbose:
            _safe_print(f"  [WARN] 单独拟合起点不可用（{e}）")

    # ---------- λ 自动扫描（可选） ----------
    lam = float(lambda_coeff)
    if auto_lambda and method == 'MEM':
        grid = np.logspace(-5, -1, 9)
        best_lam = lam
        for i, lam_c in enumerate(grid):
            _check_cancel()
            _tick(0.05 + 0.25 * i / len(grid), f"λ 扫描 {i + 1}/{len(grid)}")
            r_scan = _optimize(starts[0], lam_c)
            lam_holder[0] = 0.0                 # 只看数据项，便于跨 λ 比较
            chi_data = float(_cost_grad(r_scan.x)[0])
            lam_holder[0] = lam_c
            if chi_data <= 1.5 and lam_c > best_lam:
                best_lam = lam_c
        lam = best_lam

    # ---------- 主优化：多起点取最优 ----------
    _check_cancel()
    if _debug_grad:      # 维护用：暴露目标/梯度闭包供 check_grad 验证
        return {'_cost_grad': _cost_grad, '_sets': sets, '_A': _A,
                'rates': rates, 'x0': starts[0]}
    _tick(0.35, "全局优化中")
    best_res = None
    for si, x_start in enumerate(starts):
        _check_cancel()
        _tick(0.35 + 0.1 * si, f"全局优化（起点 {si + 1}/{len(starts)}）")
        r = _optimize(x_start, lam)
        if best_res is None or r.fun < best_res.fun:
            best_res = r
    res = best_res
    p_shared = _softmax(np.clip(res.x[:n_rates], -30.0, 30.0))
    scales = np.clip(res.x[n_rates:], 1e-12, None)

    # ---------- 每个数据集：qshift 精修 + 结果整理 ----------
    per = []
    chi2_total = 0.0
    for k, s in enumerate(sets):
        _check_cancel()
        _tick(0.7 + 0.25 * k / max(n_sets, 1), f"整理 {s['name']}")
        chi_before = _chi2_one(s, p_shared, scales[k])

        def _chi2_one_q(s_, p_, sc_, q_):
            y = (_A(s_, q_) @ p_) * s_['dmax'] * sc_ + s_['bg']
            if weight_mode == 'pearson':
                return float(np.sum((s_['d'] - y) ** 2 / np.maximum(y, 1.0))
                             / s_['npts'])
            if weight_mode == 'poisson':
                ys = np.maximum(y, 1e-9)
                dev = 2.0 * (s_['d'] * np.log(s_['d'] / ys) - (s_['d'] - ys))
                return float(np.sum(dev) / s_['npts'])
            r = (y - s_['d']) / s_['d']
            return float(np.sum(r ** 2 * s_['d']) / s_['npts'])

        q_best = s['q']
        try:
            r_q = scipy.optimize.minimize_scalar(
                lambda q: _chi2_one_q(s, p_shared, scales[k], q),
                bounds=(s['q'] - 4.0, s['q'] + 4.0), method='bounded',
                options={'xatol': 1e-3})
            if np.isfinite(r_q.fun) and r_q.fun <= chi_before:
                q_best = float(r_q.x)
        except Exception:
            pass
        chi_after = _chi2_one_q(s, p_shared, scales[k], q_best)
        chi2_total += chi_after
        y_fit = (_A(s, q_best) @ p_shared) * s['dmax'] * scales[k] + s['bg']
        per.append({
            'name': s['name'], 'chi2R': float(chi_after), 'scale': float(scales[k]),
            'qshift': float(q_best), 'qshift_ns': float(
                q_best * (s['time'][1] - s['time'][0]) if len(s['time']) > 1 else 0.0),
            'fit_start': s['fit_start'], 'fit_end': s['fit_end'],
            'time': s['time'], 'decay': s['decay'], 'irf': s['irf'],
            'y_fitted': y_fit,
        })

    # ---------- 共享分布的峰分解 ----------
    _tick(0.97, "分解共享分布")
    tmp = MEMFitter(verbose=False, name='global')
    tmp.k = rates
    tmp.k_distribution = p_shared
    tmp.info = {'k_min': float(k_min), 'k_max': float(k_max),
                'n_rates': n_rates, 'method': method}
    try:
        tmp.postprocess()
    except Exception as e:
        if verbose:
            _safe_print(f"  [WARN] 共享分布峰分解失败（{e}）")
    peaks = list(tmp.peak_result or [])

    # 每个数据集的强度占比 = 共享占比（形状相同），仅幅度不同 → 占比一致，
    # 但绝对发光量按 scale 缩放；这里同时给出两者，便于做滴定曲线
    alpha = [float(row[1]) for row in peaks]
    for entry in per:
        entry['alpha'] = alpha
        entry['amplitude'] = [a * entry['scale'] for a in alpha]

    out = {
        'k': rates, 'k_distribution': p_shared, 'peak_result': peaks,
        'tau_list': [float(row[0]) for row in peaks],
        'scales': [float(v) for v in scales],
        'per_dataset': per, 'chi2R_total': float(chi2_total),
        'lambda_coeff': float(lam), 'method': method,
        'weight_mode': weight_mode,
        'solver_converged': bool(res.success),
        'solver_status': int(res.status),
        'solver_nit': int(getattr(res, 'nit', 0)),
        'info': {'k_min': float(k_min), 'k_max': float(k_max),
                 'n_rates': n_rates, 'n_datasets': n_sets,
                 'tau_min_ns': float(1.0 / k_max), 'tau_max_ns': float(1.0 / k_min),
                 'peaks_found': tmp.info.get('peaks_found'),
                 'peaks_dropped': tmp.info.get('peaks_dropped'),
                 'intensity_share_unassigned':
                     tmp.info.get('intensity_share_unassigned')},
    }
    if verbose:
        _safe_print(f"[全局拟合] {n_sets} 个数据集，Σχ²R = {chi2_total:.4g}，"
                    f"λ = {lam:.4g}，收敛 = {res.success}")
        _safe_print("  共享分量：" + "，".join(
            f"τ{i + 1}={row[0]:.4g} ns（{row[1] * 100:.1f}%）"
            for i, row in enumerate(peaks)))
        for entry in per:
            _safe_print(f"  {entry['name']}: χ²R={entry['chi2R']:.4g}, "
                        f"幅度={entry['scale']:.4g}")
    _tick(1.0, "全局拟合完成")
    return out


def fit_global_discrete(datasets, n_comp=2, tau_init=None, weight_mode='neyman',
                        n_restarts=3, verbose=True, progress_cb=None,
                        cancel_cb=None):
    """全局离散多指数拟合：**所有数据集共享寿命 τ_i，各自有自己的幅度**。

    与 `fit_global`（共享整个速率分布）的区别：这里把 τ_i 当作全局参数一起优化，
    每个数据集只解自己的幅度 a_{d,i}（给定 τ 时是线性问题，用 NNLS 精确求解）。
    适合**系列样品/滴定**（如 FRET A0→A24，供体寿命随受体浓度变化），
    不适合"同一个样品重复测量"（那种情况用 fit_global 共享分布更稳）。

    做法：交替 (a) 给定 τ 用 NNLS 解各数据集的幅度 → (b) 用 Nelder-Mead
    优化 log τ（n_comp ≤ 4，无导数也稳）；多组初值取最优。

    Args:
        datasets: [{'name','time','decay','irf','meta'}, ...]
        n_comp: 共享寿命分量个数（建议 2–4）
        tau_init: 初始 τ 列表（ns）；默认取各数据集单独 MEM 拟合的峰位平均
        weight_mode: 'neyman'（默认）/ 'pearson' / 'poisson'
        n_restarts: 初值组数（对数等距 + 单独拟合峰位）

    Returns:
        dict: {'taus': [τ_1..τ_m], 'per_dataset': [{'name','amplitudes','alpha',
              'chi2R','y_fitted', ...}], 'chi2R_total', 'solver_converged', ...}
    """
    datasets = list(datasets or [])
    if len(datasets) < 2:
        raise ValueError("全局拟合至少需要 2 个数据集")
    n_comp = int(n_comp)
    if not (1 <= n_comp <= 8):
        raise ValueError(f"n_comp 应在 1–8 之间（当前 {n_comp}）")

    def _tick(frac, msg):
        if progress_cb is not None:
            try:
                progress_cb(float(frac), str(msg))
            except Exception:
                pass

    def _check_cancel():
        if cancel_cb is not None and cancel_cb():
            raise FitCancelled("用户取消了全局拟合")

    # ---------- 预处理每个数据集 ----------
    sets = []
    for d in datasets:
        _check_cancel()
        f = MEMFitter(verbose=False, name=d.get('name', 'dataset'))
        f.load(d['time'], d['decay'], d['irf'], d.get('meta'))
        f.preprocess()
        info = f.info
        fs, fe = int(info['fit_start']), int(info['fit_end'])
        if fe - fs < 3:
            raise ValueError(f"{f.name}: 拟合窗口只有 {fe - fs} 点")
        irf1 = np.maximum(f.irf[:fe] - float(info.get('irf_background', 0.0)), 0.0)
        if not np.any(irf1 > 0):
            raise ValueError(f"{f.name}: 扣除基线后 IRF 全为 0")
        sets.append({
            'name': f.name, 'fs': fs, 'fe': fe,
            'bg': float(info['decay_background']),
            'dmax': float(info['decay_max']),
            'd': np.maximum(f.decay[fs:fe], 1.0),
            'npts': fe - fs, 'q': float(info['qshift_suggested']),
            'irf_norm': irf1 / irf1.sum(), 'time': f.time, 'decay': f.decay,
            'irf': f.irf, 'fitter': f,
        })
    n_sets = len(sets)

    def _basis(s, taus):
        """给定量程 τ 列表，返回该数据集的基函数 (npts, m)（单位幅度、含 IRF 卷积与位移）。

        构造顺序必须与 MEMFitter 一致：**先卷积、后按 qshift 做 PCHIP 平移**。
        反过来（先平移 IRF 再卷积）在 qshift 较大时会产生亚通道的系统性偏差，
        实测同一数据的 χ²R 会从 3.7 恶化到 285。
        """
        fe = s['fe']
        t_axis = s['time'][:fe]
        taus = np.maximum(np.asarray(taus, dtype=float), 1e-6)
        cols = np.exp(-t_axis[:, None] / taus[None, :])
        A_full = scipy.signal.fftconvolve(cols, s['irf_norm'][:, None],
                                          mode='full', axes=0)[:fe]
        pchip = scipy.interpolate.PchipInterpolator(
            np.arange(fe), A_full, axis=0, extrapolate=True)
        return pchip(np.arange(s['fs'] - s['q'], s['fe'] - s['q'] - 0.01))

    def _solve_amps(s, A):
        """给定基函数，NNLS 解幅度（返回 (amps, y_fit)）。"""
        target = s['d'] - s['bg']
        try:
            amps, _ = scipy.optimize.nnls(A * s['dmax'], target)
        except Exception:
            amps = np.linalg.lstsq(A * s['dmax'], target, rcond=None)[0]
            amps = np.maximum(amps, 0.0)
        y = (A @ amps) * s['dmax'] + s['bg']
        return amps, y

    def _chi2(s, y):
        if weight_mode == 'pearson':
            return float(np.sum((s['d'] - y) ** 2 / np.maximum(y, 1.0)) / s['npts'])
        if weight_mode == 'poisson':
            ys = np.maximum(y, 1e-9)
            dev = 2.0 * (s['d'] * np.log(s['d'] / ys) - (s['d'] - ys))
            return float(np.sum(dev) / s['npts'])
        r = (y - s['d']) / s['d']
        return float(np.sum(r ** 2 * s['d']) / s['npts'])

    def _total_chi2(log_taus):
        taus = np.exp(np.asarray(log_taus, dtype=float))
        tot = 0.0
        for s in sets:
            A = _basis(s, taus)
            _, y = _solve_amps(s, A)
            tot += _chi2(s, y)
        return tot

    # ---------- 初值：单独拟合峰位 + 对数等距 ----------
    inits = []
    if tau_init:
        inits.append(np.log(np.asarray(tau_init, dtype=float)))
    else:
        peaks = []
        for s in sets[:min(n_sets, 4)]:
            try:
                _check_cancel()
                f = MEMFitter(verbose=False, name=s['name'])
                f.load(s['time'], s['decay'], s['irf'])
                f.preprocess()
                f.fit(method='MEM', n_rates=101)
                f.postprocess()
                peaks += [float(p[0]) for p in (f.peak_result or [])]
            except Exception:
                pass
        peaks = [p for p in peaks if np.isfinite(p) and p > 0]
        if len(peaks) >= n_comp:
            peaks = np.sort(np.asarray(peaks))
            idx = np.linspace(0, len(peaks) - 1, n_comp).astype(int)
            inits.append(np.log(np.maximum(peaks[idx], 1e-4)))
    # 对数等距兜底初值（覆盖 0.1–30 ns）
    for lo, hi in ((0.2, 10.0), (0.5, 20.0), (0.1, 30.0)):
        inits.append(np.log(np.geomspace(lo, hi, n_comp)))
    inits = inits[:max(1, int(n_restarts) + 1)]

    # ---------- 优化 ----------
    best = None
    for i, x0 in enumerate(inits):
        _check_cancel()
        _tick(0.2 + 0.6 * i / max(len(inits), 1), f"全局离散拟合（初值 {i + 1}/{len(inits)}）")
        try:
            r = scipy.optimize.minimize(
                _total_chi2, x0, method='Nelder-Mead',
                options={'maxiter': 4000, 'xatol': 1e-6, 'fatol': 1e-10})
        except Exception:
            continue
        if best is None or r.fun < best.fun:
            best = r
    if best is None:
        raise RuntimeError("全局离散拟合失败：所有初值都未能收敛")

    taus = np.exp(np.asarray(best.x, dtype=float))
    order = np.argsort(taus)
    taus = taus[order]

    per = []
    chi2_total = 0.0
    for s in sets:
        _check_cancel()
        A = _basis(s, taus)
        amps, y = _solve_amps(s, A)
        chi2 = _chi2(s, y)
        chi2_total += chi2
        # 光子占比 ∝ 幅度 × τ（基函数是单位幅度指数）
        w = amps * taus
        alpha = (w / w.sum()).tolist() if w.sum() > 0 else [0.0] * len(taus)
        per.append({
            'name': s['name'], 'chi2R': float(chi2),
            'amplitudes': [float(v) for v in amps],
            'alpha': [float(v) for v in alpha],
            'qshift': float(s['q']),
            'fit_start': s['fs'], 'fit_end': s['fe'],
            'time': s['time'], 'decay': s['decay'], 'irf': s['irf'],
            'y_fitted': y,
        })

    out = {
        'taus': [float(v) for v in taus],
        'per_dataset': per, 'chi2R_total': float(chi2_total),
        'n_comp': n_comp, 'weight_mode': weight_mode,
        'solver_converged': bool(best.success),
        'solver_nit': int(getattr(best, 'nit', 0)),
        'model': 'discrete-shared-tau',
    }
    if verbose:
        _safe_print(f"[全局离散拟合] {n_sets} 个数据集，共享 {n_comp} 个寿命，"
                    f"Σχ²R = {chi2_total:.4g}（收敛 = {best.success}）")
        _safe_print("  共享寿命：" + "，".join(f"τ{i + 1}={t:.4g} ns"
                                              for i, t in enumerate(taus)))
        for e in per:
            _safe_print(f"  {e['name']}: χ²R={e['chi2R']:.4g}，占比="
                        + "/".join(f"{a * 100:.1f}%" for a in e['alpha']))
    _tick(1.0, "全局离散拟合完成")
    return out


def fit_lifetime(files, save_dir='./plots', method='MEM', show=False,
                 verbose=True, save_json=True, time_unit='ns', **fit_kwargs):
    """
    一键批量拟合荧光寿命。

    Args:
        files: 文件路径 / 通配符字符串 / 路径列表（CSV 或 xlsx 均可；
            .xlsx/.xls 按 parse_decay_xlsx 拆成多个数据集逐个拟合）
        save_dir: 图与 json 的输出目录（None 则不保存）
        method: "MEM"（最大熵）或 "SESM"（平滑指数序列）
        show: 是否弹出图窗
        save_json: 是否保存拟合结果 json
        time_unit: 只影响绘图显示（'ns' / 'us'，默认 'ns'），透传给 plot_result；
            内部计算与保存的结果数据（含 json）始终用 ns。
        **fit_kwargs: 透传给 MEMFitter.fit()（如 n_rates, res_tol, lambda_coeff,
                      auto_lambda, lambda_scan_range, k_min, k_max, max_runs,
                      n_starts, seed）

    Returns:
        list[dict]：每个数据集的完整拟合结果
    """
    file_list = _expand_files(files)
    if not file_list:
        raise FileNotFoundError("未找到任何输入文件")

    results = []
    for fp in file_list:
        _safe_print(f"\n===== 拟合: {fp} =====")
        dsets = None
        if Path(fp).suffix.lower() in ('.xlsx', '.xls'):
            try:
                dsets = parse_decay_xlsx(fp)
            except Exception as e:
                _safe_print(f"  [错误] {fp}: {e}")
                continue
        nested = [{'name': d['name'], 'data': d,
                   'file': fp} for d in (dsets or [])]
        if not nested:
            nested = [{'name': None, 'data': None, 'file': fp}]
        for nd in nested:
            try:
                fitter = MEMFitter(verbose=verbose, name=nd['name'])
                if nd['data'] is not None:
                    fitter.load(nd['data']['time'], nd['data']['decay'],
                                nd['data']['irf'], nd['data'].get('meta'))
                else:
                    fitter.from_file(fp)
                fitter.preprocess()
                fitter.fit(method=method, **fit_kwargs)
                fitter.postprocess()
                name = fitter.name
                out_json = (Path(save_dir) / f"{name}_fit_result.json"
                            if (save_json and save_dir is not None) else None)
                result = fitter.serialize(out_json)
                result['file'] = str(fp)
                results.append(result)
                plot_result(result, save_dir=save_dir, name=name, show=False,
                            time_unit=time_unit)
            except Exception as e:
                _safe_print(f"  [错误] {fp}: {e}")
    if show and results:
        plt.show()
    plt.close('all')
    _safe_print(f"\n完成：成功拟合 {len(results)} / {len(file_list)} 个文件"
                + (f"，结果保存在 {save_dir}" if save_dir else ""))
    return results


# ======================== 5. 命令行入口 ========================

def main():
    parser = argparse.ArgumentParser(
        description='荧光寿命拟合（最大熵 MEM + IRF 重卷积）')
    parser.add_argument('-i', '--input', required=True,
                        help='衰减数据文件（CSV），支持通配符，如 "D:/data/*.csv"')
    parser.add_argument('-o', '--output', default='./plots',
                        help='图与 json 结果的输出目录（默认 ./plots）')
    parser.add_argument('-m', '--method', choices=('MEM', 'SESM'), default='MEM',
                        help='拟合方法：MEM=最大熵（默认），SESM=平滑指数序列（更快）')
    parser.add_argument('--n_rates', type=int, default=201,
                        help='速率网格点数（默认 201）')
    parser.add_argument('--tol', type=float, default=1e-2,
                        help='主迭代终止容限（默认 1e-2）')
    parser.add_argument('--lambda', dest='lambda_coeff', type=float, default=1e-3,
                        help='MEM 熵权重 λ（默认 1e-3）')
    parser.add_argument('--auto-lambda', action='store_true',
                        help='自动拟合 λ（MEM → λ 扫描 → MEM，仅 MEM 方法）')
    parser.add_argument('--show', action='store_true', help='显示图窗')
    parser.add_argument('--export', action='store_true',
                        help='拟合后额外导出 CSV/XLSX 汇总表与每文件 md 报告')
    parser.add_argument('--time-unit', choices=TIME_UNIT_KEYS, default='ns',
                        help='绘图与导出表格的时间单位（ns / us，默认 ns）；'
                             '只影响显示，内部计算始终用 ns')
    parser.add_argument('-q', '--quiet', action='store_true', help='静默模式')
    args = parser.parse_args()

    results = fit_lifetime(
        files=args.input,
        save_dir=args.output,
        method=args.method,
        show=args.show,
        verbose=not args.quiet,
        n_rates=args.n_rates,
        res_tol=args.tol,
        lambda_coeff=args.lambda_coeff,
        auto_lambda=args.auto_lambda,
        time_unit=args.time_unit,
    )
    if args.export and results:
        written = export_fit_results(results, args.output,
                                     name="lifetime_fit_results",
                                     time_unit=args.time_unit)
        _safe_print(f"[导出] 写出 {len(written)} 个文件：")
        for w in written:
            _safe_print(f"  - {w}")


if __name__ == '__main__':
    main()
