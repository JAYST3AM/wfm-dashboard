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
  var paintGen = 0;                      // bumped per paint: a stale measure pass must not run
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
    cardart: null, hi: null,                                       // art manifests (slug -> file)
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
        lane_rank: num(c.lane_rank),
        lane_ask: num(c.lane_ask),
        lane_bid: num(c.lane_bid),
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
      // full-art manifest (static/cardart/index.json: slug -> file) — art renders on the FRONT
      fetch('cardart/index.json', { cache: 'no-cache' })
        .then(function (r) { return r.ok ? r.json() : {}; })
        .then(function (map) { state.cardart = map || {}; render(); })
        .catch(function () { /* no full-art on disk — standard fronts */ });
      // local hi-res set (static/hi/index.json: wiki art upscaled 4x on this PC) — the only art
      // the grid loads; a slug that is not in it gets the letter tile (never a remote request)
      fetch('hi/index.json', { cache: 'no-cache' })
        .then(function (r) { return r.ok ? r.json() : {}; })
        .then(function (j) { state.hi = (j && j.items) || {}; render(); })
        .catch(function () { /* no hi set — every card paints its letter tile */ });
      buildTypeOptions();
      buildRarityButtons();
      buildChips();
      var srcEl = document.getElementById('srcLine');
      srcEl.appendChild(document.createTextNode(' · ' + state.all.length + ' cards'));
      if (state.generated) {
        srcEl.appendChild(document.createTextNode(' · built ' + String(state.generated).slice(0, 10)));
      }
      srcEl.title = 'Loaded from ' + res.url + (state.generated ? ' · built ' + state.generated : '');
      render();
    }).catch(function (err) {
      showLoadError(err);
    });
  }

  function showLoadError(err) {
    var meta = document.getElementById('meta');
    meta.textContent = 'No cards build loaded.';
    var tried = (err && err.tried) ? err.tried : [String((err && err.message) || err)];
    var box = document.getElementById('empty');
    box.textContent = '';

    var fix = el('div', 'fix');
    fix.appendChild(el('div', null, 'Run scripts/mod_cards.py, then reload.'));
    fix.appendChild(el('div', null, 'Or pick a mod_cards.json below.'));

    var input = el('input');
    input.type = 'file';
    input.accept = '.json,application/json';
    input.setAttribute('aria-label', 'Pick a mod_cards.json build');
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
          box.classList.add('hidden');
          render();
        } catch (e) {
          alert('Not a mod_cards.json build: ' + e.message);
        }
      };
      reader.readAsText(file);
    });
    fix.appendChild(input);
    box.appendChild(fix);
    // the failed sources stay one hover away instead of filling the page
    box.title = 'Tried: ' + tried.join(' · ');
    box.classList.remove('hidden');
    var chips = document.getElementById('chips');
    chips.textContent = '';
    var c = el('span', 'chip warn', '');
    c.appendChild(el('b', null, 'data'));
    c.appendChild(document.createTextNode(' not loaded'));
    chips.appendChild(c);
  }

  // ---------- chips + filters ----------
  function chip(label, value, warn, icon, title) {
    var c = el('span', 'chip' + (warn ? ' warn' : ''));
    if (icon) { c.setAttribute('data-icon', icon); c.setAttribute('data-icon-size', '12'); }
    if (title) c.title = title;
    c.appendChild(document.createTextNode(label + ' '));
    c.appendChild(el('b', null, String(value)));
    return c;
  }

  function buildChips() {
    var chips = document.getElementById('chips');
    chips.textContent = '';
    var s = state.summary || {};
    var counts = countOwned();
    /* Every count here comes from the cards THIS page loaded and filters over, so the chip row and
       the "Showing X / Y mods" meta can never disagree (the build's own summary counts raw
       catalogue rows - before the slug merge - which is a different basis). */
    chips.appendChild(chip('cards', state.all.length || s.cards || 0, false, null,
      'mod cards in this build'));
    chips.appendChild(chip('owned', counts.owned, false, null,
      'mods you own at least one copy of'));
    chips.appendChild(chip('missing', counts.missing, false, null,
      'mods you do not own'));
    chips.appendChild(chip('dupes', counts.dupes, counts.extra > 0, null,
      'mods owned more than once'));
    chips.appendChild(chip('quoted', quoteCount(), quoteCount() === 0, 'tag',
      'cards with a local price quote'));
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

  // ---------- condition (derived from the best copy's rank ratio) ----------
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
    chip.title = cond.max > 0
      ? 'rank ' + cond.rank + '/' + cond.max + ' · ' + Math.round(cond.ratio * 100) + '% ranked'
      : 'no rank scale';
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

  /* Every rarity chip carries its own count, from one helper, so no chip sits count-less beside
     its neighbours: the build's per-rarity owned/total, the local foil count for Prime/foil (foil
     is a card trait, not a rarity key in the build) and the catalogue size for All. */
  function foilStats() {
    var owned = 0, total = 0;
    state.all.forEach(function (c) { if (isFoil(c)) { total++; if (c.owned_copies > 0) owned++; } });
    return { owned: owned, total: total, totalOnly: false };
  }

  function rarityBucket(key) {
    if (key === '') return { owned: state.all.length, total: state.all.length, totalOnly: true };
    if (key === 'Prime') return foilStats();
    return ((state.summary && state.summary.rarities) || {})[key] || null;
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
      var bucket = rarityBucket(key);
      if (bucket) {
        btn.appendChild(el('span', 'mcd-rank', ' ' +
          (bucket.totalOnly ? bucket.total : bucket.owned + '/' + bucket.total)));
        btn.title = bucket.totalOnly
          ? 'every rarity · ' + bucket.total + ' cards in this build'
          : bucket.owned + ' owned of ' + bucket.total;
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

  // ---------- art (local only) ----------
  /* Card art is LOCAL: the 4x wiki set built on this PC (static/hi/index.json -> /hi/<slug>.webp).
     The warframe.market CDN refuses these embeds (HTTP 403 + Cross-Origin-Resource-Policy:
     same-origin), so the grid never asks it for an image at all - a card with no local file gets
     the shared drawer's letter tile, so nothing shows a broken image and the console stays clean. */
  /* art source for a card: the local hi-res set only - never the remote CDN */
  /* The grid loads the 264px thumb set (tools/build_card_thumbs.py). The full files are 1000x1456
     and about 261 KB each - 140 of them decoding into 125px tiles is what made this page lag
     (Jay 2026-09-28). full=true is for the inspect overlay, which keeps the crisp original. */
  function artSrc(card, full) {
    if (!card) return null;
    return (state.hi && state.hi[card.slug]) ? '/hi/' + (full ? '' : 'thumb/') + card.slug + '.webp' : null;
  }
  function artAlt(card, full) { return artSrc(card, !full); }

  /* cardart/index.json maps slug -> "file.webp" (art fills the front, our wording rides on it)
     or {file: "file.webp", baked: true} when the file already IS the finished card face
     (its own frame, title, stats and polarity) - then nothing is drawn on top of it. */
  function artEntry(card) {
    var v = card && (state.cardart || {})[card.slug];
    if (!v) return null;
    if (typeof v === 'string') return { file: v, baked: false };
    return v.file ? { file: v.file, baked: !!v.baked } : null;
  }

  /* the fallback tile (same colours as the drawer's .dw-avatar): a card with no local art.
     The letter is the drawer's rule: first alphanumeric character of the name (or slug), uppercased. */
  function initial(name, slug) {
    var s = String(name || slug || '?').replace(/[^A-Za-z0-9]/g, '');
    return (s.charAt(0) || '?').toUpperCase();
  }

  function addTile(art, card) {
    if (!art || !card || art.querySelector('.mcd-tile')) return;
    var tile = el('span', 'mcd-tile', initial(card.name, card.slug));
    tile.setAttribute('aria-hidden', 'true');
    art.classList.add('has-tile');       // the polarity line steps back while the tile is the art
    art.appendChild(tile);
  }

  function addArt(art, card, full) {
    if (!art || !card || art.querySelector('.mcd-art-img')) return;
    if (artEntry(card)) return;   // full-art / baked faces NEVER take the base card image
    var src = artSrc(card, full);
    if (!src) { addTile(art, card); return; }
    var img = el('img', 'mcd-art-img');
    img.alt = '';
    img.loading = 'lazy';
    img.decoding = 'async';
    img.referrerPolicy = 'no-referrer';
    // a missing thumb (or a local file that will not decode): try the other size, then the tile
    var tried = false;
    img.addEventListener('error', function () {
      if (!tried) { tried = true; img.src = artAlt(card, full); return; }
      img.remove();
      art.classList.remove('has-art');
      addTile(art, card);
    });
    img.src = src;
    art.classList.add('has-art');
    art.appendChild(img);
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
  // Foil rendering is DISABLED by default while Jay builds the final selective-mask
  // holo himself; the layer spans, type CSS, FOILS map and --mx/--my plumbing all stay
  // wired so selective masking can reuse them. Flip to true to bring the effect back.
  var HOLO_ENABLED = false;
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
    // foil: rarity picks the effect (off for now — see HOLO_ENABLED above)
    var foil = HOLO_ENABLED ? foilFor(card) : 'none';
    node.setAttribute('data-foil', foil);
    node.style.setProperty('--foil-i', String(FOILS[foil] || 0));
    node.style.setProperty('--mx', '50');
    node.style.setProperty('--my', '50');
    node.setAttribute('aria-label',
      card.name + ', ' + (card.rarity || 'unknown rarity') + (isFoil(card) ? ' foil' : '') +
      ', ' + (owned ? (card.owned_copies + (card.owned_copies === 1 ? ' copy' : ' copies') +
        (card.owned_rank != null ? ', rank ' + card.owned_rank : '')) : 'not owned') +
      (card.lane_rank != null && card.lane_ask != null
        ? ', lowest ask at rank ' + card.lane_rank + ' ' + fmt(card.lane_ask) + ' platinum'
        : (card.floor != null ? ', lowest ask ' + fmt(card.floor) + ' platinum' : '')) +
      ', click to inspect the card');

    var inner = el('div', 'mcd-inner');

    // front — full-art cards show the art across the whole face; the art leads, so only the
    // name + the mod's own text ride on it (the polarity seal sits top-right, CSS-positioned)
    var front = el('div', 'mcd-face mcd-front');
    var fa = artEntry(card);
    if (fa) {
      front.classList.add('has-fullart');
      if (fa.baked) front.classList.add('art-baked');
      front.style.setProperty('--cf', "url('/cardart/" + fa.file + "')");
    }
    node.setAttribute('data-art', fa ? 'full' : 'standard');
    var art = el('div', 'mcd-art');
    art.appendChild(el('span', 'mcd-type', card.type || 'mod'));
    if (!owned) art.appendChild(el('span', 'mcd-missing-flag', 'missing'));
    // local art when this PC has the file, else the drawer's letter tile. Full-art cards paint
    // from their own manifest file and never take an <img>; nothing here asks a remote host,
    // so no card can render a broken-image icon and the console stays clean.
    if (!fa) addArt(art, card, !!(opts && opts.full));
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
    // the mod's own card text: full-art faces draw it over the art, and a card with NO local art
    // shows it too (the face would otherwise be an empty plate) - an art card already prints its
    // text inside the image, so the drawn box there stays off
    if ((fa || !artSrc(card)) && card.stats_text) body.appendChild(el('div', 'mcd-desc', card.stats_text));
    // rank pips, condition chip and local prices are NOT on card faces any more (Jay: the
    // inspect panel to the right carries that) — pips()/priceLine() stay for future use
    if (!owned) body.appendChild(el('div', 'mcd-missing-flag', 'not owned'));
    front.appendChild(body);

    // back — the universal card back (static/cardback.webp, painted by CSS); all card
    // details live in the inspect panel
    var back = el('div', 'mcd-face mcd-back');

    addFoilLayers(front);
    addFoilLayers(back);
    inner.appendChild(front);
    inner.appendChild(back);
    node.appendChild(inner);

    // click opens the inspect view (the grid never flips on hover — flipping lives
    // in the overlay); inside the overlay (opts.quiet) a click flips the big card.
    node.addEventListener('click', function () {
      if (opts && opts.quiet) { node.classList.toggle('flipped'); return; }
      state.lastFocus = node;
      openInspect(card);
    });
    return node;
  }

  // ---------- inspect view: big card (drag to tilt in 3D), flip, info card ----------
  var ins = null;

  function insButton(cls, label, fn, icon) {
    var b = el('button', 'mcd-btn ' + cls, label);
    if (icon) b.setAttribute('data-icon', icon);
    b.type = 'button';
    b.addEventListener('click', fn);
    return b;
  }

  function insRow(label, value, icon) {
    var r = el('div', 'ins-row');
    var l = el('span', 'ins-lbl', label);
    if (icon) l.setAttribute('data-icon', icon);
    r.appendChild(l);
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
      bigCard: null, rx: 0, ry: 0, tx: 0, ty: 0, tx2: 0, ty2: 0, zoom: 1.85, drag: null, moved: false,
      raf: 0, last: 0, mode: 'idle',
    };
    bd.addEventListener('click', closeInspect);
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && !ins.wrap.classList.contains('hidden')) closeInspect();
    });

    // ---- single unified rotation state: mode = idle | hover | drag | settled ----
    // Hover math reads the STAGE rect (never transformed). Reading the card's own
    // transformed rect made the tilt feed back into itself -> the left/right spazzing.
    tilt.addEventListener('pointerdown', function (e) {
      ins.mode = 'drag';
      ins.drag = { x: e.clientX, y: e.clientY, tx: ins.tx, ty: ins.ty };
      ins.moved = false;
      tilt.classList.add('dragging');
      if (tilt.setPointerCapture) tilt.setPointerCapture(e.pointerId);
      e.preventDefault();
    });
    tilt.addEventListener('pointermove', function (e) {
      if (ins.drag) {                        // drag is the authoritative rotation input
        var dx = e.clientX - ins.drag.x;
        var dy = e.clientY - ins.drag.y;
        if (Math.abs(dx) + Math.abs(dy) > 6) ins.moved = true;
        // bounded so it still reads like a physical card under inspection
        ins.ty = Math.max(-20, Math.min(20, ins.drag.ty - dy * 0.22));
        ins.tx = Math.max(-30, Math.min(30, ins.drag.tx + dx * 0.26));
        return;
      }
      if (ins.mode === 'settled') return;    // just dragged: hold the angle, hover stays out
      if (e.pointerType && e.pointerType !== 'mouse') return;
      var r = stage.getBoundingClientRect(); // stable, untransformed reference
      ins.tx = Math.max(-6.5, Math.min(6.5, ((e.clientX - (r.left + r.width / 2)) / r.width) * 26));
      ins.ty = Math.max(-6.5, Math.min(6.5, -((e.clientY - (r.top + r.height / 2)) / r.height) * 26));
      ins.mode = 'hover';
    });
    tilt.addEventListener('pointerleave', function () {
      if (ins.drag) return;
      ins.mode = 'idle';                     // settle smoothly home; idle drift resumes
      ins.tx = 0;
      ins.ty = 0;
    });
    function endDrag(e) {
      var wasMoved = ins.moved;
      ins.drag = null; ins.mode = 'settled'; tilt.classList.remove('dragging');
      // Pointer capture retargets the follow-up click to the tilt, so a plain click on
      // the card never reaches the card's own click handler — flip here instead, only
      // when the gesture wasn't a drag and the release landed on the card.
      if (!wasMoved && e && e.type === 'pointerup') {
        var hit = document.elementFromPoint(e.clientX, e.clientY);
        var cc = hit && hit.closest ? hit.closest('.mcd-card') : null;
        if (cc && tilt.contains(cc)) cc.classList.toggle('flipped');
      }
    }
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
    I.mode = 'idle';
    I.zoom = 1.85;
    applyTilt();

    // big card (same builder; inside the overlay a click flips it)
    I.holder.textContent = '';
    var big = buildCard(card, { quiet: true, full: true });
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
    // the grade/condition reason — moved here off the card back, so the panel is the
    // single home for every card detail
    I.info.appendChild(gradeLine(card));

    var pol = polarityOf(card);
    insRow('Type', card.type || '—');
    insRow('Polarity', pol[1] + ' (' + pol[0] + ')');
    insRow('Base drain', card.base_drain != null ? String(card.base_drain) : '—');
    insRow('Max rank', card.max_rank != null ? String(card.max_rank) : '—');
    insRow('Best copy', card.owned_rank != null
      ? 'rank ' + card.owned_rank + (card.max_rank != null ? ' / ' + card.max_rank : '') : 'not owned');
    if (card.owned_copies > 1) insRow('Spare copies', String(card.owned_copies - 1));
    // Rank lanes: the rank you own is priced from its own order book (the any-rank
    // "sell floor" is usually a rank-0 listing and misprices a ranked copy).
    if (card.lane_rank != null) {
      insRow('↓ Lowest ask · R' + card.lane_rank,
        card.lane_ask != null ? fmt(card.lane_ask) + 'p' : 'nothing at this rank', 'tag');
      insRow('↑ Top bid · R' + card.lane_rank,
        card.lane_bid != null ? fmt(card.lane_bid) + 'p' : 'nothing at this rank', 'tag');
    } else {
      insRow('↓ Lowest ask', card.floor != null ? fmt(card.floor) + 'p' : 'no listings', 'tag');
    }
    insRow('Median (48h · all ranks)', card.median != null ? fmt(card.median) + 'p' : '—', 'tag');
    insRow('Slug', card.slug);

    // bar
    I.bar.textContent = '';
    I.bar.appendChild(insButton('ins-flip', 'Flip card', function () { big.classList.toggle('flipped'); },
      'arrows-clockwise'));
    I.bar.appendChild(insButton('ins-reset', 'Reset view', function () {
      I.tx = 0; I.ty = 0; I.zoom = 1.85;   // loop eases back to neutral
      I.holder.style.setProperty('--ins-scale', '1.85');
    }, 'arrows-clockwise'));
    var mkt = el('a', 'mcd-btn ins-market', 'warframe.market');
    mkt.setAttribute('data-icon', 'arrow-square-out');
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
      empty.textContent = 'No cards match those filters.';
      empty.removeAttribute('title');
      empty.classList.remove('hidden');
      more.classList.add('hidden');
    } else {
      empty.classList.add('hidden');
      updateMore();
    }
    document.getElementById('grid').setAttribute('aria-label',
      'Mod cards (' + state.filtered.length + ' shown)');
  }

  function paint() {
    var grid = document.getElementById('grid');
    var frag = document.createDocumentFragment();
    for (var i = 0; i < state.shown; i++) frag.appendChild(buildCard(state.filtered[i]));
    grid.textContent = '';
    grid.appendChild(frag);
    /* Cache each card's untransformed rect (document space) for the hover-tilt math - measured
       before any tilt vars exist, so a read can never feed itself back. The pass is one forced
       layout, so it runs after the swap's frame: a keystroke must not wait on 180 measurements
       (Jay 2026-09-28, the cards page lagged). Hover measures on demand if a card has no rect. */
    var gen = (paintGen += 1);
    requestAnimationFrame(function () {
      if (gen !== paintGen) return;                 // a newer paint owns the grid now
      for (var c = 0; c < grid.children.length; c++) {
        var gnode = grid.children[c];
        if (gnode._gr) continue;
        var rr = gnode.getBoundingClientRect();
        gnode._gr = { l: rr.left + window.scrollX, t: rr.top + window.scrollY, w: rr.width, h: rr.height };
      }
    });
  }

  function updateMore() {
    var more = document.getElementById('moreWrap');
    var btn = document.getElementById('moreBtn');
    var left = Math.max(0, state.filtered.length - state.shown);
    btn.textContent = left > 0 ? 'Show ' + Math.min(BATCH, left) + ' more (' + left + ' left)' : 'Show more';
    btn.title = left > 0 ? state.shown + ' of ' + state.filtered.length + ' matches shown' : '';
    more.classList.toggle('hidden', left === 0);
  }

  function updateMeta() {
    var meta = document.getElementById('meta');
    var filters = [];
    if (state.rarity) filters.push(state.rarity === 'Prime' ? 'prime/foil' : state.rarity.toLowerCase());
    if (state.type) filters.push(state.type.toLowerCase());
    if (!state.owned) filters.push('hides owned');
    if (!state.missing) filters.push('hides missing');
    if (state.dupes) filters.push('dupes only');
    if (state.q) filters.push('“' + state.q + '”');

    /* ONE line: what is on screen, what the filters cut it from, and which filters are on. The
       collection's own counts live in the header chips (and the rarity buttons carry their
       coverage) - repeating them here printed the same four numbers twice on one screen
       (screenshot review, 2026-09-28). The build notes stay in title=. */
    meta.textContent = '';
    meta.appendChild(el('span', null, 'Showing '));
    meta.appendChild(el('b', null, state.shown + ' / ' + state.filtered.length));
    meta.appendChild(el('span', null, ' mods'));
    if (state.filtered.length !== state.all.length) {
      meta.appendChild(el('span', null, ' (of ' + state.all.length + ' in this build)'));
    }
    if (filters.length) meta.appendChild(el('span', null, ' · filters: ' + filters.join(', ')));

    var help = [];
    var s = state.summary || {};
    if (s.rarities) {
      var parts = [];
      Object.keys(s.rarities).forEach(function (k) {
        parts.push(k + ' ' + s.rarities[k].owned + '/' + s.rarities[k].total);
      });
      help.push('rarity coverage (owned/total): ' + parts.join(' · '));
    }
    if (state.notes && state.notes.length) help.push(state.notes.join(' · '));
    meta.title = help.join(' · ');
  }

  // ---------- wiring ----------
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

  document.addEventListener('DOMContentLoaded', function () {
    wireThemePanel();
    var q = document.getElementById('q');
    /* one render per pause, not per keystroke: rebuilding 180 tiles measured ~335 ms on the second
       letter (Jay 2026-09-28: the page lagged). 140 ms is under the gap between keystrokes while
       still feeling immediate, and the value is compared first so a no-op input never renders. */
    q.addEventListener('input', function () {
      var v = q.value.trim().toLowerCase();
      window.clearTimeout(q._t);
      if (v === state.q) return;
      q._t = window.setTimeout(function () { state.q = v; render(); }, 140);
    });
    document.getElementById('clearBtn').addEventListener('click', function () {
      window.clearTimeout(q._t);                 // a pending debounce must not re-apply the old query
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
      if (card !== gTilt.card) {
        gReset();
        gTilt.card = card;
        /* Measure the card the pointer just entered, in this event, while no tilt var is on it.
           The paint pass caches rects, but a card that was offscreen then carries the intrinsic
           placeholder (content-visibility), and a live read of an already-tilted card would feed
           the tilt back into itself and make the card jitter. One rect read per hover change. */
        if (card) card._gr = null;
      }
      if (!card) return;
      // cached doc-space rect (measured before tilt) — a live read of a tilted
      // card would feed the tilt back into itself and make the card jitter
      var r = card._gr;
      if (!r) {
        var rr = card.getBoundingClientRect();
        r = card._gr = { l: rr.left + window.scrollX, t: rr.top + window.scrollY, w: rr.width, h: rr.height };
      }
      gTilt.x = Math.max(0, Math.min(100, ((e.clientX + window.scrollX - r.l) / r.w) * 100));
      gTilt.y = Math.max(0, Math.min(100, ((e.clientY + window.scrollY - r.t) / r.h) * 100));
      if (!gTilt.raf) gTilt.raf = requestAnimationFrame(gFlush);
    });
    gEl.addEventListener('pointerleave', gReset);
    window.addEventListener('resize', function () {
      for (var w = 0; w < gEl.children.length; w++) gEl.children[w]._gr = null;   // rects moved
    });
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
    document.getElementById('moreBtn').addEventListener('click', function () {
      state.shown = Math.min(state.filtered.length, state.shown + BATCH);
      paint();
      updateMeta();
      updateMore();
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
