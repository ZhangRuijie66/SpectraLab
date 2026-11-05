# 吸收光谱绘图工具使用指南

## 概述

`plot_absorption.py` 是专门用于处理 LabSolutions UV-Vis 输出吸收光谱文件的批量绘图工具。支持：
- 自动解析 UV-CSV 格式
- 单独光谱图 + 合并对比图
- 峰值自动标注
- 曲线平滑处理
- 数据归一化
- 摩尔吸光系数计算
- **Y轴比例尺自动优化** (2024-08-26更新)
- **默认不弹出pyplot窗口** (2024-08-26更新)

## 安装依赖

```bash
pip install pandas matplotlib numpy scipy
```

## 快速开始

### 1. 基础使用（自动解析并绘图）

```python
import plot_absorption

# 使用通配符选择多个文件
files = "D:/北大/QLS Lab/SPC/1O2+luminol/谱图/光谱/20260826/*.csv"

# 一键绘图：单独图 + 合并图
datasets = plot_absorption.plot_absorption_spectra(
    files=files,
    save_dir="./plots",
    normalize=False,          # 不归一化
    xlim=(200, 800),          # 波长范围
    ylim=(0, 5),             # 吸收值范围
    annotate_peaks=True,     # 标注峰
    smooth=True,             # 平滑曲线
    smooth_factor=2          # 平滑倍数
)
```

### 2. 分步使用

```python
import plot_absorption

# 第一步：加载数据
files = [
    "D:/北大/QLS Lab/SPC/1O2+luminol/谱图/光谱/20260826/20260826RB.csv",
    "D:/北大/QLS Lab/SPC/1O2+luminol/谱图/光谱/20260826/20260826Ce6.csv",
    "D:/北大/QLS Lab/SPC/1O2+luminol/谱图/光谱/20260826/20260826RBL8i.csv"
]

datasets = plot_absorption.load_absorption_spectra(files, verbose=True)

# 第二步：绘制单独图
plot_absorption.plot_single_absorption(
    datasets,
    save_dir="./plots",
    xlim=(200, 800),
    annotate_peaks=True,
    smooth=True
)

# 第三步：绘制合并图
plot_absorption.plot_combined_absorption(
    datasets,
    save_dir="./plots",
    normalize=False,      # 原始数据对比
    xlim=(200, 800),
    colors=['blue', 'red', 'green']
)
```

### 3. 命令行使用

```bash
# 基础绘图
python plot_absorption.py "D:/北大/QLS Lab/SPC/1O2+luminol/谱图/光谱/20260826/*.csv" -o ./plots

# 带参数绘图
python plot_absorption.py "D:/北大/QLS Lab/SPC/1O2+luminol/谱图/光谱/20260826/*.csv" \
    -o ./plots \
    --normalize \
    --xlim 200 800 \
    --ylim 0 5 \
    --peak-height 0.1 \
    --peak-distance 20 \
    --smooth \
    --smooth-factor 2 \
    --no-show

# 不绘制单独图，只绘制合并图
python plot_absorption.py "D:/北大/QLS Lab/SPC/1O2+luminol/谱图/光谱/20260826/*.csv" \
    --no-single \
    -o ./plots
```

## 主要函数

### 数据加载

```python
# 批量加载
datasets = plot_absorption.load_absorption_spectra(
    files,                    # 文件路径或通配符
    skip_metadata=False,      # 是否跳过元数据解析
    verbose=True             # 是否显示进度
)

# 单文件解析
data = plot_absorption.parse_absorption_csv("file.csv")
```

### 绘图函数

```python
# 单独绘图
plot_absorption.plot_single_absorption(
    datasets,                # 单个或多个数据集
    save_dir="./",           # 保存目录
    xlim=(200, 800),        # x轴范围
    ylim=(0, 5),           # y轴范围
    annotate_peaks=True,    # 标注峰
    smooth=True,            # 平滑曲线
    smooth_factor=2,       # 平滑倍数
    show=True              # 是否显示图像
)

# 合并绘图
plot_absorption.plot_combined_absorption(
    datasets,               # 多个数据集
    save_dir="./",          # 保存目录
    normalize=False,        # 是否归一化
    xlim=(200, 800),       # x轴范围
    colors=['red', 'blue'], # 自定义颜色
    title="吸收光谱对比"    # 图表标题
)

# 一键绘图
datasets = plot_absorption.plot_absorption_spectra(
    files="*.csv",          # 文件路径
    save_dir="./",          # 保存目录
    plot_individual=True,   # 绘制单独图
    plot_combined=True      # 绘制合并图
)
```

### 分析函数

```python
# 查找吸收峰
peaks = plot_absorption.find_absorption_peaks(
    data,                   # 光谱数据
    peak_range=(200, 800),  # 查找范围
    min_height=0.1,        # 最小峰高
    min_distance=20,       # 最小峰间距
    min_prominence=0.05     # 最小峰突出度
)

# 计算摩尔吸光系数
coeff_data = plot_absorption.calculate_absorption_coefficient(
    data,                  # 光谱数据
    path_length=1.0       # 光程（cm）
)
```

## 数据格式

工具支持 LabSolutions UV-CSV 格式，自动识别以下信息：

```
[样品信息]
类型:,测定数据
样品名称:,6RB
分析者:,张瑞杰
创建日期和时间:,2026/08/26 16:57:33

[测定]
开始(nm):,900 nm
结束(nm):,200 nm
数据间隔(nm):,0.5
光度值类型:,吸收值

波长(nm),吸收值
200.0,3.892
200.5,3.894
201.0,3.910
...
```

## 输出文件

- 单独图：`{样品名}_absorption.png`
- 合并图：`combined_absorption_spectra.png`
- 归一化合并图：`combined_absorption_spectra.png`（文件名相同，内容不同）

## 常见问题

1. **中文字体问题**：工具自动检测系统字体，如显示异常请确保已安装中文字体
2. **文件编码**：支持 UTF-8、GBK、Latin-1 编码
3. **波长范围**：UV-Vis 数据通常从高波长到低波长排列，工具会自动转换为递增排列
4. **内存占用**：大文件处理时会自动进行内存优化
5. **Y轴比例尺问题**：已自动优化，确保小数据有足够显示空间（2024-08-26修复）
6. **弹出窗口问题**：默认不弹出pyplot窗口，批量绘图更高效（2024-08-26修复）
7. **输出目录问题**：建议将图片保存在数据同目录的plots文件夹（2024-08-26建议）

## 可视化交互界面 (GUI)

### 简介
除了命令行使用，现在还提供了一个**图形化交互界面**，无需编程即可完成所有操作！

### 快速启动GUI

#### Windows用户
```bash
# 方法1：双击批处理文件
双击 run_gui.bat

# 方法2：命令行
python absorption_gui.py
```

#### 其他系统
```bash
python absorption_gui.py
```

### GUI功能特点
- 🎯 **文件/文件夹选择器**：直观选择数据文件夹
- 🎨 **参数调整面板**：实时调整线宽、DPI、颜色等
- 👁️ **实时预览**：参数修改立即看到效果
- 💾 **导出图片**：支持PNG、PDF、SVG格式
- 🚀 **数据缓存**：数据加载后保持在内存，切换流畅
- 🔍 **峰检测可视化**：自动标记吸收峰位置
- 📊 **双模式切换**：合并图 / 单独图一键切换

### 使用步骤
1. 启动程序：`python absorption_gui.py`
2. 点击"选择文件夹"，选择包含CSV/TXT文件的目录
3. 等待文件加载完成（显示在左侧列表）
4. 点击"实时预览"查看图表
5. 调整参数（线宽、颜色、峰检测等）
6. 点击"导出图片"保存结果

### 详细文档
- **完整使用指南**：见 `GUI_README.md`
- **快速开始**：见 `QUICKSTART.md`
- **依赖安装**：见 `install_dependencies.py`

### GUI vs 命令行对比

| 特性 | GUI | 命令行 |
|------|-----|--------|
| 使用难度 | 简单，无需编程 | 需要Python基础 |
| 交互性 | 实时预览，参数可视化 | 需要重新运行脚本 |
| 批量处理 | 手动操作，适合少量数据 | 脚本自动化，适合大批量 |
| 适用场景 | 数据探索、快速查看 | 重复性任务、自动化流程 |

**建议**：
- 初学者和快速查看 → 使用GUI
- 批量处理和自动化 → 使用命令行

## 更新日志

### 2024-08-26 (GUI版本)
- ✨ 新增：图形化交互界面 (PyQt5 GUI)
  - 文件/文件夹选择器
  - 参数调整面板（线宽、DPI、颜色方案等）
  - 实时预览功能
  - 导出图片功能（支持PNG/PDF/SVG）
  - 数据缓存机制
  - 峰检测可视化
  - 多线程绘图，避免界面卡顿
- 📝 文档：添加GUI_README.md和QUICKSTART.md
- 📦 工具：添加install_dependencies.py自动安装脚本
- 🚀 工具：添加run_gui.bat快速启动脚本
- ✅ 更新：README_absorption.md添加GUI使用说明

### 2024-08-26 (核心修复)
- ✅ 修复：Y轴比例尺自动优化，避免小数据被压缩
- ✅ 修复：默认不弹出pyplot窗口（show=False）
- ✅ 更新：建议将图片输出到数据同目录的plots文件夹
- ✅ 更新：__init__.py 导出所有吸收光谱函数
- ✅ 更新：skill.md 添加吸收光谱模块说明
- ✅ 新增：20260826 专用绘图脚本示例

## 推荐使用模式

### 数据目录结构
```
数据目录/
├── sample1.csv
├── sample2.csv
├── sample3.csv
├── run_plots.py      # 绘图脚本
└── plots/            # 图片输出目录（自动创建）
    ├── sample1_absorption.png
    ├── sample2_absorption.png
    ├── sample3_absorption.png
    └── combined_absorption_spectra.png
```

### run_plots.py 模板
```python
import sys
sys.path.insert(0, r'D:\北大\光谱工具')

from plot_absorption import plot_absorption_spectra
from pathlib import Path

DATA_DIR = Path(__file__).parent
OUTPUT_DIR = DATA_DIR / 'plots'  # 图片输出到同目录
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# 查找所有CSV文件
csv_files = sorted(DATA_DIR.glob('*.csv'))

# 批量绘图
plot_absorption_spectra(
    files=csv_files,
    save_dir=OUTPUT_DIR,
    plot_individual=True,   # 绘制单独图
    plot_combined=True,     # 绘制合并图
    show=False,             # 不弹出窗口
    dpi=200,                # 高分辨率
)
```

## 示例脚本

查看 `20260826/run_plots.py` 获取完整的使用示例。