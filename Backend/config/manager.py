"""配置管理器"""

import os
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional
from dotenv import load_dotenv

from Backend.core.exceptions import ConfigurationError

class ConfigurationManager:
    """配置管理器"""
    
    def __init__(self, config_file: Optional[str] = None):
        self._load_environment()
        self.config_file = config_file
        self._config_cache: Dict[str, Any] = {}

    def _load_environment(self) -> None:
        """加载环境变量"""
        load_dotenv()

    def get_api_key(self, key_name: str = "DEEP_API_KEY") -> str:
        """获取API密钥"""
        api_key = os.getenv(key_name)
        if not api_key:
            raise ConfigurationError(f"API key '{key_name}' not found in environment variables")
        return api_key

    def load_server_config(self, file_path: str) -> Dict[str, Any]:
        """加载服务器配置"""
        if file_path in self._config_cache:
            return self._config_cache[file_path]

        try:
            config_path = Path(file_path)
            if not config_path.exists():
                raise ConfigurationError(f"Configuration file not found: {file_path}")
            
            with open(config_path, 'r', encoding='utf-8') as file:
                config = json.load(file)
                self._config_cache[file_path] = config
                return config
        except json.JSONDecodeError as e:
            raise ConfigurationError(f"Invalid JSON in configuration file {file_path}: {e}")
        except Exception as e:
            raise ConfigurationError(f"Failed to load configuration file {file_path}: {e}")
