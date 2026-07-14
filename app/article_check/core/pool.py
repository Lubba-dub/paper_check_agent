"""弹性 Worker 池 — 自适应并发控制

根据实时信号动态调整并发数:
  - API 延迟低 → 增加并发
  - 错误率上升 → 降低并发
  - 队列积压 → 提高上限

参考: Hermes Concurrent Agents, MOSAIC (ILP scheduler)
"""
from __future__ import annotations
import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

MIN_CONCURRENCY = 1
MAX_CONCURRENCY = 16
ADAPT_INTERVAL = 10.0  # 每 10 秒评估一次


@dataclass
class PoolMetrics:
    """池指标快照"""
    active_workers: int = 0
    queue_depth: int = 0
    avg_latency: float = 0.0
    error_rate: float = 0.0
    total_completed: int = 0
    total_errors: int = 0
    current_limit: int = 4


class ElasticWorkerPool:
    """
    弹性 Worker 池 — 自适应并发

    用法:
        pool = ElasticWorkerPool(initial_limit=4)
        async for result in pool.run(tasks, worker_fn):
            print(f"完成: {result}")
    """

    def __init__(self, initial_limit: int = 4):
        self.limit = initial_limit
        self._sem = asyncio.Semaphore(initial_limit)
        self._metrics = PoolMetrics(current_limit=initial_limit)
        self._latencies: List[float] = []
        self._errors: int = 0
        self._completed: int = 0
        self._last_adapt = time.time()
        self._running = True
        logger.info(f"ElasticWorkerPool: initial_limit={initial_limit}")

    async def run(
        self,
        tasks: List[Any],
        worker_fn: Callable,
        task_id_fn: Optional[Callable] = None,
    ):
        """运行一批任务, 弹性并发控制"""
        self._metrics.queue_depth = len(tasks)
        pending = set()

        async def run_one(task: Any) -> tuple:
            async with self._sem:
                start = time.time()
                try:
                    result = await worker_fn(task)
                    latency = time.time() - start
                    self._latencies.append(latency)
                    self._completed += 1
                    return (task, result, None)
                except Exception as e:
                    self._errors += 1
                    latency = time.time() - start
                    self._latencies.append(latency)
                    self._completed += 1  # 计入已完成
                    return (task, None, str(e))

        # 提交所有任务
        futures = {asyncio.ensure_future(run_one(t)): t for t in tasks}

        while futures and self._running:
            # 定期自适应
            now = time.time()
            if now - self._last_adapt > ADAPT_INTERVAL:
                self._adapt()
                self._last_adapt = now

            done, _ = await asyncio.wait(
                futures.keys(), timeout=0.1,
                return_when="FIRST_COMPLETED",
            )
            for f in done:
                task, result, error = f.result()
                tid = task_id_fn(task) if task_id_fn else str(task)[:30]
                self._metrics.queue_depth = len(futures) - self._completed
                yield {"task_id": tid, "result": result, "error": error}
                del futures[f]

    def _adapt(self):
        """自适应调整并发限制"""
        if not self._latencies:
            return

        avg_lat = sum(self._latencies[-20:]) / max(len(self._latencies[-20:]), 1)
        err_rate = self._errors / max(self._completed + self._errors, 1)

        old_limit = self.limit
        if avg_lat < 1.0 and err_rate < 0.02:
            self.limit = min(self.limit + 1, MAX_CONCURRENCY)
        elif avg_lat > 5.0:
            self.limit = max(self.limit - 2, MIN_CONCURRENCY)
        elif err_rate > 0.05:
            self.limit = max(self.limit - 1, MIN_CONCURRENCY)
            logger.warning(f"错误率 {err_rate:.1%}, 降低并发 {old_limit}→{self.limit}")
            # 错误率恢复后等待
            if err_rate > 0.1:
                self._errors = 0  # 重置计数器

        if self.limit != old_limit:
            logger.info(f"自适应调整: {old_limit} → {self.limit} (延迟={avg_lat:.1f}s, 错误率={err_rate:.1%})")
            # 重建信号量
            self._sem = asyncio.Semaphore(self.limit)

        self._metrics = PoolMetrics(
            active_workers=self.limit,
            queue_depth=self._metrics.queue_depth,
            avg_latency=avg_lat,
            error_rate=err_rate,
            total_completed=self._completed,
            total_errors=self._errors,
            current_limit=self.limit,
        )

    @property
    def metrics(self) -> PoolMetrics:
        return self._metrics

    def stop(self):
        self._running = False
