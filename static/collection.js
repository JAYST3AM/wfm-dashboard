/* collection.js - Warframe collection log (no frameworks, no external libs)
   Data: data/collection_log.json written by scripts/collection_log.py, served as
         /collection_log.json (static copy), /api/feature/collection or /data/collection_log.json.
         Plus data/relics_panel.json written by scripts/relics_panel.py and served as
         /relics_panel.json - the relic store behind the Relics section.
         Plus data/mastery.json served read-only as /api/feature/mastery - the Mastery helper,
         which moved off the dashboard's rail into this page in stage 2 (2026-09-28).
   Sections: the section row inside the page head is Collection | Relics | Mastery | Cards. The
   first three are sections of THIS page (hash-routed: /collection.html#relics,
   /collection.html#mastery, #collection for the item log) and exactly one is visible under the
   head at a time; Cards is still its own page. The head itself (title + the log's counts + the
   progress hairline + the row) always shows.
   Renders ONE category tab at a time (the log can hold ~800 items - only the active tab is
   built into the DOM), with an overall completion bar, search and missing/buyable filters.
   All injected strings are escaped/created as text nodes; no innerHTML with data
   (the Mastery rows are the one exception: every value goes through escHtml() first). */
/* Icons: static/icons.js turns every data-icon host into an inline <svg> from the self-hosted
   Phosphor sprite (no CDN, no build step). This file references data-icon="tag" (a missing
   tile's price mark), data-icon="tray" (empty state, and the Relics tab), data-icon="caret-down"
   (the relic table's active sort column), data-icon="arrow-square-out" (the card's wiki line),
   data-icon="check-circle-fill" / "circle-notch" (the card's state mark) and - on a relic card -
   data-icon="drop-fill" / "lock" / "question" for a dropping / vaulted / placeholder relic; the
   category tab names are in TAB_ICONS below. All names are pinned in tools/build_icons.py, so
   `python tools/build_icons.py --check` verifies them. */
'use strict';
(function () {
  var SOURCES = ['/collection_log.json', '/api/feature/collection', '/data/collection_log.json'];
  // Deep links out of this page go to the dashboard's global search route; the standalone
  // Lookup page is discontinued, so '/#search?q=<name>' is the single item destination.
  var SEARCH = '/#search?q=';
  var RUN_CMD = 'python scripts/collection_log.py';
  // The relic store (data/relics_panel.json, written by scripts/relics_panel.py) - every relic in
  // the game with its drop lines, its six rewards per refinement and the account's own counts.
  var RELIC_SRC = '/relics_panel.json';
  var REL_REFS = ['Intact', 'Exceptional', 'Flawless', 'Radiant'];
  var REF_1 = { Intact: 'I', Exceptional: 'E', Flawless: 'F', Radiant: 'R' };
  var TIER_ORDER = ['Lith', 'Meso', 'Neo', 'Axi', 'Requiem', 'Vanguard', 'Void'];
  var REL_LINES = 6;                       // drop lanes the hover card lists before 'showing x of y'
  var REL_FILTERS = [
    { key: 'all', label: 'All' },
    { key: 'drop', label: 'Dropping now' },
    { key: 'owned', label: 'Owned' },
    { key: 'vaulted', label: 'Vaulted' }
  ];
  /* Columns in render order. key '' is a value/picture column, not a sort key - the same
     convention style.css already gives `thead th:not([data-k])` (default cursor, no sorting). */
  var REL_COLS = [
    { key: 'name', label: 'Relic' },
    { key: 'tier', label: 'Tier' },
    { key: '', label: 'State' },
    { key: 'owned', label: 'Owned' },
    { key: '', label: 'Best reward' },
    { key: 'ev', label: 'EV', cls: 'num' },
    { key: '', label: 'Where' }
  ];

  var state = {
    doc: null, cat: 0, q: '', missingOnly: false, buyable: false, src: '',
    /* the Relics tab: one store (state.relics, fetched once and cached), its own view/filter/sort */
    relics: null, relErr: false, relCounts: null,
    view: 'items', relFilter: 'all', relSort: 'name', relDir: 1,
    /* the Mastery section (moved here from the dashboard, stage 2): one cached payload + filter */
    mastery: null, mhReq: null, mhFilter: 'all'
  };

  // ---------- helpers ----------
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = String(text);
    return n;
  }

  /* copy diet: a wiki-length data line is clipped to the 8-word budget and the caller keeps the
     full text in the element's title. Trailing filler words go first. */
  function clipWords(s, maxWords) {
    var w = String(s == null ? '' : s).trim().split(/\s+/).filter(Boolean);
    if (w.length <= maxWords) return w.join(' ');
    var stop = /^(a|an|the|of|in|to|for|and|or|by|with|from|can|be|is|it|at|on)$/i;
    var n = maxWords;
    while (n > 1 && stop.test(w[n - 1])) n--;    /* trailing filler words go first */
    return w.slice(0, n).join(' ') + '\u2026';
  }

  /* a drop label can arrive as a long wiki-style string (place + level band + mission, then the
     rotation). The cell shows the place + rotation; the bracket detail stays in the title (set by
     the caller), so nothing is lost. */
  function dropLabel(lbl) {
    var s = String(lbl == null ? '' : lbl);
    if (s.split(/\s+/).filter(Boolean).length <= 8 && s.length <= 90) return s;
    var cut = s.replace(/\s*\([^)]*\)/, ' ').replace(/\s+/g, ' ').replace(/\s+,/g, ',').trim();
    return clipWords(cut, 8);
  }

  function fmtInt(v) {
    var n = Number(v);
    return isFinite(n) ? String(Math.round(n)) : '—';
  }

  function pctText(v) {
    var n = Number(v);
    if (!isFinite(n)) return '—';
    return (n % 1 === 0 ? String(n) : n.toFixed(1)) + '%';
  }

  function initial(name) {
    var s = String(name || '?').replace(/[^A-Za-z0-9]/g, '');
    return (s.charAt(0) || '?').toUpperCase();
  }

  function isCollected(it) { return !!(it && (it.owned || it.mastered)); }

  // Catalog icon URLs come from the log (WFCD CDN / warframe.market CDN, or the dashboard's own
  // /colimg/ cache written by scripts/icon_cache.py). Whitelist them so a tampered log can never
  // break out of the src attribute, then fall back to a letter tile.
  function safeUrl(u) {
    if (typeof u !== 'string' || !u) return null;
    if (/[\x00-\x1f\x7f"'<>\\\s]/.test(u)) return null;
    if (u.indexOf('/colimg/') === 0) return u;         // own origin: local icon cache, no redirect
    if (u.indexOf('https://') !== 0 && u.indexOf('/') !== 0) return null;
    return u;
  }

  function avatar(it, miss) {
    var d = el('div', 'cl-avatar', initial(it.name));
    d.setAttribute('aria-hidden', 'true');
    if (miss) d.title = 'not collected';
    return d;
  }

  function image(it, miss) {
    // Prefer the dashboard's own cached copy (`icon_local`, /colimg/, served from static/);
    // the remote CDN URL (`icon`) is the fallback, the letter tile the last resort.
    var url = safeUrl(it.icon_local) || safeUrl(it.icon);
    if (!url) return avatar(it, miss);
    var img = el('img', 'cl-thumb');
    img.alt = '';
    img.loading = 'lazy';
    img.decoding = 'async';
    img.referrerPolicy = 'no-referrer';
    img.addEventListener('error', function () {
      var av = avatar(it, miss);
      if (img.parentNode) img.parentNode.replaceChild(av, img);
    });
    img.setAttribute('src', url);
    return img;
  }

  // ---------- card ----------
  function floorLink(it) {
    // Missing + quoted in the local snapshot: show the floor and open the dashboard's
    // global search for the item (name is URL-encoded into the '/#search?q=' route).
    var a = el('a', 'cl-floor');
    a.href = SEARCH + encodeURIComponent(it.name);
    a.setAttribute('data-icon', 'tag');   // the price mark on a missing tile
    a.appendChild(el('span', null, '▲ ' + fmtInt(it.floor) + 'p'));
    a.appendChild(el('span', 'k', it.floor_kind === 'item' ? '' : ' ' + it.floor_kind));
    a.title = 'Lowest sell order in the local snapshot' +
      (it.floor_kind && it.floor_kind !== 'item' ? ' (' + it.name + ' ' + it.floor_kind + ')' : '') +
      ' - open the item search';
    return a;
  }

  function card(it) {
    var got = isCollected(it);
    var c = el('div', 'cl-card ' + (got ? 'got' : 'miss'));
    c.setAttribute('role', 'listitem');
    c._cl = it;                                          // the hover card reads the item off the tile
    if (it.slug) c.setAttribute('data-slug', it.slug);   // the drawer opens on this slug

    c.appendChild(image(it, !got));
    c.appendChild(el('div', 'cl-name', it.name));

    /* the flag row is always there, even when empty: every tile then keeps its name, its flags
       and its price on the same three lines (an empty row is 13px of air, not a layout jump) */
    var flags = el('div', 'cl-flags');
    if (it.mastered) flags.appendChild(el('span', 'cl-flag mastered', 'mastered'));
    if (it.owned) flags.appendChild(el('span', 'cl-flag owned', 'owned'));
    if (it.mastery_req != null && it.mastery_req > 0) {
      flags.appendChild(el('span', 'cl-flag mr', 'MR' + fmtInt(it.mastery_req)));
    }
    c.appendChild(flags);

    if (!got) {
      if (it.floor) c.appendChild(floorLink(it));
      else c.appendChild(el('div', 'cl-noprice', '—'));
    }
    return c;
  }

  // ---------- tabs ----------
  /* One Phosphor mark per category (static/icons.js renders the <svg> from the name; every
     name here is pinned in tools/build_icons.py and listed for its --check pass below).
     Repeats are deliberate: the label carries the meaning, the icon only groups the tab by
     kind of gear - guns, blades, arch gear, drive/amp gear.
       data-icon="user"        Warframes
       data-icon="crosshair"   Primary / Secondary / Sentinel Weapons / Arch-Gun
       data-icon="sword"       Melee / Arch-Melee
       data-icon="robot"       Sentinels          data-icon="bug"       Companions
       data-icon="rocket"      Archwing           data-icon="cube"      Other
       data-icon="lightning"   K-Drives / Amps
     Stage 6: the strip is the item log's own control again (13 categories). Relics used to ride
     here as a 14th tab - it is a section of the page now, reached from the section row, and one
     control per job means the strip never competes with it. */
  var TAB_ICONS = {
    'Warframes': 'user', 'Primary': 'crosshair', 'Secondary': 'crosshair', 'Melee': 'sword',
    'Sentinels': 'robot', 'Sentinel Weapons': 'crosshair', 'Companions': 'bug',
    'Archwing': 'rocket', 'Arch-Gun': 'crosshair', 'Arch-Melee': 'sword',
    'K-Drives': 'lightning', 'Amps': 'lightning', 'Other': 'cube'
  };

  function tabShell(on, mark, label, countText, barPct, title) {
    var t = el('button', 'tab cl-tab' + (on ? ' active' : ''));
    t.type = 'button';
    t.setAttribute('role', 'tab');
    t.setAttribute('aria-selected', on ? 'true' : 'false');
    if (mark) {
      var ic = el('span', 'cl-tab-ico');           // .cl-tab-ico is hidden under 900px
      ic.setAttribute('data-icon', mark);
      t.appendChild(ic);
    }
    t.appendChild(document.createTextNode(label));
    t.appendChild(el('span', 'cl-tab-count', countText));
    var bar = el('span', 'cl-tab-bar');
    var fill = el('i');
    fill.style.width = Number(barPct || 0).toFixed(1) + '%';
    bar.appendChild(fill);
    t.appendChild(bar);
    t.title = title;
    return t;
  }

  function buildTabs() {
    var tabs = document.getElementById('tabs');
    tabs.textContent = '';
    state.doc.categories.forEach(function (cat, i) {
      var on = i === state.cat;
      var t = tabShell(on, TAB_ICONS[cat.name], cat.name, cat.obtained + '/' + cat.total,
        cat.total ? (100 * cat.obtained / cat.total) : 0,
        cat.name + ': ' + cat.obtained + ' of ' + cat.total + ' collected (' +
        pctText(cat.pct) + ')');
      t.addEventListener('click', function () { goSection('collection'); selectCategory(i); });
      tabs.appendChild(t);
    });
  }

  function selectCategory(i) {
    if (i === state.cat && state.view === 'items') return;
    hideMastery();
    state.view = 'items';
    state.cat = i;
    buildTabs();
    showRelicView(false);
    render();
  }

  function selectRelics() {
    if (state.view === 'relics') return;
    hideMastery();
    state.view = 'relics';
    buildTabs();
    showRelicView(true);
    renderRelics();
  }

  /* Whichever view the two toolbars currently point at. The search box, the clear button and the
     tile filters all re-render through here, so #q filters relic names too. */
  function renderActive() {
    if (state.view === 'relics') { renderRelics(); return; }
    render();
  }

  function showRelicView(on) {
    document.getElementById('relicView').classList.toggle('hidden', !on);
    document.getElementById('grid').classList.toggle('hidden', on);
    if (on) document.getElementById('empty').classList.add('hidden');
    var controls = document.querySelector('.cl-controls');
    if (controls) controls.classList.toggle('rel', on);   // the tile filters hide in the relic view
    if (on) dockTip(); else undockTip();                  // the card lives in the table view, or floats
  }

  // ---------- filter + render ----------
  function matches(it, q) {
    if (!q) return true;
    return it.name.toLowerCase().indexOf(q) !== -1 ||
      String(it.slug || '').toLowerCase().indexOf(q) !== -1;
  }

  function visibleItems(cat) {
    var q = state.q.trim().toLowerCase();
    var out = [];
    cat.items.forEach(function (it) {
      var got = isCollected(it);
      if (state.missingOnly && got) return;
      if (state.buyable && (got || !it.floor)) return;
      if (!matches(it, q)) return;
      out.push(it);
    });
    return out;
  }

  /* One muted mark above whatever the empty state says (no matches, empty filter, or no log at
     all) - data-icon="tray", sized by .cl-empty-ico in the page style block. */
  function emptyIcon() {
    var d = el('div', 'cl-empty-ico');
    d.setAttribute('data-icon', 'tray');
    return d;
  }

  function render() {
    if (!state.doc) return;
    var cat = state.doc.categories[state.cat];
    if (!cat) return;
    var shown = visibleItems(cat);
    var grid = document.getElementById('grid');
    var meta = document.getElementById('meta');
    var empty = document.getElementById('empty');
    var clearBtn = document.getElementById('clearBtn');

    var frag = document.createDocumentFragment();
    shown.forEach(function (it) { frag.appendChild(card(it)); });
    grid.textContent = '';
    grid.appendChild(frag);

    var missing = cat.total - cat.obtained;

    meta.textContent = '';
    meta.appendChild(el('b', null, cat.name));
    /* one value per text node: every visible string stays inside the copy budget */
    [cat.obtained + '/' + cat.total + ' collected', missing + ' missing', shown.length + ' shown']
      .forEach(function (s) { meta.appendChild(document.createTextNode(' · ' + s)); });
    if (state.missingOnly || state.buyable || state.q) {
      meta.appendChild(document.createTextNode(' (filtered)'));
    }

    clearBtn.classList.toggle('hidden', !state.q);

    if (!shown.length) {
      empty.textContent = '';
      empty.appendChild(emptyIcon());
      empty.appendChild(el('b', null, 'Nothing found in ' + cat.name));
      empty.classList.remove('hidden');
    } else {
      empty.classList.add('hidden');
    }
  }

  // ---------- relic view (data/relics_panel.json) ----------
  /* Every relic in the game, where it comes from and what it contains - as ONE dense, sortable
     table rather than 805 tiles of the same handful of relic images. The store is fetched once
     (loadRelics) and cached on state.relics; the tab count, the filter pills and the table all
     read that one payload, so nothing here refetches.
     Honesty rules: a vaulted relic never shows a drop location, a placeholder shows its own store
     note, and a refinement with no rewards says so instead of rendering a blank block. */
  function relKind(r) { return (r && r.obtain && r.obtain.kind) || 'unknown'; }

  function stateWord(r) {
    var k = relKind(r);
    return k === 'drop' ? 'dropping' : (k === 'vaulted' ? 'vaulted' : 'unknown');
  }

  function tierRank(t) {
    var i = TIER_ORDER.indexOf(String(t));
    return i === -1 ? TIER_ORDER.length : i;
  }

  /* 'A2' sorts before 'A10': compare digit runs as numbers, everything else as text. */
  function natCmp(a, b) {
    var ra = String(a).match(/\d+|\D+/g) || [];
    var rb = String(b).match(/\d+|\D+/g) || [];
    for (var i = 0; i < Math.max(ra.length, rb.length); i++) {
      if (ra[i] == null) return -1;
      if (rb[i] == null) return 1;
      var na = /^\d+$/.test(ra[i]), nb = /^\d+$/.test(rb[i]);
      if (na && nb) {
        if (Number(ra[i]) !== Number(rb[i])) return Number(ra[i]) - Number(rb[i]);
      } else if (ra[i] !== rb[i]) {
        return ra[i] < rb[i] ? -1 : 1;
      }
    }
    return 0;
  }

  /* Best owned refinement for the account: most copies wins, the store order breaks a tie,
     null when every refinement is at zero. */
  function bestRef(r) {
    var own = r.owned || {}, pick = null, best = 0;
    REL_REFS.forEach(function (ref) {
      var n = Number(own[ref]) || 0;
      if (n > best) { best = n; pick = ref; }
    });
    return pick;
  }

  /* EV column: the owned refinement's own EV when the store has one, else the Intact value, else
     nothing at all - never a guessed number. Returns {ref, ev} or null. */
  function relicEv(r) {
    var ev = r.ev || {};
    var ref = bestRef(r);
    if (ref && ev[ref] && ev[ref].ev != null) return { ref: ref, ev: ev[ref] };
    if (ev.Intact && ev.Intact.ev != null) return { ref: 'Intact', ev: ev.Intact };
    return null;
  }

  function num1(v) {
    var n = Number(v);
    return isFinite(n) ? (n % 1 === 0 ? String(n) : n.toFixed(1)) : '—';
  }

  /* 'I3 R1' - copies per refinement, initials only, empty when the account owns none. */
  function ownedText(r) {
    var own = r.owned || {}, bits = [];
    REL_REFS.forEach(function (ref) {
      var n = Number(own[ref]) || 0;
      if (n > 0) bits.push(REF_1[ref] + n);
    });
    return bits.join(' ');
  }

  /* The four pill counts, counted off the store (the store's own 'farmable' number also counts
     the six placeholder entries, so the tab never prints it as 'dropping now'). */
  function relCounts() {
    var out = { all: 0, drop: 0, owned: 0, vaulted: 0 };
    var rows = state.relics ? state.relics.relics : [];
    rows.forEach(function (r) {
      out.all++;
      var k = relKind(r);
      if (k === 'drop') out.drop++;
      if (k === 'vaulted') out.vaulted++;
      if (Number(r.owned_total) > 0) out.owned++;
    });
    return out;
  }

  function relVisible() {
    var rows = state.relics ? state.relics.relics : [];
    var q = state.q.trim().toLowerCase();
    var f = state.relFilter;
    return rows.filter(function (r) {
      if (f === 'drop' && relKind(r) !== 'drop') return false;
      if (f === 'owned' && !(Number(r.owned_total) > 0)) return false;
      if (f === 'vaulted' && relKind(r) !== 'vaulted') return false;
      return matches(r, q);          // the tile search's own case-insensitive name/slug match
    });
  }

  /* Tier, then A2 before A10 - the fallback ordering for every sort key. */
  function cmpName(a, b) {
    var r = tierRank(a.tier) - tierRank(b.tier);
    return r || natCmp(a.name, b.name);
  }

  /* Sort keys taught in the headers: name (tier, then A2 before A10), tier, owned copies, EV.
     A relic with no EV sinks to the bottom in either direction - it is not a zero. */
  function relSort(a, b) {
    var key = state.relSort, dir = state.relDir, r = 0;
    if (key === 'ev') {
      var va = relicEv(a), vb = relicEv(b);
      if (!va && !vb) r = 0;
      else if (!va) return 1;
      else if (!vb) return -1;
      else r = Number(va.ev.ev) - Number(vb.ev.ev);
      if (r) return r * dir;
    } else if (key === 'owned') {
      r = (Number(a.owned_total) || 0) - (Number(b.owned_total) || 0);
      if (r) return r * dir;
    } else if (key === 'tier') {
      r = tierRank(a.tier) - tierRank(b.tier);
      if (r) return r * dir;
    } else {
      r = cmpName(a, b);
      if (r) return r * dir;
    }
    return cmpName(a, b);
  }

  function relCell(cls, text) {
    var td = el('td', cls || null);
    if (text != null) td.appendChild(document.createTextNode(text));
    return td;
  }

  /* One relic row: name, tier, state, owned copies, best reward, EV, first drop location. The
     detail (every drop lane, the six rewards, the market snapshot) rides in the hover card so a
     row stays one dense line. */
  function relRow(r) {
    var kind = relKind(r);
    var tr = el('tr', 'cl-relrow');
    tr._rel = r;

    var name = relCell('name cl-rname', r.name);
    name.title = r.name;
    tr.appendChild(name);

    var tier = el('td');
    tier.appendChild(el('span', 'cat', r.tier || '—'));
    tr.appendChild(tier);

    var st = el('td');
    st.appendChild(el('span', 'cl-rstate ' + kind, stateWord(r)));
    tr.appendChild(st);

    var owned = relCell('cl-rownd');
    var ot = ownedText(r);
    if (ot) owned.appendChild(document.createTextNode(ot));
    else owned.appendChild(el('span', 'cl-rnone', '—'));
    if (Number(r.owned_total) > 0) owned.title = fmtInt(r.owned_total) + ' copies owned';
    tr.appendChild(owned);

    var best = relCell('cl-rbest');
    var br = r.best_reward;
    if (br) {
      var bn = el('span', 'cl-rbitem', br.item);
      bn.title = br.item;
      best.appendChild(bn);
      best.appendChild(el('span', 'cl-rrare', br.rarity + ' · ' + pctText(br.chance_radiant)));
    } else {
      best.appendChild(el('span', 'cl-rnone', '—'));
    }
    tr.appendChild(best);

    var ev = relCell('num');
    var pick = relicEv(r);
    if (pick) {
      ev.appendChild(document.createTextNode(num1(pick.ev.ev)));
      var mark = el('span', 'cl-rref', REF_1[pick.ref]);
      mark.title = pick.ref + ' EV' + (pick.ev.verdict ? ' · ' + pick.ev.verdict : '');
      ev.appendChild(mark);
    } else {
      ev.appendChild(el('span', 'cl-rnone', '—'));
    }
    tr.appendChild(ev);

    var where = relCell('cl-rwhere');
    if (kind === 'drop') {
      var line = (r.obtain.lines || [])[0];
      var lbl = (line && line.label) || '—';
      var w = el('span', 'cl-rwheretxt', dropLabel(lbl));
      w.title = (line && line.detail) ? lbl + ' · ' + line.detail : lbl;
      where.appendChild(w);
    } else {
      /* no drop location exists for anything but a dropping relic: say which of the two it is
         rather than calling a placeholder vaulted */
      where.appendChild(el('span', 'cl-rnone', kind === 'vaulted' ? 'vaulted' : 'unknown'));
    }
    tr.appendChild(where);
    return tr;
  }

  function syncRelHead() {
    var ths = document.getElementById('relHead').getElementsByTagName('th');
    for (var i = 0; i < ths.length; i++) {
      var th = ths[i];
      var k = th.getAttribute('data-k') || '';
      var on = !!k && k === state.relSort;
      th.classList.toggle('sorted', on);
      var mark = th.getElementsByClassName('cl-rsort')[0];
      if (mark) {
        mark.classList.toggle('on', on);
        mark.classList.toggle('asc', on && state.relDir > 0);
      }
      if (on) th.setAttribute('aria-sort', state.relDir > 0 ? 'ascending' : 'descending');
      else th.removeAttribute('aria-sort');
    }
  }

  /* The thead is built once (the sort mark lives in it) and thereafter only re-marked. */
  function buildRelHead() {
    var head = document.getElementById('relHead');
    if (head.childNodes.length) { syncRelHead(); return; }
    var tr = el('tr');
    REL_COLS.forEach(function (col) {
      var th = el('th', col.cls || null);
      th.setAttribute('scope', 'col');
      th.appendChild(document.createTextNode(col.label));
      if (col.key) {
        th.setAttribute('data-k', col.key);   // style.css keeps th:not([data-k]) on the default cursor
        var mark = el('span', 'cl-rsort');    // the active column shows the caret, asc flips it
        mark.setAttribute('data-icon', 'caret-down');
        th.appendChild(mark);
        th.addEventListener('click', function () {
          if (state.relSort === col.key) state.relDir = -state.relDir;
          else { state.relSort = col.key; state.relDir = 1; }
          renderRelics();
        });
      }
      tr.appendChild(th);
    });
    head.textContent = '';
    head.appendChild(tr);
    syncRelHead();
  }

  function renderRelPills(counts) {
    var box = document.getElementById('relPills');
    box.textContent = '';
    if (!state.relics) return;
    REL_FILTERS.forEach(function (f) {
      var b = el('button', 'btn cl-relpill');
      b.type = 'button';
      b.setAttribute('aria-pressed', state.relFilter === f.key ? 'true' : 'false');
      b.appendChild(document.createTextNode(f.label));
      b.appendChild(el('b', null, fmtInt(counts[f.key])));
      b.addEventListener('click', function () {
        if (state.relFilter === f.key) return;
        state.relFilter = f.key;
        renderRelics();
      });
      box.appendChild(b);
    });
  }

  /* The one short line the tab view carries when the store is missing or nothing matches -
     the page's own empty-state look, never a blank table. */
  function relNote(text) {
    var note = document.getElementById('relNote');
    note.textContent = '';
    if (!text) { note.classList.add('hidden'); return; }
    note.appendChild(emptyIcon());
    note.appendChild(el('b', null, text));
    note.classList.remove('hidden');
  }

  function renderRelics() {
    var meta = document.getElementById('meta');
    var body = document.getElementById('relBody');
    var counts = state.relCounts || { all: 0, drop: 0, owned: 0, vaulted: 0 };

    if (!state.relics) {
      document.getElementById('relPills').textContent = '';
      document.getElementById('relHead').textContent = '';
      body.textContent = '';
      meta.textContent = '';
      relNote(state.relErr ? 'relic store not built' : 'loading relic store…');
      return;
    }

    renderRelPills(counts);
    buildRelHead();

    var rows = relVisible();
    rows.sort(relSort);
    var frag = document.createDocumentFragment();
    rows.forEach(function (r) { frag.appendChild(relRow(r)); });
    body.textContent = '';
    body.appendChild(frag);
    relNote(rows.length ? '' : (state.q.trim() || state.relFilter !== 'all'
      ? 'no relics match' : 'relic store is empty'));
    dockFirst();                              // the dock follows the table: first row by default

    meta.textContent = '';
    meta.appendChild(el('b', null, 'Relics'));
    /* one value per text node: every visible string stays inside the copy budget */
    [counts.owned + '/' + counts.all + ' owned', counts.drop + ' dropping now', rows.length + ' shown']
      .forEach(function (s) { meta.appendChild(document.createTextNode(' · ' + s)); });
    if (state.q || state.relFilter !== 'all') meta.appendChild(document.createTextNode(' (filtered)'));
  }

  // ---------- header / overall ----------
  function paintSummary() {
    var doc = state.doc;
    var ov = doc.overall || {};
    document.getElementById('ovPct').textContent = pctText(ov.pct);
    document.getElementById('ovCount').textContent = fmtInt(ov.obtained) + ' / ' + fmtInt(ov.total) +
      ' collected';
    document.getElementById('ovBar').style.width = Math.max(0, Math.min(100, Number(ov.pct) || 0)) + '%';

    /* the head's own counts: label + value, and the same words the mastery cards use. They are
       exclusive buckets ("not owned" / "not mastered"), so an item that is both is in neither and
       the four numbers never have to add up to the total. */
    var foot = document.getElementById('ovFoot');
    foot.textContent = '';
    var bits = [
      ['mastered, not owned', fmtInt(ov.mastered_only)],
      ['owned, not mastered', fmtInt(ov.owned_only)],
      ['missing', fmtInt(ov.missing)],
      ['buyable', fmtInt(ov.missing_with_price)]
    ];
    bits.forEach(function (pair) {
      var s = el('span');
      s.appendChild(el('b', null, pair[1]));
      s.appendChild(document.createTextNode(' ' + pair[0]));
      foot.appendChild(s);
    });

    var chips = document.getElementById('chips');
    chips.textContent = '';
    var c1 = el('span', 'chip');
    c1.appendChild(el('b', null, fmtInt(ov.obtained) + '/' + fmtInt(ov.total)));
    c1.appendChild(document.createTextNode(' collected'));
    chips.appendChild(c1);
    var c2 = el('span', 'chip');
    c2.appendChild(el('b', null, fmtInt(doc.categories.length)));
    c2.appendChild(document.createTextNode(' categories'));
    chips.appendChild(c2);
    var c3 = el('span', 'chip');
    c3.appendChild(el('b', null, fmtInt(ov.missing)));
    c3.appendChild(document.createTextNode(' missing'));
    chips.appendChild(c3);
    if (ov.missing_with_price) {
      var c4 = el('span', 'chip warn');
      c4.appendChild(el('b', null, fmtInt(ov.missing_with_price)));
      c4.appendChild(document.createTextNode(' buyable'));
      chips.appendChild(c4);
    }
    var src = doc.sources || {};
    if (src.catalog_partial || !src.save_xpinfo_count) {
      var warn = el('span', 'chip warn');
      warn.appendChild(el('b', null, src.catalog_partial ? 'catalog partial' : 'no mastery data'));
      chips.appendChild(warn);
    }
  }

  function paintSource() {
    var src = (state.doc && state.doc.sources) || {};
    var line = document.getElementById('srcLine');
    line.textContent = '';
    line.appendChild(document.createTextNode('Collection log ' + (state.doc.generated_iso || '') +
      ' · mastery list ' + fmtInt(src.save_xpinfo_count) + ' (' + (src.save_source || 'none') + ')'));
    var link = el('a', null, state.src);
    link.href = state.src;
    line.appendChild(document.createTextNode(' · served from '));
    line.appendChild(link);
    line.appendChild(document.createTextNode(' · builder: ' + RUN_CMD));
  }

  // ---------- load ----------
  function trySource(i) {
    if (i >= SOURCES.length) {
      fail(null);
      return;
    }
    var url = SOURCES[i];
    fetch(url, { cache: 'no-cache' }).then(function (r) {
      if (!r.ok) throw new Error(url + ' ' + r.status);
      return r.json();
    }).then(function (json) {
      if (!json || !Array.isArray(json.categories) || !json.overall) {
        throw new Error(url + ': not a collection log');
      }
      state.doc = json;
      state.src = url;
      start();
    }).catch(function () { trySource(i + 1); });
  }

  function fail(err) {
    var meta = document.getElementById('meta');
    var empty = document.getElementById('empty');
    document.getElementById('ovPct').textContent = '—';
    document.getElementById('ovCount').textContent = 'no collection log loaded';
    meta.textContent = 'Could not load the collection log' + (err ? ' (' + err + ')' : '') + '.';
    empty.textContent = '';
    empty.appendChild(emptyIcon());
    empty.appendChild(el('b', null, 'No collection_log.json available.'));
    var line = el('div');
    line.appendChild(document.createTextNode('Build it with '));
    line.appendChild(el('code', null, RUN_CMD));
    empty.appendChild(line);
    empty.classList.remove('hidden');
    document.getElementById('tabs').textContent = '';
    document.getElementById('grid').textContent = '';
  }

  function start() {
    paintSummary();
    paintSource();
    buildTabs();
    render();
    paintNav(sectionFromHash());      // #mastery / #relics deep links open their section
  }

  /* ---------- sections: Collection | Relics | Mastery ----------
     Stage 2 (2026-09-28) moved the Mastery helper out of the dashboard's rail and into this page.
     The row under the pill bar (Collection | Relics | Mastery | Cards) is the page's own section
     nav: the first three are sections of THIS page (hash-routed, deep-linkable), Cards is still
     its own page. Exactly one section is visible at a time - the category tab strip (with Relics
     as its last tab) stays the Collection section's own control. */
  function sectionFromHash() {
    var raw = String(location.hash || '').replace(/^#/, '').split('?')[0].split('/')[0];
    return raw === 'relics' ? 'relics' : (raw === 'mastery' ? 'mastery' : 'collection');
  }

  function paintNav(sec) {
    var nav = document.getElementById('collectionNav');
    if (!nav) return;
    var pills = nav.querySelectorAll('.navpill');
    for (var i = 0; i < pills.length; i++) {
      var on = pills[i].getAttribute('data-v') === sec;
      pills[i].classList.toggle('active', on);
      if (on) pills[i].setAttribute('aria-current', 'page');
      else pills[i].removeAttribute('aria-current');
    }
  }

  function hideMastery() {
    var mh = document.getElementById('view-mastery');
    if (mh) mh.classList.add('hidden');
    var controls = document.querySelector('.cl-controls');
    if (controls) controls.classList.remove('mh');
    var tabs = document.getElementById('tabs');
    if (tabs) tabs.classList.remove('hidden');
    var meta = document.getElementById('meta');
    if (meta) meta.classList.remove('hidden');
  }

  /* one visible section under the head: the item grid (its toolbar + tab strip), the relic table,
     or Mastery. The head itself - title, counts, the section row - always shows. */
  function showSection(name) {
    hideMastery();
    var on = (name === 'relics' || name === 'mastery') ? name : 'collection';
    var tabs = document.getElementById('tabs');
    if (on === 'mastery') {
      state.view = 'mastery';
      showRelicView(false);
      document.getElementById('grid').classList.add('hidden');
      document.getElementById('empty').classList.add('hidden');
      var controls = document.querySelector('.cl-controls');
      if (controls) controls.classList.add('mh');       // the search/tile filters are the grid's
      if (tabs) tabs.classList.add('hidden');
      document.getElementById('meta').classList.add('hidden');
      var mh = document.getElementById('view-mastery');
      if (mh) mh.classList.remove('hidden');
      renderMasteryPage();
    } else if (on === 'relics') {
      selectRelics();
      if (tabs) tabs.classList.add('hidden');   // the category strip belongs to the item grid
    } else {
      selectCategory(state.cat);
      if (tabs) tabs.classList.remove('hidden');
    }
    searchCopy(on);
    paintNav(on);
  }

  /* The one search box follows the section it filters: the item log's own categories, or the
     relic store's names (the box has always filtered both - only the label was fixed). */
  function searchCopy(on) {
    var q = document.getElementById('q');
    if (!q) return;
    q.placeholder = on === 'relics' ? 'Search relics…' : 'Search this category…';
    q.setAttribute('aria-label', on === 'relics' ? 'Search relics' : 'Search collection items');
  }

  /* a user action: write the hash and let the hashchange route - so #relics / #mastery are
     deep-linkable and the back button walks the sections */
  function goSection(name) {
    var want = name === 'collection' ? '#collection' : '#' + name;
    if (location.hash === want) showSection(name);
    else location.hash = want;
  }

  /* ---------- Mastery helper (moved here from static/app.js, stage 2) ----------
     What to master next, what it costs, how far the next rank is. The store ships already ranked
     (owned-not-mastered first, then craftable cheapest first, MR-gated last), so next[] renders
     in the store's own order - never re-sorted. The rank bar is NOT renderable as a percentage:
     the save's item-derived mastery sits below the MR 22 cumulative floor (1,210,000) because
     star chart / junction / Intrinsics mastery is not in the save file - mr.pct (0.0) is a floor,
     not the truth - so the header prints the rank, the gap and a tooltip, and no bar. */
  var MASTERY_SRC = '/api/feature/mastery';
  var MH_NOTE = 'items only';
  var MH_NOTE_TITLE = 'save data: items only, no star chart';
  var MH_ROWS = 60;
  var MH_FILTERS = [
    ['all', 'All', function () { return true; }],
    ['craft', 'Ready to build', function (r) {
      return !!(r.build && r.build.verdict === 'CRAFT' && !(r.build.missing_parts || []).length);
    }],
    ['owned', 'Owned, not mastered', function (r) { return r.state === 'owned'; }],
    ['missing', 'Missing', function (r) { return r.state === 'missing'; }]
  ];

  function pnum(v) {
    if (v === null || v === undefined || v === '') return '—';
    var n = typeof v === 'number' ? v : Number(v);
    return Number.isFinite(n) ? n.toLocaleString() : '—';
  }

  function ago(ts) {
    if (!ts) return '—';
    var s = Math.max(0, Math.floor(Date.now() / 1000 - ts));
    if (s < 90) return s + 's ago';
    if (s < 5400) return Math.round(s / 60) + 'm ago';
    return Math.round(s / 3600) + 'h ago';
  }

  function escHtml(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function mhEmpty(text) {
    return '<div class="empty"><span class="empty-icon" data-icon="tray" data-icon-size="18">' +
      '</span>' + escHtml(text) + '</div>';
  }

  /* one fetch, cached - opening the section again never refetches */
  function loadMastery() {
    if (state.mastery) return Promise.resolve(state.mastery);
    if (!state.mhReq) {
      state.mhReq = fetch(MASTERY_SRC).then(function (r) { return r.json(); })
        .then(function (j) { return (j && typeof j === 'object' && !Array.isArray(j)) ? j : {}; })
        .catch(function () { return {}; });
    }
    return state.mhReq.then(function (j) { state.mastery = j; return j; });
  }

  function renderMasteryPage() {
    loadMastery().then(function (M) {
      var ok = !!(M.mr && M.summary && Array.isArray(M.next));
      ['mhNextCard', 'mhCatsCard'].forEach(function (id) {
        var el2 = document.getElementById(id);
        if (el2) el2.classList.toggle('hidden', !ok);
      });
      renderMasteryHead(M, ok);
      if (ok) { renderMasteryNext(M); renderMasteryCats(M); }
    });
  }

  function renderMasteryHead(M, ok) {
    var head = document.getElementById('mhHead');
    if (!head) return;
    var meta = document.getElementById('mhMeta'), stats = document.getElementById('mhStats');
    if (!ok) {
      head.innerHTML = mhEmpty('No mastery data yet — run scripts/mastery.py');
      if (stats) stats.innerHTML = '';
      if (meta) { meta.textContent = ''; meta.title = ''; }
      return;
    }
    var mr = M.mr || {}, s = M.summary || {};
    if (meta) {
      meta.textContent = M.updated ? '· synced ' + ago(M.updated) : '';
      meta.title = 'live save XP + the collection log + craft verdicts';
    }
    head.innerHTML =
      '<div class="pc-id">' +
        '<span class="pc-alias">Mastery ' + pnum(mr.rank) + '</span>' +
        '<span class="mh-gap" title="XP still needed for the next rank">to ' + pnum(mr.next_rank) +
          ': ' + pnum(mr.xp_for_next) + ' XP</span>' +
        '<span class="pc-mr"><span class="pc-mr-l">Item mastery</span><span class="pc-mr-v">' +
          pnum(mr.xp_total) + '</span></span>' +
      '</div>' +
      '<div class="mh-note dim small" title="' + escHtml(MH_NOTE_TITLE) + '">' +
        escHtml(MH_NOTE) + '</div>';
    if (stats) stats.innerHTML =
      '<div class="kpi" title="mastered of the tracked masterable items"><div class="k-label">Mastered</div>' +
        '<div class="k-val">' + pnum(s.mastered) + '<span class="dim"> / ' + pnum(s.tracked) + '</span></div></div>' +
      '<div class="kpi"><div class="k-label">Buildable now</div><div class="k-val">' +
        pnum(s.buildable_now) + '</div></div>' +
      '<div class="kpi"><div class="k-label">Owned, not mastered</div><div class="k-val">' +
        pnum(s.owned_unmastered) + '</div></div>' +
      '<div class="kpi"><div class="k-label">Missing</div><div class="k-val">' +
        pnum(s.missing) + '</div></div>';
  }

  function mhCatNames(M) {
    var map = {};
    (M.categories || []).forEach(function (c) { map[c.key] = c.name || c.key; });
    return map;
  }

  function mhPretty(s) { return String(s || '').replace(/_/g, ' '); }

  function renderMasteryNext(M) {
    var el2 = document.getElementById('mhNext');
    if (!el2) return;
    var all = Array.isArray(M.next) ? M.next : [];
    var cats = mhCatNames(M);
    var pick = MH_FILTERS.filter(function (f) { return f[0] === state.mhFilter; })[0] || MH_FILTERS[0];
    var rows = all.filter(pick[2]);
    var shown = rows.slice(0, MH_ROWS);
    var filters = document.getElementById('mhFilters');
    if (filters) filters.innerHTML = MH_FILTERS.map(function (f) {
      return '<button data-f="' + f[0] + '" aria-pressed="' + (f[0] === pick[0]) + '"' +
        (f[0] === pick[0] ? ' class="active"' : '') + '>' + f[1] +
        ' <b>' + all.filter(f[2]).length + '</b></button>';
    }).join('');
    var meta = document.getElementById('mhNextMeta');
    if (meta) meta.textContent = all.length ? '· ' + all.length : '';
    var cap = document.getElementById('mhCap');
    if (cap) cap.textContent = rows.length ? 'showing ' + shown.length + ' of ' + rows.length : '';
    var head = '<div class="mh-row mh-head"><span>Name</span><span>Type</span><span>State</span>' +
      '<span class="num">XP</span><span class="num">Cost</span><span>Where</span></div>';
    el2.innerHTML = shown.length ? head + shown.map(function (r) {
      var b = r.build || null, ob = r.obtain || null;
      var priced = b && b.cost !== null && b.cost !== undefined;
      return '<div class="mh-row" data-slug="' + escHtml(r.slug) + '" title="Click for the full item view">' +
        '<span class="d-name" title="' + escHtml(r.name) + '">' + escHtml(r.name) + '</span>' +
        '<span class="dim">' + escHtml(cats[r.category] || mhPretty(r.category)) + '</span>' +
        '<span><span class="chip mh-st-' + escHtml(r.state || 'missing') + '">' +
          escHtml(r.state || '—') + '</span></span>' +
        '<span class="num">' + fmtInt(r.xp_value) + '</span>' +
        '<span class="num">' + (priced ? fmtInt(b.cost) + 'p' : '<span class="dim">—</span>') + '</span>' +
        '<span class="d-name dim" title="' + escHtml(ob ? (ob.text || ob.short || '') : '') + '">' +
          escHtml(ob ? clipWords(ob.short || ob.text || '—', 8) : '—') + '</span>' +
      '</div>';
    }).join('') : mhEmpty('Nothing in this filter.');
  }

  function renderMasteryCats(M) {
    var el2 = document.getElementById('mhCats');
    if (!el2) return;
    var cats = Array.isArray(M.categories) ? M.categories : [];
    var meta = document.getElementById('mhCatsMeta');
    if (meta) meta.textContent = cats.length ? '· ' + cats.length + ' types' : '';
    el2.innerHTML = cats.length ? cats.map(function (c) {
      var pct = Number(c.pct) || 0;
      return '<div class="mh-cat">' +
        '<span class="d-name" title="' + escHtml(c.name || c.key) + '">' +
          escHtml(c.name || c.key) + '</span>' +
        '<span class="num">' + pnum(c.mastered) + '/' + pnum(c.total) + '</span>' +
        '<span class="pc-bar" title="' + pct + '% of this type mastered">' +
          '<i style="width:' + pct + '%"></i></span>' +
      '</div>';
    }).join('') : mhEmpty('No types yet.');
  }

  /* filters re-render the window from the cached payload; a row opens the shared drawer */
  function wireMastery() {
    var filters = document.getElementById('mhFilters');
    if (filters) filters.addEventListener('click', function (e) {
      var b = e.target.closest ? e.target.closest('button[data-f]') : null;
      if (!b) return;
      state.mhFilter = b.getAttribute('data-f');
      renderMasteryNext(state.mastery || {});
    });
    var next = document.getElementById('mhNext');
    if (next) next.addEventListener('click', function (e) {
      var row = e.target.closest ? e.target.closest('.mh-row[data-slug]') : null;
      if (row && row.getAttribute('data-slug') && window.wfmOpenItem) {
        window.wfmOpenItem(row.getAttribute('data-slug'));
      }
    });
  }

  /* The relic store: one fetch for the whole section (805 relics, ~2.9 MB) cached on
     state.relics - the pills, the meta line, the table and every hover card read that one
     payload. A 404 / a half-written store leaves state.relErr set and the section shows one short
     line instead; the item log is untouched either way. */
  function loadRelics() {
    fetch(RELIC_SRC, { cache: 'no-cache' }).then(function (r) {
      if (!r.ok) throw new Error(RELIC_SRC + ' ' + r.status);
      return r.json();
    }).then(function (json) {
      if (!json || !Array.isArray(json.relics) || !json.relics.length) {
        throw new Error(RELIC_SRC + ': not a relic store');
      }
      state.relics = json;
      state.relCounts = relCounts();
      if (state.view === 'relics') renderRelics();
    }).catch(function () {
      state.relErr = true;
      if (state.view === 'relics') renderRelics();
    });
  }

  // ---------- wiring ----------
  /* The shared item drawer (drawer.js, defer-loaded) is optional: when it exposes
     window.wfmOpenItem, clicking a collection tile opens the drawer for that slug and the
     tile's own floor link no longer navigates. Without the drawer nothing changes - the
     floor badge stays a plain link to '/#search?q=<name>'. */
  function wireDrawer() {
    var grid = document.getElementById('grid');
    if (!grid) return;
    grid.addEventListener('click', function (e) {
      if (typeof window.wfmOpenItem !== 'function') return;
      var t = e.target;
      var tile = (t && t.closest) ? t.closest('.cl-card') : null;
      var slug = tile && tile.getAttribute('data-slug');
      if (!slug) return;
      e.preventDefault();
      window.wfmOpenItem(slug);
    });
  }

  /* ---------- how-to-obtain hover card ----------
     Jay (2026-09-26): "hover over for information on where to get it, and drop chance. and
     mission". Every tile shows a card built from collection_log item.obtain (WFCD drop tables:
     relic / mission / enemy / source, each with the chance) - an item with no record says so
     instead of inventing one. The wiki link inside the card stays clickable, so the card
     outlives the pointer leaving the tile by one beat. */
  var TIP = null;
  function tipEl() {
    if (TIP) return TIP;
    TIP = el('div', 'cl-tip');
    TIP.id = 'clTip';
    TIP.setAttribute('role', 'tooltip');
    document.body.appendChild(TIP);
    return TIP;
  }

  /* The Relics view docks that same card in its own left column (#relDock): sticky, out of the
     pointer's way, and never over the table. The tile grid keeps the floating card. */
  function tipDocked() { return !!TIP && TIP.classList.contains('docked'); }

  function tipPlaceholder() {
    var tip = tipEl();
    tip.textContent = '';
    tip.appendChild(el('div', 'clt-note', 'No relic selected'));
    tip._rel = null; tip._chips = null; tip._list = null; tip._foot = null; tip._for = null;
  }

  function dockTip() {
    var dock = document.getElementById('relDock');
    if (!dock) return;
    var tip = tipEl();
    if (tip.parentNode !== dock) dock.appendChild(tip);
    tip.classList.add('docked');
    /* nothing hovered yet: one short line until the table renders (renderRelics docks its first
       row, so this only shows while the store loads or when nothing matches) */
    if (!tip._rel) tipPlaceholder();
  }

  function undockTip() {
    if (!TIP) return;
    TIP.classList.remove('docked');
    TIP.classList.remove('on');
    if (TIP.parentNode !== document.body) document.body.appendChild(TIP);
    TIP._rel = null; TIP._chips = null; TIP._list = null; TIP._foot = null; TIP._for = null;
    markDockRow(null);
  }

  function tipRow(line) {
    var row = el('div', 'clt-row');
    row.setAttribute('data-k', line.k || '');
    if (line.text) {
      /* a prose line (wiki acquisition note / added-in update): one labelled paragraph */
      row.className = 'clt-row clt-prose';
      row.appendChild(el('span', 'clt-tag', line.label || 'Source'));
      row.appendChild(el('div', 'clt-text', line.text));
      return row;
    }
    var main = el('span', 'clt-main');
    if (line.part) main.appendChild(el('span', 'clt-part', line.part));
    main.appendChild(el('span', 'clt-src', line.label || ''));
    row.appendChild(main);
    if (line.detail) row.appendChild(el('span', 'clt-chance', line.detail));
    /* A drop row whose node the game's own region data does not describe says so, in the row:
       showing the verified part and naming the unverified one is the whole point. */
    if (line.note) row.appendChild(el('span', 'clt-caveat', line.note));
    return row;
  }

  function fillTip(tile) {
    var tip = tipEl();
    var it = tile._cl;
    tip.textContent = '';
    var got = isCollected(it);
    var head = el('div', 'clt-head');
    head.appendChild(el('span', 'clt-name', it.name));
    /* the state mark reads the same word as before - collected gets the filled tick, missing
       the open ring (data-icon="check-circle-fill" / data-icon="circle-notch") */
    var state = el('span', 'clt-state' + (got ? ' clt-got' : ''), got ? 'collected' : 'missing');
    state.setAttribute('data-icon', got ? 'check-circle-fill' : 'circle-notch');
    head.appendChild(state);
    tip.appendChild(head);
    var o = it.obtain || null;
    var lines = (o && o.lines) || [];
    if (lines.length) {
      var body = el('div', 'clt-body');
      lines.forEach(function (l) { body.appendChild(tipRow(l)); });
      tip.appendChild(body);
      if (o.lanes && o.lanes > lines.length) {
        tip.appendChild(el('div', 'clt-more', 'showing ' + lines.length + ' of ' + o.lanes +
          ' drop lanes'));
      }
    } else {
      tip.appendChild(el('div', 'clt-note', 'No drop-table record'));
    }
    if (o && o.note) tip.appendChild(el('div', 'clt-note', o.note));
    if (o && o.wiki) {
      var wk = el('div', 'clt-wiki', o.wiki.replace('https://', ''));
      wk.setAttribute('data-icon', 'arrow-square-out');   // leaves the page for the wiki
      tip.appendChild(wk);
    }
    tip._for = tile;
    return tip;
  }

  /* ---------- the relic card (one row of the Relics table) ----------
     Same .cl-tip shell as the tiles, three blocks: where it comes from (the store's own obtain
     lines, or its note when there is no drop location), what it contains (the six rewards of ONE
     refinement, switched from the already-loaded store) and the relic's market snapshot when the
     store carries one. Nothing here refetches. Unlike the tile card it is docked in #relDock
     (left column, sticky) while the Relics view is open - see dockTip(). */
  var REL_REF = 'Intact';                  // the refinement the open card lists

  function relRefDefault(r) { return bestRef(r) || 'Intact'; }

  function fillRelicTip(row) {
    var tip = tipEl();
    var r = row._rel;
    var kind = relKind(r);
    tip.textContent = '';
    REL_REF = relRefDefault(r);

    var head = el('div', 'clt-head');
    head.appendChild(el('span', 'clt-name', r.name));
    /* state mark: the drop for a relic that is dropping, the lock for a vaulted one, a question
       for a store placeholder (data-icon="drop-fill" / "lock" / "question") */
    var mark = el('span', 'clt-state' + (kind === 'drop' ? ' clt-drop' : ''), stateWord(r));
    mark.setAttribute('data-icon', kind === 'drop' ? 'drop-fill' : (kind === 'vaulted' ? 'lock' : 'question'));
    head.appendChild(mark);
    tip.appendChild(head);

    tip.appendChild(el('div', 'clt-sect', 'Where to get it'));
    var o = r.obtain || {};
    var lines = o.lines || [];
    if (kind === 'drop' && lines.length) {
      var body = el('div', 'clt-body');
      lines.slice(0, REL_LINES).forEach(function (l) {
        body.appendChild(tipRow({ k: l.k || 'mission', label: l.label, detail: l.detail,
                                  note: l.note }));
      });
      tip.appendChild(body);
      if (lines.length > REL_LINES) {
        tip.appendChild(el('div', 'clt-more', 'showing ' + REL_LINES + ' of ' + lines.length +
          ' drop lanes'));
      }
    } else {
      /* vaulted + placeholder relics carry the store's own note - never a location invented here.
         When the note only repeats the header's state word, say the thing the state means. */
      var note = o.note || 'no drop location in the store';
      if (kind === 'vaulted' && note.toLowerCase() === stateWord(r)) note = 'no active drop';
      tip.appendChild(el('div', 'clt-note', note));
    }

    tip.appendChild(el('div', 'clt-sect', 'What it contains'));
    var refs = el('div', 'clt-refs');
    var chips = [];
    REL_REFS.forEach(function (ref) {
      var b = el('button', 'clt-ref', ref);
      b.type = 'button';
      b.title = ref + ' · ' + fmtInt((r.owned || {})[ref]) + ' owned';
      b.addEventListener('click', function () {
        if (REL_REF === ref) return;
        REL_REF = ref;
        paintRelTip(tip);
      });
      chips.push(b);
      refs.appendChild(b);
    });
    tip.appendChild(refs);
    var list = el('div', 'clt-body');
    tip.appendChild(list);
    var foot = el('div', 'clt-foot');
    tip.appendChild(foot);

    tip._rel = r;
    tip._chips = chips;
    tip._list = list;
    tip._foot = foot;
    paintRelTip(tip);
    tip._for = row;
    return tip;
  }

  /* The reward list + the market line, rebuilt in place when the refinement switches. */
  function paintRelTip(tip) {
    var r = tip._rel;
    var rows = (r.rewards || {})[REL_REF] || [];
    tip._list.textContent = '';
    if (rows.length) {
      rows.forEach(function (rw) {
        tip._list.appendChild(tipRow({
          k: 'relic', label: rw.item, detail: rw.rarity + ' · ' + pctText(rw.chance)
        }));
      });
    } else {
      tip._list.appendChild(el('div', 'clt-note', 'no rewards for ' + REL_REF));
    }
    tip._chips.forEach(function (b, i) {
      b.setAttribute('aria-pressed', REL_REFS[i] === REL_REF ? 'true' : 'false');
    });
    tip._foot.textContent = '';
    var m = r.market;
    if (!m) return;                        // no snapshot for this relic: no line, not a zero
    var rowEl = el('div', 'clt-row');
    rowEl.setAttribute('data-k', 'market');
    var main = el('span', 'clt-main');
    main.appendChild(el('span', 'clt-part', 'market'));
    main.appendChild(el('span', 'clt-src', 'wts ' + num1(m.wts) + ' · wtb ' + num1(m.wtb) +
      ' · median ' + num1(m.median) + 'p'));
    rowEl.appendChild(main);
    var asOf = el('span', 'clt-chance', 'as of ' + String(m.as_of || '').slice(0, 10));
    rowEl.appendChild(asOf);
    tip._foot.appendChild(rowEl);
  }

  /* Rows of the relic table feed the docked card in place: hovering a row refills the card, and
     leaving the table changes nothing - there is nothing to place and nothing to hide. The row
     the card shows carries .sel, so the dock and the table read as one master/detail pair
     instead of a card floating beside a list. */
  function markDockRow(tr) {
    var body = document.getElementById('relBody');
    if (!body) return;
    var rows = body.getElementsByTagName('tr');
    for (var i = 0; i < rows.length; i++) rows[i].classList.toggle('sel', rows[i] === tr);
  }

  function dockRow(tr) {
    if (!tr || !tr._rel) return;
    if (TIP && TIP._for === tr) return;            // same row: the card already shows it
    fillRelicTip(tr).classList.add('on');
    markDockRow(tr);
  }

  /* Nothing hovered yet (or the hovered row just left the filter): the dock shows the first row
     on screen, so the left column is never an empty box. */
  function dockFirst() {
    if (!tipDocked()) return;
    var body = document.getElementById('relBody');
    var rows = body ? body.getElementsByTagName('tr') : [];
    if (!rows.length || !rows[0]._rel) {
      if (TIP && TIP._rel) tipPlaceholder();
      markDockRow(null);
      return;
    }
    dockRow(rows[0]);
  }

  function wireRelicTip() {
    var table = document.getElementById('relTable');
    if (!table) return;
    table.addEventListener('mouseover', function (e) {
      var tr = (e.target && e.target.closest) ? e.target.closest('tr') : null;
      if (!tr || !tr._rel) return;
      dockRow(tr);
    });
  }

  /* Beside the tile, never on top of it: right if it fits, else left, else above/below. */
  function placeTip(tile, tip) {
    var r = tile.getBoundingClientRect();
    var box = tip.getBoundingClientRect();
    var vw = window.innerWidth, vh = window.innerHeight, gap = 10;
    var left, top;
    if (r.right + gap + box.width <= vw - 8) {
      left = r.right + gap;
    } else if (r.left - gap - box.width >= 8) {
      left = r.left - gap - box.width;
    } else {
      left = Math.max(8, Math.min(r.left + (r.width / 2) - (box.width / 2), vw - box.width - 8));
    }
    top = r.top + (r.height / 2) - (box.height / 2);
    top = Math.max(8, Math.min(top, vh - box.height - 8));
    tip.style.top = Math.round(top) + 'px';
    tip.style.left = Math.round(left) + 'px';
  }

  var HIDE_TIMER = null;
  function hideTip(now) {
    if (HIDE_TIMER) { clearTimeout(HIDE_TIMER); HIDE_TIMER = null; }
    var tip = TIP;
    if (!tip) return;
    if (now) { tip.classList.remove('on'); return; }
    HIDE_TIMER = setTimeout(function () { tip.classList.remove('on'); }, 160);
  }

  /* The tile grid's card: filled from the hovered tile and placed beside it. Re-hovering the
     same tile keeps the open card. The Relics table does not use this path - its card is docked. */
  function showTip(tile) {
    if (HIDE_TIMER) { clearTimeout(HIDE_TIMER); HIDE_TIMER = null; }
    var tip = (TIP && TIP._for === tile) ? TIP : fillTip(tile);
    tip.classList.add('on');
    placeTip(tile, tip);
  }

  function wireObtainTip() {
    var grid = document.getElementById('grid');
    function tileOf(node) {
      var tile = (node && node.closest) ? node.closest('.cl-card') : null;
      return (tile && tile._cl) ? tile : null;
    }
    if (grid) {
      grid.addEventListener('mouseover', function (e) { var t = tileOf(e.target); if (t) showTip(t); });
      grid.addEventListener('mouseout', function (e) {
        var t = tileOf(e.target);
        if (!t) return;
        var to = e.relatedTarget;
        if (to && to.closest && to.closest('.cl-card') === t) return;   // still inside the tile
        if (to && to.closest && to.closest('.cl-tip')) return;          // the card's own controls
        hideTip();
      });
      grid.addEventListener('focusin', function (e) { var t = tileOf(e.target); if (t) showTip(t); });
      grid.addEventListener('focusout', function () { hideTip(); });
    }
    document.addEventListener('scroll', function () { if (!tipDocked()) hideTip(true); }, true);
    window.addEventListener('resize', function () { if (!tipDocked()) hideTip(true); });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && !tipDocked()) hideTip(true); });
  }

  /* #themePanel lives inside <header> now (the dashboard's pattern), so scrolling can no
     longer leave it off-screen. theme.js - loaded before this file - already toggles the
     panel and closes it on an outside click; these handlers are registered after it and
     only mirror the state onto the button's ARIA, plus Escape closes the panel. */
  function wireThemePanel() {
    var btn = document.getElementById('themeBtn');
    var panel = document.getElementById('themePanel');
    if (!btn || !panel) return;
    function sync() {
      btn.setAttribute('aria-expanded', panel.classList.contains('hidden') ? 'false' : 'true');
    }
    btn.setAttribute('aria-controls', 'themePanel');
    btn.addEventListener('click', sync);
    document.addEventListener('click', sync);
    document.addEventListener('keydown', function (e) {
      if (e.key !== 'Escape' || panel.classList.contains('hidden')) return;
      panel.classList.add('hidden');
      sync();
    });
    sync();
  }

  function toggleBtn(id, key) {
    var btn = document.getElementById(id);
    btn.addEventListener('click', function () {
      state[key] = !state[key];
      btn.setAttribute('aria-pressed', state[key] ? 'true' : 'false');
      renderActive();
    });
  }

  /* The section row (Collection | Relics | Mastery | Cards): the first three set the hash and the
     hashchange router paints; Cards is a real page, so its pill is left alone. The row is links
     in a nav, so Tab + Enter work with no extra wiring; arrow keys walk it and Home/End jump to
     its ends, which is what a row of tabs is expected to do. */
  function wireSections() {
    var nav = document.getElementById('collectionNav');
    if (nav) nav.addEventListener('click', function (e) {
      var a = (e.target && e.target.closest) ? e.target.closest('.navpill') : null;
      if (!a || !a.getAttribute) return;
      var v = a.getAttribute('data-v');
      if (v !== 'collection' && v !== 'relics' && v !== 'mastery') return;   // Cards: a page
      e.preventDefault();
      goSection(v);
    });
    if (nav) nav.addEventListener('keydown', function (e) {
      if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft' &&
          e.key !== 'Home' && e.key !== 'End') return;
      var pills = nav.querySelectorAll('.navpill');
      if (!pills.length) return;
      var at = 0, i;
      for (i = 0; i < pills.length; i++) { if (pills[i] === document.activeElement) at = i; }
      var next = e.key === 'Home' ? 0
        : (e.key === 'End' ? pills.length - 1
          : (at + (e.key === 'ArrowRight' ? 1 : pills.length - 1)) % pills.length);
      e.preventDefault();
      pills[next].focus();
    });
    window.addEventListener('hashchange', function () { showSection(sectionFromHash()); });
  }

  document.addEventListener('DOMContentLoaded', function () {
    var q = document.getElementById('q');
    q.addEventListener('input', function () { state.q = q.value; renderActive(); });
    document.getElementById('clearBtn').addEventListener('click', function () {
      q.value = ''; state.q = ''; renderActive(); q.focus();
    });
    toggleBtn('missBtn', 'missingOnly');
    toggleBtn('priceBtn', 'buyable');
    wireThemePanel();
    wireDrawer();
    wireObtainTip();
    wireRelicTip();
    wireMastery();
    wireSections();
    showSection(sectionFromHash());     // /collection.html#mastery / #relics open their section

    document.addEventListener('keydown', function (e) {
      if (e.key === '/' && document.activeElement !== q) { e.preventDefault(); q.focus(); return; }
      if (e.key === 'Escape' && document.activeElement === q) {
        q.value = ''; state.q = ''; renderActive(); q.blur();
      }
    });

    trySource(0);
    loadRelics();
  });
})();
