/* WFM Trader - HOME renderer (stage 3, Jay 2026-09-28).
   Home is an action surface: TODAY (one strip) / NEXT ACTION / ALERTS / SELL QUEUE / RECENT.
   This file owns the parts fed by the progress store and the trade log:
     #todayEarned / #todaySales  - the today strip's two progress cells (app.js draws the strip)
     #homeToday                 - the strip's detail disclosure (credits, items, sessions, the
                                  week roll-up, inventory value - each value exactly once)
     #homeAlerts                - real problems only (quiet if there are none)
     #homeRecent                - the last few trade events
   The page calls window.wfmRenderHome() on load and on every view switch or refresh; the function
   is idempotent (containers are rebuilt in place, no duplicate rows, stale responses from an
   older call are discarded).

   Plain browser JS, no libraries, no build step. DOM is built with createElement/textContent
   (never innerHTML with data) and colours come from the palette vars in style.css, so all themes
   work. Field names follow the local API payloads (/api/feature/progress, /api/trader,
   /api/trades, /api/feature/{sessions,baro,killswitch,hygiene}).

   Honesty rule for the progress store: null means "not known", never zero. Those values render
   '-' and the matching note from the store's notes[] becomes the row's hover text, so the card
   never invents a number.

   Icon rule: every render rebuilds its rows from scratch, so a host carrying data-icon is never
   re-texted after the sprite has injected its <svg> (textContent would wipe it). New nodes are
   picked up by icons.js' own observer. */
'use strict';
(function () {
  const SESSIONS_SHOWN = 5;     /* newest sessions listed in the Today detail */
  const MATERIALS_SHOWN = 3;    /* material names shown at once */
  const RECENT_EVENTS = 10;     /* trade events in the recent card (it scrolls past that) */
  const BARO_ALERT_HOURS = 48;  /* only treat a visit as news when this close */
  const UNKNOWN = '-';          /* rendered when the progress store has no reading */

  let seq = 0;                  /* guards overlapping refreshes */

  /* ---------- tiny DOM / format helpers ---------- */
  const el = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = String(text);
    return n;
  };
  const add = (parent, tag, cls, text) => {
    const n = el(tag, cls, text);
    parent.appendChild(n);
    return n;
  };
  const clear = (node) => { while (node.firstChild) node.removeChild(node.firstChild); };

  const clip = (s, n) => {
    const t = String(s === null || s === undefined ? '' : s).replace(/\s+/g, ' ').trim();
    return t.length > n ? t.slice(0, n - 1).replace(/[ ,;:.\-]+$/, '') + '\u2026' : t;
  };
  const plat = (n) => (n === null || n === undefined || isNaN(n)) ? null : Math.round(Number(n)).toLocaleString() + 'p';
  const ago = (ts) => {
    if (!ts) return '';
    const s = Math.max(0, Math.floor(Date.now() / 1000 - ts));
    if (s < 90) return s + 's ago';
    if (s < 5400) return Math.round(s / 60) + 'm ago';
    if (s < 172800) return Math.round(s / 3600) + 'h ago';
    return Math.round(s / 86400) + 'd ago';
  };
  const when = (ts) => ts
    ? new Date(ts * 1000).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
    : '';
  const pad2 = (x) => (x < 10 ? '0' : '') + x;
  const localDate = (d) => {
    const t = d || new Date();
    return t.getFullYear() + '-' + pad2(t.getMonth() + 1) + '-' + pad2(t.getDate());
  };
  const dayLabel = (ymd) => {
    const d = new Date(String(ymd) + 'T12:00:00');
    return isNaN(d.getTime()) ? String(ymd) : d.toLocaleDateString([], { month: 'short', day: 'numeric' });
  };
  const dur = (min) => {
    const m = Math.max(0, Math.round(min || 0));
    if (m < 60) return m + 'm';
    const h = Math.floor(m / 60);
    return h + 'h' + (m % 60 ? ' ' + (m % 60) + 'm' : '');
  };
  const plural = (n, one, many) => n + ' ' + (n === 1 ? one : (many || one + 's'));

  /* ---------- progress-store format helpers ----------
     num()/signed() keep "not known" distinct from zero: anything missing, blank or
     unparseable comes back as null and the caller renders '-'. fnum() is the same
     but keeps the fraction (durations arrive as 41.26 hours / 96.5 minutes). */
  const num = (n) => (n === null || n === undefined || n === '' || isNaN(n)) ? null : Math.round(Number(n));
  const fnum = (n) => (n === null || n === undefined || n === '' || isNaN(n)) ? null : Number(n);
  const signed = (n, unit) => {
    const v = num(n);
    return v === null ? null : (v < 0 ? '\u2212' : '+') + Math.abs(v).toLocaleString() + (unit || '');
  };
  const trend = (n) => (n > 0 ? 'upl' : n < 0 ? 'downl' : '');
  /* the store explains its own gaps: the note mentioning `re` becomes the hover text */
  const noteFor = (notes, re, fallback) => (notes.find((n) => re.test(n)) || fallback || '');
  const hm = (ts) => { const d = new Date(ts * 1000); return pad2(d.getHours()) + ':' + pad2(d.getMinutes()); };
  const wdhm = (ts) => new Date(ts * 1000).toLocaleDateString([], { weekday: 'short' }) + ' ' + hm(ts);
  const rangeTxt = (a, b) => {
    if (!a || !b) return '';
    return localDate(new Date(a * 1000)) === localDate(new Date(b * 1000))
      ? wdhm(a) + ' \u2192 ' + hm(b)          /* same day: the weekday is not repeated */
      : wdhm(a) + ' \u2192 ' + wdhm(b);
  };
  const matText = (arr) => (arr || []).filter((m) => m && m.name && num(m.delta))
    .slice(0, MATERIALS_SHOWN)
    .map((m) => clip(m.name, 24) + ' ' + signed(m.delta, '')).join(' \u00b7 ');

  /* ---------- data helpers ---------- */
  const jok = (x) => (x && !x.error) ? x : null;   /* API answers can carry {error} */
  const get = (url) => fetch(url, { headers: { 'Accept': 'application/json' } })
    .then((r) => (r && r.ok ? r.json() : null))
    .catch(() => null);
  /* the page's own summary payload (app.js owns the fetch; Home only reads the two values that
     have no home anywhere else: the credit balance and the inventory value) */
  const summaryOf = () => {
    try { return (typeof SUMMARY !== 'undefined' && SUMMARY) ? SUMMARY : null; } catch (e) { return null; }
  };

  /* ---------- navigation (drawer agent owns wfmOpenItem) ----------
     The drawer contract stays wired for rows that name a tradeable; the Today detail's rows are
     counts, so nothing calls it right now. */
  const openItem = (slug) => {
    if (!slug) return;
    if (typeof window.wfmOpenItem === 'function') {
      try { window.wfmOpenItem(slug); return; } catch (e) { /* fall through to search */ }
    }
    const q = '#search?q=' + encodeURIComponent(slug);
    const p = location.pathname;
    if (p === '/' || p === '' || p === '/index.html') location.hash = q;
    else location.assign('/' + q);
  };

  /* ---------- shared row builders ----------
     The page supplies the card chrome: #homeToday / #homeRecent are .picks bodies inside a card
     whose title is already rendered, and #alertsCard is hidden until something is worth showing.
     If the hosts are ever bare containers instead, a card shell is built so the blocks still
     look right. */
  const hasChildClass = (node, cls) => (node.childNodes || []).some((n) => n.classList && n.classList.contains(cls));
  const block = (host, title) => {
    const cls = host.classList || { contains: () => false };
    if (cls.contains('picks')) return host;                 /* page owns the chrome */
    const card = cls.contains('card') ? host : el('div', 'card');
    if (card !== host) host.appendChild(card);
    if (!hasChildClass(card, 'card-head')) {
      const head = add(card, 'div', 'card-head');
      add(head, 'div', 'card-title', title);
    }
    return add(card, 'div', 'picks');
  };
  const setMeta = (id, text, tip) => {
    const n = document.getElementById(id);
    if (!n) return;
    if (text !== undefined && text !== null) n.textContent = text;
    if (tip) n.title = tip;
  };

  /* One label and one short value per row. The value column is max-content, so it must
     stay short - anything long, or the reason a value is unknown, goes on the hover text.
     `value` is a string, or a list of pieces; each piece is a string, or a [text, class]
     pair so a signed number can carry upl/downl (hence the extra nesting for one piece). */
  const statRow = (body, label, value, tip) => {
    const row = el('div', 'h-row');
    if (tip) row.setAttribute('title', clip(tip, 220));
    const l1 = add(row, 'div', 'h-l1');
    add(l1, 'span', 'h-name', label);
    const cell = add(l1, 'span', 'h-act');
    const parts = Array.isArray(value) ? value : [[value, '']];
    parts.forEach((pc) => {
      if (pc === null || pc === undefined) return;
      const txt = Array.isArray(pc) ? pc[0] : pc;
      const cls = Array.isArray(pc) ? pc[1] : '';
      if (txt === null || txt === undefined || txt === '') return;
      cell.appendChild(cls ? el('span', cls, String(txt)) : document.createTextNode(String(txt)));
    });
    body.appendChild(row);
    return row;
  };
  /* second, dimmer line of the same row - it ellipsizes, so a long list cannot overflow */
  const subRow = (row, text) => {
    if (text) add(row, 'div', 'h-l2', clip(text, 96));
    return row;
  };

  /* One line per session: when it ran, what the store called it, how long it lasted.
     The full start stamp is the only hover detail - the cells already carry the rest. */
  const sessionRow = (s) => {
    const row = el('div', 'h-ev');
    const sm = fnum(s.minutes);
    if (s.start_ts) row.setAttribute('title', when(s.start_ts));
    const badge = el('span', s.current ? 'badge' : null);
    if (s.current) badge.appendChild(el('span', 'upl', 'live'));
    row.appendChild(badge);
    add(row, 'span', 'h-l2', clip(rangeTxt(s.start_ts, s.end_ts) || when(s.start_ts), 26));
    add(row, 'span', 'h-l3', clip(s.headline || '', 60));
    add(row, 'span', 'h-num', sm ? dur(sm) : '');
    return row;
  };

  /* ---------- A. today : the strip cells + the detail disclosure ----------
     The strip itself is app.js's (it holds the page's own platinum + trade readings). This fills
     the two cells only the progress store can answer - and never a second copy of a value that
     is already on the strip: no Platinum row below, no sales count twice. */
  const renderTodayCells = (p) => {
    const earned = document.getElementById('todayEarned');
    const sales = document.getElementById('todaySales');
    const t = (p && p.today) || {};
    const notes = (p && Array.isArray(p.notes) ? p.notes : []).filter((n) => typeof n === 'string');
    if (earned) {
      const pv = p ? num(t.plat_delta) : null;
      /* the accent only celebrates a gain: a zero or a loss stays quiet (orange must mean
         something on this page) */
      earned.textContent = '';
      earned.className = 'k-val' + (pv !== null && pv > 0 ? ' accent' : '');
      if (pv === null) earned.textContent = UNKNOWN;
      else {
        const sp = document.createElement('span');
        sp.className = trend(pv);
        sp.textContent = signed(pv, 'p');
        earned.appendChild(sp);
      }
      const from = plat(t.plat_start), now = plat(t.plat_now);
      earned.title = pv === null
        ? noteFor(notes, /plat/i, 'No reading today')
        : ('from ' + (from || UNKNOWN) + ' to ' + (now || UNKNOWN));
    }
    if (sales) {
      const sc = p ? num((t.trades || {}).sales) : null;
      sales.textContent = sc === null ? UNKNOWN : String(sc);
      sales.title = sc === null ? noteFor(notes, /trade_log/i, 'No reading today') : 'sales logged today';
    }
  };

  const renderTodayDetail = (host, p) => {
    clear(host);
    const body = block(host, 'Today');
    if (!p || typeof p !== 'object') {            /* store missing or unreachable */
      add(body, 'div', 'h-l3', 'Not available yet');
      return;
    }
    const notes = (Array.isArray(p.notes) ? p.notes : []).filter((n) => typeof n === 'string');
    const t = p.today || {};
    const tr = t.trades || {};
    const ss = t.sessions || {};
    const st = p.streaks || {};
    if (p.updated) {
      /* the date belongs to the page header, and the header already carries the sync clock: the
         store's own reading time is the card's hover, so no clock and no date render twice */
      const head = document.querySelector('#todayCard .card-title');
      if (head) head.title = 'progress store updated ' + hm(p.updated);
    }

    /* credits: the balance (it lives nowhere else in the app) and the day's own change */
    const s = summaryOf() || {};
    const bal = num(s.credits);
    statRow(body, 'Credits', bal === null ? UNKNOWN : bal.toLocaleString(), 'in-game credit balance');
    const cv = num(t.credits_delta);
    statRow(body, 'Credits today', cv === null ? UNKNOWN : [[signed(cv, ''), trend(cv)]],
      cv === null ? noteFor(notes, /credits/i, 'No reading today') : '');

    /* items: null until the day has an inventory snapshot of its own */
    const ia = num(t.items_added), ir = num(t.items_removed);
    const items = (ia === null && ir === null) ? null
      : (ia === null ? UNKNOWN : (ia > 0 ? '+' : '') + ia.toLocaleString()) + ' / '
        + (ir === null ? UNKNOWN : (ir > 0 ? '\u2212' : '') + ir.toLocaleString());
    const itotal = num(t.items_total);
    statRow(body, 'Items added / removed', items || UNKNOWN,
      (ia === null && ir === null)
        ? noteFor(notes, /items_added|inventory snapshot/i, 'No snapshot today')
        : (itotal === null ? '' : itotal.toLocaleString() + ' items tracked'));

    /* trades: the count, with the platinum that moved when there was any */
    const tc = num(tr.count);
    const tin = num(tr.plat_in), tout = num(tr.plat_out);
    const trow = statRow(body, 'Trades', tc === null ? UNKNOWN : String(tc),
      tc ? 'sales and purchases logged today' : noteFor(notes, /trade_log/i, 'No trades today'));
    if (tc && (tin || tout)) {
      const bits = [];
      if (tin) bits.push('in ' + tin.toLocaleString() + 'p');
      if (tout) bits.push('out ' + tout.toLocaleString() + 'p');
      subRow(trow, bits.join(' \u00b7 '));
    }

    /* sessions: how many, how long, and whether one is still running */
    const sc = num(ss.count);
    const smin = fnum(ss.minutes);
    const srow = statRow(body, 'Sessions',
      sc === null ? UNKNOWN : [String(sc), ss.current ? ' \u00b7 ' : null, ss.current ? ['live', 'upl'] : null],
      sc ? '' : 'No session today');
    if (sc && smin) subRow(srow, dur(smin) + ' in game');

    /* materials gained: names + deltas on the detail line, the total as the value */
    const mats = (Array.isArray(t.materials_gained) ? t.materials_gained : [])
      .filter((m) => m && m.name && num(m.delta));
    const mtot = num(t.material_delta_total);
    const mrow = statRow(body, 'Materials',
      mats.length ? (mtot !== null ? signed(mtot, '') : String(mats.length)) : UNKNOWN,
      noteFor(notes, /materials/i, 'No sample yet'));
    subRow(mrow, matText(mats));

    /* the week roll-up from streaks{} (hours arrive fractional: 41.26) */
    const wp = num(st.plat_this_week), wt = num(st.trades_this_week), wh = fnum(st.hours_this_week);
    const wrow = statRow(body, 'This week', wp === null ? UNKNOWN : [[signed(wp, 'p'), trend(wp)]],
      wp === null ? 'No week totals yet'
        : plural(num(st.days_active) || 0, 'day') + ' active'
          + (st.last_active_date ? ' \u00b7 last ' + dayLabel(st.last_active_date) : ''));
    const wsub = [];
    if (wt !== null) wsub.push(plural(wt, 'trade'));
    if (wh !== null) wsub.push(dur(wh * 60) + ' in game');
    subRow(wrow, wsub.join(' \u00b7 '));

    /* the inventory value reading (the old KPI cell) - sellable copies only, per report.json */
    const iv = num(s.total_value);
    statRow(body, 'Inventory value', iv === null ? UNKNOWN : iv.toLocaleString() + 'p', 'sellable copies only');

    /* the newest sessions, one line each (the store sends up to 30, newest first) */
    const list = (Array.isArray(p.sessions) ? p.sessions : []).filter((x) => x && x.start_ts && x.end_ts);
    const head = add(body, 'div', 'h-group-head', 'Sessions');
    head.setAttribute('data-icon', 'clock');
    if (!list.length) add(body, 'div', 'h-l3', 'No sessions yet');
    list.slice(0, SESSIONS_SHOWN).forEach((x) => body.appendChild(sessionRow(x)));
  };

  /* ---------- B. alerts ---------- */
  const buildAlerts = (d) => {
    const out = [];

    /* kill switch: posting is off until it is cleared */
    const ks = d.killswitch;
    if (ks && ks.active) {
      out.push({
        kind: 'warn',
        t: 'Posting is paused',
        d: clip(ks.note || 'Kill switch on', 60)
      });
    }

    /* sign-in trouble: the planner could not reach the market site */
    const plan = (d.trader && d.trader.plan) || null;
    if (plan && typeof plan.account === 'string' && /^signin failed/i.test(plan.account)) {
      out.push({
        kind: 'warn',
        t: 'Could not sign in to the market site',
        d: clip('Sign-in failed ' + plan.account.replace(/^signin failed:?\s*/i, ''), 80)
      });
    }

    /* listings priced above someone else */
    const uRows = (d.trader && d.trader.undercuts && d.trader.undercuts.rows) || [];
    const cut = uRows.filter((r) => r && r.action === 'reprice');
    if (cut.length) {
      const ex = cut.slice(0, 2).map((r) => {
        const mine = plat(r.my_price), floor = plat(r.floor);
        if (!r.name) return null;
        if (mine && floor) return r.name + ': you ' + mine + ', them ' + floor;
        return r.name;
      }).filter(Boolean).join(' \u00b7 ');
      out.push({
        kind: 'warn',
        t: plural(cut.length, 'listing needs', 'listings need') + ' attention',
        d: clip('Below your price: ' + ex, 150)
      });
    }

    /* listings that are hidden or stale */
    const h = d.hygiene || null;
    const actions = (h && h.actions) || [];
    const count = { hide: 0, show: 0, refresh: 0 };
    actions.forEach((a) => {
      if (a && count[a.action] !== undefined) count[a.action] += 1;
    });
    const staleDays = (h && h.rules && h.rules.stale_refresh_days) || 7;
    if (count.hide) {
      /* right now every hide row is a PLANNED listing (nothing is posted yet), so
         split the count rather than claiming live listings went offline */
      const planned = actions.filter((a) => a && a.action === 'hide' &&
        /not live yet|planned|not posted/i.test(String(a.reason || ''))).length;
      const live = count.hide - planned;
      const bits = [];
      if (live) bits.push(plural(live, 'listing is', 'listings are') + ' hidden while you are offline');
      if (planned) bits.push(plural(planned, 'planned listing is', 'planned listings are') + ' parked until posting goes live');
      if (bits.length) {
        out.push({
          kind: 'info',
          t: bits.join(' \u00b7 '),
          d: live ? '' : 'Not live - plan only'
        });
      }
    }
    if (count.refresh) {
      out.push({
        kind: 'info',
        t: plural(count.refresh, 'listing has', 'listings have') + ' not moved in ' + staleDays + ' days'
      });
    }
    if (count.show) {
      out.push({
        kind: 'info',
        t: plural(count.show, 'listing can', 'listings can') + ' go back up'
      });
    }

    /* posting is off (the title says it; the "Not live" wording already rides the alert above) */
    const set = (d.trader && d.trader.settings) || {};
    const dry = set.dry_run === true || !!(plan && plan.dry_run === true);
    if (dry) {
      out.push({ kind: 'info', t: 'Nothing is posted automatically' });
    }

    /* Baro visit, only when it is actually close */
    const tr = (d.baro && d.baro.trader) || null;
    if (tr && tr.active) {
      out.push({
        kind: 'warn',
        t: 'Baro is here' + (tr.closes_in ? ' - leaves in ' + tr.closes_in : ''),
        d: clip([tr.location, tr.expiry_text].filter(Boolean).join(' \u00b7 '), 120)
      });
    } else if (tr && typeof tr.starts_in_hours === 'number' && tr.starts_in_hours <= BARO_ALERT_HOURS && tr.starts_in) {
      out.push({
        kind: 'info',
        t: 'Baro arrives in ' + tr.starts_in,
        d: clip([tr.location, tr.activation_text].filter(Boolean).join(' \u00b7 '), 120)
      });
    }

    return out;
  };

  const renderAlerts = (host, d) => {
    clear(host);
    const alerts = buildAlerts(d);
    /* The page ships #alertsCard hidden; show it only when there is something real.
       Empty alerts must leave no trace: no card, no placeholder text - and the band above
       widens (no-alerts) so a quiet day leaves no empty column either. */
    const wrap = document.getElementById('alertsCard');
    const main = document.getElementById('homeMain');
    if (main) main.classList.toggle('no-alerts', !alerts.length);
    if (!alerts.length) {
      if (wrap && wrap.classList.add) wrap.classList.add('hidden');
      return;
    }
    if (wrap && wrap.classList.remove) wrap.classList.remove('hidden');
    const body = block(host, 'Needs attention');
    alerts.forEach((a) => {
      const row = el('div', 'h-alert h-alert-' + (a.kind || 'info'));
      add(row, 'div', 'h-alert-t', a.t);
      if (a.d) add(row, 'div', 'h-alert-d', a.d);
      body.appendChild(row);
    });
  };

  /* ---------- C. recent : the last few trade events ---------- */
  /* Newest first, whatever order the payload arrived in (the log file can hold its entries in any
     order and a note is written when it is written). A note is not a trade: it renders as a note
     row (three columns, no qty, no price), so a pinned "History tracking started" sitting above
     year-old sales cannot be read as the newest sale (screenshot review, 2026-09-28). The line
     under the title states the ordering, never a second copy of a row's own time. */
  const renderRecent = (host, d) => {
    clear(host);
    const events = ((d.trades && d.trades.events) || []).filter((e) => e && typeof e === 'object')
      .sort((a, b) => (Number(b.ts) || 0) - (Number(a.ts) || 0));
    setMeta('recentMeta', ' · newest first · notes are not trades');
    const body = block(host, 'Recent');
    if (!events.length) {
      const empty = add(body, 'div', 'empty');
      const ic = add(empty, 'span', 'empty-icon');
      ic.setAttribute('data-icon', 'tray');
      ic.setAttribute('data-icon-size', '18');
      add(empty, 'div', null, 'No trades logged yet');
      return;
    }
    const LABEL = { sale: 'Sold', purchase: 'Bought', listing: 'Listed', unlist: 'Unlisted', reprice: 'Repriced', note: 'Note' };
    events.slice(0, RECENT_EVENTS).forEach((e) => {
      const isNote = e.kind === 'note';
      const row = el('div', isNote ? 'h-ev h-note' : 'h-ev');
      if (e.note) row.setAttribute('title', clip(e.note, 300));
      add(row, 'span', 'badge' + (e.kind ? ' ' + e.kind : ''), LABEL[e.kind] || e.kind || 'Event');
      add(row, 'span', 'h-name', clip(e.name || e.note || 'item', 60));
      /* a note carries the log's own words, not a deal: no qty, no price - just when */
      if (isNote) {
        add(row, 'span', 'h-when', when(e.ts) || ago(e.ts));
        body.appendChild(row);
        return;
      }
      add(row, 'span', 'h-num h-qty', e.qty === null || e.qty === undefined ? '' : e.qty + '\u00d7');
      const deal = (e.total !== null && e.total !== undefined) ? plat(e.total)
        : (e.plat !== null && e.plat !== undefined ? plat(e.plat) : null);
      add(row, 'span', 'h-num', deal || '');
      add(row, 'span', 'h-when', when(e.ts) || ago(e.ts));
      body.appendChild(row);
    });
  };

  /* ---------- entry point ---------- */
  window.wfmRenderHome = function wfmRenderHome() {
    const mine = ++seq;
    const today = document.getElementById('homeToday');
    const alerts = document.getElementById('homeAlerts');
    const recent = document.getElementById('homeRecent');
    if (!today && !alerts && !recent) return null;
    return Promise.all([
      get('/api/trader'),
      get('/api/trades'),
      get('/api/feature/progress'),
      get('/api/feature/baro'),
      get('/api/feature/killswitch'),
      get('/api/feature/hygiene')
    ]).then((r) => {
      if (mine !== seq) return;   /* a newer refresh already answered */
      const d = {
        trader: jok(r[0]), trades: jok(r[1]), progress: jok(r[2]),
        baro: jok(r[3]), killswitch: jok(r[4]), hygiene: jok(r[5])
      };
      renderTodayCells(d.progress);
      if (today) renderTodayDetail(today, d.progress);
      if (alerts) renderAlerts(alerts, d);
      if (recent) renderRecent(recent, d);
    });
  };
})();

/* ---------------------------------------------------------------- chat dock (right of HOME)
   Loads static/chat.js + static/chat.css once, only on the page that already runs the HOME
   renderer. The chat owns its own DOM, its collapsed-or-open state and placement (see chat.js),
   so this is the whole integration: no edit to app.js is needed. */
(function () {
  if (document.getElementById('chatDock')) return;
  if (!document.querySelector('link[href="/chat.css"]')) {
    const l = document.createElement('link');
    l.rel = 'stylesheet';
    l.href = '/chat.css';
    document.head.appendChild(l);
  }
  if (!document.querySelector('script[src="/chat.js"]')) {
    const s = document.createElement('script');
    s.src = '/chat.js';
    s.defer = true;
    document.head.appendChild(s);
  }
})();
