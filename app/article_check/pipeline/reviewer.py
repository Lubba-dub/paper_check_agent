"""
Reviewer — 审查最终的审阅者、综合评分、报告生成

Reviewer 是流水线的最后一环：
1. 综合所有 Worker 的结果
2. 执行最终质量评估
3. 生成结构化审查报告
"""
from __future__ import annotations
import json
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from article_check.core.worktree.manager import WorktreeContext
from article_check.pipeline.orchestrator import PipelineResult

logger = logging.getLogger(__name__)


@dataclass
class ReviewResult:
    """审查结果汇总"""
    overall_score: float
    scores: Dict[str, float]
    strengths: List[str] = field(default_factory=list)
    weaknesses: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
    total_issues: int = 0
    critical_issues: int = 0
    duration: float = 0.0


class Reviewer:
    """
    最终审阅者 — 综合评分与报告生成

    职责:
    - 汇总多个 Worker 结果
    - 生成统一评分
    - 输出 Markdown/HTML 报告
    """

    def __init__(self, name: str = "main_reviewer"):
        self.name = name
        logger.info(f"Reviewer 初始化: {name}")

    async def generate(
        self,
        ctx: WorktreeContext,
        result: PipelineResult,
    ) -> Optional[Path]:
        """生成审查报告"""
        logger.info(f"[{result.task_id}] 开始生成审查报告")

        # 构建报告数据
        report = self._build_report(result)

        # 写入 Markdown 报告
        report_path = ctx.report_dir / f"{result.task_id}_review_report.md"
        report_content = self._render_markdown(report)

        report_path.write_text(report_content, encoding="utf-8")

        # 也写一份 JSON 机器可读版本
        json_path = ctx.report_dir / f"{result.task_id}_review_report.json"
        json_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        logger.info(f"报告已生成: {report_path}")
        return report_path

    def _build_report(self, result: PipelineResult) -> Dict[str, Any]:
        """构建结构化报告数据"""
        report = {
            "meta": {
                "paper_title": result.paper_title,
                "task_id": result.task_id,
                "review_time": result.duration,
                "overall_score": result.overall_score,
            },
            "format_check": self._extract_format_section(result),
            "content_review": self._extract_content_section(result),
            "reference_check": self._extract_reference_section(result),
            "summary": self._generate_summary(result),
        }
        return report

    def _extract_format_section(self, r: PipelineResult) -> Dict:
        if not r.format_check:
            return {"status": "skipped", "issues": []}
        return {
            "status": "completed",
            "issues": r.format_check.get("issues", r.format_check),
        }

    def _extract_content_section(self, r: PipelineResult) -> Dict:
        if not r.content_review:
            return {"status": "skipped", "sections": {}}
        return {
            "status": "completed",
            "sections": r.content_review,
        }

    def _extract_reference_section(self, r: PipelineResult) -> Dict:
        if not r.reference_check:
            return {"status": "skipped", "issues": []}
        return {
            "status": "completed",
            "details": r.reference_check,
        }

    def _generate_summary(self, r: PipelineResult) -> Dict:
        """生成中文总结"""
        score = r.overall_score or 0
        if score >= 0.9:
            level = "优秀 (Accept with minor revisions)"
        elif score >= 0.75:
            level = "良好 (Minor revisions required)"
        elif score >= 0.6:
            level = "一般 (Major revisions required)"
        else:
            level = "需大幅修改 (Reject / Major overhaul)"

        all_issues = []
        if r.format_check:
            all_issues.extend(
                r.format_check.get("issues", [])
                if isinstance(r.format_check, dict)
                else r.format_check
            )
        if r.content_review:
            for v in r.content_review.values():
                if isinstance(v, dict):
                    all_issues.extend(v.get("issues", []))

        return {
            "final_grade": level,
            "total_issues": len(all_issues),
            "critical_count": sum(
                1 for i in all_issues
                if isinstance(i, dict) and i.get("severity") == "critical"
            ),
            "overall_assessment": f"综合评分 {score:.2f}，共发现 {len(all_issues)} 个问题。",
        }

    def _render_markdown(self, report: Dict) -> str:
        """将报告渲染为 Markdown"""
        meta = report["meta"]
        summary = report["summary"]

        lines = []
        lines.append(f"# 📋 论文审查报告")
        lines.append(f"")
        lines.append(f"**论文**: {meta['paper_title']}")
        lines.append(f"**审查耗时**: {meta['review_time']:.1f}s")
        lines.append(f"**综合评分**: **{meta['overall_score']:.2f}**")
        lines.append(f"")
        lines.append(f"---")
        lines.append(f"")
        lines.append(f"## 📊 审查总结")
        lines.append(f"")
        lines.append(f"| 指标 | 值 |")
        lines.append(f"|------|-----|")
        lines.append(f"| 最终评级 | {summary['final_grade']} |")
        lines.append(f"| 总问题数 | {summary['total_issues']} |")
        lines.append(f"| 严重问题 | {summary['critical_count']} |")
        lines.append(f"| 总体评价 | {summary['overall_assessment']} |")
        lines.append(f"")
        lines.append(f"---")
        lines.append(f"")

        # 格式检查
        fmt = report.get("format_check", {})
        lines.append(f"## 📐 格式审查")
        lines.append(f"**状态**: {fmt.get('status', 'N/A')}")
        lines.append(f"")
        issues = fmt.get("issues", [])
        if issues:
            for i, issue in enumerate(issues, 1):
                if isinstance(issue, dict):
                    sev = issue.get("severity", "info")
                    emoji = {"critical": "🔴", "major": "🟡", "minor": "🟢", "info": "ℹ️"}
                    lines.append(f"{emoji.get(sev, '•')} **{issue.get('type', 'Issue')}**: {issue.get('description', str(issue))}")
                    if issue.get("suggestion"):
                        lines.append(f"   > 💡 *建议: {issue['suggestion']}*")
                else:
                    lines.append(f"- {issue}")
        else:
            lines.append("*未发现格式问题*")
        lines.append(f"")

        # 内容审查
        content = report.get("content_review", {})
        lines.append(f"## 📝 内容审查")
        lines.append(f"**状态**: {content.get('status', 'N/A')}")
        lines.append(f"")
        sections = content.get("sections", {})
        if sections:
            for worker_name, worker_data in sections.items():
                if isinstance(worker_data, dict):
                    lines.append(f"### 审查维度: {worker_name}")
                    lines.append(f"评分: **{worker_data.get('score', 'N/A')}**")
                    for issue in worker_data.get("issues", []):
                        if isinstance(issue, dict):
                            sev = issue.get("severity", "info")
                            emoji = {"critical": "🔴", "major": "🟡", "minor": "🟢"}
                            lines.append(f"- {emoji.get(sev, '•')} [{issue.get('section', 'N/A')}] {issue.get('description', '')}")
                    lines.append(f"")
        else:
            lines.append("*内容审查数据未生成*")
        lines.append(f"")

        # 文献审查
        ref = report.get("reference_check", {})
        lines.append(f"## 📚 文献审查")
        lines.append(f"**状态**: {ref.get('status', 'N/A')}")
        lines.append(f"")
        if ref.get("status") == "completed":
            lines.append(f"已验证文献数: {ref.get('details', {}).get('verified_refs', 'N/A')}")
        else:
            lines.append("*文献审查未执行*")
        lines.append(f"")
        lines.append(f"---")
        lines.append(f"*报告生成时间: {meta['review_time']:.1f}s*")

        return "\n".join(lines)
