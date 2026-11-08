# -*- coding: utf-8 -*-
"""导出产物的溯源信息（provenance）——回答「这张图/这份 JSON 是哪个版本、
什么时候、用什么参数、从哪些文件导出的」（v5.0.7）。

为什么需要它
------------
审计实测：导出的 JSON 里拟合参数（method / n_rates / k_min / k_max / λ）
**是齐全的**，缺的只是「谁导的、什么时候、从哪个文件、什么版本」。
于是拿三周前的产物回来，无法回答：
  · 这份结果是哪一版程序算的？（算法改过，数字可能不可比）
  · 源文件后来有没有被重新测量覆盖？
  · 这一批样品当时有没有被提示过可比性问题？

PNG 更彻底——只有 matplotlib 自己塞的 ``Software`` 标签。

设计原则
--------
1. **零依赖**：只用 Python 标准库 + gui_config，不引入新包。
2. **失败不阻断导出**：任何一项取不到就跳过，绝不因为溯源信息拿不全
   而让用户导不出图。
3. **可比性警告要进产物**：v5.0.6 加了数据可比性预检，但提示只在界面
   状态栏停留几秒。写进产物才能「换个时间看也知道当时提示过什么」。
"""

import datetime
import json
import platform
import sys
from pathlib import Path


def _app_version():
    try:
        from gui_config import APP_VERSION
        return str(APP_VERSION)
    except Exception:
        return ''


def _run_env():
    """运行环境快照（版本不同可能导致数值不可比，要能追溯）。"""
    out = {}
    for mod, key in (('numpy', 'numpy'), ('scipy', 'scipy'),
                     ('pandas', 'pandas'), ('matplotlib', 'matplotlib')):
        try:
            m = __import__(mod)
            out[key] = getattr(m, '__version__', '')
        except Exception:
            pass
    try:
        from PyQt5.QtCore import QT_VERSION_STR
        out['qt'] = QT_VERSION_STR
    except Exception:
        pass
    out['python'] = sys.version.split()[0]
    out['platform'] = platform.platform()
    return out


def build_meta(params=None, sources=None, comparability=None, extra=None):
    """组装一份溯源信息 dict。

    参数
    ----
    params : dict | None
        影响数值的参数快照（拟合范围 / 单位 / 归一化 / DPI / 显示范围…）。
        只放**会影响结果解释**的项，不要把整个界面状态塞进来。
    sources : list | None
        源文件路径（字符串或 Path 列表）。
    comparability : dict | None
        ``plot_compare.check_comparability()`` 的返回结果。有 error/warn 时
        会把摘要与明细写进产物，这样「当时提示过什么」可追溯。
    extra : dict | None
        其它要记录的键值。

    返回
    ----
    dict，恒含 ``version`` / ``exported_at`` / ``app`` 三个键。
    """
    meta = {
        'app': '光谱可视化分析工具',
        'version': _app_version(),
        'exported_at': datetime.datetime.now().astimezone().isoformat(
            timespec='seconds'),
    }
    try:
        meta['env'] = _run_env()
    except Exception:
        pass

    if sources:
        items = []
        for s in sources:
            try:
                p = Path(str(s))
                items.append({'path': str(p), 'name': p.name,
                              'exists': p.exists()})
            except Exception:
                items.append({'path': str(s)})
        meta['source_files'] = items
        meta['n_source_files'] = len(items)

    if params:
        try:
            meta['params'] = json.loads(
                json.dumps(params, ensure_ascii=False, default=str))
        except Exception:
            meta['params'] = {k: str(v) for k, v in dict(params).items()}

    if comparability:
        try:
            issues = comparability.get('issues') or []
            if issues:
                meta['comparability'] = {
                    'summary': comparability.get('summary', ''),
                    'n_flagged': comparability.get('n_flagged', 0),
                    'warning': ('⚠ 本批样品存在可比性问题，'
                                '误差棒里混进了条件差异，不是纯实验噪声'),
                    'issues': [
                        {'level': it.get('level'),
                         'code': it.get('code'),
                         'title': it.get('title'),
                         'samples': it.get('samples', []),
                         'detail': it.get('detail', '')}
                        for it in issues
                    ],
                }
            else:
                meta['comparability'] = {
                    'summary': comparability.get('summary', ''),
                    'n_flagged': 0,
                }
        except Exception:
            pass

    if extra:
        try:
            meta.update(json.loads(
                json.dumps(extra, ensure_ascii=False, default=str)))
        except Exception:
            meta.update({k: str(v) for k, v in dict(extra).items()})
    return meta


def meta_summary_lines(meta):
    """把 meta 压成几行可读文本（贴在图角上 / 写进报告头）。"""
    if not meta:
        return []
    lines = []
    v = meta.get('version')
    t = meta.get('exported_at')
    if v or t:
        lines.append(f"光谱可视化分析工具 v{v or '?'} · {t or '?'}")
    src = meta.get('source_files') or []
    if src:
        names = [s.get('name', '') for s in src if s.get('name')]
        if len(names) <= 3:
            lines.append('源文件：' + '、'.join(names))
        else:
            lines.append(f'源文件：{names[0]} 等 {len(names)} 个')
        missing = [s.get('name') for s in src if s.get('exists') is False]
        if missing:
            lines.append('⚠ 源文件已不存在：' + '、'.join(missing[:3]))
    comp = meta.get('comparability') or {}
    if comp.get('warning'):
        lines.append(comp['warning'])
    return lines


def stamp_figure(fig, meta, *, corner='lower right', fontsize=6.5, alpha=0.85):
    """在 fig 角落打一行溯源水印（导出图用，不污染画布预览）。

    刻意做得**很小很淡**：它是给"日后回看"用的，不该抢数据的视觉注意力。
    ``corner`` 可选 'lower right' / 'lower left' / 'upper right' / 'upper left'。
    """
    lines = meta_summary_lines(meta)
    if not lines or fig is None:
        return False
    try:
        pos = {
            'lower right': (0.995, 0.005, 'right', 'bottom'),
            'lower left': (0.005, 0.005, 'left', 'bottom'),
            'upper right': (0.995, 0.995, 'right', 'top'),
            'upper left': (0.005, 0.995, 'left', 'top'),
        }.get(corner, (0.995, 0.005, 'right', 'bottom'))
        fig.text(pos[0], pos[1], '\n'.join(lines), fontsize=fontsize,
                 color='#808080', ha=pos[2], va=pos[3], alpha=alpha,
                 transform=fig.transFigure)
        return True
    except Exception:
        return False


def annotate_csv_header(path, meta):
    """给 CSV 产物在**末尾**追加注释行（不改表头，Excel 打开不影响）。

    CSV 没有标准的元数据位；写在末尾 `# ` 开头，用户看到就知道，程序读时
    也能轻易过滤（pandas 用 ``comment='#'``）。之所以不写在最前：
    Excel 双击时第一行会被当表头，放注释会破坏表头。
    """
    if not path or not meta:
        return False
    try:
        lines = meta_summary_lines(meta)
        if not lines:
            return False
        p = Path(path)
        with open(p, 'a', encoding='utf-8-sig', newline='') as f:
            f.write('\n')
            f.write(f"# 本文件由光谱可视化分析工具 v{meta.get('version', '?')} "
                    f"于 {meta.get('exported_at', '?')} 导出\n")
            for ln in lines:
                f.write(f'# {ln}\n')
        return True
    except Exception:
        return False


def write_sidecar(path, meta):
    """在产物旁边写一个 ``<name>_meta.json``（PNG/PDF 无法自带元数据时用）。"""
    if not path or not meta:
        return None
    try:
        p = Path(path)
        side = p.with_name(p.stem + '_meta.json')
        with open(side, 'w', encoding='utf-8') as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        return side
    except Exception:
        return None
