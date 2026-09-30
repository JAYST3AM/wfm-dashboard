"""Phase 6: the mechanic registry, the migrated mechanics, and the new ones.

The registry is the source of the plumbing, so these tests check the *derivations* (accounting,
dispatch, trace destination, refusal registration) and the three new mechanics it carried: the wider
rider family, Heat's armour strip, and the stated-pool result. The falsification gate
(`design/_planner/phase6_gate.py --falsify`) is the other half: it breaks each invariant on purpose
and requires the break to be caught.
"""
import math
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from builds import (api, buffs, conditions, data, enemies, factions, ingest,  # noqa: E402
                    mechanics, schema, statuses, unsupported)

from test_builds_engine import FIXTURE_EQUIPMENT, FIXTURE_MODS, _mod_row  # noqa: E402

SERRATION = '/Fixture/Serration'


def _db(tmp_path=None, extra=None):
    """The fixture database, plus whatever synthetic cards a test needs (one level per rank).

    `FIXTURE_MODS` rows are the same tuples the other engine tests use; `_mod_row` turns one into the
    export shape (a level entry per rank, each carrying that rank's own card text).
    """
    mods = [ingest.normalise_mod(_mod_row(*row), {'/Fixture/BratonPrime': 'braton_prime'},
                                 {'file': 'phase6-test'})
            for row in FIXTURE_MODS]
    for mid, name, lines, rank in extra or []:
        mods.append(ingest.normalise_mod(
            _mod_row(mid, name, lines, 'Primary Mod', 'Rifle', 'madurai', rank),
            {'/Fixture/BratonPrime': 'braton_prime'}, {'file': 'phase6-test'}))
    equipment = [ingest.normalise_equipment(dict(raw, uniqueName=unique, name=name), kind,
                                            {'/Fixture/BratonPrime': 'braton_prime'}, {},
                                            {'file': 'phase6-test'})
                 for unique, name, kind, raw in FIXTURE_EQUIPMENT]
    return ingest.build_database(mods, equipment, {'generated_iso': 'x', 'game_version': 'x'})


def _build(mods):
    return {'config': 'A', 'equipment_id': '/Fixture/BratonPrime', 'equipment_rank': 30,
            'orokin': True, 'mastery_rank': 30,
            'slots': [{'kind': 'normal', 'index': i, 'polarity': None,
                       'mod': {'id': mid, 'rank': rank}} for i, (mid, rank) in enumerate(mods)]}


def _opts(target=None, target_faction=None, buffs_state=None, strict=False):
    context = {}
    if target_faction:
        context['target_faction'] = target_faction
    if target:
        context['target'] = target
    if buffs_state:
        context['buffs'] = {'on_kill': buffs_state}
    return {'context': context, 'strict': strict}


# ------------------------------------------------------------------ 6.1 the registry
def test_the_registry_declares_every_family_and_introspects():
    rows = mechanics.introspect()
    assert len(rows) >= 12
    for family in mechanics.FAMILIES:
        assert mechanics.by_family(family), family
    for row in rows:
        assert row['name'] and row['family'] and row['stage'] and row['source']
        assert row['states'] and row['trigger'] or row['emits_rows'] is False


def test_a_half_declared_mechanic_fails_loudly():
    good = dict(id='test_probe', name='Test probe', family='build_state', stage='damage_per_type',
                consumes=['attack.shot_index'],
                trigger=mechanics.ALL(mechanics.F('attack.shot_index')), trace='damage',
                source='test', evaluate='conditions.first_shot')
    mechanics._validate(mechanics.Mechanic(**good))
    bad = [
        dict(good, name=None), dict(good, family='nope'), dict(good, stage='nope'),
        dict(good, consumes=[], trigger=None), dict(good, trace=None),
        dict(good, source=''), dict(good, instant=False, averaged=False, strict=False,
                                    hypothetical=False),
        dict(good, refusal_codes=['no_such_code']), dict(good, withholds=['not_published']),
        dict(good, deps=['no_such_mechanic']), dict(good, required=['target.armor']),
        dict(good, trigger=mechanics.ALL(mechanics.F('target.armor'))),
        dict(good, evaluate='undotted'),
    ]
    for kwargs in bad:
        try:
            mechanics._validate(mechanics.Mechanic(**kwargs))
        except mechanics.MechanicDeclarationError:
            continue
        raise AssertionError('the validator accepted %r' % (kwargs,))


def test_every_declared_refusal_code_has_a_row():
    for code in mechanics.refusal_codes():
        assert unsupported.entry(code) is not None or code in conditions.REASON_CODES, code


def test_the_accounting_names_only_declared_fields():
    db = _db()
    out = api.compute(_build([(SERRATION, 10)]), db,
                      _opts(target_faction='grineer',
                            target={'protection': 'health', 'armor': 900,
                                    'corrosive_stacks': 4, 'heat_strip': 50}))
    declared = mechanics.consumed_fields()
    assert out['evaluation']['consumed']
    for field in out['evaluation']['consumed']:
        assert field in declared, field
    # TARGET_FIELDS is the registry's target union, in the historical order
    expected = {f.split('.', 1)[1] for f in declared if f.startswith('target.') and '.' in f}
    assert set(conditions.TARGET_FIELDS) == expected


def test_a_mechanic_is_only_evaluated_when_its_trigger_is_stated():
    db = _db()
    plain = api.compute(_build([(SERRATION, 10)]), db, _opts())
    assert not [c for c in plain['conditions']
                if c['condition'] in ('corrosive', 'heat', 'viral', 'pool', 'target_damage')]
    # a stated viral count alone asks the viral question and not the target path
    viral = api.compute(_build([(SERRATION, 10)]), db,
                        _opts(target={'protection': 'health', 'viral_stacks': 6}))
    assert [c['condition'] for c in viral['conditions']] == ['viral']
    assert viral['result']['target_damage'] is None


def test_trace_destinations_come_from_the_declarations():
    db = _db()
    out = api.compute(_build([(SERRATION, 10)]), db,
                      _opts(target_faction='grineer',
                            target={'protection': 'health', 'armor': 900, 'heat_strip': 50}))
    rows = out['result']['traces']['target_damage.impact']['modifiers']
    heat_rows = [r for r in rows if r.get('condition') == 'heat']
    assert heat_rows, [r.get('source') for r in rows]
    assert heat_rows[0]['strip'] == 0.5 and heat_rows[0]['formula']
    assert 'heat' in [c['condition'] for c in out['conditions']]


# ------------------------------------------------------------------ 6.3 the rider family
CRIT_LINES = ['On Kill: +%d%% Critical Chance for 20s. Stacks up to 3x.' % v
              for v in (90, 100, 110, 120)]


def test_a_crit_rider_lands_in_the_crit_trace_not_multishot():
    db = _db(extra=[('/Fixture/CritRider', 'Crit Rider', CRIT_LINES, 3)])
    out = api.compute(_build([(SERRATION, 10), ('/Fixture/CritRider', 3)]), db,
                      _opts(buffs_state={'stacks': 2}))
    rider = out['result']['riders'][0]
    assert rider['applied'] and rider['stat'] == 'critical_chance'
    assert rider['per_stack'] == 120.0 and rider['contribution'] == 240.0
    rows = out['result']['traces']['critical_chance']['modifiers']
    assert [r for r in rows if r.get('condition') == 'on_kill'], rows
    assert not [r for r in out['result']['traces']['multishot']['modifiers']
                if r.get('condition') == 'on_kill']
    over = api.compute(_build([(SERRATION, 10), ('/Fixture/CritRider', 3)]), db,
                       _opts(buffs_state={'stacks': 4}))
    assert over['result']['riders'][0]['state'] == 'unsupported'


def test_a_single_stack_rider_is_cap_one_and_rides_the_same_path():
    db = _db(extra=[('/Fixture/ReloadOnKill', 'Reload On Kill',
                     ['On Kill: +50% Reload Speed for 3s' for _ in range(4)], 3)])
    build = _build([(SERRATION, 10), ('/Fixture/ReloadOnKill', 3)])
    out = api.compute(build, db, _opts(buffs_state={'stacks': 1}))
    rider = out['result']['riders'][0]
    assert rider['cap'] == 1 and rider['applied'] and rider['stat'] == 'reload_speed'
    assert rider['contribution'] == 50.0
    rows = out['result']['traces']['reload_time']['modifiers']
    assert [r for r in rows if r.get('condition') == 'on_kill']
    assert api.compute(build, db, _opts(buffs_state={'stacks': 2}))['result']['riders'][0][
        'state'] == 'unsupported'


# ------------------------------------------------------------------ 6.4 Heat
def test_heat_strip_holds_only_the_ramps_own_values():
    db = _db()
    for strip, factor in ((15, 0.85), (30, 0.70), (40, 0.60), (50, 0.50)):
        out = api.compute(_build([(SERRATION, 10)]), db,
                          _opts(target_faction='grineer',
                                target={'protection': 'health', 'armor': 900,
                                        'heat_strip': strip}))
        assert abs(out['result']['target_damage']['armor']['effective'] - 900 * factor) < 1e-6
    junk = api.compute(_build([(SERRATION, 10)]), db,
                       _opts(target_faction='grineer',
                             target={'protection': 'health', 'armor': 900, 'heat_strip': 35}))
    assert junk['result']['target_damage'] is None
    row = [c for c in junk['conditions'] if c['condition'] == 'target_damage'][0]
    assert row['state'] == 'unsupported' and row['unsupported_code'] == 'heat_strip_value'


def test_heat_multiplicates_with_corrosive_as_the_wiki_writes_it():
    db = _db()
    out = api.compute(_build([(SERRATION, 10)]), db,
                      _opts(target_faction='grineer',
                            target={'protection': 'health', 'armor': 900,
                                    'corrosive_stacks': 4, 'heat_strip': 50}))
    armour = out['result']['target_damage']['armor']
    assert abs(armour['effective'] - 900 * 0.56 * 0.50) < 1e-6
    steps = [r['value'] for r in out['result']['traces']['target_damage.impact']['modifiers']
             if r.get('category') == 'mitigation_input']
    assert [round(s, 3) for s in steps] == [-396.0, -252.0]


def test_no_stated_heat_state_means_the_armour_is_not_touched():
    db = _db()
    out = api.compute(_build([(SERRATION, 10)]), db,
                      _opts(target_faction='grineer',
                            target={'protection': 'health', 'armor': 900}))
    assert out['result']['target_damage']['armor']['effective'] == 900.0
    assert 'heat' not in [c['condition'] for c in out['conditions']]


# ------------------------------------------------------------------ 6.5 the preset gap
def test_a_target_preset_is_refused_by_name_and_nothing_is_fabricated():
    db = _db()
    out = api.compute(_build([(SERRATION, 10)]), db, _opts(target={'preset': 'heavy-gunner-100'}))
    row = [c for c in out['conditions'] if c['condition'] == 'target_damage'][0]
    assert row['state'] == 'unsupported' and row['unsupported_code'] == 'preset_unavailable'
    assert 'no authoritative' in row['reason']
    assert out['result']['target_damage'] is None
    assert out['result']['stats']['damage_per_shot'] is not None


# ------------------------------------------------------------------ 6.6 the pool result
def test_the_pool_block_divides_only_a_stated_pool():
    db = _db()
    out = api.compute(_build([(SERRATION, 10)]), db,
                      _opts(target_faction='grineer',
                            target={'protection': 'health', 'armor': 900, 'health': 5000}))
    block = out['result']['pool']
    assert block['layer'] == 'health' and block['pool'] == 5000
    assert block['shots_required'] == int(math.ceil(5000 / block['damage_per_shot'] - 1e-9))
    assert out['result']['stats']['shots_to_kill'] == block['shots_required']
    # expected_shots is published trimmed (4 dp), like every other figure the engine reports
    assert abs(block['expected_shots']
               - 5000 / block['damage_per_shot_expected_crit']) < 1e-3
    assert 'pool' in out['result']['traces'] and out['result']['traces']['pool']['notes']
    # no pool stated -> no block, no key, no refusal
    quiet = api.compute(_build([(SERRATION, 10)]), db,
                        _opts(target_faction='grineer',
                              target={'protection': 'health', 'armor': 900}))
    assert 'pool' not in quiet['result']
    assert not [c for c in quiet['conditions'] if c['condition'] == 'pool']


def test_the_pool_result_never_uses_a_partial_damage_path():
    db = _db()
    unresolved = api.compute(_build([(SERRATION, 10)]), db,
                             _opts(target_faction='grineer',
                                   target={'protection': 'health', 'health': 5000}))
    row = [c for c in unresolved['conditions'] if c['condition'] == 'pool'][0]
    assert row['state'] == 'unknown' and row['unsupported_code'] == 'pool_unresolved'
    assert 'pool' not in unresolved['result']
    assert unresolved['result']['stats'].get('shots_to_kill') is None
    # the wrong pool for the stated landing is refused by name, never substituted
    mismatched = api.compute(_build([(SERRATION, 10)]), db,
                             _opts(target_faction='grineer',
                                   target={'protection': 'health', 'armor': 900, 'shields': 400}))
    row = [c for c in mismatched['conditions'] if c['condition'] == 'pool'][0]
    assert row['state'] == 'unsupported' and row['unsupported_code'] == 'pool_landing_mismatch'
    assert 'target.shields' in [m.get('field') for m in mismatched['unsupported']
                                if m.get('code') == 'context_unused']


# ------------------------------------------------------------------ hardening
def test_no_caller_json_makes_the_engine_raise():
    db = _db()
    cases = [
        {'target': {'heat_strip': 'ten'}}, {'target': {'heat_strip': True}},
        {'target': {'heat_strip': []}}, {'target': {'heat_strip': 10 ** 400}},
        {'target': {'heat_strip': -5}}, {'target': {'health': 'lots'}},
        {'target': {'health': -1}}, {'target': {'health': 10 ** 400}},
        {'target': {'protection': [], 'health': 5}},
        {'target': {'preset': {'id': 'x'}}}, {'target': {'preset': 10 ** 400}},
        {'target_faction': 'grineer',
         'target': {'protection': 'health', 'armor': 10 ** 12, 'health': 10 ** 12}},
    ]
    for context in cases:
        out = api.compute(_build([(SERRATION, 10)]), db, {'context': context})
        assert isinstance(out, dict) and out.get('evaluation'), context
        if out.get('result'):
            for value in (out['result']['stats'] or {}).values():
                assert not (isinstance(value, float) and math.isnan(value)), context


def test_dependencies_and_withholds_are_declared_and_ordered():
    ids = [row['id'] for row in mechanics.introspect()]
    for row in mechanics.introspect():
        for dep in row['deps']:
            assert dep in ids and ids.index(dep) < ids.index(row['id']), (row['id'], dep)
    assert mechanics.withholds_for(['target_damage']) == ('target_damage',)
    assert set(mechanics.withholds_for(['on_kill'])) <= set(mechanics.WITHHOLD_KEYS)
    assert mechanics.roster_contract('set') == 'distinct_legal_known'



# ------------------------------------------------------------------ review fixes (pinned)
def test_a_pool_only_refusal_leaves_the_phase_one_numbers_alone():
    """Review 3 F2 / review 1 F1: the blast radius is the blocked row's declaration."""
    db = _db()
    out = api.compute(_build([(SERRATION, 10)]), db,
                      {'strict': True,
                       'context': {'target_faction': 'grineer',
                                   'target': {'protection': 'health', 'armor': 900,
                                              'shields': 400}}})
    assert out['evaluation']['state'] == 'conditional'
    assert out['result']['stats']['damage_per_shot'] == 92.75
    assert out['result']['target_damage'] is not None


def test_a_withheld_per_shot_figure_takes_the_pool_block_with_it():
    """Review 1 F2 / review 3 F1: the pool divides the per-shot figures, so it is their mirror."""
    db2 = _db(extra=[('/Fixture/KillSwitch', 'Kill Switch',
                      ['On Kill: +%d%% Reload Speed for 3s' % v for v in (10, 20, 30, 40)], 3)])
    out = api.compute(_build([(SERRATION, 10), ('/Fixture/KillSwitch', 3)]), db2,
                      {'strict': True,
                       'context': {'target_faction': 'grineer',
                                   'target': {'protection': 'health', 'armor': 900,
                                              'health': 5000, 'corrosive_stacks': 4},
                                   'buffs': {'on_kill': {'stacks': 99}}}})
    assert out['evaluation']['state'] == 'refused'
    assert out['result']['stats'].get('damage_per_shot') is None
    pool = out['result'].get('pool')
    assert pool is not None
    assert pool['damage_per_shot'] is None and pool['shots_required'] is None
    assert out['result']['stats'].get('shots_to_kill') is None
    assert out['result']['traces']['pool']['final'] is None


def test_every_stated_target_field_is_reported_even_when_unconsumed():
    """Review 1 F3 / review 3 F7: a stated value is never dropped for not being hand-listed."""
    db = _db()
    out = api.compute(_build([(SERRATION, 10)]), db, _opts(target={'overguard': 500}))
    assert 'target.overguard' in (out['evaluation'].get('unused') or [])
    marker = [m for m in out['unsupported'] if m.get('code') == 'context_unused']
    assert any('overguard' in str(m.get('reason')) for m in marker), marker


def test_a_huge_but_finite_pool_never_raises_and_answers_or_refuses_by_name():
    """Review 2 F1: 1e308 / 0.5 is not finite; the answer is a named refusal, not an OverflowError."""
    db = _db()
    for pool in (10 ** 300, 10 ** 308, 10 ** 309):
        out = api.compute(_build([(SERRATION, 10)]), db,
                          _opts(target_faction='grineer',
                                target={'protection': 'shields', 'shields': pool,
                                        'corrosive_stacks': 0}))
        assert isinstance(out, dict) and out.get('ok') is True
        rows = [c for c in out['conditions'] if c['condition'] == 'pool']
        if pool == 10 ** 309:
            assert rows and rows[0]['state'] == 'unknown'
            assert out['result']['stats'].get('shots_to_kill') is None
        else:
            assert isinstance(out['result']['stats'].get('shots_to_kill'), int)


def test_a_rank_the_engine_cannot_drain_is_a_named_error_not_an_exception():
    """Review 2 F2: a 400-digit rank raised OverflowError out of the capacity arithmetic."""
    db = _db()
    payload = _build([(SERRATION, 10)])
    payload['slots'][0] = {'kind': 'normal', 'index': 0, 'polarity': 'naramon',
                           'mod': {'id': SERRATION, 'rank': 10 ** 400}}
    out = api.compute(payload, db, None)
    assert out.get('ok') is False
    codes = {e.get('code') for e in (out.get('validation') or {}).get('errors', [])}
    assert 'invalid_rank' in codes, codes


def test_the_averaged_state_names_fields_it_does_not_read():
    """Review 3 F6: the instant path named stray fields, the averaged path ignored them."""
    db = _db(extra=[('/Fixture/KillSwitch', 'Kill Switch',
                     ['On Kill: +%d%% Reload Speed for 3s' % v for v in (10, 20, 30, 40)], 3)])
    out = api.compute(_build([(SERRATION, 10), ('/Fixture/KillSwitch', 3)]), db,
                      _opts(buffs_state={'uptime': 0.5, 'stacks': 1, 'kills': 4}))
    rows = [c for c in out['conditions'] if c['condition'] == 'on_kill']
    assert rows and rows[0]['state'] == 'unknown' and 'kills' in rows[0]['reason']


def test_an_unknown_umbral_member_does_not_count_toward_the_set():
    """Review 3 F5: the roster contract is distinct + legal + known."""
    from builds import effects as effects_mod
    corpus = data.load(str(REPO / 'data' / 'build_data.json'))
    umbral_vitality = next(row for row in corpus['mods'].values()
                           if (row.get('name') or '') == 'Umbral Vitality')
    unknown = {'id': '/Fixture/UmbralEcho', 'name': 'Umbral Echo', 'max_rank': 10,
               'flags': {'set': True, 'set_id': umbral_vitality['flags']['set_id']},
               'effects': {'linear': [{'stat': 'ability_strength', 'value': 10.0,
                                       'unit': 'percent', 'category': 'base'}]}}
    totals, markers, _notes = effects_mod.collect_mod_effects(
        [{'kind': 'normal', 'index': 0, 'polarity': None, 'rank': 10, 'mod': umbral_vitality},
         {'kind': 'normal', 'index': 1, 'polarity': None, 'rank': 10, 'mod': unknown}])
    pieces = [row.get('set_pieces') for bucket in totals.values()
              for row in (bucket.get('rows') or []) if row.get('set_pieces') is not None]
    # one known member: no scaling off a count of two, and the unknown member is named
    assert not [p for p in pieces if p and p > 1], pieces
    assert any(m.get('code') == 'umbral_member_unknown' for m in markers), markers


def test_a_refused_rider_says_so_on_the_trace_its_declaration_names():
    """Review 3 F4: reload_speed's destination is reload_time, not the stat id."""
    db = _db(extra=[('/Fixture/ReloadOnKill', 'Reload On Kill',
                     ['On Kill: +%d%% Reload Speed for 3s' % v for v in (10, 20, 30, 40)], 3)])
    out = api.compute(_build([(SERRATION, 10), ('/Fixture/ReloadOnKill', 3)]), db, _opts())
    notes = out['result']['traces']['reload_time'].get('notes') or []
    assert any('Reload On Kill' in note for note in notes), notes


def test_the_validator_refuses_declarations_the_engine_could_never_reach():
    """Review 1 F5: trace keys, family/stage coherence, resolvable paths, real property types."""
    good = dict(id='test_probe2', name='Test probe', family='build_state',
                stage='damage_per_type', consumes=['attack.shot_index'],
                trigger=mechanics.ALL(mechanics.F('attack.shot_index')), trace='damage',
                source='test', evaluate='conditions.first_shot')
    for kwargs in (dict(good, trace='no_such_trace_key'),
                   dict(good, stat_traces={'x': 'no_such_trace'}, emits_rows=True),
                   dict(good, family='target_damage', stage='armour_transform'),
                   # a target_state mechanic may run damage_to_health (viral does) - but not
                   # damage_per_type, which no dispatcher in that family reaches
                   dict(good, family='target_state', stage='damage_per_type'),
                   dict(good, evaluate='statuses.no_such_function'),
                   dict(good, name=False), dict(good, source=False)):
        try:
            mechanics._validate(mechanics.Mechanic(**kwargs))
        except mechanics.MechanicDeclarationError:
            continue
        raise AssertionError('the validator accepted %r' % (kwargs,))
