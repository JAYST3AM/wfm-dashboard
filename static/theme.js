/* WFM Trader — shared theme module (dashboard + lookup page)
   Single source of the palette list. Any page that includes this file gets:
   - wfmApplyTheme(i): apply + persist + update .theme-item/#themeName + redraw PlatChart if present
   - wfmBuildThemeGrid(): render the picker grid into #themeGrid
   - wfmInitThemeUI(): bind #themeBtn / #themePanel / #themeGrid (lookup page)
   The saved theme is applied automatically on load, so every page matches.
   themes: [name, bg, panel, panel2, border, text, muted, accent, accentDim, hover] */
'use strict';
window.WFM_THEMES = [
  ['Vor Orange',   '#0d0f13', '#14171d', '#191d25', '#232833', '#e8eaf0', '#8b93a4', '#ff8a1e', '#7a4713', '#181d26'],
  ['Corpus Cyan',  '#0b0f14', '#10161d', '#151c25', '#1e2933', '#e6f2f5', '#7f96a3', '#22d3ee', '#155e6b', '#131b24'],
  ['Kuva Crimson', '#120c0e', '#1a1114', '#21161a', '#2c1c22', '#f0e6e8', '#9c8189', '#ef4444', '#7f1d1d', '#1f1418'],
  ['Lotus Violet', '#0f0c16', '#16111f', '#1d1729', '#2a2138', '#ece8f5', '#9188a6', '#a855f7', '#5b2d8a', '#1a1426'],
  ['Orokin Gold',  '#12100a', '#1a170f', '#221d13', '#332b1a', '#f5efe0', '#a5987a', '#eab308', '#7a5c10', '#201b12'],
  ['Sentient Teal','#0a1211', '#101a19', '#152220', '#1f302d', '#e3f2ef', '#7fa39c', '#14b8a6', '#0f5f56', '#131f1d'],
  ['Infested',     '#0c110a', '#121810', '#182016', '#22301d', '#e9f2e4', '#8ba381', '#84cc16', '#4d7c0f', '#161d13'],
  ['Void Indigo',  '#0c0d1a', '#121428', '#181b33', '#232746', '#e7e9f7', '#878cb5', '#6366f1', '#3730a3', '#15172c'],
  ['Argon Crystal','#0a1016', '#0f1720', '#141d29', '#1e2a3a', '#dff0fa', '#7c95a8', '#38bdf8', '#0c4a6e', '#121b26'],
  ['Rubedo Red',   '#110a0c', '#180f12', '#1f1418', '#2e1c22', '#f2e6e9', '#a08088', '#f43f5e', '#881337', '#1d1317'],
  ['Luna Silver',  '#0e1013', '#15181d', '#1b1f26', '#262b34', '#eceef2', '#9098a5', '#cbd5e1', '#64748b', '#191d23'],
  ['Sakura',       '#150f14', '#1c141b', '#241a22', '#33242f', '#f5e9f0', '#a8859a', '#f472b6', '#9d174d', '#211821'],
  ['Emerald',      '#0a120d', '#0f1912', '#141f18', '#1d2e24', '#e3f2e8', '#7fa38c', '#10b981', '#065f46', '#121d16'],
  ['Solar Amber',  '#131008', '#1b170c', '#231e11', '#342c19', '#f5efdc', '#a39877', '#f59e0b', '#92400e', '#211c10'],
  ['Frost Light',  '#eef2f7', '#ffffff', '#f4f7fb', '#d7dee9', '#16202c', '#5b6b7f', '#0284c7', '#0369a1', '#e8eef6'],
  ['Blood Moon',   '#100a0e', '#170e14', '#1e131a', '#2e1c26', '#f2e6ee', '#a08093', '#dc2626', '#7f1d1d', '#1c1119'],
  ['Mint',         '#0b1310', '#101b17', '#15221d', '#1f322b', '#e4f4ee', '#7fa899', '#34d399', '#047857', '#131f1a'],
  ['Cyberpunk',    '#0d0a14', '#130f1e', '#191427', '#251e39', '#ece6f7', '#8f84ad', '#d946ef', '#86198f', '#170f24'],
  ['Matrix',       '#050d07', '#0a140c', '#0e1a10', '#15281a', '#d9f5df', '#6f9c7a', '#22c55e', '#166534', '#0c1810'],
  ['Sunset',       '#140e0c', '#1c1411', '#241a16', '#34261f', '#f5e9e2', '#a8836f', '#ff7a45', '#9a3412', '#211814'],
  ['Deep Ocean',   '#08111a', '#0d1824', '#121f2e', '#1b2d40', '#e0eefa', '#7a93a8', '#0ea5e9', '#075985', '#101d2a'],
  ['Lavender',     '#100f18', '#17161f', '#1e1c29', '#2b2838', '#ecebf5', '#8f8ba6', '#8b5cf6', '#5b21b6', '#1a1824'],
  ['Crimson Gold', '#130d0d', '#1b1313', '#221818', '#332424', '#f4e8e6', '#a38986', '#eab308', '#854d0e', '#201616'],
  ['Titanium',     '#0f1113', '#16191c', '#1c2024', '#282d33', '#e8ebee', '#8d959e', '#9ca3af', '#4b5563', '#1a1e22'],
  ['Neon Lime',    '#0b1106', '#111807', '#17210b', '#233212', '#e8f5d9', '#8fa873', '#a3e635', '#4d7c0f', '#151d0a'],
  ['Magma',        '#140b06', '#1c100a', '#24150d', '#352013', '#f7e8dc', '#a87f63', '#f97316', '#9a3412', '#21130c'],
  ['Aqua Marine',  '#071214', '#0c1a1d', '#112227', '#1a3339', '#def2f5', '#79a0a6', '#06b6d4', '#155e75', '#0f1e22'],
  ['Rose Gold',    '#13100c', '#1b1611', '#231d17', '#342a22', '#f5ece1', '#a89684', '#fda4af', '#9f1239', '#211a14'],
  ['Paper Light',  '#f6f6f3', '#ffffff', '#fbfbf9', '#dddcd4', '#1d1c18', '#6d6b60', '#b45309', '#92400e', '#f0efe9'],
  ['Nebula',       '#0b0a12', '#12101b', '#181525', '#241f38', '#eae7f5', '#8a83a8', '#c084fc', '#6b21a8', '#151223'],
];
(function () {
  const TVARS = ['bg', 'panel', 'panel2', 'border', 'text', 'muted', 'accent', 'accentDim', 'hover'];
  window.wfmApplyTheme = function (i) {
    const t = window.WFM_THEMES[i]; if (!t) return;
    const root = document.documentElement.style;
    TVARS.forEach((v, k) => {
      const id = (v === 'accentDim') ? 'accent-dim' : v;
      root.setProperty('--' + id, t[k + 1]);
    });
    try { localStorage.setItem('wfm.theme', String(i)); } catch (e) { /* private mode */ }
    document.querySelectorAll('.theme-item').forEach((el, k) => el.classList.toggle('active', k === i));
    const nameEl = document.getElementById('themeName'); if (nameEl) nameEl.textContent = t[0];
    if (window.PlatChart) PlatChart.redraw();
  };
  window.wfmBuildThemeGrid = function () {
    const grid = document.getElementById('themeGrid'); if (!grid) return;
    grid.innerHTML = window.WFM_THEMES.map((t, i) => `
    <div class="theme-item" data-i="${i}" title="${t[0]}">
      <span class="dots"><i style="background:${t[1]}"></i><i style="background:${t[3]}"></i><i style="background:${t[7]}"></i></span>
      <span class="tname">${t[0]}</span>
    </div>`).join('');
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
