"""
MCP (Model Context Protocol) 工具 — Agent 与外部世界的桥梁

每个 MCP 工具是一个独立的、可被 DeepSeek 调用的功能单元。
通过注册到 Harness，LLM Agent 可以在审查过程中按需调用。

工具分类:
- format: 格式检查（零 token 本地规则引擎）
- reference: 文献验证（API 调用，少量 token）
- search: Web 搜索（网络调用）
- report: 报告生成
"""
from article_check.mcp.tools.format_tools import (
    check_latex_format,
    check_docx_format,
    check_structure,
)
from article_check.mcp.tools.reference_tools import (
    verify_doi,
    check_reference_exists,
    check_citation_accuracy,
    suggest_journals,
)
from article_check.mcp.tools.search_tools import (
    web_search,
    search_arxiv,
)
from article_check.mcp.tools.report_tools import (
    generate_markdown_report,
    generate_html_report,
)
