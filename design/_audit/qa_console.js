/* Audit-1 check 6: every console error / failed request per page, with stack + source file, so
 * each one can be attributed (probe vs app) and classified pre-existing vs new.
 *   node design/_audit/qa_console.js
 */
'use strict';
const puppeteer = require('F:/VSC Projects/pb-bench/node_modules/puppeteer-core');
const fs = require('fs');
const path = require('path');

const BASE = 'http://127.0.0.1:8787';
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const TARGETS = [
  ['index#home', '/#home'], ['index#trade', '/#trade'], ['index#inventory', '/#inventory'],
  ['index#tools', '/#tools'], ['index#tools/deals', '/#tools/deals'],
  ['index#tools/player', '/#tools/player'], ['index#tools/news', '/#tools/news'],
  ['collection', '/collection.html'], ['collection#mastery', '/collection.html#mastery'],
  ['collection#relics', '/collection.html#relics'],
  ['cards', '/cards.html'], ['settings', '/settings.html'], ['settings#trading', '/settings.html#trading'],
  ['item', '/item.html'], ['lookup', '/lookup.html'],
];

(async () => {
  const browser = await puppeteer.launch({ executablePath: CHROME, headless: 'new', args: ['--no-sandbox', '--disable-gpu'] });
  const page = await browser.newPage();
  await page.setViewport({ width: 1600, height: 1000 });
  const out = {};
  let errs, failed, http;
  const reset = () => { errs = []; failed = []; http = []; };
  reset();
  page.on('pageerror', e => errs.push({ kind: 'pageerror', text: String(e.message || e).slice(0, 200), stack: String(e.stack || '').split('\n').slice(0, 4).join(' | ').slice(0, 500) }));
  page.on('console', m => { if (m.type() === 'error') errs.push({ kind: 'console', text: m.text().slice(0, 200), loc: (m.location() || {}).url ? m.location().url + ':' + m.location().lineNumber : '' }); });
  page.on('requestfailed', r => failed.push({ url: r.url(), err: (r.failure() || {}).errorText }));
  page.on('response', r => { if (r.status() >= 400) http.push({ url: r.url(), status: r.status() }); });

  for (const [name, url] of TARGETS) {
    reset();
    await page.goto(BASE + url, { waitUntil: 'networkidle2', timeout: 40000 });
    await new Promise(r => setTimeout(r, 1200));
    /* exercise the view: apply a light theme (flushes theme paths) and click a tool entry */
    const extra = await page.evaluate(() => {
      const before = { hash: location.hash };
      try { window.wfmApplyTheme && window.wfmApplyTheme(14); } catch (e) { return { err: 'theme:' + e.message }; }
      return before;
    });
    await new Promise(r => setTimeout(r, 400));
    await page.evaluate(() => { try { window.wfmApplyTheme && window.wfmApplyTheme(0); } catch (e) {} });
    out[name] = { url, errs, failed, http, extra };
    console.log(`\n== ${name} (${url}) errs=${errs.length} failedRequests=${failed.length} http>=400=${http.length}`);
    errs.forEach(e => console.log('   ', JSON.stringify(e)));
    failed.slice(0, 8).forEach(f => console.log('    FAILED', f.err, f.url.slice(0, 120)));
    http.slice(0, 8).forEach(f => console.log('    HTTP', f.status, f.url.slice(0, 120)));
  }
  fs.writeFileSync(path.join(__dirname, 'console.json'), JSON.stringify(out, null, 1));
  console.log('\nwritten design/_audit/console.json');
  await browser.close();
})().catch(e => { console.error('PROBE FAILED', e); process.exit(1); });
