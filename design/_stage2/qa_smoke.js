/* Stage 2 smoke probe (heads-up): does the new rail/tools/mastery wiring run at all?
 *   node design/_stage2/qa_smoke.js
 */
'use strict';
const puppeteer = require('F:/VSC Projects/pb-bench/node_modules/puppeteer-core');
const BASE = 'http://127.0.0.1:8787';
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  const browser = await puppeteer.launch({ executablePath: CHROME, headless: 'new',
    args: ['--no-sandbox', '--disable-dev-shm-usage', '--window-size=1920,1080'] });
  const page = await browser.newPage();
  const errs = [];
  page.on('console', (m) => { if (m.type() === 'error') errs.push('console: ' + m.text()); });
  page.on('pageerror', (e) => errs.push('pageerror: ' + String(e.message || e)));
  await page.setViewport({ width: 1920, height: 1080 });
  await page.goto(BASE + '/', { waitUntil: 'load' });
  await sleep(1800);

  const rail = await page.evaluate(() => {
    const pills = [...document.querySelectorAll('#mainnav .navpill')];
    return { n: pills.length, rows: pills.map((p) => [p.dataset.v, p.getAttribute('href'), p.textContent.trim(), p.classList.contains('active')]) };
  });
  console.log('RAIL', JSON.stringify(rail, null, 1));

  const tools = await page.evaluate(async () => {
    const out = {};
    const wait = (ms) => new Promise((r) => setTimeout(r, ms));
    location.hash = '#tools';
    await wait(400);
    out.launcherHidden = document.getElementById('toolsLauncher').classList.contains('hidden');
    out.entries = [...document.querySelectorAll('#toolsLauncher .tool')].length;
    const slugs = ['deals', 'trends', 'rivens', 'wl', 'ducats', 'craft', 'relicev', 'sets', 'baro', 'meta', 'player'];
    out.slug = {};
    for (const s of slugs) {
      location.hash = '#tools/' + s;
      await wait(260);
      const el = document.querySelector('#toolsWs [data-tool="' + s + '"]');
      const sec = document.getElementById('view-tools');
      const vis = el && !el.classList.contains('hidden');
      const boxes = el ? [...el.querySelectorAll('[id$="List"]')] : [];
      out.slug[s] = { vis, hash: location.hash, launcherHidden: document.getElementById('toolsLauncher').classList.contains('hidden'),
        lists: boxes.map((b) => [b.id, b.children.length]),
        secVisible: sec && !sec.classList.contains('hidden') };
    }
    return out;
  });
  console.log('TOOLS', JSON.stringify(tools, null, 1));

  /* legacy hashes */
  const legacy = await page.evaluate(async () => {
    const wait = (ms) => new Promise((r) => setTimeout(r, ms));
    const out = {};
    for (const h of ['#more', '#player', '#market', '#history']) {
      location.hash = '#home'; await wait(150);
      location.hash = h; await wait(400);
      out[h] = { hash: location.hash, tools: !document.getElementById('view-tools').classList.contains('hidden'),
        player: !document.getElementById('view-player').classList.contains('hidden'),
        trade: !document.getElementById('view-trade').classList.contains('hidden') };
    }
    return out;
  });
  console.log('LEGACY', JSON.stringify(legacy, null, 1));

  /* mastery redirect */
  await page.evaluate(() => { location.hash = '#mastery'; });
  await sleep(1600);
  console.log('MASTERY REDIRECT ->', page.url());

  const mh = await page.evaluate(() => ({
    url: location.href,
    view: document.getElementById('view-mastery') ? !document.getElementById('view-mastery').classList.contains('hidden') : 'missing',
    rows: document.querySelectorAll('#mhNext .mh-row').length,
    cats: document.querySelectorAll('#mhCats .mh-cat').length,
    pills: [...document.querySelectorAll('#collectionNav .navpill')].map((p) => [p.dataset.v, p.classList.contains('active')]),
    gridHidden: document.getElementById('grid').classList.contains('hidden'),
  }));
  console.log('MASTERY', JSON.stringify(mh, null, 1));

  console.log('ERRORS', JSON.stringify(errs, null, 1));
  await browser.close();
})().catch((e) => { console.error('SMOKE FAILED', e); process.exit(1); });
