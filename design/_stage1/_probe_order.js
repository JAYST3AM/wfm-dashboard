/* stage-1 QA: (1) is the warframe.market image block the CDN's own policy? (2) what readyState
 * does shell.js mount at, and does every page script's pre-DOMContentLoaded lookup hit its hook? */
const puppeteer = require('F:/VSC Projects/pb-bench/node_modules/puppeteer-core');
const PROBE = `(() => {
  window.__shell = { nulls: {}, lookups: {} };
  const orig = Document.prototype.getElementById;
  Document.prototype.getElementById = function (id) {
    const el = orig.call(this, id);
    if (document.readyState === 'loading' &&
        ['search','refresh','themeBtn','chips','syncState','themePanel','mainnav','searchDrop'].includes(id)) {
      window.__shell.lookups[id] = (window.__shell.lookups[id] || 0) + 1;
      if (!el) window.__shell.nulls[id] = (window.__shell.nulls[id] || 0) + 1;
    }
    return el;
  };
})();`;

(async () => {
  const b = await puppeteer.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: 'new', args: ['--no-sandbox'] });

  /* (1) the bare image, no shell anywhere on the page */
  {
    const p = await b.newPage();
    const errs = [];
    p.on('console', (m) => { if (m.type() === 'error') errs.push(m.text()); });
    p.on('requestfailed', (r) => errs.push('reqfail ' + r.url().split('/').pop()));
    await p.goto('http://127.0.0.1:8787/_qa_img_probe.html', { waitUntil: 'load' });
    await new Promise((r) => setTimeout(r, 1200));
    console.log('bare <img> page (no shell, no cards.js):', JSON.stringify(errs));
    await p.close();
  }

  /* (2) ordering + parse-time lookups, per page */
  for (const u of ['/', '/collection.html', '/cards.html', '/settings.html', '/item.html']) {
    const p = await b.newPage();
    await p.evaluateOnNewDocument(PROBE);
    await p.goto('http://127.0.0.1:8787' + u, { waitUntil: 'load' });
    await new Promise((r) => setTimeout(r, 900));
    const out = await p.evaluate(() => ({
      mountedAt: window.wfmShell.mountedAt,
      mounted: window.wfmShell.mounted,
      lookupsBeforeScripts: window.__shell.lookups,
      nulls: window.__shell.nulls,
      bodyOrder: [...document.body.children].map((e) => e.tagName).slice(0, 5),
      shellbodyOrder: [...document.querySelector('.shellbody').children].map((e) => e.tagName + (e.className ? '.' + e.className.split(' ')[0] : '')).slice(0, 3),
    }));
    console.log(u, JSON.stringify(out));
    await p.close();
  }
  await b.close();
})();
