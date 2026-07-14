from __future__ import annotations

import concurrent.futures
import json
import logging
import re
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from article_check.config.settings import config
from article_check.claims import run_nli_verifier, select_support_critical_claims
from article_check.references.engine import ReferenceValidator
from article_check.references.offline_index import OfflineReferenceIndex

logger = logging.getLogger(__name__)

CACHE_PATH = Path(config.reference.identity_cache_path)
OFFLINE_INDEX = OfflineReferenceIndex(config.reference.offline_index_dir)


def _normalize_text(value: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", str(value or "").lower()).strip()


def _load_cache() -> Dict[str, Any]:
    try:
        if CACHE_PATH.exists():
            return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("读取文献快核验缓存失败: %s", exc)
    return {}


def _save_cache(cache: Dict[str, Any]) -> None:
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.warning("写入文献快核验缓存失败: %s", exc)


def _cache_key(ref: Dict[str, Any]) -> str:
    doi = str(ref.get("doi") or "").strip().lower()
    if doi:
        return f"doi::{doi}"
    arxiv_id = str(ref.get("arxiv_id") or "").strip().lower()
    if arxiv_id:
        return f"arxiv::{arxiv_id}"
    pmid = str(ref.get("pmid") or "").strip().lower()
    if pmid:
        return f"pmid::{pmid}"
    title = _normalize_text(ref.get("title"))
    authors = "|".join(_normalize_text(item) for item in (ref.get("authors") or [])[:3] if item)
    year = ref.get("year") or ""
    if title and authors and year:
        return f"title-authors-year::{title}::{authors}::{year}"
    return f"title::{title}::{year}"


def _extract_identifier(ref: Dict[str, Any], pattern: str) -> str:
    text = " ".join(
        str(item or "")
        for item in [
            ref.get("raw_text"),
            ref.get("title"),
            ref.get("doi"),
            ref.get("arxiv_id"),
            ref.get("pmid"),
        ]
    )
    match = re.search(pattern, text, re.IGNORECASE)
    return match.group(1) if match else ""


def _verify_arxiv_id(arxiv_id: str) -> Dict[str, Any]:
    if not arxiv_id:
        return {"valid": False, "reason": "missing_arxiv_id"}
    try:
        params = urllib.parse.urlencode({"search_query": f"id:{arxiv_id}", "max_results": 1})
        url = f"http://export.arxiv.org/api/query?{params}"
        req = urllib.request.Request(url, headers={"User-Agent": "ArticleCheck/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            content = resp.read().decode()
        return {
            "valid": "<entry>" in content,
            "source": "arxiv",
            "arxiv_id": arxiv_id,
        }
    except Exception as exc:
        return {"valid": False, "source": "arxiv", "arxiv_id": arxiv_id, "error": str(exc)}


def _verify_pmid(pmid: str) -> Dict[str, Any]:
    if not pmid:
        return {"valid": False, "reason": "missing_pmid"}
    try:
        params = urllib.parse.urlencode({"db": "pubmed", "id": pmid, "retmode": "json"})
        url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?{params}"
        req = urllib.request.Request(url, headers={"User-Agent": "ArticleCheck/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        result = (data.get("result") or {}).get(str(pmid)) or {}
        return {
            "valid": bool(result),
            "source": "pmid",
            "pmid": pmid,
            "title": result.get("title"),
            "pubdate": result.get("pubdate"),
        }
    except Exception as exc:
        return {"valid": False, "source": "pmid", "pmid": pmid, "error": str(exc)}


def _search_semantic_scholar(title: str) -> Dict[str, Any]:
    if not title:
        return {"exists": False, "source": "semantic_scholar", "message": "title_missing"}
    try:
        params = urllib.parse.urlencode({"query": title, "limit": 1, "fields": "title,year,externalIds,authors"})
        url = f"{config.reference.semantic_scholar_api}/paper/search?{params}"
        req = urllib.request.Request(url, headers={"User-Agent": "ArticleCheck/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        item = (data.get("data") or [{}])[0]
        matched_title = item.get("title") or ""
        return {
            "exists": bool(matched_title),
            "source": "semantic_scholar",
            "matched_title": matched_title,
            "matched_year": item.get("year"),
            "matched_doi": (item.get("externalIds") or {}).get("DOI"),
            "matched_authors": [author.get("name") for author in (item.get("authors") or []) if author.get("name")][:6],
        }
    except Exception as exc:
        return {"exists": False, "source": "semantic_scholar", "message": str(exc)}


def _build_ref_issue(ref: Dict[str, Any], issue_type: str, severity: str, description: str, suggestion: str) -> Dict[str, Any]:
    return {
        "type": issue_type,
        "severity": severity,
        "description": description,
        "suggestion": suggestion,
        "location": {"section": "references"},
        "reference_id": ref.get("reference_id"),
        "evidence_span": {
            "anchor_id": ref.get("anchor_id"),
            "block_id": None,
            "page": None,
            "bbox": None,
            "locator": ref.get("title", "")[:80],
        },
        "confidence": 1.0 if severity in {"major", "critical"} else 0.95,
    }


def _verify_reference_fast(ref: Dict[str, Any], cache: Dict[str, Any]) -> Dict[str, Any]:
    key = _cache_key(ref)
    if key in cache:
        cached = dict(cache[key])
        cached["cache_hit"] = True
        return cached

    result: Dict[str, Any] = {
        "reference_id": ref.get("reference_id"),
        "title": ref.get("title"),
        "year": ref.get("year"),
        "doi": ref.get("doi"),
        "cache_hit": False,
    }

    doi = ref.get("doi") or _extract_identifier(ref, r"(10\.\d{4,}/[-._;()/:A-Za-z0-9]+)")
    arxiv_id = ref.get("arxiv_id") or _extract_identifier(ref, r"\b(arxiv:\s*[A-Za-z0-9.\-]+|\d{4}\.\d{4,5}(?:v\d+)?)\b")
    pmid = ref.get("pmid") or _extract_identifier(ref, r"\bPMID[:\s]*([0-9]{4,12})\b")

    identifier_hits = []
    if doi:
        doi_result = ReferenceValidator.verify_doi(doi)
        result["doi_result"] = doi_result
        result["doi_valid"] = bool(doi_result.get("valid"))
        if result["doi_valid"]:
            identifier_hits.append({"identifier_type": "doi", "identifier": doi, "result": doi_result})
    else:
        result["doi_result"] = {"valid": False, "reason": "missing_doi"}
        result["doi_valid"] = False

    if arxiv_id:
        arxiv_result = _verify_arxiv_id(str(arxiv_id).replace("arxiv:", "").strip())
        result["arxiv_result"] = arxiv_result
        if arxiv_result.get("valid"):
            identifier_hits.append({"identifier_type": "arxiv", "identifier": arxiv_id, "result": arxiv_result})

    if pmid:
        pmid_result = _verify_pmid(str(pmid).strip())
        result["pmid_result"] = pmid_result
        if pmid_result.get("valid"):
            identifier_hits.append({"identifier_type": "pmid", "identifier": pmid, "result": pmid_result})

    result["identifier_hits"] = identifier_hits
    result["resolution_layer"] = "identifier" if identifier_hits else "unresolved"

    offline_match = OFFLINE_INDEX.lookup(ref)
    if offline_match:
        result["offline_match"] = {
            "source": offline_match.source,
            "score": offline_match.score,
            "matched_key": offline_match.matched_key,
            "record": offline_match.record,
        }
        result["exists"] = True
        result["matched_title"] = offline_match.record.get("title") or offline_match.record.get("display_name") or ""
        result["matched_year"] = offline_match.record.get("year") or offline_match.record.get("publication_year")
        result["matched_doi"] = offline_match.record.get("doi") or offline_match.record.get("DOI")
        result["title_similarity"] = offline_match.score
        result["score"] = offline_match.score
        if result["resolution_layer"] == "unresolved":
            result["resolution_layer"] = "offline_index"

    exists_result = {}
    semantic_result = {}
    if config.reference.enable_online_lookup:
        exists_result = ReferenceValidator.check_reference_exists(
            ref.get("title") or "",
            authors=ref.get("authors") or [],
            year=ref.get("year"),
        )
        semantic_result = _search_semantic_scholar(ref.get("title") or "")
    result["exists_result"] = exists_result
    result["semantic_scholar_result"] = semantic_result

    result["exists"] = bool(
        result.get("exists")
        or exists_result.get("exists")
        or semantic_result.get("exists")
        or identifier_hits
    )
    if not result.get("matched_title"):
        result["matched_title"] = exists_result.get("matched_title") or semantic_result.get("matched_title") or ""
    if not result.get("matched_year"):
        result["matched_year"] = exists_result.get("matched_year") or semantic_result.get("matched_year")
    if not result.get("matched_doi"):
        result["matched_doi"] = exists_result.get("matched_doi") or semantic_result.get("matched_doi")
    result["title_similarity"] = result.get("title_similarity") or exists_result.get("title_similarity")
    result["score"] = result.get("score") or exists_result.get("score", 0.0) or (0.88 if semantic_result.get("exists") else 0.0)
    if result["resolution_layer"] == "unresolved" and (exists_result.get("exists") or semantic_result.get("exists")):
        result["resolution_layer"] = "online_lookup"

    cache[key] = {
        k: v for k, v in result.items()
        if k not in {"cache_hit"}
    }
    return result


def _reference_numeric_id(ref: Dict[str, Any], index: int) -> List[str]:
    identifiers = [str(index)]
    ref_id = str(ref.get("reference_id") or "")
    if ref_id:
        identifiers.append(ref_id)
        match = re.search(r"(\d+)$", ref_id)
        if match:
            identifiers.append(match.group(1))
    return identifiers


def _run_fast_path(refs: List[Dict[str, Any]], cache: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not refs:
        return []
    max_workers = max(1, int(config.reference.fast_verify_workers or 1))
    results: List[Dict[str, Any]] = [None] * len(refs)  # type: ignore[list-item]
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {
            executor.submit(_verify_reference_fast, ref, cache): index
            for index, ref in enumerate(refs)
        }
        for future in concurrent.futures.as_completed(future_map):
            index = future_map[future]
            try:
                results[index] = future.result()
            except Exception as exc:
                ref = refs[index]
                results[index] = {
                    "reference_id": ref.get("reference_id"),
                    "title": ref.get("title"),
                    "cache_hit": False,
                    "exists": False,
                    "doi_valid": False,
                    "resolution_layer": "error",
                    "error": str(exc),
                }
    return [item for item in results if item is not None]


def run_layered_verification(
    bundle: Dict[str, Any],
    *,
    detailed_mode: bool = False,
) -> Dict[str, Any]:
    bibliography = bundle.get("bibliography") or {}
    refs = bibliography.get("references") or []
    ref_stats = bibliography.get("reference_stats") or {}
    cache = _load_cache()

    fast_items = _run_fast_path(refs[: min(len(refs), config.reference.max_refs_per_paper)], cache)
    _save_cache(cache)

    issues: List[Dict[str, Any]] = []
    suspicious_refs: List[Dict[str, Any]] = []

    for ref, item in zip(refs[: len(fast_items)], fast_items):
        if not ref.get("doi"):
            issues.append(
                _build_ref_issue(
                    ref,
                    "doi_missing",
                    "major",
                    f"参考文献“{ref.get('title', '')[:48]}”缺失 DOI。",
                    "补充 DOI 或说明该条目不具备 DOI。",
                )
            )
        if ref.get("doi") and not item.get("doi_valid"):
            issues.append(
                _build_ref_issue(
                    ref,
                    "doi_invalid",
                    "critical",
                    f"参考文献“{ref.get('title', '')[:48]}”的 DOI 无法通过 Crossref 验证。",
                    "复核 DOI、题名和出版信息，确认不存在错引或伪造条目。",
                )
            )
            suspicious_refs.append(item)
        if ref.get("title") and not item.get("exists"):
            issues.append(
                _build_ref_issue(
                    ref,
                    "reference_not_found",
                    "major",
                    f"参考文献“{ref.get('title', '')[:48]}”未在 Crossref/OpenAlex 中检索到高置信候选。",
                    "核对题名、作者与年份，必要时人工检索原始出处。",
                )
            )
            suspicious_refs.append(item)

    unmatched_citations = ref_stats.get("unmatched_citations") or []
    if unmatched_citations:
        issues.append(
            {
                "type": "citation_mismatch",
                "severity": "critical",
                "description": f"检测到 {len(unmatched_citations)} 处正文引用无法匹配到参考文献。",
                "suggestion": "核对正文引用编号与参考文献列表映射。",
                "location": {"section": "references"},
                "evidence_span": {
                    "anchor_id": None,
                    "block_id": None,
                    "page": None,
                    "bbox": None,
                    "locator": "references",
                },
                "confidence": 1.0,
            }
        )

    support_critical_claims = select_support_critical_claims(bundle, fast_items)
    deep_path = run_nli_verifier(support_critical_claims) if detailed_mode else {
        "enabled": False,
        "reason": "detailed_mode_disabled",
        "items": [],
        "dify_handoff_candidates": [],
    }

    for item in deep_path.get("items", []):
        nli_result = item.get("nli_result") or {}
        if not item.get("enabled"):
            continue
        entailment = nli_result.get("entailment")
        if entailment in {"contradict", "insufficient"}:
            issues.append(
                {
                    "type": nli_result.get("risk_type") or "claim_consistency",
                    "severity": "major" if entailment == "insufficient" else "critical",
                    "description": nli_result.get("rationale") or "高风险引文在摘要层面缺乏充分支撑。",
                    "suggestion": "补充更直接的证据来源，或修订该论断的强度与表述。",
                    "location": {"section": "content"},
                    "evidence_span": {
                        "anchor_id": item.get("citation_id"),
                        "block_id": None,
                        "page": None,
                        "bbox": None,
                        "locator": (item.get("claim_text") or "")[:80],
                    },
                    "confidence": float(nli_result.get("confidence") or 0.75),
                }
            )

    return {
        "layer": "verification",
        "fast_path": {
            "cache_path": str(CACHE_PATH),
            "checked_references": len(fast_items),
            "items": fast_items,
            "cache_hits": len([item for item in fast_items if item.get("cache_hit")]),
            "offline_hits": len([item for item in fast_items if item.get("resolution_layer") == "offline_index"]),
            "identifier_hits": len([item for item in fast_items if item.get("resolution_layer") == "identifier"]),
            "online_hits": len([item for item in fast_items if item.get("resolution_layer") == "online_lookup"]),
        },
        "deep_path": deep_path,
        "claim_verify": {
            "support_critical_claims": support_critical_claims,
            "dify_handoff_candidates": deep_path.get("dify_handoff_candidates") or [],
        },
        "issues": issues,
        "suspicious_references": suspicious_refs,
        "pending_manual_checks": [
            f"建议人工复核 {item.get('title') or item.get('matched_title') or item.get('reference_id')}"
            for item in suspicious_refs[:8]
        ],
        "score": max(0.0, round(1.0 - len(issues) * 0.08, 3)),
        "reference_stats": ref_stats,
    }
