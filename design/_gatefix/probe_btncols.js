/* design/_gatefix/probe_btncols.js — why does index/inventory Frost Light flag #btnCols?
   Read-only: loads the app, switches theme in the gate's own order/timings, prints the
   element's computed background and its ancestor chain at scan time, then re-reads after 3s. */
'use strict';
const puppeteer = require('F:/VSC Projects/pb-bench/node_modules/puppeteer-core');
const BASE = process.env.WFM_BASE || 'http://127.0.0.1:8787';
const CHROME = process.env.WFM_CHROME || 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const DUMP = `(() => {
  const el = document.getElementById('btnCols');
  if (!el) return { missing: true };
  const rows = [];
  for (let n = el; n; n = n.parentElement) {
    const cs = getComputedStyle(n);
    rows.push({ tag: n.tagName.toLowerCase(), id: n.id || '', cls: String(n.className || '').slice(0, 40),
      bg: cs.backgroundColor, img: cs.backgroundImage.slice(0, 40), color: cs.color,
      tr: cs.transitionProperty + ' ' + cs.transitionDuration + ' ' + cs.transitionDelay });
    if (n.tagName === 'BODY') break;
  }
  return { rows, rect: (() => { const r = el.getBoundingClientRect(); return [r.x|0, r.y|0, r.width|0, r.height|0]; })() };
})()`;

(async () => {
  const browser = await puppeteer.launch({ executablePath: CHROME, headless: 'new',
    args: ['--no-sandbox', '--disable-dev-shm-usage'] });
  const page = await browser.newPage();
  await page.setViewport({ width: 1920, height: 1080 });
  for (const ti of [0, 2, 14, 28]) {
    await page.goto(BASE + '/', { waitUntil: 'load' });
    await sleep(2200);
    await page.evaluate((t) => { location.hash = '#inventory'; }, ti);
    await sleep(900);
    await page.evaluate((t) => window.wfmApplyTheme(t), ti);
    let prev = '', stable = 0;
    for (let i = 0; i < 12 && stable < 2; i++) {
      await sleep(250);
      const sig = await page.evaluate(() => getComputedStyle(document.body).backgroundColor + '|' +
        getComputedStyle(document.documentElement).getPropertyValue('--bg').trim());
      stable = (sig === prev) ? stable + 1 : 0; prev = sig;
    }
    await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))));
    const atScan = await page.evaluate(DUMP);
    await sleep(3000);
    const after = await page.evaluate(DUMP);
    console.log('=== theme ' + ti + ' at scan: ' + JSON.stringify(atScan.rows[0]) + ' rect=' + JSON.stringify(atScan.rect));
    console.log('    chain:');
    atScan.rows.slice(1).forEach((r) => console.log('      ' + r.tag + '#' + r.id + '.' + r.cls + ' bg=' + r.bg + ' img=' + r.img + ' tr=' + r.tr));
    console.log('    after 3s bg=' + JSON.stringify(after.rows[0].bg));
  }
  await browser.close();
})().catch((e) => { console.error('PROBE FAILED: ' + e.stack); process.exit(1); });
