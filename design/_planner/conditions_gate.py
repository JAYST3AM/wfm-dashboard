#!/usr/bin/env python3
"""The refusal-preservation gate (Phase 4, milestone 4.6).

What this gate protects, in one sentence: **nothing conditional or unmodelled may become a number,
and nothing unknown may become false.** Every check below fails loudly if that stops being true.

It runs against whatever database the engine is pointed at (WFM_BUILD_DB, else
data/build_data.json - the real 1809-mod corpus when it has been ingested). `--falsify` then runs
the same checks against deliberately broken engines and asserts each break is caught, which is the
only way to know the gate is not decorative.

    python design/_planner/conditions_gate.py             # check the engine as it is
    python design/_planner/conditions_gate.py --falsify    # prove the checks catch breakage
    python design/_planner/conditions_gate.py --json       # machine-readable summary
"""
import argparse
import io
import json
import os
import sys
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from builds import api, conditions, data, effects, statuses, unsupported  # noqa: E402
from builds import weapons  # noqa: E402
from builds import validation  # noqa: E402

REPORT = REPO / 'design' / '_planner' / 'conditions-gate-report.md'
PAGE_FILES = ('planner.js', 'planner-stats.js', 'planner-library.js', 'planner.html')
# The Phase 4 formula constants belong in builds/ and the docs. A page that carries one of these
# is doing maths the engine owns.
FORBIDDEN_ON_PAGE = ('4.25', '+325', 'viral_stacks - 1', 'PER_STACK')

BAD_CONTEXTS = ['grineer', 42, [1, 2], {'target': 'grineer'}, {'target': {'viral_stacks': 'six'}},
                {'attack': 'first'}, {'target_faction': 7}, {'target': {'protection': []}},
                {'attack': {'shot_index': 'one'}}, {'target': {'viral_stacks': 99}},
                {'target': {'viral_stacks': -3}}, {'target': {'immune_to': 'viral'}}, {'nope': 1}]
BAD_OPTIONS = ['strict', 3, ['context'], (), {'context': 'nope'}, {'strict': 'yes'},
              {'hypothetical': True}, {'hypothetical': 'yes'}, {'strict': 1, 'hypothetical': []}]
# Shapes the independent verifier found crashing the engine while the first corpus missed them:
# an unhashable equipment or mod key, and a mod rank of 10**1000 (which reached the capacity
# arithmetic). They live here now so the corpus covers the classes, not the three examples.
BAD_BUILDS_EXTRA = [
    {'equipment_id': {'a': 1}},
    {'equipment_id': ['x']},
    {'equipment_id': '/Fixture/Weapons/BratonPrime',
     'slots': [{'index': 0, 'mod': {'name': ['Serration']}}]},
    {'equipment_id': '/Fixture/Weapons/BratonPrime',
     'slots': [{'index': 0, 'mod': {'name': 'Serration', 'rank': 10 ** 1000}}]},
    {'equipment_id': '/Fixture/Weapons/BratonPrime', 'slots': 'nope'},
]


class Result:
    """Accumulated check outcomes: one dict per check, never an exception out of a check."""

    def __init__(self):
        self.rows = []

    def check(self, cid, label, ok, detail=''):
        self.rows.append({'id': cid, 'label': label, 'ok': bool(ok), 'detail': str(detail)[:400]})
        return bool(ok)

    @property
    def failures(self):
        return [r for r in self.rows if not r['ok']]

    @property
    def ok(self):
        return not self.failures


def _build(equipment_id, mods=(), kind='normal'):
    """A one-mod build. Aura/stance/exilus slots carry no index (the layout has one of each),
    which is what validation expects; normal slots are indexed in order."""
    build = {'config': 'A', 'equipment_id': equipment_id, 'equipment_rank': 30, 'orokin': True,
             'mastery_rank': 30, 'slots': []}
    for index, (mod_id, rank) in enumerate(mods):
        build['slots'].append({'kind': kind, 'index': index if kind == 'normal' else None,
                               'polarity': None, 'mod': {'id': mod_id, 'rank': rank}})
    return build


def _conditional_mods(db):
    rows = []
    for row in db['mods'].values():
        eff = row.get('effects') or {}
        if eff.get('conditional'):
            rows.append(row)
    return rows


def _weapon_id(db, prefer=('Soma Prime', 'Braton Prime')):
    for name in prefer:
        for eid, row in db['equipment'].items():
            if row.get('name') == name and row.get('kind') == 'primary':
                return eid
    for eid, row in db['equipment'].items():
        if row.get('kind') == 'primary':
            return eid
    return None


# A mod is only meaningful on equipment of its own kind (compat 'Rifle' fits a Rifle), so every
# check below asks for the weapon that can hold the mod rather than forcing one weapon on the
# whole corpus - a build that cannot hold the mod answers 'unknown_equipment', which is a
# validation refusal and not evidence about the conditional rules.
# Which slot kind a mod needs, and how a mod's `targets` map onto the equipment kinds the
# database actually holds. A mod is then evaluated on equipment that can legally hold it.
SLOT_KIND = {'aura': 'aura', 'stance': 'stance', 'exilus': 'exilus'}
# subtype preferences: a 'Rifle' mod should not be tested on the first Bow in the database
SUBTYPE_FOR = {'rifle': 'rifle', 'shotgun': 'shotgun', 'pistol': 'pistol', 'bow': 'bow',
               'melee': 'melee', 'sniper': 'sniper', 'assault rifle': 'rifle'}
# ... and when a mod carries no `targets` at all, its own type names the kind of equipment it goes
# on. Kinds this database does not hold (Archwing, K-Drive, Focus, Plexus, Parazon) stay unmatched
# on purpose: the gate reports them as not-in-this-database rather than pretending to check them.
KIND_FOR_TYPE = {'Warframe Mod': 'warframe', 'Aura': 'warframe', 'Primary Mod': 'primary',
                 'Shotgun Mod': 'primary', 'Secondary Mod': 'secondary', 'Melee Mod': 'melee',
                 'Companion Mod': 'sentinel', 'Stance Mod': 'melee'}


def _equipment_for(db, mod_row):
    """Equipment that can hold this mod, or None when this database has none of its kind."""
    kinds = {}
    for eid, row in sorted(db['equipment'].items()):
        kinds.setdefault(row.get('kind'), []).append((eid, row))
    wanted = [t for t in (mod_row.get('targets') or ()) if t in kinds]
    if not wanted:
        fallback = KIND_FOR_TYPE.get(str(mod_row.get('type') or ''))
        if fallback in kinds:
            wanted = [fallback]
    for target in wanted:
        compat = str(mod_row.get('compat') or '').strip().lower()
        want = SUBTYPE_FOR.get(compat)
        if want:
            for eid, row in kinds[target]:
                if str(row.get('subtype') or '').lower() == want:
                    return eid
        return kinds[target][0][0]
    return None


def _value(entry):
    """`collect_mod_effects` sums into {stat: {'value': n, ...}}; take the number."""
    if isinstance(entry, dict):
        return entry.get('value')
    return entry


def _slot_kind(mod_row):
    return SLOT_KIND.get(str(mod_row.get('slot') or '').strip().lower(), 'normal')


def _compute(db, mod_row, options=None, rank=None, equipment_id=None):
    """One build: this mod at its own max rank (or `rank`), in the slot kind it belongs in."""
    eid = equipment_id or _equipment_for(db, mod_row)
    if not eid:
        return None
    body = _build(eid, [(mod_row['id'], mod_row.get('max_rank') or 0 if rank is None else rank)],
                  kind=_slot_kind(mod_row))
    build = dict(body)
    if _slot_kind(mod_row) == 'exilus':
        build['exilus_unlocked'] = True
    out = api.compute(build, db, options)
    return out if out.get('result') else None


def _unplaceable(db):
    """Conditional mods whose kind no equipment row in this database can hold, with the reason."""
    kinds = {row.get('kind') for row in db['equipment'].values()}
    out = {}
    for row in _conditional_mods(db):
        targets = tuple(row.get('targets') or ())
        fallback = KIND_FOR_TYPE.get(str(row.get('type') or ''))
        if not [t for t in targets if t in kinds] and fallback not in kinds:
            reason = 'targets %s' % (list(targets) or ('type: %s' % row.get('type')))
            out.setdefault(reason, []).append(row['name'])
    return out


def _faction_mod(db):
    for row in db['mods'].values():
        rt = (row.get('effects') or {}).get('rank_table') or {}
        if any(k.startswith('faction_') for k in rt):
            return row
    return None


def _viral_mods(db, weapon):
    """Two mods of one element each whose combination this weapon makes viral."""
    def pick(name):
        for row in db['mods'].values():
            if (row.get('name') or '') == name:
                return row
        return None
    return pick('Cryo Rounds'), pick('Infected Clip')


# --------------------------------------------------------------------------- the checks

def check_state_vocabulary(res, db):
    """1. The four states are the whole space, and every state in a payload is one of them.

    The four words are a contract with the phase brief, so they are pinned literally here: a
    widened state space (a fifth 'state', or a boolean smuggled in as one) fails this check even
    though every consumer would happily read `conditions.STATES`. The four refusal reasons are
    pinned the same way; `context_unused` is a fifth reason of a different kind (a stated input
    with no model) and is allowed to sit beside them, not among them.
    """
    res.check('states/exactly-four',
              'the state space is exactly satisfied / not_satisfied / unknown / unsupported',
              tuple(conditions.STATES) == ('satisfied', 'not_satisfied', 'unknown', 'unsupported')
              and set(conditions.MEANING) == set(conditions.STATES)
              and set(conditions.STATE_CODES) == set(conditions.STATES)
              and set(conditions.CONDITION_REASON_CODES).issubset(set(conditions.REASON_CODES))
              # ... and a validation code is not a condition state: two vocabularies, no overlap.
              and not (set(validation.CODES) & set(conditions.STATES)),
              list(conditions.STATES))
    seen = set()
    bad = []
    skipped = 0
    for row in _conditional_mods(db):
        out = _compute(db, row)
        if out is None:
            skipped += 1
            continue
        for marker in out['result']['unsupported']:
            state = marker.get('state')
            if state is None:
                continue
            seen.add(state)
            if state not in conditions.STATES:
                bad.append((row['name'], state))
    res.check('states/vocabulary', 'every condition state in a payload is one of the four',
              not bad, bad[:5])


REACHABILITY = (  # producer, inputs, the one state the plan says that producer owns
    ('classify_conditional_text', ('On Kill: +30% Damage for 20s',), conditions.UNSUPPORTED),
    ('classify_conditional_text', ('+60% Damage',), conditions.UNSUPPORTED),
    ('target_faction', ({'target_faction': 'grineer'}, 'grineer'), conditions.SATISFIED),
    ('target_faction', ({'target_faction': 'corpus'}, 'grineer'), conditions.NOT_SATISFIED),
    ('target_faction', ({}, 'grineer'), conditions.UNKNOWN),
    ('first_shot', ({'attack': {'shot_index': 1}},), conditions.SATISFIED),
    ('first_shot', ({'attack': {'shot_index': 4}},), conditions.NOT_SATISFIED),
    ('viral', ({'target': {'viral_stacks': 6, 'protection': 'shields'}},), conditions.NOT_SATISFIED),
    ('viral', ({'target': {'viral_stacks': 12, 'protection': 'health'}},), conditions.UNSUPPORTED),
    ('viral', ({'target': {'viral_stacks': 4}},), conditions.UNKNOWN),
)


def check_states_reachable(res, db):
    """Every state is reachable, and reached by the producer the plan names for it.

    The check this replaces was `bool(seen)` over whatever states a build happened to emit - a
    tautology, as the adversarial review put it: one `unsupported` row satisfied a check called
    "the corpus actually exercises the state space". This walks each producer with an input that
    must land on a specific state and requires all four states to appear.
    """
    reached, wrong = set(), []
    for producer, args, expected in REACHABILITY:
        try:
            if producer == 'classify_conditional_text':
                got = conditions.classify_conditional_text(*args)[1]
            elif producer == 'target_faction':
                got = conditions.evaluate('target_faction', conditions.normalise_context(args[0]),
                                          faction=args[1]).get('state')
            elif producer == 'first_shot':
                got = conditions.evaluate('first_shot',
                                          conditions.normalise_context(args[0])).get('state')
            else:
                got = statuses.evaluate(conditions.normalise_context(args[0])).get('state')
        except Exception as exc:                                          # noqa: BLE001
            got = 'raised: %s' % exc
        reached.add(got)
        if got != expected:
            wrong.append({'producer': producer, 'expected': expected, 'got': got})
    res.check('states/reachable',
              'each state is reached by the producer that owns it, and all four are reached',
              not wrong and reached == set(conditions.STATES),
              {'states': sorted(reached), 'wrong': wrong[:4]})


def check_corpus_still_refuses(res, db, min_corpus=100):
    """2. Every conditional mod in the database still refuses, with a structured reason."""
    rows = _conditional_mods(db)
    unstructured, applied, unbuildable = [], [], []
    unplaceable = _unplaceable(db)
    for row in rows:
        out = _compute(db, row)
        if out is None:
            if not any(row['name'] in names for names in unplaceable.values()):
                unbuildable.append(row['name'])
            continue
        markers = [m for m in out['result']['unsupported'] if m.get('code') == 'conditional_effect']
        if not markers:
            unstructured.append(row['name'])
            continue
        for marker in markers:
            block = marker.get('condition') or {}
            if not block or block.get('state') not in conditions.STATES \
                    or marker.get('reason_code') not in conditions.REASON_CODES:
                unstructured.append('%s: %s' % (row['name'], marker.get('text', '')))
            if block.get('applied'):
                applied.append(row['name'])
    res.check('refusal/corpus-count', 'the conditional corpus is non-empty',
              len(rows) >= min_corpus, '%d mods carry conditional lines' % len(rows))
    res.check('refusal/structured', 'every conditional mod refuses with a state and a reason code',
              not unstructured, unstructured[:5])
    res.check('refusal/never-applied', 'no conditional clause is ever applied',
              not applied, applied[:5])
    res.check('refusal/checked-count',
              'every conditional mod that this database can equip was actually checked',
              not unbuildable, {'of': len(rows), 'unbuildable': unbuildable[:5],
                                'not-in-this-database': {k: len(v)
                                                         for k, v in unplaceable.items()}})
    return len(rows)


def check_nothing_conditional_reaches_the_totals(res, db):
    """3. The rider never lands: what a conditional line carries stays out of the totals.

    Measured against the mod's own unconditional table, stat by stat. If a rider had landed, the
    collected total for that stat would be larger than the table value at that rank. The first
    version of this check derived the stats to look at by re-parsing the conditional text, which
    resolves to a modelled stat for only 11 of 430 lines - so it ran with nothing to compare and
    could not fail. This one compares every stat the mod actually has.
    """
    offenders, comparisons, checked = [], 0, 0
    for row in _conditional_mods(db):
        eff = row.get('effects') or {}
        table = eff.get('rank_table') or {}
        rank = row.get('max_rank') or 0
        kind = 'aura' if row.get('slot') == 'aura' else 'normal'
        build = {'equipment_id': _equipment_for(db, row),
                 'slots': [{'kind': kind, 'index': None if kind == 'aura' else 0,
                            'mod': {'id': row['id'], 'rank': rank}}]}
        slots, _ = api.engine_slots(build, db)
        totals, _, _ = effects.collect_mod_effects(slots)
        if not totals:
            continue
        checked += 1
        for stat, values in table.items():
            expected = values[rank] if isinstance(values, list) and len(values) > rank else None
            if expected is None:
                continue
            comparisons += 1
            actual = _value(totals.get(stat))
            if abs(float(actual) - float(expected)) > 1e-6:
                offenders.append({'mod': row.get('name'), 'stat': stat, 'in_total': actual,
                                  'unconditional_only': expected})
        # A stat that only a conditional line carries must not appear in the totals at all.
        for text in eff.get('conditional') or []:
            parsed = effects.parse_stat_line(text)
            stat = parsed.get('stat')
            if stat and stat not in table and stat in totals:
                offenders.append({'mod': row.get('name'), 'stat': stat,
                                  'in_total': _value(totals[stat]), 'unconditional_only': None})
    res.check('rider/never-in-totals',
              'a conditional line never adds to the totals, measured stat by stat',
              not offenders and comparisons > 0,
              {'mods': checked, 'comparisons': comparisons, 'offenders': offenders[:4]})


def check_unknown_never_becomes_zero(res, db):
    """4. An unresolved condition withholds; it does not quietly contribute zero."""
    weapon = _weapon_id(db)
    mod = _faction_mod(db)
    if mod is None:
        res.check('unknown/faction-mod-present', 'a faction mod is in the database', False, 'none')
        return
    plain = api.compute(_build(weapon), db)
    with_mod = api.compute(_build(weapon, [(mod['id'], mod.get('max_rank') or 0)]), db)
    res.check('unknown/withheld', 'a faction bonus with no target stated is withheld, not zero',
              with_mod['result']['faction_multiplier'] == 1.0
              and with_mod['evaluation']['state'] == 'conditional'
              and with_mod['evaluation']['withheld'] == ['target_faction'],
              {'multiplier': with_mod['result']['faction_multiplier'],
               'state': with_mod['evaluation']['state']})
    res.check('unknown/numbers-intact',
              'and every Phase 1 number is exactly what it was without the mod',
              all(with_mod['result']['stats'].get(k) == v
                  for k, v in plain['result']['stats'].items()),
              {k: (plain['result']['stats'][k], with_mod['result']['stats'].get(k))
               for k in plain['result']['stats']
               if with_mod['result']['stats'].get(k) != plain['result']['stats'][k]})
    faction = sorted(k for k in (mod['effects'].get('rank_table') or {})
                     if k.startswith('faction_'))[0].split('_', 1)[1]
    stated = api.compute(_build(weapon, [(mod['id'], mod.get('max_rank') or 0)]), db,
                         {'context': {'target_faction': faction}})
    res.check('unknown/context-resolves', 'and stating the target resolves it (the pipeline works)',
              stated['evaluation']['state'] == 'deterministic'
              and stated['result']['faction_multiplier'] > 1.0,
              stated['result']['faction_multiplier'])


def check_unsupported_never_applies(res, db):
    """5. A mechanic the engine cannot model never produces a number."""
    cold, toxin = _viral_mods(db, _weapon_id(db))
    if not (cold and toxin):
        res.check('unsupported/viral-mods', 'Cryo Rounds + Infected Clip are in the database',
                  False, 'missing')
        return
    weapon = _weapon_id(db)
    build = _build(weapon, [(cold['id'], 5), (toxin['id'], 5)])
    over = api.compute(build, db, {'context': {'target': {'viral_stacks': 12,
                                                          'protection': 'health'}}})
    res.check('unsupported/viral-cap',
              'stacks above the cap are unsupported, and no multiplier is produced',
              'viral_amplifier' not in over['result']['stats']
              and any(r['state'] == conditions.UNSUPPORTED for r in over['conditions']),
              [(r['condition'], r['state']) for r in over['conditions']])
    bad_landing = api.compute(build, db, {'context': {'target': {'viral_stacks': 3,
                                                                 'protection': 'hull'}}})
    res.check('unsupported/viral-landing', 'an unknown landing is unsupported, not assumed',
              'viral_amplifier' not in bad_landing['result']['stats'],
              bad_landing['evaluation']['state'])
    # unmodelled stats: a mod that declares a stat the engine does not model must refuse it
    unmodelled = []
    for row in db['mods'].values():
        eff = row.get('effects') or {}
        if eff.get('unmodelled'):
            unmodelled.append(row)
            if len(unmodelled) >= 25:
                break
    silent = []
    for row in unmodelled:
        out = _compute(db, row)
        if out is None:
            continue
        codes = {m['code'] for m in out['result']['unsupported']}
        if 'unmodelled_effect' not in codes:
            silent.append(row['name'])
    res.check('unsupported/unmodelled-named', 'an unmodelled stat is named, never a silent zero',
              not silent, {'sampled': len(unmodelled), 'silent': silent[:5]})


def check_documented_numbers(res, db):
    """The mechanics that ARE implemented still produce the documented numbers.

    A gate that only checked refusals would let the engine keep refusing correctly while quietly
    changing what it computes, so the implemented mechanics are pinned to the wiki's values: x2 at
    one viral stack, x3.25 at six, x4.25 at the ten-stack cap, and no value at all for a count the
    model cannot express.
    """
    wanted = {1: 2.0, 2: 2.25, 5: 3.0, 6: 3.25, 10: 4.25}
    wrong = {n: statuses.amplifier(n) for n, want in wanted.items()
             if statuses.amplifier(n) != want}
    res.check('numbers/viral-formula', 'the viral multiplier is the documented formula',
              not wrong, {'wrong': wrong, 'formula': statuses.FORMULA})
    refused = {str(n): statuses.amplifier(n) for n in (11, 2.5, -1, None, True, 'x')}
    res.check('numbers/viral-refuses', 'and it produces no value outside its domain',
              all(v is None for v in refused.values()), refused)
    states = {}
    for target in ({'viral_stacks': 3, 'protection': 'health'},
                   {'viral_stacks': 0, 'protection': 'health'},
                   {'viral_stacks': 3},
                   {'viral_stacks': 30, 'protection': 'health'}):
        states[str(target)] = statuses.evaluate(
            conditions.normalise_context({'target': target}))['state']
    res.check('numbers/viral-states', 'the viral mechanic reaches all four states',
              set(states.values()) == set(conditions.STATES), states)


def check_malformed_input_never_crashes(res, db):
    """6. Junk in, structured answer out. A crash here is how a refusal becomes an error."""
    weapon = _weapon_id(db)
    mod = _faction_mod(db)
    mods = [(mod['id'], mod.get('max_rank') or 0)] if mod else []
    crashes = []
    for context in BAD_CONTEXTS:
        for options in ([{'context': context}] + [dict(o, context=context) for o in BAD_OPTIONS
                                                  if isinstance(o, dict)]):
            try:
                out = api.compute(_build(weapon, mods), db, options)
                if not isinstance(out, dict) or 'evaluation' not in out:
                    crashes.append(('shape', context, options))
            except Exception as exc:                                  # noqa: BLE001
                crashes.append(('%s: %s' % (type(exc).__name__, exc), context, options))
    for options in BAD_OPTIONS:
        try:
            api.compute(_build(weapon, mods), db, options)
        except Exception as exc:                                      # noqa: BLE001
            crashes.append(('%s: %s' % (type(exc).__name__, exc), None, options))
    # the rank fields are the other place a malformed build used to reach an exception: int('abc')
    # raised ValueError and int(1e400) raised OverflowError, which the route turned into a 500
    nasty_ranks = ('abc', 'x', [1], 1e400, float('inf'), float('nan'), 3.5, -2, True, {}, '12')
    for bad_rank in nasty_ranks:
        for key in ('equipment_rank', 'mastery_rank'):
            bad_build = {'equipment_id': weapon, 'slots': [], key: bad_rank}
            try:
                out = api.compute(bad_build, db)
                if not isinstance(out, dict) or not out.get('validation'):
                    crashes.append(('shape', key, bad_rank))
            except Exception as exc:                                  # noqa: BLE001
                crashes.append(('%s: %s' % (type(exc).__name__, exc), key, bad_rank))
    for bad_build in ([], 'x', 3, None, {'equipment_id': 5}, {'slots': 'no'},
                      {'equipment_id': weapon, 'slots': [None, 3, {'kind': 'normal'}]}):
        try:
            out = api.compute(bad_build, db)
            if not isinstance(out, dict):
                crashes.append(('shape', bad_build, None))
        except Exception as exc:                                      # noqa: BLE001
            crashes.append(('%s: %s' % (type(exc).__name__, exc), bad_build, None))
    # ... and the three shapes the independent verifier found outside the first version of this
    # corpus: an unhashable equipment key, an unhashable mod key, and a mod rank of 10**1000.
    for extra in BAD_BUILDS_EXTRA:
        probe = dict(extra)
        if probe.get('equipment_id') and isinstance(probe['equipment_id'], str):
            probe['equipment_id'] = weapon
        try:
            out = api.compute(probe, db)
            if not isinstance(out, dict) or not out.get('validation'):
                crashes.append(('shape', probe, None))
        except Exception as exc:                                      # noqa: BLE001
            crashes.append(('%s: %s' % (type(exc).__name__, exc), probe, None))
    res.check('malformed/never-crashes', 'malformed builds, options and contexts never crash',
              not crashes, crashes[:4])


def check_stated_inputs_are_named(res, db):
    """A stated input the engine has no model for is refused by name, never dropped.

    The failure this exists to catch is silence: a caller states a target, the answer says
    `context_supplied: true`, and nothing anywhere says the input was not used. A warframe has no
    target model, so it is the honest test case - and it is a real one, not a synthetic build.
    """
    frame = None
    for eid, row in db['equipment'].items():
        if row.get('kind') == 'warframe':
            frame = eid
            break
    if frame is None:
        res.check('context/stated-inputs-named', 'a stated input with no model is named',
                  False, 'no warframe in this database')
        return
    stated = {'target_faction': 'grineer', 'target': {'viral_stacks': 6}}
    out = api.compute(_build(frame), db, {'context': stated})
    unused = (out.get('evaluation') or {}).get('unused') or []
    markers = [m for m in (out.get('unsupported') or []) if m.get('code') == 'context_unused']
    condition = (markers[0].get('condition') or {}) if markers else {}
    res.check('context/stated-inputs-named',
              'an input this engine has no model for is refused by name, not dropped',
              out.get('ok') is True and sorted(unused) == ['target.viral_stacks', 'target_faction']
              and len(markers) == 1 and condition.get('state') == conditions.UNSUPPORTED
              and condition.get('reason_code') == 'context_unused',
              'unused=%s markers=%d state=%s' % (unused, len(markers), condition.get('state')))

    # ... and an input the engine *did* use must not be called unused.
    weapon = _weapon_id(db)
    used = api.compute(_build(weapon), db,
                       {'context': {'target': {'viral_stacks': 4, 'protection': 'health'}}})
    res.check('context/used-inputs-not-flagged',
              'an input the engine did use is not reported as unused',
              not (used.get('evaluation') or {}).get('unused'),
              'unused=%r' % ((used.get('evaluation') or {}).get('unused'),))


def check_validation_codes_are_complete(res, db):
    """The other half of the vocabulary rule: a code the engine emits must be in `validation.CODES`.

    Read from the source rather than the payload, because the point is to catch a code that no
    test happens to trigger. The four condition states and the validation codes never overlap.
    """
    import re
    BS, QT = chr(92), chr(39)
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    emitted = set()
    for name in ('builds/validation.py', 'builds/capacity.py'):
        path = os.path.join(root, name)
        if not os.path.exists(path):
            continue
        text = io.open(path, encoding='utf-8').read()
        pat = BS + 'b(?:error|_err)' + BS + '(' + BS + 's*' + QT + '([a-z_]+)' + QT
        for match in re.finditer(pat, text):
            emitted.add(match.group(1))
    res.check('states/validation-codes-complete',
              'every code the validation and capacity engines emit is listed in validation.CODES',
              bool(emitted) and emitted.issubset(set(validation.CODES)),
              'unlisted=%s' % sorted(emitted - set(validation.CODES)))


def check_registry_covers_every_refusal(res, db):
    """7. Every refusal the engine can emit has a registry row (the project's own rule)."""
    weapon = _weapon_id(db)
    missing = set()
    for row in list(_conditional_mods(db))[:60]:
        out = _compute(db, row)
        if out is None:
            continue
        missing.update(unsupported.check_coverage(out['result']['unsupported']))
    for options in ({'strict': True}, {'context': {'target': {'viral_stacks': 6,
                                                              'protection': 'health'}}},
                    {'hypothetical': True}):
        out = api.compute(_build(weapon), db, options)
        missing.update(unsupported.check_coverage(out['result'].get('unsupported') or []))
    res.check('registry/coverage', 'every emitted refusal code has a registry entry',
              not missing, sorted(missing)[:6])


def check_refused_mode_withholds(res, db):
    """8. Strict evaluation withholds the affected stats instead of answering them."""
    mod = _faction_mod(db)
    if mod is None:
        res.check('strict/faction-mod-present', 'a faction mod is in the database', False, 'none')
        return
    out = api.compute(_build(_weapon_id(db), [(mod['id'], mod.get('max_rank') or 0)]), db,
                      {'strict': True})
    stats = out['result']['stats']
    res.check('strict/refused', 'a strict evaluation with an unresolved condition refuses',
              out['evaluation']['state'] == 'refused'
              and out['evaluation']['refused_stats']
              and all(stats.get(s) is None for s in out['evaluation']['refused_stats']),
              {'state': out['evaluation']['state'],
               'refused': out['evaluation']['refused_stats']})


def check_page_does_no_maths(res, page_text=None):
    """9. The page renders engine state; the formula stays in builds/."""
    texts = {}
    if page_text is None:
        for name in PAGE_FILES:
            path = REPO / 'static' / name
            texts[name] = path.read_text(encoding='utf-8') if path.exists() else ''
    else:
        texts = dict(page_text)
    found = []
    for name, text in texts.items():
        for needle in FORBIDDEN_ON_PAGE:
            if needle in text:
                found.append('%s: %s' % (name, needle))
    res.check('page/no-maths', 'no Phase 4 formula constant appears in the page',
              not found, found)


def _number_paths(node, keys, path=''):
    """Every path where a value under one of `keys` is still a number."""
    hits = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key in keys and isinstance(value, (int, float)):
                hits.append(path + '/' + key)
            hits += _number_paths(value, keys, path + '/' + key)
    elif isinstance(node, list):
        for i, value in enumerate(node):
            hits += _number_paths(value, keys, path + '/' + str(i))
    return hits


def _first_frame(db):
    for eid in sorted(db['equipment']):
        if (db['equipment'][eid].get('kind') or '') == 'warframe':
            return eid
    return None


def _plain_build(equipment):
    return {'config': 'A', 'equipment_id': equipment, 'equipment_rank': 30, 'mastery_rank': 30,
            'slots': []}


def check_refused_numbers_do_not_survive(res, db):
    """A refused stat's number must not exist anywhere else in the payload (review F2)."""
    mod = _faction_mod(db) or _conditional_mods(db)[0]
    equipment = _equipment_for(db, mod)
    out = api.compute(_build(equipment, [(mod['id'], mod.get('max_rank') or 0)],
                             kind=_slot_kind(mod)), db, {'strict': True})
    refused = set((out.get('evaluation') or {}).get('refused_stats') or [])
    survivors = _number_paths(out.get('result') or {}, refused)
    # The named paths too: `dps.burst.value` is a number under a key called `value`, so a walker
    # that only looks for keys named after the stat would miss the exact leak this check is for.
    survivors += _mirror_survivors(out.get('result') or {}, refused)
    res.check('strict/no-number-survives',
              'a refused stat is withheld everywhere it is reported, traces included',
              bool(refused) and not survivors,
              {'refused': sorted(refused), 'survivors': survivors[:4]})


def _mirror_survivors(result, refused):
    """Which of the engine's mirror paths still report a refused stat's number."""
    hits = []
    for stat in sorted(refused):
        for path in weapons.MIRROR_PATHS.get(stat, ()):
            node = result
            for key in path:
                node = node.get(key) if isinstance(node, dict) else None
            if isinstance(node, (int, float)):
                hits.append(stat + ' -> ' + '/'.join(path))
        trace = (result.get('traces') or {}).get(stat)
        if isinstance(trace, dict) and isinstance(trace.get('final'), (int, float)):
            hits.append(stat + ' -> traces/' + stat + '/final')
    return hits


def check_hypothetical_never_invents_a_number(res, db):
    """A hypothetical evaluation applies what it can and invents nothing (review F1)."""
    weapon = _weapon_id(db)
    out = api.compute(_plain_build(weapon), db,
                      {'hypothetical': True, 'context': {'target': {'viral_stacks': 6}}})
    stats = ((out.get('result') or {}).get('stats')) or {}
    res.check('hypothetical/never-invents',
              'an unresolvable input produces no number, hypothetical mode included',
              out.get('ok') is True and stats.get('viral_amplifier') is None
              and 'damage_to_health' not in stats,
              {'ok': out.get('ok'), 'viral_amplifier': stats.get('viral_amplifier')})


def check_engine_evaluation_is_declared(res, db):
    """The Warframe engine has no condition model and must say so (review F3)."""
    frame = _first_frame(db)
    weapon = _weapon_id(db)
    a = api.compute(_plain_build(frame), db) if frame else {}
    b = api.compute(_plain_build(weapon), db) if weapon else {}
    ev_a, ev_b = a.get('evaluation') or {}, b.get('evaluation') or {}
    res.check('evaluation/engine-declared',
              'a frame build reports not_evaluated; a weapon build reports its engine evaluated',
              ev_a.get('state') == 'not_evaluated' and ev_a.get('engine_evaluated') is False
              and ev_b.get('engine_evaluated') is True,
              {'frame': ev_a.get('state'), 'weapon': ev_b.get('state'),
               'frame_flag': ev_a.get('engine_evaluated')})




def run_checks(db, page_text=None, verbose=False, min_corpus=100):
    """Every check, in order. Returns a Result (never raises).

    `min_corpus` is the number of conditional mods the database is expected to carry: the real
    ingested database has hundreds, the test fixture has one, and the check should scale down
    rather than lie about it.
    """
    res = Result()
    for fn in (check_state_vocabulary, check_corpus_still_refuses,
               check_nothing_conditional_reaches_the_totals, check_unknown_never_becomes_zero,
               check_unsupported_never_applies, check_documented_numbers,
               check_malformed_input_never_crashes, check_validation_codes_are_complete,
               check_registry_covers_every_refusal, check_refused_mode_withholds,
               check_stated_inputs_are_named, check_refused_numbers_do_not_survive,
               check_hypothetical_never_invents_a_number,
               check_engine_evaluation_is_declared, check_states_reachable):
        try:
            if fn is check_corpus_still_refuses:
                fn(res, db, min_corpus=min_corpus)
            else:
                fn(res, db)
        except Exception as exc:                                          # noqa: BLE001
            res.check('error/%s' % fn.__name__, '%s raised' % fn.__name__, False,
                      traceback.format_exc().splitlines()[-1])
    check_page_does_no_maths(res, page_text)
    if verbose:
        for row in res.rows:
            print('%s  %-28s %s%s' % ('PASS' if row['ok'] else 'FAIL', row['id'], row['label'],
                                      '' if row['ok'] else ' -- %s' % row['detail']))
    return res


# --------------------------------------------------------------------------- falsification

class Break:
    """One deliberate defect, installed for the duration of a check run."""

    def __init__(self, name, how, why):
        self.name, self.how, self.why = name, how, why


def _install(breaks):
    return [b.how() for b in breaks]


def _restore(undo):
    for fn in reversed(undo):
        fn()


def _break_state_coercion():
    """An unknown condition reports itself as applied (the classic 'unknown -> 0' bug)."""
    original = conditions.result

    def lying(condition_id, state, reason, **extra):
        row = original(condition_id, state, reason, **extra)
        if row['state'] == conditions.UNKNOWN:
            row['applied'] = True
        return row

    conditions.result = lying

    def undo():
        conditions.result = original
    return undo


def _break_state_vocabulary():
    """A fifth 'state' - `false` - appears in the space, so a boolean can stand in for a state."""
    original = conditions.STATES

    def undo():
        conditions.STATES = original
    conditions.STATES = tuple(original) + ('false',)
    return undo


def _break_classifier():
    """The text classifier decides a condition holds, which it cannot know."""
    original = conditions.classify_conditional_text

    def lying(text):
        cid, _state, why, code = original(text)
        return cid, conditions.SATISFIED, 'assumed satisfied', code

    conditions.classify_conditional_text = lying

    def undo():
        conditions.classify_conditional_text = original
    return undo


def _break_viral_cap():
    """Past the stack cap the mechanic returns a number instead of refusing."""
    original = statuses.amplifier

    def loose(stacks):
        return 4.25

    statuses.amplifier = loose

    def undo():
        statuses.amplifier = original
    return undo


def _break_rider_lands():
    """A contribution that does not come from the mod's unconditional table is folded into the
    totals - the arithmetic signature of a rider that landed (4.2's bug class). The value is
    nudged rather than added from the conditional text on purpose: only 11 of 430 stored
    conditional lines re-parse to a stat, so a leak keyed on that would be inert, and an inert
    falsification proves nothing."""
    original = effects.collect_mod_effects

    def leaky(mod_slots):
        totals, unsupported, notes = original(mod_slots)
        for slot in mod_slots or []:
            eff = (slot.get('mod') or {}).get('effects') or {}
            for stat, values in (eff.get('rank_table') or {}).items():
                entry = totals.get(stat)
                if isinstance(entry, dict) and values:
                    entry['value'] = entry.get('value', 0) + max(1.0, abs(entry.get('value') or 0) * 0.01)
                    break
        return totals, unsupported, notes

    effects.collect_mod_effects = leaky

    def undo():
        effects.collect_mod_effects = original
    return undo


def _break_unused_fields():
    """A stated input the engine cannot use stops being reported (silence)."""
    original = conditions.unused_fields

    def silent(ctx, consumed):
        return []

    conditions.unused_fields = silent

    def undo():
        conditions.unused_fields = original
    return undo



def _break_malformed_tolerance():
    """A malformed context raises instead of degrading to `unknown`."""
    original = conditions.normalise_context

    def strict(raw):
        if raw is not None and not isinstance(raw, dict):
            raise TypeError('context must be an object')
        return original(raw)

    conditions.normalise_context = strict

    def undo():
        conditions.normalise_context = original
    return undo


def _break_page_purity():
    """A formula constant lands in the page."""
    return lambda: None


def _break_mirror_leak():
    """Refuse the stat in `stats` only - exactly the F2 shape, so the other mirrors keep it."""
    original = weapons._withhold_mirrors
    weapons._withhold_mirrors = lambda result, refused: result

    def undo():
        weapons._withhold_mirrors = original
    return undo


def _break_hypothetical_invents():
    """Hand an unknown viral row an amplifier anyway (the F1 shape)."""
    original = statuses.evaluate

    def optimistic(ctx):
        row = original(ctx)
        if isinstance(row, dict) and 'amplifier' not in row:
            row['amplifier'] = 4.25
        return row

    statuses.evaluate = optimistic

    def undo():
        statuses.evaluate = original
    return undo


def _break_engine_evaluation_claimed():
    """Claim every engine evaluated its conditions."""
    original = api.compute

    def fudged(build, db, options=None, **kw):
        out = original(build, db, options, **kw)
        evaluation = out.get('evaluation')
        if isinstance(evaluation, dict):
            evaluation['engine_evaluated'] = True
            if evaluation.get('state') == 'not_evaluated':
                evaluation['state'] = 'deterministic'
        return out

    api.compute = fudged

    def undo():
        api.compute = original
    return undo




BREAKS = (
    Break('unknown-reporting-applied', _break_state_coercion,
          'a withheld condition starts contributing'),
    Break('fifth-state-false', _break_state_vocabulary,
          'a boolean can stand in for a condition state'),
    Break('classifier-assumes-satisfied', _break_classifier,
          'conditional text is treated as satisfied'),
    Break('stated-input-dropped', _break_unused_fields,
          'a stated input with no model is silently ignored'),
    Break('rider-lands-in-totals', _break_rider_lands,
          "a conditional rider's value is folded into the totals"),
    Break('viral-cap-approximated', _break_viral_cap,
          'an unsupported stack count produces a multiplier'),
    Break('refused-number-survives', _break_mirror_leak,
          'a refused stat keeps its number in the mirrored structures'),
    Break('hypothetical-invents', _break_hypothetical_invents,
          'a hypothetical evaluation invents an amplifier it was never given'),
    Break('evaluation-claimed', _break_engine_evaluation_claimed,
          'an engine that never evaluated claims it did'),
    Break('malformed-context-raises', _break_malformed_tolerance,
          'a junk context crashes instead of answering unknown'),
)


def falsify(db, verbose=False, min_corpus=100):
    """Prove each check bites: install a defect, run the gate, require a FAILURE."""
    out = []
    for brk in BREAKS:
        undo = _install([brk])
        try:
            res = run_checks(db, min_corpus=min_corpus)
        finally:
            _restore(undo)
        caught = bool(res.failures)
        out.append({'break': brk.name, 'why': brk.why, 'caught': caught,
                    'failed': [r['id'] for r in res.failures][:6]})
        if verbose:
            print('%s  break %-30s %s' % ('OK ' if caught else 'MISS', brk.name,
                                          ','.join(r['id'] for r in res.failures[:4])))
    # the page check, falsified with poisoned text rather than a patched engine
    poisoned = {name: 'const AMP = 4.25;' for name in PAGE_FILES}
    res = run_checks(db, page_text=poisoned, min_corpus=min_corpus)
    out.append({'break': 'page-carries-formula', 'why': 'a formula constant appears in the page',
                'caught': bool(res.failures), 'failed': [r['id'] for r in res.failures][:6]})
    if verbose:
        print('%s  break %-30s %s' % ('OK ' if out[-1]['caught'] else 'MISS',
                                      'page-carries-formula', 'page/no-maths'))
    return out


# --------------------------------------------------------------------------- report + cli

def write_report(res, fals, db_name, checks_extra=''):
    lines = ['# Refusal-preservation gate - Phase 4', '',
             '```',
             'python design/_planner/conditions_gate.py%s' % checks_extra,
             'database: %s' % db_name,
             '```', '',
             '| check | result |', '| --- | --- |']
    for row in res.rows:
        lines.append('| `%s` %s | %s |' % (row['id'], row['label'],
                                           'PASS' if row['ok'] else 'FAIL'))
    broken = [r for r in res.failures]
    lines += ['', '**%d checks, %d failed.**' % (len(res.rows), len(broken))]
    if broken:
        lines += ['', 'Failures:']
        for row in broken:
            lines.append('- `%s` - %s' % (row['id'], row['detail']))
    if fals:
        lines += ['', '## Falsification: does the gate catch breakage?', '',
                  '| deliberate break | what it would let through | caught | failed checks |',
                  '| --- | --- | --- | --- |']
        for row in fals:
            lines.append('| %s | %s | %s | %s |' % (row['break'], row['why'],
                                                    'yes' if row['caught'] else '**NO**',
                                                    ', '.join('`%s`' % f for f in row['failed'])))
        missed = [r for r in fals if not r['caught']]
        lines += ['', '%d of %d breaks caught.' % (len(fals) - len(missed), len(fals))]
        if missed:
            lines += ['', '**NOT CAUGHT: %s**' % ', '.join(r['break'] for r in missed)]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return REPORT


def load_db():
    path = os.environ.get('WFM_BUILD_DB') or str(REPO / 'data' / 'build_data.json')
    if not Path(path).exists():
        return None, path
    return data.load(path), path


def main(argv=None):
    parser = argparse.ArgumentParser(description='Refusal-preservation gate (Phase 4)')
    parser.add_argument('--falsify', action='store_true',
                        help='prove the checks catch deliberately broken engines')
    parser.add_argument('--json', action='store_true', help='print the summary as JSON')
    parser.add_argument('--quiet', action='store_true')
    args = parser.parse_args(argv)
    db, path = load_db()
    if db is None:
        print('no database at %s - run: python builds/ingest.py' % path)
        return 2
    res = run_checks(db)
    fals = falsify(db, verbose=not args.quiet) if args.falsify else []
    report = write_report(res, fals, path, ' --falsify' if args.falsify else '')
    if args.json:
        print(json.dumps({'ok': res.ok, 'checks': len(res.rows),
                          'failed': [r['id'] for r in res.failures],
                          'falsification': fals, 'report': str(report)}, indent=1))
    else:
        for row in res.rows:
            print('%s  %-30s %s' % ('PASS' if row['ok'] else 'FAIL', row['id'], row['label']))
            if not row['ok']:
                print('        %s' % row['detail'])
        print('')
        print('%s - %d checks, %d failed' % ('GATE PASS' if res.ok else 'GATE FAIL',
                                             len(res.rows), len(res.failures)))
        if fals:
            missed = [r for r in fals if not r['caught']]
            print('falsification: %d of %d breaks caught' % (len(fals) - len(missed), len(fals)))
        print('report: %s' % report)
    if not res.ok:
        return 1
    if args.falsify and any(not row['caught'] for row in fals):
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
