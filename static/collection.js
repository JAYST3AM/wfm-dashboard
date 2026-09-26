/* collection.js - Warframe collection log (no frameworks, no external libs)
   Data: data/collection_log.json written by scripts/collection_log.py, served as
         /collection_log.json (static copy), /api/feature/collection or /data/collection_log.json.
   Renders ONE category tab at a time (the log can hold ~800 items - only the active tab is
   built into the DOM), with an overall completion bar, search and missing/buyable filters.
   All injected strings are escaped/created as text nodes; no innerHTML with data. */
'use strict';
(function () {
  var SOURCES = ['/collection_log.json', '/api/feature/collection', '/data/collection_log.json'];
  // Deep links out of this page go to the dashboard's global search route; the standalone
  // Lookup page is discontinued, so '/#search?q=<name>' is the single item destination.
  var SEARCH = '/#search?q=';
  var RUN_CMD = 'python scripts/collection_log.py';

  var state = { doc: null, cat: 0, q: '', missingOnly: false, buyable: false, src: '' };

  // ---------- helpers ----------
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = String(text);
    return n;
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

  // Catalog icon URLs come from the log (WFCD CDN / warframe.market CDN). Whitelist them so a
  // tampered log can never break out of the src attribute, then fall back to a letter tile.
  function safeUrl(u) {
    if (typeof u !== 'string' || !u) return null;
    if (u.indexOf('https://') !== 0 && u.indexOf('/') !== 0) return null;
    if (/[\x00-\x1f\x7f"'<>\\\s]/.test(u)) return null;
    return u;
  }

  function avatar(it, miss) {
    var d = el('div', 'cl-avatar', initial(it.name));
    d.setAttribute('aria-hidden', 'true');
    if (miss) d.title = 'not collected';
    return d;
  }

  function image(it, miss) {
    var url = safeUrl(it.icon);
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

    var flags = el('div', 'cl-flags');
    if (it.mastered) flags.appendChild(el('span', 'cl-flag mastered', 'mastered'));
    if (it.owned) flags.appendChild(el('span', 'cl-flag owned', 'owned'));
    if (it.mastery_req != null && it.mastery_req > 0) {
      flags.appendChild(el('span', 'cl-flag mr', 'MR' + fmtInt(it.mastery_req)));
    }
    if (flags.childNodes.length) c.appendChild(flags);

    if (!got) {
      if (it.floor) c.appendChild(floorLink(it));
      else c.appendChild(el('div', 'cl-noprice', '—'));
    }
    return c;
  }

  // ---------- tabs ----------
  function buildTabs() {
    var tabs = document.getElementById('tabs');
    tabs.textContent = '';
    state.doc.categories.forEach(function (cat, i) {
      var t = el('button', 'tab cl-tab' + (i === state.cat ? ' active' : ''));
      t.type = 'button';
      t.setAttribute('role', 'tab');
      t.setAttribute('aria-selected', i === state.cat ? 'true' : 'false');
      t.appendChild(document.createTextNode(cat.name));
      t.appendChild(el('span', 'cl-tab-count', cat.obtained + '/' + cat.total));
      var bar = el('span', 'cl-tab-bar');
      var fill = el('i');
      fill.style.width = (cat.total ? (100 * cat.obtained / cat.total) : 0).toFixed(1) + '%';
      bar.appendChild(fill);
      t.appendChild(bar);
      t.title = cat.name + ': ' + cat.obtained + ' of ' + cat.total + ' collected (' +
        pctText(cat.pct) + ')';
      t.addEventListener('click', function () { selectCategory(i); });
      tabs.appendChild(t);
    });
  }

  function selectCategory(i) {
    if (i === state.cat) return;
    state.cat = i;
    buildTabs();
    render();
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
    var buyable = cat.items.filter(function (it) { return !isCollected(it) && it.floor; }).length;

    meta.textContent = '';
    meta.appendChild(el('b', null, cat.name));
    meta.appendChild(document.createTextNode(' · ' + cat.obtained + '/' + cat.total + ' collected (' +
      pctText(cat.pct) + ') · ' + missing + ' missing'));
    if (buyable) meta.appendChild(document.createTextNode(' · ' + buyable + ' with a local price'));
    meta.appendChild(document.createTextNode(' · showing ' + shown.length +
      (shown.length === 1 ? ' item' : ' items')));
    if (state.missingOnly || state.buyable || state.q) {
      meta.appendChild(document.createTextNode(' (filtered)'));
    }

    clearBtn.classList.toggle('hidden', !state.q);

    if (!shown.length) {
      empty.textContent = '';
      var head = el('b', null, state.q
        ? 'Nothing in ' + cat.name + ' matches “' + state.q.trim() + '”.'
        : (state.missingOnly || state.buyable
           ? 'Nothing left to show in ' + cat.name + ' - the filters are empty.'
           : 'Nothing to show in ' + cat.name + '.'));
      empty.appendChild(head);
      var sub = el('div', null, state.buyable
        ? '“Buyable” only lists missing items that have a floor price in this PC’s local WFM snapshot.'
        : 'Clear the search or turn off the toggle to see the whole category.');
      empty.appendChild(sub);
      empty.classList.remove('hidden');
    } else {
      empty.classList.add('hidden');
    }
  }

  // ---------- header / overall ----------
  function paintSummary() {
    var doc = state.doc;
    var ov = doc.overall || {};
    document.getElementById('ovPct').textContent = pctText(ov.pct);
    document.getElementById('ovCount').textContent = fmtInt(ov.obtained) + ' / ' + fmtInt(ov.total) +
      ' obtainable items collected';
    document.getElementById('ovBar').style.width = Math.max(0, Math.min(100, Number(ov.pct) || 0)) + '%';

    var foot = document.getElementById('ovFoot');
    foot.textContent = '';
    var bits = [
      ['mastered only', fmtInt(ov.mastered_only) + (ov.mastered_only === 1 ? ' item' : ' items')],
      ['owned only', fmtInt(ov.owned_only)],
      ['missing', fmtInt(ov.missing)],
      ['missing w/ price', fmtInt(ov.missing_with_price)]
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
    empty.appendChild(el('b', null, 'No collection_log.json available.'));
    var line = el('div');
    line.appendChild(document.createTextNode('Build it with '));
    line.appendChild(el('code', null, RUN_CMD));
    line.appendChild(document.createTextNode(' - that writes data/collection_log.json and a static copy this page can fetch.'));
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

  function tipRow(line) {
    var row = el('div', 'clt-row');
    row.setAttribute('data-k', line.k || '');
    var main = el('span', 'clt-main');
    if (line.part) main.appendChild(el('span', 'clt-part', line.part));
    main.appendChild(el('span', 'clt-src', line.label || ''));
    row.appendChild(main);
    if (line.detail) row.appendChild(el('span', 'clt-chance', line.detail));
    return row;
  }

  function fillTip(tile) {
    var tip = tipEl();
    var it = tile._cl;
    tip.textContent = '';
    var head = el('div', 'clt-head');
    head.appendChild(el('span', 'clt-name', it.name));
    head.appendChild(el('span', 'clt-state', isCollected(it) ? 'collected' : 'missing'));
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
      tip.appendChild(el('div', 'clt-note',
        'No drop-table record for this item - it comes from a quest, vendor or event.'));
    }
    if (o && o.note) tip.appendChild(el('div', 'clt-note', o.note));
    if (o && o.wiki) {
      tip.appendChild(el('div', 'clt-wiki', o.wiki.replace('https://', '')));
    }
    tip._for = tile;
    return tip;
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

  function showTip(tile) {
    if (HIDE_TIMER) { clearTimeout(HIDE_TIMER); HIDE_TIMER = null; }
    var tip = (tipEl()._for === tile) ? tipEl() : fillTip(tile);
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
        hideTip();
      });
      grid.addEventListener('focusin', function (e) { var t = tileOf(e.target); if (t) showTip(t); });
      grid.addEventListener('focusout', function () { hideTip(); });
    }
    document.addEventListener('scroll', function () { hideTip(true); }, true);
    window.addEventListener('resize', function () { hideTip(true); });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape') hideTip(true); });
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
      render();
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    var q = document.getElementById('q');
    q.addEventListener('input', function () { state.q = q.value; render(); });
    document.getElementById('clearBtn').addEventListener('click', function () {
      q.value = ''; state.q = ''; render(); q.focus();
    });
    toggleBtn('missBtn', 'missingOnly');
    toggleBtn('priceBtn', 'buyable');
    wireThemePanel();
    wireDrawer();
    wireObtainTip();

    document.addEventListener('keydown', function (e) {
      if (e.key === '/' && document.activeElement !== q) { e.preventDefault(); q.focus(); return; }
      if (e.key === 'Escape' && document.activeElement === q) {
        q.value = ''; state.q = ''; render(); q.blur();
      }
    });

    trySource(0);
  });
})();
