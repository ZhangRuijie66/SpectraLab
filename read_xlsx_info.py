# -*- coding: utf-8 -*-
"""
说明.xlsx 信息读取模块（通用版）
================================
自动读取数据文件夹中的 ``说明.xlsx``，自动识别「编号」列与其余信息列，
把每个样品的信息结构化，供可视化程序把样品信息写入曲线图例等。

说明.xlsx 常见结构（首行为列名）::

    编号  RB浓度  L8i浓度  备注
    1     0      0       参比
    2    20    200       样品

列名可为：编号 / 序号 / No. / ZnPcS4浓度 / CPC浓度 / RB浓度 / L8i浓度 /
Ce6浓度 / 备注 / 是否加入PVP 等。本模块自动识别编号列，其余非空列一律作为信息列。

设计原则
--------
* 只依赖 ``pandas``（项目绘图模块已依赖），不依赖 PyQt。
* 编号尽量转成 ``int``，便于与文件名中的数字比对。
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
"""

import re
from pathlib import Path
from typing import Dict, List, Optional, Union

import pandas as pd

# 候选的「编号」列名（按优先级自上而下；此外也会做包含匹配）
_NUM_COL_NAMES = (
    '编号', '序号', '样号', '样本编号', '样品编号', '编号列',
    'No', 'NO', 'no', 'No.', 'Number', 'num', 'index', 'ID',
)


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
    """把单元格值清洗成适合展示的形式：NaN -> 空串；浮点整数值 -> int；其余原样。"""
    try:
        if pd.isna(v):
            return ''
    except (TypeError, ValueError):
        pass
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if isinstance(v, str):
        s = v.strip()
        if s.lower() == 'nan':
            return ''
        return s
    return v


class XlsxInfo:
    """说明.xlsx 的结构化信息。

    属性
    ----
    info : dict[int, dict[str, object]]
        编号 -> {信息列名: 值}，已去除空值列与编号列本身。
    numbers : list[int]
        按出现顺序（去重）记录的编号列表。
    columns : list[str]
        除编号列之外的信息列名。
    path : Path
        实际读取的 xlsx 文件路径。
    """

    def __init__(self, info: Dict[int, Dict[str, object]], numbers: List[int],
                 columns: List[str], path: Path):
        self.info = info
        self.numbers = numbers
        self.columns = columns
        self.path = path

    def __len__(self):
        return len(self.numbers)

    def __bool__(self):
        return bool(self.numbers)

    def label_for(self, number: int) -> str:
        """返回某编号的说明字符串，如 ``'RB浓度=20, L8i浓度=200, 备注=样品'``。"""
        return format_info(self.info.get(int(number), {}))


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

    info: Dict[int, Dict[str, object]] = {}
    numbers: List[int] = []
    seen = set()
    for _, r in df.iterrows():
        raw_num = r[num_col]
        try:
            num = int(raw_num)
        except (TypeError, ValueError):
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


def match_number(name: Union[str, Path], numbers) -> Optional[int]:
    """从文件名/文本中尽量找出对应的编号，返回 int；找不到返回 None。

    匹配策略（按优先级）：
    1. 整串就是编号（纯数字）且在该批次编号集合中。
    2. 把文件名按非字母/数字/汉字切分，取「编号集合中出现的整数」的第一个。
       —— ``Zn-10-3.csv`` 会切出 ``['Zn','10','3']``，命中 10（重复测量的小尾数被忽略）。
    3. 退化：编号作为子串出现在文件名中（如 ``20260827-1.csv``），取最小命中编号。
    4. 均无命中 -> None（由调用方回退到原标签）。
    """
    nums = []
    for n in numbers:
        try:
            nums.append(int(n))
        except (TypeError, ValueError):
            continue
    num_set = set(nums)
    if not num_set:
        return None

    # 统一用文件名去后缀
    try:
        p = Path(str(name))
        s = p.stem if p.suffix else str(name)
    except Exception:
        s = str(name)

    stripped = s.strip()
    # 1) 整串是数字
    if stripped.isdigit():
        v = int(stripped)
        return v if v in num_set else None

    # 2) 切分 token，优先命中集合中的整数
    parts = re_split(s)
    for tok in parts:
        if tok.isdigit():
            v = int(tok)
            if v in num_set:
                return v

    # 3) 退化整数字串匹配：编号必须作为「独立整数」出现（前后不被数字包夹），
    #    避免 ``Zn-10`` 误命中子串 ``1``。取最小命中编号，通常最保守。
    for n in sorted(num_set):
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


def build_enriched_label(base_label: str, info: XlsxInfo, number: int) -> str:
    """用说明信息增强基础标签。

    - 若 ``base_label`` 本身就是一个数字且等于 ``number``，直接用说明字符串；
    - 否则以 ``基础标签（说明信息）`` 形式返回。
    """
    info_str = info.label_for(number)
    if not info_str:
        return base_label
    # 基础标签就是编号
    try:
        if str(base_label).strip().isdigit() and int(str(base_label).strip()) == number:
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
