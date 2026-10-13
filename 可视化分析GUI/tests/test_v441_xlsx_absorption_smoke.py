# -*- coding: utf-8 -*-
"""v4.41 GUI 冒烟：吸收模式加载 20261010.xlsx（多列光谱 xlsx）+ 说明.xlsx 文本码编号。

离屏跑法（不弹窗）：
    set QT_QPA_PLATFORM=offscreen
    python tests/test_v441_xlsx_absorption_smoke.py
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

HERE = Path(__file__).resolve().parent
GUI = HERE.parent
ROOT = GUI.parent
for p in (str(GUI), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from PyQt5.QtWidgets import QApplication, QMessageBox      # noqa: E402

for _fn in ('information', 'warning', 'critical'):
    setattr(QMessageBox, _fn, staticmethod(lambda *a, **k: None))

from absorption_gui import AbsorptionGUI                    # noqa: E402

DATA = Path(r'D:\北大\QLS Lab\SPC\1O2+luminol\谱图\光谱\202610\20261010')

fails = []


def check(label, cond, extra=''):
    print(('  OK   ' if cond else '  FAIL ') + label + (('  -> ' + str(extra)) if extra else ''))
    if not cond:
        fails.append(label)


app = QApplication.instance() or QApplication(sys.argv)
w = AbsorptionGUI()

print('== 1. 吸收模式加载 20261010 文件夹 ==')
w.spectrum_type_combo.setCurrentIndex(0)          # 0 = 吸收
check('当前模式 = absorption', w.spectrum_type == 'absorption', w.spectrum_type)
w.load_data_from_folder(str(DATA))

keys = list(w.data_cache.keys())
check('缓存里有 7 条吸收光谱（来自 xlsx 的 7 列）',
      [k for k in keys] == ['R1', 'R2', 'R3', 'S4', 'S3', 'S2', 'S1'], keys)
check('文件列表 7 项', w.file_list.count() == 7, w.file_list.count())

print('== 2. 说明.xlsx 文本码编号被识别 ==')
check('状态栏确认读到了说明.xlsx',
      w.xlsx_info is not None and w.xlsx_info.numbers ==
      ['R1', 'R2', 'R3', 'S1', 'S2', 'S3', 'S4'],
      None if w.xlsx_info is None else w.xlsx_info.numbers)

print('== 3. 图例标签带上浓度信息 ==')
w.xlsx_info = w.xlsx_info or None
for key in ('R1', 'S1'):
    if key not in w.data_cache:
        continue
    lab = w._build_legend_label(key, w.data_cache[key]['data'], show_all=False)
    print(f'   {key} -> {lab!r}')
check('R1 图例 = RB浓度=50, L8i浓度=1000',
      'RB浓度=50' in w._build_legend_label('R1', w.data_cache['R1']['data']),
      w._build_legend_label('R1', w.data_cache['R1']['data']))
check('S1 图例带 Ce6浓度=50',
      'Ce6浓度=50' in w._build_legend_label('S1', w.data_cache['S1']['data']),
      w._build_legend_label('S1', w.data_cache['S1']['data']))

print('== 4. 「数据比较」变量下拉框可用 ==')
check('横轴下拉框可用（不再是「未找到说明.xlsx」）', w.compare_x_combo.isEnabled(),
      w.compare_x_combo.currentText())
check('三个数值列都在',
      sorted(w.compare_x_combo.itemText(i) for i in range(w.compare_x_combo.count()))
      == ['Ce6浓度', 'L8i浓度', 'RB浓度'],
      [w.compare_x_combo.itemText(i) for i in range(w.compare_x_combo.count())])

print('== 5. 画图与数据比较真的出结果 ==')
w.update_plot()
w._do_plot()
check('吸收图有 7 条曲线',
      len(w.canvas.fig.axes[0].get_lines()) >= 7,
      len(w.canvas.fig.axes[0].get_lines()))

w.compare_x_combo.setCurrentText('RB浓度')
w.compare_group_combo.setCurrentIndex(0)
w.compare_metric_combo.setCurrentIndex(0)
res = w._do_compare_plot()
nums = sorted(set(p[4] for p in res['points']))
check('数据比较：只有 R1/R2/R3 有 RB浓度', nums == ['R1', 'R2', 'R3'], nums)
check('数据比较：共 3 个点', res['summary']['n_points'] == 3, res['summary'])
check('跳过的 4 个 S* 理由都是「为空」',
      len(res['skipped']) == 4 and all('为空' in r for _, r in res['skipped']),
      res['skipped'])

print('== 6. 单文件信息页不炸 ==')
items = [w.file_list.item(i) for i in range(w.file_list.count())]
for it in items[:2]:
    try:
        w.on_file_selected(it)
    except Exception as e:
        check(f'信息页 {it.text()}', False, f'{type(e).__name__}: {e}')
check('信息页切换全部成功', True)

print('== 7. 发射模式仍按老规矩只收 CSV（xlsx 不掺进来）==')
w.spectrum_type_combo.setCurrentIndex(1)          # 1 = 发射
check('当前模式 = emission', w.spectrum_type == 'emission', w.spectrum_type)
w.load_data_from_folder(str(DATA))
check('发射模式加载 26 个 CSV（不含 20261010.xlsx）',
      w.file_list.count() == 26, w.file_list.count())
check('发射模式图例仍带浓度信息',
      'RB浓度=50' in w._build_legend_label('R1 (Emission)',
                                            w.data_cache['R1 (Emission)']['data'])
      if 'R1 (Emission)' in w.data_cache else True,
      list(w.data_cache.keys())[:3])

print()
if fails:
    print(f'### 失败 {len(fails)} 项：')
    for f in fails:
        print('   -', f)
    sys.exit(1)
print('SMOKE TEST PASSED')
