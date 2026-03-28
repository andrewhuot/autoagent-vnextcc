import { NavLink } from 'react-router-dom';
import {
  type LucideIcon,
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
  Bot,
  Bell,
  Award,
  Inbox,
  Target,
  ShieldCheck,
} from 'lucide-react';
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

const navSections: NavSection[] = [
  {
    title: 'Operate',
    items: [
      { to: '/', label: 'Dashboard', icon: LayoutDashboard },
      { to: '/demo', label: 'Demo', icon: Sparkles },
      { to: '/assistant', label: 'Assistant Chat', icon: Bot },
      { to: '/evals', label: 'Eval Runs', icon: FlaskConical },
      { to: '/conversations', label: 'Conversations', icon: MessageSquare },
      { to: '/loop', label: 'Loop Monitor', icon: RefreshCw },
      { to: '/deploy', label: 'Deploy', icon: Rocket },
      { to: '/traces', label: 'Traces', icon: Activity },
      { to: '/events', label: 'Event Log', icon: ScrollText },
    ],
  },
  {
    title: 'Improve',
    items: [
      { to: '/optimize', label: 'Optimize', icon: Zap },
      { to: '/live-optimize', label: 'Live Optimize', icon: Sparkles },
      { to: '/agent-studio', label: 'Agent Studio Draft', icon: Sparkles },
      { to: '/opportunities', label: 'Opportunities', icon: Flag },
      { to: '/changes', label: 'Changes', icon: GitPullRequest },
      { to: '/experiments', label: 'Experiments', icon: TestTubes },
      { to: '/autofix', label: 'AutoFix', icon: Wrench },
    ],
  },
  {
    title: 'Integrations',
    items: [
      { to: '/adk/import', label: 'ADK Import', icon: Download },
      { to: '/adk/deploy', label: 'ADK Deploy', icon: Upload },
      { to: '/cx/import', label: 'CX Import', icon: Download },
      { to: '/cx/deploy', label: 'CX Deploy', icon: Upload },
    ],
  },
  {
    title: 'Governance',
    items: [
      { to: '/judge-ops', label: 'Judge Ops', icon: Scale },
      { to: '/configs', label: 'Configs', icon: Settings2 },
      { to: '/memory', label: 'Memory', icon: Brain },
      { to: '/runbooks', label: 'Runbooks', icon: Library },
      { to: '/scorer-studio', label: 'Scorer Studio', icon: Sparkles },
      { to: '/notifications', label: 'Notifications', icon: Bell },
    ],
  },
  {
    title: 'Analysis',
    items: [
      { to: '/context', label: 'Context Workbench', icon: Layers },
      { to: '/intelligence', label: 'Build Agent', icon: BrainCircuit },
      { to: '/skills', label: 'Skills', icon: Zap },
      { to: '/registry', label: 'Registry', icon: BookOpen },
      { to: '/agent-skills', label: 'Agent Skills', icon: Sparkles },
      { to: '/blame', label: 'Blame Map', icon: MapPin },
    ],
  },
  {
    title: 'Policy Optimization',
    items: [
      { to: '/reward-studio', label: 'Reward Studio', icon: Award },
      { to: '/preference-inbox', label: 'Preference Inbox', icon: Inbox },
      { to: '/policy-candidates', label: 'Policy Candidates', icon: Target },
      { to: '/reward-audit', label: 'Reward Audit', icon: ShieldCheck },
    ],
  },
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

        <nav className="flex-1 space-y-4 overflow-y-auto px-3 py-2">
          {navSections.map((section) => (
            <div key={section.title}>
              <h3 className="mb-1.5 px-2.5 text-[11px] font-semibold uppercase tracking-wider text-gray-400">
                {section.title}
              </h3>
              <div className="space-y-0.5">
                {section.items.map(({ to, label, icon: Icon }) => (
                  <NavLink
                    key={to}
                    to={to}
                    end={to === '/'}
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

        <div className="space-y-0.5 px-3 py-2">
          <NavLink
            to="/settings"
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
            <Settings className="h-4 w-4 shrink-0" />
            <span>Settings</span>
          </NavLink>
        </div>

        <div className="border-t border-gray-100 px-5 py-3">
          <kbd className="text-[11px] text-gray-400">&#8984;K</kbd>
          <span className="ml-1.5 text-[11px] text-gray-400">Command palette</span>
        </div>
      </aside>
    </>
  );
}
