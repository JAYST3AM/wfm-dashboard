/* Width probe: 1440x900 / 1100x900 / 390x844 -> no horizontal scroll, toolbar + tiles sane. */
'use strict';
const puppeteer = require('F:/VSC Projects/pb-bench/node_modules/puppeteer-core');
const BASE = 'http://127.0.0.1:8787';
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  const browser = await puppeteer.launch({
    executablePath: CHROME, headless: 'new',
    args: ['--no-sandbox', '--disable-dev-shm-usage', '--window-size=1440,900'],
  });
  for (const [w, h] of [[1440, 900], [1100, 900], [390, 844]]) {
    const p = await browser.newPage();
    await p.setViewport({ width: w, height: h });
    const errs = [];
    p.on('console', (m) => { if (m.type() === 'error') errs.push(m.text()); });
    p.on('pageerror', (e) => errs.push('pageerror: ' + String(e.message || e)));
    await p.goto(BASE + '/cards.html', { waitUntil: 'load' });
    await p.waitForFunction(() => document.querySelectorAll('#grid .mcd-card').length > 0, { timeout: 20000 }).catch(() => {});
    await sleep(2500);
    const info = await p.evaluate(() => {
      const de = document.documentElement;
      const tiles = [...document.querySelectorAll('#grid .mcd-card')].slice(0, 8);
      const rows = {};
      tiles.forEach((t) => { const r = Math.round(t.getBoundingClientRect().height); rows[r] = (rows[r] || 0) + 1; });
      const tools = document.querySelector('.mcd-tools');
      const tops = [...new Set([...tools.children].map((k) => Math.round(k.getBoundingClientRect().top)))];
      const overflow = [...document.querySelectorAll('.mcd-wrap *')].filter((n) => {
        const r = n.getBoundingClientRect();
        return r.right > de.clientWidth + 1 || r.left < -1;
      }).length;
      return {
        vw: de.clientWidth, scrollW: de.scrollWidth, overflowEls: overflow,
        toolsRows: tops.length, cardHeights: rows, gridCols: getComputedStyle(document.getElementById('grid')).gridTemplateColumns.split(' ').length,
        metaClipped: document.getElementById('meta').scrollWidth > document.getElementById('meta').clientWidth + 1,
      };
    });
    console.log(w + 'x' + h + ': ' + JSON.stringify(info) + ' errors=' + errs.length + (errs[0] ? ' ' + errs[0] : ''));
    if (w === 390) await p.screenshot({ path: 'C:/Users/jayde/AppData/Local/Temp/shotkit/shots/s6b-cards-390.png' });
    await p.close();
  }
  await browser.close();
})();
