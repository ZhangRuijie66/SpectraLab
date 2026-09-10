# -*- coding: utf-8 -*-
"""gui_icons（单色线条图标）离屏冒烟测试——自包含运行器，不用 pytest。

跑法（GUI 目录下）::

    $env:QT_QPA_PLATFORM="offscreen"; $env:QT_QPA_FONTDIR="$env:WINDIR\\Fonts"
    python tests\\test_icons_smoke.py *> tests\\_diag\\icons_smoke.log

覆盖内容
========
1. ``ICON_NAMES`` 里 18 个名字 x 2 个主题的 PNG 都在，主图 48x48、
   ``@24`` 版本 24x24，且都是 RGBA；
2. 每张图都有实际内容：``getbbox()`` 不为 None（不是全透明），
   并且"不透明像素"（alpha>=32）占比落在 2%–60% 之间
   （既证明图形画出来了，也证明不是一整块色块 / 画糊了）；
3. ``icon(name, theme)`` 返回非空 QIcon（``isNull()`` 为 False），
   ``QIcon.pixmap(QSize(20,20))`` 取出来确实是 20x20；48px 档渲染出来的
   不透明像素平均色 == 该主题的描边色（浅 #475569 / 深 #cbd5e1），
   确保浅色界面不会误取深色文件；
4. 健壮性：未知名字 -> 空 QIcon；未知 / 非法主题 -> 回退 light；
   None / 数字 / 带斜杠的名字、非法 size 都不抛异常；把
   ``resource_path`` 打桩成"找不到文件"（模拟 exe 里漏带资源）时，
   ``icon()`` 仍返回空 QIcon 且只记 logging.warning，不崩；
   ``clear_cache()`` 之后重建依然有效；
5. 顺带把两套主题的 48px / 24px 图标拼成对比图写到 ``tests/_diag/``：
   ``icons_preview.png``（48px，上 3 行浅色底、下 3 行深色底）、
   ``icons_preview_24.png``（24px 原生尺寸），供肉眼验收。

结尾打印 ``ICON SMOKE PASSED``；任何一项不过退出码非 0。

（输出刻意只用 ASCII：重定向到日志后用 GBK 控制台回看不会乱码。）
"""
import os
import sys
import traceback

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
# 离屏 QPA 默认没有字体库，截图里文字会是空白；给出字体目录（找不到就算了）
_FONT_DIR = os.path.join(os.environ.get('WINDIR', r'C:\Windows'), 'Fonts')
if os.path.isdir(_FONT_DIR):
    os.environ.setdefault('QT_QPA_FONTDIR', _FONT_DIR)

# 和其它测试一致：把 GUI 目录（tests 的上一级）加进 sys.path
GUI_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if GUI_DIR not in sys.path:
    sys.path.insert(0, GUI_DIR)

import logging  # noqa: E402

from PIL import Image, ImageDraw, ImageFont  # noqa: E402
from PyQt5.QtCore import QSize  # noqa: E402
from PyQt5.QtGui import QIcon  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

import gui_icons  # noqa: E402
from gui_icons import ICON_NAMES, clear_cache, icon, icon_path  # noqa: E402

# gui_icons 是"轻"模块：import 它不应该把 numpy / matplotlib / gui_ui 拖进来
# （这里在**任何** icon() 调用之前取快照，因为首次调用才会延迟导入 gui_components）
EARLY_HEAVY = sorted(
    m for m in sys.modules
    if m.split('.')[0] in ('numpy', 'scipy', 'matplotlib', 'gui_ui', 'gui_data',
                           'gui_plot', 'gui_components')
)

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_diag')
ICONS_DIR = os.path.join(GUI_DIR, 'icons')
THEMES = ('light', 'dark', 'contrast')
THEME_RGB = {'light': (0x47, 0x55, 0x69), 'dark': (0xCB, 0xD5, 0xE1),
             'contrast': (0x00, 0x00, 0x00)}
MIN_OPAQUE, MAX_OPAQUE = 2.0, 70.0
# 图标名数量：v4.28 从 18 增加到 22（多了 4 个入口界面模块图标）；
# v4.29 增加到 24（停靠面板标题栏的 close / float）；v4.30 增加到 25（contrast）
EXPECTED_NAMES = 25
EXPECTED = len(ICON_NAMES) * len(THEMES)

FAILS = []


def check(cond, msg, quiet=False):
    """断言式记录：quiet=True 时只记失败（成功不刷屏）。"""
    if cond:
        if not quiet:
            print(f"  [ok]   {msg}", flush=True)
    else:
        print(f"  [FAIL] {msg}", flush=True)
        FAILS.append(msg)
    return bool(cond)


def _font(size):
    for cand in (r'C:\Windows\Fonts\arial.ttf', r'C:\Windows\Fonts\segoeui.ttf',
                 r'C:\Windows\Fonts\consola.ttf', r'C:\Windows\Fonts\msyh.ttc'):
        try:
            if os.path.isfile(cand):
                return ImageFont.truetype(cand, size)
        except Exception:
            pass
    return ImageFont.load_default()


def _avg_rgb(qi, size=48, min_alpha=128):
    """QIcon 渲染到 size x size 后，不透明像素的平均 RGB；没有像素返回 None。"""
    img = qi.pixmap(QSize(size, size)).toImage()
    sr = sg = sb = n = 0
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            if c.alpha() >= min_alpha:
                sr += c.red()
                sg += c.green()
                sb += c.blue()
                n += 1
    return None if n == 0 else (sr / n, sg / n, sb / n)


def _rgb_close(got, want, tol=12):
    return got is not None and all(abs(got[i] - want[i]) <= tol for i in range(3))


# --------------------------------------------------------------------------
# 1 + 2：文件与内容
# --------------------------------------------------------------------------
def check_pngs():
    print("\n-- 1. PNG files: name x theme x size --", flush=True)
    missing, wrong_size, wrong_mode = [], [], []
    for name in ICON_NAMES:
        for theme in THEMES:
            for size, suffix in ((48, ''), (24, '@24')):
                fn = f"{name}_{theme}{suffix}.png"
                path = os.path.join(ICONS_DIR, fn)
                if not os.path.isfile(path):
                    missing.append(fn)
                    continue
                try:
                    with Image.open(path) as im:
                        im.load()
                        if im.size != (size, size):
                            wrong_size.append(f"{fn}={im.size}")
                        if im.mode != 'RGBA':
                            wrong_mode.append(f"{fn}={im.mode}")
                except Exception as exc:
                    missing.append(f"{fn} ({exc})")
    check(not missing, f"all {EXPECTED * 2} PNGs exist (48px + @24) "
                       f"[missing: {missing[:5]}]")
    check(not wrong_size, f"every 48px file is 48x48 and @24 file is 24x24 "
                          f"[bad: {wrong_size[:5]}]")
    check(not wrong_mode, f"every file is RGBA [bad: {wrong_mode[:5]}]")

    print("\n-- 2. PNG content: not empty, not a solid block --", flush=True)
    empty, out_of_range = [], []
    stats = {}
    for name in ICON_NAMES:
        for theme in THEMES:
            fn = f"{name}_{theme}.png"
            path = os.path.join(ICONS_DIR, fn)
            if not os.path.isfile(path):
                continue
            with Image.open(path) as im:
                im.load()
                rgba = im.convert('RGBA')
                # getbbox()：整图（含 RGB 全零的透明底）非空
                if rgba.getbbox() is None:
                    empty.append(fn)
                alpha = rgba.getchannel('A')
                abbox = alpha.getbbox()
                if abbox is None:                     # 真正的"全透明"判定
                    empty.append(f"{fn} (alpha empty)")
                    continue
                px = list(alpha.getdata())
                ratio = sum(1 for v in px if v >= 32) / float(len(px)) * 100.0
                stats[(name, theme)] = ratio
                if not (MIN_OPAQUE <= ratio <= MAX_OPAQUE):
                    out_of_range.append(f"{fn}={ratio:.1f}%")
    check(not empty, f"all {EXPECTED} images have content (getbbox() is not "
                     f"None) [empty: {empty[:5]}]")
    check(not out_of_range,
          f"opaque-pixel ratio within {MIN_OPAQUE:.0f}%-{MAX_OPAQUE:.0f}% for "
          f"all {EXPECTED} images [bad: {out_of_range[:5]}]")
    for theme in THEMES:
        vals = [(v, n) for (n, t), v in stats.items() if t == theme]
        if vals:
            lo, hi = min(vals), max(vals)
            avg = sum(v for v, _ in vals) / len(vals)
            print(f"  {theme:5s} opaque ratio: min {lo[0]:5.1f}% ({lo[1]}) "
                  f"max {hi[0]:5.1f}% ({hi[1]}) avg {avg:5.1f}%", flush=True)
    # 深浅两套必须是同一张掩膜：不透明占比应完全一致
    diff = [n for n in ICON_NAMES
            if (n, 'light') in stats and (n, 'dark') in stats
            and abs(stats[(n, 'light')] - stats[(n, 'dark')]) > 0.5]
    check(not diff, f"light/dark shapes identical (same opaque ratio) "
                    f"[diff: {diff[:5]}]")


# --------------------------------------------------------------------------
# 3：QIcon
# --------------------------------------------------------------------------
def check_qicon():
    print("\n-- 3. gui_icons.icon() --", flush=True)
    clear_cache()
    null_icons, bad_pixmap, bad_path, bad_color = [], [], [], []
    for name in ICON_NAMES:
        for theme in THEMES:
            qi = icon(name, theme)
            if qi.isNull():
                null_icons.append(f"{name}/{theme}")
                continue
            pm = qi.pixmap(QSize(20, 20))
            if pm.isNull() or (pm.width(), pm.height()) != (20, 20):
                bad_pixmap.append(f"{name}/{theme}={(pm.width(), pm.height())}")
            # icon_path 必须是绝对路径，且指向 icons\ 下对应文件
            p = icon_path(name, theme, 48)
            want = os.path.join(ICONS_DIR, f"{name}_{theme}.png")
            if not p or not os.path.isabs(p) or \
                    os.path.normcase(p) != os.path.normcase(want):
                bad_path.append(f"{name}/{theme}={p}")
            # 48px 档渲染出来的颜色必须是该主题的描边色
            got = _avg_rgb(qi, 48)
            if not _rgb_close(got, THEME_RGB[theme]):
                bad_color.append(f"{name}/{theme}="
                                 f"{None if got is None else tuple(round(v) for v in got)}"
                                 f" != {THEME_RGB[theme]}")
    check(not null_icons, f"{EXPECTED} icons non-null (isNull() is False) "
                          f"[null: {null_icons[:5]}]")
    check(not bad_pixmap, f"pixmap(QSize(20,20)) is 20x20 for all "
                          f"[bad: {bad_pixmap[:5]}]")
    check(not bad_path, f"icon_path() returns absolute icons\\ path for all "
                        f"[bad: {bad_path[:5]}]")
    check(not bad_color, f"rendered 48px color matches theme stroke color "
                         f"(#475569 light / #cbd5e1 dark) [bad: {bad_color[:5]}]")
    # 缓存：同一 (name, theme) 只构造一次（拿到同一个对象）
    check(icon('home', 'light') is icon('home', 'light'),
          "same (name, theme) returns the cached QIcon object")
    check(icon('home', 'dark') is not icon('home', 'light'),
          "different theme -> different QIcon")


# --------------------------------------------------------------------------
# 4：健壮性
# --------------------------------------------------------------------------
def check_robustness():
    print("\n-- 4. robustness (never raise) --", flush=True)
    # 未知名字 -> 空 QIcon
    try:
        qi = icon('no_such_icon_xyz')
        check(qi.isNull(), "unknown name -> null QIcon, no exception")
    except Exception:
        check(False, f"unknown name raised:\n{traceback.format_exc()}")
    # 未知 / 非法主题 -> 回退 light（渲染出来是浅色描边色）
    fallbacks = []
    for bad_theme in ('blue', 'DARKISH', '', None, 3.14, object()):
        try:
            fallbacks.append(_avg_rgb(icon('home', bad_theme), 48))
        except Exception:
            fallbacks.append(f"raised:{bad_theme!r}")
    check(all(_rgb_close(f, THEME_RGB['light']) for f in fallbacks),
          f"unknown/invalid theme falls back to light "
          f"[got: {fallbacks[:3]}]")
    # 大小写 / 空白：'Dark' 应该等于 'dark'
    try:
        check(_rgb_close(_avg_rgb(icon('home', 'Dark'), 48), THEME_RGB['dark']),
              "theme name is case-insensitive ('Dark' == 'dark')")
    except Exception:
        check(False, f"case-insensitive theme raised:\n{traceback.format_exc()}")
    # 各种离谱参数不抛异常（这段是故意喂错值，先把 logging 关掉免得刷屏）
    weird = []
    _root = logging.getLogger()
    _old_level = _root.level
    _root.setLevel(logging.CRITICAL)
    try:
        for bad_name in (None, 123, '', '../gui_ui', 'icons/home', 'home.png',
                         'home_light'):
            for fn, args in ((icon, (bad_name,)),
                             (icon_path, (bad_name, 'light', 48))):
                try:
                    fn(*args)
                except Exception:
                    weird.append(f"{fn.__name__}{args!r}")
        for bad_size in (None, 'abc', 0, -1, 999, 3.5, object()):
            try:
                icon_path('home', 'light', bad_size)
            except Exception:
                weird.append(f"icon_path size={bad_size!r}")
        clear_cache()
    finally:
        _root.setLevel(_old_level)
    check(not weird, f"weird arguments never raise [raised: {weird[:5]}]")
    # size 回退：非法 size 拿到 48 主图；24 拿到 @24 版
    check(icon_path('home', 'light', 24) is not None
          and os.path.basename(icon_path('home', 'light', 24)) == 'home_light@24.png',
          "icon_path(size=24) -> home_light@24.png")
    check(os.path.basename(icon_path('home', 'light', 999)) == 'home_light.png',
          "icon_path(invalid size) -> 48px main file")

    # 资源缺失（模拟 exe 没带上 icons\）：返回空 QIcon + 一行 warning，不崩
    records = []

    class _Catcher(logging.Handler):
        def emit(self, record):
            records.append(record)

    handler = _Catcher(level=logging.WARNING)
    logger = logging.getLogger()
    old_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)
    original = gui_icons._RESOURCE_PATH
    try:
        gui_icons._RESOURCE_PATH = lambda name: None
        clear_cache()
        qi = icon('home', 'light')
        missing_ok = qi.isNull()
        path_none = icon_path('home', 'light', 48) is None
    except Exception:
        missing_ok = False
        path_none = False
        print(traceback.format_exc(), flush=True)
    finally:
        gui_icons._RESOURCE_PATH = original
        logger.removeHandler(handler)
        logger.setLevel(old_level)
        clear_cache()
    check(missing_ok and path_none,
          "resource_path missing -> null QIcon / None path (no crash)")
    check(len(records) >= 2,
          f"missing resource logs logging.warning ({len(records)} records)")
    # 恢复后缓存必须重建成功
    qi = icon('home', 'light')
    check(not qi.isNull(), "clear_cache() then rebuild -> valid QIcon again")
    cleared = clear_cache()
    check(cleared > 0, f"clear_cache() returns cleared count ({cleared})")


# --------------------------------------------------------------------------
# 5：拼图（肉眼验收用）
# --------------------------------------------------------------------------
def write_preview(path, size):
    """把 18 个图标的两套主题拼成一张对比图：上 3 行浅色底、下 3 行深色底。"""
    cols, rows = 6, 3
    cell_w = 96 if size == 48 else 62
    cell_h = 96 if size == 48 else 62
    bg = {'light': (248, 250, 252), 'dark': (30, 41, 59),
          'contrast': (255, 255, 255)}
    fg = {'light': (100, 116, 139), 'dark': (148, 163, 184),
          'contrast': (0, 0, 0)}
    grid = {'light': (226, 232, 240), 'dark': (51, 65, 85),
            'contrast': (0, 0, 0)}
    fnt = _font(11 if size == 48 else 8)
    sheet = Image.new('RGB', (cols * cell_w, 2 * rows * cell_h), bg['light'])
    d = ImageDraw.Draw(sheet)
    for idx, name in enumerate(ICON_NAMES):
        r, c = divmod(idx, cols)
        for ti, theme in enumerate(THEMES):
            row = ti * rows + r
            x0, y0 = c * cell_w, row * cell_h
            d.rectangle([x0, y0, x0 + cell_w - 1, y0 + cell_h - 1], fill=bg[theme])
            ix = x0 + (cell_w - size) // 2
            iy = y0 + 8
            if size == 48:      # 画出 48x48 格子，方便看四周留白
                d.rectangle([ix - 1, iy - 1, ix + size, iy + size], outline=grid[theme])
            fn = f"{name}_{theme}{'' if size == 48 else '@24'}.png"
            try:
                im = Image.open(os.path.join(ICONS_DIR, fn)).convert('RGBA')
            except Exception:
                continue
            sheet.paste(im, (ix, iy), im)
            label = name
            tw = d.textlength(label, font=fnt)
            d.text((x0 + (cell_w - tw) / 2.0, iy + size + 3), label,
                   font=fnt, fill=fg[theme])
    sheet.save(path)
    return sheet.size


def check_preview():
    print("\n-- 5. preview sheets (visual check) --", flush=True)
    if not os.path.isdir(OUT_DIR):
        os.makedirs(OUT_DIR)
    for fname, size in (('icons_preview.png', 48), ('icons_preview_24.png', 24)):
        p = os.path.join(OUT_DIR, fname)
        try:
            wh = write_preview(p, size)
            check(True, f"{fname} written {wh[0]}x{wh[1]} ({size}px icons)")
        except Exception:
            check(False, f"{fname} failed:\n{traceback.format_exc()}")


def main():
    app = QApplication(sys.argv)          # noqa: F841  (QIcon/QPixmap 需要它)
    print(f"QT_QPA_PLATFORM={os.environ.get('QT_QPA_PLATFORM')}", flush=True)
    print(f"GUI_DIR={GUI_DIR}", flush=True)
    print(f"ICON_NAMES={len(ICON_NAMES)} icons: {', '.join(ICON_NAMES)}", flush=True)
    check(len(ICON_NAMES) == EXPECTED_NAMES,
          f"ICON_NAMES has {EXPECTED_NAMES} names (unique)")
    check(len(set(ICON_NAMES)) == len(ICON_NAMES), "ICON_NAMES entries unique")
    check(not EARLY_HEAVY,
          f"importing gui_icons stays light (no numpy/scipy/matplotlib/"
          f"gui_ui loaded) [leaked: {EARLY_HEAVY[:4]}]")

    check_pngs()
    check_qicon()
    check_robustness()
    check_preview()

    print(f"\nicons\\: {ICONS_DIR}", flush=True)
    print(f"preview: {os.path.join(OUT_DIR, 'icons_preview.png')}", flush=True)
    if FAILS:
        print(f"\n{len(FAILS)} CHECK(S) FAILED", flush=True)
        for f in FAILS:
            print(f"  - {f}", flush=True)
        print("ICON SMOKE FAILED", flush=True)
        return 1
    print("\nICON SMOKE PASSED", flush=True)
    return 0


if __name__ == '__main__':
    try:
        code = main()
    except Exception:
        traceback.print_exc()
        print("ICON SMOKE FAILED", flush=True)
        code = 1
    sys.exit(code)
