"""
文献验证工具 — 调用学术数据库进行引文核实

API 调用成本低（免费额度），少量 token 用于结果解析。
"""
import logging
from typing import Any, Dict, List, Optional

from article_check.references import ReferenceValidator

logger = logging.getLogger(__name__)


def verify_doi(doi: str) -> Dict[str, Any]:
    """
    验证 DOI 是否存在并返回文献元数据

    使用 CrossRef API 或 Semantic Scholar API。

    Args:
        doi: DOI 标识符，如 "10.1038/nature12373"

    Returns:
        文献元数据
    """
    logger.info(f"verify_doi: {doi}")
    result = ReferenceValidator.verify_doi(doi)
    return {
        "doi": doi,
        "verified": result.get("valid", False),
        **result,
    }


def check_reference_exists(
    title: str,
    authors: Optional[str] = None,
    year: Optional[int] = None,
) -> Dict[str, Any]:
    """
    检查参考文献是否在学术数据库中真实存在

    Args:
        title: 文献标题
        authors: 作者列表（逗号分隔）
        year: 发表年份

    Returns:
        验证结果
    """
    logger.info(f"check_reference_exists: {title[:50]}...")
    return ReferenceValidator.check_reference_exists(
        title,
        authors=[item.strip() for item in (authors or "").split(",") if item.strip()],
        year=year,
    )


def check_citation_accuracy(
    claim: str,
    citation_ref: str,
) -> Dict[str, Any]:
    """
    检查引用内容是否与原文一致

    Args:
        claim: 论文中的声称
        citation_ref: 引用的文献标识

    Returns:
        核验结果
    """
    logger.info(f"check_citation_accuracy: {citation_ref}")
    return {
        "claim": claim,
        "citation_ref": citation_ref,
        "accurate": None,
        "message": "API 调用尚未实现",
    }


def suggest_journals(
    title: str,
    abstract: str,
    top_n: int = 5,
) -> List[Dict[str, Any]]:
    """
    根据论文标题和摘要推荐投稿期刊

    Args:
        title: 论文标题
        abstract: 论文摘要
        top_n: 返回数量

    Returns:
        推荐期刊列表
    """
    logger.info(f"suggest_journals: '{title[:50]}...' (top_n={top_n})")
    # TODO: 对接 journal-matcher 或 DOAJ API
    return []
