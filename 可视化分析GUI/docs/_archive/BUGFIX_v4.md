# 🔧 问题修复 v4

## 修复的问题

### 问题：绘图失败 - NumPy索引错误 ✅

**错误信息**：
```
only integers, slices (`:`), ellipsis (`...`), numpy.newaxis (`None`) and integer or boolean arrays are valid indices
```

**根本原因**：
- `find_absorption_peaks()` 函数期望接收一个**数据字典**作为第一个参数
- 数据字典的格式应该是：`{'wl': wavelength_array, 'absorption': absorption_array}`
- GUI程序直接传递了 `wavelength` 和 `absorption` 数组
- 函数内部尝试用 `data['wl']` 访问，导致索引错误

**错误代码**：
```python
# 错误：直接传递数组
peaks = find_absorption_peaks(wavelength, absorption,
                              min_height=peak_height,
                              min_distance=peak_distance)
```

**修复后的代码**：
```python
# 正确：创建临时数据字典
temp_data = {'wl': wavelength, 'absorption': absorption}
peaks = find_absorption_peaks(temp_data,
                              min_height=peak_height,
                              min_distance=peak_distance)
```

---

## 修改位置

修复了3处调用：

1. **_plot_combined() 函数**（第717行）
   - 合并图中的峰标记

2. **_plot_single() 函数**（第760行）
   - 单独图中的峰标记

3. **批量导出函数**（第867行）
   - 导出单独图时的峰标记

---

## 🎯 测试步骤

### 测试1：基本绘图

1. 启动程序：双击 `run_gui.bat`
2. 点击"选择文件夹"
3. 选择 `20260826` 文件夹
4. 点击"📊 实时预览"
5. **预期**：
   - ✅ **不会报错**
   - ✅ 右侧画布显示吸收光谱合并图
   - ✅ 3条曲线正常显示

---

### 测试2：峰标记功能

1. 勾选"标记峰"
2. 点击"📊 实时预览"
3. **预期**：
   - ✅ **不会报错**
   - ✅ 图表上显示峰标记点
   - ✅ 峰标记为红色圆点

4. 切换到"单独图"模式
5. 点击文件列表中的文件
6. **预期**：
   - ✅ **不会报错**
   - ✅ 显示单独图
   - ✅ 峰标记正常显示
   - ✅ 显示峰位置标注

---

### 测试3：批量导出

1. 加载数据
2. 勾选"标记峰"
3. 点击"📁 导出全部图片"
4. **预期**：
   - ✅ **不会报错**
   - ✅ 成功导出所有图片
   - ✅ 导出的图片包含峰标记

---

## 📝 技术细节

### find_absorption_peaks 函数签名

**正确的调用方式**：
```python
# 函数期望接收数据字典
data_dict = {
    'wl': wavelength_array,      # 波长数组
    'absorption': absorption_array  # 吸收值数组
}

peaks = find_absorption_peaks(
    data_dict,                   # 第一个参数：数据字典
    peak_range=None,             # 可选：波长范围
    min_height=0.05,             # 可选：最小峰高
    min_distance=5,              # 可选：最小峰间距
    min_prominence=0.02          # 可选：最小峰突出度
)
```

### 为什么需要数据字典

查看 `plot_absorption.py` 中的函数实现：
```python
def find_absorption_peaks(data, ...):
    wl = data['wl']              # 尝试访问 'wl' 键
    absorption = data['absorption']
    # ... 处理逻辑
```

如果直接传递数组，`data['wl']` 就会尝试用数组作为字典的键，导致索引错误。

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
- [ ] 点击"实时预览"**不会报错**
- [ ] 能正常显示合并图
- [ ] 勾选"标记峰"后能正常标记
- [ ] 切换到单独图模式**不会报错**
- [ ] 点击文件后能显示单独图
- [ ] 峰标记正常显示
- [ ] 批量导出**不会报错**
- [ ] 导出的图片包含峰标记

---

## 🎉 现在应该完全正常了！

### 所有修复总结

**已修复的5个问题**：
1. ✅ 文件加载失败（键名兼容）
2. ✅ 字体太小（全局字体增加）
3. ✅ 点击文件闪退（异常处理）
4. ✅ 绘图失败（参数名修正）
5. ✅ 峰标记失败（数据格式修正）

**程序现在应该能稳定运行所有功能！**

---

## 📊 完整功能测试流程

1. **启动程序** → 双击 `run_gui.bat`
2. **加载数据** → 选择 `20260826` 文件夹
3. **查看合并图** → 点击"实时预览"
4. **测试峰标记** → 勾选"标记峰"，重新预览
5. **查看单独图** → 切换模式，点击文件
6. **调整参数** → 修改峰检测参数，重新预览
7. **导出图片** → 批量导出，查看结果

---

**请重新启动程序并完整测试所有功能。** 🚀

如果还有任何问题，请告诉我具体的错误信息！