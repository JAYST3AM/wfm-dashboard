# Capacity & Polarity — WARFRAME Wiki rules (citation-backed)

Scope: mod capacity pools, polarity drain rules, Aura/Stance slots, Forma, Exilus slots, duplicate-mod
and capacity-providing-mod rules. Everything below is quoted or paraphrased **only** from
wiki.warframe.com pages retrieved **2026-09-29 (AUS Eastern)**; every rule carries a `Source:` line.
Wiki text that contradicts itself, or leaves something genuinely unstated, is flagged
`UNSTATED — do not guess` / `WIKI SELF-CONTRADICTION`. No code (formulas only).

---

## 1. Mod capacity

- **Capacity is a function of the item's rank, not a fixed number.**

  > "Items have a limited **Mod Capacity**, that correlates to their Rank. The maximum rank is normally **30**, but for some items it is **40**."
  > "From the Arsenal, you can install mods on your equipment, but they are limited by the equipment's **Mod Capacity** that depends on the level of the equipment."
  > "Weapons can be leveled up to gain more mod capacity, allowing for the installation of more mode to increase the weapon's power."

  Source: https://wiki.warframe.com/w/Mod (§Installation) — retrieved 2026-09-29
  Source: https://wiki.warframe.com/w/Weapons (§Overleveling intro) — retrieved 2026-09-29

- **"1 capacity per rank" — the wiki never writes that sentence verbatim.** It fixes the value only
  through numbers: rank 30 ⇒ 30 capacity (60 supercharged), rank 40 ⇒ up to 80 supercharged. Treat the
  arithmetic as fixed by those quotes, the wording as `UNSTATED — do not guess`.

  > "An applied Orokin Catalyst will double the weapon's mod capacity. For an **MR 10** player, an unranked weapon with a Catalyst installed will have a capacity of **20**, which will increase to **60** at rank 30."

  Source: https://wiki.warframe.com/w/Orokin_Catalyst (§Using Orokin Catalyst on Equipment) — retrieved 2026-09-29

- **Max rank: normally 30, sometimes 40.** Which items reach 40 (Overleveling: +2 max rank per Forma,
  up to rank 40 after 5 polarizations):

  > "Weapons that can be overlevelled includes: Necramechs, Paracesis, Kuva Weapons, Tenet Weapons, and Coda Weapons."
  > "**Mod** capacity from the additional ranks gets doubled by [Orokin Catalyst] or [Orokin Reactor], allowing for a total of up to **80** mod capacity."

  Source: https://wiki.warframe.com/w/Weapons (§Overleveling) — retrieved 2026-09-29

- **Superchargers double capacity** — Warframes / Companions / Archwings / K-Drives / Necramechs use an
  **Orokin Reactor**; weapons use an **Orokin Catalyst**:

  > "Warframes/Companions/Archwings/K-Drives/Necramechs and Weapons can be supercharged with an Orokin Reactor or Orokin Catalyst respectively, which doubles the available Mod capacity."

  Source: https://wiki.warframe.com/w/Mod (§Installation) — retrieved 2026-09-29

  > "The **Orokin Reactor** is an item used to supercharge Warframes, Archwings, K-Drives, Necramechs, and Companions, doubling their mod capacity."

  Source: https://wiki.warframe.com/w/Orokin_Reactor — retrieved 2026-09-29

  > "Orokin Catalyst is an item used to supercharge all Weapons, including Archguns, Archmelee, or Sentinel Weapons, doubling their mod capacity."

  Source: https://wiki.warframe.com/w/Orokin_Catalyst — retrieved 2026-09-29

  > (supercharger table) "Doubles Warframe, Archwing or Companion Mod capacity. **Affected by rank.**" / "Doubles Weapons Mod capacity. **Affected by weapon rank.**"

  Source: https://wiki.warframe.com/w/Equipment (§supercharger) — retrieved 2026-09-29

  - `UNSTATED — do not guess`: the Equipment table lists the Reactor for "Warframe, Archwing or
    Companion" only, while the Orokin Reactor and Mod pages also include K-Drives and Necramechs. The
    inclusion of K-Drives/Necramechs is stated on two pages and omitted on one; the omission is not an
    explicit exclusion.
  - Catalysts/Reactors are permanent: "Catalysts can only be applied once, and cannot be removed once
    installed." (https://wiki.warframe.com/w/Orokin_Catalyst — retrieved 2026-09-29)

- **Mastery-Rank minimum capacity (a floor on low-rank items).** This is separate from rank:

  > "Items also have a minimum mod capacity, which adds mod points onto items that are a lower rank than a player's current Mastery Rank. The amount of minimum mod capacity is 15, plus **1** per 2 Mastery Ranks.
  > - As an example, a Mastery Rank 6 player would have a minimum mod capacity of 18.
  > - After Mastery Rank 30, minimum mod capacity increases by 1 per Legendary Rank."

  Source: https://wiki.warframe.com/w/Mod (§Installation) — retrieved 2026-09-29

  - `UNSTATED — do not guess`: how the supercharger interacts with this floor. The only worked example
    (MR 10, unranked, catalysed = 20) is consistent with the floor **not** being doubled, but the wiki
    never says so.

- **Slot inventory per equipment type** (needed to know how many slots to model):

  > "Warframes have 8 general slots, an Exilus slot, and an Aura slot. Jade has a second Aura slot."
  > "Primary and secondary weapons have 8 general slots and an Exilus slot."
  > "Melee weapons have 8 general slots, an Exilus slot, and a Stance slot."
  > "Archguns, Archmelees, and Robotic weapons have 8 general slots."
  > "Companions have 10 general slots."
  > "Beast Claws have 8 general slots and a Posture slot."
  > "Archwings and K-Drives have 8 general slots."
  > "Necramechs have 12 general slots."
  > "The Plexus (the Railjack modding system) has 8 general slots and an Aura slot on one grid (Integrated), and 3 special slots on each of the other two grids (Battle and Tactical)."

  Source: https://wiki.warframe.com/w/Mod (§Installation) — retrieved 2026-09-29

### Formula — capacity pool

```
max_rank(item)      = 30 normally; 40 for Necramech / Paracesis / Kuva / Tenet / Coda weapons
supercharged(item)  = has Orokin Catalyst (weapons) or Orokin Reactor (frames/companions/archwing/k-drive/necramech)

capacity_pool(rank) = rank * (2 if supercharged else 1)          # rank 30 -> 30 / 60 ; rank 40 -> 40 / 80

floor(MR)           = 15 + floor(MR / 2)                          # MR 6 -> 18
floor(MR > 30)      = 15 + 15 + (MR - 30)                         # +1 per Legendary Rank

# effective available capacity — the floor is stated; whether the supercharger multiplies the
# floor is UNSTATED (only the MR10 unranked catalysed = 20 example exists)
pool_effective      = max( capacity_pool(rank), floor(MR) )      # supercharger-on-floor: UNSTATED

remaining           = pool_effective - sum(mod drains) + sum(aura/stance/posture bonuses)
```

Sources: https://wiki.warframe.com/w/Mod (§Installation), https://wiki.warframe.com/w/Orokin_Catalyst,
https://wiki.warframe.com/w/Weapons (§Overleveling) — all retrieved 2026-09-29

---

## 2. Polarity: drain adjustment (and yes, mismatch is penalised)

- **Matching polarity halves the drain, rounded UP:**

  > "Matching polarity reduces drain by half, rounded up: (e.g. Serration costs 14, but dropped into a Madurai polarized slot costs only 7)"

  Source: https://wiki.warframe.com/w/Mod (§Installation) — retrieved 2026-09-29

- **MISMATCHED polarity carries a penalty — YES.** Both the Mods page and the Polarity page state it,
  with the same 25% figure and the same rounding buckets:

  > "Non-matching polarity increases drain by a quarter, rounded mathematically: drain of 0-1 will increase by 0, drain of 2-5 by 1, drain of 6-9 by 2, drain of 10-13 by 3, drain 14-16 by 4, etc."

  Source: https://wiki.warframe.com/w/Mod (§Installation) — retrieved 2026-09-29

  > "When a mod is placed into a matching polarity slot, the cost of installing the mod will be reduced by 50%, rounding up to the nearest whole number. In contrast, placing a mod in a slot with a different polarity will increase its cost by 25%. Again, this cost is rounded to the closest integer."

  Source: https://wiki.warframe.com/w/Polarity — retrieved 2026-09-29

  - Neither page names an exception, and neither states a case where a mismatched slot is neutral.
  - `UNSTATED — do not guess`: the +25% bucket table stops at drain 14-16 ("etc."); the value for
    drains ≥ 17 is not enumerated (only the 10-13 → +3 and 14-16 → +4 buckets are given).

- **An un-polarized (blank) slot is neutral** — implied by both rules being conditioned on
  "matching"/"different polarity"; the Aura page states the neutral case explicitly for Aura slots (below).
  `UNSTATED — do not guess` for a general-slot sentence that says blank = unchanged.

- **Polarity kinds** that exist on slots/mods (relevant to what a slot can hold):

  > "Madurai - V (Damage, Powers)"
  > "Vazarin - D (Defensive, Health, Armor)"
  > "Naramon - Dash/Bar (Utility, Misc.)"
  > "Zenurik - Scratch"
  > "Unairu - R"
  > "Penjaga - Y (Companion Abilities)"
  > "Umbra - U (Anti-Sentient Mods)"
  > "Any - O (Universal polarity except Umbra) - Can only be applied by Stance Forma on the Stance slot and Omni Forma on any slot except the Stance slot."

  Source: https://wiki.warframe.com/w/Polarity — retrieved 2026-09-29

### Formula — drain per installed mod

```
drain_effective(drain, slot_polarity, mod_polarity) =
    if slot_polarity == mod_polarity:      ceil(drain / 2)                       # matching, round UP
    if slot_polarity == none:             drain                                 # neutral (Aura page wording)
    else:                                 drain + bump(drain)                    # mismatched = PENALTY

bump(drain) =  0  for drain 0-1
               1  for drain 2-5
               2  for drain 6-9
               3  for drain 10-13
               4  for drain 14-16
               UNSTATED >= 17   # wiki says "etc."
```

Sources: https://wiki.warframe.com/w/Mod (§Installation), https://wiki.warframe.com/w/Polarity,
https://wiki.warframe.com/w/Aura (§Mechanics) — all retrieved 2026-09-29

---

## 3. Aura slots (Warframes) and Stance slots (melee)

- **Auras and Stances do NOT cost drain — they ADD capacity.**

  > "Aura, Stance and Posture mods increase Mod Capacity rather than drain it."
  > "**Drain & Polarity:** The number is the amount of Capacity points a mod uses up when installed ("drain", except Aura/ Stance mods that "provide" Capacity points instead)."

  Source: https://wiki.warframe.com/w/Mod (§Installation, §Attributes) — retrieved 2026-09-29

  > "Additionally, Auras _add_ to your total mod capacity (rather than deduct from it like regular mods), hence higher rank Aura mods are typically more desirable to maximize mod capacity for other mods without the need of Forma."

  Source: https://wiki.warframe.com/w/Aura — retrieved 2026-09-29

- **Matching polarity DOUBLES the Aura's capacity contribution; a blank slot gives the listed value;
  a mismatched slot gives 80% of the listed value, rounded down:**

  > "Furthermore, equipping an Aura with a matching polarity increases mod capacity even more, specifically by double of the Aura's "drain" parameter (e.g. an Aura with a drain of 5 equipped in a matching polarity slot generates an additional mod capacity of 10). In a slot without a polarity, the capacity is the same as the listed drain, and in a slot of a different polarity, the additional capacity is 80% of listed drain, rounded down (e.g. a drain of 5 generates a capacity of 4, a drain of 9 generates a capacity of 7, and so on)."

  Source: https://wiki.warframe.com/w/Aura (§Mechanics) — retrieved 2026-09-29

- **Stances follow the same doubling rule, and level up to give more capacity:**

  > "Similar to Aura mods, Stances can be slotted into a special Stance slot on melee weapons, and they increase a weapon's mod capacity. Stance mods with a matching polarity to the stance slot will double their mod capacity bonus, while non-matching polarities will have reduced capacity bonus. Leveling up Stance mods increases the amount of additional mod capacity they provide, as well as unlocks additional Melee Combos for use."

  Source: https://wiki.warframe.com/w/Stance — retrieved 2026-09-29

  > "All Stances provide a bonus mod capacity of 5 when maxed, doubling it to 10 when placed on the matching polarity."

  Source: https://wiki.warframe.com/w/Stance (§Notes) — retrieved 2026-09-29

- **Only one Aura / one Stance per item:**

  > "They can only be equipped in the dedicated Aura slot and only one Aura can be equipped to a Warframe, or two with Jade."
  > "They can only be equipped in the dedicated Stance slot for a specific weapon type and only one Stance can be equipped to a melee weapon."

  Source: https://wiki.warframe.com/w/Aura, https://wiki.warframe.com/w/Mod (§Special Slot Mods) — retrieved 2026-09-29

- **`WIKI SELF-CONTRADICTION` on the mismatched-Aura/Stance reduction.** Same wiki, same day, three
  different figures:

  | Page | Mismatched Aura/Stance rule as written |
  | --- | --- |
  | Mod (§Installation) | "non-matching polarity reduces it by **25%**, rounded mathematically." |
  | Polarity | "non-matching polarities reduce it by **20%**." |
  | Aura (§Mechanics) | "in a slot of a different polarity, the additional capacity is **80% of listed drain, rounded down**." |

  The Aura page is the only one with a worked example and a rounding direction, and it agrees with the
  Polarity page's 20% (100% − 20% = 80%). Prefer `floor(0.8 × listed drain)`; the Mods page's "25%" is
  unreconciled — `UNSTATED — do not guess` which page is authoritative.
  Sources: https://wiki.warframe.com/w/Mod, https://wiki.warframe.com/w/Polarity,
  https://wiki.warframe.com/w/Aura — all retrieved 2026-09-29

### Formula — Aura / Stance / Posture contribution (added to the capacity pool)

```
bonus(aura_or_stance, slot_polarity) =
    matching polarity      -> 2 * listed_drain                    # "+100%", e.g. 5 -> 10
    slot has no polarity   -> listed_drain                        # e.g. 5 -> 5
    non-matching polarity  -> floor(0.8 * listed_drain)           # Aura page; Mods page says 25% off  [CONFLICT]

# stance cross-check (wiki): every Stance = 5 at max rank, 10 in a matching slot
bonus(maxed_stance, matching) == 10
```

Source: https://wiki.warframe.com/w/Aura (§Mechanics) — retrieved 2026-09-29;
https://wiki.warframe.com/w/Stance (§Notes) — retrieved 2026-09-29

---

## 4. Forma

- **What it does:** adds/removes/alters the polarity of one mod slot.

  > "Forma are items most commonly used as a supercharger to add, remove, or alter the Polarity of a Mod slot on equipment such as Warframes, Archwings, weapons, or Companions. This process is called Polarization…"

  Source: https://wiki.warframe.com/w/Forma — retrieved 2026-09-29

- **Requires rank 30; resets the item to rank 0 (so capacity collapses back to the rank-0 value/floor):**

  > "Forma can only be used on equipment that has already been ranked to 30 and, when used, said equipment is reset to rank 0 (unranked). However, Warframe, Archwing, and Necramech may retain abilities and/or their ranks depending on the player's Mastery Rank…"
  > "Orokin Catalysts and Orokin Reactors are unaffected by the usage of Forma."
  > "Forma can also be used again on already polarized equipment, provided that it is leveled to 30 again."

  Source: https://wiki.warframe.com/w/Forma (§Using Forma on Equipment) — retrieved 2026-09-29

  > "Polarization becomes available to equipment only when it has reached Rank 30."
  > "Using Forma to add/change a polarity slot will reset the equipment's rank to zero, requiring the equipment to be leveled up again."
  > "Currently, there appears to be no cap on the number of times a weapon may be 'polarized' or what polarizations are possible…"

  Source: https://wiki.warframe.com/w/Polarization, https://wiki.warframe.com/w/Polarity (§Polarization) — retrieved 2026-09-29

- **Which polarities Forma can set:** the process is "Click on a slot to cycle through the possible
  polarities" — the set is not enumerated. What *is* stated:
  - "Players cannot _add_ Umbra polarity to slots using mundane Forma. Existing Umbra polarities can be
    replaced with others, but after that, they can only be restored by using an Umbra Forma."
  - "Any - O (Universal polarity except Umbra) - Can only be applied by Stance Forma on the Stance slot
    and Omni Forma on any slot except the Stance slot."
  - Aura slot can be polarized: "The Aura slot can be polarized, either (just as a regular mod slot) with
    a Forma for a specific polarity, or with a special Omni Forma to be universally compatible with any Aura Mod Polarity."
  - `UNSTATED — do not guess`: whether Forma can set Penjaga on an arbitrary general slot, and the full
    enumerated list of selectable polarities.

  Sources: https://wiki.warframe.com/w/Forma (§Using Forma on Equipment, §Notes),
  https://wiki.warframe.com/w/Polarity, https://wiki.warframe.com/w/Aura (§Mechanics) — retrieved 2026-09-29

- **Slot counts** (standard 8 + aura/stance + exilus): see §1 slot inventory quote
  (https://wiki.warframe.com/w/Mod — retrieved 2026-09-29). Exceptions that matter for a planner:
  Companions 10 general slots, Necramechs 12 general slots, Archwings/K-Drives 8 general, Archguns /
  Archmelees / Robotic weapons 8 general (no Exilus listed), Jade has a second Aura slot.

---

## 5. Exilus slots

- **How it unlocks and the item it costs:**

  > "The Exilus slot is present on all Warframes and primary and secondary weapons. On Warframes, the Exilus slot must be unlocked with an Exilus Warframe Adapter, and on weapons, it must be unlocked with an Exilus Weapon Adapter."

  Source: https://wiki.warframe.com/w/Exilus_Mods — retrieved 2026-09-29

  > "Fuses with a Warframe to unlock the Exilus Mod Slot." / "Each Warframe can only have a single Exilus Slot active, and any eligible mods used on the slot will consume mod capacity, like normal mods. An Exilus slot can be polarized using Forma…"

  Source: https://wiki.warframe.com/w/Exilus_Warframe_Adapter — retrieved 2026-09-29

  > "Fuses with a compatible weapon to unlock its Exilus Mod Slot." / "Each weapon can only have a single Exilus Slot active, and any eligible mods used on the slot will consume mod capacity, like normal mods."

  Source: https://wiki.warframe.com/w/Exilus_Weapon_Adapter — retrieved 2026-09-29

- **Costs (acquisition):**
  - Exilus **Warframe** Adapter: "Can be purchased from the Market for **20 Platinum**"; blueprint from
    Cephalon Simaris "after completion of the Natah Quest for **50,000 Standing**"; blueprint from Teshin
    as a Rank 5 Conclave offering for **75,000 Standing**; also Sortie/Archon Hunt drops, Acrithis (20
    Pathos Clamps), Nightwave/1999 Calendar, Twitch drops, Void Surplus.

    Source: https://wiki.warframe.com/w/Exilus_Warframe_Adapter (§Acquisition) — retrieved 2026-09-29

  - Exilus **Weapon** Adapter: blueprint from any Faction Syndicate for **75,000 Standing**; Market
    **20 Platinum** (complete); blueprints from Requiem Relics; complete from Acrithis for 20 Pathos
    Clamps. Crafting: **25,000 Credits + 1 Forma + 1 Exceptional Sentient Core + 1 Orokin Cell**, 23 hrs.
    "To fuse an Exilus Weapon Adapter onto a melee weapon, the player must first complete the quest
    Whispers in the Walls."

    Source: https://wiki.warframe.com/w/Exilus_Weapon_Adapter (§Acquisition) — retrieved 2026-09-29

- Exilus mods may also be put in **general** slots: "Exilus Mods are utility or mobility-based mods that
  can be equipped in the Exilus slot, or if the player chooses, in a general slot."
  Source: https://wiki.warframe.com/w/Exilus_Mods — retrieved 2026-09-29
- **Wiki inconsistency to be aware of:** the Exilus Mods page says the slot exists "on all Warframes and
  primary and secondary weapons", while the Mods slot table gives melee weapons an Exilus slot and the
  Exilus Weapon Adapter page says it "can be fused with a Primary, Secondary or Melee weapon". The melee
  Exilus slot is stated twice; the Exilus Mods page's list looks incomplete. `UNSTATED — do not guess`
  which sentence is authoritative.
  Sources: https://wiki.warframe.com/w/Exilus_Mods, https://wiki.warframe.com/w/Mod,
  https://wiki.warframe.com/w/Exilus_Weapon_Adapter — retrieved 2026-09-29

---

## 6. Duplicate mods, and mods that ADD capacity (negative `baseDrain`)

- **The same mod cannot be installed twice on one item; variants of the same mod cannot be mixed either.**

  > "Players **cannot** install duplicate mods onto a single piece of equipment. Likewise, different variants of the same mod **cannot** be equipped together. For example, a given pistol can only accept one Hornet Strike mod at a time, and Flow, Primed Flow, and Archon Flow…"

  Source: https://wiki.warframe.com/w/Mod (§Standard Mods and Variants) — retrieved 2026-09-29

  (Note: "Any mod can be installed/removed freely and can be applied to several pieces of equipment
  at the same time." — one copy may be equipped on many different items. Source: https://wiki.warframe.com/w/Mod — retrieved 2026-09-29)

- **Which mods add capacity:** Aura (Warframe Aura slot, and Railjack/Plexus Aura), Stance (melee Stance
  slot), Posture (Beast Claws Posture slot) — quoted in §3. Regular mods always drain.
  Source: https://wiki.warframe.com/w/Mod (§Installation: "Aura, Stance and Posture mods increase Mod
  Capacity rather than drain it.") — retrieved 2026-09-29

- **What a NEGATIVE `baseDrain` means (WFCD data ↔ wiki rule).** In the wiki the value printed on an Aura
  or Stance card is the capacity it **adds** — it is never subtracted:

  > "The number is the amount of Capacity points a mod uses up when installed ("drain", except Aura/ Stance mods that "provide" Capacity points instead)."
  > "**Base Capacity Cost** refers to the Capacity points of the mod at rank 0."

  Source: https://wiki.warframe.com/w/Mod (§Attributes) — retrieved 2026-09-29

  WFCD's `Mods.json` encodes that sign convention directly: capacity-*providing* mods carry a negative
  `baseDrain`, everything else carries a positive one. Retrieved 2026-09-29 and verified in the file:

  | Name | `type` | `compatName` | `polarity` | `baseDrain` | `fusionLimit` |
  | --- | --- | --- | --- | --- | --- |
  | Corrosive Projection | Warframe Mod | AURA | naramon | −2 | 5 |
  | Energy Siphon | Warframe Mod | AURA | naramon | −2 | 5 |
  | Steel Charge | Warframe Mod | AURA | madurai | −4 | 5 |
  | Crimson Dervish | Stance Mod | Swords | madurai | −2 | 3 |
  | Blind Justice | Stance Mod | Nikanas | madurai | −2 | 3 |
  | Serration | Primary Mod | Rifle | madurai | +4 | 10 |
  | Vitality | Warframe Mod | WARFRAME | vazarin | +2 | 10 |

  Sign census over all 1809 entries: **every** `Stance Mod` (78) and `Posture Mod` (6) is negative; the
  negative `Warframe Mod` entries (36) are the Auras; everything else is positive (or a Mod Set entry
  with no `baseDrain`).
  Source: https://raw.githubusercontent.com/WFCD/warframe-items/master/data/json/Mods.json (repo:
  https://github.com/WFCD/warframe-items) — retrieved 2026-09-29

  - Rule for the planner: **negative `baseDrain` ⇒ treat as Aura/Stance/Posture; its magnitude is the
    stated capacity bonus, never a cost.** A matching slot doubles it, a blank slot leaves it as-is, a
    mismatched slot reduces it (see §3).
  - `DERIVED (not wiki-stated)` — the magnitude at a given rank. The wiki only gives points:
    "Base Capacity Cost refers to the Capacity points of the mod at rank 0" (Mod §Attributes) and
    "All Stances provide a bonus mod capacity of 5 when maxed" (Stance §Notes). `|baseDrain| + rank`
    reproduces both (Stance −2 at rank 3 → 5; Stance → 5 when maxed; Serration 4 + 10 = 14 matches the
    wiki's "Serration costs 14"; Aura example "a drain of 9" matches Steel Charge −4 at rank 5).
    The wiki never writes this formula → treat the *formula* as derived, not cited.
    Sources: https://wiki.warframe.com/w/Mod (§Attributes, §Installation),
    https://wiki.warframe.com/w/Stance (§Notes), https://wiki.warframe.com/w/Aura (§Mechanics) — retrieved 2026-09-29

---

## 7. Open items / contradictions (do not silently resolve these in code)

1. **Mismatched Aura/Stance reduction: 25% (Mod page) vs 20% (Polarity page) vs 80% rounded down (Aura
   page).** §3. Prefer the Aura page's worked rule; flag the Mods-page figure.
2. **Whether "1 capacity per rank" is a stated rule.** The wiki states rank↔capacity equivalences
   (30→30/60, 40→up to 80) but never the sentence "1 per rank" → `UNSTATED — do not guess`.
3. **Supercharger × Mastery-Rank floor.** `UNSTATED — do not guess` (§1).
4. **Mismatched-drain bump for drain ≥ 17.** The table ends at "14-16 by 4, etc." → `UNSTATED`.
5. **Exilus slot on melee weapons.** Stated twice, denied once (§5) → `UNSTATED`.
6. **Full list of polarities a plain Forma can set** (notably Penjaga on general slots) → `UNSTATED`.
7. **Necramech/K-Drive supercharger** listed on the Reactor and Mod pages, omitted from the Equipment
   supercharger table → not an explicit exclusion (§1).

---

## Source index (all retrieved 2026-09-29, AUS Eastern)

- https://wiki.warframe.com/w/Mod — §Installation, §Attributes, §Standard Mods and Variants, §Special Slot Mods
- https://wiki.warframe.com/w/Polarity — polarity list, matching/mismatching drain, §Polarization
- https://wiki.warframe.com/w/Polarization — rank-30 requirement, rank reset, no polarization cap
- https://wiki.warframe.com/w/Aura — §Mechanics (capacity contribution), §Notes, §Tips
- https://wiki.warframe.com/w/Stance — capacity bonus, §Notes ("5 when maxed")
- https://wiki.warframe.com/w/Forma — §Using Forma on Equipment, §Notes
- https://wiki.warframe.com/w/Exilus_Mods — slot existence, adapter names
- https://wiki.warframe.com/w/Exilus_Warframe_Adapter — unlock, acquisition costs
- https://wiki.warframe.com/w/Exilus_Weapon_Adapter — unlock, acquisition costs, melee quest gate
- https://wiki.warframe.com/w/Orokin_Catalyst — doubling, MR-10 example, permanent
- https://wiki.warframe.com/w/Orokin_Reactor — which equipment it applies to
- https://wiki.warframe.com/w/Equipment — supercharger table ("Affected by rank")
- https://wiki.warframe.com/w/Weapons — §Overleveling (rank 40, up to 80 capacity)
- https://raw.githubusercontent.com/WFCD/warframe-items/master/data/json/Mods.json — `baseDrain` / `fusionLimit` sign convention
