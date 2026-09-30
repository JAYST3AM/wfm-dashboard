"""Conditional damage evaluation (Phase 4, milestones 4.3, 4.5 and 4.6).

The pipeline under test, end to end and in one file:

    context -> condition evaluation -> state -> effect -> result / refusal

and the three kinds of answer 4.5 asks for: a deterministic result, a conditional result, and a
refused result. The Phase 1/3 guarantee is pinned here too: with no conditional context in play,
the numbers do not move.
"""
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from builds import api, conditions, ingest, unsupported  # noqa: E402
from test_builds_engine import FIXTURE_EQUIPMENT, FIXTURE_MODS, _mod_row  # noqa: E402
from test_condition_states import FACTION_MOD, PHASE4_MODS  # noqa: E402

FIRST_SHOT_MOD = '/Fixture/ChargedBattery'


@pytest.fixture(scope='module')
def db():
    slugs = {'/Fixture/BratonPrime': 'braton_prime', '/Fixture/Excalibur': 'excalibur'}
    src = {'file': 'conditional-damage-test'}
    mods = [ingest.normalise_mod(_mod_row(*row), slugs, src)
            for row in list(FIXTURE_MODS) + PHASE4_MODS]
    equipment = [ingest.normalise_equipment(dict(raw, uniqueName=unique, name=name),
                                            kind, slugs, {}, src)
                 for unique, name, kind, raw in FIXTURE_EQUIPMENT]
    return ingest.build_database(mods, equipment,
                                 {'generated_iso': 'conditional-damage-test',
                                  'game_version': 'conditional-damage-test'})


def _build(mods=()):
    build = {'config': 'A', 'equipment_id': '/Fixture/BratonPrime', 'equipment_rank': 30,
             'orokin': True, 'mastery_rank': 30, 'slots': []}
    for index, (mod_id, rank) in enumerate(mods):
        build['slots'].append({'kind': 'normal', 'index': index, 'polarity': None,
                               'mod': {'id': mod_id, 'rank': rank}})
    return build


def _row(rows, condition):
    for row in rows:
        if row.get('condition') == condition:
            return row
    return None


# ------------------------------------------------------------------ 4.3 one condition, four states

def test_the_faction_condition_is_unknown_when_no_target_is_stated(db):
    out = api.compute(_build([(FACTION_MOD, 5)]), db)
    assert out['evaluation']['state'] == 'conditional'
    assert out['evaluation']['withheld'] == ['target_faction']
    assert out['result']['faction_multiplier'] == 1.0
    row = _row(out['conditions'], 'target_faction')
    assert row['state'] == conditions.UNKNOWN
    assert row['missing'] == ['target_faction']
    assert row['applied'] is False


def test_the_faction_condition_is_satisfied_by_a_stated_target(db):
    out = api.compute(_build([(FACTION_MOD, 5)]), db,
                      {'context': {'target_faction': 'grineer'}})
    row = _row(out['conditions'], 'target_faction')
    assert row['state'] == conditions.SATISFIED and row['applied'] is True
    # rank 5 of a x1.05-per-rank Bane is x1.30
    assert abs(out['result']['faction_multiplier'] - 1.30) < 1e-9
    assert out['evaluation']['state'] == 'deterministic'


def test_the_wrong_faction_is_a_reported_zero_and_not_an_error(db):
    out = api.compute(_build([(FACTION_MOD, 5)]), db,
                      {'context': {'target_faction': 'corpus'}})
    row = _row(out['conditions'], 'target_faction')
    assert row['state'] == conditions.NOT_SATISFIED
    assert row['applied'] is False and row['reason_code'] == 'condition_not_satisfied'
    assert out['result']['faction_multiplier'] == 1.0
    # a known-false condition is an answer, not a hole: the result stays deterministic
    assert out['evaluation']['state'] == 'deterministic'
    assert out['validation']['ok'] is True


def test_the_condition_never_contributes_unless_it_was_resolved_true(db):
    """The honesty property: an unresolved bonus is never silently applied."""
    plain = api.compute(_build([]), db)
    for options in ({}, {'context': {}}, {'context': {'target_faction': 'corpus'}}):
        out = api.compute(_build([(FACTION_MOD, 10)]), db, options)
        assert out['result']['stats']['burst_dps'] == plain['result']['stats']['burst_dps']
        assert out['result']['faction_multiplier'] == 1.0


def test_every_state_is_reachable_through_the_same_pipeline(db):
    """satisfied / not_satisfied / unknown / unsupported - all four, one code path."""
    observed = {
        'satisfied': api.compute(_build([(FACTION_MOD, 3)]), db,
                                 {'context': {'target_faction': 'grineer'}}),
        'not_satisfied': api.compute(_build([(FACTION_MOD, 3)]), db,
                                     {'context': {'target_faction': 'infested'}}),
        'unknown': api.compute(_build([(FACTION_MOD, 3)]), db),
    }
    for state, out in observed.items():
        assert _row(out['conditions'], 'target_faction')['state'] == state
    # unsupported: a clause whose mechanic has no model, from the real corpus classifier
    cid, state, why, code = conditions.classify_conditional_text('On Kill: +30% Multishot')
    assert state == conditions.UNSUPPORTED and code == 'mechanic_unsupported'


# ------------------------------------------------------------------ 4.5 three kinds of answer

def test_a_deterministic_answer_with_no_condition_in_play(db):
    out = api.compute(_build([('/Fixture/Serration', 10)]), db)
    assert out['evaluation']['state'] == 'deterministic'
    assert out['evaluation']['withheld'] == []
    assert out['evaluation']['context_supplied'] is False


def test_strict_evaluation_refuses_the_affected_calculation(db):
    out = api.compute(_build([(FACTION_MOD, 5)]), db, {'strict': True})
    assert out['evaluation']['state'] == 'refused'
    assert out['evaluation']['refused_stats'], 'the affected stats are named'
    for stat in out['evaluation']['refused_stats']:
        assert out['result']['stats'].get(stat) is None
    marker = [m for m in out['result']['unsupported'] if m['code'] == 'calculation_refused']
    assert marker, 'a refused calculation says so in the registry'
    assert marker[0]['state'] == conditions.UNKNOWN
    assert marker[0]['reason_code'] == 'condition_unknown'
    assert marker[0]['stats'] == out['evaluation']['refused_stats']
    # and it is a refusal the registry knows how to describe
    assert marker[0]['code'] in unsupported.MARKER_TO_KEY


def test_a_hypothetical_evaluation_shows_the_bonus_but_says_it_is_hypothetical(db):
    out = api.compute(_build([(FACTION_MOD, 5)]), db, {'hypothetical': True})
    assert abs(out['result']['faction_multiplier'] - 1.30) < 1e-9
    row = _row(out['conditions'], 'target_faction')
    assert row['hypothetical'] is True and row['applied'] is False
    assert row['state'] == conditions.UNKNOWN, 'a hypothesis is not a fact'
    assert out['evaluation']['state'] == 'conditional'


def test_an_unrelated_context_changes_nothing(db):
    """A context with no bearing on the build must leave every Phase 1 number alone."""
    baseline = api.compute(_build([('/Fixture/Serration', 10)]), db)
    touched = api.compute(_build([('/Fixture/Serration', 10)]), db,
                          {'context': {'attack': {'shot_index': 4},
                                       'target': {'viral_stacks': 3}}})
    for stat, value in baseline['result']['stats'].items():
        assert touched['result']['stats'][stat] == value, stat


def test_ignored_context_fields_are_reported_back(db):
    out = api.compute(_build([]), db, {'context': {'nope': 1, 'target_faction': 5}})
    assert 'nope' in out['evaluation']['context_ignored']
    assert any('target_faction' in item for item in out['evaluation']['context_ignored'])


def test_the_phase_1_faction_option_still_works(db):
    """`options.faction` predates the context; the same answer must come out of both spellings."""
    old = api.compute(_build([(FACTION_MOD, 5)]), db, {'faction': 'grineer'})
    new = api.compute(_build([(FACTION_MOD, 5)]), db,
                      {'context': {'target_faction': 'grineer'}})
    assert old['result']['faction_multiplier'] == new['result']['faction_multiplier']
    assert _row(old['conditions'], 'target_faction')['state'] == conditions.SATISFIED


def test_an_explicit_context_beats_the_older_option(db):
    out = api.compute(_build([(FACTION_MOD, 5)]), db,
                      {'faction': 'corpus', 'context': {'target_faction': 'grineer'}})
    assert abs(out['result']['faction_multiplier'] - 1.30) < 1e-9


# ------------------------------------------------------------------ 4.6 the second mechanic

def test_the_first_shot_bonus_applies_on_the_first_shot(db):
    out = api.compute(_build([(FIRST_SHOT_MOD, 3)]), db,
                      {'context': {'attack': {'shot_index': 1}}})
    row = _row(out['conditions'], 'first_shot')
    assert row['state'] == conditions.SATISFIED and row['applied'] is True
    assert out['evaluation']['state'] == 'deterministic'
    # +40% base damage at rank 3 of the fixture
    assert abs(out['result']['stats']['modded_base_damage'] - 35 * 1.4) < 1e-6


def test_the_first_shot_bonus_does_not_apply_later_in_the_magazine(db):
    first = api.compute(_build([(FIRST_SHOT_MOD, 3)]), db,
                        {'context': {'attack': {'shot_index': 1}}})
    later = api.compute(_build([(FIRST_SHOT_MOD, 3)]), db,
                        {'context': {'attack': {'shot_index': 2}}})
    assert _row(later['conditions'], 'first_shot')['state'] == conditions.NOT_SATISFIED
    assert later['result']['stats']['modded_base_damage'] == 35
    assert later['result']['stats']['burst_dps'] < first['result']['stats']['burst_dps']
    assert later['validation']['ok'] is True


def test_the_first_shot_bonus_is_unknown_without_an_attack_context(db):
    out = api.compute(_build([(FIRST_SHOT_MOD, 3)]), db)
    row = _row(out['conditions'], 'first_shot')
    assert row['state'] == conditions.UNKNOWN
    assert row['missing'] == ['attack.shot_index']
    assert out['result']['stats']['modded_base_damage'] == 35, 'not applied, not invented'
    assert out['evaluation']['state'] == 'conditional'


def test_the_first_shot_trace_names_the_condition_and_its_state(db):
    out = api.compute(_build([(FIRST_SHOT_MOD, 3)]), db,
                      {'context': {'attack': {'shot_index': 1}}})
    trace = out['result']['traces']['damage_multiplier']
    mods = [m for m in trace['modifiers'] if m.get('condition') == 'first_shot']
    assert mods, 'the modifier that needs a condition says which one'
    assert mods[0]['state'] == conditions.SATISFIED
    assert any('first-shot bonus' in str(n) for n in trace.get('notes') or [])


def test_the_second_mechanic_reuses_the_same_state_space(db):
    """4.6: a mechanic with a different source (the attack, not the target) needs no new idea."""
    cases = {
        conditions.SATISFIED: {'context': {'attack': {'shot_index': 1}}},
        conditions.NOT_SATISFIED: {'context': {'attack': {'shot_index': 9}}},
        conditions.UNKNOWN: {},
    }
    for state, options in cases.items():
        out = api.compute(_build([(FIRST_SHOT_MOD, 3)]), db, options)
        assert _row(out['conditions'], 'first_shot')['state'] == state
    # and the fourth state, unsupported, arrives from the same vocabulary
    assert conditions.classify_conditional_text('for 6s: +50% damage')[1] == conditions.UNSUPPORTED


# ------------------------------------------------------------------ malformed input, and the route

BAD_CONTEXTS = [
    'grineer', 42, [1, 2], {'target': 'grineer'}, {'target': {'viral_stacks': 'six'}},
    {'attack': 'first'}, {'target_faction': 7}, {'target': {'protection': []}},
    {'attack': {'shot_index': 'one'}}, {'target': {'viral_stacks': 99}},
    {'target': {'viral_stacks': -3}}, {'target': {'immune_to': 'viral'}},
]


@pytest.mark.parametrize('context', BAD_CONTEXTS)
def test_a_malformed_context_never_crashes_the_engine(db, context):
    out = api.compute(_build([(FACTION_MOD, 5), (FIRST_SHOT_MOD, 3)]), db,
                      {'context': context})
    assert out['ok'] in (True, False)
    assert isinstance(out.get('conditions'), list)
    assert out['evaluation']['state'] in ('deterministic', 'conditional', 'refused')


@pytest.mark.parametrize('options', ['strict', 3, ['context'], None, {}])
def test_a_malformed_options_block_never_crashes_the_engine(db, options):
    out = api.compute(_build([(FACTION_MOD, 5)]), db, options)
    assert out['evaluation']['state'] in ('deterministic', 'conditional', 'refused')


def test_the_route_hands_the_options_to_the_engine_and_refuses_a_bad_block(tmp_path, db, monkeypatch):
    """`options` travels through /api/planner/compute without the page computing anything.

    The env var is patched with monkeypatch on purpose: setting `WFM_BUILD_DB` by hand here leaked
    this tiny fixture database into `tests/test_refusal_preservation.py`'s real-database fixture,
    which then failed its corpus assertion whenever the files ran in that order (adversarial review
    F5). Any test that points WFM_BUILD_DB somewhere must put it back.
    """
    db_file = tmp_path / 'build_data.json'
    db_file.write_text(json.dumps(db), encoding='utf-8')
    data_dir = tmp_path / 'data'
    data_dir.mkdir()
    monkeypatch.setenv('WFM_BUILD_DB', str(db_file))
    spec = importlib.util.spec_from_file_location('p4_server', str(REPO / 'server.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.ROOT = str(REPO)
    mod.DATA = str(data_dir)
    mod._PLANNER.clear()

    body = _build([(FACTION_MOD, 5)])
    body['options'] = {'context': {'target_faction': 'grineer'}}
    out = mod.planner_compute(body)
    assert abs(out['result']['faction_multiplier'] - 1.30) < 1e-9
    assert out['evaluation']['state'] == 'deterministic'

    bad = _build([(FACTION_MOD, 5)])
    bad['options'] = ['not', 'an', 'object']
    refused = mod.planner_compute(bad)
    assert refused['ok'] is False and 'options' in refused['error']

    # the same build with no options is still the Phase 2 shape and still conditional
    plain = mod.planner_compute(_build([(FACTION_MOD, 5)]))
    assert plain['evaluation']['state'] == 'conditional'

# --- an input the engine cannot use is a refusal, not silence (found in self-review) -------------

def test_a_stated_input_no_engine_can_use_is_named_not_dropped(db):
    """A warframe has no target model, so stating one must refuse it, never ignore it."""
    out = api.compute({'config': 'A', 'equipment_id': '/Fixture/Excalibur', 'equipment_rank': 30,
                       'mastery_rank': 30, 'slots': []}, db,
                      {'context': {'target_faction': 'grineer', 'target': {'viral_stacks': 6}}})
    assert out['ok'] is True
    assert out['evaluation']['unused'] == ['target_faction', 'target.viral_stacks']
    marker = [m for m in out['unsupported'] if m.get('code') == 'context_unused']
    assert marker, 'the stated input must be named in the refusals'
    assert marker[0]['condition']['state'] == conditions.UNSUPPORTED
    assert marker[0]['condition']['reason_code'] == 'context_unused'


def test_a_field_the_weapon_engine_cannot_use_is_named_too(db):
    """`immune_to` is only read by the viral mechanic; with no viral damage it is unusable."""
    out = api.compute(_build(), db, {'context': {'target': {'immune_to': ['viral']}}})
    assert out['evaluation']['unused'] == ['target.immune_to']
    assert [m.get('code') for m in out['unsupported']].count('context_unused') == 1


def test_an_input_the_engine_did_use_is_not_called_unused(db):
    out = api.compute(_build(), db,
                      {'context': {'target': {'viral_stacks': 4, 'protection': 'health'}}})
    assert not out['evaluation'].get('unused')
    assert not [m for m in out['unsupported'] if m.get('code') == 'context_unused']


def test_nothing_stated_is_not_a_refusal(db):
    out = api.compute(_build(), db)
    assert out['evaluation']['context_supplied'] is False
    assert not out['evaluation'].get('unused')


# --- what the independent adversarial review found, pinned (F1, F2, F3) ---------------------------

def test_a_hypothetical_evaluation_never_invents_a_number_it_does_not_have(db):
    """A hypothetical row is shown as-if satisfied, but an unknown viral row carries no amplifier.

    Dereferencing it raised `KeyError: amplifier` over the HTTP route (adversarial review F1).
    """
    out = api.compute(_build([]), db, {'hypothetical': True,
                                       'context': {'target': {'viral_stacks': 6}}})
    assert out['ok'] is True
    assert out['result']['stats'].get('viral_amplifier') is None
    assert 'damage_to_health' not in out['result']['stats']


def _every_number_keyed(node, keys, path=''):
    """Every path in a payload where a value under one of `keys` is still a number."""
    hits = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key in keys and isinstance(value, (int, float)):
                hits.append(path + '/' + key)
            hits += _every_number_keyed(value, keys, path + '/' + key)
    elif isinstance(node, list):
        for i, value in enumerate(node):
            hits += _every_number_keyed(value, keys, path + '/' + str(i))
    return hits


def test_a_strict_refusal_leaves_that_number_nowhere_in_the_payload(db):
    """Refusing a stat means nothing else may still report it (adversarial review F2).

    `stats` was nulled while `dps.burst.value` and the traces kept the figure, so the page printed a
    refused number in the damage card one line under the refusal.
    """
    out = api.compute(_build([(FACTION_MOD, 5)]), db, {'strict': True})
    res, refused = out['result'], out['evaluation']['refused_stats']
    assert out['evaluation']['state'] == 'refused' and 'burst_dps' in refused
    assert res['stats']['burst_dps'] is None
    assert res['dps']['burst']['value'] is None and res['dps']['sustained']['value'] is None
    assert _every_number_keyed(res, set(refused)) == []
    for key in refused:
        trace = res['traces'].get(key)
        if isinstance(trace, dict):
            assert trace['final'] is None


def test_the_frame_engine_says_it_has_no_condition_model(db):
    """A warframe build must not borrow the weapon engine's `deterministic` (review F3)."""
    frame = api.compute({'config': 'A', 'equipment_id': '/Fixture/Excalibur', 'equipment_rank': 30,
                         'mastery_rank': 30, 'slots': []}, db)
    assert frame['evaluation']['state'] == 'not_evaluated'
    assert frame['evaluation']['engine_evaluated'] is False
    weapon = api.compute(_build([]), db)
    assert weapon['evaluation']['engine_evaluated'] is True
    assert weapon['evaluation']['state'] in ('deterministic', 'conditional', 'refused')
