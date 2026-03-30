import { NavLink } from 'react-router-dom';
import { useState, useEffect } from 'react';
import {
  type LucideIcon,
  Hammer,
  LayoutDashboard,
  FlaskConical,
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
} from 'lucide-react';
import { getNavigationSections, getSimpleNavigationSections } from '../lib/navigation';
import { classNames } from '../lib/utils';

interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
}

interface NavSection {
  title: string;
  items: NavItem[];
}

const ICON_BY_PATH: Record<string, LucideIcon> = {
  '/build': Hammer,
  '/intelligence': BrainCircuit,
  '/cx/import': Download,
  '/adk/import': Download,
  '/evals': FlaskConical,
  '/optimize': Zap,
  '/live-optimize': Sparkles,
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
  '/setup': Settings2,
  '/settings': Settings,
};

interface SidebarProps {
  mobileOpen: boolean;
  onClose: () => void;
}

export function Sidebar({ mobileOpen, onClose }: SidebarProps) {
  const [simpleMode, setSimpleMode] = useState(() => {
    try {
      return localStorage.getItem('autoagent-sidebar-mode') !== 'pro';
    } catch {
      return true;
    }
  });

  useEffect(() => {
    try {
      localStorage.setItem('autoagent-sidebar-mode', simpleMode ? 'simple' : 'pro');
    } catch {
      // ignore
    }
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
          <span className="text-[15px] font-semibold tracking-tight text-gray-900">AutoAgent</span>
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
