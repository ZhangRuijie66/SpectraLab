# -*- coding: utf-8 -*-
"""
曲线颜色的稳定分配：同一份数据（按样品名 / 文件名标识）始终拿到同一个颜色。

解决的问题
----------
合并图原来是「第 i 条曲线取色带第 i 个点」，而色带又按曲线条数重新采样
（linspace(0, 1, n)）。于是只要在合并图里增删一条曲线，n 变了、采样点全变，
所有曲线的颜色一起串位——已经画好的图和增删后的图对不上。

用法
----
    from curve_colors import CurveColors

    assigner = CurveColors()                       # 一个分配器管一组图
    c = assigner.get("样品A", plt.cm.Set1)          # 首次调用时分配并记住
    c = assigner.get("样品A", plt.cm.Set1)          # 之后永远返回同一个颜色
    assigner.reset()                               # 换数据 / 换配色方案时清空

GUI（可视化分析GUI）与独立脚本（plot_absorption / plot_emission）共用本模块。
"""

import matplotlib.pyplot as plt


class CurveColors:
    """按数据身份分配颜色的分配器（只在本次运行内记忆，不落盘）。

    每条数据第一次出现时从当前色带里挑一个位置并记住，之后永远用这个位置，
    所以增删其它曲线、或调整顺序，都不会改变已画曲线的颜色。挑位置的规则：

    - 离散配色（Set1 / tab10 等，颜色数 ≤ QUALITATIVE_MAX）：按色表自然顺序
      取下一个未用过的颜色，因此前几条曲线就是大家熟悉的红、蓝、绿、紫……
    - 连续色带（Blues / viridis / rainbow 等）：取离已用位置最远的点，保证
      任意条数下颜色都尽量拉开。
    """

    QUALITATIVE_MAX = 12  # 颜色数不超过此值即按离散配色处理
    GRID = 33             # 连续色带的候选位置数量，位置 t = k / (GRID - 1)

    def __init__(self):
        self._pos = {}  # 数据标识 -> 色带位置 t ∈ [0, 1]

    def reset(self):
        """清空所有已分配的颜色（换一批数据、或换配色方案时调用）"""
        self._pos.clear()

    def get(self, key, color_map=None, total=None):
        """取 key 对应的颜色；首次调用时分配并记住。

        参数
        ----
        key : 数据标识（GUI 用文件列表里的名字，脚本用样品名）
        color_map : matplotlib 色带，默认 Set1
        total : 本次要画的曲线**总数**（可选，v4.46）。
            传入后，若总数超过该色带的唯一色数（Set1 只有 9 色），
            自动改用同色系的**连续色带**分配，避免第 10 条起颜色重复——
            实测 26 条曲线时只有 9 种颜色、26 条图例里仅 8 条唯一标签，
            合并图根本没法区分哪条是哪条。

        返回
        ----
        RGBA 元组，可直接传给 ax.plot(color=...)
        """
        if color_map is None:
            color_map = plt.cm.Set1
        cmap = color_map
        # v4.46：条数超过色表唯一色数时，降级到连续色带（保序、颜色不重复）
        try:
            n_unique = getattr(color_map, 'N', 256) or 256
            if total is not None and n_unique > 1 and total > n_unique:
                cmap = self._continuous_fallback(color_map)
        except Exception:
            cmap = color_map
        t = self._pos.get(key)
        if t is None:
            t = self._next_pos(cmap)
            self._pos[key] = t
        return cmap(t)

    @staticmethod
    def _continuous_fallback(color_map):
        """把离散色表换成"从它的颜色里插值出的连续色带"（v4.46）。

        做法：取原色表每个颜色的 RGB，用采到的这些采样点直接构造一条
        **N=256 的 LinearSegmentedColormap**。这样既保留原配方的色系
        （Set1 → 红蓝绿紫…），又能按需切出任意条互不相同的颜色。

        ⚠️ 不能用 ListedColormap(cols)：它的 N 会等于 len(cols)（如 9），
        `_next_pos` 仍会按"离散色表"处理，只会切出 9 个位置、颜色照样重复
        （第一版就这么写错，实测仍是 9/26 唯一）。必须显式给 N=256。
        """
        from matplotlib.colors import LinearSegmentedColormap
        try:
            n = int(getattr(color_map, 'N', 0) or 0)
            if n <= 1:
                return color_map
            positions = [k / (n - 1) for k in range(n)]
            cols = [tuple(color_map(k / (n - 1))) for k in range(n)]
            return LinearSegmentedColormap.from_list(
                f'{getattr(color_map, "name", "cmap")}_cont',
                list(zip(positions, cols)), N=256)
        except Exception:
            return color_map

    def _next_pos(self, color_map):
        """为新数据挑一个色带位置"""
        n = getattr(color_map, 'N', 256) or 256
        if n <= self.QUALITATIVE_MAX:
            return self._next_qualitative_pos(n)
        return self._next_continuous_pos()

    def _next_qualitative_pos(self, n):
        """离散配色：按色表顺序取下一个没用过的颜色；色表用尽后循环复用"""
        if n <= 1:
            return 0.0
        grid = [round(k / (n - 1), 6) for k in range(n)]
        used = set(self._pos.values())
        for t in grid:
            if t not in used:
                return t
        return grid[len(self._pos) % n]

    def _next_continuous_pos(self):
        """连续色带：在候选网格上取离已用位置最远的点（并列时取靠前的）"""
        used = list(self._pos.values())
        if not used:
            return 0.0
        best_t, best_d = 0.0, -1.0
        for k in range(self.GRID):
            t = k / (self.GRID - 1)
            d = min(abs(t - u) for u in used)
            if d > best_d:
                best_t, best_d = t, d
        return best_t
