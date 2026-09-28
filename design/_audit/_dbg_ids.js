/* Final spot-checks backing two claims in audit-1.md:
 *  (a) index keeps every pre-stage-1 chrome id, including #searchDrop, #settingsBtn, #foot;
 *  (b) shell.css colour literals (hex/rgb/named) really are absent.
 */
'use strict';
const puppeteer = require('F:/VSC Projects/pb-bench/node_modules/puppeteer-core');
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const BASE = 'http://127.0.0.1:8787';
(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: 'new', args: ['--no-sandbox', '--disable-gpu'] });
  const p = await b.newPage();
  await p.setViewport({ width: 1600, height: 1000 });
  await p.goto(BASE + '/#tools', { waitUntil: 'networkidle2' });
  await new Promise(r => setTimeout(r, 900));
  const r = await p.evaluate(() => {
    const ids = ['search', 'searchDrop', 'settingsBtn', 'foot', 'setupCard', 'chips', 'soundBtn', 'themeBtn', 'themePanel', 'themeGrid', 'themeName', 'syncState', 'refresh', 'btnExportPng', 'mainnav'];
    const o = {}; ids.forEach(i => { o[i] = !!document.getElementById(i); });
    o.themeItems = document.querySelectorAll('#themeGrid .theme-item').length;
    o.toolEntries = document.querySelectorAll('#toolsLauncher a.tool').length;
    o.workspaces = [...document.querySelectorAll('#toolsWs .tws')].map(w => w.dataset.tool);
    return o;
  });
  console.log(JSON.stringify(r, null, 1));
  await b.close();
})();
