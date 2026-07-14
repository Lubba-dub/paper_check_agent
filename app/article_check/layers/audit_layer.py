from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from article_check.mcp.tools.format_tools import check_docx_format, check_structure

logger = logging.getLogger(__name__)

RULE_PROFILE_DIR = Path(__file__).resolve().parents[2] / "北师大论文格式要求"
UNDERGRAD_RULE_PATH = RULE_PROFILE_DIR / "bnu_undergraduate_template_rule_profile.json"
GRAD_RULE_PATH = RULE_PROFILE_DIR / "bnu_graduate_requirement_rule_profile.json"


def _load_rule_profile(review_track: str) -> Dict[str, Any]:
    rule_path = UNDERGRAD_RULE_PATH if review_track == "undergraduate" else GRAD_RULE_PATH
    try:
        return json.loads(rule_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("读取规则画像失败 [%s]: %s", review_track, exc)
        return {}


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()


def _pick_anchor(bundle: Dict[str, Any], issue: Dict[str, Any]) -> Dict[str, Any]:
    anchors = bundle.get("source_snippet_anchors") or []
    if not anchors:
        return {
            "anchor_id": None,
            "block_id": None,
            "page": None,
            "bbox": None,
            "locator": "unresolved",
        }

    location = issue.get("location") or {}
    section = str(location.get("section") or issue.get("section") or "").strip()
    if section:
        norm_section = _normalize_text(section)
        for node in bundle.get("document_structure") or []:
            if norm_section and norm_section in _normalize_text(node.get("heading", "")):
                block_ids = set(node.get("block_ids") or [])
                for anchor in anchors:
                    if anchor.get("block_id") in block_ids:
                        return {
                            "anchor_id": anchor.get("anchor_id"),
                            "block_id": anchor.get("block_id"),
                            "page": anchor.get("page"),
                            "bbox": anchor.get("bbox"),
                            "locator": node.get("heading"),
                        }

    line = location.get("line")
    if isinstance(line, int):
        for anchor in anchors:
            if anchor.get("paragraph_index") == line:
                return {
                    "anchor_id": anchor.get("anchor_id"),
                    "block_id": anchor.get("block_id"),
                    "page": anchor.get("page"),
                    "bbox": anchor.get("bbox"),
                    "locator": f"paragraph:{line}",
                }

    description = str(issue.get("description") or "")
    if description:
        snippet = _normalize_text(description[:24])
        for anchor in anchors:
            if snippet and snippet[:12] and snippet[:12] in _normalize_text(anchor.get("text_excerpt", "")):
                return {
                    "anchor_id": anchor.get("anchor_id"),
                    "block_id": anchor.get("block_id"),
                    "page": anchor.get("page"),
                    "bbox": anchor.get("bbox"),
                    "locator": anchor.get("text_excerpt", "")[:60],
                }

    anchor = anchors[0]
    return {
        "anchor_id": anchor.get("anchor_id"),
        "block_id": anchor.get("block_id"),
        "page": anchor.get("page"),
        "bbox": anchor.get("bbox"),
        "locator": anchor.get("text_excerpt", "")[:60],
    }


def _normalize_issue(issue: Dict[str, Any], bundle: Dict[str, Any], prefix: str, index: int) -> Dict[str, Any]:
    evidence_span = _pick_anchor(bundle, issue)
    location = issue.get("location") or {}
    if not location and issue.get("line"):
        location = {"line": issue.get("line")}
    if not location and issue.get("section"):
        location = {"section": issue.get("section")}
    if evidence_span.get("page") and "page" not in location:
        location["page"] = evidence_span["page"]

    return {
        "issue_id": issue.get("issue_id") or f"{prefix}-{index}",
        "type": issue.get("type") or prefix,
        "severity": issue.get("severity") or "minor",
        "description": issue.get("description") or issue.get("summary") or "",
        "suggestion": issue.get("suggestion") or "",
        "location": location,
        "evidence_span": evidence_span,
        "confidence": 1.0,
        "source_layer": "deterministic_audit",
        "rule_id": issue.get("rule_id"),
        "section": issue.get("section"),
    }


def _check_pdf_bundle(bundle: Dict[str, Any], review_track: str) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    structure = bundle.get("document_structure") or []
    headings = [_normalize_text(item.get("heading", "")) for item in structure]
    required = {
        "undergraduate": ["摘要", "关键词", "目录", "引言", "结论", "参考文献"],
        "graduate": ["摘要", "目录", "题名页", "版权页", "参考文献"],
    }.get(review_track, ["摘要", "参考文献"])

    for section in required:
        if not any(_normalize_text(section) in heading for heading in headings):
            issues.append(
                {
                    "type": "missing_section",
                    "severity": "major",
                    "section": section,
                    "description": f"PDF 版面中未识别到“{section}”章节。",
                    "suggestion": f"请补充或显式标注“{section}”章节标题。",
                    "location": {"section": section},
                }
            )

    pages = (bundle.get("layout") or {}).get("pages") or []
    target_margins = {"top": 72.0, "bottom": 72.0, "left": 90.0, "right": 72.0}
    for page in pages[:6]:
        margins = page.get("margins_pt") or {}
        for side, expected in target_margins.items():
            value = margins.get(side)
            if value is None:
                continue
            if abs(float(value) - expected) > 24:
                issues.append(
                    {
                        "type": "pdf_margin_deviation",
                        "severity": "major",
                        "description": f"第 {page.get('page_number')} 页{side}边距约 {value:.1f} pt，明显偏离常用论文版式。",
                        "suggestion": "请统一 PDF 导出或源文档页面边距。",
                        "location": {"page": page.get("page_number")},
                    }
                )

    figures = (bundle.get("layout") or {}).get("figures") or []
    captions = (bundle.get("layout") or {}).get("captions") or []
    if figures and not captions:
        issues.append(
            {
                "type": "caption_missing",
                "severity": "major",
                "description": "识别到图形对象，但未识别到相应图题/表题。",
                "suggestion": "请为图表补充规范的题注与编号。",
                "location": {"section": "figures"},
            }
        )
    return issues


def run_deterministic_audit(
    bundle: Dict[str, Any],
    *,
    review_track: Optional[str] = None,
) -> Dict[str, Any]:
    source_path = Path(bundle.get("source_path") or "")
    file_type = bundle.get("file_type") or ""
    track = review_track or bundle.get("review_track") or "graduate"
    rule_profile = _load_rule_profile(track)

    raw_issues: List[Dict[str, Any]] = []

    if source_path.exists() and file_type == "docx":
        raw_issues.extend(check_docx_format(str(source_path), review_track=track) or [])
        struct_result = check_structure(str(source_path), file_type=file_type, review_track=track) or {}
        raw_issues.extend(struct_result.get("issues", []))
    elif source_path.exists() and file_type == "pdf":
        raw_issues.extend(_check_pdf_bundle(bundle, track))
        struct_result = check_structure(str(source_path), file_type=file_type, review_track=track) or {}
        raw_issues.extend(struct_result.get("issues", []))
    elif source_path.exists():
        struct_result = check_structure(str(source_path), file_type=file_type, review_track=track) or {}
        raw_issues.extend(struct_result.get("issues", []))

    normalized: List[Dict[str, Any]] = []
    seen = set()
    for index, issue in enumerate(raw_issues, start=1):
        if not isinstance(issue, dict):
            continue
        item = _normalize_issue(issue, bundle, "det-audit", index)
        dedupe_key = (item.get("type"), item.get("description"), str(item.get("location")))
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        normalized.append(item)

    score = max(0.0, round(1.0 - len(normalized) * 0.06, 3))
    return {
        "layer": "deterministic_audit",
        "review_track": track,
        "rule_profile_type": rule_profile.get("profile_type"),
        "rule_source_document": rule_profile.get("source_document"),
        "issues": normalized,
        "issue_count": len(normalized),
        "score": score,
        "strong_format_issue_count": len([item for item in normalized if item.get("severity") in {"major", "critical"}]),
        "confidence": 1.0,
    }
