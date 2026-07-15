"""
统一运行时装配与结构化审查报告导出。

Phase A 目标：
- 收敛 CLI / Web / Chat 的装配逻辑
- 提供 VSCode 插件可消费的结构化审查输出
- 为后续 V4 的 ReviewIntent / ReviewPlan / EvidenceRecord 留出稳定边界
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from html import escape
from pathlib import Path
from typing import Any, Dict, List, Optional

from article_check.config.settings import config
from article_check.context import ContextCacheBus, CuratedContextBuilder
from article_check.core.harness.base import Harness
from article_check.core.harness.tools import get_default_tools
from article_check.llm import ai_provider_available, create_ai_client
from article_check.mcp.tools.format_tools import (
    check_docx_format,
    check_latex_format,
    check_structure,
)
from article_check.orchestrator_v4 import CheckpointStore, EventLog, V4ReviewWorkflow
from article_check.pipeline.models import PaperTask, PipelineResult
from article_check.pipeline.orchestrator import Orchestrator
from article_check.pipeline.reviewer import Reviewer
from article_check.pipeline.streaming import StreamingOrchestrator
from article_check.pipeline.worker import ContentWorker, FormatWorker, ReferenceWorker
from article_check.utils.file_utils import detect_file_type


@dataclass
class ReviewIntent:
    """统一入口的审查意图。"""

    mode: str
    paper_paths: List[str] = field(default_factory=list)
    template_name: Optional[str] = None
    institution: Optional[str] = None
    review_track: Optional[str] = None
    goals: List[str] = field(default_factory=list)


@dataclass
class ReviewPlan:
    """轻量版执行计划，占位承接 V4 DAG 化。"""

    plan_id: str
    stages: List[str]
    strategy: str = "deterministic_pipeline"
    budget: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EvidenceRecord:
    """统一证据记录，用于报告、插件展示和后续审计。"""

    evidence_id: str
    paper_id: str
    stage: str
    source_type: str
    claim: str
    confidence: float = 0.8
    severity: str = "info"
    location: Dict[str, Any] = field(default_factory=dict)
    suggestion: Optional[str] = None
    raw_payload: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RuntimeBundle:
    """统一运行时对象。"""

    mode: str
    config: Any
    harness: Harness
    orchestrator: Orchestrator
    reviewer: Reviewer
    intent: ReviewIntent
    plan: ReviewPlan
    context_builder: CuratedContextBuilder
    cache_bus: ContextCacheBus
    workflow: V4ReviewWorkflow


def _format_location_text(location: Any) -> str:
    if isinstance(location, dict):
        text = ", ".join(f"{k}: {v}" for k, v in location.items() if v not in (None, "", [], {}))
        return text or "未提供定位信息"
    if isinstance(location, list):
        text = " / ".join(str(item) for item in location if item not in (None, "", [], {}))
        return text or "未提供定位信息"
    if location in (None, "", [], {}):
        return "未提供定位信息"
    return str(location)


def _format_duration_label(value: Any) -> str:
    try:
        seconds = float(value or 0.0)
    except Exception:
        return str(value or "0.0000 秒")
    return f"{seconds:.4f} 秒"


def _display_file_name(summary: Dict[str, Any], paper_title: str) -> str:
    source_name = str(summary.get("source_file_name") or "").strip()
    if source_name:
        return source_name
    return str(paper_title or "未命名论文")


def _format_report_location(location: Any) -> str:
    text = _format_location_text(location)
    return "" if text == "未提供定位信息" else text


def _coerce_issue_location(issue: Dict[str, Any]) -> Dict[str, Any]:
    location = issue.get("location")
    if isinstance(location, dict) and location:
        return location
    normalized: Dict[str, Any] = {}
    for key in ("page", "line", "column", "section", "paragraph_index", "anchor_id", "block_id"):
        value = issue.get(key)
        if value not in (None, "", [], {}):
            normalized[key] = value
    return normalized


def _severity_rank(severity: Any) -> int:
    order = {
        "critical": 0,
        "major": 1,
        "minor": 2,
        "info": 3,
    }
    return order.get(str(severity or "info").strip().lower(), 4)


def _sort_findings_by_severity(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(
        items or [],
        key=lambda item: (
            _severity_rank(item.get("severity")),
            str(item.get("category") or ""),
            str(item.get("type") or ""),
            str(item.get("description") or ""),
        ),
    )


def _safe_report_stem(value: str, fallback: str = "report") -> str:
    """将展示标题转换为安全的报告目录/文件名。"""

    raw = str(value or "").strip()
    candidate = Path(raw).name or raw
    candidate = candidate.replace("\r", " ").replace("\n", " ")
    candidate = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", candidate)
    candidate = re.sub(r"\s+", " ", candidate).strip(" ._")
    return candidate[:120] or fallback


def build_harness() -> Harness:
    """构建带默认工具绑定的 Harness。"""

    harness = Harness()
    tool_specs = get_default_tools()
    for spec in tool_specs.values():
        harness.register_tool(spec)

    harness.get_tool("check_latex_format").fn = check_latex_format
    harness.get_tool("check_docx_format").fn = check_docx_format
    harness.get_tool("check_structure").fn = check_structure

    from article_check.mcp.tools.reference_engine_tools import (
        check_ref_quality_api,
        cross_check_references,
        extract_references,
        generate_bibliography,
        verify_doi_api,
    )

    harness.get_tool("extract_references").fn = extract_references
    harness.get_tool("cross_check_references").fn = cross_check_references
    harness.get_tool("generate_bibliography").fn = generate_bibliography
    harness.get_tool("verify_doi_api").fn = verify_doi_api
    quality_tool = harness.get_tool("check_ref_quality_api")
    if quality_tool:
        quality_tool.fn = check_ref_quality_api

    return harness


def create_paper_task(
    paper_path: str | Path,
    *,
    depth: str = "auto",
    template_name: Optional[str] = None,
    review_track: Optional[str] = None,
) -> PaperTask:
    """统一构造 PaperTask。"""

    path = Path(paper_path)
    return PaperTask(
        task_id=path.stem,
        paper_path=path,
        title=path.stem,
        file_type=detect_file_type(path),
        journal_template=template_name or "",
        review_depth=depth,
        review_track=review_track or "auto",
    )


def build_runtime(
    *,
    mode: str = "cli",
    enable_deep_review: bool = False,
    enable_streaming: bool = False,
    api_key: Optional[str] = None,
    paper_paths: Optional[List[str]] = None,
    template_name: Optional[str] = None,
    review_track: Optional[str] = None,
) -> RuntimeBundle:
    """统一构造运行时。"""

    if api_key:
        if (config.ai.provider or "deepseek").lower() == "dify":
            config.dify.api_key = api_key
        else:
            config.deepseek.api_key = api_key

    harness = build_harness()
    orchestrator_cls = StreamingOrchestrator if enable_streaming else Orchestrator
    orchestrator = orchestrator_cls(harness=harness)

    orchestrator.register_worker(FormatWorker(harness))
    orchestrator.register_worker(ReferenceWorker(harness))

    if enable_deep_review and ai_provider_available():
        orchestrator.register_worker(ContentWorker(harness, create_ai_client()))

    reviewer = Reviewer()
    orchestrator.register_reviewer(reviewer)
    context_builder = CuratedContextBuilder()
    context_builder.observe_system("你是论文审改与文献分析助手。")
    context_builder.observe_system("输出必须围绕格式问题、参考文献风险和审改建议。")
    cache_bus = ContextCacheBus()

    intent = ReviewIntent(
        mode=mode,
        paper_paths=paper_paths or [],
        template_name=template_name,
        review_track=review_track,
        goals=[
            "检查格式规范",
            "验证参考文献有效性",
            "产出结构化审查报告",
        ],
    )
    plan = ReviewPlan(
        plan_id=f"{mode}-plan",
        stages=[
            "ingest",
            "format_check",
            "reference_validate",
            "content_review" if enable_deep_review and ai_provider_available() else "content_skip",
            "report",
        ],
        budget={"max_concurrent": config.pipeline.max_concurrent},
    )
    runtime_dir = Path.cwd() / ".article_check"
    workflow = V4ReviewWorkflow(
        event_log=EventLog(runtime_dir / "events"),
        checkpoint_store=CheckpointStore(runtime_dir / "checkpoints"),
    )
    return RuntimeBundle(
        mode=mode,
        config=config,
        harness=harness,
        orchestrator=orchestrator,
        reviewer=reviewer,
        intent=intent,
        plan=plan,
        context_builder=context_builder,
        cache_bus=cache_bus,
        workflow=workflow,
    )


async def execute_review_task(
    runtime: RuntimeBundle,
    task: PaperTask,
    *,
    enable_deep_review: bool = False,
) -> PipelineResult:
    """通过 V4 workflow 执行单篇任务。"""

    runtime.context_builder.observe_user(
        f"开始审查论文 {task.title}",
        {"task_id": task.task_id, "mode": runtime.mode},
    )
    template_pack = {
        "template": task.journal_template or "default",
        "file_type": task.file_type,
        "review_depth": task.review_depth,
    }
    runtime.cache_bus.put_pack(
        "task_profile",
        content=str(template_pack),
        metadata={"task_id": task.task_id},
    )
    result = await runtime.workflow.run_single(runtime, task, enable_deep_review)
    runtime.context_builder.observe_assistant(
        f"论文 {task.title} 审查完成，评分 {result.overall_score}",
        {"task_id": task.task_id},
    )
    return result


async def execute_review_batch(
    runtime: RuntimeBundle,
    tasks: List[PaperTask],
    *,
    max_concurrent: Optional[int] = None,
) -> List[PipelineResult]:
    """批量任务先走统一上下文与缓存，再复用现有 orchestrator。"""

    runtime.context_builder.observe_user(
        f"开始批量审查 {len(tasks)} 篇论文",
        {"mode": runtime.mode, "count": len(tasks)},
    )
    batch_profile = "\n".join(f"{task.task_id}:{task.file_type}:{task.review_depth}" for task in tasks)
    runtime.cache_bus.put_pack(
        "batch_profile",
        content=batch_profile,
        metadata={"count": len(tasks)},
    )
    return await runtime.orchestrator.review_batch(tasks, max_concurrent=max_concurrent)


def load_workflow_artifacts(plan_id: str) -> Dict[str, Any]:
    """读取 V4 工作流产物。"""

    runtime_dir = Path.cwd() / ".article_check"
    checkpoint_path = runtime_dir / "checkpoints" / f"{plan_id}.json"
    events_path = runtime_dir / "events" / f"{plan_id}_events.json"

    checkpoint = None
    events: List[Dict[str, Any]] = []
    if checkpoint_path.exists():
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    if events_path.exists():
        events = json.loads(events_path.read_text(encoding="utf-8"))

    return {
        "checkpoint_path": str(checkpoint_path) if checkpoint_path.exists() else None,
        "events_path": str(events_path) if events_path.exists() else None,
        "checkpoint": checkpoint,
        "events": events,
    }


def _extract_findings(result: PipelineResult) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []

    format_issues = []
    if isinstance(result.format_check, dict):
        format_issues = result.format_check.get("issues", [])
    for issue in format_issues:
        if not isinstance(issue, dict):
            continue
        findings.append(
            {
                "category": "format",
                "severity": issue.get("severity", "info"),
                "type": issue.get("type", "format_issue"),
                "description": issue.get("description", ""),
                "suggestion": issue.get("suggestion"),
                "location": _coerce_issue_location(issue),
            }
        )

    if isinstance(result.content_review, dict):
        for worker_name, worker_data in result.content_review.items():
            if not isinstance(worker_data, dict):
                continue
            for issue in worker_data.get("issues", []):
                if not isinstance(issue, dict):
                    continue
                findings.append(
                    {
                        "category": "content",
                        "severity": issue.get("severity", "info"),
                        "type": issue.get("type", worker_name),
                        "description": issue.get("description", ""),
                        "suggestion": issue.get("suggestion"),
                        "location": {"section": issue.get("section")},
                    }
                )

    ref_details = result.reference_check if isinstance(result.reference_check, dict) else {}
    if ref_details:
        if ref_details.get("doi_missing_count", 0) > 0:
            findings.append(
                {
                    "category": "reference",
                    "severity": "major",
                    "type": "doi_missing",
                    "description": f"存在 {ref_details.get('doi_missing_count', 0)} 条缺失 DOI 的参考文献",
                    "suggestion": "补充 DOI 或补全参考文献信息",
                    "location": {"section": "references"},
                }
            )
        if ref_details.get("unmatched_citations"):
            findings.append(
                {
                    "category": "reference",
                    "severity": "critical",
                    "type": "citation_mismatch",
                    "description": "正文引用与参考文献条目存在不一致",
                    "suggestion": "检查正文中的引文编号和参考文献列表是否一一对应",
                    "location": {"section": "references"},
                }
            )

    return _sort_findings_by_severity(findings)


def build_evidence_records(result: PipelineResult) -> List[EvidenceRecord]:
    """从 PipelineResult 导出轻量证据记录。"""

    findings = _sort_findings_by_severity(_extract_findings(result))
    evidence: List[EvidenceRecord] = []
    for index, finding in enumerate(findings, start=1):
        evidence.append(
            EvidenceRecord(
                evidence_id=f"{result.task_id}-ev-{index}",
                paper_id=result.task_id,
                stage=finding["category"],
                source_type=finding["category"],
                claim=finding["description"],
                severity=finding.get("severity", "info"),
                location=finding.get("location", {}),
                suggestion=finding.get("suggestion"),
                raw_payload=finding,
            )
        )
    return evidence


def _attach_evidence_ids(items: List[Dict[str, Any]], evidence_records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    attached: List[Dict[str, Any]] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        current = dict(item)
        if current.get("evidence_id"):
            attached.append(current)
            continue
        anchor_id = str(((current.get("evidence_span") or {}).get("anchor_id")) or "").strip()
        if anchor_id:
            current["evidence_id"] = anchor_id
            attached.append(current)
            continue
        description = str(current.get("description") or "").strip()
        location = current.get("location") or {}
        for record in evidence_records:
            if description and description == str(record.get("claim") or "").strip():
                current["evidence_id"] = record.get("evidence_id")
                break
            if location and location == (record.get("location") or {}):
                current["evidence_id"] = record.get("evidence_id")
                break
        attached.append(current)
    return attached


def build_review_payload(result: PipelineResult, *, plan_id: str = "cli-plan") -> Dict[str, Any]:
    """构建供 Web / VSCode 插件消费的统一报告格式。"""

    findings = _sort_findings_by_severity(_extract_findings(result))
    evidence = [asdict(record) for record in build_evidence_records(result)]
    findings = _attach_evidence_ids(findings, evidence)
    report_markdown_path = None
    report_json_path = None
    if result.report_path:
        report_markdown_path = result.report_path
        json_candidate = result.report_path.with_suffix(".json")
        if json_candidate.exists():
            report_json_path = str(json_candidate)

        persisted_dir = Path.cwd() / "reports" / result.task_id
        persisted_md = persisted_dir / result.report_path.name
        persisted_json = persisted_dir / result.report_path.with_suffix(".json").name
        if persisted_md.exists():
            report_markdown_path = str(persisted_md)
        elif report_markdown_path:
            report_markdown_path = str(report_markdown_path)

        if persisted_json.exists():
            report_json_path = str(persisted_json)

    workflow_artifacts = load_workflow_artifacts(plan_id)
    workflow_graph = (workflow_artifacts.get("checkpoint") or {}).get("graph", {})
    if not workflow_graph:
        workflow_graph = infer_workflow_graph(result)
    formal_report = generate_formal_review_report(
        paper_title=result.paper_title,
        findings=findings,
        evidence_records=evidence,
        workflow=workflow_artifacts,
        summary={
            "overall_score": result.overall_score,
            "duration": result.duration,
            "errors": result.errors,
            "source_file_name": result.source_file_name or (Path(result.source_paper_path).name if result.source_paper_path else ""),
        },
    )
    advice_report = generate_advice_report(findings, result.paper_title)
    format_check = result.format_check if isinstance(result.format_check, dict) else {}
    reference_check = result.reference_check if isinstance(result.reference_check, dict) else {}
    content_review = result.content_review if isinstance(result.content_review, dict) else {}
    if format_check.get("issues"):
        format_check = {
            **format_check,
            "issues": _attach_evidence_ids(format_check.get("issues", []), evidence),
        }
    if reference_check.get("issues"):
        reference_check = {
            **reference_check,
            "issues": _attach_evidence_ids(reference_check.get("issues", []), evidence),
        }
    if content_review:
        normalized_content_review: Dict[str, Any] = {}
        for worker_name, worker_data in content_review.items():
            if isinstance(worker_data, dict) and worker_data.get("issues"):
                normalized_content_review[worker_name] = {
                    **worker_data,
                    "issues": _attach_evidence_ids(worker_data.get("issues", []), evidence),
                }
            else:
                normalized_content_review[worker_name] = worker_data
        content_review = normalized_content_review
    return {
        "report_format": "article_check.ai_review.v1",
        "meta": {
            "paper_title": result.paper_title,
            "task_id": result.task_id,
            "overall_score": result.overall_score,
            "duration": result.duration,
            "source_paper_path": result.source_paper_path,
            "source_file_name": result.source_file_name or (Path(result.source_paper_path).name if result.source_paper_path else ""),
            "review_track": result.review_track or "auto",
        },
        "summary": {
            "finding_count": len(findings),
            "error_count": len(result.errors),
            "report_markdown_path": report_markdown_path,
            "report_json_path": report_json_path,
            "suggestion_report_path": advice_report.get("report_path"),
            "formal_report_markdown_path": formal_report.get("markdown_path"),
            "formal_report_html_path": formal_report.get("html_path"),
            "formal_report_json_path": formal_report.get("json_path"),
        },
        "sections": {
            "format_check": format_check,
            "content_review": content_review,
            "reference_check": reference_check,
            "workflow": {
                "graph": workflow_graph,
                "events": workflow_artifacts.get("events", []),
            },
        },
        "findings": findings,
        "evidence_records": evidence,
        "advice_report": advice_report,
        "formal_report": {
            **formal_report,
            "source_paper_path": result.source_paper_path,
        },
        "workflow": {
            "checkpoint_path": workflow_artifacts.get("checkpoint_path"),
            "events_path": workflow_artifacts.get("events_path"),
            "graph": workflow_graph,
            "events": workflow_artifacts.get("events", []),
        },
        "errors": result.errors,
    }


def infer_workflow_graph(result: PipelineResult) -> Dict[str, Dict[str, Any]]:
    """当 checkpoint 不存在时，从结果推断一个最小工作流图。"""

    has_content = bool(result.content_review)
    return {
        "ingest": {
            "stage": "ingest",
            "worker_binding": None,
            "dependencies": [],
            "critical": True,
            "status": "completed",
        },
        "format": {
            "stage": "format_check",
            "worker_binding": "format_checker",
            "dependencies": ["ingest"],
            "critical": True,
            "status": "completed" if result.format_check else "pending",
        },
        "reference": {
            "stage": "reference_validate",
            "worker_binding": "reference_checker",
            "dependencies": ["format"],
            "critical": True,
            "status": "completed" if result.reference_check else "pending",
        },
        "content": {
            "stage": "content_review" if has_content else "content_skip",
            "worker_binding": "content_reviewer" if has_content else None,
            "dependencies": ["reference"],
            "critical": has_content,
            "status": "completed" if has_content else "skipped",
        },
        "report": {
            "stage": "report",
            "worker_binding": "main_reviewer",
            "dependencies": ["content"],
            "critical": True,
            "status": "completed" if result.report_path else "pending",
        },
    }


def generate_advice_report(findings: List[Dict[str, Any]], paper_title: str) -> Dict[str, Any]:
    """将 findings 聚合为审改建议报告。"""

    if not findings:
        priorities = [{
            "priority": "low",
            "title": "当前未发现显著问题",
            "actions": ["保留当前格式与引用结构", "在提交前做一次最终人工复核"],
        }]
    else:
        grouped: Dict[str, List[Dict[str, Any]]] = {"critical": [], "major": [], "minor": [], "info": []}
        for finding in findings:
            grouped.setdefault(finding.get("severity", "info"), []).append(finding)

        priorities = []
        for severity in ["critical", "major", "minor", "info"]:
            items = grouped.get(severity, [])
            if not items:
                continue
            priorities.append(
                {
                    "priority": severity,
                    "title": {
                        "critical": "优先修复的硬性问题",
                        "major": "建议优先处理的重要问题",
                        "minor": "可在提交前完成的规范性问题",
                        "info": "补充建议",
                    }.get(severity, "问题建议"),
                    "actions": [
                        item.get("suggestion") or item.get("description", "")
                        for item in items[:6]
                    ],
                }
            )

    lines = [
        f"# 审改建议报告：{paper_title}",
        "",
        "## 核心建议",
        "",
    ]
    for block in priorities:
        lines.append(f"### {block['title']}")
        for action in block["actions"]:
            lines.append(f"- {action}")
        lines.append("")

    report_stem = _safe_report_stem(paper_title)
    report_dir = Path.cwd() / "reports" / report_stem
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"{report_stem}_advice_report.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return {
        "priorities": priorities,
        "report_path": str(report_path),
    }


def generate_formal_review_report(
    *,
    paper_title: str,
    findings: List[Dict[str, Any]],
    evidence_records: List[Dict[str, Any]],
    workflow: Dict[str, Any],
    summary: Dict[str, Any],
) -> Dict[str, Any]:
    """生成更正式的审改报告模板与导出格式。"""

    report_stem = _safe_report_stem(paper_title)
    report_dir = Path.cwd() / "reports" / report_stem
    report_dir.mkdir(parents=True, exist_ok=True)

    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for finding in findings:
        grouped.setdefault(finding.get("category", "unknown"), []).append(finding)

    graph = (workflow.get("checkpoint") or {}).get("graph", {})
    graph_lines = [
        f"- `{node_id}`: {node.get('stage')} / {node.get('status')}"
        for node_id, node in graph.items()
    ]
    evidence_lines = [
        f"- [{record.get('severity', 'info')}] {record.get('claim', '')} | 位置: {record.get('location', {})}"
        for record in evidence_records[:20]
    ]
    duration_label = _format_duration_label(summary.get("duration"))

    md_lines = [
        f"# 正式审改报告：{paper_title}",
        "",
        "## 一、执行摘要",
        f"- 综合评分：{summary.get('overall_score')}",
        f"- 审查耗时：{duration_label}",
        f"- 问题总数：{len(findings)}",
        f"- 运行错误数：{len(summary.get('errors', []))}",
        "",
        "## 二、问题分类综述",
    ]
    if not grouped:
        md_lines.append("- 当前未发现显著问题。")
    for category, items in grouped.items():
        md_lines.append(f"- `{category}`: {len(items)} 项")
    md_lines.extend([
        "",
        "## 三、关键发现",
    ])
    for finding in findings[:15]:
        md_lines.append(
            f"- [{finding.get('severity', 'info')}] {finding.get('description', '')}；建议：{finding.get('suggestion') or '请人工复核'}"
        )
    md_lines.extend([
        "",
        "## 四、证据记录",
    ])
    md_lines.extend(evidence_lines or ["- 无"])
    md_lines.extend([
        "",
        "## 五、工作流节点状态",
    ])
    md_lines.extend(graph_lines or ["- 无"])
    md_lines.extend([
        "",
        "## 六、结论与提交建议",
        "- 建议先修复严重度为 critical / major 的问题，再处理 minor 级规范项。",
        "- 修正完成后重新执行一次完整审查，以确认引用链和格式链已闭环。",
        "",
    ])

    markdown_path = report_dir / f"{report_stem}_formal_review_report.md"
    markdown_path.write_text("\n".join(md_lines), encoding="utf-8")

    safe = lambda value: escape(str(value if value is not None else ""))
    severity_counts = {
        "critical": len([item for item in findings if item.get("severity") == "critical"]),
        "major": len([item for item in findings if item.get("severity") == "major"]),
        "minor": len([item for item in findings if item.get("severity") == "minor"]),
    }
    display_name = _display_file_name(summary, paper_title)
    paper_title_safe = safe(display_name)
    task_id_safe = safe(display_name)
    conclusion_text = (
        "建议优先修复格式与文献的 critical / major 问题，再进行提交前复审。"
        if severity_counts["critical"] or severity_counts["major"]
        else "当前未发现阻断提交的问题，建议在送审前完成导师人工复核。"
    )
    toc_items = [
        ("cover", "封面与送审信息"),
        ("summary", "执行摘要与风险矩阵"),
        ("outline", "目录与问题分类综述"),
        ("issues", "分类问题详表"),
        ("evidence", "Evidence 记录"),
        ("workflow", "工作流节点状态"),
        ("signoff", "修订签批与归档建议"),
    ]
    summary_rows = "".join([
        f"<tr><th>报告编号</th><td>{task_id_safe}</td><th>综合评分</th><td>{safe(summary.get('overall_score'))}</td></tr>",
        f"<tr><th>审查耗时</th><td>{safe(duration_label)}</td><th>问题总数</th><td>{len(findings)}</td></tr>",
        f"<tr><th>Critical</th><td>{severity_counts['critical']}</td><th>Major / Minor</th><td>{severity_counts['major']} / {severity_counts['minor']}</td></tr>",
    ])
    risk_matrix_rows = "".join(
        [
            f"<tr><td>{safe(category)}</td><td>{len(items)}</td><td>{len([item for item in items if item.get('severity') == 'critical'])}</td><td>{len([item for item in items if item.get('severity') == 'major'])}</td><td>{len([item for item in items if item.get('severity') == 'minor'])}</td></tr>"
            for category, items in grouped.items()
        ]
    ) or "<tr><td colspan='5'>当前未发现显著问题。</td></tr>"
    grouped_sections = []
    for category, items in grouped.items():
        rows = []
        for item in items[:10]:
            location_text = _format_report_location(item.get("location"))
            rows.append(
                f"""
                <tr>
                  <td><span class="severity severity-{safe(item.get('severity', 'info'))}">{safe(item.get('severity', 'info'))}</span></td>
                  <td>{safe(item.get('description', ''))}</td>
                  <td>{safe(location_text or '-')}</td>
                  <td>{safe(item.get('suggestion') or '请人工复核后修订')}</td>
                </tr>
                """
            )
        grouped_sections.append(
            f"""
            <section class="report-section" id="issues-{safe(category)}">
              <div class="section-head">
                <h2>{safe(category)}</h2>
                <span>{len(items)} 项</span>
              </div>
              <table class="issue-table">
                <thead>
                  <tr><th>严重度</th><th>问题描述</th><th>定位</th><th>修订建议</th></tr>
                </thead>
                <tbody>
                  {''.join(rows) or '<tr><td colspan="4">无</td></tr>'}
                </tbody>
              </table>
            </section>
            """
        )

    evidence_cards = []
    for record in evidence_records[:18]:
        location = record.get("location") or {}
        if isinstance(location, dict):
            location_text = " · ".join(
                [
                    f"第 {location.get('page')} 页" if location.get("page") else "",
                    f"行 {location.get('line')}" if location.get("line") else "",
                    f"章节 {location.get('section')}" if location.get("section") else "",
                ]
            ).strip(" ·")
            location_text = location_text or ""
        else:
            location_text = _format_report_location(location)
        evidence_cards.append(
            f"""
            <article class="evidence-card">
              <div class="evidence-meta">
                <span class="severity severity-{safe(record.get('severity', 'info'))}">{safe(record.get('severity', 'info'))}</span>
                <span>{safe(record.get('stage', '-'))}</span>
                {'<span>' + safe(location_text) + '</span>' if location_text else ''}
              </div>
              <h3>{safe(record.get('claim', ''))}</h3>
              <p>{safe(record.get('suggestion') or '建议人工复核后修订')}</p>
            </article>
            """
        )

    workflow_items = []
    for node_id, node in graph.items():
        workflow_items.append(
            f"""
            <div class="workflow-item">
              <div>
                <strong>{safe(node.get('stage') or node_id)}</strong>
                <div class="workflow-meta">{safe(node.get('worker_binding') or '未绑定 worker')}</div>
              </div>
              <span class="severity severity-{safe(node.get('status', 'pending'))}">{safe(node.get('status', 'pending'))}</span>
            </div>
            """
        )

    html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>正式审改报告</title>
  <style>
    :root {{
      --ink: #0f172a;
      --muted: #475569;
      --line: #dbe4f0;
      --paper: #ffffff;
      --canvas: #f4efe7;
      --panel: #f8fafc;
      --primary: #1d4ed8;
      --critical: #be123c;
      --major: #b45309;
      --minor: #0369a1;
      --info: #475569;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--canvas);
      color: var(--ink);
      font-family: "Inter", "Segoe UI", Arial, sans-serif;
      line-height: 1.7;
    }}
    .page {{
      max-width: 1120px;
      margin: 0 auto;
      padding: 40px 24px 56px;
    }}
    .hero {{
      background: linear-gradient(180deg, #fff, #f8fbff);
      border: 1px solid var(--line);
      border-radius: 28px;
      padding: 32px;
      box-shadow: 0 18px 60px rgba(15, 23, 42, 0.07);
    }}
    .cover-sheet {{
      display: grid;
      grid-template-columns: 1.1fr 0.9fr;
      gap: 28px;
      align-items: stretch;
    }}
    .cover-card, .toc-card {{
      border: 1px solid var(--line);
      border-radius: 24px;
      background: var(--paper);
      padding: 28px;
    }}
    .cover-meta {{
      margin-top: 22px;
      width: 100%;
      border-collapse: collapse;
      font-size: 14px;
    }}
    .cover-meta th, .cover-meta td {{
      border-top: 1px solid var(--line);
      padding: 12px 8px;
      text-align: left;
    }}
    .cover-meta th {{
      width: 18%;
      color: var(--muted);
      font-weight: 600;
    }}
    .toc-list {{
      margin: 18px 0 0;
      padding: 0;
      list-style: none;
    }}
    .toc-item {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 14px;
      border-top: 1px dashed var(--line);
      padding: 12px 0;
      color: var(--muted);
      text-decoration: none;
    }}
    .toc-item:first-child {{ border-top: 0; padding-top: 0; }}
    .hero-grid {{
      display: grid;
      grid-template-columns: 1.3fr 0.7fr;
      gap: 28px;
    }}
    .kicker {{
      font-size: 12px;
      letter-spacing: 0.28em;
      text-transform: uppercase;
      color: var(--muted);
      margin-bottom: 12px;
    }}
    h1, h2, h3 {{
      margin: 0;
      font-family: Georgia, "Times New Roman", serif;
      color: #10213f;
    }}
    h1 {{ font-size: 40px; line-height: 1.12; margin-bottom: 12px; }}
    h2 {{ font-size: 26px; margin-bottom: 16px; }}
    h3 {{ font-size: 18px; margin-bottom: 8px; }}
    p {{ margin: 0; color: var(--muted); }}
    .hero-score {{
      background: #101827;
      color: white;
      border-radius: 24px;
      padding: 24px;
    }}
    .score-value {{ font-size: 44px; font-weight: 700; margin: 12px 0; }}
    .metrics {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 16px;
      margin-top: 24px;
    }}
    .metric {{
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.82);
      border-radius: 20px;
      padding: 16px 18px;
    }}
    .metric-label {{
      font-size: 12px;
      letter-spacing: 0.22em;
      text-transform: uppercase;
      color: var(--muted);
    }}
    .metric-value {{ font-size: 30px; font-weight: 700; margin-top: 10px; }}
    .report-section {{
      margin-top: 26px;
      border: 1px solid var(--line);
      background: var(--paper);
      border-radius: 24px;
      padding: 24px;
      break-inside: avoid;
    }}
    .section-head {{
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      gap: 16px;
      margin-bottom: 16px;
    }}
    .issue-table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 14px;
    }}
    .issue-table th, .issue-table td {{
      border-top: 1px solid var(--line);
      padding: 14px 12px;
      text-align: left;
      vertical-align: top;
    }}
    .issue-table th {{
      font-size: 12px;
      letter-spacing: 0.16em;
      text-transform: uppercase;
      color: var(--muted);
      background: #f8fafc;
    }}
    .meta-table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 14px;
    }}
    .meta-table th, .meta-table td {{
      border-top: 1px solid var(--line);
      padding: 14px 12px;
      text-align: left;
    }}
    .meta-table th {{
      color: var(--muted);
      width: 18%;
      background: #f8fafc;
      font-weight: 600;
    }}
    .severity {{
      display: inline-flex;
      align-items: center;
      border-radius: 999px;
      padding: 4px 10px;
      font-size: 12px;
      font-weight: 700;
      border: 1px solid currentColor;
    }}
    .severity-critical {{ color: var(--critical); background: #fff1f2; }}
    .severity-major {{ color: var(--major); background: #fffbeb; }}
    .severity-minor {{ color: var(--minor); background: #f0f9ff; }}
    .severity-info, .severity-completed {{ color: #166534; background: #f0fdf4; }}
    .severity-running {{ color: #0f766e; background: #ecfeff; }}
    .severity-pending, .severity-skipped {{ color: var(--info); background: #f8fafc; }}
    .evidence-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 16px;
    }}
    .evidence-card {{
      border: 1px solid var(--line);
      border-radius: 20px;
      padding: 18px;
      background: #fcfdff;
    }}
    .evidence-meta {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      font-size: 12px;
      color: var(--muted);
      margin-bottom: 12px;
    }}
    .workflow-list {{
      display: grid;
      gap: 12px;
    }}
    .workflow-item {{
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: center;
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 14px 16px;
      background: #fcfdff;
    }}
    .workflow-meta {{ font-size: 13px; color: var(--muted); margin-top: 4px; }}
    .action-list {{ margin: 0; padding-left: 20px; color: var(--muted); }}
    .action-list li {{ margin: 8px 0; }}
    .signoff-grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 16px;
      margin-top: 18px;
    }}
    .signoff-card {{
      border: 1px dashed var(--line);
      border-radius: 18px;
      padding: 18px;
      min-height: 140px;
    }}
    .muted {{ color: var(--muted); }}
    .print-toolbar {{
      position: sticky;
      top: 0;
      display: flex;
      justify-content: flex-end;
      gap: 12px;
      margin-bottom: 18px;
    }}
    .print-toolbar button {{
      border: 0;
      border-radius: 999px;
      padding: 10px 16px;
      background: #101827;
      color: white;
      cursor: pointer;
      font-weight: 600;
    }}
    @media print {{
      body {{ background: white; }}
      .page {{ max-width: none; padding: 0; }}
      .print-toolbar {{ display: none; }}
      .hero, .report-section, .cover-card, .toc-card {{
        box-shadow: none;
        border-color: #d4d4d8;
      }}
      .report-section, .hero, .cover-card, .toc-card {{
        break-inside: avoid-page;
      }}
    }}
    @media (max-width: 900px) {{
      .cover-sheet, .hero-grid, .metrics, .evidence-grid, .signoff-grid {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <div class="page">
    <div class="print-toolbar">
      <button onclick="window.print()">打印 / 导出 PDF</button>
    </div>

    <section class="hero" id="cover">
      <div class="cover-sheet">
        <div class="cover-card">
          <div class="kicker">Formal Paper Review Report</div>
          <h1>{paper_title_safe}</h1>
          <p>本报告面向送审、导师复核和系统归档，采用“封面 + 风险矩阵 + 分类问题详表 + Evidence + 签批页”的正式版式。</p>
          <table class="cover-meta">
            <tbody>
              <tr><th>报告编号</th><td>{task_id_safe}</td></tr>
              <tr><th>审查对象</th><td>{paper_title_safe}</td></tr>
              <tr><th>审查时间</th><td>{safe(duration_label)}</td></tr>
              <tr><th>送审结论</th><td>{safe(conclusion_text)}</td></tr>
              <tr><th>学生信息</th><td>待填写</td></tr>
              <tr><th>导师信息</th><td>待填写</td></tr>
            </tbody>
          </table>
        </div>
        <div class="toc-card" id="outline">
          <div class="kicker">Document Outline</div>
          <h2>目录</h2>
          <ul class="toc-list">
            {''.join([f'<li><a class="toc-item" href="#{safe(anchor)}"><span>{safe(title)}</span><span>→</span></a></li>' for anchor, title in toc_items])}
          </ul>
        </div>
      </div>
    </section>

    <section class="hero">
      <div class="hero-grid">
        <div>
          <div class="kicker">Formal Paper Review Report</div>
          <h1 id="summary">{paper_title_safe}</h1>
          <p>本报告用于支持论文作者、导师和审查系统围绕同一份正式结果开展修改、复核与归档。</p>
          <div class="metrics">
            <div class="metric"><div class="metric-label">综合评分</div><div class="metric-value">{safe(summary.get('overall_score'))}</div></div>
            <div class="metric"><div class="metric-label">问题总数</div><div class="metric-value">{len(findings)}</div></div>
            <div class="metric"><div class="metric-label">Evidence</div><div class="metric-value">{len(evidence_records)}</div></div>
            <div class="metric"><div class="metric-label">审查耗时</div><div class="metric-value">{safe(duration_label)}</div></div>
          </div>
        </div>
        <div class="hero-score">
          <div class="kicker">执行结论</div>
          <div class="score-value">{safe(summary.get('overall_score'))}</div>
          <p>Critical: {severity_counts['critical']} · Major: {severity_counts['major']} · Minor: {severity_counts['minor']}</p>
          <p style="margin-top: 12px;">{safe(conclusion_text)}</p>
        </div>
      </div>
    </section>

    <section class="report-section">
      <div class="section-head">
        <h2>一、问题分类综述</h2>
        <span>{len(grouped)} 个类别</span>
      </div>
      <ul class="action-list">
        {''.join([f"<li>{safe(category)}: {len(items)} 项</li>" for category, items in grouped.items()]) or '<li>当前未发现显著问题</li>'}
      </ul>
      <div style="margin-top: 18px;">
        <table class="issue-table">
          <thead>
            <tr><th>类别</th><th>总数</th><th>Critical</th><th>Major</th><th>Minor</th></tr>
          </thead>
          <tbody>
            {risk_matrix_rows}
          </tbody>
        </table>
      </div>
    </section>

    <section class="report-section" id="issues">
      <div class="section-head">
        <h2>二、送审摘要与元信息</h2>
        <span>Submission Metadata</span>
      </div>
      <table class="meta-table">
        <tbody>
          {summary_rows}
        </tbody>
      </table>
    </section>

    {''.join(grouped_sections)}

    <section class="report-section" id="evidence">
      <div class="section-head">
        <h2>五、Evidence 记录</h2>
        <span>支持定位与复核</span>
      </div>
      <div class="evidence-grid">
        {''.join(evidence_cards) or '<p>无证据记录。</p>'}
      </div>
    </section>

    <section class="report-section" id="workflow">
      <div class="section-head">
        <h2>六、工作流节点状态</h2>
        <span>{len(graph)} 个节点</span>
      </div>
      <div class="workflow-list">
        {''.join(workflow_items) or '<p>无工作流数据。</p>'}
      </div>
    </section>

    <section class="report-section" id="signoff">
      <div class="section-head">
        <h2>七、结论与提交建议</h2>
        <span>Submission Advice</span>
      </div>
      <ul class="action-list">
        <li>建议先修复严重度为 critical / major 的问题，再处理 minor 级规范项。</li>
        <li>修正完成后重新执行一次完整审查，以确认格式链、引用链和报告链闭环。</li>
        <li>归档时同时保留本 HTML 版本、JSON 结构化报告与建议报告 Markdown。</li>
      </ul>
      <div class="signoff-grid">
        <div class="signoff-card"><strong>学生确认</strong><p class="muted" style="margin-top: 14px;">签名：________________<br/>日期：________________</p></div>
        <div class="signoff-card"><strong>导师复核</strong><p class="muted" style="margin-top: 14px;">签名：________________<br/>日期：________________</p></div>
        <div class="signoff-card"><strong>归档备注</strong><p class="muted" style="margin-top: 14px;">版本：________________<br/>备注：________________</p></div>
      </div>
    </section>
  </div>
</body>
</html>"""
    html_path = report_dir / f"{report_stem}_formal_review_report.html"
    html_path.write_text(html_content, encoding="utf-8")

    json_path = report_dir / f"{report_stem}_formal_review_report.json"
    json_path.write_text(
        json.dumps(
            {
                "paper_title": paper_title,
                "summary": summary,
                "findings": findings,
                "evidence_records": evidence_records,
                "workflow": workflow,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    return {
        "markdown_path": str(markdown_path),
        "html_path": str(html_path),
        "json_path": str(json_path),
    }


def build_batch_payload(results: List[PipelineResult], *, plan_id: str = "batch-plan") -> Dict[str, Any]:
    """导出批量审查汇总。"""

    items = [build_review_payload(result, plan_id=plan_id) for result in results]
    avg_score = 0.0
    if items:
        avg_score = sum((item.get("meta") or {}).get("overall_score") or 0 for item in items) / len(items)
    return {
        "report_format": "article_check.ai_review.batch.v1",
        "summary": {
            "paper_count": len(items),
            "average_score": round(avg_score, 4),
            "total_findings": sum((item.get("summary") or {}).get("finding_count", 0) for item in items),
        },
        "items": items,
    }


def _collect_payload_findings(report_payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    findings = report_payload.get("findings")
    if isinstance(findings, list) and findings:
        return [item for item in findings if isinstance(item, dict)]

    collected: List[Dict[str, Any]] = []
    sections = report_payload.get("sections") or {}
    section_category_map = {
        "format_check": "format",
        "deterministic_audit": "format",
        "reference_check": "reference",
        "verification_layer": "reference",
        "content_review": "content",
    }

    def append_from_issues(items: Any, category: str) -> None:
        if not isinstance(items, list):
            return
        for item in items:
            if not isinstance(item, dict):
                continue
            collected.append(
                {
                    "category": item.get("category") or category,
                    "severity": item.get("severity", "info"),
                    "type": item.get("type") or category,
                    "description": item.get("description") or item.get("summary") or item.get("claim") or "",
                    "suggestion": item.get("suggestion") or "",
                    "location": item.get("location") or {},
                    "evidence_id": item.get("evidence_id") or ((item.get("evidence_span") or {}).get("anchor_id")) or item.get("issue_id"),
                }
            )

    for section_name, category in section_category_map.items():
        section = sections.get(section_name)
        if isinstance(section, dict):
            append_from_issues(section.get("issues"), category)
            for nested in section.values():
                if isinstance(nested, dict):
                    append_from_issues(nested.get("issues"), category)

    return collected


def answer_report_question(report_payload: Dict[str, Any], question: str) -> str:
    """基于结构化报告回答追问，优先走 LLM，失败时退回规则回答。"""

    findings = _collect_payload_findings(report_payload)
    advice_report = report_payload.get("advice_report", {})

    if ai_provider_available():
        client = create_ai_client()
        messages = [
            {
                "role": "system",
                "content": "你是论文审改助手。必须基于给定的结构化审查报告回答，不得编造未在报告中出现的事实。",
            },
            {
                "role": "user",
                "content": (
                    f"结构化报告:\n{str(report_payload)[:12000]}\n\n"
                    f"用户问题: {question}\n\n"
                    "请给出简洁、可执行、面向论文修改的回答。"
                ),
            },
        ]
        try:
            response = client.chat(messages=messages, temperature=0.1, max_tokens=800)
            return response.content.strip()
        except Exception:
            pass

    if not findings:
        return "当前报告未发现显著问题，建议在正式提交前做一次人工复核并确认参考文献来源。"

    lower_question = question.lower()
    if "参考" in question or "doi" in lower_question or "citation" in lower_question:
        ref_findings = [f for f in findings if f.get("category") == "reference"]
        if not ref_findings:
            return "当前报告中未发现显著的参考文献风险。"
        return "参考文献相关问题包括：" + "；".join(
            f.get("description", "") for f in ref_findings[:4]
        )

    if "格式" in question:
        fmt_findings = [f for f in findings if f.get("category") == "format"]
        return "格式相关问题包括：" + "；".join(
            f.get("description", "") for f in fmt_findings[:5]
        )

    priorities = advice_report.get("priorities", [])
    if priorities:
        top = priorities[0]
        return f"当前最优先处理的是“{top.get('title', '核心问题')}”，建议先执行：{'; '.join(top.get('actions', [])[:3])}"
    return "建议优先处理严重度最高的问题，并根据建议报告逐项修改后重新审查。"
