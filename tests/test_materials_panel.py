"""Materials panel: /api/feature/materials + the inventory view's Materials card.

Two files owned by other tools are joined by slug into one payload:
  data/materials.json  - what you own (slug/name/count/cat/dojo_hint) + category counts
  data/dojo_costs.json - per-room build costs + per-material needed totals for the dojo

Join rules: needed/owned/short are ints, short = max(0, needed - owned) with a floor of 0, a
dojo material nobody owns reads owned 0, and a row that is not dojo reads needed/short null.
Either file missing or corrupt degrades to an empty panel (count 0, materials [], dojo null)
with HTTP 200 - never a 500. No test here reads the repo's real data/: every fixture is built
under tmp_path, and the sort / cap-line behaviour runs the shipped matRowsFiltered() under
node when node is installed (skipped otherwise - node is never a hard dependency).
"""
import json
import os
import re
import shutil
import subprocess

import pytest

from conftest import REPO, write_json

STATIC = os.path.join(REPO, 'static')
NODE = shutil.which('node')

MATS = {
    'schema': 1, 'updated': 1790000000, 'updated_iso': '2026-09-26T00:00:00Z',
    'count': 3, 'fields': ['slug', 'name', 'count', 'cat', 'path', 'pic', 'dojo_hint'],
    'materials': [
        {'slug': 'alloy_plate', 'name': 'Alloy Plate', 'count': 231709, 'cat': 'resource',
         'path': 'Lotus/Types/Items/...', 'pic': None, 'dojo_hint': True},
        {'slug': 'ferrite', 'name': 'Ferrite', 'count': 40, 'cat': 'resource',
         'path': 'x', 'pic': None, 'dojo_hint': False},
        {'slug': 'orokin_cell', 'name': 'Orokin Cell', 'count': 0, 'cat': 'rare',
         'path': 'x', 'pic': None, 'dojo_hint': False},
    ],
    'categories': {'resource': 2, 'rare': 1},
}

DOJO = {
    'schema': 1, 'source': 'wiki.warframe.com', 'fetched': 1790000000,
    'fetched_iso': '2026-09-26T00:05:00Z', 'scope': 'Ghost clan: 2 rooms',
    'rooms': [
        {'slug': 'orokin_lab', 'name': 'Orokin Lab',
         'url': 'https://wiki.warframe.com/w/Orokin_Lab', 'credits': 15000,
         'costs': {'alloy_plate': 3000, 'ferrite': 500}, 'built': 1, 'note': ''},
        {'slug': 'tenno_lab', 'name': 'Tenno Lab',
         'url': 'https://wiki.warframe.com/w/Tenno_Lab', 'credits': 35000,
         'costs': {'alloy_plate': 1000, 'argon_crystal': 2, 'orokin_cell': 5},
         'built': 0, 'note': 'needs a forma'},
    ],
    'materials': {
        'alloy_plate': {'name': 'Alloy Plate', 'needed': 4000},
        'ferrite': {'name': 'Ferrite', 'needed': 500},
        'argon_crystal': {'name': 'Argon Crystal', 'needed': 2},
    },
    'skipped': [{'name': 'Dojo obstacle course', 'url': 'https://wiki.warframe.com/w/Obstacle_Course',
                 'reason': 'speed test, no material cost listed'}],
}


def read(name):
    with open(os.path.join(STATIC, name), encoding='utf-8') as fh:
        return fh.read()


def put(server_mod, mats=MATS, dojo=DOJO):
    if mats is not None:
        write_json(os.path.join(server_mod.DATA, 'materials.json'), mats)
    if dojo is not None:
        write_json(os.path.join(server_mod.DATA, 'dojo_costs.json'), dojo)


def rows_by_slug(out):
    return {r['slug']: r for r in out['materials']}


def inv_block():
    """The inventory <section> of index.html - nothing outside it is touched."""
    html = read('index.html')
    return html.split('id="view-inventory"', 1)[1].split('</section>', 1)[0]


def panels_block():
    """Just the two new cards: from the .invpanels row to the card that follows it."""
    html = read('index.html')
    start = html.index('<div class="invpanels">')
    return html[start:html.index('<div class="card">', start)]


# ------------------------------------------------------------------ endpoint: shape + join
def test_materials_is_a_registered_feature(server_mod):
    assert server_mod.FEATURES['materials'] == 'materials.json'


def test_payload_shape_and_row_join(server_mod, data_dir):
    put(server_mod)
    out = server_mod.feature_payload('materials')

    assert set(out) == {'count', 'updated_iso', 'categories', 'materials', 'dojo'}
    assert out['count'] == len(out['materials']) == 3
    assert out['updated_iso'] == MATS['updated_iso']
    assert out['categories'] == {'resource': 2, 'rare': 1}

    by = rows_by_slug(out)
    assert set(by) == {'alloy_plate', 'ferrite', 'orokin_cell'}
    for r in out['materials']:
        assert set(r) == {'slug', 'name', 'count', 'cat', 'dojo', 'needed', 'short'}
    alloy = by['alloy_plate']
    assert alloy['name'] == 'Alloy Plate' and alloy['count'] == 231709 and alloy['cat'] == 'resource'
    assert alloy['dojo'] is True
    assert alloy['needed'] == 4000
    assert alloy['short'] == 0                     # owned 231,709 covers the 4,000 needed


def test_dojo_flag_comes_from_the_map_or_the_hint(server_mod, data_dir):
    put(server_mod)
    by = rows_by_slug(server_mod.feature_payload('materials'))

    # in dojo_costs.materials -> dojo even though the row's hint is false
    assert by['ferrite']['dojo'] is True and by['ferrite']['needed'] == 500
    assert by['ferrite']['short'] == 460           # 500 - 40 owned
    # hint only (in no room/map) -> dojo, but there is nothing to compute yet
    assert by['orokin_cell']['dojo'] is False
    assert by['orokin_cell']['needed'] is None and by['orokin_cell']['short'] is None


def test_non_dojo_rows_have_null_needed_and_short(server_mod, data_dir):
    put(server_mod, mats=MATS, dojo=None)          # no dojo file at all
    out = server_mod.feature_payload('materials')

    assert out['dojo'] is None
    assert out['count'] == 3                       # the owned table still lists every row
    for r in out['materials']:
        assert r['needed'] is None and r['short'] is None
    # the hint still flags future dojo materials, it just cannot price them yet
    assert rows_by_slug(out)['alloy_plate']['dojo'] is True


def test_short_is_floored_at_zero_and_stays_int(server_mod, data_dir):
    put(server_mod, mats={'materials': [
        {'slug': 'a', 'name': 'A', 'count': 10, 'cat': 'c', 'dojo_hint': False},
        {'slug': 'b', 'name': 'B', 'count': 0, 'cat': 'c', 'dojo_hint': False},
        {'slug': 'c', 'name': 'C', 'count': 5, 'cat': 'c', 'dojo_hint': False},
    ]}, dojo={'materials': {'a': {'name': 'A', 'needed': 10},
                            'b': {'name': 'B', 'needed': 7},
                            'c': {'name': 'C', 'needed': 3}}})
    by = rows_by_slug(server_mod.feature_payload('materials'))

    assert by['a']['short'] == 0                   # needed == owned is still 0, not negative
    assert by['b']['short'] == 7                   # owned 0 -> the whole need is short
    assert by['c']['short'] == 0                   # owned 5 > needed 3 -> floor at 0
    for r in by.values():
        assert isinstance(r['count'], int) and isinstance(r['needed'], int)
        assert isinstance(r['short'], int) and r['short'] >= 0


# ------------------------------------------------------------------ degradation
def test_missing_files_degrade_to_an_empty_panel(server_mod, data_dir):
    out = server_mod.feature_payload('materials')          # nothing on disk

    assert out == {'count': 0, 'updated_iso': '', 'categories': {},
                   'materials': [], 'dojo': None}
    assert isinstance(out, dict)                           # never an exception, so never a 500


def test_corrupt_files_also_degrade(server_mod, data_dir):
    for name in ('materials.json', 'dojo_costs.json'):
        with open(os.path.join(server_mod.DATA, name), 'w', encoding='utf-8') as fh:
            fh.write('{ not json')

    assert server_mod.feature_payload('materials') == {
        'count': 0, 'updated_iso': '', 'categories': {}, 'materials': [], 'dojo': None}

    # a corrupt dojo file must not take the materials list down with it
    put(server_mod, mats=MATS, dojo=None)
    with open(os.path.join(server_mod.DATA, 'dojo_costs.json'), 'w', encoding='utf-8') as fh:
        fh.write('["nonsense"]')
    out = server_mod.feature_payload('materials')
    assert out['count'] == 3 and out['dojo'] is None


def test_a_dojo_file_that_is_not_an_object_is_ignored(server_mod, data_dir):
    put(server_mod, mats=MATS, dojo=None)
    write_json(os.path.join(server_mod.DATA, 'dojo_costs.json'), ['not', 'an', 'object'])
    out = server_mod.feature_payload('materials')
    assert out['dojo'] is None and out['count'] == 3


def test_junk_rows_are_skipped_not_fatal(server_mod, data_dir):
    put(server_mod, mats={'updated_iso': 'now', 'categories': 'nope', 'materials': [
        'not a dict',
        {'name': 'no slug'},
        {'slug': 'good', 'name': 'Good', 'count': '12', 'cat': '', 'dojo_hint': 1},
        {'slug': 'good', 'name': 'Dup', 'count': 99, 'cat': 'x', 'dojo_hint': False},
    ]}, dojo={'materials': {'bad': {'name': 'Bad', 'needed': 'many'}, 'good': {'needed': 20}}})
    out = server_mod.feature_payload('materials')

    assert out['count'] == 1 and out['materials'][0]['slug'] == 'good'
    assert out['materials'][0]['count'] == 12              # a numeric string coerces
    assert out['materials'][0]['dojo'] is True and out['materials'][0]['short'] == 8
    assert out['categories'] == {}                         # wrong type -> {} not a crash


# ------------------------------------------------------------------ card markup + JS
def test_materials_card_is_in_the_inventory_view_beside_the_dojo_card():
    inv = inv_block()
    assert '<div class="invpanels">' in inv
    assert inv.index('id="matCard"') < inv.index('id="dojoCard"')
    block = panels_block()
    for frag in ('id="matCard"', 'id="matMeta"', 'id="matQ"', 'id="matSort"',
                 'id="matTbl"', 'id="matRows"', 'id="matCap"'):
        assert frag in block, frag
    assert 'class="invq"' in block                         # same input convention as invQ


def test_materials_table_headers_are_material_count_category():
    head = panels_block().split('id="matTbl"', 1)[1].split('</thead>', 1)[0]
    for col in ('>Material</th>', '>Count</th>', '>Category</th>'):
        assert col in head, col
    assert head.count('</th>') == 3


def test_search_and_sort_toggle_are_wired():
    js = read('app.js')
    assert "state.matQ = e.target.value.trim(); renderMaterials();" in js
    assert "state.matSort === 'count' ? 'name' : 'count'" in js
    assert "matSort.textContent = 'Sort: ' + (state.matSort === 'count' ? 'Count' : 'Name');" in js
    # the two orders the toggle switches between: count desc, then name asc
    assert "(b.count || 0) - (a.count || 0)" in js
    assert "rs.slice().sort((a, b) => String(a.name || '').localeCompare(String(b.name || '')))" in js


def test_the_personal_dojo_swap_row_and_buttons():
    block = panels_block()
    assert '<div class="matview" id="matView" role="group" aria-label="Materials view">' in block
    assert '<button data-m="personal" aria-pressed="true">Personal</button>' in block
    assert '<button data-m="dojo" aria-pressed="false">Dojo</button>' in block
    assert block.index('id="matView"') < block.index('id="matSort"')   # left of the sort toggle
    css = read('style.css')
    assert '.matview { display: inline-flex;' in css
    assert '.matview button[aria-pressed="true"] { color: var(--accent); border-color: var(--accent); }' in css
    assert 'border: 1px solid var(--border); border-radius: 999px; padding: 3px 11px;' in css


def test_personal_is_the_default_and_the_choice_is_remembered_in_localstorage():
    js = read('app.js')
    assert "matView: 'personal'" in js                                       # shipped default
    assert "if (localStorage.getItem('wfm.matView') === 'dojo') state.matView = 'dojo';" in js
    assert "localStorage.setItem('wfm.matView', state.matView)" in js
    assert "state.matView = b.dataset.m === 'dojo' ? 'dojo' : 'personal';" in js
    assert "b.setAttribute('aria-pressed', String(b.dataset.m === state.matView))" in js
    # flipping the pills re-renders from the payload already in memory - no new fetch
    handler = js.split("matViewRow.addEventListener('click', e => {", 1)[1].split('});', 1)[0]
    assert 'fetch(' not in handler and 'renderMaterials();' in handler


def test_the_dojo_mode_swaps_the_headers_and_rows_in_place():
    js = read('app.js')
    region = js.split('const MAT_HEADS = {', 1)[1].split('function renderDojo() {', 1)[0]
    assert region.count('<table') == 0                        # one table in the DOM, swapped in place
    assert "const dojo = state.matView === 'dojo';" in region
    assert '(dojo ? !!r.dojo : true)' in region               # dojo mode lists only dojo rows
    assert "head.innerHTML = MAT_HEADS[dojo ? 'dojo' : 'personal'];" in region
    assert "${fmt(all.length)} dojo materials${shortN ? ` · ${fmt(shortN)} short` : ''}" in region
    assert "'<span class=\"dim\">ok</span>'" in region        # a 0 shortfall stays muted 'ok'
    # Personal is exactly the table the shipped markup already renders
    static_head = panels_block().split('id="matHead"', 1)[1].split('</tr>', 1)[0]
    for col in ('>Material</th>', '>Count</th>', '>Category</th>'):
        assert col in static_head, col


def test_the_payload_is_fetched_once_from_the_materials_endpoint():
    js = read('app.js')
    assert js.count("'/api/feature/materials'") == 1
    assert 'state.materials = null' in js                  # clean before the first render
    assert 'renderMaterials(); renderDojo();' in js        # both cards refresh together


def test_the_400_row_cap_and_its_line():
    js = read('app.js')
    assert 'const MAT_CAP = 400;' in js
    assert 'rows.slice(0, MAT_CAP)' in js
    assert 'if (cap) cap.textContent = rows.length > MAT_CAP ?' in js


def test_dojo_badge_rides_only_the_dojo_rows_and_counts_use_the_formatter():
    js = read('app.js')
    assert "r.dojo ? ' <span class=\"dojobadge\" title=\"needed for the clan dojo buildout\">DOJO</span>'" in js
    assert '${fmt(r.count)}' in js                         # thousands separators (172,629)
    css = read('style.css')
    assert '.dojobadge {' in css
    assert 'color: var(--accent);' in css.split('.dojobadge {', 1)[1].split('}', 1)[0]
    assert 'var(--accent-dim)' in css.split('.dojobadge {', 1)[1].split('}', 1)[0]


def test_panels_sit_side_by_side_and_stack_under_1040px():
    css = read('style.css')
    row = css.split('.invpanels {', 1)[1].split('}', 1)[0]
    assert 'grid-template-columns: minmax(0, 1fr) minmax(0, 1fr)' in row
    stacked = css.split('@media (max-width: 1040px) {', 1)[1].split('}', 1)[0]
    assert '.invpanels { grid-template-columns: minmax(0, 1fr);' in stacked
    # the condensed rows reuse the inventory density, without becoming clickable rows
    assert '.mat-row td, .dojo-row td { padding: 3.5px 10px; font-size: 12px; }' in css
    assert 'tr.inv-row { cursor: pointer; }' in css        # the inventory table is untouched


# ------------------------------------------------------------------ copy rules
TECHY = ('#', '/', 'http', 'data:', 'url', '.', 'function', 'var(', 'px ', 'cubic-bezier')


def visible_strings(src):
    """Quoted strings a user could read (same rule as tests/test_ui_polish.py)."""
    for m in re.finditer(r"['\"]([^'\"\n]{60,})['\"]", src):
        s = m.group(1)
        if s.startswith(TECHY) or 'function' in s or '{' in s or ';' in s:
            continue
        if re.match(r"^[\w\s.,!?%:;—’“”'+\-()×·→]+$", s) is None:
            continue
        yield s


def test_panel_copy_is_short():
    block = panels_block()
    for s in visible_strings(block):
        assert len(s) <= 100, s
    # a sentence a user reads must sit inside an .explain wrapper (hidden until Advanced)
    bare = re.sub(r'<\w+[^>]*class="[^"]*explain[^"]*"[^>]*>[^<]*</\w+>', '', block)
    for m in re.finditer(r'>([^<>]{61,})<', bare):
        raise AssertionError('long copy outside .explain: ' + m.group(1)[:80])
    for s in visible_strings(read('app.js')):
        assert len(s) <= 100, s


# ------------------------------------------------------------------ behaviour under node
@pytest.mark.skipif(NODE is None, reason='node is not installed - source pins still run')
def test_sort_toggle_orders_the_cap_line_and_the_dojo_swap():
    js = read('app.js')
    fn = js.split('function matRowsFiltered() {', 1)[1].split('\n}', 1)[0]
    heads = re.search(r'const MAT_HEADS = \{.*?\n\};', js, re.S)
    cap = re.search(r"rows\.length > MAT_CAP \? (`[^`]*`) : ''", js)
    assert heads and cap, 'the materials helpers moved - update this test first'

    script = (
        "const state = { matQ: '', matSort: 'count', matView: 'personal', materials: { materials: [\n"
        "  { slug: 'a', name: 'Alpha', count: 5, dojo: false },\n"
        "  { slug: 'b', name: 'Beta', count: 9, dojo: true, needed: 4, short: 0 },\n"
        "  { slug: 'c', name: 'Gamma', count: 1, dojo: true, needed: 4, short: 3 },\n"
        "  { slug: 'd', name: 'Delta', count: 0, dojo: true, needed: null, short: null } ] } };\n"
        "const MAT_CAP = 400;\n" + heads.group(0) + "\n"
        "function matRowsFiltered() {" + fn + "}\n"
        "const byCount = matRowsFiltered().map(r => r.slug);\n"
        "state.matSort = 'name';\n"
        "const byName = matRowsFiltered().map(r => r.slug);\n"
        "state.matQ = 'ga';\n"
        "const filtered = matRowsFiltered().map(r => r.slug);\n"
        "state.matQ = ''; state.matView = 'dojo';\n"
        "const dojoRows = matRowsFiltered().map(r => r.slug);\n"
        "const words = (s) => s.replace(/<[^>]+>/g, ' ').split(' ').filter(w => w.length > 2);\n"
        "const headSets = [words(MAT_HEADS.personal), words(MAT_HEADS.dojo)];\n"
        "let rows = { length: 400 }; const atCap = " + cap.group(0) + ";\n"
        "rows = { length: 401 }; const overCap = " + cap.group(0) + ";\n"
        "console.log(JSON.stringify([byCount, byName, filtered, dojoRows, headSets, atCap, overCap]));\n"
    )
    proc = subprocess.run([NODE, '-e', script], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr[-500:]
    by_count, by_name, filtered, dojo_rows, head_sets, at_cap, over_cap = json.loads(proc.stdout)

    assert by_count == ['b', 'a', 'c', 'd']         # count desc
    assert by_name == ['a', 'b', 'd', 'c']          # name asc
    assert filtered == ['c']                        # the search box filters by name
    assert dojo_rows == ['c', 'b', 'd']             # dojo rows only: shorts first, needed desc
    assert head_sets == [['Material', 'Count', 'Category'],
                         ['Material', 'Needed', 'Owned', 'Short']]
    assert at_cap == ''                             # exactly 400 rows -> no line
    assert over_cap == 'showing 400 of 401'         # truncated -> the line appears
