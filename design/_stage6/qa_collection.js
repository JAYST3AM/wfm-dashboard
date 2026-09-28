/* Stage 6 - Collection consolidation: state probe + shots.
 *   node design/_stage6/qa_collection.js            (defaults to shots in /shots)
 *   node design/_stage6/qa_collection.js before     (writes s6-*-before.png)
 * Read-only: never clicks anything that writes data.
 */
'use strict';
const puppeteer = require('F:/VSC Projects/pb-bench/node_modules/puppeteer-core');
const fs = require('fs');
const path = require('path');
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const SHOTS = 'C:/Users/jayde/AppData/Local/Temp/shotkit/shots';
const TAG = process.argv[2] === 'before' ? '-before' : '';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: 'new',
    args: ['--no-sandbox', '--disable-dev-shm-usage', '--force-device-scale-factor=1'] });
  const p = await b.newPage();
  await p.setViewport({ width: 1920, height: 1080 });
  const errors = [];
  p.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  p.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
  const out = {};

  async function shot(name) {
    await p.screenshot({ path: path.join(SHOTS, 's6-' + name + TAG + '.png') });
  }

  // ---------------- 1. Collection (default, no hash)
  await p.goto('http://127.0.0.1:8787/collection.html', { waitUntil: 'load' });
  await sleep(2500);
  out.gridIds = await p.evaluate(() => ({
    nav: [...document.querySelectorAll('#collectionNav .navpill')].map((a) => ({
      v: a.dataset.v, href: a.getAttribute('href'), cls: a.className,
      cur: a.getAttribute('aria-current'), txt: a.textContent.trim() })),
    wrapTop: (() => { const m = document.querySelector('.cl-wrap'); return m ? m.getBoundingClientRect().top : null; })(),
    docH: document.documentElement.scrollHeight,
    tiles: document.querySelectorAll('#grid .cl-card').length,
    tabs: document.querySelectorAll('#tabs .tab').length,
    title: (document.querySelector('h1') ? document.querySelector('h1').textContent.trim() : null),
    overallTitle: (() => { const e = document.querySelector('.cl-ov-title'); return e ? e.textContent.trim() : null; })(),
    meta: (() => { const e = document.getElementById('meta'); return e ? e.textContent.trim() : null; })(),
    foot: (() => { const e = document.querySelector('.cl-foot'); return e ? e.textContent.replace(/\s+/g, ' ').trim() : null; })(),
    strata: [...document.querySelectorAll('.cl-wrap > *')].map((e) => e.id || e.className)
  }));
  await shot('grid');

  // search filter: assert the tile count drops
  const q = await p.$('#q');
  await q.click();
  await p.type('#q', 'braton');
  await sleep(500);
  out.searchTiles = await p.evaluate(() => document.querySelectorAll('#grid .cl-card').length);
  out.searchMeta = await p.evaluate(() => document.getElementById('meta').textContent.trim());
  await p.evaluate(() => { const c = document.getElementById('clearBtn'); if (c) c.click(); });
  await sleep(300);
  out.searchClearedTiles = await p.evaluate(() => document.querySelectorAll('#grid .cl-card').length);

  // ---------------- 2. Relics
  await p.evaluate(() => { location.hash = '#relics'; });
  await sleep(1400);
  out.relics = await p.evaluate(() => ({
    navActive: (document.querySelector('#collectionNav .navpill.active') || {}).dataset || null,
    rows: document.querySelectorAll('#relBody tr').length,
    head: [...document.querySelectorAll('#relHead th')].map((t) => t.textContent.trim().replace(/\s+/g, ' ')),
    dockText: (document.getElementById('relDock').textContent || '').replace(/\s+/g, ' ').trim().slice(0, 400),
    dockH: document.getElementById('relDock').getBoundingClientRect().height,
    pills: [...document.querySelectorAll('#relPills .cl-relpill, #relPills button')].map((x) => x.textContent.trim()),
    gridHidden: document.getElementById('grid').classList.contains('hidden'),
    mhHidden: document.getElementById('view-mastery').classList.contains('hidden'),
    scrollX: document.documentElement.scrollWidth, docH: document.documentElement.scrollHeight
  }));
  await shot('relics');

  // ---------------- 3. Mastery
  await p.evaluate(() => { location.hash = '#mastery'; });
  await sleep(1600);
  out.mastery = await p.evaluate(() => ({
    navActive: (document.querySelector('#collectionNav .navpill.active') || {}).dataset || null,
    mhMeta: (document.getElementById('mhMeta') || {}).textContent,
    head: (document.getElementById('mhHead') || {}).textContent,
    stats: (document.getElementById('mhStats') || {}).textContent,
    nextRows: document.querySelectorAll('#mhNext .mh-row, #mhNext > *').length,
    cats: document.querySelectorAll('#mhCats .mh-cat, #mhCats > *').length,
    filters: [...document.querySelectorAll('#mhFilters button, #mhFilters .range')].map((x) => x.textContent.trim()),
    cap: (document.getElementById('mhCap') || {}).textContent,
    gridHidden: document.getElementById('grid').classList.contains('hidden'),
    relicHidden: document.getElementById('relicView').classList.contains('hidden'),
    docH: document.documentElement.scrollHeight
  }));
  await shot('mastery');

  // ---------------- 4. keyboard: arrow keys / tab focus on the section row
  await p.evaluate(() => { location.hash = ''; document.getElementById('collectionNav').querySelector('.navpill').focus(); });
  await sleep(500);
  out.kbFocus = await p.evaluate(() => document.activeElement && document.activeElement.textContent.trim());
  await p.keyboard.press('ArrowRight');
  await sleep(300);
  out.kbAfterRight = await p.evaluate(() => ({
    focus: document.activeElement && document.activeElement.textContent.trim(),
    hash: location.hash }));

  // ---------------- 5. id union (for the diff vs the stage-2 snapshot)
  out.ids = await p.evaluate(() => [...document.querySelectorAll('[id]')].map((e) => e.id).sort());

  out.consoleErrors = errors;
  fs.writeFileSync(path.join('design', '_stage6', 'qa_state' + (TAG || '') + '.json'),
    JSON.stringify(out, null, 1));
  console.log(JSON.stringify(out, null, 1));
  await b.close();
})();
