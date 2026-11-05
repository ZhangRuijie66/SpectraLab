"""
测试吸收光谱绘图功能
验证修复：
  1. Y轴比例尺自动优化
  2. 不弹出pyplot窗口
  3. 输出到指定目录
"""

import sys
sys.path.insert(0, r'D:\北大\光谱工具')

from plot_absorption import (
    load_absorption_spectra,
    plot_single_absorption,
    plot_combined_absorption
)
from pathlib import Path

# 测试数据路径
data_files = [
    r'D:\北大\QLS Lab\SPC\1O2+luminol\谱图\光谱\20260826\20260826RB.csv',
    r'D:\北大\QLS Lab\SPC\1O2+luminol\谱图\光谱\20260826\20260826Ce6.csv',
    r'D:\北大\QLS Lab\SPC\1O2+luminol\谱图\光谱\20260826\20260826RBL8i.csv',
]

output_dir = Path(r'D:\北大\QLS Lab\SPC\1O2+luminol\谱图\光谱\20260826\plots_test')
output_dir.mkdir(parents=True, exist_ok=True)

print("测试吸收光谱绘图功能")
print("=" * 70)

# 加载数据
print("\n1. 加载数据...")
datasets = load_absorption_spectra(data_files, verbose=True)
print(f"成功加载 {len(datasets)} 个光谱数据集")

# 绘制单独图
print("\n2. 绘制单独图（不弹出窗口）...")
for data in datasets:
    print(f"  - {data['label']}")
    plot_single_absorption(
        data,
        save_dir=output_dir,
        show=False,  # 不弹出窗口
        dpi=150,
        annotate_peaks=True
    )

# 绘制合并图
print("\n3. 绘制合并图（自动优化Y轴）...")
plot_combined_absorption(
    datasets,
    save_dir=output_dir,
    show=False,  # 不弹出窗口
    dpi=150,
    annotate_peaks=True,
    title="吸收光谱对比（测试Y轴优化）"
)

print("\n" + "=" * 70)
print("测试完成！")
print(f"图片已保存到: {output_dir}")
print("请检查Y轴比例尺是否合适")
