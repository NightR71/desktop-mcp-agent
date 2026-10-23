# MCP_Cli 重构设计文档

**版本**: 1.0  
**日期**: 2025-12-12  
**状态**: 待评审

---

## 1. 重构目标与范围

### 1.1 重构目标
本项目旨在将现有的 MCP (Model Context Protocol) 客户端代码库重构为符合 `BesttestMCP6.py` 最佳实践的模块化、异步化、健壮的架构。核心目标包括：
1.  **架构解耦**: 将配置、核心逻辑、会话管理清晰分离，降低模块间耦合度。
2.  **异步升级**: 将 LLM 客户端通信和工具执行全面升级为异步 (`async/await`) 模式，提升并发性能。
3.  **健壮性增强**: 引入统一的异常处理体系、类型安全的数据模型 (Dataclasses) 和重试机制。
4.  **可维护性提升**: 通过协议 (Protocols) 定义接口，规范化代码结构，便于后续扩展。

### 1.2 重构范围
*   **配置层**: `config/` 文件夹及其内部逻辑。
*   **核心层**: `core/` 文件夹，涉及 Server、LLMClient、Tools 等核心组件。
*   **会话层**: `session/` 文件夹，涉及 ChatSession 及交互逻辑。
*   **入口**: 新增 `main.py` 及工厂模式实现。
*   **排除范围**: 第三方库 (`mcp`, `openai`, `zai`) 的内部实现。

---

## 2. 当前架构分析

### 2.1 现状描述
当前项目虽然已具备基本文件夹结构，但存在以下问题：
*   **职责不清**: `ChatSession` 类承担了响应解析、历史记录管理、工具执行等多重职责 (God Class)。
*   **同步阻塞**: `LLMClient` 使用同步调用，阻塞了事件循环，无法高效处理流式或并发任务。
*   **缺乏规范**: 缺乏统一的数据模型定义，大量使用原生 `dict` 传递数据，容易引发 KeyErrors 且缺乏类型提示。
*   **配置脆弱**: 配置加载逻辑简单，缺乏环境变量校验和默认值管理。
*   **异常处理缺失**: 缺乏自定义异常类，错误处理分散且不一致。

### 2.2 差距分析 (Gap Analysis)
| 功能领域 | 当前实现 | 目标实现 (Best Practice) | 差距 |
| :--- | :--- | :--- | :--- |
| **数据模型** | 字典 (`dict`) | 数据类 (`dataclass`) | 缺乏类型安全和结构化定义 |
| **并发模型** | 同步 (`sync`) | 异步 (`asyncio`) | 性能瓶颈，无法响应中断 |
| **接口定义** | 无 | 协议 (`Protocol`) | 依赖具体实现而非接口，难以测试 |
| **工具管理** | 耦合在 Server 中 | 独立注册表 (`ToolRegistry`) | 扩展性差，难以聚合多服务器工具 |
| **错误处理** | `print` / 通用 `Exception` | 自定义异常体系 (`MCPClientError`) | 错误定位困难，恢复机制弱 |

---

## 3. 重构方案设计

### 3.1 总体架构图 (Mermaid)

```mermaid
graph TD
    Main[main.py / Application Entry] --> Factory[MCPClientFactory]
    Factory --> ConfigMgr[ConfigurationManager]
    Factory --> ToolReg[ToolRegistry]
    Factory --> AsyncLLM[AsyncLLMClient]
    Factory --> Chat[EnhancedChatSession]
    
    Chat --> ConvMgr[ConversationManager]
    Chat --> RespParser[ResponseParser]
    Chat --> AsyncLLM
    Chat --> ToolReg
    
    ToolReg --> Server1[MCPServer (Stdio)]
    ToolReg --> Server2[MCPServer (SSE)]
    
    Server1 --> Models[Models / Dataclasses]
    Server2 --> Models
    
    subgraph Core Layer
        AsyncLLM
        ToolReg
        Server1
        Server2
        Models
        Protocols
        Exceptions
    end
    
    subgraph Session Layer
        Chat
        ConvMgr
        RespParser
    end
    
    subgraph Config Layer
        ConfigMgr
        Constants
    end
```

### 3.2 核心模块设计

#### 3.2.1 基础层 (Foundation)
*   **`core/models.py`**: 定义 `ToolSchema`, `ServerConfig`, `ConversationMessage` 等数据类。
    *   *理由*: 提供强类型支持，减少运行时错误。
*   **`core/exceptions.py`**: 定义 `MCPClientError` 及其子类。
    *   *理由*: 统一错误捕获和处理策略。
*   **`core/protocols.py`**: 定义 `LLMClientProtocol`, `ToolRegistryProtocol`。
    *   *理由*: 实现依赖倒置，便于单元测试 mock。

#### 3.2.2 配置层 (Config)
*   **`config/settings.py`**: 升级为 `ConfigurationManager`，集成 `Constants`。
    *   *理由*: 集中管理环境变量和配置文件，支持缓存和校验。

#### 3.2.3 核心层 (Core)
*   **`core/llm_client.py`**: 重写为 `AsyncLLMClient`，使用 `asyncio.run_in_executor` 或原生异步库。
    *   *理由*: 解放主线程，提升响应速度。
*   **`core/tool_registry.py`**: 新增 `ToolRegistry`，管理多服务器工具集合。
    *   *理由*: 解耦服务器管理与工具调用，支持跨服务器工具查找。
*   **`core/server.py`**: `MCPServer` 适配 `ServerConfig`，集成重试机制。

#### 3.2.4 会话层 (Session)
*   **`session/conversation.py`**: 新增 `ConversationManager`，管理消息历史和修剪策略。
    *   *理由*: 将状态管理从控制逻辑中剥离。
*   **`session/response_parser.py`**: 新增 `ResponseParser`，专注处理 JSON/CodeBlock 解析。
    *   *理由*: 提高解析的健壮性，支持多种 LLM 输出格式。
*   **`session/chat_session.py`**: 重构为 `EnhancedChatSession`，作为协调者 (Orchestrator)。

---

## 4. 实施步骤分解

我们将采用**小步迭代**的方式进行重构，每一步都确保代码可编译、可运行。

### 阶段一：基础架构搭建 (预计耗时: 20%)
1.  **创建基础文件**: `core/models.py`, `core/exceptions.py`, `core/protocols.py`。
2.  **重构配置层**: 修改 `config/settings.py`，实现 `ConfigurationManager`。
3.  **验证**: 编写简单脚本验证配置加载和数据模型实例化。

### 阶段二：核心组件重构 (预计耗时: 40%)
4.  **异步 LLM 客户端**: 创建 `core/llm_client.py` 的异步版本。
5.  **工具注册表**: 实现 `core/tool_registry.py`。
6.  **服务器适配**: 修改 `core/server.py` 以使用新的 Models 和 Exceptions。
7.  **验证**: 编写单元测试验证 LLM 连接和工具注册逻辑。

### 阶段三：会话层重构 (预计耗时: 30%)
8.  **辅助组件**: 实现 `ConversationManager` 和 `ResponseParser`。
9.  **会话控制器**: 重写 `session/chat_session.py`，组装上述组件。
10. **验证**: 模拟对话流程，测试消息历史管理和 JSON 解析。

### 阶段四：集成与清理 (预计耗时: 10%)
11. **入口文件**: 创建 `main.py` 和 `core/factory.py`。
12. **清理**: 删除旧的冗余代码，规范化导入。
13. **最终验证**: 运行完整集成测试。

---

## 5. 风险评估与应对措施

| 风险点 | 风险等级 | 应对措施 |
| :--- | :--- | :--- |
| **异步迁移复杂性** | 高 | 逐步迁移，先封装同步方法为异步，确保事件循环正确管理。使用 `asyncio.run()` 作为单一入口。 |
| **破坏现有功能** | 中 | 在重构期间保留旧文件 (如 `server.py.bak`)，直到新模块通过测试。 |
| **配置兼容性** | 低 | 保持配置文件格式不变，但在代码层面增加适配层。 |
| **依赖冲突** | 低 | 检查 `requirements.txt`，确保 `mcp` 和 `openai` 等库版本兼容。 |

---

## 6. 测试验证计划

### 6.1 单元测试 (Unit Tests)
*   **Parser Test**: 测试 `ResponseParser` 对标准 JSON、Markdown 包裹 JSON、残缺 JSON 的解析能力。
*   **Config Test**: 测试环境变量缺失、配置文件格式错误时的异常抛出。
*   **Manager Test**: 测试 `ConversationManager` 的消息修剪 (Pruning) 逻辑是否符合 `MAX_MESSAGE_HISTORY` 限制。

### 6.2 集成测试 (Integration Tests)
*   **Server Connection**: 验证能否成功连接到本地 `stdio` 服务器 (如 `npx` 命令)。
*   **LLM Interaction**: 发送真实请求给 LLM，验证异步响应接收。
*   **Tool Execution**: 模拟完整链路：用户提问 -> LLM 调用工具 -> 执行工具 -> 返回结果 -> LLM 总结。

### 6.3 验收标准
1.  所有模块均已按照设计文档归位。
2.  程序通过 `python main.py` 正常启动，无报错。
3.  能够成功加载配置文件，连接 MCP 服务器。
4.  能够进行多轮对话，且工具调用正常。
5.  代码通过静态检查 (Pylint/Flake8)，无明显规范问题。

---
**确认签字**: ____________________
