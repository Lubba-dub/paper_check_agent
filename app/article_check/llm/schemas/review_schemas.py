"""
审查 Schema — 所有结构化输出的 Pydantic 模型

结构化输出是 Token 优化的关键策略之一:
- 强制 LLM 按 Schema 返回 → 减少 completion tokens 30-50%
- 避免自由文本 → 提高信息密度
- 机器可读 → 方便下游处理
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator


# ─── 格式审查 ───────────────────────────────────────

class FormatIssue(BaseModel):
    """单条格式问题"""
    type: str = Field(description="问题类型，如 heading_skip, font_inconsistency")
    severity: str = Field(description="严重程度: critical/major/minor/info")
    section: Optional[str] = Field(None, description="所在章节")
    line: Optional[int] = Field(None, description="行号")
    column: Optional[int] = Field(None, description="列号")
    description: str = Field(description="问题描述")
    suggestion: Optional[str] = Field(None, description="修改建议")
    rule_id: Optional[int] = Field(None, description="规则编号")


class FormatCheckResult(BaseModel):
    """格式审查结果"""
    file_type: str = Field(description="文件类型: latex/docx")
    issues: List[FormatIssue] = Field(default_factory=list)
    total_issues: int = Field(default=0)
    score: float = Field(default=1.0, ge=0.0, le=1.0)


# ─── 内容审查 ───────────────────────────────────────

class IssueDetail(BaseModel):
    """单条审查意见"""
    section: str = Field(description="相关章节")
    type: str = Field(description="问题类型: logic/clarity/completeness/methodology/result")
    severity: str = Field(description="严重程度")
    description: str = Field(description="具体问题")
    suggestion: Optional[str] = Field(None, description="改进建议")


class ContentReviewResult(BaseModel):
    """内容审查结果"""
    score: float = Field(default=0.0, ge=0.0, le=1.0, description="内容质量评分")
    strengths: List[str] = Field(default_factory=list, description="论文优点")
    weaknesses: List[str] = Field(default_factory=list, description="论文不足")
    issues: List[IssueDetail] = Field(default_factory=list)
    summary: str = Field(default="", description="审查总结")


# ─── 文献审查 ───────────────────────────────────────

class ReferenceCheck(BaseModel):
    """单条文献验证结果"""
    title: str = Field(description="文献标题")
    authors: Optional[str] = Field(None, description="作者")
    doi: Optional[str] = Field(None, description="DOI")
    verified: bool = Field(default=False, description="是否验证通过")
    exists_in_db: bool = Field(default=False, description="在学术数据库中是否存在")
    citation_accurate: Optional[bool] = Field(None, description="引用是否准确")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class ReferenceCheckResult(BaseModel):
    """文献审查结果"""
    verified_count: int = Field(default=0, description="已验证文献数")
    total_refs: int = Field(default=0, description="参考文献总数")
    missing_refs: List[ReferenceCheck] = Field(default_factory=list)
    citation_errors: List[ReferenceCheck] = Field(default_factory=list)
    score: float = Field(default=1.0, ge=0.0, le=1.0)


# ─── 综合报告 ───────────────────────────────────────

class ReviewReport(BaseModel):
    """完整审查报告"""
    paper_title: str = Field(description="论文标题")
    overall_score: float = Field(default=0.0, ge=0.0, le=1.0)

    format_check: FormatCheckResult = Field(default_factory=FormatCheckResult)
    content_review: ContentReviewResult = Field(default_factory=ContentReviewResult)
    reference_check: ReferenceCheckResult = Field(default_factory=ReferenceCheckResult)

    suggestions: List[str] = Field(default_factory=list)
    strengths: List[str] = Field(default_factory=list)
    critical_issues: List[str] = Field(default_factory=list)


# ─── JSON Schema 生成（用于 DeepSeek API） ───────────

# 格式审查 Schema
FORMAT_CHECK_SCHEMA = {
    "type": "object",
    "properties": {
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string"},
                    "severity": {"type": "string", "enum": ["critical", "major", "minor", "info"]},
                    "description": {"type": "string"},
                    "suggestion": {"type": "string"},
                },
                "required": ["type", "severity", "description"],
            },
        },
        "score": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["issues", "score"],
}

# 内容审查 Schema
CONTENT_REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "score": {"type": "number", "minimum": 0, "maximum": 1},
        "strengths": {"type": "array", "items": {"type": "string"}},
        "weaknesses": {"type": "array", "items": {"type": "string"}},
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "section": {"type": "string"},
                    "type": {"type": "string", "enum": ["logic", "clarity", "completeness", "methodology", "result"]},
                    "severity": {"type": "string", "enum": ["critical", "major", "minor"]},
                    "description": {"type": "string"},
                    "suggestion": {"type": "string"},
                },
                "required": ["section", "type", "severity", "description"],
            },
        },
        "summary": {"type": "string"},
    },
    "required": ["score", "issues", "summary"],
}

# 文献审查 Schema
REFERENCE_CHECK_SCHEMA = {
    "type": "object",
    "properties": {
        "verified_count": {"type": "integer"},
        "total_refs": {"type": "integer"},
        "citation_errors": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "error": {"type": "string"},
                    "severity": {"type": "string", "enum": ["minor", "major", "critical"]},
                },
            },
        },
        "score": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["verified_count", "total_refs", "score"],
}
