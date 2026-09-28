/* header chip probe: node design/_stage3/qa_chips.js */
'use strict';
const puppeteer = require('F:/VSC Projects/pb-bench/node_modules/puppeteer-core');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
(async () => {
  const b = await puppeteer.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: 'new', args: ['--no-sandbox', '--disable-dev-shm-usage'] });
  const p = await b.newPage();
  for (const [w, h] of [[1920, 1080], [1366, 768]]) {
    await p.setViewport({ width: w, height: h });
    await p.goto('http://127.0.0.1:8787/', { waitUntil: 'load' });
    await sleep(3200);
    console.log(w, await p.evaluate(() => {
      const c = document.getElementById('chips');
      const strip = document.getElementById('todayTrades');
      const chip = c ? c.querySelector('.chip.warn') : null;
      const cs = chip ? getComputedStyle(chip) : null;
      return { chips: c ? c.textContent.replace(/\s+/g, ' ').trim() : 'none',
               stripTrades: strip ? strip.textContent.trim() : 'none',
               warnDisplay: cs ? cs.display : 'no chip',
               warnRects: chip ? chip.getClientRects().length : 0,
               hasMatch: document.body.matches(':has(#view-home:not(.hidden))') };
    }));
  }
  await b.close();
})().catch((e) => { console.error(e); process.exit(1); });
