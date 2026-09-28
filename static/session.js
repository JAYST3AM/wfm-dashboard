/* WFM Trader - the Trading Session panel (#trade/session).
   docs/trading-session-workflow.md sections 1-8 and 12; design/_session/implementation-map.md.

   The session, its queue and its pending trades are SERVER state (data/trade_session.json, read
   through GET /api/session and handed to this page as FEAT.session): this file paints them and
   posts one action per click. Nothing here recomputes a price, a rank or a buyer - the queue
   carries what the plan and the run queue already produced, which is what section 2 forbids a
   second order book for. Refresh rides the existing load() cadence: the panel adds no timer of its
   own and never fetches its own endpoint, because the shared feature fan-out in load() read it.

   Loaded BEFORE app.js, like home.js/drawer.js: load() and the hash router both call
   renderSession() while app.js is still parsing, so the function has to exist by then. */
'use strict';

/* the six states the workflow names (section 3), in player words - the engine strings stay in the
   payload and never reach the screen */
const SESSION_STATE_WORD = { READY: 'ready', CONTACTED: 'whispered', 'POSSIBLE MATCH': 'check this one',
  COMPLETED: 'done', SKIPPED: 'skipped', HELD: 'held' };

/* the last whisper answer, consumed by the very next paint: a sent whisper triggers load(), which
   rebuilds the panel, so a confirmation the row just printed would be wiped by the refresh it
   caused */
let SESSION_SAY = '';

function sessionPayload() {
  const S = FEAT.session || {};
  return { live: !!S.session, focusIndex: S.focus_index, summary: S.summary || {},
    focus: S.focus || null, queue: S.queue || [], suggested: S.suggested || [],
    pending: S.pending || [], stale: S.stale_pending || [] };
}

function sessionStateWord(row) {
  const st = String((row || {}).state || 'READY').toUpperCase();
  return SESSION_STATE_WORD[st] || 'ready';
}

function sessionPlat(v) {
  const n = Number(v) || 0;
  return (n > 0 ? '+' : '') + n + 'p';
}

/* one span per fact, and a fact the payload does not carry prints NOTHING (spec section 7): no
   dash, no placeholder - the keys the payload really has are the whole vocabulary here */
function sessionWhyBits(why) {
  const w = why || {}, out = [];
  if (w.safe_copies) out.push('· ' + w.safe_copies + (w.safe_copies === 1 ? ' safe copy' : ' safe copies'));
  if (w.sales_48h !== undefined && w.sales_48h !== null) out.push('· ' + w.sales_48h + ' sales in 48h');
  if (w.buyers_online) out.push('· ' + w.buyers_online + (w.buyers_online === 1 ? ' buyer live' : ' buyers live'));
  if (w.median !== undefined && w.median !== null) out.push('· median ' + w.median + 'p');
  if (w.week_pct !== undefined && w.week_pct !== null) out.push('· price ' + (w.week_pct > 0 ? '+' : '') + w.week_pct + '% this week');
  if (w.liquidity) out.push('· liquidity ' + w.liquidity);
  if (w.buy_orders) out.push('· ' + w.buy_orders + (w.buy_orders === 1 ? ' buy order' : ' buy orders'));
  return out;
}

/* The Next-action footer control, rendered by app.js renderNextAction(). It stays at the quiet
   weight so the card keeps its one accent action (Open Trade): the card and its plan row belong to
   app.js, the loop state to this file. */
function sessionHomeAction() {
  const live = !!(FEAT.session || {}).session;
  return live
    ? '<a class="btn" href="#trade/session" title="Back to the trading session">Open session</a>'
    : '<button class="btn" id="homeStartTrading" type="button" data-icon="lightning" title="Build the queue and start trading">Start trading</button>';
}

function sessionEmpty(line) {
  return '<div class="empty">' + EMPTY_ICON + escHtml(line) + '</div>';
}

/* the rank of a row, when the payload carries one (a rank-0 mod is a real rank, so this tests for
   null/empty rather than truthiness) */
function sessionRankBit(row) {
  const r = (row || {}).rank;
  return (r === null || r === undefined || r === '') ? '' : ' <span class="dim">R' + escHtml(String(r)) + '</span>';
}

/* the queue, one compact row per item: the state, the item, what it goes for, and one way to point
   the session at it (the suggested list has no cursor, so it shows the confidence instead) */
function sessionQueueRows(rows, live) {
  if (!rows.length) return sessionEmpty(live ? 'Nothing queued yet.' : 'Nothing to sell yet.');
  return rows.map((r, i) => {
    const conf = (r.confidence || {}).level || 'low';
    return `
    <div class="sessrow">
      <span class="chip">${escHtml(sessionStateWord(r))}</span>
      <span class="l-name" title="${escHtml(r.slug || '')}">${escHtml(r.name || pretty(r.slug))}${sessionRankBit(r)}</span>
      <span class="num">${r.qty || 1}<span class="dim"> x ${escHtml(String(r.price))}p</span></span>
      ${live ? `<button class="sessfocus" data-index="${i}" title="Point the session at this item">Focus</button>`
             : `<span class="chip conf-${escHtml(conf)}" title="${escHtml(((r.confidence || {}).reasons || []).join(' · '))}">${escHtml(conf)}</span>`}
    </div>`;
  }).join('');
}

/* a buyer row is the order book's own whisper row: same classes, same button data, so the click
   path is ordWhisper and nothing else */
function sessionBuyerRow(f, b, say) {
  const st = String(b.status || 'offline');
  const rank = (f.rank === null || f.rank === undefined) ? '' : String(f.rank);
  const plat = (b.plat === null || b.plat === undefined) ? '' : String(b.plat);
  return `
    <div class="ordrow" data-kind="buy" data-st="${escHtml(st)}">
      <span class="orduser" title="the buyer who posted this order">${escHtml(b.user || '')}</span>
      <span class="ordp" title="what they pay each">${ordPrice(b.plat)}</span>
      <span class="ordst" title="${escHtml(b.why || 'from the run queue')}"><i class="orddot ${escHtml(st)}"></i>${escHtml(st)}</span>
      <button class="ordwsp" data-item="${escHtml(f.slug || '')}" data-user="${escHtml(b.user || '')}"
        data-price="${escHtml(plat)}" data-rank="${escHtml(rank)}" data-kind="buy"
        title="Send this whisper in game">Whisper</button>
      <span class="ordres" aria-live="polite">${escHtml(say || '')}</span>
    </div>`;
}

/* the focus card: the one item the loop is on, its facts, the buyer (or the honest gap), and the
   one action that moves it on */
function sessionFocusCard(f, say) {
  const b = f.buyer || null, why = f.why || {}, conf = f.confidence || {};
  const bits = sessionWhyBits(why);
  const confWord = conf.level || 'low';
  /* the same anatomy sbits() paints: one span per fact, so no visible string is a sentence */
  const whyHtml = bits.map(x => '<span>' + escHtml(x) + '</span>').join(' ');
  const facts = [sessionRankBit(f).trim(),
    '<span>' + (f.qty || 1) + ((f.qty || 1) === 1 ? ' copy' : ' copies') + '</span>',
    '<span>' + escHtml(String(f.price)) + 'p list</span>'].filter(Boolean);
  return `
    <div class="sess-head">
      <span class="l-name" title="${escHtml(f.slug || '')}">${escHtml(f.name || pretty(f.slug))}</span>
      <span class="sess-facts">${facts.join(' ')}</span>
      <span class="chip conf-${escHtml(confWord)}" title="${escHtml((conf.reasons || []).join(' · '))}">${escHtml(confWord)}</span>
      <span class="dim">${escHtml(sessionStateWord(f))}</span>
    </div>
    ${bits.length ? `<div class="sess-why" title="${escHtml((why.reasons || []).join(' · '))}">${whyHtml}</div>` : ''}
    ${b ? sessionBuyerRow(f, b, say)
        : `<div class="sess-nobuyer dim">${escHtml(why.rank_mismatch || 'No buyer in the run queue')}</div>`}`;
}

/* the pending trades: what a sent whisper is waiting on. The check that says what actually moved
   rides the same payload (proposals), so this list never resolves anything on its own - see the
   Checks card, which puts one confirm in front of the user and no automation behind it */
function sessionPendingRows(pend, stale) {
  const all = (pend || []).concat(stale || []);
  if (!all.length) return sessionEmpty('Nothing waiting on a confirmation.');
  const old = {};
  (stale || []).forEach(p => { old[p.id] = 1; });
  return all.map(p => `
    <div class="sessrow sesspend">
      <span class="dim num">${escHtml(ago(p.ts))}</span>
      <span class="l-name" title="${escHtml(p.slug || '')}">${escHtml(p.name || pretty(p.slug))}${sessionRankBit(p)}</span>
      <span class="dim">${escHtml(p.buyer || '—')}</span>
      <span class="num">${p.qty || 1}<span class="dim"> @ ${escHtml(String(p.expected_plat || ''))}p</span></span>
      <span>${old[p.id] ? '<span class="chip">old</span>' : ''}</span>
    </div>`).join('');
}

/* the checks: one row per pending trade, with what the save says moved against what was asked.
   'exact' is a confirmation waiting for a click; 'ambiguous' says why it is not certain and still
   leaves the click to the user; nothing and unknown never offer one (spec sections 4 and 7). */
const SESSION_DRAFTS = {};

function sessionCheckRows(props) {
  if (!props.length) return sessionEmpty('Nothing to check yet.');
  return props.map(p => {
    const act = (p.verdict === 'exact')
      ? '<button class="btn sessconf" data-pending="' + escHtml(p.pending_id) + '" title="Log this sale">Confirm</button>'
      : (p.verdict === 'ambiguous'
        ? '<button class="btn sessconf" data-pending="' + escHtml(p.pending_id) + '" title="Log it as your sale">Looks right</button>'
        : '');
    const word = p.verdict === 'exact' ? 'sold' : (p.verdict === 'ambiguous' ? 'check'
      : (p.verdict === 'unknown' ? 'no snapshot' : 'nothing moved'));
    const facts = (p.evidence || []).map(e => '<span class="chip">' + escHtml(e) + '</span>').join('');
    return `
    <div class="sessrow sesscheck">
      <span class="chip ${p.verdict === 'exact' ? 'ok' : ''}">${escHtml(word)}</span>
      <span class="l-name" title="${escHtml(p.slug || '')}">${escHtml(p.name || pretty(p.slug))}${sessionRankBit(p)}</span>
      <span class="dim">${escHtml(p.buyer || '—')}</span>
      <span class="num">${p.qty || 1}<span class="dim"> @ ${escHtml(String((p.expected_plat || '') + (p.qty > 1 ? 'p each' : 'p')))}</span></span>
      <span class="sess-facts">${facts}</span>
      <span>${act}</span>
    </div>`;
  }).join('');
}

/* how many of each state the queue holds - the counts the summary line rides on (the state word is
   the key, so a state the payload adds later still shows up instead of being dropped) */
function sessionQueueBits(rows) {
  const n = {};
  (rows || []).forEach(r => { const w = sessionStateWord(r); n[w] = (n[w] || 0) + 1; });
  return Object.keys(n).map(k => '· ' + n[k] + ' ' + k);
}

function renderSession() {
  const pane = document.getElementById('tp-session');
  if (!pane) return;
  const P = sessionPayload(), sum = P.summary || {};
  const say = SESSION_SAY; SESSION_SAY = '';      /* shown once, in the freshest paint */

  /* the head line: what the session is doing, and nothing at all when there is no session */
  sbits(document.getElementById('sessionMeta'), P.live
    ? ['· ' + (sum.trades || 0) + (sum.trades === 1 ? ' trade' : ' trades'),
       '· ' + (sum.queue_remaining || 0) + ' left',
       '· started ' + ago(sum.started_ts)]
    : []);

  const kpis = document.getElementById('sessionKpis');
  if (kpis) {
    kpis.classList.toggle('hidden', !P.live);
    kpis.innerHTML = P.live ? `
      <div class="kpi" title="platinum earned this session"><div class="k-label">Earned</div><div class="k-val accent">${sessionPlat(sum.earned_plat)}</div></div>
      <div class="kpi" title="trades done this session"><div class="k-label">Trades</div><div class="k-val">${sum.trades || 0}</div></div>
      <div class="kpi" title="trades left today"><div class="k-label">Left today</div><div class="k-val">${sum.trades_left_today ?? '—'}</div></div>
      <div class="kpi" title="queue rows still to work"><div class="k-label">Queue</div><div class="k-val">${sum.queue_remaining || 0}<span class="dim">/${sum.queue_total || 0}</span></div></div>` : '';
  }

  /* one control set per state: Start until a session is open, the loop's four once it is */
  const start = document.getElementById('sessionStart');
  if (start) start.classList.toggle('hidden', P.live);
  ['sessionNext', 'sessionSkip', 'sessionHold', 'sessionEnd'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.classList.toggle('hidden', !P.live);
  });
  const bnext = document.getElementById('sessionNext');
  const bskip = document.getElementById('sessionSkip');
  const bhold = document.getElementById('sessionHold');
  if (bnext) bnext.disabled = !P.live;
  if (bskip) bskip.disabled = !P.focus;
  if (bhold) bhold.disabled = !P.focus;

  const focus = document.getElementById('sessionFocus');
  if (focus) {
    focus.innerHTML = (P.live && P.focus) ? sessionFocusCard(P.focus, say)
      : sessionEmpty(P.live ? 'Nothing left in the queue.' : 'No session open yet.');
  }
  const ql = document.getElementById('sessionQueueList');
  if (ql) {
    const rows = P.live ? P.queue : P.suggested;
    ql.innerHTML = sessionQueueRows(rows, P.live);
    sbits(document.getElementById('sessionQueueMeta'),
      rows.length ? (P.live ? sessionQueueBits(P.queue) : ['· ' + rows.length + ' suggested']) : []);
  }
  const pl = document.getElementById('sessionPending');
  if (pl) {
    pl.innerHTML = sessionPendingRows(P.pending, P.stale);
    const n = (P.pending || []).length + (P.stale || []).length;
    sbits(document.getElementById('sessionPendMeta'),
      n ? ['· ' + (P.pending || []).length + ' waiting']
        .concat((P.stale || []).length ? ['· ' + P.stale.length + ' old'] : []) : []);
  }
  /* the checks ride the payload the panel already painted from: the draft behind every Confirm is
     kept here (one click sends it) and the proposals themselves are never re-asked for */
  const ck = document.getElementById('sessionChecks');
  if (ck) {
    const props = P.proposals || [];
    Object.keys(SESSION_DRAFTS).forEach(k => { delete SESSION_DRAFTS[k]; });
    props.forEach(p => { if (p.trade) SESSION_DRAFTS[p.pending_id] = p.trade; });
    ck.innerHTML = sessionCheckRows(props);
    sbits(document.getElementById('sessionChecksMeta'),
      props.length ? (P.needs_you ? ['· ' + P.needs_you + ' to confirm'] : ['· nothing to confirm'])
        : []);
  }
  markScrollers();      /* the queue and the pending list wear the same fade as every trade list */
}

/* the server's own answer, verbatim - the same contract the whisper row follows */
function sessionSay(msg, bad) {
  const el = document.getElementById('sessionSay');
  if (!el) return;
  el.textContent = msg || '';
  el.classList.toggle('bad', !!bad);
}

/* one click, one POST, then the one refresh every renderer rides (never a session-only poll) */
async function sessionPost(action, body) {
  try {
    const r = await fetch('/api/session/' + action, { method: 'POST',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) });
    const j = await r.json().catch(() => null);
    if (!j || j.ok === false) {
      sessionSay((j && (j.error || j.reason)) || ('HTTP ' + r.status), true);
      return false;
    }
    sessionSay('', false);
    return true;
  } catch (err) {
    sessionSay('no answer from the server', true);
    return false;
  }
}

/* the panel's own controls. Skip and Hold are states, Next is a focus move, End keeps the session
   as history; the pending trade state lives on the server (spec section 11), never in this file */
async function sessionAct(btn) {
  const P = sessionPayload(), f = P.focus || null;
  if (btn.id === 'sessionStart' || btn.id === 'sessionEnd') {
    if (await sessionPost(btn.id === 'sessionStart' ? 'start' : 'end', {})) await load();
    return;
  }
  if (btn.id === 'sessionNext') {
    const i = Number(P.focusIndex);
    if ((Number.isFinite(i) ? i : 0) + 1 >= (P.queue || []).length) { sessionSay('the queue ends here', false); return; }
    if (await sessionPost('focus', { index: (Number.isFinite(i) ? i : 0) + 1 })) await load();
    return;
  }
  if (btn.id === 'sessionSkip' || btn.id === 'sessionHold') {
    if (!f) return;
    const state = btn.id === 'sessionSkip' ? 'SKIPPED' : 'HELD';
    if (await sessionPost('state', { slug: f.slug, rank: f.rank ?? null, state })) await load();
  }
}

/* one confirmation, one transaction: the draft the check came with goes to /api/session/confirm,
   which writes the trade with its id, closes the pending row and moves the session on. The page
   then refreshes the way every other action does - no local completion state, ever (spec §11) */
async function sessionConfirm(btn) {
  const id = btn.dataset.pending || '';
  const draft = SESSION_DRAFTS[id];
  if (!draft) { sessionSay('that check is out of date', true); return; }
  btn.disabled = true;
  try {
    const ok = await sessionPost('confirm', { trade: draft });
    if (ok && window.sfx) sfx.play('done');
    if (ok) await load();
  } finally { btn.disabled = false; }
}

/* the whisper is the order book's own funnel (ordWhisper: one send path, one set of guards, the
   answer printed in the row). A sent whisper is already recorded server-side as CONTACTED, so this
   never posts /api/session/contact - it keeps the answer across the refresh it triggers */
async function sessionWhisper(btn) {
  const row = btn.closest('.ordrow');
  const ok = await ordWhisper(btn);
  if (!ok) return;
  SESSION_SAY = ((row && row.querySelector('.ordres')) || {}).textContent || '';
  if (window.sfx) sfx.play('done');
  await load();
}

/* Home starts the loop and then goes to it: the panel is where the work happens. A refusal (nothing
   to sell yet) lands there too, where the reason and the queue are both on screen */
async function sessionStartFromHome(btn) {
  if (btn.disabled) return;
  btn.disabled = true;
  try {
    await sessionPost('start', {});
    await load();
    if (location.hash !== '#trade/session') location.hash = '#trade/session';
  } finally { btn.disabled = false; }
}

async function sessionClick(e) {
  const t = e.target;
  if (!t || !t.closest) return;
  const wsp = t.closest('.ordwsp');
  if (wsp) { if (!wsp.disabled) await sessionWhisper(wsp); return; }
  const conf = t.closest('.sessconf');
  if (conf) { if (!conf.disabled) await sessionConfirm(conf); return; }
  const pick = t.closest('.sessfocus');
  if (pick) {
    if (await sessionPost('focus', { index: Number(pick.dataset.index) })) await load();
    return;
  }
  const btn = t.closest('button[id]');
  if (!btn || btn.disabled) return;
  if (btn.id === 'homeStartTrading') { await sessionStartFromHome(btn); return; }
  if (btn.id.indexOf('session') === 0) {
    btn.disabled = true;
    try { await sessionAct(btn); } finally { btn.disabled = false; }
  }
}

/* two delegated listeners, no per-row wiring: the panel's controls and Home's one action. The row
   buttons are rebuilt by every paint, so delegation is the only binding that survives a refresh */
(function wireSession() {
  const pane = document.getElementById('tp-session');
  if (pane) pane.addEventListener('click', sessionClick);
  const home = document.getElementById('homeSellNext');
  if (home) home.addEventListener('click', sessionClick);
})();
