# 🚀 4.5 版本更新说明

**版本**：v4.5
**日期**：2026-08-29

---

## ✨ 新增：三级启动画面（双击 → 入口界面全程有反馈）

双击 exe 后不再黑屏等待，每一段都有画面：

1. **Bootloader 启动图**（PyInstaller `--splash`，内嵌 `splash.png`）：
   双击约 1 秒内弹出，覆盖最耗时的 onefile 解压阶段；
   显示应用图标、「正在启动，请稍候…」及防重复双击提示。
2. **Qt 动态启动画面**（新增 `gui_splash.py`）：无边框圆角卡片
   （图标 + 应用名 + 版本徽标 + 蓝色状态行 + 不确定进度条），分阶段实时更新：
   - 正在加载绘图引擎与科学计算库（matplotlib / numpy / scipy / pandas）…
   - 正在检查绘图模块依赖…
   - 依赖检查通过（numpy x.x、scipy x.x、pandas x.x、matplotlib x.x）
   - 正在启动入口界面…
3. **模块选择界面**弹出，启动画面自动关闭。

## ✨ 新增：启动时真实依赖检查

- 逐个确认 numpy / scipy / pandas / matplotlib / plot_absorption / plot_emission /
  plot_lifetime / read_xlsx_info，缺依赖在启动画面显示缺失项并弹错误框，
  不再静默崩溃。

## 🔧 技术改动

- **打包入口更换**：`absorption_gui.py` → **`entry_gui.py`**（新增轻量入口）。
  重量级导入（matplotlib / scipy / pandas / 绘图模块）集中到 `import absorption_gui`
  一步，保证 Qt 启动画面先于它们出现。`entry_gui.py` 模块级零重量级依赖（已验证）。
- `absorption_gui.main()` 参数化：`main(app=None, startup_splash=None)`，
  源码直跑与 `start_gui.py` 等旧路径行为不变。
- **`gui_splash.py` 严禁导入 matplotlib / numpy / scipy / pandas**
  （只依赖 PyQt5 + gui_config）——它存在的意义就是赶在重量级库之前出现在屏幕上。
- 两级画面通过 PyInstaller `pyi_splash` 接口交接（`update_text` / `close`），
  Qt 画面起来后立即关闭 bootloader splash（不关会一直压在最上层）。
- 打包脚本新增：`--splash splash.png`、`--splash-center primary`、
  `--hidden-import absorption_gui / gui_splash`。
- PyInstaller splash 功能依赖 tkinter/Tcl-Tk（本机 8.6 可用），exe 体积 +约 2MB。

## 🎨 全局字体：微软雅黑

- 全局字体统一为**微软雅黑**（此前为系统默认宋体）：
  `entry_gui` / `absorption_gui.main` / `start_gui` / `launch_hidden` 四处启动路径
  统一设置 `app` 字体 family，主窗口（`gui_ui.setup_ui`）同步；
  基础字号基准 14pt → 12pt。**新增启动入口记得带上字体设置。**

## 🔢 版本号

- `APP_VERSION` 更新为 **v4.5**；`splash.png` 底部版本字样同步。

## 📦 打包

- 重新打包（约 110 MB，onefile + splash）并通过启动测试。
