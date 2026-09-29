#!/usr/bin/env python3
"""Explainable calculation: the trace primitives every engine returns.

The brief (section 9): every calculated stat must be able to answer "why is this
number this number?" - base value, each modifier with its source mod and rank, the
intermediate result and the final result - for tooltips, "why did this stat change?",
build comparison and debugging.

Design
  * A `Trace` is a plain dict so it can be JSON-serialised straight into a future API.
  * The engines build traces *while* calculating; nothing is reconstructed afterwards.
  * `Trace.text()` renders the brief's worked-example format:

        Critical Chance
        Base: 12%
        Point Strike R5: +150% of base
        Final: 30%
"""

RENDER_PRECISION = 4          # decimals kept when a value is not integral


def _num(value):
    """Trim a float for display: integers stay integers, everything else 4 decimals."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int,)):
        return value
    if isinstance(value, float):
        if value != value or value in (float('inf'), float('-inf')):   # NaN / inf
            return value
        if float(value).is_integer():
            return int(value)
        return round(float(value), RENDER_PRECISION)
    return value


def modifier(source, category, value, unit='percent', mod=None, mod_name=None,
             rank=None, note=None, **extra):
    """One modifier step: what a single mod (or system) contributed to a stat.

    `category` is the stacking class - 'base' (additive with other base bonuses),
    'elemental', 'physical', 'faction' (a separate multiplier, applied last),
    'flat' (added after every multiplier), or 'set' (a mod-set bonus).
    """
    out = {'source': source, 'category': category, 'value': _num(value), 'unit': unit}
    if mod is not None:
        out['mod'] = mod
    if mod_name is not None:
        out['mod_name'] = mod_name
    if rank is not None:
        out['rank'] = rank
    if note:
        out['note'] = note
    out.update(extra)
    return out


def trace(stat, base, unit='percent', label=None):
    """Start a trace for one stat: the base value plus the modifier list."""
    return {'stat': stat, 'label': label or stat.replace('_', ' ').title(),
            'base': _num(base), 'unit': unit, 'modifiers': [], 'intermediate': None,
            'final': None, 'notes': []}


def add(t, modifier_row, intermediate=None):
    """Append a modifier and (optionally) the running value after it was applied."""
    t['modifiers'].append(modifier_row)
    if intermediate is not None:
        t['intermediate'] = _num(intermediate)
    return t


def note(t, text):
    """Attach a human-readable note (an assumption, a cap, a refusal)."""
    t['notes'].append(str(text))
    return t


def finish(t, final, intermediate=None):
    """Close a trace with its final value."""
    t['final'] = _num(final)
    if intermediate is not None:
        t['intermediate'] = _num(intermediate)
    return t


def value(t):
    """The final value of a trace, or its base when it was never finished."""
    return t['final'] if t['final'] is not None else t['base']


def fmt_number(value, unit='percent'):
    """Display helper: 62.5 -> '62.5%', 1.0833 -> '1.083'. Same trimming as _num."""
    if value is None:
        return 'n/a'
    num = _num(value)
    return '%s%%' % num if unit == 'percent' else str(num)


def text(t, indent=''):
    """Render one trace in the brief's worked-example format (section 9).

        Critical Chance
        Base: 12%
        Point Strike R5: +150% of base
        Final: 30%
    """
    lines = [indent + str(t.get('label') or t['stat'])]
    lines.append(indent + 'Base: %s' % fmt_number(t.get('base'), t.get('unit')))
    for m in t.get('modifiers', []):
        src = m.get('source') or '?'
        if m.get('mod_name'):
            src += ' %s' % m['mod_name']
        if m.get('rank') is not None:
            src += ' R%s' % m['rank']
        amount = str(fmt_number(m.get('value'), m.get('unit')))
        if not amount.startswith('-'):
            amount = '+' + amount
        shape = amount if m.get('category') == 'flat' else '%s of base' % amount
        line = '%s%s: %s' % (indent, src, shape)
        if m.get('note'):
            line += ' (%s)' % m['note']
        lines.append(line)
    if t.get('final') is not None:
        lines.append(indent + 'Final: %s' % fmt_number(t['final'], t.get('unit')))
    for n in t.get('notes', []):
        lines.append(indent + 'Note: %s' % n)
    return '\n'.join(lines)


def text_all(traces, indent=''):
    """Render a list of traces, one block each."""
    return '\n'.join(text(t, indent=indent) for t in traces)


def compact(t, mods=True):
    """A JSON-friendly summary of a trace: base, final, and the modifier sources.

    `mods=False` keeps the final numbers only (for list rendering).
    """
    out = {'stat': t['stat'], 'label': t.get('label'), 'base': t.get('base'),
           'final': t.get('final'), 'unit': t.get('unit')}
    if t.get('notes'):
        out['notes'] = list(t['notes'])
    if mods:
        out['modifiers'] = [dict(m) for m in t.get('modifiers', [])]
        out['intermediate'] = t.get('intermediate')
    return out
