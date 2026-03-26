import { describe, it, expect } from 'vitest';
import { buildStudioDraft } from './agentStudio';

describe('buildStudioDraft', () => {
  it('derives focused changes from natural language requests', () => {
    const draft = buildStudioDraft(
      'Make BillingAgent verify invoices before answering and escalate VIP refund requests sooner.'
    );

    expect(draft.focusArea).toBe('Billing Agent');
    expect(draft.changeSet.some((item) => item.title.includes('Invoice'))).toBe(true);
    expect(draft.changeSet.some((item) => item.title.includes('VIP'))).toBe(true);
    expect(draft.reviewChecklist).toContain(
      'Replay a VIP refund conversation through the new path.'
    );
  });

  it('generates default prompt refresh when no specific triggers match', () => {
    const draft = buildStudioDraft('Make things better');

    expect(draft.changeSet.length).toBeGreaterThan(0);
    expect(draft.changeSet[0].kind).toBe('instruction');
    expect(draft.changeSet[0].title).toContain('prompt refresh');
  });

  it('handles routing/handoff keywords', () => {
    const draft = buildStudioDraft('Improve handoff context preservation');

    expect(draft.changeSet.some((item) => item.kind === 'routing')).toBe(true);
    expect(draft.reviewChecklist).toContain(
      'Inspect the handoff transcript to make sure context is preserved end-to-end.'
    );
  });

  it('handles safety/guardrail keywords', () => {
    const draft = buildStudioDraft('Add safety guardrails to prevent data leaks');

    expect(draft.changeSet.some((item) => item.kind === 'policy')).toBe(true);
    expect(draft.changeSet.some((item) => item.title.toLowerCase().includes('safety'))).toBe(true);
  });

  it('projects metrics based on change count', () => {
    const draft = buildStudioDraft(
      'verify invoices, escalate VIP cases, improve routing'
    );

    expect(draft.changeSet.length).toBeGreaterThan(1);
    expect(draft.metrics[0].label).toBe('Quality score');
    expect(parseInt(draft.metrics[0].projected)).toBeGreaterThan(
      parseInt(draft.metrics[0].current)
    );
  });
});
