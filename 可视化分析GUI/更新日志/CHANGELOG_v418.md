# 🎨 4.18 版本更新说明

**版本**：v4.18
**日期**：2026-09-09

---

## ✨ 新增

### D6 出版图预设

- 参数面板新增 **「出版图预设」**：`无（默认 10×6 in）` / `单栏 (3.5 in 宽)` /
  `双栏 (7 in 宽)` / `幻灯片 (10×6 in)`。
- 选中预设后：**导出图**按该尺寸出图，并把 matplotlib 默认字号按比例缩小
  （单栏 ×0.62、双栏 ×0.78），避免小图上文字挤成一团；
  「导出图片」「导出全部图片」「寿命模式导出」全部生效（保存时临时改尺寸、
  保存后恢复，不改变预览窗口）。
- 导出图的合并图/单独图 figsize 也跟随预设。

### D7 峰位数值标注开关

- 参数面板「标记峰」下方新增 **「峰位标数值 (nm)」**（默认勾选）。
  取消勾选后，图上不再写波长数字（标记逻辑仍在，只是不显示数值）。
- 说明：峰位数值此前**已经**会标在图上（吸收/发射/差谱/导出图都会写），
  本次补的是「可关闭」这个开关。

### D2 会话恢复

- 关闭窗口时自动保存、下次启动自动恢复：**上次模式**、**上次文件夹**、
  **窗口几何**，以及常用参数（线宽、DPI、导出格式、出版图预设、图例位置、
  颜色方案、图形比例、标记峰、峰位标数值、归一化、EX 标注、寿命拟合方法/
  速率点数/自动 λ、3D 扫描绘图类型与梳状处理）。
- 入口界面选择模块时**该选择优先**；直接关窗退出则沿用上次模式。
- 恢复失败一律忽略并打印，不影响启动。

### D3 深色模式

- 目录树面板顶部新增 **「🌙 深色主题 / ☀️ 浅色主题」** 切换按钮，选择会随会话保存。
- `gui_config.py` 新增 **`THEMES`** 两套色板（light / dark），`apply_style` 改为按
  当前主题取色；深色下 matplotlib 画布、坐标轴、刻度、网格、图例同步换色。
- **顺带修掉一批只在浅色下成立的问题**：QSS 里原先硬编码的 ~20 处浅色
  （列表 hover/选中、禁用态、滚动条滑块、分隔条 hover、备选行、提示框）现在
  全部走色板；多个用 `setStyleSheet` 写死 `#334155` 灰的说明文字改为
  `role="sectionLabel/hint/infoLabel/folderLabel"` 的 QSS 角色类，
  否则深色底上几乎看不见；`QPlainTextEdit`（积分结果框）此前完全没被 QSS 覆盖，
  深色下仍是白底，现已纳入输入控件样式。

### D4 快捷键

| 键 | 功能 |
|---|---|
| `F5` | 实时预览（寿命模式为开始拟合） |
| `Ctrl+R` | 重新加载数据 |
| `Ctrl+O` | 选择文件夹 |
| `Ctrl+E` | 导出图片 |
| `Ctrl+Shift+E` | 导出全部图片 |
| `Ctrl+D` | 复制积分结果 |
| `F1` | 帮助（列出全部快捷键） |

### D5 最近文件夹 + 拖拽加载

- 目录树面板新增 **「最近文件夹」** 下拉框：记住最近 6 个成功加载的文件夹
  （自动剔除已失效路径），选中即加载。
- **把文件夹直接拖到窗口上即可加载**（`setAcceptDrops` + `dragEnterEvent`/
  `dropEvent`，只接受本地目录）。

## 🧪 验证

- `py_compile` 全部改动文件通过。
- 冒烟测试（offscreen，脚本归档到 `tests\`）：
  - `test_pub_peaklabel_smoke.py`：4 个预设的 figsize/字号缩放正确；
    `_savefig_pub` 保存后尺寸恢复；峰位标注开→20 个文本、关→0 个。
  - `test_session_theme_smoke.py`：7 个快捷键注册成功；主题切换往返正常且
    matplotlib facecolor 跟随；最近文件夹写入下拉框；会话保存后新建窗口
    恢复出 mode=scan3d / 双栏 / dpi=300 / 峰位标数值关 / 深色 / 上次文件夹。
  - `tests\shot_dark_theme.py`：原生平台截图目检深色主题（`plots\_diag3d\dark_theme.png`）。

## 🔖 版本号

- APP_VERSION 4.17 → **4.18**，RELEASE_DATE 2026-09-09；splash.png 已重新生成。

## ✨ 新增（同批：E3 回归测试集）

- 新增 `tests\run_regression.py`：**不依赖 pytest** 的自包含回归运行器
  （本机未装 pytest），自动设 `QT_QPA_PLATFORM=offscreen`，覆盖 **15 项**：
  模块导入 / 寿命 CSV 解析 / SESM 拟合自洽 / 固定寿命分量 / 3D 扫描解析与
  饱和·梳状检测·清洗后无负值 / 三种梳状处理 / GUI 四模式与选项组显隐 /
  3D 选项组显隐 / 导出格式映射 / 出版图预设 / 峰位标数值开关 / 主题色板 /
  快捷键 / 最近文件夹 / 发射模式渲染带标注。全通过退出码 0，失败退出码 1。
- `tests\README.md` 补上回归测试集用法与各专项冒烟脚本对照表。

## 📦 打包（E4 体积优化 + 统一打包验证）

- `打包便携版.ps1` 排除列表扩充：PyQt5 里用不到的 Qt 模块
  （WebEngine/WebKit/Qml/Quick/3D/Multimedia/Bluetooth/Sql/Designer/OpenGL 等 36 个）、
  各第三方包的 tests 目录（matplotlib/numpy/pandas/scipy）、pytest；
  并加 `--optimize 2`。
- **结果：exe 105.1 MB → 101.6 MB（−3.5 MB / −3.3%）**；
  启动测试通过（onefile 解压 + 字体缓存 40 s 后进程仍存活）；
  xref 依赖图确认 `plot_3d_scan`/`plot_lifetime`/`plot_emission`/
  `plot_absorption`/`curve_colors`/`read_xlsx_info`/`gui_launcher`/`gui_splash` 全部在内。
- ⚠️ **踩坑记录**：用编辑工具改 `打包便携版.ps1` 会**丢掉 UTF-8 BOM**，
  PowerShell 5.1 按 ANSI 读取导致中文乱码、解析失败（`The string is missing
  the terminator`）。**改完 .ps1 必须重新加 BOM**：
  ```powershell
  $c = Get-Content -Raw -Encoding UTF8 $f
  [System.IO.File]::WriteAllText($f, $c, (New-Object System.Text.UTF8Encoding $true))
  ```
- APP_VERSION 保持 **4.18**（本批只改测试与打包脚本，未改程序代码，
  故 exe 与 4.18 一致，不再另发版本号）。
