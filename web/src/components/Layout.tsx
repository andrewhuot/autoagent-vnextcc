import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { Menu, Search } from 'lucide-react';
import { Sidebar } from './Sidebar';
import { CommandPalette } from './CommandPalette';
import { ToastViewport } from './ToastViewport';
import { MockModeBanner } from './MockModeBanner';
import { wsClient } from '../lib/websocket';

export interface BreadcrumbItem {
  label: string;
  href?: string;
}

export interface RouteContext {
  title: string;
  breadcrumbs: BreadcrumbItem[];
}

const staticRouteContexts: Record<string, RouteContext> = {
  '/': { title: 'Builder', breadcrumbs: [{ label: 'Build' }] },
  '/build': { title: 'Builder', breadcrumbs: [{ label: 'Build' }] },
  '/builder': { title: 'Builder', breadcrumbs: [{ label: 'Build' }] },
  '/builder/demo': { title: 'Builder', breadcrumbs: [{ label: 'Build' }] },
  '/dashboard': { title: 'Dashboard', breadcrumbs: [{ label: 'Operate' }] },
  '/demo': { title: 'Demo', breadcrumbs: [{ label: 'Operate' }] },
  '/assistant': { title: 'Builder', breadcrumbs: [{ label: 'Build' }] },
  '/evals': { title: 'Eval Runs', breadcrumbs: [{ label: 'Operate' }] },
  '/optimize': { title: 'Optimize', breadcrumbs: [{ label: 'Improve' }] },
  '/live-optimize': { title: 'Live Optimize', breadcrumbs: [{ label: 'Improve' }] },
  '/configs': { title: 'Config Versions', breadcrumbs: [{ label: 'Governance' }] },
  '/conversations': { title: 'Conversations', breadcrumbs: [{ label: 'Operate' }] },
  '/deploy': { title: 'Deploy', breadcrumbs: [{ label: 'Operate' }] },
  '/loop': { title: 'Loop Monitor', breadcrumbs: [{ label: 'Operate' }] },
  '/opportunities': { title: 'Opportunities', breadcrumbs: [{ label: 'Improve' }] },
  '/changes': {
    title: 'Change Review',
    breadcrumbs: [{ label: 'Improve' }, { label: 'Change Review' }],
  },
  '/experiments': { title: 'Experiments', breadcrumbs: [{ label: 'Improve' }] },
  '/traces': { title: 'Traces', breadcrumbs: [{ label: 'Operate' }] },
  '/events': { title: 'Event Log', breadcrumbs: [{ label: 'Operate' }] },
  '/autofix': { title: 'AutoFix', breadcrumbs: [{ label: 'Improve' }] },
  '/judge-ops': { title: 'Judge Ops', breadcrumbs: [{ label: 'Governance' }] },
  '/context': { title: 'Context Workbench', breadcrumbs: [{ label: 'Analysis' }] },
  '/intelligence': {
    title: 'Intelligence Studio',
    breadcrumbs: [{ label: 'Build' }],
  },
  '/runbooks': { title: 'Runbooks', breadcrumbs: [{ label: 'Governance' }] },
  '/skills': { title: 'Skills', breadcrumbs: [{ label: 'Analysis' }] },
  '/registry': { title: 'Registry Browser', breadcrumbs: [{ label: 'Analysis' }] },
  '/memory': { title: 'Project Memory', breadcrumbs: [{ label: 'Governance' }] },
  '/blame': { title: 'Blame Map', breadcrumbs: [{ label: 'Analysis' }] },
  '/scorer-studio': { title: 'Scorer Studio', breadcrumbs: [{ label: 'Governance' }] },
  '/adk/import': {
    title: 'ADK Import',
    breadcrumbs: [{ label: 'Integrations' }, { label: 'ADK Import' }],
  },
  '/adk/deploy': {
    title: 'ADK Deploy',
    breadcrumbs: [{ label: 'Integrations' }, { label: 'ADK Deploy' }],
  },
  '/cx/import': {
    title: 'CX Import',
    breadcrumbs: [{ label: 'Integrations' }, { label: 'CX Import' }],
  },
  '/cx/deploy': {
    title: 'CX Deploy',
    breadcrumbs: [{ label: 'Integrations' }, { label: 'CX Deploy' }],
  },
  '/agent-skills': { title: 'Agent Skills', breadcrumbs: [{ label: 'Analysis' }] },
  '/agent-studio': {
    title: 'Builder',
    breadcrumbs: [{ label: 'Build' }],
  },
  '/notifications': { title: 'Notifications', breadcrumbs: [{ label: 'Governance' }] },
  '/sandbox': { title: 'Sandbox', breadcrumbs: [{ label: 'Analysis' }] },
  '/knowledge': { title: 'Knowledge', breadcrumbs: [{ label: 'Analysis' }] },
  '/what-if': { title: 'What-If Replay', breadcrumbs: [{ label: 'Analysis' }] },
  '/reviews': { title: 'Collaborative Review', breadcrumbs: [{ label: 'Analysis' }] },
  '/reward-studio': { title: 'Reward Studio', breadcrumbs: [{ label: 'Policy Optimization' }] },
  '/preference-inbox': {
    title: 'Preference Inbox',
    breadcrumbs: [{ label: 'Policy Optimization' }],
  },
  '/policy-candidates': {
    title: 'Policy Candidates',
    breadcrumbs: [{ label: 'Policy Optimization' }],
  },
  '/reward-audit': { title: 'Reward Audit', breadcrumbs: [{ label: 'Policy Optimization' }] },
  '/settings': { title: 'Settings', breadcrumbs: [{ label: 'Governance' }] },
};

export function getRouteContext(pathname: string): RouteContext {
  if (pathname.startsWith('/evals/')) {
    const runId = pathname.split('/')[2] || '';
    return {
      title: 'Eval Detail',
      breadcrumbs: [
        { label: 'Operate' },
        { label: 'Eval Runs', href: '/evals' },
        { label: `Run ${runId.slice(0, 8)}` },
      ],
    };
  }

  if (pathname.startsWith('/builder/')) {
    return { title: 'Builder', breadcrumbs: [{ label: 'Build' }] };
  }

  return staticRouteContexts[pathname] ?? {
    title: 'AutoAgent',
    breadcrumbs: [],
  };
}

function useGlobalShortcuts() {
  const navigate = useNavigate();

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const tag = target?.tagName?.toLowerCase();
      const inTypingElement =
        tag === 'input' || tag === 'textarea' || target?.getAttribute('contenteditable') === 'true';
      if (inTypingElement || event.metaKey || event.ctrlKey || event.altKey) return;

      if (event.key === 'n') {
        event.preventDefault();
        navigate('/evals?new=1');
      }
      if (event.key === 'o') {
        event.preventDefault();
        navigate('/optimize?new=1');
      }
      if (event.key === 'd') {
        event.preventDefault();
        navigate('/deploy?new=1');
      }
    };

    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [navigate]);
}

export function Layout({ children }: { children: ReactNode }) {
  const location = useLocation();
  const routeContext = useMemo(() => getRouteContext(location.pathname), [location.pathname]);
  const title = routeContext.title;
  const crumbItems = routeContext.breadcrumbs;
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);

  useGlobalShortcuts();

  useEffect(() => {
    wsClient.connect();
    return () => {
      // Keep websocket alive across page changes for real-time updates.
    };
  }, []);

  return (
    <div className="flex min-h-screen bg-[var(--color-surface)] text-gray-900">
      <Sidebar mobileOpen={mobileSidebarOpen} onClose={() => setMobileSidebarOpen(false)} />

      <div className="flex min-h-screen min-w-0 flex-1 flex-col">
        <MockModeBanner />
        <header className="sticky top-0 z-20 flex items-center justify-between gap-4 border-b border-gray-200 bg-white/80 px-5 py-3 backdrop-blur-sm">
          <div className="flex min-w-0 items-center gap-3">
            <button
              onClick={() => setMobileSidebarOpen(true)}
              className="rounded-md p-1.5 text-gray-500 hover:bg-gray-100 lg:hidden"
              aria-label="Open navigation"
            >
              <Menu className="h-4 w-4" />
            </button>

            <div className="min-w-0">
              <h1 className="truncate text-[15px] font-semibold text-gray-900">{title}</h1>
              {crumbItems.length > 0 && (
                <div className="flex items-center gap-1 text-xs text-gray-400">
                  {crumbItems.map((crumb, index) => (
                    <span key={`${crumb.label}-${index}`} className="flex items-center gap-1">
                      {crumb.href ? (
                        <Link to={crumb.href} className="hover:text-gray-600">
                          {crumb.label}
                        </Link>
                      ) : (
                        <span className="text-gray-500">{crumb.label}</span>
                      )}
                      {index < crumbItems.length - 1 && <span className="text-gray-300">/</span>}
                    </span>
                  ))}
                </div>
              )}
            </div>
          </div>

          <button
            onClick={() => window.dispatchEvent(new Event('open-command-palette'))}
            className="hidden items-center gap-1.5 rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs text-gray-400 transition hover:border-gray-300 hover:text-gray-500 sm:inline-flex"
            type="button"
          >
            <Search className="h-3 w-3" />
            Search...
            <kbd className="ml-2 rounded border border-gray-200 bg-gray-50 px-1 py-0.5 font-mono text-[10px] text-gray-400">
              &#8984;K
            </kbd>
          </button>
        </header>

        <main className="flex-1 px-5 py-6 sm:px-6">
          <div
            key={location.pathname}
            className="mx-auto w-full max-w-6xl animate-[fadeIn_150ms_ease-out]"
          >
            {children}
          </div>
        </main>
      </div>

      <CommandPalette />
      <ToastViewport />
    </div>
  );
}
