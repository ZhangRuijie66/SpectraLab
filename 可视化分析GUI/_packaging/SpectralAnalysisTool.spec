# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['D:/北大/QLS Lab/SPC/1O2+luminol/谱图/光谱/画图/可视化分析GUI/entry_gui.py'],
    pathex=['D:/北大/QLS Lab/SPC/1O2+luminol/谱图/光谱/画图'],
    binaries=[],
    datas=[('D:/北大/QLS Lab/SPC/1O2+luminol/谱图/光谱/画图/可视化分析GUI/app_icon.ico', '.'), ('D:/北大/QLS Lab/SPC/1O2+luminol/谱图/光谱/画图/可视化分析GUI/icons', 'icons')],
    hiddenimports=['plot_absorption', 'curve_colors', 'plot_emission', 'plot_lifetime', 'plot_3d_scan', 'read_xlsx_info', 'openpyxl', 'absorption_gui', 'gui_launcher', 'gui_splash', 'gui_config', 'gui_components', 'gui_ui', 'gui_data', 'gui_plot', 'matplotlib.backends.backend_qt5agg', 'matplotlib.backends.backend_qtagg'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['torch', 'torchvision', 'tensorflow', 'sympy', 'IPython', 'jedi', 'lxml', 'zmq', 'rich', 'notebook', 'ipykernel', 'nbconvert', 'nbformat', 'jupyter_core', 'prompt_toolkit', 'matplotlib_inline', 'ipython_genutils', 'tkinter', 'matplotlib.backends.backend_tkagg', 'matplotlib.backends._tkagg', 'matplotlib.backends.backend_tk', 'pytest', 'matplotlib.tests', 'numpy.tests', 'pandas.tests', 'scipy.tests', 'PyQt5.QtWebEngineWidgets', 'PyQt5.QtWebEngineCore', 'PyQt5.QtWebEngine', 'PyQt5.QtWebKit', 'PyQt5.QtWebKitWidgets', 'PyQt5.QtWebChannel', 'PyQt5.QtWebSockets', 'PyQt5.QtQml', 'PyQt5.QtQuick', 'PyQt5.QtQuick3D', 'PyQt5.QtQuickWidgets', 'PyQt5.Qt3DCore', 'PyQt5.Qt3DRender', 'PyQt5.Qt3DInput', 'PyQt5.Qt3DLogic', 'PyQt5.Qt3DAnimation', 'PyQt5.Qt3DExtras', 'PyQt5.QtMultimedia', 'PyQt5.QtMultimediaWidgets', 'PyQt5.QtBluetooth', 'PyQt5.QtNfc', 'PyQt5.QtPositioning', 'PyQt5.QtLocation', 'PyQt5.QtSensors', 'PyQt5.QtSerialPort', 'PyQt5.QtSql', 'PyQt5.QtTest', 'PyQt5.QtXmlPatterns', 'PyQt5.QtHelp', 'PyQt5.QtDesigner', 'PyQt5.QtOpenGL', 'PyQt5.QtDBus', 'PyQt5.QtNetworkAuth', 'PyQt5.QtRemoteObjects', 'PyQt5.QtScript', 'PyQt5.QtScriptTools', 'PyQt5.QtTextToSpeech', 'PyQt5.QtXml'],
    noarchive=False,
    optimize=2,
)
pyz = PYZ(a.pure)
splash = Splash(
    'D:/北大/QLS Lab/SPC/1O2+luminol/谱图/光谱/画图/可视化分析GUI/splash.png',
    binaries=a.binaries,
    datas=a.datas,
    text_pos=None,
    text_size=12,
    minify_script=True,
    always_on_top=True,
    center='primary',
)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    splash,
    splash.binaries,
    [('O', None, 'OPTION'), ('O', None, 'OPTION')],
    name='SpectralAnalysisTool',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['D:/北大/QLS Lab/SPC/1O2+luminol/谱图/光谱/画图/可视化分析GUI/app_icon.ico'],
)
