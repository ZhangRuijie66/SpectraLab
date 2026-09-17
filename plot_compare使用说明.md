# plot_compare 使用说明

**光谱「强度-变量」相关性点线图**（v4.37 新增）

把一批同类型光谱（吸收或发射）各自压成**一个纵轴读数**，再按 `说明.xlsx` 里
某个变量的值散点连线——回答"强度/面积随浓度怎么变"这类问题。

---

## 1. 它需要什么数据

| 输入 | 说明 |
| --- | --- |
| 光谱文件 | 同一文件夹下的 CSV / TXT（吸收或发射），一个文件夹一批 |
| `说明.xlsx` | 同文件夹；首行列名，含 `编号` 列 + 若干信息列（如 `RB浓度 / L8i浓度 / 备注`） |
| 编号匹配 | 文件名里的数字要和 `编号` 列对得上（`RB-L8i-3.csv → 编号 3`），规则同 GUI 图例增强 |

`说明.xlsx` 里**空单元格、`null`、`N/A`、`-`、`—` 等一律视为"没有值"**：
该样品不进入图（不会出现 `nan` 点、也不补 0），并在返回值 `skipped` 里给出原因。
数值 `0` 是有效值。

---

## 2. 纵轴三种口径

| `metric` | 界面文字 | 含义 |
| --- | --- | --- |
| `peak_intensity` | 峰强度 | `band` 区间内的最大强度；不给区间 = 全谱最大 |
| `peak_area` | 峰面积 | `band` 区间的梯形积分（与 GUI「光谱积分」**同一实现**） |
| `at_wavelength` | 指定波长处的值 | `at_wl` 处线性插值；落在数据范围外返回 NaN（**不外推**） |

横轴是 `说明.xlsx` 的某个**数值列**；再给 `group_var` 就按它分组，每组一条点线。

---

## 3. 命令行用法

```bash
# 先看有哪些数值列可以当横轴 / 分组
python plot_compare.py "D:\data\20260825" --list-vars

# 峰强度 vs RB浓度，按 L8i浓度 分组（区间 560–620 nm）
python plot_compare.py "D:\data\20260825" --x RB浓度 --group L8i浓度 \
    --metric peak_intensity --band 560 620

# 峰面积（等价于 GUI 里复用积分区间）
python plot_compare.py "D:\data\20260825" --x RB浓度 --metric peak_area --band 560 620

# 指定波长处的强度
python plot_compare.py "D:\data\20260825" --x RB浓度 --metric at_wavelength --at 600

# 吸收数据
python plot_compare.py "D:\data\uvvis" --x 浓度 --kind absorption \
    --metric peak_intensity --band 400 600 --save-dir ./plots
```

输出：`./plots/compare_<变量>_<指标>.png` 与同名 `.csv`
（CSV 列：`样品, 编号, 横轴变量, 分组, 指标值`，UTF-8 BOM，Excel 直接打开不乱码）。

参数速查：`--x`（横轴变量，缺省用第一个数值列）、`--group`（分组变量）、
`--metric`、`--band LO HI`、`--at`、`--kind emission|absorption`、`--save-dir`、
`--list-vars`（只列数值列）。

---

## 4. 在 Python 里调用

```python
import plot_compare as pc
from read_xlsx_info import load_xlsx_info, match_number

info = load_xlsx_info(r'D:\data\20260825')
samples = []                      # (显示名, 匹配编号用的文件名, wl, y)
for name, wl, y in my_spectra:    # 曲线已是"最终要测的那条"（例如已扣本底）
    samples.append((name, name + '.csv', wl, y))

res = pc.collect_points(samples, info, x_var='RB浓度', group_var='L8i浓度',
                        metric='peak_intensity', band=(560, 620))
print(res['points'])      # [(分组, x, 指标值, 样品名, 编号), ...]
print(res['skipped'])     # [(样品名, 跳过原因), ...] —— 空值样品在这里

fig, summary = pc.make_compare_figure(res['points'], 'RB浓度', '峰强度 (560–620 nm)',
                                      '峰强度 - RB浓度（按 L8i浓度 分组）',
                                      legend_prefix='L8i浓度')
pc.save_figure(fig, './plots/compare.png')
```

其它可复用函数：`measure_metric(wl, y, metric, band, at_wl)`（单条曲线一个读数）、
`integrate_band(wl, y, lo, hi)`（梯形积分，GUI 的积分结果表也调它）、
`describe_metric(...)`、`group_points(points)`、`points_to_csv(...)`。

---

## 5. GUI 里怎么用

吸收 / 发射模式的参数栏「**数据比较（说明.xlsx）**」组：

1. 选**横轴变量**（没有说明.xlsx 或没有数值列时按钮置灰，悬停看原因）；
2. 可选**分组变量**；
3. 选**纵轴指标**并按需填「峰强区间」/「指定波长」（无关的输入框会自动禁用）；
4. 在左侧「数据」栏勾选要参与比较的样品（**只统计勾选项**）；
5. 点「**数据比较**」→ 自动切到「数据比较」标签页；「⤓ CSV」导出取点结果。

跳过的样品（缺变量值 / 匹配不到编号 / 指标算不出）看两处：状态栏的条数提示，
以及把鼠标停在「数据比较」画布上的悬停明细。
「导出全部图片」会连这张点线图一起导出。

---

## 6. 依赖与打包

只用到 `numpy / pandas / matplotlib`（另加同目录的 `read_xlsx_info`、`curve_colors`）。
GUI 打包脚本需要 `--hidden-import plot_compare`（`打包便携版.ps1` 与
`build_mac.command` 均已加入，`检查版本一致性.py` 会校验）。
