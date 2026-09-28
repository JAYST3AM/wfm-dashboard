/* Audit-1 check 4b: dead space per page, measured as the viewport the page does not use.
 *   content edge = widest visible element inside main that is not itself inside a horizontal
 *   scroller (so a scrollable table is not counted as content extent); rail width is separate.
 *   node design/_audit/qa_deadspace.js   ->  design/_audit/deadspace.json
 */
'use strict';
const puppeteer = require('F:/VSC Projects/pb-bench/node_modules/puppeteer-core');
const fs = require('fs');
const path = require('path');
const BASE = 'http://127.0.0.1:8787';
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const WIDTHS = [1024, 1200, 1500, 1600, 1920];
const TARGETS = [
  ['index#home', '/#home'], ['index#trade', '/#trade'], ['index#inventory', '/#inventory'],
  ['index#tools', '/#tools'], ['index#tools/deals', '/#tools/deals'], ['index#tools/player', '/#tools/player'],
  ['collection', '/collection.html'], ['collection#relics', '/collection.html#relics'], ['collection#mastery', '/collection.html#mastery'],
  ['cards', '/cards.html'], ['settings', '/settings.html'], ['settings#trading', '/settings.html#trading'], ['item', '/item.html'],
];
const sleep = ms => new Promise(r => setTimeout(r, ms));

const M = `(() => {
  const iw = innerWidth;
  const inScroller = el => { let p = el.parentElement; while (p && p !== document.body) {
    const ox = getComputedStyle(p).overflowX; if (ox === 'auto' || ox === 'scroll') return true; p = p.parentElement; } return false; };
  const isHidden = el => el.closest('.hidden') !== null;
  const main = document.querySelector('main');
  let right = 0, widest = null, cards = [];
  main.querySelectorAll('*').forEach(el => {
    if (isHidden(el) || inScroller(el)) return;
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) return;
    if (r.right > right) right = r.right;
    if (!widest || r.width > widest.w) widest = { w: Math.round(r.width), sel: el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + (typeof el.className === 'string' && el.className ? '.' + el.className.split(' ')[0] : '') };
    if (el.classList.contains('card')) cards.push(Math.round(r.width));
  });
  const aside = document.querySelector('.side');
  const ar = aside ? aside.getBoundingClientRect() : null;
  const mr = main.getBoundingClientRect();
  /* top-level layout: rail | shellcol */
  const col = document.querySelector('.shellcol');
  const cr = col ? col.getBoundingClientRect() : null;
  /* column count actually used by the widest grid in view */
  const sec = [...main.children].find(s => s.tagName === 'SECTION' && !s.classList.contains('hidden')) || main;
  const grids = [...sec.querySelectorAll('.cols-2, .cols-3')].filter(g => !isHidden(g) && g.getBoundingClientRect().width > 1)
    .map(g => ({ cls: g.className.split(' ')[0], cols: getComputedStyle(g).gridTemplateColumns.split(' ').length, w: Math.round(g.getBoundingClientRect().width) }));
  return { innerWidth: iw, scrollWidth: document.documentElement.scrollWidth,
    railW: ar ? Math.round(ar.width) : null, mainX: Math.round(mr.left), mainW: Math.round(mr.width),
    colW: cr ? Math.round(cr.width) : null, colRight: cr ? Math.round(cr.right) : null,
    contentRight: Math.round(right), rightGap: Math.round(iw - right), widest,
    cardsMax: cards.length ? Math.max(...cards) : null, cardsCount: cards.length, grids };
})()`;

(async () => {
  const browser = await puppeteer.launch({ executablePath: CHROME, headless: 'new', args: ['--no-sandbox', '--disable-gpu'] });
  const page = await browser.newPage();
  const out = {};
  for (const [name, url] of TARGETS) {
    out[name] = {};
    for (const w of WIDTHS) {
      await page.setViewport({ width: w, height: 1000 });
      await page.goto(BASE + url, { waitUntil: 'networkidle2' });
      await sleep(450);
      const m = await page.evaluate(M);
      out[name][w] = m;
      console.log(`${name.padEnd(21)} ${String(w).padEnd(5)} rail=${m.railW} main=${m.mainW}@${m.mainX} contentRight=${m.contentRight} rightGap=${m.rightGap} ` +
        `widest=${m.widest ? m.widest.sel + ':' + m.widest.w : '-'} cards=${m.cardsCount}/${m.cardsMax} grids=${JSON.stringify(m.grids.map(g => g.cls + 'x' + g.cols + ':' + g.w))}`);
    }
  }
  fs.writeFileSync(path.join(__dirname, 'deadspace.json'), JSON.stringify(out, null, 1));
  console.log('written design/_audit/deadspace.json');
  await browser.close();
})().catch(e => { console.error('PROBE FAILED', e); process.exit(1); });
