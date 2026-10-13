# -*- coding: utf-8 -*-
"""v4.41 端到端验证：20261010 批次的 说明.xlsx（文本码编号）能被识别。

跑法：
    python tests/verify_v441_text_codes.py
"""
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
GUI = HERE.parent
ROOT = GUI.parent
sys.path.insert(0, str(GUI))
sys.path.insert(0, str(ROOT))

import pandas as pd

from read_xlsx_info import (load_xlsx_info, match_number, build_enriched_label,
                            enrich_label_from_name)
import plot_compare as pc

DATA = Path(r'D:\北大\QLS Lab\SPC\1O2+luminol\谱图\光谱\202610\20261010')
fails = []


def check(label, cond, extra=''):
    print(('  OK   ' if cond else '  FAIL ') + label + (('  -> ' + str(extra)) if extra else ''))
    if not cond:
        fails.append(label)


print('== 1. load_xlsx_info（20261010 真实数据） ==')
info = load_xlsx_info(DATA)
check('说明.xlsx 能被读出（以前返回 None）', info is not None)
if info is None:
    sys.exit('致命：说明.xlsx 仍读不出来')
check('编号 = R1/R2/R3/S1..S4',
      info.numbers == ['R1', 'R2', 'R3', 'S1', 'S2', 'S3', 'S4'], info.numbers)
check('信息列 = RB浓度 / Ce6浓度 / L8i浓度',
      info.columns == ['RB浓度', 'Ce6浓度', 'L8i浓度'], info.columns)
check('数值列三个', info.numeric_columns() == ['RB浓度', 'Ce6浓度', 'L8i浓度'],
      info.numeric_columns())
check('R1: RB浓度=50, L8i浓度=1000, 无 Ce6',
      info.value_for('R1', 'RB浓度') == 50 and info.value_for('R1', 'L8i浓度') == 1000
      and info.value_for('R1', 'Ce6浓度') is None, info.info.get('R1'))
check('S1: Ce6浓度=50, 无 RB浓度',
      info.value_for('S1', 'Ce6浓度') == 50 and info.value_for('S1', 'RB浓度') is None,
      info.info.get('S1'))
print('   label_for(R1) =', info.label_for('R1'))
check('label_for(R1) 串正确', info.label_for('R1') == 'RB浓度=50, L8i浓度=1000',
      info.label_for('R1'))

print('== 2. 文件名 -> 编号 匹配（含重复测量的 -2 / -3 / -4） ==')
files = sorted(p.name for p in DATA.glob('*.csv'))
expect = {'R1.csv': 'R1', 'R1-2.csv': 'R1', 'R1-6.csv': 'R1',
          'R2.csv': 'R2', 'R3-3.csv': 'R3',
          'S1-1.csv': 'S1', 'S4-4.csv': 'S4'}
for fn, want in expect.items():
    got = match_number(fn, info.numbers)
    check(f'{fn} -> {want}', got == want, got)
check('目录里 27 个 csv 全部能匹配到编号',
      all(match_number(f, info.numbers) is not None for f in files),
      [f for f in files if match_number(f, info.numbers) is None])
check('R1 与 S1 不会互相串台（旧方案会都命中 1）',
      match_number('R1.csv', info.numbers) != match_number('S1.csv', info.numbers))
check('文本码不做子串匹配：R1 不命中 R10',
      match_number('R10.csv', ['R1', 'R10']) == 'R10',
      match_number('R10.csv', ['R1', 'R10']))

print('== 3. 图例标签 ==')
check('基础标签=R1 -> #R1 RB浓度=50, L8i浓度=1000',
      build_enriched_label('R1', info, 'R1') == '#R1 RB浓度=50, L8i浓度=1000',
      build_enriched_label('R1', info, 'R1'))
check('enrich_label_from_name("S2-1.csv") 带上 Ce6浓度=20',
      'Ce6浓度=20' in enrich_label_from_name('S2-1', 'S2-1.csv', info),
      enrich_label_from_name('S2-1', 'S2-1.csv', info))

print('== 4. plot_compare：真实 CSV + 说明.xlsx 取点 ==')
import tempfile
samples = pc._load_spectra(sorted(DATA.glob('*.csv')), kind='emission')
check('26 个光谱文件全部解析成功', len(samples) == 26, len(samples))
# 12 个 R* 有 RB浓度，14 个 S* 的 RB浓度为空 -> 不进图
res = pc.collect_points(samples, info, x_var='RB浓度', metric='peak_intensity')
nums = sorted(set(p[4] for p in res['points']))
check('R* 的 12 次测量都命中 R1/R2/R3（同一编号的重复测量共享信息）',
      sorted(p[4] for p in res['points']) == ['R1'] * 6 + ['R2'] * 3 + ['R3'] * 3,
      sorted(p[4] for p in res['points']))
check('图上有 12 个点', len(res['points']) == 12, len(res['points']))
check('编号集合 = R1/R2/R3', nums == ['R1', 'R2', 'R3'], nums)
check('x 值只取 50 / 20 / 10', sorted(set(p[1] for p in res['points'])) == [10.0, 20.0, 50.0],
      sorted(set(p[1] for p in res['points'])))
check('跳过的 14 个 S* 样品理由都是「为空」',
      len(res['skipped']) == 14 and all('为空' in r for _, r in res['skipped']),
      (len(res['skipped']), res['skipped'][:3]))
res2 = pc.collect_points(samples, info, x_var='Ce6浓度', metric='peak_intensity')
check('切到 Ce6浓度 -> 14 个 S* 进图（以前一个都进不去）',
      len(res2['points']) == 14
      and sorted(set(p[4] for p in res2['points'])) == ['S1', 'S2', 'S3', 'S4'],
      len(res2['points']))

# 一键路径（folder=...，与 GUI「数据比较」按钮同一条代码路径）+ CSV 编号列内容
out = pc.run_compare(folder=DATA, x_var='RB浓度', metric='peak_intensity',
                     save_dir=os.path.join(tempfile.mkdtemp(prefix='v441_'), 'plots'),
                     verbose=False)
check('run_compare 出图 + 出表', os.path.exists(out['figure']) and os.path.exists(out['csv']))
head = open(out['csv'], encoding='utf-8-sig').read().splitlines()
check('CSV 表头', head[0].split(',')[:3] == ['样品', '编号', 'RB浓度'], head[0])
check('CSV 的「编号」列写的是 R1/R2/R3（不是 1/2/3，也不是空）',
      sorted(set(r.split(',')[1] for r in head[1:])) == ['R1', 'R2', 'R3'],
      sorted(set(r.split(',')[1] for r in head[1:])))

print('== 5. 回归：整数编号批次（20260825）行为不变 ==')
old = Path(r'D:\北大\QLS Lab\SPC\1O2+luminol\谱图\光谱\202608\20260825')
if old.is_dir():
    oi = load_xlsx_info(old)
    check('老批次仍读出整数编号', oi is not None and all(isinstance(n, int) for n in oi.numbers),
          None if oi is None else oi.numbers)
    check('match_number("RB-L8i-1.csv") -> 1',
          match_number('RB-L8i-1.csv', oi.numbers) == 1,
          match_number('RB-L8i-1.csv', oi.numbers))
    check('match_number("20260825-2.csv") -> 2',
          match_number('20260825-2.csv', oi.numbers) == 2,
          match_number('20260825-2.csv', oi.numbers))
else:
    print('  (跳过：老批次目录不存在)')

print()
if fails:
    print(f'### 失败 {len(fails)} 项：')
    for f in fails:
        print('   -', f)
    sys.exit(1)
print('ALL CHECKS PASSED')
