from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QDialog, QVBoxLayout, QLabel, QApplication

class HotkeyCapture:
    def __init__(self, parent_dialog):
        self.dialog = QDialog(parent_dialog)
        self.dialog.setWindowTitle('按下快捷键')
        self.dialog.setFixedSize(350, 120)
        self.dialog.setWindowFlags(Qt.Dialog | Qt.WindowStaysOnTopHint)
        layout = QVBoxLayout()
        label = QLabel('请按下您想要设置的快捷键组合\n(支持 Ctrl、Shift、Alt + 字母/数字/符号)')
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet('font-size: 12px; padding: 10px;')
        layout.addWidget(label)
        self.dialog.setLayout(layout)
        self.dialog.keyPressEvent = self._capture_key_press
        self.new_hotkey = None

    def _capture_key_press(self, event):
        modifiers = []
        if event.modifiers() & Qt.ControlModifier:
            modifiers.append('Ctrl')
        if event.modifiers() & Qt.ShiftModifier:
            modifiers.append('Shift')
        if event.modifiers() & Qt.AltModifier:
            modifiers.append('Alt')
        key_text = event.text()
        if not key_text and event.key() != Qt.Key_unknown:
            key_map = {
                Qt.Key_Space: 'Space',
                Qt.Key_Return: 'Return',
                Qt.Key_Enter: 'Enter',
                Qt.Key_Tab: 'Tab',
                Qt.Key_Escape: 'Escape',
                Qt.Key_F1: 'F1', Qt.Key_F2: 'F2', Qt.Key_F3: 'F3', Qt.Key_F4: 'F4',
                Qt.Key_F5: 'F5', Qt.Key_F6: 'F6', Qt.Key_F7: 'F7', Qt.Key_F8: 'F8',
                Qt.Key_F9: 'F9', Qt.Key_F10: 'F10', Qt.Key_F11: 'F11', Qt.Key_F12: 'F12',
                Qt.Key_Period: '.', Qt.Key_Comma: ','
            }
            key_text = key_map.get(event.key(), '')
        if key_text or event.key() in [Qt.Key_Period, Qt.Key_Comma]:
            if not modifiers:
                return
            if event.key() == Qt.Key_Period:
                key_text = '.'
            elif event.key() == Qt.Key_Comma:
                key_text = ','
            hotkey_parts = modifiers + [key_text]
            self.new_hotkey = '+'.join(hotkey_parts)
            self.dialog.accept()

    @staticmethod
    def capture(parent_dialog):
        cap = HotkeyCapture(parent_dialog)
        screen = QApplication.primaryScreen().geometry()
        cap.dialog.move(
            (screen.width() - cap.dialog.width()) // 2,
            (screen.height() - cap.dialog.height()) // 2
        )
        cap.dialog.exec_()
        return cap.new_hotkey
