/* WFM Trader — dashboard frontend (vanilla JS) */
'use strict';

const THEMES = window.WFM_THEMES; /* single source: static/theme.js */
const TVARS = ['bg', 'panel', 'panel2', 'border', 'text', 'muted', 'accent', 'accentDim', 'hover'];

function applyTheme(i) { wfmApplyTheme(i); }

function buildThemeGrid() { wfmBuildThemeGrid(); }

/* ---------- data ---------- */
let ITEMS = [], SUMMARY = null, PLAT = null, REPORT = null, TRADES = null, TRADER = null, GAMENEWS = null, FEAT = {};
let state = { tab: 'all', sort: 'value', dir: -1, q: '' };
/* global item search cache - declared up here because the hash router can call into
   the search before the rest of the file has run (classic script, no module scope) */
let CATALOG = null, CATALOG_LOADING = null;

const CATS = [
  ['all', 'All'], ['prime_part', 'Prime Parts'], ['prime_bp', 'Blueprints'],
  ['relic', 'Relics'], ['arcane', 'Arcanes'], ['mod', 'Mods'], ['other', 'Other']
];
const CAT_LABEL = Object.fromEntries(CATS);

const fmt = n => (n === null || n === undefined) ? '—' : n.toLocaleString();
const ago = ts => {
  if (!ts) return '—';
  const s = Math.max(0, Math.floor(Date.now() / 1000 - ts));
  if (s < 90) return s + 's ago';
  if (s < 5400) return Math.round(s / 60) + 'm ago';
  return Math.round(s / 3600) + 'h ago';
};

function renderChips() {
  const s = SUMMARY; if (!s) return;
  document.getElementById('chips').innerHTML = `
    <span class="chip">MR <b>${s.mr ?? '—'}</b></span>
    <span class="chip warn">Trades <b>${s.trades ?? '—'}</b>/day left</span>
    <span class="chip">Credits <b>${(s.credits ?? 0).toLocaleString()}</b></span>
    <span class="chip">Synced <b>${ago(s.lastdata_mtime)}</b></span>
    <span class="chip">Prices <b>${s.priced ?? 0}/${s.items ?? 0}</b></span>
    <span class="chip">Est. value <b>${(s.total_value ?? 0).toLocaleString()}p</b></span>`;
}

/* ---------- views ---------- */
const VIEWS = ['home', 'inventory', 'trade', 'more'];
/* legacy hashes from the 9-pill era still resolve: #history/#trader -> trade, #market -> more */
const VIEW_ALIAS = { home: 'home', inventory: 'inventory', trade: 'trade', more: 'more',
  history: 'trade', trader: 'trade', market: 'more' };

function showView(v) {
  if (!VIEWS.includes(v)) v = 'home';
  VIEWS.forEach(name => {
    const el2 = document.getElementById('view-' + name);
    if (el2) el2.classList.toggle('hidden', name !== v);
  });
  document.querySelectorAll('#mainnav .navpill').forEach(el2 =>
    el2.classList.toggle('active', el2.dataset.v === v));
  if (window.PlatChart) PlatChart.redraw();
  if (v === 'home' && window.wfmRenderHome) wfmRenderHome();
}

/* trade sub-tabs (Sell / Buy / History) */
function switchTradeTab(panelId) {
  const tabs = document.querySelectorAll('#tradeTabs [role="tab"]');
  if (!tabs.length) return;
  const ok = [...tabs].some(t => t.dataset.tp === panelId);
  if (!ok) panelId = 'tp-sell';
  tabs.forEach(t => t.setAttribute('aria-selected', String(t.dataset.tp === panelId)));
  document.querySelectorAll('#view-trade .tpanel').forEach(p2 => p2.classList.toggle('hidden', p2.id !== panelId));
}

function applyHash() {
  const raw = (location.hash || '#home').slice(1);
  const [path, query] = raw.split('?');
  const [v, sub] = path.split('/');
  if (v === 'collection' || v === 'cards') { location.replace('/' + v + '.html'); return; }
  if (v === 'search') {
    showView('home');
    globalSearchOpen((new URLSearchParams(query || '')).get('q') || '');
    return;
  }
  const view = VIEW_ALIAS[v] || 'home';
  showView(view);
  if (view === 'trade') {
    switchTradeTab(v === 'history' ? 'tp-history' : (sub ? 'tp-' + sub : 'tp-sell'));
  }
}

/* first run: setup has not built any data yet - say exactly what to do instead of
   showing empty cards (a fresh clone has no data/ at all; SUMMARY comes back empty) */
function renderFirstRun() {
  const el = document.getElementById('firstRun');
  if (!el) return;
  const s = SUMMARY || {};
  const empty = !s.lastdata_mtime || !s.items;
  el.classList.toggle('hidden', !empty);
  if (!empty) { el.innerHTML = ''; return; }
  el.innerHTML = `
    <div class="card-head"><div class="card-title">First run - no data yet</div></div>
    <div class="picks">
      <div class="picks-note"><b>Windows:</b> double-click <code>setup.bat</code> in the project folder.
        It installs the one dependency, reads your AlecaFrame inventory and fetches prices
        (20-40 minutes, resumable — stop it any time and run it again).</div>
      <div class="picks-note"><b>Any platform / manual:</b> <code>pip install cryptography</code> then
        <code>python scripts/setup.py</code>.</div>
      <div class="picks-note"><b>Needs:</b> Warframe + <a class="movedlink" href="https://alecaframe.com" target="_blank" rel="noopener">AlecaFrame</a>
        installed and synced once (open the game after installing it).</div>
      <div class="picks-note dim">Once setup finishes, press <b>Refresh</b> in the header — this banner disappears when data lands.</div>
    </div>`;
}

/* ---------- home ---------- */
function renderKpis() {
  const s = SUMMARY || {}, ph = PLAT || {};
  const d = (v) => (v === null || v === undefined)
    ? '<span class="dim">—</span>'
    : `<span class="${v >= 0 ? 'upl' : 'downl'}">${v >= 0 ? '+' : ''}${v.toLocaleString()}p</span>`;
  document.getElementById('kpis').innerHTML = `
    <div class="kpi"><div class="k-label">Platinum now</div><div class="k-val accent">${(ph.now ?? s.plat ?? 0).toLocaleString()}p</div></div>
    <div class="kpi"><div class="k-label">Δ 24h</div><div class="k-val">${d(ph.d24)}</div></div>
    <div class="kpi"><div class="k-label">Δ 7d</div><div class="k-val">${d(ph.d7)}</div></div>
    <div class="kpi"><div class="k-label">Trades left</div><div class="k-val">${s.trades ?? '—'}</div></div>
    <div class="kpi" title="sellable only · equipped copies never count · owned basis: ${(s.total_value_owned ?? s.total_value ?? 0).toLocaleString()}p)"><div class="k-label">Inventory value</div><div class="k-val">${(s.total_value ?? 0).toLocaleString()}p</div></div>
    <div class="kpi"><div class="k-label">Credits</div><div class="k-val">${(s.credits ?? 0).toLocaleString()}</div></div>`;
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
function advNote(slug) {
  const a = advOf(slug);
  if (!a) return '';
  const bits = [];
  if (a.demand_badge) bits.push(a.demand_badge === 'spike' ? 'demand rising' : a.demand_badge === 'fade' ? 'demand fading' : 'demand steady');
  if (a.best_sell_window) bits.push('best ' + a.best_sell_window);
  if (a.sellable) bits.push(a.sellable + ' sellable');
  return bits.length ? ` <span class="advchip" title="${escHtml((a.reasons || []).join(' · '))}">advisor: ${bits.join(' · ')}</span>` : '';
}

function renderPicks() {
  /* the old Dashboard "Top sell picks" card is retired: HOME renders the advisor-driven
     Today block (home.js) and TRADE > Sell renders the live plan. Kept only so the
     export path and any stale markup keep working. */
  const el = document.getElementById('sellPicks');
  if (!el) return;
  const rs = (REPORT && REPORT.sell_now || []).filter((r) => !r.in_use_only).slice(0, 8);
  const note = `<div class="picks-note dim"><b>Sorted by earnings × how fast they sell.</b> List at = cheapest listing at your copy's rank (an <b>R#</b> tag marks a rank-priced row) minus 1p. Copies slotted in a build are never listed. <b>Do</b> = smart sell advisor call — hover for the reasons.</div>`;
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
  if (!ph.n) { el.textContent = 'Collector runs every 15 min — first point lands within a few minutes.'; return; }
  const since = new Date(ph.first_ts * 1000).toLocaleDateString([], { month: 'short', day: 'numeric' });
  el.textContent = `${ph.n} snapshots since ${since} · collector runs every 15 min`;
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
    `<div class="empty">Nothing here yet — fills automatically once the trader runs.</div>`;
}

/* ---------- game updates ---------- */
function fmtDay(ts) {
  if (!ts) return '—';
  return new Date(ts * 1000).toLocaleDateString(undefined, { day: 'numeric', month: 'short' });
}
function renderNews() {
  const n = GAMENEWS || {};
  document.getElementById('newsMeta').textContent =
    (n.version ? `· v${n.version}` : '') + (n.fetched ? ` · checked ${ago(n.fetched)}` : ' · not loaded');
  const items = (n.items || []).slice(0, 7);
  document.getElementById('newsList').innerHTML = items.length
    ? items.map(it => `<div class="newsrow">
        <span class="n-date">${fmtDay(it.date)}</span>
        <a class="n-title" href="${it.url}" target="_blank" rel="noopener" title="${(it.excerpt || '').replace(/"/g, '&quot;')}">${it.title}</a>
        <span class="n-src dim">${it.source}</span>
      </div>`).join('')
    : `<div class="empty">No updates fetched yet.</div>`;
}

/* ---------- trader ---------- */
function renderTrader() {
  const t = TRADER || {};
  const plan = t.plan || {}, stt = t.state || {}, set = t.settings || {}, q = t.queue || [];
  const rows = plan.plan || [];
  const plannedValue = rows.reduce((a, r) => a + (r.est_total || 0), 0);
  const held = plan.held_list || [];
  const ordersN = stt.orders ? Object.keys(stt.orders).length : (plan.live_orders || 0);
  /* the trader KPI row is retired - those facts now live in Advanced > Engine status
     (renderEngine below) so the default Trade surface stays action-first */
  document.getElementById('planMeta').textContent = plan.generated
    ? `· built ${ago(plan.generated)}${plan.mr != null ? ' · MR ' + plan.mr : ''}` : '';
  const head = `<div class="prow plan-head"><span>#</span><span>Item</span><span class="p-qty">Qty</span><span class="p-price">List at</span><span class="p-est">Est</span><span class="p-note">Notes</span></div>`;
  document.getElementById('planList').innerHTML = rows.length
    ? head + rows.map((r, i) => `
      <div class="prow">
        <span class="dim">${i + 1}</span>
        <span class="l-name" title="${r.name}">${r.name}</span>
        <span class="p-qty">${r.qty}</span>
        <span class="p-price">${r.price}p</span>
        <span class="p-est">${(r.est_total || 0).toLocaleString()}p</span>
        <span class="p-note">${r.note || (r.subtype || '')}${advNote(r.slug)}</span>
      </div>`).join('')
    : `<div class="empty">No plan yet — hit "Rebuild plan".</div>`;
  document.getElementById('heldMeta').textContent = held.length ? `· ${held.length}` : '';
  document.getElementById('heldList').innerHTML = held.length
    ? held.map(h => `<div class="heldline"><span class="l-name">${h[0]}</span><span class="dim">${h[1]}</span></div>`).join('')
    : `<div class="empty">Nothing held back.</div>`;
  const det = [];
  if (stt.ts) det.push(`last cycle ${ago(stt.ts)} · account ${stt.account || '—'} · tracked orders ${ordersN} · events last cycle ${stt.last_cycle_events ?? 0}`);
  for (const x of q.slice(-10)) det.push(`relist queued: ${x.name} x${x.sold} @ ${x.price}p (${x.status})`);
  if (!stt.ts && !q.length) det.push('Detector has not run yet — hit "Run detector".');
  document.getElementById('detList').innerHTML = det.map(x => `<div class="heldline dim">${x}</div>`).join('');
  document.getElementById('detMeta').textContent = stt.ts ? `· watching ${ordersN} orders` : '';
  const w = t.undercuts || {};
  document.getElementById('attnMeta').textContent = w.generated
    ? `· checked ${ago(w.generated)}` : '';
  const wr = w.rows || [];
  const attn = wr.map(r => `<div class="heldline">
        <span class="l-name">${escHtml(r.name)}${r.lane ? ' · ' + escHtml(r.lane) : ''}</span>
        <span class="dim">${r.floor != null && r.my_price != null && r.floor < r.my_price
          ? `someone listed at ${r.floor}p - below your ${r.my_price}p`
          : `you're at ${r.my_price}p · best now ${r.floor ?? '—'}p`}${r.proposed ? ` · reprice to ${r.proposed}p` : ''}${r.reason ? ' · ' + escHtml(r.reason) : ''}</span>
      </div>`);
  const hy = FEAT.hygiene || {}, hc = hy.summary || {};
  if (hc.total) attn.push(`<div class="heldline"><span class="l-name">Listings that haven't moved</span><span class="dim">${hc.hide} hide · ${hc.refresh} reprice · ${hc.show} restore${(hy.rules || {}).auto_hide_offline ? ` · auto-hide after ${(hy.rules || {}).offline_window_minutes} min offline` : ''}</span></div>`);
  document.getElementById('attnList').innerHTML = attn.length
    ? attn.join('')
    : (w.generated
        ? `<div class="empty">Nothing needs attention right now.</div>`
        : `<div class="empty">Not checked yet - hit "Check now".</div>`);
  renderRunQueue(); renderFlipper(); renderHygiene(); renderNotify(); renderEngine();
}

/* Advanced > Engine status: the facts the old trader KPI row used to show */
function renderEngine() {
  const t = TRADER || {}, stt = t.state || {}, set = t.settings || {}, plan = t.plan || {};
  const el = document.getElementById('engList');
  if (!el) return;
  const ordersN = stt.orders ? Object.keys(stt.orders).length : (plan.live_orders || 0);
  const plannedValue = (plan.plan || []).reduce((a, r) => a + (r.est_total || 0), 0);
  const K = FEAT.killswitch || {};
  const m = document.getElementById('engMeta');
  if (m) m.textContent = '· posting ' + (set.dry_run === false ? 'LIVE' : 'off (dry run)') + (K.active ? ' · kill switch engaged' : '');
  const line = (k, v) => `<div class="mrow"><span class="m-name dim">${k}</span><span class="num">${v}</span></div>`;
  el.innerHTML =
    line('Posting mode', set.dry_run === false ? 'LIVE - orders can post' : 'Dry run - nothing is posted to warframe.market') +
    line('Trades left today', stt.trades_left ?? '—') +
    line('Live orders', ordersN) +
    line('Platinum balance', stt.plat != null ? stt.plat.toLocaleString() + 'p' : '—') +
    line('Planned listings', plan.planned ?? (plan.plan || []).length) +
    line('Plan value', plannedValue.toLocaleString() + 'p') +
    line('Last market check', stt.ts ? ago(stt.ts) : 'not yet');
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
  el.innerHTML = rows.map(q => `<div class="runrow">
      <span class="m-name" title="${escHtml(q.why || '')}">${escHtml(q.name)} <span class="dim">x${q.qty} @ ${q.my_price}p</span></span>
      <span class="num"><span class="chip act-${q.buyer_status}">${q.buyer_status}</span> ${escHtml(q.buyer)} · ${q.buy_price}p</span>
      <span class="runwhisper" title="copy-paste whisper">${escHtml(q.whisper)}</span>
    </div>`).join('');
}

function renderFlipper() {
  const P = FEAT.flipper || {}, b = P.budget || {}, c = P.counts || {};
  const m = document.getElementById('flipPlanMeta');
  if (!m) return;
  m.textContent = b.buy_budget_p !== undefined
    ? `· ${(P.orders || []).length} buy orders · spend ${b.planned_spend_p}p of ${b.buy_budget_p}p · ${c.skipped ?? (P.skipped || []).length} skipped · ${P.mode || ''}`
    : '';
  const el = document.getElementById('flipPlanList');
  const rows = P.orders || [];
  if (!rows.length) { el.innerHTML = '<div class="dim pad">Run scripts/trader/flipper.py</div>'; return; }
  const line = o => `<div class="mrow">
      <span class="m-name" title="${escHtml(o.slug)} · ${escHtml(o.why || '')}">${escHtml(o.name || pretty(o.slug))} <span class="chip kind-${o.kind}">${o.kind}</span> <span class="dim small">${o.sales_day}/day</span></span>
      <span class="num upl">buy ${o.buy_at}p <span class="dim">→</span> ${o.relist_at}p <span class="dim">+${o.profit_each}p (${o.roi_pct}%)</span></span>
    </div>`;
  let html = `<div class="subhead">Plan only — nothing posted</div>` + rows.map(line).join('');
  const sk = (P.skipped || []).slice(0, 5);
  if (sk.length) html += `<div class="subhead">Skipped</div>` + sk.map(s2 => `<div class="mrow"><span class="m-name">${escHtml(pretty(s2.slug))}</span><span class="num dim small">${escHtml(s2.reason)}</span></div>`).join('');
  el.innerHTML = html;
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
  let html = `<div class="limrow"><b>DRY RUN — plan only</b><span class="dim">${acts.length} action(s) · ${ent.live || 0} live / ${ent.pending || 0} planned listings</span></div>`;
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
    `<div class="mrow"><span class="m-name dim small">${escHtml(s.note || '')}</span><span class="num dim small">${Object.entries(kinds).map(([k, v]) => `${escHtml(k)} ${v.sales}`).join(' · ')}</span></div>`;
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
    bands.map(b => `<div class="srow"><span class="d-name">${escHtml(b.name)}</span><span class="num">${b.floor}p</span><span class="num">${b.median}p</span><span class="num dim">${b.vol48 ?? '—'}</span><span></span></div>`).join('');
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
  const line = (r2, up) => `<div class="mrow"><span class="m-name">${escHtml(r2.name || pretty(r2.slug))} <span class="dim small">48h ${r2.vol48} · base ${r2.vol30_baseline}/d${r2.post_patch ? ' · post-patch' : ''}</span></span>
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
  const rows = N.slice().reverse().slice(0, 6);
  const sent = N.filter(r => r.status === 'sent').length;
  if (m) m.textContent = N.length ? `· ${N.length} in outbox · ${sent} delivered (rest dry-run)` : '· no outbox yet';
  el.innerHTML = rows.length ? rows.map(r => `<div class="mrow"><span class="m-name">${escHtml(r.title)} <span class="dim small">${escHtml(r.to || '')}</span></span><span class="num"><span class="chip ${r.status === 'sent' ? 'act-show' : 'act-offline'}">${escHtml(r.status)}</span> ${r.ts ? ago(Date.parse(r.ts) / 1000) : ''}</span></div>`).join('')
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
    `<div class="mrow"><span class="m-name dim small">${escHtml((L.notes || [])[0] || '')}</span><span class="num dim small">${chk.reconciles ? 'reconciles ✓' : 'NOT reconciled'} · tolerance ${chk.tolerance}p</span></div>`;
}

/* ---------- auto-refresh cadence (#45): auto_refresh_seconds from /api/config ---------- */
let AUTO_REFRESH_S = 0, autoTimer = null;
function syncAutoRefresh(values) {
  const raw = Number((values || {}).auto_refresh_seconds);
  const secs = (Number.isFinite(raw) && raw > 0) ? Math.max(15, Math.floor(raw)) : 30;
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
      <td class="name">${r.name}</td>
      <td class="num">${fmt(r.count)}</td>
      <td class="num">${fmt(advField(r, 'equipped'))}</td>
      <td class="num">${fmt(safeOf(r))}</td>
      <td class="num">${fmt(laneVal(r))}${rkTag}</td>
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
  if (!slice.length) tbody.innerHTML = '<tr><td colspan="13" class="dim" style="padding:18px">No items match.</td></tr>';
  const tot = rs.reduce((a, r) => a + laneValue(r), 0);
  document.getElementById('totals').innerHTML =
    `<span>${rs.length} stacks <span class="dim">(showing ${slice.length})</span></span>
     <span>Filtered value <b class="big">${tot.toLocaleString()}p</b></span>`;
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
  await Promise.all(['deals', 'ducats', 'sets', 'relics', 'limits', 'sessions', 'invdiff', 'movers', 'flips', 'trends', 'baro', 'wishlist', 'nudges', 'killswitch', 'flipper', 'hygiene', 'runqueue', 'timing', 'watchlist', 'rivens', 'meta', 'craft', 'notify', 'ledger', 'advisor']
    .map(async n => { FEAT[n] = await fetch('/api/feature/' + n).then(r => r.json()).catch(() => null); }));
  renderChips(); renderTabs(); renderTable();
  renderKpis(); renderPicks(); renderChartMeta(); renderHistory(); renderTrader(); renderNews();
  renderFirstRun();
  if (window.wfmRenderHome) wfmRenderHome();
  renderMarket(); renderLimits(); renderSessions(); renderDiff(); renderKill(); renderTiming(); renderPlatLedger(); loadAutoRefresh();
  PlatChart.setData(ph.points || []);
  document.getElementById('status').textContent = s.lastdata_mtime
    ? `prices updated ${ago(s.prices_mtime)} · data ${new Date().toLocaleTimeString()}`
    : 'No data yet — run: python scripts/setup.py';
  document.getElementById('foot').textContent =
    `WFM Trader · refreshed ${new Date().toLocaleTimeString()} · ${(tr && tr.n) || 0} history events · prices refresh every 15 min`;
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
    `<div class="subhead">Burn into ducats — plat would earn less than Baro value</div>` +
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
  el.innerHTML = `<div class="limrow">
    <span class="lim-big">${L.trades_left ?? '—'}<span class="dim">/${L.trade_cap}</span></span>
    <span class="dim">trades left · used ${L.trades_used ?? '—'} · resets ${(L.reset_melbourne || '').slice(11, 16)} in ${h}h ${mn}m · ${L.mr_label || ''} · ${L.account || ''}</span>
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
      <span class="m-name">${escHtml(r.name || pretty(r.slug))} <span class="dim small">30d ${r.vol30} · 90d ${r.vol90}</span></span>
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
  document.getElementById('killMeta').textContent = K.active ? '· ENGAGED' : '· disarmed';
  const ts = K.ts ? new Date(K.ts * 1000).toLocaleString([], { hour12: false }) : '';
  el.innerHTML = `<div class="limrow">
    <span class="lim-big ${K.active ? 'kill-on' : ''}">${K.active ? 'ARMED' : 'OFF'}</span>
    <span class="dim">kill switch ${K.active ? 'engaged — every engine refuses to run' : 'disarmed — engines may run'}${K.note ? ' · ' + escHtml(K.note) : ''}${ts ? ' · ' + ts : ''}</span>
  </div>
  <div class="limrow"><input id="killNote" class="noteinput" placeholder="note (why / what)" maxlength="200">
    <span class="dim small">All engines still dry-run — this is the hard stop for when posting ships.</span></div>`;
}

/* ---------- init ---------- */
const savedTheme = localStorage.getItem('wfm.theme');
buildThemeGrid();
PlatChart.init();
applyTheme(savedTheme === null ? 0 : (+savedTheme || 0));
applyHash();
window.addEventListener('hashchange', applyHash);
/* trade sub-tabs write the hash so a tab is deep-linkable (#trade/buy) */
document.querySelectorAll('#tradeTabs [role="tab"]').forEach(t => t.addEventListener('click', () => {
  switchTradeTab(t.dataset.tp);
  if (history.replaceState) history.replaceState(null, '', '#trade/' + t.dataset.tp.replace('tp-', ''));
}));

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
  b.disabled = true; b.textContent = busy;
  try {
    const r = await fetch(path, { method: 'POST' });
    const out = await r.text();
    const el = document.getElementById('rawOut');
    if (el) el.textContent = new Date().toLocaleTimeString() + ' · ' + path + ' (HTTP ' + r.status + ')\n' + out.slice(0, 4000);
    await load();
  }
  finally { b.disabled = false; b.textContent = old; }
}
/* bind only when the control exists - the redesigned views move some buttons around */
function bind(id, fn) {
  const el = document.getElementById(id);
  if (el) el.addEventListener('click', fn);
}
bind('btnPlan', () => traderAction('btnPlan', '/api/trader/plan', 'Building…'));
bind('btnCycle', () => traderAction('btnCycle', '/api/trader/cycle', 'Running…'));
bind('btnWatch', () => traderAction('btnWatch', '/api/trader/watch', 'Checking…'));
bind('btnFlip', () => traderAction('btnFlip', '/api/trader/flip', 'Checking floors…'));
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
});
document.querySelectorAll('thead th').forEach(th => th.addEventListener('click', () => {
  const k = th.dataset.k;
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

document.getElementById('refresh').addEventListener('click', async e => {
  const b = e.target; b.disabled = true; b.textContent = 'Refreshing…';
  try {
    const r = await fetch('/api/refresh', { method: 'POST' }).then(r => r.json());
    if (!r.ok) { if (window.sfx) sfx.play('warn'); alert('Refresh failed: ' + (r.stderr || r.error || 'unknown')); }
    else if (window.sfx) sfx.play('done');
    await load();
  } finally { b.disabled = false; b.textContent = 'Refresh'; }
});

load();

/* auto-refresh: 30s until /api/config lands, then auto_refresh_seconds (clamped >= 15s) */
syncAutoRefresh(null);
