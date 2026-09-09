"""
测试文件加载功能
"""

import sys
sys.path.insert(0, r'D:\北大\QLS Lab\SPC\1O2+luminol\谱图\光谱\画图')

from pathlib import Path
from plot_absorption import load_absorption_spectra

print("=" * 60)
print("  测试文件加载功能")
print("=" * 60)
print()

# 测试文件
test_file = Path(r'D:\北大\QLS Lab\SPC\1O2+luminol\谱图\光谱\20260826\20260826RB.csv')

print(f"测试文件: {test_file}")
print(f"文件存在: {test_file.exists()}")
print()

if not test_file.exists():
    print("错误：测试文件不存在！")
    sys.exit(1)

print("尝试加载文件...")
try:
    data = load_absorption_spectra(test_file, skip_metadata=True, verbose=True)
    print()
    print(f"返回类型: {type(data)}")
    print(f"返回长度: {len(data) if isinstance(data, (list, tuple)) else 'N/A'}")
    print()

    if isinstance(data, list) and len(data) > 0:
        first = data[0]
        print(f"第一个元素类型: {type(first)}")
        print(f"第一个元素键: {first.keys() if isinstance(first, dict) else 'N/A'}")
        print()

        if isinstance(first, dict):
            if 'wavelength' in first:
                print(f"wavelength 类型: {type(first['wavelength'])}")
                print(f"wavelength 形状: {first['wavelength'].shape if hasattr(first['wavelength'], 'shape') else len(first['wavelength'])}")
            if 'absorption' in first:
                print(f"absorption 类型: {type(first['absorption'])}")
                print(f"absorption 形状: {first['absorption'].shape if hasattr(first['absorption'], 'shape') else len(first['absorption'])}")

    print()
    print("=" * 60)
    print("测试完成！")
    print("=" * 60)

except Exception as e:
    print(f"错误: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)