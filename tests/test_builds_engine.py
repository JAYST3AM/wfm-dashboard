"""The build planner engine (builds/) - contract tests.

Two jobs:
  1. run the engine's own selftests, which check the math against values documented on
     the WARFRAME Wiki (they print PASS/FAIL and return a failure count, so pytest can
     treat them as one test per module);
  2. pin the things a UI or a later phase will depend on: validation codes, the
     unsupported-mechanic registry (no refusal may ship unnamed), the before/after
     comparison, and the data loader's failure mode.

Everything here is offline and builds its own fixtures: no repo data/ directory is
read, no network call is made.
"""
import json
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from builds import api, capacity, data as data_mod, effects, elements, ingest, schema
from builds import trace as trace_mod, unsupported, warframes, weapons

# ------------------------------------------------------------------ fixture data
# WFCD-shaped rows for the fixtures: values are the real ones (Braton Prime 35 damage
# with the 1.75 / 12.25 / 21 split, Excalibur 270/270/240/100) so the expected numbers
# in these tests are the wiki's, not ours.
FIXTURE_MODS = [
    ('/Fixture/Serration', 'Serration', ['+%d%% Damage' % (15 * (i + 1)) for i in range(11)],
     'Primary Mod', 'Rifle', 'madurai', 4),
    ('/Fixture/Hellfire', 'Hellfire', ['+%d%% <DT_FIRE_COLOR>Heat' % (15 * (i + 1))
                                       for i in range(6)],
     'Primary Mod', 'Rifle', 'naramon', 6),
    ('/Fixture/CryoRounds', 'Cryo Rounds', ['+%d%% <DT_FREEZE_COLOR>Cold' % (15 * (i + 1))
                                            for i in range(6)],
     'Primary Mod', 'Rifle', 'naramon', 6),
    ('/Fixture/PointStrike', 'Point Strike', ['+%d%% Critical Chance' % (25 * (i + 1))
                                              for i in range(6)],
     'Primary Mod', 'Rifle', 'madurai', 4),
    ('/Fixture/GalvanizedChamber', 'Galvanized Chamber',
     [['+%.1f%% Multishot' % (7.3 * (i + 1)),
       'On Kill:\\n+%.1f%% Multishot for 20s. Stacks up to 5x.' % (2.7 * (i + 1))]
      for i in range(11)],
     'Primary Mod', 'Rifle', 'madurai', 6),
    ('/Fixture/Vitality', 'Vitality',
     ['+%d%% Health' % round(100 * (i + 1) / 11.0) for i in range(11)],
     'Warframe Mod', 'Warframe', 'vazarin', 2),
    ('/Fixture/AuraRifleAmp', 'Rifle Amp', ['+%d%% Rifle Damage' % (5 * (i + 1))
                                            for i in range(6)],
     'Aura', 'Aura', 'madurai', 4),
    # The catalog's starter copies: same display name, different rank caps (variant). The
    # Beginner copy is renamed to the wiki's "Flawed Serration"; the Expert leftover keeps the
    # plain name and is flagged as a shadow copy.
    ('/Lotus/Upgrades/Mods/Rifle/Beginner/WeaponDamageAmountModBeginner', 'Serration',
     ['+%d%% Damage' % (10 * (i + 1)) for i in range(4)], 'Primary Mod', 'Rifle',
     'madurai', 4),
    ('/Lotus/Upgrades/Mods/Rifle/Expert/WeaponDamageAmountModExpert', 'Serration',
     ['+%d%% Damage' % (15 * (i + 1)) for i in range(11)], 'Primary Mod', 'Rifle',
     'madurai', 6),
]

FIXTURE_EQUIPMENT = [
    ('/Fixture/BratonPrime', 'Braton Prime', schema.EQUIP_PRIMARY, {
        'type': 'Rifle', 'category': 'Primary', 'masteryReq': 8,
        'damage': {'total': 35, 'impact': 1.75, 'puncture': 12.25, 'slash': 21},
        'criticalChance': 0.12, 'criticalMultiplier': 2, 'procChance': 0.26,
        'fireRate': 9.583334, 'multishot': 1, 'magazineSize': 75, 'reloadTime': 2.15,
        'trigger': 'Auto', 'polarities': ['madurai', 'naramon', None, None, None, None,
                                          None, None],
        'exilusPolarity': 'naramon'}),
    ('/Fixture/Excalibur', 'Excalibur', schema.EQUIP_WARFRAME, {
        'type': 'Warframe', 'category': 'Warframes', 'productCategory': 'Suits',
        'masteryReq': 0, 'health': 270, 'shield': 270, 'armor': 240, 'power': 100,
        'sprintSpeed': 1, 'polarities': ['vazarin', 'madurai', None, None, None, None,
                                         None, None, None, None],
        'aura': 'naramon'}),
]


def _mod_row(unique, name, lines, mtype, compat, polarity, drain):
    """One fixture mod. `lines` is either one stat line per rank or, for a rank that
    carries several stats (Galvanized base + rider), a list of lines per rank."""
    per_rank = [entry if isinstance(entry, list) else [entry] for entry in lines]
    return {'uniqueName': unique, 'name': name, 'type': mtype, 'compatName': compat,
            'polarity': polarity, 'baseDrain': drain, 'fusionLimit': len(per_rank) - 1,
            'levelStats': [{'stats': rank_lines} for rank_lines in per_rank]}


@pytest.fixture
def db():
    """A small ingested database built through the real ingest code path."""
    slugs = {'/Fixture/BratonPrime': 'braton_prime', '/Fixture/Excalibur': 'excalibur'}
    src = {'file': 'test-fixture'}
    mods = [ingest.normalise_mod(_mod_row(*row), slugs, src) for row in FIXTURE_MODS]
    equipment = [ingest.normalise_equipment(dict(raw, uniqueName=unique, name=name),
                                            kind, slugs, {}, src)
                 for unique, name, kind, raw in FIXTURE_EQUIPMENT]
    return ingest.build_database(mods, equipment,
                                 {'generated_iso': 'test-fixture',
                                  'game_version': 'test-fixture'})


def _weapon_build(mods=(), **over):
    build = {'config': 'A', 'equipment_id': '/Fixture/BratonPrime', 'equipment_rank': 30,
             'orokin': True, 'mastery_rank': 30, 'slots': []}
    for index, (mod_id, rank) in enumerate(mods):
        build['slots'].append({'kind': 'normal', 'index': index, 'polarity': None,
                               'mod': {'id': mod_id, 'rank': rank}})
    build.update(over)
    return build


def _frame_build(mods=(), **over):
    build = {'config': 'A', 'equipment_id': '/Fixture/Excalibur', 'equipment_rank': 30,
             'orokin': True, 'mastery_rank': 30, 'slots': []}
    for index, (mod_id, rank) in enumerate(mods):
        build['slots'].append({'kind': 'normal', 'index': index, 'polarity': None,
                               'mod': {'id': mod_id, 'rank': rank}})
    build.update(over)
    return build


# ------------------------------------------------------------------ 1. the math
@pytest.mark.parametrize('module', [ingest, effects, capacity, elements, weapons,
                                    warframes],
                         ids=lambda module: module.__name__.split('.')[-1])
def test_module_selftests_pass(module):
    """Each engine module's own wiki-value selftest must pass (prints PASS/FAIL)."""
    assert module.selftest() == 0


def test_weapon_build_end_to_end(db):
    out = api.compute(_weapon_build([('/Fixture/Serration', 10), ('/Fixture/Hellfire', 5),
                                     ('/Fixture/CryoRounds', 5),
                                     ('/Fixture/PointStrike', 5)]), db)
    assert out['ok'], out['validation']
    damage = out['result']['damage']
    assert damage['modded_base_damage'] == 92.75
    assert damage['per_projectile']['blast'] == 166.95
    assert damage['per_projectile_total'] == 259.7
    assert out['result']['stats']['critical_chance'] == 30
    assert out['capacity_used'] == out['capacity']['drain']['total']
    assert out['baseline']['stats']['per_projectile_total'] == 35


def test_frame_build_end_to_end(db):
    out = api.compute(_frame_build([('/Fixture/Vitality', 10)]), db)
    assert out['ok'], out['validation']
    # Excalibur 270 base Health -> 370 at rank 30, x2 with max Vitality (+100%).
    assert out['result']['stats']['health'] == 740
    assert out['result']['stats']['health_ranked'] == 370
    assert out['baseline']['stats']['health'] == 370


def test_trace_answers_why(db):
    out = api.compute(_frame_build([('/Fixture/Vitality', 10)]), db)
    text = api.explain(out, 'health')
    assert 'Vitality' in text and 'Final' in text and '740' in text
    assert trace_mod.text(out['result']['traces']['health']) == text


def test_capacity_is_traced_slot_by_slot(db):
    out = api.compute(_weapon_build([('/Fixture/Serration', 10)]), db)
    rows = out['capacity']['drain']['per_slot']
    assert rows and rows[0]['raw_drain'] == 14 and rows[0]['adjusted_drain'] == 14
    assert out['capacity']['capacity']['total'] == 60


# ------------------------------------------------------------------ 2. validation
@pytest.mark.parametrize('build,expected', [
    (_weapon_build([('/Fixture/Vitality', 10)]), 'incompatible_mod_type'),
    (_weapon_build([('/Fixture/Serration', 10), ('/Fixture/Serration', 10)]),
     'duplicate_mod'),
    (_weapon_build([('/Fixture/Serration', 11)]), 'rank_exceeds_max'),
    (_weapon_build([('/Fixture/Hellfire', 5)],
                   slots=[{'kind': 'aura', 'index': None, 'polarity': None,
                           'mod': {'id': '/Fixture/Hellfire', 'rank': 5}}]),
     'mod_slot_kind_mismatch'),
    (_weapon_build([('/Fixture/DoesNotExist', 5)]), 'unknown_mod'),
    (_weapon_build([('/Fixture/Serration', 10)], equipment_id='/Fixture/Nope'),
     'unknown_equipment'),
    (_weapon_build([], equipment_rank=31), 'invalid_equipment_rank'),
])
def test_validation_codes(db, build, expected):
    out = api.compute(build, db)
    assert out['ok'] is False
    assert expected in {row['code'] for row in out['validation']['errors']}


def test_capacity_exceeded_is_a_validation_error(db):
    heavy = [('/Fixture/Serration', 10), ('/Fixture/Hellfire', 5),
             ('/Fixture/CryoRounds', 5), ('/Fixture/PointStrike', 5),
             ('/Fixture/GalvanizedChamber', 10)]
    out = api.compute(_weapon_build(heavy, equipment_rank=0, orokin=False,
                                    mastery_rank=0), db)
    assert 'capacity_exceeded' in {row['code'] for row in out['validation']['errors']}


def test_a_bad_build_never_raises(db):
    out = api.compute({'equipment_id': None, 'slots': 'nope'}, db)
    assert out['ok'] is False and out['validation']['errors']


# ------------------------------------------------------------------ 3. refusals
def test_every_refusal_is_named_in_the_registry(db):
    """No engine may return an unregistered refusal code (brief section 11)."""
    out = api.compute(_weapon_build([('/Fixture/GalvanizedChamber', 10)]), db)
    markers = out['unsupported']
    assert markers
    assert unsupported.check_coverage(markers) == []


def test_registry_rows_explain_themselves():
    for row in unsupported.list_all():
        assert row['reason'] and row.get('phase') is not None
        assert row['supported'] is False


def test_galvanized_rider_is_refused_but_its_base_value_applies(db):
    out = api.compute(_weapon_build([('/Fixture/GalvanizedChamber', 10)]), db)
    assert out['ok']
    # +80.3% Multishot at rank 10 is applied; the "On Kill" rider is only refused.
    assert out['result']['stats']['multishot'] == pytest.approx(1.803)
    assert any(row['code'] == 'conditional_effect' for row in out['unsupported'])


def test_unsupported_effect_on_a_real_mod_is_reported(db):
    build = _frame_build([])
    build['slots'] = [{'kind': 'aura', 'index': None, 'polarity': None,
                       'mod': {'id': '/Fixture/AuraRifleAmp', 'rank': 5}}]
    out = api.compute(build, db)
    assert out['ok'], out['validation']
    codes = {row['code'] for row in out['unsupported']}
    assert 'unmodelled_effect' in codes
    # Rifle Amp R5 drains 9: a vacant aura slot pays the listed drain, a mismatched
    # polarity pays 80% (7), a matching one doubles it (18).
    assert out['capacity']['capacity']['aura_bonus'] == 9
    build['slots'][0]['polarity'] = 'naramon'
    assert api.compute(build, db)['capacity']['capacity']['aura_bonus'] == 7
    build['slots'][0]['polarity'] = 'madurai'
    assert api.compute(build, db)['capacity']['capacity']['aura_bonus'] == 18


# ------------------------------------------------------------------ 4. comparison
def test_compare_lists_the_delta_and_the_cause(db):
    before = _weapon_build([])
    after = _weapon_build([('/Fixture/Serration', 10)])
    diff = api.compare(before, after, db)
    assert diff['ok'] is True
    rows = {row['stat']: row for row in diff['diff']}
    assert rows['modded_base_damage']['delta'] == pytest.approx(57.75)
    assert rows['modded_base_damage']['a'] == 35
    assert rows['modded_base_damage']['b'] == 92.75


# ------------------------------------------------------------------ 5. data layer
def test_load_reports_a_missing_database_clearly(tmp_path):
    missing = str(tmp_path / 'nope.json')
    assert data_mod.load(missing, allow_missing=True) is None
    with pytest.raises(FileNotFoundError) as exc:
        data_mod.load(missing)
    assert 'ingest' in str(exc.value)


def test_lookups_prefer_the_standard_variant(db):
    """Beginner/Intermediate starter copies share a display name with the real mod. The starter
    copy now carries the wiki's own name ("Flawed Serration"), so a name lookup is unambiguous -
    and the real card is the one that comes back."""
    row = data_mod.find_mod(db, 'Serration')
    assert row['max_rank'] == 10
    assert row['variant'] is None
    assert data_mod.find_mod(db, 'Flawed Serration')['variant'] == 'beginner'
    # the name is still carried by the plain card and by the /Expert/ leftover, but the lookup
    # hands back the real one - and a search finds the real card first, the Flawed copy after it
    matches = data_mod.find_all(db, 'Serration', kind='mods')
    assert matches[0]['id'] == row['id']
    assert [m['variant'] for m in matches] == [None, 'expert']   # the Flawed copy has its own name
    assert matches[1]['shadowed'] is True


def test_shadow_copies_are_flagged_and_never_slot_as_the_real_card(db):
    """A /Beginner/ or /Expert/ row wearing a real mod's name is a shadow copy: flagged, and
    pointing at the card it would otherwise be mistaken for."""
    every = data_mod.find_all(db, 'Serration', kind='mods') + \
        data_mod.find_all(db, 'Flawed Serration', kind='mods')
    flawed = [r for r in every if r['variant'] == 'beginner']
    assert flawed and flawed[0]['name'] == 'Flawed Serration'
    assert flawed[0]['base_name'] == 'Serration' and flawed[0]['is_flawed'] is True
    assert flawed[0]['shadowed'] is False          # its own name now, nothing to shadow
    expert = [r for r in every if r['variant'] == 'expert']
    assert expert and expert[0]['shadowed'] is True
    assert expert[0]['shadowed_by'] == data_mod.find_mod(db, 'Serration')['id']


def test_search_finds_equipment_and_mods(db):
    hits = data_mod.search(db, 'braton')
    assert any(row['bucket'] == 'equipment' for row in hits)
    assert data_mod.summary(db)['equipment'] == len(FIXTURE_EQUIPMENT)


def test_database_is_deterministic(db):
    same_source = {'file': 'test-fixture'}
    again = ingest.build_database(
        [ingest.normalise_mod(_mod_row(*row), {}, same_source) for row in FIXTURE_MODS],
        [ingest.normalise_equipment(dict(raw, uniqueName=unique, name=name), kind, {}, {},
                                    same_source)
         for unique, name, kind, raw in FIXTURE_EQUIPMENT],
        {'generated_iso': 'test-fixture'})
    assert json.dumps(again['mods'], sort_keys=True) == json.dumps(db['mods'],
                                                                   sort_keys=True)


# ------------------------------------------------- 6. the generated database on disk
def test_the_real_database_matches_its_own_content_hash():
    """The ingest is reproducible: the file on disk must hash to the hash it carries.

    Skips when the database has not been generated (it is a build artifact, not a tracked
    file), and fails if someone hand-edited it or a run was interrupted mid-write.
    """
    path = os.path.join(REPO, 'data', 'build_data.json')
    if not os.path.exists(path):
        pytest.skip('data/build_data.json not generated: run python builds/ingest.py')
    db = data_mod.load(path=path)
    assert db['schema_version'] == ingest.SCHEMA_VERSION
    assert ingest.content_hash(db) == db['content_hash']


def test_exilus_ok_accepts_the_ingested_flag():
    """The library calls a mod Exilus-capable from flags.exilus; the validator must agree.

    The ingester folds isExilus/isUtility into flags.exilus, so a validator reading only the
    export keys refused every Exilus mod while the same row was offered as Exilus-capable.
    """
    from builds import effects
    assert effects.exilus_ok({'flags': {'exilus': True}}) is True
    assert effects.exilus_ok({'isExilus': True}) is True
    assert effects.exilus_ok({'flags': {}}) is False
    assert effects.exilus_ok({'flags': 'not a dict'}) is False
