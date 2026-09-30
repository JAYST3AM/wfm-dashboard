"""The viral status mechanic (Phase 4, milestone 4.4).

One status effect, one precisely defined piece of its behaviour: the damage-to-health multiplier
from the viral procs already on the target, as documented on the wiki's Viral damage page.

It is deliberately not 'status effects' as a category, and not a simulator: the input is a target
state the caller states, the output is one multiplier and one damage figure, and every state that
is not `satisfied` withholds both.
"""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from builds import api, conditions, ingest, statuses  # noqa: E402
from test_builds_engine import FIXTURE_EQUIPMENT, FIXTURE_MODS, _mod_row  # noqa: E402
from test_condition_states import PHASE4_MODS  # noqa: E402

COLD = '/Fixture/CryoRounds'
TOXIN = '/Fixture/InfectedClip'


@pytest.fixture(scope='module')
def db():
    slugs = {'/Fixture/BratonPrime': 'braton_prime', '/Fixture/Excalibur': 'excalibur'}
    src = {'file': 'viral-status-test'}
    mods = [ingest.normalise_mod(_mod_row(*row), slugs, src)
            for row in list(FIXTURE_MODS) + PHASE4_MODS]
    equipment = [ingest.normalise_equipment(dict(raw, uniqueName=unique, name=name),
                                            kind, slugs, {}, src)
                 for unique, name, kind, raw in FIXTURE_EQUIPMENT]
    return ingest.build_database(mods, equipment,
                                 {'generated_iso': 'viral-status-test',
                                  'game_version': 'viral-status-test'})


def _viral_build():
    return {'config': 'A', 'equipment_id': '/Fixture/BratonPrime', 'equipment_rank': 30,
            'orokin': True, 'mastery_rank': 30,
            'slots': [{'kind': 'normal', 'index': 0, 'polarity': None,
                       'mod': {'id': COLD, 'rank': 5}},
                      {'kind': 'normal', 'index': 1, 'polarity': None,
                       'mod': {'id': TOXIN, 'rank': 5}}]}


def _target(**target):
    """The evaluation *context* (what the caller states about the target)."""
    return {'target': target}


def _opts(**target):
    """The options block that carries that context to the engine."""
    return {'context': _target(**target)}


# ------------------------------------------------------------------ the formula, in isolation

def test_the_module_selftest_passes():
    assert statuses.selftest() == 0


@pytest.mark.parametrize('stacks,amplifier', [
    (1, 2.0),        # +100%
    (2, 2.25),       # +125%
    (3, 2.5),
    (5, 3.0),
    (10, 4.25),      # +325% - the wiki's documented maximum
])
def test_the_documented_multiplier(stacks, amplifier):
    """Resultant damage to health = modded damage x [2 + 0.25 x (stacks - 1)]."""
    assert statuses.amplifier(stacks) == amplifier


def test_the_formula_is_written_down_where_it_is_used():
    assert '2 + (0.25 x (viral_stacks - 1))' in statuses.FORMULA
    assert 'wiki.warframe.com' in statuses.SOURCE
    assert statuses.MAX_STACKS == 10 and statuses.PER_STACK == 0.25


def test_no_stacks_is_a_reported_zero_not_a_refusal():
    row = statuses.evaluate(conditions.normalise_context(_target(viral_stacks=0, protection='health')))
    assert row['state'] == conditions.NOT_SATISFIED
    assert row['amplifier'] == 1.0, 'no procs means x1, and that is an answer'
    assert row['applied'] is False


@pytest.mark.parametrize('target', [
    {'protection': 'health'},                      # no stacks stated
    {'viral_stacks': 6},                           # no landing stated
    {},
])
def test_missing_information_is_unknown_and_withholds_the_multiplier(target):
    row = statuses.evaluate(conditions.normalise_context(_target(**target)))
    assert row['state'] == conditions.UNKNOWN
    assert 'amplifier' not in row, 'an unknown carries no number'
    assert row['missing'], 'and it names what it needs'


@pytest.mark.parametrize('protection', ['shields', 'overguard'])
def test_the_documented_exclusion_is_a_reported_zero(protection):
    """The wiki: only shields and overguard are unaffected - so that is a known false."""
    row = statuses.evaluate(conditions.normalise_context(
        _target(viral_stacks=6, protection=protection)))
    assert row['state'] == conditions.NOT_SATISFIED
    assert row['amplifier'] == 1.0


@pytest.mark.parametrize('stacks', [11, 12, 40])
def test_a_timeline_state_is_unsupported_not_approximated(stacks):
    """Past the cap the wiki describes stack replacement over time; that is not modelled."""
    row = statuses.evaluate(conditions.normalise_context(
        _target(viral_stacks=stacks, protection='health')))
    assert row['state'] == conditions.UNSUPPORTED
    assert 'amplifier' not in row
    assert row['unsupported_code'] == 'viral_stack_timeline'


def test_an_immune_target_is_unsupported():
    row = statuses.evaluate(conditions.normalise_context(
        _target(viral_stacks=6, protection='health', immune_to=['viral'])))
    assert row['state'] == conditions.UNSUPPORTED
    assert 'amplifier' not in row


def test_a_protection_the_engine_does_not_know_is_unsupported():
    row = statuses.evaluate(conditions.normalise_context(
        _target(viral_stacks=6, protection='hull')))
    assert row['state'] == conditions.UNSUPPORTED


def test_a_non_integer_stack_count_is_unknown_not_zero():
    row = statuses.evaluate(conditions.normalise_context(
        _target(viral_stacks='six', protection='health')))
    assert row['state'] == conditions.UNKNOWN


def test_the_mechanic_speaks_the_same_four_state_vocabulary():
    seen = set()
    for target in ({'viral_stacks': 3, 'protection': 'health'},
                   {'viral_stacks': 0, 'protection': 'health'},
                   {'viral_stacks': 3},
                   {'viral_stacks': 30, 'protection': 'health'}):
        seen.add(statuses.evaluate(conditions.normalise_context(_target(**target)))['state'])
    assert seen == set(conditions.STATES)


# ------------------------------------------------------------------ through the engine and the API

def test_a_viral_build_with_stacks_reports_damage_to_health(db):
    out = api.compute(_viral_build(), db, _opts(viral_stacks=6, protection='health'))
    stats = out['result']['stats']
    assert stats['viral_amplifier'] == 3.25
    expected = stats['damage_per_shot_expected_crit'] * 3.25
    assert abs(stats['damage_to_health_expected_crit'] - expected) < 1e-6
    assert abs(stats['damage_to_health'] - stats['damage_per_shot'] * 3.25) < 1e-6
    row = [r for r in out['conditions'] if r['condition'] == 'viral'][0]
    assert row['state'] == conditions.SATISFIED and row['applied'] is True
    assert out['evaluation']['state'] == 'deterministic'


def test_the_phase_1_damage_numbers_do_not_move(db):
    """4.5: with a viral context in play, the unconditional answers are still the same answers."""
    plain = api.compute(_viral_build(), db)
    amplified = api.compute(_viral_build(), db, _opts(viral_stacks=10, protection='health'))
    for stat in ('damage_per_shot', 'burst_dps', 'sustained_dps', 'multishot', 'fire_rate'):
        assert amplified['result']['stats'][stat] == plain['result']['stats'][stat], stat
    assert 'damage_to_health' not in plain['result']['stats']


def test_a_viral_build_with_no_target_state_is_conditional_not_zeroed(db):
    out = api.compute(_viral_build(), db)
    assert out['evaluation']['state'] == 'conditional'
    assert out['evaluation']['withheld'] == ['viral']
    assert 'viral_amplifier' not in out['result']['stats']
    row = [r for r in out['conditions'] if r['condition'] == 'viral'][0]
    assert row['state'] == conditions.UNKNOWN
    # a build with no viral damage is not asked the question at all
    inert = api.compute({'config': 'A', 'equipment_id': '/Fixture/BratonPrime',
                         'equipment_rank': 30, 'orokin': True, 'mastery_rank': 30,
                         'slots': [{'kind': 'normal', 'index': 0, 'polarity': None,
                                    'mod': {'id': '/Fixture/Serration', 'rank': 10}}]}, db)
    assert inert['evaluation']['state'] == 'deterministic'
    assert [r for r in inert['conditions'] if r['condition'] == 'viral'] == []


def test_strict_evaluation_refuses_the_viral_numbers(db):
    out = api.compute(_viral_build(), db, dict(_opts(viral_stacks=6, protection='health'),
                                               strict=True))
    assert out['evaluation']['state'] == 'deterministic', 'a stated context needs no strictness'
    unresolved = api.compute(_viral_build(), db, {'strict': True})
    assert unresolved['evaluation']['state'] == 'refused'
    assert 'damage_to_health' in unresolved['evaluation']['refused_stats'] \
        or unresolved['result']['stats'].get('damage_to_health') is None


def test_the_trace_names_the_formula_and_its_source(db):
    out = api.compute(_viral_build(), db, _opts(viral_stacks=3, protection='health'))
    trace = out['result']['traces']['viral_amplifier']
    notes = ' '.join(str(n) for n in trace.get('notes') or [])
    assert '2 + (0.25 x (viral_stacks - 1))' in notes
    assert 'wiki.warframe.com' in notes
    assert trace['final'] == 2.5
    assert trace['modifiers'][0]['value'] == 2.5


# ------------------------------------------------------------------ the page contract

def test_the_page_shows_the_viral_numbers_without_doing_the_maths():
    stats = (REPO / 'static' / 'planner-stats.js').read_text(encoding='utf-8')
    assert "'viral_amplifier'" in stats and "'damage_to_health_expected_crit'" in stats
    page = ((REPO / 'static' / 'planner.js').read_text(encoding='utf-8')
            + (REPO / 'static' / 'planner-stats.js').read_text(encoding='utf-8'))
    for constant in ('4.25', '325', 'viral_stacks - 1'):
        assert constant not in page, 'the page must not carry the formula'


def test_the_page_states_the_target_and_sends_only_what_was_stated():
    page = (REPO / 'static' / 'planner.js').read_text(encoding='utf-8')
    assert 'function optionsFor' in page and 'function targetState' in page
    # an unstated field is absent from the request, so the engine can answer `unknown`
    assert 'if (t.faction) context.target_faction' in page
    assert 'statedNumber' in page
    html = (REPO / 'static' / 'planner.html').read_text(encoding='utf-8')
    for node in ('plTargetFaction', 'plTargetStacks', 'plTargetProtection', 'plTargetShot',
                 'plStrict', 'plEvalBody'):
        assert node in html, node
    assert 'not stated' in html, 'the empty option says what it means'
