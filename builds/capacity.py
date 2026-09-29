#!/usr/bin/env python3
"""Mod capacity engine: exactly what the arsenal's capacity number is made of.

Rules implemented (WARFRAME Wiki: Mods / Polarity / Aura - all quoted where they are
subtle, because these are the numbers players catch a planner getting wrong):

  capacity   = rank capacity (x2 with an Orokin Reactor/Catalyst) + aura/stance bonus
  rank cap.  = the item's rank (x2 when supercharged); an item below the player's Mastery
               Rank instead gets the minimum mod capacity: "15, plus 1 per 2 Mastery
               Ranks" (MR 6 -> 18), and "after Mastery Rank 30, minimum mod capacity
               increases by 1 per Legendary Rank" (so MR 31 -> 31, i.e. minimum == MR
               beyond 30). The wiki does not say whether a supercharger doubles that
               floor; its one worked example (MR 10, unranked, catalysed = 20) shows the
               floor undoubled, so this engine leaves it undoubled and sets
               capacity['floored_by_mastery'] when the floor is what decided the total.
  mod drain  = base drain + rank (every rank adds exactly 1; Serration 4 -> 14 at R10)
  polarity   = matching: drain halved ROUNDED UP (14 -> 7, 9 -> 5)
               mismatched: drain +25% rounded mathematically
                           (2-5 -> +1, 6-9 -> +2, 10-13 -> +3, 14-16 -> +4)
               neutral/vacant slot, or a mod with no polarity: drain unchanged
               universal slot (Omni/Aura Forma) or universal mod: always matching
               Umbra slot: matches only Umbra mods, and an Umbra mod is a mismatch
               anywhere else (Umbral mods cannot be Forma'd around)
  aura/stance= the mod's drain is a BONUS, not a cost: matching polarity doubles it,
               a vacant slot pays the listed drain, a mismatched polarity pays 80%
               (wiki pages disagree: the Aura and Polarity pages say 80%, the Mods page
               says a 25% reduction; this engine follows 80% and rounds mathematically)
  exilus     = an ordinary slot for capacity purposes: drain and polarity apply normally

Pure: takes dicts in, returns a full breakdown with a per-slot trace. No I/O.
"""
from . import schema

# Aura/stance mismatch multiplier: the wiki's Aura and Polarity pages both say 80% of
# the listed drain ("in a slot of a different polarity, the additional capacity is 80%
# of listed drain"); the Mods page words the same rule as a 25% reduction. 80% wins.
AURA_MISMATCH_FACTOR = 0.8
# Aura/stance match multiplier.
AURA_MATCH_FACTOR = 2.0
# Mismatched normal slot penalty.
MISMATCH_FACTOR = 1.25


def round_half_up(value):
    """The game's "rounded mathematically" for a positive value (0.5 -> 1)."""
    return int(value + 0.5) if value >= 0 else -int(-value + 0.5)


def minimum_capacity(mastery_rank):
    """The minimum mod capacity a low-rank item gets from the player's Mastery Rank.

    15 + 1 per 2 MR up to MR 30, then +1 per Legendary Rank (which makes it exactly the
    Mastery Rank beyond 30). Negative/hostile input is clamped to MR 0.
    """
    mr = max(0, int(mastery_rank or 0))
    if mr <= 30:
        return 15 + mr // 2
    return 15 + 15 + (mr - 30)


def mod_drain(base_drain, rank):
    """A mod's drain at a rank (base + rank). Accepts None base drain as 0."""
    return int(base_drain or 0) + int(rank or 0)


def polarity_rule(mod_polarity, slot_polarity):
    """Which of the four polarity situations applies to one slot."""
    if mod_polarity is None:
        return 'unpolarised_mod'
    if slot_polarity is None:
        return 'vacant'
    if slot_polarity == schema.POLARITY_UNIVERSAL or mod_polarity == schema.POLARITY_UNIVERSAL:
        return 'matching'
    if mod_polarity == slot_polarity:
        return 'matching'
    if mod_polarity == schema.POLARITY_UMBRA or slot_polarity == schema.POLARITY_UMBRA:
        # An Umbral polarity slot only matches Umbral mods and vice versa; everything
        # else is a mismatch (the game does not let Forma replace an Umbra polarity).
        return 'mismatched_umbra'
    return 'mismatched'


def slot_drain(raw_drain, mod_polarity, slot_polarity):
    """(adjusted drain, delta, rule) for one normal/exilus slot."""
    raw = int(raw_drain)
    rule = polarity_rule(mod_polarity, slot_polarity)
    if rule == 'matching':
        adjusted = (raw + 1) // 2                     # halved, rounded up (14 -> 7)
    elif rule in ('mismatched', 'mismatched_umbra'):
        adjusted = raw + round_half_up(raw * (MISMATCH_FACTOR - 1.0))
    else:
        adjusted = raw
    return adjusted, adjusted - raw, rule


def aura_bonus(raw_drain, mod_polarity, slot_polarity):
    """(bonus capacity, rule) a live Aura or Stance mod contributes (never a cost)."""
    raw = int(raw_drain or 0)
    rule = polarity_rule(mod_polarity, slot_polarity)
    if rule == 'matching':
        return int(round(raw * AURA_MATCH_FACTOR)), rule
    if rule in ('mismatched', 'mismatched_umbra'):
        return round_half_up(raw * AURA_MISMATCH_FACTOR), rule
    return raw, rule


def capacity_breakdown(equipment, slots, equipment_rank=None, orokin=False,
                       mastery_rank=0):
    """The full capacity picture for one build, traceable slot by slot.

    equipment: the ingested equipment row (needs `max_rank`, and the slot polarities
               the caller wants defaults for). `equipment_rank` defaults to max_rank.
    slots:     [{'kind': 'normal'|'aura'|'stance'|'exilus', 'index': int,
                 'polarity': str|None,
                 'mod': {'id','name','rank','base_drain','polarity','max_rank'} | None}]
               Aura/stance mods must be `kind: 'aura'`/`'stance'`; the engine refuses to
               guess (a normal mod in the aura slot is a validation error, not a bonus).

    Returns {'capacity': {...}, 'drain': {'per_slot': [...], 'total', 'remaining'},
             'trace': [...], 'notes': [...], 'errors': [...]} - errors are structured
    (see builds/validation.py) and do not stop the arithmetic, so a UI can show both.
    """
    equip = equipment or {}
    max_rank = equip.get('max_rank') or schema.MAX_RANK_WEAPON
    rank = max_rank if equipment_rank is None else int(equipment_rank)
    errors, notes, trace = [], [], []

    mr = max(0, int(mastery_rank or 0))
    rank_capacity = rank
    minimum = 0
    if rank < mr:
        # "Items also have a minimum mod capacity, which adds mod points onto items that
        # are a lower rank than a player's current Mastery Rank" (wiki: Mods).
        minimum = minimum_capacity(mr)
        notes.append('rank %d is below Mastery Rank %d: minimum mod capacity %d applies'
                     % (rank, mr, minimum))
    # The wiki states the floor but not whether a supercharger doubles it; the one worked
    # example (MR 10, unranked, catalysed = 20) shows the floor undoubled, so that is
    # what this engine does - flagged in `capacity['inferred']` rather than hidden.
    doubled = 2 * rank if orokin else rank
    inferred = bool(minimum and minimum > doubled)
    if inferred:
        notes.append('capacity %d comes from the Mastery Rank floor, which the wiki\'s '
                     'worked example leaves undoubled by the Orokin Catalyst/Reactor '
                     '(a supercharged rank-%d item would have %d)'
                     % (minimum, rank, doubled))
    if rank > max_rank:
        errors.append(_err('invalid_equipment_rank',
                           'equipment rank %d exceeds max rank %d' % (rank, max_rank),
                           field='equipment_rank'))

    aura_total = stance_total = 0
    per_slot, total_drain = [], 0
    for raw_slot in slots or []:
        kind = raw_slot.get('kind') or schema.SLOT_NORMAL
        index = raw_slot.get('index')
        slot_polarity = schema.norm_polarity(raw_slot.get('polarity'))
        mod = raw_slot.get('mod')
        entry = {'kind': kind, 'index': index, 'polarity': slot_polarity,
                 'mod': (mod or {}).get('id'), 'mod_name': (mod or {}).get('name'),
                 'mod_polarity': None, 'raw_drain': 0, 'adjusted_drain': 0,
                 'adjustment': 0, 'rule': None, 'contribution': 0}
        if kind not in schema.SLOT_KINDS:
            errors.append(_err('invalid_slot_kind', 'unknown slot kind %r' % (kind,),
                               field='slots[].kind'))
        if not mod:
            entry['rule'] = 'empty'
            per_slot.append(entry)
            continue
        mod_rank = mod.get('rank')
        mod_max = mod.get('max_rank')
        if mod_max is not None and mod_rank is not None and mod_rank > mod_max:
            errors.append(_err('rank_exceeds_max',
                               '%s at rank %s exceeds its max rank %s'
                               % (mod.get('name') or mod.get('id'), mod_rank, mod_max),
                               field='slots[].mod.rank', mod=mod.get('id')))
        raw_drain = mod_drain(mod.get('base_drain'), mod_rank)
        mod_polarity = schema.norm_polarity(mod.get('polarity'))
        entry.update({'mod_polarity': mod_polarity, 'raw_drain': raw_drain})
        if kind == schema.SLOT_AURA:
            bonus, rule = aura_bonus(raw_drain, mod_polarity, slot_polarity)
            aura_total += bonus
            entry.update({'rule': rule, 'adjusted_drain': -bonus,
                          'adjustment': -bonus, 'contribution': bonus})
            trace.append('%s slot: %s R%s contributes +%d capacity (%s)'
                         % (kind, entry['mod_name'] or entry['mod'], mod_rank, bonus,
                            rule))
        elif kind == schema.SLOT_STANCE:
            bonus, rule = aura_bonus(raw_drain, mod_polarity, slot_polarity)
            stance_total += bonus
            entry.update({'rule': rule, 'adjusted_drain': -bonus,
                          'adjustment': -bonus, 'contribution': bonus})
            trace.append('%s slot: %s R%s contributes +%d capacity (%s)'
                         % (kind, entry['mod_name'] or entry['mod'], mod_rank, bonus,
                            rule))
        else:
            adjusted, delta, rule = slot_drain(raw_drain, mod_polarity, slot_polarity)
            total_drain += adjusted
            entry.update({'rule': rule, 'adjusted_drain': adjusted, 'adjustment': delta,
                          'contribution': -adjusted})
            trace.append('slot %s: %s R%s drains %d (raw %d, %s%s)'
                         % (index, entry['mod_name'] or entry['mod'], mod_rank,
                            adjusted, raw_drain, rule,
                            '' if delta == 0 else ', %+d' % delta))
        per_slot.append(entry)

    aura_stance = aura_total + stance_total
    # The floor can exceed the (possibly supercharged) rank capacity on a low-rank item.
    capacity_total = max(doubled, minimum) + aura_stance
    remaining = capacity_total - total_drain
    if remaining < 0:
        errors.append(_err('capacity_exceeded',
                           'drain %d exceeds capacity %d by %d'
                           % (total_drain, capacity_total, -remaining),
                           field='slots'))
    return {
        'capacity': {
            'equipment_rank': rank, 'max_rank': max_rank,
            'mastery_rank': mr, 'minimum_from_mastery': minimum,
            'rank_capacity': rank_capacity, 'orokin_doubled': bool(orokin),
            'doubled_capacity': doubled, 'aura_bonus': aura_total,
            'stance_bonus': stance_total, 'total': capacity_total,
            'floored_by_mastery': inferred,
        },
        'drain': {'per_slot': per_slot, 'total': total_drain, 'remaining': remaining},
        'trace': trace, 'notes': notes, 'errors': errors,
    }


def _err(code, message, **extra):
    out = {'code': code, 'message': message, 'severity': 'error'}
    out.update(extra)
    return out


def capacity_check(equipment, slots, **kwargs):
    """Just the headline numbers: (capacity_total, drain_total, remaining)."""
    out = capacity_breakdown(equipment, slots, **kwargs)
    return (out['capacity']['total'], out['drain']['total'],
            out['drain']['remaining'])


def selftest():
    """The capacity rules from the wiki's Mods / Polarity / Aura pages. Offline."""
    failures = []

    counter = [0]

    def check(label, ok, detail=''):
        counter[0] += 1
        print('%s  %s%s' % ('PASS' if ok else 'FAIL', label,
                            '' if ok else ' -- %s' % detail))
        if not ok:
            failures.append(label)

    check('mod drain = base + rank (Serration 4 -> 14 at R10)', mod_drain(4, 10) == 14)
    check('matching polarity halves, rounded up (wiki: 14 -> 7)',
          slot_drain(14, 'madurai', 'madurai')[0] == 7)
    check('matching polarity halves, rounded up (9 -> 5)',
          slot_drain(9, 'madurai', 'madurai')[0] == 5)
    for drain, delta in ((1, 0), (2, 1), (5, 1), (6, 2), (9, 2), (10, 3), (14, 4), (16, 4)):
        got = slot_drain(drain, 'madurai', 'naramon')[0]
        check('mismatched polarity: drain %d -> %d (wiki table +%d)'
              % (drain, drain + delta, delta), got == drain + delta, str(got))
    check('a neutral slot leaves the drain alone', slot_drain(9, 'madurai', None)[0] == 9)
    check('a polarised slot with a polarity-less mod is neutral',
          slot_drain(9, None, 'madurai')[0] == 9)
    check('a universal slot always matches', slot_drain(9, 'madurai', 'universal')[0] == 5)
    check('an Umbra mod only matches an Umbra slot',
          slot_drain(10, 'umbra', 'umbra')[0] == 5
          and slot_drain(10, 'umbra', 'madurai')[0] == 13)
    check('minimum mod capacity: MR 6 -> 18', minimum_capacity(6) == 18)
    check('minimum mod capacity: MR 30 -> 30', minimum_capacity(30) == 30)
    check('minimum mod capacity: MR 34 (LR4) -> 34', minimum_capacity(34) == 34)
    check('aura, matching polarity: 9 -> 18', aura_bonus(9, 'naramon', 'naramon')[0] == 18)
    check('aura, mismatched polarity: 9 -> 7 (80%)',
          aura_bonus(9, 'naramon', 'madurai')[0] == 7)
    check('aura, vacant slot: 9 -> 9', aura_bonus(9, 'naramon', None)[0] == 9)

    weapon = {'max_rank': 30, 'kind': 'primary'}
    serration = {'id': 's', 'name': 'Serration', 'rank': 10, 'base_drain': 4,
                 'polarity': 'madurai'}
    out = capacity_breakdown(weapon, [{'kind': 'normal', 'index': 0,
                                       'polarity': 'madurai', 'mod': serration}],
                             equipment_rank=30, orokin=True, mastery_rank=30)
    check('rank 30 + Orokin Catalyst = 60 capacity', out['capacity']['total'] == 60,
          str(out['capacity']))
    check('Serration R10 in a matching slot costs 7 drain', out['drain']['total'] == 7,
          str(out['drain']))
    out = capacity_breakdown(weapon, [], equipment_rank=0, orokin=True, mastery_rank=30)
    check('rank 0 on an MR 30 account: the 30-point Mastery floor applies (undoubled)',
          out['capacity']['total'] == 30 and out['capacity']['floored_by_mastery'],
          str(out['capacity']))
    out = capacity_breakdown(weapon, [], equipment_rank=0, orokin=True, mastery_rank=10)
    check('wiki worked example: MR 10, unranked, catalysed -> 20 capacity',
          out['capacity']['total'] == 20, str(out['capacity']))
    out = capacity_breakdown(weapon, [], equipment_rank=30, orokin=True, mastery_rank=30)
    check('rank 30 + Catalyst on an MR 30 account -> 60 (the rank wins over the floor)',
          out['capacity']['total'] == 60 and not out['capacity']['floored_by_mastery'],
          str(out['capacity']))
    out = capacity_breakdown(weapon, [], equipment_rank=12, orokin=False, mastery_rank=0)
    check('rank 12 item, no Catalyst = 12 capacity', out['capacity']['total'] == 12,
          str(out['capacity']))
    frame = {'max_rank': 30, 'kind': 'warframe', 'aura_polarity': 'naramon'}
    aura = {'id': 'a', 'name': 'Rifle Amp', 'rank': 5, 'base_drain': 4,
            'polarity': 'madurai'}
    stance = {'id': 't', 'name': 'Stance', 'rank': 3, 'base_drain': 4,
              'polarity': 'naramon'}
    out = capacity_breakdown(frame, [{'kind': 'aura', 'index': None,
                                      'polarity': 'naramon', 'mod': aura}],
                             equipment_rank=30, orokin=True, mastery_rank=30)
    check('frame: 60 + a mismatched aura\'s 7 = 67', out['capacity']['total'] == 67,
          str(out['capacity']))
    melee = {'max_rank': 30, 'kind': 'melee', 'stance_polarity': 'naramon'}
    out = capacity_breakdown(melee, [{'kind': 'stance', 'index': None,
                                      'polarity': 'naramon', 'mod': stance}],
                             equipment_rank=30, orokin=False, mastery_rank=0)
    check('melee: 30 + a matching stance\'s 14 (drain 7 doubled) = 44',
          out['capacity']['total'] == 44, str(out['capacity']))
    big = [{'kind': 'normal', 'index': i, 'polarity': 'madurai',
            'mod': {'id': 'm%d' % i, 'name': 'Big %d' % i, 'rank': 10,
                    'base_drain': 10, 'polarity': 'madurai'}} for i in range(8)]
    out = capacity_breakdown(weapon, big, equipment_rank=0, orokin=False, mastery_rank=0)
    check('an impossible build reports capacity_exceeded instead of crashing',
          any(e['code'] == 'capacity_exceeded' for e in out['errors']),
          str([e['code'] for e in out['errors']]))
    print('\ncapacity selftest %s (%d checks, %d failed) - nothing written'
          % ('OK' if not failures else 'FAILED', counter[0], len(failures)))
    return 0 if not failures else 1
