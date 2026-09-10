# -*- coding: utf-8 -*-
"""诊断：深色主题下 QMenu 的样式解析路径对比。

对比三种取图方式，判断「弹出菜单是浅色」到底是样式没生效还是 grab 假象：
  A. popup 后直接 grab（真实用户路径）
  B. 手工 unpolish/polish 后 grab
  C. hide 再 popup 后 grab
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt5.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)
from absorption_gui import AbsorptionGUI  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_diag')
os.makedirs(OUT, exist_ok=True)

w = AbsorptionGUI()
_THEME = sys.argv[1] if len(sys.argv) > 1 else 'dark'
w.toggle_theme(_THEME == 'dark')
app.processEvents()
print('theme =', w.theme, 'CARD =', w.theme_palette()['CARD'], flush=True)


def pump(n=100):
    for _ in range(n):
        app.processEvents()


def report(tag, menu):
    pm = menu.grab()
    png = os.path.join(OUT, f'menu_{tag}.png')
    pm.save(png)
    img = pm.toImage()
    print(f'[{tag}] {img.width()}x{img.height()} '
          f'px(6,6)={img.pixelColor(6, 6).name()} '
          f'px(mid,4)={img.pixelColor(img.width() // 2, 4).name()} '
          f'px(6,h-6)={img.pixelColor(6, img.height() - 6).name()} -> {png}',
          flush=True)


menu = w.help_btn.menu()

menu.popup(w.help_btn.mapToGlobal(w.help_btn.rect().bottomLeft()))
pump()
report('A_popup_direct', menu)

menu.style().unpolish(menu)
menu.style().polish(menu)
menu.update()
pump()
report('B_after_manual_repolish', menu)

menu.hide()
pump(20)
menu.popup(w.help_btn.mapToGlobal(w.help_btn.rect().bottomLeft()))
pump()
report('C_hide_then_popup', menu)

print('MENU PATHS DONE', flush=True)
