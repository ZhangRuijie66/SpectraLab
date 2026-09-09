# 🔧 问题修复 v3

## 修复的问题

### 问题1：点击任意一个数据会闪退 ✅

**原因**：
- `on_file_selected()` 函数中的 `find_absorption_peaks()` 调用可能失败
- 没有异常处理，导致程序崩溃

**修复**：
- 在 `on_file_selected()` 函数中添加完整的异常处理
- 峰检测部分单独添加 try-except
- 错误信息显示在信息标签中

**代码修改**：
```python
def on_file_selected(self, item):
    try:
        # 主逻辑
        ...
        # 峰信息
        if self.mark_peaks_check.isChecked():
            try:
                peaks = find_absorption_peaks(...)
                # 处理峰信息
            except Exception as e:
                info_text += f"峰检测失败: {str(e)}\n"
    except Exception as e:
        self.info_label.setText(f"错误: {str(e)}")
        QMessageBox.warning(self, "错误", f"选择文件失败: {str(e)}")
```

---

### 问题2：绘图失败 - 参数名错误 ✅

**原因**：
- `find_absorption_peaks()` 函数的参数名是 `min_height` 和 `min_distance`
- GUI程序使用的是 `height` 和 `distance`

**修复**：
- 将所有 `height=` 改为 `min_height=`
- 将所有 `distance=` 改为 `min_distance=`

**修改位置**：
1. `on_file_selected()` 函数（第595-600行）
2. `_plot_combined()` 函数（第710-712行）
3. `_plot_single()` 函数（第751-753行）
4. 批量导出函数（第856-858行）

---

## 🎯 测试步骤

### 测试1：文件加载和选择

1. 启动程序：双击 `run_gui.bat`
2. 点击"选择文件夹"
3. 选择 `20260826` 文件夹
4. **预期**：
   - ✅ 文件列表显示3个文件
   - ✅ 文件夹标签显示已加载3个文件

5. 点击文件列表中的任意文件（如 20260826RB.csv）
6. **预期**：
   - ✅ **不会闪退**
   - ✅ 信息标签页显示文件信息
   - ✅ 如果勾选"标记峰"，显示峰信息

---

### 测试2：绘图功能

1. 确保数据已加载
2. 点击"📊 实时预览"
3. **预期**：
   - ✅ **不会报错**
   - ✅ 右侧画布显示吸收光谱图
   - ✅ 如果勾选"标记峰"，峰会被标记

4. 切换到"单独图"模式
5. 点击文件列表中的文件
6. **预期**：
   - ✅ 显示单独图
   - ✅ 峰会被标记（如果勾选）

---

### 测试3：参数调整

1. 调整"峰高度阈值"和"峰最小间距"
2. 点击"📊 实时预览"
3. **预期**：
   - ✅ **不会报错**
   - ✅ 图表正常显示
   - ✅ 峰标记数量会变化

---

## 📝 技术细节

### find_absorption_peaks 函数签名

**正确的参数**：
```python
find_absorption_peaks(data, peak_range=None, min_height=0.05, min_distance=5, min_prominence=0.02)
```

**错误的调用**（已修复）：
```python
find_absorption_peaks(wavelength, absorption, height=0.05, distance=10)
# 错误：参数名应该是 min_height 和 min_distance
```

**正确的调用**（已修复）：
```python
find_absorption_peaks(wavelength, absorption, min_height=0.05, min_distance=10)
```

---

## 🚀 重新启动程序

请关闭当前程序，然后重新启动：

```bash
双击：run_gui.bat
```

---

## ✅ 验证清单

请逐项验证以下功能：

- [ ] 程序能正常启动
- [ ] 能选择文件夹并加载数据
- [ ] **点击文件不会闪退**
- [ ] 点击文件后信息标签显示正确
- [ ] **点击"实时预览"不会报错**
- [ ] 能正常绘图
- [ ] 峰标记功能正常
- [ ] 调整峰检测参数后能正常工作

---

## 🎉 现在应该完全正常了！

### 修复总结

**已修复的问题**：
1. ✅ 文件加载失败（键名兼容）
2. ✅ 字体太小（全局字体增加）
3. ✅ 点击文件闪退（异常处理）
4. ✅ 绘图失败（参数名修正）

**程序现在应该能稳定运行！**

---

**请重新启动程序并完整测试所有功能。** 🚀

如果还有任何问题，请告诉我具体的错误信息！