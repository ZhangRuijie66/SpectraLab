# 🔬 4.11 版本更新说明

**版本**：v4.11
**日期**：2026-08-31

---

## 🗑️ 移除：导出全部勾选拟合结果

- 删除荧光寿命模式操作栏的「📊 导出全部勾选拟合结果」按钮及其后台批量导出逻辑
  （对勾选文件逐个按需拟合再汇总的流程，单次可能触发多次 1–2 分钟的 MEM 拟合，
  体验差且易被误触）。
- **保留「💾 导出当前拟合结果」**：先预览/拟合某文件，再点该按钮即导出
  `lifetime_fit_results_summary.csv / .xlsx` 与该文件的 md 报告，功能不变。
- 模块层 `plot_lifetime.export_fit_results()` 及命令行 `--export` 不受影响。

## 🐛 修复：导出拟合结果报「argument 3 has unexpected type 'WindowsPath'」

- 根因：文件选择对话框 `QFileDialog.getExistingDirectory` 的默认目录参数
  直接传了 `Path` 对象（`self.current_folder`），Qt 要求字符串——v4.10 新增的
  拟合结果导出一选目录就崩溃。
- 现统一 `str(...)` 后传入；已核查其余全部对话框调用点均为字符串，无同类问题。

## 🔖 版本号

- APP_VERSION 4.10 → **4.11**，RELEASE_DATE 2026-08-31；splash.png 已重新生成为 v4.11。

## 📦 打包备注

- `打包便携版.ps1` 无改动。
