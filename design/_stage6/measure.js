/* Stage 6 - Collection: the per-viewport measurements the density pins quote.
 *   node design/_stage6/measure.js
 * Read-only. Prints one line per viewport: head budget, section row, strip, grid, relic rows.
 * Widths: the wide band (1920), the 1500- cap band (1440), the 1200 rung (1200), the 900 fold
 * (1024), the tablet band (768) and the phone (390).
 */
'use strict';
const puppeteer = require('F:/VSC Projects/pb-bench/node_modules/puppeteer-core');
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const WIDTHS = [1920, 1440, 1200, 1024, 768, 390];

(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: 'new',
    args: ['--no-sandbox', '--disable-dev-shm-usage'] });
  for (const w of WIDTHS) {
    const p = await b.newPage();
    await p.setViewport({ width: w, height: w === 390 ? 844 : 1080 });
    await p.goto('http://127.0.0.1:8787/collection.html', { waitUntil: 'load' });
    await sleep(2000);
    const out = { w };
    out.head = await p.evaluate(() => {
      const R = (e) => Math.round(e.getBoundingClientRect().height);
      const lines = (sel) => new Set([...document.querySelectorAll(sel)]
        .map((x) => Math.round(x.getBoundingClientRect().top))).size;
      const tiles = [...document.querySelectorAll('#grid .cl-card')];
      const y0 = tiles.length ? Math.round(tiles[0].getBoundingClientRect().y) : 0;
      return {
        headH: R(document.getElementById('overall')),
        navH: R(document.getElementById('collectionNav')),
        navLines: lines('#collectionNav .navpill'),
        stripLines: lines('#tabs .tab'),
        perRow: tiles.filter((t) => Math.round(t.getBoundingClientRect().y) === y0).length,
        firstScreen: tiles.filter((t) => t.getBoundingClientRect().top < window.innerHeight).length,
        tileH: [...new Set(tiles.map((t) => Math.round(t.getBoundingClientRect().height)))].join('/'),
        docH: document.documentElement.scrollHeight,
        docW: document.documentElement.scrollWidth
      };
    });
    await p.evaluate(() => { location.hash = '#relics'; });
    await sleep(1500);
    out.relic = await p.evaluate(() => {
      const R = (e) => Math.round(e.getBoundingClientRect().height);
      const tip = document.getElementById('clTip');
      const tr = document.querySelector('#relBody tr');
      return {
        rows: document.querySelectorAll('#relBody tr').length,
        rowH: tr ? +tr.getBoundingClientRect().height.toFixed(2) : null,
        dockH: R(tip), dockW: Math.round(tip.getBoundingClientRect().width),
        dockRelic: (tip.querySelector('.clt-name') || {}).textContent,
        sel: document.querySelectorAll('#relBody tr.sel').length,
        docH: document.documentElement.scrollHeight
      };
    });
    console.log(JSON.stringify(out));
    await p.close();
  }
  await b.close();
})();
