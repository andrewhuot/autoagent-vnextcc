import { useEffect } from 'react';
import { useSearchParams, Link } from 'react-router-dom';
import {
  Activity,
  ArrowRight,
  Bot,
  FileText,
  Sparkles,
} from 'lucide-react';
import { classNames } from '../../lib/utils';
import { StudioSpec } from './StudioSpec';
import { StudioObserve } from './StudioObserve';
import { StudioOptimize } from './StudioOptimize';
import type { StudioTab } from './studio-types';

// ─── Tab config ───────────────────────────────────────────────────────────────

interface TabConfig {
  id: StudioTab;
  label: string;
  step: number;
  description: string;
  actionHint: string;
  icon: React.ComponentType<{ className?: string }>;
  badge?: string;
}

const TABS: TabConfig[] = [
  {
    id: 'spec',
    label: 'Spec',
    step: 1,
    description: 'Review and refine the agent specification before optimizing.',
    actionHint: 'Edit the spec, then move to Observe to see production issues.',
    icon: FileText,
  },
  {
    id: 'observe',
    label: 'Observe',
    step: 2,
    description: 'See how the agent is performing and where it struggles.',
    actionHint: 'Review issues, then move to Optimize to generate fixes.',
    icon: Activity,
    badge: '5 issues',
  },
  {
    id: 'optimize',
    label: 'Optimize',
    step: 3,
    description: 'Generate, compare, and promote improved agent candidates.',
    actionHint: 'Run optimization, review candidates, and promote the best one.',
    icon: Sparkles,
    badge: '2 ready',
  },
];

// ─── Studio Shell ─────────────────────────────────────────────────────────────

export function Studio() {
  const [searchParams, setSearchParams] = useSearchParams();
  const rawTab = searchParams.get('tab') as StudioTab | null;
  const activeTab: StudioTab = rawTab && ['spec', 'observe', 'optimize'].includes(rawTab) ? rawTab : 'spec';

  useEffect(() => {
    document.title = `Optimize Studio • AgentLab`;
  }, []);

  const setTab = (tab: StudioTab) => {
    setSearchParams({ tab }, { replace: true });
  };

  const activeTabConfig = TABS.find((t) => t.id === activeTab)!;
  const nextTab = TABS.find((t) => t.step === activeTabConfig.step + 1);

  return (
    <div className="flex h-full flex-col bg-white">
      {/* Studio header */}
      <div className="border-b border-gray-200 bg-gradient-to-r from-indigo-950 to-violet-900 px-6 py-4">
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-white/10 backdrop-blur">
              <Bot className="h-5 w-5 text-white" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-[17px] font-semibold text-white">Optimize Studio</h1>
                <span className="rounded-md bg-white/15 px-1.5 py-0.5 text-[10px] font-medium text-white/80">
                  Beta
                </span>
              </div>
              <p className="mt-0.5 text-xs text-white/60">
                Customer Support Agent
                <span className="mx-1.5 text-white/30">·</span>
                Spec v4 published
                <span className="mx-1.5 text-white/30">·</span>
                Production
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <Link
              to="/optimize"
              className="rounded-lg border border-white/20 bg-white/10 px-3 py-1.5 text-xs font-medium text-white/80 hover:bg-white/20 transition-colors"
            >
              Classic Optimize →
            </Link>
          </div>
        </div>

        {/* Step progress indicator */}
        <div className="mt-3 flex items-center gap-1.5 text-[10px] text-white/50">
          <span>Build</span>
          <ArrowRight className="h-2.5 w-2.5" />
          <span>Eval</span>
          <ArrowRight className="h-2.5 w-2.5" />
          <span className="font-semibold text-white/90">Studio</span>
          <span className="ml-1 text-white/40">— Refine, observe, and optimize your agent</span>
        </div>

        {/* Tab nav */}
        <div className="mt-3 flex gap-1">
          {TABS.map((tab) => {
            const Icon = tab.icon;
            const isActive = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => setTab(tab.id)}
                className={classNames(
                  'group flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-all',
                  isActive
                    ? 'bg-white text-gray-900 shadow-sm'
                    : 'text-white/70 hover:bg-white/10 hover:text-white'
                )}
              >
                <span className={classNames(
                  'flex h-5 w-5 items-center justify-center rounded-full text-[10px] font-bold',
                  isActive ? 'bg-indigo-600 text-white' : 'bg-white/20 text-white/80'
                )}>
                  {tab.step}
                </span>
                <Icon className={classNames('h-4 w-4', isActive ? 'text-indigo-600' : '')} />
                <span>{tab.label}</span>
                {tab.badge && (
                  <span
                    className={classNames(
                      'rounded-full px-1.5 py-0.5 text-[10px] font-semibold',
                      isActive
                        ? tab.id === 'observe'
                          ? 'bg-red-100 text-red-700'
                          : 'bg-indigo-100 text-indigo-700'
                        : 'bg-white/20 text-white/80'
                    )}
                  >
                    {tab.badge}
                  </span>
                )}
              </button>
            );
          })}
        </div>
      </div>

      {/* Tab description strip with action hint */}
      <div className="border-b border-gray-100 bg-gray-50 px-6 py-2">
        <div className="flex items-center justify-between">
          <p className="text-[12px] text-gray-600">
            <span className="font-medium text-gray-800">Step {activeTabConfig.step}:</span>{' '}
            {activeTabConfig.description}
          </p>
          {nextTab && (
            <button
              onClick={() => setTab(nextTab.id)}
              className="flex items-center gap-1 text-[11px] font-medium text-indigo-600 hover:text-indigo-800 transition-colors"
            >
              Next: {nextTab.label}
              <ArrowRight className="h-3 w-3" />
            </button>
          )}
        </div>
      </div>

      {/* Tab content — fills remaining height */}
      <div className="flex-1 overflow-hidden">
        {activeTab === 'spec' && <StudioSpec />}
        {activeTab === 'observe' && <StudioObserve />}
        {activeTab === 'optimize' && <StudioOptimize />}
      </div>
    </div>
  );
}
