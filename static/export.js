/* Top sell picks -> shareable PNG. Dependency-free, theme-aware, no network.
   window.WFMExportPicks([rows])  draws 1200x800 and downloads wfm-picks-YYYYMMDD.png
   window.wfmExportSelfTest()     draws the same composition offscreen, no download */
'use strict';

window.WFMExportPicks = (function () {
  const W = 1200, H = 800, MAX_ROWS = 15, ROW_H = 32;
  const FOOTER = 'github.com/JAYST3AM/wfm-dashboard';
  const PANEL = { x: 28, y: 24, w: W - 56, h: H - 48, r: 16 };
  /* table geometry (logical px): rank / item / sell / volume / estimated */
  const COL = { rank: 64, name: 108, nameR: 770, sell: 790, vol: 950, est: PANEL.x + PANEL.w - 36 };
  const TABLE_TOP = 190, DIVIDER = 704, FOOT = 740;

  /* ---------- theme ---------- */
  function cssVar(name, fallback) {
    const v = getComputedStyle(document.documentElement).getPropertyValue(name);
    return (v || '').trim() || fallback;
  }
  function palette() {
    return {
      bg: cssVar('--bg', '#0d0f13'), panel: cssVar('--panel', '#14171d'),
      border: cssVar('--border', '#232833'), text: cssVar('--text', '#e8eaf0'),
      muted: cssVar('--muted', '#8b93a4'), accent: cssVar('--accent', '#ff8a1e'),
      mono: cssVar('--mono', 'ui-monospace, Consolas, monospace'),
      sans: cssVar('--sans', 'system-ui, "Segoe UI", sans-serif'),
    };
  }
  function alpha(color, a) {
    const h = String(color || '').replace('#', '');
    if (!/^[0-9a-f]{3}([0-9a-f]{3})?$/i.test(h)) return color;
    const n = h.length === 3 ? h.split('').map((c) => c + c).join('') : h;
    return 'rgba(' + parseInt(n.slice(0, 2), 16) + ',' + parseInt(n.slice(2, 4), 16) + ',' + parseInt(n.slice(4, 6), 16) + ',' + a + ')';
  }

  /* ---------- rows ---------- */
  /* accepts report.json rows ({name,wts,vol48,value,count}) or DOM-style strings ("47p") */
  function num(x) {
    if (x === null || x === undefined) return null;
    const s = String(x).replace(/[^0-9.-]/g, '');
    if (!s || s === '-' || s === '.' || s === '-.') return null;
    return Number.isFinite(Number(s)) ? Math.round(Number(s)) : null;
  }
  function normRow(r) {
    if (!r) return null;
    const name = String(r.name || r.item || '').trim();
    if (!name) return null;
    const sell = num(r.sell !== undefined ? r.sell : (r.wts !== undefined ? r.wts : r.price));
    const vol = num(r.vol !== undefined ? r.vol : (r.vol48 !== undefined ? r.vol48 : r.volume));
    let est = num(r.est !== undefined ? r.est : (r.value !== undefined ? r.value : r.est_value));
    const count = num(r.count);
    if (est === null && sell !== null && count) est = sell * count;
    return { name: name, sell: sell, vol: vol, est: est };
  }
  function scrapePicks() {
    const el = document.getElementById('sellPicks');
    if (!el) return [];
    const txt = (row, sel) => { const n = row.querySelector(sel); return n ? n.textContent.trim() : null; };
    return Array.prototype.map.call(el.querySelectorAll('.pick:not(.pick-head)'), (row) => ({
      name: txt(row, '.c-name'), sell: txt(row, '.c-price'), vol: txt(row, '.c-act'), est: txt(row, '.c-tot'),
    })).filter((r) => r.name);
  }
  function rowsFrom(arg) {
    let list = Array.isArray(arg) && arg.length ? arg.map(normRow).filter(Boolean) : [];
    if (!list.length) list = scrapePicks().map(normRow).filter(Boolean);
    return list.slice(0, MAX_ROWS);
  }

  /* ---------- canvas ---------- */
  const roundRect = (ctx, x, y, w, h, r) => {
    ctx.beginPath();
    if (ctx.roundRect) { ctx.roundRect(x, y, w, h, r); return; }
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath();
  };
  const hline = (ctx, x1, x2, y, color) => {
    ctx.save(); ctx.strokeStyle = color; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(x1, y + 0.5); ctx.lineTo(x2, y + 0.5); ctx.stroke(); ctx.restore();
  };
  function fit(ctx, text, max) {
    const s = String(text);
    if (ctx.measureText(s).width <= max) return s;
    let t = s;
    while (t.length > 1 && ctx.measureText(t + '…').width > max) t = t.slice(0, -1);
    return t + '…';
  }
  const pad2 = (n) => (n < 10 ? '0' : '') + n;
  function stamp(d) { return '' + d.getFullYear() + pad2(d.getMonth() + 1) + pad2(d.getDate()); }
  function stampHuman(d) {
    return d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate()) + ' ' + pad2(d.getHours()) + ':' + pad2(d.getMinutes());
  }

  function paint(ctx, rows, c) {
    const mono = (px, w) => (w || 400) + ' ' + px + 'px ' + c.mono;
    const sans = (px, w) => (w || 400) + ' ' + px + 'px ' + c.sans;
    const L = PANEL.x + 36, R = COL.est;

    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = c.bg; ctx.fillRect(0, 0, W, H);
    roundRect(ctx, PANEL.x, PANEL.y, PANEL.w, PANEL.h, PANEL.r);
    ctx.fillStyle = c.panel; ctx.fill();
    ctx.strokeStyle = c.border; ctx.lineWidth = 1; ctx.stroke();

    /* header */
    ctx.textBaseline = 'alphabetic';
    ctx.textAlign = 'left'; ctx.fillStyle = c.text; ctx.font = sans(27, 700);
    ctx.fillText('WFM Trader · Top sell picks', L, 86);
    ctx.fillStyle = c.accent; ctx.fillRect(L, 100, 58, 4);
    ctx.textAlign = 'right'; ctx.font = mono(13); ctx.fillStyle = c.muted;
    ctx.fillText('exported ' + stampHuman(new Date()) + ' · ' + rows.length + ' pick' + (rows.length === 1 ? '' : 's'), R, 84);
    hline(ctx, L, R, 140, c.border);

    /* table head */
    ctx.font = mono(12.5, 600); ctx.fillStyle = c.muted;
    ctx.textAlign = 'left';
    ctx.fillText('#', COL.rank, 174);
    ctx.fillText('ITEM', COL.name, 174);
    ctx.textAlign = 'right';
    ctx.fillText('SELL P', COL.sell, 174);
    ctx.fillText('VOL 48H', COL.vol, 174);
    ctx.fillText('EST. VALUE', COL.est, 174);
    hline(ctx, L, R, TABLE_TOP, c.border);

    if (!rows.length) {
      ctx.textAlign = 'center';
      ctx.fillStyle = c.text; ctx.font = sans(22, 600);
      ctx.fillText('no picks yet', W / 2, 420);
      ctx.fillStyle = c.muted; ctx.font = mono(13);
      ctx.fillText('run scripts/report.py to generate data/report.json', W / 2, 452);
    } else {
      rows.forEach((r, i) => {
        const y = TABLE_TOP + ROW_H * i + 21;
        if (i) hline(ctx, L, R, TABLE_TOP + ROW_H * i, alpha(c.border, 0.4));
        ctx.textAlign = 'left'; ctx.font = mono(12.5); ctx.fillStyle = c.muted;
        ctx.fillText(String(i + 1), COL.rank, y);
        ctx.font = sans(14); ctx.fillStyle = c.text;
        ctx.fillText(fit(ctx, r.name, COL.nameR - COL.name), COL.name, y);
        ctx.textAlign = 'right'; ctx.font = mono(13.5, 600); ctx.fillStyle = c.accent;
        ctx.fillText(r.sell === null ? '—' : r.sell + 'p', COL.sell, y);
        ctx.font = mono(12.5); ctx.fillStyle = c.muted;
        ctx.fillText(r.vol === null ? '—' : String(r.vol), COL.vol, y);
        ctx.font = mono(13, 600); ctx.fillStyle = c.text;
        ctx.fillText(r.est === null ? '—' : r.est + 'p', COL.est, y);
      });
    }

    /* footer */
    hline(ctx, L, R, DIVIDER, alpha(c.border, 0.7));
    ctx.textAlign = 'left'; ctx.font = mono(13, 600); ctx.fillStyle = c.accent;
    ctx.fillText(FOOTER, L, FOOT);
    ctx.textAlign = 'right'; ctx.font = mono(12); ctx.fillStyle = c.muted;
    ctx.fillText('prices in platinum (p) · list at = cheapest listing − 1p', R, FOOT);
  }

  function draw(list) {
    const canvas = document.createElement('canvas');
    const dpr = Math.max(1, Math.min(3, window.devicePixelRatio || 1));
    canvas.width = Math.round(W * dpr);
    canvas.height = Math.round(H * dpr);
    const ctx = canvas.getContext('2d');
    if (!ctx) throw new Error('2d context unavailable');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    paint(ctx, list, palette());
    return canvas;
  }

  /* ---------- public ---------- */
  function WFMExportPicks(rows) {
    const list = rowsFrom(rows);
    const canvas = draw(list);
    const file = 'wfm-picks-' + stamp(new Date()) + '.png';
    const out = { ok: true, rows: list.length, file: file, width: canvas.width, height: canvas.height };
    if (typeof canvas.toBlob !== 'function') { out.ok = false; out.error = 'canvas.toBlob unavailable'; return out; }
    canvas.toBlob((blob) => {
      if (!blob) return;
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url; a.download = file; a.style.display = 'none';
      (document.body || document.documentElement).appendChild(a);
      a.click();
      setTimeout(() => { URL.revokeObjectURL(url); if (a.parentNode) a.parentNode.removeChild(a); }, 1000);
    }, 'image/png');
    return out;
  }

  function wfmExportSelfTest() {
    const out = { ok: false, width: 0, height: 0, nonEmptyPixels: 0, error: null };
    try {
      const list = rowsFrom();
      const canvas = draw(list);
      out.width = canvas.width; out.height = canvas.height;
      const ctx = canvas.getContext('2d');
      const data = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
      const b = (3 * canvas.width + 3) * 4; /* (3,3) is always raw --bg, outside the panel */
      let n = 0;
      for (let i = 0; i < data.length; i += 4) {
        if (Math.abs(data[i] - data[b]) + Math.abs(data[i + 1] - data[b + 1]) + Math.abs(data[i + 2] - data[b + 2]) > 24) n++;
      }
      out.nonEmptyPixels = n;
      out.rows = list.length;
      out.ok = canvas.width > 0 && canvas.height > 0 && n > 0;
    } catch (e) {
      out.error = String((e && e.message) || e);
    }
    return out;
  }

  WFMExportPicks.selfTest = wfmExportSelfTest;
  window.wfmExportSelfTest = wfmExportSelfTest;
  return WFMExportPicks;
})();
