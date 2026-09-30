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
from . import conditions as conditions_mod
from . import data as data_mod
from . import schema, unsupported as unsupported_mod, validation
from . import warframes as warframes_mod
from . import weapons as weapons_mod


def engine_slots(build, db):
    """Resolve a build's slots into the engine's shape: [{kind, index, polarity, rank,
    mod(row)}] in slot order. Unknown mods are returned in `errors`, never guessed."""
    slots, errors = [], []
    raw_slots = (build if isinstance(build, dict) else {}).get('slots')
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
    # A malformed options block is not a build error and must not be a crash: it degrades to
    # 'no options given', which is the same answer a caller who passed nothing gets.
    opts = dict(options) if isinstance(options, dict) else {}
    # A build that is not an object is not a build: it is normalised before anything reads it, so
    # garbage in gives a structured refusal out (Phase 4: malformed input must not crash).
    build = validation.as_build(build)
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
            # Phase 4: the evaluation context and the two evaluation modes travel with the
            # options; nothing else about the Phase 1 call shape changes.
            kwargs['options'] = {k: opts[k] for k in ('faction', 'quantize',
                                                      'trigger_override', 'context',
                                                      'strict', 'hypothetical')
                                 if k in opts}
        result = engine.calculate(equipment, slots, **kwargs)
        baseline = engine.calculate(equipment, [], **kwargs)

    capacity = report.get('capacity')
    unsupported = list((result or {}).get('unsupported') or [])
    if result is not None:
        missing = unsupported_mod.check_coverage(unsupported)
        for code in missing:
            unsupported.append(unsupported_mod.marker(code))
    context = conditions_mod.normalise_context(opts.get('context'))
    # A stated input this engine cannot use is a refusal, not silence: the engine says what it
    # consumed, and anything left over is named here (with the fields it named).
    # An engine that has no condition model at all (the Warframe engine) must say so rather than
    # borrowing the weapon engine's vocabulary: the page printed "every number here is
    # unconditional" over a frame that was never evaluated (adversarial review F3).
    engine_evaluation = (result or {}).get('evaluation')
    evaluation = dict(engine_evaluation if isinstance(engine_evaluation, dict) else {
        'mode': 'not_evaluated', 'state': 'not_evaluated', 'engine_evaluated': False,
        'context_supplied': bool(context['supplied']),
        'context_ignored': list(context['ignored']), 'withheld': [], 'refused_stats': []})
    if isinstance(engine_evaluation, dict):
        evaluation['engine_evaluated'] = True
    unused = conditions_mod.unused_fields(context, evaluation.get('consumed'))
    if unused:
        evaluation['unused'] = unused
        if result is not None:
            result.setdefault('unsupported', []).append(unsupported_mod.marker(
                'context_unused',
                'the stated %s is not modelled for %s, so it was not used'
                % (' and '.join(unused), (equipment or {}).get('kind') or 'this equipment'),
                fields=unused, kind=(equipment or {}).get('kind'),
                condition=conditions_mod.context_unused_result(
                    unused, (equipment or {}).get('kind'), evaluation.get('consumed'))))
            unsupported = list(result.get('unsupported') or [])
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
        # Phase 4: the condition state and the evaluation kind, surfaced at the top level so a UI
        # reads them without walking into the engine result - and prints them as-is.
        'conditions': list((result or {}).get('conditions') or []),
        # Phase 5: the riders the engine considered against the stated buff state (each with its
        # state, stacks/uptime and contribution), so the page renders the engine's own answer.
        'riders': list((result or {}).get('riders') or []),
        'evaluation': evaluation,
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
            'a': _compare_side(a), 'b': _compare_side(b)}


def _compare_side(computed):
    """One side of a comparison: what the UI needs to render it without a second call."""
    return {'stats': (computed.get('result') or {}).get('stats') or {},
            'capacity_used': computed.get('capacity_used'),
            'capacity': computed.get('capacity'),
            'validation': computed.get('validation'),
            'unsupported': computed.get('unsupported') or [],
            'damage': (computed.get('result') or {}).get('damage') or {}}


def _normalised(build, equipment):
    """The build as the engine understood it (helps a UI debug what it sent)."""
    build = build or {}
    return {'config': build.get('config') or 'A',
            'equipment_id': (equipment or {}).get('id') or build.get('equipment_id'),
            'equipment_rank': build.get('equipment_rank'),
            # strict: the echo says what the engine read, and a truthy string is not True here
            # any more than it is in validation (Phase 5).
            'orokin': build.get('orokin') is True, 'forma_count': build.get('forma_count'),
            'mastery_rank': build.get('mastery_rank'), 'slots': build.get('slots') or []}


def _baseline_stats(result):
    """The headline stats of an unmodded calculation (None when there is none)."""
    if not result:
        return None
    stats = dict(result.get('stats') or {})
    return {'stats': stats, 'capacity_used': 0}
