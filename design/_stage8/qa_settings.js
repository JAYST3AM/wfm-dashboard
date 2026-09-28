/* Stage 8 QA: the settings categories, headless.
 *
 *   node design/_stage8/qa_settings.js
 *
 * Read-only: it opens /settings.html, clicks the six category pills (never a Save button), checks
 * that exactly one panel is in the flow at a time with its rows rendered, that every id from
 * design/_stage8/ids_before.json is still in the DOM, that the two deep links paint the right
 * category, and that the console stays clean. Writes the two screenshots and a JSON report.
 */
'use strict';
const puppeteer = require('F:/VSC Projects/pb-bench/node_modules/puppeteer-core');
const fs = require('fs');
const path = require('path');
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const SHOTS = 'C:/Users/jayde/AppData/Local/Temp/shotkit/shots';
const HERE = __dirname;
const BASE = 'http://127.0.0.1:8787';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const CATS = ['general', 'trading', 'appearance', 'accounts', 'notifications', 'advanced'];
// what each category must render, straight off the GROUPS table in settings.js
// (advanced is the two-card category: the explanation switch row + the server's host/port rows)
const ROWS = { general: 3, trading: 8, appearance: 5, notifications: 1, advanced: 3 };

(async () => {
  const before = JSON.parse(fs.readFileSync(path.join(HERE, 'ids_before.json'), 'utf-8'));
  const browser = await puppeteer.launch({ executablePath: CHROME, headless: 'new',
    args: ['--no-sandbox', '--disable-dev-shm-usage'] });
  const page = await browser.newPage();
  await page.setViewport({ width: 1920, height: 1080 });
  const problems = [];
  const console_errors = [];
  page.on('console', (m) => { if (m.type() === 'error') console_errors.push(m.text()); });
  page.on('pageerror', (e) => console_errors.push('pageerror: ' + e.message));

  await page.goto(BASE + '/settings.html', { waitUntil: 'load' });
  await sleep(2200);

  const report = { categories: {}, ids: {}, deep_links: {}, console_errors, problems };

  // 1. click through all six categories (pills only - a Save click would write real config)
  for (const cat of CATS) {
    await page.evaluate((c) => document.querySelector('#settingsCats [data-cat="' + c + '"]').click(), cat);
    await sleep(450);
    const state = await page.evaluate((c) => {
      const panels = [...document.querySelectorAll('.st-cat')];
      const visible = panels.filter((p) => !p.classList.contains('hidden'));
      const panel = document.getElementById('cat-' + c);
      const pill = document.querySelector('#settingsCats [data-cat="' + c + '"]');
      const rows = panel ? panel.querySelectorAll('.cfgrow').length : -1;
      const listIds = [...panel.querySelectorAll('[id^="list-"]')].map((n) => [n.id, n.children.length]);
      return {
        hash: location.hash, visible: visible.map((p) => p.id), rows, listIds,
        pill_active: pill.classList.contains('active'),
        pill_current: pill.getAttribute('aria-current'),
        active_pills: [...document.querySelectorAll('#settingsCats .navpill.active, #settingsCats .st-catpill.active')]
          .map((p) => p.dataset.cat || p.textContent),
        h_scroll: document.documentElement.scrollWidth - window.innerWidth,
        buttons: panel.querySelectorAll('button').length,
      };
    }, cat);
    report.categories[cat] = state;
    if (state.visible.length !== 1 || state.visible[0] !== 'cat-' + cat) {
      problems.push(cat + ': visible panels = ' + JSON.stringify(state.visible));
    }
    if (ROWS[cat] !== undefined && state.rows !== ROWS[cat]) {
      problems.push(cat + ': row count ' + state.rows + ' != ' + ROWS[cat]);
    }
    if (state.hash !== '#' + cat) problems.push(cat + ': hash is ' + state.hash);
    if (!state.pill_active || state.pill_current !== 'page') problems.push(cat + ': pill not marked current');
    if (state.active_pills.length !== 2) problems.push(cat + ': active pills = ' + JSON.stringify(state.active_pills));
    if (state.h_scroll > 0) problems.push(cat + ': horizontal overflow ' + state.h_scroll + 'px');
    if (cat !== 'notifications' && state.buttons === 0) problems.push(cat + ': no controls rendered');
  }

  // 2. the id union across the whole click-through: nothing from before stage 8 may be missing
  const rendered = await page.evaluate(() => [...new Set([...document.querySelectorAll('[id]')].map((n) => n.id))]);
  report.ids = { rendered: rendered.length, missing: before.ids.filter((i) => !rendered.includes(i)) };
  if (report.ids.missing.length) problems.push('ids missing: ' + report.ids.missing.join(', '));

  // 3. screenshots: the default category and a deep link straight to Trading
  await page.evaluate(() => document.querySelector('#settingsCats [data-cat="general"]').click());
  await sleep(500);
  await page.screenshot({ path: path.join(SHOTS, 's8-settings-general.png') });
  await page.goto(BASE + '/settings.html#trading', { waitUntil: 'load' });
  await sleep(2200);
  const deep = await page.evaluate(() => {
    const visible = [...document.querySelectorAll('.st-cat')].filter((p) => !p.classList.contains('hidden')).map((p) => p.id);
    const pill = document.querySelector('#settingsCats [data-cat="trading"]');
    return { visible, active: pill.classList.contains('active'), rows: document.querySelectorAll('#cat-trading .cfgrow').length };
  });
  report.deep_links['#trading'] = deep;
  if (deep.visible.length !== 1 || deep.visible[0] !== 'cat-trading' || !deep.active) {
    problems.push('#trading deep link did not land: ' + JSON.stringify(deep));
  }
  await page.screenshot({ path: path.join(SHOTS, 's8-settings-trading.png') });

  // 4. the empty hash falls back to General
  await page.goto(BASE + '/settings.html#advanced', { waitUntil: 'load' });
  await sleep(1500);
  await page.goto(BASE + '/settings.html', { waitUntil: 'load' });
  await sleep(1500);
  const dflt = await page.evaluate(() => [...document.querySelectorAll('.st-cat')].filter((p) => !p.classList.contains('hidden')).map((p) => p.id));
  report.deep_links['(no hash)'] = dflt;
  if (dflt.join() !== 'cat-general') problems.push('default category is not General: ' + JSON.stringify(dflt));

  report.console_errors = console_errors;
  fs.writeFileSync(path.join(HERE, 'qa_settings.json'), JSON.stringify(report, null, 1));
  console.log(JSON.stringify(report, null, 1));
  console.log('\nconsole errors:', console_errors.length, console_errors.slice(0, 8));
  console.log('problems:', problems.length, problems);
  await browser.close();
  process.exit(problems.length || console_errors.length ? 1 : 0);
})();
