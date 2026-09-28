/* Audit-1 flows: Tools launcher round-trip, Mastery tab parity (moved by stage 2), Cards hop.
 *   node design/_audit/qa_flows.js   ->  design/_audit/flows.json
 */
'use strict';
const puppeteer = require('F:/VSC Projects/pb-bench/node_modules/puppeteer-core');
const fs = require('fs');
const path = require('path');
const BASE = 'http://127.0.0.1:8787';
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const sleep = ms => new Promise(r => setTimeout(r, ms));
(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: 'new', args: ['--no-sandbox', '--disable-gpu'] });
  const p = await b.newPage();
  await p.setViewport({ width: 1600, height: 1000 });
  const out = {};
  let errs = [];
  p.on('pageerror', e => errs.push(String(e.message).slice(0, 160)));
  p.on('console', m => { if (m.type() === 'error') errs.push(m.text().slice(0, 160)); });

  /* 1. rail Tools -> launcher -> Deals -> back link -> launcher */
  await p.goto(BASE + '/#home', { waitUntil: 'networkidle2' }); await sleep(400);
  await p.evaluate(() => document.querySelector('#mainnav .navpill[data-v="tools"]').click()); await sleep(400);
  const atLauncher = await p.evaluate(() => ({ hash: location.hash, entries: document.querySelectorAll('#toolsLauncher a.tool').length,
    launcherHidden: document.getElementById('toolsLauncher').classList.contains('hidden') }));
  await p.evaluate(() => document.querySelector('#toolsLauncher a.tool[data-tool="deals"]').click()); await sleep(500);
  const atDeals = await p.evaluate(() => ({ hash: location.hash, rows: document.querySelectorAll('#dealsList div.dealrow:not(.dealhead)').length,
    name: document.querySelector('#toolsWs .tws:not(.hidden) .tws-name').textContent,
    launcherHidden: document.getElementById('toolsLauncher').classList.contains('hidden') }));
  await p.evaluate(() => document.querySelector('#toolsWs .tws:not(.hidden) .tws-back').click()); await sleep(500);
  const backToLauncher = await p.evaluate(() => ({ hash: location.hash, launcherHidden: document.getElementById('toolsLauncher').classList.contains('hidden'),
    entries: document.querySelectorAll('#toolsLauncher a.tool').length }));
  out.tools_roundtrip = { at_launcher: atLauncher, at_deals: atDeals, back: backToLauncher };
  console.log('tools roundtrip:', JSON.stringify(out.tools_roundtrip));

  /* 2. Mastery tab parity (stage 2 moved it): mhStats rows / mhCats pills vs the payload */
  const pay = await p.evaluate(async () => { const r = await fetch('/api/feature/mastery'); const j = await r.json();
    return { keys: Object.keys(j), stats: (j.player && j.player.stats) ? j.player.stats : null, cats: j.categories || null,
      next: j.next || null, cap: j.cap || null }; });
  out.mastery_payload = { keys: pay.keys, statsKeys: pay.stats ? Object.keys(pay.stats).length : null, cats: pay.cats ? (Array.isArray(pay.cats) ? pay.cats.length : Object.keys(pay.cats).length) : null, next: pay.next ? (Array.isArray(pay.next) ? pay.next.length : Object.keys(pay.next).length) : null };
  await p.goto(BASE + '/collection.html#mastery', { waitUntil: 'networkidle2' }); await sleep(1200);
  const mh = await p.evaluate(() => ({ visible: !document.getElementById('view-mastery').classList.contains('hidden'),
    stats: (() => { const s = document.getElementById('mhStats'); return s ? { rows: s.querySelectorAll('.mrow,.srow,.stat,.mhrow,div').length, chars: s.innerText.trim().length, first: s.innerText.trim().split('\n').slice(0, 2).join(' | ') } : null; })(),
    cats: (() => { const c = document.getElementById('mhCats'); return c ? { kids: c.children.length, chars: c.innerText.trim().length, sample: [...c.children].slice(0, 3).map(k => k.innerText.trim().slice(0, 24)) } : null; })(),
    head: (() => { const h = document.getElementById('mhHead'); return h ? h.innerText.trim().slice(0, 80) : null; })(),
    next: (() => { const n = document.getElementById('mhNext'); return n ? n.innerText.trim().length : null; })(),
    filters: document.querySelectorAll('#mhFilters *').length, cap: (() => { const c = document.getElementById('mhCap'); return c ? c.innerText.trim().slice(0, 60) : null; })(),
    active: [...document.querySelectorAll('#mainnav .navpill.active')].map(x => x.dataset.v) }));
  out.mastery_dom = mh;
  console.log('mastery payload:', JSON.stringify(out.mastery_payload));
  console.log('mastery DOM    :', JSON.stringify(mh));

  /* 3. Collection -> Cards pill -> back */
  await p.goto(BASE + '/collection.html', { waitUntil: 'networkidle2' }); await sleep(700);
  await p.evaluate(() => document.querySelector('nav#collectionNav a[data-v="cards"]').click()); await sleep(1200);
  const onCards = await p.evaluate(() => ({ path: location.pathname, active: [...document.querySelectorAll('#mainnav .navpill.active')].map(x => x.dataset.v),
    textLen: document.querySelector('main').innerText.trim().length, cards: document.querySelectorAll('#cardsGrid .mcard, .mcard').length }));
  await p.goBack({ waitUntil: 'networkidle2' }); await sleep(800);
  const backColl = await p.evaluate(() => ({ path: location.pathname, hash: location.hash, active: [...document.querySelectorAll('#mainnav .navpill.active')].map(x => x.dataset.v),
    sub: [...document.querySelectorAll('#collectionNav .navpill')].map(a => a.dataset.v + (a.classList.contains('active') ? '*' : '')), textLen: document.querySelector('main').innerText.trim().length }));
  out.cards_hop = { on_cards: onCards, back: backColl };
  console.log('cards hop:', JSON.stringify(out.cards_hop));
  out.console = errs.slice(0, 10);
  console.log('console errors during flows:', errs.length, errs.slice(0, 5));
  fs.writeFileSync(path.join(__dirname, 'flows.json'), JSON.stringify(out, null, 1));
  console.log('written design/_audit/flows.json');
  await b.close();
})().catch(e => { console.error('PROBE FAILED', e); process.exit(1); });
