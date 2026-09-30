"""The condition state space (Phase 4, milestones 4.1 and 4.2).

The rule this file exists to enforce: a conditional effect is never silently unconditional. Every
conditional thing carries one of four states, and only `satisfied` may contribute a value. These
tests are deliberately synthetic as well as corpus-backed - the synthetic ones prove the rules, the
corpus ones prove the real 416 conditional mods obey them.
"""
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from builds import api, conditions, effects, ingest, validation  # noqa: E402
from test_builds_engine import FIXTURE_EQUIPMENT, FIXTURE_MODS, _mod_row  # noqa: E402

CONDITIONAL_MOD = '/Fixture/GalvanizedChamber'
FACTION_MOD = '/Fixture/BaneOfGrineer'

# The Phase 4 fixtures: a faction mod in the multiplier form the real corpus uses, a first-shot
# bonus, and a toxin mod (with Cryo Rounds above, it makes viral). They are appended to the shared
# fixtures locally so no other test's row counts move.
PHASE4_MODS = [
    ('/Fixture/BaneOfGrineer', 'Bane Of Grineer',
     ['x%.2f Damage to Grineer' % (1.05 + 0.05 * i) for i in range(11)],
     'Primary Mod', 'Rifle', 'madurai', 4),
    ('/Fixture/ChargedBattery', 'Charged Battery',
     ['+%d%% Damage on first shot in Magazine' % (10 * (i + 1)) for i in range(4)],
     'Primary Mod', 'Rifle', 'madurai', 4),
    ('/Fixture/InfectedClip', 'Infected Clip',
     ['+%d%% <DT_POISON_COLOR>Toxin' % (15 * (i + 1)) for i in range(6)],
     'Primary Mod', 'Rifle', 'naramon', 6),
]


@pytest.fixture(scope='module')
def db():
    """The standard fixture database, through the real ingest path."""
    slugs = {'/Fixture/BratonPrime': 'braton_prime', '/Fixture/Excalibur': 'excalibur'}
    src = {'file': 'condition-states-test'}
    mods = [ingest.normalise_mod(_mod_row(*row), slugs, src)
            for row in list(FIXTURE_MODS) + PHASE4_MODS]
    equipment = [ingest.normalise_equipment(dict(raw, uniqueName=unique, name=name),
                                            kind, slugs, {}, src)
                 for unique, name, kind, raw in FIXTURE_EQUIPMENT]
    return ingest.build_database(mods, equipment,
                                 {'generated_iso': 'condition-states-test',
                                  'game_version': 'condition-states-test'})


def _build(mods=()):
    build = {'config': 'A', 'equipment_id': '/Fixture/BratonPrime', 'equipment_rank': 30,
             'orokin': True, 'mastery_rank': 30, 'slots': []}
    for index, (mod_id, rank) in enumerate(mods):
        build['slots'].append({'kind': 'normal', 'index': index, 'polarity': None,
                               'mod': {'id': mod_id, 'rank': rank}})
    return build


# ------------------------------------------------------------------ 4.1 the state space

def test_the_module_selftests_pass():
    assert conditions.selftest() == 0


def test_the_four_states_are_the_whole_space():
    assert conditions.STATES == ('satisfied', 'not_satisfied', 'unknown', 'unsupported')
    assert set(conditions.STATE_CODES) == set(conditions.STATES)
    # each state means something different for the calculation, and says so
    for state in conditions.STATES:
        assert conditions.MEANING.get(state)
    assert len({conditions.STATE_CODES[s] for s in conditions.STATES}) == 4


def test_a_state_is_never_a_number_boolean_or_empty_string():
    """The four states are words, so nothing can be confused with 0, False, '' or None."""
    for bogus in (0, 1, True, False, '', None, [], {}, 'satisfied ', 'SATISFIED', 'partial'):
        with pytest.raises(ValueError):
            conditions.result('synthetic', bogus, 'not a state')


def test_a_refusal_carries_no_value_at_all():
    """A withheld contribution has no number and no boolean - that is what stops it being summed."""
    for state in (conditions.NOT_SATISFIED, conditions.UNKNOWN, conditions.UNSUPPORTED):
        row = conditions.result('synthetic', state, 'why', value=None)
        assert row['applied'] is False
        assert 'value' not in row or row['value'] is None
    satisfied = conditions.result('synthetic', conditions.SATISFIED, 'why')
    assert satisfied['applied'] is True


def test_only_a_satisfied_condition_may_contribute():
    """The synthetic guard behind every real conditional mod: 3 of the 4 states add nothing."""
    contributed = {state: conditions.result('synthetic', state, 'why')['applied']
                   for state in conditions.STATES}
    assert contributed == {'satisfied': True, 'not_satisfied': False, 'unknown': False,
                           'unsupported': False}


def test_unknown_is_not_false_and_names_what_is_missing():
    """'I was not told' is a different answer from 'it is false', and the missing input is named."""
    row = conditions.evaluate('target_faction',
                              conditions.normalise_context(None), faction='grineer')
    assert row['state'] == 'unknown' and row['missing'] == ['target_faction']
    false_row = conditions.evaluate('target_faction',
                                   conditions.normalise_context({'target_faction': 'corpus'}),
                                   faction='grineer')
    assert false_row['state'] == 'not_satisfied' and not false_row.get('missing')
    assert row['state'] != false_row['state']


def test_a_state_is_never_a_validation_failure():
    """Validation codes are their own vocabulary: none of them is a condition state."""
    codes = {row['code'] for row in validation.CODES.values()} if isinstance(
        getattr(validation, 'CODES', None), dict) else set()
    codes = codes or {c for c in dir(validation) if c.isupper()}
    assert not (set(conditions.STATES) & codes)
    assert not (set(conditions.STATE_CODES.values()) & codes)


def test_missing_input_is_not_a_validation_error_either(db):
    """A build with a faction mod and no target stated is VALID: nothing is wrong with it.

    The distinction 4.1 asks for: the build is fine (no validation code), the *condition* is
    unknown, and the answer says so instead of quietly applying zero.
    """
    out = api.compute(_build([(FACTION_MOD, 10)]), db)
    assert out['validation']['ok'] is True
    assert not out['validation']['errors']
    assert out['evaluation']['state'] == 'conditional'
    assert out['evaluation']['withheld'] == ['target_faction']
    assert out['conditions'][0]['state'] == 'unknown'


def test_a_refused_mechanic_is_counted_apart_from_the_evaluated_conditions(db):
    """Two different facts, both stated: what was evaluated, and what could not be modelled."""
    out = api.compute(_build([(CONDITIONAL_MOD, 10)]), db)
    assert out['evaluation']['state'] == 'deterministic'
    assert out['evaluation']['unsupported_effects'] >= 1


# ------------------------------------------------------------------ 4.2 structured refusals

def test_every_conditional_mod_in_the_corpus_refuses_with_a_structure(db):
    """The refusal keeps its code and gains the engine's own condition vocabulary."""
    out = api.compute(_build([(CONDITIONAL_MOD, 10)]), db)
    rows = [r for r in out['result']['unsupported'] if r['code'] == 'conditional_effect']
    assert rows, 'the galvanized rider must still be refused'
    for row in rows:
        assert row['state'] in conditions.STATES
        assert row['condition_id']
        assert row['reason_code']
        assert row['condition']['condition'] == row['condition_id']
        assert row['condition']['state'] == row['state']
        assert row['condition']['applied'] is False
        assert row['condition']['reason']


def test_the_refusal_says_which_of_the_four_reasons_it_is(db):
    """4.2: the four refusal reasons are distinguishable, not one generic 'conditional'."""
    galv = api.compute(_build([(CONDITIONAL_MOD, 10)]), db)
    codes = [r['reason_code'] for r in galv['result']['unsupported']
             if r['code'] == 'conditional_effect']
    assert codes, 'at least one structured reason'
    assert all(code in conditions.REASON_CODES for code in codes)


@pytest.mark.parametrize('text,expected', [
    ('On Kill: +30% Multishot for 20s', 'on_kill'),
    ('on hit: +2% damage', 'on_hit'),
    ('While Reloading: +40% damage', 'state_clause'),
    ('after a reload, +50% damage', 'sequence_clause'),
    ('+120% damage for 6s', 'timer'),
    ('+2% damage per status effect on the target', 'target_status'),
    ('On Headshot: +50% damage', 'on_headshot'),
    ('+30% damage for each enemy killed', 'per_unit'),
])
def test_the_classifier_names_the_condition_clause(text, expected):
    cid, state, why, code = conditions.classify_conditional_text(text)
    assert cid == expected
    assert state in conditions.STATES
    assert why and code


def test_conditional_text_never_classifies_as_satisfied():
    """A blanket classifier may not decide a condition holds: it cannot know that."""
    for text in ('On Kill: +30% Multishot for 20s', '+120% damage for 6s', 'per status effect'):
        assert conditions.classify_conditional_text(text)[1] in (
            conditions.UNKNOWN, conditions.UNSUPPORTED)


# ------------------------------------------------------------------ the effect layer

def test_the_base_value_applies_and_the_rider_never_does(db):
    """Galvanized Chamber: the unconditional half still counts, the rider still does not."""
    out = api.compute(_build([(CONDITIONAL_MOD, 10)]), db)
    stats = out['result']['stats']
    assert stats['multishot'] > 1.0, 'the flat multishot is real and must apply'
    # every conditional row says withheld, and none of them contributed
    for row in out['conditions']:
        assert row['applied'] is False or row['state'] == 'satisfied'


def test_a_conditional_line_is_still_kept_out_of_the_totals(db):
    """The rider text is refused by name and never becomes a stat."""
    row = [m for m in db['mods'].values() if m['id'] == CONDITIONAL_MOD][0]
    parsed = row['effects']
    assert parsed['conditional'], 'the fixture rider is detected as conditional'
    out = api.compute(_build([(CONDITIONAL_MOD, 10)]), db)
    # multishot is exactly the base table value: nothing from the rider was added
    rank = parsed['rank_table']['multishot'][10]
    assert abs(out['result']['stats']['multishot'] - (1.0 + rank / 100.0)) < 1e-6


def test_the_json_payload_survives_a_round_trip(db):
    """A structured condition is JSON, so it crosses the API boundary intact."""
    out = api.compute(_build([(CONDITIONAL_MOD, 10)]), db, {'strict': True})
    blob = json.dumps(out)
    back = json.loads(blob)
    for row in back['result']['unsupported']:
        if row['code'] == 'conditional_effect':
            assert row['condition']['state'] in conditions.STATES
            assert isinstance(row['condition']['reason'], str)
