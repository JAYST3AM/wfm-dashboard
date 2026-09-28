/* Confirm whether the Trade notify card's heading text is actually clipped (check 4 evidence). */
'use strict';
const puppeteer = require('F:/VSC Projects/pb-bench/node_modules/puppeteer-core');
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const BASE = 'http://127.0.0.1:8787';
(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: 'new', args: ['--no-sandbox', '--disable-gpu'] });
  const p = await b.newPage();
  for (const w of [1024, 1200, 1500, 1600, 1920]) {
    await p.setViewport({ width: w, height: 1000 });
    await p.goto(BASE + '/#trade', { waitUntil: 'networkidle2' });
    await new Promise(r => setTimeout(r, 700));
    const r = await p.evaluate(() => {
      const out = [];
      const card = document.getElementById('notifyCard') || (document.getElementById('notifyMeta') || {}).closest ? document.getElementById('notifyMeta').closest('.card') : null;
      const meta = document.getElementById('notifyMeta');
      if (meta) {
        const cr = card.getBoundingClientRect(), mr = meta.getBoundingClientRect();
        out.push({ el: '#notifyMeta', text: meta.textContent.slice(0, 60), metaRight: Math.round(mr.right), cardRight: Math.round(cr.right),
          clippedByCard: Math.round(mr.right - cr.right), metaScrollW: meta.scrollWidth, metaClientW: meta.clientWidth,
          cardOverflowX: getComputedStyle(card).overflowX, cardW: Math.round(cr.width), cardX: Math.round(cr.left),
          cardScrollW: card.scrollWidth, cardClientW: card.clientWidth, cardContentClipped: card.scrollWidth > card.clientWidth + 1 });
      }
      const ops = document.querySelector('.trade-ops');
      out.push({ el: '.trade-ops', overflowX: ops ? getComputedStyle(ops).overflowX : null, w: ops ? Math.round(ops.getBoundingClientRect().width) : null,
        scrollW: ops ? ops.scrollWidth : null, clientW: ops ? ops.clientWidth : null });
      return out;
    });
    console.log(w, JSON.stringify(r));
  }
  await b.close();
})();
