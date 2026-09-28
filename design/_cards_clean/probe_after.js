/* Cards clean-pass probe (AFTER): click-through, console, id union, screenshots.
 *
 *   node probe_after.js
 *
 * Read-only: search / filter buttons / a card click (opens the in-page inspect overlay) / the
 * "Show more" button — all page state, nothing written to the app. Writes ids_after.json +
 * probe_after.json next to this file and s6b-cards*.png into the shotkit folder.
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
const result = {};

(async () => {
  const browser = await puppeteer.launch({
    executablePath: CHROME, headless: 'new',
    args: ['--no-sandbox', '--disable-dev-shm-usage', '--window-size=1920,1080'],
  });
  const p = await browser.newPage();
  await p.setViewport({ width: 1920, height: 1080 });
  const consoleErrors = [];
  const failed = [];
  const remote = [];
  p.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text()); });
  p.on('pageerror', (e) => consoleErrors.push('pageerror: ' + String(e.message || e)));
  p.on('requestfailed', (r) => failed.push(r.url() + ' :: ' + ((r.failure() || {}).errorText || '')));
  p.on('request', (r) => { if (!r.url().startsWith(BASE)) remote.push(r.url()); });

  await p.goto(BASE + '/cards.html', { waitUntil: 'load' });
  await p.waitForFunction(() => document.querySelectorAll('#grid .mcd-card').length > 0, { timeout: 20000 })
    .catch(() => {});
  await sleep(3500);

  const base = await p.evaluate(() => {
    const imgs = [...document.querySelectorAll('#grid .mcd-art-img')];
    const ids = [...document.querySelectorAll('[id]')].map((e) => e.id);
    return {
      ids,
      idCount: ids.length,
      gridCards: document.querySelectorAll('#grid .mcd-card').length,
      artImgs: imgs.length,
      artBroken: imgs.filter((i) => i.complete && i.naturalWidth === 0).length,
      tiles: document.querySelectorAll('#grid .mcd-tile').length,
      tileLetters: [...document.querySelectorAll('#grid .mcd-tile')].slice(0, 5).map((t) => t.textContent),
      hasArt: document.querySelectorAll('#grid .mcd-art.has-art').length,
      meta: document.getElementById('meta').textContent,
      metaTitle: document.getElementById('meta').title.slice(0, 120),
      title: document.querySelector('.mcd-title') ? document.querySelector('.mcd-title').textContent.trim() : null,
      more: document.getElementById('moreBtn').textContent,
      srcLine: document.getElementById('srcLine').textContent,
      srcTitle: document.getElementById('srcLine').title,
      chips: [...document.querySelectorAll('#chips .chip')].map((c) => c.textContent.trim() + ' | ' + c.title),
      fwCols: getComputedStyle(document.getElementById('grid')).gridTemplateColumns.split(' ').length,
      scrollW: document.documentElement.scrollWidth,
      clientW: document.documentElement.clientWidth,
      cardHeights: [...document.querySelectorAll('#grid .mcd-card')].slice(0, 12).map((c) => Math.round(c.getBoundingClientRect().height)),
    };
  });
  await p.screenshot({ path: path.join(SHOTS, 's6b-cards.png') });

  // ---- search: the count has to move
  await p.click('#q');
  await p.type('#q', 'vitality', { delay: 6 });
  await sleep(500);
  const search = await p.evaluate(() => ({
    gridCards: document.querySelectorAll('#grid .mcd-card').length,
    meta: document.getElementById('meta').textContent,
    aria: document.getElementById('grid').getAttribute('aria-label'),
    clearVisible: !document.getElementById('clearBtn').classList.contains('hidden'),
  }));
  await p.screenshot({ path: path.join(SHOTS, 's6b-cards-filtered.png') });

  // ---- rarity filter (Rare) on top of the search, then a state toggle (Dupes)
  await p.evaluate(() => {
    const rare = [...document.querySelectorAll('#rarityRow [data-rar]')].find((b) => b.getAttribute('data-rar') === 'Rare');
    if (rare) rare.click();
  });
  await sleep(400);
  const rarity = await p.evaluate(() => ({
    gridCards: document.querySelectorAll('#grid .mcd-card').length,
    meta: document.getElementById('meta').textContent,
    active: [...document.querySelectorAll('#rarityRow .mcd-btn.active')].map((b) => b.textContent.trim()),
  }));
  await p.evaluate(() => { document.querySelector('#stateRow [data-state="dupes"]').click(); });
  await sleep(400);
  const dupes = await p.evaluate(() => ({
    gridCards: document.querySelectorAll('#grid .mcd-card').length,
    meta: document.getElementById('meta').textContent,
    moreHidden: document.getElementById('moreWrap').classList.contains('hidden'),
    moreVisible: document.getElementById('moreWrap').getBoundingClientRect().height > 0,
  }));

  // ---- the local-art fallback: a grid of cards with no /hi file (the letter tiles)
  await p.evaluate(() => { document.getElementById('resetBtn').click(); });
  await sleep(300);
  await p.evaluate(() => {
    const q = document.getElementById('q');
    q.value = 'primed bane';
    q.dispatchEvent(new Event('input', { bubbles: true }));
  });
  await sleep(700);
  const tiles = await p.evaluate(() => ({
    gridCards: document.querySelectorAll('#grid .mcd-card').length,
    tiles: document.querySelectorAll('#grid .mcd-tile').length,
    letters: [...document.querySelectorAll('#grid .mcd-tile')].map((t) => t.textContent),
    imgs: document.querySelectorAll('#grid .mcd-art-img').length,
    descs: document.querySelectorAll('#grid .mcd-desc').length,
    meta: document.getElementById('meta').textContent,
  }));
  await p.screenshot({ path: path.join(SHOTS, 's6b-cards-tiles.png') });

  // ---- a type select + the sort select still re-render
  await p.evaluate(() => { document.getElementById('resetBtn').click(); });
  await sleep(400);
  const reset = await p.evaluate(() => ({
    gridCards: document.querySelectorAll('#grid .mcd-card').length,
    meta: document.getElementById('meta').textContent,
    q: document.getElementById('q').value,
    rarityActive: [...document.querySelectorAll('#rarityRow .mcd-btn.active')].map((b) => b.getAttribute('data-rar')),
    typeSel: document.getElementById('typeSel').value,
    sortSel: document.getElementById('sortSel').value,
  }));
  const typeOption = await p.evaluate(() => {
    const sel = document.getElementById('typeSel');
    const opt = [...sel.options].find((o) => o.value);
    if (!opt) return null;
    sel.value = opt.value;
    sel.dispatchEvent(new Event('change', { bubbles: true }));
    return opt.value;
  });
  await sleep(400);
  const typed = await p.evaluate(() => ({
    gridCards: document.querySelectorAll('#grid .mcd-card').length,
    meta: document.getElementById('meta').textContent,
  }));
  await p.evaluate(() => {
    const sel = document.getElementById('sortSel');
    sel.value = 'value';
    sel.dispatchEvent(new Event('change', { bubbles: true }));
  });
  await sleep(400);
  const sorted = await p.evaluate(() => ({
    gridCards: document.querySelectorAll('#grid .mcd-card').length,
    first: (document.querySelector('#grid .mcd-card') || {}).getAttribute
      ? document.querySelector('#grid .mcd-card').getAttribute('data-slug') : null,
  }));
  await p.evaluate(() => { document.getElementById('resetBtn').click(); });
  await sleep(500);

  // ---- a card click opens the inspect overlay (the page's detail surface)
  const opened = await p.evaluate(() => {
    const card = document.querySelector('#grid .mcd-card[data-slug]');
    if (!card) return null;
    card.click();
    return card.getAttribute('data-slug');
  });
  await sleep(1200);
  const inspect = await p.evaluate(() => {
    const wrap = document.querySelector('.ins-wrap');
    const info = document.querySelector('.ins-info');
    return {
      open: wrap ? !wrap.classList.contains('hidden') : false,
      name: info ? (info.querySelector('.ins-name') || {}).textContent : null,
      rows: info ? info.querySelectorAll('.ins-row').length : 0,
      stats: info ? !!info.querySelector('.ins-stats') : false,
      grade: info ? (info.querySelector('.mcd-grade') || {}).textContent : null,
      buttons: [...document.querySelectorAll('.ins-bar .mcd-btn, .ins-bar .btn')].map((b) => b.textContent.trim()),
      bigCardArt: !!(document.querySelector('.ins-card .mcd-art-img') || document.querySelector('.ins-card .mcd-tile')),
      tiles: document.querySelectorAll('#grid .mcd-tile, .ins-card .mcd-tile').length,
    };
  });
  // Escape closes it
  await p.keyboard.press('Escape');
  await sleep(300);
  const closed = await p.evaluate(() => document.querySelector('.ins-wrap').classList.contains('hidden'));

  // ---- Show more keeps working (180 -> 360 tiles)
  await p.evaluate(() => { document.getElementById('moreBtn').click(); });
  await sleep(1200);
  const more = await p.evaluate(() => ({
    gridCards: document.querySelectorAll('#grid .mcd-card').length,
    more: document.getElementById('moreBtn').textContent,
    broken: [...document.querySelectorAll('#grid .mcd-art-img')].filter((i) => i.complete && i.naturalWidth === 0).length,
  }));

  const ids = await p.evaluate(() => [...document.querySelectorAll('[id]')].map((e) => e.id));
  fs.writeFileSync(path.join(HERE, 'ids_after.json'), JSON.stringify({
    page: 'cards.html', captured: new Date().toISOString(), ids,
  }, null, 1));

  result.base = base;
  result.search = search;
  result.rarity = rarity;
  result.dupes = dupes;
  result.tiles = tiles;
  result.reset = reset;
  result.typeOption = typeOption;
  result.typed = typed;
  result.sorted = sorted;
  result.openedCard = opened;
  result.inspect = inspect;
  result.inspectClosed = closed;
  result.more = more;
  result.consoleErrors = consoleErrors;
  result.failed = failed;
  result.remoteRequests = [...new Set(remote)];
  fs.writeFileSync(path.join(HERE, 'probe_after.json'), JSON.stringify(result, null, 1));
  delete result.base.ids;
  console.log(JSON.stringify(result, null, 1));
  await browser.close();
})();
