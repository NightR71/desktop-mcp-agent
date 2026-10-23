import json
import os
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QListWidget, 
                             QLabel, QLineEdit, QTextEdit, QPushButton, 
                             QMessageBox, QWidget, QSplitter, QGroupBox, QFormLayout)
from PyQt5.QtCore import Qt

class ToolManagerDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("工具管理 (MCP Servers)")
        self.resize(900, 600)
        
        # Calculate config path: ../../winmcp1.json relative to this file
        # This file is in d:\AiAgent\UIWindows\ui\
        current_dir = os.path.dirname(os.path.abspath(__file__))
        self.config_path = os.path.join(os.path.dirname(os.path.dirname(current_dir)), "winmcp1.json")
        
        self.config_data = {}
        self.current_server_name = None
        
        self.init_ui()
        self.load_config()

    def init_ui(self):
        main_layout = QHBoxLayout(self)
        
        # Left side: Server List
        left_panel = QGroupBox("服务器列表")
        left_layout = QVBoxLayout(left_panel)
        self.server_list = QListWidget()
        self.server_list.currentRowChanged.connect(self.on_server_selected)
        left_layout.addWidget(self.server_list)
        
        btn_layout = QHBoxLayout()
        self.btn_add = QPushButton("新增")
        self.btn_add.clicked.connect(self.add_server)
        self.btn_del = QPushButton("删除")
        self.btn_del.clicked.connect(self.delete_server)
        
        # Style buttons
        for btn in [self.btn_add, self.btn_del]:
            btn.setMinimumHeight(60)
            
        btn_layout.addWidget(self.btn_add)
        btn_layout.addWidget(self.btn_del)
        left_layout.addLayout(btn_layout)
        
        # Right side: Details
        right_panel = QGroupBox("服务器配置")
        right_layout = QFormLayout(right_panel)
        right_layout.setSpacing(10)
        
        self.edit_config = QTextEdit()
        self.edit_config.setPlaceholderText("请输入完整的 JSON 配置对象，例如：\n{\n  \"command\": \"python\",\n  \"args\": [\"script.py\"]\n}")
        self.edit_config.setMinimumHeight(300)
        
        right_layout.addRow("配置 (JSON):", self.edit_config)
        
        self.btn_save = QPushButton("保存修改")
        self.btn_save.clicked.connect(self.save_current_server)
        self.btn_save.setMinimumHeight(80)
        self.btn_save.setCursor(Qt.PointingHandCursor)
        self.btn_save.setStyleSheet("""
            QPushButton {
                background-color: #0078D4; 
                color: white; 
                border-radius: 10px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #106EBE;
            }
            QPushButton:pressed {
                background-color: #005A9E;
            }
        """)
        
        right_layout.addRow("", self.btn_save)
        
        # Splitter
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(1, 2)
        splitter.setHandleWidth(10)
        
        main_layout.addWidget(splitter)
        
        # Apply global dialog styling
        self.setStyleSheet("""
            QDialog {
                background-color: #f5f5f5;
                font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
            }
            QGroupBox {
                font-weight: bold;
                border: 1px solid #d0d0d0;
                border-radius: 6px;
                margin-top: 25px;
                background-color: white;
                font-size: 25px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
                color: #333;
            }
            QListWidget {
                border: 1px solid #e0e0e0;
                border-radius: 4px;
                background-color: #fafafa;
                font-size: 25px;
                padding: 5px;
            }
            QListWidget::item {
                padding: 15px;
            }
            QListWidget::item:selected {
                background-color: #e3f2fd;
                color: #0078D4;
            }
            QLineEdit, QTextEdit {
                border: 1px solid #ccc;
                border-radius: 4px;
                padding: 15px;
                background-color: white;
                font-size: 25px;
            }
            QLineEdit:focus, QTextEdit:focus {
                border: 1px solid #0078D4;
            }
            QLabel {
                font-size: 25px;
            }
            QPushButton {
                font-size: 25px;
                padding: 15px 20px;
            }
        """)

    def load_config(self):
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    self.config_data = json.load(f)
            else:
                self.config_data = {"mcpServers": {}}
        except Exception as e:
            QMessageBox.critical(self, "错误", f"加载配置文件失败: {str(e)}")
            self.config_data = {"mcpServers": {}}
            
        self.refresh_list()

    def refresh_list(self):
        self.server_list.clear()
        servers = self.config_data.get("mcpServers", {})
        for name in servers:
            self.server_list.addItem(name)

    def on_server_selected(self, row):
        if row < 0:
            return
        name = self.server_list.item(row).text()
        self.current_server_name = name
        server_config = self.config_data["mcpServers"][name]
        
        # Display as formatted JSON
        json_str = json.dumps(server_config, indent=2, ensure_ascii=False)
        self.edit_config.setPlainText(json_str)

    def add_server(self):
        # Determine unique name
        base_name = "new-server"
        name = base_name
        counter = 1
        while "mcpServers" in self.config_data and name in self.config_data["mcpServers"]:
            name = f"{base_name}-{counter}"
            counter += 1
            
        if "mcpServers" not in self.config_data:
            self.config_data["mcpServers"] = {}
            
        # Default template
        self.config_data["mcpServers"][name] = {
            "command": "python",
            "args": []
        }
        self.refresh_list()
        # Select the new item
        items = self.server_list.findItems(name, Qt.MatchExactly)
        if items:
            self.server_list.setCurrentItem(items[0])
            self.edit_config.setFocus()

    def delete_server(self):
        row = self.server_list.currentRow()
        if row < 0:
            return
        name = self.server_list.item(row).text()
        
        reply = QMessageBox.question(self, '确认删除', 
                                     f"确定要删除服务器 '{name}' 吗?",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        
        if reply == QMessageBox.Yes:
            del self.config_data["mcpServers"][name]
            self.save_to_file()
            self.refresh_list()
            self.edit_config.clear()
            self.current_server_name = None  # Clear current selection

    def save_current_server(self):
        # 1. 检查是否有当前选中的服务器
        current_item = self.server_list.currentItem()
        
        # 2. 如果没有选中项（比如刚删除了），也没有记住的服务器名，
        # 并且文本框也是空的，说明用户删除了配置后直接想保存退出。
        # 这种情况下，因为删除操作本身已经写入文件了，所以我们可以直接退出。
        if not current_item and not self.current_server_name and not self.edit_config.toPlainText().strip():
             self.accept()
             return

        # 3. 如果没有选中项，但文本框有内容，提示用户需要先新增或选中一个服务器
        if not current_item and not self.current_server_name:
             QMessageBox.warning(self, "提示", "请先选择一个服务器或点击新增")
             return
            
        # 获取要保存的服务器名称
        if current_item:
            name = current_item.text()
        else:
            name = self.current_server_name
        
        try:
            # Parse JSON from text edit
            config_text = self.edit_config.toPlainText()
            if not config_text.strip():
                 # 文本框为空，如果是选中状态，可能是想清空配置？但我们不允许空配置
                 # 或者用户想放弃修改？但这是保存按钮。
                 # 我们假设如果为空，不做任何修改，直接退出（如果用户意图是删除，应该用删除按钮）
                 self.accept()
                 return

            new_config = json.loads(config_text)
            if not isinstance(new_config, dict):
                raise ValueError("配置必须是 JSON 对象")
                
            self.config_data["mcpServers"][name] = new_config
            self.save_to_file()
            
            # Close dialog and return success
            self.accept()
            
        except json.JSONDecodeError as e:
            QMessageBox.warning(self, "JSON 格式错误", f"无效的 JSON 格式:\n{str(e)}")
        except Exception as e:
            QMessageBox.warning(self, "保存失败", f"保存配置时出错:\n{str(e)}")

    def save_to_file(self):
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self.config_data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存配置文件失败: {str(e)}")
