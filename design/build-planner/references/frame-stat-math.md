# Frame stat math — stacking rules for Warframe attribute & ability stats

**Scope.** The exact multiplication/stacking rules the build-planner engine needs for a Warframe: ability
Strength / Duration / Range / Efficiency, Health / Shield / Armor / Energy, Sprint Speed, and anything else
the wiki gives a closed formula for.

**Retrieved:** 2026-09-29 (AUS Eastern, UTC+10). Every claim below carries the wiki page URL and the exact
revision (`oldid`) that was read, so a later reader can tell whether the wiki has moved under us.

**Method note (reproducibility).** `wiki.warframe.com` serves a Cloudflare interstitial ("Please wait") to
plain `curl`, including to `index.php?action=raw` and `api.php?action=parse` — do **not** trust a 200 with a
42 KB body from that host, it is the challenge page, not wikitext. The quotes below were taken from the
rendered article text returned by the web-extract fetcher, reading the page URLs listed. Where the wiki's
LaTeX stripped to a compressed one-line form (e.g. `Resultant Stat Value=Base Stat Value×(...)`), it is
reproduced verbatim from the fetched text and also restated in readable notation; the readable restatement
is marked as such.

---

## 0. The one rule everything else is a special case of

> **"All sources that add a percent bonus of the same type will *typically* have their bonuses added together.
> This commonly referred to as **additive stacking** (internally represented as `STACKING_MULTIPLY` operation
> type)."**
> — <https://wiki.warframe.com/w/Calculating_Bonuses> (oldid=2789463)

> **"Resultant Stat Value = Base Stat Value × (1 + Additive Stat Bonus 1 + Additive Stat Bonus 2 + ⋯)"**
> — *"Generic formula for additive stacking percent bonuses."*, same page

The same page's overview table puts the ability stats in that bucket explicitly:

> | Operation On Base Stat | Bonus Stacking Behavior | Internal Name (`OperationType`) | Typical Context |
> |---|---|---|---|
> | Multiplication | **Additive Stacking** | `STACKING_MULTIPLY` | "Most common bonus, applies to almost all percentage-based bonuses: **±X% Ability Strength**, **±X% Armor**, **±X% Energy Max**, ±X% Fire Rate, ±X% Health, Etc." |
> — <https://wiki.warframe.com/w/Calculating_Bonuses> (oldid=2789463)

And flat / percentage-*point* bonuses are the other bucket, applied **after** everything else:

> **"Resultant Stat Value = Base Stat Value + (Additive Stat Bonus 1 + Additive Stat Bonus 2 + ⋯)"**
> *"Generic formula for additive stacking flat value and percentage point bonuses."*
> **"Sources that grant flat value or percentage point increases are *typically* applied *after* all other
> bonuses are applied (internally represented as `ADD` operation type)."**
> — <https://wiki.warframe.com/w/Calculating_Bonuses> (oldid=2789463)

Full order of operations, quoted:

> **"Resultant Stat = [Base Stat Value × (1 + Add Bonus 1 + Add Bonus 2) × (1 + Separate Add Bonus 1 +
> Separate Add Bonus 2)] + Flat Bonus 1 + Flat Bonus 2"**
> **"Resultant Stat = [Base Stat Value × ∏(1 + ∑Additive Stacking Bonuses)] + ∑Flat Bonuses"**
> — <https://wiki.warframe.com/w/Calculating_Bonuses> (oldid=2789463)

⚠️ **Two caveats the wiki states and the engine must not flatten:**
1. *"typically"* — the wiki's own word. Multiplicatively-stacking sources exist (Damage Reduction bonuses,
   Affinity bonus are listed in the `MULTIPLY` row of the same table). For the frame stats below, all the
   ordinary mods/arcanes/shards are the additive case.
2. There are named exceptions in the ability-stat space (see §1).
3. The same page notes mod **order does not matter**, except for elemental damage mods:
   *"With the exception of mods that provide elemental damage bonuses, the order in which mods are installed
   **does not matter**; the resultant stats will always be the same regardless of the mod configuration."*

---

## 1. Ability Strength / Duration / Range — and how Efficiency differs

The wiki's ability-stat overview page states only the in-game descriptions; the maths lives in
`Calculating_Bonuses` (§0), in `Maximization`, and per-ability.

Ability Duration
> "Modifies the Duration of Warframe Abilities and the Energy cost of toggled Abilities. Hover over each
> Ability to see how its stats are affected."
> — <https://wiki.warframe.com/w/Abilities> (oldid=2810281, §Ability Duration)

Ability Range
> "Modifies the Range of Warframe Abilities. Hover over each Ability to see how its stats are affected."
> — <https://wiki.warframe.com/w/Abilities> (oldid=2810281, §Ability Range)

Ability Strength
> "Modifies the Strength of Warframe Abilities and the Energy cost of toggled Abilities. Hover over each
> Ability to see how its stats are affected."
> "Ability Strength affects the potency of Warframe Abilities. Most commonly, this refers to damage, but
> Strength affects most values that are not already covered under the other stats, such as healing, Status
> Chance, or the strength of a buff."
> — <https://wiki.warframe.com/w/Abilities> (oldid=2810281, §Ability Strength)

**Formula — ability Strength / Duration / Range are `base × (1 + Σ bonuses)`.** The wiki writes the applied
form per ability. Quoted examples:

> "With Intensify and maximum Scorn at rank 3, Chroma's armor will be at:
> `Base Armor × (1 + Armor Mods + Scorn Modifier × (1 + Strength Mods)) = 370 × (1 + 1 + 3.5 × (1 + 0.3)) =
> 2,423.5`"
> — <https://wiki.warframe.com/w/Armor> (oldid=2814011)

> "With Intensify, a rank-3 Crush will deal:
> `((Base Damage + Extra Damage) ÷ 3 ) × (1 + Strength Mods) × Magnetize bonus damage × (1 + Strength Mods)
> = ((1500 + 1500) ÷ 3) × (1 + 0.30) × 2 × (1 + 0.30) = 3,380 damage for each tick.`"
> — <https://wiki.warframe.com/w/Shield> (oldid=2801800)

**Do Strength mods stack additively with each other?** The wiki does not carry a single sentence reading
"Strength mods stack additively"; what it carries is (a) the generic additive-stacking rule in §0 that names
`±X% Ability Strength` as the canonical `STACKING_MULTIPLY` case, and (b) sources that are explicitly called
out as *additive* ability-strength bonuses, e.g.:

> "Expend 25 Energy to increase the Ability Strength of the next ability cast, granting it a
> **20% / 30% / 40% / 50% additive Ability Strength bonus**."
> — <https://wiki.warframe.com/w/Abilities> (oldid=2810281, Empower)

`Maximization` computes its maxima the additive way — the maximized Strength figure is the plain sum of the
listed "+X% Ability Strength" sources:
> "**720%** Ability Strength … Requires the following mods/gear: … Transient Fortitude [+55% Ability Strength]
> … Blind Rage [+99% Ability Strength] …" with the mods' own penalties listed alongside.
> — <https://wiki.warframe.com/w/Maximization> (oldid=2804310, §Maximized Ability Strength)

**Engine rule:** `Strength/Duration/Range_modded = base × (1 + Σ(percent bonuses of that stat))`, with the
wiki's "typically" caveat and per-ability exceptions. Duration is odd for **channeled** abilities only, where
it divides into the drain (§2).

**Ability Efficiency is the odd one out: the stat is additive, but its *effect on cost* is not a
`base × (1 + Σ)` on the stat.** See §2. Do not model Efficiency as a multiplier on any stat value.

---

## 2. Ability Efficiency — energy cost formula, the 25% floor and the 175% cap

> "**Ability Efficiency** linearly affects the energy cost of Warframe abilities. All Warframes have a base
> Ability Efficiency of **100%**; Ability Efficiency over 100% indicates a reduction of ability cost while
> Ability Efficiency below 100% indicates an increase in ability cost."
> — <https://wiki.warframe.com/w/Ability_Efficiency> (oldid=2807258)

> "Because abilities cannot consume more than **175%** or less than **25%** of their base costs, the Arsenal
> does not display an Ability Efficiency below **25%** or above **175%**, though that does not mean the
> Ability Efficiency stat per se can't go beyond these parameters, only that doing so has no effect on
> non-channeled abilities."
> — <https://wiki.warframe.com/w/Ability_Efficiency> (oldid=2807258)

**Exact cost formula (non-channeled / initial cost), as the wiki states it:**

> "Final Ability Cost = Ability Cost ⋅ max(200% − Ability Efficiency, 25%)"
> — <https://wiki.warframe.com/w/Ability_Efficiency> (oldid=2807258, §Mechanics)

Restated (readable form, not a quote): `final_cost = base_cost × max(2.0 − efficiency, 0.25)`, where
`efficiency` is a decimal (1.00 = 100%). Equivalent wiki phrasing, from the Maximization page:

> "Initial/Per Target ability cost can be calculated as **[Cost = BaseCost x (2 - (1 + AbilityEfficiencyMods))]**."
> "The cost of an ability will always be between **25%-175%** of the base cost."
> — <https://wiki.warframe.com/w/Maximization> (oldid=2804310, §Maximized Ability Efficiency)

**So, explicitly for the engine:**
- **Cap:** efficiency's effect is capped at **175%** effective — i.e. cost cannot drop below **25%** of base
  (`max(..., 25%)`). The *stat* may exceed 175% (up to ~200%) but does nothing for non-channeled abilities.
  `Maximization` labels 175% a "**soft cap**".
- **Negative efficiency raises cost**, by exactly the same term: `2.0 − efficiency` grows past 1.0.
  Efficiency 45% (−55% from Blind Rage) ⇒ `2 − 0.45 = 1.55` ⇒ **155% of base cost**. The wiki's own worked
  examples of the same formula, on the earlier "using X, the cost is Y% of base" list:
  > "Using Streamline, the channeling costs 100% * 125% / 100% = 125% of the base cost."
  > "Using Fleeting Expertise, the channeling costs 100% * 95% / 40% = 237.5% of the base cost, hitting the
  > ceiling of 175% of the base cost instead."
  > — <https://wiki.warframe.com/w/Ability_Efficiency> (oldid=2807258)
  (Those percentages are the *channeled* form with `1/Duration` folded in — see next.)
- **Efficiency sources stack additively with each other:**
  > "Streamline, Fleeting Expertise, Blind Rage, the Arcane Enhancements Pax Bolt and Arcane Impetus, and the
  > positive Ability Efficiency Arcane Helmets stack additively. Stacking with Trinity Meridian Helmet or Ash
  > Scorpion Helmet does not appear to follow this formula; this suggests stacking is different when you have
  > a helmet that reduces Ability Efficiency."
  > — <https://wiki.warframe.com/w/Ability_Efficiency> (oldid=2807258, §Modifiers)

**Channeled / toggled abilities** (the engine will need this for any channeled ability; it is *not* the same
formula):

> "Final Energy Drain = Energy Drain ⋅ max((200% − Ability Efficiency) / Ability Duration, 25%)"
> — <https://wiki.warframe.com/w/Ability_Efficiency> (oldid=2807258, §Mechanics)

> "The energy drain per second for channeled abilities scales with both Ability Duration and Ability
> Efficiency, and follows the formula: **M = B \* (2 - E) \* (1 / D)**
> - **M** is the **modded** energy drain per second.
> - **B** is the **base** energy drain per second.
> - **E** is ability **efficiency** (in decimal form; uses the *true value* before the 175% cap is applied).
> - **D** is ability **duration** (in decimal form)."
> "**An important note is that modded channeling cost has a floor of -75% and a ceiling of +75%**. In other
> words, a 10 energy/s channeled ability cannot be modded to drain less than 2.5 energy per second, or more
> than 17.5 energy per second."
> — <https://wiki.warframe.com/w/Ability_Efficiency> (oldid=2807258, §Energy Drain for Channeled Abilities)

Note the trap the wiki calls out: for channeled abilities the **uncapped** efficiency value is used, so
efficiency above 175% *does* matter there (it offsets negative duration).

Also relevant: a flat "-X% energy cost" style effect (e.g. an ability with no energy cost) is an `ADD`-bucket
effect, not this formula — *"Some Warframe abilities do not cost energy to cast, thus ability efficiency has a
unique effect on these abilities"* (same page, §Other Behavior).

---

## 3. Health / Shield / Armor / Energy — the wiki's own equations

### 3.1 Health
> "Like most attribute values, Health is increased by single multiplier formed from effects that additively
> stack with each other. The health gained from leveling is an exception, stacking additively with base
> health before multipliers
> **Total Health = (Base Health + Warframe Rank Bonuses) × (1 + Modifier from Mods) + Other Bonuses**
> - **Base Health** refers to the Warframe's health at Rank 0.
> - **Warframe Rank Bonuses** are increases to a Warframe's health that apply as the Warframe goes from rank
>   0 to 30. These are normally **+100** at rank 30, though there are exceptions."
> — <https://wiki.warframe.com/w/Health> (oldid=2750469)

Corroborating statement on the mod side:
> "For mods increasing shield, health, or energy, bonuses are calculated from a warframe's base value and
> **stack additively with the Rank Bonuses**. This prevents exponential increases with the passive leveling
> bonuses…"
> — <https://wiki.warframe.com/w/Mod> (oldid=2804308)

Effective health / EHP:
> "Effective Health = Nominal Health ⋅ (Net Armor + 300)/300"
> "Effective Shield = Nominal Shield ⋅ 2"
> "EHP = (Effective Health + Effective Shield) ⋅ 1/(1 − Net Damage Reduction) ⋅ 1/(1 + Damage Type Modifier)"
> "_Nominal health refers to listed health points as displayed in-game; in other words, it is the total health
> after mods and buffs are applied.__Shield has a general 50% damage reduction.__Net damage reduction refers
> to total damage reduction outside of armor, e.g. Blessing or Adaptation._"
> — <https://wiki.warframe.com/w/Health> (oldid=2750469, §Effective Health §Calculation)

### 3.2 Shield
> "…simply add their %-value to the combined multiplier bonus that already exists:
> **Total Shields = Base Shields \* (1 + Relative Mod Bonus + Relative Ability Bonus)**
> Where the **Relative Mod Bonus** and **Relative Ability Bonus** is the sum of all the applicable bonuses
> from mods and Warframe abilities respectively.
> **Relative Mod Bonus or Relative Ability Bonus = Bonus1 + Bonus2 + Bonus3 + ⋯**"
> Worked example, Hildryn: "`Total Shields = Base Shields*(1+Redirection Bonus+Primed Vigor Bonus+Relative
> Ability Bonus) = 1780*(1+1+0.75+0.3) = 5429`"
> — <https://wiki.warframe.com/w/Shield> (oldid=2801800, §Increasing Maximum Shields)

Shield regeneration (a clean formula the wiki gives):
> "Shields recharge at **15** units per second, plus **5%** of the Warframe's maximum shields:
> **Shield Recharge Rate = (15 + 0.05(Maximum Shields)) \* (1 + Shield Recharge Bonus)**
> To calculate the time needed for depleted shields to regenerate to max shields:
> **Shield Recharge Time (s) = Maximum Shields / Shield Recharge Rate**"
> — <https://wiki.warframe.com/w/Shield> (oldid=2801800)

### 3.3 Armor
> "Like with most other stats, armor gains from mods stack additively together before being multiplied with
> the Warframe's base armor:
> **Total Armor = Base Armor(1 + Mod Multiplier)**
> - **Mod Multiplier** refers to the value on the mods equipped. It is 1.0 at max rank Steel Fiber, 0.40 at
>   max rank Armored Agility, and 1.40 with both equipped."
> — <https://wiki.warframe.com/w/Armor> (oldid=2814011, §Increasing Armor)

Damage reduction from armor (Tenno):
> "**Tenno Damage Reduction = Net Armor / (Net Armor + 300)**
> A net armor value of 300 will reduce incoming damage by 300 ÷ 600 = 50%, so only half of the weapon's
> damage is inflicted in total. At **600**, you receive only **33%** (reduction is 600 ÷ 900 = 66.6667%) of a
> weapon's outgoing damage. At **900** armor, inflicted damage is only **25%** (reduction 900 ÷ 1200 = 75%)…"
> — <https://wiki.warframe.com/w/Armor> (oldid=2814011, §Tenno Damage Reduction Formula)

Enemy armor (for completeness; not needed for a build calculator):
> "**Enemy Damage Reduction = 90% ⋅ Net Armor / 2700**" for Net Armor ≤ 2,700, else
> "**Enemy Damage Reduction = Net Armor / (Net Armor + 300)**"
> — <https://wiki.warframe.com/w/Armor> (oldid=2814011, §Enemy Damage Reduction Formula)

Armor and rank:
> "Unlike health and shield, a Warframe's base armor doesn't change as it advances from Rank 0 to Rank 30,
> with the exceptions of Nidus, Lavos, and Kullervo."
> — <https://wiki.warframe.com/w/Armor> (oldid=2814011)

### 3.4 Energy
> "These mods increase the energy capacity of a Warframe with the following the formula:
> **Energy_total = Energy_max × (1 + Mod Multiplier) + Flat Bonuses**
> So taking Volt Prime as an example, with 200 base energy and 300 max energy he will have:
> - With Flow: `300×(1+1.0)=600` max energy.
> - With Primed Flow: `300×(1+1.85)=855` max energy.
> - With Primed Flow with an Entropy effect active, and a Tauforged Azure Archon Shard:
>   `300×(1+1.85+0.25)+75=1005` max energy."
> — <https://wiki.warframe.com/w/Energy_Capacity> (oldid=2807999, §Formula For Modded Energy Capacity)

Starting energy:
> "Starting Energy can be increased with unspent mod capacity. The formula followed is:
> **Final Starting Energy = Starting Energy + (5 × Free Mod Capacity)**
> Preparation or an Amber Archon Shard can increase starting energy based on a percentage of maximum energy,
> stacking additively with each other. Including their effect, the formula becomes:
> **Final Starting Energy = Starting Energy + (5 × Free Mod Capacity) + (Energy Total × Mod Multiplier)**"
> — <https://wiki.warframe.com/w/Energy_Capacity> (oldid=2807999, §Starting Energy §Formula)

### 3.5 Rank-up bonuses (needed because WFCD stores rank-0 values — see `wfcd-data-shapes.md`)
> "Stat boosts received from ranking up are calculated from the base value of the Warframe for each stat,
> preventing mods from affecting the bonus.
> During level up, all Warframe stats gain:
> - +10 Health capacity every 3 ranks starting at Rank 1
> - +10 Shield capacity every 3 ranks starting at Rank 2
> - +5 Energy capacity every 3 ranks starting at Rank 3
> For a total of **+100 Health, +100 Shields and +50 Energy capacity at Rank 30**."
> — <https://wiki.warframe.com/w/Warframes> (oldid=2814300, §Leveling Up)

Per-frame exceptions to those defaults, quoted from the same page's "Rank-Up Exceptions" table
(Health / Shield / Armor / Energy at Rank 30):

| Warframe | Health | Shield | Armor | Energy |
|---|---|---|---|---|
| Baruuk / Baruuk Prime / Chroma Prime / Garuda / Garuda Prime / Koumei / Saryn Prime / Volt Prime / Wisp / Wisp Prime / Yareli / Yareli Prime | +100 | +100 | 0 | +100 |
| Dante / Xaku / Xaku Prime | +90 | +90 | 0 | +70 |
| Grendel / Grendel Prime / Inaros / Inaros Prime | +200 | 0 | 0 | +50 |
| Hildryn / Hildryn Prime | +100 | +500 | 0 | 0 |
| Kullervo | +200 | 0 | +100 | +50 |
| Lavos / Lavos Prime | +200 | +100 | +100 | 0 |
| Narin | +100 | +100 | 0 | +90 |
| Nezha / Nezha Prime / Valkyr / Valkyr Prime | +100 | +50 | 0 | +50 |
| Nidus / Nidus Prime | +100 | 0 | +100 | +50 |

Plus the Nidus/Nidus Prime special block on the same page: "+5 Health/s Regeneration at Unranked, +10 Health
capacity every 3 ranks starting at Rank 1, +20 Armor every 6 ranks starting at Rank 2, +3% Ability Strength
every 6 ranks starting at Rank 3, +10 Energy capacity every 6 ranks starting at Rank 5, +2 Health/s
Regeneration every 6 ranks starting at Rank 6 … For a total of +100 Health, +100 Armor, +15% Ability
Strength, +50 Energy capacity, and +15 Health/s Regeneration at Rank 30."
Frames **not** in that table use the default +100/+100/0/+50.

---

## 4. Which stats are `base × (1 + Σ)` and which are "flat after" — do not blend

| Stat | Shape | Where the shape comes from |
|---|---|---|
| **Ability Strength** | **`base × (1 + Σ%)`** | `Calculating_Bonuses` names `±X% Ability Strength` as the `STACKING_MULTIPLY` case; applied per ability as `(1 + Strength Mods)` |
| **Ability Duration** | **`base × (1 + Σ%)`** (+ channeled-drain exception) | same; channeled drain uses `M = B × (2 − E) × (1/D)` |
| **Ability Range** | **`base × (1 + Σ%)`** | same |
| **Ability Efficiency** | **NOT a `× (1 + Σ)` stat value.** The *stat* is additive (`streamline +30%, fleeting +60%` ⇒ 190%), but its effect is **`cost = base_cost × max(2.0 − efficiency, 0.25)`** | `Ability_Efficiency` §Mechanics; `Maximization` §Maximized Ability Efficiency |
| **Health** | **hybrid: `(base + rank bonus) × (1 + Σ%) + flat`** | Health page: "Total Health = (Base Health + Warframe Rank Bonuses) × (1 + Modifier from Mods) + Other Bonuses" |
| **Shield** | **`base × (1 + Σ% mods + Σ% abilities)`**, flat additions come after | Shield page formula |
| **Armor** | **`base × (1 + Σ% mods)`** + flat armor bonuses applied **after** mods | Armor page formula; Grendel note below |
| **Energy pool** | **`base × (1 + Σ%) + flat`** | Energy page formula (`+ Flat Bonuses` is explicit) |
| **Sprint Speed** | not a frame stat formula — **`base_sprint_stat × 6 × 1.25 × (1 + Σ sprint bonuses)`** in m/s (see §5) | Sprint Speed page |
| **Casting Speed** | **`(Base Animation Time) ÷ (1 + Σ speed bonus)`** — note it **divides** | `Abilities` §Casting Speed |

Flat-after examples the wiki gives explicitly (evidence that the flat bucket is real and separate):
- Energy: "`… +75`" Tauforged Azure Archon Shard in the Volt Prime example (`Energy_Capacity`).
- Armor: "**Armor bonus is added after armor mods** such as Steel Fiber. For example, Grendel…" and
  "The gained Armor is not increased by mods such as Steel Fiber… and acts as a flat increase to your total
  Armor." (`Armor` page, Grendel §Passive / Chroma notes).
- Health: the `+ Other Bonuses` term in the Health formula.
- Ability Strength: *additive percentage* bonuses (Empower, Energy Conversion) are still inside the
  `(1 + Σ)` bracket, not flat-after — they are percentage **bonuses**, not percentage *points*.

⚠️ **Rank bonus is added to base *before* the mod multiplier** — `(base + 100) × (1 + Σ)`, not
`base × (1 + Σ) + 100`. Verified against the wiki's own arithmetic: Excalibur, Rank 30 health 370, with
max Vitality +100% ⇒ **740** = 370 × 2. (The same page also notes the historical pre-27.2 behaviour where
mods multiplied only the rank-0 base, which is *not* the current rule.)
— <https://wiki.warframe.com/w/Warframes> (oldid=2814300) and <https://wiki.warframe.com/w/Health> (oldid=2750469)

---

## 5. Sprint speed and the other stats with a clean formula

### 5.1 Sprint Speed
> "Sprint Speed is a multiplier to the Warframe's run animation speed. Note that a Warframe's base Sprint
> Speed stat is **not** a direct modifier to its sprint speed, but is actually a Movement Speed modifier.
> Sprinting increases the speed of a Warframe by **25%**.
> - A Warframe with a base Sprint Speed stat of **1.0** will walk at **6 m/s** and sprint at **7.5 m/s**.
> - A Warframe with a base Sprint Speed stat of **1.4** will walk at **8.4 m/s** and sprint at **10.5 m/s**.
> - A Warframe with a base Sprint Speed stat of **1.4** using Rush will walk at **8.4 m/s** and sprint at
>   **13.65 m/s**."
> — <https://wiki.warframe.com/w/Sprint_Speed> (oldid=2805840, §Mechanics)

> "The sprint speed buff stacks additively with other sprint speed modifiers. For example, Rush combined with
> Infested Mobility at max rank and 130% Ability Strength will increase the frame's sprint speed by
> `1 + 30% + (60% × 130%) = 2.08x`"
> — <https://wiki.warframe.com/w/Sprint_Speed> (oldid=2805840) — also verbatim on
> <https://wiki.warframe.com/w/Abilities> (oldid=2810281)

**Formula for the engine (DERIVED from those examples — the wiki states the examples and the "+25% while
sprinting" / "+Σ while sprinting" facts, but does not print the closed equation):**
- `walk_mps = base_sprint_stat × 6`
- `sprint_mps = base_sprint_stat × 6 × 1.25 × (1 + Σ sprint-speed bonuses)`
  Check: 1.4, Rush (+30%) ⇒ `1.4 × 6 × 1.25 × 1.3 = 13.65` ✅ matches the wiki's 13.65 m/s.
- Sprint **mods/buffs do not change walk speed** in the wiki's own example (1.4 + Rush ⇒ walk still 8.4).
  Marked **DERIVED / not stated as a formula**.
- Ability-sourced sprint buffs are themselves scaled by Strength (`60% × 130%`), and stack additively with
  sprint mods — that part **is** stated.

### 5.2 Other clean formulas found
| Stat | Formula | Source |
|---|---|---|
| Damage reduction from armor | `DR = Net Armor / (Net Armor + 300)` | `Armor` §Tenno Damage Reduction Formula |
| Effective Health | `EHP_nominal = Nominal Health × (Net Armor + 300)/300` | `Armor` §Effective Health, `Health` §Effective Health |
| Effective Shield | `Nominal Shield × 2` (shields have a general 50% DR) | `Health` §Effective Health §Calculation |
| Shield recharge rate | `(15 + 0.05 × Maximum Shields) × (1 + Shield Recharge Bonus)` | `Shield` |
| Shield recharge time | `Maximum Shields / Shield Recharge Rate` | `Shield` |
| Starting energy | `Starting Energy + (5 × Free Mod Capacity) [+ Energy Total × Mod Multiplier]` | `Energy_Capacity` |
| Casting time | `(Base Animation Time) ÷ (1 + Speed Bonus)` | `Abilities` §Casting Speed |
| Channeled energy drain | `M = B × (2 − E) × (1/D)` | `Ability_Efficiency` |
| Ability energy cost | `Cost = BaseCost × max(2 − Efficiency, 0.25)`; channeled:
`BaseCostOverTime × (2 − Efficiency) × (1 + Duration Mods)` | `Ability_Efficiency`, `Maximization` |

### 5.3 UNSTATED — do not guess
- **The closed-form sprint-speed equation with the 6 m/s and 1.25 constants** — the wiki gives the three
  worked examples above and the additive-bonus rule, not the equation. The `× 6` / `× 1.25` form in §5.1 is
  derived from the examples and is labelled as such; treat it as derived, and re-derive if the examples move.
- **Whether the "+25% while sprinting" is itself inside or outside the sprint-bonus bracket** — the wiki
  never states it; the examples are consistent with `base × 6 × 1.25 × (1 + Σ)` but do not prove it for a
  case where Σ is negative (e.g. a hypothetical sprint penalty). **UNSTATED — do not guess.**
- **Per-frame armour rank bonuses for Nidus / Nidus Prime / Lavos / Lavos Prime / Kullervo** — the Warframes
  page table gives `Armor +100` for those rows, but the Armor page also says base armor is rank-invariant
  "with the exceptions of Nidus, Lavos, and Kullervo", i.e. the "+100 Armor at Rank 30" is a rank-up bonus,
  not a change to the rank-0 base. The two statements are consistent but the wiki does not spell out how a
  rank-30 Nidus armour value should be multiplied by Steel Fiber. **UNSTATED — do not guess; test in game.**
- **Whether the "Other Bonuses" / "Flat Bonuses" terms are capped or ordered** relative to each other —
  the wiki only says flat/percentage-point bonuses are applied after the multiplicative ones.
- **The exact cap arithmetic for efficiency above 175% on channeled abilities with ≥100% duration** — the
  page says the cap "has no effect on non-channeled abilities" and that for channeled abilities over 175%
  matters only when Duration < 100%. Its treatment of exactly-100% duration is not stated.
  **UNSTATED — do not guess.**
- Nothing else in §1–§5 is inferred; every other figure above is a quote from the cited revision.

---

## Appendix — sources, revisions, retrieval

All retrieved 2026-09-29 (AUS Eastern, UTC+10) by the web-extract fetcher; `oldid` is the revision the page
text carried at read time.

| Page | URL | Revision read |
|---|---|---|
| Calculating Bonuses | <https://wiki.warframe.com/w/Calculating_Bonuses> | oldid=2789463 |
| Abilities (= Ability Strength redirect) | <https://wiki.warframe.com/w/Abilities> | oldid=2810281 |
| Ability Efficiency | <https://wiki.warframe.com/w/Ability_Efficiency> | oldid=2807258 |
| Ability Duration | <https://wiki.warframe.com/w/Ability_Duration> | oldid=2794886 |
| Ability Range | <https://wiki.warframe.com/w/Ability_Range> | oldid=2701370 |
| Health | <https://wiki.warframe.com/w/Health> | oldid=2750469 |
| Shield | <https://wiki.warframe.com/w/Shield> | oldid=2801800 |
| Armor | <https://wiki.warframe.com/w/Armor> | oldid=2814011 |
| Energy Capacity | <https://wiki.warframe.com/w/Energy_Capacity> | oldid=2807999 |
| Sprint Speed | <https://wiki.warframe.com/w/Sprint_Speed> | oldid=2805840 |
| Warframes (leveling/rank bonuses) | <https://wiki.warframe.com/w/Warframes> | oldid=2814300 |
| Maximization | <https://wiki.warframe.com/w/Maximization> | oldid=2804310 |
| Mod | <https://wiki.warframe.com/w/Mod> | oldid=2804308 |
| Damage/Calculation (Modded Stat) | <https://wiki.warframe.com/w/Damage/Calculation> | oldid=2804415 |

**Quoting convention used in this file:** text in block quotes is verbatim from the fetched page at the
cited revision (LaTeX was stripped by the extractor, leaving e.g. `Total Armor=Base Armor(1+Mod Multiplier)`;
those are left as fetched and restated in readable form in the surrounding prose). Anything derived rather
than quoted is labelled **DERIVED**; anything the wiki does not state is labelled **UNSTATED — do not guess**.
