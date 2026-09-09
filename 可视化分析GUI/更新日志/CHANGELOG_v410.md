# 🔬 4.10 版本更新说明

**版本**：v4.10
**日期**：2026-08-31

---

## ✨ 新增：荧光寿命拟合结果导出（表格 + 单文件报告）

- 过去寿命模式只能导出 PNG 图与一整份嵌套 JSON（`_export_lifetime_plots`）；JSON 是原始嵌套结构，不便直接贴进论文 / Excel。
- 新增**专用导出**：在荧光寿命模式下，操作栏出现两个按钮（仅该模式可见）：
  - **💾 导出当前拟合结果**：导出当前主画布正在显示的那个文件的拟合结果。
  - **📊 导出全部勾选拟合结果**：对当前勾选的全部寿命文件分别拟合，批量导出。
- 两种范围都会写出：
  - `lifetime_fit_results_summary.csv`：**汇总表**，每行一个文件，列含
    文件名 / 方法 / 拟合区间起止(ns) / χ²R / qshift(ch,ns) / IRF_FWHM(ns) / 分量数，
    以及各寿命分量 `τ_i(ns)` 与 `占比_i(%)`（分量数不一致的，少的分量列留空）。
  - `lifetime_fit_results_summary.xlsx`：同上表的 Excel 版（依赖 openpyxl，缺失时自动跳过并提示）。
  - `lifetime_fit_results_<文件名>_report.md`：**每个文件的 Markdown 详细报告**
    （方法、χ²R、qshift、IRF FWHM、拟合区间、各寿命分量 τ / 强度占比）。

## 🧩 模块层复用函数（plot_lifetime.py）

- 新增可复用导出接口，GUI 与独立脚本共用：
  - `build_summary_table(results)` → pandas DataFrame（一行一文件）
  - `_format_report(result)` / `export_fit_results(results, save_dir, ...)` → 写 CSV+XLSX+md
  - 独立脚本 `plot_lifetime.py` 的命令行新增 `--export`：拟合后额外导出汇总表与报告。

## 🔖 版本号

- APP_VERSION 4.9 → **4.10**，RELEASE_DATE 2026-08-31；`生成splash图.py` 已重新生成 splash.png（v4.10）。

## 📦 打包备注

- `打包便携版.ps1` 无需改动（openpyxl 已在 hidden-imports 中；导出函数仅依赖 numpy/scipy/pandas/matplotlib/openpyxl，无 torch）。
