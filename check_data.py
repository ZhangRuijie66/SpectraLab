import pandas as pd
from pathlib import Path
import re

def parse_rf6000_csv(filepath):
    encodings = ['utf-8', 'gbk', 'latin-1']
    lines = None
    for enc in encodings:
        try:
            with open(filepath, 'r', encoding=enc) as f:
                lines = f.readlines()
            break
        except (UnicodeDecodeError, FileNotFoundError):
            continue
    if lines is None:
        raise ValueError(f'无法读取文件: {filepath}')

    sample_name = ''
    ex_wl_val = None
    spectrum_type = ''

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        parts = [p.strip() for p in stripped.split(',')]

        if 'Sample Name' in parts:
            idx = next((i for i, p in enumerate(parts) if 'Sample Name' in p), -1)
            if idx >= 0 and idx + 1 < len(parts):
                val = parts[idx + 1]
                if val and val.lower() != 'nan':
                    sample_name = val

        for p in parts:
            if 'EX Wavelength' in p:
                match = re.search(r'EX\s*Wavelength[:\s]*([\d.]+)', p)
                if match:
                    ex_wl_val = float(match.group(1))
            if ex_wl_val is None and len(parts) > 1:
                for j, p2 in enumerate(parts):
                    if 'EX Wavelength' in p2 and j + 1 < len(parts):
                        match = re.search(r'([\d.]+)', parts[j + 1])
                        if match:
                            ex_wl_val = float(match.group(1))

        for p in parts:
            if 'Spectrum Type' in p:
                idx = next((i for i, p2 in enumerate(parts) if 'Spectrum Type' in p2), -1)
                if idx >= 0 and idx + 1 < len(parts):
                    val = parts[idx + 1]
                    if val and val.lower() != 'nan':
                        spectrum_type = val

    data_start = None
    for i, line in enumerate(lines):
        if re.search(r'Wavelength\s*nm', line, re.IGNORECASE):
            data_start = i + 1
            break

    if data_start is None:
        raise ValueError('未找到 Wavelength nm. 数据表头行')

    wl_list = []
    int_list = []
    for line in lines[data_start:]:
        stripped = line.strip()
        if not stripped:
            continue
        parts = stripped.split(',')
        if len(parts) < 2:
            continue
        try:
            wl_val = float(parts[0].strip())
            int_val = float(parts[1].strip())
            wl_list.append(wl_val)
            int_list.append(int_val)
        except ValueError:
            continue

    return {
        'sample_name': sample_name,
        'ex_wl': ex_wl_val,
        'spectrum_type': spectrum_type,
        'n_points': len(wl_list),
    }

data_dir = Path('.')
for f in sorted(data_dir.glob('Zn-*.csv')):
    try:
        info = parse_rf6000_csv(str(f))
        print(f'{f.name}: sample={info["sample_name"]}, EX={info["ex_wl"]}, type={info["spectrum_type"]}, points={info["n_points"]}')
    except Exception as e:
        print(f'{f.name}: ERROR - {e}')
