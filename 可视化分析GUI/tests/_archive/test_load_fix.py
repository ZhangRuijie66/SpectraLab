"""
简化版测试 - 只测试文件加载功能
"""

import sys
sys.path.insert(0, r'D:\北大\QLS Lab\SPC\1O2+luminol\谱图\光谱\画图')

from pathlib import Path
from plot_absorption import load_absorption_spectra

print("=" * 60)
print("  测试修复后的文件加载功能")
print("=" * 60)
print()

# 测试文件夹
test_folder = Path(r'D:\北大\QLS Lab\SPC\1O2+luminol\谱图\光谱\20260826')

print(f"测试文件夹: {test_folder}")
print(f"文件夹存在: {test_folder.exists()}")
print()

# 查找所有CSV文件
csv_files = list(test_folder.glob("*.csv"))
print(f"找到 {len(csv_files)} 个CSV文件:")
for f in csv_files:
    print(f"  - {f.name}")
print()

# 测试加载
data_cache = {}
loaded_count = 0

for file_path in csv_files:
    print(f"加载文件: {file_path.name}")
    try:
        data = load_absorption_spectra(file_path, skip_metadata=True, verbose=False)

        if data and len(data) > 0:
            first_data = data[0]
            print(f"  返回数据类型: {type(first_data)}")

            if isinstance(first_data, dict):
                # 检查键名
                has_wl = 'wl' in first_data
                has_wavelength = 'wavelength' in first_data
                has_absorption = 'absorption' in first_data

                print(f"  有'wl'键: {has_wl}")
                print(f"  有'wavelength'键: {has_wavelength}")
                print(f"  有'absorption'键: {has_absorption}")

                # 修复：如果只有'wl'，添加'wavelength'
                if has_wl and has_absorption and not has_wavelength:
                    first_data['wavelength'] = first_data['wl']
                    print(f"  已添加'wavelength'键")

                # 检查修复后的结果
                if 'wavelength' in first_data and 'absorption' in first_data:
                    data_cache[file_path.name] = {
                        'path': file_path,
                        'data': first_data
                    }
                    loaded_count += 1
                    print(f"  [OK] 加载成功")
                else:
                    print(f"  [FAIL] 缺少必要的键")
            else:
                print(f"  [FAIL] 不是字典类型")
        else:
            print(f"  [FAIL] 数据为空")
    except Exception as e:
        print(f"  [ERROR] {e}")

print()
print("=" * 60)
print(f"结果: 成功加载 {loaded_count}/{len(csv_files)} 个文件")
print("=" * 60)

if loaded_count > 0:
    print()
    print("测试通过！修复有效。")
else:
    print()
    print("测试失败！需要进一步调查。")