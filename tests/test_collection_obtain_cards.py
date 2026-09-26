"""How-to-obtain hover card on the Collection page.

Jay (2026-09-26): *"in collection, each item ie ash needs to show how to get it."* then
*"change it to a hover over for information on where to get it, and drop chance. and mission"*.

The card is built from `data/obtain_index.json` (WFCD drop tables + wiki notes) by
`collection_log.build_item_obtain` and rendered by `static/collection.js` on hover. These tests
pin the two halves that can silently break: the component->parent attach rule (a drop row must
belong to the item it is shown under) and the hover wiring (a pointer-transparent tooltip that
never blocks the grid).
"""
import json
import os
import re
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

import collection_log as CL  # noqa: E402


# --------------------------------------------------------------------------- fixture index

FIXTURE = {
    'Ash': {'name': 'Ash', 'market': {'plat': 375, 'credits': 35000},
            'wiki': 'https://wiki.warframe.com/w/Ash'},
    'Ash Systems Blueprint': {
        'name': 'Ash Systems Blueprint',
        'missions': [{'planet': 'Venus', 'node': 'Falling Glory', 'mode': 'Skirmish',
                      'rotation': 'A', 'chance': 13.33, 'rarity': 'Uncommon'}],
    },
    'Ash Prime': {'name': 'Ash Prime', 'tradable': True,
                  'wiki': 'https://wiki.warframe.com/w/Ash_Prime'},
    'Ash Prime Systems Blueprint': {
        'name': 'Ash Prime Systems Blueprint',
        'relics': [{'relic': 'Axi A7', 'rarity': 'Rare', 'chance': 2.0, 'vaulted': True}],
    },
    # must NOT attach to 'Ash': 'Prime Chassis Blueprint' is Ash Prime's part, not Ash's
    'Ash Prime Chassis Blueprint': {
        'name': 'Ash Prime Chassis Blueprint',
        'relics': [{'relic': 'Axi B1', 'rarity': 'Uncommon', 'chance': 25.33, 'vaulted': True}],
    },
    'Dagath': {'name': 'Dagath', 'research': True,
               'wiki': 'https://wiki.warframe.com/w/Dagath'},
    'Kuva Bramma': {'name': 'Kuva Bramma', 'tradable': True,
                    'wiki_note': 'is obtained by vanquishing a Kuva Lich who generated with one '
                                 'equipped.',
                    'wiki': 'https://wiki.warframe.com/w/Kuva_Bramma'},
    'Nothing Known': {'name': 'Nothing Known'},
}


def card(name, index=None):
    return CL.build_item_obtain(name, FIXTURE if index is None else index)


# --------------------------------------------------------------------------- attach rules

def test_component_rows_attach_to_their_parent():
    got = card('Ash')
    assert got['parts'] == 1
    labels = [(l['k'], l['part']) for l in got['lines']]
    assert ('mission', 'Systems Blueprint') in labels


def test_another_items_parts_never_attach():
    """'Ash Prime Chassis Blueprint' belongs to Ash Prime - it must not show under Ash."""
    ash = card('Ash')
    assert all('Axi B1' not in (l.get('label') or '') for l in ash['lines'])
    assert all((l.get('part') or '') != 'Prime Chassis Blueprint' for l in ash['lines'])


def test_prime_parts_attach_to_the_prime():
    got = card('Ash Prime')
    parts = {l['part'] for l in got['lines']}
    assert parts == {'Systems Blueprint', 'Chassis Blueprint'}
    assert got['parts'] == 2 and got['complete'] is True
    assert any('vaulted' in ((l.get('label') or '') + (l.get('detail') or '')) for l in got['lines'])


def test_partial_data_is_not_reported_as_complete():
    index = dict(FIXTURE)
    # Ash gains a second, unrecorded part -> the card can no longer claim completeness
    index['Ash Neuroptics Blueprint'] = {'name': 'Ash Neuroptics Blueprint'}
    got = card('Ash', index)
    assert got['complete'] is False


# --------------------------------------------------------------------------- card content

def test_ash_card_carries_mission_and_drop_chance():
    got = card('Ash')
    case = next(l for l in got['lines'] if l['k'] == 'mission')
    assert case['label'] == 'Venus - Falling Glory'
    assert '13.33%' in case['detail']
    assert 'rotation A' in case['detail']
    assert case['part'] == 'Systems Blueprint'


def test_market_line_and_wiki_link_are_exposed():
    got = card('Ash')
    market = next(l for l in got['lines'] if l['k'] == 'market')
    assert '375p' in market['label'] and '35000' in market['label']
    assert got['wiki'] == 'https://wiki.warframe.com/w/Ash'
    assert got['short']


def test_lines_are_ordered_facts_first_and_never_carry_a_wiki_row():
    got = card('Ash')
    kinds = [l['k'] for l in got['lines']]
    assert 'wiki' not in kinds
    assert kinds.index('mission') < kinds.index('market')


def test_wiki_note_is_passed_through_for_quest_items():
    got = card('Kuva Bramma')
    assert 'Kuva Lich' in got['note']
    assert got['short'] == 'See the wiki'          # no drop lanes -> honest fallback headline


def test_dojo_research_is_a_source():
    got = card('Dagath')
    assert any(l['k'] == 'research' for l in got['lines'])


def test_unknown_item_has_no_card():
    assert card('Nothing Known') is None
    assert card('') is None
    assert CL.build_item_obtain('Ash', None) is None


def test_lane_count_is_honest_when_lines_are_capped():
    index = dict(FIXTURE)
    index['Ash Chassis Blueprint'] = {'name': 'Ash Chassis Blueprint', 'missions': [
        {'planet': 'Pluto', 'node': 'Fenton\'s Field', 'mode': 'Skirmish', 'rotation': 'A',
         'chance': 13.33}]}
    got = card('Ash', index)
    assert got['lanes'] == len(got['lines'])
    assert len(got['lines']) <= 10


def test_no_numbers_are_invented():
    """Nothing leaves the card without a source in the index (no guessed drop chances)."""
    got = card('Ash')
    for line in got['lines']:
        assert line['label']
        if line['k'] == 'mission':
            assert line['part'] in ('Systems Blueprint',)


# --------------------------------------------------------------------------- page wiring

def read(path):
    with open(os.path.join(ROOT, path), encoding='utf-8') as fh:
        return fh.read()


def test_tile_keeps_a_handle_on_its_item():
    js = read('static/collection.js')
    assert 'c._cl = it;' in js


def test_hover_wiring_exists_on_the_grid():
    js = read('static/collection.js')
    assert 'function wireObtainTip()' in js
    assert "grid.addEventListener('mouseover'" in js
    assert "grid.addEventListener('mouseout'" in js
    assert "grid.addEventListener('focusin'" in js      # keyboard users get the card too
    assert 'wireObtainTip();' in js                      # ...and it is actually called
    assert 'cl-tip' in js and 'clt-chance' in js and 'clt-main' in js


def test_tooltip_never_blocks_the_grid():
    html = read('static/collection.html')
    block = html[html.index('.cl-tip {'):html.index('</style>', html.index('.cl-tip {'))]
    assert 'pointer-events: none;' in block
    assert re.search(r'\.cl-tip\.on \{[^}]*pointer-events: auto', block) is None


def test_tooltip_has_its_own_stylesheet_block():
    html = read('static/collection.html')
    for rule in ('.cl-tip {', '.clt-head {', '.clt-row {', '.clt-part {', '.clt-src {',
                 '.clt-chance {', '.clt-note {', '.clt-wiki {', '.clt-more {'):
        assert rule in html, rule


def test_hover_copy_stays_short():
    js = read('static/collection.js')
    for text in re.findall(r"el\('[a-z-]+', [^,]+, '([^']{25,})'\)", js):
        assert len(text) <= 100, text


# --------------------------------------------------------------------------- the real index

INDEX_PATH = os.path.join(ROOT, 'data', 'obtain_index.json')


@pytest.mark.skipif(not os.path.exists(INDEX_PATH), reason='obtain_index.json not built')
def test_real_index_covers_the_collection_items():
    index = json.load(open(INDEX_PATH, encoding='utf-8'))['items']
    assert len(index) > 1000
    ash = CL.build_item_obtain('Ash', index)
    assert ash and ash['lines']
    assert any(l['k'] == 'mission' for l in ash['lines'])
    assert any('%' in (l.get('detail') or '') for l in ash['lines'])


@pytest.mark.skipif(not os.path.exists(INDEX_PATH), reason='obtain_index.json not built')
def test_every_collection_item_can_answer_how_to_get_it():
    """Each item shows either drop facts or an explicit 'no drop-table record' wiki note."""
    log_path = os.path.join(ROOT, 'data', 'collection_log.json')
    if not os.path.exists(log_path):
        pytest.skip('collection_log.json not built')
    doc = json.load(open(log_path, encoding='utf-8'))
    items = [r for cat in doc['categories'] for r in cat['items']]
    assert items and all('obtain' in r for r in items)
    with_card = [r for r in items if r.get('obtain')]
    assert len(with_card) / len(items) > 0.9
    for row in with_card:
        card_doc = row['obtain']
        # every card can say something: drop lanes, a wiki note, or at least the wiki page
        assert card_doc.get('lines') or card_doc.get('note') or card_doc.get('wiki')
        for line in card_doc.get('lines') or []:
            assert line.get('label')
