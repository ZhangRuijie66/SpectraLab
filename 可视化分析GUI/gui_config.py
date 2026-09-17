# -*- coding: utf-8 -*-
"""光谱可视化分析工具 —— 全局常量配置。"""
import sys
from pathlib import Path

# 默认工作区（目录树的初始根目录，用户可更改并记住）
# Windows 用实验室数据目录；macOS/Linux 上该路径不存在，回退到用户目录
# （gui_data._get_saved_workspace 对不存在的路径还会再兜底到 Path.home()）
if sys.platform == 'win32':
    DEFAULT_WORKSPACE = r'D:\北大\QLS Lab\SPC\1O2+luminol\谱图\光谱'
else:
    DEFAULT_WORKSPACE = str(Path.home() / 'Documents')

# 全局界面字体（Qt 控件用；matplotlib 中文字体在 gui_ui.setup_chinese_font 按候选表挑选）
if sys.platform == 'darwin':
    UI_FONT_FAMILY = 'PingFang SC'
elif sys.platform.startswith('linux'):
    UI_FONT_FAMILY = 'Noto Sans CJK SC'
else:
    UI_FONT_FAMILY = 'Microsoft YaHei'

# QSettings 应用标识（用于记住工作区等设置）
APP_ORG = "QLSLab"
APP_NAME = "光谱可视化分析工具"

# 版本号（窗口标题 / 应用版本信息）
APP_VERSION = "4.36"
# 最近一次更新的日期（入口界面"帮助"中显示）
RELEASE_DATE = "2026-09-15"

# ---- 全局设计主题（现代化浅色主题的统一色板）----
# 中性色
COLOR_BG = "#f1f5f9"        # 窗口背景（冷灰）
COLOR_CARD = "#ffffff"      # 卡片 / 分组框背景
COLOR_BORDER = "#e2e8f0"    # 卡片边框
COLOR_INPUT_BORDER = "#cbd5e1"  # 输入控件边框
COLOR_TEXT = "#1e293b"      # 主文字
COLOR_TEXT_SOFT = "#334155" # 次级文字
COLOR_MUTED = "#64748b"     # 弱化文字 / 说明
# 主题色（按钮 / 强调）
ACCENT = "#2563EB"          # 主色（蓝）
ACCENT_HOVER = "#1D4ED8"
ACCENT_PRESSED = "#1E40AF"
SUCCESS = "#16A34A"         # 绿（加载 / 拟合）
SUCCESS_HOVER = "#15803D"
SUCCESS_PRESSED = "#166534"
VIOLET = "#7C3AED"          # 紫（实时预览）
VIOLET_HOVER = "#6D28D9"
VIOLET_PRESSED = "#5B21B6"
ORANGE = "#EA580C"          # 橙（导出图片）
ORANGE_HOVER = "#C2410C"
ORANGE_PRESSED = "#9A3412"
CYAN = "#0891B2"            # 青（导出全部）
CYAN_HOVER = "#0E7490"
CYAN_PRESSED = "#155E75"
NEUTRAL = "#475569"         # 石板灰（返回模块选择）
NEUTRAL_HOVER = "#334155"
NEUTRAL_PRESSED = "#1E293B"
# 应用图标文件名（与主程序同目录，或打包时作为数据资源 bundle）
APP_ICON_FILENAME = "app_icon.ico"

# ---- 日志（D6）：打包后 stdout 被丢弃，异常/警告统一落盘 ----
# 位置：%LOCALAPPDATA%\QLSLab\logs\gui.log（单文件滚动，见 gui_log.py）
LOG_APP_DIR = "QLSLab"          # %LOCALAPPDATA% 下的应用目录
LOG_DIR_NAME = "logs"           # 日志子目录
LOG_FILE_NAME = "gui.log"       # 当天日志文件（跨天自动归档为 gui-YYYY-MM-DD.log）
LOG_MAX_BYTES = 2 * 1024 * 1024  # 单文件上限 2 MB
LOG_BACKUP_COUNT = 3            # 保留 3 个历史文件
LOGGER_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
LOGGER_DATEFMT = "%Y-%m-%d %H:%M:%S"

# ---- 主题（D3）：浅色 / 深色 / 高对比打印友好 三套色板 ----
# 键名与上面的常量一一对应（apply_style 按当前主题取色）。
# **三套色板的键必须完全一致**——apply_style 是按固定键名解包的，
# 少一个键就会 KeyError（回归测试里有一条专门守这件事）。
# 默认主题：light（与 v4.17 之前完全一致）。
DEFAULT_THEME = "light"
# 主题切换顺序（「主题」按钮 / Ctrl+T 依次循环）
THEME_ORDER = ("light", "dark", "contrast")
# 界面上显示的名字（按钮 tooltip / 帮助说明）
THEME_LABELS = {
    "light": "浅色",
    "dark": "深色",
    "contrast": "高对比（打印友好）",
}

THEMES = {
    "light": {
        "BG": COLOR_BG, "CARD": COLOR_CARD, "BORDER": COLOR_BORDER,
        "INPUT_BORDER": COLOR_INPUT_BORDER, "TEXT": COLOR_TEXT,
        "TEXT_SOFT": COLOR_TEXT_SOFT, "MUTED": COLOR_MUTED,
        "ACCENT": ACCENT, "ACCENT_HOVER": ACCENT_HOVER,
        "ACCENT_PRESSED": ACCENT_PRESSED,
        "SUCCESS": SUCCESS, "SUCCESS_HOVER": SUCCESS_HOVER,
        "SUCCESS_PRESSED": SUCCESS_PRESSED,
        "VIOLET": VIOLET, "VIOLET_HOVER": VIOLET_HOVER,
        "VIOLET_PRESSED": VIOLET_PRESSED,
        "ORANGE": ORANGE, "ORANGE_HOVER": ORANGE_HOVER,
        "ORANGE_PRESSED": ORANGE_PRESSED,
        "CYAN": CYAN, "CYAN_HOVER": CYAN_HOVER, "CYAN_PRESSED": CYAN_PRESSED,
        "NEUTRAL": NEUTRAL, "NEUTRAL_HOVER": NEUTRAL_HOVER,
        "NEUTRAL_PRESSED": NEUTRAL_PRESSED,
        # 绘图区（matplotlib）配色
        "MPL_FIG": "#ffffff", "MPL_AX": "#ffffff", "MPL_FG": "#1e293b",
        # v4.20：坐标轴边框与网格线分开配置（深色主题需要不同亮度）
        "MPL_SPINE": "#cbd5e1",      # 坐标轴边框 / 刻度线
        "MPL_GRID": "#cbd5e1",
        "MPL_GRID_ALPHA": 0.30,      # 网格线不透明度
        "MPL_ZERO": "#808080",       # 零基准线（axhline(0)）
        "MPL_NOTE_BG": "#ffffff",    # 图上数值框底色（χ²R 等）
        "MPL_NOTE_FG": "#1e293b",
        # 控件状态色（QSS 里此前是硬编码浅色）
        "HOVER_BG": "#f1f5f9", "SELECT_BG": "#dbeafe", "SELECT_FG": "#1E40AF",
        "DISABLED_BG": "#e2e8f0", "DISABLED_FG": "#94a3b8",
        "HANDLE": "#cbd5e1", "HANDLE_HOVER": "#94a3b8",
        "ALT_ROW": "#f8fafc", "INFO_BG": "#eff6ff",
        "TOOLTIP_BG": "#1e293b", "TOOLTIP_FG": "#ffffff",
        # v4.27：徽标底色（拟合质量 ok / warn / bad 三档药丸标签）
        "SUCCESS_BG": "#dcfce7", "WARN_BG": "#ffedd5",
        "DANGER": "#dc2626", "DANGER_BG": "#fee2e2",
    },
    "dark": {
        "BG": "#0f172a", "CARD": "#1e293b", "BORDER": "#334155",
        "INPUT_BORDER": "#475569", "TEXT": "#e2e8f0",
        "TEXT_SOFT": "#cbd5e1", "MUTED": "#94a3b8",
        "ACCENT": "#3b82f6", "ACCENT_HOVER": "#60a5fa",
        "ACCENT_PRESSED": "#2563eb",
        "SUCCESS": "#22c55e", "SUCCESS_HOVER": "#4ade80",
        "SUCCESS_PRESSED": "#16a34a",
        "VIOLET": "#a78bfa", "VIOLET_HOVER": "#c4b5fd",
        "VIOLET_PRESSED": "#8b5cf6",
        "ORANGE": "#fb923c", "ORANGE_HOVER": "#fdba74",
        "ORANGE_PRESSED": "#f97316",
        "CYAN": "#22d3ee", "CYAN_HOVER": "#67e8f9", "CYAN_PRESSED": "#06b6d4",
        "NEUTRAL": "#64748b", "NEUTRAL_HOVER": "#94a3b8",
        "NEUTRAL_PRESSED": "#475569",
        # 绘图区（matplotlib）配色
        # v4.24：MPL_FIG 从 #0f172a 调深到 #0b1220——原来它与窗口底色 BG 完全相同，
        # 深色下画布和窗口糊成一片、看不出图纸边界（配合 QTabWidget 的 1px 描边
        # + 4px 内边距，画布才成为一张"嵌在卡片里的图纸"）。
        "MPL_FIG": "#0b1220", "MPL_AX": "#1e293b", "MPL_FG": "#e2e8f0",
        # v4.20：坐标轴边框从 #475569 提亮到 #94a3b8——原色对坐标区底色
        # #1e293b 只有约 2.0:1 对比度，深色模式下坐标轴几乎看不见（用户反馈）。
        # 现在边框 5.6:1、网格线 2.7:1（#94a3b8 @ 55%），刻度文字沿用 MPL_FG。
        "MPL_SPINE": "#94a3b8",
        "MPL_GRID": "#94a3b8",
        "MPL_GRID_ALPHA": 0.55,
        "MPL_ZERO": "#94a3b8",       # 零基准线
        "MPL_NOTE_BG": "#334155",    # 图上数值框底色（原为白底，深色下文字看不清）
        "MPL_NOTE_FG": "#e2e8f0",
        # 控件状态色
        # v4.24：SELECT_BG 从 #1e3a5f 提到 #2b5285——原值对卡片底色 #1e293b
        # 只有约 1.3:1 对比度，深色下选中项几乎看不见。
        "HOVER_BG": "#334155", "SELECT_BG": "#2b5285", "SELECT_FG": "#bfdbfe",
        "DISABLED_BG": "#334155", "DISABLED_FG": "#64748b",
        "HANDLE": "#475569", "HANDLE_HOVER": "#64748b",
        "ALT_ROW": "#172033", "INFO_BG": "#1e3a5f",
        "TOOLTIP_BG": "#334155", "TOOLTIP_FG": "#e2e8f0",
        # v4.27：徽标底色（深色下用药丸底色而不是纯色，避免刺眼）
        "SUCCESS_BG": "#064e3b", "WARN_BG": "#7c2d12",
        "DANGER": "#f87171", "DANGER_BG": "#7f1d1d",
    },
    # ---- 第三套：高对比 / 打印友好（v4.30）----
    # 两个目标同时满足：
    #   ① 屏幕可读性——正文/按钮文字对底色的对比度都 ≥ 7:1（WCAG AAA 级），
    #      投影、明亮环境、弱视情况下也能看清；
    #   ② 打印友好——纯白底 + 纯黑描边与文字，不用大面积低对比灰底；
    #      彩色只承担语义区分（按钮/徽标），黑白激光打印后靠边框和字重仍能分辨。
    # 具体取值都按 WCAG 相对亮度公式核算过（tests/run_regression.py 里有守卫，
    # 会实测 TEXT/MUTED/ACCENT/SUCCESS/四个语义色 对 CARD 的对比度 ≥ 7:1）。
    "contrast": {
        "BG": "#ffffff", "CARD": "#ffffff", "BORDER": "#000000",
        "INPUT_BORDER": "#000000", "TEXT": "#000000",
        "TEXT_SOFT": "#1a1a1a", "MUTED": "#4d4d4d",       # 对白底 8.4:1
        "ACCENT": "#0033cc", "ACCENT_HOVER": "#002699",   # 8.9:1
        "ACCENT_PRESSED": "#001a66",
        "SUCCESS": "#006400", "SUCCESS_HOVER": "#004d00",  # 7.4:1
        "SUCCESS_PRESSED": "#003300",
        "VIOLET": "#5b00b3", "VIOLET_HOVER": "#44008a",   # 10.0:1
        "VIOLET_PRESSED": "#2e005c",
        "ORANGE": "#8f3800", "ORANGE_HOVER": "#702c00",   # 7.7:1
        "ORANGE_PRESSED": "#522000",
        "CYAN": "#00556b", "CYAN_HOVER": "#00404f",       # 8.4:1
        "CYAN_PRESSED": "#002b36",
        "NEUTRAL": "#000000", "NEUTRAL_HOVER": "#333333",
        "NEUTRAL_PRESSED": "#000000",
        # 绘图区：白底黑轴，网格用中性灰（打印后仍能当浅参考线）
        "MPL_FIG": "#ffffff", "MPL_AX": "#ffffff", "MPL_FG": "#000000",
        "MPL_SPINE": "#000000",
        "MPL_GRID": "#808080",
        "MPL_GRID_ALPHA": 0.55,
        "MPL_ZERO": "#000000",
        "MPL_NOTE_BG": "#ffffff", "MPL_NOTE_FG": "#000000",
        # 控件状态色：选中用实心主色 + 白字（8.9:1），悬停用中性灰
        "HOVER_BG": "#e6e6e6", "SELECT_BG": "#0033cc", "SELECT_FG": "#ffffff",
        "DISABLED_BG": "#e6e6e6", "DISABLED_FG": "#767676",
        "HANDLE": "#767676", "HANDLE_HOVER": "#000000",
        "ALT_ROW": "#f2f2f2", "INFO_BG": "#e6ecff",
        "TOOLTIP_BG": "#000000", "TOOLTIP_FG": "#ffffff",
        # 徽标底色：浅底 + 深字（不用深色药丸，打印后是一块灰）
        "SUCCESS_BG": "#d9f2d9", "WARN_BG": "#ffe8d1",
        "DANGER": "#a80000", "DANGER_BG": "#ffd9d9",
    },
}
