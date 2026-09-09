# 🔬 4.9 版本更新说明

**版本**：v4.9
**日期**：2026-08-31

---

## ✨ 改进：合并图数据增删时曲线颜色保持稳定

- 旧逻辑按「当前勾选文件的顺序索引」取色（`colors[i]` / `_palette(color_map, len(valid_files))`），
  只要新增或删除一条曲线，后面所有曲线的颜色都会整体错位、前后不一致。
- 新增共用模块 **`curve_colors.py`**（`CurveColors` 分配器）：
  - 按**数据身份**（样品名 / 文件名）记忆其在色带上的位置，已分配的颜色**永不变更**；
  - 新增数据取「离已用颜色最远」的位置，保证新曲线与已有曲线视觉区分度最大；
  - 离散色表（Set1 / tab10 等）按色表**自然顺序**取色，连续色带（viridis / rainbow 等）
    才启用最远点分配，避免默认配色下出现灰色等难看颜色。
- 作用范围覆盖三处合并图取色逻辑：
  - **GUI**：`_plot_combined`、`_plot_emission_combined`、`_render_combined_export_fig`
    三处改用稳定取色；换文件夹时清空身份缓存、换配色方案时整体重分配。
  - **独立脚本**：`plot_absorption.plot_combined_absorption` 与 `plot_emission.plot_combined`
    合并图同样改用按身份取色（显式传入 `colors` 参数时保持原行为不变）。
- 增删 / 插入任意曲线、勾选取消勾选、勾回原有数据，均验证**已分配颜色完全不变**。

## 🔖 版本号

- APP_VERSION 4.8 → **4.9**，RELEASE_DATE 2026-08-31；`生成splash图.py` 已重新生成 splash.png（v4.9）。

## 📦 打包备注

- `打包便携版.ps1` 两处调整：
  - 构建命令由 `python`（本机指向 3.13 且未装 GUI 依赖，会直接失败）改为 `py -3.11`，
    匹配项目约定的 3.11 环境（numpy 2.1.3 / matplotlib 3.9.2 / PyQt5）。
  - 新增 `--hidden-import curve_colors`，确保新模块稳定打进单文件 exe。
- 已产出 v4.9 便携 exe：`便携版\光谱可视化分析工具.exe`（约 110 MB，单文件可移植）。
- 验证：打包日志 0 警告/错误；offscreen 下启动 exe 冒烟，30 秒内进程持续运行
  （无导入/运行错误），合并图取色逻辑随程序一同打包可用。
