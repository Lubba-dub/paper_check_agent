"""
Agent 基类 — 所有审查 Agent 的抽象接口

每个 Agent 是一个独立的工作单元，可以：
- 接收一个任务（审查一篇论文的某个维度）
- 调用 Harness 中注册的工具
- 返回结构化结果
"""
from __future__ import annotations
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, TypeVar, Generic

from article_check.core.harness.base import Harness, HarnessContext

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass
class AgentResult(Generic[T]):
    """Agent 执行的返回结果"""
    success: bool
    data: Optional[T] = None
    error: Optional[str] = None
    duration: float = 0.0
    token_usage: Dict[str, int] = field(default_factory=dict)

    # 审查特有
    issues: List[Dict[str, Any]] = field(default_factory=list)
    score: Optional[float] = None
    suggestions: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "data": self.data,
            "error": self.error,
            "duration": self.duration,
            "token_usage": self.token_usage,
            "issues": self.issues,
            "score": self.score,
            "suggestions": self.suggestions,
        }


@dataclass
class AgentConfig:
    """Agent 运行配置"""
    name: str
    role: str  # format_checker / content_reviewer / reference_verifier / report_generator
    model: str = "deepseek-chat"
    temperature: float = 0.1
    max_tokens: int = 4096
    system_prompt_template: str = ""
    tools: List[str] = field(default_factory=list)


class Agent(ABC):
    """
    审查 Agent 的抽象基类。

    具体 Agent 需实现 execute() 方法，在方法中：
    1. 准备上下文和工具
    2. 调用 LLM
    3. 解析返回结果
    4. 返回 AgentResult
    """

    def __init__(
        self,
        config: AgentConfig,
        harness: Optional[Harness] = None,
    ):
        self.config = config
        self.harness = harness
        logger.info(f"Agent 初始化: {config.name} (role={config.role})")

    @abstractmethod
    async def execute(
        self,
        context: HarnessContext,
        input_data: Dict[str, Any],
    ) -> AgentResult:
        """执行审查任务"""
        ...

    def get_system_prompt(self, context: HarnessContext) -> str:
        """获取系统提示词（支持上下文注入）"""
        template = self.config.system_prompt_template
        if not template:
            return self._default_system_prompt()
        return template.format(**context.metadata)

    def _default_system_prompt(self) -> str:
        return f"""你是一个学术论文审查专家，担任 {self.config.role} 角色。
请基于学术规范进行专业、客观的审查。
"""

    def estimate_tokens(self, text: str) -> int:
        """粗略估算 token 数（以 DeepSeek 分词器近似）"""
        # 中文约 1.5 tokens/字，英文约 0.25 tokens/字母
        chinese_chars = sum(1 for c in text if '一' <= c <= '鿿')
        ascii_chars = len(text) - chinese_chars
        return int(chinese_chars * 1.5 + ascii_chars * 0.25)
