from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QTextEdit
from PyQt5.QtGui import QFont

class TextBubble:
    @staticmethod
    def build(parent, color: str, font_size: int, width: int, opacity: float, ball_diameter: int, text: str):
        widget = QWidget(parent)
        widget.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        widget.setAttribute(Qt.WA_TranslucentBackground)
        widget.setWindowOpacity(opacity)
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # 允许通过点击展开，所以这里不完全禁用交互
        # 但我们用一个自定义的 TextEdit 来处理滚轮事件
        from ui.floating_ball import ClickableTextEdit
        text_edit = ClickableTextEdit(parent_ball=parent) # 传入父对象以便回调
        text_edit.setReadOnly(True)
        bg_color = 'rgba(0, 0, 0, 150)' if color == 'black' else 'rgba(255, 255, 255, 150)'
        text_color = 'white' if color == 'black' else 'black'
        text_edit.setStyleSheet(f"background-color: {bg_color}; color: {text_color}; border: none;")
        font = QFont()
        font.setPointSize(font_size)
        text_edit.setFont(font)
        text_edit.setFixedWidth(width)
        
        # 初始高度
        text_height = int(ball_diameter * 3 / 4)
        text_edit.setFixedHeight(text_height)
        
        # 隐藏滚动条但保留功能
        text_edit.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        text_edit.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        text_edit.setTextInteractionFlags(Qt.TextSelectableByMouse)
        text_edit.setPlainText(text)
        layout.addWidget(text_edit)
        widget.setLayout(layout)
        
        # 添加关闭按钮
        from PyQt5.QtWidgets import QPushButton
        close_btn = QPushButton("×", widget)
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: gray;
                border: none;
                font-size: 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                color: red;
            }
        """)
        close_btn.setFixedSize(20, 20)
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.clicked.connect(lambda: widget.close())
        close_btn.move(width - 25, 5)
        
        # 保存 widget 到 text_edit 以便后续调整大小
        text_edit.parent_widget = widget
        text_edit.close_btn = close_btn
        
        return widget, text_edit
