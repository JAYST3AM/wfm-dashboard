"""The stated buff state and the first applied conditional rider (Phase 5, 5.3 + 5.4).

The rule this file enforces: the engine applies a rider's value only from state the caller
explicitly stated. It never simulates kills, never derives an uptime, never assumes a stack count,
and every averaged answer says so in words. All four Phase 4 states are reachable, and a rider
that is applied lands in the stat's own trace with its arithmetic.
"""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from builds import api, buffs, conditions, ingest  # noqa: E402
from test_builds_engine import FIXTURE_EQUIPMENT, FIXTURE_MODS, _mod_row  # noqa: E402

CHAMBER = '/Fixture/GalvanizedChamber'
SERRATION = '/Fixture/Serration'
# The fixture mod at rank 10: +80.3% Multishot, and "On Kill: +29.7% Multishot for 20s, 5x".
BASE_MS = 80.3
PER_STACK = 29.7


@pytest.fixture(scope='module')
def db():
    slugs = {'/Fixture/BratonPrime': 'braton_prime', '/Fixture/Excalibur': 'excalibur'}
    src = {'file': 'buff-state-test'}
    mods = [ingest.normalise_mod(_mod_row(*row), slugs, src)
            for row in list(FIXTURE_MODS) + PHASE5_MODS]
    equipment = [ingest.normalise_equipment(dict(raw, uniqueName=unique, name=name),
                                            kind, slugs, {}, src)
                 for unique, name, kind, raw in FIXTURE_EQUIPMENT]
    return ingest.build_database(mods, equipment,
                                 {'generated_iso': 'buff-state-test',
                                  'game_version': 'buff-state-test'})


def _build(mods=(), **over):
    build = {'config': 'A', 'equipment_id': '/Fixture/BratonPrime', 'equipment_rank': 30,
             'orokin': True, 'mastery_rank': 30, 'slots': []}
    for index, (mod_id, rank) in enumerate(mods):
        build['slots'].append({'kind': 'normal', 'index': index, 'polarity': None,
                               'mod': {'id': mod_id, 'rank': rank}})
    build.update(over)
    return build


def _opts(state=None, **extra):
    context = {}
    if state is not None:
        context['buffs'] = {'on_kill': state}
    context.update(extra)
    return {'context': context}


def _rider(out):
    return out['result']['riders'][0]


def test_the_module_selftest_passes():
    assert buffs.selftest() == 0


def test_with_no_state_the_rider_withholds_and_says_what_it_needs(db):
    out = api.compute(_build([(SERRATION, 10), (CHAMBER, 10)]), db)
    assert out['evaluation']['state'] == 'conditional'
    assert out['evaluation']['withheld'] == ['on_kill']
    assert out['result']['stats']['multishot'] == pytest.approx(1 + BASE_MS / 100.0)
    entry = _rider(out)
    assert entry['state'] == 'unknown' and entry['applied'] is False
    assert entry['per_stack'] == pytest.approx(PER_STACK) and entry['cap'] == 5
    marker = [m for m in out['unsupported'] if m.get('code') == 'conditional_effect'
              and m.get('mod') == CHAMBER][0]
    assert marker['state'] == 'unknown' and marker['reason_code'] == 'condition_unknown'
    row = [r for r in out['conditions'] if r['condition'] == 'on_kill'][0]
    assert row['state'] == 'unknown' and row['missing'] == ['buffs.on_kill']


def test_stated_stacks_apply_the_rider_end_to_end(db):
    out = api.compute(_build([(SERRATION, 10), (CHAMBER, 10)]), db,
                      _opts({'stacks': 3}))
    assert out['evaluation']['state'] == 'deterministic'
    assert out['result']['stats']['multishot'] == pytest.approx(1 + (BASE_MS + 3 * PER_STACK) / 100.0)
    entry = _rider(out)
    assert entry['applied'] is True and entry['contribution'] == pytest.approx(3 * PER_STACK)
    assert entry['mode'] == 'instant' and entry['stacks'] == 3
    # the marker is gone: nothing is refused any more
    assert not [m for m in out['unsupported'] if m.get('code') == 'conditional_effect'
                and m.get('mod') == CHAMBER]
    # the stat's own trace carries the rider row with its arithmetic
    rows = out['result']['traces']['multishot']['modifiers']
    rider_rows = [r for r in rows if r.get('condition') == 'on_kill']
    assert len(rider_rows) == 1 and rider_rows[0]['value'] == pytest.approx(3 * PER_STACK)
    assert '30' in rider_rows[0]['note'] or '29.7' in rider_rows[0]['note']
    # and the headline numbers moved with it
    assert out['result']['stats']['damage_per_shot'] == pytest.approx(
        92.75 * (1 + (BASE_MS + 3 * PER_STACK) / 100.0))


def test_the_averaged_form_states_its_assumption_and_never_invents_stacks(db):
    out = api.compute(_build([(SERRATION, 10), (CHAMBER, 10)]), db,
                      _opts({'stacks': 5, 'uptime': 0.65}))
    expected = BASE_MS + PER_STACK * 5 * 0.65
    # the stat is trimmed to 4 decimals for display, like every other engine figure
    assert out['result']['stats']['multishot'] == pytest.approx(1 + expected / 100.0, abs=1e-4)
    assert out['evaluation']['assumptions'] == [
        'averaged: 5 stacks at 65.0% uptime (stated by the caller)']
    entry = _rider(out)
    assert entry['mode'] == 'averaged' and entry['assumption']
    row = [r for r in out['conditions'] if r['condition'] == 'on_kill'][0]
    assert row['mode'] == 'averaged' and row['assumption']
    note = [m for m in out['result']['traces']['multishot']['modifiers']
            if m.get('condition') == 'on_kill'][0]['note']
    assert '65' in note and 'averaged' in note


def test_uptime_without_a_stack_count_refuses_rather_than_assuming(db):
    out = api.compute(_build([(SERRATION, 10), (CHAMBER, 10)]), db, _opts({'uptime': 0.65}))
    entry = _rider(out)
    assert entry['state'] == 'unknown' and entry['applied'] is False
    assert 'stack count' in entry['reason'] and out['result']['stats']['multishot'] ==         pytest.approx(1 + BASE_MS / 100.0)


def test_zero_stacks_and_inactive_are_reported_zeros_not_silence(db):
    for state in ({'stacks': 0}, {'active': False}):
        out = api.compute(_build([(SERRATION, 10), (CHAMBER, 10)]), db, _opts(state))
        assert out['result']['stats']['multishot'] == pytest.approx(1 + BASE_MS / 100.0)
        entry = _rider(out)
        assert entry['state'] == 'not_satisfied' and entry['applied'] is False
        assert not [m for m in out['unsupported'] if m.get('code') == 'conditional_effect'
                    and m.get('mod') == CHAMBER]
        assert any('On Kill' in n for n in out['result']['notes'])


def test_states_outside_the_models_domain_refuse_by_name(db):
    over = api.compute(_build([(SERRATION, 10), (CHAMBER, 10)]), db, _opts({'stacks': 6}))
    assert _rider(over)['state'] == 'unsupported'
    assert '5x cap' in _rider(over)['reason']
    for bad in ('3', 2.5, -1, True, [3]):
        out = api.compute(_build([(SERRATION, 10), (CHAMBER, 10)]), db, _opts({'stacks': bad}))
        assert _rider(out)['state'] == 'unknown', bad
    contradiction = api.compute(_build([(SERRATION, 10), (CHAMBER, 10)]), db,
                                _opts({'active': False, 'stacks': 3}))
    assert _rider(contradiction)['state'] == 'unknown'
    active_only = api.compute(_build([(SERRATION, 10), (CHAMBER, 10)]), db,
                              _opts({'active': True}))
    assert _rider(active_only)['state'] == 'unknown'
    truthy = api.compute(_build([(SERRATION, 10), (CHAMBER, 10)]), db,
                         _opts({'active': 'yes'}))
    assert _rider(truthy)['state'] == 'unknown'


def test_a_rider_worded_for_another_stat_still_refuses(db):
    """Only the enabled rider family is applied; the corpus keeps refusing, precisely."""
    other = _mod_row('/Fixture/KillSwitch', 'Kill Switch',
                     ['On Kill: +50% Reload Speed for 3s' for _ in range(4)],
                     'Primary Mod', 'Rifle', 'madurai', 4)
    slugs = {'/Fixture/BratonPrime': 'braton_prime'}
    src = {'file': 'buff-state-test'}
    db2 = ingest.build_database(
        [ingest.normalise_mod(other, slugs, src)],
        [ingest.normalise_equipment(dict(raw, uniqueName=unique, name=name), kind, slugs, {},
                                    src)
         for unique, name, kind, raw in FIXTURE_EQUIPMENT],
        {'generated_iso': 'x', 'game_version': 'x'})
    out = api.compute(_build([('/Fixture/KillSwitch', 3)]), db2, _opts({'stacks': 1}))
    marker = [m for m in out['unsupported'] if m.get('code') == 'conditional_effect'][0]
    assert marker['state'] == 'unsupported'
    assert marker.get('stat') == 'reload_speed'
    assert 'reload_speed' in marker['condition']['reason']
    assert out['result']['riders'] == []


def test_a_stated_buff_state_nothing_consumes_is_refused_by_name(db):
    out = api.compute(_build([(SERRATION, 10)]), db,
                      {'context': {'buffs': {'on_kill': {'stacks': 3}}}})
    assert out['evaluation']['unused'] == ['buffs.on_kill']
    assert any(m['code'] == 'context_unused' for m in out['unsupported'])
    # an unknown trigger is named the same way
    reload_state = api.compute(_build([(SERRATION, 10)]), db,
                               {'context': {'buffs': {'on_reload': {'stacks': 1}}}})
    assert reload_state['evaluation']['unused'] == ['buffs.on_reload']


CRIT_RIDER = '/Fixture/KillCrits'
PHASE5_MODS = [(CRIT_RIDER, 'Kill Crits',
                ['On Kill: +%d%% Critical Chance for 12s. Stacks up to 3x.' % (4 * (i + 1))
                 for i in range(11)], 'Primary Mod', 'Rifle', 'madurai', 4)]


def test_a_rider_on_another_stat_keeps_its_provenance(db, monkeypatch):
    """The rider plumbing is not multishot-shaped.

    The architecture review found that admitting a second stat to the enabled list applied the
    value but lost the row metadata on its trace, and that a refused rider's note landed on the
    multishot trace whatever stat it moved. This enables a crit-chance rider and checks both.
    """
    monkeypatch.setitem(buffs.ENABLED_STATS, 'critical_chance', 'critical_chance')
    out = api.compute(_build([(SERRATION, 10), (CRIT_RIDER, 10)]), db,
                      {'context': {'buffs': {'on_kill': {'stacks': 2}}}})
    entry = (out['result']['riders'] or [{}])[0]
    assert entry.get('stat') == 'critical_chance' and entry.get('state') == 'satisfied', entry
    rows = [m for m in out['result']['traces']['critical_chance']['modifiers']
            if m.get('condition') == 'on_kill']
    assert rows and rows[0].get('state') == 'satisfied' and rows[0].get('stacks') == 2, rows
    # a refused rider (no state) notes on ITS trace, not on multishot
    refused = api.compute(_build([(SERRATION, 10), (CRIT_RIDER, 10)]), db)
    notes = ' '.join(refused['result']['traces']['critical_chance'].get('notes') or [])
    assert 'rider is unknown' in notes, notes
    assert not [n for n in (refused['result']['traces']['multishot'].get('notes') or [])
                if 'Kill Crits' in n], refused['result']['traces']['multishot'].get('notes')


def test_strict_and_hypothetical_never_invent_a_stack_count(db):
    strict = api.compute(_build([(SERRATION, 10), (CHAMBER, 10)]), db, {'strict': True})
    assert strict['evaluation']['state'] == 'refused'
    assert strict['result']['stats']['multishot'] is not None      # multishot is not a refused stat
    hypothetical = api.compute(_build([(SERRATION, 10), (CHAMBER, 10)]), db,
                               {'hypothetical': True})
    assert hypothetical['result']['stats']['multishot'] == pytest.approx(1 + BASE_MS / 100.0)
    assert _rider(hypothetical)['applied'] is False
    # ... but a stated state is still applied under hypothetical: it was not a guess
    stated = api.compute(_build([(SERRATION, 10), (CHAMBER, 10)]), db,
                         dict(_opts({'stacks': 2}), hypothetical=True))
    assert stated['result']['stats']['multishot'] == pytest.approx(1 + (BASE_MS + 2 * PER_STACK) / 100.0)


def test_the_rider_value_comes_from_the_mods_own_rank_table(db):
    out = api.compute(_build([(SERRATION, 10), (CHAMBER, 5)]), db, _opts({'stacks': 2}))
    base5 = 7.3 * 6        # +43.8% Multishot at rank 5
    per5 = 2.7 * 6         # the rider's own value at rank 5
    assert out['result']['stats']['multishot'] == pytest.approx(1 + (base5 + 2 * per5) / 100.0)
    assert _rider(out)['per_stack'] == pytest.approx(per5)


def test_a_rider_never_moves_a_number_when_no_state_is_stated(db):
    plain = api.compute(_build([(SERRATION, 10), (CHAMBER, 10)]), db)
    inert = api.compute(_build([(SERRATION, 10), (CHAMBER, 10)]), db,
                        _opts({'uptime': 0.5}))
    for stat, value in plain['result']['stats'].items():
        assert inert['result']['stats'].get(stat) == value, stat
