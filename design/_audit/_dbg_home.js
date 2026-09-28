/* Home view state right now (index.html/home.js/home.css were edited after the stage-2 commit,
 * so anything here may be a mid-edit stage-3 artefact - this records the numbers, not a verdict). */
'use strict';
const puppeteer = require('F:/VSC Projects/pb-bench/node_modules/puppeteer-core');
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const BASE = 'http://127.0.0.1:8787';
(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: 'new', args: ['--no-sandbox', '--disable-gpu'] });
  const p = await b.newPage();
  await p.setViewport({ width: 1600, height: 1000 });
  await p.goto(BASE + '/#home', { waitUntil: 'networkidle2' });
  await new Promise(r => setTimeout(r, 1200));
  const r = await p.evaluate(() => {
    const home = document.getElementById('view-home');
    const ids = ['homeAlerts', 'kpis', 'sellNextList', 'platChart', 'newsList', 'homeToday', 'histList', 'homeHead', 'homeSub', 'homeDate', 'homeSync', 'heroCard', 'heroMeta', 'kpiCard', 'alertsCard', 'chartCard', 'homeSellNext', 'sellNextMeta'];
    const o = {};
    ids.forEach(i => { const e = document.getElementById(i); o[i] = e ? { chars: e.innerText.trim().length, kids: e.children.length, w: Math.round(e.getBoundingClientRect().width), h: Math.round(e.getBoundingClientRect().height) } : null; });
    return { present: Object.keys(o).filter(k => o[k]).length, of: ids.length, o,
      homeChildren: home ? [...home.children].map(c => c.tagName.toLowerCase() + (c.id ? '#' + c.id : '') + (typeof c.className === 'string' && c.className ? '.' + c.className.split(' ')[0] : '') + ':' + c.innerText.trim().length) : null,
      homeText: home ? home.innerText.trim().length : null,
      mainText: document.querySelector('main').innerText.trim().length,
      cards: home ? home.querySelectorAll('.card').length : null };
  });
  console.log(JSON.stringify(r, null, 1));
  await b.close();
})();
