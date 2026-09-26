/* item.js — the item price page: one item, its price graph as the main view, your trades and the book.
 *
 * Opened from anywhere as /item.html?slug=<slug> (the drawer's "Price page" button, the inventory
 * trend cell). Data: /api/items (snapshot row), /api/feature/itemhist?slug=<slug> (intraday points +
 * your sales), /api/trades (trade log), /api/feature/advisor (recommendation). The graph refreshes
 * itself every 60s and the sweep on the server adds points hourly.
 */
'use strict';
(function () {
  var qs = new URLSearchParams(location.search);
  var SLUG = (qs.get('slug') || '').trim();
  var REFRESH_MS = 60000;
  var chart = null, timer = null, row = null, series = null, trades = null, adv = null;

  var $ = function (id) { return document.getElementById(id); };
  var esc = function (s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  };
  var isNum = function (v) { return v !== null && v !== undefined && v !== '' && !isNaN(Number(v)); };
  var fmt = function (v) { return isNum(v) ? Number(v).toLocaleString('en-AU') : '—'; };
  var plat = function (v) {
    if (!isNum(v)) return '—';
    var n = Number(v);
    /* medians and averages come back fractional - a tenth is plenty on a price tag */
    return (n >= 100 ? fmt(Math.round(n)) : (Math.round(n * 10) / 10).toLocaleString('en-AU')) + 'p';
  };
  function when(ts) {
    if (!ts) return '—';
    var d = new Date(Number(ts) * 1000);
    return d.toLocaleDateString([], { month: 'short', day: 'numeric' }) + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }
  function show(id, on) { var n = $(id); if (n) n.classList.toggle('hidden', !on); }

  function chips(list, mount) {
    mount.innerHTML = list.map(function (c) {
      return '<span class="ip-chip' + (c.hi ? ' hi' : '') + '" title="' + esc(c.tip || '') + '">' + c.label + '</span>';
    }).join('');
  }

  function table(cols, rows) {
    if (!rows.length) return '<div class="ip-note">Nothing recorded.</div>';
    var head = '<tr>' + cols.map(function (c) {
      return '<th' + (c.num ? ' class="num"' : '') + '>' + esc(c.label) + '</th>';
    }).join('') + '</tr>';
    var body = rows.map(function (r) {
      return '<tr>' + cols.map(function (c) {
        return '<td' + (c.num ? ' class="num"' : '') + '>' + (c.html ? c.html(r) : esc(c.get(r))) + '</td>';
      }).join('') + '</tr>';
    }).join('');
    return '<table class="ip-table"><thead>' + head + '</thead><tbody>' + body + '</tbody></table>';
  }

  /* ---------- header ---------- */
  function head() {
    var name = (row && row.name) || (series && series.name) || SLUG || 'Item price';
    var t = $('ipTitle');
    /* only a full URL is safe to load here - the catalogue also carries relative
       warframe.market image paths that this local server does not serve */
    var icon = row && row.icon && /^https?:/i.test(row.icon) ? row.icon : '';
    t.innerHTML = (icon ? '<img src="' + esc(icon) + '" alt="">' : '') + '<span>' + esc(name) + '</span>';
    document.title = 'WFM Trader · ' + name;
    var a = adv || {};
    var bits = [
      a.recommendation ? 'Advisor: <b>' + esc(String(a.recommendation).replace(/_/g, ' ')) + '</b>' : null,
      isNum(a.recommended_price) ? 'list at <b>' + plat(a.recommended_price) + '</b>' : null,
      SLUG ? 'slug <b>' + esc(SLUG) + '</b>' : null,
    ].filter(Boolean);
    $('ipLead').innerHTML = bits.length ? bits.join(' · ') : 'Local snapshot and price history for this item.';
  }

  /* ---------- cards ---------- */
  function renderChips() {
    var a = adv || {};
    var eq = row ? (row.equipped || 0) : 0;
    var safe = isNum(a.sellable) ? a.sellable : (row ? (row.count || 0) : 0);
    var list = [
      { label: 'Owned <b>' + fmt(row ? row.count : null) + '</b>', tip: 'copies in your last inventory snapshot' },
      { label: 'Equipped <b>' + fmt(eq) + '</b>', tip: 'copies slotted in a loadout - never listed' },
      { label: 'Safe <b>' + fmt(safe) + '</b>', hi: safe > 0, tip: 'copies that can actually be listed' },
      { label: 'Sell <b>' + plat(row && row.lane_rank != null ? row.lane_ask : (row ? row.wts : null)) + '</b>', hi: true,
        tip: row && row.lane_rank != null ? 'lowest ask at your rank ' + row.lane_rank : 'lowest ask, any rank' },
      { label: 'Buy <b>' + plat(row && row.lane_rank != null ? row.lane_bid : (row ? row.wtb : null)) + '</b>', tip: 'top buy order' },
      { label: 'Median 48h <b>' + plat(row ? row.median : null) + '</b>', tip: 'median of the last two days of sell orders' },
      { label: 'Vol 48h <b>' + fmt(row ? row.vol48 : null) + '</b>', tip: 'orders seen in the last 48h' },
      { label: 'Ducats <b>' + fmt(row ? row.ducats : null) + '</b>', tip: 'ducat value when sold to a relay trader' },
    ].filter(function (c) { return c.label.indexOf('undefined') === -1; });
    chips(list, $('ipChips'));
  }

  function renderStats() {
    var r = row || {}, a = adv || {};
    var rows = [
      { k: 'Sell price (snapshot)', v: plat(r.lane_rank != null ? r.lane_ask : r.wts), why: r.lane_rank != null ? 'rank ' + r.lane_rank + ' lane' : 'any rank' },
      { k: 'Buy price (snapshot)', v: plat(r.lane_rank != null ? r.lane_bid : r.wtb), why: 'top buy order' },
      { k: 'Spread', v: plat(r.spread), why: 'sell minus buy - thin lines mean quick fills' },
      { k: 'Median 48h', v: plat(r.median), why: 'middle sell order' },
      { k: 'Average 48h', v: plat(r.avg48), why: 'mean sell order' },
      { k: 'Volume 48h', v: fmt(r.vol48), why: 'orders seen' },
      { k: 'Your value', v: plat(r.value), why: 'safe copies x sell price' },
      { k: 'Advisor', v: a.recommendation ? String(a.recommendation).replace(/_/g, ' ') : '—',
        why: (a.reasons || []).slice(0, 2).join('; ') || 'no advisor row', wrap: true },
    ];
    $('ipStats').innerHTML = '<table class="ip-table"><tbody>' + rows.map(function (x) {
      return '<tr><td>' + esc(x.k) + '</td><td class="num"><b>' + esc(x.v) + '</b></td>' +
        '<td class="ip-kind' + (x.wrap ? ' wrap' : '') + '" title="' + esc(x.why) + '">' + esc(x.why) + '</td></tr>';
    }).join('') + '</tbody></table>';
  }

  function renderTrades() {
    var ev = (trades && trades.events) || [];
    var names = {};
    if (row && row.name) names[row.name.toLowerCase()] = true;
    if (series && series.name) names[series.name.toLowerCase()] = true;
    var mine = ev.filter(function (e) {
      if (!e || !e.name) return false;
      if (e.slug && SLUG && e.slug === SLUG) return true;
      return !!names[String(e.name).toLowerCase()];
    }).sort(function (a, b) { return (b.ts || 0) - (a.ts || 0); });
    $('ipTradesCount').textContent = mine.length + (mine.length === 1 ? ' event' : ' events');
    show('ipTradesCard', true);
    $('ipTrades').innerHTML = table([
      { label: 'When', get: function (e) { return when(e.ts); } },
      { label: 'What', get: function (e) { return String(e.kind || '').replace(/_/g, ' '); } },
      { label: 'Qty', num: true, get: function (e) { return isNum(e.qty) ? fmt(e.qty) : '—'; } },
      { label: 'Plat', num: true, get: function (e) { return plat(e.total != null ? e.total : e.plat); } },
      { label: 'Note', get: function (e) { return e.note || ''; } },
    ], mine.slice(0, 60));
  }

  function renderMeta() {
    var s = series || {}, pts = (s.points || []).length;
    var span = pts > 1 ? (s.points[pts - 1][0] - s.points[0][0]) : 0;
    var days = Math.round(span / 86400 * 10) / 10;
    var src = s.salesOnly ? 'your own sales' : ((s.src && s.src.ask) === 'history' ? 'daily history backfill' : 'market snapshot');
    $('ipMeta').textContent = pts
      ? pts + ' points spanning ' + (span >= 86400 ? days + ' days' : Math.max(1, Math.round(span / 3600)) + ' hours') + ' · ' + src +
        ' · newest ' + when(s.last)
      : 'no points yet';
    $('ipHint').innerHTML = series && series.auto ? 'auto 60s' : '';
  }

  /* ---------- data ---------- */
  function get(url) { return fetch(url).then(function (r) { return r.json(); }); }

  function loadSeries() {
    return get('/api/feature/itemhist?slug=' + encodeURIComponent(SLUG)).then(function (j) {
      series = j && j.points ? j : { points: [] };
      var pts = (series.points || []).filter(function (p) { return p && p[0] != null && p[1] != null; });
      /* an item with sales but no price snapshots yet still gets a graph: your own fills */
      if (pts.length < 2) {
        var mine = (series.sales || []).filter(function (s) { return s && s[0] != null && s[1] != null; });
        if (mine.length >= 2) { pts = mine.map(function (s) { return [s[0], s[1], null]; }); series.salesOnly = true; }
      }
      var marks = (series.sales || []).map(function (s) { return { ts: s[0], v: s[1] }; });
      if (chart) {
        chart.setData(pts);
        chart.setMarkers(marks);
      }
      renderMeta();
    }).catch(function () {
      series = { points: [] };
      renderMeta();
    });
  }

  function draw() {
    if (!chart) return;
    chart.redraw();
    if (timer) clearInterval(timer);
    timer = setInterval(function () {
      loadSeries().then(function () { renderMeta(); });
    }, REFRESH_MS);
    loadSeries();
  }

  /* ---------- page ---------- */
  function boot(slug) {
    if (!slug) return pick();
    show('ipChartCard', true);
    var c = $('ipChart');
    chart = wfmChart({
      canvas: c, tip: '#ipTip', valueKey: 'ask', key: 'item:' + slug,
      range: '7d', style: 'area', palette: 'accent', height: 320,
    });
    chart.buildControls($('ipViews'));
    $('ipChartCard').querySelector('.card-title').textContent = 'Price history';

    return Promise.all([
      get('/api/items').catch(function () { return { items: [] }; }),
      get('/api/feature/advisor').catch(function () { return null; }),
      get('/api/trades').catch(function () { return null; }),
      get('/api/summary').catch(function () { return null; }),
      get('/api/catalog').catch(function () { return null; }),
    ]).then(function (res) {
      var items = Array.isArray(res[0]) ? res[0] : ((res[0] && res[0].items) || []);
      row = items.filter(function (r) { return r.slug === slug; })[0] || null;
      var advAll = (res[1] && (res[1].items || res[1].recommendations || res[1])) || {};
      adv = null;
      if (Array.isArray(advAll)) adv = advAll.filter(function (a) { return a && a.slug === slug; })[0] || null;
      else if (advAll && advAll[slug]) adv = advAll[slug];
      trades = res[2];
      if (res[3] && res[3].plat != null) {
        var ch = $('chips');
        if (ch) ch.innerHTML = '<span class="ip-chip hi">' + esc(fmt(res[3].plat)) + 'p</span>' +
          (res[3].items != null ? '<span class="ip-chip">' + esc(fmt(res[3].items)) + ' items</span>' : '');
      }
      if (res[4] && row) {
        var cat = (res[4] || []).filter(function (c) { return c.slug === slug; })[0];
        if (cat && cat.icon) row.icon = cat.icon;
      }
      head();
      renderChips();
      renderStats();
      renderTrades();
      show('ipStatsCard', true);
      draw();
    }).catch(function (err) {
      $('ipMeta').textContent = 'could not load this item (' + ((err && err.message) || 'error') + ')';
    });
  }

  function pick() {
    show('ipPickCard', true);
    get('/api/catalog').then(function (cat) {
      var list = (cat || []).slice();
      var box = $('ipList'), input = $('ipPick');
      function paint(q) {
        q = (q || '').toLowerCase();
        var hits = list.filter(function (c) { return !q || String(c.name || '').toLowerCase().indexOf(q) !== -1; }).slice(0, 60);
        box.innerHTML = hits.map(function (c) {
          return '<a href="/item.html?slug=' + encodeURIComponent(c.slug) + '">' + esc(c.name) + '</a>';
        }).join('') || '<span class="dim">no matches</span>';
      }
      paint('');
      input.addEventListener('input', function () { paint(input.value); });
      input.focus();
    }).catch(function () { $('ipList').innerHTML = '<span class="dim">catalogue unavailable</span>'; });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function () { boot(SLUG); });
  else boot(SLUG);
})();
