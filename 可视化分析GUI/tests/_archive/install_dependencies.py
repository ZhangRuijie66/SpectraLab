"""
安装GUI程序所需依赖
"""

import subprocess
import sys

def install_package(package):
    """安装Python包"""
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", package])
        print(f"✓ 成功安装 {package}")
        return True
    except subprocess.CalledProcessError:
        print(f"✗ 安装 {package} 失败")
        return False

def main():
    print("=" * 50)
    print("  安装吸收光谱GUI程序依赖")
    print("=" * 50)
    print()

    # 需要安装的包
    packages = [
        "PyQt5",
        "matplotlib",
        "numpy",
        "scipy",
        "pandas"
    ]

    # 检查已安装的包
    print("检查已安装的包...")
    installed = []
    missing = []
    for package in packages:
        try:
            __import__(package)
            print(f"  ✓ {package} 已安装")
            installed.append(package)
        except ImportError:
            print(f"  ✗ {package} 未安装")
            missing.append(package)

    print()
    if not missing:
        print("所有依赖已安装！可以直接运行GUI程序。")
        return

    print(f"需要安装 {len(missing)} 个包: {', '.join(missing)}")
    print()

    # 安装缺失的包
    print("开始安装...")
    success_count = 0
    for package in missing:
        if install_package(package):
            success_count += 1
        print()

    print("=" * 50)
    if success_count == len(missing):
        print("✓ 所有依赖安装成功！")
        print("现在可以运行 GUI 程序:")
        print("  python absorption_gui.py")
        print("  或双击 run_gui.bat")
    else:
        print(f"✗ 安装完成 {success_count}/{len(missing)} 个包")
        print("请检查网络连接或手动安装失败的包")
    print("=" * 50)

if __name__ == "__main__":
    main()