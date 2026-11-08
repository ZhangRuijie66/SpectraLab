# -*- coding: utf-8 -*-
"""把 Qt 内置的英文标准按钮译成中文（v5.0.5）。

为什么需要它
------------
程序界面全中文，但所有系统级按钮是英文：确认框是 ``&Yes`` / ``&No``
（还带 Windows 助记符 ``&``），错误框是 ``OK`` / ``Cancel``。
用户在「拟合尚未完成，关闭窗口将中止本次拟合并放弃本次结果。确定关闭？」
下面看到的却是两个英文按钮。

根因：``QLocale.system()`` 虽然是 ``zh_CN``，但 PyQt5 wheel **只带
``qtbase_zh_TW.qm``（繁体）、不带 ``qtbase_zh_CN.qm``**，所以
``QApplication.translate("QPlatformTheme", "OK")`` 原样返回 ``'OK'``。
而 ``QFileDialog`` 走系统原生对话框（中文），于是同一个程序里
**文件框中文、确认框英文**，割裂感更明显。

为什么用自定义 translator 而不是改调用点
----------------------------------------
全项目有 53 处 ``QMessageBox.*`` 调用。逐个改成 ``addButton("确定")``
不仅改动面大，还要为每处想一个合适的按钮文字、处理默认按钮与返回值。
装一个 ``QTranslator`` 只需一处代码，且**所有**标准按钮（含
``QDialogButtonBox``、``QFileDialog`` 非原生模式、未来的新调用点）一起生效。

实测（``probe_translator.py``）：

    装之前  Ok+Cancel → ['OK', 'Cancel']     Yes+No → ['&Yes', '&No']
    装之后  Ok+Cancel → ['确定', '取消']     Yes+No → ['是(&Y)', '否(&N)']

不译的文本原样返回（返回空串 = 让 Qt 回退到原文），所以
「自定义按钮」「Process」「Export」这类文字不受影响。
"""

from PyQt5.QtCore import QTranslator


class ZhStandardButtons(QTranslator):
    """标准按钮中文翻译器。

    只覆盖 Qt 内置的标准按钮文本。命中就返回中文、**不命中返回空串**
    （``QTranslator`` 的约定：空串表示"我没译，走原逻辑"），
    所以不会误伤任何自定义文字。
    """

    # 键是 Qt 源码里的原文（含 ``&`` 助记符的两种形态都要列）
    TABLE = {
        # QPlatformTheme 标准按钮
        'OK': '确定',
        'Ok': '确定',
        '&OK': '确定(&O)',
        'Cancel': '取消',
        '&Cancel': '取消(&C)',
        'Yes': '是',
        '&Yes': '是(&Y)',
        'No': '否',
        '&No': '否(&N)',
        'Save': '保存',
        '&Save': '保存(&S)',
        'Discard': '放弃',
        '&Discard': '放弃(&D)',
        'Close': '关闭',
        '&Close': '关闭(&C)',
        'Apply': '应用',
        '&Apply': '应用(&A)',
        'Reset': '重置',
        '&Reset': '重置(&R)',
        'Restore Defaults': '恢复默认值',
        'Help': '帮助',
        '&Help': '帮助(&H)',
        'Abort': '中止',
        '&Abort': '中止(&A)',
        'Retry': '重试',
        '&Retry': '重试(&R)',
        'Ignore': '忽略',
        '&Ignore': '忽略(&I)',
        # 常见文件对话框按钮（非原生模式下会用到）
        'Open': '打开',
        '&Open': '打开(&O)',
        'Save As': '另存为',
        '&Save As': '另存为(&A)',
        # 常见对话框标题/内建提示
        'Error': '错误',
        'Warning': '警告',
        'Question': '确认',
        'Information': '提示',
    }

    def translate(self, context, source, disambiguation=None, n=-1):
        """context/source 来自 Qt；只按 source 原文查表。"""
        try:
            hit = self.TABLE.get(source)
            if hit is not None:
                return hit
        except Exception:
            pass
        return ''            # 空串 = 未翻译，Qt 会回退到原文


def install_zh_standard_buttons(app):
    """给 QApplication 装上中文按钮翻译器，返回持引用用的 translator。

    **返回值必须由调用方保存**（例如挂到 ``app._zh_translator``）：
    ``QApplication`` 不持有 translator 的所有权，Python 侧被 GC 掉之后
    按钮文字会退回英文。

    重复调用是安全的：已装过同一个实例就不再重复安装。
    """
    if app is None:
        return None
    existing = getattr(app, '_zh_standard_buttons', None)
    if existing is not None:
        return existing
    try:
        tr = ZhStandardButtons()
        app.installTranslator(tr)
        # installTranslator 的返回值表示"是否从翻译文件加载了语言元数据"，
        # 内存里的 translator 一律返回 False——这不代表安装失败。
        app._zh_standard_buttons = tr        # 防 GC
        return tr
    except Exception:
        return None
