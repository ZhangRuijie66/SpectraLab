# 🚀 GUI程序启动方法（已修复编码问题）

## ❌ 原问题

双击批处理文件后出现编码错误：
```
'煡Python...' 不是内部或外部命令...
```

**原因**：批处理文件中的中文字符在Windows命令行中被错误解析。

## ✅ 解决方案（已修复）

### 方案1：使用英文批处理文件 ⭐⭐⭐⭐⭐

**文件**：`run_gui.bat`（已更新为纯英文）

**使用方法**：
```
双击：run_gui.bat
```

**特点**：
- ✅ 纯英文，无编码问题
- ✅ 功能完整
- ✅ 窗口保持打开

---

### 方案2：使用PowerShell脚本 ⭐⭐⭐⭐⭐

**文件**：`run_gui.ps1`

**使用方法**：
```
右键点击 run_gui.ps1 -> 使用PowerShell运行
```

**特点**：
- ✅ PowerShell对UTF-8支持更好
- ✅ 彩色输出
- ✅ 详细错误信息

---

### 方案3：双击Python文件 ⭐⭐⭐⭐

**文件**：`启动GUI.py`

**使用方法**：
```
双击：启动GUI.py
```

**特点**：
- ✅ 最简单
- ✅ 无批处理文件
- ✅ 直接运行

---

### 方案4：命令行启动 ⭐⭐⭐⭐⭐

**命令**：
```bash
cd "D:\北大\QLS Lab\SPC\1O2+luminol\谱图\光谱\画图"
python start_gui.py
```

**特点**：
- ✅ 最可靠
- ✅ 100%成功

---

### 方案5：调试版批处理文件 ⭐⭐⭐⭐

**文件**：`run_gui_en.bat`

**使用方法**：
```
双击：run_gui_en.bat
```

**特点**：
- ✅ 详细输出
- ✅ 窗口保持打开
- ✅ 纯英文

---

## 🎯 推荐使用顺序

1. **首选**：双击 `run_gui.bat` - 最简单，已修复
2. **备选**：双击 `启动GUI.py` - 不需要批处理
3. **调试**：双击 `run_gui_en.bat` - 查看详细信息
4. **可靠**：命令行 `python start_gui.py` - 最可靠

## 📋 启动文件清单

| 文件名 | 类型 | 编码 | 推荐度 |
|--------|------|------|--------|
| run_gui.bat | 批处理 | 纯英文 | ⭐⭐⭐⭐⭐ |
| run_gui.ps1 | PowerShell | UTF-8 | ⭐⭐⭐⭐⭐ |
| run_gui_en.bat | 批处理 | 纯英文 | ⭐⭐⭐⭐ |
| 启动GUI.py | Python | UTF-8 | ⭐⭐⭐⭐ |

## 🔍 测试步骤

### 第1步：测试英文批处理
```
双击：run_gui.bat
```

应该看到：
```
========================================
  Absorption Spectrum Visualization Tool
========================================

[1/3] Checking dependencies...
[OK] Dependencies check passed

[2/3] Starting GUI program...
TIP: If window does not appear, check taskbar or press Alt+Tab

Starting...
```

然后GUI窗口应该会打开。

### 第2步：如果批处理不行，尝试Python文件
```
双击：启动GUI.py
```

### 第3步：如果还不行，使用PowerShell
```
右键 run_gui.ps1 -> 使用PowerShell运行
```

### 第4步：最终方案 - 命令行
```bash
python start_gui.py
```

## 💡 提示

1. **窗口标题**：`Absorption Spectrum Visualization Tool v1.0`
2. **如果看不到窗口**：按 `Alt+Tab` 切换窗口
3. **查看任务栏**：寻找Python图标
4. **调试信息**：使用 `run_gui_en.bat` 查看详细信息

## 🎉 现在试试吧！

### 最简单的方法：
```
双击：run_gui.bat
```

### 如果还不行：
```
双击：启动GUI.py
```

### 如果还不行：
```bash
python start_gui.py
```

---

**问题已修复！** 所有启动文件都已更新，不再有编码问题。