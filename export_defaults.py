# -*- coding: utf-8 -*-
"""导出口径的单一来源（v5.0.2）。

**为什么单独一个根目录文件**：本仓库有两条互不依赖的导出路径 —— GUI
（``可视化分析GUI/``）与根目录的 ``plot_*.py`` 命令行脚本。两者都需要
"默认导出 DPI"，但根目录脚本要能脱离 GUI 目录单独跑（`python plot_absorption.py`
用的是脚本自身所在目录作为 sys.path[0]，import 不到子目录里的 gui_config）。

历史上这个值在六处各写了一份，结果是同一份数据从两条路径导出的图分辨率差
2–3 倍（GUI 600 / absorption 200 / emission 200 / 3d_scan 200 / compare 300 /
lifetime summary 200 / lifetime report PDF 150）。现在统一到这里，
``gui_config.py`` 再把它们 import 进去对外暴露，GUI 侧代码不用改引用。

改这里的值时请注意：**这是会改产物字节的改动**，属于 MINOR 及以上，
不是 PATCH 的范畴。
"""

# 位图导出默认 DPI（投稿级：多数期刊要求 ≥ 300，600 留出裁剪余量）
EXPORT_DPI_DEFAULT = 600

# 矢量产物（PDF/SVG）里内嵌位图的最低 DPI
EXPORT_DPI_VECTOR_MIN = 300

# 屏幕预览 / 快速检查 / 测试用低分辨率
EXPORT_DPI_PREVIEW = 150
