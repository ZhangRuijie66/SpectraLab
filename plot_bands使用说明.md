# plot_bands 使用说明

**谱带分解与定量**（多峰分解 + 两带面积比）

吸收/发射谱常常是**多条谱带叠在一起**。现有的 `find_peaks` 只能找局部极大，
遇到这三种情况就不够了：

| 情况 | `find_peaks` 的表现 | 本模块 |
| --- | --- | --- |
| ESIPT 的 enol\*/keto\* 双发射 | 只给两个峰位，给不出"各占多少" | 每带面积、面积占比、两带面积比 |
| 罗丹明的振动肩峰 | **只给 1 个峰**（肩峰不是局部极大） | 把肩峰分解成独立谱带 |
| 稀土/多带重叠 | 分不开重叠带 | 按峰形模型拆分并给置信指标 |

---

## 1. 它需要什么数据

| 输入 | 说明 |
| --- | --- |
| 发射光谱 | Spectracle/FE30「发射数据组」、LabSolutions RF-6000、PerkinElmer FL WinLab |
| 吸收光谱 | LabSolutions UV-Vis |
| 或者直接给数组 | `(label, wl, y)` 三元组 / `{'label','wl','y'}` dict |

解析**完全复用**现成模块（`plot_emission.parse_csv` / `load_spectra`、
`plot_absorption.load_absorption_spectra`），本模块不重写解析。
`kind='auto'` 时按文件前 60 行表头逐文件判断吸收还是发射，认不出按发射处理。

---

## 2. 核心概念

### 2.1 三种峰形

| `model` | 公式 | 什么时候用 |
| --- | --- | --- |
| `gaussian` | `h·exp(-(x-c)²/2σ²)` | 仪器展宽为主（多数液体样品） |
| `lorentzian` | `h·γ²/((x-c)²+γ²)` | 均匀展宽/寿命展宽为主，两翼拖很长 |
| `pseudo_voigt` | `h·[(1-η)G + ηL]` | 不确定时用它，η 由拟合给出（0=纯高斯，1=纯洛伦兹） |

**三者 FWHM 定义一致**（都是半高全宽），所以换峰形后峰位与 FWHM 仍可直接比较。
伪 Voigt 的 η 只改变两翼权重、**不改变半高宽**（G 和 L 在 dx=FWHM/2 处都恰好
等于 0.5），因此在 η∈[0,1] 内加权和仍是"峰值 h、FWHM=fwhm"。

**峰形选错的代价**（合成真值实测，真值为洛伦兹）：

| 拟合用的峰形 | R² | 面积误差 |
| --- | --- | --- |
| `lorentzian`（正确） | 0.999682 | +0.07% / +0.24% / -0.40% |
| `gaussian` | 0.956574 | **-14.93% / -10.48% / -12.10%** |

用错峰形时 R² 看着还行（0.957），但**面积系统性偏小 10–15%**——
所以面积比这类要跨样品比较的量，峰形必须选对。

### 2.2 面积是解析积分，不是数值积分

| 峰形 | 面积公式 |
| --- | --- |
| `gaussian` | `A = √(2π)·σ·h`，σ = FWHM/(2√(2ln2)) |
| `lorentzian` | `A = π·γ·h`，γ = FWHM/2 |
| `pseudo_voigt` | `A = (1-η)·A_G + η·A_L` |

为什么不数值积分：梯形积分对**宽洛伦兹尾**会按窗口截断而系统性偏小
（实测把 ±400 nm 窗口上的洛伦兹积分与解析值比，差 0.24%——窗口再窄差得更多），
对窄高峰又受采样点数限制。解析式只依赖三个拟合参数，可比、可外推。

### 2.3 自动定阶：BIC + 可分辨性守卫

`n_peaks=None` 时在 1…`max_peaks` 里选峰数，判据是 **BIC**：

```
BIC = n·ln(RSS/n) + k·ln(n)      k = 参数总个数
```

**但只用 BIC 会过拟合**，原因是真实光谱被**过采样**：LabSolutions 是 0.5 nm
步长，一条 150 nm 的带上有 301 个点，相邻点残差相关系数实测 **ρ≈0.995**。
此时 `n` 远大于独立信息量，`n·ln(RSS/n)` 把"多塞一个峰去咬残差纹理"的收益
放大几十倍，BIC 于是单调偏向峰数上限。

实测罗丹明数据：BIC 在 n=1..6 上单调下降，选出 6 峰方案，而那 6 峰里相邻峰的
`sep/mean(FWHM)` 只有 **0.20**（同一条带被劈成两半）；物理上合理的解是 2 峰。

所以定阶分两级：

1. **可分辨性**：相邻峰 `sep/mean(FWHM) ≥ min_separation`（默认 **0.45**）。
   低于它的方案不参与比选——这一步只看几何，与噪声无关。
2. 在满足条件的方案里取 BIC 最小。

实测评据依据：合成三峰的正确解 `sep/FWHM = 2.00`，过拟合解掉到 `0.46`。
若**没有任何**方案满足（窄峰叠在宽带上的极端情形），退回全体取 BIC 最小，
并在结果里标 `separation_limited=True`。

### 2.4 饱和平台会被自动挖掉

FE30 的强度是整数且量程上限 50000。实测
`示例数据/测试数据/20260723-ESIPT-1-DMF` 的发射数据：

- EX=460 谱：**459–463 nm 连续 5 个点都是 50000**
- EX=350 谱：**346–355 nm 连续 10 个点都是 50000**

那是散射峰顶到量程被削平，**不是谱带**：它的峰高由量程决定、峰宽由饱和点数
决定，两者都不是物理量。拟合若把它当一条带，会得到一个"又高又窄"的假峰并
分走一大块占比——实测该 460 nm 样品因此被判出 460.9 nm 的假带、占比 30.9%。

`drop_clipped=True`（默认）会自动检测并整段挖掉。真要在饱和数据上硬拟合，
传 `drop_clipped=False`。

---

## 3. 命令行用法

```bash
# 先看能读到哪些光谱（不拟合）
python plot_bands.py "D:\data\ESIPT" --list

# ESIPT 双发射：拆出 enol*/keto*（挖掉 350 nm 散射与 700 nm 倍频）
python plot_bands.py "D:\data\20260723-ESIPT-1-DMF" --kind emission \
    --range 390 660 --exclude-scatter 350

# 同时出两带面积比曲线
python plot_bands.py "D:\data\ESIPT" --range 390 660 --exclude-scatter 350 \
    --band-a 400 510 --band-b 520 660

# 罗丹明肩峰：窗口收紧到可见吸收带
python plot_bands.py "D:\data\uvvis" --kind absorption --range 470 620

# 指定 2 峰、用伪 Voigt（谱带两翼较长时）
python plot_bands.py "D:\data\uvvis" --kind absorption --range 470 620 \
    --n-peaks 2 --model pseudo_voigt

# 顺手输出每个样品的 BIC 定阶曲线
python plot_bands.py "D:\data\uvvis" --range 470 620 --order-figure

# 关闭饱和检测（默认是开的）
python plot_bands.py "D:\data\uvvis" --range 470 620 --keep-clipped
```

**输出**（默认到 `./plots`，**不弹窗**）：

| 文件 | 内容 |
| --- | --- |
| `bands_<样品>.png` | 单谱分解图：实测 + 总拟合 + 各分峰 + 本底 + 下方残差面板 |
| `bands汇总_all.png` | 多谱并排汇总（各自归一化，便于比谱形） |
| `bands峰表_all.csv` | 峰表：每峰一行（峰位/峰高/FWHM/面积/占比/η/是否贴边界） |
| `bands比值_all.png` | 两带面积比曲线（下方多一个面板画两带绝对面积柱状） |
| `bands比值_all.csv` | 比值表 |

参数速查：

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `--model` | `gaussian` | `gaussian` / `lorentzian` / `pseudo_voigt` |
| `--n-peaks` | 自动 | 指定峰数则不再扫 BIC |
| `--max-peaks` | `6` | 自动定阶上限 |
| `--baseline` | `const` | `none` / `const` / `linear` |
| `--range LO HI` | 全谱 | 拟合窗口（nm），**强烈建议给** |
| `--exclude LO HI` | — | 挖掉区间，可重复 |
| `--exclude-scatter EX` | — | 自动挖 λex 与 2λex 处的散射/倍频 |
| `--scatter-width` | `12` | 上面那个的挖除半宽（nm） |
| `--keep-clipped` | 关（即默认挖） | 不自动挖饱和平台 |
| `--clipped-min-points` | `3` | 判饱和的最少连续点数 |
| `--criterion` | `bic` | `bic` / `aic` |
| `--min-separation` | `0.45` | 可分辨性阈值；设 0 = 纯 BIC |
| `--min-share` | `0.01` | 面积占比低于此值的带子会被精简掉 |
| `--normalize` | 关 | 先归一化再拟合 |
| `--band-a` / `--band-b` | — | 两带窗口，两个都给才出比值图 |
| `--save-dir` | `./plots` | 输出目录 |
| `--dpi` | `EXPORT_DPI_DEFAULT` | 导出 DPI |

---

## 4. 在 Python 里调用

### 4.1 单条谱分解

```python
from plot_bands import decompose_bands, format_decomposition

res = decompose_bands(
    wl, y,
    model='gaussian',
    baseline='const',
    wl_range=(470, 620),      # 拟合窗口
    n_peaks=None,             # None = 自动定阶
    max_peaks=6,
)

print(res['ok'], res['n_peaks'], res['r2'])
for p in res['peaks']:                      # 已按峰位排序
    print(p['center'], p['fwhm'], p['area'], p['area_share'])
    print(p['at_bound'])                    # True = 峰位贴在窗口边界，面积只能当下限

print(format_decomposition(res))            # 现成的中文摘要
```

返回 dict 的主要字段：

| 字段 | 含义 |
| --- | --- |
| `ok` / `message` | 是否成功；失败时其余字段是 NaN/空列表，**不会抛错** |
| `peaks` | 每峰一个 dict：`center / height / fwhm / sigma / area / area_share / eta / component / at_bound` |
| `total_area` | 各带解析面积之和 |
| `r2 / rmse / rss` | 拟合质量 |
| `bic / aic` | 定阶指标 |
| `baseline` / `baseline_y` | 本底参数与曲线 |
| `fit` / `residual` | 总拟合曲线与残差 |
| `order_scan` | 自动定阶时每档峰数的 R²/RMSE/BIC/AIC/`separation`/`resolvable` |
| `separation` / `min_separation` / `separation_limited` | 可分辨性诊断 |
| `pruned` | 是否被 `min_share` 精简过 |

### 4.2 两带面积比

```python
from plot_bands import compare_band_ratios, band_areas

# 只要数值，不出图：save_dir=None
rat = compare_band_ratios(
    datasets, band_a=(400, 510), band_b=(520, 660),
    save_dir=None,                    # None → figure/csv 都返回 None
    wl_range=(390, 660), exclude_scatter=350,
)
for row in rat['table']:
    print(row['label'], row['area_a'], row['area_b'], row['ratio'])

# 已有分解结果时直接算两带面积
ba = band_areas(res, band_a=(400, 510), band_b=(520, 660))
print(ba['a'], ba['b'], ba['ratio'])       # ratio = B / A
```

`band_a`/`band_b` 可以是波长窗口 `(lo, hi)`、带的下标 `int`，或 `None`（= 全部）。

**为什么按峰位归窗、而不对原始曲线做梯形积分**：两带重叠时窗口积分会把邻带的
尾巴算进来（ESIPT 的 enol\* 尾巴一直拖到 keto\* 峰顶下面）。分解后每条带的面
积是解析的、互不重叠的。

### 4.3 一键批量

```python
from plot_bands import run_bands, load_bands_spectra

out = run_bands(
    folder=r'D:\data\20260723-ESIPT-1-DMF',
    kind='emission',
    wl_range=(390, 660),
    exclude_scatter=350,
    band_a=(400, 510), band_b=(520, 660),
    save_dir=r'./plots',
)
print(out['figures'], out['summary_figure'], out['peaks_csv'])
print(out['ratios']['summary'])

# 只要数据不要图
dss = load_bands_spectra([r'D:\data\uvvis'], kind='auto')
```

### 4.4 单独画图（GUI 集成用得上）

```python
from plot_bands import plot_decomposition, plot_order_scan, plot_bands_summary

fig, summary = plot_decomposition(wl, y, res, label='样品1',
                                  save_path=None)    # None = 不存盘
fig2, _ = plot_order_scan(res, save_path=None)
fig3, _ = plot_bands_summary([('样品1', res)], save_path=None)
```

三个函数都支持传入 `fig=` 在现成画布上重画（GUI 的画布），并且**自己恢复
`subplots_adjust` 边距**——`MplCanvas` 初始把边距设成 0，不恢复会把坐标轴
标签算到画布外。

---

## 5. GUI 里怎么用

> 本节描述**建议的**集成方式，实际控件由维护者在 GUI 里统一接入。

吸收 / 发射模式的参数栏新增「**谱带分解**」分组（仿 `lifetime_options_group`，
默认 `setVisible(False)`）：

1. 勾选启用 + 选**峰形**（高斯/洛伦兹/伪 Voigt）、**峰数**（自动/1–6）、**本底**；
2. 填**拟合窗口**（默认取当前显示范围）与**散射挖除**（λex，默认填该谱的 EX）；
3. 点「**谱带分解**」→ 后台线程调 `decompose_bands(...)`，把结果存
   `self._last_bands_result`，在画布上调 `plot_decomposition(..., fig=self.canvas.fig)`
   重画，摘要用 `format_decomposition()` 写进 `info_label`；
4. 「导出」分支调 `peaks_to_csv()` + 存图；
5. 两带比值：再给两个窗口输入框，调 `compare_band_ratios(datasets, band_a, band_b,
   save_dir=None)` 只取数值，图自己画到第二个画布。

**注意**：`decompose_bands` 是 CPU 密集的（自动定阶要拟合 6 档 × 6 起点），
必须放在 `PlotWorker` 后台线程里；参数微调的防抖回调里要提前 return，
不要让滑杆每动一下就触发整轮定阶。

---

## 6. 已知限制

1. **`exclude_scatter` 是整批统一值**，不会按每条谱自己的 λex 分别处理。
   一个文件夹混着多个激发波长时（实测 `20260723-ESIPT-1-DMF` 同一个 CSV 里
   既有 EX=460 又有 EX=350），给单个数值只能挖掉其中一条的散射位置。
   此时按 λex 分组分次调用，或用 `exclude=[(lo,hi), ...]` 一次列全。
2. **峰数上限建议 ≤ 6**。带数超过真实谱带数时，多出来的峰会去分噪声。
3. **面积依赖峰形假设**。峰形选错时面积会系统性偏差（高斯拟合洛伦兹实测偏小
   10–15%），跨样品比较前请先确认峰形。
4. **`at_bound=True` 的带子面积只能当下限**——峰位贴在拟合窗口边界，说明这条
   带的中心在窗外。
5. 只支持 `numpy / scipy / pandas / matplotlib`，不引入新依赖。

---

## 7. 依赖与打包

只用到 `numpy / scipy / matplotlib`（`scipy.optimize.curve_fit`、
`scipy.signal.find_peaks`）；解析委托同目录的 `plot_emission` /
`plot_absorption`（懒加载），DPI 取自 `export_defaults`。

GUI 打包脚本需要 `--hidden-import plot_bands`。
