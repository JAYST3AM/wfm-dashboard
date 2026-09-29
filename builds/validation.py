#!/usr/bin/env python3
"""Structured build validation: reject impossible builds cleanly (brief section 13).

Returns errors and warnings - never raises, never half-applies. Codes:

    unknown_equipment        the equipment id/slug is not in the database
    unknown_mod              a slot names a mod the database does not have
    incompatible_mod_type    the mod cannot go on this equipment kind at all
    normal_in_aura_slot      a normal mod in the Aura slot
    aura_in_normal_slot      an Aura mod in a normal slot
    stance_in_normal_slot    a Stance mod outside the Stance slot
    stance_on_non_melee      a Stance mod on equipment that has no Stance slot
    mod_not_exilus           a non-Exilus mod in an Exilus slot
    exilus_not_unlocked      a mod in an Exilus slot that is not unlocked
    duplicate_slot           two slots with the same (kind, index)
    invalid_slot_index       slot index outside 0..7 (normal) or a bad kind
    invalid_polarity         a slot polarity that is not a known polarity
    invalid_rank             a rank that is not a non-negative integer
    rank_exceeds_max         a mod rank above its own max rank
    duplicate_mod            the same mod installed twice (only one copy may be)
    capacity_exceeded        the build does not fit (from the capacity engine)
    invalid_equipment_rank   equipment rank above its max rank
    mod_slot_kind_mismatch   aura/stance mod kinds not matching their slot kind

Warnings (allowed, but surfaced): mastery rank below the item requirement, unmodelled
mod effects, negative ability efficiency, DPS withheld for exotic triggers.
"""
from . import capacity as capacity_mod
from . import effects as effects_mod
from . import schema


def error(code, message, **extra):
    out = {'code': code, 'message': message, 'severity': 'error'}
    out.update(extra)
    return out


def warning(code, message, **extra):
    out = {'code': code, 'message': message, 'severity': 'warning'}
    out.update(extra)
    return out


def resolve_equipment(build, db):
    """The build's equipment row, or (None, error) when it cannot be resolved."""
    key = build.get('equipment_id') or build.get('equipment') or build.get('equipment_slug')
    if not key:
        return None, error('unknown_equipment', 'the build names no equipment',
                           field='equipment_id')
    row = (db.get('equipment') or {}).get(key)
    if row is None:
        for candidate in (db.get('equipment') or {}).values():
            if candidate.get('slug') == key:
                row = candidate
                break
    if row is None:
        return None, error('unknown_equipment', 'no equipment with id/slug %r' % (key,),
                           field='equipment_id')
    return row, None


def resolve_mod(ref, db):
    """A slot's mod reference -> (row, rank) or (None, error).

    Accepts {'id': uniqueName, 'rank': n} / {'slug': ...} / {'name': ...}; the id is the
    canonical key (brief section 1: reuse existing canonical ids).
    """
    if not isinstance(ref, dict):
        return None, None, error('unknown_mod', 'a slot\'s mod must be an object',
                                 field='slots[].mod')
    rank = ref.get('rank')
    key = ref.get('id') or ref.get('slug') or ref.get('name')
    if not key:
        return None, None, error('unknown_mod', 'a slot\'s mod names no id', field='slots[].mod')
    row = (db.get('mods') or {}).get(key)
    if row is None:
        for candidate in (db.get('mods') or {}).values():
            if candidate.get('slug') == key or candidate.get('name') == key:
                row = candidate
                break
    if row is None:
        return None, None, error('unknown_mod', 'no mod with id/slug/name %r' % (key,),
                                 mod=key, field='slots[].mod.id')
    if rank is None:
        rank = row.get('max_rank')
    if isinstance(rank, bool) or not isinstance(rank, int) or rank < 0:
        return row, None, error('invalid_rank', '%s: rank %r is not a valid rank'
                                % (row.get('name'), rank), mod=row.get('id'),
                                field='slots[].mod.rank')
    if row.get('max_rank') is not None and rank > row['max_rank']:
        return row, rank, error('rank_exceeds_max',
                                '%s: rank %s is above its max rank %s'
                                % (row.get('name'), rank, row['max_rank']),
                                mod=row.get('id'), field='slots[].mod.rank')
    return row, rank, None


def validate_build(build, db, max_errors=50):
    """Validate one build against the database -> {'ok', 'errors', 'warnings'}.

    `build` is the brief's configuration shape (see docs/build-planner.md):
    equipment id, rank, Orokin state, Forma count, slot polarities and ordered slots.
    """
    errors, warnings = [], []
    build = build or {}
    equipment, err = resolve_equipment(build, db)
    if err:
        return {'ok': False, 'errors': [err], 'warnings': warnings}
    kind = equipment.get('kind')
    allowed_kinds = schema.EQUIP_SLOT_KINDS.get(kind, (schema.SLOT_NORMAL,))

    seen_slots = set()
    seen_mods = {}
    resolved_slots = []
    raw_slots = build.get('slots')
    if raw_slots is not None and not isinstance(raw_slots, list):
        errors.append(error('invalid_slot_index', 'slots must be a list',
                            field='slots'))
        raw_slots = []
    for raw in raw_slots or []:
        if not isinstance(raw, dict):
            errors.append(error('invalid_slot_index', 'every slot must be an object',
                                field='slots'))
            continue
        slot_kind = raw.get('kind') or schema.SLOT_NORMAL
        index = raw.get('index')
        if slot_kind not in schema.SLOT_KINDS:
            errors.append(error('invalid_slot_index',
                                'unknown slot kind %r' % (slot_kind,), field='slots[].kind'))
            continue
        if slot_kind == schema.SLOT_NORMAL and not (isinstance(index, int)
                                                    and 0 <= index < schema.NORMAL_SLOTS):
            errors.append(error('invalid_slot_index',
                                'normal slot index %r is outside 0..%d'
                                % (index, schema.NORMAL_SLOTS - 1),
                                field='slots[].index'))
            continue
        if slot_kind != schema.SLOT_NORMAL and index is not None:
            errors.append(error('invalid_slot_index',
                                '%s slots take no index (got %r)' % (slot_kind, index),
                                field='slots[].index'))
        key = (slot_kind, index)
        if key in seen_slots:
            errors.append(error('duplicate_slot',
                                'slot %s/%s appears more than once' % (slot_kind, index),
                                field='slots'))
        seen_slots.add(key)
        if slot_kind not in allowed_kinds:
            errors.append(error('mod_slot_kind_mismatch',
                                '%s has no %s slot' % (equipment.get('name'), slot_kind),
                                field='slots[].kind'))
        polarity = raw.get('polarity')
        if polarity is not None and schema.norm_polarity(polarity) is None \
                and str(polarity).strip().lower() not in ('aura', 'none', ''):
            errors.append(error('invalid_polarity', 'slot polarity %r is not a known '
                                'polarity' % (polarity,), field='slots[].polarity'))
        slot_mod, rank, mod_err = (None, None, None)
        if raw.get('mod'):
            slot_mod, rank, mod_err = resolve_mod(raw['mod'], db)
            if mod_err:
                errors.append(mod_err)
        if slot_mod is not None:
            mod_slot_class = effects_mod.slot_class(slot_mod)
            if slot_kind == schema.SLOT_AURA and mod_slot_class != schema.SLOT_AURA:
                errors.append(error('normal_in_aura_slot',
                                    '%s is not an Aura mod' % slot_mod.get('name'),
                                    mod=slot_mod.get('id'), field='slots[].mod.id'))
            elif slot_kind == schema.SLOT_STANCE and mod_slot_class != schema.SLOT_STANCE:
                errors.append(error('stance_in_normal_slot',
                                    '%s is not a Stance mod' % slot_mod.get('name'),
                                    mod=slot_mod.get('id'), field='slots[].mod.id'))
            elif slot_kind in (schema.SLOT_NORMAL, schema.SLOT_EXILUS) \
                    and mod_slot_class != schema.SLOT_NORMAL:
                errors.append(error('aura_in_normal_slot',
                                    '%s is a %s mod and cannot go in a %s slot'
                                    % (slot_mod.get('name'),
                                       'Stance' if mod_slot_class == schema.SLOT_STANCE
                                       else 'Aura', slot_kind),
                                    mod=slot_mod.get('id'), field='slots[].mod.id'))
            if slot_kind == schema.SLOT_EXILUS:
                if not raw.get('unlocked', build.get('exilus_unlocked', False)):
                    errors.append(error('exilus_not_unlocked',
                                        'the Exilus slot is not unlocked on this build',
                                        field='slots[].unlocked'))
                if not effects_mod.exilus_ok(slot_mod):
                    errors.append(error('mod_not_exilus',
                                        '%s is not an Exilus mod' % slot_mod.get('name'),
                                        mod=slot_mod.get('id'), field='slots[].mod.id'))
            targets = slot_mod.get('targets') or ()
            if kind and targets and kind not in targets:
                errors.append(error('incompatible_mod_type',
                                    '%s cannot be installed on a %s'
                                    % (slot_mod.get('name'), kind),
                                    mod=slot_mod.get('id'), field='slots[].mod.id'))
            if slot_mod.get('id') in seen_mods:
                errors.append(error('duplicate_mod',
                                    '%s is installed in two slots'
                                    % slot_mod.get('name'), mod=slot_mod.get('id'),
                                    field='slots'))
            seen_mods[slot_mod.get('id')] = True
            if (slot_mod.get('effects') or {}).get('unmodelled'):
                warnings.append(warning('unmodelled_effects',
                                        '%s carries stats the engine does not model: %s'
                                        % (slot_mod.get('name'),
                                           '; '.join(list(slot_mod['effects']['unmodelled'])[:3])),
                                        mod=slot_mod.get('id')))
        resolved_slots.append({'kind': slot_kind, 'index': index,
                               'polarity': polarity, 'mod': slot_mod, 'rank': rank,
                               'unlocked': raw.get('unlocked')})
        if len(errors) >= max_errors:
            errors.append(error('too_many_errors', 'stopped after %d errors' % max_errors))
            break

    rank = build.get('equipment_rank')
    max_rank = equipment.get('max_rank') or schema.MAX_RANK_WEAPON
    if rank is not None and (isinstance(rank, bool) or not isinstance(rank, int)
                             or rank < 0 or rank > max_rank):
        errors.append(error('invalid_equipment_rank',
                            'equipment rank %r is outside 0..%d' % (rank, max_rank),
                            field='equipment_rank'))

    mastery = int(build.get('mastery_rank') or 0)
    req = equipment.get('mastery_req')
    if req and mastery and mastery < req:
        warnings.append(warning('mastery_below_requirement',
                                '%s requires Mastery Rank %d (player is %d)'
                                % (equipment.get('name'), req, mastery)))

    cap = capacity_mod.capacity_breakdown(
        equipment,
        [{'kind': s['kind'], 'index': s['index'], 'polarity': s['polarity'],
          'mod': _capacity_mod(s['mod'], s['rank'])} for s in resolved_slots],
        equipment_rank=rank, orokin=bool(build.get('orokin')),
        mastery_rank=mastery)
    known = {(e.get('code'), e.get('mod'), e.get('field')) for e in errors}
    for row in cap['errors']:
        key = (row.get('code'), row.get('mod'), row.get('field'))
        if key not in known:
            errors.append(row)
            known.add(key)

    return {'ok': not errors, 'errors': errors, 'warnings': warnings,
            'capacity': cap}


def _capacity_mod(mod_row, rank):
    """The subset of a mod row the capacity engine reads."""
    if not mod_row:
        return None
    return {'id': mod_row.get('id'), 'name': mod_row.get('name'), 'rank': rank,
            'base_drain': mod_row.get('base_drain'), 'polarity': mod_row.get('polarity'),
            'max_rank': mod_row.get('max_rank')}


def resolved_slot_mods(build, db):
    """{slot_key: (mod_row, rank)} for the engine layer; errors are the caller's problem."""
    out, fails = {}, []
    for raw in (build or {}).get('slots') or []:
        if not raw.get('mod'):
            continue
        row, rank, err = resolve_mod(raw['mod'], db)
        if err:
            fails.append(err)
            continue
        out[(raw.get('kind') or schema.SLOT_NORMAL, raw.get('index'))] = (row, rank)
    return out, fails
