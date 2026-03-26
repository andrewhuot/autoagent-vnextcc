# AutoAgent Assistant Components

Rich, interactive card components for the AutoAgent Assistant conversational interface.

## Components

### 1. AgentPreviewCard
**Purpose:** Visualize agent configuration with tree structure, routing logic, and coverage stats.

**Usage:**
```tsx
import { AgentPreviewCard, type AgentPreviewData } from './assistant';

const data: AgentPreviewData = {
  orchestrator: 'customer_support_orchestrator',
  specialists: [
    {
      name: 'billing_specialist',
      description: 'Handles billing, refunds, and payment issues',
      intents: ['billing_inquiry', 'refund_request', 'payment_failure'],
    },
  ],
  routing_rules: [
    {
      from: 'orchestrator',
      to: 'billing_specialist',
      keywords: ['billing', 'invoice', 'refund', 'payment'],
    },
  ],
  coverage_pct: 87,
  intent_count: 15,
  tool_count: 8,
};

<AgentPreviewCard data={data} />
```

**Features:**
- Collapsible agent tree visualization
- Expandable routing logic display
- Coverage percentage indicator
- Intent and tool statistics

---

### 2. DiagnosisCard
**Purpose:** Display root cause analysis with impact scoring and trend visualization.

**Usage:**
```tsx
import { DiagnosisCard, type DiagnosisData } from './assistant';

const data: DiagnosisData = {
  root_cause: 'Missing billing keywords in routing rules',
  description: '40% of billing questions incorrectly routed to tech support',
  impact_score: 78,
  affected_conversations: 234,
  trend: 'increasing',
  trend_data: [45, 52, 58, 61, 68, 72, 78],
  fix_confidence: 'high',
  fix_summary: 'Add 5 billing keywords. Expected +19% improvement.',
};

<DiagnosisCard data={data} />
```

**Features:**
- Impact score with color-coded severity (0-100)
- Trend chart (increasing/stable/decreasing)
- Affected conversation count
- Fix confidence level indicator

---

### 3. DiffCard
**Purpose:** Show before/after configuration changes with syntax highlighting.

**Usage:**
```tsx
import { DiffCard, type DiffData } from './assistant';

const data: DiffData = {
  file_path: 'agents/customer_support/routing.yaml',
  before: 'routing:\n  keywords:\n    - billing',
  after: 'routing:\n  keywords:\n    - billing\n    - invoice\n    - refund',
  change_description: 'Added billing-related keywords',
  risk_level: 'low',
  expected_impact: {
    success_rate_delta: 19.2,
    latency_delta_ms: -15,
    cost_delta: 0.002,
  },
};

<DiffCard data={data} />
```

**Features:**
- Side-by-side diff visualization
- Risk level indicator (low/medium/high)
- Expected impact metrics
- Syntax highlighting for YAML

---

### 4. MetricsCard
**Purpose:** Compare baseline vs. candidate metrics with statistical significance.

**Usage:**
```tsx
import { MetricsCard, type MetricsData } from './assistant';

const data: MetricsData = {
  title: 'Before/After Comparison',
  metrics: [
    {
      name: 'Task Success',
      baseline: 0.62,
      candidate: 0.81,
      delta: 0.19,
      p_value: 0.001,
    },
  ],
  confidence_interval: { lower: 0.15, upper: 0.23 },
  overall_p_value: 0.0012,
  is_significant: true,
};

<MetricsCard data={data} />
```

**Features:**
- Bar chart comparison
- P-value and statistical significance
- 95% confidence interval visualization
- Delta indicators with trend icons

---

### 5. ConversationCard
**Purpose:** Display conversation transcript with failure highlights and grading.

**Usage:**
```tsx
import { ConversationCard, type ConversationData } from './assistant';

const data: ConversationData = {
  conversation_id: 'conv_a3b5c7d9',
  timestamp: Date.now() / 1000,
  grade: 45,
  failure_reason: 'Incorrect routing',
  messages: [
    {
      role: 'user',
      content: 'I need a refund',
      timestamp: Date.now() / 1000,
    },
    {
      role: 'assistant',
      content: 'Let me route you to technical support',
      is_failure: true,
    },
  ],
  metadata: {
    duration_ms: 45000,
    total_cost: 0.0234,
    model: 'claude-sonnet-4-5',
  },
};

<ConversationCard data={data} />
```

**Features:**
- Message-by-message transcript
- Failure point highlighting
- Grade/score display
- Expandable view for long conversations

---

### 6. ProgressCard
**Purpose:** Show step-by-step progress with collapsible details.

**Usage:**
```tsx
import { ProgressCard, type ProgressData } from './assistant';

const data: ProgressData = {
  title: 'Building Agent Configuration',
  overall_progress: 67,
  current_step_index: 3,
  steps: [
    {
      id: 'parse',
      label: 'Parsed 500 conversations',
      status: 'completed',
      details: 'Successfully parsed CSV files',
    },
    {
      id: 'intents',
      label: 'Extracting intents',
      status: 'in-progress',
    },
    {
      id: 'config',
      label: 'Building configuration',
      status: 'pending',
    },
  ],
};

<ProgressCard data={data} />
```

**Features:**
- Overall progress percentage
- Step status icons (completed/in-progress/pending/failed)
- Collapsible step details
- Current step indicator

---

### 7. DeployCard
**Purpose:** Display deployment status with canary metrics and rollback capability.

**Usage:**
```tsx
import { DeployCard, type DeployData } from './assistant';

const data: DeployData = {
  deployment_id: 'deploy_x7y9z2',
  status: 'canary',
  progress: 45,
  canary_traffic_pct: 5,
  started_at: Date.now() / 1000 - 600,
  can_rollback: true,
  canary_metrics: {
    success_rate: 0.812,
    error_rate: 0.042,
    p95_latency_ms: 1850,
    sample_size: 124,
  },
  baseline_metrics: {
    success_rate: 0.789,
    error_rate: 0.051,
    p95_latency_ms: 1920,
    sample_size: 2340,
  },
  timeline: [
    { timestamp: Date.now() / 1000, event: 'Started', status: 'success' },
  ],
};

<DeployCard data={data} onRollback={() => console.log('Rollback')} />
```

**Features:**
- Deployment progress bar
- Canary vs. baseline metrics comparison
- Metric trend visualization
- Rollback button
- Event timeline

---

### 8. ClusterCard
**Purpose:** Visualize blame clusters with impact ranking and example conversations.

**Usage:**
```tsx
import { ClusterCard, type ClusterData } from './assistant';

const data: ClusterData = {
  cluster_id: 'cluster_m3n5p7',
  rank: 1,
  title: 'Billing routing failures',
  description: 'Questions routed to wrong team',
  impact_score: 78,
  conversation_count: 234,
  severity: 'high',
  trend: 'increasing',
  trend_data: [45, 52, 58, 61, 68, 72, 78],
  example_conversation_ids: ['conv_a3b5c7d9', 'conv_d8e2f4g6'],
  root_cause: 'Missing routing keywords',
  suggested_fix: 'Add 5 keywords. Expected +19% improvement.',
};

<ClusterCard
  data={data}
  onViewConversation={(id) => console.log('View:', id)}
/>
```

**Features:**
- Impact score with severity badge
- Trend line chart
- Conversation count
- Example conversation links
- Suggested fix display

---

## Design Patterns

All components follow these conventions:

1. **TypeScript**: Full type safety with exported interfaces
2. **Tailwind CSS**: Utility-first styling matching existing design system
3. **Responsive**: Mobile-friendly layouts with grid/flexbox
4. **Icons**: lucide-react icons for consistency
5. **Charts**: recharts for data visualization
6. **Colors**: Neutral palette (grays, greens, reds, ambers, blues)
7. **Accessibility**: Semantic HTML, ARIA labels, keyboard navigation

## Testing

See `examples.tsx` for complete working examples of each component with sample data.

## Integration

These components are designed to be rendered in chat messages based on card type:

```tsx
import { AgentPreviewCard, DiagnosisCard, /* ... */ } from './assistant';

function renderCard(cardType: string, cardData: unknown) {
  switch (cardType) {
    case 'agent_preview':
      return <AgentPreviewCard data={cardData as AgentPreviewData} />;
    case 'diagnosis':
      return <DiagnosisCard data={cardData as DiagnosisData} />;
    // ... etc
  }
}
```

## Dependencies

- React 18+
- TypeScript 5+
- Tailwind CSS 3+
- lucide-react (icons)
- recharts (charts)
