#!/usr/bin/env python3
"""Canonical vocabulary for the build engine: ids, polarities, damage types, stats.

Everything in the engine speaks these constants - the ingested data is normalised into
them at ingest time (builds/ingest.py) so the math modules never parse game strings.

Identity rules (Phase 1 brief: "do not create a second incompatible identity system")
  * An item's canonical id is DE's own `uniqueName` ("/Lotus/Weapons/Tenno/Rifle/
    BratonPrime") - that is what the AlecaFrame save, the WFCD catalog and the local
    caches all join on.
  * `slug` (warframe.market's id, "braton_prime") rides alongside for market joins only.
    Slug is NOT an identity: 259 catalog rows share slugs and slugs collide by design.

No imports, no I/O: pure constants plus two tiny helpers.
"""

# ------------------------------------------------------------------ polarities
# The values WFCD emits (lower case) plus the two the game grew later.
POLARITY_MADURAI = 'madurai'        # V
POLARITY_VAZARIN = 'vazarin'        # D
POLARITY_NARAMON = 'naramon'        # dash
POLARITY_ZENURIK = 'zenurik'        # scratch/asterisk
POLARITY_UNAIRU = 'unairu'          # circle
POLARITY_PENJAGA = 'penjaga'        # animal/kubrow (companion mods)
POLARITY_UMBRA = 'umbra'            # Umbral mods only
POLARITY_UNIVERSAL = 'universal'    # Omni/Aura Forma: matches every mod
POLARITY_AURA = 'aura'              # WFCD's aura *slot* value (a slot, not a mod)

POLARITIES = (POLARITY_MADURAI, POLARITY_VAZARIN, POLARITY_NARAMON, POLARITY_ZENURIK,
              POLARITY_UNAIRU, POLARITY_PENJAGA, POLARITY_UMBRA, POLARITY_UNIVERSAL)
# Accepted spellings on input -> canonical value. 'aura' arrives from WFCD on the Aura
# mods module data; auras are not a mod polarity, so it normalises to "any (vacant
# polarity)" = None at the slot level and is ignored on a mod.
POLARITY_ALIASES = {
    'madurai': POLARITY_MADURAI, 'v': POLARITY_MADURAI, 'attack': POLARITY_MADURAI,
    'vazarin': POLARITY_VAZARIN, 'd': POLARITY_VAZARIN, 'defense': POLARITY_VAZARIN,
    'naramon': POLARITY_NARAMON, '-': POLARITY_NARAMON, 'tactic': POLARITY_NARAMON,
    'zenurik': POLARITY_ZENURIK, 'scratch': POLARITY_ZENURIK, 'power': POLARITY_ZENURIK,
    'unairu': POLARITY_UNAIRU, 'circle': POLARITY_UNAIRU, 'ward': POLARITY_UNAIRU,
    'penjaga': POLARITY_PENJAGA, 'precept': POLARITY_PENJAGA,
    'umbra': POLARITY_UMBRA, 'umbral': POLARITY_UMBRA,
    'universal': POLARITY_UNIVERSAL, 'any': POLARITY_UNIVERSAL, 'omni': POLARITY_UNIVERSAL,
    'aura': None, 'none': None, '': None, 'vacant': None,
}


def norm_polarity(value):
    """Any spelling -> a canonical polarity, or None for "no polarity / unrestricted"."""
    if value is None:
        return None
    key = str(value).strip().lower()
    if key in POLARITY_ALIASES:
        return POLARITY_ALIASES[key]
    return key if key in POLARITIES else None


# ------------------------------------------------------------------ damage types
# Order matters twice: PHYSICAL first in the arsenal read-out, and the element
# combination hierarchy runs in *mod placement* order (see elements.py).
DAMAGE_IMPACT = 'impact'
DAMAGE_PUNCTURE = 'puncture'
DAMAGE_SLASH = 'slash'
PHYSICAL_TYPES = (DAMAGE_IMPACT, DAMAGE_PUNCTURE, DAMAGE_SLASH)

# Primary elements, combined in pairs by placement order.
PRIMARY_ELEMENTS = ('heat', 'cold', 'electricity', 'toxin')
# Secondary (combined) elements. heat > cold > electricity > toxin ("HCET") is the
# tie-break the wiki documents for weapons carrying two innate primaries; Phase 1 marks
# those weapons unsupported rather than guessing (see unsupported.py).
SECONDARY_ELEMENTS = ('blast', 'corrosive', 'gas', 'magnetic', 'radiation', 'viral')
ELEMENTAL_TYPES = PRIMARY_ELEMENTS + SECONDARY_ELEMENTS

# Every damage type a weapon row can carry, in arsenal display order. `void`, `tau`,
# `true` and the shield/health/energy drain pseudo-types exist in the export; they are
# carried through so nothing is dropped, but they are not element-combination inputs.
EXTRA_DAMAGE_TYPES = ('void', 'tau', 'true', 'cinematic', 'shield_drain', 'health_drain',
                      'energy_drain')
ALL_DAMAGE_TYPES = PHYSICAL_TYPES + ELEMENTAL_TYPES + EXTRA_DAMAGE_TYPES

# Which two primaries make which secondary (the only legal combinations).
ELEMENT_COMBINATIONS = {
    frozenset(('heat', 'cold')): 'blast',
    frozenset(('heat', 'electricity')): 'radiation',
    frozenset(('heat', 'toxin')): 'gas',
    frozenset(('cold', 'electricity')): 'magnetic',
    frozenset(('cold', 'toxin')): 'viral',
    frozenset(('electricity', 'toxin')): 'corrosive',
}


def combined_element(a, b):
    """The secondary element two primaries form, or None when they cannot combine."""
    if a == b:
        return None                        # the same element merges, it never combines
    return ELEMENT_COMBINATIONS.get(frozenset((a, b)))


def is_primary_element(name):
    return name in PRIMARY_ELEMENTS


# ------------------------------------------------------------------ slot kinds
SLOT_NORMAL = 'normal'
SLOT_AURA = 'aura'
SLOT_STANCE = 'stance'
SLOT_EXILUS = 'exilus'
SLOT_KINDS = (SLOT_NORMAL, SLOT_AURA, SLOT_STANCE, SLOT_EXILUS)
NORMAL_SLOTS = 8                            # every moddable item has 8 normal slots

# ------------------------------------------------------------------ equipment
EQUIP_WARFRAME = 'warframe'
EQUIP_PRIMARY = 'primary'
EQUIP_SECONDARY = 'secondary'
EQUIP_MELEE = 'melee'
EQUIP_SENTINEL = 'sentinel'
EQUIP_SENTINEL_WEAPON = 'sentinel_weapon'
EQUIP_KINDS = (EQUIP_WARFRAME, EQUIP_PRIMARY, EQUIP_SECONDARY, EQUIP_MELEE,
               EQUIP_SENTINEL, EQUIP_SENTINEL_WEAPON)

# The slot kinds each equipment kind has. Warframes have an aura slot; melee weapons a
# stance slot; every moddable item has an exilus slot once an adapter is used.
EQUIP_SLOT_KINDS = {
    EQUIP_WARFRAME: (SLOT_NORMAL, SLOT_AURA, SLOT_EXILUS),
    EQUIP_PRIMARY: (SLOT_NORMAL, SLOT_EXILUS),
    EQUIP_SECONDARY: (SLOT_NORMAL, SLOT_EXILUS),
    EQUIP_MELEE: (SLOT_NORMAL, SLOT_STANCE, SLOT_EXILUS),
    EQUIP_SENTINEL: (SLOT_NORMAL, SLOT_EXILUS),
    EQUIP_SENTINEL_WEAPON: (SLOT_NORMAL,),
}

# ------------------------------------------------------------------ mod classes
# WFCD `type`/`compatName` -> the equipment kind(s) a mod may live in. This is the
# compatibility table validation uses; it is deliberately conservative (a mod whose
# class is unknown is rejected with `incompatible_mod_type`, never assumed legal).
MOD_TARGETS = {
    'warframe': (EQUIP_WARFRAME,),
    'aura': (EQUIP_WARFRAME,),
    'primary': (EQUIP_PRIMARY,),
    'rifle': (EQUIP_PRIMARY,),
    'shotgun': (EQUIP_PRIMARY,),
    'bow': (EQUIP_PRIMARY,),
    'sniper': (EQUIP_PRIMARY,),
    'speargun': (EQUIP_PRIMARY,),
    'secondary': (EQUIP_SECONDARY,),
    'pistol': (EQUIP_SECONDARY,),
    'melee': (EQUIP_MELEE,),
    'stance': (EQUIP_MELEE,),
    'sentinel': (EQUIP_SENTINEL,),
    'sentinel_weapon': (EQUIP_SENTINEL_WEAPON,),
    'robotic': (EQUIP_SENTINEL,),
    'companion': (EQUIP_SENTINEL,),
    # Archwing / necramech / k-drive mods are ingested later (documented in
    # docs/build-data-sources.md); they must not silently validate against a rifle.
    'archwing': (), 'arch-gun': (), 'arch-melee': (), 'necramech': (), 'k-drive': (),
    'parazon': (), 'railjack': (),
}

# The stat-line vocabulary. `stat` -> (canonical id, unit). `unit` is what the number in
# the stat line means: 'percent' (+50% Damage), 'flat' (+2.5s, +0.6 Energy/s) or
# 'percent_points' (rare; the value is added to a percentage stat directly).
# Anything not listed here is preserved as an unmodelled effect - never silently
# dropped, never guessed at (see effects.mod_rank_table / unsupported.py).
STAT_VOCABULARY = {
    # damage
    'damage': ('damage', 'percent'),
    'melee damage': ('damage', 'percent'),
    'damage on first shot in magazine': ('damage_on_first_shot', 'percent'),
    'impact': ('impact', 'percent'),
    'puncture': ('puncture', 'percent'),
    'slash': ('slash', 'percent'),
    'heat': ('heat', 'percent'),
    'cold': ('cold', 'percent'),
    'electricity': ('electricity', 'percent'),
    'toxin': ('toxin', 'percent'),
    'blast': ('blast', 'percent'),
    'radiation': ('radiation', 'percent'),
    'gas': ('gas', 'percent'),
    'magnetic': ('magnetic', 'percent'),
    'viral': ('viral', 'percent'),
    'corrosive': ('corrosive', 'percent'),
    'finisher damage': ('finisher_damage', 'percent'),
    'damage during bleedout': ('damage_bleedout', 'percent'),
    'status damage': ('status_damage', 'percent'),
    'weak point damage': ('weak_point_damage', 'percent'),
    # weapon handling
    'multishot': ('multishot', 'percent'),
    'critical chance': ('critical_chance', 'percent'),
    'critical chance (x2 for heavy attacks)': ('critical_chance', 'percent'),
    'critical damage': ('critical_damage', 'percent'),
    'status chance': ('status_chance', 'percent'),
    'status duration': ('status_duration', 'percent'),
    'fire rate': ('fire_rate', 'percent'),
    'fire rate (x2 for bows)': ('fire_rate', 'percent'),
    'attack speed': ('attack_speed', 'percent'),
    'reload speed': ('reload_speed', 'percent'),
    'magazine capacity': ('magazine_capacity', 'percent'),
    'ammo maximum': ('ammo_maximum', 'percent'),
    'ammo maximum (%)': ('ammo_maximum', 'percent'),
    'punch through': ('punch_through', 'flat'),
    'accuracy': ('accuracy', 'percent'),
    'zoom': ('zoom', 'percent'),
    'weapon recoil': ('recoil', 'percent'),
    'projectile speed': ('projectile_speed', 'percent'),
    'range': ('range', 'flat'),
    's combo duration': ('combo_duration', 'flat'),
    'combo duration': ('combo_duration', 'flat'),
    'heavy attack efficiency': ('heavy_attack_efficiency', 'percent'),
    'slide': ('slide', 'percent'),
    'mobility': ('mobility', 'percent'),
    # warframe survival
    'health': ('health', 'percent'),
    'shield capacity': ('shield', 'percent'),
    'armor': ('armor', 'percent'),
    'energy max': ('energy_max', 'percent'),
    'sprint speed': ('sprint_speed', 'percent'),
    'shield recharge': ('shield_recharge', 'percent'),
    'shield recharge delay': ('shield_recharge_delay', 'percent'),
    'tau resistance': ('tau_resistance', 'percent'),
    'toxin resistance': ('toxin_resistance', 'percent'),
    'heat resistance': ('heat_resistance', 'percent'),
    'cold resistance': ('cold_resistance', 'percent'),
    'electricity resistance': ('electricity_resistance', 'percent'),
    'radiation resistance': ('radiation_resistance', 'percent'),
    'bleedout delay': ('bleedout_delay', 'percent'),
    'chance to resist knockdown': ('knockdown_resistance', 'percent'),
    'faster knockdown recovery': ('knockdown_recovery', 'percent'),
    'from health orbs': ('health_orbs', 'percent'),
    'health orb effectiveness': ('health_orbs', 'percent'),
    # abilities
    'ability strength': ('ability_strength', 'percent'),
    'ability duration': ('ability_duration', 'percent'),
    'ability efficiency': ('ability_efficiency', 'percent'),
    'ability range': ('ability_range', 'percent'),
    'casting speed': ('casting_speed', 'percent'),
    'chance to open enemies to finisher attacks after warframe blocks melee':
        ('finisher_chance_on_block', 'percent'),
    # auras (squad/summoner effects) - modelled only where the value is directly usable
    'energy regen/s': ('energy_regen', 'flat'),
    'm enemy radar': ('enemy_radar', 'flat'),
    'm loot radar': ('loot_radar', 'flat'),
    'to parkour velocity': ('parkour_velocity', 'percent'),
    'aim glide/wall latch duration': ('aim_glide_duration', 'percent'),
    'zoom while aim gliding': ('aim_glide_zoom', 'percent'),
    'blast range': ('blast_range', 'flat'),
}

# Stats a weapon build can actually consume in Phase 1. A mod carrying any other stat
# is still installable (capacity is real), but the engine flags it as unmodelled for
# the affected calculation instead of pretending the stat did something.
WEAPON_STATS = frozenset((
    'damage', 'impact', 'puncture', 'slash', 'heat', 'cold', 'electricity', 'toxin',
    'blast', 'radiation', 'gas', 'magnetic', 'viral', 'corrosive', 'multishot',
    'critical_chance', 'critical_damage', 'status_chance', 'status_duration',
    'status_damage', 'fire_rate', 'attack_speed', 'reload_speed', 'magazine_capacity',
    'ammo_maximum', 'punch_through', 'accuracy', 'zoom', 'recoil', 'projectile_speed',
    'range', 'combo_duration', 'heavy_attack_efficiency', 'finisher_damage',
    'faction_grineer', 'faction_corpus', 'faction_infested', 'faction_corrupted',
    'faction_murmur', 'faction_orokin', 'faction_sentient',
))
WARFRAME_STATS = frozenset((
    'health', 'shield', 'armor', 'energy_max', 'sprint_speed', 'ability_strength',
    'ability_duration', 'ability_efficiency', 'ability_range', 'casting_speed',
    'shield_recharge', 'shield_recharge_delay', 'tau_resistance', 'energy_regen',
    'knockdown_resistance', 'parkour_velocity', 'aim_glide_duration', 'enemy_radar',
    'loot_radar',
))

# Mod classification flags the brief asks for (Primed / Umbral / Galvanized / Archon /
# ...). Derived from the mod's own name + WFCD flags at ingest time; kept here so the
# vocabulary has one home.
MOD_CLASS_FLAGS = ('primed', 'umbral', 'galvanized', 'archon', 'amalgam', 'flawed',
                   'riven', 'sacrificial', 'prime', 'augment', 'exilus', 'aura', 'stance',
                   'set')

# Warframe rank scaling (wiki: Warframes - "Leveling Up" + "Rank-Up Exceptions List"):
# the catalog carries rank-0 base stats and ranking up adds a FIXED amount derived from
# the base (mods never change the gain).
#
#   default schedule    +10 Health every 3 ranks starting at rank 1  -> +100 at rank 30
#                       +10 Shield every 3 ranks starting at rank 2  -> +100
#                       +5  Energy every 3 ranks starting at rank 3  -> +50
#                       Armor and sprint speed do not rank-scale.
#
# Frames whose gains differ are listed in the wiki's Rank-Up Exceptions table; those
# totals are exact at rank 30 and use the default cadence scaled proportionally in
# between (the engines mark that as an approximation). Nidus and Nidus Prime have a
# fully documented per-rank schedule and are computed exactly at every rank.
MAX_RANK_FRAME = 30
MAX_RANK_WEAPON = 30
MAX_RANK_NECRAMECH = 40
MAX_MOD_RANK = 10

# stat -> (first_rank, step_ranks, amount_per_step, steps_to_max, total_at_max)
RANK_STEP_DEFAULT = {
    'health': (1, 3, 10.0, 10, 100.0),
    'shield': (2, 3, 10.0, 10, 100.0),
    'energy': (3, 3, 5.0, 10, 50.0),
    'armor': None,
}

# Wiki "Rank-Up Exceptions List" (warframe name, lower-case) -> totals at rank 30.
RANK_BONUS_EXCEPTIONS = {
    'baruuk': (100, 100, 0, 100), 'baruuk prime': (100, 100, 0, 100),
    'chroma prime': (100, 100, 0, 100),
    'dante': (90, 90, 0, 70),
    'garuda': (100, 100, 0, 100), 'garuda prime': (100, 100, 0, 100),
    'grendel': (200, 0, 0, 50), 'grendel prime': (200, 0, 0, 50),
    'hildryn': (100, 500, 0, 0), 'hildryn prime': (100, 500, 0, 0),
    'inaros': (200, 0, 0, 50), 'inaros prime': (200, 0, 0, 50),
    'koumei': (100, 100, 0, 100),
    'kullervo': (200, 0, 100, 50),
    'lavos': (200, 100, 100, 0), 'lavos prime': (200, 100, 100, 0),
    'narin': (100, 100, 0, 90),
    'nezha': (100, 50, 0, 50), 'nezha prime': (100, 50, 0, 50),
    'saryn prime': (100, 100, 0, 100),
    'valkyr': (100, 50, 0, 50), 'valkyr prime': (100, 50, 0, 50),
    'volt prime': (100, 100, 0, 100),
    'wisp': (100, 100, 0, 100), 'wisp prime': (100, 100, 0, 100),
    'xaku': (90, 90, 0, 70), 'xaku prime': (90, 90, 0, 70),
    'yareli': (100, 100, 0, 100), 'yareli prime': (100, 100, 0, 100),
}
RANK_EXCEPTION_ORDER = ('health', 'shield', 'armor', 'energy')

# Nidus / Nidus Prime: the one frame family with a documented step schedule (wiki).
#   +10 Health every 3 ranks from 1, +20 Armor every 6 ranks from 2, +3% Ability
#   Strength every 6 ranks from 3, +10 Energy every 6 ranks from 5, +2 Health/s
#   Regeneration every 6 ranks from 6 (regen itself is not modelled -> marker).
NIDUS_FRAMES = ('nidus', 'nidus prime')
NIDUS_SCHEDULES = {
    'health': (1, 3, 10.0, 10, 100.0),
    'armor': (2, 6, 20.0, 5, 100.0),
    'ability_strength': (3, 6, 3.0, 5, 15.0),
    'energy': (5, 6, 10.0, 5, 50.0),
}

# Ability stat handling (wiki: Abilities / Ability Efficiency): all frames start at
# 100%; mods add percentage points; energy cost cannot drop below 25% of base, which is
# why the arsenal never shows more than 175% Efficiency.
ABILITY_BASE = 100.0
EFFICIENCY_DISPLAY_CAP = 175.0
ENERGY_COST_FLOOR = 0.25

RANK_SCALED_STATS = ('health', 'shield', 'energy', 'armor')


def rank_steps(rank, first_rank, step, steps, max_rank=MAX_RANK_FRAME):
    """How many +steps of a schedule have landed by `rank`."""
    if rank <= 0 or rank < first_rank:
        return 0
    rank = min(rank, max_rank)
    return min(steps, (rank - first_rank) // step + 1)


def frame_rank_bonus(frame_name, stat, rank, max_rank=MAX_RANK_FRAME):
    """(bonus, exact) for one rank-scaled stat of one frame.

    exact=False means the total is the documented rank-30 value spread over the default
    cadence - the engine reports that as an approximation instead of hiding it.
    """
    name = str(frame_name or '').strip().lower()
    rank = max(0, int(rank or 0))
    rank = min(rank, max_rank)
    if name in NIDUS_FRAMES:
        row = NIDUS_SCHEDULES.get(stat)
        if row is None:
            return 0.0, True                     # Nidus shields stay 0
        first, step, amount, steps, _total = row
        return amount * rank_steps(rank, first, step, steps, max_rank), True
    if name in RANK_BONUS_EXCEPTIONS:
        index = RANK_EXCEPTION_ORDER.index(stat) if stat in RANK_EXCEPTION_ORDER else None
        if index is None:
            return 0.0, True
        total = float(RANK_BONUS_EXCEPTIONS[name][index])
        if rank >= max_rank:
            return total, True
        first, step, _amount, steps, _t = RANK_STEP_DEFAULT.get(stat) or (1, 3, 10.0, 10,
                                                                         total)
        return total * rank_steps(rank, first, step, steps, max_rank) / float(steps), False
    row = RANK_STEP_DEFAULT.get(stat)
    if row is None:
        return 0.0, True
    first, step, amount, steps, _total = row
    return amount * rank_steps(rank, first, step, steps, max_rank), True


def frame_stat_at_rank(stat, base, rank, frame_name=None, max_rank=MAX_RANK_FRAME):
    """A frame stat at `rank`: rank-0 base + the frame's rank-up bonus."""
    bonus, _exact = frame_rank_bonus(frame_name, stat, rank, max_rank)
    return float(base or 0.0) + bonus
