/* lookup.js — public Warframe item lookup (no frameworks, no external libs)
   Data: /lookup_items.json (slug/name/icon/thumb from the local WFM item cache)
         /api/items        (live prices from this PC's local WFM snapshot)
   All injected strings are escaped/created as text nodes; no innerHTML with data. */
'use strict';
(function () {
  var CDN = 'https://warframe.market/static/assets/';   // verified: base + icon path => HTTP 200 image/png
  var MAX = 30;                                         // max cards rendered
  var MARKET = 'https://warframe.market/items/';

  var state = { items: [], map: Object.create(null), q: '', hasPrices: false, lastFocus: null,
                hi: null };                                   // slug -> upscaled local art
  var imgState = 'probing';   // 'probing' | 'ok' | 'off' — can this network embed the image CDN?

  // ---------- helpers ----------
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = String(text);
    return n;
  }

  // whitelist on catalog-provided asset paths -> full CDN URL (or null).
  // Blocks quotes/angle brackets/backslashes/whitespace/control chars and '..' so a
  // tampered catalog can never break out of the src attribute; segments are encoded.
  function cdnUrl(p) {
    if (typeof p !== 'string' || !p || p.indexOf('..') !== -1) return null;
    if (/[\x00-\x1f\x7f"'<>\\\s]/.test(p)) return null;
    return CDN + p.split('/').map(encodeURIComponent).join('/');
  }

  function fmt(v) {
    if (v == null || v === '') return '—';
    var n = Number(v);
    if (!isFinite(n)) return '—';
    return Number.isInteger(n) ? String(n) : String(+n.toFixed(n < 10 ? 2 : 0));
  }
  function fmtInt(v) {
    var n = Number(v);
    return isFinite(n) ? String(Math.round(n)) : '—';
  }
  function initial(name, slug) {
    var s = String(name || slug || '?').replace(/[^A-Za-z0-9]/g, '');
    return (s.charAt(0) || '?').toUpperCase();
  }
  function escRe(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }

  // letter-avatar fallback when the CDN image is unavailable (offline etc.)
  function avatar(it, big) {
    var d = el('div', big ? 'lk-avatar big' : 'lk-avatar', initial(it.name, it.slug));
    d.setAttribute('aria-hidden', 'true');
    return d;
  }

  // image: local hi-res (this PC) > thumb/icon downgrade -> letter avatar (never throws)
  function hiUrl(it) {
    return (it && state.hi && state.hi[it.slug]) ? '/hi/' + it.slug + '.webp' : null;
  }
  function image(it, big) {
    var local = hiUrl(it);
    var main = local || (big ? (cdnUrl(it.icon) || cdnUrl(it.thumb)) : (cdnUrl(it.thumb) || cdnUrl(it.icon)));
    var alt = big ? cdnUrl(it.thumb) : cdnUrl(it.icon);
    if (!main || (imgState === 'off' && !local)) return avatar(it, big);
    var img = el('img', big ? 'lk-p-img' : 'lk-thumb');
    img.alt = it.name || it.slug || '';
    img.loading = big ? 'eager' : 'lazy';
    img.decoding = 'async';
    img.referrerPolicy = 'no-referrer';
    img.addEventListener('error', function () {
      if (alt && img.getAttribute('src') !== alt) { img.setAttribute('src', alt); return; }  // one downgrade
      var av = avatar(it, big);
      if (img.id) av.id = img.id;                       // keep ids stable (e.g. #dImg) across the swap
      if (img.parentNode) img.parentNode.replaceChild(av, img);
      var z = img.lkZoom;                               // the letter tile keeps the click-to-enlarge wiring
      if (z) zoomable(av, z.it, z.opener || av);
    });
    img.setAttribute('src', main);
    return img;
  }

  // ---------- data ----------
  /* Item art lives on the warframe.market CDN, which refuses cross-origin embeds (HTTP 403 with
     Cross-Origin-Resource-Policy: same-origin -> ERR_BLOCKED_BY_RESPONSE) from some networks.
     Ask once per page load: with a healthy host the grid renders real thumbs, with a refusing
     one it renders the letter tiles straight away - one request instead of one per card. */
  function probeImages() {
    var url = null;
    for (var i = 0; i < state.items.length && !url; i++) {
      url = cdnUrl(state.items[i].thumb) || cdnUrl(state.items[i].icon);
    }
    if (!url) { imgState = 'off'; return Promise.resolve(); }
    return new Promise(function (resolve) {
      var probe = new Image();
      var done = false;
      function finish(ok) {
        if (done) return;
        done = true;
        imgState = ok ? 'ok' : 'off';
        resolve();
      }
      probe.onload = function () { finish(!!probe.naturalWidth); };
      probe.onerror = function () { finish(false); };
      setTimeout(function () { finish(true); }, 4000);   // slow host: let the lazy <img>s try
      probe.src = url;
    });
  }

  function normalizeApi(json) {
    var rows = Array.isArray(json) ? json : (json && Array.isArray(json.items) ? json.items : []);
    var by = Object.create(null);
    rows.forEach(function (r) { if (r && r.slug) by[r.slug] = r; });
    return by;
  }

  function load() {
    var meta = document.getElementById('meta');
    Promise.all([
      fetch('/lookup_items.json', { cache: 'no-cache' }).then(function (r) {
        if (!r.ok) throw new Error('lookup_items.json ' + r.status);
        return r.json();
      }),
      fetch('/api/items', { cache: 'no-cache' }).then(function (r) {
        if (!r.ok) throw new Error('api ' + r.status);
        return r.json();
      }).catch(function () { return null; }),   // page still works without prices
      fetch('/hi/index.json', { cache: 'no-cache' }).then(function (r) {
        return r.ok ? r.json() : null;
      }).catch(function () { return null; })    // local 4x upscaled art — optional
    ]).then(function (res) {
      var cat = Array.isArray(res[0]) ? res[0] : [];
      state.hi = (res[2] && res[2].items) || null;
      var prices = normalizeApi(res[1]);
      state.hasPrices = !!res[1];
      state.items = cat.map(function (c) {
        var p = prices[c.slug] || {};
        return {
          slug: c.slug,
          name: c.name || p.name || c.slug,
          icon: c.icon || null,
          thumb: c.thumb || null,
          cat: p.cat || '',
          count: Number(p.count || 0),
          ducats: p.ducats == null ? null : Number(p.ducats),
          wts: p.wts == null ? null : Number(p.wts),
          wtb: p.wtb == null ? null : Number(p.wtb),
          vol48: p.vol48 == null ? null : Number(p.vol48),
          median: p.median == null ? null : Number(p.median),
          // rank-lane fields (owned mods): the detail panel prices the copy you hold
          own_rank: p.own_rank == null ? null : Number(p.own_rank),
          equipped: p.equipped == null ? null : Number(p.equipped),
          max_rank: p.max_rank == null ? null : Number(p.max_rank),
          lane_rank: p.lane_rank == null ? null : Number(p.lane_rank),
          lane_ask: p.lane_ask == null ? null : Number(p.lane_ask),
          lane_bid: p.lane_bid == null ? null : Number(p.lane_bid),
          lanes: p.lanes || null
        };
      });
      state.map = Object.create(null);
      state.items.forEach(function (it) { state.map[it.slug] = it; });

      var owned = state.items.reduce(function (a, it) { return a + (it.count > 0 ? it.count : 0); }, 0);
      var chips = document.getElementById('chips');
      chips.innerHTML = '';
      chips.appendChild(el('span', 'chip', ''));
      chips.firstChild.innerHTML = 'catalog <b>' + state.items.length + '</b>';
      var cm = el('span', 'chip'); cm.innerHTML = 'matches <b id="chipMatches">0</b>'; chips.appendChild(cm);
      var co = el('span', 'chip'); co.innerHTML = 'owned <b>' + owned + '</b> copies'; chips.appendChild(co);
      if (!state.hasPrices) {
        var cw = el('span', 'chip warn'); cw.innerHTML = 'price feed <b>offline</b>'; chips.appendChild(cw);
      }
      probeImages().then(render);
    }).catch(function (err) {
      meta.textContent = 'Could not load the item catalog from this server (' + (err && err.message ? err.message : 'unknown error') + ').';
    });
  }

  // ---------- search ----------
  function score(it, q) {
    var n = it.name.toLowerCase(), s = it.slug.toLowerCase();
    if (n === q || s === q) return 0;
    if (n.indexOf(q) === 0) return 1;
    if (new RegExp('(^|[^a-z0-9])' + escRe(q)).test(n)) return 2;   // word start
    if (n.indexOf(q) !== -1) return 3;                              // substring in name
    if (s.indexOf(q) !== -1) return 4;                              // substring in slug only
    return -1;
  }

  function matches(q) {
    if (!q) {
      return state.items.slice().sort(function (a, b) { return (b.vol48 || 0) - (a.vol48 || 0) || a.name.localeCompare(b.name); });
    }
    var out = [];
    for (var i = 0; i < state.items.length; i++) {
      var sc = score(state.items[i], q);
      if (sc >= 0) out.push({ it: state.items[i], sc: sc });
    }
    out.sort(function (a, b) {
      return a.sc - b.sc || (b.it.vol48 || 0) - (a.it.vol48 || 0) || a.it.name.localeCompare(b.it.name);
    });
    return out.map(function (x) { return x.it; });
  }

  // ---------- render ----------
  function card(it) {
    var c = el('button', 'lk-card');
    c.type = 'button';
    c.setAttribute('role', 'listitem');
    c.setAttribute('data-slug', it.slug);
    c.setAttribute('aria-label', it.name + (it.wts != null ? ', sell ' + fmt(it.wts) + ' platinum' : '') + ', open details');
    if (it.cat) c.appendChild(el('span', 'lk-cat', it.cat.replace(/_/g, ' ')));
    if (it.count > 0) c.appendChild(el('span', 'lk-own', 'owned ' + it.count));

    c.appendChild(zoomable(image(it, false), it, c));
    c.appendChild(el('span', 'lk-name', it.name));

    var row = el('span', 'lk-row');
    var sell = el('span', 'lk-sell');
    sell.appendChild(el('span', null, '▲'));              // ▲ sell
    sell.appendChild(document.createTextNode(' ' + fmt(it.wts) + 'p'));
    var buy = el('span', 'lk-buy');
    buy.appendChild(el('span', null, '▼'));               // ▼ buy
    buy.appendChild(document.createTextNode(' ' + fmt(it.wtb) + 'p'));
    row.appendChild(sell); row.appendChild(buy);
    c.appendChild(row);

    c.appendChild(el('span', 'lk-vol', it.vol48 != null ? ('48h vol ' + fmtInt(it.vol48)) : 'no volume data'));

    c.addEventListener('click', function () { openDetail(it.slug, c); });
    return c;
  }

  function render() {
    var q = state.q.trim().toLowerCase();
    var list = matches(q);
    var grid = document.getElementById('grid');
    var meta = document.getElementById('meta');
    var empty = document.getElementById('empty');
    var clearBtn = document.getElementById('clearBtn');
    var frag = document.createDocumentFragment();
    var shown = list.slice(0, MAX);
    shown.forEach(function (it) { frag.appendChild(card(it)); });
    grid.innerHTML = '';
    grid.appendChild(frag);

    var chipM = document.getElementById('chipMatches');
    if (chipM) chipM.textContent = q ? String(list.length) : String(state.items.length);

    meta.innerHTML = '';
    if (!state.items.length) { meta.textContent = 'Loading catalog…'; return; }
    if (!q) {
      meta.appendChild(el('span', null, 'Top ' + shown.length + ' items by 48h trade volume — type to search across ' + state.items.length + ' items.'));
    } else {
      meta.appendChild(el('span', null, list.length + (list.length === 1 ? ' match' : ' matches') + ' for “' + state.q.trim() + '”'));
      if (list.length > MAX) meta.appendChild(el('span', null, ' · showing first ' + MAX));
      if (!list.length) meta.appendChild(el('span', null, ''));
    }
    if (!state.hasPrices) meta.appendChild(el('span', 'warn', ' · price feed offline (names only)'));

    clearBtn.classList.toggle('hidden', !state.q);

    if (q && !list.length) {
      empty.innerHTML = '';
      var b = el('b', null, 'No item matches “' + state.q.trim() + '”.');
      empty.appendChild(b);
      empty.appendChild(el('div', null, 'Try a shorter term — names and slugs (“prime”, “continuity”).'));
      empty.classList.remove('hidden');
    } else {
      empty.classList.add('hidden');
    }
  }

  // ---------- detail panel (same page, no navigation) ----------
  function stat(label, value, unit, cls, title) {
    var s = el('div', 'lk-stat');
    s.appendChild(el('span', 'k-label', label));
    var v = el('div', 'v' + (cls ? ' ' + cls : ''));
    v.textContent = value;
    if (unit && value !== '—') { v.appendChild(document.createTextNode(' ')); v.appendChild(el('span', 'u', unit)); }
    s.appendChild(v);
    if (title) s.title = title;
    return s;
  }

  function renderLanes(it) {
    // Order book by rank (how the market actually prices a mod): ask = cheapest sell
    // order at that rank (you buy from it, or list just under); bid = top buy order
    // (you sell to it, or bid just over). The rank you own leads its own row + chips.
    var box = document.getElementById('dLanes');
    box.innerHTML = '';
    if (!it.lanes || it.own_rank == null) return;
    var head = el('div', 'lk-lanes-head');
    head.appendChild(document.createTextNode('Order book by rank — '));
    head.appendChild(el('b', null, '↓ ask'));
    head.appendChild(document.createTextNode(' = cheapest sell order (you buy from it, or list just under) · '));
    head.appendChild(el('b', null, '↑ bid'));
    head.appendChild(document.createTextNode(' = top buy order. Ranks with no live orders are skipped.'));
    box.appendChild(head);
    var ranks = Object.keys(it.lanes).map(Number).sort(function (a, b) { return a - b; });
    if (ranks.indexOf(it.own_rank) === -1) {
      ranks.push(it.own_rank);
      ranks.sort(function (a, b) { return a - b; });
    }
    var max = it.max_rank != null ? it.max_rank : ranks[ranks.length - 1];
    ranks.forEach(function (rk) {
      var cell = it.lanes[String(rk)] || {};
      var mine = rk === it.own_rank;
      var row = el('div', 'lk-lane' + (mine ? ' mine' : ''));
      row.appendChild(el('span', 'lk-lane-rk', 'R' + rk + '/' + max));
      if (mine) row.appendChild(el('span', 'lk-lane-you', 'your copy'));
      var a = el('span', 'lk-lane-ask');
      a.title = 'cheapest sell order at rank ' + rk + (cell.n_ask != null ? ' (' + cell.n_ask + ' listings)' : '') +
        ' — buy from it, or list just under';
      a.textContent = cell.ask != null ? 'asks from ' + fmt(cell.ask) + 'p' : 'no asks';
      row.appendChild(a);
      var b = el('span', 'lk-lane-bid');
      var range = null;
      if (cell.bid != null) {
        range = (cell.bid_low != null && cell.bid_low !== cell.bid)
          ? fmt(cell.bid_low) + '–' + fmt(cell.bid) + 'p' : fmt(cell.bid) + 'p';
      }
      b.title = 'buy orders at rank ' + rk + (cell.n_bid != null ? ' (' + cell.n_bid + ' bids)' : '') +
        ' — sell to the top bid, or bid just over';
      b.textContent = range != null ? 'bids ' + range : 'no bids';
      row.appendChild(b);
      if (mine) {
        if (cell.ask != null) {
          var list = el('span', 'lk-chip lk-chip-list', 'list ' + fmtInt(Math.max(1, Math.round(cell.ask) - 1)) + 'p ↓');
          list.title = 'undercut the cheapest rank-' + rk + ' ask by 1p';
          row.appendChild(list);
        }
        if (cell.bid != null) {
          var ob = el('span', 'lk-chip lk-chip-bid', 'bid ' + fmtInt(Math.round(cell.bid) + 1) + 'p ↑');
          ob.title = 'outbid the top rank-' + rk + ' buy order by 1p';
          row.appendChild(ob);
        }
      }
      box.appendChild(row);
    });
  }

  function openDetail(slug, opener) {
    var it = state.map[slug];
    if (!it) return;
    state.lastFocus = opener || null;

    var imgSlot = document.getElementById('dImg');
    var fresh = image(it, true);
    fresh.id = 'dImg';
    zoomable(fresh, it, null);
    imgSlot.parentNode.replaceChild(fresh, imgSlot);

    document.getElementById('dName').textContent = it.name;
    document.getElementById('dSlug').textContent = it.slug;

    var stats = document.getElementById('dStats');
    stats.innerHTML = '';
    var ranked = !!it.lanes && it.own_rank != null;
    if (ranked) {
      stats.appendChild(stat('Lowest ask · R' + it.own_rank, it.lane_ask != null ? fmt(it.lane_ask) : '—',
                             it.lane_ask != null ? 'plat' : '', it.lane_ask != null ? 'accent' : 'dim',
                             'cheapest sell order at the rank you own — list just under it to sell'));
      stats.appendChild(stat('Top bid · R' + it.own_rank, it.lane_bid != null ? fmt(it.lane_bid) : '—',
                             it.lane_bid != null ? 'plat' : '', it.lane_bid != null ? '' : 'dim',
                             'highest buy order at the rank you own — quick-sell price'));
    } else {
      stats.appendChild(stat('Lowest ask', fmt(it.wts), it.wts != null ? 'plat' : '', 'accent',
                             'cheapest visible sell order for this item'));
      stats.appendChild(stat('Top bid', fmt(it.wtb), it.wtb != null ? 'plat' : '', '',
                             'highest visible buy order for this item'));
    }
    stats.appendChild(stat('Median 48h', fmt(it.median), it.median != null ? 'plat' : '', '',
                           'median of every 48h sale, all ranks — context only, not your copy’s price'));
    stats.appendChild(stat('Volume 48h', fmtInt(it.vol48), 'trades'));
    stats.appendChild(stat(it.equipped ? 'Owned · equipped' : 'Owned', String(it.count || 0),
                           it.count === 1 ? 'copy' : 'copies', it.count > 0 ? 'accent' : 'dim',
                           it.equipped ? 'includes copies slotted in a loadout — equipped copies are never sellable' : ''));
    stats.appendChild(stat('Ducats each', it.ducats == null ? '—' : fmtInt(it.ducats), it.ducats == null ? '' : 'ducats'));
    stats.appendChild(stat('Ducat value (owned)', it.ducats == null ? '—' : fmtInt((it.count || 0) * it.ducats), 'ducats'));
    renderLanes(it);

    var est = document.getElementById('dEst');
    est.innerHTML = '';
    var line = el('div');
    if (ranked) {
      // Price the copy actually held: its rank lane, never the any-rank quote.
      line.appendChild(document.createTextNode('Your rank-' + it.own_rank + ' copy: '));
      if (it.lane_bid != null) {
        line.appendChild(document.createTextNode('quick-sell to the top bid for '));
        line.appendChild(el('b', null, fmt(it.lane_bid) + 'p'));
      } else {
        line.appendChild(document.createTextNode('no buy orders at this rank — nothing to quick-sell to'));
      }
      if (it.lane_ask != null) {
        line.appendChild(document.createTextNode(it.lane_bid != null ? ' · or l' : ' — l'));
        line.appendChild(document.createTextNode('ist just under the lowest ask ('));
        line.appendChild(el('b', null, fmt(it.lane_ask) + 'p'));
        line.appendChild(document.createTextNode(') = about '));
        line.appendChild(el('b', null, fmtInt(Math.max(1, Math.round(it.lane_ask) - 1)) + 'p'));
      } else if (it.lane_bid != null) {
        line.appendChild(document.createTextNode(' · no sell orders at this rank'));
      }
      line.appendChild(document.createTextNode('.'));
    } else if (it.wts == null) {
      line.appendChild(document.createTextNode('No sell orders in the current snapshot, so a platinum value can’t be estimated right now.'));
    } else if (it.count > 0) {
      line.appendChild(document.createTextNode('Estimated value: you own '));
      line.appendChild(el('b', null, String(it.count)));
      line.appendChild(document.createTextNode(' × '));
      line.appendChild(el('b', null, fmt(it.wts) + 'p'));
      line.appendChild(document.createTextNode(' lowest ask = about '));
      line.appendChild(el('b', null, fmtInt((it.count || 0) * (it.wts || 0)) + ' platinum'));
      line.appendChild(document.createTextNode(' if every copy sells at today’s lowest ask.'));
    } else {
      line.appendChild(document.createTextNode('You don’t own this item. Its lowest ask is '));
      line.appendChild(el('b', null, fmt(it.wts) + 'p'));
      line.appendChild(document.createTextNode(', so one copy would be worth about '));
      line.appendChild(el('b', null, fmtInt(it.wts) + ' platinum'));
      line.appendChild(document.createTextNode('.'));
    }
    est.appendChild(line);
    if (it.equipped) {
      var eqn = el('div', 'sub');
      eqn.textContent = it.equipped + ' cop' + (it.equipped === 1 ? 'y is' : 'ies are') +
        ' equipped in a loadout — equipped copies are never counted as sellable.';
      est.appendChild(eqn);
    }
    var sub = el('div', 'sub');
    if (ranked) {
      sub.textContent = 'All-rank context: 48h median ' + (it.median != null ? fmt(it.median) + 'p' : '—') +
        ' · volume ' + fmtInt(it.vol48) + ' trades. The median mixes every rank, so read it as context — not your copy’s price.';
    } else if (it.median != null && it.count > 0) {
      sub.textContent = 'At the 48h median (' + fmt(it.median) + 'p) the same ' + it.count + ' cop' + (it.count === 1 ? 'y' : 'ies') +
        ' would be ≈ ' + fmtInt(it.count * it.median) + 'p · ' + (it.ducats != null ? ((it.count * it.ducats) + ' ducats if dissolved instead') : 'no ducat value');
    } else if (it.ducats != null && it.count > 0) {
      sub.textContent = it.count + ' × ' + it.ducats + ' ducats = ' + (it.count * it.ducats) + ' ducats if dissolved instead of sold';
    } else {
      sub.textContent = 'Owned = your last snapshot · ask = cheapest sell · bid = top buy (local scan).';
    }
    est.appendChild(sub);

    var links = document.getElementById('dLinks');
    links.innerHTML = '';
    var a = el('a', 'btn primary', 'Open on warframe.market ↗');
    a.href = MARKET + encodeURIComponent(it.slug);
    a.target = '_blank';
    a.rel = 'noopener noreferrer';
    links.appendChild(a);
    var b = el('button', 'btn', 'Close');
    b.type = 'button';
    b.addEventListener('click', closeDetail);
    links.appendChild(b);

    var d = document.getElementById('detail');
    d.classList.remove('hidden');
    document.body.style.overflow = 'hidden';
    document.getElementById('dClose').focus();
  }

  function closeDetail() {
    document.getElementById('detail').classList.add('hidden');
    document.body.style.overflow = '';
    if (state.lastFocus && document.contains(state.lastFocus)) state.lastFocus.focus();
    state.lastFocus = null;
  }

  // ---------- image zoom (click any item image for the full-size render) ----------
  function zoom(it, opener) {
    if (!it) return;
    state.zoomItem = it;
    state.zoomOpener = opener || null;
    var slot = document.getElementById('zImg');
    var fresh = image(it, true);
    fresh.id = 'zImg';
    fresh.className = fresh.className.indexOf('lk-avatar') !== -1 ? 'lk-z-img lk-avatar' : 'lk-z-img';
    fresh.alt = it.name || it.slug || '';
    slot.parentNode.replaceChild(fresh, slot);
    var cap = document.getElementById('zCap');
    cap.textContent = it.name || it.slug || '';
    var bits = [];
    if (it.wts != null) bits.push('▲ ' + fmt(it.wts) + 'p');
    if (it.wtb != null) bits.push('▼ ' + fmt(it.wtb) + 'p');
    if (it.count) bits.push('owned ' + it.count);
    if (it.vol48 != null) bits.push('48h vol ' + fmtInt(it.vol48));
    if (bits.length) { cap.appendChild(el('span', 'sub', bits.join(' · '))); }
    else if (it.slug) { cap.appendChild(el('span', 'sub', it.slug)); }
    document.getElementById('zoom').classList.remove('hidden');
    document.body.style.overflow = 'hidden';
    document.getElementById('zClose').focus();
  }

  function closeZoom() {
    document.getElementById('zoom').classList.add('hidden');
    var detailOpen = !document.getElementById('detail').classList.contains('hidden');
    document.body.style.overflow = detailOpen ? 'hidden' : '';
    if (detailOpen) { document.getElementById('dClose').focus(); return; }
    if (state.zoomOpener && document.contains(state.zoomOpener)) { state.zoomOpener.focus(); }
    state.zoomOpener = null;
  }

  // make an image element open the zoom overlay (mouse + keyboard). The wiring is remembered on
  // the element so the letter-tile fallback can inherit it if the image fails to load.
  function zoomable(imgEl, it, opener) {
    imgEl.classList.add('lk-zoomable');
    imgEl.title = 'Click to enlarge';
    imgEl.tabIndex = 0;
    imgEl.setAttribute('role', 'button');
    imgEl.setAttribute('aria-label', 'Enlarge ' + (it.name || it.slug || 'image'));
    imgEl.lkZoom = { it: it, opener: opener || null };
    imgEl.addEventListener('click', function (e) {
      if (e && e.stopPropagation) e.stopPropagation();
      zoom(it, opener || imgEl);
    });
    imgEl.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.stopPropagation(); zoom(it, imgEl); }
    });
    return imgEl;
  }

  // ---------- wiring ----------
  document.addEventListener('DOMContentLoaded', function () {
    var q = document.getElementById('q');
    q.addEventListener('input', function () { state.q = q.value; render(); });
    document.getElementById('clearBtn').addEventListener('click', function () { q.value = ''; state.q = ''; render(); q.focus(); });
    document.getElementById('dClose').addEventListener('click', closeDetail);
    document.getElementById('backdrop').addEventListener('click', closeDetail);
    document.getElementById('zClose').addEventListener('click', closeZoom);
    document.getElementById('zClose2').addEventListener('click', closeZoom);
    document.getElementById('zoomBackdrop').addEventListener('click', closeZoom);
    document.getElementById('zDetails').addEventListener('click', function () {
      var it = state.zoomItem;
      closeZoom();
      if (it) openDetail(it.slug, document.querySelector('#grid .lk-card[data-slug="' + it.slug + '"]'));
    });

    document.addEventListener('keydown', function (e) {
      var detailOpen = !document.getElementById('detail').classList.contains('hidden');
      var zoomOpen = !document.getElementById('zoom').classList.contains('hidden');
      if (e.key === 'Escape') {
        if (zoomOpen) { closeZoom(); return; }
        if (detailOpen) { closeDetail(); return; }
      }
      if (e.key === '/' && document.activeElement !== q && !detailOpen && !zoomOpen) { e.preventDefault(); q.focus(); return; }
      if (e.key === 'Enter' && document.activeElement === q) {
        var first = document.querySelector('#grid .lk-card');
        if (first) first.click();
      }
    });

    var qp = new URLSearchParams(location.search).get('q');
    if (qp) { q.value = qp; state.q = qp; }
    load();
  });
})();
