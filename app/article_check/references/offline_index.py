from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from article_check.config.settings import config

logger = logging.getLogger(__name__)

OFFLINE_FILES = (
    "openalex_snapshot.jsonl",
    "dblp_snapshot.jsonl",
    "acl_anthology.jsonl",
    "arxiv_metadata.jsonl",
)


def _normalize_text(value: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", str(value or "").lower()).strip()


def _candidate_identifiers(record: Dict[str, Any]) -> Dict[str, str]:
    doi = str(record.get("doi") or record.get("DOI") or "").strip().lower()
    arxiv_id = str(record.get("arxiv_id") or record.get("arxivId") or "").strip().lower()
    pmid = str(record.get("pmid") or record.get("pubmed_id") or "").strip().lower()
    title = str(record.get("title") or record.get("display_name") or "").strip()
    authors = record.get("authors") or record.get("author_names") or []
    year = record.get("year") or record.get("publication_year")
    if isinstance(authors, str):
        authors = [item.strip() for item in re.split(r"[;,，]", authors) if item.strip()]
    return {
        "doi": doi,
        "arxiv_id": arxiv_id,
        "pmid": pmid,
        "normalized_title": _normalize_text(title),
        "title_authors_year": _title_authors_year_key(title, authors, year),
    }


def _title_authors_year_key(title: str, authors: Iterable[str], year: Any) -> str:
    author_tokens = [_normalize_text(item) for item in list(authors or [])[:3] if item]
    year_token = str(year or "").strip()
    return "::".join(filter(None, [_normalize_text(title), "|".join(author_tokens), year_token]))


@dataclass
class OfflineIndexMatch:
    source: str
    record: Dict[str, Any]
    score: float
    matched_key: str


class OfflineReferenceIndex:
    """Lazy-loaded offline metadata index for OpenAlex/DBLP/ACL/arXiv snapshots."""

    def __init__(self, base_dir: Optional[str] = None):
        self.base_dir = Path(base_dir or config.reference.offline_index_dir)
        self._loaded = False
        self._by_doi: Dict[str, Dict[str, Any]] = {}
        self._by_arxiv: Dict[str, Dict[str, Any]] = {}
        self._by_pmid: Dict[str, Dict[str, Any]] = {}
        self._by_title: Dict[str, Dict[str, Any]] = {}
        self._by_tay: Dict[str, Dict[str, Any]] = {}

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not config.reference.enable_offline_index:
            return
        if not self.base_dir.exists():
            logger.info("离线索引目录不存在，跳过加载: %s", self.base_dir)
            return

        for filename in OFFLINE_FILES:
            path = self.base_dir / filename
            if not path.exists():
                continue
            try:
                self._load_file(path)
            except Exception as exc:
                logger.warning("加载离线索引失败 [%s]: %s", path, exc)

    def _load_file(self, path: Path) -> None:
        source_name = path.stem
        if path.suffix.lower() == ".json":
            payload = json.loads(path.read_text(encoding="utf-8"))
            records = payload if isinstance(payload, list) else payload.get("records") or []
        else:
            records = []
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except Exception:
                    continue

        for record in records:
            if not isinstance(record, dict):
                continue
            item = dict(record)
            item.setdefault("offline_source", source_name)
            ids = _candidate_identifiers(item)
            if ids["doi"]:
                self._by_doi.setdefault(ids["doi"], item)
            if ids["arxiv_id"]:
                self._by_arxiv.setdefault(ids["arxiv_id"], item)
            if ids["pmid"]:
                self._by_pmid.setdefault(ids["pmid"], item)
            if ids["normalized_title"]:
                self._by_title.setdefault(ids["normalized_title"], item)
            if ids["title_authors_year"]:
                self._by_tay.setdefault(ids["title_authors_year"], item)

    def lookup(self, ref: Dict[str, Any]) -> Optional[OfflineIndexMatch]:
        self._load()
        if not any([self._by_doi, self._by_arxiv, self._by_pmid, self._by_title, self._by_tay]):
            return None

        doi = str(ref.get("doi") or "").strip().lower()
        arxiv_id = str(ref.get("arxiv_id") or "").strip().lower()
        pmid = str(ref.get("pmid") or "").strip().lower()
        title = str(ref.get("title") or "")
        authors = ref.get("authors") or []
        year = ref.get("year")

        if doi and doi in self._by_doi:
            return OfflineIndexMatch(self._by_doi[doi].get("offline_source", "offline"), self._by_doi[doi], 1.0, "doi")
        if arxiv_id and arxiv_id in self._by_arxiv:
            return OfflineIndexMatch(self._by_arxiv[arxiv_id].get("offline_source", "offline"), self._by_arxiv[arxiv_id], 1.0, "arxiv_id")
        if pmid and pmid in self._by_pmid:
            return OfflineIndexMatch(self._by_pmid[pmid].get("offline_source", "offline"), self._by_pmid[pmid], 1.0, "pmid")

        tay = _title_authors_year_key(title, authors, year)
        if tay and tay in self._by_tay:
            return OfflineIndexMatch(self._by_tay[tay].get("offline_source", "offline"), self._by_tay[tay], 0.96, "title_authors_year")

        normalized_title = _normalize_text(title)
        if normalized_title and normalized_title in self._by_title:
            return OfflineIndexMatch(self._by_title[normalized_title].get("offline_source", "offline"), self._by_title[normalized_title], 0.9, "normalized_title")
        return None
