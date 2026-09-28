"""Stage 1 (2026-09-28): ONE shared app shell for every page.

Before this, index/collection/cards/settings/item each hand-declared the same header (brand,
chips, global search, sound, theme button + 60-theme panel, the settings/back link, sync state,
refresh, PNG), the same left rail and their own copy of the 7 pills - five chances to drift.
Now static/shell.js + static/shell.css are the single source and a page only declares what it is:

    <body data-shell="cards" data-shell-actions="">

These are source-level contracts (the behaviour is measured headlessly: rail present with 7 pills,
the right pill active, the panel opens with 60 themes, the sound toggle flips, the search box
answers, no overflow at 1920x1080 / 1366x768, pageOver 0 on every index view). They pin the
properties that make the shell ONE source:

  * every shell page declares data-shell + data-shell-actions and loads /shell.css + /shell.js;
  * no page re-declares the chrome (no <header>, no #mainnav, no #themePanel, no rail <aside>);
  * the shell ships every id the page scripts bind to, and renders them into the same DOM
    position the hand-written markup had (header first in <body>, rail first in .shellbody);
  * the header actions are opt-in per page - a page gets only what it had;
  * shell.css owns the chrome's rules and hardcodes no colour (60 themes, CSS vars only);
  * the pages' own content, sub-navs and footers are untouched.
"""
import os
import re

from conftest import read_static, shell_css, shell_decl, shell_js

SHELL_PAGES = ('index.html', 'collection.html', 'cards.html', 'settings.html', 'item.html')
WANTS_SUBNAV = ('collection.html', 'cards.html', 'settings.html')


# ------------------------------------------------------------------ the declaration

def test_every_shell_page_declares_what_it_is():
    keys = {}
    for page in SHELL_PAGES:
        key, _acts = shell_decl(page)
        assert key == page.replace('.html', ''), page
        keys[key] = page
    assert sorted(keys) == ['cards', 'collection', 'index', 'item', 'settings']


def test_every_shell_page_loads_the_shared_shell_not_its_own_copy():
    for page in SHELL_PAGES:
        html = read_static(page)
        assert '<link rel="stylesheet" href="/shell.css">' in html, page
        assert '<script src="/shell.js"></script>' in html, page
        # shell.css after style.css keeps the moved rules' precedence; shell.js is a plain script
        # (it must run during parse, before the page's own scripts bind their hooks)
        assert html.index('/style.css') < html.index('/shell.css') < html.index('/shell.js'), page
        assert '<script src="/shell.js" defer>' not in html, page


def test_no_page_re_declares_the_chrome():
    """The whole point: header, rail and theme panel exist exactly once, in the shell. A page keeps
    only its own sub-nav pills (collection/cards/settings use the same .navpill class for those)."""
    for page in SHELL_PAGES:
        html = read_static(page)
        for gone in ('<header>', 'id="mainnav"', 'id="themePanel"', 'id="themeBtn"',
                     'id="soundBtn"', 'id="chips"', 'class="brand"', '<aside class="side"',
                     'data-icon="speaker-', 'id="themeGrid"'):
            assert gone not in html, (page, gone)
        assert html.count('class="navpill') <= 2, page + ': only the sub-nav pills may remain'
    shell = shell_js()
    for once in ('<header>', 'id="mainnav"', 'id="themePanel"', 'id="chips"', 'id="themeGrid"'):
        assert shell.count(once) == 1, (once, shell.count(once))


def test_the_shell_renders_every_id_the_page_scripts_bind_to():
    shell = shell_js()
    for frag in ('id="mainnav"', 'id="chips"', 'id="search"', 'id="searchDrop"', 'id="soundBtn"',
                 'id="themeBtn"', 'id="themePanel"', 'id="themeName"', 'id="themeGrid"',
                 'id="syncState"', 'id="refresh"', 'id="btnExportPng"'):
        assert frag in shell, frag
    # the Settings link is contextual (settingsBtn on the SPA, the way back on the sub-pages),
    # so its id rides in the page registry
    assert "id: 'settingsBtn'" in shell and 'pg.link.id' in shell


def test_the_header_actions_are_opt_in_per_page():
    """A page gets the header actions it really had - no more (index), no less (the sub-pages had
    none of them). 'search syncState refresh png' is index's list; the other four are bare."""
    assert shell_decl('index.html')[1] == {'search', 'syncState', 'refresh', 'png'}
    for page in SHELL_PAGES[1:]:
        assert shell_decl(page)[1] == set(), page
    shell = shell_js()
    for flag, frag in (('search', 'id="search"'), ('syncState', 'id="syncState"'),
                       ('refresh', 'id="refresh"'), ('png', 'id="btnExportPng"')):
        assert 'want.%s' % flag in shell, flag
        assert frag in shell, frag


# ------------------------------------------------------------------ the DOM position

def test_the_shell_puts_the_header_and_the_rail_back_where_they_were():
    """The hand-written markup had the header as the first child of <body> (index.html styles
    `body.shell-fit > header`) and the rail as the first child of .shellbody, left of <main> /
    .shellcol. The shell inserts them in exactly those positions."""
    shell = shell_js()
    assert 'body.insertBefore' in shell and 'body.firstChild' in shell
    assert "document.querySelector('.shellbody')" in shell
    assert 'host.insertBefore' in shell and 'host.firstChild' in shell
    assert "'<aside class=\"side\" aria-label=\"Primary\">'" in shell
    assert "'<nav class=\"mainnav sidenav\" id=\"mainnav\" aria-label=\"Primary\">'" in shell


def test_the_shell_never_renders_twice():
    """mount() bails out if the header or the rail is already in the DOM, so a page that also
    loaded the shell twice (or a future inline call) cannot end up with two rails."""
    shell = shell_js()
    assert "document.querySelector('body > header')" in shell
    assert 'never render twice' in shell
    assert "if (document.querySelector('body > header') || document.getElementById('mainnav')) {" in shell


def test_the_shell_completes_the_theme_panel_wiring():
    """The toggle was wired three different ways (app.js, settings.js, collection/cards via
    wfmInitThemeUI) and item.html had no wiring at all - its theme button did nothing. The pages
    that own a richer version keep it (they raise window.wfmThemeUI); the shell finishes the job
    for a page with nothing, and never double-binds a page that already did it."""
    shell = shell_js()
    assert 'function wireThemePanel()' in shell
    assert 'if (window.wfmThemeUI || !window.wfmInitThemeUI) return;' in shell
    assert "document.addEventListener('DOMContentLoaded', wireThemePanel)" in shell
    for js in ('theme.js', 'app.js', 'settings.js'):
        assert 'window.wfmThemeUI = true;' in read_static(js), js
    # item.html ships theme.js but never wired the panel itself - the shell's completion is what
    # gives it the same button behaviour as the other four pages
    item = read_static('item.html')
    assert '/theme.js' in item and 'wfmInitThemeUI' not in item


# ------------------------------------------------------------------ the page keeps its own

def test_the_subnavs_and_footers_stay_in_their_pages():
    for page in WANTS_SUBNAV:
        html = read_static(page)
        assert '<nav class="mainnav subnav"' in html, page
        assert html.index('class="shellcol"') < html.index('class="mainnav subnav"'), page
    assert '<footer class="cl-foot">' in read_static('collection.html')
    assert '<footer class="mcd-foot">' in read_static('cards.html')
    assert '<footer class="st-foot">' in read_static('settings.html')
    assert 'id="foot"' in read_static('index.html')
    assert 'shell.js' in shell_js()          # the shell itself renders no footer


def test_lookup_stays_a_stub_without_the_shell():
    html = read_static('lookup.html')
    assert 'shell.js' not in html and 'shell.css' not in html
    assert "location.replace('/#search'" in html


# ------------------------------------------------------------------ the stylesheet

def test_shell_css_hardcodes_no_colour():
    """60 themes (30 dark + 30 light) are written on :root by theme.js - the chrome must take every
    colour from those vars, so a theme can never leave the shell half-painted."""
    css = shell_css()
    assert not re.search(r'#[0-9a-fA-F]{3,8}\b', css), 'hex colour in shell.css'
    assert not re.search(r'\b(?:rgba?|hsla?)\(', css), 'rgb()/hsl() colour in shell.css'
    for var in ('--panel', '--panel2', '--border', '--text', '--muted', '--accent',
                '--accent-dim', '--hover'):
        assert 'var(%s)' % var in css, var


def test_the_chrome_rules_live_in_shell_css_only():
    """No chrome rule is left behind in style.css, and shell.css carries the real recipe."""
    style = read_static('style.css')
    for moved in (r'^\.theme-panel \{', r'^\.tp-grid \{', r'^\.chip \{', r'^header \{',
                  r'^\.side \{', r'^\.shellbody \{', r'^\.shellcol \{', r'^\.brand \{',
                  r'^\.chips \{', r'^\.mainnav \{', r'^\.navpill \{', r'^#soundBtn\.muted',
                  r'^#syncState'):
        assert not re.search(moved, style, re.M), moved
    css = shell_css()
    for kept in ('header {', '.brand {', '.chips {', '.actions {', '.search {',
                 '.mainnav {', '.navpill {', '.navpill.active', '.side .navpill.active',
                 '.theme-panel {', '.tp-grid {', '.theme-item {', '.shellbody {', '.shellcol {',
                 '@media (max-width: 900px) {', '@media (max-width: 560px) {'):
        assert kept in css, kept
    # the rail's responsive fold (<=900px: the rail becomes a row) and the phone header stay here
    fold = css.split('@media (max-width: 900px)', 1)[1]
    assert '.side .sidenav { flex-direction: row; }' in fold
    phone = css.rsplit('@media (max-width: 560px)', 1)[1]
    assert 'min-height: 34px' in phone
