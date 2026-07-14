"""
审查流水线编排器 — orchestrator→worker→reviewer→synthesize

这是整个系统的"大脑"，决定：
1. 审查的维度与顺序
2. 并行与串行的编排
3. 自适应审查深度
4. 结果汇总与报告生成

参考: athena-loops 的 orchestrator→worker→reviewer 范式
"""
from __future__ import annotations
import asyncio
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from article_check.config.settings import config
from article_check.core.harness.base import Harness, HarnessContext
from article_check.core.worktree.manager import WorktreeManager, WorktreeContext
from article_check.pipeline.models import PaperTask, PipelineResult, WorkerResult
from article_check.pipeline.reviewer import Reviewer, ReviewResult

logger = logging.getLogger(__name__)


class Orchestrator:
    """
    审查编排器 — 管理单篇和多篇论文的完整审查流程

    审查策略:
    Phase 1 (triage): 格式检查 + 结构扫描 → 零 token / 规则引擎
    Phase 2 (deep):   内容审查 + 文献验证 → DeepSeek API
    Phase 3 (review): 综合评估 + 报告生成
    """

    def __init__(
        self,
        harness: Optional[Harness] = None,
        worktree_mgr: Optional[WorktreeManager] = None,
    ):
        self.harness = harness or Harness()
        self.worktree_mgr = worktree_mgr or WorktreeManager()
        self.workers: List[Any] = []
        self.reviewer: Optional[Reviewer] = None
        logger.info("Orchestrator 初始化完成")

    def register_worker(self, worker: Any):
        """注册一个审查 Worker"""
        self.workers.append(worker)
        logger.info(f"注册 Worker: {worker.name}")

    def register_reviewer(self, reviewer: Reviewer):
        """注册主 Reviewer"""
        self.reviewer = reviewer
        logger.info(f"注册 Reviewer: {reviewer.name}")

    async def review_single(
        self,
        task: PaperTask,
    ) -> PipelineResult:
        """
        单篇论文全流程审查

        流水线:
        1. 创建工作树
        2. 并行格式检查（规则引擎）
        3. 内容审查（DeepSeek）
        4. 文献验证（API）
        5. 结果审阅
        6. 报告生成
        """
        start = time.time()
        logger.info(f"开始单篇审查: {task.task_id} ({task.paper_path})")

        ctx = self.worktree_mgr.create(task.task_id, task.paper_path)

        result = PipelineResult(
            paper_title=task.title or task.paper_path.stem,
            task_id=task.task_id,
            source_paper_path=str(task.paper_path),
            source_file_name=task.paper_path.name,
            review_track=task.review_track,
        )

        pendings = []

        try:
            # Phase 1: 格式检查（规则引擎，零 token）
            if config.format.latex_rules_enabled or config.format.docx_rules_enabled:
                pendings.append(
                    asyncio.create_task(
                        self._run_format_check(ctx, task)
                    )
                )

            # Phase 2: 内容审查 + 文献验证（DeepSeek API）
            if self.workers:
                pendings.append(
                    asyncio.create_task(
                        self._run_content_review(ctx, task)
                    )
                )

            if config.reference.verify_doi or config.reference.check_citation_accuracy:
                pendings.append(
                    asyncio.create_task(
                        self._run_reference_check(ctx, task)
                    )
                )

            # 等待所有并行任务
            if pendings:
                done = await asyncio.gather(*pendings, return_exceptions=True)
                for d in done:
                    if isinstance(d, Exception):
                        logger.error(f"子任务失败: {d}")
                    elif isinstance(d, dict):
                        result = self._merge_phase_result(result, d)

        except Exception as e:
            logger.error(f"[{task.task_id}] 审查失败: {e}")
            result.errors.append(str(e))

        finally:
            # Phase 3: 评分与报告
            result.overall_score = self._compute_overall_score(result)
            result.duration = time.time() - start

            if self.reviewer:
                result.report_path = await self.reviewer.generate(
                    ctx, result
                )

            # 清理工作树（保留报告）
            self.worktree_mgr.remove(task.task_id, keep_report=True)

        logger.info(
            f"审查完成: {task.task_id} | "
            f"评分: {result.overall_score} | "
            f"耗时: {result.duration:.1f}s"
        )
        return result

    def _merge_phase_result(
        self, result: PipelineResult, phase_data: dict
    ) -> PipelineResult:
        """合并阶段结果到 PipelineResult"""
        phase_type = phase_data.get("_phase", "")
        if phase_type == "format":
            result.format_check = phase_data
        elif phase_type == "content":
            result.content_review = phase_data.get("workers", {})
        elif phase_type == "reference":
            result.reference_check = phase_data
        return result

    async def review_batch(
        self,
        tasks: List[PaperTask],
        max_concurrent: Optional[int] = None,
    ) -> List[PipelineResult]:
        """
        批量并行审查多篇论文

        使用 asyncio 并发控制，每篇论文运行在独立的工作树中。
        一篇失败不影响其他。
        """
        max_c = max_concurrent or config.pipeline.max_concurrent
        logger.info(f"批量审查: {len(tasks)} 篇, 并发={max_c}")

        semaphore = asyncio.Semaphore(max_c)

        async def limited_review(task: PaperTask) -> PipelineResult:
            async with semaphore:
                return await self.review_single(task)

        results = await asyncio.gather(
            *[limited_review(t) for t in tasks],
            return_exceptions=True,
        )

        # 过滤异常为错误结果
        final_results = []
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                logger.error(f"任务 {tasks[i].task_id} 异常: {r}")
                final_results.append(PipelineResult(
                    paper_title=tasks[i].title,
                    task_id=tasks[i].task_id,
                    source_paper_path=str(tasks[i].paper_path),
                    source_file_name=tasks[i].paper_path.name,
                    review_track=tasks[i].review_track,
                    errors=[str(r)],
                ))
            else:
                final_results.append(r)

        logger.info(f"批量审查完成: {len(final_results)}/{len(tasks)} 成功")
        return final_results

    # ─── 内部方法 ──────────────────────────────────────

    async def _run_format_check(
        self, ctx: WorktreeContext, task: PaperTask
    ) -> Dict[str, Any]:
        """运行格式检查"""
        logger.info(f"[{task.task_id}] Phase 1: 格式检查")
        results: Dict[str, Any] = {"_phase": "format", "issues": []}

        file_type = task.file_type or self._detect_file_type(task.paper_path)

        if file_type == "latex":
            tool = self.harness.get_tool("check_latex_format")
            if tool and tool.fn:
                issues = tool.fn(file_path=str(ctx.paper_copy))
                if issues:
                    results["issues"].extend(issues)
        elif file_type == "docx":
            tool = self.harness.get_tool("check_docx_format")
            if tool and tool.fn:
                issues = tool.fn(
                    file_path=str(ctx.paper_copy),
                    review_track=task.review_track,
                )
                if issues:
                    results["issues"].extend(issues)

        # 结构检查
        tool = self.harness.get_tool("check_structure")
        if tool and tool.fn:
            struct = tool.fn(
                file_path=str(ctx.paper_copy),
                file_type=file_type,
                review_track=task.review_track,
            )
            if struct:
                results["structure"] = struct
                results["issues"].extend(struct.get("issues", []))

        return results

    async def _run_content_review(
        self, ctx: WorktreeContext, task: PaperTask
    ) -> Dict[str, Any]:
        """运行内容审查"""
        logger.info(f"[{task.task_id}] Phase 2: 内容审查")
        results: Dict[str, Any] = {"_phase": "content", "workers": {}}

        for worker in self.workers:
            if worker.name != "content_reviewer":
                continue
            wr = await worker.work(ctx, task)
            if wr.success and wr.data:
                results["workers"][worker.name] = wr.data

        return results

    async def _run_reference_check(
        self, ctx: WorktreeContext, task: PaperTask
    ) -> Dict[str, Any]:
        """运行文献验证"""
        logger.info(f"[{task.task_id}] Phase 2: 文献验证")
        results: Dict[str, Any] = {"_phase": "reference", "issues": [], "verified_refs": 0}

        for worker in self.workers:
            if worker.name != "reference_checker":
                continue
            wr = await worker.work(ctx, task)
            if wr.success and wr.data:
                results.update(wr.data)
                if wr.issues and "issues" not in wr.data:
                    results["issues"] = wr.issues
                break

        return results

    def _compute_overall_score(
        self, result: PipelineResult
    ) -> float:
        """计算综合评分"""
        scores = []
        weights = {
            "format": 0.25,
            "content": 0.50,
            "reference": 0.25,
        }

        # 格式分
        if result.format_check:
            fmt_issues = result.format_check.get("issues", [])
            format_score = max(0, 10 - len(fmt_issues) * 0.5)
            scores.append(("format", format_score / 10))

        # 内容分
        if result.content_review:
            cr_scores = [
                v.get("score", 0) for v in result.content_review.values()
                if isinstance(v, dict)
            ]
            if cr_scores:
                content_score = sum(cr_scores) / len(cr_scores)
                scores.append(("content", content_score))

        # 文献分
        if result.reference_check:
            ref_issues = result.reference_check.get("issues", [])
            ref_score = max(0, 10 - len(ref_issues) * 1.0)
            scores.append(("reference", ref_score / 10))

        if not scores:
            return 0.0

        total = sum(weights.get(s[0], 0.33) * s[1] for s in scores)
        weight_sum = sum(weights.get(s[0], 0.33) for s in scores)
        return round(total / weight_sum, 2) if weight_sum > 0 else 0.0

    def _detect_file_type(self, path: Path) -> str:
        """检测文件类型"""
        suffix = path.suffix.lower()
        if suffix in {".tex", ".ltx", ".cls", ".sty"}:
            return "latex"
        elif suffix == ".docx":
            return "docx"
        elif suffix == ".pdf":
            return "pdf"
        return "unknown"
