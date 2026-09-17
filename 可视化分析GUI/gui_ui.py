# -*- coding: utf-8 -*-
"""
界面/样式混入：负责建立主窗口的各个面板、QSS 样式与中文字体。
"""

from pathlib import Path

import logging

import matplotlib.pyplot as plt
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
from PyQt5.QtCore import Qt, QDir, QTimer, QSize, QEvent
from PyQt5.QtGui import QFont, QIcon, QPixmap
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QFileDialog, QComboBox, QDoubleSpinBox, QCheckBox, QGroupBox, QScrollArea,
    QTabWidget, QListWidget, QSplitter, QProgressBar, QStatusBar, QFrame,
    QSizePolicy, QLineEdit, QFileSystemModel, QTreeView, QSlider, QSpinBox,
    QPlainTextEdit, QToolButton, QMenu, QAction, QMessageBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QStackedWidget, QDockWidget, QToolBar,
)

from gui_config import (
    DEFAULT_WORKSPACE, APP_NAME, APP_VERSION, APP_ICON_FILENAME, UI_FONT_FAMILY,
    RELEASE_DATE,
    COLOR_BG as BG, COLOR_CARD as CARD, COLOR_BORDER as BORDER,
    COLOR_INPUT_BORDER as INPUT_BORDER, COLOR_TEXT as TEXT,
    COLOR_TEXT_SOFT as TEXT_SOFT, COLOR_MUTED as MUTED,
    ACCENT, ACCENT_HOVER, ACCENT_PRESSED,
    SUCCESS, SUCCESS_HOVER, SUCCESS_PRESSED,
    VIOLET, VIOLET_HOVER, VIOLET_PRESSED,
    ORANGE, ORANGE_HOVER, ORANGE_PRESSED,
    CYAN, CYAN_HOVER, CYAN_PRESSED,
    NEUTRAL, NEUTRAL_HOVER, NEUTRAL_PRESSED,
)
from gui_components import (SliderSpin, ComboItemDelegate, MplCanvas,
                            resource_path, set_combo_palette)
from gui_log import log_exception


class UiMixin:
    """界面搭建与样式（含各面板、中文字体、实时预览联动）。"""

    def setup_chinese_font(self):
        """设置中文字体（与 plot_emission 一致）"""
        try:
            candidates = [
                # Windows
                'Microsoft YaHei', 'SimHei', 'KaiTi', 'FangSong', 'SimSun',
                # macOS / Linux
                'PingFang SC', 'Hiragino Sans GB', 'Songti SC', 'STHeiti',
                'Noto Sans CJK SC', 'WenQuanYi Micro Hei', 'Arial Unicode MS',
            ]
            import matplotlib.font_manager as fm
            available = {f.name for f in fm.fontManager.ttflist}
            chosen = None
            for font in candidates:
                if font in available:
                    chosen = font
                    break
            if chosen:
                plt.rcParams['font.sans-serif'] = [chosen, 'DejaVu Sans']
                plt.rcParams['axes.unicode_minus'] = False
            else:
                plt.rcParams['font.sans-serif'] = ['DejaVu Sans']
        except:
            pass

    def setup_ui(self):
        """设置用户界面"""
        self.setWindowTitle(f"光谱可视化分析工具 v{APP_VERSION}")
        # 设置窗口图标
        try:
            icon_path = resource_path(APP_ICON_FILENAME)
            if icon_path:
                self.setWindowIcon(QIcon(icon_path))
        except Exception:
            pass
        # 初始窗口尽量大且不超出屏幕（避免系统压缩导致布局闪变）；可自由调整
        screen = QApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            init_w = min(1500, int(avail.width() * 0.95))
            init_h = min(880, int(avail.height() * 0.92))
        else:
            init_w, init_h = 1500, 880
        self.resize(init_w, init_h)
        self.setMinimumSize(1000, 600)  # 允许缩小到一定范围
        # 接受文件夹拖放加载（D5）
        self.setAcceptDrops(True)
        # 居中窗口
        if screen is not None:
            geom = self.frameGeometry()
            geom.moveCenter(screen.availableGeometry().center())
            self.move(geom.topLeft())

        # 四个面板：目录树 / 数据 / 参数 / 画布
        self.tree_panel = self.create_tree_panel()
        self.file_panel = self.create_file_panel()
        self.param_panel = self.create_param_panel()
        self.canvas_panel = self.create_canvas_panel()
        # 「数据比较」变量下拉框按当前说明.xlsx 初始化（v4.37）：
        # 还没加载文件夹时应显示「未找到说明.xlsx」并禁用按钮
        try:
            self._refresh_compare_combos()
        except Exception:
            pass

        # ---- 三栏折叠状态与宽度记忆（v4.26 建立；v4.29 起由 QDockWidget 承载）----
        # 索引与下面三个 dock 一一对应：0=目录树 1=数据 2=参数
        self._panel_widgets = (self.tree_panel, self.file_panel, self.param_panel)
        self._panel_names = ("目录树", "数据", "参数")
        self._panel_labels = ("目\n录", "数\n据", "参\n数")
        self._col_min = [170, 170, 275]          # 各栏最小宽度（内容决定）
        self._col_widths = [200, 210, 285]       # 各栏"展开时应有的宽度"（记住用户拖过的结果）
        self._col_hidden = [False, False, False]
        self._col_sizes_applied = False

        # 画布 = 中央部件；三栏 = 停靠面板（v4.29：可拖动 / 浮动 / 关闭 / 堆叠）
        central = QWidget()
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(8, 8, 8, 8)
        central_layout.setSpacing(0)
        central_layout.addWidget(self.canvas_panel)
        self.central_wrapper = central
        self.setCentralWidget(central)

        # 前三栏最小宽度兜底（QDockWidget 会跟随内容最小宽度，不再挤压）
        # 参数栏最小宽度 275：v4.22 修订后内容最小宽度 254，竖向滚动条另占约 15 px
        self.tree_panel.setMinimumWidth(self._col_min[0])
        self.file_panel.setMinimumWidth(self._col_min[1])
        self.param_panel.setMinimumWidth(self._col_min[2])
        self.canvas_panel.setMinimumWidth(400)

        self.tree_dock = self._make_dock(0, self._panel_names[0], self.tree_panel, "treeDock")
        self.file_dock = self._make_dock(1, self._panel_names[1], self.file_panel, "fileDock")
        self.param_dock = self._make_dock(2, self._panel_names[2], self.param_panel, "paramDock")
        self._panel_docks = (self.tree_dock, self.file_dock, self.param_dock)
        self.left_docks = (self.tree_dock, self.file_dock)
        self._place_docks_default()

        # 栏开关条（v4.26）：始终可见的折叠/展开入口。
        # 它**不在**任何 dock 里——栏关掉后其内部所有控件（含折叠按钮）都会
        # 一起消失，入口必须留在栏外，否则关了就再也点不回来。
        self.panel_rail = self._create_panel_rail()
        self.addToolBar(Qt.LeftToolBarArea, self.panel_rail)

        # 设置全局字体大小（适配高分辨率屏幕）
        font = QFont()
        font.setFamily(UI_FONT_FAMILY)  # 全局界面字体（按平台自动选择）
        font.setPointSize(12)  # 全局基础字体（各控件字号统一由 QSS 控制）
        self.setFont(font)

        # 状态栏（v4.27）：左侧状态文字 / 中段进度条 / 右侧「模式 + 样品数」徽标。
        # 进度条原来固定在参数栏顶部，既占纵向空间、又和状态栏信息重复；
        # 现在统一收到状态栏里（属性名保持 progress_bar，加载/拟合代码不用改）。
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedWidth(180)
        self.progress_bar.setFixedHeight(12)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setVisible(False)          # 空闲时不占位
        self.progress_bar.setToolTip("加载 / 拟合进度")
        self.status_bar.addPermanentWidget(self.progress_bar)

        self.status_mode_badge = QLabel("吸收光谱")
        self.status_mode_badge.setProperty("role", "badge")
        self.status_mode_badge.setToolTip("当前模块（左侧「光谱类型」下拉框切换）")
        self.status_bar.addPermanentWidget(self.status_mode_badge)

        self.status_sample_badge = QLabel("0 个样品")
        self.status_sample_badge.setProperty("role", "badge")
        self.status_sample_badge.setToolTip("已加载的数据文件数（数据栏列表）")
        self.status_bar.addPermanentWidget(self.status_sample_badge)

        self.status_bar.showMessage("就绪")

        # 应用样式
        self.apply_style()

        # 连接实时预览
        self._connect_live_update()

        # 全局快捷键（D4）
        self._setup_shortcuts()

        # 首次进入的空状态（还没加载任何数据）
        self._sync_empty_state()
        self._update_status_badges()

    def _setup_shortcuts(self):
        """全局快捷键（D4 / E5）。"""
        from PyQt5.QtWidgets import QShortcut
        from PyQt5.QtGui import QKeySequence
        pairs = [
            ("F5", lambda: self.update_plot(explicit=True)),
            ("Ctrl+R", self.reload_data),
            ("Ctrl+O", self.select_folder),
            ("Ctrl+E", self.export_plot),
            ("Ctrl+S", self.export_plot),           # E5：导出当前图
            ("Ctrl+Shift+E", self.export_all_plots),
            ("Ctrl+D", self._copy_integration_results),
            ("Ctrl+F", self._focus_file_search),
            ("Ctrl+T", lambda: self.toggle_theme()),  # E5：切换主题
            # v4.29：布局预设（三栏停靠体系的快捷入口）
            ("Ctrl+1", lambda: self.apply_layout_preset("fit")),
            ("Ctrl+2", lambda: self.apply_layout_preset("plot")),
            ("Ctrl+3", lambda: self.apply_layout_preset("canvas")),
            ("F1", self.show_help),
        ]
        self._shortcuts = []
        for seq, slot in pairs:
            try:
                sc = QShortcut(QKeySequence(seq), self)
                sc.activated.connect(slot)
                self._shortcuts.append(sc)
            except Exception as e:
                logging.warning("快捷键 %s 绑定失败: %s", seq, e)

    def _open_log_folder(self):
        """「帮助 → 打开日志文件夹」（D6）。"""
        try:
            from gui_log import log_dir, open_log_folder
            if not open_log_folder():
                QMessageBox.warning(self, "提示",
                                    f"无法打开日志文件夹，请手动访问：\n{log_dir()}")
        except Exception as e:
            logging.warning("打开日志文件夹失败: %s", e)

    # ---------- 停靠面板（QDockWidget）+ 布局预设（v4.29）----------

    # 三套布局预设：栏宽 + 各栏显隐（真正的几何由 resizeDocks / setVisible 下发）
    _LAYOUT_PRESETS = {
        "fit":    {"widths": (210, 220, 320), "hidden": (False, False, False)},
        "plot":   {"widths": (190, 200, 285), "hidden": (False, False, True)},
        "canvas": {"widths": (190, 200, 285), "hidden": (True, True, True)},
    }
    _LAYOUT_TITLES = {
        "fit": "拟合工作台", "plot": "出图工作台", "canvas": "只看图",
    }

    def _make_dock(self, idx, title, widget, object_name):
        """把一栏的内容包成 QDockWidget。

        v4.29：三栏从 QSplitter 子控件改为停靠面板——可以拖动换位、拖出成
        浮动窗口、叠成标签页、按 × 关闭（= 折叠），比原来只能拖分隔条灵活。
        objectName 必须设：QMainWindow.saveState/restoreState 靠它识别面板。
        """
        dock = QDockWidget(title, self)
        dock.setObjectName(object_name)
        dock.setFeatures(QDockWidget.DockWidgetMovable
                         | QDockWidget.DockWidgetFloatable
                         | QDockWidget.DockWidgetClosable)
        # 只允许左右停靠：停到上下会把列表/参数压成一条横带，反而不好用
        dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        # 面板本体是普通 QWidget，QSS 的背景/圆角要靠 WA_StyledBackground 才画得出来
        widget.setAttribute(Qt.WA_StyledBackground, True)
        widget.setProperty("role", "dockBody")
        dock.setWidget(widget)
        # ⚠️ 这里**不能**接 dock.visibilityChanged（v4.29 踩过的坑）：
        #   那个 lambda 闭包引用 self，会和 dock 形成引用环，窗口对象于是不再
        #   即时析构、被 GC 延后到任意时刻销毁；而"仍处于显示状态"的窗口在
        #   析构时 dock 会发 Hide 信号——PyQt 在析构期派发这个信号直接 abort
        #   （退出码 0xC0000409、没有任何 traceback，连开 3 个窗口必崩）。
        #   改用事件过滤听 dock 自己的 Show/Hide：事件过滤路径在析构期安全，
        #   也不会产生引用环。
        dock.installEventFilter(self)      # 记录拖动后的栏宽 + 同步显隐状态
        return dock

    def _place_docks_default(self):
        """默认停靠位置：左侧「目录树 | 数据」并排，右侧「参数」。"""
        self.addDockWidget(Qt.LeftDockWidgetArea, self.tree_dock)
        self.splitDockWidget(self.tree_dock, self.file_dock, Qt.Horizontal)
        self.addDockWidget(Qt.RightDockWidgetArea, self.param_dock)

    def _dock_index(self, obj):
        """obj 是第几栏的 dock；不是 dock 就返回 None。"""
        for i, d in enumerate(getattr(self, '_panel_docks', ())):
            if obj is d:
                return i
        return None

    def _create_panel_rail(self):
        """最左侧的「栏开关条」：三个竖排按钮 + 布局预设。

        v4.29：栏本身改成 QDockWidget 后，Qt 自带拖动/浮动/关闭，但栏一关掉
        它内部的控件就全没了——入口必须留在栏外，所以这条 rail 不放在任何
        dock 里，而是作为左工具条区域最外侧的 QToolBar，位置永远固定。
        """
        tb = QToolBar("栏开关条", self)
        tb.setObjectName("panelRail")
        tb.setMovable(False)
        tb.setFloatable(False)
        tb.setAllowedAreas(Qt.LeftToolBarArea)
        tb.setOrientation(Qt.Vertical)
        tb.setIconSize(QSize(16, 16))

        self.panel_toggle_btns = []
        for idx, label in enumerate(self._panel_labels):
            btn = QPushButton(label)
            btn.setProperty("variant", "rail")
            btn.setCheckable(True)
            btn.setChecked(True)                 # 勾选 = 该栏展开
            btn.setFixedSize(30, 56)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setToolTip(f"{self._panel_names[idx]}栏：点击收起 / 展开")
            btn.clicked.connect(lambda _checked=False, i=idx: self.toggle_panel(i))
            tb.addWidget(btn)
            self.panel_toggle_btns.append(btn)

        # 布局预设入口（v4.29）：三套预设 + 各栏显隐 + 恢复默认
        self.layout_btn = QPushButton("布\n局")
        self.layout_btn.setProperty("variant", "rail")
        self.layout_btn.setFixedSize(30, 44)
        self.layout_btn.setCursor(Qt.PointingHandCursor)
        self.layout_btn.setToolTip(
            "布局预设：拟合工作台 (Ctrl+1) / 出图工作台 (Ctrl+2) / 只看图 (Ctrl+3)\n"
            "三栏可自由拖动、拖出浮动、叠放成标签页")
        self.layout_btn.setMenu(self._create_layout_menu())
        tb.addWidget(self.layout_btn)
        return tb

    def _create_layout_menu(self):
        """「布局」下拉菜单：三套预设 + 各栏显隐 + 恢复默认布局。"""
        menu = QMenu(self)
        for key, text, tip in (
            ("fit", "拟合工作台　(Ctrl+1)", "三栏全开、参数栏加宽——边调参数边看图"),
            ("plot", "出图工作台　(Ctrl+2)", "收起参数栏，把宽度让给画布——专心出图"),
            ("canvas", "只看图　(Ctrl+3)", "三栏全部收起——汇报/审图时画布最大化"),
        ):
            act = QAction(text, self)
            act.setToolTip(tip)
            act.triggered.connect(lambda _checked=False, k=key:
                                  self.apply_layout_preset(k))
            menu.addAction(act)
        menu.addSeparator()

        # 各栏显隐（勾选态由 _sync_panel_toggle_btns 与 dock 实际状态同步）
        self.act_show_panels = []
        for idx in range(3):
            act = QAction(f"{self._panel_names[idx]}栏", self)
            act.setCheckable(True)
            act.setChecked(True)
            act.setToolTip(f"显示 / 收起{self._panel_names[idx]}栏")
            act.triggered.connect(lambda _checked=False, i=idx: self.toggle_panel(i))
            menu.addAction(act)
            self.act_show_panels.append(act)
        menu.addSeparator()

        act_reset = QAction("恢复默认布局", self)
        act_reset.setToolTip("三栏归位（左侧目录树+数据、右侧参数）并全部展开，浮动/叠放一并复位")
        act_reset.triggered.connect(lambda: self.reset_dock_layout())
        menu.addAction(act_reset)
        return menu

    # v4.29（版本标记写在注释里：docstring 属于字符串字面量，
    # 会被 检查版本一致性.py 当成"硬编码版本号"）
    def apply_layout_preset(self, key):
        """套用布局预设：先归位到默认停靠状态，再按预设设宽度与显隐。"""
        spec = self._LAYOUT_PRESETS.get(key)
        if spec is None or not hasattr(self, '_panel_docks'):
            return
        self.reset_dock_layout(quiet=True)
        for i, w in enumerate(spec["widths"]):
            self._col_widths[i] = int(w)
        for i, hidden in enumerate(spec["hidden"]):
            self.toggle_panel(i, collapsed=bool(hidden))
        self._apply_col_sizes()
        self._sync_panel_toggle_btns()
        self.status_bar.showMessage(
            f"已切换到「{self._LAYOUT_TITLES.get(key, key)}」布局")

    def reset_dock_layout(self, quiet=False):
        """把三栏从浮动/叠放状态恢复到默认停靠位置。"""
        if not hasattr(self, '_panel_docks'):
            return
        try:
            for dock in self._panel_docks:
                if dock.isFloating():
                    dock.setFloating(False)
                if not dock.isVisible():
                    dock.show()
            self._place_docks_default()
            for i in range(3):
                self._col_hidden[i] = False
            self._apply_col_sizes()
            self._sync_panel_toggle_btns()
            if not quiet:
                self.status_bar.showMessage("已恢复默认布局（左：目录树+数据，右：参数）")
        except Exception as e:
            log_exception("恢复默认布局失败", e)

    def toggle_panel(self, idx, collapsed=None):
        """收起 / 展开第 idx 栏（0=目录树 1=数据 2=参数）。

        collapsed=None 表示切换点击；显式传 True/False 供会话恢复用。
        v4.29：收起 = 隐藏对应的 QDockWidget（等价于按它标题栏的 ×）。
        """
        if idx not in (0, 1, 2) or not hasattr(self, '_panel_docks'):
            return
        dock = self._panel_docks[idx]
        prev_hidden = self._col_hidden[idx]
        if collapsed is None:
            want_hidden = dock.isVisible()
        else:
            want_hidden = bool(collapsed)
        if want_hidden and dock.isVisible() and dock.width() > 0:
            # 收起前记住实际宽度，展开时回到原样（最小值兜底）
            self._col_widths[idx] = max(int(dock.width()), self._col_min[idx])
        self._col_hidden[idx] = want_hidden
        dock.setVisible(not want_hidden)
        self._apply_col_sizes()
        self._sync_panel_toggle_btns()
        # 只在**用户点击（collapsed is None）或状态真的变了**时提示；
        # 否则启动时恢复布局会把三栏各播报一遍，最后一句还留在状态栏上
        if collapsed is None or prev_hidden != want_hidden:
            self.status_bar.showMessage(
                f"{self._panel_names[idx]}栏已" + ("收起" if want_hidden else "展开"))

    def _apply_col_sizes(self):
        """按「记忆宽度 + 画布吃剩余」重算三栏宽度（v4.29：Dock 版）。

        QMainWindow.resizeDocks 会把指定宽度分配给各 dock，剩下的全部留给
        中央部件（画布）；隐藏的栏不参与，否则会把宽度白算进被跳过的那一栏。
        浮动的 dock 已经是独立窗口，Qt 会忽略它，不影响结果。
        """
        try:
            if not hasattr(self, '_panel_docks'):
                return
            docks, widths = [], []
            for i in range(3):
                dock = self._panel_docks[i]
                if self._col_hidden[i] or not dock.isVisible():
                    continue
                docks.append(dock)
                widths.append(int(self._col_widths[i]))
            if docks:
                self.resizeDocks(docks, widths, Qt.Horizontal)
                # 首次按记忆宽度下发之后，才允许 eventFilter 记录"用户拖动后的宽度"。
                # 否则建窗阶段 dock 先按自身 sizeHint（约 276px）排一次版，
                # 会被当成用户拖动结果写进 _col_widths，把记忆宽度覆盖掉。
                self._dock_widths_live = True
        except Exception as e:
            log_exception("重算栏宽失败", e)

    def _sync_panel_toggle_btns(self):
        """开关条按钮 / 布局菜单勾选项与当前折叠状态同步。"""
        for i, btn in enumerate(getattr(self, 'panel_toggle_btns', [])):
            expanded = not self._col_hidden[i]
            btn.blockSignals(True)
            btn.setChecked(expanded)
            btn.blockSignals(False)
            btn.setToolTip(f"{self._panel_names[i]}栏："
                           + ("已展开 —— 点击收起" if expanded else "已收起 —— 点击展开"))
        for i, act in enumerate(getattr(self, 'act_show_panels', [])):
            act.blockSignals(True)
            act.setChecked(not self._col_hidden[i])
            act.blockSignals(False)

    def eventFilter(self, obj, event):
        """听三栏 dock 的事件：显隐同步 + 记录拖动后的栏宽（v4.29）。

        QDockWidget 既没有"分隔条被拖动"信号，它的 visibilityChanged 也不能
        接（见 _make_dock 里的说明：会形成引用环、在析构期被派发导致 abort），
        所以两件事都放在事件过滤里做。

        Resize（栏宽）的两个过滤条件缺一不可：
          * ``_dock_widths_live``：首次按记忆宽度排好版之前不记录（否则建窗
            阶段 dock 的 sizeHint 宽度会把记忆宽度冲掉）；
          * 左键按下中：只有用户真的在拖分隔条时才记录，窗口缩放导致的
            连带变窄不算（否则"窗口拖小一次"会永久把栏宽改小）。

        Show/Hide（显隐）：用户按 dock 标题栏的 × 关闭、或把栏拖成浮动窗口
        时，`_col_hidden` 要跟着变；dock 的 Show/Hide 只在**它自己**显隐时
        发出，窗口最小化不会触发（Qt 不给子控件补发 Hide），所以不会把
        "最小化"误记成"三栏全收起"。
        """
        etype = event.type()
        if etype == QEvent.Resize:
            if (getattr(self, '_dock_widths_live', False)
                    and (QApplication.mouseButtons() & Qt.LeftButton)):
                try:
                    idx = self._dock_index(obj)
                    if idx is not None:
                        w = int(event.size().width())
                        if (not self._col_hidden[idx]) and w >= self._col_min[idx]:
                            self._col_widths[idx] = w
                except Exception:
                    # 析构期的事件：异常从事件过滤器逃出去会被 PyQt 直接 abort
                    pass
        elif etype in (QEvent.Show, QEvent.Hide):
            try:
                idx = self._dock_index(obj)
                if idx is not None:
                    self._col_hidden[idx] = (etype == QEvent.Hide)
                    self._sync_panel_toggle_btns()
            except Exception:
                pass
        return super().eventFilter(obj, event)

    def showEvent(self, event):
        """首次显示后按真实宽度应用一次栏宽（setSizes 需要真实宽度才准确）。"""
        super().showEvent(event)
        if not getattr(self, '_col_sizes_applied', False):
            self._col_sizes_applied = True
            QTimer.singleShot(0, self._apply_col_sizes)

    # v4.26 新增（版本标记写在注释里：docstring 属于字符串字面量，
    # 会被 检查版本一致性.py 当成"硬编码版本号"，只能放注释）
    def _focus_file_search(self):
        """Ctrl+F：聚焦数据栏的搜索框并选中已有内容。"""
        edit = getattr(self, 'file_search_edit', None)
        if edit is None:
            return
        # 搜索框在折叠的数据栏里就先把栏展开，否则聚焦了也看不见
        if self._col_hidden[1]:
            self.toggle_panel(1, collapsed=False)
        edit.setFocus()
        edit.selectAll()

    # ---------- 状态栏徽标 / 空状态 / 工具条中文化（v4.27）----------

    @staticmethod
    def _repolish(widget):
        """改过 QSS 属性（如 badgeState）后强制重新解析样式，否则颜色不会变。"""
        try:
            st = widget.style()
            st.unpolish(widget)
            st.polish(widget)
            widget.update()
        except Exception:
            pass

    def set_badge_state(self, widget, state):
        """设置徽标状态（ok / warn / bad / none）并立即换色。"""
        if widget is None:
            return
        widget.setProperty("badgeState", state)
        self._repolish(widget)

    def _update_status_badges(self):
        """状态栏右侧两个徽标：当前模式 + 已加载样品数。"""
        names = {0: "吸收光谱", 1: "发射光谱", 2: "荧光寿命", 3: "3D 扫描"}
        badge = getattr(self, 'status_mode_badge', None)
        if badge is not None:
            try:
                idx = int(self.spectrum_type_combo.currentIndex())
                badge.setText(names.get(idx, "—"))
            except Exception:
                pass
        sb = getattr(self, 'status_sample_badge', None)
        if sb is not None:
            try:
                sb.setText(f"{self.file_list.count()} 个样品")
            except Exception:
                pass

    # matplotlib 工具条按钮的中文说明（键是 NavigationToolbar2QT 内部的
    # 回调名，比按显示文字匹配稳——不同 mpl 版本按钮文字会变）
    _TOOLBAR_TIPS = {
        'home': ('复位视图', '恢复到初始缩放/平移状态（快捷键 h）'),
        'back': ('上一视图', '回到上一个视图（快捷键 ← 或 c）'),
        'forward': ('下一视图', '前进到下一个视图（快捷键 → 或 v）'),
        'pan': ('平移', '按住左键拖动画面（快捷键 p）'),
        'zoom': ('框选缩放', '左键拖出矩形放大；右键拖出矩形缩小（快捷键 o）'),
        'configure_subplots': ('调整边距', '打开边距参数对话框手工微调（快捷键 f）'),
        'edit_parameters': ('曲线参数', '编辑坐标轴/曲线/图像参数（快捷键 Ctrl+E 是本程序的导出）'),
        'save_figure': ('保存图片', '把当前画布另存为图片（程序自己的导出见「💾 导出 ▾」）'),
    }

    def _decorate_nav_toolbar(self, tb):
        """给 matplotlib 导航工具条加中文 tooltip。

        mpl 自带工具条只有英文 tooltip（Home / Pan / Zoom / Customize…），
        且有个按钮连图标都没有（Customize）。这里只改文字与 tooltip：
        **按钮顺序和分组分隔保持 mpl 原样**——`toolitems` 里本来就带了
        None 分隔项（视图 | 缩放/参数 | 保存），自己再插一遍会出现双分隔线
        （开发中实测踩到）。
        """
        try:
            acts = getattr(tb, '_actions', None) or {}
            for key, (label, tip) in self._TOOLBAR_TIPS.items():
                a = acts.get(key)
                if a is None:
                    continue
                a.setText(label)
                a.setToolTip(f"{label} —— {tip}")
                a.setStatusTip(tip)
            tb.setToolTip("matplotlib 缩放 / 平移 / 保存（鼠标悬停看中文说明）")
            lab = getattr(tb, 'locLabel', None)
            if lab is not None:
                lab.setToolTip("当前鼠标位置的数据坐标")
        except Exception as e:
            log_exception("装饰导航工具条失败", e)

    # 三步上手指引（v4.31）：第 3 步的文案随模式变（见 _sync_empty_state）。
    # 文案刻意压短——默认三栏布局下画布只有 ~460px 宽，三张卡片各占 ~140px，
    # 写长了每张都要折成三行（实测）。
    _EMPTY_STEPS = (
        ("1", "选择数据文件夹",
         "点下面的按钮，或把文件夹拖进来"),
        ("2", "选类型 / 调参数",
         "左栏顶部切类型，右侧「参数」栏调整"),
        ("3", "预览并导出",
         "按 F5 出图，再从「导出」菜单选格式"),
    )
    _EMPTY_STEP3_LIFETIME = "主按钮是「开始拟合」，单文件约 1–2 分钟"

    def _empty_guide_visible(self):
        """三步指引是否显示（用户点过「不再显示」就记在会话里）。"""
        s = getattr(self, 'settings', None)
        if s is None:
            return True
        try:
            v = s.value("ui/onboarding_hidden", 0)
        except Exception:
            return True
        return str(v).strip().lower() not in ("1", "true", "yes")

    def _set_empty_guide_visible(self, show):
        """显示 / 收起三步指引（并同步按钮文案）。"""
        box = getattr(self, 'empty_steps', None)
        if box is not None:
            box.setVisible(bool(show))
        btn = getattr(self, 'empty_guide_toggle', None)
        if btn is not None:
            btn.setText("不再显示这三步" if show else "显示上手指引")
            btn.setToolTip(
                "收起上面的三步上手指引；收起后这里变成「显示上手指引」，随时可以再展开"
                if show else "重新展开三步上手指引")

    def _toggle_empty_guide(self):
        """「不再显示这三步」/「显示上手指引」按钮。"""
        show = not self._empty_guide_visible()
        self._set_empty_guide_visible(show)
        s = getattr(self, 'settings', None)
        if s is not None:
            try:
                s.setValue("ui/onboarding_hidden", 0 if show else 1)
                s.sync()
            except Exception:
                pass
        if hasattr(self, 'status_bar'):
            self.status_bar.showMessage(
                "已收起三步上手指引（随时可点「显示上手指引」展开）" if not show
                else "已展开三步上手指引")

    def _create_empty_steps(self, parent=None):
        """三步上手指引：三张并排小卡片（序号徽标 + 标题 + 一句说明）。

        空状态最容易犯的错是"只说一句『请选择数据文件夹』"——第一次用的人
        仍然不知道后面两步要干什么。这里把「选数据 → 调参数 → 出图/导出」
        整条主路径摆出来，并在第 3 步按当前模式给不同的说法。
        """
        box = QWidget(parent)
        h = QHBoxLayout(box)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(10)
        self.empty_step_cards = []
        self.empty_step_descs = []
        for num, title, desc in self._EMPTY_STEPS:
            card = QWidget()
            card.setProperty("role", "stepCard")
            cv = QVBoxLayout(card)
            cv.setContentsMargins(12, 10, 12, 10)
            cv.setSpacing(6)

            head = QHBoxLayout()
            head.setSpacing(8)
            no = QLabel(num)
            no.setProperty("role", "stepNo")
            no.setAlignment(Qt.AlignCenter)
            no.setFixedSize(22, 22)
            head.addWidget(no, 0)
            t = QLabel(title)
            t.setProperty("role", "stepTitle")
            head.addWidget(t, 1)
            cv.addLayout(head)

            d = QLabel(desc)
            d.setProperty("role", "hint")
            d.setWordWrap(True)
            cv.addWidget(d)
            cv.addStretch(1)
            h.addWidget(card, 1)
            self.empty_step_cards.append(card)
            self.empty_step_descs.append(d)
        return box

    def _create_empty_state(self, parent=None):
        """画布空状态引导页：插画 + 一句引导 + 主按钮 + 三步上手指引。

        原来没数据时画布上只有一行小灰字，第一眼看不出下一步该干什么；
        v4.27 换成整页引导，v4.31 再补两件：一张"光谱卡片"插画（比图标有
        信息量），以及把「选数据 → 调参数 → 出图」三步写成并排卡片——
        这三步就是首次使用要走的全部路径，可以一键收起、不会再打扰。
        """
        box = QWidget(parent)
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)
        v.addStretch(1)

        icon = QLabel()
        icon.setAlignment(Qt.AlignCenter)
        icon.setProperty("role", "emptyIcon")
        self._set_empty_icon(icon)
        v.addWidget(icon)
        self.empty_icon = icon

        self.empty_title = QLabel("还没有加载数据")
        self.empty_title.setAlignment(Qt.AlignCenter)
        self.empty_title.setProperty("role", "emptyTitle")
        v.addWidget(self.empty_title)

        self.empty_hint = QLabel("把数据文件夹拖到窗口上，或点下面的按钮选择")
        self.empty_hint.setAlignment(Qt.AlignCenter)
        self.empty_hint.setProperty("role", "hint")
        self.empty_hint.setWordWrap(True)
        v.addWidget(self.empty_hint)

        row = QHBoxLayout()
        row.addStretch(1)
        self.empty_btn = QPushButton("选择数据文件夹")
        self.empty_btn.setProperty("variant", "primary")
        self.empty_btn.setCursor(Qt.PointingHandCursor)
        self.empty_btn.setToolTip("选择数据文件夹并加载其中全部数据文件（Ctrl+O）")
        self.empty_btn.clicked.connect(self.select_folder)
        row.addWidget(self.empty_btn)
        row.addStretch(1)
        v.addLayout(row)

        # ---- 三步上手指引 ----
        v.addSpacing(6)
        steps_wrap = QWidget()
        sw = QVBoxLayout(steps_wrap)
        sw.setContentsMargins(8, 0, 8, 0)
        sw.setSpacing(6)
        self.empty_steps = self._create_empty_steps(steps_wrap)
        sw.addWidget(self.empty_steps)
        toggle_row = QHBoxLayout()
        toggle_row.addStretch(1)
        self.empty_guide_toggle = QPushButton("不再显示这三步")
        self.empty_guide_toggle.setProperty("variant", "ghost")
        self.empty_guide_toggle.setCursor(Qt.PointingHandCursor)
        self.empty_guide_toggle.clicked.connect(self._toggle_empty_guide)
        toggle_row.addWidget(self.empty_guide_toggle)
        toggle_row.addStretch(1)
        sw.addLayout(toggle_row)
        self.empty_steps_wrap = steps_wrap
        v.addWidget(steps_wrap)
        self._set_empty_guide_visible(self._empty_guide_visible())

        v.addStretch(1)
        self.empty_state = box
        return box

    def _apply_ui_icons(self):
        """把界面按钮上的 emoji 换成单色图标集。

        图标分浅色/深色两套（描边色不同，浅色界面看不清楚深色图标），所以
        切主题时必须重新取一遍。资源缺失时 `gui_icons.icon()` 返回**空 QIcon**，
        按钮就只剩文字——不会崩、也不会出现"方块豆腐"。
        """
        # 文本按钮的图标尺寸小一点（跟着 13px 字号），纯图标按钮稍大
        specs = [
            (getattr(self, 'home_btn', None), 'home', 17),
            (getattr(self, 'theme_btn', None), self._theme_btn_icon_name(), 17),
            (getattr(self, 'help_btn', None), 'help', 17),
            (getattr(self, 'workspace_btn', None), 'folder_open', 14),
            (getattr(self, 'preview_btn', None), 'play', 15),
            (getattr(self, 'export_menu_btn', None), 'export', 15),
            (getattr(self, 'lifetime_save_defaults_btn', None), 'save', 15),
            (getattr(self, 'lifetime_overlay_btn', None), 'chart_bar', 15),
            (getattr(self, 'integ_copy_btn', None), 'copy', 15),
        ]
        # 三套主题各有一套图标（描边色不同），直接传主题名，由 gui_icons 归一化
        theme = getattr(self, 'theme', 'light')
        try:
            from gui_icons import icon as _icon
        except Exception as e:
            log_exception("加载图标集失败（按钮将只显示文字）", e)
            return
        for btn, name, size in specs:
            if btn is None:
                continue
            try:
                btn.setIcon(_icon(name, theme))
                btn.setIconSize(QSize(size, size))
            except Exception as e:
                log_exception(f"设置按钮图标失败: {name}", e)

    def _set_empty_icon(self, label):
        """给空状态页画图：优先插画，其次单色大图标，最后退回 emoji。

        插画由 `生成图标.py` 生成（`icons\\illus_empty_<theme>.png`），交付的
        是 2 倍图（400x240），这里标上 `devicePixelRatio=2` 按 200x120 逻辑
        尺寸显示——用户的屏幕是 200% 缩放，直接塞 1 倍图会被系统放大到发虚。
        `gui_icons` 找不到文件时逐级退回，所以打包漏了资源也不会空白或崩溃。
        """
        try:
            from gui_icons import illustration_path
            path = illustration_path('empty', getattr(self, 'theme', 'light'))
            if path:
                pm = QPixmap(path)
                if not pm.isNull():
                    pm.setDevicePixelRatio(2.0)
                    label.setText("")
                    label.setPixmap(pm)
                    return
        except Exception:
            pass
        try:
            from gui_icons import icon_path
            path = icon_path('folder_open', getattr(self, 'theme', 'light'), 48)
            if path:
                pm = QPixmap(path)
                if not pm.isNull():
                    label.setText("")
                    label.setPixmap(pm.scaled(56, 56, Qt.KeepAspectRatio,
                                              Qt.SmoothTransformation))
                    return
        except Exception:
            pass
        label.setPixmap(QPixmap())
        label.setText("📁")

    def _sync_empty_state(self):
        """没有数据 → 显示空状态引导；有数据 → 显示画布。"""
        stack = getattr(self, 'preview_stack', None)
        if stack is None:
            return
        try:
            empty = not getattr(self, 'data_cache', None)
            idx = 1 if empty else 0
            if stack.currentIndex() != idx:
                stack.setCurrentIndex(idx)
            # 空画布时那条 matplotlib 工具条没意义，一起收起来。
            # 无条件 setVisible：窗口还没 show() 时 isVisible() 恒为 False，
            # 用 isVisible() 做判断会导致初始状态漏设（v4.27 实测踩到）。
            tb = getattr(self, 'toolbar', None)
            if tb is not None:
                tb.setVisible(not empty)
            if not empty:
                return
            # 第 3 步的说法随模式变（寿命模式的主操作是「开始拟合」而不是预览）
            descs = getattr(self, 'empty_step_descs', None)
            if descs is not None and len(descs) >= 3:
                if getattr(self, 'spectrum_type', '') == 'lifetime':
                    descs[2].setText(self._EMPTY_STEP3_LIFETIME)
                else:
                    descs[2].setText(self._EMPTY_STEPS[2][2])
            folder = getattr(self, 'current_folder', None)
            if folder:
                self.empty_title.setText("该文件夹没有解析出可用数据")
                self.empty_hint.setText(
                    f"{self._short_path(str(folder))}\n"
                    "换一个文件夹，或按 F1 查看当前模式支持的数据格式")
            else:
                self.empty_title.setText("还没有加载数据")
                self.empty_hint.setText(
                    "把数据文件夹拖到窗口上，或点下面的按钮选择")
        except Exception as e:
            log_exception("切换空状态失败", e)

    def _help_mode_section(self):
        """按当前模式返回帮助正文里的一段 HTML（E3）。"""
        mode = getattr(self, 'spectrum_type', 'absorption')
        if mode == 'lifetime':
            return (
                "<p><b>荧光寿命（Lifetime）模式</b></p><ul>"
                "<li><b>数据格式</b>：Horiba/DeltaHub 三列 CSV"
                "（time / decay / IRF，表头 Labels/Type/Start/Stop/Step），"
                "或多列 xlsx（时间 + 各样品列 + IRF，自动按列拆成多个数据集）</li>"
                "<li><b>主操作</b>：面板底部固定的「▶ 开始拟合」"
                "（单文件 MEM/SESM 拟合，约 1–2 分钟/文件）</li>"
                "<li><b>批量与导出</b>：「叠加分布」按钮（并行拟合后叠加对比）、"
                "「导出」菜单里的——导出当前拟合结果（PNG + 拟合结果 json）、"
                "跨样品汇总图、导出 PDF 报告；<b>菜单里的批量动作会复用已拟合的结果</b>，"
                "不会把同一批样品重复拟合</li>"
                "<li><b>勾选＝统计范围</b>：数据栏的勾选框现在也出现在寿命模式，"
                "「叠加分布 / 跨样品汇总图 / PDF 报告」<b>只处理勾选的样品</b>——"
                "想看部分样品的对比就只勾它们；点一下某个文件名仍是单独拟合查看它</li>"
                "<li><b>参数固化</b>：「存为默认值」把当前拟合参数"
                "固定为下次启动的默认值</li>"
                "<li><b>参数</b>：拟合方法（MEM 最大熵 / SESM 平滑指数序列）、"
                "速率网格点数、k 范围（τ = 1/k）、"
                "「自动拟合 λ」（每次启动默认勾选，程序扫描最优熵权重）、"
                "固定 τ（逗号分隔，作为不受熵约束的基函数）</li>"
                "<li><b>F5 行为</b>：本模式下 F5 = <b>开始拟合</b>"
                "（不是普通预览；拟合约 1–2 分钟，会弹出带「取消」的进度框）</li>"
                "<li><b>拟合质量怎么看</b>：χ²R 的分母是拟合点数 M（不是自由度 ν）；"
                "残差自相关 ACF 应落在 ±1.96/√N 置信带内；"
                "Durbin–Watson &lt; 1.5 说明残差正相关、模型可能不足</li></ul>")
        if mode == 'scan3d':
            return (
                "<p><b>3D 扫描（EEM）模式</b></p><ul>"
                "<li><b>数据格式</b>：EEM CSV，表头形如 EM(nm)\\EX(nm) 的二维矩阵</li>"
                "<li><b>专属选项</b>：绘图类型（3D 曲面 / 等高线 / Waterfall）、"
                "去尖峰窗口、σ_em / σ_ex 高斯平滑、对数色标、梳状伪迹处理</li>"
                "<li><b>操作</b>：在「数据」栏点选一个文件即绘制（一次只画一个）</li>"
                "<li><b>F5 行为</b>：重新绘制当前 EEM 图（不做拟合）</li></ul>")
        if mode == 'emission':
            return (
                "<p><b>发射光谱（Emission）模式</b></p><ul>"
                "<li><b>数据格式</b>：仪器导出的发射光谱 CSV/TXT（含激发波长信息）</li>"
                "<li><b>专属选项</b>：「发射光谱选项」组——归一化强度、"
                "标注激发波长 (EX)</li>"
                "<li><b>通用功能</b>：合并图 / 单独图、峰检测、显示范围、"
                "光谱减法、光谱积分</li>"
                "<li><b>数据比较</b>：文件夹里有 <b>说明.xlsx</b> 时，"
                "按某个变量（如 RB浓度）画「峰强度 / 峰面积 / 指定波长强度」"
                "点线图，可再用一个变量分组；图在「数据比较」标签页。"
                "只统计左侧勾选的样品，说明.xlsx 里为空的变量不参与（该样品自动跳过）</li>"
                "<li><b>F5 行为</b>：实时预览（重新绘制，不拟合）</li></ul>")
        return (
            "<p><b>吸收光谱（UV-Vis）模式</b></p><ul>"
            "<li><b>数据格式</b>：吸收光谱 CSV/TXT（波长 + 吸收值两列；"
            "带仪器元数据头也能自动跳过）</li>"
            "<li><b>专属功能</b>：合并图 / 单独图、峰检测（最小峰高 / 最小峰距）、"
            "显示范围、光谱减法（A − B 差谱或各减本底）、光谱积分（数据输出区）</li>"
            "<li><b>数据比较</b>：文件夹里有 <b>说明.xlsx</b> 时，"
            "按某个变量（如浓度）画「最大吸收 / 吸收峰面积 / 指定波长吸光度」"
            "点线图，可再用一个变量分组；图在「数据比较」标签页</li>"
            "<li><b>F5 行为</b>：实时预览（重新绘制，不拟合）</li></ul>")

    def show_help(self):
        """F1 帮助（主窗口内）：非模态、可滚动的主题化帮助窗口（v4.24）。

        原来用 `QMessageBox.about()` 弹一次性富文本：实测 722×600 逻辑像素、
        占可用高度 70%，不可滚动、不可复制、宽度不可调，内容再长就溢出。
        现改为 `gui_help.HelpDialog`（左侧小节目录 + 可滚动正文 + 搜索 +
        复制全部 + 打开日志文件夹），深浅主题都走 theme_palette()。
        """
        from gui_log import log_dir
        from gui_help import show_help_dialog
        shortcuts = (
            "<ul>"
            "<li><b>F5</b> — 实时预览（寿命模式为开始拟合）</li>"
            "<li><b>Ctrl+R</b> — 重新加载数据</li>"
            "<li><b>Ctrl+O</b> — 选择文件夹</li>"
            "<li><b>Ctrl+E / Ctrl+S</b> — 导出当前图</li>"
            "<li><b>Ctrl+Shift+E</b> — 导出全部图片</li>"
            "<li><b>Ctrl+D</b> — 复制积分结果</li>"
            "<li><b>Ctrl+F</b> — 跳到文件搜索框（数据栏折叠时会自动展开）</li>"
            "<li><b>Ctrl+T</b> — 切换浅色 / 深色主题（也可点左上角的月亮/太阳图标）</li>"
            "<li><b>F1</b> — 本帮助</li>"
            "</ul>")
        others = (
            "<ul>"
            "<li><b>三栏折叠</b>：最左侧的「目/数/参」开关条可折叠目录树、数据、"
            "参数栏——折叠后画布变宽（三栏全折可到 1300px 左右，看大图/出图很实用）；"
            "栏宽与折叠状态会记住</li>"
            "<li><b>勾选＝统计范围</b>：光谱积分结果表、寿命模式的"
            "「叠加分布 / 跨样品汇总图 / PDF 报告」、「数据比较」点线图"
            "都只统计左侧<b>勾选</b>的样品——图上没有的样品不会再出现在结果里</li>"
            "<li><b>找样品</b>：数据栏顶部搜索框按文件名过滤，"
            "「全选」只勾当前筛选出来的结果，「全不选」再点一次即可</li>"
            "<li>把文件夹直接拖到窗口上也可以加载；目录树单击展开、"
            "<b>双击</b>加载该文件夹</li>"
            "<li>导出格式由「导出格式」下拉框决定（PNG / PDF / SVG 或其组合）；"
            "「导出用白底」勾选后导出图强制白底深字，"
            "深色主题下投稿/做 PPT 用得上</li>"
            "<li>「返回模块选择」（左上角房子图标）回到入口界面重新选模式；直接关窗则退出程序</li>"
            "<li>界面元素说明：鼠标悬停任意按钮/标签/下拉项都会显示 tooltip"
            "（被截断的文件名、完整路径也在这里看）</li>"
            "</ul>")
        return show_help_dialog(
            self,
            title=f"帮助 — {APP_NAME}",
            sections=[("当前模式", self._help_mode_section()),
                      ("快捷键", shortcuts),
                      ("其它", others)],
            palette=self.theme_palette(),
            subtitle=f"v{APP_VERSION} · {RELEASE_DATE}",
            log_text=f"日志（含加载失败原因、未捕获异常）：{log_dir()}")

    def _connect_live_update(self):
        """将所有参数控件连接到实时预览（防抖自动刷新）"""
        # 数值类控件：valueChanged 信号
        try:
            self.linewidth_spin.valueChanged.connect(self._trigger_live_update)
            self.dpi_spin.valueChanged.connect(self._trigger_live_update)
            self.peak_height_spin.valueChanged.connect(self._trigger_live_update)
            self.peak_distance_spin.valueChanged.connect(self._trigger_live_update)
            # 显示范围（波长上/下限已在控件创建处连接到实时预览）
        except AttributeError:
            pass

        # 复选框：stateChanged 信号
        try:
            self.mark_peaks_check.stateChanged.connect(self._trigger_live_update)
            self.normalize_check.stateChanged.connect(self._trigger_live_update)
            self.show_ex_check.stateChanged.connect(self._trigger_live_update)
        except AttributeError:
            pass

        # 下拉框：currentIndexChanged 信号
        try:
            self.plot_type_combo.currentIndexChanged.connect(self._trigger_live_update)
            # 换颜色方案 = 换色带，清空已记住的曲线颜色后重画
            self.color_combo.currentIndexChanged.connect(self.on_color_scheme_changed)
        except AttributeError:
            pass

        # 标题输入框：textChanged 信号
        try:
            self.title_edit.textChanged.connect(self._trigger_live_update)
        except AttributeError:
            pass

        # 文件列表勾选：itemChanged 触发（已在 on_item_checked 处理，这里统一走防抖）
        try:
            self.file_list.itemChanged.connect(self._trigger_live_update)
        except AttributeError:
            pass

    def _trigger_live_update(self, *args):
        """实时预览触发（防抖：300ms 内不重复触发）

        荧光寿命模式下单次拟合耗时 1–2 分钟，参数微调不做自动重拟合，
        只有点击「实时预览」按钮才启动拟合。
        """
        if getattr(self, 'spectrum_type', None) == "lifetime":
            return
        # 仅在有数据时才刷新
        if self.data_cache:
            self._live_timer.start()

    def on_lifetime_method_changed(self, *args):
        """拟合方法切换联动：λ（熵权重）只在 MEM 方法下有意义，SESM 时禁用。"""
        is_mem = "MEM" in self.lifetime_method_combo.currentText()
        self.lifetime_lambda_spin.setEnabled(is_mem
                                             and not self.lifetime_auto_lambda_check.isChecked())
        self.lifetime_auto_lambda_check.setEnabled(is_mem)

    def on_auto_lambda_toggled(self, checked):
        """「自动拟合 λ」勾选联动：自动拟合时 λ 输入框禁用（扫描代替手动值）。"""
        self.lifetime_lambda_spin.setEnabled(
            not checked and "MEM" in self.lifetime_method_combo.currentText())

    def create_tree_panel(self):
        """创建目录树面板：直接浏览电脑目录并点击选取文件夹"""
        # v4.29：本栏由 QDockWidget 承载，标题在 dock 标题栏上，这里不再套
        # QGroupBox（否则"目录树"会在标题栏和卡片标题上各写一遍、还会双层描边）
        panel = QWidget()
        root_layout = QVBoxLayout(panel)
        root_layout.setContentsMargins(10, 8, 10, 10)
        root_layout.setSpacing(8)
        # ---- 顶部三个等宽图标按钮（v4.24）----
        # 原来三个按钮宽度各不相同（160/160/自适应）且只有「帮助」是白底下拉按钮，
        # 左边缘参差、三种视觉语言混在一起。现在统一成 ghost 图标按钮 + tooltip，
        # 尺寸一致、排成一行，说明文字放进 tooltip 不再占版面。
        top_row = QHBoxLayout()
        top_row.setSpacing(6)

        home_btn = QPushButton()
        self.home_btn = home_btn
        home_btn.setProperty("variant", "ghost")
        home_btn.setFixedSize(36, 30)
        home_btn.setIconSize(QSize(17, 17))
        home_btn.setCursor(Qt.PointingHandCursor)
        home_btn.setToolTip("返回模块选择（回到入口界面重新选模式）")
        home_btn.clicked.connect(self.return_to_launcher)
        top_row.addWidget(home_btn)

        # 主题切换（D3）：浅色 / 深色。图标由 _apply_ui_icons 按当前主题设置
        # （浅色界面显示月亮=切到深色，深色界面显示太阳=切回浅色）
        self.theme_btn = QPushButton()
        self.theme_btn.setProperty("variant", "ghost")
        self.theme_btn.setFixedSize(36, 30)
        self.theme_btn.setIconSize(QSize(17, 17))
        self.theme_btn.setCursor(Qt.PointingHandCursor)
        self.theme_btn.setToolTip("切换主题：浅色 / 深色 / 高对比打印友好（Ctrl+T）")
        self.theme_btn.clicked.connect(lambda: self.cycle_theme())
        top_row.addWidget(self.theme_btn)

        # 帮助菜单（D6）：快捷键说明 + 打开日志文件夹
        self.help_btn = QPushButton()
        self.help_btn.setProperty("variant", "ghost")
        self.help_btn.setFixedSize(36, 30)
        self.help_btn.setIconSize(QSize(17, 17))
        self.help_btn.setCursor(Qt.PointingHandCursor)
        self.help_btn.setToolTip("帮助：快捷键说明（F1）/ 打开日志文件夹")
        help_menu = QMenu(self.help_btn)
        act_help = QAction("快捷键与说明 (F1)", self.help_btn)
        act_help.triggered.connect(self.show_help)
        help_menu.addAction(act_help)
        act_log = QAction("打开日志文件夹", self.help_btn)
        act_log.triggered.connect(self._open_log_folder)
        help_menu.addAction(act_log)
        self.help_btn.setMenu(help_menu)
        top_row.addWidget(self.help_btn)
        top_row.addStretch(1)
        root_layout.addLayout(top_row)

        # 顶部：光谱类型切换
        type_label = QLabel("光谱类型:")
        type_label.setProperty("role", "sectionLabel")
        type_label.setToolTip("当前模块；四个模式各有专属参数与操作")
        root_layout.addWidget(type_label)
        self.spectrum_type_combo = QComboBox()
        # v4.24：括号里的英文名在 200px 栏里必被截断（旧文案会显示成
        # 「吸收光谱（UV-」），改为中文短名 + tooltip 给全称
        self.spectrum_type_combo.addItems([
            "吸收光谱",
            "发射光谱",
            "荧光寿命",
            "3D 扫描",
        ])
        for _i, _tip in enumerate([
                "吸收光谱 (UV-Vis)：波长-吸收值，峰检测 / 差谱 / 积分",
                "发射光谱 (Emission)：发射谱绘图、EX 标注与归一化",
                "荧光寿命 (Lifetime)：MEM / SESM 最大熵寿命拟合",
                "3D 扫描 (EEM)：激发-发射矩阵曲面 / 等高线 / Waterfall"]):
            self.spectrum_type_combo.setItemData(_i, _tip, Qt.ToolTipRole)
        self.spectrum_type_combo.currentIndexChanged.connect(self.on_spectrum_type_changed)
        self._style_combo(self.spectrum_type_combo)
        root_layout.addWidget(self.spectrum_type_combo)

        # 数据文件夹：本栏唯一的主操作，独占一行（v4.24）
        # 原来「选择工作区」「选择文件夹」两个彩色实心按钮并排，在 200px 栏里
        # 每个只剩约 77px，中文标签被切掉一半（画面上显示成「; 工作」）。
        folder_btn = QPushButton("选择数据文件夹")
        folder_btn.clicked.connect(self.select_folder)
        folder_btn.setProperty("variant", "primary")
        folder_btn.setCursor(Qt.PointingHandCursor)
        folder_btn.setToolTip("选择数据文件夹并加载其中全部数据文件（Ctrl+O）")
        root_layout.addWidget(folder_btn)

        # 工作区（目录树的根目录）：低频操作，缩成路径行上的小图标按钮
        ws_row = QHBoxLayout()
        ws_row.setSpacing(4)
        self.workspace_label = QLabel("工作区: 未设置")
        self.workspace_label.setWordWrap(False)
        self.workspace_label.setProperty("role", "hint")
        ws_row.addWidget(self.workspace_label, 1)

        workspace_btn = QPushButton()
        self.workspace_btn = workspace_btn
        workspace_btn.setProperty("variant", "ghost")
        workspace_btn.setFixedSize(26, 22)
        workspace_btn.setIconSize(QSize(14, 14))
        workspace_btn.setCursor(Qt.PointingHandCursor)
        workspace_btn.setToolTip("选择工作区（左侧目录树的根目录，会记住）")
        workspace_btn.clicked.connect(self.select_workspace)
        ws_row.addWidget(workspace_btn, 0)
        root_layout.addLayout(ws_row)

        self.folder_label = QLabel("未选择文件夹")
        self.folder_label.setWordWrap(False)
        self.folder_label.setProperty("role", "folderLabel")
        root_layout.addWidget(self.folder_label)

        # 最近文件夹（D5）：下拉选择即加载
        recent_label = QLabel("最近文件夹:")
        recent_label.setProperty("role", "sectionLabel")
        root_layout.addWidget(recent_label)
        self.recent_combo = QComboBox()
        self.recent_combo.addItem("（无）")
        self.recent_combo.currentIndexChanged.connect(
            self.on_recent_folder_selected)
        self._style_combo(self.recent_combo)
        root_layout.addWidget(self.recent_combo)

        # 目录树（只显示目录、包含子文件夹；单击展开，双击加载数据，D2）
        tree_label = QLabel("目录（双击加载）")
        tree_label.setProperty("role", "sectionLabel")
        tree_label.setToolTip("单击展开子文件夹，双击该文件夹即加载其中数据")
        root_layout.addWidget(tree_label)
        self.file_system_model = QFileSystemModel()
        # 只显示目录（不含文件），提升浏览速度
        self.file_system_model.setFilter(QDir.AllDirs | QDir.NoDotAndDotDot)
        # 定位到工作区（上次记住的，否则默认），并在工作区下铺开显示子文件夹
        initial_root = self.workspace or DEFAULT_WORKSPACE
        self.file_system_model.setRootPath(initial_root)
        self.tree = QTreeView()
        self.tree.setModel(self.file_system_model)
        self.tree.setRootIndex(self.file_system_model.index(initial_root))
        self.tree.setHeaderHidden(True)
        self.tree.setColumnHidden(1, True)
        self.tree.setColumnHidden(2, True)
        self.tree.setColumnHidden(3, True)
        # D2：单击只展开/选中，双击才加载（旧实现单击即解析整个文件夹）
        self.tree.clicked.connect(self.on_tree_clicked)
        self.tree.doubleClicked.connect(self.on_tree_double_clicked)
        root_layout.addWidget(self.tree)
        # 单行短路径 + 完整路径 tooltip（v4.24：原来是整条长路径自动换行占 3 行）
        self.workspace_label.setText(f"工作区: {self._short_path(initial_root)}")
        self.workspace_label.setToolTip(f"工作区（目录树根目录）:\n{initial_root}")

        return panel

    def create_file_panel(self):
        """创建文件列表面板：已加载的数据文件（勾选以绘制合并图）"""
        # v4.29：同 create_tree_panel，标题交给 dock 标题栏
        panel = QWidget()
        root_layout = QVBoxLayout(panel)
        root_layout.setContentsMargins(10, 8, 10, 10)
        root_layout.setSpacing(8)
        # v4.24：标题缩短——原文案「已加载的文件（勾选以绘制合并图）:」在 210px
        # 栏里必被截断，说明移到 tooltip；各模式的完整提示仍由 gui_data 写入 tooltip
        file_list_label = QLabel("已加载文件")
        file_list_label.setProperty("role", "sectionLabel")
        file_list_label.setToolTip("勾选以绘制合并图（寿命/3D 模式为点选单个文件）")
        self.file_list_label = file_list_label  # 文案随模式切换（见 gui_data.on_spectrum_type_changed）
        root_layout.addWidget(file_list_label)

        # 搜索框（v4.26）：一次加载几十个样品后，列表靠滚动找文件太慢
        self.file_search_edit = QLineEdit()
        self.file_search_edit.setPlaceholderText("搜索文件名…")
        self.file_search_edit.setClearButtonEnabled(True)
        self.file_search_edit.setToolTip(
            "按文件名过滤下面的列表（不区分大小写）\n"
            "只影响显示，不会取消已勾选的样品")
        self.file_search_edit.textChanged.connect(self.on_file_search_changed)
        root_layout.addWidget(self.file_search_edit)

        self.file_list = QListWidget()
        self.file_list.setMinimumHeight(140)
        self.file_list.itemClicked.connect(self.on_file_selected)
        self.file_list.itemChanged.connect(self.on_item_checked)
        root_layout.addWidget(self.file_list)

        # 全选 / 全不选 + 计数（v4.26）：按钮文字随状态切换，省一行宽度
        sel_row = QHBoxLayout()
        sel_row.setSpacing(6)
        self.file_select_btn = QPushButton("全选")
        self.file_select_btn.setProperty("variant", "secondary")
        self.file_select_btn.setCursor(Qt.PointingHandCursor)
        self.file_select_btn.setToolTip(
            "勾选列表里的全部样品；有搜索词时只勾筛选出来的结果\n"
            "全部勾选后按钮变为「全不选」")
        self.file_select_btn.clicked.connect(self.toggle_select_all_visible)
        sel_row.addWidget(self.file_select_btn, 0)
        self.file_count_label = QLabel("已加载 0 个文件")
        self.file_count_label.setProperty("role", "hint")
        sel_row.addWidget(self.file_count_label, 1)
        root_layout.addLayout(sel_row)

        reload_btn = QPushButton("重新加载数据")
        reload_btn.clicked.connect(self.reload_data)
        reload_btn.setProperty("variant", "primary")
        reload_btn.setCursor(Qt.PointingHandCursor)
        root_layout.addWidget(reload_btn)

        return panel

    def create_param_panel(self):
        """创建绘图参数面板 + 操作按钮。

        外层为普通 QWidget：「操作」按钮组固定在面板下方（滚动区之外，
        任何时刻都可见）；绘图参数组内容较长，放进 QScrollArea 滚动查看。
        v4.29：本栏由 QDockWidget 承载，不再套「绘图参数」QGroupBox——
        各参数分组（发射光谱选项 / 寿命拟合 …）直接落在 dock 卡片上。
        """
        # 外层控件（放入 dock）
        panel = QWidget()
        outer = QVBoxLayout(panel)
        # 边距与目录树/数据两栏对齐
        outer.setContentsMargins(10, 8, 10, 10)
        outer.setSpacing(10)

        # 进度条（v4.27 起移到状态栏里，见 setup_ui）——参数栏顶部不再占一行

        # 参数内容控件（放进下方滚动区）
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # 绘图参数（v4.29：原「绘图参数」QGroupBox 由 dock 卡片取代）
        param_group = QWidget()
        param_layout = QVBoxLayout(param_group)
        param_layout.setContentsMargins(0, 0, 0, 0)
        param_layout.setSpacing(10)

        # 图表类型
        label = QLabel("图表类型:")
        param_layout.addWidget(label)
        self.plot_type_label = label
        self.plot_type_combo = QComboBox()
        self.plot_type_combo.addItems(["合并图 (Combined)", "单独图 (Single)"])
        self.plot_type_combo.currentIndexChanged.connect(self.on_plot_type_changed)
        self._style_combo(self.plot_type_combo)
        param_layout.addWidget(self.plot_type_combo)

        # 自定义标题
        label = QLabel("绘图标题:")
        font = label.font()
        font.setPointSize(15)
        label.setFont(font)
        param_layout.addWidget(label)
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("留空使用默认标题")
        self.title_edit.setStyleSheet("font-size: 13px; padding: 5px;")
        self.title_edit.textChanged.connect(self.on_title_changed)
        param_layout.addWidget(self.title_edit)

        # 线宽（带滑块）
        label = QLabel("线宽:")
        param_layout.addWidget(label)
        self.linewidth_spin = SliderSpin(0.5, 5.0, 1.5, 0.1, scale=10, decimals=1, suffix="")
        param_layout.addWidget(self.linewidth_spin)

        # DPI（带滑块；导出图片的分辨率，默认 600 dpi，最高 1200）
        label = QLabel("DPI:")
        param_layout.addWidget(label)
        self.dpi_spin = SliderSpin(72, 1200, 600, 10, scale=1, decimals=0, suffix="")
        param_layout.addWidget(self.dpi_spin)

        # 导出格式（PNG 位图 / PDF、SVG 矢量，可多选组合）
        param_layout.addWidget(QLabel("导出格式:"))
        self.export_format_combo = QComboBox()
        self.export_format_combo.addItems([
            "PNG (位图)",
            "PDF (矢量)",
            "SVG (矢量)",
            "PNG + PDF",
            "PNG + SVG",
            "全部 (PNG+PDF+SVG)",
        ])
        self._style_combo(self.export_format_combo)
        param_layout.addWidget(self.export_format_combo)

        # 导出用白底：深色主题下界面是深底，但投稿图要白底，
        # 勾选后导出时临时切到白底配色（不影响界面显示）
        self.export_white_check = QCheckBox("导出用白底")
        self.export_white_check.setChecked(True)
        self.export_white_check.setToolTip(
            "勾选后导出的图片使用白底深字（适合投稿/PPT）；\n"
            "取消勾选则跟随当前界面主题（深色主题导出深底图）")
        param_layout.addWidget(self.export_white_check)

        # 出版图预设（D6）：一键切换导出图尺寸 + 字号缩放
        param_layout.addWidget(QLabel("出版图预设:"))
        self.pub_preset_combo = QComboBox()
        self.pub_preset_combo.addItems([
            "无（默认）",
            "单栏 (3.5 in)",
            "双栏 (7 in)",
            "幻灯片 (10×6)",
        ])
        self.pub_preset_combo.currentIndexChanged.connect(self._apply_pub_rc)
        self._style_combo(self.pub_preset_combo)
        param_layout.addWidget(self.pub_preset_combo)

        # 标记峰
        self.mark_peaks_check = QCheckBox("标记峰")
        self.mark_peaks_check.setChecked(True)
        param_layout.addWidget(self.mark_peaks_check)

        # 峰位标数值（D7）：关掉后峰上不再写波长数字
        self.peak_value_check = QCheckBox("峰位标数值")
        self.peak_value_check.setToolTip("在峰顶标注波长数值 (nm)")
        self.peak_value_check.setChecked(True)
        self.peak_value_check.stateChanged.connect(self._trigger_live_update)
        param_layout.addWidget(self.peak_value_check)

        # 发射光谱专用选项（默认隐藏，切换到发射时显示）
        emission_options = QVBoxLayout()
        emission_group = QGroupBox("发射光谱选项")
        self.normalize_check = QCheckBox("归一化强度")
        self.show_ex_check = QCheckBox("标注 EX")
        self.show_ex_check.setToolTip("标注激发波长 (EX)")
        emission_options.addWidget(self.normalize_check)
        emission_options.addWidget(self.show_ex_check)
        emission_group.setLayout(emission_options)
        self.emission_options_group = emission_group
        # 默认隐藏（切换到发射光谱时才显示）
        emission_group.setVisible(False)
        param_layout.addWidget(emission_group)

        # 荧光寿命专用选项（默认隐藏，切换到荧光寿命时显示）
        lifetime_options = QVBoxLayout()
        lifetime_method_label = QLabel("拟合方法:")
        lifetime_options.addWidget(lifetime_method_label)
        self.lifetime_method_combo = QComboBox()
        self.lifetime_method_combo.addItems([
            "MEM 最大熵（推荐）",
            "SESM 平滑指数（快）",
        ])
        self._style_combo(self.lifetime_method_combo)
        self.lifetime_method_combo.currentIndexChanged.connect(
            self.on_lifetime_method_changed)
        lifetime_options.addWidget(self.lifetime_method_combo)

        lifetime_rates_label = QLabel("网格点数:")
        lifetime_options.addWidget(lifetime_rates_label)
        self.lifetime_nrates_spin = QSpinBox()
        self.lifetime_nrates_spin.setRange(51, 401)
        self.lifetime_nrates_spin.setSingleStep(10)
        self.lifetime_nrates_spin.setValue(201)
        lifetime_options.addWidget(self.lifetime_nrates_spin)

        # 速率网格范围 k_min–k_max（k = 1/τ，单位 1/ns）
        # 上下排列（v4.22 修订）：并排一行最小宽度 188 px，是参数栏收不窄的主因。
        lifetime_options.addWidget(QLabel("k_min (1/ns):"))
        self.lifetime_kmin_spin = QDoubleSpinBox()
        self.lifetime_kmin_spin.setRange(1e-5, 10.0)
        self.lifetime_kmin_spin.setDecimals(5)
        self.lifetime_kmin_spin.setValue(0.01)
        self.lifetime_kmin_spin.setSingleStep(0.01)
        self.lifetime_kmin_spin.setMinimumWidth(84)
        lifetime_options.addWidget(self.lifetime_kmin_spin)

        lifetime_options.addWidget(QLabel("k_max (1/ns):"))
        self.lifetime_kmax_spin = QDoubleSpinBox()
        self.lifetime_kmax_spin.setRange(0.1, 1000.0)
        self.lifetime_kmax_spin.setDecimals(2)
        self.lifetime_kmax_spin.setValue(100.0)
        self.lifetime_kmax_spin.setSingleStep(1.0)
        self.lifetime_kmax_spin.setMinimumWidth(84)
        lifetime_options.addWidget(self.lifetime_kmax_spin)

        # 固定寿命分量（不受熵约束的额外基函数）
        lifetime_options.addWidget(QLabel("固定 τ:"))
        self.lifetime_fixed_taus_edit = QLineEdit()
        self.lifetime_fixed_taus_edit.setPlaceholderText(
            "留空 = 不固定；例：3.6 或 0.5, 3.6")
        lifetime_options.addWidget(self.lifetime_fixed_taus_edit)

        # 熵权重 λ（MEM 目标函数 chi² - λ·S 中的 λ）：可手动修改，
        # 也可勾选「自动拟合 λ」让程序扫描最优值（对数滑块，跨 6 个数量级）
        lambda_label = QLabel("λ (MEM):")
        lifetime_options.addWidget(lambda_label)
        self.lifetime_lambda_spin = SliderSpin(
            1e-6, 1.0, 1e-3, 1e-6, decimals=6, logscale=True)
        lifetime_options.addWidget(self.lifetime_lambda_spin)

        self.lifetime_auto_lambda_check = QCheckBox("自动拟合 λ")
        self.lifetime_auto_lambda_check.setToolTip(
            "推荐：程序按当前 λ 拟合后扫描 χ²R ≤ 1.1 的最大 λ 再重拟合")
        self.lifetime_auto_lambda_check.setChecked(True)   # 默认勾选（用户要求）
        self.lifetime_auto_lambda_check.toggled.connect(
            self.on_auto_lambda_toggled)
        lifetime_options.addWidget(self.lifetime_auto_lambda_check)
        self.on_auto_lambda_toggled(True)                  # 同步禁用 λ 输入框

        # 存为默认值（v4.22 修订）：把当前拟合参数固定为每次启动的默认值
        self.lifetime_save_defaults_btn = QPushButton("存为默认值")
        self.lifetime_save_defaults_btn.setProperty("variant", "secondary")
        self.lifetime_save_defaults_btn.setCursor(Qt.PointingHandCursor)
        self.lifetime_save_defaults_btn.setToolTip(
            "把当前荧光寿命拟合参数存为默认值，下次启动自动套用：\n"
            "拟合方法、速率网格点数、k 范围、固定 τ、λ 与自动拟合 λ。\n"
            "临时改动不会自动变成默认值——想改默认值就再点一次本按钮。")
        self.lifetime_save_defaults_btn.clicked.connect(
            self._save_lifetime_defaults)
        lifetime_options.addWidget(self.lifetime_save_defaults_btn)

        # v4.25：「⏱ 开始拟合」从本组移到下方「操作」区的**主按钮**
        # （面板底部固定可见、不用滚动；寿命模式下它的文字会变成「▶ 开始拟合」）。
        # 这里不再放重复的拟合按钮，避免同一个动作有两个入口。

        # 并行拟合全部文件并叠加寿命分布对比（C1 + C8）
        self.lifetime_overlay_btn = QPushButton("叠加分布")
        self.lifetime_overlay_btn.setToolTip(
            "并行拟合全部文件后叠加寿命分布对比（已拟合过的样品直接复用结果）")
        self.lifetime_overlay_btn.setProperty("variant", "fit")
        self.lifetime_overlay_btn.setCursor(Qt.PointingHandCursor)
        self.lifetime_overlay_btn.clicked.connect(self._run_overlay_lifetime)
        lifetime_options.addWidget(self.lifetime_overlay_btn)

        lifetime_group = QGroupBox("寿命拟合")
        lifetime_group.setLayout(lifetime_options)
        self.lifetime_options_group = lifetime_group
        lifetime_group.setVisible(False)
        param_layout.addWidget(lifetime_group)

        # 3D 扫描（EEM）专用选项（默认隐藏，切换到 3D 扫描时显示）
        scan3d_options = QVBoxLayout()

        scan3d_options.addWidget(QLabel("绘图类型:"))
        self.scan3d_plot_combo = QComboBox()
        self.scan3d_plot_combo.addItems([
            "3D 曲面",
            "等高线 (俯视图)",
            "Waterfall 堆叠谱",
        ])
        self._style_combo(self.scan3d_plot_combo)
        scan3d_options.addWidget(self.scan3d_plot_combo)

        scan3d_options.addWidget(QLabel("条纹处理:"))
        self.scan3d_comb_combo = QComboBox()
        self.scan3d_comb_combo.addItems([
            "只保留谷值通道",
            "按乘性条纹除法",
            "污染整行替换",
            "不处理",
        ])
        self._style_combo(self.scan3d_comb_combo)
        scan3d_options.addWidget(self.scan3d_comb_combo)

        scan3d_options.addWidget(QLabel("去窄线:"))
        self.scan3d_despike_spin = SliderSpin(1, 15, 3, 1, scale=1, decimals=0)
        scan3d_options.addWidget(self.scan3d_despike_spin)

        scan3d_options.addWidget(QLabel("σ_EM:"))
        self.scan3d_sigma_em_spin = SliderSpin(0, 5, 1.0, 0.1, scale=10,
                                               decimals=1)
        scan3d_options.addWidget(self.scan3d_sigma_em_spin)

        scan3d_options.addWidget(QLabel("σ_EX:"))
        self.scan3d_sigma_ex_spin = SliderSpin(0, 5, 0.0, 0.1, scale=10,
                                               decimals=1)
        scan3d_options.addWidget(self.scan3d_sigma_ex_spin)

        self.scan3d_log_check = QCheckBox("对数色标")
        self.scan3d_log_check.setToolTip("强度跨数量级时更清楚")
        scan3d_options.addWidget(self.scan3d_log_check)

        scan3d_group = QGroupBox("3D 扫描")
        scan3d_group.setLayout(scan3d_options)
        self.scan3d_options_group = scan3d_group
        scan3d_group.setVisible(False)
        param_layout.addWidget(scan3d_group)

        # 3D 扫描参数改动即重绘（EEM 处理 <1 秒，无需像寿命那样显式触发）
        self.scan3d_plot_combo.currentIndexChanged.connect(self._trigger_live_update)
        self.scan3d_comb_combo.currentIndexChanged.connect(self._trigger_live_update)
        self.scan3d_despike_spin.valueChanged.connect(self._trigger_live_update)
        self.scan3d_sigma_em_spin.valueChanged.connect(self._trigger_live_update)
        self.scan3d_sigma_ex_spin.valueChanged.connect(self._trigger_live_update)
        self.scan3d_log_check.stateChanged.connect(self._trigger_live_update)

        # 峰检测参数（带滑块）
        peaks_layout = QVBoxLayout()
        peaks_layout.addWidget(QLabel("峰高度阈值:"))
        self.peak_height_spin = SliderSpin(0.01, 1.0, 0.05, 0.01, scale=100, decimals=2, suffix="")
        peaks_layout.addWidget(self.peak_height_spin)

        peaks_layout.addWidget(QLabel("峰最小间距:"))
        self.peak_distance_spin = SliderSpin(5, 50, 10, 1, scale=1, decimals=0, suffix=" nm")
        peaks_layout.addWidget(self.peak_distance_spin)

        peaks_group = QGroupBox("峰检测参数")
        peaks_group.setLayout(peaks_layout)
        self.peaks_group = peaks_group
        param_layout.addWidget(peaks_group)

        # 颜色方案
        param_layout.addWidget(QLabel("颜色方案:"))
        self.color_combo = QComboBox()
        self.color_combo.addItems([
            "默认 (Default)",
            "蓝-红 (Blue-Red)",
            "绿-紫 (Green-Purple)",
            "彩虹 (Rainbow)"
        ])
        self._style_combo(self.color_combo)
        param_layout.addWidget(self.color_combo)

        # 图例位置（避免遮挡曲线）
        param_layout.addWidget(QLabel("图例位置:"))
        self.legend_pos_combo = QComboBox()
        self.legend_pos_combo.addItems([
            "自动 (Auto)",
            "右上 (Upper Right)",
            "左上 (Upper Left)",
            "右下 (Lower Right)",
            "左下 (Lower Left)",
            "图外右上 (Outside Right)",
            "图外下方 (Outside Bottom)",
            "隐藏 (Hidden)"
        ])
        self.legend_pos_combo.setCurrentText("右上 (Upper Right)")
        self.legend_pos_combo.currentIndexChanged.connect(self._trigger_live_update)
        self._style_combo(self.legend_pos_combo)
        param_layout.addWidget(self.legend_pos_combo)

        # 图形比例（长宽比）
        ratio_label = QLabel("图形比例:")
        param_layout.addWidget(ratio_label)
        self.ratio_combo = QComboBox()
        self.ratio_combo.addItems([
            "自动 (随窗口)",
            "16:9",
            "16:10",
            "4:3",
            "3:2",
            "1:1",
            "2:1"
        ])
        self.ratio_combo.currentIndexChanged.connect(self._on_ratio_changed)
        self._style_combo(self.ratio_combo)
        param_layout.addWidget(self.ratio_combo)

        # 显示范围（波长上/下限）
        # 标签与输入框改为上下排列（v4.22 修订）：并排时「标签+输入框」最小
        # 宽度约 204 px，是参数栏收不窄的主因；上下排列后仅取决于输入框本身。
        range_group = QGroupBox("显示范围")
        range_layout = QVBoxLayout()

        range_layout.addWidget(QLabel("波长下限:"))
        self.wl_min_spin = QDoubleSpinBox()
        self.wl_min_spin.setRange(0, 3000)
        self.wl_min_spin.setValue(200)
        self.wl_min_spin.setDecimals(1)
        self.wl_min_spin.setSuffix(" nm")
        self.wl_min_spin.setSingleStep(10)
        self.wl_min_spin.setMinimumWidth(84)
        self.wl_min_spin.valueChanged.connect(self._trigger_live_update)
        range_layout.addWidget(self.wl_min_spin)

        range_layout.addWidget(QLabel("波长上限:"))
        self.wl_max_spin = QDoubleSpinBox()
        self.wl_max_spin.setRange(0, 3000)
        self.wl_max_spin.setValue(900)
        self.wl_max_spin.setDecimals(1)
        self.wl_max_spin.setSuffix(" nm")
        self.wl_max_spin.setSingleStep(10)
        self.wl_max_spin.setMinimumWidth(84)
        self.wl_max_spin.valueChanged.connect(self._trigger_live_update)
        range_layout.addWidget(self.wl_max_spin)

        # 自动范围按钮（E2）：只在首次加载某文件夹时自动设范围，之后想回到
        # 数据实际范围就点这里，不再每次加载都覆盖用户手填的区间
        self.auto_range_btn = QPushButton("自动范围")
        self.auto_range_btn.setToolTip("按已加载数据的实际波长范围重设上下限")
        self.auto_range_btn.setCursor(Qt.PointingHandCursor)
        self.auto_range_btn.setProperty("variant", "neutral")
        self.auto_range_btn.clicked.connect(self._on_auto_range_clicked)
        range_layout.addWidget(self.auto_range_btn)

        range_group.setLayout(range_layout)
        self.range_group = range_group
        param_layout.addWidget(range_group)

        # 光谱减法（两光谱相减 / 扣除本底；吸收与发射模式可用，寿命模式隐藏）
        subtract_group = QGroupBox("光谱减法")
        subtract_layout = QVBoxLayout()

        self.subtract_enable_check = QCheckBox("启用光谱减法")
        self.subtract_enable_check.stateChanged.connect(self._trigger_live_update)
        subtract_layout.addWidget(self.subtract_enable_check)

        subtract_layout.addWidget(QLabel("被减光谱 (A):"))
        self.subtract_minuend_combo = QComboBox()
        self.subtract_minuend_combo.currentIndexChanged.connect(self._trigger_live_update)
        self._style_combo(self.subtract_minuend_combo)
        # 第一项 = 所有光谱各减本底；选具体文件 = 只绘制 A − B 差谱
        self.subtract_minuend_combo.addItem("所有光谱（各减本底）")
        subtract_layout.addWidget(self.subtract_minuend_combo)

        subtract_layout.addWidget(QLabel("减数 (B):"))
        self.subtract_ref_combo = QComboBox()
        self.subtract_ref_combo.currentIndexChanged.connect(self._trigger_live_update)
        self._style_combo(self.subtract_ref_combo)
        subtract_layout.addWidget(self.subtract_ref_combo)

        # v4.36：一批数据里常混着不同发射窗口的光谱，扣不了本底的那些只跳过自己
        subtract_group.setToolTip(
            "A 选「所有光谱（各减本底）」= 每条光谱都减去 B 本底；\n"
            "A 选某个文件 = 只画 A − B 差谱（按重叠区间插值对齐）。\n"
            "样品与本底的波长范围没有重叠时无法相减：该条只跳过自己，\n"
            "其余光谱照常绘制/积分（跳过明细见状态栏与积分计数标签的悬停提示）。")

        subtract_group.setLayout(subtract_layout)
        self.subtract_group = subtract_group
        param_layout.addWidget(subtract_group)

        # 数据比较（v4.37）：按说明.xlsx 里某个变量的值画「指标-变量」点线图。
        # 只在吸收/发射模式显示（寿命/3D 没有"波长-强度"曲线也无变量可比）。
        compare_group = QGroupBox("数据比较（说明.xlsx）")
        compare_layout = QVBoxLayout()
        compare_layout.setSpacing(4)

        compare_layout.addWidget(QLabel("横轴变量:"))
        self.compare_x_combo = QComboBox()
        self._style_combo(self.compare_x_combo)
        self.compare_x_combo.setToolTip("说明.xlsx 中的数值列（如 RB浓度）；横轴用它的值")
        compare_layout.addWidget(self.compare_x_combo)

        compare_layout.addWidget(QLabel("分组变量 (可选):"))
        self.compare_group_combo = QComboBox()
        self._style_combo(self.compare_group_combo)
        self.compare_group_combo.setToolTip(
            "再选一个变量分组：每组画一条点线\n"
            "（例如横轴 RB浓度、按 L8i浓度 分组 → 每个 L8i 浓度一条曲线）")
        compare_layout.addWidget(self.compare_group_combo)

        compare_layout.addWidget(QLabel("纵轴指标:"))
        self.compare_metric_combo = QComboBox()
        self._style_combo(self.compare_metric_combo)
        self.compare_metric_combo.addItems(["峰强度", "峰面积", "指定波长处的值"])
        self.compare_metric_combo.setToolTip(
            "峰强度：指定区间内的最大强度\n"
            "峰面积：指定区间的梯形积分（复用下方「光谱积分」的起止波长）\n"
            "指定波长：该波长处线性插值取值")
        self.compare_metric_combo.currentIndexChanged.connect(
            self._on_compare_metric_changed)
        compare_layout.addWidget(self.compare_metric_combo)

        peak_row = QHBoxLayout()
        peak_row.setSpacing(4)
        peak_row.addWidget(QLabel("区间下限:"))
        self.compare_peak_lo_spin = QDoubleSpinBox()
        self.compare_peak_hi_spin = QDoubleSpinBox()
        for sp in (self.compare_peak_lo_spin, self.compare_peak_hi_spin):
            sp.setRange(0, 3000)
            sp.setDecimals(1)
            sp.setSuffix(" nm")
            sp.setSingleStep(10)
            sp.setValue(0.0)
            sp.setMinimumWidth(80)
        # v4.37：两行各一个 spin（而不是一行两个），否则本组最小宽度会把
        # 参数栏撑到 360px+，默认 285px 下 spin 的后缀「 nm」会被挤掉
        peak_row.addWidget(self.compare_peak_lo_spin)
        peak_row.addStretch()
        compare_layout.addLayout(peak_row)
        peak_row2 = QHBoxLayout()
        peak_row2.setSpacing(4)
        peak_row2.addWidget(QLabel("区间上限:"))
        peak_row2.addWidget(self.compare_peak_hi_spin)
        peak_row2.addStretch()
        compare_layout.addLayout(peak_row2)
        for sp in (self.compare_peak_lo_spin, self.compare_peak_hi_spin):
            sp.setToolTip("峰强度 / 峰面积的波长区间；两个都填 0 = 峰强度用全谱\n"
                          "（峰面积必须有区间，填 0 时自动复用下方「光谱积分」的起止波长）")

        wl_row = QHBoxLayout()
        wl_row.setSpacing(4)
        wl_row.addWidget(QLabel("指定波长:"))
        self.compare_wl_spin = QDoubleSpinBox()
        self.compare_wl_spin.setRange(0, 3000)
        self.compare_wl_spin.setDecimals(1)
        self.compare_wl_spin.setSuffix(" nm")
        self.compare_wl_spin.setSingleStep(5)
        self.compare_wl_spin.setValue(0.0)
        self.compare_wl_spin.setMinimumWidth(78)
        self.compare_wl_spin.setToolTip("纵轴选「指定波长处的值」时用这个波长")
        wl_row.addWidget(self.compare_wl_spin)
        wl_row.addStretch()
        compare_layout.addLayout(wl_row)

        compare_btns = QHBoxLayout()
        compare_btns.setSpacing(4)
        self.compare_btn = QPushButton("数据比较")
        self.compare_btn.setProperty("variant", "primary")
        self.compare_btn.setCursor(Qt.PointingHandCursor)
        self.compare_btn.setToolTip(
            "按说明.xlsx 的变量画点线图（只统计左侧勾选的样品）\n"
            "图在「数据比较」标签页")
        self.compare_btn.clicked.connect(self._run_compare)
        compare_btns.addWidget(self.compare_btn)
        self.compare_csv_btn = QPushButton("⤓ CSV")
        self.compare_csv_btn.setProperty("variant", "secondary")
        self.compare_csv_btn.setCursor(Qt.PointingHandCursor)
        self.compare_csv_btn.setToolTip("把点线图的取点结果导出为 CSV（UTF-8 BOM）")
        self.compare_csv_btn.clicked.connect(self._export_compare_csv)
        compare_btns.addWidget(self.compare_csv_btn)
        compare_layout.addLayout(compare_btns)

        compare_group.setLayout(compare_layout)
        self.compare_group = compare_group
        param_layout.addWidget(compare_group)

        layout.addWidget(param_group)

        # 参数内容放进可滚动区域（伸展吃满滚动区上方剩余空间）
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        scroll.setFrameShape(QFrame.NoFrame)
        outer.addWidget(scroll, 1)

        # 操作按钮组：固定在面板底部（滚动区之外，任何时刻都可见，无需滚动）
        # v4.25 按钮体系收口（设计方案 §5.1）：
        #   * 每屏只留 **1 个**实心主色按钮 = 本模式下真正的主操作
        #     （光谱/3D 模式 = 实时预览；寿命模式 = 开始拟合，文字随模式切换）
        #   * 其余动作改次级按钮（卡片底 + 描边），语义色不再整块填充
        #   * 原来 5 个实心彩色按钮（导出图片/导出全部/导出拟合结果/汇总图/PDF）
        #     合并进「💾 导出 ▾」一个下拉菜单
        action_group = QGroupBox("操作")
        action_layout = QVBoxLayout()
        action_layout.setSpacing(8)

        self.preview_btn = QPushButton("实时预览")
        self.preview_btn.setProperty("variant", "primary")
        self.preview_btn.setIconSize(QSize(15, 15))
        self.preview_btn.setCursor(Qt.PointingHandCursor)
        self.preview_btn.setToolTip(
            "按当前参数重新绘图（F5）\n"
            "⚠️ 荧光寿命模式下本按钮 = 开始拟合（约 1–2 分钟/文件）")
        # 显式触发（explicit=True）：荧光寿命模式下只有该按钮才真正启动拟合
        self.preview_btn.clicked.connect(lambda: self.update_plot(explicit=True))
        action_layout.addWidget(self.preview_btn)

        # 导出：5 个动作合并成一个菜单（v4.25，原本是 5 个彩色实心按钮排成一列）
        self.export_menu_btn = QPushButton("导出")
        self.export_menu_btn.setProperty("variant", "export")
        self.export_menu_btn.setCursor(Qt.PointingHandCursor)
        self.export_menu_btn.setToolTip(
            "导出当前图 / 全部图片 / 拟合结果 / 跨样品汇总图 / PDF 报告")
        export_menu = QMenu(self.export_menu_btn)
        export_menu.setToolTipsVisible(True)

        self.act_export_current = QAction("导出当前图　(Ctrl+E)", self.export_menu_btn)
        self.act_export_current.setToolTip("把当前画布上的图存成 PNG/PDF/SVG（按「导出格式」）")
        self.act_export_current.triggered.connect(self.export_plot)
        export_menu.addAction(self.act_export_current)

        self.act_export_all = QAction("导出全部图片　(Ctrl+Shift+E)", self.export_menu_btn)
        self.act_export_all.setToolTip("把当前文件夹每个文件各存一张图到导出目录")
        self.act_export_all.triggered.connect(self.export_all_plots)
        export_menu.addAction(self.act_export_all)

        # 分隔线也要跟着一起隐藏，否则非寿命模式下菜单底部会留一条空线。
        # 注意：创建时就得隐藏——程序启动若停在非寿命模式（索引 0），
        # currentIndexChanged 不会触发，on_spectrum_type_changed 就不会跑，
        # 这一条会一直露在菜单底部（v4.25 回归测试抓到）。
        self.act_export_sep = export_menu.addSeparator()
        self.act_export_sep.setVisible(False)

        # 以下三条只在荧光寿命模式显示（gui_data.on_spectrum_type_changed 控制）
        self.act_export_fit = QAction(
            "导出当前拟合结果（PNG + json）", self.export_menu_btn)
        self.act_export_fit.setToolTip("当前样品的拟合图 + 拟合结果 json（含 τ、占比、χ²R）")
        self.act_export_fit.triggered.connect(self._export_lifetime_fit_results)
        self.act_export_fit.setVisible(False)
        export_menu.addAction(self.act_export_fit)

        self.act_summary_plot = QAction(
            "跨样品汇总图（τ / α / χ²R）", self.export_menu_btn)
        self.act_summary_plot.setToolTip(
            "并行拟合当前文件夹全部文件后，画「τ / 占比 / χ²R 随样品变化」的三联图\n"
            "适合滴定序列（如 FRET A0→A24）；已拟合过的样品直接复用结果")
        self.act_summary_plot.triggered.connect(self._run_summary_plot)
        self.act_summary_plot.setVisible(False)
        export_menu.addAction(self.act_summary_plot)

        self.act_pdf_report = QAction("导出 PDF 报告（每样品一页）", self.export_menu_btn)
        self.act_pdf_report.setToolTip(
            "汇总表 + χ²R 柱状图 + 每个样品一页（衰减拟合 + 寿命分布）；\n"
            "已拟合过的样品直接复用结果")
        self.act_pdf_report.triggered.connect(self._run_pdf_report)
        self.act_pdf_report.setVisible(False)
        export_menu.addAction(self.act_pdf_report)

        self.export_menu = export_menu
        self.export_menu_btn.setMenu(export_menu)
        action_layout.addWidget(self.export_menu_btn)

        action_group.setLayout(action_layout)
        outer.addWidget(action_group)

        return panel

    def create_canvas_panel(self):
        """创建右侧画布区域"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)

        # 创建标签页
        self.tab_widget = QTabWidget()
        # 副画布上的占位提示文字（切换主题时由 _apply_mpl_theme 统一换色）
        self._placeholder_texts = []

        # 预览标签页
        preview_tab = QWidget()
        preview_layout = QVBoxLayout(preview_tab)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(0)

        # 创建画布
        self.canvas = MplCanvas(self, width=8, height=5, dpi=100)
        # 缩放窗口后按新尺寸重算左边距（否则 y 轴标题会被裁到图外，v4.20）
        self.canvas.on_after_fit = lambda: self._refit_canvas_margins(self.canvas)
        # matplotlib 缩放/平移/重置工具栏
        self.toolbar = NavigationToolbar(self.canvas, self)
        self._decorate_nav_toolbar(self.toolbar)     # 中文 tooltip + 分组（v4.27）
        preview_layout.addWidget(self.toolbar)  # 固定工具条高度
        # 画布 / 空状态两页（v4.27）：没有数据时显示引导页而不是一张空图
        self.preview_stack = QStackedWidget()
        self.preview_stack.addWidget(self.canvas)                     # 0 = 画布
        self.preview_stack.addWidget(self._create_empty_state(preview_tab))  # 1 = 空状态
        preview_layout.addWidget(self.preview_stack, 1)  # stretch，吃满剩余空间

        self.tab_widget.addTab(preview_tab, "预览")

        # 寿命分布标签页：荧光寿命模式下单独显示寿命分布图（独立于拟合曲线画布）
        dist_tab = QWidget()
        dist_layout = QVBoxLayout(dist_tab)
        dist_layout.setContentsMargins(0, 0, 0, 0)
        dist_layout.setSpacing(0)
        self.lifetime_canvas = MplCanvas(self, width=8, height=3, dpi=100)
        self.lifetime_canvas.on_after_fit = lambda: self._refit_canvas_margins(
            self.lifetime_canvas)
        self.lifetime_toolbar = NavigationToolbar(self.lifetime_canvas, self)
        self._decorate_nav_toolbar(self.lifetime_toolbar)
        dist_layout.addWidget(self.lifetime_toolbar)
        dist_layout.addWidget(self.lifetime_canvas, 1)
        # 覆盖 MplCanvas 的初始提示文字
        self.lifetime_canvas.clear_fig()
        self.lifetime_canvas.axes = self.lifetime_canvas.fig.add_subplot(111)
        self._placeholder_texts.append(self.lifetime_canvas.axes.text(
            0.5, 0.5, "荧光寿命拟合完成后，寿命分布显示在这里",
            transform=self.lifetime_canvas.axes.transAxes,
            ha='center', va='center', fontsize=15,
            color=self.theme_palette()['MUTED']))
        self.lifetime_canvas.axes.set_axis_off()
        self.lifetime_canvas.fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
        self.tab_widget.addTab(dist_tab, "寿命分布")
        # 寿命分布页只在荧光寿命模式下显示（初始为吸收模式，隐藏）
        self.dist_tab = dist_tab
        self._set_dist_tab_visible(False)

        # 拟合诊断标签页：IRF/拟合区间 + 残差自相关（同样只在寿命模式显示）
        diag_tab = QWidget()
        diag_layout = QVBoxLayout(diag_tab)
        diag_layout.setContentsMargins(0, 0, 0, 0)
        diag_layout.setSpacing(0)
        self.diag_canvas = MplCanvas(self, width=8, height=5, dpi=100)
        self.diag_canvas.on_after_fit = lambda: self._refit_canvas_margins(
            self.diag_canvas)
        self.diag_toolbar = NavigationToolbar(self.diag_canvas, self)
        self._decorate_nav_toolbar(self.diag_toolbar)
        diag_layout.addWidget(self.diag_toolbar)
        diag_layout.addWidget(self.diag_canvas, 1)
        self.diag_canvas.clear_fig()
        self.diag_canvas.axes = self.diag_canvas.fig.add_subplot(111)
        self._placeholder_texts.append(self.diag_canvas.axes.text(
            0.5, 0.5, "拟合完成后，IRF / 拟合区间 / 残差自相关显示在这里",
            transform=self.diag_canvas.axes.transAxes,
            ha='center', va='center', fontsize=15,
            color=self.theme_palette()['MUTED']))
        self.diag_canvas.axes.set_axis_off()
        self.diag_canvas.fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
        self.tab_widget.addTab(diag_tab, "拟合诊断")
        self.diag_tab = diag_tab
        self._set_diag_tab_visible(False)

        # 数据比较标签页（v4.37）：按说明.xlsx 变量画「指标-变量」点线图，
        # 只在吸收/发射模式下显示
        compare_tab = QWidget()
        compare_tab_layout = QVBoxLayout(compare_tab)
        compare_tab_layout.setContentsMargins(0, 0, 0, 0)
        compare_tab_layout.setSpacing(0)
        self.compare_canvas = MplCanvas(self, width=8, height=5, dpi=100)
        self.compare_canvas.on_after_fit = lambda: self._refit_canvas_margins(
            self.compare_canvas)
        self.compare_toolbar = NavigationToolbar(self.compare_canvas, self)
        self._decorate_nav_toolbar(self.compare_toolbar)
        compare_tab_layout.addWidget(self.compare_toolbar)
        compare_tab_layout.addWidget(self.compare_canvas, 1)
        self.compare_canvas.clear_fig()
        self.compare_canvas.axes = self.compare_canvas.fig.add_subplot(111)
        self._placeholder_texts.append(self.compare_canvas.axes.text(
            0.5, 0.5,
            "点参数栏「数据比较」按钮，按说明.xlsx 的变量画强度-变量点线图",
            transform=self.compare_canvas.axes.transAxes,
            ha='center', va='center', fontsize=15,
            color=self.theme_palette()['MUTED']))
        self.compare_canvas.axes.set_axis_off()
        self.compare_canvas.fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
        self.tab_widget.addTab(compare_tab, "数据比较")
        self.compare_tab = compare_tab
        self._set_compare_tab_visible(False)

        # 信息标签页（v4.27 卡片化）：文件信息 / 拟合摘要（分量表 + 质量徽标）。
        # 原来是一整页纯文本 QLabel，字号一致、没有层级，一大片看不出重点；
        # 现在拆成两张卡片放进滚动区：上面是文件元数据（原文案原样保留），
        # 下面是拟合摘要——寿命拟合完成后才出现，带 ok/poor/failed 质量徽标。
        info_tab = QWidget()
        info_outer = QVBoxLayout(info_tab)
        info_outer.setContentsMargins(0, 0, 0, 0)
        info_scroll = QScrollArea()
        info_scroll.setWidgetResizable(True)
        info_scroll.setFrameShape(QFrame.NoFrame)
        info_body = QWidget()
        info_layout = QVBoxLayout(info_body)
        info_layout.setContentsMargins(10, 10, 10, 10)
        info_layout.setSpacing(10)

        file_card = QGroupBox("文件信息")
        file_card_layout = QVBoxLayout(file_card)
        self.info_label = QLabel("选择文件后显示详细信息")
        self.info_label.setWordWrap(True)
        self.info_label.setAlignment(Qt.AlignTop)
        # 允许框选复制（原来只能看，想抄一个数得手打）
        self.info_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.info_label.setProperty("role", "infoLabel")
        file_card_layout.addWidget(self.info_label)
        info_layout.addWidget(file_card)

        self.fit_card = QGroupBox("拟合摘要")
        fit_card_layout = QVBoxLayout(self.fit_card)
        fit_card_layout.setSpacing(6)
        head_row = QHBoxLayout()
        head_row.setSpacing(8)
        self.fit_badge = QLabel("未拟合")
        self.fit_badge.setProperty("role", "badge")
        self.fit_badge.setProperty("badgeState", "none")
        self.fit_badge.setToolTip(
            "拟合质量：ok = χ²R 接近 1 且收敛；poor = 偏差较大/未收敛；"
            "failed = χ²R 非有限")
        head_row.addWidget(self.fit_badge, 0)
        self.fit_quality_label = QLabel("")
        self.fit_quality_label.setProperty("role", "hint")
        self.fit_quality_label.setWordWrap(True)
        head_row.addWidget(self.fit_quality_label, 1)
        fit_card_layout.addLayout(head_row)

        self.fit_table = QTableWidget(0, 4)
        self.fit_table.setHorizontalHeaderLabels(
            ["分量", "τ (ns)", "强度占比 (%)", "振幅占比 (%)"])
        self.fit_table.verticalHeader().setVisible(False)
        self.fit_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.fit_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.fit_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.fit_table.setAlternatingRowColors(True)
        self.fit_table.setSortingEnabled(True)
        self.fit_table.setWordWrap(False)
        fhdr = self.fit_table.horizontalHeader()
        fhdr.setSectionResizeMode(0, QHeaderView.Stretch)
        for _c in (1, 2, 3):
            fhdr.setSectionResizeMode(_c, QHeaderView.ResizeToContents)
        self.fit_table.setMinimumHeight(90)
        self.fit_table.setMaximumHeight(220)
        self.fit_table.setToolTip(
            "分离出的寿命分量；点表头可排序，框选后 Ctrl+C 复制。\n"
            "强度占比 = 发光强度贡献（分布下面积，各分量和 100%），"
            "振幅占比 = 分量峰高（按最大者归一）")
        fit_card_layout.addWidget(self.fit_table)
        self.fit_card.setVisible(False)      # 没拟合过就不显示（含它占的空间）
        info_layout.addWidget(self.fit_card)
        info_layout.addStretch(1)
        info_scroll.setWidget(info_body)
        info_outer.addWidget(info_scroll)
        self.tab_widget.addTab(info_tab, "信息")

        layout.addWidget(self.tab_widget, 1)  # 填满垂直空间

        # 数据输出区（绘图区下方）：光谱积分参数与结果合一，始终可见、可查看/复制。
        # 不放进左/中参数面板——那两栏内容超长需要滚动，放那里默认视图看不见。
        integ_group = QGroupBox("光谱积分（数据输出）")
        integ_layout = QVBoxLayout(integ_group)
        integ_layout.setSpacing(6)

        integ_ctrl = QHBoxLayout()
        integ_ctrl.setSpacing(6)
        integ_ctrl.addWidget(QLabel("起始:"))
        self.integ_min_spin = QDoubleSpinBox()
        self.integ_min_spin.setRange(0, 3000)
        self.integ_min_spin.setValue(450)
        self.integ_min_spin.setDecimals(1)
        self.integ_min_spin.setSuffix(" nm")
        self.integ_min_spin.setSingleStep(10)
        self.integ_min_spin.setMinimumWidth(100)
        self.integ_min_spin.valueChanged.connect(self._trigger_live_update)
        integ_ctrl.addWidget(self.integ_min_spin)
        integ_ctrl.addWidget(QLabel("结束:"))
        self.integ_max_spin = QDoubleSpinBox()
        self.integ_max_spin.setRange(0, 3000)
        self.integ_max_spin.setValue(550)
        self.integ_max_spin.setDecimals(1)
        self.integ_max_spin.setSuffix(" nm")
        self.integ_max_spin.setSingleStep(10)
        self.integ_max_spin.setMinimumWidth(100)
        self.integ_max_spin.valueChanged.connect(self._trigger_live_update)
        integ_ctrl.addWidget(self.integ_max_spin)
        self.integ_count_label = QLabel("未计算")
        self.integ_count_label.setProperty("role", "hint")
        integ_ctrl.addWidget(self.integ_count_label)
        integ_ctrl.addStretch()
        self.integ_copy_btn = QPushButton("复制结果")
        self.integ_copy_btn.setProperty("variant", "primary")
        self.integ_copy_btn.setCursor(Qt.PointingHandCursor)
        self.integ_copy_btn.setToolTip("把整张表复制到剪贴板（制表符分隔，可直接粘进 Excel/Origin）")
        self.integ_copy_btn.clicked.connect(self._copy_integration_results)
        integ_ctrl.addWidget(self.integ_copy_btn)

        # 导出 CSV（v4.26）：表格化之后顺手支持落地成文件
        self.integ_csv_btn = QPushButton("⤓ CSV")
        self.integ_csv_btn.setProperty("variant", "secondary")
        self.integ_csv_btn.setCursor(Qt.PointingHandCursor)
        self.integ_csv_btn.setToolTip("把积分结果导出为 CSV 文件（UTF-8 BOM，Excel 直接打开不乱码）")
        self.integ_csv_btn.clicked.connect(self._export_integration_csv)
        integ_ctrl.addWidget(self.integ_csv_btn)
        integ_layout.addLayout(integ_ctrl)

        # 结果表（v4.26）：原来是等宽文本的 QPlainTextEdit，像调试输出、不能排序、
        # 也没法只复制某几行。改成 QTableWidget——可排序、可框选、可复制局部。
        self.integ_table = QTableWidget(0, 3)
        self.integ_table.setHorizontalHeaderLabels(["样品", "区间 (nm)", "积分值"])
        self.integ_table.verticalHeader().setVisible(False)
        self.integ_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.integ_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.integ_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.integ_table.setAlternatingRowColors(True)
        self.integ_table.setSortingEnabled(True)      # 点表头排序
        self.integ_table.setWordWrap(False)
        hdr = self.integ_table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.Stretch)     # 样品名最宽
        hdr.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.integ_table.setMinimumHeight(110)
        self.integ_table.setMaximumHeight(240)
        self.integ_table.setToolTip(
            "梯形积分，用原始强度（不受归一化影响）；\n"
            "覆盖所有已加载样品（与左侧勾选无关），启用光谱减法时按扣本底后的曲线积分；\n"
            "点表头可排序，框选后 Ctrl+C 复制选中行")
        integ_layout.addWidget(self.integ_table)

        self.integ_group = integ_group
        layout.addWidget(integ_group)

        return panel

    def _set_tab_visible(self, tab, title, fallback_index, visible):
        """通用标签页显隐：Qt>=5.15 用 setTabVisible；旧版回退 removeTab/insertTab。"""
        if tab is None or not hasattr(self, 'tab_widget'):
            return
        if hasattr(self.tab_widget, 'setTabVisible'):
            self.tab_widget.setTabVisible(self.tab_widget.indexOf(tab), visible)
        else:
            idx = self.tab_widget.indexOf(tab)
            if visible and idx < 0:
                self.tab_widget.insertTab(fallback_index, tab, title)
            elif not visible and idx >= 0:
                if self.tab_widget.currentWidget() is tab:
                    self.tab_widget.setCurrentIndex(0)
                self.tab_widget.removeTab(idx)

    def _set_dist_tab_visible(self, visible):
        """「寿命分布」选项卡的显隐：只在荧光寿命模式下显示。"""
        self._set_tab_visible(getattr(self, 'dist_tab', None), "寿命分布", 1, visible)

    def _set_diag_tab_visible(self, visible):
        """「拟合诊断」选项卡的显隐：只在荧光寿命模式下显示。"""
        self._set_tab_visible(getattr(self, 'diag_tab', None), "拟合诊断", 2, visible)

    def _set_compare_tab_visible(self, visible):
        """「数据比较」选项卡的显隐：只在吸收/发射模式下显示。"""
        self._set_tab_visible(getattr(self, 'compare_tab', None), "数据比较", 3, visible)

    def _on_compare_metric_changed(self):
        """纵轴指标切换时，只启用对应需要的输入框。"""
        try:
            metric = self.compare_metric_combo.currentText()
            is_peak = metric.startswith('峰强')
            is_area = metric.startswith('峰面积')
            is_wl = metric.startswith('指定波长')
            for sp in (getattr(self, 'compare_peak_lo_spin', None),
                       getattr(self, 'compare_peak_hi_spin', None)):
                if sp is not None:
                    sp.setEnabled(is_peak or is_area)
            wl_spin = getattr(self, 'compare_wl_spin', None)
            if wl_spin is not None:
                wl_spin.setEnabled(is_wl)
        except Exception:
            pass

    @staticmethod
    def _load_style_icons():
        """加载预生成的 QSS 小图标（icons/ 目录下的静态 PNG，打包时随 --add-data 带上）。

        返回 (上箭头, 下箭头, 对勾, 下拉箭头) 的 url 供 QSS image 使用；
        某个文件缺失时对应项返回空串，apply_style 会省略相应 image 行。
        """
        def u(name):
            p = resource_path(f"icons/{name}")
            return Path(p).as_posix() if p else ""
        return (u("arrow-up.png"), u("arrow-down.png"),
                u("check.png"), u("chevron-down.png"))

    def theme_palette(self):
        """当前主题色板（D3），见 gui_config.THEMES。

        注意：不要改回 `_palette`——PlotMixin 里另有一个
        `_palette(color_map, n)`（按配色方案生成曲线颜色），
        两个混入同名会互相覆盖（UiMixin 在 MRO 前面，会让「单独图」
        和「差谱」直接报 TypeError，v4.20 修）。
        """
        from gui_config import THEMES, DEFAULT_THEME
        return THEMES.get(getattr(self, 'theme', DEFAULT_THEME),
                          THEMES[DEFAULT_THEME])

    def set_theme(self, name):
        """直接切到指定主题（三套：light / dark / contrast），v4.30。

        原来是 `toggle_theme(dark)` 两态开关，加第三套后统一走这里；
        `toggle_theme` 保留为薄封装（回归测试与老代码仍可用）。
        """
        from gui_config import THEMES, THEME_LABELS, THEME_ORDER
        if name not in THEMES:
            name = 'light'
        self.theme = name
        # 主题按钮改成单色图标（v4.28 起）。三态循环时图标显示的是
        # **点一下会切到的那套主题**：浅色→月亮、深色→高对比、高对比→太阳。
        # 具体图标在 apply_style → _apply_ui_icons 里统一设置。
        self._update_theme_btn_tip()
        self.apply_style()
        self._apply_mpl_theme()
        # 重绘一次让颜色跟上主题。注意：
        #  - 寿命模式若直接调 update_plot()，非 explicit 分支会 clear_fig 画提示文字，
        #    刚拟合好的结果会从画面上消失（缓存里还在，但用户会以为丢了）；
        #  - 也不能用 update_plot(explicit=True)，那会重新触发 1–2 分钟的拟合。
        # 所以有结果时只做"纯渲染"。
        try:
            if (getattr(self, 'spectrum_type', '') == 'lifetime'
                    and getattr(self, '_last_lifetime_result', None) is not None):
                self._render_lifetime_result(
                    self._last_lifetime_result,
                    self.linewidth_spin.value(),
                    self.title_edit.text().strip())
            else:
                self.update_plot()
        except Exception:
            pass
        if hasattr(self, 'status_bar'):
            label = THEME_LABELS.get(name, name)
            nxt = THEME_LABELS.get(self._next_theme(), '')
            self.status_bar.showMessage(f"已切换到「{label}」主题（再点一次切到「{nxt}」）")

    def _next_theme(self):
        """点一下主题按钮会切到哪套（按 THEME_ORDER 循环）。"""
        from gui_config import THEME_ORDER
        cur = getattr(self, 'theme', 'light')
        try:
            i = THEME_ORDER.index(cur)
        except ValueError:
            return THEME_ORDER[0]
        return THEME_ORDER[(i + 1) % len(THEME_ORDER)]

    def _theme_btn_icon_name(self):
        """主题按钮该显示哪个图标——显示**下一套**主题的象征物。

        浅色（下一套是深色）→ 月亮；深色（下一套是高对比）→ 对比度圆；
        高对比（下一套是浅色）→ 太阳。
        """
        return {'light': 'moon', 'dark': 'contrast', 'contrast': 'sun'}.get(
            getattr(self, 'theme', 'light'), 'moon')

    def _update_theme_btn_tip(self):
        """刷新主题按钮的 tooltip（三套循环，说明当前与下一套）。"""
        from gui_config import THEME_LABELS
        btn = getattr(self, 'theme_btn', None)
        if btn is None:
            return
        cur = THEME_LABELS.get(getattr(self, 'theme', 'light'), '')
        nxt = THEME_LABELS.get(self._next_theme(), '')
        btn.setToolTip(f"当前：{cur}主题 —— 点击切到「{nxt}」（Ctrl+T）")

    def cycle_theme(self):
        """主题按钮 / Ctrl+T：三套主题循环切换。"""
        self.set_theme(self._next_theme())

    def toggle_theme(self, dark=None):
        """切到浅色 / 深色（兼容入口）。

        dark=None 表示"互换浅色与深色"——现在界面上的主题按钮走
        `cycle_theme()` 三态循环，这个方法留给快捷键以外的老调用与回归测试。
        """
        if dark is None:
            dark = getattr(self, 'theme', 'light') != 'dark'
        self.set_theme('dark' if dark else 'light')

    def _apply_mpl_theme(self):
        """把主题配色应用到 matplotlib 全局参数与现有画布（D3）。"""
        import matplotlib as mpl
        P = self.theme_palette()
        spine = P.get('MPL_SPINE', P['MPL_GRID'])
        pairs = {
            'figure.facecolor': P['MPL_FIG'],
            'savefig.facecolor': P['MPL_FIG'],
            'axes.facecolor': P['MPL_AX'],
            'text.color': P['MPL_FG'],
            'axes.labelcolor': P['MPL_FG'],
            'axes.titlecolor': P['MPL_FG'],
            'xtick.color': P['MPL_FG'],
            'ytick.color': P['MPL_FG'],
            # 坐标轴边框（v4.20）：与网格线分开取色，深色主题用更亮的颜色，
            # 否则 #475569 边框压在 #1e293b 底色上几乎看不见。
            'axes.edgecolor': spine,
            'grid.color': P['MPL_GRID'],
            'legend.facecolor': P['MPL_AX'],
            'legend.edgecolor': spine,
            'legend.labelcolor': P['MPL_FG'],
            'figure.edgecolor': P['MPL_FIG'],
        }
        for k, v in pairs.items():
            try:
                mpl.rcParams[k] = v
            except Exception:
                pass
        for attr in ('canvas', 'lifetime_canvas', 'diag_canvas', 'compare_canvas'):
            cv = getattr(self, attr, None)
            if cv is None:
                continue
            try:
                cv.fig.set_facecolor(P['MPL_FIG'])
                for ax in cv.fig.axes:
                    ax.set_facecolor(P['MPL_AX'])
                    # 已存在的坐标轴也要跟着换边框颜色（切换主题时立即生效）
                    for sp in getattr(ax, 'spines', {}).values():
                        sp.set_color(spine)
                    try:
                        ax.tick_params(colors=P['MPL_FG'])
                    except Exception:
                        pass
                    # 既有文字（标题 / 轴标签 / 注释 / 刻度 / 图例）也要换色：
                    # rcParams 的 text.color 只影响此后新建的文字，切到深色后
                    # 旧文字会停在浅色主题的深色上（对 #0f172a 只有约 1.5:1）
                    texts = [getattr(ax, 'title', None),
                             getattr(ax.xaxis, 'label', None),
                             getattr(ax.yaxis, 'label', None)]
                    texts += list(getattr(ax, 'texts', []))
                    texts += list(ax.get_xticklabels()) + list(ax.get_yticklabels())
                    for t in texts:
                        try:
                            if t is not None and t.get_text():
                                t.set_color(P['MPL_FG'])
                        except Exception:
                            pass
                    leg = ax.get_legend()
                    if leg is not None:
                        try:
                            leg.get_frame().set_facecolor(P['MPL_AX'])
                            leg.get_frame().set_edgecolor(spine)
                            for t in leg.get_texts():
                                t.set_color(P['MPL_FG'])
                        except Exception:
                            pass
                    for gl in (ax.xaxis.get_gridlines() + ax.yaxis.get_gridlines()):
                        try:
                            gl.set_color(P['MPL_GRID'])
                            gl.set_alpha(P['MPL_GRID_ALPHA'])
                        except Exception:
                            pass
                # 画布控件自身底色同步（避免缩放/重绘瞬间闪白边）
                cv.setStyleSheet(f"background-color: {P['MPL_FIG']};")
                cv.draw_idle()
            except Exception:
                pass
        # 主画布 + 两个副画布上的占位提示文字也换色
        for t in (list(getattr(self, '_placeholder_texts', []))
                  + [getattr(getattr(self, 'canvas', None), '_placeholder', None)]):
            try:
                if t is not None:
                    t.set_color(P['MUTED'])
            except Exception:
                pass
        # matplotlib 导航工具栏图标是深灰 PNG，浅色主题下对比度仅约 2.5:1；
        # 用 QGraphicsColorizeEffect 统一染成主题前景色（形状保留、对比度达标）
        try:
            from PyQt5.QtWidgets import QGraphicsColorizeEffect, QToolButton
            from PyQt5.QtGui import QColor
            for tb_attr in ('toolbar', 'lifetime_toolbar', 'diag_toolbar'):
                tb = getattr(self, tb_attr, None)
                if tb is None:
                    continue
                for btn in tb.findChildren(QToolButton):
                    eff = QGraphicsColorizeEffect(btn)
                    eff.setColor(QColor(P['MPL_FG']))
                    eff.setStrength(1.0)
                    btn.setGraphicsEffect(eff)
        except Exception:
            pass

    def apply_style(self):
        """应用现代化样式（浅色/深色主题，色板见 gui_config.THEMES）"""
        P = self.theme_palette()
        (BG, CARD, BORDER, INPUT_BORDER, TEXT, TEXT_SOFT, MUTED,
         ACCENT, ACCENT_HOVER, ACCENT_PRESSED,
         SUCCESS, SUCCESS_HOVER, SUCCESS_PRESSED,
         VIOLET, VIOLET_HOVER, VIOLET_PRESSED,
         ORANGE, ORANGE_HOVER, ORANGE_PRESSED,
         CYAN, CYAN_HOVER, CYAN_PRESSED,
         NEUTRAL, NEUTRAL_HOVER, NEUTRAL_PRESSED,
         HOVER_BG, SELECT_BG, SELECT_FG, DISABLED_BG, DISABLED_FG,
         HANDLE, HANDLE_HOVER, ALT_ROW, INFO_BG, TOOLTIP_BG, TOOLTIP_FG,
         SUCCESS_BG, WARN_BG, DANGER, DANGER_BG) = (
            P['BG'], P['CARD'], P['BORDER'], P['INPUT_BORDER'], P['TEXT'],
            P['TEXT_SOFT'], P['MUTED'], P['ACCENT'], P['ACCENT_HOVER'],
            P['ACCENT_PRESSED'], P['SUCCESS'], P['SUCCESS_HOVER'],
            P['SUCCESS_PRESSED'], P['VIOLET'], P['VIOLET_HOVER'],
            P['VIOLET_PRESSED'], P['ORANGE'], P['ORANGE_HOVER'],
            P['ORANGE_PRESSED'], P['CYAN'], P['CYAN_HOVER'],
            P['CYAN_PRESSED'], P['NEUTRAL'], P['NEUTRAL_HOVER'],
            P['NEUTRAL_PRESSED'], P['HOVER_BG'], P['SELECT_BG'],
            P['SELECT_FG'], P['DISABLED_BG'], P['DISABLED_FG'],
            P['HANDLE'], P['HANDLE_HOVER'], P['ALT_ROW'], P['INFO_BG'],
            P['TOOLTIP_BG'], P['TOOLTIP_FG'],
            P.get('SUCCESS_BG', P['CARD']), P.get('WARN_BG', P['CARD']),
            P.get('DANGER', P['ORANGE']), P.get('DANGER_BG', P['CARD']))
        up_u, dn_u, ck_u, ch_u = self._load_style_icons()
        # 停靠面板标题栏的 × / 浮动按钮（v4.29）：图标分深浅两套，缺文件就
        # 省略对应行（QSS 里空 url 会让整条规则失效，宁可不写）。
        try:
            from gui_icons import icon_path as _icon_path
            _theme = getattr(self, 'theme', 'light')
            close_u = _icon_path("close", _theme, 24) or ""
            float_u = _icon_path("float", _theme, 24) or ""
        except Exception:
            close_u, float_u = "", ""
        close_img = (f"titlebar-close-icon: url({Path(close_u).as_posix()});"
                     if close_u else "")
        float_img = (f"titlebar-normal-icon: url({Path(float_u).as_posix()});"
                     if float_u else "")
        # 下拉弹窗的 item delegate 取色也要跟着主题走（否则深色下弹出一块白板）
        set_combo_palette(P)
        # 图标文件缺失时省略对应 image 行（QSS 里空 url 会使整条规则失效）
        up_img = f"image: url({up_u});" if up_u else ""
        dn_img = f"image: url({dn_u});" if dn_u else ""
        ck_img = f"image: url({ck_u});" if ck_u else ""
        ch_img = f"image: url({ch_u});" if ch_u else ""
        # 弹出菜单（v4.23）：QMenu 是独立的弹出窗口，只跟随 QPalette。
        # 此前 qss 里没有 QMenu 规则，深色主题下「❓ 帮助」下拉面板（以及
        # matplotlib 工具栏的菜单）仍按浅色 Fusion 默认色板绘制成一块近白面板
        # （#f9f9f9）——用户反馈的「深色模式下帮助面板背景还是浅色」。
        # 这段既进全局 qss，也由 apply_style 逐个下发到每个 QMenu（见文末）。
        menu_qss = f"""
            QMenu {{
                background-color: {CARD};
                color: {TEXT};
                border: 1px solid {BORDER};
                padding: 6px 5px;
            }}
            QMenu::item {{
                background: transparent;
                color: {TEXT};
                padding: 6px 26px 6px 14px;
                border-radius: 6px;
                font-size: 13px;
            }}
            QMenu::item:selected {{
                background-color: {SELECT_BG};
                color: {SELECT_FG};
            }}
            QMenu::item:disabled {{
                color: {DISABLED_FG};
            }}
            QMenu::separator {{
                height: 1px;
                background: {BORDER};
                margin: 6px 10px;
            }}
            QMenu::icon {{
                left: 8px;
            }}
            QMenu::indicator {{
                width: 14px;
                height: 14px;
                left: 10px;
            }}
        """
        qss = f"""
            /* ===== 全局底色 ===== */
            QMainWindow, QDialog {{
                background-color: {BG};
            }}
            QToolTip {{
                background-color: {TOOLTIP_BG};
                color: {TOOLTIP_FG};
                border: none;
                padding: 6px 10px;
                border-radius: 6px;
                font-size: 13px;
            }}

            /* ===== 弹出菜单（v4.23）=====
               QMenu 是独立的弹出窗口，只跟随 QPalette；此前 qss 里没有 QMenu 规则，
               于是深色主题下「❓ 帮助」下拉面板（以及 matplotlib 工具栏的菜单）
               仍按浅色 Fusion 默认色板绘制成一块近白面板（#f9f9f9）。
               规则本体抽成 menu_qss（见上方），这里引进来让全局样式表也覆盖到。 */
            {menu_qss}

            /* ===== 文字角色（随主题变色，D3）=====
               v4.25 字阶收口：控件正文 15–16px → 13px、标签 12px、辅助 11px。
               同一探针实测（寿命模式、三组均未隐藏）：
               v4.24 = 1230+575+294 = 2099px，v4.25 = 1100+494+126 = 1720px（−18%）。 */
            QLabel[role="sectionLabel"] {{
                font-size: 12px; font-weight: bold; color: {TEXT_SOFT};
            }}
            QLabel[role="folderLabel"] {{
                font-size: 11px; color: {TEXT_SOFT};
            }}
            QLabel[role="infoLabel"] {{
                font-size: 13px; color: {TEXT_SOFT};
            }}
            QLabel[role="hint"] {{
                font-size: 11px; color: {MUTED};
            }}
            /* 空状态引导页（v4.27）：整页只留一个焦点 */
            QLabel[role="emptyIcon"] {{
                font-size: 46px;
                color: {MUTED};
            }}
            QLabel[role="emptyTitle"] {{
                font-size: 16px; font-weight: bold; color: {TEXT_SOFT};
            }}
            /* 三步上手指引（v4.31）：三张并排小卡片 + 序号圆徽标 */
            QWidget[role="stepCard"] {{
                background-color: {CARD};
                border: 1px solid {BORDER};
                border-radius: 8px;
            }}
            QLabel[role="stepNo"] {{
                background-color: {ACCENT};
                color: {CARD};
                border-radius: 11px;
                font-size: 12px;
                font-weight: bold;
            }}
            QLabel[role="stepTitle"] {{
                font-size: 13px; font-weight: bold; color: {TEXT_SOFT};
            }}
            /* 徽标药丸（v4.27）：状态栏模式/样品数 + 拟合质量 ok/warn/bad */
            QLabel[role="badge"] {{
                background-color: {ALT_ROW};
                color: {TEXT_SOFT};
                border: 1px solid {BORDER};
                border-radius: 9px;
                padding: 1px 9px;
                font-size: 11px;
            }}
            QLabel[role="badge"][badgeState="ok"] {{
                background-color: {SUCCESS_BG};
                color: {SUCCESS};
                border: 1px solid {SUCCESS};
            }}
            QLabel[role="badge"][badgeState="warn"] {{
                background-color: {WARN_BG};
                color: {ORANGE};
                border: 1px solid {ORANGE};
            }}
            QLabel[role="badge"][badgeState="bad"] {{
                background-color: {DANGER_BG};
                color: {DANGER};
                border: 1px solid {DANGER};
            }}

            /* ===== 卡片式分组框 ===== */
            QGroupBox {{
                background-color: {CARD};
                border: 1px solid {BORDER};
                border-radius: 10px;
                margin-top: 14px;
                padding: 12px 10px 10px 10px;
                font-weight: bold;
                font-size: 14px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 12px;
                top: 3px;
                padding: 0 6px;
                color: {TEXT_SOFT};
            }}

            /* ===== 滚动区域（参数面板等）：viewport 与内容透明，露出窗口默认背景 ===== */
            QScrollArea {{
                background: transparent;
                border: none;
            }}
            QScrollArea > QWidget > QWidget {{
                background: transparent;
            }}

            /* ===== 文字 ===== */
            QLabel {{
                color: {TEXT};
                font-size: 13px;
                background: transparent;
            }}

            /* ===== 按钮：基础 + 语义色变体（variant 属性选择）===== */
            QPushButton {{
                background-color: {CARD};
                color: {TEXT};
                border: 1px solid {INPUT_BORDER};
                border-radius: 8px;
                padding: 6px 12px;
                font-size: 13px;
            }}
            /* 带菜单的按钮（「导出 ▾」）：隐藏 Qt 自带的箭头图标，
               由按钮文字里的 ▾ 表示可展开（v4.25） */
            QPushButton::menu-indicator {{
                image: none;
                width: 0px;
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
                background-color: {HOVER_BG};
                border-color: {BORDER};
            }}
            QPushButton[variant="primary"] {{
                background-color: {ACCENT};
                color: white;
                border: none;
                font-weight: bold;
            }}
            QPushButton[variant="primary"]:hover {{ background-color: {ACCENT_HOVER}; }}
            QPushButton[variant="primary"]:pressed {{ background-color: {ACCENT_PRESSED}; }}
            QPushButton[variant="success"] {{
                background-color: {SUCCESS};
                color: white;
                border: none;
                font-weight: bold;
            }}
            QPushButton[variant="success"]:hover {{ background-color: {SUCCESS_HOVER}; }}
            QPushButton[variant="success"]:pressed {{ background-color: {SUCCESS_PRESSED}; }}
            QPushButton[variant="violet"] {{
                background-color: {VIOLET};
                color: white;
                border: none;
                font-weight: bold;
            }}
            QPushButton[variant="violet"]:hover {{ background-color: {VIOLET_HOVER}; }}
            QPushButton[variant="violet"]:pressed {{ background-color: {VIOLET_PRESSED}; }}
            QPushButton[variant="orange"] {{
                background-color: {ORANGE};
                color: white;
                border: none;
                font-weight: bold;
            }}
            QPushButton[variant="orange"]:hover {{ background-color: {ORANGE_HOVER}; }}
            QPushButton[variant="orange"]:pressed {{ background-color: {ORANGE_PRESSED}; }}
            QPushButton[variant="cyan"] {{
                background-color: {CYAN};
                color: white;
                border: none;
                font-weight: bold;
            }}
            QPushButton[variant="cyan"]:hover {{ background-color: {CYAN_HOVER}; }}
            QPushButton[variant="cyan"]:pressed {{ background-color: {CYAN_PRESSED}; }}
            QPushButton[variant="neutral"] {{
                background-color: {NEUTRAL};
                color: white;
                border: none;
                font-weight: bold;
            }}
            QPushButton[variant="neutral"]:hover {{ background-color: {NEUTRAL_HOVER}; }}
            QPushButton[variant="neutral"]:pressed {{ background-color: {NEUTRAL_PRESSED}; }}
            /* 幽灵按钮（v4.24）：透明底 + 悬停浅底，用于图标按钮
               （目录树栏顶部的 🏠 / 🌓 / ❓）——既统一尺寸又不抢视觉 */
            QPushButton[variant="ghost"] {{
                background: transparent;
                border: 1px solid transparent;
                color: {TEXT_SOFT};
                padding: 2px;
                font-size: 15px;
            }}
            QPushButton[variant="ghost"]:hover {{
                background-color: {HOVER_BG};
                border-color: {BORDER};
            }}
            QPushButton[variant="ghost"]:pressed {{
                background-color: {DISABLED_BG};
            }}
            /* 次级按钮（v4.25）：卡片底 + 描边——大多数动作都属于这一档，
               语义色彩不再整块填充，改为左侧 3px 竖条（下面是 fit / export）。 */
            QPushButton[variant="secondary"] {{
                background-color: {CARD};
                color: {TEXT};
                border: 1px solid {INPUT_BORDER};
                border-radius: 8px;
                padding: 6px 12px;
                font-size: 13px;
            }}
            QPushButton[variant="secondary"]:hover {{
                background-color: {HOVER_BG};
                border-color: {HANDLE_HOVER};
            }}
            /* 拟合类动作：紫色语义条（原来整块紫底） */
            QPushButton[variant="fit"],
            QPushButton[variant="export"] {{
                background-color: {CARD};
                color: {TEXT};
                border: 1px solid {INPUT_BORDER};
                border-radius: 8px;
                padding: 6px 12px;
                font-size: 13px;
            }}
            QPushButton[variant="fit"] {{ border-left: 3px solid {VIOLET}; }}
            QPushButton[variant="export"] {{ border-left: 3px solid {ORANGE}; }}
            QPushButton[variant="fit"]:hover,
            QPushButton[variant="export"]:hover {{
                background-color: {HOVER_BG};
                border-color: {HANDLE_HOVER};
            }}
            QPushButton[variant="fit"]:hover {{ border-left: 3px solid {VIOLET}; }}
            QPushButton[variant="export"]:hover {{ border-left: 3px solid {ORANGE}; }}

            /* 栏开关条按钮（v4.26）：窄竖条，勾选态 = 该栏展开 */
            QPushButton[variant="rail"] {{
                background: transparent;
                border: 1px solid transparent;
                border-radius: 8px;
                color: {MUTED};
                padding: 0;
                font-size: 12px;
            }}
            QPushButton[variant="rail"]:hover {{
                background-color: {HOVER_BG};
                border-color: {BORDER};
                color: {TEXT};
            }}
            QPushButton[variant="rail"]:checked {{
                background-color: {SELECT_BG};
                border-color: {HANDLE_HOVER};
                color: {SELECT_FG};
                font-weight: bold;
            }}

            /* ===== 列表 / 目录树 ===== */
            QListWidget, QTreeView {{
                background-color: {CARD};
                border: 1px solid {BORDER};
                border-radius: 8px;
                padding: 4px;
                outline: 0;
                font-size: 13px;
            }}
            QListWidget::item, QTreeView::item {{
                padding: 4px;
                border-radius: 6px;
                color: {TEXT};
            }}
            QListWidget::item:hover, QTreeView::item:hover {{
                background-color: {HOVER_BG};
            }}
            QListWidget::item:selected, QTreeView::item:selected {{
                background-color: {SELECT_BG};
                color: {SELECT_FG};
            }}

            /* ===== 结果表格（v4.26：积分结果改表格）===== */
            QTableView {{
                background-color: {CARD};
                alternate-background-color: {ALT_ROW};
                border: 1px solid {BORDER};
                border-radius: 8px;
                gridline-color: {BORDER};
                color: {TEXT};
                font-size: 13px;
                outline: 0;
            }}
            QTableView::item:selected {{
                background-color: {SELECT_BG};
                color: {SELECT_FG};
            }}
            QHeaderView::section {{
                background-color: {ALT_ROW};
                color: {TEXT_SOFT};
                border: none;
                border-bottom: 1px solid {BORDER};
                padding: 5px 8px;
                font-size: 12px;
                font-weight: bold;
            }}

            /* ===== 输入控件 ===== */
            QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit,
            QPlainTextEdit, QTextEdit {{
                background-color: {CARD};
                border: 1px solid {INPUT_BORDER};
                border-radius: 6px;
                padding: 4px 8px;
                color: {TEXT};
                font-size: 13px;
            }}
            QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover, QLineEdit:hover,
            QPlainTextEdit:hover, QTextEdit:hover {{
                border-color: {HANDLE_HOVER};
            }}
            QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QLineEdit:focus,
            QPlainTextEdit:focus, QTextEdit:focus {{
                border: 1px solid {ACCENT};
            }}
            QComboBox::drop-down {{
                border: none;
                width: 26px;
            }}
            QComboBox::down-arrow {{
                {ch_img}
                width: 12px;
                height: 12px;
            }}
            /* 下拉弹出列表（popup 实为 QListView）：统一背景/边框 */
            QComboBox QAbstractItemView {{
                background-color: {CARD};
                border: 1px solid {BORDER};
                border-radius: 6px;
                outline: 0;
            }}
            /* 数值框：确保上下箭头按钮正常显示（提供 image 资源，防止按钮整块空白） */
            QSpinBox::up-button, QDoubleSpinBox::up-button,
            QSpinBox::down-button, QDoubleSpinBox::down-button {{
                border: none;
                background: {HOVER_BG};
                width: 18px;
            }}
            QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
            QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{
                background: {DISABLED_BG};
            }}
            QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
                {up_img}
                width: 12px;
                height: 12px;
            }}
            QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
                {dn_img}
                width: 12px;
                height: 12px;
            }}

            /* ===== 复选框 ===== */
            QCheckBox {{
                color: {TEXT_SOFT};
                font-size: 13px;
                padding: 3px;
                spacing: 7px;
                background: transparent;
            }}
            QCheckBox::indicator {{
                width: 15px;
                height: 15px;
                border: 2px solid {HANDLE_HOVER};
                border-radius: 4px;
                background-color: {CARD};
            }}
            QCheckBox::indicator:hover {{
                border-color: {ACCENT};
            }}
            QCheckBox::indicator:checked {{
                background-color: {ACCENT};
                border-color: {ACCENT};
                {ck_img}
            }}

            /* ===== 标签页 ===== */
            /* v4.24：给 pane 加 4px 内边距——画布 figure 底色（MPL_FIG）比卡片深，
               留出这圈"卡纸边"后画布才像一张嵌在卡片里的图纸，而不是挖了个洞 */
            QTabWidget::pane {{
                border: 1px solid {BORDER};
                border-radius: 10px;
                background-color: {CARD};
                top: -1px;
                padding: 4px;
            }}
            QTabBar::tab {{
                background: transparent;
                color: {MUTED};
                padding: 7px 18px;
                margin: 4px 4px 4px 0;
                border-radius: 8px;
                font-size: 13px;
            }}
            QTabBar::tab:selected {{
                background-color: {ACCENT};
                color: white;
                font-weight: bold;
            }}
            QTabBar::tab:hover:!selected {{
                background-color: {DISABLED_BG};
                color: {TEXT_SOFT};
            }}

            /* ===== 工具条（matplotlib 导航栏）===== */
            QToolBar {{
                background: transparent;
                border: none;
                padding: 2px 4px;
                spacing: 2px;
            }}
            QToolBar QToolButton {{
                background: transparent;
                border: none;
                border-radius: 6px;
                padding: 3px;
            }}
            QToolBar QToolButton:hover {{
                background-color: {DISABLED_BG};
            }}

            /* ===== 滑块 ===== */
            QSlider {{
                background: transparent;
                min-height: 22px;
            }}
            QSlider::groove:horizontal {{
                height: 6px;
                background: {DISABLED_BG};
                border-radius: 3px;
            }}
            QSlider::sub-page:horizontal {{
                background: {ACCENT};
                border-radius: 3px;
            }}
            QSlider::add-page:horizontal {{
                background: {DISABLED_BG};
                border-radius: 3px;
            }}
            QSlider::handle:horizontal {{
                width: 16px;
                height: 16px;
                margin: -6px 0;
                border-radius: 8px;
                background-color: white;
                border: 2px solid {ACCENT};
            }}
            QSlider::handle:horizontal:hover {{
                border-color: {ACCENT_HOVER};
                background-color: {INFO_BG};
            }}

            /* ===== 滚动条（纤细圆角）===== */
            QScrollBar:vertical {{
                background: transparent;
                width: 10px;
                margin: 2px;
            }}
            QScrollBar::handle:vertical {{
                background: {HANDLE};
                border-radius: 4px;
                min-height: 30px;
            }}
            QScrollBar::handle:vertical:hover {{ background: {HANDLE_HOVER}; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: transparent;
            }}
            QScrollBar:horizontal {{
                background: transparent;
                height: 10px;
                margin: 2px;
            }}
            QScrollBar::handle:horizontal {{
                background: {HANDLE};
                border-radius: 4px;
                min-width: 30px;
            }}
            QScrollBar::handle:horizontal:hover {{ background: {HANDLE_HOVER}; }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
                background: transparent;
            }}

            /* ===== 进度条 / 状态栏 / 分割线 ===== */
            QProgressBar {{
                background-color: {DISABLED_BG};
                border: none;
                border-radius: 7px;
                max-height: 14px;
                text-align: center;
                color: {TEXT_SOFT};
                font-size: 10px;
            }}
            QProgressBar::chunk {{
                background-color: {ACCENT};
                border-radius: 7px;
            }}
            QStatusBar {{
                background-color: {ALT_ROW};
                border-top: 1px solid {BORDER};
                font-size: 12px;
            }}
            QStatusBar QLabel {{
                color: {MUTED};
                font-size: 12px;
            }}
            /* ===== 停靠面板（v4.29：三栏由 QDockWidget 承载）=====
               标题栏 + 面板本体合成一张圆角卡片：标题栏画上半部分圆角，
               dockBody 画下半部分，中间不描边，看上去就是原来那张卡片。
               面板之间用 QMainWindow::separator 当拖动手柄（原来 splitter 的
               分隔条样式已随之取消）。 */
            QMainWindow::separator {{
                background: transparent;
                width: 6px;
                height: 6px;
            }}
            QMainWindow::separator:hover {{
                background: {SELECT_BG};
            }}
            QDockWidget {{
                color: {TEXT_SOFT};
                font-size: 13px;
                {close_img}
                {float_img}
            }}
            QDockWidget::title {{
                background-color: {CARD};
                border: 1px solid {BORDER};
                border-bottom: none;
                border-top-left-radius: 10px;
                border-top-right-radius: 10px;
                padding: 4px 8px;
                text-align: left;
                font-weight: bold;
                font-size: 13px;
                color: {TEXT_SOFT};
            }}
            QDockWidget::close-button, QDockWidget::float-button {{
                background: transparent;
                border: none;
                border-radius: 4px;
                padding: 1px;
                icon-size: 12px;
            }}
            QDockWidget::close-button:hover, QDockWidget::float-button:hover {{
                background-color: {HOVER_BG};
            }}
            QWidget[role="dockBody"] {{
                background-color: {CARD};
                border: 1px solid {BORDER};
                border-top: none;
                border-bottom-left-radius: 10px;
                border-bottom-right-radius: 10px;
            }}

            /* ===== 栏开关条（左工具条区域，v4.29 由 QWidget 改 QToolBar）===== */
            QToolBar#panelRail {{
                background: transparent;
                border: none;
                padding: 0 2px;
                spacing: 6px;
            }}
            QPushButton[variant="rail"]::menu-indicator {{
                image: none;
                width: 0;
            }}
        """
        # 同时应用到主窗口和 QApplication（后者可覆盖到下拉弹窗 popup）。
        # v4.29：应用级样式表**内容没变就不要再设一遍**——QApplication.setStyleSheet
        # 会让 Qt 重新解析整张表并对进程内**每一个**控件做 unpolish/polish；
        # 反复设同一份内容纯属浪费，而且在"窗口对象还没被 GC 回收、又新建窗口"
        # 的场景下（回归测试每项都建一次窗口）会在这一步撞上访问违例：
        # 实测第 47~48 个窗口必崩在 app.setStyleSheet 这一行。
        self.setStyleSheet(qss)
        app = QApplication.instance()
        if app is not None and app.styleSheet() != qss:
            app.setStyleSheet(qss)
        # 弹出菜单（QMenu）是独立弹出窗口：它的样式规则只在**第一次显示**时解析，
        # 切换主题后再弹出时不会自动按新色板重算（实测仍是 #ffffff 浅色面板）。
        # 所以除了把 QMenu 段写进全局 qss，还要逐个 setStyleSheet 强制它重新解析
        # unpolish/polish（v4.23）。
        try:
            from PyQt5.QtWidgets import QMenu
            menus = list(self.findChildren(QMenu))
            btn_menu = getattr(getattr(self, 'help_btn', None), 'menu', None)
            if callable(btn_menu) and btn_menu() is not None:
                menus.append(btn_menu())
            for m in menus:
                m.setStyleSheet(menu_qss)
                m.style().unpolish(m)
                m.style().polish(m)
                m.update()
        except Exception as e:
            logging.warning("重新解析 QMenu 样式失败: %s", e)
        # 空状态大图标是位图（图标集分深浅两套），换主题要重新取一遍
        if getattr(self, 'empty_icon', None) is not None:
            self._set_empty_icon(self.empty_icon)
        # 按钮上的单色图标同样分深浅两套（v4.28）
        self._apply_ui_icons()

    @staticmethod
    def _style_combo(combo):
        """为下拉框设置自定义 item delegate，可靠控制背景/文字颜色（避免 QSS 白框问题）。

        同时把最小宽度与最长项文本解耦（AdjustToMinimumContentsLengthWithIcon），
        避免「图外下方 (Outside Bottom)」这类长文本项把参数列最小宽度撑到
        400px 以上、在列内出现横向滚动条并与相邻栏对不齐。
        """
        combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(6)
        view = combo.view()
        if view is not None:
            delegate = ComboItemDelegate(view)
            view.setItemDelegate(delegate)
            # 保留引用，防止 delegate 被垃圾回收
            combo._combo_delegate = delegate
            # 清空可能残留的 QSS 干扰
            view.setStyleSheet("")
            view.setMouseTracking(True)
