# 🔬 4.35 版本更新说明

**版本**：v4.35
**日期**：2026-09-11

---

## 🐛 修复：拟合完成后「发生未处理的错误：ValueError: too many values to unpack (expected 4)」

**症状**：点「开始拟合」跑完之后，弹出「发生未处理的错误」，日志里是

```
Traceback (most recent call last):
  File "gui_plot.py", line 2304, in _on_plot_finished
  File "gui_plot.py", line 1825, in _show_lifetime_fit_info
ValueError: too many values to unpack (expected 4)
```

**根因**：v4.33 给 `peak_result` 的每一项**追加**了第 5 项（振幅占比），
`[tau, 强度占比, FWHM(k), 强度占比, 振幅占比]`。当时只改了 `plot_lifetime.py`
内部那处 4 元解包，**漏了两处 GUI 侧**：

1. `gui_plot.py::_show_lifetime_fit_info` —— 信息页的分量列表
   `for n, (tau, area, _fwhm, _w) in enumerate(peaks, 1)`
2. `gui_plot.py::_update_info_fit_card` —— 「拟合摘要」卡片分量表
   `for n, (tau, area, _f, _w) in enumerate(peaks, 1)`

拟合本身是成功的（分布图、拟合曲线都已画出），只是随后渲染信息页时崩在解包上，
所以表现为"图出来了但报未处理错误"。

**修复**：两处都改为按索引取值（不再依赖元组长度）：

- 信息页分量列表
  `τ1 = 0.6651 ns, 强度占比 = 1.54%，振幅占比 = 6.89%`，
  并补一行口径说明；
- 「拟合摘要」卡片分量表由 3 列扩到 **4 列**：
  `分量 / τ (ns) / 强度占比 (%) / 振幅占比 (%)`（`gui_ui.py`），
  表头 tooltip 也写明两个占比的口径；
- **向后兼容**：旧结果 json（`peak_result` 只有 4 项）不再报错，振幅列显示 `—`
  （取值处统一写 `p[4] if len(p) > 4 else nan`）。

口径与 v4.33 在单独拟合「寿命分布」页图例给出的两个占比**完全一致**，
只是把同一组读数补到了信息页与摘要表，便于复制/排序。

## ✅ 回归测试

新增 `GUI：信息页/结果摘要兼容 5 元 peak_result，不抛未捕获异常（v4.35）`：

- 用**真实拟合结果**（含 5 元 `peak_result`）直接走 `_show_lifetime_fit_info`
  —— 也就是原报错点，断言不抛异常、信息页含「振幅占比」「强度占比」；
- 断言分量表为 4 列且第 4 列是振幅占比、且该列有数值；
- 再喂一份**旧格式**的 4 元 `peak_result`，断言仍能正常显示（兼容性）。

**为什么之前没测到**：原有用例 `GUI：信息页拟合摘要卡片 + 质量徽标三档`
用的是**手写的 4 元** `peak_result`，恰好绕过了这个长度变化。新用例改用真实
拟合产物，长度与线上一致。另外补了一次 AST 扫描确认全仓库已无对
`peak_result` 的 4 元解包残留。

全套回归：**59 项通过 / 0 失败**（v4.34 为 58 项）。

## 🔖 版本号

- APP_VERSION 4.34 → **4.35**，RELEASE_DATE 不变（2026-09-11）。

## 📝 文档

- `docs/用户手册.md` 8.8 节：补充两个占比**同时出现在信息页与「拟合摘要」
  分量表**（4 列），并给出表格列名与复制/排序说明。

## 📦 打包备注

- 改 `gui_plot.py`（两处解包 + 信息页文案）、`gui_ui.py`（分量表 3→4 列）、
  `tests/run_regression.py`、文档、版本号
  → **无需**改 `打包便携版.ps1` 的 hidden-import 列表。
- 发布流程：`生成splash图.py` → `同步到mac文件夹.ps1` → `打包便携版.ps1` →
  启动测试 → `检查版本一致性.py` → git commit → 复制到 `D:\dsh backup`。
