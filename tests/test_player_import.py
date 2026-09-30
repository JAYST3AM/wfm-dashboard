"""Player build import (Phase 3) - contract tests.

The fixture is a synthetic AlecaFrame-shaped save in design/_planner/fixtures/ whose ids are
checked against the real catalogue when it is generated, so a rename in the ingested data fails
here loudly instead of silently importing nothing. Everything is offline; nothing reads the real
save and nothing writes outside a temporary cache path.
"""
import io
import json
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from builds import api, data as data_mod, player_import as pi          # noqa: E402
from scripts import player_loadout as pl                                # noqa: E402

FIXTURES = os.path.join(REPO, 'design', '_planner', 'fixtures')
FULL = os.path.join(FIXTURES, 'save-full.json')
EMPTY = os.path.join(FIXTURES, 'save-empty.json')
MALFORMED = os.path.join(FIXTURES, 'save-malformed.json')


@pytest.fixture(scope='module')
def db():
    """The ingested database, when this checkout has one.

    `data/` is gitignored and the CI runner never ingests, so a missing database skips these tests
    rather than failing the job: they are contract tests over the engine's own catalogue, and the
    fixture save only means something against it. Locally (and after `python builds/ingest.py`) they
    all run.
    """
    path = os.environ.get('WFM_BUILD_DB') or os.path.join(REPO, 'data', 'build_data.json')
    if not os.path.exists(path):
        pytest.skip('no ingested database at %s - run: python builds/ingest.py' % path)
    return data_mod.load()


@pytest.fixture()
def needs_db(db):
    """The reader loads the engine database itself, so a save cannot be resolved without one.

    These tests exercise `player_loadout.load()`, not the engine, but the reader's whole job is id
    resolution against the catalogue: without an ingest it raises before the state machine runs, so
    they depend on `db` (which skips) rather than failing the job.
    """
    return db


@pytest.fixture(scope='module')
def imported(db):
    with io.open(FULL, encoding='utf-8') as f:
        save = json.load(f)
    return pi.import_loadout(save, db, source='save-full.json',
                             source_timestamp=1000, imported_timestamp=1000, now=1000)


@pytest.fixture()
def source(tmp_path, monkeypatch):
    """Point the reader at a fixture and its own cache file; never the real save."""
    monkeypatch.setenv(pl.SAVE_ENV, FULL)
    monkeypatch.setenv(pl.CACHE_ENV, str(tmp_path / 'current_loadout.json'))
    return FULL


def category(imported, name):
    assert name in imported['categories'], 'fixture lost the %s import' % name
    return imported['categories'][name]


# ------------------------------------------------------------------ the snapshot

def test_every_equipped_category_is_imported(imported):
    assert set(imported['categories']) == {'warframe', 'primary', 'secondary', 'melee',
                                           'companion', 'companion_weapon'}
    for name, block in imported['categories'].items():
        assert block['category'] == name


def test_identity_is_verified_and_carries_the_catalogue_key(imported):
    primary = category(imported, 'primary')
    assert primary['equipment']['confidence'] == pi.OBSERVED
    value = primary['equipment']['value']
    assert value['uniqueName'] == '/Lotus/Weapons/Tenno/Rifle/BratonPrime'
    assert value['name'] == 'Braton Prime'
    assert value['id'] == value['uniqueName'], 'the planner stores the unique name as the id'


def test_active_config_is_verified(imported):
    frame = category(imported, 'warframe')
    assert frame['config']['confidence'] == pi.OBSERVED
    assert frame['config']['label'] == 'A'
    assert [c['label'] for c in frame['configs']] == ['A', 'B', 'C']


def test_rank_above_the_threshold_is_derived_and_below_it_stays_unknown(imported):
    primary = category(imported, 'primary')
    assert primary['equipment_rank']['value'] == 30
    assert primary['equipment_rank']['confidence'] == pi.DERIVED
    pistol = category(imported, 'secondary')
    assert pistol['equipment_rank']['value'] == 0
    assert pistol['equipment_rank']['confidence'] == pi.DERIVED, 'a recorded zero is a zero'


def test_an_absent_xp_field_is_unknown_not_zero(imported):
    # GPT review: "I cannot derive anything but 0" is not "the rank is 0".
    melee = category(imported, 'melee')
    assert melee['equipment_rank']['value'] is None
    assert melee['equipment_rank']['confidence'] == pi.UNKNOWN
    assert 'no XP' in melee['equipment_rank']['note']
    assert 'equipment_rank' in melee['unknown_fields']


def test_slot_order_polarity_and_ranks_are_preserved(imported):
    frame = category(imported, 'warframe')
    slots = frame['configs'][0]['slots']
    assert [s['save_index'] for s in slots] == [0, 8], 'installed mods and their save positions'
    assert all(s['save_index'] != 10 for s in slots), 'the arcane slot is not one the engine can take'
    assert slots[0]['kind'] == 'normal' and slots[0]['index'] == 0
    assert slots[1]['kind'] == 'aura', 'slot 8 is the aura'
    assert slots[0]['mod']['name'] == 'Vitality' and slots[0]['mod_rank'] == 8
    assert slots[0]['confidence'] == pi.OBSERVED
    assert slots[1]['mod']['name'] == 'Energy Siphon'
    polarities = frame['configs'][0]['polarities']
    assert polarities['confidence'] == pi.OBSERVED
    assert polarities['value'] == {2: 'vazarin', 6: 'madurai'}


def test_polarities_are_only_claimed_for_the_active_config(imported):
    frame = category(imported, 'warframe')
    assert frame['configs'][1]['polarities']['confidence'] == pi.UNKNOWN
    assert frame['configs'][1]['polarities']['value'] == {}


def test_the_engine_cannot_take_slots_are_called_out_not_dropped(imported):
    frame = category(imported, 'warframe')
    unsupported = frame['configs'][0]['unsupported']
    assert unsupported, 'the fixture has an entry the engine has no slot for'
    assert all(u['unsupported'] for u in unsupported), 'every one is named'


def test_unresolvable_identifiers_are_logged_with_where(imported):
    assert imported['unmapped'], 'the fixture has broken ids on purpose'
    wheres = [u['where'] for u in imported['unmapped']]
    assert 'melee.configA.slot8' in wheres
    assert all(u.get('raw') for u in imported['unmapped'])


def test_unknown_fields_are_listed_never_defaulted(imported):
    top = imported['unknown_fields']
    for field in ('catalyst_reactor', 'exilus_unlocked'):
        assert 'warframe.' + field in top, 'the snapshot namespaces what it could not know'
        assert field in imported['categories']['warframe']['unknown_fields']
    assert imported['categories']['warframe']['features_bitmask']['value'] is not None
    assert 'not decoded' in imported['categories']['warframe']['features_bitmask']['note']


def test_freshness_labels_the_source_not_the_import(imported):
    fresh = pi.freshness(1000, 1000, now=1000)
    assert fresh['stale'] is False and 'just now' in fresh['label']
    old = pi.freshness(1000, 1000, now=1000 + 90000)          # 25 hours
    assert old['stale'] is True
    assert old['label'] == 'Last seen 25 hours ago', 'the label stays a label'
    assert old['warning'] == 'Current loadout could not be verified as live.'
    assert pi.freshness(1000, 1000, now=1000 + 200000)['label'] == 'Last seen 2 days ago'
    assert pi.freshness(None)['stale'] is None and pi.freshness(None)['warning'] is None


# ------------------------------------------------------------------ the clone

def test_clone_uses_the_pages_storage_vocabulary(imported):
    out = pi.clone_to_planner(imported, 'warframe', 'A', master=20)
    assert out['ok'] is True
    slots = out['doc']['configs']['A']['slots']
    assert set(slots) == {'normal:0', 'aura'}, 'normal keeps its index, the aura is bare'
    assert slots['normal:0'] == {
        'id': '/Lotus/Upgrades/Mods/Warframe/AvatarHealthMaxMod', 'rank': 8}
    assert out['doc']['configs']['A']['polarities'] == {'normal:2': 'vazarin', 'normal:6': 'madurai'}
    assert out['doc']['configs']['B']['slots'] == {}, 'only the named config is cloned'
    assert out['doc']['version'] == 1 and out['doc']['ui'] == {'trace': None}


def test_clone_never_invents_catalyst_or_exilus(imported):
    out = pi.clone_to_planner(imported, 'warframe', 'A', master=20)
    assert 'orokin' not in out['doc'] and 'exilus_unlocked' not in out['doc']
    assert 'catalyst_reactor' in out['unknown_fields']
    assert 'exilus_unlocked' in out['unknown_fields']


def test_clone_omits_a_rank_it_does_not_know(imported):
    out = pi.clone_to_planner(imported, 'melee', 'A', master=20)
    assert out['doc']['configs']['A']['slots'] == {}, 'the melee fixture has no importable mods'
    assert 'equipment_rank' in out['unknown_fields'], 'an unknown rank is not written as a number'
    out2 = pi.clone_to_planner(imported, 'primary', 'B', master=20)
    assert out2['ok'] and out2['doc']['configs']['B']['slots'], 'config B has its own mods'


def test_clone_does_not_mutate_the_snapshot(imported):
    before = json.dumps(imported, sort_keys=True)
    out = pi.clone_to_planner(imported, 'warframe', 'A', master=20)
    out['doc']['configs']['A']['slots'].clear()
    assert json.dumps(imported, sort_keys=True) == before


def test_clone_refuses_a_config_or_category_that_does_not_exist(imported):
    assert pi.clone_to_planner(imported, 'archwing', 'A')['ok'] is False
    assert pi.clone_to_planner(imported, 'primary', 'Z')['ok'] is False


def test_a_clone_the_engine_accepts_keeps_the_engines_own_numbers(imported, db):
    out = pi.clone_to_planner(imported, 'primary', 'A', master=20)
    slots = []
    for key, entry in out['doc']['configs']['A']['slots'].items():
        kind, _, index = key.partition(':')
        mod = {'id': entry['id']}
        if 'rank' in entry:
            mod['rank'] = entry['rank']
        slots.append({'kind': kind, 'index': int(index) if index else None, 'polarity': None,
                      'mod': mod})
    answer = api.compute({'config': 'A', 'equipment_id': out['doc']['equipment_id'],
                          'orokin': False, 'exilus_unlocked': False, 'mastery_rank': 20,
                          'equipment_rank': out['doc']['equipment_rank'], 'slots': slots}, db)
    assert answer['ok'] is True
    assert not answer['validation']['errors']
    assert answer['result']['stats']['modded_base_damage'] == 92.75, 'Serration R10 on Braton Prime'


# ------------------------------------------------------------------ the reader

def test_the_reader_reports_each_failure_mode_by_name(needs_db, source, monkeypatch):
    payload = pl.load(force=True)
    assert payload['state'] == 'ok' and payload['snapshot']['categories']
    assert payload['cached'] is False

    monkeypatch.setenv(pl.SAVE_ENV, MALFORMED)
    assert pl.load(force=True)['state'] == 'malformed'
    monkeypatch.setenv(pl.SAVE_ENV, EMPTY)
    assert pl.load(force=True)['state'] == 'no_build_data'
    monkeypatch.setenv(pl.SAVE_ENV, str(FIXTURES) + '/does-not-exist.dat')
    payload = pl.load(force=True)
    assert payload['state'] == 'missing' and payload['refreshable'] is False
    assert 'expected' in payload['detail']


def test_a_second_read_inside_the_ttl_is_served_from_the_cache(needs_db, source):
    first = pl.load(force=True)
    second = pl.load()
    assert first['state'] == 'ok' and second['cached'] is True
    assert second['snapshot']['categories'].keys() == first['snapshot']['categories'].keys()
    assert second['snapshot']['freshness']['label'], 'freshness is recomputed for the caller'


def test_the_import_never_writes_to_the_source(needs_db, source):
    before = os.stat(FULL).st_mtime_ns, io.open(FULL, encoding='utf-8').read()
    pl.load(force=True)
    after = os.stat(FULL).st_mtime_ns, io.open(FULL, encoding='utf-8').read()
    assert before == after


def test_the_routes_speak_the_same_state_language(needs_db, source):
    from server import planner_current_clone, planner_current_payload
    payload = planner_current_payload(force=True)
    assert payload['ok'] is True and payload['state'] == 'ok' and payload['error'] is None
    assert set(payload['snapshot']['categories']) == set(pl.load()['snapshot']['categories'])
    clone = planner_current_clone({'category': 'primary', 'config': 'A', 'mastery_rank': 20})
    assert clone['ok'] is True and clone['doc']['equipment_id'].endswith('BratonPrime')
    assert planner_current_clone({'category': 'primary', 'config': 'Q'})['ok'] is False
    assert planner_current_clone({'category': 'archwing'})['ok'] is False
    assert planner_current_clone({})['ok'] is False
