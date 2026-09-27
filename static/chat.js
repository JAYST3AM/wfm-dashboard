/* WFM Trader - CHAT dock (right of HOME).
   Jay (2026-09-27): "add a chat that snaps to the right of the home page. look into getting it so
   other people can chat with their profiles active."

   Local-first: every message is stored by the dashboard itself (POST /api/chat -> data/chat.json),
   so the panel works with no relay, no account and no keys. When a relay URL is configured
   (GET /api/chat -> relay, set via chat_relay_url in config), messages are also posted to that
   room and the room history is pulled back, which is what lets other dashboards share
   the same chat. Each message carries a profile stamp (name, MR, platform) taken from the local
   save - the chip shows exactly what is sent.

   Layout: this file owns #chatDock and its own placement, so no edit is needed inside
   app.js/index.html. On first load it wraps the existing HOME cards in #homeMain and appends the
   dock beside them; #view-home.chat-docked is a 2-column grid at >=1500px (360px rail), a 300px
   rail at 1200-1499px, and a normal block below the cards under 1200px. Styling is in chat.css,
   colours come from the palette vars, sounds from window.sfx (no-op when absent).

   Plain browser JS, no libraries, no build step. DOM via createElement/textContent only. */
(function () {
  'use strict';
  var POLL = 5000;          /* local poll: cheap, one request per tick, paused when hidden */
  var RELAY_POLL = 5000;
  var MAXLEN = 500;

  var href = '', rows = [], seen = {}, lastId = 0, relayCursor = 0, me = {}, timer = null, busy = false;

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

  /* ---------------------------------------------------------------- build */

  function build() {
    var view = document.getElementById('view-home');
    if (!view) return false;
    var dock = document.getElementById('chatDock');
    if (dock && dock.isConnected) return true;

    /* wrap the existing HOME cards once (never twice), then dock beside them */
    var main = document.getElementById('homeMain');
    if (!main) {
      main = el('div');
      main.id = 'homeMain';
      while (view.firstChild) main.appendChild(view.firstChild);
      view.appendChild(main);
      view.classList.add('chat-docked');
    }

    dock = el('aside', 'card');
    dock.id = 'chatDock';

    var head = el('div', 'card-head');
    var title = el('div', 'card-title', 'Chat');
    title.setAttribute('data-icon', 'chats');
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
    if (atBottom) list.scrollTop = list.scrollHeight;
  }

  function status(text, kind) {
    var s = document.getElementById('chatState');
    if (!s) return;
    s.textContent = text;
    s.className = 'chip ' + (kind === 'live' ? 'act-show' : (kind === 'err' ? 'act-offline' : ''));
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
    pullLocal().then(pullRelay);
  }

  function boot() {
    if (!build()) return;
    tick();
    if (timer) clearInterval(timer);
    timer = setInterval(tick, POLL);
    document.addEventListener('visibilitychange', function () { if (!document.hidden) tick(); });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
  window.wfmChatBoot = boot;                       /* the HOME renderer can re-dock after a rebuild */
})();
