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
          className="fixed inset-0 z-30 bg-gray-900/35 backdrop-blur-[1px] lg:hidden"
          aria-label="Close navigation"
        />
      )}

      <aside
        className={classNames(
          'fixed inset-y-0 left-0 z-40 flex h-full w-72 flex-col border-r border-gray-200 bg-white/95 shadow-2xl transition-transform duration-200 lg:static lg:w-64 lg:translate-x-0 lg:shadow-none',
          mobileOpen ? 'translate-x-0' : '-translate-x-full'
        )}
      >
        <div className="flex items-center justify-between border-b border-gray-200 px-5 py-4">
          <div className="flex items-center gap-2">
            <span className="text-lg font-semibold tracking-tight text-gray-900">AutoAgent</span>
            <span className="rounded border border-blue-200 bg-blue-50 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-blue-700">
              VNextCC
            </span>
          </div>
          <button
            onClick={onClose}
            className="rounded p-1 text-gray-500 hover:bg-gray-100 hover:text-gray-700 lg:hidden"
            aria-label="Close sidebar"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <nav className="flex-1 space-y-1 overflow-y-auto px-3 py-4">
          {navItems.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              onClick={onClose}
              className={({ isActive }) =>
                classNames(
                  'group flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition-colors duration-150',
                  isActive
                    ? 'bg-blue-600 text-white shadow-sm'
                    : 'text-gray-700 hover:bg-gray-100 hover:text-gray-900'
                )
              }
            >
              <Icon className="h-4 w-4 shrink-0" />
              <span className="font-medium">{label}</span>
            </NavLink>
          ))}
        </nav>

        <div className="border-t border-gray-200 px-5 py-4">
          <p className="text-xs text-gray-500">Command Palette</p>
          <p className="mt-1 font-mono text-xs text-gray-700">Cmd+K</p>
        </div>
      </aside>
    </>
  );
}
