import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { expect, test, type Page } from '@playwright/test';

const BASE_URL = process.env.PLAYWRIGHT_BASE_URL || 'http://localhost:5173';
const TEST_DIR = path.dirname(fileURLToPath(import.meta.url));

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
    archive_name: 'intelligence-transcripts.json',
    created_at: Date.now(),
    conversation_count: 3,
    languages: ['en'],
    missing_intents: [
      {
        intent: 'address_change',
        count: 1,
        reason: 'Customers asked to update the address after checkout.',
      },
    ],
    procedure_summaries: [
      {
        intent: 'cancellation',
        steps: ['Verify identity', 'Confirm shipment state', 'Cancel order'],
        source_conversation_id: 'hist-002',
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
      entry_count: 3,
    },
    conversations: [
      {
        conversation_id: 'hist-001',
        session_id: 'archive-1',
        user_message: 'Where is my order? I do not have my order number.',
        agent_response: 'I can help after I verify your email and ZIP code.',
        outcome: 'transfer',
        language: 'en',
        intent: 'order_tracking',
        transfer_reason: 'missing_order_number',
        source_file: 'intelligence-transcripts.json',
        procedure_steps: [],
      },
      {
        conversation_id: 'hist-002',
        session_id: 'archive-2',
        user_message: 'Can you cancel this order before it ships?',
        agent_response: 'I can cancel it after I verify your identity.',
        outcome: 'success',
        language: 'en',
        intent: 'cancellation',
        transfer_reason: null,
        source_file: 'intelligence-transcripts.json',
        procedure_steps: [],
      },
    ],
  };
}

async function mockIntelligenceRoutes(page: Page) {
  await page.route('**/api/intelligence/archive', async (route) => {
    await route.fulfill({
      status: 201,
      contentType: 'application/json',
      body: JSON.stringify(buildTranscriptReport()),
    });
  });

  await page.route('**/api/intelligence/generate-agent', async (route) => {
    const requestBody = route.request().postDataJSON() as { transcript_report_id?: string };
    const createdFrom = requestBody.transcript_report_id ? 'transcript' : 'prompt';
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(buildGeneratedConfig(createdFrom)),
    });
  });

  await page.route('**/api/intelligence/chat', async (route) => {
    const payload = route.request().postDataJSON() as { config: ReturnType<typeof buildGeneratedConfig> };
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        response:
          'Applied the following changes:\n- Added high-priority escalation routing rule.\n- Added refund workflow safeguards.',
        config: payload.config,
      }),
    });
  });
}

function collectBrowserIssues(page: Page) {
  const consoleErrors: string[] = [];
  const pageErrors: string[] = [];
  const requestFailures: string[] = [];
  const badResponses: string[] = [];

  const ignorable = (entry: string) => entry.includes('/favicon.ico');

  page.on('console', (msg) => {
    if (msg.type() === 'error') {
      consoleErrors.push(msg.text());
    }
  });
  page.on('pageerror', (error) => {
    pageErrors.push(error.message);
  });
  page.on('requestfailed', (request) => {
    requestFailures.push(
      `${request.method()} ${request.url()} :: ${request.failure()?.errorText || 'unknown'}`
    );
  });
  page.on('response', (response) => {
    if (response.status() >= 400) {
      badResponses.push(`${response.status()} ${response.url()}`);
    }
  });

  return () => {
    expect(pageErrors).toEqual([]);
    expect(consoleErrors.filter((entry) => !ignorable(entry))).toEqual([]);
    expect(requestFailures.filter((entry) => !ignorable(entry))).toEqual([]);
    expect(badResponses.filter((entry) => !ignorable(entry))).toEqual([]);
  };
}

test.describe('Intelligence Studio', () => {
  test('supports prompt and transcript flows from the shared build workspace', async ({ page }) => {
    const assertHealthy = collectBrowserIssues(page);
    const transcriptFile = path.join(TEST_DIR, 'fixtures', 'intelligence-transcripts.json');
    await mockIntelligenceRoutes(page);

    await page.goto(`${BASE_URL}/intelligence`, { waitUntil: 'networkidle' });

    await expect(page).toHaveURL(`${BASE_URL}/build?tab=transcript`);
    await expect(page.getByRole('heading', { name: 'Intelligence Studio' }).nth(0)).toBeVisible();
    await expect(page.getByRole('tab', { name: 'Transcript' })).toHaveAttribute('aria-selected', 'true');

    await page.getByRole('tab', { name: 'Prompt' }).click();
    await expect(page.getByRole('heading', { name: 'Build' }).nth(0)).toBeVisible();
    await expect(page.getByRole('tab', { name: 'Prompt' })).toHaveAttribute('aria-selected', 'true');

    await page.getByRole('button', {
      name: /Build a customer service agent for order tracking, cancellations, and refunds/i,
    }).click();
    await page.getByRole('button', { name: 'Generate Agent' }).click();

    await expect(page.getByRole('heading', { name: 'Conversational Refinement' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'View Config' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Save & Run Eval' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Save & Generate Evals' })).toBeVisible();
    await expect(
      page.getByText(/These actions save the current draft first/i)
    ).toBeVisible();

    await page.getByRole('textbox', { name: 'Refinement message' }).fill(
      'Add escalation logic for VIP customers and a refund workflow.'
    );
    await page.getByRole('button', { name: 'Send refinement message' }).click();
    await expect(page.getByText(/Applied the following changes:/i)).toBeVisible();

    await page.goto(`${BASE_URL}/intelligence`, { waitUntil: 'networkidle' });
    await expect(page.getByRole('heading', { name: 'Intelligence Studio' }).nth(0)).toBeVisible();
    await page.getByLabel('Upload transcript files').setInputFiles(transcriptFile);

    await expect(page.getByText('Top Intents')).toBeVisible();
    await expect(page.getByText('Pattern Signals')).toBeVisible();
    await expect(page.getByText('Extracted FAQs')).toBeVisible();

    await page.getByRole('button', { name: 'Generate Agent' }).click();
    await expect(page.getByRole('button', { name: 'View Config' })).toBeVisible();

    await page.getByRole('button', { name: 'View Config' }).click();
    const dialog = page.getByRole('dialog', { name: 'Agent Configuration' });
    await expect(dialog.getByTestId('yaml-preview')).toContainText('created_from: transcript');

    assertHealthy();
  });
});
