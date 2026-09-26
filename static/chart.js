/* chart.js — the dashboard's single graph renderer.
 *
 * One factory draws every graph: the platinum balance chart on Home, the per-item price graph on
 * the item page, and the mini graph inside the item drawer. Views are switchable — time range,
 * chart style (area / line / bars / steps) and line colour — and the choice is remembered per
 * chart key in localStorage.
 *
 *   window.wfmChart({ canvas, tip, height, valueKey, key, mini, labels, pads, range, style, palette })
 *     .setData(points)        [{ts, plat|ask, bid}] or [[ts, v]] / [[ts, ask, bid]]
 *     .setMarkers(list)       [{ts, v, label}]  — your own trades, drawn as dots
 *     .setRange('1h'|'6h'|'24h'|'7d'|'30d'|'all') .setStyle(...) .setPalette(...)
 *     .buildControls(mount, { ranges:false })   range / style / colour buttons into `mount`
 *     .redraw() .info()
 *
 * window.PlatChart is the platinum chart on Home, built from the same factory (kept for app.js).
 */
'use strict';
(function () {
  var LS_KEY = 'wfm_chart_v1';
  var RANGES = [['1h', 3600], ['6h', 21600], ['24h', 86400], ['7d', 604800], ['30d', 2592000], ['all', 0]];
  var STYLES = [['area', 'Area'], ['line', 'Line'], ['bars', 'Bars'], ['steps', 'Steps']];
  var PALETTES = [['accent', 'Accent'], ['green', 'Green'], ['blue', 'Blue'], ['violet', 'Violet'], ['amber', 'Amber']];
  var HEX = { green: '#3ddc97', blue: '#58a6ff', violet: '#b47cff', amber: '#ffb454' };

  var cssVar = function (n) { return getComputedStyle(document.documentElement).getPropertyValue(n).trim(); };
  var fmtNum = function (v) { return Math.round(v).toLocaleString('en-AU'); };
  var pad2 = function (n) { return (n < 10 ? '0' : '') + n; };
  var clamp = function (v, a, b) { return Math.max(a, Math.min(b, v)); };

  function hexA(hex, a) {
    var h = (hex || '#ff8a1e').replace('#', '');
    var n = h.length === 3 ? h.split('').map(function (c) { return c + c; }).join('') : h;
    return 'rgba(' + parseInt(n.slice(0, 2), 16) + ',' + parseInt(n.slice(2, 4), 16) + ',' + parseInt(n.slice(4, 6), 16) + ',' + a + ')';
  }

  /* axis labels: fine ticks on short spans, months (with the year) on long ones */
  function tickLabel(ts, spanS) {
    var d = new Date(ts * 1000);
    if (spanS <= 3 * 86400) return pad2(d.getHours()) + ':' + pad2(d.getMinutes());
    if (spanS <= 120 * 86400) return d.toLocaleDateString([], { month: 'short', day: 'numeric' });
    return d.toLocaleDateString([], { month: 'short' }) + " '" + String(d.getFullYear()).slice(2);
  }
  function fullLabel(ts, spanS) {
    var d = new Date(ts * 1000);
    var day = d.toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' });
    return spanS <= 3 * 86400 ? day + ' ' + pad2(d.getHours()) + ':' + pad2(d.getMinutes()) : day;
  }
  /* a round gridline step so the y labels read as nice numbers */
  function niceStep(raw) {
    var mag = Math.pow(10, Math.floor(Math.log10(Math.max(raw, 1))));
    var n = raw / mag;
    var m = n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10;
    return m * mag;
  }

  function prefStore(key, defaults) {
    var all = {};
    try { all = JSON.parse(localStorage.getItem(LS_KEY) || '{}') || {}; } catch (e) { all = {}; }
    var p = (key && all[key]) || {};
    if (!p.style) p.style = defaults.style;
    if (!p.palette) p.palette = defaults.palette;
    if (!p.range) p.range = defaults.range;
    return {
      get: function () { return p; },
      save: function () { try { all[key] = p; localStorage.setItem(LS_KEY, JSON.stringify(all)); } catch (e) {} },
    };
  }

  /* The view controls (range / style / colour) are rendered by JS so every page that loads a chart
     gets them, and they carry their own styles - nothing to add to the page CSS files. */
  var CSS = [
    '.chartbtnrow { display: flex; flex-wrap: wrap; gap: 4px; align-items: center; margin-left: auto; }',
    '.chartbtnrow + .chartbtnrow { margin-left: 8px; }',
    '.chartbtn { background: var(--panel2, #1a1e26); border: 1px solid var(--border, #232833); color: var(--muted, #8b93a4);',
    '  font: 600 10.5px var(--sans, sans-serif); padding: 2px 8px; border-radius: 999px; cursor: pointer; line-height: 1.7; }',
    '.chartbtn:hover { color: var(--text, #e6e9ef); border-color: var(--accent-dim, #7a4a12); }',
    '.chartbtn:focus-visible { outline: 2px solid var(--accent, #ff8a1e); outline-offset: 1px; }',
    '.chartbtn[aria-pressed="true"] { color: var(--text, #e6e9ef); border-color: var(--accent, #ff8a1e); background: var(--hover, #222833); }',
    '.chartbtn.dot { width: 14px; height: 14px; padding: 0; border-radius: 50%; background: var(--dot, var(--accent, #ff8a1e)); border-color: transparent; }',
    '.chartbtn.dot[aria-pressed="true"] { box-shadow: 0 0 0 2px var(--accent, #ff8a1e); }',
    '.chartviews { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }',
  ].join('\n');
  function injectCss() {
    if (document.getElementById('chartCss')) return;
    var s = document.createElement('style');
    s.id = 'chartCss';
    s.textContent = CSS;
    (document.head || document.documentElement).appendChild(s);
  }

  var registry = [];
  function wfmChart(opts) {
    opts = opts || {};
    var canvas = opts.canvas;
    var noop = {
      setData: function () {}, setMarkers: function () {}, setRange: function () {}, setStyle: function () {},
      setPalette: function () {}, buildControls: function () {}, redraw: function () {}, info: function () { return { ok: false }; },
    };
    if (!canvas || !canvas.getContext) return noop;
    var ctx = canvas.getContext('2d');
    var key = opts.key || 'chart';
    var valueKey = opts.valueKey || 'plat';
    var mini = !!opts.mini;
    var labels = opts.labels !== false && !mini;
    var PAD = opts.pads || (mini ? { l: 4, r: 4, t: 4, b: 4 } : { l: 58, r: 16, t: 16, b: 30 });
    var pref = prefStore(key, { style: opts.style || 'area', palette: opts.palette || 'accent', range: opts.range || 'all' });
    var tip = opts.tip ? (typeof opts.tip === 'string' ? document.querySelector(opts.tip) : opts.tip) : null;
    var pts = [], marks = [], hover = -1, view = null;

    function colour() { return HEX[pref.get().palette] || cssVar('--accent') || '#ff8a1e'; }
    function spanOf(list) { return list.length < 2 ? 0 : list[list.length - 1].ts - list[0].ts; }
    function filtered() {
      var p = pref.get();
      if (!pts.length || p.range === 'all') return pts;
      var span = 0;
      for (var i = 0; i < RANGES.length; i++) if (RANGES[i][0] === p.range) span = RANGES[i][1];
      if (!span) return pts;
      var t1 = pts[pts.length - 1].ts;
      var out = pts.filter(function (q) { return q.ts >= t1 - span; });
      return out.length > 1 ? out : pts.slice(-2);
    }
    function sizeCanvas() {
      var dpr = window.devicePixelRatio || 1;
      var wrap = canvas.parentElement;
      var w = Math.max(80, (wrap ? wrap.clientWidth : canvas.clientWidth) || 320);
      var h = Math.max(56, opts.height || (wrap ? wrap.clientHeight : 0) || 200);
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
      canvas.style.width = w + 'px';
      canvas.style.height = h + 'px';
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      return { w: w, h: h };
    }
    function scales(ps, w, h) {
      var xs = ps.map(function (q) { return q.ts; });
      var x0 = Math.min.apply(null, xs), x1 = Math.max.apply(null, xs);
      if (x1 === x0) { x0 -= 3600; x1 += 3600; }
      var ys = ps.map(function (q) { return q.v; });
      var y0 = Math.min.apply(null, ys), y1 = Math.max.apply(null, ys);
      if (y1 === y0) { y0 -= 5; y1 += 5; }
      var padY = Math.max((y1 - y0) * 0.15, 2);
      y0 = Math.max(0, y0 - padY); y1 += padY;                 /* platinum and prices never go below zero */
      return {
        X: function (t) { return PAD.l + (t - x0) / (x1 - x0) * (w - PAD.l - PAD.r); },
        Y: function (v) { return h - PAD.b - (v - y0) / (y1 - y0) * (h - PAD.t - PAD.b); },
        x0: x0, x1: x1, y0: y0, y1: y1,
      };
    }
    /* monotone cubic (Fritsch-Carlson) — no fake dips on stepped data */
    function buildSegs(ps, X, Y) {
      var n = ps.length;
      var px = ps.map(function (q) { return X(q.ts); }), py = ps.map(function (q) { return Y(q.v); });
      if (n < 2) return { px: px, py: py, segs: [] };
      var dx = [], dy = [], m = [];
      for (var i = 0; i < n - 1; i++) { dx[i] = px[i + 1] - px[i]; dy[i] = py[i + 1] - py[i]; }
      m[0] = dy[0] / dx[0];
      for (i = 1; i < n - 1; i++) {
        var a = dy[i - 1] / dx[i - 1], b = dy[i] / dx[i];
        m[i] = (a * b <= 0) ? 0 : (a + b) / 2;
      }
      m[n - 1] = dy[n - 2] / dx[n - 2];
      for (i = 0; i < n - 1; i++) {
        if (dy[i] === 0) { m[i] = 0; m[i + 1] = 0; continue; }
        var s = m[i] / (dy[i] / dx[i]), t = m[i + 1] / (dy[i] / dx[i]);
        var q = s * s + t * t;
        if (q > 9) { var f = 3 / Math.sqrt(q); m[i] = f * s * (dy[i] / dx[i]); m[i + 1] = f * t * (dy[i] / dx[i]); }
      }
      var segs = [];
      for (i = 0; i < n - 1; i++) {
        segs.push({
          c1x: px[i] + dx[i] / 3, c1y: py[i] + m[i] * dx[i] / 3,
          c2x: px[i + 1] - dx[i] / 3, c2y: py[i + 1] - m[i + 1] * dx[i] / 3,
          x: px[i + 1], y: py[i + 1],
        });
      }
      return { px: px, py: py, segs: segs };
    }
    function path(c, g, style) {
      c.beginPath();
      c.moveTo(g.px[0], g.py[0]);
      if (style === 'steps') {
        for (var i = 1; i < g.px.length; i++) { c.lineTo(g.px[i], g.py[i - 1]); c.lineTo(g.px[i], g.py[i]); }
      } else {
        for (var j = 0; j < g.segs.length; j++) { var s = g.segs[j]; c.bezierCurveTo(s.c1x, s.c1y, s.c2x, s.c2y, s.x, s.y); }
      }
    }

    function draw() {
      var ps = filtered();
      var dim = sizeCanvas(), w = dim.w, h = dim.h;
      var col = colour(), muted = cssVar('--muted') || '#8b93a4', border = cssVar('--border') || '#232833';
      ctx.clearRect(0, 0, w, h);
      if (!ps.length) {
        hover = -1;
        if (tip) { tip.classList.add('hidden'); tip.textContent = ''; }
        if (labels) {
          ctx.fillStyle = muted;
          ctx.font = '12px ' + (cssVar('--sans') || 'sans-serif');
          ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
          ctx.fillText('No snapshots yet.', w / 2, h / 2);
        }
        view = null;
        return;
      }
      var span = spanOf(ps);
      var S = scales(ps, w, h);
      var style = pref.get().style;

      /* y gridlines + round labels */
      if (labels) {
        var step = niceStep((S.y1 - S.y0) / 4);
        ctx.font = '10.5px ' + (cssVar('--sans') || 'sans-serif');
        ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
        for (var v = Math.ceil(S.y0 / step) * step; v <= S.y1; v += step) {
          var gy = S.Y(v);
          ctx.strokeStyle = border; ctx.globalAlpha = 0.55;
          ctx.beginPath(); ctx.moveTo(PAD.l, gy); ctx.lineTo(w - PAD.r, gy); ctx.stroke();
          ctx.globalAlpha = 1;
          ctx.fillStyle = muted;
          ctx.fillText(fmtNum(v) + 'p', PAD.l - 7, gy);
        }
      }

      /* x ticks — density scales with width and span (finer on short ranges) */
      if (labels) {
        var nT = clamp(Math.round((w - PAD.l - PAD.r) / 95), 3, 12);
        var lastLbl = '';
        ctx.font = '10.5px ' + (cssVar('--sans') || 'sans-serif');
        ctx.textBaseline = 'top';
        for (var i = 0; i < nT; i++) {
          var t = S.x0 + (S.x1 - S.x0) * (i / (nT - 1));
          var lbl = tickLabel(t, span);
          if (lbl === lastLbl) continue;
          lastLbl = lbl;
          var x = S.X(t);
          ctx.strokeStyle = border; ctx.globalAlpha = 0.4;
          ctx.beginPath(); ctx.moveTo(x, h - PAD.b); ctx.lineTo(x, h - PAD.b + 3); ctx.stroke();
          ctx.globalAlpha = 1;
          ctx.fillStyle = muted;
          /* the end ticks sit ON the plot edge — anchor them inward so they cannot clip */
          ctx.textAlign = i === 0 ? 'left' : (i === nT - 1 ? 'right' : 'center');
          ctx.fillText(lbl, x, h - PAD.b + 7);
        }
      }

      var g = buildSegs(ps, S.X, S.Y);
      if (style === 'bars') {
        var bw = Math.max(1, Math.min(9, (w - PAD.l - PAD.r) / Math.max(ps.length, 1) * 0.7));
        for (var b = 0; b < ps.length; b++) {
          var by = S.Y(ps[b].v);
          ctx.fillStyle = hexA(col, b === hover ? 0.95 : 0.6);
          ctx.fillRect(S.X(ps[b].ts) - bw / 2, by, bw, h - PAD.b - by);
        }
      } else if (g.segs.length) {
        if (style === 'area') {
          var grad = ctx.createLinearGradient(0, PAD.t, 0, h - PAD.b);
          grad.addColorStop(0, hexA(col, 0.30));
          grad.addColorStop(1, hexA(col, 0.02));
          path(ctx, g, style);
          ctx.lineTo(g.px[g.px.length - 1], h - PAD.b);
          ctx.lineTo(g.px[0], h - PAD.b);
          ctx.closePath();
          ctx.fillStyle = grad;
          ctx.fill();
        }
        path(ctx, g, style);
        ctx.save();
        ctx.strokeStyle = col; ctx.lineWidth = mini ? 1.6 : 2; ctx.lineJoin = 'round'; ctx.lineCap = 'round';
        if (!mini) { ctx.shadowColor = hexA(col, 0.5); ctx.shadowBlur = 9; }
        ctx.stroke();
        ctx.restore();
      }

      /* your own trades as dots */
      for (var k = 0; k < marks.length; k++) {
        var mk = marks[k];
        if (mk.ts < S.x0 || mk.ts > S.x1) continue;
        ctx.beginPath();
        ctx.arc(S.X(mk.ts), S.Y(mk.v), 3, 0, Math.PI * 2);
        ctx.fillStyle = col; ctx.fill();
        ctx.lineWidth = 1.2; ctx.strokeStyle = cssVar('--panel') || '#14171d'; ctx.stroke();
      }

      /* end dot */
      ctx.beginPath();
      ctx.arc(g.px[g.px.length - 1], g.py[g.py.length - 1], 3.5, 0, Math.PI * 2);
      ctx.fillStyle = col; ctx.fill();
      if (!mini) {
        ctx.beginPath();
        ctx.arc(g.px[g.px.length - 1], g.py[g.py.length - 1], 7, 0, Math.PI * 2);
        ctx.strokeStyle = hexA(col, 0.35); ctx.lineWidth = 1.5; ctx.stroke();
      }

      /* hover crosshair */
      if (hover >= 0 && hover < ps.length) {
        var hq = ps[hover], hx = S.X(hq.ts), hy = S.Y(hq.v);
        ctx.save();
        ctx.setLineDash([4, 4]);
        ctx.strokeStyle = hexA(cssVar('--muted') || '#8b93a4', 0.7); ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(hx, PAD.t); ctx.lineTo(hx, h - PAD.b); ctx.stroke();
        ctx.restore();
        ctx.beginPath(); ctx.arc(hx, hy, 5, 0, Math.PI * 2);
        ctx.fillStyle = cssVar('--panel') || '#14171d'; ctx.fill();
        ctx.strokeStyle = col; ctx.lineWidth = 2; ctx.stroke();
        if (tip) showTip(hover, S, w);
      } else if (tip && !mini) {
        tip.classList.add('hidden');
      }
      view = { ps: ps, S: S, span: span };
    }

    function showTip(idx, S, w) {
      var ps = view.ps, q = ps[idx];
      if (!q || !tip) return;
      var prev = ps[idx - 1];
      var delta = '';
      if (prev) {
        var dv = q.v - prev.v;
        delta = '<span class="' + (dv >= 0 ? 'upl' : 'downl') + '">' + (dv >= 0 ? '+' : '') + fmtNum(dv) + 'p</span>';
      }
      var when = new Date(q.ts * 1000).toLocaleString([], { weekday: 'short', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
      var extra = q.v2 != null ? ' <span class="dim">bid ' + fmtNum(q.v2) + 'p</span>' : '';
      tip.innerHTML = '<b>' + fmtNum(q.v) + 'p</b> ' + delta + extra + '<br><span class="dim">' + when + '</span>';
      tip.classList.remove('hidden');
      tip.style.left = clamp(S.X(q.ts), 70, w - 70) + 'px';
      tip.style.top = (S.Y(q.v) - 10) + 'px';
    }

    function nearestIndex(clientX) {
      if (!view) return -1;
      var r = canvas.getBoundingClientRect();
      var mx = clientX - r.left;
      var best = -1, bd = Infinity;
      for (var i = 0; i < view.ps.length; i++) {
        var d = Math.abs(view.S.X(view.ps[i].ts) - mx);
        if (d < bd) { bd = d; best = i; }
      }
      return bd <= 40 ? best : -1;
    }

    function normalise(list) {
      var out = [];
      (list || []).forEach(function (q) {
        if (!q) return;
        if (Array.isArray(q)) {
          if (q.length < 2 || q[0] == null || q[1] == null) return;
          out.push({ ts: Number(q[0]), v: Number(q[1]), v2: q.length > 2 && q[2] != null ? Number(q[2]) : null });
          return;
        }
        var v = q[valueKey] != null ? q[valueKey] : q.v;
        if (q.ts == null || v == null) return;
        out.push({ ts: Number(q.ts), v: Number(v), v2: q.bid != null ? Number(q.bid) : null });
      });
      out.sort(function (a, b) { return a.ts - b.ts; });
      return out;
    }

    function buildControls(mount, cfg) {
      if (!mount) return null;
      cfg = cfg || {};
      mount.innerHTML = '';
      var rows = {};
      var mk = function (items, getActive, onPick, cls, label) {
        var box = document.createElement('div');
        box.className = 'chartbtnrow ' + cls;
        if (label) box.setAttribute('aria-label', label);
        items.forEach(function (it) {
          var b = document.createElement('button');
          b.type = 'button';
          b.className = 'chartbtn' + (cls === 'colours' ? ' dot' : '');
          b.dataset.k = it[0];
          if (cls === 'colours') {
            b.title = it[1] + ' line';
            b.setAttribute('aria-label', it[1] + ' line');
            b.style.setProperty('--dot', HEX[it[0]] || cssVar('--accent'));
          } else {
            b.textContent = (cls === 'ranges') ? it[0] : it[1];   /* 1h / 6h / ... , not the seconds */
          }
          b.setAttribute('aria-pressed', getActive() === it[0] ? 'true' : 'false');
          b.addEventListener('click', function () { onPick(it[0], box); });
          box.appendChild(b);
        });
        mount.appendChild(box);
        return box;
      };
      var sync = function (box, active) {
        box.querySelectorAll('.chartbtn').forEach(function (b) { b.setAttribute('aria-pressed', b.dataset.k === active ? 'true' : 'false'); });
      };
      if (cfg.ranges !== false) {
        rows.range = mk(RANGES, function () { return pref.get().range; }, function (k, box) { pref.get().range = k; pref.save(); sync(box, k); draw(); }, 'ranges', 'Time range');
      }
      rows.style = mk(STYLES, function () { return pref.get().style; }, function (k, box) { pref.get().style = k; pref.save(); sync(box, k); draw(); }, 'styles', 'Chart style');
      rows.palette = mk(PALETTES, function () { return pref.get().palette; }, function (k, box) { pref.get().palette = k; pref.save(); sync(box, k); draw(); }, 'colours', 'Line colour');
      return rows;
    }

    var api = {
      setData: function (list) { pts = normalise(list); hover = -1; draw(); },
      setMarkers: function (list) {
        marks = (list || []).filter(function (m) { return m && m.ts != null && (m.v != null || m.value != null); })
          .map(function (m) { return { ts: Number(m.ts), v: Number(m.v != null ? m.v : m.value) }; });
        draw();
      },
      setRange: function (k) { pref.get().range = k; pref.save(); draw(); },
      setStyle: function (k) { pref.get().style = k; pref.save(); draw(); },
      setPalette: function (k) { pref.get().palette = k; pref.save(); draw(); },
      buildControls: buildControls,
      redraw: draw,
      info: function () {
        return {
          ok: pts.length > 0, points: pts.length, shown: view ? view.ps.length : 0,
          range: pref.get().range, style: pref.get().style, palette: pref.get().palette,
          span_s: view ? view.span : 0,
        };
      },
    };
    registry.push(api);

    canvas.addEventListener('mousemove', function (e) { var i = nearestIndex(e.clientX); if (i !== hover) { hover = i; draw(); } });
    canvas.addEventListener('mouseleave', function () { if (hover !== -1) { hover = -1; draw(); } });
    canvas.addEventListener('touchmove', function (e) { if (e.touches && e.touches[0]) { var i = nearestIndex(e.touches[0].clientX); if (i !== hover) { hover = i; draw(); } } }, { passive: true });
    canvas.addEventListener('touchend', function () { hover = -1; draw(); });
    window.addEventListener('resize', function () { draw(); });
    /* the theme swaps CSS variables without a resize event — redraw when it lands */
    try {
      new MutationObserver(function () { draw(); }).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme', 'class', 'style'] });
    } catch (e) {}
    draw();
    return api;
  }

  window.wfmChart = wfmChart;
  window.wfmCharts = function () { return registry.map(function (c) { return c.info(); }); };

  /* back-compat wrapper: the platinum balance chart on Home */
  window.PlatChart = (function () {
    var api = null;
    return {
      init: function () {
        var c = document.getElementById('platChart');
        if (!c) return this;
        injectCss();
        api = wfmChart({
          canvas: c, tip: '#chartTip', valueKey: 'plat', key: 'plat',
          range: 'all', style: 'area', palette: 'accent',
          height: c.parentElement ? c.parentElement.clientHeight : 220,
        });
        /* the view controls mount beside the range pills in the chart card's head */
        var mount = document.getElementById('chartViews');
        if (!mount) {
          var head = c.closest ? c.closest('.card') : null;
          head = head ? head.querySelector('.card-head') : null;
          if (head) {
            mount = document.createElement('div');
            mount.id = 'chartViews';
            mount.className = 'chartviews';
            head.appendChild(mount);
          }
        }
        if (mount) api.buildControls(mount, { ranges: false });
        return this;
      },
      setData: function (l) { if (api) api.setData(l); },
      setMarkers: function (l) { if (api) api.setMarkers(l); },
      setRange: function (k) { if (api) api.setRange(k); },
      setStyle: function (k) { if (api) api.setStyle(k); },
      setPalette: function (k) { if (api) api.setPalette(k); },
      redraw: function () { if (api) api.redraw(); },
      info: function () { return api ? api.info() : { ok: false }; },
    };
  })();
})();
