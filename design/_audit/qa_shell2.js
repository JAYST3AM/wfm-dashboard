/* Audit-1 check 2b: theme panel contents per page, rail hrefs per page, pill focus outline.
 *   node design/_audit/qa_shell2.js   ->  design/_audit/shell2.json
 */
'use strict';
const puppeteer = require('F:/VSC Projects/pb-bench/node_modules/puppeteer-core');
const fs = require('fs');
const path = require('path');
const BASE = 'http://127.0.0.1:8787';
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const PAGES = [['index', '/#home'], ['collection', '/collection.html'], ['cards', '/cards.html'], ['settings', '/settings.html'], ['item', '/item.html']];
const sleep = ms => new Promise(r => setTimeout(r, ms));
(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: 'new', args: ['--no-sandbox', '--disable-gpu'] });
  const p = await b.newPage();
  await p.setViewport({ width: 1600, height: 1000 });
  const out = {};
  for (const [name, url] of PAGES) {
    await p.goto(BASE + url, { waitUntil: 'networkidle2' });
    await sleep(500);
    /* keyboard focus the first pill to read its outline */
    await p.evaluate(() => { const a = document.querySelector('#mainnav .navpill'); if (a) a.focus(); });
    const r = await p.evaluate(() => {
      const btn = document.getElementById('themeBtn'), panel = document.getElementById('themePanel');
      btn.click();
      const items = document.querySelectorAll('#themeGrid .theme-item').length;
      const filters = [...document.querySelectorAll('#themeFilter .tpf')].map(f => f.textContent.trim() + (f.classList.contains('on') ? '*' : ''));
      const open = !panel.classList.contains('hidden');
      btn.click();
      const closed = panel.classList.contains('hidden');
      const focused = document.querySelector('#mainnav .navpill');
      const cs = focused ? getComputedStyle(focused) : null;
      return { panelOpens: open, closes: closed, items, filters,
        railHrefs: [...document.querySelectorAll('#mainnav .navpill')].map(a => a.dataset.v + '=' + a.getAttribute('href')),
        subHrefs: [...document.querySelectorAll('nav.mainnav.subnav .navpill, nav.subnav .navpill')].map(a => (a.dataset.v || a.textContent.trim()) + '=' + a.getAttribute('href')),
        pillFocusOutline: cs ? cs.outlineStyle + ' ' + cs.outlineWidth + ' ' + cs.outlineColor : null,
        themeBtnAria: btn.getAttribute('aria-expanded'), panelRole: panel.getAttribute('role'),
        gridScrollable: (() => { const g = document.getElementById('themeGrid'); return g ? g.scrollHeight + '/' + g.clientHeight : null; })() };
    });
    out[name] = r;
    console.log(`${name.padEnd(11)} panelOpens=${r.panelOpens} closesOnSecondClick=${r.closes} themeItems=${r.items} filters=${JSON.stringify(r.filters)} ` +
      `pillOutline=${r.pillFocusOutline} gridScroll=${r.gridScrollable}`);
    console.log(`   rail: ${r.railHrefs.join(' ')}`);
    if (r.subHrefs.length) console.log(`   sub:  ${r.subHrefs.join(' ')}`);
  }
  fs.writeFileSync(path.join(__dirname, 'shell2.json'), JSON.stringify(out, null, 1));
  console.log('written design/_audit/shell2.json');
  await b.close();
})().catch(e => { console.error('PROBE FAILED', e); process.exit(1); });
