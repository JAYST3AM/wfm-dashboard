/* WFM Trader — settings page: human-readable groups over the two config schemas.
   Visible groups: Trading / Appearance / Updates. The collapsed Advanced settings section keeps the
   implementation surface: host, port and one row per raw key from both schemas.
   Routes are unchanged from the previous page: GET/POST /api/trader/cfg|settings and GET/POST
   /api/config, both writing {pairs: {raw_key: value}} and only sending changed keys. */
'use strict';

/* ---------- honesty map (checked against the code, not just the schema text) ---------- */
const NOT_READ = 'not read by the app yet';
/* keys with no reader anywhere in the app: a saved value changes nothing */
const DEAD_KEYS = { theme: 1, currency_display: 1, gifs: 1, max_active_listings: 1 };
const READ_BY = {
  buy_budget_cap_platinum: 'flip planner',
};

/* ---------- auto sync picker (Jay: 5m / 10m / 15m / 30m / 1hr) ----------
   Six presets over auto_refresh_seconds, saved through the same group Save as every other knob.
   0 is 'Manual only'; a stored value that is not a preset is shown raw as Custom, never rounded
   and never preselected. */
const AUTO_SYNC_OPTIONS = [
  { seconds: 0, label: 'Manual only' },
  { seconds: 300, label: 'Every 5 minutes' },
  { seconds: 600, label: 'Every 10 minutes' },
  { seconds: 900, label: 'Every 15 minutes' },
  { seconds: 1800, label: 'Every 30 minutes' },
  { seconds: 3600, label: 'Every hour' },
];
/* the row's value text: a preset's label, or the raw seconds kept honest (no rounding) */
function pickText(raw) {
  const sec = Number(raw);
  const preset = AUTO_SYNC_OPTIONS.find(o => o.seconds === sec);
  if (preset) return preset.label;
  return 'Custom \u00b7 ' + (Number.isFinite(sec) ? sec + 's' : String(raw));
}

/* ---------- groups: display copy only; the raw key is what gets posted ----------
   `icon` is a Phosphor sprite name (data-icon): it marks what the row or section means, and
   rides on the label host, so the label text, the field name and the save payload are untouched.
   Copy diet (Jay, 2026-09-27): labels and values only. A hint survives only where it adds a
   fact the label does not have, and never as a sentence. */
const GROUPS = [
  {
    id: 'verbose', title: 'Advanced', src: 'dash',
    rows: [
      { key: 'advanced', label: 'Advanced', apply: 1, icon: 'sliders-horizontal' },
    ],
  },
  {
    id: 'trading', title: 'Trading', src: 'trader',
    rows: [
      { key: 'dry_run', label: 'Posting mode', status: 1, icon: 'lock' },
      { key: 'max_new_listings_per_day', label: 'Maximum listings per day', unit: 'listings/day', icon: 'calendar-blank',
        hint: 'max 20' },
      { key: 'max_active_listings', label: 'Maximum active sell orders', unit: 'orders', badge: NOT_READ, icon: 'list' },
      { key: 'undercut_platinum', label: 'Undercut the lowest listing by', unit: 'platinum', icon: 'arrow-down' },
      { key: 'min_price_pct_of_median', label: 'Minimum price vs 48h median', unit: '%', icon: 'percent' },
      { key: 'min_price_platinum', label: 'Minimum sale price', unit: 'platinum', icon: 'tag' },
      { key: 'buy_budget_cap_platinum', label: 'Maximum platinum spent buying', unit: 'platinum', icon: 'shopping-cart',
        hint: '0 turns buying off' },
      { key: 'poll_seconds', label: 'Check prices every', unit: 'seconds', icon: 'clock' },
    ],
  },
  {
    id: 'appearance', title: 'Appearance', src: 'dash',
    rows: [
      { note: 'remembered per browser', icon: 'palette' },
      { key: 'currency_display', label: 'Platinum suffix', badge: NOT_READ, icon: 'currency-circle-dollar',
        choices: { p: '100p', plat: '100 plat', none: '100' } },
      { key: 'gifs', label: 'Celebration animations', badge: NOT_READ, icon: 'sparkle' },
      { key: 'deals_shown', label: 'Deal rows shown', unit: 'rows', icon: 'rows' },
      { key: 'sessions_shown', label: 'Sessions listed', unit: 'rows', icon: 'table' },
    ],
  },
  {
    id: 'updates', title: 'Updates', src: 'dash',
    rows: [
      { key: 'auto_refresh_seconds', label: 'Auto sync', pick: AUTO_SYNC_OPTIONS, icon: 'arrows-clockwise' },
      { key: 'watch_save_seconds', label: 'Check for a new game save every', unit: 'seconds', icon: 'floppy-disk',
        hint: 'lower is fresher' },
      { key: 'gamenews_cache_seconds', label: 'Refresh game news every', unit: 'minutes', factor: 60, icon: 'newspaper' },
    ],
  },
];

/* advanced: host + port only (both are read once at server startup) */
const ADV_GROUP = {
  id: 'advanced', title: 'Advanced settings', src: 'dash',
  rows: [
    { key: 'host', label: 'Bind address', restart: 1, icon: 'desktop',
      hint: 'WFM_HOST overrides it',
      choices: { '127.0.0.1': 'This PC only (127.0.0.1)', '0.0.0.0': 'Also on the LAN (0.0.0.0)' } },
    { key: 'port', label: 'Dashboard port', restart: 1, icon: 'plug',
      hint: 'WFM_PORT overrides it' },
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
const shownValue = ctl => ctl.dataset.pick ? pickText(ctl.querySelector('input').value)
  : ctl.type === 'checkbox' ? (ctl.checked ? 'on' : 'off') : ctl.value;
const fmtValue = v => typeof v === 'boolean' ? (v ? 'true' : 'false') : String(v);
/* a textContent write drops an already-rendered icon child: ask icons.js to put it back, once the
   sprite has landed (an earlier render would only mark the host as done and never draw it) */
function reIcon(node) {
  if (!node || !window.wfmIcons || !window.wfmIcons.render) return;
  node.removeAttribute('data-icon-done');
  if (window.wfmIcons.ready) window.wfmIcons.ready().then(() => {
    window.wfmIcons.render(node.parentNode || document);
  });
}
function setStatus(node, msg, bad) {
  if (!node) return;
  node.textContent = msg;
  node.classList.toggle('err', !!bad);
}

/* ---------- controls ---------- */
/* the auto sync picker: six pills over a hidden seconds input, so the row keeps its id and
   data-k plumbing and saveGroup's number branch posts the picked value unchanged */
function buildPickControl(meta, val, id, src) {
  const sec = Number(val);
  const wrap = el('span', 'st-segwrap');
  wrap.dataset.pick = '1';
  const store = el('input');
  store.type = 'hidden';
  store.id = id;
  store.dataset.k = meta.key;
  store.dataset.src = src;
  store.value = String(val);
  const box = el('span', 'st-seg');
  box.setAttribute('role', 'group');
  box.setAttribute('aria-label', meta.label || meta.key);
  meta.pick.forEach(o => {
    const b = el('button', null, o.label);
    b.type = 'button';
    b.dataset.sec = String(o.seconds);
    b.setAttribute('aria-pressed', String(o.seconds === sec));   /* a Custom value presses none */
    b.addEventListener('click', () => {
      store.value = String(o.seconds);
      box.querySelectorAll('button').forEach(x => x.setAttribute('aria-pressed', String(x === b)));
      store.dispatchEvent(new Event('change', { bubbles: true }));  /* the value cell follows */
    });
    box.appendChild(b);
  });
  wrap.appendChild(store);
  wrap.appendChild(box);
  return wrap;
}

function buildControl(meta, sch, src, id) {
  const f = meta.factor || 1;
  const cur = valuesOf(src)[meta.key];
  const val = cur !== undefined ? cur : sch.default;
  let ctl;
  if (meta.pick) {
    return buildPickControl(meta, val, id, src);
  } else if (sch.type === 'bool') {
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
    if (sch.max) ctl.maxLength = sch.max;
    ctl.value = String(val);
  }
  ctl.id = id;
  ctl.dataset.k = meta.key;
  ctl.dataset.src = src;
  if (f !== 1) ctl.dataset.factor = String(f);
  return ctl;
}

/* one labelled control row: name | control | value (+ unit), with the note under it.
   `i-host` keeps a long label free to wrap (icons.css only pins nowrap on plain hosts).
   A pick row (`pick-row`) puts label + value on line one and the pills across the card width. */
function fieldRow(meta, src) {
  const sch = schemaRow(src, meta.key);
  const wrap = el('div', 'cfgrow' + (meta.pick ? ' pick-row' : ''));
  const id = 'set-' + meta.key;
  const label = el('label', 'm-name i-host', meta.label || (sch && sch.help) || meta.key);
  if (meta.icon) label.setAttribute('data-icon', meta.icon);
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

  const help = el('div', 'cfg-help' + (meta.hint ? ' explain' : ''));
  if (meta.hint) help.appendChild(el('span', null, meta.hint + ' '));
  if (meta.badge) help.appendChild(el('span', 'st-badge', meta.badge));
  if (meta.restart) help.appendChild(el('b', 'st-restart', 'restart required'));
  if (help.childNodes.length) wrap.appendChild(help);

  if (ctl) {
    const show = () => { live.textContent = shownValue(ctl); };
    ctl.addEventListener('input', show);
    ctl.addEventListener('change', show);
    /* the Advanced switch takes effect immediately - the Save button only persists it */
    if (meta.apply && ctl.type === 'checkbox') {
      ctl.addEventListener('change', () => { if (window.wfmAdv) window.wfmAdv.set(ctl.checked); });
    }
  }
  return wrap;
}

/* posting mode is a status line, never an editable control (the engine owns dry_run) */
function statusRow(meta, src) {
  const sch = schemaRow(src, meta.key);
  const cur = valuesOf(src)[meta.key];
  const dry = cur !== undefined ? !!cur : !!(sch && sch.default);
  const wrap = el('div', 'cfgrow');
  const name = el('span', 'm-name', meta.label || meta.key);
  if (meta.icon) name.setAttribute('data-icon', meta.icon);
  wrap.appendChild(name);
  const cell = el('span');
  cell.appendChild(el('span', 'st-pill ' + (dry ? 'dry' : 'live'), dry ? 'Not live' : 'Live'));
  wrap.appendChild(cell);
  return wrap;
}

/* the theme row: label + one value, nothing else */
function noteRow(text, icon) {
  const wrap = el('div', 'cfgrow');
  const name = el('span', 'm-name', 'Theme');
  if (icon) name.setAttribute('data-icon', icon);
  wrap.appendChild(name);
  wrap.appendChild(el('span'));                       // no control on this row
  wrap.appendChild(el('span', 'cfg-val dim', text));
  return wrap;
}

/* ---------- render ---------- */
function renderGroup(g) {
  const box = document.getElementById('list-' + g.id);
  if (!box) return;
  box.textContent = '';
  if (!schemaOf(g.src).length) {
    box.appendChild(el('div', 'pad dim', 'Engine settings unavailable'));
    return;
  }
  g.rows.forEach(meta => {
    if (meta.note) box.appendChild(noteRow(meta.note, meta.icon));
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
      rows.push({ key: k, value: vals[k], file: file, by: 'unknown key' });
    });
  });
  rows.forEach(r => {
    const tr = document.createElement('tr');
    tr.appendChild(el('td', 'k', r.key));
    tr.appendChild(el('td', 'v', fmtValue(r.value)));
    tr.appendChild(el('td', 'f', r.file));
    const by = el('td', 'by');
    if (DEAD_KEYS[r.key]) by.appendChild(el('span', 'dead', NOT_READ));
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
  } finally { if (btn) { btn.disabled = false; btn.textContent = label; reIcon(btn); } }
}

/* ---------- accounts: one data profile per Warframe account (scripts/profiles.py) ---------- */
let ACCT = null;
let acctApply = null;

function fmtBytes(n) {
  const u = ['B', 'KB', 'MB', 'GB'];
  let v = +n || 0, i = 0;
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
  return (i ? v.toFixed(1) : v) + ' ' + u[i];
}

function acctNote(text) { return el('div', 'st-acctnote', text); }

function renderAccounts() {
  const box = document.getElementById('list-accounts');
  if (!box) return;
  box.textContent = '';
  const status = document.getElementById('status-accounts');
  if (!ACCT || ACCT.ok === false) {
    box.appendChild(acctNote('Profiles unavailable' + (ACCT && ACCT.error ? ': ' + ACCT.error : '.')));
    return;
  }
  const live = el('div', 'st-acctrow first');
  live.appendChild(el('span', 'st-aname', ACCT.current || 'unmanaged (live data)'));
  live.appendChild(el('span', 'st-badge', ACCT.managed ? 'current profile' : 'no profile yet'));
  let liveMeta = ACCT.live || '';
  if (ACCT.managed && ACCT.switched) liveMeta += ' · switched ' + new Date(ACCT.switched * 1000).toLocaleString();
  live.appendChild(el('span', 'st-ameta', liveMeta));
  box.appendChild(live);

  // the account AlecaFrame is linked to: profiles are named after it automatically
  const list = ACCT.profiles || [];
  const det = ACCT.detected || {};
  const detProf = list.find(p => p.name === det.name);
  const input = document.getElementById('acctName');
  if (input) input.placeholder = det.name ? ('auto: ' + det.name) : 'new profile name';
  if (det.name) {
    const state = ACCT.current === det.name ? 'current' : (detProf ? 'profile exists' : 'no profile yet');
    box.appendChild(acctNote('Detected ' + det.name + ' \u00b7 ' + (det.source || 'AlecaFrame') + ' \u00b7 ' + state));
  } else {
    box.appendChild(acctNote('No account detected (' + (det.reason || 'AlecaFrame not found') + ')'));
  }

  if (!list.length) {
    box.appendChild(acctNote('No profiles yet'));
    return;
  }
  list.forEach(p => {
    const row = el('div', 'st-acctrow');
    row.appendChild(el('span', 'st-aname', p.name));
    if (p.current) row.appendChild(el('span', 'st-badge', 'current'));
    const bits = [p.files + ' file' + (p.files === 1 ? '' : 's'), fmtBytes(p.bytes)];
    if (p.created) bits.push('created ' + new Date(p.created * 1000).toLocaleDateString());
    row.appendChild(el('span', 'st-ameta', bits.join(' · ')));
    const g = el('div', 'st-agrow');
    const b = el('button', 'btn', p.current ? 'In use' : 'Switch to this');
    b.type = 'button';
    if (p.current) b.disabled = true;
    else b.addEventListener('click', () => switchProfile(p.name, false));
    g.appendChild(b);
    row.appendChild(g);
    box.appendChild(row);
  });
}

function renderPlanActions(name) {
  const pre = document.getElementById('acctPlan');
  if (acctApply) { acctApply.remove(); acctApply = null; }
  if (!name || !pre || !pre.parentNode) return;
  acctApply = el('div', 'st-acctrow');
  acctApply.appendChild(el('span', 'st-ameta', 'safety zip first, nothing deleted'));
  const g = el('div', 'st-agrow');
  const b = el('button', 'btn', 'Apply switch to ' + name);
  b.type = 'button';
  b.addEventListener('click', () => switchProfile(name, true));
  g.appendChild(b);
  acctApply.appendChild(g);
  pre.parentNode.insertBefore(acctApply, pre.nextSibling);
}

async function switchProfile(name, apply) {
  const status = document.getElementById('status-accounts');
  const plan = document.getElementById('acctPlan');
  setStatus(status, apply ? 'Switching to ' + name + '…' : 'Building the switch plan for ' + name + '…');
  try {
    const res = await fetch('/api/profiles', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'switch', name: name, apply: !!apply }),
    }).then(r => r.json());
    const out = ((res.stdout || '') + (res.stderr ? '\n' + res.stderr : '')).trim();
    if (plan) { plan.hidden = !out; plan.textContent = out; }
    if (res.ok) {
      if (apply) {
        setStatus(status, 'Switched to “' + name + '” · restart the server');
        renderPlanActions(null);
      } else {
        setStatus(status, 'Plan only · nothing changed');
        renderPlanActions(name);
      }
    } else {
      setStatus(status, 'Refused: see the output above.', true);
      renderPlanActions(null);
    }
    if (res.profiles) { ACCT = res.profiles; renderAccounts(); }
  } catch (e) { setStatus(status, 'Request failed: ' + e, true); }
}

async function createProfile() {
  const input = document.getElementById('acctName');
  const status = document.getElementById('status-accounts');
  const btn = document.getElementById('acctCreate');
  const name = ((input && input.value) || '').trim();
  const det = (ACCT && ACCT.detected) || {};
  if (!name && !det.name) {
    setStatus(status, 'Type a profile name first', true);
    return;
  }
  if (btn) { btn.disabled = true; btn.textContent = 'Creating…'; }
  try {
    const res = await fetch('/api/profiles', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'create', name: name }),
    }).then(r => r.json());
    const made = (((res.stdout || '') + (res.stderr || '')).match(/profile '([^']+)' created/) || [])[1];
    if (res.ok) {
      setStatus(status, 'Profile “' + (made || name || det.name || 'account') + '” created');
      if (input) input.value = '';
    } else {
      setStatus(status, 'Refused: ' + (((res.stdout || '') + (res.stderr || '')).trim() || res.error || 'unknown'), true);
    }
    if (res.profiles) { ACCT = res.profiles; renderAccounts(); }
  } catch (e) { setStatus(status, 'Request failed: ' + e, true); }
  finally { if (btn) { btn.disabled = false; btn.textContent = 'Create profile'; } }
}

async function loadAccounts() {
  try { ACCT = await fetch('/api/profiles').then(r => r.json()); }
  catch (e) { ACCT = { ok: false, error: String(e) }; }
  renderAccounts();
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
  window.wfmThemeUI = true;      /* the panel is wired here: the shell leaves it alone */
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
loadAccounts();
const acctBtn = document.getElementById('acctCreate');
if (acctBtn) acctBtn.addEventListener('click', createProfile);
