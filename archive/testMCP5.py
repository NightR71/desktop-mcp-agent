import asyncio
import json
import logging
import os
import re
import sys
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple, Union
from dotenv import load_dotenv
import shutil
from datetime import timedelta
from contextlib import AsyncExitStack

# 需要安装的MCP相关库
try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.client.sse import sse_client
    from mcp.client.streamable_http import streamablehttp_client
except ImportError:
    logging.error("请安装MCP库: pip install mcp")
    sys.exit(1)

# 需要安装的LLM客户端库
try:
    from openai import OpenAI
    # 假设您有自定义的ZhipuAiClient
    from zai import ZhipuAiClient
except ImportError:
    logging.error("请安装OpenAI库: pip install openai")
    sys.exit(1)

# 配置日志格式
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler()
    ]
)


class Configuration:
    """管理MCP客户端的配置和环境变量"""
    def __init__(self) -> None:
        """使用环境变量初始化配置。"""
        self.load_env()
        self.api_key = os.getenv("Zai_API_KEY")

    @staticmethod
    def load_env() -> None:
        """加载环境变量"""
        load_dotenv()

    @staticmethod
    def load_config(file_path: str) -> dict[str, Any]:
        """从指定的JSON文件加载配置"""
        try:
            with open(file_path, 'r', encoding='utf-8') as file:
                return json.load(file)
        except Exception as e:
            logging.error(f"无法加载配置文件 {file_path}: {e}")
            return {}

    @property
    def get_api_key(self) -> str:
        """获取API密钥"""
        if not self.api_key:
            raise ValueError("API key 未设置. 请重新设置 Zai_API_KEY 变量")
        return self.api_key


class Server:
    """管理MCP连接及工具执行过程"""
    def __init__(self, name: str, config: dict[str, Any]) -> None:
        self.name = name
        self.config: dict[str, Any] = config
        self.session: ClientSession | None = None
        self._cleanup_lock: asyncio.Lock = asyncio.Lock()
        self.exit_stack: AsyncExitStack = AsyncExitStack()
        self.connection_type = self._determine_connection_type()
        self.tools: List[Any] = []

    def _determine_connection_type(self) -> str:
        """确定连接类型：stdio、sse或streamable_http。"""
        if "url" in self.config:
            return self.config.get("type", "streamable_http")
        elif "command" in self.config:
            return "stdio"
        else:
            raise ValueError(f"Invalid server configuration for {self.name}")

    async def initialize(self) -> bool:
        """根据配置类型初始化服务器连接。"""
        logging.info(f"Initializing server {self.name} with type: {self.connection_type}")

        try:
            if self.connection_type == "stdio":
                await self._initialize_stdio()
            elif self.connection_type == "sse":
                await self._initialize_sse()
            elif self.connection_type == "streamable_http":
                await self._initialize_streamable_http()
            else:
                raise ValueError(f"Unsupported connection type: {self.connection_type}")
            
            # 初始化后获取工具列表
            self.tools = await self.list_tools()
            return True
            
        except Exception as e:
            logging.error(f"Error initializing server {self.name}: {e}")
            await self.cleanup()
            return False

    async def _initialize_stdio(self) -> None:
        """初始化stdio连接。"""
        if self.config["command"] == "npx":
            command = shutil.which("npx")
        elif self.config["command"] == "uvx":
            command = shutil.which("uvx")
        else:
            command = self.config["command"]

        if command is None:
            raise ValueError(f"The command {self.config['command']} must be a valid string and cannot be None.")

        server_params = StdioServerParameters(
            command=command,
            args=self.config["args"],
            env={**os.environ, **self.config["env"]}
            if self.config.get("env")
            else None,
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
        """初始化SSE连接。"""
        server_url = self.config["url"]

        sse_transport = await self.exit_stack.enter_async_context(
            sse_client(
                url=server_url,
                timeout=60,
            )
        )
        read_stream, write_stream = sse_transport
        session = await self.exit_stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        await session.initialize()
        self.session = session

    async def _initialize_streamable_http(self) -> None:
        """初始化StreamableHTTP连接。"""
        server_url = self.config["url"]

        http_transport = await self.exit_stack.enter_async_context(
            streamablehttp_client(
                url=server_url,
                timeout=timedelta(seconds=60),
            )
        )
        read_stream, write_stream, get_session_id = http_transport
        session = await self.exit_stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        await session.initialize()
        self.session = session

    async def list_tools(self) -> list[Any]:
        """列出服务器中可用的工具。

        Returns:
            可用工具的列表。

        Raises:
            RuntimeError: 如果服务器未初始化。
        """
        if not self.session:
            raise RuntimeError(f"Server {self.name} not initialized")

        try:
            tools_response = await self.session.list_tools()
            tools = []

            for item in tools_response:
                if isinstance(item, tuple) and item[0] == "tools":
                    tools.extend(
                        Tool(tool.name, tool.description, tool.inputSchema, tool.title)
                        for tool in item[1]
                    )

            return tools
        except Exception as e:
            logging.error(f"Error listing tools from server {self.name}: {e}")
            return []

    async def execute_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        retries: int = 2,
        delay: float = 1.0,
    ) -> Any:
        """使用重试机制执行工具。

        Args:
            tool_name: 要执行的工具名称。
            arguments: 工具参数。
            retries: 重试次数。
            delay: 重试间隔时间（秒）。

        Returns:
            工具执行结果。

        Raises:
            RuntimeError: 如果服务器未初始化。
            Exception: 如果工具执行在所有重试后仍然失败。
        """
        if not self.session:
            raise RuntimeError(f"Server {self.name} not initialized")

        attempt = 0
        while attempt <= retries:
            try:
                logging.info(f"Executing {tool_name}...")
                result = await self.session.call_tool(tool_name, arguments)
                logging.info(f"Tool {tool_name} executed successfully.")
                return result
            except Exception as e:
                attempt += 1
                logging.warning(
                    f"Error executing tool: {e}. Attempt {attempt} of {retries}."
                )
                if attempt <= retries:
                    logging.info(f"Retrying in {delay} seconds...")
                    await asyncio.sleep(delay)
                else:
                    logging.error("Max retries reached. Failing.")
                    raise

    async def cleanup(self) -> None:
        """清理服务器资源。"""
        async with self._cleanup_lock:
            try:
                await self.exit_stack.aclose()
                self.session = None
            except Exception as e:
                logging.error(f"Error during cleanup of server {self.name}: {e}")


class Tool:
    """工具的类统一"""
    def __init__(
            self,
            name: str,
            description: str,
            input_schema: dict[str, Any],
            title: str | None = None,
        ) -> None:
        self.name: str = name
        self.description: str = description
        self.input_schema: dict[str, Any] = input_schema
        self.title: str | None = title

    def format_for_llm(self) -> str:
        """格式化工具信息以供LLM使用"""
        args_desc = []
        if "properties" in self.input_schema:
            for param_name, param_info in self.input_schema["properties"].items():
                arg_desc = (
                    f"- {param_name}: {param_info.get('description', 'No description')}"
                )
                if param_name in self.input_schema.get("required", []):
                    arg_desc += " (required)"
                args_desc.append(arg_desc)

        # 构建格式化输出，标题作为单独字段
        output = f"Tool: {self.name}\n"
        # 如果有可读标题则添加
        if self.title:
            output += f"User-readable title: {self.title}\n"

        output += f"""Description: {self.description}
Arguments:
{chr(10).join(args_desc)}
"""

        return output



class LLMClient:
    """管理与LLM提供商的通信。"""

    def __init__(self, api_key: str) -> None:
        self.client = ZhipuAiClient(api_key=api_key)

    def get_response(self, messages: list[dict[str, str]]) -> str:
        """从LLM获取响应。

        Args:
            messages: 消息字典列表。

        Returns:
            LLM的响应字符串。

        Raises:
            Exception: 如果向LLM的请求失败。
        """
        try:
            response = self.client.chat.completions.create(
                model="glm-4.5",
                messages=messages,
                temperature=0.7,
                max_tokens=2000,
                stream=False,
            )

            return response.choices[0].message.content
        except Exception as e:
            error_message = f"Error getting LLM response: {str(e)}"
            logging.error(error_message)
            return (
                f"I encountered an error: {error_message}. "
                "Please try again or rephrase your request."
            )


class ChatSession:
    """协调用户、LLM和工具之间的交互。"""

    def __init__(self, servers: list[Server], llm_client: LLMClient) -> None:
        self.servers: list[Server] = servers
        self.llm_client: LLMClient = llm_client
        self.all_tools: List[Any] = []

    async def cleanup_servers(self) -> None:
        """正确清理所有服务器。"""
        for server in reversed(self.servers):
            try:
                await server.cleanup()
            except Exception as e:
                logging.warning(f"Warning during final cleanup: {e}")

    def extract_json_from_response(self, response: str) -> Optional[Dict[str, Any]]:
        """从LLM响应中提取JSON内容"""
        try:
            # 尝试找到JSON开始和结束的位置
            json_start = response.find('{')
            json_end = response.rfind('}')
            
            if json_start == -1 or json_end == -1 or json_end < json_start:
                return None
                
            json_str = response[json_start:json_end+1]
            return json.loads(json_str)
        except json.JSONDecodeError:
            return None

    async def process_tool_call(self, tool_call: Dict[str, Any]) -> str:
        """处理单个工具调用"""
        tool_name = tool_call.get("name") or tool_call.get("tool")
        if not tool_name:
            return "错误: 工具调用中没有指定工具名称"
        
        arguments = tool_call.get("parameters") or tool_call.get("arguments") or {}
        
        logging.info(f"执行工具: {tool_name}")
        logging.info(f"参数: {arguments}")

        # 查找合适的服务器执行工具
        for server in self.servers:
            if any(tool.name == tool_name for tool in server.tools):
                try:
                    result = await server.execute_tool(tool_name, arguments)
                    return f"工具执行成功: {result}"
                except Exception as e:
                    return f"工具执行错误: {str(e)}"

        return f"找不到工具: {tool_name}"

    async def process_llm_response(self, llm_response: str, messages: List[Dict[str, str]]) -> Tuple[str, bool]:
        """处理LLM响应并在需要时执行工具"""
        # 尝试提取JSON
        json_data = self.extract_json_from_response(llm_response)
        
        if not json_data:
            return llm_response, False
        
        # 检查是否是工具调用格式
        if "tool_calls" in json_data:
            # MCP标准格式
            tool_calls = json_data["tool_calls"]
            if not tool_calls:
                return llm_response, False
            
            # 处理第一个工具调用
            tool_result = await self.process_tool_call(tool_calls[0])
            return tool_result, True
            
        elif "tool" in json_data and "arguments" in json_data:
            # 旧格式兼容
            tool_result = await self.process_tool_call(json_data)
            return tool_result, True
        
        return llm_response, False

    async def long_running_tool(self, messages: List[Dict[str, str]], llm_response: str, depth: int = 0) -> None:
        """处理多工具调用链，添加深度限制防止无限递归"""
        if depth > 100:  # 防止无限递归
            print(f"\nAssistant: 工具调用深度超过限制，请简化您的请求")
            messages.append({"role": "assistant", "content": "工具调用深度超过限制，请简化您的请求"})
            return

        try:
            # 处理LLM响应
            result, is_tool_call = await self.process_llm_response(llm_response, messages)
            
            if is_tool_call:
                # 添加助手消息到历史
                messages.append({"role": "assistant", "content": llm_response})
                # 添加工具执行结果到历史
                messages.append({"role": "user", "content": f"工具执行结果: {result}"})
                
                # 获取LLM对工具结果的响应
                next_response = self.llm_client.get_response(messages)
                # 递归处理可能的进一步工具调用
                await self.long_running_tool(messages, next_response, depth + 1)
            else:
                # 这是普通回复，直接显示
                print(f"\nAssistant: {llm_response}")
                messages.append({"role": "assistant", "content": llm_response})
                
        except Exception as e:
            logging.error(f"Error during long-running tool execution: {e}")
            error_msg = f"处理工具时出错: {str(e)}"
            print(f"\nAssistant: {error_msg}")
            messages.append({"role": "assistant", "content": error_msg})

    async def start(self) -> None:
        """主聊天会话处理器。"""
        try:
            # 初始化所有服务器并获取工具
            for server in self.servers:
                if await server.initialize():
                    self.all_tools.extend(server.tools)
                    logging.info(f"✅ Successfully initialized server: {server.name} with {len(server.tools)} tools")
                else:
                    logging.error(f"❌ Failed to initialize server: {server.name}")

            if not self.all_tools:
                logging.error("❌ No tools available from any server. Exiting.")
                return

            # 构建系统消息
            tools_description = "\n".join([tool.format_for_llm() for tool in self.all_tools])
            
            system_message = (
                "你是一个有帮助的AI助手，可以使用以下工具：\n\n"
                f"{tools_description}\n\n"
                "当需要使用工具时，请严格按照以下JSON格式响应：\n"
                "{\n"
                '  "tool_calls": [\n'
                '    {\n'
                '      "name": "工具名称",\n'
                '      "id": "唯一标识符",\n'
                '      "parameters": {\n'
                '        "参数名": "参数值"\n'
                '      }\n'
                '    }\n'
                '  ]\n'
                "}\n\n"
                "重要规则：\n"
                "1. 只返回有效的JSON，不要包含其他内容\n"
                "2. 不要使用代码块包装JSON\n"
                "3. 确保所有字符串都有引号\n"
                "4. 如果不使用工具，请用自然语言直接回答"
            )

            messages = [{"role": "system", "content": system_message}]

            logging.info("🎯 MCP客户端已启动")
            logging.info(f"📊 可用工具数量: {len(self.all_tools)}")
            logging.info("💬 输入 'quit' 或 'exit' 结束会话\n")

            while True:
                try:
                    user_input = input("You: ").strip()
                    if user_input.lower() in ["quit", "exit"]:
                        logging.info("\n👋 正在退出...")
                        break

                    messages.append({"role": "user", "content": user_input})

                    llm_response = self.llm_client.get_response(messages)
                    await self.long_running_tool(messages, llm_response)

                except KeyboardInterrupt:
                    logging.info("\n\n👋 再见！")
                    break

        finally:
            await self.cleanup_servers()


async def main() -> None:
    """初始化并运行聊天会话。"""
    config = Configuration()
    # server_config = config.load_config("omnimcp.json")
    server_config = config.load_config("winmcp2.json")
    
    if not server_config:
        logging.error("❌ 无法加载服务器配置")
        return
    
    servers = []
    for name, srv_config in server_config.get("mcpServers", {}).items():
        try:
            server = Server(name, srv_config)
            servers.append(server)
            logging.info(f"📝 配置服务器: {name} ({server.connection_type})")
        except Exception as e:
            logging.error(f"❌ 配置服务器 {name} 失败: {e}")
            continue
    
    if not servers:
        logging.error("❌ 没有有效的服务器配置")
        return
    
    try:
        llm_client = LLMClient(config.get_api_key)
        chat_session = ChatSession(servers, llm_client)
        await chat_session.start()
    except Exception as e:
        logging.error(f"❌ 启动聊天会话失败: {e}")


if __name__ == "__main__":
    asyncio.run(main())