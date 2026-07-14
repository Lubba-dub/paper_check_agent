"""V4 工作流执行器。"""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict

from article_check.pipeline.models import PaperTask

from .checkpoint import CheckpointStore
from .dag import StageNode, TaskGraph
from .events import EventLog, WorkflowEvent


class V4ReviewWorkflow:
    """以 DAG/事件/checkpoint 包裹现有流水线的 V4 执行器。"""

    def __init__(
        self,
        event_log: EventLog,
        checkpoint_store: CheckpointStore,
    ):
        self.event_log = event_log
        self.checkpoint_store = checkpoint_store

    def compile_graph(self, plan_id: str, enable_deep_review: bool) -> TaskGraph:
        graph = TaskGraph(plan_id=plan_id)
        graph.add_node(StageNode("ingest", "ingest", critical=True))
        graph.add_node(StageNode("format", "format_check", "format_checker", ["ingest"], True))
        graph.add_node(StageNode("reference", "reference_validate", "reference_checker", ["format"], True))
        graph.add_node(
            StageNode(
                "content",
                "content_review" if enable_deep_review else "content_skip",
                "content_reviewer" if enable_deep_review else None,
                ["reference"],
                enable_deep_review,
            )
        )
        graph.add_node(StageNode("report", "report", "main_reviewer", ["content"], True))
        return graph

    def create_checkpoint_payload(self, graph: TaskGraph, task: PaperTask) -> Dict[str, Any]:
        return {
            "plan_id": graph.plan_id,
            "task": {
                "task_id": task.task_id,
                "paper_path": str(task.paper_path),
                "title": task.title,
                "file_type": task.file_type,
                "review_depth": task.review_depth,
            },
            "graph": graph.to_dict(),
            "status": "running",
        }

    async def run_single(self, runtime: Any, task: PaperTask, enable_deep_review: bool) -> Any:
        graph = self.compile_graph(runtime.plan.plan_id, enable_deep_review)
        self.event_log.append(WorkflowEvent("run_started", runtime.plan.plan_id, task.task_id))
        self.checkpoint_store.save(
            runtime.plan.plan_id,
            self.create_checkpoint_payload(graph, task),
        )

        graph.mark("ingest", "completed")
        self.event_log.append(WorkflowEvent("node_completed", runtime.plan.plan_id, task.task_id, "ingest"))

        graph.mark("format", "running")
        self.event_log.append(WorkflowEvent("node_started", runtime.plan.plan_id, task.task_id, "format_check"))
        graph.mark("reference", "running")
        graph.mark("content", "running" if enable_deep_review else "skipped")

        result = await runtime.orchestrator.review_single(task)

        graph.mark("format", "completed")
        graph.mark("reference", "completed")
        graph.mark("content", "completed" if enable_deep_review else "skipped")
        graph.mark("report", "completed")

        self.event_log.append(
            WorkflowEvent(
                "run_finished",
                runtime.plan.plan_id,
                task.task_id,
                payload={
                    "overall_score": result.overall_score,
                    "report_path": str(result.report_path) if result.report_path else None,
                },
            )
        )
        self.checkpoint_store.save(
            runtime.plan.plan_id,
            {
                **self.create_checkpoint_payload(graph, task),
                "status": "completed",
                "result": result.to_dict(),
            },
        )
        self.event_log.save(runtime.plan.plan_id)
        return result

