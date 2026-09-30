"""Where an item actually is: the acquisition hierarchy (Ash Systems / Railjack regression).

Jay (2026-09-30): the drop table labels a Railjack node `Venus/Falling Glory (Skirmish)`, and the
collection card used to read that as `Venus - Falling Glory`, which sends a player to a Venus Star
Chart node that does not exist.  The answer has to be `Railjack -> Venus Proxima -> Falling Glory`.

The hermetic half of this file runs anywhere: it builds a tiny export (region entries + the English
dictionary) and checks the resolver's rules.  The real-data half needs the game's export cached under
`data/dropdata/export/` (scripts/acquisition_hierarchy.py --fetch) and skips without it, because CI
never has it - the same discipline the player-import tests use.
"""
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

import acquisition_hierarchy as AH  # noqa: E402

EXPORT_DIR = os.path.join(ROOT, 'data', 'dropdata', 'export')
MISSIONS = os.path.join(ROOT, 'data', 'dropdata', 'missionRewards.json')
INDEX = os.path.join(ROOT, 'data', 'obtain_index.json')
STORE = os.path.join(ROOT, 'static', 'collection_log.json')

has_export = os.path.exists(os.path.join(EXPORT_DIR, 'ExportRegions.json'))
has_missions = os.path.exists(MISSIONS)
needs_export = pytest.mark.skipif(not has_export, reason='the game export is not cached')
needs_index = pytest.mark.skipif(not os.path.exists(INDEX), reason='the obtain index is not built')


# --------------------------------------------------------------------- a tiny export to resolve against
def make_export():
    """(regions, dictionary) in the shape the game's export uses, for the rules under test."""
    regions = {
        # a Star Chart Venus node
        'SolNode1': {'name': '/Lotus/Language/Locations/Malva',
                     'missionType': 'MT_SURVIVAL',
                     'systemName': '/Lotus/Language/Locations/Venus',
                     'nodeType': 0},
        # a Railjack Venus Proxima node with the same display name family
        'CrewBattleNode514': {'name': '/Lotus/Language/Locations/CrewBattleNode514',
                              'missionType': 'MT_RAILJACK',
                              'systemName': '/Lotus/Language/Locations/Venus_SPACE',
                              'nodeType': 4},
        # a Star Chart node that shares its name with a Conclave map
        'SolNode2': {'name': '/Lotus/Language/Locations/Cytherean',
                     'missionType': 'MT_TERRITORY',
                     'systemName': '/Lotus/Language/Locations/Venus',
                     'nodeType': 0},
        'PvpNode1': {'name': '/Lotus/Language/Locations/Cytherean',
                     'missionType': 'MT_PVP',
                     'systemName': '/Lotus/Language/Locations/Venus',
                     'nodeType': 0},
    }
    dictionary = {
        '/Lotus/Language/Locations/Malva': 'Malva',
        '/Lotus/Language/Locations/CrewBattleNode514': 'Falling Glory',
        '/Lotus/Language/Locations/Cytherean': 'Cytherean',
        '/Lotus/Language/Locations/Venus': 'Venus',
        '/Lotus/Language/Locations/Venus_SPACE': 'Venus Proxima',
    }
    return regions, dictionary


@pytest.fixture()
def tiny():
    regions, dictionary = make_export()
    index = AH.build_index(regions, dictionary)
    known = AH.known_regions(regions, dictionary)
    return index, known


# --------------------------------------------------------------------- the rules
def test_a_railjack_node_is_placed_in_its_proxima_not_its_planet(tiny):
    index, known = tiny
    rec = AH.resolve('Venus', 'Falling Glory', 'Skirmish', index=index, known=known)
    assert (rec['system'], rec['region'], rec['node']) == ('Railjack', 'Venus Proxima', 'Falling Glory')
    assert AH.label(rec) == 'Railjack \u2192 Venus Proxima \u2192 Falling Glory'


def test_the_drop_table_label_is_kept_as_provenance_only(tiny):
    index, known = tiny
    rec = AH.resolve('Venus', 'Falling Glory', 'Skirmish', index=index, known=known)
    assert rec['drop_table_label'] == 'Venus'
    assert rec['region'] != 'Venus'
    assert rec['label_system'] == 'Star Chart'          # the disagreement is recorded, not hidden


def test_a_star_chart_node_keeps_its_planet(tiny):
    index, known = tiny
    rec = AH.resolve('Venus', 'Malva', 'Survival', index=index, known=known)
    assert (rec['system'], rec['region']) == ('Star Chart', 'Venus')
    assert AH.label(rec) == 'Star Chart \u2192 Venus \u2192 Malva'


def test_a_conclave_map_never_stands_in_for_the_star_chart_node(tiny):
    index, known = tiny
    rec = AH.resolve('Venus', 'Cytherean', 'Interception', index=index, known=known)
    assert rec['system'] == 'Star Chart'


def test_the_reward_table_suffix_is_not_part_of_the_node_name(tiny):
    index, known = tiny
    assert AH.split_key('Falling Glory (Caches)') == ('Falling Glory', 'caches')
    assert AH.split_key('Bifrost Echo (Extra)') == ('Bifrost Echo', 'extra')
    assert AH.split_key('Malva') == ('Malva', None)
    rec = AH.resolve('Venus', 'Falling Glory (Caches)', 'Caches', index=index, known=known)
    assert rec['node'] == 'Falling Glory' and rec['variant'] == 'caches'
    assert AH.reward_source('Caches', variant='caches', system='Railjack') == 'railjack cache'
    assert AH.reward_source('Caches', variant='caches', system='Star Chart') == 'sabotage cache'
    assert AH.reward_source('Skirmish', variant='extra') == 'bonus reward table'


def test_an_unknown_node_keeps_the_verified_part_and_says_what_is_missing(tiny):
    index, known = tiny
    rec = AH.resolve('Venus', 'A Node That Never Existed', 'Survival', index=index, known=known)
    assert rec['system'] == 'Star Chart' and rec['region'] == 'Venus'
    assert rec['unresolved'] == ['node not in the game export (may be retired or renamed)']
    bare = AH.resolve('Nowhere', 'A Node That Never Existed', 'Survival', index={}, known={})
    assert bare['system'] is None and bare['region'] is None and bare['unresolved']


def test_a_region_the_export_does_not_know_is_never_called_the_star_chart():
    regions = {'x': {'name': '/Lotus/Language/TauPrequel/TauRegion',
                     'missionType': 'MT_TAU_WAR',
                     'systemName': '/Lotus/Language/TauPrequel/TauRegion'}}
    dictionary = {'/Lotus/Language/TauPrequel/TauRegion': 'Dark Refractory, Deimos'}
    known = AH.known_regions(regions, dictionary)
    assert known == {'Dark Refractory, Deimos': None}
    rec = AH.resolve('Dark Refractory, Deimos', 'Some Table', 'The Perita Rebellion',
                     index={}, known=known)
    assert rec['system'] is None and rec['region'] == 'Dark Refractory, Deimos'
    assert 'navigation system not confirmed for this region' in rec['unresolved']


# --------------------------------------------------------------------- the real data (skips offline)
@needs_export
def test_the_real_export_places_falling_glory_in_venus_proxima():
    index, _dictionary, known = AH.load_all()
    rec = AH.resolve('Venus', 'Falling Glory', 'Skirmish', index=index, known=known)
    assert (rec['system'], rec['region'], rec['node']) == ('Railjack', 'Venus Proxima', 'Falling Glory')
    assert rec['match'] == 'exact'


@needs_export
def test_the_real_export_knows_the_proxima_names_and_the_star_chart():
    _index, _dictionary, known = AH.load_all()
    assert known.get('Venus Proxima') == 'Railjack'
    assert known.get('Veil Proxima') == 'Railjack'
    assert known.get('Venus') == 'Star Chart'
    assert 'Nowhere' not in known


@needs_export
@needs_index
def test_no_railjack_row_in_the_index_renders_as_its_drop_table_planet():
    with open(INDEX, encoding='utf-8') as fh:
        index = json.load(fh)['items']
    checked = 0
    for name, rec in index.items():
        for row in rec.get('missions') or []:
            if row.get('system') != 'Railjack':
                continue
            checked += 1
            assert '\u2192' in (row.get('hierarchy') or ''), '%s: %r' % (name, row.get('hierarchy'))
            # 'Veil Proxima' is the drop table's label AND the region name: the label named a
            # region, which is correct.  'Venus' is a planet, so region 'Venus' on a Railjack row
            # would be the flattening bug this file exists to catch.
            if not str(row.get('planet') or '').endswith(' Proxima'):
                assert row.get('region') != row.get('planet'), '%s: %r' % (name, row.get('region'))
    assert checked > 100


@needs_index
def test_ash_systems_is_the_railjack_case_end_to_end():
    """The regression the brief names: the hierarchy, and the rotation/chance it must retain."""
    with open(INDEX, encoding='utf-8') as fh:
        index = json.load(fh)['items']
    rows = [r for r in (index.get('Ash Systems Blueprint') or {}).get('missions') or []
            if r.get('node') == 'Falling Glory']
    assert rows, 'Ash Systems Blueprint has no Falling Glory row'
    row = rows[0]
    assert (row['system'], row['region'], row['node']) == ('Railjack', 'Venus Proxima', 'Falling Glory')
    assert row['hierarchy'] == 'Railjack \u2192 Venus Proxima \u2192 Falling Glory'
    assert row['rotation'] == 'A' and row['chance'] == 13.33
    # and the flattened form - the bug - is not what a consumer would render
    assert 'Venus - Falling Glory' != row['hierarchy']
    assert row['provenance']['chance'] and row['provenance']['hierarchy']


@needs_index
def test_the_collection_card_shows_the_hierarchy_not_the_drop_table_label():
    path = STORE if os.path.exists(STORE) else None
    if not path:
        pytest.skip('the collection store is not built')
    with open(path, encoding='utf-8') as fh:
        store = json.load(fh)
    found = []
    for cat in store.get('categories') or []:
        for item in cat.get('items') or []:
            if item.get('name') != 'Ash':
                continue
            for line in ((item.get('obtain') or {}).get('lines') or []):
                if 'Falling Glory' in (line.get('label') or ''):
                    found.append(line)
    assert found, 'the Ash card has no Falling Glory line'
    line = found[0]
    assert line['label'] == 'Railjack \u2192 Venus Proxima \u2192 Falling Glory'
    assert 'rotation A' in line['detail'] and '13.33%' in line['detail']
    assert line['where'] == {'system': 'Railjack', 'region': 'Venus Proxima', 'node': 'Falling Glory'}
