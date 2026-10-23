"""应用程序工厂"""

import logging
from typing import Optional

from Backend.config.manager import ConfigurationManager
from Backend.core.types import ServerConfig
from Backend.services.llm import AsyncLLMClient
from Backend.services.mcp_server import MCPServer, ToolRegistry
from Backend.session.chat_session import EnhancedChatSession
from Backend.utils.conversation import ConversationManager


class MCPClientFactory:
    """MCP客户端工厂"""
    
    @staticmethod
    async def create_client(config_file: str = "winmcp1.json", status_callback=None) -> Optional[EnhancedChatSession]:
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
            
            # 记录是否所有尝试初始化的服务器都失败了
            total_servers = len(servers_data)
            failed_servers = 0
            
            for name, srv_config in servers_data.items():
                try:
                    server_config_obj = ServerConfig(name=name, config=srv_config)
                    server = MCPServer(server_config_obj)
                    
                    if await server.initialize():
                        tool_registry.add_server(server)
                        logging.info(f"📝 服务器 {name} 配置成功 ({server_config_obj.connection_type.value})")
                    else:
                        logging.error(f"❌ 服务器 {name} 初始化失败")
                        failed_servers += 1
                        
                except Exception as e:
                    logging.error(f"❌ 配置服务器 {name} 失败: {e}")
                    failed_servers += 1
                    continue
            
            # 如果有任何一个服务器失败，我们认为整个初始化是不完美的
            if failed_servers > 0:
                error_msg = f"{failed_servers}/{total_servers} 个服务器初始化失败"
                logging.error(f"❌ {error_msg}")
                # 在这里，我们抛出异常以便上层捕获并显示具体的错误信息
                raise Exception(error_msg)
            
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
                conversation_manager=conversation_manager,
                status_callback=status_callback
            )
            
            return chat_session
            
        except Exception as e:
            logging.error(f"❌ 创建MCP客户端失败: {e}")
            return None