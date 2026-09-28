/* Audit-1 check 4: EDGE SIZES (820 / 1024 / 1200 / 1500 / 1600 / 1920).
 *   per page: horizontal overflow, elements escaping the viewport, clipped pills, dead space.
 *   node design/_audit/qa_widths.js   ->  design/_audit/widths.json
 */
'use strict';
const puppeteer = require('F:/VSC Projects/pb-bench/node_modules/puppeteer-core');
const fs = require('fs');
const path = require('path');
const BASE = 'http://127.0.0.1:8787';
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const WIDTHS = [820, 1024, 1200, 1500, 1600, 1920];
const TARGETS = [
  ['index#home', '/#home'], ['index#trade', '/#trade'], ['index#inventory', '/#inventory'],
  ['index#tools', '/#tools'], ['index#tools/deals', '/#tools/deals'], ['index#tools/player', '/#tools/player'],
  ['collection', '/collection.html'], ['collection#relics', '/collection.html#relics'],
  ['cards', '/cards.html'], ['settings', '/settings.html'], ['item', '/item.html'],
];
const sleep = ms => new Promise(r => setTimeout(r, ms));

const MEASURE = `(() => {
  const iw = window.innerWidth, out = {};
  out.innerWidth = iw;
  out.scrollWidth = document.documentElement.scrollWidth;
  out.bodyScrollWidth = document.body.scrollWidth;
  out.overflowX = Math.max(0, document.documentElement.scrollWidth - iw);
  const contained = el => { let p = el.parentElement; while (p && p !== document.body) {
    const ox = getComputedStyle(p).overflowX; if (ox === 'auto' || ox === 'scroll' || ox === 'hidden') return true; p = p.parentElement; } return false; };
  const esc = [];
  document.querySelectorAll('body *').forEach(el => {
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) return;
    if (r.right > iw + 1 && !contained(el)) {
      const c = typeof el.className === 'string' ? el.className.split(' ')[0] : '';
      esc.push({ sel: el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + (c ? '.' + c : ''), right: Math.round(r.right), w: Math.round(r.width), over: Math.round(r.right - iw) });
    }
  });
  const uniq = {}; esc.forEach(e => { if (!uniq[e.sel] || uniq[e.sel].over < e.over) uniq[e.sel] = e; });
  out.escapes = Object.values(uniq).sort((a, b) => b.over - a.over).slice(0, 8);
  out.escapeCount = esc.length;
  /* rail */
  const aside = document.querySelector('.side'), nav = document.getElementById('mainnav');
  if (aside) { const r = aside.getBoundingClientRect(); out.rail = { w: Math.round(r.width), h: Math.round(r.height), x: Math.round(r.left), y: Math.round(r.top) }; }
  if (nav) { out.nav = { scrollW: nav.scrollWidth, clientW: nav.clientWidth, overflow: Math.max(0, nav.scrollWidth - nav.clientWidth) }; }
  /* pills: clipped text or off-screen */
  const pills = [];
  document.querySelectorAll('.navpill').forEach(p => {
    const r = p.getBoundingClientRect();
    const clippedText = p.scrollWidth > p.clientWidth + 1;
    const offscreen = r.left < -1 || r.right > iw + 1;
    const clippedV = p.scrollHeight > p.clientHeight + 1;
    if (clippedText || offscreen || clippedV) pills.push({ t: p.textContent.trim().slice(0, 18), clippedText, clippedV, offscreen,
      right: Math.round(r.right), sw: p.scrollWidth, cw: p.clientWidth });
  });
  out.clippedPills = pills;
  /* dead space: right gap after the widest visible thing in main, and inside main */
  const main = document.querySelector('main');
  if (main) {
    const mr = main.getBoundingClientRect();
    out.main = { x: Math.round(mr.left), w: Math.round(mr.width), right: Math.round(mr.right), h: Math.round(mr.height) };
    let maxRight = 0, maxW = 0;
    main.querySelectorAll(':scope > section:not(.hidden) *').forEach(el => {
      const r = el.getBoundingClientRect(); if (r.width < 1 || r.height < 1) return;
      if (r.right > maxRight) maxRight = r.right; if (r.width > maxW) maxW = r.width;
    });
    const sr = [...main.children].find(s => s.tagName === 'SECTION' && !s.classList.contains('hidden'));
    out.contentRight = Math.round(maxRight);
    out.rightGap = Math.round(iw - maxRight);
    out.sectionW = sr ? Math.round(sr.getBoundingClientRect().width) : null;
    let cards = [...(sr ? sr.querySelectorAll('.card') : [])].map(c => Math.round(c.getBoundingClientRect().width));
    out.cards = cards.slice(0, 6);
    /* empty space: sum of the two biggest horizontal gaps between sibling cards in the grid */
    const cols = sr ? sr.querySelectorAll('.cols-2, .cols-3, .cards') : [];
  }
  out.footerFoot = (() => { const f = document.getElementById('foot'); return f ? Math.round(f.getBoundingClientRect().width) : null; })();
  return out;
})()`;

(async () => {
  const browser = await puppeteer.launch({ executablePath: CHROME, headless: 'new', args: ['--no-sandbox', '--disable-gpu'] });
  const page = await browser.newPage();
  const out = {};
  for (const [name, url] of TARGETS) {
    out[name] = { url, widths: {} };
    for (const w of WIDTHS) {
      await page.setViewport({ width: w, height: 1000 });
      await page.goto(BASE + url, { waitUntil: 'networkidle2' });
      await sleep(500);
      const m = await page.evaluate(MEASURE);
      out[name].widths[w] = m;
      console.log(`${name.padEnd(20)} ${String(w).padEnd(5)} overflowX=${m.overflowX} escapes=${m.escapeCount}` +
        `${m.escapes.length ? ' worst=' + m.escapes[0].sel + '+'+m.escapes[0].over : ''} rail=${m.rail ? m.rail.w + 'x' + m.rail.h : '-'} ` +
        `navOverflow=${m.nav ? m.nav.overflow : '-'} clippedPills=${m.clippedPills.length} main=${m.main ? m.main.w + '@' + m.main.x : '-'} ` +
        `rightGap=${m.rightGap} sectionW=${m.sectionW} footW=${m.footerFoot}`);
    }
  }
  fs.writeFileSync(path.join(__dirname, 'widths.json'), JSON.stringify(out, null, 1));
  console.log('written design/_audit/widths.json');
  await browser.close();
})().catch(e => { console.error('PROBE FAILED', e); process.exit(1); });
