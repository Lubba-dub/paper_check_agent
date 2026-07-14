"""
文献工具 — 注册到 MCP 工具系统
"""
import logging
from typing import Any, Dict, List, Optional

from article_check.references import (
    ReferenceEngine, Reference, ReferenceGenerator,
    ReferenceParser, ReferenceValidator, ReferenceCheckResult,
)

logger = logging.getLogger(__name__)
_engine = ReferenceEngine()


def extract_references(
    paper_path: str,
) -> Dict[str, Any]:
    """从论文中提取参考文献"""
    refs = _engine.extract_from_paper(paper_path)
    return {
        "count": len(refs),
        "refs": [
            {
                "ref_id": r.ref_id,
                "title": r.title[:80],
                "authors": r.authors[:3],
                "year": r.year,
                "doi": r.doi,
            }
            for r in refs[:20]
        ],
    }


def cross_check_references(
    paper_path: str,
) -> Dict[str, Any]:
    """交叉验证参考文献一致性"""
    result = _engine.validate(paper_path)
    refs = _engine.extract_from_paper(paper_path)
    quality_checks = [_engine.check_ref_quality(ref) for ref in refs[: min(len(refs), 5)]]
    suspicious_refs = [
        item for item in quality_checks
        if item.get("exists") is False or item.get("doi_verified") is False
    ]
    return {
        "total_refs": result.total_refs,
        "total_citations": result.total_citations,
        "matched": result.matched,
        "unmatched_citations": result.unmatched_citations[:10],
        "unused_refs": result.unused_refs[:10],
        "doi_missing": len(result.doi_missing),
        "score": result.score,
        "quality_checks": quality_checks,
        "suspicious_references": suspicious_refs,
    }


def verify_doi_api(
    doi: str,
) -> Dict[str, Any]:
    """验证 DOI 并返回元数据"""
    return ReferenceValidator.verify_doi(doi)


def generate_bibliography(
    paper_path: str,
    style: str = "ieee",
) -> str:
    """按指定格式生成参考文献列表"""
    refs = _engine.extract_from_paper(paper_path)
    return _engine.generate_bibliography(refs, style)


def check_ref_quality_api(
    paper_path: str,
    ref_index: int = 1,
) -> Dict[str, Any]:
    """检查单一文献质量"""
    refs = _engine.extract_from_paper(paper_path)
    if not refs or ref_index > len(refs):
        return {"error": f"索引 {ref_index} 超出范围 (共 {len(refs)} 篇)"}
    return _engine.check_ref_quality(refs[ref_index - 1])
