# -*- coding: utf-8 -*-
"""启动画面：双击启动后第一时间显示的无边框小窗，实时显示加载与依赖检查进度。

注意：本模块只允许依赖 PyQt5 与 gui_config——它存在的意义就是赶在
matplotlib / numpy / scipy / pandas 等重量级库加载之前出现在屏幕上，
在这里导入重量级库会让启动画面失去意义（也不要 import gui_launcher，
那条链会拉进 QtWidgets 之外的一堆东西）。

主题（v4.28）：启动画面出现在入口界面之前，此前只能硬用一套浅色配色，
深色用户每次启动都会先看到一块白卡片。现在**自己读 QSettings 里保存的主题**
（只用到 QtCore.QSettings + gui_config 的色板），浅色/深色会话各自显示对应配色。
"""

import sys
from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QIcon, QPixmap
from PyQt5.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QProgressBar, QVBoxLayout, QWidget,
)

from gui_config import (
    APP_NAME, APP_VERSION, APP_ICON_FILENAME, UI_FONT_FAMILY,
    APP_ORG, THEMES, DEFAULT_THEME,
)


def _resource_path(name):
    """定位资源文件（打包后 sys._MEIPASS / 源码运行脚本目录），与 gui_components 同逻辑但保持零重依赖。"""
    candidates = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / name)
    candidates.append(Path(__file__).resolve().parent / name)
    for c in candidates:
        try:
            if c.is_file():
                return str(c)
        except Exception:
            pass
    return None


def saved_theme(default=None):
    """读取上次会话保存的主题（与 gui_launcher.saved_theme 同义，但保持零重依赖）。

    QSettings 读失败（注册表被限制、键不存在等）一律回退，绝不抛异常——
    启动画面挂了会直接导致程序打不开。

    v4.46：没有保存过主题时（首次启动）跟随操作系统深浅色，
    避免深色用户第一次启动先看到一块白色启动画面。
    """
    try:
        from PyQt5.QtCore import QSettings
        if default is None:
            try:
                from gui_config import detect_system_theme
                default = detect_system_theme()
            except Exception:
                default = DEFAULT_THEME
        t = QSettings(APP_ORG, APP_NAME).value("theme", default, str)
        return t if t in THEMES else default
    except Exception:
        return default or DEFAULT_THEME


class StartupSplash(QWidget):
    """无边框启动画面：标题 + 动态状态行 + 不确定进度条。

    用法:
        splash = StartupSplash()          # theme 留空 = 读上次会话的主题
        splash.show_centered()
        splash.stage("正在加载 …")         # 每个阶段调用，立即重绘
        splash.finish()                   # 主界面就绪后关闭
    """

    def __init__(self, theme=None):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.theme = theme if theme in THEMES else saved_theme()
        P = THEMES[self.theme]
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(500, 280)

        card = QFrame(self)
        card.setObjectName("splashCard")
        card.setGeometry(0, 0, self.width(), self.height())
        # 配色全部来自 theme_palette（不再硬编码浅色）
        card.setStyleSheet(f"""
            QFrame#splashCard {{
                background-color: {P['CARD']};
                border: 1px solid {P['BORDER']};
                border-top: 5px solid {P['ACCENT']};
                border-radius: 14px;
            }}
        """)

        lay = QVBoxLayout(card)
        lay.setContentsMargins(32, 26, 32, 18)
        lay.setSpacing(12)

        # 标题行：图标 + 应用名
        head = QHBoxLayout()
        head.setSpacing(12)
        icon_path = _resource_path(APP_ICON_FILENAME)
        icon_label = QLabel()
        if icon_path:
            pm = QPixmap(icon_path)
            if not pm.isNull():
                icon_label.setPixmap(pm.scaled(44, 44, Qt.KeepAspectRatio,
                                               Qt.SmoothTransformation))
            self.setWindowIcon(QIcon(icon_path))
        head.addWidget(icon_label)
        title = QLabel(APP_NAME)
        f = QFont(UI_FONT_FAMILY)
        f.setPointSize(15)
        f.setBold(True)
        title.setFont(f)
        title.setStyleSheet(f"color: {P['TEXT']}; background: transparent;")
        head.addWidget(title)
        version = QLabel(f"v{APP_VERSION}")
        version.setStyleSheet(
            f"font-size: 13px; font-weight: bold; color: {P['SELECT_FG']};"
            f"background-color: {P['SELECT_BG']}; border-radius: 10px;"
            "padding: 3px 10px;")
        head.addStretch()
        head.addWidget(version)
        lay.addLayout(head)

        subtitle = QLabel("正在准备运行环境")
        subtitle.setStyleSheet(
            f"font-size: 13px; color: {P['MUTED']}; background: transparent;")
        lay.addWidget(subtitle)

        # 动态状态行（各阶段更新）
        self.status = QLabel("正在初始化…")
        self.status.setWordWrap(True)
        self.status.setStyleSheet(
            f"font-size: 15px; font-weight: bold; color: {P['ACCENT']};"
            "background: transparent;")
        lay.addWidget(self.status)

        # 不确定进度条（细条）
        bar = QProgressBar()
        bar.setRange(0, 0)
        bar.setFixedHeight(8)
        bar.setTextVisible(False)
        bar.setStyleSheet(f"""
            QProgressBar {{
                background-color: {P['DISABLED_BG']};
                border: none;
                border-radius: 4px;
                max-height: 8px;
            }}
            QProgressBar::chunk {{
                background-color: {P['ACCENT']};
                border-radius: 4px;
            }}
        """)
        lay.addWidget(bar)

        hint = QLabel("首次启动需要解压资源并检查依赖（约 20–40 秒），\n启动画面消失前请勿重复双击。")
        hint.setStyleSheet(
            f"font-size: 12px; color: {P['MUTED']}; background: transparent;")
        lay.addWidget(hint)
        lay.addStretch()

    def show_centered(self):
        """显示并居中到主屏幕"""
        self.show()
        screen = QApplication.primaryScreen()
        if screen is not None:
            geom = self.frameGeometry()
            geom.moveCenter(screen.availableGeometry().center())
            self.move(geom.topLeft())
        self.repaint()

    def stage(self, text):
        """更新阶段文字并立即重绘（随后的重量级导入会阻塞事件循环）"""
        self.status.setText(text)
        self.repaint()

    def finish(self):
        """关闭启动画面"""
        self.close()
