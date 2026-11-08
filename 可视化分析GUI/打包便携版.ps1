# ============================================================
#  光谱可视化分析工具 - PyInstaller 打包脚本（单文件可移植 exe）
#  用法：在此目录下执行  powershell -ExecutionPolicy Bypass -File 打包便携版.ps1
#  需要：已安装 PyInstaller（python -m pip install pyinstaller）
# ============================================================

$ErrorActionPreference = "Stop"
$appdir  = $PSScriptRoot                    # 本脚本所在目录（GUI 目录）
$parent  = (Split-Path $appdir -Parent)     # 上级目录（含 plot_absorption.py 等）
$work    = Join-Path $appdir "_packaging\build"
$dist    = Join-Path $appdir "_packaging\dist"
$spec    = Join-Path $appdir "_packaging"
$portable = Join-Path $appdir "便携版"        # 交付目录

Write-Host "=========================================================================="
Write-Host "  打包：光谱可视化分析工具（单文件可移植 exe）"
Write-Host "  程序目录: $appdir"
Write-Host "  依赖模块目录: $parent"
Write-Host "=========================================================================="

foreach ($p in @($work, $dist)) {
    if (Test-Path $p) { Remove-Item -Recurse -Force $p }
}

$excl = @(
    # ---- 本程序用不到的重量级依赖 ----
    "torch","torchvision","tensorflow","sympy","IPython","jedi",
    "lxml","zmq","rich","notebook","ipykernel","nbconvert",
    "nbformat","jupyter_core","prompt_toolkit","matplotlib_inline",
    "ipython_genutils","tkinter",
    "matplotlib.backends.backend_tkagg","matplotlib.backends._tkagg",
    "matplotlib.backends.backend_tk",
    # ---- 测试套件（第三方包的 tests 目录体积不小）----
    "pytest","matplotlib.tests","numpy.tests","pandas.tests","scipy.tests",
    # ---- PyQt5 里用不到的 Qt 模块（体积优化 E4）----
    "PyQt5.QtWebEngineWidgets","PyQt5.QtWebEngineCore","PyQt5.QtWebEngine",
    "PyQt5.QtWebKit","PyQt5.QtWebKitWidgets","PyQt5.QtWebChannel",
    "PyQt5.QtWebSockets","PyQt5.QtQml","PyQt5.QtQuick","PyQt5.QtQuick3D",
    "PyQt5.QtQuickWidgets","PyQt5.Qt3DCore","PyQt5.Qt3DRender",
    "PyQt5.Qt3DInput","PyQt5.Qt3DLogic","PyQt5.Qt3DAnimation",
    "PyQt5.Qt3DExtras","PyQt5.QtMultimedia","PyQt5.QtMultimediaWidgets",
    "PyQt5.QtBluetooth","PyQt5.QtNfc","PyQt5.QtPositioning",
    "PyQt5.QtLocation","PyQt5.QtSensors","PyQt5.QtSerialPort",
    "PyQt5.QtSql","PyQt5.QtTest","PyQt5.QtXmlPatterns","PyQt5.QtHelp",
    "PyQt5.QtDesigner","PyQt5.QtOpenGL","PyQt5.QtDBus",
    "PyQt5.QtNetworkAuth","PyQt5.QtRemoteObjects","PyQt5.QtScript",
    "PyQt5.QtScriptTools","PyQt5.QtTextToSpeech","PyQt5.QtXml"
)

# 应用图标
$icon = Join-Path $appdir "app_icon.ico"
# QSS 小图标目录（预生成的静态 PNG，gui_ui._load_style_icons 通过 resource_path 加载）
$icons_dir = Join-Path $appdir "icons"
# bootloader 启动画面（双击后解压阶段即显示，entry_gui 里经 pyi_splash 交接给 Qt 启动画面）
$splash_img = Join-Path $appdir "splash.png"

$args = @(
    "-m","PyInstaller",
    "--noconfirm","--clean","--onefile","--windowed",
    "--name","SpectralAnalysisTool",
    "--optimize","2",
    "--paths",$parent,
    "--icon",$icon,
    "--add-data",("$icon" + ";."),
    "--add-data",("$icons_dir" + ";icons"),
    "--splash",$splash_img,
    "--splash-center","primary",
    "--hidden-import","plot_absorption",
    "--hidden-import","curve_colors",
    "--hidden-import","plot_emission",
    "--hidden-import","plot_compare",
    "--hidden-import","plot_lifetime",
    "--hidden-import","plot_3d_scan",
    "--hidden-import","read_xlsx_info",
    "--hidden-import","openpyxl",
    "--hidden-import","absorption_gui",
    "--hidden-import","gui_launcher",
    "--hidden-import","gui_splash",
    "--hidden-import","gui_config",
    "--hidden-import","gui_components",
    "--hidden-import","gui_ui",
    "--hidden-import","gui_data",
    "--hidden-import","gui_plot",
    "--hidden-import","gui_i18n",
    "--hidden-import","matplotlib.backends.backend_qt5agg",
    "--hidden-import","matplotlib.backends.backend_qtagg",
    "--workpath",$work,
    "--distpath",$dist,
    "--specpath",$spec
)
foreach ($e in $excl) { $args += @("--exclude-module",$e) }
# 入口：轻量启动脚本（先弹启动画面，再加载重量级依赖，见 entry_gui.py）
$args += (Join-Path $appdir "entry_gui.py")

py -3.11 @args
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "[失败] 打包出错，请查看上方 PyInstaller 错误信息。"
    exit 1
}

New-Item -ItemType Directory -Force -Path $portable | Out-Null
$exe  = Join-Path $dist "SpectralAnalysisTool.exe"
$out  = Join-Path $portable "光谱可视化分析工具.exe"
Copy-Item -Force $exe $out

Write-Host ""
Write-Host "[完成] 打包成功！"
Write-Host "  单文件可移植程序：$out"
Write-Host "  （无需 Python 环境，双击即可运行；首次启动会解压到临时目录，稍慢属正常）"