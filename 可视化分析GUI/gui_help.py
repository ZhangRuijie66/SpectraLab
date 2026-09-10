# -*- coding: utf-8 -*-
"""主题化帮助窗口（gui_help）。

取代原来的 ``QMessageBox.about(self, "帮助 — …", 大段HTML)``：那是一次性弹窗，
尺寸固定（实测 722×600 逻辑像素），长了就溢出、不能滚动也**不能复制**，
深色主题下还只能跟随系统调色板。

本模块提供一个**非模态、可滚动、可复制**的帮助窗口：
左侧小节目录（点击跳转）+ 右侧 QTextBrowser 正文 + 顶部搜索框 +
底部「复制全部 / 打开日志文件夹 / 关闭」。全部颜色来自调用方传入的色板
（``gui_config.THEMES[theme]``），**模块内不硬编码任何颜色值**，所以深色
主题下不会出现白块。

对外接口：
    HelpDialog(parent, title, sections, palette, subtitle, log_text,
               default_size, remember_geometry)
        帮助窗口本体；``sections`` 是 ``[(小节标题, HTML 正文), ...]``，
        正文由调用方给（本模块不含任何业务文案）。
    show_help_dialog(parent, title, sections, palette, subtitle, log_text)
        构造并**非模态**显示（挂到 ``parent._help_dialog`` 防止被 GC）；
        已有可见窗口且内容未变时只提到前台（主题色板变了会调
        ``apply_palette`` 重刷样式表），内容变了则重建。
    HelpDialog.apply_palette(palette)
        给已存在的窗口换主题色板（重设样式表 + 重渲染正文）。

用法示例（调用方在 ``gui_ui.show_help()`` / ``gui_launcher.show_help()`` 里）：

    from gui_help import show_help_dialog
    show_help_dialog(
        self,
        title=f"帮助 — {APP_NAME}",
        sections=[("快捷键", "<p>F5 — 实时预览 …</p>"),
                  ("数据格式", "<p>…</p>")],
        palette=self.theme_palette(),          # = THEMES[self.theme]
        subtitle=f"v{APP_VERSION} · {RELEASE_DATE}",
        log_text=str(log_dir()),
    )

健壮性：剪贴板 / QSettings / 日志目录任何一步失败都只写 ``logging.warning``，
绝不让窗口起不来（打包成 exe 后 stdout 被丢弃，故不用 print）。
"""
import html
import logging

from PyQt5.QtCore import Qt, QSettings, QSize, QTimer
from PyQt5.QtGui import QTextCursor
from PyQt5.QtWidgets import (
    QApplication, QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QTextBrowser, QVBoxLayout,
)

from gui_config import APP_NAME, APP_ORG, APP_ICON_FILENAME, DEFAULT_THEME, THEMES

__all__ = ["HelpDialog", "show_help_dialog"]

_logger = logging.getLogger(__name__)

# QSettings 里记住窗口尺寸用的组名（键：help_dialog/<标题>）
_SETTINGS_GROUP = "help_dialog"

# 最近一次创建的窗口（parent 为 None 时靠它兜住引用，避免被 GC 掉）
_LAST_DIALOG = None


def _safe_key(name):
    """把窗口标题转成安全的 QSettings 键（斜杠在 QSettings 里是分组分隔符）。"""
    try:
        key = "".join(ch if (ch.isalnum() or ch in "-_") else "_"
                      for ch in str(name))
        return key or "help"
    except Exception:
        return "help"


def _to_size(value):
    """把 QSettings 读出来的值转成 QSize；无法解析时返回 None。"""
    try:
        if value is None:
            return None
        if isinstance(value, QSize):
            return value if value.isValid() else None
        txt = str(value).strip()
        if not txt:
            return None
        for sep in ("x", "X", ",", " "):
            if sep in txt:
                parts = [p for p in txt.split(sep) if p.strip()]
                if len(parts) >= 2:
                    return QSize(int(float(parts[0])), int(float(parts[1])))
        return None
    except Exception:
        return None


def _sections_key(sections):
    """小节的规范化指纹，用来判断「内容是否变了」。"""
    try:
        return tuple((str(t), str(b)) for t, b in (sections or []))
    except Exception:
        return tuple()


def _icon_theme(palette):
    """按背景色亮度判断该用哪套图标（浅色/深色图标描边色不同，v4.28）。

    调用方只传色板、没有主题名，所以直接算背景色亮度：>0.5 视为浅色底。
    解析失败一律按浅色处理。
    """
    try:
        h = str((palette or {}).get('BG', '') or '').lstrip('#')
        if len(h) >= 6:
            r, g, b = (int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
            return 'light' if (0.299 * r + 0.587 * g + 0.114 * b) > 0.5 else 'dark'
    except Exception:
        pass
    return 'light'


def _palette_key(palette):
    """色板指纹，用来判断「主题是否变了」（变了必须重刷样式表）。"""
    if not palette:
        return None
    try:
        return tuple(sorted((str(k), str(v)) for k, v in dict(palette).items()))
    except Exception:
        return None


class HelpDialog(QDialog):
    """主题化帮助窗口：左侧目录 + 右侧可滚动正文 + 复制/日志/搜索。

    非模态（``show()``），用户可以一边看图一边查帮助。窗口尺寸可选记忆
    （``QSettings(APP_ORG, APP_NAME)``，键 ``help_dialog/<标题>``）。
    """

    def __init__(self, parent=None, title="帮助", sections=None,
                 palette=None, subtitle="", log_text="",
                 default_size=(720, 560), remember_geometry=True):
        """
        Args:
            parent: 父窗口（可为 None）
            title: 窗口标题
            sections: [("小节标题", "HTML 正文"), ...]  —— 正文由调用方给，
                模块内不要硬编码业务文案
            palette: gui_config.THEMES[theme] 色板 dict；为 None 时用
                THEMES[DEFAULT_THEME]（缺失的键用默认色板补齐，防止局部色板 KeyError）
            subtitle: 标题右侧的副标题（例如 "v4.24 · 2026-09-10"）
            log_text: 底部显示的日志路径文字（空串则不显示该行）
            default_size: (宽, 高) 初始尺寸，可缩放
            remember_geometry: True 时用 QSettings(APP_ORG, APP_NAME) 记住并恢复尺寸
        """
        super().__init__(parent)
        # 色板：以默认主题为底，再用传入色板覆盖（传入不全也不会 KeyError）。
        # 注意不要命名成 self.palette —— QWidget.palette() 是 Qt 自带方法。
        base = dict(THEMES.get(DEFAULT_THEME, {}))
        if palette:
            try:
                base.update(dict(palette))
            except Exception as e:
                _logger.warning("帮助窗口色板无效，退回默认主题：%s", e)
        self._P = base
        self._palette_key = _palette_key(palette)

        self.title_text = str(title or "帮助")
        self.subtitle_text = str(subtitle or "")
        self.log_text = str(log_text or "")
        self.sections = [(str(t), str(b)) for t, b in (sections or [])]
        self.default_size = tuple(default_size)

        self.setWindowTitle(self.title_text)
        # 非模态：边看图边查帮助；自己带标题栏
        self.setModal(False)
        try:
            self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        except Exception:
            pass
        self.setSizeGripEnabled(True)
        self.setMinimumSize(460, 340)

        self._settings = None
        self._geo_key = None
        try:
            self.resize(int(default_size[0]), int(default_size[1]))
        except Exception:
            self.resize(720, 560)
        # 恢复上次尺寸：任何失败都退回 default_size，不影响窗口起不来
        if remember_geometry:
            try:
                self._settings = QSettings(APP_ORG, APP_NAME)
                self._geo_key = f"{_SETTINGS_GROUP}/{_safe_key(self.title_text)}"
                saved = _to_size(self._settings.value(self._geo_key))
                if saved is not None and saved.width() >= 460 and saved.height() >= 340:
                    self.resize(saved)
            except Exception as e:
                self._settings = None
                _logger.warning("恢复帮助窗口尺寸失败：%s", e)

        # 「已复制」提示的定时器：挂在窗口上，窗口销毁时一起没了（不会回调到野指针）
        self._copy_timer = QTimer(self)
        self._copy_timer.setSingleShot(True)
        self._copy_timer.timeout.connect(self._restore_copy_button)
        self._copy_default_text = "复制全部"

        self._build_ui()
        try:
            self.setStyleSheet(self._build_qss())
        except Exception as e:
            _logger.warning("帮助窗口样式表构建失败：%s", e)

        self._render_sections()

    # ------------------------------------------------------------------ 界面
    def _build_ui(self):
        """搭界面：标题 / 副标题 → 搜索框 → 目录 + 正文 → 日志行 → 按钮行。"""
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(10)

        # ---- 顶部：标题（16px 加粗）+ 副标题（12px、MUTED）----
        head = QHBoxLayout()
        head.setSpacing(10)
        self.title_label = QLabel(self.title_text)
        self.title_label.setObjectName("helpTitle")
        head.addWidget(self.title_label)
        self.subtitle_label = None
        if self.subtitle_text:
            self.subtitle_label = QLabel(self.subtitle_text)
            self.subtitle_label.setObjectName("helpSubtitle")
            head.addWidget(self.subtitle_label, 0, Qt.AlignBottom)
        head.addStretch(1)
        root.addLayout(head)

        # ---- 搜索框（正文上方）----
        search_row = QHBoxLayout()
        search_row.setSpacing(8)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("搜索帮助内容…")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._on_search_changed)
        search_row.addWidget(self.search_edit, 1)
        self.search_hint = QLabel("")
        self.search_hint.setObjectName("helpHintLabel")
        search_row.addWidget(self.search_hint)
        root.addLayout(search_row)

        # ---- 中部：左侧目录 + 右侧正文 ----
        body = QHBoxLayout()
        body.setSpacing(12)

        self.toc = QListWidget()
        self.toc.setFixedWidth(148)          # 固定宽约 148px
        self.toc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.toc.setUniformItemSizes(True)
        self.toc.currentRowChanged.connect(self._on_toc_changed)
        for i, (sec_title, _body) in enumerate(self.sections):
            item = QListWidgetItem(sec_title)
            item.setTextAlignment(Qt.AlignCenter)
            item.setToolTip(sec_title)       # 标题过长被省略时看完整文字
            self.toc.addItem(item)
        body.addWidget(self.toc)

        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(True)
        self.browser.setOpenLinks(True)
        self.browser.setMinimumHeight(240)
        body.addWidget(self.browser, 1)
        root.addLayout(body, 1)

        # ---- 底部：日志路径（空串则整行不显示）----
        self.log_label = None
        if self.log_text:
            self.log_label = QLabel(f"日志：{self.log_text}")
            self.log_label.setObjectName("helpHintLabel")
            self.log_label.setWordWrap(True)
            # 路径可以手工选中复制
            self.log_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            root.addWidget(self.log_label)

        # ---- 底部一行：复制全部 / 打开日志文件夹 / 右侧 关闭 ----
        foot = QHBoxLayout()
        foot.setSpacing(8)
        self.copy_btn = QPushButton(self._copy_default_text)
        self.copy_btn.setProperty("variant", "primary")
        self.copy_btn.setCursor(Qt.PointingHandCursor)
        self.copy_btn.setToolTip("把全部帮助正文以纯文本复制到剪贴板")
        self.copy_btn.clicked.connect(self.copy_all_text)
        foot.addWidget(self.copy_btn)

        self.log_btn = QPushButton("打开日志文件夹")
        self.log_btn.setCursor(Qt.PointingHandCursor)
        self.log_btn.setToolTip(self.log_text or "打开日志目录")
        self.log_btn.clicked.connect(self.open_log_folder)
        foot.addWidget(self.log_btn)

        foot.addStretch(1)
        self.close_btn = QPushButton("关闭")
        self.close_btn.setCursor(Qt.PointingHandCursor)
        self.close_btn.clicked.connect(self.close)
        foot.addWidget(self.close_btn)
        root.addLayout(foot)
        self._apply_icons()          # 按钮图标（v4.28：单色图标集，分深浅两套）

        # 窗口图标（缺失就算了，不影响显示）
        try:
            from gui_components import resource_path
            from PyQt5.QtGui import QIcon
            icon_path = resource_path(APP_ICON_FILENAME)
            if icon_path:
                self.setWindowIcon(QIcon(icon_path))
        except Exception as e:
            _logger.warning("帮助窗口图标加载失败：%s", e)

    def _build_qss(self):
        """用传入色板拼样式表（深色主题下不能残留任何浅色硬编码）。

        说明：主色按钮的文字颜色取 ``CARD``——浅色主题下即白色（对 #2563EB
        约 4.8:1），深色主题下是一片深蓝（对 #3b82f6 约 4.5:1），两种主题
        都够读，又完全由色板决定。
        """
        P = self._P
        BG = P['BG']
        CARD = P['CARD']
        BORDER = P['BORDER']
        INPUT_BORDER = P.get('INPUT_BORDER', BORDER)
        TEXT = P['TEXT']
        MUTED = P['MUTED']
        ACCENT = P['ACCENT']
        ACCENT_HOVER = P.get('ACCENT_HOVER', ACCENT)
        ACCENT_PRESSED = P.get('ACCENT_PRESSED', ACCENT)
        HOVER_BG = P.get('HOVER_BG', CARD)
        SELECT_BG = P.get('SELECT_BG', CARD)
        SELECT_FG = P.get('SELECT_FG', TEXT)
        DISABLED_BG = P.get('DISABLED_BG', CARD)
        DISABLED_FG = P.get('DISABLED_FG', MUTED)
        HANDLE = P.get('HANDLE', BORDER)
        HANDLE_HOVER = P.get('HANDLE_HOVER', MUTED)
        TOOLTIP_BG = P.get('TOOLTIP_BG', CARD)
        TOOLTIP_FG = P.get('TOOLTIP_FG', TEXT)
        return f"""
            /* ===== 窗口底色 ===== */
            QDialog {{
                background-color: {BG};
            }}
            QToolTip {{
                background-color: {TOOLTIP_BG};
                color: {TOOLTIP_FG};
                border: none;
                padding: 6px 10px;
                border-radius: 6px;
                font-size: 12px;
            }}

            /* ===== 文字：正文 13px、次级 12px ===== */
            QLabel {{
                color: {TEXT};
                font-size: 13px;
                background: transparent;
                border: none;
            }}
            QLabel#helpTitle {{
                font-size: 16px;
                font-weight: bold;
                color: {TEXT};
            }}
            QLabel#helpSubtitle {{
                font-size: 12px;
                color: {MUTED};
            }}
            QLabel#helpHintLabel {{
                font-size: 12px;
                color: {MUTED};
            }}

            /* ===== 左侧目录（小节列表）===== */
            QListWidget {{
                background-color: {CARD};
                color: {TEXT};
                border: 1px solid {BORDER};
                border-radius: 8px;
                padding: 4px;
                outline: 0;
                font-size: 13px;
            }}
            QListWidget::item {{
                padding: 7px 6px;
                border-radius: 6px;
                color: {TEXT};
            }}
            QListWidget::item:hover {{
                background-color: {HOVER_BG};
            }}
            QListWidget::item:selected {{
                background-color: {SELECT_BG};
                color: {SELECT_FG};
            }}

            /* ===== 右侧正文（可滚动、可选择复制）===== */
            QTextBrowser {{
                background-color: {CARD};
                color: {TEXT};
                border: 1px solid {BORDER};
                border-radius: 8px;
                padding: 8px 10px;
                font-size: 13px;
                selection-background-color: {SELECT_BG};
                selection-color: {SELECT_FG};
            }}

            /* ===== 搜索框 ===== */
            QLineEdit {{
                background-color: {CARD};
                color: {TEXT};
                border: 1px solid {INPUT_BORDER};
                border-radius: 6px;
                padding: 5px 8px;
                font-size: 13px;
            }}
            QLineEdit:hover {{
                border-color: {HANDLE_HOVER};
            }}
            QLineEdit:focus {{
                border-color: {ACCENT};
            }}

            /* ===== 按钮：卡片底 + 1px 描边；主色按钮用 ACCENT ===== */
            QPushButton {{
                background-color: {CARD};
                color: {TEXT};
                border: 1px solid {INPUT_BORDER};
                border-radius: 8px;
                padding: 7px 14px;
                font-size: 13px;
            }}
            QPushButton:hover {{
                background-color: {HOVER_BG};
                border-color: {HANDLE_HOVER};
            }}
            QPushButton:pressed {{
                background-color: {DISABLED_BG};
            }}
            QPushButton:disabled {{
                color: {DISABLED_FG};
                background-color: {DISABLED_BG};
                border-color: {BORDER};
            }}
            QPushButton[variant="primary"] {{
                background-color: {ACCENT};
                color: {CARD};
                border: none;
                font-weight: bold;
            }}
            QPushButton[variant="primary"]:hover {{
                background-color: {ACCENT_HOVER};
            }}
            QPushButton[variant="primary"]:pressed {{
                background-color: {ACCENT_PRESSED};
            }}

            /* ===== 滚动条：不写的话深色主题下会露出浅灰默认样式 ===== */
            QScrollBar:vertical {{
                background: transparent;
                width: 10px;
                margin: 2px;
            }}
            QScrollBar::handle:vertical {{
                background-color: {HANDLE};
                border-radius: 5px;
                min-height: 28px;
            }}
            QScrollBar::handle:vertical:hover {{
                background-color: {HANDLE_HOVER};
            }}
            QScrollBar:horizontal {{
                background: transparent;
                height: 10px;
                margin: 2px;
            }}
            QScrollBar::handle:horizontal {{
                background-color: {HANDLE};
                border-radius: 5px;
                min-width: 28px;
            }}
            QScrollBar::add-line, QScrollBar::sub-line {{
                width: 0;
                height: 0;
            }}
            QScrollBar::add-page, QScrollBar::sub-page {{
                background: transparent;
            }}
        """

    def _anchor(self, index):
        """第 index 个小节的 HTML 锚点名。"""
        return f"help_sec_{int(index)}"

    def _render_sections(self):
        """把小节拼成一段 HTML（锚点 + 小节标题 + 调用方给的正文）并塞进正文控件。"""
        P = self._P
        parts = []
        # 正文文字颜色也用色板写进 HTML：不依赖 Qt 从 QSS 推导文档默认色
        parts.append(f'<div style="font-size:13px; color:{P["TEXT"]};">')
        for i, (sec_title, sec_body) in enumerate(self.sections):
            # 零宽锚点：不影响排版，scrollToAnchor 能定位到
            parts.append(f'<a name="{self._anchor(i)}"></a>')
            parts.append(
                f'<h3 style="font-size:15px; color:{P["TEXT"]}; '
                f'margin-top:4px; margin-bottom:6px;">{html.escape(sec_title)}</h3>')
            parts.append(sec_body or "")
        parts.append("</div>")
        document_css = (
            f"p {{ margin-top: 5px; margin-bottom: 5px; }}"
            f" li {{ margin-top: 2px; margin-bottom: 2px; }}"
            f" a {{ color: {P['ACCENT']}; text-decoration: underline; }}"
            f" pre, code {{ background-color: {P.get('ALT_ROW', P['CARD'])};"
            f" color: {P['TEXT']}; font-family: Consolas, Menlo, monospace; }}"
        )
        try:
            self.browser.document().setDefaultStyleSheet(document_css)
        except Exception as e:
            _logger.warning("帮助正文默认样式设置失败：%s", e)
        try:
            self.browser.setHtml("".join(parts))
        except Exception as e:
            _logger.warning("帮助正文渲染失败：%s", e)
        try:
            self.browser.moveCursor(QTextCursor.Start)
        except Exception:
            pass
        # 默认选中第一小节
        if self.sections:
            try:
                self.toc.setCurrentRow(0)
            except Exception:
                pass

    # ------------------------------------------------------------ 主题重刷
    def _apply_icons(self):
        """给底部两个按钮设单色图标（v4.28）。

        图标分浅色/深色两套（描边色不同），所以换主题时要重取；资源缺失时
        `gui_icons.icon()` 返回空 QIcon，按钮就只剩文字，不会崩也不会出现方块。
        """
        try:
            from gui_icons import icon as _icon
        except Exception as e:
            _logger.warning("帮助窗口加载图标集失败：%s", e)
            return
        theme = _icon_theme(self._P)
        for btn, name in ((getattr(self, 'copy_btn', None), 'copy'),
                          (getattr(self, 'log_btn', None), 'folder_open')):
            if btn is None:
                continue
            try:
                btn.setIcon(_icon(name, theme))
                btn.setIconSize(QSize(15, 15))
            except Exception as e:
                _logger.warning("帮助窗口设置图标失败（%s）：%s", name, e)

    def apply_palette(self, palette):
        """换主题色板：重设样式表 + 重渲染正文（主题切换后复用同一窗口时调用）。

        正文里的行内颜色也来自色板，所以必须重渲染；否则「先浅色开帮助、
        再切深色、又按 F1」会复用旧样式表，深色界面里留下一块白底正文
        （本项目踩过的白块坑）。成功返回 True。
        """
        try:
            base = dict(THEMES.get(DEFAULT_THEME, {}))
            if palette:
                base.update(dict(palette))
            self._P = base
            self._palette_key = _palette_key(palette)
            self.setStyleSheet(self._build_qss())
            self._render_sections()
            self._apply_icons()      # 图标分深浅两套，换主题要重取（v4.28）
            # 正文重渲染后搜索状态要重算（命中高亮 / 未命中描边都跟主题有关）
            self._on_search_changed(self.search_edit.text())
            return True
        except Exception as e:
            _logger.warning("帮助窗口换主题失败：%s", e)
            return False

    # -------------------------------------------------------------- 目录跳转
    def _on_toc_changed(self, row):
        """点目录跳转到对应小节。"""
        if isinstance(row, int) and 0 <= row < len(self.sections):
            self.scroll_to_section(row)

    def scroll_to_section(self, index):
        """滚动到第 index 个小节（QTextBrowser.scrollToAnchor）。"""
        try:
            name = self._anchor(index)
            self.browser.scrollToAnchor(name)
            bar = self.browser.verticalScrollBar()
            # 兜底：极端情况下（锚点未解析）按比例滚动，至少跳到大致位置
            if index > 0 and bar is not None and bar.value() == 0 \
                    and len(self.sections) > 1:
                frac = index / float(len(self.sections) - 1)
                bar.setValue(int(bar.maximum() * frac))
            return True
        except Exception as e:
            _logger.warning("跳转帮助小节失败（index=%s）：%s", index, e)
            return False

    def select_section(self, index, sync_toc=True):
        """选中并跳转到第 index 个小节（供调用方编程使用）。"""
        if sync_toc:
            try:
                self.toc.setCurrentRow(index)
                return True
            except Exception as e:
                _logger.warning("同步帮助目录失败：%s", e)
        return self.scroll_to_section(index)

    # ------------------------------------------------------------------ 搜索
    def _set_search_missing(self, missing):
        """未命中时给搜索框加主题色描边（ORANGE 取自色板，不硬编码颜色）。"""
        try:
            if missing:
                P = self._P
                self.search_edit.setStyleSheet(
                    "QLineEdit {"
                    f" border: 2px solid {P['ORANGE']};"
                    f" background-color: {P['CARD']};"
                    f" color: {P['TEXT']};"
                    " border-radius: 6px;"
                    " padding: 4px 7px;"
                    " font-size: 13px; }")
            else:
                self.search_edit.setStyleSheet("")
        except Exception as e:
            _logger.warning("搜索框状态样式设置失败：%s", e)

    def _on_search_changed(self, text):
        """输入即搜索：命中就选中并滚到该处，没命中标红边框 + 文字提示。"""
        kw = (text or "").strip()
        try:
            if not kw:
                self.search_hint.setText("")
                self._set_search_missing(False)
                return
            # 每次都从文档开头找，否则连续输入只会向后搜、前面的命中会漏
            self.browser.moveCursor(QTextCursor.Start)
            found = self.browser.find(kw)
            if found:
                self.search_hint.setText(f"已定位「{kw}」")
                self._set_search_missing(False)
            else:
                self.search_hint.setText(f"未找到「{kw}」")
                self._set_search_missing(True)
        except Exception as e:
            _logger.warning("帮助搜索失败：%s", e)
            self._set_search_missing(False)

    # ------------------------------------------------------------ 复制 / 日志
    def copy_all_text(self):
        """把全部正文纯文本复制到剪贴板；成功返回 True（失败只写日志）。"""
        try:
            text = self.browser.toPlainText()
            clipboard = QApplication.clipboard()
            if clipboard is None:
                raise RuntimeError("剪贴板不可用")
            clipboard.setText(text)
            self._flash_copy_button()
            return True
        except Exception as e:
            _logger.warning("复制帮助正文失败：%s", e)
            return False

    def _flash_copy_button(self):
        """按钮文字短暂变成「已复制」再变回。"""
        try:
            self.copy_btn.setText("已复制")
            self._copy_timer.start(1200)
        except Exception as e:
            _logger.warning("复制按钮反馈失败：%s", e)

    def _restore_copy_button(self):
        """把复制按钮文字还原。"""
        try:
            self.copy_btn.setText(self._copy_default_text)
        except Exception as e:
            _logger.warning("复制按钮文字还原失败：%s", e)

    def open_log_folder(self):
        """打开日志文件夹；失败时 QMessageBox.warning 提示（不影响窗口本身）。"""
        try:
            from gui_log import open_log_folder
        except Exception as e:
            _logger.warning("导入 gui_log 失败：%s", e)
            QMessageBox.warning(self, "无法打开日志文件夹",
                                f"日志模块不可用：\n{e}")
            return False
        ok = False
        try:
            ok = bool(open_log_folder())
        except Exception as e:
            _logger.warning("打开日志文件夹失败：%s", e)
        if not ok:
            try:
                QMessageBox.warning(
                    self, "无法打开日志文件夹",
                    "未能打开日志目录，请手动前往：\n" + (self.log_text or "（未知路径）"))
            except Exception as e:
                _logger.warning("日志提示框显示失败：%s", e)
        return ok

    # -------------------------------------------------------------- 尺寸记忆
    def _save_geometry(self):
        """保存当前尺寸（失败只写日志）。"""
        if self._settings is None or not self._geo_key:
            return
        try:
            self._settings.setValue(
                self._geo_key, f"{self.width()}x{self.height()}")
            self._settings.sync()
        except Exception as e:
            _logger.warning("保存帮助窗口尺寸失败：%s", e)

    def closeEvent(self, event):
        """关闭时记住尺寸。"""
        self._save_geometry()
        try:
            super().closeEvent(event)
        except Exception:
            event.accept()

    def hideEvent(self, event):
        # 非模态窗口被 hide 时也顺手记一下尺寸
        self._save_geometry()
        try:
            super().hideEvent(event)
        except Exception:
            pass


def show_help_dialog(parent, title, sections, palette=None, subtitle="",
                     log_text=""):
    """构造并**非模态**显示帮助窗口；返回该对象。

    窗口挂在 ``parent._help_dialog`` 上防止被 GC。若 parent 已有
    ``_help_dialog`` 且还可见则复用（先 ``raise_()``；sections 或标题变了
    就关掉旧的重建）。parent 为 None 时退化为模块级引用兜底。

    Args:
        parent: 父窗口（可为 None）
        title: 窗口标题
        sections: [("小节标题", "HTML 正文"), ...]
        palette: gui_config.THEMES[theme]；None 时用默认主题
        subtitle: 副标题（如 "v4.24 · 2026-09-10"）
        log_text: 底部日志路径文字（空串则不显示该行）
    """
    global _LAST_DIALOG
    key = _sections_key(sections)
    pkey = _palette_key(palette)
    title = str(title or "帮助")

    old = None
    if parent is not None:
        try:
            old = getattr(parent, "_help_dialog", None)
        except Exception:
            old = None
    if old is not None:
        try:
            # 已销毁的 C++ 对象：isVisible() 会抛 RuntimeError，视为没有
            same = (getattr(old, "_sections_key", None) == key
                    and getattr(old, "title_text", None) == title)
            if same:
                # 主题换过就必须重刷样式表（否则深色界面里会复用浅色白块）
                if getattr(old, "_palette_key", None) != pkey:
                    old.apply_palette(palette)
                if not old.isVisible():
                    old.show()
                old.raise_()
                old.activateWindow()
                return old
            # 内容变了：先关掉旧窗口再重建（尺寸会从 QSettings 恢复）
            old.close()
        except RuntimeError:
            old = None
        except Exception as e:
            _logger.warning("复用帮助窗口失败，改为重建：%s", e)

    dialog = HelpDialog(parent=parent, title=title, sections=sections,
                        palette=palette, subtitle=subtitle, log_text=log_text)
    dialog._sections_key = key
    if parent is not None:
        try:
            parent._help_dialog = dialog
        except Exception as e:
            _logger.warning("挂载帮助窗口到父窗口失败：%s", e)
            _LAST_DIALOG = dialog
    else:
        _LAST_DIALOG = dialog
    dialog.show()
    dialog.raise_()
    dialog.activateWindow()
    return dialog
