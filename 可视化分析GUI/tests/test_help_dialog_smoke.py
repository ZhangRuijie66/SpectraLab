# -*- coding: utf-8 -*-
"""gui_help.HelpDialog 离屏冒烟测试。

在 ``QT_QPA_PLATFORM=offscreen`` 下用 gui_config.THEMES 的两套真实色板各构造
一次 HelpDialog，检查：

1. 窗口尺寸 ≈ default_size（±40px）；
2. QTextBrowser 能取到正文（toPlainText 非空且含各小节内容）；
3. 左侧目录项数 == len(sections)；
4. 正文控件区域的实际背景色 == 该主题的 CARD（用 dialog.grab() 取像后统计
   主体色，不只看 stylesheet 字符串）；
5. 目录点击能滚动到对应小节；搜索命中/未命中状态正确；复制按钮 1.2 s 后文字还原；
6. remember_geometry 的尺寸记忆往返（关窗 900x640 → 重开仍是 900x640）；
7. show_help_dialog 的非模态 / 复用 / 内容变了重建 / 换主题重刷（防深色白块）；
8. 边界情形：空 sections、局部色板、空 log_text、parent=None；
9. 两张截图存到 tests/_diag/help_dialog_{light,dark}.png。

坑：这台机器上离屏模式弹 QMessageBox 会让解释器崩溃（0xC0000005），
所以这里把 QMessageBox 的静态方法全部打成空函数，测试内也不弹任何对话框。
"""
import os
import sys
import time
import traceback

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
# 离屏 QPA 默认**没有字体库**（QFontDatabase().families() == 0），截图里所有文字
# 都是空白——本项目其它脚本（shot_dark_theme.py 等）因此改用原生平台截图。
# 这里给出字体目录让离屏也带字体，冒烟截图才能肉眼验收（找不到目录就算了，
# 颜色/尺寸/文本断言都不依赖字体）。
_FONT_DIR = os.path.join(os.environ.get('WINDIR', r'C:\Windows'), 'Fonts')
if os.path.isdir(_FONT_DIR):
    os.environ.setdefault('QT_QPA_FONTDIR', _FONT_DIR)

GUI_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if GUI_DIR not in sys.path:
    sys.path.insert(0, GUI_DIR)

from PyQt5.QtCore import QPoint, QRect, QSettings, Qt  # noqa: E402
from PyQt5.QtGui import QColor  # noqa: E402
from PyQt5.QtWidgets import (  # noqa: E402
    QApplication, QMessageBox, QTextBrowser, QWidget,
)

# 离屏下真的弹 QMessageBox 会崩解释器 —— 直接禁掉静态弹窗
for _fn in ('information', 'warning', 'critical', 'about', 'question'):
    setattr(QMessageBox, _fn, staticmethod(lambda *a, **k: None))

from gui_config import APP_NAME, APP_ORG, THEMES  # noqa: E402
import gui_log  # noqa: E402
from gui_help import HelpDialog, show_help_dialog  # noqa: E402

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_diag')
DEFAULT_SIZE = (720, 560)
SUB_TITLE = "v4.23 · 2026-09-10"

# 正文故意写长一点，保证正文需要滚动（顺带验证滚动条与锚点跳转）
SECTIONS = [
    ("快速上手", """
        <p>把数据文件夹拖到窗口上即可加载；目录树里单击展开、<b>双击</b>加载该文件夹。</p>
        <p>左侧「光谱类型」下拉框切换吸收 / 发射 / 荧光寿命 / 3D 扫描四种模式，
        切模式会清空缓存并重新加载当前文件夹里的可用数据。</p>
        <p>参数面板里的控件改动会触发实时预览（300 ms 防抖）；荧光寿命模式的
        单次拟合需要 1–2 分钟，所以参数微调不会自动重拟合，只有点「⏱ 开始拟合」
        按钮才真正开始。</p>
        <p>画布下方的工具栏可以缩放、平移、保存图片；导出分辨率由「DPI」控件决定。</p>
    """),
    ("数据格式", """
        <p>支持吸收光谱 CSV/TXT（波长 + 吸收值两列）、发射光谱 CSV、
        Horiba / DeltaHub 时间扫描 CSV（三列 time/decay/irf）。</p>
        <p>带仪器元数据头的文件会自动跳过头部：识别到 Labels / Type / Start /
        Stop / Step 行就当作时间扫描数据，行尾多余逗号会被忽略。</p>
        <p>同一目录里混着其它类型的 CSV 是常态，解析不了的文件会被静默跳过，
        只有整个文件夹全部失败才会弹一次警告。</p>
        <p>编码支持 UTF-8 / GBK / Latin-1：前两种解不出来时自动按 Latin-1 兜底。</p>
    """),
    ("快捷键", """
        <ul>
          <li><b>F5</b> — 实时预览（寿命模式为开始拟合）</li>
          <li><b>Ctrl+R</b> — 重新加载数据</li>
          <li><b>Ctrl+O</b> — 选择文件夹</li>
          <li><b>Ctrl+E / Ctrl+S</b> — 导出当前图</li>
          <li><b>Ctrl+Shift+E</b> — 导出全部图片</li>
          <li><b>Ctrl+D</b> — 复制积分结果</li>
          <li><b>Ctrl+T</b> — 切换浅色 / 深色主题</li>
          <li><b>F1</b> — 打开本帮助</li>
        </ul>
        <p>快捷键在主窗口有焦点时生效；帮助窗口是非模态的，可以帮助开着的同时
        继续操作主窗口，按 Esc 或点「关闭」退出帮助窗口。</p>
    """),
    ("常见问题", """
        <p><b>深色主题下出现白块？</b>先检查是否是本窗口：本窗口全部颜色取自
        gui_config.THEMES 色板，不硬编码颜色值。</p>
        <p><b>图上的中文变成方块？</b>启动时会按候选表（Microsoft YaHei /
        SimHei / PingFang SC / Noto Sans CJK SC）挑可用字体，装好中文字体后
        重启程序即可。</p>
        <p><b>拟合不收敛？</b>试着减小最小峰高、放宽最小峰距，或者把 λ 从自动
        调成手动给一个较小的值。</p>
        <p><b>程序没反应？</b>未捕获异常会写进日志文件（本窗口底部有路径），
        点「📂 打开日志文件夹」直接去看。</p>
    """),
    ("关于与日志", """
        <p>光谱可视化分析工具由 QLS Lab 开发，界面基于 PyQt5，绘图基于
        matplotlib，拟合基于 numpy / scipy。</p>
        <p>日志按天归档在 <code>%LOCALAPPDATA%\\QLSLab\\logs</code>：单文件
        上限 2 MB，保留 3 个历史文件；跨天启动时上一次的 gui.log 会自动改名
        成 gui-YYYY-MM-DD.log。</p>
        <p>反馈问题时请附上日志文件与本窗口「📋 复制全部」得到的环境说明。</p>
    """),
]


def pump(app, n=30):
    """跑事件循环若干轮，让布局/样式表真正生效。"""
    for _ in range(n):
        app.processEvents()


def widget_rect_in_dialog(dialog, widget, inset=4):
    """把 widget 的矩形换算到 dialog 的坐标系（用于截图取色）。"""
    top_left = widget.mapTo(dialog, widget.rect().topLeft())
    bottom_right = widget.mapTo(dialog, widget.rect().bottomRight())
    return QRect(top_left, bottom_right).adjusted(inset, inset, -inset, -inset)


def dominant_color(image, rect, scale=1.0, step=2):
    """统计截图里某矩形区域的主体色（出现次数最多的颜色）。"""
    counts = {}
    x0 = max(0, int(rect.left() * scale))
    y0 = max(0, int(rect.top() * scale))
    x1 = min(image.width(), int(rect.right() * scale))
    y1 = min(image.height(), int(rect.bottom() * scale))
    total = 0
    for y in range(y0, y1, step):
        for x in range(x0, x1, step):
            rgb = image.pixelColor(x, y).rgb() & 0xFFFFFF
            counts[rgb] = counts.get(rgb, 0) + 1
            total += 1
    if not counts:
        return QColor(0, 0, 0), 0, 0
    best_rgb, best_n = max(counts.items(), key=lambda kv: kv[1])
    return QColor(best_rgb), best_n, total


def luminance(color):
    """感知亮度（0–255，粗略加权），用来断言"确实是深色"。"""
    return 0.2126 * color.red() + 0.7152 * color.green() + 0.0722 * color.blue()


def check_sample_points(image, dialog, browser, expected, scale, label):
    """在正文区域取几个点打印实测 RGB（人工核对用），返回命中数。"""
    rect = widget_rect_in_dialog(dialog, browser)
    points = [
        QPoint(rect.right() - 6, rect.top() + 10),          # 右上角空白
        QPoint(rect.right() - 6, rect.center().y()),        # 右侧中部空白
        QPoint(rect.left() + 8, rect.bottom() - 8),         # 左下角空白
    ]
    hit = 0
    for pt in points:
        c = image.pixelColor(int(pt.x() * scale), int(pt.y() * scale))
        ok = c.rgb() & 0xFFFFFF == expected.rgb() & 0xFFFFFF
        hit += 1 if ok else 0
        print(f"  [{label}] 取样点 ({pt.x()},{pt.y()}) = "
              f"{c.name().upper()} rgb({c.red()},{c.green()},{c.blue()})"
              f"{'  == CARD' if ok else '  != CARD'}", flush=True)
    return hit


def run_theme(app, theme):
    """跑一套主题的全部断言，返回 (主体色 QColor, 占比字符串)。"""
    P = THEMES[theme]
    card = QColor(P['CARD'])
    print(f"\n=== 主题 {theme}  CARD={P['CARD']}  BG={P['BG']} ===", flush=True)

    # 清掉上次留下的窗口尺寸记忆，保证初始尺寸就是 default_size
    settings = QSettings(APP_ORG, APP_NAME)
    settings.remove('help_dialog')
    settings.sync()

    # 这里用 remember_geometry=True 顺带走一遍「恢复尺寸」路径（无历史值 → default_size）
    dialog = HelpDialog(parent=None, title=f"帮助 — {APP_NAME}", sections=SECTIONS,
                        palette=P, subtitle=SUB_TITLE,
                        log_text=str(gui_log.log_dir()),
                        default_size=DEFAULT_SIZE, remember_geometry=True)
    dialog.show()
    pump(app, 40)

    # ---- 断言 1：窗口尺寸 ≈ default_size（±40px）----
    dw, dh = dialog.width(), dialog.height()
    print(f"  窗口尺寸 = {dw}x{dh}（期望 {DEFAULT_SIZE[0]}x{DEFAULT_SIZE[1]} ±40）",
          flush=True)
    assert abs(dw - DEFAULT_SIZE[0]) <= 40, f"{theme}: 宽度 {dw} 偏离 default_size"
    assert abs(dh - DEFAULT_SIZE[1]) <= 40, f"{theme}: 高度 {dh} 偏离 default_size"

    # ---- 断言 2：正文控件能拿到正文 ----
    assert isinstance(dialog.browser, QTextBrowser), "正文控件不是 QTextBrowser"
    text = dialog.browser.toPlainText()
    print(f"  正文纯文本长度 = {len(text)} 字符", flush=True)
    assert len(text) > 300, f"{theme}: 正文内容过少（{len(text)} 字符）"
    for sec_title, _body in SECTIONS:
        assert sec_title in text, f"{theme}: 正文里找不到小节「{sec_title}」"
    assert "荧光寿命" in text, f"{theme}: 正文缺少关键内容"
    assert dialog.browser.openExternalLinks() and dialog.browser.openLinks(), \
        "正文控件未开启链接"

    # ---- 断言 3：目录项数 == len(sections) ----
    n_toc = dialog.toc.count()
    print(f"  目录项数 = {n_toc}（期望 {len(SECTIONS)}）", flush=True)
    assert n_toc == len(SECTIONS), f"{theme}: 目录项数 {n_toc} != {len(SECTIONS)}"
    assert dialog.toc.width() <= 160, f"{theme}: 目录宽度 {dialog.toc.width()} 过大"

    # ---- 断言 4：正文区域实际背景色 == 该主题的 CARD ----
    pixmap = dialog.grab()
    image = pixmap.toImage()
    scale = image.width() / float(dialog.width()) if dialog.width() else 1.0
    rect = widget_rect_in_dialog(dialog, dialog.browser)
    color, count, total = dominant_color(image, rect, scale)
    ratio = count / float(total) if total else 0.0
    print(f"  正文区域主体色 = {color.name().upper()} "
          f"rgb({color.red()},{color.green()},{color.blue()}) "
          f"占比 {ratio * 100:.1f}%（期望 CARD {card.name().upper()}）", flush=True)
    assert color.rgb() & 0xFFFFFF == card.rgb() & 0xFFFFFF, (
        f"{theme}: 正文背景实测 {color.name()} != CARD {card.name()}")
    hits = check_sample_points(image, dialog, dialog.browser, card, scale, theme)

    # ---- 截图（取默认状态：正文停在第一小节、搜索框为空）----
    os.makedirs(OUT_DIR, exist_ok=True)
    shot_path = os.path.join(OUT_DIR, f"help_dialog_{theme}.png")
    dialog.grab().save(shot_path)
    print(f"  截图已保存：{shot_path} ({image.width()}x{image.height()})", flush=True)

    # ---- 断言 5：目录跳转 + 搜索 ----
    dialog.select_section(len(SECTIONS) - 1)
    pump(app, 20)
    scroll_value = dialog.browser.verticalScrollBar().value()
    scroll_max = dialog.browser.verticalScrollBar().maximum()
    print(f"  跳到最后小节后滚动位置 = {scroll_value}/{scroll_max}", flush=True)
    assert scroll_max > 0, f"{theme}: 正文没有产生滚动条（内容太短，锚点跳转验不了）"
    assert scroll_value > 0, f"{theme}: 点击最后一节未滚动（锚点跳转失效）"

    dialog.search_edit.setText("荧光寿命")
    pump(app, 10)
    print(f"  搜索「荧光寿命」→ 提示：{dialog.search_hint.text()!r}", flush=True)
    assert "未找到" not in dialog.search_hint.text(), f"{theme}: 命中词被判为未找到"
    assert dialog.browser.textCursor().hasSelection(), f"{theme}: 命中未选中文本"

    dialog.search_edit.setText("这个词肯定没有zzz")
    pump(app, 10)
    print(f"  搜索不存在词 → 提示：{dialog.search_hint.text()!r}", flush=True)
    assert "未找到" in dialog.search_hint.text(), f"{theme}: 未命中却没有提示"
    dialog.search_edit.setText("")
    pump(app, 10)

    # ---- 断言 6：复制到剪贴板（离屏剪贴板可能不可用，故只提示不硬失败）----
    copied = dialog.copy_all_text()
    pump(app, 10)
    clip = ""
    try:
        cb = QApplication.clipboard()
        clip = cb.text() if cb is not None else ""
    except Exception as e:  # pragma: no cover - 离屏平台差异
        print(f"  读取剪贴板异常：{e}", flush=True)
    print(f"  复制全部 → 返回 {copied}，剪贴板长度 {len(clip)}", flush=True)
    if copied:
        assert dialog.copy_btn.text() == "✅ 已复制", f"{theme}: 复制按钮未反馈"
        assert len(clip) > 300, f"{theme}: 剪贴板内容过短（{len(clip)}）"
        assert "荧光寿命" in clip, f"{theme}: 剪贴板内容不含正文"

    # ---- 日志按钮接线（打桩，避免真的弹资源管理器）----
    import gui_log as _gl
    origin = _gl.open_log_folder
    _gl.open_log_folder = lambda: True
    try:
        assert dialog.open_log_folder() is True, f"{theme}: 打开日志文件夹接线异常"
    finally:
        _gl.open_log_folder = origin

    # ---- 底部日志行内容 ----
    assert dialog.log_label is not None, f"{theme}: 传了 log_text 却没显示日志行"
    assert dialog.log_label.text().startswith("日志："), f"{theme}: 日志行文字不对"

    # ---- 断言 7：复制按钮文字 1.2 s 后自己变回来 ----
    deadline = time.time() + 3.0
    while time.time() < deadline and dialog.copy_btn.text() != "📋 复制全部":
        app.processEvents()
        time.sleep(0.05)
    print(f"  1.2 s 后复制按钮文字 = {dialog.copy_btn.text()!r}", flush=True)
    assert dialog.copy_btn.text() == "📋 复制全部", f"{theme}: 复制按钮文字没有还原"

    # ---- 深色主题必须真的是深色 ----
    if theme == 'dark':
        lum = luminance(color)
        print(f"  正文背景亮度 = {lum:.1f}/255", flush=True)
        assert lum < 90, f"dark: 正文背景亮度 {lum:.1f} 太高，不是深色"

    # ---- 断言 8：remember_geometry 的尺寸记忆往返 ----
    dialog.resize(900, 640)
    pump(app, 5)
    dialog.close()          # closeEvent 里写入 QSettings
    pump(app, 10)
    again = HelpDialog(title=f"帮助 — {APP_NAME}", sections=SECTIONS, palette=P,
                       subtitle=SUB_TITLE, log_text=str(gui_log.log_dir()),
                       default_size=DEFAULT_SIZE, remember_geometry=True)
    saved_w, saved_h = again.width(), again.height()
    print(f"  关闭时 900x640 → 重开恢复为 {saved_w}x{saved_h}", flush=True)
    assert abs(saved_w - 900) <= 40 and abs(saved_h - 640) <= 40, \
        f"{theme}: 尺寸记忆失效（重开得到 {saved_w}x{saved_h}）"
    again.close()
    pump(app, 10)
    return color, f"{ratio * 100:.1f}%", hits


def body_color_of(dialog):
    """取某窗口正文区域的主体色（复用/换主题后复检用）。"""
    pixmap = dialog.grab()
    image = pixmap.toImage()
    scale = image.width() / float(dialog.width()) if dialog.width() else 1.0
    rect = widget_rect_in_dialog(dialog, dialog.browser)
    color, _count, _total = dominant_color(image, rect, scale)
    return color


def run_reuse(app):
    """show_help_dialog：非模态、复用、内容变了重建、换主题重刷样式。"""
    # 用一个真实的 QWidget 当父窗口（QDialog(parent) 要求 parent 是 QWidget）
    parent = QWidget()
    d1 = show_help_dialog(parent, f"帮助 — {APP_NAME}", SECTIONS,
                          palette=THEMES['light'], subtitle=SUB_TITLE,
                          log_text=str(gui_log.log_dir()))
    pump(app, 20)
    assert parent._help_dialog is d1, "show_help_dialog 未把窗口挂到 parent._help_dialog"
    assert d1.isVisible(), "show_help_dialog 没有显示窗口"
    assert not d1.isModal(), "帮助窗口应为非模态"
    light_body = body_color_of(d1)
    print(f"  复用前（浅色）正文主体色 = {light_body.name().upper()}", flush=True)
    assert light_body.name().upper() == THEMES['light']['CARD'].upper(), \
        "浅色复用窗口的正文底色不是浅色 CARD"

    d2 = show_help_dialog(parent, f"帮助 — {APP_NAME}", SECTIONS,
                          palette=THEMES['light'], subtitle=SUB_TITLE)
    assert d2 is d1, "内容未变时应复用同一个窗口"

    # 内容没变但主题变了：必须复用同一窗口**且**重刷成深色（否则深色下白块）
    d2b = show_help_dialog(parent, f"帮助 — {APP_NAME}", SECTIONS,
                           palette=THEMES['dark'], subtitle=SUB_TITLE)
    pump(app, 20)
    assert d2b is d1, "同一内容同一标题应复用窗口"
    dark_body = body_color_of(d2b)
    print(f"  复用后（切深色）正文主体色 = {dark_body.name().upper()}"
          f"（期望 {THEMES['dark']['CARD'].upper()}），亮度 {luminance(dark_body):.1f}",
          flush=True)
    assert dark_body.name().upper() == THEMES['dark']['CARD'].upper(), \
        "换主题复用窗口后正文没有重刷成深色 CARD（白块）"
    assert luminance(dark_body) < 90, "换主题复用窗口后正文不是深色"

    changed = list(SECTIONS) + [("新增小节", "<p>内容变了</p>")]
    d3 = show_help_dialog(parent, f"帮助 — {APP_NAME}", changed,
                          palette=THEMES['dark'], subtitle=SUB_TITLE)
    pump(app, 20)
    assert d3 is not d1, "内容变了应重建窗口"
    assert d3.toc.count() == len(changed), "重建后的目录项数不对"
    assert d3.browser.toPlainText().find("内容变了") >= 0, "重建后正文没更新"
    print(f"  非模态复用/重建 OK（目录项 {d1.toc.count()} → {d3.toc.count()}）", flush=True)
    d3.close()
    pump(app, 10)
    return True


def run_edge_cases(app):
    """边界：没有小节 / 局部色板 / 空 log_text / parent=None —— 都不能让窗口起不来。"""
    empty = HelpDialog(title="帮助 — 空", sections=[], palette=THEMES['dark'],
                       remember_geometry=False)
    assert empty.toc.count() == 0, "空 sections 的目录项数应为 0"
    assert empty.browser.toPlainText().strip() == "", "空 sections 的正文应为空"
    assert empty.log_label is None, "log_text 为空时不应显示日志行"
    empty.close()

    # 局部色板：缺的键用默认主题补齐，不能 KeyError
    partial = HelpDialog(title="帮助 — 局部色板", sections=[("一", "<p>x</p>")],
                         palette={'ACCENT': THEMES['dark']['ACCENT']},
                         remember_geometry=False)
    assert partial.browser.toPlainText().strip().startswith("一"), "局部色板窗口正文异常"
    partial.close()

    # parent=None：靠模块级引用兜住，不弹异常
    lone = show_help_dialog(None, "帮助 — 无父窗口", SECTIONS, palette=THEMES['dark'])
    pump(app, 20)
    assert lone.isVisible(), "parent=None 的帮助窗口没有显示"
    lone.close()
    pump(app, 10)
    print("  边界情形（空小节 / 局部色板 / 空 log_text / parent=None）OK", flush=True)
    return True


def main():
    app = QApplication(sys.argv)
    print(f"QT_QPA_PLATFORM={os.environ.get('QT_QPA_PLATFORM')}", flush=True)
    results = {}
    for theme in ('light', 'dark'):
        color, ratio, hits = run_theme(app, theme)
        results[theme] = (color, ratio, hits)
    run_reuse(app)
    run_edge_cases(app)

    print("\n---- 实测正文背景色 ----", flush=True)
    for theme in ('light', 'dark'):
        color, ratio, hits = results[theme]
        print(f"  {theme:5s} 主体色 {color.name().upper()} "
              f"rgb({color.red()},{color.green()},{color.blue()}) "
              f"占比 {ratio}，取样点命中 CARD {hits}/3 "
              f"（期望 {THEMES[theme]['CARD']}）", flush=True)
    print(f"\n截图：{os.path.join(OUT_DIR, 'help_dialog_light.png')}", flush=True)
    print(f"      {os.path.join(OUT_DIR, 'help_dialog_dark.png')}", flush=True)
    # 清掉测试写进 QSettings 的窗口尺寸，别影响用户真实的帮助窗口
    _s = QSettings(APP_ORG, APP_NAME)
    _s.remove('help_dialog')
    _s.sync()
    print("HELP DIALOG SMOKE PASSED", flush=True)
    return 0


if __name__ == '__main__':
    try:
        code = main()
    except Exception:
        traceback.print_exc()
        print("HELP DIALOG SMOKE FAILED", flush=True)
        code = 1
    sys.exit(code)
