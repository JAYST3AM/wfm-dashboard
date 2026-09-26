"""The item price page + the switchable graphs (Jay 2026-09-26).

  "add a mini graph as a column for each row. and when I click on the item it should show a mini
   graph of the price similar to platinum graph on main page, but lives in the info card, add a
   button that links to a page that shows full details on trades, and the main view is the graph.
   also all graphs should have a faster hz tick. and more variations of views ie time, colors ect."

These tests pin: one chart factory used by every graph, the view variants (range / style / colour)
and their persistence, the finer tick rules, the drawer's mini graph with its link to the item page,
and the item page itself (graph first, trades and book beside it, auto refresh).
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(rel):
    with open(os.path.join(ROOT, rel), encoding='utf-8') as fh:
        return fh.read()


# ---------------------------------------------------------------- chart factory

def test_one_factory_draws_every_graph():
    js = read('static/chart.js')
    assert 'window.wfmChart' in js, 'the factory is the public entry point'
    assert 'window.PlatChart' in js, 'the platinum chart keeps its name for app.js'
    assert 'wfmChart({' in js, 'PlatChart is built from the factory, not a second renderer'
    assert js.count('function draw()') == 1, 'exactly one drawing routine'


def test_view_variants_exist_and_persist():
    js = read('static/chart.js')
    for r in ('1h', '6h', '24h', '7d', '30d', 'all'):
        assert "'" + r + "'" in js, 'range ' + r + ' missing'
    for s in ('area', 'line', 'bars', 'steps'):
        assert "'" + s + "'" in js, 'style ' + s + ' missing'
    for p in ('accent', 'green', 'blue', 'violet', 'amber'):
        assert p + ':' in js or "'" + p + "'," in js, 'palette ' + p + ' missing'
    assert 'wfm_chart_v1' in js, 'choices are remembered per chart key'
    assert 'setStyle' in js and 'setPalette' in js and 'setRange' in js
    assert 'buildControls' in js, 'the buttons are built from the same factory'


def test_ticks_are_finer_on_short_ranges():
    js = read('static/chart.js')
    m = re.search(r'clamp\(Math\.round\(\(w - PAD\.l - PAD\.r\) / (\d+)\), (\d+), (\d+)\)', js)
    assert m, 'tick density must scale with the width'
    assert int(m.group(3)) >= 10, 'wide charts get at least 10 ticks'
    assert "pad2(d.getHours()) + ':' + pad2(d.getMinutes())" in js, 'intraday ticks read as clock times'
    assert "month: 'short', day: 'numeric'" in js, 'day ticks for week/month spans'
    assert "String(d.getFullYear()).slice(2)" in js, 'years on long spans'


def test_axis_rules_kept_from_the_home_work():
    js = read('static/chart.js')
    assert 'Math.max(0, y0 - padY)' in js, 'platinum and prices never plot below zero'
    assert 'niceStep' in js, 'round gridline steps'
    assert "toLocaleString('en-AU')" in js, 'thousands separators on the labels'


def test_controls_are_styled_by_the_factory():
    js = read('static/chart.js')
    assert 'chartCss' in js, 'the factory injects its own control styles (no page CSS edits)'
    assert '.chartbtn' in js and 'aria-pressed' in js, 'buttons report their state'
    assert 'chartbtn dot' in js or 'chartbtn.dot' in js, 'colour choices are dots'


def test_markers_and_mini_mode():
    js = read('static/chart.js')
    assert 'setMarkers' in js, 'trade markers supported'
    assert 'mini' in js and 'labels: false' in js.replace('labels = opts.labels !== false && !mini', 'labels: false'), \
        'mini mode draws without axis labels'
    assert "key: 'mini:'" in read('static/drawer.js'), 'the drawer graph is its own chart key'


# ---------------------------------------------------------------- drawer

def test_drawer_has_a_mini_graph_and_links_to_the_price_page():
    js = read('static/drawer.js')
    assert 'function renderPriceGraph' in js
    assert 'wfmChart({' in js, 'the mini graph uses the shared factory'
    assert "mini: true" in js and 'height: 64' in js
    assert "\u00b7" in js or '\\u00b7' in js, 'the footer reports points and span'
    assert "'/item.html?slug='" in js, 'the button links to the item price page'
    assert 'Price page' in js, 'and it says what it does'
    assert 'renderPriceGraph(it)' in js, 'wired into renderAll'
    assert 'histCache' in js, 'one fetch per slug per drawer session'


def test_drawer_css_styles_the_graph():
    css = read('static/drawer.css')
    for sel in ('.dw-graph', '.dw-graph-wrap', '.dw-graph-foot', '.dw-page-link'):
        assert sel in css, sel + ' missing'


# ---------------------------------------------------------------- item page

def test_item_page_shell():
    html = read('static/item.html')
    assert '<canvas id="ipChart">' in html, 'the graph is the main view'
    assert 'id="ipTip"' in html
    assert 'id="ipViews"' in html, 'the view buttons mount'
    assert '/chart.js' in html and '/item.js' in html
    assert '/theme.js' in html and '/sfx.js' in html, 'same chrome as every other page'
    for pill in ('Home', 'Inventory', 'Trade', 'Collection', 'More'):
        assert '>' + pill + '<' in html, 'nav pill ' + pill + ' missing'
    assert 'id="ipTrades"' in html and 'id="ipStats"' in html, 'trade details and the book'
    assert 'id="ipPick"' in html, 'a picker for a bare /item.html'


def test_item_page_reads_the_right_data():
    js = read('static/item.js')
    assert "/api/feature/itemhist?slug=" in js, 'the series comes from the hourly store'
    assert "'/api/items'" in js and "'/api/trades'" in js and "'/api/feature/advisor'" in js
    assert 'REFRESH_MS = 60000' in js, 'the graph refreshes on a fast tick'
    assert 'setInterval' in js and 'setMarkers' in js, 'your own trades show on the graph'
    assert 'wfmChart({' in js and "key: 'item:'" in js, 'per-item chart key keeps its own view'
    assert 'history/items' not in js


def test_item_page_picker_uses_the_catalogue():
    js = read('static/item.js')
    assert "'/api/catalog'" in js
    assert 'item.html?slug=' in js, 'each hit links to its own price page'
    assert 'URLSearchParams' in js and "qs.get('slug')" in js


def test_i18n_of_the_controls_and_numbers():
    """Range buttons read as times, not seconds; fractional snapshot prices are rounded."""
    js = read('static/chart.js')
    assert "(cls === 'ranges') ? it[0] : it[1]" in js, 'range buttons show 1h/6h/..., not the seconds'
    item = read('static/item.js')
    assert 'Math.round(n * 10) / 10' in item, 'medians read 15.1p, not 15.071p'
    assert "class=\"ip-kind' + (x.wrap ? ' wrap' : '')" in item, 'the advisor reasons wrap instead of clipping'
    assert '.ip-kind.wrap' in read('static/item.html')
