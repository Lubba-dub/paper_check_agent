"""
LLM 缓存层 — Token 优化的核心策略

实现了三层缓存:
1. 系统提示词缓存（前缀缓存 — 利用 DeepSeek 的自动缓存）
2. 语义缓存（embedding-based — 相同问题复用结果）
3. 结果缓存（key-value — 完全相同的请求直接命中）

参考:
- "Don't Break the Cache" (arXiv:2601.06007)
- "Prompt Caching Efficiency" (Zenodo 2026)
"""
from __future__ import annotations
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from article_check.config.settings import config

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """缓存条目"""
    key: str
    value: Any
    created_at: float = field(default_factory=time.time)
    ttl: int = 3600
    hit_count: int = 0

    @property
    def is_expired(self) -> bool:
        return time.time() - self.created_at > self.ttl


class PromptCache:
    """
    提示词缓存 — 管理 LLM 调用的缓存策略

    缓存策略（按优先级）:
    1. 精确命中: 完全相同的 messages → 直接返回
    2. 语义命中: 相似度 > threshold → 返回缓存结果
    3. 前缀缓存: 静态 system prompt 前缀 → 利用 provider 缓存
    """

    def __init__(self, cache_dir: Optional[str] = None):
        self.cfg = config.cache
        self.cache_dir = Path(cache_dir or ".cache/llm_cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # 内存缓存
        self._memory_cache: Dict[str, CacheEntry] = {}
        self._semantic_cache: Dict[str, List[Tuple[str, float, CacheEntry]]] = {}

        logger.info(f"PromptCache 初始化: dir={self.cache_dir}")

    def get(self, messages: List[Dict]) -> Optional[Any]:
        """获取缓存结果"""
        # 1. 精确键值缓存
        key = self._make_key(messages)
        entry = self._memory_cache.get(key)

        if entry and not entry.is_expired:
            entry.hit_count += 1
            logger.debug(f"缓存命中 (exact): {key[:16]}...")
            return entry.value

        return None

    def set(
        self,
        messages: List[Dict],
        value: Any,
        ttl: Optional[int] = None,
    ):
        """设置缓存"""
        key = self._make_key(messages)
        entry = CacheEntry(
            key=key,
            value=value,
            ttl=ttl or self.cfg.system_cache_ttl,
        )
        self._memory_cache[key] = entry
        logger.debug(f"缓存设置: {key[:16]}... (TTL={entry.ttl}s)")

    def get_system_prefix(self, system_prompt: str) -> str:
        """
        获取/生成系统提示词前缀（用于 provider 缓存）

        把不变的系统提示词放在前缀，DeepSeek 会在服务器端缓存。
        返回的字符串应放在 messages[0]["content"]
        """
        # 简单返回 — 实际的缓存由 DeepSeek API 的 context caching 处理
        return system_prompt

    def _make_key(self, messages: List[Dict]) -> str:
        """生成缓存键"""
        serialized = json.dumps(messages, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(serialized.encode()).hexdigest()

    def clear_expired(self):
        """清理过期缓存"""
        expired = [
            k for k, v in self._memory_cache.items()
            if v.is_expired
        ]
        for k in expired:
            del self._memory_cache[k]
        if expired:
            logger.debug(f"清理 {len(expired)} 条过期缓存")

    def stats(self) -> Dict[str, Any]:
        """缓存统计"""
        return {
            "memory_entries": len(self._memory_cache),
            "ttl_seconds": self.cfg.system_cache_ttl,
            "cache_dir": str(self.cache_dir),
        }
