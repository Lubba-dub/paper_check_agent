from __future__ import annotations

import argparse
import json
import logging
import re
import ssl
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterable, List

from article_check.layers import build_evidence_bundle

logger = logging.getLogger(__name__)
SSL_CONTEXT = ssl._create_unverified_context()


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _lookup_title(ref: Dict[str, Any]) -> str:
    title = str(ref.get("title") or "").strip()
    title = re.sub(r"\[[A-Z/]+\].*$", "", title, flags=re.IGNORECASE)
    title = re.sub(r"[，,;；]\s*(Current Psychology|Applied Sciences|Scientific Data|Behavioral Sciences|Frontiers in Neuroscience|Communications Biology|Transactions of the Association for Computational Linguistics|Biomedical Signal Processing and Control).*$", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\s+", " ", title).strip(" .，,;；")
    return title


def _extract_arxiv_id(ref: Dict[str, Any]) -> str:
    text = " ".join(str(ref.get(key) or "") for key in ["arxiv_id", "raw_text", "title"])
    match = re.search(r"\b(?:arxiv:)?(\d{4}\.\d{4,5}(?:v\d+)?)\b", text, re.IGNORECASE)
    return match.group(1) if match else ""


def _fetch_json(url: str) -> Dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": "ArticleCheck/1.0"})
    with urllib.request.urlopen(req, timeout=20, context=SSL_CONTEXT) as resp:
        return json.loads(resp.read().decode())


def _fetch_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "ArticleCheck/1.0"})
    with urllib.request.urlopen(req, timeout=20, context=SSL_CONTEXT) as resp:
        return resp.read().decode(errors="ignore")


def _query_openalex(ref: Dict[str, Any]) -> Dict[str, Any] | None:
    title = _lookup_title(ref)
    if not title:
        return None
    params = urllib.parse.urlencode({"search": title, "per-page": 1})
    data = _fetch_json(f"https://api.openalex.org/works?{params}")
    item = (data.get("results") or [{}])[0]
    if not item or not item.get("display_name"):
        return None
    return {
        "title": item.get("display_name"),
        "doi": item.get("doi"),
        "year": item.get("publication_year"),
        "authors": [author.get("display_name") for author in (item.get("authorships") or []) if author.get("display_name")][:8],
        "openalex_id": item.get("id"),
        "source_url": item.get("primary_location", {}).get("landing_page_url"),
    }


def _query_dblp(ref: Dict[str, Any]) -> Dict[str, Any] | None:
    title = _lookup_title(ref)
    if not title:
        return None
    params = urllib.parse.urlencode({"q": title, "h": 1, "format": "json"})
    data = _fetch_json(f"https://dblp.org/search/publ/api?{params}")
    hits = (((data.get("result") or {}).get("hits") or {}).get("hit") or [])
    if not hits:
        return None
    info = hits[0].get("info") or {}
    authors = info.get("authors") or {}
    author_value = authors.get("author") if isinstance(authors, dict) else authors
    if isinstance(author_value, list):
        author_names = [item.get("text") if isinstance(item, dict) else str(item) for item in author_value]
    elif isinstance(author_value, dict):
        author_names = [author_value.get("text") or ""]
    elif author_value:
        author_names = [str(author_value)]
    else:
        author_names = []
    return {
        "title": info.get("title"),
        "doi": info.get("doi"),
        "year": int(info.get("year")) if str(info.get("year") or "").isdigit() else None,
        "authors": [name for name in author_names if name][:8],
        "dblp_key": info.get("key"),
        "source_url": info.get("url"),
        "venue": info.get("venue"),
    }


def _query_acl(ref: Dict[str, Any]) -> Dict[str, Any] | None:
    title = _lookup_title(ref)
    if not title:
        return None
    query = urllib.parse.quote_plus(title)
    html = _fetch_text(f"https://aclanthology.org/search/?q={query}")
    href_match = re.search(r'href="(https://aclanthology\.org/[^"]+/)"', html)
    title_match = re.search(r'<span class="d-block title">([^<]+)</span>', html)
    if not href_match or not title_match:
        return None
    return {
        "title": _normalize_text(title_match.group(1)),
        "source_url": href_match.group(1),
        "doi": None,
        "year": None,
        "authors": [],
    }


def _query_arxiv(ref: Dict[str, Any]) -> Dict[str, Any] | None:
    arxiv_id = _extract_arxiv_id(ref)
    if not arxiv_id:
        return None
    params = urllib.parse.urlencode({"search_query": f"id:{arxiv_id}", "max_results": 1})
    xml_text = _fetch_text(f"http://export.arxiv.org/api/query?{params}")
    entry_match = re.search(r"<entry>(.*?)</entry>", xml_text, re.DOTALL)
    title_match = re.search(r"<title>([^<]+)</title>", entry_match.group(1), re.DOTALL) if entry_match else None
    if not title_match:
        return None
    authors = re.findall(r"<name>([^<]+)</name>", xml_text)
    published = re.search(r"<published>(\d{4})-", xml_text)
    return {
        "title": _normalize_text(title_match.group(1)),
        "arxiv_id": arxiv_id,
        "year": int(published.group(1)) if published else None,
        "authors": authors[:8],
        "source_url": f"https://arxiv.org/abs/{arxiv_id}",
    }


def _write_jsonl(path: Path, records: Iterable[Dict[str, Any]]) -> int:
    rows = [record for record in records if record]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for item in rows:
            fh.write(json.dumps(item, ensure_ascii=False) + "\n")
    return len(rows)


def build_first_snapshots(paper_path: str, output_dir: str) -> Dict[str, int]:
    bundle = build_evidence_bundle(paper_path, review_track="graduate")
    refs = (bundle.get("bibliography") or {}).get("references") or []

    openalex_records = []
    dblp_records = []
    acl_records = []
    arxiv_records = []

    for ref in refs[:20]:
        try:
            result = _query_openalex(ref)
            if result:
                openalex_records.append(result)
        except Exception as exc:
            logger.warning("OpenAlex 查询失败 [%s]: %s", ref.get("title"), exc)

        try:
            result = _query_dblp(ref)
            if result:
                dblp_records.append(result)
        except Exception as exc:
            logger.warning("DBLP 查询失败 [%s]: %s", ref.get("title"), exc)

        try:
            result = _query_acl(ref)
            if result:
                acl_records.append(result)
        except Exception as exc:
            logger.warning("ACL 查询失败 [%s]: %s", ref.get("title"), exc)

        try:
            result = _query_arxiv(ref)
            if result:
                arxiv_records.append(result)
        except Exception as exc:
            logger.warning("arXiv 查询失败 [%s]: %s", ref.get("title"), exc)

    output = Path(output_dir)
    return {
        "openalex_snapshot.jsonl": _write_jsonl(output / "openalex_snapshot.jsonl", openalex_records),
        "dblp_snapshot.jsonl": _write_jsonl(output / "dblp_snapshot.jsonl", dblp_records),
        "acl_anthology.jsonl": _write_jsonl(output / "acl_anthology.jsonl", acl_records),
        "arxiv_metadata.jsonl": _write_jsonl(output / "arxiv_metadata.jsonl", arxiv_records),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="为 ArticleCheck 生成第一版离线索引快照")
    parser.add_argument("--paper", required=True, help="用于抽取参考文献的论文路径")
    parser.add_argument("--output-dir", default=".article_check/offline_indices", help="快照输出目录")
    args = parser.parse_args()

    summary = build_first_snapshots(args.paper, args.output_dir)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
