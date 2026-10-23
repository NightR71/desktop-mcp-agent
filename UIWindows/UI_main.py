import sys
import os
import asyncio
import threading
import logging
from dotenv import load_dotenv
from PyQt5.QtWidgets import QApplication, QMessageBox
from ui.floating_ball import FloatingBall
from PyQt5.QtCore import QObject, pyqtSignal


current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(current_dir)
sys.path.append(root_dir)

from Backend.factory import MCPClientFactory

class BackendWorker(QObject):
    response_received = pyqtSignal(str)
    init_error = pyqtSignal(str)
    init_success = pyqtSignal()
    
    def __init__(self):
        super().__init__()
        self.loop = asyncio.new_event_loop()
        self.client = None
        self.running = True
        self.is_processing = False
        
    def start_backend(self):
        # 配置日志，使其在终端输出详细信息
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - %(message)s",
            handlers=[logging.StreamHandler()]
        )
        
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self.init_client())
        self.loop.run_forever()
        
    async def init_client(self):
        try:
            # 如果已有客户端，先清理
            if self.client:
                await self.client.cleanup()
                self.client = None
                
            config_file = os.path.join(root_dir, "winmcp1.json")
            
            # 尝试创建客户端，传入状态回调
            self.client = await MCPClientFactory.create_client(config_file, status_callback=self.on_status_update)
            
            # 只有当 factory 返回了非 None 的 client 且至少有一个服务器成功初始化时，才算成功
            if self.client and self.client.tool_registry.get_all_tools():
                await self.client.initialize()
                print("Backend initialized successfully")
                self.init_success.emit()
            else:
                error_msg = "MCP客户端创建失败或无可用工具 (请检查配置文件或服务状态)"
                print(f"Failed to initialize backend: {error_msg}")
                self.init_error.emit(error_msg)
        except Exception as e:
            error_msg = str(e)
            print(f"Exception during backend initialization: {error_msg}")
            self.init_error.emit(error_msg)

    def on_status_update(self, status_msg):
        """处理来自后端的实时状态更新"""
        self.response_received.emit(status_msg)

    def restart(self):
        asyncio.run_coroutine_threadsafe(self.init_client(), self.loop)

    def process_input(self, text):
        if self.client and not self.is_processing:
            self.is_processing = True
            print(f"\nYou: {text}")
            asyncio.run_coroutine_threadsafe(self._process_input_async(text), self.loop)

    async def _process_input_async(self, text):
        if self.client:
            try:
                response = await self.client.process_user_input(text)
                self.response_received.emit(response)
            except Exception as e:
                self.response_received.emit(f"执行出错: {str(e)}")
            finally:
                self.is_processing = False

    def stop_processing(self):
        """停止当前处理"""
        if self.client and self.is_processing:
            # 在协程中调用 stop_processing
            self.client.stop_processing()
            self.is_processing = False

    def stop(self):
        self.running = False
        if self.client:
             asyncio.run_coroutine_threadsafe(self.client.cleanup(), self.loop)
        self.loop.stop()

class AiAgentApp(QApplication):
    def __init__(self, argv):
        super().__init__(argv)
        self.worker = None
        self.restart_backend = None

def main():
    load_dotenv()
    app = AiAgentApp(sys.argv)
    
    # Initialize Backend Worker
    worker = BackendWorker()
    app.worker = worker
    # Define restart method
    app.restart_backend = worker.restart
    
    worker_thread = threading.Thread(target=worker.start_backend, daemon=True)
    worker_thread.start()

    ball = FloatingBall()
    
    # Connect signals
    ball.recognition_finished.connect(lambda text: worker.process_input(text))
    worker.response_received.connect(lambda response: ball.show_text_window(response))
    worker.init_error.connect(lambda msg: show_error_and_open_manager(ball, msg))
    
    def on_init_success():
        ball.is_connecting = False
        ball.default_ball_text = " O _ O \n\t ---"
        ball.reset_ball_text()
        ball.show_text_window("MCP服务连接成功！")
        
    worker.init_success.connect(on_init_success)
    
    ball.show()
    
    def on_exit():
        ball.save_settings()
        worker.stop()
        
    app.aboutToQuit.connect(on_exit)
    sys.exit(app.exec_())

def show_error_and_open_manager(ball, msg):
    # 初始化失败时，也要解除连接状态，以便用户操作
    ball.is_connecting = False
    ball.default_ball_text = " O _ O \n\t ---"
    ball.reset_ball_text()
    
    QMessageBox.critical(None, "后端启动失败", f"后端服务初始化出错:\n{msg}")
    ball.show_tool_manager()

if __name__ == "__main__":
    main()
