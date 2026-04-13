import playwright from '../web/node_modules/playwright/index.js';

const { chromium } = playwright;

const baseUrl = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:5173';
const screenshotPath = process.env.SCREENSHOT_PATH ?? '.tmp/build-probe.png';

const prompt = [
  'Build FAQ Concierge, a customer FAQ support agent for a fictional B2B SaaS.',
  'It should answer product setup, billing plan, security, and troubleshooting questions.',
  'It should escalate unclear billing/security issues, cite internal KB guidance, and keep a calm concise tone.',
  'Include tools for searching the knowledge base, checking account plan status, and creating escalation tickets.',
].join(' ');

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
const consoleMessages = [];
const failedRequests = [];

page.on('console', (message) => {
  if (['error', 'warning'].includes(message.type())) {
    consoleMessages.push(`${message.type()}: ${message.text()}`);
  }
});

page.on('requestfailed', (request) => {
  failedRequests.push(`${request.method()} ${request.url()} ${request.failure()?.errorText ?? ''}`);
});

await page.goto(`${baseUrl}/build?tab=builder-chat`, { waitUntil: 'networkidle' });

const initialText = await page.locator('body').innerText();

const textbox = page.getByTestId('builder-composer');
await textbox.fill(prompt);

const buttonCandidates = [
  page.getByTestId('builder-send'),
  page.getByRole('button', { name: /^send$/i }),
  page.getByRole('button', { name: /draft/i }),
  page.getByRole('button', { name: /build/i }),
  page.getByRole('button', { name: /generate/i }),
];

let clicked = false;
for (const locator of buttonCandidates) {
  const count = await locator.count();
  if (count > 0 && await locator.first().isEnabled()) {
    await locator.first().click();
    clicked = true;
    break;
  }
}

if (!clicked) {
  await textbox.press('Meta+Enter').catch(async () => {
    await textbox.press('Enter');
  });
}

await page.waitForLoadState('networkidle');
await page.waitForFunction(() => {
  const node = document.querySelector('[data-testid="builder-preview-agent-name"]');
  return node && node.textContent && !node.textContent.includes('Draft pending');
}, null, { timeout: 60000 }).catch(() => {});
await page.waitForTimeout(1000);

const finalText = await page.locator('body').innerText();
const agentName = await page.getByTestId('builder-preview-agent-name').innerText().catch(() => '');
const toolCount = await page.getByTestId('builder-stat-tools').innerText().catch(() => '');
const policyCount = await page.getByTestId('builder-stat-policies').innerText().catch(() => '');
const routeCount = await page.getByTestId('builder-stat-routes').innerText().catch(() => '');
const buttons = await page.getByRole('button').evaluateAll((nodes) =>
  nodes.map((node) => node.textContent?.trim()).filter(Boolean).slice(0, 80)
);

await page.screenshot({ path: screenshotPath, fullPage: true });
await browser.close();

const interestingTerms = [
  'FAQ Concierge',
  'FAQ',
  'billing',
  'security',
  'knowledge base',
  'escalation',
  'HR',
  'employee',
  'airline',
  'mock',
  'live',
  'rate',
];

const termHits = Object.fromEntries(
  interestingTerms.map((term) => [term, finalText.toLowerCase().includes(term.toLowerCase())])
);

console.log(JSON.stringify({
  url: `${baseUrl}/build?tab=builder-chat`,
  prompt,
  initialTextSample: initialText.slice(0, 1200),
  finalTextSample: finalText.slice(0, 5000),
  finalTextLength: finalText.length,
  agentName,
  toolCount,
  policyCount,
  routeCount,
  buttons,
  termHits,
  consoleMessages,
  failedRequests,
  screenshotPath,
}, null, 2));
