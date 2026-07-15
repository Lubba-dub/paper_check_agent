import React from 'react';
import { Link } from 'react-router-dom';
import { Activity, FileCheck, FileText, ShieldAlert, Sparkles, TrendingUp } from 'lucide-react';

export default function Dashboard({ status }) {
  const features = [
    { icon: FileText, title: '先知道这次该从哪改起', desc: '把问题轻重、修改建议和处理顺序放在一起，不用来回切换页面', tone: 'text-primary-700' },
    { icon: ShieldAlert, title: '问题旁边直接给出原文位置', desc: '需要核对时可以马上展开相关片段，减少回到全文反复翻找', tone: 'text-rose-700' },
    { icon: TrendingUp, title: '参考文献风险先单独拎出来', desc: '优先提示缺项、编号不一致、DOI 缺失等最常见的送审问题', tone: 'text-amber-700' },
    { icon: Activity, title: '多篇论文可以连续处理', desc: '适合连续检查多名学生或同一篇论文的多轮版本，结果会集中留在一处', tone: 'text-sky-700' },
    { icon: Sparkles, title: '拿不准的地方可以继续问清楚', desc: '可以继续问“先改哪条”“为什么算问题”“还有哪些没补齐”', tone: 'text-violet-700' },
    { icon: FileCheck, title: '结果页方便打印和发给导师', desc: '支持查看正式报告与留档页面，便于自己修改或给导师快速过目', tone: 'text-emerald-700' },
  ];
  return (
    <div className="page-stack">
      <section className="hero-banner">
        <div className="hero-grid">
          <div className="space-y-5">
            <div className="capsule capsule-primary">送审前先看这里</div>
            <h1 className="hero-title">先把最影响送审的问题找出来</h1>
            <p className="hero-text">
              上传论文后，会把格式问题、参考文献风险、原文对应位置和修改建议整理到同一页，方便作者逐条修改，也方便导师快速判断还差哪几步。
            </p>
            <div className="flex flex-wrap gap-3">
              <Link to="/review" className="btn-primary">上传论文开始检查</Link>
            </div>
          </div>

          <div className="hero-panel">
            <div className="hero-panel-row">
              <span>当前状态</span>
              <span className={`capsule ${status ? 'capsule-success' : 'capsule-danger'}`}>{status ? '在线' : '离线'}</span>
            </div>
            <div className="hero-panel-row">
              <span>智能检查</span>
              <span>{status?.dify_enabled ? '已就绪' : '待配置'}</span>
            </div>
            <div className="hero-panel-row">
              <span>可用模板</span>
              <span>{status?.templates || 0}</span>
            </div>
            <div className="hero-panel-row">
              <span>能力来源</span>
              <span>{status?.ai_provider ? String(status.ai_provider).toUpperCase() : '-'}</span>
            </div>
          </div>
        </div>
      </section>

      <section className="grid gap-6 xl:grid-cols-[1.2fr,0.8fr]">
        <div className="surface-card">
          <div className="surface-card-head">
            <div>
              <h2 className="surface-card-title">你可以在这里完成这些事</h2>
              <p className="surface-card-subtitle">把送审前最常见的检查动作收在一个页面里，尽量少切换</p>
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
              <h2 className="surface-card-title">一般会这样使用</h2>
              <p className="surface-card-subtitle">从上传到安排修改顺序，尽量把来回切换压到最少</p>
            </div>
          </div>
          <div className="space-y-4">
            {[
              '先上传需要检查的论文，页面会生成一份便于阅读的检查结果。',
              '先看会影响送审和提交的重点问题，再决定修改顺序。',
              '需要核对时，直接展开依据和原文片段，不必来回翻文档。',
              '改完后再看正式报告，方便打印、留档或发给导师。',
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
