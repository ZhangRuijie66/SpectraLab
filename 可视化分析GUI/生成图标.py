# -*- coding: utf-8 -*-
"""生成光谱可视化分析工具的单色线条图标（PNG）。

用途
====
界面上的按钮/菜单原先用 emoji 当图标（🏠 🌙 ☀️ ❓ 📂 ▶ 💾 📋 …），
本脚本把它们换成一套统一的**单色线条图标**：用 Pillow 程序化绘制，
不依赖任何外部素材，完全离线、可重复运行。

用法
====
    cd 可视化分析GUI
    python 生成图标.py

输出（全部落在脚本同级的 icons\\ 目录）
======================================
    icons\\<name>_light.png       48x48   浅色界面用（描边 #475569，slate-600）
    icons\\<name>_dark.png        48x48   深色界面用（描边 #cbd5e1，slate-300）
    icons\\<name>_light@24.png    24x24   小尺寸版本（同样两套配色）
    icons\\<name>_dark@24.png    24x24

共 18 个图标 x 2 套配色 x 2 个尺寸 = 72 个 PNG。
（icons\\ 下已有的 4 个 QSS 小图标 arrow-down / arrow-up / check /
chevron-down 不在生成清单里，脚本绝不会覆盖它们。）

风格约定
========
* 24px 逻辑基准 -> 在 4 倍画布 96x96 上绘制，再用 ``Image.LANCZOS``
  缩到 48x48 与 24x24，边缘抗锯齿；
* 描边宽度统一 2.25px@24（96 画布上 9px），圆头端点（``joint="curve"``
  + 两端补圆），只有 play 三角等极少数图形用实心；
* 四周留 2px@24 安全边距，内容按视觉重心居中（末尾会打印各图的实际
  包围盒与偏移，方便自检）；
* 画法全部是常量、不使用随机数，重复运行结果逐字节一致（幂等）。

改图标风格只要改本脚本里的画法再重跑；GUI 侧由 ``gui_icons.py``
按 ``名字 + 主题`` 去 icons\\ 找文件并缓存成 QIcon。
"""

import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw

# --------------------------------------------------------------------------
# 基本参数
# --------------------------------------------------------------------------
BASE = 24                 # 逻辑基准尺寸（24px 图标）
SCALE = 4                 # 放大倍数：96x96 画布上绘制
CANVAS = BASE * SCALE     # 96
LW = 9                    # 线宽（9 / 4 = 2.25px @24，符合 2.2–2.5 规范）
HALF = LW / 2.0
MARGIN = 2 * SCALE        # 2px@24 的安全边距 -> 96 画布上的 8px

THEMES = (("light", "#475569"), ("dark", "#cbd5e1"))
SIZES = ((48, ""), (24, "@24"))

# icons\ 下已有的 4 个 QSS 小图标：永不覆盖
PROTECTED = {"arrow-down.png", "arrow-up.png", "check.png", "chevron-down.png"}

ICON_NAMES = (
    "home", "moon", "sun", "help", "folder_open", "play", "save", "export",
    "image", "images", "copy", "csv", "chart_bar", "pdf", "refresh", "search",
    "select_all", "fit",
)

FILL = 255   # 掩膜上的"上色"
CLEAR = 0    # 掩膜上的"擦除"


# --------------------------------------------------------------------------
# 绘图工具：全部画在 96x96 的单通道掩膜上，最后统一用主题色上色
# --------------------------------------------------------------------------
def _rgb(hex_str):
    h = hex_str.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _caps(d, pts, val=FILL, w=LW):
    """折线两端补圆头（PIL 的 joint="curve" 只处理中间顶点，不管端点）。"""
    for (x, y) in (pts[0], pts[-1]):
        _dot(d, x, y, w / 2.0, val=val)


def _dot(d, x, y, r, val=FILL):
    """实心小圆点（圆头端点 / 图形里的实心细节）。"""
    d.ellipse([x - r, y - r, x + r, y + r], fill=val)


def _poly(d, pts, val=FILL, w=LW):
    """圆头圆角折线；点可以是浮点。"""
    pts = [(float(x), float(y)) for x, y in pts]
    if len(pts) < 2:
        return
    d.line(pts, fill=val, width=int(round(w)), joint="curve")
    _caps(d, pts, val=val, w=w)


def _circle(d, cx, cy, r, val=FILL, w=LW):
    """圆环：外缘半径 = r，描边向内。"""
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=val, width=int(round(w)))


def _arc(d, cx, cy, r, a0, a1, val=FILL, w=LW):
    """圆弧：角度制，0° = 3 点钟方向，角度增大 = 顺时针（屏幕坐标 y 向下）。

    ``a1`` 大于 ``a0`` 表示顺时针扫过 ``a1 - a0`` 度（可以超过 360）。
    自己用折线逼近而不是 ``ImageDraw.arc``，是为了拿到真正的圆头端点。
    """
    sweep = a1 - a0
    n = max(2, int(abs(sweep) / 3.0) + 1)
    pts = []
    for i in range(n + 1):
        a = math.radians(a0 + sweep * i / n)
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    _poly(d, pts, val=val, w=w)


def _rrect(d, x0, y0, x1, y1, r, val=FILL, w=LW):
    """圆角矩形描边（描边向内）。"""
    d.rounded_rectangle([x0, y0, x1, y1], radius=r, outline=val,
                        width=int(round(w)))


def _erase_rrect(d, x0, y0, x1, y1, r):
    """实心圆角矩形擦除（给"叠放"类图标留出前片的位置）。"""
    d.rounded_rectangle([x0, y0, x1, y1], radius=r, fill=CLEAR)


def _erase_rect(d, x0, y0, x1, y1):
    """实心矩形擦除（把被上层图形压住的描边挖掉，避免线条交叉发糊）。"""
    d.rectangle([x0, y0, x1, y1], fill=CLEAR)


# --------------------------------------------------------------------------
# 18 个图标：每个函数接收掩膜的 ImageDraw，在 96x96 坐标里画
# --------------------------------------------------------------------------
def icon_home(d):
    """房子：屋顶三角 + 墙体方框 + 门。"""
    _poly(d, [(14, 46), (48, 14), (82, 46)])            # 屋顶
    _poly(d, [(22, 39), (22, 80), (74, 80), (74, 39)])  # 墙体
    _poly(d, [(40, 80), (40, 58), (58, 58), (58, 80)])  # 门


def icon_moon(d):
    """月牙：外圆减偏移内圆，只描外弧 + 内弧，交点即两个尖角。"""
    cx, cy = 56.9, 48.0
    r_out, r_in, off = 32.0, 28.8, 11.2
    x = (off ** 2 + r_out ** 2 - r_in ** 2) / (2 * off)
    y = math.sqrt(max(r_out ** 2 - x ** 2, 0.0))
    a_out = math.degrees(math.atan2(y, x))              # 外圆上的交点角
    a_in = math.degrees(math.atan2(y, x - off))         # 内圆上的交点角
    _arc(d, cx, cy, r_out, a_out, 360.0 - a_out)        # 外弧（走左侧大半圈）
    _arc(d, cx + off, cy, r_in, a_in, 360.0 - a_in)     # 内弧（内圆的左半边）


def icon_sun(d):
    """太阳：圆 + 8 条短射线。"""
    _circle(d, 48, 48, 19)
    for i in range(8):
        a = math.radians(i * 45)
        ca, sa = math.cos(a), math.sin(a)
        _poly(d, [(48 + 26 * ca, 48 + 26 * sa), (48 + 34 * ca, 48 + 34 * sa)])


def icon_help(d):
    """帮助：圆圈里一个问号（钩 + 短竖 + 点）。

    问号要留在圆环内侧：圆环内缘半径 = 36-9 = 27，问号最高点离圆心 24，
    否则问号顶部会和圆环粘在一起（v1 的 32 半径就撞上了）。
    """
    _circle(d, 48, 47, 36)
    _arc(d, 48, 39.5, 12, 200, 450)    # 问号钩：200° 起顺时针经顶部到 90°
    _poly(d, [(48, 51.5), (48, 58)])   # 短竖
    _dot(d, 48, 66, 5.5)               # 点


def icon_folder_open(d):
    """打开的文件夹：后片（带标签页）+ 右倾的梯形前片。"""
    _poly(d, [(14, 74), (14, 22), (37, 22), (45, 32), (81, 32), (81, 42)])
    _poly(d, [(14, 74), (28, 47), (80, 47), (66, 74), (14, 74)])


def icon_play(d):
    """播放/预览：实心右三角。

    三角的重心天然偏左，所以包围盒略微右移（+4@96），观感才居中。
    """
    d.polygon([(27, 17), (27, 79), (77, 48)], fill=FILL)


def icon_save(d):
    """保存：软盘（外框 + 上方快门 + 下方标签）。

    标签折线的两个端点只画到 y=73（不顶到外框底边），否则圆头端点会
    戳出外框 4.5px。
    """
    _rrect(d, 12, 15, 84, 81, 6)
    _poly(d, [(36, 38), (36, 15), (60, 15), (60, 38), (36, 38)])  # 顶部快门
    _poly(d, [(26, 73), (26, 57), (70, 57), (70, 73)])            # 下方标签


def icon_export(d):
    """导出：上开口的托盘 + 指向右上的箭头。"""
    _poly(d, [(16, 48), (16, 78), (72, 78), (72, 48)])   # 托盘
    _poly(d, [(42, 56), (78, 16)])                       # 箭杆
    _poly(d, [(63, 16), (78, 16), (78, 31)])             # 箭头


def icon_image(d):
    """图片：圆角方框 + 内部小山 + 太阳点。"""
    _rrect(d, 12, 16, 84, 80, 8)
    _poly(d, [(22, 70), (37, 48), (48, 60), (57, 50), (74, 70)])
    _dot(d, 30, 38, 5)


def icon_images(d):
    """多张图片：后一张在右上，前一张在左下（挖掉被压住的描边）。"""
    _rrect(d, 24, 14, 82, 60, 7)                  # 后一张
    _erase_rrect(d, 10, 28, 76, 84, 9)            # 给前一张留位置（含留白）
    _rrect(d, 14, 32, 72, 80, 7)                  # 前一张
    _poly(d, [(24, 70), (38, 54), (46, 66), (54, 58), (66, 70)])
    _dot(d, 30, 48, 4)


def icon_copy(d):
    """复制：剪贴板（板 + 顶部夹子 + 两条内容线）。"""
    _rrect(d, 18, 20, 78, 82, 6)
    _erase_rect(d, 32, 15, 64, 25)                # 挖掉夹子底下的板顶边
    _rrect(d, 34, 11, 62, 29, 6)                  # 夹子
    _poly(d, [(30, 48), (66, 48)])
    _poly(d, [(30, 62), (66, 62)])


def icon_csv(d):
    """CSV：2x2 表格网格 + 向下箭头。"""
    _rrect(d, 16, 13, 80, 53, 5)
    _poly(d, [(48, 13), (48, 53)])
    _poly(d, [(16, 33), (80, 33)])
    _poly(d, [(48, 62), (48, 80)])
    _poly(d, [(38, 70), (48, 80), (58, 70)])


def icon_chart_bar(d):
    """柱状图：三根高低不同的柱。

    柱身画成实心：24px 下"描边柱"的空腔只剩 1px 的缝，看着像残影，
    实心柱在 24px 才是清楚的柱状图（属于规范里允许的少量实心图形）。
    """
    d.rounded_rectangle([10, 20, 32, 78], radius=5, fill=FILL)
    d.rounded_rectangle([36, 38, 58, 78], radius=5, fill=FILL)
    d.rounded_rectangle([62, 58, 84, 78], radius=5, fill=FILL)


def icon_pdf(d):
    """文档：方框 + 右上折角 + 两条横线。"""
    _poly(d, [(22, 13), (54, 13), (78, 37), (78, 81), (22, 81), (22, 13)])
    _poly(d, [(54, 13), (54, 37), (78, 37)])      # 折角
    _poly(d, [(32, 52), (66, 52)])
    _poly(d, [(32, 66), (66, 66)])


def icon_refresh(d):
    """刷新：3/4 圆环 + 箭头（缺口在左上，箭头指向顺时针方向）。

    箭头的顶点放在圆环末端再往前走 10px 的位置、两臂长 16px：v1 那种
    "顶点就是弧端点、两臂只有 11px"的画法在 24px 下糊成一个小疙瘩。
    """
    _arc(d, 48, 52, 26, 270, 540)
    _poly(d, [(46.7, 14.7), (58, 26), (46.7, 37.3)])


def icon_search(d):
    """搜索：放大镜（圆 + 斜柄）。"""
    _circle(d, 38, 38, 26)
    _poly(d, [(51, 51), (78, 78)])


def icon_select_all(d):
    """全选：左侧对勾 + 右侧清单方框（两条横线）。"""
    _poly(d, [(14, 46), (23, 56), (38, 32)])
    _rrect(d, 48, 18, 83, 76, 6)
    _poly(d, [(58, 38), (73, 38)])
    _poly(d, [(58, 58), (73, 58)])


def icon_fit(d):
    """拟合：秒表（圆 + 表针 + 顶部按钮）。"""
    _circle(d, 48, 54, 30)
    _poly(d, [(48, 54), (48, 36)])                # 表针（上）
    _poly(d, [(48, 54), (62, 54)])                # 表针（右）
    _poly(d, [(38, 16), (58, 16)])                # 顶部按钮
    _poly(d, [(48, 16), (48, 26)])                # 按钮连杆


ICONS = {
    "home": icon_home,
    "moon": icon_moon,
    "sun": icon_sun,
    "help": icon_help,
    "folder_open": icon_folder_open,
    "play": icon_play,
    "save": icon_save,
    "export": icon_export,
    "image": icon_image,
    "images": icon_images,
    "copy": icon_copy,
    "csv": icon_csv,
    "chart_bar": icon_chart_bar,
    "pdf": icon_pdf,
    "refresh": icon_refresh,
    "search": icon_search,
    "select_all": icon_select_all,
    "fit": icon_fit,
}


# --------------------------------------------------------------------------
# 渲染与写盘
# --------------------------------------------------------------------------
def render_mask(name):
    """在 96x96 单通道掩膜上绘制一个图标（只有 0 / 255 与抗锯齿过渡）。"""
    mask = Image.new("L", (CANVAS, CANVAS), CLEAR)
    draw = ImageDraw.Draw(mask)
    ICONS[name](draw)
    return mask


def colorize(mask, size, rgb):
    """掩膜 -> 指定尺寸、指定描边色的 RGBA。

    alpha 用 LANCZOS 缩放出抗锯齿边缘；RGB 保持"直通 alpha"（不做预乘，
    否则半透明边缘叠到浅色背景上会发黑）。完全透明的像素清零成
    (0,0,0,0)，这样 PNG 里空白区域是干净的透明，``getbbox()`` 也有意义。
    """
    m = mask.resize((size, size), Image.LANCZOS)
    img = Image.merge("RGBA", (*Image.new("RGB", (size, size), rgb).split(), m))
    img.paste((0, 0, 0, 0), (0, 0), m.point(lambda v: 255 if v == 0 else 0))
    return img


def _report(name, mask):
    """打印一个图标的可见包围盒 / 像素重心 / 不透明占比，自检"没画歪、不空、不满"。

    包围盒按 alpha>=32 统计（LANCZOS 缩小时边缘会有极弱的振铃，肉眼不可见，
    但会把 getbbox() 撑大几个像素，所以自检用阈值版更接近实际观感）。
    """
    small = mask.resize((48, 48), Image.LANCZOS)
    hist = small.histogram()
    opaque_n = sum(hist[32:])
    if opaque_n == 0:
        return f"  {name:<12s} !! EMPTY"
    bbox = small.point(lambda v: 255 if v >= 32 else 0).getbbox()
    x0, y0, x1, y1 = bbox
    # 像素重心（alpha 加权）：比包围盒中心更接近"视觉重心"
    sx = sy = wsum = 0.0
    px = small.load()
    for yy in range(48):
        for xx in range(48):
            a = px[xx, yy]
            sx += xx * a
            sy += yy * a
            wsum += a
    gx, gy = sx / wsum, sy / wsum
    return (f"  {name:<12s} bbox=({x0:2d},{y0:2d})-({x1:2d},{y1:2d}) "
            f"size={x1 - x0:2d}x{y1 - y0:2d} "
            f"centroid=({gx - 23.5:+.1f},{gy - 23.5:+.1f}) "
            f"opaque={opaque_n / 2304.0 * 100.0:4.1f}%")


def main():
    out_dir = Path(__file__).resolve().parent / "icons"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"draw canvas   : {CANVAS}x{CANVAS} (line width {LW}px = "
          f"{LW / SCALE:.2f}px @24, safe margin {MARGIN / SCALE:.0f}px @24)")
    print(f"output dir    : icons\\")
    print(f"icons x themes x sizes = {len(ICON_NAMES)} x {len(THEMES)} x {len(SIZES)}")

    written, skipped, reports, warnings = [], [], [], []
    for name in ICON_NAMES:
        mask = render_mask(name)
        reports.append(_report(name, mask))
        if mask.getbbox() is None:
            warnings.append(f"{name}: 掩膜为空")
        for theme, hex_color in THEMES:
            rgb = _rgb(hex_color)
            for size, suffix in SIZES:
                fname = f"{name}_{theme}{suffix}.png"
                if fname in PROTECTED:            # 理论到不了，纯防御
                    skipped.append(fname)
                    continue
                colorize(mask, size, rgb).save(out_dir / fname)
                written.append(fname)

    print("\n self-check (bbox / opacity at 48px):")
    for line in reports:
        print(line)

    print(f"\n generated {len(written)} PNG files in icons\\ :")
    for fname in written:
        print(f"   icons\\{fname}")
    if skipped:
        print("\n skipped (protected existing files): " + ", ".join(skipped))
    for w in warnings:
        print(f"\n WARNING: {w}")

    expected = len(ICON_NAMES) * len(THEMES) * len(SIZES)
    ok = len(written) == expected and not warnings
    print(f"\n{len(written)}/{expected} files written -- "
          + ("OK" if ok else "INCOMPLETE"))
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(errors="replace")   # 终端编码兜底，别因为字体崩
    except Exception:
        pass
    try:
        sys.exit(main())
    except Exception:
        import traceback
        traceback.print_exc()
        print("ICON GENERATION FAILED")
        sys.exit(1)
