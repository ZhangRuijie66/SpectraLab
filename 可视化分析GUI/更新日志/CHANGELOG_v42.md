# 🎨 4.2 版本更新说明

**版本**：v4.2
**日期**：2026-08-29

---

## 🎨 界面现代化美化（统一设计主题）

原界面为多种 Material 色拼凑 + 方角灰框 + 各控件内联样式，重构为统一现代浅色主题：

- **色板常量化**（`gui_config.py`）：冷灰背景 `#f1f5f9` + 白色圆角卡片 + 蓝色主色
  `#2563EB`，另设 success 绿 / violet 紫 / orange 橙 / cyan 青 / neutral 灰语义色。
  **以后改主题色只需动 `gui_config.py`**。
- **按钮语义色变体**：删除 8 处内联 `setStyleSheet`，改为
  `setProperty("variant", ...)` + QSS 属性选择器——
  primary 蓝（选择工作区/重新加载）、success 绿（选择文件夹/开始拟合）、
  violet 紫（实时预览）、orange 橙（导出图片）、cyan 青（导出全部）、
  neutral 灰（返回模块选择）。
- **全控件交互反馈**：输入类控件悬停加深边框、聚焦亮蓝边；按钮补齐悬停/按下/禁用
  三态；复选框改蓝色圆角选中态（白色对勾图标）；下拉框补箭头图标；
  滑块改细轨道 + 圆形手柄 + 蓝色已填充段。
- **部件级翻新**：标签页改蓝色药丸选中样式；滚动条纤细圆角化；状态栏加分隔线；
  matplotlib 工具栏按钮悬停底色；tooltip 深色圆角；分组框改白色圆角卡片。
- **入口界面重做**（`gui_launcher.py`）：纯色大按钮 → 白底卡片
  （左侧彩色竖条 + 图标 + 标题/描述分行 + 右侧「›」箭头，悬停整卡亮起），
  顶部应用名 + v 版本徽标；新增 `ModuleCard` 组件（QFrame + clicked 信号）。
- 下拉列表渲染（`ComboItemDelegate`）配色对齐新主题（选中蓝底白字、悬停淡蓝）。

## 🔧 顺带修复

- `launch_hidden.py` 硬编码的「v4.1」窗口标题改为跟随 `gui_config.APP_VERSION`。

## 🔢 版本号

- `APP_VERSION` 更新为 **v4.2**。

## 📦 打包

- 重新打包并通过启动测试（`gui_launcher` / `gui_components` 确认进 PyInstaller 依赖图）。
