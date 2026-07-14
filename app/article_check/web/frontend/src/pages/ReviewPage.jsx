import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ExternalLink, FileText, Loader2, Search, Upload } from 'lucide-react';
import { api } from '../api/client';
import ReviewStudio from '../components/ReviewStudio';

export default function ReviewPage() {
  const [files, setFiles] = useState([]);
  const [results, setResults] = useState([]);
  const [selectedResultId, setSelectedResultId] = useState(null);
  const [detailTarget, setDetailTarget] = useState(null);
  const [focusedFragmentId, setFocusedFragmentId] = useState(null);
  const [question, setQuestion] = useState('');
  const [answer, setAnswer] = useState('');
  const [asking, setAsking] = useState(false);
  const [snippetLoading, setSnippetLoading] = useState(false);
  const [sourceSnippet, setSourceSnippet] = useState(null);
  const [loading, setLoading] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [deepReview, setDeepReview] = useState(false);
  const [reviewTrack, setReviewTrack] = useState('graduate');
  const [uploading, setUploading] = useState(false);
  const inputRef = useRef();
  const focusTimerRef = useRef(null);

  const handleUpload = useCallback(async (event) => {
    const selectedFiles = Array.from(event.target.files || []);
    if (!selectedFiles.length) return;

    setUploading(true);
    try {
      const uploaded = [];
      for (const file of selectedFiles) {
        const response = await api.upload(file);
        uploaded.push({ ...(response.data || {}), name: file.name, size: file.size });
      }
      setFiles((prev) => dedupeFiles([...prev, ...uploaded]));
    } catch (error) {
      alert(`上传失败: ${error.message}`);
    }
    setUploading(false);
    if (event.target) {
      event.target.value = '';
    }
  }, []);

  const runReview = useCallback(async () => {
    const queue = dedupeFiles(files);
    if (!queue.length) return;

    setLoading(true);
    setResults([]);
    setSelectedResultId(null);
    setDetailTarget(null);
    setAnswer('');
    try {
      const allResults = [];
      for (const file of queue) {
        const response = deepReview
          ? await api.deepReview(file.path, null, reviewTrack)
          : await api.review(file.path, null, false, reviewTrack);
        const review = unwrapApiPayload(response);
        allResults.push({
          id: buildEntryId(file.path || file.name, review?.meta?.task_id),
          file,
          review,
          displayName: extractDisplayName(file, review),
        });
      }
      setResults(allResults);
      if (allResults[0]) {
        setSelectedResultId(allResults[0].id);
        const firstEvidence = allResults[0].review?.evidence_records?.[0];
        const firstNodeId = Object.keys(allResults[0].review?.workflow?.graph || {})[0];
        if (firstEvidence?.evidence_id) {
          setDetailTarget({ type: 'evidence', id: firstEvidence.evidence_id });
        } else if (firstNodeId) {
          setDetailTarget({ type: 'workflow', id: firstNodeId });
        }
      }
    } catch (error) {
      alert(`审查失败: ${error.message}`);
    }
    setLoading(false);
  }, [files, deepReview, reviewTrack]);

  const runBatchStream = useCallback(async () => {
    const queue = dedupeFiles(files);
    if (!queue.length) return;

    setStreaming(true);
    setResults([]);
    setSelectedResultId(null);
    setDetailTarget(null);
    setAnswer('');
    try {
      const response = await api.batchStream(
        queue.map((file) => file.path),
        { with_deep_review: deepReview, review_track: reviewTrack }
      );
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const packets = buffer.split('\n\n');
        buffer = packets.pop() || '';

        for (const packet of packets) {
          if (!packet.startsWith('data: ')) continue;
          const data = JSON.parse(packet.slice(6));
          if (data.type !== 'result') continue;

          const review = data.review_payload || data;
          const nextEntry = {
            id: buildEntryId(data.paper_title, review?.meta?.task_id),
            file: {
              name: extractDisplayName(null, review, data.paper_title),
              path: review?.meta?.source_paper_path || '',
            },
            review,
            displayName: extractDisplayName(null, review, data.paper_title),
          };
          setResults((prev) => {
            const next = dedupeResults([...prev, nextEntry]);
            if (!selectedResultId && next[0]) {
              setSelectedResultId(next[0].id);
            }
            return next;
          });
        }
      }
    } catch (error) {
      alert(`流式审查失败: ${error.message}`);
    }
    setStreaming(false);
  }, [files, deepReview, reviewTrack]);

  useEffect(() => {
    if (!results.length) {
      setSelectedResultId(null);
      setDetailTarget(null);
      return;
    }

    if (!selectedResultId || !results.some((item) => item.id === selectedResultId)) {
      const first = results[0];
      setSelectedResultId(first.id);
      const firstEvidence = first.review?.evidence_records?.[0];
      const firstNodeId = Object.keys(first.review?.workflow?.graph || {})[0];
      if (firstEvidence?.evidence_id) {
        setDetailTarget({ type: 'evidence', id: firstEvidence.evidence_id });
      } else if (firstNodeId) {
        setDetailTarget({ type: 'workflow', id: firstNodeId });
      }
    }
  }, [results, selectedResultId]);

  useEffect(() => {
    if (!focusedFragmentId) return;
    const element = document.getElementById(focusedFragmentId);
    if (!element) return;

    element.scrollIntoView({ behavior: 'smooth', block: 'center' });
    element.classList.add('ring-2', 'ring-primary-500', 'ring-offset-2');
    if (focusTimerRef.current) {
      window.clearTimeout(focusTimerRef.current);
    }
    focusTimerRef.current = window.setTimeout(() => {
      element.classList.remove('ring-2', 'ring-primary-500', 'ring-offset-2');
    }, 1800);
  }, [focusedFragmentId]);

  const selectedReview = useMemo(
    () => results.find((item) => item.id === selectedResultId)?.review || null,
    [results, selectedResultId]
  );

  useEffect(() => {
    if (!selectedReview || detailTarget?.type !== 'evidence' || !detailTarget?.id) {
      setSourceSnippet(null);
      setSnippetLoading(false);
      return;
    }

    let cancelled = false;
    setSnippetLoading(true);
    api.reportSourceSnippet(selectedReview, detailTarget.id, 4)
      .then((response) => {
        if (!cancelled) {
          setSourceSnippet(response?.data || null);
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setSourceSnippet({
            source_name: '片段预览不可用',
            claim: error.message,
            snippet: {
              excerpt: [{ line_number: null, text: `片段预览失败: ${error.message}` }],
              source_kind: 'error',
            },
          });
        }
      })
      .finally(() => {
        if (!cancelled) {
          setSnippetLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [selectedReview, detailTarget]);

  const askReportQuestion = useCallback(async () => {
    const prompt = question.trim();
    if (!prompt || !selectedReview) return;

    setAsking(true);
    try {
      const response = await api.reportDialogue(selectedReview, prompt);
      setAnswer(response?.data?.answer || '暂无回答。');
    } catch (error) {
      setAnswer(`回答失败: ${error.message}`);
    }
    setAsking(false);
  }, [question, selectedReview]);

  const openFormalReport = useCallback((shouldPrint = false) => {
    const targetPath = selectedReview?.summary?.formal_report_html_path || selectedReview?.formal_report?.html_path;
    if (!targetPath) {
      window.alert('当前报告还没有正式 HTML 导出文件。');
      return;
    }

    const reportUrl = api.reportFileUrl(targetPath);
    const popup = window.open(reportUrl, '_blank');
    if (shouldPrint && popup) {
      popup.addEventListener('load', () => {
        popup.focus();
        popup.print();
      }, { once: true });
    }
  }, [selectedReview]);

  const queuedFiles = dedupeFiles(files);

  return (
    <div className="page-stack">
      <section className="command-deck compact-command-deck">
        <div className="flex flex-col gap-8 xl:flex-row xl:items-center xl:justify-between">
          <div className="max-w-3xl space-y-4">
            <div className="capsule capsule-primary">论文审查</div>
            <div>
              <h1 className="page-title">先找出最需要优先修改的问题</h1>
              <p className="page-subtitle">
                先上传论文，再选择适用的审查类型。系统会把主要问题、原文定位、修改建议和答疑结果放在同一页，方便作者逐项修改，也方便导师快速查看重点。
              </p>
            </div>
            <div className="flex flex-wrap gap-3 text-sm text-slate-500">
              <span className="capsule capsule-muted">{queuedFiles.length} 篇待处理论文</span>
              <span className="capsule capsule-muted">{deepReview ? '已开启深入审查' : '当前为快速审查'}</span>
              <span className="capsule capsule-muted">{reviewTrack === 'undergraduate' ? '按本科论文要求审查' : '按研究生论文要求审查'}</span>
            </div>
          </div>

          <div className="upload-panel space-y-4">
            <div className="upload-panel-head">
              <div>
                <div className="upload-panel-title">开始审查</div>
                <div className="upload-panel-subtitle">支持单篇和多篇论文连续处理，结果会自动汇总到下方报告区</div>
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <span className="text-sm font-medium text-slate-600">论文类型</span>
              <button
                type="button"
                onClick={() => setReviewTrack('undergraduate')}
                className={reviewTrack === 'undergraduate' ? 'btn-primary' : 'btn-outline'}
              >
                本科论文
              </button>
              <button
                type="button"
                onClick={() => setReviewTrack('graduate')}
                className={reviewTrack === 'graduate' ? 'btn-primary' : 'btn-outline'}
              >
                研究生论文
              </button>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <button type="button" onClick={() => inputRef.current?.click()} disabled={uploading} className="btn-primary inline-flex items-center gap-2">
                <Upload className="h-4 w-4" />
                {uploading ? '上传中...' : '选择论文文件'}
              </button>
              <input
                ref={inputRef}
                type="file"
                multiple
                accept=".tex,.ltx,.docx,.pdf"
                className="hidden"
                onChange={handleUpload}
              />
              <button type="button" onClick={runReview} disabled={loading || !queuedFiles.length} className="btn-outline inline-flex items-center gap-2">
                {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
                开始审查
              </button>
              <button type="button" onClick={runBatchStream} disabled={streaming || !queuedFiles.length} className="btn-outline inline-flex items-center gap-2">
                {streaming ? <Loader2 className="h-4 w-4 animate-spin" /> : <ExternalLink className="h-4 w-4" />}
                连续处理多篇
              </button>
            </div>
            <label className="inline-flex items-center gap-2 pt-1 text-sm text-slate-600">
              <input type="checkbox" checked={deepReview} onChange={(event) => setDeepReview(event.target.checked)} className="rounded border-slate-300" />
              开启更细致的内容审查
            </label>
            <div className="queue-files">
              {queuedFiles.length === 0 && <div className="text-sm text-slate-500">还没有添加论文。当前支持 `tex / docx / pdf` 三类文件。</div>}
              {queuedFiles.map((file) => (
                <div key={`${file.path}-${file.name}`} className="queue-file-item">
                  <div className="flex items-center gap-3">
                    <div className="queue-file-icon">
                      <FileText className="h-4 w-4" />
                    </div>
                    <div>
                      <div className="queue-file-name">{file.name}</div>
                      <div className="queue-file-meta">{file.path || '待写入路径'} · {Math.max(1, Math.round((file.size || 0) / 1024))} KB</div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      <ReviewStudio
        results={results}
        selectedResultId={selectedResultId}
        onSelectResult={setSelectedResultId}
        detailTarget={detailTarget}
        onSelectWorkflow={(id) => setDetailTarget({ type: 'workflow', id })}
        onSelectEvidence={(id) => setDetailTarget({ type: 'evidence', id })}
        onJumpEvidence={(id) => {
          setDetailTarget({ type: 'evidence', id });
          setFocusedFragmentId(`report-evidence-${slugify(id)}`);
        }}
        question={question}
        onQuestionChange={setQuestion}
        onAskQuestion={askReportQuestion}
        answer={answer}
        asking={asking}
        sourceSnippet={sourceSnippet}
        snippetLoading={snippetLoading}
        onOpenFormalReport={() => openFormalReport(false)}
        onPrintFormalReport={() => openFormalReport(true)}
        reportFileUrl={selectedReview?.summary?.formal_report_html_path || selectedReview?.formal_report?.html_path ? api.reportFileUrl(selectedReview?.summary?.formal_report_html_path || selectedReview?.formal_report?.html_path) : null}
      />
    </div>
  );
}

function unwrapApiPayload(payload) {
  return payload?.data ?? payload;
}

function buildEntryId(seed, fallback) {
  return `${fallback || seed || 'report'}-${Math.random().toString(36).slice(2, 8)}`;
}

function slugify(value) {
  return String(value || 'fragment')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
}

function dedupeFiles(files) {
  const seen = new Set();
  return files.filter((file) => {
    const key = file.path || `${file.name}-${file.size}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function dedupeResults(items) {
  const seen = new Set();
  return items.filter((item) => {
    const key = item.review?.meta?.task_id || item.file?.path || item.file?.name || item.id;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function extractDisplayName(file, review, fallback = '论文审查报告') {
  if (file?.name) return file.name;
  if (review?.meta?.source_file_name) return review.meta.source_file_name;

  const sourcePath = review?.meta?.source_paper_path;
  if (sourcePath) {
    const normalized = String(sourcePath).split(/[/\\]/).filter(Boolean);
    if (normalized.length) return normalized[normalized.length - 1];
  }

  if (review?.meta?.paper_title) return review.meta.paper_title;
  return fallback;
}
