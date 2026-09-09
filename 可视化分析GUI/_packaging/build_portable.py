# -*- coding: utf-8 -*-
r"""【已停用 / 危险脚本，故意留成空壳】—— 请勿运行，也不会做任何事。

原始文件（2026-08-27 17:05，1957 字节）已移到
`_quarantine\_packaging\build_portable.py`，原因见 `_quarantine\README.md`。

为什么危险（原脚本的三个致命缺陷）：
  1. 把 openpyxl 写进 --exclude-module —— 读 xlsx 样品信息时直接 ModuleNotFoundError；
  2. 只 --hidden-import 了 plot_absorption / plot_emission 两个模块
     —— plot_lifetime / plot_3d_scan / read_xlsx_info / curve_colors 全缺，
     打出来的 exe 一进寿命或 3D 扫描模式就崩；
  3. 入口是 absorption_gui.py 而不是 entry_gui.py
     —— 跳过启动画面，且与现役打包链路口径不一致。

它一旦被运行，会把 **正确的** 便携版\光谱可视化分析工具.exe 覆盖成上面那个残缺版本。
所以这里留一个同名空壳：谁不小心执行 `python _packaging\build_portable.py`，
只会看到这段说明并以退出码 1 结束，不会动任何文件。

真正的打包方式（唯一权威）：
    powershell -ExecutionPolicy Bypass -File 打包便携版.ps1
"""
import sys

print(__doc__)
print("[已停用] _packaging\\build_portable.py 是空壳，不会执行打包。")
print("         请改用：powershell -ExecutionPolicy Bypass -File 打包便携版.ps1")
sys.exit(1)