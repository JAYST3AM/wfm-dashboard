"""Pins the stage-10 contrast fixes: theme-var-driven colours, no literal leaks.

Two defects the gate caught across the 60-theme sweep:
  * .badge.sale painted the literal #4ade80 -> 1.74:1 on light palettes, and the colour survived a
    dark -> light theme switch untouched.
  * .cl-rref painted --accent-dim -> 1.85:1 on dark-red palettes (Kuva Crimson showed
    rgb(127,29,29) on rgb(26,17,20)).
Both now take palette vars (--up / --accent), whose per-theme values tests/test_themes.py keeps
above the readability floor, so every theme stays legible and every switch repaints.
"""
import os
import re

ROOT = os.path.join(os.path.dirname(__file__), '..')
STYLE_CSS = os.path.join(ROOT, 'static', 'style.css')
COLLECTION_HTML = os.path.join(ROOT, 'static', 'collection.html')


def _read(path):
    with open(path, encoding='utf-8') as fh:
        return fh.read()


def _rule(css, selector):
    """The declaration block for an exact selector (first match)."""
    m = re.search(re.escape(selector) + r'\s*\{([^}]*)\}', css)
    return m.group(1) if m else None


def _without_var_fallbacks(css):
    """Drop comments and every var(...) call, so only bare literals are left to look at."""
    css = re.sub(r'/\*.*?\*/', '', css, flags=re.S)
    return re.sub(r'var\([^)]*\)', '', css)


def test_sale_badge_uses_the_palette_up_var():
    css = _read(STYLE_CSS)
    block = _rule(css, '.badge.sale')
    assert block is not None, '.badge.sale rule is gone from static/style.css'
    assert re.search(r'color:\s*var\(--up\b', block), '.badge.sale colour must come from var(--up)'
    assert not re.search(r'#[0-9a-fA-F]{3,8}', _without_var_fallbacks(block)), \
        '.badge.sale must not paint a literal colour (it does not follow the theme)'


def test_relic_ref_cell_uses_the_palette_accent_var():
    html = _read(COLLECTION_HTML)
    block = _rule(html, '.cl-rref')
    assert block is not None, '.cl-rref rule is gone from static/collection.html'
    assert re.search(r'color:\s*var\(--accent\)', block), '.cl-rref colour must come from var(--accent)'
    assert 'accent-dim' not in block, \
        '--accent-dim cannot meet the panel-contrast floor on dark-red palettes (Kuva Crimson)'
    assert not re.search(r'#[0-9a-fA-F]{3,8}', _without_var_fallbacks(block)), \
        '.cl-rref must not paint a literal colour'


def test_gain_literals_survive_only_inside_var_fallbacks():
    """.upl's var(--up, #4ade80) is the repo idiom; a bare gain/loss literal is a theme leak."""
    stripped = _without_var_fallbacks(_read(STYLE_CSS))
    for lit in ('#4ade80', '#4ec97a'):
        assert lit not in stripped, '%s must only appear as a var() fallback, never as a colour' % lit
