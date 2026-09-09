# 🆕 4.1 版本更新说明

**版本**：v4.1
**日期**：2026-08-29

---

## ✨ 新增：「🏠 返回模块选择」按键

- 主窗口左上角（目录树面板顶部）新增「🏠 返回模块选择」按钮：点击后关闭
  当前窗口并回到 v4.0 的模块选择入口界面，可重新选择模块进入——
  **主界面 ⇄ 入口 可反复进出**，直接关闭窗口则退出程序；
- 实现机制：`return_to_launcher` 设置 `next_mode="launcher"` 并 close，
  `absorption_gui.main` / `start_gui.py` 的主循环检测 `window.next_mode`
  后重新弹出 `ModuleLauncher`；
- 若拟合正在进行中点返回，会先弹确认框（默认「否」），避免误放弃正在跑的拟合。

## ✨ 新增：入口界面「？」帮助（关于）

帮助信息挂在入口对话框**标题栏右上角自带的「？」按键**上
（`Qt.WindowContextHelpButtonHint` + 重写 `event()` 拦截
`QEvent.EnterWhatsThisMode`），点击即弹出帮助对话框，内容：

- **版本**：v4.1（读取 `gui_config.APP_VERSION`）
- **更新日期**：2026-08-29（新增 `gui_config.RELEASE_DATE` 常量，以后更新只改配置）
- **创建人**：张瑞杰
- **代码生成**：deepseek-v4-flash、GLM-5.3-flash
- 附三个模块的一句话说明

---

## 🔢 版本号
- `APP_VERSION` 更新为 **v4.1**，新增 `RELEASE_DATE = "2026-08-29"`；
  `launch_hidden.py` 标题同步。

## 📦 打包
- 重新打包（108 MB，onefile）并通过启动测试。

## 📝 经验记录
- 打包后 exe 的存活判断用 Git Bash `kill -0 $!` 最稳；
  `tasklist` / `PowerShell` 按**中文进程名/路径**查找会因 GBK 编码出现假阴性
  （进程明明在运行却查不到）。
