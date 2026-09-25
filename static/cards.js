/* cards.js — mod cards (TCG collection view), no frameworks, no external libs.
   Data: data/mod_cards.json (built by scripts/mod_cards.py). The dashboard server only
   serves static/, so the page tries the routes a small local server can expose and
   reports which one worked; ?src=<url> pins a source, and a file picker is the offline
   fallback. All injected strings are created as text nodes - never innerHTML with data. */
'use strict';
(function () {
  var SOURCES = ['/api/feature/cards', '/api/cards', '/mod_cards.json', '/cards.json',
                 '/data/mod_cards.json', '/api/data/mod_cards.json'];
  var BATCH = 180;                       // cards rendered per call (1551 cards in a full list)
  var MARKET = 'https://warframe.market/items/';
  var PIPS = 10;                         // rank pip strip length (= highest in-game mod rank)
  var RARITY_RANK = { Legendary: 4, Rare: 3, Uncommon: 2, Common: 1, Unknown: 0 };
  var GLYPH = {
    madurai: ['∨', 'Madurai'], vazarin: ['D', 'Vazarin'], naramon: ['─', 'Naramon'],
    zenurik: ['≈', 'Zenurik'], unairu: ['Y', 'Unairu'], penjaga: ['P', 'Penjaga'],
    umbra: ['U', 'Umbra'], universal: ['○', 'Universal'], aura: ['△', 'Aura']
  };

  var state = {
    all: [], map: Object.create(null), summary: null, notes: [], sources: null, url: '',
    q: '', rarity: '', type: '', owned: true, missing: true, dupes: false,
    sort: 'owned', shown: 0, filtered: [], lastFocus: null
  };

  // ---------- helpers ----------
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = String(text);
    return n;
  }
  function num(v) {
    if (v == null || v === '' || typeof v === 'boolean') return null;   // Number(null) === 0
    var n = Number(v);
    return isFinite(n) ? n : null;                                      // keeps "unknown" null
  }
  function fmt(v) {
    if (v == null || v === '') return '—';
    var n = Number(v);
    if (!isFinite(n)) return '—';
    return Number.isInteger(n) ? String(n) : String(+n.toFixed(1));
  }
  function escRe(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }
  function cardsOf(json) {
    if (Array.isArray(json)) return json;
    return json && Array.isArray(json.cards) ? json.cards : null;
  }
  function rarityClass(card) {
    var key = String(card.rarity || '').toLowerCase();
    if (key === 'common' || key === 'uncommon' || key === 'rare' || key === 'legendary') return 'r-' + key;
    return 'r-none';
  }
  function isFoil(card) { return !!card.is_prime || card.rarity === 'Legendary'; }
  function polarityOf(card) {
    return GLYPH[String(card.polarity || '').toLowerCase()] || ['·', 'no polarity'];
  }

  // ---------- data ----------
  function tryNext(list, i, tried) {
    if (i >= list.length) {
      var err = new Error('no data source answered');
      err.tried = tried;
      throw err;
    }
    var url = list[i];
    return fetch(url, { cache: 'no-cache' }).then(function (r) {
      if (!r.ok) throw new Error(url + ' → HTTP ' + r.status);
      return r.json();
    }).then(function (json) {
      var cards = cardsOf(json);
      if (!cards || !cards.length) throw new Error(url + ' → no cards array');
      return { json: json, cards: cards, url: url };
    }).catch(function (e) {
      tried.push((e && e.message) ? e.message : String(e));
      return tryNext(list, i + 1, tried);
    });
  }

  function normalize(raw) {
    var out = [];
    for (var i = 0; i < raw.length; i++) {
      var c = raw[i] || {};
      var slug = String(c.slug || '').trim();
      if (!slug) continue;
      out.push({
        slug: slug,
        name: String(c.name || slug),
        rarity: c.rarity ? String(c.rarity) : null,
        type: c.type ? String(c.type) : '',
        polarity: c.polarity ? String(c.polarity) : null,
        base_drain: num(c.base_drain),
        max_rank: num(c.max_rank),
        is_prime: !!c.is_prime,
        owned_copies: num(c.owned_copies) || 0,
        owned_rank: num(c.owned_rank),
        floor: num(c.floor),
        median: num(c.median),
        stats_text: c.stats_text ? String(c.stats_text) : '',
        icon: c.icon ? String(c.icon) : null
      });
    }
    return out;
  }

  function load() {
    var override = '';
    try { override = new URLSearchParams(location.search).get('src') || ''; } catch (e) { /* old browser */ }
    var list = override ? [override].concat(SOURCES) : SOURCES.slice();
    tryNext(list, 0, []).then(function (res) {
      state.all = normalize(res.cards);
      state.map = Object.create(null);
      state.all.forEach(function (c) { state.map[c.slug] = c; });
      state.summary = res.json.summary || null;
      state.notes = Array.isArray(res.json.notes) ? res.json.notes : [];
      state.sources = res.json.sources || null;
      state.url = res.url;
      state.generated = res.json.generated_iso || res.json.generated || '';
      // per-card back art manifest (static/cardbacks/index.json: slug -> file)
      fetch('cardbacks/index.json', { cache: 'no-cache' })
        .then(function (r) { return r.ok ? r.json() : {}; })
        .then(function (map) { state.cardbacks = map || {}; render(); })
        .catch(function () { /* no art on disk — default back */ });
      buildTypeOptions();
      buildRarityButtons();
      buildChips();
      buildGrades();
      document.getElementById('srcLine').appendChild(document.createTextNode(
        ' · loaded ' + state.all.length + ' cards from ' + res.url +
        (state.generated ? ' (built ' + state.generated + ')' : '')));
      render();
      probeArt();
    }).catch(function (err) {
      showLoadError(err);
    });
  }

  function showLoadError(err) {
    var meta = document.getElementById('meta');
    meta.textContent = '';
    var tried = (err && err.tried) ? err.tried : [String((err && err.message) || err)];
    var box = document.getElementById('empty');
    box.textContent = '';
    box.appendChild(el('b', null, 'The mod cards build could not be loaded.'));
    box.appendChild(el('div', null, 'Tried: ' + tried.join(' · ')));

    var fix = el('div', 'fix');
    fix.appendChild(el('div', null, 'Build the cards, then serve the file:'));
    var steps = el('div');
    steps.appendChild(el('code', null, 'python scripts/mod_cards.py'));
    steps.appendChild(el('div', null, 'then either expose '));
    steps.appendChild(el('code', null, 'data/mod_cards.json'));
    steps.appendChild(el('div', null, ' (e.g. /api/feature/cards in server.py, or serve the repo root) '));
    steps.appendChild(el('div', null, 'or pick the file below.'));
    fix.appendChild(steps);

    var input = el('input');
    input.type = 'file';
    input.accept = '.json,application/json';
    input.addEventListener('change', function () {
      var file = input.files && input.files[0];
      if (!file) return;
      var reader = new FileReader();
      reader.onload = function () {
        try {
          var json = JSON.parse(String(reader.result));
          var cards = cardsOf(json);
          if (!cards || !cards.length) throw new Error('no cards array in that file');
          state.all = normalize(cards);
          state.map = Object.create(null);
          state.all.forEach(function (c) { state.map[c.slug] = c; });
          state.summary = json.summary || null;
          state.notes = Array.isArray(json.notes) ? json.notes : [];
          state.sources = json.sources || null;
          state.url = 'file: ' + file.name;
          state.generated = json.generated_iso || json.generated || '';
          buildTypeOptions();
          buildRarityButtons();
          buildChips();
          buildGrades();
          box.classList.add('hidden');
          render();
          probeArt();
        } catch (e) {
          alert('That file is not a mod_cards.json build: ' + e.message);
        }
      };
      reader.readAsText(file);
    });
    fix.appendChild(input);
    box.appendChild(fix);
    box.classList.remove('hidden');
    var chips = document.getElementById('chips');
    chips.textContent = '';
    var c = el('span', 'chip warn', '');
    c.appendChild(el('b', null, 'data'));
    c.appendChild(document.createTextNode(' not loaded'));
    chips.appendChild(c);
  }

  // ---------- chips + filters ----------
  function chip(label, value, warn) {
    var c = el('span', 'chip' + (warn ? ' warn' : ''));
    c.appendChild(document.createTextNode(label + ' '));
    c.appendChild(el('b', null, String(value)));
    return c;
  }

  function buildChips() {
    var chips = document.getElementById('chips');
    chips.textContent = '';
    var s = state.summary || {};
    var counts = countOwned();
    chips.appendChild(chip('cards', s.cards != null ? s.cards : state.all.length));
    chips.appendChild(chip('owned', s.owned != null ? s.owned : counts.owned));
    chips.appendChild(chip('missing', s.missing != null ? s.missing : counts.missing));
    chips.appendChild(chip('dupes', s.dupes != null ? s.dupes : counts.dupes, counts.extra > 0));
    chips.appendChild(chip('quoted', quoteCount(), quoteCount() === 0));
  }

  function countOwned() {
    var owned = 0, missing = 0, dupes = 0, extra = 0;
    state.all.forEach(function (c) {
      if (c.owned_copies > 0) {
        owned++;
        if (c.owned_copies > 1) { dupes++; extra += c.owned_copies - 1; }
      } else { missing++; }
    });
    return { owned: owned, missing: missing, dupes: dupes, extra: extra };
  }
  function quoteCount() {
    var n = 0;
    state.all.forEach(function (c) { if (c.floor != null) n++; });
    return n;
  }

  // ---------- grades legend (why a card looks the way it does) ----------
  var RARITY_ORDER = ['Common', 'Uncommon', 'Rare', 'Legendary'];

  // ---------- condition (TCG-style, derived from the best copy's rank ratio) ----------
  // 1:1 = ranked all the way up = Mint; a single rank on a rank-10 mod (1:10) = Poor.
  var CONDITIONS = [
    { key: 'mint',   label: 'Mint',       min: 0.995, range: 'ranked 1:1 (full)' },
    { key: 'nm',     label: 'Near Mint',  min: 0.75,  range: '≥ 3/4 ranked' },
    { key: 'exc',    label: 'Excellent',  min: 0.55,  range: '≥ 55% ranked' },
    { key: 'good',   label: 'Good',       min: 0.35,  range: '≥ 35% ranked' },
    { key: 'played', label: 'Played',     min: 0.15,  range: '≥ 15% ranked' },
    { key: 'poor',   label: 'Poor',       min: 0,     range: '< 15% ranked' }
  ];

  function conditionOf(card) {
    if (!card.owned_copies || card.owned_rank == null) return null;   // not owned / no rank data
    var max = card.max_rank == null ? 0 : card.max_rank;
    var ratio = max > 0 ? Math.max(0, Math.min(1, card.owned_rank / max)) : 1;
    for (var i = 0; i < CONDITIONS.length; i++) {
      if (ratio >= CONDITIONS[i].min) {
        return { key: CONDITIONS[i].key, label: CONDITIONS[i].label,
                 ratio: ratio, rank: card.owned_rank, max: max };
      }
    }
    return null;
  }

  function conditionChip(cond) {
    var chip = el('span', 'mcd-cond cond-' + cond.key, cond.label);
    chip.title = 'Condition ' + cond.label + ' — best owned copy is rank ' + cond.rank +
      (cond.max > 0 ? '/' + cond.max : '') + ' (' +
      (cond.max > 0 ? Math.round(cond.ratio * 100) + '% of max rank' : 'no rank scale') +
      '). TCG-style: rank ratio = wear.';
    return chip;
  }

  // one line on the back of a card, derived from that card's own fields
  function gradeLine(card) {
    var line = el('div', 'mcd-grade');
    if (!card.rarity) { line.textContent = 'Grade: none in game data (neutral border)'; return line; }
    line.appendChild(document.createTextNode('Grade: '));
    line.appendChild(el('b', null, card.rarity));
    var foilLabel = card.is_prime ? 'Prime' : card.rarity;
    if (isFoil(card) && foilLabel !== card.rarity) line.appendChild(document.createTextNode(' · foil: ' + foilLabel));
    var cond = conditionOf(card);
    if (cond) {
      line.appendChild(document.createTextNode(' · condition: '));
      line.appendChild(el('b', 'cond-' + cond.key, cond.label));
      line.appendChild(document.createTextNode(' (' + cond.rank + (cond.max > 0 ? '/' + cond.max : '') + ')'));
    }
    return line;
  }

  function gradeCounts() {
    var by = Object.create(null), order = [], foil = 0, none = 0;
    var condCount = Object.create(null), condTotal = 0;
    state.all.forEach(function (card) {
      if (card.rarity) {
        if (!(card.rarity in by)) { by[card.rarity] = 0; order.push(card.rarity); }
        by[card.rarity]++;
      } else { none++; }
      if (isFoil(card)) foil++;
      var cond = conditionOf(card);
      if (cond) { condCount[cond.key] = (condCount[cond.key] || 0) + 1; condTotal++; }
    });
    order.sort(function (a, b) {
      var ia = RARITY_ORDER.indexOf(a), ib = RARITY_ORDER.indexOf(b);
      return (ia === -1 ? RARITY_ORDER.length : ia) - (ib === -1 ? RARITY_ORDER.length : ib) || a.localeCompare(b);
    });
    return { by: by, order: order, foil: foil, none: none, cond: condCount, condTotal: condTotal };
  }

  function gradeRow(panel, label, text) {
    var row = el('div', 'g-row');
    row.appendChild(el('b', null, label));
    row.appendChild(document.createTextNode(text));
    panel.appendChild(row);
  }

  // counts always come from the loaded cards array - never hardcoded
  function buildGrades() {
    var panel = document.getElementById('gradeLegend');
    if (!panel) return;
    panel.textContent = '';
    var g = gradeCounts();
    var head = el('div', 'g-head', 'How the cards are graded');
    head.appendChild(el('span', 'dim', ' · counted from the ' + state.all.length + ' mods loaded'));
    panel.appendChild(head);
    gradeRow(panel, 'Border', " = the mod's in-game rarity field from the WFCD game catalog — " +
      (g.order.length ? g.order.map(function (k) { return k + ' ' + g.by[k]; }).join(' · ') : 'no rarity values in this build'));
    gradeRow(panel, 'Foil metallic sweep', ' = Prime (is_prime) or Legendary rarity — ' + g.foil + (g.foil === 1 ? ' card' : ' cards'));
    gradeRow(panel, 'Neutral border', ' = no rarity in the game data — ' + g.none + (g.none === 1 ? ' card' : ' cards'));
    gradeRow(panel, 'Dimmed', ' = not owned · rank pips = your best owned copy’s rank · ×N badge = copies owned · floor/median = live WFM prices');
    gradeRow(panel, 'Condition', ' = the TCG-style wear grade, read from the best owned copy’s rank ratio — 1:1 (fully ranked) = Mint; a lone rank on a rank-10 mod = Poor. ' +
      CONDITIONS.map(function (c) { return c.label + ' ' + (g.cond[c.key] || 0); }).join(' · ') +
      ' · cards with no copy: ' + (state.all.length - g.condTotal));
  }

  function buildRarityButtons() {
    var row = document.getElementById('rarityRow');
    row.textContent = '';
    row.appendChild(el('span', 'mcd-lbl', 'Rarity'));
    var order = Object.keys((state.summary && state.summary.rarities) || {});
    state.all.forEach(function (c) {
      var key = c.rarity || 'Unknown';
      if (order.indexOf(key) === -1) order.push(key);
    });
    var opts = ['', 'Prime'].concat(order);
    opts.forEach(function (key) {
      var btn = el('button', 'mcd-btn rar' + (state.rarity === key ? ' active' : ''), '');
      btn.type = 'button';
      btn.setAttribute('data-rar', key);
      btn.appendChild(document.createTextNode(key === '' ? 'All' : (key === 'Prime' ? '★ Prime / foil' : key)));
      var bucket = state.summary && state.summary.rarities ? state.summary.rarities[key] : null;
      if (bucket) {
        btn.appendChild(el('span', 'mcd-rank', ' ' + bucket.owned + '/' + bucket.total));
      }
      btn.addEventListener('click', function () {
        state.rarity = (state.rarity === key) ? '' : key;
        buildRarityButtons();
        render();
      });
      row.appendChild(btn);
    });
  }

  function buildTypeOptions() {
    var sel = document.getElementById('typeSel');
    var counts = Object.create(null), types = [];
    state.all.forEach(function (c) {
      if (!c.type) return;
      if (c.type in counts) counts[c.type]++;
      else { counts[c.type] = 1; types.push(c.type); }     // 0 is falsy: membership, not truthiness
    });
    types.sort(function (a, b) { return counts[b] - counts[a] || a.localeCompare(b); });
    sel.textContent = '';
    var all = el('option', null, 'All types (' + state.all.length + ')');
    all.value = '';
    sel.appendChild(all);
    types.forEach(function (t) {
      var o = el('option', null, t + ' (' + counts[t] + ')');
      o.value = t;
      sel.appendChild(o);
    });
    sel.value = state.type;
  }

  // ---------- filtering ----------
  function score(c, q) {
    var n = c.name.toLowerCase(), s = c.slug.toLowerCase();
    if (n === q || s === q) return 0;
    if (n.indexOf(q) === 0) return 1;
    if (new RegExp('(^|[^a-z0-9])' + escRe(q)).test(n)) return 2;
    if (n.indexOf(q) !== -1) return 3;
    if (s.indexOf(q) !== -1) return 4;
    return -1;
  }

  function matches(card) {
    if (!state.owned && !state.missing) return false;
    var owned = card.owned_copies > 0;
    if (owned && !state.owned) return false;
    if (!owned && !state.missing) return false;
    if (state.dupes && card.owned_copies < 2) return false;
    if (state.rarity === 'Prime') { if (!isFoil(card)) return false; }
    else if (state.rarity) { if ((card.rarity || 'Unknown') !== state.rarity) return false; }
    if (state.type && card.type !== state.type) return false;
    if (state.q && score(card, state.q) < 0) return false;
    return true;
  }

  function sorted(list) {
    var out = list.slice();
    function byName(a, b) { return a.name.localeCompare(b.name) || a.slug.localeCompare(b.slug); }
    function byRarity(a, b) {
      return (RARITY_RANK[b.rarity] || 0) - (RARITY_RANK[a.rarity] || 0) || byName(a, b);
    }
    if (state.sort === 'name') out.sort(byName);
    else if (state.sort === 'rarity') out.sort(byRarity);
    else if (state.sort === 'copies') {
      out.sort(function (a, b) { return b.owned_copies - a.owned_copies || byRarity(a, b); });
    } else if (state.sort === 'value') {
      out.sort(function (a, b) {
        return ((b.floor == null ? -1 : b.floor) - (a.floor == null ? -1 : a.floor)) || byRarity(a, b);
      });
    } else {
      out.sort(function (a, b) {
        return ((a.owned_copies > 0 ? 0 : 1) - (b.owned_copies > 0 ? 0 : 1)) || byRarity(a, b);
      });
    }
    if (state.q) {
      var q = state.q;
      out.sort(function (a, b) { return score(a, q) - score(b, q); });
    }
    return out;
  }

  // ---------- icons ----------
  /* Card art lives on the warframe.market CDN, which refuses cross-origin embeds (HTTP 403 with
     Cross-Origin-Resource-Policy: same-origin -> ERR_BLOCKED_BY_RESPONSE) from some networks.
     Probe once per page load: cards paint instantly with their CSS art (polarity glyph + rarity
     border) and pick up an icon only if the host answers - a refusing host then costs one request
     instead of one per card. */
  var artState = 'probing';   // 'probing' | 'ok' | 'off'

  function addArt(art, card) {
    if (!art || !card || !card.icon || art.querySelector('.mcd-art-img')) return;
    var img = el('img', 'mcd-art-img');
    img.alt = '';
    img.loading = 'lazy';
    img.decoding = 'async';
    img.referrerPolicy = 'no-referrer';
    img.addEventListener('error', function () { img.remove(); art.classList.remove('has-art'); });
    img.src = card.icon;
    art.classList.add('has-art');
    art.appendChild(img);
  }

  function upgradeArt() {
    var nodes = document.querySelectorAll('#grid .mcd-card[data-slug]');
    for (var i = 0; i < nodes.length; i++) {
      var card = state.map[nodes[i].getAttribute('data-slug')];
      if (card) addArt(nodes[i].querySelector('.mcd-art'), card);
    }
  }

  function probeArt() {
    if (artState !== 'probing') return;
    var first = null;
    for (var i = 0; i < state.all.length && !first; i++) { if (state.all[i].icon) first = state.all[i]; }
    if (!first) { artState = 'off'; return; }
    var probe = new Image();
    var done = false;
    function finish(ok) {
      if (done) return;
      done = true;
      artState = ok ? 'ok' : 'off';
      if (ok) upgradeArt();
    }
    probe.onload = function () { finish(!!probe.naturalWidth); };
    probe.onerror = function () { finish(false); };
    setTimeout(function () { finish(true); }, 4000);   // slow host: let the lazy <img>s try
    probe.src = first.icon;
  }

  // ---------- card ----------
  function pips(card) {
    var row = el('div', 'mcd-pips');
    row.setAttribute('aria-hidden', 'true');
    var cap = card.max_rank == null ? PIPS : Math.max(0, Math.min(PIPS, card.max_rank));
    var rank = card.owned_rank == null ? -1 : card.owned_rank;
    for (var i = 0; i < PIPS; i++) {
      var dot = el('i');
      if (i < rank) dot.className = 'on';
      else if (i < cap) dot.className = 'avail';
      row.appendChild(dot);
    }
    var label = card.owned_rank == null
      ? 'rank unknown'
      : 'rank ' + card.owned_rank + (card.max_rank != null ? '/' + card.max_rank : '');
    row.appendChild(el('span', 'mcd-rank', label));
    var cond = conditionOf(card);
    if (cond) row.appendChild(conditionChip(cond));
    return row;
  }

  function priceLine(card) {
    var row = el('div', 'mcd-price');
    if (card.floor == null && card.median == null) {
      row.appendChild(el('span', 'no', 'no local quote'));
      return row;
    }
    if (card.floor != null) {
      var f = el('span', 'f', 'floor ' + fmt(card.floor) + 'p');
      f.title = 'lowest visible sell listing in this PC\'s snapshot';
      row.appendChild(f);
    } else {
      row.appendChild(el('span', 'no', 'no listings'));
    }
    if (card.median != null) row.appendChild(el('span', null, '· med ' + fmt(card.median) + 'p'));
    return row;
  }

  // ---------- holographic foil system (rendered ABOVE the art; never baked in) ----------
  // effect types: none | holo | prismatic | etched | legendary — intensity scales the layers
  var FOILS = { none: 0, holo: .38, prismatic: .52, etched: .64, legendary: .80 };
  function foilFor(card) {
    if (isFoil(card)) return card.rarity === 'Legendary' ? 'legendary' : 'etched';
    if (card.rarity === 'Rare') return 'prismatic';
    if (card.rarity === 'Uncommon') return 'holo';
    return 'none';
  }
  function addFoilLayers(face) {
    // blend modes (dodge/screen/overlay) make BRIGHT artwork react hardest and dark
    // armour stay clean — that is the "selective holo response" without per-pixel masks
    face.appendChild(el('span', 'mcd-foil'));
    face.appendChild(el('span', 'mcd-spec'));
    face.appendChild(el('span', 'mcd-grain'));
  }

  function buildCard(card, opts) {
    var owned = card.owned_copies > 0;
    var pol = polarityOf(card);
    var node = el('button', 'mcd-card ' + rarityClass(card) +
      (isFoil(card) ? ' is-prime' : '') + (owned ? '' : ' missing'));
    node.type = 'button';
    node.setAttribute('role', 'listitem');
    node.setAttribute('data-slug', card.slug);
    // foil: rarity picks the effect, intensity rides --foil-i into the CSS layers
    var foil = foilFor(card);
    node.setAttribute('data-foil', foil);
    node.style.setProperty('--foil-i', String(FOILS[foil] || 0));
    node.style.setProperty('--mx', '50');
    node.style.setProperty('--my', '50');
    node.setAttribute('aria-label',
      card.name + ', ' + (card.rarity || 'unknown rarity') + (isFoil(card) ? ' foil' : '') +
      ', ' + (owned ? (card.owned_copies + (card.owned_copies === 1 ? ' copy' : ' copies') +
        (card.owned_rank != null ? ', rank ' + card.owned_rank : '')) : 'not owned') +
      (card.floor != null ? ', sell floor ' + fmt(card.floor) + ' platinum' : '') +
      ', click to inspect the card');

    var inner = el('div', 'mcd-inner');

    // front
    var front = el('div', 'mcd-face mcd-front');
    var art = el('div', 'mcd-art');
    if (artState === 'ok') addArt(art, card);
    art.appendChild(el('span', 'mcd-type', card.type || 'mod'));
    if (!owned) art.appendChild(el('span', 'mcd-missing-flag', 'missing'));
    art.appendChild(el('span', 'mcd-pol', pol[0]));
    art.appendChild(el('span', 'mcd-pol-name', pol[1]));
    front.appendChild(art);
    if (card.owned_copies > 1) {
      var dup = el('span', 'mcd-dup', '×' + card.owned_copies);
      dup.title = card.owned_copies + ' copies owned';
      front.appendChild(dup);
    }
    var body = el('div', 'mcd-body');
    body.appendChild(el('div', 'mcd-name', card.name));
    if (owned) body.appendChild(pips(card));
    else body.appendChild(el('div', 'mcd-missing-flag', 'not owned'));
    body.appendChild(priceLine(card));
    front.appendChild(body);

    // back — per-card art when cardbacks/index.json has one for this slug
    var back = el('div', 'mcd-face mcd-back');
    var cb = (state.cardbacks || {})[card.slug];
    if (cb) {
      back.classList.add('has-art');
      back.style.setProperty('--cb', "url('/cardbacks/" + cb + "')");
    }
    back.appendChild(el('div', 'mcd-back-name', card.name));
    back.appendChild(el('div', 'mcd-stats', card.stats_text || 'No stat line in the catalog for this mod.'));
    back.appendChild(gradeLine(card));
    var meta = el('div', 'mcd-back-meta');
    var bits = [
      (card.rarity || 'no rarity') + (isFoil(card) ? ' ★' : ''),
      card.type || 'mod',
      pol[1],
      card.owned_copies + (card.owned_copies === 1 ? ' copy' : ' copies'),
      card.owned_rank != null ? 'rank ' + card.owned_rank : 'rank unknown',
      card.base_drain != null ? 'drain ' + card.base_drain : 'drain —',
      card.max_rank != null ? 'max rank ' + card.max_rank : 'max rank —'
    ];
    bits.forEach(function (bit) {
      meta.appendChild(el('div', null, bit));
    });
    if (card.floor != null || card.median != null) {
      meta.appendChild(el('div', null, 'floor ' + fmt(card.floor) + 'p · med ' + fmt(card.median) + 'p'));
    }
    back.appendChild(meta);
    back.appendChild(el('div', 'mcd-back-slug', card.slug));

    addFoilLayers(front);
    addFoilLayers(back);
    inner.appendChild(front);
    inner.appendChild(back);
    node.appendChild(inner);

    // click opens the inspect view (hover still flips in the grid on desktop);
    // inside the overlay (opts.quiet) a click flips the big card instead.
    node.addEventListener('click', function () {
      if (opts && opts.quiet) { node.classList.toggle('flipped'); return; }
      state.lastFocus = node;
      openInspect(card);
    });
    return node;
  }

  // ---------- inspect view: big card (drag to tilt in 3D), flip, info card ----------
  var ins = null;

  function insButton(cls, label, fn) {
    var b = el('button', 'mcd-btn ' + cls, label);
    b.type = 'button';
    b.addEventListener('click', fn);
    return b;
  }

  function insRow(label, value) {
    var r = el('div', 'ins-row');
    r.appendChild(el('span', 'ins-lbl', label));
    r.appendChild(el('span', 'ins-val', value));
    ins.info.appendChild(r);
  }

  function applyTilt() {
    if (!ins) return;
    ins.tilt.style.transform = 'rotateX(' + ins.rx.toFixed(2) + 'deg) rotateY(' + ins.ry.toFixed(2) + 'deg)';
    // specular + holo react to the tilt: the reflection direction follows the angle
    var px = Math.max(4, Math.min(96, 50 + ins.ry * 1.6));
    var py = Math.max(4, Math.min(96, 50 - ins.rx * 1.7));
    ins.sheen.style.setProperty('--sx', px.toFixed(1) + '%');
    ins.sheen.style.setProperty('--sy', py.toFixed(1) + '%');
    if (ins.bigCard) {
      ins.bigCard.style.setProperty('--mx', px.toFixed(1));
      ins.bigCard.style.setProperty('--my', py.toFixed(1));
    }
  }

  // smooth interpolation (no snapping) + a gentle idle drift while the viewer is open
  function tiltLoop(t) {
    if (!ins || ins.wrap.classList.contains('hidden')) { if (ins) { ins.raf = 0; ins.last = 0; } return; }
    var dt = ins.last ? Math.min(64, Math.max(4, t - ins.last)) : 16;
    ins.last = t;
    if (ins.drag || ins.tx !== 0 || ins.ty !== 0) {
      ins.tx2 = ins.tx;
      ins.ty2 = ins.ty;
    } else {
      // idle motion: ~1.4deg drift, auto-paused the moment the user interacts
      ins.tx2 = Math.sin(t / 2600) * 1.4;
      ins.ty2 = Math.cos(t / 3700) * 1.1;
    }
    var k = 1 - Math.pow(0.0018, dt / 1000);   // frame-rate independent easing
    ins.rx += (ins.ty2 - ins.rx) * k;
    ins.ry += (ins.tx2 - ins.ry) * k;
    applyTilt();
    ins.raf = requestAnimationFrame(tiltLoop);
  }
  function startTiltLoop() {
    if (ins && !ins.raf) { ins.last = 0; ins.raf = requestAnimationFrame(tiltLoop); }
  }

  function ensureInspect() {
    if (ins) return ins;
    var wrap = el('div', 'ins-wrap hidden');
    var bd = el('div', 'ins-backdrop');
    var body = el('div', 'ins-body');
    var stage = el('div', 'ins-stage');
    var tilt = el('div', 'ins-tilt');
    var holder = el('div', 'ins-card');
    var glow = el('div', 'ins-glow');
    var sheen = el('div', 'ins-sheen');
    holder.appendChild(glow);
    holder.appendChild(sheen);
    tilt.appendChild(holder);
    stage.appendChild(tilt);
    var info = el('div', 'ins-info');
    body.appendChild(stage);
    body.appendChild(info);
    var bar = el('div', 'ins-bar');
    wrap.appendChild(bd);
    wrap.appendChild(body);
    wrap.appendChild(bar);
    document.body.appendChild(wrap);

    ins = {
      wrap: wrap, bd: bd, holder: holder, tilt: tilt, sheen: sheen, glow: glow, info: info, bar: bar,
      bigCard: null, rx: 0, ry: 0, tx: 0, ty: 0, tx2: 0, ty2: 0, zoom: 1.85, drag: null, moved: false, raf: 0, last: 0,
    };
    bd.addEventListener('click', closeInspect);
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && !ins.wrap.classList.contains('hidden')) closeInspect();
    });

    // drag to rotate — targets are eased by tiltLoop (smooth, never snapping)
    tilt.addEventListener('pointerdown', function (e) {
      ins.drag = { x: e.clientX, y: e.clientY, tx: ins.tx, ty: ins.ty };
      ins.moved = false;
      tilt.classList.add('dragging');
      if (tilt.setPointerCapture) tilt.setPointerCapture(e.pointerId);
      e.preventDefault();
    });
    tilt.addEventListener('pointermove', function (e) {
      if (ins.drag) {
        var dx = e.clientX - ins.drag.x;
        var dy = e.clientY - ins.drag.y;
        if (Math.abs(dx) + Math.abs(dy) > 6) ins.moved = true;
        // bounded so it still reads like a physical card under inspection
        ins.ty = Math.max(-20, Math.min(20, ins.drag.ty - dy * 0.22));
        ins.tx = Math.max(-30, Math.min(30, ins.drag.tx + dx * 0.26));
        return;
      }
      if (e.pointerType && e.pointerType !== 'mouse') return;
      // hover (no drag): the card leans gently toward the cursor, max ~6.5deg
      var r = tilt.getBoundingClientRect();
      ins.tx = Math.max(-6.5, Math.min(6.5, ((e.clientX - (r.left + r.width / 2)) / r.width) * 26));
      ins.ty = Math.max(-6.5, Math.min(6.5, -((e.clientY - (r.top + r.height / 2)) / r.height) * 26));
    });
    tilt.addEventListener('pointerleave', function () { if (!ins.drag) { ins.tx = 0; ins.ty = 0; } });
    function endDrag() { ins.drag = null; tilt.classList.remove('dragging'); }
    tilt.addEventListener('pointerup', endDrag);
    tilt.addEventListener('pointercancel', endDrag);
    // a drag must not read as a click (clicks flip the card)
    tilt.addEventListener('click', function (e) {
      if (ins.moved) { e.stopPropagation(); e.preventDefault(); ins.moved = false; }
    }, true);
    // wheel = controlled zoom of the showcase card
    tilt.addEventListener('wheel', function (e) {
      e.preventDefault();
      ins.zoom = Math.max(1.25, Math.min(2.6, ins.zoom + (e.deltaY < 0 ? 0.12 : -0.12)));
      ins.holder.style.setProperty('--ins-scale', ins.zoom.toFixed(2));
    }, { passive: false });
    return ins;
  }

  function closeInspect() {
    if (!ins) return;
    ins.wrap.classList.add('hidden');
    document.body.style.overflow = '';
    if (state.lastFocus && state.lastFocus.focus) { try { state.lastFocus.focus(); } catch (e) { /* node gone */ } }
  }

  function openInspect(card) {
    var I = ensureInspect();
    I.rx = 0; I.ry = 0; I.tx = 0; I.ty = 0; I.tx2 = 0; I.ty2 = 0;
    I.zoom = 1.85;
    applyTilt();

    // big card (same builder; inside the overlay a click flips it)
    I.holder.textContent = '';
    var big = buildCard(card, { quiet: true });
    I.bigCard = big;
    I.holder.style.setProperty('--ins-scale', '1.85');
    I.holder.appendChild(big);
    I.holder.appendChild(I.glow);
    I.holder.appendChild(I.sheen);
    startTiltLoop();

    // attached info card
    I.info.textContent = '';
    var head = el('div', 'ins-head');
    head.appendChild(el('div', 'ins-name', card.name));
    var chips = el('div', 'ins-chips');
    chips.appendChild(el('span', 'ins-chip', (card.rarity || 'no rarity') + (isFoil(card) ? ' · foil ★' : '')));
    var cond = conditionOf(card);
    if (cond) chips.appendChild(conditionChip(cond));
    chips.appendChild(el('span', 'ins-chip', card.owned_copies > 0
      ? card.owned_copies + (card.owned_copies === 1 ? ' copy owned' : ' copies owned') : 'not owned'));
    head.appendChild(chips);
    I.info.appendChild(head);
    if (card.stats_text) I.info.appendChild(el('div', 'ins-stats', card.stats_text));

    var pol = polarityOf(card);
    insRow('Type', card.type || '—');
    insRow('Polarity', pol[1] + ' (' + pol[0] + ')');
    insRow('Base drain', card.base_drain != null ? String(card.base_drain) : '—');
    insRow('Max rank', card.max_rank != null ? String(card.max_rank) : '—');
    insRow('Best copy', card.owned_rank != null
      ? 'rank ' + card.owned_rank + (card.max_rank != null ? ' / ' + card.max_rank : '') : 'not owned');
    if (card.owned_copies > 1) insRow('Spare copies', String(card.owned_copies - 1));
    insRow('Sell floor', card.floor != null ? fmt(card.floor) + 'p' : 'no listings');
    insRow('Median (48h)', card.median != null ? fmt(card.median) + 'p' : '—');
    insRow('Slug', card.slug);

    // bar
    I.bar.textContent = '';
    I.bar.appendChild(insButton('ins-flip', '↻ Flip card', function () { big.classList.toggle('flipped'); }));
    I.bar.appendChild(insButton('ins-reset', '⟲ Reset view', function () {
      I.tx = 0; I.ty = 0; I.zoom = 1.85;   // loop eases back to neutral
      I.holder.style.setProperty('--ins-scale', '1.85');
    }));
    var mkt = el('a', 'mcd-btn ins-market', 'warframe.market ↗');
    mkt.href = MARKET + encodeURIComponent(card.slug);
    mkt.target = '_blank';
    mkt.rel = 'noopener';
    I.bar.appendChild(mkt);

    I.wrap.classList.remove('hidden');
    document.body.style.overflow = 'hidden';
    I.tilt.tabIndex = -1;
  }

  // ---------- render ----------
  function render() {
    var grid = document.getElementById('grid');
    var meta = document.getElementById('meta');
    var empty = document.getElementById('empty');
    var more = document.getElementById('moreWrap');
    var clearBtn = document.getElementById('clearBtn');
    if (!state.all.length) { meta.textContent = 'Loading mod cards…'; return; }

    state.filtered = sorted(state.all.filter(matches));
    state.shown = Math.min(BATCH, state.filtered.length);
    paint();
    updateMeta();

    clearBtn.classList.toggle('hidden', !state.q);
    if (!state.filtered.length) {
      empty.textContent = '';
      empty.appendChild(el('b', null, 'No card matches those filters.'));
      empty.appendChild(el('div', null, 'Widen the rarity/type/state filters, or try a shorter search term — ' +
        'search covers mod names and slugs (e.g. “primed”, “umbra”, “riven”).'));
      empty.classList.remove('hidden');
      more.classList.add('hidden');
    } else {
      empty.classList.add('hidden');
      more.classList.toggle('hidden', state.shown >= state.filtered.length);
    }
    var btn = document.getElementById('moreBtn');
    var left = state.filtered.length - state.shown;
    btn.textContent = left > 0 ? ('Show ' + Math.min(BATCH, left) + ' more (' + left + ' left)' +
      ' — ' + state.filtered.length + ' match' + (state.filtered.length === 1 ? '' : 'es')) : 'Show more';
    grid.setAttribute('aria-label', 'Mod cards (' + state.filtered.length + ' shown)');
  }

  function paint() {
    var grid = document.getElementById('grid');
    var frag = document.createDocumentFragment();
    for (var i = 0; i < state.shown; i++) frag.appendChild(buildCard(state.filtered[i]));
    grid.textContent = '';
    grid.appendChild(frag);
  }

  function updateMeta() {
    var meta = document.getElementById('meta');
    var counts = countOwned();
    var s = state.summary || {};
    var filters = [];
    if (state.rarity) filters.push(state.rarity === 'Prime' ? 'prime/foil' : state.rarity.toLowerCase());
    if (state.type) filters.push(state.type.toLowerCase());
    if (!state.owned) filters.push('hides owned');
    if (!state.missing) filters.push('hides missing');
    if (state.dupes) filters.push('dupes only');
    if (state.q) filters.push('“' + state.q + '”');

    meta.textContent = '';
    meta.appendChild(el('span', null, 'Showing '));
    meta.appendChild(el('b', null, state.shown + ' / ' + state.filtered.length));
    meta.appendChild(el('span', null, ' of ' + state.all.length + ' mods'));
    if (filters.length) meta.appendChild(el('span', null, ' · filters: ' + filters.join(', ')));
    meta.appendChild(el('span', null, ' · owned '));
    meta.appendChild(el('b', null, String(counts.owned)));
    meta.appendChild(el('span', null, ' · missing '));
    meta.appendChild(el('b', null, String(counts.missing)));
    meta.appendChild(el('span', null, ' · dupes '));
    meta.appendChild(el('b', null, String(counts.dupes)));
    meta.appendChild(el('span', null, ' (' + counts.extra + ' spare copies) · quoted '));
    meta.appendChild(el('b', null, String(quoteCount())));
    if (s.rarities) {
      var parts = [];
      Object.keys(s.rarities).forEach(function (k) {
        parts.push(k + ' ' + s.rarities[k].owned + '/' + s.rarities[k].total);
      });
      meta.appendChild(el('div', null, 'rarity coverage (owned/total): ' + parts.join(' · ')));
    }
    if (state.notes && state.notes.length) {
      meta.appendChild(el('div', null, state.notes.join(' · ')));
    }
  }

  // ---------- wiring ----------
  document.addEventListener('DOMContentLoaded', function () {
    var q = document.getElementById('q');
    q.addEventListener('input', function () { state.q = q.value.trim().toLowerCase(); render(); });
    document.getElementById('clearBtn').addEventListener('click', function () {
      q.value = ''; state.q = ''; render(); q.focus();
    });
    document.getElementById('typeSel').addEventListener('change', function (e) {
      state.type = e.target.value; render();
    });
    document.getElementById('sortSel').addEventListener('change', function (e) {
      state.sort = e.target.value; render();
    });
    // grid foil + tilt: ONE delegated, rAF-throttled pointer listener for all cards
    var gTilt = { card: null, x: 50, y: 50, raf: 0 };
    var gEl = document.getElementById('grid');
    function gFlush() {
      gTilt.raf = 0;
      if (!gTilt.card) return;
      gTilt.card.style.setProperty('--mx', gTilt.x.toFixed(1));
      gTilt.card.style.setProperty('--my', gTilt.y.toFixed(1));
      gTilt.card.style.setProperty('--ry', ((gTilt.x - 50) * 0.11).toFixed(2) + 'deg');
      gTilt.card.style.setProperty('--rx', (-(gTilt.y - 50) * 0.09).toFixed(2) + 'deg');
    }
    function gReset() {
      if (gTilt.card) {
        gTilt.card.style.removeProperty('--rx');
        gTilt.card.style.removeProperty('--ry');
        gTilt.card.style.setProperty('--mx', '50');
        gTilt.card.style.setProperty('--my', '50');
      }
      gTilt.card = null;
    }
    gEl.addEventListener('pointermove', function (e) {
      if (e.pointerType && e.pointerType !== 'mouse') return;   // touch degrades to no tilt
      var card = e.target && e.target.closest ? e.target.closest('.mcd-card') : null;
      if (card !== gTilt.card) { gReset(); gTilt.card = card; }
      if (!card) return;
      var r = card.getBoundingClientRect();
      gTilt.x = Math.max(0, Math.min(100, ((e.clientX - r.left) / r.width) * 100));
      gTilt.y = Math.max(0, Math.min(100, ((e.clientY - r.top) / r.height) * 100));
      if (!gTilt.raf) gTilt.raf = requestAnimationFrame(gFlush);
    });
    gEl.addEventListener('pointerleave', gReset);
    var stateRow = document.getElementById('stateRow');
    stateRow.querySelectorAll('[data-state]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var key = btn.getAttribute('data-state');
        state[key] = !state[key];
        btn.classList.toggle('active', state[key]);
        btn.setAttribute('aria-pressed', state[key] ? 'true' : 'false');
        render();
      });
    });
    document.getElementById('resetBtn').addEventListener('click', function () {
      state.q = ''; state.rarity = ''; state.type = ''; state.owned = true;
      state.missing = true; state.dupes = false; state.sort = 'owned';
      q.value = '';
      document.getElementById('typeSel').value = '';
      document.getElementById('sortSel').value = 'owned';
      stateRow.querySelectorAll('[data-state]').forEach(function (btn) {
        var on = btn.getAttribute('data-state') === 'dupes' ? false : true;
        btn.classList.toggle('active', on);
        btn.setAttribute('aria-pressed', on ? 'true' : 'false');
      });
      buildRarityButtons();
      render();
    });
    document.getElementById('gradeBtn').addEventListener('click', function () {
      var btn = document.getElementById('gradeBtn');
      var panel = document.getElementById('gradeLegend');
      panel.classList.toggle('hidden');
      var open = !panel.classList.contains('hidden');
      btn.setAttribute('aria-expanded', open ? 'true' : 'false');
      btn.classList.toggle('active', open);
    });
    document.getElementById('moreBtn').addEventListener('click', function () {
      state.shown = Math.min(state.filtered.length, state.shown + BATCH);
      paint();
      updateMeta();
      document.getElementById('moreWrap').classList.toggle('hidden', state.shown >= state.filtered.length);
      var btn = document.getElementById('moreBtn');
      var left = state.filtered.length - state.shown;
      btn.textContent = 'Show ' + Math.min(BATCH, left) + ' more (' + left + ' left)';
    });

    document.addEventListener('keydown', function (e) {
      if (e.key === '/' && document.activeElement !== q) { e.preventDefault(); q.focus(); return; }
      if (e.key === 'Escape' && document.activeElement === q && q.value) {
        q.value = ''; state.q = ''; render();
      }
    });

    load();
  });
})();
