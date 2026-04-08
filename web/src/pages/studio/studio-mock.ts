import type {
  SpecVersion,
  ProductionIssue,
  ProductionMetricsSnapshot,
  EvidenceTrace,
  EvidenceConversation,
  EvalSetSummary,
  StudioCandidate,
  StudioOptimizeRun,
  OptimizeModeConfig,
} from './studio-types';

// ─── Spec Mock ────────────────────────────────────────────────────────────────

export const MOCK_SPEC_CONTENT = `# Customer Support Agent — Specification v1.2

## Role
You are a Tier-1 customer support agent for Acme Corp. You handle billing inquiries, order status, product questions, and escalate complex issues to human agents.

## Capabilities
- Look up order status by order ID or email
- Process refunds for orders < 30 days old
- Update shipping addresses for orders not yet shipped
- Answer product FAQ questions
- Escalate to Tier-2 for: legal, fraud, complex billing disputes

## Constraints
- Never share another customer's personal information
- Never promise compensation not listed in the refund policy
- Always verify customer identity before accessing account data
- Do not process refunds > $500 without manager approval

## Response Style
- Concise and professional
- Acknowledge the customer's issue before offering solutions
- Use the customer's name if known
- End responses with a clear next step or confirmation

## Escalation Criteria
Escalate immediately if the customer mentions:
- Legal action or attorneys
- Fraud or unauthorized charges > $200
- Safety concerns related to a product

## Tools Available
- \`lookup_order(order_id)\`: Returns order status, items, and shipping info
- \`process_refund(order_id, amount, reason)\`: Initiates a refund
- \`update_address(order_id, new_address)\`: Updates shipping address
- \`get_customer_account(email)\`: Returns account details
- \`create_ticket(priority, summary, category)\`: Creates escalation ticket
`;

export const MOCK_SPEC_VERSIONS: SpecVersion[] = [
  {
    version_id: 'v-005',
    version_number: 5,
    created_at: '2025-04-07T14:22:00Z',
    author: 'andrew@acme.com',
    summary: 'Add escalation criteria for fraud threshold',
    status: 'draft',
    content: MOCK_SPEC_CONTENT,
  },
  {
    version_id: 'v-004',
    version_number: 4,
    created_at: '2025-04-05T10:15:00Z',
    author: 'sarah@acme.com',
    summary: 'Clarify refund window to 30 days, add manager approval threshold',
    status: 'published',
    content: MOCK_SPEC_CONTENT,
  },
  {
    version_id: 'v-003',
    version_number: 3,
    created_at: '2025-04-01T09:00:00Z',
    author: 'andrew@acme.com',
    summary: 'Add address update constraint for shipped orders',
    status: 'published',
    content: MOCK_SPEC_CONTENT,
  },
  {
    version_id: 'v-002',
    version_number: 2,
    created_at: '2025-03-28T16:40:00Z',
    author: 'sarah@acme.com',
    summary: 'Initial tools list, response style guidelines',
    status: 'archived',
    content: MOCK_SPEC_CONTENT,
  },
  {
    version_id: 'v-001',
    version_number: 1,
    created_at: '2025-03-25T11:00:00Z',
    author: 'andrew@acme.com',
    summary: 'Initial spec draft',
    status: 'archived',
    content: MOCK_SPEC_CONTENT,
  },
];

// ─── Observe Mock ─────────────────────────────────────────────────────────────

export const MOCK_PRODUCTION_METRICS: ProductionMetricsSnapshot = {
  success_rate: 0.847,
  success_rate_delta: -0.023,
  latency_p50_ms: 1240,
  latency_p95_ms: 4820,
  latency_delta_pct: 0.08,
  error_rate: 0.031,
  error_rate_delta: 0.007,
  cost_per_session_usd: 0.0042,
  cost_delta_pct: 0.12,
  sparkline_success: [88, 87, 86, 85, 84, 85, 84, 85, 85, 84],
  sparkline_latency: [1100, 1150, 1180, 1200, 1220, 1210, 1230, 1240, 1250, 1240],
  sparkline_errors: [2.0, 2.1, 2.4, 2.6, 2.9, 3.0, 3.1, 2.9, 3.0, 3.1],
};

export const MOCK_ISSUES: ProductionIssue[] = [
  {
    issue_id: 'iss-001',
    category: 'task_failure',
    severity: 'critical',
    title: 'Refund lookup fails for international orders',
    description:
      'Agent returns "order not found" for orders with non-US shipping addresses, causing refund requests to be incorrectly rejected.',
    count: 147,
    first_seen: '2025-04-03T08:22:00Z',
    last_seen: '2025-04-07T14:11:00Z',
    affected_sessions: 134,
    example_trace_id: 'trace-001',
    example_conversation_id: 'conv-001',
  },
  {
    issue_id: 'iss-002',
    category: 'hallucination',
    severity: 'high',
    title: 'Agent invents refund policy terms',
    description:
      'In 3.2% of refund conversations, agent states non-existent policies such as "we offer a 60-day no-questions-asked return".',
    count: 89,
    first_seen: '2025-04-01T11:00:00Z',
    last_seen: '2025-04-07T13:44:00Z',
    affected_sessions: 82,
    example_trace_id: 'trace-002',
    example_conversation_id: 'conv-002',
  },
  {
    issue_id: 'iss-003',
    category: 'latency',
    severity: 'high',
    title: 'P95 latency spike on order lookup tool',
    description:
      'lookup_order tool calls exhibit P95 latency of 4.8s, up from 2.1s baseline. Affects perceived agent response speed.',
    count: 312,
    first_seen: '2025-04-05T06:00:00Z',
    last_seen: '2025-04-07T14:20:00Z',
    affected_sessions: 287,
    example_trace_id: 'trace-003',
    example_conversation_id: null,
  },
  {
    issue_id: 'iss-004',
    category: 'policy_violation',
    severity: 'medium',
    title: 'Missing identity verification before account access',
    description:
      'Agent retrieves customer account details before completing identity verification in ~8% of sessions.',
    count: 56,
    first_seen: '2025-04-04T15:30:00Z',
    last_seen: '2025-04-07T09:12:00Z',
    affected_sessions: 51,
    example_trace_id: null,
    example_conversation_id: 'conv-003',
  },
  {
    issue_id: 'iss-005',
    category: 'tool_error',
    severity: 'medium',
    title: 'create_ticket fails on missing category field',
    description:
      'When creating escalation tickets, agent omits required `category` field in 12% of calls, resulting in API 400 errors and no ticket created.',
    count: 34,
    first_seen: '2025-04-06T10:00:00Z',
    last_seen: '2025-04-07T13:55:00Z',
    affected_sessions: 34,
    example_trace_id: 'trace-004',
    example_conversation_id: null,
  },
];

export const MOCK_EVIDENCE_TRACES: EvidenceTrace[] = [
  {
    trace_id: 'trace-001',
    session_id: 'sess-abc1',
    started_at: '2025-04-07T11:22:00Z',
    outcome: 'failure',
    latency_ms: 3210,
    issue_category: 'task_failure',
    steps: [
      { step_id: 's1', type: 'model_call', label: 'Parse intent: refund request', latency_ms: 340 },
      { step_id: 's2', type: 'tool_call', label: 'lookup_order("ORD-UK-88812")', latency_ms: 2480 },
      { step_id: 's3', type: 'tool_response', label: 'Error: order not found', latency_ms: 0, error: 'order not found' },
      { step_id: 's4', type: 'model_call', label: 'Generate response: order not found', latency_ms: 390 },
    ],
  },
  {
    trace_id: 'trace-002',
    session_id: 'sess-def2',
    started_at: '2025-04-07T13:44:00Z',
    outcome: 'failure',
    latency_ms: 1870,
    issue_category: 'hallucination',
    steps: [
      { step_id: 's1', type: 'model_call', label: 'Parse intent: return policy inquiry', latency_ms: 310 },
      { step_id: 's2', type: 'model_call', label: 'Generate response: stated 60-day policy', latency_ms: 1560, error: 'Fabricated policy claim' },
    ],
  },
  {
    trace_id: 'trace-003',
    session_id: 'sess-ghi3',
    started_at: '2025-04-07T14:02:00Z',
    outcome: 'partial',
    latency_ms: 5190,
    issue_category: 'latency',
    steps: [
      { step_id: 's1', type: 'model_call', label: 'Parse intent: order status check', latency_ms: 290 },
      { step_id: 's2', type: 'tool_call', label: 'lookup_order("ORD-9923")', latency_ms: 4620 },
      { step_id: 's3', type: 'tool_response', label: 'Order found: shipped', latency_ms: 0 },
      { step_id: 's4', type: 'model_call', label: 'Generate response: status update', latency_ms: 280 },
    ],
  },
];

export const MOCK_EVIDENCE_CONVERSATIONS: EvidenceConversation[] = [
  {
    conversation_id: 'conv-001',
    session_id: 'sess-abc1',
    started_at: '2025-04-07T11:22:00Z',
    outcome: 'failure',
    issue_category: 'task_failure',
    turns: [
      { turn_id: 't1', role: 'user', content: "Hi, I need a refund for order ORD-UK-88812. I received a damaged item.", timestamp: '2025-04-07T11:22:05Z' },
      { turn_id: 't2', role: 'agent', content: "I'm sorry to hear that! Let me look up that order for you.", timestamp: '2025-04-07T11:22:06Z' },
      { turn_id: 't3', role: 'agent', content: "I'm sorry, I wasn't able to find order ORD-UK-88812 in our system. Could you double-check the order number?", timestamp: '2025-04-07T11:22:10Z', flagged: true, flag_reason: 'International order lookup failure' },
      { turn_id: 't4', role: 'user', content: "I'm sure that's correct, I can see it in my confirmation email.", timestamp: '2025-04-07T11:22:45Z' },
      { turn_id: 't5', role: 'agent', content: "I apologize for the inconvenience. I'm unable to locate this order in our system. I'll create a support ticket for our team to investigate further.", timestamp: '2025-04-07T11:22:50Z' },
    ],
  },
  {
    conversation_id: 'conv-002',
    session_id: 'sess-def2',
    started_at: '2025-04-07T13:44:00Z',
    outcome: 'failure',
    issue_category: 'hallucination',
    turns: [
      { turn_id: 't1', role: 'user', content: "What is your return policy?", timestamp: '2025-04-07T13:44:10Z' },
      { turn_id: 't2', role: 'agent', content: "We offer a 60-day no-questions-asked return policy on all items. Simply contact us within 60 days of purchase for a full refund.", timestamp: '2025-04-07T13:44:14Z', flagged: true, flag_reason: 'Fabricated policy: actual policy is 30 days with conditions' },
      { turn_id: 't3', role: 'user', content: "Great, I want to return something I bought 45 days ago.", timestamp: '2025-04-07T13:44:50Z' },
      { turn_id: 't4', role: 'agent', content: "Of course! Since it's within 60 days, I can process that return for you.", timestamp: '2025-04-07T13:44:55Z', flagged: true, flag_reason: 'Acting on fabricated policy' },
    ],
  },
  {
    conversation_id: 'conv-003',
    session_id: 'sess-jkl4',
    started_at: '2025-04-07T09:12:00Z',
    outcome: 'failure',
    issue_category: 'policy_violation',
    turns: [
      { turn_id: 't1', role: 'user', content: "Can you check my account balance?", timestamp: '2025-04-07T09:12:05Z' },
      { turn_id: 't2', role: 'agent', content: "Sure! What's your email address?", timestamp: '2025-04-07T09:12:06Z' },
      { turn_id: 't3', role: 'user', content: "jane.doe@email.com", timestamp: '2025-04-07T09:12:20Z' },
      { turn_id: 't4', role: 'agent', content: "I can see your account. You have 3 active orders and a store credit balance of $42.50.", timestamp: '2025-04-07T09:12:25Z', flagged: true, flag_reason: 'Account accessed without identity verification' },
    ],
  },
];

// ─── Optimize Mock ────────────────────────────────────────────────────────────

export const MOCK_OPTIMIZE_MODE_CONFIGS: OptimizeModeConfig[] = [
  {
    mode: 'basic',
    label: 'Basic',
    description: 'Quick single-pass optimization targeting the top issue. Best for focused fixes.',
    iterations: 1,
    uses_research: false,
    uses_pareto: false,
    estimated_duration: '~5 min',
  },
  {
    mode: 'research',
    label: 'Research',
    description: 'Multi-hypothesis search with evidence-backed proposals. Good for root cause analysis.',
    iterations: 3,
    uses_research: true,
    uses_pareto: false,
    estimated_duration: '~15 min',
  },
  {
    mode: 'pro',
    label: 'Pro',
    description: 'Full Pareto-frontier search across all quality dimensions. Best overall improvement.',
    iterations: 8,
    uses_research: true,
    uses_pareto: true,
    estimated_duration: '~45 min',
  },
];

export const MOCK_EVAL_SETS: EvalSetSummary[] = [
  {
    eval_set_id: 'es-001',
    name: 'Core Support Flows',
    description: '120 cases covering order lookup, refunds, and address changes',
    num_cases: 120,
    last_run: '2025-04-06T10:00:00Z',
    pass_rate: 0.847,
  },
  {
    eval_set_id: 'es-002',
    name: 'Edge Cases & Escalations',
    description: '45 cases covering fraud, legal, and unusual requests',
    num_cases: 45,
    last_run: '2025-04-05T14:30:00Z',
    pass_rate: 0.756,
  },
  {
    eval_set_id: 'es-003',
    name: 'Policy Adherence',
    description: '60 cases testing identity verification and policy compliance',
    num_cases: 60,
    last_run: null,
    pass_rate: null,
  },
];

const BASELINE_CANDIDATE: StudioCandidate = {
  candidate_id: 'cand-baseline',
  label: 'Current (v4)',
  is_baseline: true,
  created_at: '2025-04-05T10:15:00Z',
  eval_run_id: 'er-042',
  scores: {
    overall: 78.3,
    task_success: 84.7,
    response_quality: 82.1,
    safety: 91.0,
    latency_score: 72.4,
    cost_score: 88.5,
  },
  spec_diff_lines: [],
  status: 'evaluated',
};

const CANDIDATE_A: StudioCandidate = {
  candidate_id: 'cand-a',
  label: 'Candidate A — Refund lookup fix',
  is_baseline: false,
  created_at: '2025-04-07T10:00:00Z',
  eval_run_id: 'er-043',
  scores: {
    overall: 84.1,
    task_success: 91.2,
    response_quality: 83.4,
    safety: 91.0,
    latency_score: 73.1,
    cost_score: 88.2,
  },
  spec_diff_lines: [
    { type: 'context', content: '## Tools Available', line_a: 1, line_b: 1 },
    { type: 'removed', content: '- `lookup_order(order_id)`: Returns order status, items, and shipping info', line_a: 2, line_b: 2 },
    { type: 'added', content: '- `lookup_order(order_id, region?)`: Returns order status, items, and shipping info. Pass region="intl" for non-US orders.', line_a: 2, line_b: 2 },
    { type: 'context', content: '- `process_refund(order_id, amount, reason)`: Initiates a refund', line_a: 3, line_b: 3 },
  ],
  status: 'evaluated',
};

const CANDIDATE_B: StudioCandidate = {
  candidate_id: 'cand-b',
  label: 'Candidate B — Policy grounding + refund fix',
  is_baseline: false,
  created_at: '2025-04-07T10:30:00Z',
  eval_run_id: 'er-044',
  scores: {
    overall: 87.6,
    task_success: 91.8,
    response_quality: 86.2,
    safety: 93.5,
    latency_score: 72.9,
    cost_score: 87.8,
  },
  spec_diff_lines: [
    { type: 'context', content: '## Constraints', line_a: 1, line_b: 1 },
    { type: 'added', content: '- Always cite the actual policy when discussing refunds or returns; do not paraphrase or summarize policy terms', line_a: 2, line_b: 2 },
    { type: 'context', content: '- Never share another customer\'s personal information', line_a: 3, line_b: 3 },
    { type: 'context', content: '', line_a: 4, line_b: 4 },
    { type: 'context', content: '## Tools Available', line_a: 5, line_b: 5 },
    { type: 'removed', content: '- `lookup_order(order_id)`: Returns order status, items, and shipping info', line_a: 6, line_b: 6 },
    { type: 'added', content: '- `lookup_order(order_id, region?)`: Returns order status, items, and shipping info. Pass region="intl" for non-US orders.', line_a: 6, line_b: 6 },
  ],
  status: 'evaluated',
};

const CANDIDATE_C: StudioCandidate = {
  candidate_id: 'cand-c',
  label: 'Candidate C — Pending eval',
  is_baseline: false,
  created_at: '2025-04-07T11:00:00Z',
  eval_run_id: null,
  scores: {
    overall: 0,
    task_success: 0,
    response_quality: 0,
    safety: 0,
    latency_score: 0,
    cost_score: 0,
  },
  spec_diff_lines: [],
  status: 'running',
};

export const MOCK_CANDIDATES: StudioCandidate[] = [
  BASELINE_CANDIDATE,
  CANDIDATE_A,
  CANDIDATE_B,
  CANDIDATE_C,
];

export const MOCK_OPTIMIZE_RUN: StudioOptimizeRun = {
  run_id: 'orun-001',
  mode: 'research',
  status: 'completed',
  started_at: '2025-04-07T10:00:00Z',
  completed_at: '2025-04-07T10:18:00Z',
  candidates: [CANDIDATE_A, CANDIDATE_B, CANDIDATE_C],
  recommended_candidate_id: 'cand-b',
  progress: 100,
  log_tail: [
    '[10:00:01] Loaded spec v4 and 120 eval cases',
    '[10:00:03] Analyzing top 3 issues from production',
    '[10:02:10] Hypothesis 1: Add international order lookup support',
    '[10:06:44] Candidate A generated and evaluated (84.1)',
    '[10:07:55] Hypothesis 2: Refund policy grounding + lookup fix',
    '[10:14:22] Candidate B generated and evaluated (87.6)',
    '[10:14:23] Hypothesis 3: Latency-focused tooling changes',
    '[10:18:00] Candidate C still evaluating...',
    '[10:18:00] Pareto analysis complete. Recommended: Candidate B',
  ],
};
