# 📊 plot_3d_scan.py 使用说明

> 3D 扫描（EEM，激发-发射矩阵）CSV 绘图模块：**3D 曲面 / 等高线（俯视图）/ Waterfall 堆叠谱**
> 适用格式：**Spectracle / FE30** 输出的「3D 扫描 扫描」CSV

---

## 1. 适用数据格式

```
标签,"RB/Lu 1"
类型,"3D 扫描 扫描"
EX WL 起点 (nm),500.0
EX WL 结束 (nm),600.0
EX 读取间隔 (nm),1.0
EM WL 起点 (nm),200.0
EM WL 结束 (nm),900.0
EM 读取间隔 (nm),1.0
...
EM(nm)\EX(nm),500.0,501.0,502.0,...
200.0,1310.2173,1307.2765,...
201.0,2452.1919,2465.2397,...
```

- 数据表头必须含 `EM(nm)\EX(nm)`；第一列是 EM 波长，其余每列是一个 EX 波长。
- 解析时按**位置**保留空单元格为 NaN（旧版遇空值 `continue` 会让后续列左移，是曲面错位的元凶之一）。
- EM 轴若乱序会自动排序。

---

## 2. 为什么"插值了还是不连续"——数据清洗管线

实测这类数据的原始矩阵里混着两类伪迹，三次样条只会把它们一起放大：

| 伪迹 | 特征 | 后果 |
|---|---|---|
| **饱和点** | 强度卡在仪器上限（如 50000 反复出现，占矩阵 10%+） | 曲面顶出一块平板 |
| **周期梳状伪迹** | ~7 nm 周期、3 个通道一簇、峰值饱和、**位置固定在 EM 不随 EX 移动** | 样条必须穿过它们，两侧振铃出负值 → 视觉上"断开的尖刺" |

> 判据：**固定 EM** 说明它不是样品荧光（荧光带会随 EX 移动）。这类条纹通常是等厚干涉（滤光片/窗口的 étalon 效应）或光栅鬼线。

**清洗顺序**（每步可关，处理量会打印）：

```
饱和掩膜 → 沿 EM 线性补全 → 周期梳状伪迹处理 → 中值去残余窄线 → 高斯平滑 → 三次样条加密
```

**周期梳状伪迹的三种处理方式**（`comb_mode`）：

| 模式 | 做法 | 适用 |
|---|---|---|
| `minima`（默认） | 只保留条纹**谷值**通道（每周期 1 个），其余沿 EM 插值重建 | 条纹占 5/7 通道且峰值饱和时最稳；EM 有效采样降到 1 个周期（~7 nm） |
| `divide` | 按乘性条纹 `Z = I_true × gain(λ)` 除以估计增益 | 条纹较温和、未饱和时保留更多采样 |
| `rows` | 把被污染的 EM 行整体插值替换 | 污染行较少时 |
| 关闭 | 不做处理 | 数据本身没有条纹 |

颜色范围默认取**稳健分位数**（1%–99.5%），否则色标被伪迹独占、真正的发射带看不见。

---

## 3. 一键用法

```python
from plot_3d_scan import plot_3d_all

data, prep = plot_3d_all(
    r"D:\...\20260727-RB-Lu\RBLu 1 2026-07-27 07-11.csv",
    save_dir=r"D:\...\plots",
    n_traces=10,          # waterfall 曲线数
    smooth_factor=3,      # 样条加密倍数（1=不加密）
)
print(prep['stats'])      # 清洗统计：饱和点、条纹周期、保留通道数…
```

单独出图：

```python
from plot_3d_scan import (parse_3d_scan_csv, prepare_grid,
                          plot_3d_surface, plot_contour, plot_waterfall)

data = parse_3d_scan_csv(path)
plot_3d_surface(data, save_dir=out)                     # 3D 曲面
plot_contour(data, save_dir=out, n_levels=30)           # 等高线
plot_waterfall(data, save_dir=out, n_traces=12)         # 堆叠谱
```

---

## 4. 命令行用法

```bash
# 默认：清洗 + 三张图
python plot_3d_scan.py "RBLu 1 2026-07-27 07-11.csv" -o ./plots --no-show

# 关掉清洗看原始数据
python plot_3d_scan.py "x.csv" -o ./plots --no-notch --despike 0 --sigma-em 0

# 对数色标 + 稳健分位
python plot_3d_scan.py "x.csv" -o ./plots --log --percentile 5,99.9

# 手动指定条纹周期、只出等高线
python plot_3d_scan.py "x.csv" -o ./plots --comb-period 6.94 --no-3d --no-waterfall
```

主要参数：

| 参数 | 默认 | 说明 |
|---|---|---|
| `--despike` | 5 | 沿 EM 中值去残余窄线窗口（0/1 关闭） |
| `--sigma-em` / `--sigma-ex` | 1.0 / 0.0 | 高斯平滑 σ |
| `--no-notch` | — | 不做周期梳状伪迹处理 |
| `--comb-mode` | minima | minima / divide / rows |
| `--comb-period` | 自动 | 手动指定条纹周期 (nm) |
| `--no-clip-saturation` | — | 不自动修补饱和点 |
| `--log` | — | 对数色标 |
| `--percentile` | 1,99.5 | 稳健色标分位 |
| `--smooth` | 3 | 样条加密倍数 |

---

## 5. GUI 用法

主界面「光谱类型」下拉框选 **3D 扫描 (EEM)**（或入口界面点「🧊 3D 扫描 (EEM)」卡片）：

1. 左侧目录树/「选择文件夹」定位到含 3D 扫描 CSV 的文件夹（混着普通光谱 CSV 会自动跳过）；
2. 文件列表**点选**一个文件即绘制（该模式无合并图，无勾选框）；
3. 在「3D 扫描 (EEM) 选项」里切换：绘图类型（曲面/等高线/Waterfall）、梳状伪迹处理方式、
   中值窗口、EM/EX 平滑 σ、对数色标——**改参数即时重绘**；
4. 「信息」标签页显示矩阵尺寸、EX/EM 范围、强度范围，以及检测到的饱和上限与条纹周期；
5. 「💾 导出图片」保存当前画布（PNG/PDF/SVG）。

---

## 6. 清洗统计（v4.21 起 `stats` 里新增的诊断字段）

`prepare_grid()` 返回的 `stats` 现在把"做了什么、还剩多少没处理"全部量化，
CLI/GUI 的清洗报告也会打印：

| 字段 | 含义 |
| --- | --- |
| `cols_filled_em` / `cols_filled_ex` / `nan_left` | 沿 EM 补全的列数 / 整列缺失改沿 EX 补全的列数 / 仍剩的 NaN |
| `saturation` / `saturation_points` | 检测到的饱和上限与点数 |
| `saturation_neighbor_frac` / `saturation_ex_coverage` | 极值点的 EM 连续度 / 跨 EX 通道覆盖度——**判断是仪器饱和还是真实峰顶** |
| `comb_period` / `comb_strength` | 条纹周期 (nm) / 校正前的峰-底噪比 |
| `comb_strength_after` / `comb_residual` | 校正后的峰-底噪比 / 残余比例（>0.30 会提示换模式） |
| `comb_kept` / `comb_kept_step` / `comb_replaced_frac` | minima 模式保留的谷值通道数 / 等效采样 (nm) / 被插值替换的通道占比 |
| `neg_after_spline` | 样条加密后出现的负值个数（**已截断为 0**，不再流入分析） |
| `spline_ok` | 样条加密是否成功（失败会打印原因并降级为原始网格） |
| `axis_uniform` / `ex_dedup` / `em_dedup` | 坐标是否等间距 / 重复波长合并数 |

其它行为变化：

- **整条 EX 通道缺测不再被填 0**：旧实现 `_fill_nan_along_em` 对全 NaN 列直接置 0，
  会在 EEM 里造出一条人造暗带，被后续平滑"坐实"成结构；现在改为沿 EX 方向插值，
  插不了才保留 NaN；
- **EX 轴也做排序 + 重复波长合并**（旧实现只处理 EM，EX 递减时加密会静默失败）；
- **`Z_orig` 现在是 `Z` 的拷贝**（旧实现是别名，后续原地改动会连带改掉它）；
- `plot_3d_surface/contour/waterfall` 支持 `prep=` 复用已清洗网格，
  `plot_3d_all` 只清洗一次（此前同一份数据被清洗 3 次）；
- `_remove_comb_rows` 的 `harmonics` 参数现在真正生效（此前传入后完全没被使用）。

---

## 7. 已知限制

- `minima` 模式把 EM 有效采样降到约一个条纹周期（实测 ~7 nm）。对 30–50 nm 宽的荧光带够用，
  但会抹掉真正窄于一个周期的发射线——这种情况请选 `divide` 或关闭处理；
  峰高也会系统性偏低（谷值本身处在条纹低谷），`comb_replaced_frac` 给出被替换通道的比例。
- 只支持 `EM(nm)\EX(nm)` 单表头布局；同目录的普通发射光谱 CSV（如「发射数据组 …csv」）会被跳过。
- 若数据里还存在 `EM + EX ≈ 常数` 的斜线（光栅级次/杂散光鬼线），本模块**不**自动去除，
  需要在分析时自行判别。
- 极值点的空间形态（`saturation_neighbor_frac` / `saturation_ex_coverage` 都 <15%）提示
  可能是真实峰顶而非饱和；此时仍会按饱和修补并打印警告，若峰顶被削平请用
  `--no-clip-saturation` 关闭。

---

## 8. 相关文件

- 模块：`画图\plot_3d_scan.py`
- GUI 集成：`可视化分析GUI\gui_ui.py`（选项组）、`gui_data.py`（`_load_scan3d_files`）、
  `gui_plot.py`（`_do_scan3d_plot`）、`gui_launcher.py`（模块卡片）
- 打包：`打包便携版.ps1` 已加 `--hidden-import plot_3d_scan`
