"""
工具注册表 — 标准工具集的定义与注册工厂。

所有工具分为三类:
1. 本地确定性工具（零 token 成本）
2. Web 搜索工具（需网络）
3. LLM 辅助工具（消耗 token）
"""
from __future__ import annotations
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable
from dataclasses import dataclass, field

from article_check.core.harness.base import ToolSpec

logger = logging.getLogger(__name__)


class ToolRegistry:
    """
    工具注册表 — 集中管理所有可用工具。
    提供按类别分组、批量注册、schema 导出能力。
    """

    def __init__(self):
        self._tools: Dict[str, ToolSpec] = {}
        self._categories: Dict[str, List[str]] = {
            "format": [],
            "reference": [],
            "search": [],
            "report": [],
        }

    def add(
        self,
        category: str,
        name: str,
        description: str,
        parameters: Dict[str, Any],
        required: Optional[List[str]] = None,
        fn: Optional[Callable] = None,
    ) -> ToolSpec:
        """添加并返回一个工具规范"""
        spec = ToolSpec(
            name=name,
            description=description,
            parameters=parameters,
            required=required or [],
            fn=fn,
        )
        self._tools[name] = spec
        if category in self._categories:
            self._categories[category].append(name)
        logger.debug(f"注册工具 [{category}]: {name}")
        return spec

    def get(self, name: str) -> Optional[ToolSpec]:
        return self._tools.get(name)

    def all(self) -> List[ToolSpec]:
        return list(self._tools.values())

    def by_category(self, category: str) -> List[ToolSpec]:
        return [self._tools[n] for n in self._categories.get(category, [])]

    def schemas(self) -> List[Dict[str, Any]]:
        return [t.to_openai_tool() for t in self._tools.values()]

    def bind(self, name: str, fn: Callable):
        """将已有的工具规范绑定到实际函数"""
        if name not in self._tools:
            raise KeyError(f"工具 '{name}' 尚未注册")
        self._tools[name].fn = fn

    def size(self) -> int:
        return len(self._tools)


# ─── 预定义工具工厂 ─────────────────────────────────────

def create_format_tools() -> Dict[str, ToolSpec]:
    """
    创建格式检查工具集（零 token 成本 — 本地规则引擎）

    这些工具在 harness 层运行，不消耗 LLM token。
    只在规则引擎无法判断时，才升级到 AI 辅助。
    """
    registry = ToolRegistry()

    # LaTeX 格式检查 — 封装 chktex
    registry.add(
        category="format",
        name="check_latex_format",
        description="对 LaTeX 源码执行 chktex 检查，返回格式违规列表（40+ 规则）",
        parameters={
            "file_path": {
                "type": "string",
                "description": "LaTeX 文件路径"
            },
            "rules_filter": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "仅检查指定规则编号（可选）"
            }
        },
        required=["file_path"],
    )

    # Word 格式检查 — python-docx 引擎
    registry.add(
        category="format",
        name="check_docx_format",
        description="对 Word 文档执行样式/格式检查（标题、字体、段落、页边距、图表编号等）",
        parameters={
            "file_path": {
                "type": "string",
                "description": "Word 文件路径"
            },
            "template_path": {
                "type": "string",
                "description": "可选模板路径，用于对比样式一致性"
            },
            "review_track": {
                "type": "string",
                "enum": ["auto", "undergraduate", "graduate"],
                "description": "审查轨道：本科或研究生"
            }
        },
        required=["file_path"],
    )

    # 结构完整性检查
    registry.add(
        category="format",
        name="check_structure",
        description="检查论文结构完整性（摘要、引言、方法、结果、讨论、结论、参考文献）",
        parameters={
            "file_path": {
                "type": "string",
                "description": "论文文件路径"
            },
            "file_type": {
                "type": "string",
                "enum": ["latex", "docx"],
                "description": "文件类型"
            },
            "expected_sections": {
                "type": "array",
                "items": {"type": "string"},
                "description": "期望的章节列表"
            },
            "review_track": {
                "type": "string",
                "enum": ["auto", "undergraduate", "graduate"],
                "description": "审查轨道：本科或研究生"
            }
        },
        required=["file_path", "file_type"],
    )

    # 图表编号与引用一致性
    registry.add(
        category="format",
        name="check_figure_table_consistency",
        description="检查图表编号是否连续、是否有编号重复、引用是否存在对应的图表",
        parameters={
            "file_path": {"type": "string", "description": "文件路径"},
            "file_type": {"type": "string", "enum": ["latex", "docx"]},
        },
        required=["file_path", "file_type"],
    )

    return dict(registry._tools)


def create_reference_tools() -> Dict[str, ToolSpec]:
    """
    创建文献审查工具集（基于 API 调用 — 少量 token）

    利用 Semantic Scholar / CrossRef / OpenAlex 免费 API。
    """
    registry = ToolRegistry()

    # DOI 验证
    registry.add(
        category="reference",
        name="verify_doi",
        description="验证 DOI 是否存在并返回文献元数据",
        parameters={
            "doi": {"type": "string", "description": "DOI 标识符"}
        },
        required=["doi"],
    )

    # 参考文献真实性检查
    registry.add(
        category="reference",
        name="check_reference_exists",
        description="检查参考文献标题/作者是否在学术数据库中真实存在",
        parameters={
            "title": {"type": "string", "description": "文献标题"},
            "authors": {
                "type": "string",
                "description": "作者列表（逗号分隔）"
            },
            "year": {
                "type": "integer",
                "description": "发表年份"
            }
        },
        required=["title"],
    )

    # 引用准确性
    registry.add(
        category="reference",
        name="check_citation_accuracy",
        description="检查引用内容是否与原文一致（核验引用是否断章取义）",
        parameters={
            "claim": {"type": "string", "description": "论文中声称的内容"},
            "citation_ref": {"type": "string", "description": "引用的文献标识（DOI/URL）"}
        },
        required=["claim", "citation_ref"],
    )

    # 期刊匹配
    registry.add(
        category="reference",
        name="suggest_journals",
        description="根据论文标题和摘要，推荐匹配的投稿期刊",
        parameters={
            "title": {"type": "string", "description": "论文标题"},
            "abstract": {"type": "string", "description": "论文摘要"},
            "top_n": {
                "type": "integer",
                "description": "返回推荐数量",
                "default": 5
            }
        },
        required=["title", "abstract"],
    )

    # 文献缺失检查
    registry.add(
        category="reference",
        name="check_missing_references",
        description="检查是否遗漏了领域内的重要文献",
        parameters={
            "keywords": {
                "type": "array",
                "items": {"type": "string"},
                "description": "论文关键词列表"
            },
            "existing_refs": {
                "type": "array",
                "items": {"type": "string"},
                "description": "已有的参考文献标题"
            }
        },
        required=["keywords", "existing_refs"],
    )

    # 文献提取
    registry.add(
        category="reference",
        name="extract_references",
        description="从论文中提取所有参考文献条目",
        parameters={
            "paper_path": {"type": "string", "description": "论文文件路径"}
        },
        required=["paper_path"],
    )

    # 文献交叉验证
    registry.add(
        category="reference",
        name="cross_check_references",
        description="验证正文引用与参考文献表的一致性，检测缺失/多余引用",
        parameters={
            "paper_path": {"type": "string", "description": "论文文件路径"}
        },
        required=["paper_path"],
    )

    # 文献列表生成
    registry.add(
        category="reference",
        name="generate_bibliography",
        description="按IEEE/APA/ACM格式生成完整的参考文献列表",
        parameters={
            "paper_path": {"type": "string", "description": "论文文件路径"},
            "style": {
                "type": "string",
                "enum": ["ieee", "apa", "acm", "springer", "nature"],
                "description": "参考文献格式",
                "default": "ieee"
            }
        },
        required=["paper_path"],
    )

    # DOI 批量验证
    registry.add(
        category="reference",
        name="verify_doi_api",
        description="验证 DOI 并通过 CrossRef API 获取元数据",
        parameters={
            "doi": {"type": "string", "description": "DOI 标识符"}
        },
        required=["doi"],
    )

    return dict(registry._tools)


def create_search_tools() -> Dict[str, ToolSpec]:
    """创建 Web 搜索工具集"""
    registry = ToolRegistry()

    registry.add(
        category="search",
        name="web_search",
        description="搜索 web 获取领域最新信息（用于验证文献时效性、检查前沿进展）",
        parameters={
            "query": {"type": "string", "description": "搜索关键词"},
            "num_results": {
                "type": "integer",
                "description": "返回结果数",
                "default": 5
            }
        },
        required=["query"],
    )

    registry.add(
        category="search",
        name="search_arxiv",
        description="在 arXiv 搜索相关论文（用于文献对比和前沿追踪）",
        parameters={
            "query": {"type": "string", "description": "搜索关键词"},
            "max_results": {
                "type": "integer",
                "description": "最大结果数",
                "default": 10
            }
        },
        required=["query"],
    )

    return dict(registry._tools)


def create_report_tools() -> Dict[str, ToolSpec]:
    """创建报告生成工具集"""
    registry = ToolRegistry()

    registry.add(
        category="report",
        name="generate_markdown_report",
        description="生成 Markdown 格式的审查报告",
        parameters={
            "paper_title": {"type": "string"},
            "format_issues": {"type": "array", "items": {"type": "object"}},
            "content_review": {"type": "object"},
            "reference_check": {"type": "object"},
            "overall_score": {"type": "number"},
        },
        required=["paper_title", "overall_score"],
    )

    registry.add(
        category="report",
        name="generate_html_report",
        description="生成 HTML 格式的审查报告（含交互式图表）",
        parameters={
            "paper_title": {"type": "string"},
            "report_data": {"type": "object"},
            "template": {
                "type": "string",
                "description": "模板名称",
                "default": "default"
            }
        },
        required=["paper_title", "report_data"],
    )

    return dict(registry._tools)


# ─── 全局工具工厂 ───────────────────────────────────────

def get_default_tools() -> Dict[str, ToolSpec]:
    """获取所有默认工具（按名称索引）"""
    tools = {}
    tools.update(create_format_tools())
    tools.update(create_reference_tools())
    tools.update(create_search_tools())
    tools.update(create_report_tools())
    return tools
