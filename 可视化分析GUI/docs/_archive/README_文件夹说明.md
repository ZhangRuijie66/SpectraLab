# 📁 文件夹整理说明

本文件夹（`可视化分析GUI`）包含了**吸收光谱可视化分析工具**的全部相关文件，在 2026-08-26 的开发过程中创建。

**当前版本**：v2.4（读取说明.xlsx 写入图例并纳入打包；模块化）— 详见 `CHANGELOG_v24.md`

## 文件结构

```
可视化分析GUI/
├── 🚀 主程序（直接使用这些即可）
│   ├── 光谱可视化分析工具.lnk ← 【推荐】双击启动（无cmd窗口）
│   ├── run_gui.bat          ← 备选启动（pythonw无窗口）
│   ├── absorption_gui.py    ← 主程序入口（v2.3，模块化后仅负责组装）
│   ├── gui_config.py        ← 全局常量配置
│   ├── gui_components.py    ← 可复用界面组件（后台绘图线程/滑块/画布/资源定位）
│   ├── gui_ui.py            ← 界面样式混入（面板搭建、QSS、中文字体）
│   ├── gui_data.py          ← 数据混入（加载光谱/工作区/说明.xlsx图例增强）
│   ├── gui_plot.py          ← 绘图混入（实时预览/合并图/单独图/导出）
│   ├── launch_hidden.py     ← 无窗口启动入口
│   ├── start_gui.py         ← 启动脚本（窗口置顶版）
│   └── 启动GUI.py            ← 双击运行版
│
├── 🛠️ 辅助脚本
│   ├── install_dependencies.py   ← 自动安装依赖
│   ├── check_dependencies.py     ← 检查依赖
│   ├── example_gui_usage.py      ← 使用示例
│   └── debug_gui.py              ← 调试启动
│
├── 🧪 测试脚本
│   ├── test_gui.py               ← GUI功能测试
│   ├── test_pyqt_simple.py       ← PyQt基础测试
│   └── test_load.py / test_load_fix.py / test_peaks_all.py / check_peaks.py
│
├── 📄 使用文档
│   ├── GUI_README.md         ← 【推荐】完整使用指南
│   ├── QUICKSTART.md         ← 快速开始
│   ├── QUICK_REFERENCE.md    ← 快速参考卡片
│   ├── INSTALL.md            ← 安装指南
│   ├── FINAL_GUIDE.md        ← 最终使用说明
│   └── TROUBLESHOOTING.md    ← 故障排查
│
└── 📝 开发/修复记录
    ├── BUGFIX.md / BUGFIX_v2.md ~ v5.md  ← 各轮问题修复说明
    ├── FINAL_FIX.md           ← 最终修复总结
    ├── GUI_SUMMARY.md         ← 开发总结
    └── PROJECT_COMPLETE.md    ← 项目完成报告
```

## 🚀 如何启动

### 方法1：双击（推荐）
```
双击：run_gui.bat
```

### 方法2：命令行
```bash
cd "D:\北大\QLS Lab\SPC\1O2+luminol\谱图\光谱\画图\可视化分析GUI"
python start_gui.py
```

## ⚙️ 注意事项

1. **依赖关系**：`absorption_gui.py` 需要导入上层目录的 `plot_absorption.py` 模块，路径已自动配置好，无需手动修改。
2. **数据文件夹**：启动后点击"选择文件夹"，选择包含 CSV/TXT 数据文件的目录即可。
3. **中文字体**：程序自动使用 Microsoft YaHei 等中文字体。

## 📌 其他保留在原主目录的文件

以下文件不属于本次GUI开发，保留在 `光谱\画图` 目录：
- `plot_absorption.py` - 吸收光谱核心绘图模块（GUI依赖它）
- `plot_emission.py` / `plot_3d_scan.py` / `plot_zn_rb_analysis.py` - 其他光谱分析功能
- `read_xlsx_info.py` - 说明.xlsx 信息读取模块（GUI依赖它，自动读浓度等信息写入图例）
- `__init__.py` - 模块统一导出
- `README_absorption.md` - 吸收光谱绘图工具说明

---

**整理时间**：2026-08-26
**整理说明**：将本次GUI开发的所有文件统一收纳到本子文件夹，保持主目录整洁。