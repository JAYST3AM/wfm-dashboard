/* WFM Trader — shared theme module (all pages)

   Palettes: 60 entries of [name, bg, panel, panel2, border, text, muted, accent, accentDim, hover, mode]
   mode is 'dark' or 'light' (index 10). Regenerate with: python tools/gen_themes.py

   Any page that includes this file gets:
   - wfmApplyTheme(i): apply + persist + update .theme-item/#themeName, redraw PlatChart, set --up/--down
   - wfmBuildThemeGrid(): render the picker grid + the Dark/Light filter into #themeGrid
   - wfmInitThemeUI(): bind #themeBtn / #themePanel / #themeGrid
   The saved theme is applied automatically on load, so every page matches. */
'use strict';

window.WFM_THEMES = [
  ['Vor Orange', '#0d0f13', '#14171d', '#191d25', '#232833', '#e8eaf0', '#8b93a4', '#ff8a1e', '#7a4713', '#181d26', 'dark'],
  ['Corpus Cyan', '#0b0f14', '#10161d', '#151c25', '#1e2933', '#e6f2f5', '#7f96a3', '#22d3ee', '#155e6b', '#131b24', 'dark'],
  ['Kuva Crimson', '#120c0e', '#1a1114', '#21161a', '#2c1c22', '#f0e6e8', '#9c8189', '#ef4444', '#7f1d1d', '#1f1418', 'dark'],
  ['Lotus Violet', '#0f0c16', '#16111f', '#1d1729', '#2a2138', '#ece8f5', '#9188a6', '#a855f7', '#5b2d8a', '#1a1426', 'dark'],
  ['Orokin Gold', '#12100a', '#1a170f', '#221d13', '#332b1a', '#f5efe0', '#a5987a', '#eab308', '#7a5c10', '#201b12', 'dark'],
  ['Sentient Teal', '#0a1211', '#101a19', '#152220', '#1f302d', '#e3f2ef', '#7fa39c', '#14b8a6', '#0f5f56', '#131f1d', 'dark'],
  ['Infested', '#0c110a', '#121810', '#182016', '#22301d', '#e9f2e4', '#8ba381', '#84cc16', '#4d7c0f', '#161d13', 'dark'],
  ['Void Indigo', '#0c0d1a', '#121428', '#181b33', '#232746', '#e7e9f7', '#878cb5', '#6366f1', '#3730a3', '#15172c', 'dark'],
  ['Argon Crystal', '#0a1016', '#0f1720', '#141d29', '#1e2a3a', '#dff0fa', '#7c95a8', '#38bdf8', '#0c4a6e', '#121b26', 'dark'],
  ['Rubedo Red', '#110a0c', '#180f12', '#1f1418', '#2e1c22', '#f2e6e9', '#a08088', '#f43f5e', '#881337', '#1d1317', 'dark'],
  ['Luna Silver', '#0e1013', '#15181d', '#1b1f26', '#262b34', '#eceef2', '#9098a5', '#cbd5e1', '#64748b', '#191d23', 'dark'],
  ['Duviri Rose', '#150f14', '#1c141b', '#241a22', '#33242f', '#f5e9f0', '#a8859a', '#f472b6', '#9d174d', '#211821', 'dark'],
  ['Cryotic Emerald', '#0a120d', '#0f1912', '#141f18', '#1d2e24', '#e3f2e8', '#7fa38c', '#10b981', '#065f46', '#121d16', 'dark'],
  ['Solar Amber', '#131008', '#1b170c', '#231e11', '#342c19', '#f5efdc', '#a39877', '#f59e0b', '#92400e', '#211c10', 'dark'],
  ['Frost Light', '#eef2f7', '#ffffff', '#f4f7fb', '#d7dee9', '#16202c', '#5b6b7f', '#0284c7', '#0369a1', '#e8eef6', 'light'],
  ['Blood Moon', '#100a0e', '#170e14', '#1e131a', '#2e1c26', '#f2e6ee', '#a08093', '#dc2626', '#7f1d1d', '#1c1119', 'dark'],
  ['Vome Mint', '#0b1310', '#101b17', '#15221d', '#1f322b', '#e4f4ee', '#7fa899', '#34d399', '#047857', '#131f1a', 'dark'],
  ['Zariman Neon', '#0d0a14', '#130f1e', '#191427', '#251e39', '#ece6f7', '#8f84ad', '#d946ef', '#86198f', '#170f24', 'dark'],
  ['Cephalon Grid', '#050d07', '#0a140c', '#0e1a10', '#15281a', '#d9f5df', '#6f9c7a', '#22c55e', '#166534', '#0c1810', 'dark'],
  ['Eidolon Sunset', '#140e0c', '#1c1411', '#241a16', '#34261f', '#f5e9e2', '#a8836f', '#ff7a45', '#9a3412', '#211814', 'dark'],
  ['Uranus Deep', '#08111a', '#0d1824', '#121f2e', '#1b2d40', '#e0eefa', '#7a93a8', '#0ea5e9', '#075985', '#101d2a', 'dark'],
  ['Lotus Lavender', '#100f18', '#17161f', '#1e1c29', '#2b2838', '#ecebf5', '#8f8ba6', '#8b5cf6', '#5b21b6', '#1a1824', 'dark'],
  ['Crimson Gold', '#130d0d', '#1b1313', '#221818', '#332424', '#f4e8e6', '#a38986', '#eab308', '#854d0e', '#201616', 'dark'],
  ['Titanium', '#0f1113', '#16191c', '#1c2024', '#282d33', '#e8ebee', '#8d959e', '#9ca3af', '#4b5563', '#1a1e22', 'dark'],
  ['Neon Lime', '#0b1106', '#111807', '#17210b', '#233212', '#e8f5d9', '#8fa873', '#a3e635', '#4d7c0f', '#151d0a', 'dark'],
  ['Fomorian Magma', '#140b06', '#1c100a', '#24150d', '#352013', '#f7e8dc', '#a87f63', '#f97316', '#9a3412', '#21130c', 'dark'],
  ['Vox Aqua', '#071214', '#0c1a1d', '#112227', '#1a3339', '#def2f5', '#79a0a6', '#06b6d4', '#155e75', '#0f1e22', 'dark'],
  ['Ducat Rose', '#13100c', '#1b1611', '#231d17', '#342a22', '#f5ece1', '#a89684', '#fda4af', '#9f1239', '#211a14', 'dark'],
  ['Cephalon White', '#f6f6f3', '#ffffff', '#fbfbf9', '#dddcd4', '#1d1c18', '#6d6b60', '#b45309', '#92400e', '#f0efe9', 'light'],
  ['Sentient Nebula', '#0b0a12', '#12101b', '#181525', '#241f38', '#eae7f5', '#8a83a8', '#c084fc', '#6b21a8', '#151223', 'dark'],
  ['Umbra Black', '#08080b', '#161618', '#212123', '#303032', '#f5f4f2', '#7a797a', '#e0a92b', '#5a4517', '#1b1b1d', 'dark'],
  ['Nekros Bone', '#0f0e0c', '#1c1b19', '#272624', '#353533', '#f0f6f8', '#7b7d7d', '#5eead4', '#2d6258', '#21201e', 'dark'],
  ['Lua Ivory', '#f5f3ee', '#ffffff', '#fafaf7', '#d8d6d1', '#1a1711', '#5c5953', '#8a6d3b', '#d5cbb8', '#eae8e3', 'light'],
  ['Cetus Sand', '#f6f0e4', '#ffffff', '#fbf8f3', '#d8d3c9', '#1c150f', '#5d574f', '#b45309', '#e2c1a2', '#ebe5da', 'light'],
  ['Ostron Ochre', '#f7f2e7', '#ffffff', '#fbf9f4', '#d9d5cb', '#1b160f', '#5d5850', '#a16207', '#ddc7a4', '#ece7dd', 'light'],
  ['Solaris Daylight', '#eef4f8', '#ffffff', '#f7fafc', '#d1d7da', '#131616', '#55595a', '#0369a1', '#a8cade', '#e3e9ed', 'light'],
  ['Corpus Platinum', '#f2f4f7', '#ffffff', '#f9fafb', '#d5d7d9', '#141715', '#575959', '#0e7490', '#aeced8', '#e7e9ec', 'light'],
  ['Orokin Marble', '#f7f5ef', '#ffffff', '#fbfaf8', '#d9d8d2', '#1b160e', '#5d5952', '#9a6a05', '#dbcba9', '#eceae4', 'light'],
  ['Tenno Dawn', '#fdf3ec', '#ffffff', '#fefaf6', '#dfd6d0', '#1d140f', '#605751', '#c2410c', '#ebbea9', '#f2e8e1', 'light'],
  ['Deimos Bone', '#f4f2e9', '#ffffff', '#faf9f5', '#d7d5cd', '#17170f', '#595950', '#4d7c0f', '#c2cfa8', '#e9e7df', 'light'],
  ['Zariman Alabaster', '#f4f1fa', '#ffffff', '#faf9fd', '#d7d4dc', '#181319', '#5a565c', '#6d28d9', '#ccb5f0', '#e9e6ef', 'light'],
  ['Holdfast Pale', '#f0f4f8', '#ffffff', '#f8fafc', '#d3d7da', '#141519', '#56585c', '#1d4ed8', '#b1c2ee', '#e5e9ed', 'light'],
  ['Duviri Chalk', '#f7f3f7', '#ffffff', '#fbfafb', '#d9d6d9', '#1b1217', '#5d565a', '#a21caf', '#deb2e1', '#ece8ec', 'light'],
  ['Necralisk Mist', '#f1f5f2', '#ffffff', '#f9faf9', '#d4d8d5', '#141714', '#565a57', '#0f766e', '#adcfca', '#e6eae7', 'light'],
  ['Entrati Ivory', '#f6f1e8', '#ffffff', '#fbf9f5', '#d8d4cc', '#1a140f', '#5c5650', '#92400e', '#d8bca7', '#ebe6de', 'light'],
  ['Cavia Vermilion', '#fdf1ee', '#ffffff', '#fef9f7', '#dfd4d1', '#1c1210', '#605553', '#b91c1c', '#e9b1af', '#f2e6e3', 'light'],
  ['Quills Parchment', '#f7f2e3', '#ffffff', '#fbf9f2', '#d9d5c8', '#1a150f', '#5c574f', '#854d0e', '#d5c0a3', '#ece7d9', 'light'],
  ['Vox Azure', '#eef6fb', '#ffffff', '#f7fbfd', '#d1d8dd', '#131818', '#555b5c', '#0284c7', '#a7d4eb', '#e3ebf0', 'light'],
  ['Eidolon Lume', '#f4f6f9', '#ffffff', '#fafbfc', '#d7d8db', '#161418', '#59585c', '#4338ca', '#bfbdeb', '#e9ebee', 'light'],
  ['Cryotic Blue', '#eff6fb', '#ffffff', '#f8fbfd', '#d2d8dd', '#141519', '#56585d', '#1d4ed8', '#b0c4f0', '#e4ebf0', 'light'],
  ['Ducat Beige', '#f8f4ea', '#ffffff', '#fcfaf6', '#dad7ce', '#1c150f', '#5e5851', '#b45309', '#e4c4a6', '#ede9df', 'light'],
  ['Prime Gold Leaf', '#fbf6e9', '#ffffff', '#fdfbf5', '#ddd8cd', '#1b160e', '#5e5950', '#9a6a05', '#decca5', '#f0ebdf', 'light'],
  ['Relic Pale Gold', '#f9f5ec', '#ffffff', '#fcfaf6', '#dbd8d0', '#1b160f', '#5e5951', '#a16207', '#dfc9a7', '#eeeae1', 'light'],
  ['Sentient Frost', '#f0f6f6', '#ffffff', '#f8fbfb', '#d3d8d8', '#141714', '#565a58', '#0f766e', '#acd0cd', '#e5ebeb', 'light'],
  ['Infested Bloom', '#f4f8f0', '#ffffff', '#fafcf8', '#d7dad3', '#17170f', '#595a52', '#4d7c0f', '#c2d3ac', '#e9ede5', 'light'],
  ['Grineer Sandstone', '#f6f1e6', '#ffffff', '#fbf9f4', '#d8d4ca', '#1b140f', '#5d5650', '#9a3412', '#dab8a6', '#ebe6dc', 'light'],
  ['Kuva Blush', '#faf1f2', '#ffffff', '#fdf9f9', '#dcd4d5', '#1c1211', '#5f5554', '#be123c', '#e8aebb', '#efe6e7', 'light'],
  ['Lotus Blossom', '#faf1f7', '#ffffff', '#fdf9fb', '#dcd4d9', '#1b1217', '#5e555a', '#a21caf', '#e0b1e1', '#efe6ec', 'light'],
  ['Dax Brass Light', '#f6f3ea', '#ffffff', '#fbfaf6', '#d8d6ce', '#1a160f', '#5c5851', '#92660a', '#d8c9a7', '#ebe8df', 'light'],
  ['Umbra Silver', '#f2f3f5', '#ffffff', '#f9fafa', '#d5d6d8', '#161412', '#585756', '#334155', '#b9bec5', '#e7e8ea', 'light'],
];

(function () {
  const TVARS = ['bg', 'panel', 'panel2', 'border', 'text', 'muted', 'accent', 'accentDim', 'hover'];
  window.wfmThemeMode = function (t) {
    if (!t) return 'dark';
    if (t[10] === 'light' || t[10] === 'dark') return t[10];
    // fall back to the background luminance when an old entry has no mode
    const h = String(t[1] || '#000').replace('#', '');
    if (h.length !== 6) return 'dark';
    const r = parseInt(h.slice(0, 2), 16), g = parseInt(h.slice(2, 4), 16), b = parseInt(h.slice(4, 6), 16);
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255 > 0.5 ? 'light' : 'dark';
  };
  window.wfmApplyTheme = function (i) {
    const t = window.WFM_THEMES[i]; if (!t) return;
    const root = document.documentElement.style;
    TVARS.forEach((v, k) => {
      const id = (v === 'accentDim') ? 'accent-dim' : v;
      root.setProperty('--' + id, t[k + 1]);
    });
    // gain/loss tones follow the mode so they stay readable on light backgrounds
    const light = window.wfmThemeMode(t) === 'light';
    root.setProperty('--up', light ? '#15803d' : '#4ade80');
    root.setProperty('--down', light ? '#b91c1c' : '#f87171');
    root.setProperty('--chart-grid', mixGrid(t[4]));
    try { localStorage.setItem('wfm.theme', String(i)); } catch (e) { /* private mode */ }
    document.querySelectorAll('.theme-item').forEach(el => el.classList.toggle('active', +el.dataset.i === i));
    const nameEl = document.getElementById('themeName');
    if (nameEl) nameEl.textContent = t[0] + ' \u00b7 ' + window.wfmThemeMode(t);
    if (window.PlatChart) PlatChart.redraw();
  };
  function mixGrid(c) { return c; }   // grid lines use the theme border already
  function ensureCss() {
    if (document.getElementById('themeCss')) return;
    const st = document.createElement('style');
    st.id = 'themeCss';
    st.textContent = [
      '.tp-filter{display:flex;gap:6px;margin:0 0 10px}',
      '.tp-filter .tpf{cursor:pointer;border:1px solid var(--border);background:var(--panel2);',
      'color:var(--muted);border-radius:999px;padding:3px 10px;font-size:11px;font-weight:600}',
      '.tp-filter .tpf:hover{border-color:var(--accent-dim);color:var(--text)}',
      '.tp-filter .tpf.on{border-color:var(--accent);color:var(--accent);background:var(--hover)}',
    ].join('');
    document.head.appendChild(st);
  }
  window.wfmEnsureThemeCss = ensureCss;
  window.wfmThemeFilter = function (mode) {
    try { localStorage.setItem('wfm.themeFilter', mode); } catch (e) { /* private mode */ }
    window.wfmBuildThemeGrid();
  };
  window.wfmBuildThemeGrid = function () {
    const grid = document.getElementById('themeGrid'); if (!grid) return;
    ensureCss();
    const host = grid.parentElement || grid;
    let filter = 'all';
    try { filter = localStorage.getItem('wfm.themeFilter') || 'all'; } catch (e) { /* private mode */ }
    const counts = { all: window.WFM_THEMES.length, dark: 0, light: 0 };
    window.WFM_THEMES.forEach(t => { counts[window.wfmThemeMode(t)]++; });
    if (!document.getElementById('themeFilter')) {
      const bar = document.createElement('div');
      bar.id = 'themeFilter';
      bar.className = 'tp-filter';
      bar.innerHTML = ['all', 'dark', 'light'].map((m, k) =>
        '<button class="tpf" data-m="' + m + '" type="button">' +
        (m === 'all' ? 'All' : m === 'dark' ? 'Dark' : 'Light') + ' ' + counts[m] + '</button>').join('');
      host.insertBefore(bar, grid);
      bar.addEventListener('click', e => {
        const b = e.target.closest('.tpf'); if (!b) return;
        window.wfmThemeFilter(b.dataset.m);
      });
    }
    document.querySelectorAll('#themeFilter .tpf').forEach(b => b.classList.toggle('on', b.dataset.m === filter));
    const saved = parseInt(localStorage.getItem('wfm.theme') || '0', 10) || 0;
    grid.innerHTML = window.WFM_THEMES.map((t, i) => {
      const mode = window.wfmThemeMode(t);
      if (filter !== 'all' && mode !== filter) return '';
      return `<div class="theme-item${i === saved ? ' active' : ''}" data-i="${i}" data-mode="${mode}" title="${t[0]} \u00b7 ${mode}">
      <span class="dots"><i style="background:${t[1]}"></i><i style="background:${t[3]}"></i><i style="background:${t[7]}"></i></span>
      <span class="tname">${t[0]}</span>
    </div>`;
    }).join('');
    grid.querySelectorAll('.theme-item').forEach(el => el.addEventListener('click', () => window.wfmApplyTheme(+el.dataset.i)));
  };
  window.wfmInitThemeUI = function () {
    const btn = document.getElementById('themeBtn'), panel = document.getElementById('themePanel');
    if (!btn || !panel) return;
    window.wfmBuildThemeGrid();
    btn.addEventListener('click', () => panel.classList.toggle('hidden'));
    document.addEventListener('click', e => {
      if (!panel.contains(e.target) && !btn.contains(e.target)) panel.classList.add('hidden');
    });
  };
  const saved = parseInt(localStorage.getItem('wfm.theme') || '0', 10);
  window.wfmApplyTheme(isNaN(saved) ? 0 : saved);
})();
