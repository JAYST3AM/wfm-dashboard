/* Stage 1 QA: prove the shared shell renders identically on all five pages, nothing was lost,
 * nothing overflows, and the page scripts still find their hooks.
 *
 *   node design/_stage1/qa_shell.js
 * Writes C:/Users/jayde/AppData/Local/Temp/shotkit/shots/shell-<page>.png and prints a report.
 */
'use strict';
const puppeteer = require('F:/VSC Projects/pb-bench/node_modules/puppeteer-core');
const fs = require('fs');
const path = require('path');

const BASE = 'http://127.0.0.1:8787';
const SHOTS = 'C:/Users/jayde/AppData/Local/Temp/shotkit/shots';
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const IDS_BEFORE = JSON.parse(fs.readFileSync(path.join(__dirname, 'ids_before.json'), 'utf8'));

const PAGES = [
  { name: 'index', url: '/', sub: 'local', active: null,
    acts: ['search', 'syncState', 'refresh', 'png', 'settingsBtn'], subnav: false, foot: '#foot' },
  { name: 'collection', url: '/collection.html', sub: 'collection log', active: 'collection',
    acts: [], subnav: true, foot: '.cl-foot' },
  { name: 'cards', url: '/cards.html', sub: 'mod cards', active: 'collection',
    acts: [], subnav: true, foot: '.mcd-foot' },
  { name: 'settings', url: '/settings.html', sub: 'settings', active: 'more',
    acts: [], subnav: true, foot: '.st-foot' },
  { name: 'item', url: '/item.html', sub: 'item price', active: null,
    acts: [], subnav: false, foot: null },
];

const PROBE = `(() => {
  window.__shell = { mountedReadyState: null, nulls: {} };
  const orig = Document.prototype.getElementById;
  Document.prototype.getElementById = function (id) {
    const el = orig.call(this, id);
    if (document.readyState === 'loading' && ['search','refresh','themeBtn','chips','syncState','themePanel','mainnav'].includes(id)) {
      window.__shell.nulls[id] = (window.__shell.nulls[id] || 0) + (el ? 0 : 1);
    }
    return el;
  };
  const obs = new MutationObserver(() => {
    if (!window.__shell.mountedReadyState && document.querySelector('body > header') && document.getElementById('mainnav')) {
      window.__shell.mountedReadyState = document.readyState;
    }
  });
  document.addEventListener('DOMContentLoaded', () => obs.observe(document.body, { childList: true, subtree: true }));
})();`;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const report = { pages: {}, fit: {}, errors: {} };

async function measure(browser, page, width, height) {
  await page.setViewport({ width, height });
  await sleep(250);
  return page.evaluate(() => {
    const de = document.documentElement;
    const overX = Math.max(de.scrollWidth - de.clientWidth, document.body.scrollWidth - window.innerWidth);
    const overY = Math.max(de.scrollHeight - de.clientHeight, document.body.scrollHeight - window.innerHeight);
    return { overX, overY, inner: [window.innerWidth, window.innerHeight], doc: [de.scrollWidth, de.scrollHeight] };
  });
}

(async () => {
  const browser = await puppeteer.launch({
    executablePath: CHROME, headless: 'new',
    args: ['--no-sandbox', '--disable-dev-shm-usage', '--window-size=1920,1080'],
  });
  for (const spec of PAGES) {
    const page = await browser.newPage();
    const errs = [];
    page.on('console', (m) => { if (m.type() === 'error') errs.push('console: ' + m.text()); });
    page.on('pageerror', (e) => errs.push('pageerror: ' + String(e.message || e)));
    page.on('requestfailed', (r) => errs.push('reqfail: ' + r.url() + ' ' + (r.failure() || {}).errorText));
    await page.evaluateOnNewDocument(PROBE);
    await page.setViewport({ width: 1920, height: 1080 });
    await page.goto(BASE + spec.url, { waitUntil: 'load', timeout: 30000 });
    await sleep(1500);

    const out = await page.evaluate((spec) => {
      const q = (s) => document.querySelector(s);
      const ids = [...document.querySelectorAll('[id]')].map((e) => e.id);
      const dups = ids.filter((v, i) => ids.indexOf(v) !== i);
      const rail = q('#mainnav');
      const pills = rail ? [...rail.querySelectorAll('.navpill')] : [];
      const active = pills.filter((p) => p.classList.contains('active'));
      const header = q('body > header');
      return {
        ids, dups,
        headerIsBodyChild: !!(header && header.parentElement === document.body),
        headerBeforeShellbody: !!(header && header.compareDocumentPosition(document.querySelector('.shellbody')) & Node.DOCUMENT_POSITION_FOLLOWING),
        railFirst: !!q('.shellbody > aside.side'),
        railIsRightPlace: rail ? rail.closest('.shellbody') !== null : false,
        pills: pills.map((p) => ({ v: p.dataset.v, t: p.textContent.trim(), href: p.getAttribute('href'),
                                   icon: p.dataset.icon, cur: p.getAttribute('aria-current') })),
        active: active.map((p) => p.dataset.v), activeCount: active.length,
        activeCur: active.map((p) => p.getAttribute('aria-current'))[0] || null,
        brand: q('.brand') ? q('.brand').textContent.replace(/\s+/g, ' ').trim() : null,
        brandInHeader: !!(header && q('.brand') && header.contains(q('.brand'))),
        chips: !!q('header #chips'),
        chipsText: q('#chips') ? q('#chips').textContent.replace(/\s+/g, ' ').trim() : null,
        search: !!q('header #search'), searchDrop: !!q('#searchDrop'),
        sounds: !!q('#soundBtn'), themeBtn: !!q('#themeBtn'), themePanel: !!q('#themePanel'),
        themeName: !!q('#themeName'), themeGrid: !!q('#themeGrid'),
        sync: !!q('#syncState'), refresh: !!q('#refresh'), png: !!q('#btnExportPng'),
        settingsLink: q('#settingsBtn') ? q('#settingsBtn').getAttribute('href') : null,
        subnav: (() => { const s = q('.shellcol > nav.mainnav.subnav');
          return s ? { inShellcol: true, pills: s.querySelectorAll('.navpill').length,
                       active: [...s.querySelectorAll('.navpill.active')].map((p) => p.dataset.v),
                       cur: [...s.querySelectorAll('.navpill[aria-current]')].map((p) => p.dataset.v) } : null; })(),
        foot: spec.foot && q(spec.foot) ? q(spec.foot).textContent.replace(/\s+/g, ' ').trim().slice(0, 80) : null,
        syncText: q('#syncState') ? q('#syncState').textContent.trim() : null,
        shellState: (window.wfmShell && window.wfmShell.mountedAt) || 'no-probe',
        shellNulls: window.__shell ? window.__shell.nulls : null,
        headerRect: header ? header.getBoundingClientRect().height : null,
        railRect: q('.side') ? q('.side').getBoundingClientRect().width : null,
      };
    }, spec);

    /* the theme panel: open, count the themes, check the filter row, close again */
    const theme = await page.evaluate(async () => {
      const btn = document.getElementById('themeBtn'), panel = document.getElementById('themePanel');
      btn.click();
      await new Promise((r) => setTimeout(r, 120));
      const open = !panel.classList.contains('hidden');
      const items = panel.querySelectorAll('.theme-item').length;
      const filter = [...panel.querySelectorAll('#themeFilter .tpf')].map((b) => b.textContent.trim());
      const first = panel.querySelector('.theme-item');
      const name = document.getElementById('themeName').textContent.trim();
      /* pick nothing - just close it again (no theme is applied) */
      btn.click();
      await new Promise((r) => setTimeout(r, 80));
      return { open, items, filter, firstTitle: first ? first.getAttribute('title') : null,
               name, closed: panel.classList.contains('hidden') };
    });

    /* the sound button: one click mutes, the next restores */
    const sound = await page.evaluate(async () => {
      const b = document.getElementById('soundBtn');
      const before = b.getAttribute('aria-pressed');
      b.click();
      await new Promise((r) => setTimeout(r, 60));
      const muted = { pressed: b.getAttribute('aria-pressed'), cls: b.classList.contains('muted'), title: b.title };
      b.click();
      await new Promise((r) => setTimeout(r, 60));
      const back = { pressed: b.getAttribute('aria-pressed'), cls: b.classList.contains('muted') };
      return { before, muted, back };
    });

    /* the global search (index only): type, expect the dropdown to fill from /api/catalog */
    let search = null;
    if (spec.acts.includes('search')) {
      await page.click('#search');
      await page.type('#search', 'primed continuity', { delay: 12 });
      await sleep(900);
      search = await page.evaluate(() => {
        const drop = document.getElementById('searchDrop');
        const rows = [...drop.querySelectorAll('button[data-slug]')];
        return { open: !drop.classList.contains('hidden'), rows: rows.length,
                 first: rows[0] ? rows[0].textContent.replace(/\s+/g, ' ').trim() : null,
                 aria: document.getElementById('search').getAttribute('aria-expanded') };
      });
      await page.evaluate(() => { document.getElementById('search').value = ''; document.getElementById('searchDrop').classList.add('hidden'); });
    }

    /* the pages' own local searches (collection #q / cards #q) still filter their grids */
    let localSearch = null;
    if (spec.name === 'collection' || spec.name === 'cards') {
      const before = await page.evaluate(() => ({ tiles: document.querySelectorAll('#grid > *').length }));
      await page.click('#q');
      await page.type('#q', spec.name === 'collection' ? 'prime' : 'primed', { delay: 12 });
      await sleep(900);
      localSearch = await page.evaluate((before) => ({
        before, after: document.querySelectorAll('#grid > *').length,
        meta: (document.getElementById('meta') || {}).textContent,
      }), before);
      await page.evaluate(() => {
        const q = document.getElementById('q');
        q.value = '';
        q.dispatchEvent(new Event('input', { bubbles: true }));
      });
    }

    const m1920 = await measure(browser, page, 1920, 1080);
    const m1366 = await measure(browser, page, 1366, 768);
    /* the rail's responsive fold: under 900px the rail is a row above the content, and the window
       still does not scroll sideways */
    const m820 = await measure(browser, page, 820, 900);
    const fold = await page.evaluate(() => {
      const side = document.querySelector('.side');
      const nav = document.getElementById('mainnav');
      const pills = [...nav.querySelectorAll('.navpill')].map((p) => p.getBoundingClientRect());
      const rows = new Set(pills.map((r) => Math.round(r.top))).size;
      const cs = getComputedStyle(side);
      return { flexDirection: getComputedStyle(document.querySelector('.shellbody')).flexDirection,
               sideTop: Math.round(side.getBoundingClientRect().top),
               mainTop: Math.round(document.querySelector('main').getBoundingClientRect().top),
               pillRows: rows, sideWidth: Math.round(side.getBoundingClientRect().width),
               sideOverflowX: side.scrollWidth - side.clientWidth, borderRight: cs.borderRightWidth };
    });
    await page.setViewport({ width: 1366, height: 768 });
    await sleep(200);
    await page.screenshot({ path: path.join(SHOTS, 'shell-' + spec.name + '.png') });
    await page.setViewport({ width: 1920, height: 1080 });
    await sleep(200);

    report.pages[spec.name] = { url: spec.url, ...out, theme, sound, search, localSearch, m1920, m1366, m820, fold };
    report.errors[spec.name] = errs;
    console.log('%s: pills=%d active=%s subnav=%s overflow1920=%s/%s overflow1366=%s/%s errs=%d',
      spec.name, out.pills.length, JSON.stringify(out.active), out.subnav ? out.subnav.pills : '-',
      m1920.overX, m1920.overY, m1366.overX, m1366.overY, errs.length);
    await page.close();
  }

  /* ---- index: the fit rules still hold on every view, at both sizes ---- */
  {
    const page = await browser.newPage();
    await page.setViewport({ width: 1920, height: 1080 });
    await page.goto(BASE + '/', { waitUntil: 'load' });
    await sleep(1500);
    for (const vp of [[1920, 1080], [1366, 768]]) {
      await page.setViewport({ width: vp[0], height: vp[1] });
      await sleep(250);
      const key = vp.join('x');
      report.fit[key] = {};
      for (const v of ['home', 'trade', 'inventory', 'mastery', 'player', 'more']) {
        await page.evaluate((v) => document.querySelector('#mainnav .navpill[data-v="' + v + '"]').click(), v);
        await sleep(450);
        report.fit[key][v] = await page.evaluate(() => {
          const de = document.documentElement;
          const sec = document.querySelector('main > section:not(.hidden)');
          const open = { home: 'home', trade: 'trade', inventory: 'inventory', mastery: 'mastery',
                         player: 'player', more: 'more' };
          const name = sec ? sec.id : null;
          const cards = [...(sec ? sec.querySelectorAll('.card') : [])];
          const wide = cards.filter((c) => c.scrollWidth > c.clientWidth + 1).map((c) => c.id || c.className);
          return {
            view: name,
            pageOverX: Math.max(de.scrollWidth - de.clientWidth, document.body.scrollWidth - window.innerWidth),
            pageOverY: Math.max(de.scrollHeight - de.clientHeight, document.body.scrollHeight - window.innerHeight),
            secOverX: sec ? Math.max(0, sec.scrollWidth - sec.clientWidth) : null,
            secOverY: sec ? Math.max(0, sec.scrollHeight - sec.clientHeight) : null,
            scrollers: sec ? sec.querySelectorAll('[class*="scrolly"]').length : null,
            firstCard: cards.length ? cards[0].getBoundingClientRect().top : null,
            wideCards: wide.slice(0, 4), open,
          };
        });
      }
    }
    await page.evaluate(() => document.querySelector('#mainnav .navpill[data-v="home"]').click());
    await page.setViewport({ width: 1366, height: 768 });
    await sleep(400);
    await page.screenshot({ path: path.join(SHOTS, 'shell-index-home.png'), fullPage: false });
    await page.close();
  }

  await browser.close();
  fs.writeFileSync(path.join(__dirname, 'qa_shell.json'), JSON.stringify(report, null, 1));
  const fitLine = Object.entries(report.fit).map(([k, views]) =>
    k + ' ' + Object.entries(views).map(([v, m]) => v + ':' + m.pageOverX + '/' + m.pageOverY).join(' ')).join(' | ');
  console.log('FIT ' + fitLine);
  console.log('STAGE1 QA DONE');
})().catch((e) => { console.error('QA FAILED', e); process.exit(1); });
