# test 数据文件夹说明

## 第一组：2-Aminopurine（2025 分析小班二）

来源：`D:\北大\课程\25秋大二上\分析小班（二）\2025 荧光大作业文件\2025版本\专题2 Fluorescence Intensity Decays of 2-Aminopurine solutions\data.xlsx`

2-氨基嘌呤（2-Aminopurine, 2AP）荧光衰减数字化数据，已转成可视化分析工具「荧光寿命」模式
可直接读取的 Horiba/DeltaHub 时间扫描格式（`Labels/Type/Start/Stop/Step` 头部 + `时间,衰减,IRF` 三列）。

### 文件清单（7 份）

| 文件 | 原始来源 | 样品 | 时间窗 |
|---|---|---|---|
| Fig2_0pctH2O.csv | sheet "Fig. 2" | 0% H2O | 0–60 ns, 385 点 |
| Fig2_10pctH2O.csv | sheet "Fig. 2" | 10% H2O | 同上 |
| Fig2_100pctH2O.csv | sheet "Fig. 2" | 100% H2O | 同上 |
| Fig5_0M_Acrylamide.csv | sheet "Fig. 5" | 0M Acrylamide | 0–60 ns, 392 点 |
| Fig5_1M_Acrylamide.csv | sheet "Fig. 5" | 1M Acrylamide | 同上 |
| Fig9_FoldedRNA.csv | sheet "Fig. 9" | Folded RNA | 0–35 ns, 303 点 |
| Fig9_DenaturedRNA.csv | sheet "Fig. 9" | Denatured RNA | 同上 |

每个 sheet 的 Time 列为共享时间轴，IRF 列为该组共享的仪器响应函数，
每个样品列 + IRF 组合生成一份独立的 CSV（每个文件都带完整 IRF 列）。

### 数据处理说明

- **Fig. 2 的 IRF 修正**：原始 xlsx 中 Fig. 2 的 IRF 列在 40–60 ns 段有数字化伪迹
  （零星 100–300 计数的尖峰，应为本底 10），已按确认将 t ≥ 40 ns 的 IRF 全部置为 10。
  其余数据（三个样品衰减列、Fig. 5 / Fig. 9 全部列）与 xlsx 逐点一致，未做任何修改。
- 时间轴保留 xlsx 原值（Fig.2 步长 0.15625 ns；Fig.5 步长 ≈0.15345 ns；Fig.9 步长 ≈0.11589 ns）。
- 数据来自论文图数字化，噪声非严格泊松分布，拟合 χ²ᴿ 会明显高于 1 属正常现象；
  寿命分量数值仍可靠（2AP 在不同环境约 0.1–11 ns）。

## 第二组：FRET 距离依赖（2026 分析小班一）

来源：`D:\北大\课程\26春大二下\分析小班（一）\2026荧光大作业文件\2026版本\专题3 Distance Dependency of FRET (dsDNA)\专题1 Distance Dependency of FRET (dsDNA)\decay curves for lifetime-homeworkdata-shift resolved.xlsx`

dsDNA 不同供-受体距离的 donor 荧光衰减（FRET 效率随距离变化），同样转成 Horiba 格式。

### 文件清单（7 份）

| 文件 | 样品（受体距离） | 拟合参考值（MEM，默认参数） |
|---|---|---|
| FRET_A0.csv | A0（无受体对照） | τ = 3.74 ns |
| FRET_A6.csv | A6 | 快分量 0.54 ns（17.6%，FRET 猝灭）+ 3.59 ns |
| FRET_A9/A12/A15/A18.csv | A9–A18 | 介于两者之间 |
| FRET_A24.csv | A24（距离最远） | τ = 3.55 ns（FRET 可忽略） |

- 2048 点，0–50 ns，步长 24.4 ps；IRF 峰在 9.5 ns（峰前有零基线）。
- 数据与 xlsx 逐点一致，未做任何修改；χ²ᴿ ≈ 1.2，拟合质量很好。

## 使用方法

可视化分析工具 → 模块选择 → 「荧光寿命」→ 目录树进入本文件夹 → 加载文件夹 →
文件列表点选任一文件 → 「实时预览」。参数保持默认（MEM，速率点数 201）即可。
同一文件再次点选会直接加载缓存结果；修改方法/速率点数后自动重算。

## 注意

- `_diag_*.png` / `_raw_columns.png` 为转换验证时的诊断图，可随意删除。
