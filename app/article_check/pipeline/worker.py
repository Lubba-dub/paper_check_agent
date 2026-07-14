"""
审查 Worker — 负责执行具体的审查工作单元

Worker 是审查流水线的执行单元，每个 Worker 负责一个审查维度：
- FormatWorker: 格式审查
- ContentWorker: 内容质量审查
- ReferenceWorker: 文献真实性审查
- NoveltyWorker: 创新性评估
"""
from __future__ import annotations
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from article_check.config.settings import config
from article_check.core.harness.base import Harness, HarnessContext
from article_check.core.worktree.manager import WorktreeContext
from article_check.pipeline.models import PaperTask, WorkerResult
from article_check.llm import create_ai_client
from article_check.utils.file_utils import detect_file_type, extract_text_from_docx, extract_text_from_pdf, read_paper_content

logger = logging.getLogger(__name__)


class Worker(ABC):
    """Worker 基类"""

    def __init__(
        self,
        name: str,
        harness: Optional[Harness] = None,
        llm_client: Optional[Any] = None,
    ):
        self.name = name
        self.harness = harness
        self.llm = llm_client or create_ai_client()

    @abstractmethod
    async def work(
        self,
        ctx: WorktreeContext,
        task: PaperTask,
    ) -> WorkerResult:
        """执行审查工作"""
        ...


class FormatWorker(Worker):
    """格式审查 Worker — 混合规则引擎 + LLM 辅助"""

    def __init__(self, harness: Harness):
        super().__init__(name="format_checker", harness=harness)

    async def work(
        self,
        ctx: WorktreeContext,
        task: PaperTask,
    ) -> WorkerResult:
        logger.info(f"[{task.task_id}] FormatWorker 开始")

        issues = []
        file_type = task.file_type or "unknown"

        # 1. 本地规则引擎检查（零 token）
        if file_type == "latex":
            tool = self.harness.get_tool("check_latex_format")
            if tool and tool.fn:
                latex_issues = tool.fn(file_path=str(ctx.paper_copy))
                issues.extend(latex_issues or [])

        elif file_type == "docx":
            tool = self.harness.get_tool("check_docx_format")
            if tool and tool.fn:
                docx_issues = tool.fn(
                    file_path=str(ctx.paper_copy),
                    review_track=task.review_track,
                )
                issues.extend(docx_issues or [])

        # 2. 结构完整性检查
        tool = self.harness.get_tool("check_structure")
        if tool and tool.fn:
            struct_issues = tool.fn(
                file_path=str(ctx.paper_copy),
                file_type=file_type,
                review_track=task.review_track,
            )
            if struct_issues:
                issues.extend(struct_issues.get("issues", []))

        score = max(0, 10 - len(issues) * 0.5) / 10
        logger.info(
            f"[{task.task_id}] FormatWorker 完成: "
            f"{len(issues)} issues, score={score}"
        )

        return WorkerResult(
            success=True,
            worker_name=self.name,
            data={"issues": issues, "score": score},
            issues=issues,
            score=score,
        )


class ContentWorker(Worker):
    """内容审查 Worker — 基于可切换的 AI Provider"""

    def __init__(self, harness: Harness, llm_client: Any):
        super().__init__(
            name="content_reviewer",
            harness=harness,
            llm_client=llm_client,
        )

    async def work(
        self,
        ctx: WorktreeContext,
        task: PaperTask,
    ) -> WorkerResult:
        logger.info(f"[{task.task_id}] ContentWorker 开始")

        # 读取论文内容，避免把 DOCX/PDF 当普通文本直接解码。
        paper_text = self._read_paper_text(ctx.paper_copy, task.file_type)
        if not paper_text.strip():
            return WorkerResult(
                success=True,
                worker_name=self.name,
                data={
                    "score": 0.0,
                    "issues": [],
                    "summary": "未能提取到可供深度审查的论文正文",
                },
                issues=[],
                score=0.0,
            )

        # 结构化输出 schema — 减少 completion tokens
        schema = {
            "type": "object",
            "properties": {
                "strengths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "论文的优点"
                },
                "weaknesses": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "论文的不足"
                },
                "issues": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "section": {"type": "string"},
                            "type": {"type": "string", "enum": ["logic", "clarity", "completeness", "methodology", "result", "citation_support", "claim_consistency", "structure_support"]},
                            "severity": {"type": "string", "enum": ["minor", "major", "critical"]},
                            "description": {"type": "string"},
                            "suggestion": {"type": "string"}
                        }
                    }
                },
                "score": {
                    "type": "number",
                    "description": "内容质量评分 0-1"
                },
                "summary": {"type": "string"}
            },
            "required": ["score", "summary", "issues"]
        }

        # 分段审查：避免 40% 上下文阈值问题
        sections = self._split_sections(paper_text)

        all_issues = []
        total_score = 0.0

        for i, section in enumerate(sections):
            if not section["text"].strip():
                continue

            messages = [
                {
                    "role": "system",
                    "content": (
                        f"你是一个学术论文深度审查专家，负责审查 {section['name']} 部分。"
                        f" 当前论文审查轨道为 {task.review_track or 'auto'}。"
                        " 除了逻辑与完整性，还要关注论断是否有证据支撑、是否存在章节承诺与正文内容不一致、是否有引用支撑不足。"
                        " 请严格按 JSON Schema 输出，只给出客观、具体、可复核的批评意见。"
                    )
                },
                {
                    "role": "user",
                    "content": f"请审查以下论文的 {section['name']} 部分：\n\n{section['text'][:6000]}"
                }
            ]

            try:
                result = self.llm.structured_chat(
                    messages=messages,
                    schema=schema,
                    temperature=0.1,
                )
                all_issues.extend(result.get("issues", []))
                total_score += result.get("score", 0.5)
            except Exception as e:
                logger.error(f"[{task.task_id}] 分段审查失败 ({section['name']}): {e}")

        avg_score = total_score / max(len(sections), 1)
        avg_score = min(1.0, max(0.0, avg_score))

        return WorkerResult(
            success=True,
            worker_name=self.name,
            data={
                "score": avg_score,
                "issues": all_issues,
                "summary": f"审查 {len(sections)} 个章节，发现 {len(all_issues)} 个问题",
            },
            issues=all_issues,
            score=avg_score,
        )

    def _split_sections(self, text: str) -> List[Dict]:
        """将论文分割为段落块（避免超长上下文）"""
        # 简单的分段逻辑
        section_keywords = [
            "abstract", "introduction", "related work",
            "method", "methodology", "experiment", "result",
            "discussion", "conclusion",
            "摘要", "引言", "方法", "实验", "结果", "讨论", "结论"
        ]
        lines = text.split("\n")
        sections = []
        current = {"name": "preamble", "text": ""}

        for line in lines:
            lower = line.lower().strip()
            for kw in section_keywords:
                if kw in lower:
                    if current["text"]:
                        sections.append(current)
                    current = {"name": kw, "text": line + "\n"}
                    break
            else:
                current["text"] += line + "\n"

        if current["text"]:
            sections.append(current)

        return sections

    def _read_paper_text(self, path, file_type: str = "") -> str:
        detected_type = file_type or detect_file_type(path)
        if detected_type == "docx":
            return extract_text_from_docx(path)
        if detected_type == "pdf":
            return extract_text_from_pdf(path)
        return read_paper_content(path)


class ReferenceWorker(Worker):
    """文献审查 Worker — 调用学术数据库 API"""

    def __init__(self, harness: Harness):
        super().__init__(name="reference_checker", harness=harness)

    async def work(
        self,
        ctx: WorktreeContext,
        task: PaperTask,
    ) -> WorkerResult:
        logger.info(f"[{task.task_id}] ReferenceWorker 开始")
        extract_tool = self.harness.get_tool("extract_references") if self.harness else None
        cross_check_tool = self.harness.get_tool("cross_check_references") if self.harness else None
        quality_tool = self.harness.get_tool("check_ref_quality_api") if self.harness else None

        issues: List[Dict[str, Any]] = []
        refs_summary: Dict[str, Any] = {"count": 0, "refs": []}
        cross_result: Dict[str, Any] = {
            "total_refs": 0,
            "matched": 0,
            "score": 0.0,
            "unmatched_citations": [],
            "unused_refs": [],
            "doi_missing": 0,
        }

        if extract_tool and extract_tool.fn:
            refs_summary = extract_tool.fn(paper_path=str(ctx.paper_copy)) or refs_summary

        if cross_check_tool and cross_check_tool.fn:
            cross_result = cross_check_tool.fn(paper_path=str(ctx.paper_copy)) or cross_result

        ref_count = refs_summary.get("count", 0)
        if ref_count == 0:
            issues.append({
                "type": "reference_missing",
                "severity": "critical",
                "description": "未检测到参考文献列表",
                "suggestion": "请检查论文是否包含规范的参考文献章节",
            })

        doi_missing_count = cross_result.get("doi_missing", 0)
        if doi_missing_count:
            issues.append({
                "type": "doi_missing",
                "severity": "major",
                "description": f"有 {doi_missing_count} 条参考文献缺失 DOI",
                "suggestion": "补充 DOI 或确认该参考文献是否属于无 DOI 文献类型",
            })

        unmatched = cross_result.get("unmatched_citations", []) or []
        if unmatched:
            issues.append({
                "type": "citation_mismatch",
                "severity": "critical",
                "description": f"检测到 {len(unmatched)} 处正文引用无法匹配到参考文献",
                "suggestion": "核对正文引用标号与参考文献列表的一致性",
            })

        unused_refs = cross_result.get("unused_refs", []) or []
        if unused_refs:
            issues.append({
                "type": "unused_reference",
                "severity": "minor",
                "description": f"检测到 {len(unused_refs)} 条参考文献未在正文中被引用",
                "suggestion": "删除未使用的文献或在正文中补充必要引用",
            })

        quality_checks = []
        if quality_tool and quality_tool.fn:
            sample_size = min(ref_count, 5)
            for index in range(sample_size):
                try:
                    quality_checks.append(
                        quality_tool.fn(
                            paper_path=str(ctx.paper_copy),
                            ref_index=index + 1,
                        )
                    )
                except Exception as exc:
                    logger.warning(f"[{task.task_id}] 参考文献质量抽样失败 #{index + 1}: {exc}")

        invalid_quality = [item for item in quality_checks if not item.get("exists", True) or item.get("doi_verified") is False]
        if invalid_quality:
            issues.append({
                "type": "reference_verification_risk",
                "severity": "major",
                "description": f"抽样核验中发现 {len(invalid_quality)} 条参考文献存在真实性或元数据异常。",
                "suggestion": "请逐条复核题名、作者、年份与 DOI，确认不存在伪造或错引条目。",
            })

        score = cross_result.get("score")
        if score is None:
            score = max(0.0, 1.0 - len(issues) * 0.15)

        data = {
            "issues": issues,
            "verified_refs": ref_count,
            "total_refs": cross_result.get("total_refs", ref_count),
            "matched": cross_result.get("matched", 0),
            "unmatched_citations": unmatched,
            "unused_refs": unused_refs,
            "doi_missing_count": doi_missing_count,
            "quality_checks": quality_checks,
            "score": score,
        }

        return WorkerResult(
            success=True,
            worker_name=self.name,
            data=data,
            issues=issues,
            score=score,
        )
