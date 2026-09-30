# The target model — sources, rules, and what stays refused

Phase 5 gave the engine a stated enemy and a damage path against it. This document is the
provenance record for every rule that path applies: what was read, where, when, which values
were pinned, and what the model deliberately does not claim. Everything here was re-read on
**2026-09-30** from the current WARFRAME Wiki (revision ids below are the ones the engine's
constants carry). Nothing is carried over from an older wiki state without being checked against
the current one — the three findings in §1 are exactly the places where an older formula was
wrong.

The engine itself is the authority at runtime: every `source=` string in a payload comes from the
constants recorded here, and `design/_planner/phase5_gate.py` fails if a row loses its citation.

## 1. What the current sources changed (the reason this phase looked different)

1. **Damage 3.0 (Update 36, 2024-06-18) replaced the per-health-type damage tables.** Health,
   Armour and Shields are each a single type now; the old `Cloned Flesh` / `Ferrite Armor` /
   `Alloy Armor` matrix is gone. Vulnerabilities and resistances are **faction-scoped**: every
   Grineer is vulnerable to Impact and Corrosive at all times, regardless of armour or shields.
   Source: `wiki.warframe.com/w/Damage` (oldid 2812034); table
   `wiki.warframe.com/w/Damage/Overview_Table` (oldid 2792179).
   **Consequence for the model:** the enemy carries a `faction`, and a `health_type` /
   `armor_type` input would be a fiction — the engine refuses those words (see §5).
2. **Enemy armour mitigation is no longer `armor/(armor+300)` across the board.** Current rule:
   `DR = 0.9 · sqrt(Net Armor / 2700)` for Net Armor ≤ 2700, and `DR = AR/(AR+300)` above it.
   Source: `wiki.warframe.com/w/Armor` (oldid 2814011).
   **Consequence:** the pinned plateaus in §3, and the reason an "average enemy armour" cannot be
   assumed — 300 and 2700 armour are qualitatively different regimes.
3. **Corrosive's current rule is the multiplicative armour reduction** — 26% on the first proc
   (20% + 6% × 1), +6% per further stack, capped at 80% at ten stacks. Source:
   `wiki.warframe.com/w/Damage/Corrosive_Damage` (oldid 2804597). A previously common
   additive/four-stack-capped figure is **not** what the current page says; the engine follows the
   page.

## 2. The damage path, rule by rule

| Rule | Value / formula the engine uses | Source (oldid) | Notes |
|---|---|---|---|
| Faction vulnerability / resistance | `+50%` (Vulnerable) or `−50%` (Resistant) to the listed damage types, applied to shields and health alike | `Damage` (2812034) + `Damage/Overview_Table` (2792179), per-faction pages in `builds/factions.py:FACTION_SOURCE` | Faction-scoped since U36; no per-health-type table |
| Enemy damage reduction | `DR = 0.9·sqrt(AR/2700)` (AR ≤ 2700); `DR = AR/(AR+300)` (AR > 2700) | `Armor` (2814011) | Applies only when the damage lands on health; never to shields or Overguard |
| Per-type minimum | a damage type reduced below 1 by armour is kept at 1 | `Armor` (2814011) | `result.target_damage.min_damage_types` names the types it touched |
| Overguard | neutral to every damage type except a ×1.5 Void vulnerability; not reduced by armour | `Overguard` (2808615) | Stated layer, never inferred |
| Faction damage mods ("Bane of Grineer") | separate multiplier applied to every type after mitigation; covers Grineer/Corpus/Infested, *including* Kuva Grineer, Corpus Amalgam and Infested Deimos, **excluding** Corrupted/Narmer counterparts and Techrot | `Faction_Damage_Bonus` (2804854) | Provenance strings: `Faction_Damage_Bonus` |
| Faction damage mods | *do* apply to Kuva Grineer, Corpus Amalgam, Infested Deimos; *do not* apply to Corrupted or Narmer counterparts, or to Techrot | `Faction_Damage_Bonus` (2804854) | `FACTION_DAMAGE_APPLIES` in `builds/factions.py` |
| Corrosive procs | `armor_after = armor × (1 − (0.20 + 0.06 × stacks))`, 1..10 stacks, 80% cap at ten | `Damage/Corrosive_Damage` (2804597) | The reduction is *stated stack state*, never simulated |
| Viral procs (Phase 4, restated) | `damage_to_health = damage × [2 + 0.25 × (stacks − 1)]`, health and health-under-armour only | `Damage/Viral_Damage` (2805913) | Unchanged by this phase |
| Umbral set (the generalisation proof) | Vitality/Fiber scale their own value ×1.30 with 2 pieces and ×1.80 with 3; Intensify ×1.25 / ×1.75; one piece is a stated no-bonus | `Umbral_Vitality` (2792490), `Umbral_Intensify` (2792489), `Umbral_Fiber` (2792488) | All other sets refuse by name |

Retrieval date for every row above: **2026-09-30**. The faction table's per-page citations are in
`builds/factions.py:FACTION_SOURCE`; the formula citations are the module-level `SOURCE_*`
constants in `builds/enemies.py`, `builds/statuses.py`, `builds/factions.py`, `builds/effects.py`.

## 3. The pinned numbers (what the gate holds the engine to)

| Input | Pinned result |
|---|---|
| Armour 0 | DR 0 |
| Armour 300 | DR 0.3 |
| Armour 675 | DR 0.45 |
| Armour 2700 | DR 0.9 |
| Armour 3000 | DR 0.909090909090909 |
| Armour 900, 4 corrosive procs | net armour 504; DR 0.388844441904472; multiplier 0.611155558095528 |
| Braton Prime + Serration R10 | 92.75 damage per shot; 103.88 crit-expected; 995.5132 burst DPS (Phase 1, unchanged) |

## 4. The enemy model's fields

| Field | Meaning | Required when | Absent → |
|---|---|---|---|
| `target_faction` | the faction whose vulnerability/resistance table applies | always, for any target-aware damage | `unknown`, `target_faction` named |
| `target.protection` | which layer the damage lands on: `health`, `armor`, `shields`, `overguard` | always | `unknown`, `target.protection` named |
| `target.armor` | the target's **current net armour** (before the reductions this engine models) | when the landing is health/armour-health | `unknown`, `target.armor` named |
| `target.corrosive_stacks` | corrosive procs currently on the target, 0..10 | required when the weapon can apply corrosive procs; always consumed when stated | `unknown`; above 10 → `unsupported` |
| `target.viral_stacks` | viral procs currently on the target, 0..10 | Phase 4 rule, unchanged | Phase 4 behaviour |
| `buffs.on_kill` | `{stacks: N}` (instant) or `{stacks: N, uptime: f}` (averaged) for the On-Kill rider | required for an on-kill rider mod to apply | `unknown`, `buffs.on_kill` named |

Pool sizes (`health`, `shields`) are accepted as inputs *only so their refusal can be precise*:
no supported calculation consumes them, and they are reported as `unused` by name.

A field whose value is `null` counts as **not stated** (JSON `null` = absent), consistently for
every field above — a `null` never means zero, and never becomes a default.

## 5. What the model deliberately does not claim

* **No "average enemy".** Every number above is the caller's statement. The engine never picks a
  faction, never picks a landing layer, never assumes an armour value, never assumes stacks or
  uptime, and never infers a target state from anything else in the build.
* **No `health_type` / `armor_type`.** With one health type and one armour class, an input like
  `health_type: "ferrite"` would describe a game state that no longer exists. It is refused.
* **No timeline.** Corrosive stacks, viral stacks and On-Kill stacks are *states*, not events. The
  engine does not model proc rates, kill rates, stack replacement above a mod's own cap, or an
  Emerald Archon Shard raising the corrosive cap — each of those is a named `unsupported`.
* **No pool sizes.** Damage per projectile, per shot and per second are computed; "how many shots
  to kill" is not, because it would require a health pool and a window that the caller has not
  supplied.
* **No other status mechanic, no other set, no Riven/Incarnon/Helminth/Shard interaction.** They
  keep their Phase 4 refusals, by name.
