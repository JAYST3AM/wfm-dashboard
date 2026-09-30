#!/usr/bin/env python3
"""Warframe stat engine: what a modded Warframe has - and why.

Formulas (WARFRAME Wiki: Warframes, Abilities, Ability Efficiency, Steel Fiber):

  rank scaling   the catalog carries rank-0 base stats. Ranking up adds a FIXED amount
                 derived from the base (wiki "Leveling Up"): +10 Health every 3 ranks
                 from rank 1 (base+100 at rank 30), +10 Shield from rank 2 (+100), +5
                 Energy from rank 3 (+50); Armor and sprint speed do not rank-scale.
                 Frames in the wiki's Rank-Up Exceptions list (Inaros +200 Health,
                 Hildryn +500 Shields, Nidus +100 Armor, ...) use their documented
                 totals: exact at rank 30, and below rank 30 the total is spread over the
                 default cadence and reported as an approximation. Nidus / Nidus Prime
                 have a fully documented step schedule and are exact at every rank.
  mods apply     to the stat at the CURRENT rank ("Health, Shield, Energy, and Armor
                 Mods apply to the stats of Warframes at their current rank"), so at
                 rank 30 with max Vitality: (base + 100) x (1 + 1.00) = the familiar
                 740 Health on an Excalibur (370 x 2).
  ability stats  every frame starts at 100%; mods add percentage points (Intensify +30,
                 Transient Fortitude +55 -> 185%). Efficiency is special: energy cost
                 cannot drop below 25% of base, which is why the arsenal never displays
                 more than 175% - the raw value is exposed too, because channeled
                 abilities use efficiency above the cap when duration is below 100%.
  caps/floors    efficiency: display cap 175%, cost floor 25%; strength/duration/range
                 have no cap (negative mods can push duration very low - returned as the
                 raw sum, with per-ability effects left to later phases).

Unsupported (returned as markers, never invented): ability-specific formulas, augments,
Helminth, Archon Shards, arcanes, companion/external buffs, Nidus's health regeneration,
and the rank-up interpolation for exception frames below rank 30.
"""
from . import effects as effects_mod
from . import schema, trace as trace_mod, unsupported as unsupported_mod

# Stats read straight off the equipment row and scaled by rank (armor only scales for
# the frame families that have a documented armor bonus).
RANK_SCALED = (('health', 'health'), ('shield', 'shield'), ('energy', 'energy'),
               ('armor', 'armor'))
# Stats that are flat base values (no rank scaling at all).
FLAT_BASE = (('sprint_speed', 'sprint_speed'),)

ABILITY_STATS = (
    ('ability_strength', 'Ability Strength'),
    ('ability_duration', 'Ability Duration'),
    ('ability_efficiency', 'Ability Efficiency'),
    ('ability_range', 'Ability Range'),
)


def collect_mod_effects(mod_slots):
    """Thin alias so callers can stay inside this module (implementation shared)."""
    return effects_mod.collect_mod_effects(mod_slots)


def calculate(equipment, mod_slots=None, options=None):
    """A modded Warframe -> stats + traces + refusals.

    equipment: ingested row - id, name, kind, base stats {health, shield, armor, energy,
               sprint_speed}, max_rank.
    options:   {'rank': int (default max rank), 'frame': name override}
    """
    opts = {'rank': None}
    opts.update(options or {})
    equip = equipment or {}
    stats_in = equip.get('stats') or {}
    max_rank = int(equip.get('max_rank') or schema.MAX_RANK_FRAME)
    rank = max_rank if opts.get('rank') is None else max(0, int(opts['rank']))
    totals, unsupported, notes = collect_mod_effects(mod_slots)
    traces, stats = {}, {}

    name = equip.get('name')
    low = str(name or '').strip().lower()
    if low in schema.NIDUS_FRAMES:
        unsupported.append(unsupported_mod.marker(
            'nidus_health_regeneration',
            '%s gains +2 Health/s Regeneration every 6 ranks from rank 6 (+15/s at rank '
            '30); regeneration is not modelled' % name, equipment=equip.get('id')))

    # --- rank-scaled pools ------------------------------------------------------
    for key, out_key in RANK_SCALED:
        base = float(stats_in.get(key) or 0.0)
        bonus, exact = schema.frame_rank_bonus(name, key, rank, max_rank)
        at_rank = base + bonus
        if not exact:
            unsupported.append(unsupported_mod.marker(
                'rank_bonus_approximation',
                '%s is in the Rank-Up Exceptions list: its rank-30 total is documented '
                'but the per-rank cadence is not, so intermediate ranks are spread over '
                'the default cadence' % name, equipment=equip.get('id'), stat=out_key))
        if not at_rank and not stats_in.get(key):
            continue                                  # frames with no shields at all
        t = trace_mod.trace(out_key, base, 'flat', key.title())
        if bonus:
            source = ('Nidus rank-up schedule' if low in schema.NIDUS_FRAMES
                      else 'Rank-Up Exceptions total' if low in schema.RANK_BONUS_EXCEPTIONS
                      else 'default rank-up schedule')
            trace_mod.note(t, 'rank %d: base %s + %s rank gain %s (%s)'
                          % (rank, trace_mod._num(base), trace_mod._num(bonus),
                             'exact' if exact else 'spread over the default cadence',
                             source))
            trace_mod.add(t, trace_mod.modifier('rank %d' % rank, 'flat', bonus,
                                                unit='flat',
                                                mod_name='rank-up gain'),
                          intermediate=at_rank)
        for row in effects_mod.effect_rows_of(totals, out_key):
            trace_mod.add(t, trace_mod.modifier(row['mod_name'], 'percent', row['value'],
                                                mod=row['mod'], rank=row['rank'],
                                                note=row.get('note')))
        trace_mod.finish(t, at_rank * (1.0 + effects_mod.summed_percent(totals, out_key)
                                       / 100.0))
        traces[out_key] = t
        stats[out_key] = trace_mod.value(t)
        stats[out_key + '_ranked'] = trace_mod._num(at_rank)
        stats[out_key + '_base'] = trace_mod._num(base)

    # --- flat base stats --------------------------------------------------------
    for key, out_key in FLAT_BASE:
        base = float(stats_in.get(key) or 0.0)
        bonus = effects_mod.summed_percent(totals, out_key)
        total = base * (1.0 + bonus / 100.0)
        t = trace_mod.trace(out_key, base, 'flat', key.replace('_', ' ').title())
        for row in effects_mod.effect_rows_of(totals, out_key):
            trace_mod.add(t, trace_mod.modifier(row['mod_name'], 'percent', row['value'],
                                                mod=row['mod'], rank=row['rank'],
                                                note=row.get('note')))
        trace_mod.finish(t, total)
        traces[out_key] = t
        stats[out_key] = trace_mod._num(total)

    # --- ability stats ----------------------------------------------------------
    for stat_id, label in ABILITY_STATS:
        rank_gain, gain_exact = schema.frame_rank_bonus(name, stat_id, rank, max_rank)
        bonus = effects_mod.summed_percent(totals, stat_id)
        total = schema.ABILITY_BASE + rank_gain + bonus
        t = trace_mod.trace(stat_id, schema.ABILITY_BASE, 'percent', label)
        if rank_gain:
            trace_mod.add(t, trace_mod.modifier('rank %d' % rank, 'flat', rank_gain,
                                                mod_name='rank-up gain'),
                          intermediate=schema.ABILITY_BASE + rank_gain)
            trace_mod.note(t, '%s carries an Ability Strength rank-up exception: +%s '
                          'percentage points by rank %d (%s)'
                          % (name, trace_mod._num(rank_gain), rank,
                             'exact' if gain_exact else 'approximate'))
        for row in effects_mod.effect_rows_of(totals, stat_id):
            trace_mod.add(t, trace_mod.modifier(row['mod_name'], 'flat', row['value'],
                                                mod=row['mod'], rank=row['rank'],
                                                note=row.get('note') or 'percentage points'))
        trace_mod.finish(t, total)
        traces[stat_id] = t
        stats[stat_id] = trace_mod._num(total)
    efficiency = float(stats['ability_efficiency'])
    display = min(efficiency, schema.EFFICIENCY_DISPLAY_CAP)
    cost_multiplier = max(schema.ENERGY_COST_FLOOR, 2.0 - efficiency / 100.0)
    stats['ability_efficiency_display'] = trace_mod._num(display)
    stats['ability_cost_multiplier'] = trace_mod._num(cost_multiplier)
    if efficiency > schema.EFFICIENCY_DISPLAY_CAP:
        trace_mod.note(traces['ability_efficiency'],
                       'above the 175%% display cap; energy costs cannot drop below 25%% '
                       'of base (channeled abilities still use the raw value)')
    if efficiency < schema.ABILITY_BASE:
        notes.append('negative efficiency: abilities cost more than base')

    for stat in ('casting_speed', 'shield_recharge', 'shield_recharge_delay',
                 'tau_resistance', 'energy_regen'):
        if stat in totals:
            stats[stat] = trace_mod._num(effects_mod.summed_percent(totals, stat))

    # --- refusals ---------------------------------------------------------------
    for slot in mod_slots or []:
        mod = slot.get('mod') or {}
        flags = mod.get('flags') or {}
        if flags.get('augment'):
            unsupported.append(effects_mod.unsupported_marker(
                'augment_mod', '%s is an augment; it changes one specific ability and '
                'Phase 1 has no ability formulas' % (mod.get('name') or mod.get('id')),
                mod=mod.get('id')))
    unsupported.append(effects_mod.unsupported_marker(
        'ability_formulas',
        'per-ability formulas (damage, range, duration values) are not implemented; '
        'only the four ability stats are computed', equipment=equip.get('id')))
    unsupported.append(effects_mod.unsupported_marker(
        'external_buffs',
        'Helminth, Archon Shards, arcanes, companion and squad buffs are not modelled',
        equipment=equip.get('id')))

    return {
        'equipment': {'id': equip.get('id'), 'name': equip.get('name'),
                      'kind': equip.get('kind') or schema.EQUIP_WARFRAME,
                      'rank': rank},
        'stats': stats,
        'traces': traces,
        'unsupported': unsupported,
        'notes': notes,
    }


# ------------------------------------------------------------------ selftest
def _fixture_frame(name, stats, **over):
    row = {'id': '/fixture/' + name, 'name': name, 'kind': schema.EQUIP_WARFRAME,
           'max_rank': 30, 'stats': stats}
    row.update(over)
    return row


def _mod(name, lines, **kw):
    """Fixture mod -> ingested row (shared with effects.selftest's builders)."""
    return effects_mod._as_row(effects_mod._fixture_mod(name, lines, **kw))


def _slot(index, mod_row, rank):
    return {'kind': schema.SLOT_NORMAL, 'index': index, 'polarity': None,
            'mod': mod_row, 'rank': rank}


def selftest():
    """Frame math against the wiki's infobox values. Offline, writes nothing."""
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

    excalibur = _fixture_frame('Excalibur', {'health': 270, 'shield': 270, 'armor': 240,
                                             'energy': 100, 'sprint_speed': 1})
    inaros = _fixture_frame('Inaros', {'health': 2110, 'shield': 0, 'armor': 240,
                                       'energy': 100, 'sprint_speed': 1})
    hildryn = _fixture_frame('Hildryn', {'health': 180, 'shield': 1280, 'armor': 315,
                                         'energy': 0, 'sprint_speed': 1})
    nidus = _fixture_frame('Nidus', {'health': 675, 'shield': 0, 'armor': 350,
                                     'energy': 100, 'sprint_speed': 1})

    r30 = calculate(excalibur, [], {'rank': 30})['stats']
    check('wiki: Excalibur 270 Health (370 at Rank 30)', near(r30['health'], 370),
          str(r30.get('health')))
    check('wiki: Excalibur 270 Shields (370 at Rank 30)', near(r30['shield'], 370))
    check('wiki: Excalibur 100 Energy (150 at Rank 30)', near(r30['energy'], 150))
    check('armor does not rank-scale on a default frame', near(r30['armor'], 240)
          and near(r30['armor_ranked'], 240))
    r0 = calculate(excalibur, [], {'rank': 0})['stats']
    check('rank 0 is the catalog value', near(r0['health'], 270) and near(r0['energy'], 100))
    r3 = calculate(excalibur, [], {'rank': 3})['stats']
    check('rank cadence: +10 Health (rank 1), +10 Shield (rank 2), +5 Energy (rank 3)',
          near(r3['health'], 280) and near(r3['shield'], 280) and near(r3['energy'], 105),
          '%s/%s/%s' % (r3['health'], r3['shield'], r3['energy']))

    check('wiki: Inaros 2110 Health (2310 at Rank 30)',
          near(calculate(inaros, [], {'rank': 30})['stats']['health'], 2310),
          str(calculate(inaros, [], {'rank': 30})['stats']['health']))
    check('wiki: Hildryn 1280 Shields (1780 at Rank 30)',
          near(calculate(hildryn, [], {'rank': 30})['stats']['shield'], 1780),
          str(calculate(hildryn, [], {'rank': 30})['stats']['shield']))
    n30 = calculate(nidus, [], {'rank': 30})
    check('wiki: Nidus 675 Health (775), 350 Armor (450) and +15% Ability Strength',
          near(n30['stats']['health'], 775) and near(n30['stats']['armor'], 450)
          and near(n30['stats']['ability_strength'], 115),
          str({k: n30['stats'][k] for k in ('health', 'armor', 'ability_strength')}))
    check('Nidus regeneration is refused by name',
          any(m['code'] == 'nidus_health_regeneration' for m in n30['unsupported']))
    n12 = calculate(nidus, [], {'rank': 12})['stats']
    check('Nidus rank 12 follows his documented step schedule (715/390/106/120)',
          near(n12['health'], 715) and near(n12['armor'], 390)
          and near(n12['ability_strength'], 106) and near(n12['energy'], 120),
          '%s/%s/%s/%s' % (n12['health'], n12['armor'], n12['ability_strength'],
                           n12['energy']))
    h10 = calculate(hildryn, [], {'rank': 10})
    check('an exception frame below rank 30 reports the interpolation',
          any(m['code'] == 'rank_bonus_approximation' for m in h10['unsupported']))

    vitality = _mod('Vitality', [['+%d%% Health' % round(100 * (i + 1) / 11.0)]
                                 for i in range(11)],
                    compat='Warframe', mtype='Warframe Mod', polarity='vazarin')
    steel = _mod('Steel Fiber', [['+%d%% Armor' % round(100 * (i + 1) / 11.0)]
                                 for i in range(11)],
                 compat='Warframe', mtype='Warframe Mod', polarity='vazarin')
    intensify = _mod('Intensify', [['+%d%% Ability Strength' % (5 * (i + 1))]
                                   for i in range(6)],
                     compat='Warframe', mtype='Warframe Mod')
    streamline = _mod('Streamline', [['+%d%% Ability Efficiency' % (5 * (i + 1))]
                                     for i in range(6)],
                      compat='Warframe', mtype='Warframe Mod', polarity='naramon')
    fleeting = _mod('Fleeting Expertise', [['+%d%% Ability Efficiency' % (10 * (i + 1))]
                                           for i in range(6)],
                    compat='Warframe', mtype='Warframe Mod', polarity='naramon')
    transient = _mod('Transient Fortitude', [['+%d%% Ability Strength' % (5 * (i + 1))]
                                             + ['-%d%% Ability Duration' % (3 * (i + 1))]
                                             for i in range(11)],
                     compat='Warframe', mtype='Warframe Mod', polarity='madurai')
    vitality10 = calculate(excalibur, [_slot(0, vitality, 10)], {'rank': 30})['stats']
    check('Vitality R10 (+100% Health since Update 27.2; was +440%) on a rank-30 '
          'Excalibur: 370 x 2 = 740',
          near(vitality10['health'], 740), str(vitality10.get('health')))
    check('mods apply at the CURRENT rank, not to the base only',
          near(vitality10['health_ranked'], 370) and near(vitality10['health_base'], 270))
    steel10 = calculate(excalibur, [_slot(0, steel, 10)], {'rank': 30})['stats']
    check('Steel Fiber R10 (+100% Armor since Update 27.2; was +110%): 240 x 2 = 480',
          near(steel10['armor'], 480), str(steel10.get('armor')))
    check('ability strength starts at 100% and takes percentage points',
          near(calculate(excalibur, [_slot(0, intensify, 5)], {'rank': 30})
               ['stats']['ability_strength'], 130))
    both = calculate(excalibur, [_slot(0, streamline, 5), _slot(1, fleeting, 5)],
                     {'rank': 30})['stats']
    check('efficiency is capped at 175% for display while the raw value is kept',
          near(both['ability_efficiency'], 190)
          and near(both['ability_efficiency_display'], 175),
          '%s / %s' % (both['ability_efficiency'], both['ability_efficiency_display']))
    check('energy cost multiplier floors at 25% (2 - 1.9 = 0.1 -> 0.25)',
          near(both['ability_cost_multiplier'], 0.25), str(both['ability_cost_multiplier']))
    tf = calculate(excalibur, [_slot(0, transient, 10)], {'rank': 30})['stats']
    check('negative duration is reported raw (100 + 55 strength, 100 - 33 duration)',
          near(tf['ability_strength'], 155) and near(tf['ability_duration'], 67),
          '%s / %s' % (tf['ability_strength'], tf['ability_duration']))
    print('\nwarframes selftest %s (%d checks, %d failed) - nothing written'
          % ('OK' if not failures else 'FAILED', counter[0], len(failures)))
    return 0 if not failures else 1
