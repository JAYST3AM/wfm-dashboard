"""UI polish pass: navigation on every page, terse copy, motion, and the click sounds.

Jay (2026-09-26): "clean up ui, don't leave anything long winded, make navigation through all
pages easy, add some clean ui vfx. and some calm and satisfying sounds for button clicks."

These are source-level contracts so the properties survive future edits. The behaviour itself is
exercised in the browser (screenshots + the AudioContext probe) during the QA pass.
"""
import json
import os
import re

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGES = ('index.html', 'collection.html', 'cards.html', 'settings.html')
STATIC = os.path.join(REPO, 'static')


def read(name):
    return open(os.path.join(STATIC, name), encoding='utf-8').read()


# --------------------------------------------------------------------------- navigation
@pytest.mark.parametrize('page', PAGES)
def test_every_page_carries_the_full_nav(page):
    html = read(page)
    assert 'id="mainnav"' in html
    nav = html.split('id="mainnav"', 1)[1].split('</nav>', 1)[0]
    assert nav.count('class="navpill') == 5                       # Home/Inventory/Trade/Collection/More
    for frag in ('#home', '#inventory', '#trade', '#more'):        # bare hash on the SPA, /#… elsewhere
        assert re.search(r'href="(?:/)?%s"' % re.escape(frag), nav), (page, frag)
    assert 'href="/collection.html"' in nav
    assert nav.count('navpill active') <= 1                       # one section in focus, max


def test_settings_sits_under_more_with_its_own_subnav():
    html = read('settings.html')
    assert 'mainnav subnav' in html
    sub = html.split('mainnav subnav', 1)[1].split('</nav>', 1)[0]
    assert 'href="/settings.html" class="navpill active" aria-current="page"' in sub
    assert 'href="/#more" class="navpill"' in sub


def test_collection_and_cards_link_both_ways():
    col = read('collection.html')
    cards = read('cards.html')
    assert 'href="/cards.html"' in col
    assert 'href="/collection.html"' in cards


# --------------------------------------------------------------------------- copy
TECHY = ('#', '/', 'http', 'data:', 'url', '.', 'function', 'var(', 'px ', 'cubic-bezier')


def visible_strings(src):
    """Quoted strings a user could read (skips selectors, urls, code)."""
    for m in re.finditer(r"['\"]([^'\"\n]{60,})['\"]", src):
        s = m.group(1)
        if s.startswith(TECHY) or 'function' in s or '{' in s or ';' in s or '\\u25' in s:
            continue
        if re.match(r'^[\w\s.,!?%:;—’“”\'+\-()×·→]+$', s) is None:
            continue
        yield s


@pytest.mark.parametrize('page', PAGES)
def test_no_long_winded_copy_in_the_pages(page):
    for s in visible_strings(read(page)):
        assert len(s) <= 100, (page, len(s), s)


@pytest.mark.parametrize('js', ('app.js', 'home.js', 'cards.js', 'lookup.js', 'settings.js', 'drawer.js'))
def test_no_long_winded_copy_in_the_scripts(js):
    for s in visible_strings(read(js)):
        assert len(s) <= 100, (js, len(s), s)


def test_settings_lead_is_one_line_of_intent():
    html = read('settings.html')
    lead = html.split('class="st-lead', 1)[1].split('</p>', 1)[0]
    words = len(re.sub(r'<[^>]+>', ' ', lead).split())
    assert words <= 22, words


# --------------------------------------------------------------------------- motion (vfx)
def test_style_has_the_polish_animations():
    css = read('style.css')
    for key in ('@keyframes wfm-rise', '@keyframes wfm-sheen', '@keyframes wfm-glow',
                'main > section:not(.hidden)', '.btn:hover { transform', '.navpill.active::after',
                '.dw-scrim { animation'):
        assert key in css, key


def test_reduced_motion_turns_everything_off():
    css = read('style.css')
    block = css.split('@media (prefers-reduced-motion: reduce)', 1)[1]
    assert 'animation-duration: .001ms !important' in block
    assert 'transition-duration: .001ms !important' in block


# --------------------------------------------------------------------------- sound
def test_sfx_is_wired_into_every_page():
    assert os.path.isfile(os.path.join(STATIC, 'sfx.js'))
    for page in PAGES:
        html = read(page)
        assert '<script src="/sfx.js">' in html, page
        assert 'id="soundBtn"' in html, page


def test_sfx_is_generated_not_downloaded():
    js = read('sfx.js')
    assert 'createOscillator' in js and 'createGain' in js
    assert 'lowpass' in js and 'biquadfilter' in js.lower()
    for banned in ('http://', 'https://', 'new Audio(', '.mp3', '.wav', '.ogg', 'fetch('):
        assert banned not in js, banned


def test_sfx_is_calm_and_optional():
    js = read('sfx.js')
    assert "localStorage.getItem(KEY)" in js and "localStorage.setItem(KEY" in js
    assert "KEY = 'wfm_sound'" in js
    assert 'data-sfx' in js                      # per-element opt-out / override
    assert 'aria-pressed' in js                  # the mute button announces its state
    # quiet by design: the GAIN argument of every voice recipe stays at or below 0.06
    recipes = js.split('var RECIPES', 1)[1].split('};', 1)[0]
    gains = []
    for args in re.findall(r'voice\(([^)]*)\)', recipes):
        parts = [p.strip() for p in args.split(',')]
        if len(parts) >= 3:
            try:
                gains.append(float(parts[2]))
            except ValueError:
                pass
    assert gains and max(gains) <= 0.06, gains


def test_sound_button_style_exists():
    css = read('style.css')
    assert '#soundBtn.muted' in css and 'rotate(-28deg)' in css


def test_app_plays_a_cue_when_a_refresh_finishes():
    js = read('app.js')
    assert "sfx.play('done')" in js and "sfx.play('warn')" in js


# --------------------------------------------------------------------------- housekeeping
def test_theme_panel_survives_the_nav_work():
    for page in PAGES:
        html = read(page)
        assert 'id="themePanel"' in html and 'id="themeBtn"' in html, page
