"""
Harness 核心 — 定义了 Agent 的运行环境和工具集抽象层。

Harness = 所有"模型之外"的东西：工具系统、上下文管理、约束、可观测性。
参考: Agent Harness Survey 2026 的 6-layer 架构
"""
from article_check.core.harness.base import Harness, HarnessContext
from article_check.core.harness.tools import ToolRegistry, ToolSpec
