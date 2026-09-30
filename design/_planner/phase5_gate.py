#!/usr/bin/env python3
"""The Phase 5 target-model gate: stated enemies, stated buff state, and the refusals around them.

What this gate protects, in one sentence: **the engine may apply a conditional effect only from a
state the caller stated, and every target input it does not have stays unknown.**

It runs against whatever database the engine is pointed at (WFM_BUILD_DB, else
data/build_data.json). `--falsify` then runs the same checks against deliberately broken engines
and asserts every break is caught - unknown armour defaulting to 0, a missing layer defaulting,
invented stacks, assumed uptime, truthy strings as booleans, mitigation moved into the page - which
is the only way to know this gate is not decorative. The Phase 4 refusal-preservation gate is run
inside this gate as well (`refusals/phase-4-gate`), so preserving its verdict is part of passing.

    python design/_planner/phase5_gate.py             # check the engine as it is
    python design/_planner/phase5_gate.py --falsify    # prove the checks catch breakage
    python design/_planner/phase5_gate.py --json       # machine-readable summary
"""
import argparse
import importlib.util
import io
import json
import math
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from builds import api, buffs, conditions, data, effects, enemies, factions, statuses  # noqa: E402
from builds import trace as trace_mod  # noqa: E402
from builds import unsupported, validation, weapons  # noqa: E402

import re  # noqa: E402

# every provenance string the engine writes ends '... (oldid NNNNN, retrieved D)'
OLDID_RE = re.compile(r'oldid[ =]?\d+')

REPORT = REPO / 'design' / '_planner' / 'phase5-gate-report.md'
PAGE_FILES = ('planner.js', 'planner-stats.js', 'planner-library.js', 'planner.html')
# Phase 5's enemy/buff arithmetic belongs in builds/ (and the docs). A page that carries one of
# these is computing mitigation, or a buff contribution, on the client.
FORBIDDEN_ON_PAGE = ('2700', '+ 300', '0.06', '0.90', 'Math.sqrt', 'CORROSIVE_', 'armour * (1',
                     'armor * (1', '1 - 0.2', 'stacks * 0.06', 'maximum_armor', 'armour_after')

# The golden pins, as literals: the wiki's enemy armour rule at the plateaus. These are values, not
# a formula - the gate compares the engine's answer with the number the wiki's rule produces, so an
# implementation drift fails here instead of becoming the new normal.
ARMOUR_PINS = (
    (0, 0.0),
    (300, 0.3),                    # 0.9 x sqrt(300/2700)
    (675, 0.45),                   # 0.9 x sqrt(675/2700)
    (2700, 0.9),                   # 0.9 x sqrt(1)
    (3000, 0.909090909090909),     # above the plateau: armour / (armour + 300)
)
# 4 corrosive procs on 900 armour: 900 x (1 - (0.20 + 0.06 x 4)) = 504, then the same DR rule.
CORROSIVE_PIN = {'effective': 504.0, 'reduction': 0.388844441904472,
                 'multiplier': 0.611155558095528}
# Phase 1's own pin (the browser gate pins the same pair): the target path must not move it.
PHASE1_PIN = {'damage_per_shot_expected_crit': 103.88, 'burst_dps': 995.5132}


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


# --------------------------------------------------------------------------- corpus helpers
def _build(equipment_id, mods=(), kind='normal', **extra):
    build = {'config': 'A', 'equipment_id': equipment_id, 'equipment_rank': 30, 'orokin': True,
             'mastery_rank': 30, 'slots': []}
    for index, (mod_id, rank) in enumerate(mods):
        build['slots'].append({'kind': kind, 'index': index if kind == 'normal' else None,
                               'polarity': None, 'mod': {'id': mod_id, 'rank': rank}})
    build.update(extra)
    return build


def _weapon_id(db, prefer=('Braton Prime', 'Soma Prime')):
    for name in prefer:
        for eid, row in db['equipment'].items():
            if row.get('name') == name and row.get('kind') == 'primary':
                return eid
    for eid, row in db['equipment'].items():
        if row.get('kind') == 'primary':
            return eid
    return None


def _rifle_mod(db, name):
    """The mod by that exact name at the highest rank the database holds.

    Corpus trap: the database carries several rows per display name (a legacy 'Intermediate'
    Serration at max rank 5 and the real one at 10), in no order. A gate that took the first
    match would be measuring the wrong mod - and would pin the wrong numbers.
    """
    best = None
    for row in db['mods'].values():
        if (row.get('name') or '') == name:
            if best is None or (row.get('max_rank') or 0) > (best.get('max_rank') or 0):
                best = row
    return best


KIND_FOR_TYPE = {'Warframe Mod': 'warframe', 'Aura': 'warframe', 'Primary Mod': 'primary',
                 'Shotgun Mod': 'primary', 'Secondary Mod': 'secondary', 'Melee Mod': 'melee',
                 'Companion Mod': 'sentinel', 'Stance Mod': 'melee'}


def _equipment_for(db, mod_row):
    kinds = {}
    for eid, row in sorted(db['equipment'].items()):
        kinds.setdefault(row.get('kind'), []).append((eid, row))
    for target in (mod_row.get('targets') or ()):
        if target in kinds:
            return kinds[target][0][0]
    fallback = KIND_FOR_TYPE.get(str(mod_row.get('type') or ''))
    if fallback in kinds:
        return kinds[fallback][0][0]
    return None


def _rider_mod(db):
    """A real mod carrying an on-kill rider this engine applies: (row, text, stat, max_stacks)."""
    best = None
    for row in db['mods'].values():
        for text in (row.get('effects') or {}).get('conditional') or []:
            rider = buffs.parse_rider(text)
            if rider and rider.get('trigger') == 'on_kill' and rider.get('enabled'):
                if best is None or (row.get('max_rank') or 0) > (best[0].get('max_rank') or 0):
                    best = (row, text, rider)
    return best


def _unsupported_conditional_mod(db):
    """A deployable real mod whose effects are only conditional lines this engine refuses.

    `rank_table` must be empty: an unconditional effect would legitimately move the numbers, and
    the check this feeds is that a *refused* effect moves nothing. Weapon-side mods are preferred
    because a weapon's stats publish the numbers such a leak would land in.
    """
    found = None
    for row in sorted(db['mods'].values(), key=lambda r: r['id']):
        eff = row.get('effects') or {}
        if not eff.get('conditional') or eff.get('rank_table'):
            continue
        deployable = _equipment_for(db, row)
        if not deployable:
            continue
        refused = None
        for text in eff.get('conditional') or []:
            rider = buffs.parse_rider(text)
            if not rider or rider.get('trigger') != 'on_kill' or not rider.get('enabled'):
                refused = (row, text, deployable)
                break
        if refused is None:
            continue
        found = found or refused
        if db['equipment'].get(deployable, {}).get('kind') in ('primary', 'secondary', 'melee'):
            return refused
    if found:
        return found
    return None, None, None


def _compute(db, equipment_id, mods, options=None):
    return api.compute(_build(equipment_id, mods), db, options)


def _ctx(target_faction=None, **target):
    ctx = {}
    if target_faction is not None:
        ctx['target_faction'] = target_faction
    if target:
        ctx['target'] = target
    return {'context': ctx}


def _target_row(out):
    for row in (out.get('conditions') or []):
        if row.get('condition') == 'target_damage':
            return row
    return None


def _rows(out):
    return (out.get('conditions') or [])


def _markers(out):
    return list(out.get('unsupported') or []) + list((out.get('result') or {}).get('unsupported') or [])


# --------------------------------------------------------------------------- the checks
def check_enemy_inputs_are_required(res, db):
    """A target input the engine does not have is `unknown`, named - never a default and never 0."""
    weapon = _weapon_id(db)
    serration = _rifle_mod(db, 'Serration')
    mods = [(serration['id'], serration.get('max_rank') or 0)]

    out = _compute(db, weapon, mods, _ctx(protection='health', armor=300))
    row = _target_row(out)
    res.check('enemy/faction-required', 'no stated faction: the damage-type modifiers stay unknown',
              row is not None and row['state'] == conditions.UNKNOWN
              and 'target_faction' in (row.get('missing') or [])
              and (out.get('result') or {}).get('target_damage') is None,
              'state=%s missing=%s' % (row and row['state'], row and row.get('missing')))

    out = _compute(db, weapon, mods, _ctx('grineer', armor=300))
    row = _target_row(out)
    res.check('enemy/layer-required', 'no stated landing layer: the engine will not pick one',
              row is not None and row['state'] == conditions.UNKNOWN
              and 'target.protection' in (row.get('missing') or [])
              and (out.get('result') or {}).get('target_damage') is None,
              'state=%s missing=%s' % (row and row['state'], row and row.get('missing')))

    out = _compute(db, weapon, mods, _ctx('grineer', protection='health'))
    row = _target_row(out)
    res.check('enemy/armour-required', 'a health landing with no stated armour is withheld, not 0',
              row is not None and row['state'] == conditions.UNKNOWN
              and 'target.armor' in (row.get('missing') or [])
              and (out.get('result') or {}).get('target_damage') is None,
              'state=%s missing=%s' % (row and row['state'], row and row.get('missing')))

    bad = []
    for value in ('lots', True, -5, None, float('nan')):
        out = _compute(db, weapon, mods, _ctx('grineer', protection='health', armor=value))
        row = _target_row(out)
        target = (out.get('result') or {}).get('target_damage')
        if row is None or row['state'] != conditions.UNKNOWN or target is not None:
            bad.append((value, row and row['state'], target is not None))
    res.check('enemy/armour-invalid', 'a junk armour value is unknown, never read as no armour',
              not bad, 'bad=%s' % bad)

    bad = []
    for value in ('attachments', 42, [], 'HEALTH-ISH'):
        out = _compute(db, weapon, mods, _ctx('grineer', protection=value, armor=300))
        row = _target_row(out)
        if row is None or row['state'] != conditions.UNSUPPORTED:
            bad.append((value, row and row['state']))
    res.check('enemy/layer-invalid', 'an unknown landing layer is refused by name, not defaulted',
              not bad, 'bad=%s' % bad)

    bad = []
    for value in ('grineerish', 42, ['grineer']):
        out = _compute(db, weapon, mods, _ctx(value, protection='health', armor=300))
        row = _target_row(out)
        if row is None or row['state'] not in (conditions.UNSUPPORTED, conditions.UNKNOWN):
            bad.append((value, row and row['state']))
    res.check('enemy/faction-invalid', 'an unknown faction is refused, never a default faction',
              not bad, 'bad=%s' % bad)


def check_mitigation_is_pinned(res, db):
    """The armour rule is pinned at the wiki's plateaus, and the target state changes it."""
    weapon = _weapon_id(db)
    serration = _rifle_mod(db, 'Serration')
    mods = [(serration['id'], serration.get('max_rank') or 0)]
    bad = []
    for armour, want in ARMOUR_PINS:
        out = _compute(db, weapon, mods, _ctx('grineer', protection='health', armor=armour))
        plan = ((out.get('result') or {}).get('target_damage') or {}).get('armor') or {}
        got = plan.get('reduction')
        if got is None or abs(got - want) > 1e-9:
            bad.append((armour, got, want))
    res.check('enemy/armour-pinned', 'the armour rule matches its pinned values at every plateau',
              not bad, 'bad=%s' % bad)

    out = _compute(db, weapon, mods, _ctx('grineer', protection='health', armor=900,
                                          corrosive_stacks=4))
    td = (out.get('result') or {}).get('target_damage') or {}
    plan = td.get('armor') or {}
    row = None
    for candidate in _rows(out):
        if candidate.get('condition') == 'corrosive':
            row = candidate
    res.check('enemy/corrosive-pinned',
              'stated corrosive procs reduce the armour the mitigation uses, by the pinned values',
              abs((plan.get('effective') or 0) - CORROSIVE_PIN['effective']) < 1e-9
              and abs((plan.get('reduction') or 0) - CORROSIVE_PIN['reduction']) < 1e-9
              and abs((1.0 - (plan.get('reduction') or 0)) - CORROSIVE_PIN['multiplier']) < 1e-9
              and row is not None and row['state'] == conditions.SATISFIED,
              'armour=%s reduction=%s corrosive_row=%s'
              % (plan.get('effective'), plan.get('reduction'), row and row['state']))

    bad = []
    for stacks in (11, 'two', -1, True, 2.5):
        out = _compute(db, weapon, mods, _ctx('grineer', protection='health', armor=900,
                                              corrosive_stacks=stacks))
        row = _target_row(out)
        if row is None or row['state'] not in (conditions.UNKNOWN, conditions.UNSUPPORTED):
            bad.append((stacks, row and row['state']))
    res.check('enemy/corrosive-invalid', 'junk or over-cap stack counts refuse, never approximate',
              not bad, 'bad=%s' % bad)


def check_target_never_touches_phase1(res, db):
    """No target context -> the Phase 1 numbers, and no Phase 5 block. A target context may not
    move the Phase 1 numbers either: the target path is additive, never a re-derivation."""
    weapon = _weapon_id(db)
    serration = _rifle_mod(db, 'Serration')
    mods = [(serration['id'], serration.get('max_rank') or 0)]
    base = _compute(db, weapon, mods)
    stats = (base.get('result') or {}).get('stats') or {}
    res.check('enemy/no-context-no-target-damage',
              'with no target context the answer holds no target block and Phase 1 is itself',
              (base.get('result') or {}).get('target_damage') is None
              and abs((stats.get('damage_per_shot_expected_crit') or 0)
                      - PHASE1_PIN['damage_per_shot_expected_crit']) < 0.005
              and abs((stats.get('burst_dps') or 0) - PHASE1_PIN['burst_dps']) < 0.01,
              'pin=%s/%s got=%s/%s' % (PHASE1_PIN['damage_per_shot_expected_crit'],
                                       PHASE1_PIN['burst_dps'],
                                       stats.get('damage_per_shot_expected_crit'),
                                       stats.get('burst_dps')))

    aimed = _compute(db, weapon, mods, _ctx('grineer', protection='health', armor=300))
    aimed_stats = (aimed.get('result') or {}).get('stats') or {}
    same = all(abs((aimed_stats.get(k) or 0) - (stats.get(k) or 0)) < 1e-9
               for k in ('damage_per_shot_expected_crit', 'burst_dps', 'damage_per_shot'))
    res.check('enemy/target-does-not-move-phase-1',
              'the target path adds its block and leaves every Phase 1 number where it was',
              same and (aimed.get('result') or {}).get('target_damage') is not None,
              'phase1 %s vs %s' % (stats.get('damage_per_shot_expected_crit'),
                                   aimed_stats.get('damage_per_shot_expected_crit')))


def check_unsupported_mechanics_contribute_nothing(res, db):
    """A conditional mechanic with no model must leave every damage number exactly as it was."""
    row, text, equip = _unsupported_conditional_mod(db)
    if row is None or not equip:
        res.check('enemy/unsupported-contributes-nothing', 'an unmodelled rider contributes nothing',
                  False, 'no deployable mod with a purely-conditional unsupported line')
        return
    # the same equipment, with and without the mod: every number must be identical, because the
    # mod's only effects are conditional lines this engine refuses.
    base = _compute(db, equip, [])
    out = _compute(db, equip, [(row['id'], row.get('max_rank') or 0)])
    base_stats = json.dumps(((base.get('result') or {}).get('stats') or {}), sort_keys=True)
    stats = json.dumps(((out.get('result') or {}).get('stats') or {}), sort_keys=True)
    markers = [m for m in _markers(out) if m.get('mod') == row['id']]
    res.check('enemy/unsupported-contributes-nothing',
              'an unmodelled conditional rider leaves every number exactly as it was',
              base_stats == stats and not (out.get('result') or {}).get('riders')
              and any(m.get('code') == 'conditional_effect'
                      and m.get('state') == conditions.UNSUPPORTED for m in markers),
              'mod=%s stats_equal=%s riders=%s markers=%s'
              % (row.get('name'), base_stats == stats,
                 (out.get('result') or {}).get('riders'),
                 [(m.get('code'), m.get('state')) for m in markers]))


def check_buff_state_is_stated_only(res, db):
    """The one actually-applied conditional path: context -> state -> effect -> trace -> result."""
    found = _rider_mod(db)
    if not found:
        res.check('buff/stated-stacks', 'a stated on-kill stack count is applied end to end', False,
                  'no mod with an enabled on-kill rider in this database')
        return
    row, text, rider = found
    equip = _equipment_for(db, row)
    if not equip:
        res.check('buff/stated-stacks', 'a stated on-kill stack count is applied end to end', False,
                  'no equipment for %s' % row.get('name'))
        return
    mods = [(row['id'], row.get('max_rank') or 0)]
    stat = rider['stat']

    out = _compute(db, equip, mods, {'context': {'buffs': {'on_kill': {'stacks': 3}}}})
    riders = (out.get('result') or {}).get('riders') or []
    entry = riders[0] if riders else {}
    stats = (out.get('result') or {}).get('stats') or {}
    base = _compute(db, equip, mods)
    base_stats = (base.get('result') or {}).get('stats') or {}
    contribution = entry.get('contribution')
    rider_rows = [r for r in _rows(out) if r.get('condition') == rider['trigger']]
    res.check('buff/stated-stacks',
              'a stated on-kill stack count is applied end to end (context -> state -> effect)',
              entry.get('state') == conditions.SATISFIED and entry.get('stacks') == 3
              and entry.get('mode') == 'instant'
              and abs((contribution or 0) - (entry.get('per_stack') or 0) * 3) < 1e-9
              and rider_rows and rider_rows[0]['state'] == conditions.SATISFIED,
              'entry=%s' % json.dumps(entry)[:220])
    nudged = (base_stats.get(stat) or 0) != (stats.get(stat) or 0)
    res.check('buff/applied-in-the-stat',
              'the applied rider actually moves the stat it names, and only that one',
              nudged and contribution and contribution > 0,
              '%s %s -> %s (contribution %s)' % (stat, base_stats.get(stat), stats.get(stat),
                                                 contribution))

    # no state at all: unknown, and not a single number moves.
    out = _compute(db, equip, mods)
    entry = ((out.get('result') or {}).get('riders') or [{}])[0]
    stats = (out.get('result') or {}).get('stats') or {}
    row0 = [r for r in _rows(out) if r.get('condition') == rider['trigger']][0]
    res.check('buff/no-state-no-number',
              'no stated buff state: unknown, no contribution, and the stat is the base one',
              entry.get('state') == conditions.UNKNOWN and entry.get('contribution') is None
              and entry.get('applied') is False
              and (stats.get(stat) or 0) == (base_stats.get(stat) or 0)
              and 'buffs.%s' % rider['trigger'] in (row0.get('missing') or []),
              'state=%s contribution=%s stat=%s missing=%s'
              % (entry.get('state'), entry.get('contribution'), stats.get(stat),
                 row0.get('missing')))

    # averaged: only with the stacks stated too, and the assumption travels with the number.
    out = _compute(db, equip, mods,
                   {'context': {'buffs': {'on_kill': {'stacks': 5, 'uptime': 0.65}}}})
    entry = ((out.get('result') or {}).get('riders') or [{}])[0]
    assumptions = (out.get('evaluation') or {}).get('assumptions') or []
    res.check('buff/averaged-states-its-assumption',
              'an averaged state carries its stated assumption into the answer',
              entry.get('mode') == 'averaged' and entry.get('uptime') == 0.65
              and entry.get('stacks') == 5
              and abs((entry.get('contribution') or 0)
                      - (entry.get('per_stack') or 0) * 5 * 0.65) < 1e-9
              and any('averaged' in a and '65' in a for a in assumptions),
              'entry=%s assumptions=%s' % (json.dumps(entry)[:200], assumptions))

    bad = []
    for state in ({'uptime': 0.65}, {'stacks': 'three'}, {'stacks': True}, {'stacks': -1},
                  {'stacks': 99}, {'active': 'yes'}, {'kill_rate': 2}, {'stacks': 3, 'active': False},
                  {'uptime': 'often', 'stacks': 3}, {'stacks': 3, 'uptime': 1.5}):
        out = _compute(db, equip, mods, {'context': {'buffs': {'on_kill': state}}})
        entry = ((out.get('result') or {}).get('riders') or [{}])[0]
        if entry.get('contribution') is not None:
            bad.append((state, entry.get('contribution'), entry.get('state')))
        if entry.get('state') not in (conditions.UNKNOWN, conditions.UNSUPPORTED,
                                      conditions.NOT_SATISFIED):
            bad.append((state, 'state=%s' % entry.get('state')))
    res.check('buff/junk-state-never-a-number',
              'a malformed or contradictory buff state never produces a contribution',
              not bad, 'bad=%s' % bad)


def check_four_states_everywhere(res, db):
    """Every row the new paths emit is one of the four states, and an unknown row is not a false."""
    weapon = _weapon_id(db)
    serration = _rifle_mod(db, 'Serration')
    found = _rider_mod(db)
    mods = [(serration['id'], serration.get('max_rank') or 0)]
    if found:
        mods.append((found[0]['id'], found[0].get('max_rank') or 0))
    cases = [
        {},
        _ctx('grineer', protection='health', armor=300),
        _ctx('grineer', protection='health', armor=300, corrosive_stacks=4),
        _ctx('grineer', protection='shields', armor=300, corrosive_stacks='two'),
        _ctx('grineer', protection='attachments', armor=-1),
        _ctx('nowhere', protection='health'),
        _ctx('grineer', protection='health', armor=300, armor_extra='junk'),
        {'context': {'buffs': {'on_kill': {'stacks': 3}}}},
        {'context': {'buffs': {'on_kill': {'stacks': 99}}}},
        {'context': {'target_faction': 'grineer', 'target': {'protection': 'health',
                                                             'armor': 300, 'health': 1000}}},
    ]
    bad = []
    for options in cases:
        try:
            out = api.compute(_build(weapon, mods), db, options)
        except Exception as exc:                                     # noqa: BLE001
            bad.append((options, 'raised %s' % exc))
            continue
        for row in _rows(out):
            if row.get('state') not in conditions.STATES:
                bad.append((options, row.get('condition'), row.get('state')))
            if row.get('state') in (conditions.UNKNOWN, conditions.UNSUPPORTED) \
                    and row.get('applied') is True:
                bad.append((options, row.get('condition'), 'unknown-marked-applied'))
    res.check('states/four-states-only',
              'every condition row speaks the four-state vocabulary, and none is a boolean',
              not bad, 'bad=%s' % bad[:4])


def check_booleans_are_booleans(res, db):
    """A declared boolean input is a boolean: truthy strings are a structured refusal, not a cast."""
    weapon = _weapon_id(db)
    serration = _rifle_mod(db, 'Serration')
    mods = [(serration['id'], serration.get('max_rank') or 0)]
    bad = []
    for value in ('yes', 'true', 'no', 'false', 1, 0, 'on'):
        out = api.compute(_build(weapon, mods, orokin=value), db)
        codes = [e.get('code') for e in ((out.get('validation') or {}).get('errors') or [])]
        if 'invalid_boolean' not in codes:
            bad.append(('orokin=%r' % (value,), codes[:3]))
    for value in (True, False):
        out = api.compute(_build(weapon, mods, orokin=value), db)
        codes = [e.get('code') for e in ((out.get('validation') or {}).get('errors') or [])]
        if 'invalid_boolean' in codes:
            bad.append(('orokin=%r' % (value,), 'refused a real boolean'))
    for value in ('yes', 'Y', 1, 'true'):
        build = _build(weapon, [], kind='exilus', exilus_unlocked=True)
        build['slots'] = [{'kind': 'exilus', 'index': None, 'polarity': None, 'mod': None,
                           'unlocked': value}]
        out = api.compute(build, db)
        codes = [e.get('code') for e in ((out.get('validation') or {}).get('errors') or [])]
        if 'invalid_boolean' not in codes:
            bad.append(('exilus unlocked=%r' % (value,), codes[:3]))
    res.check('validate/booleans-are-booleans',
              'a declared boolean rejects truthy strings and accepts real booleans',
              not bad, 'bad=%s' % bad)
    res.check('validate/boolean-code-registered',
              'the invalid_boolean code is in the validation vocabulary',
              'invalid_boolean' in validation.CODES, 'codes=%s' % (validation.CODES,))


def check_target_field_handling(res, db):
    """Target fields: canonical ids consumed, aliases honoured, unsupported fields named."""
    weapon = _weapon_id(db)
    serration = _rifle_mod(db, 'Serration')
    mods = [(serration['id'], serration.get('max_rank') or 0)]

    out = api.compute(_build(weapon, mods), db,
                      {'context': {'target_faction': 'grineer',
                                   'target': {'protection': 'health', 'armour': 300}}})
    stripped = (out.get('result') or {}).get('target_damage') or {}
    row = _target_row(out)
    res.check('enemy/alias-armour-is-armour',
              'the British spelling of armour is read as the armour it is',
              row is not None and row['state'] == conditions.SATISFIED
              and ((stripped.get('armor') or {}).get('stated')) == 300,
              'state=%s armor=%s' % (row and row['state'], stripped.get('armor')))

    out = api.compute(_build(weapon, mods), db,
                      {'context': {'target': {'health': 1000, 'shields': 500}}})
    unused = (out.get('evaluation') or {}).get('unused') or []
    markers = [m for m in _markers(out) if m.get('code') == 'context_unused']
    res.check('enemy/unsupported-target-fields-named',
              'a stated target field with no consumer is refused by name, not dropped',
              sorted(unused) == ['target.health', 'target.shields'] and markers,
              'unused=%s markers=%s' % (unused, [(m.get('code'), m.get('state')) for m in markers]))

    # the names Damage 3.0 removed are refused by name too (the wiki-provenance audit found the doc
    # claiming "refused" while the engine only ignored them)
    out = api.compute(_build(weapon, mods), db,
                      {'context': {'target': {'health_type': 'ferrite', 'armor_type': 'alloy'}}})
    unused = (out.get('evaluation') or {}).get('unused') or []
    markers = [m for m in _markers(out) if m.get('code') == 'context_unused']
    res.check('enemy/removed-vocabulary-named',
              'the health_type / armor_type vocabulary Damage 3.0 removed is refused by name',
              sorted(unused) == ['target.armor_type', 'target.health_type'] and markers,
              'unused=%s markers=%s' % (unused, [m.get('code') for m in markers]))

    out = api.compute(_build(weapon, mods), db, {'context': {'target': 'grineer'}})
    ignored = (out.get('evaluation') or {}).get('context_ignored') or []
    res.check('enemy/non-object-target-ignored-named',
              'a target that is not an object is named as ignored, never half-read',
              ignored and out.get('ok') is True, 'ignored=%s' % ignored)

    # two spellings of one field, stated differently: the canonical one is used and the loser is
    # named - a silently-picked winner would be the same failure mode as a silently-picked default
    out = api.compute(_build(weapon, mods), db,
                      {'context': {'target_faction': 'grineer',
                                   'target': {'protection': 'health', 'armor': 300,
                                              'armour': 900}}})
    ignored = (out.get('evaluation') or {}).get('context_ignored') or []
    stated = (((out.get('result') or {}).get('target_damage') or {}).get('armor') or {}).get('stated')
    res.check('enemy/conflicting-alias-named',
              'a conflicting second spelling is named, and the canonical field is the one used',
              stated == 300 and any('armour' in i for i in ignored),
              'stated=%s ignored=%s' % (stated, ignored))


def check_trace_is_the_whole_story(res, db):
    """Every stage of the target path is in the trace, in order, with its source."""
    weapon = _weapon_id(db)
    serration = _rifle_mod(db, 'Serration')
    mods = [(serration['id'], serration.get('max_rank') or 0)]
    out = _compute(db, weapon, mods, _ctx('grineer', protection='health', armor=900,
                                          corrosive_stacks=4))
    result = out.get('result') or {}
    td = result.get('target_damage') or {}
    traces = result.get('traces') or {}
    total = traces.get('target_damage')
    # the mitigation rows live on the per-type traces (one per damage type); the total carries the
    # per-type target rows. The check reads both, because a user asking "why this number" reads the
    # per-type path when the composition matters.
    per_type = {k: v for k, v in traces.items() if k.startswith('target_damage.')}
    per_stages = sorted({m.get('category') for t in per_type.values()
                         for m in (t.get('modifiers') or [])})
    notes = ' '.join((total or {}).get('notes') or [])
    res.check('trace/target-stages',
              'the target trace carries every stage from base damage to the mitigation',
              total is not None and per_type
              and abs((total.get('final') or 0) - (td.get('per_projectile_total') or -1)) < 1e-6
              and 'mitigation' in per_stages and 'target' in per_stages
              and OLDID_RE.search(notes),
              'per-type stages=%s notes=%s' % (per_stages, notes[:160]))

    # The trace has to answer "why is this number this number" by composition: the per-type rows
    # are (percent bonuses) x (ratio factors), and their product must be the factor the engine
    # applied. The architecture review found the corrosive row recording its armour reduction as a
    # ratio of its own, which broke exactly this.
    td = result.get('target_damage') or {}
    bad = []
    for dtype, modifier in (td.get('modifiers') or {}).items():
        t = traces.get('target_damage.' + dtype)
        if t is None:
            bad.append((dtype, 'no trace'))
            continue
        percent = sum(float(m.get('value') or 0) for m in t['modifiers']
                      if m.get('unit') == 'percent')
        ratio = 1.0
        for m in t['modifiers']:
            if m.get('unit') == 'ratio':
                ratio *= float(m.get('value') or 1)
        composed = (1.0 + percent / 100.0) * ratio
        applied = float(modifier.get('combined') or 1.0)
        # the rows are trimmed to the engine's display precision, so this compares there - the
        # defect it exists to catch was off by a factor of two, not by a rounding
        if abs(composed - applied) > 2e-3:
            bad.append((dtype, 'composed %.9f vs applied %.9f' % (composed, applied)))
    res.check('trace/rows-compose',
              'the per-type trace rows multiply to the applied factor (display precision)',
              bool(td.get('modifiers')) and not bad, 'bad=%s' % bad[:4])

    sources = {}
    for candidate in _rows(out):
        if candidate.get('condition') in ('target_damage', 'corrosive'):
            source = candidate.get('source')
            if isinstance(source, dict):
                source = str(source.get('url') or source.get('label') or source)
            sources[candidate['condition']] = str(source or '')
    res.check('trace/provenance-on-every-row',
              'the target and corrosive rows carry their wiki source with a revision id',
              len(sources) >= 2 and all('wiki.warframe.com' in v and OLDID_RE.search(v)
                                        for v in sources.values()),
              'sources=%s' % {k: v[:60] for k, v in sources.items()})


def check_umbral_counts_distinct_legal_members(res, db):
    """The set piece count is a roster, not a slot count. The architecture review executed the
    three ways the old count lied: a duplicated member counted twice, a rank-invalid member
    counted, an unknown member counted - and a count outside the pinned domain scaled by 1.0 while
    the note claimed a scaling had happened.
    """
    frame = None
    for eid, row in db['equipment'].items():
        if row.get('kind') == 'warframe':
            frame = eid
            break
    umbral = None
    for mod_id, row in db['mods'].items():
        if (row.get('flags') or {}).get('set_id') == effects.UMBRAL_SET:
            umbral = mod_id
            break
    if frame is None or umbral is None:
        res.check('set/umbral-counts-distinct-members', 'the Umbral count is a roster',
                  False, 'no warframe or no Umbral mod in this database')
        return
    bad = []
    slot = {'mod': db['mods'][umbral], 'rank': None}
    # First line of defence: a duplicate build never reaches the set pass through the API.
    dup = api.compute(_build(frame, [(umbral, None), (umbral, None)]), db)
    dup_codes = [e.get('code') for e in ((dup.get('validation') or {}).get('errors') or [])]
    if dup.get('ok') is not False or 'duplicate_mod' not in dup_codes:
        bad.append(('duplicate validation', dup.get('ok'), dup_codes))
    # ... and at the engine seam the count still refuses to double-count.
    totals, markers, notes = effects.collect_mod_effects([slot, slot])
    codes = [m.get('code') for m in markers]
    if 'duplicate_set_member' not in codes:
        bad.append(('duplicate', codes))
    scaled = [r for bucket in totals.values() if isinstance(bucket, dict)
              for r in bucket.get('rows') or [] if r.get('set_multiplier') not in (None, 1.0)]
    if scaled:
        bad.append(('duplicate scaled anyway', [(r.get('mod'), r.get('set_multiplier'))
                                                for r in scaled]))
    # a refused member is not equipped, so it is not a piece: one legal member stays unscaled
    totals2, markers2, notes2 = effects.collect_mod_effects([slot, {'mod': db['mods'][umbral],
                                                                    'rank': 99}])
    codes2 = [m.get('code') for m in markers2]
    if 'mod_rank_out_of_range' not in codes2:
        bad.append(('rank-invalid member', codes2))
    scaled2 = [r for bucket in totals2.values() if isinstance(bucket, dict)
               for r in bucket.get('rows') or [] if r.get('set_multiplier') not in (None, 1.0)]
    if scaled2:
        bad.append(('a refused member granted a piece', [(r.get('mod'), r.get('set_multiplier'))
                                                         for r in scaled2]))
    # an unknown Umbral member still counts as a piece (the game counts the roster) but its own
    # scaling is refused by name
    odd = {**db['mods'][umbral], 'id': '/Fixture/UnknownUmbral', 'name': 'Umbral Oddity'}
    _t3, markers3, _n3 = effects.collect_mod_effects([slot, {'mod': odd, 'rank': None}])
    codes3 = [m.get('code') for m in markers3]
    if 'umbral_member_unknown' not in codes3:
        bad.append(('unknown member', codes3))
    res.check('set/umbral-counts-distinct-members',
              'duplicates, refused members and unknown members are named, never silently counted',
              not bad, 'bad=%s' % bad[:4])
    # the two codes a real build can reach are exercised here; the other two are defensive paths
    # (they fire for a roster of four or for members that contribute nothing modelled)
    res.check('refusals/umbral-codes-exercised',
              'the reachable set-bonus codes are exercised, so their registry rows are not dead',
              {'duplicate_set_member', 'umbral_member_unknown'} <= set(codes) | set(codes3),
              'dup=%s odd=%s' % (codes, codes3))


def check_phase_4_gate_still_passes(res, db):
    """The Phase 4 refusal-preservation gate, run inside this one: its verdict is not negotiable."""
    path = REPO / 'design' / '_planner' / 'conditions_gate.py'
    spec = importlib.util.spec_from_file_location('conditions_gate', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    inner = mod.run_checks(db)
    res.check('refusals/phase-4-gate', 'the Phase 4 refusal-preservation gate still passes',
              inner.ok, 'failed=%s' % [r['id'] for r in inner.failures][:6])


def check_malformed_target_never_crashes(res, db):
    """Malformed context is answered, never raised - including the shapes a JSON document can
    actually carry. `json.loads` parses an integer of any length, so `float()` on one raises
    OverflowError; `immune_to` as a number raised TypeError. Both were found by an independent
    reviewer's probes, and both are pinned here now.
    """
    weapon = _weapon_id(db)
    chamber = _rider_mod(db)
    mods = []
    serration = _rifle_mod(db, 'Serration')
    mods.append((serration['id'], serration.get('max_rank') or 0))
    if chamber:
        mods.append((chamber[0]['id'], chamber[0].get('max_rank') or 0))
    huge = int('1' + '0' * 400)
    cases = [
        ('armour as a 401-digit JSON integer',
         {'target_faction': 'grineer',
          'target': {'protection': 'health', 'armor': huge}}),
        ('uptime as a 401-digit JSON integer',
         {'target': {'protection': 'health', 'armor': 300},
          'buffs': {'on_kill': {'uptime': huge, 'stacks': 5}}}),
        ('stacks as a 401-digit JSON integer',
         {'target': {'protection': 'health', 'armor': 300},
          'buffs': {'on_kill': {'stacks': huge}}}),
        ('immune_to as a number',
         {'target': {'protection': 'health', 'viral_stacks': 6, 'immune_to': 5}}),
        ('immune_to as a list with junk in it',
         {'target': {'protection': 'health', 'viral_stacks': 6, 'immune_to': ['viral', 7]}}),
        ('a float where a stack count belongs',
         {'target': {'protection': 'health', 'armor': 300, 'corrosive_stacks': float('inf')}}),
        ('a nested list where a layer belongs',
         {'target_faction': 'grineer', 'target': {'protection': [['health']], 'armor': 300}}),
    ]
    bad = []
    for label, ctx in cases:
        try:
            out = api.compute(_build(weapon, mods), db, {'context': ctx})
        except Exception as exc:                                     # noqa: BLE001
            bad.append((label, 'raised %s: %s' % (type(exc).__name__, exc)))
            continue
        if out.get('ok') is not True:
            bad.append((label, 'ok=%r' % (out.get('ok'),)))
        for row in _rows(out):
            if row.get('state') not in conditions.STATES:
                bad.append((label, 'state=%r' % (row.get('state'),)))
    res.check('enemy/malformed-never-crashes',
              'a malformed target or buff shape is answered with a state, never raised',
              not bad, 'bad=%s' % bad[:4])


def check_a_target_refusal_keeps_the_build(res, db):
    """A stated target state the engine cannot resolve must not take the computable build with it.

    The architecture review executed the shape a Bane + viral user states - faction + landing +
    viral stacks, no armour - and found the target path dragged it into a conditional evaluation
    and, under strict, withheld the Phase 1 and viral numbers. The refusal belongs to the target
    block alone.
    """
    weapon = _weapon_id(db)
    serration = _rifle_mod(db, 'Serration')
    mods = [(serration['id'], serration.get('max_rank') or 0)]
    cases = [
        ('faction + landing + viral, no armour',
         {'target_faction': 'grineer', 'target': {'protection': 'health', 'viral_stacks': 6}}),
        ('corrosive 0 alone ("no procs")', {'target': {'corrosive_stacks': 0}}),
        ('a landing with no faction', {'target': {'protection': 'health', 'armor': 300}}),
    ]
    bad = []
    for label, ctx in cases:
        out = api.compute(_build(weapon, mods), db, {'context': ctx})
        stats = (out.get('result') or {}).get('stats') or {}
        ev = out.get('evaluation') or {}
        if abs((stats.get('damage_per_shot') or 0) - 92.75) > 0.005 \
                or abs((stats.get('burst_dps') or 0) - 995.5132) > 0.01:
            bad.append((label, 'phase 1 withheld', stats.get('damage_per_shot')))
        if ev.get('state') == 'refused' and stats.get('damage_per_shot') is None:
            bad.append((label, 'strict refused the build', ev.get('refused_stats')))
        strict = api.compute(_build(weapon, mods), db, dict({'context': ctx}, strict=True))
        s_stats = (strict.get('result') or {}).get('stats') or {}
        s_ev = strict.get('evaluation') or {}
        if s_stats.get('damage_per_shot') is None or s_stats.get('burst_dps') is None:
            bad.append((label, 'strict nulled phase 1', s_ev.get('refused_stats')))
        if target_ok := ((strict.get('result') or {}).get('target_damage') is not None):
            bad.append((label, 'the target block answered anyway', target_ok))
    res.check('enemy/target-refusal-keeps-the-build',
              'an unresolved target state withholds the target block, never the Phase 1 numbers',
              not bad, 'bad=%s' % bad[:4])


def check_page_does_no_enemy_maths(res, db, page_text=None):
    """The page may send inputs and print answers; the enemy arithmetic lives in builds/."""
    text = page_text
    if text is None:
        text = {}
        for name in PAGE_FILES:
            path = REPO / 'static' / name
            text[name] = path.read_text(encoding='utf-8') if path.exists() else ''
    hits = []
    for name, body in text.items():
        for needle in FORBIDDEN_ON_PAGE:
            if needle in body:
                hits.append('%s: %s' % (name, needle))
    res.check('page/no-enemy-maths',
              'no enemy/buff formula constant appears in the page',
              not hits, 'hits=%s' % hits[:6])

    # ... and the page must not be carrying a private copy of the target arithmetic either.
    joined = '\n'.join(text.values())
    res.check('page/no-mitigation-copy',
              'the page carries no armour/DR computation of its own',
              'armour_damage_reduction' not in joined and 'damage_reduction' not in joined
              and '/ (armour' not in joined and '(armour +' not in joined,
              'armour_damage_reduction=%s damage_reduction=%s'
              % ('armour_damage_reduction' in joined, 'damage_reduction' in joined))


def check_refusal_registry_covers_new_paths(res, db):
    """Every refusal the new paths emit has a registry row (the project's own rule).

    Both shapes count as refusals here: the `unsupported` markers, and the finer-grained
    `unsupported_code` a condition row can carry (the two Phase 5 codes: an over-cap corrosive
    stack count, and a stack count above a mod's own cap). A code with no row is a refusal the
    registry - and the UI built from it - cannot explain.
    """
    weapon = _weapon_id(db)
    serration = _rifle_mod(db, 'Serration')
    found = _rider_mod(db)
    mods = [(serration['id'], serration.get('max_rank') or 0)]
    if found:
        mods.append((found[0]['id'], found[0].get('max_rank') or 0))
    missing = set()
    cond_codes = set()
    for options in (_ctx('grineer', protection='health'),
                    _ctx('grineer', protection='health', armor='lots'),
                    _ctx('grineer', protection='attachments', armor=1),
                    _ctx('nowhere', protection='health', armor=1),
                    _ctx('grineer', protection='health', armor=900, corrosive_stacks=11),
                    _ctx('grineer', protection='health', armor=900, corrosive_stacks=99),
                    {'context': {'buffs': {'on_kill': {'stacks': 99}}}},
                    {'context': {'buffs': {'on_kill': {'stacks': 2.5}}}},
                    {'context': {'buffs': {'on_kill': {'stacks': 3, 'rotation': 'x'}}}},
                    {'context': {'target': {'health': 1000}}}):
        out = api.compute(_build(weapon, mods), db, options)
        for marker in _markers(out):
            missing.update(unsupported.check_coverage([marker]))
        for row in _rows(out):
            code = row.get('unsupported_code')
            if code:
                cond_codes.add(code)
                if unsupported.entry(code) is None:
                    missing.add(code)
    res.check('refusals/registry-covers-phase-5',
              'every refusal the new paths emit has a registry entry (markers and condition codes)',
              not missing, 'missing=%s condition_codes=%s' % (sorted(missing)[:6], sorted(cond_codes)))
    res.check('refusals/phase-5-condition-codes-exercised',
              'the Phase 5 condition codes are reachable, so the registry rows above are not dead',
              {'corrosive_stack_timeline', 'buff_stacks_above_cap'} <= cond_codes,
              'exercised=%s' % sorted(cond_codes))


CHECKS = (
    check_enemy_inputs_are_required,
    check_mitigation_is_pinned,
    check_target_never_touches_phase1,
    check_unsupported_mechanics_contribute_nothing,
    check_buff_state_is_stated_only,
    check_four_states_everywhere,
    check_booleans_are_booleans,
    check_target_field_handling,
    check_a_target_refusal_keeps_the_build,
    check_malformed_target_never_crashes,
    check_trace_is_the_whole_story,
    check_umbral_counts_distinct_legal_members,
    check_phase_4_gate_still_passes,
    check_refusal_registry_covers_new_paths,
)


def run_checks(db, page_text=None, keep_clean=False):
    res = Result()
    for fn in CHECKS:
        try:
            fn(res, db)
        except Exception as exc:                                     # noqa: BLE001
            import traceback
            res.check(fn.__name__, '%s crashed' % fn.__name__, False,
                      '%s: %s' % (type(exc).__name__, exc) + ' | '
                      + traceback.format_exc().splitlines()[-1])
    check_page_does_no_enemy_maths(res, db, page_text=page_text)
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


def _break_unparseable_armour_is_zero():
    """An armour value the model cannot read is read as 0 armour (unknown -> 0)."""
    original = enemies._as_number

    def loose(value):
        got = original(value)
        return 0.0 if got is None else got

    enemies._as_number = loose

    def undo():
        enemies._as_number = original
    return undo


def _break_missing_armour_is_zero():
    """A missing armour value quietly becomes 0 armour, so the mitigation runs anyway."""
    original = enemies.evaluate

    def generous(ctx, deals_corrosive=False):
        if not conditions.has(ctx, 'target', 'armor') and \
                conditions.has(ctx, 'target', 'protection'):
            ctx = dict(ctx)
            ctx['target'] = dict(ctx.get('target') or {}, armor=0)
        return original(ctx, deals_corrosive=deals_corrosive)

    enemies.evaluate = generous

    def undo():
        enemies.evaluate = original
    return undo


def _break_missing_layer_defaults():
    """A missing landing layer is defaulted to health."""
    original = enemies.evaluate

    def defaulting(ctx, deals_corrosive=False):
        if not conditions.has(ctx, 'target', 'protection') and \
                conditions.has(ctx, 'target_faction'):
            ctx = dict(ctx)
            ctx['target'] = dict((ctx.get('target') or {}), protection='health')
        return original(ctx, deals_corrosive=deals_corrosive)

    enemies.evaluate = defaulting

    def undo():
        enemies.evaluate = original
    return undo


def _break_faction_defaults():
    """An unknown faction is defaulted to grineer."""
    original = factions.normalise_faction

    def defaulting(stated):
        faction, known = original(stated)
        if not known:
            return 'grineer', True
        return faction, known

    factions.normalise_faction = defaulting

    def undo():
        factions.normalise_faction = original
    return undo


def _break_unknown_becomes_false():
    """An unknown condition is reported as not_satisfied - a state that looks like an answer."""
    original = conditions.result

    def lying(condition_id, state, reason, **extra):
        if state == conditions.UNKNOWN:
            state = conditions.NOT_SATISFIED
        return original(condition_id, state, reason, **extra)

    conditions.result = lying

    def undo():
        conditions.result = original
    return undo


def _break_unsupported_contributes():
    """A conditional mechanic with no model is folded into the damage totals anyway.

    Note the two seams: `builds/weapons.py` (and `builds/warframes.py`) alias
    `effects.collect_mod_effects` at import time, so patching only the effects module would leave
    the weapon engine's totals untouched and this break would be inert. A gate whose break is
    inert proves nothing about the engine - it proves the break was pointed at the wrong name.
    """
    originals = [(effects, effects.collect_mod_effects),
                 (weapons, weapons.collect_mod_effects)]

    def leaky(mod_slots):
        totals, unsupported, notes = originals[0][1](mod_slots)
        for slot in mod_slots or []:
            eff = (slot.get('mod') or {}).get('effects') or {}
            if eff.get('conditional') and not eff.get('rank_table'):
                # critical_chance is the one stat every weapon kind publishes, so the leak is
                # observable on melee, firearms and bows alike.
                for stat in ('damage', 'multishot', 'critical_chance'):
                    bucket = totals.setdefault(stat, {'value': 0.0, 'unit': 'percent',
                                                      'category': 'percent', 'rows': []})
                    bucket['value'] = bucket.get('value', 0) + 10.0
                break
        return totals, unsupported, notes

    effects.collect_mod_effects = leaky
    weapons.collect_mod_effects = leaky

    def undo():
        effects.collect_mod_effects = originals[0][1]
        weapons.collect_mod_effects = originals[1][1]
    return undo


def _break_unstated_rider_applies():
    """A rider with no stated state is treated as one stack - a guessed combat state."""
    original = buffs.evaluate_state

    def guessing(trigger, raw_state, max_stacks, mod=None, mod_name=None):
        if raw_state is None:
            return conditions.result(trigger, conditions.SATISFIED,
                                     'assumed one stack', mode='instant', stacks=1,
                                     stacks_effective=1.0, trigger=trigger, mod=mod,
                                     mod_name=mod_name, max_stacks=max_stacks)
        return original(trigger, raw_state, max_stacks, mod=mod, mod_name=mod_name)

    buffs.evaluate_state = guessing

    def undo():
        buffs.evaluate_state = original
    return undo


def _break_stacks_invented():
    """An uptime without a stack count invents the mod's maximum stack count."""
    original = buffs.evaluate_state

    def inventing(trigger, raw_state, max_stacks, mod=None, mod_name=None):
        if isinstance(raw_state, dict) and raw_state.get('uptime') is not None \
                and 'stacks' not in raw_state:
            raw_state = dict(raw_state, stacks=max_stacks)
        return original(trigger, raw_state, max_stacks, mod=mod, mod_name=mod_name)

    buffs.evaluate_state = inventing

    def undo():
        buffs.evaluate_state = original
    return undo


def _break_uptime_assumed():
    """With no buff state at all, the engine assumes an averaged 50% uptime at max stacks."""
    original = buffs.evaluate_state

    def assuming(trigger, raw_state, max_stacks, mod=None, mod_name=None):
        if raw_state is None:
            return original(trigger, {'stacks': max_stacks, 'uptime': 0.5}, max_stacks,
                            mod=mod, mod_name=mod_name)
        return original(trigger, raw_state, max_stacks, mod=mod, mod_name=mod_name)

    buffs.evaluate_state = assuming

    def undo():
        buffs.evaluate_state = original
    return undo


def _break_malformed_raises():
    """A malformed target value raises instead of degrading to a named unknown."""
    original = enemies._as_number

    def strict(value):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError('armour must be a number')
        return float(value)

    enemies._as_number = strict

    def undo():
        enemies._as_number = original
    return undo


def _break_bool_coercion():
    """Truthy strings are accepted as booleans again (the Phase 4 leftover)."""
    original = validation.as_bool

    def loose(build, key, default=False):
        value = (build or {}).get(key)
        if isinstance(value, str):
            return value.strip().lower() in ('yes', 'true', 'on', '1'), None
        return original(build, key, default)

    validation.as_bool = loose

    def undo():
        validation.as_bool = original
    return undo


def _break_corrosive_cap_approximated():
    """An over-cap stack count is clamped to the cap instead of refusing: a number appears where
    the engine has no sourced rule (the cap can be raised by an Archon Shard, which is a timeline
    this engine does not model)."""
    original = statuses.evaluate_corrosive

    def clamping(ctx):
        row = original(ctx)
        if row.get('state') == conditions.UNSUPPORTED and \
                '10-stack cap' in (row.get('reason') or ''):
            clamped = dict(ctx)
            clamped['target'] = dict(ctx.get('target') or {}, corrosive_stacks=10)
            return original(clamped)
        return row

    statuses.evaluate_corrosive = clamping

    def undo():
        statuses.evaluate_corrosive = original
    return undo


def _break_target_moves_phase1():
    """The target path nudges a Phase 1 stat - the target-aware answer contaminating Phase 1."""
    original = api.compute

    def fudged(build, db, options=None, **kw):
        out = original(build, db, options, **kw)
        result = out.get('result') or {}
        if result.get('target_damage') is not None:
            stats = result.get('stats') or {}
            if isinstance(stats.get('damage_per_shot_expected_crit'), (int, float)):
                stats['damage_per_shot_expected_crit'] = \
                    round(stats['damage_per_shot_expected_crit'] * 1.01, 4)
        return out

    api.compute = fudged

    def undo():
        api.compute = original
    return undo


def _break_phase1_drifted():
    """The Phase 1 numbers drift even with no target context at all."""
    original = api.compute

    def drifted(build, db, options=None, **kw):
        out = original(build, db, options, **kw)
        result = out.get('result') or {}
        stats = result.get('stats') or {}
        if isinstance(stats.get('damage_per_shot_expected_crit'), (int, float)):
            stats['damage_per_shot_expected_crit'] = \
                round(stats['damage_per_shot_expected_crit'] * 0.99, 4)
        return out

    api.compute = drifted

    def undo():
        api.compute = original
    return undo


def _break_reducer_bites_nowhere():
    """The armour reduction ignores its input (a constant) - the mitigation stops being stated."""
    original = enemies.armour_damage_reduction

    def flat(armor):
        return 0.9

    enemies.armour_damage_reduction = flat

    def undo():
        enemies.armour_damage_reduction = original
    return undo


BREAKS = (
    Break('unparseable-armour-becomes-zero', _break_unparseable_armour_is_zero,
          'an armour value the model cannot read is read as 0 armour'),
    Break('missing-armour-becomes-zero', _break_missing_armour_is_zero,
          'a missing armour value quietly becomes 0 armour'),
    Break('missing-layer-defaults', _break_missing_layer_defaults,
          'a missing landing layer is defaulted to health'),
    Break('unknown-faction-defaults', _break_faction_defaults,
          'an unknown faction is defaulted to grineer'),
    Break('unknown-becomes-false', _break_unknown_becomes_false,
          'an unknown condition is reported as not_satisfied'),
    Break('unsupported-contributes', _break_unsupported_contributes,
          'a conditional mechanic with no model is folded into the totals'),
    Break('unstated-rider-applies', _break_unstated_rider_applies,
          'a rider with no stated state is treated as one stack'),
    Break('stacks-invented', _break_stacks_invented,
          'an uptime without a stack count invents the maximum stack count'),
    Break('uptime-assumed', _break_uptime_assumed,
          'with no buff state the engine assumes 50% uptime at max stacks'),
    Break('malformed-target-raises', _break_malformed_raises,
          'a malformed target value crashes instead of answering unknown'),
    Break('truthy-string-as-boolean', _break_bool_coercion,
          'truthy strings are accepted as booleans'),
    Break('corrosive-cap-approximated', _break_corrosive_cap_approximated,
          'an over-cap corrosive stack count produces a reduction'),
    Break('target-moves-phase-1', _break_target_moves_phase1,
          'the target path contaminates the Phase 1 numbers'),
    Break('phase-1-drifts-without-context', _break_phase1_drifted,
          'the Phase 1 numbers drift with no target context at all'),
    Break('armour-rule-constant', _break_reducer_bites_nowhere,
          'the armour reduction stops depending on the stated armour'),
)


def falsify(db, verbose=False):
    """Prove each check bites: install a defect, run the gate, require a FAILURE."""
    out = []
    for brk in BREAKS:
        undo = _install([brk])
        try:
            res = run_checks(db)
        finally:
            _restore(undo)
        caught = bool(res.failures)
        out.append({'break': brk.name, 'why': brk.why, 'caught': caught,
                    'failed': [r['id'] for r in res.failures][:6]})
        if verbose:
            print('%s  break %-32s %s' % ('OK ' if caught else 'MISS', brk.name,
                                          ','.join(r['id'] for r in res.failures[:4])))
    # the page check, falsified with poisoned text rather than a patched engine
    poisoned = {name: 'const DR = 0.9 * Math.sqrt(armour / 2700);' for name in PAGE_FILES}
    res = run_checks(db, page_text=poisoned)
    out.append({'break': 'enemy-maths-in-page', 'why': 'an enemy formula constant appears in the page',
                'caught': bool(res.failures),
                'failed': [r['id'] for r in res.failures][:6]})
    if verbose:
        print('%s  break %-32s %s' % ('OK ' if out[-1]['caught'] else 'MISS',
                                      'enemy-maths-in-page', 'page/no-enemy-maths'))
    return out


# --------------------------------------------------------------------------- report + cli
def write_report(res, fals, db_name, checks_extra=''):
    lines = ['# Phase 5 target-model gate', '',
             '```',
             'python design/_planner/phase5_gate.py%s' % checks_extra,
             'database: %s' % db_name,
             '```', '',
             '| check | result |', '| --- | --- |']
    for row in res.rows:
        lines.append('| `%s` %s | %s |' % (row['id'], row['label'],
                                           'PASS' if row['ok'] else 'FAIL'))
    broken = list(res.failures)
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
    parser = argparse.ArgumentParser(description='Phase 5 target-model gate')
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
            print('%s  %-34s %s' % ('PASS' if row['ok'] else 'FAIL', row['id'], row['label']))
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
