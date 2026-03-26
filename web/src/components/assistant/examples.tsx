/**
 * Example usage of Assistant card components
 *
 * This file demonstrates how to use each card component with sample data.
 * Import the components and types from './index' and provide appropriate data props.
 */

import {
  AgentPreviewCard,
  DiagnosisCard,
  DiffCard,
  MetricsCard,
  ConversationCard,
  ProgressCard,
  DeployCard,
  ClusterCard,
  type AgentPreviewData,
  type DiagnosisData,
  type DiffData,
  type MetricsData,
  type ConversationData,
  type ProgressData,
  type DeployData,
  type ClusterData,
} from './index';

// ============================================================================
// Example Data
// ============================================================================

export const exampleAgentPreview: AgentPreviewData = {
  orchestrator: 'customer_support_orchestrator',
  specialists: [
    {
      name: 'billing_specialist',
      description: 'Handles billing, refunds, and payment issues',
      intents: ['billing_inquiry', 'refund_request', 'payment_failure', 'invoice_question'],
    },
    {
      name: 'shipping_specialist',
      description: 'Manages shipping tracking and delivery questions',
      intents: ['track_order', 'shipping_delay', 'delivery_address_change'],
    },
    {
      name: 'returns_specialist',
      description: 'Processes returns and exchanges',
      intents: ['return_item', 'exchange_request', 'return_policy'],
    },
    {
      name: 'technical_support',
      description: 'Provides technical product support',
      intents: ['product_setup', 'troubleshooting', 'technical_specs'],
    },
  ],
  routing_rules: [
    {
      from: 'orchestrator',
      to: 'billing_specialist',
      keywords: ['billing', 'invoice', 'refund', 'payment', 'charge', 'subscription'],
    },
    {
      from: 'orchestrator',
      to: 'shipping_specialist',
      keywords: ['shipping', 'tracking', 'delivery', 'carrier', 'transit'],
    },
    {
      from: 'orchestrator',
      to: 'returns_specialist',
      keywords: ['return', 'exchange', 'swap', 'wrong item'],
    },
  ],
  coverage_pct: 87,
  intent_count: 15,
  tool_count: 8,
};

export const exampleDiagnosis: DiagnosisData = {
  root_cause: 'Missing billing keywords in routing rules',
  description: '40% of billing questions are incorrectly routed to technical support because routing rules don\'t include keywords like "invoice", "refund", or "charge".',
  impact_score: 78,
  affected_conversations: 234,
  trend: 'increasing',
  trend_data: [45, 52, 58, 61, 68, 72, 78],
  fix_confidence: 'high',
  fix_summary: 'Add 5 billing-related keywords to routing rules. Expected improvement: +19%. Low risk change.',
};

export const exampleDiff: DiffData = {
  file_path: 'agents/customer_support/routing.yaml',
  before: `routing:
  - from: orchestrator
    to: billing_specialist
    keywords:
      - billing
      - payment`,
  after: `routing:
  - from: orchestrator
    to: billing_specialist
    keywords:
      - billing
      - payment
      - invoice
      - refund
      - charge
      - subscription`,
  change_description: 'Added 4 billing-related keywords to improve routing accuracy',
  risk_level: 'low',
  expected_impact: {
    success_rate_delta: 19.2,
    latency_delta_ms: -15,
    cost_delta: 0.002,
  },
};

export const exampleMetrics: MetricsData = {
  title: 'Before/After Comparison',
  metrics: [
    {
      name: 'Task Success',
      baseline: 0.62,
      candidate: 0.81,
      delta: 0.19,
      p_value: 0.001,
    },
    {
      name: 'Routing Accuracy',
      baseline: 0.71,
      candidate: 0.92,
      delta: 0.21,
      p_value: 0.002,
    },
    {
      name: 'Response Quality',
      baseline: 0.78,
      candidate: 0.84,
      delta: 0.06,
      p_value: 0.045,
    },
    {
      name: 'Safety Compliance',
      baseline: 0.95,
      candidate: 0.96,
      delta: 0.01,
      p_value: 0.234,
    },
  ],
  confidence_interval: {
    lower: 0.15,
    upper: 0.23,
  },
  overall_p_value: 0.0012,
  is_significant: true,
};

export const exampleConversation: ConversationData = {
  conversation_id: 'conv_a3b5c7d9',
  timestamp: Date.now() / 1000 - 3600,
  grade: 45,
  failure_reason: 'Agent incorrectly routed billing question to technical support',
  messages: [
    {
      role: 'user',
      content: 'I was charged twice for my last order. Can you help me get a refund?',
      timestamp: Date.now() / 1000 - 3600,
    },
    {
      role: 'assistant',
      content: 'I understand you\'re having an issue. Let me route you to our technical support team.',
      timestamp: Date.now() / 1000 - 3595,
      is_failure: true,
    },
    {
      role: 'user',
      content: 'Wait, this is a billing issue, not technical support.',
      timestamp: Date.now() / 1000 - 3590,
    },
    {
      role: 'assistant',
      content: 'My apologies. Let me connect you with our billing specialist.',
      timestamp: Date.now() / 1000 - 3585,
    },
    {
      role: 'user',
      content: 'Thank you.',
      timestamp: Date.now() / 1000 - 3580,
    },
  ],
  metadata: {
    duration_ms: 45000,
    total_cost: 0.0234,
    model: 'claude-sonnet-4-5',
  },
};

export const exampleProgress: ProgressData = {
  title: 'Building Agent Configuration',
  overall_progress: 67,
  current_step_index: 4,
  steps: [
    {
      id: 'parse',
      label: 'Parsed 500 conversations',
      status: 'completed',
      details: 'Successfully parsed all CSV files and extracted conversation data.',
    },
    {
      id: 'intents',
      label: 'Extracted 12 intents',
      status: 'completed',
      details: [
        'billing_inquiry',
        'refund_request',
        'track_order',
        'return_item',
        'technical_support',
        'product_info',
        'account_management',
        'shipping_delay',
        'payment_failure',
        'exchange_request',
        'cancel_order',
        'general_inquiry',
      ],
    },
    {
      id: 'specialists',
      label: 'Identified 4 specialist domains',
      status: 'completed',
      details: 'Created specialist agents for billing, shipping, returns, and technical support.',
    },
    {
      id: 'routing',
      label: 'Generating routing rules',
      status: 'in-progress',
      details: 'Analyzing keyword patterns and intent distributions...',
    },
    {
      id: 'config',
      label: 'Building agent configuration',
      status: 'pending',
    },
    {
      id: 'eval',
      label: 'Running baseline evaluation',
      status: 'pending',
    },
  ],
};

export const exampleDeploy: DeployData = {
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
  metric_trend: [0.79, 0.80, 0.81, 0.81, 0.82],
  timeline: [
    {
      timestamp: Date.now() / 1000 - 600,
      event: 'Deployment initiated',
      status: 'success',
    },
    {
      timestamp: Date.now() / 1000 - 580,
      event: 'Configuration validated',
      status: 'success',
    },
    {
      timestamp: Date.now() / 1000 - 560,
      event: 'Canary deployment started (5% traffic)',
      status: 'success',
    },
    {
      timestamp: Date.now() / 1000 - 300,
      event: 'Canary metrics collected (124 samples)',
      status: 'success',
    },
    {
      timestamp: Date.now() / 1000 - 60,
      event: 'Canary health check passed',
      status: 'success',
    },
  ],
};

export const exampleCluster: ClusterData = {
  cluster_id: 'cluster_m3n5p7',
  rank: 1,
  title: 'Billing question routing failures',
  description: 'Billing-related questions are being incorrectly routed to technical support due to missing keywords in routing configuration.',
  impact_score: 78,
  conversation_count: 234,
  severity: 'high',
  trend: 'increasing',
  trend_data: [45, 52, 58, 61, 68, 72, 78],
  example_conversation_ids: ['conv_a3b5c7d9', 'conv_d8e2f4g6', 'conv_k9l1m3n5'],
  root_cause: 'Routing rules missing keywords: invoice, refund, charge, subscription',
  suggested_fix: 'Add 5 billing-related keywords to routing rules. Expected improvement: +19%.',
};

// ============================================================================
// Example Component Usage
// ============================================================================

export function AssistantCardExamples() {
  return (
    <div className="space-y-8 p-8 bg-gray-50">
      <div>
        <h2 className="text-lg font-semibold text-gray-900 mb-4">Agent Preview Card</h2>
        <AgentPreviewCard data={exampleAgentPreview} />
      </div>

      <div>
        <h2 className="text-lg font-semibold text-gray-900 mb-4">Diagnosis Card</h2>
        <DiagnosisCard data={exampleDiagnosis} />
      </div>

      <div>
        <h2 className="text-lg font-semibold text-gray-900 mb-4">Diff Card</h2>
        <DiffCard data={exampleDiff} />
      </div>

      <div>
        <h2 className="text-lg font-semibold text-gray-900 mb-4">Metrics Card</h2>
        <MetricsCard data={exampleMetrics} />
      </div>

      <div>
        <h2 className="text-lg font-semibold text-gray-900 mb-4">Conversation Card</h2>
        <ConversationCard data={exampleConversation} />
      </div>

      <div>
        <h2 className="text-lg font-semibold text-gray-900 mb-4">Progress Card</h2>
        <ProgressCard data={exampleProgress} />
      </div>

      <div>
        <h2 className="text-lg font-semibold text-gray-900 mb-4">Deploy Card</h2>
        <DeployCard
          data={exampleDeploy}
          onRollback={() => alert('Rollback initiated')}
        />
      </div>

      <div>
        <h2 className="text-lg font-semibold text-gray-900 mb-4">Cluster Card</h2>
        <ClusterCard
          data={exampleCluster}
          onViewConversation={(id) => alert(`View conversation: ${id}`)}
        />
      </div>
    </div>
  );
}
