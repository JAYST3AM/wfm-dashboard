/* planner.js - the build planner page.
 *
 * What this file owns: the build state (storage v1), the API client, the equipment picker,
 * the toolbar (rank / catalyst / exilus / mastery / configs), the slot grid with drag & drop,
 * the capacity bar, the validation list and the hover preview loop.
 *
 * What it does NOT own: any Warframe math. Every number the page draws - drain per slot,
 * capacity, stats, traces, refusals, validation - arrives from /api/planner/*, which runs the
 * Phase 1 engine in builds/. The page formats what the engine said and diffs two engine
 * answers it was handed (/preview); it never guesses one.
 *
 * The other two scripts are panels on top of this one: planner-library.js (what can go in)
 * and planner-stats.js (what comes out). They talk to WFMPlanner below and nothing else.
 *
 * Icons: data-icon names come from the pinned Phosphor sprite (tools/build_icons.py --check);
 * this file uses blueprint/caret-down/caret-right/grid-four/diamond/lock-open/x/plus/minus/
 * check-circle/warning-circle/x-circle/info/magnifying-glass/funnel/arrows-clockwise/
 * sliders-horizontal/stack/chart-line/list-dashes/atom/seal-check/trash-simple/clipboard-text.
 */
'use strict';

(function () {
  var STORE_KEY = 'wfm.planner.v1';
  var STORE_VERSION = 1;            // must match meta.storage_version
  var CONFIGS = ['A', 'B', 'C'];
  var POLARITIES = ['madurai', 'naramon', 'vazarin', 'zenurik', 'penjaga', 'umbra', 'universal'];
  var POL_SHORT = { madurai: 'V', naramon: '—', vazarin: 'D', zenurik: 'Z', penjaga: 'P',
    umbra: 'U', universal: 'A' };
  var KIND_LABEL = { warframe: 'Warframe', primary: 'Primary', secondary: 'Secondary',
    melee: 'Melee', sentinel: 'Sentinel', sentinel_weapon: 'Sentinel weapon' };
  var SLOT_LABEL = { normal: 'Mod slot', aura: 'Aura', stance: 'Stance', exilus: 'Exilus' };
  var COMPUTE_DEBOUNCE = 40;
  var SAVE_DEBOUNCE = 220;
  var PREVIEW_DEBOUNCE = 90;

  // ------------------------------------------------------------------ DOM shorthands
  function $(id) { return document.getElementById(id); }
  function el(tag, attrs, kids) {
    var node = document.createElement(tag);
    if (attrs) {
      for (var k in attrs) {
        if (!Object.prototype.hasOwnProperty.call(attrs, k)) continue;
        var v = attrs[k];
        if (v === null || v === undefined || v === false) continue;
        if (k === 'text') { node.textContent = String(v); continue; }
        if (k === 'style') { node.setAttribute('style', v); continue; }
        node.setAttribute(k, v === true ? '' : String(v));
      }
    }
    if (kids) {
      (Array.isArray(kids) ? kids : [kids]).forEach(function (kid) {
        if (kid === null || kid === undefined || kid === false) return;
        node.appendChild(typeof kid === 'string' || typeof kid === 'number'
          ? document.createTextNode(String(kid)) : kid);
      });
    }
    return node;
  }
  function clear(node) { while (node && node.firstChild) node.removeChild(node.firstChild); }
  function show(node, on) { if (node) node.hidden = !on; }

  // ------------------------------------------------------------------ formatting
  // Display only: the engine already rounded its answers. These trim them the way the
  // engine's own trace renderer does, so a stat reads the same in both places.
  function numText(v) {
    if (v === null || v === undefined || v === '') return '—';
    var n = Number(v);
    if (!isFinite(n)) return String(v);
    if (Math.abs(n - Math.round(n)) < 1e-9) return String(Math.round(n));
    var rounded = Math.round(n * 1000) / 1000;
    return String(rounded);
  }
  function intText(v) {
    if (v === null || v === undefined) return '—';
    return String(Math.round(Number(v)));
  }
  var fmt = {
    num: numText,
    int: intText,
    pct: function (v) { return v === null || v === undefined ? '—' : numText(v) + '%'; },
    signed: function (v, unit) {
      var n = Number(v);
      if (!isFinite(n)) return '—';
      var sign = n > 0 ? '+' : '';
      return sign + numText(n) + (unit === 'percent' ? '%' : '');
    },
    multiplier: function (v) { return v === null || v === undefined ? '—' : 'x' + numText(v); },
    seconds: function (v) { return v === null || v === undefined ? '—' : numText(v) + 's'; },
    // stat key -> a human label; the trace carries the engine's own label when it has one
    label: function (key) {
      return String(key || '').replace(/_/g, ' ').replace(/\b\w/g, function (c) {
        return c.toUpperCase();
      });
    }
  };

  // ------------------------------------------------------------------ state
  var state = {
    ready: false,
    meta: null,
    equipment: null,          // the ingested row from /equipment/<key>
    layout: [],               // [{kind,index,polarity,unlocked,default_polarity}]
    polaritiesFromExport: true,
    library: [],              // mod rows for this equipment (planner-library.js draws them)
    libraryFor: null,
    result: null,             // last /compute answer, when it carried a numeric result
    answer: null,             // the whole /compute answer, refusals included
    baseline: null,
    storage: null,
    focused: null,            // {kind, index} of the selected slot
    selectedMod: null,        // library row the user picked (for Enter / click install)
    computing: false,
    computeSeq: 0,
    rescued: false,           // an unreadable stored payload was replaced (boot rewrites it)
    library: [],              // the mods that fit this item (server rows)
    libraryFor: null,
    libraryHidden: null,      // {shadowed: N, reason: ...}: rows the server kept out by name
    libraryWithHidden: false,
    error: null
  };

  function slotKey(kind, index) { return kind + ':' + (index === null || index === undefined ? '-' : index); }

  function freshStorage() {
    var configs = {};
    CONFIGS.forEach(function (letter) { configs[letter] = { slots: {}, polarities: {} }; });
    return {
      version: STORE_VERSION,
      equipment_id: null,
      equipment_rank: null,   // null = the item's own max rank
      orokin: false,
      exilus_unlocked: false,
      mastery_rank: 28,
      active_config: 'A',
      configs: configs,
      library: { q: '', polarity: '', slot: '', sort: 'name', hide_refused: false },
      ui: { trace: null },
      // Phase 4: what the caller states about the target. Blank/absent means NOT STATED, which
      // the engine answers as `unknown` - never as zero or false. The page sends only the parts
      // the user actually stated, so "not stated" survives the trip.
      target: { faction: '', viral_stacks: null, protection: '', shot: null, strict: false,
        // Phase 5: the enemy model and the stated buff state. null = NOT STATED, which the engine
        // answers as `unknown`; 0 is a stated zero and means something else.
        armour: null, corrosive_stacks: null, kill_stacks: null, kill_uptime: null,
        // Phase 6: the Heat strip (one of the ramp's values) and the stated pool sizes. null =
        // NOT STATED; 0 is a stated zero and means something else.
        heat_strip: null, pool_health: null, pool_shields: null, pool_overguard: null }
    };
  }

  function loadStorage() {
    var raw = null;
    try { raw = window.localStorage.getItem(STORE_KEY); } catch (e) { raw = null; }
    if (!raw) return freshStorage();
    var data = null;
    try { data = JSON.parse(raw); } catch (e) { data = null; }
    // An unknown version is a fresh start, not a guess: storage v1 is what this page writes.
    // state.rescued makes the boot rewrite the store, so a payload this page cannot read does
    // not sit there being re-tested on every load.
    if (!data || Number(data.version) !== STORE_VERSION) {
      state.rescued = true;
      return freshStorage();
    }
    var clean = cleanV1(data);
    if (!clean) {
      state.rescued = true;                 // structural junk is replaced whole, never half-applied
      return freshStorage();
    }
    return clean;
  }

  var POLARITY_NAMES = ['madurai', 'naramon', 'vazarin', 'zenurik', 'umbral', 'penjaga', 'unairu'];
  var MAX_STORED_RANK = 40;        // the game's own ceiling (a rank-40 frame)

  // Every field of a v1 document, checked before any of it is trusted: a payload this page
  // cannot read in full is dropped in full (the boot then rewrites the key). Ranges are checked
  // here too, because the engine's own coercion must never see a string where it wants a rank.
  function cleanV1(data) {
    if (!data || typeof data !== 'object' || Array.isArray(data)) return null;
    if (data.version !== STORE_VERSION) return null;   // "1" is not 1: no coercion here
    var out = freshStorage();
    var bad = false;
    // Strict: a field that is present but not what v1 says it is fails the whole document (the
    // boot then rewrites the key). Defaulting a junk value would silently change the user's state.
    function scalar(key, ok, fallback) {
      var v = data[key];
      if (v === undefined || v === null) return fallback;
      if (!ok(v)) { bad = true; return fallback; }
      return v;
    }
    var SLOT_KEY = /^(normal:\d+|exilus|aura|stance)$/;
    out.equipment_id = scalar('equipment_id',
      function (v) { return typeof v === 'string' && v.length > 0; }, null);
    out.equipment_rank = scalar('equipment_rank',
      function (v) { return Number.isInteger(v) && v >= 0; }, null);
    out.mastery_rank = scalar('mastery_rank',
      function (v) { return Number.isInteger(v) && v >= 0 && v <= 40; }, 0);
    out.orokin = scalar('orokin', function (v) { return typeof v === 'boolean'; }, false);
    out.exilus_unlocked = scalar('exilus_unlocked',
      function (v) { return typeof v === 'boolean'; }, false);
    if (data.active_config !== undefined && data.active_config !== null) {
      if (CONFIGS.indexOf(data.active_config) < 0) return null;   // a config that does not exist
      out.active_config = data.active_config;
    }
    var cfgIn = (data.configs === undefined || data.configs === null) ? {} : data.configs;
    if (typeof cfgIn !== 'object' || Array.isArray(cfgIn)) return null;
    for (var i = 0; i < CONFIGS.length; i++) {
      var letter = CONFIGS[i];
      var cfg = cfgIn[letter];
      if (cfg === undefined || cfg === null) continue;
      if (typeof cfg !== 'object' || Array.isArray(cfg)) return null;
      var slotsIn = (cfg.slots === undefined || cfg.slots === null) ? {} : cfg.slots;
      var polIn = (cfg.polarities === undefined || cfg.polarities === null) ? {} : cfg.polarities;
      if (typeof slotsIn !== 'object' || Array.isArray(slotsIn)) return null;
      if (typeof polIn !== 'object' || Array.isArray(polIn)) return null;
      var slots = {};
      var slotKeys = Object.keys(slotsIn);
      for (var s = 0; s < slotKeys.length; s++) {
        var entry = slotsIn[slotKeys[s]];
        if (!entry || typeof entry !== 'object' || Array.isArray(entry)) return null;
        if (!SLOT_KEY.test(slotKeys[s])) return null;
        if (typeof entry.id !== 'string' || !entry.id.length) return null;
        var rank = (entry.rank === undefined || entry.rank === null) ? 0 : entry.rank;
        if (!Number.isInteger(rank) || rank < 0 || rank > MAX_STORED_RANK) return null;
        slots[slotKeys[s]] = { id: entry.id, rank: rank };
      }
      var pols = {};
      var polKeys = Object.keys(polIn);
      for (var q = 0; q < polKeys.length; q++) {
        if (!SLOT_KEY.test(polKeys[q])) return null;
        var value = polIn[polKeys[q]];
        if (value === undefined || value === null) continue;
        if (typeof value !== 'string') return null;
        // '' is meaningful: it is a slot the player cleared, and clearing costs a Forma
        if (value !== '' && POLARITY_NAMES.indexOf(value) < 0) return null;
        pols[polKeys[q]] = value;
      }
      out.configs[letter] = { slots: slots, polarities: pols };
    }
    out.library = cleanLibrary(data.library);
    if (out.library === null) return null;
    var cleanTargetOut = cleanTarget(data.target);
    if (cleanTargetOut === null) return null;
    out.target = cleanTargetOut;
    if (data.ui !== undefined && data.ui !== null &&
        (typeof data.ui !== 'object' || Array.isArray(data.ui))) return null;
    out.ui = (data.ui && typeof data.ui === 'object') ? data.ui : {};
    return bad ? null : out;
  }

  // The Phase 4 target block, validated like every other member of v1: what the caller stated is
  // kept exactly as stated (blank and null are meaningful - they mean NOT STATED, which the engine
  // answers as unknown), and a member that is present and wrong fails the document like any other.
  var TARGET_FACTIONS = ['', 'grineer', 'kuva_grineer', 'corpus', 'corpus_amalgam', 'infested',
    'infested_deimos', 'orokin', 'sentient', 'narmer', 'murmur', 'zariman', 'scaldra', 'techrot',
    'anarchs', 'tenno'];
  var TARGET_LANDINGS = ['', 'health', 'armor', 'shields', 'overguard'];
  // The stored ranges, shared by the loader (cleanTarget) and the editor (targetEdit) so the page
  // cannot write a document its own loader would reject: an out-of-range entry is refused at the
  // box, visibly, instead of being stored and re-read as corruption on the next load. The engine's
  // contract is looser (any finite non-negative number the caller states) - the store keeps a
  // practical ceiling, and a value above it is refused rather than dropped.
  var TARGET_RANGES = {viral_stacks: [0, 10], shot: [1, 999], armour: [0, 1000000000],
    corrosive_stacks: [0, 10], kill_stacks: [0, 99], kill_uptime: [0, 100],
    pool_health: [0, 1000000000], pool_shields: [0, 1000000000], pool_overguard: [0, 1000000000]};
  // The Heat strip's own values: the wiki's ramp plateaus (15/30/40/50) or a stated zero.
  var HEAT_STRIPS = [0, 15, 30, 40, 50];
  // Number('0x10') is 16 and Number('1e3') is 1000: a stored field is a plain decimal or it is
  // not a value this page wrote.
  var DECIMAL = /^-?\d+(?:\.\d+)?$/;

  // undefined/null -> null (not stated); a whole number or a numeric string in range -> it; anything
  // else -> false, which the caller turns into "this document is not v1".
  function numericField(value, lo, hi) {
    if (value === undefined || value === null) return null;
    var text = (typeof value === 'string') ? value.trim() : null;
    var n = (typeof value === 'number') ? value
      : (text !== null && DECIMAL.test(text) ? Number(text) : NaN);
    // A fractional count is in range but is not a count: it is kept as stated and the engine
    // answers unknown (a refusal, not a rounding). Only shape and range fail the document.
    if (!isFinite(n) || n < lo || n > hi) return false;
    return n;
  }

  function cleanTarget(raw) {
    var out = freshStorage().target;
    if (raw === undefined || raw === null) return out;
    if (typeof raw !== 'object' || Array.isArray(raw)) return null;
    var keys = Object.keys(raw);
    for (var i = 0; i < keys.length; i++) {
      if (keys[i] !== 'heat_strip' && keys[i] !== 'pool_health' && keys[i] !== 'pool_shields' &&
          keys[i] !== 'pool_overguard' &&
          keys[i] !== 'faction' && keys[i] !== 'viral_stacks' && keys[i] !== 'protection' &&
          keys[i] !== 'shot' && keys[i] !== 'strict' && keys[i] !== 'armour' &&
          keys[i] !== 'corrosive_stacks' && keys[i] !== 'kill_stacks' &&
          keys[i] !== 'kill_uptime') return null;
    }
    if (raw.faction !== undefined && raw.faction !== null) {
      if (typeof raw.faction !== 'string' || TARGET_FACTIONS.indexOf(raw.faction) < 0) return null;
      out.faction = raw.faction;
    }
    if (raw.heat_strip !== undefined && raw.heat_strip !== null) {
      var heat = Number(raw.heat_strip);
      if (HEAT_STRIPS.indexOf(heat) < 0) return null;
      out.heat_strip = heat;
    }
    if (raw.protection !== undefined && raw.protection !== null) {
      if (typeof raw.protection !== 'string' || TARGET_LANDINGS.indexOf(raw.protection) < 0) return null;
      out.protection = raw.protection;
    }
    // A count written as a numeric string ("6") is unambiguous, so it is coerced rather than
    // failing the whole document - losing a planner's build over a quoted digit would be worse
    // than the quote. Anything else is a shape v1 does not define and fails like every other.
    // Phase 5: the enemy model and the buff state, validated through the same table the editor
    // refuses against - one contract, two readers.
    var rangeKeys = Object.keys(TARGET_RANGES);
    for (var r = 0; r < rangeKeys.length; r++) {
      var rk = rangeKeys[r];
      var rv = numericField(raw[rk], TARGET_RANGES[rk][0], TARGET_RANGES[rk][1]);
      if (rv === false) return null;
      out[rk] = rv;
    }
    if (raw.strict !== undefined && raw.strict !== null) {
      if (typeof raw.strict !== 'boolean') return null;
      out.strict = raw.strict;
    }
    return out;
  }

  var LIB_SLOTS = ['', 'normal', 'aura', 'stance', 'exilus'];
  var LIB_SORTS = ['name', 'drain', 'rarity', 'flag', 'catalogue'];

  // The library panel's own persisted view state: every member v1 defines, checked; a member
  // that is present and wrong fails the document like any other.
  function cleanLibrary(raw) {
    if (raw === undefined || raw === null) return freshStorage().library;
    if (typeof raw !== 'object' || Array.isArray(raw)) return null;
    var out = freshStorage().library;
    var ok = true;
    function text(key, allowed) {
      var v = raw[key];
      if (v === undefined || v === null) return;
      if (typeof v !== 'string' || (allowed && allowed.indexOf(v) < 0)) { ok = false; return; }
      out[key] = v;
    }
    function bool(key) {
      var v = raw[key];
      if (v === undefined || v === null) return;
      if (typeof v !== 'boolean') { ok = false; return; }
      out[key] = v;
    }
    text('q');
    text('polarity', POLARITY_NAMES.concat(['']));
    text('slot', LIB_SLOTS);
    text('sort', LIB_SORTS);
    bool('hide_refused');
    bool('hide_installed');
    return ok ? out : null;
  }

  var saveTimer = null;

  function writeStorage() {
    try { window.localStorage.setItem(STORE_KEY, JSON.stringify(state.storage)); }
    catch (e) { /* a full quota must not break the page */ }
  }

  // A debounced write is a write the browser can lose: navigating away (or closing the tab) inside
  // the debounce window drops the user's last edit. The debounce stays - it is what keeps a drag
  // from writing on every frame - but a pending write is flushed on the way out.
  function flushStorage() {
    if (!saveTimer) return;
    clearTimeout(saveTimer);
    saveTimer = null;
    writeStorage();
  }

  if (window.addEventListener) {
    window.addEventListener('pagehide', flushStorage);
    window.addEventListener('beforeunload', flushStorage);
  }
  if (document.addEventListener) {
    document.addEventListener('visibilitychange', function () {
      if (document.visibilityState === 'hidden') flushStorage();
    });
  }

  function saveStorage() {
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(function () {
      saveTimer = null;
      writeStorage();
    }, SAVE_DEBOUNCE);
  }

  // ------------------------------------------------------------------ events
  var listeners = {};
  function on(name, fn) {
    (listeners[name] = listeners[name] || []).push(fn);
    return function off() {
      listeners[name] = (listeners[name] || []).filter(function (f) { return f !== fn; });
    };
  }
  function emit(name, payload) {
    (listeners[name] || []).forEach(function (fn) {
      try { fn(payload); } catch (e) {
        if (window.console) console.error('planner listener failed', name, e);
      }
    });
  }

  // ------------------------------------------------------------------ API client
  function get(url) {
    return fetch(url, { cache: 'no-cache' }).then(function (r) {
      return r.json().catch(function () { return { ok: false, error: 'bad JSON from ' + url }; });
    }).catch(function (e) { return { ok: false, error: String(e && e.message || e) }; });
  }
  function post(url, body) {
    return fetch(url, {
      method: 'POST', cache: 'no-cache',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {})
    }).then(function (r) {
      return r.json().catch(function () { return { ok: false, error: 'bad JSON from ' + url }; });
    }).catch(function (e) {
      return { ok: false, error: String(e && e.message || e) };
    });
  }
  var api = {
    meta: function () { return get('/api/planner/meta'); },
    equipment: function (q, kind, limit) {
      var url = '/api/planner/equipment?q=' + encodeURIComponent(q || '') +
        (kind ? '&kind=' + encodeURIComponent(kind) : '') + '&limit=' + (limit || 80);
      return get(url);
    },
    item: function (key) { return get('/api/planner/equipment/' + encodeURIComponent(key)); },
    mods: function (key, includeShadowed) {
      return get('/api/planner/mods?equipment=' + encodeURIComponent(key) +
        (includeShadowed ? '&shadowed=1' : ''));
    },
    unsupported: function () { return get('/api/planner/unsupported'); },
    compute: function (build) { return post('/api/planner/compute', build); },
    current: function (force) {
      return force ? post('/api/planner/current/refresh', {}) : get('/api/planner/current');
    },
    cloneCurrent: function (body) { return post('/api/planner/clone', body); },
    preview: function (build, next) {
      return post('/api/planner/preview', { build: build, next: next });
    },
    explain: function (build, stat) {
      return post('/api/planner/explain', { build: build, stat: stat });
    }
  };

  // ------------------------------------------------------------------ the build dict
  function activeConfig() { return state.storage.configs[state.storage.active_config]; }

  function layoutSlot(kind, index) {
    for (var i = 0; i < state.layout.length; i++) {
      var s = state.layout[i];
      if (s.kind === kind && (s.index === index || (index === null && s.index === null))) return s;
    }
    return null;
  }

  function slotPolarity(kind, index) {
    var key = slotKey(kind, index);
    var cfg = activeConfig();
    if (cfg.polarities && Object.prototype.hasOwnProperty.call(cfg.polarities, key)) {
      var stored = cfg.polarities[key];
      return stored === '' ? null : stored;             // '' = the user cleared it
    }
    var slot = layoutSlot(kind, index);
    var def = slot ? slot.default_polarity : null;
    return def || null;
  }

  function slotMod(kind, index) {
    var entry = activeConfig().slots[slotKey(kind, index)];
    return entry && entry.id ? entry : null;
  }

  function build() {
    var slots = state.layout.map(function (s) {
      var entry = slotMod(s.kind, s.index);
      return {
        kind: s.kind, index: s.index,
        polarity: slotPolarity(s.kind, s.index),
        unlocked: s.kind === 'exilus' ? !!state.storage.exilus_unlocked : undefined,
        mod: entry ? { id: entry.id, rank: entry.rank } : null
      };
    });
    var out = {
      config: state.storage.active_config,
      equipment_id: state.storage.equipment_id,
      equipment_rank: state.storage.equipment_rank === null ? undefined
        : state.storage.equipment_rank,
      orokin: !!state.storage.orokin,
      mastery_rank: state.storage.mastery_rank,
      exilus_unlocked: !!state.storage.exilus_unlocked,
      slots: slots
    };
    var options = optionsFor();
    if (options) out.options = options;
    return out;
  }

  // The evaluation options, built only from what was stated. An unstated field is absent, which is
  // what lets the engine tell 'unknown' apart from a stated value.
  function targetState() {
    if (!state.storage.target || typeof state.storage.target !== 'object') {
      state.storage.target = { faction: '', viral_stacks: null, protection: '', shot: null,
        strict: false, heat_strip: null, pool_health: null, pool_shields: null,
        pool_overguard: null };
    }
    return state.storage.target;
  }

  function optionsFor() {
    var t = targetState();
    var context = {};
    if (t.faction) context.target_faction = String(t.faction);
    var target = {};
    var stacks = statedNumber(t.viral_stacks);
    if (stacks !== null) target.viral_stacks = stacks;
    if (t.protection) target.protection = String(t.protection);
    var armour = statedNumber(t.armour);
    if (armour !== null) target.armor = armour;
    var corrosive = statedNumber(t.corrosive_stacks);
    if (corrosive !== null) target.corrosive_stacks = corrosive;
    // Phase 6: the stated Heat strip (the ramp's own values) and the stated pool sizes.
    var heat = statedNumber(t.heat_strip);
    if (heat !== null && HEAT_STRIPS.indexOf(heat) >= 0) target.heat_strip = heat;
    var pools = [['pool_health', 'health'], ['pool_shields', 'shields'],
      ['pool_overguard', 'overguard']];
    for (var pi = 0; pi < pools.length; pi++) {
      var poolValue = statedNumber(t[pools[pi][0]]);
      if (poolValue !== null) target[pools[pi][1]] = poolValue;
    }
    if (Object.keys(target).length) context.target = target;
    // The stated buff state (Phase 5): instant stacks, or the averaged pair of stacks + uptime %.
    var ks = statedNumber(t.kill_stacks);
    var up = statedNumber(t.kill_uptime);
    if (ks !== null || up !== null) {
      var onKill = {};
      if (ks !== null) onKill.stacks = ks;
      if (up !== null) onKill.uptime = PAGE_TRANSFORMS['uptime-percent'](up);
      context.buffs = { on_kill: onKill };
    }
    var shot = statedNumber(t.shot);
    if (shot !== null) context.attack = { shot_index: shot };
    var options = {};
    if (Object.keys(context).length) options.context = context;
    if (t.strict) options.strict = true;
    return Object.keys(options).length ? options : null;
  }

  // The one page-side transform in the whole target path: the uptime box is a percent and the
  // request wants a fraction, so the user's own number is rescaled once, here. It lives in a named
  // table (not an inline division) so the page's own no-math scan can see and pin it: a second
  // transform needs its own table row and the same review.
  var PAGE_TRANSFORMS = {'uptime-percent': function (percent) { return percent / 100; }};

  // A stated number or nothing: '' / null / NaN is not a value, so it is not sent.
  function statedNumber(v) {
    if (v === null || v === undefined || v === '') return null;
    var n = Number(v);
    return isFinite(n) ? n : null;
  }


  function buildWith(nextConfig) {
    var current = state.storage.active_config;
    state.storage.active_config = nextConfig;
    var out = build();
    state.storage.active_config = current;
    return out;
  }

  // ------------------------------------------------------------------ mutations
  function install(kind, index, modRow, rank, polarity) {
    if (!modRow) return false;
    var key = slotKey(kind, index);
    var cfg = activeConfig();
    cfg.slots[key] = { id: modRow.id,
      rank: rank === undefined || rank === null ? (modRow.max_rank || 0) : rank };
    if (polarity !== undefined) cfg.polarities[key] = polarity || '';
    saveStorage();
    state.focused = { kind: kind, index: index };
    recompute();
    return true;
  }

  function clearSlot(kind, index) {
    var cfg = activeConfig();
    delete cfg.slots[slotKey(kind, index)];
    saveStorage();
    recompute();
  }

  // Setting a polarity to the item's own default removes the entry (nothing to Forma); a clear
  // (`''`) and any other value stay, because both are a slot the user changed - one Forma each.
  function setPolarity(kind, index, polarity) {
    var cfg = activeConfig();
    var key = slotKey(kind, index);
    var slot = layoutSlot(kind, index);
    var def = slot ? (slot.default_polarity || null) : null;
    if (!polarity) {
      if (def) cfg.polarities[key] = '';            // cleared a slot the item polarised: one Forma
      else delete cfg.polarities[key];              // already vacant as shipped: no Forma
    } else if (polarity === def) {
      delete cfg.polarities[key];                   // back to the item's own polarity: no Forma
    } else {
      cfg.polarities[key] = polarity;
    }
    saveStorage();
    recompute();
  }

  // Every slot whose polarity differs from the item's own - what a real player pays Forma for.
  function polarityChanges() {
    var cfg = activeConfig();
    var out = [];
    state.layout.forEach(function (slot) {
      var key = slotKey(slot.kind, slot.index);
      if (!Object.prototype.hasOwnProperty.call(cfg.polarities || {}, key)) return;
      var now = cfg.polarities[key] === '' ? null : cfg.polarities[key];
      out.push({
        kind: slot.kind, index: slot.index, polarity: now,
        label: slot.kind === 'normal' ? 'Slot ' + (slot.index + 1) : SLOT_LABEL[slot.kind],
        base: slot.default_polarity || null
      });
    });
    return out;
  }
  function formaUsed() { return polarityChanges().length; }

  function setModRank(kind, index, rank) {
    var cfg = activeConfig();
    var key = slotKey(kind, index);
    if (!cfg.slots[key]) return;
    cfg.slots[key].rank = rank;
    saveStorage();
    recompute();
  }

  // Which slot does a mod legally go in? Data from the library row (`slot`, `exilus_ok`),
  // the slots come from the item's layout - no engine number is involved.
  function modFitsSlot(modRow, kind) {
    var cls = modRow.slot || 'normal';
    if (kind === 'aura' || kind === 'stance') return cls === kind;
    if (kind === 'exilus') return !!modRow.exilus_ok;
    return cls === 'normal';
  }

  function firstLegalSlot(modRow) {
    var order = state.layout.filter(function (s) {
      return slotLegal(s.kind, s.index, modRow) && !slotMod(s.kind, s.index);
    });
    return order.length ? order[0] : null;
  }

  function installAuto(modRow) {
    var target = null;
    if (state.focused && slotLegal(state.focused.kind, state.focused.index, modRow)) {
      target = state.focused;
    } else target = firstLegalSlot(modRow);
    if (!target) {
      // No empty compatible slot: the library row stays selected and the drop targets light up.
      state.selectedMod = modRow.id;
      emit('state', state);
      flashHint('No free ' + (modRow.slot === 'aura' ? 'aura' : modRow.slot === 'stance'
        ? 'stance' : 'mod') + ' slot - drop to replace');
      return false;
    }
    return install(target.kind, target.index, modRow);
  }

  // ------------------------------------------------------------------ compute loop
  var computeTimer = null;
  function recompute(immediate) {
    if (!state.storage.equipment_id || !state.storage.equipment_id.length) return;
    if (computeTimer) { clearTimeout(computeTimer); computeTimer = null; }
    var run = function () {
      computeTimer = null;
      var seq = ++state.computeSeq;
      state.computing = true;
      var payload = build();
      api.compute(payload).then(function (out) {
        if (seq !== state.computeSeq) return;           // a stale answer never lands
        state.computing = false;
        var good = !!(out && out.result);
        // A refusal is not a result to paint, but it is an answer: the engine's own validation
        // (capacity_exceeded, mod_not_exilus, ...) is kept and shown by the Validation card.
        state.answer = out || null;
        state.result = good ? out : null;
        state.baseline = good ? out.baseline : null;
        state.error = (out && out.error) ? out.error
          : (good || (out && out.validation) ? null : 'the engine did not answer');
        renderResult();
        emit('result', out);
      }).catch(function (err) {
        if (seq !== state.computeSeq) return;
        state.computing = false;
        state.result = null;
        state.answer = null;
        state.error = 'the engine did not answer (' + ((err && err.message) || 'network') + ')';
        renderResult();
        emit('result', null);
      });
    };
    if (immediate) run(); else computeTimer = setTimeout(run, COMPUTE_DEBOUNCE);
  }

  // ------------------------------------------------------------------ rendering: grid
  function polDot(polarity, interactive, kind, index) {
    var dot = el('span', {
      class: 'pl-pol', 'data-p': polarity || 'none', title: polarity
        ? 'Polarity: ' + polarity + ' - click to change' : 'Polarity: vacant - click to set',
      role: interactive ? 'button' : null, 'aria-label': 'Slot polarity'
    }, [polarity ? POL_SHORT[polarity] || '' : '']);
    // the letter rides the dot (POL_SHORT); the dot is bigger now, so the glyph grows with it
    dot.style.font = '700 8.5px var(--mono)';
    dot.style.textAlign = 'center';
    dot.style.lineHeight = '9px';
    if (interactive) {
      dot.setAttribute('tabindex', '0');
      dot.addEventListener('click', function (ev) {
        ev.stopPropagation();
        openPolarityMenu(dot, kind, index);
      });
      dot.addEventListener('keydown', function (ev) {
        if (ev.key === 'Enter' || ev.key === ' ') {
          ev.preventDefault();
          ev.stopPropagation();
          openPolarityMenu(dot, kind, index);
        }
      });
    }
    return dot;
  }

  function drainFor(kind, index) {
    var drain = state.result && state.result.capacity && state.result.capacity.drain;
    var rows = (drain && drain.per_slot) || [];
    for (var i = 0; i < rows.length; i++) {
      if (rows[i].kind === kind && rows[i].index === index) return rows[i];
    }
    return null;
  }

  function renderGrid() {
    var grid = $('plGrid');
    if (!grid) return;
    clear(grid);
    if (!state.layout.length) {
      grid.appendChild(el('div', { class: 'dim small', text: 'Pick equipment to start.' }));
      return;
    }
    var normal = state.layout.filter(function (s) { return s.kind === 'normal'; });
    var aux = state.layout.filter(function (s) { return s.kind !== 'normal'; });
    normal.forEach(function (slot) { grid.appendChild(slotEl(slot)); });
    if (aux.length) {
      var strip = el('div', { class: 'pl-grid-aux' });
      aux.forEach(function (slot) { strip.appendChild(slotEl(slot)); });
      grid.appendChild(strip);
    }
    var filled = 0;
    for (var i = 0; i < normal.length; i++) {
      if (slotMod(normal[i].kind, normal[i].index)) filled++;   // the layout has no mod field
    }
    $('plGridMeta').textContent = '· ' + filled + ' of ' + normal.length + ' filled' +
      (aux.length ? ' + ' + aux.map(function (s) { return SLOT_LABEL[s.kind].toLowerCase(); })
        .join(' / ') : '');
  }

  function slotEl(slot) {
    var kind = slot.kind, index = slot.index;
    var entry = slotMod(kind, index);
    var polarity = slotPolarity(kind, index);
    var unlocked = slotIsOpen(kind);
    var drain = drainFor(kind, index);
    var label = kind === 'normal' ? 'Slot ' + (index + 1) : SLOT_LABEL[kind];
    var node = el('button', {
      class: 'pl-slot', type: 'button', 'data-kind': kind,
      'data-index': index === null ? '' : index,
      'data-state': !unlocked ? 'blocked' : (entry ? 'filled' : 'empty'),
      'data-focus': state.focused && state.focused.kind === kind &&
        state.focused.index === index ? 'true' : 'false',
      title: label + (entry ? '' : ' (empty)')
    });
    node.appendChild(el('span', { class: 'pl-slot-kind', text: label }));
    node.appendChild(el('span', { class: 'pl-slot-name',
      text: entry ? (modName(entry.id) || '…') : (unlocked ? 'Empty' : 'Locked'),
      title: !unlocked ? 'Needs an Exilus Adapter' : null }));
    if (entry && entry.rank !== null && entry.rank !== undefined) {
      node.appendChild(el('span', { class: 'pl-slot-sub', text: 'R' + entry.rank }));
    }
    if (drain && entry) {
      node.appendChild(el('span', {
        class: 'pl-slot-drain' + (drain.adjustment > 0 ? ' up' : ''),
        text: String(drain.adjusted_drain),
        title: 'Drain ' + drain.raw_drain + ' → ' + drain.adjusted_drain + ' (' + drain.rule + ')'
      }));
    }
    node.appendChild(polDot(polarity, true, kind, index));
    if (entry) {
      // The mod that is in here can be dragged out: to another slot (move, or swap) or onto the
      // library card (remove). Slot order stays real - it is what element combination reads.
      node.setAttribute('draggable', 'true');
      node.addEventListener('dragstart', function (ev) { onInstalledDragStart(kind, index, ev); });
      node.addEventListener('dragend', onDragEnd);
      var sup = (modRowById(entry.id) || {}).support || {};
      var refused = (sup.unmodelled || 0) + (sup.conditional || 0);
      if (refused) {
        var chip = el('span', { class: 'pl-slot-refused', role: 'button', tabindex: '0',
          title: (sup.unmodelled || 0) + ' stat(s) the engine does not model'
            + (sup.conditional ? ', ' + sup.conditional + ' conditional effect(s)' : '')
            + ' - click to see which', text: refused + ' not calculated' });
        chip.addEventListener('click', function (ev) {
          ev.stopPropagation();
          emit('tip', { id: entry.id, anchor: chip });
        });
        chip.addEventListener('keydown', function (ev) {
          if (ev.key === 'Enter' || ev.key === ' ') {
            ev.preventDefault();
            emit('tip', { id: entry.id, anchor: chip });
          }
        });
        node.appendChild(chip);
      }
      var x = el('span', { class: 'pl-slot-x', role: 'button', tabindex: '-1',
        'aria-label': 'Remove ' + (modName(entry.id) || 'mod'), text: '✕' });
      x.addEventListener('click', function (ev) {
        ev.stopPropagation();
        clearSlot(kind, index);
        renderGrid();
        renderInspector();
      });
      node.appendChild(x);
    }
    node.addEventListener('click', function () {
      state.focused = { kind: kind, index: index };
      state.selectedMod = null;
      renderGrid();
      renderInspector();
      emit('state', state);
    });
    // Every slot answers a drag, locked ones included: a locked slot must refuse *here* (and stop
    // the event), not quietly hand the drop to the grid's "put it in the first free slot" rule.
    node.addEventListener('dragover', function (ev) { onSlotDragOver(ev, kind, index, node); });
    node.addEventListener('dragleave', function () { node.removeAttribute('data-drop'); });
    node.addEventListener('drop', function (ev) { onSlotDrop(ev, kind, index, node); });
    return node;
  }

  function modName(id) {
    var row = modRowById(id);
    return row ? row.name : null;
  }
  function modRowById(id) {
    for (var i = 0; i < state.library.length; i++) {
      if (state.library[i].id === id) return state.library[i];
    }
    return null;
  }

  // The selection strip: what the focused slot is, its rank, its polarity, and how to remove it.
  function renderInspector() {
    var hint = $('plGridHint');
    if (!hint) return;
    clear(hint);
    var f = state.focused;
    if (!f) {
      hint.appendChild(el('kbd', { text: '1-8' }));
      hint.appendChild(document.createTextNode(' focus a slot · click a mod'));
      return;
    }
    var entry = slotMod(f.kind, f.index);
    var label = f.kind === 'normal' ? 'Slot ' + (f.index + 1) : SLOT_LABEL[f.kind];
    hint.appendChild(el('b', { text: label }));
    if (!entry) {
      hint.appendChild(document.createTextNode(' is empty'));
      return;
    }
    var row = modRowById(entry.id);
    hint.appendChild(document.createTextNode(' · '));
    hint.appendChild(el('span', { class: 'pl-hintkey', text: row ? row.name : entry.id }));
    var maxRank = row && row.max_rank !== null && row.max_rank !== undefined ? row.max_rank : 10;
    var range = el('input', { type: 'range', min: '0', max: String(maxRank), step: '1',
      value: String(entry.rank), 'aria-label': 'Mod rank', class: 'pl-rank-range' });
    range.addEventListener('input', function () {
      setModRank(f.kind, f.index, Number(range.value));
      rankValue.textContent = 'R' + range.value;
    });
    var rankValue = el('span', { class: 'pl-hintkey', text: 'R' + entry.rank });
    hint.appendChild(range);
    hint.appendChild(rankValue);
    if (row && row.drain_max !== null && row.drain_max !== undefined) {
      hint.appendChild(el('span', { class: 'dim small',
        text: ' drain ' + row.base_drain + '+' + entry.rank + ' → max ' + row.drain_max }));
    }
    var del = el('button', { class: 'pl-mini btn', type: 'button', 'data-icon': 'x', text: 'Remove' });
    del.addEventListener('click', function () {
      clearSlot(f.kind, f.index);
      renderGrid();
      renderInspector();
    });
    hint.appendChild(del);
    if (window.wfmIcons && window.wfmIcons.render) window.wfmIcons.render(hint);
  }

  function flashHint(text) {
    var hint = $('plGridHint');
    if (!hint) return;
    clear(hint);
    hint.appendChild(el('span', { class: 'pl-hintwarn', text: text }));
    setTimeout(renderInspector, 2600);
  }

  // ------------------------------------------------------------------ polarity menu
  var popMenu = null;
  function closePolarityMenu() {
    if (popMenu && popMenu.parentNode) popMenu.parentNode.removeChild(popMenu);
    popMenu = null;
  }
  function openPolarityMenu(anchor, kind, index) {
    closePolarityMenu();
    var slot = layoutSlot(kind, index);
    var def = slot ? (slot.default_polarity || null) : null;
    var current = slotPolarity(kind, index);
    var box = el('div', { class: 'pl-polmenu card' });
    box.appendChild(el('div', { class: 'pl-polmenu-head dim small',
      text: KIND_LABEL[state.equipment.kind] + ' · ' +
        (kind === 'normal' ? 'Slot ' + (index + 1) : SLOT_LABEL[kind]) + ' polarity' }));
    function option(label, value, extra) {
      var row = el('button', { type: 'button', class: 'pl-polopt', 'data-on':
        (value === current ? 'true' : 'false') });
      row.appendChild(polDot(value, false));
      row.appendChild(el('span', { text: label }));
      if (extra) row.appendChild(el('span', { class: 'dim small', text: extra }));
      row.addEventListener('click', function () {
        setPolarity(kind, index, value);
        closePolarityMenu();
        renderGrid();
        renderInspector();
      });
      return row;
    }
    if (def) {
      box.appendChild(option('As shipped (' + def + ')', def, 'default'));
    } else {
      box.appendChild(option('As shipped (vacant)', null, 'default'));
    }
    if (def) box.appendChild(option('Vacant', null, 'clears it - costs a Forma'));
    POLARITIES.forEach(function (p) {
      if (p === def) return;
      box.appendChild(option(p, p));
    });
    document.body.appendChild(box);
    var r = anchor.getBoundingClientRect();
    box.style.left = Math.min(window.innerWidth - box.offsetWidth - 10, r.left) + 'px';
    box.style.top = (r.bottom + 4) + 'px';
    popMenu = box;
  }

  // ------------------------------------------------------------------ drag & drop + preview
  var dragMod = null;            // a library row on its way into a slot
  var dragInstalled = null;      // {kind, index} of an installed mod being dragged around
  var previewTimer = null;
  function onDragStart(modRow, ev) {
    dragMod = modRow;
    dragInstalled = null;
    state.selectedMod = modRow.id;
    if (ev && ev.dataTransfer) {
      ev.dataTransfer.effectAllowed = 'copy';
      try { ev.dataTransfer.setData('text/plain', modRow.name); } catch (e) {}
    }
    emit('state', state);
  }
  function onInstalledDragStart(kind, index, ev) {
    dragInstalled = { kind: kind, index: index };
    dragMod = null;
    state.focused = { kind: kind, index: index };
    if (ev && ev.dataTransfer) {
      ev.dataTransfer.effectAllowed = 'move';
      var row = modRowById((slotMod(kind, index) || {}).id);
      try { ev.dataTransfer.setData('text/plain', row ? row.name : 'mod'); } catch (e) {}
    }
    // The grid is deliberately not re-rendered here: replacing the node the browser is dragging
    // from can cancel a native drag. The body class does the visual work.
    document.body.classList.add('pl-dragging-installed');
  }
  function onDragEnd() {
    dragMod = null;
    dragInstalled = null;
    hidePreview();
    document.body.classList.remove('pl-dragging-installed');
    var lib = $('plLibrary');
    if (lib) lib.classList.remove('pl-lib-drop');
    var spots = document.querySelectorAll('.pl-slot[data-drop]');
    Array.prototype.forEach.call(spots, function (n) { n.removeAttribute('data-drop'); });
  }
  // One legality rule for every way a mod can arrive (click, keyboard, auto, drag): the class
  // rules from the library row, plus the Exilus slot's *live* adapter switch. The layout's own
  // `unlocked` only says whether the item has the slot at all.
  // Whether a slot can take anything at all. For the Exilus slot that is the toolbar's adapter
  // switch and nothing else - server.py's slot layout hard-codes unlocked: false for Exilus, so
  // the layout's own field must never be read for that kind (it would say "locked" forever).
  function slotIsOpen(kind) {
    if (kind === 'exilus') return !!state.storage.exilus_unlocked;
    var slot = layoutSlot(kind, null);
    return !slot || slot.unlocked !== false;
  }

  function slotLegal(kind, index, modRow) {
    return slotIsOpen(kind) && modFitsSlot(modRow, kind);
  }

  function onSlotDragOver(ev, kind, index, node) {
    if (!dragMod && !dragInstalled) return;
    ev.preventDefault();
    if (ev.stopPropagation) ev.stopPropagation();
    var ok;
    if (dragInstalled) {
      var row = modRowById((slotMod(dragInstalled.kind, dragInstalled.index) || {}).id);
      ok = !!row && slotLegal(kind, index, row);
      if (ev.dataTransfer) ev.dataTransfer.dropEffect = 'move';
    } else {
      ok = slotLegal(kind, index, dragMod);
      if (ev.dataTransfer) ev.dataTransfer.dropEffect = ok ? 'copy' : 'none';
      if (ok) queuePreview(kind, index, node);
    }
    node.setAttribute('data-drop', ok ? (dragInstalled ? 'move' : 'ok') : 'bad');
  }
  // Moving an installed mod keeps slot order real: the mod lands in the target slot and whatever
  // was there takes the vacated one.
  function moveInstalled(kind, index) {
    var from = dragInstalled;
    if (!from) return;
    if (from.kind === kind && from.index === index) return;
    var cfg = activeConfig();
    var fromKey = slotKey(from.kind, from.index);
    var toKey = slotKey(kind, index);
    var moved = cfg.slots[fromKey];
    if (!moved) return;
    var row = modRowById(moved.id);
    if (!row || !slotLegal(kind, index, row)) {      // one legality rule, moves included
      flashHint((row ? row.name : 'that mod') + ' does not go in a ' + SLOT_LABEL[kind]);
      return;
    }
    var replaced = cfg.slots[toKey];
    if (replaced) {
      // A swap moves the displaced mod the other way, so that half needs the same check: an Aura
      // mod cannot land in a normal slot just because a normal mod was dragged onto the Aura one.
      var replacedRow = modRowById(replaced.id);
      if (!replacedRow || !slotLegal(from.kind, from.index, replacedRow)) {
        flashHint((replacedRow ? replacedRow.name : 'that mod') + ' does not go in ' +
          layoutLabel(from.kind, from.index));
        return;
      }
    }
    delete cfg.slots[fromKey];
    cfg.slots[toKey] = moved;
    if (replaced) cfg.slots[fromKey] = replaced;
    saveStorage();
    state.focused = { kind: kind, index: index };
    recompute();
    flashHint((row ? row.name : 'mod') + ' → ' + (kind === 'normal' ? 'slot ' + (index + 1)
      : SLOT_LABEL[kind]) + (replaced ? ' (swapped)' : ''));
  }
  function queuePreview(kind, index, node) {
    if (previewTimer) clearTimeout(previewTimer);
    previewTimer = setTimeout(function () {
      previewTimer = null;
      var next = nextBuildWith(kind, index, dragMod);
      showPreviewFor(next, dragMod.name + ' → ' + (kind === 'normal' ? 'slot ' + (index + 1)
        : SLOT_LABEL[kind]), node);
    }, PREVIEW_DEBOUNCE);
  }
  function onSlotDrop(ev, kind, index, node) {
    if (!dragMod && !dragInstalled) return;
    ev.preventDefault();
    if (ev.stopPropagation) ev.stopPropagation();      // the grid's rules do not apply to a slot
    node.removeAttribute('data-drop');
    if (dragInstalled) {
      var movingRow = modRowById((slotMod(dragInstalled.kind, dragInstalled.index) || {}).id);
      if (!movingRow || !slotLegal(kind, index, movingRow)) {
        flashHint(layoutLabel(kind, index) + ' takes no ' + (movingRow ? movingRow.name : 'mod')
          + (slotIsOpen(kind) ? '' : ' until the slot is unlocked'));
        onDragEnd();
        return;
      }
      moveInstalled(kind, index);
      onDragEnd();
      return;
    }
    var mod = dragMod;
    if (!slotLegal(kind, index, mod)) {
      flashHint(!slotIsOpen(kind)
        ? layoutLabel(kind, index) + ' is locked - unlock it first'
        : mod.name + ' does not go in a ' + kind + ' slot');
      onDragEnd();
      return;
    }
    install(kind, index, mod);
    onDragEnd();
  }

  function layoutLabel(kind, index) {
    return kind === 'normal' ? 'Slot ' + (index + 1) : (SLOT_LABEL[kind] || kind);
  }

  function cloneConfigSlots(letter, mutate) {
    var cfg = state.storage.configs[letter];
    var copy = { slots: {}, polarities: {} };
    Object.keys(cfg.slots || {}).forEach(function (k) {
      copy.slots[k] = { id: cfg.slots[k].id, rank: cfg.slots[k].rank };
    });
    Object.keys(cfg.polarities || {}).forEach(function (k) { copy.polarities[k] = cfg.polarities[k]; });
    if (mutate) mutate(copy);
    return copy;
  }

  // A hypothetical build for a change the user has not made yet: the page builds it, the
  // engine answers it (no number is guessed here).
  function nextBuildWith(kind, index, modRow, rank, polarity) {
    var letter = state.storage.active_config;
    var nextCfg = cloneConfigSlots(letter, function (copy) {
      copy.slots[slotKey(kind, index)] = {
        id: modRow.id, rank: rank === undefined || rank === null ? modRow.max_rank : rank };
      if (polarity !== undefined) copy.polarities[slotKey(kind, index)] = polarity || '';
    });
    var current = state.storage.configs[letter];
    state.storage.configs[letter] = nextCfg;
    var out = build();
    state.storage.configs[letter] = current;
    return out;
  }

  var previewSeq = 0;
  function showPreviewFor(next, title, anchor) {
    var base = build();
    var seq = ++previewSeq;
    api.preview(base, next).then(function (out) {
      if (seq !== previewSeq) return;                  // the pointer has moved on since
      if (!out || out.ok === false && !out.diff) {
        renderPreview({ title: title, error: out && out.error || 'preview failed' });
        return;
      }
      renderPreview({ title: title, diff: out.diff, side: out.b, base: out.a });
    });
  }

  function renderPreview(payload) {
    var box = $('plPreview');
    if (!box) return;
    clear(box);
    box.hidden = false;
    var side = payload.side || {};
    var validation = (side.validation || {});
    var errors = validation.errors || [];
    var used = side.capacity_used;
    var total = side.capacity && side.capacity.capacity ? side.capacity.capacity.total : null;
    var over = errors.some(function (e) { return e.code === 'capacity_exceeded'; });
    var tight = !over && used !== null && total !== null && used === total;
    box.setAttribute('data-fit', over ? 'no' : (tight ? 'tight' : 'yes'));
    box.appendChild(el('div', { class: 'pl-preview-title',
      text: (payload.title || 'Change') + (over ? ' - does not fit' : '') }));
    if (payload.error) {
      box.appendChild(el('div', { class: 'pl-preview-why', text: payload.error }));
      return;
    }
    var grid = el('div', { class: 'pl-preview-grid' });
    (payload.diff || []).slice(0, 9).forEach(function (d) {
      grid.appendChild(el('span', { class: 'k', text: fmt.label(d.stat) }));
      grid.appendChild(el('span', { class: 'b', text: fmt.num(d.a) }));
      grid.appendChild(el('span', { class: 'a', text: fmt.num(d.b) +
        (d.delta > 0 ? ' ↑' : d.delta < 0 ? ' ↓' : '') }));
    });
    if (!(payload.diff || []).length) {
      grid.appendChild(el('span', { class: 'k', text: 'nothing changes' }));
    }
    box.appendChild(grid);
    if (payload.base && payload.side) {
      var capLine = 'capacity ' + fmt.num(payload.base.capacity_used) + ' → ' + fmt.num(used) +
        (total !== null ? ' / ' + total : '');
      box.appendChild(el('div', { class: 'pl-preview-foot', text: capLine }));
    }
    if (errors.length) {
      box.appendChild(el('div', { class: 'pl-preview-why', text: 'engine: ' +
        errors.map(function (e) { return e.code; }).join(', ') }));
    }
  }

  function hidePreview() {
    if (previewTimer) { clearTimeout(previewTimer); previewTimer = null; }
    previewSeq++;                                    // a late answer must not reopen the card
    var box = $('plPreview');
    if (box) { box.hidden = true; clear(box); }
  }

  // ------------------------------------------------------------------ rendering: capacity + validation
  /* Before an item is chosen there is nothing to build, so the workspace, the controls and the
     diagnostics step aside and the page invites the one useful action. The class drives it all
     (see the .pl-empty block in planner.css); the hero itself carries the button that opens the
     picker. */
  function renderEmptyState() {
    var has = !!state.storage.equipment_id;
    document.body.classList.toggle('pl-no-equip', !has);
    var diag = $('plDiag');
    if (diag) diag.hidden = !has;
    var chip = $('plHeadRank');
    if (chip && !has) { chip.hidden = true; chip.textContent = ''; }
  }

  function renderCapacity() {
    renderEmptyState();
    if (!state.result) {
      $('plCapUsed').textContent = '—';
      $('plCapTotal').textContent = '—';
      $('plCapUsed').className = 'pl-cap-num mono';
      $('plCapBar').className = 'pl-cap-bar';
      $('plCapFill').setAttribute('style', 'width:0%');
      $('plCapBar').setAttribute('aria-label', 'Capacity unknown');
      $('plCapNote').textContent = state.error ? 'no answer from the engine'
        : (state.answer && state.answer.validation ? 'the engine refused this build - see Validation' : '');
      return;
    }
    var out = state.result;
    var cap = out.capacity && out.capacity.capacity ? out.capacity.capacity : null;
    var used = out.capacity_used === null || out.capacity_used === undefined ? 0 : out.capacity_used;
    var total = cap ? cap.total : null;
    $('plCapUsed').textContent = fmt.num(used);
    $('plCapTotal').textContent = total === null ? '—' : fmt.num(total);
    var over = total !== null && used > total;
    $('plCapUsed').className = 'pl-cap-num mono' + (over ? ' over' : '');
    var bar = $('plCapBar');
    bar.className = 'pl-cap-bar' + (over ? ' over' : (total !== null && used === total ? ' warn' : ''));
    // The engine sends used_pct with the drain total (builds/capacity.py): same two numbers,
     // divided once, in the one place allowed to divide them.
    var drain = out.capacity && out.capacity.drain ? out.capacity.drain : null;
    var pct = drain && drain.used_pct !== undefined && drain.used_pct !== null ? drain.used_pct : 0;
    $('plCapFill').setAttribute('style', 'width:' + pct + '%');
    bar.setAttribute('aria-label', 'Capacity ' + used + ' of ' + (total === null ? '?' : total));
    var notes = [];
    if (cap) {
      if (cap.orokin_doubled) notes.push('catalyst/reactor x2');
      if (cap.aura_bonus) notes.push('+' + fmt.num(cap.aura_bonus) + ' aura');
      if (cap.stance_bonus) notes.push('+' + fmt.num(cap.stance_bonus) + ' stance');
      if (cap.floored_by_mastery) notes.push('MR floor ' + fmt.num(cap.minimum_from_mastery));
      if (cap.equipment_rank !== null && cap.max_rank !== null &&
          cap.equipment_rank < cap.max_rank) notes.push('rank ' + cap.equipment_rank + '/' + cap.max_rank);
    }
    $('plCapNote').textContent = notes.join(' · ');
  }

  function renderValidation() {
    // The engine's refusals are the point of this card, so it reads the whole answer - a build
    // that does not fit has validation.errors and no numeric result, and both facts matter.
    var out = state.result || state.answer;
    if (!out) {
      var empty = $('plValidity');
      clear(empty);
      $('plValidityMeta').textContent = '';
      $('plValidityMeta').removeAttribute('data-k');
      empty.appendChild(el('div', { class: 'dim small',
        text: state.error ? 'No answer from the engine.' : 'Nothing to check yet.' }));
      return;
    }
    var v = out.validation || {};
    var errors = v.errors || [];
    var warnings = v.warnings || [];
    var box = $('plValidity');
    clear(box);
    $('plValidityMeta').setAttribute('data-k',
      errors.length ? 'error' : (warnings.length ? 'warning' : 'ok'));
    $('plValidityMeta').textContent = errors.length || warnings.length
      ? '· ' + errors.length + ' error' + (errors.length === 1 ? '' : 's') +
        (warnings.length ? ', ' + warnings.length + ' warning' + (warnings.length === 1 ? '' : 's') : '')
      : (out.ok ? '· clean' : '');
    if (!errors.length && !warnings.length) {
      if (out.ok || out.validation) {
        box.appendChild(el('div', { class: 'pl-val-row', 'data-k': 'ok' }, [
          el('span', { class: 'i', 'data-icon': 'check-circle' }),
          el('div', {}, [el('span', { text: out.ok ? 'This build is valid.' : 'Nothing to check yet.' })])
        ]));
      }
      return;
    }
    errors.concat(warnings).forEach(function (row) {
      var kind = errors.indexOf(row) >= 0 ? 'error' : 'warning';
      box.appendChild(el('div', { class: 'pl-val-row', 'data-k': kind }, [
        el('span', { class: 'i', 'data-icon': kind === 'error' ? 'x-circle' : 'warning-circle' }),
        el('div', {}, [
          el('span', { text: row.message || row.code }),
          el('div', { class: 'pl-val-code',
            text: ['code', row.code, row.field,
              row.mod ? (modName(row.mod) || row.mod) : null].filter(Boolean).join(' · ') })
        ])
      ]));
    });
  }

  function renderUnsupported() {
    var box = $('plUnsupported');
    clear(box);
    if (!state.result) {
      $('plUnsupportedMeta').textContent = '';
      box.appendChild(el('div', { class: 'dim small',
        text: state.error ? 'No answer from the engine.'
          : (state.answer && state.answer.validation ? 'the engine refused this build'
            : 'Nothing to check yet.') }));
      return;
    }
    var out = state.result;
    var rows = out.unsupported || [];
    $('plUnsupportedMeta').textContent = rows.length ? '· ' + rows.length + ' mechanic' +
      (rows.length === 1 ? '' : 's') : '';
    if (!rows.length) {
      box.appendChild(el('div', { class: 'dim small',
        text: 'Everything this build uses is calculated.' }));
      return;
    }
    rows.forEach(function (row) {
      box.appendChild(el('div', { class: 'pl-unsup-row' }, [
        el('div', { class: 'pl-unsup-name', text: row.label || row.code }),
        el('div', { class: 'pl-unsup-why', text: row.reason || '' })
      ]));
    });
  }

  // The conditions the engine evaluated, in the engine's own words. This page decides nothing:
  // it prints the four-state vocabulary (satisfied / not_satisfied / unknown / unsupported) and
  // the reason the engine gave.
  function renderEvaluation() {
    var box = $('plEvalBody');
    if (!box) return;
    clear(box);
    var chip = $('plStatsEval');
    var meta = $('plEvalMeta');
    var answer = state.result;
    var ev = answer && answer.evaluation;
    var rows = (answer && answer.conditions) || [];
    if (!ev) {
      if (meta) meta.textContent = '';
      if (chip) { chip.hidden = true; chip.textContent = ''; }
      box.appendChild(el('div', { class: 'dim small',
        text: state.error ? 'No answer from the engine.'
          : (state.answer && state.answer.validation ? 'the engine refused this build'
            : 'Nothing to evaluate yet.') }));
      return;
    }
    if (meta) {
      // The refused-mechanic count belongs here too: it is the other half of the engine's answer,
      // and a reader should not have to open a second card to learn that both facts exist.
      meta.textContent = '· ' + ev.state.replace('_', ' ') +
        (ev.unsupported_effects ? ' · ' + ev.unsupported_effects + ' refused' : '') +
        (rows.length ? ' · ' + rows.length + (rows.length === 1 ? ' condition' : ' conditions') : '');
      meta.setAttribute('data-k', ev.state);
    }
    if (chip) {
      // `not_evaluated` is its own answer: this engine has no condition model, so nothing here was
      // withheld and nothing here was checked either. It must not read as `deterministic`.
      chip.hidden = ev.state === 'deterministic';
      chip.textContent = ev.state === 'deterministic' ? ''
        : (ev.state + (ev.withheld && ev.withheld.length
          ? ': ' + ev.withheld.join(', ') + ' not stated' : ''));
      chip.setAttribute('data-k', ev.state);
      chip.setAttribute('title', ev.state === 'refused' ? 'strict: stats withheld'
        : (ev.state === 'not_evaluated' ? 'no condition model' : 'withheld: input not stated'));
    }
    if (ev.context_ignored && ev.context_ignored.length) {
      box.appendChild(el('div', { class: 'pl-eval-note', 'data-k': 'warn',
        text: 'ignored input: ' + ev.context_ignored.join(', ') }));
    }
    if (ev.unused && ev.unused.length) {
      // A stated input this engine has no model for: a refusal, not silence.
      box.appendChild(el('div', { class: 'pl-eval-note', 'data-k': 'warn',
        text: 'not modelled here: ' + ev.unused.join(', ') }));
    }
    if (ev.refused_stats && ev.refused_stats.length) {
      box.appendChild(el('div', { class: 'pl-eval-note', 'data-k': 'error',
        text: 'refused under strict evaluation: ' + ev.refused_stats.join(', ') }));
    }
    if (!rows.length) {
      box.appendChild(el('div', { class: 'dim small',
        text: ev.state === 'deterministic'
          ? 'every number here is unconditional'
          : 'no condition evaluated' }));
      return;
    }
    rows.forEach(function (row) {
      var title = (row.state === 'unknown'
        ? 'condition unresolved'
        : row.state === 'unsupported'
          ? 'mechanic not modelled'
          : row.state === 'not_satisfied'
            ? 'known false: a reported zero'
            : 'holds here');
      box.appendChild(el('div', { class: 'pl-eval-row', 'data-k': row.state, title: title }, [
        el('div', { class: 'pl-eval-head' }, [
          el('span', { class: 'pl-eval-name', text: row.condition || 'condition' }),
          el('span', { class: 'pl-eval-state', 'data-k': row.state, text: row.state })
        ]),
        el('div', { class: 'pl-eval-why', text: row.reason || '' }),
        el('div', { class: 'pl-eval-in', text: [
          row.inputs ? Object.keys(row.inputs).map(function (k) {
            return k + '=' + row.inputs[k];
          }).join(' · ') : '',
          row.reason_code ? 'code ' + row.reason_code : ''
        ].filter(Boolean).join(' · ') })
      ]));
    });
    if (ev.mode && ev.mode !== 'stated_inputs') {
      box.appendChild(el('div', { class: 'pl-eval-note', text: 'evaluation: ' + ev.mode }));
    }
  }

  // Phase 5: what the engine answered against the stated target, and the riders it considered.
  // Every figure is printed from the last /api/planner/compute answer - the page derives nothing,
  // and a withheld figure prints as withheld, never as a zero.
  function renderTargetOut() {
    var box = $('plTargetOut');
    if (!box) return;
    clear(box);
    var answer = state.result;
    var td = answer && answer.result && answer.result.target_damage;
    var ev = (answer && answer.evaluation) || {};
    if (!td) {
      var rows = (answer && answer.conditions) || [];
      for (var i = 0; i < rows.length; i++) {
        if (rows[i].condition === 'target_damage') {
          box.appendChild(el('div', { class: 'pl-eval-why',
            text: 'target damage: ' + rows[i].state + ' - ' + rows[i].reason }));
          break;
        }
      }
    } else {
      var head = [];
      // The engine's own label, or no clause at all: 'vs target' is a word the engine never sent.
      if (td.faction_label) head.push('vs ' + td.faction_label);
      if (td.protection) head.push('lands on ' + td.protection);
      if (td.armor) {
        head.push('armour ' + fmt.num(td.armor.stated) +
          (td.armor.effective !== td.armor.stated ? ' -> ' + fmt.num(td.armor.effective) : ''));
      }
      box.appendChild(el('div', { class: 'pl-eval-in', text: head.join(' · ') }));
      var types = Object.keys(td.per_projectile || {});
      if (types.length) {
        box.appendChild(el('div', { class: 'pl-eval-why', text: types.map(function (k) {
          return k + ' ' + fmt.num(td.per_projectile[k]);
        }).join(' · ') }));
      }
      var line = ['per projectile ' + fmt.num(td.per_projectile_total),
        'per shot ' + fmt.num(td.per_shot_total),
        'crit-expected ' + fmt.num(td.per_shot_expected_crit)];
      box.appendChild(el('div', { class: 'pl-eval-in', text: line.join(' · ') }));
      var pool = answer.result.pool;
      if (pool) {
        box.appendChild(el('div', { class: 'pl-eval-in',
          text: 'pool ' + fmt.num(pool.pool) + ' ' + pool.layer + ' · ' +
            pool.shots_required + ' shots' +
            (pool.expected_shots === null || pool.expected_shots === undefined
              ? '' : ' · ~' + fmt.num(pool.expected_shots) + ' crit-expected') }));
      }
      if (td.dps && td.dps.supported) {
        box.appendChild(el('div', { class: 'pl-eval-why',
          text: 'burst ' + fmt.num(td.dps.burst) + ' DPS · sustained ' + fmt.num(td.dps.sustained) +
            ' DPS' }));
      }
      var why = el('button', { class: 'pl-btn-ghost pl-target-why', type: 'button',
        text: 'why', title: 'the engine\'s step-by-step target trace' });
      why.addEventListener('click', function () {
        if (window.WFMPlanner && window.WFMPlanner.openTrace) {
          window.WFMPlanner.openTrace('target_damage');
        }
      });
      box.appendChild(why);
    }
    ((answer && answer.riders) || []).forEach(function (r) {
      var text = 'On Kill · ' + (r.mod_name || r.mod) + ': ' + r.state;
      if (r.applied) {
        text += ' · ' + r.stacks + ' stack' + (r.stacks === 1 ? '' : 's') + ' · +' +
          fmt.num(r.contribution) + '% ' + r.stat;
        if (r.mode === 'averaged' && r.assumption) text += ' · ' + r.assumption;
      } else if (r.state !== 'satisfied') {
        text += ' - ' + (r.reason || '');
      }
      box.appendChild(el('div', { class: 'pl-eval-why', 'data-k': r.state, text: text }));
    });
    (ev.assumptions || []).forEach(function (a) {
      box.appendChild(el('div', { class: 'pl-eval-note', text: 'assumption: ' + a }));
    });
  }

  function renderResult() {
    renderError();
    renderMrHint();              // the capacity floor comes from the engine's answer
    renderGrid();
    renderInspector();
    renderCapacity();
    renderValidation();
    renderEvaluation();
    renderTargetOut();
    renderUnsupported();
    renderStatus();
    renderForma();                 // a polarity change moves the Forma count, not just the stats
    if (window.wfmIcons && window.wfmIcons.render) window.wfmIcons.render(document.body);
  }

  // No answer, no claims: when the engine did not answer, every panel says so instead of
  // painting zeros and "everything is calculated".
  function renderError() {
    var box = $('plError');
    if (!box) return;
    var msg = state.error
      ? (state.computing ? 'asking the engine…' : String(state.error))
      : '';
    box.textContent = msg;
    box.hidden = !msg;
    box.setAttribute('data-k', state.computing ? 'busy' : 'error');
    document.body.setAttribute('data-planswer', state.result ? 'yes' : 'no');
  }

  function renderStatus() {
    var meta = state.meta;
    if (!meta) return;
    // An unreadable stored build is replaced at boot; say so once, because a silent replacement
    // reads exactly like a save that vanished.
    if (state.rescued) { state.rescued = false; flashHint('stored build unreadable; replaced'); }
    var bits = [];
    if (meta.content_hash) bits.push(meta.content_hash.slice(0, 8));
    if (meta.mods_total) bits.push(meta.mods_total + ' mods');
    if (meta.equipment_total) bits.push(meta.equipment_total + ' items');
    $('plStatus').textContent = 'db ' + bits.join(' · ');
    var foot = 'schema v' + meta.schema_version;
    if (bits[0]) foot += ' · db ' + bits[0];
    $('plFootEngine').textContent = foot;
  }

  // ------------------------------------------------------------------ equipment picker
  var picker = { open: false, q: '', kind: '', rows: [] };
  function renderPickerKinds() {
    var box = $('plEquipKinds');
    clear(box);
    var kinds = [{ kind: '', label: 'All' }].concat((state.meta && state.meta.kinds) || []);
    kinds.forEach(function (k) {
      var b = el('button', { class: 'pl-chip', type: 'button',
        'aria-pressed': picker.kind === k.kind ? 'true' : 'false',
        text: k.label + (k.count ? ' ' + k.count : '') });
      b.addEventListener('click', function () {
        picker.kind = k.kind;
        // Update the pressed state IN PLACE. Rebuilding this row would detach the button the
        // click is still being dispatched on, and the document-level close handler would then
        // see a target that is no longer inside the popover - which closed the picker on every
        // category click. The handler below also runs in the capture phase now, so this cannot
        // come back if a future renderer forgets.
        box.querySelectorAll('.pl-chip').forEach(function (c) {
          c.setAttribute('aria-pressed', c === b ? 'true' : 'false');
        });
        loadPicker();
      });
      box.appendChild(b);
    });
  }
  function renderPicker() {
    var list = $('plEquipList');
    clear(list);
    picker.rows.forEach(function (row) {
      var meta = [];
      if (row.mastery_req) meta.push('MR ' + row.mastery_req);
      if (row.damage_total) meta.push(fmt.num(row.damage_total) + ' dmg');
      if (row.crit_chance) meta.push(fmt.num(row.crit_chance) + '% crit');
      if (row.stats && row.stats.health) meta.push(fmt.num(row.stats.health) + ' hp');
      var b = el('button', { class: 'pl-eq-row', type: 'button', role: 'option',
        'aria-selected': row.id === state.storage.equipment_id ? 'true' : 'false' });
      b.appendChild(el('span', {}, [
        el('span', { class: 'pl-eq-name', text: row.name }),
        el('span', { class: 'pl-eq-kind', text: ' ' + (KIND_LABEL[row.kind] || row.kind) +
          (row.subtype ? ' · ' + row.subtype : '') })
      ]));
      b.appendChild(el('span', { class: 'pl-eq-nums', text: meta.join(' · ') }));
      b.addEventListener('click', function () { selectEquipment(row.id); });
      list.appendChild(b);
    });
    $('plEquipFoot').textContent = picker.rows.length + ' shown';
  }
  var pickerTimer = null;
  var pickerSeq = 0;
  function loadPicker() {
    if (pickerTimer) clearTimeout(pickerTimer);
    pickerTimer = setTimeout(function () {
      pickerTimer = null;
      var seq = ++pickerSeq;
      var asked = picker.q;
      api.equipment(picker.q, picker.kind, 80).then(function (out) {
        if (seq !== pickerSeq || asked !== picker.q) return;   // a newer query owns the list
        picker.rows = (out && out.rows) || [];
        renderPicker();
        $('plEquipFoot').textContent = out && out.error ? out.error
          : picker.rows.length + ' shown of ' + (out.total || 0);
      });
    }, 140);
  }
  function openPicker() {
    picker.open = true;
    show($('plEquipPop'), true);
    $('plEquipBtn').setAttribute('aria-expanded', 'true');
    renderPickerKinds();
    loadPicker();
    $('plEquipSearch').focus();
  }
  function closePicker() {
    picker.open = false;
    show($('plEquipPop'), false);
    $('plEquipBtn').setAttribute('aria-expanded', 'false');
  }

  var libraryCache = {};
  function selectEquipment(key, keepRank) {
    closePicker();
    if (document.activeElement && document.activeElement.blur) document.activeElement.blur();
    $('plEquipBtn').focus();                         // never drop the caret into <body>
    api.item(key).then(function (detail) {
      if (!detail || detail.ok === false) {
        flashHint(detail && detail.error || 'That equipment could not be loaded');
        return;
      }
      state.equipment = detail.equipment;
      state.layout = detail.slots || [];
      state.polaritiesFromExport = !!detail.polarities_from_export;
      var same = state.storage.equipment_id === detail.equipment.id;
      var stored = state.storage.equipment_rank;
      state.storage.equipment_id = detail.equipment.id;
      state.storage.equipment_rank = (keepRank && same && Number.isInteger(stored) &&
        stored >= 0 && stored <= detail.equipment.max_rank) ? stored : null;
      state.focused = null;
      state.selectedMod = null;
      saveStorage();
      $('plEquipName').textContent = detail.equipment.name;
      $('plEquipKind').textContent = KIND_LABEL[detail.equipment.kind] || detail.equipment.kind;
      var bits = [];
      if (detail.equipment.mastery_req) bits.push('MR ' + detail.equipment.mastery_req);
      bits.push('max rank ' + detail.equipment.max_rank);
      if (detail.equipment.damage_total) bits.push(fmt.num(detail.equipment.damage_total) + ' base damage');
      $('plEquipMeta').textContent = bits.join(' · ');
      var rankInput = $('plRank');
      rankInput.max = String(detail.equipment.max_rank);
      rankInput.value = String(state.storage.equipment_rank === null
        ? detail.equipment.max_rank : state.storage.equipment_rank);
      $('plRankMax').textContent = '/' + detail.equipment.max_rank;
      var chip = $('plHeadRank');
      if (chip) {
        var shownRank = state.storage.equipment_rank === null ||
          state.storage.equipment_rank === undefined ? detail.equipment.max_rank
          : state.storage.equipment_rank;
        chip.hidden = false;
        chip.textContent = 'Rank ' + shownRank + ' / ' + detail.equipment.max_rank;
      }
      $('plPolarityNote').textContent = state.polaritiesFromExport ? ''
        : 'This item has no polarities - set them ' +
          'with the polarity dots.';
      emit('equipment', detail);
      loadLibrary(detail.equipment.id);
      recompute(true);
    });
  }

  function loadLibrary(id, includeShadowed) {
    var cacheKey = id + (includeShadowed ? '+shadowed' : '');
    var cached = libraryCache[cacheKey];
    if (cached) {
      state.library = cached.rows;
      state.libraryHidden = cached.hidden;
      state.libraryFor = id;
      state.libraryWithHidden = !!includeShadowed;   // the reveal state belongs to this answer
      renderGrid();
      emit('library', state.library);
      emit('state', state);
      return;
    }
    api.mods(id, includeShadowed).then(function (out) {
      if (!out || out.ok === false) {
        flashHint(out && out.error || 'The mod library could not be loaded');
        return;
      }
      if (state.storage.equipment_id !== id) return;   // the item changed while this was in flight
      libraryCache[cacheKey] = { rows: out.rows || [], hidden: out.hidden || null };
      state.library = libraryCache[cacheKey].rows;
      state.libraryHidden = libraryCache[cacheKey].hidden;
      state.libraryFor = id;
      state.libraryWithHidden = !!includeShadowed;
      renderGrid();                    // slot names and refusal chips wait for the library
      emit('library', state.library);
      emit('state', state);
    });
  }

  // ------------------------------------------------------------------ configs + toolbar
  function renderConfigs() {
    var box = $('plConfigs');
    clear(box);
    CONFIGS.forEach(function (letter) {
      var cfg = state.storage.configs[letter];
      var count = Object.keys(cfg.slots || {}).length;
      var wrap = el('span', { class: 'pl-tab-wrap' });
      var b = el('button', { class: 'pl-tab', type: 'button', role: 'tab',
        'aria-selected': letter === state.storage.active_config ? 'true' : 'false',
        title: 'Config ' + letter + (count ? ' · ' + count + ' mods' : ' · empty'),
        text: letter });
      b.addEventListener('click', function () {
        state.storage.active_config = letter;
        saveStorage();
        renderConfigs();
        recompute();
        emit('state', state);
      });
      wrap.appendChild(b);
      if (count) wrap.appendChild(el('span', { class: 'pl-tab-count', text: String(count) }));
      box.appendChild(wrap);
    });
    if (window.wfmIcons && window.wfmIcons.render) window.wfmIcons.render(box);
  }

  // What the user stated, echoed back - no interpretation, no defaults invented.
  function renderTargetMeta(t) {
    var node = $('plTargetMeta');
    if (!node) return;
    t = t || targetState();
    var bits = [];
    if (t.faction) bits.push('faction: ' + t.faction);
    if (statedNumber(t.viral_stacks) !== null) bits.push('viral ' + statedNumber(t.viral_stacks));
    if (t.protection) bits.push('on ' + t.protection);
    if (statedNumber(t.armour) !== null) bits.push('armour ' + statedNumber(t.armour));
    if (statedNumber(t.heat_strip) !== null) bits.push('heat strip ' + t.heat_strip + '%');
    var poolBits = [];
    if (statedNumber(t.pool_health) !== null) poolBits.push('health ' + fmt.num(t.pool_health));
    if (statedNumber(t.pool_shields) !== null) poolBits.push('shields ' + fmt.num(t.pool_shields));
    if (statedNumber(t.pool_overguard) !== null) {
      poolBits.push('overguard ' + fmt.num(t.pool_overguard));
    }
    if (poolBits.length) bits.push('pool ' + poolBits.join(' '));
    if (statedNumber(t.corrosive_stacks) !== null) {
      bits.push('corrosive ' + statedNumber(t.corrosive_stacks));
    }
    if (statedNumber(t.kill_stacks) !== null) bits.push('on-kill ' + statedNumber(t.kill_stacks));
    if (statedNumber(t.kill_uptime) !== null) bits.push('uptime ' + statedNumber(t.kill_uptime) + '%');
    if (statedNumber(t.shot) !== null) bits.push('shot ' + statedNumber(t.shot));
    if (t.strict) bits.push('strict');
    node.textContent = bits.length ? bits.join(' · ') : 'nothing stated';
  }

  function setToggle(btn, on, label) {
    btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    if (label) label.textContent = on ? 'on' : 'off';
  }

  function renderToolbar() {
    setToggle($('plOrokin'), !!state.storage.orokin, $('plOrokinVal'));
    setToggle($('plExilus'), !!state.storage.exilus_unlocked, $('plExilusVal'));
    $('plMr').value = String(state.storage.mastery_rank);
    var t = targetState();
    $('plTargetFaction').value = t.faction || '';
    var heatSelect = $('plTargetHeat');
    if (heatSelect) {
      heatSelect.value = (t.heat_strip === null || t.heat_strip === undefined)
        ? '' : String(t.heat_strip);
    }
    var poolBoxes = [['plPoolHealth', 'pool_health'], ['plPoolShields', 'pool_shields'],
      ['plPoolOverguard', 'pool_overguard']];
    for (var pb = 0; pb < poolBoxes.length; pb++) {
      var box = $(poolBoxes[pb][0]);
      if (!box) continue;
      var stored = statedNumber(t[poolBoxes[pb][1]]);
      box.value = stored === null ? '' : String(stored);
    }
    $('plTargetStacks').value = (t.viral_stacks === null || t.viral_stacks === undefined)
      ? '' : String(t.viral_stacks);
    $('plTargetProtection').value = t.protection || '';
    $('plTargetShot').value = (t.shot === null || t.shot === undefined) ? '' : String(t.shot);
    $('plTargetArmor').value = (t.armour === null || t.armour === undefined) ? '' : String(t.armour);
    $('plTargetCorrosive').value = (t.corrosive_stacks === null || t.corrosive_stacks === undefined)
      ? '' : String(t.corrosive_stacks);
    $('plKillStacks').value = (t.kill_stacks === null || t.kill_stacks === undefined)
      ? '' : String(t.kill_stacks);
    $('plKillUptime').value = (t.kill_uptime === null || t.kill_uptime === undefined)
      ? '' : String(t.kill_uptime);
    setToggle($('plStrict'), !!t.strict, $('plStrictVal'));
    renderTargetMeta(t);
    var max = state.equipment ? state.equipment.max_rank : 30;
    $('plRank').value = String(state.storage.equipment_rank === null ? max
      : state.storage.equipment_rank);
    renderConfigs();
    renderMrHint();
    renderForma();
  }

  // "Forma": how many of the item's slots this config rewrites. Zero means the config runs on the
  // item exactly as it comes - the page says which slots differ in the capacity card.
  function renderForma() {
    var n = formaUsed();
    var box = $('plForma');
    if (box) box.textContent = String(n);
    var note = $('plFormaNote');
    if (note) {
      note.textContent = n === 0 ? 'matches the item'
        : (n === 1 ? '1 slot changed vs the item' : n + ' slots changed vs the item');
    }
    var chip = $('plFormaChip');
    if (chip) {
      var names = polarityChanges().map(function (c) {
        return c.label + ': ' + (c.polarity ? POL_SHORT[c.polarity] || c.polarity : 'none')
          + ' (item: ' + (c.base ? POL_SHORT[c.base] || c.base : 'none') + ')';
      });
      chip.title = names.length ? 'Forma spent on\n' + names.join('\n')
        : 'This config uses the item\'s own polarities';
    }
  }

  // The capacity floor belongs to builds/capacity.py (15 + 1 per 2 MR, +1 per Legendary Rank);
  // this page only prints the figure the engine sent, and says when it is the binding one.
  function renderMrHint() {
    var node = $('plMrFloor');
    if (!node) return;
    var cap = state.result && state.result.capacity && state.result.capacity.capacity;
    var floor = cap ? cap.minimum_from_mastery : null;
    if (floor === null || floor === undefined) {
      node.textContent = '';
      node.setAttribute('title', 'the floor the engine reports');
      return;
    }
    node.textContent = 'capacity floor ' + floor + (cap.floored_by_mastery ? ' - in use' : '');
    node.setAttribute('title', cap.floored_by_mastery
      ? 'held up by the Mastery floor'
      : 'rank and supercharger beat the floor');
  }

  // ------------------------------------------------------------------ keyboard + wiring
  function wire() {
    $('plEquipBtn').addEventListener('click', function () {
      if (picker.open) closePicker(); else openPicker();
    });
    $('plEmptyPick').addEventListener('click', function () {
      openPicker();
      $('plEquipSearch').focus();
    });
    $('plEquipSearch').addEventListener('input', function (e) {
      picker.q = e.target.value;
      loadPicker();
    });
    $('plEquipSearch').addEventListener('keydown', function (e) {
      if (e.key === 'Escape') {
        e.stopPropagation();                         // do not let the document blur the button
        closePicker();
        $('plEquipBtn').focus();
        return;
      }
      if (e.key === 'Enter') {
        var first = $('plEquipList').querySelector('.pl-eq-row');
        if (first) first.click();
      }
    });
    $('plRank').addEventListener('change', function (e) {
      var max = state.equipment ? state.equipment.max_rank : 30;
      var v = Math.max(0, Math.min(max, Number(e.target.value) || 0));
      state.storage.equipment_rank = v === max ? null : v;
      e.target.value = String(v);
      saveStorage();
      recompute();
    });
    $('plMr').addEventListener('change', function (e) {
      var v = Math.max(0, Math.min(40, Number(e.target.value) || 0));
      state.storage.mastery_rank = v;
      e.target.value = String(v);
      renderMrHint();
      saveStorage();
      recompute();
    });
    // Phase 4 target controls: state an input, persist it, and let the engine answer. Each one
    // is stored as stated (or as an empty string), never as a substitute value.
    // An input's value is a string; what gets stored (and posted) is a number or null. The engine
    // refuses a string where it wants a count, and it is right to: "6" is not 6.
    var NUMERIC_TARGETS = { viral_stacks: 1, shot: 1, armour: 1, corrosive_stacks: 1,
      kill_stacks: 1, kill_uptime: 1, pool_health: 1, pool_shields: 1, pool_overguard: 1 };
    var TARGET_BOXES = { viral_stacks: 'plTargetStacks', shot: 'plTargetShot',
      armour: 'plTargetArmor', corrosive_stacks: 'plTargetCorrosive',
      kill_stacks: 'plKillStacks', kill_uptime: 'plKillUptime',
      heat_strip: 'plTargetHeat', pool_health: 'plPoolHealth', pool_shields: 'plPoolShields',
      pool_overguard: 'plPoolOverguard' };
    // A numeric box is stored through the loader's own ranges. An out-of-range entry is refused
    // here - the box goes back to the stored value and says why - because the alternative is a
    // document this page cannot read back (which would replace the whole build on the next load).
    function targetEdit(patch) {
      var t = targetState();
      var rejected = null;
      Object.keys(patch).forEach(function (k) {
        if (!NUMERIC_TARGETS[k]) { t[k] = patch[k]; return; }
        var bounds = TARGET_RANGES[k];
        var raw = patch[k];
        var stored = (raw === '' || raw === null || raw === undefined) ? null
          : numericField(raw, bounds[0], bounds[1]);
        if (stored === false) { rejected = k; return; }
        t[k] = stored;
      });
      if (rejected) {
        var box = $(TARGET_BOXES[rejected]);
        var keep = t[rejected];
        if (box) box.value = (keep === null || keep === undefined) ? '' : String(keep);
        flashHint('out of range (' + TARGET_RANGES[rejected][0] + '-' +
          TARGET_RANGES[rejected][1] + ')');
      }
      saveStorage();
      recompute();
    }
    $('plTargetFaction').addEventListener('change', function (e) {
      targetEdit({ faction: e.target.value });
    });
    $('plTargetProtection').addEventListener('change', function (e) {
      targetEdit({ protection: e.target.value });
    });
    $('plTargetStacks').addEventListener('change', function (e) {
      targetEdit({ viral_stacks: e.target.value === '' ? null : e.target.value });
    });
    $('plTargetShot').addEventListener('change', function (e) {
      targetEdit({ shot: e.target.value === '' ? null : e.target.value });
    });
    $('plTargetArmor').addEventListener('change', function (e) {
      targetEdit({ armour: e.target.value === '' ? null : e.target.value });
    });
    $('plTargetCorrosive').addEventListener('change', function (e) {
      targetEdit({ corrosive_stacks: e.target.value === '' ? null : e.target.value });
    });
    $('plKillStacks').addEventListener('change', function (e) {
      targetEdit({ kill_stacks: e.target.value === '' ? null : e.target.value });
    });
    $('plKillUptime').addEventListener('change', function (e) {
      targetEdit({ kill_uptime: e.target.value === '' ? null : e.target.value });
    });
    // Phase 6: the Heat strip is a select over the values the engine accepts (the wiki's ramp),
    // so a value the engine would refuse cannot be produced here at all.
    $('plTargetHeat').addEventListener('change', function (e) {
      var raw = e.target.value;
      var value = raw === '' ? null : Number(raw);
      if (value !== null && HEAT_STRIPS.indexOf(value) < 0) {
        e.target.value = '';
        flashHint('heat strip: 0, 15, 30, 40 or 50');
        return;
      }
      targetEdit({ heat_strip: value });
    });
    [['plPoolHealth', 'pool_health'], ['plPoolShields', 'pool_shields'],
      ['plPoolOverguard', 'pool_overguard']].forEach(function (pair) {
      $(pair[0]).addEventListener('change', function (e) {
        var patch = {};
        // '' means NOT STATED (the engine's `unknown`), never a zero
        patch[pair[1]] = e.target.value === '' ? null : e.target.value;
        targetEdit(patch);
      });
    });
    $('plStrict').addEventListener('click', function () {
      var t = targetState();
      targetEdit({ strict: !t.strict });
      renderToolbar();
    });

    $('plOrokin').addEventListener('click', function () {
      state.storage.orokin = !state.storage.orokin;
      renderToolbar();
      saveStorage();
      recompute();
    });
    $('plExilus').addEventListener('click', function () {
      state.storage.exilus_unlocked = !state.storage.exilus_unlocked;
      renderToolbar();
      renderGrid();
      saveStorage();
      recompute();
    });
    $('plReset').addEventListener('click', function () {
      var cfg = activeConfig();
      cfg.slots = {};
      cfg.polarities = {};
      state.focused = null;
      saveStorage();
      renderGrid();
      renderInspector();
      recompute(true);
    });
    $('plCopy').addEventListener('click', function () {
      var text = JSON.stringify(build(), null, 1);
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(function () {
          flashHint('Build JSON copied to the clipboard');
        }, function () { flashHint('Copy failed - JSON in console'); });
      }
      if (window.console) console.log('build JSON', text);
    });
    $('plDup').addEventListener('click', function () {
      var from = state.storage.active_config;
      var at = CONFIGS.indexOf(from);
      var to = CONFIGS[(at + 1) % CONFIGS.length];
      var copy = cloneConfigSlots(from);
      state.storage.configs[to] = { slots: copy.slots, polarities: copy.polarities };
      state.storage.active_config = to;
      saveStorage();
      renderToolbar();
      recompute();
      flashHint('config ' + from + ' → ' + to);
      emit('state', state);
    });
    // Dropping an installed mod on the library takes it out of the config (the brief's
    // "drag slot mod -> library to remove"), and the panel says so while the drag is in flight.
    (function wireLibraryDrop() {
      var panel = $('plLibrary');
      if (!panel) return;
      panel.addEventListener('dragover', function (ev) {
        if (!dragInstalled) return;
        ev.preventDefault();
        if (ev.dataTransfer) ev.dataTransfer.dropEffect = 'move';
        panel.classList.add('pl-lib-drop');
      });
      panel.addEventListener('dragleave', function (ev) {
        if (ev.target === panel) panel.classList.remove('pl-lib-drop');
      });
      panel.addEventListener('drop', function (ev) {
        if (!dragInstalled) return;
        ev.preventDefault();
        panel.classList.remove('pl-lib-drop');
        var from = dragInstalled;
        var row = modRowById((slotMod(from.kind, from.index) || {}).id);
        clearSlot(from.kind, from.index);
        flashHint((row ? row.name : 'mod') + ' removed');
        onDragEnd();
      });
    }());
    document.addEventListener('click', function (ev) {
      // Capture phase: this decides whether a click was outside BEFORE any handler can re-render
      // the element that was clicked (a detached target used to read as outside). The isConnected
      // guard covers the other direction: a target already swapped out by an earlier handler is
      // ours, not a click outside.
      var t = ev.target;
      if (!t || !t.isConnected) return;
      if (picker.open && !$('plEquipPop').contains(t) && !$('plEquipBtn').contains(t)) closePicker();
      if (popMenu && !popMenu.contains(t)) closePolarityMenu();
    }, true);
    document.addEventListener('keydown', function (ev) {
      var tag = (ev.target && ev.target.tagName || '').toLowerCase();
      if (tag === 'input' || tag === 'textarea' || tag === 'select') {
        if (ev.key === 'Escape' && ev.target.blur) ev.target.blur();
        return;
      }
      if (ev.key === 'Escape') {
        closePicker();
        closePolarityMenu();
        hidePreview();
        state.focused = null;
        renderGrid();
        renderInspector();
        return;
      }
      if (ev.key === '/' ) {
        ev.preventDefault();
        $('plLibSearch').focus();
        return;
      }
      if (ev.key === 'Delete' || ev.key === 'Backspace') {
        if (state.focused) {
          ev.preventDefault();
          clearSlot(state.focused.kind, state.focused.index);
          renderGrid();
          renderInspector();
        }
        return;
      }
      var n = parseInt(ev.key, 10);
      if (!isNaN(n) && n >= 1 && n <= 8) {
        state.focused = { kind: 'normal', index: n - 1 };
        renderGrid();
        renderInspector();
        emit('state', state);
        return;
      }
      if (ev.key === 'a' && layoutSlot('aura', null)) focusSlot('aura');
      if (ev.key === 's' && layoutSlot('stance', null)) focusSlot('stance');
      if (ev.key === 'e' && layoutSlot('exilus', null)) focusSlot('exilus');
    });
    // dropping onto empty grid space installs into the first free slot
    var grid = $('plGrid');
    grid.addEventListener('dragover', function (ev) { if (dragMod) ev.preventDefault(); });
    grid.addEventListener('drop', function (ev) {
      if (!dragMod) return;
      ev.preventDefault();
      var mod = dragMod;
      onDragEnd();
      var target = firstLegalSlot(mod);
      if (target) install(target.kind, target.index, mod);
      else flashHint('No free slot for ' + mod.name);
    });
  }

  function focusSlot(kind) {
    state.focused = { kind: kind, index: null };
    renderGrid();
    renderInspector();
    emit('state', state);
  }

  // ------------------------------------------------------------------ boot
  // A v1 document from outside the page (the current-loadout card's clone) enters through the
  // same validator the page uses for its own storage - rejected whole or accepted whole, stored,
  // and then rendered by the ordinary path. Nothing here trusts the caller's document.
  function adopt(doc) {
    var clean = cleanV1(doc);
    if (!clean) return false;
    state.storage = clean;
    saveStorage();
    renderToolbar();
    renderStatus();
    if (clean.equipment_id) selectEquipment(clean.equipment_id, true);
    else { renderGrid(); recompute(); }
    emit('state', state);
    return true;
  }

  function boot() {
    state.storage = loadStorage();
    renderEmptyState();                  // no item stored = the first-run layout, before any fetch
    if (state.rescued) saveStorage();     // the unreadable payload is replaced, not left sitting
    var params = new URLSearchParams(window.location.search);
    var wanted = params.get('equip');
    var config = params.get('config');
    if (config && CONFIGS.indexOf(config.toUpperCase()) >= 0) {
      state.storage.active_config = config.toUpperCase();
    }
    api.meta().then(function (meta) {
      state.meta = meta;
      if (!meta || meta.ok === false) {
        flashHint(meta && meta.error || 'The planner API did not answer');
        return;
      }
      if (meta.storage_version && Number(meta.storage_version) !== STORE_VERSION) {
        if (window.console) console.warn('planner storage version mismatch',
          meta.storage_version, STORE_VERSION);
      }
      state.storage.mastery_rank = state.storage.mastery_rank === null
        ? 28 : state.storage.mastery_rank;
      wire();
      renderToolbar();
      renderStatus();
      renderGrid();
      var start = wanted || state.storage.equipment_id;
      if (start) {
        selectEquipment(start, true);
      } else {
        $('plEquipName').textContent = 'Choose equipment';
        $('plEquipMeta').textContent = (meta.equipment_total || 0) + ' items · ' +
          (meta.mods_total || 0) + ' mods';
        renderEmptyState();
        openPicker();
      }
      state.ready = true;
      emit('ready', state);
    });
  }

  // ------------------------------------------------------------------ the shared surface
  window.WFMPlanner = {
    state: state,
    api: api,
    build: build,
    buildWith: buildWith,
    result: function () { return state.result; },
    equipment: function () { return state.equipment; },
    layout: function () { return state.layout; },
    error: function () { return state.error; },
    answer: function () { return state.answer; },
    library: function () { return state.library; },
    libraryHidden: function () { return state.libraryHidden || null; },
    libraryWithHidden: function () { return !!state.libraryWithHidden; },
    revealShadowed: function () { loadLibrary(state.libraryFor, true); },
    storage: function () { return state.storage; },
    focused: function () { return state.focused; },
    setFocused: function (kind, index) {
      state.focused = { kind: kind, index: index };
      renderGrid();
      renderInspector();
      emit('state', state);
    },
    clearFocused: function () { state.focused = null; renderGrid(); renderInspector(); },
    install: install,
    slotLegal: slotLegal,
    installAuto: installAuto,
    clearSlot: clearSlot,
    setPolarity: setPolarity,
    setModRank: setModRank,
    setEquipment: selectEquipment,
    setConfig: function (letter) {
      if (CONFIGS.indexOf(letter) < 0) return;
      state.storage.active_config = letter;
      saveStorage();
      renderConfigs();
      recompute();
      emit('state', state);
    },
    modFitsSlot: modFitsSlot,
    slotKey: slotKey,
    slotPolarity: slotPolarity,
    slotMod: slotMod,
    modRowById: modRowById,
    pick: function (modRow) { state.selectedMod = modRow ? modRow.id : null; emit('state', state); },
    selected: function () { return state.selectedMod; },
    previewNext: function (next, title) { showPreviewFor(next, title); },
    previewChange: function (mutate, title) {
      var letter = state.storage.active_config;
      var next = cloneConfigSlots(letter, mutate);
      var current = state.storage.configs[letter];
      state.storage.configs[letter] = next;
      var out = build();
      state.storage.configs[letter] = current;
      showPreviewFor(out, title);
    },
    hidePreview: hidePreview,
    dragStart: onDragStart,
    dragEnd: onDragEnd,
    moveInstalledTo: function (kind, index) { moveInstalled(kind, index); onDragEnd(); },
    polarityChanges: polarityChanges,
    formaUsed: formaUsed,
    // test + gate surface: the same mutations the UI runs, no shortcuts into state
    focusSlot: function (kind, index) {
      if (index === null || index === undefined) { focusSlot(kind); return; }
      state.focused = { kind: kind, index: index };
      renderGrid();
      renderInspector();
      emit('state', state);
    },
    setPolarityFor: setPolarity,
    installMod: install,
    clearSlot: clearSlot,
    setRank: setModRank,
    duplicateConfig: function () { var b = $('plDup'); if (b) b.click(); },
    explain: function (stat) { return api.explain(build(), stat); },
    save: saveStorage,
    adopt: adopt,
    on: on,
    emit: emit,
    recompute: recompute,
    render: renderResult,
    fmt: fmt,
    el: el,
    clear: clear,
    polDot: polDot,
    slotLabel: SLOT_LABEL,
    polarityShort: POL_SHORT,
    freshness: function () { return state.meta; }
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
