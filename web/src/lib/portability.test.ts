import { describe, expect, it } from 'vitest';
import { getImportPortabilityReport } from './portability';
import type { PortabilityReport } from './types';

const REPORT: PortabilityReport = {
  platform: 'adk',
  source: 'adk-import',
  summary: {
    total_surfaces: 1,
    imported_surfaces: 1,
    optimizable_surfaces: 1,
    read_only_surfaces: 0,
    unsupported_surfaces: 0,
    supported_parity_surfaces: 1,
    partial_parity_surfaces: 0,
    read_only_parity_surfaces: 0,
    unsupported_parity_surfaces: 0,
    ready_export_surfaces: 1,
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
      rationale: ['Portable'],
      source_refs: [],
      documentation_refs: [],
      code_refs: [],
      metadata: {},
    },
  ],
  callbacks: [],
  topology: {
    nodes: [],
    edges: [],
    summary: {
      node_count: 1,
      edge_count: 0,
      max_depth: 1,
      agent_count: 1,
      tool_count: 0,
      callback_count: 0,
      flow_count: 0,
      page_count: 0,
      intent_count: 0,
      webhook_count: 0,
      test_case_count: 0,
      orchestration_modes: [],
    },
  },
  optimization_eligibility: {
    score: 90,
    coverage_score: 90,
    optimizability_score: 90,
    export_score: 90,
    blockers: [],
    rationale: ['Portable'],
  },
  export_matrix: {
    status: 'ready',
    round_trip_ready: true,
    ready_surfaces: ['instructions'],
    lossy_surfaces: [],
    blocked_surfaces: [],
    surfaces: [],
    rationale: ['Ready'],
  },
  notes: [],
};

describe('getImportPortabilityReport', () => {
  it('prefers the real backend portability_report field when both fields exist', () => {
    const legacy = { ...REPORT, source: 'legacy' };
    expect(
      getImportPortabilityReport({
        portability_report: REPORT,
        portability: legacy,
      })
    ).toEqual(REPORT);
  });

  it('falls back to the legacy portability alias when needed', () => {
    expect(
      getImportPortabilityReport({
        portability: REPORT,
      })
    ).toEqual(REPORT);
  });

  it('returns null when neither report field is present', () => {
    expect(getImportPortabilityReport({})).toBeNull();
  });
});
