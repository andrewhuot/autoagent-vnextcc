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
