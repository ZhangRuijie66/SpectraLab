#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试脚本：验证吸收光谱模块改进是否正常
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from plot_absorption import load_absorption_spectra, plot_single_absorption, plot_combined_absorption
import matplotlib
matplotlib.use('Agg')  # 禁用显示

def test_combined_plot():
    """测试合并图的缩放问题"""
    print("=== 测试合并图缩放改进 ===")
    
    # 测试数据路径
    data_dir = r"D:\北大\QLS Lab\SPC\1O2+luminol\谱图\光谱\20260826"
    
    # 加载数据
    print("加载吸收光谱数据...")
    datasets = load_absorption_spectra(data_dir)
    print(f"加载了 {len(datasets)} 个光谱数据集")
    
    # 创建输出目录
    output_dir = os.path.join(data_dir, "plots")
    os.makedirs(output_dir, exist_ok=True)
    
    # 测试不同的合并图参数
    test_cases = [
        {"normalize": True, "title": "归一化合并图"},
        {"normalize": False, "title": "原始值合并图"},
        {"normalize": True, "ylimit": "auto", "title": "自动Y轴范围"}
    ]
    
    for i, case in enumerate(test_cases):
        print(f"\n测试案例 {i+1}: {case['title']}")
        
        plot_combined_absorption(
            datasets,
            save_dir=output_dir,
            show=False,  # 禁用显示
            dpi=100,     # 使用较低DPI以加快测试
            normalize=case.get("normalize", False),
            ylim=case.get("ylimit"),
            title=case["title"]
        )
        
        # 检查文件是否生成
        files = os.listdir(output_dir)
        combined_files = [f for f in files if "combined" in f and f.endswith(".png")]
        if combined_files:
            print(f"成功生成: {combined_files[0]}")
        else:
            print("警告: 未找到合并图文件")

def test_single_plot_scaling():
    """测试单图缩放"""
    print("\n=== 测试单图缩放改进 ===")
    
    # 加载数据
    data_dir = r"D:\北大\QLS Lab\SPC\1O2+luminol\谱图\光谱\20260826"
    datasets = load_absorption_spectra(data_dir)
    
    # 创建输出目录
    output_dir = os.path.join(data_dir, "plots")
    os.makedirs(output_dir, exist_ok=True)
    
    # 选择第一个数据集测试
    if datasets:
        print("测试数据集:", datasets[0]['label'])
        
        # 测试不同Y轴范围设置
        test_ranges = [
            None,  # 自动范围
            (0, 5),  # 固定范围
            (0.1, 10)  # 较大范围
        ]
        
        for i, yrange in enumerate(test_ranges):
            print(f"\n测试Y轴范围 {i+1}: {yrange}")
            
            plot_single_absorption(
                datasets[0],
                save_dir=output_dir,
                show=False,
                dpi=100,
                ylim=yrange,
                title=f"测试 {i+1} - {'自动' if yrange is None else f'范围: {yrange}'}"
            )
            
            # 检查文件
            files = os.listdir(output_dir)
            label = datasets[0]['label']
            single_files = [f for f in files if label in f and f.endswith(".png")]
            if single_files:
                print(f"成功生成: {single_files[0]}")
            else:
                print("警告: 未找到单图文件")

if __name__ == "__main__":
    print("开始测试吸收光谱模块改进...")
    
    test_combined_plot()
    test_single_plot_scaling()
    
    print("\n测试完成！请检查 plots 目录中的图像文件。")