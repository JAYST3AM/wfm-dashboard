/* Stage 6 - Collection consolidation: final click-through probe + the three 1920x1080 shots.
 *   node design/_stage6/qa_stage6.js
 * Read-only: never clicks anything that writes data.
 */
'use strict';
const puppeteer = require('F:/VSC Projects/pb-bench/node_modules/puppeteer-core');
const fs = require('fs');
const path = require('path');
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const SHOTS = 'C:/Users/jayde/AppData/Local/Temp/shotkit/shots';
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

  const section = () => p.evaluate(() => ({
    hash: location.hash,
    active: (document.querySelector('#collectionNav .navpill.active') || {}).textContent,
    grid: !document.getElementById('grid').classList.contains('hidden'),
    relics: !document.getElementById('relicView').classList.contains('hidden'),
    mastery: !document.getElementById('view-mastery').classList.contains('hidden'),
    strip: !document.getElementById('tabs').classList.contains('hidden'),
    search: !document.querySelector('.cl-controls').classList.contains('mh'),
    ph: document.getElementById('q').placeholder
  }));

  // ---------------- 1. default: #collection (deep link + default entry)
  await p.goto('http://127.0.0.1:8787/collection.html#collection', { waitUntil: 'load' });
  await sleep(2500);
  out.deepLinkCollection = await section();
  out.tiles = await p.evaluate(() => document.querySelectorAll('#grid .cl-card').length);
  out.rows = await p.evaluate(() => document.querySelectorAll('#relBody tr').length);
  await p.screenshot({ path: path.join(SHOTS, 's6-grid.png') });

  // grid search drops the tile count (search a name that exists in the open category)
  const name = await p.evaluate(() => (document.querySelector('#grid .cl-card .cl-name') || {}).textContent);
  const term = String(name || '').slice(0, 4);
  await p.click('#q');
  await p.type('#q', term);
  await sleep(500);
  out.search = { term, tiles: await p.evaluate(() => document.querySelectorAll('#grid .cl-card').length),
                 meta: await p.evaluate(() => document.getElementById('meta').textContent) };
  // missing-only + buyable toggles still work on top of the search
  await p.click('#missBtn');
  await sleep(400);
  out.missOnly = { tiles: await p.evaluate(() => document.querySelectorAll('#grid .cl-card').length),
                   pressed: await p.evaluate(() => document.getElementById('missBtn').getAttribute('aria-pressed')) };
  await p.click('#missBtn');
  await p.click('#clearBtn');
  await sleep(400);
  out.cleared = await p.evaluate(() => document.querySelectorAll('#grid .cl-card').length);

  // ---------------- 2. Relics: clicked, not typed
  await p.evaluate(() => { const a = document.querySelector('#collectionNav .navpill[data-v="relics"]'); a.focus(); });
  await p.keyboard.press('Enter');                     // keyboard path: focus + Enter follows the link
  await sleep(1600);
  out.relics = await section();
  out.relicsData = await p.evaluate(() => ({
    rows: document.querySelectorAll('#relBody tr').length,
    cols: document.querySelectorAll('#relHead th').length,
    pills: [...document.querySelectorAll('#relPills .cl-relpill')].map((x) => x.textContent.trim()),
    dockRelic: (document.querySelector('#clTip .clt-name') || {}).textContent,
    dockHeader: (document.querySelector('#clTip .clt-state') || {}).textContent,
    docksRows: document.querySelectorAll('#clTip .clt-row').length,
    dockH: Math.round(document.getElementById('clTip').getBoundingClientRect().height),
    sel: document.querySelectorAll('#relBody tr.sel').length
  }));
  await p.screenshot({ path: path.join(SHOTS, 's6-relics.png') });

  // hover row 4 -> the dock follows it, only one row marked
  const tr = await p.$('#relBody tr:nth-child(4)');
  if (tr) { await tr.hover(); await sleep(500); }
  out.dockHover = await p.evaluate(() => ({
    dockRelic: (document.querySelector('#clTip .clt-name') || {}).textContent,
    sel: [...document.querySelectorAll('#relBody tr.sel')].map((r) => r.querySelector('td').textContent)
  }));
  // a pill filter + the section search still drive the table
  await p.evaluate(() => { document.querySelector('#relPills .cl-relpill:nth-child(2)').click(); });
  await sleep(700);
  out.dropFilter = await p.evaluate(() => ({ rows: document.querySelectorAll('#relBody tr').length,
    pills: [...document.querySelectorAll('#relPills .cl-relpill')].map((x) => x.getAttribute('aria-pressed')) }));
  await p.click('#q'); await p.type('#q', 'axi'); await sleep(600);
  out.relicSearch = await p.evaluate(() => ({ rows: document.querySelectorAll('#relBody tr').length,
    meta: document.getElementById('meta').textContent }));
  await p.evaluate(() => { document.getElementById('clearBtn').click();
    document.querySelector('#relPills .cl-relpill:nth-child(1)').click(); });
  await sleep(400);

  // ---------------- 3. Mastery
  await p.evaluate(() => { location.hash = '#mastery'; });
  await sleep(1800);
  out.mastery = await section();
  out.masteryData = await p.evaluate(() => ({
    rows: document.querySelectorAll('#mhNext .mh-row').length,
    cats: document.querySelectorAll('#mhCats .mh-cat').length,
    filters: [...document.querySelectorAll('#mhFilters button')].map((x) => x.textContent.trim()),
    cap: document.getElementById('mhCap').textContent,
    stats: document.getElementById('mhStats').textContent
  }));
  await p.screenshot({ path: path.join(SHOTS, 's6-mastery.png') });

  // ---------------- 4. Cards pill points at its own page
  out.cardsHref = await p.evaluate(() => document.querySelector('#collectionNav .navpill[data-v="cards"]').getAttribute('href'));

  // ---------------- 5. back to the grid: hash + section row agree
  await p.evaluate(() => { location.hash = '#collection'; });
  await sleep(900);
  out.back = await section();

  // ---------------- 6. narrow: the row must stay on one line
  await p.setViewport({ width: 390, height: 844 });
  await sleep(900);
  out.phone = await p.evaluate(() => {
    const nav = document.getElementById('collectionNav');
    const pills = [...nav.querySelectorAll('.navpill')].map((x) => x.getBoundingClientRect());
    const tops = [...new Set(pills.map((r) => Math.round(r.top)))];
    return { lines: tops.length, navH: Math.round(nav.getBoundingClientRect().height),
      docW: document.documentElement.scrollWidth,
      tilesPerRow: (() => { const t = [...document.querySelectorAll('#grid .cl-card')];
        const y = t.length ? Math.round(t[0].getBoundingClientRect().y) : 0;
        return t.filter((x) => Math.round(x.getBoundingClientRect().y) === y).length; })() };
  });

  out.consoleErrors = errors;
  out.ids = await p.evaluate(() => [...document.querySelectorAll('[id]')].map((e) => e.id).sort());
  fs.writeFileSync(path.join('design', '_stage6', 'qa_stage6.json'), JSON.stringify(out, null, 1));
  console.log(JSON.stringify(out, null, 1));
  await b.close();
})();
