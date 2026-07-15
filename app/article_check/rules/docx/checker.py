"""
Word 格式检查器 — 基于 python-docx 的样式/格式规则引擎

支持检查:
- 标题样式层级
- 字体一致性
- 段落间距
- 页边距
- 图表编号连续性
- 页码格式

参考: validocx 项目的模板验证模式
"""
from __future__ import annotations
import logging
import re
from collections import Counter
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class DocxChecker:
    """
    Word (.docx) 格式检查器

    完全本地运行，零 token 成本。
    使用 python-docx 解析 XML 结构进行规则匹配。
    """

    SECTION_REQUIREMENTS = {
        "undergraduate": [
            ("cover_missing", "封面", ["封面", "论文封面"], "major"),
            ("abstract_missing", "中文摘要", ["摘要", "摘 要"], "major"),
            ("en_abstract_missing", "英文摘要", ["英文摘要", "abstract"], "major"),
            ("keyword_missing", "关键词", ["关键词", "key words", "keywords"], "minor"),
            ("catalog_missing", "目录", ["目录"], "minor"),
            ("introduction_missing", "引言", ["引言", "前言", "绪论", "introduction"], "minor"),
            ("conclusion_missing", "结论", ["结论", "结语", "总结", "conclusion"], "minor"),
            ("reference_missing", "参考文献", ["参考文献", "references", "bibliography"], "major"),
        ],
        "graduate": [
            ("cover_missing", "封面", ["封面"], "major"),
            ("title_page_missing", "题名页", ["题名页"], "major"),
            ("copyright_missing", "版权页", ["版权页"], "major"),
            ("abstract_missing", "中文摘要", ["摘要", "摘 要"], "major"),
            ("en_abstract_missing", "外文摘要", ["英文摘要", "外文摘要", "abstract"], "major"),
            ("keyword_missing", "关键词", ["关键词", "key words", "keywords"], "minor"),
            ("catalog_missing", "目录", ["目录"], "minor"),
            ("reference_missing", "参考文献", ["参考文献", "references", "bibliography"], "major"),
        ],
    }
    COVER_EXCLUDE_MARKERS = {
        "本人承诺", "学生签名", "论文使用授权说明", "诚信承诺书", "原创性声明", "使用授权说明",
    }
    STATEMENT_MARKERS = {
        "诚信承诺书", "论文使用授权说明", "原创性声明", "使用授权说明",
    }

    def __init__(
        self,
        template_path: Optional[str] = None,
        *,
        review_track: str = "auto",
        rule_profile: Optional[Dict[str, Any]] = None,
    ):
        self.template_path = template_path
        self.review_track = review_track or "auto"
        self.rule_profile = rule_profile or {}

    def check(self, file_path: str) -> List[Dict[str, Any]]:
        """执行 Word 格式检查"""
        try:
            from docx import Document
        except ImportError:
            logger.error("python-docx 未安装。执行: pip install python-docx")
            return [{
                "type": "dependency_error",
                "description": "python-docx 未安装，无法检查 Word 格式",
                "severity": "critical",
                "suggestion": "执行 pip install python-docx"
            }]

        issues = []
        doc = Document(file_path)

        # 1. 检查标题样式层级
        self._check_headings(doc, issues)

        # 2. 检查字体一致性
        self._check_fonts(doc, issues)

        # 3. 检查页边距
        self._check_page_margins(doc, issues)

        # 4. 检查封面关键元素
        self._check_cover_page_layout(doc, issues)

        # 5. 检查基础结构完整性
        self._check_required_sections(doc, issues)

        # 6. 检查摘要和关键词规则
        self._check_abstract_and_keywords(doc, issues)

        # 7. 检查字号
        self._check_font_sizes(doc, issues)

        # 8. 检查段落间距与行距
        self._check_paragraph_spacing(doc, issues)

        # 9. 检查图表标题位置
        self._check_caption_positions(doc, issues)

        # 10. 检查图表编号
        self._check_figure_table_numbering(doc, issues)

        return issues

    def _check_headings(self, doc, issues: List[Dict]):
        """检查标题样式是否连续"""
        seen_headings = []
        for line_no, para in enumerate(doc.paragraphs, start=1):
            text = para.text.strip()
            if not text:
                continue
            style_name = para.style.name if para.style else ""
            level = self._infer_heading_level(text, style_name)
            if not level:
                continue
            seen_headings.append({
                "text": text[:80],
                "level": level,
                "style": style_name or "heuristic",
                "line": line_no,
            })

        # 检查是否有跳级（如 Heading 1 → Heading 3）
        for i in range(1, len(seen_headings)):
            prev = seen_headings[i - 1]["level"]
            curr = seen_headings[i]["level"]
            if curr > prev + 1:
                issues.append({
                    "type": "heading_skip",
                    "line": seen_headings[i]["line"],
                    "severity": "minor",
                    "description": f"标题层级跳跃: '{seen_headings[i-1]['text']}' (H{prev}) → '{seen_headings[i]['text']}' (H{curr})",
                    "suggestion": "在中间添加 H{} 级别的标题".format(prev + 1),
                })

    def _check_required_sections(self, doc, issues: List[Dict]):
        """检查 DOCX 是否包含基础论文结构。"""
        text = "\n".join(item.get("text", "") for item in self._iter_doc_blocks_with_pages(doc) if item.get("text"))
        normalized = self._normalize_text(text)
        required_sections = self.SECTION_REQUIREMENTS.get(
            self.review_track,
            [
                ("abstract_missing", "摘要", ["摘要", "摘 要", "abstract"], "major"),
                ("keyword_missing", "关键词", ["关键词", "key words", "keywords"], "minor"),
                ("introduction_missing", "引言", ["引言", "前言", "绪论", "introduction"], "minor"),
                ("reference_missing", "参考文献", ["参考文献", "references", "bibliography"], "major"),
            ],
        )

        for issue_type, label, aliases, severity in required_sections:
            if issue_type == "cover_missing":
                cover_state = self._detect_cover_state(doc)
                if cover_state == "present":
                    continue
                if cover_state == "uncertain":
                    issues.append({
                        "type": "cover_manual_confirmation",
                        "severity": "minor",
                        "description": "首页疑似为封面，但自动识别不够稳定，建议人工确认。",
                        "suggestion": "请人工确认第一页是否为封面，并核对题名、作者、导师等字段是否齐全。",
                    })
                    continue
            if issue_type in {"copyright_missing", "title_page_missing"} and self._contains_statement_page(normalized):
                continue
            if any(self._normalize_text(alias) in normalized for alias in aliases):
                continue
            issues.append({
                "type": issue_type,
                "severity": severity,
                "description": f"文档中未识别到“{label}”部分。",
                "suggestion": f"请补充或显式标注“{label}”部分标题。",
            })

    def _check_abstract_and_keywords(self, doc, issues: List[Dict]):
        """检查摘要字数与关键词数量。"""
        abstract_text = self._extract_section_text(doc, ["摘要", "摘 要", "abstract"], stop_aliases=["关键词", "key words", "keywords", "目录", "引言", "绪论"])
        keyword_text = self._extract_section_text(doc, ["关键词", "key words", "keywords"], stop_aliases=["目录", "引言", "绪论"])

        abstract_rules = self.rule_profile.get("abstract_rules") or {}
        keyword_rules = self.rule_profile.get("keyword_rules") or {}

        if abstract_text:
            abstract_length = len(re.sub(r"\s+", "", abstract_text))
            if self.review_track == "undergraduate":
                target_chars = abstract_rules.get("zh_abstract_target_chars")
                if target_chars and abs(abstract_length - int(target_chars)) > 180:
                    issues.append({
                        "type": "abstract_length_deviation",
                        "severity": "minor",
                        "description": f"中文摘要约 {abstract_length} 字，明显偏离本科摘要目标 {target_chars} 字。",
                        "suggestion": "请按学校规范补足或压缩摘要，确保包含研究目的、方法与结论。",
                    })
            elif self.review_track == "graduate":
                target_chars = abstract_rules.get("master_zh_target_chars") or abstract_rules.get("doctoral_zh_target_chars")
                if target_chars and abstract_length < int(target_chars) * 0.6:
                    issues.append({
                        "type": "abstract_too_short",
                        "severity": "major",
                        "description": f"中文摘要约 {abstract_length} 字，低于研究生摘要建议长度 {target_chars} 字。",
                        "suggestion": "建议补充研究目的、方法、结果、结论与创新点，形成更完整的学位论文摘要。",
                    })

        if keyword_text:
            separators = re.split(r"[，,;；、\s]+", keyword_text)
            keywords = [item for item in separators if item and item not in {"关键词", "Keywords", "keywords", "Key", "Words"}]
            min_keywords = int(keyword_rules.get("min_keywords", 3))
            max_keywords = int(keyword_rules.get("max_keywords", 8))
            if len(keywords) < min_keywords or len(keywords) > max_keywords:
                issues.append({
                    "type": "keyword_count_invalid",
                    "severity": "minor",
                    "description": f"当前识别到 {len(keywords)} 个关键词，超出规则范围 {min_keywords}-{max_keywords}。",
                    "suggestion": "请按学校规范调整关键词数量，并使用统一分隔符。",
                })

    def _check_page_margins(self, doc, issues: List[Dict]):
        """检查页面边距是否统一且接近论文常用值。"""
        target_cm = self._get_target_margins_cm()
        tolerance_cm = 0.3

        for index, section in enumerate(doc.sections, start=1):
            margins = {
                "top": section.top_margin.cm if section.top_margin else None,
                "bottom": section.bottom_margin.cm if section.bottom_margin else None,
                "left": section.left_margin.cm if section.left_margin else None,
                "right": section.right_margin.cm if section.right_margin else None,
            }
            for side, value in margins.items():
                if value is None:
                    continue
                if abs(value - target_cm[side]) > tolerance_cm:
                    issues.append({
                        "type": "page_margin_deviation",
                        "severity": "major",
                        "description": f"第 {index} 节的{self._margin_label(side)}为 {value:.2f} cm，偏离常见论文版式 {target_cm[side]:.1f} cm。",
                        "suggestion": "请在页面设置中统一页边距，避免不同章节版式漂移。",
                    })

    def _check_cover_page_layout(self, doc, issues: List[Dict]):
        """只检查第一页封面区域，避免把声明页和摘要页误当成封面。"""
        blocks = self._iter_doc_blocks_with_pages(doc)
        cover_blocks = [block for block in blocks if block.get("page") == 1 and self._is_cover_candidate_text(block.get("text", ""))]
        if not cover_blocks:
            return

        paragraph_blocks = [block for block in cover_blocks if block.get("kind") == "paragraph"]
        if not paragraph_blocks:
            return

        title_block = next(
            (
                block for block in paragraph_blocks
                if not self._looks_like_author_line(block.get("text", ""))
                and not re.search(r"(大学|学院|学校|导师|指导教师|专业|学号)", block.get("text", ""))
                and len(block.get("text", "")) >= 6
            ),
            paragraph_blocks[0],
        )
        title_line = title_block.get("line")
        title_para = title_block.get("obj")
        title_text = title_block.get("text", "").strip()
        title_size = self._get_paragraph_font_size(title_para) if title_para is not None else None
        if title_line > 3:
            issues.append({
                "type": "cover_title_position",
                "severity": "minor",
                "line": title_line,
                "description": "首页题名未出现在文档开头区域。",
                "suggestion": "将论文题名置于首页靠前位置，保持封面层次清晰。",
            })
        if title_para is not None and title_para.alignment != 1:
            issues.append({
                "type": "cover_title_alignment",
                "severity": "major",
                "line": title_line,
                "description": f"首页题名“{title_text[:24]}”未居中。",
                "suggestion": "将论文题名设置为居中排版。",
            })
        min_title_size = 18 if self.review_track == "graduate" else 16
        if title_size is not None and title_size < min_title_size:
            issues.append({
                "type": "cover_title_size",
                "severity": "minor",
                "line": title_line,
                "description": f"首页题名字号约为 {title_size:.1f} pt，偏小。",
                "suggestion": "适当增大题名字号，突出首页主标题层级。",
            })

        institution_found = False
        author_found = False
        advisor_found = False
        for block in cover_blocks:
            if block is title_block:
                continue
            text = block.get("text", "").strip()
            para = block.get("obj")
            line_no = block.get("line")
            normalized = self._normalize_text(text)
            if any(marker in normalized for marker in map(self._normalize_text, self.COVER_EXCLUDE_MARKERS)):
                continue
            if re.search(r"(大学|学院|学校)", text):
                institution_found = True
                if para is not None and para.alignment != 1:
                    issues.append({
                        "type": "cover_institution_alignment",
                        "severity": "minor",
                        "line": line_no,
                        "description": f"首页机构信息“{text[:24]}”未居中。",
                        "suggestion": "将学校/学院信息与题名保持统一居中。",
                    })
            if re.search(r"(指导教师|导师|教授|副教授|讲师)", text):
                advisor_found = True
                if para is not None and para.alignment != 1:
                    issues.append({
                        "type": "cover_advisor_alignment",
                        "severity": "minor",
                        "line": line_no,
                        "description": f"首页导师信息“{text[:24]}”未居中。",
                        "suggestion": "将导师信息置于封面信息区并与其他元素对齐。",
                    })
            if self._looks_like_author_line(text):
                author_found = True
                if para is not None and para.alignment != 1:
                    issues.append({
                        "type": "cover_author_alignment",
                        "severity": "minor",
                        "line": line_no,
                        "description": f"首页作者信息“{text[:24]}”未居中。",
                        "suggestion": "将作者/署名信息与题名、机构信息保持统一对齐。",
                    })

        if not institution_found:
            issues.append({
                "type": "cover_institution_missing",
                "severity": "minor",
                "description": "首页未识别到学校或学院信息。",
                "suggestion": "建议在封面或首页显式标注学校、学院等归属信息。",
            })
        if not author_found:
            issues.append({
                "type": "cover_author_missing",
                "severity": "minor",
                "description": "首页未识别到明确的作者/署名信息。",
                "suggestion": "建议在首页补充作者姓名、学号或署名区。",
            })
        if not advisor_found:
            issues.append({
                "type": "cover_advisor_missing",
                "severity": "minor",
                "description": "首页未识别到指导教师或导师信息。",
                "suggestion": "若学校模板要求首页展示导师信息，请补充对应字段。",
            })

    def _check_fonts(self, doc, issues: List[Dict]):
        """检查字体一致性"""
        fonts_seen = set()
        for para in doc.paragraphs:
            for run in para.runs:
                if run.font.name:
                    fonts_seen.add(run.font.name)

        if len(fonts_seen) > 3:
            issues.append({
                "type": "font_inconsistency",
                "severity": "minor",
                "description": f"文档使用了 {len(fonts_seen)} 种不同字体: {', '.join(fonts_seen)}",
                "suggestion": "建议全文字体保持一致（正文一种，标题一种）",
            })

    def _check_font_sizes(self, doc, issues: List[Dict]):
        """检查正文、标题和图题字号是否明显失衡。"""
        body_sizes = []
        heading_sizes = []
        caption_sizes = []

        for para in doc.paragraphs:
            text = para.text.strip()
            if not text:
                continue
            size = self._get_paragraph_font_size(para)
            if size is None:
                continue

            if self._is_caption(text):
                caption_sizes.append(size)
                continue
            if self._infer_heading_level(text, para.style.name if para.style else ""):
                heading_sizes.append(size)
                continue
            if len(text) >= 20:
                body_sizes.append(size)

        dominant_body_size = self._dominant_value(body_sizes, precision=1)
        if dominant_body_size is None:
            return

        heading_below_body = [size for size in heading_sizes if size <= dominant_body_size]
        if heading_below_body:
            issues.append({
                "type": "heading_font_size_weak",
                "severity": "minor",
                "description": f"部分标题字号未明显大于正文字号（正文主流约 {dominant_body_size:.1f} pt）。",
                "suggestion": "建议至少让一级/二级标题与正文形成稳定字号层级。",
            })

        body_outliers = [size for size in body_sizes if abs(size - dominant_body_size) > 1.2]
        if len(body_outliers) >= 3:
            issues.append({
                "type": "body_font_size_inconsistency",
                "severity": "minor",
                "description": f"正文主流字号约为 {dominant_body_size:.1f} pt，但存在 {len(body_outliers)} 处明显偏离。",
                "suggestion": "统一正文字号，避免不同段落出现不必要的视觉跳变。",
            })

        if caption_sizes:
            dominant_caption_size = self._dominant_value(caption_sizes, precision=1)
            if dominant_caption_size and dominant_caption_size > dominant_body_size + 1:
                issues.append({
                    "type": "caption_font_size_large",
                    "severity": "minor",
                    "description": f"图表标题主流字号约为 {dominant_caption_size:.1f} pt，明显大于正文 {dominant_body_size:.1f} pt。",
                    "suggestion": "图表标题宜略小于或接近正文，避免压过正文视觉层级。",
                })

    def _check_paragraph_spacing(self, doc, issues: List[Dict]):
        """检查段落间距和正文行距一致性。"""
        spacings = []
        body_line_spacings = []
        for para in doc.paragraphs:
            text = para.text.strip()
            if not text:
                continue
            pf = para.paragraph_format
            if pf.space_before or pf.space_after:
                spacings.append({
                    "before": pf.space_before.pt if pf.space_before else 0,
                    "after": pf.space_after.pt if pf.space_after else 0,
                })

            if len(text) >= 20 and not self._is_caption(text) and not self._infer_heading_level(text, para.style.name if para.style else ""):
                line_spacing_pt = self._get_line_spacing_value(para)
                if line_spacing_pt is not None:
                    body_line_spacings.append(line_spacing_pt)

        if len(spacings) > 5:
            unique_before = set(s["before"] for s in spacings)
            unique_after = set(s["after"] for s in spacings)
            if len(unique_before) > 3:
                issues.append({
                    "type": "spacing_inconsistency",
                    "severity": "minor",
                    "description": f"段落前间距存在 {len(unique_before)} 种不同值: {unique_before}",
                    "suggestion": "统一段落前间距",
                })

        dominant_line_spacing = self._dominant_value(body_line_spacings, precision=1)
        if dominant_line_spacing is not None:
            line_outliers = [value for value in body_line_spacings if abs(value - dominant_line_spacing) > 1.5]
            if len(line_outliers) >= 3:
                issues.append({
                    "type": "line_spacing_inconsistency",
                    "severity": "minor",
                    "description": f"正文主流行距约为 {dominant_line_spacing:.1f} pt，但存在 {len(line_outliers)} 处明显偏离。",
                    "suggestion": "统一正文行距，避免不同章节密度不一致。",
                })

    def _check_caption_positions(self, doc, issues: List[Dict]):
        """检查图题表题的相对位置与对齐。"""
        blocks = self._iter_body_blocks(doc)
        for index, block in enumerate(blocks):
            if block["kind"] != "paragraph":
                continue

            para = block["obj"]
            text = para.text.strip()
            caption_kind = self._caption_kind(text)
            if not caption_kind:
                continue

            if para.alignment != 1:
                issues.append({
                    "type": f"{caption_kind}_caption_alignment",
                    "severity": "minor",
                    "line": block["line"],
                    "description": f"{caption_kind.upper()} 标题“{text[:24]}”未居中。",
                    "suggestion": "建议将图题/表题与对象保持统一居中排版。",
                })

            prev_block = blocks[index - 1] if index > 0 else None
            next_block = blocks[index + 1] if index + 1 < len(blocks) else None

            if caption_kind == "figure":
                has_inline_figure = self._paragraph_has_drawing(para)
                prev_drawing = self._find_nearest_paragraph(blocks, index, direction=-1, max_steps=2)
                next_drawing = self._find_nearest_paragraph(blocks, index, direction=1, max_steps=2)

                if has_inline_figure:
                    continue
                if prev_drawing and self._paragraph_has_drawing(prev_drawing["obj"]):
                    continue
                if next_drawing and self._paragraph_has_drawing(next_drawing["obj"]):
                    issues.append({
                        "type": "figure_caption_position",
                        "severity": "minor",
                        "line": block["line"],
                        "description": f"图题“{text[:24]}”位于图形对象上方或未置于图后。",
                        "suggestion": "图题通常应放在图片下方，并与图片相邻。",
                    })
                else:
                    issues.append({
                        "type": "figure_caption_detached",
                        "severity": "minor",
                        "line": block["line"],
                        "description": f"图题“{text[:24]}”未与相邻图片形成对应关系。",
                        "suggestion": "请检查图题与图片是否紧邻，避免跨页或夹杂正文。",
                    })
            if caption_kind == "table":
                if not (next_block and next_block["kind"] == "table"):
                    if prev_block and prev_block["kind"] == "table":
                        issues.append({
                            "type": "table_caption_position",
                            "severity": "major",
                            "line": block["line"],
                            "description": f"表题“{text[:24]}”位于表格下方。",
                            "suggestion": "中文论文通常要求表题置于表格上方。",
                        })
                    else:
                        issues.append({
                            "type": "table_caption_detached",
                            "severity": "minor",
                            "line": block["line"],
                            "description": f"表题“{text[:24]}”未与相邻表格形成对应关系。",
                            "suggestion": "请检查表题与表格是否紧邻，并避免跨页或夹杂正文。",
                        })

    def _check_figure_table_numbering(self, doc, issues: List[Dict]):
        """检查图表编号连续性"""
        figure_nums = []
        table_nums = []
        for para in doc.paragraphs:
            text = para.text.strip()
            caption_kind = self._caption_kind(text)
            caption_number = self._caption_number(text)
            if not caption_kind or caption_number is None:
                continue
            if caption_kind == "figure":
                figure_nums.append(caption_number)
            elif caption_kind == "table":
                table_nums.append(caption_number)

        # 简单的连续性检查
        if figure_nums or table_nums:
            issues.append({
                "type": "figure_table_count",
                "severity": "info",
                "description": f"文档包含 {len(figure_nums)} 个图题、{len(table_nums)} 个表题",
                "suggestion": "",
            })

        self._append_numbering_issue("图", figure_nums, issues)
        self._append_numbering_issue("表", table_nums, issues)

    def _infer_heading_level(self, text: str, style_name: str) -> Optional[int]:
        if style_name.startswith("Heading"):
            level = style_name.replace("Heading", "")
            return int(level) if level.isdigit() else 1

        candidate = text.strip()
        normalized = self._normalize_text(candidate).rstrip(":：")
        if not candidate or len(candidate) > 80:
            return None

        if normalized in {"摘要", "摘 要", "abstract", "关键词", "目录", "引言", "前言", "绪论", "结论", "结语", "参考文献", "references"}:
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

    def _normalize_text(self, value: str) -> str:
        return re.sub(r"\s+", "", str(value or "")).lower()

    def _get_paragraph_font_size(self, para) -> Optional[float]:
        sizes = []
        for run in para.runs:
            if run.font.size:
                sizes.append(run.font.size.pt)
        if sizes:
            return round(sum(sizes) / len(sizes), 1)
        if para.style and para.style.font.size:
            return round(para.style.font.size.pt, 1)
        return None

    def _get_line_spacing_value(self, para) -> Optional[float]:
        spacing = para.paragraph_format.line_spacing
        if spacing is None:
            return None
        if hasattr(spacing, "pt"):
            return round(spacing.pt, 1)
        if isinstance(spacing, (int, float)):
            if spacing > 50:
                return round(spacing / 12700, 1)
            return round(float(spacing), 1)
        return None

    def _dominant_value(self, values: List[float], precision: int = 1) -> Optional[float]:
        if not values:
            return None
        rounded = [round(value, precision) for value in values if value is not None]
        if not rounded:
            return None
        return Counter(rounded).most_common(1)[0][0]

    def _paragraph_has_drawing(self, para) -> bool:
        return bool(para._element.xpath('.//*[local-name()="drawing" or local-name()="pict"]'))

    def _iter_body_blocks(self, doc) -> List[Dict[str, Any]]:
        para_map = {id(para._p): (line_no, para) for line_no, para in enumerate(doc.paragraphs, start=1)}
        table_map = {id(table._tbl): table for table in doc.tables}
        blocks: List[Dict[str, Any]] = []

        for child in doc.element.body.iterchildren():
            tag = child.tag.split("}")[-1]
            if tag == "p" and id(child) in para_map:
                line_no, para = para_map[id(child)]
                blocks.append({"kind": "paragraph", "obj": para, "line": line_no})
            elif tag == "tbl" and id(child) in table_map:
                blocks.append({"kind": "table", "obj": table_map[id(child)]})

        return blocks

    def _caption_kind(self, text: str) -> Optional[str]:
        candidate = text.strip()
        if re.match(r"^(图|Figure)\s*\d+", candidate, re.IGNORECASE):
            return "figure"
        if re.match(r"^(表|Table)\s*\d+", candidate, re.IGNORECASE):
            return "table"
        return None

    def _caption_number(self, text: str) -> Optional[int]:
        match = re.match(r"^(?:图|表|Figure|Table)\s*(\d+)", text.strip(), re.IGNORECASE)
        return int(match.group(1)) if match else None

    def _is_caption(self, text: str) -> bool:
        return self._caption_kind(text) is not None

    def _append_numbering_issue(self, label: str, numbers: List[int], issues: List[Dict]):
        if len(numbers) < 2:
            return
        expected = list(range(1, max(numbers) + 1))
        if sorted(numbers) != expected:
            issues.append({
                "type": f"{label}_numbering_inconsistency",
                "severity": "minor",
                "description": f"{label}题编号存在跳号或重复：{numbers}",
                "suggestion": f"请统一{label}题编号顺序，确保从 1 开始连续编号。",
            })

    def _looks_like_author_line(self, text: str) -> bool:
        if re.search(r"(作者|姓名|学号|学生)", text):
            return True
        return bool(re.search(r"[\u4e00-\u9fff]{2,4}[，,、 ][\u4e00-\u9fff]{2,4}", text))

    def _margin_label(self, side: str) -> str:
        return {
            "top": "上边距",
            "bottom": "下边距",
            "left": "左边距",
            "right": "右边距",
        }.get(side, side)

    def _get_target_margins_cm(self) -> Dict[str, float]:
        page_layout = self.rule_profile.get("page_layout") or {}
        if self.review_track == "graduate":
            return {
                "top": float(page_layout.get("body_margin_top_cm", 2.54)),
                "bottom": float(page_layout.get("body_margin_bottom_cm", 2.54)),
                "left": float(page_layout.get("body_margin_left_cm", 3.17)),
                "right": float(page_layout.get("body_margin_right_cm", 3.17)),
            }
        return {
            "top": float(page_layout.get("margin_top_mm", 25)) / 10,
            "bottom": float(page_layout.get("margin_bottom_mm", 20)) / 10,
            "left": float(page_layout.get("margin_left_mm", 25)) / 10,
            "right": float(page_layout.get("margin_right_mm", 20)) / 10,
        }

    def _find_nearest_paragraph(self, blocks: List[Dict[str, Any]], index: int, direction: int, max_steps: int = 2) -> Optional[Dict[str, Any]]:
        steps = 0
        cursor = index + direction
        while 0 <= cursor < len(blocks) and steps < max_steps:
            block = blocks[cursor]
            if block["kind"] == "paragraph":
                text = block["obj"].text.strip()
                if text or self._paragraph_has_drawing(block["obj"]):
                    return block
                steps += 1
            cursor += direction
        return None

    def _extract_section_text(self, doc, aliases: List[str], stop_aliases: Optional[List[str]] = None) -> str:
        collected: List[str] = []
        in_section = False
        stop_aliases = stop_aliases or []
        normalized_aliases = {self._normalize_text(alias) for alias in aliases}
        normalized_stops = {self._normalize_text(alias) for alias in stop_aliases}

        for block in self._iter_doc_blocks_with_pages(doc):
            text = block.get("text", "").strip()
            if not text:
                continue
            normalized = self._normalize_text(text).rstrip(":：")
            if normalized in normalized_aliases:
                in_section = True
                continue
            if in_section and normalized in normalized_stops:
                break
            if in_section:
                collected.append(text)
        return "\n".join(collected).strip()

    def _iter_doc_blocks_with_pages(self, doc) -> List[Dict[str, Any]]:
        para_map = {id(para._p): (line_no, para) for line_no, para in enumerate(doc.paragraphs, start=1)}
        table_map = {id(table._tbl): table for table in doc.tables}
        blocks: List[Dict[str, Any]] = []
        current_page = 1

        for child in doc.element.body.iterchildren():
            tag = child.tag.split("}")[-1]
            if tag == "p" and id(child) in para_map:
                line_no, para = para_map[id(child)]
                if para.paragraph_format and para.paragraph_format.page_break_before and blocks:
                    current_page += 1
                text = para.text.strip()
                if text:
                    blocks.append({"kind": "paragraph", "obj": para, "line": line_no, "page": current_page, "text": text})
                if self._paragraph_starts_new_page_after(para):
                    current_page += 1
            elif tag == "tbl" and id(child) in table_map:
                table = table_map[id(child)]
                row_texts = []
                for row in table.rows:
                    cells = [" ".join(p.text.strip() for p in cell.paragraphs if p.text and p.text.strip()) for cell in row.cells]
                    text = " | ".join(item.strip() for item in cells if item and item.strip()).strip()
                    if text:
                        row_texts.append(text)
                table_text = "\n".join(row_texts).strip()
                if table_text:
                    blocks.append({"kind": "table", "obj": table, "line": None, "page": current_page, "text": table_text})
        return blocks

    def _paragraph_starts_new_page_after(self, para) -> bool:
        if para._element.xpath('./*[local-name()="pPr"]/*[local-name()="sectPr"]'):
            return True
        return bool(para._element.xpath('.//*[local-name()="br" and @*[local-name()="type"]="page"]'))

    def _is_cover_candidate_text(self, text: str) -> bool:
        normalized = self._normalize_text(text)
        if not normalized:
            return False
        if normalized in {"摘要", "摘要：", "abstract", "关键词", "目录", "引言", "前言", "绪论"}:
            return False
        if any(marker in normalized for marker in map(self._normalize_text, self.STATEMENT_MARKERS)):
            return False
        return True

    def _contains_statement_page(self, normalized_text: str) -> bool:
        return any(marker in normalized_text for marker in map(self._normalize_text, self.STATEMENT_MARKERS))

    def _detect_cover_state(self, doc) -> str:
        blocks = [block for block in self._iter_doc_blocks_with_pages(doc) if block.get("page") == 1 and self._is_cover_candidate_text(block.get("text", ""))]
        if not blocks:
            return "missing"
        joined = "\n".join(block.get("text", "") for block in blocks)
        field_hits = sum(
            1 for marker in ["大学", "学院", "论文", "姓名", "学号", "导师", "指导教师", "专业"]
            if marker in joined
        )
        title_hits = len(re.findall(r"[\u4e00-\u9fff]{4,}", joined))
        if field_hits >= 3 and title_hits >= 2:
            return "present"
        if field_hits >= 2:
            return "uncertain"
        return "missing"
