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

    def get(self, key, color_map=None):
        """取 key 对应的颜色；首次调用时分配并记住。

        参数
        ----
        key : 数据标识（GUI 用文件列表里的名字，脚本用样品名）
        color_map : matplotlib 色带，默认 Set1

        返回
        ----
        RGBA 元组，可直接传给 ax.plot(color=...)
        """
        if color_map is None:
            color_map = plt.cm.Set1
        t = self._pos.get(key)
        if t is None:
            t = self._next_pos(color_map)
            self._pos[key] = t
        return color_map(t)

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
