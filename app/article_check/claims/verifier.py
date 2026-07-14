from __future__ import annotations

import json
import logging
import re
import urllib.parse
import urllib.request
from typing import Any, Dict, List

from article_check.config.settings import config
from article_check.llm.client.deepseek import DeepSeekClient

logger = logging.getLogger(__name__)


def _decode_openalex_abstract(abstract_index: Dict[str, List[int]]) -> str:
    if not isinstance(abstract_index, dict):
        return ""
    tokens = []
    for word, positions in abstract_index.items():
        for position in positions:
            tokens.append((position, word))
    tokens.sort(key=lambda item: item[0])
    return " ".join(word for _, word in tokens).strip()


def fetch_reference_snippet(title: str) -> Dict[str, Any]:
    if not title:
        return {}
    snippet_chars = config.claim_verify.abstract_snippet_chars
    try:
        params = urllib.parse.urlencode({"search": title, "per-page": 1})
        url = f"{config.reference.openalex_api}/works?{params}"
        req = urllib.request.Request(url, headers={"User-Agent": "ArticleCheck/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        item = (data.get("results") or [{}])[0]
        abstract = _decode_openalex_abstract(item.get("abstract_inverted_index") or {})
        return {
            "matched_title": item.get("display_name") or "",
            "abstract": abstract[:snippet_chars],
            "publication_year": item.get("publication_year"),
            "doi": item.get("doi"),
            "source": "openalex",
        }
    except Exception as exc:
        return {"source": "openalex", "error": str(exc)}


def select_support_critical_claims(bundle: Dict[str, Any], fast_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    suspicious_by_ref = {}
    for index, item in enumerate(fast_items, start=1):
        if not item.get("exists") or not item.get("doi_valid"):
            ref_id = str(item.get("reference_id") or index)
            suspicious_by_ref[ref_id] = item
            match = re.search(r"(\d+)$", ref_id)
            if match:
                suspicious_by_ref[match.group(1)] = item

    high_risk_terms = ["表明", "证明", "显著", "优于", "improves", "significant", "demonstrates", "outperforms"]
    claims = []
    citations = (bundle.get("bibliography") or {}).get("citations") or []
    max_claims = config.claim_verify.max_support_critical_claims

    for citation in citations:
        ref_ids = [str(item) for item in citation.get("ref_ids") or []]
        hit = next((suspicious_by_ref.get(ref_id) for ref_id in ref_ids if ref_id in suspicious_by_ref), None)
        if not hit:
            continue
        claim_text = " ".join(
            part for part in [
                citation.get("context_before", "")[-200:],
                citation.get("text", ""),
                citation.get("context_after", "")[:200],
            ]
            if part
        ).strip()
        priority = 1
        if any(term in claim_text for term in high_risk_terms):
            priority += 1
        if re.search(r"\d+(\.\d+)?%|\bp\s*[<=>]\s*0\.\d+", claim_text, re.IGNORECASE):
            priority += 1
        claims.append(
            {
                "citation_id": citation.get("citation_id"),
                "claim_text": claim_text,
                "citation": citation,
                "reference": hit,
                "priority": priority,
            }
        )

    claims.sort(key=lambda item: item.get("priority", 0), reverse=True)
    return claims[:max_claims]


def run_nli_verifier(claims: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not claims:
        return {"enabled": False, "reason": "no_support_critical_claims", "items": [], "dify_handoff_candidates": []}
    if not config.claim_verify.enable_nli:
        return {"enabled": False, "reason": "nli_disabled", "items": [], "dify_handoff_candidates": []}
    if not config.deepseek.api_key:
        return {"enabled": False, "reason": "deepseek_api_key_missing", "items": [], "dify_handoff_candidates": []}

    client = DeepSeekClient()
    schema = {
        "type": "object",
        "properties": {
            "entailment": {"type": "string", "enum": ["support", "contradict", "insufficient"]},
            "confidence": {"type": "number"},
            "rationale": {"type": "string"},
            "risk_type": {"type": "string", "enum": ["citation_support", "claim_consistency", "insufficient_evidence"]},
        },
        "required": ["entailment", "confidence", "rationale", "risk_type"],
    }

    items = []
    handoff = []
    for claim in claims:
        ref = claim.get("reference") or {}
        snippet = fetch_reference_snippet(ref.get("matched_title") or ref.get("title") or "")
        abstract = snippet.get("abstract") or ""
        if not abstract:
            item = {
                "citation_id": claim.get("citation_id"),
                "enabled": False,
                "reason": snippet.get("error") or "abstract_unavailable",
                "reference_id": ref.get("reference_id"),
                "claim_text": claim.get("claim_text"),
            }
            items.append(item)
            handoff.append(item)
            continue

        messages = [
            {
                "role": "system",
                "content": (
                    "你是学术论断核验器。根据引文上下文与参考文献摘要，判断该参考文献是否真正支持该论断。"
                    " 只允许输出 JSON。若摘要无法支持可靠判断，返回 insufficient。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"引文上下文:\n{claim.get('claim_text', '')}\n\n"
                    f"参考文献题名: {snippet.get('matched_title') or ref.get('matched_title') or ref.get('title')}\n"
                    f"参考文献摘要:\n{abstract}"
                ),
            },
        ]

        try:
            result = client.structured_chat(messages=messages, schema=schema, temperature=0.1)
            item = {
                "citation_id": claim.get("citation_id"),
                "reference_id": ref.get("reference_id"),
                "claim_text": claim.get("claim_text"),
                "reference_snippet": snippet,
                "nli_result": result,
                "enabled": True,
            }
            items.append(item)
            if result.get("entailment") == "insufficient" and config.claim_verify.enable_dify_handoff:
                handoff.append(item)
        except Exception as exc:
            item = {
                "citation_id": claim.get("citation_id"),
                "reference_id": ref.get("reference_id"),
                "claim_text": claim.get("claim_text"),
                "enabled": False,
                "reason": str(exc),
            }
            items.append(item)
            handoff.append(item)

    return {
        "enabled": True,
        "reason": None,
        "items": items,
        "dify_handoff_candidates": handoff,
    }
