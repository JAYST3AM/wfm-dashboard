"""Five-section IA (2026-09-26 redesign): source-level contracts for the new shell.

The site is static, so these are text-level checks on the shipped files:
  * the primary nav is Home / Inventory / Trade / Collection / More;
  * the old five views collapse into four in-page sections + one sub-page nav;
  * the legacy 9-pill hashes still resolve (history/trader -> trade, market -> more);
  * /lookup.html is a redirect stub and the item detail lives in the shared drawer;
  * global search is backed by the cached /api/catalog payload.
No test reads the repo's data/ folder: the catalogue fixture is built under tmp_path.
"""
import os

from conftest import REPO, write_json

STATIC = os.path.join(REPO, 'static')


def read(name):
    with open(os.path.join(STATIC, name), encoding='utf-8') as fh:
        return fh.read()


# ------------------------------------------------------------------ shell: nav + views
def test_index_has_the_five_section_nav():
    html = read('index.html')
    nav = html.split('id="mainnav"', 1)[1].split('</nav>', 1)[0]
    for href, label in (('#home', 'Home'), ('#inventory', 'Inventory'), ('#trade', 'Trade'),
                        ('/collection.html', 'Collection'), ('#more', 'More')):
        assert 'href="%s"' % href in nav, href
        assert '>%s</a>' % label in nav, label
    assert nav.count('class="navpill') == 5


def test_index_has_four_view_sections_and_real_trade_tabs():
    html = read('index.html')
    for view in ('home', 'inventory', 'trade', 'more'):
        assert 'id="view-%s"' % view in html, view
    for panel in ('tp-sell', 'tp-buy', 'tp-history'):
        assert 'id="%s"' % panel in html, panel
    assert 'id="tradeTabs"' in html and 'role="tab"' in html
    assert 'details class="acc"' in html                       # progressive disclosure shells
    assert 'id="searchDrop"' in html                           # global-search dropdown


def test_drawer_and_home_scripts_ship_with_the_shell():
    html = read('index.html')
    for asset in ('/drawer.css', '/home.css', '/drawer.js', '/home.js'):
        assert asset in html, asset
    # drawer/home define the globals app.js calls, so they must load first
    assert html.index('/drawer.js') < html.index('/home.js') < html.index('/app.js')


def test_app_wires_drawer_search_and_legacy_hashes():
    js = read('app.js')
    assert 'window.wfmOpenItem' in js and 'window.wfmRenderHome' in js
    for alias in ("history: 'trade'", "trader: 'trade'", "market: 'more'"):
        assert alias in js, alias                               # old bookmarks keep working
    assert "if (v === 'collection' || v === 'cards')" in js    # deep links forward to sub-pages
    assert "'/api/catalog'" in js and 'searchDrop' in js       # global lookup is catalogue-backed
    # the old per-row expander is gone: rows open the drawer instead
    assert 'advrow' not in js


def test_inventory_columns_are_progressively_disclosed():
    css = read('style.css')
    assert '.hide-a { display: none; }' in css
    assert 'body.show-a .hide-a' in css
    js = read('app.js')
    assert "classList.toggle('show-a')" in js                  # the "All columns" toggle
    assert "id=\"invQ\"" in read('index.html')                 # local filter, not the header search


# ------------------------------------------------------------------ lookup retired
def test_lookup_page_is_a_redirect_stub():
    html = read('lookup.html')
    assert "location.replace('/#search'" in html
    assert 'theme.js' not in html                              # no shell wiring left on the stub
    assert '/lookup.js' not in html


def test_drawer_exposes_the_documented_api():
    js = read('drawer.js')
    assert 'window.wfmOpenItem = open' in js
    assert 'window.wfmDrawer' in js
    assert '/lookup_items.json' in js                          # offline catalogue fallback


def test_home_renders_into_the_shell_and_uses_the_drawer():
    js = read('home.js')
    assert 'window.wfmRenderHome' in js
    assert 'window.wfmOpenItem' in js


# ------------------------------------------------------------------ /api/catalog
def test_catalog_endpoint_slices_slug_name_icon(server_mod):
    write_json(os.path.join(server_mod.DATA, 'wfm_items_v2.json'), {
        'apiVersion': '0.25.0',
        'data': [
            {'slug': 'primed_continuity',
             'i18n': {'en': {'name': 'Primed Continuity', 'icon': 'items/images/en/primed_continuity.png'}}},
            {'slug': 'blind_rage', 'i18n': {'en': {'name': 'Blind Rage'}}},
            {'id': 'no-slug', 'i18n': {'en': {'name': 'ignored'}}},
        ],
        'error': None,
    })
    rows = server_mod.catalog_payload()
    assert [r['slug'] for r in rows] == ['blind_rage', 'primed_continuity']   # name-sorted
    assert rows[0]['name'] == 'Blind Rage' and rows[0]['icon'] == ''
    assert rows[1]['icon'].startswith('items/images/en/')
    assert server_mod.catalog_payload() is rows                # cached, parsed once


def test_catalog_route_is_registered():
    src = open(os.path.join(REPO, 'server.py'), encoding='utf-8').read()
    assert "if p == '/api/catalog': return self._send(200, catalog_payload())" in src
