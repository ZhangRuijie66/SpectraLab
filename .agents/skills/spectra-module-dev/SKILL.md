---
name: spectra-module-dev
description: 光谱可视化分析工具（原 QLS Lab 光谱画图程序，2026-11-05 已迁至独立工作区 D:\北大\光谱工具）的新模块开发全流程——编写独立 plot_*.py 模块、集成进 PyQt5 可视化分析GUI（gui_ui/gui_data/gui_plot 三混入）、统一版本号、用 PyInstaller 打包便携 exe 并验证。凡用户提到给画图程序/光谱GUI加新功能或新拟合方法、把模块加进GUI、更新GUI、重新打包、改版本号，都使用本技能。
---

# 光谱画图模块开发全流程

三个交付物按顺序完成：**独立模块 → GUI 集成 → 打包**。每步都有验证标准，跳过验证会留隐患。

## 代码位置

> **⚠️ 2026-11-05 起：项目已迁至独立工作区 `D:\北大\光谱工具`（脱离 QLS Lab，先读这段）**
>
> - **当前唯一工作副本**：`D:\北大\光谱工具\`——项目根即 git 仓库根；其下 `可视化分析GUI\`
>   即 GUI 程序，根目录是 plot_*.py 等模块。**新功能开发、打包、验证都在这里做**。
> - 本技能随项目放在 `<项目根>\.agents\skills\spectra-module-dev\`（项目级技能，进入该工作区
>   自动加载）；同时在 `C:\Users\zhang\.agents\skills\spectra-module-dev\` 留一份用户级副本，
>   改动技能时两处同步（`Copy-Item` 覆盖即可）。
> - 历史：2026-09-10 18:36–19:10 原 `画图` 目录曾被同步客户端批量删除过一轮（只留下最近一小时
>   修改过的文件），抢救经过见 `D:\dsh backup\README_备份说明.md`；旧 `SPC\1O2+luminol\谱图\光谱\画图`
>   残留副本已于 2026-11-05 删除。
> - **重要文件备份目录**：`D:\dsh backup`（内含 `QLS_画图_restored_20260910\` 全量工程、
>   `_salvage_20260910\` 抢救素材及 v4.32–v4.42 各版本快照）。每完成一批改动，把工程复制一份进去。
> - git：仓库随目录迁移，历史不变（恢复提交 `dad0dee` = 恢复 + v4.28；**旧历史已导入为
>   `legacy-v427` 分支**，末端 `48e28a1` = v4.27；`master` 从恢复状态起算；迁移提交见 `git log`）。
> - 教训：这个目录**不要放进任何云同步盘**（北大网盘 AnyShare / 搜狗云 等），
>   或用"始终保留在此设备上"，否则可能再次被占位化/删除。

- 模块目录：`D:\北大\光谱工具`（plot_*.py 独立模块 + 各自的使用说明 md）
- GUI 程序：`可视化分析GUI`（absorption_gui.py 入口；gui_ui / gui_data / gui_plot 三个 Mixin；gui_config.py 常量；gui_components.py 自定义控件）
- 打包脚本：`可视化分析GUI\打包便携版.ps1`（PyInstaller onefile）
- 参考算法代码（带注释）：`D:\北大\光谱工具\代码（含注释）`（fluoit.py = 最大熵寿命拟合出处，utils.py = multistart 等）

环境：Windows + Git Bash，Python 3.11（numpy / scipy / pandas / matplotlib / PyQt5 / PyInstaller 已装，**无 torch**）。

## 第 0 步：先读懂惯例再动手

读 1–2 个现有模块再写代码，推荐 plot_emission.py（光谱绘图惯例）和 plot_lifetime.py（数值拟合+GUI 集成惯例）。必须遵守：

- 文件头部 docstring：适用数据格式、功能、一键用法、命令行用法
- `setup_chinese_font()`（模块导入时执行）+ `_safe_print()`（GBK 终端安全打印）
- 一键函数（如 `fit_lifetime(files, save_dir, ...)`，支持通配符/列表，返回结果 dict 列表）+ `argparse` 命令行入口
- 图默认存 `./plots` 不弹窗；配套写《plot_xxx使用说明.md》
- **只 import numpy/scipy/pandas/matplotlib**——打包脚本排除 torch/rich 等，新模块引入它们会让 exe 变大甚至打包失败
- 数据格式自动检测；Horiba/DeltaHub 时间扫描 CSV（头部 Labels/Type/Start/Stop/Step，数据区三列 time/decay/irf、行尾多逗号）的解析直接复用 `plot_lifetime.parse_decay_csv`

## 第 1 步：开发与验证模块

1. 算法如需参考已有实现，从 `代码（含注释）` 移植并**去 torch 化**（torch autograd 优化改 scipy SLSQP/minimize_scalar；GPU multistart 改多起点循环），保持算法流程与参数默认值一致。
2. 用真实数据端到端跑一遍（数据路径问用户，或搜索 `D:\北大\QLS Lab\SPC\**\*.csv`——实验数据仍留在 QLS Lab 目录，未随工具迁移），检查收敛指标（如 χ²ᴿ≈1）是否合理。
3. `python -m py_compile plot_xxx.py`；图表做视觉验收（渲染 PNG 后派 judge agent，验收标准=科研出图：图例、中文标签、无乱码、无遮挡）。

## 第 2 步：集成进 GUI

三混入职责：**gui_ui** 建界面与参数控件；**gui_data** 加载数据与信息页文本；**gui_plot** 后台线程执行计算并画图。光谱类型下拉框 `spectrum_type_combo` 的索引约定：0=吸收、1=发射、2=荧光寿命（新模式继续往后加，`self.spectrum_type` 用字符串 "absorption"/"emission"/"lifetime"…区分）。

**入口界面（gui_launcher.py，v4.0 起）**：启动时先弹 `ModuleLauncher` 对话框（MODES 列表：模式标识/标题/说明/颜色），选择后以 `AbsorptionGUI(initial_mode=...)` 进入主窗口；新模式要在 MODES 里加一项，并同步 `absorption_gui.MODE_INDEX` 的映射。两个启动入口（absorption_gui.main 和 start_gui.py）都要走 launcher。

**返回入口循环（v4.1 起）**：主窗口左上角「🏠 返回模块选择」按钮（gui_ui 建按钮 → gui_data.return_to_launcher 设 `next_mode="launcher"` 并 close）；absorption_gui.main / start_gui 的主循环检测 `window.next_mode`，为 "launcher" 时重新弹出 ModuleLauncher，直接关窗则退出。帮助/关于挂在入口对话框**标题栏自带的「？」**上：`setWindowFlag(Qt.WindowContextHelpButtonHint, True)` + 重写 `event()` 拦截 `QEvent.EnterWhatsThisMode` 调 `show_help()`；版本/日期/创建人来自 gui_config 的 APP_VERSION / RELEASE_DATE。

**gui_ui.py（create_tree_panel / create_param_panel）：**
- `spectrum_type_combo.addItems` 加新项
- 新建「XXX 选项」QGroupBox（仿 `lifetime_options_group`），`setVisible(False)` 默认隐藏；组内存放下拉框/数值框
- 需要随模式切换显隐的既有控件（plot_type_label、plot_type_combo、peaks_group、range_group、emission_options_group…）赋 `self.` 引用
- 「实时预览」按钮保持 `lambda: self.update_plot(explicit=True)`
- 注意补顶部 import（QSpinBox 之类容易漏）；`_trigger_live_update` 中对新模式提前 return（防止参数微调触发耗时重算）
- **画布边距坑**：`MplCanvas` 初始把子图边距设为 0（提示文字铺满用），`clear_fig()` 后不会恢复；光谱路径靠 `_do_plot` 末尾的 `subplots_adjust` 修正，新的 `_do_xxx_plot` 若提前 return 就必须自己补 `fig.subplots_adjust(left≈0.10, right≈0.97, top≈0.93, bottom≈0.14)`，否则坐标轴标签被裁在图外看不见

**gui_data.py：**
- 模块级 import 新模块的加载函数
- `on_spectrum_type_changed`：新索引分支设置 `self.spectrum_type`、各 group 的 setVisible、清缓存重载
- 新增 `_load_xxx_files(all_files)`：逐文件 try/except，不可解析的静默跳过（目录里混着其他类型 CSV 是常态），全部失败才弹警告
- `on_file_selected` 开头加模式分支（寿命等模式没有"波长"概念，走 `_show_xxx_info`）

**gui_plot.py：**
- `_do_plot` 开头分支到 `_do_xxx_plot`——它在 PlotWorker 后台线程里执行，**耗时计算全部放这里**，UI 控件只读值
- 结果存 `self._last_xxx_result`（供信息页与导出用）
- **多图输出**：如果一个模式要出多张图，在 `create_canvas_panel`（gui_ui）加独立标签页放第二个 `MplCanvas`（如寿命分布 tab），`_do_xxx_plot` 里分别画到 `self.canvas` 和 `self.lifetime_canvas`，两张图都要补 `subplots_adjust`（边距坑对每个画布都适用）
- `_on_plot_finished`：新模式下把结果摘要写入 `self.info_label`，状态栏给完成提示，并对第二个画布做 `_fit_to_widget()` + `draw()`
- **导出**：多图模式写一个 `_export_xxx_plots(save_dir)` 助手（导出各图 PNG + 结果 json），`export_plot` 和 `export_all_plots` 的该模式分支都调它
- 冒烟测试时给 `QMessageBox.information/critical/warning` 打静态补丁（print 代替），否则离屏测试会被模态弹窗挂死
- 绘图直接在 `self.canvas.fig` 上用 GridSpec 画（参考 `_do_lifetime_plot`）

**慢操作模式（单次 >30 秒，如寿命拟合 1–2 分钟）：**
- `update_plot(explicit=False)` 加 explicit 参数：非显式触发（加载文件夹、防抖 timer）时只画提示文字，不启动计算；只有「实时预览」按钮传 explicit=True

**⚠️ Qt 硬崩溃的两个经典陷阱（v4.29 踩过，各花了几小时）**

症状都是**没有任何 traceback 的进程猝死**（PyQt5 对"从槽函数/事件过滤器里逃出去的异常"直接 abort）：

1. **不要给 `QDockWidget.visibilityChanged` 这类信号接 lambda 闭包**。闭包引用 `self` 会和子控件
   形成引用环 → 窗口不再即时析构、被 GC 延后到任意时刻销毁 → 而"仍处于显示状态"的窗口在析构时
   dock 会发 `Hide` 信号，**在析构期派发该信号直接 abort（退出码 `0xC0000409`）**。
   连开 3 个主窗口必崩；`try/except` 和 `Qt.QueuedConnection` 都挡不住（崩在进入 Python 之前）。
   → 改用 `widget.installEventFilter(self)` 听 `QEvent.Show/Hide`（事件过滤路径在析构期安全）。
   自检：`python tests\_diag\loop_windows.py 60` 应该打印 `LOOP DONE`。

2. **不要每次建窗都重设应用级样式表**。`QApplication.setStyleSheet()` 会让 Qt 重新解析整张表并对
   进程内**每一个**控件 unpolish/polish；在"旧窗口还没被 GC 回收、又新建窗口"的场景（回归测试
   每项都建一次窗口）下，第 47~48 个窗口会崩在 `app.setStyleSheet` 这一行（访问违例 `0xC0000005`）。
   → `if app.styleSheet() != qss: app.setStyleSheet(qss)`。

排查手法（有效）：用 `Start-Process -RedirectStandardOutput/-RedirectStandardError` 重定向
+ `python -u`（PowerShell 的 `>` 管道在进程硬崩时会丢输出）；`python -X faulthandler` 只能抓到
真正的访问违例（`0xC0000409` 是 fail-fast，抓不到）。

**改完必做冒烟测试**（offscreen，不弹窗）：

```bash
cd "画图\可视化分析GUI" && QT_QPA_PLATFORM=offscreen python - <<'EOF'
import sys, os
sys.path.insert(0, os.getcwd()); sys.path.insert(0, os.path.dirname(os.getcwd()))
from PyQt5.QtWidgets import QApplication
app = QApplication(sys.argv)
from absorption_gui import AbsorptionGUI
w = AbsorptionGUI()
w.spectrum_type_combo.setCurrentIndex(<新索引>)        # 切模式
w.load_data_from_folder(r"<真实数据文件夹>")            # 加载
w.update_plot()                                        # 非显式→应只画提示
fig = w._do_xxx_plot()                                 # 直接调后台函数体=同步跑全流程
print(w._last_xxx_result)                              # 检查结果
w._show_xxx_info() if hasattr(w, '_show_xxx_info') else None
print("SMOKE TEST PASSED")
EOF
```

## 第 3 步：版本号与打包

- 版本号**只改** `gui_config.py` 的 `APP_VERSION`（gui_ui 窗口标题自动跟随）；grep 确认 start_gui.py / launch_hidden.py 没有硬编码旧版本残留；如需更新日期（帮助框显示）同步改 `RELEASE_DATE`
- 每个版本写一份 `CHANGELOG_vXX.md`，放进「更新日志」子文件夹（`可视化分析GUI\更新日志\`，与 CHANGELOG_v21–v41 同格式：版本/日期 + emoji 小节 + 版本号/打包/备注）
- `打包便携版.ps1` 里给新模块加一行 `"--hidden-import","plot_xxx",`（紧跟 plot_emission 之后），然后：
  `powershell -ExecutionPolicy Bypass -File 打包便携版.ps1`（约 2–3 分钟，后台跑）
- 产物：`便携版\光谱可视化分析工具.exe`（单文件 ~108MB；首次启动要解压+建字体缓存，等 25 秒属正常）
- **mac 打包脚本**：`可视化分析GUI\build_mac.command`（v4.31 重写归位）。
  权威副本在 GUI 根目录（受 git 跟踪），由 SYNC-MANIFEST 的 `app|build_mac.command`
  同步到 `mac打包文件夹\`；`*.command`/`*.sh` 由 `.gitattributes` 强制 **LF**
  （`core.autocrlf=true` 会转成 CRLF，macOS 上 `#!/bin/bash` 直接报 bad interpreter）。
  ⚠️ 别把脚本只放在 `mac打包文件夹\` 里——那个目录被 `.gitignore` 排除，
  也不在同步清单内，2026-09-10 事故中就是这样丢的。
- 发布收尾固定动作：`python 生成splash图.py` → `同步到mac文件夹.ps1` →
  `打包便携版.ps1` → 启动测试 → `python 检查版本一致性.py`（要求 **11 项全通过、0 警告**）→ git commit → 复制一份到 `D:\dsh backup`
- ⚠️ 编辑 `同步到mac文件夹.ps1` / `打包便携版.ps1` 后**必须确认 UTF-8 BOM 还在**
  （edit 类工具会吃掉 BOM，PS 5.1 会按 GBK 解析，脚本里的中文全变乱码）：
  `[System.IO.File]::ReadAllBytes($p)[0..2]` 应为 `239,187,191`
- 打包后验证：
  1. `grep 模块名 _packaging/build/SpectralAnalysisTool/xref-*.html` 确认模块进了依赖图
  2. 启动测试：后台运行 exe，等 ~30 秒（解压+建字体缓存），用 Git Bash 的 `kill -0 $!` 判断存活后 taskkill。注意 tasklist/PowerShell 按**中文进程名/路径**查找在编码上不可靠（GBK 乱码导致假阴性），存活判断用 `kill -0` 最稳
  3. 修改过的源文件全部 `python -m py_compile`

## 交付说明

向用户汇报时给：改了哪些文件、GUI 操作路径（哪个下拉框 → 哪个按钮）、拟合/绘图的关键数值（如 χ²ᴿ、寿命分量）、exe 位置与启动测试结论。
