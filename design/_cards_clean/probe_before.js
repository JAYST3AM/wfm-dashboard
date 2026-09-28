/* Cards clean-pass probe (BEFORE): ids union, console errors, art/blocked-CDN situation.
 *
 *   node probe_before.js
 *
 * Read-only: types into the search box (state only, nothing written) to see the counts move.
 * Writes design/_cards_clean/ids_before.json + a baseline shot into the shotkit folder.
 */
'use strict';
const puppeteer = require('F:/VSC Projects/pb-bench/node_modules/puppeteer-core');
const fs = require('fs');
const path = require('path');

const BASE = 'http://127.0.0.1:8787';
const SHOTS = 'C:/Users/jayde/AppData/Local/Temp/shotkit/shots';
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const HERE = 'F:/VSC Projects/wfm-dashboard/design/_cards_clean';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  const browser = await puppeteer.launch({
    executablePath: CHROME, headless: 'new',
    args: ['--no-sandbox', '--disable-dev-shm-usage', '--window-size=1920,1080'],
  });
  const p = await browser.newPage();
  await p.setViewport({ width: 1920, height: 1080 });
  const consoleErrors = [];
  const failed = [];
  p.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text()); });
  p.on('pageerror', (e) => consoleErrors.push('pageerror: ' + String(e.message || e)));
  p.on('requestfailed', (r) => failed.push(r.url() + ' :: ' + ((r.failure() || {}).errorText || '')));

  await p.goto(BASE + '/cards.html', { waitUntil: 'load' });
  await p.waitForFunction(() => document.querySelectorAll('#grid .mcd-card').length > 0, { timeout: 20000 })
    .catch(() => {});
  await sleep(5000);   // let the art probe + any image loads settle

  const before = await p.evaluate(() => {
    const cards = [...document.querySelectorAll('#grid .mcd-card')];
    const ids = [...document.querySelectorAll('[id]')].map((e) => e.id);
    const imgs = [...document.querySelectorAll('#grid .mcd-art-img')];
    return {
      url: location.href,
      title: document.title,
      ids,
      idCount: ids.length,
      gridCards: cards.length,
      artImgs: imgs.length,
      artBroken: imgs.filter((i) => i.complete && i.naturalWidth === 0).length,
      hasArt: document.querySelectorAll('#grid .mcd-art.has-art').length,
      metaText: (document.getElementById('meta') || {}).textContent,
      srcLine: (document.getElementById('srcLine') || {}).textContent,
      moreBtn: (document.getElementById('moreBtn') || {}).textContent,
      chips: [...document.querySelectorAll('#chips .chip')].map((c) => c.textContent.trim()),
      bodyScrollW: document.documentElement.scrollWidth,
      clientW: document.documentElement.clientWidth,
    };
  });

  // one filter interaction: the search box
  await p.click('#q');
  await p.type('#q', 'vitality', { delay: 8 });
  await sleep(600);
  const search = await p.evaluate(() => ({
    q: document.getElementById('q').value,
    gridCards: document.querySelectorAll('#grid .mcd-card').length,
    meta: document.getElementById('meta').textContent,
    ariaLabel: document.getElementById('grid').getAttribute('aria-label'),
  }));
  await p.evaluate(() => { const q = document.getElementById('q'); q.value = ''; q.dispatchEvent(new Event('input', { bubbles: true })); });
  await sleep(400);

  await p.screenshot({ path: path.join(SHOTS, 's6b-cards-before.png') });

  const out = { before, search, consoleErrors, failed };
  fs.writeFileSync(path.join(HERE, 'ids_before.json'), JSON.stringify({
    page: 'cards.html', captured: new Date().toISOString(), ids: before.ids,
  }, null, 1));
  fs.writeFileSync(path.join(HERE, 'probe_before.json'), JSON.stringify(out, null, 1));
  console.log(JSON.stringify({
    idCount: before.idCount, gridCards: before.gridCards, artImgs: before.artImgs,
    artBroken: before.artBroken, hasArt: before.hasArt,
    metaText: before.metaText, srcLine: before.srcLine, moreBtn: before.moreBtn,
    chips: before.chips, scroll: [before.bodyScrollW, before.clientW],
    search: search, consoleErrorCount: consoleErrors.length,
    consoleErrors: [...new Set(consoleErrors)].slice(0, 12), failed: [...new Set(failed)].slice(0, 12),
  }, null, 1));
  await browser.close();
})();
