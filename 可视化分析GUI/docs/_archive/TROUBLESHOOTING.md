# GUI窗口不显示问题排查

## 问题描述
双击 `run_gui.bat` 后只弹出黑色窗口，然后消失，看不到GUI界面。

## 可能的原因

### 1. 窗口打开在后台
**症状**：程序启动但没有窗口可见
**解决**：
- 检查任务栏，看是否有"吸收光谱可视化分析工具"图标
- 按 `Alt+Tab` 切换窗口
- 按 `Win+Tab` 查看所有打开的窗口

### 2. 窗口在屏幕外
**症状**：程序启动但窗口在屏幕可见区域外
**解决**：
- 按 `Alt+Space`，然后按 `M`（移动），用方向键把窗口移回来
- 重启电脑重置窗口位置
- 使用改进版启动脚本 `run_gui_v2.bat`

### 3. 程序立即崩溃
**症状**：窗口一闪而过
**解决**：
- 从命令行运行查看错误信息：
  ```bash
  cd "D:\北大\光谱工具"
  python debug_gui.py
  ```
- 查看错误消息并解决

### 4. Python环境问题
**症状**：程序无法启动
**解决**：
- 检查Python版本（需要3.7+）
- 重新安装依赖：
  ```bash
  pip install --upgrade PyQt5 matplotlib numpy scipy pandas
  ```

## 推荐的启动方法

### 方法1：使用改进版批处理文件
```
双击：run_gui_v2.bat
```

这个版本会显示更多信息，窗口会保持在最前面。

### 方法2：使用Python脚本
```bash
cd "D:\北大\光谱工具"
python start_gui.py
```

### 方法3：从命令行运行
```bash
cd "D:\北大\光谱工具"
python absorption_gui.py
```

## 测试PyQt5是否正常工作

运行简单测试：
```bash
cd "D:\北大\光谱工具"
python test_pyqt_simple.py
```

如果能看到"PyQt5 测试"窗口，说明PyQt5工作正常。

## 调试步骤

### 第1步：检查依赖
```bash
python check_dependencies.py
```

### 第2步：运行调试脚本
```bash
python debug_gui.py
```

这会显示详细的启动过程和任何错误信息。

### 第3步：运行简单测试
```bash
python test_pyqt_simple.py
```

这会测试PyQt5是否正常工作。

## 常见错误和解决方法

### 错误1：ModuleNotFoundError: No module named 'PyQt5'
**解决**：
```bash
pip install PyQt5
```

### 错误2：ImportError: cannot import name 'xxx'
**解决**：
```bash
pip install --upgrade PyQt5 matplotlib numpy scipy pandas
```

### 错误3：AttributeError: type object 'Qt' has no attribute 'xxx'
**解决**：
这通常是代码问题，已经在新版本中修复。使用最新的 `absorption_gui.py`。

### 错误4：窗口一闪而过
**解决**：
从命令行运行查看错误信息：
```bash
python absorption_gui.py
```

## 如果仍然无法解决

1. **收集信息**：
   - Python版本：`python --version`
   - PyQt5版本：`python -c "import PyQt5.QtCore; print(PyQt5.QtCore.PYQT_VERSION_STR)"`
   - 操作系统版本
   - 完整的错误消息

2. **尝试重新安装**：
   ```bash
   pip uninstall PyQt5
   pip install PyQt5
   ```

3. **尝试使用不同的Python环境**：
   - 使用conda：`conda install pyqt`
   - 使用虚拟环境

## 临时解决方案

如果GUI程序无法使用，可以使用命令行版本：

```python
import sys
sys.path.insert(0, r'D:\北大\光谱工具')

from plot_absorption import plot_absorption_spectra
from pathlib import Path

# 绘制光谱
plot_absorption_spectra(
    files="D:/北大/QLS Lab/SPC/1O2+luminol/谱图/光谱/20260826/*.csv",
    save_dir="./plots",
    show=False
)
```

## 需要帮助？

请提供以下信息以便诊断问题：
1. Python版本
2. PyQt5版本
3. 完整的错误消息
4. 你尝试了哪些解决方法

---

**提示**：大多数情况下，使用 `run_gui_v2.bat` 或 `python start_gui.py` 可以解决窗口显示问题。