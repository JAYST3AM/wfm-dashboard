/* Toolbar/control audit: exact geometry + computed styles of every control in .mcd-tools. */
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
  const p = await browser.newPage();
  await p.setViewport({ width: 1920, height: 1080 });
  await p.goto(BASE + '/cards.html', { waitUntil: 'load' });
  await p.waitForFunction(() => document.querySelectorAll('#grid .mcd-card').length > 0, { timeout: 20000 }).catch(() => {});
  await sleep(3000);
  const info = await p.evaluate(() => {
    const out = [];
    document.querySelectorAll('.mcd-tools > *').forEach((k) => {
      const r = k.getBoundingClientRect();
      const cs = getComputedStyle(k);
      const item = { sel: k.id || k.className, top: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height),
        radius: cs.borderRadius, bg: cs.backgroundColor, border: cs.borderColor, font: cs.fontSize };
      if (k.classList.contains('mcd-row')) {
        item.kids = [...k.children].map((b) => {
          const br = b.getBoundingClientRect();
          const bs = getComputedStyle(b);
          return { t: (b.id || b.className || b.tagName) + ':' + b.textContent.trim().slice(0, 14),
            w: Math.round(br.width), h: Math.round(br.height), radius: bs.borderRadius,
            bg: bs.backgroundColor, border: bs.borderColor, color: bs.color };
        });
      }
      out.push(item);
    });
    const rows = [...new Set([...document.querySelectorAll('.mcd-tools > *')].map((k) => Math.round(k.getBoundingClientRect().top)))];
    const headRows = [...new Set([...document.querySelector('.mcd-head').children].map((k) => Math.round(k.getBoundingClientRect().top)))];
    return { toolsRows: rows.length, headerRows: headRows, controls: out,
      sepCount: document.querySelectorAll('.mcd-sep').length,
      iconsInReset: document.querySelectorAll('#resetBtn svg.i').length,
      toolsW: Math.round(document.querySelector('.mcd-tools').getBoundingClientRect().width) };
  });
  console.log(JSON.stringify(info, null, 1));
  await browser.close();
})();
