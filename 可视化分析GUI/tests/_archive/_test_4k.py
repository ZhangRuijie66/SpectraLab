import sys, os
sys.path.insert(0, '.')
sys.path.insert(0, '..')
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QTimer
app = QApplication([])
import absorption_gui
w = absorption_gui.AbsorptionGUI()
w.show()
app.processEvents()
# 模拟高分屏窗口（逻辑较大）
w.resize(1440, 900); app.processEvents()
s = w.splitter.sizes()
print('1440x900 sizes:', s, '→ 图片区:', s[3])
print('figure dpi:', w.canvas.fig.get_dpi())
w.load_data_from_folder(r'D:\北大\QLS Lab\SPC\1O2+luminol\谱图\光谱\20260826')
w._do_plot(); w._on_plot_finished(None); app.processEvents()
fi = w.canvas.fig.get_size_inches()
print('canvas:', (w.canvas.width(), w.canvas.height()))
print('figure==canvas:', abs(fi[0]*w.canvas.fig.get_dpi()-w.canvas.width())<15 and abs(fi[1]*w.canvas.fig.get_dpi()-w.canvas.height())<15)
bb = w.canvas.axes.get_position().bounds
print('axes 占宽%:', round(float(bb[2])*100,1), '高%:', round(float(bb[3])*100,1))
sys.stdout.flush()
os._exit(0)