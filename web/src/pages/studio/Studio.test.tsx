import { describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Studio } from './Studio';

const toastMocks = vi.hoisted(() => ({
  toastError: vi.fn(),
  toastInfo: vi.fn(),
  toastSuccess: vi.fn(),
}));

vi.mock('../../lib/toast', () => ({
  toastError: toastMocks.toastError,
  toastInfo: toastMocks.toastInfo,
  toastSuccess: toastMocks.toastSuccess,
}));

function renderStudio(initialEntry = '/studio') {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route path="/studio" element={<Studio />} />
        <Route path="/optimize" element={<div>Classic Optimize</div>} />
      </Routes>
    </MemoryRouter>
  );
}

// ─── Shell ────────────────────────────────────────────────────────────────────

describe('Studio shell', () => {
  it('renders the studio header with title and agent context', () => {
    renderStudio();
    expect(screen.getByText('Optimize Studio')).toBeInTheDocument();
    // The header paragraph contains the agent context
    const headerPara = screen.getByText(/Spec v4 published/);
    expect(headerPara).toBeInTheDocument();
    expect(headerPara.textContent).toContain('Customer Support Agent');
  });

  it('shows the Build → Eval → Studio breadcrumb trail', () => {
    renderStudio();
    expect(screen.getByText(/Refine, observe, and optimize your agent/)).toBeInTheDocument();
    // The breadcrumb contains Build, Eval, Studio as separate spans
    expect(screen.getByText('Studio')).toBeInTheDocument();
  });

  it('renders three tab buttons with step numbers: Spec, Observe, Optimize', () => {
    renderStudio();
    // Tab buttons contain step numbers; find them by step + label combo
    const tabButtons = screen.getAllByRole('button').filter(
      (btn) => btn.textContent?.match(/^[123]/)
    );
    expect(tabButtons).toHaveLength(3);
    expect(tabButtons[0].textContent).toContain('Spec');
    expect(tabButtons[1].textContent).toContain('Observe');
    expect(tabButtons[2].textContent).toContain('Optimize');
  });

  it('shows step-aware description strip with action hint', () => {
    renderStudio('/studio?tab=spec');
    expect(screen.getByText(/Step 1:/)).toBeInTheDocument();
    expect(screen.getByText(/Review and refine the agent specification/)).toBeInTheDocument();
  });

  it('shows a "Next" button in the description strip to advance tabs', async () => {
    const user = userEvent.setup();
    renderStudio('/studio?tab=spec');
    const nextBtn = screen.getByRole('button', { name: /Next: Observe/ });
    expect(nextBtn).toBeInTheDocument();
    await user.click(nextBtn);
    expect(screen.getByText('Active Issues')).toBeInTheDocument();
  });

  it('does not show Next button on the last tab (Optimize)', () => {
    renderStudio('/studio?tab=optimize');
    expect(screen.queryByRole('button', { name: /^Next:/ })).not.toBeInTheDocument();
  });

  it('defaults to the Spec tab when no ?tab param is present', () => {
    renderStudio('/studio');
    // Spec tab content — textarea and preview pane should be visible
    expect(screen.getByPlaceholderText(/Write your agent spec/i)).toBeInTheDocument();
  });

  it('honours ?tab=observe in the URL', () => {
    renderStudio('/studio?tab=observe');
    expect(screen.getByText('Active Issues')).toBeInTheDocument();
  });

  it('honours ?tab=optimize in the URL', () => {
    renderStudio('/studio?tab=optimize');
    expect(screen.getByText('Optimization Mode')).toBeInTheDocument();
  });

  it('falls back to Spec tab for an invalid ?tab value', () => {
    renderStudio('/studio?tab=invalid_tab');
    expect(screen.getByPlaceholderText(/Write your agent spec/i)).toBeInTheDocument();
  });

  it('switches tabs when the user clicks Observe', async () => {
    const user = userEvent.setup();
    renderStudio('/studio');
    // Use the tab button (contains step number "2"), not the "Next: Observe" button
    const observeTab = screen.getAllByRole('button', { name: /Observe/ })
      .find((el) => el.textContent?.includes('2'));
    await user.click(observeTab!);
    expect(screen.getByText('Active Issues')).toBeInTheDocument();
  });

  it('switches tabs when the user clicks Optimize', async () => {
    const user = userEvent.setup();
    renderStudio('/studio');
    const optimizeTab = screen.getAllByRole('button', { name: /Optimize/ })
      .find((el) => el.textContent?.includes('3'));
    await user.click(optimizeTab!);
    expect(screen.getByText('Optimization Mode')).toBeInTheDocument();
  });

  it('has a link back to Classic Optimize', () => {
    renderStudio();
    const link = screen.getByRole('link', { name: /Classic Optimize/i });
    expect(link).toHaveAttribute('href', '/optimize');
  });
});

// ─── StudioSpec ───────────────────────────────────────────────────────────────

describe('Studio > Spec tab', () => {
  it('renders markdown editor, preview, and version history rail', () => {
    renderStudio('/studio?tab=spec');
    expect(screen.getByPlaceholderText(/Write your agent spec/i)).toBeInTheDocument();
    expect(screen.getByText('Version History')).toBeInTheDocument();
  });

  it('shows 5 versions in the history rail', () => {
    renderStudio('/studio?tab=spec');
    expect(screen.getByText('v5')).toBeInTheDocument();
    expect(screen.getByText('v4')).toBeInTheDocument();
    expect(screen.getByText('v3')).toBeInTheDocument();
    expect(screen.getByText('v2')).toBeInTheDocument();
    expect(screen.getByText('v1')).toBeInTheDocument();
  });

  it('shows published / draft / archived badges on versions', () => {
    renderStudio('/studio?tab=spec');
    expect(screen.getByText('draft')).toBeInTheDocument();
    expect(screen.getAllByText('published').length).toBeGreaterThan(0);
    expect(screen.getAllByText('archived').length).toBeGreaterThan(0);
  });

  it('calls toastSuccess when Save draft is clicked', async () => {
    const user = userEvent.setup();
    renderStudio('/studio?tab=spec');
    await user.click(screen.getByRole('button', { name: /Save draft/i }));
    expect(toastMocks.toastSuccess).toHaveBeenCalledWith('Draft saved');
  });

  it('calls toastSuccess when Publish version is clicked', async () => {
    const user = userEvent.setup();
    renderStudio('/studio?tab=spec');
    await user.click(screen.getByRole('button', { name: /Publish version/i }));
    expect(toastMocks.toastSuccess).toHaveBeenCalledWith(
      expect.stringContaining('published')
    );
  });

  it('toggles to Preview-only mode', async () => {
    const user = userEvent.setup();
    renderStudio('/studio?tab=spec');
    await user.click(screen.getByRole('button', { name: 'Preview' }));
    // Editor textarea should be hidden, preview visible
    const textarea = screen.getByPlaceholderText(/Write your agent spec/i);
    expect(textarea.closest('div')).toHaveClass('hidden');
  });
});

// ─── StudioObserve ────────────────────────────────────────────────────────────

describe('Studio > Observe tab', () => {
  it('renders 4 metric cards', () => {
    renderStudio('/studio?tab=observe');
    expect(screen.getByText('Success Rate')).toBeInTheDocument();
    expect(screen.getByText('P95 Latency')).toBeInTheDocument();
    expect(screen.getByText('Error Rate')).toBeInTheDocument();
    expect(screen.getByText('Cost / Session')).toBeInTheDocument();
  });

  it('renders the first critical issue', () => {
    renderStudio('/studio?tab=observe');
    expect(screen.getByText('Refund lookup fails for international orders')).toBeInTheDocument();
  });

  it('renders all 5 mock issues', () => {
    renderStudio('/studio?tab=observe');
    expect(screen.getByText('Refund lookup fails for international orders')).toBeInTheDocument();
    expect(screen.getByText('Agent invents refund policy terms')).toBeInTheDocument();
    expect(screen.getByText('P95 latency spike on order lookup tool')).toBeInTheDocument();
    expect(screen.getByText('Missing identity verification before account access')).toBeInTheDocument();
    expect(screen.getByText('create_ticket fails on missing category field')).toBeInTheDocument();
  });

  it('shows trace and conversation evidence panels', () => {
    renderStudio('/studio?tab=observe');
    expect(screen.getByText('Trace Evidence')).toBeInTheDocument();
    expect(screen.getByText('Conversation Evidence')).toBeInTheDocument();
  });

  it('selecting an issue filters the evidence panels', async () => {
    const user = userEvent.setup();
    renderStudio('/studio?tab=observe');

    // The first issue is already selected; click to deselect then select another
    const hallucIssue = screen.getByText('Agent invents refund policy terms');
    await user.click(hallucIssue.closest('button')!);

    // Filtered badge should appear in both panels
    expect(screen.getAllByText('Filtered by issue').length).toBeGreaterThanOrEqual(1);
  });

  it('shows critical/high badge count in issue header', () => {
    renderStudio('/studio?tab=observe');
    // 2 critical/high issues by severity in our mock (critical + high + high = 3)
    expect(screen.getByText(/critical\/high/)).toBeInTheDocument();
  });
});

// ─── StudioOptimize ───────────────────────────────────────────────────────────

describe('Studio > Optimize tab', () => {
  it('renders three mode selector cards: Basic, Research, Pro', () => {
    renderStudio('/studio?tab=optimize');
    expect(screen.getByText('Basic')).toBeInTheDocument();
    expect(screen.getByText('Research')).toBeInTheDocument();
    expect(screen.getByText('Pro')).toBeInTheDocument();
  });

  it('Research mode is selected by default', () => {
    renderStudio('/studio?tab=optimize');
    const researchCard = screen.getByText('Research').closest('button')!;
    expect(researchCard.className).toMatch(/border-violet/);
  });

  it('renders the eval set picker with 3 sets', () => {
    renderStudio('/studio?tab=optimize');
    expect(screen.getByText('Core Support Flows')).toBeInTheDocument();
    expect(screen.getByText('Edge Cases & Escalations')).toBeInTheDocument();
    expect(screen.getByText('Policy Adherence')).toBeInTheDocument();
  });

  it('shows run button', () => {
    renderStudio('/studio?tab=optimize');
    expect(screen.getByRole('button', { name: /Run.*Optimization/i })).toBeInTheDocument();
  });

  it('shows candidate comparison table with baseline and candidates', () => {
    renderStudio('/studio?tab=optimize');
    expect(screen.getByText('Current (v4)')).toBeInTheDocument();
    expect(screen.getByText('Candidate A — Refund lookup fix')).toBeInTheDocument();
    // Candidate B appears in both table and the default-open detail panel; use getAllByText
    expect(screen.getAllByText('Candidate B — Policy grounding + refund fix').length).toBeGreaterThan(0);
  });

  it('shows Recommended badge on Candidate B', () => {
    renderStudio('/studio?tab=optimize');
    // Candidate B appears multiple times (table + detail panel); find the table row
    const candBRows = screen.getAllByText('Candidate B — Policy grounding + refund fix');
    const tableRowEl = candBRows.find((el) => el.closest('tr') !== null);
    expect(tableRowEl).toBeDefined();
    const candBRow = tableRowEl!.closest('tr')!;
    expect(within(candBRow).getByText('Recommended')).toBeInTheDocument();
  });

  it('shows diff detail panel when a candidate row is clicked', async () => {
    const user = userEvent.setup();
    renderStudio('/studio?tab=optimize');
    // Click Candidate A row
    await user.click(screen.getByText('Candidate A — Refund lookup fix').closest('tr')!);
    expect(screen.getByRole('button', { name: /Promote to spec/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Reject' })).toBeInTheDocument();
  });

  it('shows spec diff lines in the detail panel', async () => {
    const user = userEvent.setup();
    renderStudio('/studio?tab=optimize');
    await user.click(screen.getByText('Candidate A — Refund lookup fix').closest('tr')!);
    // diff should include the added line with region param
    expect(screen.getByText(/region\?/)).toBeInTheDocument();
  });

  it('calls toastSuccess when Promote is clicked', async () => {
    const user = userEvent.setup();
    renderStudio('/studio?tab=optimize');
    await user.click(screen.getByText('Candidate A — Refund lookup fix').closest('tr')!);
    await user.click(screen.getByRole('button', { name: /Promote to spec/i }));
    expect(toastMocks.toastSuccess).toHaveBeenCalledWith(
      expect.stringContaining('promoted')
    );
  });

  it('calls toastInfo when Reject is clicked', async () => {
    const user = userEvent.setup();
    renderStudio('/studio?tab=optimize');
    await user.click(screen.getByText('Candidate A — Refund lookup fix').closest('tr')!);
    await user.click(screen.getByRole('button', { name: 'Reject' }));
    expect(toastMocks.toastInfo).toHaveBeenCalledWith('Candidate rejected');
  });

  it('switches optimization mode when Basic is clicked', async () => {
    const user = userEvent.setup();
    renderStudio('/studio?tab=optimize');
    await user.click(screen.getByText('Basic').closest('button')!);
    // Basic card should now be selected
    const basicCard = screen.getByText('Basic').closest('button')!;
    expect(basicCard.className).toMatch(/border-blue/);
  });

  it('renders the run log section', () => {
    renderStudio('/studio?tab=optimize');
    expect(screen.getByText('Run Log')).toBeInTheDocument();
    expect(screen.getByText(/Loaded spec v4/)).toBeInTheDocument();
  });

  it('calls toastInfo when Run Optimization is clicked', async () => {
    const user = userEvent.setup();
    renderStudio('/studio?tab=optimize');
    await user.click(screen.getByRole('button', { name: /Run.*Optimization/i }));
    expect(toastMocks.toastInfo).toHaveBeenCalledWith('Optimization run started…');
  });
});
