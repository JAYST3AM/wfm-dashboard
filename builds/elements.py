#!/usr/bin/env python3
"""Elemental combination: mod placement hierarchy -> the damage types a weapon deals.

The rules this implements (WARFRAME Wiki: Damage, Calculating Bonuses) - all of them
verified against the wiki rather than assumed, because "the math must math":

1. Mod placement decides the hierarchy: slots are read left to right, top row then
   bottom row (our slot index 0..7 is already that order).
2. Each element enters the list in that order. An element that is already in the list
   MERGES with itself: "If multiple mods of the same element are added, only the first
   is used when making combinations" - the second Heat mod of an Amprex/Hellfire/Cryo
   build simply increases the Blast amount.
3. Two different primary elements that can combine do combine (Heat+Cold=Blast, ...),
   at the position of the earlier of the two. A combined element never combines again.
4. A mod that grants a combined element (Blast, Viral, ...) passes straight through.
5. Innate (weapon) elemental damage is considered LAST, with two documented
   exceptions Phase 1 handles explicitly:
     * if a mod carries the same element as an innate element, the innate damage merges
       into that mod's position ("equipping Stormbringer on an Amprex moves its innate
       Electricity to the front of the hierarchy");
     * an innate SECONDARY element (Hema's innate Viral) is a documented special case
       that the registry flags as not modelled - the pass-through result is still
       computed, but the unsupported marker rides along so nothing is silent.
6. Leftovers stay standalone: whatever never combined is its own damage type.

The engines return the final composition (amount per damage type), not just a total,
because the brief asks for the composition - proc weighting and enemy modifiers are
later phases building on exactly this.
"""
from . import schema


def element_entry(element, amount, source='mod', slot=None, mod=None, mod_name=None,
                  rank=None, note=None):
    """One damage-type contribution entering the combination order."""
    row = {'element': element, 'amount': float(amount or 0.0), 'source': source}
    if slot is not None:
        row['slot'] = slot
    if mod is not None:
        row['mod'] = mod
    if mod_name is not None:
        row['mod_name'] = mod_name
    if rank is not None:
        row['rank'] = rank
    if note:
        row['note'] = note
    return row


def group_by_element(entries):
    """Merge same-element entries into one group per element, at first-occurrence order.

    This is rule 2 above and it is what makes [Heat, Cold, Heat] a Blast + the two Heat
    mods' worth of Heat (not a second standalone Heat).
    """
    order = []
    groups = {}
    for entry in entries:
        element = entry.get('element')
        if element is None:
            continue
        if element not in groups:
            groups[element] = {'element': element, 'amount': 0.0, 'sources': [],
                               'first_index': len(order)}
            order.append(element)
        group = groups[element]
        group['amount'] += float(entry.get('amount') or 0.0)
        group['sources'].append(entry)
    return [groups[e] for e in order]


def combine(entries):
    """The full elemental-combination pass over ordered entries -> composition + trace.

    Returns:
        {'types': [{'element', 'amount', 'sources', 'combined_from'|None, 'standalone'}],
         'order': [element, ...],                 # arsenal-style display order
         'trace': [step, ...],                    # every merge / combine / finalise
         'notes': [...]}
    """
    groups = group_by_element(entries)
    trace = []
    for group in groups:
        if len(group['sources']) > 1:
            trace.append({'stage': 'merge', 'element': group['element'],
                          'amount': _round(group['amount']),
                          'merged': [s.get('mod_name') or s.get('source')
                                     for s in group['sources']]})

    finals = []
    pending = None
    for group in groups:
        element = group['element']
        if element in schema.SECONDARY_ELEMENTS:
            # Rule 4: a combined element passes straight through.
            if pending is not None:
                finals.append(_finalise(pending, standalone=True))
                trace.append({'stage': 'finalise', 'element': pending['element'],
                              'amount': _round(pending['amount']),
                              'why': 'standalone: a combined element cannot combine'})
                pending = None
            finals.append(_finalise(group, standalone=True))
            trace.append({'stage': 'passthrough', 'element': element,
                          'amount': _round(group['amount']),
                          'why': 'mod-granted combined element'})
            continue
        if pending is None:
            pending = dict(group)
            continue
        combo = schema.combined_element(pending['element'], element)
        if combo:
            total = pending['amount'] + group['amount']
            combined = {'element': combo, 'amount': total,
                        'sources': pending['sources'] + group['sources'],
                        'combined_from': [pending['element'], element],
                        'first_index': pending['first_index']}
            finals.append(_finalise(combined, standalone=True))
            trace.append({'stage': 'combine', 'element': combo, 'amount': _round(total),
                          'from': [pending['element'], element],
                          'slots': [s.get('slot') for s in combined['sources']
                                    if s.get('slot') is not None]})
            pending = None
        else:
            finals.append(_finalise(pending, standalone=True))
            trace.append({'stage': 'finalise', 'element': pending['element'],
                          'amount': _round(pending['amount']),
                          'why': 'no combination with %s' % element})
            pending = dict(group)
    if pending is not None:
        finals.append(_finalise(pending, standalone=True))
        trace.append({'stage': 'finalise', 'element': pending['element'],
                      'amount': _round(pending['amount']), 'why': 'end of list'})

    notes = []
    return {'types': finals, 'order': [f['element'] for f in finals], 'trace': trace,
            'notes': notes}


def _finalise(group, standalone):
    amount = float(group.get('amount') or 0.0)
    return {'element': group['element'], 'amount': _round(amount),
            'sources': list(group.get('sources') or []),
            'combined_from': group.get('combined_from'),
            'standalone': bool(standalone)}


def _round(value):
    f = float(value)
    return int(f) if f.is_integer() else round(f, 4)


def amount_of(composition, element):
    """The amount of one damage type in a composition result (0.0 when absent)."""
    for row in composition.get('types') or []:
        if row['element'] == element:
            return float(row['amount'])
    return 0.0


def total(composition):
    """Sum of every damage type in a composition."""
    return _round(sum(float(r['amount']) for r in composition.get('types') or []))


def innate_entries(damage_map, note=None):
    """Elements a weapon deals innately -> ordered entries (first = the export's order).

    `damage_map` is {type: value} from the ingested equipment row. Only elemental types
    produce entries; physical damage is handled by the weapon engine, not by the
    combination pass.
    """
    out = []
    for element in schema.PRIMARY_ELEMENTS + schema.SECONDARY_ELEMENTS:
        value = float((damage_map or {}).get(element) or 0.0)
        if value > 0:
            out.append(element_entry(element, value, source='innate',
                                     note=note or 'innate elemental damage'))
    return out


def apply_innate_rules(mod_entries, innate):
    """Place innate entries into the mod order per rules 5a/5b, returning (entries, notes).

    * an innate element that a mod also carries merges into that mod's entry (so the
      innate damage lands at the mod's position);
    * everything left over is appended at the end (innate damage is last);
    * an innate secondary element is flagged, not silently merged.
    """
    notes = []
    entries = [dict(e) for e in mod_entries]
    leftovers = []
    by_element = {}
    for entry in entries:
        by_element.setdefault(entry['element'], entry)
    for innate_entry in innate:
        element = innate_entry['element']
        if element in by_element:
            target = by_element[element]
            target['amount'] = float(target.get('amount') or 0.0) + \
                float(innate_entry['amount'])
            trace_note = 'innate %s merged at slot %s' % (element, target.get('slot'))
            target['note'] = trace_note
            notes.append(trace_note)
            continue
        if element in schema.SECONDARY_ELEMENTS:
            notes.append('innate secondary element (%s) passes through without '
                         'combining - documented special case, marked unsupported'
                         % element)
        leftovers.append(innate_entry)
    entries.extend(leftovers)
    return entries, notes


def selftest():
    """The wiki's own worked examples, checked offline. Writes nothing."""
    failures = []

    counter = [0]

    def check(label, ok, detail=''):
        counter[0] += 1
        print('%s  %s%s' % ('PASS' if ok else 'FAIL', label,
                            '' if ok else ' -- %s' % detail))
        if not ok:
            failures.append(label)

    def comp(*specs):
        return combine([element_entry(el, amt, source='mod', slot=i)
                        for i, (el, amt) in enumerate(specs)])

    check('cold + heat -> blast (200)',
          comp(('cold', 100), ('heat', 100))['order'] == ['blast']
          and amount_of(comp(('cold', 100), ('heat', 100)), 'blast') == 200)
    for a, b, expect in (('electricity', 'toxin', 'corrosive'), ('heat', 'toxin', 'gas'),
                         ('cold', 'electricity', 'magnetic'),
                         ('electricity', 'heat', 'radiation'),
                         ('cold', 'toxin', 'viral')):
        got = comp((a, 100), (b, 100))['order']
        check('%s + %s -> %s' % (a, b, expect), got == [expect], str(got))
    got = comp(('heat', 100), ('cold', 100), ('toxin', 100))
    check('heat, cold, toxin -> blast + toxin (slot order decides the pair)',
          got['order'] == ['blast', 'toxin'] and amount_of(got, 'toxin') == 100,
          str(got['order']))
    got = comp(('toxin', 100), ('cold', 100), ('heat', 100))
    check('toxin, cold, heat -> viral + heat', got['order'] == ['viral', 'heat'],
          str(got['order']))
    got = comp(('heat', 60), ('cold', 100), ('heat', 40))
    check('a repeated element merges into its first group (blast 200, no second heat)',
          got['order'] == ['blast'] and amount_of(got, 'blast') == 200 and total(got) == 200,
          str(got['order']))
    got = comp(('radiation', 100), ('toxin', 100))
    check('a mod-granted combined element passes through the order',
          got['order'] == ['radiation', 'toxin'], str(got['order']))
    got = comp(('heat', 100), ('toxin', 100), ('cold', 100))
    check('gas forms first, then cold stands alone (blast needs a free cold)',
          got['order'] == ['gas', 'cold'], str(got['order']))

    innate = innate_entries({'electricity': 100})
    entries, _notes = apply_innate_rules(
        [element_entry('heat', 90, source='mod', slot=0, mod_name='Hellfire'),
         element_entry('cold', 90, source='mod', slot=1, mod_name='Cryo Rounds')], innate)
    got = combine(entries)
    check('wiki Amprex example: innate electricity + heat + cold -> blast + electricity',
          got['order'] == ['blast', 'electricity']
          and amount_of(got, 'electricity') == 100 and amount_of(got, 'blast') == 180,
          '%s %s' % (got['order'], [r['amount'] for r in got['types']]))
    innate = innate_entries({'heat': 50})
    entries, _notes = apply_innate_rules(
        [element_entry('heat', 90, source='mod', slot=0, mod_name='Hellfire')], innate)
    got = combine(entries)
    check('an innate element of the same type merges into the mod group (90 + 50)',
          got['order'] == ['heat'] and amount_of(got, 'heat') == 140, str(got['order']))
    innate = innate_entries({'viral': 50})
    entries, notes = apply_innate_rules([element_entry('toxin', 40, source='mod', slot=0)],
                                        innate)
    got = combine(entries)
    check('an innate secondary element passes through and is flagged',
          got['order'] == ['toxin', 'viral'] and any('secondary' in n for n in notes),
          str(got['order']))
    print('\nelements selftest %s (%d checks, %d failed) - nothing written'
          % ('OK' if not failures else 'FAILED', counter[0], len(failures)))
    return 0 if not failures else 1
