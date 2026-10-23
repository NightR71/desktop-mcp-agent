"""聊天会话管理"""

import asyncio
import logging
from typing import Any, Dict, List

from Backend.config.settings import Constants
from Backend.core.exceptions import ToolExecutionError
from Backend.core.types import ToolSchema
from Backend.services.llm import AsyncLLMClient
from Backend.services.mcp_server import ToolRegistry
from Backend.utils.conversation import ConversationManager
from Backend.utils.parser import ResponseParser


class EnhancedChatSession:
    """增强的聊天会话"""
    
    def __init__(
        self,
        llm_client: AsyncLLMClient,
        tool_registry: ToolRegistry,
        conversation_manager: ConversationManager,
        status_callback=None
    ):
        self.llm_client = llm_client
        self.tool_registry = tool_registry
        self.conversation_manager = conversation_manager
        self.response_parser = ResponseParser()
        self._running = False
        self.status_callback = status_callback # 用于通知前端状态变化的回调函数

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

    async def process_user_input(self, user_input: str) -> str:
        """处理用户输入"""
        self._running = True
        # 禁用多轮对话历史：每次处理新输入前清除历史（保留系统消息）
        self.conversation_manager.clear_history()
        
        self.conversation_manager.add_message("user", user_input)
        
        retry_count = 0
        max_retries = 3
        
        while retry_count <= max_retries:
            try:
                # 检查是否停止运行
                if not self._running:
                    return "操作已取消"
                    
                return await self._handle_conversation_turn()
            except Exception as e:
                error_msg = str(e)
                # 检查是否是上下文超限错误（这里假设是通用的超限错误描述，或者包含特定关键词）
                # 实际上 LLM 客户端可能会抛出特定的 APIError
                # 这里我们简化处理，如果是任何异常都尝试重试，或者可以根据错误信息判断
                
                # 如果是用户手动停止，不再重试
                if "手动停止" in error_msg:
                    return "操作已取消"

                retry_count += 1
                if retry_count <= max_retries:
                    logging.warning(f"Error processing input: {error_msg}. Retrying ({retry_count}/{max_retries})...")
                    if self.status_callback:
                        self.status_callback(f"遇到错误，正在重试 ({retry_count}/{max_retries})...")
                    
                    # 重新初始化会话状态（清除历史除了系统提示，重新添加用户输入）
                    self.conversation_manager.clear_history()
                    self.conversation_manager.add_message("user", user_input)
                    
                    # 等待一下再重试
                    await asyncio.sleep(1)
                else:
                    error_msg = f"处理用户输入时出错 (已重试{max_retries}次): {str(e)}"
                    logging.error(error_msg)
                    print(f"\nAssistant: {error_msg}")
                    self.conversation_manager.add_message("assistant", error_msg)
                    return error_msg

    def stop_processing(self):
        """停止当前处理"""
        self._running = False

    async def _handle_conversation_turn(self, depth: int = 0) -> str:
        """处理对话轮次"""
        if not self._running:
             raise Exception("手动停止运行")

        if depth > Constants.MAX_CONVERSATION_DEPTH:
            error_msg = "对话深度超过限制，请简化您的请求"
            print(f"\nAssistant: {error_msg}")
            self.conversation_manager.add_message("assistant", error_msg)
            return error_msg

        # 通知前端：模型正在思考
        if self.status_callback:
            if depth == 0:
                self.status_callback("当前模型正在思考中……")
            else:
                self.status_callback("模型正在分析工具结果……")
        
        # 再次检查停止信号
        if not self._running:
             raise Exception("手动停止运行")

        # 获取LLM响应
        messages = self.conversation_manager.get_messages_for_llm()
        llm_response = await self.llm_client.get_response(messages)
        
        # 再次检查停止信号
        if not self._running:
             raise Exception("手动停止运行")
        
        # 解析响应
        json_data = self.response_parser.extract_json(llm_response)
        
        if json_data:
            tool_calls = self.response_parser.parse_tool_calls(json_data)
            if tool_calls:
                # 处理工具调用
                return await self._execute_tool_calls(llm_response, tool_calls, depth)
        
        # 普通响应
        print(f"\nAssistant: {llm_response}")
        self.conversation_manager.add_message("assistant", llm_response)
        return llm_response

    async def _execute_tool_calls(
        self, 
        original_response: str, 
        tool_calls: List[Dict[str, Any]], 
        depth: int
    ) -> str:
        """执行工具调用"""
        if not self._running:
             raise Exception("手动停止运行")
             
        self.conversation_manager.add_message("assistant", original_response)
        
        # 通知前端：正在调用工具
        if self.status_callback:
            self.status_callback("模型正在调用工具中，请注意！")
            
        # 执行所有工具调用
        results = []
        for tool_call in tool_calls:
            # 在每个工具执行前检查停止信号
            if not self._running:
                raise Exception("手动停止运行")
                
            try:
                result = await self._execute_single_tool_call(tool_call)
                results.append(f"工具 {tool_call.get('name', 'unknown')} 执行成功: {result}")
            except Exception as e:
                results.append(f"工具 {tool_call.get('name', 'unknown')} 执行失败: {str(e)}")
        
        # 添加工具执行结果
        tool_results = "\n".join(results)
        self.conversation_manager.add_message("user", f"工具执行结果:\n{tool_results}")
        
        # 继续对话
        return await self._handle_conversation_turn(depth + 1)

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
