from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from article_check.dify_review import (
    get_dify_registry_status,
    load_dify_workflow_bindings,
    run_dify_component_classification,
)
from article_check.web.server import app


ROOT = Path(r"e:\cocoon\projects\article_check")
TEX_PATH = ROOT / "uploads" / "65629e58.tex"
DOCX_PATH = ROOT / "uploads" / "6d3a5770.docx"


def _post(client: TestClient, path: str, payload: dict) -> tuple[int, dict]:
    response = client.post(path, json=payload)
    return response.status_code, response.json()


def _safe_post(client: TestClient, path: str, payload: dict) -> tuple[int | None, dict]:
    try:
        return _post(client, path, payload)
    except Exception as exc:  # pragma: no cover - regression helper
        return None, {"error": str(exc), "data": {}}


def main() -> None:
    summary: dict = {}

    bindings = load_dify_workflow_bindings()
    component_binding = bindings.get("articlecheck_component_classification_workflow.yml")
    summary["component_binding_present"] = bool(component_binding)
    summary["component_binding_base_url"] = getattr(component_binding, "base_url", "")
    summary["component_binding_api_prefix"] = (getattr(component_binding, "api_key", "") or "")[:12]
    summary["registry_status"] = get_dify_registry_status()

    try:
        component_tex = run_dify_component_classification(str(TEX_PATH), review_track="graduate")
        summary["component_tex"] = {
            "component_count": len(((component_tex.get("component_classification") or {}).get("component_map") or [])),
            "manual_check_count": len(((component_tex.get("component_classification") or {}).get("manual_check_flags") or [])),
            "has_font_profile": bool(component_tex.get("font_profile")),
        }
    except Exception as exc:  # pragma: no cover - regression helper
        summary["component_tex"] = {
            "error": str(exc),
        }

    client = TestClient(app)

    status_code, parse_tex = _safe_post(
        client,
        "/api/parse/evidence-bundle",
        {
            "paper_path": str(TEX_PATH),
            "review_track": "graduate",
        },
    )
    summary["parse_tex"] = {
        "status": status_code,
        "has_anchors": len((((parse_tex.get("data") or {}).get("source_snippet_anchors")) or [])),
        "file_type": ((parse_tex.get("data") or {}).get("file_type")),
    }

    status_code, audit_tex = _safe_post(
        client,
        "/api/audit/deterministic",
        {
            "paper_path": str(TEX_PATH),
            "review_track": "graduate",
        },
    )
    summary["audit_tex"] = {
        "status": status_code,
        "issue_count": ((audit_tex.get("data") or {}).get("issue_count")),
        "strong_issue_count": ((audit_tex.get("data") or {}).get("strong_format_issue_count")),
    }

    status_code, verify_tex = _safe_post(
        client,
        "/api/verify/layered",
        {
            "paper_path": str(TEX_PATH),
            "review_track": "graduate",
            "detailed_mode": False,
        },
    )
    summary["verify_tex"] = {
        "status": status_code,
        "issue_count": len((((verify_tex.get("data") or {}).get("issues")) or [])),
    }

    status_code, classify_tex = _safe_post(
        client,
        "/api/classify/components",
        {
            "paper_path": str(TEX_PATH),
            "review_track": "graduate",
        },
    )
    classify_tex_data = classify_tex.get("data") or {}
    summary["classify_tex"] = {
        "status": status_code,
        "component_count": len((((classify_tex_data.get("component_classification") or {}).get("component_map")) or [])),
        "manual_check_count": len((((classify_tex_data.get("component_classification") or {}).get("manual_check_flags")) or [])),
    }

    status_code, review_tex = _safe_post(
        client,
        "/api/review",
        {
            "paper_path": str(TEX_PATH),
            "review_track": "graduate",
            "with_deep_review": False,
            "depth": "auto",
        },
    )
    review_tex_data = review_tex.get("data") or {}
    evidence_records = review_tex_data.get("evidence_records") or []
    findings = review_tex_data.get("findings") or []
    summary["review_tex"] = {
        "status": status_code,
        "backend": ((review_tex_data.get("meta") or {}).get("review_backend")),
        "architecture_version": ((review_tex_data.get("meta") or {}).get("architecture_version")),
        "finding_count": len(findings),
        "evidence_count": len(evidence_records),
        "severity_order": [item.get("severity") for item in findings[:6]],
        "location_samples": [item.get("location") for item in evidence_records[:3]],
        "has_component_section": "component_classification" in (review_tex_data.get("sections") or {}),
        "errors": review_tex_data.get("errors") or [],
    }

    if len(evidence_records) >= 2:
        snippet_summaries = []
        for record in evidence_records[:2]:
            status_code, snippet = _safe_post(
                client,
                "/api/report/source-snippet",
                {
                    "report_payload": review_tex_data,
                    "evidence_id": record.get("evidence_id"),
                    "context_radius": 4,
                },
            )
            snippet_data = snippet.get("data") or {}
            snippet_summaries.append(
                {
                    "status": status_code,
                    "evidence_id": record.get("evidence_id"),
                    "summary": (((snippet_data.get("snippet") or {}).get("summary"))),
                    "focus_line": (((snippet_data.get("snippet") or {}).get("focus_line"))),
                }
            )
        summary["snippet_tex"] = snippet_summaries
        summary["snippet_focus_lines_distinct"] = len(
            {item.get("focus_line") for item in snippet_summaries if item.get("focus_line") is not None}
        ) > 1
    else:
        summary["snippet_tex"] = []
        summary["snippet_focus_lines_distinct"] = False

    line_evidence_records = [
        record for record in evidence_records if isinstance(record.get("location"), dict) and record["location"].get("line")
    ]
    if len(line_evidence_records) >= 2:
        line_snippets = []
        for record in line_evidence_records[:3]:
            status_code, snippet = _safe_post(
                client,
                "/api/report/source-snippet",
                {
                    "report_payload": review_tex_data,
                    "evidence_id": record.get("evidence_id"),
                    "context_radius": 4,
                },
            )
            snippet_data = snippet.get("data") or {}
            line_snippets.append(
                {
                    "status": status_code,
                    "evidence_id": record.get("evidence_id"),
                    "location": record.get("location"),
                    "focus_line": (((snippet_data.get("snippet") or {}).get("focus_line"))),
                    "summary": (((snippet_data.get("snippet") or {}).get("summary"))),
                }
            )
        summary["snippet_tex_line_based"] = line_snippets
        summary["line_based_focus_lines_distinct"] = len(
            {item.get("focus_line") for item in line_snippets if item.get("focus_line") is not None}
        ) > 1
    else:
        summary["snippet_tex_line_based"] = []
        summary["line_based_focus_lines_distinct"] = False

    status_code, classify_docx = _safe_post(
        client,
        "/api/classify/components",
        {
            "paper_path": str(DOCX_PATH),
            "review_track": "graduate",
        },
    )
    classify_docx_data = classify_docx.get("data") or {}
    summary["classify_docx"] = {
        "status": status_code,
        "component_count": len((((classify_docx_data.get("component_classification") or {}).get("component_map")) or [])),
        "manual_check_count": len((((classify_docx_data.get("component_classification") or {}).get("manual_check_flags")) or [])),
    }

    status_code, review_docx = _safe_post(
        client,
        "/api/review",
        {
            "paper_path": str(DOCX_PATH),
            "review_track": "graduate",
            "with_deep_review": False,
            "depth": "auto",
        },
    )
    review_docx_data = review_docx.get("data") or {}
    summary["review_docx"] = {
        "status": status_code,
        "backend": ((review_docx_data.get("meta") or {}).get("review_backend")),
        "finding_count": len((review_docx_data.get("findings") or [])),
        "evidence_count": len((review_docx_data.get("evidence_records") or [])),
        "has_component_section": "component_classification" in (review_docx_data.get("sections") or {}),
    }

    status_code, deep_tex = _safe_post(
        client,
        "/api/review/deep",
        {
            "paper_path": str(TEX_PATH),
            "review_track": "graduate",
            "with_deep_review": True,
            "depth": "deep",
        },
    )
    deep_tex_data = deep_tex.get("data") or {}
    summary["review_deep_tex"] = {
        "status": status_code,
        "backend": ((deep_tex_data.get("meta") or {}).get("review_backend")),
        "finding_count": len((deep_tex_data.get("findings") or [])),
    }

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
