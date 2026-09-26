/* drawer.js - shared item-detail drawer (works on any page that includes drawer.css + drawer.js).
   Public API:
     window.wfmOpenItem(key[, opener])   key = item slug or name, case/space-insensitive
     window.wfmOpenItem.close()          close it programmatically
     window.wfmOpenItem.preload([keys])  warm the data caches without opening anything
   Layers: 1 = recommended action (big), 2 = your copies + the four market tiles,
   3 = collapsed sections (Market details, Collection & sets, Advanced).
   Plain words on the surface; precise trader terms (lowest ask, top bid, lane, median,
   48h volume) live only in title tooltips or the Advanced section.
   A ranked copy is always priced from its own rank lane (lane_ask / lane_bid) - never
   from the any-rank quote (wts / wtb). Equipped copies are never sellable.
   Data is fetched lazily on first open, cached in memory, one fetch per endpoint:
     /api/items, /lookup_items.json, /hi/index.json, /api/feature/advisor,
     /api/feature/collection, /api/feature/sets, /api/report
   Everything renders through textContent - no innerHTML with data. */
'use strict';
(function () {
  var MARKET = 'https://warframe.market/items/';
  var CDN = 'https://warframe.market/static/assets/';
  var HI_DIR = '/hi/';
  var MAX_WHY = 2;                                  // reason lines shown under the action headline
  var NAME_ID = 'wfmDrawerName';                    // panel aria-labelledby target
  var BAD_URL = /[\x00-\x1f\x7f"'<>\\\s]/;

  /* ================= helpers ================= */
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = String(text);
    return n;
  }
  function clear(n) { while (n.firstChild) n.removeChild(n.firstChild); }
  function isNum(v) { return v != null && v !== '' && isFinite(Number(v)); }
  function num(v) { return isNum(v) ? Number(v) : null; }
  function fmt(v) {
    if (!isNum(v)) return '-';
    var n = Number(v);
    return Number.isInteger(n) ? String(n) : String(+n.toFixed(n < 10 ? 2 : 0));
  }
  function fmtInt(v) {
    if (!isNum(v)) return '-';
    return String(Math.round(Number(v)));
  }
  function copies(n) { return String(n) + (n === 1 ? ' copy' : ' copies'); }
  function label(s) { return String(s == null ? '' : s).replace(/_/g, ' '); }
  function initial(name, slug) {
    var s = String(name || slug || '?').replace(/[^A-Za-z0-9]/g, '');
    return (s.charAt(0) || '?').toUpperCase();
  }
  function normKey(s) { return String(s == null ? '' : s).toLowerCase().replace(/[_\s]+/g, ' ').trim(); }
  function looseKey(s) { return String(s == null ? '' : s).toLowerCase().replace(/[^a-z0-9]/g, ''); }
  function slugify(s) {
    return String(s == null ? '' : s).trim().toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
  }
  function titleCase(s) {
    return String(s == null ? '' : s).replace(/[_-]+/g, ' ').replace(/\s+/g, ' ').trim()
      .replace(/(^|\s)([a-z])/g, function (m, a, b) { return a + b.toUpperCase(); });
  }
  /* Catalog-provided asset paths -> full CDN URL (or null). Blocks quotes / angle brackets /
     backslashes / whitespace / control chars and '..' so a tampered catalog can never break
     out of the src attribute; relative segments are encoded, absolute https URLs pass through. */
  function cdnUrl(p) {
    if (typeof p !== 'string' || !p || p.indexOf('..') !== -1) return null;
    if (BAD_URL.test(p)) return null;
    if (p.indexOf('https://') === 0) return p;          // collection-log icons are absolute
    if (p.indexOf('http://') === 0 || p.indexOf('//') === 0) return null;
    return CDN + p.split('/').map(encodeURIComponent).join('/');
  }

  /* ================= data (lazy + cached) ================= */
  var store = Object.create(null);
  function fetchOnce(name, url) {
    var rec = store[name];
    if (rec && rec.done) return Promise.resolve(rec.value);
    if (rec && rec.pending) return rec.pending;
    rec = store[name] = { done: false, value: null, pending: null };
    rec.pending = fetch(url, { cache: 'no-cache' }).then(function (r) {
      if (!r.ok) throw new Error(name + ' HTTP ' + r.status);
      return r.json();
    }).then(function (j) {
      rec.done = true; rec.value = j; rec.pending = null;
      return j;
    }).catch(function (err) {
      delete store[name];                        // a failed load is retried on the next open
      throw err;
    });
    return rec.pending;
  }
  function soft(name, url) { return fetchOnce(name, url).catch(function () { return null; }); }

  var idx = { ready: false, map: Object.create(null), byNorm: Object.create(null),
              byLoose: Object.create(null), hi: null, count: 0, degraded: false };
  var PRICE_FIELDS = ['count', 'equipped', 'ducats', 'wts', 'wtb', 'vol48', 'median', 'avg48',
                      'value', 'spread', 'own_rank', 'lane_rank', 'lane_ask', 'lane_bid', 'max_rank'];

  function loadCore() {
    if (idx.ready) return Promise.resolve(true);
    return Promise.all([
      soft('items', '/api/items'),
      soft('catalog', '/lookup_items.json'),
      soft('hi', '/hi/index.json')
    ]).then(function (res) {
      var rows = res[0];
      rows = Array.isArray(rows) ? rows : (rows && Array.isArray(rows.items) ? rows.items : []);
      var cat = Array.isArray(res[1]) ? res[1] : [];
      idx.hi = (res[2] && res[2].items) || null;
      idx.degraded = !res[0] || !res[1];
      var map = Object.create(null);
      cat.forEach(function (c) {
        if (!c || !c.slug) return;
        map[c.slug] = { slug: c.slug, name: c.name || c.slug, icon: c.icon || null,
                        thumb: c.thumb || null, cat: '', sections: '', lanes: null };
      });
      rows.forEach(function (r) {
        if (!r || !r.slug) return;
        var it = map[r.slug] || (map[r.slug] = { slug: r.slug, icon: null, thumb: null });
        it.name = it.name || r.name || r.slug;
        it.cat = r.cat || it.cat || '';
        it.sections = r.sections || '';
        it.lanes = r.lanes || null;
        it.raw = r;
        PRICE_FIELDS.forEach(function (k) { it[k] = num(r[k]); });
        it.count = r.count == null ? 0 : Number(r.count);
      });
      idx.map = map;
      idx.byNorm = Object.create(null);
      idx.byLoose = Object.create(null);
      Object.keys(map).forEach(function (slug) {
        var it = map[slug];
        addKey(idx.byNorm, normKey(slug), it);
        addKey(idx.byNorm, normKey(it.name), it);
        addKey(idx.byLoose, looseKey(slug), it);
        addKey(idx.byLoose, looseKey(it.name), it);
      });
      idx.count = Object.keys(map).length;
      idx.ready = true;
      return true;
    });
  }
  function addKey(bag, k, it) { if (k && !bag[k]) bag[k] = it; }

  function resolve(key) {
    var s = String(key == null ? '' : key);
    if (!s.trim()) return null;
    return idx.byNorm[normKey(s)] || idx.byLoose[looseKey(s)] || idx.map[slugify(s)] || idx.map[s] || null;
  }
  /* Items the shared pages know about but the price snapshot does not carry (set rows from
     /api/feature/sets, masterable rows from /api/feature/collection) still open, market-only. */
  function syntheticFrom(key, data) {
    var s = normKey(key), loose = looseKey(key);
    var tt = (data.sets && data.sets.top_targets) || [];
    for (var i = 0; i < tt.length; i++) {
      var t = tt[i] || {};
      if (normKey(t.slug) === s || normKey(t.name) === s || looseKey(t.slug) === loose || looseKey(t.name) === loose) {
        return blank(t.slug || slugify(key), t.name || titleCase(key), 'prime set', null);
      }
    }
    var row = colRow(data.collection, key, key);
    if (row) return blank(row.slug || slugify(key), row.name || titleCase(key), row.cat || 'collection', row.icon || null);
    return null;
  }
  function blank(slug, name, cat, icon) {
    return { slug: slug, name: name, cat: cat, icon: icon, thumb: null, count: 0, equipped: 0,
             sections: '', lanes: null, synthetic: true };
  }

  /* ================= DOM (created once, reused) ================= */
  var root = null, panel = null, bodyBox = null, imgSlot = null, nameEl = null, slugEl = null,
      chipsEl = null, closeBtn = null, marketLink = null, zoomEl = null, zoomSlot = null,
      zoomCap = null, zoomOpenerEl = null;
  var state = { open: false, opener: null, zoom: false, item: null, token: 0,
                prevOverflow: '', locked: false, sec: { market: false, collection: false, adv: false } };

  function build() {
    if (root) return;
    root = el('div', 'dw-root dw-hidden');
    root.setAttribute('data-wfm-drawer', 'root');

    var scrim = el('div', 'dw-scrim');
    scrim.addEventListener('click', function () { close(); });
    root.appendChild(scrim);

    panel = el('section', 'dw-panel');
    panel.setAttribute('role', 'dialog');
    panel.setAttribute('aria-modal', 'true');
    panel.setAttribute('aria-labelledby', NAME_ID);
    panel.tabIndex = -1;

    var head = el('header', 'dw-head');
    imgSlot = el('div', 'dw-imgslot');
    head.appendChild(imgSlot);
    var titles = el('div', 'dw-titles');
    nameEl = el('h2', 'dw-name', '-');
    nameEl.id = NAME_ID;
    slugEl = el('div', 'dw-slug');
    chipsEl = el('div', 'dw-chips');
    titles.appendChild(nameEl);
    titles.appendChild(slugEl);
    titles.appendChild(chipsEl);
    head.appendChild(titles);
    closeBtn = el('button', 'dw-x', '\u2715');
    closeBtn.type = 'button';
    closeBtn.title = 'Close (Esc)';
    closeBtn.setAttribute('aria-label', 'Close details');
    closeBtn.addEventListener('click', function () { close(); });
    head.appendChild(closeBtn);
    panel.appendChild(head);

    bodyBox = el('div', 'dw-body');
    panel.appendChild(bodyBox);

    var foot = el('footer', 'dw-foot');
    marketLink = el('a', 'btn primary dw-market', 'Open on warframe.market \u2197');
    marketLink.target = '_blank';
    marketLink.rel = 'noopener noreferrer';
    foot.appendChild(marketLink);
    var closeBtn2 = el('button', 'btn', 'Close');
    closeBtn2.type = 'button';
    closeBtn2.addEventListener('click', function () { close(); });
    foot.appendChild(closeBtn2);
    panel.appendChild(foot);
    root.appendChild(panel);

    /* image zoom overlay - nested dialog, above the panel */
    zoomEl = el('div', 'dw-zoom dw-hidden');
    zoomEl.setAttribute('role', 'dialog');
    zoomEl.setAttribute('aria-modal', 'true');
    zoomEl.setAttribute('aria-label', 'Item image viewer');
    var zscrim = el('div', 'dw-zoom-scrim');
    zscrim.addEventListener('click', closeZoom);
    zoomEl.appendChild(zscrim);
    var zbox = el('div', 'dw-zoom-box');
    zoomSlot = el('div', 'dw-zoom-slot');
    zbox.appendChild(zoomSlot);
    zoomCap = el('div', 'dw-zoom-cap');
    zbox.appendChild(zoomCap);
    var zact = el('div', 'dw-zoom-actions');
    var zback = el('button', 'btn', 'Back to details');
    zback.type = 'button';
    zback.addEventListener('click', function () { closeZoom(); });
    var zclose = el('button', 'btn', 'Close image');
    zclose.type = 'button';
    zclose.addEventListener('click', function () { closeZoom(); });
    zact.appendChild(zback);
    zact.appendChild(zclose);
    zbox.appendChild(zact);
    zoomEl.appendChild(zbox);
    var zx = el('button', 'dw-x dw-zoom-x', '\u2715');
    zx.type = 'button';
    zx.title = 'Close (Esc)';
    zx.setAttribute('aria-label', 'Close image');
    zx.addEventListener('click', closeZoom);
    zoomEl.appendChild(zx);
    root.appendChild(zoomEl);

    document.body.appendChild(root);
  }

  /* ================= scroll lock ================= */
  function lockScroll(on) {
    if (on && !state.locked) {
      state.prevOverflow = document.body.style.overflow || '';
      document.body.style.overflow = 'hidden';
      state.locked = true;
    } else if (!on && state.locked) {
      document.body.style.overflow = state.prevOverflow;
      state.locked = false;
    }
  }

  /* ================= visuals ================= */
  function hiUrl(it) {
    if (!it || !idx.hi) return null;
    var rec = idx.hi[it.slug];
    if (!rec) return null;
    var file = (rec && rec.file) ? String(rec.file) : (it.slug + '.webp');
    if (!file || file.indexOf('..') !== -1 || BAD_URL.test(file)) return null;
    return HI_DIR + file.split('/').map(encodeURIComponent).join('/');
  }
  function avatar(it, big) {
    var d = el('div', big ? 'dw-avatar dw-avatar-big' : 'dw-avatar', initial(it && it.name, it && it.slug));
    d.setAttribute('aria-hidden', 'true');
    return d;
  }
  /* local hi-res art (this PC) > CDN icon > one downgrade to the thumb > letter tile */
  function art(it, big) {
    var local = hiUrl(it);
    var item = it || {};
    var main = local || (big ? (cdnUrl(item.icon) || cdnUrl(item.thumb)) : (cdnUrl(item.thumb) || cdnUrl(item.icon)));
    var alt = big ? cdnUrl(item.thumb) : cdnUrl(item.icon);
    if (!main) return avatar(item, big);
    var img = el('img', big ? 'dw-img' : 'dw-thumb');
    img.alt = item.name || item.slug || '';
    img.loading = 'eager';
    img.decoding = 'async';
    img.referrerPolicy = 'no-referrer';
    img.addEventListener('error', function () {
      if (alt && img.getAttribute('src') !== alt) { img.setAttribute('src', alt); return; }
      var av = avatar(item, big);
      if (img.parentNode) img.parentNode.replaceChild(av, img);
      var z = img.dwZoom;                                  // the letter tile inherits the zoom wiring
      if (z) zoomable(av, z.it, z.opener || null);
    });
    img.setAttribute('src', main);
    return img;
  }

  /* ================= zoom overlay ================= */
  function zoomCaption(it) {
    var bits = [];
    if (it) {
      var ranked = it.own_rank != null;
      if (ranked && it.lane_ask != null) bits.push('sell ' + fmt(it.lane_ask) + 'p at rank ' + it.own_rank);
      else if (!ranked && it.wts != null) bits.push('sell ' + fmt(it.wts) + 'p');
      if (ranked && it.lane_bid != null) bits.push('buyer offering ' + fmt(it.lane_bid) + 'p');
      else if (!ranked && it.wtb != null) bits.push('buyer offering ' + fmt(it.wtb) + 'p');
      if (it.count) bits.push('you own ' + it.count);
      if (it.slug) bits.push(it.slug);
    }
    return bits;
  }
  function openZoom(it, opener) {
    ensureRoot();
    zoomOpenerEl = opener || imgSlot.firstChild || null;
    clear(zoomSlot);
    var fresh = art(it, true);
    zoomSlot.appendChild(fresh);
    zoomable(fresh, it, zoomOpenerEl);
    clear(zoomCap);
    zoomCap.appendChild(el('div', 'dw-zoom-name', (it && (it.name || it.slug)) || 'Item image'));
    var bits = zoomCaption(it);
    if (bits.length) zoomCap.appendChild(el('div', 'dw-zoom-sub', bits.join(' \u00b7 ')));
    zoomEl.classList.remove('dw-hidden');
    state.zoom = true;
    var first = zoomEl.querySelector('.dw-zoom-actions .btn');
    if (first) first.focus(); else zoomEl.focus();
  }
  function closeZoom() {
    if (!state.zoom) return;
    state.zoom = false;
    zoomEl.classList.add('dw-hidden');
    var back = (zoomOpenerEl && document.contains(zoomOpenerEl)) ? zoomOpenerEl : closeBtn;
    if (back && document.contains(back)) back.focus();
    zoomOpenerEl = null;
  }
  /* make an image open the zoom overlay (mouse + keyboard); wiring is remembered on the
     element so the letter-tile fallback inherits it when the image fails to load */
  function zoomable(node, it, opener) {
    node.classList.add('dw-zoomable');
    node.title = 'Click to enlarge';
    node.tabIndex = 0;
    node.setAttribute('role', 'button');
    node.setAttribute('aria-label', 'Enlarge ' + ((it && (it.name || it.slug)) || 'item image'));
    node.dwZoom = { it: it, opener: opener || node };
    node.addEventListener('click', function (e) {
      if (e && e.stopPropagation) e.stopPropagation();
      openZoom(it, opener || node);
    });
    node.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        e.stopPropagation();
        openZoom(it, node);
      }
    });
    return node;
  }

  /* ================= a11y: focus trap ================= */
  var FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]),' +
                  ' textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
  function visibleIn(node) {
    for (var e = node; e && e !== document.body; e = e.parentElement) {
      if (!e.hasAttribute) continue;
      if (e.hasAttribute('hidden') || e.classList.contains('dw-hidden')) return false;
      var st = window.getComputedStyle(e);
      if (st.display === 'none' || st.visibility === 'hidden') return false;
    }
    return true;
  }
  function focusables(layer) {
    var all = layer.querySelectorAll(FOCUSABLE), out = [];
    for (var i = 0; i < all.length; i++) if (visibleIn(all[i])) out.push(all[i]);
    return out;
  }
  function layerNow() { return (state.zoom && !zoomEl.classList.contains('dw-hidden')) ? zoomEl : panel; }

  document.addEventListener('keydown', function (e) {
    if (!root || !state.open) return;
    if (e.key === 'Escape') {
      e.preventDefault();
      if (state.zoom) { closeZoom(); return; }
      close();
      return;
    }
    if (e.key !== 'Tab') return;
    var layer = layerNow();
    var f = focusables(layer);
    if (!f.length) { e.preventDefault(); layer.focus(); return; }
    var first = f[0], last = f[f.length - 1], active = document.activeElement;
    if (!layer.contains(active)) { e.preventDefault(); first.focus(); return; }
    if (e.shiftKey && active === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && active === last) { e.preventDefault(); first.focus(); }
  });

  /* ================= render pieces ================= */
  function stat(labelText, value, unit, cls, title) {
    var s = el('div', 'dw-ostat' + (cls ? ' ' + cls : ''));
    s.appendChild(el('span', 'dw-k', labelText));
    var v = el('div', 'dw-v', value);
    if (unit && value !== '-') { v.appendChild(document.createTextNode(' ')); v.appendChild(el('span', 'dw-u', unit)); }
    s.appendChild(v);
    if (title) s.title = title;
    return s;
  }
  function tile(labelText, value, unit, sub, cls, title) {
    var t = el('div', 'dw-tile' + (cls ? ' ' + cls : ''));
    t.appendChild(el('span', 'dw-k', labelText));
    var v = el('div', 'dw-v', value);
    if (unit && value !== '-') { v.appendChild(document.createTextNode(' ')); v.appendChild(el('span', 'dw-u', unit)); }
    t.appendChild(v);
    if (sub) t.appendChild(el('div', 'dw-sub', sub));
    if (title) t.title = title;
    return t;
  }
  function line(parent, cls, text) {
    if (text == null) return null;
    var d = el('div', cls, text);
    parent.appendChild(d);
    return d;
  }

  var ADV_TIP = {
    list: 'smart sell advisor: list the sellable copies now',
    burn_ducats: 'smart sell advisor: dissolve the surplus copies for ducats',
    open_relic: 'smart sell advisor: open the relic instead of selling it',
    assemble_set: 'smart sell advisor: assemble the complete set and sell it as one trade',
    finish_set: 'smart sell advisor: one or two parts short - finish the set, then sell it as one trade',
    already_listed: 'smart sell advisor: your copies are on the market already',
    keep: 'smart sell advisor: keep every copy (sets, crafting or one stays in the collection)',
    hold: 'smart sell advisor: nothing sellable left after reservations'
  };
  function actionHead(rec, qty, price) {
    var q = qty ? String(qty) + ' \u00d7' : '';
    var p = price != null ? fmtInt(price) + 'p' : '';
    switch (rec) {
      case 'list': return p ? ('List' + (q ? ' ' + q : '') + ' ' + p) : ('List' + (q ? ' ' + q : ' now'));
      case 'burn_ducats': return 'Burn' + (qty ? ' ' + qty : ' the surplus') + ' for ducats';
      case 'open_relic': return 'Open' + (qty ? ' ' + qty : ' it') + (qty === 1 ? ' relic' : ' relics');
      case 'assemble_set': return 'Assemble the set - one trade';
      case 'finish_set': return 'Finish the set - one trade';
      case 'already_listed': return 'Already listed - sit tight';
      case 'keep': return 'Keep - completes a set';
      case 'hold': return 'Hold - nothing safe to sell';
      default: return null;
    }
  }
  function setReason(reasons, rec) {
    for (var i = 0; i < reasons.length; i++) {
      var r = String(reasons[i] || '').toLowerCase();
      if (r.indexOf('set') !== -1 && r.indexOf('craft') !== -1) return reasons[i];
      if (rec === 'finish_set' && r.indexOf('set') !== -1) return reasons[i];
    }
    return null;
  }

  function renderLayer1(it, adv) {
    var box = el('div', 'dw-act');
    var owned = !!(it && it.count > 0);
    var head = null, why = [];
    if (!it) {
      head = 'Not in the local snapshot';
      why = ['Nothing found for this key — check the spelling.'];
      box.className = 'dw-act dw-act-unknown';
    } else if (owned && adv && adv.recommendation) {
      var rec = adv.recommendation;
      var price = num(adv.recommended_price);
      var qty = num(adv.recommended_quantity);
      if (rec === 'keep' && !setReason(adv.reasons || [], rec)) head = 'Keep - nothing safe to sell';
      if (rec === 'burn_ducats' && !qty) head = 'Burn the surplus for ducats';
      head = head || actionHead(rec, qty, price) || 'Hold - nothing safe to sell';
      why = (adv.reasons || []).slice(0, MAX_WHY);
      var tip = ADV_TIP[rec];
      if (tip) box.title = tip; else box.removeAttribute('title');
    } else if (owned) {
      head = 'You own ' + copies(it.count) + ' - no advisor call';
      why = ['The numbers below come from the local market snapshot; the advisor has no row for this item.'];
    } else {
      head = 'Not owned - market only';
      why = ['Not in your inventory snapshot — everything below is market data.'];
    }
    var hEl = el('div', 'dw-act-line');
    hEl.appendChild(document.createTextNode(head));
    box.appendChild(hEl);
    if (owned && adv && adv.sellable === 0) {
      box.appendChild(el('div', 'dw-act-sub', 'Nothing here is safe to list right now - every copy is equipped, reserved or earmarked.'));
    } else if (owned) {
      var safe = num(adv && adv.sellable);
      if (safe != null) box.appendChild(el('div', 'dw-act-sub', safe + ' of ' + it.count + ' ' + (it.count === 1 ? 'copy is' : 'copies are') + ' safe to sell.'));
    }
    if (why.length) {
      var wbox = el('div', 'dw-why');
      why.forEach(function (w) { line(wbox, 'dw-why-line', '\u00b7 ' + String(w)); });
      var rest = owned && adv && adv.reasons ? adv.reasons.length - why.length : 0;
      if (rest > 0) line(wbox, 'dw-why-line dw-dim', '\u00b7 ' + rest + ' more advisor reason' + (rest === 1 ? '' : 's') + ' - see Advanced');
      box.appendChild(wbox);
    }
    return box;
  }

  function renderOwned(it, adv) {
    var wrap = el('div', 'dw-owned');
    var equipped = it.equipped != null ? it.equipped : 0;
    var reserved = num(adv && adv.reserved);
    var safe = num(adv && adv.sellable);
    wrap.appendChild(stat('Owned', String(it.count || 0), it.count === 1 ? 'copy' : 'copies',
      it.count > 0 ? 'dw-hi' : 'dw-zero',
      it.countFromAdvisor
        ? 'copies the advisor found (the inventory snapshot had no stack for this item)'
        : 'copies in the last inventory snapshot taken on this PC'));
    wrap.appendChild(stat('Equipped', String(equipped), equipped === 1 ? 'copy' : 'copies',
      equipped > 0 ? '' : 'dw-zero',
      'copies slotted in a loadout - equipped copies are never sellable'));
    wrap.appendChild(stat('Reserved', reserved == null ? '-' : String(reserved),
      reserved === 1 ? 'copy' : 'copies',
      reserved == null ? 'dw-zero' : (reserved > 0 ? '' : 'dw-zero'),
      reserved == null
        ? 'reserved copies are unknown right now (advisor data unavailable)'
        : 'copies kept back for sets, crafting or a build - reserved copies are never listed'));
    wrap.appendChild(stat('Safe to sell', safe == null ? '-' : String(safe), safe === 1 ? 'copy' : 'copies',
      safe == null ? 'dw-zero' : (safe > 0 ? 'dw-hi' : 'dw-zero'),
      safe == null
        ? 'unknown right now (advisor data unavailable) - equipped copies are always excluded'
        : 'copies left once equipped and reserved copies are taken out - these are the ones you can list'));
    return wrap;
  }

  function renderMarket(it) {
    var wrap = el('div', 'dw-tiles');
    var ranked = it.own_rank != null;
    var hasLanes = !!it.lanes;
    var ask = ranked ? it.lane_ask : it.wts;
    var bid = ranked ? it.lane_bid : it.wtb;
    var sellSub;
    if (isNum(ask)) sellSub = 'list just under: ' + fmtInt(Math.max(1, Math.round(Number(ask)) - 1)) + 'p';
    else if (!ranked) sellSub = 'no sell orders right now';
    else sellSub = hasLanes ? 'no sell orders at your rank' : 'no rank data in this snapshot';
    wrap.appendChild(tile(ranked ? 'Sell price (your rank)' : 'Sell price', fmt(ask), isNum(ask) ? 'plat' : '',
      sellSub, isNum(ask) ? 'dw-hi' : 'dw-zero',
      (ranked
        ? 'lowest ask at rank ' + it.own_rank + ' - the cheapest sell order at the rank your copy is; list just under it to sell'
        : 'lowest ask - the cheapest sell order for this item, any rank') +
      ' (read from the local warframe.market snapshot)'));

    var bidSub = isNum(bid) ? 'quick-sell price'
      : (ranked && !hasLanes ? 'no rank data in this snapshot' : 'no standing buy orders');
    wrap.appendChild(tile('Buyer offering', fmt(bid), isNum(bid) ? 'plat' : '',
      bidSub, isNum(bid) ? '' : 'dw-zero',
      (ranked
        ? 'top bid at rank ' + it.own_rank + ' - the highest standing buy order at that rank; you quick-sell to it'
        : 'top bid - the highest standing buy order for this item, any rank') +
      ' (read from the local warframe.market snapshot)'));

    wrap.appendChild(tile('Typical price (context)', fmt(it.median), isNum(it.median) ? 'plat' : '',
      'all ranks, last 48h', isNum(it.median) ? '' : 'dw-zero',
      '48h median, all ranks \u2014 context only'));

    wrap.appendChild(tile('Sales / 48h', fmtInt(it.vol48), isNum(it.vol48) ? 'trades' : '',
      isNum(it.vol48) && Number(it.vol48) === 0 ? 'no sales in the last 48h' : 'all ranks, last 48h',
      isNum(it.vol48) && Number(it.vol48) > 0 ? '' : 'dw-zero',
      'number of trades completed in the last 48 hours, all ranks'));
    return wrap;
  }

  function renderEstimate(it) {
    var box = el('div', 'dw-est');
    var ranked = it.own_rank != null;
    var p = el('div');
    function t(s) { p.appendChild(document.createTextNode(s)); }
    function b(s) { p.appendChild(el('b', null, s)); }
    if (ranked) {
      var hasBid = isNum(it.lane_bid), hasAsk = isNum(it.lane_ask);
      t('Your rank-' + it.own_rank + ' copy: ');
      if (hasBid) { t('quick-sell to the top bid for '); b(fmt(it.lane_bid) + 'p'); }
      else t('no buy orders at this rank');
      if (hasAsk) {
        t(hasBid ? ' \u00b7 or list just under the lowest ask (' : ' - list just under the lowest ask (');
        b(fmt(it.lane_ask) + 'p');
        t(') = about ');
        b(fmtInt(Math.max(1, Math.round(Number(it.lane_ask)) - 1)) + 'p');
      } else if (hasBid) {
        t(' \u00b7 no sell orders at this rank');
      }
      t('.');
    } else if (!isNum(it.wts)) {
      t('No sell orders in the snapshot \u2014 no platinum estimate right now.');
    } else if (it.count > 0) {
      t('Estimated value: you own ');
      b(String(it.count));
      t(' \u00d7 ');
      b(fmt(it.wts) + 'p');
      t(' lowest ask = about ');
      b(fmtInt(it.count * Number(it.wts)) + ' platinum');
      t(' if every copy sells at today\u2019s lowest ask.');
    } else {
      t('You don\u2019t own this item. Its lowest ask is ');
      b(fmt(it.wts) + 'p');
      t(', so one copy would be worth about ');
      b(fmtInt(it.wts) + ' platinum');
      t('.');
    }
    box.appendChild(p);
    if (it.equipped) {
      line(box, 'dw-sub', it.equipped + ' cop' + (it.equipped === 1 ? 'y is' : 'ies are') +
        ' equipped in a loadout - equipped copies are never counted as sellable.');
    }
    var sub;
    if (ranked) {
      sub = 'All-rank context: 48h median ' + (isNum(it.median) ? fmt(it.median) + 'p' : '-') +
        ' \u00b7 volume ' + fmtInt(it.vol48) + ' trades. The median mixes every rank, so read it as context - not your copy\u2019s price.';
    } else if (isNum(it.median) && it.count > 0) {
      sub = 'At the 48h median (' + fmt(it.median) + 'p) the same ' + it.count + ' cop' + (it.count === 1 ? 'y' : 'ies') +
        ' would be \u2248 ' + fmtInt(it.count * Number(it.median)) + 'p' +
        (isNum(it.ducats) ? ' \u00b7 ' + (it.count * Number(it.ducats)) + ' ducats if dissolved instead' : '');
    } else if (isNum(it.ducats) && it.count > 0) {
      sub = it.count + ' \u00d7 ' + fmtInt(it.ducats) + ' ducats = ' + (it.count * Number(it.ducats)) + ' ducats if dissolved instead of sold';
    } else {
      sub = 'Prices come from the local warframe.market snapshot on this PC.';
    }
    line(box, 'dw-sub', sub);
    return box;
  }

  /* ---------- layer 3: expandables ---------- */
  function section(id, title, tooltip) {
    var sec = el('div', 'dw-sec');
    var head = el('button', 'dw-sec-head');
    head.type = 'button';
    head.id = 'wfmDwHead-' + id;
    head.setAttribute('aria-expanded', state.sec[id] ? 'true' : 'false');
    head.setAttribute('aria-controls', 'wfmDwSec-' + id);
    head.appendChild(el('span', null, title));
    head.appendChild(el('span', 'dw-caret', state.sec[id] ? '\u25be' : '\u25b8'));
    var body = el('div', 'dw-sec-body');
    body.id = 'wfmDwSec-' + id;
    body.setAttribute('role', 'region');
    body.setAttribute('aria-labelledby', 'wfmDwHead-' + id);
    if (!state.sec[id]) body.setAttribute('hidden', 'hidden');
    head.addEventListener('click', function () {
      var on = !state.sec[id];
      state.sec[id] = on;
      head.setAttribute('aria-expanded', on ? 'true' : 'false');
      clear(head.lastChild);
      head.lastChild.appendChild(document.createTextNode(on ? '\u25be' : '\u25b8'));
      if (on) body.removeAttribute('hidden'); else body.setAttribute('hidden', 'hidden');
    });
    if (tooltip) head.title = tooltip;
    sec.appendChild(head);
    sec.appendChild(body);
    return { box: sec, body: body };
  }

  function renderMarketDetails(it, rep) {
    var wrap = el('div');
    line(wrap, 'dw-note', 'Order book by rank - the cheapest sell order and the top buy order at each rank.');
    var lanes = it.lanes;
    var ranks = lanes ? Object.keys(lanes).map(Number).filter(function (n) { return isFinite(n); }) : [];
    ranks.sort(function (a, b) { return a - b; });
    if (it.own_rank != null && ranks.indexOf(Number(it.own_rank)) === -1) {
      ranks.push(Number(it.own_rank));
      ranks.sort(function (a, b) { return a - b; });
    }
    var maxR = it.max_rank != null ? it.max_rank : (ranks.length ? ranks[ranks.length - 1] : null);
    if (!ranks.length) {
      line(wrap, 'dw-note', 'No per-rank order book in the local snapshot for this item.');
    } else {
      var head = el('div', 'dw-lane dw-lane-head');
      head.title = 'ask = cheapest sell order at that rank (you buy from it, or list just under) \u00b7 ' +
        'bid = top buy order at that rank (you quick-sell to it, or bid just over). ' +
        'Ranks with no live orders are skipped.';
      head.appendChild(el('span', 'dw-lane-rk', 'Rank'));
      head.appendChild(el('span', 'dw-lane-ask', 'Cheapest sell order'));
      head.appendChild(el('span', 'dw-lane-bid', 'Top buy order'));
      wrap.appendChild(head);
      ranks.forEach(function (rk) {
        var cell = (lanes && lanes[String(rk)]) || {};
        var mine = it.own_rank != null && rk === Number(it.own_rank);
        var row = el('div', 'dw-lane' + (mine ? ' dw-mine' : ''));
        row.appendChild(el('span', 'dw-lane-rk', 'R' + rk + (maxR != null ? '/' + maxR : '')));
        if (mine) row.appendChild(el('span', 'dw-lane-you', 'your copy'));
        var a = el('span', 'dw-lane-ask', isNum(cell.ask) ? 'asks from ' + fmt(cell.ask) + 'p' : 'no asks');
        a.title = 'cheapest sell order at rank ' + rk +
          (isNum(cell.n_ask) ? ' (' + fmtInt(cell.n_ask) + ' listings)' : '') + ' - buy from it, or list just under';
        row.appendChild(a);
        var range = null;
        if (isNum(cell.bid)) {
          range = (isNum(cell.bid_low) && Number(cell.bid_low) !== Number(cell.bid))
            ? fmt(cell.bid_low) + '-' + fmt(cell.bid) + 'p' : fmt(cell.bid) + 'p';
        }
        var b = el('span', 'dw-lane-bid', range != null ? 'bids ' + range : 'no bids');
        b.title = 'buy orders at rank ' + rk +
          (isNum(cell.n_bid) ? ' (' + fmtInt(cell.n_bid) + ' bids)' : '') + ' - sell to the top bid, or bid just over';
        row.appendChild(b);
        if (mine) {
          if (isNum(cell.ask)) {
            var chip = el('span', 'dw-chip dw-chip-list', 'list ' + fmtInt(Math.max(1, Math.round(Number(cell.ask)) - 1)) + 'p \u2193');
            chip.title = 'undercut the cheapest rank-' + rk + ' ask by 1p';
            row.appendChild(chip);
          }
          if (isNum(cell.bid)) {
            var ob = el('span', 'dw-chip dw-chip-bid', 'bid ' + fmtInt(Math.round(Number(cell.bid)) + 1) + 'p \u2191');
            ob.title = 'outbid the top rank-' + rk + ' buy order by 1p';
            row.appendChild(ob);
          }
        }
        wrap.appendChild(row);
      });
    }
    var rr = repRow(rep, it.slug);
    if (rr) {
      var bits = [];
      if (isNum(rr.mn48) && isNum(rr.mx48)) bits.push('48h sales ranged ' + fmt(rr.mn48) + '-' + fmt(rr.mx48) + 'p');
      if (isNum(rr.n_sell)) bits.push(fmtInt(rr.n_sell) + ' live sell orders');
      if (isNum(rr.n_buy)) bits.push(fmtInt(rr.n_buy) + ' live buy orders');
      if (isNum(rr.est_days)) {
        var d = Number(rr.est_days);
        bits.push(d < 1 ? 'sells in under a day at this demand' : 'roughly ' + (d >= 10 ? Math.round(d) : +d.toFixed(1)) + ' days of supply at this demand');
      }
      if (bits.length) line(wrap, 'dw-note', bits.join(' \u00b7 ') + '.');
    }
    return wrap;
  }

  function renderCollection(it, col, sets) {
    var wrap = el('div');
    var found = false;
    var row = colRow(col, it.slug, it.name);
    if (row) {
      found = true;
      var cat = row.cat || '';
      var collected = !!(row.owned || row.mastered);
      line(wrap, null, 'Collection log: ' + (collected ? 'collected' : 'not collected') +
        (cat ? ' (' + cat + ')' : '') +
        (row.mastered ? ' \u00b7 mastered' : (row.owned ? ' \u00b7 owned in the save' : '')) +
        (isNum(row.mastery_req) && Number(row.mastery_req) > 0 ? ' \u00b7 mastery rank ' + fmtInt(row.mastery_req) + ' required' : '') + '.');
      if (isNum(row.floor)) {
        line(wrap, 'dw-note', 'Lowest sell order in the local snapshot: ' + fmt(row.floor) + 'p' +
          (row.floor_kind ? ' (' + label(row.floor_kind) + ')' : '') + '.');
      }
    } else if (col) {
      found = true;
      line(wrap, null, 'Collection log: this item is not tracked there (the log covers masterable items).');
    }
    var setLines = setsLines(it, sets);
    setLines.forEach(function (s) { wrap.appendChild(s); found = found || !!s; });
    if (sets && sets.summary) {
      var sm = sets.summary;
      line(wrap, 'dw-note', 'Set tracker: ' + fmtInt(sm.sets_total) + ' sets \u00b7 ' + fmtInt(sm.complete) + ' complete \u00b7 ' +
        fmtInt(sm.near_1_missing) + ' one part away.');
      found = true;
    }
    if (!found) line(wrap, 'dw-note', 'Collection and set data are unavailable right now.');
    return wrap;
  }
  function colRow(col, slug, name) {
    if (!col || !Array.isArray(col.categories)) return null;
    var target = looseKey(slug), targetName = looseKey(name);
    for (var i = 0; i < col.categories.length; i++) {
      var cat = col.categories[i] || {};
      var rows = cat.items || [];
      for (var j = 0; j < rows.length; j++) {
        var r = rows[j] || {};
        if (looseKey(r.slug) === target || (targetName && looseKey(r.name) === targetName)) {
          return { name: r.name, slug: r.slug, icon: r.icon || null, cat: cat.name || '',
                   owned: !!r.owned, mastered: !!r.mastered,
                   mastery_req: r.mastery_req, floor: r.floor, floor_kind: r.floor_kind };
        }
      }
    }
    return null;
  }
  function repRow(rep, slug) {
    if (!rep || !slug) return null;
    var pools = [rep.sell_now, rep.patient, rep.flips];
    for (var i = 0; i < pools.length; i++) {
      var rows = pools[i] || [];
      for (var j = 0; j < rows.length; j++) if (rows[j] && rows[j].slug === slug) return rows[j];
    }
    var junk = (rep.junk && rep.junk.rows) || [];
    for (var k = 0; k < junk.length; k++) if (junk[k] && junk[k].slug === slug) return junk[k];
    return null;
  }
  function setName(slug, sets, itName) {
    var tt = (sets && sets.top_targets) || [];
    for (var i = 0; i < tt.length; i++) if (tt[i] && tt[i].slug === slug) return tt[i].name || titleCase(slug);
    var inItems = idx.map[slug];
    if (inItems && inItems.name) return inItems.name;
    return titleCase(slug);
  }
  var SET_ACTION = { ASSEMBLE_SELL: 'assemble and sell as one trade', COMPLETE: 'complete it, then sell as one trade',
                     COMPLETE_MAYBE: 'probably worth completing', SELL_PARTS: 'sell the parts, skip the set',
                     WATCH: 'keep an eye on it', IGNORE: 'not worth chasing' };
  function setsLines(it, sets) {
    var out = [];
    if (!sets) return out;
    var tt = (sets.top_targets) || [];
    for (var i = 0; i < tt.length; i++) {
      if (tt[i] && tt[i].slug === it.slug) {
        var t = tt[i];
        var need = Array.isArray(t.need) ? t.need.map(function (n) {
          return typeof n === 'string' ? label(n) : label((n && (n.name || n.slug || n.part)) || '');
        }).filter(Boolean) : [];
        out.push(el('div', null, 'Set ' + (t.name || it.name) + ': ' + (t.parts || '?') + ' parts \u00b7 ' +
          (SET_ACTION[t.action] || label(t.action)) +
          (isNum(t.set_value) ? ' \u00b7 set value about ' + fmtInt(t.set_value) + 'p' : '') + '.'));
        if (need.length) out.push(el('div', 'dw-note', 'Still missing: ' + need.join(', ') + '.'));
        break;
      }
    }
    var cop = (sets.cash_out_parts) || [];
    for (var j = 0; j < cop.length; j++) {
      if (cop[j] && cop[j].part === it.slug) {
        out.push(el('div', null, 'Part of ' + setName(cop[j].set, sets) + ' - quoted at ' + fmt(cop[j].wts) + 'p' +
          (isNum(cop[j].vol48) ? ' \u00b7 ' + fmtInt(cop[j].vol48) + ' sold in 48h' : '') + '.'));
        break;
      }
    }
    return out;
  }

  function renderAdvanced(it, adv) {
    var table = el('table', 'dw-raw');
    var tb = el('tbody');
    function row(k, v) {
      var tr = el('tr');
      tr.appendChild(el('th', null, k));
      tr.appendChild(el('td', null, v == null || v === '' ? '-' : String(v)));
      tb.appendChild(tr);
    }
    row('slug', it.slug);
    row('cat', label(it.cat));
    row('tags', it.sections ? it.sections.split(',').map(label).join(', ') : '');
    row('own_rank', it.own_rank);
    row('lane_rank', it.lane_rank);
    row('lane_ask', it.lane_ask);
    row('lane_bid', it.lane_bid);
    row('max_rank', it.max_rank);
    row('wts', it.wts);
    row('wtb', it.wtb);
    row('median', it.median == null ? null : +Number(it.median).toFixed(2));
    row('avg48', it.avg48 == null ? null : +Number(it.avg48).toFixed(2));
    row('vol48', it.vol48);
    row('count', it.count);
    row('equipped', it.equipped);
    row('ducats', it.ducats);
    row('value', it.value);
    row('spread', it.spread);
    row('lanes', it.lanes ? Object.keys(it.lanes).length + ' rank rows' : '');
    if (adv) {
      row('advisor.recommendation', adv.recommendation);
      row('advisor.recommended_quantity', adv.recommended_quantity);
      row('advisor.recommended_price', adv.recommended_price);
      row('advisor.reserved', adv.reserved);
      row('advisor.sellable', adv.sellable);
      row('advisor.liquidity', adv.liquidity);
      row('advisor.best_sell_window', adv.best_sell_window);
      row('advisor.score', adv.score);
      row('advisor.reasons', (adv.reasons || []).join(' \u00b7 '));
    }
    table.appendChild(tb);
    var wrap = el('div');
    wrap.appendChild(el('div', 'dw-note',
      'Raw fields from the local warframe.market snapshot (and the advisor row when present). ' +
      'ask = cheapest sell order \u00b7 bid = top buy order \u00b7 lane_* = the rank you own \u00b7 ' +
      'median and vol48 cover every rank.'));
    wrap.appendChild(table);
    return wrap;
  }

  /* ================= panel render ================= */
  function setHeader(it, key, loading) {
    clear(imgSlot);
    var name = it ? it.name : titleCase(key);
    nameEl.textContent = name;
    clear(slugEl);
    if (it && it.slug) slugEl.textContent = it.slug;
    clear(chipsEl);
    if (it) {
      if (it.cat) chipsEl.appendChild(el('span', 'dw-chipk', label(it.cat)));
      var ranked = it.own_rank != null;
      if (ranked) {
        chipsEl.appendChild(el('span', 'dw-chipk',
          'R' + it.own_rank + (it.max_rank != null ? '/' + it.max_rank : '')));
      }
      if (it.count > 0) chipsEl.appendChild(el('span', 'dw-chipk dw-chipk-on', copies(it.count)));
      else chipsEl.appendChild(el('span', 'dw-chipk', 'not owned'));
      if (it.equipped > 0) chipsEl.appendChild(el('span', 'dw-chipk', it.equipped + ' equipped'));
    } else if (!loading) {
      chipsEl.appendChild(el('span', 'dw-chipk', 'no local record'));
    }
    var art0 = art(it || { slug: key, name: name }, true);
    imgSlot.appendChild(art0);
    if (it) zoomable(art0, it, null);
    else art0.setAttribute('aria-hidden', 'true');
    marketLink.href = MARKET + encodeURIComponent((it && it.slug) || slugify(key));
  }

  function renderMinimal(key) {
    var box = el('div');
    if (idx.degraded) {
      line(box, 'dw-note', 'The item catalogue or the local price snapshot could not be loaded from this server.');
      line(box, 'dw-note', 'Reload the page and try again - the drawer needs /api/items and /lookup_items.json.');
      return box;
    }
    line(box, 'dw-note', 'No market or inventory record for \u201c' + String(key) + '\u201d in the local snapshot.');
    line(box, 'dw-note', 'The link below opens it on warframe.market, where the full listing book lives.');
    return box;
  }

  /* ---- mini price graph + link to the full price page (item.js) ---- */
  var histCache = {};
  function itemHist(slug) {
    if (histCache[slug]) return histCache[slug];
    histCache[slug] = fetch('/api/feature/itemhist?slug=' + encodeURIComponent(slug))
      .then(function (r) { return r.json(); })
      .then(function (j) { return (j && j.points) ? j : { points: [] }; })
      .catch(function () { return { points: [] }; });
    return histCache[slug];
  }

  function renderPriceGraph(it) {
    var box = el('div', 'dw-graph');
    var head = el('div', 'dw-graph-head');
    head.appendChild(el('span', 'dw-graph-title', 'Price trend'));
    var link = document.createElement('a');
    link.className = 'dw-page-link';
    link.href = '/item.html?slug=' + encodeURIComponent(it.slug || '');
    link.textContent = 'Price page ▸';
    link.title = 'Full price history, your trades and the order book for this item';
    head.appendChild(link);
    box.appendChild(head);

    var wrap = el('div', 'dw-graph-wrap');
    var canvas = document.createElement('canvas');
    canvas.setAttribute('aria-label', 'Price trend for ' + (it.name || it.slug || 'this item'));
    wrap.appendChild(canvas);
    box.appendChild(wrap);
    var foot = el('div', 'dw-graph-foot', 'loading…');
    box.appendChild(foot);

    if (window.wfmChart) {
      var chart = wfmChart({ canvas: canvas, mini: true, key: 'mini:' + (it.slug || ''), height: 64, range: '7d', style: 'area' });
      itemHist(it.slug).then(function (j) {
        chart.setData(j.points || []);
        chart.setMarkers((j.sales || []).map(function (s) { return { ts: s[0], v: s[1] }; }));
        var n = (j.points || []).length;
        var info = chart.info();
        var span = info.span_s || 0;
        var spanTxt = span <= 0 ? '' : (span >= 86400 ? Math.round(span / 8640) / 10 + ' days' : Math.max(1, Math.round(span / 3600)) + 'h');
        foot.textContent = n
          ? n + ' points' + (spanTxt ? ' · ' + spanTxt : '') + (j.last ? ' · newest ' + new Date(j.last * 1000).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '')
          : 'no snapshots for this item yet';
      });
    } else {
      foot.textContent = 'graph unavailable';
    }
    return box;
  }

  function renderAll(key, data) {
    var it = data.item;
    setHeader(it, key);
    clear(bodyBox);
    try {
      if (!it) {
        bodyBox.appendChild(renderLayer1(null, null));
        bodyBox.appendChild(renderMinimal(key));
        return;
      }
      bodyBox.appendChild(renderLayer1(it, data.advisor));
      var hasMarket = it.count > 0 || isNum(it.wts) || isNum(it.wtb) ||
                      isNum(it.lane_ask) || isNum(it.lane_bid) || !!it.lanes;
      if (hasMarket) {
        bodyBox.appendChild(renderOwned(it, data.advisor));
        bodyBox.appendChild(renderMarket(it));
        bodyBox.appendChild(renderEstimate(it));
        if (it.slug) bodyBox.appendChild(renderPriceGraph(it));
      } else {
        line(bodyBox, 'dw-note', 'No price snapshot for this item — see what is known below.');
      }
      var secs = el('div');
      var m = section('market', 'Market details', 'the full per-rank order book plus live order counts');
      m.body.appendChild(renderMarketDetails(it, data.report));
      var c = section('collection', 'Collection & sets', 'collection-log status and which set this item feeds');
      c.body.appendChild(renderCollection(it, data.collection, data.sets));
      var a = section('adv', 'Advanced', 'raw snapshot fields, trader terms included');
      a.body.appendChild(renderAdvanced(it, data.advisor));
      secs.appendChild(m.box);
      secs.appendChild(c.box);
      secs.appendChild(a.box);
      bodyBox.appendChild(secs);
    } catch (err) {
      clear(bodyBox);
      line(bodyBox, 'dw-note', 'This item could not be fully rendered (' + ((err && err.message) || 'unknown error') + ').');
      bodyBox.appendChild(renderLayer1(it, null));
    }
  }

  /* ================= open / close ================= */
  function ensureRoot() {
    if (root) return;
    if (!document.body) return;
    build();
  }

  function open(key, opener) {
    if (!document.body) return;
    state.token++;
    var token = state.token;
    ensureRoot();
    if (!root) return;
    state.open = true;
    state.item = key;
    state.opener = opener || document.activeElement || null;
    var it = idx.ready ? resolve(key) : null;
    setHeader(it, key, true);                            // header paints straight away
    clear(bodyBox);
    line(bodyBox, 'dw-note', 'Loading item data\u2026');
    root.classList.remove('dw-hidden');
    lockScroll(true);
    if (closeBtn && closeBtn.focus) closeBtn.focus();    // focus moves into the dialog

    loadCore().then(function () {
      var item = resolve(key);
      return Promise.all([
        soft('advisor', '/api/feature/advisor'),
        soft('collection', '/api/feature/collection'),
        soft('sets', '/api/feature/sets'),
        soft('report', '/api/report')
      ]).then(function (res) {
        var data = { item: item, advisor: null, collection: res[1], sets: res[2], report: res[3] };
        data.item = item || syntheticFrom(key, data);
        data.advisor = advOf(res[0], data.item);
        data.item = withOwned(data.item, data.advisor);   // advisor knows the stack when the snapshot did not
        return data;
      });
    }).then(function (data) {
      if (token !== state.token || !state.open) return;    // a newer open (or a close) won
      renderAll(key, data);
    }).catch(function () {
      if (token !== state.token || !state.open) return;
      renderAll(key, { item: resolve(key), advisor: null, collection: null, sets: null, report: null });
    });
  }
  function advOf(bag, item) {
    if (!bag || !item || !bag.items) return null;
    return bag.items[item.slug] || null;
  }
  function withOwned(it, adv) {
    if (!it) return it;
    var owned = num(adv && adv.owned);
    if (!(it.count > 0) && owned != null && owned > 0) {
      var copy = {};
      for (var k in it) copy[k] = it[k];
      copy.count = owned;
      copy.countFromAdvisor = true;
      return copy;
    }
    return it;
  }

  function close() {
    if (!state.open) return;
    state.open = false;
    state.token++;
    if (state.zoom) closeZoom();
    if (root) root.classList.add('dw-hidden');
    lockScroll(false);
    var back = state.opener;
    state.opener = null;
    if (back && document.contains(back) && back.focus) back.focus();   // focus returns to the opener
  }

  open.close = close;
  open.isOpen = function () { return !!state.open; };
  open.preload = function () {
    loadCore();
    soft('advisor', '/api/feature/advisor');
    soft('collection', '/api/feature/collection');
    soft('sets', '/api/feature/sets');
    soft('report', '/api/report');
  };
  window.wfmOpenItem = open;
  window.wfmDrawer = { open: open, close: close, isOpen: open.isOpen };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', ensureRoot);
  } else {
    ensureRoot();
  }
})();
