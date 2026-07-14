"""
格式模板 — 定义学术论文/期刊的格式规范

每个模板描述一种期刊或论文类别的完整格式要求，
规则引擎根据这些规范进行自动校验。

支持:
- LaTeX 模板 (IEEE/ACM/Elsevier/Springer LNCS 等)
- Word 模板 (毕业论文/学位论文/期刊投稿 等)
- 自定义模板
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ─── 基本约束类型 ─────────────────────────────────────

@dataclass
class PageConstraint:
    """页面布局约束"""
    paper_size: str = "A4"  # A4 / Letter
    margin_top_mm: float = 25.4
    margin_bottom_mm: float = 25.4
    margin_left_mm: float = 25.4
    margin_right_mm: float = 25.4
    line_spacing: float = 2.0  # double spacing
    page_numbers: bool = True


@dataclass
class FontConstraint:
    """字体约束"""
    body_font: str = "Times New Roman"
    body_size_pt: float = 12
    heading_font: str = "Times New Roman"
    heading_sizes: Dict[int, float] = field(default_factory=lambda: {
        1: 16, 2: 14, 3: 12,
    })
    mono_font: str = "Courier New"
    mono_size_pt: float = 10


@dataclass
class SectionConstraint:
    """章节结构约束"""
    required_sections: List[str] = field(default_factory=lambda: [
        "abstract", "introduction", "method", "experiment",
        "result", "discussion", "conclusion", "reference",
    ])
    max_abstract_words: int = 300
    section_numbering: bool = True
    max_section_depth: int = 3  # 1.1.1


@dataclass
class FigureTableConstraint:
    """图表约束"""
    figure_max_count: Optional[int] = None
    table_max_count: Optional[int] = None
    need_caption: bool = True
    need_numbering: bool = True
    caption_style: str = "above"  # above / below


@dataclass
class ReferenceConstraint:
    """参考文献约束"""
    ref_format: str = "ieee"  # ieee / apa / mla / chicago / nature
    min_refs: int = 10
    max_refs: Optional[int] = None
    citation_style: str = "numeric"  # numeric / author_year
    need_doi: bool = False


@dataclass
class TitlePageConstraint:
    """封面/标题页约束"""
    title_max_words: int = 20
    need_author_affiliation: bool = True
    need_abstract: bool = True
    need_keywords: bool = True
    keywords_max: int = 6


@dataclass
class FormatTemplate:
    """
    完整的格式模板定义

    使用示例:
        ieee_template = FormatTemplate(
            name="IEEE Transactions",
            page=PageConstraint(paper_size="Letter", ...),
            font=FontConstraint(body_font="Times New Roman", body_size_pt=10),
            ...
        )
    """
    name: str                         # 模板名称，如 "IEEE Transactions"
    version: str = "1.0"
    description: str = ""
    category: str = "journal"         # journal / conference / thesis / report

    # 约束分组
    page: PageConstraint = field(default_factory=PageConstraint)
    font: FontConstraint = field(default_factory=FontConstraint)
    section: SectionConstraint = field(default_factory=SectionConstraint)
    figures: FigureTableConstraint = field(default_factory=FigureTableConstraint)
    references: ReferenceConstraint = field(default_factory=ReferenceConstraint)
    title_page: TitlePageConstraint = field(default_factory=TitlePageConstraint)

    # LaTeX 特定约束（可选）
    latex_packages: List[str] = field(default_factory=list)
    latex_class: Optional[str] = None

    # Word 特定约束（可选）
    heading_styles: Dict[int, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        import dataclasses
        return dataclasses.asdict(self)


# ─── 预定义模板 ────────────────────────────────────────

# IEEE Transactions 模板
IEEE_TEMPLATE = FormatTemplate(
    name="IEEE Transactions",
    category="journal",
    description="IEEE Transactions 系列期刊标准格式",
    page=PageConstraint(
        paper_size="Letter",
        margin_top_mm=19.05,
        margin_bottom_mm=19.05,
        margin_left_mm=17.78,
        margin_right_mm=17.78,
        line_spacing=1.0,
        page_numbers=True,
    ),
    font=FontConstraint(
        body_font="Times New Roman",
        body_size_pt=10,
        heading_font="Times New Roman",
        heading_sizes={1: 10, 2: 10, 3: 10},
    ),
    section=SectionConstraint(
        required_sections=["abstract", "introduction", "conclusion", "reference"],
        section_numbering=True,
        max_section_depth=3,
    ),
    references=ReferenceConstraint(
        ref_format="ieee",
        citation_style="numeric",
        min_refs=10,
    ),
    title_page=TitlePageConstraint(
        need_abstract=True,
        need_keywords=True,
        keywords_max=6,
    ),
    latex_class="IEEEtran",
    latex_packages=["cite", "amsmath", "graphicx"],
)

# Elsevier 模板
ELSEVIER_TEMPLATE = FormatTemplate(
    name="Elsevier",
    category="journal",
    description="Elsevier 旗下期刊标准格式",
    page=PageConstraint(
        paper_size="A4",
        line_spacing=1.5,
    ),
    font=FontConstraint(
        body_font="Times New Roman",
        body_size_pt=12,
    ),
    references=ReferenceConstraint(
        ref_format="elsevier",
        citation_style="numeric",
        min_refs=15,
    ),
    section=SectionConstraint(
        required_sections=["abstract", "introduction", "method",
                           "result", "discussion", "conclusion", "reference"],
    ),
    title_page=TitlePageConstraint(
        need_abstract=True,
        need_keywords=True,
        keywords_max=8,
    ),
)

# ACM 模板
ACM_TEMPLATE = FormatTemplate(
    name="ACM Conference",
    category="conference",
    description="ACM 会议论文标准格式",
    page=PageConstraint(
        paper_size="Letter",
        margin_top_mm=19.05,
        margin_bottom_mm=19.05,
        margin_left_mm=17.78,
        margin_right_mm=17.78,
        line_spacing=1.0,
    ),
    font=FontConstraint(
        body_font="Times New Roman",
        body_size_pt=9,
        mono_font="Courier New",
        mono_size_pt=8,
    ),
    section=SectionConstraint(
        required_sections=["abstract", "introduction", "conclusion", "reference"],
        max_abstract_words=150,
        max_section_depth=3,
    ),
    references=ReferenceConstraint(
        ref_format="acm",
        citation_style="numeric",
        min_refs=10,
    ),
    title_page=TitlePageConstraint(
        title_max_words=20,
        need_abstract=True,
        need_keywords=True,
        keywords_max=3,
    ),
    latex_class="acmart",
    latex_packages=["amsmath", "graphicx"],
)

# Springer LNCS 模板
LNCS_TEMPLATE = FormatTemplate(
    name="Springer LNCS",
    category="conference",
    description="Springer Lecture Notes in Computer Science",
    page=PageConstraint(
        paper_size="A4",
        margin_top_mm=45.0,
        margin_bottom_mm=56.0,
        margin_left_mm=28.0,
        margin_right_mm=28.0,
        line_spacing=1.0,
        page_numbers=True,
    ),
    font=FontConstraint(
        body_font="Times New Roman",
        body_size_pt=10,
    ),
    section=SectionConstraint(
        max_abstract_words=200,
        section_numbering=True,
        max_section_depth=3,
    ),
    references=ReferenceConstraint(
        ref_format="springer",
        citation_style="numeric",
        min_refs=10,
    ),
    latex_class="llncs",
    latex_packages=["amsmath", "graphicx"],
)
