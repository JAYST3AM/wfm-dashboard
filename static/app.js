/* WFM Trader — dashboard frontend (vanilla JS) */
'use strict';

/* ---------- themes: [name, bg, panel, panel2, border, text, muted, accent, accentDim, hover] ---------- */
const THEMES = [
  ['Vor Orange',   '#0d0f13', '#14171d', '#191d25', '#232833', '#e8eaf0', '#8b93a4', '#ff8a1e', '#7a4713', '#181d26'],
  ['Corpus Cyan',  '#0b0f14', '#10161d', '#151c25', '#1e2933', '#e6f2f5', '#7f96a3', '#22d3ee', '#155e6b', '#131b24'],
  ['Kuva Crimson', '#120c0e', '#1a1114', '#21161a', '#2c1c22', '#f0e6e8', '#9c8189', '#ef4444', '#7f1d1d', '#1f1418'],
  ['Lotus Violet', '#0f0c16', '#16111f', '#1d1729', '#2a2138', '#ece8f5', '#9188a6', '#a855f7', '#5b2d8a', '#1a1426'],
  ['Orokin Gold',  '#12100a', '#1a170f', '#221d13', '#332b1a', '#f5efe0', '#a5987a', '#eab308', '#7a5c10', '#201b12'],
  ['Sentient Teal','#0a1211', '#101a19', '#152220', '#1f302d', '#e3f2ef', '#7fa39c', '#14b8a6', '#0f5f56', '#131f1d'],
  ['Infested',     '#0c110a', '#121810', '#182016', '#22301d', '#e9f2e4', '#8ba381', '#84cc16', '#4d7c0f', '#161d13'],
  ['Void Indigo',  '#0c0d1a', '#121428', '#181b33', '#232746', '#e7e9f7', '#878cb5', '#6366f1', '#3730a3', '#15172c'],
  ['Argon Crystal','#0a1016', '#0f1720', '#141d29', '#1e2a3a', '#dff0fa', '#7c95a8', '#38bdf8', '#0c4a6e', '#121b26'],
  ['Rubedo Red',   '#110a0c', '#180f12', '#1f1418', '#2e1c22', '#f2e6e9', '#a08088', '#f43f5e', '#881337', '#1d1317'],
  ['Luna Silver',  '#0e1013', '#15181d', '#1b1f26', '#262b34', '#eceef2', '#9098a5', '#cbd5e1', '#64748b', '#191d23'],
  ['Sakura',       '#150f14', '#1c141b', '#241a22', '#33242f', '#f5e9f0', '#a8859a', '#f472b6', '#9d174d', '#211821'],
  ['Emerald',      '#0a120d', '#0f1912', '#141f18', '#1d2e24', '#e3f2e8', '#7fa38c', '#10b981', '#065f46', '#121d16'],
  ['Solar Amber',  '#131008', '#1b170c', '#231e11', '#342c19', '#f5efdc', '#a39877', '#f59e0b', '#92400e', '#211c10'],
  ['Frost Light',  '#eef2f7', '#ffffff', '#f4f7fb', '#d7dee9', '#16202c', '#5b6b7f', '#0284c7', '#0369a1', '#e8eef6'],
  ['Blood Moon',   '#100a0e', '#170e14', '#1e131a', '#2e1c26', '#f2e6ee', '#a08093', '#dc2626', '#7f1d1d', '#1c1119'],
  ['Mint',         '#0b1310', '#101b17', '#15221d', '#1f322b', '#e4f4ee', '#7fa899', '#34d399', '#047857', '#131f1a'],
  ['Cyberpunk',    '#0d0a14', '#130f1e', '#191427', '#251e39', '#ece6f7', '#8f84ad', '#d946ef', '#86198f', '#170f24'],
  ['Matrix',       '#050d07', '#0a140c', '#0e1a10', '#15281a', '#d9f5df', '#6f9c7a', '#22c55e', '#166534', '#0c1810'],
  ['Sunset',       '#140e0c', '#1c1411', '#241a16', '#34261f', '#f5e9e2', '#a8836f', '#ff7a45', '#9a3412', '#211814'],
  ['Deep Ocean',   '#08111a', '#0d1824', '#121f2e', '#1b2d40', '#e0eefa', '#7a93a8', '#0ea5e9', '#075985', '#101d2a'],
  ['Lavender',     '#100f18', '#17161f', '#1e1c29', '#2b2838', '#ecebf5', '#8f8ba6', '#8b5cf6', '#5b21b6', '#1a1824'],
  ['Crimson Gold', '#130d0d', '#1b1313', '#221818', '#332424', '#f4e8e6', '#a38986', '#eab308', '#854d0e', '#201616'],
  ['Titanium',     '#0f1113', '#16191c', '#1c2024', '#282d33', '#e8ebee', '#8d959e', '#9ca3af', '#4b5563', '#1a1e22'],
  ['Neon Lime',    '#0b1106', '#111807', '#17210b', '#233212', '#e8f5d9', '#8fa873', '#a3e635', '#4d7c0f', '#151d0a'],
  ['Magma',        '#140b06', '#1c100a', '#24150d', '#352013', '#f7e8dc', '#a87f63', '#f97316', '#9a3412', '#21130c'],
  ['Aqua Marine',  '#071214', '#0c1a1d', '#112227', '#1a3339', '#def2f5', '#79a0a6', '#06b6d4', '#155e75', '#0f1e22'],
  ['Rose Gold',    '#13100c', '#1b1611', '#231d17', '#342a22', '#f5ece1', '#a89684', '#fda4af', '#9f1239', '#211a14'],
  ['Paper Light',  '#f6f6f3', '#ffffff', '#fbfbf9', '#dddcd4', '#1d1c18', '#6d6b60', '#b45309', '#92400e', '#f0efe9'],
  ['Nebula',       '#0b0a12', '#12101b', '#181525', '#241f38', '#eae7f5', '#8a83a8', '#c084fc', '#6b21a8', '#151223'],
];
const TVARS = ['bg', 'panel', 'panel2', 'border', 'text', 'muted', 'accent', 'accentDim', 'hover'];

function applyTheme(i) {
  const t = THEMES[i]; if (!t) return;
  const root = document.documentElement.style;
  TVARS.forEach((v, k) => {
    const id = (v === 'accentDim') ? 'accent-dim' : v;
    root.setProperty('--' + id, t[k + 1]);
  });
  localStorage.setItem('wfm.theme', String(i));
  document.querySelectorAll('.theme-item').forEach((el, k) => el.classList.toggle('active', k === i));
  document.getElementById('themeName').textContent = t[0];
  if (window.PlatChart) PlatChart.redraw();
}

function buildThemeGrid() {
  const grid = document.getElementById('themeGrid');
  grid.innerHTML = THEMES.map((t, i) => `
    <div class="theme-item" data-i="${i}" title="${t[0]}">
      <span class="dots"><i style="background:${t[1]}"></i><i style="background:${t[3]}"></i><i style="background:${t[7]}"></i></span>
      <span class="tname">${t[0]}</span>
    </div>`).join('');
  grid.querySelectorAll('.theme-item').forEach(el => el.addEventListener('click', () => applyTheme(+el.dataset.i)));
}

/* ---------- data ---------- */
let ITEMS = [], SUMMARY = null, PLAT = null, REPORT = null, TRADES = null;
let state = { tab: 'prime_part', sort: 'value', dir: -1, q: '' };

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
function showView(v) {
  document.getElementById('view-home').classList.toggle('hidden', v !== 'home');
  document.getElementById('view-inventory').classList.toggle('hidden', v !== 'inventory');
  document.getElementById('view-history').classList.toggle('hidden', v !== 'history');
  document.querySelectorAll('.navpill').forEach(el => el.classList.toggle('active', el.dataset.v === v));
  if (window.PlatChart) PlatChart.redraw();
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
    <div class="kpi"><div class="k-label">Inventory value</div><div class="k-val">${(s.total_value ?? 0).toLocaleString()}p</div></div>
    <div class="kpi"><div class="k-label">Credits</div><div class="k-val">${(s.credits ?? 0).toLocaleString()}</div></div>`;
}

function renderPicks() {
  const rs = (REPORT && REPORT.sell_now || []).slice(0, 8);
  const el = document.getElementById('sellPicks');
  const note = `<div class="picks-note dim"><b>Sorted by earnings × how fast they sell.</b> List at = cheapest listing minus 1p.</div>`;
  const head = `<div class="pick pick-head">
      <span class="c-rank">#</span><span class="c-name">Item</span>
      <span class="c-own">You own</span><span class="c-act">Sold · 48h</span>
      <span class="c-soldfor">Sold for</span>
      <span class="c-price">List at</span><span class="c-tot">If all sell</span>
    </div>`;
  const rows = rs.map((r, i) => {
    const rng = (r.mn48 !== null && r.mn48 !== undefined && r.mx48 !== null && r.mx48 !== undefined)
      ? ` · range ${r.mn48}–${r.mx48}p` : '';
    const soldFor = (r.med !== null && r.med !== undefined)
      ? `<span class="c-soldfor" title="typical price actually paid, last 48h${rng}">${Math.round(r.med)}p</span>`
      : `<span class="c-soldfor dim" title="no sales in the last 48h">—</span>`;
    return `
    <div class="pick">
      <span class="c-rank dim">${i + 1}</span>
      <span class="c-name" title="${r.name}">${r.name}</span>
      <span class="c-own">${r.count}</span>
      <span class="c-act dim">${r.vol48}</span>
      ${soldFor}
      <span class="c-price">${r.wts}p</span>
      <span class="c-tot">${r.value}p</span>
    </div>`;
  }).join('');
  el.innerHTML = rs.length ? note + head + rows : '<div class="dim" style="padding:10px 8px">No report yet — run scripts/report.py.</div>';
  document.getElementById('picksMeta').textContent = (REPORT && REPORT.generated) ? '· ' + REPORT.generated : '';
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
    x = (x === null || x === undefined) ? -Infinity : x;
    y = (y === null || y === undefined) ? -Infinity : y;
    return state.dir * (x - y);
  });
  return rs;
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
  tbody.innerHTML = slice.map(r => `
    <tr>
      <td class="name" title="${r.name}">${r.name}</td>
      <td class="hide-s"><span class="cat ${r.cat}">${CAT_LABEL[r.cat] || r.cat}</span></td>
      <td class="num">${fmt(r.count)}</td>
      <td class="num hide-s">${fmt(r.ducats)}</td>
      <td class="num">${fmt(r.wts)}</td>
      <td class="num hide-s">${fmt(r.wtb)}</td>
      <td class="num hide-s${(r.spread !== null && r.spread !== undefined && r.spread < 0) ? ' neg' : ''}">${fmt(r.spread)}</td>
      <td class="num">${r.vol48 === null || r.vol48 === undefined ? '<span class="dim">—</span>' : r.vol48.toFixed(1)}</td>
      <td class="num hide-s">${fmt(r.median)}</td>
      <td class="num v">${fmt(r.value)}</td>
    </tr>`).join('');
  if (!slice.length) tbody.innerHTML = '<tr><td colspan="10" class="dim" style="padding:18px">No items match.</td></tr>';
  const tot = rs.reduce((a, r) => a + (r.value || 0), 0);
  document.getElementById('totals').innerHTML =
    `<span>${rs.length} stacks <span class="dim">(showing ${slice.length})</span></span>
     <span>Filtered value <b class="big">${tot.toLocaleString()}p</b></span>`;
}

async function load() {
  const [s, i, ph, rep, tr] = await Promise.all([
    fetch('/api/summary').then(r => r.json()),
    fetch('/api/items').then(r => r.json()),
    fetch('/api/plat_history').then(r => r.json()),
    fetch('/api/report').then(r => r.json()).catch(() => null),
    fetch('/api/trades').then(r => r.json()).catch(() => null),
  ]);
  SUMMARY = s; ITEMS = i; PLAT = ph; REPORT = rep; TRADES = tr;
  renderChips(); renderTabs(); renderTable();
  renderKpis(); renderPicks(); renderChartMeta(); renderHistory();
  PlatChart.setData(ph.points || []);
  document.getElementById('status').textContent = s.lastdata_mtime
    ? `prices updated ${ago(s.prices_mtime)} · data ${new Date().toLocaleTimeString()}`
    : 'No data yet — run: python scripts/setup.py';
  document.getElementById('foot').textContent =
    `WFM Trader · local service on 127.0.0.1:8787 · refreshed ${new Date().toLocaleTimeString()} · ${(tr && tr.n) || 0} history events · snapshot collector every 15 min`;
}

/* ---------- init ---------- */
const savedTheme = localStorage.getItem('wfm.theme');
buildThemeGrid();
PlatChart.init();
applyTheme(savedTheme === null ? 0 : (+savedTheme || 0));
function viewFromHash() {
  const v = (location.hash || '#home').slice(1);
  return ['home', 'inventory', 'history'].includes(v) ? v : 'home';
}
showView(viewFromHash());
window.addEventListener('hashchange', () => showView(viewFromHash()));

document.querySelectorAll('#ranges button').forEach(b => b.addEventListener('click', () => {
  document.querySelectorAll('#ranges button').forEach(x => x.classList.toggle('active', x === b));
  PlatChart.setRange(b.dataset.r);
}));

document.querySelectorAll('#hFilters button').forEach(b => b.addEventListener('click', () => {
  document.querySelectorAll('#hFilters button').forEach(x => x.classList.toggle('active', x === b));
  hFilter = b.dataset.f; renderHistory();
}));

document.addEventListener('keydown', e => {
  if (e.key === '/' && !/input|textarea/i.test((e.target.tagName || ''))) {
    e.preventDefault();
    location.hash = '#inventory';
    document.getElementById('search').focus();
  }
});

document.getElementById('search').addEventListener('input', e => { state.q = e.target.value.trim(); renderTable(); });
document.querySelectorAll('thead th').forEach(th => th.addEventListener('click', () => {
  const k = th.dataset.k;
  if (state.sort === k) state.dir *= -1; else { state.sort = k; state.dir = (k === 'name' || k === 'cat') ? 1 : -1; }
  renderTable();
}));
const tBtn = document.getElementById('themeBtn');
const tPanel = document.getElementById('themePanel');
tBtn.addEventListener('click', e => { e.stopPropagation(); tPanel.classList.toggle('hidden'); });
document.addEventListener('click', e => {
  if (!tPanel.classList.contains('hidden') && !tPanel.contains(e.target) && e.target !== tBtn) tPanel.classList.add('hidden');
});
document.addEventListener('keydown', e => { if (e.key === 'Escape') tPanel.classList.add('hidden'); });

document.getElementById('refresh').addEventListener('click', async e => {
  const b = e.target; b.disabled = true; b.textContent = 'Refreshing…';
  try {
    const r = await fetch('/api/refresh', { method: 'POST' }).then(r => r.json());
    if (!r.ok) alert('Refresh failed: ' + (r.stderr || r.error || 'unknown'));
    await load();
  } finally { b.disabled = false; b.textContent = 'Refresh'; }
});

load();
setInterval(load, 30000);
