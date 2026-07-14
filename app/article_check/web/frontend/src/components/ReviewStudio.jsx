import React, { useMemo } from 'react';
import {
  AlertTriangle,
  ArrowRight,
  BookMarked,
  Bot,
  ChevronRight,
  ExternalLink,
  FileWarning,
  Files,
  Flag,
  Printer,
  Gauge,
  ListChecks,
  LocateFixed,
  ScanLine,
  ScanSearch,
  ShieldAlert,
  Sparkles,
} from 'lucide-react';

const DEMO_REPORT = {
  meta: {
    paper_title: '模板示例：本科毕业论文审查报告',
    task_id: 'template-demo',
    overall_score: 0.71,
    duration: 18.4,
  },
  summary: {
    finding_count: 12,
    error_count: 0,
  },
  sections: {
    format_check: {
      issues: [
        {
          type: 'title_format',
          severity: 'major',
          line: 3,
          column: 1,
          description: '论文封面标题字体与模板要求不一致',
          suggestion: '将封面标题调整为指定字号与加粗样式',
        },
        {
          type: 'missing_section',
          severity: 'minor',
          section: 'related work',
          description: "缺少 'related work' 章节",
          suggestion: '补充相关工作综述并说明与现有研究的差异',
        },
        {
          type: 'caption_alignment',
          severity: 'minor',
          line: 42,
          column: 3,
          description: '图表标题未按学校模板要求居中',
          suggestion: '统一图表标题的居中与编号样式',
        },
      ],
    },
    reference_check: {
      issues: [
        {
          type: 'reference_missing',
          severity: 'critical',
          section: 'references',
          description: '存在正文引用但未形成完整参考文献列表',
          suggestion: '补齐参考文献章节并检查编号顺序',
        },
        {
          type: 'doi_missing',
          severity: 'major',
          section: 'references',
          description: '3 条英文文献缺少 DOI 信息',
          suggestion: '补充 DOI 或稳定访问链接，提升可验证性',
        },
      ],
      total_refs: 15,
      matched: 12,
      doi_missing_count: 3,
      score: 0.76,
    },
    report_generation: {
      risk_matrix: [
        { severity: 'critical', title: '参考文献完整性', detail: '正文引用与文后参考文献列表未完全闭合。' },
        { severity: 'major', title: '模板一致性', detail: '封面与图题样式尚未完全贴合学校模板。' },
      ],
      publication_readiness: {
        readiness: '需修订后提交',
        blocker_count: 1,
      },
    },
  },
  findings: [
    {
      category: 'format',
      severity: 'major',
      type: 'title_format',
      description: '封面标题字体与模板不一致',
      suggestion: '按模板统一封面字体、字号与加粗规则',
      location: { line: 3, column: 1 },
    },
    {
      category: 'reference',
      severity: 'critical',
      type: 'reference_missing',
      description: '正文引用与参考文献列表不完整',
      suggestion: '补齐 reference 章节并逐条核对引用',
      location: { section: 'references' },
    },
  ],
  evidence_records: [
    {
      evidence_id: 'template-ev-1',
      stage: 'format',
      severity: 'major',
      claim: '封面标题字体与模板不一致',
      suggestion: '改为模板指定字体与字号',
      location: { line: 3, column: 1, page: 1 },
    },
    {
      evidence_id: 'template-ev-2',
      stage: 'reference',
      severity: 'critical',
      claim: '正文引用存在，但 reference 章节缺失完整条目',
      suggestion: '补齐参考文献列表，并校对编号映射',
      location: { section: 'references', page: 8 },
    },
    {
      evidence_id: 'template-ev-3',
      stage: 'format',
      severity: 'minor',
      claim: '图 2 标题未居中',
      suggestion: '统一图题对齐与编号',
      location: { line: 42, page: 5 },
    },
  ],
  advice_report: {
    priorities: [
      {
        priority: 'critical',
        title: '先修复影响提交的硬性问题',
        actions: [
          '补齐参考文献章节并逐条核对正文引用映射',
          '确保每条外文文献具备 DOI 或稳定检索路径',
        ],
      },
      {
        priority: 'major',
        title: '再修复模板一致性问题',
        actions: [
          '统一封面、目录、正文标题层级的格式样式',
          '对图表标题、页眉页脚与行距做整体验证',
        ],
      },
    ],
  },
  question_router_hints: ['总览结论', '格式问题', '参考文献', '修订建议'],
  qa_seed_questions: [
    '请按优先级总结最需要先改的 3 个问题。',
    '哪些问题会直接影响论文提交？',
    '请说明参考文献部分最需要补强的地方。',
  ],
  workflow: {
    graph: {
      ingest: { stage: 'ingest', status: 'completed', critical: true, dependencies: [], worker_binding: 'file_loader' },
      format: { stage: 'format_check', status: 'completed', critical: true, dependencies: ['ingest'], worker_binding: 'format_checker' },
      reference: { stage: 'reference_validate', status: 'completed', critical: true, dependencies: ['format'], worker_binding: 'reference_checker' },
      report: { stage: 'report', status: 'completed', critical: true, dependencies: ['reference'], worker_binding: 'report_builder' },
    },
    events: [
      { event_type: 'started', stage: 'ingest', timestamp: 1710000000 },
      { event_type: 'completed', stage: 'format_check', timestamp: 1710000005 },
      { event_type: 'completed', stage: 'reference_validate', timestamp: 1710000010 },
      { event_type: 'completed', stage: 'report', timestamp: 1710000012 },
    ],
  },
};

export default function ReviewStudio({
  results,
  selectedResultId,
  onSelectResult,
  detailTarget,
  onSelectWorkflow,
  onSelectEvidence,
  onJumpEvidence,
  question,
  onQuestionChange,
  onAskQuestion,
  answer,
  asking,
  sourceSnippet,
  snippetLoading,
  onOpenFormalReport,
  onPrintFormalReport,
  reportFileUrl,
}) {
  const selectedEntry = useMemo(
    () => results.find((item) => item.id === selectedResultId) || null,
    [results, selectedResultId]
  );
  const review = selectedEntry?.review || DEMO_REPORT;
  const usingTemplate = !selectedEntry;
  const displayTitle = getDisplayTitle(selectedEntry, review, usingTemplate);

  const formatIssues = useMemo(() => extractFormatIssues(review), [review]);
  const referenceIssues = useMemo(() => extractReferenceIssues(review), [review]);
  const contentHighlights = useMemo(() => extractContentHighlights(review), [review]);
  const evidenceRecords = review.evidence_records || [];
  const priorities = review.advice_report?.priorities || [];
  const reportGeneration = review.sections?.report_generation || {};
  const summaryCards = buildSummaryCards(review, formatIssues, referenceIssues, evidenceRecords);
  const overview = buildOverview(review, formatIssues, referenceIssues, contentHighlights);
  const navigatorItems = buildNavigatorItems(evidenceRecords, formatIssues, referenceIssues);
  const qaSeedQuestions = useMemo(() => extractSuggestionQuestions(review, reportGeneration), [review, reportGeneration]);
  const routerHints = useMemo(() => extractRouterHints(review, reportGeneration), [review, reportGeneration]);
  const riskMatrixItems = useMemo(() => extractRiskMatrixItems(reportGeneration), [reportGeneration]);

  return (
    <div className="space-y-8">
      <section className="report-hero overflow-hidden">
        <div className="grid gap-8 xl:grid-cols-[1.35fr,0.85fr]">
          <div className="space-y-5">
            <div className="flex flex-wrap items-center gap-3">
              <span className="capsule capsule-primary">
                <Files className="h-3.5 w-3.5" />
                {usingTemplate ? '报告样例预览' : '论文审查结果'}
              </span>
              <span className="capsule capsule-muted">
                <Gauge className="h-3.5 w-3.5" />
                {describeVerdict(review.meta?.overall_score)}
              </span>
              <span className="capsule capsule-muted">
                <ScanSearch className="h-3.5 w-3.5" />
                任务编号 {review.meta?.task_id || '-'}
              </span>
            </div>

            <div className="space-y-3">
              <div className="report-kicker">本次审查概览</div>
              <h1 className="report-title">
                {displayTitle}
              </h1>
              <p className="report-subtitle">
                按“先看重点问题，再看证据位置，最后看修改建议”的顺序组织，方便作者直接改稿，也方便导师快速了解论文当前最需要处理的内容。
              </p>
            </div>

            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              {summaryCards.map((card) => (
                <MetricCard key={card.label} {...card} />
              ))}
            </div>

            <div className="flex flex-wrap gap-3">
              <button type="button" className="btn-primary" onClick={onOpenFormalReport} disabled={usingTemplate}>
                <ExternalLink className="h-4 w-4" />
                查看正式报告
              </button>
              <button type="button" className="btn-outline" onClick={onPrintFormalReport} disabled={usingTemplate}>
                <Printer className="h-4 w-4" />
                打印 / 导出 PDF
              </button>
            </div>
          </div>

          <div className="report-brief">
            <div className="report-brief-header">
              <div>
                <div className="report-brief-label">整体建议</div>
                <div className="report-brief-value">{formatScore(review.meta?.overall_score)}</div>
              </div>
              <div className={`risk-orb ${scoreToneClass(review.meta?.overall_score)}`}>
                {Math.round(normalizeScore(review.meta?.overall_score) || 0)}
              </div>
            </div>

            <div className="space-y-4">
              {overview.map((item) => (
                <div key={item.label} className="overview-row">
                  <div className="overview-row-head">
                    <item.icon className="h-4 w-4" />
                    <span>{item.label}</span>
                  </div>
                  <div className="overview-row-meta">
                    <span className={`capsule ${item.capsuleClass}`}>{item.value}</span>
                  </div>
                  <p className="overview-row-text">{item.description}</p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      <div className="grid gap-6">
        <SurfaceCard
          title="正式报告预览"
          subtitle="可直接用于打印、留档或与导师沟通的报告页面"
          icon={Printer}
        >
          {usingTemplate || !reportFileUrl ? (
            <EmptyState text="完成真实审查后，这里会展示可直接打印的正式报告。" />
          ) : (
            <div className="space-y-4">
              <iframe
                title="formal-report-preview"
                src={reportFileUrl}
                className="print-preview-frame"
              />
            </div>
          )}
        </SurfaceCard>
      </div>

      <section className="space-y-6 min-w-0">
        <div className="grid gap-6 xl:grid-cols-[1.05fr,0.95fr]">
          <SurfaceCard
            title="审查结果列表"
            subtitle={results.length ? `${results.length} 份论文已生成结果` : '当前显示的是示例报告'}
            icon={Files}
          >
            <div className="space-y-3">
              {(results.length ? results : [{ id: 'template-demo', review: DEMO_REPORT }]).map((entry) => {
                const active = entry.id === (selectedEntry?.id || 'template-demo');
                const meta = entry.review?.meta || {};
                return (
                  <button
                    key={entry.id}
                    type="button"
                    onClick={() => onSelectResult?.(entry.id)}
                    className={`queue-card ${active ? 'queue-card-active' : ''}`}
                  >
                    <div className="queue-card-top">
                      <span className="queue-title">{getQueueTitle(entry)}</span>
                      <span className={`queue-score ${scoreToneClass(meta.overall_score)}`}>
                        {formatScore(meta.overall_score)}
                      </span>
                    </div>
                    <div className="queue-meta">
                      <span>{meta.task_id || 'template-demo'}</span>
                      <span>{entry.review?.summary?.finding_count ?? 0} 条发现</span>
                    </div>
                  </button>
                );
              })}
            </div>
          </SurfaceCard>

          <SurfaceCard
            title="快速查看重点"
            subtitle="优先展示最值得先看的问题和可定位证据"
            icon={LocateFixed}
          >
            <div className="space-y-2.5">
              {navigatorItems.length === 0 && (
                <EmptyState text="当前没有可快速定位的证据或问题。" />
              )}
              {navigatorItems.map((item) => (
                <button
                  key={item.key}
                  type="button"
                  onClick={() => onJumpEvidence?.(item.id)}
                  className="navigator-item"
                >
                  <div className={`severity-dot ${severityColor(item.severity)}`} />
                  <div className="flex-1 text-left">
                    <div className="navigator-title">{item.title}</div>
                    <div className="navigator-meta">{item.meta}</div>
                  </div>
                  <ChevronRight className="h-4 w-4 text-slate-400" />
                </button>
              ))}
            </div>
          </SurfaceCard>
        </div>

        <div className="grid gap-6">
          <SurfaceCard
            title="格式问题"
            subtitle="重点查看章节缺失、排版不一致和模板不符合之处"
            icon={FileWarning}
            actionLabel={formatIssues.length ? `${formatIssues.length} 项` : '无'}
          >
            <IssueTable
              emptyText="当前未检测到格式层面的显著问题。"
              items={formatIssues}
              onLocate={onSelectEvidence}
              onJump={onJumpEvidence}
            />
          </SurfaceCard>

          <SurfaceCard
            title="参考文献问题"
            subtitle="重点查看引用不一致、参考文献缺失和可验证性风险"
            icon={BookMarked}
            actionLabel={referenceIssues.length ? `${referenceIssues.length} 项` : '无'}
          >
            <IssueTable
              emptyText="当前未检测到显著的文献风险。"
              items={referenceIssues}
              onLocate={onSelectEvidence}
              onJump={onJumpEvidence}
            />
          </SurfaceCard>
        </div>

        <div className="grid gap-6 2xl:grid-cols-[1.05fr,0.95fr]">
          <SurfaceCard
            title="问题依据与定位"
            subtitle="这里汇总每个重点问题的证据摘要，并支持跳转查看"
            icon={ShieldAlert}
          >
            <div className="space-y-4">
              {evidenceRecords.length === 0 && (
                <EmptyState text="当前报告暂无可定位证据。" />
              )}
              {evidenceRecords.map((record) => (
                <div
                  key={record.evidence_id}
                  id={`report-evidence-${slugify(record.evidence_id)}`}
                  className="evidence-card"
                >
                  <div className="evidence-card-head">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className={`severity-pill ${severityPillClass(record.severity)}`}>{record.severity || 'info'}</span>
                      <span className="mini-meta">{record.stage || '-'}</span>
                      <span className="mini-meta">{formatLocation(record.location)}</span>
                      {formatEvidenceAnchor(record) && (
                        <span className="mini-meta">{formatEvidenceAnchor(record)}</span>
                      )}
                    </div>
                  </div>
                  <h4 className="evidence-card-title">{record.claim || '未命名 evidence'}</h4>
                  {record.quoted_text && (
                    <p className="evidence-card-text">原文摘录：{truncateText(record.quoted_text, 120)}</p>
                  )}
                  {record.suggestion && (
                    <p className="evidence-card-text">建议：{record.suggestion}</p>
                  )}
                  <div className="evidence-card-actions">
                    <button type="button" className="btn-primary" onClick={() => onJumpEvidence?.(record.evidence_id)}>
                      跳转到对应片段
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </SurfaceCard>

          <SurfaceCard
            title="原文对应位置"
            subtitle="选中某条问题后，这里会显示论文中的相关原文片段"
            icon={ScanLine}
          >
            <SourceSnippetPanel snippetLoading={snippetLoading} sourceSnippet={sourceSnippet} />
          </SurfaceCard>
        </div>

        <div className="grid gap-6 2xl:grid-cols-[0.95fr,1.05fr]">
          <SurfaceCard
            title="建议先这样修改"
            subtitle="按照轻重缓急整理成可执行的修改顺序"
            icon={ListChecks}
          >
            <div className="space-y-4">
              {priorities.length === 0 && (
                <EmptyState text="当前没有生成审改行动建议。" />
              )}
              {priorities.map((block) => (
                <div key={block.title} className="priority-card">
                  <div className="priority-head">
                    <span className={`severity-pill ${severityPillClass(block.priority)}`}>{block.priority}</span>
                    <span className="priority-title">{block.title}</span>
                  </div>
                  <div className="space-y-2.5">
                    {(block.actions || []).map((action, index) => (
                      <div key={`${block.title}-${index}`} className="priority-item">
                        <ArrowRight className="h-4 w-4 text-primary-600" />
                        <span>{action}</span>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </SurfaceCard>

          <SurfaceCard
            title="内容与写作提醒"
            subtitle="保留最影响论文表达质量和结构完整性的提醒"
            icon={Flag}
          >
            <div className="space-y-3">
              {contentHighlights.length === 0 && (
                <EmptyState text="当前没有需要单独提示的内容或写作问题。" />
              )}
              {contentHighlights.map((item, index) => (
                <div key={`content-${index}`} className="content-item">
                  <div className="content-item-head">
                    <span className={`severity-pill ${severityPillClass(item.severity)}`}>{item.severity || 'info'}</span>
                    <span className="mini-meta">{item.location || '全文'}</span>
                  </div>
                  <p className="content-item-text">{item.description}</p>
                </div>
              ))}
            </div>
          </SurfaceCard>

          <SurfaceCard
            title="进一步关注点"
            subtitle="补充展示风险层级、提问方向和提交前准备情况"
            icon={Sparkles}
          >
            <div className="space-y-4">
              {riskMatrixItems.length === 0 && routerHints.length === 0 && (
                <EmptyState text="当前报告尚未返回可展示的增强字段。" />
              )}
              {riskMatrixItems.length > 0 && (
                <div className="space-y-3">
                  {riskMatrixItems.map((item, index) => (
                    <div key={`${item.title}-${index}`} className="content-item">
                      <div className="content-item-head">
                        <span className={`severity-pill ${severityPillClass(item.severity)}`}>{item.severity || 'info'}</span>
                        <span className="mini-meta">{item.title}</span>
                      </div>
                      <p className="content-item-text">{item.detail}</p>
                    </div>
                  ))}
                </div>
              )}
              {routerHints.length > 0 && (
                <div className="space-y-2">
                  <div className="text-xs font-semibold uppercase tracking-[0.24em] text-slate-500">建议继续追问</div>
                  <div className="flex flex-wrap gap-2">
                    {routerHints.map((hint) => (
                      <span key={hint} className="capsule capsule-muted">{hint}</span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </SurfaceCard>

          <SurfaceCard
            title="继续追问这份报告"
            subtitle="可以继续问“先改什么”“为什么这样判断”“证据在哪里”"
            icon={Bot}
          >
            <div className="space-y-4">
              {qaSeedQuestions.length > 0 && (
                <div className="space-y-2">
                  <div className="text-xs font-semibold uppercase tracking-[0.24em] text-slate-500">可直接使用的问题</div>
                  <div className="flex flex-wrap gap-2">
                    {qaSeedQuestions.map((item) => (
                      <button
                        key={item}
                        type="button"
                        className="capsule capsule-muted text-left"
                        onClick={() => onQuestionChange?.(item)}
                      >
                        {item}
                      </button>
                    ))}
                  </div>
                </div>
              )}
              <div className="rounded-2xl border border-slate-200 bg-white/70 p-4">
                <div className="mb-2 text-xs font-semibold uppercase tracking-[0.24em] text-slate-500">你的问题</div>
                <textarea
                  value={question}
                  onChange={(event) => onQuestionChange?.(event.target.value)}
                  placeholder="例如：请告诉我最应该先改的 3 个问题，并说明对应证据。"
                  className="min-h-28 w-full resize-y border-0 bg-transparent p-0 text-sm leading-7 text-slate-700 outline-none placeholder:text-slate-400"
                />
              </div>
              <div className="flex flex-wrap gap-3">
                <button
                  type="button"
                  onClick={onAskQuestion}
                  disabled={asking || usingTemplate}
                  className="btn-primary inline-flex items-center gap-2 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  <Sparkles className="h-4 w-4" />
                  {asking ? '生成中...' : '生成答复'}
                </button>
                {usingTemplate && (
                  <span className="capsule capsule-muted">模板模式下不发起真实问答</span>
                )}
              </div>
              <div className="answer-panel answer-markdown">
                <MarkdownAnswer content={answer} />
              </div>
            </div>
          </SurfaceCard>
        </div>
      </section>
    </div>
  );
}

function SurfaceCard({ title, subtitle, icon: Icon, actionLabel, children }) {
  return (
    <section className="surface-card">
      <div className="surface-card-head">
        <div className="flex items-start gap-3">
          {Icon && (
            <div className="surface-card-icon">
              <Icon className="h-4 w-4" />
            </div>
          )}
          <div>
            <h3 className="surface-card-title">{title}</h3>
            {subtitle && <p className="surface-card-subtitle">{subtitle}</p>}
          </div>
        </div>
        {actionLabel && <span className="capsule capsule-muted">{actionLabel}</span>}
      </div>
      {children}
    </section>
  );
}

function MetricCard({ label, value, detail, toneClass, icon: Icon }) {
  return (
    <div className="metric-card">
      <div className="metric-card-head">
        <span className="metric-label">{label}</span>
        {Icon && <Icon className={`h-4 w-4 ${toneClass}`} />}
      </div>
      <div className={`metric-value ${toneClass}`}>{value}</div>
      <div className="metric-detail">{detail}</div>
    </div>
  );
}

function IssueTable({ items, emptyText, onLocate, onJump }) {
  if (!items.length) {
    return <EmptyState text={emptyText} />;
  }

  return (
    <div className="overflow-hidden rounded-2xl border border-slate-200">
      <div className="min-w-0 overflow-x-auto">
        <table className="w-full min-w-full table-fixed text-left">
          <thead className="bg-slate-50/80 text-xs uppercase tracking-[0.22em] text-slate-500">
            <tr>
              <th className="w-[108px] px-4 py-3 font-medium">严重度</th>
              <th className="w-[31%] px-4 py-3 font-medium">问题</th>
              <th className="w-[19%] px-4 py-3 font-medium">定位</th>
              <th className="w-[30%] px-4 py-3 font-medium">建议</th>
              <th className="w-[132px] px-4 py-3 font-medium text-right">动作</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-200 bg-white/80 text-sm text-slate-700">
            {items.map((item) => (
              <tr key={item.key} className="align-top">
                <td className="px-4 py-4">
                  <span className={`severity-pill ${severityPillClass(item.severity)}`}>{item.severity || 'info'}</span>
                </td>
                <td className="px-4 py-4">
                  <div className="break-words font-medium text-slate-900">{item.title}</div>
                  {item.type && <div className="mt-1 text-xs text-slate-500">{item.type}</div>}
                </td>
                <td className="px-4 py-4 text-slate-600">
                  <div className="break-words">{item.locator}</div>
                </td>
                <td className="px-4 py-4 text-slate-600">
                  <div className="break-words">{item.suggestion || '建议人工复核后修订'}</div>
                </td>
                <td className="px-4 py-4">
                  <div className="flex flex-wrap justify-end gap-2">
                    {item.evidenceId && (
                      <button type="button" className="btn-outline" onClick={() => onLocate?.(item.evidenceId)}>
                        详情
                      </button>
                    )}
                    {item.evidenceId && (
                      <button type="button" className="btn-primary" onClick={() => onJump?.(item.evidenceId)}>
                        跳转
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function EmptyState({ text }) {
  return (
    <div className="rounded-2xl border border-dashed border-slate-300 bg-slate-50/70 px-4 py-8 text-center text-sm text-slate-500">
      <Files className="mx-auto mb-3 h-5 w-5 text-slate-400" />
      <div className="mb-1 text-xs font-semibold uppercase tracking-[0.22em] text-slate-400">暂无内容</div>
      {text}
    </div>
  );
}

function SourceSnippetPanel({ snippetLoading, sourceSnippet }) {
  if (snippetLoading) {
    return <EmptyState text="正在加载与当前证据对应的原文片段。" />;
  }

  if (!sourceSnippet) {
    return <EmptyState text="点击任一证据后，这里会展示源论文中的对应片段。" />;
  }

  const excerpt = sourceSnippet?.snippet?.excerpt || [];
  const focusLine = sourceSnippet?.snippet?.focus_line;
  const snippetMode = formatSnippetMode(sourceSnippet?.snippet?.mode);
  const anchorText = formatSourceAnchor(sourceSnippet);
  const hitHint = sourceSnippet?.snippet?.matched_hint || '';
  const pageText = sourceSnippet?.snippet?.page ? `第 ${sourceSnippet.snippet.page} 页` : '未标记';
  return (
    <div className="space-y-4">
      <div className="snippet-header">
        <div>
          <div className="snippet-title">{sourceSnippet.source_name || '原文片段'}</div>
          <div className="snippet-meta">{sourceSnippet.claim || '未提供问题摘要'}</div>
        </div>
        <span className="capsule capsule-muted">{sourceSnippet?.snippet?.source_kind || 'unknown'}</span>
      </div>
      <div className="snippet-summary-grid">
        <div className="snippet-summary-card">
          <div className="snippet-summary-label">定位摘要</div>
          <div className="snippet-summary-value">{sourceSnippet?.snippet?.summary || '未提供定位信息'}</div>
        </div>
        <div className="snippet-summary-card">
          <div className="snippet-summary-label">定位模式</div>
          <div className="snippet-summary-value">{snippetMode}</div>
        </div>
        <div className="snippet-summary-card">
          <div className="snippet-summary-label">定位锚点</div>
          <div className="snippet-summary-value">{anchorText}</div>
        </div>
        <div className="snippet-summary-card">
          <div className="snippet-summary-label">焦点行</div>
          <div className="snippet-summary-value">{focusLine || '章节匹配 / 未知'}</div>
        </div>
        <div className="snippet-summary-card">
          <div className="snippet-summary-label">页面 / 命中</div>
          <div className="snippet-summary-value">{hitHint ? `${pageText} · ${truncateText(hitHint, 40)}` : pageText}</div>
        </div>
      </div>
      <div className="snippet-panel">
        {excerpt.length === 0 && (
          <div className="text-sm text-slate-500">当前没有可展示的原文片段。</div>
        )}
        {excerpt.map((line, index) => (
          <div
            key={`${line.line_number || 'line'}-${index}`}
            className={`snippet-line ${focusLine && line.line_number === focusLine ? 'snippet-line-focused' : ''}`}
          >
            <div className="snippet-line-number">{line.line_number || '·'}</div>
            <div className="snippet-line-text">{decodeSnippetText(line.text)}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function MarkdownAnswer({ content }) {
  if (!content) {
    return <p>这里将显示围绕当前论文审查结果生成的解释、优先级建议与答辩式说明。</p>;
  }

  const blocks = parseMarkdownBlocks(content);
  return (
    <>
      {blocks.map((block, index) => {
        if (block.type === 'ol') {
          return (
            <ol key={`block-${index}`}>
              {block.items.map((item, itemIndex) => (
                <li key={`item-${itemIndex}`}>{renderInlineMarkdown(item)}</li>
              ))}
            </ol>
          );
        }
        if (block.type === 'ul') {
          return (
            <ul key={`block-${index}`}>
              {block.items.map((item, itemIndex) => (
                <li key={`item-${itemIndex}`}>{renderInlineMarkdown(item)}</li>
              ))}
            </ul>
          );
        }
        return <p key={`block-${index}`}>{renderInlineMarkdown(block.text)}</p>;
      })}
    </>
  );
}

function buildSummaryCards(review, formatIssues, referenceIssues, evidenceRecords) {
  return [
    {
      label: '综合评分',
      value: formatScore(review.meta?.overall_score),
      detail: describeVerdict(review.meta?.overall_score),
      toneClass: scoreToneClass(review.meta?.overall_score),
      icon: Gauge,
    },
    {
      label: '格式预警',
      value: String(formatIssues.length),
      detail: '模板、结构与版式问题',
      toneClass: 'text-amber-600',
      icon: FileWarning,
    },
    {
      label: '文献预警',
      value: String(referenceIssues.length),
      detail: '引用一致性与 DOI 风险',
      toneClass: 'text-rose-600',
      icon: BookMarked,
    },
    {
      label: '证据记录',
      value: String(evidenceRecords.length),
      detail: '可定位证据记录',
      toneClass: 'text-sky-600',
      icon: ShieldAlert,
    },
  ];
}

function buildOverview(review, formatIssues, referenceIssues, contentHighlights) {
  return [
    {
      label: '格式结构',
      value: `${countBySeverity(formatIssues, 'major') + countBySeverity(formatIssues, 'critical')} 项重点问题`,
      description: formatIssues[0]?.title || '暂无显著格式风险',
      icon: FileWarning,
      capsuleClass: 'capsule-warn',
    },
    {
      label: '参考文献',
      value: `${countBySeverity(referenceIssues, 'major') + countBySeverity(referenceIssues, 'critical')} 项需优先修复`,
      description: referenceIssues[0]?.title || '文献结构基本正常',
      icon: BookMarked,
      capsuleClass: 'capsule-danger',
    },
    {
      label: '内容表达',
      value: `${contentHighlights.length} 条摘录`,
      description: contentHighlights[0]?.description || '暂无内容层摘录',
      icon: AlertTriangle,
      capsuleClass: 'capsule-muted',
    },
  ];
}

function buildNavigatorItems(evidenceRecords, formatIssues, referenceIssues) {
  const evidenceItems = evidenceRecords.slice(0, 4).map((record) => ({
    key: `evidence-${record.evidence_id}`,
    kind: 'evidence',
    id: record.evidence_id,
    title: record.claim || '未命名 evidence',
    meta: `${record.stage || '-'} · ${formatLocation(record.location)}`,
    severity: record.severity || 'info',
  }));

  const issueItems = [...formatIssues, ...referenceIssues].slice(0, 4).map((item) => ({
    key: `issue-${item.key}`,
    kind: 'evidence',
    id: item.evidenceId,
    title: item.title,
    meta: item.locator,
    severity: item.severity || 'info',
  }));

  return [...evidenceItems, ...issueItems].filter((item) => item.id);
}

function extractFormatIssues(review) {
  const issues = review.sections?.format_check?.issues || [];
  return issues
    .filter((issue) => issue && (issue.description || issue.type))
    .map((issue, index) => ({
      key: `format-${index}`,
      title: issue.description || issue.type || '未命名格式问题',
      type: issue.type || 'format',
      severity: issue.severity || 'info',
      locator: formatLocation(issue),
      suggestion: issue.suggestion || '按模板要求修订',
      evidenceId: issue.evidence_id || findEvidenceId(review, issue.description, issue.location),
    }));
}

function extractReferenceIssues(review) {
  const issues = review.sections?.reference_check?.issues || review.sections?.reference_check?.details?.issues || [];
  return issues
    .filter((issue) => issue && (issue.description || issue.type))
    .map((issue, index) => ({
      key: `reference-${index}`,
      title: issue.description || issue.type || '未命名文献问题',
      type: issue.type || 'reference',
      severity: issue.severity || 'info',
      locator: formatLocation(issue),
      suggestion: issue.suggestion || '补充文献定位与核验信息',
      evidenceId: issue.evidence_id || findEvidenceId(review, issue.description, issue.location),
    }));
}

function extractContentHighlights(review) {
  const content = review.sections?.content_review || {};
  const blocks = Object.values(content).filter(Boolean);
  const issues = [];

  blocks.forEach((block) => {
    const nestedIssues = Array.isArray(block?.issues) ? block.issues : Array.isArray(block) ? block : [];
    nestedIssues.forEach((item) => {
      if (typeof item === 'string') {
        issues.push({ description: item, severity: 'info', location: '全文' });
        return;
      }
      if (item && typeof item === 'object') {
        issues.push({
          description: item.description || item.issue || '内容层问题',
          severity: item.severity || 'minor',
          location: item.location || item.section || '全文',
        });
      }
    });
  });

  return issues.slice(0, 6);
}

function extractSuggestionQuestions(review, reportGeneration) {
  return extractTextList(review.qa_seed_questions || reportGeneration.qa_seed_questions, 6);
}

function extractRouterHints(review, reportGeneration) {
  return extractTextList(
    review.question_router_hints || reportGeneration.question_router_hints || reportGeneration.routing_hints,
    6
  );
}

function extractRiskMatrixItems(reportGeneration) {
  const riskMatrix = reportGeneration?.risk_matrix;
  if (Array.isArray(riskMatrix) && riskMatrix.length) {
    return riskMatrix.slice(0, 6).map((item, index) => ({
      severity: item?.severity || 'info',
      title: item?.title || item?.label || `风险项 ${index + 1}`,
      detail: item?.detail || item?.description || item?.summary || '未提供详情',
    }));
  }

  const readiness = reportGeneration?.publication_readiness;
  if (readiness && typeof readiness === 'object') {
    return Object.entries(readiness).slice(0, 4).map(([key, value]) => ({
      severity: key.includes('blocker') ? 'major' : 'info',
      title: key,
      detail: typeof value === 'string' ? value : JSON.stringify(value),
    }));
  }

  return [];
}

function extractTextList(value, limit = 6) {
  const items = [];

  const pushText = (entry) => {
    if (!entry) return;
    if (typeof entry === 'string') {
      items.push(entry.trim());
      return;
    }
    if (Array.isArray(entry)) {
      entry.forEach(pushText);
      return;
    }
    if (typeof entry === 'object') {
      const candidate = entry.question || entry.title || entry.label || entry.description || entry.summary || entry.value;
      if (candidate) {
        items.push(String(candidate).trim());
      }
    }
  };

  pushText(value);
  return [...new Set(items.filter(Boolean))].slice(0, limit);
}

function getDisplayTitle(selectedEntry, review, usingTemplate) {
  if (usingTemplate) return review.meta?.paper_title || '模板示例';
  return selectedEntry?.displayName || selectedEntry?.file?.name || extractFileName(review?.meta?.source_paper_path) || review.meta?.paper_title || '论文审查报告';
}

function getQueueTitle(entry) {
  return entry?.displayName || entry?.file?.name || extractFileName(entry?.review?.meta?.source_paper_path) || entry?.review?.meta?.paper_title || '模板示例';
}

function extractFileName(path) {
  if (!path) return '';
  const segments = String(path).split(/[/\\]/).filter(Boolean);
  return segments[segments.length - 1] || '';
}

function parseMarkdownBlocks(content) {
  const lines = String(content || '').replace(/\r\n/g, '\n').split('\n');
  const blocks = [];
  let paragraph = [];
  let listType = null;
  let listItems = [];

  const flushParagraph = () => {
    if (!paragraph.length) return;
    blocks.push({ type: 'p', text: paragraph.join(' ').trim() });
    paragraph = [];
  };

  const flushList = () => {
    if (!listItems.length || !listType) return;
    blocks.push({ type: listType, items: [...listItems] });
    listType = null;
    listItems = [];
  };

  lines.forEach((rawLine) => {
    const line = rawLine.trim();
    if (!line) {
      flushParagraph();
      flushList();
      return;
    }

    const orderedMatch = line.match(/^\d+\.\s+(.*)$/);
    const bulletMatch = line.match(/^[-*]\s+(.*)$/);

    if (orderedMatch) {
      flushParagraph();
      if (listType && listType !== 'ol') flushList();
      listType = 'ol';
      listItems.push(orderedMatch[1]);
      return;
    }

    if (bulletMatch) {
      flushParagraph();
      if (listType && listType !== 'ul') flushList();
      listType = 'ul';
      listItems.push(bulletMatch[1]);
      return;
    }

    if (listType && listItems.length) {
      listItems[listItems.length - 1] = `${listItems[listItems.length - 1]} ${line}`.trim();
      return;
    }

    paragraph.push(line);
  });

  flushParagraph();
  flushList();
  return blocks;
}

function renderInlineMarkdown(content) {
  const tokens = String(content || '').split(/(\*\*[^*]+\*\*|`[^`]+`)/g).filter(Boolean);
  return tokens.map((token, index) => {
    if (token.startsWith('**') && token.endsWith('**')) {
      return <strong key={`token-${index}`}>{token.slice(2, -2)}</strong>;
    }
    if (token.startsWith('`') && token.endsWith('`')) {
      return <code key={`token-${index}`}>{token.slice(1, -1)}</code>;
    }
    return <React.Fragment key={`token-${index}`}>{token}</React.Fragment>;
  });
}

function decodeSnippetText(value) {
  let text = String(value || '');
  text = text.replace(/\\u([0-9a-fA-F]{4})/g, (_, hex) => String.fromCharCode(parseInt(hex, 16)));
  text = text.replace(/\\n/g, '\n').replace(/\\t/g, '\t').replace(/\\"/g, '"');

  if (typeof document !== 'undefined' && /&(?:[a-z]+|#\d+|#x[\da-f]+);/i.test(text)) {
    const textarea = document.createElement('textarea');
    textarea.innerHTML = text;
    text = textarea.value;
  }

  return text;
}

function truncateText(value, maxLength = 80) {
  const text = String(value || '').replace(/\s+/g, ' ').trim();
  if (!text) return '';
  if (text.length <= maxLength) return text;
  return `${text.slice(0, maxLength - 1)}...`;
}

function formatSnippetMode(mode) {
  if (mode === 'line') return '按行定位';
  if (mode === 'section') return '按章节定位';
  if (mode === 'search') return '按文本检索命中';
  if (mode === 'docx-unavailable') return 'DOCX 预览不可用';
  if (mode === 'pdf-unavailable') return 'PDF 预览不可用';
  if (mode === 'unsupported') return '暂不支持';
  if (mode === 'error') return '加载失败';
  return mode || '未知';
}

function formatEvidenceAnchor(record) {
  const anchorId = record?.evidence_span?.anchor_id || record?.location?.anchor_id;
  if (!anchorId) return '';
  return `锚点 ${anchorId}`;
}

function formatSourceAnchor(sourceSnippet) {
  const anchorId = sourceSnippet?.location?.anchor_id || sourceSnippet?.evidence_span?.anchor_id;
  const blockId = sourceSnippet?.location?.block_id || sourceSnippet?.evidence_span?.block_id;
  if (anchorId && blockId) return `${anchorId} / ${blockId}`;
  if (anchorId) return anchorId;
  if (blockId) return blockId;
  return '未命名锚点';
}

function findEvidenceId(review, description, location) {
  const records = review.evidence_records || [];
  if (!records.length) return null;
  if (description) {
    const hit = records.find((record) => record.claim === description);
    if (hit?.evidence_id) return hit.evidence_id;
  }
  if (location && typeof location === 'object') {
    const hit = records.find((record) => JSON.stringify(record.location || {}) === JSON.stringify(location));
    if (hit?.evidence_id) return hit.evidence_id;
  }
  const normalizedDescription = String(description || '').replace(/\s+/g, ' ').trim();
  const fuzzy = records.find((record) => String(record.claim || '').replace(/\s+/g, ' ').trim() === normalizedDescription);
  if (fuzzy?.evidence_id) return fuzzy.evidence_id;
  const hit = records.find((record) => record.claim === description);
  return hit?.evidence_id || null;
}

function countBySeverity(items, severity) {
  return items.filter((item) => item.severity === severity).length;
}

function normalizeScore(score) {
  if (typeof score !== 'number' || Number.isNaN(score)) return null;
  return score <= 1 ? score * 100 : score;
}

function formatScore(score) {
  const normalized = normalizeScore(score);
  if (normalized === null) return '-';
  return `${Math.round(normalized)}分`;
}

function describeVerdict(score) {
  const normalized = normalizeScore(score);
  if (normalized === null) return '待评估';
  if (normalized >= 85) return '可提交，仅需轻微修订';
  if (normalized >= 70) return '建议修订后提交';
  if (normalized >= 55) return '存在明显问题，需较大修订';
  return '当前不建议直接提交';
}

function scoreToneClass(score) {
  const normalized = normalizeScore(score);
  if (normalized === null) return 'text-slate-500';
  if (normalized >= 85) return 'text-emerald-600';
  if (normalized >= 70) return 'text-blue-600';
  if (normalized >= 55) return 'text-amber-600';
  return 'text-rose-600';
}

function severityPillClass(severity) {
  if (severity === 'critical') return 'pill-critical';
  if (severity === 'major') return 'pill-major';
  if (severity === 'minor') return 'pill-minor';
  return 'pill-info';
}

function severityColor(severity) {
  if (severity === 'critical') return 'bg-rose-500';
  if (severity === 'major') return 'bg-amber-500';
  if (severity === 'minor') return 'bg-sky-500';
  return 'bg-slate-400';
}

function statusPillClass(status) {
  if (status === 'completed') return 'pill-completed';
  if (status === 'running') return 'pill-running';
  if (status === 'skipped') return 'pill-skipped';
  return 'pill-pending';
}

function formatLocation(location) {
  if (!location) return '未提供定位信息';
  if (typeof location === 'string') return truncateText(location, 60);
  if (typeof location !== 'object') return '未提供定位信息';
  const fields = [];
  if (location.page) fields.push(`第 ${location.page} 页`);
  if (location.line) fields.push(`行 ${location.line}`);
  if (location.column) fields.push(`列 ${location.column}`);
  if (location.section) fields.push(`章节 ${location.section}`);
  if (location.anchor_id) fields.push(`锚点 ${location.anchor_id}`);
  if (!fields.length && location.locator) fields.push(truncateText(location.locator, 48));
  if (fields.length) return fields.join(' · ');
  return '未提供定位信息';
}

function simplifyStage(stage) {
  if (!stage) return stage;
  if (stage.includes('format')) return 'format';
  if (stage.includes('reference')) return 'reference';
  if (stage.includes('content')) return 'content';
  return stage;
}

function formatTimestamp(timestamp) {
  if (!timestamp) return '-';
  try {
    return new Date(timestamp * 1000).toLocaleString();
  } catch {
    return String(timestamp);
  }
}

function slugify(value) {
  return String(value || 'fragment')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
}
