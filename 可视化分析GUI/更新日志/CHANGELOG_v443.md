# CHANGELOG v4.43

**版本**：v4.43
**日期**：2026-11-05
**类型**：品牌清理（去实验室绑定）+ 设置迁移

---

## 🧹 清除 QLS 相关字样

软件已与原作者实验室（QLS Lab）完全解绑，成为通用光谱分析工具。

- **应用标识**：`APP_ORG` / `LOG_APP_DIR` 由 `QLSLab` 改为 `SpectraLab`
  - QSettings 注册表根：`HKCU\Software\SpectraLab`
  - 日志目录：`%LOCALAPPDATA%\SpectraLab\logs\`
- **默认工作区**：由原实验室数据目录改为项目自带示例数据 `D:\北大\光谱工具\示例数据`
- **日志 logger 名**：`qls` → `spectra`（handler 标记属性 `_qls_*` → `_spectra_*`）
- **启动画面**：页脚去掉 `QLS Lab` 署名，只保留版本号
- **splash 元数据键**：`QLSVersion` → `SpectraVersion`（`生成splash图.py` 与 `检查版本一致性.py` 同步改）
- **调试环境变量**：`QLS_DEBUG_CHI2` → `SPECTRA_DEBUG_CHI2`
- **图表内部属性**：`ax._qls_base_left` → `ax._spectra_base_left`
- **帮助/关于**：删去「代码生成：deepseek-v4-flash、GLM-5.3-flash」一行，只保留更新日期与创建人
- 测试脚本、文档、更新日志中的实验数据路径统一改指项目内 `示例数据\测试数据\`

## 🔄 旧设置自动继承

升级不会丢失已有配置：

- 旧注册表键 `HKCU\Software\QLSLab` 的 56 项设置（主题、工作区、上次会话、参数、默认值、帮助窗口尺寸）**已完整复制**到 `HKCU\Software\SpectraLab`（逐字节校验一致）
- 旧日志目录 `%LOCALAPPDATA%\QLSLab\logs` 下 11 个历史日志**已复制**到新目录（哈希一致）
- 旧数据保留不删，可随时回退

## 📦 打包

- 便携版 exe 重新打包（v4.43），内部不再含 QLS 字样
- 版本一致性检查：splash 元数据 `SpectraVersion=4.43` == `APP_VERSION`

## ⚠️ 兼容性说明

- 若曾用外部脚本读取 `%LOCALAPPDATA%\QLSLab\logs`，需改为新路径
- 若曾设置环境变量 `QLS_DEBUG_CHI2`，需改用 `SPECTRA_DEBUG_CHI2`
- 依赖旧注册表路径的工具需改指 `HKCU\Software\SpectraLab`
