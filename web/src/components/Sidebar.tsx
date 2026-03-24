import { NavLink } from 'react-router-dom';
import {
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
} from 'lucide-react';
import { classNames } from '../lib/utils';

const navItems = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard },
  { to: '/evals', label: 'Eval Runs', icon: FlaskConical },
  { to: '/optimize', label: 'Optimize', icon: Zap },
  { to: '/configs', label: 'Configs', icon: Settings2 },
  { to: '/conversations', label: 'Conversations', icon: MessageSquare },
  { to: '/deploy', label: 'Deploy', icon: Rocket },
  { to: '/loop', label: 'Loop Monitor', icon: RefreshCw },
  { to: '/opportunities', label: 'Opportunities', icon: Flag },
  { to: '/experiments', label: 'Experiments', icon: TestTubes },
  { to: '/traces', label: 'Traces', icon: Activity },
  { to: '/events', label: 'Event Log', icon: ScrollText },
  { to: '/autofix', label: 'AutoFix', icon: Wrench },
  { to: '/judge-ops', label: 'Judge Ops', icon: Scale },
  { to: '/context', label: 'Context Workbench', icon: Layers },
  { to: '/registry', label: 'Registry', icon: BookOpen },
  { to: '/blame', label: 'Blame Map', icon: MapPin },
  { to: '/scorer-studio', label: 'Scorer Studio', icon: Sparkles },
  { to: '/settings', label: 'Settings', icon: Settings },
];

interface SidebarProps {
  mobileOpen: boolean;
  onClose: () => void;
}

export function Sidebar({ mobileOpen, onClose }: SidebarProps) {
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

        <nav className="flex-1 space-y-0.5 overflow-y-auto px-3 py-2">
          {navItems.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              onClick={onClose}
              className={({ isActive }) =>
                classNames(
                  'group flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-[13px] transition-colors',
                  isActive
                    ? 'bg-gray-100 font-medium text-gray-900'
                    : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900'
                )
              }
            >
              <Icon className="h-4 w-4 shrink-0" />
              <span>{label}</span>
            </NavLink>
          ))}
        </nav>

        <div className="border-t border-gray-100 px-5 py-3">
          <kbd className="text-[11px] text-gray-400">&#8984;K</kbd>
          <span className="ml-1.5 text-[11px] text-gray-400">Command palette</span>
        </div>
      </aside>
    </>
  );
}
