"""Generate static/theme.js: 30 dark + 30 light Warframe-themed palettes + a mode filter.

Jay 2026-09-26: "with the themes, add a dark/light filter, I want 30x themes of each, and they need
to be warframe themed."

Sources of truth:
- the 30 existing palettes are parsed verbatim out of the current static/theme.js (never retyped),
  renamed where the name was not Warframe-flavoured;
- the 30 new ones are seeded here (name + bg + accent + mode) and their panel/panel2/border/text/
  muted/accentDim/hover are derived so every pair passes the contrast floor the test enforces.

Run:  python tools/gen_themes.py            (rewrites static/theme.js)
      python tools/gen_themes.py --check    (print the contrast table, write nothing)
"""
import argparse
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
THEME_JS = os.path.join(ROOT, 'static', 'theme.js')

# ---------------------------------------------------------------- colour maths
def rgb(h):
    h = h.lstrip('#')
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def hexs(c):
    return '#%02x%02x%02x' % tuple(max(0, min(255, int(round(x)))) for x in c)


def mix(a, b, t):
    """t=0 -> a, t=1 -> b."""
    ca, cb = rgb(a), rgb(b)
    return hexs(tuple(ca[i] + (cb[i] - ca[i]) * t for i in range(3)))


def lum(h):
    def ch(v):
        v /= 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = rgb(h)
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(a, b):
    la, lb = lum(a), lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


# ---------------------------------------------------------------- the existing 30 (parsed verbatim)
RENAMES = {
    'Sakura': 'Duviri Rose',
    'Emerald': 'Cryotic Emerald',
    'Mint': 'Vome Mint',
    'Cyberpunk': 'Zariman Neon',
    'Matrix': 'Cephalon Grid',
    'Sunset': 'Eidolon Sunset',
    'Deep Ocean': 'Uranus Deep',
    'Lavender': 'Lotus Lavender',
    'Magma': 'Fomorian Magma',
    'Aqua Marine': 'Vox Aqua',
    'Rose Gold': 'Ducat Rose',
    'Nebula': 'Sentient Nebula',
    'Paper Light': 'Cephalon White',
    'Frost Light': 'Frost Light',          # already Warframe
}

ROW = re.compile(r"\['([^']+)',\s*('(?:#[0-9a-fA-F]{6})'(?:,\s*)?){9}\]")


def parse_existing(path):
    src = io.open(path, encoding='utf-8').read()
    rows = []
    for m in re.finditer(r"\['([^']+)',([^\]]+)\]", src):
        name = m.group(1)
        cols = re.findall(r"#[0-9a-fA-F]{6}", m.group(2))
        if len(cols) != 9:
            continue
        rows.append([name] + cols)
    return rows


# ---------------------------------------------------------------- the new 30 (28 light + 2 dark)
# (name, bg, accent) - the rest is derived; keep the accents saturated but readable on light bg.
NEW_LIGHT = [
    ('Lua Ivory',           '#f5f3ee', '#8a6d3b'),
    ('Cetus Sand',          '#f6f0e4', '#b45309'),
    ('Ostron Ochre',        '#f7f2e7', '#a16207'),
    ('Solaris Daylight',    '#eef4f8', '#0369a1'),
    ('Corpus Platinum',     '#f2f4f7', '#0e7490'),
    ('Orokin Marble',       '#f7f5ef', '#9a6a05'),
    ('Tenno Dawn',          '#fdf3ec', '#c2410c'),
    ('Deimos Bone',         '#f4f2e9', '#4d7c0f'),
    ('Zariman Alabaster',   '#f4f1fa', '#6d28d9'),
    ('Holdfast Pale',       '#f0f4f8', '#1d4ed8'),
    ('Duviri Chalk',        '#f7f3f7', '#a21caf'),
    ('Necralisk Mist',      '#f1f5f2', '#0f766e'),
    ('Entrati Ivory',       '#f6f1e8', '#92400e'),
    ('Cavia Vermilion',     '#fdf1ee', '#b91c1c'),
    ('Quills Parchment',    '#f7f2e3', '#854d0e'),
    ('Vox Azure',           '#eef6fb', '#0284c7'),
    ('Eidolon Lume',        '#f4f6f9', '#4338ca'),
    ('Cryotic Blue',        '#eff6fb', '#1d4ed8'),
    ('Ducat Beige',         '#f8f4ea', '#b45309'),
    ('Prime Gold Leaf',     '#fbf6e9', '#9a6a05'),
    ('Relic Pale Gold',     '#f9f5ec', '#a16207'),
    ('Sentient Frost',      '#f0f6f6', '#0f766e'),
    ('Infested Bloom',      '#f4f8f0', '#4d7c0f'),
    ('Grineer Sandstone',   '#f6f1e6', '#9a3412'),
    ('Kuva Blush',          '#faf1f2', '#be123c'),
    ('Lotus Blossom',       '#faf1f7', '#a21caf'),
    ('Dax Brass Light',     '#f6f3ea', '#92660a'),
    ('Umbra Silver',        '#f2f3f5', '#334155'),
]
NEW_DARK = [
    ('Umbra Black',         '#08080b', '#e0a92b'),
    ('Nekros Bone',         '#0f0e0c', '#5eead4'),
]


def build_dark(name, bg, accent):
    panel = mix(bg, '#ffffff', 0.055)
    panel2 = mix(bg, '#ffffff', 0.10)
    border = mix(bg, '#ffffff', 0.16)
    text = mix('#f6f7fa', accent, 0.04)
    muted = mix(text, bg, 0.52)
    if contrast(muted, bg) < 3.0:
        muted = mix(text, bg, 0.40)
    if contrast(muted, bg) < 3.0:
        muted = mix(text, bg, 0.25)
    accent_dim = mix(accent, bg, 0.62)
    hover = mix(bg, '#ffffff', 0.075)
    return [name, bg, panel, panel2, border, text, muted, accent, accent_dim, hover]


def build_light(name, bg, accent):
    panel = '#ffffff'
    panel2 = mix(bg, '#ffffff', 0.55)
    border = mix(bg, '#000000', 0.12)
    text = mix('#14120f', accent, 0.05)
    muted = mix(text, bg, 0.45)
    if contrast(muted, bg) < 4.5:
        muted = mix(text, bg, 0.30)
    if contrast(muted, bg) < 4.5:
        muted = mix(text, bg, 0.18)
    accent_dim = mix(accent, bg, 0.70)
    hover = mix(bg, '#000000', 0.045)
    return [name, bg, panel, panel2, border, text, muted, accent, accent_dim, hover]


HEADER = """/* WFM Trader — shared theme module (all pages)

   Palettes: 60 entries of [name, bg, panel, panel2, border, text, muted, accent, accentDim, hover, mode]
   mode is 'dark' or 'light' (index 10). Regenerate with: python tools/gen_themes.py

   Any page that includes this file gets:
   - wfmApplyTheme(i): apply + persist + update .theme-item/#themeName, redraw PlatChart, set --up/--down
   - wfmBuildThemeGrid(): render the picker grid + the Dark/Light filter into #themeGrid
   - wfmInitThemeUI(): bind #themeBtn / #themePanel / #themeGrid
   The saved theme is applied automatically on load, so every page matches. */
"""

FOOTER = """
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
    if (nameEl) nameEl.textContent = t[0] + ' \\u00b7 ' + window.wfmThemeMode(t);
    if (window.PlatChart) PlatChart.redraw();
  };
  function mixGrid(c) { return c; }   // grid lines use the theme border already
  window.wfmThemeFilter = function (mode) {
    try { localStorage.setItem('wfm.themeFilter', mode); } catch (e) { /* private mode */ }
    window.wfmBuildThemeGrid();
  };
  window.wfmBuildThemeGrid = function () {
    const grid = document.getElementById('themeGrid'); if (!grid) return;
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
      return `<div class="theme-item${i === saved ? ' active' : ''}" data-i="${i}" data-mode="${mode}" title="${t[0]} \
\\u00b7 ${mode}">
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
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--check', action='store_true', help='print the contrast table, write nothing')
    args = ap.parse_args()

    existing = parse_existing(THEME_JS)
    if len(existing) != 30:
        print('expected 30 existing palettes, parsed %d' % len(existing))
        return 1

    themes = []
    for row in existing:
        name = RENAMES.get(row[0], row[0])
        mode = 'light' if lum(row[1]) > 0.5 else 'dark'
        themes.append([name] + row[1:] + [mode])

    for name, bg, accent in NEW_DARK:
        themes.append(build_dark(name, bg, accent) + ['dark'])
    for name, bg, accent in NEW_LIGHT:
        themes.append(build_light(name, bg, accent) + ['light'])

    dark = [t for t in themes if t[10] == 'dark']
    light = [t for t in themes if t[10] == 'light']
    print('themes: %d total | dark %d | light %d' % (len(themes), len(dark), len(light)))
    names = [t[0] for t in themes]
    if len(set(names)) != len(names):
        print('DUPLICATE NAMES: %s' % [n for n in names if names.count(n) > 1])
        return 1

    worst = []
    for t in themes:
        name, bg, panel, panel2, border, text, muted, accent, accent_dim, hover, mode = t
        c = dict(text=contrast(text, bg), muted=contrast(muted, bg), accent=contrast(accent, panel),
                 accent_bg=contrast(accent, bg), border=contrast(border, bg), hover=contrast(hover, bg))
        worst.append((name, mode, c))
    bad = [w for w in worst if w[2]['text'] < 4.5 or w[2]['muted'] < 3.0 or w[2]['accent'] < 3.0]
    if args.check or bad:
        for name, mode, c in worst:
            print('%-20s %-5s text %.2f  muted %.2f  accent/panel %.2f  accent/bg %.2f  border %.2f' %
                  (name, mode, c['text'], c['muted'], c['accent'], c['accent_bg'], c['border']))
    if bad:
        print('CONTRAST FAIL: %s' % [(w[0], {k: round(v, 2) for k, v in w[2].items()}) for w in bad])
        return 1
    if args.check:
        return 0

    rows = ',\n'.join(
        "  ['%s', %s, '%s']" % (t[0], ', '.join("'%s'" % c for c in t[1:10]), t[10]) for t in themes)
    body = 'window.WFM_THEMES = [\n%s,\n];\n' % rows
    io.open(THEME_JS, 'w', encoding='utf-8', newline='\r\n').write(HEADER + "'use strict';\r\n" + body + FOOTER)
    print('wrote %s' % THEME_JS)
    return 0


if __name__ == '__main__':
    sys.exit(main())
