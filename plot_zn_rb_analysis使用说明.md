# 📊 plot_zn_rb_analysis.py 使用说明

> Zn 系列 + RB（参照）光谱分析与绘图（可复用源码）
>
> 功能：
> 1. **单独光谱图**（多光谱逐条成图，可选）：`plot_individual`
> 2. **合并局部放大图**（默认 300–500 nm），RB 自动标注为 "RB（参照）"
> 3. **区间峰值查找**（默认 400–500 nm）+ 峰表 CSV
> 4. **RB 归一化浓度图**（RB 峰值 = 1，横轴为 ZnPcS4 浓度）
>
> **多光谱数据直接引用函数**：多个样品时，`analyze_zn_rb_folder(..., individual=True)`
> 一键同时输出【每条单独图】+【合并放大图】+ 峰表 + 浓度图；
> 也可以单独引用 `plot_individual`（单独图）和 `plot_combined_zoom`（合并图）。
>
> 激发光谱（Spectrum Type = Excitation）默认跳过，不参与绘图与峰表。

---

## 🚀 一键调用

```python
import sys
sys.path.insert(0, r'...\谱图\光谱\画图')   # 指向共享源码目录
from plot_zn_rb_analysis import analyze_zn_rb_folder, read_zn_info

info = read_zn_info(r'...\20260731\说明.xlsx')   # 读取说明.xlsx 全部浓度/备注

analyze_zn_rb_folder(
    data_dir=r'...\20260731',                 # CSV 所在目录
    out_dir=r'...\20260731\plots_emission',   # 输出目录（自动创建）
    samples=[
        {'file': 'RB.csv',   'name': 'RB',   'zn_conc': 0.0},
        {'file': 'Zn-5.csv', 'name': 'Zn-5', **info[5]},   # 自动带全部分量信息
        {'file': 'Zn-6.csv', 'name': 'Zn-6', **info[6]},
        {'file': 'Zn-7.csv', 'name': 'Zn-7', **info[7]},
    ],
    individual=True,   # 多光谱时同时输出每条单独图（默认 False）
)
```

一键会依次完成：加载数据（跳过激发光谱）→ **（individual=True 时）每条单独图** →
合并局部放大图 → 峰表 → 归一化浓度图。

---

## 📋 samples 列表格式

每项为一个 dict：

| 键 | 必填 | 说明 |
|:---|:---|:---|
| `file` | ✔ | CSV 文件名（相对 data_dir）或绝对路径 |
| `name` | ✔ | 样品短名，用于颜色/参照识别/单独图文件名（参照样品名默认 `RB`） |
| `zn_conc` | ✔ | ZnPcS4 浓度（μmol/L），RB 填 0；浓度图中忽略为 None 的样品 |
| `l8i` / `cpc` / `note` | ✘ | L8i 浓度、CPC 浓度、备注（说明.xlsx 信息），缺省时自动加入图例 |
| `label` | ✘ | 完全自定义图例显示名；缺省时自动生成（RB → "RB（参照）"，Zn → "Zn-x（ZnPcS4=…, L8i=…, CPC=…，备注）"） |

`read_zn_info(excel_path)` 返回 `{编号: {zn_conc, l8i, cpc, note}}`，可直接用 `**info[编号]` 展开进 samples。

---

## ⚙️ analyze_zn_rb_folder 可选参数

| 参数 | 默认值 | 说明 |
|:---|:---|:---|
| `xlim` | `(300, 500)` | 合并图横轴范围（nm）；同时用于单独图的横轴范围 |
| `peak_range` | `(400, 500)` | 峰值查找区间（nm） |
| `rb_name` | `'RB'` | 参照样品名（归一化基准） |
| `zoom_fname` | `combined_zoom_300_500.png` | 合并图文件名 |
| `table_fname` | `peaks_400_500.csv` | 峰表文件名 |
| `conc_fname` | `ZnPcS4_concentration_RB_normalized.png` | 浓度图文件名 |
| `title` | 自动 | 合并图标题 |
| `conc_title` | 自动 | 浓度图标题 |
| `annotate_peaks` | `True` | 合并图是否标注峰位（不标峰传 `False`） |
| `normalize_to` | `None` | 合并图归一化基准样品名（如 `'RB'`，该样品峰值 = 1）；不归一化传 `None` |
| `individual` | `False` | **多光谱时传 `True`**，额外为每条光谱单独成图（文件名 `<name>_emission.png`） |
| `dpi` | `200` | 输出分辨率 |

---

## 🔧 单独调用

每个环节也可独立使用：

```python
from plot_zn_rb_analysis import (
    load_emission_datasets,
    plot_individual,          # 单独图（每条一张）
    plot_combined_zoom,       # 合并局部放大图
    export_peak_table,
    plot_rb_normalized_concentration,
)

datasets = load_emission_datasets(data_dir, samples)      # 加载（跳过激发谱）

# 多光谱 → 单独图：每条光谱各画一张 PNG
plot_individual(datasets, 'out', xlim=(300, 500))

# 多光谱 → 合并图：局部放大合并
plot_combined_zoom(datasets, 'zoom.png', xlim=(300, 500))

df, rb_peak = export_peak_table(datasets, 'peaks.csv')    # 峰表 + RB 峰值
plot_rb_normalized_concentration(datasets, 'conc.png')    # RB=1 浓度图
```

`plot_individual` 返回已保存的文件路径列表；参数 `xlim`（横轴范围）、
`annotate_peaks`、`peak_height`、`peak_distance`、`peak_prominence`、`show_ex`、
`dpi`、`suffix`（文件名后缀）均可按需传入。

不标峰、按 RB 峰值归一化的合并图（RB 在 `peak_range` 内的峰值为 1）：

```python
plot_combined_zoom(
    datasets,
    'zoom_normalized_RB.png',
    annotate_peaks=False,
    normalize_to='RB',
)
```

---

## 📦 输出文件

| 文件 | 说明 |
|:---|:---|
| `<name>_emission.png` | 每条光谱单独图（仅 `individual=True` 时生成） |
| 合并图 PNG | 各光谱叠加 + 峰位标注，RB 加粗为参照 |
| 峰表 CSV | 样品/文件/类型/EX/浓度/峰值波长/峰值强度/相对RB |
| 浓度图 PNG | 纵轴 = 峰值/RB峰值（RB=1），横轴 = ZnPcS4 浓度 |

---

## 📝 示例（20260731）

```python
python "..\20260731\plot_Zn5_7_RB.py"
```

该脚本从 `说明.xlsx` 自动读取浓度，只处理发射光谱（Zn-8-ex.csv 仅有激发光谱，自动跳过）。
如需同时输出每条单独图，在脚本的 `analyze_zn_rb_folder(...)` 调用中加 `individual=True` 即可。
