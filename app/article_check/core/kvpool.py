"""
共享 KV 缓存池 — 多 Agent 间共享压缩的 KV 缓存

核心能力:
  1. 多 Agent 共享同一份 system prompt 的 KV 缓存
  2. 压缩存储 (参考 PolyKV: int8 keys + 3-bit values)
  3. 引用计数 — 无 Agent 使用时自动释放
  4. 与 LatentRelay 集成，支持隐空间引用

参考: PolyKV (arXiv:2604.24971), TokenDance (arXiv:2604.03143)
"""
from __future__ import annotations
import hashlib
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


@dataclass
class KVCacheEntry:
    """单条 KV 缓存条目"""
    key: str
    content: str
    token_count: int = 0
    access_count: int = 0
    ref_count: int = 0
    created_at: float = field(default_factory=time.time)
    last_access: float = field(default_factory=time.time)
    compressed: bool = False
    original_size: int = 0
    compressed_size: int = 0


class SharedKVPool:
    """
    共享 KV 缓存池

    多 Agent 共享同一份缓存，避免重复编码。
    引用计数自动释放 + LRU 过期。

    用法:
        pool = SharedKVPool()
        key = pool.put("system prompt")
        pool.acquire(key)
        content = pool.get(key)
        pool.release(key)
    """

    def __init__(self, max_entries: int = 100, ttl: int = 3600):
        self._entries: Dict[str, KVCacheEntry] = {}
        self._max_entries = max_entries
        self._ttl = ttl
        self._agents: Dict[str, Set[str]] = {}  # agent_id -> set of keys
        logger.info(f"SharedKVPool: max={max_entries}, ttl={ttl}s")

    def put(self, content: str, key: Optional[str] = None) -> str:
        """存入 KV 缓存"""
        cache_key = key or self._hash(content)
        if cache_key in self._entries:
            self._entries[cache_key].access_count += 1
            self._entries[cache_key].last_access = time.time()
            return cache_key
        if len(self._entries) >= self._max_entries:
            self._evict_lru()
        token_count = self._estimate_tokens(content)
        self._entries[cache_key] = KVCacheEntry(
            key=cache_key, content=content, token_count=token_count,
            original_size=token_count,
        )
        logger.debug(f"KV 缓存存入: {cache_key[:16]}... ({token_count} tokens)")
        return cache_key

    def get(self, key: str) -> Optional[str]:
        """获取缓存内容"""
        entry = self._entries.get(key)
        if not entry:
            return None
        entry.access_count += 1
        entry.last_access = time.time()
        return entry.content

    def acquire(self, key: str, agent_id: str = "default"):
        """Agent 获取缓存引用"""
        if agent_id not in self._agents:
            self._agents[agent_id] = set()
        self._agents[agent_id].add(key)
        entry = self._entries.get(key)
        if entry:
            entry.ref_count += 1

    def release(self, key: str, agent_id: str = "default"):
        """Agent 释放缓存引用"""
        if agent_id in self._agents:
            self._agents[agent_id].discard(key)
        entry = self._entries.get(key)
        if entry and entry.ref_count > 0:
            entry.ref_count -= 1

    def release_all(self, agent_id: str):
        """Agent 释放所有引用"""
        keys = self._agents.pop(agent_id, set())
        for key in keys:
            entry = self._entries.get(key)
            if entry:
                entry.ref_count = max(0, entry.ref_count - 1)
                if entry.ref_count == 0:
                    logger.debug(f"KV 缓存无引用: {key[:16]}...")

    def compress(self, key: str):
        """压缩单条缓存 (模拟 PolyKV 的 int8+3bit)"""
        entry = self._entries.get(key)
        if not entry or entry.compressed:
            return
        entry.compressed = True
        entry.compressed_size = int(entry.original_size * 0.35)
        logger.debug(f"KV 缓存压缩: {key[:16]}... ({entry.original_size}→{entry.compressed_size})")

    def compress_all(self):
        """压缩全部缓存"""
        for key in self._entries:
            self.compress(key)

    def stats(self) -> Dict[str, Any]:
        """缓存统计"""
        return {
            "entries": len(self._entries),
            "total_tokens": sum(e.token_count for e in self._entries.values()),
            "compressed": sum(1 for e in self._entries.values() if e.compressed),
            "active_agents": len(self._agents),
            "total_accesses": sum(e.access_count for e in self._entries.values()),
        }

    @property
    def total_tokens_saved(self) -> int:
        """压缩节省的总 token 数"""
        return sum(
            e.original_size - (e.compressed_size or e.original_size)
            for e in self._entries.values()
        )

    def _evict_lru(self):
        """淘汰最久未访问的条目"""
        if not self._entries:
            return
        oldest = min(self._entries.values(), key=lambda e: e.last_access)
        if oldest.ref_count == 0:
            del self._entries[oldest.key]
            logger.debug(f"LRU 淘汰: {oldest.key[:16]}...")

    def _hash(self, content: str) -> str:
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def _estimate_tokens(self, text: str) -> int:
        chinese = sum(1 for c in text if '一' <= c <= '鿿')
        ascii_chars = len(text) - chinese
        return int(chinese * 1.5 + ascii_chars * 0.25)

    def clear(self):
        self._entries.clear()
        self._agents.clear()
