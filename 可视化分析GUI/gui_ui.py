# -*- coding: utf-8 -*-
"""
界面/样式混入：负责建立主窗口的各个面板、QSS 样式与中文字体。
"""

from pathlib import Path

import logging

import matplotlib.pyplot as plt
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
from PyQt5.QtCore import Qt, QDir, QTimer
from PyQt5.QtGui import QFont, QIcon
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QFileDialog, QComboBox, QDoubleSpinBox, QCheckBox, QGroupBox, QScrollArea,
    QTabWidget, QListWidget, QSplitter, QProgressBar, QStatusBar, QFrame,
    QSizePolicy, QLineEdit, QFileSystemModel, QTreeView, QSlider, QSpinBox,
    QPlainTextEdit, QToolButton, QMenu, QAction, QMessageBox,
)

from gui_config import (
    DEFAULT_WORKSPACE, APP_NAME, APP_VERSION, APP_ICON_FILENAME, UI_FONT_FAMILY,
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

        # 创建主部件和布局
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        # 四栏并列布局：目录树 | 数据 | 参数 | 图片
        main_layout = QHBoxLayout(main_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        # 四栏：目录树、数据、参数、画布(图片)
        self.tree_panel = self.create_tree_panel()
        self.file_panel = self.create_file_panel()
        self.param_panel = self.create_param_panel()
        self.canvas_panel = self.create_canvas_panel()

        splitter = QSplitter(Qt.Horizontal)
        self.splitter = splitter
        splitter.addWidget(self.tree_panel)
        splitter.addWidget(self.file_panel)
        splitter.addWidget(self.param_panel)
        splitter.addWidget(self.canvas_panel)
        # 前三栏用最小宽度兜底，图片区 stretch 占满剩余
        # 参数栏最小/默认宽度略增：寿命与 3D 选项组控件较多（v4.19 用户反馈）
        self._col_widths = [170, 170, 340]
        self.tree_panel.setMinimumWidth(self._col_widths[0])
        self.file_panel.setMinimumWidth(self._col_widths[1])
        self.param_panel.setMinimumWidth(self._col_widths[2])
        self.canvas_panel.setMinimumWidth(400)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 0)
        splitter.setStretchFactor(2, 0)
        splitter.setStretchFactor(3, 1000)  # 图片占满所有剩余宽度
        # 初始给图片区更大的默认宽度（前几栏按内容保留较窄宽度），
        # 窗口放大时通过 stretchFactor(1000) 让图片区吃满剩余空间
        splitter.setSizes([200, 210, 360, 730])
        main_layout.addWidget(splitter)

        # 设置全局字体大小（适配高分辨率屏幕）
        font = QFont()
        font.setFamily(UI_FONT_FAMILY)  # 全局界面字体（按平台自动选择）
        font.setPointSize(12)  # 全局基础字体（各控件字号统一由 QSS 控制）
        self.setFont(font)

        # 状态栏
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("就绪")

        # 应用样式
        self.apply_style()

        # 连接实时预览
        self._connect_live_update()

        # 全局快捷键（D4）
        self._setup_shortcuts()

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
            ("Ctrl+T", lambda: self.toggle_theme()),  # E5：切换主题
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

    def _help_mode_section(self):
        """按当前模式返回帮助正文里的一段 HTML（E3）。"""
        mode = getattr(self, 'spectrum_type', 'absorption')
        if mode == 'lifetime':
            return (
                "<p><b>荧光寿命（Lifetime）模式</b></p><ul>"
                "<li><b>数据格式</b>：Horiba/DeltaHub 三列 CSV"
                "（time / decay / IRF，表头 Labels/Type/Start/Stop/Step），"
                "或多列 xlsx（时间 + 各样品列 + IRF，自动按列拆成多个数据集）</li>"
                "<li><b>专属按钮</b>：「⏱ 开始拟合」（单文件 MEM/SESM 拟合）、"
                "「📊 叠加寿命分布（并行拟合全部）」（多进程批量拟合后叠加对比）、"
                "「💾 导出当前拟合结果」（PNG + 拟合结果 json）</li>"
                "<li><b>参数</b>：拟合方法（MEM 最大熵 / SESM 平滑指数序列）、"
                "速率网格点数、τ 范围（1/k_min – 1/k_max）、"
                "「自动拟合 λ」（每次启动默认勾选，程序扫描最优熵权重）、"
                "固定寿命分量（逗号分隔的 τ，作为不受熵约束的基函数）</li>"
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
                "<li><b>F5 行为</b>：实时预览（重新绘制，不拟合）</li></ul>")
        return (
            "<p><b>吸收光谱（UV-Vis）模式</b></p><ul>"
            "<li><b>数据格式</b>：吸收光谱 CSV/TXT（波长 + 吸收值两列；"
            "带仪器元数据头也能自动跳过）</li>"
            "<li><b>专属功能</b>：合并图 / 单独图、峰检测（最小峰高 / 最小峰距）、"
            "显示范围、光谱减法（A − B 差谱或各减本底）、光谱积分（数据输出区）</li>"
            "<li><b>F5 行为</b>：实时预览（重新绘制，不拟合）</li></ul>")

    def show_help(self):
        """F1 帮助（主窗口内）：正文按当前光谱模式生成（E3）。"""
        from gui_log import log_dir
        QMessageBox.about(
            self, f"帮助 — {APP_NAME}",
            f"<h3>{APP_NAME} v{APP_VERSION}</h3>"
            + self._help_mode_section()
            + "<p><b>快捷键：</b></p><ul>"
            "<li>F5 — 实时预览（寿命模式为开始拟合）</li>"
            "<li>Ctrl+R — 重新加载数据</li>"
            "<li>Ctrl+O — 选择文件夹</li>"
            "<li>Ctrl+E / Ctrl+S — 导出当前图</li>"
            "<li>Ctrl+Shift+E — 导出全部图片</li>"
            "<li>Ctrl+D — 复制积分结果</li>"
            "<li>Ctrl+T — 切换浅色 / 深色主题（也可点左上角「🌙 深色主题」按钮）</li>"
            "<li>F1 — 本帮助</li></ul>"
            "<p><b>其它：</b></p><ul>"
            "<li>「🏠 返回模块选择」回到入口界面重新选模式；直接关窗则退出程序</li>"
            "<li>把文件夹直接拖到窗口上也可以加载；目录树单击展开、"
            "<b>双击</b>加载该文件夹</li>"
            "<li>导出格式由「导出格式」下拉框决定（PNG / PDF / SVG 或其组合）；"
            "「导出用白底」勾选后导出图强制白底深字，"
            "深色主题下投稿/做 PPT 用得上</li>"
            f"<li>日志（含加载失败原因、未捕获异常）：<br>{log_dir()}</li></ul>")

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
        panel = QWidget()
        file_group = QGroupBox("目录树")

        root_layout = QVBoxLayout()

        # 返回入口界面（模块选择）：关闭当前窗口，由主循环重新弹出 ModuleLauncher
        home_btn = QPushButton("🏠 返回模块选择")
        home_btn.setProperty("variant", "neutral")
        home_btn.setCursor(Qt.PointingHandCursor)
        home_btn.clicked.connect(self.return_to_launcher)
        root_layout.addWidget(home_btn)

        # 主题切换（D3）：浅色 / 深色
        self.theme_btn = QPushButton("🌙 深色主题")
        self.theme_btn.setProperty("variant", "neutral")
        self.theme_btn.setCursor(Qt.PointingHandCursor)
        self.theme_btn.clicked.connect(lambda: self.toggle_theme())
        root_layout.addWidget(self.theme_btn)

        # 帮助菜单（D6）：快捷键说明 + 打开日志文件夹
        self.help_btn = QToolButton()
        self.help_btn.setText("❓ 帮助")
        self.help_btn.setPopupMode(QToolButton.InstantPopup)
        self.help_btn.setCursor(Qt.PointingHandCursor)
        self.help_btn.setToolTip("快捷键与说明（F1）；查看日志文件夹")
        help_menu = QMenu(self.help_btn)
        act_help = QAction("快捷键与说明 (F1)", self.help_btn)
        act_help.triggered.connect(self.show_help)
        help_menu.addAction(act_help)
        act_log = QAction("打开日志文件夹", self.help_btn)
        act_log.triggered.connect(self._open_log_folder)
        help_menu.addAction(act_log)
        self.help_btn.setMenu(help_menu)
        root_layout.addWidget(self.help_btn)

        # 顶部：光谱类型切换
        type_label = QLabel("光谱类型:")
        type_label.setProperty("role", "sectionLabel")
        root_layout.addWidget(type_label)
        self.spectrum_type_combo = QComboBox()
        self.spectrum_type_combo.addItems([
            "吸收光谱 (UV-Vis)",
            "发射光谱 (Emission)",
            "荧光寿命 (Lifetime)",
            "3D 扫描 (EEM)",
        ])
        self.spectrum_type_combo.currentIndexChanged.connect(self.on_spectrum_type_changed)
        self._style_combo(self.spectrum_type_combo)
        root_layout.addWidget(self.spectrum_type_combo)

        # 选择工作区按钮（设置目录树的根目录，并记住下次启动）
        workspace_btn = QPushButton("选择工作区")
        workspace_btn.clicked.connect(self.select_workspace)
        workspace_btn.setProperty("variant", "primary")
        workspace_btn.setCursor(Qt.PointingHandCursor)
        root_layout.addWidget(workspace_btn)

        self.workspace_label = QLabel("工作区: 未设置")
        self.workspace_label.setWordWrap(True)
        self.workspace_label.setProperty("role", "hint")
        root_layout.addWidget(self.workspace_label)

        # 选择文件夹按钮（直接加载该文件夹的数据）
        folder_btn = QPushButton("选择文件夹")
        folder_btn.clicked.connect(self.select_folder)
        folder_btn.setProperty("variant", "success")
        folder_btn.setCursor(Qt.PointingHandCursor)
        root_layout.addWidget(folder_btn)

        self.folder_label = QLabel("未选择文件夹")
        self.folder_label.setWordWrap(True)
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
        tree_label = QLabel("选择数据文件夹（双击子文件夹加载）:")
        tree_label.setProperty("role", "sectionLabel")
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
        self.workspace_label.setText(f"工作区: {initial_root}")

        file_group.setLayout(root_layout)
        v = QVBoxLayout(panel)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(file_group)
        return panel

    def create_file_panel(self):
        """创建文件列表面板：已加载的数据文件（勾选以绘制合并图）"""
        panel = QWidget()
        file_group = QGroupBox("数据")

        root_layout = QVBoxLayout()

        file_list_label = QLabel("已加载的文件（勾选以绘制合并图）:")
        file_list_label.setProperty("role", "sectionLabel")
        self.file_list_label = file_list_label  # 文案随模式切换（见 gui_data.on_spectrum_type_changed）
        root_layout.addWidget(file_list_label)

        self.file_list = QListWidget()
        self.file_list.setMinimumHeight(140)
        self.file_list.itemClicked.connect(self.on_file_selected)
        self.file_list.itemChanged.connect(self.on_item_checked)
        root_layout.addWidget(self.file_list)

        self.file_count_label = QLabel("已加载 0 个文件")
        self.file_count_label.setProperty("role", "hint")
        root_layout.addWidget(self.file_count_label)

        reload_btn = QPushButton("重新加载数据")
        reload_btn.clicked.connect(self.reload_data)
        reload_btn.setProperty("variant", "primary")
        reload_btn.setCursor(Qt.PointingHandCursor)
        root_layout.addWidget(reload_btn)

        file_group.setLayout(root_layout)
        v = QVBoxLayout(panel)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(file_group)
        return panel

    def create_param_panel(self):
        """创建绘图参数面板 + 操作按钮。

        外层为普通 QWidget：进度条与「操作」按钮组固定在面板上/下方（滚动区之外，
        任何时刻都可见）；绘图参数组内容较长，放进 QScrollArea 滚动查看。
        """
        # 外层控件（放入 splitter）
        panel = QWidget()
        outer = QVBoxLayout(panel)
        # 边距归零：与目录树/数据两栏的分组框边缘对齐
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)

        # 进度条（固定面板顶部：拟合/加载进行中时无需滚动即可见）
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setFixedHeight(10)
        outer.addWidget(self.progress_bar)

        # 参数内容控件（放进下方滚动区）
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # 绘图参数组
        param_group = QGroupBox("绘图参数")
        param_layout = QVBoxLayout()

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
        self.title_edit.setStyleSheet("font-size: 15px; padding: 5px;")
        self.title_edit.textChanged.connect(self.on_title_changed)
        param_layout.addWidget(self.title_edit)

        # 线宽（带滑块）
        label = QLabel("线宽:")
        param_layout.addWidget(label)
        self.linewidth_spin = SliderSpin(0.5, 5.0, 1.5, 0.1, scale=10, decimals=1, suffix="")
        param_layout.addWidget(self.linewidth_spin)

        # DPI（带滑块；导出图片的分辨率，默认 600 dpi，最高 1200）
        label = QLabel("分辨率 (DPI):")
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
        self.peak_value_check = QCheckBox("峰位标数值 (nm)")
        self.peak_value_check.setChecked(True)
        self.peak_value_check.stateChanged.connect(self._trigger_live_update)
        param_layout.addWidget(self.peak_value_check)

        # 发射光谱专用选项（默认隐藏，切换到发射时显示）
        emission_options = QVBoxLayout()
        emission_group = QGroupBox("发射光谱选项")
        self.normalize_check = QCheckBox("归一化强度")
        self.show_ex_check = QCheckBox("标注激发波长 (EX)")
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

        lifetime_rates_label = QLabel("速率网格点数:")
        lifetime_options.addWidget(lifetime_rates_label)
        self.lifetime_nrates_spin = QSpinBox()
        self.lifetime_nrates_spin.setRange(51, 401)
        self.lifetime_nrates_spin.setSingleStep(10)
        self.lifetime_nrates_spin.setValue(201)
        lifetime_options.addWidget(self.lifetime_nrates_spin)

        # 速率网格范围 k_min–k_max（k = 1/τ，单位 1/ns）
        lifetime_krange_label = QLabel("速率网格范围 k (1/ns):")
        lifetime_options.addWidget(lifetime_krange_label)
        krange_row = QHBoxLayout()
        self.lifetime_kmin_spin = QDoubleSpinBox()
        self.lifetime_kmin_spin.setRange(1e-5, 10.0)
        self.lifetime_kmin_spin.setDecimals(5)
        self.lifetime_kmin_spin.setValue(0.01)
        self.lifetime_kmin_spin.setSingleStep(0.01)
        self.lifetime_kmin_spin.setMinimumWidth(110)
        krange_row.addWidget(self.lifetime_kmin_spin)
        krange_row.addWidget(QLabel("—"))
        self.lifetime_kmax_spin = QDoubleSpinBox()
        self.lifetime_kmax_spin.setRange(0.1, 1000.0)
        self.lifetime_kmax_spin.setDecimals(2)
        self.lifetime_kmax_spin.setValue(100.0)
        self.lifetime_kmax_spin.setSingleStep(1.0)
        self.lifetime_kmax_spin.setMinimumWidth(110)
        krange_row.addWidget(self.lifetime_kmax_spin)
        lifetime_options.addLayout(krange_row)
        krange_hint = QLabel("k = 1/τ：默认 0.01–100 对应 τ = 100 ns–10 ps。\n"
                             "要拟合更长寿命（μs 级）把 k_min 调小。")
        krange_hint.setWordWrap(True)
        krange_hint.setProperty("role", "hint")
        lifetime_options.addWidget(krange_hint)

        # 固定寿命分量（不受熵约束的额外基函数）
        lifetime_options.addWidget(QLabel("固定寿命分量 τ (ns，逗号分隔):"))
        self.lifetime_fixed_taus_edit = QLineEdit()
        self.lifetime_fixed_taus_edit.setPlaceholderText(
            "留空 = 不固定；例：3.6 或 0.5, 3.6")
        lifetime_options.addWidget(self.lifetime_fixed_taus_edit)
        fixed_hint = QLabel(
            "填了就把这些 τ 作为**不受熵约束**的基函数一起拟合，幅度自动求解——\n"
            "用于扣除参照染料寿命、IRF 拖尾等已知分量。")
        fixed_hint.setWordWrap(True)
        fixed_hint.setProperty("role", "hint")
        lifetime_options.addWidget(fixed_hint)

        # 熵权重 λ（MEM 目标函数 chi² - λ·S 中的 λ）：可手动修改，
        # 也可勾选「自动拟合 λ」让程序扫描最优值（对数滑块，跨 6 个数量级）
        lambda_label = QLabel("熵权重 λ (MEM):")
        lifetime_options.addWidget(lambda_label)
        self.lifetime_lambda_spin = SliderSpin(
            1e-6, 1.0, 1e-3, 1e-6, decimals=6, logscale=True)
        lifetime_options.addWidget(self.lifetime_lambda_spin)

        self.lifetime_auto_lambda_check = QCheckBox("自动拟合 λ（推荐）")
        self.lifetime_auto_lambda_check.setChecked(True)   # 默认勾选（用户要求）
        self.lifetime_auto_lambda_check.toggled.connect(
            self.on_auto_lambda_toggled)
        lifetime_options.addWidget(self.lifetime_auto_lambda_check)
        self.on_auto_lambda_toggled(True)                  # 同步禁用 λ 输入框

        lambda_hint = QLabel(
            "λ = 熵正则强度：越大分布越平滑，越小越贴合噪声。\n"
            "勾选后流程：按当前 λ 拟合 MEM → 扫描 χ²R ≤ 1.1 的最大 λ → "
            "用新 λ 重新拟合（约 2–4 分钟/文件）")
        lambda_hint.setWordWrap(True)
        lambda_hint.setProperty("role", "hint")
        lifetime_options.addWidget(lambda_hint)

        lifetime_hint = QLabel("选中文件后点下方按钮开始拟合\n（MEM 约 1–2 分钟/文件）")
        lifetime_hint.setWordWrap(True)
        lifetime_hint.setProperty("role", "hint")
        lifetime_options.addWidget(lifetime_hint)

        # 组内最下方的拟合按钮（显式触发，等效于「实时预览」）
        self.lifetime_fit_btn = QPushButton("⏱ 开始拟合")
        self.lifetime_fit_btn.setProperty("variant", "success")
        self.lifetime_fit_btn.setCursor(Qt.PointingHandCursor)
        self.lifetime_fit_btn.clicked.connect(
            lambda: self.update_plot(explicit=True))
        lifetime_options.addWidget(self.lifetime_fit_btn)

        # 并行拟合全部文件并叠加寿命分布对比（C1 + C8）
        self.lifetime_overlay_btn = QPushButton("📊 叠加寿命分布（并行拟合全部）")
        self.lifetime_overlay_btn.setProperty("variant", "cyan")
        self.lifetime_overlay_btn.setCursor(Qt.PointingHandCursor)
        self.lifetime_overlay_btn.clicked.connect(self._run_overlay_lifetime)
        lifetime_options.addWidget(self.lifetime_overlay_btn)

        lifetime_group = QGroupBox("荧光寿命拟合")
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

        scan3d_options.addWidget(QLabel("周期梳状伪迹处理:"))
        self.scan3d_comb_combo = QComboBox()
        self.scan3d_comb_combo.addItems([
            "只保留谷值通道",
            "按乘性条纹除法",
            "污染整行替换",
            "不处理",
        ])
        self._style_combo(self.scan3d_comb_combo)
        scan3d_options.addWidget(self.scan3d_comb_combo)

        scan3d_options.addWidget(QLabel("中值去窄线窗口:"))
        self.scan3d_despike_spin = SliderSpin(1, 15, 3, 1, scale=1, decimals=0)
        scan3d_options.addWidget(self.scan3d_despike_spin)

        scan3d_options.addWidget(QLabel("EM 方向平滑 σ:"))
        self.scan3d_sigma_em_spin = SliderSpin(0, 5, 1.0, 0.1, scale=10,
                                               decimals=1)
        scan3d_options.addWidget(self.scan3d_sigma_em_spin)

        scan3d_options.addWidget(QLabel("EX 方向平滑 σ:"))
        self.scan3d_sigma_ex_spin = SliderSpin(0, 5, 0.0, 0.1, scale=10,
                                               decimals=1)
        scan3d_options.addWidget(self.scan3d_sigma_ex_spin)

        self.scan3d_log_check = QCheckBox("对数色标（强度跨数量级时更清楚）")
        scan3d_options.addWidget(self.scan3d_log_check)

        scan3d_hint = QLabel(
            "EEM 数据常含 ~7 nm 周期条纹（等厚干涉/光栅鬼线）：位置固定在 EM、"
            "峰值常饱和。默认只保留条纹谷值通道再插值，曲面才连续；"
            "无条纹的数据选「不处理」。点选文件即绘制。")
        scan3d_hint.setWordWrap(True)
        scan3d_hint.setProperty("role", "hint")
        scan3d_options.addWidget(scan3d_hint)

        scan3d_group = QGroupBox("3D 扫描 (EEM) 选项")
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
        range_group = QGroupBox("显示范围 (nm)")
        range_layout = QVBoxLayout()

        lo_layout = QHBoxLayout()
        lo_layout.addWidget(QLabel("波长下限:"))
        self.wl_min_spin = QDoubleSpinBox()
        self.wl_min_spin.setRange(0, 3000)
        self.wl_min_spin.setValue(200)
        self.wl_min_spin.setDecimals(1)
        self.wl_min_spin.setSuffix(" nm")
        self.wl_min_spin.setSingleStep(10)
        # 显式最小宽度：压低「显示范围」组的最小宽度，避免把参数列撑出横向滚动条
        self.wl_min_spin.setMinimumWidth(110)
        self.wl_min_spin.valueChanged.connect(self._trigger_live_update)
        lo_layout.addWidget(self.wl_min_spin)
        range_layout.addLayout(lo_layout)

        hi_layout = QHBoxLayout()
        hi_layout.addWidget(QLabel("波长上限:"))
        self.wl_max_spin = QDoubleSpinBox()
        self.wl_max_spin.setRange(0, 3000)
        self.wl_max_spin.setValue(900)
        self.wl_max_spin.setDecimals(1)
        self.wl_max_spin.setSuffix(" nm")
        self.wl_max_spin.setSingleStep(10)
        self.wl_max_spin.setMinimumWidth(110)
        self.wl_max_spin.valueChanged.connect(self._trigger_live_update)
        hi_layout.addWidget(self.wl_max_spin)
        range_layout.addLayout(hi_layout)

        # 自动范围按钮（E2）：只在首次加载某文件夹时自动设范围，之后想回到
        # 数据实际范围就点这里，不再每次加载都覆盖用户手填的区间
        self.auto_range_btn = QPushButton("自动（按数据范围）")
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

        subtract_layout.addWidget(QLabel("本底 / 减数 (B):"))
        self.subtract_ref_combo = QComboBox()
        self.subtract_ref_combo.currentIndexChanged.connect(self._trigger_live_update)
        self._style_combo(self.subtract_ref_combo)
        subtract_layout.addWidget(self.subtract_ref_combo)

        subtract_hint = QLabel("A 选「所有光谱」时每条光谱都减去本底 B；\n"
                               "A 选具体文件时只绘制 A − B 差谱。\n"
                               "本底文件本身不再绘制。")
        subtract_hint.setWordWrap(True)
        subtract_hint.setProperty("role", "hint")
        subtract_layout.addWidget(subtract_hint)

        subtract_group.setLayout(subtract_layout)
        self.subtract_group = subtract_group
        param_layout.addWidget(subtract_group)

        param_group.setLayout(param_layout)
        layout.addWidget(param_group)

        # 参数内容放进可滚动区域（伸展吃满滚动区上方剩余空间）
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        scroll.setFrameShape(QFrame.NoFrame)
        outer.addWidget(scroll, 1)

        # 操作按钮组：固定在面板底部（滚动区之外，任何时刻都可见，无需滚动）
        action_group = QGroupBox("操作")
        action_layout = QVBoxLayout()

        self.preview_btn = QPushButton("📊 实时预览")
        self.preview_btn.setProperty("variant", "violet")
        self.preview_btn.setCursor(Qt.PointingHandCursor)
        # 显式触发（explicit=True）：荧光寿命模式下只有该按钮才真正启动拟合
        self.preview_btn.clicked.connect(lambda: self.update_plot(explicit=True))
        action_layout.addWidget(self.preview_btn)

        self.export_btn = QPushButton("💾 导出图片")
        self.export_btn.setProperty("variant", "orange")
        self.export_btn.setCursor(Qt.PointingHandCursor)
        self.export_btn.clicked.connect(self.export_plot)
        action_layout.addWidget(self.export_btn)

        self.export_all_btn = QPushButton("📁 导出全部图片")
        self.export_all_btn.setProperty("variant", "cyan")
        self.export_all_btn.setCursor(Qt.PointingHandCursor)
        self.export_all_btn.clicked.connect(self.export_all_plots)
        action_layout.addWidget(self.export_all_btn)

        # 荧光寿命模式专属：导出拟合结果（汇总表 + 单文件报告）
        self.export_current_fit_btn = QPushButton("💾 导出当前拟合结果")
        self.export_current_fit_btn.setProperty("variant", "orange")
        self.export_current_fit_btn.setCursor(Qt.PointingHandCursor)
        self.export_current_fit_btn.clicked.connect(
            self._export_lifetime_fit_results)
        self.export_current_fit_btn.setVisible(False)
        action_layout.addWidget(self.export_current_fit_btn)

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
        preview_layout.addWidget(self.toolbar)  # 固定工具条高度
        preview_layout.addWidget(self.canvas, 1)  # 画布 stretch，吃满剩余空间

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

        # 信息标签页
        info_tab = QWidget()
        info_layout = QVBoxLayout(info_tab)
        self.info_label = QLabel("选择文件后显示详细信息")
        self.info_label.setWordWrap(True)
        self.info_label.setAlignment(Qt.AlignTop)
        self.info_label.setProperty("role", "infoLabel")
        info_layout.addWidget(self.info_label)
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
        self.integ_copy_btn = QPushButton("📋 复制结果")
        self.integ_copy_btn.setProperty("variant", "primary")
        self.integ_copy_btn.setCursor(Qt.PointingHandCursor)
        self.integ_copy_btn.clicked.connect(self._copy_integration_results)
        integ_ctrl.addWidget(self.integ_copy_btn)
        integ_layout.addLayout(integ_ctrl)

        self.integ_output = QPlainTextEdit()
        self.integ_output.setReadOnly(True)
        self.integ_output.setPlaceholderText(
            "加载数据后，每个样品的积分结果显示在这里\n"
            "（格式：样品名 积分 450nm-550nm 123455；梯形积分，用原始强度，不受归一化影响）")
        self.integ_output.setMinimumHeight(110)
        self.integ_output.setMaximumHeight(210)
        integ_layout.addWidget(self.integ_output)

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

    def toggle_theme(self, dark=None):
        """切换浅色 / 深色主题（D3）。"""
        if dark is None:
            dark = getattr(self, 'theme', 'light') != 'dark'
        self.theme = 'dark' if dark else 'light'
        if hasattr(self, 'theme_btn'):
            self.theme_btn.setText("☀️ 浅色主题" if dark else "🌙 深色主题")
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
            self.status_bar.showMessage(
                f"已切换到{'深色' if dark else '浅色'}主题")

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
        for attr in ('canvas', 'lifetime_canvas', 'diag_canvas'):
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
         HANDLE, HANDLE_HOVER, ALT_ROW, INFO_BG, TOOLTIP_BG, TOOLTIP_FG) = (
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
            P['TOOLTIP_BG'], P['TOOLTIP_FG'])
        up_u, dn_u, ck_u, ch_u = self._load_style_icons()
        # 下拉弹窗的 item delegate 取色也要跟着主题走（否则深色下弹出一块白板）
        set_combo_palette(P)
        # 图标文件缺失时省略对应 image 行（QSS 里空 url 会使整条规则失效）
        up_img = f"image: url({up_u});" if up_u else ""
        dn_img = f"image: url({dn_u});" if dn_u else ""
        ck_img = f"image: url({ck_u});" if ck_u else ""
        ch_img = f"image: url({ch_u});" if ch_u else ""
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
                font-size: 14px;
            }}

            /* ===== 文字角色（随主题变色，D3）===== */
            QLabel[role="sectionLabel"] {{
                font-size: 14px; font-weight: bold; color: {TEXT_SOFT};
            }}
            QLabel[role="folderLabel"] {{
                font-size: 12px; color: {TEXT_SOFT};
            }}
            QLabel[role="infoLabel"] {{
                font-size: 15px; color: {TEXT_SOFT};
            }}
            QLabel[role="hint"] {{
                font-size: 13px; color: {MUTED};
            }}

            /* ===== 卡片式分组框 ===== */
            QGroupBox {{
                background-color: {CARD};
                border: 1px solid {BORDER};
                border-radius: 10px;
                margin-top: 16px;
                padding: 14px 10px 10px 10px;
                font-weight: bold;
                font-size: 16px;
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
                font-size: 16px;
                background: transparent;
            }}

            /* ===== 按钮：基础 + 语义色变体（variant 属性选择）===== */
            QPushButton {{
                background-color: {CARD};
                color: {TEXT};
                border: 1px solid {INPUT_BORDER};
                border-radius: 8px;
                padding: 8px 14px;
                font-size: 15px;
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

            /* ===== 列表 / 目录树 ===== */
            QListWidget, QTreeView {{
                background-color: {CARD};
                border: 1px solid {BORDER};
                border-radius: 8px;
                padding: 4px;
                outline: 0;
            }}
            QListWidget::item, QTreeView::item {{
                padding: 6px;
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

            /* ===== 输入控件 ===== */
            QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit,
            QPlainTextEdit, QTextEdit {{
                background-color: {CARD};
                border: 1px solid {INPUT_BORDER};
                border-radius: 6px;
                padding: 4px 8px;
                color: {TEXT};
                font-size: 15px;
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
                font-size: 15px;
                padding: 4px;
                spacing: 8px;
                background: transparent;
            }}
            QCheckBox::indicator {{
                width: 17px;
                height: 17px;
                border: 2px solid {HANDLE_HOVER};
                border-radius: 5px;
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
            QTabWidget::pane {{
                border: 1px solid {BORDER};
                border-radius: 10px;
                background-color: {CARD};
                top: -1px;
            }}
            QTabBar::tab {{
                background: transparent;
                color: {MUTED};
                padding: 10px 24px;
                margin: 6px 4px 4px 0;
                border-radius: 8px;
                font-size: 15px;
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
                font-size: 14px;
            }}
            QStatusBar QLabel {{
                color: {MUTED};
                font-size: 14px;
            }}
            QSplitter::handle {{
                background: transparent;
            }}
            QSplitter::handle:horizontal {{ width: 5px; }}
            QSplitter::handle:hover {{ background: {SELECT_BG}; border-radius: 2px; }}
        """
        # 同时应用到主窗口和 QApplication（后者可覆盖到下拉弹窗 popup）
        self.setStyleSheet(qss)
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(qss)

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
