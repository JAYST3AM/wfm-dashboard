/* design/_gatefix/probe_rref2.js — find .cl-rref on the relics view (longer wait + diagnostics). */
'use strict';
const puppeteer = require('F:/VSC Projects/pb-bench/node_modules/puppeteer-core');
const BASE = process.env.WFM_BASE || 'http://127.0.0.1:8787';
const CHROME = process.env.WFM_CHROME || 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
(async () => {
  const browser = await puppeteer.launch({ executablePath: CHROME, headless: 'new', args: ['--no-sandbox', '--disable-dev-shm-usage'] });
  const page = await browser.newPage();
  await page.setViewport({ width: 1920, height: 1080 });
  const errs = [];
  page.on('pageerror', (e) => errs.push(String(e.message)));
  page.on('console', (m) => { if (m.type() === 'error') errs.push(m.text()); });
  await page.goto(BASE + '/collection.html', { waitUntil: 'load' });
  await sleep(4000);
  for (const h of ['', '#relics']) {
    if (h) { await page.evaluate((x) => { location.hash = x; }, h); await sleep(3000); }
    const info = await page.evaluate(() => ({
      hash: location.hash,
      sections: [...document.querySelectorAll('main > section')].map((s) => s.id + (s.classList.contains('hidden') ? ':hidden' : ':shown')),
      relRows: document.querySelectorAll('#relBody tr').length,
      rref: document.querySelectorAll('.cl-rref').length,
      rwhere: document.querySelectorAll('.cl-rwheretxt').length,
      sampleRow: (() => { const tr = document.querySelector('#relBody tr'); return tr ? tr.outerHTML.slice(0, 900) : null; })(),
    }));
    console.log(JSON.stringify(info, null, 1).slice(0, 2200));
  }
  console.log('errors: ' + JSON.stringify(errs.slice(0, 6)));
  await browser.close();
})().catch((e) => { console.error('PROBE FAILED: ' + e.stack); process.exit(1); });
