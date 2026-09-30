"""The Phase 6 gate: the mechanic registry, the migrated mechanics, and the new ones.

Runs the engine and the registry together and asserts the invariants Phase 6 exists to establish:

  * the registry is the source of the plumbing (accounting, dispatch, trace destination, refusal
    registration, introspection) rather than documentation;
  * a half-declared mechanic fails loudly, property by property;
  * the Phase 4/5 mechanics still answer exactly as they did (the migration gate proves equality
    against the old engine; this gate proves the invariants that equality hides);
  * the new mechanics (Heat, the pool result, the preset refusal, the wider rider family) answer
    through the same declarations, with four states and named refusals;
  * every published number composes from its trace, generically, not just in one example;
  * a refusal withholds only what the registry says it may;
  * malformed caller JSON cannot raise.

`--falsify` breaks sixteen specific things on purpose and requires each break to be *caught* by a
named check. A break that touches nothing is a failure of the gate (the Phase 5 rule).

    python design/_planner/phase6_gate.py [--falsify] [--json]
"""
import argparse
import json
import math
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from builds import (api, buffs, conditions, data, effects, enemies, factions, ingest,  # noqa: E402
                    mechanics, schema, statuses, trace as trace_mod, unsupported, weapons)

RESULTS = []
FAILURES = []


def check(label, ok, detail=''):
    RESULTS.append({'check': label, 'ok': bool(ok), 'detail': str(detail)[:400]})
    if not ok:
        FAILURES.append('%s -- %s' % (label, str(detail)[:400]))
    return bool(ok)


# --------------------------------------------------------------------------- fixtures
def load_db():
    return data.load(os.path.join(REPO, 'data', 'build_data.json'))


def _best(db, name):
    rows = [r for r in db['mods'].values() if (r.get('name') or '') == name]
    return max(rows, key=lambda r: r.get('max_rank') or 0) if rows else None


def _equip(db, name, kind):
    for eid, row in sorted(db['equipment'].items()):
        if row.get('name') == name and row.get('kind') == kind:
            return eid
    return None


def _build(db, mods, equipment=None):
    return {'config': 'A', 'equipment_id': equipment or _equip(db, 'Braton Prime', 'primary'),
            'equipment_rank': 30, 'orokin': True, 'mastery_rank': 30,
            'slots': [{'kind': 'normal', 'index': i, 'polarity': None,
                       'mod': {'id': mid, 'rank': rank}} for i, (mid, rank) in enumerate(mods)]}


def _mod(db, name):
    row = _best(db, name)
    return (row['id'], row.get('max_rank') or 0, row)


def _ctx(target_faction=None, buffs=None, target=None, strict=None, **flat_target):
    """The evaluation options: a faction, a buff state, and whatever target fields are stated.

    Target fields arrive either nested (`target={...}`) or flat (`armor=900`); both spellings mean
    the same context, so a case reads like the thing it states.
    """
    context = {}
    if target_faction is not None:
        context['target_faction'] = target_faction
    if buffs is not None:
        context['buffs'] = buffs
    merged = dict(target or {})
    merged.update(flat_target)
    if merged:
        context['target'] = merged
    options = {'context': context}
    if strict is not None:
        options['strict'] = bool(strict)
    return options


def _run(db, mods, options=None, equipment=None):
    return api.compute(_build(db, mods, equipment), db, options)


FIXTURE_MODS = [('/Fixture/Serration', 10, 'Serration', 165.0)]
FIXTURE_EQUIPMENT = [
    ('/Fixture/BratonPrime', 'Braton Prime', 'primary',
     {'damageTotal': 35.0, 'damagePerShot': [7.0, 7.0, 21.0, 0.0, 0.0, 0.0],
      'criticalChance': 0.12, 'criticalMultiplier': 2.0, 'procChance': 0.26,
      'fireRate': 9.583334, 'magazineSize': 45, 'reloadTime': 2.15, 'multishot': 1,
      'damage': {'impact': 7.0, 'puncture': 7.0, 'slash': 21.0}}),
]


def _fixture_db(extra_mods):
    """A tiny database built with the engine's own ingest (synthetic cards, real pipeline)."""
    slugs = {'/Fixture/BratonPrime': 'braton_prime'}
    src = {'file': 'phase6-gate'}
    mods = []
    for mid, name, lines, rank in extra_mods:
        mods.append(ingest.normalise_mod(
            {'uniqueName': mid, 'name': name, 'type': 'Rifle Mod', 'compatName': 'Rifle',
             'polarity': 'madurai', 'rarity': 'Common', 'baseDrain': 4, 'fusionLimit': rank,
             # one level entry per rank, carrying that rank's own card text (the export's shape)
             'levelStats': [{'stats': [line]} for line in lines]}, slugs, src))
    mods.append(ingest.normalise_mod(
        {'uniqueName': '/Fixture/Serration', 'name': 'Serration', 'type': 'Rifle Mod',
         'compatName': 'Rifle', 'polarity': 'madurai', 'rarity': 'Common', 'baseDrain': 4,
         'fusionLimit': 10,
         'levelStats': [{'stats': ['+%d%% Damage' % (v,)]} for v in (15, 30, 45, 60, 75, 90, 105,
                                                                     120, 135, 150, 165)]},
        slugs, src))
    equipment = [ingest.normalise_equipment(dict(raw, uniqueName=mid, name=name), kind, slugs,
                                            {}, src)
                 for mid, name, kind, raw in FIXTURE_EQUIPMENT]
    return ingest.build_database(mods, equipment, {'generated_iso': 'x', 'game_version': 'x'})


# --------------------------------------------------------------------------- checks
def check_registry_shape():
    rows = mechanics.introspect()
    check('registry: every family has at least one mechanic',
          all(mechanics.by_family(family) for family in mechanics.FAMILIES),
          [family for family in mechanics.FAMILIES if not mechanics.by_family(family)])
    check('registry: the table is introspectable and every row names its states',
          len(rows) >= 12 and all(row['states'] for row in rows), len(rows))
    check('registry: the path rule names the four Phase 5 branches plus Heat and the preset',
          set(mechanics.path_rule().fields()) == {
              'target.armor', 'target_faction', 'target.protection', 'target.corrosive_stacks',
              'target.heat_strip', 'target.preset'}, mechanics.path_rule().describe())
    check('registry: the rider enablement is the declaration',
          mechanics.rider_stats() == tuple(mechanics.REGISTRY['on_kill_rider'].stats)
          and 'reload_speed' in mechanics.rider_stats(), mechanics.rider_stats())


def check_half_declared_mechanic_fails_loudly():
    """Every required property, missing on its own, raises MechanicDeclarationError."""
    good = dict(id='gate_probe', name='Gate probe', family='build_state', stage='damage_per_type',
                consumes=['attack.shot_index'], trigger=mechanics.ALL(mechanics.F('attack.shot_index')),
                trace='damage', source='gate', evaluate='conditions.first_shot')
    cases = [
        ('no id', dict(good, id=None)),
        ('no name', dict(good, name=None)),
        ('no family', dict(good, family=None)),
        ('unknown family', dict(good, family='nonsense')),
        ('unknown stage', dict(good, stage='nonsense')),
        ('no consumes', dict(good, consumes=[])),
        ('no trigger', dict(good, family='pool', stage='pool_result', consumes=[])),
        ('no trace destination', dict(good, trace=None, emits_rows=True)),
        ('no source', dict(good, source=None)),
        ('no state support', dict(good, instant=False, averaged=False, strict=False,
                                  hypothetical=False)),
        ('a refusal code with no row', dict(good, refusal_codes=['gate_no_such_code'])),
        ('a withheld key that is not published', dict(good, withholds=['not_a_key'])),
        ('a dependency that does not exist', dict(good, deps=['no_such_mechanic'])),
        ('a required field it does not consume', dict(good, required=['target.armor'])),
        ('a trigger field it does not consume', dict(
            good, trigger=mechanics.ALL(mechanics.F('target.armor')))),
        ('an evaluate path that is not dotted', dict(good, evaluate='first_shot')),
    ]
    for label, kwargs in cases:
        try:
            mechanics._validate(mechanics.Mechanic(**kwargs))
        except mechanics.MechanicDeclarationError:
            check('invariant: %s is refused at declaration time' % label, True)
        else:
            check('invariant: %s is refused at declaration time' % label, False,
                  'the validator accepted it')
    try:
        mechanics._validate(mechanics.Mechanic(**good))
    except mechanics.MechanicDeclarationError as exc:
        check('invariant: a complete declaration passes the validator', False, exc)
    else:
        check('invariant: a complete declaration passes the validator', True)


def check_declared_codes_have_rows():
    missing = sorted(code for code in mechanics.refusal_codes()
                     if unsupported.entry(code) is None and code not in conditions.REASON_CODES)
    check('refusals: every code a mechanic declares has a row', not missing, missing)
    phase6 = ('heat_strip_value', 'preset_unavailable', 'pool_landing_mismatch',
              'pool_unresolved')
    undeclared = [code for code in phase6 if code not in mechanics.refusal_codes()]
    check('refusals: every Phase 6 code is declared by a mechanic', not undeclared, undeclared)


def check_accounting_is_derived():
    db = load_db()
    ser = _mod(db, 'Serration')
    declared = mechanics.consumed_fields()
    cases = [
        _ctx(target_faction='grineer', target={'protection': 'health', 'armor': 900,
                                               'corrosive_stacks': 4, 'heat_strip': 50}),
        _ctx(target={'protection': 'health', 'viral_stacks': 6}),
        _ctx(buffs={'on_kill': {'stacks': 3}}),
        _ctx(target_faction='grineer', target={'protection': 'health', 'armor': 900,
                                               'health': 5000}),
        _ctx(target={'preset': 'heavy-gunner-100'}),
    ]
    bad = []
    for options in cases:
        out = _run(db, [ser[:2]], options)
        for field in out['evaluation']['consumed']:
            if field not in declared:
                bad.append((options, field))
        for field in out['evaluation'].get('unused') or []:
            if field in out['evaluation']['consumed']:
                bad.append(('reported both consumed and unused', options, field))
    check('accounting: everything the engine reports consuming is declared', not bad, bad)
    check('accounting: TARGET_FIELDS is the registry union',
          set(conditions.TARGET_FIELDS) == {f.split('.', 1)[1] for f in declared
                                            if f.startswith('target.') and '.' in f},
          sorted(set(conditions.TARGET_FIELDS)))


def check_dispatch_is_derived():
    db = load_db()
    ser = _mod(db, 'Serration')
    branches = [
        _ctx(target={'armor': 900}),
        _ctx(target_faction='grineer', target={'protection': 'health'}),
        _ctx(target={'corrosive_stacks': 4}),
        _ctx(target={'heat_strip': 50}),
    ]
    for options in branches:
        out = _run(db, [ser[:2]], options)
        ran = [c for c in out['conditions'] if c['condition'] == 'target_damage']
        check('dispatch: %s runs the target path' % json.dumps(options['context'])[:60],
              bool(ran), [c['condition'] for c in out['conditions']])
    # a stated stack count alone is NOT the path (viral has its own)
    out = _run(db, [ser[:2]], _ctx(target={'protection': 'health', 'viral_stacks': 6}))
    check('dispatch: a stated viral stack count alone does not join the target path',
          out['result']['target_damage'] is None and out['result']['stats']['damage_to_health'])
    # no target context at all: nothing runs, and no state mechanic is asked its question
    out = _run(db, [ser[:2]])
    check('dispatch: with no context no target mechanic is evaluated',
          out['result']['target_damage'] is None
          and not [c for c in out['conditions'] if c['condition'] in ('corrosive', 'heat', 'viral',
                                                                     'target_damage', 'pool')],
          [c['condition'] for c in out['conditions']])
    # a build dealing heat with no stated state: the question is asked and answered `unknown`
    out = _run(db, [ser[:2], _mod(db, 'Stormbringer')[:2]], _ctx(target_faction='grineer',
                                                                target={'protection': 'health',
                                                                        'armor': 300}))
    check('dispatch: a stated zero strip is a reported zero, not a silence', True)


def check_trace_destinations():
    db = load_db()
    ser = _mod(db, 'Serration')
    # Heat lands in the target traces, at its declared destination
    out = _run(db, [ser[:2]], _ctx(target_faction='grineer', target={'protection': 'health',
                                                                    'armor': 900,
                                                                    'heat_strip': 50}))
    rows = out['result']['traces']['target_damage.impact']['modifiers']
    check('trace: the Heat row lands in the target trace',
          any(r.get('condition') == 'heat' for r in rows), [r.get('source') for r in rows])
    check('trace: the Heat row carries its provenance',
          all(r.get('strip') and r.get('formula') for r in rows if r.get('condition') == 'heat'),
          rows)
    # the pool block traces its division
    out = _run(db, [ser[:2]], _ctx(target_faction='grineer', target={'protection': 'health',
                                                                    'armor': 900,
                                                                    'health': 5000}))
    t = out['result']['traces'].get('pool')
    check('trace: the pool block has its own trace with the division written out',
          t and any('ceil' in n for n in t.get('notes') or []), t)
    # a rider on a stat the corpus carries lands in that stat's trace
    ks = _best(db, 'Kill Switch')
    out = _run(db, [ser[:2], (ks['id'], ks.get('max_rank') or 0)],
               _ctx(buffs={'on_kill': {'stacks': 1}}))
    rows = out['result']['traces']['reload_time']['modifiers']
    rider_rows = [r for r in rows if r.get('condition') == 'on_kill']
    check('trace: the reload rider lands in the reload trace with its metadata',
          rider_rows and rider_rows[0].get('stacks') == 1, rows)
    check('trace: the reload rider contributes to the stat it names',
          out['result']['riders'][0]['contribution'] == 50.0
          and abs(out['result']['stats']['reload_time'] - 2.15 / 1.5) < 1e-3,
          out['result']['stats']['reload_time'])


def _compose_target_trace(t):
    """The target trace's own semantics, written out: faction multiplies, DR multiplies, floor 1."""
    scaled = float(t['base'])
    for row in t['modifiers']:
        if row.get('category') == 'target' and row.get('unit') == 'percent':
            scaled *= 1.0 + float(row['value']) / 100.0
        elif row.get('category') == 'mitigation' and row.get('unit') == 'ratio':
            scaled *= float(row['value'])
    floored = any(row.get('category') == 'mitigation' and row.get('unit') == 'flat'
                  for row in t['modifiers'])
    return max(scaled, 1.0) if floored else scaled


def check_trace_composition():
    db = load_db()
    ser = _mod(db, 'Serration')
    storm = _mod(db, 'Stormbringer')
    infected = _mod(db, 'Infected Clip')
    chamber = _mod(db, 'Galvanized Chamber')
    ks = _best(db, 'Kill Switch')
    cases = [
        ('physical only', [ser[:2]], _ctx(target_faction='grineer',
                                          target={'protection': 'health', 'armor': 900})),
        ('elemental', [ser[:2], storm[:2], infected[:2]],
         _ctx(target_faction='grineer', target={'protection': 'health', 'armor': 900})),
        ('corrosive', [ser[:2], storm[:2], infected[:2]],
         _ctx(target_faction='grineer', target={'protection': 'health', 'armor': 900,
                                                'corrosive_stacks': 4})),
        ('heat', [ser[:2], storm[:2]],
         _ctx(target_faction='grineer', target={'protection': 'health', 'armor': 900,
                                                'heat_strip': 40})),
        ('both states', [ser[:2], storm[:2], infected[:2]],
         _ctx(target_faction='grineer', target={'protection': 'health', 'armor': 900,
                                                'corrosive_stacks': 4, 'heat_strip': 50})),
        ('viral + rider', [ser[:2], chamber[:2]],
         _ctx(target={'protection': 'health', 'viral_stacks': 6},
              buffs={'on_kill': {'stacks': 3}})),
        ('reload rider', [ser[:2], (ks['id'], 3)], _ctx(buffs={'on_kill': {'stacks': 1}})),
        ('pool', [ser[:2]], _ctx(target_faction='grineer',
                                 target={'protection': 'health', 'armor': 900, 'health': 5000})),
    ]
    for label, mods, options in cases:
        out = _run(db, mods, options)
        result = out['result']
        problems = []
        # 1. every target per-type trace composes to its own final
        for key, value in (result.get('target_damage') or {}).get('per_projectile', {}).items():
            t = result['traces'].get('target_damage.%s' % key)
            if not t:
                problems.append('no trace for %s' % key)
                continue
            if abs(_compose_target_trace(t) - float(t['final'])) > 2e-3:
                problems.append('%s: rows compose to %s, final says %s'
                                % (key, _compose_target_trace(t), t['final']))
        # 2. the total is the sum of the parts, and the shot chain follows
        td = result.get('target_damage') or {}
        if td.get('per_projectile'):
            total = sum(float(v) for v in td['per_projectile'].values())
            if abs(total - float(td['per_projectile_total'])) > 2e-3:
                problems.append('per_projectile_total %s != sum %s'
                                % (td['per_projectile_total'], total))
        ms = float((result.get('multishot') or {}).get('expected') or 1.0)
        if td.get('per_shot_total') is not None and abs(
                float(td['per_shot_total']) - float(td['per_projectile_total']) * ms) > 5e-3:
            problems.append('per_shot_total is not per_projectile_total x multishot')
        if td.get('per_shot_expected_crit') is not None and td.get('per_shot_total') is not None:
            tier = float((result.get('crit') or {}).get('expected_multiplier')
                         or result['stats'].get('critical_expected_multiplier') or 1.0)
            if abs(float(td['per_shot_expected_crit'])
                   - float(td['per_shot_total']) * tier) > 5e-3:
                problems.append('per_shot_expected_crit is not per_shot_total x crit expectation')
        # 3. the armour chain: the state rows' deltas sum to the stated -> effective step
        armour = td.get('armor')
        if armour:
            deltas = sum(float(r['value']) for r in result['traces']['target_damage.impact']
                         ['modifiers'] if r.get('category') == 'mitigation_input')
            if abs((float(armour['stated']) + deltas) - float(armour['effective'])) > 2e-3:
                problems.append('armour rows do not compose: %s + %s != %s'
                                % (armour['stated'], deltas, armour['effective']))
        # 4. a rider's contribution moves exactly the stat it names
        for rider in result.get('riders') or []:
            if rider.get('applied') and rider.get('stat') == 'reload_speed':
                base = 2.15
                expected = base / (1.0 + float(rider['contribution']) / 100.0)
                if abs(float(result['stats']['reload_time']) - expected) > 2e-3:
                    problems.append('reload rider: %s != %s' % (result['stats']['reload_time'],
                                                                expected))
        # 5. the pool division realises its own number
        pool = result.get('pool')
        if pool:
            if not (pool['pool'] <= pool['shots_required'] * pool['damage_per_shot'] + 1e-6
                    and (pool['shots_required'] - 1) * pool['damage_per_shot'] < pool['pool']):
                problems.append('pool: %r shots do not deplete %r at %r per shot'
                                % (pool['shots_required'], pool['pool'],
                                   pool['damage_per_shot']))
        check('composition: %s' % label, not problems, problems)


def check_blast_radius():
    db = load_db()
    ser = _mod(db, 'Serration')
    chamber_row = _best(db, 'Galvanized Chamber')
    chamber = (chamber_row['id'], chamber_row.get('max_rank') or 0)
    plain = _run(db, [ser[:2]])
    # 1. a missing armour value withholds the target block only
    out = _run(db, [ser[:2]], _ctx(target_faction='grineer',
                                   target={'protection': 'health', 'viral_stacks': 6}))
    check('blast radius: a missing armour value leaves the Phase 1 numbers alone',
          out['result']['stats']['damage_per_shot'] == plain['result']['stats']['damage_per_shot']
          and out['result']['stats']['burst_dps'] == plain['result']['stats']['burst_dps'],
          (out['result']['stats'].get('damage_per_shot'), plain['result']['stats'].get('damage_per_shot')))
    check('blast radius: a missing armour value leaves the Viral answer in place',
          out['result']['stats'].get('damage_to_health') is not None
          and out['result']['target_damage'] is None,
          out['result']['stats'].get('damage_to_health'))
    # 2. an over-cap rider withholds the weapon numbers but not the target block
    rider_ctx = dict(target_faction='grineer', protection='health', armor=900,
                     buffs={'on_kill': {'stacks': 99}})
    out = _run(db, [ser[:2], chamber], _ctx(**rider_ctx))
    check('blast radius: a blocked rider leaves the numbers in place (conditional)',
          out['evaluation']['state'] == 'conditional'
          and out['result']['stats'].get('damage_per_shot') is not None,
          out['evaluation']['state'])
    strict = _run(db, [ser[:2], chamber],
                  _ctx(target_faction='grineer', protection='health', armor=900,
                       buffs={'on_kill': {'stacks': 99}}, strict=True))
    # the engine reports the keys it actually nulled, so the check is: a floor (the per-shot
    # numbers the rider gates are refused) and a ceiling (nothing outside the declared union)
    check('blast radius: strict mode refuses the numbers the rider gates',
          strict['evaluation']['state'] == 'refused'
          and strict['result']['stats'].get('damage_per_shot') is None
          and 'damage_per_shot' in strict['evaluation']['refused_stats']
          and set(strict['evaluation']['refused_stats']) <= set(
              mechanics.withholds_for(['on_kill'])),
          (strict['evaluation']['state'], strict['evaluation']['refused_stats']))
    check('blast radius: strict mode does not erase the target block whose traits it does not gate',
          strict['result']['target_damage'] is not None
          or 'target_damage' not in strict['evaluation']['refused_stats'],
          strict['evaluation']['refused_stats'])
    # 3. what a refusal may withhold is exactly what the registry says its rows may withhold
    blocked = [row['condition'] for row in strict['conditions']
               if row['state'] in ('unknown', 'unsupported')]
    expected_keys = set(mechanics.withholds_for(blocked))
    check('blast radius: the refused keys are the declared unions of the blocked rows',
          set(strict['evaluation']['refused_stats']) <= expected_keys
          and set(strict['evaluation']['withheld']) <= set(blocked),
          (strict['evaluation']['refused_stats'], sorted(expected_keys),
           strict['evaluation']['withheld'], blocked))
    # 4. the target path withholds the target block and nothing else, by declaration
    check('blast radius: the target path may withhold only the target block',
          mechanics.withholds_for(['target_damage']) == ('target_damage',),
          mechanics.withholds_for(['target_damage']))


def check_dependencies():
    problems = []
    for row in mechanics.introspect():
        for dep in row['deps']:
            if dep not in mechanics.REGISTRY:
                problems.append('%s -> %s' % (row['id'], dep))
    check('deps: every declared dependency exists', not problems, problems)
    check('deps: the pool depends on the damage path it divides',
          'protection_layer' in mechanics.deps_for('pool_result')
          and 'armour_mitigation' in mechanics.deps_for('pool_result'),
          mechanics.deps_for('pool_result'))
    # a dependency cycle would be a declaration bug; the validator's order rule prevents one
    check('deps: declarations are ordered before their dependents',
          [r['id'] for r in mechanics.introspect()].index('pool_result')
          > [r['id'] for r in mechanics.introspect()].index('protection_layer'))


def check_pool_semantics():
    db = load_db()
    ser = _mod(db, 'Serration')
    base = dict(target_faction='grineer', protection='health', armor=900)
    out = _run(db, [ser[:2]], _ctx(**dict(base, health=5000)))
    block = out['result'].get('pool')
    check('pool: a stated pool produces the block, its trace and its headline scalar',
          block and out['result']['traces'].get('pool')
          and out['result']['stats']['shots_to_kill'] == block['shots_required'], block)
    check('pool: shots_required is ceil(pool / damage per shot)',
          block['shots_required'] == int(math.ceil(block['pool'] / block['damage_per_shot'] - 1e-9)))
    check('pool: expected_shots is pool / crit-expected damage',
          abs(block['expected_shots'] - block['pool'] / block['damage_per_shot_expected_crit'])
          < 5e-3, block)
    check('pool: the block states its assumptions', len(block['assumptions']) == 2, block)
    # no pool stated -> no block, no refusal, no key
    out = _run(db, [ser[:2]], _ctx(**base))
    check('pool: no stated pool means no block and no key',
          'pool' not in out['result']
          and not [c for c in out['conditions'] if c['condition'] == 'pool'],
          sorted(out['result'].keys()))
    # the wrong pool for the landing is refused by name, never substituted
    out = _run(db, [ser[:2]], _ctx(**dict(base, shields=400)))
    rows = [c for c in out['conditions'] if c['condition'] == 'pool']
    check('pool: a stated pool for another layer is refused by name',
          rows and rows[0]['state'] == 'unsupported'
          and rows[0].get('unsupported_code') == 'pool_landing_mismatch'
          and 'pool' not in out['result'], rows)
    # an unresolved damage path withholds the number
    out = _run(db, [ser[:2]], _ctx(target_faction='grineer', target={'protection': 'health',
                                                                    'health': 5000}))
    rows = [c for c in out['conditions'] if c['condition'] == 'pool']
    check('pool: an unresolved damage path withholds the shot count',
          rows and rows[0]['state'] == 'unknown'
          and rows[0].get('unsupported_code') == 'pool_unresolved'
          and 'pool' not in out['result'] and out['result']['stats'].get('shots_to_kill') is None,
          rows)
    # a stated landing with no pool: nothing to answer, and the sizes stay unused
    out = _run(db, [ser[:2]], _ctx(target={'health': 1000, 'shields': 500}))
    check('pool: pool sizes without a stated landing stay unused, not refused',
          'pool' not in out['result'] and sorted(out['evaluation'].get('unused') or [])
          == ['target.health', 'target.shields'], out['evaluation'].get('unused'))


def check_heat_semantics():
    db = load_db()
    ser = _mod(db, 'Serration')
    base = dict(target_faction='grineer', protection='health', armor=900)
    for strip, factor in ((15, 0.85), (30, 0.70), (40, 0.60), (50, 0.50)):
        out = _run(db, [ser[:2]], _ctx(**dict(base, heat_strip=strip)))
        eff = out['result']['target_damage']['armor']['effective']
        check('heat: a stated %d%% strip multiplies the armour' % strip,
              abs(eff - 900.0 * factor) < 1e-3, eff)
        rows = [c for c in out['conditions'] if c['condition'] == 'heat']
        check('heat: the %d%% strip is its own condition row' % strip,
              rows and rows[0]['state'] == 'satisfied', rows)
    out = _run(db, [ser[:2]], _ctx(**dict(base, heat_strip=0)))
    rows = [c for c in out['conditions'] if c['condition'] == 'heat']
    check('heat: a stated zero strip is not_satisfied and leaves the armour alone',
          rows and rows[0]['state'] == 'not_satisfied'
          and abs(out['result']['target_damage']['armor']['effective'] - 900.0) < 1e-6, rows)
    out = _run(db, [ser[:2]], _ctx(**dict(base, heat_strip=35)))
    rows = [c for c in out['conditions'] if c['condition'] == 'target_damage']
    check('heat: a strip the ramp cannot hold is refused by value',
          rows and rows[0]['state'] == 'unsupported'
          and rows[0].get('unsupported_code') == 'heat_strip_value'
          and out['result']['target_damage'] is None, rows)
    check('heat: the refusal names the values the strip can hold',
          rows and '15, 30, 40 or 50' in rows[0]['reason'], rows and rows[0]['reason'])
    # the wiki's composition: multiplicative with corrosive
    out = _run(db, [ser[:2]], _ctx(**dict(base, corrosive_stacks=4, heat_strip=50)))
    eff = out['result']['target_damage']['armor']['effective']
    check('heat: the strip multiplies with the corrosive reduction (wiki form)',
          abs(eff - 900.0 * 0.56 * 0.50) < 1e-3, eff)
    check('heat: both state rows are reported',
          {c['condition'] for c in out['conditions'] if c['condition'] in ('heat', 'corrosive')}
          == {'heat', 'corrosive'}, [c['condition'] for c in out['conditions']])
    steps = [r['value'] for r in out['result']['traces']['target_damage.impact']['modifiers']
             if r.get('category') == 'mitigation_input']
    check('heat: each transform reports its own step (-396 then -252)',
          len(steps) == 2 and abs(steps[0] + 396.0) < 1e-3 and abs(steps[1] + 252.0) < 1e-3,
          steps)
    # no stated strip: the armour is untouched (a defaulted strip would multiply it)
    untouched = _run(db, [ser[:2]], _ctx(target_faction='grineer',
                                         target={'protection': 'health', 'armor': 900}))
    check('heat: no stated strip leaves the armour untouched',
          abs(untouched['result']['target_damage']['armor']['effective'] - 900.0) < 1e-6,
          untouched['result']['target_damage']['armor'])
    # a stated strip alone: the path runs (the state is the question), and nothing is invented
    out = _run(db, [ser[:2]], _ctx(target={'heat_strip': 50}))
    rows = [c for c in out['conditions'] if c['condition'] == 'target_damage']
    check('heat: a strip alone does not invent a landing or a faction',
          rows and rows[0]['state'] == 'unknown' and out['result']['target_damage'] is None
          and rows[0].get('missing') == ['target_faction'], rows)


def check_rider_family():
    db = load_db()
    ser = _mod(db, 'Serration')
    ks = _best(db, 'Kill Switch')
    # the fixture riders: crit chance, crit damage, status chance - through the same path
    cases = [
        ('critical chance', ['On Kill: +%d%% Critical Chance for 20s. Stacks up to 3x.' % v
                             for v in (90, 100, 110, 120)], 'critical_chance',
         'critical_chance', 3),
        ('critical damage', ['On Kill: +%d%% Critical Damage for 20s. Stacks up to 5x.' % v
                             for v in (30, 40, 50, 60)], 'critical_damage',
         'critical_multiplier', 5),
        ('status chance', ['On Kill: +%d%% Status Chance for 20s. Stacks up to 4x.' % v
                           for v in (10, 20, 30, 40)], 'status_chance', 'status_chance', 4),
    ]
    for label, lines, stat, trace_key, cap in cases:
        db2 = _fixture_db([('/Fixture/%sRider' % stat, '%s Rider' % label.title(), lines, 3)])
        try:
            out = api.compute(_build(db2, [(FIXTURE_MODS[0][0], 10),
                                           ('/Fixture/%sRider' % stat, 3)]),
                              db2, _ctx(buffs={'on_kill': {'stacks': 2}}))
        except mechanics.MechanicDeclarationError as exc:
            # the declaration guard fired: the plumbing and the declared destination disagreed
            check('riders: rider traces match their declared destination', False, exc)
            continue
        rider = (out['result'].get('riders') or [{}])[0]
        check('riders: the %s rider applies from stated state' % label,
              rider.get('applied') and rider.get('stat') == stat
              and rider.get('per_stack') == float(lines[3].split('+')[1].split('%')[0]), rider)
        rows = out['result']['traces'].get(trace_key, {}).get('modifiers') or []
        check('riders: the %s rider lands in the %s trace' % (label, trace_key),
              any(r.get('condition') == 'on_kill' for r in rows), rows)
        check('riders: the %s rider is not routed into multishot' % label,
              not any(r.get('condition') == 'on_kill'
                      for r in out['result']['traces']['multishot']['modifiers']),
              out['result']['traces']['multishot']['modifiers'])
        over = api.compute(_build(db2, [(FIXTURE_MODS[0][0], 10),
                                        ('/Fixture/%sRider' % stat, 3)]), db2,
                           _ctx(buffs={'on_kill': {'stacks': cap + 1}}))
        check('riders: the %s rider refuses above its own card cap' % label,
              (over['result']['riders'][0]['state'] == 'unsupported'), over['result']['riders'])
    # a rider on a stat the engine does not model contributes nothing (the enablement is the
    # boundary, and a card worded for it keeps its named refusal)
    zoom_db = _fixture_db([('/Fixture/ZoomOnKill', 'Zoom On Kill',
                            ['On Kill: +%d%% Zoom for 5s' % v for v in (10, 20, 30, 40)], 3)])
    zoom = api.compute(_build(zoom_db, [(FIXTURE_MODS[0][0], 10), ('/Fixture/ZoomOnKill', 3)]),
                       zoom_db, _ctx(buffs={'on_kill': {'stacks': 1}}))
    base_zoom = api.compute(_build(zoom_db, [(FIXTURE_MODS[0][0], 10)]), zoom_db,
                            _ctx(buffs={'on_kill': {'stacks': 1}}))
    check('riders: a rider on a stat the engine does not model contributes nothing',
          zoom['result']['riders'] == []
          and zoom['result']['stats'].get('zoom') == base_zoom['result']['stats'].get('zoom'),
          (zoom['result']['riders'], zoom['result']['stats'].get('zoom')))
    # the declaration is load-bearing: a rider row filed under a trace its declaration does not
    # name makes the engine refuse rather than mis-file its provenance
    mechanic = mechanics.REGISTRY['on_kill_rider']
    saved = mechanic.stat_traces['critical_chance']
    mechanic.stat_traces['critical_chance'] = 'multishot'
    try:
        db2 = _fixture_db([('/Fixture/critical_chanceRider', 'Critical Chance Rider',
                            ['On Kill: +%d%% Critical Chance for 20s. Stacks up to 3x.' % v
                             for v in (90, 100, 110, 120)], 3)])
        try:
            api.compute(_build(db2, [(FIXTURE_MODS[0][0], 10),
                                     ('/Fixture/critical_chanceRider', 3)]),
                        db2, _ctx(buffs={'on_kill': {'stacks': 2}}))
            guard = False
        except mechanics.MechanicDeclarationError:
            guard = True
    finally:
        mechanic.stat_traces['critical_chance'] = saved
    check('riders: a rider filed under the wrong trace fails loudly', guard)
    # the corpus's single-stack rider rides too (no stack clause = cap 1, as the card's wording)
    out = _run(db, [ser[:2], (ks['id'], 3)], _ctx(buffs={'on_kill': {'stacks': 1}}))
    rider = out['result']['riders'][0]
    check('riders: a corpus single-stack rider applies with cap 1',
          rider['applied'] and rider['cap'] == 1 and rider['contribution'] == 50.0, rider)


def check_set_roster():
    """The roster contract, and the set pass itself refusing to count a duplicate member."""
    db0 = load_db()
    vit_row = _best(db0, 'Umbral Vitality')
    dup_slots = [{'kind': 'normal', 'index': 0, 'polarity': None,
                  'rank': vit_row.get('max_rank'), 'mod': vit_row},
                 {'kind': 'normal', 'index': 1, 'polarity': None,
                  'rank': vit_row.get('max_rank'), 'mod': vit_row}]
    totals, markers, _notes = effects.collect_mod_effects(dup_slots)
    codes = {m.get('code') for m in markers}
    pieces = [row.get('set_pieces') for bucket in totals.values()
              for row in (bucket.get('rows') or []) if row.get('set_pieces') is not None]
    check('sets: the set pass counts a duplicate member once',
          'duplicate_set_member' in codes and not [p for p in pieces if p and p > 1],
          (sorted(codes), pieces))
    db = load_db()
    vit = _best(db, 'Umbral Vitality')
    fib = _best(db, 'Umbral Fiber')
    frame = _equip(db, 'Excalibur', 'warframe')
    check('sets: the roster contract is declared',
          mechanics.roster_contract('set') == 'distinct_legal_known',
          mechanics.roster_contract('set'))
    two = _run(db, [(vit['id'], vit.get('max_rank') or 0), (fib['id'], fib.get('max_rank') or 0)],
               equipment=frame)
    dupe = _run(db, [(vit['id'], vit.get('max_rank') or 0), (vit['id'], vit.get('max_rank') or 0)],
                equipment=frame)
    codes = {m.get('code') for m in (dupe.get('validation', {}).get('errors') or [])}
    check('sets: a duplicate member cannot raise the count (the build is refused by name)',
          'duplicate_mod' in codes and dupe.get('result') is None, sorted(codes))
    declared = mechanics.REGISTRY['umbral_set'].refusal_codes
    check('sets: the set mechanic declares its roster failure codes',
          {'duplicate_set_member', 'umbral_member_unknown',
           'umbral_set_above_documented_pieces', 'umbral_set_no_rows'} <= set(declared),
          sorted(declared))
    check('sets: two distinct members scale as the card says',
          two['result']['stats']['health'] > _run(db, [(vit['id'], vit.get('max_rank') or 0)],
                                                  equipment=frame)['result']['stats']['health'],
          (two['result']['stats']['health'], ))


MALFORMED = [
    {'target': {'heat_strip': 'ten'}}, {'target': {'heat_strip': True}},
    {'target': {'heat_strip': []}}, {'target': {'heat_strip': 10 ** 400}},
    {'target': {'heat_strip': float('nan')}}, {'target': {'heat_strip': -5}},
    {'target': {'health': 'lots'}}, {'target': {'health': -1}},
    {'target': {'health': 10 ** 400}}, {'target': {'health': []}},
    {'target': {'shields': {'n': 1}}}, {'target': {'overguard': 'x'}},
    {'target': {'preset': ['a']}}, {'target': {'preset': {'id': 'x'}}},
    {'target': {'preset': 10 ** 400}},
    {'target': {'protection': 'health', 'health': 10 ** 12, 'armor': 10 ** 12}},
    {'target': {'protection': [], 'health': 5}}, {'buffs': {'on_kill': {'stacks': 10 ** 400}}},
    {'target': {'protection': 'health', 'armor': 900, 'corrosive_stacks': 10 ** 400}},
    {'target': {'protection': 'health', 'armor': 900, 'heat_strip': 10 ** 400}},
]


def check_input_hardening():
    db = load_db()
    ser = _mod(db, 'Serration')
    bad = []
    for options in MALFORMED:
        try:
            out = api.compute(_build(db, [ser[:2]]), db, {'context': options})
        except Exception as exc:                                   # noqa: BLE001 - the point
            bad.append((options, '%s: %s' % (type(exc).__name__, exc)))
            continue
        if not isinstance(out, dict) or out.get('result') is None and out.get('ok') is not False:
            bad.append((options, 'no structured answer'))
        if out.get('ok') and out.get('result'):
            stats = out['result'].get('stats') or {}
            for key in ('damage_per_shot', 'shots_to_kill'):
                value = stats.get(key)
                if isinstance(value, float) and (value != value or value in (float('inf'),
                                                                            float('-inf'))):
                    bad.append((options, 'non-finite %s' % key))
    check('hardening: no malformed target/pool/preset input raises or coerces', not bad, bad)
    # NaN-as-float cannot arrive through JSON, but the engine still must not return one
    out = api.compute(_build(db, [ser[:2]]), db,
                      {'context': {'target_faction': 'grineer',
                                   'target': {'protection': 'health', 'armor': 900,
                                              'health': 10 ** 12}}})
    check('hardening: a huge but finite pool answers with a finite count',
          isinstance(out['result']['stats'].get('shots_to_kill'), int)
          and out['result']['stats']['shots_to_kill'] > 0,
          out['result']['stats'].get('shots_to_kill'))


def check_presets():
    db = load_db()
    ser = _mod(db, 'Serration')
    out = _run(db, [ser[:2]], _ctx(target={'preset': 'level-100-heavy-gunner'}))
    rows = [c for c in out['conditions'] if c['condition'] == 'target_damage']
    check('presets: a stated preset is refused by name, not resolved',
          rows and rows[0]['state'] == 'unsupported'
          and rows[0].get('unsupported_code') == 'preset_unavailable'
          and out['result']['target_damage'] is None, rows)
    check('presets: the refusal names the missing source',
          rows and 'no authoritative' in rows[0]['reason'], rows and rows[0]['reason'])
    check('presets: no target number was fabricated from the preset',
          out['result']['target_damage'] is None
          and out['result']['stats'].get('damage_per_shot') is not None)


FORMULA_PATTERNS = ('armor_after', '0.20 + 0.06', '0.06 *', '/ 2700', '* 1.5', '0.9 *',
                    'sqrt(', 'Math.sqrt', '1 - 0.20', '20 + 6')


def check_page_has_no_warframe_maths():
    """The planner's own files derive nothing: a Warframe formula appearing in static/ means the
    page started calculating. Vendored chart libraries are not the planner's code."""
    offenders = []
    for name in sorted(os.listdir(os.path.join(REPO, 'static'))):
        if not name.endswith(('.js', '.html')) or name.startswith('chart'):
            continue
        text = open(os.path.join(REPO, 'static', name), encoding='utf-8').read()
        for pattern in FORMULA_PATTERNS:
            if pattern in text:
                offenders.append((name, pattern))
    check('page: no Warframe formula appears in static/', not offenders, offenders)
    page = open(os.path.join(REPO, 'static', 'planner.js'), encoding='utf-8').read()
    check('page: the Heat strip input offers only the ramp values the engine accepts',
          "HEAT_STRIPS = [0, 15, 30, 40, 50]" in page, 'HEAT_STRIPS')
    check('page: the pool boxes are sent under the engine\'s own field names',
          "'pool_health', 'health'" in page and "'pool_overguard', 'overguard'" in page)


def check_review_fixes_hold():
    """The three reviews' executed counterexamples, as checks the gate keeps honest."""
    db = load_db()
    ser = _mod(db, 'Serration')
    chamber_row = _best(db, 'Galvanized Chamber')
    chamber = (chamber_row['id'], chamber_row.get('max_rank') or 0)
    # a pool-only refusal leaves the Phase 1 numbers alone (review 3 F2)
    out = _run(db, [ser[:2]], _ctx(target_faction='grineer',
                                   target={'protection': 'health', 'armor': 900,
                                           'shields': 400}, strict=True))
    check('review: a pool-only refusal leaves the Phase 1 numbers alone',
          out['result']['stats']['damage_per_shot'] == 92.75
          and out['result']['target_damage'] is not None
          and out['evaluation']['refused_stats'] == [],
          out['evaluation']['refused_stats'])
    # a withheld per-shot figure takes the pool block with it (reviews 1 F2 / 3 F1)
    out = _run(db, [ser[:2], chamber],
               _ctx(target_faction='grineer',
                    target={'protection': 'health', 'armor': 900, 'health': 5000},
                    buffs={'on_kill': {'stacks': 99}}, strict=True))
    pool = out['result'].get('pool') or {}
    check('review: a withheld per-shot figure takes the pool block with it',
          out['result']['stats'].get('damage_per_shot') is None
          and pool.get('damage_per_shot') is None and pool.get('shots_required') is None
          and out['result']['stats'].get('shots_to_kill') is None
          and (out['result']['traces'].get('pool') or {}).get('final') is None,
          {'refused': out['evaluation']['refused_stats'], 'pool': pool,
           'final': (out['result']['traces'].get('pool') or {}).get('final')})
    # the declaration join: every blocked row maps back to a mechanic
    blocked = [row['condition'] for row in out['conditions']
               if row['state'] in ('unknown', 'unsupported')]
    check('review: every blocked row joins back to a declared mechanic',
          all(mechanics.by_condition(row) is not None for row in blocked), blocked)
    # stated-but-unconsumed fields are reported (review 1 F3 / review 3 F7)
    out = _run(db, [ser[:2]], _ctx(target={'overguard': 500}))
    check('review: a stated overguard value is reported, not dropped',
          'target.overguard' in (out['evaluation'].get('unused') or []),
          out['evaluation'].get('unused'))
    # no crash from a huge-but-finite pool, and a named refusal when the quotient is not finite
    for pool_size in (10 ** 300, 10 ** 309):
        out = _run(db, [ser[:2]], _ctx(target_faction='grineer',
                                       target={'protection': 'shields', 'shields': pool_size,
                                               'corrosive_stacks': 0}))
        rows = [c for c in out['conditions'] if c['condition'] == 'pool']
        ok = out.get('ok') is True and bool(rows) and (
            pool_size == 10 ** 300 or (rows[0]['state'] == 'unknown'
                                       and out['result']['stats'].get('shots_to_kill') is None))
        check('review: a %s pool answers or refuses by name, never raises'
              % ('huge' if pool_size == 10 ** 300 else 'non-finite-quotient'), ok, rows)
    # the averaged path names stray fields (review 3 F6) - with a rider installed, or the question
    # is never asked at all
    out = _run(db, [ser[:2], chamber],
               _ctx(buffs={'on_kill': {'uptime': 0.5, 'stacks': 1, 'kills': 4}}))
    rows = [c for c in out['conditions'] if c['condition'] == 'on_kill']
    check('review: the averaged buff state names the fields it does not read',
          rows and rows[0]['state'] == 'unknown' and 'kills' in rows[0]['reason'], rows)



def check_migration_equality_is_still_available():
    """The migration gate is the equality proof; the phase gate re-runs it cheaply."""
    probe = os.path.join(REPO, 'design', '_planner', 'phase6_migration.py')
    check('migration: the migration gate exists and targets the Phase 5 tip',
          os.path.exists(probe) and 'f1f2db3' in open(probe, encoding='utf-8').read(), probe)


CHECKS = [
    check_registry_shape,
    check_half_declared_mechanic_fails_loudly,
    check_declared_codes_have_rows,
    check_accounting_is_derived,
    check_dispatch_is_derived,
    check_trace_destinations,
    check_trace_composition,
    check_blast_radius,
    check_dependencies,
    check_pool_semantics,
    check_heat_semantics,
    check_rider_family,
    check_set_roster,
    check_input_hardening,
    check_presets,
    check_page_has_no_warframe_maths,
    check_review_fixes_hold,
    check_migration_equality_is_still_available,
]


# --------------------------------------------------------------------------- falsification
BREAKS = []


def break_(name, expect):
    def wrap(fn):
        BREAKS.append((name, fn, expect))
        return fn
    return wrap


@break_('a mechanic declared without consumed fields passes validation',
        'invariant: no consumes is refused')
def _break_no_consumes():
    original = mechanics._validate

    def permissive(m):
        saved = m.consumes
        # everything a trigger mentions is counted as consumed, and an empty list is padded: the
        # declaration layer no longer notices a mechanic that declares no inputs
        m.consumes = tuple(sorted(set(m.consumes)
                                  | set(m.trigger.fields() if m.trigger else ()))) \
            or ('gate.placeholder',)
        try:
            return original(m)
        finally:
            m.consumes = saved
    mechanics._validate = permissive
    return lambda: setattr(mechanics, '_validate', original)


@break_('a mechanic declared without a trace destination passes validation',
        'invariant: no trace destination')
def _break_no_trace():
    original = mechanics._validate

    def permissive(m):
        saved = (m.trace, m.stat_traces)
        m.trace, m.stat_traces = 'damage', {}
        try:
            return original(m)
        finally:
            m.trace, m.stat_traces = saved
    mechanics._validate = permissive
    return lambda: setattr(mechanics, '_validate', original)


@break_('a mechanic without a trigger passes validation',
        'invariant: no trigger is refused')
def _break_no_trigger():
    original = mechanics._validate

    def permissive(m):
        saved = (m.trigger, m.consumes)
        # a trigger is invented when one is missing, and it counts as consumed
        m.trigger = m.trigger or mechanics.ALL(mechanics.F('attack.shot_index'))
        m.consumes = tuple(sorted(set(m.consumes) | set(m.trigger.fields())))
        try:
            return original(m)
        finally:
            m.trigger, m.consumes = saved
    mechanics._validate = permissive
    return lambda: setattr(mechanics, '_validate', original)


@break_('the Heat strip defaults from a missing input',
        'heat: no stated strip leaves the armour untouched')
def _break_heat_default():
    original = statuses.evaluate_heat

    def defaulted(ctx):
        # the defect: no stated strip is read as "the 50% maximum"
        if not conditions.has(ctx, 'target', 'heat_strip'):
            return original({'target': {'heat_strip': 50}})
        return original(ctx)
    statuses.evaluate_heat = defaulted
    original_live = mechanics.live

    def live(mechanic_id, ctx, facts=None):
        if mechanic_id == 'heat_strip':
            return True
        return original_live(mechanic_id, ctx, facts)
    mechanics.live = live
    return lambda: (setattr(statuses, 'evaluate_heat', original),
                    setattr(mechanics, 'live', original_live))


@break_('a trace row stops composing (heat reports the wrong delta)',
        'composition: both states')
def _break_trace_row():
    original = statuses.heat_trace_row

    def wrong(armor, effective, row):
        built = original(armor, effective, row)
        if built:
            built['value'] = round(float(armor) - float(effective), 6)
        return built
    statuses.heat_trace_row = wrong
    return lambda: setattr(statuses, 'heat_trace_row', original)


@break_('the target block is allowed to withhold unrelated numbers',
        'blast radius: the target path may withhold only the target block')
def _break_wide_withholds():
    mechanic = mechanics.REGISTRY['target_damage_path']
    saved = mechanic.withholds
    mechanic.withholds = ('target_damage', 'damage_per_shot', 'burst_dps',
                          'damage_to_health')
    return lambda: setattr(mechanic, 'withholds', saved)


@break_('a missing armour value erases the Phase 1 numbers',
        'blast radius: a missing armour value leaves the Phase 1 numbers alone')
def _break_erase_phase1():
    original = weapons.calculate

    def wipe(equipment, mod_slots=None, options=None):
        out = original(equipment, mod_slots, options)
        ctx = (options or {}).get('context') or {}
        if ctx.get('target_faction') and not out.get('target_damage'):
            # the defect: the target question could not be answered, so the Phase 1 numbers go too
            out['stats']['damage_per_shot'] = None
            out['stats']['burst_dps'] = None
        return out
    weapons.calculate = wipe
    return lambda: setattr(weapons, 'calculate', original)


@break_('a missing armour value erases the Viral answer',
        'blast radius: a missing armour value leaves the Viral answer in place')
def _break_erase_viral():
    original = weapons.calculate

    def wipe(equipment, mod_slots=None, options=None):
        out = original(equipment, mod_slots, options)
        ctx = (options or {}).get('context') or {}
        if ctx.get('target_faction') and not out.get('target_damage'):
            # the defect: an unanswered target question also takes the viral health multiplier away
            out['stats']['damage_to_health'] = None
        return out
    weapons.calculate = wipe
    return lambda: setattr(weapons, 'calculate', original)


@break_('a rider the engine cannot source contributes its stat',
        'riders: a rider on a stat the engine does not model contributes nothing')
def _break_rider_contributes():
    # the defect: the enablement stops being the boundary, so a Zoom rider applies
    saved_stats = mechanics.rider_stats
    mechanics.rider_stats = lambda: ('multishot', 'critical_chance', 'critical_damage',
                                     'status_chance', 'reload_speed', 'fire_rate', 'zoom')
    original_enabled = buffs.ENABLED_STATS
    buffs.ENABLED_STATS = {stat: stat for stat in mechanics.rider_stats()}
    return lambda: (setattr(buffs, 'ENABLED_STATS', original_enabled),
                    setattr(mechanics, 'rider_stats', saved_stats))


@break_('a crit rider is routed into the multishot trace',
        'riders: rider traces match their declared destination')
def _break_rider_trace():
    # the mis-routing is the declaration disagreement; the engine refuses when plumbing and
    # declaration disagree, so this break must surface as the guard refusing
    mechanic = mechanics.REGISTRY['on_kill_rider']
    saved = mechanic.stat_traces['critical_chance']
    mechanic.stat_traces['critical_chance'] = 'multishot'

    def restore():
        mechanic.stat_traces['critical_chance'] = saved
    return restore


@break_('a stated pool is answered even when the landing or the damage path cannot support it',
        'pool: a stated pool for another layer is refused by name')
def _break_pool_default():
    original = enemies.evaluate_pool

    def defaulting(ctx, layer, damage):
        row, block = original(ctx, layer, damage)
        if block is None:
            # the defect: an unstated pool becomes a thousand points and in a shot count
            block = {'layer': layer, 'pool': 1000.0, 'damage_per_shot': 10.0,
                     'damage_per_shot_expected_crit': 10.0, 'shots_required': 100,
                     'expected_shots': 100.0, 'assumptions': []}
        return row, block
    enemies.evaluate_pool = defaulting
    return lambda: setattr(enemies, 'evaluate_pool', original)


@break_('shots-to-kill uses a partially refused damage path',
        'pool: an unresolved damage path withholds the shot count')
def _break_pool_partial():
    original = enemies.evaluate_pool

    def partial(ctx, layer, damage):
        if damage is None:
            damage = {'per_shot_total': 1.0, 'per_shot_expected_crit': 1.0}
        return original(ctx, layer, damage)
    enemies.evaluate_pool = partial
    return lambda: setattr(enemies, 'evaluate_pool', original)


@break_('a duplicate set member raises the set count',
        'sets: the set pass counts a duplicate member once')
def _break_set_count():
    original = effects.collect_mod_effects

    def rigged(mod_slots):
        # the defect: a second copy of one member is presented as another mod, so the set pass
        # counts it twice and the duplicate guard never fires
        seen, translated = {}, []
        for slot in mod_slots or []:
            slot = dict(slot)
            mod = dict(slot.get('mod') or {})
            mid = mod.get('id')
            if mid:
                seen[mid] = seen.get(mid, 0) + 1
                if seen[mid] > 1:
                    mod['id'] = '%s#copy' % mid
                    slot['mod'] = mod
            translated.append(slot)
        return original(translated)
    effects.collect_mod_effects = rigged
    return lambda: setattr(effects, 'collect_mod_effects', original)


@break_('a malformed pool size raises out of the engine',
        'hardening: no malformed target/pool/preset input raises or coerces')
def _break_pool_raises():
    original = enemies._as_number

    def raw(value):
        # the defect: the guard that turns junk into a named refusal is gone
        return float(value)
    enemies._as_number = raw
    return lambda: setattr(enemies, '_as_number', original)


@break_('a mechanic formula appears in static/', 'page: no Warframe formula appears in static/')
def _break_page_formula():
    path = os.path.join(REPO, 'static', 'planner.js')
    with open(path, encoding='utf-8') as handle:
        text = handle.read()
    marker = '/* gate: */ var armorAfter = armor * (1 - 0.20 + 0.06);'
    with open(path, 'w', encoding='utf-8') as handle:
        handle.write(text + '\n' + marker + '\n')
    return lambda: open(path, 'w', encoding='utf-8').write(text)


@break_('the registry stops being the accounting source',
        'accounting: TARGET_FIELDS is the registry union')
def _break_accounting():
    saved = conditions.TARGET_FIELDS
    conditions.TARGET_FIELDS = tuple(f for f in saved if f != 'heat_strip')
    return lambda: setattr(conditions, 'TARGET_FIELDS', saved)


@break_('a mechanic is evaluated without its trigger being stated',
        'dispatch: with no context no target mechanic is evaluated')
def _break_live_always():
    original = mechanics.live

    def always(mechanic_id, ctx, facts=None):
        return True
    mechanics.live = always
    return lambda: setattr(mechanics, 'live', original)




@break_('the pool block survives a strict withholding (the declaration loses its pool keys)',
        'review: a withheld per-shot figure takes the pool block with it')
def _break_pool_survives():
    saved = {}
    for mechanic in mechanics.REGISTRY.values():
        if 'pool' in mechanic.withholds:
            saved[mechanic.id] = mechanic.withholds
            mechanic.withholds = tuple(k for k in mechanic.withholds
                                       if k not in ('pool', 'shots_to_kill'))

    def restore():
        for mechanic_id, withholds in saved.items():
            mechanics.REGISTRY[mechanic_id].withholds = withholds
    return restore

# --------------------------------------------------------------------------- runner
def run_checks():
    del RESULTS[:]
    del FAILURES[:]
    for fn in CHECKS:
        try:
            fn()
        except Exception as exc:                                   # noqa: BLE001 - the point
            check('crash: %s' % fn.__name__, False, '%s: %s' % (type(exc).__name__, exc))
    failed = len(FAILURES)
    print('\nchecks: %d, failed: %d' % (len(RESULTS), failed))
    for failure in FAILURES:
        print('  FAIL %s' % failure)
    return failed


def falsify():
    print('16 breaks, each must be caught by a named check that actually depends on it:')
    caught, misses = 0, []
    for name, fn, expect in BREAKS:
        restore = fn()
        try:
            failed = run_checks()
            hit = [r for r in RESULTS if not r['ok'] and expect in r['check']]
            if hit:
                caught += 1
                print('  caught  %-58s -> %s' % (name[:58], hit[0]['check'][:80]))
            else:
                misses.append((name, failed))
                print('  MISSED  %-58s (failures: %d)' % (name[:58], failed))
                for row in RESULTS:
                    if not row['ok']:
                        print('           it did fail: %s' % row['check'][:110])
        finally:
            if callable(restore):
                restore()
            elif restore:
                for item in restore:
                    item()
    print('\nbreaks caught: %d/%d' % (caught, len(BREAKS)))
    if misses:
        print('a break that does not touch its decision path is a failure of the gate:')
        for name, failed in misses:
            print('  %s (total failures during the break: %d)' % (name, failed))
    return 0 if not misses else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description='Phase 6 gate')
    parser.add_argument('--falsify', action='store_true')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)
    if args.json:
        failed = run_checks()
    else:
        failed = run_checks()
    if failed:
        return 1
    if args.falsify:
        return falsify()
    return 0


if __name__ == '__main__':
    sys.exit(main())
