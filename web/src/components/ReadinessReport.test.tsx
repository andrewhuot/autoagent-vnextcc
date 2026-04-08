import { describe, expect, it } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { render, screen } from '@testing-library/react';
import { ReadinessReport } from './ReadinessReport';
import type { PortabilityReport } from '../lib/types';

function renderReport(props: Parameters<typeof ReadinessReport>[0]) {
  return render(
    <MemoryRouter>
      <ReadinessReport {...props} />
    </MemoryRouter>
  );
}

const FULL_REPORT: PortabilityReport = {
  overall_score: 92,
  verdict: 'ready',
  surfaces: [
    { name: 'instructions', status: 'full', detail: 'Prompt imported', item_count: 1, optimizable_count: 1 },
    { name: 'tools', status: 'full', detail: 'All tools optimizable', item_count: 5, optimizable_count: 5 },
  ],
  warnings: [],
};

const PARTIAL_REPORT: PortabilityReport = {
  overall_score: 58,
  verdict: 'partial',
  surfaces: [
    { name: 'instructions', status: 'full', detail: 'Prompt imported', item_count: 1, optimizable_count: 1 },
    { name: 'tools', status: 'partial', detail: '3 of 5 tools optimizable', item_count: 5, optimizable_count: 3 },
    { name: 'callbacks', status: 'unsupported', detail: 'Not supported' },
  ],
  warnings: [
    { severity: 'warning', category: 'code_tools', message: 'Two tools have opaque code', recommendation: 'Review manually' },
    { severity: 'critical', category: 'round_trip', message: 'Export may lose callback wiring', recommendation: 'Test round-trip before deploying' },
  ],
  topology: {
    node_count: 4,
    edge_count: 3,
    max_depth: 2,
    has_cycles: true,
    callback_count: 2,
    code_tool_count: 2,
  },
};

describe('ReadinessReport', () => {
  it('renders fallback when report is null', () => {
    renderReport({ report: null, fallbackSurfaces: ['instructions', 'tools'], fallbackToolsCount: 3 });

    expect(screen.getByText('Import Summary')).toBeInTheDocument();
    expect(screen.getByText(/Detailed readiness analysis is not yet available/)).toBeInTheDocument();
    expect(screen.getByText(/instructions, tools/)).toBeInTheDocument();
  });

  it('renders full ready report with score and surfaces', () => {
    renderReport({ report: FULL_REPORT, adapter: 'ADK' });

    const report = screen.getByTestId('readiness-report');
    expect(report).toBeInTheDocument();

    // Score
    expect(screen.getByText('92%')).toBeInTheDocument();

    // Verdict
    expect(screen.getByText('Ready for optimization')).toBeInTheDocument();

    // Surfaces
    expect(screen.getByText('instructions')).toBeInTheDocument();
    expect(screen.getByText('tools')).toBeInTheDocument();

    // No warnings section when empty
    expect(screen.queryByText('Warnings & Recommendations')).not.toBeInTheDocument();
  });

  it('renders partial report with warnings and topology', () => {
    renderReport({ report: PARTIAL_REPORT, adapter: 'ADK' });

    // Verdict
    expect(screen.getByText('Imported with gaps — review before optimizing')).toBeInTheDocument();

    // Score
    expect(screen.getByText('58%')).toBeInTheDocument();

    // Topology
    expect(screen.getByText('Agent Topology')).toBeInTheDocument();
    expect(screen.getByText('4')).toBeInTheDocument(); // node_count
    expect(screen.getByText('Cycles detected')).toBeInTheDocument();
    expect(screen.getByText('2 callbacks')).toBeInTheDocument();
    expect(screen.getByText('2 code tools (opaque)')).toBeInTheDocument();

    // Warnings
    expect(screen.getByText('Warnings & Recommendations')).toBeInTheDocument();
    expect(screen.getByText('Two tools have opaque code')).toBeInTheDocument();
    expect(screen.getByText('Export may lose callback wiring')).toBeInTheDocument();

    // Critical count in summary
    expect(screen.getByText(/1 critical issue/)).toBeInTheDocument();
  });

  it('renders unsupported verdict with red styling', () => {
    const unsupported: PortabilityReport = {
      overall_score: 10,
      verdict: 'unsupported',
      surfaces: [{ name: 'custom', status: 'unsupported', detail: 'Entirely custom framework' }],
      warnings: [{ severity: 'critical', category: 'structure', message: 'Not mappable', recommendation: 'Manual port needed' }],
    };
    renderReport({ report: unsupported });

    expect(screen.getByText('Not well-suited for AgentLab optimization')).toBeInTheDocument();
    expect(screen.getByText('10%')).toBeInTheDocument();
  });

  it('shows CX adapter label in fallback', () => {
    renderReport({ report: null, adapter: 'CX' });

    expect(screen.getByText(/CX import/)).toBeInTheDocument();
  });

  it('derives next-step actions from verdict', () => {
    renderReport({ report: PARTIAL_REPORT, adapter: 'ADK' });

    // Should have eval + inspect links
    expect(screen.getByText('Run evaluations')).toBeInTheDocument();
    expect(screen.getByText('Inspect gaps')).toBeInTheDocument();
    expect(screen.getByText('Review critical warnings')).toBeInTheDocument();
  });
});
