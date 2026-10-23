"""优化版MCP客户端实现

这是一个重构后的MCP客户端，解决了原版本中的架构、性能和代码质量问题。
主要改进：
- 清晰的分层架构和职责分离
- 更好的错误处理和恢复机制
- 异步性能优化
- 配置管理和依赖注入
- 符合Python最佳实践
"""

import asyncio
import json
import logging
import os
import sys
from abc import ABC, abstractmethod
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from datetime import timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Tuple, Union
import shutil

from dotenv import load_dotenv

# MCP相关导入
try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.client.sse import sse_client
    from mcp.client.streamable_http import streamablehttp_client
except ImportError as e:
    logging.error(f"请安装MCP库: pip install mcp - {e}")
    sys.exit(1)

# LLM客户端导入
try:
    from zai import ZhipuAiClient
    from openai import OpenAI
except ImportError as e:
    logging.error(f"请安装ZAI库 - {e}")
    sys.exit(1)


# 配置和常量
class Constants:
    """应用常量"""
    DEFAULT_RETRY_COUNT = 3
    DEFAULT_RETRY_DELAY = 1.0
    DEFAULT_TIMEOUT = 60
    MAX_CONVERSATION_DEPTH = 50
    MAX_MESSAGE_HISTORY = 100
    DEFAULT_TEMPERATURE = 0.7
    DEFAULT_MAX_TOKENS = 2000


class ConnectionType(Enum):
    """连接类型枚举"""
    STDIO = "stdio"
    SSE = "sse"
    STREAMABLE_HTTP = "streamable_http"


# 异常类定义
class MCPClientError(Exception):
    """MCP客户端基础异常"""
    pass


class ServerInitializationError(MCPClientError):
    """服务器初始化异常"""
    pass


class ToolExecutionError(MCPClientError):
    """工具执行异常"""
    pass


class ConfigurationError(MCPClientError):
    """配置异常"""
    pass


# 数据类定义
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


# 协议定义
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


# 配置管理
class ConfigurationManager:
    """配置管理器"""
    
    def __init__(self, config_file: Optional[str] = None):
        self._load_environment()
        self.config_file = config_file
        self._config_cache: Dict[str, Any] = {}

    def _load_environment(self) -> None:
        """加载环境变量"""
        load_dotenv()

    def get_api_key(self, key_name: str = "MODELSCOPE_API_KEY") -> str:
        """获取API密钥"""
        api_key = os.getenv(key_name)
        if not api_key:
            raise ConfigurationError(f"API key '{key_name}' not found in environment variables")
        return api_key

    def load_server_config(self, file_path: str) -> Dict[str, Any]:
        """加载服务器配置"""
        if file_path in self._config_cache:
            return self._config_cache[file_path]

        try:
            config_path = Path(file_path)
            if not config_path.exists():
                raise ConfigurationError(f"Configuration file not found: {file_path}")
            
            with open(config_path, 'r', encoding='utf-8') as file:
                config = json.load(file)
                self._config_cache[file_path] = config
                return config
        except json.JSONDecodeError as e:
            raise ConfigurationError(f"Invalid JSON in configuration file {file_path}: {e}")
        except Exception as e:
            raise ConfigurationError(f"Failed to load configuration file {file_path}: {e}")


# LLM客户端实现
class AsyncLLMClient:
    """异步LLM客户端"""
    
    def __init__(self, api_key: str, model: str = "Qwen/Qwen3-VL-30B-A3B-Instruct", base_url="https://api-inference.modelscope.cn/v1/"):
        # self.client = ZhipuAiClient(api_key=api_key)
        # model = "glm-4.6"
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model
        self.default_params = {
            "temperature": Constants.DEFAULT_TEMPERATURE,
            "max_tokens": Constants.DEFAULT_MAX_TOKENS,
            "stream": False
        }

    async def get_response(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """获取LLM响应"""
        params = {**self.default_params, **kwargs}
        
        try:
            # 在实际异步环境中，这里应该使用真正的异步调用
            response = await asyncio.get_event_loop().run_in_executor(
                None, 
                lambda: self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    **params
                )
            )
            return response.choices[0].message.content
        except Exception as e:
            error_msg = f"LLM request failed: {str(e)}"
            logging.error(error_msg)
            raise MCPClientError(error_msg) from e


# 服务器管理
class MCPServer:
    """MCP服务器管理器"""
    
    def __init__(self, config: ServerConfig):
        self.config = config
        self.session: Optional[ClientSession] = None
        self.tools: List[ToolSchema] = []
        self.exit_stack = AsyncExitStack()
        self._cleanup_lock = asyncio.Lock()
        self._is_initialized = False

    @property
    def name(self) -> str:
        return self.config.name

    @property
    def is_initialized(self) -> bool:
        return self._is_initialized

    async def initialize(self) -> bool:
        """初始化服务器连接"""
        if self._is_initialized:
            return True

        logging.info(f"Initializing server {self.name} with type: {self.config.connection_type.value}")
        
        try:
            await self._establish_connection()
            self.tools = await self._load_tools()
            self._is_initialized = True
            logging.info(f"✅ Server {self.name} initialized with {len(self.tools)} tools")
            return True
        except Exception as e:
            logging.error(f"❌ Failed to initialize server {self.name}: {e}")
            await self.cleanup()
            return False

    async def _establish_connection(self) -> None:
        """建立连接"""
        connection_handlers = {
            ConnectionType.STDIO: self._initialize_stdio,
            ConnectionType.SSE: self._initialize_sse,
            ConnectionType.STREAMABLE_HTTP: self._initialize_streamable_http
        }
        
        handler = connection_handlers.get(self.config.connection_type)
        if not handler:
            raise ServerInitializationError(f"Unsupported connection type: {self.config.connection_type}")
        
        await handler()

    async def _initialize_stdio(self) -> None:
        """初始化stdio连接"""
        command = self.config.config["command"]
        if command in ["npx", "uvx"]:
            command = shutil.which(command)
        
        if not command:
            raise ServerInitializationError(f"Command not found: {self.config.config['command']}")

        server_params = StdioServerParameters(
            command=command,
            args=self.config.config.get("args", []),
            env={**os.environ, **self.config.config.get("env", {})}
        )

        stdio_transport = await self.exit_stack.enter_async_context(
            stdio_client(server_params)
        )
        read, write = stdio_transport
        session = await self.exit_stack.enter_async_context(
            ClientSession(read, write)
        )
        await session.initialize()
        self.session = session

    async def _initialize_sse(self) -> None:
        """初始化SSE连接"""
        server_url = self.config.config["url"]
        sse_transport = await self.exit_stack.enter_async_context(
            sse_client(url=server_url, timeout=self.config.timeout)
        )
        read_stream, write_stream = sse_transport
        session = await self.exit_stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        await session.initialize()
        self.session = session

    async def _initialize_streamable_http(self) -> None:
        """初始化StreamableHTTP连接"""
        server_url = self.config.config["url"]
        http_transport = await self.exit_stack.enter_async_context(
            streamablehttp_client(
                url=server_url,
                timeout=timedelta(seconds=self.config.timeout)
            )
        )
        read_stream, write_stream, _ = http_transport
        session = await self.exit_stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        await session.initialize()
        self.session = session

    async def _load_tools(self) -> List[ToolSchema]:
        """加载工具列表"""
        if not self.session:
            raise ServerInitializationError(f"Server {self.name} session not initialized")

        try:
            tools_response = await self.session.list_tools()
            tools = []
            
            for item in tools_response:
                if isinstance(item, tuple) and item[0] == "tools":
                    tools.extend(
                        ToolSchema(
                            name=tool.name,
                            description=tool.description,
                            input_schema=tool.inputSchema,
                            title=getattr(tool, 'title', None)
                        )
                        for tool in item[1]
                    )
            
            return tools
        except Exception as e:
            logging.error(f"Failed to load tools from server {self.name}: {e}")
            return []

    async def execute_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """执行工具"""
        if not self.session:
            raise ToolExecutionError(f"Server {self.name} not initialized")

        for attempt in range(self.config.retry_count):
            try:
                logging.info(f"Executing tool {tool_name} on server {self.name} (attempt {attempt + 1})")
                result = await self.session.call_tool(tool_name, arguments)
                logging.info(f"Tool {tool_name} executed successfully")
                return result
            except Exception as e:
                if attempt == self.config.retry_count - 1:
                    raise ToolExecutionError(f"Tool execution failed after {self.config.retry_count} attempts: {e}")
                logging.warning(f"Tool execution attempt {attempt + 1} failed: {e}. Retrying...")
                await asyncio.sleep(self.config.retry_delay)

    async def cleanup(self) -> None:
        """清理资源"""
        async with self._cleanup_lock:
            try:
                await self.exit_stack.aclose()
                self.session = None
                self._is_initialized = False
            except Exception as e:
                logging.error(f"Error during cleanup of server {self.name}: {e}")


# 工具注册表
class ToolRegistry:
    """工具注册表"""
    
    def __init__(self):
        self.servers: List[MCPServer] = []
        self._tool_cache: Dict[str, MCPServer] = {}

    def add_server(self, server: MCPServer) -> None:
        """添加服务器"""
        self.servers.append(server)
        # 更新工具缓存
        for tool in server.tools:
            self._tool_cache[tool.name] = server

    def get_all_tools(self) -> List[ToolSchema]:
        """获取所有工具"""
        tools = []
        for server in self.servers:
            tools.extend(server.tools)
        return tools

    async def execute_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """执行工具"""
        server = self._tool_cache.get(tool_name)
        if not server:
            raise ToolExecutionError(f"Tool '{tool_name}' not found")
        
        return await server.execute_tool(tool_name, arguments)

    async def cleanup_all(self) -> None:
        """清理所有服务器"""
        for server in reversed(self.servers):
            await server.cleanup()


# 响应解析器
class ResponseParser:
    """LLM响应解析器"""
    
    @staticmethod
    def extract_json(response: str) -> Optional[Dict[str, Any]]:
        """从响应中提取JSON"""
        try:
            # 寻找JSON边界
            start = response.find('{')
            end = response.rfind('}') + 1
            
            if start == -1 or end == 0 or end <= start:
                return None
            
            json_str = response[start:end]
            return json.loads(json_str)
        except (json.JSONDecodeError, ValueError):
            return None

    @staticmethod
    def parse_tool_calls(json_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """解析工具调用"""
        tool_calls = []
        
        # 标准格式
        if "tool_calls" in json_data and isinstance(json_data["tool_calls"], list):
            tool_calls.extend(json_data["tool_calls"])
        
        # 兼容格式
        elif "tool" in json_data and "arguments" in json_data:
            tool_calls.append({
                "name": json_data["tool"],
                "parameters": json_data["arguments"]
            })
        
        return tool_calls


# 对话管理器
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


# 主要的聊天会话类
class EnhancedChatSession:
    """增强的聊天会话"""
    
    def __init__(
        self,
        llm_client: AsyncLLMClient,
        tool_registry: ToolRegistry,
        conversation_manager: ConversationManager
    ):
        self.llm_client = llm_client
        self.tool_registry = tool_registry
        self.conversation_manager = conversation_manager
        self.response_parser = ResponseParser()
        self._running = False

    async def initialize(self) -> bool:
        """初始化会话"""
        tools = self.tool_registry.get_all_tools()
        if not tools:
            logging.error("❌ No tools available")
            return False

        # 构建系统消息
        system_message = self._build_system_message(tools)
        self.conversation_manager.add_message("system", system_message)
        
        logging.info(f"🎯 Enhanced MCP Client initialized with {len(tools)} tools")
        return True

    def _build_system_message(self, tools: List[ToolSchema]) -> str:
        """构建系统消息"""
        tools_description = "\n".join(tool.format_for_llm() for tool in tools)
        
        return f"""你是一个智能AI助手，可以使用以下工具：

{tools_description}

当需要使用工具时，请严格按照以下JSON格式响应：
{{
  "tool_calls": [
    {{
      "name": "工具名称",
      "id": "唯一标识符",
      "parameters": {{
        "参数名": "参数值"
      }}
    }}
  ]
}}

重要规则：
1. 只返回有效的JSON，不要包含其他内容
2. 不要使用代码块包装JSON
3. 确保所有字符串都有引号
4. 如果不使用工具，请用自然语言直接回答
5. 可以同时调用多个工具"""

    async def process_user_input(self, user_input: str) -> None:
        """处理用户输入"""
        self.conversation_manager.add_message("user", user_input)
        
        try:
            await self._handle_conversation_turn()
        except Exception as e:
            error_msg = f"处理用户输入时出错: {str(e)}"
            logging.error(error_msg)
            print(f"\nAssistant: {error_msg}")
            self.conversation_manager.add_message("assistant", error_msg)

    async def _handle_conversation_turn(self, depth: int = 0) -> None:
        """处理对话轮次"""
        if depth > Constants.MAX_CONVERSATION_DEPTH:
            error_msg = "对话深度超过限制，请简化您的请求"
            print(f"\nAssistant: {error_msg}")
            self.conversation_manager.add_message("assistant", error_msg)
            return

        # 获取LLM响应
        messages = self.conversation_manager.get_messages_for_llm()
        llm_response = await self.llm_client.get_response(messages)
        
        # 解析响应
        json_data = self.response_parser.extract_json(llm_response)
        
        if json_data:
            tool_calls = self.response_parser.parse_tool_calls(json_data)
            if tool_calls:
                # 处理工具调用
                await self._execute_tool_calls(llm_response, tool_calls, depth)
                return
        
        # 普通响应
        print(f"\nAssistant: {llm_response}")
        self.conversation_manager.add_message("assistant", llm_response)

    async def _execute_tool_calls(
        self, 
        original_response: str, 
        tool_calls: List[Dict[str, Any]], 
        depth: int
    ) -> None:
        """执行工具调用"""
        self.conversation_manager.add_message("assistant", original_response)
        
        # 执行所有工具调用
        results = []
        for tool_call in tool_calls:
            try:
                result = await self._execute_single_tool_call(tool_call)
                results.append(f"工具 {tool_call.get('name', 'unknown')} 执行成功: {result}")
            except Exception as e:
                error_msg = f"工具 {tool_call.get('name', 'unknown')} 执行失败: {str(e)}"
                results.append(error_msg)
                logging.error(error_msg)

        # 自动使用State-Tool进行验证
        try:
            state_tool_name = "State-Tool"  # 假设工具名称为"State-Tool"，根据实际调整
            state_args = {"use_vision": True}
            state_result = await self.tool_registry.execute_tool(state_tool_name, state_args)
            results.append(f"State-Tool 验证 (use_vision=True): {state_result}")
        except Exception as e:
            results.append(f"State-Tool 验证失败: {str(e)}")

        # 添加工具结果到对话
        tool_results_message = "\n".join(results)
        self.conversation_manager.add_message("tool", tool_results_message)
        
        # 继续下一轮对话
        await self._handle_conversation_turn(depth + 1)

    async def _execute_single_tool_call(self, tool_call: Dict[str, Any]) -> Any:
        """执行单个工具调用"""
        tool_name = tool_call.get("name")
        if not tool_name:
            raise ToolExecutionError("工具调用中没有指定工具名称")
        
        arguments = tool_call.get("parameters", tool_call.get("arguments", {}))
        
        logging.info(f"Executing tool: {tool_name} with arguments: {arguments}")
        return await self.tool_registry.execute_tool(tool_name, arguments)

    async def start_interactive_session(self) -> None:
        """启动交互式会话"""
        if not await self.initialize():
            return
        
        self._running = True
        print("💬 输入 'quit' 或 'exit' 结束会话\n")
        
        try:
            while self._running:
                try:
                    user_input = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: input("You: ").strip()
                    )
                    
                    if user_input.lower() in ["quit", "exit"]:
                        print("\n👋 正在退出...")
                        break
                    
                    if user_input:
                        await self.process_user_input(user_input)
                        
                except KeyboardInterrupt:
                    print("\n\n👋 再见！")
                    break
                except Exception as e:
                    logging.error(f"Session error: {e}")
                    print(f"\n发生错误: {e}")
        finally:
            await self.cleanup()

    async def cleanup(self) -> None:
        """清理资源"""
        self._running = False
        await self.tool_registry.cleanup_all()


# 应用程序工厂
class MCPClientFactory:
    """MCP客户端工厂"""
    
    @staticmethod
    async def create_client(config_file: str = "winmcp2.json") -> Optional[EnhancedChatSession]:
        """创建MCP客户端"""
        try:
            # 初始化配置管理器
            config_manager = ConfigurationManager()
            
            # 加载服务器配置
            server_config = config_manager.load_server_config(config_file)
            if not server_config:
                logging.error("❌ 无法加载服务器配置")
                return None
            
            # 创建工具注册表
            tool_registry = ToolRegistry()
            
            # 初始化服务器
            servers_data = server_config.get("mcpServers", {})
            if not servers_data:
                logging.error("❌ 配置文件中没有找到服务器配置")
                return None
            
            for name, srv_config in servers_data.items():
                try:
                    server_config_obj = ServerConfig(name=name, config=srv_config)
                    server = MCPServer(server_config_obj)
                    
                    if await server.initialize():
                        tool_registry.add_server(server)
                        logging.info(f"📝 服务器 {name} 配置成功 ({server_config_obj.connection_type.value})")
                    else:
                        logging.error(f"❌ 服务器 {name} 初始化失败")
                except Exception as e:
                    logging.error(f"❌ 配置服务器 {name} 失败: {e}")
                    continue
            
            if not tool_registry.get_all_tools():
                logging.error("❌ 没有可用的工具")
                return None
            
            # 创建LLM客户端
            api_key = config_manager.get_api_key()
            llm_client = AsyncLLMClient(api_key)
            
            # 创建对话管理器
            conversation_manager = ConversationManager()
            
            # 创建聊天会话
            chat_session = EnhancedChatSession(
                llm_client=llm_client,
                tool_registry=tool_registry,
                conversation_manager=conversation_manager
            )
            
            return chat_session
            
        except Exception as e:
            logging.error(f"❌ 创建MCP客户端失败: {e}")
            return None


# 主函数
async def main() -> None:
    """主函数"""
    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler()]
    )
    
    try:
        client = await MCPClientFactory.create_client()
        if client:
            await client.start_interactive_session()
        else:
            logging.error("❌ 无法创建MCP客户端")
    except Exception as e:
        logging.error(f"❌ 应用程序启动失败: {e}")


if __name__ == "__main__":
    asyncio.run(main())