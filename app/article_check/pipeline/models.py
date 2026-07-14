"""Review pipeline shared data models — breaks circular imports between orchestrator and worker."""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class WorkerResult:
    """Worker execution result"""
    success: bool
    worker_name: str
    data: Optional[Any] = None
    error: Optional[str] = None
    score: Optional[float] = None
    issues: List[Dict] = field(default_factory=list)
    token_usage: Dict[str, int] = field(default_factory=dict)


@dataclass
class PaperTask:
    """Single paper review task"""
    task_id: str
    paper_path: Path
    title: str = ""
    file_type: str = ""
    journal_template: str = ""
    review_depth: str = "auto"
    review_track: str = "auto"


@dataclass
class PipelineResult:
    """Final result of a review pipeline"""
    paper_title: str
    task_id: str
    source_paper_path: Optional[str] = None
    source_file_name: Optional[str] = None
    review_track: Optional[str] = None
    format_check: Optional[Any] = None
    content_review: Optional[Any] = None
    reference_check: Optional[Any] = None
    overall_score: Optional[float] = None
    report_path: Optional[Path] = None
    errors: List[str] = field(default_factory=list)
    duration: float = 0.0

    def to_dict(self) -> dict:
        return {
            "paper_title": self.paper_title,
            "task_id": self.task_id,
            "source_paper_path": self.source_paper_path,
            "overall_score": self.overall_score,
            "report_path": str(self.report_path) if self.report_path else None,
            "errors": self.errors,
            "duration": self.duration,
        }
