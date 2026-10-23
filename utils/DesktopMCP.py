import os
from mcp.server.fastmcp import FastMCP, Context
from pathlib import Path
from mcp.server.session import ServerSession


mcp = FastMCP("FileSystem")  # 服务名称

@mcp.tool()
def get_user_desktop_files() -> list:
    """获取当前用户的桌面文件列表（支持Windows/macOS/Linux）"""
    return os.listdir(os.path.expanduser("~/Desktop"))

@mcp.tool()
def read_user_desktop_directory() -> str:
    """
    获取用户桌面路径，
    """
    desktop_path = Path(os.path.expanduser("~/Desktop"))
    return f"{desktop_path}"

@mcp.tool()
def get_public_desktop_files() -> list:
    """
    获取公共桌面和用户桌面的文件列表
    若无特殊说明，默认获取桌面文件时使用该工具。
    """

    file_set = set()
    
    # 获取用户桌面
    try:
        user_desktop = Path(os.path.join(os.environ['USERPROFILE'], 'Desktop'))
        if user_desktop.exists():
            for item in user_desktop.iterdir():
                file_set.add(item.name)
    except KeyError:
        pass
    
    # 获取公共桌面 - 尝试多种方式
    public_desktop_paths = [
        os.path.join(os.environ.get('PUBLIC', ''), 'Desktop'),
        os.path.join(os.environ.get('ALLUSERSPROFILE', ''), 'Desktop'),
        r'C:\Users\Public\Desktop'
    ]

    
    for path_str in public_desktop_paths:
        if path_str and path_str != 'Desktop':  # 避免空路径
            try:
                public_desktop = Path(path_str)
                if public_desktop.exists():
                    for item in public_desktop.iterdir():
                        file_set.add(item.name)
                    break  # 找到一个有效路径就停止
            except Exception:
                continue

    return sorted(list(file_set))

if __name__ == "__main__":
    mcp.run(transport='stdio')  # 使用标准输入输出通信
