import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createElement } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import App from '../App';
import { getNavigationSections, getSimpleNavigationSections } from '../lib/navigation';
import { CommandPalette } from './CommandPalette';
import { getRouteContext } from './Layout';
import { Sidebar } from './Sidebar';

vi.mock('../lib/websocket', () => ({
  wsClient: {
    connect: vi.fn(),
    onMessage: vi.fn(() => vi.fn()),
  },
}));

vi.mock('../lib/api', () => ({
  useAgent: () => ({ data: null, isLoading: false }),
  useAgents: () => ({ data: [], isLoading: false }),
  useConfigs: () => ({ data: [] }),
  useConversations: () => ({ data: [] }),
  useEvalRuns: () => ({ data: [] }),
  useApplyCurriculum: () => ({ mutate: vi.fn(), isPending: false }),
  useBuilderArtifacts: () => ({ data: [] }),
  useCurriculumBatches: () => ({ data: [] }),
  useGenerateCurriculum: () => ({ mutate: vi.fn(), isPending: false }),
  useGeneratedSuites: () => ({ data: [], isLoading: false }),
  useSavedBuildArtifacts: () => ({ data: [] }),
  useSaveAgent: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useStartEval: () => ({ mutate: vi.fn(), isPending: false }),
  useStartOptimize: () => ({ mutate: vi.fn(), isPending: false }),
  useOptimizeHistory: () => ({ data: [], isLoading: false, refetch: vi.fn() }),
  useTaskStatus: () => ({ data: null }),
  useTranscriptReports: () => ({ data: [] }),
  useImportTranscriptArchive: () => ({ mutate: vi.fn(), isPending: false }),
  useGenerateAgent: () => ({ mutate: vi.fn(), isPending: false }),
  useChatRefine: () => ({ mutate: vi.fn(), isPending: false }),
  useOpportunities: () => ({ data: [], isLoading: false, isError: false }),
  useExperiments: () => ({ data: [], isLoading: false, isError: false }),
  useParetoFrontier: () => ({ data: { candidates: [], frontier_size: 0, infeasible_count: 0 } }),
  useArchiveEntries: () => ({ data: [] }),
  useJudgeCalibration: () => ({ data: null }),
  useChanges: () => ({ data: [], isLoading: false, isError: false }),
  useApplyChange: () => ({ mutate: vi.fn(), isPending: false }),
  useRejectChange: () => ({ mutate: vi.fn(), isPending: false }),
  useUpdateHunkStatus: () => ({ mutate: vi.fn(), isPending: false }),
  useChangeAuditSummary: () => ({ data: null }),
  useChangeAudit: () => ({ data: null }),
}));

function installLocalStorageMock(initial: Record<string, string> = {}) {
  const store = { ...initial };
  const localStorageMock = {
    getItem: vi.fn((key: string) => (key in store ? store[key] : null)),
    setItem: vi.fn((key: string, value: string) => {
      store[key] = value;
    }),
    removeItem: vi.fn((key: string) => {
      delete store[key];
    }),
    clear: vi.fn(() => {
      Object.keys(store).forEach((key) => delete store[key]);
    }),
    key: vi.fn(),
    get length() {
      return Object.keys(store).length;
    },
  };

  Object.defineProperty(window, 'localStorage', {
    configurable: true,
    value: localStorageMock,
  });

  return { store, localStorageMock };
}

describe('getRouteContext', () => {
  it('uses taxonomy labels for build aliases and review routes', () => {
    expect(getRouteContext('/builder/demo')).toEqual({
      title: 'Build',
      breadcrumbs: [{ label: 'Build' }],
    });

    expect(getRouteContext('/improvements')).toEqual({
      title: 'Improvements',
      breadcrumbs: [{ label: 'Review' }],
    });
  });

  it('keeps eval detail breadcrumbs under the Eval group', () => {
    expect(getRouteContext('/evals/run-1234567890')).toEqual({
      title: 'Eval Detail',
      breadcrumbs: [
        { label: 'Eval' },
        { label: 'Eval Runs', href: '/evals' },
        { label: 'Run run-1234' },
      ],
    });
  });

  it('falls back to AgentLab when a route is unknown', () => {
    expect(getRouteContext('/totally-unknown')).toEqual({
      title: 'AgentLab',
      breadcrumbs: [],
    });
  });
});

describe('Sidebar', () => {
  it('renders the simple navigation by default', () => {
    installLocalStorageMock();
    render(createElement(MemoryRouter, null, createElement(Sidebar, { mobileOpen: true, onClose: vi.fn() })));

    expect(
      screen.getAllByRole('heading', { level: 3 }).map((heading) => heading.textContent)
    ).toEqual(getSimpleNavigationSections().map((section) => section.label));
    expect(screen.getByRole('link', { name: 'Connect' })).toHaveAttribute('href', '/connect');
    expect(screen.getByRole('link', { name: 'CX Studio' })).toHaveAttribute('href', '/cx/studio');
    expect(screen.getByRole('link', { name: 'ADK Import' })).toHaveAttribute('href', '/adk/import');
    expect(screen.getByRole('link', { name: 'CLI' })).toHaveAttribute('href', '/cli');
    expect(screen.getByRole('link', { name: 'Docs' })).toHaveAttribute('href', '/docs');
    expect(screen.queryByRole('link', { name: 'CX Import' })).not.toBeInTheDocument();
  });

  it('toggles to the full navigation surface and persists pro mode', async () => {
    const user = userEvent.setup();
    const { localStorageMock } = installLocalStorageMock();

    render(createElement(MemoryRouter, null, createElement(Sidebar, { mobileOpen: true, onClose: vi.fn() })));

    await user.click(screen.getByRole('button', { name: /show all pages/i }));

    expect(
      screen.getAllByRole('heading', { level: 3 }).map((heading) => heading.textContent)
    ).toEqual(getNavigationSections().map((section) => section.label));
    expect(screen.getByRole('link', { name: 'CX Import' })).toHaveAttribute('href', '/cx/import');
    expect(localStorageMock.setItem).toHaveBeenCalledWith('agentlab-sidebar-mode', 'pro');
  });
});

describe('CommandPalette', () => {
  it('shows top-level taxonomy navigation items', async () => {
    render(createElement(MemoryRouter, null, createElement(CommandPalette)));

    window.dispatchEvent(new Event('open-command-palette'));

    for (const section of getNavigationSections()) {
      expect((await screen.findAllByRole('button', { name: section.label })).length).toBeGreaterThan(0);
    }
  });
});

describe('App', () => {
  it('mounts the unified Build workspace at /build', async () => {
    window.history.pushState({}, '', '/build');

    render(createElement(App));

    expect(await screen.findByRole('heading', { name: 'Build', level: 2 })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Prompt' })).toBeInTheDocument();
  });

  it('redirects legacy builder aliases to /build', async () => {
    window.history.pushState({}, '', '/assistant');

    render(createElement(App));

    expect(window.location.pathname).toBe('/build');
    expect(window.location.search).toBe('?tab=builder-chat');
  });

  it('redirects transcript intelligence to the unified transcript tab', async () => {
    window.history.pushState({}, '', '/intelligence');

    render(createElement(App));

    expect(window.location.pathname).toBe('/build');
    expect(window.location.search).toBe('?tab=transcript');
    expect(await screen.findByRole('tab', { name: 'Transcript' })).toHaveAttribute(
      'aria-selected',
      'true'
    );
  });

  it('redirects /eval to the eval runs page', async () => {
    installLocalStorageMock();
    window.history.pushState({}, '', '/eval');

    render(createElement(App));

    expect(window.location.pathname).toBe('/evals');
    expect(await screen.findByText('Pick an agent to start evaluating')).toBeInTheDocument();
  });

  it('redirects /review to the plural review route', async () => {
    installLocalStorageMock();
    window.history.pushState({}, '', '/review');

    render(createElement(App));

    expect(window.location.pathname).toBe('/improvements');
    expect(window.location.search).toBe('?tab=review');
    expect(await screen.findByRole('heading', { name: 'Improvements', level: 2 })).toBeInTheDocument();
  });

  it('mounts the CLI launcher page at /cli', async () => {
    installLocalStorageMock();
    window.history.pushState({}, '', '/cli');

    render(createElement(App));

    expect(await screen.findByRole('heading', { name: 'Launch the CLI' })).toBeInTheDocument();
    expect(screen.getByText('npx agentlab')).toBeInTheDocument();
  });

  it('mounts the documentation page at /docs', async () => {
    installLocalStorageMock();
    window.history.pushState({}, '', '/docs');

    render(createElement(App));

    expect((await screen.findAllByRole('heading', { name: 'Documentation' })).length).toBeGreaterThan(0);
    expect(screen.getByRole('heading', { name: 'Using the CLI' })).toBeInTheDocument();
  });
});
