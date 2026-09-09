# 🔧 4.3 版本更新说明

**版本**：v4.3
**日期**：2026-08-29

---

## 🛠 修复：「寿命分布」选项卡出现在吸收/发射模式

- 此前该选项卡无条件添加，吸收/发射模式下也显示。现改为**只在荧光寿命模式下显示**。
- 新增 `gui_ui._set_dist_tab_visible()`：Qt ≥ 5.15 用 `setTabVisible`（页保留、索引不变），
  旧版 Qt 回退为移除/插回（插回固定放「预览」之后第 1 位，切走前若正停在该页先切回预览）。
- 由 `gui_data.on_spectrum_type_changed` 在模式切换时调用。

## 🛠 修复：数字调整箭头角度错误

- 运行时 QPainter 画的折线箭头角度跑偏（形似「7」字）。
- 按「预生成图片文件」思路重构：
  - 新增 `icons\` 目录，预生成 4 个静态 PNG（arrow-up / arrow-down 实心三角、
    chevron-down 下拉箭头、check 白色对勾，32px 高清源）；
  - 删除 `gui_ui._ensure_style_icons()`（运行时渲染），改为 `_load_style_icons()`
    经 `resource_path` 加载静态文件；
  - 打包脚本新增 `--add-data icons;icons`；图标缺失时自动省略对应 image 行
    （QSS 空 url 会使整条规则失效）。

## 🎨 字体统一（整体调小一档）

- **根因**：旧代码给单个控件硬编码 pt 字号（15/14/13pt 混杂），「峰检测参数」标题和
  「颜色方案」下拉框恰好没设置所以偏小，其余偏大。
- **处理**：删除 30 余处逐控件 `setPointSize` 硬编码，字号统一由 `apply_style()` 的
  QSS 控制：全局字体 12pt、标签 16px、输入框/按钮 15px、复选框 15px、
  分组标题统一 16px。**以后调字号只改 QSS，不要给单控件 setPointSize。**
- 「预览 / 寿命分布 / 信息」选项卡文字被边框遮挡：`QTabBar::tab` 内边距 7px→10px、
  字号调小，三个标签渲染完整。

## 🔢 版本号

- `APP_VERSION` 更新为 **v4.3**。

## 📦 打包

- 重新打包并通过启动测试。

## 📝 经验记录

- 验证选项卡显隐要用 `tabBar().isTabVisible(i)`——`tabText` 列表对隐藏页照样返回文本，
  会得出「没生效」的假结论。
- offscreen 平台（`QT_QPA_PLATFORM=offscreen`）字体库为空（0 个字体族），Qt 控件
  文字全部缺失属环境限制，非样式问题；验证视觉效果需用真实 windows 平台。
- 未 `show()` 的窗口直接 `grab()` 可能出现布局未完成的伪影（如 tabbar 宽度异常、
  出现滚动按钮），需先 `show()`（可配 `WA_DontShowOnScreen`）再截图。
