# `tests\_archive\` —— 历史调试脚本（**已归档，非权威**）

> **一句话：这里都是历史脚本，非权威，不要拿它们的输出当结论。**

归档日期：2026-09-09（仓库清理 F3）。
原位置：`tests\` 根目录；现位置：`tests\_archive\`（**只移动，不删除**）。

## 为什么归档

这些脚本记录了 v2.x 时代「PyQt5 装不上 / 数据加载失败 / 4K 屏 UI 错位」等问题的排查过程，
偶尔回查有价值；但它们：

- 大多硬编码绝对路径、或依赖 `PYTHONPATH` 设置，现在直接跑未必成功；
- 有的已经**完全失效**（`启动GUI.py` 会去 `open('start_gui.py')`，而该文件在上一级）；
- 功能与现役工具重复（`check_dependencies.py` / `install_dependencies.py` 已被 `requirements.txt` 取代）。

真正结论性的内容已沉淀到 `更新日志\CHANGELOG_v*.md` 和 `docs\`，所以这些脚本**不再是权威资料**。

## 清单

| 脚本 | 大小 | 原用途 | 备注 |
|---|---|---|---|
| `_test_4k.py` | 983 B | 4K 屏 UI 缩放验证 | 路径自适应，可直接跑 |
| `check_peaks.py` | 626 B | 找峰结果抽查 | 硬编码绝对路径 |
| `test_load.py` | 1,813 B | 数据加载测试 | 硬编码绝对路径 |
| `test_load_fix.py` | 2,608 B | 加载修复回归测试 | 硬编码绝对路径 |
| `test_gui.py` | 716 B | GUI 启动冒烟测试 | 需设 `PYTHONPATH` |
| `debug_gui.py` | 1,806 B | 带环境打印的调试启动 | 需绝对 `PYTHONPATH` |
| `test_pyqt_simple.py` | 1,028 B | 最小 PyQt5 可用性测试 | 只依赖 PyQt5 |
| `启动GUI.py` | 271 B | 旧版「双击即启动」 | **已失效**，改用根目录 `start_gui.py` / `run_gui.bat` |
| `example_gui_usage.py` | 6,495 B | 6 个调用示例（打印为主） | 独立脚本 |
| `check_dependencies.py` | 1,667 B | 依赖是否装齐 | 已被 `requirements.txt` + `pip install -r` 取代 |
| `install_dependencies.py` | 1,856 B | 自动 pip 安装依赖 | 同上；**归档后不要执行**（会真装包） |

合计 11 个脚本、19,769 字节。

## 现役工具在哪儿

| 需求 | 用这个（**权威**） |
|---|---|
| 回归测试（19 项，不依赖 pytest） | `python tests\run_regression.py` |
| 单模块专项冒烟 | `tests\test_*_smoke.py`（见 `tests\README.md`） |
| 主题/UI 视觉验收截图 | `tests\shot_dark_theme.py`、`shot_dark_axis.py`、`shot_ui_layout.py` |
| 启动程序 | `python start_gui.py` 或 `run_gui.bat` |
| 装依赖 | `python -m pip install -r requirements.txt` |
| 版本体检 | `python 检查版本一致性.py` |

> `tests\README.md` 里仍写着这些历史脚本的说明（它是并行会话负责的文件，本次未改动）；
> 以本文件为准。
