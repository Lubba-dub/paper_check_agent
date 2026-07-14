"""ContextCacheBus — V4 逻辑级共享上下文总线。"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional

from article_check.core.polykv import CompressionLevel, PolyKVEngine


@dataclass
class ContextPack:
    """共享上下文包。"""

    pack_id: str
    pack_type: str
    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    base_pack_id: Optional[str] = None


class ContextCacheBus:
    """为 runtime / workflow / 插件报告提供统一缓存接口。"""

    def __init__(self, engine: Optional[PolyKVEngine] = None):
        self.engine = engine or PolyKVEngine()
        self._packs: Dict[str, ContextPack] = {}

    def put_pack(
        self,
        pack_type: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
        *,
        level: int = CompressionLevel.STANDARD,
    ) -> str:
        pack_id = self.engine.put(content, level=level)
        self._packs[pack_id] = ContextPack(
            pack_id=pack_id,
            pack_type=pack_type,
            content=content,
            metadata=metadata or {},
        )
        return pack_id

    def acquire(self, pack_id: str, agent_id: str) -> None:
        self.engine.acquire(pack_id, agent_id)

    def release(self, pack_id: str, agent_id: str) -> None:
        self.engine.release(pack_id, agent_id)

    def get_pack(self, pack_id: str) -> Optional[ContextPack]:
        pack = self._packs.get(pack_id)
        if not pack:
            return None
        restored = self.engine.get(pack_id)
        if restored is not None:
            pack.content = restored
        return pack

    def fork_pack(
        self,
        base_pack_id: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
        *,
        level: int = CompressionLevel.HIGH,
    ) -> str:
        pack_id = self.put_pack("fork", content, metadata, level=level)
        self._packs[pack_id].base_pack_id = base_pack_id
        return pack_id

    def stats(self) -> Dict[str, Any]:
        metrics = self.engine.stats()
        return {
            "pack_count": len(self._packs),
            "metrics": asdict(metrics),
        }

