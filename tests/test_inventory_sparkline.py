"""Inventory Trend column: the slim /api/feature/itemhist series + the sparkline that draws it.

Jay (2026-09-26): a mini price graph per inventory row, and the table itself condensed. The
endpoint answers {"count", "items": {slug: [ask, ...]}} - oldest to newest, at most 48 points,
ints, nulls dropped, thin slugs omitted - and a missing item_history.json must answer
{"count": 0, "items": {}} with HTTP 200 (the route never turns it into a 500).

Mirrors test_redesign_ia.py: no socket is opened and no repo file is read or written - the
fixture item_history.json is built under the server_mod tmp DATA dir.
"""
import os
import re

from conftest import REPO, write_json

STATIC = os.path.join(REPO, 'static')
SLUG = 'primed_continuity'


def read(name):
    with open(os.path.join(STATIC, name), encoding='utf-8') as fh:
        return fh.read()


def points(asks, t0=1700000000, step=900):
    """A source points array: [[ts, ask, bid], ...] oldest -> newest."""
    return [[t0 + i * step, asks[i], None] for i in range(len(asks))]


def history(items):
    return {'schema': 1, 'updated': 1700000000, 'updated_iso': '2023-11-14T22:13:20Z',
            'count': len(items), 'fields': ['ts', 'ask', 'bid'], 'items': items, 'meta': {}}


def put_history(server_mod, items):
    return write_json(os.path.join(server_mod.DATA, 'item_history.json'), history(items))


# ------------------------------------------------------------------ endpoint: shape + trimming
def test_itemhist_is_a_registered_feature(server_mod):
    assert server_mod.FEATURES['itemhist'] == 'item_history.json'
    src = open(os.path.join(REPO, 'server.py'), encoding='utf-8').read()
    assert 'feature_payload(name, parse_qs(urlparse(self.path).query))' in src   # /api/feature/<name>?slug=


def test_payload_is_a_slim_ask_series(server_mod):
    asks = [100 + i for i in range(60)]                # 60 samples: only the newest 48 ship
    put_history(server_mod, {SLUG: {'name': 'Primed Continuity', 'points': points(asks)}})
    out = server_mod.feature_payload('itemhist')
    assert set(out) == {'count', 'items'}              # no pts/sales/src/meta in the payload
    assert out == {'count': 1, 'items': {SLUG: asks[-48:]}}
    assert all(isinstance(v, int) for v in out['items'][SLUG])


def test_nulls_drop_and_thin_slugs_are_omitted(server_mod):
    put_history(server_mod, {
        SLUG: {'name': 'Primed Continuity', 'points': points([10.4, None, 12.6, None, 9.0])},
        'two_points': {'name': 'Two', 'points': points([5.4, 6.6])},
        'one_point': {'name': 'One', 'points': points([None, 7.2, None])},
        'no_points': {'name': 'None', 'points': []},
    })
    out = server_mod.feature_payload('itemhist')
    assert out['items'] == {SLUG: [10, 13, 9], 'two_points': [5, 7]}   # nulls out, ints in
    assert out['count'] == len(out['items']) == 2                      # 1-point slugs dropped


def test_junk_points_do_not_break_the_projection(server_mod):
    put_history(server_mod, {
        SLUG: {'points': points([8.0, 9.0]) + ['nonsense', None, 1234]},
        'not_a_dict': ['8.0', '9.0'],
    })
    assert server_mod.feature_payload('itemhist') == {'count': 1, 'items': {SLUG: [8, 9]}}


def test_missing_file_answers_count_zero_never_500(server_mod):
    action = os.path.join(server_mod.DATA, 'item_history.json')
    assert not os.path.exists(action)                  # nothing written in this test
    assert server_mod.feature_payload('itemhist') == {'count': 0, 'items': {}}


def test_corrupt_file_also_answers_empty(server_mod):
    with open(os.path.join(server_mod.DATA, 'item_history.json'), 'w', encoding='utf-8') as fh:
        fh.write('{ not json')
    assert server_mod.feature_payload('itemhist') == {'count': 0, 'items': {}}


# ------------------------------------------------------------------ index.html: the column
def test_index_puts_the_trend_header_just_before_value():
    html = read('index.html')
    before = html.split('<th data-k="value"', 1)[0]
    assert before.rstrip().endswith('>Trend</th>')     # immediately before the Value header
    trend_th = before.rsplit('<th', 1)[1]
    assert 'scope="col"' in trend_th


# ------------------------------------------------------------------ app.js: cell + fetch + helper
def test_app_renders_a_spark_cell_between_price_and_value():
    js = read('app.js')
    assert js.index('<td class="spark">') < js.index('<td class="num v">')   # cell order = header
    assert 'colspan="14"' in js and 'colspan="13"' not in js                 # Trend adds a column


def test_sparkline_helper_is_a_bare_svg_path():
    js = read('app.js')
    fn = js.split('function sparkline(vals) {', 1)[1].split('\n}', 1)[0]
    for frag in ('viewBox="0 0 62 18"', '<path d="M', 'fill="none"', 'stroke="currentColor"',
                 'stroke-width="1.5"', 'vector-effect="non-scaling-stroke"'):
        assert frag in fn, frag
    assert fn.count('<path') == 1                      # a single path: no axes, no line joins
    for junk in ('<text', '<title', '<circle', '<g '):
        assert junk not in fn, junk
    assert 'vals.length < 2' in fn                     # missing/short series -> '' -> a dash


def test_sparkline_colour_rule_matches_the_table_colours():
    js = read('app.js')
    fn = js.split('function sparkline(vals) {', 1)[1].split('\n}', 1)[0]
    assert "'upl'" in fn and "'downl'" in fn and "'dim'" in fn
    assert 'vals[vals.length - 1] >= vals[0]' in fn    # rising (last >= first) is the gain colour
    css = read('style.css')
    assert '.upl { color: #4ade80; }' in css
    assert '.downl { color: #f87171; }' in css
    assert '.dim { color: var(--muted); }' in css


def test_itemhist_is_fetched_once_per_page_load_into_state():
    js = read('app.js')
    assert js.count("'/api/feature/itemhist'") == 1    # one fetch, never one per row
    assert 'itemhist: {}' in js                        # state carries it before the first render
    assert js.count('state.itemhist') >= 2             # written by load(), read by the row
    block = js.rsplit('FEAT = {};', 1)[1].split('renderChips()', 1)[0]
    assert 'Promise.all(' in block and "'/api/feature/itemhist'" in block
    assert 'state.itemhist = (j && j.items) || {};' in block
    assert '.catch(() => { state.itemhist = {}; })' in block   # a dead endpoint can't break it


def test_rows_read_the_series_from_state_and_blank_to_a_dash():
    js = read('app.js')
    cell = js.split('<td class="spark">', 1)[1].split('</td>', 1)[0]
    assert 'sparkline(state.itemhist[r.slug])' in cell
    assert cell.count("'<span class=\"dim\">-</span>'") == 2   # both the no-state and empty paths
    assert '<td class="spark">-</td>' not in js                # never a bare dash cell


# ------------------------------------------------------------------ style.css: cell + density
def test_css_styles_the_spark_cell():
    css = read('style.css')
    assert 'td.spark { width: 62px; }' in css
    assert 'td.spark svg { display: block; width: 62px; height: 18px; pointer-events: none; }' in css


def test_css_condenses_the_inventory_rows():
    css = read('style.css')
    row = re.search(r'\.inv-row td \{ padding: ([0-9.]+)px ([0-9.]+)px; font-size: ([0-9.]+)px; \}', css)
    assert row, 'the condensed .inv-row td rule is missing'
    pad_v, pad_h, size = (float(x) for x in row.groups())
    base_v = float(re.search(r'tbody td \{ padding: ([0-9.]+)px', css).group(1))
    assert pad_v < base_v                              # denser than the generic table rows
    assert pad_v + pad_v <= 7                          # 7px of vertical padding per row
    assert size <= 12 and pad_h <= 12                  # smaller type, tighter gutters
    assert 'td.num, th.num { text-align: right;' in css        # right-alignment kept
    assert 'tr.inv-row:hover { background: var(--hover); }' in css   # hover/click kept
    assert 'tr.inv-row { cursor: pointer; }' in css
