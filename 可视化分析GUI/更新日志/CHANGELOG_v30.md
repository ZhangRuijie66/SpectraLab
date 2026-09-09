# 🆕 3.0 版本更新说明

**版本**：v3.0
**日期**：2026-08-28

---

## ✨ 新增：荧光寿命拟合模块（MEM 最大熵 + IRF 重卷积）

- 新增独立绘图模块 `plot_lifetime.py`（位于画图文件夹），算法移植自
  FluoIt（Edward Kerman，MIT License），改为**纯 numpy/scipy 实现**（原版依赖
  torch/gpuminimize，本机无 torch，且 torch 不可打包）：
  1. 预处理：IRF FWHM / 背景 / 上升沿统计，tail-fitting 估计时间位移 qshift，
     自动确定拟合区间；
  2. 主拟合：对数速率网格（k = 1/τ，0.01–100 ns⁻¹，201 点）预卷积 IRF →
     多起点 SLSQP 粗估 → 交替优化 qshift 与速率分布
     （目标函数 χ² − λ·S，S 为 Shannon 熵），改进量 < 容限收敛；
  3. 后处理：速率分布多重高斯分解，给出各分量 τ / 面积占比 / FWHM；
  4. 出图：衰减+IRF+拟合（log 轴）+残差图、寿命分布图，另存结果 json。
- 数据格式自动检测：Horiba/DeltaHub 时间扫描 CSV（`Labels,Decay2,IR1` 头部）
  与简单三列 CSV（time, decay, irf）。
- 附 `plot_lifetime使用说明.md`。

## ✨ 新增：GUI 集成「荧光寿命 (Lifetime)」模式

- 光谱类型下拉框新增第三项，参数面板新增「荧光寿命选项」组
  （拟合方法 MEM/SESM、速率网格点数），寿命模式下自动隐藏峰检测/波长范围等
  不相关控件；
- 加载：逐文件解析，无法解析的文件静默跳过（目录里混有其他 CSV 属常态）；
- 拟合在 **PlotWorker 后台线程**执行，不卡界面；预览显示衰减+IRF+拟合+残差
  （log 轴、χ²ᴿ 标注），「信息」页显示 χ²ᴿ、IRF 位移、各寿命分量与占比；
- 慢操作约定：单次拟合 1–2 分钟，**只有点「📊 实时预览」才触发拟合**，
  参数改动不自动重拟合。

## ✅ 验证

- 真实数据实测（`esipt-1/Decay2.csv`，4096 点，IRF FWHM≈0.098 ns）：
  **χ²ᴿ = 0.9994，τ₁ = 0.886 ns（44.1%）、τ₂ = 6.23 ns（55.9%）**，
  符合 ESIPT 双发射衰减预期；
- 图表经视觉验收（图例/中文标签/残差/χ²ᴿ 标注正常）。

---

## 🔢 版本号
- `APP_VERSION` 更新为 **v3.0**（`start_gui.py` / `launch_hidden.py` 同步）。

## 📦 打包
- `打包便携版.ps1` 新增 `--hidden-import plot_lifetime`；重新打包并通过
  依赖图检查与启动测试。
- **约定**：新模块只能依赖 numpy/scipy/pandas/matplotlib（打包排除
  torch/rich 等），不得 import torch/rich。
