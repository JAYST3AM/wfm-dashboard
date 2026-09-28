/* design/_gatefix/probe_btncols2.js — reproduce the gate's exact theme-walk sequence in ONE document
   (home state then inventory state, themes 0/2/14/28 back to back, no reloads) and watch #btnCols. */
'use strict';
const puppeteer = require('F:/VSC Projects/pb-bench/node_modules/puppeteer-core');
const BASE = process.env.WFM_BASE || 'http://127.0.0.1:8787';
const CHROME = process.env.WFM_CHROME || 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const SCAN = `(() => {
  const rows = [];
  document.querySelectorAll('body *').forEach((el) => {
    const own = [...el.childNodes].filter((n) => n.nodeType === 3).map((n) => n.data).join(' ').replace(/\\s+/g, ' ').trim();
    if (!own || !/[a-z0-9]/i.test(own)) return;
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden' || +cs.opacity === 0) return;
    const r = el.getBoundingClientRect();
    if (!(r.width > 0 && r.height > 0)) return;
    const btn = document.getElementById('btnCols');
    if (el === btn) rows.push({ text: own.slice(0, 40), bg: cs.backgroundColor, color: cs.color,
      rect: [r.x|0, r.y|0, r.width|0, r.height|0],
      advOpen: document.getElementById('invAdv') ? document.getElementById('invAdv').open : null });
  });
  const cs2 = getComputedStyle(document.getElementById('btnCols') || document.body);
  return { rows, panel2: getComputedStyle(document.documentElement).getPropertyValue('--panel2').trim(), btnBg: cs2.backgroundColor };
})()`;

(async () => {
  const browser = await puppeteer.launch({ executablePath: CHROME, headless: 'new',
    args: ['--no-sandbox', '--disable-dev-shm-usage'] });
  const page = await browser.newPage();
  await page.setViewport({ width: 1920, height: 1080 });
  await page.goto(BASE + '/', { waitUntil: 'load' });
  await sleep(2200);
  for (const state of ['home', 'inventory']) {
    if (state !== 'home') { await page.evaluate((s) => { location.hash = '#' + s; }, state); await sleep(900); }
    for (const ti of [0, 2, 14, 28]) {
      await page.evaluate((t) => window.wfmApplyTheme(t), ti);
      let prev = '', stable = 0;
      for (let i = 0; i < 12 && stable < 2; i++) {
        await sleep(250);
        const sig = await page.evaluate(() => getComputedStyle(document.body).backgroundColor + '|' +
          getComputedStyle(document.documentElement).getPropertyValue('--bg').trim());
        stable = (sig === prev) ? stable + 1 : 0; prev = sig;
      }
      await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))));
      const out = await page.evaluate(SCAN);
      console.log(state + ' theme ' + ti + ' --panel2=' + out.panel2 + ' btnBg=' + out.btnBg);
      out.rows.forEach((r) => console.log('   row: ' + JSON.stringify(r)));
      if (state === 'inventory' && ti === 14) {
        for (let i = 0; i < 10; i++) { await sleep(300); console.log('   poll+' + ((i + 1) * 300) + 'ms btnBg=' + (await page.evaluate(SCAN)).btnBg); }
      }
    }
  }
  await browser.close();
})().catch((e) => { console.error('PROBE FAILED: ' + e.stack); process.exit(1); });
