"""LLM Client 工厂与导出。"""

from article_check.config.settings import config
from article_check.llm.client.deepseek import DeepSeekClient, LLMResponse
from article_check.llm.client.dify import DifyClient


def create_ai_client():
    """按配置选择 AI Provider。"""
    provider = (config.ai.provider or "dify").lower()
    if provider == "dify":
        return DifyClient()
    return DeepSeekClient()


def ai_provider_available() -> bool:
    provider = (config.ai.provider or "dify").lower()
    if provider == "dify":
        return bool(config.dify.api_key and config.dify.base_url)
    return bool(config.deepseek.api_key)
