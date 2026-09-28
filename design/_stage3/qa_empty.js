/* empty-state probe: home with no plan / no inventory (whatever the data dir holds right now)
   node design/_stage3/qa_empty.js  -- read-only */
'use strict';
const puppeteer = require('F:/VSC Projects/pb-bench/node_modules/puppeteer-core');
const path = require('path');
const SHOTS = 'C:/Users/jayde/AppData/Local/Temp/shotkit/shots';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
(async () => {
  const b = await puppeteer.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: 'new', args: ['--no-sandbox', '--disable-dev-shm-usage', '--force-device-scale-factor=1'] });
  const p = await b.newPage();
  const errors = [];
  p.on('console', (m) => { if (m.type() === 'error') errors.push('console: ' + m.text()); });
  p.on('pageerror', (e) => errors.push('pageerror: ' + ((e && e.message) || e)));
  await p.setViewport({ width: 1920, height: 1080 });
  await p.goto('http://127.0.0.1:8787/', { waitUntil: 'load' });
  await sleep(3500);
  console.log(JSON.stringify(await p.evaluate(() => {
    const vis = (id) => { const e = document.getElementById(id); return e ? !!e.getClientRects().length : null; };
    const de = document.documentElement;
    return {
      de_hidden: [...document.querySelectorAll('#homeMain > *')].map((e) => (e.id || e.className) + (e.getClientRects().length ? '' : ' [hidden]')),
      alertsShown: vis('alertsCard'), nextShown: vis('homeSellNext'), queueShown: vis('sellQueueCard'),
      strip: [...document.querySelectorAll('#kpis .kpi')].map((k) => k.querySelector('.k-label').textContent + '=' + k.querySelector('.k-val').textContent.trim()),
      noAlertsClass: document.getElementById('homeMain').className,
      overY: Math.max(de.scrollHeight - de.clientHeight, document.body.scrollHeight - window.innerHeight),
      overX: Math.max(de.scrollWidth - de.clientWidth, document.body.scrollWidth - window.innerWidth),
      secOver: (() => { const s = document.querySelector('main > section:not(.hidden)'); return s ? s.scrollHeight - s.clientHeight : null; })(),
    };
  }), null, 1));
  await p.screenshot({ path: path.join(SHOTS, 's3-home-empty-1920.png') });
  console.log('errors', JSON.stringify(errors));
  await b.close();
})().catch((e) => { console.error(e); process.exit(1); });
