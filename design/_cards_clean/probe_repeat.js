/* Repeat-load check: how often does the local dev server refuse a connection during the art
   burst? (Pre-existing server-side backlog behaviour; the page must still never show a broken
   image.) 3 loads, counts only. */
'use strict';
const puppeteer = require('F:/VSC Projects/pb-bench/node_modules/puppeteer-core');
const BASE = 'http://127.0.0.1:8787';
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  const browser = await puppeteer.launch({
    executablePath: CHROME, headless: 'new',
    args: ['--no-sandbox', '--disable-dev-shm-usage', '--window-size=1920,1080'],
  });
  const runs = [];
  for (let i = 0; i < 3; i++) {
    const p = await browser.newPage();
    await p.setViewport({ width: 1920, height: 1080 });
    const errs = [];
    const failed = [];
    p.on('console', (m) => { if (m.type() === 'error') errs.push(m.text()); });
    p.on('pageerror', (e) => errs.push('pageerror: ' + String(e.message || e)));
    p.on('requestfailed', (r) => failed.push(r.url() + ' :: ' + ((r.failure() || {}).errorText || '')));
    await p.goto(BASE + '/cards.html', { waitUntil: 'load' });
    await p.waitForFunction(() => document.querySelectorAll('#grid .mcd-card').length > 0, { timeout: 20000 }).catch(() => {});
    await sleep(4000);
    const dom = await p.evaluate(() => {
      const imgs = [...document.querySelectorAll('#grid .mcd-art-img')];
      return {
        cards: document.querySelectorAll('#grid .mcd-card').length,
        imgs: imgs.length,
        broken: imgs.filter((x) => x.complete && x.naturalWidth === 0).length,
        tiles: document.querySelectorAll('#grid .mcd-tile').length,
      };
    });
    runs.push({ errs, failed, dom });
    await p.close();
  }
  runs.forEach((r, i) => console.log('run ' + (i + 1) + ': errors=' + r.errs.length +
    ' refused=' + r.failed.filter((f) => f.includes('ERR_CONNECTION_REFUSED')).length +
    ' otherFailed=' + r.failed.filter((f) => !f.includes('ERR_CONNECTION_REFUSED')).length +
    ' dom=' + JSON.stringify(r.dom)));
  const refused = runs.flatMap((r) => r.failed.filter((f) => f.includes('ERR_CONNECTION_REFUSED')));
  console.log('unique refused urls: ' + JSON.stringify([...new Set(refused)]));
  console.log('all non-refused failures: ' +
    JSON.stringify([...new Set(runs.flatMap((r) => r.failed.filter((f) => !f.includes('ERR_CONNECTION_REFUSED'))))]));
  await browser.close();
})();
