"""流式批处理 — 审查完一篇立即返回一篇

核心:
  - async generator: 审查结果逐篇产出
  - 不等全部完成, 先到先出
  - 兼容现有的 review_single 接口
"""
from __future__ import annotations
import asyncio
import logging
from typing import AsyncGenerator, List, Optional

from article_check.config.settings import config
from article_check.pipeline.models import PaperTask, PipelineResult
from article_check.pipeline.orchestrator import Orchestrator
from article_check.pipeline.worker import FormatWorker, ContentWorker, ReferenceWorker
from article_check.pipeline.reviewer import Reviewer
from article_check.llm.client.deepseek import DeepSeekClient

logger = logging.getLogger(__name__)


class StreamingOrchestrator(Orchestrator):
    """
    流式编排器 — 支持逐篇返回结果

    用法:
        orch = StreamingOrchestrator()
        async for result in orch.review_batch_stream(tasks):
            print(f"完成: {result.paper_title} 评分={result.overall_score}")
    """

    async def review_batch_stream(
        self,
        tasks: List[PaperTask],
        max_concurrent: Optional[int] = None,
    ) -> AsyncGenerator[PipelineResult, None]:
        """
        流式批量审查 — 完成一篇 yield 一篇

        Args:
            tasks: 论文任务列表
            max_concurrent: 最大并发数

        Yields:
            每篇论文审查完成后立即 yield
        """
        max_c = max_concurrent or config.pipeline.max_concurrent
        logger.info(f"流式批量审查: {len(tasks)} 篇, 并发={max_c}")

        sem = asyncio.Semaphore(max_c)
        pending = set()

        async def review_one(task: PaperTask) -> PipelineResult:
            async with sem:
                return await self.review_single(task)

        # 逐个提交, 完成即 yield
        for task in tasks:
            future = asyncio.ensure_future(review_one(task))
            pending.add(future)
            future.add_done_callback(pending.discard)

            # 一旦有完成的就 yield
            done, _ = await asyncio.wait(
                pending, timeout=0.01, return_when="FIRST_COMPLETED"
            )
            for f in done:
                try:
                    result = f.result()
                    yield result
                except Exception as e:
                    logger.error(f"流式任务失败: {e}")
                    yield PipelineResult(
                        paper_title=task.title or task.paper_path.stem,
                        task_id=task.task_id,
                        source_paper_path=str(task.paper_path),
                        source_file_name=task.paper_path.name,
                        review_track=task.review_track,
                        errors=[str(e)],
                    )

        # 收尾剩余的
        while pending:
            done, pending = await asyncio.wait(
                pending, return_when="FIRST_COMPLETED"
            )
            for f in done:
                try:
                    yield f.result()
                except Exception as e:
                    logger.error(f"流式收尾失败: {e}")
