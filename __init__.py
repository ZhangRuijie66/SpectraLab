# -*- coding: utf-8 -*-
"""
光谱绘图工具包 — 统一导出接口
===============================
导入示例：
    from 画图 import plot_spectra, load_spectra          # 发射光谱
    from 画图 import parse_3d_scan_csv, plot_3d_surface   # 3D 扫描
    from 画图 import analyze_zn_rb_folder, read_zn_info   # Zn+RB 分析
    from 画图 import plot_absorption_spectra, load_absorption_spectra  # 吸收光谱
"""

from plot_emission import (
    setup_chinese_font,
    clean_array,
    detect_format,
    parse_rf6000_csv,
    parse_spectracle_csv,
    parse_csv,
    load_spectra,
    plot_single,
    plot_combined,
    plot_spectra,
)

from plot_3d_scan import (
    parse_3d_scan_csv,
    plot_3d_surface,
    plot_contour,
    plot_waterfall,
)

from plot_zn_rb_analysis import (
    read_zn_info,
    load_emission_datasets,
    find_main_peak,
    find_aux_peaks,
    plot_individual,
    plot_combined_zoom,
    export_peak_table,
    plot_rb_normalized_concentration,
    analyze_zn_rb_folder,
)

from plot_absorption import (
    setup_chinese_font as setup_chinese_font_abs,
    clean_array as clean_array_abs,
    detect_absorption_format,
    parse_absorption_csv,
    parse_uvvis_csv,
    load_absorption_spectra,
    plot_single_absorption,
    plot_combined_absorption,
    plot_absorption_spectra,
    find_absorption_peaks,
    calculate_absorption_coefficient,
)

from read_xlsx_info import (
    load_xlsx_info,
    match_number,
    format_info,
    build_enriched_label,
    enrich_label_from_name,
    parse_spectrum_xlsx,
    clean_xlsx_column_label,
)

__all__ = [
    # plot_emission
    'setup_chinese_font',
    'clean_array',
    'detect_format',
    'parse_rf6000_csv',
    'parse_spectracle_csv',
    'parse_csv',
    'load_spectra',
    'plot_single',
    'plot_combined',
    'plot_spectra',
    # plot_3d_scan
    'parse_3d_scan_csv',
    'plot_3d_surface',
    'plot_contour',
    'plot_waterfall',
    # plot_zn_rb_analysis
    'read_zn_info',
    'load_emission_datasets',
    'find_main_peak',
    'find_aux_peaks',
    'plot_individual',
    'plot_combined_zoom',
    'export_peak_table',
    'plot_rb_normalized_concentration',
    'analyze_zn_rb_folder',
    # plot_absorption
    'setup_chinese_font_abs',
    'clean_array_abs',
    'detect_absorption_format',
    'parse_absorption_csv',
    'parse_uvvis_csv',
    'load_absorption_spectra',
    'plot_single_absorption',
    'plot_combined_absorption',
    'plot_absorption_spectra',
    'find_absorption_peaks',
    'calculate_absorption_coefficient',
    # read_xlsx_info
    'load_xlsx_info',
    'match_number',
    'format_info',
    'build_enriched_label',
    'enrich_label_from_name',
    'parse_spectrum_xlsx',
    'clean_xlsx_column_label',
]
