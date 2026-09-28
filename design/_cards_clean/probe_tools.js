/* Cards toolbar measure: does the one toolbar row fit on a single line at 1920x1080? */
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
  await sleep(2500);
  const info = await p.evaluate(() => {
    const tools = document.querySelector('.mcd-tools');
    const kids = [...tools.children].map((k) => {
      const r = k.getBoundingClientRect();
      return { cls: k.className, w: Math.round(r.width), top: Math.round(r.top), h: Math.round(r.height) };
    });
    const tr = tools.getBoundingClientRect();
    const rows = [...new Set(kids.map((k) => k.top))].length;
    return {
      rowCount: rows,
      toolsW: Math.round(tr.width), toolsH: Math.round(tr.height),
      kidSum: kids.reduce((a, k) => a + k.w, 0),
      kids,
      gridW: Math.round(document.getElementById('grid').getBoundingClientRect().width),
      wrapW: Math.round(document.querySelector('.mcd-wrap').getBoundingClientRect().width),
      metaW: Math.round(document.getElementById('meta').getBoundingClientRect().width),
      titleW: Math.round(document.querySelector('.mcd-title').getBoundingClientRect().width),
      headRows: [...new Set([...document.querySelector('.mcd-head').children].map((k) => Math.round(k.getBoundingClientRect().top)))].length,
      heights: {
        search: Math.round(document.querySelector('.mcd-search').getBoundingClientRect().height),
        select: Math.round(document.getElementById('typeSel').getBoundingClientRect().height),
        btn: Math.round(document.querySelector('#stateRow .mcd-btn').getBoundingClientRect().height),
      },
    };
  });
  console.log(JSON.stringify(info, null, 1));
  await browser.close();
})();
