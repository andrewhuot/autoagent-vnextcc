import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { Menu, Search } from 'lucide-react';
import { Sidebar } from './Sidebar';
import { CommandPalette } from './CommandPalette';
import { ToastViewport } from './ToastViewport';
import { MockModeBanner } from './MockModeBanner';
import { getBreadcrumbForPath, getBuildWorkspaceContext, getRouteTitle } from '../lib/navigation';
import { wsClient } from '../lib/websocket';

export interface BreadcrumbItem {
  label: string;
  href?: string;
}

export interface RouteContext {
  title: string;
  breadcrumbs: BreadcrumbItem[];
}

interface DemoJourneyContext {
  stepLabel: string;
  summary: string;
  detail: string;
  activeStep: number;
}

function toBreadcrumbItems(labels: string[]): BreadcrumbItem[] {
  return labels.map((label, index) => {
    if (label === 'Eval Runs' && index > 0) {
      return { label, href: '/evals' };
    }

    return { label };
  });
}

export function getRouteContext(pathname: string, search = ''): RouteContext {
  const normalizedPathname = pathname.split('?')[0]?.split('#')[0] ?? pathname;

  if (normalizedPathname.startsWith('/evals/')) {
    const runId = pathname.split('/')[2] || '';
    return {
      title: 'Eval Detail',
      breadcrumbs: [
        { label: 'Eval' },
        { label: 'Eval Runs', href: '/evals' },
        { label: `Run ${runId.slice(0, 8)}` },
      ],
    };
  }

  if (normalizedPathname === '/build') {
    const tab = new URLSearchParams(search).get('tab');
    return {
      title: getBuildWorkspaceContext(tab).title,
      breadcrumbs: toBreadcrumbItems(getBreadcrumbForPath(normalizedPathname)),
    };
  }

  const title = getRouteTitle(normalizedPathname);
  const breadcrumbs = toBreadcrumbItems(getBreadcrumbForPath(normalizedPathname));

  if (title === 'AgentLab' && breadcrumbs.length === 0) {
    return { title, breadcrumbs };
  }

  return { title, breadcrumbs };
}

// Surface a lightweight demo narrative in shared chrome so Build and Eval pages feel connected.
export function getDemoJourneyContext(pathname: string, search = ''): DemoJourneyContext | null {
  const normalizedPathname = pathname.split('?')[0]?.split('#')[0] ?? pathname;

  if (normalizedPathname === '/build') {
    return {
      stepLabel: 'Step 1 of 5',
      summary: 'Build the draft',
      detail:
        'Shape the config in Build, then use Save & Run Eval to carry that exact saved draft into Eval Runs.',
      activeStep: 0,
    };
  }

  if (normalizedPathname === '/evals') {
    const params = new URLSearchParams(search);
    const carriedFromBuild = params.get('new') === '1';

    return {
      stepLabel: 'Step 2 of 5',
      summary: carriedFromBuild ? 'Run the saved draft from Build' : 'Launch and review evals',
      detail: carriedFromBuild
        ? 'The saved draft stays selected so you can launch the first run without re-choosing the config.'
        : 'Start a run, inspect the results, and compare follow-up iterations from the same page.',
      activeStep: 1,
    };
  }

  if (normalizedPathname === '/optimize' || normalizedPathname === '/studio') {
    return {
      stepLabel: 'Step 3 of 5',
      summary: 'Optimize the agent',
      detail:
        'Use eval results to search for better configs. The optimizer proposes changes you can accept, reject, or tweak.',
      activeStep: 2,
    };
  }

  if (normalizedPathname === '/improvements') {
    return {
      stepLabel: 'Step 4 of 5',
      summary: 'Review improvements',
      detail:
        'Inspect proposed changes, compare before/after scores, and accept the improvements worth keeping.',
      activeStep: 3,
    };
  }

  if (normalizedPathname === '/deploy') {
    return {
      stepLabel: 'Step 5 of 5',
      summary: 'Deploy to production',
      detail:
        'Ship the accepted config. Use canary deploys to test in production before promoting to 100%.',
      activeStep: 4,
    };
  }

  return null;
}

function DemoJourneyStrip({
  context,
}: {
  context: DemoJourneyContext;
}) {
  const steps = [
    { label: 'Build', href: '/build' },
    { label: 'Eval', href: '/evals' },
    { label: 'Optimize', href: '/optimize' },
    { label: 'Review', href: '/improvements' },
    { label: 'Deploy', href: '/deploy' },
  ];

  return (
    <div className="border-b border-sky-100 bg-[linear-gradient(180deg,rgba(248,250,252,0.96),rgba(255,255,255,0.98))]">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-4 px-5 py-3 sm:px-6 lg:flex-row lg:items-center lg:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="inline-flex rounded-full border border-sky-200 bg-sky-50 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-sky-800">
              Journey
            </span>
            <span className="text-xs font-medium text-gray-500">{context.stepLabel}</span>
          </div>
          <p className="mt-1.5 text-sm font-semibold text-gray-900">{context.summary}</p>
          <p className="mt-0.5 max-w-2xl text-sm text-gray-600">{context.detail}</p>
        </div>

        <ol className="flex flex-wrap gap-1.5">
          {steps.map((step, index) => {
            const isActive = context.activeStep === index;
            const isComplete = context.activeStep > index;
            const pillClass = isActive
              ? 'border-sky-200 bg-sky-50 text-sky-800'
              : isComplete
                ? 'border-emerald-200 bg-emerald-50 text-emerald-800'
                : 'border-gray-200 bg-white text-gray-400';

            return (
              <li key={step.label}>
                <Link
                  to={step.href}
                  className={`flex items-center gap-1.5 rounded-full border px-2.5 py-1.5 text-xs font-medium transition hover:border-gray-300 hover:text-gray-700 ${pillClass}`}
                >
                  <span className="flex h-5 w-5 items-center justify-center rounded-full border border-current/20 bg-white text-[10px] font-semibold">
                    {index + 1}
                  </span>
                  {step.label}
                </Link>
              </li>
            );
          })}
        </ol>
      </div>
    </div>
  );
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
  const routeContext = useMemo(
    () => getRouteContext(location.pathname, location.search),
    [location.pathname, location.search]
  );
  const demoJourneyContext = useMemo(
    () => getDemoJourneyContext(location.pathname, location.search),
    [location.pathname, location.search]
  );
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

        {demoJourneyContext ? <DemoJourneyStrip context={demoJourneyContext} /> : null}

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
