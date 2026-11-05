# tests\ —— 回归测试 + 历史调试脚本

> 注意：本目录是**脚本**目录；`可视化分析GUI\test\`（少个 s）是**测试数据**目录
> （CSV / 诊断 PNG），两者无关，别搞混。

---

## 0. 回归测试集（E3，2026-09-09 新增，推荐日常用这个）

```powershell
cd "D:\北大\光谱工具\可视化分析GUI"
python tests\run_regression.py
```

- **不依赖 pytest**（本机没装），纯标准库自包含运行器；
- 自动设 `QT_QPA_PLATFORM=offscreen`，不会弹窗；
- 覆盖 15 项：模块导入 / 寿命 CSV 解析 / SESM 拟合自洽 / 固定寿命分量 /
  3D 扫描解析与饱和·梳状检测·清洗后无负值 / 三种梳状处理 / GUI 四模式与选项组显隐 /
  3D 选项组显隐 / 导出格式映射 / 出版图预设 / 峰位标数值开关 / 主题色板 /
  快捷键 / 最近文件夹 / 发射模式渲染带标注；
- 全通过退出码 0，任一失败退出码 1（可直接接 CI 或打包前置检查）。

各功能模块的**专项冒烟脚本**（`test_*_smoke.py`）保留在本目录，出问题时单独跑定位更快：

| 脚本 | 覆盖 |
|---|---|
| `test_scan3d_smoke.py` | 3D 扫描模式：三种绘图类型 + 三种梳状处理 |
| `test_lifetime_export_smoke.py` | 寿命导出格式（B4） |
| `test_lifetime_diag_smoke.py` | 拟合诊断页 + 质量指标（C4/C5） |
| `test_lifetime_fixed_smoke.py` | 固定寿命分量（C6） |
| `test_lifetime_parallel_smoke.py` | 并行拟合 + 分布叠加（C1/C8） |
| `test_tau_range_smoke.py` | 寿命范围 τ 输入 → 速率网格 k = 1/τ 的端到端换算（v4.38，真实数据拟合；默认 τ 与 μs 级 τ_max 各跑一次） |
| `test_lifetime_unit_smoke.py` | 寿命时间单位 ns/μs（v4.39）：τ 换算、时间轴/τ 轴/信息页单位、改标题纯外观重绘、导出 PNG |
| `test_pub_peaklabel_smoke.py` | 出版图预设 + 峰位标注开关（D6/D7） |
| `test_session_theme_smoke.py` | 会话恢复 / 主题 / 快捷键 / 最近文件夹（D2–D5） |
| `shot_dark_theme.py` | 深色主题**视觉**验收（原生平台截图，输出 `plots\_diag3d\dark_theme.png`） |

---

## 1. 运行方式（历史脚本）

Python 会把**脚本所在目录**（即本 `tests\` 目录）放到 `sys.path[0]`，而不是当前工作目录。
因此从根目录执行 `python tests\xxx.py` 时，脚本里"相对自己所在目录"的路径会失效。

**推荐统一这样跑**（在 `可视化分析GUI` 根目录下打开 PowerShell）：

```powershell
cd "D:\北大\光谱工具\可视化分析GUI"
$env:PYTHONPATH = (Get-Location).Path      # 让脚本能 import 到 gui_*.py / absorption_gui.py
python tests\test_gui.py
```

`$env:PYTHONPATH` 用**绝对路径**，因为部分脚本会 `os.chdir` 到本目录，
相对路径会跟着变。

---

## 2. 各脚本说明与可运行性

| 脚本 | 作用 | 移动后能否直接跑 | 说明 |
|---|---|---|---|
| `_test_4k.py` | 4K 屏 UI 缩放验证 | ✅ 可以 | 自己插入了 `.` 和 `..`，路径自适应 |
| `check_peaks.py` | 找峰结果抽查 | ✅ 可以 | 硬编码了绝对路径 `...\画图` |
| `test_load.py` | 数据加载测试 | ✅ 可以 | 硬编码绝对路径 |
| `test_load_fix.py` | 加载修复回归测试 | ✅ 可以 | 硬编码绝对路径 |
| `test_peaks_all.py` | 全量找峰测试 | ✅ 可以 | 硬编码绝对路径 |
| `test_pyqt_simple.py` | 最小 PyQt5 可用性测试 | ✅ 可以 | 只依赖 PyQt5 |
| `check_dependencies.py` | 依赖是否装齐 | ✅ 可以 | 纯标准库 + 打印 |
| `install_dependencies.py` | 自动 pip 安装依赖 | ✅ 可以 | 独立脚本 |
| `example_gui_usage.py` | 6 个调用示例（打印为主） | ✅ 可以 | 独立脚本 |
| `test_gui.py` | GUI 启动冒烟测试 | ⚠️ 需设 PYTHONPATH | 它把**自己所在目录**加入 sys.path，所以要靠 `PYTHONPATH` 指向根目录 |
| `debug_gui.py` | 带环境打印的调试启动 | ⚠️ 需设 PYTHONPATH（绝对路径） | 先 `os.chdir` 到本目录再 `import absorption_gui`，必须用绝对 PYTHONPATH |
| `启动GUI.py` | 旧版"双击即启动"脚本 | ❌ 已失效 | 它 `open('start_gui.py')`，而 `start_gui.py` 在上一级；且功能与根目录 `start_gui.py` 完全重复 |

**替代方案**：想启动程序，直接用根目录现役入口，不要用 `启动GUI.py`：

```powershell
python start_gui.py        # 源码启动
.\run_gui.bat              # 静默启动（无控制台）
```

---

## 3. 为什么不直接删除

它们记录了早期"PyQt5 装不上 / 数据加载失败 / 4K 屏 UI 错位"等问题的排查过程，
偶尔回查有价值。真正结论性的内容已经沉淀到 `更新日志\CHANGELOG_v*.md` 和
`docs\` 里的历史文档中，所以这些脚本**不再是权威资料**，仅作参考。
