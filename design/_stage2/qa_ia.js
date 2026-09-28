/* Stage 2 QA: the rebuilt primary navigation, the Tools launcher + workspaces, Mastery inside
 * Collection, and the legacy hashes - measured headlessly.
 *
 *   node design/_stage2/qa_ia.js
 *
 * Writes C:/Users/jayde/AppData/Local/Temp/shotkit/shots/ia-*.png and design/_stage2/qa_ia.json,
 * then prints the numbers the stage is judged on (console errors, rail per page, index fit,
 * click-through of every tool workspace, the rendered id union vs stage 1's snapshot).
 */
'use strict';
const puppeteer = require('F:/VSC Projects/pb-bench/node_modules/puppeteer-core');
const fs = require('fs');
const path = require('path');

const BASE = 'http://127.0.0.1:8787';
const SHOTS = 'C:/Users/jayde/AppData/Local/Temp/shotkit/shots';
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const IDS_BEFORE = JSON.parse(fs.readFileSync(path.join(__dirname, '..', '_stage1', 'ids_before.json'), 'utf8'));
/* cards.html paints card art from the WFCD image CDN, which is blocked on this PC - that one
   request failure is pre-existing and not this stage's business (it was already the only error
   the stage 1 run reported for cards). */
const PREEXISTING = /cdn\.warframestat\.us|api\.warframe\.market|wfcd/i;

const RAIL = [['home', '#home', 'Home'], ['trade', '#trade', 'Trade'],
  ['inventory', '#inventory', 'Inventory'], ['collection', '/collection.html', 'Collection'],
  ['tools', '#tools', 'Tools'], ['settings', '/settings.html', 'Settings']];
const TOOLS = ['deals', 'trends', 'rivens', 'wl', 'ducats', 'craft', 'relicev', 'sets', 'baro',
  'meta', 'player', 'dojo'];            /* stage 5 (2026-09-28): the Clan Dojo card moved off
                                           Inventory into a workspace of its own */
const TOOL_LIST_IDS = {
  deals: ['dealsList'], trends: ['moversList', 'trendsList'], rivens: ['rivensList'],
  wl: ['wlList'], ducats: ['ducatsList'], craft: ['craftList'], relicev: ['relicsList'],
  sets: ['setsList', 'nudgesList'], baro: ['baroList'], meta: ['metaList'],
  player: ['pcHead', 'pcStats', 'pcTop', 'pcSyn', 'pcInt', 'pcFocus', 'pcMarket'],
  dojo: ['dojoTbl', 'dojoRows'],
};

const PAGES = [
  { name: 'index', url: '/', active: 'home' },
  { name: 'collection', url: '/collection.html', active: 'collection' },
  { name: 'cards', url: '/cards.html', active: 'collection' },
  { name: 'settings', url: '/settings.html', active: 'settings' },
  { name: 'item', url: '/item.html', active: null },
];

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const report = { pages: {}, errors: {}, fit: {}, tools: {}, legacy: {}, collection: {}, ids: {} };

function grab(page) {
  return page.evaluate(() => {
    const ids = [...document.querySelectorAll('[id]')].map((e) => e.id);
    return { ids, dups: ids.filter((v, i) => ids.indexOf(v) !== i) };
  });
}

async function measure(browser, page, width, height) {
  await page.setViewport({ width, height });
  await sleep(300);
  return page.evaluate(() => {
    const de = document.documentElement;
    return {
      overX: Math.max(de.scrollWidth - de.clientWidth, document.body.scrollWidth - window.innerWidth),
      overY: Math.max(de.scrollHeight - de.clientHeight, document.body.scrollHeight - window.innerHeight),
      doc: [de.scrollWidth, de.scrollHeight],
    };
  });
}

(async () => {
  const browser = await puppeteer.launch({
    executablePath: CHROME, headless: 'new',
    args: ['--no-sandbox', '--disable-dev-shm-usage', '--window-size=1920,1080'],
  });

  /* ---------------- (a) every page: rail + errors + the <=900px fold ---------------- */
  for (const spec of PAGES) {
    const page = await browser.newPage();
    const errs = [];
    page.on('console', (m) => { if (m.type() === 'error') errs.push('console: ' + m.text()); });
    page.on('pageerror', (e) => errs.push('pageerror: ' + String(e.message || e)));
    page.on('requestfailed', (r) => {
      const u = r.url();
      if (!PREEXISTING.test(u)) errs.push('reqfail: ' + u + ' ' + (r.failure() || {}).errorText);
    });
    await page.setViewport({ width: 1920, height: 1080 });
    await page.goto(BASE + spec.url, { waitUntil: 'load', timeout: 30000 });
    await sleep(2000);

    const out = await page.evaluate((spec) => {
      const pills = [...document.querySelectorAll('#mainnav .navpill')];
      const active = pills.filter((p) => p.classList.contains('active'));
      return {
        pills: pills.map((p) => ({ v: p.dataset.v, t: p.textContent.trim(), href: p.getAttribute('href'),
                                   icon: p.dataset.icon, cur: p.getAttribute('aria-current') })),
        active: active.map((p) => p.dataset.v), activeCount: active.length,
        railFirst: !!document.querySelector('.shellbody > aside.side'),
        subnav: (() => { const s = document.querySelector('.shellcol > nav.mainnav.subnav');
          return s ? { pills: [...s.querySelectorAll('.navpill')].map((p) => [p.dataset.v, p.getAttribute('href'), p.classList.contains('active')]) } : null; })(),
        bodyBg: getComputedStyle(document.body).backgroundColor,
      };
    }, spec);
    const ids = await grab(page);
    const m1920 = await measure(browser, page, 1920, 1080);
    /* the rail's fold: under 900px it is a row above the content and the window still does not
       scroll sideways */
    const m820 = await measure(browser, page, 820, 900);
    const fold = await page.evaluate(() => {
      const side = document.querySelector('.side');
      const pills = [...document.querySelectorAll('#mainnav .navpill')].map((p) => p.getBoundingClientRect());
      return {
        flexDirection: getComputedStyle(document.querySelector('.shellbody')).flexDirection,
        sideTop: Math.round(side.getBoundingClientRect().top),
        mainTop: Math.round(document.querySelector('main').getBoundingClientRect().top),
        pillRows: new Set(pills.map((r) => Math.round(r.top))).size,
        sideOverflowX: side.scrollWidth - side.clientWidth,
        sideW: Math.round(side.getBoundingClientRect().width),
      };
    });
    await page.setViewport({ width: 1920, height: 1080 });
    await sleep(250);

    report.pages[spec.name] = { url: spec.url, ...out, m1920, m820, fold, ids: ids.ids, dups: ids.dups };
    report.errors[spec.name] = errs;
    const ok = out.active.join(',') === (spec.active || '');
    console.log([spec.name.padEnd(11), 'pills=' + out.pills.length,
      'active=' + JSON.stringify(out.active) + (ok ? '' : ' WANT ' + spec.active),
      'errs=' + errs.length, 'overX@1920=' + m1920.overX, 'overX@820=' + m820.overX,
      'fold=' + fold.flexDirection, 'pillRows=' + fold.pillRows,
      'sideTop<mainTop=' + (fold.sideTop < fold.mainTop)].join(' '));
    await page.close();
  }

  /* ---------------- (b) index fit + (c) every tool workspace, clicked ---------------- */
  {
    const page = await browser.newPage();
    const errs = [];
    page.on('console', (m) => { if (m.type() === 'error') errs.push('console: ' + m.text()); });
    page.on('pageerror', (e) => errs.push('pageerror: ' + String(e.message || e)));
    await page.setViewport({ width: 1920, height: 1080 });
    await page.goto(BASE + '/', { waitUntil: 'load' });
    await sleep(2200);

    /* stage 5: five sizes, and both inventory subviews - the materials panel is a panel of its
       own now and has to measure clean at every width, not just the one the items table sees */
    for (const vp of [[1920, 1080], [1536, 864], [1440, 900], [1366, 768], [1280, 800]]) {
      const key = vp.join('x');
      report.fit[key] = {};
      await page.setViewport({ width: vp[0], height: vp[1] });
      await sleep(300);
      for (const v of ['home', 'trade', 'inventory', 'tools']) {
        await page.evaluate((v) => document.querySelector('#mainnav .navpill[data-v="' + v + '"]').click(), v);
        await sleep(500);
        report.fit[key][v] = await page.evaluate(() => {
          const de = document.documentElement;
          const sec = document.querySelector('main > section:not(.hidden)');
          return {
            view: sec ? sec.id : null,
            pageOverX: Math.max(de.scrollWidth - de.clientWidth, document.body.scrollWidth - window.innerWidth),
            pageOverY: Math.max(de.scrollHeight - de.clientHeight, document.body.scrollHeight - window.innerHeight),
            secOverX: sec ? Math.max(0, sec.scrollWidth - sec.clientWidth) : null,
          };
        });
      }
      await page.evaluate(() => document.querySelector('#invViews [role="tab"][data-v="materials"]').click());
      await sleep(450);
      report.fit[key]['inventory/materials'] = await page.evaluate(() => {
        const de = document.documentElement;
        const sec = document.querySelector('main > section:not(.hidden)');
        return {
          view: sec ? sec.id : null,
          pageOverX: Math.max(de.scrollWidth - de.clientWidth, document.body.scrollWidth - window.innerWidth),
          pageOverY: Math.max(de.scrollHeight - de.clientHeight, document.body.scrollHeight - window.innerHeight),
          secOverX: sec ? Math.max(0, sec.scrollWidth - sec.clientWidth) : null,
        };
      });
      await page.evaluate(() => document.querySelector('#invViews [role="tab"][data-v="items"]').click());
      await sleep(200);
    }
    console.log('FIT ' + Object.entries(report.fit).map(([k, views]) =>
      k + ' ' + Object.entries(views).map(([v, m]) => v + ':' + m.pageOverX + '/' + m.pageOverY).join(' ')).join(' | '));

    /* click-through: the rail pill, then every launcher entry (a real click on a real link) */
    await page.setViewport({ width: 1920, height: 1080 });
    await sleep(300);
    await page.evaluate(() => document.querySelector('#mainnav .navpill[data-v="tools"]').click());
    await sleep(600);
    report.tools.launcher = await page.evaluate(() => ({
      hash: location.hash,
      entries: [...document.querySelectorAll('#toolsLauncher .tool')].map((a) => [a.dataset.tool, a.getAttribute('href')]),
      groups: [...document.querySelectorAll('#toolsLauncher .tl-ghead')].map((d) => d.textContent.trim()),
      launcherVisible: !document.getElementById('toolsLauncher').classList.contains('hidden'),
      workspacesVisible: [...document.querySelectorAll('#toolsWs .tws')].filter((e) => !e.classList.contains('hidden')).map((e) => e.dataset.tool),
      setup: [...document.querySelectorAll('#setupCard a')].map((a) => a.getAttribute('href')),
      foot: !!document.getElementById('foot'),
    }));
    report.tools.slugs = {};
    for (const slug of TOOLS) {
      /* every tool is entered FROM THE LAUNCHER (that is the interaction the brief describes), so
         go back to the launcher first, then click the entry. A real mouse click on a real link; if
         Chrome refuses the clickable point, the same navigation is dispatched from the DOM and
         flagged, never hidden. */
      await page.evaluate(() => { location.hash = '#tools'; });
      await sleep(350);
      let how = 'real';
      try {
        const entry = await page.$('#toolsLauncher a.tool[data-tool="' + slug + '"]');
        if (!entry) throw new Error('no launcher entry');
        await entry.scrollIntoViewIfNeeded();
        await entry.click();
      } catch (e) {
        how = 'dom';
        await page.evaluate((s) => { document.querySelector('#toolsLauncher a.tool[data-tool="' + s + '"]').click(); }, slug);
      }
      await sleep(650);
      report.tools.slugs[slug] = await page.evaluate((slug) => {
        const el = document.querySelector('#toolsWs [data-tool="' + slug + '"]');
        return { hash: location.hash, visible: el ? !el.classList.contains('hidden') : false,
          onlyOne: [...document.querySelectorAll('#toolsWs .tws')].filter((e) => !e.classList.contains('hidden')).length,
          launcherHidden: document.getElementById('toolsLauncher').classList.contains('hidden'),
          rows: el ? [...el.querySelectorAll('[id$="List"], [id^="pc"]')].map((b) => [b.id, b.children.length]) : [],
          secVisible: !document.getElementById('view-tools').classList.contains('hidden'),
          pageOverY: document.documentElement.scrollHeight - document.documentElement.clientHeight };
      }, slug);
      /* the back link works: the launcher returns (checked once, on the first workspace) */
      if (slug === TOOLS[0]) {
        await page.click('#toolsWs .tws[data-tool="deals"] .tws-back');
        await sleep(400);
        report.tools.backToLauncher = await page.evaluate(() => ({
          hash: location.hash,
          launcherVisible: !document.getElementById('toolsLauncher').classList.contains('hidden'),
          workspacesVisible: [...document.querySelectorAll('#toolsWs .tws')].filter((e) => !e.classList.contains('hidden')).length,
        }));
      }
      report.tools.slugs[slug].clicked = how;
      if (slug === 'deals') fs.writeFileSync(path.join(SHOTS, 'ia-tools-deals.png'), await page.screenshot());
    }
    /* the launcher screenshot, taken after the round-trip (the back link is above) */
    await page.evaluate(() => { location.hash = '#tools'; });
    await sleep(600);
    fs.writeFileSync(path.join(SHOTS, 'ia-launcher.png'), await page.screenshot());

    /* the tool list ids really carry rows (the renderers still fill them) */
    for (const [slug, ids] of Object.entries(TOOL_LIST_IDS)) {
      await page.evaluate((s) => { location.hash = '#tools/' + s; }, slug);
      await sleep(600);
      report.tools[slug] = await page.evaluate((ids) => {
        const out = {};
        ids.forEach((i) => { const el = document.getElementById(i); out[i] = el ? el.children.length : 'MISSING'; });
        return out;
      }, ids);
    }
    /* legacy hashes: #more -> #tools, #player -> #tools/player, #market -> #tools,
       #history/#trader -> trade, #mastery -> /collection.html#mastery (a real navigation) */
    report.legacy = {};
    for (const h of ['#more', '#player', '#market', '#history', '#trader', '#mastery']) {
      await page.evaluate(() => { location.hash = '#home'; });
      await sleep(200);
      await page.evaluate((h) => { location.hash = h; }, h);
      await sleep(h === '#mastery' ? 1800 : 700);
      report.legacy[h] = await page.evaluate(() => {
        const on = (id) => { const el = document.getElementById(id); return el ? !el.classList.contains('hidden') : null; };
        return {
          href: location.href, path: location.pathname, hash: location.hash,
          tools: on('view-tools'), player: on('view-player'), trade: on('view-trade'),
          home: on('view-home'),
          mastery: on('view-mastery'),
        };
      });
      if (report.legacy[h].path !== '/') {          /* #mastery left the SPA: go back for the next */
        await page.goto(BASE + '/', { waitUntil: 'load' });
        await sleep(1800);
      }
    }
    report.errors.index_clickthrough = errs;
    await page.close();
  }

  /* ---------------- (d) collection: the section row + the Mastery tab ---------------- */
  {
    const page = await browser.newPage();
    const errs = [];
    page.on('console', (m) => { if (m.type() === 'error') errs.push('console: ' + m.text()); });
    page.on('pageerror', (e) => errs.push('pageerror: ' + String(e.message || e)));
    await page.setViewport({ width: 1920, height: 1080 });
    await page.goto(BASE + '/collection.html', { waitUntil: 'load' });
    await sleep(2500);
    report.collection.grid = await page.evaluate(() => ({
      section: location.hash,
      nav: [...document.querySelectorAll('#collectionNav .navpill')].map((p) => [p.dataset.v, p.getAttribute('href'), p.classList.contains('active')]),
      tiles: document.querySelectorAll('#grid > *').length,
    }));
    /* click the Mastery pill (a real click), then check the panel */
    await page.click('#collectionNav .navpill[data-v="mastery"]');
    await sleep(1200);
    report.collection.mastery = await page.evaluate(() => ({
      hash: location.hash,
      visible: !document.getElementById('view-mastery').classList.contains('hidden'),
      gridHidden: document.getElementById('grid').classList.contains('hidden'),
      relicsHidden: document.getElementById('relicView').classList.contains('hidden'),
      nav: [...document.querySelectorAll('#collectionNav .navpill')].map((p) => [p.dataset.v, p.classList.contains('active')]),
      rows: document.querySelectorAll('#mhNext .mh-row[data-slug]').length,
      cats: document.querySelectorAll('#mhCats .mh-cat').length,
      filters: [...document.querySelectorAll('#mhFilters button')].map((b) => b.textContent.trim()),
      cap: (document.getElementById('mhCap') || {}).textContent || '',
      head: (document.getElementById('mhHead') || {}).textContent.replace(/\s+/g, ' ').trim().slice(0, 90),
      stats: [...document.querySelectorAll('#mhStats .kpi')].map((k) => k.textContent.replace(/\s+/g, ' ').trim()),
    }));
    fs.writeFileSync(path.join(SHOTS, 'ia-collection-mastery.png'), await page.screenshot());
    /* the Relics pill and back to Collection */
    await page.click('#collectionNav .navpill[data-v="relics"]');
    await sleep(1400);
    report.collection.relics = await page.evaluate(() => ({
      hash: location.hash,
      relicsVisible: !document.getElementById('relicView').classList.contains('hidden'),
      rows: document.querySelectorAll('#relBody tr').length,
      nav: [...document.querySelectorAll('#collectionNav .navpill')].map((p) => [p.dataset.v, p.classList.contains('active')]),
    }));
    await page.click('#collectionNav .navpill[data-v="collection"]');
    await sleep(800);
    report.collection.back = await page.evaluate(() => ({
      hash: location.hash, tiles: document.querySelectorAll('#grid > *').length,
      gridHidden: document.getElementById('grid').classList.contains('hidden'),
    }));
    /* the deep link must open the tab directly */
    await page.goto(BASE + '/collection.html#mastery', { waitUntil: 'load' });
    await sleep(2500);
    const deepMh = await page.evaluate(() => ({
      hash: location.hash,
      visible: !document.getElementById('view-mastery').classList.contains('hidden'),
      rows: document.querySelectorAll('#mhNext .mh-row').length,
    }));
    report.collection.deep_link = deepMh;
    report.errors.collection = errs;
    await page.close();
  }

  /* ---------------- (e) the screenshots the brief asks for ---------------- */
  {
    const page = await browser.newPage();
    await page.setViewport({ width: 1920, height: 1080 });
    await page.goto(BASE + '/', { waitUntil: 'load' });
    await sleep(2200);
    await page.evaluate(() => { location.hash = '#tools'; });
    await sleep(600);
    const railBox = await page.evaluate(() => {
      const r = document.querySelector('.side').getBoundingClientRect();
      return { x: 0, y: Math.max(0, Math.floor(r.top)), width: Math.ceil(r.width) + 90, height: Math.ceil(r.height) + 40 };
    });
    await page.screenshot({ path: path.join(SHOTS, 'ia-rail-1920.png'),
      clip: { x: railBox.x, y: railBox.y, width: Math.min(railBox.width, 1920), height: Math.min(railBox.height, 1080) } });
    await page.close();
  }

  await browser.close();

  /* ---------------- the id union vs the stage 1 snapshot ---------------- */
  const before = new Set();
  Object.values(IDS_BEFORE).forEach((list) => list.forEach((i) => before.add(i)));
  const after = new Set();
  Object.values(report.pages).forEach((p) => p.ids.forEach((i) => after.add(i)));
  const missing = [...before].filter((i) => !after.has(i)).sort();
  const shellIds = ['mainnav', 'chips', 'soundBtn', 'themeBtn', 'themePanel', 'themeName',
    'themeGrid', 'search', 'searchDrop', 'syncState', 'refresh', 'btnExportPng', 'settingsBtn'];
  const unknown = [...after].filter((i) => !before.has(i) && !shellIds.includes(i)).sort();
  report.ids = { before: before.size, after: after.size, missing, unknown };

  fs.writeFileSync(path.join(__dirname, 'qa_ia.json'), JSON.stringify(report, null, 1));
  console.log('\nID UNION  before=%d  rendered=%d  missing=%d %s',
    before.size, after.size, missing.length, JSON.stringify(missing));
  console.log('ID UNION  new ids: ' + JSON.stringify(unknown));
  console.log('ERRORS per page: ' + JSON.stringify(Object.fromEntries(Object.entries(report.errors).map(([k, v]) => [k, v.length]))));
  console.log('LEGACY ' + Object.entries(report.legacy).map(([h, r]) => h + '->' + r.hash).join(' '));
  console.log('TOOL WORKSPACES ' + Object.entries(report.tools.slugs).map(([s, r]) =>
    s + ':' + (r.visible && r.onlyOne === 1 && r.launcherHidden ? 'ok' : 'BAD')).join(' '));
  console.log('STAGE2 QA DONE');
})().catch((e) => { console.error('QA FAILED', e); process.exit(1); });
