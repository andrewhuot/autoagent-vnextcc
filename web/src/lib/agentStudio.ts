/**
 * Agent Studio - Natural language prompt parser for agent configuration changes.
 * Converts plain language requests into structured changesets with diffs, metrics, and review checklists.
 */

export type StudioChangeKind = 'instruction' | 'routing' | 'tooling' | 'policy';
export type StudioImpact = 'low' | 'medium' | 'high';
export type StudioMetricTone = 'positive' | 'neutral' | 'caution';

export interface StudioChangeItem {
  id: string;
  kind: StudioChangeKind;
  title: string;
  detail: string;
  before: string;
  after: string;
  impact: StudioImpact;
}

export interface StudioMetric {
  label: string;
  current: string;
  projected: string;
  tone: StudioMetricTone;
}

export interface StudioDraft {
  prompt: string;
  title: string;
  branchName: string;
  summary: string;
  focusArea: string;
  changeSet: StudioChangeItem[];
  metrics: StudioMetric[];
  reviewChecklist: string[];
}

function clampImpactScore(value: number): StudioImpact {
  if (value >= 8) return 'high';
  if (value >= 5) return 'medium';
  return 'low';
}

function titleCase(value: string): string {
  return value
    .split(/[\s_-]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

function buildBaseReviewChecklist(prompt: string): string[] {
  const normalized = prompt.toLowerCase();
  const checklist = [
    'Verify the diff keeps the original tone and domain constraints intact.',
    'Run a simulation that covers the highest-volume customer path.',
  ];

  if (normalized.includes('vip') || normalized.includes('escalat')) {
    checklist.push('Replay a VIP refund conversation through the new path.');
  }

  if (normalized.includes('invoice') || normalized.includes('billing')) {
    checklist.push('Confirm the agent verifies invoice context before issuing an answer.');
  }

  if (normalized.includes('route') || normalized.includes('handoff')) {
    checklist.push('Inspect the handoff transcript to make sure context is preserved end-to-end.');
  }

  if (normalized.includes('safety') || normalized.includes('guardrail')) {
    checklist.push('Test edge cases to ensure safety guardrails remain active.');
  }

  if (normalized.includes('tool') || normalized.includes('function')) {
    checklist.push('Verify tool calls return expected results in test environment.');
  }

  return checklist;
}

/**
 * Parse a natural language prompt and generate a structured changeset draft.
 */
export function buildStudioDraft(prompt: string): StudioDraft {
  const normalized = prompt.trim().toLowerCase();
  const changeSet: StudioChangeItem[] = [];

  // Extract focus area from prompt
  let focusArea = 'General Configuration';
  if (normalized.includes('billing')) focusArea = 'Billing Agent';
  else if (normalized.includes('refund')) focusArea = 'Refund Agent';
  else if (normalized.includes('support')) focusArea = 'Support Agent';
  else if (normalized.includes('orchestrat') || normalized.includes('router')) focusArea = 'Orchestrator';
  else if (normalized.includes('escalat')) focusArea = 'Escalation Agent';

  // Invoice/billing verification
  if (normalized.includes('invoice') || normalized.includes('billing')) {
    changeSet.push({
      id: 'invoice-guardrail',
      kind: 'instruction',
      title: 'Invoice-first response guardrail',
      detail:
        'Require the agent to ground billing answers in fresh invoice or order context before replying.',
      before: 'Handle billing inquiries and respond to customer balance questions.',
      after: 'Before answering any balance, payment, or shipping question, verify the invoice or order record and cite the finding in the reply. Handle billing inquiries and respond to customer balance questions.',
      impact: clampImpactScore(8),
    });
  }

  // VIP/escalation handling
  if (
    normalized.includes('vip') ||
    normalized.includes('priority') ||
    normalized.includes('escalat') ||
    normalized.includes('associate')
  ) {
    changeSet.push({
      id: 'vip-escalation',
      kind: 'policy',
      title: 'VIP escalation fast lane',
      detail:
        'Escalate frustrated or high-value cases earlier and avoid forcing a repeated self-serve loop.',
      before: 'Attempt self-service resolution before escalating to human support.',
      after: 'If the customer is marked VIP, references repeated frustration, or the refund value is high, hand off to escalation agent within two turns. Otherwise attempt self-service resolution before escalating to human support.',
      impact: clampImpactScore(9),
    });
  }

  // Routing/handoff improvements
  if (normalized.includes('route') || normalized.includes('handoff') || normalized.includes('transfer')) {
    changeSet.push({
      id: 'routing-refresh',
      kind: 'routing',
      title: 'Context-preserving routing update',
      detail:
        'Tighten the orchestrator handoff path so downstream specialists inherit the full conversation state.',
      before: 'Route customer needs to specialists and preserve context.',
      after: 'Route customer needs to specialists and preserve context. Include customer tier, prior actions, and confidence score in every handoff packet.',
      impact: clampImpactScore(7),
    });
  }

  // Tool/integration changes
  if (
    normalized.includes('tool') ||
    normalized.includes('shopify') ||
    normalized.includes('refund') ||
    normalized.includes('shipment') ||
    normalized.includes('function')
  ) {
    changeSet.push({
      id: 'tooling-sync',
      kind: 'tooling',
      title: 'Tool-backed resolution check',
      detail:
        'Add a required system lookup before the agent approves a refund or shipping promise.',
      before: 'Available tools: check_order_status, process_refund',
      after: 'Available tools: check_order_status, lookup_fulfillment_status, process_refund',
      impact: clampImpactScore(6),
    });
  }

  // Safety/guardrails
  if (normalized.includes('safety') || normalized.includes('guardrail') || normalized.includes('complian')) {
    changeSet.push({
      id: 'safety-guardrail',
      kind: 'policy',
      title: 'Enhanced safety guardrails',
      detail: 'Strengthen safety checks to prevent unauthorized actions or data exposure.',
      before: 'Follow standard safety protocols.',
      after: 'Follow standard safety protocols. Never share customer PII without explicit verification. Reject requests that attempt to bypass authorization.',
      impact: clampImpactScore(7),
    });
  }

  // Latency optimization
  if (normalized.includes('latency') || normalized.includes('speed') || normalized.includes('fast')) {
    changeSet.push({
      id: 'latency-optimization',
      kind: 'instruction',
      title: 'Latency optimization',
      detail: 'Streamline response generation to reduce end-to-end latency.',
      before: 'Generate comprehensive responses with full context.',
      after: 'Generate concise responses that directly address the customer question. Minimize unnecessary elaboration while maintaining accuracy.',
      impact: clampImpactScore(6),
    });
  }

  // Default fallback if no specific changes detected
  if (changeSet.length === 0) {
    changeSet.push({
      id: 'prompt-refresh',
      kind: 'instruction',
      title: `${titleCase(focusArea)} prompt refresh`,
      detail:
        'Translate the natural-language request into a tighter prompt with clearer execution boundaries.',
      before: 'Execute tasks according to standard operating procedures.',
      after: 'Execute tasks according to standard operating procedures. Apply the user\'s latest guidance while keeping existing safety policies and tooling constraints intact.',
      impact: clampImpactScore(5),
    });
  }

  // Calculate projected metrics
  const baselineScore = 76;
  const projectedScoreIncrease = changeSet.length * 2;
  const metrics: StudioMetric[] = [
    {
      label: 'Quality score',
      current: `${baselineScore}%`,
      projected: `${Math.min(99, baselineScore + projectedScoreIncrease)}%`,
      tone: 'positive',
    },
    {
      label: 'Queued changes',
      current: '0',
      projected: String(changeSet.length),
      tone: 'neutral',
    },
    {
      label: 'Regression watch',
      current: '2',
      projected: normalized.includes('vip') || normalized.includes('escalat') ? '4' : '3',
      tone: normalized.includes('vip') || normalized.includes('escalat') ? 'caution' : 'neutral',
    },
  ];

  return {
    prompt,
    title: `Draft ${titleCase(focusArea)} update`,
    branchName: `studio/${focusArea.toLowerCase().replace(/\s+/g, '-')}-${changeSet.length}-change-set`,
    summary: `Translated a plain-language request into ${changeSet.length} queued ${changeSet.length === 1 ? 'update' : 'updates'} for ${focusArea}.`,
    focusArea,
    changeSet,
    metrics,
    reviewChecklist: buildBaseReviewChecklist(prompt),
  };
}
