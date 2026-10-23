import sys
import json  # 添加导入
import threading
import time
from PyQt5.QtCore import Qt, QTimer, QPoint, QRect, QPropertyAnimation, QEasingCurve, pyqtSignal
from PyQt5.QtGui import QFont, QColor, QPainter, QPen, QCursor, QRegion, QScreen, QKeySequence, QFontMetrics
from PyQt5.QtWidgets import QApplication, QWidget, QTextEdit, QVBoxLayout, QMenu, QAction, QDialog, QFormLayout, QSpinBox, QSlider, QComboBox, QPushButton, QShortcut, QLineEdit, QLabel, QCheckBox

# 导入语音识别功能

import base64
import requests
from typing import List
import os
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("VOICE_API_KEY")
SECRET_KEY = os.getenv("SECRET_API_KEY")

def record_pcm_realtime(duration: int = 5,
                       channels: int = 1,
                       rate: int = 16000,
                       chunk: int = 1024,
                       stop_event=None) -> bytes:
    """使用麦克风录音并返回原始 PCM 数据，支持提前停止。"""
    try:
        import pyaudio
    except ImportError as exc:
        raise RuntimeError("未找到 PyAudio，请先安装：pip install pyaudio") from exc

    pa = pyaudio.PyAudio()
    try:
        stream = pa.open(format=pyaudio.paInt16,
                         channels=channels,
                         rate=rate,
                         input=True,
                         frames_per_buffer=chunk)
        frames: List[bytes] = []
        max_frames = int(rate / chunk * duration)
        
        for i in range(max_frames):
            if stop_event and stop_event.is_set():
                break
            data = stream.read(chunk, exception_on_overflow=False)
            frames.append(data)
    finally:
        stream.stop_stream()
        stream.close()
        pa.terminate()

    audio_data = b''.join(frames)
    return audio_data

def get_access_token() -> str:
    """从百度获取 access_token。"""
    url = "https://aip.baidubce.com/oauth/2.0/token"
    params = {
        "grant_type": "client_credentials",
        "client_id": API_KEY,
        "client_secret": SECRET_KEY,
    }
    if not API_KEY or not SECRET_KEY:
        return None
    try:
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        resp = requests.post(url, data=params, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        token = data.get("access_token")
        return token if token else None
    except Exception:
        return None

def recognize_pcm(pcm_data: bytes, rate: int = 16000, channel: int = 1) -> str:
    """调用百度语音识别 API 识别 PCM 音频数据并返回文字结果。"""
    token = get_access_token()
    if not token or str(token).strip().lower() == "none":
        raise RuntimeError("未能获取 access_token")

    url = "https://vop.baidu.com/pro_api"
    speech_b64 = base64.b64encode(pcm_data).decode("utf8")
    payload = {
        "format": "pcm",
        "rate": rate,
        "channel": channel,
        "cuid": "python_client",
        "dev_pid": 80001,
        "speech": speech_b64,
        "len": len(pcm_data),
        "token": token,
    }
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    last_err = None
    for attempt in range(2):
        try:
            resp = requests.post(url, headers=headers, data=json.dumps(payload), timeout=30)
            resp.raise_for_status()
            data = resp.json()
            if data.get("err_no") == 0:
                return data.get("result", [""])[0]
            last_err = RuntimeError(f"百度语音识别错误: {data}")
        except requests.RequestException as e:
            last_err = RuntimeError(f"网络错误: {str(e)}")
        except Exception as e:
            last_err = RuntimeError(f"识别异常: {str(e)}")
        time.sleep(0.6)
    if last_err:
        raise last_err
    raise RuntimeError("识别失败")

class FloatingBall(QWidget):
    # 添加信号用于线程间通信
    recognition_finished = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()
        self.config_file = os.path.join(os.getenv('APPDATA') or os.path.expanduser('~'), 'UIsettings.json')
        self.load_settings()  # 加载设置
        self.init_ui()
        self.m_drag = False
        self.m_drag_position = QPoint()
        self.text_window = None
        self.scroll_timer = QTimer(self)
        self.scroll_timer.timeout.connect(self.scroll_text)
        self.scroll_position = 0
        self.screen = QApplication.primaryScreen().geometry()
        self.setWindowOpacity(self.opacity)
        self.text_width = 400  # 文本框宽度
        
        # 录音相关状态
        self.is_recording = False
        self.recording_thread = None
        self.stop_recording_event = None
        self.audio_data = None
        self.recording_start_time = None  # 录音开始时间
        self.skip_recognition = False  # 是否跳过识别
        
        # 悬浮球内部文本相关
        self.default_ball_text = " O _ O \n\t ---"
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
        
        # 自动隐藏定时器
        self.auto_hide_timer = QTimer(self)
        self.auto_hide_timer.timeout.connect(self.hide_text_window)
        self.auto_hide_timer.setSingleShot(True)

        # 鼠标悬停定时器
        self.hover_timer = QTimer(self)
        self.hover_timer.timeout.connect(self.on_hover_timeout)
        self.hover_timer.setSingleShot(True)
        self.is_hovering = False
        
        # 设置悬浮球位置
        self.set_position()
        
        # 设置全局快捷键
        self.setup_hotkey()
        
        # 连接信号
        self.recognition_finished.connect(self.on_recognition_finished)

    def init_ui(self):
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(self.ball_diameter, self.ball_diameter)
        self.setMask(QRegion(QRect(0, 0, self.ball_diameter, self.ball_diameter), QRegion.Ellipse))

    def show_context_menu(self, position):
        # 停止悬停定时器，避免冲突
        self.hover_timer.stop()
        self.is_hovering = False
        
        menu = QMenu()
        settings_action = QAction('设置', self)
        settings_action.triggered.connect(self.show_settings_dialog)
        exit_action = QAction('退出', self)
        exit_action.triggered.connect(QApplication.quit)
        menu.addAction(settings_action)
        menu.addAction(exit_action)
        menu.exec_(position)

    def show_settings_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('设置')
        layout = QFormLayout()

        # 悬浮球设置
        size_spin = QSpinBox()
        size_spin.setRange(50, 300)
        size_spin.setValue(self.ball_diameter)
        size_spin.valueChanged.connect(lambda value: self.apply_settings(value, self.opacity, self.color, self.font_size))
        layout.addRow('大小:', size_spin)

        opacity_slider = QSlider(Qt.Horizontal)
        opacity_slider.setRange(1, 100)
        opacity_slider.setValue(int(self.opacity * 100))
        opacity_slider.valueChanged.connect(lambda value: self.apply_settings(self.ball_diameter, value / 100.0, self.color, self.font_size))
        layout.addRow('透明度:', opacity_slider)

        color_combo = QComboBox()
        color_combo.addItems(['black', 'white'])
        color_combo.setCurrentText(self.color)
        color_combo.currentTextChanged.connect(lambda text: self.apply_settings(self.ball_diameter, self.opacity, text, self.font_size))
        layout.addRow('颜色:', color_combo)

        font_spin = QSpinBox()
        font_spin.setRange(8, 24)
        font_spin.setValue(self.font_size)
        font_spin.valueChanged.connect(lambda value: self.apply_settings(self.ball_diameter, self.opacity, self.color, value))
        layout.addRow('字体大小:', font_spin)

        # 悬停设置
        hover_checkbox = QCheckBox()
        hover_checkbox.setChecked(self.hover_enabled)
        hover_checkbox.toggled.connect(lambda checked: self.set_hover_config(checked, self.hover_delay))
        layout.addRow('悬停弹窗:', hover_checkbox)

        hover_delay_spin = QSpinBox()
        hover_delay_spin.setRange(200, 5000)
        hover_delay_spin.setValue(self.hover_delay)
        hover_delay_spin.valueChanged.connect(lambda value: self.set_hover_config(self.hover_enabled, value))
        layout.addRow('悬停延时(ms):', hover_delay_spin)

        # 快捷键设置
        current_hotkey_label = QLabel(f'当前快捷键: {self.hotkey}')
        layout.addRow('', current_hotkey_label)

        self.hotkey_capture_btn = QPushButton('点击捕获新快捷键')
        self.hotkey_capture_btn.clicked.connect(lambda: self.start_hotkey_capture(dialog))
        self.hotkey_capture_btn.setMinimumHeight(35)
        layout.addRow('快捷键设置:', self.hotkey_capture_btn)
        
        self.captured_hotkey_label = QLabel('')
        self.captured_hotkey_label.setStyleSheet('color: #0066cc; font-weight: bold;')
        layout.addRow('新快捷键:', self.captured_hotkey_label)
        
        # 快捷键确认按钮
        hotkey_confirm_btn = QPushButton('应用快捷键')
        hotkey_confirm_btn.clicked.connect(lambda: self.confirm_hotkey_in_settings())
        hotkey_confirm_btn.setMinimumHeight(30)
        layout.addRow('', hotkey_confirm_btn)

        dialog.setLayout(layout)
        dialog.setFixedWidth(400)  # 增加设置窗口宽度以容纳快捷键设置
        dialog.adjustSize()
        screen = QApplication.primaryScreen().geometry()
        dialog.move((screen.width() - dialog.width()) // 2, (screen.height() - dialog.height()) // 2)
        
        self.new_hotkey = None  # 存储新捕获的快捷键
        self.settings_dialog = dialog  # 保存对话框引用
        dialog.exec_()
    
    def confirm_hotkey_in_settings(self):
        """在设置对话框中确认快捷键设置"""
        if self.new_hotkey:
            try:
                if not any(m in self.new_hotkey for m in ['Ctrl', 'Shift', 'Alt']):
                    self.show_text_window("快捷键需包含修饰键")
                    return
                # 验证快捷键格式
                QKeySequence(self.new_hotkey)
                self.hotkey = self.new_hotkey
                self.save_settings()  # 保存到配置文件
                self.setup_hotkey()  # 重新设置快捷键
                self.show_text_window(f"快捷键已更新为: {self.hotkey}")
                # 更新显示
                if hasattr(self, 'settings_dialog'):
                    # 刷新当前快捷键显示
                    for i in range(self.settings_dialog.layout().rowCount()):
                        item = self.settings_dialog.layout().itemAt(i, QFormLayout.LabelRole)
                        if item and item.widget() and isinstance(item.widget(), QLabel):
                            if '当前快捷键:' in item.widget().text():
                                item.widget().setText(f'当前快捷键: {self.hotkey}')
                                break
                self.captured_hotkey_label.setText('')  # 清空捕获显示
                self.new_hotkey = None
            except:
                # 快捷键格式错误，显示提示
                self.show_text_window("快捷键格式错误，请重新设置")
        else:
            self.show_text_window("请先捕获快捷键")
    
    def start_hotkey_capture(self, parent_dialog):
        """开始捕获快捷键"""
        self.hotkey_capture_btn.setText('请按下快捷键组合...')
        self.hotkey_capture_btn.setEnabled(False)
        
        # 创建快捷键捕获器
        self.key_capture_dialog = QDialog(parent_dialog)
        self.key_capture_dialog.setWindowTitle('按下快捷键')
        self.key_capture_dialog.setFixedSize(350, 120)
        self.key_capture_dialog.setWindowFlags(Qt.Dialog | Qt.WindowStaysOnTopHint)
        
        layout = QVBoxLayout()
        label = QLabel('请按下您想要设置的快捷键组合\n(支持 Ctrl、Shift、Alt + 字母/数字/符号)')
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet('font-size: 12px; padding: 10px;')
        layout.addWidget(label)
        
        self.key_capture_dialog.setLayout(layout)
        self.key_capture_dialog.keyPressEvent = self.capture_key_press
        
        # 居中显示
        screen = QApplication.primaryScreen().geometry()
        self.key_capture_dialog.move(
            (screen.width() - self.key_capture_dialog.width()) // 2,
            (screen.height() - self.key_capture_dialog.height()) // 2
        )
        
        self.key_capture_dialog.exec_()
    
    def capture_key_press(self, event):
        """捕获按键事件"""
        modifiers = []
        if event.modifiers() & Qt.ControlModifier:
            modifiers.append('Ctrl')
        if event.modifiers() & Qt.ShiftModifier:
            modifiers.append('Shift')
        if event.modifiers() & Qt.AltModifier:
            modifiers.append('Alt')

        key_text = event.text()
        if not key_text and event.key() != Qt.Key_unknown:
            # 处理特殊键
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

            # 更新显示
            self.captured_hotkey_label.setText(self.new_hotkey)
            self.hotkey_capture_btn.setText('点击捕获新快捷键')
            self.hotkey_capture_btn.setEnabled(True)

            # 关闭捕获对话框
            self.key_capture_dialog.accept()


    
    def setup_hotkey(self):
        """设置全局快捷键"""
        try:
            # 如果已存在快捷键，先删除
            if hasattr(self, 'shortcut'):
                self.shortcut.deleteLater()

            # 创建新的快捷键
            self.shortcut = QShortcut(QKeySequence(self.hotkey), self)
            self.shortcut.activated.connect(self.handle_hotkey)
        except:
            # 快捷键设置失败，使用默认快捷键
            self.hotkey = 'Ctrl+.'
            self.shortcut = QShortcut(QKeySequence(self.hotkey), self)
            self.shortcut.activated.connect(self.handle_hotkey)
    
    def handle_hotkey(self):
        """处理快捷键触发"""
        self.handle_click()

    def load_settings(self):
        self.ball_diameter = 150
        self.opacity = 0.8
        self.color = 'black'
        self.font_size = 12
        self.ball_x = None
        self.ball_y = None
        self.hotkey = 'Ctrl+.'  # 默认快捷键
        self.hover_enabled = True
        self.hover_delay = 1000
        try:
            with open(self.config_file, 'r') as f:
                settings = json.load(f)
                self.ball_diameter = settings.get('ball_diameter', self.ball_diameter)
                self.opacity = settings.get('opacity', self.opacity)
                self.color = settings.get('color', self.color)
                self.font_size = settings.get('font_size', self.font_size)
                self.ball_x = settings.get('ball_x', None)
                self.ball_y = settings.get('ball_y', None)
                self.hotkey = settings.get('hotkey', self.hotkey)
                self.hover_enabled = settings.get('hover_enabled', self.hover_enabled)
                self.hover_delay = settings.get('hover_delay', self.hover_delay)
        except FileNotFoundError:
            try:
                with open('UIsettings.json', 'r') as f:
                    settings = json.load(f)
                    self.ball_diameter = settings.get('ball_diameter', self.ball_diameter)
                    self.opacity = settings.get('opacity', self.opacity)
                    self.color = settings.get('color', self.color)
                    self.font_size = settings.get('font_size', self.font_size)
                    self.ball_x = settings.get('ball_x', None)
                    self.ball_y = settings.get('ball_y', None)
                    self.hotkey = settings.get('hotkey', self.hotkey)
                    self.hover_enabled = settings.get('hover_enabled', self.hover_enabled)
                    self.hover_delay = settings.get('hover_delay', self.hover_delay)
            except Exception:
                pass
        except Exception:
            try:
                with open('UIsettings.json', 'r') as f:
                    settings = json.load(f)
                    self.ball_diameter = settings.get('ball_diameter', self.ball_diameter)
                    self.opacity = settings.get('opacity', self.opacity)
                    self.color = settings.get('color', self.color)
                    self.font_size = settings.get('font_size', self.font_size)
                    self.ball_x = settings.get('ball_x', None)
                    self.ball_y = settings.get('ball_y', None)
                    self.hotkey = settings.get('hotkey', self.hotkey)
                    self.hover_enabled = settings.get('hover_enabled', self.hover_enabled)
                    self.hover_delay = settings.get('hover_delay', self.hover_delay)
            except Exception:
                pass

    def apply_settings(self, size, opacity, color, font_size):
        self.ball_diameter = size
        self.opacity = opacity
        self.color = color
        self.font_size = font_size
        self.save_settings()  # 保存设置
        self.setFixedSize(self.ball_diameter, self.ball_diameter)
        self.setMask(QRegion(QRect(0, 0, self.ball_diameter, self.ball_diameter), QRegion.Ellipse))
        self.setWindowOpacity(self.opacity)
        self.update()  # 重新绘制
        
        # 如果悬浮球内有文本，重新设置以更新字体大小和滚动状态
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
        # 停止悬停定时器
        self.hover_timer.stop()
        self.is_hovering = False
        
        if event.button() == Qt.LeftButton:
            self.m_drag = True
            self.m_drag_position = event.globalPos() - self.pos()
            self.drag_start_pos = event.globalPos()
            event.accept()
            self.setCursor(QCursor(Qt.OpenHandCursor))
        elif event.button() == Qt.RightButton:
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
        """鼠标进入悬浮球区域"""
        if not self.is_recording and self.hover_enabled:
            self.is_hovering = True
            self.hover_timer.start(self.hover_delay)
        super().enterEvent(event)

    def leaveEvent(self, event):
        """鼠标离开悬浮球区域"""
        self.hover_timer.stop()
        self.is_hovering = False
        super().leaveEvent(event)
    
    def on_hover_timeout(self):
        """悬停超时处理"""
        if self.is_hovering and not self.is_recording:
            self.show_text_window("你好，有什么需要帮助的？")


    def handle_click(self):
        if not self.is_recording:
            # 第一次点击：开始录音
            self.start_recording()
        else:
            # 第二次点击：停止录音并识别
            self.stop_recording()
    
    def start_recording(self):
        self.is_recording = True
        self.recording_start_time = time.time()  # 记录录音开始时间
        self.set_ball_text("正在录音...点击停止", enable_scroll=True)
        
        # 创建停止事件
        self.stop_recording_event = threading.Event()
        
        # 在新线程中开始录音
        self.recording_thread = threading.Thread(
            target=self.record_audio_thread,
            args=(60, 1, 16000, 1024)  # 最大60秒录音
        )
        self.recording_thread.start()
    
    def stop_recording(self):
        if self.is_recording and self.stop_recording_event:
            # 检查录音时长
            recording_duration = time.time() - self.recording_start_time if self.recording_start_time else 0

            self.is_recording = False
            self.stop_recording_event.set()  # 通知录音线程停止

            # 如果录音时间太短（少于1秒），显示提示信息并标记跳过识别
            if recording_duration < 1.0:
                self.reset_ball_text()
                self.show_text_window("录音时间太短，请重新录入")
                self.audio_data = None  # 清空音频数据，避免调用API
                self.skip_recognition = True  # 添加标记跳过识别
                if self.recording_thread and self.recording_thread.is_alive():
                    self.recording_thread.join()
                    self.recording_thread = None
                return

            self.skip_recognition = False  # 正常录音，不跳过识别
            self.set_ball_text("录音结束，正在识别...", enable_scroll=True)

    def record_audio_thread(self, duration, channels, rate, chunk):
        try:
            self.audio_data = record_pcm_realtime(
                duration=duration,
                channels=channels,
                rate=rate,
                chunk=chunk,
                stop_event=self.stop_recording_event
            )
            # 录音完成后进行识别
            self.recognize_audio_thread()
        except BaseException as e:
            self.recognition_finished.emit(f"录音失败: {str(e)}")

    def recognize_audio_thread(self):
        try:
            # 如果标记跳过识别，直接返回
            if self.skip_recognition:
                return

            # 检查是否有有效的音频数据
            if self.audio_data and len(self.audio_data) > 0:
                result_text = recognize_pcm(self.audio_data, 16000, 1)
                self.recognition_finished.emit(result_text)
            else:
                self.recognition_finished.emit("录音数据为空")
        except Exception as e:
            self.recognition_finished.emit(f"识别失败: {str(e)}")

    def on_recognition_finished(self, result):
        """处理识别结果的槽函数"""
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
        if self.text_window:
            self.text_edit.setPlainText(text)
            return

        self.text_window = QWidget()
        self.text_window.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.text_window.setAttribute(Qt.WA_TranslucentBackground)
        self.text_window.setWindowOpacity(self.opacity)

        layout = QVBoxLayout(self.text_window)
        layout.setContentsMargins(0, 0, 0, 0)

        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        bg_color = 'rgba(0, 0, 0, 150)' if self.color == 'black' else 'rgba(255, 255, 255, 150)'
        text_color = 'white' if self.color == 'black' else 'black'
        self.text_edit.setStyleSheet(f"background-color: {bg_color}; color: {text_color}; border: none;")
        font = QFont()
        font.setPointSize(self.font_size)
        self.text_edit.setFont(font)
        self.text_edit.setFixedWidth(self.text_width)
        text_height = int(self.ball_diameter * 3 / 4)
        self.text_edit.setFixedHeight(text_height)
        self.text_edit.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.text_edit.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.text_edit.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self.text_edit.setPlainText(text)
        font_metrics = self.text_edit.fontMetrics()
        text_content_height = font_metrics.boundingRect(0, 0, self.text_width, 1000, Qt.TextWordWrap, text).height()
        display_height = text_height

        layout.addWidget(self.text_edit)
        self.text_window.setLayout(layout)

        self.update_text_position()
        self.text_window.show()
        
        # 根据文本长度动态调整显示时间（3-7秒）
        text_length = len(text)
        display_time = max(3000, min(7000, text_length * 50))  # 每个字符50ms，最少3秒，最多7秒
        self.auto_hide_timer.start(display_time)

        # 如果文本过长，启动滚动
        if text_content_height > display_height:
            self.scroll_position = 0
            self.scroll_timer.start(50)  # 每50ms滚动
    
    def hide_text_window(self):
        if self.text_window:
            self.text_window.close()
            self.text_window = None
            self.scroll_timer.stop()
    
    def set_ball_text(self, text, enable_scroll=True):
        """设置悬浮球内部显示的文本"""
        self.ball_text = text
        if text:
            # 检查文本是否需要滚动
            font = QFont()
            font.setPointSize(self.font_size)
            try:
                font_metrics = QFontMetrics(font)
                text_width = font_metrics.boundingRect(text).width()
            except Exception:
                font_metrics = self.fontMetrics()
                text_width = font_metrics.boundingRect(text).width()
            # 计算可用宽度 - 从圆心左边半径的3/4处到右边缘
            center_x = self.ball_diameter // 2
            radius = self.ball_diameter // 2
            start_x = center_x - int(radius * 3 / 4)
            available_width = self.ball_diameter - start_x - 10  # 留出右边距

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
        """滚动悬浮球内部文本"""
        if self.ball_text:
            self.ball_text_scroll_position += 1
            if self.ball_text_scroll_position > len(self.ball_text) * 10:  # 滚动一轮后重置
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
            # 展开到左边，右边缘在球中心到左圆周的3/4处
            x_offset = int(-self.text_width + (self.ball_diameter / 4))
            text_pos = ball_pos + QPoint(x_offset, y_offset)
        else:
            # 展开到右边，左边缘在球中心到右圆周的3/4处
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
        
        # 绘制悬浮球内部文本
        if self.ball_text:
            painter.setPen(QColor(255, 255, 255) if self.color == 'black' else QColor(0, 0, 0))
            font = QFont()
            font.setPointSize(self.font_size)  # 使用设置中的字体大小
            painter.setFont(font)
            
            # 计算文本显示区域 - 从圆心左边半径的3/4处开始
            center_x = self.ball_diameter // 2
            radius = self.ball_diameter // 2
            start_x = center_x - int(radius * 3 / 4)  # 圆心左边半径的3/4处
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
            'hover_enabled': self.hover_enabled,
            'hover_delay': self.hover_delay
        }
        try:
            with open(self.config_file, 'w') as f:
                json.dump(settings, f)
        except Exception:
            try:
                with open('UIsettings.json', 'w') as f:
                    json.dump(settings, f)
            except Exception:
                pass

    def set_hover_config(self, enabled, delay):
        self.hover_enabled = enabled
        self.hover_delay = delay
        self.save_settings()
    
    def set_position(self):
        """设置悬浮球位置"""
        if self.ball_x is not None and self.ball_y is not None:
            self.move(self.ball_x, self.ball_y)
        else:
            # 默认屏幕中心
            center_x = (self.screen.width() - self.ball_diameter) // 2
            center_y = (self.screen.height() - self.ball_diameter) // 2
            self.move(center_x, center_y)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    ball = FloatingBall()
    ball.show()
    
    # 程序退出时保存位置
    def on_exit():
        ball.save_settings()
    
    app.aboutToQuit.connect(on_exit)
    sys.exit(app.exec_())
