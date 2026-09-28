/* design/_gatefix/shots.js — captures the three gate-fix evidence shots. Read-only driving:
   theme applied the same way the UI does (wfmApplyTheme), hashes only, no clicks on Save/refresh. */
'use strict';
const puppeteer = require('F:/VSC Projects/pb-bench/node_modules/puppeteer-core');
const BASE = process.env.WFM_BASE || 'http://127.0.0.1:8787';
const CHROME = process.env.WFM_CHROME || 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const OUT = process.env.SHOT_DIR || 'C:/Users/jayde/AppData/Local/Temp/shotkit/shots';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const THEME_LIGHT = 14;   /* Frost Light */
const THEME_KUVA = 2;     /* Kuva Crimson */

(async () => {
  const browser = await puppeteer.launch({ executablePath: CHROME, headless: 'new',
    args: ['--no-sandbox', '--disable-dev-shm-usage', '--window-size=1920,1080'] });
  const page = await browser.newPage();
  await page.setViewport({ width: 1920, height: 1080 });
  const errs = [];
  page.on('pageerror', (e) => errs.push(String(e.message)));

  /* 1. index in a light theme, History tab on screen: the .badge.sale rows are the fix under test */
  await page.goto(BASE + '/', { waitUntil: 'load' });
  await sleep(2800);
  await page.evaluate((t) => { window.wfmApplyTheme(t); }, THEME_LIGHT);
  await sleep(900);
  await page.evaluate(() => { location.hash = '#trade/history'; });
  await sleep(1600);
  const badge = await page.evaluate(() => {
    const log = document.getElementById('tradeLog');
    const b = log && log.querySelector('.badge.sale');
    if (!b) return null;
    b.scrollIntoView({ block: 'center' });
    const cs = getComputedStyle(b);
    const r = b.getBoundingClientRect();
    return { text: b.textContent, color: cs.color, visible: r.width > 0 && r.height > 0,
      top: Math.round(r.top), rows: log.querySelectorAll('.lrow').length };
  });
  await sleep(400);
  await page.screenshot({ path: OUT + '/gf-light-home.png' });
  console.log('gf-light-home.png', JSON.stringify(badge));

  /* 2. collection > relics under Kuva Crimson: the .cl-rref cells (was accent-dim = 1.85:1) */
  await page.goto(BASE + '/collection.html', { waitUntil: 'load' });
  await sleep(4000);
  await page.evaluate((t) => { window.wfmApplyTheme(t); }, THEME_KUVA);
  await sleep(900);
  await page.evaluate(() => { location.hash = '#relics'; });
  await sleep(2500);
  const rref = await page.evaluate(() => {
    const cells = [...document.querySelectorAll('.cl-rref')];
    if (cells.length) cells[0].scrollIntoView({ block: 'center' });
    const cs = cells.length ? getComputedStyle(cells[0]) : null;
    return { count: cells.length, color: cs && cs.color, bg: cs && cs.backgroundColor, bg0: getComputedStyle(document.body).backgroundColor };
  });
  await sleep(400);
  await page.screenshot({ path: OUT + '/gf-kuva-relics.png' });
  console.log('gf-kuva-relics.png', JSON.stringify(rref));

  /* 3. tools > baro: the empty-stock line (was the 42-word dev note) */
  await page.goto(BASE + '/', { waitUntil: 'load' });
  await sleep(2800);
  await page.evaluate(() => { location.hash = '#tools/baro'; });
  await sleep(1400);
  const baro = await page.evaluate(() => {
    const meta = document.getElementById('baroMeta');
    const list = document.getElementById('baroList');
    if (list) list.scrollIntoView({ block: 'center' });
    const pad = list && list.querySelector('.dim.pad');
    return { meta: meta && meta.textContent, line: pad && pad.textContent.trim(), title: pad && pad.title.slice(0, 90) };
  });
  await sleep(400);
  await page.screenshot({ path: OUT + '/gf-baro.png' });
  console.log('gf-baro.png', JSON.stringify(baro));

  /* leave the profile as we found it */
  await page.evaluate((t) => { try { localStorage.setItem('wfm.theme', String(t)); } catch (e) {} window.wfmApplyTheme(t); }, 0);
  console.log('pageerrors: ' + JSON.stringify(errs.slice(0, 5)));
  await browser.close();
})().catch((e) => { console.error('SHOTS FAILED: ' + e.stack); process.exit(1); });
