"""V4 checkpoint 持久化。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional


class CheckpointStore:
    """基于 JSON 文件的轻量 checkpoint 存储。"""

    def __init__(self, checkpoint_dir: Path):
        self.checkpoint_dir = checkpoint_dir
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

    def save(self, plan_id: str, payload: Dict[str, Any]) -> Path:
        target = self.checkpoint_dir / f"{plan_id}.json"
        target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return target

    def load(self, plan_id: str) -> Optional[Dict[str, Any]]:
        target = self.checkpoint_dir / f"{plan_id}.json"
        if not target.exists():
            return None
        return json.loads(target.read_text(encoding="utf-8"))

