import playwright from '../web/node_modules/playwright/index.js';

const { chromium } = playwright;

const baseUrl = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:5173';
const prompt = [
  'Build FAQ Concierge, a customer FAQ support agent for a fictional B2B SaaS.',
  'It should answer product setup, billing plan, security, and troubleshooting questions.',
  'It should escalate unclear billing/security issues, cite internal KB guidance, and keep a calm concise tone.',
  'Include tools for searching the knowledge base, checking account plan status, and creating escalation tickets.',
].join(' ');

function sample(text, length = 2200) {
  return text.replace(/\s+\n/g, '\n').slice(0, length);
}

async function bodyText(page) {
  return page.locator('body').innerText();
}

async function clickByRole(page, name, timeout = 10000) {
  const button = page.getByRole('button', { name });
  await button.first().waitFor({ state: 'visible', timeout });
  await button.first().click();
}

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
const consoleMessages = [];
const failedRequests = [];
const evalStartRequests = [];
const steps = [];

page.on('console', (message) => {
  if (['error', 'warning'].includes(message.type())) {
    consoleMessages.push(`${message.type()}: ${message.text()}`);
  }
});

page.on('requestfailed', (request) => {
  const url = request.url();
  if (!url.includes('/ws')) {
    failedRequests.push(`${request.method()} ${url} ${request.failure()?.errorText ?? ''}`);
  }
});

page.on('request', (request) => {
  if (request.method() === 'POST' && request.url().includes('/api/eval/run')) {
    evalStartRequests.push(request.postData() ?? '');
  }
});

async function pollLatestGeneratedBuildRun(timeoutMs = 60000) {
  const startedAt = Date.now();
  let latest = null;
  while (Date.now() - startedAt < timeoutMs) {
    const response = await fetch('http://localhost:8000/api/eval/runs');
    const runs = await response.json();
    latest = runs.find((run) => {
      const datasetPath = run.dataset_path ?? run.result?.dataset_path ?? run.result?.provenance?.dataset_path;
      return String(datasetPath ?? '').endsWith('generated_build.yaml');
    }) ?? latest;
    if (latest && ['completed', 'failed', 'cancelled'].includes(latest.status)) {
      return latest;
    }
    await new Promise((resolve) => setTimeout(resolve, 2500));
  }
  return latest;
}

let fatalError = null;
try {
  await page.goto(`${baseUrl}/build?tab=builder-chat`, { waitUntil: 'networkidle' });
  await page.getByTestId('builder-composer').fill(prompt);
  await page.getByTestId('builder-send').click();
  await page.waitForFunction(() => {
    const node = document.querySelector('[data-testid="builder-preview-agent-name"]');
    return node && node.textContent && node.textContent.includes('FAQ Concierge');
  }, null, { timeout: 70000 });
  steps.push({
    step: 'build',
    url: page.url(),
    agentName: await page.getByTestId('builder-preview-agent-name').innerText(),
    toolCount: await page.getByTestId('builder-stat-tools').innerText(),
    policyCount: await page.getByTestId('builder-stat-policies').innerText(),
    routeCount: await page.getByTestId('builder-stat-routes').innerText(),
  });

  await page.getByTestId('builder-preview-input').fill(
    'How do I enable SSO on the Team plan, and should this go through security review?'
  );
  await clickByRole(page, /^Test Agent$/);
  await page.waitForFunction(() => document.body.innerText.includes('Tool:'), null, { timeout: 30000 }).catch(() => {});
  steps.push({
    step: 'preview',
    text: sample(await bodyText(page), 3200),
  });

  await page.getByTestId('builder-run-eval').click();
  await page.waitForURL(/\/evals\?/, { timeout: 30000 });
  await page.waitForLoadState('networkidle');
  const evalUrl = page.url();
  steps.push({
    step: 'save-to-evals',
    url: evalUrl,
    text: sample(await bodyText(page), 2600),
  });

  await clickByRole(page, /Run First Eval|Start Eval/, 20000);
  const generatedBuildRun = await pollLatestGeneratedBuildRun();
  await page.waitForTimeout(1500);
  steps.push({
    step: 'eval-started',
    url: page.url(),
    generatedBuildRun,
    evalStartRequests,
    text: sample(await bodyText(page), 3200),
  });

  const agentId = new URL(page.url()).searchParams.get('agent');
  await page.goto(`${baseUrl}/workbench`, { waitUntil: 'networkidle' });
  steps.push({
    step: 'workbench',
    url: page.url(),
    text: sample(await bodyText(page), 2600),
  });

  await page.goto(`${baseUrl}/optimize${agentId ? `?agent=${encodeURIComponent(agentId)}` : ''}`, {
    waitUntil: 'networkidle',
  });
  steps.push({
    step: 'optimize',
    url: page.url(),
    text: sample(await bodyText(page), 3200),
  });

  await page.goto(`${baseUrl}/improvements`, { waitUntil: 'networkidle' });
  steps.push({
    step: 'improvements',
    url: page.url(),
    text: sample(await bodyText(page), 2400),
  });

  await page.goto(`${baseUrl}/deploy?new=1`, { waitUntil: 'networkidle' });
  steps.push({
    step: 'deploy',
    url: page.url(),
    text: sample(await bodyText(page), 2800),
  });

  await page.screenshot({ path: '.tmp/golden-path-full-final.png', fullPage: true });
} catch (error) {
  fatalError = {
    name: error?.name ?? 'Error',
    message: error?.message ?? String(error),
    url: page.url(),
    text: sample(await bodyText(page).catch(() => ''), 4000),
  };
  await page.screenshot({ path: '.tmp/golden-path-full-error.png', fullPage: true }).catch(() => {});
} finally {
  await browser.close();
}

console.log(JSON.stringify({
  steps,
  fatalError,
  consoleMessages,
  failedRequests,
}, null, 2));
