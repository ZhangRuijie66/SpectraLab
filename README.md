# SpectraLab · 光谱可视化分析工具

面向荧光/吸收光谱实验的桌面分析工具。PyQt5 界面，支持四种测量模式的加载、绘图、拟合与批量导出，可打包成免安装的单文件 exe。

**当前版本**：v4.43

## 功能

| 模式 | 说明 |
|---|---|
| **吸收光谱 (UV-Vis)** | 紫外-可见吸收曲线绘制、峰标注、归一化对比、吸光系数计算 |
| **发射光谱 (Emission)** | 荧光发射曲线绘制、激发波长标注、归一化、按样品批量出图 |
| **荧光寿命 (Lifetime)** | 最大熵法（MEM/SESM）寿命分布拟合、多分量分解、强度/振幅占比、拟合质量评估 |
| **3D 扫描 (EEM)** | 激发-发射矩阵的 3D 曲面 / 等高线 / Waterfall，自动去除周期梳状伪迹与散射 |
| **数据比较** | 按样品信息表把每条谱压成一个读数（峰强/峰面积/指定波长），对浓度等变量作点线图 |

其他能力：三栏可折叠布局、浅色/深色/高对比三套主题、批量导出 PNG/PDF、拟合结果导出 JSON/CSV/Excel、多列光谱 xlsx 自动按列拆分。

## 安装

需要 Python 3.11。

```bash
pip install -r 可视化分析GUI/requirements.txt
```

## 快速开始

```bash
cd 可视化分析GUI
python start_gui.py
```

启动后先弹出模块选择对话框（四张卡片），选一种模式进入主窗口。主窗口左上角的「光谱类型」下拉框可随时切换模式。

其他入口：

- `run_gui.bat` — Windows 双击启动（无控制台窗口）
- `launch_hidden.py` — 隐藏控制台启动，供桌面快捷方式调用
- `entry_gui.py` — 打包入口（带启动画面）

## 独立模块（命令行 / 脚本调用）

项目根目录的 `plot_*.py` 可脱离 GUI 单独使用，每个模块配套一份《使用说明.md》：

```python
from plot_absorption import plot_absorption_spectra
plot_absorption_spectra("data/*.csv", save_dir="./plots")

from plot_lifetime import fit_lifetime
results = fit_lifetime("decay/*.csv", save_dir="./plots")
```

```bash
python plot_emission.py "data/*.csv" -o ./plots --no-show
python plot_lifetime.py -i "decay.csv" -o ./plots/lifetime
```

| 模块 | 用途 |
|---|---|
| `plot_absorption.py` | 吸收光谱解析与绘图 |
| `plot_emission.py` | 发射光谱解析与绘图 |
| `plot_lifetime.py` | 荧光寿命 MEM 拟合 |
| `plot_3d_scan.py` | 3D 扫描（EEM）绘图 |
| `plot_compare.py` | 按变量比较样品读数 |
| `plot_ref_ratio_analysis.py` | 峰查找、峰表导出、归一化浓度图 |
| `read_xlsx_info.py` | 说明.xlsx 样品信息读取与图例增强 |
| `curve_colors.py` | 曲线配色 |

## 数据格式

程序会自动检测格式，常见支持：

- **吸收**：LabSolutions UV-Vis CSV、通用两列 CSV
- **发射**：LabSolutions RF / RF-6000、Spectracle / FE30、FLWinLab
- **寿命**：Horiba / DeltaHub 时间扫描 CSV（头部 `Labels/Type/Start/Stop/Step`，数据区 time/decay/IRF 三列）
- **3D 扫描**：Spectracle / FE30「3D 扫描」CSV
- **信息表**：与光谱同目录的 `说明.xlsx`（含 `编号` 列 + 浓度/备注等列）

## 测试

`可视化分析GUI/tests/` 下有完整回归测试集（71 项，离屏运行）：

```bash
cd 可视化分析GUI
python tests/run_regression.py
```

打包前后另可运行版本一致性检查：

```bash
python 检查版本一致性.py     # 应 11/11 通过
```

## 打包便携版

```bash
cd 可视化分析GUI
powershell -ExecutionPolicy Bypass -File 打包便携版.ps1
```

产物为 `便携版/光谱可视化分析工具.exe`（单文件约 109 MB，目标机器无需 Python）。首次启动需解压资源，约 20–40 秒属正常。

## 项目结构

```
├─ plot_*.py                 独立分析模块（可脱离 GUI 使用）
├─ curve_colors.py           曲线配色
├─ read_xlsx_info.py         样品信息表读取
├─ 代码（含注释）/            参考算法实现
└─ 可视化分析GUI/
   ├─ start_gui.py           推荐入口
   ├─ absorption_gui.py      主窗口（组合三个 Mixin）
   ├─ gui_ui.py              界面与控件
   ├─ gui_data.py            数据加载与信息页
   ├─ gui_plot.py            计算与绘图
   ├─ gui_config.py          全局常量（版本号唯一来源）
   ├─ gui_launcher.py        模块选择对话框
   ├─ gui_help.py            帮助窗口
   ├─ gui_splash.py          启动画面
   ├─ icons/                 图标资源
   ├─ tests/                 回归测试
   ├─ docs/                  用户手册与环境说明
   ├─ 更新日志/               各版本变更记录
   └─ 打包便携版.ps1           PyInstaller 打包脚本
```

## 技术说明

- 界面：PyQt5 5.15 + 三 Mixin 分层（`gui_ui` / `gui_data` / `gui_plot`）
- 绘图：matplotlib（Qt5Agg 后端嵌入画布）
- 数值：numpy / scipy（寿命拟合用 SLSQP 与 minimize_scalar）
- 打包：PyInstaller onefile

依赖刻意保持精简，不含 torch / rich；新增模块请只依赖 `requirements.txt` 里的包，否则打包体积会暴涨。

## License

MIT
