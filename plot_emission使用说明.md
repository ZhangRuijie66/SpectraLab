# 📊 plot_emission.py 使用说明

> 荧光发射光谱 CSV 批量绘图工具  
> 适用格式：
> 1. **Spectracle / FE30** 输出的"发射数据组" CSV 文件
> 2. **LabSolutions RF / RF-6000** 输出的 Emission CSV 文件（如 D2O.csv）
> 3. **PerkinElmer FL WinLab 风格**的发射扫描 CSV（如 `EmScan1.csv`，含 Labels/Type/Fixed-Offset/XAxis 字段）
>
> 格式自动检测，无需手动指定。
>
> **多光谱数据**：可直接引用 `plot_spectra` / `plot_single` / `plot_combined` 等函数，
> 一次调用同时得到【每条单独图】+【合并图】（见下方"Python 直接引用函数"）。
>
> **激发光谱自动跳过**：`load_spectra` / `plot_spectra` / `plot_single` / `plot_combined`
> 均默认跳过 Spectrum Type = Excitation 的激发光谱（传 `skip_excitation=False` 可关闭）。

---

## 🚀 方式一：命令行（CLI）

```bash
python plot_emission.py <文件...> [选项]
```

### 📂 位置参数

| 参数 | 说明 |
|:------|:------|
| `files` | 一个或多个 CSV 文件路径，支持通配符 `*.csv`（支持混合格式） |

### ⚙️ 可选参数

| 参数 | 类型 | 默认值 | 说明 |
|:------|:------|:------|:------|
| `-o, --out` | `str` | `plots_emission` | 输出图片的目录路径 |
| `--no-show` | flag | 关闭 | 不弹出图像窗口，适合批量处理 |
| `--normalize` | flag | 关闭 | 合并图归一化到 [0, 1]，便于比较峰形 |
| `--xlim XMIN XMAX` | `float float` | 自动 | 手动指定横轴波长范围（nm），如 `--xlim 500 700` |
| `--show-ex` | flag | 关闭 | 在单独图上绘制红色虚线标注激发波长位置 |
| `--no-peaks` | flag | 关闭 | 关闭自动标峰功能 |
| `--peak-height` | `float` | `0.05` | 峰最小高度（占光谱最大值的比例）。**减小** → 检测更多弱峰；**增大** → 忽略噪声 |
| `--peak-distance` | `float` | `10` | 两峰之间的最小间距（nm）。**减小** → 分辨相邻小峰 |
| `--peak-prominence` | `float` | `0.03` | 峰最小突出度（占光谱最大值的比例）。**减小** → 肩膀峰也识别 |
| `--no-single` | flag | 关闭 | 不绘制每条单独图 |
| `--no-combined` | flag | 关闭 | 不绘制合并图 |

> CLI 默认行为：**每条光谱一张单独图 + 一张合并图**（合并图仅当有效数据 ≥2 条时生成）。

### 📝 CLI 使用示例

```bash
# 最基本：处理单个 Spectracle 文件
python plot_emission.py "发射数据组 2026-07-28 02-42.csv"

# 处理 RF-6000 格式（自动识别）
python plot_emission.py "..\260728-A226-RF6000\D2O.csv"

# 混合格式批量处理（多条光谱 → 自动单独图 + 合并图）
python plot_emission.py "发射数据组 2026-07-28 02-42.csv" "..\260728-A226-RF6000\D2O.csv"

# 批量处理所有 CSV，静默模式
python plot_emission.py *.csv --no-show

# 只关注可见光区，合并图归一化
python plot_emission.py *.csv --xlim 400 700 --normalize

# 只画合并图，不画单独图
python plot_emission.py *.csv --no-single

# 显示激发波长虚线
python plot_emission.py data.csv --show-ex

# 全功能组合
python plot_emission.py *.csv -o results --xlim 450 750 --normalize --peak-height 0.03 --show-ex
```

---

## 🐍 方式二：Python 直接引用函数（推荐，可复用）

把 `画图` 目录加入 `sys.path` 后直接 import，适合写进自己的分析脚本：

```python
import sys
sys.path.insert(0, r'D:\北大\光谱工具')

from plot_emission import plot_spectra, load_spectra, plot_single, plot_combined
```

### 1️⃣ `plot_spectra(...)` — 多光谱一键：单独图 + 合并图（最常用）

```python
# 传文件列表：自动解析 → 每条单独图 + 合并图，返回全部数据集
datasets = plot_spectra(
    files=[r'...\RB.csv', r'...\Zn-5.csv', r'...\Zn-6.csv'],
    save_dir=r'...\plots_emission',   # 输出目录（自动创建）
    show=False,                       # 不弹窗，只存图
    xlim=(300, 500),                  # 可选：横轴局部放大
    normalize=False,                  # 可选：合并图归一化到 [0,1]
    show_ex=False,                    # 可选：标注激发波长虚线
    annotate_peaks=True,              # 自动标峰
    skip_excitation=True,             # 跳过激发光谱（默认 True）
    combined_fname='combined_emission.png',
)

# 也支持通配符（跨 shell 自动展开）
datasets = plot_spectra('*.csv', save_dir='out', show=False)

# 返回的 datasets 可直接复用：
from plot_emission import plot_combined
plot_combined(datasets, save_dir='out', show=False, xlim=(400, 700),
              fname='combined_zoom_400_700.png')
```

### 2️⃣ `load_spectra(files, ...)` — 只解析、不画图

```python
datasets = load_spectra([r'...\RB.csv', r'...\Zn-5.csv'], skip_excitation=True)
print(len(datasets), "条光谱")
# 之后再自行调用 plot_single / plot_combined
```

> 说明：`load_spectra` 解析时已跳过激发光谱；即使传入的数据里混有激发光谱，
> `plot_single` / `plot_combined` 也会自动跳过（`skip_excitation=False` 可关闭）。

### 3️⃣ `plot_single(...)` — 单独图（支持 1 条或多条）

```python
# 画 1 条
plot_single(datasets[0], save_dir='out', show=False)

# 一次画多条（每条一张图）——多光谱直接引用即可
plot_single(datasets, save_dir='out', show=False, xlim=(300, 500))

# 自定义文件名（单条时）
plot_single(datasets[0], save_dir='out', show=False,
            fname='RB_emission.png', dpi=300)
```

### 4️⃣ `plot_combined(...)` — 合并图（多条叠加一张）

```python
saved = plot_combined(datasets, save_dir='out', show=False,
                      normalize=True,          # 归一化比较峰形
                      xlim=(400, 700),
                      fname='combined_400_700.png')
# 返回保存路径；有效数据不足 2 条时返回 None
```

### 📋 函数返回值速查

| 函数 | 返回 |
|:------|:------|
| `load_spectra(files)` | `list[dict]`：全部光谱数据集 |
| `plot_spectra(...)` | `list[dict]`：解析得到的数据集（便于复用） |
| `plot_single(...)` | `list[Path]`：已保存的单独图路径 |
| `plot_combined(...)` | `Path 或 None`：合并图路径（不足 2 条返回 None） |

数据集 dict 键：`label`（或 `name`）、`ex_wl`（或 `ex`）、`wl`、`intensity`（可选 `spectrum_type`）。

---

## 📦 输出文件

| 文件 | 说明 |
|:------|:------|
| `<标签名>.png` | 每条光谱单独一张图 |
| `combined_emission.png` | 所有光谱叠加对比图（仅当 ≥2 条时生成） |

---

## 📋 支持的三种格式

### Spectracle / FE30 格式
- 文件含"发射数据组"、"波长(nm)"等中文字段
- 支持双通道数据（两列光谱）
- 自动提取标签、EX WL、评论

### LabSolutions RF / RF-6000 格式
- RF-6000 仪器输出的 Emission 光谱
- 自动提取 Sample Name、EX Wavelength、Spectrum Type
- 元数据与数据区域自动分离

### PerkinElmer FL WinLab 风格（新增）
- 纯英文、无中文表头的发射扫描 CSV（如 `EmScan1.csv`）
- 元数据块为 `Labels,<名称>,` / `Type,Emission Scan,` / `Comment,,` /
  `Start/Stop/Step` / `Fixed/Offset,<波长>,` / `XAxis,Wavelength` / `YAxis,Counts`
- 空行之后为数据块：`<波长>,<强度>,`（每行两列，末位常有逗号）
- 自动提取标签（Labels）、激发波长（Fixed/Offset）作为 EX WL、光谱类型

**程序会自动检测格式，无需手动指定。**

---

## 🎯 调峰速查

| 现象 | 对策 |
|:------|:------|
| 漏掉明显的峰 | ⬇️ 降低 `peak_height` 和 `peak_prominence` |
| 噪声被误标成峰 | ⬆️ 提高 `peak_height` 或 `peak_prominence` |
| 两个紧邻峰被当成一个 | ⬇️ 减小 `peak_distance` |
| 峰标注和标题重叠 | ⬇️ 降低 `peak_height` 过滤高耸峰，或扩大 `xlim` |
| 合并图图例太拥挤 | 加 `annotate_peaks=False` 关闭标注 |
