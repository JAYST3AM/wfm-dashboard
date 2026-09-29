/* planner-library.js - the "what can go in" half of the planner page.
 *
 * #plLibrary's own pieces: the filter chips (#plLibFilters), the sort control (#plLibSort), the
 * search box (#plLibSearch), the count (#plLibCount) and the rows themselves (#plLibList).
 *
 * The rule this file keeps: no Warframe math. Drain ranges, refusal counts and every flag shown
 * here come off the server's library rows (GET /api/planner/mods, handed over as
 * WFMPlanner.library()); the before/after preview is the engine's own answer on /preview - this
 * file only builds the hypothetical build dict and passes it to WFMPlanner.previewNext().
 *
 * Search, sort and the chips class rows on their own payload fields (name, slug, lines, polarity,
 * slot, drain_max, rarity, flags, support counts). Filter state that survives a reload lives in
 * storage.library (q, polarity, slot, sort, hide_refused, hide_installed); the focused-slot
 * filter is transient by design.
 *
 * Icons (pinned in tools/build_icons.py, verified with `python tools/build_icons.py --check`):
 * warning-circle (a row with riders the engine does not calculate), eye (the installed filter),
 * x (clear filters).
 */
'use strict';

(function () {
  var P = window.WFMPlanner;
  if (!P) return;

  var SEARCH_MS = 80;              // the debounce the brief asks for
  var HOVER_MS = 250;              // how long a row must be hovered before the card and preview
  var MAX_FLAGS = 2;               // chips drawn on a row before the '+n' counter
  var MAX_LINES = 3;               // the card's own lines, as the API delivers them
  var LINE_CHARS = 110;            // one display line, hard-clipped so the row stays one line
  var POLARITIES = ['madurai', 'naramon', 'vazarin', 'zenurik', 'penjaga', 'umbra', 'universal'];
  // Rarity is a display key only: the order matches the game's, unknown rarities sort last.
  var RARITY_RANK = { common: 0, uncommon: 1, rare: 2, legendary: 3 };
  var SLOT_CHIPS = [
    { key: '', label: 'All', title: 'Every mod this item accepts' },
    { key: 'normal', label: 'Mods', title: 'Standard mod slots only' },
    { key: 'aura', label: 'Aura', title: 'Aura mods only' },
    { key: 'stance', label: 'Stance', title: 'Stance mods only' },
    { key: 'exilus', label: 'Exilus', title: 'Mods an Exilus slot accepts' }
  ];
  var SORTS = [
    { key: 'name', label: 'Name', title: 'By name, A to Z' },
    { key: 'drain', label: 'Drain', title: 'By maximum drain, highest first' },
    { key: 'rarity', label: 'Rarity', title: 'By rarity, common first' },
    { key: 'flag', label: 'Flag', title: 'Flagged copies first - primed, then umbral' },
    { key: 'catalogue', label: 'Catalogue', title: "The library's own order (as the server sent it)" }
  ];

  var lib = {
    q: '', slot: '', polarity: '', sort: 'name',       // persisted in storage.library
    refusedOnly: false, hideInstalled: false,
    fitsOn: false,                                     // transient: dies with the focused slot
    loading: false,
    rows: [],                                          // the row objects currently drawn, in order
    shown: 0,                                          // how many of them survived the filters
    hl: -1,                                            // index of the keyboard-highlighted row
    tip: null, hoverTimer: null, searchTimer: null, dragging: false
  };

  // ------------------------------------------------------------------ DOM shorthands
  function $(id) { return document.getElementById(id); }
  function el(tag, attrs, kids) { return P.el(tag, attrs, kids); }
  function clear(node) { P.clear(node); }
  function store() { return P.storage(); }
  function libStore() {
    var st = store();
    if (!st.library || typeof st.library !== 'object') st.library = {};
    return st.library;
  }
  function persist() { P.save(); }
  function iconize(node) {
    if (window.wfmIcons && window.wfmIcons.render) window.wfmIcons.render(node);
  }

  // ------------------------------------------------------------------ row vocabulary
  function norm(s) { return String(s === null || s === undefined ? '' : s).toLowerCase(); }
  function slugGuess(name) {
    return norm(name).replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
  }
  function slotName(kind, index) {
    if (kind === 'normal') return 'Slot ' + (Number(index) + 1);
    return P.slotLabel[kind] || kind;
  }
  function flagsOf(row) {
    var flags = (row.flags || []).slice();
    if (row.is_prime && flags.indexOf('prime') < 0) flags.push('prime');
    return flags;
  }
  function drainText(row) {
    var base = row.base_drain, max = row.drain_max;
    if (base === null || base === undefined) {
      return max === null || max === undefined ? '—' : String(max);
    }
    if (max === null || max === undefined || max === base) return String(base);
    return base + ' → ' + max + (row.max_rank === null || row.max_rank === undefined
      ? '' : ' at R' + row.max_rank);
  }
  function drainTitle(row) {
    return "Drain " + drainText(row) + " - the mod's own drain, before the slot polarity is applied";
  }
  function drainKids(row) {
    var base = row.base_drain, max = row.drain_max;
    if (base === null || base === undefined || max === null || max === undefined || max === base) {
      return [drainText(row)];
    }
    return [String(base), el('span', { class: 'at', text: '/' }), String(max)];
  }
  function supportCounts(sup) {
    sup = sup || {};
    var bits = [];
    if (sup.unmodelled) bits.push(sup.unmodelled + ' not calculated');
    if (sup.conditional) bits.push(sup.conditional + ' conditional');
    return bits.join(' · ');
  }
  function clip(text) {
    var s = String(text === null || text === undefined ? '' : text);
    return s.length > LINE_CHARS ? s.slice(0, LINE_CHARS - 1) + '…' : s;
  }

  // ------------------------------------------------------------------ the active config
  // What is installed where, read straight out of storage (keys are 'kind:index', values
  // {id, rank}) - the same slots planner.js builds the /compute payload from.
  function installedMap() {
    var st = store();
    var cfg = (st.configs || {})[st.active_config] || { slots: {} };
    var slots = cfg.slots || {};
    var map = {};
    Object.keys(slots).forEach(function (key) {
      var entry = slots[key];
      if (!entry || !entry.id || map[entry.id]) return;
      var bits = key.split(':');
      map[entry.id] = {
        key: key,
        kind: bits[0],
        index: bits[1] === '-' || bits[1] === undefined ? null : Number(bits[1]),
        rank: entry.rank
      };
    });
    return map;
  }

  // ------------------------------------------------------------------ filter + search + sort
  function prep(row, i) {
    return {
      row: row, i: i,
      name: norm(row.name),
      slug: norm(row.slug),
      guess: slugGuess(row.name),
      lines: norm((row.lines || []).join(' ')),
      rank: 0
    };
  }

  // Ranked search: exact name, then prefix, then a name substring, then the slug, then the card
  // lines; a multi-word query falls back to "every word appears somewhere".
  function matchRank(e, q) {
    if (!q) return 0;
    if (e.name === q) return 0;
    if (e.name.indexOf(q) === 0) return 1;
    if (e.name.indexOf(q) !== -1) return 2;
    if ((e.slug && e.slug.indexOf(q) !== -1) || e.guess.indexOf(q) !== -1) return 3;
    if (e.lines.indexOf(q) !== -1) return 4;
    var words = q.split(/\s+/).filter(Boolean);
    if (words.length > 1) {
      var hay = e.name + ' ' + e.guess + ' ' + e.lines;
      var all = true;
      for (var i = 0; i < words.length; i++) {
        if (hay.indexOf(words[i]) === -1) { all = false; break; }
      }
      if (all) return 5;
    }
    return -1;
  }

  function byName(a, b) {
    if (a.name === b.name) return 0;
    return a.name < b.name ? -1 : 1;
  }
  function byDrain(a, b) {
    var d = (b.row.drain_max === null || b.row.drain_max === undefined ? -1 : b.row.drain_max) -
      (a.row.drain_max === null || a.row.drain_max === undefined ? -1 : a.row.drain_max);
    return d || byName(a, b);
  }
  function rarityRank(row) {
    var key = norm(row.rarity);
    return Object.prototype.hasOwnProperty.call(RARITY_RANK, key) ? RARITY_RANK[key] : 9;
  }
  function byRarity(a, b) {
    var r = rarityRank(a.row) - rarityRank(b.row);
    return r || byName(a, b);
  }
  function byFlag(a, b) {
    return flagRank(a.row) - flagRank(b.row) || byName(a, b);
  }
  function flagRank(row) {
    var flags = flagsOf(row);
    if (flags.indexOf('primed') >= 0 || flags.indexOf('prime') >= 0) return 0;
    if (flags.indexOf('umbral') >= 0 || flags.indexOf('umbra') >= 0) return 1;
    return flags.length ? 2 : 3;
  }
  function baseCmp(key) {
    if (key === 'drain') return byDrain;
    if (key === 'rarity') return byRarity;
    if (key === 'flag') return byFlag;
    if (key === 'catalogue') return function (a, b) { return a.i - b.i; };
    return byName;
  }

  function passes(row, fitsKind, installed) {
    var slot = lib.slot;
    if (slot) {
      if (slot === 'exilus') {
        if (!row.exilus_ok) return false;
      } else if ((row.slot || 'normal') !== slot) {
        return false;
      }
    }
    if (fitsKind && !P.slotLegal(fitsKind, null, row)) return false;   // lock included
    if (lib.polarity && (row.polarity || '') !== lib.polarity) return false;
    if (lib.refusedOnly) {
      var sup = row.support || {};
      if (!(sup.unmodelled || sup.conditional)) return false;
    }
    if (lib.hideInstalled && installed[row.id]) return false;
    return true;
  }

  function visible() {
    var rows = P.library() || [];
    var focus = P.focused();
    var fitsKind = lib.fitsOn && focus ? focus.kind : null;
    var installed = installedMap();
    var out = [];
    for (var i = 0; i < rows.length; i++) {
      if (!passes(rows[i], fitsKind, installed)) continue;
      var e = prep(rows[i], i);
      var rank = matchRank(e, lib.q);
      if (rank < 0) continue;
      e.rank = rank;
      out.push(e);
    }
    var by = baseCmp(lib.sort);
    var ranked = !!lib.q;
    out.sort(function (a, b) {
      if (ranked && a.rank !== b.rank) return a.rank - b.rank;
      return by(a, b) || a.i - b.i;
    });
    return out;
  }

  function filtersOn() {
    return !!(lib.q || lib.slot || lib.polarity || lib.refusedOnly || lib.hideInstalled ||
      (lib.fitsOn && P.focused()));
  }

  function clearFilters() {
    lib.q = '';
    lib.slot = '';
    lib.polarity = '';
    lib.refusedOnly = false;
    lib.hideInstalled = false;
    lib.fitsOn = false;
    var s = libStore();
    s.q = '';
    s.slot = '';
    s.polarity = '';
    s.hide_refused = false;
    s.hide_installed = false;
    var box = $('plLibSearch');
    if (box) box.value = '';
    persist();
    renderAll();
  }

  // ------------------------------------------------------------------ chrome: chips + sort
  function chip(label, on, onClick, opts) {
    opts = opts || {};
    var node = el('button', {
      class: 'pl-chip', type: 'button', 'aria-pressed': on ? 'true' : 'false',
      title: opts.title || null, 'aria-label': opts.ariaLabel || null, 'data-icon': opts.icon || null
    });
    if (opts.dot) node.appendChild(opts.dot);
    node.appendChild(document.createTextNode(label));
    node.addEventListener('click', onClick);
    return node;
  }

  function dotFor(polarity) {
    var dot = P.polDot(polarity, false);
    dot.setAttribute('aria-hidden', 'true');
    dot.removeAttribute('title');
    clear(dot);                        // the chip's own label names the polarity: keep the tint
    return dot;
  }

  function renderFilters() {
    var box = $('plLibFilters');
    if (!box) return;
    clear(box);
    SLOT_CHIPS.forEach(function (c) {
      box.appendChild(chip(c.label, lib.slot === c.key, function () { setSlot(c.key); },
        { title: c.title }));
    });
    var focus = P.focused();
    if (focus) {
      box.appendChild(chip('fits ' + slotName(focus.kind, focus.index), lib.fitsOn,
        function () { setFits(!lib.fitsOn); },
        { title: 'Only mods ' + slotName(focus.kind, focus.index) + ' accepts' }));
    }
    box.appendChild(chip('any polarity', lib.polarity === '', function () { setPolarityFilter(''); },
      { dot: dotFor(null), title: 'Any polarity', ariaLabel: 'Any polarity' }));
    POLARITIES.forEach(function (p) {
      var label = p.charAt(0).toUpperCase() + p.slice(1);
      box.appendChild(chip(label, lib.polarity === p, function () { setPolarityFilter(p); },
        { dot: dotFor(p), title: 'Polarity: ' + p, ariaLabel: 'Polarity ' + p }));
    });
    box.appendChild(chip('with refusals', lib.refusedOnly, function () { setRefusedOnly(!lib.refusedOnly); },
      { icon: 'warning-circle',
        title: 'Mods with an uncalculated line',
        ariaLabel: 'Show only mods with refusals' }));
    box.appendChild(chip('installed', lib.hideInstalled, function () { setHideInstalled(!lib.hideInstalled); },
      { icon: lib.hideInstalled ? 'eye-slash' : 'eye',
        title: 'Hide the mods already in config ' + store().active_config,
        ariaLabel: 'Hide installed mods' }));
  }

  function renderSort() {
    var box = $('plLibSort');
    if (!box) return;
    clear(box);
    SORTS.forEach(function (s) {
      box.appendChild(chip(s.label, lib.sort === s.key, function () { setSort(s.key); },
        { title: s.title }));
    });
  }

  // ------------------------------------------------------------------ rows
  function flagWrap(row) {
    var wrap = el('div', { class: 'pl-row-flags' });
    var flags = flagsOf(row);
    flags.slice(0, MAX_FLAGS).forEach(function (f) {
      wrap.appendChild(el('span', { class: 'pl-flag', 'data-f': f, text: f }));
    });
    if (flags.length > MAX_FLAGS) {
      wrap.appendChild(el('span', { class: 'pl-flag',
        title: flags.slice(MAX_FLAGS).join(' · '), text: '+' + (flags.length - MAX_FLAGS) }));
    }
    return wrap;
  }

  function rightWrap(row, installed) {
    var wrap = el('div', { class: 'pl-row-right' });
    var sup = row.support || {};
    var counts = supportCounts(sup);
    if (counts) {
      wrap.appendChild(el('span', { class: 'pl-row-warn', 'data-icon': 'warning-circle',
        title: counts, 'aria-label': counts }));
    }
    if (installed) {
      var rank = installed.rank === null || installed.rank === undefined
        ? (row.max_rank || 0) : installed.rank;
      wrap.appendChild(el('span', { class: 'pl-flag', 'data-f': 'installed', text: 'R' + rank,
        title: 'Installed in ' + slotName(installed.kind, installed.index) + ' at rank ' + rank }));
      wrap.appendChild(el('span', { class: 'dim small', text: '(installed)' }));
    }
    wrap.appendChild(el('span', { class: 'pl-row-drain', title: drainTitle(row) }, drainKids(row)));
    return wrap;
  }

  function rowNode(e, i, installed) {
    var row = e.row;
    var inst = installed[row.id];
    var node = el('div', {
      class: 'pl-row', role: 'listitem', draggable: 'true', tabindex: '-1',
      'data-index': String(i), 'data-id': row.id, 'data-slot': row.slot || 'normal',
      'aria-selected': (i === lib.hl || row.id === P.selected()) ? 'true' : 'false',
      title: inst ? row.name + ' - in config ' + store().active_config
        : row.name + ' - click, or drag to a slot'
    });
    node.appendChild(P.polDot(row.polarity, false));
    var main = el('div', { class: 'pl-row-main' });
    var nameLine = el('div', { class: 'pl-row-name' });
    nameLine.appendChild(document.createTextNode(row.name || row.id));
    if (row.variant === 'beginner') {
      nameLine.appendChild(el('span', { class: 'pl-variant', text: 'flawed',
        title: 'The starter copy the game calls "' + (row.name || '') + '" - a different mod, ' +
          'with its own ranks' }));
    }
    if (row.shadowed) {
      nameLine.appendChild(el('span', { class: 'pl-variant pl-variant-hidden', text: 'not in game',
        title: 'No card in the wiki on this path' }));
    } else if (row.conclave) {
      nameLine.appendChild(el('span', { class: 'pl-variant', text: 'conclave',
        title: 'PvP only - not usable in PvE' }));
    }
    main.appendChild(nameLine);
    var first = (row.lines || [])[0];
    if (first) main.appendChild(el('div', { class: 'pl-row-lines', text: clip(first) }));
    node.appendChild(main);
    node.appendChild(flagWrap(row));
    node.appendChild(rightWrap(row, inst));

    node.addEventListener('click', function () { act(row); });
    node.addEventListener('mouseenter', function () { scheduleHover(node, row); });
    node.addEventListener('mouseleave', function () {
      cancelHover();
      P.hidePreview();
    });
    node.addEventListener('dragstart', function (ev) {
      lib.dragging = true;
      cancelHover();
      hideTip();
      P.hidePreview();
      node.setAttribute('data-dragging', 'true');
      P.dragStart(row, ev);
    });
    node.addEventListener('dragend', function () {
      lib.dragging = false;
      node.removeAttribute('data-dragging');
      P.dragEnd();
    });
    return node;
  }

  function emptyState(text, withClear) {
    var box = el('div', { class: 'pl-lib-empty dim', text: text });
    if (withClear) {
      var b = el('button', { class: 'pl-chip', type: 'button', 'data-icon': 'x',
        text: 'clear filters' });
      b.style.marginTop = '8px';
      b.addEventListener('click', clearFilters);
      box.appendChild(document.createElement('br'));
      box.appendChild(b);
    }
    return box;
  }

  function setCount(text) {
    var node = $('plLibCount');
    if (node) node.textContent = text;
  }

  /* The server keeps obsolete internal rows (the /Intermediate/ and /Expert/ leftovers that wear
     a real card's name) out of the list and says how many. Nothing is dropped in silence: the
     note offers them back, one click, and each revealed row is badged "not in game". */
  function renderHiddenNote() {
    var node = $('plLibHidden');
    if (!node) return;
    clear(node);
    var hidden = P.libraryHidden && P.libraryHidden();
    if (!hidden || !hidden.shadowed || P.libraryWithHidden && P.libraryWithHidden()) {
      node.hidden = true;
      return;
    }
    node.hidden = false;
    var link = el('button', { class: 'pl-hidden-link', type: 'button',
      text: hidden.shadowed + ' obsolete duplicates hidden',
      title: 'Rows this item can never slot: ' + (hidden.reason || '') });
    link.addEventListener('click', function () {
      if (P.revealShadowed) P.revealShadowed();
    });
    node.appendChild(link);
  }

  function renderList() {
    var list = $('plLibList');
    if (!list) return;
    hideTip();
    clear(list);
    lib.rows = [];
    if (!store().equipment_id) {
      lib.hl = -1;
      list.appendChild(emptyState('Pick equipment to see the mod library'));
      setCount('');
      return;
    }
    var total = (P.library() || []).length;
    if (lib.loading && !total) {
      lib.hl = -1;
      list.appendChild(emptyState('loading the library…'));
      setCount('· loading…');
      return;
    }
    var rows = visible();
    var installed = installedMap();
    var frag = document.createDocumentFragment();
    rows.forEach(function (e, i) {
      lib.rows.push(e.row);
      frag.appendChild(rowNode(e, i, installed));
    });
    lib.shown = rows.length;
    if (!rows.length) {
      var filtered = filtersOn();
      lib.hl = -1;
      list.appendChild(emptyState(filtered ? 'no mods match - clear a filter'
        : 'no mods in the library for this item', filtered));
      setCount('· 0 of ' + total);
      return;
    }
    // keep the highlight on the picked mod when it is on screen
    var sel = P.selected();
    lib.hl = -1;
    for (var i = 0; i < lib.rows.length; i++) {
      if (sel && lib.rows[i].id === sel) { lib.hl = i; break; }
    }
    list.appendChild(frag);
    iconize(list);
    setCount('· ' + rows.length + (rows.length === total ? ' mods' : ' of ' + total));
  }

  function renderAll() {
    renderFilters();
    renderSort();
    renderHiddenNote();
    renderList();
  }

  // ------------------------------------------------------------------ the mod detail card
  function kv(grid, key, value) {
    if (value === null || value === undefined || value === '') return;
    grid.appendChild(el('div', { class: 'pl-modtip-key', text: key }));
    grid.appendChild(el('div', { class: 'pl-modtip-val', text: String(value) }));
  }

  function metaText(row) {
    var bits = [];
    if (row.compat) bits.push(row.compat);
    if (row.type) bits.push(row.type);
    if (row.rarity) bits.push(row.rarity);
    bits.push(row.polarity ? 'polarity ' + row.polarity : 'vacant polarity');
    bits.push('MR-free');
    return bits.join(' · ');
  }

  function buildTip(row) {
    var box = el('div', { class: 'pl-modtip card', role: 'tooltip' });
    var head = el('div', { class: 'pl-modtip-head' });
    head.appendChild(el('span', { class: 'pl-modtip-name', text: row.name || row.id }));
    head.appendChild(el('span', { class: 'pl-modtip-meta', text: metaText(row),
      title: 'Mods carry no mastery requirement - MR-free' }));
    box.appendChild(head);
    var lines = (row.lines || []).slice(0, MAX_LINES);
    lines.forEach(function (line) {
      box.appendChild(el('div', { class: 'pl-modtip-line', text: clip(line) }));
    });
    if (!lines.length) {
      box.appendChild(el('div', { class: 'pl-modtip-line dim',
        text: 'no card text in the export' }));
    }
    var grid = el('div', { class: 'pl-modtip-grid' });
    kv(grid, 'Slot', (row.slot || 'normal') + (row.exilus_ok ? ' · fits an Exilus slot' : ''));
    kv(grid, 'Drain', drainText(row));
    kv(grid, 'Max rank', row.max_rank === null || row.max_rank === undefined
      ? null : 'R' + row.max_rank);
    kv(grid, 'Targets', (row.targets || []).join(', '));
    kv(grid, 'Class', row.class);
    kv(grid, 'Variant', row.variant);
    kv(grid, 'Flags', flagsOf(row).join(' · '));
    box.appendChild(grid);

    var sup = row.support || {};
    var unmodelled = sup.unmodelled_examples || [];
    var conditional = sup.conditional_examples || [];
    var warn = el('div', { class: 'pl-modtip-warn' });
    unmodelled.forEach(function (text) {
      warn.appendChild(el('div', { class: 'pl-modtip-refused', text: 'not calculated: ' + clip(text) }));
    });
    conditional.forEach(function (text) {
      warn.appendChild(el('div', { class: 'pl-modtip-refused', text: 'conditional: ' + clip(text) }));
    });
    if (!unmodelled.length && !conditional.length) {
      warn.appendChild(el('div', { text: 'Every line on this card is calculated.' }));
    } else {
      warn.appendChild(el('div', { text: supportCounts(sup) + ' - listed under "Not calculated"' }));
    }
    box.appendChild(warn);
    return box;
  }

  function placeTip(box, anchor) {
    document.body.appendChild(box);
    var r = anchor.getBoundingClientRect();
    var w = box.offsetWidth, h = box.offsetHeight;
    var y = r.top;
    var x = r.right + 12;                                   // beside the row when there is room
    if (x + w > window.innerWidth - 8) x = r.left - w - 12;
    if (x < 8) {                                            // a narrow viewport has no side room
      x = r.left;
      y = r.bottom + 6;
    }
    x = Math.max(8, Math.min(x, window.innerWidth - w - 8));
    y = Math.max(8, Math.min(y, window.innerHeight - h - 8));
    box.style.left = Math.round(x) + 'px';
    box.style.top = Math.round(y) + 'px';
  }

  function showTip(anchor, row) {
    hideTip();
    var box = buildTip(row);
    placeTip(box, anchor);
    iconize(box);
    lib.tip = box;
  }

  function hideTip() {
    if (lib.tip && lib.tip.parentNode) lib.tip.parentNode.removeChild(lib.tip);
    lib.tip = null;
  }

  function cancelHover() {
    if (lib.hoverTimer) { clearTimeout(lib.hoverTimer); lib.hoverTimer = null; }
  }

  function scheduleHover(anchor, row) {
    if (lib.dragging) return;                       // never a card while a drag is in flight
    cancelHover();
    lib.hoverTimer = setTimeout(function () {
      lib.hoverTimer = null;
      if (lib.dragging) return;
      showTip(anchor, row);
      previewFor(row);
    }, HOVER_MS);
  }

  // ------------------------------------------------------------------ before/after preview
  // The page builds the hypothetical build; the engine answers it (planner.js owns the diff).
  function defaultRank(row) {
    return row.max_rank === null || row.max_rank === undefined ? 0 : row.max_rank;
  }

  function previewTarget(row) {
    // The same legality rule the install paths use, so a hover can never promise a slot a click
    // would refuse (a locked Exilus slot is the case that used to diverge).
    var focus = P.focused();
    if (focus && P.slotLegal(focus.kind, focus.index, row)) {
      return { kind: focus.kind, index: focus.index };
    }
    var slots = P.build().slots || [];
    var last = null;
    for (var i = 0; i < slots.length; i++) {
      var s = slots[i];
      if (!P.slotLegal(s.kind, s.index, row)) continue;
      if (!s.mod) return { kind: s.kind, index: s.index };
      last = { kind: s.kind, index: s.index };
    }
    return last;                                     // no free slot: the last filled one
  }

  function previewFor(row) {
    if (installedMap()[row.id]) return;              // already in the config: nothing to preview
    var target = previewTarget(row);
    if (!target) return;
    var next = JSON.parse(JSON.stringify(P.build()));   // equipment/orokin/MR/exilus ride along
    var slots = next.slots || [];
    var placed = false;
    for (var i = 0; i < slots.length; i++) {
      if (slots[i].kind === target.kind && slots[i].index === target.index) {
        slots[i].mod = { id: row.id, rank: defaultRank(row) };
        placed = true;
        break;
      }
    }
    if (!placed) return;
    P.previewNext(next, row.name + ' → ' + slotName(target.kind, target.index));
  }

  // ------------------------------------------------------------------ interaction
  function act(row) {
    cancelHover();
    hideTip();
    P.hidePreview();
    if (installedMap()[row.id]) {                    // the engine refuses duplicates: select it
      P.pick(row);
      return;
    }
    var focus = P.focused();
    // one legality rule for every path: the class rules plus the live Exilus switch (the drag
    // handler and installAuto use the same function, so a click cannot do what a drag cannot)
    if (focus && P.slotLegal && P.slotLegal(focus.kind, focus.index, row)) {
      P.install(focus.kind, focus.index, row);
    } else P.installAuto(row);
  }

  function rowIndexFromEvent(ev) {
    var node = ev.target;
    var list = $('plLibList');
    while (node && node !== list) {
      if (node.classList && node.classList.contains('pl-row')) {
        var i = Number(node.getAttribute('data-index'));
        return isFinite(i) ? i : -1;
      }
      node = node.parentNode;
    }
    return -1;
  }

  function paintHl() {
    var list = $('plLibList');
    if (!list) return;
    var nodes = list.querySelectorAll('.pl-row');
    var sel = P.selected();
    for (var k = 0; k < nodes.length && k < lib.rows.length; k++) {
      var on = k === lib.hl || (sel && lib.rows[k].id === sel);
      nodes[k].setAttribute('aria-selected', on ? 'true' : 'false');
    }
  }

  function setHl(i, scroll) {
    lib.hl = i;
    paintHl();
    if (!scroll) return;
    var list = $('plLibList');
    var nodes = list ? list.querySelectorAll('.pl-row') : [];
    if (nodes[i] && nodes[i].scrollIntoView) nodes[i].scrollIntoView({ block: 'nearest' });
  }

  function wireList(list) {
    list.setAttribute('tabindex', '0');              // tab-reachable: arrows + Enter drive it
    list.addEventListener('keydown', function (ev) {
      var n = lib.rows.length;
      if (!n) return;
      var at = rowIndexFromEvent(ev);
      if (ev.key === 'ArrowDown' || ev.key === 'ArrowUp') {
        ev.preventDefault();
        var step = ev.key === 'ArrowDown' ? 1 : -1;
        var from = at >= 0 ? at : lib.hl;
        var next = from < 0 ? (step > 0 ? 0 : n - 1)
          : Math.max(0, Math.min(n - 1, from + step));
        setHl(next, true);
        return;
      }
      if (ev.key === 'Home' || ev.key === 'End') {
        ev.preventDefault();
        setHl(ev.key === 'Home' ? 0 : n - 1, true);
        return;
      }
      if (ev.key === 'Enter') {
        var idx = at >= 0 ? at : lib.hl;
        if (idx < 0 || idx >= n) return;
        ev.preventDefault();
        act(lib.rows[idx]);
      }
    });
    list.addEventListener('scroll', hideTip);
  }

  function wireSearch() {
    var box = $('plLibSearch');
    if (!box) return;
    if (lib.q) box.value = lib.q;
    box.addEventListener('input', function () {
      if (lib.searchTimer) clearTimeout(lib.searchTimer);
      var value = box.value;
      lib.searchTimer = setTimeout(function () {
        lib.searchTimer = null;
        setQuery(value.trim());
      }, SEARCH_MS);
    });
    box.addEventListener('keydown', function (ev) {
      if (ev.key === 'Escape' && box.value) {
        ev.stopPropagation();                        // first Escape clears, the next blurs
        box.value = '';
        setQuery('');
        return;
      }
      // ArrowDown walks out of the search and into the results, so the keyboard path is
      // "/ serration ArrowDown Enter" - the mouse is never required.
      if (ev.key === 'ArrowDown' || ev.key === 'ArrowUp') {
        var list = $('plLibList');
        if (!list) return;
        ev.preventDefault();
        if (lib.searchTimer) { clearTimeout(lib.searchTimer); lib.searchTimer = null; }
        setQuery(box.value.trim());
        list.focus();
        if (lib.rows.length) setHl(Math.max(0, lib.hl), true);   // Enter has something to act on
      }
    });
  }

  // ------------------------------------------------------------------ state writers
  function setSlot(v) { lib.slot = v; libStore().slot = v; persist(); renderAll(); }
  function setPolarityFilter(v) { lib.polarity = v; libStore().polarity = v; persist(); renderAll(); }
  function setSort(v) { lib.sort = v; libStore().sort = v; persist(); renderAll(); }
  function setRefusedOnly(v) { lib.refusedOnly = v; libStore().hide_refused = v; persist(); renderAll(); }
  function setHideInstalled(v) { lib.hideInstalled = v; libStore().hide_installed = v; persist(); renderAll(); }
  function setFits(v) { lib.fitsOn = v; renderAll(); }                 // transient, not stored
  function setQuery(v) { lib.q = v; libStore().q = v; persist(); renderList(); }

  function applyStored() {
    var st = store();
    var saved = (st && st.library) || {};
    lib.q = saved.q === null || saved.q === undefined ? '' : String(saved.q);
    lib.polarity = saved.polarity || '';
    lib.slot = saved.slot || '';
    lib.sort = saved.sort || 'name';
    var known = SORTS.some(function (s) { return s.key === lib.sort; });
    if (!known) lib.sort = 'name';
    lib.refusedOnly = !!saved.hide_refused;
    lib.hideInstalled = !!saved.hide_installed;
    var box = $('plLibSearch');
    if (box && lib.q) box.value = lib.q;
  }

  // ------------------------------------------------------------------ boot
  function init() {
    if (!$('plLibList')) return;
    applyStored();
    wireSearch();
    var list = $('plLibList');
    if (list) wireList(list);
    P.on('ready', function () { applyStored(); renderAll(); });
    P.on('equipment', function () { lib.loading = true; renderAll(); });
    P.on('library', function () { lib.loading = false; renderAll(); });
    P.on('state', renderAll);
    P.on('result', renderAll);
    // An installed mod's chip in the slot grid asks for that same card -
    // the same card a library row shows, so the reasons live in one place.
    P.on('tip', function (payload) {
      if (!payload || !payload.id) return;
      var row = P.modRowById ? P.modRowById(payload.id) : null;
      if (row) showTip(payload.anchor || $('plLibList') || document.body, row);
    });
    document.addEventListener('keydown', function (ev) {
      if (ev.key === 'Escape') hideTip();
    });
    // a drag that ends outside a row still has to hand the panel back
    document.addEventListener('dragend', function () { lib.dragging = false; });
    document.addEventListener('drop', function () { lib.dragging = false; });
    window.addEventListener('scroll', hideTip, true);
    window.addEventListener('resize', hideTip);
    renderAll();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
