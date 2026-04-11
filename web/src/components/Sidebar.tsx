import { NavLink, useLocation } from 'react-router-dom';
import { useState, useEffect } from 'react';
import {
  type LucideIcon,
  Cloud,
  Bot,
  Hammer,
  LayoutDashboard,
  FlaskConical,
  ArrowLeftRight,
  Search,
  Zap,
  Settings2,
  MessageSquare,
  Rocket,
  RefreshCw,
  Settings,
  X,
  Flag,
  TestTubes,
  Activity,
  ScrollText,
  Wrench,
  Scale,
  Layers,
  BookOpen,
  Terminal,
  MapPin,
  Sparkles,
  GitPullRequest,
  Library,
  Brain,
  BrainCircuit,
  Download,
  Upload,
  Bell,
  Award,
  Inbox,
  Target,
  ShieldCheck,
  Workflow,
} from 'lucide-react';
import {
  getNavigationSections,
  getSidebarMode,
  getSimpleNavigationSections,
  setSidebarMode,
} from '../lib/navigation';
import { classNames } from '../lib/utils';

const ICON_BY_PATH: Record<string, LucideIcon> = {
  '/build': Hammer,
  '/workbench': Bot,
  '/agent-improver': BrainCircuit,
  '/intelligence': BrainCircuit,
  '/connect': Download,
  '/cx/studio': Cloud,
  '/cx/import': Download,
  '/adk/import': Download,
  '/evals': FlaskConical,
  '/results': Search,
  '/compare': ArrowLeftRight,
  '/studio': Workflow,
  '/optimize': Zap,
  '/live-optimize': Sparkles,
  '/improvements': Sparkles,
  '/experiments': TestTubes,
  '/changes': GitPullRequest,
  '/reviews': GitPullRequest,
  '/opportunities': Flag,
  '/deploy': Rocket,
  '/dashboard': LayoutDashboard,
  '/conversations': MessageSquare,
  '/traces': Activity,
  '/events': ScrollText,
  '/blame': MapPin,
  '/context': Layers,
  '/loop': RefreshCw,
  '/configs': Settings2,
  '/judge-ops': Scale,
  '/runbooks': Library,
  '/skills': Wrench,
  '/memory': Brain,
  '/registry': BookOpen,
  '/scorer-studio': Sparkles,
  '/notifications': Bell,
  '/reward-studio': Award,
  '/preference-inbox': Inbox,
  '/policy-candidates': Target,
  '/reward-audit': ShieldCheck,
  '/cx/deploy': Upload,
  '/adk/deploy': Upload,
  '/agent-skills': Sparkles,
  '/sandbox': Layers,
  '/what-if': RefreshCw,
  '/knowledge': BookOpen,
  '/cli': Terminal,
  '/docs': BookOpen,
  '/setup': Settings2,
  '/settings': Settings,
};

interface SidebarProps {
  mobileOpen: boolean;
  onClose: () => void;
}

interface GuidedFlowStep {
  label: string;
  matcher: (pathname: string) => boolean;
}

const GUIDED_FLOW_STEPS: GuidedFlowStep[] = [
  {
    label: 'Setup',
    matcher: (pathname) => pathname === '/setup' || pathname === '/dashboard',
  },
  {
    label: 'Build',
    matcher: (pathname) => pathname === '/build',
  },
  {
    label: 'Eval',
    matcher: (pathname) =>
      pathname === '/evals' || pathname.startsWith('/evals/') || pathname === '/results' || pathname === '/compare',
  },
  {
    label: 'Improve',
    matcher: (pathname) => pathname === '/optimize' || pathname === '/studio' || pathname === '/improvements',
  },
  {
    label: 'Deploy',
    matcher: (pathname) => pathname === '/deploy',
  },
];

function getGuidedFlowState(pathname: string) {
  const activeIndex = GUIDED_FLOW_STEPS.findIndex((step) => step.matcher(pathname));
  const boundedIndex = activeIndex === -1 ? 0 : activeIndex;
  const currentStep = GUIDED_FLOW_STEPS[boundedIndex];
  const nextStep = GUIDED_FLOW_STEPS[boundedIndex + 1] ?? null;

  return {
    activeIndex: boundedIndex,
    currentLabel: currentStep.label,
    nextLabel: nextStep?.label ?? 'Done',
  };
}

export function Sidebar({ mobileOpen, onClose }: SidebarProps) {
  const location = useLocation();
  const [simpleMode, setSimpleMode] = useState(() => getSidebarMode() !== 'pro');
  const guidedFlow = getGuidedFlowState(location.pathname);

  useEffect(() => {
    setSidebarMode(simpleMode ? 'simple' : 'pro');
  }, [simpleMode]);

  const sections = (simpleMode ? getSimpleNavigationSections() : getNavigationSections()).map(
    (section) => ({
      title: section.label,
      items: section.items.map((item) => ({
        to: item.path,
        label: item.label,
        icon: ICON_BY_PATH[item.path] ?? Sparkles,
      })),
    })
  );

  return (
    <>
      {mobileOpen && (
        <button
          onClick={onClose}
          className="fixed inset-0 z-30 bg-black/20 backdrop-blur-[1px] lg:hidden"
          aria-label="Close navigation"
        />
      )}

      <aside
        className={classNames(
          'fixed inset-y-0 left-0 z-40 flex h-full w-64 flex-col border-r border-gray-200 bg-white transition-transform duration-200 lg:static lg:translate-x-0',
          mobileOpen ? 'translate-x-0' : '-translate-x-full'
        )}
      >
        <div className="flex items-center gap-2 px-5 py-5">
          <span className="text-[15px] font-semibold tracking-tight text-gray-900">AgentLab</span>
          <span className="rounded-md bg-gray-100 px-1.5 py-0.5 text-[10px] font-medium text-gray-500">
            VNextCC
          </span>
          <button
            onClick={onClose}
            className="ml-auto rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600 lg:hidden"
            aria-label="Close sidebar"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <nav className="flex-1 space-y-4 overflow-y-auto px-3 py-2">
          {simpleMode ? (
            <section className="rounded-2xl border border-sky-200 bg-[linear-gradient(180deg,rgba(240,249,255,0.92),rgba(255,255,255,1))] px-3.5 py-3 shadow-sm shadow-sky-100/70">
              <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-sky-700">
                Guided flow
              </p>
              <p className="mt-2 text-sm font-medium text-slate-900">
                You're on {guidedFlow.currentLabel}. Next up: {guidedFlow.nextLabel}.
              </p>
              <p className="mt-1 text-xs leading-5 text-slate-600">
                Move left to right to keep the product feeling predictable: Setup, Build, Eval, Improve, then Deploy.
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                {GUIDED_FLOW_STEPS.map((step, index) => {
                  const isActive = index === guidedFlow.activeIndex;
                  const isComplete = index < guidedFlow.activeIndex;
                  return (
                    <span
                      key={step.label}
                      className={classNames(
                        'rounded-full border px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.12em]',
                        isActive
                          ? 'border-sky-300 bg-sky-100 text-sky-800'
                          : isComplete
                            ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
                            : 'border-slate-200 bg-white text-slate-500'
                      )}
                    >
                      {step.label}
                    </span>
                  );
                })}
              </div>
            </section>
          ) : null}

          {sections.map((section) => (
            <div key={section.title}>
              <h3 className="mb-1.5 px-2.5 text-[11px] font-semibold uppercase tracking-wider text-gray-400">
                {section.title}
              </h3>
              <div className="space-y-0.5">
                {section.items.map(({ to, label, icon: Icon }) => (
                  <NavLink
                    key={to}
                    to={to}
                    end={to !== '/evals'}
                    onClick={onClose}
                    className={({ isActive }) =>
                      classNames(
                        'group flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-[13px] transition-all duration-150',
                        isActive
                          ? 'bg-gray-900 font-medium text-white shadow-sm'
                          : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900'
                      )
                    }
                  >
                    <Icon className="h-4 w-4 shrink-0" />
                    <span>{label}</span>
                  </NavLink>
                ))}
              </div>
            </div>
          ))}
        </nav>

        <div className="border-t border-gray-100 px-3 py-2">
          <button
            onClick={() => setSimpleMode(!simpleMode)}
            className="flex w-full items-center justify-between rounded-lg px-2.5 py-2 text-[12px] text-gray-500 transition-colors hover:bg-gray-50 hover:text-gray-700"
          >
            <span>{simpleMode ? 'Show all pages →' : '← Simple view'}</span>
            {simpleMode && (
              <span className="rounded bg-indigo-50 px-1.5 py-0.5 text-[10px] font-medium text-indigo-600">
                Pro
              </span>
            )}
          </button>
        </div>

        <div className="border-t border-gray-100 px-5 py-3">
          <kbd className="text-[11px] text-gray-400">&#8984;K</kbd>
          <span className="ml-1.5 text-[11px] text-gray-400">Command palette</span>
        </div>
      </aside>
    </>
  );
}
