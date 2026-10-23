

### 核心模块分布图

```text
d:\AiAgent\
├── main.py                     # [新增] 程序入口
├── config\
│   ├── settings.py             # 配置管理 & 常量 (ConfigurationManager, Constants)
│   └── __init__.py
├── core\
│   ├── exceptions.py           # [新增] 异常定义
│   ├── models.py               # [新增] 数据模型 (ServerConfig, ToolSchema, Enums)
│   ├── protocols.py            # [新增] 接口协议
│   ├── llm_client.py           # LLM 客户端 (AsyncLLMClient)
│   ├── server.py               # MCP 服务器 (MCPServer)
│   ├── tool_registry.py        # [新增] 工具注册表 (ToolRegistry)
│   ├── tools.py                # 工具类 (可选，可合并入 models.py)
│   ├── factory.py              # [新增] 客户端工厂 (MCPClientFactory)
│   └── __init__.py
├── session\
│   ├── chat_session.py         # 会话控制 (EnhancedChatSession)
│   ├── conversation.py         # [新增] 对话管理 (ConversationManager)
│   ├── response_parser.py      # [新增] 响应解析 (ResponseParser)
│   └── __init__.py
└── logs\                       # 日志目录
```
