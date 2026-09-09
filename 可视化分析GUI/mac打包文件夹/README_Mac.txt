macOS 可移植版打包说明（v4.6，自包含文件夹）
==============================================

这个文件夹是【自包含】的：包含光谱可视化分析工具 v4.6 的全部源码与资源，
整个文件夹拷贝到 Mac 即可打包，不依赖 Windows 机器上的任何其他文件。

【本版内容 —— 与 Windows 便携版 v4.6 功能一致】
  * 吸收光谱 / 发射光谱 / 荧光寿命（MEM+IRF）三种模式
  * 模块选择入口（启动时弹窗选择）+ 主窗口「返回模块选择」循环
  * 说明.xlsx 样品信息读取（自动增强图例标签）
  * macOS 中文字体已适配：界面用苹方（PingFang SC），
    图表按 PingFang SC / Hiragino Sans GB / Songti SC 顺序挑选

【文件夹内容】
  absorption_gui.py      主程序入口（含 launcher 循环，打包入口脚本）
  gui_config.py          全局常量（版本号、平台感知字体/工作区）
  gui_components.py      自定义控件与资源定位
  gui_data.py            数据加载混入
  gui_ui.py              界面混入
  gui_plot.py            绘图混入（后台线程计算）
  gui_launcher.py        模块选择入口对话框
  gui_splash.py          启动画面
  plot_absorption.py     吸收光谱绘图模块
  plot_emission.py       发射光谱绘图模块
  plot_lifetime.py       荧光寿命拟合模块（MEM + IRF，Horiba/DeltaHub CSV）
  read_xlsx_info.py      说明.xlsx 样品信息读取（需 openpyxl，脚本已装）
  app_icon.ico/.png      程序图标（PNG 供打包时转 macOS .icns）
  splash.png             启动画面配图
  icons/                 界面小图标（排序箭头等）
  build_mac.command      一键打包脚本（纯 ASCII，不会中文乱码）
  README_Mac.txt         本说明

【为什么脚本是纯英文的】
之前脚本里有中文，在某些 Mac 终端（非 UTF-8 环境）里中文变成 "?" 导致执行出错。
现在的 build_mac.command 全部 ASCII、开头强制 UTF-8 locale（LANG/LC_ALL/LC_CTYPE
和 PYTHONUTF8）、LF 换行无 BOM，保证任何终端都能正确执行。

【在 Mac 上打包（三步）】
1) 把整个本文件夹拷到 Mac（例如桌面）。
2) 打开「终端」，进入该文件夹：
     cd ~/Desktop/mac打包文件夹
   如果双击 build_mac.command 没反应，先执行一次赋予可执行权限：
     chmod +x build_mac.command
3) 运行：
     bash build_mac.command
   脚本会自动：创建 .venv_mac 虚拟环境 → 安装 PyQt5 / matplotlib / scipy /
   pandas / numpy / openpyxl / pyinstaller → 生成 .icns 图标 → PyInstaller 打包
   → ad-hoc 签名（Apple Silicon 必须）→ 去隔离属性。
   需要 python3（一般装 Xcode Command Line Tools 即可：xcode-select --install）。
   全程约 5–10 分钟（视网速）。

【打包结果】
文件夹里生成：  portable_mac/SpectralAnalysisTool.app
- 把整个 SpectralAnalysisTool.app 拷到任何 Mac（同架构）双击即用，无需装 Python。
- 想要中文名：在 Finder 里直接重命名 .app 即可。
- 首次启动会建 matplotlib 字体缓存，等几秒属正常。

【注意事项】
- 默认打出打包机自己架构的包（Apple Silicon 或 Intel）。
  要 Intel + Apple Silicon 通用版，需在通用版 Python 环境下打包，脚本命令里加：
    --target-architecture universal2
  （通用版体积翻倍；一般只打自己机器架构即可。）
- 默认工作区：Windows 上的 D:\... 路径在 Mac 上不存在，程序会自动回退到
  「文稿」（Documents），在界面里可自行切换并记住。
- 首次打开 .app 若提示「无法打开/已损坏」：右键 .app → 打开；或在
  系统设置 → 隐私与安全性 里允许。（脚本已做 codesign ad-hoc + xattr 去隔离。）

【同步维护提醒】
本文件夹里的源码是 Windows 主目录的快照。以后 GUI 升级版本时，需要把改过的
.py 文件重新拷贝进来（或在打包前同步），保持两边一致。
