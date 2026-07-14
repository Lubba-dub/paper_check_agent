"""V4 事件日志。"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List


@dataclass
class WorkflowEvent:
    """工作流事件。"""

    event_type: str
    plan_id: str
    task_id: str
    stage: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


class EventLog:
    """事件存储。"""

    def __init__(self, log_dir: Path):
        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._events: List[WorkflowEvent] = []

    def append(self, event: WorkflowEvent) -> None:
        self._events.append(event)

    def save(self, plan_id: str) -> Path:
        target = self.log_dir / f"{plan_id}_events.json"
        target.write_text(
            json.dumps([asdict(event) for event in self._events], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return target

    @property
    def events(self) -> List[WorkflowEvent]:
        return list(self._events)

