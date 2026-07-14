from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from article_check.config.settings import config
from article_check.layers import (
    build_evidence_bundle,
    build_evidence_index,
    build_section_digest,
    run_deterministic_audit,
    run_layered_verification,
)
from article_check.llm.client.dify import DifyClient
from article_check.references import ReferenceEngine
from article_check.runtime import generate_advice_report, generate_formal_review_report
from article_check.utils.file_utils import detect_file_type, extract_text_from_docx, extract_text_from_pdf, read_paper_content

logger = logging.getLogger(__name__)

RULE_DIR = Path.cwd() / "北师大论文格式要求"
API_DOC_PATH = Path.cwd() / "dify_api.md"
API_DOC_EXAMPLE_PATH = Path.cwd() / "dify_api.example.md"

UNDERGRAD_RULE_PATH = RULE_DIR / "bnu_undergraduate_template_rule_profile.json"
GRAD_RULE_PATH = RULE_DIR / "bnu_graduate_requirement_rule_profile.json"

DOCUMENT_READ_DSL = "articlecheck_document_read_workflow.yml"
FORMAT_REVIEW_DSL = "articlecheck_format_review_workflow.yml"
REFERENCE_REVIEW_DSL = "articlecheck_reference_verify_workflow.yml"
HALLUCINATION_REVIEW_DSL = "articlecheck_hallucination_review_workflow.yml"
REPORT_GENERATION_DSL = "articlecheck_report_generation_workflow.yml"
REPORT_QA_DSL = "articlecheck_report_qa_workflow.yml"
PRIMARY_DIFY_DSLS = {
    DOCUMENT_READ_DSL,
    FORMAT_REVIEW_DSL,
    HALLUCINATION_REVIEW_DSL,
    REPORT_GENERATION_DSL,
    REPORT_QA_DSL,
}
ENV_BINDING_MAP = {
    DOCUMENT_READ_DSL: "DOCUMENT_READ",
    FORMAT_REVIEW_DSL: "FORMAT_REVIEW",
    REFERENCE_REVIEW_DSL: "REFERENCE_VERIFY",
    HALLUCINATION_REVIEW_DSL: "HALLUCINATION_REVIEW",
    REPORT_GENERATION_DSL: "REPORT_GENERATION",
    REPORT_QA_DSL: "REPORT_QA",
}


@dataclass
class DifyWorkflowBinding:
    dsl_file: str
    purpose: str
    app_reference: str
    api_key: str
    base_url: str
    mode: str
    input_vars: List[str]
    output_vars: List[str]


def _clean_md_cell(raw: str) -> str:
    cleaned = raw.strip().strip("`").strip()
    if cleaned.startswith("<") and cleaned.endswith(">"):
        cleaned = cleaned[1:-1]
    cleaned = cleaned.replace("<br />", " ").replace("<br/>", " ")
    return cleaned.strip()


def _build_env_workflow_bindings() -> Dict[str, DifyWorkflowBinding]:
    base_url_default = (
        os.getenv("ARTICLE_CHECK_DIFY_BASE_URL")
        or os.getenv("DIFY_BASE_URL")
        or config.dify.base_url
    ).rstrip("/")
    mode_default = (os.getenv("ARTICLE_CHECK_DIFY_APP_MODE") or "workflow").strip().lower()
    common_api_key = os.getenv("ARTICLE_CHECK_DIFY_API_KEY") or os.getenv("DIFY_API_KEY") or ""

    bindings: Dict[str, DifyWorkflowBinding] = {}
    for dsl_name, env_suffix in ENV_BINDING_MAP.items():
        prefix = f"ARTICLE_CHECK_DIFY_{env_suffix}"
        api_key = os.getenv(f"{prefix}_API_KEY") or common_api_key
        base_url = (os.getenv(f"{prefix}_BASE_URL") or base_url_default).rstrip("/")
        mode = (os.getenv(f"{prefix}_MODE") or mode_default).strip().lower()
        app_reference = os.getenv(f"{prefix}_APP_REFERENCE") or ""
        if not api_key or not base_url:
            continue
        bindings[dsl_name] = DifyWorkflowBinding(
            dsl_file=f"dify_dsl/{dsl_name}",
            purpose=env_suffix.lower(),
            app_reference=app_reference,
            api_key=api_key,
            base_url=base_url,
            mode=mode,
            input_vars=[],
            output_vars=[],
        )
    return bindings


@lru_cache(maxsize=1)
def load_dify_workflow_bindings(doc_path: str = str(API_DOC_PATH)) -> Dict[str, DifyWorkflowBinding]:
    path = Path(doc_path)
    bindings: Dict[str, DifyWorkflowBinding] = {}
    if path.exists() or API_DOC_EXAMPLE_PATH.exists():
        if not path.exists():
            path = API_DOC_EXAMPLE_PATH
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        in_table = False

        for line in lines:
            if line.startswith("## DSL / API 填写表"):
                in_table = True
                continue
            if in_table and line.startswith("## "):
                break
            if not in_table or not line.strip().startswith("|"):
                continue
            if "---" in line or "序号" in line:
                continue

            parts = [_clean_md_cell(part) for part in line.strip().strip("|").split("|")]
            if len(parts) < 12:
                continue
            dsl_file = parts[1]
            dsl_name = Path(dsl_file).name
            bindings[dsl_name] = DifyWorkflowBinding(
                dsl_file=dsl_file,
                purpose=parts[2],
                app_reference=parts[4],
                api_key=parts[5],
                base_url=parts[6].rstrip("/"),
                mode=(parts[8] or "workflow").strip("`").lower(),
                input_vars=[item.strip().strip("`") for item in parts[9].split(",") if item.strip()],
                output_vars=[item.strip().strip("`") for item in parts[10].split(",") if item.strip()],
            )

    env_bindings = _build_env_workflow_bindings()
    if env_bindings:
        bindings.update(env_bindings)
    if not bindings:
        raise FileNotFoundError(f"Dify API 文档不存在且未提供环境变量绑定: {path}")
    return bindings


def dify_workflows_available() -> bool:
    try:
        bindings = load_dify_workflow_bindings()
    except Exception:
        return False
    if not PRIMARY_DIFY_DSLS.issubset(set(bindings)):
        return False
    return all(
        bool(item.api_key and item.base_url)
        for name, item in bindings.items()
        if name in PRIMARY_DIFY_DSLS
    )


def get_dify_registry_status() -> Dict[str, Any]:
    try:
        bindings = load_dify_workflow_bindings()
    except Exception as exc:
        return {"available": False, "error": str(exc), "workflows": []}
    return {
        "available": dify_workflows_available(),
        "workflow_count": len(bindings),
        "primary_workflow_count": len(PRIMARY_DIFY_DSLS),
        "workflows": [
            {
                "dsl_file": name,
                "purpose": item.purpose,
                "base_url": item.base_url,
                "configured": bool(item.api_key and item.base_url),
                "is_primary": name in PRIMARY_DIFY_DSLS,
            }
            for name, item in bindings.items()
        ],
    }


@lru_cache(maxsize=2)
def load_rule_profiles() -> Tuple[Dict[str, Any], Dict[str, Any]]:
    undergraduate = json.loads(UNDERGRAD_RULE_PATH.read_text(encoding="utf-8"))
    graduate = json.loads(GRAD_RULE_PATH.read_text(encoding="utf-8"))
    return undergraduate, graduate


def _extract_text(path: Path) -> str:
    file_type = detect_file_type(path)
    if file_type in {"text", "markdown", "latex"}:
        return read_paper_content(path)
    if file_type == "pdf":
        return extract_text_from_pdf(path)
    if file_type == "docx":
        return extract_text_from_docx(path)
    return read_paper_content(path) if path.exists() else ""


def _detect_language(text: str) -> str:
    if not text:
        return ""
    zh_count = len(re.findall(r"[\u4e00-\u9fff]", text))
    en_count = len(re.findall(r"[A-Za-z]", text))
    return "zh" if zh_count >= en_count else "en"


def _normalize_heading(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "")).rstrip(":：")


def _detect_heading_level(line: str) -> Optional[int]:
    candidate = line.strip()
    if not candidate or len(candidate) > 80:
        return None

    normalized = _normalize_heading(candidate).lower()
    if normalized in {
        "摘要", "abstract", "关键词", "目录", "引言", "前言", "绪论", "正文",
        "结论", "结语", "参考文献", "致谢", "附录", "references",
    }:
        return 1
    if re.match(r"^第[一二三四五六七八九十\d]+章", candidate):
        return 1
    if re.match(r"^[一二三四五六七八九十]+[、.．].+", candidate):
        return 1
    if re.match(r"^\d+\.\d+(\.\d+){0,2}\s*\S+", candidate):
        return min(candidate.count(".") + 1, 4)
    if re.match(r"^\d+[.、]\s*\S+", candidate):
        return 2
    if re.match(r"^[（(][一二三四五六七八九十\d]+[）)]\s*\S+", candidate):
        return 3
    return None


def _is_heading(line: str) -> bool:
    return _detect_heading_level(line) is not None


def _extract_sections(text: str, *, max_sections: int = 24, excerpt_chars: int = 800) -> List[Dict[str, Any]]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return []

    sections: List[Dict[str, Any]] = []
    current_heading = "全文"
    current_heading_level = 0
    current_raw_heading = "全文"
    current_body: List[str] = []
    heading_stack: Dict[int, str] = {}

    def flush_section() -> None:
        if not current_body and current_heading == "全文":
            return
        body_text = "\n".join(current_body).strip()
        sections.append(
            {
                "heading": current_heading,
                "raw_heading": current_raw_heading,
                "heading_level": current_heading_level,
                "text": body_text[:excerpt_chars],
                "char_count": len(body_text),
            }
        )

    for line in lines[:2000]:
        heading_level = _detect_heading_level(line)
        if heading_level:
            flush_section()
            heading_stack[heading_level] = line
            for level in list(heading_stack.keys()):
                if level > heading_level:
                    heading_stack.pop(level, None)

            if heading_level <= 1:
                display_heading = line
            else:
                parents = [heading_stack[level] for level in sorted(heading_stack) if level < heading_level]
                display_heading = " / ".join(parents + [line]) if parents else line

            current_heading = display_heading
            current_raw_heading = line
            current_heading_level = heading_level
            current_body = []
            if len(sections) >= max_sections:
                break
            continue
        current_body.append(line)
    flush_section()
    return sections[:max_sections]


def _extract_references_preview(path: Path) -> Dict[str, Any]:
    engine = ReferenceEngine()
    refs = []
    quality_checks = []
    try:
        refs = engine.extract_from_paper(str(path))
    except Exception as exc:
        logger.warning("提取参考文献失败: %s", exc)
    try:
        validation = engine.validate(str(path), refs=refs)
    except Exception as exc:
        logger.warning("验证参考文献失败: %s", exc)
        validation = None
    try:
        quality_checks = [engine.check_ref_quality(item) for item in refs[: min(len(refs), 8)]]
    except Exception as exc:
        logger.warning("抽样核验参考文献质量失败: %s", exc)

    return {
        "total_refs": len(refs),
        "refs": [
            {
                "ref_id": item.ref_id,
                "title": item.title[:120],
                "authors": item.authors[:4],
                "year": item.year,
                "doi": item.doi,
                "source": item.source,
            }
            for item in refs[:20]
        ],
        "validation": {
            "total_refs": getattr(validation, "total_refs", len(refs)),
            "total_citations": getattr(validation, "total_citations", 0),
            "matched": getattr(validation, "matched", 0),
            "unmatched_citations": getattr(validation, "unmatched_citations", []),
            "unused_refs": getattr(validation, "unused_refs", []),
            "doi_missing_count": len(getattr(validation, "doi_missing", [])),
            "doi_missing": getattr(validation, "doi_missing", []),
            "score": getattr(validation, "score", 0.0),
            "quality_checks": quality_checks,
            "suspicious_references": [
                item for item in quality_checks
                if item.get("exists") is False or item.get("doi_verified") is False
            ],
        },
    }


def _infer_title(path: Path, text: str) -> str:
    for line in text.splitlines():
        candidate = line.strip()
        if candidate and len(candidate) <= 80 and not _is_heading(candidate):
            return candidate
    return path.stem


def _detect_review_track(text: str, *, template_name: str = "", paper_path: Optional[Path] = None) -> Tuple[str, List[str]]:
    joined = " ".join([template_name or "", str(paper_path or ""), text[:5000]])
    score = {"undergraduate": 0, "graduate": 0}
    reasons: List[str] = []

    undergraduate_markers = ["本科", "毕业论文", "本科生"]
    graduate_markers = ["研究生", "硕士", "博士", "学位论文", "题名页", "版权页"]

    for marker in undergraduate_markers:
        if marker in joined:
            score["undergraduate"] += 2
            reasons.append(f"命中本科标记: {marker}")
    for marker in graduate_markers:
        if marker in joined:
            score["graduate"] += 2
            reasons.append(f"命中研究生标记: {marker}")

    if score["graduate"] > score["undergraduate"]:
        return "graduate", reasons
    if score["undergraduate"] > score["graduate"]:
        return "undergraduate", reasons
    return "graduate", reasons or ["未命中明确标记，默认按研究生规则高标准审查"]


def _build_paper_bundle(
    path: Path,
    *,
    template_name: Optional[str] = None,
    review_track: Optional[str] = None,
) -> Tuple[Dict[str, Any], str, List[str]]:
    text = _extract_text(path)
    if review_track in {"undergraduate", "graduate"}:
        track = review_track
        reasons = [f"前端/接口显式指定审查轨道: {review_track}"]
    else:
        track, reasons = _detect_review_track(text, template_name=template_name or "", paper_path=path)
    sections = _extract_sections(text)
    reference_payload = _extract_references_preview(path)
    figure_count = len(re.findall(r"(图\s*\d+|Figure\s+\d+)", text, re.IGNORECASE))
    table_count = len(re.findall(r"(表\s*\d+|Table\s+\d+)", text, re.IGNORECASE))
    title = _infer_title(path, text)

    bundle = {
        "title": title,
        "source_path": str(path),
        "file_type": detect_file_type(path),
        "language": _detect_language(text),
        "detected_review_track": track,
        "routing_reasons": reasons,
        "abstract": next((item.get("text", "")[:1000] for item in sections if "摘要" in item.get("heading", "")), ""),
        "sections": sections,
        "figures": [{"id": f"fig-{idx + 1}"} for idx in range(figure_count)],
        "tables": [{"id": f"tbl-{idx + 1}"} for idx in range(table_count)],
        "references": reference_payload.get("refs", []),
        "reference_stats": reference_payload.get("validation", {}),
        "raw_text_excerpt": text[:18000],
        "text_length": len(text),
    }
    return bundle, track, reasons


def _project_paper_bundle_from_evidence_bundle(bundle: Dict[str, Any]) -> Dict[str, Any]:
    sections = [
        {
            "heading": item.get("heading", ""),
            "raw_heading": item.get("heading", ""),
            "heading_level": item.get("level", 0),
            "text": item.get("text_excerpt", ""),
            "char_count": len(item.get("text_excerpt", "") or ""),
        }
        for item in bundle.get("document_structure", [])[:24]
    ]
    return {
        "title": bundle.get("title", ""),
        "source_path": bundle.get("source_path", ""),
        "file_type": bundle.get("file_type", ""),
        "language": bundle.get("language", ""),
        "detected_review_track": bundle.get("review_track", "graduate"),
        "routing_reasons": bundle.get("routing_reasons", []),
        "abstract": next((item.get("text_excerpt", "") for item in bundle.get("document_structure", []) if "摘要" in item.get("heading", "")), ""),
        "sections": sections,
        "figures": bundle.get("layout", {}).get("figures", []),
        "tables": bundle.get("layout", {}).get("tables", []),
        "references": bundle.get("bibliography", {}).get("references", []),
        "reference_stats": bundle.get("bibliography", {}).get("reference_stats", {}),
        "raw_text_excerpt": bundle.get("raw_text_excerpt", ""),
        "text_length": bundle.get("text_length", 0),
    }


def _build_rule_injection(track: str, reasons: List[str]) -> Dict[str, Any]:
    undergraduate, graduate = load_rule_profiles()
    active_profile = undergraduate if track == "undergraduate" else graduate
    inactive_profile = graduate if track == "undergraduate" else undergraduate

    return {
        "track": track,
        "template_bundle": active_profile,
        "requirement_bundle": active_profile,
        "active_rule_profile": active_profile,
        "inactive_reference_profile": inactive_profile,
        "routing_reasons": reasons,
        "format_policy": {
            "institution": "北京师范大学",
            "active_track": track,
            "primary_rule_source": active_profile.get("source_document", ""),
            "primary_template_name": active_profile.get("template_name", ""),
            "secondary_rule_source": inactive_profile.get("source_document", ""),
            "secondary_reference_only": True,
            "evidence_first": True,
            "strict_conflict_resolution": True,
        },
        "hallucination_policy": {
            "policy_name": "articlecheck-hallucination-policy-v1",
            "active_track": track,
            "rules": [
                "仅基于输入证据判断，不把潜在风险说成已证实造假",
                "优先引用格式审查与参考文献核验已有证据",
                "对于证据不足的论断，只能标注为待人工复核或证据不足",
            ],
        },
    }


def _default_review_focus(track: str) -> str:
    if track == "undergraduate":
        return "封面、摘要、关键词、目录、章节层级、图表标题、参考文献完整性"
    return "封面、题名页、版权页、摘要、目录、页码、章节层级、图表标题、参考文献、附录"


def _default_report_focus(track: str) -> str:
    return f"生成面向北京师范大学{ '本科' if track == 'undergraduate' else '研究生' }论文送审的正式审改报告，强调格式违规、引文风险与可执行修改建议。"


def _build_fallback_document_read_output(
    paper_bundle: Dict[str, Any],
    injected_rules: Dict[str, Any],
    *,
    review_focus: str,
    template_name: str,
) -> Dict[str, Any]:
    section_titles = [item.get("heading", "") for item in paper_bundle.get("sections", []) if item.get("heading")]
    reference_stats = paper_bundle.get("reference_stats") or {}
    figures = paper_bundle.get("figures") or []
    tables = paper_bundle.get("tables") or []
    references = paper_bundle.get("references") or []

    section_digest = [
        {
            "section_title": item.get("heading", ""),
            "section_role": "",
            "key_points": [item.get("text", "")[:180]] if item.get("text") else [],
        }
        for item in paper_bundle.get("sections", [])[:12]
    ]
    evidence_index = [
        {
            "evidence_id": f"section-{index}",
            "evidence_type": "section",
            "locator": item.get("heading", ""),
        }
        for index, item in enumerate(paper_bundle.get("sections", [])[:12], start=1)
    ]
    evidence_index.extend(
        {
            "evidence_id": figure.get("id") or f"figure-{index}",
            "evidence_type": "figure",
            "locator": figure.get("id") or f"figure-{index}",
        }
        for index, figure in enumerate(figures[:10], start=1)
    )

    risk_hints: List[str] = []
    if not section_titles:
        risk_hints.append("未能从论文文本中稳定识别章节标题，需要人工复核结构完整性。")
    if len(references) < 3:
        risk_hints.append("参考文献数量较少，后续应重点检查引文充分性。")
    if not figures and not tables:
        risk_hints.append("未发现图表对象，如论文为实验性研究需复核图表清单。")

    return {
        "paper_profile": {
            "paper_title": paper_bundle.get("title", ""),
            "language": paper_bundle.get("language", ""),
            "sections": section_titles,
            "figure_table_count": len(figures) + len(tables),
            "reference_count": len(references),
        },
        "template_rule_profile": injected_rules["template_bundle"],
        "requirement_rule_profile": injected_rules["requirement_bundle"],
        "review_context": {
            "paper_title": paper_bundle.get("title", ""),
            "discipline": "",
            "language": paper_bundle.get("language", ""),
            "section_titles": section_titles,
            "figure_table_count": len(figures) + len(tables),
            "reference_count": len(references),
            "review_focus": review_focus,
            "institution": "北京师范大学",
            "template_name": template_name,
            "review_goal": "送审前审改",
            "strictness_level": "high",
            "core_risks": risk_hints,
        },
        "section_digest": section_digest,
        "evidence_index": evidence_index,
        "risk_hints": risk_hints,
        "routing_hints": {
            "format_focus": section_titles[:5],
            "reference_focus": ["参考文献完整性", "引用与参考文献映射一致性"],
            "hallucination_focus": ["摘要与结论一致性", "结论论断与引文支撑关系"],
        },
        "normalization_meta": {
            "has_layout_metrics": False,
            "has_reference_list": bool(references),
            "has_figures": bool(figures),
            "has_tables": bool(tables),
            "bundle_completeness": "partial" if paper_bundle.get("raw_text_excerpt") else "minimal",
        },
    }


def _loose_json_loads(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if value is None:
        return {}
    text = str(value).strip()
    if not text:
        return {}
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    if "{" in text and "}" in text:
        text = text[text.find("{"): text.rfind("}") + 1]
    elif "[" in text and "]" in text:
        text = text[text.find("["): text.rfind("]") + 1]
    repaired = text
    repaired = re.sub(r'\\(?!["\\/bfnrtu])', r"\\\\", repaired)
    repaired = re.sub(r'\\u(?![0-9a-fA-F]{4})', r"\\\\u", repaired)
    repaired = re.sub(r",\s*([}\]])", r"\1", repaired)
    repaired = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F]", " ", repaired)
    for candidate in (text, repaired):
        try:
            return json.loads(candidate)
        except Exception:
            continue
    return {"raw_text": str(value)}


def _json_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _to_mapping(value: Any) -> Dict[str, Any]:
    parsed = _loose_json_loads(value)
    return parsed if isinstance(parsed, dict) else {}


def _normalize_search_text(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()


def _coerce_int(value: Any) -> Optional[int]:
    if value in (None, "", [], {}):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    try:
        return int(str(value).strip())
    except Exception:
        match = re.search(r"(\d+)", str(value))
        return int(match.group(1)) if match else None


def _merge_location_fields(target: Dict[str, Any], source: Any) -> None:
    if not isinstance(source, dict):
        return
    for key in ("page", "line", "column", "section", "paragraph_index", "anchor_id", "block_id", "bbox", "locator", "text_excerpt"):
        if target.get(key) in (None, "", [], {}) and source.get(key) not in (None, "", [], {}):
            target[key] = source.get(key)


def _normalize_location_value(location: Any, *sources: Any) -> Dict[str, Any]:
    normalized: Dict[str, Any] = {}
    if isinstance(location, dict):
        normalized.update(location)
    elif isinstance(location, str):
        text = location.strip()
        if text:
            normalized["locator"] = text
            page = re.search(r"(?:第\s*(\d+)\s*页|page\s*[:#]?\s*(\d+))", text, re.IGNORECASE)
            line = re.search(r"(?:第\s*(\d+)\s*行|line\s*[:#]?\s*(\d+)|paragraph\s*[:#]?\s*(\d+))", text, re.IGNORECASE)
            section = re.search(r"(?:章节|section)\s*[:：#]?\s*([^,，;；|]+)", text, re.IGNORECASE)
            if page:
                normalized["page"] = next((int(group) for group in page.groups() if group), None)
            if line:
                normalized["line"] = next((int(group) for group in line.groups() if group), None)
            if section:
                normalized["section"] = section.group(1).strip()
    for source in sources:
        _merge_location_fields(normalized, source)
    normalized["page"] = _coerce_int(normalized.get("page"))
    normalized["line"] = _coerce_int(normalized.get("line"))
    normalized["column"] = _coerce_int(normalized.get("column"))
    normalized["paragraph_index"] = _coerce_int(normalized.get("paragraph_index"))
    if not normalized.get("line") and normalized.get("paragraph_index"):
        normalized["line"] = normalized["paragraph_index"]
    return {key: value for key, value in normalized.items() if value not in (None, "", [], {})}


def _build_anchor_lookup(evidence_bundle: Dict[str, Any], evidence_index: List[Dict[str, Any]]) -> Dict[str, Any]:
    anchors = [item for item in (evidence_bundle.get("source_snippet_anchors") or []) if isinstance(item, dict)]
    by_anchor_id = {str(item.get("anchor_id")): item for item in anchors if item.get("anchor_id")}
    by_block_id = {str(item.get("block_id")): item for item in anchors if item.get("block_id")}
    by_paragraph = {int(item.get("paragraph_index")): item for item in anchors if isinstance(item.get("paragraph_index"), int)}
    for item in evidence_index or []:
        if not isinstance(item, dict):
            continue
        anchor_id = str(item.get("evidence_id") or "").strip()
        if not anchor_id:
            continue
        anchor = by_anchor_id.setdefault(anchor_id, {})
        if item.get("block_id") and not anchor.get("block_id"):
            anchor["block_id"] = item.get("block_id")
        if item.get("page") not in (None, "") and not anchor.get("page"):
            anchor["page"] = item.get("page")
        if item.get("locator") and not anchor.get("text_excerpt"):
            anchor["text_excerpt"] = item.get("locator")
        if anchor.get("block_id"):
            by_block_id.setdefault(str(anchor["block_id"]), anchor)
    return {
        "anchors": anchors,
        "by_anchor_id": by_anchor_id,
        "by_block_id": by_block_id,
        "by_paragraph": by_paragraph,
    }


def _resolve_anchor_for_evidence(
    record: Dict[str, Any],
    anchor_lookup: Dict[str, Any],
) -> Dict[str, Any]:
    raw_payload = record.get("raw_payload") if isinstance(record.get("raw_payload"), dict) else {}
    evidence_span = {}
    _merge_location_fields(evidence_span, raw_payload.get("evidence_span"))
    _merge_location_fields(evidence_span, record.get("evidence_span"))
    location = _normalize_location_value(record.get("location"), evidence_span, raw_payload)

    candidates: List[Dict[str, Any]] = []
    anchor_id = str(evidence_span.get("anchor_id") or record.get("evidence_id") or location.get("anchor_id") or "").strip()
    if anchor_id:
        anchor = (anchor_lookup.get("by_anchor_id") or {}).get(anchor_id)
        if isinstance(anchor, dict):
            candidates.append(anchor)
    block_id = str(evidence_span.get("block_id") or location.get("block_id") or "").strip()
    if block_id:
        anchor = (anchor_lookup.get("by_block_id") or {}).get(block_id)
        if isinstance(anchor, dict):
            candidates.append(anchor)
    paragraph_index = _coerce_int(location.get("paragraph_index") or location.get("line"))
    if paragraph_index:
        anchor = (anchor_lookup.get("by_paragraph") or {}).get(paragraph_index)
        if isinstance(anchor, dict):
            candidates.append(anchor)

    claim_norm = _normalize_search_text(record.get("claim") or raw_payload.get("quoted_text") or raw_payload.get("quote") or location.get("locator"))
    if claim_norm:
        for anchor in anchor_lookup.get("anchors") or []:
            excerpt_norm = _normalize_search_text(anchor.get("text_excerpt"))
            if excerpt_norm and (
                claim_norm[:18] in excerpt_norm
                or excerpt_norm[:18] in claim_norm
            ):
                candidates.append(anchor)
                break

    resolved = dict(evidence_span)
    if candidates:
        anchor = candidates[0]
        resolved.setdefault("anchor_id", anchor.get("anchor_id"))
        resolved.setdefault("block_id", anchor.get("block_id"))
        resolved.setdefault("page", anchor.get("page"))
        resolved.setdefault("paragraph_index", anchor.get("paragraph_index"))
        resolved.setdefault("bbox", anchor.get("bbox"))
        resolved.setdefault("locator", anchor.get("text_excerpt", "")[:120])
        resolved.setdefault("text_excerpt", anchor.get("text_excerpt"))

    if resolved.get("page") and not location.get("page"):
        location["page"] = resolved["page"]
    if resolved.get("paragraph_index") and not location.get("line"):
        location["line"] = resolved["paragraph_index"]
    if resolved.get("anchor_id") and not location.get("anchor_id"):
        location["anchor_id"] = resolved["anchor_id"]
    if resolved.get("block_id") and not location.get("block_id"):
        location["block_id"] = resolved["block_id"]
    if resolved.get("locator") and not location.get("locator"):
        location["locator"] = resolved["locator"]
    if resolved.get("text_excerpt") and not record.get("quoted_text"):
        record["quoted_text"] = resolved["text_excerpt"]

    return {
        "location": {key: value for key, value in location.items() if value not in (None, "", [], {})},
        "evidence_span": {key: value for key, value in resolved.items() if value not in (None, "", [], {})},
    }


def _extract_score(*candidates: Any) -> float:
    for candidate in candidates:
        if isinstance(candidate, (int, float)):
            return float(candidate)
        if isinstance(candidate, str):
            try:
                return float(candidate.strip())
            except Exception:
                continue
        if isinstance(candidate, dict):
            nested = (
                candidate.get("score")
                or (candidate.get("meta_delta") or {}).get("overall_score")
                or (candidate.get("reference_quality") if isinstance(candidate.get("reference_quality"), dict) else {})
            )
            if nested != candidate:
                value = _extract_score(nested)
                if value:
                    return value
    return 0.0


def _create_client(binding: DifyWorkflowBinding) -> DifyClient:
    return DifyClient(
        api_key=binding.api_key,
        base_url=binding.base_url,
        app_type=binding.mode,
        response_mode="blocking",
        user=config.dify.user,
        timeout=config.dify.timeout,
    )


def _run_workflow(binding_name: str, inputs: Dict[str, Any]) -> Dict[str, Any]:
    bindings = load_dify_workflow_bindings()
    binding = bindings[binding_name]
    with _create_client(binding) as client:
        return client.run_workflow(inputs=inputs)


def _extract_output(data: Dict[str, Any], preferred_keys: Iterable[str]) -> Any:
    workflow_data = data.get("data", data)
    outputs = workflow_data.get("outputs") or {}
    if isinstance(outputs, dict):
        for key in preferred_keys:
            if key in outputs:
                return outputs[key]
        if len(outputs) == 1:
            return next(iter(outputs.values()))
        for value in outputs.values():
            return value
    return workflow_data.get("answer") or workflow_data.get("text") or {}


def _ensure_issue_ids(items: List[Dict[str, Any]], prefix: str, category: str) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for index, item in enumerate(items or [], start=1):
        if not isinstance(item, dict):
            continue
        normalized.append(
            {
                "issue_id": item.get("issue_id") or f"{prefix}-{index}",
                "type": item.get("type") or category,
                "severity": item.get("severity") or "minor",
                "description": item.get("description") or item.get("summary") or "",
                "suggestion": item.get("suggestion") or "",
                "location": item.get("location") or {},
                "evidence_span": item.get("evidence_span") or {},
                **{k: v for k, v in item.items() if k not in {"issue_id", "type", "severity", "description", "suggestion", "location"}},
            }
        )
    return normalized


def _reference_items_to_issues(reference_review: Dict[str, Any]) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    existing_issues = reference_review.get("issues")
    if isinstance(existing_issues, list) and existing_issues:
        for index, item in enumerate(existing_issues, start=1):
            if not isinstance(item, dict):
                continue
            issues.append(
                {
                    "issue_id": item.get("issue_id") or f"reference-{index}",
                    "type": item.get("type") or "reference_risk",
                    "severity": item.get("severity") or "major",
                    "description": item.get("description") or item.get("title") or "参考文献风险",
                    "suggestion": item.get("suggestion") or "复核该参考文献的来源、作者、年份与 DOI 信息",
                    "location": item.get("location") or {"section": "references"},
                    "confidence": item.get("confidence", 0.95),
                    "evidence_span": item.get("evidence_span") or {},
                }
            )
        return issues
    for index, item in enumerate(reference_review.get("suspicious_references", []) or [], start=1):
        if isinstance(item, str):
            issues.append(
                {
                    "issue_id": f"reference-{index}",
                    "type": "reference_risk",
                    "severity": "major",
                    "description": item,
                    "suggestion": "复核该参考文献的来源、作者、年份与 DOI 信息",
                    "location": {"section": "references"},
                }
            )
            continue
        if isinstance(item, dict):
            issues.append(
                {
                    "issue_id": item.get("issue_id") or f"reference-{index}",
                    "type": item.get("type") or "reference_risk",
                    "severity": item.get("severity") or "major",
                    "description": item.get("description") or item.get("title") or "参考文献风险",
                    "suggestion": item.get("suggestion") or "复核该参考文献的来源、作者、年份与 DOI 信息",
                    "location": item.get("location") or {"section": "references"},
                    "evidence_span": item.get("evidence_span") or {},
                }
            )
    for index, item in enumerate(reference_review.get("pending_manual_checks", []) or [], start=len(issues) + 1):
        desc = item if isinstance(item, str) else item.get("description") or item.get("title") or "参考文献待人工复核"
        issues.append(
            {
                "issue_id": f"reference-pending-{index}",
                "type": "manual_check",
                "severity": "minor",
                "description": desc,
                "suggestion": "人工复核该引文与参考文献是否一致",
                "location": {"section": "references"},
                "evidence_span": item.get("evidence_span") if isinstance(item, dict) else {},
            }
        )
    return issues


def _normalize_findings(
    report_delta: Dict[str, Any],
    format_review: Dict[str, Any],
    reference_review: Dict[str, Any],
    hallucination_review: Dict[str, Any],
) -> List[Dict[str, Any]]:
    findings = report_delta.get("findings")
    if isinstance(findings, list) and findings:
        normalized: List[Dict[str, Any]] = []
        for index, item in enumerate(findings, start=1):
            if not isinstance(item, dict):
                continue
            normalized.append(
                {
                    "category": item.get("category") or item.get("stage") or "format",
                    "severity": item.get("severity") or "minor",
                    "type": item.get("type") or f"finding_{index}",
                    "description": item.get("description") or item.get("title") or "",
                    "suggestion": item.get("suggestion") or "",
                    "location": item.get("location") or {},
                    "evidence_span": item.get("evidence_span") or {},
                }
            )
        if normalized:
            return normalized

    merged: List[Dict[str, Any]] = []
    for item in _ensure_issue_ids(format_review.get("issues", []), "format", "format"):
        merged.append(
            {
                "category": "format",
                "severity": item.get("severity", "minor"),
                "type": item.get("type", "format"),
                "description": item.get("description", ""),
                "suggestion": item.get("suggestion", ""),
                "location": item.get("location") or {},
                "evidence_span": item.get("evidence_span") or {},
            }
        )
    for item in _reference_items_to_issues(reference_review):
        merged.append(
            {
                "category": "reference",
                "severity": item.get("severity", "minor"),
                "type": item.get("type", "reference"),
                "description": item.get("description", ""),
                "suggestion": item.get("suggestion", ""),
                "location": item.get("location") or {},
                "evidence_span": item.get("evidence_span") or {},
            }
        )
    for item in _ensure_issue_ids(hallucination_review.get("issues", []), "hallucination", "hallucination"):
        merged.append(
            {
                "category": "content",
                "severity": item.get("severity", "minor"),
                "type": item.get("type", "hallucination"),
                "description": item.get("description", ""),
                "suggestion": item.get("suggestion", ""),
                "location": item.get("location") or {},
                "evidence_span": item.get("evidence_span") or {},
            }
        )
    return merged


def _normalize_evidence_records(
    report_delta: Dict[str, Any],
    format_review: Dict[str, Any],
    reference_review: Dict[str, Any],
    hallucination_review: Dict[str, Any],
    evidence_bundle: Dict[str, Any],
    evidence_index: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    anchor_lookup = _build_anchor_lookup(evidence_bundle, evidence_index)
    evidence_records = report_delta.get("evidence_records")
    if isinstance(evidence_records, list) and evidence_records:
        normalized: List[Dict[str, Any]] = []
        for index, item in enumerate(evidence_records, start=1):
            if not isinstance(item, dict):
                continue
            record = {
                "evidence_id": item.get("evidence_id") or f"report-ev-{index}",
                "paper_id": item.get("paper_id") or "",
                "stage": item.get("stage") or item.get("category") or "report",
                "source_type": item.get("source_type") or item.get("stage") or "report",
                "claim": item.get("claim") or item.get("description") or item.get("summary") or "",
                "confidence": item.get("confidence", 0.8),
                "severity": item.get("severity", "info"),
                "location": item.get("location") or {},
                "evidence_span": item.get("evidence_span") or {},
                "quoted_text": item.get("quoted_text") or item.get("quote") or "",
                "suggestion": item.get("suggestion") or "",
                "raw_payload": item,
            }
            resolved = _resolve_anchor_for_evidence(record, anchor_lookup)
            record["location"] = resolved["location"]
            record["evidence_span"] = resolved["evidence_span"]
            if record.get("evidence_span", {}).get("anchor_id"):
                record["evidence_id"] = record["evidence_span"]["anchor_id"]
            normalized.append(record)
        if normalized:
            return normalized

    normalized = []
    for stage, payload, field in (
        ("format", format_review, "issues"),
        ("reference", {"issues": _reference_items_to_issues(reference_review)}, "issues"),
        ("content", hallucination_review, "issues"),
    ):
        for index, item in enumerate(payload.get(field, []) or [], start=len(normalized) + 1):
            if not isinstance(item, dict):
                continue
            record = {
                "evidence_id": item.get("issue_id") or f"{stage}-ev-{index}",
                "paper_id": "",
                "stage": stage,
                "source_type": stage,
                "claim": item.get("description") or item.get("summary") or "",
                "confidence": item.get("confidence", 0.8),
                "severity": item.get("severity", "info"),
                "location": item.get("location") or {},
                "evidence_span": item.get("evidence_span") or {},
                "quoted_text": item.get("quoted_text") or item.get("quote") or "",
                "suggestion": item.get("suggestion") or "",
                "raw_payload": item,
            }
            resolved = _resolve_anchor_for_evidence(record, anchor_lookup)
            record["location"] = resolved["location"]
            record["evidence_span"] = resolved["evidence_span"]
            if record.get("evidence_span", {}).get("anchor_id"):
                record["evidence_id"] = record["evidence_span"]["anchor_id"]
            normalized.append(record)
    return normalized


def _link_issues_with_evidence(
    issues: List[Dict[str, Any]],
    evidence_records: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    linked: List[Dict[str, Any]] = []
    for item in issues or []:
        if not isinstance(item, dict):
            continue
        issue = dict(item)
        if issue.get("evidence_id"):
            linked.append(issue)
            continue
        anchor_id = str(((issue.get("evidence_span") or {}).get("anchor_id")) or "").strip()
        if anchor_id:
            issue["evidence_id"] = anchor_id
            linked.append(issue)
            continue
        description = str(issue.get("description") or issue.get("summary") or "").strip()
        location = issue.get("location") or {}
        matched_id = None
        for record in evidence_records:
            if not isinstance(record, dict):
                continue
            if description and description == str(record.get("claim") or "").strip():
                matched_id = record.get("evidence_id")
                break
            if location and location == (record.get("location") or {}):
                matched_id = record.get("evidence_id")
                break
        if matched_id:
            issue["evidence_id"] = matched_id
        linked.append(issue)
    return linked


def _priority_blocks(report_delta: Dict[str, Any]) -> List[Dict[str, Any]]:
    actions = report_delta.get("priority_actions") or []
    if not actions:
        return []
    blocks = []
    for index, action in enumerate(actions, start=1):
        if isinstance(action, str):
            blocks.append(
                {
                    "priority": "major" if index == 1 else "minor",
                    "title": f"优先处理事项 {index}",
                    "actions": [action],
                }
            )
        elif isinstance(action, dict):
            action_items = action.get("actions") or action.get("items") or []
            if isinstance(action_items, str):
                action_items = [action_items]
            blocks.append(
                {
                    "priority": action.get("priority") or ("major" if index == 1 else "minor"),
                    "title": action.get("title") or f"优先处理事项 {index}",
                    "actions": action_items or [action.get("description") or ""],
                }
            )
    return [item for item in blocks if item.get("actions")]


def _build_workflow_trace(duration: float) -> Tuple[Dict[str, Dict[str, Any]], List[Dict[str, Any]]]:
    stages = [
        ("parse", "parse_layer"),
        ("audit", "deterministic_audit"),
        ("verify", "verification"),
        ("document_read", "document_read"),
        ("format", "format_check"),
        ("content", "hallucination_review"),
        ("report", "report"),
    ]
    graph: Dict[str, Dict[str, Any]] = {}
    events: List[Dict[str, Any]] = []
    base_ts = int(time.time())
    for offset, (node_id, stage) in enumerate(stages):
        if stage in {"parse_layer", "deterministic_audit", "verification"}:
            worker_binding = f"local::{stage}"
        else:
            worker_binding = f"dify::{stage}"
        graph[node_id] = {
            "stage": stage,
            "worker_binding": worker_binding,
            "dependencies": [] if offset == 0 else [stages[offset - 1][0]],
            "critical": True,
            "status": "completed",
        }
        events.append({"event_type": "completed", "stage": stage, "timestamp": base_ts + offset})
    graph["report"]["latency_seconds"] = round(duration, 3)
    return graph, events


def run_dify_review_chain(
    paper_path: str | Path,
    *,
    template_name: Optional[str] = None,
    detailed_mode: bool = False,
    review_track: Optional[str] = None,
    review_focus: Optional[str] = None,
    report_focus: Optional[str] = None,
) -> Dict[str, Any]:
    if not dify_workflows_available():
        raise RuntimeError("Dify workflow 配置不完整，无法执行联调审查。")

    path = Path(paper_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"论文文件不存在: {path}")

    start_time = time.time()
    evidence_bundle = build_evidence_bundle(
        path,
        template_name=template_name,
        review_track=review_track,
    )
    track = evidence_bundle.get("review_track", "graduate")
    reasons = evidence_bundle.get("routing_reasons", [])
    paper_bundle = _project_paper_bundle_from_evidence_bundle(evidence_bundle)
    deterministic_audit = run_deterministic_audit(evidence_bundle, review_track=track)
    verification_layer = run_layered_verification(evidence_bundle, detailed_mode=detailed_mode)

    injected_rules = _build_rule_injection(track, reasons)
    detailed_flag = "True" if detailed_mode else "False"
    resolved_template_name = template_name or injected_rules["active_rule_profile"].get("template_name") or path.stem
    resolved_review_focus = review_focus or _default_review_focus(track)
    resolved_report_focus = report_focus or _default_report_focus(track)

    section_digest = build_section_digest(evidence_bundle)
    evidence_index = build_evidence_index(evidence_bundle)
    risk_hints = [
        item.get("description")
        for item in (deterministic_audit.get("issues") or [])[:6]
        if item.get("description")
    ]
    risk_hints.extend(
        item.get("description")
        for item in (verification_layer.get("issues") or [])[:6]
        if item.get("description")
    )

    doc_inputs = {
        "paper_bundle_json": _json_text(paper_bundle),
        "template_bundle_json": _json_text(injected_rules["template_bundle"]),
        "requirement_bundle_json": _json_text(injected_rules["requirement_bundle"]),
        "detailed_mode": detailed_flag,
        "review_focus": resolved_review_focus,
        "institution": "北京师范大学",
        "template_name": resolved_template_name,
        "review_goal": "送审前审改",
        "strictness_level": "high",
        "review_track": track,
    }
    doc_raw = _run_workflow(DOCUMENT_READ_DSL, doc_inputs)
    doc_output = _loose_json_loads(
        _extract_output(
            doc_raw,
            ["document_read_detailed_result" if detailed_mode else "document_read_standard_result"],
        )
    )
    if not isinstance(doc_output, dict) or "paper_profile" not in doc_output:
        logger.warning("document_read 输出无法稳定解析，回退本地归一化结果。")
        doc_output = _build_fallback_document_read_output(
            paper_bundle,
            injected_rules,
            review_focus=resolved_review_focus,
            template_name=resolved_template_name,
        )

    paper_profile = {
        **(doc_output.get("paper_profile") or {}),
        "evidence_bundle_version": evidence_bundle.get("bundle_version"),
        "paper_title": paper_bundle.get("title"),
        "reference_count": len(evidence_bundle.get("bibliography", {}).get("references", []) or []),
    }
    template_rule_profile = injected_rules["active_rule_profile"]
    requirement_rule_profile = injected_rules["active_rule_profile"]
    review_context = {
        **(doc_output.get("review_context") or {}),
        "institution": "北京师范大学",
        "template_name": injected_rules["active_rule_profile"].get("template_name", ""),
        "review_goal": "送审前审改",
        "strictness_level": "high",
        "review_track": track,
        "rule_profile_type": injected_rules["active_rule_profile"].get("profile_type", ""),
        "layered_architecture": "parse -> deterministic_audit -> verification -> dify_orchestration",
        "evidence_bundle_summary": {
            "structure_nodes": len(evidence_bundle.get("document_structure", []) or []),
            "anchors": len(evidence_bundle.get("source_snippet_anchors", []) or []),
            "captions": len(evidence_bundle.get("layout", {}).get("captions", []) or []),
            "references": len(evidence_bundle.get("bibliography", {}).get("references", []) or []),
            "citations": len(evidence_bundle.get("bibliography", {}).get("citations", []) or []),
        },
        "deterministic_audit_summary": {
            "issue_count": deterministic_audit.get("issue_count", 0),
            "strong_format_issue_count": deterministic_audit.get("strong_format_issue_count", 0),
            "score": deterministic_audit.get("score"),
        },
        "verification_summary": {
            "issue_count": len(verification_layer.get("issues") or []),
            "fast_checked": verification_layer.get("fast_path", {}).get("checked_references", 0),
            "identity_cache_hits": verification_layer.get("fast_path", {}).get("cache_hits", 0),
            "offline_hits": verification_layer.get("fast_path", {}).get("offline_hits", 0),
            "identifier_hits": verification_layer.get("fast_path", {}).get("identifier_hits", 0),
            "online_hits": verification_layer.get("fast_path", {}).get("online_hits", 0),
            "deep_enabled": verification_layer.get("deep_path", {}).get("enabled", False),
            "dify_handoff_candidates": len((verification_layer.get("claim_verify") or {}).get("dify_handoff_candidates") or []),
        },
    }

    format_raw = _run_workflow(
        FORMAT_REVIEW_DSL,
        {
            "paper_profile_json": _json_text(paper_profile),
            "template_rule_profile_json": _json_text(template_rule_profile),
            "requirement_rule_profile_json": _json_text(requirement_rule_profile),
            "review_context_json": _json_text(review_context),
            "format_policy_json": _json_text(injected_rules["format_policy"]),
            "section_digest_json": _json_text(section_digest),
            "evidence_index_json": _json_text(evidence_index),
            "risk_hints_json": _json_text(risk_hints),
            "detailed_mode": detailed_flag,
            "review_focus": resolved_review_focus,
        },
    )
    weak_format_review = _loose_json_loads(_extract_output(format_raw, ["format_review_json"]))
    weak_format_issues = _ensure_issue_ids((weak_format_review or {}).get("issues", []), "weak-format", "weak_format")
    format_review = {
        **(weak_format_review if isinstance(weak_format_review, dict) else {}),
        "deterministic_audit": deterministic_audit,
        "weak_format_issues": weak_format_issues,
        "issues": _ensure_issue_ids(
            (deterministic_audit.get("issues") or []) + weak_format_issues,
            "format",
            "format",
        ),
        "score": _extract_score(
            weak_format_review.get("score") if isinstance(weak_format_review, dict) else None,
            deterministic_audit.get("score"),
        ),
    }

    reference_verify = evidence_bundle.get("bibliography", {}).get("reference_stats") or {}
    reference_verify_payload = {
        "paper_title": paper_bundle.get("title"),
        "track": track,
        "routing_reasons": reasons,
        "references": paper_bundle.get("references") or [],
        "verification_layer": verification_layer,
        **reference_verify,
    }
    reference_review = {
        **verification_layer,
        "issues": _reference_items_to_issues(verification_layer),
    }

    hallucination_raw = _run_workflow(
        HALLUCINATION_REVIEW_DSL,
        {
            "paper_profile_json": _json_text(paper_profile),
            "review_context_json": _json_text(review_context),
            "reference_verify_json": _json_text(reference_verify_payload),
            "hallucination_policy_json": _json_text(injected_rules["hallucination_policy"]),
            "section_digest_json": _json_text(section_digest),
            "evidence_index_json": _json_text(evidence_index),
            "format_review_json": _json_text(format_review),
            "reference_review_json": _json_text(reference_review),
            "detailed_mode": detailed_flag,
            "review_focus": resolved_review_focus,
        },
    )
    hallucination_review = _to_mapping(_extract_output(hallucination_raw, ["hallucination_review_json"]))

    report_raw = _run_workflow(
        REPORT_GENERATION_DSL,
        {
            "paper_profile_json": _json_text(paper_profile),
            "format_review_json": _json_text(format_review),
            "hallucination_review_json": _json_text(hallucination_review),
            "review_context_json": _json_text(review_context),
            "reference_review_json": _json_text(reference_review),
            "section_digest_json": _json_text(section_digest),
            "evidence_index_json": _json_text(evidence_index),
            "detailed_mode": detailed_flag,
            "report_focus": resolved_report_focus,
        },
    )
    report_delta = _to_mapping(_extract_output(report_raw, ["report_generation_json"]))

    reference_section = {
        **reference_review,
        "details": reference_review,
        **reference_verify,
    }
    hallucination_review["issues"] = _ensure_issue_ids(
        hallucination_review.get("issues", []),
        "hallucination",
        "hallucination",
    )

    findings = _normalize_findings(report_delta, format_review, reference_review, hallucination_review)
    evidence_records = _normalize_evidence_records(
        report_delta,
        format_review,
        reference_review,
        hallucination_review,
        evidence_bundle,
        evidence_index,
    )
    for item in evidence_records:
        item["paper_id"] = path.stem
    format_review["issues"] = _link_issues_with_evidence(format_review.get("issues", []), evidence_records)
    reference_section["issues"] = _link_issues_with_evidence(reference_section.get("issues", []), evidence_records)
    hallucination_review["issues"] = _link_issues_with_evidence(hallucination_review.get("issues", []), evidence_records)
    findings = _link_issues_with_evidence(findings, evidence_records)

    overall_score = _extract_score(
        report_delta,
        format_review.get("score"),
        hallucination_review.get("score"),
        reference_review,
        deterministic_audit.get("score"),
        verification_layer.get("score"),
        reference_verify.get("score"),
    )

    graph, events = _build_workflow_trace(time.time() - start_time)
    priorities = _priority_blocks(report_delta)
    if not priorities:
        advice_report = generate_advice_report(findings, paper_bundle.get("title") or path.stem)
    else:
        advice_report = {
            "priorities": priorities,
            "report_path": None,
        }

    formal_report = generate_formal_review_report(
        paper_title=paper_bundle.get("title") or path.stem,
        findings=findings,
        evidence_records=evidence_records,
        workflow={"checkpoint": {"graph": graph}, "events": events},
        summary={
            "overall_score": overall_score,
            "duration": round(time.time() - start_time, 3),
            "errors": [],
        },
    )

    payload = {
        "report_format": "article_check.ai_review.v1",
        "meta": {
            "paper_title": paper_bundle.get("title") or path.stem,
            "task_id": path.stem,
            "overall_score": overall_score,
            "duration": round(time.time() - start_time, 3),
            "source_paper_path": str(path),
            "source_file_name": path.name,
            "institution": "北京师范大学",
            "review_track": track,
            "routing_reasons": reasons,
            "architecture_version": "four_layer_v1",
            "dify_primary_workflow_count": len(PRIMARY_DIFY_DSLS),
        },
        "summary": {
            "finding_count": len(findings),
            "error_count": 0,
            "report_markdown_path": None,
            "report_json_path": None,
            "suggestion_report_path": advice_report.get("report_path"),
            "formal_report_markdown_path": formal_report.get("markdown_path"),
            "formal_report_html_path": formal_report.get("html_path"),
            "formal_report_json_path": formal_report.get("json_path"),
        },
        "sections": {
            "parse_layer": evidence_bundle,
            "deterministic_audit": deterministic_audit,
            "verification_layer": verification_layer,
            "document_read": doc_output,
            "format_check": format_review,
            "reference_check": reference_section,
            "content_review": {"hallucination_review": hallucination_review},
            "report_generation": report_delta,
            "workflow": {
                "graph": graph,
                "events": events,
            },
        },
        "findings": findings,
        "evidence_records": evidence_records,
        "advice_report": advice_report,
        "formal_report": {
            **formal_report,
            "source_paper_path": str(path),
        },
        "workflow": {
            "checkpoint_path": None,
            "events_path": None,
            "graph": graph,
            "events": events,
        },
        "errors": [],
        "question_router_hints": report_delta.get("question_router_hints") or [],
        "qa_seed_questions": report_delta.get("qa_seed_questions") or [],
    }
    return payload


def infer_question_scope(question: str) -> str:
    lower = question.lower()
    if any(token in question for token in ["证据", "出处", "定位", "原文"]) or "evidence" in lower:
        return "evidence"
    if any(token in question for token in ["修改", "怎么改", "修订", "建议"]) or "revision" in lower:
        return "revision"
    if any(token in question for token in ["参考文献", "doi", "引用"]) or "citation" in lower:
        return "reference"
    return "overview"


def run_dify_report_qa(report_payload: Dict[str, Any], question: str) -> str:
    if not dify_workflows_available():
        raise RuntimeError("Dify workflow 配置不完整，无法执行问答。")
    qa_raw = _run_workflow(
        REPORT_QA_DSL,
        {
            "report_payload_json": _json_text(report_payload),
            "user_question": question,
            "question_scope": infer_question_scope(question),
            "answer_style": "standard",
        },
    )
    answer = _extract_output(qa_raw, ["answer"])
    return str(answer).strip()
