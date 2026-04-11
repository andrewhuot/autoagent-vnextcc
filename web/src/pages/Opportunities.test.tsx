import { describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Opportunities } from './Opportunities';

const apiMocks = vi.hoisted(() => ({
  useOpportunities: vi.fn(),
}));

vi.mock('../lib/api', () => ({
  useOpportunities: apiMocks.useOpportunities,
}));

function OptimizeLocationProbe() {
  const location = useLocation();
  return <div>Optimize route: {location.search}</div>;
}

function renderOpportunities() {
  return render(
    <MemoryRouter initialEntries={['/opportunities']}>
      <Routes>
        <Route path="/opportunities" element={<Opportunities />} />
        <Route path="/optimize" element={<OptimizeLocationProbe />} />
      </Routes>
    </MemoryRouter>
  );
}

describe('Opportunities', () => {
  it('starts an optimize run from a specific opportunity with context preserved', async () => {
    const user = userEvent.setup();
    apiMocks.useOpportunities.mockReturnValue({
      data: [
        {
          opportunity_id: 'opp-routing',
          failure_family: 'routing_failure',
          affected_agent_path: 'agents.root',
          severity: 0.9,
          prevalence: 0.7,
          recency: 0.8,
          business_impact: 0.6,
          priority_score: 0.78,
          status: 'open',
          recommended_operator_families: ['routing_policy'],
          sample_trace_ids: ['trace-1'],
        },
      ],
      isLoading: false,
      isError: false,
    });

    renderOpportunities();

    await user.click(screen.getByRole('button', { name: 'Optimize this' }));

    expect(await screen.findByText(/Optimize route:/)).toBeInTheDocument();
    expect(screen.getByText(/force=1/)).toBeInTheDocument();
    expect(screen.getByText(/opportunity_id=opp-routing/)).toBeInTheDocument();
    expect(screen.getByText(/objective=Improve\+routing\+failure\+for\+agents.root/)).toBeInTheDocument();
  });
});
