import { getBreadcrumbForPath, getBuildWorkspaceContext, getRouteTitle } from '../lib/navigation';

export interface BreadcrumbItem {
  label: string;
  href?: string;
}

export interface RouteContext {
  title: string;
  breadcrumbs: BreadcrumbItem[];
}

export interface DemoJourneyContext {
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
    const isNewRun = params.get('new') === '1';
    const hasSelectedAgent = Boolean(params.get('agent'));

    return {
      stepLabel: 'Step 2 of 5',
      summary: hasSelectedAgent
        ? 'Run the selected draft'
        : isNewRun
          ? 'Set up an eval run'
          : 'Launch and review evals',
      detail: hasSelectedAgent
        ? 'The same saved config stays selected so you can launch the run without re-choosing it.'
        : isNewRun
          ? 'Choose an agent from the library, or create one in Build, before launching the run.'
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
