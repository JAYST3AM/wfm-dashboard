#!/usr/bin/env python3
"""Weapon stat engine: what a modded weapon actually deals.

Every formula here is quoted from the WARFRAME Wiki (Damage, Damage/Calculation,
Calculating Bonuses, Critical Hit, Status Effect, Multishot, Reload) and implemented
exactly as documented - no "close enough" numbers:

  damage order      base damage bonuses add together and apply first; then elemental and
                    physical bonuses are calculated FROM THE MODDED BASE damage; then
                    faction bonuses apply to every type (not shown in the arsenal).
  arsenal total     Base x [1 + Elemental + sum(dist_t x phys_t)] x (1 + Damage Bonuses)
                    x multishot, where dist_t is the weapon's own distribution.
  physical mods     apply only to base damage of the same type; a weapon with no damage
                    of that type gets nothing from the mod (Karak/Fanged Fusillade).
  elemental mods    apply to ALL damage the weapon deals: amount = modded base x %.
  modded stats      Stat x (1 + bonuses) - except reload: Time / (1 + speed bonus).
  critical          multiplier = base x (1 + crit damage bonuses); above 100% chance the
                    hit gains tiers: tier multiplier = 1 + tier x (multi - 1), with the
                    fractional part a chance of one more tier (expected value exposed,
                    never a boolean).
  status            per-projectile chance (shotguns included - post-Update 27.2 the
                    arsenal value IS the per-pellet value); expected procs per shot =
                    multishot x status, which is the wiki's own formula and lets >100%
                    status mean more than one proc.
  multishot         projectiles = base x (1 + bonuses); the fraction is a chance of one
                    more projectile, so both the deterministic and expected forms are
                    exposed.
  quantization      live damage rounds each type to 1/32nd of the (modded) base damage:
                    quantized(x) = sign(x) * floor(|x| * 32 + 0.5) / 32 * base. Exposed
                    on request because the arsenal does not show it, but the game does it.
  sustain           burst DPS = average shot x effective fire rate; sustained multiplies
                    by the shooting share of a magazine cycle. Only trigger types whose
                    effective rate the wiki documents as the modded fire rate are
                    reported as production values; Charge/Burst/Continuous are returned
                    with supported=false.

Nothing here reads files, the market or the network. Sim input:
`calculate(equipment_row, mod_slots, options)` where each mod slot carries the ingested
mod row (with its parsed effect tables) and the rank it is equipped at.
"""
from . import capacity as capacity_mod
from . import conditions
from . import effects as effects_mod
from . import elements, schema, statuses, trace as trace_mod
from . import unsupported as unsupported_mod

# Trigger types whose effective fire rate is simply the modded fire rate (wiki table).
SUPPORTED_TRIGGERS = ('auto', 'semi', 'held', 'duplex')


# ---------------------------------------------------------------- effect collection
# The collection pass lives in effects.py (shared with the Warframe engine).
collect_mod_effects = effects_mod.collect_mod_effects
_marker = effects_mod.unsupported_marker


def _pct(effect_totals, stat):
    """The summed percentage of a stat (0.0 when absent)."""
    return effects_mod.summed_percent(effect_totals, stat)


def _rows(effect_totals, stat):
    return effects_mod.effect_rows_of(effect_totals, stat)


# ---------------------------------------------------------------- the engine
def calculate(equipment, mod_slots=None, options=None):
    """A modded weapon -> every headline stat, with traces and refusals.

    equipment: ingested equipment row - uses id, name, kind, damage{}, damage_total,
               crit_chance, crit_multiplier, status_chance, fire_rate, multishot,
               magazine, reload, trigger, range, combo_duration, and the flags that mark
               mechanics we refuse (incarnon forms, innate secondary elements).
    mod_slots: [{'kind', 'index', 'polarity', 'rank', 'mod': ingested mod row}]
    options:   {'faction': None|'grineer'|..., 'quantize': False,
                'trigger_override': None}
    """
    opts = {'faction': None, 'quantize': False, 'trigger_override': None, 'context': None,
            'strict': False, 'hypothetical': False}
    opts.update(options if isinstance(options, dict) else {})
    equip = _normalise_equipment(equipment)
    kind = equip.get('kind') or schema.EQUIP_PRIMARY
    totals, unsupported, notes = collect_mod_effects(mod_slots)
    traces, stats = {}, {}

    # --- the evaluation context and the conditions it resolves (Phase 4, 4.3 + 4.5) --------
    # `options.faction` predates the context and still works: it IS the target faction. A context
    # that names one wins, because it is the newer, more explicit statement.
    ctx = conditions.normalise_context(opts.get('context'))
    if ctx['target_faction'] is None and opts.get('faction'):
        ctx['target_faction'] = str(opts['faction']).strip().lower()
    mode = ('hypothetical' if opts.get('hypothetical')
            else 'strict' if opts.get('strict') else 'stated_inputs')
    condition_rows = []

    def condition_applies(row):
        """Does this condition's contribution go into the number?

        `satisfied` yes; `not_satisfied` no (a reported zero); `unknown`/`unsupported` no -
        unless the caller explicitly asked for a hypothetical evaluation, in which case the
        contribution is shown as-if satisfied and the row keeps saying `hypothetical`.
        """
        if row.get('applied'):
            return True
        return bool(row.get('hypothetical')) and row.get('state') == conditions.UNKNOWN

    faction_stats = sorted(s for s in totals if s.startswith('faction_'))
    faction_rows = {}
    for stat in faction_stats:
        want = stat[len('faction_'):]
        row = conditions.evaluate('target_faction', ctx, faction=want)
        if mode == 'hypothetical' and row['state'] == conditions.UNKNOWN:
            row = dict(row, hypothetical=True)
        condition_rows.append(row)
        faction_rows[stat] = row


    base_dist = {t: float(v) for t, v in (equip.get('damage') or {}).items() if v}
    base_total = float(equip.get('damage_total') or sum(base_dist.values()) or 0.0)
    innate_elements = {t: v for t, v in base_dist.items()
                       if t in schema.ELEMENTAL_TYPES and v}
    innate_secondary = sorted(t for t in innate_elements
                              if t in schema.SECONDARY_ELEMENTS)
    if len(innate_elements) - len(innate_secondary) > 1:
        unsupported.append(_marker(
            'multiple_innate_elements',
            'weapon carries %d innate primary elements; only Kuva/Tenet weapons do, and '
            'their HCET tie-break is not modelled'
            % (len(innate_elements) - len(innate_secondary)), equipment=equip.get('id')))
    for element in innate_secondary:
        unsupported.append(_marker(
            'innate_secondary_element',
            'weapon has an innate %s damage type; its interaction with %s mods is a '
            'documented special case Phase 1 does not model'
            % (element, element), equipment=equip.get('id')))

    # --- the first-shot condition (4.6: the second mechanic) ------------------
    # 'damage on first shot in magazine' is a base-damage bonus that only applies to one shot, so
    # it was silently ignored before Phase 4. It is now a condition: applied only when the attack
    # context says this is the first shot, reported either way.
    first_shot_pct = 0.0
    first_shot_row = None
    if totals.get('damage_on_first_shot'):
        row = conditions.evaluate('first_shot', ctx)
        if mode == 'hypothetical' and row['state'] == conditions.UNKNOWN:
            row = dict(row, hypothetical=True)
        first_shot_row = row
        condition_rows.append(row)
        if condition_applies(row):
            first_shot_pct = _pct(totals, 'damage_on_first_shot')

    # --- base damage multiplier ------------------------------------------------
    damage_bonus = 1.0 + (_pct(totals, 'damage') + first_shot_pct) / 100.0
    t_base = trace_mod.trace('damage_multiplier', 1.0, 'ratio', 'Base damage multiplier')
    for row in _rows(totals, 'damage'):
        trace_mod.add(t_base, trace_mod.modifier(row['mod_name'], 'base',
                                                 row['value'], mod=row['mod'], rank=row['rank']))
    for row in _rows(totals, 'damage_on_first_shot'):
        trace_mod.add(t_base, trace_mod.modifier(
            row['mod_name'], 'base', row['value'], mod=row['mod'], rank=row['rank'],
            condition='first_shot', state=(first_shot_row or {}).get('state')))
    trace_mod.finish(t_base, damage_bonus)
    if totals.get('damage_on_first_shot') and first_shot_row:
        trace_mod.note(t_base, 'first-shot bonus: %s (%s)'
                       % (first_shot_row['state'], first_shot_row['reason']))
    traces['damage_multiplier'] = t_base
    modded_base = base_total * damage_bonus
    stats['base_damage'] = trace_mod._num(base_total)
    stats['modded_base_damage'] = trace_mod._num(modded_base)
    # The headline number a build guide quotes: base damage with the damage mods applied.
    t_dmg = trace_mod.trace('damage', base_total, 'flat', 'Base damage (modded)')
    for row in _rows(totals, 'damage'):
        trace_mod.add(t_dmg, trace_mod.modifier(row['mod_name'], 'base', row['value'],
                                                mod=row['mod'], rank=row['rank']))
    trace_mod.finish(t_dmg, modded_base)
    if not totals.get('damage'):
        trace_mod.note(t_dmg, 'no damage mods installed: the weapon deals its base damage')
    traces['damage'] = t_dmg

    # --- physical damage --------------------------------------------------------
    physical, t_phys = {}, {}
    for phys in schema.PHYSICAL_TYPES:
        base_val = float(base_dist.get(phys) or 0.0)
        bonus = _pct(totals, phys)
        value = base_val * damage_bonus * (1.0 + bonus / 100.0)
        if base_val or bonus:
            physical[phys] = value
        t = trace_mod.trace(phys, base_val, 'flat', '%s damage' % phys.title())
        for row in _rows(totals, phys):
            trace_mod.add(t, trace_mod.modifier(row['mod_name'], 'physical', row['value'],
                                                mod=row['mod'], rank=row['rank']))
        if bonus and not base_val:
            trace_mod.note(t, 'no base %s damage: the mod has no effect (wiki)' % phys)
        trace_mod.finish(t, value)
        t_phys[phys] = t
    traces.update(t_phys)

    # --- elemental damage -------------------------------------------------------
    elemental_mods, slots_by_element = {}, {}
    for slot in _elemental_order(mod_slots):
        mod = slot.get('mod') or {}
        eff = mod.get('effects') or {}
        rank = slot.get('rank')
        if rank is None:
            rank = mod.get('max_rank')
        for element in schema.ELEMENTAL_TYPES:
            value = effects_mod.rank_value(eff, element, rank)
            if value is None or not value:
                continue
            amount = modded_base * float(value) / 100.0
            elemental_mods[element] = elemental_mods.get(element, 0.0) + amount
            slots_by_element.setdefault(element, []).append((slot, value, amount))

    entries = []
    for element, amount in elemental_mods.items():
        first_slot, first_value, first_amount = slots_by_element[element][0]
        entries.append(elements.element_entry(
            element, amount, source='mod', slot=first_slot.get('index'),
            mod=(first_slot.get('mod') or {}).get('id'),
            mod_name=(first_slot.get('mod') or {}).get('name'),
            rank=first_slot.get('rank'),
            note=('%d mods merged' % len(slots_by_element[element]))
            if len(slots_by_element[element]) > 1 else None))
    innate_entries = []
    if innate_elements:
        for element, value in innate_elements.items():
            innate_entries.append(elements.element_entry(
                element, value * damage_bonus, source='innate',
                note='innate %.4g at rank-scaled base' % value))
    ordered, innate_notes = elements.apply_innate_rules(entries, innate_entries)
    notes.extend(innate_notes)
    composition = elements.combine(ordered)

    # --- composition + totals ---------------------------------------------------
    per_projectile = dict(physical)
    for row in composition['types']:
        per_projectile[row['element']] = per_projectile.get(row['element'], 0.0) + \
            float(row['amount'])
    t_elem = trace_mod.trace('elemental_damage', 0.0, 'flat', 'Elemental damage (per projectile)')
    for kind_name in schema.ELEMENTAL_TYPES:
        if kind_name not in elemental_mods:
            continue
        for slot, value, amount in slots_by_element[kind_name]:
            trace_mod.add(t_elem, trace_mod.modifier(
                (slot.get('mod') or {}).get('name'), 'elemental', value,
                mod=(slot.get('mod') or {}).get('id'), rank=slot.get('rank'),
                slot=slot.get('index'), amount=trace_mod._num(amount)))
    trace_mod.finish(t_elem, sum(elemental_mods.values()))
    traces['elemental_damage'] = t_elem
    projectile_total = sum(per_projectile.values())
    stats['per_projectile_total'] = trace_mod._num(projectile_total)

    # --- multishot --------------------------------------------------------------
    base_multishot = float(equip.get('multishot') or 1.0) or 1.0
    multishot_bonus = _pct(totals, 'multishot')
    multishot = base_multishot * (1.0 + multishot_bonus / 100.0)
    t_ms = trace_mod.trace('multishot', base_multishot, 'ratio', 'Multishot (projectiles)')
    for row in _rows(totals, 'multishot'):
        trace_mod.add(t_ms, trace_mod.modifier(row['mod_name'], 'percent', row['value'],
                                               mod=row['mod'], rank=row['rank']))
    trace_mod.finish(t_ms, multishot)
    traces['multishot'] = t_ms
    whole = int(multishot)
    fractional = multishot - whole
    stats['multishot'] = trace_mod._num(multishot)
    stats['multishot_whole'] = whole
    stats['multishot_extra_chance'] = trace_mod._num(fractional)

    per_shot = projectile_total * multishot
    stats['damage_per_shot'] = trace_mod._num(per_shot)
    # Flat per-type damage so a UI (and api.compare) can diff "before -> after" per
    # damage type without walking the composition block.
    for dtype, amount in per_projectile.items():
        stats['damage_' + dtype] = trace_mod._num(amount)

    # --- critical ---------------------------------------------------------------
    base_cc = float(equip.get('crit_chance') or 0.0)
    crit_chance = base_cc * (1.0 + _pct(totals, 'critical_chance') / 100.0)
    base_cd = float(equip.get('crit_multiplier') or 1.0)
    crit_multi = base_cd * (1.0 + _pct(totals, 'critical_damage') / 100.0)
    t_cc = trace_mod.trace('critical_chance', base_cc, 'percent', 'Critical Chance')
    for row in _rows(totals, 'critical_chance'):
        trace_mod.add(t_cc, trace_mod.modifier(row['mod_name'], 'percent', row['value'],
                                               mod=row['mod'], rank=row['rank']))
    trace_mod.finish(t_cc, crit_chance)
    t_cd = trace_mod.trace('critical_multiplier', base_cd, 'ratio', 'Critical Multiplier')
    for row in _rows(totals, 'critical_damage'):
        trace_mod.add(t_cd, trace_mod.modifier(row['mod_name'], 'percent', row['value'],
                                               mod=row['mod'], rank=row['rank']))
    trace_mod.finish(t_cd, crit_multi)
    traces['critical_chance'] = t_cc
    traces['critical_multiplier'] = t_cd
    tiers = crit_tiers(crit_chance, crit_multi)
    stats['critical_chance'] = trace_mod._num(crit_chance)
    stats['critical_multiplier'] = trace_mod._num(crit_multi)
    stats['critical_tier'] = tiers['tier']
    stats['critical_expected_multiplier'] = tiers['expected_multiplier']

    # --- status -----------------------------------------------------------------
    base_sc = float(equip.get('status_chance') or 0.0)
    status_chance = base_sc * (1.0 + _pct(totals, 'status_chance') / 100.0)
    t_sc = trace_mod.trace('status_chance', base_sc, 'percent', 'Status Chance (per projectile)')
    for row in _rows(totals, 'status_chance'):
        trace_mod.add(t_sc, trace_mod.modifier(row['mod_name'], 'percent', row['value'],
                                               mod=row['mod'], rank=row['rank']))
    trace_mod.finish(t_sc, status_chance)
    traces['status_chance'] = t_sc
    stats['status_chance'] = trace_mod._num(status_chance)
    stats['status_procs_per_projectile'] = trace_mod._num(status_chance / 100.0)
    stats['status_expected_procs_per_shot'] = trace_mod._num(multishot * status_chance / 100.0)

    # --- fire rate / magazine / reload -----------------------------------------
    fire_rate = float(equip.get('fire_rate') or 0.0)
    rate_stat = 'attack_speed' if kind == schema.EQUIP_MELEE else 'fire_rate'
    rate_bonus = _pct(totals, rate_stat) + (_pct(totals, 'fire_rate')
                                            if kind == schema.EQUIP_MELEE else 0.0)
    modded_rate = fire_rate * (1.0 + rate_bonus / 100.0)
    t_rate = trace_mod.trace(rate_stat, fire_rate, 'flat',
                             'Attack Speed' if kind == schema.EQUIP_MELEE else 'Fire Rate')
    for row in _rows(totals, rate_stat) + (_rows(totals, 'fire_rate')
                                           if kind == schema.EQUIP_MELEE else []):
        trace_mod.add(t_rate, trace_mod.modifier(row['mod_name'], 'percent', row['value'],
                                                 mod=row['mod'], rank=row['rank']))
    trace_mod.finish(t_rate, modded_rate)
    traces[rate_stat] = t_rate
    stats[rate_stat] = trace_mod._num(modded_rate)

    magazine = float(equip.get('magazine') or 0.0)
    modded_mag = magazine * (1.0 + _pct(totals, 'magazine_capacity') / 100.0)
    stats['magazine_size'] = trace_mod._num(modded_mag) if magazine else None
    t_mag = trace_mod.trace('magazine_size', magazine, 'flat', 'Magazine Size')
    for row in _rows(totals, 'magazine_capacity'):
        trace_mod.add(t_mag, trace_mod.modifier(row['mod_name'], 'percent', row['value'],
                                                mod=row['mod'], rank=row['rank']))
    trace_mod.finish(t_mag, modded_mag)
    traces['magazine_size'] = t_mag

    reload_time = equip.get('reload')
    modded_reload = None
    if reload_time:
        speed = _pct(totals, 'reload_speed')
        modded_reload = float(reload_time) / (1.0 + speed / 100.0)
        t_rel = trace_mod.trace('reload_time', reload_time, 'flat', 'Reload Time (s)')
        for row in _rows(totals, 'reload_speed'):
            trace_mod.add(t_rel, trace_mod.modifier(row['mod_name'], 'percent',
                                                    row['value'], mod=row['mod'],
                                                    rank=row['rank'],
                                                    note='reload speed, time divides'))
        trace_mod.finish(t_rel, modded_reload)
        traces['reload_time'] = t_rel
    stats['reload_time'] = trace_mod._num(modded_reload)

    for stat in ('punch_through', 'range', 'combo_duration', 'status_duration',
                 'accuracy', 'zoom', 'recoil', 'projectile_speed'):
        if stat in totals:
            stats[stat] = trace_mod._num(_pct(totals, stat))

    # --- damage expectations ----------------------------------------------------
    crit_expected = tiers['expected_multiplier']
    per_shot_crit = per_shot * crit_expected
    quantized = None
    if opts.get('quantize') and base_total:
        quantized = quantize_composition(per_projectile, modded_base)
        notes.append('quantized per the wiki rule (each type to 1/32 of the modded base '
                     'damage); the arsenal shows the unquantized values')
    stats['damage_per_shot_expected_crit'] = trace_mod._num(per_shot_crit)

    # --- the viral status mechanic (4.4) ----------------------------------------
    # Evaluated when the build can actually apply viral procs, or when the caller described a
    # target that already carries them. A build with no viral damage and no target state is not
    # asked the question at all, which is what keeps every Phase 1 number untouched.
    viral_row = None
    consumed = [f for f in ('target_faction',)
                if any(s.startswith('faction_') for s in totals)]
    if any(s == 'damage_on_first_shot' for s in totals):
        consumed.append('attack.shot_index')
    if per_projectile.get('viral') or conditions.has(ctx, 'target', 'viral_stacks'):
        viral_row = statuses.evaluate(ctx)
        consumed += ['target.viral_stacks', 'target.protection', 'target.immune_to']
        if mode == 'hypothetical' and viral_row['state'] == conditions.UNKNOWN:
            viral_row = dict(viral_row, hypothetical=True)
        condition_rows.append(viral_row)
        t_viral = trace_mod.trace('viral_amplifier', 1.0, 'ratio',
                                  'Viral amplification (damage to health)')
        trace_mod.note(t_viral, statuses.FORMULA)
        trace_mod.note(t_viral, 'source: %s' % statuses.SOURCE)
        # `hypothetical` shows a condition as-if satisfied, but an unknown viral row has no
        # `amplifier` key at all ("a refusal carries no number"), so there is nothing to apply and
        # nothing to trace. Dereferencing it here raised KeyError on the HTTP route (adversarial
        # review F1).
        if condition_applies(viral_row) and viral_row.get('amplifier') is not None:
            row = statuses.trace_rows(viral_row)
            trace_mod.add(t_viral, row)
            trace_mod.finish(t_viral, viral_row['amplifier'])
            # the multiplier is a headline scalar like critical_multiplier, so it lives in stats as
            # well as in its trace; the state travels beside it in `conditions`
            stats['viral_amplifier'] = trace_mod._num(viral_row['amplifier'])
            # The wiki's own output: the modded damage x the amplifier. `damage_to_health` uses
            # this build's damage_per_shot (no crit assumption); the crit-weighted companion uses
            # the same per-shot figure the rest of the panel quotes. Both are kept out of every
            # Phase 1 stat, so the unconditional answers cannot move - and both carry a trace that
            # names the formula, the source and the amplifier that was applied.
            amp = viral_row['amplifier']
            stats['damage_to_health'] = trace_mod._num(per_shot * amp)
            stats['damage_to_health_expected_crit'] = trace_mod._num(per_shot_crit * amp)
            t_health = trace_mod.trace('damage_to_health', per_shot, 'flat',
                                       'Damage per shot to health (viral-amplified)')
            trace_mod.note(t_health, '%s - modded_damage is this build\'s damage_per_shot'
                           % statuses.FORMULA)
            trace_mod.note(t_health, 'source: %s' % statuses.SOURCE)
            trace_mod.add(t_health, statuses.trace_rows(viral_row))
            trace_mod.finish(t_health, per_shot * amp, intermediate=amp)
            traces['damage_to_health'] = t_health
            t_healthc = trace_mod.trace('damage_to_health_expected_crit', per_shot_crit, 'flat',
                                        'Damage per shot to health, crit-weighted')
            trace_mod.note(t_healthc, 'damage_per_shot_expected_crit x viral amplifier')
            trace_mod.add(t_healthc, statuses.trace_rows(viral_row))
            trace_mod.finish(t_healthc, per_shot_crit * amp, intermediate=amp)
            traces['damage_to_health_expected_crit'] = t_healthc
        else:
            trace_mod.finish(t_viral, None)
            trace_mod.note(t_viral, 'withheld: %s (%s)'
                           % (viral_row['state'], viral_row['reason']))
        traces['viral_amplifier'] = t_viral

    # --- faction damage (applied last, never in the arsenal total) --------------
    # 4.3: the first condition source with a full pipeline - context -> condition -> state ->
    # effect -> number or refusal. The multiplier now comes from the condition rows above, never
    # from a bare 'is a faction option set' test, so a bonus that is simply unknown is reported as
    # withheld instead of being quietly multiplied by 1.
    faction_multiplier = 1.0
    for stat in faction_stats:
        if condition_applies(faction_rows[stat]):
            faction_multiplier *= 1.0 + _pct(totals, stat) / 100.0
    if faction_multiplier != 1.0:
        notes.append('faction damage x%.4g applies to every type but is not part of '
                     'the arsenal total (wiki)' % faction_multiplier)
    for stat in faction_stats:
        row = faction_rows[stat]
        if not condition_applies(row):
            notes.append('%s: %s - %s'
                         % (stat.replace('_', ' '), row['state'], row['reason']))

    # --- DPS --------------------------------------------------------------------
    trigger = (opts.get('trigger_override') or equip.get('trigger') or '').strip().lower()
    dps = _dps_block(per_shot_crit, modded_rate, modded_mag, modded_reload, trigger,
                     faction_multiplier, kind)
    unsupported.extend(dps.pop('unsupported', []))
    stats['burst_dps'] = dps['burst']['value']
    stats['sustained_dps'] = dps['sustained']['value']

    # --- mechanics this engine refuses to fake ----------------------------------
    if kind == schema.EQUIP_MELEE:
        unsupported.extend([
            _marker('melee_combo_multiplier',
                    'melee combo counter multipliers are not modelled (Phase 1 melee is '
                    'base stance-free damage)', equipment=equip.get('id')),
            _marker('heavy_attack',
                    'heavy attack damage and wind-up are not modelled',
                    equipment=equip.get('id')),
            _marker('stance_multiplier',
                    'stance damage multipliers are not modelled',
                    equipment=equip.get('id')),
        ])
    if equip.get('incarnon'):
        unsupported.append(_marker('incarnon',
                                   'Incarnon evolution stats are not modelled',
                                   equipment=equip.get('id')))
    if equip.get('traits'):
        unsupported.append(_marker('weapon_traits',
                                   'the weapon carries special traits Phase 1 does not '
                                   'model: %s' % ', '.join(equip['traits'][:4]),
                                   equipment=equip.get('id')))

    # --- the evaluation block (4.5) --------------------------------------------
    # Three kinds of answer, named: a deterministic result (every condition that bears on it was
    # satisfied by the stated inputs), a conditional result (something that bears on it is unknown,
    # so the numbers below are the stated-inputs answer with those contributions withheld), and a
    # refused result (the caller asked for strict semantics and a condition could not be resolved,
    # so the affected stats are withheld entirely rather than answered).
    blocked = [r for r in condition_rows if r['state'] in (conditions.UNKNOWN,
                                                          conditions.UNSUPPORTED)]
    refused_stats = []
    if mode == 'strict' and blocked:
        for key in ('damage_per_shot', 'damage_per_shot_expected_crit', 'burst_dps',
                    'sustained_dps', 'damage_to_health', 'damage_to_health_expected_crit'):
            if key in stats and stats[key] is not None:
                stats[key] = None
                refused_stats.append(key)
        for row in blocked:
            unsupported.append(_marker(
                'calculation_refused', 'the %s condition is %s: %s'
                % (row['condition'], row['state'], row['reason']),
                condition=row['condition'], state=row['state'],
                reason_code=row['reason_code'], stats=refused_stats,
                equipment=equip.get('id')))
    evaluation = {
        'mode': mode,
        'state': ('refused' if refused_stats
                  else 'conditional' if blocked else 'deterministic'),
        'context_supplied': ctx['supplied'],
        'context_ignored': ctx['ignored'],
        'withheld': [r['condition'] for r in condition_rows if not condition_applies(r)],
        'consumed': list(consumed),
        'refused_stats': refused_stats,
        # `state` above is about the conditions this engine can reason about. Mechanics it cannot
        # model are refused as *effects* and counted here, so one payload carries both facts and a
        # reader never has to infer one from the other.
        'unsupported_effects': len([m for m in unsupported
                                    if m.get('code') in unsupported_mod.MARKER_TO_KEY]),
    }

    result = {
        'equipment': {'id': equip.get('id'), 'name': equip.get('name'), 'kind': kind,
                      'trigger': trigger or None},
        'conditions': condition_rows,
        'evaluation': evaluation,
        'stats': stats,
        'damage': {
            'per_projectile': {k: trace_mod._num(v) for k, v in per_projectile.items()},
            'per_projectile_total': trace_mod._num(projectile_total),
            'per_shot_total': trace_mod._num(per_shot),
            'modded_base_damage': trace_mod._num(modded_base),
            'composition': composition,
            'quantized_per_projectile': quantized,
        },
        'crit': tiers,
        'status': {
            'chance_per_projectile': trace_mod._num(status_chance),
            'expected_procs_per_projectile': trace_mod._num(status_chance / 100.0),
            'expected_procs_per_shot': trace_mod._num(multishot * status_chance / 100.0),
            'over_100': status_chance > 100.0,
            'damage_type_weights': _weights(per_projectile),
        },
        'multishot': {'expected': trace_mod._num(multishot), 'whole': whole,
                      'extra_chance': trace_mod._num(fractional),
                      'base': trace_mod._num(base_multishot)},
        'dps': dps,
        'faction_multiplier': trace_mod._num(faction_multiplier),
        'traces': traces,
        'unsupported': unsupported,
        'notes': notes,
    }
    if refused_stats:
        _withhold_mirrors(result, refused_stats)
    return result


# Where else a refused stat's number is reported. The page reads `result.dps` and `result.damage`
# as well as `stats`, so a refusal that nulled only `stats` still left the same figure on screen in
# the damage card (adversarial review F2). Every mirror of a refused stat is nulled with it, and
# the gate walks these paths.
MIRROR_PATHS = {
    'burst_dps': (('dps', 'burst', 'value'),),
    'sustained_dps': (('dps', 'sustained', 'value'),),
    'damage_per_shot': (('damage', 'per_shot_total'),),
}


def _withhold_mirrors(result, refused):
    """Null every other place a refused stat's number appears, traces included."""
    for stat in refused:
        for path in MIRROR_PATHS.get(stat, ()):
            node = result
            for key in path[:-1]:
                node = node.get(key) if isinstance(node, dict) else None
            if isinstance(node, dict) and path[-1] in node:
                node[path[-1]] = None
        trace = (result.get('traces') or {}).get(stat)
        if isinstance(trace, dict):
            trace['final'] = None
    return result


def _elemental_order(mod_slots):
    """Mods in the game's own hierarchy order: normal slots 0..7, then the Exilus slot.

    Aura/Stance mods are capacity sources and carry no damage types, so they are not
    part of the hierarchy. The Exilus slot is documented as coming after the eight
    normal slots (it is a ninth slot in the data model).
    """
    normal = [s for s in (mod_slots or []) if (s.get('kind') or schema.SLOT_NORMAL)
              == schema.SLOT_NORMAL]
    exilus = [s for s in (mod_slots or []) if s.get('kind') == schema.SLOT_EXILUS]
    normal.sort(key=lambda s: (s.get('index') if s.get('index') is not None else 99))
    exilus.sort(key=lambda s: (s.get('index') if s.get('index') is not None else 99))
    return normal + exilus


def crit_tiers(crit_chance, crit_multiplier):
    """Critical tier breakdown + the expected multiplier (no booleans, no rounding off).

    tier k multiplier = 1 + k x (crit multiplier - 1). With a fractional chance the
    expected multiplier is the weighted mix of the guaranteed tier and one tier higher.
    """
    chance = max(0.0, float(crit_chance or 0.0))
    multi = float(crit_multiplier or 1.0)
    tier = int(chance // 100.0)
    fraction = (chance / 100.0) - tier
    def mult_for(k):
        return 1.0 + k * (multi - 1.0)
    guaranteed = mult_for(tier)
    next_tier = mult_for(tier + 1)
    expected = (1.0 - fraction) * guaranteed + fraction * next_tier
    if chance <= 0.0:
        expected = 1.0
    return {
        'chance': trace_mod._num(chance), 'multiplier': trace_mod._num(multi),
        'tier': tier, 'tier_fraction': trace_mod._num(fraction),
        'guaranteed_multiplier': trace_mod._num(guaranteed if chance > 0 else 1.0),
        'next_tier_multiplier': trace_mod._num(next_tier),
        'expected_multiplier': trace_mod._num(expected),
        'over_100': chance > 100.0,
    }


def quantize_composition(per_projectile, modded_base):
    """The wiki's quantization rule applied to a damage composition.

    quantized(x) = sign(x) * floor(|x| * 32 + 0.5) / 32 * modded_base, per damage type.
    """
    if not modded_base:
        return None
    scale = float(modded_base) / 32.0
    out = {}
    for element, value in (per_projectile or {}).items():
        units = int(abs(float(value)) / scale + 0.5)
        quantized = units * scale
        out[element] = trace_mod._num(quantized if float(value) >= 0 else -quantized)
    return out


def _weights(per_projectile):
    """Each damage type's share of the total (feeds later proc weighting)."""
    total = sum(float(v) for v in per_projectile.values())
    if not total:
        return {}
    return {k: trace_mod._num(float(v) / total) for k, v in per_projectile.items()}


def _dps_block(per_shot_crit, modded_rate, magazine, reload_time, trigger,
               faction_multiplier, kind):
    """Burst + sustained DPS, refusing trigger types the wiki documents as special."""
    shot = per_shot_crit * faction_multiplier
    supported = trigger in SUPPORTED_TRIGGERS and bool(modded_rate)
    block = {
        'burst': {'value': None, 'supported': bool(supported),
                  'formula': 'average shot x effective fire rate'},
        'sustained': {'value': None, 'supported': bool(supported and magazine and
                                                       reload_time is not None),
                      'formula': 'burst x shots / (shots + fire rate x reload)'},
        'assumptions': [],
    }
    if not supported:
        block['unsupported'] = [_marker(
            'dps_trigger_type',
            'trigger type %r has a documented non-trivial effective fire rate that '
            'Phase 1 does not implement (Charge/Burst/Continuous); burst and sustained '
            'DPS are withheld rather than approximated' % (trigger or 'unknown'),
            equipment=None)]
        return block
    burst = shot * modded_rate
    block['burst']['value'] = trace_mod._num(burst)
    block['assumptions'].append('assumes the player fires at the arsenal fire rate')
    if magazine and reload_time is not None:
        shots = float(magazine)
        sustained = burst * shots / (shots + modded_rate * float(reload_time))
        block['sustained']['value'] = trace_mod._num(sustained)
        block['assumptions'].append('reload is uninterrupted and full')
    if kind == schema.EQUIP_MELEE:
        block['assumptions'].append('melee: no combo counter, no stance multiplier, no '
                                    'heavy attacks')
    return block


def _normalise_equipment(row):
    """Ingest-shaped row -> the keys this engine reads (kept here for clarity)."""
    out = dict(row or {})
    damage = out.get('damage') or {}
    out['damage'] = {k: float(v) for k, v in damage.items() if v}
    out['damage_total'] = float(out.get('damage_total') or sum(out['damage'].values()))
    return out


# ------------------------------------------------------------------ selftest
def _fixture_equipment(**over):
    """A Braton Prime row with the export's real values (wiki-verified)."""
    row = {'id': '/fixture/BratonPrime', 'name': 'Braton Prime', 'kind': 'primary',
           'mastery_req': 8, 'max_rank': 30,
           'damage': {'impact': 1.75, 'puncture': 12.25, 'slash': 21},
           'damage_total': 35.0, 'crit_chance': 12.0, 'crit_multiplier': 2.0,
           'status_chance': 26.0, 'fire_rate': 9.583334, 'multishot': 1.0,
           'magazine': 75, 'reload': 2.15, 'trigger': 'Auto'}
    row.update(over)
    return row


def _fixture_slot(index, mod_row, rank, kind=schema.SLOT_NORMAL, polarity=None):
    return {'kind': kind, 'index': index, 'polarity': polarity, 'mod': mod_row,
            'rank': rank}


def _mod(name, lines, **kw):
    """Fixture mod -> ingested row (shared with effects.selftest's builders)."""
    return effects_mod._as_row(effects_mod._fixture_mod(name, lines, **kw))


def selftest():
    """Weapon math against the wiki's documented values. Offline, writes nothing."""
    failures = []

    counter = [0]

    def check(label, ok, detail=''):
        counter[0] += 1
        print('%s  %s%s' % ('PASS' if ok else 'FAIL', label,
                            '' if ok else ' -- %s' % detail))
        if not ok:
            failures.append(label)

    def near(a, b, tol=1e-6):
        return a is not None and abs(float(a) - float(b)) <= tol

    serration = _mod('Serration', [['+%d%% Damage' % (15 * (i + 1))] for i in range(11)])
    hellfire = _mod('Hellfire', [['+%d%% <DT_FIRE_COLOR>Heat' % (15 * (i + 1))]
                                 for i in range(6)], polarity='naramon')
    cryo = _mod('Cryo Rounds', [['+%d%% <DT_FREEZE_COLOR>Cold' % (15 * (i + 1))]
                                for i in range(6)], polarity='naramon')
    point_strike = _mod('Point Strike', [['+%d%% Critical Chance' % (25 * (i + 1))]
                                         for i in range(6)])
    vital_sense = _mod('Vital Sense', [['+%d%% Critical Damage' % (20 * (i + 1))]
                                       for i in range(6)])
    split_chamber = _mod('Split Chamber', [['+%d%% Multishot' % (15 * (i + 1))]
                                           for i in range(6)])
    fast_hands = _mod('Fast Hands', [['+%d%% Reload Speed' % (5 * (i + 1))]
                                     for i in range(6)])
    bane = _mod('Bane of Grineer', [['+%d%% Damage to Grineer' % (5 * (i + 1))]
                                    for i in range(6)])

    base = calculate(_fixture_equipment(), [])
    check('unmodded Braton Prime deals 35 per projectile',
          near(base['damage']['per_projectile_total'], 35)
          and near(base['damage']['per_projectile']['impact'], 1.75)
          and near(base['damage']['per_projectile']['puncture'], 12.25)
          and near(base['damage']['per_projectile']['slash'], 21),
          str(base['damage']['per_projectile']))
    check('unmodded crit 12% x2.0, status 26%, multishot 1',
          near(base['stats']['critical_chance'], 12)
          and near(base['stats']['critical_multiplier'], 2)
          and near(base['stats']['status_chance'], 26)
          and near(base['stats']['multishot'], 1))
    check('expected crit multiplier below 100% chance is 1 + chance x (multi - 1)',
          near(base['stats']['critical_expected_multiplier'], 1.12),
          str(base['stats']['critical_expected_multiplier']))

    serr = calculate(_fixture_equipment(), [_fixture_slot(0, serration, 10)])
    check('Serration R10: base 35 -> 92.75 (+165% of base)',
          near(serr['damage']['modded_base_damage'], 92.75)
          and near(serr['damage']['per_projectile_total'], 92.75),
          str(serr['damage']['modded_base_damage']))
    check('Serration scales every physical type that exists',
          near(serr['damage']['per_projectile']['slash'], 21 * 2.65),
          str(serr['damage']['per_projectile']))
    damage_text = trace_mod.text(serr['traces']['damage'])
    check('the damage trace reads as the brief\'s worked example',
          'Base: 35' in damage_text and 'Serration R10: +165% of base' in damage_text
          and 'Final: 92.75' in damage_text, damage_text.replace('\n', ' | '))

    elems = calculate(_fixture_equipment(),
                      [_fixture_slot(0, serration, 10), _fixture_slot(1, hellfire, 5),
                       _fixture_slot(2, cryo, 5)])
    check('Hellfire + Cryo Rounds combine into Blast (2 x 0.9 x 92.75 = 166.95)',
          near(elems['damage']['per_projectile'].get('blast'), 166.95)
          and near(elems['damage']['per_projectile_total'], 259.7),
          str(elems['damage']['per_projectile']))
    check('elemental mods scale off the MODDED base, not the base',
          near(elems['damage']['per_projectile']['blast'], 2 * 0.9 * 92.75))

    crit = calculate(_fixture_equipment(), [_fixture_slot(0, point_strike, 5),
                                            _fixture_slot(1, vital_sense, 5)])
    check('Point Strike R5: 12% + 150% -> 30% crit chance',
          near(crit['stats']['critical_chance'], 30), str(crit['stats']['critical_chance']))
    check('Vital Sense R5: 2.0 + 120% -> 4.4 crit multiplier (multiplicative on the '
          'crit multiplier itself)',
          near(crit['stats']['critical_multiplier'], 4.4),
          str(crit['stats']['critical_multiplier']))
    check('30% crit at x4.4 -> expected multiplier 2.02',
          near(crit['crit']['expected_multiplier'], 1 + 0.3 * 3.4),
          str(crit['crit']['expected_multiplier']))

    multi = calculate(_fixture_equipment(), [_fixture_slot(0, serration, 10),
                                             _fixture_slot(1, split_chamber, 5)])
    check('Split Chamber R5: 1 + 90% -> 1.9 multishot',
          near(multi['stats']['multishot'], 1.9), str(multi['stats']['multishot']))
    check('damage per shot includes multishot (92.75 x 1.9 = 176.225)',
          near(multi['stats']['damage_per_shot'], 176.225),
          str(multi['stats']['damage_per_shot']))

    reload_mod = calculate(_fixture_equipment(), [_fixture_slot(0, fast_hands, 5)])
    check('reload time = base / (1 + reload speed) (2.15 / 1.3 = 1.653846)',
          near(reload_mod['stats']['reload_time'], 2.15 / 1.3, 1e-4),
          str(reload_mod['stats']['reload_time']))

    with_bane = calculate(_fixture_equipment(), [_fixture_slot(0, serration, 10),
                                                 _fixture_slot(1, bane, 5)],
                          {'faction': 'grineer'})
    check('faction damage is a separate x1.3 multiplier, not part of the base total',
          near(with_bane['faction_multiplier'], 1.3)
          and near(with_bane['damage']['per_projectile_total'], 92.75),
          '%s / %s' % (with_bane['faction_multiplier'],
                       with_bane['damage']['per_projectile_total']))

    dps = calculate(_fixture_equipment(),
                    [_fixture_slot(0, serration, 10), _fixture_slot(1, split_chamber, 5)])
    shot = dps['stats']['damage_per_shot_expected_crit']
    check('burst DPS = average shot x fire rate',
          near(dps['stats']['burst_dps'], shot * 9.583334, 1e-3),
          '%s vs %s' % (dps['stats']['burst_dps'], shot * 9.583334))
    check('sustained DPS = burst x magazine / (magazine + fire rate x reload)',
          near(dps['stats']['sustained_dps'],
               shot * 9.583334 * 75 / (75 + 9.583334 * 2.15), 1e-3),
          str(dps['stats']['sustained_dps']))

    charged = calculate(_fixture_equipment(trigger='Charge'), [])
    check('an exotic trigger withholds DPS and says why',
          charged['dps']['burst']['value'] is None
          and any(m['code'] == 'dps_trigger_type' for m in charged['unsupported']))

    melee = calculate(_fixture_equipment(kind='melee', magazine=None, reload=None,
                                         trigger='Auto'),
                      [_fixture_slot(0, serration, 10)])
    check('melee carries the combo / heavy attack / stance refusals',
          {'melee_combo_multiplier', 'heavy_attack', 'stance_multiplier'} <=
          {m['code'] for m in melee['unsupported']},
          str(sorted({m['code'] for m in melee['unsupported']})))

    quant = quantize_composition({'impact': 4.6375, 'slash': 55.65}, 92.75)
    scale = 92.75 / 32.0
    check('quantization lands on multiples of modded_base / 32',
          near(quant['impact'], round(2 * scale, 4), 1e-6)
          and near(quant['slash'], round(19 * scale, 4), 1e-6),
          str(quant))
    tiers = crit_tiers(110.0, 2.0)
    check('a 110% crit chance sits in tier 1 with 10% of tier 2 '
          '(expected 0.9 x 2 + 0.1 x 3 = 2.1)',
          tiers['tier'] == 1 and near(tiers['expected_multiplier'], 2.1), str(tiers))
    print('\nweapons selftest %s (%d checks, %d failed) - nothing written'
          % ('OK' if not failures else 'FAILED', counter[0], len(failures)))
    return 0 if not failures else 1
