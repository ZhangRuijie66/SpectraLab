# -*- coding: utf-8 -*-
"""
版本一致性只读检查（E5 / F1 补盲区）
====================================

用途：升版后一键体检，避免"改了 gui_config 却忘了写 CHANGELOG / 忘了重生成
splash.png / 忘了给打包脚本加 --hidden-import / exe 还是旧的 / mac 副本没同步
/ 源码里还残留旧版本号"这类问题。

检查项：
  1. 能否从 gui_config.py 读出 APP_VERSION 与 RELEASE_DATE
  2. 更新日志\\CHANGELOG_v{版本号去点}.md 是否存在（4.15 -> CHANGELOG_v415.md）
  3. 更新日志 目录里是否存在**比当前版本更高**的 CHANGELOG（版本号回退/漏改）
  4. splash.png 内嵌的版本号（PNG tEXt 键 QLSVersion）是否等于 APP_VERSION
     —— v4.21 起改为读 PNG 元数据，不再比文件 mtime（mtime 会被无关改动带偏）
  5. 便携版\\光谱可视化分析工具.exe 是否比"打包输入集合"新（exe 落后 = FAIL）
  6. 绘图模块清单由 `sorted(parent.glob('plot_*.py'))` 动态推导（不再硬编码）
  7. 打包便携版.ps1 是否给全部绘图模块写了 --hidden-import（缺失 = FAIL）
  8. mac打包文件夹\\build_mac.command 是否给全部绘图模块写了 --hidden-import（缺失 = WARN）
  9. mac 副本逐文件 SHA256 比对：清单来自 同步到mac文件夹.ps1 的 SYNC-MANIFEST 区块
     （**清单唯一真源**）；哈希不一致 / 目标缺失 / 源缺失 = FAIL
 10. gui_ui.py / start_gui.py / launch_hidden.py / entry_gui.py 里是否残留
     硬编码的版本号字符串（只报告，不修改）

每项打印 ✅ / ⚠️ / ❌ 与中文说明，结尾打印总结。

**本脚本只读，绝不修改任何文件。**
退出码：无 ❌ 时为 0，存在 ❌ 时为 1（便于接到别的脚本里）。

用法：
    python 检查版本一致性.py
"""
import hashlib
import re
import struct
import sys
from pathlib import Path

# ---------------------------------------------------------------- 终端兼容
def _encodable(s):
    """当前 stdout 能否编码该字符（GBK 控制台编码不了 ✅ 等 emoji）。"""
    enc = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        s.encode(enc)
        return True
    except Exception:
        return False


_OK = "✅" if _encodable("✅") else "[OK]"
_WARN = "⚠️" if _encodable("⚠️") else "[WARN]"
_FAIL = "❌" if _encodable("❌") else "[FAIL]"


def _p(text=""):
    """安全打印：编码不了的字符降级替换，绝不因编码异常中断检查。"""
    enc = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        print(text)
    except UnicodeEncodeError:
        sys.stdout.write(text.encode(enc, errors="replace").decode(enc, errors="replace") + "\n")


# ---------------------------------------------------------------- 常量
ROOT = Path(__file__).resolve().parent
PARENT = ROOT.parent                      # 画图 目录（绘图模块所在处）
CONFIG_PY = ROOT / "gui_config.py"
CHANGELOG_DIR = ROOT / "更新日志"
SPLASH_PNG = ROOT / "splash.png"
SPLASH_SCRIPT = ROOT / "生成splash图.py"
BUILD_PS1 = ROOT / "打包便携版.ps1"
MAC_DIR = ROOT / "mac打包文件夹"
MAC_CONFIG_PY = MAC_DIR / "gui_config.py"
MAC_BUILD_CMD = MAC_DIR / "build_mac.command"
SYNC_PS1 = ROOT / "同步到mac文件夹.ps1"
PORTABLE_EXE = ROOT / "便携版" / "光谱可视化分析工具.exe"

# splash.png 里烧进去的版本号用的 PNG tEXt 键（生成splash图.py 写入）
PNG_META_KEY = "QLSVersion"

# ---- 打包输入集合（exe 新鲜度基准）----
# GUI 目录下的 *.py：gui_*.py（glob）+ 四个入口/启动脚本。
# 不含 生成splash图.py（它的产物 splash.png 本身已单列）与 检查版本一致性.py
# （维护脚本，改它不该让 exe 判定为"变旧"）。
GUI_GLOB_PY = "gui_*.py"
GUI_ENTRY_PY = ["absorption_gui.py", "entry_gui.py", "start_gui.py", "launch_hidden.py"]
PACK_ASSETS = ["splash.png", "app_icon.ico"]

# ---- 绘图模块（glob 推导，不硬编码）----
# GUI 直接 import 的、非 plot_ 前缀的两个辅助模块（同样要 --hidden-import）
AUX_MODULES = ["read_xlsx_info", "curve_colors"]

# glob 出来的 plot_*.py 里，下面这些**不是 GUI 模块**，不参与打包，故不要求 hidden-import：
#   plot_absorption_test.py —— 早期单模块测试脚本（无 GUI 集成）
#   plot_zn_rb_analysis.py  —— 另一课题（Zn-Rb 分析）的独立模块，GUI 未集成
# 若哪天它们被 GUI 集成，下面的 check_plot_modules() 会直接报 FAIL 提醒。
PLOT_MODULE_EXCLUDE = {"plot_absorption_test", "plot_zn_rb_analysis"}

# 需要扫描硬编码版本号的源码（不含 gui_config.py 本身——那里是唯一合法来源）
VERSION_SCAN_FILES = ["gui_ui.py", "start_gui.py", "launch_hidden.py", "entry_gui.py"]

# 判断"某个模块是否被 GUI 集成"时扫描的源码
GUI_SOURCE_FILES = ["absorption_gui.py", "entry_gui.py", "gui_ui.py", "gui_data.py",
                    "gui_plot.py", "gui_launcher.py", "gui_splash.py", "gui_components.py"]

# SYNC-MANIFEST 区块标记（与 同步到mac文件夹.ps1 共用）
_MANIFEST_BEGIN = "SYNC-MANIFEST BEGIN"
_MANIFEST_END = "SYNC-MANIFEST END"
_MANIFEST_ENTRY_RE = re.compile(
    r'"\s*(appdir|parentdir|app|parent)\s*\|\s*([^"|]+?)\s*(?:\|\s*([A-Za-z]+)\s*)?"')

# 字符串字面量（用于只在字符串里找版本号，避免命中注释和算式）
_LITERAL_RE = re.compile(r'''"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*' ''', re.X)
# 整个字面量就是一个版本号： "4.15" / 'v4.1'
_EXACT_VER_RE = re.compile(r"\s*v?(\d{1,2}\.\d{1,3})\s*")
# 字面量里带版本前缀的版本号： "v4.12"、"版本 4.12"、"Version: 4.12"
_PREFIXED_VER_RE = re.compile(
    r"(?:^|[^0-9A-Za-z])(?:v|V|版本|Version|version|ver)\s*[:：]?\s*(\d{1,2}\.\d{1,3})(?![0-9.])")

results = []   # (level, title, detail)


def add(level, title, detail=""):
    results.append((level, title, detail))


def _fmt_mtime(p):
    try:
        import datetime
        return datetime.datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return "未知"


def _sha256(path):
    """分块计算 SHA256（大文件也不吃内存）。"""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _brief(items, limit=12):
    """列表太长就截断，避免一次刷屏几十行。"""
    items = list(items)
    if len(items) <= limit:
        return "、".join(items)
    return "、".join(items[:limit]) + "…（共 {} 项）".format(len(items))


def parse_version_tuple(s):
    """'4.15' -> (4, 15)；'2' -> (2, 0)；解析失败返回 None。"""
    parts = str(s).strip().lstrip("vV").split(".")
    try:
        major = int(parts[0])
        minor = int(parts[1]) if len(parts) > 1 else 0
    except (ValueError, IndexError):
        return None
    return (major, minor)


def version_from_filename(name):
    """CHANGELOG_v415.md -> '4.15'（把数字串按 首位=主版本 还原）。"""
    m = re.search(r"CHANGELOG_v(\d+)\.md$", name, re.I)
    if not m:
        return None
    d = m.group(1)
    return d[0] + "." + d[1:] if len(d) > 1 else d + ".0"


def version_from_changelog_text(text):
    """从 CHANGELOG 正文里取 **版本**：v4.15。"""
    m = re.search(r"版本\s*\**\s*[：:]\s*\**\s*v?(\d+\.\d+)", text)
    return m.group(1) if m else None


def read_app_version():
    """从 gui_config.py 文本里取 APP_VERSION / RELEASE_DATE（不 import，避免副作用）。"""
    if not CONFIG_PY.is_file():
        return None, None
    text = CONFIG_PY.read_text(encoding="utf-8", errors="replace")
    ver = re.search(r'^\s*APP_VERSION\s*=\s*["\']([^"\']+)["\']', text, re.M)
    date = re.search(r'^\s*RELEASE_DATE\s*=\s*["\']([^"\']+)["\']', text, re.M)
    return (ver.group(1) if ver else None, date.group(1) if date else None)


def read_png_text_chunks(path):
    """纯标准库读 PNG 的 tEXt 块（不依赖 pillow，检查脚本要能裸跑）。

    PNG 结构：8 字节签名 + 若干块 [4B 长度][4B 类型][数据][4B CRC]。
    tEXt 数据 = keyword + b"\\x00" + 文本（latin-1 编码）。
    返回 {keyword: text}；解析不了就返回空 dict。
    """
    out = {}
    try:
        with open(path, "rb") as fh:
            if fh.read(8) != b"\x89PNG\r\n\x1a\n":
                return out
            while True:
                head = fh.read(8)
                if len(head) < 8:
                    break
                length, ctype = struct.unpack(">I4s", head)
                data = fh.read(length)
                fh.read(4)          # 跳过 CRC
                if ctype == b"tEXt" and b"\x00" in data:
                    k, v = data.split(b"\x00", 1)
                    out[k.decode("latin-1")] = v.decode("latin-1")
                elif ctype == b"IEND":
                    break
    except Exception:
        return out
    return out


def plot_module_stems():
    """glob 推导绘图模块名（不带 .py），并剔除明确非 GUI 的脚本。"""
    return [p.stem for p in sorted(PARENT.glob("plot_*.py"))
            if p.stem not in PLOT_MODULE_EXCLUDE]


def required_hidden_modules():
    """打包必须 --hidden-import 的模块：glob 出来的绘图模块 + 两个辅助模块。"""
    return plot_module_stems() + AUX_MODULES


def pack_input_files():
    """打包输入集合：GUI 的 *.py + 绘图模块 + splash.png + app_icon.ico。"""
    files = []
    for p in sorted(ROOT.glob(GUI_GLOB_PY)):
        files.append(p)
    for name in GUI_ENTRY_PY:
        p = ROOT / name
        if p.is_file():
            files.append(p)
    for stem in required_hidden_modules():
        p = PARENT / (stem + ".py")
        if p.is_file():
            files.append(p)
    for name in PACK_ASSETS:
        p = ROOT / name
        if p.is_file():
            files.append(p)
    return files


# ================================================================ 检查 1
def check_read_config():
    ver, date = read_app_version()
    if not ver:
        add("fail", "读取 gui_config.py 的 APP_VERSION",
            f"未能从 {CONFIG_PY} 解析出 APP_VERSION，请确认变量写法为 APP_VERSION = \"x.y\"")
        return None, None
    detail = f"APP_VERSION = {ver}，RELEASE_DATE = {date or '（未找到 RELEASE_DATE）'}"
    if not date:
        add("warn", "读取 gui_config.py 的版本信息", detail)
    else:
        add("ok", "读取 gui_config.py 的版本信息", detail)
    return ver, date


# ================================================================ 检查 2
def check_changelog_exists(version):
    if not CHANGELOG_DIR.is_dir():
        add("fail", "更新日志目录", f"目录不存在：{CHANGELOG_DIR}")
        return None
    expect = "CHANGELOG_v{}.md".format(re.sub(r"\D", "", version))
    target = CHANGELOG_DIR / expect
    if target.is_file():
        add("ok", "当前版本的 CHANGELOG", f"已存在：更新日志\\{expect}")
        return target
    add("fail", "当前版本的 CHANGELOG",
        f"缺少 更新日志\\{expect}（版本 {version}）。每个版本都必须写一份更新日志。")
    return None


# ================================================================ 检查 3
def check_higher_changelog(version):
    cur = parse_version_tuple(version)
    if cur is None:
        add("warn", "检测更高的 CHANGELOG", f"当前版本 {version} 无法解析，跳过比较")
        return
    if not CHANGELOG_DIR.is_dir():
        add("warn", "检测更高的 CHANGELOG", "更新日志目录不存在，跳过")
        return

    higher = []
    for f in sorted(CHANGELOG_DIR.glob("CHANGELOG_v*.md")):
        text = f.read_text(encoding="utf-8", errors="replace")
        v = version_from_changelog_text(text) or version_from_filename(f.name)
        t = parse_version_tuple(v) if v else None
        if t and t > cur:
            higher.append((f.name, v))

    if higher:
        detail = "以下 CHANGELOG 的版本高于 gui_config.APP_VERSION={}：".format(version)
        detail += "；".join(f"{n}（v{v}）" for n, v in higher)
        detail += " —— 可能是版本号被回退，或升版时漏改了 gui_config.py"
        add("fail", "检测更高的 CHANGELOG", detail)
    else:
        add("ok", "检测更高的 CHANGELOG",
            f"更新日志里没有高于 {version} 的版本，版本号没有回退")


# ================================================================ 检查 4（splash 版本，读 PNG 元数据）
def check_splash_version(version):
    if not SPLASH_PNG.is_file():
        add("fail", "splash.png 内嵌版本号", f"文件不存在：{SPLASH_PNG}")
        return
    meta = read_png_text_chunks(SPLASH_PNG)
    got = meta.get(PNG_META_KEY)
    info = "splash.png = {}（{} 字节）".format(_fmt_mtime(SPLASH_PNG), SPLASH_PNG.stat().st_size)

    if got is None:
        add("fail", "splash.png 内嵌版本号",
            "PNG 里没有 tEXt 键 {}（只有这些：{}）。说明这张 splash.png 是"
            "旧脚本生成的，无法核对图内版本号 —— 请重跑 python 生成splash图.py 后重新打包。{}"
            .format(PNG_META_KEY, ", ".join(sorted(meta)) or "无", info))
    elif got.strip() == str(version).strip():
        add("ok", "splash.png 内嵌版本号",
            f"图内 {PNG_META_KEY}={got}，与 gui_config.APP_VERSION={version} 一致。{info}")
    else:
        add("fail", "splash.png 内嵌版本号",
            "图内 {}={}，gui_config.APP_VERSION={} —— 版本号不一致，"
            "请重跑 python 生成splash图.py 后重新打包。{}"
            .format(PNG_META_KEY, got, version, info))


# ================================================================ 检查 5（exe 新鲜度）
def check_exe_freshness():
    if not PORTABLE_EXE.is_file():
        add("warn", "便携版 exe 新鲜度",
            f"未找到 {PORTABLE_EXE}（尚未打包或已清理），跳过新鲜度检查。")
        return

    inputs = pack_input_files()
    if not inputs:
        add("warn", "便携版 exe 新鲜度", "没有找到任何打包输入文件，跳过检查")
        return

    newest = max(inputs, key=lambda p: p.stat().st_mtime)
    t_exe = PORTABLE_EXE.stat().st_mtime
    t_new = newest.stat().st_mtime
    newer = [p for p in inputs if p.stat().st_mtime > t_exe]

    info = "exe = {}；输入集合 {} 个文件，最新 = {}（{}）".format(
        _fmt_mtime(PORTABLE_EXE), len(inputs), newest.name, _fmt_mtime(newest))

    if t_exe >= t_new:
        add("ok", "便携版 exe 新鲜度",
            f"exe 不早于全部打包输入，产物是最新的。{info}")
    else:
        add("fail", "便携版 exe 新鲜度",
            "exe 比打包输入旧，说明改了源码/资源后没重新打包。{}；"
            "有 {} 个输入比 exe 新：{} —— 请重跑 打包便携版.ps1。"
            .format(info, len(newer),
                    _brief(["{}（{}）".format(p.name, _fmt_mtime(p)) for p in
                            sorted(newer, key=lambda q: q.stat().st_mtime, reverse=True)])))


# ================================================================ 检查 6（绘图模块动态推导）
def check_plot_modules():
    """模块清单由 glob 推导；同时守住"被排除的模块不许悄悄被集成"。"""
    globbed = [p.stem for p in sorted(PARENT.glob("plot_*.py"))]
    used = plot_module_stems()

    gui_text = ""
    for name in GUI_SOURCE_FILES:
        p = ROOT / name
        if p.is_file():
            gui_text += p.read_text(encoding="utf-8", errors="replace")

    bad = []
    for stem in sorted(PLOT_MODULE_EXCLUDE):
        if re.search(r"(?:^|\n)\s*(?:from|import)\s+{}\b".format(re.escape(stem)), gui_text) \
                or ("import {} as".format(stem) in gui_text):
            bad.append(stem)

    if bad:
        add("fail", "绘图模块清单（动态推导）",
            "以下模块在 PLOT_MODULE_EXCLUDE 里被排除，但已经被 GUI 源码 import 了：{}"
            " —— 请从 检查版本一致性.py 的 PLOT_MODULE_EXCLUDE 中删掉它们，"
            "并补进 打包便携版.ps1 / 同步到mac文件夹.ps1 的清单。".format(", ".join(bad)))
    else:
        add("ok", "绘图模块清单（动态推导）",
            "glob(plot_*.py) 共 {} 个：{}；剔除 {} 个非 GUI 脚本（{}）后，"
            "参与打包的绘图模块 = {} 个：{}".format(
                len(globbed), _brief(globbed),
                len(PLOT_MODULE_EXCLUDE), _brief(sorted(PLOT_MODULE_EXCLUDE)),
                len(used), _brief(used)))


def _hidden_imports_ps1(raw):
    """从 ps1 文本里抠出 --hidden-import 的模块名（兼容 "--hidden-import","x", 与 =x）。"""
    norm = raw.replace('"', "").replace("'", "").replace(" ", "").replace("\t", "")
    return set(re.findall(r"--hidden-import[,=]([A-Za-z0-9_.]+)", norm))


def _hidden_imports_shell(raw):
    """从 shell 脚本里抠出 --hidden-import 的模块名（"--hidden-import x \\" 形式）。"""
    return set(re.findall(r"--hidden-import\s+([A-Za-z0-9_.]+)", raw))


# ================================================================ 检查 7（Windows 打包脚本）
def check_hidden_imports():
    required = required_hidden_modules()
    if not BUILD_PS1.is_file():
        add("fail", "打包脚本 --hidden-import", f"文件不存在：{BUILD_PS1}")
        return
    have = _hidden_imports_ps1(BUILD_PS1.read_text(encoding="utf-8", errors="replace"))
    missing = [m for m in required if m not in have]

    if not missing:
        add("ok", "打包脚本 --hidden-import",
            f"{len(required)} 个绘图模块（{_brief(required)}）均已写入 打包便携版.ps1")
    else:
        add("fail", "打包脚本 --hidden-import",
            "以下模块没有在 打包便携版.ps1 里写 --hidden-import：{}"
            " —— 打包出的 exe 可能在运行时报 ModuleNotFoundError，请补上再打包。"
            .format(", ".join(missing)))


# ================================================================ 检查 8（mac 打包脚本）
def check_mac_build_hidden_imports():
    required = required_hidden_modules()
    if not MAC_BUILD_CMD.is_file():
        add("warn", "（附加）mac 打包脚本 --hidden-import",
            f"文件不存在：{MAC_BUILD_CMD}，先运行 同步到mac文件夹.ps1")
        return
    have = _hidden_imports_shell(MAC_BUILD_CMD.read_text(encoding="utf-8", errors="replace"))
    missing = [m for m in required if m not in have]

    if not missing:
        add("ok", "（附加）mac 打包脚本 --hidden-import",
            f"{len(required)} 个绘图模块均已写入 build_mac.command")
    else:
        add("warn", "（附加）mac 打包脚本 --hidden-import",
            "以下模块没有在 mac打包文件夹\\build_mac.command 里写 --hidden-import：{}"
            " —— mac 版运行/打包时可能 ImportError，请补上并重新同步。"
            .format(", ".join(missing)))


# ================================================================ 检查 9（mac 副本逐文件 SHA256）
def parse_sync_manifest():
    """解析 同步到mac文件夹.ps1 的 SYNC-MANIFEST 区块。

    返回 [(scope, rel, optional), ...]；文件/区块缺失或解析不到条目时返回 None。
    """
    if not SYNC_PS1.is_file():
        return None
    text = SYNC_PS1.read_text(encoding="utf-8-sig", errors="replace")
    if _MANIFEST_BEGIN not in text or _MANIFEST_END not in text:
        return None
    block = text.split(_MANIFEST_BEGIN, 1)[1].split(_MANIFEST_END, 1)[0]
    entries = []
    for line in block.splitlines():
        s = line.strip()
        if not s.startswith('"'):
            continue
        m = _MANIFEST_ENTRY_RE.match(s)
        if not m:
            continue
        scope, rel = m.group(1), m.group(2).strip()
        optional = (m.group(3) or "").strip().lower() == "optional"
        entries.append((scope, rel, optional))
    return entries or None


def _expand_manifest(entries):
    """[(scope, rel, optional)] -> [(源 Path, mac 侧相对路径, optional)]"""
    plan = []
    for scope, rel, optional in entries:
        if scope in ("appdir", "parentdir"):
            root = ROOT if scope == "appdir" else PARENT
            d = root / rel
            if not d.is_dir():
                plan.append((d, rel, optional))     # 让下面的"源缺失"分支报出来
                continue
            for f in sorted(d.rglob("*")):
                if f.is_file():
                    plan.append((f, str(Path(rel) / f.relative_to(d)), optional))
        else:
            root = ROOT if scope == "app" else PARENT
            plan.append((root / rel, rel, optional))
    return plan


def check_mac_hashes(entries):
    if entries is None:
        add("fail", "mac 副本 SHA256 比对",
            "无法从 同步到mac文件夹.ps1 的 SYNC-MANIFEST 区块解析出同步清单"
            "（文件不存在 / 标记缺失 / 条目为空）。清单是 mac 一致性的唯一真源，"
            "请先修好该脚本再检查。")
        return
    if not MAC_DIR.is_dir():
        add("fail", "mac 副本 SHA256 比对",
            f"目录不存在：{MAC_DIR}，请先运行 同步到mac文件夹.ps1")
        return

    plan = _expand_manifest(entries)
    mismatched, miss_dest, miss_src = [], [], []
    ok_n, skipped = 0, 0

    for src, rel_dest, optional in plan:
        dst = MAC_DIR / rel_dest
        if not src.is_file():
            if optional:
                skipped += 1
                continue
            miss_src.append(rel_dest)
            continue
        if not dst.is_file():
            miss_dest.append(rel_dest)
            continue
        try:
            same = _sha256(src) == _sha256(dst)
        except OSError as e:
            mismatched.append("{}（读取失败：{}）".format(rel_dest, e))
            continue
        if same:
            ok_n += 1
        else:
            mismatched.append(rel_dest)

    # 清单是否覆盖全部绘图模块（新增 plot_xxx.py 忘了加清单 = mac 打包会 ImportError）
    listed = {Path(rel).name for scope, rel, _opt in entries if scope in ("app", "parent")}
    not_listed = ["{}.py".format(s) for s in required_hidden_modules() if "{}.py".format(s) not in listed]

    problems = []
    if mismatched:
        problems.append("哈希不一致 {} 个：{}".format(len(mismatched), _brief(mismatched)))
    if miss_dest:
        problems.append("mac 副本缺失 {} 个：{}".format(len(miss_dest), _brief(miss_dest)))
    if miss_src:
        problems.append("源文件缺失 {} 个：{}".format(len(miss_src), _brief(miss_src)))
    if not_listed:
        problems.append("绘图模块未列入同步清单 {} 个：{}".format(len(not_listed), _brief(not_listed)))

    summary = ("清单 {} 条 → 展开 {} 个文件；一致 {} 个，跳过可选 {} 个"
               .format(len(entries), len(plan), ok_n, skipped))

    if problems:
        add("fail", "mac 副本 SHA256 比对",
            "mac打包文件夹 与主目录不一致（清单真源：同步到mac文件夹.ps1 的 SYNC-MANIFEST）。"
            "{}。{}\n        —— 请运行 同步到mac文件夹.ps1 重新同步（本检查只读，不会替你同步）。"
            .format(summary, "；".join(problems)))
    else:
        add("ok", "mac 副本 SHA256 比对",
            "mac打包文件夹 与主目录逐文件 SHA256 全部一致。{}".format(summary))


def check_mac_copy_version(version):
    """mac 副本 gui_config.py 的版本号（SHA256 之外的快速定位信息）。"""
    if not MAC_CONFIG_PY.is_file():
        add("warn", "（附加）mac 副本版本号",
            "mac打包文件夹\\gui_config.py 不存在，先运行 同步到mac文件夹.ps1")
        return
    text = MAC_CONFIG_PY.read_text(encoding="utf-8", errors="replace")
    m = re.search(r'^\s*APP_VERSION\s*=\s*["\']([^"\']+)["\']', text, re.M)
    mac_ver = m.group(1) if m else None
    if mac_ver == version:
        add("ok", "（附加）mac 副本版本号", f"mac打包文件夹 的版本与主目录一致（{version}）")
    else:
        add("warn", "（附加）mac 副本版本号",
            f"mac打包文件夹\\gui_config.py = {mac_ver}，主目录 = {version}，"
            "请运行 同步到mac文件夹.ps1 重新同步")


# ================================================================ 检查 10
def check_hardcoded_versions(version):
    """只报告，不修改。"""
    known = {version}
    for f in CHANGELOG_DIR.glob("CHANGELOG_v*.md") if CHANGELOG_DIR.is_dir() else []:
        v = version_from_changelog_text(f.read_text(encoding="utf-8", errors="replace")) \
            or version_from_filename(f.name)
        if v:
            known.add(v)

    old_hits = []    # 硬编码了**旧**版本号
    cur_hits = []    # 硬编码了**当前**版本号（重复定义，建议引用 gui_config）

    for name in VERSION_SCAN_FILES:
        p = ROOT / name
        if not p.is_file():
            continue
        for lineno, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            # 只看字符串字面量：注释里的历史版本号、算式里的 1.1 都不算硬编码
            for lit in _LITERAL_RE.finditer(line):
                content = lit.group(0)[1:-1]
                found = set()
                m = _EXACT_VER_RE.fullmatch(content)
                if m:
                    found.add(m.group(1))
                for m in _PREFIXED_VER_RE.finditer(content):
                    found.add(m.group(1))
                for v in found:
                    if v not in known:
                        continue
                    rec = "{}:{}  {}".format(name, lineno, line.strip()[:100])
                    if parse_version_tuple(v) and parse_version_tuple(version) \
                            and parse_version_tuple(v) != parse_version_tuple(version):
                        if rec not in old_hits:
                            old_hits.append(rec)
                    elif rec not in cur_hits:
                        cur_hits.append(rec)

    if old_hits:
        add("fail", "硬编码版本号残留",
            "发现硬编码的**旧**版本号（应改为引用 gui_config.APP_VERSION）：\n        "
            + "\n        ".join(old_hits))
    elif cur_hits:
        add("warn", "硬编码版本号残留",
            "发现硬编码的当前版本号（能跑但属于重复定义，建议引用 gui_config.APP_VERSION）：\n        "
            + "\n        ".join(cur_hits))
    else:
        add("ok", "硬编码版本号残留",
            "gui_ui.py / start_gui.py / launch_hidden.py / entry_gui.py 中未发现硬编码版本号")


# ================================================================ 主流程
def main():
    _p("=" * 70)
    _p("  光谱可视化分析工具 —— 版本一致性检查（只读，不修改任何文件）")
    _p("  检查目录：{}".format(ROOT))
    _p("=" * 70)
    _p()

    version, _date = check_read_config()
    if version:
        check_changelog_exists(version)
        check_higher_changelog(version)
        check_splash_version(version)
        check_exe_freshness()
        check_plot_modules()
        check_hidden_imports()
        check_mac_build_hidden_imports()
        check_mac_hashes(parse_sync_manifest())
        check_mac_copy_version(version)
        check_hardcoded_versions(version)

    for level, title, detail in results:
        icon = {"ok": _OK, "warn": _WARN, "fail": _FAIL}[level]
        _p("{} {}".format(icon, title))
        if detail:
            for line in str(detail).split("\n"):
                _p("    " + line)
        _p()

    n_ok = sum(1 for r in results if r[0] == "ok")
    n_warn = sum(1 for r in results if r[0] == "warn")
    n_fail = sum(1 for r in results if r[0] == "fail")

    _p("=" * 70)
    _p("  总结：{} 通过  {} 警告  {} 失败   （共 {} 项）".format(n_ok, n_warn, n_fail, len(results)))
    if n_fail:
        _p("  {} 存在必须修复的问题，请按上方 ❌ 项处理后再打包。".format(_FAIL))
    elif n_warn:
        _p("  {} 没有致命问题，但有警告项，建议打包前处理。".format(_WARN))
    else:
        _p("  {} 全部检查通过：版本号、更新日志、splash 元数据、exe 新鲜度、"
           "打包脚本 hidden-import、mac 副本 SHA256 均一致。".format(_OK))
    _p("=" * 70)

    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
