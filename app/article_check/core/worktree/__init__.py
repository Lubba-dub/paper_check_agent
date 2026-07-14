"""
工作树隔离 — 为每篇论文创建独立的工作区进行审查。

参考 Claude Code 的 worktree isolation 模式：
- 每篇论文在隔离的工作树中独立流水线审查
- 互不干扰，某篇崩溃不影响其他
- 审查完成自动清理
"""
from article_check.core.worktree.manager import WorktreeManager
from article_check.core.worktree.isolation import WorktreeContext
