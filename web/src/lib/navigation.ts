import {
  COMMAND_GROUPS,
  COMMAND_TAXONOMY,
  type CommandGroup,
} from '../../../shared/taxonomy';

export interface NavigationItem {
  label: string;
  path: string;
  description?: string;
}

export interface NavigationSection {
  group: CommandGroup;
  label: string;
  description: string;
  items: NavigationItem[];
}

export interface RouteMetadata {
  title: string;
  breadcrumbs: string[];
  redirectTo?: string;
}

const NAVIGATION_SECTIONS: NavigationSection[] = [
  {
    group: 'home',
    label: COMMAND_TAXONOMY.home.label,
    description: COMMAND_TAXONOMY.home.description,
    items: [
      { label: 'Dashboard', path: '/dashboard' },
      { label: 'Setup', path: '/setup' },
    ],
  },
  {
    group: 'build',
    label: COMMAND_TAXONOMY.build.label,
    description: COMMAND_TAXONOMY.build.description,
    items: [{ label: 'Build', path: '/build' }],
  },
  {
    group: 'import',
    label: COMMAND_TAXONOMY.import.label,
    description: COMMAND_TAXONOMY.import.description,
    items: [
      { label: 'CX Import', path: '/cx/import' },
      { label: 'ADK Import', path: '/adk/import' },
    ],
  },
  {
    group: 'eval',
    label: COMMAND_TAXONOMY.eval.label,
    description: COMMAND_TAXONOMY.eval.description,
    items: [{ label: 'Eval Runs', path: '/evals' }],
  },
  {
    group: 'optimize',
    label: COMMAND_TAXONOMY.optimize.label,
    description: COMMAND_TAXONOMY.optimize.description,
    items: [
      { label: 'Optimize', path: '/optimize' },
      { label: 'Live Optimize', path: '/live-optimize' },
      { label: 'Experiments', path: '/experiments' },
      { label: 'Opportunities', path: '/opportunities' },
    ],
  },
  {
    group: 'review',
    label: COMMAND_TAXONOMY.review.label,
    description: COMMAND_TAXONOMY.review.description,
    items: [
      { label: 'Change Review', path: '/changes' },
      { label: 'Reviews', path: '/reviews' },
    ],
  },
  {
    group: 'deploy',
    label: COMMAND_TAXONOMY.deploy.label,
    description: COMMAND_TAXONOMY.deploy.description,
    items: [{ label: 'Deploy', path: '/deploy' }],
  },
  {
    group: 'observe',
    label: COMMAND_TAXONOMY.observe.label,
    description: COMMAND_TAXONOMY.observe.description,
    items: [
      { label: 'Conversations', path: '/conversations' },
      { label: 'Traces', path: '/traces' },
      { label: 'Event Log', path: '/events' },
      { label: 'Blame Map', path: '/blame' },
      { label: 'Context', path: '/context' },
      { label: 'Loop Monitor', path: '/loop' },
    ],
  },
  {
    group: 'govern',
    label: COMMAND_TAXONOMY.govern.label,
    description: COMMAND_TAXONOMY.govern.description,
    items: [
      { label: 'Configs', path: '/configs' },
      { label: 'Judge Ops', path: '/judge-ops' },
      { label: 'Runbooks', path: '/runbooks' },
      { label: 'Skills', path: '/skills' },
      { label: 'Memory', path: '/memory' },
      { label: 'Registry', path: '/registry' },
      { label: 'Scorer Studio', path: '/scorer-studio' },
      { label: 'Notifications', path: '/notifications' },
      { label: 'Reward Studio', path: '/reward-studio' },
      { label: 'Preference Inbox', path: '/preference-inbox' },
      { label: 'Policy Candidates', path: '/policy-candidates' },
      { label: 'Reward Audit', path: '/reward-audit' },
    ],
  },
  {
    group: 'integrations',
    label: COMMAND_TAXONOMY.integrations.label,
    description: COMMAND_TAXONOMY.integrations.description,
    items: [
      { label: 'CX Deploy', path: '/cx/deploy' },
      { label: 'ADK Deploy', path: '/adk/deploy' },
      { label: 'Agent Skills', path: '/agent-skills' },
      { label: 'Sandbox', path: '/sandbox' },
      { label: 'What-If', path: '/what-if' },
      { label: 'Knowledge', path: '/knowledge' },
    ],
  },
  {
    group: 'settings',
    label: COMMAND_TAXONOMY.settings.label,
    description: COMMAND_TAXONOMY.settings.description,
    items: [{ label: 'Settings', path: '/settings' }],
  },
];

const ROUTE_METADATA: Record<string, RouteMetadata> = {
  '/': { title: 'Build', breadcrumbs: ['Build'], redirectTo: '/build' },
  '/build': { title: 'Build', breadcrumbs: ['Build'] },
  '/intelligence': { title: 'Build', breadcrumbs: ['Build'], redirectTo: '/build?tab=transcript' },
  '/builder': { title: 'Build', breadcrumbs: ['Build'], redirectTo: '/build?tab=builder-chat' },
  '/builder/demo': {
    title: 'Build',
    breadcrumbs: ['Build'],
    redirectTo: '/build?tab=builder-chat',
  },
  '/agent-studio': {
    title: 'Build',
    breadcrumbs: ['Build'],
    redirectTo: '/build?tab=builder-chat',
  },
  '/assistant': { title: 'Build', breadcrumbs: ['Build'], redirectTo: '/build?tab=builder-chat' },
  '/dashboard': { title: 'Dashboard', breadcrumbs: ['Home'] },
  '/demo': { title: 'Demo', breadcrumbs: ['Observe'] },
  '/evals': { title: 'Eval Runs', breadcrumbs: ['Eval'] },
  '/optimize': { title: 'Optimize', breadcrumbs: ['Optimize'] },
  '/live-optimize': { title: 'Optimize', breadcrumbs: ['Optimize'] },
  '/experiments': { title: 'Experiments', breadcrumbs: ['Optimize'] },
  '/changes': { title: 'Change Review', breadcrumbs: ['Optimize', 'Review'] },
  '/opportunities': { title: 'Opportunities', breadcrumbs: ['Optimize'] },
  '/deploy': { title: 'Deploy', breadcrumbs: ['Deploy'] },
  '/traces': { title: 'Traces', breadcrumbs: ['Observe'] },
  '/events': { title: 'Event Log', breadcrumbs: ['Observe'] },
  '/blame': { title: 'Blame Map', breadcrumbs: ['Observe'] },
  '/context': { title: 'Context Workbench', breadcrumbs: ['Observe'] },
  '/loop': { title: 'Loop Monitor', breadcrumbs: ['Observe'] },
  '/setup': { title: 'Setup', breadcrumbs: ['Home'] },
  '/configs': { title: 'Configs', breadcrumbs: ['Govern'] },
  '/judge-ops': { title: 'Judge Ops', breadcrumbs: ['Govern'] },
  '/runbooks': { title: 'Runbooks', breadcrumbs: ['Govern'] },
  '/skills': { title: 'Skills', breadcrumbs: ['Govern'] },
  '/memory': { title: 'Memory', breadcrumbs: ['Govern'] },
  '/registry': { title: 'Registry', breadcrumbs: ['Govern'] },
  '/scorer-studio': { title: 'Scorer Studio', breadcrumbs: ['Govern'] },
  '/notifications': { title: 'Notifications', breadcrumbs: ['Govern'] },
  '/reward-studio': { title: 'Reward Studio', breadcrumbs: ['Govern'] },
  '/preference-inbox': { title: 'Preference Inbox', breadcrumbs: ['Govern'] },
  '/policy-candidates': { title: 'Policy Candidates', breadcrumbs: ['Govern'] },
  '/reward-audit': { title: 'Reward Audit', breadcrumbs: ['Govern'] },
  '/cx/import': { title: 'CX Import', breadcrumbs: ['Import'] },
  '/cx/deploy': { title: 'CX Deploy', breadcrumbs: ['Integrations'] },
  '/adk/import': { title: 'ADK Import', breadcrumbs: ['Import'] },
  '/adk/deploy': { title: 'ADK Deploy', breadcrumbs: ['Integrations'] },
  '/agent-skills': { title: 'Agent Skills', breadcrumbs: ['Integrations'] },
  '/sandbox': { title: 'Sandbox', breadcrumbs: ['Integrations'] },
  '/what-if': { title: 'What-If Replay', breadcrumbs: ['Integrations'] },
  '/knowledge': { title: 'Knowledge', breadcrumbs: ['Integrations'] },
  '/reviews': { title: 'Reviews', breadcrumbs: ['Review'] },
  '/settings': { title: 'Settings', breadcrumbs: ['Settings'] },
};

function normalizePathname(pathname: string): string {
  return pathname.split('?')[0]?.split('#')[0] ?? pathname;
}

function getRouteMetadata(pathname: string): RouteMetadata {
  const path = normalizePathname(pathname);
  return ROUTE_METADATA[path] ?? { title: 'AutoAgent', breadcrumbs: [] };
}

export function getNavigationSections(): NavigationSection[] {
  return NAVIGATION_SECTIONS.map((section) => ({
    ...section,
    items: section.items.map((item) => ({ ...item })),
  }));
}

/** Essential pages shown in Simple mode. */
const SIMPLE_MODE_PATHS = new Set([
  '/dashboard',
  '/build',
  '/evals',
  '/optimize',
  '/reviews',
  '/deploy',
]);

export function getSimpleNavigationSections(): NavigationSection[] {
  return NAVIGATION_SECTIONS
    .map((section) => ({
      ...section,
      items: section.items.filter((item) => SIMPLE_MODE_PATHS.has(item.path)),
    }))
    .filter((section) => section.items.length > 0);
}

export function getRouteTitle(pathname: string): string {
  return getRouteMetadata(pathname).title;
}

export function getBreadcrumbForPath(pathname: string): string[] {
  return [...getRouteMetadata(pathname).breadcrumbs];
}

export function getRouteRedirect(pathname: string): string | undefined {
  const path = normalizePathname(pathname);
  const route = ROUTE_METADATA[path];
  if (route?.redirectTo) {
    return route.redirectTo;
  }

  if (path === '/intelligence') {
    return '/build?tab=transcript';
  }

  if (path === '/builder' || path.startsWith('/builder/')) {
    return '/build?tab=builder-chat';
  }

  if (path === '/agent-studio' || path === '/assistant') {
    return '/build?tab=builder-chat';
  }

  return undefined;
}

export { COMMAND_GROUPS, COMMAND_TAXONOMY };
