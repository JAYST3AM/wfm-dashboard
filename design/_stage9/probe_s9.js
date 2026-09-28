/* Stage 9 probe: the drawer's one path into the full analysis page, and the deep link on load.
 *
 *   node probe_s9.js
 *
 * Read-only: it clicks one inventory row (that only opens the drawer) and loads item.html with and
 * without the deep link. Writes s9-drawer.png + s9-item-analysis.png into the shotkit folder.
 */
'use strict';
const puppeteer = require('F:/VSC Projects/pb-bench/node_modules/puppeteer-core');
const fs = require('fs');
const path = require('path');

const BASE = 'http://127.0.0.1:8787';
const SHOTS = 'C:/Users/jayde/AppData/Local/Temp/shotkit/shots';
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const OUT = path.join(process.env.TMPDIR || '.', 'probe_s9.json');
const PREEXISTING = /cdn\.warframestat\.us|api\.warframe\.market|wfcd/i;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const result = {};

async function newPage(browser, errs) {
  const p = await browser.newPage();
  await p.setViewport({ width: 1920, height: 1080 });
  p.on('console', (m) => { if (m.type() === 'error') errs.push('console: ' + m.text()); });
  p.on('pageerror', (e) => errs.push('pageerror: ' + String(e.message || e)));
  p.on('requestfailed', (r) => {
    const u = r.url();
    if (!PREEXISTING.test(u)) errs.push('requestfailed: ' + u + ' ' + (r.failure() || {}).errorText);
  });
  return p;
}

(async () => {
  const browser = await puppeteer.launch({
    executablePath: CHROME, headless: 'new',
    args: ['--no-sandbox', '--disable-dev-shm-usage', '--window-size=1920,1080'],
  });

  /* ---------- (a) the drawer, opened from a plain inventory row click ---------- */
  {
    const errs = [];
    const p = await newPage(browser, errs);
    await p.goto(BASE + '/#inventory', { waitUntil: 'load' });
    await sleep(2500);
    const rows = await p.evaluate(() => document.querySelectorAll('#rows .inv-row[data-slug]').length);
    const picked = await p.evaluate(() => {
      const all = [...document.querySelectorAll('#rows .inv-row[data-slug]')];
      const want = all.find((r) => r.dataset.slug === 'hildryn_prime_chassis_blueprint')
        || all.find((r) => r.dataset.slug === 'true_steel') || all[0];
      if (!want) return null;
      want.click();
      return want.dataset.slug;
    });
    await sleep(2200);
    const drawer = await p.evaluate(() => {
      const panel = document.querySelector('.dw-panel');
      const act = document.querySelector('.dw-foot .dw-full');
      const role = document.querySelector('.dw-foot .dw-role');
      const anchors = [...document.querySelectorAll('.dw-panel a')].map((a) => ({
        text: a.textContent.trim(), href: a.getAttribute('href'), cls: a.className,
      }));
      return {
        open: !!panel, name: (document.getElementById('wfmDrawerName') || {}).textContent,
        role: role ? role.textContent.trim() : null,
        roleCount: document.querySelectorAll('.dw-role').length,
        action: act ? { text: act.textContent.trim(), href: act.getAttribute('href'),
                        tag: act.tagName, dataDw: act.getAttribute('data-dw'),
                        classes: act.className, hidden: act.classList.contains('dw-hidden') } : null,
        primaries: [...document.querySelectorAll('.dw-foot .btn')].filter((b) => b.classList.contains('primary')).map((b) => b.textContent.trim()),
        anchors,
        actionCount: document.querySelectorAll('.dw-foot .dw-full').length,
      };
    });
    await p.screenshot({ path: path.join(SHOTS, 's9-drawer.png') });
    result.drawerFromInventory = { rows, pickedSlug: picked, ...drawer, errors: errs };
    await p.close();
  }

  /* ---------- (b) item.html via the deep link, plus the no-parameter default ---------- */
  const slug = (result.drawerFromInventory.action || {}).href || '';
  const wantSlug = result.drawerFromInventory.pickedSlug;
  {
    const errs = [];
    const p = await newPage(browser, errs);
    await p.goto(BASE + '/item.html?item=' + encodeURIComponent(wantSlug), { waitUntil: 'load' });
    await sleep(2600);
    const page = await p.evaluate(() => {
      const vis = (id) => {
        const n = document.getElementById(id);
        return n ? !n.classList.contains('hidden') : null;
      };
      const c = document.getElementById('ipChart');
      return {
        url: location.pathname + location.search,
        title: document.getElementById('ipTitle').textContent.trim(),
        lead: document.getElementById('ipLead').textContent.trim(),
        role: document.getElementById('ipRole').textContent.trim(),
        pickCardVisible: vis('ipPickCard'), chartCard: vis('ipChartCard'),
        statsCard: vis('ipStatsCard'), tradesCard: vis('ipTradesCard'),
        chips: document.querySelectorAll('#ipChips .ip-chip').length,
        statRows: document.querySelectorAll('#ipStats tr').length,
        tradeRows: document.querySelectorAll('#ipTrades tr').length,
        meta: document.getElementById('ipMeta').textContent.trim(),
        canvas: c ? [c.width, c.height] : null,
        views: document.querySelectorAll('#ipViews .chartbtn').length,
      };
    });
    await p.screenshot({ path: path.join(SHOTS, 's9-item-analysis.png') });
    result.deepLink = { ...page, errors: errs };
    await p.close();
  }

  /* ---------- (b2) the hash form, and the legacy ?slug= form ---------- */
  for (const [name, url] of [['hash', '/item.html#item=' + encodeURIComponent(wantSlug)],
                             ['legacy', '/item.html?slug=' + encodeURIComponent(wantSlug)]]) {
    const errs = [];
    const p = await newPage(browser, errs);
    await p.goto(BASE + url, { waitUntil: 'load' });
    await sleep(2000);
    result[name] = await p.evaluate(() => ({
      title: document.getElementById('ipTitle').textContent.trim(),
      lead: document.getElementById('ipLead').textContent.trim(),
      pickCardVisible: !document.getElementById('ipPickCard').classList.contains('hidden'),
    }));
    result[name].errors = errs;
    await p.close();
  }

  /* ---------- (b2b) a second item through the drawer: the ranked-mod path ---------- */
  {
    const errs = [];
    const p = await newPage(browser, errs);
    await p.goto(BASE + '/#inventory', { waitUntil: 'load' });
    await sleep(2500);
    const picked = await p.evaluate(async () => {
      const all = [...document.querySelectorAll('#rows .inv-row[data-slug]')];
      const want = all.find((r) => r.dataset.slug === 'true_steel') || all[0];
      if (!want) return null;
      want.click();
      return want.dataset.slug;
    });
    await sleep(2200);
    result.secondItem = { pickedSlug: picked, ...(await p.evaluate(() => {
      const act = document.querySelector('.dw-foot .dw-full');
      return { name: (document.getElementById('wfmDrawerName') || {}).textContent,
        actionHref: act ? act.getAttribute('href') : null,
        actionText: act ? act.textContent.trim() : null,
        primaries: document.querySelectorAll('.dw-foot .btn.primary').length };
    })), errors: errs };
    await p.close();
  }

  /* ---------- (b3) no parameter at all: the picker, unchanged ---------- */
  {
    const errs = [];
    const p = await newPage(browser, errs);
    await p.goto(BASE + '/item.html', { waitUntil: 'load' });
    await sleep(2200);
    result.noParam = await p.evaluate(() => {
      const links = [...document.querySelectorAll('#ipList a')].map((a) => a.getAttribute('href'));
      return {
        pickCardVisible: !document.getElementById('ipPickCard').classList.contains('hidden'),
        chartCardHidden: document.getElementById('ipChartCard').classList.contains('hidden'),
        listLinks: links.length, firstLink: links[0] || null,
        canonical: links.every((h) => h.startsWith('/item.html?item=')),
        title: document.getElementById('ipTitle').textContent.trim(),
        lead: document.getElementById('ipLead').textContent.trim(),
      };
    });
    result.noParam.errors = errs;
    await p.close();
  }

  await browser.close();
  fs.writeFileSync(OUT, JSON.stringify(result, null, 1));
  console.log(JSON.stringify(result, null, 1));
  console.log('--- wrote ' + OUT);
})();
