"""
一键启动脚本 - 最简单的方式
直接从这里运行，不需要批处理
"""

import sys
import os
from pathlib import Path

# 切换到脚本所在目录
os.chdir(Path(__file__).parent)

# 直接启动GUI
exec(open('start_gui.py', encoding='utf-8').read())