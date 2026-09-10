# -*- coding: utf-8 -*-
"""量一下当前 UI 的实际尺寸/字号，给设计方案提供准确数据。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtWidgets import QApplication, QMessageBox, QLabel, QPushButton, QGroupBox  # noqa: E402

app = QApplication(sys.argv)
for fn in ('information', 'warning', 'critical'):
    setattr(QMessageBox, fn, staticmethod(lambda *a, **k: None))

from absorption_gui import AbsorptionGUI  # noqa: E402

w = AbsorptionGUI()
w.resize(1600, 950)
w.spectrum_type_combo.setCurrentIndex(2)      # 寿命模式：控件最多
w.show()
for _ in range(30):
    app.processEvents()

print('--- 三栏与画布宽度（窗口 1600x950）---', flush=True)
for attr in ('tree_panel', 'param_panel', 'canvas', 'lifetime_canvas',
             'diag_canvas', 'tab_widget', 'file_list', 'param_scroll',
             'scan3d_options_group'):
    x = getattr(w, attr, None)
    if x is not None:
        print(f'  {attr:24s} {x.width():5d} x {x.height():5d}', flush=True)

print('--- 各栏 minimumWidth / sizeHint ---', flush=True)
for attr in ('tree_panel', 'param_panel'):
    x = getattr(w, attr, None)
    if x is not None:
        print(f'  {attr:24s} min={x.minimumWidth()} hint={x.sizeHint().width()}', flush=True)

print('--- 按钮尺寸（中英混排最长的几个）---', flush=True)
for b in w.findChildren(QPushButton):
    t = b.text()
    if len(t) >= 6 and b.isVisible():
        print(f'  {t!r:34s} {b.width():4d} x {b.height():3d} '
              f'font={b.font().pointSize()}pt', flush=True)

print('--- 字号统计 ---', flush=True)
sizes = {}
for lb in w.findChildren(QLabel):
    if lb.text().strip():
        sizes[lb.font().pointSize()] = sizes.get(lb.font().pointSize(), 0) + 1
print('  QLabel 磅值分布:', dict(sorted(sizes.items())), flush=True)
print('  应用默认字体:', app.font().family(), app.font().pointSize(), 'pt', flush=True)

print('--- 参数区组高度（是否出现滚动条）---', flush=True)
for gb in w.findChildren(QGroupBox):
    if gb.isVisible():
        print(f'  {gb.title()!r:22s} h={gb.height():4d} hint_h={gb.sizeHint().height():4d}',
              flush=True)
sb = getattr(w, 'param_scroll', None)
if sb is not None:
    bar = sb.verticalScrollBar()
    print(f'  参数栏滚动条: 可见={bar.isVisible()} '
          f'范围={bar.minimum()}..{bar.maximum()} 页步={bar.pageStep()}', flush=True)

print('--- 帮助对话框实测尺寸（寿命模式正文最长）---', flush=True)
from gui_config import APP_NAME, APP_VERSION  # noqa: E402
html = (f"<h3>{APP_NAME} v{APP_VERSION}</h3>" + w._help_mode_section()
        + "<p><b>快捷键：</b></p><ul>"
        "<li>F5 — 实时预览（寿命模式为开始拟合）</li>"
        "<li>Ctrl+R — 重新加载数据</li><li>Ctrl+O — 选择文件夹</li>"
        "<li>Ctrl+E / Ctrl+S — 导出当前图</li>"
        "<li>Ctrl+Shift+E — 导出全部图片</li>"
        "<li>Ctrl+D — 复制积分结果</li><li>Ctrl+T — 切换浅色 / 深色主题</li>"
        "<li>F1 — 本帮助</li></ul>")
from PyQt5.QtWidgets import QMessageBox as MB  # noqa: E402
box = MB(w)
box.setWindowTitle('帮助')
box.setText(html)
box.setIcon(MB.Information)
box.setStandardButtons(MB.Ok)
box.adjustSize()
print(f'  QMessageBox sizeHint = {box.sizeHint().width()} x {box.sizeHint().height()}',
      flush=True)
scr = app.primaryScreen()
print(f'  屏幕 = {scr.size().width()} x {scr.size().height()} '
      f'(帮助框高度超过屏幕则底部内容被裁掉)', flush=True)
print('MEASURE DONE', flush=True)
