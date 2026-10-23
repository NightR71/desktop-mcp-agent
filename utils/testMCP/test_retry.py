import sys
import asyncio
import os
from unittest.mock import MagicMock, AsyncMock
from threading import Thread

# 将项目根目录添加到 sys.path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)
    
ui_path = os.path.join(project_root, 'UIWindows')
if ui_path not in sys.path:
    sys.path.insert(0, ui_path)

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QObject, pyqtSignal, QTimer

# 导入必要的类
# 注意：这里假设 uiwindows 包在项目根目录下
from UIWindows.ui.floating_ball import FloatingBall
from Backend.session.chat_session import EnhancedChatSession

class MockBackendWorker(QObject):
    response_received = pyqtSignal(str)
    
    def __init__(self, client):
        super().__init__()
        self.client = client
        self.loop = asyncio.new_event_loop()
        self.is_processing = False

    def process_input(self, text):
        self.is_processing = True
        print(f"开始处理输入: {text}")
        asyncio.run_coroutine_threadsafe(self._process_input_async(text), self.loop)

    async def _process_input_async(self, text):
        try:
            # 这里的 client 是 EnhancedChatSession 的实例
            response = await self.client.process_user_input(text)
            self.response_received.emit(response)
        except Exception as e:
            self.response_received.emit(f"执行出错: {str(e)}")
        finally:
            self.is_processing = False
            
    def stop_processing(self):
        if self.client:
            self.client.stop_processing()
            self.is_processing = False

def run_test():
    print("Starting test...")
    # 创建 QApplication
    app = QApplication(sys.argv)
    print("QApplication created")
    
    # 1. 创建 Mock 依赖
    mock_llm = MagicMock()
    mock_registry = MagicMock()
    mock_registry.get_all_tools.return_value = []
    
    # Mock ConversationManager 的方法，避免实际逻辑报错
    mock_conversation = MagicMock()
    mock_conversation.clear_history = MagicMock()
    mock_conversation.add_message = MagicMock()
    
    # 2. 创建 Client
    # 不需要真实的初始化，只要对象存在即可
    client = EnhancedChatSession(mock_llm, mock_registry, mock_conversation)
    
    # 关键：Mock _handle_conversation_turn 方法，让它总是抛出异常
    # process_user_input 会捕获这个异常并触发重试逻辑
    client._handle_conversation_turn = AsyncMock(side_effect=Exception("模拟的上下文超限错误"))
    
    # 3. 创建悬浮球
    print("正在初始化悬浮球...")
    try:
        ball = FloatingBall()
        ball.show()
    except Exception as e:
        print(f"悬浮球初始化失败: {e}")
        return
    
    # 4. 创建 Worker 并连接信号
    worker = MockBackendWorker(client)
    
    # 将 worker 挂载到 app 上，以便 floating_ball 可以访问 (仿照 UI_main.py 的逻辑)
    # 这对于测试手动停止等功能很重要，虽然本测试主要关注重试
    app.worker = worker 
    
    # 设置 status_callback，这样 client 的状态更新能显示在悬浮球上
    # 这里的逻辑是：Client -> status_callback -> Worker Signal -> FloatingBall
    def on_status_update(msg):
        print(f"Status Update: {msg}")
        # 通过信号发送到主线程更新 UI
        # 注意：status_callback 可能会在异步线程调用，所以最好通过信号发射
        worker.response_received.emit(msg)
        
    client.status_callback = on_status_update
    
    # 连接 worker 信号到悬浮球
    worker.response_received.connect(lambda msg: ball.show_text_window(msg))
    
    # 5. 启动后台循环线程
    def start_loop(loop):
        asyncio.set_event_loop(loop)
        loop.run_forever()
        
    t = Thread(target=start_loop, args=(worker.loop,), daemon=True)
    t.start()
    
    # 6. 定义测试触发函数
    def trigger_test():
        print("触发测试：模拟用户输入...")
        worker.process_input("这是一条测试重试的消息")

    # 7. 模拟 MCP 连接过程
    def on_mcp_connected():
        print("MCP 连接成功！更新 UI 状态...")
        # 更新悬浮球状态，模拟真实应用中的连接成功
        ball.is_connecting = False
        ball.default_ball_text = "测试AiAgent" 
        ball.reset_ball_text()
        ball.show_text_window("MCP 服务已连接")
        
        # 连接成功后，再触发测试
        print("连接成功，1秒后触发重试逻辑测试...")
        QTimer.singleShot(1000, trigger_test)

    # 启动模拟连接流程 (延迟 2 秒，模拟连接耗时)
    print("正在等待 MCP 连接 (模拟)...")
    QTimer.singleShot(2000, on_mcp_connected)
    
    print("测试程序已启动，请观察悬浮球状态...")
    print("预期效果：")
    print("1. 悬浮球显示 '遇到错误，正在重试 (1/3)...'")
    print("2. 悬浮球显示 '遇到错误，正在重试 (2/3)...'")
    print("3. 悬浮球显示 '遇到错误，正在重试 (3/3)...'")
    print("4. 最后显示错误信息")
    
    sys.exit(app.exec_())

if __name__ == "__main__":
    run_test()