import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { Command, Menu } from 'lucide-react';
import { Sidebar } from './Sidebar';
import { CommandPalette } from './CommandPalette';
import { ToastViewport } from './ToastViewport';
import { wsClient } from '../lib/websocket';

const pageTitles: Record<string, string> = {
  '/': 'Dashboard',
  '/evals': 'Eval Runs',
  '/optimize': 'Optimize',
  '/configs': 'Configs',
  '/conversations': 'Conversations',
  '/deploy': 'Deploy',
  '/loop': 'Loop Monitor',
  '/settings': 'Settings',
};

function getPageTitle(pathname: string): string {
  if (pageTitles[pathname]) return pageTitles[pathname];
  if (pathname.startsWith('/evals/')) return 'Eval Detail';
  return 'AutoAgent';
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

function breadcrumbs(pathname: string): Array<{ label: string; href?: string }> {
  if (pathname === '/') {
    return [{ label: 'Dashboard' }];
  }

  if (pathname.startsWith('/evals/')) {
    const runId = pathname.split('/')[2] || '';
    return [
      { label: 'Eval Runs', href: '/evals' },
      { label: `Run ${runId.slice(0, 8)}` },
    ];
  }

  if (pageTitles[pathname]) {
    return [{ label: pageTitles[pathname] }];
  }

  return [{ label: 'AutoAgent' }];
}

export function Layout({ children }: { children: ReactNode }) {
  const location = useLocation();
  const title = getPageTitle(location.pathname);
  const crumbItems = useMemo(() => breadcrumbs(location.pathname), [location.pathname]);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);

  useGlobalShortcuts();

  useEffect(() => {
    wsClient.connect();
    return () => {
      // Keep websocket alive across page changes for real-time updates.
    };
  }, []);

  return (
    <div className="flex min-h-screen bg-gray-50 text-gray-900">
      <Sidebar mobileOpen={mobileSidebarOpen} onClose={() => setMobileSidebarOpen(false)} />

      <div className="flex min-h-screen min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 border-b border-gray-200 bg-white/95 px-4 py-3 backdrop-blur sm:px-6">
          <div className="flex items-center justify-between gap-4">
            <div className="flex min-w-0 items-center gap-3">
              <button
                onClick={() => setMobileSidebarOpen(true)}
                className="rounded-md border border-gray-200 bg-white p-2 text-gray-600 hover:bg-gray-50 lg:hidden"
                aria-label="Open navigation"
              >
                <Menu className="h-4 w-4" />
              </button>

              <div className="min-w-0">
                <h1 className="truncate text-base font-semibold tracking-tight text-gray-900">{title}</h1>
                <div className="mt-0.5 flex items-center gap-1 text-xs text-gray-500">
                  {crumbItems.map((crumb, index) => (
                    <span key={`${crumb.label}-${index}`} className="flex items-center gap-1">
                      {crumb.href ? (
                        <Link to={crumb.href} className="hover:text-blue-700">
                          {crumb.label}
                        </Link>
                      ) : (
                        <span>{crumb.label}</span>
                      )}
                      {index < crumbItems.length - 1 && <span>/</span>}
                    </span>
                  ))}
                </div>
              </div>
            </div>

            <button
              onClick={() => window.dispatchEvent(new Event('open-command-palette'))}
              className="hidden items-center gap-2 rounded-md border border-gray-200 bg-white px-3 py-1.5 text-xs text-gray-600 hover:bg-gray-50 sm:inline-flex"
              type="button"
            >
              <Command className="h-3.5 w-3.5" />
              Command Palette
              <span className="rounded border border-gray-200 bg-gray-50 px-1.5 py-0.5 font-mono text-[10px]">
                Cmd+K
              </span>
            </button>
          </div>
        </header>

        <main className="flex-1 px-4 py-5 sm:px-6">
          <div key={location.pathname} className="animate-[fadeIn_220ms_ease-out]">
            {children}
          </div>
        </main>
      </div>

      <CommandPalette />
      <ToastViewport />
    </div>
  );
}
