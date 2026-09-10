# ✨ 4.23 版本更新说明

**版本**：v4.23
**日期**：2026-09-10

> 本版处理用户反馈的 2 个问题：**深色模式下帮助面板仍是浅色**、
> **跨样品汇总图 / PDF 报告会重新拟合一遍**。拟合算法与默认参数值**一律未动**。
> 另有第 3 条「UI 美观度」反馈，先出设计方案（见 `UI设计方案_讨论稿.md`），
> 本版不改界面结构。

---

## 一、深色模式下「帮助」面板还是浅色（已修）

### 现象与定位

深色主题下点左上角 **「❓ 帮助」**，弹出的下拉面板是一块近白色的板子
（实测背景 `#f9f9f9`，QPalette Window = `#f0f0f0`），与深色界面完全不搭。

排查过程（**不是** QMessageBox 的问题）：

- `F1` 帮助 / 入口界面「？」都是 `QMessageBox.about()`。实测在主窗口深色主题下
  渲染为 `#0f172a` 深底 + 浅字，**本来就是对的**；入口界面的也一样；
- 真正浅色的是 **`QMenu`**（QToolButton 的下拉菜单）。`apply_style()` 的样式表里
  **从来没有 QMenu 规则**，而 QMenu 是独立弹出窗口、只跟随 `QPalette`，
  于是回落到浅色 Fusion 默认色板。同源问题也会影响 matplotlib 工具栏的菜单。

### 修复

1. `gui_ui.apply_style()` 新增 **QMenu 规则段**（`menu_qss`）：背景随 `CARD`、
   文字随 `TEXT`、选中项用 `SELECT_BG/SELECT_FG`、禁用项用 `DISABLED_FG`、
   分隔线用 `BORDER`，并设置内边距与圆角项。这段既写进全局样式表，
   也**逐个下发**到现存每个 QMenu。
2. 为什么必须逐个下发：QMenu 的样式规则只在**第一次显示**时解析，
   切换主题后再弹出不会自动按新色板重算。实测同一份代码：
   - popup 后直接取图 → `#ffffff`（错）
   - 手工 `unpolish/polish` 后 → `#1e293b`（对）
   - 隐藏后再次 popup → `#1e293b`（对）
   所以 `apply_style()` 末尾对 `findChildren(QMenu)` + 帮助菜单统一
   `setStyleSheet(menu_qss)` + `unpolish/polish`，第一次弹出即正确。
3. **入口界面启动时跟随上次主题**：`ModuleLauncher` 以前在 `theme=None` 时硬用
   `DEFAULT_THEME`（浅色），深色用户每次启动都会看到一块全白入口界面，
   标题栏「？」里的帮助也是白的。新增 `gui_launcher.saved_theme()` 读
   QSettings 里的 `theme`，启动即用上次会话的主题。
   （主窗口「🏠 返回模块选择」本来就传当前主题，行为不变。）

### 验收

真实 windows 平台、真实路径取色（`tests/diag_menu_paths.py`）：

| 主题 | 帮助菜单背景 | 期望 |
|------|--------------|------|
| 深色 | `#1e293b` | ✅ 卡片色 |
| 浅色 | `#ffffff` | ✅ 卡片色 |

---

## 二、跨样品汇总图 / PDF 报告不再全部重新拟合（已修）

### 问题

寿命模式的「⏱ 开始拟合」把结果存进了 `_lifetime_fit_cache`
（键 = 文件名 + 方法 + 速率点数 + λ 设置 + k 范围 + 固定 τ），
但「📈 跨样品汇总图」「📄 导出 PDF 报告」「📊 叠加分布」三个按钮
**完全绕过缓存**，无条件调用 `fit_many` 把全部样品重算一遍——
每个样品 1–2 分钟，且连续点「汇总图 → PDF 报告」要把整批拟合两次。

### 修复

新增三个共用助手（`gui_plot`）：

- `_lifetime_cache_key(name, params)` —— **唯一的缓存键来源**。此前
  `_do_lifetime_plot` 自己拼键、批量操作不认键，正是漏复用的根因；
- `_lifetime_fit_kwargs(params)` —— 统一构造拟合参数（原本两处抄了同样一份 dict）；
- `_fit_all_with_cache(params, worker)` —— 逐样品查缓存：命中的直接复用，
  只把未命中的丢给 `fit_many`（仍带并行→串行兜底），
  新结果**回写缓存**，返回 `(results, n_reused, n_fitted)`（与文件列表同序）。

「叠加分布」「跨样品汇总图」「PDF 报告」三个入口全部改走这条路径，
提示文案也如实回显，例如：

- `已复用全部 7 个样品的已有拟合结果，正在出图...`
- `正在拟合 6 个样品（复用 1 个已有拟合结果）...`
- 完成后：`已保存（7 个样品，复用 7 个已有拟合结果）：<路径>`

缓存失效规则不变：改拟合参数 → 键变了自然重拟合；
重载数据 / 切模式 → `gui_data` 里已有的 `_lifetime_fit_cache.clear()`。

### 验收（`tests/test_lifetime_cache_smoke.py`，7 个真实 FRET 样品）

监视 `fit_many` 实际收到多少个数据集：

| 步骤 | 修复前 | 修复后 |
|------|--------|--------|
| 单文件拟合 A0 | 1 | 1 |
| 跨样品汇总图 | **7** | **6**（复用 A0） |
| 导出 PDF 报告 | **7** | **0**（全复用） |
| 叠加分布 | **7** | **0**（全复用） |
| 改速率点数后再汇总 | 7 | 7（缓存键变了，应重拟合） |

即「汇总图 → PDF 报告」整条链路从 14 次拟合降到 6 次；PDF + 汇总图产物正常落盘。

---

## 三、回归测试 35 → **37 项**（全部通过）

新增 2 项：

1. **「弹出菜单(QMenu)跟随主题」**：深色下全局样式表与每个 QMenu 的样式表
   都必须是深色卡片色 `background-color: #1e293b`，切回浅色必须换成 `#ffffff`
   且不残留深色底色；
2. **「跨样品汇总图/PDF 报告复用已有拟合结果」**：合成 3 个样品，
   监视 `fit_many` —— 首次汇总图拟合 3 个、PDF 报告 0 个、叠加分布 0 个、
   改 n_rates 后重新拟合 3 个。

```
python tests\run_regression.py  →  共 37 项：通过 37，跳过 0，失败 0
python tests\test_lifetime_cache_smoke.py  →  SMOKE TEST PASSED
python 检查版本一致性.py  →  11/11 通过（含 mac 文件夹 SHA256 同步）
```

---

## 四、本版改动的文件

| 文件 | 改动 |
|------|------|
| `gui_ui.py` | 新增 `menu_qss`（QMenu 主题规则）+ `apply_style()` 末尾逐个下发并重新解析 QMenu |
| `gui_launcher.py` | 新增 `saved_theme()`；启动时入口界面跟随上次会话主题 |
| `gui_plot.py` | 新增 `_lifetime_cache_key` / `_lifetime_fit_kwargs` / `_lifetime_cached_count` / `_fit_all_with_cache` / `_batch_fit_status_text`；`_do_batch_export`、`_do_overlay_lifetime`、`_do_lifetime_plot` 改用统一键与缓存 |
| `gui_config.py` | 版本号 4.22 → **4.23**，`RELEASE_DATE` → 2026-09-10 |
| `tests/run_regression.py` | 新增 2 项回归检查 |
| `tests/test_lifetime_cache_smoke.py` | 新增：缓存复用专项冒烟测试 |
| `tests/diag_menu_paths.py` 等 | 新增：QMenu 取色诊断脚本（排查用） |
| `UI设计方案_讨论稿.md` | 新增：UI 美观度设计方案（只讨论，未改代码） |

---

## 五、备注

- **拟合数值零改动**：默认参数（MEM / 201 点 / k 0.01–100 / 自动拟合 λ /
  固定 τ 留空）与算法流程一律未动，本版只改「结果从哪来」；
- 单文件「⏱ 开始拟合」的行为不变（命中缓存时仍提示「直接加载上次拟合结果」）；
- 深色模式仍有若干**已知的观感问题**（入口界面 🌙 图标、三个侧栏宽度与
  文字截断、操作区按钮颜色过多等），已整理进 `UI设计方案_讨论稿.md`，
  等确认方案后再动界面。
