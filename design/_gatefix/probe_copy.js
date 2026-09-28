/* design/_gatefix/probe_copy.js — run the gate's own COPY_SCAN over the same page states (fast
   pre-check before the full 4-minute harness). Read-only: navigation + hash changes only. */
'use strict';
const puppeteer = require('F:/VSC Projects/pb-bench/node_modules/puppeteer-core');
const BASE = process.env.WFM_BASE || 'http://127.0.0.1:8787';
const CHROME = process.env.WFM_CHROME || 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const SCAN = `(() => {
  const out = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null);
  let node;
  while ((node = walker.nextNode())) {
    const raw = String(node.data || '').replace(/\\s+/g, ' ').trim();
    if (!raw || !/[a-z]/i.test(raw)) continue;
    const el = node.parentElement; if (!el) continue;
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') continue;
    const r = el.getBoundingClientRect();
    if (!(r.width > 0 && r.height > 0)) continue;
    const words = raw.split(' ').filter(Boolean).length;
    if (words > 8 || raw.length > 90) out.push({ text: raw.slice(0, 180), words, chars: raw.length, cls: String(el.className || '').slice(0, 40) });
  }
  return out;
})()`;
(async () => {
  const browser = await puppeteer.launch({ executablePath: CHROME, headless: 'new', args: ['--no-sandbox', '--disable-dev-shm-usage'] });
  const page = await browser.newPage();
  await page.setViewport({ width: 1920, height: 1080 });
  const errs = [];
  page.on('pageerror', (e) => errs.push(String(e.message)));
  const seen = new Set(), all = [];
  const take = async (label) => {
    const rows = await page.evaluate(SCAN);
    rows.forEach((r) => { const k = label.replace(/\/.*$/, '') + '|' + r.text; if (seen.has(k)) return; seen.add(k); all.push({ label, ...r }); });
  };
  await page.goto(BASE + '/', { waitUntil: 'load' });
  await sleep(3000);
  await take('index/landing #home');
  for (const v of ['inventory', 'trade', 'tools']) { await page.evaluate((x) => { location.hash = '#' + x; }, v); await sleep(900); await take('index/#' + v); }
  for (const w of ['deals', 'trends', 'rivens', 'wl', 'ducats', 'craft', 'relicev', 'sets', 'baro', 'meta', 'news', 'player']) {
    await page.evaluate((x) => { location.hash = '#tools/' + x; }, w); await sleep(900); await take('index/#tools/' + w);
  }
  await page.goto(BASE + '/collection.html', { waitUntil: 'load' }); await sleep(3500); await take('collection/collection');
  for (const s of ['relics', 'mastery']) { await page.evaluate((x) => { location.hash = '#' + x; }, s); await sleep(2500); await take('collection/' + s); }
  await page.goto(BASE + '/settings.html', { waitUntil: 'load' }); await sleep(2500);
  for (const c of ['general', 'trading', 'appearance', 'accounts', 'notifications', 'advanced']) {
    await page.evaluate((x) => { location.hash = '#' + x; }, c); await sleep(700); await take('settings/' + c);
  }
  await page.goto(BASE + '/item.html?item=primed_continuity', { waitUntil: 'load' }); await sleep(3000); await take('item/deeplink');
  await page.goto(BASE + '/lookup.html', { waitUntil: 'load' }); await sleep(3000); await take('lookup/landing');
  console.log('offenders: ' + all.length);
  all.forEach((r) => console.log('  ' + r.label + ' [' + r.words + 'w ' + r.chars + 'c] cls=' + r.cls + ' :: ' + r.text));
  console.log('pageerrors: ' + JSON.stringify(errs.slice(0, 6)));
  await browser.close();
})().catch((e) => { console.error('PROBE FAILED: ' + e.stack); process.exit(1); });
