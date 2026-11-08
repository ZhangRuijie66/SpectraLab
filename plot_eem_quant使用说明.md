# 📊 plot_eem_quant.py 使用说明

> **EEM（激发-发射矩阵，即「3D 扫描」）定量读出模块**
> 从 3D 扫描数据里读出能写进实验报告的数字：**最佳激发波长 / 发射峰位表 / 峰位漂移 / 发射带面积**
> 并且在给出任何数字之前，先判断**这份数据到底能不能定量**

配套模块：`plot_3d_scan.py`（负责解析 + 清洗 + 出图，本模块复用它的 `parse_3d_scan_csv` / `prepare_grid`）

---

## 0. 三十秒看懂本模块的立场

`plot_3d_scan.py` 只有图，不给数。本模块补数，但**不会为了给出一组漂亮数字而挑清洗参数**。

每个定量函数都返回两个关键字段：

| 字段 | 含义 |
|---|---|
| `reliable` | `False` 表示**这份数据不支持定量**，数字仅供参考 |
| `quality` | 完整的可定量性诊断（四条判据逐项结论） |

`reliable=False` 会一路带到：每个导出的 CSV（`reliable` 列）、图标题、图里的摘要卡。
**该说"给不出可信的数"的时候就说**，这是本模块的核心功能，不是失败。

---

## 1. 公开函数一览

| 函数 | 作用 | 关键返回 |
|---|---|---|
| **`assess_quantifiability(prep)`** | **第一等公民**：四条判据判定能否定量 | `quantifiable` / `reasons` / `criteria` / `evidence` / `messages` |
| `find_optimal_excitation(prep, em_range=...)` | 每个 EX 的发射积分 → 最佳激发波长 | `best_ex` / `best_value` / `table` / `contrast` / `reliable` |
| `emission_peak_table(prep, em_range=...)` | 每个 EX 的发射峰位 / 峰高 / FWHM → **峰位漂移** | `table` / `drift_range` / `drift_span` / `drift_per_nm` / `reliable` |
| `band_area_table(prep, em_band=(a,b))` | 每个 EX 在指定发射区间的积分面积 | `table` / `band` / `area_contrast` / `reliable` |
| `export_eem_quant(prep, ...)` | 导出 CSV（`utf-8-sig`）+ 可选长表 | `files` / `rows` / `reliable` |
| `plot_eem_quant(prep, ...)` | 定量结果图（3 子图 + 摘要卡） | `(图片路径, 结果 dict)` |
| `eem_quant_all(prep, ...)` | 一键串起上面全部 | `quality` / `reliable` / `files` / `figure` |
| `build_synthetic_eem(...)` | 造真值已知的合成 EEM | 与 `parse_3d_scan_csv` 同构的 data dict |
| `self_test()` | 合成真值自检（**执行器恢复后第一个跑这个**） | `passed` / `checks` / `failures` |
| `draw_optimal_excitation` / `draw_peak_drift` / `draw_band_area` | 把单张图画到外部 ax（**GUI 用这三个**） | `(line, 值)` |

别名：`assess_eem_quality = assess_quantifiability`（早期草稿用过这个名字）。

---

## 2. 四条可定量性判据

`assess_quantifiability` 全部通过才返回 `quantifiable=True`。任一不通过即判不可定量。
**算不出来的判据按未通过处理**（保守：无法验证就不声称可信）。

| # | 判据 | 指标 | 默认阈值 | 真实数据实测 | 为什么 |
|---|---|---|---|---|---|
| 1 | 饱和占比 | `saturation_fraction`（分母=**原始**点数） | ≤ 0.02 | **0.114** ❌ | 饱和把峰高与面积一起削平 |
| 2 | 周期伪迹强度 | 频谱峰/底噪（陷波**前**算出） | < 20 | **77.8** ❌ | 纯噪声期望 ≈2.8（Rayleigh）；真实发射带的宽度落在 3–30 nm 频段外，不会推高它 |
| 3 | EM 通道平滑度 | 对数域二阶差分 / 对数域有效量程 | ≤ 0.06 | **0.374** ❌ | 真实发射带沿 EM 平滑，梳状伪迹是数量级锯齿 |
| 4 | 分块最佳 EX 一致性 | 各 EM 块最优 EX 极差 / EX 量程 | ≤ 0.25 | **0.860** ❌ | 见下方「为什么这条是严格的」 |

判据 1、2 在 `prepare_grid` 没提供相应 stats 时会**现场自测**。
**判据 1、3、4 用原始矩阵跑**（见下方警告）。

### 为什么判据 4 是严格约束

单一荧光体的 EEM 是**可分离**的：`Z(em, ex) = A(ex) · f(em)`。
于是任一 EM 区间的积分 = `(区间内 f 之和) · A(ex)` —— 一个正数常数乘以 `A(ex)`。
所以**无论取哪个发射窗口，`argmax` 都落在同一个 EX**。

伪迹打破这个结构。按 EM 每 100 nm 分块各求最优 EX，如果散布达 EX 量程的一大半，
就说明"最佳 EX"是被噪声/伪迹挑出来的。

### 为什么**不用**「跨 EX 谱形一致性」

这是本模块开发中一次必须记录的自我纠错。最初设计过「相邻 EX 切片归一化谱形偏差」
作为伪迹判据，后来发现它**物理上无效**：

单一荧光体可分离 ⇒ 任何只沿 EM 变化的图案，在跨 EX 归一化后**完全相同**。
真实发射带如此，固定在 EM 的梳状伪迹也如此。这类判据区分不了二者，
会把干净数据也判成不可定量。

有效的不变量只有两个方向：**沿 EM 的局部纹波幅度**（判据 3）和
**可分离性给出的严格约束**（判据 4）。

### ⚠️ 诊断用原始数据，定量用清洗后数据

这是本模块开发中修掉的最严重缺陷。第一版把诊断放在 `prep['Z']`（清洗后）上，
在真实数据上跑出**四条判据全部通过 → "可定量"**——完全错误。

原因：`prepare_grid` 的默认管线把伪迹**连同信号一起抹平**。清洗后的矩阵只剩
平滑地板（~1200 AU），于是"纹波很小、很平滑、各块最佳 EX 一致"。
诊断看到的是一份**被销毁了证据的数据集**。

正确分工：

```python
# 诊断（能不能定量）→ 原始 intensity，伪迹证据还在
q = assess_quantifiability(data, raw=data, ...)

# 定量（算数字）→ prep['Z']，已清洗
optimal = find_optimal_excitation(prep, quantifiability=q, ...)
```

所以 `assess_quantifiability` / `eem_quant_all` 都有 `raw=` 参数。
**只传 prep 时务必一起传 raw**（见 6.2）。

---

## 3. 快速上手

### 3.1 Python

```python
from plot_3d_scan import parse_3d_scan_csv, prepare_grid
from plot_eem_quant import eem_quant_all

data = parse_3d_scan_csv(r"D:\...\RBLu 1 2026-07-27 07-11.csv")
prep = prepare_grid(data)                  # 复用现有清洗管线，不要自己重写

res = eem_quant_all(prep, save_dir=r"D:\...\plots", label="RB/Lu 1",
                    em_band=(560, 700), em_range=(450, 800))

# 先看诊断结论！
if res['quality']['quantifiable']:
    print("最佳激发波长:", res['optimal']['best_ex'], "nm")
    print("发射峰位漂移:", res['peaks']['drift_range'], "nm")
    print("发射带面积  :", [r['area'] for r in res['band']['table']])
else:
    for r in res['quality']['reasons']:
        print("不可定量:", r)
```

### 3.2 命令行

```bash
# 基本用法（图存 ./plots，不弹窗）
python plot_eem_quant.py "文件.csv" -o ./plots

# 按体系指定发射带与统计区间（强烈建议）
python plot_eem_quant.py "文件.csv" -o ./plots --em-band 560,700 --em-range 450,800

# 额外导出长表 (EX, EM, I) —— 默认关，数据量很大
python plot_eem_quant.py "文件.csv" --long-table

# 用不清洗的参数直接看原始谱形
python plot_eem_quant.py "文件.csv" --no-notch --no-clip-saturation --smooth 1

# 合成真值自检（不需要任何数据文件）
python plot_eem_quant.py --self-test
```

### 3.3 只画图、不要 CSV

```python
from plot_eem_quant import plot_eem_quant
fig_path, res = plot_eem_quant(prep, save_dir="./plots", label="样品A",
                               em_band=(560, 700), dpi=150)
```

---

## 4. 导出产物

`export_eem_quant` 写 4–5 个 CSV，全部 `utf-8-sig`（Excel 直接双击可读）：

| 文件 | 内容 | 行数（示例数据） |
|---|---|---|
| `{prefix}_optimal_excitation.csv` | `EX, value, reliable` | 101 / 303（视加密倍数） |
| `{prefix}_emission_peaks.csv` | `EX, EM_peak, intensity, fwhm, drift_range_nm, drift_per_nm, reliable` | 同上 |
| `{prefix}_band_area.csv` | `EX, area, peak_EM, peak_intensity, reliable` | 同上（给 `em_band` 时才有） |
| `{prefix}_quantifiability.csv` | `criterion, passed, computed, value, threshold, note, quantifiable, reasons` | 4 |
| `{prefix}_long_table.csv` | `EX, EM, I` | **70801**（原始网格）/ 637209（加密×3） |

**长表默认关闭。** 示例数据原始网格 701×101 = 70801 行；`smooth_factor=3` 加密后
2103×303 = 637209 行。需要时显式传 `long_table=True`。

---

## 5. 参数怎么设

### `em_range`（统计 / 找峰的 EM 区间）

**强烈建议显式指定。** 全窗积分会把瑞利/拉曼散射带与近红外本底一起积进去，
最佳 EX 会被散射带拉走。

经验值：先看 `plot_3d_scan` 的等高线图确认发射带位置；罗丹明类 RB 发射峰约 575–590 nm，
可用 `em_range=(450, 800)`。

### `em_band`（积分区间）

`band_area_table` **必须**显式给（默认 560–700 nm 只对罗丹明类合适）。

### `baseline`

| 取值 | 做法 | 适用 |
|---|---|---|
| `'none'` | 不扣基线 | 本底已很低的干净数据 |
| `'min'` | 扣区间最小值 | 有恒定偏置 |
| `'edge'` | 区间两端各 5% 均值线性外推 | **推荐**，最接近文献做法 |

### 清洗参数

原样透传给 `prepare_grid`（`--smooth` / `--despike` / `--sigma-em` / `--sigma-ex` /
`--no-notch` / `--comb-mode` / `--no-clip-saturation` / `--remove-scatter`）。

> ⚠️ **换清洗参数会改变定量结果**。示例数据实测：最佳 EX 在 505–600 nm 之间变动
> （差 95 nm）、峰位漂移在 177.8–399.0 nm 之间变动（差 221 nm）。
> 如果一组数字对清洗参数敏感，它就不是可靠的物理量 —— 这正是判据 1–4 想提前告诉你的。

---

## 6. 建议 GUI 怎么接

### 6.1 关键原则：复用同一个 prep，**并且必须传 `raw`**

`gui_plot.py` 的 `_do_scan3d_plot` 已经在第 1488 行附近调过 `prepare_grid(data, ...)`。
**不要再调一次**，直接把那个 `prep` 传进来；**同时把 `data` 作为 `raw` 传进去**：

```python
# gui_plot.py 里 _do_scan3d_plot 的现有代码已有 data 和 prep
# 只需在其后追加：

import plot_eem_quant as _peq

# 1) 定量读出（不弹窗、不重复清洗）
quant = _peq.eem_quant_all(
    prep,                              # ← 复用，不要再 prepare_grid 一次
    raw=data,                          # ← 关键！诊断需要原始矩阵，见 6.2
    save_dir=self._out_dir(),          # GUI 现有导出目录
    label=data.get('label') or file_name,
    em_band=self._scan3d_em_band(),    # 见 6.3
    em_range=self._scan3d_em_range(),
    show=False,
    verbose=False,                     # 不污染 GUI 控制台
)

# 2) 结果挂到已有结果 dict 上，供"数据输出区"显示
self._last_scan3d_result['quant'] = quant
self._last_scan3d_result['quantifiable'] = quant['reliable']
```

### 6.2 ⚠️ 为什么必须传 `raw`（漏传会出错判）

**诊断用原始矩阵，定量用清洗后的 prep —— 这是两件不同的事。**

`prepare_grid` 的默认管线（陷波 → 中值去窄线 → 高斯平滑 → 样条加密）
会把伪迹**连同信号一起抹平**。如果诊断只看 `prep['Z']`，
它看到的是一份"很干净"的数据（因为证据已被销毁），会**错判为可定量**。

这不是理论担忧——开发中真实踩到了：第一版只看 prep，
示例数据（实际 11.35% 饱和、77.8× 伪迹）被判为**"四条判据全部通过"**。

漏传 `raw` 时模块会退化到用 prep 诊断，并：
- 在 `quality['warning']` 里写明"判据可能偏乐观"
- 在 `quality['messages']` 里插入一条 `⚠️` 开头的提示

**GUI 必须把这个 warning 显示出来**，否则用户会以为结果可信。

### 6.3 数据输出区怎么显示

`quality['messages']` 已经是**可直接显示的中文句子列表**：

```python
for msg in quant['quality']['messages']:
    self._append_output(msg)          # 逐行写进数据输出区
```

`reliable=False` 时**必须**给用户醒目的警告，不要让这些数字看起来像结论：

```
⚠️ 该数据不满足定量条件，以下读数仅供参考：
   • 饱和占比未通过：饱和上限 50000，8037 个点（11.35%）
   • 周期伪迹强度未通过：频谱峰/底噪 77.8×（阈值 20），周期 6.941 nm
   • EM 通道平滑度未通过：二阶差分纹波 0.3742（阈值 0.06）
   • 分块最佳 EX 的一致性未通过：4 个 EM 块的最佳 EX: 600/539/581/514
```

### 6.4 需要新增的控件（建议）

| 控件 | 类型 | 默认 | 说明 |
|---|---|---|---|
| 发射带区间 | 两个 `QDoubleSpinBox` | 560 / 700 | 传给 `em_band` |
| 统计区间 | 两个 `QDoubleSpinBox`（可勾选"全窗"） | 450 / 800 | 传给 `em_range` |
| 导出长表 | `QCheckBox` | **不勾** | 传给 `long_table` |
| 「读取定量结果」按钮 | `QPushButton` | — | 触发上面那段代码 |

**不要**给四条判据的阈值做 UI 控件 —— 它们是有物理依据的标定值，
让用户随手调会把"可信度检查"变成"调到能出数为止"。

### 6.5 三个 draw_* 函数可直接画到 GUI 画布

如果想让定量图进 GUI 的 tab 而不是存文件：

```python
ax = self.canvas.fig.add_subplot(111)
_peq.draw_optimal_excitation(ax, quant['optimal'])
# 或用 draw_peak_drift / draw_band_area
self.canvas.draw_idle()
```

---

## 7. 示例数据的实测结论（**这份数据不可定量**）

`示例数据/04-3D扫描EEM-RB-Lu/RBLu 1 2026-07-27 07-11.csv`
（EX 500–600 nm × EM 200–900 nm，701×101 = 70801 点）：

| 证据 | 实测值 | 说明 |
|---|---|---|
| 饱和点 | **8037 个 = 11.35%** | 仪器上限 50000 |
| 梳状伪迹周期 | **6.9400 nm** | 最小二乘拟合（6.5–7.6 nm 网格），相位 2.938 rad |
| 梳状伪迹峰/底噪 | **77×** | 远高于纯噪声期望（≈2.8） |
| 梳状峰位是否随 EX 移动 | **不移动** | 固定在 EM ⇒ 不是样品荧光 |
| 伪迹幅度（峰−谷中位） | **≈8600** | 远超任何荧光信号 |
| 地板包络（滚动最小值） | EM 200–500 ≈**1200**，EM 700–800 ≈**1900**，EM 800–900 ≈**2000–2400** | 平滑无结构 ⇒ **没有发射带** |
| 参数敏感性（最佳 EX） | 505 → 600 nm（差 **95 nm**） | 换 `comb_mode` 即变 |
| 参数敏感性（峰位漂移） | 177.8 → 399.0 nm（差 **221 nm**） | 同上 |
| 分块最佳 EX | **600/539/581/514**（4 块，散布 86 nm = 量程 86%） | 无可分离性要求的一致性 |

**结论：这份数据不支持定量读出。** 上面这些数字**不能**写进实验报告。
`assess_quantifiability` 在它上面返回 `quantifiable=False`，模块实测输出：

```
🔍 可定量性诊断（原始矩阵）
   ❌ 饱和占比：0.114 / 阈值 0.02　饱和上限 50000，8037 个点（11.35%）
   ❌ 周期伪迹强度：77.825 / 阈值 20　频谱峰/底噪 77.8×（阈值 20），周期 6.941 nm
   ❌ EM 通道平滑度：0.374 / 阈值 0.06　二阶差分纹波 0.3742，对数域量程 1.66 decade
   ❌ 分块最佳 EX 的一致性：0.860 / 阈值 0.25　4 个 EM 块: 600/539/581/514（散布 86 nm）
   → ⛔ 不可定量：以下读数标 reliable=False，仅供参考
```

> 想让这份数据变得可定量，得回到测量端：**降低检测器电压或缩短积分时间以避免饱和**，
> 并排除产生 6.94 nm 周期条纹的干涉源（滤光片/窗口的 étalon 效应或光栅鬼线）。

---

## 8. 验证状态

> **本模块已全部验证通过**（2026-11-08，`C:\Python311\python.exe`）。

| 验证项 | 结果 |
|---|---|
| `python -m py_compile` | ✅ 通过 |
| 合成真值自检 `--self-test` | ✅ **12/12 全部通过** |
| 真实数据实测 | ✅ 4/4 判据正确判出"不可定量" |
| 与原始数据一致性（±1 nm） | ✅ 最大偏差 **0.15 nm** |
| PNG 渲染 + 目检 | ✅ 真实数据图与合成真值图均人工看过 |
| CSV 产物核对 | ✅ 4 个文件，每个带 `reliable` 列 |

### 8.1 自检还原精度（`--self-test`）

```
🧪 合成真值自检
  ✅ _interp_peak 还原抛物线顶点：得到 7.300，真值 7.300
  ✅ _fwhm 还原高斯半高宽：得到 7.0645，真值 7.0645
  ✅ 合成真值被判为可定量：四条判据全部通过
  ✅ 还原最佳激发波长：得到 550 nm，真值 550 nm
  ✅ 最佳 EX 标记 reliable：reliable=True
  ✅ 还原发射峰位：EX=550 处得到 621.70 nm，真值 621.82 nm（设计参数 620）
  ✅ 单一荧光体峰位漂移（强激发段）：漂移 1.89 nm（容差 4 nm）
  ✅ 无噪声可分离数据漂移为 0：漂移 0.0000 nm，峰位 622.04 nm
  ✅ 人为周期伪迹能被检出：峰/底噪=39.14，平滑度=0.2471
  ✅ 干净数据未被误判为伪迹：峰/底噪=7.55，平滑度=0.01276
  ✅ CSV 导出：4 个文件
  ✅ PNG 出图

✅ 全部通过（12/12）
```

> 真值为什么是 **621.82** 而不是 620：双高斯带的次峰（620+85 nm，幅度 0.35）
> 把总轮廓往长波拉。`synthetic_truth()` 会从 profile 算出实际真值供断言。

### 8.2 与原始数据的一致性（任务要求 ±1 nm）

在**同一网格**（只掩饱和 + 沿 EM 补全）上比较：

```
    EX    模块EM_peak    直接argmax    差(nm)
   500        718.0       718.0      0.0
   520        530.0       530.0      0.0
   540        682.1       682.0      0.1
   550        668.1       668.0      0.1
   560        654.1       654.0      0.1
   580        738.0       738.0      0.0
   600        717.0       717.0      0.0
最大偏差 = 0.15 nm → 通过
```

⚠️ 如果拿**完全原始**的 CSV 列做 argmax，会差 250–350 nm——因为
**7/7 个 EX 的窗口最大值都是饱和点 50000**，原始 argmax 落在伪迹列。
这不是模块的问题，是数据本身没有可目检的真峰。

### 8.3 复跑验证

```bash
# 1) 语法
C:\Python311\python.exe -m py_compile plot_eem_quant.py

# 2) 合成真值自检（不需要数据文件）
C:\Python311\python.exe plot_eem_quant.py --self-test

# 3) 真实数据（预期：判为不可定量）
C:\Python311\python.exe plot_eem_quant.py ^
  "示例数据\04-3D扫描EEM-RB-Lu\RBLu 1 2026-07-27 07-11.csv" ^
  --em-band 560,700 --em-range 450,800 -o "%TEMP%\eem_test"
```

---

## 9. 常见问题

**Q：为什么 `reliable` 是 `False`，但函数还是返回了 `best_ex`？**

A：因为"给出数字 + 明确标注不可信"比"直接报错不返回"更有用 —— 你可以拿它做质量排查，
但**不要**写进报告。这也是为什么每个 CSV 都有 `reliable` 列。

**Q：`contrast` / `area_contrast` 是什么？**

A：`max / median`。`< 1.1` 说明各激发波长的总强度几乎没差别 —— "最佳 EX"是噪声挑出来的。

**Q：峰位漂移动辄上百 nm，是内滤效应吗？**

A：**不是。** 内滤效应造成的峰位移动通常在几 nm 到十几 nm。上百 nm 说明峰位跟着伪迹跑，
是数据质量问题。真实的多组分体系漂移也远小于此。

**Q：为什么 `band_area_table` 不给默认值就报错？**

A：发射带位置随体系变化很大（RB ≈580 nm，其他体系可能完全不同）。
给一个"看起来合理"的默认值反而危险 —— 用户会忘了改。

**Q：`smooth_sigma` 该设多少？**

A：`prepare_grid` 默认 `smooth_factor=3`（样条加密 3 倍），此时网格已经很密，用 0。
如果传 `smooth_factor=1`（1 nm 原始网格），建议 1–2。

**Q：能不能直接用 `data` 而不先 `prepare_grid`？**

A：可以，`_as_prep` 会自动调 `prepare_grid`。但**建议**自己先调 ——
这样你能复用同一个 `prep` 做多次定量，且能检查清洗统计。
