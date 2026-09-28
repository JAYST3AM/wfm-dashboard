/* Stage 3 QA - the Home action surface: order, values-once, fit, the chat toggle, the news move.
 *   node design/_stage3/qa_home.js
 * Read-only: never clicks a plan rebuild, a queue button or anything that writes app data. The
 * only clicks are the chat toggle (localStorage) and viewing hash routes.
 * Writes C:/Users/jayde/AppData/Local/Temp/shotkit/shots/s3-*.png and design/_stage3/qa_home.json.
 */
'use strict';
const puppeteer = require('F:/VSC Projects/pb-bench/node_modules/puppeteer-core');
const fs = require('fs');
const path = require('path');

const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const SHOTS = 'C:/Users/jayde/AppData/Local/Temp/shotkit/shots';
const BASE = 'http://127.0.0.1:8787';
const OUT = path.join(__dirname, 'qa_home.json');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const report = {};

(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: 'new',
    args: ['--no-sandbox', '--disable-dev-shm-usage', '--force-device-scale-factor=1'] });
  const p = await b.newPage();
  const errors = [];
  p.on('console', (m) => { if (m.type() === 'error') errors.push('console: ' + m.text()); });
  p.on('pageerror', (e) => errors.push('pageerror: ' + ((e && e.message) || e)));
  p.on('requestfailed', (r) => errors.push('reqfail: ' + r.url()));

  await p.setViewport({ width: 1920, height: 1080 });
  await p.goto(BASE + '/', { waitUntil: 'load' });
  await sleep(400);                                   /* fonts/scripts land */
  await p.evaluate(() => { try { localStorage.removeItem('wfm.chat.open'); } catch (e) {} });
  await p.goto(BASE + '/', { waitUntil: 'load' });
  await sleep(3000);

  const shot = (name) => p.screenshot({ path: path.join(SHOTS, 's3-' + name + '.png') });

  /* ---------------- home: structure, the strip, every number that renders ---------------- */
  report.home = await p.evaluate(() => {
    const vis = (el) => !!(el && el.getClientRects().length);
    const sec = document.getElementById('view-home');
    const order = [...document.querySelectorAll('#homeMain > *')]
      .map((e) => (e.id || e.className) + (vis(e) ? '' : ' [hidden]'));
    const strip = [...document.querySelectorAll('#kpis .kpi')].map((k) => ({
      label: k.querySelector('.k-label').textContent.trim(),
      value: k.querySelector('.k-val').textContent.trim(),
      tip: k.getAttribute('title'),
    }));
    /* every leaf that shows a digit, with the card it belongs to - the duplication read-out */
    const numbers = [];
    document.querySelectorAll('#view-home *').forEach((e) => {
      if (e.children.length) return;
      const t = (e.textContent || '').trim();
      if (!t || !/\d/.test(t)) return;
      const card = e.closest('.card');
      numbers.push([card ? (card.id || card.className) : 'head', e.tagName.toLowerCase() + '.' + (e.className || '-'), t]);
    });
    const ids = [...document.querySelectorAll('[id]')].map((e) => e.id);
    const toggle = document.getElementById('chatToggle');
    const dock = document.getElementById('chatDock');
    return {
      order, strip, numbers,
      duplicateIds: ids.filter((v, i) => ids.indexOf(v) !== i),
      headText: document.getElementById('homeHead').textContent.replace(/\s+/g, ' ').trim(),
      headHtml: document.getElementById('homeHead').innerHTML.replace(/\s+/g, ' ').slice(0, 300),
      toggle: toggle ? { text: toggle.textContent.trim(), expanded: toggle.getAttribute('aria-expanded'), title: toggle.title } : null,
      dock: dock ? { attached: true, displayed: getComputedStyle(dock).display, rows: (document.getElementById('chatRows') || {}).childElementCount } : { attached: false },
      viewClass: sec.className,
      secOverflow: sec.scrollHeight - sec.clientHeight,
      alertsVisible: vis(document.getElementById('alertsCard')),
      alertText: (document.getElementById('homeAlerts') || {}).textContent ? document.getElementById('homeAlerts').textContent.replace(/\s+/g, ' ').trim().slice(0, 200) : '',
      nextText: document.getElementById('sellNextList').textContent.replace(/\s+/g, ' ').trim(),
      queueRows: [...document.querySelectorAll('#sellQueueList .hnext-row')].map((r) => r.textContent.replace(/\s+/g, ' ').trim()),
      recentRows: [...document.querySelectorAll('#homeRecent .h-ev')].map((r) => r.textContent.replace(/\s+/g, ' ').trim()),
      newsMoved: { homeHasNews: !!document.querySelector('#view-home #newsList'), toolsHasNews: !!document.querySelector('#tws-news #newsList') },
    };
  });
  await shot('home-1920');

  /* ---------------- fit on the four index views at three sizes ---------------- */
  const fitAt = async (w, h) => {
    await p.setViewport({ width: w, height: h });
    await sleep(400);
    const rows = {};
    for (const [name, hash] of [['home', '#home'], ['trade', '#trade'], ['inventory', '#inventory'], ['tools', '#tools'], ['tools/news', '#tools/news']]) {
      await p.evaluate((hh) => { location.hash = hh; }, hash);
      await sleep(700);
      rows[name] = await p.evaluate(() => {
        const de = document.documentElement;
        const sec = document.querySelector('main > section:not(.hidden)');
        return {
          overX: Math.max(de.scrollWidth - de.clientWidth, document.body.scrollWidth - window.innerWidth),
          overY: Math.max(de.scrollHeight - de.clientHeight, document.body.scrollHeight - window.innerHeight),
          secOver: sec ? sec.scrollHeight - sec.clientHeight : null,
          secId: sec ? sec.id : null,
        };
      });
    }
    await p.evaluate(() => { location.hash = '#home'; });
    await sleep(600);
    return rows;
  };
  report.fit = { '1920x1080': await fitAt(1920, 1080), '1536x864': await fitAt(1536, 864), '1366x768': await fitAt(1366, 768) };

  /* ---------------- 1366 home shot ---------------- */
  await shot('home-1366');
  await p.setViewport({ width: 1920, height: 1080 });
  await sleep(600);

  /* ---------------- the chat toggle: closed by default, one control, persisted ---------------- */
  report.chatClosed = await p.evaluate(() => ({
    dockDisplay: getComputedStyle(document.getElementById('chatDock')).display,
    expanded: document.getElementById('chatToggle').getAttribute('aria-expanded'),
    viewClass: document.getElementById('view-home').className,
    stored: (() => { try { return localStorage.getItem('wfm.chat.open'); } catch (e) { return 'n/a'; } })(),
    homeWidth: Math.round(document.getElementById('homeMain').getBoundingClientRect().width),
  }));
  await shot('chat-closed-1920');

  await p.click('#chatToggle');
  await sleep(1200);
  report.chatOpen = await p.evaluate(() => {
    const dock = document.getElementById('chatDock');
    const r = dock.getBoundingClientRect();
    const view = document.getElementById('view-home').getBoundingClientRect();
    return {
      dockDisplay: getComputedStyle(dock).display,
      expanded: document.getElementById('chatToggle').getAttribute('aria-expanded'),
      viewClass: document.getElementById('view-home').className,
      stored: (() => { try { return localStorage.getItem('wfm.chat.open'); } catch (e) { return 'n/a'; } })(),
      dockTop: Math.round(r.top), dockBottom: Math.round(r.bottom), dockWidth: Math.round(r.width),
      viewBottom: Math.round(view.bottom),
      rows: document.querySelectorAll('#chatRows .chatrow, #chatRows #chatEmpty').length,
      form: !!document.getElementById('chatForm'),
      stateChip: document.getElementById('chatState').textContent.trim(),
      homeWidth: Math.round(document.getElementById('homeMain').getBoundingClientRect().width),
      overY: Math.max(document.documentElement.scrollHeight - document.documentElement.clientHeight,
        document.body.scrollHeight - window.innerHeight),
    };
  });
  await shot('chat-open-1920');

  /* a reload remembers "open", a second click closes it again */
  await p.reload({ waitUntil: 'load' });
  await sleep(2500);
  report.chatPersisted = await p.evaluate(() => ({
    expanded: document.getElementById('chatToggle').getAttribute('aria-expanded'),
    dockDisplay: getComputedStyle(document.getElementById('chatDock')).display,
    viewClass: document.getElementById('view-home').className,
  }));
  await p.click('#chatToggle');
  await sleep(800);
  report.chatReclosed = await p.evaluate(() => ({
    expanded: document.getElementById('chatToggle').getAttribute('aria-expanded'),
    dockDisplay: getComputedStyle(document.getElementById('chatDock')).display,
    homeWidth: Math.round(document.getElementById('homeMain').getBoundingClientRect().width),
    stored: (() => { try { return localStorage.getItem('wfm.chat.open'); } catch (e) { return 'n/a'; } })(),
  }));

  /* ---------------- the Today detail disclosure (one tap, no data lost) ---------------- */
  await p.evaluate(() => { const d = document.getElementById('todayMore'); if (d) d.open = true; });
  await sleep(500);
  report.todayDetail = await p.evaluate(() => ({
    rows: [...document.querySelectorAll('#homeToday .h-row')].map((r) => r.textContent.replace(/\s+/g, ' ').trim()),
    sessions: document.querySelectorAll('#homeToday .h-ev').length,
    groupHeads: [...document.querySelectorAll('#homeToday .h-group-head')].map((e) => e.textContent.trim()),
    overY: Math.max(document.documentElement.scrollHeight - document.documentElement.clientHeight,
      document.body.scrollHeight - window.innerHeight),
  }));
  await shot('today-detail-1920');
  await p.evaluate(() => { const d = document.getElementById('todayMore'); if (d) d.open = false; });

  /* ---------------- the news workspace ---------------- */
  await p.evaluate(() => { location.hash = '#tools/news'; });
  await sleep(1200);
  report.news = await p.evaluate(() => ({
    launcherHidden: document.getElementById('toolsLauncher').classList.contains('hidden'),
    wsHidden: document.getElementById('tws-news').classList.contains('hidden'),
    listRows: document.querySelectorAll('#newsList .newsrow').length,
    meta: document.getElementById('newsMeta').textContent.trim(),
    backLink: !!document.querySelector('#tws-news .tws-back'),
    overY: Math.max(document.documentElement.scrollHeight - document.documentElement.clientHeight,
      document.body.scrollHeight - window.innerHeight),
  }));
  await shot('news-workspace-1920');

  /* ---------------- open: the rail at the three sizes, and the fit it must not break ---------------- */
  await p.evaluate(() => { location.hash = '#home'; });
  await sleep(900);
  await p.click('#chatToggle');
  await sleep(1200);
  const openFit = {};
  for (const [w, h] of [[1920, 1080], [1536, 864], [1366, 768]]) {
    await p.setViewport({ width: w, height: h });
    await sleep(700);
    openFit[w + 'x' + h] = await p.evaluate(() => {
      const de = document.documentElement;
      const dock = document.getElementById('chatDock').getBoundingClientRect();
      const view = document.getElementById('view-home').getBoundingClientRect();
      const sec = document.querySelector('main > section:not(.hidden)');
      return {
        overX: Math.max(de.scrollWidth - de.clientWidth, document.body.scrollWidth - window.innerWidth),
        overY: Math.max(de.scrollHeight - de.clientHeight, document.body.scrollHeight - window.innerHeight),
        secOver: sec ? sec.scrollHeight - sec.clientHeight : null,
        dockWidth: Math.round(dock.width), dockBottom: Math.round(dock.bottom), viewBottom: Math.round(view.bottom),
        rows: !!document.getElementById('chatRows'),
      };
    });
  }
  await p.setViewport({ width: 1920, height: 1080 });
  await sleep(800);
  report.chatOpenFit = openFit;
  await shot('chat-open-1920');
  await p.click('#chatToggle');
  await sleep(700);
  await shot('chat-closed-1920');

  /* ---------------- the quiet day: alerts hidden -> the action band widens, nothing overflows ---------------- */
  report.noAlerts = await p.evaluate(() => {
    const main = document.getElementById('homeMain');
    document.getElementById('alertsCard').classList.add('hidden');
    main.classList.add('no-alerts');
    const a = document.getElementById('homeSellNext').getBoundingClientRect();
    const b = document.getElementById('sellQueueCard').getBoundingClientRect();
    const de = document.documentElement;
    return {
      gap: Math.round(b.top - a.bottom),
      nextWidth: Math.round(a.width),
      overY: Math.max(de.scrollHeight - de.clientHeight, document.body.scrollHeight - window.innerHeight),
      overX: Math.max(de.scrollWidth - de.clientWidth, document.body.scrollWidth - window.innerWidth),
    };
  });
  await shot('no-alerts-1920');
  await p.evaluate(() => {
    document.getElementById('homeMain').classList.remove('no-alerts');
    document.getElementById('alertsCard').classList.remove('hidden');
  });
  await sleep(400);

  report.errors = errors;
  fs.writeFileSync(OUT, JSON.stringify(report, null, 1));
  console.log(JSON.stringify(report, null, 1));
  await b.close();
})().catch((e) => { console.error('PROBE FAILED', e); process.exit(1); });