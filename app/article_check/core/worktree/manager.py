"""
工作树管理器 — 为每篇论文创建隔离的工作区

在并行批量审查中，每篇论文获得一个"工作树"（隔离目录）：
- 论文文件 → 拷贝到工作区
- 审查中间产物 → 存放在工作区
- 各论文之间完全隔离

参考: Claude Code 的 worktree isolation 模式
"""
from __future__ import annotations
import os
import shutil
import tempfile
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Optional, Dict

from article_check.config.settings import config

logger = logging.getLogger(__name__)


@dataclass
class WorktreeContext:
    """单个工作树的上下文"""
    task_id: str          # 论文唯一标识
    work_dir: Path        # 工作目录
    paper_path: Path      # 原始论文路径
    paper_copy: Path      # 工作区中的副本路径
    artifacts_dir: Path   # 中间产物目录
    report_dir: Path      # 报告输出目录
    temp_files: List[Path] = field(default_factory=list)

    def cleanup(self):
        """清理工作树中的临时文件"""
        for f in self.temp_files:
            if f.exists():
                f.unlink()
        logger.debug(f"[{self.task_id}] 临时文件已清理")


class WorktreeManager:
    """
    工作树管理器 — 创建、管理、清理隔离的工作区。

    支持:
    - 为每篇论文创建隔离工作区
    - 批量创建多个工作区
    - 优雅清理
    - 失败隔离（一篇论文失败不影响其他）
    """

    def __init__(self, base_dir: Optional[str] = None):
        self.base_dir = Path(
            base_dir or config.pipeline.worktree_base_dir
        ).resolve()
        self.active_contexts: Dict[str, WorktreeContext] = {}
        logger.info(f"工作树管理器初始化: base_dir={self.base_dir}")

    def create(
        self,
        task_id: str,
        paper_path: Path,
    ) -> WorktreeContext:
        """为单篇论文创建隔离工作区"""
        # 创建工作目录
        work_dir = self.base_dir / task_id
        artifacts_dir = work_dir / "artifacts"
        report_dir = work_dir / "report"

        work_dir.mkdir(parents=True, exist_ok=True)
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        report_dir.mkdir(parents=True, exist_ok=True)

        # 复制论文到工作区
        paper_path = Path(paper_path)
        if paper_path.exists():
            paper_copy = work_dir / paper_path.name
            shutil.copy2(str(paper_path), str(paper_copy))
        else:
            paper_copy = work_dir / "paper.tex"  # fallback
            paper_copy.write_text("")

        ctx = WorktreeContext(
            task_id=task_id,
            work_dir=work_dir,
            paper_path=paper_path,
            paper_copy=paper_copy,
            artifacts_dir=artifacts_dir,
            report_dir=report_dir,
        )

        self.active_contexts[task_id] = ctx
        logger.info(f"[{task_id}] 工作树创建: {work_dir}")
        return ctx

    def create_batch(
        self,
        papers: List[tuple[str, Path]],
    ) -> List[WorktreeContext]:
        """批量创建多个隔离工作区"""
        return [self.create(task_id, path) for task_id, path in papers]

    def get(self, task_id: str) -> Optional[WorktreeContext]:
        return self.active_contexts.get(task_id)

    def remove(self, task_id: str, keep_report: bool = True):
        """移除指定工作树"""
        ctx = self.active_contexts.pop(task_id, None)
        if not ctx:
            return

        # 如果保留报告，先把报告移出
        if keep_report and ctx.report_dir.exists():
            final_report_path = Path.cwd() / "reports" / task_id
            final_report_path.parent.mkdir(parents=True, exist_ok=True)
            if final_report_path.exists():
                shutil.rmtree(str(final_report_path))
            shutil.copytree(str(ctx.report_dir), str(final_report_path))
            logger.info(f"[{task_id}] 报告已保存: {final_report_path}")

        # 清理工作树
        if ctx.work_dir.exists():
            shutil.rmtree(str(ctx.work_dir))
            logger.debug(f"[{task_id}] 工作树已删除")

    def cleanup_all(self, keep_reports: bool = True):
        """清理所有工作树"""
        for task_id in list(self.active_contexts.keys()):
            self.remove(task_id, keep_report=keep_reports)
        logger.info("所有工作树已清理")

    @property
    def active_count(self) -> int:
        return len(self.active_contexts)
