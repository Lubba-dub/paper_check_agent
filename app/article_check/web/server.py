"""
FastAPI Web 服务器 — Article Check 图形化界面后端

提供 REST API + SSE 流式批处理 + 文件上传，供 React 前端调用。

启动:
    python -m article_check.web.server
    或
    article-check web
"""
from __future__ import annotations
import asyncio
import json
import logging
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from fastapi import FastAPI, File, Form, UploadFile, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel

from article_check.layers import build_evidence_bundle, run_deterministic_audit, run_layered_verification
from article_check.runtime import (
    answer_report_question,
    build_review_payload,
    build_runtime,
    create_paper_task,
    execute_review_task,
)
from article_check.utils.file_utils import detect_file_type
from article_check.dify_review import (
    dify_workflows_available,
    get_dify_registry_status,
    run_dify_report_qa,
    run_dify_review_chain,
)

logger = logging.getLogger(__name__)

# ─── Pydantic Models ───────────────────────────────────

class ReviewRequest(BaseModel):
    paper_path: str
    template: Optional[str] = None
    depth: str = "auto"
    with_deep_review: bool = False
    review_track: str = "auto"
    institution: Optional[str] = None
    review_focus: Optional[str] = None
    report_focus: Optional[str] = None


class BatchReviewRequest(BaseModel):
    paths: List[str]
    with_deep_review: bool = True
    review_track: str = "auto"
    template: Optional[str] = None


class ReportDialogueRequest(BaseModel):
    report_payload: Dict[str, Any]
    question: str


class ReportFileRequest(BaseModel):
    path: str


class EvidenceSnippetRequest(BaseModel):
    report_payload: Dict[str, Any]
    evidence_id: str
    context_radius: int = 3


class LayerRequest(BaseModel):
    paper_path: str
    template: Optional[str] = None
    review_track: str = "auto"
    detailed_mode: bool = False


# ─── FastAPI App ────────────────────────────────────────

app = FastAPI(
    title="Article Check API",
    description="学术论文审查与文献调研系统",
    version="0.3.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)
REPORT_DIR = Path("reports")
REPORT_DIR.mkdir(exist_ok=True)
SUPPORTED_UPLOAD_SUFFIXES = {".docx", ".pdf", ".tex", ".ltx"}


# ─── Helper ─────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    # 确保关键目录存在
    for d in [UPLOAD_DIR, REPORT_DIR, Path(".worktrees")]:
        d.mkdir(exist_ok=True)


def api_success(data: Any = None, message: str = "ok") -> dict:
    return {"status": "ok", "data": data, "message": message}


def api_error(message: str, code: int = 400) -> dict:
    return {"status": "error", "message": message, "code": code}


def _platform_auth_runtime_config() -> Dict[str, Any]:
    raw_enabled = os.getenv("ARTICLE_CHECK_PLATFORM_AUTH_ENABLED", "").strip().lower()
    raw_debug = os.getenv("ARTICLE_CHECK_PLATFORM_AUTH_DEBUG", "").strip().lower()

    config: Dict[str, Any] = {}
    if raw_enabled in {"true", "false"}:
        config["enabled"] = raw_enabled == "true"
    if raw_debug in {"true", "false"}:
        config["debug"] = raw_debug == "true"

    string_fields = {
        "mode": os.getenv("ARTICLE_CHECK_PLATFORM_AUTH_MODE", "").strip(),
        "apiBase": os.getenv("ARTICLE_CHECK_PLATFORM_AUTH_API_BASE", "").strip(),
        "host": os.getenv("ARTICLE_CHECK_PLATFORM_AUTH_HOST", "").strip(),
        "callbackPath": os.getenv("ARTICLE_CHECK_PLATFORM_AUTH_CALLBACK_PATH", "").strip(),
        "storagePrefix": os.getenv("ARTICLE_CHECK_PLATFORM_AUTH_STORAGE_PREFIX", "").strip(),
    }
    for key, value in string_fields.items():
        if value:
            config[key] = value
    return config


def _resolve_safe_path(raw_path: str) -> Path:
    path = Path(raw_path).expanduser().resolve()
    allowed_roots = [
        Path.cwd().resolve(),
        REPORT_DIR.resolve(),
        UPLOAD_DIR.resolve(),
    ]
    if not any(root == path or root in path.parents for root in allowed_roots):
        raise HTTPException(403, "不允许访问该文件")
    if not path.exists():
        raise HTTPException(404, f"文件不存在: {raw_path}")
    return path


def _ensure_supported_paper_path(path: Path) -> None:
    file_type = detect_file_type(path)
    if file_type not in {"docx", "pdf", "latex"}:
        raise HTTPException(400, "当前仅支持 docx、pdf、tex/ltx 文件")


def _find_evidence(report_payload: Dict[str, Any], evidence_id: str) -> Dict[str, Any]:
    for record in report_payload.get("evidence_records", []) or []:
        if record.get("evidence_id") == evidence_id:
            return record
    sections = report_payload.get("sections") or {}
    for section in sections.values():
        if not isinstance(section, dict):
            continue
        for key in ("issues", "findings", "items", "records"):
            items = section.get(key)
            if isinstance(items, list):
                for item in items:
                    anchor_id = ((item.get("evidence_span") or {}).get("anchor_id")) if isinstance(item, dict) else None
                    if isinstance(item, dict) and (item.get("evidence_id") == evidence_id or item.get("issue_id") == evidence_id or anchor_id == evidence_id):
                        return {
                            "evidence_id": evidence_id,
                            "claim": item.get("description") or item.get("summary") or item.get("claim") or "",
                            "severity": item.get("severity", "info"),
                            "location": item.get("location") or {},
                            "suggestion": item.get("suggestion") or "",
                            **item,
                        }
        for nested in section.values():
            if not isinstance(nested, dict):
                continue
            items = nested.get("issues")
            if isinstance(items, list):
                for item in items:
                    anchor_id = ((item.get("evidence_span") or {}).get("anchor_id")) if isinstance(item, dict) else None
                    if isinstance(item, dict) and (item.get("evidence_id") == evidence_id or item.get("issue_id") == evidence_id or anchor_id == evidence_id):
                        return {
                            "evidence_id": evidence_id,
                            "claim": item.get("description") or item.get("summary") or item.get("claim") or "",
                            "severity": item.get("severity", "info"),
                            "location": item.get("location") or {},
                            "suggestion": item.get("suggestion") or "",
                            **item,
                        }
    raise HTTPException(404, f"未找到 evidence: {evidence_id}")


def _snippet_from_lines(lines: List[str], center_line: int, radius: int) -> Dict[str, Any]:
    line_index = max(0, center_line - 1)
    start = max(0, line_index - radius)
    end = min(len(lines), line_index + radius + 1)
    excerpt = [
        {"line_number": idx + 1, "text": lines[idx].rstrip("\n")}
        for idx in range(start, end)
    ]
    return {
        "mode": "line",
        "start_line": start + 1,
        "end_line": end,
        "focus_line": line_index + 1,
        "excerpt": excerpt,
    }


def _snippet_from_section(lines: List[str], section_name: str, radius: int) -> Dict[str, Any]:
    section_lower = section_name.lower().strip()
    section_tokens = [section_lower.replace("_", " "), section_lower.replace("-", " ")]
    for idx, line in enumerate(lines):
        line_lower = line.lower().strip()
        if any(token and token in line_lower for token in section_tokens):
            snippet = _snippet_from_lines(lines, idx + 1, max(radius, 6))
            snippet["mode"] = "section"
            snippet["matched_section"] = section_name
            return snippet
        if line_lower.startswith("\\section") or line_lower.startswith("#"):
            normalized_line = (
                line_lower
                .replace("\\section{", "")
                .replace("\\subsection{", "")
                .replace("}", "")
                .replace("#", "")
                .strip()
            )
            if any(token and token in normalized_line for token in section_tokens):
                snippet = _snippet_from_lines(lines, idx + 1, max(radius, 6))
                snippet["mode"] = "section"
                snippet["matched_section"] = section_name
                return snippet
    return {
        "mode": "section",
        "start_line": None,
        "end_line": None,
        "focus_line": None,
        "matched_section": section_name,
        "excerpt": [{"line_number": None, "text": f"未在源文件中定位到章节: {section_name}"}],
    }


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
        if match:
            return int(match.group(1))
    return None


def _merge_location_fields(target: Dict[str, Any], source: Any) -> None:
    if not isinstance(source, dict):
        return
    for key in (
        "page",
        "line",
        "column",
        "section",
        "paragraph_index",
        "anchor_id",
        "block_id",
        "bbox",
        "locator",
        "text_excerpt",
    ):
        if target.get(key) in (None, "", [], {}) and source.get(key) not in (None, "", [], {}):
            target[key] = source.get(key)


def _extract_evidence_span(evidence: Dict[str, Any]) -> Dict[str, Any]:
    merged: Dict[str, Any] = {}
    raw_payload = evidence.get("raw_payload") if isinstance(evidence.get("raw_payload"), dict) else {}
    for source in (
        evidence.get("evidence_span"),
        raw_payload.get("evidence_span"),
    ):
        _merge_location_fields(merged, source)
    return merged


def _normalize_location(location: Any, evidence: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    normalized: Dict[str, Any] = {}

    if isinstance(location, dict):
        normalized.update(location)
    elif isinstance(location, str):
        text = location.strip()
        if text.startswith("{") and text.endswith("}"):
            try:
                maybe_json = json.loads(text)
                if isinstance(maybe_json, dict):
                    normalized.update(maybe_json)
            except Exception:
                pass
        if not normalized:
            normalized["locator"] = text
            page = re.search(r"(?:第\s*(\d+)\s*页|page\s*[:#]?\s*(\d+))", text, re.IGNORECASE)
            line = re.search(r"(?:第\s*(\d+)\s*行|line\s*[:#]?\s*(\d+)|paragraph\s*[:#]?\s*(\d+))", text, re.IGNORECASE)
            column = re.search(r"(?:第\s*(\d+)\s*列|column\s*[:#]?\s*(\d+))", text, re.IGNORECASE)
            section = re.search(r"(?:章节|section)\s*[:：#]?\s*([^,，;；|]+)", text, re.IGNORECASE)
            normalized["page"] = next((int(group) for group in page.groups() if group), None) if page else None
            normalized["line"] = next((int(group) for group in line.groups() if group), None) if line else None
            normalized["column"] = next((int(group) for group in column.groups() if group), None) if column else None
            if section:
                normalized["section"] = section.group(1).strip()
    elif isinstance(location, list):
        text = " / ".join(str(item).strip() for item in location if item not in (None, "", [], {}))
        if text:
            normalized["locator"] = text

    if evidence:
        _merge_location_fields(normalized, evidence)
        _merge_location_fields(normalized, evidence.get("location"))
        _merge_location_fields(normalized, _extract_evidence_span(evidence))
        raw_payload = evidence.get("raw_payload") if isinstance(evidence.get("raw_payload"), dict) else {}
        _merge_location_fields(normalized, raw_payload)
        if normalized.get("section") in (None, "") and evidence.get("section"):
            normalized["section"] = evidence.get("section")

    normalized["page"] = _coerce_int(normalized.get("page"))
    normalized["line"] = _coerce_int(normalized.get("line"))
    normalized["column"] = _coerce_int(normalized.get("column"))
    normalized["paragraph_index"] = _coerce_int(normalized.get("paragraph_index"))

    if not normalized.get("line") and normalized.get("paragraph_index"):
        normalized["line"] = normalized["paragraph_index"]
    if not normalized.get("locator") and normalized.get("text_excerpt"):
        normalized["locator"] = str(normalized["text_excerpt"])[:80]

    return {key: value for key, value in normalized.items() if value not in (None, "", [], {})}


def _resolve_anchor_location(
    location: Dict[str, Any],
    anchors: List[Dict[str, Any]],
    *,
    claim: str = "",
) -> Dict[str, Any]:
    if not anchors:
        return location

    resolved = dict(location)
    claim_norm = _normalize_search_text(claim)

    def _apply(anchor: Dict[str, Any]) -> Dict[str, Any]:
        resolved.setdefault("anchor_id", anchor.get("anchor_id"))
        resolved.setdefault("block_id", anchor.get("block_id"))
        resolved.setdefault("page", anchor.get("page"))
        resolved.setdefault("paragraph_index", anchor.get("paragraph_index"))
        if not resolved.get("line") and anchor.get("paragraph_index"):
            resolved["line"] = anchor.get("paragraph_index")
        resolved.setdefault("text_excerpt", anchor.get("text_excerpt"))
        resolved.setdefault("locator", anchor.get("text_excerpt", "")[:80])
        return resolved

    for anchor in anchors:
        if resolved.get("anchor_id") and resolved.get("anchor_id") == anchor.get("anchor_id"):
            return _apply(anchor)
    for anchor in anchors:
        if resolved.get("block_id") and resolved.get("block_id") == anchor.get("block_id"):
            return _apply(anchor)
    for anchor in anchors:
        if resolved.get("paragraph_index") and resolved.get("paragraph_index") == anchor.get("paragraph_index"):
            if not resolved.get("page") or resolved.get("page") == anchor.get("page"):
                return _apply(anchor)
    if claim_norm:
        for anchor in anchors:
            excerpt_norm = _normalize_search_text(anchor.get("text_excerpt"))
            if excerpt_norm and (
                claim_norm[:18] in excerpt_norm
                or excerpt_norm[:18] in claim_norm
            ):
                return _apply(anchor)
    return resolved


def _collect_snippet_hints(evidence: Dict[str, Any], location: Dict[str, Any]) -> List[str]:
    raw_payload = evidence.get("raw_payload") if isinstance(evidence.get("raw_payload"), dict) else {}
    evidence_span = _extract_evidence_span(evidence)
    candidates = [
        location.get("locator"),
        location.get("text_excerpt"),
        evidence_span.get("locator"),
        evidence_span.get("text_excerpt"),
        evidence.get("claim"),
        evidence.get("description"),
        raw_payload.get("claim"),
        raw_payload.get("description"),
        raw_payload.get("summary"),
        raw_payload.get("quote"),
        raw_payload.get("quoted_text"),
    ]
    hints: List[str] = []
    seen: set[str] = set()
    for item in candidates:
        text = str(item or "").strip()
        norm = _normalize_search_text(text)
        if len(norm) < 6 or norm in seen:
            continue
        seen.add(norm)
        hints.append(text)
    return hints


def _snippet_from_search(lines: List[str], hints: List[str], radius: int) -> Optional[Dict[str, Any]]:
    indexed = [(idx, _normalize_search_text(line), line) for idx, line in enumerate(lines)]
    for hint in sorted(hints, key=len, reverse=True):
        needle = _normalize_search_text(hint)
        if len(needle) < 6:
            continue
        token = needle[: min(len(needle), 24)]
        for idx, normalized_line, _ in indexed:
            if token and (token in normalized_line or normalized_line[: min(len(normalized_line), 24)] in needle):
                snippet = _snippet_from_lines(lines, idx + 1, max(radius, 4))
                snippet["mode"] = "search"
                snippet["matched_hint"] = hint[:120]
                return snippet
    return None


def _build_snippet_summary(location: Dict[str, Any]) -> str:
    parts: List[str] = []
    if location.get("page"):
        parts.append(f"第 {location['page']} 页")
    if location.get("line"):
        parts.append(f"行 {location['line']}")
    if location.get("column"):
        parts.append(f"列 {location['column']}")
    if location.get("section"):
        parts.append(f"章节 {location['section']}")
    if location.get("anchor_id"):
        parts.append(f"锚点 {location['anchor_id']}")
    if not parts and location.get("locator"):
        parts.append(str(location["locator"])[:120])
    return " · ".join(parts) or "未提供定位信息"


def _read_text_excerpt(
    source_path: Path,
    evidence: Dict[str, Any],
    radius: int,
    *,
    anchors: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    suffix = source_path.suffix.lower()
    location = _resolve_anchor_location(
        _normalize_location(evidence.get("location"), evidence),
        anchors or [],
        claim=str(evidence.get("claim") or ""),
    )
    hints = _collect_snippet_hints(evidence, location)

    if suffix in {".tex", ".ltx", ".txt", ".md"}:
        lines = source_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        if location.get("line"):
            snippet = _snippet_from_lines(lines, int(location["line"]), radius)
        elif location.get("section"):
            snippet = _snippet_from_section(lines, str(location["section"]), radius)
        else:
            snippet = _snippet_from_search(lines, hints, radius) or _snippet_from_lines(lines, 1, max(radius, 8))
        snippet["source_kind"] = "text"
        snippet["summary"] = _build_snippet_summary(location)
        if snippet.get("mode") == "search" and snippet.get("matched_hint") and snippet.get("summary") == "未提供定位信息":
            snippet["summary"] = f"文本检索命中: {snippet.get('matched_hint')}"
        return snippet

    if suffix == ".docx":
        try:
            from docx import Document
        except Exception as exc:  # pragma: no cover - import fallback
            return {
                "mode": "docx-unavailable",
                "source_kind": "docx",
                "summary": _build_snippet_summary(location),
                "excerpt": [{"line_number": None, "text": f"DOCX 片段预览不可用: {exc}"}],
            }

        doc = Document(str(source_path))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        lines = [text.strip() for text in paragraphs]
        if location.get("section"):
            snippet = _snippet_from_section(lines, str(location["section"]), max(radius, 4))
        elif location.get("line"):
            snippet = _snippet_from_lines(lines, int(location["line"]), radius)
        else:
            snippet = _snippet_from_search(lines, hints, radius) or _snippet_from_lines(lines, 1, max(radius, 5))
        snippet["source_kind"] = "docx"
        snippet["summary"] = _build_snippet_summary(location)
        if snippet.get("mode") == "search" and snippet.get("matched_hint") and snippet.get("summary") == "未提供定位信息":
            snippet["summary"] = f"文本检索命中: {snippet.get('matched_hint')}"
        return snippet

    if suffix == ".pdf":
        try:
            import fitz
        except Exception as exc:  # pragma: no cover - import fallback
            return {
                "mode": "pdf-unavailable",
                "source_kind": "pdf",
                "summary": _build_snippet_summary(location),
                "excerpt": [{"line_number": None, "text": f"PDF 片段预览不可用: {exc}"}],
            }

        page_number = max(1, int(location.get("page") or 1))
        with fitz.open(str(source_path)) as pdf:
            page = pdf.load_page(page_number - 1)
            text = page.get_text("text")
        lines = text.splitlines()
        if location.get("line"):
            snippet = _snippet_from_lines(lines, int(location.get("line") or 1), max(radius, 5))
        else:
            snippet = _snippet_from_search(lines, hints, radius) or _snippet_from_lines(lines, 1, max(radius, 5))
        snippet["source_kind"] = "pdf"
        snippet["page"] = page_number
        snippet["summary"] = _build_snippet_summary(location)
        if snippet.get("mode") == "search" and snippet.get("matched_hint") and snippet.get("summary") == "未提供定位信息":
            snippet["summary"] = f"文本检索命中: {snippet.get('matched_hint')}"
        return snippet

    return {
        "mode": "unsupported",
        "source_kind": suffix.lstrip(".") or "unknown",
        "summary": _build_snippet_summary(location),
        "excerpt": [{"line_number": None, "text": f"暂不支持该文件类型的原文片段预览: {suffix or 'unknown'}"}],
    }


def _annotate_review_payload(
    payload: Dict[str, Any],
    *,
    backend: str,
    warning: Optional[str] = None,
) -> Dict[str, Any]:
    meta = payload.setdefault("meta", {})
    meta["review_backend"] = backend
    if warning:
        warnings = meta.setdefault("warnings", [])
        if warning not in warnings:
            warnings.append(warning)
        errors = payload.setdefault("errors", [])
        if warning not in errors:
            errors.append(warning)
    return payload


async def _run_local_review_payload(
    path: Path,
    req: ReviewRequest,
    *,
    enable_deep_review: bool,
    warning: Optional[str] = None,
) -> Dict[str, Any]:
    runtime = build_runtime(
        mode="web",
        enable_deep_review=enable_deep_review,
        paper_paths=[str(path)],
        template_name=req.template,
        review_track=req.review_track,
    )
    task = create_paper_task(
        path,
        depth="deep" if enable_deep_review else req.depth,
        template_name=req.template,
        review_track=req.review_track,
    )
    result = await execute_review_task(runtime, task, enable_deep_review=enable_deep_review)
    payload = build_review_payload(result, plan_id=runtime.plan.plan_id)
    payload["sections"]["structure"] = (
        result.format_check.get("structure", {}) if isinstance(result.format_check, dict) else {}
    )
    return _annotate_review_payload(payload, backend="local_runtime", warning=warning)


# ─── System ─────────────────────────────────────────────

@app.get("/api/status")
async def get_status():
    """系统状态检查"""
    from article_check.config.settings import config
    from article_check.rules.registry import template_registry

    registry_status = get_dify_registry_status()
    return api_success({
        "version": "0.3.0",
        "ai_provider": config.ai.provider,
        "dify_enabled": bool(registry_status.get("available")),
        "dify_registry": registry_status,
        "review_backend": "dify_workflow_chain" if registry_status.get("available") else "local_runtime",
        "templates": template_registry.count,
        "templates_list": [t.name for t in template_registry.list_all()],
    })


@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    """上传论文文件"""
    file_id = str(uuid.uuid4())[:8]
    suffix = Path(file.filename).suffix if file.filename else ".docx"
    if suffix.lower() not in SUPPORTED_UPLOAD_SUFFIXES:
        raise HTTPException(400, "当前仅支持上传 docx、pdf、tex/ltx 文件")
    save_path = UPLOAD_DIR / f"{file_id}{suffix}"
    content = await file.read()
    with open(save_path, "wb") as f:
        f.write(content)
    return api_success({
        "file_id": file_id,
        "filename": file.filename,
        "path": str(save_path),
        "size": len(content),
        "type": suffix.lstrip("."),
    })


@app.post("/api/parse/evidence-bundle")
async def parse_evidence_bundle(req: LayerRequest):
    """生成统一 Evidence Bundle JSON。"""
    path = Path(req.paper_path)
    if not path.exists():
        raise HTTPException(404, f"文件不存在: {req.paper_path}")
    _ensure_supported_paper_path(path)
    bundle = await asyncio.to_thread(
        build_evidence_bundle,
        str(path),
        template_name=req.template,
        review_track=req.review_track,
    )
    return api_success(bundle)


@app.post("/api/audit/deterministic")
async def deterministic_audit(req: LayerRequest):
    """执行确定性格式审计层。"""
    path = Path(req.paper_path)
    if not path.exists():
        raise HTTPException(404, f"文件不存在: {req.paper_path}")
    _ensure_supported_paper_path(path)
    bundle = await asyncio.to_thread(
        build_evidence_bundle,
        str(path),
        template_name=req.template,
        review_track=req.review_track,
    )
    audit = await asyncio.to_thread(
        run_deterministic_audit,
        bundle,
        review_track=req.review_track,
    )
    return api_success(audit)


@app.post("/api/verify/layered")
async def layered_verify(req: LayerRequest):
    """执行分层文献核验层。"""
    path = Path(req.paper_path)
    if not path.exists():
        raise HTTPException(404, f"文件不存在: {req.paper_path}")
    _ensure_supported_paper_path(path)
    bundle = await asyncio.to_thread(
        build_evidence_bundle,
        str(path),
        template_name=req.template,
        review_track=req.review_track,
    )
    result = await asyncio.to_thread(
        run_layered_verification,
        bundle,
        detailed_mode=req.detailed_mode,
    )
    return api_success(result)


# ─── Review ─────────────────────────────────────────────

@app.post("/api/review")
async def review_paper(req: ReviewRequest):
    """审查单篇论文（统一 runtime 输出）"""
    path = Path(req.paper_path)
    if not path.exists():
        raise HTTPException(404, f"文件不存在: {req.paper_path}")
    _ensure_supported_paper_path(path)

    if dify_workflows_available():
        try:
            payload = await asyncio.to_thread(
                run_dify_review_chain,
                str(path),
                template_name=req.template,
                detailed_mode=bool(req.with_deep_review or req.depth == "deep"),
                review_track=req.review_track,
                review_focus=req.review_focus,
                report_focus=req.report_focus,
            )
            return api_success(_annotate_review_payload(payload, backend="dify_workflow_chain"))
        except Exception as exc:
            logger.exception("Dify 审查链执行失败")
            warning = f"Dify 审查链执行失败，已自动回退本地审查: {exc}"
            payload = await _run_local_review_payload(
                path,
                req,
                enable_deep_review=bool(req.with_deep_review or req.depth == "deep"),
                warning=warning,
            )
            return api_success(payload)

    payload = await _run_local_review_payload(
        path,
        req,
        enable_deep_review=bool(req.with_deep_review or req.depth == "deep"),
    )
    return api_success(payload)


@app.post("/api/review/deep")
async def deep_review(req: ReviewRequest):
    """深度审查（含 DeepSeek 内容分析）"""
    path = Path(req.paper_path)
    if not path.exists():
        raise HTTPException(404, "文件不存在")
    _ensure_supported_paper_path(path)

    if dify_workflows_available():
        try:
            payload = await asyncio.to_thread(
                run_dify_review_chain,
                str(path),
                template_name=req.template,
                detailed_mode=True,
                review_track=req.review_track,
                review_focus=req.review_focus,
                report_focus=req.report_focus,
            )
            return api_success(_annotate_review_payload(payload, backend="dify_workflow_chain"))
        except Exception as exc:
            logger.exception("Dify 深度审查链执行失败")
            warning = f"Dify 深度审查链执行失败，已自动回退本地审查: {exc}"
            payload = await _run_local_review_payload(
                path,
                req,
                enable_deep_review=bool(req.with_deep_review),
                warning=warning,
            )
            return api_success(payload)

    payload = await _run_local_review_payload(path, req, enable_deep_review=bool(req.with_deep_review))
    return api_success(payload)


@app.post("/api/report/dialogue")
async def report_dialogue(req: ReportDialogueRequest):
    """围绕结构化报告进行问答。"""
    if dify_workflows_available():
        try:
            answer = await asyncio.to_thread(run_dify_report_qa, req.report_payload, req.question)
            normalized = str(answer or "").strip()
            if normalized and normalized not in {"{}", "null", "None", '""'}:
                return api_success({"answer": normalized})
        except Exception:
            logger.exception("Dify 报告问答失败，将回退本地问答。")
    answer = answer_report_question(req.report_payload, req.question)
    return api_success({"answer": answer})


@app.get("/api/report/file")
async def get_report_file(path: str = Query(..., description="报告文件路径")):
    """安全返回报告导出文件。"""
    file_path = _resolve_safe_path(path)
    if file_path.suffix.lower() == ".html":
        return HTMLResponse(file_path.read_text(encoding="utf-8"))
    if file_path.suffix.lower() == ".json":
        return PlainTextResponse(file_path.read_text(encoding="utf-8"), media_type="application/json")
    if file_path.suffix.lower() == ".md":
        return PlainTextResponse(file_path.read_text(encoding="utf-8"), media_type="text/markdown; charset=utf-8")
    return FileResponse(str(file_path))


@app.post("/api/report/source-snippet")
async def get_report_source_snippet(req: EvidenceSnippetRequest):
    """根据 evidence 定位并返回原文片段。"""
    report_payload = req.report_payload or {}
    evidence = _find_evidence(report_payload, req.evidence_id)
    source_path_raw = (
        (report_payload.get("meta") or {}).get("source_paper_path")
        or (report_payload.get("formal_report") or {}).get("source_paper_path")
    )
    if not source_path_raw:
        raise HTTPException(400, "报告中缺少 source_paper_path，无法定位原文片段")

    source_path = _resolve_safe_path(source_path_raw)
    anchors = ((((report_payload.get("sections") or {}).get("parse_layer") or {}).get("source_snippet_anchors")) or [])
    normalized_location = _resolve_anchor_location(
        _normalize_location(evidence.get("location"), evidence),
        anchors,
        claim=str(evidence.get("claim") or ""),
    )
    snippet = _read_text_excerpt(source_path, evidence, req.context_radius, anchors=anchors)
    return api_success({
        "evidence_id": req.evidence_id,
        "source_path": str(source_path),
        "source_name": source_path.name,
        "location": normalized_location,
        "evidence_span": _extract_evidence_span(evidence),
        "claim": evidence.get("claim") or "",
        "snippet": snippet,
    })


# ─── Stream Review (SSE) ───────────────────────────────

@app.post("/api/review/batch-stream")
async def batch_review_stream(req: BatchReviewRequest):
    """流式批量审查 — SSE 推送"""
    async def event_stream():
        paths = req.paths
        if dify_workflows_available():
            total = len(paths)
            yield f"data: {json.dumps({'type': 'start', 'total': total})}\n\n"
            for raw_path in paths:
                try:
                    _ensure_supported_paper_path(Path(raw_path))
                    payload = await asyncio.to_thread(
                        run_dify_review_chain,
                        raw_path,
                        template_name=req.template,
                        detailed_mode=bool(req.with_deep_review),
                        review_track=req.review_track,
                    )
                    data = {
                        "type": "result",
                        "paper_title": (payload.get("meta") or {}).get("paper_title"),
                        "score": (payload.get("meta") or {}).get("overall_score"),
                        "duration": (payload.get("meta") or {}).get("duration"),
                        "errors": payload.get("errors", []),
                        "report_path": (payload.get("summary") or {}).get("formal_report_markdown_path"),
                        "review_payload": _annotate_review_payload(payload, backend="dify_workflow_chain"),
                    }
                    yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                except Exception as exc:
                    logger.exception("Dify 批量审查失败，回退本地 runtime: %s", raw_path)
                    path = Path(raw_path)
                    if not path.exists():
                        error_data = {
                            "type": "result",
                            "paper_title": path.stem,
                            "score": None,
                            "duration": None,
                            "errors": [f"文件不存在: {raw_path}"],
                            "report_path": None,
                            "review_payload": None,
                        }
                        yield f"data: {json.dumps(error_data, ensure_ascii=False)}\n\n"
                        continue
                    try:
                        _ensure_supported_paper_path(path)
                    except HTTPException as file_error:
                        error_data = {
                            "type": "result",
                            "paper_title": path.stem,
                            "score": None,
                            "duration": None,
                            "errors": [file_error.detail],
                            "report_path": None,
                            "review_payload": None,
                        }
                        yield f"data: {json.dumps(error_data, ensure_ascii=False)}\n\n"
                        continue

                    fallback_req = ReviewRequest(
                        paper_path=raw_path,
                        depth="deep" if req.with_deep_review else "auto",
                        with_deep_review=bool(req.with_deep_review),
                        review_track=req.review_track,
                        template=req.template,
                    )
                    payload = await _run_local_review_payload(
                        path,
                        fallback_req,
                        enable_deep_review=bool(req.with_deep_review),
                        warning=f"Dify 批量审查失败，已自动回退本地审查: {exc}",
                    )
                    data = {
                        "type": "result",
                        "paper_title": (payload.get("meta") or {}).get("paper_title"),
                        "score": (payload.get("meta") or {}).get("overall_score"),
                        "duration": (payload.get("meta") or {}).get("duration"),
                        "errors": payload.get("errors", []),
                        "report_path": (payload.get("summary") or {}).get("formal_report_markdown_path"),
                        "review_payload": payload,
                    }
                    yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type': 'complete'})}\n\n"
            return

        runtime = build_runtime(
            mode="batch",
            enable_deep_review=bool(req.with_deep_review),
            enable_streaming=True,
            paper_paths=paths,
            template_name=req.template,
            review_track=req.review_track,
        )
        tasks = [
            create_paper_task(
                p,
                depth="deep" if req.with_deep_review else "auto",
                template_name=req.template,
                review_track=req.review_track,
            )
            for p in paths
            if detect_file_type(Path(p)) in {"docx", "pdf", "latex"}
        ]

        total = len(tasks)
        yield f"data: {json.dumps({'type': 'start', 'total': total})}\n\n"

        for raw_path in paths:
            if detect_file_type(Path(raw_path)) in {"docx", "pdf", "latex"}:
                continue
            error_data = {
                "type": "result",
                "paper_title": Path(raw_path).stem,
                "score": None,
                "duration": None,
                "errors": ["当前仅支持 docx、pdf、tex/ltx 文件"],
                "report_path": None,
                "review_payload": None,
            }
            yield f"data: {json.dumps(error_data, ensure_ascii=False)}\n\n"

        async for result in runtime.orchestrator.review_batch_stream(tasks):
            data = {
                "type": "result",
                "paper_title": result.paper_title,
                "score": result.overall_score,
                "duration": result.duration,
                "errors": result.errors,
                "report_path": str(result.report_path) if result.report_path else None,
                "review_payload": build_review_payload(result, plan_id=runtime.plan.plan_id),
            }
            yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

        yield f"data: {json.dumps({'type': 'complete'})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ─── Health / Static Files / SPA ───────────────────────

@app.get("/api/health")
async def health():
    return {"status": "healthy", "service": "article-check-api"}


from fastapi.staticfiles import StaticFiles

FRONTEND_DIR = Path(__file__).parent / "frontend" / "dist"
ASSETS_DIR = FRONTEND_DIR / "assets"
if ASSETS_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(ASSETS_DIR)), name="frontend-assets")


@app.get("/", response_class=HTMLResponse)
async def frontend_index():
    if not FRONTEND_DIR.exists():
        raise HTTPException(404, "前端构建文件不存在")
    return HTMLResponse((FRONTEND_DIR / "index.html").read_text(encoding="utf-8"))


@app.get("/api/platform-auth-config")
async def platform_auth_config():
    return _platform_auth_runtime_config()


@app.get("/{full_path:path}")
async def frontend_spa_fallback(full_path: str):
    if full_path.startswith("api/"):
        raise HTTPException(404, "API 路径不存在")
    if not FRONTEND_DIR.exists():
        raise HTTPException(404, "前端构建文件不存在")

    requested = (FRONTEND_DIR / full_path).resolve()
    if requested.exists() and requested.is_file() and FRONTEND_DIR.resolve() in requested.parents:
        return FileResponse(str(requested))

    index_path = FRONTEND_DIR / "index.html"
    return HTMLResponse(index_path.read_text(encoding="utf-8"))

# ─── CLI Entry ──────────────────────────────────────────


def run_server(host: str = "127.0.0.1", port: int = 8765):
    """启动 Web 服务器"""
    import uvicorn
    print(f"🌐 Article Check Web UI: http://{host}:{port}")
    print(f"📚 API 文档: http://{host}:{port}/docs")
    print(f"🔍 按 Ctrl+C 停止")
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run_server()
