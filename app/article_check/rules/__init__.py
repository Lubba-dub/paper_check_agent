"""格式规则引擎 — LaTeX / Word / 模板/结构检查"""
from article_check.rules.latex.checker import LaTeXChecker
from article_check.rules.docx.checker import DocxChecker
from article_check.rules.template import (
    FormatTemplate, IEEE_TEMPLATE, ELSEVIER_TEMPLATE,
    ACM_TEMPLATE, LNCS_TEMPLATE,
    PageConstraint, FontConstraint, SectionConstraint,
    FigureTableConstraint, ReferenceConstraint, TitlePageConstraint,
)
from article_check.rules.registry import template_registry, TemplateRegistry
from article_check.rules.engine import TemplateRuleEngine
