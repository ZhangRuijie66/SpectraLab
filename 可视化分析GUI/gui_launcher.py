# -*- coding: utf-8 -*-
"""入口界面：启动时选择功能模块，再进入对应模式的主窗口。"""

import logging

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor, QIcon
from PyQt5.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QMessageBox, QVBoxLayout,
)

from gui_config import (
    APP_NAME, APP_VERSION, APP_ICON_FILENAME, RELEASE_DATE,
    DEFAULT_THEME, THEMES,
    COLOR_BG, COLOR_BORDER, COLOR_TEXT, COLOR_TEXT_SOFT, COLOR_MUTED,
    ACCENT, SUCCESS, VIOLET, CYAN,
)
from gui_components import resource_path


def _hex_to_rgba(hexc, alpha):
    """'#RRGGBB' → 'rgba(r, g, b, a)' 字符串（供 QSS 背景色使用）"""
    c = QColor(hexc)
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, {alpha})"


def saved_theme(default=None):
    """读取上次会话保存的主题（v4.23 / v4.46 增强）。

    启动时入口界面在「上次会话」之前出现，此前只能硬用默认浅色主题——
    深色用户每次启动都会看到一块全白入口界面，连标题栏「？」里的
    帮助也都是白的。这里直接读 QSettings 里的 theme 保持一致。

    v4.46：**没有保存过主题时（首次启动）跟随操作系统深浅色**，
    而不是硬用 light。Windows 深色模式的用户第一次打开就能看到深色界面，
    不需要先手动按 Ctrl+T。`default` 参数传 None 表示"按系统探测"，
    显式传值则优先用传入值（旧调用方语义不变）。
    """
    try:
        from PyQt5.QtCore import QSettings
        from gui_config import APP_ORG, APP_NAME, detect_system_theme
        fallback = default if default is not None else detect_system_theme()
        t = QSettings(APP_ORG, APP_NAME).value("theme", fallback, str)
        return t if t in THEMES else fallback
    except Exception:
        try:
            from gui_config import detect_system_theme
            return detect_system_theme()
        except Exception:
            return DEFAULT_THEME


class ModuleCard(QFrame):
    """入口界面的模块卡片：圆角卡片 + 左侧彩色竖条，悬停时整卡亮起。

    相比整块纯色大按钮，卡片式设计信息层级更清晰（标题/描述分行、配色克制）。
    v4.28：左侧图标从 emoji 换成单色图标集（`icons\\<name>_<theme>.png`），
    跟随当前主题取浅色/深色两套描边色。
    """

    clicked = pyqtSignal()

    def __init__(self, icon_name, title, desc, color, parent=None,
                 palette=None, theme="light"):
        super().__init__(parent)
        P = palette or THEMES[DEFAULT_THEME]
        card_bg = P['CARD']
        border = P['BORDER']
        text = P['TEXT']
        muted = P['MUTED']
        self.setCursor(Qt.PointingHandCursor)
        self.setObjectName("moduleCard")
        self.setMinimumHeight(78)
        self.setStyleSheet(f"""
            QFrame#moduleCard {{
                background-color: {card_bg};
                border: 1px solid {border};
                border-left: 5px solid {color};
                border-radius: 10px;
            }}
            QFrame#moduleCard:hover {{
                background-color: {_hex_to_rgba(color, 0.06)};
                border: 1px solid {color};
                border-left: 5px solid {color};
            }}
        """)

        row = QHBoxLayout(self)
        row.setContentsMargins(18, 10, 14, 10)
        row.setSpacing(14)

        icon_label = QLabel()
        icon_label.setFixedSize(28, 28)
        icon_label.setStyleSheet("background: transparent; border: none;")
        self._icon_label = icon_label
        self.set_mode_icon(icon_name, theme)
        row.addWidget(icon_label)

        text_col = QVBoxLayout()
        text_col.setSpacing(3)
        title_label = QLabel(title)
        title_label.setStyleSheet(
            f"font-size: 16px; font-weight: bold; color: {text};"
            "background: transparent; border: none;")
        desc_label = QLabel(desc)
        desc_label.setStyleSheet(
            f"font-size: 13px; color: {muted}; background: transparent;"
            "border: none;")
        text_col.addWidget(title_label)
        text_col.addWidget(desc_label)
        row.addLayout(text_col, 1)

        # 右侧箭头提示可点击
        arrow = QLabel("›")
        arrow.setStyleSheet(
            f"font-size: 26px; color: {COLOR_MUTED}; background: transparent; border: none;")
        row.addWidget(arrow)

    def set_mode_icon(self, name, theme="light"):
        """设置卡片图标（单色图标集，v4.28）。

        图标集缺失时退回一个中性占位点——入口界面绝不能因为少一张图就崩。
        """
        try:
            from gui_icons import icon
            qi = icon(name, theme)
            if not qi.isNull():
                self._icon_label.setPixmap(qi.pixmap(26, 26))
                return
        except Exception as e:
            logging.warning("入口卡片图标加载失败（%s）：%s", name, e)
        self._icon_label.setText("·")

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.pos()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class ModuleLauncher(QDialog):
    """模块选择对话框：吸收光谱 / 发射光谱 / 荧光寿命，选择后进入主窗口。

    用法:
        launcher = ModuleLauncher()
        if launcher.exec_() == QDialog.Accepted:
            window = AbsorptionGUI(initial_mode=launcher.selected_mode)
    用户关闭对话框（Esc/右上角×）时 exec_() 返回 Rejected，程序应直接退出。
    """

    # (模式标识, 图标名, 按钮主标题, 一句话说明, 主色)
    # 图标名对应 icons\<name>_<theme>.png（v4.28 起用单色图标集，原来是 emoji）
    # 主色直接取设计令牌（v4.30 收敛：原来这里写死 #2563EB/#16A34A/#7C3AED/#0891B2，
    # 和 gui_config 里的 ACCENT/SUCCESS/VIOLET/CYAN 是同一组值、改一处会漏另一处）
    MODES = [
        ("absorption", "mode_absorb", "吸收光谱 (UV-Vis)",
         "紫外-可见吸收光谱绘图与峰标注", ACCENT),
        ("emission", "mode_emit", "发射光谱 (Emission)",
         "荧光发射光谱绘图、EX 标注与归一化", SUCCESS),
        ("lifetime", "mode_lifetime", "荧光寿命 (Lifetime)",
         "最大熵寿命拟合（MEM/SESM）与分量分解", VIOLET),
        ("scan3d", "mode_3d", "3D 扫描 (EEM)",
         "激发-发射矩阵曲面/等高线/Waterfall，自动去除周期梳状伪迹", CYAN),
    ]

    def __init__(self, parent=None, theme=None):
        super().__init__(parent)
        self.selected_mode = None
        # 跟随主窗口当前主题：深色会话里点「返回模块选择」不该弹出一块全白界面；
        # 启动时 theme 为 None，退回**上次会话保存的主题**（v4.23）
        self.theme = theme if theme in THEMES else saved_theme()
        P = THEMES[self.theme]
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION} — 选择模块")
        try:
            icon_path = resource_path(APP_ICON_FILENAME)
            if icon_path:
                self.setWindowIcon(QIcon(icon_path))
        except Exception:
            pass
        self.setMinimumWidth(520)
        self.setStyleSheet(f"QDialog {{ background-color: {P['BG']}; }}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 18)
        layout.setSpacing(14)

        # 顶部：应用名 + 版本徽标 + 副标题
        header = QHBoxLayout()
        app_title = QLabel(APP_NAME)
        app_title.setStyleSheet(
            f"font-size: 24px; font-weight: bold; color: {P['TEXT']};")
        header.addWidget(app_title)
        header.addStretch()
        version_chip = QLabel(f"v{APP_VERSION}")
        version_chip.setStyleSheet(
            f"font-size: 13px; font-weight: bold; color: {P['SELECT_FG']};"
            f"background-color: {P['SELECT_BG']}; border-radius: 10px;"
            "padding: 4px 12px;")
        header.addWidget(version_chip)
        layout.addLayout(header)

        subtitle = QLabel("请选择要使用的模块")
        subtitle.setStyleSheet(f"font-size: 15px; color: {P['MUTED']};")
        layout.addWidget(subtitle)

        # 分隔细线
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet(f"color: {P['BORDER']}; background-color: {P['BORDER']};"
                           "max-height: 1px; border: none;")
        layout.addWidget(line)

        # 模块卡片
        for mode, icon_name, name, desc, color in self.MODES:
            card = ModuleCard(icon_name, name, desc, color, palette=P,
                              theme=self.theme)
            card.clicked.connect(lambda m=mode: self._choose(m))
            layout.addWidget(card)

        hint = QLabel("进入主窗口后仍可通过左上角「光谱类型」下拉框切换模块")
        hint.setStyleSheet(f"color: {P['MUTED']}; font-size: 13px;")
        hint.setAlignment(Qt.AlignCenter)
        layout.addWidget(hint)

        # 标题栏自带的「？」按键（Qt 的上下文帮助按键）：拦截它来显示帮助/关于
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, True)

        self._help_text = f"""
        <p><b>更新日期：</b>{RELEASE_DATE}</p>
        <p><b>创建人：</b>张瑞杰</p>
        <p><b>包含模块：</b></p>
        <ul>
          <li>吸收光谱 (UV-Vis) —— 紫外-可见吸收光谱绘图与峰标注</li>
          <li>发射光谱 (Emission) —— 荧光发射光谱绘图、EX 标注与归一化</li>
          <li>荧光寿命 (Lifetime) —— 最大熵寿命拟合（MEM/SESM）与分量分解</li>
          <li>3D 扫描 (EEM) —— 激发-发射矩阵曲面/等高线/Waterfall，自动去周期梳状伪迹</li>
        </ul>
        <p>进入主窗口后按 <b>F1</b> 可查看当前模式的完整说明与全部快捷键。</p>
        """

    def event(self, e):
        """拦截标题栏「？」（进入 What's-This 模式事件），改为弹出帮助/关于"""
        from PyQt5.QtCore import QEvent
        if e.type() == QEvent.EnterWhatsThisMode:
            self.show_help()
            return True  # 不进入 What's-This 模式
        return super().event(e)

    def show_help(self):
        """帮助 / 关于（v4.24）：改为主题化可滚动窗口，深色下不再是一块白板"""
        try:
            from gui_help import show_help_dialog
            from gui_log import log_dir
            return show_help_dialog(
                self,
                title=f"帮助 — {APP_NAME}",
                sections=[("关于本工具", self._help_text)],
                palette=THEMES[self.theme],
                subtitle=f"v{APP_VERSION} · {RELEASE_DATE}",
                log_text=f"日志目录：{log_dir()}")
        except Exception as e:                      # 兜底：绝不因帮助起不来而崩
            logging.warning("打开帮助窗口失败: %s", e)

    def _choose(self, mode):
        self.selected_mode = mode
        self.accept()
