#!/usr/bin/env python3
"""The enemy / target model (Phase 5, milestone 5.1) and the target-aware damage path (5.2).

The model is **stated context, never derived**. A caller describes the target - its faction, which
layer the damage lands on, the armour value, the target states this engine models - and the engine
answers with the wiki's own deterministic chain:

    base damage -> build modifiers -> conditional modifiers -> target modifiers -> mitigation
    -> final supported damage result

Nothing here reads files or the network. Every rule carries its source, and every gap refuses.

The rules, each quoted from the WARFRAME Wiki (Damage 3.0, Update 36; oldids in `SOURCE_*`):

* Damage-type modifiers are factions (U36):
  "all Grineer are now exclusively vulnerable to Impact and Corrosive at all times, regardless of
   the presence of armor or shields, and no longer have any resistances."
  Vulnerable + = x1.5, Resistant - = x0.5.               (builds/factions.py holds the table)

* Unarmoured enemies (or True damage):
      Inflicted Damage = Starting Damage x (1 + Health-type Modifier)
  where the health-type modifier is the faction's modifier for that damage type.

* Armoured enemies:
      DM = 1 - 0.9 x sqrt(AR / 2700)                       (Net Armor <= 2700)
      DM = AR / (AR + 300)                                 (Net Armor > 2700, exceptional)
  "AR is the target's armor after all reductions from debuffs (e.g. Corrosive Projection, Corrosive
   status effects, and Terrify)." Shields are never mitigated by armour:
  "In the case of enemies who have both shields and armor, damage to shields is not mitigated by
   armor." Each damage type keeps a minimum of 1 damage when armour reduces it:
  "When damage is reduced from armor, each damage type has a minimum damage of 1."

* Overguard: "It is neutral to all damage types except for a 50% vulnerability from Void damage" and
  "Overguard is not affected by Damage Reduction from armor or abilities".

* Per-type damage composes multiplicatively with the armour factor:
  "Total Inflicted Damage = SD1 x DM1 + ... + SDN x DMN". The faction damage-type modifier and the
  armour factor are independent sources of modification (Damage Type Modifier: "Damage type
  modifiers are independent of sources of Damage Reduction").

Deliberately NOT here: enemy health/shield pools (no supported calculation consumes them), headshot
/ weak-point multipliers, shield regeneration, Magnetic's shield amplification, status procs other
than the ones `builds/statuses.py` owns, level scaling (the caller states the current net armour),
enemy damage-over-time, and quotes/crit compounds beyond the ones the weapon engine already owns.
Those are refusals, not omissions.

Sources (retrieved 2026-09-30):
    https://wiki.warframe.com/w/Damage/Calculation          oldid 2804415
    https://wiki.warframe.com/w/Armor                      oldid 2814011
    https://wiki.warframe.com/w/Overguard                  oldid 2808615
    https://wiki.warframe.com/w/Damage/Overview_Table      oldid 2792179
    https://wiki.warframe.com/w/Damage_Type_Modifier       oldid 2749666  (the independence
                                                           sentence quoted above)
"""
import math

from . import conditions, factions, statuses, trace as trace_mod

SOURCE_CALC = ('https://wiki.warframe.com/w/Damage/Calculation '
               '(oldid 2804415, retrieved 2026-09-30)')
SOURCE_ARMOR = 'https://wiki.warframe.com/w/Armor (oldid 2814011, retrieved 2026-09-30)'
SOURCE_OVERGUARD = ('https://wiki.warframe.com/w/Overguard (oldid 2808615, retrieved 2026-09-30)')

# Which layer of the target the damage lands on (the Phase 4 viral vocabulary, reused here because
# it is the same fact: what is taking the damage).
LAYERS = ('health', 'armor', 'shields', 'overguard')
# Layers that armour mitigation applies to. `armor` means "health protected by armour" - the wiki's
# own "yellow health": the damage lands on health and the armour reduces it.
ARMORED_LAYERS = ('health', 'armor')
# Damage types outside the faction table are neutral. `true` ignores armour (the wiki's own rule);
# cinematic damage (Slash bleeds) also ignores armour, and neither appears in a weapon's base
# composition, so the behaviour is stated rather than silently implied.
ARMOR_BYPASSING = ('true', 'cinematic')
MAX_STANDARD_ARMOR = 2700.0


def armour_damage_reduction(armor):
    """The enemy damage reduction from armour, or None for a value the model cannot express.

    Net Armor <= 2700  ->  DR = 0.9 x sqrt(armor / 2700)
    Net Armor >  2700  ->  DR = armor / (armor + 300)        (the wiki's exceptional branch)
    """
    if isinstance(armor, bool) or not isinstance(armor, (int, float)):
        return None
    value = float(armor)
    if not math.isfinite(value) or value < 0:
        return None
    if value == 0.0:
        return 0.0
    if value <= MAX_STANDARD_ARMOR:
        return 0.9 * math.sqrt(value / MAX_STANDARD_ARMOR)
    return value / (value + 300.0)


def armour_multiplier(armor):
    """The factor armour applies to incoming damage (1 - DR), or None for an unusable value."""
    dr = armour_damage_reduction(armor)
    if dr is None:
        return None
    return 1.0 - dr


def _as_number(value):
    """A stated numeric field -> float, or None. Never coerces a string or a bool.

    A JSON integer can be arbitrarily large (`json.loads` keeps every digit), so the conversion
    itself can raise - an armour value of 10**400 is not a number this model can express, and
    saying so beats an OverflowError out of the API.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except (OverflowError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


# ------------------------------------------------------------------ the evaluation (5.1)
def evaluate(ctx, deals_corrosive=False):
    """The stated target -> (condition row for 'target_damage', plan | None).

    The plan is the resolved, validated target; it exists only when the row is `satisfied`. Every
    branch ends in one of the four Phase 4 states, and a missing input is `unknown` with the input
    named - never a default target, never a zeroed armour value.
    """
    stated_faction = conditions.get(ctx, 'target_faction')
    if not conditions.has(ctx, 'target_faction'):
        return conditions.result(
            'target_damage', conditions.UNKNOWN,
            'no target faction was supplied: the damage-type modifiers cannot be resolved',
            reason_code='condition_unknown', missing=['target_faction'],
            source=SOURCE_CALC), None
    faction, known = factions.normalise_faction(stated_faction)
    if not known:
        return conditions.result(
            'target_damage', conditions.UNSUPPORTED,
            'the stated target faction %r is not in the Damage 3.0 faction vocabulary, so no '
            'damage-type modifiers exist for it' % (stated_faction,),
            reason_code='mechanic_unsupported', inputs={'target_faction': stated_faction},
            source=SOURCE_CALC), None

    if not conditions.has(ctx, 'target', 'protection'):
        return conditions.result(
            'target_damage', conditions.UNKNOWN,
            'the target state does not say which layer the damage lands on (health / armour / '
            'shields / overguard), and this engine will not pick one',
            reason_code='condition_unknown', missing=['target.protection'],
            source=SOURCE_CALC), None
    layer = conditions.get(ctx, 'target', 'protection')
    if not isinstance(layer, str) or layer.strip().lower() not in LAYERS:
        return conditions.result(
            'target_damage', conditions.UNSUPPORTED,
            'target.protection %r is not one of %s' % (layer, ', '.join(LAYERS)),
            reason_code='mechanic_unsupported',
            inputs={'protection': layer if isinstance(layer, str) else repr(layer)},
            source=SOURCE_CALC), None
    layer = layer.strip().lower()

    # --- armour: required for a health landing, irrelevant (but named) elsewhere -----------------
    armour = None
    if conditions.has(ctx, 'target', 'armor'):
        armour = _as_number(conditions.get(ctx, 'target', 'armor'))
        if armour is None or armour < 0:
            # A negative value is not "no armour": it is a state the model cannot express, and
            # reading it as an unarmoured target would be exactly the silent coercion this phase
            # exists to stop.
            return conditions.result(
                'target_damage', conditions.UNKNOWN,
                'target.armor %r is not an armour value this engine will interpret'
                % (conditions.get(ctx, 'target', 'armor'),),
                reason_code='condition_unknown',
                inputs={'armor': conditions.get(ctx, 'target', 'armor')},
                missing=['a non-negative numeric target.armor'],
                source=SOURCE_ARMOR), None
    if layer in ARMORED_LAYERS and armour is None:
        return conditions.result(
            'target_damage', conditions.UNKNOWN,
            'the damage lands on %s, so the armour value is needed to compute the mitigation, '
            'and no armour was stated' % layer,
            reason_code='condition_unknown', missing=['target.armor'],
            source=SOURCE_ARMOR), None

    # --- the target-state mechanic the armour stage consumes (5.5) -------------------------------
    corrosive_row = None
    corrosive_mult = 1.0
    if deals_corrosive or conditions.has(ctx, 'target', 'corrosive_stacks'):
        corrosive_row = statuses.evaluate_corrosive(ctx)
        if corrosive_row['state'] in (conditions.UNKNOWN, conditions.UNSUPPORTED):
            extra = {}
            if corrosive_row.get('unsupported_code'):
                # the finer code travels with the refusal, so a consumer can tell an over-cap
                # stack timeline from a mechanic with no model at all
                extra['unsupported_code'] = corrosive_row['unsupported_code']
            if corrosive_row.get('inputs'):
                extra['inputs'] = dict(corrosive_row['inputs'])
            return conditions.result(
                'target_damage', corrosive_row['state'],
                'the target armour cannot be resolved: %s' % corrosive_row['reason'],
                reason_code=corrosive_row['reason_code'],
                missing=list(corrosive_row.get('missing') or []),
                source=SOURCE_CALC, **extra), None
        corrosive_mult = float(corrosive_row.get('armor_multiplier') or 1.0)

    plan = {
        'faction': faction,
        'faction_label': factions.FACTION_LABEL.get(faction, faction),
        'protection': layer,
        'corrosive_row': corrosive_row,
        'corrosive_multiplier': corrosive_mult,
        'armor': None,
    }
    if armour is not None:
        effective = armour * corrosive_mult
        plan['armor'] = {
            'stated': armour,
            'corrosive_multiplier': corrosive_mult,
            'effective': effective,
            'reduction': armour_damage_reduction(effective),
            'multiplier': armour_multiplier(effective),
            'applies': layer in ARMORED_LAYERS and effective > 0.0,
        }
    reason = 'the target is %s and the damage lands on %s' % (plan['faction_label'], layer)
    if plan['armor'] and plan['armor']['applies']:
        reason += ('; armour %g (after modelled reductions) reduces each damage type by %s%%'
                   % (plan['armor']['effective'],
                      round(plan['armor']['reduction'] * 100.0, 4)))
    return conditions.result(
        'target_damage', conditions.SATISFIED, reason,
        inputs={'target_faction': stated_faction, 'protection': layer,
                'armor': armour},
        source=SOURCE_CALC, faction=faction,
        armor=(plan['armor'] or {}).get('effective')), plan


# ------------------------------------------------------------------ the damage path (5.2)
def calculate(per_projectile, plan, faction_multiplier=1.0):
    """Apply the stated target's rules to a per-projectile damage composition.

    `per_projectile` is the weapon engine's modded composition (builds/weapons.calculate), one
    value per damage type per projectile. `plan` comes from `evaluate`. Returns the per-type
    result, its modifiers, and traced stages. Pure arithmetic - nothing here guesses a value the
    caller did not state.
    """
    faction = plan['faction']
    layer = plan['protection']
    armor = plan['armor']
    armor_applies = bool(armor and armor['applies'])
    armor_mult = float(armor['multiplier']) if armor_applies else 1.0
    fm = float(faction_multiplier or 1.0)

    per_type, modifiers, clamped = {}, {}, []
    for dtype in sorted(per_projectile):
        sd = float(per_projectile[dtype])
        if layer == 'overguard':
            # Neutral to every damage type except Void (x1.5); no armour mitigation.
            type_mod = 1.5 if dtype == 'void' else 1.0
            am = 1.0
        else:
            mod, _why = factions.modifier(faction, dtype)
            type_mod = 1.0 + float(mod or 0.0)
            if dtype in ARMOR_BYPASSING:
                am = 1.0                            # True / Cinematic damage ignore armour (wiki)
            else:
                am = armor_mult
        value = sd * type_mod * am
        did_clamp = False
        if am < 1.0 and sd > 0 and value < 1.0:
            value = 1.0                             # "a minimum damage of 1" per reduced type
            did_clamp = True
            clamped.append(dtype)
        value = value * fm
        per_type[dtype] = value
        modifiers[dtype] = {'type_modifier': type_mod, 'armor_multiplier': am,
                            'faction_multiplier': fm, 'combined': type_mod * am * fm,
                            'min_damage': did_clamp}
    total = sum(per_type.values())

    traces = _traces(per_projectile, per_type, modifiers, plan, fm, layer)
    notes = []
    if armor and armor['stated'] and layer in ('shields', 'overguard'):
        notes.append('armour does not mitigate damage to %s (wiki), so the stated armour %g was '
                     'not applied' % (layer, armor['stated']))
    if layer == 'overguard':
        notes.append('Overguard is neutral to every damage type except Void (x1.5) and is not '
                     'reduced by armour (wiki)')
    if clamped:
        notes.append('the minimum-damage rule kept %s at 1 per projectile (wiki)'
                     % ', '.join(sorted(clamped)))
    if fm != 1.0:
        notes.append('the separate faction multiplier x%.4g is applied to every type (wiki; not '
                     'part of the arsenal total)' % fm)
    return {
        'faction': faction, 'faction_label': plan['faction_label'],
        'protection': layer,
        'armor': ({k: v for k, v in armor.items() if k != 'multiplier'} if armor else None),
        # published figures are trimmed to the engine's display precision (builds/trace._num), the
        # same as every Phase 1 stat; the arithmetic above ran on the raw values.
        'per_projectile': {k: trace_mod._num(v) for k, v in per_type.items()},
        'per_projectile_total': trace_mod._num(total),
        'modifiers': modifiers,
        'min_damage_types': sorted(clamped),
        'faction_multiplier': fm,
        'source': SOURCE_CALC,
        'traces': traces,
        'notes': notes,
    }


def _modifier_row(source, category, value, unit, note=None, **extra):
    row = {'source': source, 'category': category, 'value': value, 'unit': unit}
    if note:
        row['note'] = note
    row.update(extra)
    return row


def _traces(per_projectile, per_type, modifiers, plan, fm, layer):
    """Per-type traces and the total: base -> target modifiers -> mitigation -> final."""
    from . import trace as trace_mod
    traces = {}
    armor = plan['armor']
    for dtype in sorted(per_projectile):
        sd = float(per_projectile[dtype])
        mod = modifiers[dtype]
        label = '%s damage vs the stated target (per projectile)' % dtype.title()
        t = trace_mod.trace('target_damage.' + dtype, sd, 'flat', label)
        if mod['type_modifier'] != 1.0:
            pct = round((mod['type_modifier'] - 1.0) * 100.0, 4)
            t['modifiers'].append(_modifier_row(
                'Target faction (%s)' % plan['faction_label'], 'target', pct, 'percent',
                note='%s is a %s %s (x%s); Damage 3.0 faction table'
                     % (dtype.title(), plan['faction_label'],
                        'vulnerability' if pct > 0 else 'resistance', mod['type_modifier']),
                damage_type=dtype,
                state='satisfied', source_url=factions.SOURCE_TABLE))
        if layer == 'overguard' and dtype == 'void':
            t['modifiers'].append(_modifier_row(
                'Overguard (Void)', 'target', 50, 'percent',
                note='Overguard is neutral to every damage type except a x1.5 Void vulnerability',
                damage_type=dtype, state='satisfied', source_url=SOURCE_OVERGUARD))
        if plan['corrosive_row'] and mod['armor_multiplier'] < 1.0:
            row = statuses.corrosive_trace_row(armor['stated'], armor['effective'],
                                               plan['corrosive_row'])
            if row:
                t['modifiers'].append(row)
        if mod['armor_multiplier'] < 1.0:
            t['modifiers'].append(_modifier_row(
                'Armor %g' % armor['effective'], 'mitigation', mod['armor_multiplier'], 'ratio',
                note='enemy DR = 90%% x sqrt(net armour / 2700) = %s%% (wiki)'
                     % round(armor['reduction'] * 100.0, 4),
                damage_type=dtype, state='satisfied', source_url=SOURCE_ARMOR))
        if mod['min_damage']:
            t['modifiers'].append(_modifier_row(
                'Minimum damage', 'mitigation', 1.0, 'flat',
                note='each damage type has a minimum of 1 damage when armour reduces it (wiki)',
                damage_type=dtype))
        if fm != 1.0:
            t['modifiers'].append(_modifier_row(
                'Faction damage', 'faction', fm, 'ratio',
                note='separate multiplier, applied to every type (wiki)', damage_type=dtype))
        trace_mod.finish(t, per_type[dtype])
        traces['target_damage.' + dtype] = t

    t_total = trace_mod.trace('target_damage', sum(float(v) for v in per_projectile.values()),
                              'flat', 'Damage vs the stated target (per projectile)')
    for dtype in sorted(per_projectile):
        sd = float(per_projectile[dtype])
        delta = per_type[dtype] - sd
        t_total['modifiers'].append(_modifier_row(
            dtype, 'target', delta, 'flat',
            note='%s -> %s (x%s combined: type x%s, armour x%s)'
                 % (round(sd, 6), round(per_type[dtype], 6),
                    round(modifiers[dtype]['combined'], 6),
                    round(modifiers[dtype]['type_modifier'], 4),
                    round(modifiers[dtype]['armor_multiplier'], 4)),
            damage_type=dtype))
    trace_mod.finish(t_total, sum(per_type.values()))
    trace_mod.note(t_total, 'source: %s' % SOURCE_CALC)
    trace_mod.note(t_total, 'armour source: %s' % SOURCE_ARMOR)
    traces['target_damage'] = t_total
    return traces


# ------------------------------------------------------------------ selftest
def _plan(**target):
    ctx = conditions.normalise_context({'target_faction': target.pop('faction', 'grineer'),
                                        'target': target})
    row, plan = evaluate(ctx, deals_corrosive=target.pop('deals_corrosive', False))
    return row, plan


def selftest():
    failures, counter = [], [0]

    def check(label, ok, detail=''):
        counter[0] += 1
        print('%s  %s%s' % ('PASS' if ok else 'FAIL', label, '' if ok else ' -- %s' % detail))
        if not ok:
            failures.append(label)

    def near(a, b, tol=1e-9):
        return a is not None and abs(float(a) - float(b)) <= tol

    # --- the armour formula, against the wiki's own branch points
    check('AR 0 -> no reduction', armour_damage_reduction(0) == 0.0)
    check('AR 300 -> DR 0.9 x sqrt(300/2700) = 0.3 (hand arithmetic)',
          near(armour_damage_reduction(300), 0.9 * (300 / 2700) ** 0.5)
          and near(armour_damage_reduction(300), 0.3, 1e-12))
    check('AR 675 -> DR 0.45 (sqrt(0.25) = 0.5)', near(armour_damage_reduction(675), 0.45))
    check('AR 2700 -> DR 0.9 (the cap of the square-root branch)',
          near(armour_damage_reduction(2700), 0.9))
    check('AR 5700 -> the exceptional branch: 5700/(5700+300) = 0.95',
          near(armour_damage_reduction(5700), 5700 / 6000.0))
    check('armour values that are not numbers refuse',
          armour_damage_reduction('300') is None and armour_damage_reduction(True) is None
          and armour_damage_reduction(-5) is None and armour_damage_reduction(float('nan')) is None)

    # --- the evaluation: satisfied / unknown / unsupported
    row, plan = _plan(faction='grineer', protection='health', armor=300, corrosive_stacks=0)
    check('a fully stated target is satisfied', row['state'] == 'satisfied' and plan is not None,
          str(row.get('reason')))
    check('the plan carries the resolved armour', plan['armor']['effective'] == 300.0
          and near(plan['armor']['multiplier'], 0.7))
    row_missing, plan_missing = _plan(faction='grineer', protection='health', corrosive_stacks=0)
    check('no armour on a health landing -> unknown (never 0 armour)',
          row_missing['state'] == 'unknown' and plan_missing is None
          and row_missing['missing'] == ['target.armor'], str(row_missing))
    row_layer, _ = _plan(faction='grineer', armor=300, corrosive_stacks=0)
    check('no protection -> unknown (never a default layer)',
          row_layer['state'] == 'unknown' and row_layer['missing'] == ['target.protection'],
          str(row_layer))
    row_faction, _ = _plan(faction='', protection='health', armor=300)
    check('no faction -> unknown', row_faction['state'] == 'unknown'
          and row_faction['missing'] == ['target_faction'])
    row_bad_faction, _ = _plan(faction='wally', protection='health', armor=300,
                               corrosive_stacks=0)
    check('a faction outside the vocabulary -> unsupported', row_bad_faction['state'] == 'unsupported'
          and row_bad_faction['reason_code'] == 'mechanic_unsupported')
    row_bad_armor, _ = _plan(faction='grineer', protection='health', armor='300',
                             corrosive_stacks=0)
    check('a string armour value -> unknown, never coerced', row_bad_armor['state'] == 'unknown',
          str(row_bad_armor))
    row_bad_layer, _ = _plan(faction='grineer', protection='hull', armor=300)
    check('an unknown layer word -> unsupported', row_bad_layer['state'] == 'unsupported')
    row_cor, _ = _plan(faction='grineer', protection='health', armor=300)
    check('a health landing with the corrosive state unstated and no corrosive damage -> satisfied',
          row_cor['state'] == 'satisfied')
    row_cor2, _ = _plan(faction='grineer', protection='health', armor=300, deals_corrosive=True)
    check('the same build dealing corrosive damage -> unknown (state it, even as 0)',
          row_cor2['state'] == 'unknown'
          and row_cor2['missing'] == ['target.corrosive_stacks'], str(row_cor2))
    row_shield, plan_shield = _plan(faction='corpus', protection='shields')
    check('shields need no armour value', row_shield['state'] == 'satisfied'
          and plan_shield['armor'] is None)

    # --- the damage path, hand-checked against the wiki's arithmetic
    # Braton Prime + Serration R10: impact 4.6375, puncture 32.4625, slash 55.65 (Phase 1 values).
    comp = {'impact': 4.6375, 'puncture': 32.4625, 'slash': 55.65}
    row, plan = _plan(faction='grineer', protection='health', armor=300, corrosive_stacks=0)
    out = calculate(comp, plan)
    check('impact: x1.5 Grineer vulnerability, x0.7 armour = 4.869375 (published at 4dp)',
          near(out['per_projectile']['impact'], trace_mod._num(4.6375 * 1.5 * 0.7)))
    check('puncture is neutral vs Grineer: x0.7 armour = 22.72375 (published at 4dp)',
          near(out['per_projectile']['puncture'], trace_mod._num(32.4625 * 0.7)))
    check('the total is the sum of the mitigated types (66.548125, published at 4dp)',
          near(out['per_projectile_total'],
               trace_mod._num(4.6375 * 1.5 * 0.7 + 32.4625 * 0.7 + 55.65 * 0.7)))
    row, plan = _plan(faction='grineer', protection='health', armor=300, corrosive_stacks=2)
    out2 = calculate(comp, plan)
    eff = 300 * (1 - 0.32)
    check('2 corrosive stacks: armour 204, DR = 0.9 x sqrt(204/2700) (hand arithmetic)',
          near(plan['armor']['effective'], eff)
          and near(plan['armor']['multiplier'], 1 - 0.9 * (eff / 2700) ** 0.5))
    check('the corrosive multiplier reaches the total',
          near(out2['per_projectile_total'],
               trace_mod._num((4.6375 * 1.5 + 32.4625 + 55.65)
                              * (1 - 0.9 * (eff / 2700) ** 0.5))))
    row, plan = _plan(faction='grineer', protection='shields', armor=300, corrosive_stacks=0)
    out3 = calculate(comp, plan)
    check('shields: no armour mitigation (impact still x1.5 for Grineer)',
          near(out3['per_projectile_total'], trace_mod._num(4.6375 * 1.5 + 32.4625 + 55.65)))
    row, plan = _plan(faction='grineer', protection='overguard')
    out4 = calculate(comp, plan)
    check('overguard: neutral for physical, armour irrelevant',
          near(out4['per_projectile_total'], 4.6375 + 32.4625 + 55.65))
    row, plan = _plan(faction='zariman', protection='health', armor=0, corrosive_stacks=0)
    out5 = calculate({'void': 10.0, 'impact': 10.0}, plan)
    check('unarmoured Zariman: void x1.5', near(out5['per_projectile_total'], 15.0 + 10.0))
    row, plan = _plan(faction='grineer', protection='overguard')
    out6 = calculate({'void': 10.0, 'impact': 10.0}, plan)
    check('void vs overguard: x1.5 on the Void share only',
          near(out6['per_projectile_total'], 15.0 + 10.0))

    # the faction multiplier is a separate multiplier on top of everything
    row, plan = _plan(faction='kuva_grineer', protection='health', armor=300, corrosive_stacks=0)
    out7 = calculate(comp, plan, faction_multiplier=1.3)
    check('a Bane multiplier applies to every type, after mitigation',
          near(out7['per_projectile_total'], out['per_projectile_total'] * 1.3, 1e-3))

    # the minimum-damage rule
    row, plan = _plan(faction='grineer', protection='health', armor=2700, corrosive_stacks=0)
    out8 = calculate({'impact': 0.04}, plan)
    check('a type reduced below 1 is kept at 1 (wiki minimum)', near(out8['per_projectile']['impact'],
                                                                     1.0)
          and out8['min_damage_types'] == ['impact'])

    # traces (the trace layer trims to 4 decimals for display - compare at that precision)
    check('every type has a trace and the total is traced', 'target_damage' in out['traces']
          and 'target_damage.impact' in out['traces']
          and near(out['traces']['target_damage']['final'],
                   round(out['per_projectile_total'], 4), 1e-6))
    check('traces name the sources in their notes', any(
        'wiki' in (m.get('note') or '') for m in out['traces']['target_damage.impact']['modifiers']))

    # malformed structural input never raises
    for junk in ('grineer', 42, [1], {'target': 'x'}, {'target': {'protection': []}},
                 {'target': {'armor': {}}}, {'target': {'armor': 1e400}}, {'target': []}):
        try:
            ctx = conditions.normalise_context(junk if isinstance(junk, dict) else {})
            evaluate(ctx)
        except Exception as exc:                                     # noqa: BLE001
            check('a malformed context never raises (%r: %s)' % (junk, exc), False)
    check('malformed contexts never raise', True)

    print('\nenemies selftest %s (%d checks, %d failed) - nothing written'
          % ('OK' if not failures else 'FAILED', counter[0], len(failures)))
    return 0 if not failures else 1


if __name__ == '__main__':
    import sys
    sys.exit(selftest())
