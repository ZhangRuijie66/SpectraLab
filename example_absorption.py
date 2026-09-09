#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
吸收光谱分析示例脚本
演示如何使用 plot_absorption 模块处理吸收光谱数据
"""

import sys
from pathlib import Path
import numpy as np
import plot_absorption

def main():
    # 设置数据目录 - 使用绝对路径
    data_dir = Path("D:/北大/QLS Lab/SPC/1O2+luminol/谱图/光谱/20260826")
    output_dir = Path("D:/北大/QLS Lab/SPC/1O2+luminol/谱图/光谱/20260826/plots")
    
    # 支持通配符选择文件
    files = [
        data_dir / "20260826RB.csv",
        data_dir / "20260826Ce6.csv", 
        data_dir / "20260826RBL8i.csv"
    ]
    
    print("=== 吸收光谱分析示例 ===")
    print(f"数据目录: {data_dir}")
    print(f"输出目录: {output_dir}")
    print(f"处理文件: {[f.name for f in files]}")
    print()
    
    # 步骤1: 加载光谱数据
    print("1. 加载光谱数据...")
    datasets = plot_absorption.load_absorption_spectra(files, verbose=True)
    print()
    
    # 步骤2: 分析每个样品的吸收峰
    print("2. 分析吸收峰...")
    for i, data in enumerate(datasets):
        print(f"\n样品 {i+1}: {data['label']}")
        peaks = plot_absorption.find_absorption_peaks(
            data, 
            peak_range=(200, 800),  # 分析范围 200-800 nm
            min_height=0.1,         # 最小峰高
            min_distance=20,        # 最小峰间距
            min_prominence=0.05     # 最小峰突出度
        )
        print(f"   发现 {peaks['num_peaks']} 个吸收峰:")
        for j, (wl, intensity) in enumerate(peaks['all_peaks'][:5]):  # 只显示前5个
            print(f"     峰 {j+1}: {wl:.1f} nm, 强度: {intensity:.3f}")
    
    print()
    
    # 步骤3: 绘制单独的吸收光谱图
    print("3. 绘制单独吸收光谱图...")
    individual_files = plot_absorption.plot_single_absorption(
        datasets,
        save_dir=output_dir,
        xlim=(200, 800),         # x轴范围
        ylim=(0, 5),             # y轴范围
        annotate_peaks=True,     # 标注峰
        smooth=True,             # 平滑曲线
        smooth_factor=2,        # 平滑倍数
        title="吸收光谱",        # 统一标题
        show=False               # 不显示，直接保存
    )
    print(f"   已保存 {len(individual_files)} 个单独图")
    
    print()
    
    # 步骤4: 绘制合并的吸收光谱图
    print("4. 绘制合并吸收光谱图...")
    combined_file = plot_absorption.plot_combined_absorption(
        datasets,
        save_dir=output_dir,
        normalize=False,         # 不归一化
        xlim=(200, 800),        # x轴范围
        ylim=(0, 5),            # y轴范围
        annotate_peaks=True,    # 标注峰
        smooth=True,            # 平滑曲线
        title="吸收光谱对比",
        xlabel="波长 (nm)",
        ylabel="吸收值",
        colors=['blue', 'red', 'green']   # 自定义颜色
    )
    print(f"   已保存合并图: {combined_file}")
    
    print()
    
    # 步骤5: 绘制归一化的合并图
    print("5. 绘制归一化的吸收光谱图...")
    normalized_file = plot_absorption.plot_combined_absorption(
        datasets,
        save_dir=output_dir,
        normalize=True,         # 归一化
        xlim=(200, 800),        # x轴范围
        annotate_peaks=False,   # 不标注峰（归一化后峰值位置相同）
        smooth=True,            # 平滑曲线
        title="归一化吸收光谱对比",
        xlabel="波长 (nm)",
        ylabel="归一化吸收值"
    )
    print(f"   已保存归一化合并图: {normalized_file}")
    
    print()
    print("=== 分析完成 ===")
    print(f"所有图像已保存到: {output_dir}")
    
    # 演示其他分析功能
    print("\n=== 演示高级分析功能 ===")
    
    # 计算摩尔吸光系数（假设浓度为 1 μM = 1e-6 M）
    for data in datasets:
        data['concentration'] = 1e-6  # 假设浓度
        
        coeff_data = plot_absorption.calculate_absorption_coefficient(
            data, 
            path_length=1.0  # 光程 1 cm
        )
        max_coeff = max(coeff_data['absorption_coefficient'])
        max_wl = coeff_data['wavelengths'][np.argmax(coeff_data['absorption_coefficient'])]
        print(f"{data['label']}: 最大摩尔吸光系数 epsilon = {max_coeff:.0f} L mol^-1 cm^-1 @ {max_wl:.1f} nm")

if __name__ == "__main__":
    main()