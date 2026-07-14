"""
Context Curator — 独立上下文管理器，解耦上下文策展与任务执行

核心职责：
1. 跟踪每一步的 token 消耗和信息价值
2. 在上下文超过阈值时触发策展
3. 支持弹性类型 (raw / abstract / drop) 决策
4. 可逆压缩 — 关键信息永不丢失
5. 与 Harness 解耦，可插拔

参考架构:
- SelfCompact (arXiv:2606.23525): LLM 自压缩
- ACE (arXiv:2606.31564): 弹性上下文类型
- ContextCurator (arXiv:2604.11462): 解耦式上下文管理
- ACON (ICML 2026): 失败驱动的迭代优化
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Callable

from article_check.config.settings import config

logger = logging.getLogger(__name__)

# ─── 常量 ─────────────────────────────────────────────

MAX_CONTEXT_TOKENS = 128000  # DeepSeek 128K
COMPACTION_THRESHOLD = 0.70  # 超过 70% 触发压缩
CRITICAL_THRESHOLD = 0.90    # 超过 90% 强制紧急压缩


# ─── 弹性类型 ─────────────────────────────────────────

class ElasticType(str, Enum):
    """ACE 弹性类型 — 每步历史的处理方式"""
    RAW = "raw"           # 保留原始信息（重要步骤）
    ABSTRACT = "abstract" # 压缩为摘要（普通步骤）
    DROP = "drop"         # 丢弃（噪声步骤）
    LATENT = "latent"     # 保留为隐空间表示（Latent Briefing）


@dataclass
class ContextStep:
    """上下文中的一步"""
    step_id: int
    role: str                    # system / user / assistant / tool
    content: str
    token_count: int
    elastic_type: ElasticType = ElasticType.RAW
    importance_score: float = 1.0   # 0.0 ~ 1.0
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    # 压缩后保留的信息（可逆）
    abstract: Optional[str] = None
    latent_key: Optional[str] = None  # KV cache reference
    original_content_hash: Optional[str] = None


@dataclass
class CuratorDecision:
    """策展决策记录"""
    step_id: int
    old_type: ElasticType
    new_type: ElasticType
    reason: str
    tokens_saved: int
    reversible: bool = True


@dataclass
class CuratorMetrics:
    """策展指标"""
    total_steps: int = 0
    total_tokens: int = 0
    compressed_tokens: int = 0
    decisions: List[CuratorDecision] = field(default_factory=list)
    compaction_count: int = 0

    @property
    def compression_ratio(self) -> float:
        if self.total_tokens == 0:
            return 1.0
        return (self.total_tokens - self.compressed_tokens) / self.total_tokens


# ─── 策展策略 ─────────────────────────────────────────

class CuratorStrategy:
    """策展策略抽象 — 决定每步的弹性类型"""

    def classify(self, step: ContextStep, metrics: CuratorMetrics) -> Tuple[ElasticType, str]:
        """返回 (弹性类型, 原因)"""
        raise NotImplementedError


class BaselineStrategy(CuratorStrategy):
    """基线策略 — 基于规则的策略"""

    def __init__(self):
        # 高重要性信号
        self.high_importance_keywords = [
            "error", "exception", "fail", "critical",
            "decision", "approve", "confirm",
        ]

    def classify(self, step: ContextStep, metrics: CuratorMetrics) -> Tuple[ElasticType, str]:
        # Tool call 结果通常有高信息密度
        if step.role == "tool" and step.token_count > 500:
            return (ElasticType.ABSTRACT, "长工具输出 → 摘要")

        # 低重要性
        if step.importance_score < 0.3:
            return (ElasticType.DROP, f"低重要性 ({step.importance_score:.2f})")

        if step.importance_score < 0.6:
            return (ElasticType.ABSTRACT, f"中等重要性 ({step.importance_score:.2f})")

        # 高重要性关键词
        if any(kw in step.content.lower() for kw in self.high_importance_keywords):
            return (ElasticType.RAW, "高重要性关键词匹配")

        return (ElasticType.ABSTRACT, "默认 → 摘要")


class LLMStrategy(CuratorStrategy):
    """LLM 驱动策略 — 让 LLM 自己决定（SelfCompact 模式）"""

    def __init__(self, llm_classify_fn: Optional[Callable] = None):
        self._llm_classify = llm_classify_fn

    def classify(self, step: ContextStep, metrics: CuratorMetrics) -> Tuple[ElasticType, str]:
        if self._llm_classify:
            return self._llm_classify(step, metrics)

        # 降级到基线
        return BaselineStrategy().classify(step, metrics)


class ACONStrategy(CuratorStrategy):
    """
    ACON 策略 — 从失败中学习

    记录每次审查的"失败模式"（如遗漏了关键信息），
    在下一次压缩时调整阈值。
    """

    def __init__(self):
        self.failure_log: List[Dict] = []
        self.threshold_adjustments: Dict[str, float] = {
            "importance": 0.4,
            "token_max": 500,
        }

    def record_failure(self, failure: Dict):
        """记录失败的压缩决策"""
        self.failure_log.append(failure)
        # 动态调整阈值
        if failure.get("missed_important"):
            self.threshold_adjustments["importance"] *= 0.8
        if failure.get("over_compressed"):
            self.threshold_adjustments["token_max"] *= 1.2

    def classify(self, step: ContextStep, metrics: CuratorMetrics) -> Tuple[ElasticType, str]:
        # 根据调整后的阈值决策
        if step.importance_score < self.threshold_adjustments["importance"]:
            return (ElasticType.DROP, "ACON: 低于调整后阈值")
        if step.token_count > self.threshold_adjustments["token_max"]:
            return (ElasticType.ABSTRACT, "ACON: 超过调整后长度阈值")
        return (ElasticType.RAW, "ACON: 保留")


# ─── Context Curator 主类 ────────────────────────────

@dataclass
class CompactionReport:
    """策展报告"""
    before_tokens: int
    after_tokens: int
    saved_tokens: int
    saved_percent: float
    decisions: List[CuratorDecision]
    duration: float


class ContextCurator:
    """
    Context Curator — 上下文策展人

    独立于 Harness 和 TaskExecutor 运行。
    追踪上下文状态，在阈值触发时执行策展。

    用例:
        curator = ContextCurator(strategy=ACONStrategy())
        curator.observe_step(step)
        if curator.should_compact():
            report = curator.compact()
    """

    def __init__(
        self,
        strategy: Optional[CuratorStrategy] = None,
        threshold: float = COMPACTION_THRESHOLD,
    ):
        self.strategy = strategy or BaselineStrategy()
        self.threshold = threshold
        self.steps: List[ContextStep] = []
        self.metrics = CuratorMetrics()
        self._step_counter = 0
        self._compressed_abstracts: Dict[int, str] = {}  # 可逆存储
        logger.info(f"ContextCurator 初始化: strategy={type(self.strategy).__name__}, threshold={threshold}")

    # ── 核心接口 ──────────────────────────────────────

    def observe(self, role: str, content: str, metadata: Optional[Dict] = None) -> ContextStep:
        """记录一步上下文"""
        self._step_counter += 1
        step = ContextStep(
            step_id=self._step_counter,
            role=role,
            content=content,
            token_count=self._estimate_tokens(content),
            metadata=metadata or {},
        )
        self.steps.append(step)
        self.metrics.total_steps += 1
        self.metrics.total_tokens += step.token_count
        logger.debug(f"观察步骤 #{step.step_id}: role={role}, tokens={step.token_count}")
        return step

    def observe_step(self, step: ContextStep) -> ContextStep:
        """直接记录 ContextStep 对象"""
        self.steps.append(step)
        self.metrics.total_steps += 1
        self.metrics.total_tokens += step.token_count
        return step

    # ── 策展决策 ──────────────────────────────────────

    def should_compact(self) -> bool:
        """判断是否需要压缩"""
        current_tokens = self.total_current_tokens
        ratio = current_tokens / MAX_CONTEXT_TOKENS
        if ratio >= self.threshold:
            logger.info(f"触发压缩: {current_tokens}/{MAX_CONTEXT_TOKENS} ({ratio:.0%})")
            return True
        if ratio >= CRITICAL_THRESHOLD:
            logger.warning(f"紧急压缩: {current_tokens}/{MAX_CONTEXT_TOKENS} ({ratio:.0%})")
            return True
        return False

    @property
    def total_current_tokens(self) -> int:
        """当前总 token 数（只计算 RAW 和 ABSTRACT）"""
        return sum(
            s.token_count for s in self.steps
            if s.elastic_type in (ElasticType.RAW, ElasticType.ABSTRACT)
        )

    @property
    def usage_ratio(self) -> float:
        """上下文使用率"""
        return self.total_current_tokens / MAX_CONTEXT_TOKENS

    def compact(self, force: bool = False) -> CompactionReport:
        """
        执行上下文压缩

        Args:
            force: 即使未达阈值也强制压缩

        Returns:
            策展报告
        """
        start = time.time()
        if not force and not self.should_compact():
            logger.info("无需压缩")
            return CompactionReport(
                before_tokens=self.total_current_tokens,
                after_tokens=self.total_current_tokens,
                saved_tokens=0,
                saved_percent=0,
                decisions=[],
                duration=0,
            )

        before = self.total_current_tokens
        decisions = []

        for step in self.steps:
            if step.elastic_type == ElasticType.DROP:
                continue  # 已丢弃

            old_type = step.elastic_type
            new_type, reason = self.strategy.classify(step, self.metrics)

            if new_type != old_type:
                # 保存摘要（可逆）
                if new_type == ElasticType.ABSTRACT and step.content:
                    step.abstract = self._summarize(step.content)
                    self._compressed_abstracts[step.step_id] = step.content

                elif new_type == ElasticType.DROP:
                    # 丢弃前保存原文（可逆）
                    self._compressed_abstracts[step.step_id] = step.content
                    step.abstract = "[已压缩，可恢复]"

                elif new_type == ElasticType.LATENT:
                    step.latent_key = f"latent_{step.step_id}"

                step.elastic_type = new_type
                tokens_saved = step.token_count if new_type == ElasticType.DROP else \
                               step.token_count - self._estimate_tokens(step.abstract or "")

                decision = CuratorDecision(
                    step_id=step.step_id,
                    old_type=old_type,
                    new_type=new_type,
                    reason=reason,
                    tokens_saved=tokens_saved,
                    reversible=True,
                )
                decisions.append(decision)
                self.metrics.compressed_tokens += tokens_saved

        self.metrics.compaction_count += 1
        after = self.total_current_tokens
        duration = time.time() - start

        report = CompactionReport(
            before_tokens=before,
            after_tokens=after,
            saved_tokens=before - after,
            saved_percent=((before - after) / before * 100) if before > 0 else 0,
            decisions=decisions,
            duration=duration,
        )

        logger.info(
            f"压缩完成: {report.saved_tokens} tokens saved "
            f"({report.saved_percent:.1f}%) in {duration:.2f}s"
        )
        return report

    # ── 可逆操作 ──────────────────────────────────────

    def restore(self, step_id: int) -> Optional[str]:
        """恢复被压缩的步骤原文"""
        return self._compressed_abstracts.get(step_id)

    def get_active_context(self) -> List[ContextStep]:
        """获取当前活跃的上下文（构建 messages 用）"""
        active = []
        for step in self.steps:
            if step.elastic_type == ElasticType.DROP and step.step_id not in self._compressed_abstracts:
                continue
            if step.elastic_type == ElasticType.ABSTRACT and step.abstract:
                step.content = step.abstract
            if step.elastic_type == ElasticType.RAW or step.elastic_type == ElasticType.ABSTRACT:
                active.append(step)
        return active

    def get_messages(self) -> List[Dict[str, str]]:
        """生成 LLM messages（供 API 调用）"""
        return [
            {"role": s.role, "content": s.content}
            for s in self.get_active_context()
        ]

    def get_compaction_history(self) -> List[Dict]:
        """获取策展历史"""
        return [
            {
                "step_id": d.step_id,
                "from": d.old_type.value,
                "to": d.new_type.value,
                "reason": d.reason,
                "tokens_saved": d.tokens_saved,
            }
            for d in self.metrics.decisions
        ]

    # ── 内部方法 ──────────────────────────────────────

    def _estimate_tokens(self, text: str) -> int:
        """估算 token 数"""
        chinese = sum(1 for c in text if '一' <= c <= '鿿')
        ascii_chars = len(text) - chinese
        return int(chinese * 1.5 + ascii_chars * 0.25)

    def _summarize(self, text: str, max_ratio: float = 0.3) -> str:
        """本地摘要（零 token）——提取关键句"""
        # 简单策略：保留首句和尾句，中间截断
        lines = text.strip().split("\n")
        if len(lines) <= 3:
            return text

        head = lines[0] if lines[0] else ""
        tail = lines[-1] if lines[-1] else ""
        middle_count = max(1, int(len(lines) * max_ratio))
        middle = "\n".join(lines[1:1 + middle_count])

        summary = f"{head}\n{'' if len(head) < 50 else '...'}\n{middle}\n...\n{tail}"
        # 确保长度不超过原始 30%
        max_len = int(len(text) * max_ratio)
        if len(summary) > max_len:
            summary = summary[:max_len] + "..."
        return summary

    def reset(self):
        """重置策展状态"""
        self.steps = []
        self.metrics = CuratorMetrics()
        self._compressed_abstracts = {}
        self._step_counter = 0
        logger.info("ContextCurator 已重置")

    def report(self) -> Dict[str, Any]:
        """策展报告"""
        return {
            "total_steps": self.metrics.total_steps,
            "total_tokens": self.metrics.total_tokens,
            "current_tokens": self.total_current_tokens,
            "usage_ratio": self.usage_ratio,
            "compaction_count": self.metrics.compaction_count,
            "compression_ratio": self.metrics.compression_ratio,
            "active_steps": len(self.get_active_context()),
            "strategy": type(self.strategy).__name__,
            "threshold": self.threshold,
        }
