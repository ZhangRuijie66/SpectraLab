"""
测试吸收光谱GUI程序

用于测试GUI程序是否正常工作
"""

import sys
from pathlib import Path

# 添加当前目录到Python路径
current_dir = Path(__file__).parent
if str(current_dir) not in sys.path:
    sys.path.insert(0, str(current_dir))

try:
    from absorption_gui import main
    print("✓ 成功导入GUI模块")
    print("✓ 启动GUI程序...")
    main()
except ImportError as e:
    print(f"✗ 导入失败: {e}")
    print("\n请检查是否安装了必要的依赖:")
    print("  pip install PyQt5 matplotlib numpy scipy pandas")
    sys.exit(1)
except Exception as e:
    print(f"✗ 程序启动失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)