/* Stage 4 QA: the Trade rework (Sell / Buy / History + the ONE Safety & advanced layer).
 *
 *   node design/_stage4/qa_trade.js
 *
 * Read-only interaction only: tab buttons, the held/hygiene disclosures, one plan row (which only
 * opens the shared item drawer) and viewport resizes. No action button is ever clicked.
 *
 * Measures, against the running server on 127.0.0.1:8787:
 *   (a) the four tabs: one visible panel at a time, 0 console errors, the posting badge honest;
 *   (b) fit: pageOver / ovfX 0 on home / trade / inventory / tools at 1920x1080, 1536x864,
 *       1366x768, 1280x800 - trade measured on every tab;
 *   (c) parity: rendered row counts vs the payloads the app fetched (plan / held / notify /
 *       run queue / hygiene / trade log) and dry_run still true in the rendered badge;
 *   (d) the advanced layer does not clip at 1024 / 1200 / 1366 / 1600 / 1920 (card + heading
 *       widths measured);
 *   (e) screenshots C:/Users/jayde/AppData/Local/Temp/shotkit/shots/s4-trade-{sell,buy,history,
 *       advanced}.png at 1920x1080;
 *   (f) every id from the stage-1 view-trade snapshot is still rendered (0 missing, 0 dups).
 * Writes design/_stage4/qa_trade.json.
 */
'use strict';
const puppeteer = require('C:/Users/jayde/AppData/Local/Temp/shotkit/node_modules/puppeteer-core');
const fs = require('fs');
const path = require('path');

const BASE = 'http://127.0.0.1:8787';
const SHOTS = 'C:/Users/jayde/AppData/Local/Temp/shotkit/shots';
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const IDS_BEFORE = JSON.parse(fs.readFileSync(path.join(__dirname, 'ids_before.json'), 'utf8'));
const TABS = ['sell', 'buy', 'history', 'advanced'];
const VIEWS = ['home', 'trade', 'inventory', 'tools'];
const VIEWPORTS = [[1920, 1080], [1536, 864], [1366, 768], [1280, 800]];
const CLIP_WIDTHS = [1024, 1200, 1366, 1600, 1920];
const ADV_IDS = ['killMeta', 'btnKill', 'killNote', 'killList', 'limMeta', 'limList',
  'notifyMeta', 'btnNotify', 'notifyList', 'runqMeta', 'btnRunq', 'runqList',
  'hygieneAcc', 'hygieneMeta', 'btnHygiene', 'hygieneList'];
/* cards.html paints card art from the WFCD CDN, blocked on this PC - not this stage's business */
const PREEXISTING = /cdn\.warframestat\.us|api\.warframe\.market|wfcd/i;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const report = { tabs: {}, fit: {}, parity: {}, clip: {}, ids: {}, drawer: {}, errors: {} };

function hookErrors(page, bag) {
  page.on('console', (m) => { if (m.type() === 'error') bag.push('console: ' + m.text()); });
  page.on('pageerror', (e) => bag.push('pageerror: ' + String(e.message || e)));
  page.on('requestfailed', (r) => {
    const u = r.url();
    if (!PREEXISTING.test(u)) bag.push('reqfail: ' + u + ' ' + ((r.failure() || {}).errorText || ''));
  });
}

/* what each tab must show: the visible panel, its row counts and the ids it owns */
async function tabState(page) {
  return page.evaluate(() => {
    const vis = (id) => { const el = document.getElementById(id); return el ? !el.classList.contains('hidden') : null; };
    const rows = (sel) => document.querySelectorAll(sel).length;
    const pm = document.getElementById('postMode');
    const adv = document.getElementById('tp-advanced');
    return {
      hash: location.hash,
      aria: [...document.querySelectorAll('#tradeTabs [role="tab"]')].map((t) => [t.id, t.dataset.tp, t.getAttribute('aria-selected')]),
      panels: { sell: vis('tp-sell'), buy: vis('tp-buy'), history: vis('tp-history'), advanced: vis('tp-advanced') },
      visibleCount: ['tp-sell', 'tp-buy', 'tp-history', 'tp-advanced'].filter(vis).length,
      sell: { plan: rows('#planList .prow:not(.plan-head)'), planSlug: rows('#planList .prow[data-slug]'),
              held: rows('#heldList .heldline'), heldOpen: document.getElementById('heldAcc').open,
              attn: rows('#attnList .attnrow'), attnSlug: rows('#attnList .attnrow[data-slug]') },
      buy: { flips: rows('#flipsList .frow:not(.frowhead)'), wish: rows('#wishList > *') },
      history: { kpis: rows('#histKpis .kpi'), log: rows('#tradeLog .lrow:not(.log-head)'),
                 sessions: rows('#sessList .sessrow'), timing: rows('#timingList > *'), ledger: rows('#ledgerList > *') },
      advanced: {
        present: (() => { const out = {}; ['killMeta', 'btnKill', 'killNote', 'killList', 'limMeta', 'limList',
          'notifyMeta', 'btnNotify', 'notifyList', 'runqMeta', 'btnRunq', 'runqList', 'hygieneAcc',
          'hygieneMeta', 'btnHygiene', 'hygieneList'].forEach((i) => {
            const el = document.getElementById(i);
            out[i] = el ? (adv.contains(el) ? 'in-adv' : 'outside') : 'MISSING';
          }); return out; })(),
        details: adv ? adv.querySelectorAll('details').length : null,
        detailsIds: adv ? [...adv.querySelectorAll('details')].map((d) => d.id) : [],
        notifyLabels: [...document.querySelectorAll('#notifyList .chip')].map((c) => c.textContent.trim()),
        notifyRawPresent: /dry[ _-]?run/i.test(adv ? adv.textContent : ''),
        killMedia: document.getElementById('killNote').value,
        runqRows: rows('#runqList .runrow:not(.runhead)'),
        hygieneRows: rows('#hygieneList .heldline') + rows('#hygieneList .limrow') + rows('#hygieneList .dim'),
        noLiveLines: (document.getElementById('hygieneList').textContent.includes('NOT LIVE - plan only'))
          + (document.getElementById('killList').textContent.includes('Not live')),
      },
      postMode: pm ? { text: pm.textContent.trim(), cls: pm.className } : null,
      planTabOrder: [...document.querySelectorAll('#tradeTabs [role="tab"]')].map((t) => t.textContent.trim()),
    };
  });
}

(async () => {
  const browser = await puppeteer.launch({
    executablePath: CHROME, headless: 'new',
    args: ['--no-sandbox', '--disable-dev-shm-usage', '--window-size=1920,1080'],
  });
  const page = await browser.newPage();
  const errs = [];
  hookErrors(page, errs);
  await page.setViewport({ width: 1920, height: 1080 });
  await page.goto(BASE + '/#trade', { waitUntil: 'load', timeout: 30000 });
  await sleep(2600);

  /* ---------------- (a) the four tabs, clicked, one panel at a time ---------------- */
  report.parity.payload = await page.evaluate(async () => {
    const t = await fetch('/api/trader').then((r) => r.json()).catch(() => ({}));
    const h = await fetch('/api/feature/hygiene').then((r) => r.json()).catch(() => ({}));
    const rq = await fetch('/api/feature/runqueue').then((r) => r.json()).catch(() => ({}));
    const nf = await fetch('/api/feature/notify').then((r) => r.json()).catch(() => ([]));
    const tr = await fetch('/api/trades').then((r) => r.json()).catch(() => ({}));
    return {
      plan: ((t.plan || {}).plan || []).length, held: ((t.plan || {}).held_list || []).length,
      undercuts: (((t.undercuts || {}).rows) || []).length,
      dryPlan: (t.plan || {}).dry_run === true, drySettings: (t.settings || {}).dry_run === true,
      hygieneActions: ((h.actions) || []).length, hygieneTotal: ((h.summary || {}).total) || 0,
      runq: ((rq.queue) || []).length, notify: Array.isArray(nf) ? nf.length : ((nf.rows || []).length),
      events: ((tr.events) || []).length,
    };
  });
  const P = report.parity.payload;

  for (const tab of TABS) {
    await page.click('#tt-' + tab);
    await sleep(650);
    report.tabs[tab] = await tabState(page);
  }
  /* the held/hygiene disclosures (read-only: they only change their own display) */
  report.tabs.held = await page.evaluate(async () => {
    document.querySelector('#tt-sell').click();
    await new Promise((r) => setTimeout(r, 400));
    const acc = document.getElementById('heldAcc');
    acc.open = true;
    await new Promise((r) => setTimeout(r, 400));
    const list = document.getElementById('heldList');
    return { open: acc.open, heldRows: list.querySelectorAll('.heldline').length,
             scrollable: list.scrollHeight > list.clientHeight + 2,
             listH: Math.round(list.clientHeight), contentH: Math.round(list.scrollHeight) };
  });
  report.tabs.hygiene = await page.evaluate(async () => {
    document.querySelector('#tt-advanced').click();
    await new Promise((r) => setTimeout(r, 400));
    const acc = document.getElementById('hygieneAcc');
    const before = document.getElementById('hygieneList').getBoundingClientRect().height;
    acc.open = true;
    await new Promise((r) => setTimeout(r, 500));
    const box = document.getElementById('hygieneList');
    return { open: acc.open, beforeH: Math.round(before), afterH: Math.round(box.getBoundingClientRect().height),
             moreRows: box.querySelectorAll('.heldline').length, scrolls: box.scrollHeight > box.clientHeight + 2,
             notLive: box.textContent.includes('NOT LIVE - plan only') };
  });
  /* one action per row: the first recommended listing opens the drawer (read-only) */
  await page.evaluate(() => { document.querySelector('#tt-sell').click(); });
  await sleep(400);
  report.drawer = await page.evaluate(async () => {
    const row = document.querySelector('#planList .prow[data-slug]');
    row.scrollIntoView({ block: 'center' });
    row.click();
    await new Promise((r) => setTimeout(r, 900));
    const root = document.querySelector('[data-wfm-drawer="root"]');
    const open = root ? !root.classList.contains('dw-hidden') : false;
    const title = root ? (root.textContent || '').slice(0, 60) : '';
    if (window.wfmOpenItem && window.wfmOpenItem.close) window.wfmOpenItem.close();
    return { rowSlug: row.dataset.slug, drawerOpen: open, head: title.replace(/\s+/g, ' ').trim() };
  });
  await sleep(400);
  /* the badge is not hardcoded: flip the config in memory (no fetch, no write) and re-render -
     'Live' must only appear when dry_run is off, then put the real config back */
  report.badgeFlip = await page.evaluate(() => {
    const out = {};
    const pm = () => ({ text: document.getElementById('postMode').textContent.trim(),
                        cls: document.getElementById('postMode').className });
    out.asShipped = pm();
    const keep = { s: TRADER.settings.dry_run, p: TRADER.plan.dry_run };
    try {
      TRADER.settings.dry_run = false; TRADER.plan.dry_run = false; renderTrader();
      out.whenDryRunOff = pm();
    } finally {
      TRADER.settings.dry_run = keep.s; TRADER.plan.dry_run = keep.p; renderTrader();
    }
    out.restored = pm();
    return out;
  });
  report.errors.tabs = errs.slice();
  console.log('BADGE   %s  dry_settings=%s dry_plan=%s  flip=%j',
    JSON.stringify(report.tabs.sell.postMode), P.drySettings, P.dryPlan, report.badgeFlip);
  console.log('TABS    ' + TABS.map((t) => t + ':vis=' + report.tabs[t].visibleCount + '/' + JSON.stringify(report.tabs[t].panels)).join(' '));
  console.log('VERTAB  present=%j notify=%j raw_dry_run_in_adv=%s adv_details=%j',
    Object.values(report.tabs.advanced.advanced.present).every((v) => v === 'in-adv'),
    report.tabs.advanced.advanced.notifyLabels, report.tabs.advanced.advanced.notifyRawPresent,
    report.tabs.advanced.advanced.detailsIds);
  console.log('PARITY  plan=%d/%d held=%d/%d runq=%d/%d notify=%d/%d log=%d/%d attn=%d/%d',
    report.tabs.sell.sell.plan, P.plan, report.tabs.sell.sell.held, P.held,
    report.tabs.advanced.advanced.runqRows, Math.min(P.runq, 10),
    report.tabs.advanced.advanced.notifyLabels.length, Math.min(P.notify, 6),
    report.tabs.history.history.log, P.events,
    report.tabs.sell.sell.attn, P.undercuts + (P.hygieneTotal ? 1 : 0));
  console.log('DRAWER  ' + JSON.stringify(report.drawer));
  console.log('ERRORS(a) %d %j', errs.length, errs.slice(0, 4));

  /* ---------------- (b) fit matrix: 4 views x 4 viewports, trade on every tab ---------------- */
  for (const [w, h] of VIEWPORTS) {
    const key = w + 'x' + h;
    report.fit[key] = {};
    await page.setViewport({ width: w, height: h });
    await sleep(350);
    for (const v of VIEWS) {
      await page.evaluate((v) => { document.querySelector('#mainnav .navpill[data-v="' + v + '"]').click(); }, v);
      await sleep(450);
      if (v === 'trade') {
        report.fit[key][v] = {};
        for (const tab of TABS) {
          await page.evaluate((t) => { document.getElementById('tt-' + t).click(); }, tab);
          await sleep(400);
          report.fit[key][v][tab] = await page.evaluate(() => {
            const de = document.documentElement;
            const sec = document.querySelector('main > section:not(.hidden)');
            return {
              pageOverX: Math.max(de.scrollWidth - de.clientWidth, document.body.scrollWidth - window.innerWidth),
              pageOverY: Math.max(de.scrollHeight - de.clientHeight, document.body.scrollHeight - window.innerHeight),
              secOverX: sec ? Math.max(0, sec.scrollWidth - sec.clientWidth) : null,
              secOverY: sec ? Math.max(0, sec.scrollHeight - sec.clientHeight) : null,
            };
          });
        }
      } else {
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
    }
    await page.setViewport({ width: 1920, height: 1080 });
    await sleep(300);
  }
  console.log('FIT     ' + Object.entries(report.fit).map(([k, views]) =>
    k + ' ' + Object.entries(views).map(([v, m]) => v + (v === 'trade'
      ? '[' + Object.entries(m).map(([t, x]) => t + ':' + x.pageOverX + '/' + x.pageOverY).join(' ') + ']'
      : ':' + m.pageOverX + '/' + m.pageOverY)).join(' ')).join(' | '));

  /* ---------------- (d) the advanced layer does not clip, 1024 -> 1920 ---------------- */
  for (const w of CLIP_WIDTHS) {
    await page.setViewport({ width: w, height: Math.max(800, Math.round(w * 0.6)) });
    await sleep(350);
    await page.evaluate(() => { location.hash = '#trade/advanced'; });
    await sleep(650);
    report.clip[w] = await page.evaluate(() => {
      const adv = document.getElementById('tp-advanced');
      const cards = [...adv.querySelectorAll('.card')];
      const out = { cards: [], section: adv.scrollWidth - adv.clientWidth,
                    pageOverX: Math.max(document.documentElement.scrollWidth - document.documentElement.clientWidth,
                                        document.body.scrollWidth - window.innerWidth) };
      for (const c of cards) {
        const title = c.querySelector('.card-title');
        const cr = c.getBoundingClientRect();
        const trect = title ? title.getBoundingClientRect() : null;
        let inner = 0;
        [...c.querySelectorAll('*')].forEach((el) => {
          const r = el.getBoundingClientRect();
          if (r.width) inner = Math.max(inner, Math.round(r.right - cr.right), Math.round(cr.left - r.left));
        });
        out.cards.push({
          title: (title ? title.textContent : '?').replace(/\s+/g, ' ').trim().slice(0, 34),
          cardOver: c.scrollWidth - c.clientWidth,
          headOver: title ? Math.max(0, title.scrollWidth - title.clientWidth) : null,
          titleOverRight: trect ? Math.round(trect.right - (cr.right - 8)) : null,
          maxInner: inner,
          w: Math.round(cr.width),
        });
      }
      return out;
    });
    await sleep(100);
  }
  const clipBad = [];
  Object.entries(report.clip).forEach(([w, m]) => {
    m.cards.forEach((c) => {
      if (c.cardOver > 1 || (c.headOver || 0) > 1 || c.maxInner > 1) clipBad.push(w + ':' + c.title + ' card=' + c.cardOver + ' head=' + c.headOver + ' inner=' + c.maxInner);
    });
    if (m.section > 1) clipBad.push(w + ':section=' + m.section);
  });
  console.log('CLIP    ' + CLIP_WIDTHS.map((w) => w + ':' + report.clip[w].cards.map((c) => c.cardOver + '/' + c.headOver).join(',')).join(' '));
  console.log('CLIPBAD %d %j', clipBad.length, clipBad.slice(0, 6));

  /* ---------------- (e) screenshots at 1920x1080 ---------------- */
  await page.setViewport({ width: 1920, height: 1080 });
  await sleep(400);
  /* the shipped default state: both disclosures closed (the probe opened them above) */
  await page.evaluate(() => {
    document.getElementById('heldAcc').open = false;
    document.getElementById('hygieneAcc').open = false;
  });
  for (const tab of TABS) {
    await page.evaluate((t) => { document.getElementById('tt-' + t).click(); }, tab);
    await sleep(700);
    fs.writeFileSync(path.join(SHOTS, 's4-trade-' + tab + '.png'), await page.screenshot());
  }
  /* the held panel opened, for the record (a second sell frame; the four required shots stand) */
  await page.evaluate(() => { document.getElementById('tt-sell').click(); });
  await sleep(300);
  await page.evaluate(() => { document.getElementById('heldAcc').open = true; });
  await sleep(600);
  fs.writeFileSync(path.join(SHOTS, 's4-trade-sell-held.png'), await page.screenshot());
  await page.evaluate(() => { document.getElementById('heldAcc').open = false; });
  await sleep(200);
  report.errors.final = errs.slice();

  /* ---------------- (f) every stage-1 trade id is still rendered ---------------- */
  const rendered = await page.evaluate(() => [...document.querySelectorAll('[id]')].map((e) => e.id));
  const missing = IDS_BEFORE.filter((i) => !rendered.includes(i));
  const dups = rendered.filter((v, i) => rendered.indexOf(v) !== i);
  report.ids = { before: IDS_BEFORE.length, rendered: rendered.length, all: rendered, missing, dups,
    newIds: rendered.filter((i) => !IDS_BEFORE.includes(i)) };
  console.log('IDS     before=%d missing=%d %j dups=%j new=%j',
    IDS_BEFORE.length, missing.length, missing, dups, report.ids.newIds.filter((i) => /^(tt-|tp-|postMode)/.test(i)));
  console.log('ERRORS  total=%d %j', errs.length, errs.slice(0, 6));

  fs.writeFileSync(path.join(__dirname, 'qa_trade.json'), JSON.stringify(report, null, 1));
  await browser.close();
  console.log('STAGE4 QA DONE');
})().catch((e) => { console.error('QA FAILED', e); process.exit(1); });
