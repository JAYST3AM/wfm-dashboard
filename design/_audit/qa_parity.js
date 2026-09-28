/* Audit-1 check 1 (DOM side) + check 5 (regression sweep) + check 6 (console/network, index).
 *   node design/_audit/qa_parity.js
 * Opens /#tools/<slug> for every slug, counts the rows each list element actually rendered,
 * and records the workspace heading, visibility and console/network activity.
 * Writes design/_audit/parity_dom.json.
 */
'use strict';
const puppeteer = require('F:/VSC Projects/pb-bench/node_modules/puppeteer-core');
const fs = require('fs');
const path = require('path');

const BASE = 'http://127.0.0.1:8787';
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const OUT = path.join(__dirname, 'parity_dom.json');
const SLUGS = ['deals', 'trends', 'rivens', 'wl', 'ducats', 'craft', 'relicev', 'sets', 'baro',
  'meta', 'news', 'player'];
/* row selector per list id: one element per rendered data row (headers excluded) */
const ROWSEL = {
  dealsList: 'div.dealrow:not(.dealhead)',
  moversList: 'div.mrow', trendsList: 'div.mrow', wlList: 'div.mrow', ducatsList: 'div.mrow',
  nudgesList: 'div.mrow', baroList: 'div.mrow', metaList: 'div.mrow',
  rivensList: 'div.srow:not(.srowhead)', craftList: 'div.srow:not(.srowhead)',
  relicsList: 'div.srow:not(.srowhead)', setsList: 'div.srow:not(.srowhead)',
};
const LISTS = Object.keys(ROWSEL);
/* legacy More-page sweep: 12 list ids + the setup strip / foot */
const LEGACY = { lists: LISTS, setup: ['setupCard', 'foot'] };

(async () => {
  const browser = await puppeteer.launch({
    executablePath: CHROME, headless: 'new',
    args: ['--no-sandbox', '--disable-gpu', '--window-size=1600,1000'],
  });
  const page = await browser.newPage();
  await page.setViewport({ width: 1600, height: 1000 });
  const out = { slugs: {}, legacy: {}, pages: {} };
  let errs = [], failed = [];
  page.on('console', m => {
    if (m.type() === 'error' || m.type() === 'warning') errs.push({ type: m.type(), text: m.text().slice(0, 300) });
  });
  page.on('pageerror', e => errs.push({ type: 'pageerror', text: String(e).slice(0, 300) }));
  page.on('requestfailed', r => failed.push({ url: r.url().slice(0, 200), err: r.failure() && r.failure().errorText }));
  page.on('response', r => { if (r.status() >= 400) failed.push({ url: r.url().slice(0, 200), err: 'HTTP ' + r.status() }); });

  /* --- the workspace matrix ------------------------------------------------------------- */
  for (const slug of SLUGS) {
    errs = []; failed = [];
    await page.goto(BASE + '/#tools/' + slug, { waitUntil: 'networkidle2', timeout: 30000 });
    await page.waitForFunction(`(() => { const w = document.querySelector('#toolsWs [data-tool="${slug}"]'); return w && !w.classList.contains('hidden'); })()`, { timeout: 15000 }).catch(() => {});
    await new Promise(r => setTimeout(r, 700));
    const rec = await page.evaluate((slug, ROWSEL, LISTS) => {
      const ws = document.querySelector('#toolsWs [data-tool="' + slug + '"]');
      const lists = {};
      for (const id of LISTS) {
        const el = document.getElementById(id);
        if (!el) { lists[id] = { present: false }; continue; }
        const sel = ROWSEL[id];
        const rows = el.querySelectorAll(sel).length;
        const firstKids = el.children.length;
        const placeholder = !!el.querySelector('.dim.pad');
        const rect = el.getBoundingClientRect();
        lists[id] = { present: true, rows, first_level_children: firstKids, placeholder,
          text_len: el.innerText.trim().length, h: Math.round(rect.height),
          desc: (el.innerText.trim().split('\n')[0] || '').slice(0, 60) };
      }
      const bar = ws ? ws.querySelector('.tws-bar') : null;
      const heads = ws ? [...ws.querySelectorAll('h1,h2,h3,.tws-name,.card-title')].map(h => h.textContent.trim().slice(0, 50)) : [];
      const launcher = document.getElementById('toolsLauncher');
      const launcherHidden = launcher ? launcher.classList.contains('hidden') : null;
      const wsVisible = {}; const vis = {};
      document.querySelectorAll('#toolsWs .tws').forEach(w => { vis[w.dataset.tool] = !w.classList.contains('hidden'); });
      const viewTools = document.getElementById('view-tools');
      const activePills = [...document.querySelectorAll('#mainnav .navpill.active')].map(p => p.dataset.v);
      const aria = [...document.querySelectorAll('#mainnav .navpill[aria-current]')].map(p => p.dataset.v);
      return { slug, lists, bar: !!bar, barName: bar ? (bar.querySelector('.tws-name') || {}).textContent : null,
        heads, launcherHidden, wsVisible: vis, activePills, ariaCurrent: aria,
        viewToolsVisible: viewTools ? !viewTools.classList.contains('hidden') : null,
        hash: location.hash, backLink: bar ? !!bar.querySelector('a.tws-back') : false };
    }, slug, ROWSEL, LISTS);
    /* player workspace: count the pc* hooks that rendered */
    if (slug === 'player') {
      rec.pc = await page.evaluate(() => {
        const ids = ['pcCard', 'pcMeta', 'pcStats', 'pcSyndicates', 'pcFocus', 'pcMarket', 'pcClan'];
        const o = {};
        document.querySelectorAll('#toolsWs [data-tool="player"] [id^="pc"]').forEach(el => { o[el.id] = { text_len: el.innerText.trim().length, kids: el.children.length }; });
        return o;
      });
    }
    rec.console = errs.slice(0, 12); rec.failed = failed.slice(0, 12);
    out.slugs[slug] = rec;
    console.log(`${slug.padEnd(8)} launcherHidden=${rec.launcherHidden} bar=${rec.bar} name=${rec.barName} ` +
      `active=${rec.activePills} aria=${rec.ariaCurrent} errs=${errs.length} failed=${failed.length} ` +
      LISTS.map(id => `${id}:${rec.lists[id] && rec.lists[id].present ? rec.lists[id].rows + (rec.lists[id].placeholder ? 'P' : '') : 'MISSING'}`).join(' '));
  }

  /* --- the legacy More-page sweep: every one of the 12 lists is in the DOM with data ----- */
  errs = []; failed = [];
  await page.goto(BASE + '/#tools', { waitUntil: 'networkidle2' });
  await new Promise(r => setTimeout(r, 700));
  const sweep = await page.evaluate((LEGACY, ROWSEL) => {
    const res = { lists: {}, setup: {}, launcherEntries: document.querySelectorAll('#toolsLauncher a.tool').length };
    for (const id of LEGACY.lists) {
      const el = document.getElementById(id);
      res.lists[id] = el ? { present: true, rows: el.querySelectorAll(ROWSEL[id]).length,
        total_chars: el.innerText.trim().length } : { present: false };
    }
    for (const id of LEGACY.setup) {
      const el = document.getElementById(id);
      res.setup[id] = el ? { present: true, chars: el.innerText.trim().length } : { present: false };
    }
    return res;
  }, LEGACY, ROWSEL);
  out.legacy = sweep;
  out.legacy_console = errs.slice(0, 12); out.legacy_failed = failed.slice(0, 12);
  console.log('legacy sweep:', JSON.stringify(sweep.lists));
  console.log('legacy setup:', JSON.stringify(sweep.setup), 'launcher entries:', sweep.launcherEntries);

  fs.writeFileSync(OUT, JSON.stringify(out, null, 1));
  console.log('written', OUT);
  await browser.close();
})().catch(e => { console.error('PROBE FAILED', e); process.exit(1); });
