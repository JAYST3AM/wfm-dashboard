"""Phase 5 refusal preservation and validation strictness.

Two jobs:
  * the validation cleanup: a declared boolean is a boolean (`'yes'` is not `True`), and the new
    enemy/buff fields refuse malformed values instead of coercing them;
  * refusal preservation: the Umbral set is the one set bonus that applies, every other set still
    refuses by name, and the corpus of refused mechanics did not shrink silently.
"""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from builds import api, conditions, effects, ingest, unsupported, validation  # noqa: E402
from test_builds_engine import FIXTURE_EQUIPMENT, FIXTURE_MODS, _mod_row  # noqa: E402

UMBRAL_VITALITY = '/Lotus/Upgrades/Mods/Sets/Umbra/WarframeUmbraModA'
UMBRAL_FIBER = '/Lotus/Upgrades/Mods/Sets/Umbra/WarframeUmbraModB'
UMBRAL_INTENSIFY = '/Lotus/Upgrades/Mods/Sets/Umbra/WarframeUmbraModC'

PHASE5_MODS = [
    (UMBRAL_VITALITY, 'Umbral Vitality',
     ['+%d%% Health' % (10 * (i + 1)) for i in range(11)], 'Warframe Mod', 'Warframe',
     'umbra', 4),
    (UMBRAL_FIBER, 'Umbral Fiber',
     ['+%d%% Armor' % (10 * (i + 1)) for i in range(11)], 'Warframe Mod', 'Warframe',
     'umbra', 4),
    (UMBRAL_INTENSIFY, 'Umbral Intensify',
     ['+%d%% Ability Strength' % (4 * (i + 1)) for i in range(11)], 'Warframe Mod', 'Warframe',
     'umbra', 4),
    ('/Fixture/AugurSecrets', 'Augur Secrets',
     ['+%d%% Ability Strength' % (4 * (i + 1)) for i in range(7)], 'Warframe Mod', 'Warframe',
     'madurai', 4),
]


@pytest.fixture(scope='module')
def db():
    slugs = {'/Fixture/BratonPrime': 'braton_prime', '/Fixture/Excalibur': 'excalibur'}
    src = {'file': 'phase5-refusals-test'}
    mods = [ingest.normalise_mod(_mod_row(*row), slugs, src)
            for row in list(FIXTURE_MODS) + PHASE5_MODS]
    equipment = [ingest.normalise_equipment(dict(raw, uniqueName=unique, name=name),
                                            kind, slugs, {}, src)
                 for unique, name, kind, raw in FIXTURE_EQUIPMENT]
    return ingest.build_database(mods, equipment,
                                 {'generated_iso': 'phase5-refusals-test',
                                  'game_version': 'phase5-refusals-test'})


def _weapon(mods=(), **over):
    build = {'config': 'A', 'equipment_id': '/Fixture/BratonPrime', 'equipment_rank': 30,
             'orokin': True, 'mastery_rank': 30, 'slots': []}
    for index, (mod_id, rank) in enumerate(mods):
        build['slots'].append({'kind': 'normal', 'index': index, 'polarity': None,
                               'mod': {'id': mod_id, 'rank': rank}})
    build.update(over)
    return build


def _frame(mods=(), **over):
    build = {'config': 'A', 'equipment_id': '/Fixture/Excalibur', 'equipment_rank': 30,
             'orokin': True, 'mastery_rank': 30, 'slots': []}
    for index, (mod_id, rank) in enumerate(mods):
        build['slots'].append({'kind': 'normal', 'index': index, 'polarity': None,
                               'mod': {'id': mod_id, 'rank': rank}})
    build.update(over)
    return build


# ------------------------------------------------------------------ validation strictness

def test_a_truthy_string_is_not_a_boolean_any_more(db):
    for bad in ('yes', 'true', 1, 0, '1', [], {}):
        out = api.compute(_weapon([], orokin=bad), db)
        codes = [e['code'] for e in out['validation']['errors']]
        assert 'invalid_boolean' in codes, bad
        assert out['build']['orokin'] is False, bad
    for bad in ('yes', 1, 0):
        out = api.compute(_weapon([], exilus_unlocked=bad), db)
        assert 'invalid_boolean' in [e['code'] for e in out['validation']['errors']], bad


def test_a_real_boolean_still_works_and_is_not_an_error(db):
    for value in (True, False):
        out = api.compute(_weapon([], orokin=value), db)
        assert 'invalid_boolean' not in [e['code'] for e in out['validation']['errors']]
        assert out['build']['orokin'] is value


def test_a_slot_level_unlock_must_be_a_boolean_too(db):
    build = _weapon()
    build['slots'] = [{'kind': 'exilus', 'index': None, 'polarity': None,
                       'mod': None, 'unlocked': 'yes'}]
    out = api.compute(build, db)
    codes = [e['code'] for e in out['validation']['errors']]
    assert 'invalid_boolean' in codes
    # a real boolean still enables the slot
    build['slots'][0]['unlocked'] = True
    ok = api.compute(build, db)
    assert 'invalid_boolean' not in [e['code'] for e in ok['validation']['errors']]
    assert 'exilus_not_unlocked' not in [e['code'] for e in ok['validation']['errors']]


def test_invalid_boolean_is_a_registered_validation_code():
    assert 'invalid_boolean' in validation.CODES


def test_the_malformed_corpus_never_crashes_and_never_coerces(db):
    """The new fields, in the shapes that used to slip through as something else."""
    contexts = [
        {'buffs': 'on_kill'}, {'buffs': ['on_kill']}, {'buffs': 3},
        {'buffs': {'on_kill': None}}, {'buffs': {'on_kill': {}}},
        {'buffs': {'on_kill': {'stacks': {}}}}, {'buffs': {'on_kill': {'uptime': -1}}},
        {'buffs': {'on_kill': {'uptime': 2}}}, {'buffs': {'on_kill': {'stacks': 10 ** 9}}},
        {'target': {'armor': '300'}}, {'target': {'armor': []}},
        {'target': {'corrosive_stacks': '0'}}, {'target': {'corrosive_stacks': True}},
        {'target': {'faction': 'grineer'}}, {'target_faction': {'a': 1}},
        {'target_faction': []}, {'target': {'health': 1000, 'protection': 'health',
                                            'armor': 300, 'corrosive_stacks': 0}},
    ]
    for context in contexts:
        for build in (_weapon([('/Fixture/Serration', 10)]),):
            out = api.compute(build, db, {'context': context})
            assert isinstance(out, dict) and out.get('evaluation'), context
            assert isinstance(out.get('unsupported'), list), context
    # the pool size has no consumer: named, and the target answer still computes
    pooled = api.compute(_weapon([('/Fixture/Serration', 10)]), db,
                         {'context': {'target_faction': 'grineer',
                                      'target': {'protection': 'health', 'armor': 300,
                                                 'corrosive_stacks': 0, 'health': 1000}}})
    assert (pooled['evaluation'].get('unused') or []) == ['target.health']
    assert pooled['result']['target_damage'] is not None


# ------------------------------------------------------------------ the Umbral set (5.6)

def test_the_umbral_set_bonus_applies_from_two_pieces(db):
    out = api.compute(_frame([(UMBRAL_VITALITY, 10), (UMBRAL_INTENSIFY, 10)]), db)
    assert out['ok'], out['validation']
    stats = out['result']['stats']
    # Excalibur rank 30: 370 health; Umbral Vitality R10 +110% x1.30 = +143%
    assert stats['health'] == pytest.approx(370 * (1 + 110 * 1.30 / 100.0))
    # Umbral Intensify R10 +44 pp x1.25 = +55 pp
    assert stats['ability_strength'] == pytest.approx(155)
    assert any('Umbral set: 2 pieces' in n for n in out['result']['notes'])
    assert not [m for m in out['result']['unsupported'] if m['code'] == 'set_bonus']


def test_three_pieces_scale_vitality_and_fiber_by_1_8_and_intensify_by_1_75(db):
    out = api.compute(_frame([(UMBRAL_VITALITY, 10), (UMBRAL_FIBER, 10),
                              (UMBRAL_INTENSIFY, 10)]), db)
    stats = out['result']['stats']
    assert stats['health'] == pytest.approx(370 * (1 + 110 * 1.80 / 100.0))
    assert stats['armor'] == pytest.approx(240 * (1 + 110 * 1.80 / 100.0))
    assert stats['ability_strength'] == pytest.approx(100 + 44 * 1.75)
    # the health trace shows the scaled contribution, with the set noted on the row
    row = [m for m in out['result']['traces']['health']['modifiers']
           if m.get('source') == 'Umbral Vitality'][0]
    assert row['value'] == pytest.approx(198)
    assert 'Umbral set bonus' in (row.get('note') or '')


def test_one_piece_is_a_stated_no_bonus_not_a_refusal(db):
    out = api.compute(_frame([(UMBRAL_VITALITY, 10)]), db)
    assert out['result']['stats']['health'] == pytest.approx(370 * (1 + 1.10))
    assert not [m for m in out['result']['unsupported'] if m['code'] == 'set_bonus']
    assert any('second equipped set piece' in n for n in out['result']['notes'])


def test_every_other_set_still_refuses_by_name(db):
    out = api.compute(_frame([('/Fixture/AugurSecrets', 6)]), db)
    marker = [m for m in out['result']['unsupported'] if m['code'] == 'set_bonus']
    assert marker and 'Umbral set only' in marker[0]['reason']
    assert out['result']['stats']['ability_strength'] == pytest.approx(100 + 28)


# ------------------------------------------------------------------ refusal preservation

def test_the_registry_covers_every_new_refusal(db):
    probes = [
        _weapon([('/Fixture/Serration', 10)]),
        _weapon([('/Fixture/GalvanizedChamber', 10)]),
        _frame([(UMBRAL_VITALITY, 10), (UMBRAL_INTENSIFY, 10)]),
        _frame([('/Fixture/AugurSecrets', 6)]),
    ]
    options = [
        {'context': {'buffs': {'on_kill': {'stacks': 3}}}},
        {'context': {'target_faction': 'grineer',
                     'target': {'protection': 'health', 'armor': 300, 'corrosive_stacks': 12}}},
        {'context': {'buffs': {'on_kill': {'stacks': 7}}}},
        {'strict': True, 'context': {'target_faction': 'grineer'}},
    ]
    missing = set()
    for build in probes:
        for opts in [None] + options:
            out = api.compute(build, db, opts)
            missing.update(unsupported.check_coverage(out.get('unsupported') or []))
    assert not missing, sorted(missing)


def test_the_four_condition_states_and_the_validation_vocabulary_stay_disjoint():
    assert not (set(validation.CODES) & set(conditions.STATES))
    assert set(conditions.CONDITION_REASON_CODES) == {
        'condition_unknown', 'condition_not_satisfied', 'condition_effect_unimplemented',
        'mechanic_unsupported'}


def test_the_umbral_rule_is_pinned_data_not_a_special_case_in_the_engine():
    """The rule table is data keyed by the game's own ids; the scaling pass is generic."""
    assert effects.UMBRAL_MULTIPLIERS[UMBRAL_VITALITY][3] == 1.80
    assert effects.UMBRAL_MULTIPLIERS[UMBRAL_INTENSIFY][2] == 1.25
    src = (REPO / 'builds' / 'effects.py').read_text(encoding='utf-8')
    assert src.count('UMBRAL_MULTIPLIERS') >= 2


def test_a_json_document_cannot_make_the_engine_raise(db):
    """Malformed context is answered with a named state, never an exception.

    The three shapes below are the ones an independent reviewer's probes found raising: a JSON
    integer is unbounded (`float()` overflows), and `immune_to` was iterated as if any non-string
    were a sequence. A JSON document can carry all of them, so they are pinned here.
    """
    huge = int('1' + '0' * 400)
    cases = [
        {'target_faction': 'grineer', 'target': {'protection': 'health', 'armor': huge}},
        {'target': {'protection': 'health', 'armor': 300},
         'buffs': {'on_kill': {'uptime': huge, 'stacks': 5}}},
        {'target': {'protection': 'health', 'armor': 300},
         'buffs': {'on_kill': {'stacks': huge}}},
        {'target': {'protection': 'health', 'viral_stacks': 6, 'immune_to': 5}},
        {'target': {'protection': 'health', 'viral_stacks': 6, 'immune_to': ['viral', 7]}},
        {'target': {'protection': 'health', 'armor': 300, 'corrosive_stacks': float('inf')}},
    ]
    for ctx in cases:
        out = api.compute(_weapon([('/Fixture/Serration', 10)]), db, {'context': ctx})
        assert out['ok'] is True, (ctx, out['validation'])
        for row in out.get('conditions') or []:
            assert row['state'] in conditions.STATES, (ctx, row)


def test_a_conflicting_second_spelling_is_named_not_silently_picked(db):
    out = api.compute(_weapon([('/Fixture/Serration', 10)]), db,
                      {'context': {'target_faction': 'grineer',
                                   'target': {'protection': 'health', 'armor': 300,
                                              'armour': 900}}})
    ignored = (out.get('evaluation') or {}).get('context_ignored') or []
    stated = ((out['result']['target_damage'] or {}).get('armor') or {}).get('stated')
    assert stated == 300
    assert any('armour' in entry for entry in ignored), ignored
