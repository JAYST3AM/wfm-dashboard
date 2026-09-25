/* WFM Trader — settings page: human-readable groups over the two config schemas.
   Visible groups: Trading / Appearance / Updates. The collapsed Advanced settings section keeps the
   implementation surface: host, port and one row per raw key from both schemas.
   Routes are unchanged from the previous page: GET/POST /api/trader/cfg|settings and GET/POST
   /api/config, both writing {pairs: {raw_key: value}} and only sending changed keys. */
'use strict';

/* ---------- honesty map (checked against the code, not just the schema text) ---------- */
const NOT_READ = 'not read by the app yet';
const NOT_READ_LONG = 'Saved, but no part of the app reads it yet.';
/* keys with no reader anywhere in the app: a saved value changes nothing */
const DEAD_KEYS = { theme: 1, currency_display: 1, gifs: 1, max_active_listings: 1 };
/* the schema understates this one: the flip planner does read it as a fallback budget */
const READ_BY = {
  buy_budget_cap_platinum: 'flip planner — fallback spend budget (the schema text understates this)',
};

/* ---------- groups: display copy only; the raw key is what gets posted ---------- */
const GROUPS = [
  {
    id: 'trading', title: 'Trading', src: 'trader',
    rows: [
      { key: 'dry_run', label: 'Posting mode', status: 1 },
      { key: 'max_new_listings_per_day', label: 'Maximum listings per day', unit: 'listings/day',
        hint: 'The engine caps this at 20 — the control can only lower it, never raise it.' },
      { key: 'max_active_listings', label: 'Maximum active sell orders', unit: 'orders', badge: NOT_READ,
        hint: 'Ceiling on live sell orders before the lister stops adding more.' },
      { key: 'undercut_platinum', label: 'Undercut the lowest listing by', unit: 'platinum',
        hint: 'Listings sit this far under the lane floor.' },
      { key: 'min_price_pct_of_median', label: 'Refuse prices under this share of the 48h median', unit: '%',
        hint: 'A lane priced below this share of the item median is skipped.' },
      { key: 'min_price_platinum', label: 'Minimum sale price', unit: 'platinum',
        hint: 'Never list or reprice below this.' },
      { key: 'buy_budget_cap_platinum', label: 'Maximum platinum spent buying', unit: 'platinum',
        hint: 'Per buy action. 0 turns buying off.' },
      { key: 'poll_seconds', label: 'Check prices every', unit: 'seconds',
        hint: 'How often the watcher and detector look for changes.' },
    ],
  },
  {
    id: 'appearance', title: 'Appearance', src: 'dash',
    rows: [
      { note: 'Theme — chosen with the ◐ Theme button in the header (top right). Your pick is remembered '
        + 'in this browser. A stored default is not applied by the app yet.' },
      { key: 'currency_display', label: 'Platinum suffix', badge: NOT_READ,
        hint: 'How platinum amounts are written across the dashboard.',
        choices: { p: '100p', plat: '100 plat', none: '100' } },
      { key: 'gifs', label: 'Celebration animations', badge: NOT_READ,
        hint: 'Animated extras in the dashboard UI.' },
      { key: 'deals_shown', label: 'Deal rows shown', unit: 'rows',
        hint: 'Most rows the Market deals list returns.' },
      { key: 'sessions_shown', label: 'Sessions listed', unit: 'rows',
        hint: 'Most rows the trade-sessions list returns.' },
    ],
  },
  {
    id: 'updates', title: 'Updates', src: 'dash',
    rows: [
      { key: 'auto_refresh_seconds', label: 'Auto-refresh the dashboard every', unit: 'seconds',
        hint: 'How often the open dashboard pulls fresh data.' },
      { key: 'watch_save_seconds', label: 'Check for a new game save every', unit: 'seconds',
        hint: 'Lower is fresher — the watch reads the game save on this cadence.' },
      { key: 'gamenews_cache_seconds', label: 'Refresh game news every', unit: 'minutes', factor: 60,
        hint: 'How long cached news may be reused before it is fetched again.' },
    ],
  },
];

/* advanced: host + port only (both are read once at server startup) */
const ADV_GROUP = {
  id: 'advanced', title: 'Advanced settings', src: 'dash',
  rows: [
    { key: 'host', label: 'Bind address', restart: 1,
      hint: 'Which interface the dashboard listens on. The WFM_HOST environment variable overrides it.',
      choices: { '127.0.0.1': 'This PC only (127.0.0.1)', '0.0.0.0': 'Also on the LAN (0.0.0.0)' } },
    { key: 'port', label: 'Dashboard port', restart: 1,
      hint: 'The TCP port the dashboard binds. The WFM_PORT environment variable overrides it.' },
  ],
};
const SAVE_GROUPS = GROUPS.concat([ADV_GROUP]);

/* ---------- payloads ---------- */
let TRADER_CFG = null, DASH_CFG = null;
const cfgOf = src => src === 'trader' ? (TRADER_CFG || {}) : (DASH_CFG || {});
const schemaOf = src => cfgOf(src).schema || [];
const valuesOf = src => src === 'trader' ? (cfgOf(src).settings || {}) : (cfgOf(src).values || {});
const schemaRow = (src, key) => schemaOf(src).find(r => r.key === key) || null;

/* ---------- small DOM helpers (textContent only: no data goes through innerHTML) ---------- */
function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
}
const shownValue = ctl => ctl.type === 'checkbox' ? (ctl.checked ? 'on' : 'off') : ctl.value;
const fmtValue = v => typeof v === 'boolean' ? (v ? 'true' : 'false') : String(v);
function setStatus(node, msg, bad) {
  if (!node) return;
  node.textContent = msg;
  node.classList.toggle('err', !!bad);
}

/* ---------- controls ---------- */
function buildControl(meta, sch, src, id) {
  const f = meta.factor || 1;
  const cur = valuesOf(src)[meta.key];
  const val = cur !== undefined ? cur : sch.default;
  let ctl;
  if (sch.type === 'bool') {
    ctl = el('input');
    ctl.type = 'checkbox';
    ctl.checked = !!val;
  } else if (sch.type === 'choice' && (sch.choices || []).length) {
    ctl = el('select');
    sch.choices.forEach(c => {
      const o = el('option', null, (meta.choices && meta.choices[c]) || c);
      o.value = c;
      if (c === val) o.selected = true;
      ctl.appendChild(o);
    });
  } else if (sch.type === 'min/max') {
    ctl = el('input');
    ctl.type = 'number';
    ctl.min = sch.min / f;
    ctl.max = sch.max / f;
    ctl.step = sch.step || 1;
    ctl.value = val / f;
  } else {
    ctl = el('input');
    ctl.type = 'text';
    ctl.value = String(val);
  }
  ctl.id = id;
  ctl.dataset.k = meta.key;
  ctl.dataset.src = src;
  if (f !== 1) ctl.dataset.factor = String(f);
  return ctl;
}

/* one labelled control row: name | control | value (+ unit), with the note under it */
function fieldRow(meta, src) {
  const sch = schemaRow(src, meta.key);
  const wrap = el('div', 'cfgrow');
  const id = 'set-' + meta.key;
  const label = el('label', 'm-name', meta.label || (sch && sch.help) || meta.key);
  label.htmlFor = id;
  wrap.appendChild(label);

  const cell = el('span');
  const ctl = sch ? buildControl(meta, sch, src, id) : null;
  if (ctl) cell.appendChild(ctl); else cell.appendChild(el('span', 'dim', 'unavailable'));
  wrap.appendChild(cell);

  const valCell = el('span', 'cfg-val');
  const live = el('span', null, ctl ? shownValue(ctl) : '');
  valCell.appendChild(live);
  if (meta.unit) valCell.appendChild(el('span', 'st-unit', ' ' + meta.unit));
  wrap.appendChild(valCell);

  const help = el('div', 'cfg-help');
  if (meta.hint) help.appendChild(el('span', null, meta.hint + ' '));
  if (meta.badge) help.appendChild(el('span', 'st-badge', meta.badge));
  if (meta.restart) help.appendChild(el('b', 'st-restart', 'restart required'));
  wrap.appendChild(help);

  if (ctl) {
    const show = () => { live.textContent = shownValue(ctl); };
    ctl.addEventListener('input', show);
    ctl.addEventListener('change', show);
  }
  return wrap;
}

/* posting mode is a status line, never an editable control (the engine owns dry_run) */
function statusRow(meta, src) {
  const sch = schemaRow(src, meta.key);
  const cur = valuesOf(src)[meta.key];
  const dry = cur !== undefined ? !!cur : !!(sch && sch.default);
  const wrap = el('div', 'cfgrow');
  wrap.appendChild(el('span', 'm-name', meta.label || meta.key));
  const cell = el('span');
  cell.appendChild(el('span', 'st-pill ' + (dry ? 'dry' : 'live'), dry ? 'Dry run' : 'Live'));
  wrap.appendChild(cell);
  wrap.appendChild(el('span', 'cfg-val', dry ? 'dry run' : 'live'));
  wrap.appendChild(el('div', 'cfg-help', dry
    ? 'Posting mode: Dry run — nothing is posted to warframe.market until this is turned off in the engine config.'
    : 'Posting mode: Live — the trader may post to warframe.market. Set in the engine config; it cannot be changed from this page.'));
  return wrap;
}

function noteRow(text) {
  const wrap = el('div', 'cfgrow');
  wrap.appendChild(el('span', 'm-name', 'Theme'));
  wrap.appendChild(el('span', 'dim', '◐ Theme button in the header'));
  wrap.appendChild(el('div', 'cfg-help', text));
  return wrap;
}

/* ---------- render ---------- */
function renderGroup(g) {
  const box = document.getElementById('list-' + g.id);
  if (!box) return;
  box.textContent = '';
  if (!schemaOf(g.src).length) {
    box.appendChild(el('div', 'pad dim', 'These settings could not be read from the engine.'));
    return;
  }
  g.rows.forEach(meta => {
    if (meta.note) box.appendChild(noteRow(meta.note));
    else if (meta.status) box.appendChild(statusRow(meta, g.src));
    else box.appendChild(fieldRow(meta, g.src));
  });
}

/* raw-key table: every schema row of both files, plus any key the schema does not describe */
function renderRaw() {
  const tbody = document.getElementById('rawRows');
  if (!tbody) return;
  tbody.textContent = '';
  const rows = [];
  [['trader', 'scripts/trader/settings.json'], ['dash', 'data/config.json']].forEach(([src, file]) => {
    const sch = schemaOf(src), vals = valuesOf(src);
    if (!sch.length) return;
    sch.forEach(r => rows.push({ key: r.key, value: r.key in vals ? vals[r.key] : r.default, file: file, by: READ_BY[r.key] || r.consumed_by || '' }));
    Object.keys(vals).filter(k => !sch.some(r => r.key === k)).forEach(k => {
      rows.push({ key: k, value: vals[k], file: file, by: 'unknown key — kept by the engine, not described by the schema' });
    });
  });
  rows.forEach(r => {
    const tr = document.createElement('tr');
    tr.appendChild(el('td', 'k', r.key));
    tr.appendChild(el('td', 'v', fmtValue(r.value)));
    tr.appendChild(el('td', 'f', r.file));
    const by = el('td', 'by');
    if (DEAD_KEYS[r.key]) by.appendChild(el('span', 'dead', NOT_READ_LONG));
    else by.textContent = r.by;
    tr.appendChild(by);
    tbody.appendChild(tr);
  });
  const errBox = document.getElementById('advErr');
  if (errBox) {
    const errs = [];
    [['GET /api/trader/cfg', TRADER_CFG], ['GET /api/config', DASH_CFG]].forEach(([name, C]) => {
      if (!C) errs.push(name + ' — no answer');
      else if (C.error) errs.push(name + ' — ' + String(C.error));
    });
    errBox.textContent = errs.length ? 'Payload problems: ' + errs.join(' · ') : '';
  }
}

function render() {
  GROUPS.forEach(renderGroup);
  renderGroup(ADV_GROUP);
  renderRaw();
}

/* ---------- save (same routes, same {pairs} body, same diff-then-post as before) ---------- */
async function saveGroup(g) {
  const box = document.getElementById('list-' + g.id);
  const btn = document.getElementById('btnSave-' + g.id);
  const status = document.getElementById('status-' + g.id);
  const cur = valuesOf(g.src);
  const pairs = {};
  if (box) box.querySelectorAll('[data-k]').forEach(node => {
    const key = node.dataset.k, f = +node.dataset.factor || 1;
    if (node.type === 'checkbox') { if (node.checked !== cur[key]) pairs[key] = node.checked; return; }
    if (node.tagName === 'SELECT' || node.type === 'text') { if (node.value !== cur[key]) pairs[key] = node.value; return; }
    const num = +node.value * f;               /* number input: post only a finite change */
    if (node.value !== '' && Number.isFinite(num) && num !== cur[key]) pairs[key] = num;
  });
  const label = btn ? btn.textContent : '';
  if (btn) { btn.disabled = true; btn.textContent = 'Saving…'; }
  try {
    const n = Object.keys(pairs).length;
    if (n) {
      const url = g.src === 'trader' ? '/api/trader/settings' : '/api/config';
      const res = await fetch(url, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pairs }),
      }).then(r => r.json());
      if (!res.ok) {
        alert('Save refused: ' + (res.error || 'unknown'));
        setStatus(status, 'Save refused: ' + (res.error || 'unknown'), true);
      } else {
        setStatus(status, 'Saved — ' + n + ' value' + (n === 1 ? '' : 's') + ' updated.');
      }
    } else {
      setStatus(status, 'No changes to save.');
    }
    await loadAll();
  } finally { if (btn) { btn.disabled = false; btn.textContent = label; } }
}

/* ---------- header theme picker (port of app.js: toggle + outside-click + Escape close) ---------- */
function initThemePanel() {
  const btn = document.getElementById('themeBtn'), panel = document.getElementById('themePanel');
  if (!btn || !panel) return;
  if (typeof window.wfmBuildThemeGrid === 'function') window.wfmBuildThemeGrid();
  if (typeof window.wfmApplyTheme === 'function') {
    let saved = 0;
    try { saved = parseInt(localStorage.getItem('wfm.theme') || '0', 10); } catch (e) { saved = 0; }
    window.wfmApplyTheme(isNaN(saved) ? 0 : saved);   /* also marks the active swatch */
  }
  const setOpen = open => {
    panel.classList.toggle('hidden', !open);
    btn.setAttribute('aria-expanded', open ? 'true' : 'false');
  };
  btn.addEventListener('click', e => { e.stopPropagation(); setOpen(panel.classList.contains('hidden')); });
  document.addEventListener('click', e => {
    if (!panel.classList.contains('hidden') && !panel.contains(e.target) && e.target !== btn) setOpen(false);
  });
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && !panel.classList.contains('hidden')) { setOpen(false); btn.focus(); }
  });
}

/* ---------- advanced accordion (collapsed by default; a developer who opens it stays open) ---------- */
function initAccordion() {
  const btn = document.getElementById('advBtn'), panel = document.getElementById('advPanel');
  if (!btn || !panel) return;
  const caret = btn.querySelector('.st-caret');
  const setOpen = open => {
    panel.hidden = !open;
    btn.setAttribute('aria-expanded', open ? 'true' : 'false');
    if (caret) caret.textContent = open ? '\u25be' : '\u25b8';
    try { localStorage.setItem('wfm.settings.advanced', open ? '1' : '0'); } catch (e) { /* private mode */ }
  };
  let saved = null;
  try { saved = localStorage.getItem('wfm.settings.advanced'); } catch (e) { saved = null; }
  setOpen(saved === '1');
  btn.addEventListener('click', () => setOpen(btn.getAttribute('aria-expanded') !== 'true'));
}

/* ---------- wiring ---------- */
async function loadAll() {
  try { TRADER_CFG = await fetch('/api/trader/cfg').then(r => r.json()); } catch (e) { TRADER_CFG = null; }
  try { DASH_CFG = await fetch('/api/config').then(r => r.json()); } catch (e) { DASH_CFG = null; }
  render();
}

initThemePanel();
initAccordion();
SAVE_GROUPS.forEach(g => {
  const btn = document.getElementById('btnSave-' + g.id);
  if (btn) btn.addEventListener('click', () => saveGroup(g));
});
loadAll();
