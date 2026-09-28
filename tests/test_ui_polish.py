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

from conftest import rail_rows, read_static, shell_css, shell_css_all, shell_decl, shell_js

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGES = ('index.html', 'collection.html', 'cards.html', 'settings.html')
STATIC = os.path.join(REPO, 'static')


def read(name):
    return open(os.path.join(STATIC, name), encoding='utf-8').read()


# --------------------------------------------------------------------------- navigation
@pytest.mark.parametrize('page', PAGES)
def test_every_page_carries_the_full_nav(page):
    """The rail lives in /shell.js now (stage 1): a page declares what it is, the shell renders
    the same 7 pills on all of them. Both halves are pinned here - the page's declaration and the
    shell's pill registry (order, href, icon, label), so neither can drift alone."""
    key, _acts = shell_decl(page)
    assert '<script src="/shell.js"></script>' in read(page), page + ' must load the shared shell'
    rows = rail_rows()
    assert [r[0] for r in rows] == ['home', 'inventory', 'trade', 'collection', 'mastery',
                                    'player', 'more']
    assert [r[1] for r in rows] == ['#home', '#inventory', '#trade', '/collection.html', '#mastery',
                                    '#player', '#more']
    assert [r[3] for r in rows] == ['Home', 'Inventory', 'Trade', 'Collection', 'Mastery',
                                    'Player', 'More']
    assert dict((r[0], r[2]) for r in rows)['mastery'] == 'trophy'    # the 7th pill is Mastery
    shell = shell_js()
    assert "class=\"navpill' + (on ? ' active' : '')" in shell, 'exactly the active pill is marked'
    assert 'aria-current="page"' in shell, 'the page you are on announces itself'
    assert "data-v=\"' + v + '\"" in shell, 'every pill keeps its data-v (app.js routes on it)'
    assert 'data-icon="' in shell, 'the rail keeps its icons'


def test_the_shell_rail_marks_the_page_that_owns_it():
    """data-shell decides the active pill: collection.html + cards.html own Collection (Cards is a
    Collection section), settings.html sits under More, item has no pill (it is opened from a row),
    and index follows its own hash the way app.js routes it."""
    shell = shell_js()
    for page, pill in (('collection.html', 'collection'), ('cards.html', 'collection'),
                       ('settings.html', 'more'), ('item.html', '')):
        key, _acts = shell_decl(page)
        row = re.search(r'%s: \{(.*?)\n    \},' % key, shell, re.S)
        assert row, 'no shell entry for ' + key
        assert "active: '%s'" % pill in row.group(1), (page, pill)
    # Cards is not a pill of its own: the Collection section owns it, and the SPA follows its hash
    assert shell_decl('cards.html')[0] == 'cards'
    assert 'hash: true' in re.search(r'index: \{(.*?)\n    \},', shell, re.S).group(1)


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


@pytest.mark.parametrize('js', ('app.js', 'home.js', 'cards.js', 'lookup.js', 'settings.js', 'drawer.js',
                                'shell.js'))
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
    css = shell_css_all()
    for key in ('@keyframes wfm-rise', '@keyframes wfm-sheen', '@keyframes wfm-glow',
                'main > section:not(.hidden)', '.btn:hover { transform', '.navpill.active::after',
                '.dw-scrim { animation'):
        assert key in css, key


def test_reduced_motion_turns_everything_off():
    css = read('style.css') + shell_css()
    block = css.split('@media (prefers-reduced-motion: reduce)', 1)[1]
    assert 'animation-duration: .001ms !important' in block
    assert 'transition-duration: .001ms !important' in block


# --------------------------------------------------------------------------- sound
def test_sfx_is_wired_into_every_page():
    assert os.path.isfile(os.path.join(STATIC, 'sfx.js'))
    for page in PAGES + ('item.html',):
        html = read(page)
        assert '<script src="/sfx.js">' in html, page
        assert '<script src="/shell.js"></script>' in html, page + ' loads the shell'
    # the mute button itself is shell chrome now: one host, every page
    assert 'id="soundBtn"' in shell_js()


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
    css = shell_css()
    assert '#soundBtn.muted' in css and 'rotate(-28deg)' in css


def test_app_plays_a_cue_when_a_refresh_finishes():
    js = read('app.js')
    assert "sfx.play('done')" in js and "sfx.play('warn')" in js


# --------------------------------------------------------------------------- housekeeping
def test_theme_panel_survives_the_nav_work():
    """One theme panel, one source: the shell ships it and every page loads the shell, so a page
    cannot lose the 60-theme picker on its own."""
    shell = shell_js()
    for frag in ('id="themePanel"', 'id="themeBtn"', 'id="themeName"', 'id="themeGrid"'):
        assert frag in shell, frag
    for page in PAGES + ('item.html',):
        assert '/shell.js' in read(page), page
        assert 'id="themePanel"' not in read(page), page + ' must not re-declare the panel'


# --------------------------------------------------------------------------- polish round 2 (2026-09-27)
def test_header_counter_is_labelled_by_its_own_basis():
    """The chip shows owned rows with a live sell price / owned rows - never 'Prices N/M', which read
    as if the price feed had missed rows (it holds a record for every owned slug)."""
    js = read('app.js')
    assert 'Prices <b>' not in js
    chip = js.split('no live quote">Priced ', 1)[1].split('</span>', 1)[0]
    assert chip.startswith('<b>${s.priced ?? 0}/${s.items ?? 0}</b>')     # one basis, one payload
    assert 'owned rows with a live sell price / owned rows' in js        # the how lives in the title


def test_status_line_does_not_call_the_load_clock_data():
    js = read('app.js')
    assert '· checked ${new Date().toLocaleTimeString()}' in js
    assert '· data ${new Date().toLocaleTimeString()}' not in js


def test_phone_media_block_keeps_the_header_compact_and_the_pills_tappable():
    """The header half of the <=560px recipe moved to shell.css with the chrome (stage 1); the
    data-row half is still the page sheet's. Both are pinned, neither file can drop its half."""
    block = shell_css().rsplit('@media (max-width: 560px)', 1)[1]
    assert '.chips { flex: 1 1 auto; min-width: 0; flex-wrap: nowrap; overflow-x: auto;' in block
    pills = block.split('.navpill {', 1)[1].split('}', 1)[0]
    assert 'min-height: 34px' in pills                                  # >= the 32px touch minimum
    assert 'flex: 1 1 calc(33.333% - 4px)' in pills                     # 3 + 3 rows, never 4 + 2
    rows = read('style.css').rsplit('@media (max-width: 560px)', 1)[1]
    for row in ('.plan-head, .prow {', '.log-head, .lrow {', '.srow, .srowhead {', '.dealrow, .dealhead {'):
        assert row in rows, row                                         # data rows fit their card at 390px


def test_numeric_cells_stay_right_aligned_with_tabular_numerals():
    css = read('style.css')
    assert 'td.num, th.num { text-align: right; font-family: var(--mono); font-variant-numeric: tabular-nums; }' in css
    chip = shell_css().split('.chip b {', 1)[1].split('\n', 1)[0]
    assert 'font-variant-numeric: tabular-nums; }' in chip


def test_header_controls_share_one_height_and_cards_one_inset():
    assert 'header .btn, header a.btn { min-height: 32px;' in shell_css()
    assert '.picks { padding: 10px 16px 14px; }' in read('style.css')        # the same 16px inset as .card-head
