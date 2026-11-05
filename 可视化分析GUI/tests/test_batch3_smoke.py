# -*- coding: utf-8 -*-
"""冒烟测试（v4.26 第 3 批）：三栏折叠/宽度记忆、文件搜索与全选、积分结果表格化。

离屏运行（不会弹任何窗口）：

    set QT_QPA_PLATFORM=offscreen
    set QT_QPA_FONTDIR=%WINDIR%\\Fonts
    python tests\\test_batch3_smoke.py

覆盖点：
  1. 栏开关条：3 个按钮、勾选态与折叠状态同步；
  2. 收起/展开：画布宽度确实变大（QDockWidget 重排，v4.29），展开后回到原宽度；
  3. 宽度记忆：写入 ui/panel_widths + ui/panel_hidden 后新建窗口能恢复；
  4. 文件搜索：过滤只影响显示，不动勾选状态；计数标签跟着变；
  5. 全选/全不选：按钮文字随状态切换，且**只作用于当前筛选结果**；
  6. 积分结果：改表格后有 N 行、数值列按数值排序、可导出 CSV（UTF-8 BOM）。
"""

import os
import sys
import tempfile
from pathlib import Path

GUI_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(GUI_DIR))
sys.path.insert(0, str(GUI_DIR.parent))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QSettings, Qt                      # noqa: E402
from PyQt5.QtWidgets import QApplication, QMessageBox       # noqa: E402

from gui_config import APP_ORG, APP_NAME                    # noqa: E402

DATA_DIR = r"D:\北大\光谱工具\示例数据\测试数据\20260729-A226RBL8i"
# 该目录是 LabSolutions RF 的发射谱（8 个 CSV，加载 7 个同名/可解析样品），
# 所以下面的文件列表与积分测试都跑在**发射模式**（吸收模式读不出这批数据）


def _make_gui():
    """建窗口：静态替换 QMessageBox，离屏下模态弹窗会挂死/崩溃。"""
    for fn in ("information", "warning", "critical", "question"):
        setattr(QMessageBox, fn, staticmethod(lambda *a, **k: None))
    from absorption_gui import AbsorptionGUI
    return AbsorptionGUI()


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    ok = []

    w = _make_gui()
    w.show()                       # 需要真实几何才能量宽度（离屏也能算）
    app.processEvents()

    # ---------- 1. 栏开关条 ----------
    btns = getattr(w, "panel_toggle_btns", [])
    assert len(btns) == 3, f"开关条应有 3 个按钮，实际 {len(btns)}"
    assert [b.isChecked() for b in btns] == [True, True, True], "初始应三栏都展开"
    ok.append(f"栏开关条 3 个按钮，初始全展开（宽度 {[b.width() for b in btns]}）")

    # ---------- 2. 收起 / 展开改变画布宽度 ----------
    # v4.29：三栏改成 QDockWidget，量的是画布与 dock 的实际宽度（原来量 splitter）
    w._apply_col_sizes()
    app.processEvents()
    canvas0 = w.canvas_panel.width()
    tree_w = w.tree_dock.width()
    w.toggle_panel(0)                                   # 收起目录树
    app.processEvents()
    assert not w.tree_dock.isVisible(), "收起后目录树栏应隐藏"
    assert not btns[0].isChecked(), "收起后开关条按钮应取消勾选"
    canvas1 = w.canvas_panel.width()
    assert canvas1 > canvas0, \
        f"收起目录树后画布应变宽：{canvas0} → {canvas1}"
    ok.append(f"收起目录树：画布 {canvas0} → {canvas1} px（+{canvas1 - canvas0}"
              f"，该栏原宽 {tree_w}）")

    w.toggle_panel(1)                                   # 再收起数据栏
    app.processEvents()
    canvas2 = w.canvas_panel.width()
    ok.append(f"再收起数据栏：画布 → {canvas2} px")
    w.toggle_panel(0)
    w.toggle_panel(1)                                   # 都展开回来
    app.processEvents()
    canvas3 = w.canvas_panel.width()
    assert w.tree_dock.isVisible() and w.file_dock.isVisible()
    assert all(b.isChecked() for b in btns), "展开后勾选态应恢复"
    ok.append(f"两栏展开回来：画布 {canvas3} px，三栏宽度 "
              f"{[d.width() for d in w._panel_docks]}")

    # ---------- 3. 宽度记忆（写入 → 新窗口恢复）----------
    s = QSettings(APP_ORG, APP_NAME)
    old_hidden = s.value("ui/panel_hidden", None)
    old_widths = s.value("ui/panel_widths", None)
    try:
        s.setValue("ui/panel_hidden", [0, 1, 0])
        s.setValue("ui/panel_widths", [240, 210, 320])
        s.sync()
        w2 = _make_gui()
        assert w2._col_hidden == [False, True, False], \
            f"折叠状态未恢复：{w2._col_hidden}"
        assert w2._col_widths == [240, 210, 320], \
            f"宽度未恢复：{w2._col_widths}"
        assert not w2.file_dock.isVisible(), "数据栏应保持上次的收起状态"
        assert w2.panel_toggle_btns[1].isChecked() is False, "开关条状态应同步"
        ok.append("宽度记忆：写入 [240,210,320] + 折叠数据栏 → 新窗口原样恢复")
        w2.close()
    finally:
        # 别把用户的真实栏布局改掉
        if old_hidden is None:
            s.remove("ui/panel_hidden")
        else:
            s.setValue("ui/panel_hidden", old_hidden)
        if old_widths is None:
            s.remove("ui/panel_widths")
        else:
            s.setValue("ui/panel_widths", old_widths)
        s.sync()

    # ---------- 4. 文件搜索 ----------
    assert hasattr(w, "file_search_edit"), "数据栏应有搜索框"
    if not os.path.isdir(DATA_DIR):
        print(f"[SKIP] 样例目录不存在：{DATA_DIR}")
    else:
        w.spectrum_type_combo.setCurrentIndex(1)        # 发射模式（见文件头说明）
        app.processEvents()
        w.load_data_from_folder(DATA_DIR)
        app.processEvents()
        total = w.file_list.count()
        if total < 5:
            print(f"[SKIP] 样例目录未加载到足够文件（{total} 个）")
            total = 0
        if total:
            vis0 = len(w._visible_file_items())
            assert vis0 == total, "没输搜索词时不应过滤掉任何文件"
            # 加载时默认全部勾选 → 按钮此时应是「全不选」；先全部取消，回到干净状态
            assert w.file_select_btn.text() == "全不选", \
                f"刚加载时全部勾选，按钮应为「全不选」，实际 {w.file_select_btn.text()!r}"
            w.toggle_select_all_visible()
            app.processEvents()
            assert len(w.get_checked_files()) == 0 and w.file_select_btn.text() == "全选"

            w.file_search_edit.setText("1000")
            app.processEvents()
            shown = len(w._visible_file_items())
            assert 0 < shown < total, f"搜索 “1000” 应过滤出部分文件：{shown}/{total}"
            assert "显示" in w.file_count_label.text(), \
                f"计数标签应提示过滤结果，实际 {w.file_count_label.text()!r}"
            ok.append(f"搜索 “1000”：{total} → 显示 {shown} 个（{w.file_count_label.text()}）")

            # ---------- 5. 全选只作用于筛选结果 ----------
            assert w.file_select_btn.text() == "全选", \
                f"筛选出的都未勾选，按钮应为「全选」，实际 {w.file_select_btn.text()!r}"
            w.toggle_select_all_visible()
            app.processEvents()
            checked = len(w.get_checked_files())
            assert checked == shown, f"全选应只勾选筛选出的 {shown} 个，实际 {checked}"
            assert w.file_select_btn.text() == "全不选", \
                "筛选结果全部勾选后按钮应变为「全不选」"
            w.file_search_edit.setText("")
            app.processEvents()
            assert len(w.get_checked_files()) == checked, \
                "清除搜索词不应改变已勾选的样品（过滤只影响显示）"
            assert w.file_select_btn.text() == "全选", \
                "清除搜索词后仍有未勾选项，按钮应回到「全选」"
            w.toggle_select_all_visible()
            app.processEvents()
            assert len(w.get_checked_files()) == total, \
                f"无筛选时全选应勾上全部 {total} 个"
            ok.append(f"全选：筛选内 {shown} 个 → 清筛选后仍 {checked} 个 → "
                      f"再全选得 {len(w.get_checked_files())}/{total} 个")
            w.toggle_select_all_visible()               # 复原：全部取消勾选
            app.processEvents()

            # ---------- 6. 积分结果表格 ----------
            assert hasattr(w, "integ_table"), "积分结果应为 QTableWidget"
            assert not hasattr(w, "integ_output"), "旧的 QPlainTextEdit 应已被替换"
            w._do_plot()                                # 同步跑一遍绘图+积分
            w._update_integration_output()
            app.processEvents()
            rows = w.integ_table.rowCount()
            n_data = len(w.data_cache)
            assert rows > 0, "积分结果表应有数据行"
            assert rows <= n_data, f"结果行数不应超过样品数：{rows} vs {n_data}"
            assert w.integ_table.columnCount() == 3
            headers = [w.integ_table.horizontalHeaderItem(c).text()
                       for c in range(3)]
            assert headers == ["样品", "区间 (nm)", "积分值"], f"表头异常：{headers}"
            ok.append(f"积分结果表：{rows} 行 × 3 列（表头 {headers}），"
                      f"计数标签「{w.integ_count_label.text()}」")

            # 数值列按数值排序：升序后第一行 ≤ 最后一行
            w.integ_table.sortItems(2, Qt.AscendingOrder)
            app.processEvents()
            v0 = float(w.integ_table.item(0, 2).text())
            v1 = float(w.integ_table.item(rows - 1, 2).text())
            assert v0 <= v1, f"积分值列应按数值排序：首行 {v0} > 末行 {v1}"
            ok.append(f"数值排序生效：升序首行 {v0:.6g} ≤ 末行 {v1:.6g}")

            # 复制（制表符文本）
            tsv = w._integration_tsv()
            assert tsv.count("\n") == rows, "复制文本应为 表头 + N 行"
            assert "\t" in tsv.splitlines()[0], "复制文本应为制表符分隔"

            # 导出 CSV
            tmp = tempfile.mkdtemp(prefix="integ_csv_")
            out = w._export_integration_csv(save_dir=tmp)
            assert out and Path(out).exists(), f"CSV 未生成：{out}"
            raw = Path(out).read_bytes()
            assert raw.startswith(b"\xef\xbb\xbf"), "CSV 应带 UTF-8 BOM（Excel 打开不乱码）"
            lines = Path(out).read_text(encoding="utf-8-sig").strip().splitlines()
            assert len(lines) == rows + 1, f"CSV 应为表头 + {rows} 行，实际 {len(lines)}"
            ok.append(f"导出 CSV：{Path(out).name}（{len(lines)} 行，含 BOM）")

    print("=" * 70)
    for line in ok:
        print("  ✓ " + line)
    print("=" * 70)
    print("BATCH3 SMOKE PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
