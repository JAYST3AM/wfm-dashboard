#!/usr/bin/env python3
"""The unsupported / special-mechanics registry.

Brief section 11: never silently approximate a mechanic. Anything the engine cannot
compute is named here with a reason, and the engines emit the same marker shape when a
build touches one:

    {"supported": false, "reason": "conditional Galvanized stack behaviour not
     implemented yet"}

Two consumers:
  * the engines (weapons.py / warframes.py / effects.py) for per-build markers;
  * the UI later, which can list "what this planner does not know yet" without reading
    the code.

`phase` records where each one is intended to land (the brief's Phase 2..7 roadmap) so
the registry doubles as the punch list for the next phases.
"""

# code -> registry row. Codes match the markers the engines emit.
REGISTRY = {
    'galvanized_stacks': {
        'reason': 'only the multishot On-Kill rider of the Galvanized family is applied, and '
                  'only from a stated buff state',
        'phase': 5, 'engine': 'weapons.calculate / buffs.evaluate_state',
        'detail': 'a stated context.buffs.on_kill state applies the multishot rider '
                  '(instant or averaged). Every other Galvanized rider (crit, status, on-hit) '
                  'and every unstated state still refuses by name'},
    'conditional_buffs': {
        'reason': 'conditional mod effects other than the On-Kill multishot rider have no '
                  'model: weak-point/aiming riders, timers, per-status scaling and on-hit '
                  'riders all refuse by name with the clause they carry',
        'phase': 5, 'engine': 'effects.parse_mod_effects',
        'detail': 'an on-kill rider with a stat this phase does not apply gets its own precise '
                  'reason; every other conditional line keeps the four-state refusal row'},
    'set_bonuses': {
        'reason': 'only the Umbral set is modelled (Vitality/Fiber x1.30 at 2 pieces and '
                  'x1.80 at 3; Intensify x1.25/x1.75); every other set (Augur, Gladiator, '
                  'Vigorous, ...) refuses by name',
        'phase': 5, 'engine': 'effects.collect_mod_effects'},
    'rivens': {
        'reason': 'Riven mods are generated, not catalog rows: their stats and '
                  'dispositions are not modelled', 'phase': 2,
        'engine': 'effects.collect_mod_effects'},
    'incarnon_evolutions': {
        'reason': 'weapon Incarnon evolutions (form stats and evolution perks) are not '
                  'implemented', 'phase': 2, 'engine': 'weapons.calculate'},
    'faction_damage_special_cases': {
        'reason': 'faction damage is supported as a separate multiplier; the special '
                  'cases (Bane mods against boss damage attenuation, faction-specific '
                  'proc interactions) are not', 'phase': 2,
        'engine': 'weapons.calculate'},
    'headshot_multipliers': {
        'reason': 'headshot / weak point multipliers are not implemented',
        'phase': 2, 'engine': 'weapons.calculate'},
    'enemy_armor': {
        'reason': 'a stated target models armour mitigation, faction damage-type '
                  'modifiers and the corrosive reduction; any target state the caller did '
                  'not state, pool sizes, other armour strips and enemy auras are refused',
        'phase': 5, 'engine': 'enemies.evaluate / enemies.calculate'},
    'status_effects': {
        'reason': 'viral amplification (state-stated) and the corrosive armour reduction are '
                  'modelled; every other status and all tick damage (Heat, Slash, Gas, '
                  'Electricity, Toxin) are refused', 'phase': 5,
        'engine': 'statuses.evaluate / statuses.evaluate_corrosive'},
    'status_weighting': {
        'reason': 'proc weighting/priority and damage-type distribution effects are '
                  'exposed as weights but not yet used to predict procs', 'phase': 2,
        'engine': 'weapons.calculate'},
    'condition_overload': {
        'reason': 'Condition Overload and other per-status-type scaling melee mechanics '
                  'are not implemented', 'phase': 2, 'engine': 'weapons.calculate'},
    'melee_combo_multiplier': {
        'reason': 'the melee combo counter multiplier is not implemented', 'phase': 2,
        'engine': 'weapons.calculate'},
    'heavy_attacks': {
        'reason': 'heavy attacks (wind-up, heavy attack damage, efficiency) are not '
                  'implemented', 'phase': 2, 'engine': 'weapons.calculate'},
    'stance_multipliers': {
        'reason': 'stance damage multipliers and combo trees are not implemented',
        'phase': 2, 'engine': 'weapons.calculate'},
    'melee_range_and_follow_through': {
        'reason': 'melee range bonuses are reported, but follow-through and hit counts '
                  'are not modelled', 'phase': 2, 'engine': 'weapons.calculate'},
    'dps_trigger_types': {
        'reason': 'burst/sustained DPS is only reported for Auto/Semi/Held/Duplex '
                  'triggers; Charge, Burst and Continuous attacks have documented '
                  'non-trivial effective fire rates that are not implemented', 'phase': 2,
        'engine': 'weapons._dps_block'},
    'arcanes': {
        'reason': 'Arcane enhancements (weapon and Warframe) are not implemented',
        'phase': 2, 'engine': 'both'},
    'ability_specific_formulas': {
        'reason': 'per-ability formulas are not implemented: only the four ability stats '
                  '(strength / duration / efficiency / range) are computed', 'phase': 3,
        'engine': 'warframes.calculate'},
    'helminth': {
        'reason': 'Helminth subsumed abilities and invigorations are not implemented',
        'phase': 3, 'engine': 'warframes.calculate'},
    'archon_shards': {
        'reason': 'Archon Shards are not implemented', 'phase': 3,
        'engine': 'warframes.calculate'},
    'companion_buffs': {
        'reason': 'companion and squad buffs are not implemented', 'phase': 3,
        'engine': 'warframes.calculate'},
    'external_buffs': {
        'reason': 'external buffs (squad abilities, focus, operator, primed setups) are '
                  'not implemented', 'phase': 3, 'engine': 'both'},
    'primers': {
        'reason': 'primers and their status setups are not implemented', 'phase': 6,
        'engine': 'none'},
    'rank_exception_frames': {
        'reason': 'frames in the wiki Rank-Up Exceptions list use their documented '
                  'rank-30 totals; below rank 30 the cadence is interpolated (exact '
                  'per-rank schedules are only documented for the Nidus family)',
        'phase': 3, 'engine': 'warframes.calculate'},
    'nidus_health_regeneration': {
        'reason': 'Nidus / Nidus Prime gain +2 Health/s Regeneration every 6 ranks from '
                  'rank 6 (+15/s at rank 30); health regeneration is not modelled',
        'phase': 3, 'engine': 'warframes.calculate'},
    'rank_bonus_approximation': {
        'reason': 'the frame is in the Rank-Up Exceptions list: its rank-30 stat totals '
                  'are documented and exact, but the per-rank cadence is not, so '
                  'intermediate ranks spread the total over the default cadence',
        'phase': 3, 'engine': 'warframes.calculate'},
    'innate_secondary_element': {
        'reason': 'a weapon with an innate combined element (Hema: Viral) has a '
                  'documented special interaction with matching primary mods that is not '
                  'modelled', 'phase': 2, 'engine': 'weapons.calculate'},
    'multiple_innate_elements': {
        'reason': 'Kuva/Tenet weapons can carry two innate primary elements; the HCET '
                  'tie-break for their combine order is not implemented', 'phase': 2,
        'engine': 'weapons.calculate'},
    'weapon_traits': {
        'reason': 'weapon-specific traits (multi-mode attacks, alt-fires, charge '
                  'mechanics) are not implemented', 'phase': 2,
        'engine': 'weapons.calculate'},
    'archwing_necramech': {
        'reason': 'Archwing, Arch-Gun, Arch-Melee and Necramech rows are ingested later; '
                  'their mod sets are not in the database yet', 'phase': 2,
        'engine': 'ingest'},
    'companions': {
        'reason': 'Sentinel/Pet mod effects on the player (and vice versa) are not '
                  'modelled', 'phase': 3, 'engine': 'none'},
    'duplicate_set_member': {
        'reason': 'the same set mod is equipped more than once: two copies of one mod are not two '
                  'set pieces, so the set bonus is refused rather than double-counted',
        'phase': 5, 'engine': 'effects.collect_mod_effects'},
    'umbral_member_unknown': {
        'reason': 'a mod carries the Umbral set flag but has no pinned scaling in this engine, so '
                  'its own set bonus is refused while the counted pieces still count',
        'phase': 5, 'engine': 'effects.collect_mod_effects'},
    'umbral_set_above_documented_pieces': {
        'reason': 'the build states more Umbral set pieces than the pinned rule documents (2 and '
                  '3), so no scaling is applied instead of defaulting to the mods\' own values',
        'phase': 5, 'engine': 'effects.collect_mod_effects'},
    'umbral_set_no_rows': {
        'reason': 'the Umbral set bonus applies to the members\' own contributions; if none of '
                  'them contributed a stat this engine models, the refusal says so instead of a '
                  'note claiming a scaling that touched nothing',
        'phase': 5, 'engine': 'effects.collect_mod_effects'},
    'corrosive_stack_timeline': {
        'reason': 'corrosive stacks above the 10-proc cap are a timeline (the Emerald Archon '
                  'Shard raises the cap and stacks beyond it replace the oldest), so the armour '
                  'reduction is refused rather than clamped',
        'phase': 5, 'engine': 'statuses.evaluate_corrosive'},
    'buff_stacks_above_cap': {
        'reason': 'a stated stack count above the cap the mod\'s own card documents is a '
                  'timeline (stacks replace the oldest), so the rider is refused rather than '
                  'clamped to the cap',
        'phase': 5, 'engine': 'buffs.evaluate_state'},
    'conditional_calculations': {
        'reason': 'a condition this engine can resolve - the target faction, the shot '
                  'number in the magazine, or the viral procs on the target - was not stated, '
                  'and the caller asked for a strict evaluation, so the affected stats are '
                  'withheld instead of being answered without it',
        'phase': 4, 'engine': 'weapons.calculate'},
    'quantization_shown_values': {
        'reason': 'live damage is quantized to 1/32 of the modded base damage; the '
                  'planner exposes the quantized values on request but the arsenal-style '
                  'default stays unquantized', 'phase': 2, 'engine': 'weapons.calculate'},
    'context_unused': {
        'reason': 'the caller stated an input this engine has no model for; it is named '
                  'rather than dropped, and no number is invented from it',
        'phase': 4, 'engine': 'api.compute'},
}

# The marker codes the engines emit, mapped onto registry keys. Everything the engines
# can refuse must appear here, or a build could carry an unnamed refusal.
MARKER_TO_KEY = {
    'context_unused': 'context_unused',
    'conditional_effect': 'conditional_buffs',
    'calculation_refused': 'conditional_calculations',
    'unmodelled_effect': None,                 # per-stat: named in the marker itself
    'set_bonus': 'set_bonuses',
    'riven': 'rivens',
    'incarnon': 'incarnon_evolutions',
    'multiple_innate_elements': 'multiple_innate_elements',
    'innate_secondary_element': 'innate_secondary_element',
    'weapon_traits': 'weapon_traits',
    'melee_combo_multiplier': 'melee_combo_multiplier',
    'heavy_attack': 'heavy_attacks',
    'stance_multiplier': 'stance_multipliers',
    'dps_trigger_type': 'dps_trigger_types',
    'augment_mod': 'ability_specific_formulas',
    'ability_formulas': 'ability_specific_formulas',
    'external_buffs': 'external_buffs',
    'rank_exception_frame': 'rank_exception_frames',
    'rank_bonus_approximation': 'rank_bonus_approximation',
    'nidus_health_regeneration': 'nidus_health_regeneration',
    'mod_rank_out_of_range': None,             # a build error, not a missing mechanic
}


def entry(code):
    """Registry row for a code (or None), with the code filled in."""
    key = MARKER_TO_KEY.get(code, code)
    if key is None:
        return None
    row = REGISTRY.get(key)
    if row is None:
        return None
    out = {'code': code, 'supported': False}
    out.update(row)
    return out


def marker(code, reason=None, **extra):
    """A refusal marker in the brief's shape, enriched with registry detail when known."""
    row = entry(code) or {}
    out = {'supported': False, 'code': code,
           'reason': reason or row.get('reason') or 'not modelled'}
    if row.get('phase'):
        out['phase'] = row['phase']
    out.update(extra)
    return out


def list_all():
    """Every unsupported mechanic, registry-shaped (for docs, UI and tests)."""
    return [dict(code=code, supported=False, **row) for code, row in REGISTRY.items()]


def supported_summary():
    """What Phase 1 *does* compute - the counterpart of list_all(), used by the docs."""
    return {
        'capacity': ['rank capacity, Orokin doubling, Mastery minimum capacity',
                     'aura/stance bonuses with polarity doubling/80% mismatch',
                     'per-slot polarity rules (match/neutral/mismatch/universal/Umbra)',
                     'exilus slots, Forma-set polarities, rounding edge cases'],
        'mods': ['per-rank effect tables straight from the export (partial ranks exact)',
                 'linear/non-linear progression reporting', 'classification flags',
                 'compatibility + slot-class validation'],
        'weapons': ['base/physical/elemental damage in the wiki order',
                    'element combination by mod placement + innate rules',
                    'critical chance/multiplier with multi-tier expectation',
                    'status chance + expected procs per shot (per projectile, >100%)',
                    'multishot (deterministic + expected)', 'fire rate, magazine, reload',
                    'burst/sustained DPS for Auto/Semi/Held/Duplex triggers',
                    'faction multiplier (separate, traced)', 'quantization on request'],
        'warframes': ['rank-scaled health/shield/energy, armor, sprint speed',
                      'ability strength/duration/efficiency/range with caps + cost floor'],
        'infrastructure': ['calculation traces for every stat', 'structured validation',
                           'data provenance and schema versioning',
                           'scalar engine usable by a future UI through builds/api.py'],
    }


def check_coverage(markers):
    """Sanity helper: every marker the engines emitted maps to a registry entry.

    Returns the list of codes with no registry row - the test suite asserts it is empty,
    so a new refusal cannot ship unnamed.
    """
    missing = []
    for row in markers or []:
        code = row.get('code') if isinstance(row, dict) else row
        if code and code not in MARKER_TO_KEY and code not in REGISTRY:
            missing.append(code)
    return missing


__all__ = ['REGISTRY', 'MARKER_TO_KEY', 'entry', 'marker', 'list_all',
           'supported_summary', 'check_coverage']
