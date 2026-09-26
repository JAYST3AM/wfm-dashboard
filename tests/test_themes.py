"""Themes: 60 Warframe palettes (30 dark + 30 light) and the Dark/Light filter.

Jay 2026-09-26: "with the themes, add a dark/light filter, I want 30x themes of each, and they need
to be warframe themed."

These tests read static/theme.js as data: every palette has 9 colours + a mode, the modes split 30/30,
names are unique and Warframe-flavoured (the generic placeholder names are banned), every palette
passes the contrast floors, and the picker builds a filter that writes/reads localStorage.
"""
import io
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
THEME = os.path.join(ROOT, 'static', 'theme.js')

GENERIC_NAMES = ['Sakura', 'Emerald', 'Mint', 'Cyberpunk', 'Matrix', 'Sunset', 'Deep Ocean',
                 'Lavender', 'Magma', 'Aqua Marine', 'Rose Gold', 'Nebula', 'Paper Light']


def read():
    return io.open(THEME, encoding='utf-8').read()


def palettes():
    """[(name, [9 colours], mode)]"""
    src = read()
    body = src[src.index('window.WFM_THEMES'):src.index('];')]
    out = []
    for m in re.finditer(r"\['([^']+)',([^\]]+)\]", body):
        cols = re.findall(r"#[0-9a-fA-F]{6}", m.group(2))
        mode = re.search(r"'(dark|light)'", m.group(2).rsplit(',', 1)[-1])
        out.append((m.group(1), cols, mode.group(1) if mode else None))
    return out


def rgb(h):
    h = h.lstrip('#')
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


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


def test_sixty_themes_thirty_each():
    rows = palettes()
    assert len(rows) == 60, 'expected 60 palettes, found %d' % len(rows)
    dark = [r for r in rows if r[2] == 'dark']
    light = [r for r in rows if r[2] == 'light']
    assert len(dark) == 30 and len(light) == 30, 'modes: %d dark / %d light' % (len(dark), len(light))


def test_every_palette_has_nine_colours_and_a_mode():
    for name, cols, mode in palettes():
        assert len(cols) == 9, '%s has %d colours' % (name, len(cols))
        assert mode in ('dark', 'light'), '%s has no mode' % name


def test_names_are_unique_and_warframe_flavoured():
    names = [r[0] for r in palettes()]
    assert len(set(names)) == len(names), 'duplicate theme names'
    for bad in GENERIC_NAMES:
        assert bad not in names, 'the generic theme name %r came back' % bad
    for n in names:
        assert len(n) <= 20, 'theme name too long: %r' % n


def test_contrast_floors():
    """text >= 4.5, muted >= 3, accent vs panel >= 3 for every palette."""
    worst = []
    for name, c, mode in palettes():
        bg, panel, text, muted, accent = c[0], c[1], c[4], c[5], c[6]
        t, m, a = contrast(text, bg), contrast(muted, bg), contrast(accent, panel)
        if t < 4.5 or m < 3.0 or a < 3.0:
            worst.append((name, round(t, 2), round(m, 2), round(a, 2)))
    assert not worst, 'palettes below the contrast floor: %s' % worst


def test_light_themes_are_actually_light():
    for name, c, mode in palettes():
        if mode == 'light':
            assert lum(c[0]) > 0.55, '%s bg is not light' % name
            assert lum(c[4]) < 0.25, '%s text is not dark' % name
        else:
            assert lum(c[0]) < 0.25, '%s bg is not dark' % name
            assert lum(c[4]) > 0.6, '%s text is not light' % name


def test_dark_light_filter_is_wired():
    src = read()
    assert "localStorage.setItem('wfm.themeFilter'" in src, 'the filter is not persisted'
    assert "localStorage.getItem('wfm.themeFilter')" in src
    assert "id = 'themeFilter'" in src and 'tp-filter' in src
    for label in ("'All'", "'Dark'", "'Light'"):
        assert label in src, 'missing filter label %s' % label
    assert 'data-mode="' in src, 'grid items do not carry their mode'
    assert 'wfmThemeMode' in src and "'light'" in src and "'dark'" in src
    assert 'themeCss' in src, 'the filter styles must ship with the module'


def test_apply_sets_mode_aware_up_down_tones():
    src = read()
    assert "setProperty('--up'" in src and "setProperty('--down'" in src
    assert "'#15803d'" in src and "'#b91c1c'" in src, 'light-mode gain/loss tones missing'
    assert "'#4ade80'" in src and "'#f87171'" in src, 'dark-mode gain/loss tones missing'


def test_saved_theme_still_applies_by_index():
    src = read()
    assert "localStorage.getItem('wfm.theme')" in src
    assert 'window.wfmApplyTheme(isNaN(saved) ? 0 : saved);' in src
    # the first thirty palettes keep their original order, so a stored index still means the same look
    first = palettes()[0][0]
    assert first == 'Vor Orange', 'palette order changed: first theme is %r' % first
