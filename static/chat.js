/* WFM Trader - CHAT dock (right of HOME).
   Jay (2026-09-27): "add a chat that snaps to the right of the home page. look into getting it so
   other people can chat with their profiles active."
   Jay (2026-09-28, stage 3): "Chat: make it collapsible / opened on demand ... not a permanently
   visible 300-360px column." So the dock is COLLAPSED BY DEFAULT: one toggle (#chatToggle, in the
   home header row) opens and closes it, the choice is remembered per browser (localStorage), and
   a closed dock leaves no rail and no gap (the home grid is one column until it opens).

   Local-first: every message is stored by the dashboard itself (POST /api/chat -> data/chat.json),
   so the panel works with no relay, no account and no keys. When a relay URL is configured
   (GET /api/chat -> relay, set via chat_relay_url in config), messages are also posted to that
   room and the room history is pulled back, which is what lets other dashboards share
   the same chat. Each message carries a profile stamp (name, MR, platform) taken from the local
   save - the chip shows exactly what is sent.

   Layout: this file owns #chatDock, the toggle and their placement, so no edit is needed inside
   app.js/index.html; #homeMain (the cards) is the page's own wrapper and the dock simply appends
   beside it. #view-home.chat-open is a 2-column grid at >=1200px (340px rail, 360px at >=1500px)
   and a normal block under the cards below 1200px. Styling is in chat.css, colours come from the
   palette vars, sounds from window.sfx (no-op when absent).

   Plain browser JS, no libraries, no build step. DOM via createElement/textContent only. */
(function () {
  'use strict';
  var POLL = 5000;          /* local poll: cheap, one request per tick, paused when hidden */
  var RELAY_POLL = 5000;
  var MAXLEN = 500;
  var KEY = 'wfm.chat.open'; /* per-browser: closed until the toggle asks for it */

  var href = '', rows = [], seen = {}, lastId = 0, relayCursor = 0, me = {}, timer = null, busy = false;
  var open = false;

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  function jget(url) {
    return fetch(url, { headers: { 'Accept': 'application/json' } }).then(function (r) {
      if (!r.ok) throw new Error('http ' + r.status);
      return r.json();
    });
  }

  function jpost(url, body) {
    return fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) { return { ok: r.ok, status: r.status, j: j }; });
    });
  }

  function timeOf(ts) {
    try {
      return new Date(ts * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
    } catch (e) { return ''; }
  }

  function whoText(w) {
    w = w || {};
    var bits = [];
    if (w.name) bits.push(w.name);
    if (w.mr) bits.push('MR ' + w.mr);
    return bits.join(' · ') || 'anon';
  }

  /* ---------------------------------------------------------------- open / closed */

  function stored() {
    try { return localStorage.getItem(KEY) === '1'; } catch (e) { return false; }
  }

  function remembered(v) {
    try { localStorage.setItem(KEY, v ? '1' : '0'); } catch (e) { /* private mode: session only */ }
  }

  function setOpen(v) {
    open = !!v;
    remembered(open);
    paint();
  }

  /* paint the state: the section grid, the toggle's own state, the measured height, and the
     first pull the moment the dock becomes visible (a closed dock does not poll) */
  function paint() {
    var view = document.getElementById('view-home');
    var btn = document.getElementById('chatToggle');
    if (view) view.classList.toggle('chat-open', open);
    if (btn) {
      btn.setAttribute('aria-expanded', open ? 'true' : 'false');
      btn.title = open ? 'Hide the squad chat' : 'Show the squad chat';
    }
    fit();
    if (window.PlatChart && window.PlatChart.redraw) { try { window.PlatChart.redraw(); } catch (e) {} }
    if (open) pullLocal().then(pullRelay);
  }

  /* ---------------------------------------------------------------- build */

  function build() {
    var view = document.getElementById('view-home');
    if (!view) return false;
    var dock = document.getElementById('chatDock');
    if (dock && dock.isConnected) return true;

    dock = el('aside', 'card');
    dock.id = 'chatDock';

    var head = el('div', 'card-head');
    var title = el('div', 'card-title', 'Chat');
    title.setAttribute('data-icon', 'users-three');
    var state = el('span', 'chip act-offline', 'Local only');
    state.id = 'chatState';
    state.title = 'Local only · no relay set';
    head.appendChild(title);
    head.appendChild(state);

    var list = el('div', 'chat-rows');
    list.id = 'chatRows';
    list.setAttribute('aria-live', 'polite');

    var form = el('form', 'chat-form');
    form.id = 'chatForm';
    var input = el('input', 'chat-input');
    input.id = 'chatInput';
    input.placeholder = 'Message the squad';
    input.maxLength = MAXLEN;
    input.autocomplete = 'off';
    var send = el('button', 'btn primary', 'Send');
    send.type = 'submit';
    send.id = 'chatSend';
    form.appendChild(input);
    form.appendChild(send);

    dock.appendChild(head);
    dock.appendChild(list);
    dock.appendChild(form);
    view.appendChild(dock);

    form.addEventListener('submit', function (ev) { ev.preventDefault(); post(); });
    var btn = document.getElementById('chatToggle');
    if (btn) btn.addEventListener('click', function () { setOpen(!open); });
    open = stored();
    paint();
    if (window.iconRepaint) { try { window.iconRepaint(dock); } catch (e) {} }
    return true;
  }

  /* ---------------------------------------------------------------- render */

  function merge(list) {
    (list || []).forEach(function (r) {
      if (!r || typeof r.id !== 'number' || seen[r.id]) return;
      seen[r.id] = 1;
      rows.push(r);
      if (r.id > lastId) lastId = r.id;
    });
    rows.sort(function (a, b) { return (a.id || 0) - (b.id || 0); });
    if (rows.length > 300) rows = rows.slice(-300);
  }

  function render() {
    var list = document.getElementById('chatRows');
    if (!list) return;
    var atBottom = list.scrollTop + list.clientHeight >= list.scrollHeight - 24;
    list.textContent = '';
    if (!rows.length) {
      var empty = el('div', 'dim small pad', 'No messages yet');
      empty.id = 'chatEmpty';
      list.appendChild(empty);
      return;
    }
    rows.forEach(function (r) {
      var row = el('div', 'chatrow');
      var who = el('span', 'chat-who', whoText(r.who));
      var txt = el('span', 'chat-text', r.text);
      var at = el('span', 'chat-at dim small', timeOf(r.ts));
      if (r.who && r.who.name && me && r.who.name === me.name) row.classList.add('mine');
      row.title = whoText(r.who) + ' · ' + timeOf(r.ts);
      row.appendChild(who);
      row.appendChild(txt);
      row.appendChild(at);
      list.appendChild(row);
    });
    if (atBottom || !list.dataset.init) { list.dataset.init = '1'; list.scrollTop = list.scrollHeight; }
  }

  function status(text, kind) {
    var s = document.getElementById('chatState');
    if (!s) return;
    s.textContent = text;
    s.className = 'chip ' + (kind === 'live' ? 'act-show' : (kind === 'err' ? 'act-offline' : ''));
  }

  /* The open rail runs from its own top to the bottom of the home view (Jay: "chat can go all the
     way down"). CSS cannot know the header or footer heights, so the view's bottom edge is
     measured here and re-measured on resize. While the dock is closed - or under 1200px, where it
     stacks under the cards - the measured height is cleared and the CSS caps take over. */
  function fit() {
    var dock = document.getElementById('chatDock');
    var view = document.getElementById('view-home');
    if (!dock) return;
    if (!open || window.innerWidth < 1200 || !view) { dock.style.height = ''; return; }
    var top = dock.getBoundingClientRect().top;
    if (top < 0) top = 10;                     /* already stuck to the top of the viewport */
    dock.style.height = Math.max(280, Math.round(view.getBoundingClientRect().bottom - top)) + 'px';
  }

  /* ---------------------------------------------------------------- sync */

  function pullLocal() {
    return jget('/api/chat').then(function (d) {
      me = (d && d.me) || {};
      href = (d && d.relay) || '';
      merge(d && d.rows);
      status(href ? 'Live' : 'Local only', href ? 'live' : 'off');
      var input = document.getElementById('chatInput');
      if (input && me.name) input.placeholder = 'Message as ' + me.name;
      render();
    }).catch(function () { status('Offline', 'err'); });
  }

  function pullRelay() {
    if (!href) return Promise.resolve();
    return jget(href.replace(/\/+$/, '') + '/messages?since=' + relayCursor).then(function (d) {
      var got = (d && d.rows) || [];
      /* the room has its own id space: advance that cursor separately from the local one */
      got.forEach(function (r) { if (r && typeof r.id === 'number' && r.id > relayCursor) relayCursor = r.id; });
      merge(got);
      status('Live', 'live');
      render();
    }).catch(function () { status('Relay unreachable', 'err'); });
  }

  function post() {
    var input = document.getElementById('chatInput');
    if (!input || busy) return;
    var text = (input.value || '').replace(/\s+/g, ' ').trim();
    if (!text) return;
    busy = true;
    var stamp = { name: me.name || '', mr: me.mr || null, platform: me.platform || '' };
    var payload = { text: text.slice(0, MAXLEN), who: stamp };
    input.value = '';

    var chain = Promise.resolve({ ok: true, j: {} });
    if (href) {
      chain = jpost(href.replace(/\/+$/, '') + '/messages', payload).then(function (res) {
        /* keep the room identity for the copy in our own store */
        if (res.ok && res.j && res.j.row && res.j.row.id) stamp.id = res.j.row.id;
        return res;
      });
    }
    chain.then(function (res) {
      if (href && !res.ok) {
        status(res.status === 429 ? 'Slow down' : 'Relay rejected', 'err');
        if (window.sfx) sfx.play('warn');
        if (res.j && res.j.row) { /* keep nothing on a rejected relay post */ } else { return null; }
      }
      return jpost('/api/chat', { text: text.slice(0, MAXLEN), who: stamp });
    }).then(function (res) {
      if (res && res.ok && res.j && res.j.row) {
        merge([res.j.row]);
        render();
        if (window.sfx) sfx.play('soft');
      } else if (res && res.status === 429) {
        status('Slow down', 'err');
      }
    }).catch(function () {
      status('Send failed', 'err');
    }).then(function () { busy = false; });
  }

  function tick() {
    if (document.hidden) return;
    var view = document.getElementById('view-home');
    if (!view) return;
    if (view.hidden) return;                      /* HOME only: no polling while another view is up */
    if (!build()) return;
    fit();
    if (!open) return;                            /* closed: nothing renders, so nothing to poll */
    pullLocal().then(pullRelay);
  }

  function boot() {
    if (!build()) return;
    fit();
    tick();
    if (timer) clearInterval(timer);
    timer = setInterval(tick, POLL);
    document.addEventListener('visibilitychange', function () { if (!document.hidden) tick(); });
    /* the header grows when the sync status lands and when the chips wrap (measured: 23px at
       1600w), so the rail is re-measured a few times while the page settles */
    [0, 400, 1200, 3000].forEach(function (ms) { setTimeout(fit, ms); });
    window.addEventListener('load', fit);
    if (!window.wfmChatFitResize) {
      window.wfmChatFitResize = true;
      var t = null;
      window.addEventListener('resize', function () {
        clearTimeout(t);
        t = setTimeout(fit, 150);
      });
    }
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
  window.wfmChatBoot = boot;                       /* the HOME renderer can re-dock after a rebuild */
  window.wfmChatOpen = function (v) { setOpen(v); };   /* tests / QA drive the same one toggle */
})();
