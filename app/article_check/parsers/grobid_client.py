from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from article_check.config.settings import config

logger = logging.getLogger(__name__)

TEI_NS = {"tei": "http://www.tei-c.org/ns/1.0"}


def _normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _first_text(node: Optional[ET.Element], xpath: str) -> str:
    if node is None:
        return ""
    target = node.find(xpath, TEI_NS)
    return _normalize_space("".join(target.itertext())) if target is not None else ""


def _iter_texts(node: Optional[ET.Element], xpath: str) -> List[str]:
    if node is None:
        return []
    return [
        _normalize_space("".join(item.itertext()))
        for item in node.findall(xpath, TEI_NS)
        if _normalize_space("".join(item.itertext()))
    ]


def _parse_coords(value: str) -> List[Dict[str, Any]]:
    coords: List[Dict[str, Any]] = []
    for part in str(value or "").split(";"):
        part = part.strip()
        if not part:
            continue
        pieces = [item.strip() for item in part.split(",")]
        if len(pieces) < 5:
            continue
        try:
            coords.append(
                {
                    "page": int(float(pieces[0])),
                    "x": float(pieces[1]),
                    "y": float(pieces[2]),
                    "w": float(pieces[3]),
                    "h": float(pieces[4]),
                }
            )
        except Exception:
            continue
    return coords


def _first_bbox(coords: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not coords:
        return None
    first = coords[0]
    return {
        "x": round(first["x"], 2),
        "y": round(first["y"], 2),
        "w": round(first["w"], 2),
        "h": round(first["h"], 2),
    }


class GrobidClient:
    """GROBID TEI client for PDF parsing enhancement."""

    def __init__(
        self,
        *,
        base_url: Optional[str] = None,
        timeout: Optional[int] = None,
    ):
        self.base_url = (base_url or config.parser.grobid_base_url).rstrip("/")
        self.timeout = timeout or config.parser.grobid_timeout
        self.enabled = config.parser.grobid_enabled

    def process_fulltext_document(self, pdf_path: str | Path) -> Dict[str, Any]:
        if not self.enabled:
            return {"enabled": False, "reason": "grobid_disabled"}

        path = Path(pdf_path)
        if not path.exists():
            return {"enabled": False, "reason": f"file_not_found:{path}"}

        try:
            with path.open("rb") as fh, httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    f"{self.base_url}/api/processFulltextDocument",
                    data={
                        "consolidateHeader": str(config.parser.grobid_consolidate_header),
                        "consolidateCitations": str(config.parser.grobid_consolidate_citations),
                        "includeRawCitations": "1" if config.parser.grobid_include_raw_citations else "0",
                        "teiCoordinates": config.parser.grobid_tei_coordinates,
                    },
                    files={"input": (path.name, fh, "application/pdf")},
                )
                response.raise_for_status()
        except Exception as exc:
            logger.warning("GROBID fulltext 解析失败: %s", exc)
            return {"enabled": False, "reason": str(exc)}

        xml_text = response.text
        return {
            "enabled": True,
            "source": "grobid",
            "tei_xml": xml_text,
            **self._parse_tei(xml_text),
        }

    def _parse_tei(self, xml_text: str) -> Dict[str, Any]:
        try:
            root = ET.fromstring(xml_text)
        except Exception as exc:
            logger.warning("GROBID TEI XML 解析失败: %s", exc)
            return {"enabled": False, "reason": f"tei_parse_error:{exc}"}

        title = _first_text(root, ".//tei:titleStmt/tei:title")
        abstract = _first_text(root, ".//tei:profileDesc/tei:abstract")

        blocks: List[Dict[str, Any]] = []
        anchors: List[Dict[str, Any]] = []
        structure: List[Dict[str, Any]] = []

        for node_index, node in enumerate(root.findall(".//tei:text/tei:body//tei:head", TEI_NS), start=1):
            text = _normalize_space("".join(node.itertext()))
            coords = _parse_coords(node.attrib.get("coords", ""))
            block_id = f"grobid-head-{node_index}"
            block = {
                "block_id": block_id,
                "type": "heading",
                "page": coords[0]["page"] if coords else None,
                "paragraph_index": None,
                "heading_level": max(1, min(4, len(node.findall("./ancestor::tei:div", TEI_NS)) if False else 1)),
                "text": text,
                "bbox": _first_bbox(coords),
                "coords": coords,
                "style": {"parser": "grobid"},
            }
            blocks.append(block)
            anchors.append(
                {
                    "anchor_id": f"anchor-{block_id}",
                    "block_id": block_id,
                    "page": block["page"],
                    "paragraph_index": None,
                    "bbox": block["bbox"],
                    "text_excerpt": text[:200],
                }
            )
            structure.append(
                {
                    "node_id": f"grobid-section-{len(structure) + 1}",
                    "heading": text,
                    "level": 1,
                    "page_start": block["page"],
                    "page_end": block["page"],
                    "block_ids": [block_id],
                    "paragraph_start": None,
                    "paragraph_end": None,
                    "text_excerpt": "",
                }
            )

        for para_index, node in enumerate(root.findall(".//tei:text/tei:body//tei:p", TEI_NS), start=1):
            text = _normalize_space("".join(node.itertext()))
            if not text:
                continue
            coords = _parse_coords(node.attrib.get("coords", ""))
            block_id = f"grobid-p-{para_index}"
            block = {
                "block_id": block_id,
                "type": "paragraph",
                "page": coords[0]["page"] if coords else None,
                "paragraph_index": para_index,
                "heading_level": None,
                "text": text,
                "bbox": _first_bbox(coords),
                "coords": coords,
                "style": {"parser": "grobid"},
            }
            blocks.append(block)
            anchors.append(
                {
                    "anchor_id": f"anchor-{block_id}",
                    "block_id": block_id,
                    "page": block["page"],
                    "paragraph_index": para_index,
                    "bbox": block["bbox"],
                    "text_excerpt": text[:200],
                }
            )

        bibliography: List[Dict[str, Any]] = []
        for index, item in enumerate(root.findall(".//tei:listBibl/tei:biblStruct", TEI_NS), start=1):
            coords = _parse_coords(item.attrib.get("coords", ""))
            title_level_a = _first_text(item, ".//tei:analytic/tei:title")
            title_level_j = _first_text(item, ".//tei:monogr/tei:title")
            authors = []
            for author in item.findall(".//tei:analytic/tei:author", TEI_NS) or item.findall(".//tei:monogr/tei:author", TEI_NS):
                parts = [
                    _first_text(author, "./tei:persName/tei:forename"),
                    _first_text(author, "./tei:persName/tei:surname"),
                ]
                text = _normalize_space(" ".join(part for part in parts if part))
                if text:
                    authors.append(text)
            doi = ""
            arxiv_id = ""
            pmid = ""
            for idno in item.findall(".//tei:idno", TEI_NS):
                id_type = str(idno.attrib.get("type", "")).lower()
                value = _normalize_space("".join(idno.itertext()))
                if id_type == "doi" and value:
                    doi = value
                elif id_type == "arxiv" and value:
                    arxiv_id = value
                elif id_type in {"pmid", "pubmed"} and value:
                    pmid = value
            raw_note = _first_text(item, ".//tei:note[@type='raw_reference']")
            year_text = _first_text(item, ".//tei:date")
            year_match = re.search(r"(19|20)\d{2}", year_text)
            bibliography.append(
                {
                    "reference_id": item.attrib.get("{http://www.w3.org/XML/1998/namespace}id") or f"b{index}",
                    "anchor_id": f"reference-{index}",
                    "title": title_level_a or title_level_j,
                    "authors": authors,
                    "year": int(year_match.group()) if year_match else None,
                    "journal": title_level_j if title_level_j and title_level_j != title_level_a else "",
                    "booktitle": "",
                    "publisher": _first_text(item, ".//tei:publisher"),
                    "volume": _first_text(item, ".//tei:biblScope[@unit='volume']"),
                    "number": _first_text(item, ".//tei:biblScope[@unit='issue']"),
                    "pages": _first_text(item, ".//tei:biblScope[@unit='page']"),
                    "doi": doi,
                    "arxiv_id": arxiv_id,
                    "pmid": pmid,
                    "url": _first_text(item, ".//tei:ptr"),
                    "source": "grobid",
                    "raw_text": raw_note,
                    "page": coords[0]["page"] if coords else None,
                    "bbox": _first_bbox(coords),
                }
            )

        citations: List[Dict[str, Any]] = []
        for index, ref in enumerate(root.findall(".//tei:text/tei:body//tei:ref[@type='bibr']", TEI_NS), start=1):
            text = _normalize_space("".join(ref.itertext()))
            target = str(ref.attrib.get("target", "")).strip().lstrip("#")
            coords = _parse_coords(ref.attrib.get("coords", ""))
            parent = None
            for candidate in root.findall(".//tei:text/tei:body//tei:p", TEI_NS):
                if ref in list(candidate.iter()):
                    parent = candidate
                    break
            parent_text = _normalize_space("".join(parent.itertext())) if parent is not None else ""
            if text and parent_text and text in parent_text:
                pos = parent_text.find(text)
                context_before = parent_text[max(0, pos - 180):pos].strip()
                context_after = parent_text[pos + len(text): pos + len(text) + 180].strip()
            else:
                context_before = ""
                context_after = ""
            citations.append(
                {
                    "citation_id": f"citation-{index}",
                    "text": text,
                    "ref_ids": [target] if target else [],
                    "context_before": context_before,
                    "context_after": context_after,
                    "char_start": None,
                    "char_end": None,
                    "page": coords[0]["page"] if coords else None,
                    "bbox": _first_bbox(coords),
                    "target_ref_id": target or None,
                }
            )

        figures: List[Dict[str, Any]] = []
        tables: List[Dict[str, Any]] = []
        captions: List[Dict[str, Any]] = []
        for index, figure in enumerate(root.findall(".//tei:figure", TEI_NS), start=1):
            coords = _parse_coords(figure.attrib.get("coords", ""))
            head = _first_text(figure, "./tei:head")
            desc = _first_text(figure, "./tei:figDesc")
            label = _first_text(figure, "./tei:label")
            caption_id = f"caption-grobid-{index}"
            captions.append(
                {
                    "caption_id": caption_id,
                    "block_id": None,
                    "page": coords[0]["page"] if coords else None,
                    "bbox": _first_bbox(coords),
                    "label": _normalize_space(" ".join(part for part in [label, head, desc] if part))[:200],
                }
            )
            figure_type = (figure.attrib.get("type") or "").lower()
            record = {
                "page": coords[0]["page"] if coords else None,
                "bbox": _first_bbox(coords),
                "caption_id": caption_id,
            }
            if figure_type == "table":
                tables.append({"table_id": f"tbl-{len(tables) + 1}", **record})
            else:
                figures.append({"figure_id": f"fig-{len(figures) + 1}", **record})

        return {
            "title": title,
            "abstract": abstract,
            "blocks": blocks,
            "anchors": anchors,
            "document_structure": structure,
            "bibliography": bibliography,
            "citations": citations,
            "figures": figures,
            "tables": tables,
            "captions": captions,
        }
