"""
Harness 基类 — Agent 运行环境的核心抽象。

6-layer Harness 架构 (参考 Agent Harness Survey 2026):
  1. 信息边界: 什么 agent 知道/不知道
  2. 工具系统: 与世界的交互方式
  3. 执行编排: 多步序列化
  4. 记忆与状态: 管理中间/长期状态
  5. 评估与可观测性: 独立验证
  6. 约束与恢复: 护栏、重试、回滚
"""
from __future__ import annotations
import os
import time
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import (
    Any, Callable, Dict, List, Optional, Protocol, TypeVar, Union
)
from concurrent.futures import ThreadPoolExecutor, as_completed

from article_check.config.settings import config

logger = logging.getLogger(__name__)


class Tool(Protocol):
    """工具协议 — 所有注册到 Harness 的工具必须实现"""
    name: str
    description: str

    def __call__(self, **kwargs) -> Any: ...


T = TypeVar("T")


@dataclass
class HarnessContext:
    """Harness 上下文 — 在一次审查任务中传递的状态"""
    task_id: str
    paper_path: Path
    work_dir: Path
    start_time: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    token_usage: Dict[str, int] = field(default_factory=lambda: {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "cached_tokens": 0,
    })
    checkpoints: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolSpec:
    """工具元数据 — 用于 LLM function calling 的 schema"""
    name: str
    description: str
    parameters: Dict[str, Any]
    required: List[str] = field(default_factory=list)
    fn: Optional[Callable] = None

    def to_openai_tool(self) -> Dict[str, Any]:
        """转换为 OpenAI/DeepSeek 兼容的 tool 格式"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": self.parameters,
                    "required": self.required,
                }
            }
        }


class Harness:
    """
    Harness 主类 — 管理 Agent 的运行环境。

    核心职责:
    - 工具注册与调度 (Tool Manager)
    - 上下文边界管理 (Context Manager)
    - Token 使用监控 (40% 阈值)
    - 约束与重试 (Guardrails)
    """

    def __init__(self, config_override: Optional[Dict] = None):
        self.cfg = config
        self._tools: Dict[str, ToolSpec] = {}
        self._executor = ThreadPoolExecutor(
            max_workers=self.cfg.pipeline.max_concurrent
        )

    # ─── 工具管理 ────────────────────────────────────────

    def register_tool(self, spec: ToolSpec):
        """注册一个工具到 harness"""
        if spec.name in self._tools:
            logger.warning(f"Tool '{spec.name}' 被覆盖注册")
        self._tools[spec.name] = spec
        logger.debug(f"工具注册: {spec.name}")

    def register_tools(self, specs: List[ToolSpec]):
        for spec in specs:
            self.register_tool(spec)

    def get_tool(self, name: str) -> Optional[ToolSpec]:
        return self._tools.get(name)

    def list_tools(self) -> List[ToolSpec]:
        return list(self._tools.values())

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        """返回所有工具的 OpenAI function calling schema"""
        return [t.to_openai_tool() for t in self._tools.values()]

    def execute_tool(self, name: str, **kwargs) -> Any:
        """执行指定的工具"""
        spec = self.get_tool(name)
        if not spec or not spec.fn:
            raise ValueError(f"工具 '{name}' 未注册或未绑定实现")
        logger.info(f"执行工具: {name}({kwargs})")
        try:
            result = spec.fn(**kwargs)
            return result
        except Exception as e:
            logger.error(f"工具 '{name}' 执行失败: {e}")
            raise

    # ─── 并发执行 ────────────────────────────────────────

    def run_parallel(
        self,
        tasks: List[Callable[[], T]],
        timeout: Optional[int] = None
    ) -> List[T]:
        """并行执行一批任务，带超时控制"""
        timeout = timeout or self.cfg.pipeline.timeout_per_worker
        futures = [self._executor.submit(t) for t in tasks]
        results = []
        for future in as_completed(futures, timeout=timeout):
            try:
                results.append(future.result())
            except Exception as e:
                logger.error(f"并行任务失败: {e}")
                results.append(None)
        return results

    # ─── Token 监控 ──────────────────────────────────────

    def track_usage(self, ctx: HarnessContext, usage: Dict[str, int]):
        """追踪 token 使用，检查 40% 阈值"""
        for k, v in usage.items():
            ctx.token_usage[k] = ctx.token_usage.get(k, 0) + v

        total = ctx.token_usage["total_tokens"]
        if total > 0:
            usage_pct = total / 128000  # DeepSeek 128K 上下文
            if usage_pct > 0.40:
                logger.warning(
                    f"[{ctx.task_id}] Token 使用已达 {usage_pct:.0%} "
                    f"({total}/{128000})，逼近 40% 阈值"
                )

    # ─── 上下文管理 ──────────────────────────────────────

    def create_context(
        self,
        task_id: str,
        paper_path: Path,
        work_dir: Optional[Path] = None
    ) -> HarnessContext:
        """创建新的审查上下文"""
        return HarnessContext(
            task_id=task_id,
            paper_path=Path(paper_path),
            work_dir=work_dir or Path.cwd() / ".worktrees" / task_id,
        )

    # ─── 生命周期 ────────────────────────────────────────

    def close(self):
        """释放资源"""
        self._executor.shutdown(wait=True)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
