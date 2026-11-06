# CHANGELOG v5.0.0

**版本**：v5.0.0
**日期**：2026-11-06
**类型**：MAJOR —— 工具改名（破坏性）+ 版本号体系重构

---

## ⚠️ 兼容性说明（升 MAJOR 的两条理由）

### 1. 独立模块改名：`plot_zn_rb_analysis` → `plot_ref_ratio_analysis`

**这条是破坏性的**：任何外部脚本里写过

```python
from plot_zn_rb_analysis import analyze_zn_rb_folder
```

**会直接 ImportError**。请改成：

```python
from plot_ref_ratio_analysis import analyze_zn_rb_folder
```

| 旧 | 新 |
|---|---|
| `plot_zn_rb_analysis.py` | `plot_ref_ratio_analysis.py` |
| `plot_zn_rb_analysis使用说明.md` | `plot_ref_ratio_analysis使用说明.md` |
| `from plot_zn_rb_analysis import ...` | `from plot_ref_ratio_analysis import ...` |

**改名理由**：旧名把两个具体化学品（Zn / RB）写进了模块名，而它实际提供的是
**通用能力**——以参照物峰值为内标、对浓度系列做局部放大 / 找峰 / 归一化浓度图。
换一个体系（换个参照染料、换个待测物）这套分析完全一样，叫 `zn_rb` 会让人以为它只能干那一个课题。

**保持不变**（重要）：模块内**全部公开函数名一字未改**——
`analyze_zn_rb_folder`、`read_zn_info`、`plot_individual`、`plot_combined_zoom`、
`export_peak_table`、`plot_rb_normalized_concentration`、`find_main_peak`、`find_aux_peaks`。
它们的参数、返回值、行为都不变，**只改了文件名**。
（函数名里的 `zn_rb` 属于"这套分析的业务语境"，改名收益低而破坏面大，故保留。）

**同步更新的引用点**（共 4 个文件、8 处）：
`__init__.py`（2 处）、`README.md`（1 处）、
`可视化分析GUI/检查版本一致性.py`（2 处，含 `PLOT_MODULE_EXCLUDE` 白名单）、
使用说明文档（3 处）。

### 2. 版本号体系重构：PATCH 位从「永远 .0」改为承载可判定的修复类别

旧规则下 `4.44.0 → 4.45.0 → 4.46.0 → 4.47.0` 连续四次发版**全是修复、没有一个是新功能**，
MINOR 被当成了"每次发版 +1"，PATCH 位从头到尾没用过。后果是第三位没有信息量：
「4.47.0」和「4.44.0」在版本号上无法区分「修了个错别字」和「修了一整类静默产错」。

新规则（详见 `spectra-module-dev` 技能 §4.2.1）给 PATCH 分配**可判定的类别**：

| PATCH | 类别 | 含义 |
|---|---|---|
| `.1` | 数值/口径 | 修了会导致结果算错的问题 |
| `.2` | 产物/导出 | 导出物内容或字段错 |
| `.3` | 稳定性/状态 | 崩溃、静默失败、竞态、状态残留 |
| `.4` | 界面/可用性 | 布局、对比度、可访问性、文案 |
| `.5` | 文档/工程 | 注释、README、打包脚本、测试自身缺陷 |
| `.6` | 依赖/构建 | 依赖版本、PyInstaller、资源 |

这样 `5.0.3` 一眼可知是「稳定性修复」，不必打开 CHANGELOG 就能判断该不该升级、要不要重跑数据。

> 本版自身按此规则应记为 **`5.0.5`（文档/工程）** —— 但因为它同时含**破坏性改名**，
> 按「PATCH 不允许破坏性变更，一旦出现直接升 MAJOR」的规则，记为 **5.0.0**。

---

## 🔄 工具改名

- `plot_zn_rb_analysis.py` → **`plot_ref_ratio_analysis.py`**（内容与 API 不变）
- `plot_zn_rb_analysis使用说明.md` → **`plot_ref_ratio_analysis使用说明.md`**
- 说明文档标题与示例代码同步更新
- `README.md` 的模块表、`__init__.py` 的导出、`检查版本一致性.py` 的模块清单同步

改名执行方式：先 dry-run 列出全部待改位置并人工核对，再 `--apply`；
执行前把 5 个受影响文件备份到仓库外（`_审计_20261105/rename_backup/`）。
验证：`py_compile` 通过、模块可导入、**8 个公开 API 全部保留原名**、
4 个引用文件**零旧名残留**、版本一致性检查 12/12 通过。

---

## 📌 顺带说明

- 本版**没有任何功能、数值或产物变化**——纯粹是改名 + 版本号规范调整。
  因此**不需要重跑历史数据**，旧结果与新版结果完全可比。
- 上一条 `v4.47.0`（门户可最小化 + 部分失败可见 + 门户键盘可达 + 参数栏折叠）
  已推送至 `origin/main`，tag `v4.47.0`。

---

## ✅ 验证

| 项目 | 结果 |
|---|---|
| `py_compile plot_ref_ratio_analysis.py` | 通过 |
| 模块导入 | `import plot_ref_ratio_analysis` 正常 |
| 8 个公开 API | 全部保留原名 |
| 旧名残留 | 4 个引用文件均 0 处 |
| 版本一致性检查 | **12 / 12 通过**（脚本自动识别 glob 到的新模块名） |
| 版本号解析 | `5.0.1 / 5.0.3` 可正确区分并比较大小 |
