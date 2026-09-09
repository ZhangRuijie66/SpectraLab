"""
简单的GUI测试程序
用于测试PyQt5是否能正常显示窗口
"""

import sys
from PyQt5.QtWidgets import QApplication, QLabel, QWidget, QVBoxLayout, QPushButton, QMessageBox

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("GUI测试")
    
    # 创建简单窗口
    window = QWidget()
    window.setWindowTitle("PyQt5 测试")
    window.resize(400, 300)
    
    layout = QVBoxLayout()
    
    label = QLabel("如果你能看到这个窗口，说明PyQt5工作正常！")
    label.setStyleSheet("font-size: 18px; font-weight: bold; color: green;")
    
    btn = QPushButton("点击测试")
    btn.setStyleSheet("font-size: 14px; padding: 10px;")
    btn.clicked.connect(lambda: QMessageBox.information(window, "测试", "按钮工作正常！"))
    
    layout.addWidget(label)
    layout.addWidget(btn)
    window.setLayout(layout)
    
    window.show()
    
    print("GUI窗口已创建，请检查是否可见")
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()