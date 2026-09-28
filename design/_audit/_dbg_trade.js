/* Diagnose what exceeds main's box on /#trade at 1200-1600 (index rightGap goes negative). */
'use strict';
const puppeteer = require('F:/VSC Projects/pb-bench/node_modules/puppeteer-core');
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const BASE = 'http://127.0.0.1:8787';
(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: 'new', args: ['--no-sandbox', '--disable-gpu'] });
  const p = await b.newPage();
  for (const w of [1200, 1600]) {
    await p.setViewport({ width: w, height: 1000 });
    await p.goto(BASE + '/#trade', { waitUntil: 'networkidle2' });
    await new Promise(r => setTimeout(r, 700));
    const r = await p.evaluate(() => {
      const main = document.querySelector('main');
      const mr = main.getBoundingClientRect();
      const rows = [];
      main.querySelectorAll('*').forEach(el => {
        if (el.closest('.hidden')) return;
        const b2 = el.getBoundingClientRect();
        if (b2.width < 1 || b2.height < 1) return;
        if (b2.right > mr.right + 1) {
          const chain = [];
          let q = el;
          while (q && q !== document.body) {
            const cs = getComputedStyle(q);
            chain.push(q.tagName.toLowerCase() + (q.id ? '#' + q.id : '') + (typeof q.className === 'string' && q.className ? '.' + q.className.split(' ').slice(0, 2).join('.') : '') + '[' + cs.overflowX + '/' + (cs.position) + ']');
            q = q.parentElement;
          }
          rows.push({ sel: chain[0], right: Math.round(b2.right), w: Math.round(b2.width), over: Math.round(b2.right - mr.right), chain: chain.slice(0, 6).join(' < ') });
        }
      });
      const seen = {};
      rows.forEach(x => { if (!seen[x.chain]) seen[x.chain] = x; });
      return { innerWidth: innerWidth, mainRight: Math.round(mr.right), scrollWidth: document.documentElement.scrollWidth,
        bodyOverflowX: getComputedStyle(document.body).overflowX, htmlOverflowX: getComputedStyle(document.documentElement).overflowX,
        count: rows.length, worst: Object.values(seen).slice(0, 6) };
    });
    console.log(w, JSON.stringify(r, null, 1));
  }
  await b.close();
})();
