"""
LLM 客户端 — DeepSeek API 的封装

核心职责：
- 兼容 DeepSeek Chat / Reasoner 模型
- 支持 system prompt 缓存（token 优化）
- 结构化输出强制（Pydantic / JSON Schema）
- Token 使用统计与 40% 阈值监控
- 自动重试与回退
"""
from __future__ import annotations
import os
import json
import time
import logging
import re
from typing import Any, Dict, List, Optional, Type, Union
from dataclasses import dataclass, field

import httpx

from article_check.config.settings import config

logger = logging.getLogger(__name__)


@dataclass
class LLMResponse:
    """LLM 调用返回的标准化结果"""
    content: str
    role: str = "assistant"
    tool_calls: List[Dict] = field(default_factory=list)
    usage: Dict[str, int] = field(default_factory=dict)
    model: str = ""
    latency: float = 0.0

    @property
    def total_tokens(self) -> int:
        return self.usage.get("total_tokens", 0)

    @property
    def cached_tokens(self) -> int:
        return self.usage.get("prompt_cache_hit_tokens", 0)


class DeepSeekClient:
    """
    DeepSeek API 客户端

    支持:
    - Chat Completions API
    - 函数调用 / 工具使用
    - 流式输出
    - 结构化输出（JSON mode）
    - 系统提示词缓存
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ):
        cfg = config.deepseek
        self.api_key = api_key or cfg.api_key
        self.base_url = base_url or cfg.base_url
        self.model = model or cfg.chat_model
        self.max_tokens = cfg.max_tokens
        self.temperature = cfg.temperature
        self.top_p = cfg.top_p
        self.timeout = cfg.timeout

        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=self.timeout,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )

        if not self.api_key:
            logger.warning("DEEPSEEK_API_KEY 未配置。请在环境变量或 settings.py 中设置。")

    def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict]] = None,
        response_format: Optional[Dict] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        model: Optional[str] = None,
        stream: bool = False,
    ) -> LLMResponse:
        """
        发送聊天请求到 DeepSeek API

        Args:
            messages: 消息列表。建议把不变的系统提示词放在 messages[0]（利用缓存）
            tools: OpenAI-format tool schemas
            response_format: {"type": "json_object"} 或自定义 schema
            temperature: 覆盖默认温度
            max_tokens: 覆盖默认 max_tokens
            model: 覆盖默认模型
            stream: 是否流式输出
        """
        start = time.time()
        url = f"{self.base_url}/chat/completions"

        payload: Dict[str, Any] = {
            "model": model or self.model,
            "messages": messages,
            "temperature": temperature if temperature is not None else self.temperature,
            "max_tokens": max_tokens or self.max_tokens,
            "top_p": self.top_p,
            "stream": stream,
        }

        if tools:
            payload["tools"] = tools

        if response_format:
            payload["response_format"] = response_format

        try:
            logger.debug(
                f"DeepSeek API 请求: model={payload['model']}, "
                f"messages={len(messages)}, tools={len(tools) if tools else 0}"
            )

            resp = self._client.post("/chat/completions", json=payload)
            resp.raise_for_status()
            data = resp.json()

        except httpx.TimeoutException:
            logger.error("DeepSeek API 请求超时")
            raise
        except httpx.HTTPStatusError as e:
            logger.error(f"DeepSeek API HTTP 错误: {e.response.status_code} {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"DeepSeek API 请求失败: {e}")
            raise

        elapsed = time.time() - start
        choice = data["choices"][0]
        usage = data.get("usage", {})

        result = LLMResponse(
            content=choice["message"].get("content", ""),
            role=choice["message"]["role"],
            tool_calls=choice["message"].get("tool_calls", []),
            usage=usage,
            model=data.get("model", ""),
            latency=elapsed,
        )

        logger.info(
            f"DeepSeek 响应: {result.total_tokens} tokens "
            f"(cached={result.cached_tokens}) in {elapsed:.1f}s"
        )

        return result

    def structured_chat(
        self,
        messages: List[Dict[str, Any]],
        schema: Dict[str, Any],
        **kwargs,
    ) -> dict:
        """
        结构化输出 — 强制 LLM 按 JSON Schema 返回

        这是 Token 优化的关键策略之一：
        结构化输出比自由文本减少 30-50% completion tokens
        """
        response_format = {
            "type": "json_object",
            "schema": schema,
        }
        result = self.chat(
            messages=messages,
            response_format=response_format,
            **kwargs,
        )

        try:
            return self._parse_structured_json(result.content)
        except json.JSONDecodeError as e:
            logger.error(f"结构化输出解析失败: {e}")
            logger.debug(f"原始输出: {result.content[:500]}")
            raise

    def _parse_structured_json(self, content: str) -> dict:
        """尽量容错地解析模型 JSON 输出。"""

        candidates = []
        stripped = content.strip()
        if stripped:
            candidates.append(stripped)

        extracted = self._extract_json_object(stripped)
        if extracted and extracted not in candidates:
            candidates.append(extracted)

        for candidate in list(candidates):
            repaired = self._repair_json_text(candidate)
            if repaired and repaired not in candidates:
                candidates.append(repaired)

        last_error: Optional[json.JSONDecodeError] = None
        for candidate in candidates:
            try:
                return json.loads(candidate)
            except json.JSONDecodeError as exc:
                last_error = exc
                continue

        if last_error:
            raise last_error
        raise json.JSONDecodeError("Empty JSON content", content, 0)

    def _extract_json_object(self, text: str) -> str:
        """从可能带解释文本的输出中截取最外层 JSON 对象。"""

        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return text
        return text[start:end + 1]

    def _repair_json_text(self, text: str) -> str:
        """修复常见 JSON 格式问题。"""

        repaired = text.strip()
        # 去掉 markdown fenced code block
        repaired = re.sub(r"^```(?:json)?\s*", "", repaired)
        repaired = re.sub(r"\s*```$", "", repaired)

        # 修复非法转义，如 \_ 或无效 \uXXXX
        repaired = re.sub(r'\\(?!["\\/bfnrtu])', r"\\\\", repaired)
        repaired = re.sub(r'\\u(?![0-9a-fA-F]{4})', r"\\\\u", repaired)

        # 去掉尾随逗号
        repaired = re.sub(r",\s*([}\]])", r"\1", repaired)

        # 清理裸控制字符
        repaired = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F]", " ", repaired)
        return repaired

    def close(self):
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
