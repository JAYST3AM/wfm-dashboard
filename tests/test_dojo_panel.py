"""Clan Dojo panel: the dojo half of /api/feature/materials + the inventory view's card.

data/dojo_costs.json (rooms with credits + a slug->qty cost map, a slug->needed material map,
a source/scope header and a skipped list) is joined with the owned counts from
data/materials.json by slug: owned 0 when nobody owns the material, short = max(0, needed -
owned) at both levels, and credits is the sum over rooms. A missing or corrupt file leaves the
materials half of the payload alone and answers dojo null with HTTP 200, never a 500.
Fixtures live under tmp_path; the shorts-first ordering runs the shipped comparator under node
when node is installed (skipped otherwise - node is never a hard dependency).
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
    'materials': [
        {'slug': 'alloy_plate', 'name': 'Alloy Plate', 'count': 231709, 'cat': 'resource',
         'dojo_hint': True},
        {'slug': 'ferrite', 'name': 'Ferrite', 'count': 40, 'cat': 'resource', 'dojo_hint': False},
        {'slug': 'orokin_cell', 'name': 'Orokin Cell', 'count': 0, 'cat': 'rare', 'dojo_hint': False},
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
    'tiers': ['ghost', 'shadow', 'storm', 'mountain', 'moon'],
    'tier_totals': {
        'ghost': {'credits': 50000, 'materials': {
            'alloy_plate': {'name': 'Alloy Plate', 'needed': 4000},
            'ferrite': {'name': 'Ferrite', 'needed': 500},
            'argon_crystal': {'name': 'Argon Crystal', 'needed': 2}}},
        'shadow': {'credits': 150000, 'materials': {
            'alloy_plate': {'name': 'Alloy Plate', 'needed': 12000}}},
        'moon': {'credits': 5000000, 'materials': {
            'alloy_plate': {'name': 'Alloy Plate', 'needed': 400000},
            'ferrite': {'name': 'Ferrite', 'needed': 50000}}},
    },
    'room_tiers': {
        'orokin_lab': {'ghost': {'credits': 15000, 'costs': {'alloy_plate': 3000, 'ferrite': 500}},
                       'moon': {'credits': 1500000, 'costs': {'alloy_plate': 300000}}},
        'tenno_lab': {'ghost': {'credits': 35000, 'costs': {'alloy_plate': 1000}},
                      'moon': {'credits': 3500000, 'costs': {'alloy_plate': 100000}}},
    },
    'skipped': [{'name': 'Dojo obstacle course', 'url': 'https://wiki.warframe.com/w/Obstacle_Course',
                 'reason': 'speed test, no material cost listed'}],
}


def read(name):
    with open(os.path.join(STATIC, name), encoding='utf-8') as fh:
        return fh.read()


def put(server_mod, dojo=DOJO, mats=MATS):
    if dojo is not None:
        write_json(os.path.join(server_mod.DATA, 'dojo_costs.json'), dojo)
    if mats is not None:
        write_json(os.path.join(server_mod.DATA, 'materials.json'), mats)


def panels_block():
    """Just the two new cards: from the .invpanels row to the card that follows it."""
    html = read('index.html')
    start = html.index('<div class="invpanels">')
    return html[start:html.index('<div class="card">', start)]


# ------------------------------------------------------------------ endpoint: the dojo object
def test_dojo_header_scope_and_credit_total(server_mod, data_dir):
    put(server_mod)
    d = server_mod.feature_payload('materials')['dojo']

    assert set(d) == {'source', 'fetched_iso', 'scope', 'credits', 'rooms', 'materials',
                      'tiers', 'tier_totals', 'room_tiers', 'skipped'}
    assert d['source'] == 'wiki.warframe.com'
    assert d['fetched_iso'] == DOJO['fetched_iso']
    assert d['scope'] == DOJO['scope']
    assert d['credits'] == 50000                     # 15,000 + 35,000 summed over rooms
    assert d['skipped'] == DOJO['skipped']           # passed through for the notes
    assert [r['slug'] for r in d['rooms']] == ['orokin_lab', 'tenno_lab']


def test_room_rows_carry_their_cost_list_joined_to_owned(server_mod, data_dir):
    put(server_mod)
    rooms = {r['slug']: r for r in server_mod.feature_payload('materials')['dojo']['rooms']}

    lab = rooms['orokin_lab']
    assert set(lab) == {'slug', 'name', 'url', 'credits', 'built', 'note', 'costs'}
    assert lab['name'] == 'Orokin Lab' and lab['credits'] == 15000 and lab['built'] == 1
    assert lab['url'] == DOJO['rooms'][0]['url']
    costs = {c['slug']: c for c in lab['costs']}
    for c in lab['costs']:
        assert set(c) == {'slug', 'name', 'qty', 'owned', 'short'}
    assert costs['alloy_plate'] == {'slug': 'alloy_plate', 'name': 'Alloy Plate',
                                    'qty': 3000, 'owned': 231709, 'short': 0}
    assert costs['ferrite'] == {'slug': 'ferrite', 'name': 'Ferrite',
                                'qty': 500, 'owned': 40, 'short': 460}
    # a room cost whose slug is not a dojo material still joins by slug (owned 0, all short)
    tenno = {c['slug']: c for c in rooms['tenno_lab']['costs']}
    assert tenno['orokin_cell'] == {'slug': 'orokin_cell', 'name': 'Orokin Cell',
                                    'qty': 5, 'owned': 0, 'short': 5}
    # costs are biggest-first so the heavy asks read at the top
    assert [c['qty'] for c in rooms['tenno_lab']['costs']] == [1000, 5, 2]


def test_dojo_materials_short_first_maths_and_unowned_rows(server_mod, data_dir):
    put(server_mod)
    mats = {m['slug']: m for m in server_mod.feature_payload('materials')['dojo']['materials']}

    for m in mats.values():
        assert set(m) == {'slug', 'name', 'needed', 'owned', 'short'}
        assert isinstance(m['needed'], int) and isinstance(m['owned'], int)
        assert isinstance(m['short'], int) and m['short'] >= 0
    assert mats['alloy_plate'] == {'slug': 'alloy_plate', 'name': 'Alloy Plate',
                                   'needed': 4000, 'owned': 231709, 'short': 0}
    assert mats['ferrite'] == {'slug': 'ferrite', 'name': 'Ferrite',
                               'needed': 500, 'owned': 40, 'short': 460}
    # no owned row at all -> owned 0, short = needed
    assert mats['argon_crystal'] == {'slug': 'argon_crystal', 'name': 'Argon Crystal',
                                     'needed': 2, 'owned': 0, 'short': 2}
    # needed figures are the heaviest first (the UI re-sorts shorts-first on top)
    needed = [m['needed'] for m in server_mod.feature_payload('materials')['dojo']['materials']]
    assert needed == sorted(needed, reverse=True)


def test_dojo_materials_all_read_owned_zero_when_nothing_is_owned(server_mod, data_dir):
    put(server_mod, mats=None)                       # materials.json missing entirely
    out = server_mod.feature_payload('materials')

    assert out['count'] == 0 and out['materials'] == []
    for m in out['dojo']['materials']:
        assert m['owned'] == 0 and m['short'] == m['needed']


def test_missing_dojo_file_is_null_not_a_crash(server_mod, data_dir):
    put(server_mod, dojo=None)
    out = server_mod.feature_payload('materials')
    assert out['dojo'] is None and out['count'] == 3


def test_junk_rooms_and_costs_are_skipped(server_mod, data_dir):
    put(server_mod, dojo={
        'source': 'wiki.warframe.com', 'fetched_iso': 'now', 'scope': 'x',
        'rooms': ['nope', {'name': 'no slug'}, {'slug': 'ok', 'name': 'OK', 'credits': 'x',
                                                'costs': {'ferrite': 'many', 'alloy_plate': '3'},
                                                'built': 'y'}],
        'materials': {'ferrite': {'needed': 'lots'}, 'alloy_plate': {'needed': '3'}},
        'skipped': ['nope', {'name': 'kept', 'url': 'u', 'reason': 'r'}],
    })
    d = server_mod.feature_payload('materials')['dojo']

    assert d['credits'] == 0                         # a non-numeric credits reads 0
    assert [r['slug'] for r in d['rooms']] == ['ok']
    room = d['rooms'][0]
    assert room['credits'] == 0 and room['built'] == 0 and room['note'] == ''
    assert [c['slug'] for c in room['costs']] == ['alloy_plate']   # 'many' is dropped
    assert room['costs'][0]['qty'] == 3 and room['costs'][0]['owned'] == 231709
    assert [m['slug'] for m in d['materials']] == ['alloy_plate']
    assert d['skipped'] == [{'name': 'kept', 'url': 'u', 'reason': 'r'}]


# ------------------------------------------------------------------ card markup + JS
def test_dojo_card_markup_and_headers():
    block = panels_block()
    for frag in ('id="dojoCard"', 'id="dojoTitle"', 'id="dojoMeta"', 'id="dojoTbl"',
                 'id="dojoRows"', 'id="dojoRooms"', 'id="dojoRoomsList"', 'id="dojoSrc"'):
        assert frag in block, frag
    head = block.split('id="dojoTbl"', 1)[1].split('</thead>', 1)[0]
    for col in ('>Material</th>', '>Needed</th>', '>Owned</th>', '>Short</th>'):
        assert col in head, col
    assert head.count('</th>') == 4


def test_the_scope_is_a_title_tooltip_not_visible_copy():
    js = read('app.js')
    assert "head.title = D.scope || '';" in js
    assert js.count('D.scope') == 1                 # never rendered as a sentence
    assert 'id="dojoTitle"' in panels_block()


def test_the_head_counts_shout_credits_and_shortages():
    js = read('app.js')
    assert "meta.textContent = `· ${dojoTierLabel(D, TT)} · ${fmt(credits)} cr · ${shortN} short`;" in js
    assert "const shortN = rowsSrc.filter(m => (m.short || 0) > 0).length;" in js
    assert "const TT = (D.tier_totals || {})[state.dojoTier] || null;" in js
    assert "const rowsSrc = TT ? TT.materials : (D.materials || []);" in js   # no column -> ghost


def test_shortages_sort_first_then_needed_desc():
    js = read('app.js')
    assert "const rows = rowsSrc.slice().sort((a, b) => (b.short || 0) - (a.short || 0)" in js


def test_short_colour_rule_accent_above_zero_muted_ok_below():
    js = read('app.js')
    assert "'<span class=\"v\">' + fmt(m.short) + '</span>'" in js       # accent when > 0
    assert "'<span class=\"dim\">ok</span>'" in js                       # muted when 0
    css = read('style.css')
    assert '.v { color: var(--accent); font-weight: 600; }' in css
    assert '.dim { color: var(--muted); }' in css


def test_rooms_breakdown_is_collapsed_by_default_and_filled_by_js():
    block = panels_block()
    assert '<details class="acc sub" id="dojoRooms">' in block           # no open attribute
    assert '<details class="acc sub" id="dojoRooms" open' not in block
    assert '<summary>Rooms' in block
    js = read('app.js')
    assert "rooms.classList.remove('hidden')" in js                      # shown once data lands
    assert "rooms.classList.add('hidden')" in js                         # hidden with no data
    assert '<div class="mrow"><span class="m-name" title="${escHtml(rm.url' in js  # name + credits
    assert 'class="rcosts dim small"' in js                              # its cost list
    assert 'const rmeta = document.getElementById(\'dojoRoomsMeta\');' in js


def test_the_source_url_is_a_short_link():
    block = panels_block()
    assert 'class="movedlink" id="dojoSrc" href="https://wiki.warframe.com"' in block
    assert '>wiki.warframe.com</a>' in block
    js = read('app.js')
    assert "a.href = /^https?:/i.test(D.source) ? D.source : 'https://' + D.source;" in js


def test_empty_state_hides_the_rooms_and_says_so():
    js = read('app.js')
    assert "if (rooms) rooms.classList.add('hidden');" in js
    assert "'<tr><td colspan=\"4\" class=\"dim mat-empty\">No dojo data yet.</td></tr>'" in js


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


def test_dojo_card_copy_is_short_and_its_one_explainer_is_wrapped():
    block = panels_block()
    for s in visible_strings(block):
        assert len(s) <= 100, s
    # the only sentence lives behind the Advanced switch, wrapped in .explain
    note = block.split('id="dojoNote"', 1)[1]
    assert note.startswith(' class="dojo-note dim small explain">'
                           'Short counts what is still missing after your owned materials.</div>')
    bare = re.sub(r'<\w+[^>]*class="[^"]*explain[^"]*"[^>]*>[^<]*</\w+>', '', block)
    for m in re.finditer(r'>([^<>]{61,})<', bare):
        raise AssertionError('long copy outside .explain: ' + m.group(1)[:80])


# ------------------------------------------------------------------ behaviour under node
@pytest.mark.skipif(NODE is None, reason='node is not installed - source pins still run')
def test_shorts_first_order_runs_as_written():
    js = read('app.js')
    cmp = re.search(r"\.sort\(\(a, b\) => \(b\.short \|\| 0\) - \(a\.short \|\| 0\)"
                    r"\s*\|\| \(b\.needed \|\| 0\) - \(a\.needed \|\| 0\)\)", js)
    assert cmp, 'the dojo sort comparator moved - update renderDojo first'

    script = (
        "const rows = [\n"
        "  { slug: 'x', short: 0, needed: 10 },\n"
        "  { slug: 'y', short: 5, needed: 3 },\n"
        "  { slug: 'z', short: 5, needed: 8 },\n"
        "  { slug: 'w', short: 0, needed: 99 } ]\n"
        "  .slice()" + cmp.group(0) + ";\n"
        "console.log(JSON.stringify(rows.map(r => r.slug)));\n"
    )
    proc = subprocess.run([NODE, '-e', script], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr[-500:]
    assert json.loads(proc.stdout) == ['z', 'y', 'w', 'x']   # shortages first, biggest need first

def test_tier_totals_reach_the_page_with_owned_and_short(server_mod, data_dir):
    put(server_mod)
    d = server_mod.feature_payload('materials')['dojo']

    assert d['tiers'] == ['ghost', 'shadow', 'storm', 'mountain', 'moon']
    assert list(d['tier_totals']) == ['ghost', 'shadow', 'moon']      # only what the file lists
    moon = {m['slug']: m for m in d['tier_totals']['moon']['materials']}
    assert moon['alloy_plate'] == {'slug': 'alloy_plate', 'name': 'Alloy Plate',
                                   'needed': 400000, 'owned': 231709, 'short': 168291}
    assert moon['ferrite'] == {'slug': 'ferrite', 'name': 'Ferrite',
                               'needed': 50000, 'owned': 40, 'short': 49960}
    assert d['tier_totals']['moon']['credits'] == 5000000             # verbatim, never scaled here
    assert d['tier_totals']['ghost']['credits'] == 50000
    lab = d['room_tiers']['orokin_lab']
    assert lab['moon']['costs'] == [{'slug': 'alloy_plate', 'name': 'Alloy Plate', 'qty': 300000,
                                     'owned': 231709, 'short': 68291}]
    assert lab['moon']['credits'] == 1500000


def test_junk_tier_blocks_are_dropped_not_guessed(server_mod, data_dir):
    put(server_mod, dojo={'source': 'wiki.warframe.com', 'rooms': [], 'materials': {},
                          'tiers': ['ghost', 'moon', 7],
                          'tier_totals': {'ghost': 'nope', 'moon': {'credits': 'x',
                                                                     'materials': {'ferrite': {'needed': 'lots'}}}},
                          'room_tiers': {'nope': 'x'}})
    d = server_mod.feature_payload('materials')['dojo']

    assert d['tiers'] == ['ghost', 'moon']          # the non-string entry is dropped
    assert d['tier_totals'] == {}                   # junk blocks never become numbers
    assert d['room_tiers'] == {}


def test_the_tier_switch_defaults_to_ghost_and_remembers(server_mod, data_dir):
    js = read('app.js')
    assert "dojoTier: 'ghost'," in js               # shipped default
    assert "localStorage.getItem('wfm.dojoTier')" in js
    assert "localStorage.setItem('wfm.dojoTier', state.dojoTier)" in js
    assert "state.dojoTier = b.dataset.t;" in js
    assert "b.setAttribute('aria-pressed', String(b.dataset.t === on))" in js
    block = panels_block()
    assert 'id="dojoTier"' in block
    for tier in ('ghost', 'shadow', 'storm', 'mountain', 'moon'):
        assert 'data-t="%s"' % tier in block, tier
    assert 'data-t="ghost" title="Ghost clan cost column" aria-pressed="true"' in block


def test_the_tier_label_never_invents_a_column(server_mod, data_dir):
    js = read('app.js')
    assert "if (!TT || tiers.indexOf(state.dojoTier) < 0) return 'ghost clan';" in js
    assert "const on = known ? state.dojoTier : 'ghost';" in js
