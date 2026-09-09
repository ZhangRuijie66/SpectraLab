# GUI程序安装指南

## 方法1：快速安装（推荐）

### Windows用户
```bash
# 打开命令提示符或PowerShell，运行：
pip install PyQt5

# 验证安装
python check_dependencies.py
```

### 安装成功后启动GUI
```bash
# 方法1：双击批处理文件
双击 run_gui.bat

# 方法2：命令行
python absorption_gui.py
```

## 方法2：使用国内镜像源（更快）

```bash
# 使用清华镜像源
pip install -i https://pypi.tuna.tsinghua.edu.cn/simple PyQt5

# 或使用阿里云镜像源
pip install -i https://mirrors.aliyun.com/pypi/simple/ PyQt5

# 或使用豆瓣镜像源
pip install -i https://pypi.douban.com/simple/ PyQt5
```

## 方法3：安装所有依赖

```bash
# 安装所有需要的包
pip install PyQt5 matplotlib numpy scipy pandas

# 验证安装
python check_dependencies.py
```

## 方法4：使用conda（如果使用Anaconda）

```bash
# 使用conda安装
conda install pyqt matplotlib numpy scipy pandas

# 验证安装
python check_dependencies.py
```

## 方法5：使用安装脚本

```bash
# 运行自动安装脚本
python install_dependencies.py

# 脚本会自动检测并安装缺失的依赖
```

## 常见安装问题

### 问题1：pip命令不存在
**解决**：
- 重新安装Python，确保勾选"Add Python to PATH"
- 或使用完整路径：`C:\Python39\Scripts\pip.exe install PyQt5`

### 问题2：网络连接超时
**解决**：
- 使用方法2中的国内镜像源
- 或设置pip默认镜像源：
  ```bash
  pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
  ```

### 问题3：权限不足
**解决**：
```bash
# 使用--user参数安装到用户目录
pip install --user PyQt5
```

### 问题4：版本冲突
**解决**：
```bash
# 升级pip到最新版本
python -m pip install --upgrade pip

# 清理缓存
pip cache purge

# 重新安装
pip install PyQt5 --no-cache-dir
```

### 问题5：Microsoft Visual C++ 错误
**解决**：
- PyQt5需要Microsoft Visual C++ Redistributable
- 下载并安装：https://aka.ms/vs/17/release/vc_redist.x64.exe

## 验证安装

运行检查脚本：
```bash
python check_dependencies.py
```

预期输出：
```
[OK] PyQt5 (GUI框架) - 已安装
[OK] Matplotlib (绘图引擎) - 已安装
[OK] NumPy (数值计算) - 已安装
[OK] SciPy (科学计算) - 已安装
[OK] Pandas (数据处理) - 已安装

[OK] 所有依赖已安装！可以启动GUI程序
```

## 安装后的文件结构

```
画图/
├── absorption_gui.py           # GUI主程序
├── run_gui.bat                 # Windows快速启动脚本
├── test_gui.py                 # 测试脚本
├── install_dependencies.py     # 自动安装脚本
├── check_dependencies.py       # 依赖检查脚本
├── example_gui_usage.py        # 使用示例
├── GUI_README.md               # 完整使用指南
├── QUICKSTART.md               # 快速开始
└── INSTALL.md                  # 本文件
```

## 系统要求

### 最低要求
- Python 3.7+
- 2GB RAM
- 500MB 可用磁盘空间

### 推荐配置
- Python 3.9+
- 4GB RAM
- 1GB 可用磁盘空间
- Windows 10/11 或 macOS 10.14+ 或 Linux

## 卸载

如果需要卸载GUI程序：
```bash
pip uninstall PyQt5
```

## 获取帮助

如果遇到问题：
1. 查看本文件的"常见安装问题"部分
2. 运行 `python check_dependencies.py` 查看详细错误
3. 查看程序的错误消息（右下角状态栏）
4. 查看控制台输出（如果从命令行启动）

---

**提示**：安装完成后，建议先使用 `20260826` 文件夹测试GUI功能，该文件夹包含3个标准格式的CSV文件。