"""V4 审查任务图。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class StageNode:
    """V4 阶段节点。"""

    node_id: str
    stage: str
    worker_binding: Optional[str] = None
    dependencies: List[str] = field(default_factory=list)
    critical: bool = False
    status: str = "pending"


@dataclass
class TaskGraph:
    """轻量 DAG，用于阶段编排和状态展示。"""

    plan_id: str
    nodes: Dict[str, StageNode] = field(default_factory=dict)

    def add_node(self, node: StageNode) -> None:
        self.nodes[node.node_id] = node

    def mark(self, node_id: str, status: str) -> None:
        if node_id in self.nodes:
            self.nodes[node_id].status = status

    def to_dict(self) -> Dict[str, dict]:
        return {
            node_id: {
                "stage": node.stage,
                "worker_binding": node.worker_binding,
                "dependencies": node.dependencies,
                "critical": node.critical,
                "status": node.status,
            }
            for node_id, node in self.nodes.items()
        }

