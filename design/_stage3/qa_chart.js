/* chart geometry probe: node design/_stage3/qa_chart.js */
'use strict';
const puppeteer = require('F:/VSC Projects/pb-bench/node_modules/puppeteer-core');
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: 'new', args: ['--no-sandbox', '--disable-dev-shm-usage', '--force-device-scale-factor=1'] });
  const p = await b.newPage();
  p.on('pageerror', (e) => console.log('pageerror', e.message));
  await p.setViewport({ width: 1920, height: 1080 });
  await p.goto('http://127.0.0.1:8787/', { waitUntil: 'load' });
  await sleep(4000);
  const geom = async (tag) => {
    const g = await p.evaluate(() => {
      const c = document.querySelector('#chartCard canvas');
      const wrap = document.querySelector('#chartCard .chartwrap');
      const card = document.getElementById('chartCard');
      const pressed = [...document.querySelectorAll('#chartCard .chartbtn')].filter((b) => b.getAttribute('aria-pressed') === 'true').map((b) => b.textContent);
      const cr = c ? c.getBoundingClientRect() : null;
      const wr = wrap ? wrap.getBoundingClientRect() : null;
      return {
        canvasAttr: c ? [c.width, c.height] : null,
        canvasCss: c ? [Math.round(cr.width), Math.round(cr.height)] : null,
        canvasTopLeft: c ? [Math.round(cr.left), Math.round(cr.top)] : null,
        wrapBox: wrap ? [Math.round(wr.width), Math.round(wr.height)] : null,
        cardBox: card ? [Math.round(card.getBoundingClientRect().width), Math.round(card.getBoundingClientRect().height)] : null,
        pressed,
        pts: (window.PlatChart && window.PlatChart.points) ? window.PlatChart.points.length : 'n/a',
      };
    });
    console.log(tag, JSON.stringify(g));
  };
  await geom('at-load');
  /* force a redraw the way the app does on a view switch, then measure again */
  await p.evaluate(() => { if (window.PlatChart && PlatChart.redraw) PlatChart.redraw(); });
  await sleep(400);
  await geom('after-redraw');
  await p.evaluate(() => { location.hash = '#trade'; });
  await sleep(900);
  await p.evaluate(() => { location.hash = '#home'; });
  await sleep(900);
  await geom('after-view-switch');
  await b.close();
})().catch((e) => { console.error(e); process.exit(1); });
