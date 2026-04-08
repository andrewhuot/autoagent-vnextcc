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
  platform: 'adk',
  source: 'adk-import',
  summary: {
    total_surfaces: 2,
    imported_surfaces: 2,
    optimizable_surfaces: 2,
    read_only_surfaces: 0,
    unsupported_surfaces: 0,
    supported_parity_surfaces: 2,
    partial_parity_surfaces: 0,
    read_only_parity_surfaces: 0,
    unsupported_parity_surfaces: 0,
    ready_export_surfaces: 2,
    lossy_export_surfaces: 0,
    blocked_export_surfaces: 0,
  },
  surfaces: [
    {
      surface_id: 'instructions',
      label: 'Instructions',
      coverage_status: 'imported',
      parity_status: 'supported',
      portability_status: 'optimizable',
      export_status: 'ready',
      optimization_surface_id: 'instructions',
      rationale: ['System prompt imported and writable.'],
      source_refs: [],
      documentation_refs: [],
      code_refs: [],
      metadata: { item_count: 1, optimizable_count: 1 },
    },
    {
      surface_id: 'tools',
      label: 'Tools',
      coverage_status: 'imported',
      parity_status: 'supported',
      portability_status: 'optimizable',
      export_status: 'ready',
      optimization_surface_id: 'tools',
      rationale: ['All declared tools are portable.'],
      source_refs: [],
      documentation_refs: [],
      code_refs: [],
      metadata: { item_count: 5, optimizable_count: 5 },
    },
  ],
  callbacks: [],
  topology: {
    nodes: [],
    edges: [],
    summary: {
      node_count: 4,
      edge_count: 3,
      max_depth: 2,
      agent_count: 2,
      tool_count: 5,
      callback_count: 0,
      flow_count: 0,
      page_count: 0,
      intent_count: 0,
      webhook_count: 0,
      test_case_count: 0,
      orchestration_modes: ['router'],
    },
  },
  optimization_eligibility: {
    score: 92,
    coverage_score: 92,
    optimizability_score: 92,
    export_score: 92,
    blockers: [],
    rationale: ['High parity and export readiness.'],
  },
  export_matrix: {
    status: 'ready',
    round_trip_ready: true,
    ready_surfaces: ['instructions', 'tools'],
    lossy_surfaces: [],
    blocked_surfaces: [],
    surfaces: [],
    rationale: ['Round-trip ready.'],
  },
  notes: [],
};

const PARTIAL_REPORT: PortabilityReport = {
  platform: 'adk',
  source: 'adk-import',
  summary: {
    total_surfaces: 3,
    imported_surfaces: 3,
    optimizable_surfaces: 2,
    read_only_surfaces: 0,
    unsupported_surfaces: 1,
    supported_parity_surfaces: 1,
    partial_parity_surfaces: 1,
    read_only_parity_surfaces: 0,
    unsupported_parity_surfaces: 1,
    ready_export_surfaces: 1,
    lossy_export_surfaces: 1,
    blocked_export_surfaces: 1,
  },
  surfaces: [
    {
      surface_id: 'instructions',
      label: 'Instructions',
      coverage_status: 'imported',
      parity_status: 'supported',
      portability_status: 'optimizable',
      export_status: 'ready',
      optimization_surface_id: 'instructions',
      rationale: ['Prompt imported cleanly.'],
      source_refs: [],
      documentation_refs: [],
      code_refs: [],
      metadata: { item_count: 1, optimizable_count: 1 },
    },
    {
      surface_id: 'tools',
      label: 'Tools',
      coverage_status: 'partial',
      parity_status: 'partial',
      portability_status: 'optimizable',
      export_status: 'lossy',
      optimization_surface_id: 'tools',
      rationale: ['3 of 5 tools are optimizable.'],
      source_refs: [],
      documentation_refs: [],
      code_refs: [],
      metadata: { item_count: 5, optimizable_count: 3, opaque_code_tool_count: 2 },
    },
    {
      surface_id: 'callbacks',
      label: 'Callbacks',
      coverage_status: 'missing',
      parity_status: 'unsupported',
      portability_status: 'unsupported',
      export_status: 'blocked',
      optimization_surface_id: 'callbacks',
      rationale: ['Custom callbacks are not modeled.'],
      source_refs: [],
      documentation_refs: [],
      code_refs: [],
      metadata: {},
    },
  ],
  callbacks: [
    {
      name: 'before_model',
      binding: 'app.callbacks.before_model',
      stage: 'before_model',
      source_ref: 'agent.py:12',
      portability_status: 'unsupported',
      export_status: 'blocked',
      rationale: ['Detected but not portable.'],
      metadata: {},
    },
  ],
  topology: {
    nodes: [],
    edges: [],
    summary: {
      node_count: 4,
      edge_count: 3,
      max_depth: 2,
      agent_count: 2,
      tool_count: 5,
      callback_count: 1,
      flow_count: 0,
      page_count: 0,
      intent_count: 0,
      webhook_count: 0,
      test_case_count: 0,
      orchestration_modes: ['router'],
    },
  },
  optimization_eligibility: {
    score: 58,
    coverage_score: 65,
    optimizability_score: 58,
    export_score: 41,
    blockers: ['Export may lose callback wiring'],
    rationale: ['Partially portable with blocked callback round-trip.'],
  },
  export_matrix: {
    status: 'lossy',
    round_trip_ready: false,
    ready_surfaces: ['instructions'],
    lossy_surfaces: ['tools'],
    blocked_surfaces: ['callbacks'],
    surfaces: [],
    rationale: ['Round-trip is lossy because callback support is missing.'],
  },
  notes: ['One tool has opaque code'],
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

    expect(screen.getByTestId('readiness-report')).toBeInTheDocument();
    expect(screen.getByText('92%')).toBeInTheDocument();
    expect(screen.getByText('Ready for optimization')).toBeInTheDocument();
    expect(screen.getByText('Instructions')).toBeInTheDocument();
    expect(screen.getByText('Tools')).toBeInTheDocument();
    expect(screen.queryByText('Warnings & Recommendations')).not.toBeInTheDocument();
  });

  it('renders partial report with warnings and topology', () => {
    renderReport({ report: PARTIAL_REPORT, adapter: 'ADK' });

    expect(screen.getByText('Imported with gaps — review before optimizing')).toBeInTheDocument();
    expect(screen.getByText('58%')).toBeInTheDocument();
    expect(screen.getByText('Agent Topology')).toBeInTheDocument();
    expect(screen.getByText('1 callback')).toBeInTheDocument();
    expect(screen.getByText('2 code tools (opaque)')).toBeInTheDocument();
    expect(screen.getByText('Warnings & Recommendations')).toBeInTheDocument();
    expect(screen.getByText('One tool has opaque code')).toBeInTheDocument();
    expect(screen.getByText('Export may lose callback wiring')).toBeInTheDocument();
    expect(screen.getByText(/2 critical issues/)).toBeInTheDocument();
  });

  it('renders unsupported verdict with red styling', () => {
    const unsupported: PortabilityReport = {
      ...PARTIAL_REPORT,
      optimization_eligibility: {
        ...PARTIAL_REPORT.optimization_eligibility,
        score: 10,
        blockers: ['Not mappable'],
      },
      summary: {
        ...PARTIAL_REPORT.summary,
        unsupported_surfaces: 3,
      },
      notes: [],
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
    expect(screen.getByText('Run evaluations')).toBeInTheDocument();
    expect(screen.getByText('Inspect gaps')).toBeInTheDocument();
    expect(screen.getByText('Review export blockers')).toBeInTheDocument();
  });
});
