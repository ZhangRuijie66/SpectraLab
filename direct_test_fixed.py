#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
直接测试数据加载和绘图功能 - 修复编码问题
"""

import sys
import os
import matplotlib
matplotlib.use('Agg')  # 禁用显示
import numpy as np
from pathlib import Path
import chardet

def detect_encoding(file_path):
    """检测文件编码"""
    with open(file_path, 'rb') as f:
        raw_data = f.read()
        result = chardet.detect(raw_data)
        return result['encoding']

def load_absorption_spectra_test(data_dir):
    """修改版的数据加载函数，简化测试用"""
    datasets = []
    
    # 获取目录下所有CSV文件
    csv_files = []
    for ext in ['*.csv', '*.CSV']:
        csv_files.extend(Path(data_dir).glob(ext))
    
    if not csv_files:
        print(f"未找到CSV文件: {data_dir}")
        return datasets
    
    for csv_file in csv_files:
        try:
            print(f" [FILE] 正在读取: {csv_file.name}")
            
            # 检测编码
            encoding = detect_encoding(csv_file)
            print(f"   [ENCODING] 检测到编码: {encoding}")
            
            # 读取文件内容
            with open(csv_file, 'r', encoding=encoding) as f:
                lines = f.readlines()
            
            # 获取样品名称
            sample_name = csv_file.stem
            
            # 查找数据头
            data_start = None
            for i, line in enumerate(lines):
                if '波长(nm),吸收值' in line:
                    data_start = i + 1
                    break
            
            if data_start is None:
                print(f"  [ERROR] 未找到数据头")
                continue
            
            # 读取数据
            wl_list = []
            abs_list = []
            for line in lines[data_start:]:
                line = line.strip()
                if not line:
                    continue
                parts = line.split(',')
                if len(parts) >= 2:
                    try:
                        wl = float(parts[0])
                        abs_val = float(parts[1])
                        wl_list.append(wl)
                        abs_list.append(abs_val)
                    except ValueError:
                        continue
            
            if len(wl_list) == 0:
                print(f"  [ERROR] 无有效数据")
                continue
            
            # 转换为numpy数组并确保波长递增
            wl_array = np.array(wl_list)
            abs_array = np.array(abs_list)
            
            # 如果波长是递减的，反转数据
            if wl_array[0] > wl_array[-1]:
                wl_array = wl_array[::-1]
                abs_array = abs_array[::-1]
            
            # 创建数据集
            dataset = {
                'label': sample_name,
                'wl': wl_array,
                'absorption': abs_array,
                'file': str(csv_file)
            }
            
            datasets.append(dataset)
            print(f"   [OK] 样品: {sample_name}")
            print(f"   [RANGE] 波长范围: {wl_array.min():.1f} - {wl_array.max():.1f} nm")
            print(f"   [RANGE] 数据点数: {len(wl_array)}")
            
        except Exception as e:
            print(f"  [ERROR] 读取失败: {e}")
            continue
    
    print(f"\n [TOTAL] 成功加载 {len(datasets)} 个吸收光谱数据集")
    return datasets

def test_plot_combined(datasets, output_dir):
    """测试合并图绘制"""
    try:
        import matplotlib.pyplot as plt
        
        # 创建输出目录
        os.makedirs(output_dir, exist_ok=True)
        
        # 创建图表
        fig, ax = plt.subplots(figsize=(12, 8))
        
        # 颜色
        colors = plt.cm.tab10.colors
        
        # 绘制每个光谱
        for i, data in enumerate(datasets):
            x = data['wl']
            y = data['absorption']
            color = colors[i % len(colors)]
            
            ax.plot(x, y, linewidth=2, alpha=0.8, 
                   label=data['label'], color=color)
        
        # 设置标题和标签
        ax.set_title("吸收光谱对比测试", fontsize=14, fontweight='bold')
        ax.set_xlabel("波长 (nm)", fontsize=12)
        ax.set_ylabel("吸收值", fontsize=12)
        
        # 网格和图例
        ax.grid(True, alpha=0.3)
        ax.legend()
        
        # 自动调整Y轴范围
        all_abs = [data['absorption'] for data in datasets]
        max_abs = max(max(abs_vals) for abs_vals in all_abs)
        min_abs = min(min(abs_vals) for abs_vals in all_abs)
        
        print(f"   [RANGE] 吸收值范围: {min_abs:.3f} - {max_abs:.3f}")
        print(f"   [RATIO] 最大/最小比: {max_abs/min_abs:.1f}")
        
        # 如果数据范围很大，使用对数坐标
        if max_abs / min_abs > 100:
            ax.set_yscale('log')
            ax.set_ylabel("吸收值 (对数坐标)", fontsize=12)
            y_range = (min_abs * 0.5, max_abs * 2)
            print("   [SCALE] 使用对数坐标")
        else:
            y_range = (min_abs - (max_abs - min_abs) * 0.1, 
                      max_abs + (max_abs - min_abs) * 0.1)
            print("   [SCALE] 使用线性坐标")
        
        ax.set_ylim(y_range)
        
        plt.tight_layout()
        
        # 保存图像
        save_path = Path(output_dir) / "combined_absorption_test.png"
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        plt.close()
        
        print(f"成功生成测试图: {save_path}")
        return True
        
    except Exception as e:
        print(f"绘图失败: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    print("开始直接测试...")
    
    # 数据目录
    data_dir = r"D:\北大\光谱工具\示例数据\测试数据\20260826"
    output_dir = os.path.join(data_dir, "plots")
    
    print(f"数据目录: {data_dir}")
    print(f"输出目录: {output_dir}")
    
    # 检查目录
    if not os.path.exists(data_dir):
        print("错误: 数据目录不存在")
        return
    
    # 加载数据
    datasets = load_absorption_spectra_test(data_dir)
    
    if not datasets:
        print("未加载到任何数据")
        return
    
    # 测试绘图
    print("\n开始测试合并图绘制...")
    success = test_plot_combined(datasets, output_dir)
    
    if success:
        print("\n测试完成！请检查 plots 目录中的图像文件。")
    else:
        print("\n测试失败！")

if __name__ == "__main__":
    main()