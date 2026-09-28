/* Inspect the art-less card: does the big showcase card carry the letter tile? (+ screenshot) */
'use strict';
const puppeteer = require('F:/VSC Projects/pb-bench/node_modules/puppeteer-core');
const BASE = 'http://127.0.0.1:8787';
const SHOTS = 'C:/Users/jayde/AppData/Local/Temp/shotkit/shots';
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  const browser = await puppeteer.launch({
    executablePath: CHROME, headless: 'new',
    args: ['--no-sandbox', '--disable-dev-shm-usage', '--window-size=1920,1080'],
  });
  const p = await browser.newPage();
  await p.setViewport({ width: 1920, height: 1080 });
  const errs = [];
  p.on('console', (m) => { if (m.type() === 'error') errs.push(m.text()); });
  p.on('pageerror', (e) => errs.push('pageerror: ' + String(e.message || e)));
  await p.goto(BASE + '/cards.html', { waitUntil: 'load' });
  await p.waitForFunction(() => document.querySelectorAll('#grid .mcd-card').length > 0, { timeout: 20000 }).catch(() => {});
  await sleep(3000);
  const picked = await p.evaluate(() => {
    const q = document.getElementById('q');
    q.value = 'primed bane of corpus';
    q.dispatchEvent(new Event('input', { bubbles: true }));
    return null;
  });
  await sleep(600);
  const opened = await p.evaluate(() => {
    const card = document.querySelector('#grid .mcd-card[data-slug]');
    if (!card) return null;
    card.click();
    return card.getAttribute('data-slug');
  });
  await sleep(1500);
  const state = await p.evaluate(() => {
    const big = document.querySelector('.ins-card');
    const info = document.querySelector('.ins-info');
    return {
      open: !document.querySelector('.ins-wrap').classList.contains('hidden'),
      slug: (big && big.querySelector('.mcd-card') || {}).getAttribute
        ? big.querySelector('.mcd-card').getAttribute('data-slug') : null,
      bigTile: !!(big && big.querySelector('.mcd-tile')),
      bigTileText: (big && big.querySelector('.mcd-tile') || {}).textContent,
      bigImg: !!(big && big.querySelector('.mcd-art-img')),
      desc: !!(big && big.querySelector('.mcd-desc')),
      name: (info.querySelector('.ins-name') || {}).textContent,
      rows: [...info.querySelectorAll('.ins-row')].map((r) => r.textContent.trim()),
      grade: (info.querySelector('.mcd-grade') || {}).textContent,
      flip: !!document.querySelector('.ins-bar .ins-flip'),
    };
  });
  await p.screenshot({ path: SHOTS + '/s6b-cards-inspect.png' });
  console.log(JSON.stringify({ picked: opened, ...state, errors: errs.length, errs: errs.slice(0, 3) }, null, 1));
  await browser.close();
})();
