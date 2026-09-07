import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import path from 'node:path';
import assert from 'node:assert/strict';

const require = createRequire(import.meta.url);
let browserPackage;
try { browserPackage = require('playwright'); }
catch {
  const runtime = process.env.PLAYWRIGHT_NODE_MODULES || process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES;
  if (!runtime) throw Error('Install playwright to run the browser check.');
  browserPackage = require(path.join(runtime, 'playwright'));
}
const root = path.resolve('services/video/narma_video/static');
const files = { '/': ['index.html', 'text/html'], '/assets/portal.js': ['portal.js', 'text/javascript'], '/assets/portal.css': ['portal.css', 'text/css'] };
const server = createServer(async (request, response) => {
  const file = files[request.url];
  if (!file) { response.writeHead(404).end(); return; }
  response.setHeader('Content-Type', file[1]); response.end(await readFile(path.join(root, file[0])));
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const origin = `http://127.0.0.1:${server.address().port}`;
const browser = await browserPackage.chromium.launch({ headless: true, args: ['--no-sandbox'] });
try {
  for (const width of [390, 1440]) {
    const page = await browser.newPage({ viewport: { width, height: 1000 } });
    let authenticated = false;
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.route('**/api/**', async route => {
      const endpoint = new URL(route.request().url()).pathname;
      let body;
      if (endpoint === '/api/auth/login') { authenticated = true; body = { authenticated: true }; }
      else if (endpoint === '/api/session') body = { authenticated, setup_required: false, user: authenticated ? { email: 'fixture@example.test' } : null };
      else if (endpoint === '/api/profile') body = { profile: null };
      else if (endpoint === '/api/videos') body = { videos: [], worker_ready: true, budget_available: true, frame_budget: 3600 };
      else throw Error('Unexpected frontend API request');
      await route.fulfill({ json: body });
    });
    await page.goto(origin);
    await page.getByLabel('Email', { exact: true }).fill('fixture@example.test');
    await page.getByLabel('Пароль', { exact: true }).fill('Synthetic passphrase 2026');
    await page.getByRole('button', { name: 'Войти', exact: true }).click();
    await page.getByRole('heading', { name: 'Разбери свой эпизод' }).waitFor();
    assert.equal(await page.getByRole('button', { name: 'Загрузить и разобрать' }).isDisabled(), true);
    await page.getByRole('button', { name: 'Закрепить игрока', exact: true }).click();
    await page.getByRole('heading', { name: 'Мой игрок', exact: true }).waitFor();
    await page.addScriptTag({ path: require.resolve('axe-core/axe.min.js') });
    const accessibility = await page.evaluate(async () => window.axe.run(document, { runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21aa'] } }));
    assert.deepEqual(accessibility.violations.map(v => ({ id: v.id, nodes: v.nodes.map(n => n.target) })), []);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    assert.deepEqual(errors, []);
    await page.close();
  }
  console.log('Portal login/navigation, bound-player gate, mobile layout and WCAG checks passed (mocked API; no provider requests).');
} finally {
  await browser.close(); await new Promise(resolve => server.close(resolve));
}
