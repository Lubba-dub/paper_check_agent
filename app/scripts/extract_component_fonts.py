#!/usr/bin/env python
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List


def _summarize_counter(values: List[Any], limit: int = 5) -> List[Dict[str, Any]]:
    counter = Counter(value for value in values if value not in (None, "", []))
    return [{"value": key, "count": count} for key, count in counter.most_common(limit)]


def _docx_component_name(text: str, page: int, style_name: str) -> str:
    normalized = re.sub(r"\s+", "", text or "").lower()
    if page == 1 and any(token in normalized for token in ["论文", "学位", "作者", "姓名", "导师", "学院", "专业"]):
        return "cover"
    if any(token in normalized for token in ["诚信承诺书", "论文使用授权说明", "原创性声明", "版权声明"]):
        return "statement"
    if normalized.rstrip(":：") in {"摘要", "abstract", "摘 要"}:
        return "abstract_heading"
    if normalized.rstrip(":：") in {"关键词", "keywords", "key words"}:
        return "keywords_heading"
    if style_name and "heading" in style_name.lower():
        return "heading"
    if re.match(r"^(图|表|figure|table)\s*\d+", text.strip(), re.IGNORECASE):
        return "caption"
    return "body"


def extract_docx_fonts(path: Path) -> Dict[str, Any]:
    from docx import Document

    doc = Document(str(path))
    para_map = {id(para._p): para for para in doc.paragraphs}
    current_page = 1
    components: Dict[str, Dict[str, List[Any]]] = defaultdict(lambda: defaultdict(list))

    for child in doc.element.body.iterchildren():
        tag = child.tag.split("}")[-1]
        if tag != "p" or id(child) not in para_map:
            continue
        para = para_map[id(child)]
        if para.paragraph_format and para.paragraph_format.page_break_before and components:
            current_page += 1
        text = para.text.strip()
        if text:
            style_name = para.style.name if para.style else ""
            component = _docx_component_name(text, current_page, style_name)
            components[component]["samples"].append(text[:80])
            components[component]["pages"].append(current_page)
            components[component]["styles"].append(style_name or "")
            components[component]["alignments"].append(str(para.alignment))
            for run in para.runs:
                if run.font and run.font.name:
                    components[component]["fonts"].append(run.font.name)
                if run.font and run.font.size:
                    components[component]["font_sizes_pt"].append(round(float(run.font.size.pt), 2))
                components[component]["bold"].append(bool(run.bold))
                components[component]["italic"].append(bool(run.italic))
        if para._element.xpath('./*[local-name()="pPr"]/*[local-name()="sectPr"]') or para._element.xpath('.//*[local-name()="br" and @*[local-name()="type"]="page"]'):
            current_page += 1

    return {
        "file_type": "docx",
        "components": {
            name: {
                "sample_count": len(payload.get("samples", [])),
                "sample_texts": payload.get("samples", [])[:5],
                "pages": sorted(set(payload.get("pages", []))),
                "font_name_summary": _summarize_counter(payload.get("fonts", [])),
                "font_size_summary_pt": _summarize_counter(payload.get("font_sizes_pt", [])),
                "style_name_summary": _summarize_counter(payload.get("styles", [])),
                "alignment_summary": _summarize_counter(payload.get("alignments", [])),
                "bold_ratio": round(sum(1 for item in payload.get("bold", []) if item) / max(1, len(payload.get("bold", []))), 4),
                "italic_ratio": round(sum(1 for item in payload.get("italic", []) if item) / max(1, len(payload.get("italic", []))), 4),
            }
            for name, payload in components.items()
        },
    }


def extract_tex_fonts(path: Path) -> Dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    components: Dict[str, Dict[str, Any]] = {}

    body_font = None
    if re.search(r"\\setmainfont\{([^}]+)\}", text):
        body_font = re.search(r"\\setmainfont\{([^}]+)\}", text).group(1)
    elif re.search(r"\\usepackage\{(?:times|mathptmx)\}", text):
        body_font = "Times-compatible"

    heading_font = None
    heading_cmd = re.search(r"\\titleformat\{\\section\}\{([^}]+)\}", text)
    if heading_cmd:
        heading_font = heading_cmd.group(1)

    documentclass = re.search(r"\\documentclass(?:\[([^\]]*)\])?\{([^}]+)\}", text)
    body_size = None
    if documentclass and documentclass.group(1):
        size_match = re.search(r"(\d{1,2})pt", documentclass.group(1))
        if size_match:
            body_size = float(size_match.group(1))

    components["body"] = {
        "font_name_summary": _summarize_counter([body_font] if body_font else []),
        "font_size_summary_pt": _summarize_counter([body_size] if body_size else []),
        "sample_texts": [line.strip()[:80] for line in text.splitlines() if line.strip() and not line.lstrip().startswith("%")][:5],
    }
    components["heading"] = {
        "font_name_summary": _summarize_counter([heading_font] if heading_font else []),
        "font_size_summary_pt": [],
        "sample_texts": re.findall(r"\\(?:section|subsection|chapter)\{([^}]+)\}", text)[:5],
    }
    components["caption"] = {
        "font_name_summary": [],
        "font_size_summary_pt": [],
        "sample_texts": re.findall(r"\\caption\{([^}]+)\}", text)[:5],
    }

    return {
        "file_type": "latex",
        "documentclass": documentclass.group(2) if documentclass else "",
        "components": components,
    }


def main(argv: List[str]) -> int:
    if len(argv) < 2:
        print("Usage: python scripts/extract_component_fonts.py <file_path>", file=sys.stderr)
        return 1

    path = Path(argv[1]).expanduser().resolve()
    if not path.exists():
        print(json.dumps({"error": f"文件不存在: {path}"}, ensure_ascii=False, indent=2))
        return 2

    suffix = path.suffix.lower()
    if suffix == ".docx":
        payload = extract_docx_fonts(path)
    elif suffix in {".tex", ".ltx"}:
        payload = extract_tex_fonts(path)
    else:
        payload = {
            "file_type": suffix.lstrip(".") or "unknown",
            "error": "当前脚本仅支持 docx / tex / ltx",
        }

    payload["file_path"] = str(path)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
