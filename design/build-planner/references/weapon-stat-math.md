# Weapon Stat Math — WARFRAME Wiki reference

Citation-backed rules for the build-planner damage engine. Every claim carries a `Source:` line with the wiki URL it was quoted from.

- **All URLs retrieved:** 2026-09-29 (AUS Eastern, UTC+10)
- **Wiki:** `wiki.warframe.com` (the current community wiki; Damage is **version 3.0** since Update 36.0, 2024-06-18)
- Notation used below copies the wiki verbatim, including its capitalisation of stat names ("Total Critical Chance", "Modded Crit Chance").
- Where the wiki does not state something, it is marked **UNSTATED — do not guess**.

---

## 0. Global stacking rules

Every stat calculation on the wiki is one of these two shapes.

```
Additive stacking:       Resultant Stat Value = Base Stat Value × (1 + Additive Stat Bonus 1 + Additive Stat Bonus 2 + ...)
Multiplicative stacking: Resultant Stat Value = Base Stat Value × (1 + Multiplicative Stat Bonus 1) × (1 + Multiplicative Stat Bonus 2) × ...
```

> "All sources that add a percent bonus of the same type will _typically_ have their bonuses added together. This commonly referred to as **additive stacking** (internally represented as `STACKING_MULTIPLY` operation type)."
> "Sources that affect the same fundamental stat but have different conditions for granting its bonuses will _typically_ have their bonuses multiplied together (but not always such as Chroma's Vex Armor additively stacking with base damage mods). This is commonly referred to as **multiplicative stacking**."

`Source: https://wiki.warframe.com/w/Calculating_Bonuses` (sections "Additive Stacking" / "Multiplicative Stacking")

Two important carve-outs the wiki states up front:

> "With the exception of mods that provide elemental damage bonuses, the order in which mods are installed **does not matter**; the resultant stats will always be the same regardless of the mod configuration."

`Source: https://wiki.warframe.com/w/Calculating_Bonuses` (intro)

```
Modded Stat       = Base Stat × (1 + Stat Bonuses)
Modded Stat Time  = Base Stat Time / (1 + Stat Speed Bonuses)
```

> "Basic formula for calculating modded stats (e.g. critical chance) with the exception of accuracy, reload time, and charge time."
> "Formula for calculating modded reload time and charge time."

`Source: https://wiki.warframe.com/w/Damage/Calculation` (section "Modded Stats")

**Note the division, not multiplication, on time stats.** Speed bonuses are additive in the denominator; time stats use `Modded Stat Time` instead of `Modded Stat`.

---

## 1. Base damage and damage mods

### 1.1 The damage application order

The wiki gives an explicit ordered procedure. This is the authoritative statement for how `+% Damage` interacts with everything else.

```
1. Base damage bonuses are summed and applied to base damage.
   Both physical and elemental bonuses are then computed FROM that modified base damage.
2. Elemental and physical bonuses are calculated based on the MODIFIED base damage.
3. Faction damage bonuses are applied to ALL damage types (not shown in arsenal).
4. Critical Hit / armour / damage-reduction mechanics then modify the result.
```

> "When calculating damage, first base damage bonuses are added together and applied. For example, the Karak has a base damage of 29. Equipping a max rank Serration (+165% base damage) adds 1.65 × 29 = 47.85 additional damage for a total of 76.85 damage (the arsenal will round this number to 76.9). **The added damage will be of the same damage type distribution the weapon innately deals.**"
> "Then, all elemental and physical damage bonuses are calculated based on the modified base damage. For example, adding a Hellfire (+90% Heat damage) to a Karak that already has Serration equipped will add 90% of 76.85 for a total of 69.165 Heat damage."
> "After that, faction damage bonuses are applied to all damage types. Note that faction damage bonuses will not be accounted for in the arsenal stats."
> "Once damage is calculated, it may be affected by Critical Hit mechanics or modified based on the opponent's armor or sources of damage reduction."

`Source: https://wiki.warframe.com/w/Calculating_Bonuses` (section "The Damage Application Order")

### 1.2 Does an elemental mod scale off base damage INCLUDING the +damage bonus? — **YES**

Stated twice, unambiguously.

> "Serration damage is applied before any other damage type. Therefore, every other damage increasing mod benefits from Serration. E.g. a weapon with a base damage of 18 equipped with a rank 9 Serration mod (150%) would have a new base damage of 45: 18 × (1 + 1.5) = 45"
> "This new base damage will be what is used to calculate elemental damages."

`Source: https://wiki.warframe.com/w/Serration` (section "Notes")

> "Elemental bonuses calculate using the **full** base damage, are rounded to the nearest 1/32nd of the base damage and added to the total."

`Source: https://wiki.warframe.com/w/Damage/Calculation` (section "Adding Physical and/or Elemental Mods/Bonuses")

The arsenal formula encodes the same thing (elemental bonus and `(1 + Damage Bonuses)` both present):

```
Arsenal Total Damage =
    Base Damage
  × [ 1 + Elemental Bonuses
        + Unmodded Impact Distribution   × Impact Bonuses
        + Unmodded Puncture Distribution × Puncture Bonuses
        + Unmodded Slash Distribution    × Slash Bonuses ]
  × (1 + Damage Bonuses)
  × [ Base Weapon Multishot × (1 + Multishot Bonuses) ]
```

> "This arsenal damage is the average non-crit damage per shot, without Faction Damage Bonus."
> "For melee weapons, remove multishot from the equation. It does not include Stance damage multipliers."

`Source: https://wiki.warframe.com/w/Damage/Calculation` (section "Total Damage")

### 1.3 Damage types are additive components of a weapon's damage

```
Weapon Damage = (Impact + Puncture + Slash) + (Elemental Damage Types)
```

> "Elemental Damage can be applied on top of a weapon's base damage depending on what Elemental Mods are applied. Elemental Damage is applied in addition to a weapon's physical damage types."

`Source: https://wiki.warframe.com/w/Damage` (section "Elemental Damage"; also redirected from `Elemental_Damage`)

> "The overall physical damage of any given weapon is the sum of Impact, Puncture, and Slash damage. This is sometimes referred to as **IPS**."

`Source: https://wiki.warframe.com/w/Damage` (section "Physical Damage")

### 1.4 How multiple `+% Damage` mods combine — additive with each other

```
Total Damage Bonus = Bonus1 + Bonus2 + ...          (additive)
```

> "Additively stacks with Heavy Caliber for a maximum of +330% damage."
> "Multiplicatively stacks with Faction Damage Mods for a maximum of +244.5% damage."

`Source: https://wiki.warframe.com/w/Serration` (section "Notes")

> "For example, if a primary weapon has Serration (+165% damage) and Heavy Caliber..." — given as the worked example of additive stacking.

`Source: https://wiki.warframe.com/w/Calculating_Bonuses` (section "Additive Stacking / Percent Bonuses")

### 1.5 Do two elemental mods of the same element stack additively? — **YES (sum rule, stated)**

```
Element total = Mod 1 %  +  Mod 2 %  + ...   ; the SUM is then quantized as one value
```

> "Elements formed by a sum of mods and bonuses quantize their sum alone. For example, if 90% Cold combined with 90% Toxin, or 90% modded Radiation combined with 90% of Smite Infusion, these types would count separately as a sum of their final element (180% Viral, or 180% Radiation), each rounded to the nearest 1/32 of base damage, and finally added to the quantized total."

`Source: https://wiki.warframe.com/w/Damage/Calculation` (section "Adding Physical and/or Elemental Mods/Bonuses")

> "As well, when using multiple mods with the same element, the first position that element is placed in establishes its hierarchy and where it's combined."

`Source: https://wiki.warframe.com/w/Damage` (section "Modding")

**UNSTATED — do not guess:** the wiki prints a worked example of two *different* primary elements summing into one secondary (90% Cold + 90% Toxin = 180% Viral), but no printed example of two mods of the *same* element summing (e.g. Hellfire 90% + Thermite Rounds 60%). The sum rule above is stated; the same-element worked figure is not.

### 1.6 Damage quantization (the 1/32 rounding) — matters for reproducing displayed numbers

```
Scale            = Modded Base Damage / 32
x                = Total Damage Type Value / Modded Base Damage
Quantized(x)     = sign(x) × ⌊ |x| × 32 + 0.5 ⌋ / 32
Quantized Damage Type Value = Quantized(x) × Modded Base Damage
```

> "**Dealing damage is [quantized].** Meaning, rather than the damage being applied smoothly, physical and elemental damages round to the nearest multiple of 1/32nd of their attack's base damage, before being multiplied further."
> "This quantized value is used in mission damage calculations. The final damage seen in damage pop-ups is further rounded to a whole number."
> "Elemental and Physical bonuses do not affect the scale."
> "Damage mods such as Hornet Strike, Faction Damage Bonus such as Bane of Grineer, and any other multipliers only multiply final quantized values and do not affect the scale or damage composition."

`Source: https://wiki.warframe.com/w/Damage/Calculation` (section "Quantization")

The page also flags a **conflicting pair of statements** about whether `+Damage` (Serration) is applied before or after quantization:

> Conflicting info:
> - "Damage mods such as Hornet Strike, Faction Damage Bonus such as Bane of Grineer, and any other multipliers only multiply final quantized values and do not affect the scale or damage composition."
> - "Applying +Damage, +Faction or any other non-elemental bonus multiplies both the base value of rounding numerator and Scale of rounding denominator, and therefore is a simple multiplier to any quantized total."

`Source: https://wiki.warframe.com/w/Damage/Calculation` (section "Quantization")

**Practical read:** either interpretation is a plain multiplier on the quantized total for `+Damage`. Implement `+Damage` as a final multiplier.

---

## 2. Elemental combination order

### 2.1 Which mod slot "wins" — slot placement hierarchy, top-left first

> "**Elemental Damage Combinations** are made by following a mod placement hierarchy. This hierarchy is from closest to top left (first to be considered) to the bottom right (last to be considered) on the mod layout. Innate weapon elemental damages are considered the very last in any hierarchy, with one exception: [Kuva/Tenet dual-innate weapons — see 2.4]."

`Source: https://wiki.warframe.com/w/Damage` (section "Modding")

The slot grid used for this priority (paired with the rule above):

```
1 | 2 | 3 | 4
5 | 6 | 7 | 8
```

> "**Mod priority order** — **(for Companion Precepts and Elemental Damage mods)**"

`Source: https://wiki.warframe.com/w/Mods` (section "Mod Slots")

### 2.2 HCET order (progenitor dual-innate tiebreak)

```
Heat > Cold > Electricity > Toxin        ("HCET" for short)
```

> "In these cases, whichever of the two primary elements comes first in this element order - Heat > Cold > Electricity > Toxin, or **"HCET"** for short - will be placed second to last in the element combine order, while the other primary element will be placed last in the combine order."

`Source: https://wiki.warframe.com/w/Damage` (section "Modding")

### 2.3 Innate elemental weapon damage

> "However, a weapon's innate elemental damage can be forced into a different position in the hierarchy (and thus be combined into a secondary element earlier) if the player has equipped a mod of the same element as the innate element."
> "A weapon's innate elemental damage will contribute to elemental combinations, as long as the combination has been established earlier in the hierarchy. It can also combine with the last uncombined elemental mod in the hierarchy to form a secondary element."

Worked example on the same page:

> "[A] weapon with Electricity such as the Prova or the Lecta, then adding Cold, Toxin, and Heat in 1, 2 and 3 respectively get: Viral (Cold + Toxin) and Radiation (Heat + Electricity)."

`Source: https://wiki.warframe.com/w/Damage` (section "Modding")

Weapons with an **innate secondary** element are a separate case:

> "Weapons with innate secondary elements such as Ogris (Blast), Penta (Blast), Stug (Corrosive), Nukor (Radiation) and Detron (Radiation) will **always** have that damage type, regardless of mods used. On weapons like these, basic elemental damage mods will combine and function _independently_ of the innate secondary elements, as basic elements **cannot** combine with a weapon's already combined innate damage type."

`Source: https://wiki.warframe.com/w/Damage` (section "Modding")

### 2.4 Dual-innate (Kuva / Tenet progenitor)

> "[Kuva Weapons] and [Tenet Weapons] will follow this behavior too. For example, a Tenet Detron (Radiation) can come with an additional Electricity Progenitor damage bonus that will **not** add onto the innate Radiation damage."

`Source: https://wiki.warframe.com/w/Damage` (section "Modding")

And the two-primary-innates case quoted in 2.2: the higher (HCET) of the two innate elements is inserted **second-to-last** in the combine order; the other innate goes **last**.

`Source: https://wiki.warframe.com/w/Damage` (section "Modding")

### 2.5 Riven mods with two elemental stats

> "In the case of Riven Mods where there is more than one elemental stat present, the hierarchy priority will be given to the **last** elemental stat listed on the Riven mod."
> "If no other elemental damage mods are present, the elements on the Riven mod will combine with itself."

`Source: https://wiki.warframe.com/w/Damage` (section "Modding")

### 2.6 Pair -> secondary element (complete table, all 6 combinations)

| Secondary element | = Primary A | + Primary B | Internal name | Status internal name |
| --- | --- | --- | --- | --- |
| Blast | Cold | Heat | `DT_EXPLOSION` | `PT_FLASHBANG` |
| Corrosive | Electricity | Toxin | `DT_CORROSIVE` | `PT_CAUSTIC_BURN` |
| Gas | Heat | Toxin | `DT_GAS` | `PT_ASPHYXIATION` |
| Magnetic | Cold | Electricity | `DT_MAGNETIC` | `PT_MAGNETIZED` |
| Radiation | Electricity | Heat | `DT_RADIATION` | `PT_RAD_TOX` |
| Viral | Cold | Toxin | `DT_VIRAL` | `PT_INFECTED` |

> "Except by using weapons with innate secondary elemental damage, or mods which give a secondary element such as Magnetic Might, it is impossible to add more than two elemental damage types on a single weapon. There are only four types of primary elemental damage and every two types of primary elemental damage will be automatically combined into a secondary type."

`Source: https://wiki.warframe.com/w/Damage` (section "Possible Combinations" and "Secondary Elemental Damage")

The same pairings are listed again on the overview table, e.g. "Blast (Heat + Cold)", "Corrosive (Electricity + Toxin)", "Gas (Heat + Toxin)", "Magnetic (Cold + Electricity)", "Radiation (Heat + Electricity)", "Viral (Cold + Toxin)".

`Source: https://wiki.warframe.com/w/Damage/Overview_Table`

Note the wiki's own ordering in the pair column is not alphabetical or HCET — do not derive order from it. The `Heat + Cold`, `Cold + Heat` presentation is cosmetic; the *behaviour* (which element is "first") is governed by 2.1/2.2/2.3 only.

Combined elements stop dealing their components:

> "Note that a primary elemental damage type that has been combined into a secondary type will no longer be dealt to the weapon's targets, nor its status effect will be applied to the targets either."

`Source: https://wiki.warframe.com/w/Damage` (section "Elemental Damage")

The wiki's "Possible Combinations" table additionally shows which **pairs of elements** can coexist on one weapon (e.g. Cold is only possible alongside Corrosive, Gas or Radiation) — that is the co-existence table, not the combination-product table.

`Source: https://wiki.warframe.com/w/Damage` (section "Possible Combinations")

---

## 3. Critical hits

### 3.1 Total critical chance — relative vs absolute

```
Total Critical Chance = Base Critical Chance × (1 + Relative Bonus)
Relative Bonus        = Bonus1 + Bonus2 + Bonus3 + ...
```

> "Most increases to critical chance are relative **to the base chance**. Multiple of these stack additively with each other:"

Example from the page: `12% × (1 + 150% + 135%) = 46.2%`

```
Total Critical Chance = Base Crit Chance × (1 + Relative Bonus) + Absolute Bonus
Absolute Bonus        = Bonus1 + Bonus2 + Bonus3 + ...
```

> "A few effects grant absolute (also called flat) amounts of critical chance which are applied after relative bonuses." (Arcane Avenger, Cat's Eye, Covenant, Puncture's "Weakened", Secondary Enervate, Shadow Haze)

Example from the page: `12% × (1 + 150%) + 45% = 75%`

`Source: https://wiki.warframe.com/w/Critical_Hit` (sections "Relative Increases" and "Absolute Increases")

Melee combo exception (Blood Rush / Gladiator):

```
Total Crit Chance = Base Crit Chance × (1 + Relative Bonus + Blood Rush Multi × (Combo Multi − 1)) + Absolute Bonus
```
`Source: https://wiki.warframe.com/w/Critical_Hit` (section "Blood Rush")

### 3.2 Total critical damage multiplier

```
Total Critical Damage Multiplier = Base Critical Damage Multiplier × (1 + Relative Bonus)
Total Critical Damage Multiplier = Base Critical Damage Multiplier × (1 + Relative Bonus) + Absolute Bonus
```

> "Most increases to critical damage are relative **to the base multiplier**. Multiple of these stack additively with each other:"
> "A few effects grant absolute (also called flat) amounts of critical damage which are applied after relative bonuses." (Arcane Crepuscular, Cold's "Freeze", Shroud of Dynar)

`Source: https://wiki.warframe.com/w/Critical_Hit` (section "Critical Damage")

### 3.3 Crit tiers for total chance > 100%

| Total Crit Chance | Outcome | Tier |
| --- | --- | --- |
| x ≤ 0% | no hit can crit | Tier 0 |
| 0% < x < 100% | chance for a yellow crit | Tier 1 |
| x = 100% | all hits yellow crit | Tier 1 |
| 100% < x < 200% | chance for an orange (**Big**) crit | Tier 2 |
| x = 200% | all hits **Big** crit | Tier 2 |
| 200% < x < 300% | chance for a red (**Super**) crit | Tier 3 |
| x = 300% | all hits **Super** crit | Tier 3 |
| 300% < x < 400% | chance for a red ! crit | Tier 4 |
| x = 400% | all hits red crit | Tier 4 |
| 400% < x < 500% | chance for a red !! crit | Tier 5 |
| x = 500% | all hits red crit | Tier 5 |
| 500% < x < 600% | chance for a red !!! crit | Tier 6 |
| ... | ... | ... |

> "When a weapon achieves a critical chance **higher than 100%**, every attack will crit but it also gains a chance to deal an even stronger crit. As the critical chance increases, the tier of critical damage does so as well."
> "Although the coloration remains red after a certain point, critical tiers continue to increase. Every tier above 3 will produce an additional exclamation mark (!) up to three times."

`Source: https://wiki.warframe.com/w/Critical_Hit` (section "Critical Tiers")

### 3.4 Damage multiplier per tier

```
Critical Tier Multiplier = 1 + Critical Tier × (Total Critical Damage Multiplier − 1)
```

> Example from the page: a Lenz with Point Strike and Vital Sense has an orange critical multiplier of `1 + 2 × (2.0 × (1 + 120%) − 1) = 7.8x`

Also stated (Vigilante set): "each mod of the Vigilante Mod Set has a **5%** chance to increase a Primary Weapon's critical hit's tier by 1 ... up to a **30%** chance with all six Vigilante Mods equipped."

`Source: https://wiki.warframe.com/w/Critical_Hit` (section "Critical Tiers")

### 3.5 Average damage formula

```
Average Damage Multiplier = 1 + Total Critical Chance × (Total Critical Damage Multiplier − 1)
Average Damage on Hit     = Modded Damage × Average Damage Multiplier
```

> "The following equation accounts for critical hits that are not headshots:"
> Example: a Paris has `1 + 30% × (2.0 − 1) = 1.3x`; with Point Strike and Vital Sense `1 + (30% × (1 + 150%)) × (2.0 × (1 + 120%) − 1) = 3.55x`

`Source: https://wiki.warframe.com/w/Critical_Hit` (section "Average Damage")

The same average-shot form appears in the full damage calculation, broken into floor/ceil tiers:

```
Normal Shot    = Total Damage × [1 + (⌊Modded Crit Chance⌋ × (Modded Crit Multiplier − 1))]
Critical Shot  = Total Damage × [1 + (⌈Modded Crit Chance⌉ × (Modded Crit Multiplier − 1))]
Average Shot   = Total Damage × (1 + Modded Crit Chance × (Modded Crit Multiplier − 1))
```

> "In the case where modded critical chance is over 100%, the lowest crit tier possible will be considered a normal shot. (e.g. if a weapon has 250% crit chance, the 100% for an orange crit will be considered a normal shot)"
> "In the case where modded critical chance is over 100%, the next crit tier possible will be considered a critical shot (e.g. if a weapon has 250% crit chance, the 50% for a red crit will be considered a critical shot)"

`Source: https://wiki.warframe.com/w/Damage/Calculation` (section "Average Shot/Hit")

### 3.6 Critical multiplier quantization (IS stated)

Critical *damage* (not the per-tier multiplier) is quantized before mods:

```
Code(x)                 = ⌊ clamp(x, 0, 32) × 4095 / 32 + 0.5 ⌋
Quantized Base CDM(x)   = Code(x) × 32 / 4095
```

> "The base critical damage multiplier of a weapon is quantized. This applies before mods, but after certain effects that are additive to the base value. Before encoding, the base critical damage multiplier x is clamped to the range from 0 to 32. The exact 12-bit integer code and decoded multiplier are:"
> "The 4096 possible codes range from 0 to 4095, so adjacent decoded values differ by 32/4095. The calculation uses 32-bit floating-point arithmetic."

`Source: https://wiki.warframe.com/w/Critical_Hit` (section "Quantization")

### 3.7 Headshot and crit-headshot behaviour (stated)

```
Headshot Crit Tier Multi = Headshot Multi × (1 + Critical Tier × (2 × Total Critical Damage Multiplier − 1))
```

> "Certain body parts on enemies, most notably heads, will receive additional damage when struck. This location-based damage increase is usually a 3.0x multiplier, but if the strike is a critical hit, then it receives an additional damage bonus of **2.0x** _on top_ of the location multiplier and the critical damage multiplier:"
> Example: a Lanka with Vital Sense and a headshot multiplier of 3.0 has an orange critical damage multiplier of `3.0 × (1 + 2 × (2 × 2.0 × (1 + 120%) − 1)) = 49.8x`
> "The Headshot Multiplier is 3.0x in almost all cases. The bonus damage from headshot crits is specific to heads and not generalized to all special body parts."
> "Corpus humanoids do **not** receive headcrits, instead only taking the normal 3.0x headshot damage even after their helmets are removed. If a weapon defaults to a 1x headshot multiplier it will not benefit from the critical bonus, this is true even if the headshot multiplier is raised."

`Source: https://wiki.warframe.com/w/Critical_Hit` (section "Critical Headshots")

Weak-point hits are a separate multiplier in the damage calculation:

```
Average Shot(WeakPoint) = Average Shot × (Weak Point Multiplier + Weak Point Damage Bonus)
Average Shot(WeakPoint) = Average Shot        # for weapons with no headshot bonus (e.g. Arca Plasmor); AoE cannot headshot
```
> "Weak Point Damage bonuses include Target Acquired (headshots), Primary Acuity, and Pistol Acuity"

`Source: https://wiki.warframe.com/w/Damage/Calculation` (section "Single Target Weak Point Hit")

### 3.8 Each projectile rolls crit separately

> "Each attack, or each pellet in the case of most shotguns and weapons with Multishot, rolls its own chance to critically hit."

`Source: https://wiki.warframe.com/w/Critical_Hit` (intro)

---

## 4. Multishot

### 4.1 What it does numerically — whole projectiles plus a fractional chance

```
Total Projectiles = Weapon Projectile Count × (1 + Multishot Modifier)
```

> "You can calculate a weapon's projectile count using the following equation;"
> "**Weapon Projectile Count** refers to the base number of projectiles fired per weapon attack."
> "**Multishot Modifier** refers to the total value of all related mods added together."
> "Should the total projectile count be a fraction, the fractional part will be a chance to fire one more projectile."

Worked examples from the page:

> "Lex ... with +180% Multishot will have Multishot equaling 2.8. It will, therefore, possess 2 damage instances (projectiles) per shot with an 80% chance of a third damage instance on that shot."
> "Hek, a hitscan projectile weapon with a base Multishot of 7, with Hell's Chamber will have Multishot equaling 15.4. This means it will possess 15 damage instances per shot with a 40% chance of 16th damage instance."

Also worth encoding: "The effectiveness of the Multishot bonus is affected by a weapon's Accuracy stat."

> "The resulting value's integer component expresses the number of shots, and the fractional component (the value after the decimal point) expresses the chance that one more additional projectile will be fired (e.g. \"1.2\" means one projectile with a 20% chance of an additional one)."

`Source: https://wiki.warframe.com/w/Multishot` (intro and section "Calculating Multishot")

### 4.2 How it affects DISPLAYED damage — arsenal shows the *average*

> "If the weapon has multishot from a mod like Split Chamber, it will have a percent chance to fire additional projectiles per shot, each of which will deal the full modded damage as if one projectile was shot. **The arsenal will display multishot bonuses as percent increases in total damage when in fact this is not true in reality. The total damage stat shown in the arsenal actually reflects the _average_ damage dealt per shot in this case.**"
> "For example, a Karak with only Split Chamber equipped will see a 29 × 0.9 = 26.1 increase in damage for an average of 55.1 damage per shot."
> "For weapons that only fire a single projectile, Split Chamber's 90% multishot will cause each shot to randomly have a 90% chance to fire two projectiles instead of one."
> "On continuous beam weapons like the Glaxion, multishot adds a chance to increase damage on a tick."

`Source: https://wiki.warframe.com/w/Calculating_Bonuses` (section "Multishot")

The arsenal formula's multishot term matches (average damage per shot):

```
... × [ Base Weapon Multishot × (1 + Multishot Bonuses) ]
```
`Source: https://wiki.warframe.com/w/Damage/Calculation` (section "Total Damage")

### 4.3 How it affects displayed STATUS chance — it does NOT change per-hit status

> "One can also increase the number of projectiles fired through multishot mods such as Split Chamber; this effectively increases the opportunities for an enemy to be procced per a given attack, and is reflected in the weapon's attributes box in the Arsenal screen, **but does not change the status chance for each individual hit**."
> "Another indirect way of increasing the amount of procs is to increase fire rate, this also doesn't change the likelihood that a proc will occur per hit, but increases the number of possible procs in a given time frame."

`Source: https://wiki.warframe.com/w/Status_Effect` (section "Status Chance")

### 4.4 Status chance per pellet — shotguns and multishot in general

**Current rule: the Arsenal status chance *is* the per-pellet chance.**

> "When firing multiple pellets in a single attack, the status chance on a listed weapon in the Arsenal is the probability that each pellet will individually proc. For example, the Strun Wraith displays a 12% status chance, so each of its ten pellets has a 12% chance to individually proc."

```
Average Number of Procs Per Shot   = Multishot × (Number of Forced Procs + Status Chance per Projectile)
Average Number of Procs per Second = Average Number of Procs Per Shot × Fire Rate
```

`Source: https://wiki.warframe.com/w/Status_Effect` (section "Multishot")

The old (pre-Update 27.2, 2020-03-05) formula is documented as **historical only** — do not implement it:

> "Prior to Update 27.2 (2020-03-05), shotguns' status chance per pellet were calculated differently, instead of being the exact status chance shown in the Arsenal: `Chance per Pellet = 1 − (1 − Status Chance)^(1 ÷ Pellet Count)`"
> "In other words, the status chance shown in the Arsenal represented the calculated probability that at least one of the weapon's pellets would proc."
> "However, ... The UI now behaves to show the reality that you are determining Status Chance per pellet."

`Source: https://wiki.warframe.com/w/Status_Effect` (section "Trivia" + Update 27.2 patch notes quoted on the page)

### 4.5 Which proc fires first — status is weighted by damage

```
Proc Type Chance = Damage ÷ Total Damage
```

> "Status effect procs will occur in proportion to the amount of base damage dealt by each of the present damage types on the weapon."
> "Increasing the physical or elemental damage of a weapon does not increase the duration of the associated proc."
> "Proc type chances are not altered by enemy resistances or weaknesses to the damage components used in their computation; however, they are modified by enemy status immunities."

`Source: https://wiki.warframe.com/w/Status_Effect` (sections "Damage Distribution" and "Status Immunity Interactions")

### 4.6 Continuous weapons (multishot merges beams)

> "On Continuous Weapons, additional beams that hit the same target instead merge into a singular damage tick. This combined tick has damage **and** Status Chance equal to the **sum** of the individual beams, but the Critical Chance is still equal to that of a single beam."

`Source: https://wiki.warframe.com/w/Multishot` (section "Continuous Weapons")

---

## 5. Status

### 5.1 Per-pellet status formula and >100% status

- Per-pellet: see 4.4 (`Arsenal status chance = per-pellet chance`; `Average Procs per Shot = Multishot × (Forced Procs + Status Chance per Projectile)`).
  `Source: https://wiki.warframe.com/w/Status_Effect` (section "Multishot")

> "When a weapon achieves a status chance **higher than 100%**, each hit may apply additional \" **unique**\" status effects. The type of each proc is independently drawn, so it is possible to apply the same status several times in one hit."
> "A specific status type shown at 100% status chance, when hovering over a weapon's shown Status in the Arsenal, does not guarantee that status effect. An example of this would be a weapon that has 200% Status with only Heat and Impact status effects as possible options can still trigger two heat or two impact status effects regardless of their relative status chance values."
> "If a single attack hits multiple enemies, each enemy gets their own status roll to determine if they will receive a status effect from the attack and which status effect they will receive."

`Source: https://wiki.warframe.com/w/Status_Effect` (section "Status Chance")

So: `statusChance > 100%` ⇒ **guaranteed floor(statusChance/100%) procs**, each independent.

**UNSTATED — do not guess:** the wiki does not state a single closed-form formula for the exact number of extra procs past 100%; it states only the "each hit may apply additional unique status effects, independently drawn" rule above.

### 5.2 Status effect of each damage type (one line each)

Percentages below are of **base damage**; the listed stack cap is what the wiki prints.

| Type | Effect (internal name) | Effect | Stacks / cap |
| --- | --- | --- | --- |
| Impact | Knockback / `PT_KNOCKBACK` | Flinch + stagger 1s; +8% Parazon Mercy threshold per proc | **Up to 5 stacks** (80% total) |
| Puncture | Weakened / `PT_FRAILTY` | −40% target damage dealt, +5% received crit chance, 10s (6s on the Damage page) | **Up to 5 stacks** → −80% damage, +25% crit chance |
| Slash | Bleed / `PT_BLEEDING` | 35% of base damage per second over 6s, bypasses Armor | **Stacks are not limited**; each stack has its own duration |
| Heat | Ignite / `PT_IMMOLATION` | 50% of base damage as Heat per second over 6s (can be refreshed); panic 4s; strips up to 50% Armor over 2s | **Stacks are not limited** (Damage page); the Status Effect page prints no stack cap for Heat |
| Cold | Freeze / `PT_CHILLED` | −50% Move Speed, Fire Rate, Attack Speed; +0.1 crit multiplier, 6s | **Up to 10 stacks** → 90% slow / +0.5 crit mult; 10th stack = Frozen 3s, +1.0 crit mult |
| Electricity | Tesla Chain / `PT_ELECTROCUTION` | 50% of base damage per second over 6s to enemies within 3m; stuns 3s | **UNSTATED — do not guess.** The wiki states only "Each stack has its own duration" (Damage page table); no stack cap is printed |
| Toxin | Poison / `PT_POISONED` | 50% of base damage per second over 6s; bypasses Shields | **Stacks are not limited**; each stack has its own duration |
| Blast | Detonate / `PT_FLASHBANG` | 30% of base damage after 1.5s | **Up to 10 stacks**; on cap or death all stacks detonate at once for 300% of base damage within 5m (initial target excluded) |
| Corrosive | Corrosion / `PT_CAUSTIC_BURN` | −26% armor for 8s | **Up to 10 stacks** → 80% reduced armor |
| Gas | Gas Cloud / `PT_ASPHYXIATION` | 50% of base damage as Gas per second for 6s in a 3m radius | **Up to 10 stacks** → 6m radius |
| Magnetic | Disrupt / `PT_MAGNETIZED` | +100% damage to Shields/Overguard, nullifies shield regen, 6s | **Up to 10 stacks** → +325%; on break, Electricity proc = 3% of max Shields/Overguard per stack, max 30% |
| Radiation | Confusion / `PT_RAD_TOX` | +100% bonus damage to allies, 12s | **Up to 10 stacks** → +550% vs allied units; **bosses cap at 4 stacks** and +250% damage received |
| Viral | Virus / `PT_INFECTED` | +100% damage to Health, 6s | **Up to 10 stacks** → +325% damage to health |

`Source: https://wiki.warframe.com/w/Damage` (sections "Physical Damage", "Primary Elemental Damage", "Secondary Elemental Damage") and `https://wiki.warframe.com/w/Status_Effect` (section "Status Effects / General")

Note the two pages disagree slightly on **Puncture** duration (10s on Status Effect, 6s on Damage) and on **Heat** stacking wording; the values above are the ones each page prints.

Also: `Void` = Bullet Attractor (2.5m field, 3s), `Tau` = Status Vulnerability (+10% received status chance per proc, 8s, up to 10 stacks / +100%), `True` = "No status effect."

`Source: https://wiki.warframe.com/w/Status_Effect` (section "Status Effects / General")

### 5.3 >100% status and stacking — the page's own summary of the mechanic

> "**But wait - THERE'S MORE! In addition to being able to achieve two Status Effects on a single shot with >100% Status, we are also adding new meaning if you get a duplicate Status Effect on an enemy overall.**"

`Source: https://wiki.warframe.com/w/Status_Effect` (Update 27.2 patch notes quoted on the page)

### 5.4 Railjack status effects are separate

Railjack has its own status table (Tear, Immobilize, Scramble, Sear, Intoxicate...). Out of scope for the build planner; do not merge with the ground table.

`Source: https://wiki.warframe.com/w/Status_Effect`

---

## 6. Fire rate / attack speed / reload / magazine / charge time

### 6.1 Fire rate

```
Modded Fire Rate = Base Fire Rate × (1 + Fire Rate Bonuses)     # see §0 Modded Stat
Shot Delay in Seconds = 1 / Modded Fire Rate
```

> "As a general principle, the **Fire Rate bonus increases fire rate linearly, regardless of the Trigger Type** ... For the same reason, apart from increasing the weapon's fire rate in the narrowest sense, the Fire Rate bonus also affects **Spool-up Time** ... and **Charge Time**."
> "Notably, Semi-Auto weapons are capped at 10 rounds per second."
> "Taking the inverse of resultant fire rate will give the time between shots in seconds."
> "Note that the Vectis and Vectis Prime are not affected by this shot delay before reloading and reloads instantly after the last shot instead."

`Source: https://wiki.warframe.com/w/Fire_Rate` (sections "Mechanics" and "Shot Delay")

**Stacking:** the Fire Rate page does **not** print a fire-rate-specific stacking formula. The general additive rule from §0 applies (same-type percent bonuses add into `(1 + Stat Bonuses)`).

`Source: https://wiki.warframe.com/w/Calculating_Bonuses` (section "Additive Stacking / Percent Bonuses") — **the fire-rate-specific statement is UNSTATED.**

Effective fire rate by trigger type (true rate, not the arsenal value):

```
Effective Fire Rate (Auto, Auto-Spool, Semi, Duplex, Held) = Modded Fire Rate
Effective Fire Rate (Charge) = 1 / Modded Charge Time + 1 / Modded Fire Rate
Effective Fire Rate (Burst)  = Burst Count / ( 1 / Modded Fire Rate + [ (Burst Count − 1) · Burst Delay ] )
```

> "Arsenal Fire Rate stat ≠ actual rate of fire in-game"
> "For Burst trigger types, there is a delay between bursts (Fire Rate value) and a delay between shots in a burst (Burst Delay value). For Mag Burst attacks, use the full magazine size as the Burst Count."

`Source: https://wiki.warframe.com/w/Damage/Calculation` (section "Average Burst DPS")

### 6.2 Charge time / charge rate

```
Charge Rate = 1 / Charge Time
Charge Time = Base Charge Time / (1 + Mod Bonus)
Charge Rate = Base Charge Rate × (1 + Mod Bonus)
```

> "Note that charge weapons mislabel the charge time of the attack as the **Charge Rate**. For example, the Scourge lists its \"Charge Rate\" as 0.5, however that is actually the charge time (0.5 **seconds**)."
> "The charge time is the time it takes the charge circle to progress to full."
> "For charged weapons, **charge time cannot go above 10 times the base charge time** (achieved by having at least -90% fire rate bonus)."
> "Effective Fire Rate = 1 / Modded Charge Time + 1 / Modded Fire Rate" — "Calculation for true fire rate for charge weapons with the exception of bows, Epitaph, and Lanka."
> "Effective Fire Rate = 1 / Modded Charge Time + Modded Reload Time" — "Calculation for true fire rate for bow weapons."
> "Effective Fire Rate = 1 / Modded Charge Time" — "Calculation for true fire rate for Lanka which does not have a delay between charged shots."

`Source: https://wiki.warframe.com/w/Fire_Rate` (section "Fire Rate and Charge Time")

**Charge time uses DIVISION** (it is `Modded Stat Time`, §0):

```
Modded Stat Time = Base Stat Time / (1 + Stat Speed Bonuses)
```
> "Formula for calculating modded reload time and charge time."

`Source: https://wiki.warframe.com/w/Damage/Calculation` (section "Modded Stats")

### 6.3 Reload speed

```
Total Reload Time = Weapon Reload Time / (1 + Reload Speed Bonus)
```

> "Reload time is not directly modified with these, but rather reload speed changes. To calculate the resultant reload time with reload speed buffs/debuffs:"
> "**Weapon Reload Time:** This refers to the base amount of time indicated on the stats of an unmodified weapon."
> Example: "a Braton ... with a rank 5 Fast Hands (+30% Reload Speed) would have a new reload time of: 2.0 ÷ (1 + 0.30) = 1.54s"
> "With -30% reload speed from a rank 9 Tainted Mag: 2.0 ÷ (1 - 0.30) = ~2.85s"
> "Note that reduced reload speed has a more substantial effect than increased reload speed (-0.54s from +30% Reload Speed versus +0.85 from -30% Reload Speed)."

`Source: https://wiki.warframe.com/w/Reload` (section "Calculating Reload Time")

Weapons that reload per shell:

```
Total Reload Time = Reload Start and End Delay / (1 + Reload Speed Bonus)
                  + ( Weapon Reload Time Per Shell / (1 + Reload Speed Bonus) × Magazine Capacity )
```
`Source: https://wiki.warframe.com/w/Reload` (section "Weapons that reload per shell")

Battery (rechargeable) weapons — reload speed bonus affects only the delay, not the rate:

```
Total Reload Time = Recharge Delay / (1 + Reload Speed Bonus) + Magazine Capacity / Recharge Rate
```
> "Reload speed bonuses only affect the **Recharge Delay** while the **Recharge Rate** cannot be changed."
> "Recharge Delay for battery weapons cannot go below 0.5s."

`Source: https://wiki.warframe.com/w/Reload` (section "Rechargeable weapons")

### 6.4 Magazine size

```
Modded Magazine Capacity = Base Magazine Capacity × (1 + Magazine Capacity Bonuses)   # generic Modded Stat rule, §0
```

> "Note that Magazine Capacity bonuses do not affect weapons that pull ammo directly from their reserve pool like Bows and Epitaph."
> "Note that Ammo Maximum bonuses do not increase Magazine Capacity."

`Source: https://wiki.warframe.com/w/Ammo` (section "Magazine Capacity")

**UNSTATED — do not guess:** `https://wiki.warframe.com/w/Ammo` (retrieved 2026-09-29) prints **no magazine-specific formula**. The multiply form above is inferred from the generic `Modded Stat` rule; the Ammo page's only explicit magazine statements are the two exclusion notes quoted here.

The magazine's role in sustained DPS is stated:

```
Number of Shots Per Magazine = Modded Mag Size / Ammo Cost Per Shot
```
> "Not all weapons consume one ammo per shot; this formula is needed to account for Continuous Weapons and certain alt-fires."
> "For Incarnon Form, use Max Incarnon Charge. Ammo Cost is 1 per shot"

`Source: https://wiki.warframe.com/w/Damage/Calculation` (section "Number of Shots Per Magazine")

### 6.5 Attack speed (melee)

```
Modified Animation Length = Base Attack Animation Length / [ Base Weapon Attack Speed × (1 + Attack Speed Bonuses) ]
```

> "An Attack Speed of 1.0 runs its attacks at default speed. An Attack Speed of 1.2 executes 20% faster, while a speed of 0.8 runs 20% slower. Attack Speed is then further increased (or decreased) by Attack Speed mods and ability buffs, giving us the following basic equation:"
> "_Where Base Attack Animation Length is based on the time it takes to complete an attack at Attack Speed of 1.0_"
> "Recall that attack animations vary between weapon types. Despite the Fragor (Hammer) and Karyst (Dagger) both having listed speeds of 0.8, the Karyst's actual speed is faster than the Fragor's due to daggers having a faster attack animation."

`Source: https://wiki.warframe.com/w/Attack_Speed` (section "Mechanics")

Attack speed bonuses are **additive with each other**, including ability buffs:

> "Attack Speed bonus is additive to mods (e.g., Fury)."
> "Attack Speed Mods + Warcry Modifier × (1 + Strength Mods) = 0.3 + 0.5 × (1 + 0.3) = 95%"

`Source: https://wiki.warframe.com/w/Attack_Speed` (Warcry notes quoted on the page)

### 6.6 Which of these are multiplicative rather than additive

```
Time stats (reload time, charge time):   BASE / (1 + Speed Bonuses)     ← division, not × (1 + ...)
Speed stats (fire rate, attack speed):   BASE × (1 + Speed Bonuses)     ← multiply
Crit chance / crit damage / damage:      BASE × (1 + Bonus)             ← multiply
Crit tier multiplier:                    1 + Tier × (Total CDM − 1)     ← linear in tier, not exponential
```

> "Basic formula for calculating modded stats (e.g. critical chance) with the exception of accuracy, reload time, and charge time."
> "Formula for calculating modded reload time and charge time." (the division form)

`Source: https://wiki.warframe.com/w/Damage/Calculation` (section "Modded Stats")

---

## Appendix — URL index (all retrieved 2026-09-29)

| Page | URL | Used for |
| --- | --- | --- |
| Damage 3.0 | https://wiki.warframe.com/w/Damage | elemental types, combination hierarchy, HCET, innate rules, status table |
| Damage/Calculation | https://wiki.warframe.com/w/Damage/Calculation | quantized damage, arsenal total damage, crit tiers formula, DPS, modded stats |
| Damage/Overview Table | https://wiki.warframe.com/w/Damage/Overview_Table | pair -> secondary element listing, per-enemy resistances |
| Critical Hit | https://wiki.warframe.com/w/Critical_Hit | crit chance/damage, tiers, average damage, quantization, headshots |
| Multishot | https://wiki.warframe.com/w/Multishot | projectile count, fractional roll, continuous weapons |
| Status Effect (← Status_Chance) | https://wiki.warframe.com/w/Status_Effect | per-pellet status, >100% status, all status effects, proc weighting |
| Serration | https://wiki.warframe.com/w/Serration | +Damage applied to base damage; elemental uses modified base |
| Calculating Bonuses | https://wiki.warframe.com/w/Calculating_Bonuses | additive vs multiplicative stacking, damage application order, arsenal multishot |
| Fire Rate | https://wiki.warframe.com/w/Fire_Rate | fire rate / charge time formulas, effective fire rate |
| Reload | https://wiki.warframe.com/w/Reload | reload time formulas (normal / per-shell / battery) |
| Ammo (← Magazine) | https://wiki.warframe.com/w/Ammo | magazine capacity notes |
| Attack Speed | https://wiki.warframe.com/w/Attack_Speed | melee attack speed formula |
| Mods | https://wiki.warframe.com/w/Mods | mod slot priority grid for elementals |

### Known gaps (do not invent values)

1. Same-element mod summing has the stated "sum rule" but no worked two-same-element example (§1.5).
2. The wiki itself flags a **conflict** on whether `+Damage` is applied before or after damage quantization; both readings make it a plain final multiplier (§1.6).
3. `Electricity` status stack cap is not printed (§5.2); Slash/Toxin/Heat are "not limited".
4. Puncture status duration differs between the Damage (6s) and Status Effect (10s) pages (§5.2).
5. No fire-rate-specific stacking formula beyond the generic additive rule (§6.1).
6. No magazine-capacity-specific formula on the Ammo page (§6.4).
7. No closed-form formula for extra procs above 100% status (§5.1).

---

## Appendix B — Mod data cache (`WFCD warframe-items` → `data/json/Mods.json`)

Checked directly against the raw file, 2026-09-29 (1,809 entries, 5.76 MB):
`https://raw.githubusercontent.com/WFCD/warframe-items/master/data/json/Mods.json`

**`upgrades` DOES NOT EXIST in this dataset.** `grep -c '"upgrades"'` on the raw file returns **0**; 0 of 1,809 entries carry the key. There is also no `Upgrades.json` in that repo (`404`). So there is no numeric per-rank `upgrade_type` / `operation` / `value` array to parse here — **the engine must parse `levelStats[].stats` text strings.**

Keys an entry actually carries (union, verbatim):

```
uniqueName, name, polarity, rarity, codexSecret, baseDrain, fusionLimit, compatName, type,
levelStats, imageName, category, drops, introduced, releaseDate, tradable, transmutable,
masterable, wikiAvailable, wikiaUrl, wikiaThumbnail, isPrime, isAugment (some)
```

Shape of the per-rank data:

```json
"levelStats": [ { "stats": ["+15% Damage"] }, { "stats": ["+30% Damage"] }, ... ]
```

- `levelStats` has exactly `fusionLimit + 1` entries (rank 0 … max rank). 184 of 1,809 entries have empty/absent `levelStats`.
- Most ranks have 1 stat string; histogram across all entries: `1 stat × 7695`, `2 × 1620`, `3 × 138`, `4 × 13` (dual/triple-stat mods such as Malignant Force `["+60% <DT_POISON_COLOR>Toxin", "+60% Status Chance"]`).
- **Element stat strings are wrapped in markup tags** — e.g. `"+60% <DT_POISON_COLOR>Toxin"`, `"+30% <DT_FIRE_COLOR>Heat"`, `"+30% <DT_ELECTRICITY_COLOR>Electricity"`, `"+60% <DT_FREEZE_COLOR>Cold"`. These must be stripped/normalised before matching, and they are the same `DT_*` type tokens the wiki uses (see §2.6).

Other data gotchas for the engine:

- **`name` is NOT unique.** There are three `"Serration"` entries (uniqueNames `…/Rifle/Beginner/WeaponDamageAmountModBeginner` +40%/rank-3, `…/Rifle/Intermediate/WeaponDamageAmountModIntermediate` +90%/rank-5, `…/Rifle/WeaponDamageAmountMod` +165%/rank-10), three `"Split Chamber"`, three `"Vital Sense"` (incl. a `…/Expert/WeaponCritDamageModExpert` **+220% / rank 10** variant), two `"Continuity"`, etc. **Key on `uniqueName`, never `name`.**
- The values quoted in the original task brief (Serration `baseDrain 2` / `fusionLimit 3`) belong to the **Beginner (Flawed)** entry, not the normal one. Normal Serration is `baseDrain 4`, `fusionLimit 10`, `+165%` — which agrees with the wiki (`https://wiki.warframe.com/w/Serration`, rank 10 = +165%, base capacity cost 4).
- `compatName` values seen: `Rifle`, `WARFRAME`, `AURA`, …; `type` values seen: `Primary Mod`, `Warframe Mod`.
- Aura drain is negative (`Corrosive Projection` `baseDrain -2`, `type: "Warframe Mod"`, `compatName: "AURA"`, `fusionLimit 5`), and its stat text is phrased negatively: `"Enemies lose -3% Armor"` … `"Enemies lose -18% Armor"` — it does **not** look like the `+X% Damage` pattern the elemental/damage parser will expect.

`Source: https://raw.githubusercontent.com/WFCD/warframe-items/master/data/json/Mods.json` (retrieved 2026-09-29)

