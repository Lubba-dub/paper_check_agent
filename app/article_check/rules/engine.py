"""
模板规则引擎 — 将格式模板转化为具体的检查规则

核心逻辑:
1. 根据模板定义，生成检查规则列表
2. 每一条规则对应一个具体的、可执行的检查函数
3. 对论文执行检查 → 返回违规列表

流程:
  template.tex + FormatTemplate → TemplateRuleEngine.check()
                                      → 规则列表
                                      → 逐条执行
                                      → List[FormatIssue]
"""
from __future__ import annotations
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable

from article_check.rules.template import FormatTemplate
from article_check.rules.registry import template_registry

logger = logging.getLogger(__name__)


# ─── 规则函数类型 ─────────────────────────────────────

RuleFunc = Callable[[FormatTemplate, Path, str], List[Dict[str, Any]]]
"""规则函数签名: (template, file_path, file_text) → issues"""


class TemplateRuleEngine:
    """
    模板规则引擎

    将 FormatTemplate 定义转换为可执行的检查规则，
    对论文文件逐条运行，输出违规列表。
    """

    def __init__(self):
        self._rules: List[RuleFunc] = []
        self._register_builtin_rules()

    def _register_builtin_rules(self):
        """注册内置检查规则"""
        self._rules = [
            # 页面布局
            _check_line_spacing,
            _check_margins,
            _check_page_numbers,

            # 字体
            _check_body_font,
            _check_font_sizes,
            _check_mono_font,

            # 章节结构
            _check_required_sections,
            _check_abstract_word_count,
            _check_section_numbering,

            # 图表
            _check_figure_captions,
            _check_table_captions,

            # 文献
            _check_reference_count,
            _check_citation_format,

            # 标题页
            _check_abstract_presence,
            _check_keywords_presence,

            # LaTeX 特定
            _check_latex_class,
            _check_latex_packages,

            # Word 特定
            _check_heading_styles,
        ]
        logger.info(f"模板规则引擎已加载 {len(self._rules)} 条规则")

    def register_rule(self, rule: RuleFunc):
        """注册自定义规则"""
        self._rules.append(rule)
        logger.debug(f"自定义规则已注册: {rule.__name__}")

    def check(
        self,
        template_name: str,
        file_path: Path,
        file_type: str,
    ) -> List[Dict[str, Any]]:
        """
        按模板规范检查论文格式

        Args:
            template_name: 模板名称（如 "IEEE Transactions"）
            file_path: 论文文件路径
            file_type: 文件类型 (latex/docx)

        Returns:
            格式问题列表
        """
        template = template_registry.get(template_name)
        if not template:
            available = [t.name for t in template_registry.list_all()]
            return [{
                "type": "template_not_found",
                "severity": "critical",
                "description": f"未找到模板 '{template_name}'。可用模板: {', '.join(available)}",
                "suggestion": f"使用 article_check.rules.registry 注册新模板",
            }]

        # 读取文件内容
        try:
            text = file_path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return [{
                "type": "file_read_error",
                "severity": "critical",
                "description": f"无法读取文件: {e}",
            }]

        # 逐条执行规则
        all_issues = []
        for rule in self._rules:
            try:
                issues = rule(template, file_path, text)
                if issues:
                    all_issues.extend(issues)
            except Exception as e:
                logger.warning(f"规则 {rule.__name__} 执行失败: {e}")
                all_issues.append({
                    "type": "rule_error",
                    "severity": "info",
                    "description": f"规则 {rule.__name__} 检查异常: {e}",
                })

        logger.info(
            f"模板检查 '{template_name}': {len(all_issues)} 个问题"
        )
        return all_issues

    def check_all_templates(
        self,
        file_path: Path,
        file_type: str,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """用所有模板检查同一篇论文"""
        results = {}
        for tpl in template_registry.list_all():
            issues = self.check(tpl.name, file_path, file_type)
            results[tpl.name] = issues
        return results

    @property
    def rule_count(self) -> int:
        return len(self._rules)


# ═══════════════════════════════════════════════════════
# 内置检查规则实现
# ═══════════════════════════════════════════════════════

def _check_line_spacing(
    template: FormatTemplate, path: Path, text: str
) -> List[Dict]:
    """检查行间距"""
    issues = []
    expected = template.page.line_spacing
    # LaTeX: 检查 \linespread 或 \setstretch
    import re
    ls_match = re.search(r'\\(?:linespread|setstretch)\{([^}]+)\}', text)
    if ls_match:
        try:
            actual = float(ls_match.group(1))
            if abs(actual - expected) > 0.1:
                issues.append({
                    "type": "line_spacing_mismatch",
                    "severity": "major" if abs(actual - expected) > 0.3 else "minor",
                    "description": f"行间距 {actual} 与模板要求 {expected} 不一致",
                    "suggestion": f"使用 \\linespread{{{expected}}}",
                })
        except ValueError:
            pass
    # Word 行间距检查留待 python-docx
    return issues


def _check_margins(
    template: FormatTemplate, path: Path, text: str
) -> List[Dict]:
    """检查页边距"""
    issues = []
    t = template.page
    # LaTeX: geometry 包
    gm = re.search(r'\\usepackage\[([^\]]+)\]\{geometry\}', text)
    if gm:
        opts = gm.group(1).lower()
        checks = [
            ("top", t.margin_top_mm),
            ("bottom", t.margin_bottom_mm),
            ("left", t.margin_left_mm),
            ("right", t.margin_right_mm),
        ]
        for name, expected in checks:
            m = re.search(rf'{name}\s*=\s*([\d.]+)(mm|cm|in)?', opts)
            if m:
                val = float(m.group(1))
                unit = m.group(2) or "mm"
                if unit == "cm":
                    val *= 10
                elif unit == "in":
                    val *= 25.4
                if abs(val - expected) > 2.0:
                    issues.append({
                        "type": f"margin_{name}_mismatch",
                        "severity": "minor",
                        "description": f"上边距 {val:.0f}mm 与模板要求 {expected:.0f}mm 不一致",
                        "suggestion": f"调整 {name}={expected}mm",
                    })
    return issues


def _check_page_numbers(
    template: FormatTemplate, path: Path, text: str
) -> List[Dict]:
    """检查页码"""
    if template.page.page_numbers:
        # LaTeX: 需要 \pagestyle 或 \thepage
        if r"\pagestyle" not in text and r"\thepage" not in text and r"\pagenumbering" not in text:
            return [{
                "type": "page_number_missing",
                "severity": "minor",
                "description": "论文未设置页码",
                "suggestion": "添加 \\pagestyle{plain} 或 \\pagenumbering{arabic}",
            }]
    return []


def _check_body_font(
    template: FormatTemplate, path: Path, text: str
) -> List[Dict]:
    """检查正文字体"""
    issues = []
    expected = template.font.body_font
    # LaTeX: fontspec 或 mathptmx 等
    if "times" in expected.lower():
        if r"\usepackage{mathptmx}" not in text and \
           r"\usepackage{times}" not in text and \
           r"\setmainfont{Times New Roman}" not in text:
            issues.append({
                "type": "body_font_mismatch",
                "severity": "minor",
                "description": f"未设置正文字体为 {expected}",
                "suggestion": f"添加 \\usepackage{{mathptmx}} 或 \\setmainfont{{{expected}}}",
            })
    return issues


def _check_font_sizes(
    template: FormatTemplate, path: Path, text: str
) -> List[Dict]:
    """检查字体大小"""
    issues = []
    expected_size = template.font.body_size_pt
    # LaTeX: 检查 \documentclass[] 中的字号
    dc = re.search(r'\\documentclass\[([^\]]*)\]', text)
    if dc:
        opts = dc.group(1)
        size_map = {"10pt": 10, "11pt": 11, "12pt": 12}
        for opt, sz in size_map.items():
            if opt in opts:
                if sz != expected_size:
                    issues.append({
                        "type": "font_size_mismatch",
                        "severity": "minor",
                        "description": f"正文字号 {sz}pt 与模板要求 {expected_size}pt 不一致",
                        "suggestion": f"将 \\documentclass 选项改为 {int(expected_size)}pt",
                    })
                break
    return issues


def _check_mono_font(
    template: FormatTemplate, path: Path, text: str
) -> List[Dict]:
    """检查等宽字体"""
    return []


def _check_required_sections(
    template: FormatTemplate, path: Path, text: str
) -> List[Dict]:
    """检查必需章节是否齐全"""
    text_lower = text.lower()
    issues = []
    required = template.section.required_sections
    for sec in required:
        # LaTeX: \section{...}
        pattern = rf'\\(?:section|chapter)\{{.*?{re.escape(sec)}.*?\}}'
        if not re.search(pattern, text_lower):
            issues.append({
                "type": "missing_required_section",
                "severity": "major" if sec in ["abstract", "reference"] else "minor",
                "description": f"缺少必要章节: {sec.capitalize()}",
                "suggestion": f"添加 \\section{{{sec.capitalize()}}}",
            })
    return issues


def _check_abstract_word_count(
    template: FormatTemplate, path: Path, text: str
) -> List[Dict]:
    """检查摘要字数"""
    max_words = template.section.max_abstract_words
    m = re.search(r'\\begin\{abstract\}(.*?)\\end\{abstract\}', text, re.DOTALL)
    if m:
        abstract_text = m.group(1)
        word_count = len(abstract_text.split())
        if word_count > max_words:
            return [{
                "type": "abstract_too_long",
                "severity": "minor",
                "description": f"摘要 {word_count} 字，超过模板限制 {max_words} 字",
                "suggestion": f"将摘要精简至 {max_words} 字以内",
            }]
    return []


def _check_section_numbering(
    template: FormatTemplate, path: Path, text: str
) -> List[Dict]:
    """检查章节编号"""
    if not template.section.section_numbering:
        return []
    if r"\section*{" in text and r"\section{" not in text:
        return [{
            "type": "section_numbering_missing",
            "severity": "minor",
            "description": "所有章节均未编号，但模板要求编号",
            "suggestion": "使用 \\section{...} 而非 \\section*{...}",
        }]
    return []


def _check_figure_captions(
    template: FormatTemplate, path: Path, text: str
) -> List[Dict]:
    """检查图标题"""
    if not template.figures.need_caption:
        return []
    if r"\begin{figure}" in text and r"\caption" not in text:
        return [{
            "type": "figure_caption_missing",
            "severity": "major",
            "description": "图表缺少标题",
            "suggestion": "在每个 figure 环境中添加 \\caption{...}",
        }]
    return []


def _check_table_captions(
    template: FormatTemplate, path: Path, text: str
) -> List[Dict]:
    """检查表标题"""
    if not template.figures.need_caption:
        return []
    if r"\begin{table}" in text and r"\caption" not in text:
        return [{
            "type": "table_caption_missing",
            "severity": "major",
            "description": "表格缺少标题",
            "suggestion": "在每个 table 环境中添加 \\caption{...}",
        }]
    return []


def _check_reference_count(
    template: FormatTemplate, path: Path, text: str
) -> List[Dict]:
    """检查参考文献数量"""
    # 统计 \bibitem 或 thebibliography 中的条目
    refs = re.findall(r'\\bibitem', text)
    count = len(refs)
    issues = []
    if count < template.references.min_refs:
        issues.append({
            "type": "insufficient_references",
            "severity": "major",
            "description": f"参考文献 {count} 篇，低于模板要求的最低 {template.references.min_refs} 篇",
            "suggestion": "建议补充文献至要求数量",
        })
    if template.references.max_refs and count > template.references.max_refs:
        issues.append({
            "type": "excessive_references",
            "severity": "minor",
            "description": f"参考文献 {count} 篇，超过模板上限 {template.references.max_refs} 篇",
            "suggestion": "建议精简文献至要求范围内",
        })
    return issues


def _check_citation_format(
    template: FormatTemplate, path: Path, text: str
) -> List[Dict]:
    """检查引用格式"""
    # 简单的引用格式检测
    if template.references.citation_style == "numeric":
        # 期望 \cite{...} 而非 \citep{...} 或 \citet{...}
        pass  # 更复杂的检查留待后续
    return []


def _check_abstract_presence(
    template: FormatTemplate, path: Path, text: str
) -> List[Dict]:
    """检查是否有摘要"""
    if template.title_page.need_abstract:
        if not re.search(r'\\begin\{abstract\}', text):
            return [{
                "type": "abstract_missing",
                "severity": "critical",
                "description": "论文缺少摘要",
                "suggestion": "添加 \\begin{abstract}...\\end{abstract}",
            }]
    return []


def _check_keywords_presence(
    template: FormatTemplate, path: Path, text: str
) -> List[Dict]:
    """检查是否有关键词"""
    if template.title_page.need_keywords:
        if not re.search(r'\\(?:keywords|keyword)\{', text, re.IGNORECASE):
            return [{
                "type": "keywords_missing",
                "severity": "minor",
                "description": "论文缺少关键词",
                "suggestion": "添加 \\keywords{...}",
            }]
    return []


def _check_latex_class(
    template: FormatTemplate, path: Path, text: str
) -> List[Dict]:
    """检查 LaTeX 文档类"""
    if template.latex_class:
        expected = template.latex_class
        m = re.search(r'\\documentclass(?:\[[^\]]*\])?\{(.+?)\}', text)
        if m:
            actual = m.group(1)
            if actual != expected:
                return [{
                    "type": "latex_class_mismatch",
                    "severity": "major",
                    "description": f"文档类 '{actual}' 与模板要求的 '{expected}' 不符",
                    "suggestion": f"将 \\documentclass{{{actual}}} 改为 \\documentclass{{{expected}}}",
                }]
    return []


def _check_latex_packages(
    template: FormatTemplate, path: Path, text: str
) -> List[Dict]:
    """检查必需宏包"""
    if not template.latex_packages:
        return []
    issues = []
    for pkg in template.latex_packages:
        if not re.search(rf'\\usepackage(?:\[[^\]]*\])?{{{re.escape(pkg)}}}', text):
            issues.append({
                "type": "missing_package",
                "severity": "minor",
                "description": f"缺少必需的宏包: {pkg}",
                "suggestion": f"添加 \\usepackage{{{pkg}}}",
            })
    return issues


def _check_heading_styles(
    template: FormatTemplate, path: Path, text: str
) -> List[Dict]:
    """检查 Word 标题样式"""
    # 此规则需要 python-docx，留待后期实现
    return []
