/* Platinum line chart — canvas, theme-aware, interactive. */
'use strict';
window.PlatChart = (() => {
  let pts = [], range = 'all', hover = -1;
  let canvas, ctx, wrap, tip;
  const PAD = { l: 58, r: 16, t: 16, b: 30 };

  const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  const fmtK = (v) => Math.abs(v) >= 10000 ? (v / 1000).toFixed(1).replace(/\.0$/, '') + 'k' : String(Math.round(v));
  const fmtFull = (v) => Number(v).toLocaleString();

  function hexA(hex, a) {
    const h = (hex || '#ff8a1e').replace('#', '');
    const n = h.length === 3 ? h.split('').map((c) => c + c).join('') : h;
    const r = parseInt(n.slice(0, 2), 16), g = parseInt(n.slice(2, 4), 16), b = parseInt(n.slice(4, 6), 16);
    return `rgba(${r},${g},${b},${a})`;
  }

  function filtered() {
    if (!pts.length || range === 'all') return pts;
    const span = { '24h': 86400, '7d': 7 * 86400, '30d': 30 * 86400 }[range] || 0;
    const t1 = pts[pts.length - 1].ts;
    return pts.filter((p) => p.ts >= t1 - span);
  }

  function sizeCanvas() {
    const dpr = window.devicePixelRatio || 1;
    const w = wrap.clientWidth, h = wrap.clientHeight;
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
    canvas.style.width = w + 'px';
    canvas.style.height = h + 'px';
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return { w, h };
  }

  function scales(ps, w, h) {
    const xs = ps.map((p) => p.ts);
    let x0 = Math.min.apply(null, xs), x1 = Math.max.apply(null, xs);
    if (x1 === x0) x0 = x0 - 3600;
    const ys = ps.map((p) => p.plat);
    let y0 = Math.min.apply(null, ys), y1 = Math.max.apply(null, ys);
    if (y1 === y0) { y0 -= 5; y1 += 5; }
    const padY = Math.max((y1 - y0) * 0.15, 2);
    y0 -= padY; y1 += padY;
    const X = (t) => PAD.l + (t - x0) / (x1 - x0) * (w - PAD.l - PAD.r);
    const Y = (v) => h - PAD.b - (v - y0) / (y1 - y0) * (h - PAD.t - PAD.b);
    return { X, Y, x0, x1, y0, y1 };
  }

  /* monotone cubic (Fritsch–Carlson) -> bezier segments; no fake dips on stepped data */
  function buildSegs(ps, X, Y) {
    const n = ps.length;
    const px = ps.map((p) => X(p.ts)), py = ps.map((p) => Y(p.plat));
    if (n < 2) return { px, py, segs: [] };
    const dx = [], dy = [], m = [];
    for (let i = 0; i < n - 1; i++) { dx[i] = px[i + 1] - px[i]; dy[i] = py[i + 1] - py[i]; }
    m[0] = dy[0] / dx[0];
    for (let i = 1; i < n - 1; i++) {
      const a = dy[i - 1] / dx[i - 1], b = dy[i] / dx[i];
      m[i] = (a * b <= 0) ? 0 : (a + b) / 2;
    }
    m[n - 1] = dy[n - 2] / dx[n - 2];
    for (let i = 0; i < n - 1; i++) {
      if (dy[i] === 0) { m[i] = 0; m[i + 1] = 0; continue; }
      const s = m[i] / (dy[i] / dx[i]), t = m[i + 1] / (dy[i] / dx[i]);
      const q = s * s + t * t;
      if (q > 9) { const f = 3 / Math.sqrt(q); m[i] = f * s * (dy[i] / dx[i]); m[i + 1] = f * t * (dy[i] / dx[i]); }
    }
    const segs = [];
    for (let i = 0; i < n - 1; i++) {
      segs.push({
        c1x: px[i] + dx[i] / 3, c1y: py[i] + m[i] * dx[i] / 3,
        c2x: px[i + 1] - dx[i] / 3, c2y: py[i + 1] - m[i + 1] * dx[i] / 3,
        x: px[i + 1], y: py[i + 1],
      });
    }
    return { px, py, segs };
  }

  function pathFrom(segs, px0, py0, ctx2) {
    ctx2.beginPath();
    ctx2.moveTo(px0, py0);
    for (const s of segs) ctx2.bezierCurveTo(s.c1x, s.c1y, s.c2x, s.c2y, s.x, s.y);
  }

  function posTip(idx, X, Y, w) {
    const ps = filtered();
    const pt = ps[idx];
    if (!pt) { tip.classList.add('hidden'); return; }
    const px = X(pt.ts), py = Y(pt.plat);
    const prev = ps[idx - 1];
    let delta = '';
    if (prev) {
      const dv = pt.plat - prev.plat;
      delta = `<span class="${dv >= 0 ? 'upl' : 'downl'}">${dv >= 0 ? '+' : ''}${fmtFull(dv)}p</span>`;
    }
    const when = new Date(pt.ts * 1000).toLocaleString([], { weekday: 'short', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
    tip.innerHTML = `<b>${fmtFull(pt.plat)}p</b> ${delta}<br><span class="dim">${when}</span>`;
    tip.classList.remove('hidden');
    const cx = Math.min(Math.max(px, 70), w - 70);
    tip.style.left = cx + 'px';
    tip.style.top = (py - 10) + 'px';
  }

  function draw() {
    const { w, h } = sizeCanvas();
    ctx.clearRect(0, 0, w, h);
    const accent = css('--accent') || '#ff8a1e';
    const muted = css('--muted') || '#8b93a4';
    const border = css('--border') || '#232833';
    const panel = css('--panel') || '#14171d';
    const ps = filtered();

    if (!ps.length) {
      ctx.fillStyle = muted;
      ctx.font = '13px Segoe UI, system-ui, sans-serif';
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      ctx.fillText('No snapshots yet — the collector starts logging automatically.', w / 2, h / 2);
      tip.classList.add('hidden');
      return;
    }

    const { X, Y, x0, x1, y0, y1 } = scales(ps, w, h);

    /* gridlines + y labels */
    ctx.font = '11px Consolas, monospace';
    ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
    for (let i = 0; i <= 4; i++) {
      const v = y0 + (y1 - y0) * i / 4;
      const y = Y(v);
      ctx.strokeStyle = border; ctx.globalAlpha = 0.55;
      ctx.beginPath(); ctx.moveTo(PAD.l, y); ctx.lineTo(w - PAD.r, y); ctx.stroke();
      ctx.globalAlpha = 1;
      ctx.fillStyle = muted;
      ctx.fillText(fmtK(v) + 'p', PAD.l - 8, y);
    }

    /* x labels */
    ctx.textAlign = 'center'; ctx.textBaseline = 'top';
    let lastLbl = '';
    for (let i = 0; i <= 4; i++) {
      const t = x0 + (x1 - x0) * i / 4;
      const d = new Date(t * 1000);
      const label = (range === '24h')
        ? d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
        : d.toLocaleDateString([], { month: 'short', day: 'numeric' });
      if (label === lastLbl) continue;
      lastLbl = label;
      ctx.fillStyle = muted;
      ctx.fillText(label, X(t), h - PAD.b + 8);
    }

    const { px, py, segs } = buildSegs(ps, X, Y);

    if (segs.length) {
      /* area fill */
      const grad = ctx.createLinearGradient(0, PAD.t, 0, h - PAD.b);
      grad.addColorStop(0, hexA(accent, 0.30));
      grad.addColorStop(1, hexA(accent, 0.02));
      pathFrom(segs, px[0], py[0], ctx);
      ctx.lineTo(px[px.length - 1], h - PAD.b);
      ctx.lineTo(px[0], h - PAD.b);
      ctx.closePath();
      ctx.fillStyle = grad;
      ctx.fill();

      /* line with glow */
      ctx.save();
      pathFrom(segs, px[0], py[0], ctx);
      ctx.strokeStyle = accent; ctx.lineWidth = 2; ctx.lineJoin = 'round'; ctx.lineCap = 'round';
      ctx.shadowColor = hexA(accent, 0.5); ctx.shadowBlur = 9;
      ctx.stroke();
      ctx.restore();
    }

    /* end dot */
    ctx.beginPath();
    ctx.arc(px[px.length - 1], py[py.length - 1], 3.5, 0, Math.PI * 2);
    ctx.fillStyle = accent; ctx.fill();
    ctx.beginPath();
    ctx.arc(px[px.length - 1], py[py.length - 1], 7, 0, Math.PI * 2);
    ctx.strokeStyle = hexA(accent, 0.35); ctx.lineWidth = 1.5; ctx.stroke();

    /* hover crosshair */
    if (hover >= 0 && hover < ps.length) {
      const hx = X(ps[hover].ts), hy = Y(ps[hover].plat);
      ctx.save();
      ctx.setLineDash([4, 4]);
      ctx.strokeStyle = hexA(muted, 0.7); ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(hx, PAD.t); ctx.lineTo(hx, h - PAD.b); ctx.stroke();
      ctx.restore();
      ctx.beginPath(); ctx.arc(hx, hy, 5, 0, Math.PI * 2);
      ctx.fillStyle = panel; ctx.fill();
      ctx.strokeStyle = accent; ctx.lineWidth = 2; ctx.stroke();
      posTip(hover, X, Y, w);
    } else {
      tip.classList.add('hidden');
    }
  }

  function nearest(mx) {
    const ps = filtered();
    if (!ps.length) return -1;
    const xs = ps.map((p) => p.ts);
    const x0 = Math.min.apply(null, xs), x1 = Math.max.apply(null, xs);
    const span = Math.max(1, x1 - x0);
    const width = wrap.clientWidth - PAD.l - PAD.r;
    let best = -1, bd = Infinity;
    for (let i = 0; i < ps.length; i++) {
      const px = PAD.l + ((ps[i].ts - x0) / span) * width;
      const d = Math.abs(px - mx);
      if (d < bd) { bd = d; best = i; }
    }
    return best;
  }

  function init() {
    canvas = document.getElementById('platChart');
    wrap = canvas.parentElement;
    tip = document.getElementById('chartTip');
    ctx = canvas.getContext('2d');
    canvas.addEventListener('mousemove', (e) => {
      const idx = nearest(e.offsetX);
      hover = idx;
      draw();
    });
    canvas.addEventListener('mouseleave', () => { hover = -1; draw(); });
    window.addEventListener('resize', () => draw());
    draw();
  }

  return {
    init,
    setData: (p) => { pts = (p || []).slice().sort((a, b) => a.ts - b.ts); draw(); },
    setRange: (r) => { range = r; hover = -1; draw(); },
    redraw: () => draw(),
    info: () => ({ n: pts.length, shown: filtered().length, range }),
  };
})();
