# -*- coding: utf-8 -*-
"""
说明.xlsx 信息读取模块（通用版）+ 多列光谱 xlsx 数据表解析
==========================================================
本模块负责两件事：

1. **说明.xlsx 信息表**——自动读取数据文件夹中的 ``说明.xlsx``，自动识别「编号」列与
   其余信息列，把每个样品的信息结构化，供可视化程序把样品信息写入曲线图例等。
2. **多列光谱 xlsx 数据表**（v4.41）——仪器的 Excel 多光谱导出：一列波长 + 若干样品列，
   按列拆成多条光谱（``parse_spectrum_xlsx`` / ``clean_xlsx_column_label``）。
   吸收模式用它读 20261010.xlsx 这类文件。

说明.xlsx 常见结构（首行为列名）::

    编号  RB浓度  L8i浓度  备注
    1     0      0       参比
    2    20    200       样品

「编号」列**既可以是整数，也可以是文本码**（v4.41）::

    编号  RB浓度  Ce6浓度  L8i浓度
    R1   50             1000
    S1           50      1000

文本码直接对应文件名里的样品名（``R1-2.csv`` -> ``R1``、``S1-1.csv`` -> ``S1``）。
v4.41 之前只认整数：整列写成 ``R1`` / ``S1`` 时每一行都会被丢掉，
``load_xlsx_info`` 直接返回 ``None``——界面上就表现为「有 说明.xlsx，但软件说
未找到 / 读取失败，图例用文件名」（20261010 批次踩到）。

列名可为：编号 / 序号 / No. / ZnPcS4浓度 / CPC浓度 / RB浓度 / L8i浓度 /
Ce6浓度 / 备注 / 是否加入PVP 等。本模块自动识别编号列，其余非空列一律作为信息列。

设计原则
--------
* 只依赖 ``pandas``（项目绘图模块已依赖），不依赖 PyQt。
* 编号的内部表示跟着单元格走：整数编号是 ``int``，文本码是 ``str``
  （``XlsxInfo.numbers`` 的元素与 ``match_number`` 的返回值都是这个口径）。
* 提供 ``match_number`` 做「文件名 -> 编号」的容错匹配，匹配不到时由调用方回退到原标签。

示例
----
::

    from read_xlsx_info import load_xlsx_info, match_number, format_info

    info = load_xlsx_info(r'...\\20260827')        # 自动定位 说明.xlsx
    if info is not None:
        print('样品编号:', info.numbers)            # [1, 2]
        num = match_number('20260827-1.csv', info.numbers)   # -> 1
        print(format_info(info.info[num]))          # 'RB浓度=20, L8i浓度=200, 备注=样品'

    # 文本码批次（如 20261010）：numbers = ['R1', 'R2', 'R3', 'S1', 'S2', 'S3', 'S4']
    num = match_number('S1-2.csv', info.numbers)             # -> 'S1'
"""

import re
from pathlib import Path
from typing import Dict, List, Optional, Union

import numpy as np
import pandas as pd

# 候选的「编号」列名（按优先级自上而下；此外也会做包含匹配）
_NUM_COL_NAMES = (
    '编号', '序号', '样号', '样本编号', '样品编号', '编号列',
    'No', 'NO', 'no', 'No.', 'Number', 'num', 'index', 'ID',
)

# 文本形式的「空值」——说明.xlsx 里常手填这些表示"该变量没有值"（v4.37）。
# 只收无歧义的写法；像「无」「未测」这类可能是有意义的备注内容，不当空值处理。
_NULL_TOKENS = {
    '', 'null', 'none', 'nil', 'nan', 'n/a', '#n/a', '#value!',
    'na', 'nd', '-', '--', '---', '—', '–',
}


def _is_number_col(name: str) -> bool:
    """判断某列名是否像「编号」列。"""
    s = str(name).strip()
    if not s:
        return False
    # 完全匹配候选名
    for cand in _NUM_COL_NAMES:
        if s == cand:
            return True
    # 包含「编号」即可（注意排除「样品编号」之外的误判），常见如「样编号」「编号(照片)」
    if '编号' in s or '序号' in s:
        return True
    # 常见英文编号列
    if s.lower() in {'no', 'no.', 'number', 'index', 'id'}:
        return True
    return False


def _clean_value(v):
    """把单元格值清洗成适合展示的形式：空值 -> 空串；浮点整数值 -> int；其余原样。

    v4.37：除 Excel 真正的空单元格（读进来是 NaN）之外，**文本形式的空值**也
    一律当空处理——说明.xlsx 里常有人手填 ``null`` / ``NULL`` / ``None`` /
    ``N/A`` / ``#N/A`` / ``-`` / ``—`` 表示"这个变量没有值"，它们以前会被原样
    当成有效值显示成 ``RB浓度=null``，现在统一按空值丢弃（不参与展示、不参与
    数据比较的取点）。
    """
    try:
        if pd.isna(v):
            return ''
    except (TypeError, ValueError):
        pass
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if isinstance(v, str):
        s = v.strip()
        if s.lower() in _NULL_TOKENS:
            return ''
        return s
    return v


def _norm_code(v):
    """把「编号」单元格 / 文件名片段规范化成匹配用的键（v4.41）。

    - 空单元格、``null`` / ``N/A`` / ``-`` 等文本空值 -> ``None``（该行不算样品）；
    - 整数（含 numpy 整数）-> ``int``；
    - 纯数字文本 ``'1'`` -> ``int``（与整数 1 视为同一个编号）；
    - 其余文本 -> 去掉首尾空白并**统一大写**，如 ``'r1'`` / ``'R1 '`` -> ``'R1'``。

    返回 ``None`` 表示"不是有效编号"。
    """
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(v, bool):
        return None
    if isinstance(v, str):
        s = v.strip()
        if not s or s.lower() in _NULL_TOKENS:
            return None
        if re.fullmatch(r'[+-]?\d+', s):
            return int(s)
        return s.upper()
    # numpy 整数不继承 int（Windows 上 np.int64 尤其如此），用 duck typing 判断
    try:
        if int(v) == v:
            return int(v)
    except (TypeError, ValueError, OverflowError):
        # OverflowError：inf / 超大浮点（int(inf) 会抛）
        pass
    s = str(v).strip()
    return s.upper() or None


def _unique_codes(numbers):
    """把一批编号规范化、去重并保持原顺序（``match_number`` 的内部入口）。"""
    out: List[Union[int, str]] = []
    seen = set()
    if numbers is None:
        return out
    for c in numbers:
        k = _norm_code(c)
        if k is None or k in seen:
            continue
        seen.add(k)
        out.append(k)
    return out


class XlsxInfo:
    """说明.xlsx 的结构化信息。

    属性
    ----
    info : dict[int | str, dict[str, object]]
        编号 -> {信息列名: 值}，已去除空值列与编号列本身。
        键是**整数**（编号列写 1/2/…）或**文本码**（编号列写 R1/S1/…）。
    numbers : list[int | str]
        按出现顺序（去重）记录的编号列表。
    columns : list[str]
        除编号列之外的信息列名。
    path : Path
        实际读取的 xlsx 文件路径。
    """

    def __init__(self, info: Dict[Union[int, str], Dict[str, object]],
                 numbers: List[Union[int, str]],
                 columns: List[str], path: Path):
        self.info = info
        self.numbers = numbers
        self.columns = columns
        self.path = path

    def __len__(self):
        return len(self.numbers)

    def __bool__(self):
        return bool(self.numbers)

    def _key(self, number):
        """把外部编号规范化成 ``info`` 的字典键；找不到时返回规范化后的原值。

        v4.41：编号不再强制 ``int``——以前这里写的是 ``int(number)``，
        编号列是 ``R1`` / ``S1`` 这类文本码时 ``int('R1')`` 直接抛 ValueError，
        调用方（图例、数据比较）拿不到信息，界面上就等于"没有说明"。
        """
        k = _norm_code(number)
        if k is None:
            return None
        if k in self.info:
            return k
        if isinstance(k, str):
            for key in self.info:
                if isinstance(key, str) and key.upper() == k:
                    return key
        return k

    def entry_for(self, number) -> Dict[str, object]:
        """取某编号的整行信息字典；编号对不上时返回空字典（不抛异常）。"""
        return self.info.get(self._key(number), {})

    def label_for(self, number) -> str:
        """返回某编号的说明字符串，如 ``'RB浓度=20, L8i浓度=200, 备注=样品'``。"""
        return format_info(self.entry_for(number))

    def value_for(self, number, column: str):
        """取某编号在某列的值；该样品缺这一列（空单元格 / null 文本）时返回 None。

        「数据比较」模块靠它把"没有值"和"值为 0"区分开——返回 None 的样品
        不进入点线图（v4.37）。
        """
        entry = self.entry_for(number)
        val = _clean_value(entry.get(column))
        return None if val == '' else val

    def numeric_columns(self) -> List[str]:
        """可作为横轴 / 分组变量的**数值列**（至少有一个样品给出可转 float 的值）。

        空值列、纯文本列（如「备注」）都不会出现在这里。
        """
        cols = []
        for col in self.columns:
            for entry in self.info.values():
                val = _clean_value(entry.get(col))
                if val == '':
                    continue
                try:
                    float(val)
                except (TypeError, ValueError):
                    continue
                cols.append(col)
                break
        return cols


def load_xlsx_info(folder_path: Union[str, Path], xlsx_name: Optional[str] = None) -> Optional[XlsxInfo]:
    """读取文件夹中的说明.xlsx，返回 XlsxInfo；找不到或读取失败时返回 None。

    参数
    ----
    folder_path : str | Path
        数据文件夹路径。
    xlsx_name : str | None
        指定要读的文件名。为 None 时自动查找：优先文件名含「说明」的 .xlsx，
        否则取该文件夹下第一个 .xlsx。
    """
    folder = Path(folder_path)
    if not folder.is_dir():
        return None

    xlsx_files = list(folder.glob('*.xlsx'))
    if not xlsx_files:
        return None

    if xlsx_name:
        target = folder / xlsx_name
        if not target.exists():
            return None
        path = target
    else:
        # 优先找文件名带「说明」的
        prefers = [f for f in xlsx_files if '说明' in f.stem]
        path = prefers[0] if prefers else xlsx_files[0]

    try:
        df = pd.read_excel(path, header=0)
    except Exception as e:
        print(f'[read_xlsx_info] 读取 {path.name} 失败: {e}')
        return None

    if df.empty:
        return None

    # --- 识别编号列 ---
    num_col = None
    for col in df.columns:
        if _is_number_col(col):
            num_col = col
            break
    if num_col is None:
        # 兜底：用第一列作为编号列
        num_col = df.columns[0]

    # --- 信息列（除去编号列）+ 去空列 ---
    info_cols = []
    for col in df.columns:
        if col == num_col:
            continue
        if df[col].notna().any():
            info_cols.append(col)

    info: Dict[Union[int, str], Dict[str, object]] = {}
    numbers: List[Union[int, str]] = []
    seen = set()
    for _, r in df.iterrows():
        # v4.41：编号可以是整数，也可以是文本码（R1 / S1 / Zn-10…）
        num = _norm_code(r[num_col])
        if num is None:
            continue
        if num in seen:
            # 重复编号：保留第一次，再次出现时跳过
            continue
        seen.add(num)
        entry: Dict[str, object] = {}
        for col in info_cols:
            val = _clean_value(r[col])
            if val == '':
                continue
            entry[col] = val
        info[num] = entry
        numbers.append(num)

    if not numbers:
        return None
    return XlsxInfo(info=info, numbers=numbers, columns=[c for c in info_cols], path=path)


def match_number(name: Union[str, Path], numbers) -> Optional[Union[int, str]]:
    """从文件名/文本中尽量找出对应的编号，返回编号本身（``int`` 或文本码）；找不到返回 None。

    编号既可能是整数（``1`` / ``2``），也可能是文本码（``R1`` / ``S1`` / ``Zn-10``），
    后者直接对应文件名里的样品名。

    匹配策略（按优先级）：
    1. 整串就是编号（``'R1'`` / ``'1'``）且在该批次编号集合中。
    2. 把文件名按非字母/数字/汉字切分，取「编号集合中出现的编号」的第一个——
       ``R1-2.csv`` 切出 ``['R1','2']``，命中 ``R1``；``Zn-10-3.csv`` 切出
       ``['Zn','10','3']``，命中 10（重复测量的小尾数被忽略）。
    3. 退化：**整数**编号作为「独立整数」出现在文件名中（如 ``20260827-1.csv``），
       取最小命中编号。文本码不做子串匹配——``R1`` 不该命中 ``R10``。
    4. 均无命中 -> None（由调用方回退到原标签）。
    """
    codes = _unique_codes(numbers)
    if not codes:
        return None
    code_set = set(codes)
    int_codes = {c for c in codes if isinstance(c, int)}
    str_codes = {c: c for c in codes if isinstance(c, str)}   # 已大写，可直接查

    # 统一用文件名去后缀
    try:
        p = Path(str(name))
        s = p.stem if p.suffix else str(name)
    except Exception:
        s = str(name)

    stripped = s.strip()
    # 1) 整串就是编号
    whole = _norm_code(stripped)
    if whole is not None and whole in code_set:
        return whole

    # 2) 切分 token，按出现顺序命中集合中的编号（整数 / 文本码都认）
    parts = re_split(s)
    for tok in parts:
        if tok.isdigit():
            v = int(tok)
            if v in int_codes:
                return v
        hit = str_codes.get(tok.upper())
        if hit is not None:
            return hit

    # 3) 退化整数字串匹配：整数编号必须作为「独立整数」出现（前后不被数字包夹），
    #    避免 ``Zn-10`` 误命中子串 ``1``。取最小命中编号，通常最保守。
    for n in sorted(int_codes):
        if re.search(r'(?<![0-9])' + str(n) + r'(?![0-9])', s):
            return int(n)

    return None


def re_split(s: str) -> List[str]:
    """把字符串按非「数字/字母/汉字」切分，保留数字/字母/汉字片段。"""
    out = []
    cur = []
    for ch in s:
        if ch.isalnum() or '\u4e00' <= ch <= '\u9fff':
            cur.append(ch)
        else:
            if cur:
                out.append(''.join(cur))
                cur = []
    if cur:
        out.append(''.join(cur))
    return out


def format_info(entry: Dict[str, object]) -> str:
    """把 {信息列名: 值} 字典格式化为展示字符串，如 ``'RB浓度=20, L8i浓度=200'``。"""
    if not entry:
        return ''
    parts = []
    for col in entry:
        val = entry[col]
        if val == '' or val is None:
            continue
        parts.append(f'{col}={val}')
    return ', '.join(parts)


def build_enriched_label(base_label: str, info: XlsxInfo, number) -> str:
    """用说明信息增强基础标签。

    - 若 ``base_label`` 本身就是编号（``'1'`` / ``'R1'``），直接用说明字符串；
    - 否则以 ``基础标签（说明信息）`` 形式返回。
    """
    info_str = info.label_for(number)
    if not info_str:
        return base_label
    # 基础标签就是编号（v4.41：不再要求是纯数字，文本码同样成立）
    try:
        key = _norm_code(number)
        if key is not None and _norm_code(str(base_label).strip()) == key:
            return f'#{number} {info_str}'
    except Exception:
        pass
    # 说明已包含基础标签（或反向），避免重复
    if info_str in str(base_label) or str(base_label) in info_str:
        return str(base_label)
    return f'{base_label}（{info_str}）'


def enrich_label_from_name(base_label: str, name: Union[str, Path], info: XlsxInfo,
                           numbers=None) -> str:
    """一步完成：用文件名/文本匹配编号，再用说明信息增强标签。

    匹配不到编号时原样返回 ``base_label``。
    """
    if info is None or not info.numbers:
        return base_label
    nums = numbers if numbers is not None else info.numbers
    num = match_number(name, nums)
    if num is None:
        return base_label
    return build_enriched_label(base_label, info, num)


# ============================================================
# 多列光谱 xlsx 数据表（v4.41）
# ============================================================
# 列名里的仪器后缀：'20261010R1 - RawData' / 'S1 - CorrectionData'。
# 短横线**后面要求有空白**——否则 'Sample-absorption' 这种正常样品名会被切掉。
_COL_SUFFIX_RE = re.compile(
    r'\s*[-–—]\s+(raw\s*data|correction\s*data|emission|excitation|absorption|'
    r'spectrum|rawdata|correctiondata)\s*$', re.IGNORECASE)
# 列名开头的导出日期：'20261010R1' -> 'R1'
_DATE_PREFIX_RE = re.compile(r'^\d{8}[\s_\-]*')
# 波长列表头：'波长(nm)' / 'Wavelength nm.' / 'Wavelength (nm)' / 'wl'
_WL_HEAD_RE = re.compile(r'波长|wavelength|(^|[^a-z])wl([^a-z]|$)|nm\b', re.IGNORECASE)


def clean_xlsx_column_label(raw) -> str:
    """把多列光谱 xlsx 的表头列名清成样品名（v4.41）。

    ``'20261010R1 - RawData'`` -> ``'R1'``、``'S1 - CorrectionData'`` -> ``'S1'``。
    清干净之后它既能直接当图例标签，也能被 ``match_number`` 对上说明.xlsx 里的编号
    （否则整串 ``20261010R1`` 一个编号都对不上）。
    """
    s = str(raw).strip()
    if not s:
        return s
    for _ in range(3):          # 后缀可能叠了两层，如 'x - RawData - Correction'
        stripped = _COL_SUFFIX_RE.sub('', s).strip()
        if stripped == s:
            break
        s = stripped
    s = _DATE_PREFIX_RE.sub('', s).strip()
    return s or str(raw).strip()


def parse_spectrum_xlsx(filepath) -> List[Dict[str, object]]:
    """解析「多列光谱 xlsx」：一列波长 + 若干样品列，每列拆成一条光谱（v4.41）。

    典型表头（LabSolutions RF 的 Excel 多光谱导出，20261010.xlsx 即此格式）::

        波长(nm) | 20261010R1 - RawData | 20261010R2 - RawData | ...
        900      | 0.006                | 0.001                | ...
        899.5    | 0.005                | 0.002                | ...

    判定规则（不是这种表就抛 ``ValueError``，由调用方按"跳过"处理）：
    * 表头里**必须有一列**是波长列（列名含 波长 / wavelength / wl / nm）；
      没有就直接拒绝——不猜第一列。这样 ``说明.xlsx``、"序号 + 数值列"的汇总表、
      ``time (ns) + A0 + IRF`` 的多列衰减表都不会被误收；
    * 该列必须是数值轴（≥10 个点）；
    * **只有它右边的列**才当样品列（左边的列一律忽略，如"序号"列），
      每列与波长轴对齐后要有 ≥10 个有效点。

    返回 ``list[dict]``，每个元素::

        {'label': 'R1',            # 列名清洗后的样品名
         'wl':   np.ndarray,       # 波长、**升序**（导出通常是降序）
         'y':    np.ndarray,       # 该列的纵轴读数（吸收值 / 强度，由调用方解释）
         'source': '...xlsx',      # 来源文件
         'column': '20261010R1 - RawData',   # 原始列名
         'format': 'xlsx-multicolumn'}

    本函数不解释纵轴含义——同一个文件既能当吸收光谱读（y = 吸光度），
    也能当发射光谱读（y = 强度）。
    """
    path = Path(filepath)
    try:
        df = pd.read_excel(path, header=0)
    except Exception as e:
        raise ValueError(f"{path.name}: xlsx 读取失败（{type(e).__name__}: {e}）")
    if df.shape[1] < 2:
        raise ValueError(f"{path.name}: 只有 {df.shape[1]} 列，不是多列光谱表")

    cols = [str(c).strip() for c in df.columns]
    num = df.apply(pd.to_numeric, errors='coerce')
    # 波长列必须由**表头**认出来，不猜第一列——否则 说明.xlsx / 汇总表 /
    # 多列衰减表（time (ns) + A0 + IRF）都会被当成光谱表收进来（v4.41 复核发现）。
    wl_idx = next((i for i, c in enumerate(cols) if _WL_HEAD_RE.search(c)), None)
    if wl_idx is None:
        raise ValueError(f"{path.name}: 表头里没有波长列（列名需含 "
                         f"波长 / wavelength / wl / nm），不是多列光谱表"
                         f"（第 1 列是 {cols[0]!r}）")

    if int(num.iloc[:, wl_idx].notna().sum()) < 10:
        raise ValueError(f"{path.name}: 第 {wl_idx + 1} 列（{cols[wl_idx]!r}）"
                         "不是数值波长轴，不是多列光谱表")

    wl_col = num.iloc[:, wl_idx]
    datasets = []
    for i, cname in enumerate(cols):
        if i <= wl_idx:
            # 波长列本身、以及它**左边**的列（如"序号"）都不是样品列
            continue
        sub = pd.DataFrame({'wl': wl_col, 'y': num.iloc[:, i]}).dropna()
        if len(sub) < 10:
            continue                     # 空列 / 备注列 / 单位列
        sub = sub.sort_values('wl')
        y = sub['y'].to_numpy(dtype=float)
        if not np.any(np.isfinite(y)):
            continue
        datasets.append({
            'label': clean_xlsx_column_label(cname) or f'{path.stem}-{i + 1}',
            'wl': sub['wl'].to_numpy(dtype=float),
            'y': y,
            'source': str(path),
            'column': cname,
            'format': 'xlsx-multicolumn',
        })
    if not datasets:
        raise ValueError(f"{path.name}: 没有可用的样品数据列")
    return datasets

