# -*- coding: utf-8 -*-
"""单色线条图标的加载器（icons\\ 目录下由 ``生成图标.py`` 预生成的 PNG）。

用途
====
界面上的按钮/菜单不再用 emoji（🏠 🌙 ☀️ ❓ 📂 ▶ 💾 📋 …），改成这里统一
提供的线条图标。每套配色两个尺寸：

* 浅色界面 -> ``icons\\<name>_light.png``（48x48，描边 #475569）
* 深色界面 -> ``icons\\<name>_dark.png`` （48x48，描边 #cbd5e1）
* 小尺寸   -> ``icons\\<name>_{light,dark}@24.png``（24x24）

``icon()`` 返回的 QIcon 里同时挂 48 与 24 两档，Qt 按控件实际大小自动挑最
清晰的一张，小按钮上不会糊。

API
===
    ICON_NAMES                     18 个图标名的元组（顺序与 icons\\ 一致）
    icon_path(name, theme, size)   PNG 的绝对路径；找不到返回 None
    icon(name, theme)              QIcon（48/24 两档）；文件缺失返回空 QIcon
    clear_cache()                  清空内部 QIcon 缓存（测试用），返回清了几个

``theme`` 只认 ``"light"`` / ``"dark"``，其它值（含 None、数字）一律按
``"light"`` 处理；``size`` 只认 24 / 48，其它值按 48 处理（返回主图路径）。
所有函数都对异常健壮：路径异常、文件缺失、Qt 构造失败都只记一行
``logging.warning`` 并返回 None / 空 QIcon，绝不往上抛——程序打包成
exe 之后 ``sys._MEIPASS`` 里的资源万一没带上，界面最多少个图标，不能崩。

维护说明
========
图标是**预生成的静态 PNG**：要改风格（线宽、描边色、形状、增删图标），
去改 ``生成图标.py`` 里的画法再重跑 ``python 生成图标.py``，本模块不用动，
它只负责"按 名字 + 主题 找文件并缓存成 QIcon"。

为控制体积，本模块只 import ``pathlib`` 与 ``PyQt5``；项目内的
``gui_components.resource_path`` 是**延迟导入**的（模块级 ``import
gui_components`` 会连带把 matplotlib / numpy 一起拖进来，而本模块
在启动早期就会被 import）。也不 import gui_ui / gui_data / gui_plot
（避免循环导入）。延迟导入失败时只告警并返回空图标，不会崩。
"""

import logging
from pathlib import Path

from PyQt5.QtCore import QSize
from PyQt5.QtGui import QIcon

# 资源定位函数缓存：None = 还没取；False = 取不到（不再重试）
_RESOURCE_PATH = None


def _resolve(name):
    """用 ``gui_components.resource_path`` 定位资源；拿不到函数时返回 None。"""
    global _RESOURCE_PATH
    if _RESOURCE_PATH is None:
        try:
            from gui_components import resource_path
            _RESOURCE_PATH = resource_path
        except Exception:
            logging.warning("图标：导入 gui_components.resource_path 失败，"
                            "图标将不可用", exc_info=True)
            _RESOURCE_PATH = False
    if not _RESOURCE_PATH:
        return None
    return _RESOURCE_PATH(name)

# 与 icons\ 下的文件名一一对应；新增图标要同步改生成图标.py 与本元组
ICON_NAMES = (
    "home", "moon", "sun", "help", "folder_open", "play", "save", "export",
    "image", "images", "copy", "csv", "chart_bar", "pdf", "refresh", "search",
    "select_all", "fit",
)

ICON_DIR = "icons"           # 相对 GUI 根目录（resource_path 的基准）
THEMES = ("light", "dark")
DEFAULT_THEME = "light"
MAIN_SIZE = 48               # 主图尺寸（无后缀）
SMALL_SIZE = 24              # 小尺寸（@24 后缀）
ICON_SIZES = (MAIN_SIZE, SMALL_SIZE)

# (name, theme) -> QIcon：同一组合只构造一次
_CACHE = {}


def _norm_theme(theme):
    """主题名规范化：只认 light / dark，其它一律回退 light。"""
    try:
        t = str(theme).strip().lower()
    except Exception:
        return DEFAULT_THEME
    return t if t in THEMES else DEFAULT_THEME


def _norm_size(size):
    """尺寸规范化：只认 24 / 48，其它（含非法值）按 48 处理。"""
    try:
        s = int(size)
    except Exception:
        return MAIN_SIZE
    return SMALL_SIZE if s == SMALL_SIZE else MAIN_SIZE


def _file_name(name, theme, size):
    suffix = "" if size == MAIN_SIZE else f"@{SMALL_SIZE}"
    return f"{name}_{theme}{suffix}.png"


def icon_path(name, theme="light", size=48):
    """返回图标 PNG 的绝对路径；文件不存在或路径异常时返回 None（不抛异常）。

    ``name`` 不限于 ``ICON_NAMES``（传别的名字就是找不到 -> None）。
    ``size`` 给 24 拿到 @24 那张，其它值拿到 48 主图。
    """
    theme = _norm_theme(theme)
    size = _norm_size(size)
    try:
        fname = _file_name(name, theme, size)
        rel = f"{ICON_DIR}/{fname}"
        found = _resolve(rel)
        if found:
            return str(Path(found).resolve())
        logging.warning("图标资源缺失：%s（name=%r theme=%s size=%d）",
                        rel, name, theme, size)
        return None
    except Exception:
        logging.warning("图标路径解析失败：name=%r theme=%r size=%r",
                        name, theme, size, exc_info=True)
        return None


def icon(name, theme="light"):
    """返回带 48 / 24 两档尺寸的 QIcon；缺文件时返回空 QIcon（不抛异常）。

    结果按 (name, theme) 缓存，重复调用不会重复读盘。
    需要在 QApplication 建好之后调用（QPixmap 依赖 QGuiApplication）。
    """
    theme = _norm_theme(theme)
    try:
        key = (str(name), theme)
    except Exception:
        key = (repr(name), theme)
    cached = _CACHE.get(key)
    if cached is not None:
        return cached

    qi = QIcon()
    try:
        for size in ICON_SIZES:
            path = icon_path(name, theme, size)
            if path:
                qi.addFile(path, QSize(size, size))
        if qi.isNull():
            logging.warning("图标不可用，返回空 QIcon：%s（theme=%s）", name, theme)
    except Exception:
        logging.warning("构造 QIcon 失败：%s（theme=%s）", name, theme,
                        exc_info=True)
        qi = QIcon()
    _CACHE[key] = qi
    return qi


def clear_cache():
    """清空 QIcon 缓存（测试用：换过图标 PNG 或改过主题后可强制重建）。

    返回被清掉的条目数。
    """
    n = len(_CACHE)
    _CACHE.clear()
    return n
