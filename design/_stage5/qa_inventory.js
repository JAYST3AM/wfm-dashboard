/* Stage 5 QA: Inventory is basic info only (Items | Materials, one Columns disclosure, the
 * changes behind their own disclosure, the item drawer still opening from a row) and the Clan
 * Dojo card is now the Tools workspace #tools/dojo - measured headlessly.
 *
 *   node design/_stage5/qa_inventory.js
 *
 * Read-only: every click is a navigation or a disclosure toggle. Nothing on the page writes.
 * Writes C:/Users/jayde/AppData/Local/Temp/shotkit/shots/s5-*.png and design/_stage5/qa_inventory.json,
 * then prints the numbers the stage is judged on:
 *
 *   (a) click-through  - Items/Materials switch, the Columns disclosure open/close, the drawer
 *                        from a row, the Materials search + sort, and #tools/dojo rendering;
 *   (b) parity         - item rows vs /api/items, material rows vs data/materials.json,
 *                        dojo research rows vs the dojo payload (expected vs rendered printed);
 *   (c) fit            - pageOverX/Y + the view's own ovfX on home/trade/inventory/tools at
 *                        1920x1080, 1536x864, 1366x768 and 1280x800;
 *   (d) shots          - s5-inventory-items.png, s5-inventory-materials.png,
 *                        s5-inventory-disclosure.png, s5-tools-dojo.png;
 *   (e) console errors - 0, with the pre-existing WFCD CDN request failures excluded.
 */
'use strict';
const puppeteer = require('F:/VSC Projects/pb-bench/node_modules/puppeteer-core');
const fs = require('fs');
const http = require('http');
const path = require('path');

const BASE = 'http://127.0.0.1:8787';
const SHOTS = 'C:/Users/jayde/AppData/Local/Temp/shotkit/shots';
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const REPO = path.join(__dirname, '..', '..');
/* card art comes from the WFCD image CDN, which is blocked on this PC - pre-existing, not this
   stage's business (the stage 1 and 2 runs reported the same single failure). */
const PREEXISTING = /cdn\.warframestat\.us|api\.warframe\.market|wfcd/i;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const report = { errors: [], clicks: {}, parity: {}, fit: {}, shots: {} };
const t = (b) => (b ? 'PASS' : 'FAIL');
let failures = 0;
function check(label, ok, detail) {
  if (!ok) failures++;
  console.log([t(ok), label, detail === undefined ? '' : detail].join(' ').trim());
  return ok;
}

function getJson(url) {
  return new Promise((resolve, reject) => {
    http.get(url, (res) => {
      let b = '';
      res.on('data', (c) => { b += c; });
      res.on('end', () => { try { resolve(JSON.parse(b)); } catch (e) { reject(e); } });
    }).on('error', reject);
  });
}

(async () => {
  const API_ITEMS = await getJson(BASE + '/api/items');
  const API_MATS = await getJson(BASE + '/api/feature/materials');
  const FILE_MATS = JSON.parse(fs.readFileSync(path.join(REPO, 'data', 'materials.json'), 'utf8'));
  const FILE_DOJO = JSON.parse(fs.readFileSync(path.join(REPO, 'data', 'dojo_costs.json'), 'utf8'));

  const browser = await puppeteer.launch({
    executablePath: CHROME, headless: 'new',
    args: ['--no-sandbox', '--disable-dev-shm-usage', '--window-size=1920,1080'],
  });
  const page = await browser.newPage();
  const errs = [];
  page.on('console', (m) => { if (m.type() === 'error') errs.push('console: ' + m.text()); });
  page.on('pageerror', (e) => errs.push('pageerror: ' + String(e.message || e)));
  page.on('requestfailed', (r) => {
    const u = r.url();
    if (!PREEXISTING.test(u)) errs.push('reqfail: ' + u + ' ' + (r.failure() || {}).errorText);
  });
  await page.setViewport({ width: 1920, height: 1080 });
  await page.goto(BASE + '/', { waitUntil: 'load', timeout: 30000 });
  await sleep(2500);                       /* the feature fan-out + the first render */

  /* ---------------- (a) click-through ---------------- */
  const goInv = () => page.evaluate(() => document.querySelector('#mainnav .navpill[data-v="inventory"]').click());
  const go = (hash) => page.evaluate((h) => { location.hash = h; }, hash);
  const state = () => page.evaluate(() => {
    const vis = (el) => !!el && getComputedStyle(el).display !== 'none' && !el.classList.contains('hidden');
    const ths = [...document.querySelectorAll('#tbl thead th')];
    const row = document.querySelector('#tbl tbody tr.inv-row');
    const adv = document.getElementById('invAdv');
    return {
      hash: location.hash,
      invTabs: [...document.querySelectorAll('#invViews [role="tab"]')].map((b) => [b.dataset.v, b.getAttribute('aria-selected'), b.classList.contains('active')]),
      itemsVis: vis(document.getElementById('invItems')),
      matsVis: vis(document.getElementById('invMaterials')),
      /* the REAL check: an id rule can outrank .hidden, so read computed display, not the class */
      itemsDisp: document.getElementById('invItems') ? getComputedStyle(document.getElementById('invItems')).display : null,
      matsDisp: document.getElementById('invMaterials') ? getComputedStyle(document.getElementById('invMaterials')).display : null,
      itemsHid: document.getElementById('invItems') ? document.getElementById('invItems').classList.contains('hidden') : null,
      matsHid: document.getElementById('invMaterials') ? document.getElementById('invMaterials').classList.contains('hidden') : null,
      matEmpty: (document.querySelector('#matRows .mat-empty') || {}).textContent || '',
      itemRows: document.querySelectorAll('#rows tr.inv-row').length,
      totals: (document.getElementById('totals') || {}).textContent || '',
      thVisible: ths.filter((th) => getComputedStyle(th).display !== 'none').length,
      thTotal: ths.length,
      tdVisible: row ? [...row.children].filter((td) => getComputedStyle(td).display !== 'none').length : null,
      tdTotal: row ? row.children.length : null,
      showA: document.body.classList.contains('show-a'),
      advOpen: !!(adv && adv.open),
      btnCols: (document.getElementById('btnCols') || {}).textContent || '',
      btnPressed: (document.getElementById('btnCols') || {}).getAttribute ? document.getElementById('btnCols').getAttribute('aria-pressed') : null,
      diffOpen: !!(document.getElementById('invDiff') || {}).open,
      diffMeta: (document.getElementById('diffMeta') || {}).textContent || '',
      diffRows: document.querySelectorAll('#diffList > *').length,
      matRows: document.querySelectorAll('#matRows tr.mat-row').length,
      matMeta: (document.getElementById('matMeta') || {}).textContent || '',
      matFirst: [...document.querySelectorAll('#matRows tr.mat-row .name')].slice(0, 3).map((x) => x.textContent.trim()),
      matSort: (document.getElementById('matSort') || {}).textContent || '',
      matView: [...document.querySelectorAll('#matView button')].map((b) => [b.dataset.m, b.getAttribute('aria-pressed')]),
      drawerOpen: typeof window.wfmOpenItem === 'function' && window.wfmOpenItem.isOpen(),
      drawerDom: !!document.querySelector('.dw-root') && !document.querySelector('.dw-root').classList.contains('dw-hidden'),
      scr: (() => { const el = document.querySelector('#invItems > .tablewrap');
        return el ? { h: el.scrollHeight, c: el.clientHeight, scrolly: el.classList.contains('scrolly') } : null; })(),
    };
  });

  await goInv();
  await sleep(600);
  let s = await state();
  check('items is the landing subview', s.itemsVis && !s.matsVis && s.itemsDisp === 'flex' && s.matsDisp === 'none' && s.matsHid
        && s.invTabs[0][0] === 'items' && s.invTabs[0][1] === 'true',
        `items=${s.itemsDisp} materials=${s.matsDisp} tabs=${JSON.stringify(s.invTabs)}`);
  check('advanced columns hidden by default', !s.showA && s.thVisible === 4 && s.tdVisible === 4 && !s.advOpen,
        `th ${s.thVisible}/${s.thTotal} td ${s.tdVisible}/${s.tdTotal} show-a=${s.showA}`);
  report.clicks.itemsDefault = { ...s };
  await page.screenshot({ path: path.join(SHOTS, 's5-inventory-items.png') });
  report.shots['s5-inventory-items.png'] = s.thVisible;

  /* the Columns disclosure: open, switch the advanced columns on, shot, then close both ways */
  await page.evaluate(() => document.querySelector('#invAdv summary').click());
  await sleep(200);
  await page.evaluate(() => document.getElementById('btnCols').click());
  await sleep(250);
  s = await state();
  check('the Columns disclosure opens and shows the advanced columns', s.advOpen && s.showA && s.thVisible === 14 && s.tdVisible === 14 && s.btnPressed === 'true',
        `th ${s.thVisible}/14 td ${s.tdVisible}/14 "${s.btnCols}" pressed=${s.btnPressed}`);
  report.clicks.disclosureOpen = { ...s };
  await page.screenshot({ path: path.join(SHOTS, 's5-inventory-disclosure.png') });
  report.shots['s5-inventory-disclosure.png'] = s.thVisible;

  await page.evaluate(() => document.getElementById('btnCols').click());
  await sleep(150);
  await page.evaluate(() => document.querySelector('#invAdv summary').click());
  await sleep(200);
  s = await state();
  check('the disclosure closes both ways', !s.advOpen && !s.showA && s.thVisible === 4,
        `open=${s.advOpen} show-a=${s.showA} th=${s.thVisible}`);

  /* the changes strip: its own disclosure, closed by default, opening in place */
  await page.evaluate(() => document.querySelector('#invDiff summary').click());
  await sleep(250);
  s = await state();
  const diffOk = check('inventory changes open behind their own disclosure', s.diffOpen,
                       `rows=${s.diffRows} meta="${s.diffMeta}"`);
  if (diffOk) report.clicks.diff = { rows: s.diffRows, meta: s.diffMeta };
  await page.evaluate(() => document.querySelector('#invDiff summary').click());
  await sleep(150);

  /* the drawer still opens from a row, and closes again */
  const rowCount = await page.evaluate(() => document.querySelectorAll('#rows tr.inv-row').length);
  if (rowCount > 0) {
    await page.evaluate(() => document.querySelector('#rows tr.inv-row').click());
    await sleep(900);
    s = await state();
    check('the item drawer opens from a row', s.drawerOpen && s.drawerDom, `isOpen=${s.drawerOpen} dom=${s.drawerDom} rows=${rowCount}`);
    await page.evaluate(() => window.wfmOpenItem.close());
    await sleep(400);
  } else {
    check('the item drawer opens from a row', false, 'no rows rendered - /api/items is empty');
  }

  /* Materials: the switch, then the search and the sort toggle inside that subview */
  await page.evaluate(() => document.querySelector('#invViews [role="tab"][data-v="materials"]').click());
  await sleep(500);
  s = await state();
  check('the Materials subview switches in', s.matsVis && !s.itemsVis && s.matsDisp !== 'none' && s.itemsDisp === 'none' && s.itemsHid
        && s.invTabs[1][1] === 'true',
        `items=${s.itemsDisp} materials=${s.matsDisp} matRows=${s.matRows} meta="${s.matMeta}"`);
  report.clicks.materials = { rows: s.matRows, meta: s.matMeta, sort: s.matSort };
  await page.screenshot({ path: path.join(SHOTS, 's5-inventory-materials.png') });
  report.shots['s5-inventory-materials.png'] = s.matRows;

  const sortBefore = s.matSort, firstBefore = s.matFirst.join(' | ');
  if (s.matRows > 0) {
    await page.evaluate(() => document.getElementById('matSort').click());
    await sleep(350);
    s = await state();
    check('the Materials sort toggle re-orders the rows', s.matSort !== sortBefore && s.matFirst.join() !== firstBefore,
          `"${sortBefore}" -> "${s.matSort}" :: ${firstBefore} -> ${s.matFirst.join(' | ')}`);
    await page.evaluate(() => document.getElementById('matSort').click());   /* back to Count */
    await sleep(200);

    const probe = firstBefore.split(' | ')[0].split(' ')[0].slice(0, 4);
    await page.evaluate((q) => { const el = document.getElementById('matQ'); el.value = q; el.dispatchEvent(new Event('input', { bubbles: true })); }, probe);
    await sleep(400);
    s = await state();
    const filtered = await page.evaluate(() => [...document.querySelectorAll('#matRows tr.mat-row .name')].map((x) => x.textContent.trim()));
    check('the Materials search filters in place', s.matRows > 0 && filtered.every((n) => n.toLowerCase().includes(probe.toLowerCase())),
          `${s.matRows} rows match "${probe}"`);
    await page.evaluate(() => { const el = document.getElementById('matQ'); el.value = ''; el.dispatchEvent(new Event('input', { bubbles: true })); });
    await sleep(300);
    s = await state();
    report.clicks.materialsFiltered = { rows: s.matRows };
  } else {
    /* the live store has no material rows to sort or filter (data/materials.json is an empty
       skeleton right now) - the panel must still be usable and say so */
    const mk = s.matSort;
    await page.evaluate(() => document.getElementById('matSort').click());
    await sleep(300);
    s = await state();
    check('the Materials sort control stays live on an empty store', s.matSort !== mk && s.matRows === 0 && /No material data/.test(s.matEmpty),
          `"${mk}" -> "${s.matSort}" empty="${s.matEmpty}"`);
    await page.evaluate(() => document.getElementById('matSort').click());
    await sleep(150);
    const q = await page.evaluate(() => { const el = document.getElementById('matQ'); el.value = 'alloy'; el.dispatchEvent(new Event('input', { bubbles: true })); return el.value; });
    await sleep(300);
    s = await state();
    check('the Materials search stays live on an empty store', s.matRows === 0 && /No material data/.test(s.matEmpty),
          `query="${q}" empty="${s.matEmpty}"`);
    await page.evaluate(() => { const el = document.getElementById('matQ'); el.value = ''; el.dispatchEvent(new Event('input', { bubbles: true })); });
    await sleep(250);
    report.clicks.materialsEmptyStore = { sort: s.matSort, empty: s.matEmpty, note: 'data/materials.json has 0 rows' };
  }

  /* Items | Materials round trip, then the hash deep link (#inventory/materials) */
  await page.evaluate(() => document.querySelector('#invViews [role="tab"][data-v="items"]').click());
  await sleep(300);
  s = await state();
  check('the subview switch round-trips', s.itemsVis && !s.matsVis, `itemRows=${s.itemRows}`);

  /* below the fit threshold (1200px) the panels are plain blocks - the swap must still hide one */
  await page.setViewport({ width: 1100, height: 900 });
  await sleep(500);
  await page.evaluate(() => document.querySelector('#mainnav .navpill[data-v="inventory"]').click());
  await sleep(300);
  s = await state();
  const nonFitItems = { items: s.itemsDisp, mats: s.matsDisp };
  await page.evaluate(() => document.querySelector('#invViews [role="tab"][data-v="materials"]').click());
  await sleep(350);
  s = await state();
  check('below the fit threshold the swap still hides the other panel',
        nonFitItems.items !== 'none' && nonFitItems.mats === 'none' && s.itemsDisp === 'none' && s.matsDisp !== 'none',
        `1100px items-first ${nonFitItems.items}/${nonFitItems.mats} mats-first ${s.itemsDisp}/${s.matsDisp}`);
  report.clicks.nonFit = { itemsFirst: nonFitItems, matsFirst: { items: s.itemsDisp, mats: s.matsDisp } };
  await page.evaluate(() => document.querySelector('#invViews [role="tab"][data-v="items"]').click());
  await page.setViewport({ width: 1920, height: 1080 });
  await sleep(400);
  /* the hash deep link, from a cold load with no remembered choice (the query string forces a
     real document load - a same-document hash change would keep the previous state) */
  await page.evaluate(() => localStorage.removeItem('wfm.invView'));
  await page.goto(BASE + '/?s5=mat#inventory/materials', { waitUntil: 'load' });
  await sleep(2200);
  s = await state();
  check('#inventory/materials deep-links the second subview', s.matsVis && !s.itemsVis && s.invTabs[1][1] === 'true', 'hash=' + s.hash);
  await page.evaluate(() => localStorage.removeItem('wfm.invView'));
  await page.goto(BASE + '/?s5=bare#inventory', { waitUntil: 'load' });
  await sleep(2200);
  s = await state();
  check('#inventory alone lands on Items', s.itemsVis && !s.matsVis, `hash=${s.hash} tabs=${JSON.stringify(s.invTabs)}`);
  await goInv();
  await sleep(300);

  /* ---------------- the dojo at #tools/dojo ---------------- */
  const launcher = await page.evaluate(() => {
    const ent = document.querySelector('#toolsLauncher a.tool[data-tool="dojo"]');
    const grp = [...document.querySelectorAll('#toolsLauncher .tl-group')].find((g) => /Warframe/.test(g.textContent));
    return { href: ent && ent.getAttribute('href'), inWarframe: !!(ent && grp && grp.contains(ent)),
             count: document.querySelectorAll('#toolsLauncher a.tool').length };
  });
  check('the launcher entry sits in the Warframe group', launcher.href === '#tools/dojo' && launcher.inWarframe, JSON.stringify(launcher));

  await page.evaluate(() => document.querySelector('#toolsLauncher a.tool[data-tool="dojo"]').click());
  await sleep(1200);
  const dojo = await page.evaluate(() => {
    const ws = document.getElementById('tws-dojo');
    const rooms = document.getElementById('dojoRooms');
    return {
      hash: location.hash,
      wsVis: !!ws && !ws.classList.contains('hidden') && getComputedStyle(ws).display !== 'none',
      wsOthers: [...document.querySelectorAll('#toolsWs .tws')].filter((e) => !e.classList.contains('hidden')).map((e) => e.dataset.tool),
      launcherHidden: document.getElementById('toolsLauncher').classList.contains('hidden'),
      title: (document.getElementById('dojoTitle') || {}).textContent || '',
      meta: (document.getElementById('dojoMeta') || {}).textContent || '',
      rows: document.querySelectorAll('#dojoRows tr.dojo-row').length,
      tier: [...document.querySelectorAll('#dojoTier button')].map((b) => [b.dataset.t, b.getAttribute('aria-pressed')]),
      roomsVis: !!rooms && !rooms.classList.contains('hidden') && rooms.open !== false,
      roomsMeta: (document.getElementById('dojoRoomsMeta') || {}).textContent || '',
      roomsList: document.querySelectorAll('#dojoRoomsList .mrow').length,
      src: (document.getElementById('dojoSrc') || {}).textContent || '',
      scrolly: (() => { const el = document.querySelector('#tws-dojo .tablewrap'); return el ? el.scrollHeight > el.clientHeight + 2 : null; })(),
    };
  });
  check('clicking the launcher entry renders the dojo workspace', dojo.hash === '#tools/dojo' && dojo.wsVis && dojo.launcherHidden,
        `hash=${dojo.hash} rows=${dojo.rows} rooms=${dojo.roomsList} others-visible=${JSON.stringify(dojo.wsOthers)}`);
  check('the dojo table and the rooms breakdown both render', dojo.rows > 0 && dojo.roomsList > 0,
        `${dojo.rows} research rows, ${dojo.roomsList} rooms, meta "${dojo.meta}", rooms meta "${dojo.roomsMeta}"`);
  await page.screenshot({ path: path.join(SHOTS, 's5-tools-dojo.png') });
  report.shots['s5-tools-dojo.png'] = dojo.rows;

  /* a direct hash load of the workspace (no launcher click), via a real document load */
  await page.goto(BASE + '/?s5=dojo#tools/dojo', { waitUntil: 'load' });
  await sleep(2200);
  const dojo2 = await page.evaluate(() => ({
    hash: location.hash,
    wsVis: !!document.getElementById('tws-dojo') && !document.getElementById('tws-dojo').classList.contains('hidden'),
    rows: document.querySelectorAll('#dojoRows tr.dojo-row').length,
    rooms: document.querySelectorAll('#dojoRoomsList .mrow').length,
  }));
  check('#tools/dojo renders on a cold load too', dojo2.wsVis && dojo2.rows > 0 && dojo2.rooms > 0, JSON.stringify(dojo2));
  report.clicks.dojo = { ...dojo, cold: dojo2 };

  /* ---------------- (b) parity ---------------- */
  await goInv();
  await sleep(500);
  const itemsPage = await page.evaluate(() => ({
    rows: document.querySelectorAll('#rows tr.inv-row').length,
    totals: (document.getElementById('totals') || {}).textContent.replace(/\s+/g, ' ').trim(),
    totalRows: [...document.querySelectorAll('#tbl thead th')].length,
    colspan: (document.querySelector('#tbl thead th') || {}).getAttribute ? null : null,
  }));
  const stacks = /^(\d+) stacks \(showing (\d+)\)/.exec(itemsPage.totals) || [];
  const expItems = Array.isArray(API_ITEMS) ? API_ITEMS.length : (API_ITEMS.rows || []).length;
  const renItems = itemsPage.rows;
  check('PARITY items: rendered rows vs /api/items', renItems === Math.min(expItems, 400) && Number(stacks[2]) === renItems,
        `expected=${expItems} rendered=${renItems} totals="${itemsPage.totals}"`);
  report.parity.items = { expected: expItems, rendered: renItems, totals: itemsPage.totals };

  await page.evaluate(() => document.querySelector('#invViews [role="tab"][data-v="materials"]').click());
  await sleep(500);
  const matsPage = await page.evaluate(() => ({
    rows: document.querySelectorAll('#matRows tr.mat-row').length,
    meta: (document.getElementById('matMeta') || {}).textContent.trim(),
  }));
  const fileMats = (FILE_MATS.materials || []).filter((r) => r && r.slug).length;
  const dedupFileMats = new Set((FILE_MATS.materials || []).filter((r) => r && r.slug).map((r) => String(r.slug))).size;
  check('PARITY materials: rendered rows vs data/materials.json', matsPage.rows === Math.min(API_MATS.count, 400) && API_MATS.count === dedupFileMats,
        `file=${fileMats} distinct=${dedupFileMats} api.count=${API_MATS.count} rendered=${matsPage.rows} meta="${matsPage.meta}"`);
  report.parity.materials = { fileEntries: fileMats, distinct: dedupFileMats, apiCount: API_MATS.count,
                              rendered: matsPage.rows, meta: matsPage.meta };

  const tier = 'ghost';
  const expResearch = (((API_MATS.dojo || {}).tier_totals || {})[tier] || {}).materials || [];
  const fileResearch = Object.keys((((FILE_DOJO.tier_totals || {})[tier] || {}).materials) || {}).length;
  const expRooms = ((API_MATS.dojo || {}).rooms || []).length;
  await page.evaluate(() => document.querySelector('#mainnav .navpill[data-v="tools"]').click());
  await sleep(300);
  await page.evaluate(() => document.querySelector('#toolsLauncher a.tool[data-tool="dojo"]').click());
  await sleep(900);
  const dojoRows = await page.evaluate(() => ({
    rows: document.querySelectorAll('#dojoRows tr.dojo-row').length,
    rooms: document.querySelectorAll('#dojoRoomsList .mrow').length,
    tier: (document.querySelector('#dojoTier button[aria-pressed="true"]') || {}).dataset
      ? document.querySelector('#dojoTier button[aria-pressed="true"]').dataset.t : null,
  }));
  check('PARITY dojo: research rows vs the payload tier', dojoRows.rows === expResearch.length && dojoRows.tier === tier,
        `tier=${dojoRows.tier} expected=${expResearch.length} rendered=${dojoRows.rows} file(tier_totals.${tier})=${fileResearch}`);
  check('PARITY dojo: rooms vs the payload', dojoRows.rooms === expRooms,
        `expected=${expRooms} rendered=${dojoRows.rooms}`);
  report.parity.dojo = { tier: dojoRows.tier, research: { expected: expResearch.length, rendered: dojoRows.rows, fileTierTotal: fileResearch },
                         rooms: { expected: expRooms, rendered: dojoRows.rooms } };

  /* ---------------- (c) fit ---------------- */
  const VP = [[1920, 1080], [1536, 864], [1440, 900], [1366, 768], [1280, 800]];
  for (const [w, h] of VP) {
    const key = w + 'x' + h;
    report.fit[key] = {};
    await page.setViewport({ width: w, height: h });
    await sleep(350);
    for (const v of ['home', 'trade', 'inventory', 'tools']) {
      await page.evaluate((v) => document.querySelector('#mainnav .navpill[data-v="' + v + '"]').click(), v);
      await sleep(450);
      report.fit[key][v] = await page.evaluate(() => {
        const de = document.documentElement;
        const sec = document.querySelector('main > section:not(.hidden)');
        return {
          pageOverX: Math.max(de.scrollWidth - de.clientWidth, document.body.scrollWidth - window.innerWidth),
          pageOverY: Math.max(de.scrollHeight - de.clientHeight, document.body.scrollHeight - window.innerHeight),
          ovfX: sec ? Math.max(0, sec.scrollWidth - sec.clientWidth) : null,
        };
      });
    }
    /* the two inventory subviews, and the dojo workspace, at the same width */
    await page.evaluate(() => document.querySelector('#mainnav .navpill[data-v="inventory"]').click());
    await sleep(300);
    report.fit[key]['inventory/materials'] = await page.evaluate(() => {
      document.querySelector('#invViews [role="tab"][data-v="materials"]').click();
      return null;
    }).then(() => sleep(400)).then(() => page.evaluate(() => {
      const de = document.documentElement;
      const sec = document.querySelector('main > section:not(.hidden)');
      return { pageOverX: Math.max(de.scrollWidth - de.clientWidth, document.body.scrollWidth - window.innerWidth),
               pageOverY: Math.max(de.scrollHeight - de.clientHeight, document.body.scrollHeight - window.innerHeight),
               ovfX: sec ? Math.max(0, sec.scrollWidth - sec.clientWidth) : null };
    }));
    await page.evaluate(() => document.querySelector('#invViews [role="tab"][data-v="items"]').click());
    report.fit[key]['tools/dojo'] = await page.evaluate(() => {
      location.hash = '#tools/dojo';
      return null;
    }).then(() => sleep(700)).then(() => page.evaluate(() => {
      const de = document.documentElement;
      const sec = document.querySelector('main > section:not(.hidden)');
      return { pageOverX: Math.max(de.scrollWidth - de.clientWidth, document.body.scrollWidth - window.innerWidth),
               pageOverY: Math.max(de.scrollHeight - de.clientHeight, document.body.scrollHeight - window.innerHeight),
               ovfX: sec ? Math.max(0, sec.scrollWidth - sec.clientWidth) : null };
    }));
  }
  for (const [key, views] of Object.entries(report.fit)) {
    const line = Object.entries(views).map(([v, m]) => `${v}:${m.pageOverX}/${m.pageOverY}/${m.ovfX}`).join(' ');
    const core = ['home', 'trade', 'inventory', 'tools'].map((v) => views[v]);
    check('FIT ' + key + ' pageOverX/Y + ovfX 0 (x/y/ovf)', core.every((m) => m.pageOverX === 0 && m.pageOverY === 0 && m.ovfX === 0), line);
  }

  /* ---------------- (e) console errors ---------------- */
  report.errors = errs;
  check('0 console errors / failed requests', errs.length === 0, errs.slice(0, 6).join(' | '));

  await browser.close();
  fs.writeFileSync(path.join(__dirname, 'qa_inventory.json'), JSON.stringify(report, null, 2));
  console.log(failures === 0 ? 'ALL CHECKS PASSED' : failures + ' CHECK(S) FAILED');
  process.exit(failures === 0 ? 0 : 1);
})().catch((e) => { console.error('QA CRASH', e); process.exit(2); });
