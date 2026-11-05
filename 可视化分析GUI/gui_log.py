# -*- coding: utf-8 -*-
"""日志落盘（D6）。

打包成 --windowed 的 exe 后 stdout/stderr 被重定向到 os.devnull，全项目
``except ...: print(...)`` 等于没有任何提示。本模块把日志写到用户目录下的
滚动文件里，界面上的「打开日志文件夹」直接打开它。

日志位置（Windows）：``%LOCALAPPDATA%\\SpectraLab\\logs\\gui.log``
（每天一个文件：``gui.log``、``gui-2026-09-10.log`` …；单文件 ≤ 2 MB，
保留 3 个历史文件。）

对外接口：
    setup_logging()          初始化（可重复调用，只装一次 handler）
    log_file_path()          当前日志文件路径
    log_dir()                日志目录
    log_exception(msg, exc)  记录一次异常（含堆栈）
    open_log_folder()        在文件管理器里打开日志目录
    install_excepthook()     安装未捕获异常钩子（写日志 + 弹一次提示框）
"""
import logging
import os
import subprocess
import sys
import threading
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path

from gui_config import (
    LOG_APP_DIR, LOG_BACKUP_COUNT, LOG_DIR_NAME, LOG_FILE_NAME,
    LOG_MAX_BYTES, LOGGER_FORMAT, LOGGER_DATEFMT,
)

_lock = threading.Lock()
_initialized = False
_log_path = None
_hook_installed = False
_error_box_shown = False  # 未捕获异常只弹一次，避免连环弹窗


def log_dir():
    """日志目录（Windows: %LOCALAPPDATA%\\SpectraLab\\logs）。"""
    base = os.environ.get('LOCALAPPDATA') or os.environ.get('APPDATA')
    if not base:
        # 非 Windows 或环境变量缺失时的兜底：用户目录下
        base = str(Path.home() / 'AppData' / 'Local') if sys.platform == 'win32' \
            else str(Path.home() / '.local' / 'share')
    return Path(base) / LOG_APP_DIR / LOG_DIR_NAME


def log_file_path():
    """当前日志文件路径（未初始化时也返回预期路径）。"""
    if _log_path:
        return Path(_log_path)
    return log_dir() / LOG_FILE_NAME


def setup_logging(level=logging.INFO):
    """初始化日志（写文件 + 控制台）。可重复调用，只装一次 handler。

    Returns:
        str: 日志文件路径；初始化失败时返回预期路径（不抛异常）。
    """
    global _initialized, _log_path
    with _lock:
        if _initialized:
            return str(log_file_path())
        d = log_dir()
        path = d / LOG_FILE_NAME
        try:
            d.mkdir(parents=True, exist_ok=True)
            # 按天归档：上次运行留下的 gui.log 若跨天，改名为 gui-<日期>.log
            try:
                if path.is_file():
                    import datetime
                    mtime = datetime.date.fromtimestamp(path.stat().st_mtime)
                    if mtime != datetime.date.today():
                        archived = d / f"gui-{mtime.strftime('%Y-%m-%d')}.log"
                        if not archived.exists():
                            path.replace(archived)
            except Exception:
                pass

            handler = RotatingFileHandler(
                str(path), maxBytes=LOG_MAX_BYTES,
                backupCount=LOG_BACKUP_COUNT, encoding='utf-8')
            handler.setFormatter(logging.Formatter(LOGGER_FORMAT, LOGGER_DATEFMT))
            handler.setLevel(level)

            root = logging.getLogger()
            root.setLevel(level)
            # 去掉重复安装（例如 main() 与 entry_gui.main() 都调过）
            for h in list(root.handlers):
                if getattr(h, '_spectra_file_handler', False):
                    root.removeHandler(h)
            handler._spectra_file_handler = True
            root.addHandler(handler)
            _log_path = str(path)

            # 控制台输出：源码运行时便于排查；打包后 stderr 指向 devnull 也不报错
            if not any(getattr(h, '_spectra_stream_handler', False)
                       for h in root.handlers):
                try:
                    sh = logging.StreamHandler(sys.stderr)
                    sh.setFormatter(logging.Formatter(
                        '%(levelname)s: %(message)s'))
                    sh.setLevel(level)
                    sh._spectra_stream_handler = True
                    root.addHandler(sh)
                except Exception:
                    pass
        except Exception:
            # 日志本身失败绝不能影响程序启动
            _log_path = str(path)
        _initialized = True
        return str(_log_path)


def log_exception(msg, exc=None, level=logging.ERROR):
    """记录一次异常（含堆栈）；exc 可以是异常实例、字符串或 None。"""
    setup_logging()
    try:
        if exc is None:
            logging.getLogger('spectra').log(level, "%s", msg)
        elif isinstance(exc, BaseException):
            logging.getLogger('spectra').log(
                level, "%s: %s: %s", msg, type(exc).__name__, exc,
                exc_info=exc)
        else:
            logging.getLogger('spectra').log(level, "%s: %s", msg, exc)
    except Exception:
        pass


def open_log_folder():
    """在文件管理器里打开日志目录（Windows: explorer；macOS: open）。"""
    setup_logging()
    d = log_dir()
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    try:
        if sys.platform == 'win32':
            os.startfile(str(d))  # noqa: S606 (Windows 专用)
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', str(d)])
        else:
            subprocess.Popen(['xdg-open', str(d)])
        return True
    except Exception as e:
        log_exception("打开日志文件夹失败", e)
        return False


def install_excepthook(app=None):
    """安装未捕获异常钩子：写日志 + 弹一次 QMessageBox.critical（含日志路径）。

    app 参数保留给调用方传 QApplication（当前不强制使用）；无 Qt 或未创建
    QApplication 时只写日志，不弹窗。
    """
    global _hook_installed
    setup_logging()
    if _hook_installed:
        return
    _hook_installed = True

    def _hook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        try:
            logging.getLogger('spectra').error(
                "未捕获异常", exc_info=(exc_type, exc_value, exc_tb))
        except Exception:
            pass
        # 弹窗只弹一次（未捕获异常常常连环触发）
        global _error_box_shown
        if _error_box_shown:
            return
        _error_box_shown = True
        try:
            from PyQt5.QtWidgets import QApplication, QMessageBox
            if QApplication.instance() is None:
                return
            detail = ''.join(traceback.format_exception_only(
                exc_type, exc_value)).strip()
            QMessageBox.critical(
                None, "程序错误",
                f"发生未处理的错误：\n{detail}\n\n"
                f"详细信息已写入日志：\n{log_file_path()}\n\n"
                "（可用主界面「帮助 → 打开日志文件夹」查看）")
        except Exception:
            pass

    sys.excepthook = _hook
    # 后台线程里的异常同样进日志（Python 3.8+）
    try:
        def _thread_hook(args):
            logging.getLogger('spectra').error(
                "线程未捕获异常（%s）", getattr(args.thread, 'name', '?'),
                exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
        threading.excepthook = _thread_hook
    except Exception:
        pass
