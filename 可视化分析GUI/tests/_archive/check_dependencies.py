"""
检查GUI程序依赖状态
"""

import sys

def check_module(module_name, display_name=None):
    """检查模块是否已安装"""
    try:
        __import__(module_name)
        print(f"[OK] {display_name or module_name} - 已安装")
        return True
    except ImportError:
        print(f"[X]  {display_name or module_name} - 未安装")
        return False

def main():
    print("=" * 60)
    print("  吸收光谱GUI程序依赖检查")
    print("=" * 60)
    print()

    # 需要检查的模块
    modules = [
        ("PyQt5", "PyQt5 (GUI框架)"),
        ("matplotlib", "Matplotlib (绘图引擎)"),
        ("numpy", "NumPy (数值计算)"),
        ("scipy", "SciPy (科学计算)"),
        ("pandas", "Pandas (数据处理)")
    ]

    results = []
    for module, display in modules:
        results.append(check_module(module, display))

    print()
    print("=" * 60)

    if all(results):
        print("[OK] 所有依赖已安装！可以启动GUI程序")
        print()
        print("启动命令：")
        print("  python absorption_gui.py")
        print()
        print("或双击：")
        print("  run_gui.bat")
    else:
        print("[X] 部分依赖未安装，请运行：")
        print()
        print("自动安装：")
        print("  python install_dependencies.py")
        print()
        print("或手动安装缺失的模块：")
        for i, (module, display) in enumerate(modules):
            if not results[i]:
                print(f"  pip install {module}")
        print()
        print("安装完成后重新运行此脚本检查")

    print("=" * 60)

if __name__ == "__main__":
    main()