# -*- coding: utf-8 -*-
"""按要求裁剪并放大截图局部，便于目检（工具栏图标对比度等）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PyQt5.QtCore import Qt  # noqa: E402
from PyQt5.QtGui import QPixmap  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)
BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_ui_review')

CROPS = [
    ('dark_lifetime', 'crop_dark_toolbar', (700, 70, 560, 60), 3),
    ('light_absorption', 'crop_light_toolbar', (700, 70, 560, 60), 3),
    ('dark_lifetime', 'crop_dark_actions', (470, 620, 260, 320), 2),
    ('light_absorption', 'crop_light_tree', (0, 0, 380, 330), 2),
]

for src, out, (x, y, w, h), scale in CROPS:
    pm = QPixmap(os.path.join(BASE, src + '.png'))
    if pm.isNull():
        print('missing', src, flush=True)
        continue
    sub = pm.copy(x, y, w, h).scaled(w * scale, h * scale,
                                     Qt.KeepAspectRatio,
                                     Qt.SmoothTransformation)
    p = os.path.join(BASE, out + '.png')
    sub.save(p)
    print('saved', p, sub.width(), sub.height(), flush=True)
print('CROP DONE', flush=True)
