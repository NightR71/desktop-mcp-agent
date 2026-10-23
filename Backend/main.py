"""主程序入口"""

import asyncio
import logging
import sys
import os

# 确保 Backend 包在路径中
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from Backend.factory import MCPClientFactory

async def main() -> None:
    """主函数"""
    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler()]
    )
    
    try:
        # 默认配置文件路径
        config_file = "winmcp1.json"
        
        # 尝试从命令行参数获取配置文件
        if len(sys.argv) > 1:
            config_file = sys.argv[1]
            
        client = await MCPClientFactory.create_client(config_file)
        if client:
            await client.start_interactive_session()
        else:
            logging.error("❌ 无法创建MCP客户端")
    except Exception as e:
        logging.error(f"❌ 应用程序启动失败: {e}")


if __name__ == "__main__":
    asyncio.run(main())
