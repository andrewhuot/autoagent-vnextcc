import type {
  JourneyStatusSummary,
  OperatorJourneyStep,
  OperatorJourneyStatus,
} from './types';

export interface OperatorJourneyStepDefinition {
  step: OperatorJourneyStep;
  label: string;
  path: string;
  matcher: (pathname: string) => boolean;
}

export interface OperatorJourneyRouteState {
  activeIndex: number;
  currentStep: OperatorJourneyStepDefinition;
  nextStep: OperatorJourneyStepDefinition | null;
}

export const OPERATOR_JOURNEY_STEPS: OperatorJourneyStepDefinition[] = [
  {
    step: 'build',
    label: 'Build',
    path: '/build',
    matcher: (pathname) => pathname === '/build',
  },
  {
    step: 'workbench',
    label: 'Workbench',
    path: '/workbench',
    matcher: (pathname) => pathname === '/workbench',
  },
  {
    step: 'eval',
    label: 'Eval',
    path: '/evals',
    matcher: (pathname) =>
      pathname === '/evals' || pathname.startsWith('/evals/') || pathname === '/results' || pathname === '/compare',
  },
  {
    step: 'optimize',
    label: 'Optimize',
    path: '/optimize',
    matcher: (pathname) => pathname === '/optimize' || pathname === '/studio' || pathname === '/live-optimize',
  },
  {
    step: 'review',
    label: 'Review',
    path: '/improvements?tab=review',
    matcher: (pathname) =>
      pathname === '/improvements' || pathname === '/review' || pathname === '/reviews',
  },
  {
    step: 'deploy',
    label: 'Deploy',
    path: '/deploy',
    matcher: (pathname) => pathname === '/deploy',
  },
];

/** Return the display label from the canonical journey so page cards and sidebar stay in sync. */
export function getOperatorJourneyStepLabel(step: OperatorJourneyStep): string {
  return OPERATOR_JOURNEY_STEPS.find((definition) => definition.step === step)?.label ?? step;
}

/** Match the current route to the canonical operator journey instead of each surface maintaining its own order. */
export function getOperatorJourneyRouteState(pathname: string): OperatorJourneyRouteState {
  const normalizedPathname = pathname.split('?')[0]?.split('#')[0] ?? pathname;
  const activeIndex = OPERATOR_JOURNEY_STEPS.findIndex((step) => step.matcher(normalizedPathname));
  const boundedIndex = activeIndex === -1 ? 0 : activeIndex;
  return {
    activeIndex: boundedIndex,
    currentStep: OPERATOR_JOURNEY_STEPS[boundedIndex],
    nextStep: OPERATOR_JOURNEY_STEPS[boundedIndex + 1] ?? null,
  };
}

/** Build one typed summary object so pages differ only in evidence, not in card shape. */
export function createJourneyStatusSummary(input: {
  currentStep: OperatorJourneyStep;
  status: OperatorJourneyStatus;
  statusLabel: string;
  summary: string;
  nextLabel: string;
  nextDescription: string;
  href?: string;
  disabled?: boolean;
}): JourneyStatusSummary {
  return {
    currentStep: input.currentStep,
    status: input.status,
    statusLabel: input.statusLabel,
    summary: input.summary,
    nextAction: {
      label: input.nextLabel,
      description: input.nextDescription,
      href: input.href,
      disabled: input.disabled,
    },
  };
}
