import playwright from '../web/node_modules/playwright/index.js';

const { chromium } = playwright;
const baseUrl = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:5173';
const buildRequests = [];
const failedRequests = [];
const consoleMessages = [];

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });

page.on('request', (request) => {
  if (request.method() === 'POST' && request.url().includes('/api/workbench/build/stream')) {
    buildRequests.push(request.postData() ?? '');
  }
});

page.on('requestfailed', (request) => {
  if (!request.url().includes('/ws')) {
    failedRequests.push(`${request.method()} ${request.url()} ${request.failure()?.errorText ?? ''}`);
  }
});

page.on('console', (message) => {
  if (['error', 'warning'].includes(message.type())) {
    consoleMessages.push(`${message.type()}: ${message.text()}`);
  }
});

let fatalError = null;
try {
  await page.goto(
    `${baseUrl}/workbench?agent=agent-v005&agentName=FAQ+Concierge&configPath=configs%2Fv005.yaml`,
    { waitUntil: 'networkidle' }
  );
  await page.waitForFunction(
    () => document.body.innerText.includes('Continuing from Build'),
    null,
    { timeout: 15000 }
  );
  await page.waitForFunction(
    () => document.body.innerText.includes('FAQ Concierge'),
    null,
    { timeout: 15000 }
  ).catch(() => {});
  await page.waitForTimeout(2500);
} catch (error) {
  fatalError = {
    name: error?.name ?? 'Error',
    message: error?.message ?? String(error),
  };
}

const text = await page.locator('body').innerText();
const finalUrl = page.url();
await page.screenshot({ path: '.tmp/workbench-handoff.png', fullPage: true });
await browser.close();

console.log(JSON.stringify({
  url: finalUrl,
  buildRequests,
  fatalError,
  containsBuildHandoff: text.includes('Continuing from Build'),
  containsFaqConcierge: text.includes('FAQ Concierge'),
  textSample: text.slice(0, 2400),
  consoleMessages,
  failedRequests,
}, null, 2));
