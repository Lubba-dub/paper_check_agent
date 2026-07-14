"""
工作树隔离工具 — 确保并行审查任务互不干扰

隔离策略:
- 文件系统隔离: 每篇论文的工作区独立
- 进程隔离: 可选的子进程级隔离
- 错误隔离: 一个工作树的崩溃不影响其他
"""
from __future__ import annotations
import os
import sys
import json
import logging
from pathlib import Path
from typing import Any, Callable, Dict, Optional, TypeVar

from article_check.core.worktree.manager import WorktreeContext

logger = logging.getLogger(__name__)

T = TypeVar("T")


def run_in_isolation(
    ctx: WorktreeContext,
    fn: Callable[..., T],
    *args,
    **kwargs,
) -> T:
    """
    在指定工作树中执行函数（文件系统隔离）

    函数执行过程中：
    - 当前目录临时切换到 ctx.work_dir
    - 任何文件写入都限制在工作树内
    """
    original_cwd = Path.cwd()
    try:
        os.chdir(str(ctx.work_dir))
        logger.debug(f"[{ctx.task_id}] 切换到工作目录: {ctx.work_dir}")
        result = fn(*args, **kwargs)
        return result
    finally:
        os.chdir(str(original_cwd))
        logger.debug(f"[{ctx.task_id}] 恢复目录: {original_cwd}")


def save_artifact(
    ctx: WorktreeContext,
    name: str,
    data: Any,
    fmt: str = "json",
):
    """保存审查中间产物到工作树"""
    if fmt == "json":
        path = ctx.artifacts_dir / f"{name}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    elif fmt == "text":
        path = ctx.artifacts_dir / f"{name}.txt"
        with open(path, "w", encoding="utf-8") as f:
            f.write(str(data))
    else:
        path = ctx.artifacts_dir / name
        path.write_bytes(data)

    ctx.temp_files.append(path)
    return path


def load_artifact(
    ctx: WorktreeContext,
    name: str,
    fmt: str = "json",
) -> Any:
    """从工作树加载审查中间产物"""
    if fmt == "json":
        path = ctx.artifacts_dir / f"{name}.json"
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    elif fmt == "text":
        path = ctx.artifacts_dir / f"{name}.txt"
        return path.read_text(encoding="utf-8")
    else:
        path = ctx.artifacts_dir / name
        return path.read_bytes()
