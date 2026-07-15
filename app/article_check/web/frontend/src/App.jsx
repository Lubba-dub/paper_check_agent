import React, { useState, useEffect } from 'react';
import { Routes, Route, Link, useLocation } from 'react-router-dom';
import {
  Activity,
  FileCheck,
  FileText,
  Github,
  Menu,
  ShieldCheck,
  X,
  BarChart3,
} from 'lucide-react';
import Dashboard from './pages/Dashboard';
import ReviewPage from './pages/ReviewPage';
import { api } from './api/client';

const NAV = [
  { path: '/', label: '首页', icon: BarChart3 },
  { path: '/review', label: '开始检查', icon: FileText },
];

export default function App() {
  const [sidebar, setSidebar] = useState(false);
  const [status, setStatus] = useState(null);
  const location = useLocation();

  useEffect(() => {
    api.status().then(r => setStatus(r.data)).catch(() => setStatus(null));
  }, []);

  return (
    <div className="app-shell">
      <div className="app-glow app-glow-left" />
      <div className="app-glow app-glow-right" />

      <aside className={`app-sidebar ${sidebar ? 'translate-x-0' : '-translate-x-full'} lg:translate-x-0`}>
        <div className="flex items-center justify-between border-b border-white/10 px-6 py-5">
          <Link to="/" className="flex items-center gap-3">
            <div className="brand-mark">
              <FileCheck className="h-5 w-5" />
            </div>
            <div>
              <div className="text-sm font-semibold tracking-[0.24em] text-white/90">ARTICLE CHECK</div>
              <div className="text-xs text-slate-400">论文修改与送审准备</div>
            </div>
          </Link>
          <button onClick={() => setSidebar(false)} className="text-slate-400 lg:hidden">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="px-4 py-5">
          <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-4">
            <div className="text-xs uppercase tracking-[0.24em] text-slate-400">当前服务</div>
            <div className="mt-3 flex items-center gap-2 text-sm text-white">
              <span className={`h-2.5 w-2.5 rounded-full ${status ? 'bg-emerald-400' : 'bg-rose-400'}`} />
              {status ? '检查服务可用' : '暂未连接检查服务'}
            </div>
            <div className="mt-2 text-xs text-slate-400">
              {status?.templates ? `${status.templates} 套检查规则 · ${status.dify_enabled ? '智能检查已就绪' : '智能检查待配置'}` : '正在读取当前服务信息'}
            </div>
            {status?.version && (
              <div className="mt-2 text-xs text-slate-500">
                服务版本: {status.version}
              </div>
            )}
          </div>
        </div>

        <nav className="space-y-1 px-4">
          {NAV.map(({ path, label, icon: Icon }) => (
            <Link
              key={path}
              to={path}
              className={`sidebar-link ${location.pathname === path ? 'sidebar-link-active' : ''}`}
              onClick={() => setSidebar(false)}
            >
              <Icon className="h-4 w-4" /> {label}
            </Link>
          ))}
        </nav>

        <div className="mt-auto px-4 pb-5 pt-6">
          <div className="rounded-2xl border border-white/10 bg-gradient-to-br from-primary-500/20 to-sky-500/10 px-4 py-4">
            <div className="flex items-center gap-2 text-sm font-medium text-white">
              <ShieldCheck className="h-4 w-4 text-primary-300" />
              这次先看什么
            </div>
            <div className="mt-3 space-y-2 text-xs text-slate-300">
              <div className="flex items-center gap-2"><Activity className="h-3.5 w-3.5" /> 哪些地方最容易被导师指出</div>
              <div className="flex items-center gap-2"><Activity className="h-3.5 w-3.5" /> 哪些引用和格式需要先补齐</div>
              <div className="flex items-center gap-2"><Activity className="h-3.5 w-3.5" /> 修改顺序该怎么排</div>
            </div>
          </div>
        </div>
      </aside>

      {sidebar && <div className="fixed inset-0 z-40 bg-slate-950/50 lg:hidden" onClick={() => setSidebar(false)} />}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="app-topbar">
          <div className="flex items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <button onClick={() => setSidebar(true)} className="rounded-full border border-slate-200 bg-white/70 p-2 text-slate-700 shadow-sm lg:hidden">
                <Menu className="h-5 w-5" />
              </button>
              <div>
                <div className="text-xs uppercase tracking-[0.28em] text-slate-500">Before Submission</div>
                <div className="mt-1 text-lg font-semibold text-slate-900">论文修改与送审准备</div>
              </div>
            </div>

            <div className="hidden items-center gap-3 lg:flex">
              <span className="capsule capsule-muted">
                <Activity className="h-3.5 w-3.5" />
                {status?.dify_enabled ? '智能检查已就绪' : '智能检查待配置'}
              </span>
              <span className="capsule capsule-muted">
                <BarChart3 className="h-3.5 w-3.5" />
                当前为交付环境
              </span>
              <a
                href="https://github.com/Lubba-dub/ArticleCheck"
                target="_blank"
                rel="noreferrer"
                className="rounded-full border border-slate-200 bg-white/70 p-2 text-slate-500 transition-colors hover:text-slate-900"
              >
                <Github className="h-5 w-5" />
              </a>
            </div>
          </div>
        </header>

        <main className="app-main">
          <Routes>
            <Route path="/" element={<Dashboard status={status} />} />
            <Route path="/review" element={<ReviewPage />} />
          </Routes>
        </main>
      </div>
    </div>
  );
}
