# `docs\_archive\` —— v2.x 时代文档（**已过期，仅存档**）

> **v2.x 时代文档，已过期，仅存档。** 请勿据此操作，现状以 `docs\用户手册.md`、
> `docs\环境说明.md` 和 `更新日志\CHANGELOG_v*.md` 为准。

归档日期：2026-09-09（仓库清理 F5）。
来源：`docs\` 根目录；本目录 **只移动、不删除**。
合计 22 个文件、100,018 字节。

## 为什么归档

这批文档写于 **2026-08-26 ~ 08-29**（v2.x 时代），当时程序还只有「吸收光谱」一个模式、
启动方式靠 `启动GUI.py`、依赖靠手写 `install_dependencies.py`。它们记录的是当时
「PyQt5 装不上 / 数据加载失败 / GUI 起不来」的排查过程，**与 v4.20 现状严重脱节**：

| 文档里的说法（v2.x） | v4.20 现状 |
|---|---|
| 「当前版本 v2.4」 | v4.20（`gui_config.APP_VERSION`） |
| 只有吸收模式 | 吸收 / 发射 / 荧光寿命 / 3D 扫描（EEM）四个模式 + 模块选择器 |
| 双击 `run_gui.bat` 或 `启动GUI.py` | `start_gui.py` / `run_gui.bat`；`启动GUI.py` 已失效并移入 `tests\_archive\` |
| 手动 `pip install` 一堆包 | `python -m pip install -r requirements.txt`（8 个直接依赖） |
| 没有打包 | `打包便携版.ps1` → `便携版\光谱可视化分析工具.exe`（单文件，约 101.6 MiB） |

考古价值仍在（能查到当年某个报错的根因），所以**不删**，只是不再出现在 docs 根目录。

## 清单

| 文件 | 大小 | 原用途 |
|---|---|---|
| `BUGFIX.md` | 3,117 B | 第 1 轮启动/加载 bug 修复记录 |
| `BUGFIX_v2.md` | 3,572 B | 第 2 轮修复 |
| `BUGFIX_v3.md` | 3,910 B | 第 3 轮修复 |
| `BUGFIX_v4.md` | 4,712 B | 第 4 轮修复 |
| `BUGFIX_v5.md` | 2,992 B | 第 5 轮修复 |
| `FINAL_FIX.md` | 4,054 B | 修复收尾记录 |
| `FINAL_GUIDE.md` | 3,451 B | 早期使用指南 |
| `GUI_LAUNCH.md` | 1,922 B | 旧版启动方式说明 |
| `GUI_README.md` | 7,434 B | 旧版完整使用指南（当时号称「推荐」） |
| `GUI_SUCCESS.md` | 6,434 B | 早期「跑通」验收记录 |
| `GUI_SUMMARY.md` | 9,224 B | 早期开发总结 |
| `INSTALL.md` | 3,637 B | 旧版安装说明 |
| `LAUNCH_FIXED.md` | 3,288 B | 启动修复说明 |
| `LAUNCH_GUIDE.md` | 3,121 B | 旧版启动指南 |
| `PROJECT_COMPLETE.md` | 9,810 B | 早期完工报告 |
| `QUICKSTART.md` | 2,244 B | 旧版快速开始 |
| `QUICK_REFERENCE.md` | 2,456 B | 旧版速查卡片 |
| `README_GUI.md` | 4,554 B | 旧版 GUI README |
| `README_文件夹说明.md` | 3,770 B | v2.4 时代的目录结构说明（当时版本 v2.4） |
| `README_目录整理.md` | 9,036 B | 2026-09-07 那次（E1）目录整理的说明；**是这批里最新的**，但其中的文件清单已被 F3/F5 清理改变，结构描述见 `docs\环境说明.md` 第 8 节 |
| `SOLUTION.md` | 3,482 B | 启动问题解决方案 |
| `TROUBLESHOOTING.md` | 3,798 B | 旧版排障手册 |

## 保留在 `docs\` 的（现役）

| 文件 | 说明 |
|---|---|
| `用户手册.md` | **v4.20 现行功能手册**（本次新建，最权威） |
| `环境说明.md` | Python 环境、依赖、打包命令、从零重建（含目录结构第 8 节） |
| `run_gui_debug.bat` / `run_gui_en.bat` / `run_gui_v2.bat` | 旧启动批处理（不在本次归档清单里，保留原位；现役入口是根目录 `run_gui.bat` / `run_gui.ps1`） |
