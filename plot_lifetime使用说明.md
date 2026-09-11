# 荧光寿命拟合工具使用指南

## 概述

`plot_lifetime.py` 是荧光寿命拟合模块，从 FluoIt（Edward Kerman，MIT License）移植算法，
**纯 numpy/scipy 实现，不需要 pyTorch / GPU**。

核心方法：**最大熵算法（MEM）+ IRF 重卷积**。不假设寿命分量的个数，而是在对数速率网格
（k = 1/τ，默认 0.01–100 ns⁻¹ 共 201 个点）上直接求最平滑（最大熵）的速率分布，
分布中的每个峰即对应一个寿命分量——适合 ESIPT 等存在多组分/连续分布的体系。

处理流程：
1. **预处理**：自动统计 IRF FWHM、背景、上升沿；tail-fitting 估计 IRF 与衰减曲线的
   时间位移；自动确定拟合区间
2. **主拟合**：预先将 201 条单指数衰减与 IRF 卷积 → 多起点 SLSQP 粗估 →
   交替优化（IRF 位移 qshift ↔ 速率分布），目标函数 `χ² − λ·S`（S 为 Shannon 熵），
   相邻两轮改进量 < 容限即收敛
3. **后处理**：对速率分布做多重高斯分解，给出各分量的 τ、面积占比、FWHM
4. **出图**：衰减拟合图（log 轴 + 残差 + χ²ᴿ）与寿命分布图（log τ 轴 + 各高斯分量）

## 支持的数据格式（自动检测）

1. **Horiba / DeltaHub 时间扫描 CSV**（如 `Decay2.csv`）：头部含
   `Labels,Decay2,IR1` / `Type,Time Scan,Instrument Response Time Scan` 等元数据，
   数据区三列 time, decay, irf
2. **简单三列 CSV**：第一列 time（ns），第二列 decay，第三列 irf，可有表头
3. **多列衰减 xlsx**（首行为表头，按列自动拆分，一个文件可含多个样品）：
   - **布局 A（多样品共用一份 IRF）**：`Time (ns) | S1 | S2 | S3 | IRF`
   - **布局 B（每个样品各配一份 IRF，成对交替）**：
     `Time (ns) | 0nM | IRF | 50nM | IRF | ... | 500nM | IRF`
     —— 表头含多个 IRF 列时，按「样品列,紧随其后的 IRF 列」配对；
     非严格交替的表头自动退回「最近的 IRF 列」规则。

> 必须有 IRF 列（或另存一个含 IRF 的文件拼成三列），否则无法做重卷积拟合。

## 安装依赖

```bash
pip install numpy scipy pandas matplotlib
```

## 快速开始

### 1. 命令行一键拟合

```bash
python plot_lifetime.py -i "D:/北大/QLS Lab/SPC/ESIPT/谱图/吸收&荧光/20260724lifetime/20260724/esipt-1/Decay2.csv" -o ./plots/lifetime
```

常用参数：
- `-m SESM`：改用平滑指数序列法（更快、更稳，分辨率略低）
- `--n_rates 201`：速率网格点数
- `--tol 1e-2`：收敛容限
- `--show`：弹出图窗
- `-q`：静默模式

输出（保存到 `-o` 目录）：
- `{文件名}_decay.png`：衰减曲线 + 平移后 IRF + 拟合曲线（log 轴）+ 残差 + χ²ᴿ
- `{文件名}_peaks.png`：寿命分布 + 各高斯分量（标注 τ 与占比 α）
- `{文件名}_fit_result.json`：完整拟合结果（含全部数组与元数据）

### 2. Python 一键批量

```python
import plot_lifetime

results = plot_lifetime.fit_lifetime(
    files="D:/.../20260724/esipt-*/Decay*.csv",  # 支持通配符或列表
    save_dir="./plots/lifetime",
    method="MEM",        # 或 "SESM"
    show=False,
)
for r in results:
    print(r['name'], 'chi2_R =', r['info']['chi_sqr'])
    for tau, area, fwhm, weight in r['peak_result']:
        print(f"  tau = {tau:.3f} ns, 占比 = {area*100:.1f}%")
```

### 3. 分步使用（需要精细控制时）

```python
import plot_lifetime

fitter = plot_lifetime.MEMFitter(verbose=True)
fitter.from_file("Decay2.csv")          # 或 fitter.load(time, decay, irf)
fitter.preprocess()                     # 预处理 + tail-fitting
fitter.fit(method="MEM",                # "MEM" / "SESM"
           n_rates=201,                 # 速率网格点数
           k_min=0.01, k_max=100.0,     # 速率范围 (1/ns)，即 tau 100~0.01 ns
           res_tol=1e-2,                # 收敛容限
           lambda_coeff=1e-3,           # 熵项权重（MEM）
           max_runs=10,                 # 交替优化轮数上限
           n_starts=5, seed=0)          # 粗估多起点
fitter.postprocess()                    # 高斯分解寿命分量
result = fitter.serialize("out.json")   # 返回 dict 并保存
plot_lifetime.plot_result(result, save_dir="./plots", show=False)
```

## 导出拟合结果（汇总表 + 报告）

把一批拟合结果整理成可直接进 Excel / 论文的表格，以及每个文件的详细报告。

### 命令行（拟合时顺带导出）

```bash
python plot_lifetime.py -i "D:/.../20260724/esipt-*/Decay*.csv" -o ./plots/lifetime --export
```

`--export` 会在拟合完成后额外写出：

- `lifetime_fit_results_summary.csv`：汇总表，每行一个文件，列含
  文件名 / 方法 / 拟合区间起止(ns) / χ²R / qshift(ch,ns) / IRF_FWHM(ns) / 分量数，
  以及各寿命分量 `τ_i(ns)` 与 `占比_i(%)`
- `lifetime_fit_results_summary.xlsx`：同上表的 Excel 版（需 openpyxl）
- `lifetime_fit_results_<文件名>_report.md`：每个文件的 Markdown 报告（方法、χ²R、
  qshift、IRF FWHM、拟合区间、各寿命分量 τ / 强度占比）

### Python 调用

```python
import plot_lifetime

results = plot_lifetime.fit_lifetime("D:/.../Decay*.csv", save_dir="./plots")
written = plot_lifetime.export_fit_results(
    results, save_dir="./plots", name="lifetime_fit_results")
# written 为写出的文件路径列表
```

`export_fit_results(results, save_dir, name=...)` 接受 `serialize()` 返回的 dict 列表
（来自 `fit_lifetime` 或 GUI 拟合缓存），返回实际写出的文件路径。
可用 `write_csv / write_xlsx / write_report` 三个开关分别控制三类输出。

> GUI 中无需命令行：寿命模式下操作栏的「💾 导出当前拟合结果」与
> 「📊 导出全部勾选拟合结果」即调用上述同一套逻辑。

## 结果解读

- **χ²ᴿ ≈ 1**：拟合质量良好（>2 说明模型/拟合区间有问题，可检查 IRF 与 decay
  是否来自同一次测量）
- **qshift**：IRF 相对衰减曲线的平移量（channels，乘以时间步长换算为 ns），
  主迭代中会自动精修
- **peak_result**：每个元素为 `[tau (ns), 面积占比, FWHM(k空间), 权重]`，
  按中心速率从大到小（即 τ 从小到大无关）排序，面积占比即振幅分数 α
- **寿命分布**：分布宽度大说明该分量有连续分布（非单指数）；FWHM 小说明接近单指数

## 拟合质量与不确定度（v4.21 新增）

`fit()` 结束后 `info` 里多了一批**自检字段**，GUI 的「信息」页与「拟合诊断」页会直接显示：

| 字段 | 含义 |
| --- | --- |
| `chi_sqr` | χ²ᴿ = Σ(y−d)²/d / **M**（Neyman 口径，分母是观测计数，除数是点数 M 而非自由度 ν） |
| `chi_sqr_pearson` | 同一数据的 Pearson 口径 χ²ᴿ = Σ(d−y)²/y / M，便于与文献对照 |
| `chi2_type` | 固定为 `neyman_obs_denominator_over_M`，避免口径被误读 |
| `quality` / `quality_notes` | `ok` / `poor` / `failed` + 具体原因（优化器未收敛、χ²R 过大、IRF 位移不可辨识、每分量数据点太少…） |
| `solver_converged` / `solver_last_status` / `solver_last_nit` | 最后几轮 SLSQP 是否真的收敛（**状态 0 不等于解是对的**，详见下方说明） |
| `iter_converged` | 主迭代是否达到 `res_tol` 判据 |
| `intensity_share_grid_edges` | 落在速率网格两端（最快/最慢 2% 网格）的发光强度占比，>5% 会告警——**边界堆积**提示 |
| `intensity_share_fastest_decade` / `..._slowest_decade` | 最快/最慢一个数量级内的强度占比 |
| `intensity_share_unassigned` | 距任何分量中心都超过 0.5 dex 的强度占比（"谁都不像"的质量） |
| `peaks_found` / `peaks_dropped` / `peaks_dropped_low_share` | 找到的分量数、被 `max_peaks` 截断的数量、因强度占比 <0.5% 被丢弃的噪声分量数 |
| `fit_kwargs` | 本次拟合的完整参数（供 `bootstrap_ci()` 复现） |

### 收敛性：为什么现在会明确告警

v4.21 之前粗估用多起点 SLSQP 直接优化 201 维分布。实测在**合成真值数据**
（τ=2.5/8.0 ns 双指数 + 泊松噪声）上，SLSQP 会停在"报告成功（status=0）但
χ²R≈134"的点，而同一基函数的 NNLS 精确解 χ²R≈0.91——也就是说**优化器会静默
给出错误结论**。现在：

1. 粗估与每轮迭代都用 **NNLS 精确解**做起点（`scipy.optimize.nnls`），保证不会比它差；
2. `_chi2` / 熵项提供**解析梯度**，不再让 SLSQP 对 201 维做有限差分；
3. 每轮记录 `res.success/status/nit`，未收敛就写进 `quality_notes` 并在日志里告警。

因此 `quality='poor'` 时请先看 `quality_notes`，不要直接引用 τ/占比。

### 不确定度：残差 bootstrap

```python
fitter.fit(method="MEM", n_rates=201)
fitter.postprocess()
ci = fitter.bootstrap_ci(n_boot=20, seed=0, ci=0.95)
for c in ci['components']:
    print(c['tau'], c['tau_lo'], c['tau_hi'], c['alpha'], c['alpha_lo'], c['alpha_hi'],
          c['hit_rate'], c['unstable'])
```

做法：以当前拟合为"真值模型"，从残差池有放回重采样、生成 n_boot 组伪数据，
用**完全相同的参数**各自重新拟合，统计 τ / α 的 2.5%–97.5% 分位。

- `hit_rate`：该分量在多少次重采样里被找到。**命中率 < 50% 会被标为 `unstable=True`**，
  说明这个分量本身时有时无，它的区间不可信；
- `ci_inconsistent=True`：区间不覆盖点估计（常见于相邻一强一弱的分量互相挤压），
  此时区间不能当误差棒；
- 代价 ≈ `n_boot × 单次拟合耗时`（auto λ 时单次 1–2 分钟，请谨慎设大）。

### 输入校验（v4.21 起明确报错）

以下情况不再"静默给结果"，而是抛 `ValueError`：

- 时间/衰减/IRF 长度不一致；含 NaN/Inf；时间轴非严格递增；IRF 全为 0
- 衰减峰值不超过本底（没有可拟合的信号）
- `n_rates < 3`、`k_min ≥ k_max`、未知方法名
- 拟合窗口点数少于自由分量数（欠定）
- 速率分布出现 NaN/Inf（优化器未收敛）

另外：`k_min`/`k_max` 可调范围不变，但**分量个数与寿命不再随 `n_rates` 漂移**
（判峰改为相对峰高 2% + log-k 空间 0.08 dex 间距；旧实现用绝对阈值 + 点数距离，
同一份数据在 101/201/401 点下会给出 2/3/4 个分量）。

### 归一化数据自动还原（v4.32 新增）

**症状**：拿一份"峰值 = 1"的数据拟合，报
`拟合点数不足：拟合窗口 50 点，自由分量 N 个`，且把 `n_rates` 调小也只是勉强能跑、
给出的寿命明显不合理（例如 τ 顶到网格上界 100 ns）。

**原因**：拟合窗口的噪声判据是

```python
noise_level = max(decay_max / 500, 10, 1.5 * 本底)
```

其中 **`10`** 这个绝对下限是针对**原始光子计数**写的（真实 TCSPC 数据峰值 10³~10⁵、
本底几十，该下限基本不生效）。而作业/交换数据常被归一化成峰值 = 1 的**相对强度**，
此时全部通道都 `< 10` → "低于噪声水平"的第一段从衰减峰位就开始 → 窗口退化成
`[IRF峰, 衰减峰)` 的上升沿、被夹到 50 点下限 → 欠定报错。**与数据质量无关。**

**现在**：`preprocess()` 会先检测并还原：

- 判据：衰减峰值 < **10**（`_NORMALIZED_PEAK_MAX`）视为归一化；
  真实计数数据峰值远高于此（工作区实测最低 3×10³），不会误伤。
- 还原：decay 与 IRF 乘**同一个**因子，使峰值 → **10⁴**（`_RESCALE_TARGET_PEAK`），
  保持两者相对比例（IRF 基线扣除依赖该比例），再据此定噪声水平与拟合窗口。
- 记录：`info['rescaled_from_normalized']` / `rescale_factor` /
  `decay_peak_before_rescale`，GUI 信息页会显示一行提示，**不是静默换算**。

**精度说明**：还原恢复的是"噪声判据的物理量级"，**不是与计数刻度逐位复现**——
绝对下限 `10` 在两种刻度下的相对强度不同，窗口端点会差几个通道。实测同一份数据
（`esipt-1/Decay2.csv`）两种输入的主寿命差 **0.07%**（6.1053 vs 6.1007 ns），
而不还原时窗口退化成 50 点、τ 偏到 200 ns（偏差 3176%）。

所以：**能拿到原始计数就用原始计数**；只有归一化数据在手时，这层还原保证结果可用。

### 拟合窗口被下限托底时的诊断（v4.32 新增）

若窗口仍被 50 点下限托底（还原后仍发生，或还原被显式关掉），报错不再只提示
"把 n_rates 调小"，而是给出诊断量：

```
本次拟合窗口是被 50 点下限托底的（噪声判据在衰减峰附近即触发），
依据：噪声水平 = …, 衰减峰值 = …, 本底 = …；
请依次检查：
  1) 衰减列是否为计数（峰值过低/被归一化会导致判据失效）；
  2) IRF 是否与衰减同窗、且有明显上升沿；
  3) 数据是否需要先去背景/去尖峰。
```

`info['window_floored']` / `info['fit_end_raw']` / `info['noise_level']` 可程序化读取。

### 进度与取消（GUI / 脚本）

```python
fitter.fit(method="MEM", auto_lambda=True,
           progress_cb=lambda frac, msg: print(f"{frac:.0%} {msg}"),
           cancel_cb=lambda: False)      # 返回 True 时抛 plot_lifetime.FitCancelled
```

GUI 的寿命拟合会弹出进度框（含「取消」按钮），取消后保留上一次已画出的结果。

## 实测示例

对 `esipt-1/Decay2.csv`（4096 点，IRF FWHM ≈ 0.098 ns）：

```
chi2_R = 0.9994
tau_1 = 0.886 ns, 占比 44.1%
tau_2 = 6.23  ns, 占比 55.9%
```

## 全局拟合（v4.22 新增）

### 1. 共享速率分布：`fit_global()`

同一样品的多次测量 / 多检测窗：所有数据集共享同一份速率分布 `p`，
各自只有幅度 `s_d`（`y_d = (A_d @ p)·decay_max_d·s_d + bg_d`）。

```python
import plot_lifetime as pl
res = pl.fit_global(datasets, method='MEM', n_rates=201)
print(res['tau_list'], res['chi2R_total'])
for e in res['per_dataset']:
    print(e['name'], e['chi2R'], e['scale'], e['alpha'])
```

### 2. 共享寿命 τ、各样品独立幅度：`fit_global_discrete()`

滴定 / 系列样品（FRET A0→A24）用这个：共享 `n_comp` 个寿命，
每个样品解自己的幅度（NNLS），τ 用 Nelder-Mead 优化。

```python
res = pl.fit_global_discrete(datasets, n_comp=3)
print(res['taus'])                      # 共享寿命
for e in res['per_dataset']:
    print(e['name'], e['chi2R'], e['alpha'])   # 各样品占比 → 可做滴定曲线
```

实测 7 份 FRET 数据（n_comp=3）：共享 τ = 0.735/2.018/3.521 ns，Σχ²R = 17.8。

## 跨样品汇总图与 PDF 报告（v4.22 新增）

```python
pl.plot_summary(results, save_dir='./plots', xlabel='受体浓度')  # τ/α/χ²R 三联图
pl.export_report_pdf(results, save_dir='./plots')                # 多页 PDF 报告
```

GUI 寿命模式下对应两个按钮：**「📈 跨样品汇总图」**、**「📄 导出 PDF 报告」**
（会自动并行拟合当前文件夹全部文件）。

## 注意事项

- 计数率过低（峰计数 < ~1000）时 χ² 加权统计意义变差，结果仅供参考
- 粗估阶段剔除了 τ > 100 ns 与 τ < 0.1 ns 的分量；若体系寿命在范围外，
  请调整 `k_min` / `k_max`
- v4.21 起粗估用 NNLS 精确解热启动，MEM 单文件通常 **数秒到十几秒**
  （n_rates=201 实测约 7.6 s；auto λ 仍需 1–2 分钟，因为要扫 9 个 λ）；
  `SESM` 的平滑权重现在真正受 `lambda_coeff` 控制（旧实现写死 1e-1，调 λ 无反应）
- 若只需快速估算可先看预处理输出的 qshift 与 FWHM 是否合理（IRF 明显晚于
  decay 起峰说明数据有问题）
- 报告里的占比之和恒为 100%：它是**在检测到的分量之间**归一的，
  请同时看 `intensity_share_unassigned` 与 `intensity_share_grid_edges`
  判断有没有"没被分量覆盖"的质量
