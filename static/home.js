/* WFM Trader - HOME "what should I do today?" renderer.
   Fills three containers owned by index.html: #homeToday, #homeAlerts and
   #homeRecent. They are .picks bodies inside page-owned cards, so this file adds
   rows only; it also unhides #alertsCard while there is something to show and
   fills the page's #todayMeta / #recentMeta spans when they are empty.
   The page calls window.wfmRenderHome() on load and on every view switch or
   refresh; the function is idempotent (containers are rebuilt in place, no
   duplicate rows, stale responses from an older call are discarded).

   What it answers:
     #homeToday  - what to do first (sell actions, then keep/ducat/relic groups)
     #homeAlerts - real problems only (quiet if there are none)
     #homeRecent - last few trade events + the latest session summary

   Plain browser JS, no libraries, no build step. DOM is built with
   createElement/textContent (never innerHTML with data) and colours come from
   the palette vars in style.css, so all themes work. Field names follow the
   local API payloads (/api/feature/advisor, /api/trader, /api/trades,
   /api/feature/{sessions,baro,killswitch,hygiene}). */
'use strict';
(function () {
  const TOP_SELL = 6;           /* sell actions shown straight away */
  const REST_SELL = 30;         /* extra rows behind the expander */
  const GROUP_ROWS = 2;         /* rows per secondary group */
  const RECENT_EVENTS = 5;      /* trade events in the recent card */
  const BARO_ALERT_HOURS = 48;  /* only treat a visit as news when this close */

  let openAll = false;          /* expander state; survives re-renders */
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

  /* ---------- data helpers ---------- */
  const jok = (x) => (x && !x.error) ? x : null;   /* API answers can carry {error} */
  const get = (url) => fetch(url, { headers: { 'Accept': 'application/json' } })
    .then((r) => (r && r.ok ? r.json() : null))
    .catch(() => null);

  const rowsOf = (adv) => {
    const out = [];
    if (!adv || !adv.items) return out;
    const m = adv.items;
    for (const k in m) if (Object.prototype.hasOwnProperty.call(m, k) && m[k]) out.push(m[k]);
    return out;
  };
  const byScore = (a, b) => (b.score || 0) - (a.score || 0)
    || String(a.name || '').localeCompare(String(b.name || ''));
  const of = (rs, rec) => rs.filter((r) => r.recommendation === rec);
  const demandText = (b) => b === 'spike' ? 'demand rising'
    : b === 'fade' ? 'demand fading'
      : b === 'steady' ? 'demand steady' : '';

  const qtyOf = (r) => r.recommended_quantity || 0;
  const priceOf = (r) => (r.recommended_price === null || r.recommended_price === undefined)
    ? null : Math.round(r.recommended_price);

  const actText = (r) => {
    const q = qtyOf(r), p = priceOf(r);
    switch (r.recommendation) {
      case 'list': return 'List ' + (q || 1) + (p === null ? '' : ' \u00d7 ' + p + 'p');
      case 'burn_ducats': return 'Burn ' + (q || 1) + ' for ducats';
      case 'open_relic': return 'Open ' + plural(q || 1, 'relic');
      case 'finish_set': return 'Finish the set';
      case 'assemble_set': return 'Assemble the set';
      case 'keep': return 'Keep it';
      case 'already_listed': return 'Already listed';
      default: return 'Hold';
    }
  };

  /* Layer 2 - what you actually have. Equipped copies never count as sellable,
     so the API's sellable number is used as-is. */
  const ownLine = (r) => {
    const bits = [];
    if (r.sellable) bits.push('You have ' + r.sellable + ' safe to sell');
    if (r.owned !== null && r.owned !== undefined && r.owned !== r.sellable) bits.push(r.owned + ' owned');
    if (r.equipped) bits.push(r.equipped + ' equipped');
    if (r.reserved) bits.push(r.reserved + ' kept back');
    if (r.lane_rank !== null && r.lane_rank !== undefined) bits.push('rank ' + r.lane_rank);
    return bits.join(' \u00b7 ');
  };

  /* Layer 2 - a short "why". Boilerplate price/liquidity/lane lines are skipped
     in favour of the first reason that says something about this item, and any
     bit that would repeat one already shown is dropped. */
  const BOILER = /^(current market price|you sell |you historically sell|liquidity |no obvious baro|\d+ stays in the)/i;
  const whyLine = (r) => {
    const bits = [];
    const rs = (r.reasons || []).filter((s) => typeof s === 'string' && s.trim());
    const has = (re) => bits.some((b) => re.test(b));
    const pick = rs.find((s) => !BOILER.test(s));
    if (pick) bits.push(clip(pick, 92));
    const d = demandText(r.demand_badge);
    if (d && !has(/demand/i)) bits.push(d);
    const note = (r.notes || []).filter((s) => typeof s === 'string' && s.trim())[0];
    if (note) {
      const key = clip(note, 24);
      if (!bits.some((b) => b.indexOf(key) >= 0)) bits.push(clip(note, 70));
    }
    if (r.best_sell_window && !bits.some((b) => b.indexOf(r.best_sell_window) >= 0)) bits.push('best window ' + r.best_sell_window);
    if (r.vol48 && !has(/48h/i)) bits.push('Sales / 48h: ' + r.vol48);
    if (!bits.length && rs[0]) bits.push(clip(rs[0], 92));
    return bits.join(' \u00b7 ');
  };

  /* Layer 3 - full detail on hover. */
  const tipText = (r) => {
    const parts = [];
    if (r.text) parts.push(String(r.text).trim());
    const rs = (r.reasons || []).filter((s) => typeof s === 'string' && s.trim());
    if (rs.length) parts.push('\u2014 ' + rs.join('\n\u2014 '));
    return clip(parts.join('\n\n'), 900);
  };

  /* set jobs have nothing sellable on their own, so the why line explains the
     job: the keeping reason if there is one, else the plain plan from the row text. */
  const setWhy = (r) => {
    const rs = (r.reasons || []).filter((s) => typeof s === 'string' && s.trim());
    const pick = rs.find((s) => /craft|complete/i.test(s));
    if (pick) return clip(pick, 92);
    const rec = String(r.text || '').split('\n').map((s) => s.trim())
      .find((s) => /^recommendation:/i.test(s));
    if (rec) return clip(rec.replace(/^recommendation:\s*/i, ''), 110);
    return clip(rs[0] || 'Whole sets sell for more than loose parts', 92);
  };

  /* ---------- navigation (drawer agent may own wfmOpenItem) ---------- */
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
     The page supplies the card chrome: #homeToday / #homeRecent are .picks bodies
     inside a card whose title is already rendered, and #alertsCard is hidden until
     something is worth showing. If the hosts are ever bare containers instead, a
     card shell is built so the blocks still look right. */
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
  const setMeta = (id, text) => {
    const n = document.getElementById(id);
    if (n && !String(n.textContent || '').trim()) n.textContent = text || '';
  };

  const itemRow = (r, opts) => {
    const o = opts || {};
    const slug = r.item || o.slug || '';
    const row = el('div', 'h-row h-click' + (o.sm ? ' h-sm' : ''));
    row.setAttribute('role', 'button');
    row.setAttribute('tabindex', '0');
    if (slug) row.setAttribute('data-slug', slug);
    const tip = tipText(r);
    if (tip) row.setAttribute('title', tip);
    const l1 = add(row, 'div', 'h-l1');
    add(l1, 'span', 'h-name', r.name || slug || 'Item');
    add(l1, 'span', 'h-act', o.act || actText(r));
    const l2 = ownLine(r);
    if (l2) add(row, 'div', 'h-l2', l2);
    const why = o.why || whyLine(r);
    if (why) add(row, 'div', 'h-l3', why);
    row.addEventListener('click', () => openItem(slug));
    row.addEventListener('keydown', (ev) => {
      if (ev.key === 'Enter' || ev.key === ' ' || ev.key === 'Spacebar') { ev.preventDefault(); openItem(slug); }
    });
    return row;
  };

  /* ---------- A. today ---------- */
  const renderToday = (host, adv) => {
    clear(host);
    const body = block(host, 'Today');
    const rs = rowsOf(adv);
    if (!rs.length) {
      add(body, 'div', 'h-l3', 'Still working out what to sell - refresh in a moment.');
      return;
    }
    const sells = of(rs, 'list').sort(byScore);
    const ducats = of(rs, 'burn_ducats').sort(byScore);
    const relics = of(rs, 'open_relic').sort(byScore);
    const sets = of(rs, 'finish_set').concat(of(rs, 'assemble_set')).sort(byScore);
    const earmarked = of(rs, 'keep')
      .filter((r) => (r.reasons || []).some((s) => typeof s === 'string' && /craft|complete/i.test(s)))
      .sort(byScore);
    const keepRows = sets.length ? sets : earmarked;
    const total = sells.length + ducats.length + relics.length + sets.length;

    setMeta('todayMeta', adv && adv.generated ? '\u00b7 updated ' + clip(adv.generated, 24) : '');

    add(body, 'div', 'h-lead', total
      ? 'You have ' + total + ' things worth doing'
      : 'Nothing needs doing right now');
    const bits = [];
    if (sells.length) bits.push(sells.length + ' to sell');
    if (ducats.length) bits.push(ducats.length + ' to burn for ducats');
    if (relics.length) bits.push(relics.length + ' relics to open');
    if (sets.length) bits.push(plural(sets.length, 'set job'));
    if (bits.length) add(body, 'div', 'h-lead2', bits.join(' \u00b7 '));

    const potential = sells.reduce((s, r) => s + qtyOf(r) * (r.recommended_price || 0), 0);
    if (potential > 0) {
      const pot = add(body, 'div', 'h-pot');
      add(pot, 'span', null, 'Potential platinum: ');
      add(pot, 'span', 'h-pot-n', plat(potential));
      add(pot, 'span', 'h-pot-x', ' if every sell row moves');
    }

    sells.slice(0, TOP_SELL).forEach((r) => body.appendChild(itemRow(r)));

    const group = (title, arr, mk) => {
      if (!arr.length) return;
      add(body, 'div', 'h-group-head', title);
      arr.slice(0, GROUP_ROWS).forEach((r) => body.appendChild(mk(r)));
    };
    group('Keep - sets worth finishing', keepRows, (r) => itemRow(r, { sm: true, why: setWhy(r) }));
    group('Ducats - low value, burn them', ducats, (r) => itemRow(r, { sm: true }));
    group('Relics to open', relics, (r) => itemRow(r, { sm: true }));

    const rest = sells.slice(TOP_SELL, TOP_SELL + REST_SELL);
    if (rest.length) {
      const wrap = add(body, 'div', 'h-morewrap');
      const btn = el('button', 'h-more');
      btn.type = 'button';
      btn.setAttribute('aria-expanded', openAll ? 'true' : 'false');
      btn.textContent = openAll ? 'Hide extra recommendations' : 'View all recommendations';
      const panel = add(wrap, 'div', 'h-morelist');
      panel.hidden = !openAll;
      add(panel, 'div', 'h-lead2',
        'Next ' + rest.length + ' of ' + sells.length + ' - biggest earners first.');
      rest.forEach((r) => panel.appendChild(itemRow(r, { sm: true })));
      btn.addEventListener('click', () => {
        openAll = !openAll;
        panel.hidden = !openAll;
        btn.textContent = openAll ? 'Hide extra recommendations' : 'View all recommendations';
        btn.setAttribute('aria-expanded', openAll ? 'true' : 'false');
      });
      wrap.appendChild(btn);
    }
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
        d: clip(ks.note || 'The kill switch is on - nothing will be listed until it is cleared.', 140)
      });
    }

    /* sign-in trouble: the planner could not reach the market site */
    const plan = (d.trader && d.trader.plan) || null;
    if (plan && typeof plan.account === 'string' && /^signin failed/i.test(plan.account)) {
      out.push({
        kind: 'warn',
        t: 'Could not sign in to the market site',
        d: 'Listings wait until the next sign-in works. ' + clip(plan.account.replace(/^signin failed:?\s*/i, ''), 110)
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
        d: clip('Someone is listing lower than you. ' + ex, 150)
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
          d: live ? 'They go back up when you next play.' : 'Nothing is posted to the market yet - this is only a plan.'
        });
      }
    }
    if (count.refresh) {
      out.push({
        kind: 'info',
        t: plural(count.refresh, 'listing has', 'listings have') + ' not moved in ' + staleDays + ' days',
        d: 'A fresh price gets them seen again.'
      });
    }
    if (count.show) {
      out.push({
        kind: 'info',
        t: plural(count.show, 'listing can', 'listings can') + ' go back up',
        d: 'Your last session finished - they can be shown again.'
      });
    }

    /* posting is off */
    const set = (d.trader && d.trader.settings) || {};
    const dry = set.dry_run === true || !!(plan && plan.dry_run === true);
    if (dry) {
      out.push({
        kind: 'info',
        t: 'Nothing is posted automatically',
        d: 'Not live - listings are planned here, nothing is sent out.'
      });
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
       Empty alerts must leave no trace: no card, no placeholder text. */
    const wrap = document.getElementById('alertsCard');
    if (!alerts.length) {
      if (wrap && wrap.classList && wrap.classList.add) wrap.classList.add('hidden');
      return;
    }
    if (wrap && wrap.classList && wrap.classList.remove) wrap.classList.remove('hidden');
    const body = block(host, 'Needs attention');
    add(body, 'div', 'h-lead2', plural(alerts.length, 'thing needs', 'things need') + ' a look');
    alerts.forEach((a) => {
      const row = el('div', 'h-alert h-alert-' + (a.kind || 'info'));
      add(row, 'div', 'h-alert-t', a.t);
      if (a.d) add(row, 'div', 'h-alert-d', a.d);
      body.appendChild(row);
    });
  };

  /* ---------- C. recent ---------- */
  const renderRecent = (host, d) => {
    clear(host);
    const events = ((d.trades && d.trades.events) || []).filter((e) => e && typeof e === 'object');
    const sessions = (d.sessions && d.sessions.sessions) || [];
    if (!events.length && !sessions.length) return;

    setMeta('recentMeta', events.length && events[0].ts ? '\u00b7 latest ' + when(events[0].ts) : '');
    const body = block(host, 'Recent');

    /* latest day with a session, rolled up */
    const byDate = {};
    sessions.forEach((s) => {
      if (s && s.date) (byDate[s.date] = byDate[s.date] || []).push(s);
    });
    const days = Object.keys(byDate).sort().reverse();
    if (days.length) {
      const day = days[0];
      const group = byDate[day];
      const agg = { dur: 0, sales: 0, gross: 0, bought: 0, spent: 0, net: 0 };
      group.forEach((s) => {
        agg.dur += s.dur_min || 0;
        agg.sales += s.sales || 0;
        agg.gross += s.gross || 0;
        agg.bought += s.purchases || 0;
        agg.spent += s.spent || 0;
        agg.net += s.net || 0;
      });
      const best = group.map((s) => s.best_sale).filter(Boolean)
        .sort((a, b) => (b.total || b.plat || 0) - (a.total || a.plat || 0))[0] || null;
      const box = add(body, 'div', 'h-sess');
      const yesterday = (() => { const t = new Date(); t.setDate(t.getDate() - 1); return localDate(t); })();
      const dayTxt = day === localDate() ? 'Today'
        : day === yesterday ? 'Yesterday'
          : 'Last session \u00b7 ' + dayLabel(day);
      add(box, 'span', 'h-sess-t', dayTxt);
      add(box, 'span', 'h-sess-n', dur(agg.dur) + ' in game \u00b7 '
        + plural(agg.sales, 'sale') + ' \u00b7 ' + Math.round(agg.gross) + 'p earned');
      const sub = add(box, 'div', 'h-l3');
      if (agg.bought) {
        sub.appendChild(el('span', null, plural(agg.bought, 'buy', 'buys') + ' \u00b7 ' + Math.round(agg.spent) + 'p spent'));
        sub.appendChild(document.createTextNode(' \u00b7 '));
      }
      const net = el('span', agg.net >= 0 ? 'upl' : 'downl',
        (agg.net >= 0 ? '+' : '\u2212') + Math.abs(Math.round(agg.net)) + 'p net');
      sub.appendChild(net);
      if (best && (best.name || best.plat || best.total)) {
        sub.appendChild(document.createTextNode(' \u00b7 '));
        sub.appendChild(el('span', null, 'best sale: ' + clip(best.name || 'item', 40)
          + (best.total || best.plat ? ' ' + Math.round(best.total || best.plat) + 'p' : '')));
      }
      if (group.length > 1) {
        sub.appendChild(document.createTextNode(' \u00b7 '));
        sub.appendChild(el('span', null, plural(group.length, 'session')));
      }
    }

    if (events.length) {
      add(body, 'div', 'h-group-head', 'Latest activity');
      const LABEL = { sale: 'Sold', purchase: 'Bought', listing: 'Listed', unlist: 'Unlisted', reprice: 'Repriced', note: 'Note' };
      events.slice(0, RECENT_EVENTS).forEach((e) => {
        const row = el('div', 'h-ev');
        if (e.note) row.setAttribute('title', clip(e.note, 300));
        add(row, 'span', 'badge' + (e.kind ? ' ' + e.kind : ''), LABEL[e.kind] || e.kind || 'Event');
        add(row, 'span', 'h-name', clip(e.name || e.note || 'item', 60));
        add(row, 'span', 'h-num h-qty', e.qty === null || e.qty === undefined ? '' : e.qty + '\u00d7');
        const deal = (e.total !== null && e.total !== undefined) ? plat(e.total)
          : (e.plat !== null && e.plat !== undefined ? plat(e.plat) : null);
        add(row, 'span', 'h-num', deal || '');
        add(row, 'span', 'h-when', when(e.ts) || ago(e.ts));
        body.appendChild(row);
      });
    }
  };

  /* ---------- entry point ---------- */
  window.wfmRenderHome = function wfmRenderHome() {
    const mine = ++seq;
    const today = document.getElementById('homeToday');
    const alerts = document.getElementById('homeAlerts');
    const recent = document.getElementById('homeRecent');
    if (!today && !alerts && !recent) return null;
    return Promise.all([
      get('/api/feature/advisor'),
      get('/api/trader'),
      get('/api/trades'),
      get('/api/feature/sessions'),
      get('/api/feature/baro'),
      get('/api/feature/killswitch'),
      get('/api/feature/hygiene')
    ]).then((r) => {
      if (mine !== seq) return;   /* a newer refresh already answered */
      const d = {
        advisor: jok(r[0]), trader: jok(r[1]), trades: jok(r[2]), sessions: jok(r[3]),
        baro: jok(r[4]), killswitch: jok(r[5]), hygiene: jok(r[6])
      };
      if (today) renderToday(today, d.advisor);
      if (alerts) renderAlerts(alerts, d);
      if (recent) renderRecent(recent, d);
    });
  };
})();
