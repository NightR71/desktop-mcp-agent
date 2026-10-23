"""异常类定义"""

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
