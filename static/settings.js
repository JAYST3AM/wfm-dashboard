/* WFM Trader — settings page: trader guardrail sliders (#39/#40) + dashboard config knobs (#45).
   Both cards were moved here out of static/index.html + static/app.js; the dashboard SPA keeps
   only the auto_refresh_seconds poll wiring. Talks to GET/POST /api/trader/cfg|settings and
   GET/POST /api/config. */
'use strict';

const escHtml = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

/* ---------- trader guardrail settings (#39/#40) ---------- */
let TRADER_CFG = null;
async function loadTraderCfg() {
  try { TRADER_CFG = await fetch('/api/trader/cfg').then(r2 => r2.json()); } catch (e) { TRADER_CFG = null; }
  renderSettings();
}
function renderSettings() {
  const el = document.getElementById('cfgList');
  if (!el) return;
  const C = TRADER_CFG || {}, s = C.settings || {}, sch = C.schema || [];
  document.getElementById('cfgMeta').textContent = (s.dry_run !== undefined)
    ? `· guardrails active${C.error ? ' · schema error' : ''}` : '';
  if (!sch.length) { el.innerHTML = '<div class="dim pad">settings.py unavailable</div>'; return; }
  el.innerHTML = sch.map(row => {
    const val = s[row.key] ?? row.default;
    if (row.type === 'bool') {
      return `<div class="cfgrow ${row.locked ? 'locked' : ''}">
        <span class="m-name">${escHtml(row.help || row.key)} ${row.locked ? '<span class="chip wl-WAIT">LOCKED</span>' : ''}</span>
        <span><input type="checkbox" data-k="${row.key}" ${val ? 'checked' : ''} ${row.locked ? 'disabled' : ''}></span>
        <span class="cfg-val">${val ? 'on' : 'off'}</span>
        <div class="cfg-help">${escHtml(row.consumed_by || '')}</div>
      </div>`;
    }
    return `<div class="cfgrow">
      <span class="m-name" title="${escHtml(row.key)}">${escHtml(row.help || row.key)}</span>
      <span><input type="range" min="${row.min}" max="${row.max}" step="${row.step || 1}" value="${val}" data-k="${row.key}"></span>
      <span class="cfg-val" data-kv="${row.key}">${val}</span>
      <div class="cfg-help">${escHtml(row.key)} · ${escHtml(row.consumed_by || '')}</div>
    </div>`;
  }).join('');
  el.querySelectorAll('input[type=range]').forEach(r2 => r2.addEventListener('input', () => {
    const v = el.querySelector(`[data-kv="${r2.dataset.k}"]`); if (v) v.textContent = r2.value;
  }));
}
async function saveCfg() {
  const el = document.getElementById('cfgList');
  const s = (TRADER_CFG || {}).settings || {};
  const pairs = {};
  el.querySelectorAll('input[type=range]').forEach(r2 => { const v = +r2.value; if (s[r2.dataset.k] !== v) pairs[r2.dataset.k] = v; });
  el.querySelectorAll('input[type=checkbox]:not(:disabled)').forEach(c => { const v = c.checked; if (s[c.dataset.k] !== v) pairs[c.dataset.k] = v; });
  const b = document.getElementById('btnCfgSave');
  b.disabled = true; b.textContent = 'Saving…';
  try {
    if (Object.keys(pairs).length) {
      const res = await fetch('/api/trader/settings', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pairs }),
      }).then(r2 => r2.json());
      if (!res.ok) alert('Save refused: ' + (res.error || 'unknown'));
    }
    await loadTraderCfg();
  } finally { b.disabled = false; b.textContent = 'Save'; }
}

/* ---------- dashboard config (#45): scripts/config.py → data/config.json ---------- */
let DASH_CFG = null;
const DASH_RESTART_KEYS = { port: 1, host: 1 };   /* only read by server.py at startup */
async function loadDashboardCfg() {
  try { DASH_CFG = await fetch('/api/config').then(r2 => r2.json()); } catch (e) { DASH_CFG = null; }
  renderDashConfig();
}
function renderDashConfig() {
  const el = document.getElementById('configList');
  if (!el) return;
  const C = DASH_CFG || {}, v = C.values || {}, sch = C.schema || [];
  const meta = document.getElementById('configMeta');
  if (meta) meta.textContent = sch.length
    ? `· ${sch.length} knobs · data/config.json${C.error ? ' · schema error' : ''}`
    : (C.error ? '· config.py unavailable' : '');
  if (!sch.length) { el.innerHTML = '<div class="dim pad">scripts/config.py unavailable</div>'; return; }
  el.innerHTML = sch.map(row => {
    const val = (v[row.key] !== undefined) ? v[row.key] : row.default;
    const k = escHtml(row.key);
    let input;
    if (row.type === 'bool') {
      input = `<input type="checkbox" data-k="${k}" ${val ? 'checked' : ''}>`;
    } else if (row.type === 'choice' && (row.choices || []).length) {
      input = `<select data-k="${k}">` +
        row.choices.map(c => `<option value="${escHtml(c)}" ${c === val ? 'selected' : ''}>${escHtml(c)}</option>`).join('') +
        `</select>`;
    } else if (row.type === 'min/max') {
      input = `<input type="number" data-k="${k}" min="${row.min}" max="${row.max}" step="${row.step || 1}" value="${val}">`;
    } else {
      input = `<input type="text" data-k="${k}" value="${escHtml(val)}">`;
    }
    const shown = row.type === 'bool' ? (val ? 'on' : 'off') : escHtml(String(val));
    const restart = DASH_RESTART_KEYS[row.key]
      ? ' · <b class="cfg-restart">port/host changes need a server restart</b>' : '';
    return `<div class="cfgrow">
      <span class="m-name" title="${k}">${escHtml(row.help || row.key)}</span>
      <span>${input}</span>
      <span class="cfg-val" data-kv="${k}">${shown}</span>
      <div class="cfg-help">${k} · ${escHtml(row.consumed_by || '')}${restart}</div>
    </div>`;
  }).join('');
  el.querySelectorAll('[data-k]').forEach(node => {
    const live = el.querySelector(`[data-kv="${node.dataset.k}"]`);
    const show = () => { if (live) live.textContent = node.type === 'checkbox' ? (node.checked ? 'on' : 'off') : node.value; };
    node.addEventListener('input', show);
    node.addEventListener('change', show);
  });
}
async function saveDashCfg() {
  const el = document.getElementById('configList');
  const v = (DASH_CFG || {}).values || {};
  const pairs = {};
  el.querySelectorAll('[data-k]').forEach(node => {
    const key = node.dataset.k, cur = v[key];
    if (node.type === 'checkbox') { if (node.checked !== cur) pairs[key] = node.checked; return; }
    if (node.tagName === 'SELECT' || node.type === 'text') { if (node.value !== cur) pairs[key] = node.value; return; }
    const num = +node.value;                    /* number input: post only a finite change */
    if (node.value !== '' && Number.isFinite(num) && num !== cur) pairs[key] = num;
  });
  const b = document.getElementById('btnConfigSave');
  b.disabled = true; b.textContent = 'Saving…';
  try {
    if (Object.keys(pairs).length) {
      const res = await fetch('/api/config', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pairs }),
      }).then(r2 => r2.json());
      if (!res.ok) alert('Save refused: ' + (res.error || 'unknown'));
    }
    await loadDashboardCfg();
  } finally { b.disabled = false; b.textContent = 'Save'; }
}

/* ---------- wiring ---------- */
document.getElementById('btnCfgSave').addEventListener('click', saveCfg);
document.getElementById('btnConfigSave').addEventListener('click', saveDashCfg);
loadTraderCfg();
loadDashboardCfg();
