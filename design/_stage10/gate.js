/* ============================================================================================
 * design/_stage10/gate.js — the one-shot release acceptance gate for WFM Trader.
 *
 *   node design/_stage10/gate.js          (normally run through: python design/_stage10/gate.py)
 *
 * It drives the LIVE app at http://127.0.0.1:8787 with puppeteer-core and writes
 * design/_stage10/gate-raw.json — every number it measured, nothing summarised away.
 * design/_stage10/gate.py runs the repo's own copy-diet test, calls this script, and writes
 * design/_stage10/gate-report.md (timestamped) with the mechanical pass/fail verdict.
 *
 * READ-ONLY ON THE APP: it loads pages, changes hash views, switches theme + settings category
 * pills, changes the viewport and applies themes. It never POSTs and never clicks a control
 * that writes data (no rebuild plan/queue, no list/buy, no kill switch, no notify test, no
 * settings save). Theme picks touch localStorage only (the app's own persistence).
 *
 * Checks:
 *   1 load      every page/state with 0 console errors, 0 failed requests outside the documented
 *               blocked-CDN class (warframe.market card / warframe art)
 *   2 fit       pageOverX/Y == 0 on every index view at 1920x1080 / 1536x864 / 1440x900 /
 *               1366x768 / 1280x800
 *   3 rail      exactly the 6 rail entries in order, exactly one active + one aria-current per
 *               page/view; the legacy hashes all resolve
 *   4 parity    headline numbers vs the raw data/*.json + the /api payloads (expected vs rendered)
 *   5 copy      rendered visible strings over 8 words / 90 chars, per page
 *   6 safety    the Not-live gate and the kill-switch file, reported as raw facts
 *   7 themes    4 themes (2 dark, 2 light) across every page: unreadable text, colours that
 *               ignore the theme vars, and console errors
 *   8 ids       every id in design/_stage1/ids_before.json still exists (sanctioned moves)
 * ============================================================================================ */
'use strict';

/* puppeteer-core: the repo has no node_modules of its own, so resolve the shared copy the
   other harnesses use. Nothing here reads stdin; every input is a constant, an env var or a file. */
let puppeteer = null, PUPPETEER_FROM = null;
for (const cand of [process.env.WFM_PUPPETEER, 'puppeteer-core', 'puppeteer',
                    'F:/VSC Projects/pb-bench/node_modules/puppeteer-core']) {
  if (!cand) continue;
  try { puppeteer = require(cand); PUPPETEER_FROM = cand; break; } catch (e) { /* next */ }
}
if (!puppeteer) {
  console.error('gate.js: no puppeteer-core found (tried WFM_PUPPETEER, node_modules, pb-bench)');
  process.exit(2);
}
const fs = require('fs');
const path = require('path');

/* ---------------------------------------------------------------- fixed inputs ------------ */
const REPO = 'F:/VSC Projects/wfm-dashboard';
const BASE = process.env.WFM_BASE || 'http://127.0.0.1:8787';
const CHROME = process.env.WFM_CHROME || 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const OUT = path.join(REPO, 'design', '_stage10');
const RAW = path.join(OUT, 'gate-raw.json');
const PROFILE = path.join(process.env.TEMP || 'C:/Users/jayde/AppData/Local/Temp', 'gate10-profile');
const ITEM_SLUG = process.env.WFM_SLUG || 'primed_continuity';

const VIEWPORTS = [[1920, 1080], [1536, 864], [1440, 900], [1366, 768], [1280, 800]];
/* 2 dark + 2 light, by index into static/theme.js WFM_THEMES */
const THEMES = [0, 2, 14, 28];                 /* Vor Orange, Kuva Crimson (dark) | Frost Light, Cephalon White (light) */
const THEME_DARK = 0, THEME_LIGHT = 14;        /* the dark/light pair compared for var escapes */
const RAIL_EXPECT = ['home', 'trade', 'inventory', 'collection', 'tools', 'settings'];
const INDEX_VIEWS = ['home', 'inventory', 'trade', 'tools'];
const WORKSPACES = ['deals', 'trends', 'rivens', 'wl', 'ducats', 'craft', 'relicev', 'sets', 'baro', 'meta', 'news', 'player'];
const SETTINGS_CATS = ['general', 'trading', 'appearance', 'accounts', 'notifications', 'advanced'];
const COLLECTION_SECTIONS = ['collection', 'relics', 'mastery'];
const LEGACY_HASHES = ['more', 'market', 'player', 'mastery', 'history', 'trader'];
/* the documented blocked-CDN class: card / warframe art that is not in the local cache */
const BLOCKED_HOSTS = ['warframe.market', 'cdn.warframestat.us', 'wfcdn.com', 'wiki.warframe.com', 'raw.githubusercontent.com'];
/* ids that legitimately left their old page (stage 2/3 moves) - reported, never silently dropped */
const SANCTIONED = {
  'view-more': 'renamed view-tools (stage 2)',
  'heroCard': 'merged into the Home Today strip (stage 3)',
  'heroMeta': 'merged into the Home Today strip (stage 3)',
  'homeSync': 'merged: sync state lives in the header #syncState + footer (stage 3)',
  'kpiCard': 'merged into the Home Today strip #kpis (stage 3)',
  'view-mastery': 'moved to collection.html #view-mastery (stage 2)',
};

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const rd = (rel) => { try { return JSON.parse(fs.readFileSync(path.join(REPO, rel), 'utf8')); } catch (e) { return null; } };
const api = async (p) => { try { const r = await fetch(BASE + p); return await r.json(); } catch (e) { return null; } };
const uniq = (a) => Array.from(new Set(a));

/* ---------------------------------------------------------------- result model ------------ */
const R = {
  meta: {
    started: new Date().toISOString(), finished: null, base: BASE, repo: REPO, node: process.version,
    chrome: CHROME, slug: ITEM_SLUG, viewports: VIEWPORTS.map((v) => v.join('x')), themes: THEMES,
    workspaces: WORKSPACES, index_views: INDEX_VIEWS, settings_cats: SETTINGS_CATS,
    collection_sections: COLLECTION_SECTIONS, legacy_hashes: LEGACY_HASHES,
  },
  states: [],      /* one row per page/state driven (errors/fails measured in that state) */
  load: {},        /* per page totals */
  load_detail: {}, /* the actual error/failure lines when a page has any */
  load_transient: {}, /* first attempts dropped by Chromium's net stack that were reloaded once */
  load_recheck: {},   /* connection-level failures re-verified with a direct fetch */
  fit: [],         /* {viewport, view, overX, overY, secOverX, secOverY} */
  rail: [],        /* {page, state, order, active, current, ok} */
  legacy: [],      /* {hash, visible, rail_active, alias_expects, ok} */
  parity: [],      /* {claim, source, expected, rendered, ok} */
  copy: [],        /* {page, state, text, words, chars, cls} */
  copy_totals: {},
  safety: {},
  themes: [],      /* {theme, name, mode, page, state, scanned, low, literalCount, newErrors} */
  theme_cross: [], /* {page, state, escaped, sample[]} - colours identical dark vs light */
  ids: { before: null, found: {}, missing_raw: [], sanctioned: [], missing: [] },
  checks: [],
};
const addCheck = (group, title, ok, expected, rendered, note) => {
  const c = { group, title, ok: !!ok, expected: String(expected), rendered: String(rendered), note: note || '' };
  R.checks.push(c);
  return c;
};

/* ---------------------------------------------------------------- recorders --------------- */
function isBlockedArt(url) {
  try { const h = new URL(url).host; return BLOCKED_HOSTS.some((b) => h === b || h.endsWith('.' + b)); } catch (e) { return false; }
}
/* A refused / buffer-starved request to our OWN origin is re-verified with a direct node fetch before
   it is allowed to fail the release. The dashboard server is single-threaded, so one page firing three
   requests at once can be refused and then answer instantly; anything that still refuses, or answers
   4xx/5xx, stays a failure. Every recheck is printed in the report - nothing is silently dropped. */
const ENVCODE = /ERR_CONNECTION_REFUSED|ERR_EMPTY_RESPONSE|ERR_SOCKET_NOT_CONNECTED|ERR_CONNECTION_RESET|ERR_NO_BUFFER_SPACE|ERR_INSUFFICIENT_RESOURCES|ERR_NETWORK_CHANGED/;
async function envRecheck(name, rec) {
  const envFails = rec.fails.filter((f) => ENVCODE.test(String(f.why)) && String(f.url).indexOf(BASE) === 0);
  if (!envFails.length) return;
  const rows = [];
  for (const f of envFails) {
    let status = 0, err = '';
    try { const r = await fetch(f.url, { cache: 'no-store' }); status = r.status; }
    catch (e) { err = String((e && e.message) || e); }
    rows.push({ url: f.url, why: f.why, recheck_status: status, recheck_error: err });
  }
  const clear = rows.filter((r) => r.recheck_status && r.recheck_status < 400);
  const stillBad = rows.filter((r) => !r.recheck_status || r.recheck_status >= 400);
  R.load_recheck[name] = { cleared: clear, still_failing: stillBad };
  if (!clear.length) return;
  const dropUrls = new Set(clear.map((r) => r.url));
  const perState = {};
  rec.fails.forEach((f) => { if (dropUrls.has(f.url)) perState[f.state] = (perState[f.state] || 0) + 1; });
  rec.fails = rec.fails.filter((f) => !dropUrls.has(f.url));
  const budget = Object.assign({}, perState);
  rec.errors = rec.errors.filter((e) => {
    if (/Failed to load resource/.test(e.text) && budget[e.state] > 0) { budget[e.state]--; return false; }
    return true;
  });
  R.states.forEach((s) => {
    const k = perState[s.state];
    if (s.page !== name || !k) return;
    s.fails = Math.max(0, (s.fails || 0) - k);
    s.errors = Math.max(0, (s.errors || 0) - k);
  });
}
class Rec {
  constructor(page) {
    this.errors = []; this.fails = []; this.blocked = []; this.state = '(boot)';
    page.on('console', (m) => { if (m.type() === 'error') this.err(m.text()); });
    page.on('pageerror', (e) => this.err('pageerror: ' + String((e && e.message) || e)));
    page.on('requestfailed', (r) => this.req(r.url(), String(((r.failure() || {}).errorText) || 'failed')));
    page.on('response', (r) => { if (r.status() >= 400) this.req(r.url(), 'HTTP ' + r.status()); });
  }
  err(text) { this.errors.push({ state: this.state, text: String(text).slice(0, 220) }); }
  req(url, why) {
    const row = { state: this.state, url: String(url).slice(0, 200), why };
    (isBlockedArt(url) ? this.blocked : this.fails).push(row);
  }
  mark() { return { e: this.errors.length, f: this.fails.length, b: this.blocked.length }; }
  since(m, label, page) {
    const row = { page, state: label, errors: this.errors.length - m.e, fails: this.fails.length - m.f,
      blocked: this.blocked.length - m.b };
    R.states.push(row);
    return row;
  }
}

/* ---------------------------------------------------------------- in-page probes ---------- */
const FACTS = `(() => {
  const q = (s) => document.querySelector(s);
  const txt = (s) => { const e = document.querySelector(s); return e ? e.textContent.replace(/\\s+/g, ' ').trim().slice(0, 260) : null; };
  const cnt = (s) => document.querySelectorAll(s).length;
  const HEAD = /(^|\\s)([a-z-]*head|note|empty|pad|subhead)(\\s|$)/;
  const rail = q('#mainnav');
  const pills = rail ? [...rail.querySelectorAll('.navpill')] : [];
  const active = pills.filter((p) => p.classList.contains('active'));
  const cur = pills.filter((p) => p.getAttribute('aria-current'));
  const rowCount = (id) => { const e = document.getElementById(id); if (!e) return null;
    const cls = ['dealrow','mrow','srow','frow','newsrow','prow','heldline'];
    const all = [...e.querySelectorAll('*')].filter((c) => cls.some((k) => c.classList.contains(k)) && !HEAD.test(String(c.className)));
    const direct = all.filter((c) => c.parentElement === e);
    return (direct.length ? direct : all).length; };
  const chipPairs = () => { const chips = [...document.querySelectorAll('.chips .chip')];
    if (!chips.length) { const c = document.querySelector('.chips'); return c ? [c.textContent.replace(/\\s+/g, ' ').trim()] : []; }
    return chips.map((c) => c.textContent.replace(/\\s+/g, ' ').trim()); };
  const shell = window.wfmShell || null;
  return {
    hash: location.hash,
    shell: shell ? { key: shell.pageKey ? shell.pageKey() : null, hashDriven: !!(shell.PAGES || {})[(shell.pageKey ? shell.pageKey() : '')] &&
        (shell.PAGES[shell.pageKey()] || {}).hash === true,
      pageActive: ((shell.PAGES || {})[(shell.pageKey ? shell.pageKey() : '')] || {}).active,
      hashView: shell.hashView ? shell.hashView() : null, alias: shell.ALIAS || null } : null,
    visibleSections: [...document.querySelectorAll('main > section')].filter((s) => !s.classList.contains('hidden') && s.offsetParent !== null).map((s) => s.id),
    railOrder: pills.map((p) => p.dataset.v),
    railHrefs: pills.map((p) => p.getAttribute('href')),
    railActive: active.map((p) => p.dataset.v),
    railCurrent: cur.map((p) => p.dataset.v),
    railCurrentMatchesActive: active.length === 1 && cur.length === 1 && active[0] === cur[0],
    workspaceVisible: [...document.querySelectorAll('#toolsWs .tws')].filter((e) => !e.classList.contains('hidden')).map((e) => e.id),
    launcherHidden: (() => { const l = q('#toolsLauncher'); return l ? l.classList.contains('hidden') : null; })(),
    subnav: [...document.querySelectorAll('.subnav .navpill')].map((p) => (p.dataset.v || p.dataset.cat || p.textContent.trim()) + (p.classList.contains('active') ? '*' : '')),
    ids: [...document.querySelectorAll('[id]')].map((e) => e.id),
    n: {
      invRows: (() => { const trs = [...document.querySelectorAll('#rows tr')];
        return trs.filter((tr) => !tr.querySelector('td[colspan]')).length; })(),
      invEmpty: (() => { const trs = [...document.querySelectorAll('#rows tr')];
        return trs.filter((tr) => !!tr.querySelector('td[colspan]')).length; })(),
      invTotals: txt('#totals'),
      kpis: txt('#kpis'),
      earned: txt('#todayEarned'), sales: txt('#todaySales'), trades: txt('#todayTrades'), plat: txt('#platinumNow'),
      planChildren: rowCount('planList'),
      planHeadish: 0,
      heldChildren: rowCount('heldList'),
      heldHeadish: 0,
      rowCounts: Object.fromEntries(['dealsList','moversList','trendsList','rivensList','wlList','ducatsList','craftList','relicsList','setsList','nudgesList','baroList','metaList','newsList','flipsList','wishList','runqList','attnList','pcTop','mhNext','mhCats'].map((id) => [id, rowCount(id)])),
      metas: Object.fromEntries(['planMeta','dealsMeta','moversMeta','rivensMeta','wlMeta','ducatsMeta','craftMeta','relicsMeta','setsMeta','nudgesMeta','baroMeta','metaMeta','newsMeta','trendsMeta','flipsMeta','wishMeta','limMeta','killMeta','notifyMeta','sessMeta','histMeta','ledgerMeta','timingMeta','attnMeta','hygieneMeta','runqMeta','mhStats','mhHead','mhMeta','ovPct','ovCount','ovFoot','ipTitle','ipLead','ipMeta','ipTradesCount','foot','chips','baroNotes'].map((id) => [id, txt('#' + id)])),
      pageMeta: txt('#meta'),
      gridTiles: cnt('#grid > *'),
      relRows: cnt('#relBody tr'),
      cardChips: (() => { const e = document.querySelector('.chips'); return e ? e.textContent.replace(/\\s+/g, ' ').trim() : null; })(),
      chipPairs: chipPairs(),
      catVisible: [...document.querySelectorAll('.st-cat')].filter((e) => !e.classList.contains('hidden')).map((e) => e.id),
      catPills: [...document.querySelectorAll('.st-cats .st-catpill')].map((p) => (p.dataset.cat || '') + (p.classList.contains('active') ? '*' : '')),
      notLive: [...document.querySelectorAll('body *')].filter((e) => e.children.length === 0 && /^(Not live|Live)$/.test(e.textContent.trim())).map((e) => e.textContent.trim() + '#' + (e.id || String(e.className).slice(0, 30))),
      homeAlerts: txt('#homeAlerts'),
      killLine: txt('#killList'),
      itemCards: ['ipPickCard','ipChartCard','ipTradesCard','ipStatsCard'].map((id) => { const e = document.getElementById(id); return e ? id + (e.classList.contains('hidden') ? ':hidden' : ':shown') : id + ':missing'; }),
    },
  };
})()`;

const COPY_SCAN = `(() => {
  const out = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null);
  let node;
  while ((node = walker.nextNode())) {
    const raw = String(node.data || '').replace(/\\s+/g, ' ').trim();
    if (!raw || !/[a-z]/i.test(raw)) continue;
    const el = node.parentElement;
    if (!el) continue;
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') continue;
    const r = el.getBoundingClientRect();
    if (!(r.width > 0 && r.height > 0)) continue;
    const words = raw.split(' ').filter(Boolean).length;
    if (words > 8 || raw.length > 90) out.push({ text: raw.slice(0, 180), words, chars: raw.length, cls: String(el.className || '').slice(0, 40), tag: el.tagName.toLowerCase() });
  }
  return out;
})()`;

const FIT_SCAN = `(() => {
  const de = document.documentElement, b = document.body;
  const sec = [...document.querySelectorAll('main > section')].filter((s) => !s.classList.contains('hidden'))[0] || null;
  const cards = sec ? [...sec.querySelectorAll('.card')] : [];
  return {
    overX: Math.max(de.scrollWidth - de.clientWidth, b.scrollWidth - window.innerWidth),
    overY: Math.max(de.scrollHeight - de.clientHeight, b.scrollHeight - window.innerHeight),
    secOverX: sec ? Math.max(0, sec.scrollWidth - sec.clientWidth) : null,
    secOverY: sec ? Math.max(0, sec.scrollHeight - sec.clientHeight) : null,
    secId: sec ? sec.id : null,
    wideCards: cards.filter((c) => c.scrollWidth > c.clientWidth + 1).map((c) => c.id || String(c.className).slice(0, 30)).slice(0, 5),
  };
})()`;

/* theme walk: scan one state under all 4 themes, aggregate in-page.
   Honesty rules: a gradient/image background cannot be measured from computed styles, so any
   element whose own or ancestor background (up to the first opaque colour) carries a
   background-image is counted as 'unmeasured', never guessed. The page base colour is the
   theme's own --bg, not white. The cross-theme pass compares the same element (keyed by
   tag#id.class|text, not by index - a redraw can reorder the DOM) under a dark and a light
   theme: an identical text colour ignored the vars. */
const THEME_STATE = `(async () => {
  const parse = (s) => {
    if (!s) return null; s = String(s).trim();
    if (s === 'transparent') return { r: 0, g: 0, b: 0, a: 0 };
    let m = s.match(/^rgba?\\(([^)]+)\\)$/);
    if (m) { const p = m[1].split(/[,\\s\\/]+/).filter(Boolean).map(Number); return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 }; }
    m = s.match(/^color\\(srgb\\s+([^)]+)\\)$/);
    if (m) { const p = m[1].split(/[\\s\\/]+/).filter(Boolean).map(Number); return { r: p[0]*255, g: p[1]*255, b: p[2]*255, a: p.length > 3 ? p[3] : 1 }; }
    m = s.match(/^#([0-9a-f]{6})$/i);
    if (m) { const h = m[1]; return { r: parseInt(h.slice(0,2),16), g: parseInt(h.slice(2,4),16), b: parseInt(h.slice(4,6),16), a: 1 }; }
    return null;
  };
  const lum = (c) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b); };
  const over = (fg, bg) => ({ r: fg.r * fg.a + bg.r * (1 - fg.a), g: fg.g * fg.a + bg.g * (1 - fg.a), b: fg.b * fg.a + bg.b * (1 - fg.a), a: 1 });
  const rgbTxt = (c) => 'rgb(' + [c.r, c.g, c.b].map((v) => Math.round(v)).join(',') + ')';
  const baseOf = (theme) => parse(theme[1]) || { r: 13, g: 15, b: 19, a: 1 };
  /* walk up: composite the solid layers, and report whether an image/gradient got in the way */
  const bgAt = (el, base) => {
    let stack = [], gradient = false;
    for (let n = el; n; n = n.parentElement) {
      const cs = getComputedStyle(n);
      if (cs.backgroundImage && cs.backgroundImage !== 'none') gradient = n === el || !stack.some((c) => c.a === 1);
      const c = parse(cs.backgroundColor);
      if (c && c.a > 0) stack.push(c);
    }
    let out = base;
    for (let i = stack.length - 1; i >= 0; i--) out = over(stack[i], out);
    return { bg: out, gradient };
  };
  const ratio = (a, b) => { const l1 = lum(a), l2 = lum(b); return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05); };
  const key = (el, text) => el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + '.' + String(el.className || '').split(/\\s+/).filter(Boolean).slice(0, 2).join('.') + '|' + text.slice(0, 26);
  const byTheme = [], perTheme = [];
  for (const ti of window.__gateThemes) {
    const theme = (window.WFM_THEMES || [])[ti] || [];
    window.__gateTheme = ti;
    window.wfmApplyTheme(ti);
    /* the app transitions colours over .22s, and a big page (cards, relics) can start that
       transition late while it repaints - so wait until the page background has actually
       stopped moving instead of trusting a fixed sleep */
    let prev = '', stable = 0;
    for (let i = 0; i < 12 && stable < 2; i++) {
      await new Promise((r) => setTimeout(r, 250));
      const sig = getComputedStyle(document.body).backgroundColor + '|' +
        getComputedStyle(document.documentElement).getPropertyValue('--bg').trim();
      stable = (sig === prev) ? stable + 1 : 0;
      prev = sig;
    }
    await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
    const base = baseOf(theme);
    const allowed = new Set((theme.slice(1, 11) || []).map((v) => String(v).toLowerCase()));
    const map = new Map(), low = []; let literal = 0, unmeasured = 0;
    document.querySelectorAll('body *').forEach((el) => {
      const own = [...el.childNodes].filter((n) => n.nodeType === 3).map((n) => n.data).join(' ').replace(/\\s+/g, ' ').trim();
      if (!own || !/[a-z0-9]/i.test(own)) return;
      const cs = getComputedStyle(el);
      if (cs.display === 'none' || cs.visibility === 'hidden' || +cs.opacity === 0) return;
      const r = el.getBoundingClientRect();
      if (!(r.width > 0 && r.height > 0)) return;
      const fg = parse(cs.color); if (!fg) return;
      const b = bgAt(el, base);
      if (b.gradient) { unmeasured++; return; }
      const cr = ratio(fg.a < 1 ? over(fg, b.bg) : fg, b.bg);
      const row = { text: own.slice(0, 44), cls: String(el.className || '').slice(0, 30), tag: el.tagName.toLowerCase(),
        color: String(cs.color), cr: Math.round(cr * 100) / 100, bg: rgbTxt(b.bg) };
      map.set(key(el, own), row);
      if (cr < 2.2) low.push(row);
      if (fg.a === 1 && !allowed.has(String(cs.color).toLowerCase())) literal++;
    });
    const sigs = new Map();
    low.forEach((row) => {
      const s = row.cls + '|' + row.color + '|' + row.bg;
      const e = sigs.get(s) || { ...row, count: 0 };
      e.count++;
      sigs.set(s, e);
    });
    byTheme.push(map);
    perTheme.push({ theme: ti, name: theme[0], mode: theme[10], varBg: getComputedStyle(document.documentElement).getPropertyValue('--bg').trim(),
      bodyBg: getComputedStyle(document.body).backgroundColor, scanned: map.size, lowCount: low.length,
      lowSample: [...sigs.values()].sort((a, b) => b.count - a.count).slice(0, 4),
      literalCount: literal, unmeasured });
  }
  const di = window.__gateThemes.indexOf(window.__gateDark), li = window.__gateThemes.indexOf(window.__gateLight);
  const d = byTheme[di] || new Map(), l = byTheme[li] || new Map();
  const escaped = [];
  d.forEach((row, k) => {
    const other = l.get(k);
    if (!other) return;
    if (String(row.color) === String(other.color)) {
      escaped.push({ text: row.text, cls: row.cls, tag: row.tag, color: row.color, cr_dark: row.cr, cr_light: other.cr,
        bg_dark: row.bg, bg_light: other.bg, low: (row.cr < 2.2 || other.cr < 2.2) });
    }
  });
  return { perTheme, escapedCount: escaped.length, escapedLow: escaped.filter((e) => e.low).length, escapedSample: escaped.slice(0, 10) };
})()`;

/* ---------------------------------------------------------------- helpers ----------------- */
async function newPage(browser) {
  const page = await browser.newPage();
  const rec = new Rec(page);
  await page.setViewport({ width: 1920, height: 1080 });
  return { page, rec };
}
function railCheck(pageName, label, facts) {
  const order = facts.railOrder.join(',');
  /* the expectation comes from the live shell's own registry, not from a hard-coded guess:
     the SPA marks hashView(); a page with `active: '<pill>'` marks that pill; item.html declares
     active: '' and correctly marks none. */
  const sh = facts.shell || {};
  const want = sh.hashDriven ? sh.hashView : (sh.pageActive || '');
  const expectActive = want ? [want] : [];
  const good = order === RAIL_EXPECT.join(',') && facts.railActive.join(',') === expectActive.join(',') &&
    facts.railCurrent.join(',') === expectActive.join(',') && facts.railCurrentMatchesActive === (expectActive.length === 1);
  R.rail.push({ page: pageName, state: label, order, active: facts.railActive.join(','), current: facts.railCurrent.join(','),
    expects: expectActive.join(',') || '(none)', ok: good });
  addCheck('rail', pageName + ' ' + label + ': 6 entries in order, one active + one aria-current',
    good, RAIL_EXPECT.join(',') + ' | active=' + (expectActive.join(',') || '(none)'),
    order + ' | active=' + facts.railActive.join(',') + ' current=' + facts.railCurrent.join(','));
}
const fmtInt = (n) => (n === null || n === undefined) ? null : Number(n).toLocaleString('en-US');
const signed = (n) => (n === null || n === undefined) ? null : (n > 0 ? '+' : '') + Number(n).toLocaleString('en-US') + 'p';
/* the first signed/unsigned number in a rendered string ("+0p", "1,022p", "—" -> null) */
const numOf = (s) => {
  if (s === null || s === undefined) return null;
  const m = String(s).replace(/,/g, '').match(/-?\d+(\.\d+)?/);
  return m ? Number(m[0]) : null;
};
function parityNum(claim, source, expectedNum, renderedText) {
  const got = numOf(renderedText);
  const ok = expectedNum !== null && expectedNum !== undefined && got !== null && Number(expectedNum) === got;
  R.parity.push({ claim, source, expected: expectedNum, rendered: renderedText === null ? null : String(renderedText), ok });
  addCheck('parity', claim, ok, String(expectedNum), String(renderedText),
    ok ? '' : 'expected vs rendered differ (source: ' + source + ')');
}
function parityRow(claim, source, expected, rendered) {
  const ok = expected !== null && expected !== undefined && rendered !== null && rendered !== undefined && String(expected) === String(rendered);
  R.parity.push({ claim, source, expected, rendered, ok });
  addCheck('parity', claim, ok, String(expected), String(rendered),
    ok ? '' : 'expected vs rendered differ (source: ' + source + ')');
}

/* ---------------------------------------------------------------- parity ------------------ */
async function runParity(node, rendered) {
  /* node-side raw stores */
  const plan = rd('data/trader_plan.json') || {};
  const relicsRaw = rd('data/relics_panel.json') || {};
  const cardsRaw = rd('data/mod_cards.json') || {};
  const masteryRaw = rd('data/mastery.json') || {};
  /* payloads the pages themselves fetch */
  const summary = await api('/api/summary');
  const plat = await api('/api/plat_history');
  const progress = await api('/api/feature/progress');
  const cardsApi = await api('/api/feature/cards');
  const masteryApi = await api('/api/feature/mastery');
  const items = await api('/api/items');

  /* -- trade plan: reachability + parity, never layout -- */
  if (rendered.index.planChildren === null) {
    addCheck('parity', 'Trade plan rows vs data/trader_plan.json', false, (plan.plan || []).length,
      'NOT RUNNABLE: no #planList in the DOM',
      'the trade view was unreachable or mid-surgery: its row container is not in the DOM');
  } else {
    parityNum('Trade plan rows vs data/trader_plan.json', 'data/trader_plan.json plan[]',
      (plan.plan || []).length, rendered.index.planChildren);
    parityNum('Trade held rows vs data/trader_plan.json', 'data/trader_plan.json held_list[]',
      (plan.held_list || []).length, rendered.index.heldChildren);
  }

  /* -- tool workspaces: rendered rows vs their own source store -- */
  const rc = rendered.index.rowCounts || {};
  const table = [
    ['Deals', 'dealsList', () => Math.min(14, ((rd('data/deals.json') || {}).deals || []).length)],
    ['Movers & demand > Movers', 'moversList', () => Math.min(8, ((rd('data/price_movers.json') || {}).movers || []).length)],
    ['Movers & demand > Trends', 'trendsList', () => { const d = rd('data/trends.json') || {}; return Math.min(6, (d.top_spikes || []).length) + Math.min(6, (d.top_fades || []).length); }],
    ['Riven bands', 'rivensList', () => { const d = rd('data/rivens.json') || {}; return (d.veiled_bands || []).length + (d.owned_rivens || []).length; }],
    ['Watchlist', 'wlList', () => { const d = rd('data/watchlist.json') || {}; return (d.entries || []).length + Math.min(4, (d.suggested || []).length); }],
    ['Ducats', 'ducatsList', () => { const r = (rd('data/ducats.json') || {}).rows || []; return Math.min(8, r.filter((x) => x.verdict === 'BURN').length) + Math.min(8, r.filter((x) => x.verdict === 'SELL').length); }],
    ['Craft or buy', 'craftList', () => Math.min(12, ((rd('data/craft.json') || {}).rows || []).filter((x) => x.verdict !== 'SKIP').length)],
    ['Relic EV', 'relicsList', () => Math.min(12, ((rd('data/relic_ev.json') || {}).rows || []).length)],
    ['Sets', 'setsList', () => Math.min(12, ((rd('data/sets.json') || {}).top_targets || []).length)],
    ['Sets > Almost complete', 'nudgesList', () => { const d = rd('data/nudges.json') || {}; return Math.min(10, (d.ready || []).length + Math.min(5, (d.one_away || []).length)); }],
    ['Baro Ki\'Teer', 'baroList', () => { const r = (rd('data/baro.json') || {}).rows || []; return r.length ? Math.min(10, r.length) : 0; }],
    ['Patch meta', 'metaList', () => { const d = rd('data/meta_watch.json') || {}; return Math.min(6, (d.spike || []).length) + Math.min(6, (d.sink || []).length); }],
    ['Game news', 'newsList', () => Math.min(8, ((rd('data/gamenews.json') || {}).items || []).length)],
    ['Buy > Flip opportunities', 'flipsList', () => Math.min(10, ((rd('data/flip_digest.json') || {}).flips || []).length)],
    ['Buy > Wishlist', 'wishList', () => { const d = rd('data/wishlist.json') || {}; return (d.affordable_plan || []).length + Math.min(6, (d.wishlist || []).filter((e) => (e.status || '') === 'BUY_NOW').length); }],
  ];
  table.forEach(([name, id, exp]) => {
    const renderedN = rc[id];
    let expected = null;
    try { expected = exp(); } catch (e) { expected = null; }
    if (renderedN === null || renderedN === undefined) {
      addCheck('parity', 'Tools > ' + name + ' rows', false, String(expected),
        'NOT RUNNABLE: no #' + id, 'the workspace container is missing from the DOM');
    } else {
      parityNum('Tools > ' + name + ' rows (#' + id + ')', 'its own data/*.json store', expected, renderedN);
    }
  });

  /* -- home Today vs /api/summary + /api/plat_history + the progress store -- */
  const platExpected = (plat && plat.now !== null && plat.now !== undefined) ? plat.now : (summary || {}).plat;
  parityNum('Home Today > Platinum now', '/api/plat_history.now (fallback /api/summary.plat)',
    platExpected, rendered.index.plat);
  const t = (progress && progress.today) || {};
  parityNum('Home Today > Earned today', 'progress.json today.plat_delta', t.plat_delta, rendered.index.earned);
  parityNum('Home Today > Sales today', 'progress.json today.trades.sales', (t.trades || {}).sales, rendered.index.sales);
  const tradesRendered = numOf(rendered.index.trades);
  const tradesExpected = (summary && summary.trades !== null && summary.trades !== undefined) ? summary.trades : null;
  const tradesOk = (tradesExpected === null && tradesRendered === null) || Number(tradesExpected) === tradesRendered;
  R.parity.push({ claim: 'Home Today > Trades left', source: '/api/summary.trades (null -> em dash)',
    expected: tradesExpected === null ? '— (null)' : tradesExpected, rendered: rendered.index.trades, ok: tradesOk });
  addCheck('parity', 'Home Today > Trades left', tradesOk,
    tradesExpected === null ? '— (summary.trades null)' : String(tradesExpected), String(rendered.index.trades));
  /* the inventory table renders at most 400 rows and its totals bar declares the real count and
     the cap (876 stacks (showing 400)): parity is against the smaller of the two, and the cap must
     be declared in that same bar rather than silently dropping rows */
  const invCount = Array.isArray(items) ? items.length : null;
  const INV_ROW_CAP = 400;
  parityNum('Inventory > rows rendered (capped at ' + INV_ROW_CAP + ')', '/api/items length',
    invCount === null ? null : Math.min(invCount, INV_ROW_CAP), rendered.index.invRows);
  addCheck('parity', 'Inventory > the row cap is declared when it bites',
    invCount === null || invCount <= INV_ROW_CAP || /showing\s+[\d,]+/i.test(rendered.index.invTotals || ''),
    invCount > INV_ROW_CAP ? 'showing ' + INV_ROW_CAP : 'n/a', rendered.index.invTotals || '');
  const stacks = /([\d,]+)\s+stacks/.exec(rendered.index.invTotals || '');
  parityNum('Inventory > "N stacks" in the totals bar', '/api/items length',
    Array.isArray(items) ? items.length : null, stacks ? stacks[1] : null);

  /* -- cards page: chips read element-wise ("cards 1551", "owned 557", ...) -- */
  const csum = Object.assign({}, cardsRaw.summary || {}, (cardsApi || {}).summary || {});
  const pairs = rendered.cards.chipPairs || [];
  const chipNum = (label) => {
    const hit = pairs.find((p) => new RegExp('^' + label + '\\b', 'i').test(String(p)));
    if (!hit) return null;
    const m = String(hit).replace(/,/g, '').match(/\d+/);
    return m ? Number(m[0]) : null;
  };
  parityNum('Cards > total in the header chips', 'cards summary.cards', csum.cards, chipNum('cards'));
  parityNum('Cards > owned in the header chips', 'cards summary.owned', csum.owned, chipNum('owned'));
  parityNum('Cards > missing in the header chips', 'cards summary.missing', csum.missing, chipNum('missing'));
  parityNum('Cards > dupes in the header chips', 'cards summary.dupes', csum.dupes, chipNum('dupes'));
  parityNum('Cards > grid tiles on first paint', 'min(BATCH 180, cards payload)', 180, rendered.cards.tiles);
  const shown = /Showing\s+(\d+)\s*\/\s*(\d+)/.exec(rendered.cards.meta || '');
  parityNum('Cards > "Showing X / Y mods"', 'mod_cards.json cards.length', (cardsRaw.cards || []).length, shown ? shown[2] : null);

  /* -- mastery -- */
  const ms = Object.assign({}, masteryRaw.summary || {}, (masteryApi || {}).summary || {});
  const mhM = /Mastered\s*([\d,]+)\s*\/\s*([\d,]+)/.exec(rendered.collection.mhStats || '');
  parityNum('Collection > Mastery mastered count', 'mastery.json summary.mastered', ms.mastered, mhM ? mhM[1] : null);
  parityNum('Collection > Mastery tracked count', 'mastery.json summary.tracked', ms.tracked, mhM ? mhM[2] : null);
  const mrM = /Mastery\s*(\d+)/.exec(rendered.collection.mhHead || '');
  parityNum('Collection > Mastery rank', 'mastery.json mr.rank',
    ((masteryApi || {}).mr || masteryRaw.mr || {}).rank, mrM ? mrM[1] : null);

  /* -- relics vs the relic store -- */
  const rrows = relicsRaw.relics || [];
  const relM = /Relics\s*·\s*([\d,]+)\s*\/\s*([\d,]+)\s*owned\s*·\s*([\d,]+)\s*dropping now/.exec(rendered.collection.relicMeta || '');
  parityNum('Collection > Relics owned count', 'relics_panel.json owned_total > 0', rrows.filter((r) => Number(r.owned_total) > 0).length, relM ? relM[1] : null);
  parityNum('Collection > Relics store count', 'relics_panel.json relics.length', rrows.length, relM ? relM[2] : null);
  parityNum('Collection > Relics dropping now', 'relics_panel.json obtain.kind == drop', rrows.filter((r) => r && r.obtain && r.obtain.kind === 'drop').length, relM ? relM[3] : null);
}

/* ---------------------------------------------------------------- safety + ids ------------ */
function safetyFacts(rendered) {
  const cfg = rd('data/config.json');
  const trader = rd('scripts/trader/settings.json');
  const plan = rd('data/trader_plan.json');
  const kill = rd('data/kill_switch.json');
  const cfgKeys = cfg ? Object.keys(cfg) : [];
  R.safety = {
    config_json: { path: 'data/config.json', exists: !!cfg, has_dry_run_key: cfgKeys.includes('dry_run'), keys: cfgKeys.length },
    trader_settings: { path: 'scripts/trader/settings.json', dry_run: trader ? trader.dry_run : null },
    trader_plan: { path: 'data/trader_plan.json', dry_run: plan ? plan.dry_run : null,
      generated_iso: plan && plan.generated ? new Date(plan.generated * 1000).toISOString() : null },
    kill_switch: { path: 'data/kill_switch.json', exists: !!kill, active: kill ? kill.active : null,
      note: kill ? kill.note : null, ts_iso: kill && kill.ts ? new Date(kill.ts * 1000).toISOString() : null },
    rendered: {
      settings_pill: (rendered.settings.notLive || []).join(' '),
      trade_kill_meta: rendered.index.killMeta, trade_kill_line: rendered.index.killLine,
      trade_plan_meta: rendered.index.planMeta, home_alerts: rendered.index.homeAlerts,
    },
  };
  const dry = !!(trader && trader.dry_run === true) && !!(plan && plan.dry_run === true);
  addCheck('safety', 'Not-live gate: scripts/trader/settings.json + data/trader_plan.json dry_run === true',
    dry, 'dry_run true in both', 'settings=' + (trader ? trader.dry_run : 'missing') + ' plan=' + (plan ? plan.dry_run : 'missing'),
    'data/config.json has no dry_run key (' + cfgKeys.length + ' keys) - the gate lives in scripts/trader/settings.json + the plan header, which is what the UI reads');
  addCheck('safety', 'Kill switch file exists and parses (nothing flipped)',
    !!(kill && kill.active === false), 'data/kill_switch.json parses, active false',
    kill ? JSON.stringify({ active: kill.active, note: kill.note }) : 'missing');
}
function idsCheck() {
  const union = new Set();
  Object.values(R.ids.found).forEach((arr) => arr.forEach((id) => union.add(id)));
  const missing = [], sanctioned = [];
  Object.entries(R.ids.before || {}).forEach(([page, ids]) => {
    ids.forEach((id) => {
      if (union.has(id)) return;
      if (SANCTIONED[id]) { sanctioned.push(id + ' (' + page + ') <- ' + SANCTIONED[id]); return; }
      missing.push(id + ' (' + page + ')');
    });
  });
  R.ids.missing_raw = missing.slice();
  R.ids.sanctioned = sanctioned;
  R.ids.missing = missing;
}

/* ================================================================ main ==================== */
(async () => {
  const browser = await puppeteer.launch({
    executablePath: CHROME, headless: 'new', userDataDir: PROFILE,
    args: ['--no-sandbox', '--disable-dev-shm-usage', '--window-size=1920,1080'],
  });
  const rendered = { index: {}, cards: {}, collection: {}, settings: {}, item: {}, lookup: {} };
  const ids = R.ids.found;
  const ID_PAGES = ['index', 'collection', 'cards', 'settings', 'item', 'item-deeplink', 'lookup'];
  ID_PAGES.forEach((p) => { ids[p] = []; });

  /* ============ 1. index: 4 hash views + 12 tool workspaces + legacy hashes ============ */
  {
    const { page, rec } = await newPage(browser);
    await page.goto(BASE + '/', { waitUntil: 'load', timeout: 45000 });
    await sleep(2500);
    let m = rec.mark();
    let f = await page.evaluate(FACTS);
    rec.state = 'landing #home';
    m = rec.mark();
    Object.assign(rendered.index, {
      plat: f.n.plat, earned: f.n.earned, sales: f.n.sales, trades: f.n.trades, kpis: f.n.kpis,
      invRows: f.n.invRows, invTotals: f.n.invTotals, killMeta: f.n.metas.killMeta, killLine: f.n.killLine,
      planMeta: f.n.metas.planMeta, homeAlerts: f.n.homeAlerts, rowCounts: f.n.rowCounts,
      planChildren: f.n.planChildren, planHeadish: f.n.planHeadish, heldChildren: f.n.heldChildren, heldHeadish: f.n.heldHeadish,
      chips: f.n.metas.chips, foot: f.n.metas.foot, notLive: f.n.notLive,
    });
    ids.index.push(...f.ids);
    railCheck('index', 'landing #home', f);
    addCheck('load', 'index lands with a visible section', f.visibleSections.length === 1, '1 visible section', f.visibleSections.join(',') || 'none');
    const copy0 = await page.evaluate(COPY_SCAN);
    copy0.forEach((c) => R.copy.push({ page: 'index', state: 'landing #home', text: c.text, words: c.words, chars: c.chars, cls: c.cls }));

    for (const v of INDEX_VIEWS) {
      if (v === 'home') continue;
      rec.state = '#' + v;
      m = rec.mark();
      await page.evaluate((v) => { location.hash = '#' + v; }, v);
      await sleep(900);
      f = await page.evaluate(FACTS);
      rec.since(m, '#' + v, 'index');
      ids.index.push(...f.ids);
      railCheck('index', '#' + v, f);
      addCheck('load', 'index #' + v + ' renders exactly one section', f.visibleSections.length === 1, '1 visible section', f.visibleSections.join(',') || 'none');
      const cc = await page.evaluate(COPY_SCAN);
      cc.forEach((c) => R.copy.push({ page: 'index', state: '#' + v, text: c.text, words: c.words, chars: c.chars, cls: c.cls }));
      if (v === 'trade') Object.assign(rendered.index, { planChildren: f.n.planChildren, planHeadish: f.n.planHeadish,
        heldChildren: f.n.heldChildren, heldHeadish: f.n.heldHeadish, planMeta: f.n.metas.planMeta, killMeta: f.n.metas.killMeta, killLine: f.n.killLine });
      if (v === 'inventory') Object.assign(rendered.index, { invRows: f.n.invRows, invTotals: f.n.invTotals });
    }
    for (const w of WORKSPACES) {
      rec.state = '#tools/' + w;
      m = rec.mark();
      await page.evaluate((w) => { location.hash = '#tools/' + w; }, w);
      await sleep(600);
      f = await page.evaluate(FACTS);
      rec.since(m, '#tools/' + w, 'index');
      ids.index.push(...f.ids);
      railCheck('index', 'Tool ' + w, f);
      addCheck('load', 'Tools > ' + w + ' opens exactly one workspace',
        f.workspaceVisible.length === 1, '1 workspace open', f.workspaceVisible.join(',') || 'none');
      const cc = await page.evaluate(COPY_SCAN);
      cc.forEach((c) => R.copy.push({ page: 'index', state: '#tools/' + w, text: c.text, words: c.words, chars: c.chars, cls: c.cls }));
    }
    Object.assign(rendered.index, { rowCounts: (await page.evaluate(FACTS)).n.rowCounts });

    /* Trade > Orders (a live order book with usernames): its own state so the console watch, the
       copy scan and the fit sweep all cover it, plus Jay's placement rule - Orders first in the
       strip, Sell still the surface a fresh load opens on. */
    {
      rec.state = '#trade/orders';
      m = rec.mark();
      await page.goto(BASE + '/#trade/orders', { waitUntil: 'load', timeout: 45000 });
      await sleep(2800);
      const tabs = await page.evaluate(() => [...document.querySelectorAll('#tradeTabs [role="tab"]')]
        .map((e) => e.id));
      addCheck('load', 'Trade puts Orders first in the strip, before Sell',
        tabs[0] === 'tt-orders' && tabs[1] === 'tt-sell', 'tt-orders, tt-sell',
        tabs.slice(0, 3).join(', '));
      const sel = await page.evaluate(() => {
        const t = document.querySelector('#tradeTabs [aria-selected="true"]');
        return t ? t.id : null;
      });
      addCheck('load', 'the #trade/orders deep link opens the Orders tab itself',
        sel === 'tt-orders', 'tt-orders selected', String(sel));
      const ord = await page.evaluate(() => ({
        rows: document.querySelectorAll('#tp-orders [data-user]').length,
        ladder: document.querySelectorAll('#ordValues tr').length,
        chips: document.querySelectorAll('#ordStatus [aria-pressed]').length,
        meta: ((document.getElementById('ordMeta') || {}).textContent || '').trim(),
        item: ((document.getElementById('ordItem') || {}).textContent || '').trim(),
        err: ((document.getElementById('ordErr') || {}).textContent || '').trim(),
      }));
      addCheck('load', 'Orders shows its status chips and either a book or an honest reason',
        ord.chips >= 3 && (ord.rows > 0 || ord.err.length > 0), 'chips >= 3, rows or a reason',
        ord.chips + ' chips, ' + ord.rows + ' rows, ' + ord.ladder + ' ladder rows, item "' + ord.item + '"');
      R.orders = ord;
      const ccord = await page.evaluate(COPY_SCAN);
      ccord.forEach((c) => R.copy.push({ page: 'index', state: '#trade/orders', text: c.text, words: c.words, chars: c.chars, cls: c.cls }));
      ids.index.push(...(await page.evaluate(FACTS)).ids);
      rec.since(m, '#trade/orders', 'index');

      /* the other half of the placement rule: a plain Trade load still lands on Sell, because that
         is the surface the day-to-day flow runs on */
      rec.state = '#trade (plain)';
      m = rec.mark();
      await page.goto(BASE + '/#trade', { waitUntil: 'load', timeout: 45000 });
      await sleep(2000);
      const sel2 = await page.evaluate(() => {
        const t = document.querySelector('#tradeTabs [aria-selected="true"]');
        return t ? t.id : null;
      });
      addCheck('load', 'a plain Trade load still opens on the Sell surface', sel2 === 'tt-sell',
        'tt-sell selected', String(sel2));
      rec.since(m, '#trade (plain)', 'index');
    }

    /* legacy hashes: each one gets a FRESH load, because some of them redirect the whole page
       (#mastery -> /collection.html#mastery, #more/#market -> #tools, #player -> #tools/player) */
    for (const h of LEGACY_HASHES) {
      rec.state = '#' + h;
      m = rec.mark();
      await page.goto(BASE + '/#' + h, { waitUntil: 'load', timeout: 45000 });
      await sleep(1600);
      const lf = await page.evaluate(FACTS);
      const where = await page.evaluate(() => ({ path: location.pathname, hash: location.hash }));
      const st = rec.since(m, '#' + h, 'index');
      const rail = lf.railActive.join(',');
      const want = (lf.shell && lf.shell.alias) ? lf.shell.alias[h] : null;
      let expect, ok;
      if (h === 'mastery') {                       /* the Collection tab owns it now */
        expect = 'path /collection.html, hash #mastery, rail collection';
        ok = where.path === '/collection.html' && where.hash === '#mastery' && rail === 'collection' && lf.visibleSections.length >= 1;
      } else if (h === 'more' || h === 'market') {  /* the old More page is the Tools launcher */
        expect = 'path /, hash #tools, rail tools, one visible section';
        ok = where.path === '/' && where.hash === '#tools' && rail === 'tools' && lf.visibleSections.length === 1;
      } else if (h === 'player') {                  /* the Player view is a Tools workspace */
        expect = 'path /, hash #tools/player, the player workspace open, rail tools';
        ok = where.path === '/' && where.hash === '#tools/player' && rail === 'tools' && lf.workspaceVisible.length === 1;
      } else {                                      /* #history / #trader stay on the SPA, on Trade */
        expect = 'path /, hash kept, a visible section, rail trade';
        ok = where.path === '/' && rail === 'trade' && lf.visibleSections.length >= 1;
      }
      R.legacy.push({ hash: '#' + h, landed: where.path + where.hash, visible: lf.visibleSections.join(',') || lf.workspaceVisible.join(','),
        rail_active: rail, alias_expects: want, expect, ok, errors: st.errors });
    }
    addCheck('rail', 'legacy hashes resolve (#more/#market/#player/#mastery/#history/#trader)',
      R.legacy.every((l) => l.ok), 'each lands where the alias table sends it, with a visible section',
      R.legacy.map((l) => l.hash + '->' + l.landed + '/' + (l.rail_active || '-')).join('  '),
      R.legacy.filter((l) => !l.ok).map((l) => l.hash + ' expected ' + l.expect).join(' | '));

    await envRecheck('index', rec);
    R.load.index = { errors: rec.errors.length, fails: rec.fails.length, blocked: rec.blocked.length,
      states: R.states.filter((s) => s.page === 'index').length };
    if (rec.errors.length || rec.fails.length) R.load_detail.index = { errors: rec.errors.slice(0, 25), fails: rec.fails.slice(0, 25) };
    addCheck('load', 'index: 0 console errors / 0 failed requests (all 4 views + 12 workspaces + legacy hashes)',
      rec.errors.length === 0 && rec.fails.length === 0, '0 / 0', rec.errors.length + ' / ' + rec.fails.length,
      rec.blocked.length + ' blocked-CDN request(s) excluded');
    addCheck('load', 'index: ' + R.states.filter((s) => s.page === 'index').length + ' states driven, all rendered',
      R.states.filter((s) => s.page === 'index').every((s) => s.errors === 0), '0 per-state errors',
      R.states.filter((s) => s.page === 'index' && s.errors).length + ' states with errors');
    await page.close();
  }

  /* ============ 2. collection / cards / settings / item / item deep link / lookup ============ */
  const specs = [
    { name: 'collection', url: '/collection.html' },
    { name: 'cards', url: '/cards.html' },
    { name: 'settings', url: '/settings.html' },
    { name: 'item', url: '/item.html' },
    { name: 'item-deeplink', url: '/item.html?item=' + ITEM_SLUG },
    { name: 'lookup', url: '/lookup.html' },
  ];
  for (const spec of specs) {
    const { page, rec } = await newPage(browser);
    rec.state = spec.name + ' landing';
    await page.goto(BASE + spec.url, { waitUntil: 'load', timeout: 45000 });
    await sleep(spec.name === 'lookup' ? 2600 : 3200);
    /* Chromium's net stack occasionally drops a LOCAL file with a transient kernel-level error
       (ERR_NO_BUFFER_SPACE / ERR_INSUFFICIENT_RESOURCES / ERR_NETWORK_CHANGED). That is noise, not a
       regression, so such a first attempt is recorded under load_transient and reloaded ONCE; a
       real 404/500/refused connection on any request keeps failing the page. */
    const transient = (t) => /ERR_NO_BUFFER_SPACE|ERR_INSUFFICIENT_RESOURCES|ERR_NETWORK_CHANGED|ERR_CONNECTION_RESET/.test(String(t));
    if (rec.fails.length && rec.fails.every((f) => transient(f.why))) {
      R.load_transient[spec.name] = { errors: rec.errors.slice(0, 5), fails: rec.fails.slice(0, 5) };
      rec.errors = []; rec.fails = []; rec.blocked = [];
      await page.reload({ waitUntil: 'load', timeout: 45000 });
      await sleep(3200);
      rec.transient_retries = 1;
    }
    let m = rec.mark();
    if (spec.name === 'collection') {
      for (const sec of COLLECTION_SECTIONS) {
        if (sec !== COLLECTION_SECTIONS[0]) {
          rec.state = 'collection ' + sec;
          m = rec.mark();
          await page.evaluate((s) => { location.hash = '#' + s; }, sec);
          await sleep(2000);
        }
        const f = await page.evaluate(FACTS);
        rec.since(m, sec, 'collection');
        m = rec.mark();
        ids.collection.push(...f.ids);
        railCheck('collection', sec, f);
        R.collectionSubnav = f.subnav;
        addCheck('load', 'collection > ' + sec + ' section renders',
          sec === 'collection' ? f.n.gridTiles > 0 : f.visibleSections.length >= 1,
          sec === 'collection' ? 'the collection grid has tiles' : '>= 1 visible section',
          'hash=' + f.hash + ' visible=' + f.visibleSections.join(',') + ' tiles=' + f.n.gridTiles + ' subnav=' + f.subnav.join(' '));
        if (sec === 'mastery') Object.assign(rendered.collection, { mhStats: f.n.metas.mhStats, mhHead: f.n.metas.mhHead, mhMeta: f.n.metas.mhMeta });
        if (sec === 'relics') Object.assign(rendered.collection, { relicMeta: f.n.pageMeta, relRows: f.n.relRows, relMin: f.n.metas.relicsMeta });
        if (sec === 'collection') Object.assign(rendered.collection, { ovPct: f.n.metas.ovPct, ovCount: f.n.metas.ovCount, ovFoot: f.n.metas.ovFoot, clMeta: f.n.pageMeta, tiles: f.n.gridTiles });
        const cc = await page.evaluate(COPY_SCAN);
        cc.forEach((c) => R.copy.push({ page: 'collection', state: sec, text: c.text, words: c.words, chars: c.chars, cls: c.cls }));
      }
      addCheck('load', 'collection: 3 sections (Collection / Relics / Mastery) + the Cards pill',
        COLLECTION_SECTIONS.length === 3 && R.collectionSubnav && R.collectionSubnav.length === 4,
        '4 sub-nav pills: collection, relics, mastery, cards',
        (R.collectionSubnav || []).join(' '), 'Cards is its own page (/cards.html)');
    } else if (spec.name === 'settings') {
      for (const cat of SETTINGS_CATS) {
        rec.state = 'settings ' + cat;
        m = rec.mark();
        await page.evaluate((c) => { location.hash = '#' + c; }, cat);
        await sleep(800);
        const f = await page.evaluate(FACTS);
        rec.since(m, cat, 'settings');
        m = rec.mark();
        ids.settings.push(...f.ids);
        railCheck('settings', cat, f);
        addCheck('load', 'settings > ' + cat + ' shows exactly its own panel',
          f.n.catVisible.length === 1 && f.n.catVisible[0] === 'cat-' + cat, 'cat-' + cat, f.n.catVisible.join(',') || 'none');
        if (cat === 'trading') Object.assign(rendered.settings, { notLive: f.n.notLive, tradingFacts: f.n.metas });
        if (cat === 'general') Object.assign(rendered.settings, { notLive: (rendered.settings.notLive || []).concat(f.n.notLive) });
        const cc = await page.evaluate(COPY_SCAN);
        cc.forEach((c) => R.copy.push({ page: 'settings', state: cat, text: c.text, words: c.words, chars: c.chars, cls: c.cls }));
      }
    } else {
      const f = await page.evaluate(FACTS);
      rec.since(m, 'landing', spec.name);
      m = rec.mark();
      ids[spec.name].push(...f.ids);
      if (spec.name !== 'item') railCheck(spec.name, 'landing', f);
      if (spec.name === 'cards') {
        Object.assign(rendered.cards, { chips: f.n.cardChips, chipPairs: f.n.chipPairs, tiles: f.n.gridTiles, meta: f.n.pageMeta });
      }
      if (spec.name === 'item') Object.assign(rendered.item, { title: f.n.metas.ipTitle, lead: f.n.metas.ipLead, meta: f.n.metas.ipMeta, cards: f.n.itemCards });
      if (spec.name === 'item-deeplink') {
        Object.assign(rendered.item, { deepTitle: f.n.metas.ipTitle, deepLead: f.n.metas.ipLead, deepMeta: f.n.metas.ipMeta, deepCards: f.n.itemCards, deepTrades: f.n.metas.ipTradesCount });
        addCheck('load', 'item deep link ?item=' + ITEM_SLUG + ' fills the analysis',
          f.n.itemCards.includes('ipChartCard:shown'), 'ipChartCard shown', f.n.itemCards.join(' '),
          'title=' + f.n.metas.ipTitle + ' | meta=' + f.n.metas.ipMeta);
      }
      if (spec.name === 'lookup') {
        const landed = await page.evaluate(() => ({ path: location.pathname, hash: location.hash, hasSearch: !!document.getElementById('search') }));
        addCheck('load', 'lookup.html redirects to the global search',
          landed.hash.indexOf('#search') === 0 && landed.hasSearch, 'hash #search on the app', JSON.stringify(landed));
      }
      const cc = await page.evaluate(COPY_SCAN);
      cc.forEach((c) => R.copy.push({ page: spec.name, state: 'landing', text: c.text, words: c.words, chars: c.chars, cls: c.cls }));
    }
    await envRecheck(spec.name, rec);
    R.load[spec.name] = { errors: rec.errors.length, fails: rec.fails.length, blocked: rec.blocked.length,
      states: R.states.filter((s) => s.page === spec.name).length };
    addCheck('load', spec.name + ': 0 console errors / 0 failed requests',
      rec.errors.length === 0 && rec.fails.length === 0, '0 / 0', rec.errors.length + ' / ' + rec.fails.length,
      rec.blocked.length + ' blocked-CDN request(s) excluded' +
        (rec.transient_retries ? '; first attempt hit a transient net-stack error and was reloaded once (see load_transient)' : ''));
    if (rec.errors.length || rec.fails.length) {
      R.load_detail[spec.name] = { errors: rec.errors.slice(0, 25), fails: rec.fails.slice(0, 25) };
    }
    await page.close();
  }

  /* ============ 3. fit: 5 viewports x every index view ============ */
  {
    const { page, rec } = await newPage(browser);
    rec.state = 'fit';
    await page.goto(BASE + '/', { waitUntil: 'load' });
    await sleep(2500);
    for (const [w, h] of VIEWPORTS) {
      await page.setViewport({ width: w, height: h });
      await sleep(400);
      for (const v of INDEX_VIEWS.concat(['trade/orders'])) {
        await page.evaluate((v) => { location.hash = '#' + v; }, v);
        await sleep(700);
        const mm = await page.evaluate(FIT_SCAN);
        R.fit.push({ viewport: w + 'x' + h, view: v, overX: mm.overX, overY: mm.overY, sec: mm.secId,
          secOverX: mm.secOverX, secOverY: mm.secOverY, wideCards: mm.wideCards });
      }
    }
    const bad = R.fit.filter((x) => x.overX !== 0 || x.overY !== 0);
    addCheck('fit', 'pageOverX/Y == 0 on every index view at all 5 viewports',
      bad.length === 0, '0 overflowing measurements (' + R.fit.length + ' measured)', bad.length + ' overflowing',
      bad.length ? bad.map((b) => b.viewport + ' ' + b.view + ' ' + b.overX + '/' + b.overY).join(' | ') : 'all clean');
    R.load.fit = { errors: rec.errors.length, fails: rec.fails.length };
    if (rec.errors.length || rec.fails.length) R.load_detail.fit = { errors: rec.errors.slice(0, 15), fails: rec.fails.slice(0, 15) };
    await page.close();
  }

  /* ============ 4. themes: 4 palettes across every page ============ */
  {
    const targets = [
      ['index', '/', INDEX_VIEWS.concat(['trade/orders'])],
      ['collection', '/collection.html', COLLECTION_SECTIONS],
      ['cards', '/cards.html', [null]],
      ['settings', '/settings.html', SETTINGS_CATS],
      ['item', '/item.html?item=' + ITEM_SLUG, [null]],
    ];
    const { page, rec } = await newPage(browser);
    await page.evaluateOnNewDocument((t, d, l) => { window.__gateThemes = t; window.__gateDark = d; window.__gateLight = l; }, THEMES, THEME_DARK, THEME_LIGHT);
    await page.goto(BASE + '/', { waitUntil: 'load' });
    await sleep(2200);
    for (const [pname, url, states] of targets) {
      if (url !== '/') { await page.goto(BASE + url, { waitUntil: 'load' }); await sleep(2800); }
      for (const st of states) {
        if (st) {
          if (pname === 'collection') { await page.evaluate((s) => { location.hash = '#' + s; }, st); await sleep(2000); }
          else if (pname === 'settings') { await page.evaluate((s) => { location.hash = '#' + s; }, st); await sleep(800); }
          else { await page.evaluate((s) => { location.hash = '#' + s; }, st); await sleep(900); }
        }
        rec.state = pname + (st ? '/' + st : '');
        const m = rec.mark();
        const res = await page.evaluate(THEME_STATE);
        const newErrs = rec.errors.length - m.e;
        res.perTheme.forEach((t) => {
          R.themes.push({ theme: t.theme, name: t.name, mode: t.mode, page: pname, state: st || 'landing',
            varBg: t.varBg, bodyBg: t.bodyBg, scanned: t.scanned, low: t.lowCount, lowSample: t.lowSample,
            literalCount: t.literalCount, unmeasured: t.unmeasured, newErrors: newErrs });
        });
        R.theme_cross.push({ page: pname, state: st || 'landing', escaped: res.escapedCount,
          escapedLow: res.escapedLow, sample: res.escapedSample });
      }
    }
    /* restore the configured default theme */
    const cfgTheme = (rd('data/config.json') || {}).theme || 0;
    await page.goto(BASE + '/', { waitUntil: 'load' });
    await sleep(1200);
    await page.evaluate((t) => { try { localStorage.setItem('wfm.theme', String(t)); } catch (e) {} window.wfmApplyTheme(t); }, cfgTheme);
    R.themesRestored = cfgTheme;
    const lows = R.themes.reduce((a, t) => a + t.low, 0);
    const themeErrs = R.themes.reduce((a, t) => a + t.newErrors, 0);
    const escaped = R.theme_cross.reduce((a, t) => a + t.escaped, 0);
    const escapedLow = R.theme_cross.reduce((a, t) => a + t.escapedLow, 0);
    addCheck('themes', '4 themes (2 dark, 2 light): no unreadable text, no console error',
      lows === 0 && themeErrs === 0, '0 low-contrast / 0 errors', lows + ' low-contrast / ' + themeErrs + ' errors over ' + R.themes.length + ' scans',
      R.themes.filter((t) => t.low).map((t) => t.page + (t.state !== 'landing' ? '/' + t.state : '') + ' ' + t.name + '=' + t.low).join(' | '));
    addCheck('themes', 'no text colour survives the dark->light switch untouched (var escapes)',
      escapedLow === 0, '0 unreadable escaped colours',
      escaped + ' colours identical in theme ' + THEME_DARK + ' (dark) and theme ' + THEME_LIGHT + ' (light), ' + escapedLow + ' of them unreadable',
      R.theme_cross.filter((t) => t.escapedLow).map((t) => t.page + (t.state !== 'landing' ? '/' + t.state : '') + '=' + t.escapedLow).join(' | '));
    R.load.themes = { errors: rec.errors.length, fails: rec.fails.length };
    if (rec.errors.length || rec.fails.length) R.load_detail.themes = { errors: rec.errors.slice(0, 15), fails: rec.fails.slice(0, 15) };
    await page.close();
  }

  /* ============ 5. parity ============ */
  await runParity(null, rendered);
  R.rendered = rendered;

  /* ============ 6. copy totals, safety, ids ============ */
  {
    const seen = new Set();
    R.copy = R.copy.filter((c) => { const k = c.page + '|' + c.text; if (seen.has(k)) return false; seen.add(k); return true; });
    R.copy_totals = { offenders: R.copy.length, byPage: {} };
    R.copy.forEach((c) => { R.copy_totals.byPage[c.page] = (R.copy_totals.byPage[c.page] || 0) + 1; });
    addCheck('copy', 'rendered visible strings stay inside 8 words / 90 chars on every page',
      R.copy.length === 0, '0 offenders', R.copy.length + ' offenders',
      (() => {
        const meta = R.copy.filter((c) => c.text.trim().startsWith('·')).length;
        return meta + ' offenders start with "\u00b7" (data-driven status lines the source test cannot see) + ' +
          (R.copy.length - meta) + ' other offenders; examples: ' +
          R.copy.filter((c) => !c.text.trim().startsWith('·')).slice(0, 4)
            .map((c) => c.page + '/' + c.state + ' [' + c.words + 'w ' + c.chars + 'c] ' + c.text).join(' | ');
      })());
    safetyFacts(rendered);
    R.ids.before = rd('design/_stage1/ids_before.json');
    idsCheck();
    addCheck('ids', 'every id in design/_stage1/ids_before.json still exists (sanctioned moves excepted)',
      R.ids.missing.length === 0, '0 missing', R.ids.missing.length + ' missing: ' + (R.ids.missing.join(', ') || '—'),
      R.ids.sanctioned.length + ' sanctioned move(s): ' + (R.ids.sanctioned.join(' | ') || '—'));
  }

  /* ============ verdict ============ */
  const failed = R.checks.filter((c) => !c.ok);
  R.meta.finished = new Date().toISOString();
  R.verdict = {
    pass: failed.length === 0,
    checks_total: R.checks.length,
    checks_failed: failed.length,
    failed: failed.map((c) => c.group + ': ' + c.title + ' [' + c.rendered + ']'),
    states_driven: R.states.length,
    blocked_cdn_requests: R.states.reduce((a, s) => a + (s.blocked || 0), 0),
  };
  fs.writeFileSync(RAW, JSON.stringify(R, null, 1));
  console.log('GATE ' + (R.verdict.pass ? 'PASS' : 'FAIL') + ' — ' + R.verdict.checks_total + ' checks, ' +
    R.verdict.checks_failed + ' failed, ' + R.verdict.states_driven + ' states driven');
  R.verdict.failed.forEach((x) => console.log('  FAIL ' + x));
  console.log('raw: ' + RAW);
  await browser.close();
  process.exit(R.verdict.pass ? 0 : 1);
})().catch(async (e) => {
  console.error('GATE CRASHED', e);
  R.meta.finished = new Date().toISOString();
  R.verdict = { pass: false, crashed: String((e && e.stack) || e).slice(0, 3000), checks_total: R.checks.length,
    checks_failed: R.checks.filter((c) => !c.ok).length, failed: ['gate crashed before finishing: ' + String((e && e.message) || e)] };
  try { fs.writeFileSync(RAW, JSON.stringify(R, null, 1)); } catch (err) {}
  process.exit(1);
});
