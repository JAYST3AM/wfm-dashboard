/* Debug: why does a hard load of /#trade leave aria-current on Home? */
'use strict';
const puppeteer = require('F:/VSC Projects/pb-bench/node_modules/puppeteer-core');
(async () => {
  const b = await puppeteer.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: 'new', args: ['--no-sandbox'] });
  const p = await b.newPage();
  const early = [];
  p.on('console', m => { if (m.type() === 'error' || m.type() === 'warning') early.push(m.text().slice(0, 200)); });
  p.on('pageerror', e => early.push('ERR ' + e.message));
  for (const u of ['http://127.0.0.1:8787/?x=1#trade', 'http://127.0.0.1:8787/#inventory', 'http://127.0.0.1:8787/?x=1#tools/deals']) {
    await p.goto(u, { waitUntil: 'networkidle2' });
    await new Promise(r => setTimeout(r, 600));
    const r = await p.evaluate(() => ({
      url: location.href, hash: location.hash,
      hashView: window.wfmShell && window.wfmShell.hashView(),
      mountedAt: window.wfmShell && window.wfmShell.mountedAt,
      rail: [...document.querySelectorAll('#mainnav .navpill')].map(x => x.dataset.v + (x.classList.contains('active') ? '*' : '') + (x.getAttribute('aria-current') ? '[cur]' : '')),
      railHTML: window.wfmShell && window.wfmShell.railHTML(window.wfmShell.PAGES.index).slice(0, 150),
      state: { viewHome: !document.getElementById('view-home').classList.contains('hidden'),
        viewTrade: !document.getElementById('view-trade').classList.contains('hidden'),
        viewInv: !document.getElementById('view-inventory').classList.contains('hidden'),
        viewTools: !document.getElementById('view-tools').classList.contains('hidden') },
      dataShell: document.body.getAttribute('data-shell'),
      bodyFirstChild: document.body.firstElementChild.tagName + '.' + document.body.firstElementChild.className.slice(0, 30),
    }));
    console.log(u, JSON.stringify(r, null, 1));
  }
  console.log('console:', early);
  await b.close();
})();
