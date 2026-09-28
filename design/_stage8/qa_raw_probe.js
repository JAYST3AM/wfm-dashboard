/* Stage 8 raw-config probe: the Advanced category's implementation surface, headless.
 *
 *   node design/_stage8/qa_raw_probe.js
 *
 * Read-only except the accordion toggle (a UI disclosure, never a Save): checks the raw-key table
 * still renders both schemas, its payload problem line is empty, the accordion still toggles the
 * labelled region, and the raw table's own sideways scroll box keeps the page from overflowing.
 */
'use strict';
const puppeteer = require('F:/VSC Projects/pb-bench/node_modules/puppeteer-core');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  const b = await puppeteer.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe',
    headless: 'new', args: ['--no-sandbox', '--disable-dev-shm-usage'] });
  const p = await b.newPage();
  const errs = [];
  p.on('console', (m) => { if (m.type() === 'error') errs.push(m.text()); });
  p.on('pageerror', (e) => errs.push('pageerror: ' + e.message));
  await p.setViewport({ width: 1600, height: 1000 });
  await p.goto('http://127.0.0.1:8787/settings.html#advanced', { waitUntil: 'load' });
  await sleep(2000);
  const before = await p.evaluate(() => ({
    panel_hidden: document.getElementById('advPanel').hidden,
    rows: document.querySelectorAll('#rawRows tr').length,
    first_row: [...document.querySelectorAll('#rawRows tr:first-child td')].map((t) => t.textContent),
    dead_key_marked: document.querySelectorAll('#rawRows td.by .dead').length,
    err: document.getElementById('advErr').textContent,
    adv_on: document.documentElement.dataset.adv,
  }));
  await p.evaluate(() => document.getElementById('advBtn').click());
  await sleep(400);
  const after = await p.evaluate(() => ({
    panel_hidden: document.getElementById('advPanel').hidden,
    expanded: document.getElementById('advBtn').getAttribute('aria-expanded'),
    raw_scroll: document.querySelector('.st-rawwrap').scrollWidth - document.querySelector('.st-rawwrap').clientWidth,
    page_overflow: document.documentElement.scrollWidth - window.innerWidth,
  }));
  console.log(JSON.stringify({ before, after, errs }, null, 1));
  await b.close();
  // the accordion ships collapsed (its own default) - the failure is it not opening, or errors
  process.exit(errs.length || after.panel_hidden || after.expanded !== 'true' ? 1 : 0);
})();
