# -*- coding: utf-8 -*-
"""UI 现状截图（设计评审用）：浅色/深色各一组，视口 1600x950。

不弹窗（QMessageBox 静态方法打补丁），跑完即退出。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt5.QtCore import QSettings  # noqa: E402
from PyQt5.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication(sys.argv)
for fn in ('information', 'warning', 'critical', 'about'):
    setattr(QMessageBox, fn, staticmethod(lambda *a, **k: None))

from gui_config import APP_ORG, APP_NAME  # noqa: E402
s = QSettings(APP_ORG, APP_NAME)
for k in ('geometry', 'last_mode', 'last_folder', 'theme'):
    s.remove(k)
s.sync()

from absorption_gui import AbsorptionGUI  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_ui_review')
os.makedirs(OUT, exist_ok=True)

ABS_CANDIDATES = [
    r'D:\北大\QLS Lab\SPC\1O2+luminol\谱图\光谱\20260826',
    r'D:\北大\QLS Lab\SPC\1O2+luminol\谱图\光谱\20260903',
    r'D:\北大\QLS Lab\SPC\1O2+luminol\谱图\光谱\20260827',
]
LIFE_FOLDER = r'D:\北大\QLS Lab\SPC\1O2+luminol\谱图\光谱\test2'


def pump(n=30):
    for _ in range(n):
        app.processEvents()


def wait_idle(timeout_s=90):
    """等后台绘图/拟合线程收工，否则截图可能拍到「正在生成图表…」的空画布。"""
    import time
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        app.processEvents()
        if not getattr(w, '_plotting', False):
            pump(15)
            return True
        time.sleep(0.05)
    print('  [WARN] 等待绘图线程超时，截图可能不完整', flush=True)
    return False


def shot(w, name):
    pump(20)
    p = os.path.join(OUT, name + '.png')
    w.grab().save(p)
    print('saved', p, flush=True)


w = AbsorptionGUI()
w.resize(1600, 950)
w.show()
pump()

# ---------- 吸收模式 ----------
for folder in ABS_CANDIDATES:
    if not os.path.isdir(folder):
        continue
    w.spectrum_type_combo.setCurrentIndex(0)
    pump(10)
    w.load_data_from_folder(folder)
    pump(40)
    n = len(getattr(w, 'data_cache', {}) or {})
    print(f'folder={os.path.basename(folder)} loaded={n}', flush=True)
    if n:
        break
w.plot_type_combo.setCurrentIndex(0)
w.update_plot(explicit=True)
wait_idle()
shot(w, 'light_absorption')
w.toggle_theme(True)
wait_idle()
shot(w, 'dark_absorption')

# ---------- 寿命模式 ----------
import os.path  # noqa: E402
if os.path.isdir(LIFE_FOLDER):
    w.toggle_theme(False)
    w.spectrum_type_combo.setCurrentIndex(2)
    pump(20)
    w.load_data_from_folder(LIFE_FOLDER)
    pump(40)
    print('lifetime loaded =', len(getattr(w, 'data_cache', {}) or {}), flush=True)
    shot(w, 'light_lifetime')
    w.toggle_theme(True)
    pump(30)
    shot(w, 'dark_lifetime')

# ---------- 信息页 ----------
try:
    w.tab_widget.setCurrentIndex(3)
    pump(20)
    shot(w, 'dark_info_tab')
except Exception as e:
    print('info tab failed', e, flush=True)

# ---------- 三栏折叠（v4.26 新增：折两栏后画布 ≥1000px） ----------
w.tab_widget.setCurrentIndex(0)          # 回到画布页
w.toggle_theme(False)
pump(20)
for i in (0, 1):                         # 折叠目录树 + 数据栏
    w.toggle_panel(i, collapsed=True)
pump(20)
print('collapsed: sizes =', w.splitter.sizes(), flush=True)
shot(w, 'light_collapsed')
w.toggle_theme(True)
pump(20)
shot(w, 'dark_collapsed')
w.toggle_theme(False)
for i in (0, 1):                         # 复原（后面的截图仍要完整三栏）
    w.toggle_panel(i, collapsed=False)
pump(20)

# ---------- 帮助窗口（v4.24 新增：非模态可滚动窗口，深浅两套） ----------
for theme, dark in (('light', False), ('dark', True)):
    w.toggle_theme(dark)
    pump(10)
    try:
        dlg = w.show_help()
        pump(40)
        p = os.path.join(OUT, f'help_{theme}.png')
        dlg.grab().save(p)
        print('saved', p, dlg.width(), 'x', dlg.height(), flush=True)
        dlg.close()
    except Exception as e:
        print('help dialog shot failed:', e, flush=True)

# ---------- 入口界面 ----------
from gui_launcher import ModuleLauncher  # noqa: E402

for theme in ('light', 'dark'):
    lau = ModuleLauncher(theme=theme)
    lau.show()
    pump(20)
    p = os.path.join(OUT, f'launcher_{theme}.png')
    lau.grab().save(p)
    print('saved', p, flush=True)
    lau.close()

print('SHOTS DONE', flush=True)
