"""类型定义"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol

from Backend.config.settings import Constants
from Backend.core.exceptions import ConfigurationError

class ConnectionType(Enum):
    """连接类型枚举"""
    STDIO = "stdio"
    SSE = "sse"
    STREAMABLE_HTTP = "streamable_http"


@dataclass
class ToolSchema:
    """工具模式定义"""
    name: str
    description: str
    input_schema: Dict[str, Any]
    title: Optional[str] = None

    def format_for_llm(self) -> str:
        """格式化工具信息供LLM使用"""
        args_desc = []
        if "properties" in self.input_schema:
            for param_name, param_info in self.input_schema["properties"].items():
                arg_desc = f"- {param_name}: {param_info.get('description', 'No description')}"
                if param_name in self.input_schema.get("required", []):
                    arg_desc += " (required)"
                args_desc.append(arg_desc)

        output = f"Tool: {self.name}\n"
        if self.title:
            output += f"Title: {self.title}\n"
        output += f"Description: {self.description}\n"
        output += f"Arguments:\n{chr(10).join(args_desc)}\n"
        return output


@dataclass
class ServerConfig:
    """服务器配置"""
    name: str
    config: Dict[str, Any]
    connection_type: Optional[ConnectionType] = None
    retry_count: int = Constants.DEFAULT_RETRY_COUNT
    retry_delay: float = Constants.DEFAULT_RETRY_DELAY
    timeout: int = Constants.DEFAULT_TIMEOUT

    def __post_init__(self):
        if self.connection_type is None:
            self.connection_type = self._determine_connection_type()

    def _determine_connection_type(self) -> ConnectionType:
        """确定连接类型"""
        if "url" in self.config:
            return ConnectionType(self.config.get("type", "streamable_http"))
        elif "command" in self.config:
            return ConnectionType.STDIO
        else:
            raise ConfigurationError(f"Invalid server configuration for {self.name}")


@dataclass
class ConversationMessage:
    """对话消息"""
    role: str
    content: str
    timestamp: Optional[float] = None

    def to_dict(self) -> Dict[str, str]:
        return {"role": self.role, "content": self.content}


class LLMClientProtocol(Protocol):
    """LLM客户端协议"""
    async def get_response(self, messages: List[Dict[str, str]]) -> str:
        ...


class ToolRegistryProtocol(Protocol):
    """工具注册表协议"""
    def get_all_tools(self) -> List[ToolSchema]:
        ...

    async def execute_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        ...
