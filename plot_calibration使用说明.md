# plot_calibration 使用说明

**线性标定 + 检出限/定量限（LOD/LOQ）+ Stern–Volmer 分析**

`plot_compare` 能把一批光谱各自压成一个读数、画成点线图，但**止步于点线图**——
没有回归、没有 R²、没有 LOD。而标定实验的产出物恰恰是
「斜率 / 截距 / R² / 检出限 / 线性范围」。本模块补上这一段。

> **⚠️ 本版本未经执行验证。** 交付时整个会话的命令执行器失效
> （`ops_bash` 返回 `EXECUTOR_UNAVAILABLE`），因此下文所有具体数值都写成
> `<待实测>`，**没有任何一个是猜的**。等执行器恢复后按第 8 节的命令补跑，
> 把真实数字回填。

---

## 1. 它需要什么数据

| 输入 | 说明 |
| --- | --- |
| 光谱文件 | 同一文件夹下的 CSV / TXT（发射或吸收），一个文件夹一批 |
| `说明.xlsx` | 同文件夹；首行列名，含 `编号` 列 + 若干信息列（如 `RB浓度 / Ce6浓度 / L8i浓度`） |
| 编号匹配 | 文件名里的编号要和 `编号` 列对得上（规则同 `plot_compare` / GUI 图例增强） |

`说明.xlsx` 里**空单元格、`null`、`N/A`、`-`** 一律视为"没有值"：该样品不进入
标定，并在返回值里给出原因。数值 `0` 是有效值。

---

## 2. 三条最容易被写错的统计口径

写实验报告时直接照这三条核对，别凭印象：

| 量 | 正确公式 | 常见错误写法 |
| --- | --- | --- |
| 回归标准误 | `s_yx = sqrt(RSS/(n−2))` | `sqrt(RSS/n)`（少扣自由度，LOD 偏小） |
| 斜率标准误 | `SE(b) = s_yx / sqrt(Σ(x−x̄)²)` | `s_yx/sqrt(n)`（**错**，与 x 的分散度无关了） |
| 截距标准误 | `SE(a) = s_yx·sqrt(1/n + x̄²/Σ(x−x̄)²)` | `s_yx/sqrt(n)` |
| 检出限 | `LOD = 3·s_yx/|b|` | 用 `s_yx/sqrt(n)` 当 s（偏小 √n 倍） |

**单位提醒**：`LOD` / `LOQ` 的单位是 **x 的单位**（浓度），不是强度。
写成「LOD = 1.2 a.u.」是把响应值单位错安到浓度上了。

本模块的两个 s 分开给，别混：

- `s_yx` = `sqrt(RSS/(n−2))` —— 自由度修正过，**LOD 公式用的就是它**；
- `rmse` = `sqrt(RSS/n)` —— 未修正，某些软件报的"RMSE"是这一个。

**另外**：`lod_loq` 还会用**重复测量的纯误差**另估一个空白标准差 `s0`
（`blank_sd`），并给出 `lod_from_blank`。理论上 IUPAC 的 `s0` 指的是空白测量的
标准差，比 `s_yx` 更贴近定义（`s_yx` 混进了弯曲等模型误差）。两个都给出来，
报告里说明用了哪个。

---

## 3. 边界情况的行为（都有明确结果，不会静默返回 nan）

| 情形 | 行为 |
| --- | --- |
| 有效点 < 2 | 抛 `CalibrationError`，消息含实际点数与丢弃点数 |
| **只有 2 个点** | **降级**：`s_yx` / `SE` / 置信区间 / `LOD` / `LOQ` 全部返回 `None`，`status='degraded'`，`warnings` 写明"自由度 n−2=0"。**不返回 0 也不返回 nan** |
| **所有 x 相同** | 抛 `CalibrationError`：`Σ(x−x̄)²=0`，斜率无定义；消息列出重复的那个 x |
| **y 全部相同** | **降级**：斜率 = 0、`r2` 返回 `None`、`LOD` 无定义；`warnings` 说明"响应值没有随浓度变化" |
| **含 NaN / inf** | 默认**丢弃并记录**：`n_dropped` 是丢了几点，`dropped_index` 是丢在哪几个位置；剩下的点 < 2 才报错。传 `nan_policy='raise'` 可改成直接报错 |
| 斜率为 0 | `lod_loq` 的 `lod` / `loq` 返回 `None` 并写明"除以 0，无法定义检出限" |
| LOD > 最低标准点 | 仍返回 LOD，但 `warnings` 提示"真实检出限落在标准曲线覆盖范围之外，不能直接引用这个号码" |

---

## 4. 命令行用法

```bash
# 先看说明.xlsx 里有哪些数值列可当横轴
python plot_calibration.py "D:\data\05" --list-vars

# RB 系列标定（峰强度带 555–620 nm）
python plot_calibration.py "D:\data\05" --x RB浓度 --band 555 620 --name RB

# Ce6 系列标定
python plot_calibration.py "D:\data\05" --x Ce6浓度 --band 655 685 --name Ce6

# 峰面积口径 + 指定 DPI
python plot_calibration.py "D:\data\05" --x RB浓度 --metric peak_area --band 555 620 --dpi 300

# 合成真值自检（不需要数据，直接跑）
python plot_calibration.py --demo
```

**不给 `--band` 时会按谱峰自动定带**，并打印选了哪一段。这个区间直接决定读数，
报告里必须写明。若数据里混着两组峰（实测 `05` 数据：RB 系列峰在 570 nm、
Ce6 系列在 665 nm），自动定带会落在占比最大的那簇上——**请显式给 `--band`**。

输出（全部在 `--save-dir`，默认 `./plots`）：

| 文件 | 内容 |
| --- | --- |
| `calibration_<变量>_<指标>.png` | 标定图 + 残差图 |
| `calibration_<变量>_<指标>_points.csv` | 逐点数据 + 是否参与回归 + 剔除原因 + 逐浓度汇总 |
| `calibration_<变量>_<指标>_fit.csv` | 统计量竖排表（slope/SE/R²/LOD/LOQ/线性范围…） |
| `calibration_<变量>_<指标>.json` | 结构化结果 + `meta`（导出时间、参数快照） |

CSV 全部 `utf-8-sig`，Excel 直接打开中文不乱码。
默认 DPI 取自 `export_defaults.EXPORT_DPI_DEFAULT`（与 GUI 及其它 `plot_*.py` 同一真源）。

参数速查：`--x`、`--metric`、`--band LO HI`、`--at`、`--kind`、`--name`、`--dpi`、
`--outlier-sigma`、`--drop-outliers`、`--no-comparability`、`--list-vars`、`--demo`、`--json`。

---

## 5. 在 Python 里调用

### 5.1 一键（从文件夹）

```python
from plot_calibration import calibrate_from_folder

out = calibrate_from_folder(
    folder=r'D:\data\05',
    x_var='RB浓度',
    metric='peak_intensity',
    band=(555, 620),
    save_dir=r'./plots',
)
print(out['slope'], out['r2'], out['lod'], out['loq'])
print(out['report_text'])          # 排好版的中文报告，可直接贴进实验报告
print(out['exclude_reasons'])      # 被排除 / 需留意的样品及原因
```

### 5.2 只要数字（自己已有 x / y）

```python
import numpy as np
from plot_calibration import linear_calibration, lod_loq, format_calibration_report

x = np.array([...]); y = np.array([...])     # 逐点，含重复测量，不要先平均
cal = linear_calibration(x, y)
lod = lod_loq(x, y, calibrate=cal)
print(format_calibration_report(cal, lod, x_name='c / μmol·L⁻¹', y_name='峰强度'))
```

### 5.3 Stern–Volmer（含模型比较）

```python
from plot_calibration import stern_volmer, plot_stern_volmer

sv = stern_volmer(q, i0_over_i)                 # 一阶 + 二阶都拟合
print(sv['ksv'], sv['k1'], sv['k2'])
print(sv['comparison']['verdict'])              # 中文结论：哪个模型更合适、为什么
plot_stern_volmer(sv, save_path='./plots/sv.png')

# 也可以直接给原始强度和 I0
sv = stern_volmer(q, intensity, i0=I_0)
```

`comparison` 里同时给 **F 检验**（嵌套模型，`p` 值）与 **AICc**（`delta_aicc`，
二阶减一阶，< −2 倾向二阶、> +2 倾向一阶），以及两者不一致时的说明。
**只报一个模型的 R² 是判断不了"哪个更合适"的**——这正是本模块把两个模型
一起拟合、并给出判据的原因。

### 5.4 失拟检验（R² 高不等于直线够用）

```python
from plot_calibration import lack_of_fit_test
lof = lack_of_fit_test(x, y)      # 需要同一浓度有重复测量
print(lof['f'], lof['p'], lof['verdict'])
```

R² 只说明"直线解释了大部分方差"，说明不了"剩下的偏离是不是还有系统弯曲"。
失拟检验用重复测量的纯误差当标尺去比，`p < 0.05` 就是**直线不够**。

---

## 6. 关于可比性预检（很重要）

`calibrate_from_folder` 默认先跑 `plot_compare.check_comparability`（需 v5.0.6+）。
同一编号下的多个文件如果**激发波长不同 / 带宽不同 / 扫描被截断**，它们不是
平行样，拿去回归会把斜率与 LOD 一起算歪。

本模块的处理规则：

| 问题级别 | 处理 |
| --- | --- |
| `error` 级（激发波长/带宽不一致、扫描截断） | **直接排除**在回归之外，原因写进 `exclude_reasons` |
| `error: peak_shift`（谱形不一致） | **不**一票否决 —— 改由读数质检判断（波段已限定时，谱形差异可能只是散射峰位置不同，波段内的峰仍可用） |
| `warn` 级（峰强可能取到散射/拉曼峰） | 不排除，但写进 `exclude_reasons` 提醒 |

另外做一道**读数质检**：`peak_intensity` 且给了 `band` 时，检查带内最大值是否
贴着区间边缘（距边缘 < max(2 nm, 4% 带宽)）。贴着说明读数可能取到了散射/拉曼带
而不是荧光峰——这种点**只提示、不剔除**（区间是人定的，判据在人手里）。

要关掉预检（你确信所有文件条件一致时）：`comparability=False` 或 `--no-comparability`。

---

## 7. 图表怎么看

生成的是**上下两栏**：

- **上栏（标定图）**：数据点 + 拟合线 + 两层带 + LOD/LOQ 竖线。
  - **深蓝窄带 = 95% 置信带**：回答"这条拟合线本身多准"；
  - **浅蓝宽带 = 95% 预测带**：回答"再测一个点会落在哪"。
    两件事，所以都画。报告里说"浓度不确定度"用的是预测带。
  - 有重复测量时画"均值 ± 标准差"误差棒，原始点淡色叠在同位置（不丢信息）。
  - 被剔除的点画成**灰色空心叉**——图上看得到扔了什么，不是偷偷丢掉。
  - 标准化残差超过 `outlier_sigma` 的点加**红圈**（只提示，除非开 `--drop-outliers`）。
- **下栏（残差图）**：绿带是 ±2 `s_yx`。**残差该是随机散布**；
  出现明显趋势（U 形、上翘）说明直线不够，去看失拟检验的结论。

Stern–Volmer 图同理：上栏画一阶实线与二阶虚线（标出判据倾向哪个），
下栏把两个模型的残差并排画——残差里还剩趋势，就说明那个模型没抓全。

---

## 8. 执行器恢复后必须补跑的验证清单

> 交付时命令执行器不可用，**以下全部未运行**。请按顺序补跑并把结果回填到
> `F_plot_calibration实现报告.md` 的「待验证」区。

```bash
cd "D:\北大\光谱工具"

# ① 语法
"C:\Python311\python.exe" -m py_compile plot_calibration.py

# ② 合成真值自检（含四种边界情况；不需要数据）
"C:\Python311\python.exe" plot_calibration.py --demo --save-dir "C:\Users\zhang\AppData\Local\Temp\spectra_improve\F\demo"

# ③ RB 系列真实标定
"C:\Python311\python.exe" plot_calibration.py "示例数据\05-数据比较-浓度梯度" ^
    --x RB浓度 --band 555 620 --name RB --save-dir "C:\Users\zhang\AppData\Local\Temp\spectra_improve\F\RB"

# ④ Ce6 系列真实标定
"C:\Python311\python.exe" plot_calibration.py "示例数据\05-数据比较-浓度梯度" ^
    --x Ce6浓度 --band 655 685 --name Ce6 --save-dir "C:\Users\zhang\AppData\Local\Temp\spectra_improve\F\Ce6"

# ⑤ 看可比性预检排除了哪些文件
"C:\Python311\python.exe" plot_calibration.py "示例数据\05-数据比较-浓度梯度" --x RB浓度 --list-vars
```

<待实测> 需要回填的数字：

| 项 | RB 系列 | Ce6 系列 |
| --- | --- | --- |
| 参与回归的点数 / 剔除数 | <待实测> | <待实测> |
| 斜率 b ± SE | <待实测> | <待实测> |
| 截距 a ± SE | <待实测> | <待实测> |
| R² / 校正 R² | <待实测> | <待实测> |
| `s_yx` | <待实测> | <待实测> |
| LOD / LOQ | <待实测> | <待实测> |
| 线性范围 | <待实测> | <待实测> |
| 失拟检验 F / p | <待实测> | <待实测> |

合成真值：

| 项 | 期望（真值已知） | 实测 |
| --- | --- | --- |
| 线性还原 b（真值 250） | 偏差应 < 2% | <待实测> |
| 线性还原 a（真值 1500） | 偏差应 < 5% | <待实测> |
| `s_yx` / 真值 σ=400 | 应 ≈ 1 | <待实测> |
| LOD vs `3σ/\|b\|` | 应接近 | <待实测> |
| Ksv 还原（真值 0.032） | 偏差应 < 3% | <待实测> |
| 混合猝灭 K2 还原（真值 0.0006） | 同量级 | <待实测> |
| 模型比较是否选对二阶 | 应选二阶 | <待实测> |

边界情况（期望值已在第 3 节写死，只需核对实际输出是否一致）：

| 情形 | 期望 | 实测 |
| --- | --- | --- |
| 只有 2 点 | `status='degraded'`，`s_yx`/`SE`/`LOD` 为 `None`，不报错 | <待实测> |
| x 全相同 | 抛 `CalibrationError` | <待实测> |
| y 全相同 | `r2=None`，`lod=None`，斜率 0 | <待实测> |
| 含 NaN | `n_dropped=2`，`dropped_index=[1, 2]` | <待实测> |

PNG 目检（`read_image` 打开）：中文字体无方框、标注框不压数据、
LOD/LOQ 竖线与图例不打架、残差图坐标轴标签不被裁。
输出路径：`...\spectra_improve\F\RB\calibration_RB浓度_peak_intensity.png` 等。

---

## 9. 建议的 GUI 接入方式

本模块**没有**接进 GUI（按任务分工，由 Lead 统一接）。若要做，建议：

1. `gui_config.py` 或新建 `gui_calibration.py` 里放参数：横轴变量下拉框
   （复用 `plot_compare.numeric_columns`）、纵轴口径、峰强区间、LOD 的 k 值。
2. `gui_plot.py` 里加 `_do_calibration_plot()`，在 `PlotWorker` 后台线程里调
   `calibrate_from_folder(..., save_dir=临时目录)` —— 计算全部在后台，
   UI 线程只读控件值。
3. 画布：主画布放标定图，第二个 `MplCanvas` 标签页放残差图
   （注意 `MplCanvas` 初始边距是 0，切页后要补 `subplots_adjust`）。
4. 结果摘要写 `info_label`：`b ± SE`、`R²`、`LOD`、`LOQ`、剔除了几个样品。
5. 导出：加 `_export_calibration_plots(save_dir)`，把 PNG + `_fit.csv` + `.json` 一起导出。
   注意 JSON 里的 `meta.params` 已经记录了参数快照，直接沿用。

---

## 10. 依赖与打包

只用到 `numpy` / `scipy` / `matplotlib`（另加同目录 `read_xlsx_info`、`plot_compare`、
`plot_emission` / `plot_absorption`、`export_defaults`）。
**没有引入任何新依赖**（不碰 torch / rich）。

GUI 打包脚本需加 `--hidden-import plot_calibration`（若接进 GUI）。
根目录脚本可脱离 GUI 单独运行。

---

## 11. 已知限制

1. **本版本未经执行验证**（见文首）。所有公式是人工核对的，但没有一个数字是跑出来的。
2. `_trim_linear_range`（线性范围收缩）的判据是"两端层级的标准化残差 > 3σ 就剔一层"，
   每剔一层重拟合一次。**这是个自我加强的循环**：剔一层 → `s_yx` 变小 → 下一轮判据
   更严。浓度层级只有 5–6 个时可能连着剔掉 2 层，把"两端略有弯曲"的数据收缩成很窄的
   区间。**当浓度层级 < 6 时请人工核对 `linear_range`**，不要直接按它写
   "本方法线性范围为 x–y"。保守做法：把 `sigma` 调大（如 4.0）再看会不会剔，
   或干脆忽略 `linear_range`、用实验设计的浓度区间作线性范围并附失拟检验结论。
3. `auto_band` 用"峰位最大簇"定带，不识别散射峰。数据里混有散射带时它可能
   把带定偏——`05` 数据的 S3/S4 系列就属于这种情况（全谱最大落在 EX+13~15 nm
   的拉曼带上），此时必须显式给 `band`，并且下限要取在荧光区（如 690 nm 之后）。
4. 加权拟合（`weights`）只实现了标准 WLS 口径，没有做"按浓度反比加权"这类
   经验方案的自动选择。
5. Stern–Volmer 的二阶模型是**表观**模型（`1 + K1[Q] + K2[Q]²`），
   不区分静态/动态猝灭的物理来源；要拆开需要变温实验或寿命测量。
