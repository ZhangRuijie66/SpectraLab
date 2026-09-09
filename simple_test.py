#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简单测试脚本：直接测试吸收光谱模块
"""

import sys
import os
import matplotlib
matplotlib.use('Agg')  # 禁用显示

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from plot_absorption import load_absorption_spectra, plot_combined_absorption

def main():
    print("开始简单测试...")
    
    # 测试数据路径
    data_dir = r"D:\北大\QLS Lab\SPC\1O2+luminol\谱图\光谱\20260826"
    print(f"数据目录: {data_dir}")
    
    # 检查数据文件是否存在
    if os.path.exists(data_dir):
        files = os.listdir(data_dir)
        csv_files = [f for f in files if f.endswith('.csv')]
        print(f"找到CSV文件: {csv_files}")
    else:
        print("错误: 数据目录不存在")
        return
    
    # 尝试加载数据
    try:
        datasets = load_absorption_spectra(data_dir)
        print(f"成功加载 {len(datasets)} 个光谱数据集")
        
        # 打印数据集信息
        for i, data in enumerate(datasets):
            print(f"数据集 {i+1}: {data['label']}")
            print(f"  波长范围: {min(data['wl']):.1f} - {max(data['wl']):.1f} nm")
            print(f"  吸收值范围: {min(data['absorption']):.3f} - {max(data['absorption']):.3f}")
        
        # 创建输出目录
        output_dir = os.path.join(data_dir, "plots")
        os.makedirs(output_dir, exist_ok=True)
        print(f"输出目录: {output_dir}")
        
        # 测试绘图
        if datasets:
            print("\n开始测试合并图绘图...")
            plot_combined_absorption(
                datasets,
                save_dir=output_dir,
                show=False,
                dpi=100,
                normalize=False,
                title="测试合并图"
            )
            
            # 检查是否生成了文件
            if os.path.exists(output_dir):
                files = os.listdir(output_dir)
                png_files = [f for f in files if f.endswith('.png')]
                print(f"生成的PNG文件: {png_files}")
            else:
                print("警告: 输出目录不存在")
        
    except Exception as e:
        print(f"错误: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()