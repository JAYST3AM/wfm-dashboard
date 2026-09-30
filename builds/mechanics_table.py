"""The declarations: every mechanic the engine implements, declared once.

The implementations stay in their modules; the dotted paths here are resolved lazily by the
engine. Every `source` string is the provenance the engine prints; every `refusal_codes` entry
must have a row in `builds/unsupported.REGISTRY` (enforced at import).
"""
from .mechanics import Mechanic, Rule, F, ANY, ALL, register  # noqa: F401

HEAT_SOURCE = ('https://wiki.warframe.com/w/Damage/Heat_Damage (oldid 2807948, retrieved 2026-09-30)')
HEAT_RULE = ("Heat status: reduces armour by up to 50% - 'Every 0.5 seconds after the initial proc, "
             "the enemy will have 15%, then 30%, 40%, and finally 50% of its armor stripped. It "
             "therefore takes 2 seconds to reach the maximum armor strip.' The strip is "
             "multiplicative with corrosive (and with Corrosive Projection, which this engine does "
             "not model). The 6-second damage-over-time is a timeline and stays refused.")
ARMOUR_SOURCE = 'https://wiki.warframe.com/w/Armor (oldid 2814011, retrieved 2026-09-30)'
CORROSIVE_SOURCE = ('https://wiki.warframe.com/w/Damage/Corrosive_Damage '
                    '(oldid 2804597, retrieved 2026-09-30)')
VIRAL_SOURCE = 'https://wiki.warframe.com/w/Damage/Viral_Damage (oldid 2805913, retrieved 2026-09-30)'
FACTION_SOURCE = ('https://wiki.warframe.com/w/Damage (oldid 2812034) + '
                  '/w/Damage/Overview_Table (oldid 2792179) (retrieved 2026-09-30)')
STATUS_SOURCE = 'https://wiki.warframe.com/w/Status_Effect (oldid 2813980, retrieved 2026-09-30)'
RIDER_SOURCE = ('per-mod wiki card text + the exported corpus conditional table '
                '(data/build_data.json); the stack/cap/duration semantics are the card\'s own '
                '(retrieved 2026-09-30)')
# The result keys every Phase 1/Phase 4 mechanic gates when it cannot be resolved (the engine's
# long-standing behaviour). Only the target-path mechanics differ: their blast radius is the target
# block alone - that difference is the Phase 5 fix, and now a declaration rather than a hand list.
WIDE = ('damage_per_shot', 'damage_per_shot_expected_crit', 'burst_dps', 'sustained_dps',
        'damage_to_health', 'damage_to_health_expected_crit')
# ... plus the target block, which mirrors those very numbers: withholding a per-shot figure while
# its mirror stayed visible would be a withheld number that survives in another field.
WIDE_AND_BLOCK = WIDE + ('target_damage',)
# ... and the pool block, which *divides* those per-shot figures: withholding the divisor while the
# quotient stayed published was review 1's F2 / review 3's F1.
WIDE_AND_BLOCK_AND_POOL = WIDE_AND_BLOCK + ('pool', 'shots_to_kill')
# ... and the pool block, which *divides* those per-shot figures: withholding the divisor while the
# quotient stayed published was review 1's F2 / review 3's F1.
WIDE_AND_BLOCK_AND_POOL = WIDE_AND_BLOCK + ('pool', 'shots_to_kill')

UMBRAL_SOURCE = ('https://wiki.warframe.com/w/Umbral_Vitality (oldid 2792490), /w/Umbral_Fiber '
                 '(oldid 2792488), /w/Umbral_Intensify (oldid 2792489) (retrieved 2026-09-30)')
POOL_SOURCE = ('https://wiki.warframe.com/w/Armor (oldid 2814011) for the armour reduction chain; '
               'the pool result is this engine\'s own division of traced numbers')


register(Mechanic(
    id='target_faction', name='Target faction (damage-type modifiers)',
    family='target_damage', stage='damage_per_type',
    trigger=F('target_faction'),
    consumes=['target_faction', 'target.protection', 'target.armor'],
    required=['target_faction'],
    optional=['target.protection', 'target.armor'],
    stats=['damage_per_type'], trace='target_damage.{damage_type}',
    refusal_codes=['condition_unknown', 'mechanic_unsupported'],
    source=FACTION_SOURCE,
    withholds=WIDE_AND_BLOCK_AND_POOL,
    evaluate='conditions.target_faction',
    notes='the faction table is build/factions.py; a faction outside it refuses by name'))

register(Mechanic(
    id='protection_layer', name='Landing layer (health / armour / shields / Overguard)',
    family='target_damage', stage='damage_per_type',
    trigger=ALL(F('target.protection')),
    consumes=['target.protection', 'target_faction', 'target.armor'],
    required=['target.protection'],
    optional=['target.armor'],
    trace='target_damage.{damage_type}',
    refusal_codes=['condition_unknown', 'mechanic_unsupported'],
    source=ARMOUR_SOURCE,
    withholds=['target_damage'],
    deps=['target_faction'],
    notes='the path trigger itself is declared once as TARGET_PATH_RULE (armour, or a landing '
          'plus a faction, or a stated state mechanic); this row decides which layer the damage '
          'lands on'))

register(Mechanic(
    id='armour_mitigation', name='Enemy armour damage reduction',
    family='target_damage', stage='damage_per_type',
    trigger=ANY(F('target.armor'), ALL(F('target_faction'), F('target.protection'))),
    consumes=['target.armor', 'target.protection', 'target_faction'],
    required=['target.armor'],
    trace='target_damage.{damage_type}',
    refusal_codes=['condition_unknown'],
    source=ARMOUR_SOURCE,
    withholds=['target_damage'],
    deps=['protection_layer'],
    notes='DR = 0.9*sqrt(AR/2700) at or below 2700, AR/(AR+300) above; per-type minimum 1'))

register(Mechanic(
    id='first_shot', name='First-shot bonus',
    family='build_state', stage='damage_per_type',
    trigger=ALL(F('attack.shot_index')),
    consumes=['attack.shot_index'],
    required=['attack.shot_index'],
    trace='damage',
    refusal_codes=['condition_unknown', 'condition_not_satisfied'],
    source='https://wiki.warframe.com/w/Damage (oldid 2812034, retrieved 2026-09-30)',
    withholds=WIDE_AND_BLOCK_AND_POOL,
    evaluate='conditions.first_shot',
    notes='resolved from the stated shot number; never inferred from the build'))

register(Mechanic(
    id='viral', name='Viral status (damage to health)',
    family='target_state', stage='damage_to_health',
    trigger=ANY(F('target.viral_stacks')),
    consumes=['target.viral_stacks', 'target.protection', 'target.immune_to'],
    required=['target.viral_stacks'],
    optional=['target.immune_to'],
    trace='damage_to_health',
    refusal_codes=['mechanic_unsupported', 'condition_unknown'],
    source=VIRAL_SOURCE,
    required_when='build.deals_viral',
    withholds=WIDE_AND_BLOCK_AND_POOL,
    evaluate='statuses.evaluate',
    notes='a stated stack count only; immunity is declared, never inferred'))

register(Mechanic(
    id='corrosive', name='Corrosive status (armour reduction)',
    family='target_state', stage='armour_transform',
    trigger=ANY(F('target.corrosive_stacks')),
    consumes=['target.corrosive_stacks'],
    required=['target.corrosive_stacks'],
    trace='target_damage.{damage_type}',
    refusal_codes=['mechanic_unsupported', 'condition_unknown', 'corrosive_stack_timeline'],
    source=CORROSIVE_SOURCE,
    withholds=['target_damage'],
    evaluate='statuses.evaluate_corrosive',
    apply='statuses.corrosive_armour_transform',
    trace_row='statuses.corrosive_trace_row',
    required_when='build.deals_corrosive',
    notes="armour x (1 - (0.20 + 0.06 x stacks)); the reduction is stated stack state, never "
          "simulated"))

register(Mechanic(
    id='heat_strip', name='Heat status (armour strip)',
    family='target_state', stage='armour_transform',
    condition_id='heat',
    trigger=ANY(F('target.heat_strip')),
    consumes=['target.heat_strip'],
    required=['target.heat_strip'],
    trace='target_damage.{damage_type}',
    refusal_codes=['mechanic_unsupported', 'condition_unknown', 'heat_strip_value'],
    source=HEAT_SOURCE,
    withholds=['target_damage'],
    evaluate='statuses.evaluate_heat',
    apply='statuses.heat_armour_transform',
    trace_row='statuses.heat_trace_row',
    required_when='build.deals_heat',
    notes=HEAT_RULE))

register(Mechanic(
    id='on_kill_rider', name='On-Kill stat rider (stated build state)',
    family='build_state', stage='rider_contribution',
    trigger=ANY(F('buffs.on_kill')),
    consumes=['buffs.on_kill'],
    required=['buffs.on_kill'],
    # The stat list is the enablement (6.3): the stats this engine models, traces, and can source a
    # rider for. Each names the trace its rows land on - the destination is declared here, not
    # wired at the trace site. A rider on any other stat keeps its named refusal.
    stats=['multishot', 'critical_chance', 'critical_damage', 'status_chance', 'reload_speed',
           'fire_rate'],
    stat_traces={'multishot': 'multishot', 'critical_chance': 'critical_chance',
                 'critical_damage': 'critical_multiplier', 'status_chance': 'status_chance',
                 'reload_speed': 'reload_time', 'fire_rate': 'fire_rate'},
    condition_id='on_kill',
    refusal_codes=['mechanic_unsupported', 'condition_unknown', 'condition_not_satisfied',
                   'buff_stacks_above_cap'],
    source=RIDER_SOURCE,
    withholds=WIDE_AND_BLOCK_AND_POOL,
    averaged=True,
    evaluate='buffs.evaluate_state',
    notes='the stat list is the enablement: a stat the engine models and can source rides through '
          'the same path; instant and averaged states are separate and never mixed'))

register(Mechanic(
    id='target_damage_path', name='Target damage path (the aggregate row and the block)',
    family='target_damage', stage='target_path',
    condition_id='target_damage',
    trigger=ANY(F('target.armor'), ALL(F('target_faction'), F('target.protection')),
                F('target.corrosive_stacks'), F('target.heat_strip'), F('target.preset')),
    consumes=['target.protection', 'target.armor', 'target_faction', 'target.corrosive_stacks',
              'target.heat_strip', 'target.preset'],
    required=['target.protection'],
    trace='target_damage', emits_rows=False,
    refusal_codes=['condition_unknown', 'mechanic_unsupported'],
    source=ARMOUR_SOURCE,
    withholds=['target_damage'],
    deps=['protection_layer', 'target_faction', 'armour_mitigation'],
    notes='the row the target path reports when a stated input cannot be resolved; its blast '
          'radius is the target block alone (the Phase 5 fix, declared instead of hand-written)'))

register(Mechanic(
    id='umbral_set', name='Umbral set scaling (roster contract)',
    family='set', stage='set_scaling',
    trigger=None, consumes=[], stats=['health', 'armor', 'ability_strength'],
    emits_rows=False,
    refusal_codes=['set_bonus', 'duplicate_set_member', 'umbral_member_unknown',
                   'umbral_set_above_documented_pieces', 'umbral_set_no_rows'],
    source=UMBRAL_SOURCE,
    roster='distinct_legal_known',
    notes='Vitality/Fiber x1.30 at 2 pieces and x1.80 at 3; Intensify x1.25/x1.75; the roster '
          'rule (distinct, legal, known members) is the family contract every future set reuses'))

register(Mechanic(
    id='pool_result', name='Stated pool result (shots to deplete)',
    family='pool', stage='pool_result',
    # the rows it emits carry `condition: 'pool'` (enemies.evaluate_pool), so the declaration must
    # name the same id or `by_condition` cannot join them and its radius stays underivable
    condition_id='pool',
    trigger=ANY(F('target.health'), F('target.shields'), F('target.overguard')),
    consumes=['target.health', 'target.shields', 'target.overguard'],
    required=[], one_of=['target.health', 'target.shields', 'target.overguard'],
    optional=['target.shields', 'target.overguard'],
    trace='pool',
    refusal_codes=['mechanic_unsupported', 'condition_unknown', 'pool_landing_mismatch',
                   'pool_unresolved'],
    source=POOL_SOURCE,
    withholds=['pool', 'shots_to_kill'],
    deps=['protection_layer', 'armour_mitigation'],
    notes='a division of traced numbers, only for the stated pool and only when the damage path '
          'that depletes it is itself resolved'))

register(Mechanic(
    id='target_preset', name='Target preset (deferred: no authoritative source)',
    family='target_state', stage='target_path',
    trigger=ANY(F('target.preset')),
    consumes=['target.preset'],
    required=['target.preset'],
    emits_rows=False,
    refusal_codes=['preset_unavailable'],
    source='none: this database carries equipment and mods, and no enemy rows at all',
    withholds=['target_damage'],
    notes='the corpus has no enemy profiles to join a preset to; the input is refused by name '
          'rather than fabricated (design/build-planner/phase6-plan.md §5)'))

register(Mechanic(
    id='removed_vocabulary', name='Damage 3.0-removed fields (health_type / armor_type)',
    family='target_state', stage='target_path',
    trigger=ANY(F('target.health_type'), F('target.armor_type')),
    consumes=['target.health_type', 'target.armor_type'],
    required=['target.health_type'], emits_rows=False,
    refusal_codes=['mechanic_unsupported'],
    source='https://wiki.warframe.com/w/Damage (oldid 2812034, retrieved 2026-09-30)',
    withholds=[],
    notes='Damage 3.0 removed the per-health-type model, so these names describe a game state that '
          'no longer exists; they are refused by name (context_unused + a marker) exactly like the '
          'pool sizes were before the pool mechanic consumed them'))

register(Mechanic(
    id='squad_armour_auras', name='Squad armour reduction auras (Corrosive Projection)',
    family='target_state', stage='armour_transform',
    trigger=None, consumes=[], emits_rows=False,
    refusal_codes=['mechanic_unsupported'],
    source=HEAT_SOURCE,
    withholds=['target_damage'],
    notes='the Heat formula composes with Corrosive Projection; auras are a squad state this '
          'engine does not model, so the source is named and the term is refused'))
