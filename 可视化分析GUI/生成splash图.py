# -*- coding: utf-8 -*-
"""
重新生成 bootloader 启动画面 splash.png（静态资源，打包经 --splash 内嵌）。

版本号取自 gui_config.APP_VERSION；GUI 升版后重跑本脚本即可同步启动图，
避免图内版本号与程序不一致。

版本号同时写进 PNG 的 tEXt 元数据（键 `QLSVersion`），这样 检查版本一致性.py
可以直接**读图内版本号**与 gui_config.APP_VERSION 比对——不再依赖文件 mtime
（mtime 会被无关改动带偏，且无法证明图里烧的到底是哪个版本）。

尺寸说明：PyInstaller 会把 splash 图缩放到最大 760x422 显示，之前按 900x500
生成时被缩小导致文字发虚；现在直接按 760x422 生成（bootloader 不再缩放），
并以 2x 超采样渲染再降采样，保证文字边缘平滑清晰。

配色（v4.28）：这张图由 PyInstaller 的 bootloader 在 **Python 还没启动时**用
Tk 画出来，它读不到任何程序设置，所以**无法跟随主题**——原来固定浅色，
深色会话启动时先闪一块白卡片。现在改成**深色品牌图**（取 THEMES["dark"] 的
深色色板），无论会话主题如何都先看到深色启动图；紧随其后的 Qt 启动画面
（gui_splash.StartupSplash）会按上次会话的主题显示，那一个才是跟随主题的。

用法:
    python 生成splash图.py
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, PngImagePlugin

from gui_config import APP_VERSION, THEMES

W, H = 760, 422                     # PyInstaller splash 的目标尺寸（不再被缩放）
SS = 2                              # 超采样倍率（渲染在 W*SS x H*SS 上再缩回）
CARD = (34, 47, 726, 370)           # 卡片矩形 (l, t, r, b)
BAR_H = 6                           # 卡片顶部彩色条高
ICON = (68, 98, 136, 166)           # 图标位置（68x68）
# 深色品牌配色：直接取深色主题色板，避免这里另抄一套颜色
_D = THEMES["dark"]
C_BG = _D["MPL_FIG"]                # 比窗口底色更深一档，与程序里的"深色图纸"一致
C_CARD = _D["CARD"]
C_BORDER = _D["BORDER"]
C_BAR = _D["ACCENT"]
C_TITLE = _D["TEXT"]
C_TEXT = _D["TEXT_SOFT"]
C_MUTED = _D["MUTED"]


def _font(size, bold=False):
    name = "msyhbd.ttc" if bold else "msyh.ttc"
    return ImageFont.truetype(f"C:/Windows/Fonts/{name}", size * SS)


def _rounded_icon(size=80, radius=18):
    """app_icon.png（优先）或 app_icon.ico 圆角化"""
    here = Path(__file__).parent
    src_path = here / "app_icon.png"
    if not src_path.is_file():
        src_path = here / "app_icon.ico"
    src = Image.open(src_path).convert("RGBA")
    src = src.resize((size * SS, size * SS), Image.LANCZOS)
    mask = Image.new("L", (size * SS, size * SS), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size * SS - 1, size * SS - 1),
                                           radius=radius * SS, fill=255)
    out = Image.new("RGBA", (size * SS, size * SS), (0, 0, 0, 0))
    out.paste(src, (0, 0), mask)
    return out


def main():
    img = Image.new("RGB", (W * SS, H * SS), C_BG)
    draw = ImageDraw.Draw(img)
    s = SS  # 坐标缩放

    # 卡片 + 顶部蓝色条（细条，与卡片同上圆角）
    card = tuple(v * s for v in CARD)
    draw.rounded_rectangle(card, radius=16 * s, fill=C_CARD, outline=C_BORDER, width=1 * s)
    l, t, r, b = card
    draw.rounded_rectangle((l, t, r, t + 27 * s), radius=16 * s, fill=C_BAR)
    draw.rectangle((l, t + BAR_H * s, r, t + 27 * s), fill=C_CARD)

    # 图标 + 标题
    icon = _rounded_icon(ICON[2] - ICON[0])
    img.paste(icon, (ICON[0] * s, ICON[1] * s), icon)
    draw.text(((ICON[2] + 22) * s, 116 * s), "光谱可视化分析工具",
              font=_font(29, bold=True), fill=C_TITLE)

    # 状态与提示
    draw.text((68 * s, 186 * s), "正在启动，请稍候…", font=_font(17), fill=C_TEXT)
    draw.text((68 * s, 224 * s), "首次运行需要解压资源并检查依赖（约 20–40 秒）",
              font=_font(13), fill=C_MUTED)
    draw.text((68 * s, 247 * s), "启动画面消失前勿重复双击", font=_font(13), fill=C_MUTED)

    # 页脚版本
    draw.text((68 * s, 316 * s), f"QLS Lab · v{APP_VERSION}", font=_font(14), fill=C_MUTED)

    # 降采样回目标尺寸（抗锯齿、文字平滑）
    img = img.resize((W, H), Image.LANCZOS)

    out = Path(__file__).parent / "splash.png"
    # 把版本号写进 PNG tEXt 元数据（键 QLSVersion），供 检查版本一致性.py 读取比对
    meta = PngImagePlugin.PngInfo()
    meta.add_text("QLSVersion", str(APP_VERSION))
    meta.add_text("Software", "QLS Lab 光谱可视化分析工具 生成splash图.py")
    img.save(out, pnginfo=meta)
    print(f"已生成 {out}（v{APP_VERSION}，{W}x{H}，PNG tEXt QLSVersion={APP_VERSION}）")


if __name__ == "__main__":
    main()
