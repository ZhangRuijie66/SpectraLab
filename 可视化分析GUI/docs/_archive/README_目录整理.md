# GUI 根目录整理说明（E1）

整理日期：2026-09-07
整理范围：`可视化分析GUI\` 根目录下的历史文档、一次性测试脚本、多余启动批处理。

---

## 1. 为什么要整理

根目录此前堆放了 40 多个文件，其中：

- **历史修复记录 / 说明文档**（`BUGFIX*.md`、`FINAL_*.md`、`GUI_*.md`、`LAUNCH_*.md`、`INSTALL.md`、`QUICKSTART.md` …）
  都是 2026-08-26 ~ 08-29 早期调试阶段留下的过程记录，内容已被 `更新日志\CHANGELOG_v*.md` 取代，但仍有一定考古价值，不宜直接删除。
- **一次性测试 / 调试脚本**（`test_*.py`、`check_*.py`、`debug_gui.py`、`启动GUI.py` …）
  只在当时验证 PyQt5 能否启动、数据能否加载时跑过一次，现在不属于程序运行链路。
- **多余的启动批处理**（`run_gui_debug.bat`、`run_gui_en.bat`、`run_gui_v2.bat`）
  是调试期的替代启动方式，现役入口只有 `run_gui.bat`（静默启动）和 `run_gui.ps1`。

这些文件混在源码中间，会让人误以为 `test_*.py` 是程序的一部分，也影响打包/同步脚本阅读。
因此把它们分门别类收进 `docs\` 和 `tests\`，**只移动、不改内容、不删除**。

---

## 2. 移动清单

### 2.1 → `docs\`（历史说明 / 修复记录类，共 21 个 md）

| 文件名 | 内容简述 |
|---|---|
| `BUGFIX.md` ~ `BUGFIX_v5.md` | 早期 5 轮启动/加载 bug 修复记录 |
| `FINAL_FIX.md` | 修复收尾记录 |
| `FINAL_GUIDE.md` | 早期使用指南 |
| `GUI_LAUNCH.md` | 启动方式说明（旧版） |
| `GUI_README.md` | 旧版 README |
| `GUI_SUCCESS.md` | 早期"跑通"验收记录 |
| `GUI_SUMMARY.md` | 早期功能总结 |
| `INSTALL.md` | 旧版安装说明 |
| `LAUNCH_FIXED.md` | 启动修复说明 |
| `LAUNCH_GUIDE.md` | 旧版启动指南 |
| `PROJECT_COMPLETE.md` | 早期完工报告 |
| `QUICKSTART.md` | 旧版快速开始 |
| `QUICK_REFERENCE.md` | 旧版速查表 |
| `README_GUI.md` | 旧版 GUI README |
| `SOLUTION.md` | 启动问题解决方案 |
| `TROUBLESHOOTING.md` | 旧版排障手册 |
| `README_文件夹说明.md` | 旧版目录结构说明（内容已过时，见本文件） |

### 2.2 → `docs\`（多余启动批处理，共 3 个）

| 文件名 | 为什么移走 |
|---|---|
| `run_gui_debug.bat` | 调试用带控制台启动，现役入口不需要 |
| `run_gui_en.bat` | 英文环境启动变体，已不再维护 |
| `run_gui_v2.bat` | v2 时代遗留启动脚本 |

> **保留在根目录不动**：`run_gui.bat`（现役静默启动，调 `launch_hidden.py`）、`run_gui.ps1`（现役 PowerShell 启动）。

### 2.3 → `tests\`（一次性测试 / 调试脚本，共 12 个 py）

| 文件名 | 内容简述 |
|---|---|
| `_test_4k.py` | 4K 屏下 UI 缩放验证 |
| `debug_gui.py` | 带环境打印的调试启动 |
| `check_dependencies.py` | 依赖是否装齐的检查 |
| `check_peaks.py` | 找峰结果抽查 |
| `example_gui_usage.py` | 6 个调用示例 |
| `install_dependencies.py` | 自动 pip 安装依赖 |
| `test_gui.py` | GUI 启动冒烟测试 |
| `test_load.py` | 数据加载测试 |
| `test_load_fix.py` | 加载修复后的回归测试 |
| `test_peaks_all.py` | 全量找峰测试 |
| `test_pyqt_simple.py` | 最小 PyQt5 可用性测试 |
| `启动GUI.py` | 双击运行版启动脚本（与现役 `start_gui.py` 重复） |

---

## 3. 安全检查结果（移动前必做）

移动前用 ripgrep 在 `可视化分析GUI` 全目录搜索了这些文件名是否被其它代码引用：

1. 在**所有 `.py` 文件**中搜索 `^\s*(import|from)\s+(被移动的模块名)` → **0 处匹配**，
   即没有任何源码 `import check_peaks` / `from test_load import ...` 之类。
2. 在**所有 `.ps1` 打包/构建脚本**中搜索这些文件名 → **0 处匹配**。
3. 唯一出现这些名字的地方是**被移动文件自身**（如 `check_dependencies.py` 里提示
   `python install_dependencies.py`）以及**同样被移动到 `docs\` 的历史 md 文档**，
   二者一起搬走，相对引用关系不变。

**结论：没有任何文件因被引用而必须留在原位，12 个测试脚本全部成功移动。**
（`start_gui.py` 与 `启动GUI.py` 是两个不同文件，前者是现役入口、**保留原位**，后者是重复的旧脚本、已移入 `tests\`。）

---

## 4. 整理后的根目录结构

```
可视化分析GUI\
├── docs\                      ← 新增：历史文档 + 旧启动批处理 + 本说明 + 环境说明.md
├── tests\                     ← 新增：一次性测试 / 调试脚本（含 README.md 运行说明）
├── test\                      ← 原有：测试**数据**（CSV / 诊断 PNG），与 tests\ 无关
├── 更新日志\                   ← CHANGELOG_v*.md
├── 便携版\                     ← 打包产物（光谱可视化分析工具.exe）
├── mac打包文件夹\              ← mac 打包用源码副本（用 同步到mac文件夹.ps1 同步）
├── icons\                     ← QSS 小图标
├── _packaging\                ← PyInstaller 中间产物
├── __pycache__\
│
├── 【程序源码】
│   ├── absorption_gui.py      主窗口（入口之一）
│   ├── entry_gui.py           打包 exe 的真正入口（先 splash 再加载重依赖）
│   ├── start_gui.py           源码启动入口（含 launcher 循环）
│   ├── launch_hidden.py       无控制台静默启动（run_gui.bat 调它）
│   ├── gui_ui.py              界面构建 Mixin
│   ├── gui_data.py            数据加载 Mixin
│   ├── gui_plot.py            绘图/拟合 Mixin
│   ├── gui_config.py          全局常量（APP_VERSION / RELEASE_DATE）
│   ├── gui_components.py      自定义控件
│   ├── gui_launcher.py        模块选择入口对话框
│   ├── gui_splash.py          Qt 启动画面
│   └── 生成splash图.py         生成 splash.png（改版本号后要重跑）
│
├── 【资源】
│   ├── app_icon.ico           程序图标
│   └── splash.png             启动画面（版本号烧在图里）
│
├── 【构建 / 启动脚本】
│   ├── 打包便携版.ps1          PyInstaller onefile 打包
│   ├── 同步到mac文件夹.ps1      ← 新增（E2）：把源码同步到 mac打包文件夹
│   ├── 检查版本一致性.py        ← 新增（E5）：版本号/CHANGELOG/splash 一致性只读检查
│   ├── requirements.txt        ← 新增（E6）：人工整理的直接依赖
│   ├── requirements-lock.txt   ← 新增（E6）：pip freeze 全量锁定
│   ├── run_gui.bat             现役静默启动
│   ├── run_gui.ps1             现役 PowerShell 启动
│   └── 创建桌面快捷方式.bat
│
├── 光谱可视化分析工具.lnk       桌面快捷方式备份
├── mac打包文件夹.zip           历史压缩包（可忽略）
├── 便携版.zip                  历史压缩包（可忽略）
├── test.zip                    历史压缩包（可忽略）
└── _fix_*.png / _integ_*.png / _repack46.txt   调试期截图与打包日志（可忽略）
```

---

## 5. 移动后的副作用与运行方式

Python 把**脚本所在目录**（现在是 `tests\`）而非当前工作目录放进 `sys.path[0]`，
所以有 3 个脚本移动后需要额外设置才能跑（**内容未改，仅路径环境变化**）：

| 脚本 | 移动后 | 处理 |
|---|---|---|
| `tests\test_gui.py` | ⚠️ 需设 `PYTHONPATH` | 它把自身目录加入 sys.path，要靠 `PYTHONPATH` 指向根目录 |
| `tests\debug_gui.py` | ⚠️ 需设**绝对** `PYTHONPATH` | 先 `os.chdir` 到 `tests\` 再 `import absorption_gui` |
| `tests\启动GUI.py` | ❌ 已失效 | 它 `open('start_gui.py')`，而该文件在上一级；且与根目录 `start_gui.py` 功能重复，**请改用 `start_gui.py` / `run_gui.bat`** |

其余 9 个脚本（`_test_4k.py`、`check_peaks.py`、`test_load.py`、`test_load_fix.py`、
`test_peaks_all.py`、`test_pyqt_simple.py`、`check_dependencies.py`、
`install_dependencies.py`、`example_gui_usage.py`）移动后**仍可直接运行**。

推荐运行方式（详见 `tests\README.md`）：

```powershell
cd "D:\北大\QLS Lab\SPC\1O2+luminol\谱图\光谱\画图\可视化分析GUI"
$env:PYTHONPATH = (Get-Location).Path
python tests\test_gui.py
```

---

## 6. 后续维护建议

- 新增**临时验证脚本**请直接放 `tests\`，不要再堆根目录。
- 新增**模块使用说明**放 `画图\` 对应目录或 `docs\`；**版本变更记录**一律写 `更新日志\CHANGELOG_vXX.md`。
- 升版后先跑 `python 检查版本一致性.py` 再打包。
- 需要更新 mac 侧源码时跑 `powershell -File 同步到mac文件夹.ps1`（会覆盖 mac 文件夹同名文件）。
- 本文件若与实际结构不符，以实际为准并顺手更新本文件。
