import sys
import os
from unittest.mock import MagicMock
from threading import Timer

# 1. 确保环境路径正确
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

ui_path = os.path.join(project_root, 'UIWindows')
if ui_path not in sys.path:
    sys.path.insert(0, ui_path)

# 2. Mock 掉后端依赖，防止真实调用或导入错误
# 模拟 services.baidu_asr
sys.modules['services'] = MagicMock()
sys.modules['services.baidu_asr'] = MagicMock()
sys.modules['services.baidu_asr'].recognize_pcm = MagicMock(return_value="这是模拟的识别结果")

# 模拟 audio.recorder
sys.modules['audio'] = MagicMock()
sys.modules['audio.recorder'] = MagicMock()
sys.modules['audio.recorder'].record_pcm_realtime = MagicMock(return_value=[])

# 3. 导入 UI 依赖
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QPushButton, QLabel, QScrollArea, QGroupBox
from PyQt5.QtCore import Qt, QTimer

# 导入真实 UI 类 (现在应该不会报错了)
try:
    from UIWindows.ui.floating_ball import FloatingBall
except ImportError as e:
    print(f"Import Error: {e}")
    sys.exit(1)

# 4. 创建测试用的 FloatingBall 子类
class TestFloatingBall(FloatingBall):
    def __init__(self):
        # 调用父类初始化，UI 布局与真实一致
        super().__init__()
        
        # 强制设置初始状态：已连接
        self.is_connecting = False
        self.default_ball_text = " O _ O \n\t ---"
        self.reset_ball_text()
        
        # 禁用真实录音线程
        self.recording_thread = None
        
    def start_recording(self):
        """重写：仅改变 UI 状态为录音中，不启动真实录音"""
        if self.is_recording:
            return
            
        print("[Test] 模拟开始录音")
        self.is_recording = True
        self.set_ball_text("录音中", enable_scroll=False)
        
        # 模拟录音持续一段时间后自动停止（或者等待用户点击停止）
        # 这里为了测试方便，不自动停止，等待再次点击
        
    def stop_recording(self):
        """重写：仅改变 UI 状态为停止，并显示模拟结果"""
        if not self.is_recording:
            return

        print("[Test] 模拟停止录音")
        self.is_recording = False
        self.reset_ball_text()
        
        # 模拟识别中状态
        self.is_recognizing = True
        self.set_ball_text("识别中", enable_scroll=False)
        
        # 模拟 1 秒后识别完成
        QTimer.singleShot(1000, self._simulate_recognition_finished)

    def _simulate_recognition_finished(self):
        print("[Test] 模拟识别完成")
        self.is_recognizing = False
        self.reset_ball_text()
        self.show_text_window("这是模拟的语音识别结果，UI测试正常。")

    def handle_click(self):
        """重写点击处理：仅切换录音状态"""
        if self.is_recognizing:
            self.show_text_window("正在识别中，请稍候...")
            return

        if not self.is_recording:
            self.start_recording()
        else:
            self.stop_recording()

# 5. 创建控制面板
class ControlPanel(QWidget):
    def __init__(self, ball):
        super().__init__()
        self.ball = ball
        self.init_ui()
        
    def init_ui(self):
        self.setWindowTitle("AiAgent UI 测试控制面板")
        self.setGeometry(100, 100, 400, 600)
        
        layout = QVBoxLayout()
        
        # 分组：状态展示测试
        group_status = QGroupBox("状态文本测试")
        layout_status = QVBoxLayout()
        
        btn_thinking = QPushButton("模拟：思考中")
        btn_thinking.clicked.connect(lambda: self.show_text("当前模型正在思考中……"))
        layout_status.addWidget(btn_thinking)
        
        btn_analyzing = QPushButton("模拟：分析工具结果")
        btn_analyzing.clicked.connect(lambda: self.show_text("模型正在分析工具结果……"))
        layout_status.addWidget(btn_analyzing)
        
        btn_tool_call = QPushButton("模拟：调用工具")
        btn_tool_call.clicked.connect(lambda: self.show_text("模型正在调用工具中，请注意！"))
        layout_status.addWidget(btn_tool_call)
        
        group_status.setLayout(layout_status)
        layout.addWidget(group_status)
        
        # 分组：错误与重试
        group_error = QGroupBox("错误与重试测试")
        layout_error = QVBoxLayout()
        
        btn_retry_1 = QPushButton("模拟：重试 (1/3)")
        btn_retry_1.clicked.connect(lambda: self.show_text("遇到错误，正在重试 (1/3)..."))
        layout_error.addWidget(btn_retry_1)
        
        btn_retry_2 = QPushButton("模拟：重试 (2/3)")
        btn_retry_2.clicked.connect(lambda: self.show_text("遇到错误，正在重试 (2/3)..."))
        layout_error.addWidget(btn_retry_2)
        
        btn_error = QPushButton("模拟：最终错误")
        btn_error.clicked.connect(lambda: self.show_text("处理用户输入时出错 (已重试3次): 模拟的超时错误"))
        layout_error.addWidget(btn_error)
        
        btn_stop = QPushButton("模拟：手动停止")
        btn_stop.clicked.connect(lambda: self.show_text("手动停止运行成功"))
        layout_error.addWidget(btn_stop)
        
        group_error.setLayout(layout_error)
        layout.addWidget(group_error)
        
        # 分组：普通对话
        group_chat = QGroupBox("对话文本测试")
        layout_chat = QVBoxLayout()
        
        btn_short = QPushButton("短文本回复")
        btn_short.clicked.connect(lambda: self.show_text("你好，我是 AiAgent 助手。"))
        layout_chat.addWidget(btn_short)
        
        btn_long = QPushButton("长文本回复 (滚动)")
        long_text = "好的！已为您打开哔哩哔哩，并成功搜索“人民日报”。当前页面已显示相关搜索结果，包括官方账号及热门视频。如需进一步操作，例如播放视频或关注账号，请随时告诉我！"
        btn_long.clicked.connect(lambda: self.show_text(long_text))
        layout_chat.addWidget(btn_long)
        
        btn_code = QPushButton("代码块样式测试")
        code_text = """这里有一段代码：
```python
def hello():
    print("Hello World")
```
请检查显示效果。"""
        btn_code.clicked.connect(lambda: self.show_text(code_text))
        layout_chat.addWidget(btn_code)
        
        group_chat.setLayout(layout_chat)
        layout.addWidget(group_chat)
        
        # 分组：悬浮球状态
        group_ball = QGroupBox("悬浮球状态测试")
        layout_ball = QVBoxLayout()
        
        btn_ball_connect = QPushButton("悬浮球：连接中")
        btn_ball_connect.clicked.connect(self.set_ball_connecting)
        layout_ball.addWidget(btn_ball_connect)
        
        btn_ball_ready = QPushButton("悬浮球：就绪")
        btn_ball_ready.clicked.connect(self.set_ball_ready)
        layout_ball.addWidget(btn_ball_ready)
        
        group_ball.setLayout(layout_ball)
        layout.addWidget(group_ball)

        self.setLayout(layout)

    def show_text(self, text):
        print(f"[Control] 请求显示文本: {text[:20]}...")
        self.ball.show_text_window(text)
        
    def set_ball_connecting(self):
        print("[Control] 设置悬浮球为连接中状态")
        self.ball.is_connecting = True
        self.ball.default_ball_text = "MCP正在连接"
        self.ball.reset_ball_text()
        
    def set_ball_ready(self):
        print("[Control] 设置悬浮球为就绪状态")
        self.ball.is_connecting = False
        self.ball.default_ball_text = "AiAgent"
        self.ball.reset_ball_text()

def run_test():
    app = QApplication(sys.argv)
    
    # 创建测试悬浮球
    ball = TestFloatingBall()
    ball.show()
    
    # 创建控制面板
    control_panel = ControlPanel(ball)
    control_panel.show()
    
    print("UI 测试程序已启动。")
    print("请使用控制面板按钮测试各种 UI 状态。")
    print("点击悬浮球可测试录音 UI 切换（不录音）。")
    
    sys.exit(app.exec_())

if __name__ == "__main__":
    run_test()
