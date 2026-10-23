import keyboard
import threading
import time
from PyQt5.QtCore import Qt, QTimer, QPoint, QRect, pyqtSignal
from PyQt5.QtGui import QFont, QColor, QPainter, QPen, QCursor, QRegion, QKeySequence, QFontMetrics
from PyQt5.QtWidgets import QWidget, QTextEdit, QVBoxLayout, QMenu, QAction, QDialog, QFormLayout, QSpinBox, QSlider, QComboBox, QPushButton, QShortcut, QLabel, QCheckBox, QApplication, QTabWidget, QGroupBox, QHBoxLayout
from config.settings import read_settings, write_settings, get_settings_path
from services.baidu_asr import recognize_pcm
from audio.recorder import record_pcm_realtime
from ui.tool_manager import ToolManagerDialog

class ClickableTextEdit(QTextEdit):
    def __init__(self, parent=None, parent_ball=None):
        super().__init__(parent)
        self.parent_ball = parent_ball
        self.is_expanded = False
        self.parent_widget = None
        self.close_btn = None
        self.original_height = 0

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            # 记录初始高度，如果还没记录过
            if self.original_height == 0 and self.height() > 0:
                 self.original_height = self.height()
                 
            self.toggle_expand()
        
        super().mousePressEvent(event)

    def toggle_expand(self):
        if not self.parent_widget or not self.parent_ball:
            return

        self.is_expanded = not self.is_expanded
        
        # 重新获取文本和计算完整高度
        text = self.toPlainText()
        font_metrics = self.fontMetrics()
        # 增加一些 padding 防止底部被切断
        full_height = font_metrics.boundingRect(0, 0, self.width(), 10000, Qt.TextWordWrap, text).height() + 40
        
        # 限制最大高度，防止超出屏幕
        screen_height = QApplication.primaryScreen().geometry().height()
        max_height = int(screen_height * 0.6)
        
        # 如果当前高度是原始高度，且文本本来就很短，就不需要展开
        if not self.is_expanded:
             # 恢复逻辑
             target_height = self.original_height
             self.parent_ball.scroll_timer.start(50) # 恢复自动滚动
             self.parent_ball.auto_hide_timer.start(3000) # 恢复自动隐藏
             self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        else:
             # 展开逻辑
             target_height = min(full_height, max_height)
             # 如果文本比原始高度还短，就不需要展开
             if target_height <= self.original_height:
                 self.is_expanded = False
                 return
                 
             self.parent_ball.scroll_timer.stop() # 停止自动滚动
             self.parent_ball.auto_hide_timer.stop() # 停止自动隐藏
             self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        # 应用高度
        self.setFixedHeight(target_height)
        self.parent_widget.setFixedHeight(target_height)
        
        # 调整关闭按钮位置
        if self.close_btn:
            self.close_btn.move(self.width() - 25, 5)
            self.close_btn.raise_() # 确保按钮在最上层

        # 调整气泡位置，确保不超出屏幕
        self.parent_ball.update_text_position()

    def wheelEvent(self, event):
        # 滚轮事件触发时，停止自动滚动和自动隐藏
        if self.parent_ball:
            self.parent_ball.scroll_timer.stop()
            self.parent_ball.auto_hide_timer.stop()
        super().wheelEvent(event)

class FloatingBall(QWidget):
    recognition_finished = pyqtSignal(str)
    hotkey_triggered = pyqtSignal()
    stop_hotkey_triggered = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.config_file = get_settings_path()
        s = read_settings()
        self.ball_diameter = s['ball_diameter']
        self.opacity = s['opacity']
        self.color = s['color']
        self.font_size = s['font_size']
        self.ball_x = s['ball_x']
        self.ball_y = s['ball_y']
        self.hotkey = s['hotkey']
        self.stop_hotkey = s.get('stop_hotkey', 'Ctrl+Shift+.')
        self.hover_enabled = s['hover_enabled']
        self.hover_delay = s['hover_delay']
        self.init_ui()
        self.m_drag = False
        self.m_drag_position = QPoint()
        self.text_window = None
        self.scroll_timer = QTimer(self)
        self.scroll_timer.timeout.connect(self.scroll_text)
        self.scroll_position = 0
        self.screen = QApplication.primaryScreen().geometry()
        self.setWindowOpacity(self.opacity)
        self.text_width = 400
        self.is_recording = False
        self.is_connecting = True  # 新增：是否正在连接后端
        self.is_recognizing = False # 新增：是否正在识别中
        self.recording_thread = None
        self.hotkey_handle = None
        self.stop_hotkey_handle = None
        self.stop_recording_event = None
        self.audio_data = None
        self.recording_start_time = None
        self.skip_recognition = False
        self.default_ball_text = "MCP正在连接" # 初始状态
        self.ball_text = self.default_ball_text
        self.ball_text_scroll_timer = QTimer(self)
        self.ball_text_scroll_timer.timeout.connect(self.scroll_ball_text)
        self.ball_text_scroll_position = 0
        self.ball_text_effect_timer = QTimer(self)
        self.ball_text_effect_timer.timeout.connect(self.update_ball_text_effect)
        self.ball_text_segments = []
        self.fade_opacity = 1.0
        self.fade_phase = 'hold'
        self.fade_index = 0
        self.fade_hold_ms = 800
        self.fade_elapsed_ms = 0
        self.auto_hide_timer = QTimer(self)
        self.auto_hide_timer.timeout.connect(self.hide_text_window)
        self.auto_hide_timer.setSingleShot(True)
        self.hover_timer = QTimer(self)
        self.hover_timer.timeout.connect(self.on_hover_timeout)
        self.hover_timer.setSingleShot(True)
        self.is_hovering = False
        self.set_position()
        self.setup_hotkey()
        self.recognition_finished.connect(self.on_recognition_finished)
        self.hotkey_triggered.connect(self.handle_hotkey)
        self.stop_hotkey_triggered.connect(self.stop_backend_processing)

    def init_ui(self):
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(self.ball_diameter, self.ball_diameter)
        self.setMask(QRegion(QRect(0, 0, self.ball_diameter, self.ball_diameter), QRegion.Ellipse))

    def show_context_menu(self, position):
        self.hover_timer.stop()
        self.is_hovering = False
        menu = QMenu()
        
        # 1. 停止运行 (强制显示，但可能禁用)
        stop_action = QAction('停止运行', self)
        # 检查是否正在运行
        is_running = False
        
        # 获取 app 实例中的 worker
        app = QApplication.instance()
        if hasattr(app, 'worker') and app.worker and app.worker.is_processing:
            is_running = True
        
        # 备用检查：尝试通过 parent 获取
        if not is_running and self.parent() and hasattr(self.parent(), 'worker') and self.parent().worker.is_processing:
            is_running = True
            
        stop_action.triggered.connect(self.stop_backend_processing)
        if not is_running:
            stop_action.setEnabled(False)
            stop_action.setText('停止运行 (未运行)')
        
        menu.addAction(stop_action)
        menu.addSeparator()

        settings_action = QAction('设置', self)
        settings_action.triggered.connect(self.show_settings_dialog)
        
        tool_action = QAction('新增工具', self)
        tool_action.triggered.connect(self.show_tool_manager)
        
        exit_action = QAction('退出', self)
        exit_action.triggered.connect(QApplication.quit)
        
        menu.addAction(settings_action)
        menu.addAction(tool_action)
        menu.addSeparator()
        menu.addAction(exit_action)
        
        # Style the menu
        menu.setStyleSheet("""
            QMenu {
                background-color: white;
                border: 1px solid #ccc;
                border-radius: 5px;
                padding: 5px;
            }
            QMenu::item {
                padding: 8px 25px;
                border-radius: 3px;
            }
            QMenu::item:selected {
                background-color: #0078D4;
                color: white;
            }
        """)
        menu.exec_(position)

    def stop_backend_processing(self):
        """手动停止后端处理"""
        # 尝试通过 parent 获取 worker
        worker = None
        if self.parent() and hasattr(self.parent(), 'worker'):
            worker = self.parent().worker
        
        # 尝试通过 app 获取 worker
        if not worker:
            app = QApplication.instance()
            if hasattr(app, 'worker'):
                worker = app.worker
                
        if worker and worker.is_processing:
            worker.stop_processing()
            # 1. 气泡展示
            self.show_text_window("手动停止运行成功")
            # 2. 悬浮球文字展示
            self.set_ball_text("已停止", enable_scroll=False)
            # 3. 2秒后恢复默认表情
            QTimer.singleShot(2000, self.reset_ball_text)

    def show_tool_manager(self):
        dialog = ToolManagerDialog(self)
        if dialog.exec_() == QDialog.Accepted:
             # 设置为连接状态
             self.is_connecting = True
             self.default_ball_text = "MCP正在连接"
             self.reset_ball_text()
             
             self.show_text_window("正在尝试连接MCP服务端...")
             # 触发重新连接信号或逻辑，这里需要与 UI_main.py 配合
             # 我们可以发送一个自定义信号给 UI_main
             if self.parent() and hasattr(self.parent(), 'restart_backend'):
                 self.parent().restart_backend()
             elif QApplication.instance() and hasattr(QApplication.instance(), 'restart_backend'):
                 QApplication.instance().restart_backend()

    def show_settings_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('设置')
        dialog.setMinimumWidth(550)
        dialog.setMinimumHeight(450)
        
        main_layout = QVBoxLayout(dialog)
        tab_widget = QTabWidget()
        
        # --- Appearance Tab ---
        appearance_tab = QWidget()
        app_layout = QFormLayout(appearance_tab)
        app_layout.setSpacing(20)
        app_layout.setContentsMargins(25, 25, 25, 25)
        
        size_spin = QSpinBox()
        size_spin.setRange(50, 300)
        size_spin.setValue(self.ball_diameter)
        size_spin.setMinimumHeight(35)
        size_spin.valueChanged.connect(lambda value: self.apply_settings(value, self.opacity, self.color, self.font_size))
        app_layout.addRow('悬浮球大小:', size_spin)
        
        opacity_slider = QSlider(Qt.Horizontal)
        opacity_slider.setRange(1, 100)
        opacity_slider.setValue(int(self.opacity * 100))
        opacity_slider.setMinimumHeight(35)
        opacity_slider.valueChanged.connect(lambda value: self.apply_settings(self.ball_diameter, value / 100.0, self.color, self.font_size))
        app_layout.addRow('不透明度:', opacity_slider)
        
        color_combo = QComboBox()
        color_combo.addItems(['black', 'white'])
        color_combo.setCurrentText(self.color)
        color_combo.setMinimumHeight(35)
        color_combo.currentTextChanged.connect(lambda text: self.apply_settings(self.ball_diameter, self.opacity, text, self.font_size))
        app_layout.addRow('主题颜色:', color_combo)
        
        font_spin = QSpinBox()
        font_spin.setRange(8, 24)
        font_spin.setValue(self.font_size)
        font_spin.setMinimumHeight(35)
        font_spin.valueChanged.connect(lambda value: self.apply_settings(self.ball_diameter, self.opacity, self.color, value))
        app_layout.addRow('字体大小:', font_spin)
        
        tab_widget.addTab(appearance_tab, "外观")
        
        # --- Interaction Tab ---
        interaction_tab = QWidget()
        int_layout = QFormLayout(interaction_tab)
        int_layout.setSpacing(20)
        int_layout.setContentsMargins(25, 25, 25, 25)
        
        hover_checkbox = QCheckBox("启用鼠标悬停弹窗")
        hover_checkbox.setChecked(self.hover_enabled)
        hover_checkbox.setMinimumHeight(30)
        hover_checkbox.toggled.connect(lambda checked: self.set_hover_config(checked, self.hover_delay))
        int_layout.addRow(hover_checkbox)
        
        hover_delay_spin = QSpinBox()
        hover_delay_spin.setRange(200, 5000)
        hover_delay_spin.setValue(self.hover_delay)
        hover_delay_spin.setSuffix(" ms")
        hover_delay_spin.setMinimumHeight(35)
        hover_delay_spin.valueChanged.connect(lambda value: self.set_hover_config(self.hover_enabled, value))
        int_layout.addRow('悬停触发延时:', hover_delay_spin)
        
        tab_widget.addTab(interaction_tab, "交互")
        
        # --- Hotkey Tab ---
        hotkey_tab = QWidget()
        hotkey_layout = QVBoxLayout(hotkey_tab)
        hotkey_layout.setSpacing(20)
        hotkey_layout.setContentsMargins(25, 25, 25, 25)
        
        # --- 唤醒/录音快捷键 ---
        wake_hotkey_group = QGroupBox("唤醒/录音 快捷键")
        wake_layout = QVBoxLayout(wake_hotkey_group)
        wake_layout.setContentsMargins(15, 25, 15, 15)
        
        self.current_hotkey_label_widget = QLabel(f'{self.hotkey}')
        self.current_hotkey_label_widget.setAlignment(Qt.AlignCenter)
        self.current_hotkey_label_widget.setStyleSheet("font-size: 32px; font-weight: bold; color: #333;")
        wake_layout.addWidget(self.current_hotkey_label_widget)
        
        self.wake_hotkey_capture_btn = QPushButton('点击修改')
        self.wake_hotkey_capture_btn.setMinimumHeight(40)
        self.wake_hotkey_capture_btn.setCursor(Qt.PointingHandCursor)
        self.wake_hotkey_capture_btn.clicked.connect(lambda: self.start_hotkey_capture(dialog, 'wake'))
        wake_layout.addWidget(self.wake_hotkey_capture_btn)
        
        hotkey_layout.addWidget(wake_hotkey_group)
        
        # --- 停止运行快捷键 ---
        stop_hotkey_group = QGroupBox("停止运行 快捷键")
        stop_layout = QVBoxLayout(stop_hotkey_group)
        stop_layout.setContentsMargins(15, 25, 15, 15)
        
        self.current_stop_hotkey_label = QLabel(f'{self.stop_hotkey}')
        self.current_stop_hotkey_label.setAlignment(Qt.AlignCenter)
        self.current_stop_hotkey_label.setStyleSheet("font-size: 32px; font-weight: bold; color: #333;")
        stop_layout.addWidget(self.current_stop_hotkey_label)
        
        self.stop_hotkey_capture_btn = QPushButton('点击修改')
        self.stop_hotkey_capture_btn.setMinimumHeight(40)
        self.stop_hotkey_capture_btn.setCursor(Qt.PointingHandCursor)
        self.stop_hotkey_capture_btn.clicked.connect(lambda: self.start_hotkey_capture(dialog, 'stop'))
        stop_layout.addWidget(self.stop_hotkey_capture_btn)
        
        hotkey_layout.addWidget(stop_hotkey_group)
        
        # --- 捕获状态提示 ---
        self.captured_hotkey_label = QLabel('')
        self.captured_hotkey_label.setAlignment(Qt.AlignCenter)
        self.captured_hotkey_label.setStyleSheet('color: #666; font-style: italic; margin: 10px; font-size: 20px;')
        hotkey_layout.addWidget(self.captured_hotkey_label)

        hotkey_layout.addStretch()
        
        tab_widget.addTab(hotkey_tab, "快捷键")
        
        main_layout.addWidget(tab_widget)
        
        # Global Stylesheet for Dialog
        dialog.setStyleSheet("""
            QDialog {
                background-color: #f0f0f0;
                font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
            }
            QTabWidget::pane {
                border: 1px solid #ccc;
                background-color: white;
                border-radius: 6px;
            }
            QTabBar::tab {
                background: #e0e0e0;
                padding: 15px 35px;
                margin-right: 4px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                font-size: 25px;
            }
            QTabBar::tab:selected {
                background: white;
                border-bottom: 3px solid #0078D4;
                font-weight: bold;
            }
            QGroupBox {
                font-weight: bold;
                border: 1px solid #ddd;
                border-radius: 8px;
                margin-top: 25px;
                font-size: 25px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 5px;
                color: #333;
            }
            QLabel {
                font-size: 25px;
            }
            QSpinBox, QComboBox {
                font-size: 25px;
                padding: 5px;
                border: 1px solid #ccc;
                border-radius: 4px;
            }
            QCheckBox {
                font-size: 25px;
            }
            QPushButton {
                border: 1px solid #ccc;
                border-radius: 6px;
                background-color: #f8f8f8;
                font-size: 25px;
            }
            QPushButton:hover {
                background-color: #e8e8e8;
            }
        """)
        
        self.settings_dialog = dialog
        dialog.exec_()

    def start_hotkey_capture(self, parent_dialog, hotkey_type):
        from ui.hotkey_capture import HotkeyCapture
        
        btn = self.wake_hotkey_capture_btn if hotkey_type == 'wake' else self.stop_hotkey_capture_btn
        original_text = btn.text()
        
        btn.setText('请按下组合键...')
        btn.setEnabled(False)
        QApplication.processEvents()
        
        new_key = HotkeyCapture.capture(parent_dialog)
        
        if new_key:
            try:
                if not any(m in new_key for m in ['Ctrl', 'Shift', 'Alt']):
                    self.show_text_window("快捷键需包含修饰键")
                else:
                    QKeySequence(new_key) # Validate
                    if hotkey_type == 'wake':
                        self.hotkey = new_key
                        self.current_hotkey_label_widget.setText(f'{self.hotkey}')
                    else:
                        self.stop_hotkey = new_key
                        self.current_stop_hotkey_label.setText(f'{self.stop_hotkey}')
                        
                    self.save_settings()
                    self.setup_hotkey()
                    self.captured_hotkey_label.setText(f"已更新: {new_key}")
            except:
                self.show_text_window("快捷键格式错误")
        
        btn.setText(original_text)
        btn.setEnabled(True)

    def confirm_hotkey_in_settings(self):
        # Deprecated: Logic moved to start_hotkey_capture
        pass

    def capture_key_press(self, event):
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
            self.captured_hotkey_label.setText(self.new_hotkey)
            self.hotkey_capture_btn.setText('点击捕获新快捷键')
            self.hotkey_capture_btn.setEnabled(True)
            self.key_capture_dialog.accept()

    def normalize_hotkey(self, hotkey_str):
        if not hotkey_str:
            return None
        hotkey_str = hotkey_str.lower()
        replacements = {
            'return': 'enter',
            'escape': 'esc',
            'period': '.',
            'comma': ',',
            'plus': '+',
            'minus': '-',
            'slash': '/',
            'asterisk': '*',
            'page up': 'page up',
            'page down': 'page down'
        }
        for old, new in replacements.items():
            hotkey_str = hotkey_str.replace(old, new)
        return hotkey_str

    def setup_hotkey(self):
        # 移除旧的快捷键
        try:
            if hasattr(self, 'hotkey_handle'):
                keyboard.remove_hotkey(self.hotkey_handle)
            if hasattr(self, 'stop_hotkey_handle'):
                keyboard.remove_hotkey(self.stop_hotkey_handle)
            
            # 同时也尝试移除旧的Qt快捷键（如果存在）
            if hasattr(self, 'shortcut'):
                self.shortcut.deleteLater()
            if hasattr(self, 'stop_shortcut'):
                self.stop_shortcut.deleteLater()
        except Exception:
            pass

        # 1. 唤醒快捷键 (全局)
        try:
            norm_hotkey = self.normalize_hotkey(self.hotkey)
            if norm_hotkey:
                # 使用 keyboard 库注册全局快捷键
                # 注意：keyboard 的回调是在非主线程执行的，需要通过信号触发主线程槽函数
                self.hotkey_handle = keyboard.add_hotkey(norm_hotkey, lambda: self.hotkey_triggered.emit())
        except Exception as e:
            print(f"Failed to register global hotkey {self.hotkey}: {e}")
            
        # 2. 停止快捷键 (全局)
        try:
            norm_stop_hotkey = self.normalize_hotkey(self.stop_hotkey)
            if norm_stop_hotkey:
                self.stop_hotkey_handle = keyboard.add_hotkey(norm_stop_hotkey, lambda: self.stop_hotkey_triggered.emit())
        except Exception as e:
            print(f"Failed to register global stop hotkey {self.stop_hotkey}: {e}")

    def handle_hotkey(self):
        # 只有在非连接状态下才响应唤醒快捷键
        if not self.is_connecting:
            self.handle_click()

    def apply_settings(self, size, opacity, color, font_size):
        self.ball_diameter = size
        self.opacity = opacity
        self.color = color
        self.font_size = font_size
        self.save_settings()
        self.setFixedSize(self.ball_diameter, self.ball_diameter)
        self.setMask(QRegion(QRect(0, 0, self.ball_diameter, self.ball_diameter), QRegion.Ellipse))
        self.setWindowOpacity(self.opacity)
        self.update()
        if self.ball_text:
            current_text = self.ball_text
            self.set_ball_text(current_text)
        if self.text_window:
            bg_color = 'rgba(0, 0, 0, 150)' if self.color == 'black' else 'rgba(255, 255, 255, 150)'
            text_color = 'white' if self.color == 'black' else 'black'
            self.text_edit.setStyleSheet(f"background-color: {bg_color}; color: {text_color}; border: none;")
            font = QFont()
            font.setPointSize(self.font_size)
            self.text_edit.setFont(font)
            text_height = int(self.ball_diameter * 3 / 4)
            self.text_edit.setFixedHeight(text_height)
            self.text_window.adjustSize()
            self.update_text_position()

    def mousePressEvent(self, event):
        self.hover_timer.stop()
        self.is_hovering = False
        
        # 如果正在连接，禁止交互，但允许右键（如果需要退出）
        # 或者完全禁止？
        if self.is_connecting and event.button() == Qt.LeftButton:
             self.show_text_window("MCP服务正在初始化，请稍候...")
             return
             
        if event.button() == Qt.LeftButton:
            self.m_drag = True
            self.m_drag_position = event.globalPos() - self.pos()
            self.drag_start_pos = event.globalPos()
            event.accept()
            self.setCursor(QCursor(Qt.OpenHandCursor))
        elif event.button() == Qt.RightButton:
            # 右键菜单可以允许，方便用户在卡住时退出
            self.show_context_menu(event.globalPos())

    def mouseMoveEvent(self, event):
        if self.m_drag and event.buttons() == Qt.LeftButton:
            new_pos = event.globalPos() - self.m_drag_position
            self.move(new_pos)
            if self.text_window:
                self.update_text_position()
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.m_drag = False
            self.setCursor(QCursor(Qt.ArrowCursor))
            if (event.globalPos() - self.drag_start_pos).manhattanLength() < 5:
                self.handle_click()

    def enterEvent(self, event):
        if not self.is_recording and self.hover_enabled:
            self.is_hovering = True
            self.hover_timer.start(self.hover_delay)
        # 如果已经显示了气泡，停止自动隐藏计时器，保持显示
        if self.text_window and self.text_window.isVisible():
            self.auto_hide_timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.hover_timer.stop()
        self.is_hovering = False
        # 鼠标离开后，重新启动自动隐藏计时器，给用户一点时间阅读
        if self.text_window and self.text_window.isVisible():
             self.auto_hide_timer.start(3000) # 离开后3秒消失
        super().leaveEvent(event)

    def on_hover_timeout(self):
        # 如果正在录音，不显示默认文本
        if self.is_recording:
            return
            
        # 如果正在识别中，不显示默认文本
        if self.is_recognizing:
            return

        # 如果正在处理后端任务（思考、工具调用等），也不显示默认文本
        is_processing = False
        app = QApplication.instance()
        if hasattr(app, 'worker') and app.worker and app.worker.is_processing:
            is_processing = True
        elif self.parent() and hasattr(self.parent(), 'worker') and self.parent().worker.is_processing:
            is_processing = True
            
        if is_processing:
            return

        if self.is_hovering:
            self.show_text_window("你好，有什么需要帮助的？")

    def handle_click(self):
        # 检查是否正在处理后端任务
        is_processing = False
        worker = None
        app = QApplication.instance()
        if hasattr(app, 'worker') and app.worker and app.worker.is_processing:
            is_processing = True
            worker = app.worker
        elif self.parent() and hasattr(self.parent(), 'worker') and self.parent().worker.is_processing:
            is_processing = True
            worker = self.parent().worker
            
        if is_processing and worker:
            worker.stop_processing()
            self.show_text_window("手动停止运行")
            return
            
        # 如果正在识别中，忽略点击或提示
        if self.is_recognizing:
            self.show_text_window("正在识别中，请稍候...")
            return

        if not self.is_recording:
            self.start_recording()
        else:
            self.stop_recording()

    def start_recording(self):
        self.is_recording = True
        self.recording_start_time = time.time()
        self.set_ball_text("录音中", enable_scroll=False)
        self.stop_recording_event = threading.Event()
        self.recording_thread = threading.Thread(
            target=self.record_audio_thread,
            args=(60, 1, 16000, 1024)
        )
        self.recording_thread.start()

    def stop_recording(self):
        if self.is_recording and self.stop_recording_event:
            recording_duration = time.time() - self.recording_start_time if self.recording_start_time else 0
            self.is_recording = False
            self.stop_recording_event.set()
            if recording_duration < 1.0:
                self.reset_ball_text()
                self.show_text_window("录音时间太短，请重新录入")
                self.audio_data = None
                self.skip_recognition = True
                if self.recording_thread and self.recording_thread.is_alive():
                    self.recording_thread.join()
                    self.recording_thread = None
                return
            
            self.skip_recognition = False
            self.is_recognizing = True # 进入识别状态
            self.set_ball_text("识别中", enable_scroll=False)

    def record_audio_thread(self, duration, channels, rate, chunk):
        try:
            self.audio_data = record_pcm_realtime(
                duration=duration,
                channels=channels,
                rate=rate,
                chunk=chunk,
                stop_event=self.stop_recording_event
            )
            self.recognize_audio_thread()
        except BaseException as e:
            self.recognition_finished.emit(f"录音失败: {str(e)}")

    def recognize_audio_thread(self):
        try:
            if self.skip_recognition:
                return
            if self.audio_data and len(self.audio_data) > 0:
                result_text = recognize_pcm(self.audio_data, 16000, 1)
                self.recognition_finished.emit(result_text)
            else:
                self.recognition_finished.emit("录音数据为空")
        except Exception as e:
            self.recognition_finished.emit(f"识别失败: {str(e)}")

    def on_recognition_finished(self, result):
        self.is_recognizing = False # 结束识别状态
        self.reset_ball_text()
        self.show_text_window(result)
        self.is_recording = False
        self.audio_data = None
        if self.recording_thread:
            try:
                if self.recording_thread.is_alive():
                    self.recording_thread.join()
            finally:
                self.recording_thread = None

    def show_text_window(self, text="你好，有什么需要帮助的？"):
        from ui.text_bubble import TextBubble
        if self.text_window:
            self.text_edit.setPlainText(text)
            self.text_window.show() # 确保显示
            
            # 如果不是默认的问候语，延长显示时间
            if text != "你好，有什么需要帮助的？":
                text_length = len(text)
                # LLM回复可能很长，给予更多阅读时间，每100字符5秒，最长60秒
                display_time = max(5000, min(60000, text_length * 50))
            else:
                display_time = 3000
                
            self.auto_hide_timer.start(display_time)
            return
            
        widget, text_edit = TextBubble.build(self, self.color, self.font_size, self.text_width, self.opacity, self.ball_diameter, text)
        self.text_window = widget
        self.text_edit = text_edit
        font_metrics = self.text_edit.fontMetrics()
        text_content_height = font_metrics.boundingRect(0, 0, self.text_width, 1000, Qt.TextWordWrap, text).height()
        display_height = self.text_edit.height()
        self.update_text_position()
        self.text_window.show()
        
        # 如果不是默认的问候语，延长显示时间
        if text != "你好，有什么需要帮助的？":
            text_length = len(text)
            display_time = max(5000, min(60000, text_length * 50))
        else:
            display_time = 3000
            
        self.auto_hide_timer.start(display_time)
        if text_content_height > display_height:
            self.scroll_position = 0
            self.scroll_timer.start(50)

    def hide_text_window(self):
        if self.text_window:
            self.text_window.close()
            self.text_window = None
            self.scroll_timer.stop()

    def set_ball_text(self, text, enable_scroll=True):
        self.ball_text = text
        if text:
            font = QFont()
            font.setPointSize(self.font_size)
            try:
                font_metrics = QFontMetrics(font)
                text_width = font_metrics.boundingRect(text).width()
            except Exception:
                font_metrics = self.fontMetrics()
                text_width = font_metrics.boundingRect(text).width()
            center_x = self.ball_diameter // 2
            radius = self.ball_diameter // 2
            start_x = center_x - int(radius * 3 / 4)
            available_width = self.ball_diameter - start_x - 10
            if text == self.default_ball_text:
                enable_scroll = False
                self.ball_text_effect_timer.stop()
                self.ball_text_segments = []
                self.fade_opacity = 1.0
                self.fade_phase = 'hold'
                self.fade_index = 0
                self.fade_elapsed_ms = 0
            elif enable_scroll and text_width > available_width:
                self.ball_text_scroll_timer.stop()
                try:
                    segment_start = font_metrics.elidedText(text, Qt.ElideRight, available_width)
                    segment_end = font_metrics.elidedText(text, Qt.ElideLeft, available_width)
                except Exception:
                    segment_start = text[:max(1, int(len(text) * 0.6))] + "..."
                    segment_end = "..." + text[-max(1, int(len(text) * 0.6)):]
                self.ball_text_segments = [segment_start, segment_end]
                self.fade_opacity = 1.0
                self.fade_phase = 'hold'
                self.fade_index = 0
                self.fade_elapsed_ms = 0
                self.ball_text_effect_timer.start(50)
            else:
                self.ball_text_scroll_timer.stop()
                self.ball_text_effect_timer.stop()
                self.ball_text_segments = []
                self.fade_opacity = 1.0
                self.fade_phase = 'hold'
                self.fade_index = 0
                self.fade_elapsed_ms = 0
        else:
            self.ball_text_scroll_timer.stop()
            self.ball_text_effect_timer.stop()
            self.ball_text_segments = []
            self.fade_opacity = 1.0
            self.fade_phase = 'hold'
            self.fade_index = 0
            self.fade_elapsed_ms = 0
        self.update()

    def reset_ball_text(self):
        self.set_ball_text(self.default_ball_text, enable_scroll=False)

    def scroll_ball_text(self):
        if self.ball_text:
            self.ball_text_scroll_position += 1
            if self.ball_text_scroll_position > len(self.ball_text) * 10:
                self.ball_text_scroll_position = 0
            self.update()

    def update_ball_text_effect(self):
        if not self.ball_text_segments:
            self.ball_text_effect_timer.stop()
            return
        if self.fade_phase == 'hold':
            self.fade_elapsed_ms += 50
            self.fade_opacity = 1.0
            if self.fade_elapsed_ms >= self.fade_hold_ms:
                self.fade_phase = 'out'
        elif self.fade_phase == 'out':
            self.fade_opacity -= 0.15
            if self.fade_opacity <= 0.0:
                self.fade_opacity = 0.0
                self.fade_index = (self.fade_index + 1) % len(self.ball_text_segments)
                self.fade_phase = 'in'
        elif self.fade_phase == 'in':
            self.fade_opacity += 0.15
            if self.fade_opacity >= 1.0:
                self.fade_opacity = 1.0
                self.fade_elapsed_ms = 0
                self.fade_phase = 'hold'
        self.update()

    def update_text_position(self):
        ball_pos = self.pos()
        text_height = self.text_edit.height()
        y_offset = int((self.ball_diameter - text_height) / 2)
        if ball_pos.x() + self.ball_diameter / 2 > self.screen.width() / 2:
            x_offset = int(-self.text_width + (self.ball_diameter / 4))
            text_pos = ball_pos + QPoint(x_offset, y_offset)
        else:
            x_offset = int(self.ball_diameter * 3 / 4)
            text_pos = ball_pos + QPoint(x_offset, y_offset)
        self.text_window.move(text_pos)

    def scroll_text(self):
        font_metrics = self.text_edit.fontMetrics()
        text = self.text_edit.toPlainText()
        text_height = font_metrics.boundingRect(0, 0, self.text_width, 1000, Qt.TextWordWrap, text).height()
        display_height = self.text_edit.height()
        self.scroll_position += 1
        if self.scroll_position > text_height - display_height:
            self.scroll_position = 0
        self.text_edit.verticalScrollBar().setValue(self.scroll_position)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        pen_color = QColor(30, 30, 30, 200) if self.color == 'black' else QColor(200, 200, 200, 200)
        brush_color = QColor(0, 0, 0, 150) if self.color == 'black' else QColor(255, 255, 255, 150)
        painter.setPen(QPen(pen_color, 2))
        painter.setBrush(brush_color)
        painter.drawEllipse(0, 0, self.ball_diameter, self.ball_diameter)
        if self.ball_text:
            painter.setPen(QColor(255, 255, 255) if self.color == 'black' else QColor(0, 0, 0))
            font = QFont()
            font.setPointSize(self.font_size)
            painter.setFont(font)
            center_x = self.ball_diameter // 2
            radius = self.ball_diameter // 2
            start_x = center_x - int(radius * 3 / 4)
            text_rect = QRect(start_x, 0, self.ball_diameter - start_x - 10, self.ball_diameter)
            display_text = self.ball_text
            if self.ball_text_segments:
                display_text = self.ball_text_segments[self.fade_index]
                painter.setOpacity(self.fade_opacity)
            painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, display_text)
            if self.ball_text_segments:
                painter.setOpacity(1.0)

    def save_settings(self):
        settings = {
            'ball_diameter': self.ball_diameter,
            'opacity': self.opacity,
            'color': self.color,
            'font_size': self.font_size,
            'ball_x': self.pos().x(),
            'ball_y': self.pos().y(),
            'hotkey': self.hotkey,
            'stop_hotkey': getattr(self, 'stop_hotkey', 'Ctrl+Shift+.'),
            'hover_enabled': self.hover_enabled,
            'hover_delay': self.hover_delay
        }
        write_settings(settings)

    def set_hover_config(self, enabled, delay):
        self.hover_enabled = enabled
        self.hover_delay = delay
        self.save_settings()

    def set_position(self):
        if self.ball_x is not None and self.ball_y is not None:
            self.move(self.ball_x, self.ball_y)
        else:
            center_x = (self.screen.width() - self.ball_diameter) // 2
            center_y = (self.screen.height() - self.ball_diameter) // 2
            self.move(center_x, center_y)
