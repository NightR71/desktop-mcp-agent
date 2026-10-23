from mcp.server.fastmcp import FastMCP, Context
from mcp.server.session import ServerSession
mcp = FastMCP("Context")  # 服务名称

@mcp.tool()
def get_context(ctx: Context[ServerSession, None]) -> str:
    """获取当前上下文信息"""

    return "This is the current context information."
