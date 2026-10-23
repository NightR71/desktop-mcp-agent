"""响应解析器"""

import json
from typing import Any, Dict, List, Optional

class ResponseParser:
    """LLM响应解析器"""
    
    @staticmethod
    def extract_json(response: str) -> Optional[Dict[str, Any]]:
        """从响应中提取JSON"""
        try:
            # 寻找JSON边界
            start = response.find('{')
            end = response.rfind('}') + 1
            
            if start == -1 or end == 0 or end <= start:
                return None
            
            json_str = response[start:end]
            return json.loads(json_str)
        except (json.JSONDecodeError, ValueError):
            return None

    @staticmethod
    def parse_tool_calls(json_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """解析工具调用"""
        tool_calls = []
        
        # 标准格式
        if "tool_calls" in json_data and isinstance(json_data["tool_calls"], list):
            tool_calls.extend(json_data["tool_calls"])
        
        # 兼容格式
        elif "tool" in json_data and "arguments" in json_data:
            tool_calls.append({
                "name": json_data["tool"],
                "parameters": json_data["arguments"]
            })
        
        return tool_calls
