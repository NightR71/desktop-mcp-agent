"""MCP服务器管理器"""

import asyncio
import logging
import os
import shutil
import sys
from contextlib import AsyncExitStack
from datetime import timedelta
from typing import Any, Dict, List, Optional

from Backend.config.settings import Constants
from Backend.core.exceptions import ServerInitializationError, ToolExecutionError
from Backend.core.types import ConnectionType, ServerConfig, ToolSchema

# MCP相关导入
try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.client.sse import sse_client
    from mcp.client.streamable_http import streamablehttp_client
except ImportError as e:
    logging.error(f"请安装MCP库: pip install mcp - {e}")
    sys.exit(1)


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
                # 使用 aclose() 关闭所有 async context managers
                # 这会触发 transport 和 session 的清理
                await self.exit_stack.aclose()
            except BaseException as e:
                # 忽略 "Attempted to exit cancel scope..." 错误
                # 以及 GeneratorExit 等可能的异步清理异常
                error_str = str(e)
                if "cancel scope" not in error_str and not isinstance(e, GeneratorExit):
                     logging.error(f"Error during cleanup of server {self.name}: {e}")
            finally:
                self.session = None
                self._is_initialized = False


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
