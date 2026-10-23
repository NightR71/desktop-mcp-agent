"""对话管理器"""

from typing import Dict, List

from Backend.config.settings import Constants
from Backend.core.types import ConversationMessage

class ConversationManager:
    """对话管理器"""
    
    def __init__(self, max_history: int = Constants.MAX_MESSAGE_HISTORY):
        self.messages: List[ConversationMessage] = []
        self.max_history = max_history

    def add_message(self, role: str, content: str) -> None:
        """添加消息"""
        message = ConversationMessage(role=role, content=content)
        self.messages.append(message)
        
        # 保持历史记录在限制范围内
        if len(self.messages) > self.max_history:
            # 保留系统消息和最近的消息
            system_messages = [msg for msg in self.messages if msg.role == "system"]
            recent_messages = self.messages[-(self.max_history - len(system_messages)):]
            self.messages = system_messages + [msg for msg in recent_messages if msg.role != "system"]

    def get_messages_for_llm(self) -> List[Dict[str, str]]:
        """获取用于LLM的消息格式"""
        return [msg.to_dict() for msg in self.messages]

    def clear_history(self) -> None:
        """清除历史记录（保留系统消息）"""
        system_messages = [msg for msg in self.messages if msg.role == "system"]
        self.messages = system_messages
