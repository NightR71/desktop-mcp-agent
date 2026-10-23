"""LLM客户端"""

import asyncio
import logging
import sys
from typing import Dict, List

from Backend.config.settings import Constants
from Backend.core.exceptions import MCPClientError

# LLM客户端导入
try:
    from zai import ZhipuAiClient
    from openai import OpenAI
except ImportError as e:
    logging.error(f"请安装ZAI库 - {e}")
    sys.exit(1)


class AsyncLLMClient:
    """异步LLM客户端"""
    
    def __init__(self, api_key: str, model: str = "deepseek-chat", base_url="https://api.deepseek.com"):
        # self.client = ZhipuAiClient(api_key=api_key)
        # model = "glm-4.6"
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model
        self.default_params = {
            "temperature": Constants.DEFAULT_TEMPERATURE,
            "max_tokens": Constants.DEFAULT_MAX_TOKENS,
            "stream": False
        }

    async def get_response(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """获取LLM响应"""
        params = {**self.default_params, **kwargs}
        
        try:
            # 在实际异步环境中，这里应该使用真正的异步调用
            response = await asyncio.get_event_loop().run_in_executor(
                None, 
                lambda: self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    **params
                )
            )
            return response.choices[0].message.content
        except Exception as e:
            error_msg = f"LLM request failed: {str(e)}"
            logging.error(error_msg)
            raise MCPClientError(error_msg) from e
