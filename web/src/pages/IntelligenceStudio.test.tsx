import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { IntelligenceStudio } from './IntelligenceStudio';

vi.mock('../lib/toast', () => ({
  toastError: vi.fn(),
  toastSuccess: vi.fn(),
}));

const fetchMock = vi.fn();

function buildGeneratedConfig(createdFrom: 'prompt' | 'transcript') {
  return {
    system_prompt:
      'You are an order operations assistant.\nVerify identity before any order change.\nEscalate when the user requests a human.',
    tools: [
      {
        name: 'lookup_order',
        description: 'Retrieve order details using verified identifiers.',
        parameters: ['order_id', 'email'],
      },
      {
        name: 'process_refund',
        description: 'Issue refunds that meet policy and eligibility rules.',
        parameters: ['order_id', 'amount'],
      },
    ],
    routing_rules: [
      {
        condition: "intent == 'order_tracking'",
        action: 'lookup_order',
        priority: 1,
      },
      {
        condition: "intent == 'refund_request'",
        action: 'process_refund',
        priority: 2,
      },
    ],
    policies: [
      {
        name: 'identity_verification',
        description: 'Verify the user before exposing or modifying order data.',
        enforcement: 'strict',
      },
      {
        name: 'escalation_with_context',
        description: 'Hand the full conversation summary to human support.',
        enforcement: 'advisory',
      },
    ],
    eval_criteria: [
      {
        name: 'resolution_rate',
        weight: 0.45,
        description: 'Resolve common order requests without escalation.',
      },
      {
        name: 'policy_adherence',
        weight: 0.55,
        description: 'Apply verification and refund guardrails correctly.',
      },
    ],
    metadata: {
      agent_name: 'Order Operations Agent',
      version: '1.0.0',
      created_from: createdFrom,
    },
  };
}

function buildTranscriptReport() {
  return {
    report_id: 'report-123',
    archive_name: 'support-transcripts.json',
    created_at: Date.now(),
    conversation_count: 3,
    languages: ['en'],
    missing_intents: [
      {
        intent: 'address_change',
        count: 1,
        share: 0.33,
        evidence: ['Customers ask to update the address after purchase.'],
      },
    ],
    procedure_summaries: [
      {
        intent: 'cancellation',
        summary: 'Verify identity, confirm shipment state, then cancel when eligible.',
        steps: ['Verify identity', 'Check shipment state', 'Cancel order'],
      },
    ],
    faq_entries: [
      {
        intent: 'refund',
        question: 'How do I get a refund for a damaged item?',
        answer: 'Confirm eligibility, capture the damage reason, and issue the refund.',
      },
    ],
    workflow_suggestions: [
      {
        title: 'Fallback verification',
        description: 'Use email plus ZIP code when the order number is missing.',
      },
    ],
    suggested_tests: [
      {
        name: 'refund-damaged-item',
        user_message: 'I want a refund for a damaged order.',
        expected_behavior: 'Verify the order, confirm the issue, and process the refund.',
      },
    ],
    insights: [
      {
        insight_id: 'insight-1',
        title: 'Missing order numbers drive escalations',
        summary: 'Customers often do not have the order number ready.',
        recommendation: 'Add a fallback verification path using email plus ZIP.',
        drafted_change_prompt: 'Add fallback verification with email and ZIP.',
        metric_name: 'transfer_reason',
        share: 0.67,
        count: 2,
        total: 3,
        evidence: ['Where is my order? I do not have my order number.'],
      },
    ],
    knowledge_asset: {
      asset_id: 'asset-1',
      title: 'Support archive knowledge',
      entry_count: 3,
      created_at: Date.now(),
    },
    conversations: [],
  };
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/intelligence']}>
        <IntelligenceStudio />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe('IntelligenceStudio', () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal('fetch', fetchMock);
    vi.stubGlobal(
      'URL',
      Object.assign(globalThis.URL ?? {}, {
        createObjectURL: vi.fn(() => 'blob:intelligence-config'),
        revokeObjectURL: vi.fn(),
      })
    );
    Object.defineProperty(globalThis.navigator, 'clipboard', {
      configurable: true,
      value: {
        writeText: vi.fn().mockResolvedValue(undefined),
      },
    });
  });

  it('defaults to prompt mode and switches into a YAML-first refinement workspace after generation', async () => {
    const user = userEvent.setup();
    fetchMock.mockResolvedValueOnce({
      ok: true,
      json: async () => buildGeneratedConfig('prompt'),
    });

    renderPage();

    expect(screen.getByRole('button', { name: 'Start from Prompt' })).toBeInTheDocument();
    expect(
      screen.getByPlaceholderText('Describe the agent you want to build...')
    ).toBeInTheDocument();

    await user.click(
      screen.getByRole('button', {
        name: /Build a customer service agent for order tracking, cancellations, and refunds/i,
      })
    );
    await user.click(screen.getByRole('button', { name: 'Generate Agent' }));

    expect(await screen.findByRole('heading', { name: 'Conversational Refinement' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Live YAML Config' })).toBeInTheDocument();
    expect(screen.getByTestId('yaml-preview')).toHaveTextContent('system_prompt:');
    expect(screen.getByRole('button', { name: 'Generate Evals' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Export' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Run Eval' })).toBeInTheDocument();
  });

  it('accepts transcript JSON uploads, shows extracted insights, and generates an agent from them', async () => {
    const user = userEvent.setup();
    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => buildTranscriptReport(),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => buildGeneratedConfig('transcript'),
      });

    renderPage();

    await user.click(screen.getByRole('button', { name: 'Start from Transcripts' }));

    const uploadInput = screen.getByLabelText('Upload transcript files');
    const transcriptFile = new File(
      [
        JSON.stringify([
          {
            conversation_id: 'hist-001',
            session_id: 'session-1',
            user_message: 'Where is my order?',
            agent_response: 'I can help with that.',
            outcome: 'success',
          },
        ]),
      ],
      'support-transcripts.json',
      { type: 'application/json' }
    );

    await user.upload(uploadInput, transcriptFile);

    expect(await screen.findByText('Top Intents')).toBeInTheDocument();
    expect(screen.getByText('Pattern Signals')).toBeInTheDocument();
    expect(screen.getByText('Extracted FAQs')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Generate Agent' }));

    expect(await screen.findByRole('heading', { name: 'Live YAML Config' })).toBeInTheDocument();
    expect(screen.getByTestId('yaml-preview')).toHaveTextContent('created_from: transcript');
  });
});
