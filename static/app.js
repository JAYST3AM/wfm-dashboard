/* WFM Trader — dashboard frontend (vanilla JS) */
'use strict';

const THEMES = window.WFM_THEMES; /* single source: static/theme.js */
const TVARS = ['bg', 'panel', 'panel2', 'border', 'text', 'muted', 'accent', 'accentDim', 'hover'];

function applyTheme(i) { wfmApplyTheme(i); }

function buildThemeGrid() { wfmBuildThemeGrid(); }

/* ---------- data ---------- */
let ITEMS = [], SUMMARY = null, PLAT = null, REPORT = null, TRADES = null, TRADER = null, GAMENEWS = null, FEAT = {};
let state = { tab: 'all', sort: 'value', dir: -1, q: '', itemhist: {}, materials: null, matView: 'personal', matSort: 'count', matQ: '', dojoTier: 'ghost', player: null, cfg: null };
/* global item search cache - declared up here because the hash router can call into
   the search before the rest of the file has run (classic script, no module scope) */
/* Jay's wording (2026-09-26): posting is 'Live' or 'Not live' - never 'dry run'. The one
   surface that printed a plan's raw mode was the flipper-internals card, retired 2026-09-27, so
   the mapper went with it: nothing renders a mode string any more (see tests/test_terminology). */

let CATALOG = null, CATALOG_LOADING = null;

const CATS = [
  ['all', 'All'], ['prime_part', 'Prime Parts'], ['prime_bp', 'Blueprints'],
  ['relic', 'Relics'], ['arcane', 'Arcanes'], ['mod', 'Mods'], ['other', 'Other']
];
const CAT_LABEL = Object.fromEntries(CATS);

const fmt = n => (n === null || n === undefined) ? '—' : n.toLocaleString();
/* empty / idle states: one quiet 18px icon above the line (styling: .empty-icon in style.css) */
const EMPTY_ICON = '<span class="empty-icon" data-icon="tray" data-icon-size="18"></span>';
const ago = ts => {
  if (!ts) return '—';
  const s = Math.max(0, Math.floor(Date.now() / 1000 - ts));
  if (s < 90) return s + 's ago';
  if (s < 5400) return Math.round(s / 60) + 'm ago';
  return Math.round(s / 3600) + 'h ago';
};

function renderChips() {
  const s = SUMMARY; if (!s) return;
  /* "Priced" counts owned rows that carry a live sell price (prices.json wts), out of owned rows -
     one basis, both numbers from /api/summary. It is not the price-feed coverage: that file holds a
     record for every owned slug, so the old "Prices 803/863" label read as if 60 rows had no price
     data at all. The rows without a live quote are the ones the title names. */
  const unquoted = Math.max(0, (s.items ?? 0) - (s.priced ?? 0));
  document.getElementById('chips').innerHTML = `
    <span class="chip">MR <b>${s.mr ?? '—'}</b></span>
    <span class="chip warn">Trades <b>${s.trades ?? '—'}</b>/day left</span>
    <span class="chip" title="owned rows with a live sell price / owned rows · ${unquoted} no live quote">Priced <b>${s.priced ?? 0}/${s.items ?? 0}</b></span>
`;
}

/* ---------- views ---------- */
/* Stage 2 (2026-09-28): four hash views on this page. Mastery moved into Collection (its own
   tab) and the Player profile became a Tools workspace, so neither is a destination of its own
   any more - #mastery redirects to /collection.html#mastery and #player to #tools/player. */
const VIEWS = ['home', 'inventory', 'trade', 'tools'];
/* legacy hashes still resolve: #history/#trader -> trade, #market/#more -> tools,
   #player -> the Tools player workspace, #mastery -> the Collection tab */
const VIEW_ALIAS = { home: 'home', inventory: 'inventory', trade: 'trade', tools: 'tools',
  more: 'tools', market: 'tools', player: 'tools', history: 'trade', trader: 'trade' };

/* the Tools workspaces, in launcher order: slug -> the list ids it owns. Every one is reachable
   by hash (#tools/<slug>); '' is the launcher itself. Keep in step with the markup in
   index.html and with tests/test_ia_reachability.py. */
const TOOL_SLUGS = ['deals', 'trends', 'rivens', 'wl', 'ducats', 'craft', 'relicev', 'sets',
  'baro', 'meta', 'news', 'player'];

function showView(v, sub) {
  if (!VIEWS.includes(v)) v = 'home';
  VIEWS.forEach(name => {
    const el2 = document.getElementById('view-' + name);
    if (el2) el2.classList.toggle('hidden', name !== v);
  });
  /* The rail's mark moves with the router, in BOTH of its forms: .active is the paint and
     aria-current="page" is the same fact for a screen reader (shell.js sets it at mount, so a
     view switch used to leave it on Home - audit M1). The two may never disagree. */
  document.querySelectorAll('#mainnav .navpill').forEach(el2 => {
    const on = el2.dataset.v === v;
    el2.classList.toggle('active', on);
    if (on) el2.setAttribute('aria-current', 'page');
    else el2.removeAttribute('aria-current');
  });
  if (window.PlatChart) PlatChart.redraw();
  if (v === 'trade') markScrollers();
  if (v === 'tools') showTool(sub || '');
  if (v === 'home' && window.wfmRenderHome) wfmRenderHome();
}

/* Tools: one focused workspace at a time. The launcher (#tools) is the default, #tools/<slug>
   opens that tool, and the player workspace is where the old Player view lives now. */
function showTool(slug) {
  if (TOOL_SLUGS.indexOf(slug) < 0) slug = '';
  const launcher = document.getElementById('toolsLauncher');
  if (launcher) launcher.classList.toggle('hidden', !!slug);
  TOOL_SLUGS.forEach(s => {
    /* by data-tool, not by id: the player workspace keeps the old #view-player id so its own
       stylesheet rules and the tests that pin them still describe the moved content */
    const el = document.querySelector('#toolsWs [data-tool="' + s + '"]');
    if (el) el.classList.toggle('hidden', s !== slug);
  });
  if (slug === 'player') renderPlayerPage();
}

/* trade sub-tabs (Sell / Buy / History) */
function switchTradeTab(panelId) {
  const tabs = document.querySelectorAll('#tradeTabs [role="tab"]');
  if (!tabs.length) return;
  const ok = [...tabs].some(t => t.dataset.tp === panelId);
  if (!ok) panelId = 'tp-sell';
  tabs.forEach(t => t.setAttribute('aria-selected', String(t.dataset.tp === panelId)));
  document.querySelectorAll('#view-trade .tpanel').forEach(p2 => p2.classList.toggle('hidden', p2.id !== panelId));
  markScrollers();
}

function applyHash() {
  const raw = (location.hash || '#home').slice(1);
  const [path, query] = raw.split('?');
  const [v, sub] = path.split('/');
  if (v === 'collection' || v === 'cards') { location.replace('/' + v + '.html'); return; }
  /* legacy destinations that are sections now: Mastery is a Collection tab, the old More page and
     the Player view are Tools. The hash is rewritten (replaceState-style, no history entry) so the
     address always names the surface that is showing - nothing that resolved before 404s. */
  if (v === 'mastery') { location.replace('/collection.html#mastery'); return; }
  if (v === 'more' || v === 'market') { location.replace('#tools'); return; }
  if (v === 'player') { location.replace('#tools/player'); return; }
  if (v === 'search') {
    showView('home');
    globalSearchOpen((new URLSearchParams(query || '')).get('q') || '');
    return;
  }
  const view = VIEW_ALIAS[v] || 'home';
  showView(view, sub);
  if (view === 'trade') {
    switchTradeTab(v === 'history' ? 'tp-history' : (sub ? 'tp-' + sub : 'tp-sell'));
  }
}

/* first run: setup has not built any data yet - say exactly what to do instead of
   showing empty cards (a fresh clone has no data/ at all; SUMMARY comes back empty).
   The banner may only speak when there is genuinely NOTHING behind the page. One real reading -
   a save file, the price feed, an inventory row, a catalogue total, a platinum snapshot - means
   setup has already run, and then the "no data yet" card would be a lie (screenshot review,
   2026-09-28: it showed over a 1,022p balance, a sell queue and 471 history events). */
function hasAnyData(s) {
  if (!s) return false;
  if (s.lastdata_mtime || s.prices_mtime) return true;      /* a pipeline wrote a file */
  if (s.items || s.priced || s.total_value || s.total_value_owned) return true;
  const cats = s.by_cat || {};
  if (Object.keys(cats).some(k => Number(cats[k]) > 0)) return true;
  const pts = (s.plat_hist || {}).points || [];
  return pts.length > 0;
}

function renderFirstRun() {
  const el = document.getElementById('firstRun');
  if (!el) return;
  const empty = !hasAnyData(SUMMARY);
  el.classList.toggle('hidden', !empty);
  if (!empty) { el.innerHTML = ''; return; }
  el.innerHTML = `
    <div class="card-head"><div class="card-title" data-icon="tray">First run - no data yet</div></div>
    <div class="picks">
      <div class="picks-note"><b>Windows:</b> double-click <code>setup.bat</code> in the project folder.
        It installs the one dependency, reads your AlecaFrame inventory and fetches prices
        (20-40 minutes, resumable — stop it any time and run it again).</div>
      <div class="picks-note"><b>Any platform / manual:</b> <code>pip install cryptography</code> then
        <code>python scripts/setup.py</code>.</div>
      <div class="picks-note"><b>Needs:</b> Warframe + <a class="movedlink" href="https://alecaframe.com" target="_blank" rel="noopener">AlecaFrame</a>
        installed and synced once (open the game after installing it).</div>
      <div class="picks-note dim">Press <b>Refresh</b> after setup.</div>
    </div>`;
}

/* ---------- home ----------
   Stage 3 (Jay 2026-09-28): Home is an action surface - TODAY / NEXT ACTION / ALERTS / SELL
   QUEUE / RECENT - and every value renders exactly once. The old hero band and the six-cell KPI
   grid are merged into the one Today strip below; credits, items, sessions and the week roll-up
   ride the strip's detail disclosure (home.js); nothing that used to be on Home left the app -
   game news is Tools > Game news, the session roll-up is Trade > History > Sessions. */

/* The Today strip, in the order the brief gave: earned today, sales today, trades left, platinum
   now. The two day cells come from home.js (fed by /api/feature/progress): #todayEarned and
   #todaySales read '-' until that answer lands, never an invented 0. One number, one place.

   The trade allowance has two possible bases, in order: the save's own TradesRemaining
   (SUMMARY.trades) when the save carries it, else the limits reading (/api/feature/limits) - but
   only while that reading still describes TODAY's window. The allowance resets every day, so a
   reading from an older window is not today's number: that stays '-', never an invented value
   (the title says why, and when the last reading was). */
function tradesLeftReading() {
  const s = SUMMARY || {};
  if (s.trades !== null && s.trades !== undefined) {
    return { v: s.trades, tip: 'trades left today (from the game save)' };
  }
  const L = FEAT.limits || {};
  const now = Math.floor(Date.now() / 1000);
  const reading = (L.trades_left !== null && L.trades_left !== undefined);
  if (reading && L.status === 'OK' && (!L.reset_epoch || now < L.reset_epoch)) {
    return { v: L.trades_left, tip: 'trades left in the current daily window' };
  }
  const last = (reading && L.ts) ? ' - last reading ' + ago(L.ts) : '';
  return { v: null, tip: 'no reading for today: the allowance resets daily' + last };
}

function renderTodayStrip() {
  const s = SUMMARY || {}, ph = PLAT || {};
  const el = document.getElementById('kpis');
  if (!el) return;
  const tl = tradesLeftReading();
  el.innerHTML = `
    <div class="kpi" title="platinum gained or spent today"><div class="k-label">Earned today</div><div class="k-val accent" id="todayEarned">—</div></div>
    <div class="kpi" title="sales logged today"><div class="k-label">Sales today</div><div class="k-val" id="todaySales">—</div></div>
    <div class="kpi" title="daily trade allowance left"><div class="k-label">Trades left</div><div class="k-val" id="todayTrades" title="${escHtml(tl.tip)}">${tl.v ?? '—'}</div></div>
    <div class="kpi" title="in-game platinum balance"><div class="k-label">Platinum now</div><div class="k-val"><span id="platinumNow">${(ph.now ?? s.plat ?? 0).toLocaleString()}</span>p</div></div>`;
}

/* the page header row: the date only - the sync state lives in the header (#syncState) and the
   footer, so repeating it here was one of Home's duplicate lines (stage 3 removed it) */
function renderHomeHead() {
  const date = document.getElementById('homeDate');
  if (date) date.textContent = new Date().toLocaleDateString([], { weekday: 'long', day: 'numeric', month: 'long' });
}

/* NEXT ACTION + SELL QUEUE: both read the plan Trade sells from (TRADER.plan) plus the advisor
   and run-queue payloads this page already fetches, so Home invents nothing and fetches nothing
   new. The buyer line only shows when the run queue names that exact item; otherwise the row
   points at Trade's run-queue surface. */
const QUEUE_ROWS = 5;      /* plan rows listed under NEXT ACTION */
const RUNQ_WHOM = 3;       /* buyers named in a hover title */

function homePlan() {
  const plan = (TRADER || {}).plan || {};
  return { plan, rows: (plan.plan || []) };
}

/* demand for one plan row: the advisor's own 48h sales count and its trend word, else the plan
   row's vol48; everything missing stays missing ('—' / no chip) rather than being guessed */
function homeDemand(slug, row) {
  const a = advOf(slug) || {};
  const vol = (a.vol48 !== null && a.vol48 !== undefined) ? a.vol48 : row.vol48;
  const word = a.trend === 'rising' ? 'rising' : (a.trend === 'falling' ? 'fading' : (a.trend === 'steady' ? 'steady' : ''));
  return { vol: (vol === null || vol === undefined) ? null : vol, word,
    conf: a.liquidity || '', pct: (a.price_trend_pct === null || a.price_trend_pct === undefined) ? null : a.price_trend_pct };
}

function demandCell(slug, row) {
  const d = homeDemand(slug, row);
  /* the column head already says "Sold 48h", so the cell is the count alone; a rising/falling
     trend rides a one-glyph arrow and the word lives in the hover */
  const arrow = d.word === 'rising' ? ' \u2191' : (d.word === 'fading' ? ' \u2193' : '');
  const txt = d.vol !== null ? String(d.vol) + arrow : (d.word || '—');
  const tip = [d.vol !== null ? d.vol + ' completed sales in 48h' : '', d.word ? 'demand ' + d.word : '']
    .filter(Boolean).join(' · ');
  return { txt, tip };
}

/* the run queue's own rows for this item - the tradeable buyers, if it names any */
function homeBuyers(slug) {
  const R = FEAT.runqueue || {};
  return (R.queue || []).filter((q) => q && q.slug === slug);
}

function renderNextAction() {
  const card = document.getElementById('homeSellNext');
  const list = document.getElementById('sellNextList');
  if (!card || !list) return;
  const { plan, rows } = homePlan();
  const meta = document.getElementById('sellNextMeta');
  const r = rows[0];
  if (!r) {                                   /* no plan on Home: the band steps aside */
    card.classList.add('hidden');
    list.textContent = '';
    if (meta) { meta.textContent = ''; meta.title = ''; }
    return;
  }
  card.classList.remove('hidden');
  const a = advOf(r.slug) || {};
  const d = homeDemand(r.slug, r);
  const copies = (a.sellable !== null && a.sellable !== undefined) ? a.sellable : r.qty;
  const head = card.querySelector('.card-title');
  if (head) head.title = plan.generated ? rows.length + ' items in the plan' : '';
  if (meta) { meta.textContent = ''; meta.title = ''; }
  const sub = [r.lane, copies + (copies === 1 ? ' copy' : ' copies')].filter(Boolean).join(' · ');
  const who = homeBuyers(r.slug);
  const b = who[0];
  /* one link on the card, and it says what it opens: with a buyer named below, the head action
     opens Trade; with nobody named, the head action IS the buyers surface (no second CTA) */
  const open = card.querySelector('.home-open');
  if (open) open.textContent = b ? 'Open Trade' : 'See buyers in Trade';
  const dmTip = ['advisor demand ' + (d.word || 'not known'),
    d.pct === null ? '' : Math.abs(d.pct) + '% price move over 30 days'].filter(Boolean).join(' · ');
  list.innerHTML = `
    <div class="next-one">
      <div class="next-l">
        <div class="next-t">${escHtml(r.name || pretty(r.slug))}</div>
        <div class="next-sub" title="${escHtml(r.note || '')}">${escHtml(sub)}</div>
      </div>
      <div class="next-pr">${r.price}p</div>
    </div>
    <div class="next-facts">
      <div class="next-fact" title="${escHtml(dmTip)}"><div class="nf-l">Demand</div><div class="nf-v${d.word === 'rising' ? ' upl' : (d.word === 'fading' ? ' downl' : '')}">${escHtml(d.word || '—')}</div></div>
      <div class="next-fact" title="completed sales in the last 48h"><div class="nf-l">Sold 48h</div><div class="nf-v">${d.vol === null ? '—' : escHtml(String(d.vol))}</div></div>
      <div class="next-fact" title="how easily it sells near this price"><div class="nf-l">Liquidity</div><div class="nf-v">${escHtml(d.conf || '—')}</div></div>
    </div>
    <div class="next-foot">
      ${b
        ? `<span class="next-buyer" title="${escHtml(who.slice(0, RUNQ_WHOM).map((q) => q.buyer + ' pays ' + q.buy_price + 'p').join(' · '))}">Buyer <b>${escHtml(b.buyer)}</b> pays ${b.buy_price}p</span>
           <span class="chip act-${escHtml(b.buyer_status)}">${escHtml(b.buyer_status)}</span>`
        : `<span class="next-nobuyer" title="no buyer row in the run queue">No buyer in the run queue</span>`}
    </div>`;
  renderSellQueue(rows);
}

/* Sell queue: the next few DIFFERENT items (a plan can carry the same item twice - two ranks,
   two prices; those stay in Trade's plan table, Home lists each item once). */
function renderSellQueue(rows) {
  const card = document.getElementById('sellQueueCard');
  const el = document.getElementById('sellQueueList');
  if (!el) return;
  const all = rows || homePlan().rows;
  const items = [];
  const seenSlug = {};
  all.forEach((r) => {
    const key = r.slug || r.name;
    if (seenSlug[key]) return;
    seenSlug[key] = 1;
    items.push(r);
  });
  const rest = items.slice(1, 1 + QUEUE_ROWS);
  if (card) card.classList.toggle('hidden', !rest.length);
  const meta = document.getElementById('sellQueueMeta');
  if (meta) meta.textContent = rest.length ? rest.length + ' of ' + (items.length - 1) + ' items' : '';
  el.innerHTML = (rest.length ? `<div class="hnext-row hnext-head">
      <span>Item</span><span class="hnext-dm">Sold 48h</span><span class="hnext-pr">List at</span><span></span>
    </div>` : '') + rest.map((r) => {
    const d = demandCell(r.slug, r);
    return `
    <a class="hnext-row" href="#trade" title="${escHtml(r.note || r.name || '')}">
      <span class="hnext-nm">
        <span class="hnext-t">${escHtml(r.name || pretty(r.slug))}</span>
        <span class="hnext-sub">${escHtml([r.lane, r.qty + (r.qty === 1 ? ' copy' : ' copies')].filter(Boolean).join(' · '))}</span>
      </span>
      <span class="hnext-dm" title="${escHtml(d.tip)}">${escHtml(d.txt)}</span>
      <span class="hnext-pr">${r.price}p</span>
      <span class="hnext-chev" aria-hidden="true">\u203a</span>
    </a>`;
  }).join('');
}

/* ---- smart sell advisor (scripts/sell_advisor.py -> /api/feature/advisor) ---- */
function advOf(slug) {
  const A = FEAT.advisor || {};
  return (A.items && slug) ? (A.items[slug] || null) : null;
}
const ADV_VERB = { list: 'list', burn_ducats: 'burn', open_relic: 'open', assemble_set: 'assemble set',
  finish_set: 'finish set', already_listed: 'listed', keep: 'keep', hold: 'hold' };
function advTag(a) {
  if (!a) return '';
  let t = ADV_VERB[a.recommendation] || a.recommendation;
  if (['list', 'burn_ducats', 'open_relic'].includes(a.recommendation) && a.recommended_quantity) {
    t += ' ' + a.recommended_quantity;
    if (a.recommendation === 'list' && a.recommended_price != null) t += ' · ' + Math.round(a.recommended_price) + 'p';
  }
  return t;
}
function advRec(a) {
  const n = a.recommended_quantity || 0;
  const p = a.recommended_price != null ? ' around ' + Math.round(a.recommended_price) + 'p' : '';
  switch (a.recommendation) {
    case 'list': return 'list ' + n + ' now' + p;
    case 'burn_ducats': return 'burn ' + n + ' for ducats';
    case 'open_relic': return 'open ' + n;
    case 'assemble_set': return 'assemble the set, sell it as one';
    case 'finish_set': return 'finish the set, sell it as one';
    case 'already_listed': return 'already listed';
    case 'keep': return 'hold - nothing sellable';
    default: return 'hold';
  }
}
function advBits(slug) {
  const a = advOf(slug);
  if (!a) return '';
  const bits = [];
  if (a.demand_badge) bits.push(a.demand_badge === 'spike' ? 'demand rising' : a.demand_badge === 'fade' ? 'demand fading' : 'demand steady');
  if (a.best_sell_window) bits.push('best ' + a.best_sell_window);
  if (a.sellable) bits.push(a.sellable + ' sellable');
  return bits.join(' · ');
}

function advNote(slug) {
  const bits = advBits(slug), a = advOf(slug) || {};
  return bits ? ` <span class="advchip" title="${escHtml((a.reasons || []).join(' · '))}">advisor: ${bits}</span>` : '';
}

function renderPicks() {
  /* the old Dashboard "Top sell picks" card is retired: HOME renders the advisor-driven
     Today block (home.js) and TRADE > Sell renders the live plan. Kept only so the
     export path and any stale markup keep working. */
  const el = document.getElementById('sellPicks');
  if (!el) return;
  const rs = (REPORT && REPORT.sell_now || []).filter((r) => !r.in_use_only).slice(0, 8);
  const note = `<div class="picks-note dim">Sorted by earnings × how fast they sell.</div>`;
  const head = `<div class="pick pick-head">
      <span class="c-rank">#</span><span class="c-name">Item</span>
      <span class="c-own" title="sellable copies — equipped copies are excluded">Sellable</span><span class="c-act">Sold · 48h</span>
      <span class="c-soldfor">Sold for</span><span class="c-do" title="smart sell advisor — what to actually do">Do</span>
      <span class="c-price">List at</span><span class="c-tot">If all sell</span>
    </div>`;
  const rows = rs.map((r, i) => {
    const a = advOf(r.slug);
    const rng = (r.mn48 !== null && r.mn48 !== undefined && r.mx48 !== null && r.mx48 !== undefined)
      ? ` · range ${r.mn48}–${r.mx48}p` : '';
    const soldFor = (r.med !== null && r.med !== undefined)
      ? `<span class="c-soldfor" title="typical price actually paid, last 48h${rng}">${Math.round(r.med)}p</span>`
      : `<span class="c-soldfor dim" title="no sales in the last 48h">—</span>`;
    const doCell = a
      ? `<span class="c-do do-${a.recommendation}" title="${escHtml((a.reasons || []).join(' · '))}">${escHtml(advTag(a))}</span>`
      : `<span class="c-do dim" title="no advisor entry">—</span>`;
    return `
    <div class="pick">
      <span class="c-rank dim">${i + 1}</span>
      <span class="c-name" title="${r.name}">${r.name}</span>
      <span class="c-own">${(r.sellable_count !== undefined && r.sellable_count !== null) ? r.sellable_count : r.count}${r.in_use_count > 0 ? `<span class="dim" title="${r.in_use_count} equipped — never listed"> (+${r.in_use_count} use)</span>` : ''}</span>
      <span class="c-act dim">${r.vol48}</span>
      ${soldFor}
      ${doCell}
      <span class="c-price">${r.wts}p</span>
      <span class="c-tot">${r.value}p</span>
    </div>`;
  }).join('');
  el.innerHTML = rs.length ? note + head + rows : '<div class="dim" style="padding:10px 8px">No report yet — run scripts/report.py.</div>';
  const pm = document.getElementById('picksMeta');
  if (pm) pm.textContent = (REPORT && REPORT.generated) ? '· ' + REPORT.generated : '';
}

function renderChartMeta() {
  const ph = PLAT || {};
  const el = document.getElementById('chartMeta');
  if (!ph.n) { el.textContent = 'Collector: every 15 min'; return; }
  const since = new Date(ph.first_ts * 1000).toLocaleDateString([], { month: 'short', day: 'numeric' });
  el.textContent = `${ph.n} readings · every 15 min`;
  el.title = `snapshots since ${since}`;
}

/* ---------- history ---------- */
let hFilter = 'all';

function balAt(ts) {
  if (!PLAT || !PLAT.points) return null;
  let v = null;
  for (const p of PLAT.points) { if (p.ts <= ts) v = p.plat; else break; }
  return v;
}

function renderHistory() {
  const t = TRADES || { events: [], totals: {} };
  const tot = t.totals || {};
  document.getElementById('histKpis').innerHTML = `
    <div class="kpi"><div class="k-label">Plat earned</div><div class="k-val upl">+${(tot.earned || 0).toLocaleString()}p</div></div>
    <div class="kpi"><div class="k-label">Plat spent</div><div class="k-val downl">−${(tot.spent || 0).toLocaleString()}p</div></div>
    <div class="kpi"><div class="k-label">Net</div><div class="k-val ${(tot.net || 0) >= 0 ? 'upl' : 'downl'}">${(tot.net || 0) >= 0 ? '+' : '−'}${Math.abs(tot.net || 0).toLocaleString()}p</div></div>
    <div class="kpi"><div class="k-label">Sales</div><div class="k-val">${tot.sales || 0}</div></div>
    <div class="kpi"><div class="k-label">Purchases</div><div class="k-val">${tot.purchases || 0}</div></div>
    <div class="kpi"><div class="k-label">Items moved</div><div class="k-val">${tot.items || 0}</div></div>`;
  document.getElementById('histMeta').textContent = t.n ? `· ${t.n} event${t.n === 1 ? '' : 's'}` : '';

  const LABEL = { sale: 'Sold', purchase: 'Bought', listing: 'Listed', unlist: 'Unlisted', reprice: 'Repriced', note: 'Note' };
  const evs = (t.events || []).filter(e => {
    if (hFilter === 'sale') return e.kind === 'sale';
    if (hFilter === 'purchase') return e.kind === 'purchase';
    if (hFilter === 'other') return e.kind !== 'sale' && e.kind !== 'purchase';
    return true;
  });
  const head = `<div class="lrow log-head">
      <span>When</span><span>Event</span><span>Item</span>
      <span class="l-qty">Qty</span><span class="l-deal">Total</span><span class="l-bal hide-s">Balance ~</span>
    </div>`;
  const rows = evs.map(e => {
    const when = new Date(e.ts * 1000).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
    const bal = balAt(e.ts);
    const deal = (e.total !== undefined && e.total !== null) ? `${(+e.total).toLocaleString()}p`
      : ((e.plat !== undefined && e.plat !== null) ? `${e.plat}p` : '—');
    return `<div class="lrow">
      <span class="l-when">${when}</span>
      <span><span class="badge ${e.kind}">${LABEL[e.kind] || e.kind}</span></span>
      <span class="l-name" title="${e.name || e.note || ''}">${e.name || e.note || '—'}</span>
      <span class="l-qty">${e.qty ?? '—'}</span>
      <span class="l-deal">${deal}</span>
      <span class="l-bal hide-s">${bal === null ? '—' : bal.toLocaleString() + 'p'}</span>
    </div>`;
  }).join('');
  document.getElementById('tradeLog').innerHTML = evs.length ? head + rows :
    `<div class="empty">${EMPTY_ICON}Nothing here yet — fills automatically once the trader runs.</div>`;
}

/* ---------- game updates (Tools > Game news since stage 3; was a Home card) ---------- */
const NEWS_ROWS = 8;        /* headlines listed in the workspace */
function fmtDay(ts) {
  if (!ts) return '—';
  return new Date(ts * 1000).toLocaleDateString(undefined, { day: 'numeric', month: 'short' });
}
function renderNews() {
  const n = GAMENEWS || {};
  const meta = document.getElementById('newsMeta');
  const list = document.getElementById('newsList');
  if (!meta || !list) return;                        /* the workspace owns these (Tools > Game news) */
  meta.textContent =
    (n.version ? `· v${n.version}` : '') + (n.fetched ? ` · checked ${ago(n.fetched)}` : ' · not loaded');
  const items = (n.items || []).slice(0, NEWS_ROWS);
  list.innerHTML = items.length
    ? items.map(it => `<div class="newsrow">
        <span class="n-date">${fmtDay(it.date)}</span>
        <a class="n-title" href="${it.url}" target="_blank" rel="noopener" title="${(it.excerpt || '').replace(/"/g, '&quot;')}">${it.title}</a>
        <span class="n-src dim">${it.source}</span>
      </div>`).join('')
    : `<div class="empty">${EMPTY_ICON}No updates fetched yet.</div>`;
}

/* ---------- trader ---------- */
function renderTrader() {
  const t = TRADER || {};
  const plan = t.plan || {}, stt = t.state || {}, set = t.settings || {};
  const rows = plan.plan || [];
  const held = plan.held_list || [];
  document.getElementById('planMeta').textContent = plan.generated
    ? `· built ${ago(plan.generated)}${plan.mr != null ? ' · MR ' + plan.mr : ''}` : '';
  /* the posting gate, read from the config that decides it (settings.json + the plan's own
     dry_run) and stated where the decision is made - the chip can never claim Live while
     dry_run is locked, and it is never hardcoded */
  const dry = set.dry_run === true || plan.dry_run === true;
  const pm = document.getElementById('postMode');
  if (pm) {
    pm.className = dry ? 'chip' : 'chip kill-on';
    pm.textContent = dry ? 'Not live - nothing is posted' : 'Live';
  }
  const head = `<div class="prow plan-head"><span>#</span><span>Item</span><span class="p-qty">Qty</span><span class="p-price">List at</span><span class="p-est">Est</span><span class="p-note">Notes</span></div>`;
  document.getElementById('planList').innerHTML = rows.length
    ? head + rows.map((r, i) => {
      /* the notes are short by design: the note itself never shrinks, the advisor chip takes the
         cut, and the cell title carries the whole line (note + advisor bits) for hover */
      const note = r.note || (r.subtype || ''), bits = advBits(r.slug);
      const tip = escHtml(note) + (bits ? escHtml(' · advisor: ' + bits) : '');
      /* one action per row: a click opens the shared item drawer, exactly like an inventory row */
      const act = r.slug ? ` data-slug="${escHtml(r.slug)}" title="Open item"` : '';
      return `
      <div class="prow"${act}>
        <span class="dim">${i + 1}</span>
        <span class="l-name" title="${r.name}">${r.name}</span>
        <span class="p-qty">${r.qty}</span>
        <span class="p-price">${r.price}p</span>
        <span class="p-est">${(r.est_total || 0).toLocaleString()}p</span>
        <span class="p-note" title="${tip}"><span class="p-notxt">${note}</span>${advNote(r.slug)}</span>
      </div>`;
    }).join('')
    : `<div class="empty">${EMPTY_ICON}No plan yet — hit "Rebuild plan".</div>`;
  document.getElementById('heldMeta').textContent = held.length ? `· ${held.length}` : '';
  document.getElementById('heldList').innerHTML = held.length
    ? held.map(h => `<div class="heldline"><span class="l-name" title="${escHtml(h[0])}">${h[0]}</span><span class="dim">${h[1]}</span></div>`).join('')
    : `<div class="empty">${EMPTY_ICON}Nothing held back.</div>`;
  const w = t.undercuts || {};
  document.getElementById('attnMeta').textContent = w.generated
    ? `· checked ${ago(w.generated)}` : '';
  const wr = w.rows || [];
  const attn = wr.map(r => `<div class="heldline attnrow"${r.slug ? ` data-slug="${escHtml(r.slug)}" title="Open item"` : ''}>
        <span class="l-name" title="${escHtml(r.name)}${r.lane ? ' · ' + escHtml(r.lane) : ''}">${escHtml(r.name)}${r.lane ? ' · ' + escHtml(r.lane) : ''}</span>
        <span class="dim">${r.floor != null && r.my_price != null && r.floor < r.my_price
          ? `someone listed at ${r.floor}p - below your ${r.my_price}p`
          : `you're at ${r.my_price}p · best now ${r.floor ?? '—'}p`}${r.proposed ? ` · reprice to ${r.proposed}p` : ''}${r.reason ? ' · ' + escHtml(r.reason) : ''}</span>
      </div>`);
  const hy = FEAT.hygiene || {}, hc = hy.summary || {};
  if (hc.total) attn.push(`<div class="heldline attnrow"><span class="l-name">Listings that haven't moved</span><span class="dim">${hc.hide} hide · ${hc.refresh} reprice · ${hc.show} restore${(hy.rules || {}).auto_hide_offline ? ` · auto-hide after ${(hy.rules || {}).offline_window_minutes} min offline` : ''}</span></div>`);
  document.getElementById('attnList').innerHTML = attn.length
    ? attn.join('')
    : (w.generated
        ? `<div class="empty">${EMPTY_ICON}Nothing needs attention right now.</div>`
        : `<div class="empty">${EMPTY_ICON}Not checked yet - hit "Check now".</div>`);
  renderRunQueue(); renderHygiene(); renderNotify(); markScrollers();
}

/* ---------- round-3 renderers ---------- */
function renderRunQueue() {
  const R = FEAT.runqueue || {}, s = R.summary || {};
  const m = document.getElementById('runqMeta');
  if (!m) return;
  m.textContent = R.generated
    ? `· ${s.ingame || 0} ingame · ${s.online || 0} online · ${s.offline || 0} offline · built ${ago(R.generated)}`
    : '';
  const el = document.getElementById('runqList');
  const rows = (R.queue || []).slice(0, 10);
  if (!rows.length) { el.innerHTML = '<div class="dim pad">Run scripts/trader/runqueue.py</div>'; return; }
  /* one row, five fixed columns: item / price / status / buyer / message. The message is the only
     flexible one - it truncates, and the full whisper rides the cell title. */
  el.innerHTML = '<div class="runrow runhead"><span>Item</span><span class="r-price">Price</span>'
    + '<span>Status</span><span>Buyer</span><span>Message</span></div>'
    + rows.map(q => `<div class="runrow">
      <span class="r-name" title="${escHtml(q.why || '')}">${escHtml(q.name)}</span>
      <span class="r-price">x${q.qty} @ ${q.my_price}p</span>
      <span class="r-status"><span class="chip act-${q.buyer_status}">${q.buyer_status}</span></span>
      <span class="r-buyer">${escHtml(q.buyer)} · ${q.buy_price}p</span>
      <span class="runwhisper" title="${escHtml(q.whisper)}">${escHtml(q.whisper)}</span>
    </div>`).join('');
  markScrollers();
}

function renderHygiene() {
  const H = FEAT.hygiene || {}, c = H.summary || {}, r = H.rules || {};
  const ent = (H.inputs || {}).entries || {};
  const m = document.getElementById('hygieneMeta');
  if (!m) return;
  m.textContent = (c.total !== undefined)
    ? `· ${c.hide} hide · ${c.show} show · ${c.refresh} refresh${r.auto_hide_offline ? ` · offline ${r.offline_window_minutes}m` : ''}`
    : '';
  const el = document.getElementById('hygieneList');
  if (!H.mode) { el.innerHTML = '<div class="dim pad">Run scripts/trader/hygiene.py</div>'; return; }
  const acts = H.actions || [];
  const line = a => `<div class="heldline"><span class="l-name" title="${escHtml(a.order_id)}">${escHtml(a.item)}${a.lane ? ' · ' + escHtml(a.lane) : ''}</span><span class="dim">${escHtml(a.reason || '')}</span></div>`;
  let html = `<div class="limrow"><b>NOT LIVE - plan only</b><span class="dim">${acts.length} action(s) · ${ent.live || 0} live / ${ent.pending || 0} planned listings</span></div>`;
  ['hide', 'show', 'refresh'].forEach(k => {
    const rows = acts.filter(a => a.action === k);
    if (rows.length) html += `<div class="subhead">${k} <span class="dim">(${rows.length})</span></div>` + rows.slice(0, 6).map(line).join('');
  });
  if (!acts.length) html += `<div class="dim pad">${escHtml((H.notes || [])[0] || 'Nothing to do — no live listings.')}</div>`;
  el.innerHTML = html;
}

function renderTiming() {
  const T = FEAT.timing || {}, s = T.sample || {}, hours = T.hours || [], kinds = T.by_kind || {};
  const m = document.getElementById('timingMeta');
  if (!m) return;
  m.textContent = s.sales_total ? `· ${T.verdict === 'SELL_NOW' ? 'SELL NOW' : 'HOLD'} · ${s.sales_total} sales · next ${(T.next_window || {}).label || '—'}` : '';
  const el = document.getElementById('timingList');
  if (!s.sales_total) { el.innerHTML = '<div class="dim pad">Run scripts/sell_timing.py</div>'; return; }
  const peak = Math.max(1, ...hours.map(h => h.sales));
  const top = [...hours].filter(h => h.sales > 0).sort((a, b) => b.sales - a.sales || b.plat - a.plat).slice(0, 3);
  const line = h => `<div class="mrow"><span class="m-name">${String(h.hour).padStart(2, '0')}:00 <span class="dim small">${h.sales} sales · ${h.plat}p</span></span><span class="num">${'\u2588'.repeat(Math.max(1, Math.round(h.sales / peak * 8)))}</span></div>`;
  el.innerHTML = `<div class="limrow"><b>${T.verdict === 'SELL_NOW' ? 'SELL NOW' : 'HOLD'}</b><span class="dim">${escHtml(T.verdict_reason || '')}</span></div>` +
    `<div class="subhead">Best hours (Melbourne)</div>` + top.map(line).join('') +
    `<div class="mrow"><span class="m-name dim small" title="${escHtml(s.note || '')}">${escHtml(s.note || '')}</span><span class="num dim small">${Object.entries(kinds).map(([k, v]) => `${escHtml(k)} ${v.sales}`).join(' · ')}</span></div>`;
}

function renderWatchlist() {
  const W = FEAT.watchlist || {}, s = W.summary || {};
  const m = document.getElementById('wlMeta');
  if (!m) return;
  m.textContent = s.total ? `· ${s.hit_buy} buy hit · ${s.hit_sell} sell hit · ${s.wait} waiting` : '';
  const el = document.getElementById('wlList');
  const rows = W.entries || [], cand = W.suggested || [];
  const line = e => {
    const t = e.status === 'HIT_BUY' ? ['upl', 'BUY'] : e.status === 'HIT_SELL' ? ['downl', 'SELL'] : ['dim', 'WAIT'];
    return `<div class="mrow"><span class="m-name" title="${escHtml(e.slug)}">${escHtml(e.name || pretty(e.slug))} <span class="chip wl-${e.status}">${t[1]}</span></span>
      <span class="num ${t[0]}">floor ${e.floor == null ? '—' : e.floor + 'p'} <span class="dim">/ buy ${e.max_buy ?? '—'} · sell ${e.min_sell ?? '—'}</span></span></div>`;
  };
  const hit = rows.filter(e => (e.alerts || []).length), wait = rows.filter(e => !(e.alerts || []).length);
  let html = '';
  if (hit.length) html += `<div class="subhead">Triggered now</div>` + hit.map(line).join('');
  if (wait.length) html += `<div class="subhead">Waiting</div>` + wait.map(line).join('');
  if (!rows.length) html += `<div class="dim pad">Add rows to data/watchlist_config.json</div>`;
  if (cand.length) html += `<div class="subhead">Candidates (not alerted)</div>` + cand.slice(0, 4).map(c => `<div class="mrow"><span class="m-name dim">${escHtml(c.name || pretty(c.slug))}</span><span class="num dim">buy ≤ ${c.max_buy}p · sell ≥ ${c.min_sell}p</span></div>`).join('');
  el.innerHTML = html || '<div class="dim pad">Run scripts/watchlist.py</div>';
}

function renderRivens() {
  const R = FEAT.rivens || {}, s = R.summary || {}, bands = R.veiled_bands || [], mine = R.owned_rivens || [];
  const m = document.getElementById('rivensMeta');
  if (!m) return;
  m.textContent = s.band_count ? `· ${s.band_count} veiled families · ${s.owned_count} owned` : '';
  const el = document.getElementById('rivensList');
  if (!bands.length && !mine.length) { el.innerHTML = '<div class="dim pad">Run scripts/rivens.py</div>'; return; }
  let html = `<div class="subhead">Veiled bands — floor / 48h median (unrevealed)</div>` +
    `<div class="srow srowhead"><span>Family</span><span class="num">Floor</span><span class="num">Median</span><span class="num">Vol48</span><span></span></div>` +
    bands.map(b => `<div class="srow"><span class="d-name" title="${escHtml(b.name)}">${escHtml(b.name)}</span><span class="num">${b.floor}p</span><span class="num">${b.median}p</span><span class="num dim">${b.vol48 ?? '—'}</span><span></span></div>`).join('');
  if (mine.length) html += `<div class="subhead">My rivens</div>` +
    `<div class="srow srowhead"><span>Riven</span><span class="num">Qty</span><span class="num">Low</span><span class="num">High</span><span></span></div>` +
    mine.map(r2 => `<div class="srow"><span class="d-name" title="${escHtml(r2.basis || '')}">${escHtml(r2.name)}</span><span class="num dim">×${r2.qty}</span><span class="num">${r2.est_low ?? '—'}p</span><span class="num upl">${r2.est_high ?? '—'}p</span><span></span></div>`).join('');
  el.innerHTML = html;
}

function renderMeta() {
  const M = FEAT.meta || {}, p = M.patch || {}, s = M.summary || {};
  const m = document.getElementById('metaMeta');
  if (!m) return;
  m.textContent = M.generated_iso ? (p.post_patch_active
    ? `· post-patch ${p.latest_version || ''} (${p.days_since_latest ?? '?'}d) · ${s.spike} up · ${s.sink} down of ${s.tracked}`
    : `· no update in ${p.window_days || 10}d · ${s.spike} up · ${s.sink} down of ${s.tracked}`) : '';
  const el = document.getElementById('metaList');
  const sp = (M.spike || []).slice(0, 6), sk = (M.sink || []).slice(0, 6);
  if (!sp.length && !sk.length) { el.innerHTML = '<div class="dim pad">Run scripts/meta_watcher.py</div>'; return; }
  const line = (r2, up) => `<div class="mrow"><span class="m-name" title="${escHtml(r2.name || pretty(r2.slug))}">${escHtml(r2.name || pretty(r2.slug))} <span class="dim small">48h ${r2.vol48} · base ${r2.vol30_baseline}/d${r2.post_patch ? ' · post-patch' : ''}</span></span>
      <span class="num ${up ? 'upl' : 'downl'}">x${(r2.ratio ?? 0).toFixed(2)}</span></div>`;
  el.innerHTML = `<div class="subhead">Post-patch surges</div>` + sp.map(r2 => line(r2, true)).join('') +
    `<div class="subhead">Post-patch sinks</div>` + sk.map(r2 => line(r2, false)).join('');
}

function renderCraft() {
  const C = FEAT.craft || {}, s = C.summary || {};
  const m = document.getElementById('craftMeta');
  if (!m) return;
  m.textContent = s.total ? `· ${s.craft} craft · ${s.buy} buy · ${s.skip} skip` : '';
  const el = document.getElementById('craftList');
  const rows = (C.rows || []).filter(r2 => r2.verdict !== 'SKIP').slice(0, 12);
  if (!rows.length) { el.innerHTML = '<div class="dim pad">Run scripts/craft.py</div>'; return; }
  const parts = r2 => (r2.missing_parts || []).map(p => `${escHtml(pretty(p.slug))} <b>${p.floor ?? '?'}p</b>`).join('<span class="dim"> · </span>') || '<span class="dim">nothing to buy</span>';
  el.innerHTML = `<div class="srow srowhead"><span>Item</span><span class="num">Missing parts</span><span class="num">Built floor</span><span class="num">Profit</span><span></span></div>` +
    rows.map(r2 => `<div class="srow"><span class="d-name" title="${escHtml(r2.result_slug)}">${escHtml(r2.result_name || pretty(r2.result_slug))} <span class="dim">${(r2.owned_parts || []).length} owned</span></span>
      <span class="num">${parts(r2)}</span><span class="num">${r2.built_floor ?? '—'}p</span>
      <span class="num ${(r2.profit ?? 0) >= 0 ? 'upl' : 'downl'}">${r2.profit > 0 ? '+' : ''}${r2.profit}p</span>
      <span><span class="chip act-${r2.verdict}">${r2.verdict}</span></span></div>`).join('');
}

function renderNotify() {
  const raw = FEAT.notify;
  const N = Array.isArray(raw) ? raw : ((raw && raw.rows) || []);
  const el = document.getElementById('notifyList'), m = document.getElementById('notifyMeta');
  if (!el) return;
  /* the outbox stores engine statuses (plan-mode rows carry dry_run): the cell prints the
     label, never the raw status value */
  const NLABEL = { sent: 'sent', dry_run: 'not live', held: 'not live', failed: 'failed' };
  const rows = N.slice().reverse().slice(0, 6);
  const sent = N.filter(r => r.status === 'sent').length;
  if (m) m.textContent = N.length ? `· ${N.length} in outbox · ${sent} delivered (rest held)` : '· no outbox yet';
  el.innerHTML = rows.length ? rows.map(r => `<div class="mrow"><span class="m-name" title="${escHtml(r.title)}${r.to ? ' · ' + escHtml(r.to) : ''}">${escHtml(r.title)} <span class="dim small">${escHtml(r.to || '')}</span></span><span class="num"><span class="chip ${r.status === 'sent' ? 'act-show' : 'act-offline'}">${escHtml(NLABEL[r.status] || r.status)}</span> ${r.ts ? ago(Date.parse(r.ts) / 1000) : ''}</span></div>`).join('')
    : '<div class="dim pad">Configure a webhook in data/notify_config.json, then send a test ping.</div>';
}

/* ---------- platinum ledger (#51) ---------- */
function renderPlatLedger() {
  const L = FEAT.ledger || {}, t = L.totals || {}, rows = L.days || [], chk = L.self_check || {};
  const m = document.getElementById('ledgerMeta');
  if (!m) return;
  m.textContent = t.windows ? `· balance ${t.current_balance}p · inferred in-game spend ${t.in_game_spent_inferred_plat}p · reconciles ${chk.reconciles ? '✓' : '✗'}` : '';
  const el = document.getElementById('ledgerList');
  if (!t.windows) { el.innerHTML = '<div class="dim pad">Run scripts/plat_ledger.py</div>'; return; }
  const p = v => (v >= 0 ? '+' : '−') + Math.abs(v).toLocaleString() + 'p';
  el.innerHTML = `<div class="limrow"><b>${t.trades_earned_plat.toLocaleString()}p earned · ${t.trades_spent_plat.toLocaleString()}p spent</b><span class="dim">balance ${t.first_balance}p → ${t.current_balance}p across ${t.reading_days} reading days (${t.gap_days} days without a reading)</span></div>` +
    `<div class="subhead">Balance windows (newest first)</div>` +
    rows.slice(0, 8).map(r => `<div class="sessrow">
      <span class="num dim">${r.date}</span>
      <span class="dim">${r.window_days}d window · ${r.trades} trade${r.trades === 1 ? '' : 's'}</span>
      <span>trades <span class="${r.trades_net >= 0 ? 'upl' : 'downl'}">${p(r.trades_net)}</span> · other <span class="${r.other_net >= 0 ? 'upl' : 'downl'}">${p(r.other_net)}</span>${r.inferred_spend ? ` <span class="dim">· inferred in-game spend ${r.inferred_spend}p</span>` : ''}</span>
      <span class="num ${r.delta >= 0 ? 'upl' : 'downl'}">${p(r.delta)}</span>
    </div>`).join('') +
    `<div class="mrow"><span class="m-name dim small" title="${escHtml((L.notes || [])[0] || '')}">${escHtml((L.notes || [])[0] || '')}</span><span class="num dim small">${chk.reconciles ? 'reconciles ✓' : 'NOT reconciled'} · tolerance ${chk.tolerance}p</span></div>`;
}

/* ---------- auto-refresh cadence (#45): auto_refresh_seconds from /api/config ----------
   The SERVER runs the sync pipeline on that cadence (GET /api/sync reports it); this timer only
   re-reads the stores the page renders. It is capped at 60s so a 1-hour cadence still shows
   fresh data - the data itself is refreshed by the server loop, not by this poll. */
let AUTO_REFRESH_S = 0, autoTimer = null;
function syncAutoRefresh(values) {
  const raw = Number((values || {}).auto_refresh_seconds);
  const knob = (Number.isFinite(raw) && raw > 0) ? Math.max(15, Math.floor(raw)) : 30;
  const secs = Math.min(knob, 60);
  if (autoTimer && secs === AUTO_REFRESH_S) return;
  AUTO_REFRESH_S = secs;
  if (autoTimer) clearInterval(autoTimer);
  autoTimer = setInterval(load, secs * 1000);
}
async function loadAutoRefresh() {
  try {
    const c = await fetch('/api/config').then(r2 => r2.json());
    syncAutoRefresh((c || {}).values || {});
  } catch (e) { syncAutoRefresh(null); }
}

/* ---------- auto-sync status (server loop): GET /api/sync ----------
   Label only, no prose: 'Auto sync off' (enabled false) / 'Syncing…' (running) /
   'Sync failed' (last_ok false) / 'Synced 12:04' (last sync landed) / 'Auto sync —' before
   the first sync has landed. The hover title carries the cadence + the next run. */
const SYNC_POLL_MS = 60000;
function syncClock(ts) {
  return new Date(ts * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
}
function syncText(s) {
  if (s.enabled === false) return 'Auto sync off';
  if (s.running) return 'Syncing…';
  if (s.last_ok === false) return 'Sync failed';
  if (s.last_sync) return 'Synced ' + syncClock(s.last_sync);
  return 'Auto sync —';
}
function syncHint(s) {
  if (s.enabled === false) return 'manual only';
  const mins = Math.max(1, Math.round((Number(s.seconds) || 0) / 60));
  const next = (s.next_in == null) ? '' : ' · next ' + syncClock(Math.floor(Date.now() / 1000) + Number(s.next_in));
  return `auto sync every ${mins} minutes${next}`;
}
function renderSyncState(s) {
  const el = document.getElementById('syncState');
  if (!el) return;
  const known = !!s && typeof s === 'object';
  el.textContent = known ? syncText(s) : 'Auto sync —';
  if (known) el.title = syncHint(s); else el.removeAttribute('title');
  iconRepaint(el);   /* textContent drops the host's icon: re-arm it (icons.js repaints) */
}
async function loadSyncState() {
  try {
    renderSyncState(await fetch('/api/sync').then(r2 => r2.json()));
  } catch (e) { renderSyncState(null); }
}

/* ---------- inventory ---------- */
function renderTabs() {
  const el = document.getElementById('tabs');
  el.innerHTML = CATS.map(([k, label]) =>
    `<div class="tab${state.tab === k ? ' active' : ''}" data-k="${k}">${label}</div>`).join('');
  el.querySelectorAll('.tab').forEach(t => t.onclick = () => { state.tab = t.dataset.k; renderTabs(); renderTable(); });
}

function rowsFiltered() {
  let rs = ITEMS;
  if (state.tab !== 'all') rs = rs.filter(r => r.cat === state.tab);
  if (state.q) {
    const q = state.q.toLowerCase();
    rs = rs.filter(r => r.name.toLowerCase().includes(q));
  }
  const k = state.sort;
  rs = rs.slice().sort((a, b) => {
    let x = a[k], y = b[k];
    if (k === 'name' || k === 'cat') { x = String(x || ''); y = String(y || ''); return state.dir * x.localeCompare(y); }
    // price columns sort (and display) from the rank lane when the item is ranked
    if (k === 'wts') { x = laneVal(a); y = laneVal(b); }
    else if (k === 'wtb') { x = laneBid(a); y = laneBid(b); }
    else if (k === 'spread') { x = laneSpread(a); y = laneSpread(b); }
    else if (k === 'value') { x = laneValue(a); y = laneValue(b); }
    else if (k === 'equipped') { x = advField(a, 'equipped'); y = advField(b, 'equipped'); }
    else if (k === 'safe') { x = safeOf(a); y = safeOf(b); }
    else if (k === 'reserved') { x = advField(a, 'reserved'); y = advField(b, 'reserved'); }
    x = (x === null || x === undefined) ? -Infinity : x;
    y = (y === null || y === undefined) ? -Infinity : y;
    return state.dir * (x - y);
  });
  return rs;
}

/* Rank lanes: a ranked copy is priced from the order book of the rank owned. The raw
   wts is usually a rank-0 listing while wtb can be a rank-10 bid - an any-rank pair
   would misprice the copy, so every price surface reads the lane first. */
function laneVal(r) { return r.lane_rank != null ? r.lane_ask : r.wts; }
function laneBid(r) { return r.lane_rank != null ? r.lane_bid : r.wtb; }
function laneSpread(r) {
  const p = laneVal(r), b = laneBid(r);
  return (p != null && b != null) ? p - b : null;
}
function laneValue(r) { return (laneVal(r) || 0) * (r.count || 0); }
/* owned/equipped/reserved/safe come from the advisor when it has the item, else the row */
function advField(r, k) {
  const a = advOf(r.slug);
  if (a && a[k] !== undefined && a[k] !== null) return a[k];
  return (r[k] === undefined) ? null : r[k];
}
function safeOf(r) {
  const a = advOf(r.slug);
  if (a && a.sellable !== undefined && a.sellable !== null) return a.sellable;
  return r.count || 0;
}

/* Price trend: one ask series (state.itemhist[slug]) as a 62x18 inline SVG. Rising gets the
   table's gain colour (.upl), falling its loss colour (.downl), a series that never moved
   reads muted; '' means "no line" so the cell falls back to a dash. */
function sparkline(vals) {
  if (!vals || vals.length < 2) return '';
  const w = 62, h = 18, pad = 1.5;
  let lo = Infinity, hi = -Infinity;
  for (let i = 0; i < vals.length; i++) {
    const v = Number(vals[i]);
    if (!isFinite(v)) return '';
    if (v < lo) lo = v;
    if (v > hi) hi = v;
  }
  const step = (w - pad * 2) / (vals.length - 1), span = (hi - lo) || 1;
  const pts = vals.map((v, i) => (pad + i * step).toFixed(1) + ',' + (h - pad - ((v - lo) / span) * (h - pad * 2)).toFixed(1));
  const cls = (hi === lo) ? 'dim' : (vals[vals.length - 1] >= vals[0] ? 'upl' : 'downl');
  return '<svg class="' + cls + '" viewBox="0 0 62 18" width="62" height="18" aria-hidden="true" focusable="false">' +
    '<path d="M' + pts.join('L') + '" fill="none" stroke="currentColor" stroke-width="1.5" vector-effect="non-scaling-stroke"/>' +
    '</svg>';
}

function renderTable() {
  const rs = rowsFiltered();
  const tbody = document.getElementById('rows');
  document.querySelectorAll('thead th').forEach(th => {
    const base = th.textContent.replace(/ [▼▲]$/, '');
    th.textContent = base + (th.dataset.k === state.sort ? (state.dir < 0 ? ' ▼' : ' ▲') : '');
    th.classList.toggle('sorted', th.dataset.k === state.sort);
  });
  const slice = rs.slice(0, 400);
  tbody.innerHTML = slice.map(r => {
    const rkTag = r.lane_rank != null
      ? ` <span class="lane-tag" title="priced from the rank-${r.lane_rank} order book - the rank you own">R${r.lane_rank}</span>` : '';
    return `
    <tr class="inv-row" data-slug="${escHtml(r.slug)}" title="Click for the full item view">
      <td class="name" title="${escHtml(r.name)}">${escHtml(r.name)}</td>
      <td class="num">${fmt(r.count)}</td>
      <td class="num">${fmt(advField(r, 'equipped'))}</td>
      <td class="num">${fmt(safeOf(r))}</td>
      <td class="num">${fmt(laneVal(r))}${rkTag}</td>
      <td class="spark">${state.itemhist ? (sparkline(state.itemhist[r.slug]) || '<span class="dim">-</span>') : '<span class="dim">-</span>'}</td>
      <td class="num v">${fmt(laneValue(r))}</td>
      <td class="hide-a"><span class="cat ${r.cat}">${CAT_LABEL[r.cat] || r.cat}</span></td>
      <td class="num hide-a">${fmt(r.ducats)}</td>
      <td class="num hide-a">${fmt(laneBid(r))}</td>
      <td class="num hide-a${(laneSpread(r) !== null && laneSpread(r) < 0) ? ' neg' : ''}">${fmt(laneSpread(r))}</td>
      <td class="num hide-a">${r.vol48 === null || r.vol48 === undefined ? '<span class="dim">—</span>' : r.vol48.toFixed(1)}</td>
      <td class="num hide-a">${fmt(r.median)}</td>
      <td class="num hide-a">${fmt(advField(r, 'reserved'))}</td>
    </tr>`;
  }).join('');
  if (!slice.length) tbody.innerHTML = '<tr><td colspan="14" class="dim" style="padding:18px">No items match.</td></tr>';
  const tot = rs.reduce((a, r) => a + laneValue(r), 0);
  document.getElementById('totals').innerHTML =
    `<span>${rs.length} stacks <span class="dim">(showing ${slice.length})</span></span>
     <span>Filtered value <b class="big">${tot.toLocaleString()}p</b></span>`;
}

/* ---------- inventory panels: materials + the clan dojo buildout ----------
   One payload (state.materials, /api/feature/materials) feeds both cards: the owned
   materials table (Personal/Dojo swap, search + a Count/Name sort toggle, capped at
   MAT_CAP rows) and the clan dojo card (shortages first, per-room costs collapsed). */
const MAT_CAP = 400;
/* the swapped header cells - Personal is the shipped default in index.html (#matHead) */
const MAT_HEADS = {
  personal: '<th scope="col">Material</th><th scope="col" class="num">Count</th><th scope="col">Category</th>',
  dojo: '<th scope="col">Material</th><th scope="col" class="num">Needed</th><th scope="col" class="num">Owned</th><th scope="col" class="num">Short</th>',
};

function matRowsFiltered() {
  const M = state.materials || {};
  const dojo = state.matView === 'dojo';
  const q = (state.matQ || '').toLowerCase();
  let rs = (M.materials || []).filter(r => (dojo ? !!r.dojo : true)
    && (!q || String(r.name || '').toLowerCase().includes(q)));
  if (dojo) {
    return rs.slice().sort((a, b) => (b.short || 0) - (a.short || 0)
      || (b.needed || 0) - (a.needed || 0));
  }
  if (state.matSort === 'name') {
    rs = rs.slice().sort((a, b) => String(a.name || '').localeCompare(String(b.name || '')));
  } else {
    rs = rs.slice().sort((a, b) => (b.count || 0) - (a.count || 0)
      || String(a.name || '').localeCompare(String(b.name || '')));
  }
  return rs;
}

function renderMaterials() {
  const M = state.materials || {};
  const dojo = state.matView === 'dojo';
  const meta = document.getElementById('matMeta');
  if (meta) {
    const all = (M.materials || []).filter(r => (dojo ? !!r.dojo : true));
    const shortN = all.filter(r => (r.short || 0) > 0).length;
    meta.title = dojo ? 'needed for the clan dojo buildout' : 'distinct materials owned';
    meta.textContent = dojo
      ? `${fmt(all.length)} dojo materials${shortN ? ` · ${fmt(shortN)} short` : ''}`
      : (M.count ? '· ' + fmt(M.count) : '');
  }
  const tbody = document.getElementById('matRows');
  if (!tbody) return;
  const head = document.getElementById('matHead');
  if (head) head.innerHTML = MAT_HEADS[dojo ? 'dojo' : 'personal'];
  const rows = matRowsFiltered();
  tbody.innerHTML = rows.slice(0, MAT_CAP).map(r => dojo ? `
    <tr class="mat-row" data-slug="${escHtml(r.slug)}">
      <td class="name" title="${escHtml(r.name)}">${escHtml(r.name)}</td>
      <td class="num">${fmt(r.needed)}</td>
      <td class="num">${fmt(r.count)}</td>
      <td class="num">${(r.short || 0) > 0 ? '<span class="v">' + fmt(r.short) + '</span>' : (r.short == null ? '<span class="dim">—</span>' : '<span class="dim">ok</span>')}</td>
    </tr>` : `
    <tr class="mat-row" data-slug="${escHtml(r.slug)}">
      <td class="name" title="${escHtml(r.name)}">${escHtml(r.name)}${r.dojo ? ' <span class="dojobadge" title="needed for the clan dojo buildout">DOJO</span>' : ''}</td>
      <td class="num">${fmt(r.count)}</td>
      <td><span class="cat">${escHtml(r.cat || '-')}</span></td>
    </tr>`).join('') || (dojo
      ? '<tr><td colspan="4" class="dim mat-empty">No dojo materials yet.</td></tr>'
      : '<tr><td colspan="3" class="dim mat-empty">No material data yet.</td></tr>');
  const cap = document.getElementById('matCap');
  if (cap) cap.textContent = rows.length > MAT_CAP ? `showing ${MAT_CAP} of ${rows.length}` : '';
}

/* the in-card table scrollers only wear the soft bottom edge when there is more below it */
function markScrollers() {
  document.querySelectorAll('.tablewrap').forEach(function (el) {
    el.classList.toggle('scrolly', el.scrollHeight > el.clientHeight + 2);
  });
  /* the Trade lists are scrollers too: same cue, only when the list really has more rows below */
  document.querySelectorAll('#view-trade .picks').forEach(function (el) {
    const oy = getComputedStyle(el).overflowY;
    el.classList.toggle('scrolly', (oy === 'auto' || oy === 'scroll') && el.scrollHeight > el.clientHeight + 2);
  });
}

function renderDojo() {
  const D = (state.materials || {}).dojo || null;
  const head = document.getElementById('dojoTitle'), meta = document.getElementById('dojoMeta');
  const tbody = document.getElementById('dojoRows'), rooms = document.getElementById('dojoRooms');
  if (!tbody) return;
  if (!D) {
    if (meta) meta.textContent = '';
    if (head) head.title = '';
    if (rooms) rooms.classList.add('hidden');
    tbody.innerHTML = '<tr><td colspan="4" class="dim mat-empty">No dojo data yet.</td></tr>';
    return;
  }
  if (head) head.title = D.scope || '';
  const TT = (D.tier_totals || {})[state.dojoTier] || null;   // the wiki's own column for this clan size
  const rowsSrc = TT ? TT.materials : (D.materials || []);    // no column -> ghost totals
  const credits = TT ? TT.credits : D.credits;
  const shortN = rowsSrc.filter(m => (m.short || 0) > 0).length;
  if (meta) meta.textContent = `· ${dojoTierLabel(D, TT)} · ${fmt(credits)} cr · ${shortN} short`;
  const rows = rowsSrc.slice().sort((a, b) => (b.short || 0) - (a.short || 0)
    || (b.needed || 0) - (a.needed || 0));
  tbody.innerHTML = rows.map(m => `
    <tr class="dojo-row" data-slug="${escHtml(m.slug)}">
      <td class="name">${escHtml(m.name)}</td>
      <td class="num">${fmt(m.needed)}</td>
      <td class="num">${fmt(m.owned)}</td>
      <td class="num">${(m.short || 0) > 0 ? '<span class="v">' + fmt(m.short) + '</span>' : '<span class="dim">ok</span>'}</td>
    </tr>`).join('') || '<tr><td colspan="4" class="dim mat-empty">Nothing needed.</td></tr>';
  if (rooms) rooms.classList.remove('hidden');
  const rmeta = document.getElementById('dojoRoomsMeta');
  if (rmeta) rmeta.textContent = `· ${(D.rooms || []).length}`;
  const rlist = document.getElementById('dojoRoomsList');
  if (rlist) rlist.innerHTML = (D.rooms || []).map(rm => {
    const R = ((D.room_tiers || {})[rm.slug] || {})[state.dojoTier]
      || ((D.room_tiers || {})[rm.slug] || {}).ghost || null;   // per-tier table, else ghost
    const costs = R ? R.costs : (rm.costs || []), cr = R ? R.credits : rm.credits;
    return `
    <div class="mrow"><span class="m-name" title="${escHtml(rm.url || '')}">${escHtml(rm.name)}</span><span class="num">${fmt(cr)} cr</span></div>
    <div class="rcosts dim small">${(costs || []).map(c => `<span title="needed ${fmt(c.qty)} · owned ${fmt(c.owned)}">${escHtml(c.name)} ${fmt(c.qty)}</span>`).join(' · ')}</div>`;
  }).join('');
  const a = document.getElementById('dojoSrc');
  if (a && D.source) {
    a.textContent = D.source;
    a.href = /^https?:/i.test(D.source) ? D.source : 'https://' + D.source;
    iconRepaint(a);
  }
}

async function load() {
  const [s, i, ph, rep, tr, tdr, gn] = await Promise.all([
    fetch('/api/summary').then(r => r.json()),
    fetch('/api/items').then(r => r.json()),
    fetch('/api/plat_history').then(r => r.json()),
    fetch('/api/report').then(r => r.json()).catch(() => null),
    fetch('/api/trades').then(r => r.json()).catch(() => null),
    fetch('/api/trader').then(r => r.json()).catch(() => null),
    fetch('/api/gamenews').then(r => r.json()).catch(() => null),
  ]);
  SUMMARY = s; ITEMS = i; PLAT = ph; REPORT = rep; TRADES = tr; TRADER = tdr; GAMENEWS = gn;
  FEAT = {};
  /* the Trend column reads one slim series map for the whole page (state.itemhist) - never a
     fetch per row; a missing/empty file answers {} so every cell just shows a dash */
  await Promise.all(['deals', 'ducats', 'sets', 'relics', 'limits', 'sessions', 'invdiff', 'movers', 'flips', 'trends', 'baro', 'wishlist', 'nudges', 'killswitch', 'flipper', 'hygiene', 'runqueue', 'timing', 'watchlist', 'rivens', 'meta', 'craft', 'notify', 'ledger', 'advisor']
    .map(async n => { FEAT[n] = await fetch('/api/feature/' + n).then(r => r.json()).catch(() => null); })
    .concat([fetch('/api/feature/itemhist').then(r => r.json())
      .then(j => { state.itemhist = (j && j.items) || {}; })
      .catch(() => { state.itemhist = {}; }),
      fetch('/api/feature/materials').then(r => r.json())
      .then(j => { state.materials = (j && typeof j === 'object') ? j : null; })
      .catch(() => { state.materials = null; })]));
  paintDojoTier();
  renderChips(); renderTabs(); renderTable(); renderMaterials(); renderDojo();
  markScrollers();
  renderTodayStrip(); renderPicks(); renderChartMeta(); renderHistory(); renderTrader(); renderNews();
  renderFirstRun();
  renderHomeHead(); renderNextAction();
  if (window.wfmRenderHome) wfmRenderHome();
  window.addEventListener('resize', function () { window.clearTimeout(window.__wfmScrollerT); window.__wfmScrollerT = window.setTimeout(markScrollers, 180); });
  /* the trade columns settle after the first paint (details content, flex heights), and any body
     resize reflows them - re-mark so a list that overflows always shows the cue, a short one never */
  if (window.ResizeObserver) {
    const _scrollerRO = new ResizeObserver(function () {
      window.clearTimeout(window.__wfmScrollerT);
      window.__wfmScrollerT = window.setTimeout(markScrollers, 60);
    });
    _scrollerRO.observe(document.body);
  }
  renderMarket(); renderLimits(); renderSessions(); renderDiff(); renderKill(); renderTiming(); renderPlatLedger(); loadAutoRefresh();
  PlatChart.setData(ph.points || []);
  document.getElementById('status').textContent = s.lastdata_mtime
    ? `prices updated ${ago(s.prices_mtime)} · checked ${new Date().toLocaleTimeString()}`
    : 'No data yet — run: python scripts/setup.py';
  document.getElementById('foot').textContent =
    `WFM Trader · refreshed ${new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false })} · ${(tr && tr.n) || 0} history events · prices refresh every 15 min`;
}

/* ---------- market ---------- */
const escHtml = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const pretty = s => String(s || '').replace(/_/g, ' ');

function renderDeals() {
  const D = FEAT.deals || {}, c = D.counts || {}, rows = (D.deals || []).slice(0, 14);
  document.getElementById('dealsMeta').textContent = c.total
    ? `· ${c.total} live in ${D.window_hours || 12}h (${(c.by_kind || {}).spread || 0} spreads · ${(c.by_kind || {}).undercut || 0} undercuts) · cursor ${(D.scan || {}).cursor_end ?? '—'}/${(D.scan || {}).pool_size ?? '—'}`
    : '';
  const el = document.getElementById('dealsList');
  if (!rows.length) { el.innerHTML = '<div class="dim pad">Run scripts/deal_scanner.py</div>'; return; }
  el.innerHTML =
    `<div class="dealrow dealhead"><span>Kind</span><span>Item</span><span class="num">Floor → target</span><span class="num">Profit</span><span class="num hide-s">48h vol</span><span class="num hide-s">Own</span></div>` +
    rows.map(r => `<div class="dealrow">
      <span><span class="chip kind-${r.kind}">${r.kind}</span></span>
      <span class="d-name" title="${escHtml(r.slug)}${r.stale ? ' · stale' : ''}">${escHtml(r.name)}${r.stale ? ' <span class="dim">· stale</span>' : ''}</span>
      <span class="num">${r.floor_sell}<span class="dim"> → </span><b>${r.target_price ?? r.ref ?? '—'}</b></span>
      <span class="num upl">+${r.profit}<span class="dim"> (${Math.round(r.profit_pct || 0)}%)</span></span>
      <span class="num hide-s dim">${r.vol48 ?? '—'}</span>
      <span class="num hide-s">${r.owned ? '✔' : '<span class="dim">—</span>'}</span>
    </div>`).join('');
}

function renderDucats() {
  const U = FEAT.ducats || {}, s = U.summary || {}, rows = U.rows || [];
  document.getElementById('ducatsMeta').textContent = s.slugs
    ? `· ${s.sell_count} sell (${s.total_sell_plat}p) · ${s.burn_count} burn (${s.total_burn_ducats} ducats) · ${s.hold_count} hold`
    : '';
  const el = document.getElementById('ducatsList');
  if (!rows.length) { el.innerHTML = '<div class="dim pad">Run scripts/ducats.py</div>'; return; }
  const line = (r, mode) => {
    const num = mode === 'burn'
      ? `${r.ducats_total} duc <span class="dim">· ${r.ducats_per_plat}d/p</span>`
      : `${r.wts}p ea → ${r.sell_total}p`;
    return `<div class="mrow"><span class="m-name" title="${escHtml(r.slug)}">${escHtml(r.name)} <span class="dim">×${r.count}</span></span><span class="num">${num}</span></div>`;
  };
  el.innerHTML =
    `<div class="subhead">Burn for ducats</div>` +
    rows.filter(r => r.verdict === 'BURN').slice(0, 8).map(r => line(r, 'burn')).join('') +
    `<div class="subhead">Sell for plat</div>` +
    rows.filter(r => r.verdict === 'SELL').slice(0, 8).map(r => line(r, 'sell')).join('');
}

function renderSets() {
  const S = FEAT.sets || {}, sm = S.summary || {}, tt = S.top_targets || [];
  document.getElementById('setsMeta').textContent = sm.sets_total
    ? `· ${sm.complete} complete · ${sm.near_1_missing} one away · ${sm.two_missing} two away · ${sm.targets} targets · ${sm.net_profit_build_targets}p modelled profit`
    : '';
  const el = document.getElementById('setsList');
  if (!tt.length) { el.innerHTML = '<div class="dim pad">Run scripts/sets.py</div>'; return; }
  el.innerHTML =
    `<div class="srow srowhead"><span>Set</span><span>Parts</span><span class="num">Cost to finish</span><span class="num">Set value</span><span class="num">Profit</span></div>` +
    tt.slice(0, 12).map(r => `<div class="srow">
      <span class="d-name" title="${escHtml(r.slug)}">${escHtml(r.name || pretty(r.slug))}</span>
      <span class="dim">${r.parts} <span class="chip act-${r.action}">${r.action}</span></span>
      <span class="num">${r.cost_est ? r.cost_est + 'p' : '—'}</span>
      <span class="num">${r.set_value}p</span>
      <span class="num upl">+${r.profit}p</span>
    </div>`).join('');
}

function renderRelics() {
  const R = FEAT.relics || {}, t = R.totals || {}, rows = (R.rows || []);
  document.getElementById('relicsMeta').textContent = t.ev_if_all_opened
    ? `· EV ${Math.round(t.ev_if_all_opened)}p if opened vs ${t.value_if_all_sold_as_is}p sold · ${(t.actions || {}).OPEN || 0} open / ${(t.actions || {}).SELL || 0} sell / ${(t.actions || {}).HOLD || 0} hold`
    : '';
  const el = document.getElementById('relicsList');
  if (!rows.length) { el.innerHTML = '<div class="dim pad">Run scripts/relic_ev.py</div>'; return; }
  const top = rows.slice().sort((a, b) => Math.abs(b.gain_if_opened_total || 0) - Math.abs(a.gain_if_opened_total || 0)).slice(0, 12);
  el.innerHTML =
    `<div class="srow srowhead"><span>Relic</span><span class="num">EV each</span><span class="num">Sell each</span><span class="num">Ratio</span><span></span></div>` +
    top.map(r => `<div class="srow">
      <span class="d-name" title="${escHtml(r.slug)}">${escHtml(r.relic)} <span class="dim">${r.refinement} ×${r.count}</span></span>
      <span class="num">${(r.ev_unit_wts ?? 0).toFixed(1)}p</span>
      <span class="num">${r.relic_wts ?? '—'}p</span>
      <span class="num ${r.ratio >= 1.2 ? 'upl' : (r.ratio <= 0.8 ? 'downl' : '')}">${r.ratio >= 10 ? '×' + Math.round(r.ratio) : '×' + (r.ratio ?? 0).toFixed(2)}</span>
      <span><span class="chip act-${r.action}">${r.action}</span></span>
    </div>`).join('');
}

function renderMovers() {
  const M = FEAT.movers || {}, rows = (M.movers || []).slice(0, 8);
  document.getElementById('moversMeta').textContent = rows.length
    ? (M.mode === 'baseline' ? `· baseline day — real 24h deltas from tomorrow`
        : (M.prev_day ? `· ${M.day || ''} vs ${M.prev_day}` : `· ${M.day || ''}`))
    : '';
  const el = document.getElementById('moversList');
  if (!rows.length) { el.innerHTML = '<div class="dim pad">Run scripts/price_history.py</div>'; return; }
  el.innerHTML = rows.map(r => `<div class="mrow">
      <span class="m-name" title="${escHtml(r.slug)}">${escHtml(r.name)} <span class="dim small">${escHtml(r.basis || '')}</span></span>
      <span class="num ${r.gap_pct >= 0 ? 'upl' : 'downl'}">${r.gap_pct > 0 ? '+' : ''}${r.gap_pct}%</span>
    </div>`).join('');
}

function renderMarket() { renderDeals(); renderDucats(); renderSets(); renderRelics(); renderMovers(); renderFlips(); renderNudges(); renderWish(); renderWatchlist(); renderCraft(); renderRivens(); renderBaro(); renderTrends(); renderMeta(); }

function renderLimits() {
  const L = FEAT.limits || {}, el = document.getElementById('limList');
  if (!L.trade_cap) { el.innerHTML = '<div class="dim pad">Run scripts/trader/limits.py</div>'; document.getElementById('limMeta').textContent = ''; return; }
  const sec = L.seconds_until_reset || 0, h = Math.floor(sec / 3600), mn = Math.floor((sec % 3600) / 60);
  document.getElementById('limMeta').textContent = L.status === 'OK' ? '· live from game save' : '· ' + (L.status || '');
  /* the numeral is the card's centrepiece: it, the used/cap bar and the meta share the column */
  const used = L.trades_used ?? 0, cap = L.trade_cap || 0;
  const pct = cap ? Math.min(100, Math.max(0, Math.round((used / cap) * 100))) : 0;
  el.innerHTML = `<div class="limrow lim-hero">
    <span class="lim-big">${L.trades_left ?? '—'}<span class="dim">/${L.trade_cap}</span></span>
    <span class="limbar" title="used ${used} of ${cap}"><i style="width: ${pct}%"></i></span>
    <span class="dim limmeta">trades left · used ${L.trades_used ?? '—'} · resets ${(L.reset_melbourne || '').slice(11, 16)} in ${h}h ${mn}m · ${L.mr_label || ''} · ${L.account || ''}</span>
  </div>`;
}

function renderSessions() {
  const S = FEAT.sessions || {}, t = S.totals || {}, rows = S.sessions || [];
  document.getElementById('sessMeta').textContent = t.sessions
    ? `· ${t.trade_sessions} trade sessions · ${t.in_game_hours}h in game · earned ${t.gross}p · spent ${t.spent}p`
    : '';
  const el = document.getElementById('sessList');
  const list = rows.filter(r => r.events > 0).slice(0, 8);
  if (!list.length) { el.innerHTML = '<div class="dim pad">No trade sessions yet.</div>'; return; }
  el.innerHTML = list.map(r => `<div class="sessrow">
    <span class="num dim">${(r.start_at || '').slice(0, 10)}</span>
    <span class="dim">${(r.start_at || '').slice(11, 16)}–${(r.end_at || '').slice(11, 16)} · ${Math.round(r.dur_min || 0)}m</span>
    <span>${r.sales} sold <span class="upl">+${r.gross}p</span>${r.purchases ? ` · ${r.purchases} bought <span class="downl">−${r.spent}p</span>` : ''}${r.best_sale && r.best_sale.name ? ` <span class="dim">· best ${escHtml(r.best_sale.name)} ${r.best_sale.total ?? ''}p</span>` : ''}</span>
    <span class="num ${r.plat_delta > 0 ? 'upl' : (r.plat_delta < 0 ? 'downl' : 'dim')}">${r.plat_delta == null ? '' : (r.plat_delta > 0 ? '+' : '') + r.plat_delta + 'p'}</span>
  </div>`).join('');
}

function renderDiff() {
  const DI = FEAT.invdiff || {}, el = document.getElementById('diffList');
  if (!DI.status) { el.innerHTML = '<div class="dim pad">Run scripts/invdiff.py</div>'; document.getElementById('diffMeta').textContent = ''; return; }
  document.getElementById('diffMeta').textContent = '· ' + DI.status;
  let html = `<div class="limrow"><b>${DI.refreshed ? 'Snapshot refreshed' : 'Snapshot unchanged'}</b>
    <span class="dim">${DI.snapshot || ''}${DI.reference ? ' · vs ' + DI.reference : ' · first snapshot — diffs from tomorrow'}</span></div>`;
  (DI.added || []).slice(0, 6).forEach(a => {
    html += `<div class="mrow"><span class="m-name">${escHtml(a.name)}</span><span class="num upl">+${a.delta} <span class="dim">· ${a.value || 0}p</span></span></div>`;
  });
  (DI.removed || []).slice(0, 6).forEach(a => {
    html += `<div class="mrow"><span class="m-name">${escHtml(a.name)}</span><span class="num downl">removed</span></div>`;
  });
  if (!(DI.added || []).length && !(DI.removed || []).length) {
    html += `<div class="dim pad">No changes${DI.note ? ' · ' + escHtml(DI.note) : ''}</div>`;
  }
  el.innerHTML = html;
}

function renderFlips() {
  const F = FEAT.flips || {}, c = F.counts || {}, rows = (F.flips || []).slice(0, 10);
  document.getElementById('flipsMeta').textContent = (c.flips || c.scored)
    ? `· ${c.flips ?? rows.length} ranked · fresh ${c.fresh ?? '?'} of ${c.deals_in ?? '?'} deals`
    : '';
  const el = document.getElementById('flipsList');
  if (!rows.length) { el.innerHTML = '<div class="dim pad">Run scripts/flip_digest.py</div>'; return; }
  el.innerHTML =
    `<div class="frow frowhead"><span>Item</span><span class="num">Buy → sell</span><span class="num">Margin</span><span class="num">Sales/day</span><span class="num hide-s">Queue</span><span class="num">Score</span></div>` +
    rows.map(r => `<div class="frow">
      <span class="d-name" title="${escHtml(r.slug)}">${escHtml(r.name)} <span class="chip kind-${r.kind}">${r.kind}</span></span>
      <span class="num">${r.buy_at}<span class="dim"> → </span><b>${r.sell_at}</b></span>
      <span class="num upl">+${r.profit}p <span class="dim">(${r.margin_pct}%)</span></span>
      <span class="num">${r.sales_day}</span>
      <span class="num hide-s dim">${r.queue_ahead}</span>
      <span class="num">${Math.round(r.score_raw ?? r.score ?? 0)}</span>
    </div>`).join('');
}

function renderNudges() {
  const N = FEAT.nudges || {}, c = N.counts || {};
  document.getElementById('nudgesMeta').textContent = (c.ready !== undefined)
    ? `· ${c.ready} ready · ${c.one_away} one away · ${c.part_cash} part sales`
    : '';
  const el = document.getElementById('nudgesList');
  const rows = [...(N.ready || []), ...(N.one_away || []).slice(0, 5)].slice(0, 10);
  if (!rows.length) { el.innerHTML = '<div class="dim pad">Run scripts/nudges.py</div>'; return; }
  el.innerHTML = rows.map(r => `<div class="mrow">
      <span class="m-name" title="${escHtml(r.slug)}">${escHtml(r.name || pretty(r.slug))} <span class="chip act-${r.category || ''}">${r.category || ''}</span></span>
      <span class="num upl">+${r.profit ?? 0}p <span class="dim small">${escHtml(String(r.action || '')).slice(0, 36)}</span></span>
    </div>`).join('');
}

function renderWish() {
  const W = FEAT.wishlist || {}, s = W.summary || {};
  document.getElementById('wishMeta').textContent = (s.budget_available !== undefined)
    ? `· buy plan ${s.affordable_subset_cost}p of ${s.budget_available}p · ${s.trades_needed} trades · ${s.buy_now_count} buy-now`
    : '';
  const el = document.getElementById('wishList');
  const plan = W.affordable_plan || [];
  const union = W.wishlist || [];
  let html = '';
  if (plan.length) {
    html += `<div class="subhead">Buy plan — fits budget + trades</div>` +
      plan.map(p => `<div class="mrow"><span class="m-name">${escHtml(p.name || pretty(p.slug))} <span class="dim">x${p.qty || 1}</span></span><span class="num">${p.cost}p <span class="dim">(floor ${p.floor}p)</span></span></div>`).join('');
  }
  const buyNow = union.filter(e => (e.status || '') === 'BUY_NOW').slice(0, 6);
  if (buyNow.length) {
    html += `<div class="subhead">At or below your max price</div>` +
      buyNow.map(e => `<div class="mrow"><span class="m-name">${escHtml(e.name || pretty(e.slug))}</span><span class="num">floor ${e.floor}p <span class="dim">/ max ${e.max_price}p</span></span></div>`).join('');
  }
  el.innerHTML = html || '<div class="dim pad">Run scripts/wishlist.py</div>';
}

function renderBaro() {
  const B = FEAT.baro || {}, T = B.trader || {};
  const el = document.getElementById('baroList'), meta = document.getElementById('baroMeta');
  if (!T.activation_iso) { meta.textContent = ''; el.innerHTML = '<div class="dim pad">Run scripts/baro.py</div>'; return; }
  meta.textContent = T.active ? '· AT THE RELAY NOW' : (T.starts_in_days !== undefined ? `· next visit in ${Math.round(T.starts_in_days * 10) / 10}d` : '');
  const when = `${(T.activation_iso || '').slice(0, 16).replace('T', ' ')} → ${(T.expiry_iso || '').slice(0, 16).replace('T', ' ')} UTC`;
  let html = `<div class="limrow"><b>${escHtml(T.status_text || '')}</b></div>`;
  if ((B.rows || []).length) {
    html += B.rows.slice(0, 10).map(r => `<div class="mrow"><span class="m-name">${escHtml(r.item)}${r.owned ? ' <span class="dim">· owned</span>' : ''}</span><span class="num">${r.ducats} duc · ${(r.credits || 0).toLocaleString()} cr</span></div>`).join('');
  } else {
    html += `<div class="dim pad">${escHtml((B.notes || [])[0] || 'Stock publishes only during the visit window.')} · ${escHtml(when)}</div>`;
  }
  el.innerHTML = html;
}

function renderTrends() {
  const T = FEAT.trends || {}, c = T.counts || {};
  document.getElementById('trendsMeta').textContent = c.tracked
    ? `· ${c.spike} spiking · ${c.fade} fading of ${c.tracked} tracked`
    : '';
  const el = document.getElementById('trendsList');
  const sp = (T.top_spikes || []).slice(0, 6), fd = (T.top_fades || []).slice(0, 6);
  if (!sp.length && !fd.length) { el.innerHTML = '<div class="dim pad">Run scripts/trends.py</div>'; return; }
  const line = (r, up) => `<div class="mrow">
      <span class="m-name" title="${escHtml(r.name || pretty(r.slug))}">${escHtml(r.name || pretty(r.slug))} <span class="dim small">30d ${r.vol30} · 90d ${r.vol90}</span></span>
      <span class="num ${up ? 'upl' : 'downl'}">x${(r.ratio ?? 0).toFixed(2)} <span class="dim">${r.price_trend_pct != null ? ((r.price_trend_pct > 0 ? '+' : '') + r.price_trend_pct + '%') : ''}</span></span>
    </div>`;
  el.innerHTML = `<div class="subhead">Demand rising</div>` + sp.map(r => line(r, true)).join('') +
    `<div class="subhead">Demand cooling</div>` + fd.map(r => line(r, false)).join('');
}

function renderKill() {
  const K = FEAT.killswitch || {};
  const el = document.getElementById('killList');
  const btn = document.getElementById('btnKill');
  btn.textContent = K.active ? 'Disarm' : 'Arm kill switch';
  iconRepaint(btn);
  /* ONE state element: the chip in the card head. The body keeps the note field and the record
     (why + when); there is no second ARMED/OFF anywhere. */
  const meta = document.getElementById('killMeta');
  meta.className = K.active ? 'chip kill-on' : 'chip';
  meta.textContent = K.active ? 'ARMED' : 'disarmed';
  const ts = K.ts ? new Date(K.ts * 1000).toLocaleString([], { hour12: false }) : '';
  el.innerHTML = `<div class="limrow killline"><span class="dim">${K.note ? escHtml(K.note) + ' · ' : ''}${ts || '—'}</span>
    <span class="dim small explain">Not live</span></div>`;
}

/* ---------- player page (#player): data/player.json ---------- */
/* The page renders labels and values only. Every number goes through pnum(), so a missing
   or non-numeric field prints a dash - never undefined or NaN. The payload is fetched once
   and cached on state.player; the clan name is a dashboard config value, not player.json. */
const PC_SIDES = [
  ['Railjack', 'railjack', [['pilotting', 'Piloting'], ['gunnery', 'Gunnery'],
    ['engineering', 'Engineering'], ['tactical', 'Tactical'], ['command', 'Command']]],
  ['Drifter', 'drifter', [['riding', 'Riding'], ['combat', 'Combat'], ['opportunity', 'Opportunity']]],
];
let PLAYER_REQ = null, CFG_REQ = null, PC_CLAN_ERR = '';

function pnum(v) {
  if (v === null || v === undefined || v === '') return '—';
  const n = typeof v === 'number' ? v : Number(v);
  return Number.isFinite(n) ? n.toLocaleString() : '—';
}
function ptxt(v) { return (v === null || v === undefined || v === '') ? '—' : escHtml(v); }
function pyes(v) { return v === true ? 'Yes' : (v === false ? 'No' : '—'); }
function pcVal(v) {
  if (typeof v === 'number') return Number.isFinite(v) ? v.toLocaleString() : '—';
  if (typeof v === 'boolean') return pyes(v);
  if (typeof v === 'string') return v ? escHtml(v) : '—';
  return '—';
}
function pcStanding(s) {
  const v = (s || {}).standing;
  const n = typeof v === 'number' ? v : Number(v);
  return (v === null || v === undefined || v === '' || !Number.isFinite(n)) ? -Infinity : n;
}

function loadPlayer() {
  if (state.player) return Promise.resolve(state.player);
  if (!PLAYER_REQ) {
    PLAYER_REQ = fetch('/api/feature/player').then(r => r.json())
      .then(j => (j && typeof j === 'object' && !Array.isArray(j)) ? j : {})
      .catch(() => ({}));
  }
  return PLAYER_REQ.then(j => { state.player = j; return j; });
}

function loadDashCfg() {
  if (state.cfg) return Promise.resolve(state.cfg);
  if (!CFG_REQ) {
    CFG_REQ = fetch('/api/config').then(r => r.json())
      .then(j => { state.cfg = (j && j.values) || {}; return state.cfg; })
      .catch(() => { state.cfg = {}; return state.cfg; });
  }
  return CFG_REQ;
}

function renderPlayerPage() {
  loadPlayer().then(P => {
    renderPlayerCard(P); renderPlayerSyndicates(P); renderPlayerIntrinsics(P);
    renderPlayerFocus(P); renderPlayerMarket(P); renderPlayerClan(P);
  });
  if (state.cfg) renderPlayerClan(state.player || {});
  else loadDashCfg().then(() => renderPlayerClan(state.player || {}));
}

function renderPlayerCard(P) {
  const m = P.mastery || {}, s = P.stats || {};
  const head = document.getElementById('pcHead');
  if (head) head.innerHTML =
    `<div class="pc-alias">${ptxt(P.alias)}</div><div class="pc-mr">` +
    `<span class="pc-mr-l">MR</span><span class="pc-mr-v">${pnum(m.rank)}</span></div>`;
  const meta = document.getElementById('pcMeta');
  if (meta) meta.textContent = P.updated ? '· synced ' + ago(P.updated) : '';
  const stats = document.getElementById('pcStats');
  if (stats) stats.innerHTML =
    `<div class="kpi"><div class="k-label">Items tracked</div><div class="k-val">${pnum(s.items_tracked)}</div></div>` +
    `<div class="kpi"><div class="k-label">Achievements</div><div class="k-val">${pnum(s.achievements_tracked)}</div></div>` +
    `<div class="kpi"><div class="k-label">Last region</div><div class="k-val">${ptxt(s.last_region)}</div></div>` +
    `<div class="kpi"><div class="k-label">Railjack</div><div class="k-val">${pyes(s.railjack_owned)}</div></div>` +
    `<div class="kpi"><div class="k-label">Necramech</div><div class="k-val">${pyes(s.necramech_owned)}</div></div>`;
  const top = document.getElementById('pcTop');
  const items = Array.isArray(m.top_items) ? m.top_items.slice(0, 8) : [];
  if (top) top.innerHTML = items.length ? items.map(it => {
    const r2 = it || {};
    return `<div class="mrow"><span class="m-name" title="${escHtml(r2.name || '')}">${ptxt(r2.name)}</span>` +
      `<span class="num">${pnum(r2.xp)}</span></div>`;
  }).join('') : '<div class="dim pad">—</div>';
}

function renderPlayerClan(P) {
  const el = document.getElementById('pcClan');
  if (!el) return;
  const C = (P && P.clan) || {}, cfg = state.cfg;
  const name = cfg ? String(cfg.clan_name || '').trim() : '';
  const rows = [];
  if (name) {
    rows.push(`<div class="mrow"><span class="m-name dim">Clan name</span><span class="num pc-name">${escHtml(name)}</span></div>`);
  } else if (cfg) {
    rows.push(`<div class="mrow"><label class="m-name dim" for="pcClanName">Clan name</label><span class="num pc-inrow">` +
      `<input id="pcClanName" class="noteinput" type="text" maxlength="32" placeholder="—" aria-label="Clan name">` +
      `<button class="btn" id="pcClanSave" data-icon="check">Save</button></span></div>`);
  } else {
    rows.push(`<div class="mrow"><span class="m-name dim">Clan name</span><span class="num dim">—</span></div>`);
  }
  const cid = String(C.id || '');
  rows.push(`<div class="mrow"><span class="m-name dim">Clan id</span><span class="num">` +
    (cid ? `<span title="${escHtml(cid)}">${escHtml(cid.slice(0, 8))}</span>` : '<span class="dim">—</span>') + `</span></div>`);
  rows.push(`<div class="mrow"><span class="m-name dim">Research blueprints</span><span class="num">${pnum(C.research_blueprints)}</span></div>`);
  const vb = C.vault_bonus;
  const vbTxt = (vb && vb.progress !== null && vb.progress !== undefined)
    ? pnum(vb.progress) + ' / ' + pnum(vb.week_count) : '—';
  rows.push(`<div class="mrow"><span class="m-name dim">Vault bonus</span><span class="num${vbTxt === '—' ? ' dim' : ''}">${vbTxt}</span></div>`);
  rows.push(`<a class="movedlink" href="#inventory">Dojo materials →</a>`);
  if (PC_CLAN_ERR) rows.push(`<div class="dim small pad">${escHtml(PC_CLAN_ERR)}</div>`);
  el.innerHTML = rows.join('');
  const inp = document.getElementById('pcClanName'), btn = document.getElementById('pcClanSave');
  if (btn) btn.onclick = pcSaveClanName;
  if (inp) inp.addEventListener('keydown', e => { if (e.key === 'Enter') pcSaveClanName(); });
}

async function pcSaveClanName() {
  const inp = document.getElementById('pcClanName');
  if (!inp) return;
  const name = String(inp.value || '').trim();
  try {
    const res = await fetch('/api/config', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pairs: { clan_name: name } }),
    }).then(r => r.json());
    if (res && res.ok === false) {
      PC_CLAN_ERR = 'Not saved · ' + String(res.error || '').slice(0, 80);
    } else {
      PC_CLAN_ERR = '';
      state.cfg = (res && res.cfg && res.cfg.values)
        ? res.cfg.values : Object.assign({}, state.cfg || {}, { clan_name: name });
    }
  } catch (e) {
    PC_CLAN_ERR = 'Not saved · ' + String((e && e.message) || e).slice(0, 80);
  }
  renderPlayerClan(state.player || {});
}

function renderPlayerSyndicates(P) {
  const el = document.getElementById('pcSyn');
  if (!el) return;
  const list = (Array.isArray(P.syndicates) ? P.syndicates.slice() : [])
    .sort((a, b) => pcStanding(b) - pcStanding(a));
  const meta = document.getElementById('pcSynMeta');
  if (meta) meta.textContent = list.length ? '· ' + list.length : '';
  el.innerHTML = list.length
    ? `<div class="pc-syn pc-synhead"><span>Rank</span><span>Syndicate</span>` +
      `<span class="num">Standing</span><span class="num">Next</span></div>` +
      list.map(s => {
        const st = pcStanding(s), known = Number.isFinite(st);
        const hasNext = s.next_at !== null && s.next_at !== undefined;
        const next = !hasNext ? '<span class="dim">max</span>'
          : pnum(known ? Math.max(0, Number(s.next_at) - st) : s.next_at);
        return `<div class="pc-syn">` +
          `<span class="dim">${pnum(s.title)}</span>` +
          `<span class="d-name" title="${escHtml(s.tag || '')}">${ptxt(s.name)}</span>` +
          `<span class="num ${known && st < 0 ? 'downl' : (known ? 'pc-up' : 'dim')}">${known ? st.toLocaleString() : '—'}</span>` +
          `<span class="num">${next}</span></div>`;
      }).join('')
    : '<div class="dim pad">—</div>';
}

function renderPlayerIntrinsics(P) {
  const el = document.getElementById('pcInt');
  if (!el) return;
  const I = P.intrinsics || {};
  el.innerHTML = PC_SIDES.map(([label, key, stats]) => {
    const side = I[key] || {};
    const chips = stats.map(([k, tag]) => `<span class="chip">${tag} <b>${pnum(side[k])}</b></span>`).join('');
    return `<div class="pc-col"><div class="subhead">${label} <span class="dim">XP ${pnum(side.xp)}</span></div>` +
      `<div class="pc-chips">${chips}</div></div>`;
  }).join('');
}

function renderPlayerFocus(P) {
  const el = document.getElementById('pcFocus');
  if (!el) return;
  const fx = f => { const n = Number((f || {}).xp); return Number.isFinite(n) ? n : -1; };
  const list = (Array.isArray(P.focus) ? P.focus.slice() : []).sort((a, b) => fx(b) - fx(a));
  const total = list.reduce((a, f) => a + Math.max(0, fx(f)), 0);
  const top = list.reduce((a, f) => Math.max(a, fx(f)), 0);
  const df = (P.stats || {}).daily_focus;
  const meta = document.getElementById('pcFocusMeta');
  if (meta) {
    meta.textContent = (typeof df === 'number' && Number.isFinite(df)) ? '· today ' + df.toLocaleString() : '';
    meta.title = 'focus earned today (resets daily)';
  }
  el.innerHTML = list.length ? list.map(f => {
    const share = total > 0 ? Math.round(Math.max(0, fx(f)) / total * 1000) / 10 : 0;
    const bar = top > 0 ? Math.max(3, Math.round(Math.max(0, fx(f)) / top * 100)) : 0;   // vs the biggest school
    return `<div class="pc-frow"><span class="d-name" title="${escHtml(f.tag || '')}">${ptxt(f.name)}</span>` +
      `<span class="num">${pnum(f.xp)}</span>` +
      `<span class="pc-bar" title="${share}% of your focus XP"><i style="width:${bar}%"></i></span></div>`;
  }).join('') : '<div class="dim pad">—</div>';
}

function renderPlayerMarket(P) {
  const el = document.getElementById('pcMarket');
  if (!el) return;
  const M = (P.market && typeof P.market === 'object' && !Array.isArray(P.market)) ? P.market : {};
  const keys = Object.keys(M).filter(k => M[k] !== null && M[k] !== undefined && M[k] !== '');
  const rows = keys.map(k => `<div class="mrow"><span class="m-name dim">${escHtml(pretty(k))}</span>` +
    `<span class="num">${pcVal(M[k])}</span></div>`);
  el.innerHTML = rows.join('') || '<div class="dim pad">—</div>';
  /* the profile's own market numbers live on /api/trader, fetched once */
  if (!rows.length) loadTrader().then(T => {
    const st = (T && T.state) || {}, out = [];
    if (st.account) out.push(`<div class="mrow"><span class="m-name dim">Account</span><span class="num">${escHtml(String(st.account))}</span></div>`);
    if (typeof st.plat === 'number') out.push(`<div class="mrow"><span class="m-name dim">Platinum</span><span class="num">${fmt(st.plat)}p</span></div>`);
    if (typeof st.trades_left === 'number') out.push(`<div class="mrow"><span class="m-name dim">Trades left</span><span class="num">${fmt(st.trades_left)}</span></div>`);
    const orders = st.orders && typeof st.orders === 'object' ? Object.keys(st.orders).length : 0;
    out.push(`<div class="mrow"><span class="m-name dim">Orders live</span><span class="num">${fmt(orders)}</span></div>`);
    el.innerHTML = out.join('') || '<div class="dim pad">—</div>';
  }).catch(() => {});
}

async function loadTrader() {
  if (!state.trader) state.trader = await fetch('/api/trader').then(r => r.json()).catch(() => ({}));
  return state.trader;
}
/* ---------- /player page ---------- */


/* ---------- init ---------- */
const savedTheme = localStorage.getItem('wfm.theme');
buildThemeGrid();
PlatChart.init();
/* The chart opens on its default range (30d) or on the range the user last picked - the stored
   choice wins, and the pill in the card head follows whatever the chart actually opened on, so
   the control never disagrees with the line it is labelling. */
(function syncRangePills() {
  const info = PlatChart.info ? PlatChart.info() : null;
  if (!info || !info.range) return;
  document.querySelectorAll('#ranges button').forEach(b =>
    b.classList.toggle('active', b.dataset.r === info.range));
})();
applyTheme(savedTheme === null ? 0 : (+savedTheme || 0));
applyHash();
window.addEventListener('hashchange', applyHash);
/* trade sub-tabs write the hash so a tab is deep-linkable (#trade/buy) */
document.querySelectorAll('#tradeTabs [role="tab"]').forEach(t => t.addEventListener('click', () => {
  switchTradeTab(t.dataset.tp);
  if (history.replaceState) history.replaceState(null, '', '#trade/' + t.dataset.tp.replace('tp-', ''));
}));
/* opening/closing the held-back panel gives the plan table a different amount of room */
const heldAcc = document.getElementById('heldAcc');
if (heldAcc) heldAcc.addEventListener('toggle', () => markScrollers());

/* one action per trade row: a recommended listing or an attention row opens the shared item
   drawer, the same wfmOpenItem the inventory rows use - no per-row buttons to confuse the plan */
const tradeView = document.getElementById('view-trade');
if (tradeView) tradeView.addEventListener('click', e => {
  const row = e.target.closest('[data-slug]');
  if (row && row.dataset.slug && window.wfmOpenItem) wfmOpenItem(row.dataset.slug);
});

document.querySelectorAll('#ranges button').forEach(b => b.addEventListener('click', () => {
  document.querySelectorAll('#ranges button').forEach(x => x.classList.toggle('active', x === b));
  PlatChart.setRange(b.dataset.r);
}));

document.querySelectorAll('#hFilters button').forEach(b => b.addEventListener('click', () => {
  document.querySelectorAll('#hFilters button').forEach(x => x.classList.toggle('active', x === b));
  hFilter = b.dataset.f; renderHistory();
}));

async function traderAction(id, path, busy) {
  const b = document.getElementById(id);
  const old = b.textContent;
  b.disabled = true; b.textContent = busy; iconRepaint(b);
  try {
    const r = await fetch(path, { method: 'POST' });
    await r.text();
    await load();
  }
  finally { b.disabled = false; b.textContent = old; iconRepaint(b); }
}
/* bind only when the control exists - the redesigned views move some buttons around */
function bind(id, fn) {
  const el = document.getElementById(id);
  if (el) el.addEventListener('click', fn);
}
/* Assigning textContent drops a host's data-icon glyph, and icons.js only ever draws a host
   once - re-arm it and let the library paint the icon again (the swap and the repaint are the
   same task, so nothing flickers). Called after every dynamic label change. */
function iconRepaint(el) {
  const I = window.wfmIcons;
  if (!el || !el.getAttribute || !el.getAttribute('data-icon') || !I) return;
  el.removeAttribute('data-icon-done');
  const draw = () => I.render(document);
  if (I.ready) I.ready().then(draw); else draw();
}
bind('btnPlan', () => traderAction('btnPlan', '/api/trader/plan', 'Building…'));
bind('btnCycle', () => traderAction('btnCycle', '/api/trader/cycle', 'Running…'));
bind('btnWatch', () => traderAction('btnWatch', '/api/trader/watch', 'Checking…'));
bind('btnRunq', () => traderAction('btnRunq', '/api/trader/runqueue', 'Scanning buyers…'));
bind('btnHygiene', () => traderAction('btnHygiene', '/api/trader/hygiene', 'Planning…'));
bind('btnNotify', () => traderAction('btnNotify', '/api/trader/notify', 'Sending…'));
bind('btnExportPng', () => WFMExportPicks(REPORT && REPORT.sell_now));
bind('btnKill', async () => {
  const active = !((FEAT.killswitch || {}).active);
  const note = (document.getElementById('killNote') || {}).value || '';
  try {
    await fetch('/api/trader/killswitch', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ active, note }),
    });
  } finally { await load(); }
});

/* ---------- global item search: owned items + the full WFM catalogue ---------- */
function catalogLoad() {
  if (CATALOG) return Promise.resolve(CATALOG);
  if (!CATALOG_LOADING) {
    CATALOG_LOADING = fetch('/api/catalog').then(r => r.json())
      .then(rows => { CATALOG = Array.isArray(rows) ? rows : []; return CATALOG; })
      .catch(() => { CATALOG = []; return CATALOG; });
  }
  return CATALOG_LOADING;
}

function searchMatches(q) {
  q = (q || '').trim().toLowerCase();
  if (q.length < 2) return [];
  const owned = new Map(ITEMS.map(r => [r.slug, r]));
  const out = [];
  const pool = CATALOG || ITEMS;
  for (const c of pool) {
    if ((c.slug || '').includes(q) || (c.name || '').toLowerCase().includes(q)) {
      out.push({ slug: c.slug, name: c.name, owned: owned.get(c.slug) || null });
    }
    if (out.length >= 40) break;
  }
  out.sort((a, b) => (b.owned ? 1 : 0) - (a.owned ? 1 : 0)
    || (a.name || '').toLowerCase().indexOf(q) - (b.name || '').toLowerCase().indexOf(q));
  return out.slice(0, 8);
}

function searchDropRender(q) {
  const drop = document.getElementById('searchDrop');
  const input = document.getElementById('search');
  if (!drop) return;
  const rows = searchMatches(q);
  drop.classList.toggle('hidden', !rows.length);
  if (input) input.setAttribute('aria-expanded', String(!!rows.length));
  drop.innerHTML = rows.map(r => `
    <button class="srowx" role="option" data-slug="${escHtml(r.slug)}">
      <span class="s-name">${escHtml(r.name)}</span>
      ${r.owned ? `<span class="s-own">${r.owned.count} owned · ${laneVal(r.owned) ?? '—'}p</span>` : '<span class="s-own dim">not owned</span>'}
    </button>`).join('');
  drop.querySelectorAll('button[data-slug]').forEach(b => b.addEventListener('click', () => globalSearchPick(b.dataset.slug)));
}

function globalSearchPick(slug) {
  const drop = document.getElementById('searchDrop');
  if (drop) drop.classList.add('hidden');
  if (window.wfmOpenItem) wfmOpenItem(slug);
  else location.hash = '#search?q=' + encodeURIComponent(slug);
}

function globalSearchOpen(q) {
  const input = document.getElementById('search');
  catalogLoad().then(() => {
    if (input && q) input.value = q;
    if (q) {
      const m = searchMatches(q);
      const exact = m.find(r => r.slug === q) || (m.length === 1 ? m[0] : null);
      if (exact) { globalSearchPick(exact.slug); return; }
    }
    searchDropRender(q || '');
  });
}

const searchInput = document.getElementById('search');
if (searchInput) {
  searchInput.addEventListener('focus', () => catalogLoad());
  searchInput.addEventListener('input', e => { catalogLoad(); searchDropRender(e.target.value); });
  searchInput.addEventListener('keydown', e => {
    if (e.key === 'Enter') {
      const first = document.querySelector('#searchDrop button[data-slug]');
      if (first) globalSearchPick(first.dataset.slug);
    } else if (e.key === 'Escape') {
      const drop = document.getElementById('searchDrop');
      if (drop) drop.classList.add('hidden');
      searchInput.blur();
    }
  });
}
document.addEventListener('click', e => {
  const drop = document.getElementById('searchDrop');
  if (drop && !drop.classList.contains('hidden') && !drop.contains(e.target) && e.target !== searchInput) drop.classList.add('hidden');
});

document.addEventListener('keydown', e => {
  if (e.key === '/' && !/input|textarea/i.test((e.target.tagName || ''))) {
    e.preventDefault();
    if (searchInput) searchInput.focus();
  }
});

/* inventory-local filter (the header search is the global lookup) */
const invQ = document.getElementById('invQ');
if (invQ) invQ.addEventListener('input', e => { state.q = e.target.value.trim(); renderTable(); });
/* materials card: local search + the Count/Name sort toggle */
const matQ = document.getElementById('matQ');
if (matQ) matQ.addEventListener('input', e => { state.matQ = e.target.value.trim(); renderMaterials(); });
const matSort = document.getElementById('matSort');
if (matSort) matSort.addEventListener('click', () => {
  state.matSort = state.matSort === 'count' ? 'name' : 'count';
  matSort.textContent = 'Sort: ' + (state.matSort === 'count' ? 'Count' : 'Name');
  iconRepaint(matSort);
  renderMaterials();
});
/* clan dojo card: the tier switch the wiki lists its cost tables by (ghost..moon) */
function dojoTierLabel(D, TT) {
  const tiers = (D && D.tiers) || [];
  if (!TT || tiers.indexOf(state.dojoTier) < 0) return 'ghost clan';
  return state.dojoTier + ' clan';
}
const dojoTierRow = document.getElementById('dojoTier');
const paintDojoTier = () => {
  if (!dojoTierRow) return;
  const D = (state.materials || {}).dojo || {};
  const known = (D.tiers || []).indexOf(state.dojoTier) >= 0 && !!(D.tier_totals || {})[state.dojoTier];
  const on = known ? state.dojoTier : 'ghost';
  dojoTierRow.querySelectorAll('button[data-t]').forEach(b =>
    b.setAttribute('aria-pressed', String(b.dataset.t === on)));
};
if (dojoTierRow) {
  if (((state.materials || {}).dojo || {}).tiers && ((state.materials || {}).dojo || {}).tiers.indexOf(
    localStorage.getItem('wfm.dojoTier') || '') >= 0) {
    state.dojoTier = localStorage.getItem('wfm.dojoTier');
  }
  dojoTierRow.addEventListener('click', e => {
    const b = e.target.closest('button[data-t]');
    if (!b) return;
    state.dojoTier = b.dataset.t;
    try { localStorage.setItem('wfm.dojoTier', state.dojoTier); } catch (err) { /* storage off */ }
    paintDojoTier();
    renderDojo();
  });
}

/* materials card: the Personal/Dojo swap (remembered in localStorage, never re-fetches) */
const matViewRow = document.getElementById('matView');
function syncMatView() {
  if (!matViewRow) return;
  matViewRow.querySelectorAll('button[data-m]').forEach(b =>
    b.setAttribute('aria-pressed', String(b.dataset.m === state.matView)));
}
if (matViewRow) {
  if (localStorage.getItem('wfm.matView') === 'dojo') state.matView = 'dojo';
  syncMatView();
  matViewRow.addEventListener('click', e => {
    const b = e.target.closest('button[data-m]');
    if (!b) return;
    state.matView = b.dataset.m === 'dojo' ? 'dojo' : 'personal';
    try { localStorage.setItem('wfm.matView', state.matView); } catch (err) { /* storage off */ }
    syncMatView();
    renderMaterials();
  });
}
/* inventory rows open the shared item drawer */
document.getElementById('rows').addEventListener('click', e => {
  const tr = e.target.closest('tr.inv-row');
  if (!tr || !tr.dataset.slug) return;
  if (window.wfmOpenItem) wfmOpenItem(tr.dataset.slug);
});
/* "All columns" toggle */
const btnCols = document.getElementById('btnCols');
if (btnCols) btnCols.addEventListener('click', () => {
  const on = document.body.classList.toggle('show-a');
  btnCols.setAttribute('aria-pressed', String(on));
  btnCols.textContent = on ? 'Fewer columns' : 'All columns';
  iconRepaint(btnCols);
});
document.querySelectorAll('thead th').forEach(th => th.addEventListener('click', () => {
  const k = th.dataset.k;
  if (!k) return;               /* Trend renders a series, it is not a sort key */
  if (state.sort === k) state.dir *= -1; else { state.sort = k; state.dir = (k === 'name' || k === 'cat') ? 1 : -1; }
  renderTable();
}));
const tBtn = document.getElementById('themeBtn');
const tPanel = document.getElementById('themePanel');
const tSync = () => tBtn.setAttribute('aria-expanded', String(!tPanel.classList.contains('hidden')));
tBtn.addEventListener('click', e => { e.stopPropagation(); tPanel.classList.toggle('hidden'); tSync(); });
document.addEventListener('click', e => {
  if (!tPanel.classList.contains('hidden') && !tPanel.contains(e.target) && e.target !== tBtn) { tPanel.classList.add('hidden'); tSync(); }
});
document.addEventListener('keydown', e => { if (e.key === 'Escape') { tPanel.classList.add('hidden'); tSync(); } });
window.wfmThemeUI = true;      /* the panel is wired here: the shell leaves it alone */

document.getElementById('refresh').addEventListener('click', async e => {
  const b = e.target; b.disabled = true; b.textContent = 'Refreshing…'; iconRepaint(b);
  try {
    const r = await fetch('/api/refresh', { method: 'POST' }).then(r => r.json());
    if (!r.ok) { if (window.sfx) sfx.play('warn'); alert('Refresh failed: ' + (r.stderr || r.error || 'unknown')); }
    else if (window.sfx) sfx.play('done');
    await load();
  } finally { b.disabled = false; b.textContent = 'Refresh'; iconRepaint(b); }
});

/* the trade lists settle a frame or two after the data lands (details content, flex heights, the 20
   rows themselves) - mark once more so a fresh load on #trade wears the same fade a click does */
load().then(function () { window.setTimeout(markScrollers, 250); }).catch(function () {});

/* auto-refresh: 30s until /api/config lands, then auto_refresh_seconds (capped to 60s) */
syncAutoRefresh(null);
/* header status: the server's sync loop, once now and then every minute */
loadSyncState();
setInterval(loadSyncState, SYNC_POLL_MS);
