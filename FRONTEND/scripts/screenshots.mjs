/**
 * Walks through every screen at desktop, tablet and phone sizes and saves screenshots
 * to screenshots/. Also reports horizontal overflow, which should never happen.
 *
 *   npm run build && npm run preview      # in one terminal (serves http://localhost:4173)
 *   npm run screenshots                   # in another
 *
 * Env: BASE_URL (default http://localhost:4173), CHROME_PATH (default: system Chrome),
 * THEME=dark to walk the dark theme (saved to screenshots/dark/; the default is light).
 * Uses playwright-core with an installed Chrome, so no browser download is needed.
 */
import { chromium } from 'playwright-core';
import { existsSync, mkdirSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const theme = process.env.THEME === 'dark' ? 'dark' : 'light'; // the system setting the browser reports
const outDir = join(root, 'screenshots', ...(theme === 'dark' ? ['dark'] : []));
const baseUrl = process.env.BASE_URL ?? 'http://localhost:4173';
const chromePath =
  process.env.CHROME_PATH ??
  ['/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser', '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'].find(existsSync);
const only = process.argv[2]; // optional: desktop | tablet | phone

if (!chromePath) {
  console.error('No Chrome found. Set CHROME_PATH to a Chrome or Chromium executable.');
  process.exit(1);
}
mkdirSync(outDir, { recursive: true });

const VIEWPORTS = {
  desktop: { width: 1440, height: 900 },
  tablet: { width: 834, height: 1112 },
  phone: { width: 390, height: 844 },
};

const problems = [];
const browser = await chromium.launch({
  executablePath: chromePath,
  args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
});

async function newPage(viewport, options = {}) {
  const context = await browser.newContext({ viewport, deviceScaleFactor: 1, colorScheme: theme, ...options });
  const page = await context.newPage();
  page.on('pageerror', (error) => problems.push(`page error: ${error.message}`));
  page.on('console', (message) => {
    if (message.type() === 'error') problems.push(`console error: ${message.text()}`);
  });
  return page;
}

async function shot(page, name, { fullPage = false } = {}) {
  await page.waitForTimeout(450); // let enter transitions finish
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  if (overflow > 0) problems.push(`${name}: page scrolls sideways by ${overflow}px`);
  await page.screenshot({ path: join(outDir, `${name}.png`), fullPage });
  console.log(`saved ${name}.png`);
}

async function robot3d(page) {
  await page.waitForSelector('.robot[data-renderer="3d"]', { timeout: 8000 }).catch(() => {
    problems.push('3D robot did not appear within 8s');
  });
}

const sampleFile = (name, text, mimeType) => ({ name, mimeType, buffer: Buffer.from(text) });

async function chooseDocument(page, file) {
  await page.setInputFiles('[data-testid="document-input"]', file);
}

async function documentFlow(page, prefix, viewportName) {
  const desktop = viewportName === 'desktop';
  await page.goto(baseUrl);
  await robot3d(page);
  await page.waitForTimeout(desktop ? 700 : 2800); // mid-wave on desktop, settled elsewhere
  await shot(page, `${prefix}-01-welcome`);

  await page.getByRole('button', { name: /Learn from a document/ }).click();
  await robot3d(page);
  await shot(page, `${prefix}-02-select-document`);

  if (desktop) {
    await chooseDocument(page, sampleFile('holiday-photo.png', 'not a document', 'image/png'));
    await shot(page, `${prefix}-03-select-invalid-file`);
  }

  await chooseDocument(page, sampleFile('Fruit-Growing-Guide.pdf', '%PDF-1.4 sample bytes for the demo', 'application/pdf'));
  await page.waitForTimeout(1700); // the robot's short celebration
  await shot(page, `${prefix}-04-select-document-chosen`);

  await page.getByRole('button', { name: /Open document/ }).click();
  if (desktop) await shot(page, `${prefix}-05-processing`);

  await page.waitForSelector('.notes__title', { timeout: 8000 });
  await robot3d(page);
  await shot(page, `${prefix}-06-notes`, { fullPage: !desktop });

  // Collapsed source lists must really be hidden (a CSS display rule once overrode `hidden`).
  if (await page.locator('#panel-notes .sources__list').isVisible()) problems.push(`${prefix}: notes sources visible while collapsed`);

  if (desktop) {
    await page.getByRole('button', { name: 'Show source 3' }).first().click();
    if (!(await page.locator('#panel-notes .sources__list').isVisible())) problems.push(`${prefix}: citation did not open the sources`);
    await shot(page, `${prefix}-07-notes-source-open`);
  }

  await page.getByRole('tab', { name: 'Ask' }).click();
  await shot(page, `${prefix}-08-ask-empty`);

  for (const question of ['Which planet is the largest?', 'How many moons does Mars have, and who discovered them?', 'Who discovered Neptune?', 'How far is Mars from the Sun?']) {
    await page.getByLabel('Your question').fill(question);
    await page.keyboard.press('Enter');
    await page.waitForSelector('.answer--pending', { state: 'detached', timeout: 8000 });
  }
  await page.locator('#panel-ask .sources__toggle').first().click();
  await page.waitForTimeout(400);
  await shot(page, `${prefix}-09-ask-answers`, { fullPage: true });

  await page.getByRole('tab', { name: 'Quiz' }).click();
  await page.waitForSelector('.quiz__prompt', { timeout: 8000 });
  await shot(page, `${prefix}-10-quiz-question`);

  await page.locator('.option').first().click(); // "460 million years ago" — wrong
  await page.getByRole('button', { name: 'Check answer' }).click();
  await shot(page, `${prefix}-11-quiz-feedback`, { fullPage: !desktop });

  const correct = ['c', 'a', 'b', 'c'];
  for (const id of correct) {
    await page.getByRole('button', { name: /Next question|See results/ }).click();
    await page.locator(`.option input[value="${id}"]`).check({ force: true });
    await page.getByRole('button', { name: 'Check answer' }).click();
  }
  await page.getByRole('button', { name: 'See results' }).click();
  await shot(page, `${prefix}-12-quiz-results`, { fullPage: true });
}

async function codebaseFlow(page, prefix) {
  await page.goto(baseUrl);
  await page.getByRole('button', { name: /Understand a codebase/ }).click();
  await robot3d(page);
  await shot(page, `${prefix}-13-select-folder`);

  // A real folder: this frontend's own source code.
  await page.setInputFiles('[data-testid="folder-input"]', join(root, 'src'));
  await page.waitForTimeout(1700);
  await shot(page, `${prefix}-14-select-folder-chosen`);

  await page.getByRole('button', { name: /Explore codebase/ }).click();
  await page.waitForSelector('.deck__question', { timeout: 8000 });
  await robot3d(page);
  await shot(page, `${prefix}-15-codebase`, { fullPage: true });

  await page.getByRole('button', { name: 'Next' }).click();
  await page.getByRole('button', { name: 'Next' }).click();
  await shot(page, `${prefix}-16-codebase-card-3`);
}

async function errorStates(page, prefix) {
  await page.goto(`${baseUrl}/?simulate=ask-error,open-error`);
  await page.getByRole('button', { name: /Quiz yourself/ }).click();
  await chooseDocument(page, sampleFile('notes.md', '# Notes', 'text/markdown'));
  await page.getByRole('button', { name: /Build my quiz/ }).click();
  await page.waitForSelector('.notice--error', { timeout: 8000 });
  await shot(page, `${prefix}-17-open-failed`);

  await page.getByRole('button', { name: 'Try again' }).click();
  await page.waitForSelector('.quiz__prompt', { timeout: 8000 });
  await page.getByRole('tab', { name: 'Ask' }).click();
  await page.getByRole('button', { name: 'Which planet is the largest?' }).click();
  await page.waitForSelector('.answer--error', { timeout: 8000 });
  await shot(page, `${prefix}-18-ask-error`);
}

async function reducedMotion() {
  const page = await newPage(VIEWPORTS.desktop, { reducedMotion: 'reduce' });
  await page.goto(baseUrl);
  await page.waitForTimeout(600);
  const renderer = await page.getAttribute('.robot', 'data-renderer');
  if (renderer !== 'svg') problems.push(`reduced motion: expected the SVG robot, got ${renderer}`);
  await shot(page, 'desktop-19-welcome-reduced-motion');
  await page.getByRole('button', { name: /Understand a codebase/ }).click();
  await shot(page, 'desktop-20-select-folder-svg-robot');
  await page.context().close();
}

for (const [name, viewport] of Object.entries(VIEWPORTS)) {
  if (only && only !== name) continue;
  const page = await newPage(viewport);
  await documentFlow(page, name, name);
  await codebaseFlow(page, name);
  if (name === 'desktop' || name === 'phone') await errorStates(page, name);
  await page.context().close();
}
if (!only || only === 'desktop') await reducedMotion();

await browser.close();
if (problems.length) {
  console.log('\nProblems found:');
  for (const p of problems) console.log(` - ${p}`);
  process.exitCode = 1;
} else {
  console.log('\nNo overflow, page errors or console errors found.');
}
