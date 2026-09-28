/* Audit-1 extras: (a) chrome is mounted exactly once per page; (b) data-shell-actions matches
 * the header actions actually present; (c) the rendered id union vs stage 1's snapshot
 * (design/_stage1/ids_before.json) - independently, not via the builders' verify_ids.py.
 *   node design/_audit/qa_ids.js   ->  design/_audit/ids.json
 */
'use strict';
const puppeteer = require('F:/VSC Projects/pb-bench/node_modules/puppeteer-core');
const fs = require('fs');
const path = require('path');
const BASE = 'http://127.0.0.1:8787';
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const TARGETS = [
  ['index', '/#home'], ['index#trade', '/#trade'], ['index#inventory', '/#inventory'],
  ['index#tools', '/#tools'], ['index#tools/deals', '/#tools/deals'], ['index#tools/trends', '/#tools/trends'],
  ['index#tools/rivens', '/#tools/rivens'], ['index#tools/wl', '/#tools/wl'], ['index#tools/ducats', '/#tools/ducats'],
  ['index#tools/craft', '/#tools/craft'], ['index#tools/relicev', '/#tools/relicev'], ['index#tools/sets', '/#tools/sets'],
  ['index#tools/baro', '/#tools/baro'], ['index#tools/meta', '/#tools/meta'], ['index#tools/news', '/#tools/news'],
  ['index#tools/player', '/#tools/player'],
  ['collection', '/collection.html'], ['collection#relics', '/collection.html#relics'],
  ['collection#mastery', '/collection.html#mastery'],
  ['cards', '/cards.html'], ['settings', '/settings.html'], ['item', '/item.html'],
];
const sleep = ms => new Promise(r => setTimeout(r, ms));
(async () => {
  const snap = JSON.parse(fs.readFileSync(path.join(__dirname, '..', '_stage1', 'ids_before.json'), 'utf8'));
  const browser = await puppeteer.launch({ executablePath: CHROME, headless: 'new', args: ['--no-sandbox', '--disable-gpu'] });
  const page = await browser.newPage();
  await page.setViewport({ width: 1600, height: 1000 });
  const out = { chrome: {}, declared: {}, union: {}, snapshot_keys: Object.keys(snap) };
  const union = new Set();
  for (const [name, url] of TARGETS) {
    await page.goto(BASE + url, { waitUntil: 'networkidle2' });
    await sleep(600);
    const r = await page.evaluate(() => {
      const ids = new Set([...document.querySelectorAll('[id]')].map(e => e.id));
      const acts = {};
      ['search', 'syncState', 'refresh', 'btnExportPng', 'chips', 'soundBtn', 'themeBtn', 'themePanel', 'themeGrid', 'themeName', 'mainnav'].forEach(i => { acts[i] = !!document.getElementById(i); });
      return { ids: [...ids], headers: document.querySelectorAll('body > header').length,
        rails: document.querySelectorAll('.side').length, mains: document.querySelectorAll('main').length,
        navs: document.querySelectorAll('#mainnav').length, declared: document.body.getAttribute('data-shell'),
        declaredActions: document.body.getAttribute('data-shell-actions'), acts,
        extraMainnavs: [...document.querySelectorAll('nav.mainnav')].map(n => (n.id || '(no id)') + ':' + n.querySelectorAll('.navpill').length) };
    });
    r.ids.forEach(i => union.add(i));
    out.chrome[name] = { headers: r.headers, rails: r.rails, mains: r.mains, mainnavHosts: r.navs, navs: r.extraMainnavs };
    out.declared[name] = { shell: r.declared, actions: r.declaredActions, present: r.acts };
    console.log(`${name.padEnd(22)} header=${r.headers} rail=${r.rails} main=${r.mains} #mainnav=${r.navs} navs=${JSON.stringify(r.extraMainnavs)} shell=${r.declared} actions="${r.declaredActions}" ` +
      `present=${Object.entries(r.acts).filter(([k, v]) => v).map(([k]) => k).join(',')}`);
  }
  out.union.size = union.size;
  const snapIds = new Set();
  Object.values(snap).forEach(v => { (Array.isArray(v) ? v : (v.ids || [])).forEach(i => snapIds.add(i)); });
  const missing = [...snapIds].filter(i => !union.has(i));
  out.snapshot_ids = snapIds.size;
  out.missing_from_dom = missing;
  console.log(`\nid union vs stage-1 snapshot: snapshot=${snapIds.size} rendered=${union.size} missing=${missing.length} ${JSON.stringify(missing.slice(0, 40))}`);
  fs.writeFileSync(path.join(__dirname, 'ids.json'), JSON.stringify(out, null, 1));
  console.log('written design/_audit/ids.json');
  await browser.close();
})().catch(e => { console.error('PROBE FAILED', e); process.exit(1); });
