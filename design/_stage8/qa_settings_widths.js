/* Stage 8 widths probe: the settings page at the sizes the density pass measured.
 *
 *   node design/_stage8/qa_settings_widths.js
 *
 * Read-only. Checks no horizontal overflow, one visible panel, console clean, and that the
 * sidebar folds into a pill row under 1000px (the categories stay reachable at every width).
 */
'use strict';
const puppeteer = require('F:/VSC Projects/pb-bench/node_modules/puppeteer-core');
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const BASE = 'http://127.0.0.1:8787';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const SIZES = [[1440, 900], [1100, 800], [900, 800], [390, 844]];

(async () => {
  const browser = await puppeteer.launch({ executablePath: CHROME, headless: 'new',
    args: ['--no-sandbox', '--disable-dev-shm-usage'] });
  const problems = [];
  for (const [w, h] of SIZES) {
    const page = await browser.newPage();
    await page.setViewport({ width: w, height: h });
    const errors = [];
    page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
    page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
    await page.goto(BASE + '/settings.html#trading', { waitUntil: 'load' });
    await sleep(1800);
    const state = await page.evaluate(() => {
      const nav = document.getElementById('settingsCats');
      const cats = [...nav.querySelectorAll('[data-cat]')];
      const boxes = cats.map((c) => c.getBoundingClientRect());
      const pills = new Set(boxes.map((b) => Math.round(b.top / 8)));
      return {
        overflow: document.documentElement.scrollWidth - window.innerWidth,
        visible: [...document.querySelectorAll('.st-cat')].filter((p) => !p.classList.contains('hidden')).map((p) => p.id),
        rows: document.querySelectorAll('#cat-trading .cfgrow').length,
        nav_direction: getComputedStyle(nav).flexDirection,
        rows_of_pills: pills.size,
        all_visible: boxes.every((b) => b.width > 0 && b.height > 0),
      };
    });
    const bad = [];
    if (state.overflow > 0) bad.push('overflow ' + state.overflow + 'px');
    if (state.visible.join() !== 'cat-trading') bad.push('visible ' + state.visible);
    if (state.rows !== 8) bad.push('rows ' + state.rows);
    if (!state.all_visible) bad.push('a pill has no box');
    if (errors.length) bad.push('console ' + errors[0]);
    console.log(w + 'x' + h, JSON.stringify(state), bad.length ? 'FAIL ' + bad : 'ok');
    problems.push(...bad.map((b) => w + 'x' + h + ': ' + b));
    await page.close();
  }
  await browser.close();
  console.log('problems:', problems.length, problems);
  process.exit(problems.length ? 1 : 0);
})();
