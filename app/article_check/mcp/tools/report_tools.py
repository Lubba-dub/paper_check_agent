"""
报告生成工具 — 将审查结果输出为 Markdown / HTML 格式

结构化输出为主，尽量减少 LLM token 消耗。
报告模板由 Python 生成，不经过 LLM。
"""
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def generate_markdown_report(
    paper_title: str,
    format_issues: Optional[List] = None,
    content_review: Optional[Dict] = None,
    reference_check: Optional[Dict] = None,
    overall_score: float = 0.0,
    output_path: Optional[str] = None,
) -> str:
    """
    生成 Markdown 审查报告

    Args:
        paper_title: 论文标题
        format_issues: 格式问题列表
        content_review: 内容审查结果
        reference_check: 文献审查结果
        overall_score: 综合评分
        output_path: 输出路径（可选）

    Returns:
        Markdown 报告内容
    """
    lines = []
    lines.append(f"# 📋 论文审查报告")
    lines.append(f"")
    lines.append(f"**论文**: {paper_title}")
    lines.append(f"**综合评分**: {overall_score:.2f}")
    lines.append(f"")
    lines.append(f"---")
    lines.append(f"")

    # 格式审查
    lines.append(f"## 📐 格式审查")
    if format_issues:
        for issue in format_issues:
            sev = issue.get("severity", "info")
            emoji = {"critical": "🔴", "major": "🟡", "minor": "🟢", "info": "ℹ️"}
            lines.append(f"{emoji.get(sev, '•')} {issue.get('description', str(issue))}")
            if issue.get("suggestion"):
                lines.append(f"  > 💡 {issue['suggestion']}")
    else:
        lines.append("*未发现格式问题*")
    lines.append(f"")

    # 内容审查
    lines.append(f"## 📝 内容审查")
    if content_review:
        score = content_review.get("score", "N/A")
        lines.append(f"**评分**: {score}")
        for issue in content_review.get("issues", []):
            sev = issue.get("severity", "info")
            emoji = {"critical": "🔴", "major": "🟡", "minor": "🟢"}
            lines.append(f"- {emoji.get(sev, '•')} [{issue.get('section', '')}] {issue.get('description', '')}")
    else:
        lines.append("*内容审查数据未生成*")
    lines.append(f"")

    # 文献审查
    lines.append(f"## 📚 文献审查")
    if reference_check:
        lines.append(f"已验证: {reference_check.get('verified_count', 0)} / {reference_check.get('total_refs', 0)}")
    else:
        lines.append("*文献审查未执行*")

    report_content = "\n".join(lines)

    if output_path:
        Path(output_path).write_text(report_content, encoding="utf-8")
        logger.info(f"报告已保存: {output_path}")

    return report_content


def generate_html_report(
    paper_title: str,
    report_data: Dict[str, Any],
    template: str = "default",
) -> str:
    """
    生成 HTML 格式的审查报告

    Args:
        paper_title: 论文标题
        report_data: 报告数据（JSON）
        template: 模板名称

    Returns:
        HTML 报告内容
    """
    # 简化的 HTML 生成
    score = report_data.get("overall_score", 0)
    score_color = "#4caf50" if score >= 0.8 else "#ff9800" if score >= 0.6 else "#f44336"

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>审查报告: {paper_title}</title>
    <style>
        body {{ font-family: -apple-system, 'Segoe UI', sans-serif; max-width: 900px; margin: 0 auto; padding: 20px; }}
        .score {{ font-size: 48px; font-weight: bold; color: {score_color}; text-align: center; }}
        .section {{ margin: 20px 0; padding: 15px; border-radius: 8px; background: #f5f5f5; }}
        .critical {{ border-left: 4px solid #f44336; }}
        .major {{ border-left: 4px solid #ff9800; }}
        .minor {{ border-left: 4px solid #4caf50; }}
    </style>
</head>
<body>
    <h1>📋 论文审查报告</h1>
    <h2>{paper_title}</h2>
    <div class="score">{score:.2f}</div>
    <p style="text-align:center">综合评分</p>
    <div class="section">
        <h3>📐 格式审查</h3>
        <pre>{json.dumps(report_data.get('format_check', {}), ensure_ascii=False, indent=2)}</pre>
    </div>
    <div class="section">
        <h3>📝 内容审查</h3>
        <pre>{json.dumps(report_data.get('content_review', {}), ensure_ascii=False, indent=2)}</pre>
    </div>
    <div class="section">
        <h3>📚 文献审查</h3>
        <pre>{json.dumps(report_data.get('reference_check', {}), ensure_ascii=False, indent=2)}</pre>
    </div>
</body>
</html>"""
    return html
