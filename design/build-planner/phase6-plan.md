# Phase 6 plan — the mechanic registry, and the mechanics that prove it

Status: **in progress**, written 2026-09-30. Phase 5 is closed and verified
(`design/build-planner/phase5-report.md`); the Phase 1–5 contracts are non-negotiable.

The goal, in the brief's words: *make adding a combat mechanic structurally safe*. Phase 5's fourth
adversarial review found that a mechanic's requirements live in four unrelated places (trigger,
consumed fields, trace hook, target/mitigation integration) and that forgetting one fails
silently. Phase 6 builds one declarative registry, migrates the existing mechanics onto it with
**identical answers**, then proves it by adding mechanics through it — including one that needs a
stage the engine did not have before (Heat's armour transform).

## 1. Sources to pin this phase (retrieved 2026-09-30)

| Rule | Source (oldid) |
|---|---|
| Heat status: Ignite reduces armour by up to 50%; ramp 15/30/40/50% every 0.5s, full strip 2s after the proc; ramp-down 50/40/30/15/0 over 6s; strip is **multiplicative** with corrosive (and with Corrosive Projection, which stays refused); a tick every 1s for 6s (DoT — refused: timeline) | `Damage/Heat_Damage` (oldid 2807948) |
| Armour / damage reduction, and the ordering of armour transforms ("net armour") | `Armor` (oldid 2814011) |
| Corrosive stacks | `Damage/Corrosive_Damage` (oldid 2804597) |
| Status effect semantics (stacking, caps) | `Status Effect` (oldid 2813980) |
| On-kill rider mechanism per mod: the card's own value, cap and duration, as the corpus exports them | per-mod wiki pages (pinned per rider when 6.3 lands) + `data/build_data.json` (`conditional_table`) |
| Target presets (6.5) | **none found** — see §5 |

## 2. Existing decisions this phase must not disturb

* Four-state vocabulary (`satisfied`/`not_satisfied`/`unknown`/`unsupported`), one condition row per
  mechanic, every row carrying `reason_code` + `missing`/`inputs` + a source string.
* Strict mode withholds only what depends on the unresolved row (Phase 5's blast-radius fix); the
  target block is withheld as a block, never the Phase 1 numbers.
* Stated-only combat state: no guessed stacks, uptime, armour, pool, or preset.
* The page states inputs and prints engine answers; no Warframe maths in `static/`.
* Refusal codes exist in `builds/unsupported.REGISTRY`; a code without a row is a gate failure.

## 3. The registry (6.1) — shape and the plumbing it derives

`builds/mechanics.py` holds one machine-readable table (`mechanics.REGISTRY`) of `Mechanic`
declarations. Each declares: id, name, family (`target_state`, `target_damage`, `build_state`,
`set`, `pool`), trigger (a small machine-readable `Rule` over stated context fields), consumed
fields, required/optional inputs, affected stats, pipeline stage, trace destination, refusal codes,
provenance, state support (instant/averaged, strict/hypothetical), and dependencies.

Derived (not hand-maintained) from it:

1. **consumed-context accounting** — `evaluation.unused`, the `context_unused` markers and the
   canonical target/attack field lists come from the union of `consumes`;
2. **condition/evaluation dispatch** — the target path's trigger rule, the target-state loop
   (armour transforms in registry order), the build-state rider loop and the stage order;
3. **trace destination** — every applied value names its trace key (`multishot`,
   `critical_chance`, `target_damage.<type>`, `damage_to_health`), so no mechanic can be attached to
   a trace by hand;
4. **unsupported/refusal registration** — a mechanic's declared codes are checked against
   `unsupported.REGISTRY` at import and in the gate;
5. **mechanic discovery/introspection** — `python builds/debug.py mechanics`, plus the registry
   table rendered in the docs and in the Phase 6 gate's report.

`register()` validates a declaration on the spot and raises `MechanicDeclarationError` when a
required property is missing or points at an unknown family/stage/trace/refusal code — the
architecture invariant test asserts exactly that (a half-declared mechanic fails loudly instead of
being silently ignored).

## 4. Migration (6.2) — a regression migration, not a rewrite

Moved onto the registry: target faction, first shot, viral, corrosive, the On-Kill multishot rider,
the Umbral set (its roster contract declared as the set family's rule so future sets reuse it).
Implementations stay where they are; the *declarations* move, and the engine reads them.

Proof: `design/_planner/phase6_migration.py` computes a corpus of builds × contexts against both
the pre-migration engine (extracted with `git archive` from the Phase 5 commit) and the working
tree, and diffs `conditions`, `refusals`, `traces`, `stats`, `riders`, `evaluation` and
`target_damage` case by case. Any diff fails the script; a diff is investigated, never re-pinned.

## 5. 6.5 target presets — the honest answer, decided up front

This database carries `equipment` (warframes/weapons/sentinels) and `mods`, and no enemy rows at
all (verified: no `enemies` key, no per-unit level/armour profiles; `heavy_gunner` appears nowhere).
There is therefore **no authoritative source in this project to join a preset to**. Per the brief,
the milestone is a documented gap: the engine exposes `target_preset` as a **named refusal**
("no authoritative exported target-profile source is available to this build") and Phase 7 may
revisit it if a sourced export is added. No preset is fabricated, and no preset is ever inferred
from build context.

## 6. Milestones (in order)

1. `phase6-plan.md` (this file) · 2. registry + derived plumbing · 3. migration + migration gate ·
4. 6.3 rider family through the shared path · 5. 6.4 Heat through the registry · 6. 6.6 pool /
shots-to-kill · 7. 6.5 refusal + documented gap · 8. trace composition + blast-radius +
architecture-invariant tests · 9. Phase 6 falsification gate (16 named breaks, inert breakers do
not count) · 10. page inputs + browser gate checks · 11. docs, report, independent review
dispositions · 12. frozen-tree sequential verification.
