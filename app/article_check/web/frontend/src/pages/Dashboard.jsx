import React from 'react';
import { Link } from 'react-router-dom';
import { Activity, FileCheck, FileText, ShieldAlert, Sparkles, TrendingUp } from 'lucide-react';

export default function Dashboard({ status }) {
  const features = [
    { icon: FileText, title: '一份能直接使用的审查报告', desc: '把格式问题、参考文献风险和修改建议整理成清楚易读的结果', tone: 'text-primary-700' },
    { icon: ShieldAlert, title: '问题对应原文位置', desc: '看到问题的同时，也能定位到论文里的相关段落或片段', tone: 'text-rose-700' },
    { icon: TrendingUp, title: '参考文献重点提醒', desc: '集中提示引文不一致、缺 DOI 和参考文献不完整等常见问题', tone: 'text-amber-700' },
    { icon: Activity, title: '支持多篇一起看', desc: '单篇、批量结果都汇总到同一页面，方便连续审阅', tone: 'text-sky-700' },
    { icon: Sparkles, title: '围绕报告继续追问', desc: '可以继续问“先改什么”“为什么这样判定”“证据在哪”', tone: 'text-violet-700' },
    { icon: FileCheck, title: '便于打印和提交', desc: '支持查看正式报告、打印导出，方便给导师或学生直接使用', tone: 'text-emerald-700' },
  ];
  return (
    <div className="page-stack">
      <section className="hero-banner">
        <div className="hero-grid">
          <div className="space-y-5">
            <div className="capsule capsule-primary">论文审查助手</div>
            <h1 className="hero-title">把论文问题看清楚，也把修改顺序理清楚</h1>
            <p className="hero-text">
              适合论文作者、导师和审改人员使用。上传论文后，你可以快速看到格式问题、参考文献风险、原文定位片段和可执行的修改建议，减少来回翻找和重复沟通。
            </p>
            <div className="flex flex-wrap gap-3">
              <Link to="/review" className="btn-primary">开始审查论文</Link>
            </div>
          </div>

          <div className="hero-panel">
            <div className="hero-panel-row">
              <span>系统状态</span>
              <span className={`capsule ${status ? 'capsule-success' : 'capsule-danger'}`}>{status ? '在线' : '离线'}</span>
            </div>
            <div className="hero-panel-row">
              <span>Dify</span>
              <span>{status?.dify_enabled ? '已接入' : '待配置'}</span>
            </div>
            <div className="hero-panel-row">
              <span>模板数量</span>
              <span>{status?.templates || 0}</span>
            </div>
            <div className="hero-panel-row">
              <span>AI Provider</span>
              <span>{status?.ai_provider ? String(status.ai_provider).toUpperCase() : '-'}</span>
            </div>
          </div>
        </div>
      </section>

      <section className="grid gap-6 xl:grid-cols-[1.2fr,0.8fr]">
        <div className="surface-card">
          <div className="surface-card-head">
            <div>
              <h2 className="surface-card-title">你可以在这里完成什么</h2>
              <p className="surface-card-subtitle">围绕论文修改最常见的几个需求，把结果一次看清楚</p>
            </div>
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            {features.map(({ icon: Icon, title, desc, tone }) => (
              <div key={title} className="feature-card">
                <div className={`feature-icon ${tone}`}>
                  <Icon className="h-5 w-5" />
                </div>
                <div>
                  <h3 className="feature-title">{title}</h3>
                  <p className="feature-text">{desc}</p>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="surface-card">
          <div className="surface-card-head">
            <div>
              <h2 className="surface-card-title">典型使用流程</h2>
              <p className="surface-card-subtitle">从上传论文到确认修改重点，整个过程尽量放在同一页里完成</p>
            </div>
          </div>
          <div className="space-y-4">
            {[
              '先上传一篇或多篇论文，系统会生成清晰的审查结果。',
              '你可以先看最影响提交的问题，再逐条查看证据和原文位置。',
              '如果对判断结果有疑问，可以继续追问原因、依据和修改顺序。',
              '最后把正式报告打印或导出，直接用于沟通、留档或修改跟进。',
            ].map((item) => (
              <div key={item} className="timeline-item">
                <div className="timeline-dot" />
                <div className="timeline-text">{item}</div>
              </div>
            ))}
          </div>
        </div>
      </section>
    </div>
  );
}
