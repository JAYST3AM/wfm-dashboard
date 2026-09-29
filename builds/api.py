#!/usr/bin/env python3
"""The one entry point a UI (or a script) uses: compute a build.

    from builds import api, data
    db = data.load()
    result = api.compute(build_dict, db)

`build_dict` is the brief's configuration representation (section 3) - deliberately not
tied to any DOM:

    {
      "config": "A",                       # A/B/C identifier, free-form
      "equipment_id": "/Lotus/Weapons/Tenno/Rifle/BratonPrime",
      "equipment_rank": 30,
      "orokin": true,                      # Reactor (frame) / Catalyst (weapon)
      "forma_count": 2,
      "mastery_rank": 12,
      "slots": [
        {"kind": "normal", "index": 0, "polarity": "madurai",
         "mod": {"id": "/Lotus/Upgrades/Mods/Rifle/WeaponDamageAmountMod", "rank": 10}},
        {"kind": "aura", "polarity": "naramon", "mod": {"id": "...", "rank": 5}},
        {"kind": "exilus", "polarity": null, "unlocked": true, "mod": null}
      ]
    }

compute() returns validation, the engine result, the merged unsupported markers and a
baseline (the same equipment unmodded) so a UI can render "before -> after" per stat
without a second call (brief section 18: preserve before/after comparison).
"""
from . import capacity as capacity_mod
from . import data as data_mod
from . import schema, unsupported as unsupported_mod, validation
from . import warframes as warframes_mod
from . import weapons as weapons_mod


def engine_slots(build, db):
    """Resolve a build's slots into the engine's shape: [{kind, index, polarity, rank,
    mod(row)}] in slot order. Unknown mods are returned in `errors`, never guessed."""
    slots, errors = [], []
    raw_slots = (build or {}).get('slots')
    if not isinstance(raw_slots, list):
        raw_slots = []
    for raw in raw_slots:
        if not isinstance(raw, dict):
            errors.append({'code': 'unknown_mod', 'message': 'slot entries must be '
                           'objects', 'severity': 'error', 'field': 'slots[]'})
            continue
        entry = {'kind': raw.get('kind') or schema.SLOT_NORMAL, 'index': raw.get('index'),
                 'polarity': raw.get('polarity'), 'mod': None, 'rank': None,
                 'unlocked': raw.get('unlocked')}
        if raw.get('mod'):
            row, rank, err = validation.resolve_mod(raw['mod'], db)
            if err:
                errors.append(err)
            else:
                entry['mod'] = row
                entry['rank'] = rank
        slots.append(entry)
    return slots, errors


def compute(build, db, options=None):
    """Validate + calculate one build. Never raises for a bad build."""
    opts = dict(options or {})
    kind_hint = None
    equipment, err = validation.resolve_equipment(build or {}, db)
    if equipment is not None:
        kind_hint = equipment.get('kind')
    report = validation.validate_build(build or {}, db)
    slots, slot_errors = engine_slots(build, db)
    for row in slot_errors:
        if row not in report['errors']:
            report['errors'].append(row)
            report['ok'] = False

    result, baseline = None, None
    if equipment is not None and report['ok']:
        engine = (warframes_mod if equipment.get('kind') == schema.EQUIP_WARFRAME
                  else weapons_mod)
        kwargs = {}
        if equipment.get('kind') == schema.EQUIP_WARFRAME:
            kwargs['options'] = {'rank': (build or {}).get('equipment_rank')}
        else:
            kwargs['options'] = {k: opts[k] for k in ('faction', 'quantize',
                                                      'trigger_override')
                                 if k in opts}
        result = engine.calculate(equipment, slots, **kwargs)
        baseline = engine.calculate(equipment, [], **kwargs)

    capacity = report.get('capacity')
    unsupported = list((result or {}).get('unsupported') or [])
    if result is not None:
        missing = unsupported_mod.check_coverage(unsupported)
        for code in missing:
            unsupported.append(unsupported_mod.marker(code))
    return {
        'ok': bool(result is not None),
        'build': _normalised(build, equipment),
        'equipment': ({'id': equipment.get('id'), 'name': equipment.get('name'),
                       'kind': equipment.get('kind')} if equipment else None),
        'validation': {'ok': report['ok'], 'errors': report['errors'],
                       'warnings': report['warnings']},
        'capacity': capacity,
        'capacity_used': (capacity or {}).get('drain', {}).get('total'),
        'capacity_remaining': (capacity or {}).get('drain', {}).get('remaining'),
        'result': result,
        'baseline': _baseline_stats(baseline),
        'unsupported': unsupported,
        'unsupported_registry': unsupported_mod.list_all() if opts.get('registry') else None,
    }


def explain(computed, stat):
    """The rendered trace text for one stat of a computed build (brief section 9)."""
    from . import trace as trace_mod
    result = (computed or {}).get('result') or {}
    traces = result.get('traces') or {}
    row = traces.get(stat)
    if row is None:
        return None
    return trace_mod.text(row)


def compare(build_a, build_b, db, options=None):
    """Two builds -> per-stat before/after, with the source of every change.

    This is the "why did this stat change?" primitive the brief wants for Phase 2+:
    stat, a_value, b_value, delta, and (when the traces name mods) the modifier rows
    that differ.
    """
    a = compute(build_a, db, options)
    b = compute(build_b, db, options)
    if not (a.get('result') and b.get('result')):
        return {'ok': False, 'a': a, 'b': b, 'diff': [],
                'reason': 'one of the builds does not compute'}
    left = (a['result'].get('stats') or {})
    right = (b['result'].get('stats') or {})
    diff = []
    for stat in sorted(set(left) | set(right)):
        av, bv = left.get(stat), right.get(stat)
        if av == bv:
            continue
        row = {'stat': stat, 'a': av, 'b': bv}
        if isinstance(av, (int, float)) and isinstance(bv, (int, float)):
            row['delta'] = round(float(bv) - float(av), 6)
        diff.append(row)
    return {'ok': True, 'diff': diff,
            'a': {'stats': left, 'capacity_used': a.get('capacity_used')},
            'b': {'stats': right, 'capacity_used': b.get('capacity_used')}}


def _normalised(build, equipment):
    """The build as the engine understood it (helps a UI debug what it sent)."""
    build = build or {}
    return {'config': build.get('config') or 'A',
            'equipment_id': (equipment or {}).get('id') or build.get('equipment_id'),
            'equipment_rank': build.get('equipment_rank'),
            'orokin': bool(build.get('orokin')), 'forma_count': build.get('forma_count'),
            'mastery_rank': build.get('mastery_rank'), 'slots': build.get('slots') or []}


def _baseline_stats(result):
    """The headline stats of an unmodded calculation (None when there is none)."""
    if not result:
        return None
    stats = dict(result.get('stats') or {})
    return {'stats': stats, 'capacity_used': 0}
