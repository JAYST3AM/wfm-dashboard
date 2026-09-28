"""Stage 9 - quick look vs full analysis (Jay's restructure brief, 2026-09-28).

The shared item drawer and item.html used to read as two versions of the same thing. The rule now:

  * the drawer is the QUICK LOOK (summary: recommended action, your copies, the market tiles, three
    collapsed sections) and it carries EXACTLY ONE action into the full analysis page for the same
    item - the footer's 'Open full analysis' link, deep-linking /item.html?item=<slug>;
  * item.html is the ANALYSIS page. It honours that deep link on load (chart, trades and the
    snapshot book render for that slug), still works with no parameter (its own picker), and writes
    nothing - every request on the page is a GET;
  * both surfaces state their role, so a reader can tell summary from analysis without guessing.

Source-level contracts (the browser pass lives in the stage QA scripts, like the rest of the suite).
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# the 18 ip* ids item.html shipped with - stage 9 adds a role line, it takes none away
ITEM_IDS = ('ipTitle', 'ipLead', 'ipPickCard', 'ipPick', 'ipList', 'ipChartCard', 'ipCadence',
            'ipViews', 'ipChart', 'ipTip', 'ipMeta', 'ipHint', 'ipTradesCard', 'ipTradesCount',
            'ipTrades', 'ipStatsCard', 'ipChips', 'ipStats')


def read(rel):
    with open(os.path.join(ROOT, rel), encoding='utf-8') as fh:
        return fh.read()


# ------------------------------------------------------------------ the drawer's one action

def test_drawer_gains_exactly_one_action_into_the_analysis_page():
    js = read('static/drawer.js')
    assert "var ANALYSIS_URL = '/item.html?item='" in js, 'the deep link is declared once'
    assert js.count("'/item.html?item='") == 1, 'one builder, one destination'
    assert "el('a', 'btn primary dw-full', 'Open full analysis \\u2197')" in js, \
        'the action is the footer anchor, labelled Open full analysis'
    assert js.count("dw-full") == 1, 'no second control grew out of it'
    # the drawer builds exactly three anchors: wiki, market, and this one
    assert js.count("el('a', ") == 3, js.count("el('a', ")  # \\u2197 wiki/market + the action


def test_the_action_carries_the_resolved_items_own_slug():
    js = read('static/drawer.js')
    assert "var openSlug = (it && it.slug) ? String(it.slug) : '';" in js
    assert 'fullLink.href = ANALYSIS_URL + encodeURIComponent(openSlug);' in js
    assert "fullLink.classList.toggle('dw-hidden', !openSlug);" in js, \
        'an unknown key with no local record has no analysis page, so the action stands down'


def test_the_analysis_action_is_the_only_primary_control_in_the_drawer():
    """Wiki and Market stay as plain links - the page is the next step, they are references."""
    js = read('static/drawer.js')
    assert js.count("'btn primary") == 1, 'exactly one primary-weight control'
    assert "el('a', 'btn primary dw-full'" in js, 'and it is the analysis action'
    assert "el('a', 'btn dw-wiki'" in js and "el('a', 'btn dw-market'" in js


def test_drawer_footer_states_the_role_next_to_the_path():
    js = read('static/drawer.js')
    assert "el('span', 'dw-role', 'Quick look')" in js
    foot = js.split("var foot = el('footer', 'dw-foot');", 1)[1].split("panel.appendChild(foot);", 1)[0]
    assert 'dw-role' in foot and 'dw-full' in foot, 'role tag and path sit on the same row'
    css = read('static/drawer.css')
    for sel in ('.dw-role', '.dw-full'):
        assert sel in css, sel + ' missing from drawer.css'


def test_drawer_ids_and_hooks_survive():
    js = read('static/drawer.js')
    for hook in ("NAME_ID = 'wfmDrawerName'", "'wfmDwHead-'", "'wfmDwSec-'", "'dw-scrim'",
                 'window.wfmOpenItem = open', 'window.wfmDrawer ='):
        assert hook in js, hook
    # the inline graph link into the page survives untouched (pinned by tests/test_item_page.py)
    assert "'/item.html?slug='" in js and 'Price page' in js


# ------------------------------------------------------------------ the page's deep link

def test_item_page_reads_the_deep_link_first_and_keeps_the_old_form():
    js = read('static/item.js')
    assert "var qs = new URLSearchParams(location.search);" in js
    assert "qs.get('item') || hashQs.get('item') || qs.get('slug')" in js, \
        "?item -> #item= -> the older ?slug=, in that order"
    assert "String(location.hash || '').replace(/^#/, '')" in js, 'the hash form is parsed too'


def test_item_page_and_its_picker_use_the_canonical_link():
    js = read('static/item.js')
    assert 'href="/item.html?item=\' + encodeURIComponent(c.slug)' in js, \
        'picker hits deep-link the same form the drawer writes'
    assert "item.html?slug=" in js, 'the legacy form is still documented for older links'


def test_item_page_still_works_with_no_parameter():
    js = read('static/item.js')
    assert 'function boot(slug) {' in js and 'if (!slug) return pick();' in js
    assert 'function pick() {' in js and "get('/api/catalog')" in js
    html = read('static/item.html')
    assert 'id="ipPickCard"' in html and 'id="ipPick"' in html and 'id="ipList"' in html


def test_item_page_deep_link_renders_the_analysis_cards():
    js = read('static/item.js')
    for call in ("show('ipChartCard', true)", "show('ipStatsCard', true)", 'renderTrades()',
                 'renderChips()', 'renderStats()', 'draw()'):
        assert call in js, call
    assert "get('/api/feature/itemhist?slug=' + encodeURIComponent(SLUG))" in js


def test_item_page_writes_nothing():
    js = read('static/item.js')
    assert re.search(r'\bmethod\s*:', js) is None, 'no request declares a write method'
    assert 'XMLHttpRequest' not in js and 'sendBeacon' not in js
    for word in ('POST', 'PUT', 'DELETE', 'PATCH'):
        assert word not in js, word
    urls = re.findall(r"get\('(/[^']+)'", js)
    assert urls and all(u.startswith('/api/') for u in urls), urls


# ------------------------------------------------------------------ roles stated, ids kept

def test_item_page_states_its_role():
    html = read('static/item.html')
    assert '<p class="ip-role" id="ipRole">' in html
    role = html.split('<p class="ip-role" id="ipRole">', 1)[1].split('</p>', 1)[0]
    assert 'Full analysis' in role, role
    assert 'quick look' in role, 'the page names where the summary lives: ' + role
    assert '.ip-role' in html, 'the role line is styled by the page'


def test_item_page_keeps_every_id_it_had():
    html = read('static/item.html')
    for i in ITEM_IDS:
        assert 'id="%s"' % i in html, i
    assert 'id="ipRole"' in html, 'the role line is the only addition'


def test_drawer_summary_blocks_are_still_all_there():
    """Nothing unique was traded away for the action: the summary, the tiles, the graph and the
    three collapsed sections all still render."""
    js = read('static/drawer.js')
    for keep in ('renderLayer1(', 'renderOwned(', 'renderMarket(', 'renderEstimate(',
                 'renderPriceGraph(', 'renderObtain(', 'renderMarketDetails(', 'renderCollection(',
                 "section('obtain'", "section('market'", "section('collection'"):
        assert keep in js, keep


def test_the_analysis_page_chart_controls_come_from_the_factory():
    """Found while screenshotting the deep link: chart.js only injected its control CSS from Home's
    PlatChart, so item.html's colour dots rendered as raw UA buttons. The factory injects now."""
    js = read('static/chart.js')
    body = js.split('function wfmChart(opts) {', 1)[1].split('\n  }', 1)[0]
    assert 'injectCss();' in body, 'the factory styles its own controls, whoever calls it'
