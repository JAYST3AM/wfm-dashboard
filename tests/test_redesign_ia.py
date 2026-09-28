"""Primary IA (stage 2, 2026-09-28): source-level contracts for the six-destination rail.

The site is static, so these are text-level checks on the shipped files:
  * the primary nav is Home / Trade / Inventory / Collection, then Tools / Settings;
  * Mastery is a Collection tab, the Player profile is a Tools workspace, More is the Tools
    launcher - none of the three is a primary destination any more;
  * the legacy hashes still resolve (history/trader -> trade, market/more -> tools,
    player -> tools/player, mastery -> the Collection tab);
  * /lookup.html is a redirect stub and the item detail lives in the shared drawer;
  * global search is backed by the cached /api/catalog payload.
No test reads the repo's data/ folder: the catalogue fixture is built under tmp_path.
"""
import os

from conftest import REPO, rail_rows, shell_decl, shell_js, write_json

STATIC = os.path.join(REPO, 'static')


def read(name):
    with open(os.path.join(STATIC, name), encoding='utf-8') as fh:
        return fh.read()


# ------------------------------------------------------------------ shell: nav + views
def test_index_has_the_six_destination_nav():
    """The rail is shell chrome now: index declares itself the SPA and /shell.js renders the six
    destinations, in this order, with these hrefs (bare hashes on the SPA, /#… on the sub-pages).
    Stage 2 removed the Mastery / Player / More pills - their homes are pinned in
    tests/test_ia_reachability.py."""
    key, _acts = shell_decl('index.html')
    assert key == 'index'
    rows = [(r[0], r[1], r[3]) for r in rail_rows()]
    assert len(rows) == 6, rows
    assert [v for v, _h, _l in rows] == ['home', 'trade', 'inventory', 'collection', 'tools',
                                         'settings']
    assert [(h, l) for _v, h, l in rows] == [('#home', 'Home'), ('#trade', 'Trade'),
                                             ('#inventory', 'Inventory'),
                                             ('/collection.html', 'Collection'),
                                             ('#tools', 'Tools'), ('/settings.html', 'Settings')]
    for gone in ('mastery', 'player', 'more'):
        assert gone not in [v for v, _h, _l in rows], gone + ' must not be a primary pill'
    assert "pg.prefix + p[1]" in shell_js(), 'the sub-pages get the /#… form from the page prefix'


def test_index_has_four_view_sections_and_real_trade_tabs():
    html = read('index.html')
    for view in ('home', 'inventory', 'trade', 'tools'):
        assert 'id="view-%s"' % view in html, view
    for panel in ('tp-sell', 'tp-buy', 'tp-history'):
        assert 'id="%s"' % panel in html, panel
    assert 'id="tradeTabs"' in html and 'role="tab"' in html
    assert 'details class="acc' in html                        # progressive disclosure shells
    # the global-search dropdown is shell chrome: index asks for it, the shell ships it
    key, acts = shell_decl('index.html')
    assert 'search' in acts, 'index declares the header search'
    assert 'id="searchDrop"' in shell_js()


def test_drawer_and_home_scripts_ship_with_the_shell():
    html = read('index.html')
    for asset in ('/drawer.css', '/home.css', '/drawer.js', '/home.js', '/shell.css', '/shell.js'):
        assert asset in html, asset
    # the shell renders the chrome the page scripts bind to, so it loads first (classic script,
    # runs during parse - not deferred); drawer/home define the globals app.js calls
    assert html.index('/shell.js') < html.index('/drawer.js') < html.index('/home.js') < html.index('/app.js')
    assert '<script src="/shell.js"></script>' in html, 'the shell is a plain script, never defer'


def test_app_wires_drawer_search_and_legacy_hashes():
    js = read('app.js')
    assert 'window.wfmOpenItem' in js and 'window.wfmRenderHome' in js
    for alias in ("history: 'trade'", "trader: 'trade'", "market: 'tools'", "more: 'tools'",
                  "player: 'tools'"):
        assert alias in js, alias                               # old bookmarks keep working
    assert "if (v === 'collection' || v === 'cards')" in js    # deep links forward to sub-pages
    assert "'/collection.html#mastery'" in js                  # the old #mastery hash forwards too
    assert "'#tools/player'" in js and "'#tools'" in js        # #player / #more rewrite to Tools
    assert "'/api/catalog'" in js and 'searchDrop' in js       # global lookup is catalogue-backed
    # the old per-row expander is gone: rows open the drawer instead
    assert 'advrow' not in js


def test_inventory_columns_are_progressively_disclosed():
    """Stage 5: the basic columns are the default surface and the advanced ones live behind the
    ONE Columns disclosure in the tablebar (details#invAdv), switched by #btnCols."""
    css = read('style.css')
    assert '.hide-a { display: none; }' in css
    assert 'body.show-a .hide-a' in css
    js = read('app.js')
    assert "classList.toggle('show-a')" in js                  # the "Columns" switch
    assert "btnCols.textContent = on ? 'Hide advanced columns' : 'Show advanced columns';" in js
    html = read('index.html')
    assert "id=\"invQ\"" in html                               # local filter, not the header search
    assert 'id="invAdv"' in html, 'the disclosure control is named'
    adv = html.split('id="invAdv"', 1)[1].split('</details>', 1)[0]
    assert 'id="btnCols"' in adv, 'the switch sits inside its disclosure'
    assert 'aria-controls="tbl"' in adv, 'the switch says which table it drives'


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
