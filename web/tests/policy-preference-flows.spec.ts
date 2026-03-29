import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';

import { expect, test, type Page } from '@playwright/test';

const BASE_URL = process.env.PLAYWRIGHT_BASE_URL || 'http://localhost:5173';

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

test.describe('Preference + Policy Flows', () => {
  test('preference inbox loads and accepts a new preference pair', async ({ page }) => {
    const assertHealthy = collectBrowserIssues(page);
    const prompt = `Playwright preference ${Date.now()}`;

    await page.goto(`${BASE_URL}/preference-inbox`, { waitUntil: 'networkidle' });
    await page.getByRole('button', { name: /Add Pair/i }).click();

    const textareas = page.locator('textarea');
    await textareas.nth(0).fill(prompt);
    await textareas.nth(1).fill('Preferred answer');
    await textareas.nth(2).fill('Rejected answer');
    await page.getByRole('button', { name: /Submit Pair/i }).click();

    await expect(page.getByText(prompt)).toBeVisible();

    assertHealthy();
  });

  test('policy candidates can create a valid training job and run OPE', async ({ page }) => {
    const assertHealthy = collectBrowserIssues(page);
    const datasetDir = await fs.mkdtemp(path.join(os.tmpdir(), 'autoagent-policy-'));
    const datasetPath = path.join(datasetDir, 'control-dataset.jsonl');
    await fs.writeFile(datasetPath, '{"input_text":"hello","output_text":"world"}\n', 'utf-8');

    await page.goto(`${BASE_URL}/policy-candidates`, { waitUntil: 'networkidle' });
    await page.getByRole('button', { name: /New Training Job/i }).click();
    await page.getByRole('combobox').nth(0).selectOption('control');
    await page.getByRole('combobox').nth(1).selectOption('vertex_sft');
    await page.getByPlaceholder(/s3:\/\/bucket\/dataset\.jsonl/i).fill(datasetPath);
    await page.getByRole('button', { name: /Start Job/i }).click();

    await expect(page.getByText(datasetPath)).toBeVisible();
    await page.getByRole('button', { name: /control_vertex_sft/i }).first().click();
    await page.getByRole('button', { name: /Run OPE/i }).click();

    await expect(page.getByText('OPE Report')).toBeVisible();
    await expect(page.getByRole('button', { name: /Promote/i })).toBeEnabled();

    assertHealthy();
  });
});
