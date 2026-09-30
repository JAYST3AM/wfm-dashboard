# Phase 5 plan — the target model, applied conditions, and stated buff state

Status: **delivered** (2026-09-30; implementation, tests, gate, docs and report complete). Phase 4
is complete and verified (`design/build-planner/phase4-report.md`); the Phase 1–4 contracts were
treated as non-negotiable. What the delivered code does differently from this plan is recorded in
"Deviations from this plan" at the end — the plan itself is left as written, because it is the
document the implementation was measured against.

The one-line version: the engine learns what it is shooting at (a stated enemy), applies **one
real conditional rider** end to end, can express a buff's stack/uptime state without simulating
anything, proves the target model with a second status mechanic, and proves the abstraction with a
set bonus — or it refuses, precisely, in the same four-state vocabulary Phase 4 built.

## 0. What the research changed (read this first)

The first job was to find **current** authoritative rules, not to preserve old ones. Three findings
from the current wiki (retrieved 2026-09-30; oldids in `docs/build-planner-target-model.md`) shaped
the whole phase:

1. **Damage 3.0 (Update 36, 2024-06-18) replaced per-health-type damage tables.** Health, Armor and
   Shield are one type each now; vulnerabilities and resistances are **faction-scoped** (all Grineer
   are vulnerable to Impact and Corrosive at all times, regardless of armour or shields). The enemy
   model therefore carries a **faction**, not a "Cloned Flesh / Ferrite Armor" vocabulary. A
   `health_type` input would be a fiction and is refused by name.
2. **Enemy armour mitigation is no longer `armor/(armor+300)`.** Current rule
   (`wiki.warframe.com/w/Armor`): `DR = 90% · sqrt(Net Armor / 2700)` for Net Armor ≤ 2700, and
   `DR = AR/(AR+300)` above it. Damage types have **no armour-class modifier any more** — armour DR
   is uniform per damage type, and each damage type keeps a minimum of 1 damage when armour
   reduces it.
3. **Corrosive's current rule is the multiplicative one**: 26% on the first proc (20% + 6% × 1),
   +6% per further stack, capped at 80% at 10 stacks — expressed in the engine as
   `armour × (1 - (0.20 + 0.06 × stacks))`. This is what makes 5.5 (a second, target-state-dependent
   mechanic) land on the *mitigation* path instead of duplicating Phase 4's viral multiplier.

Everything else the phase needed was verified the same way and is recorded with its source in
`docs/build-planner-target-model.md`.

## 1. The milestones, as implemented

### 5.1 — Enemy/target model foundation → `builds/enemies.py` (new)

* The model is **stated context, never derived**: `context.target_faction` (Phase 4 spelling,
  extended to the current 15-faction vocabulary) plus `context.target`
  (`protection`, `armor`, `corrosive_stacks`, `viral_stacks`, `immune_to`).
* Field meanings, all source-pinned: `faction` drives damage-type modifiers; `armor` is the
  target's current net armour (the caller's number; the engine applies the corrosive reduction and
  the DR formula); `protection` is which layer the damage lands on; pool sizes (`health`, `shields`)
  are **not** fields — no supported calculation consumes them, and an input nothing consumes is
  refused by name (`context_unused`), not quietly kept.
* A stated-but-unknown field (`target.armor: "300"`, a faction outside the vocabulary) is named in
  `context_ignored`; the condition that needed it answers `unknown` with the missing input named.
  Nothing is coerced, nothing is defaulted, nothing is assumed.
* Provenance for the target data lives in the engine: the faction table and both formulas carry
  `source` + `retrieved` strings, and the registry row `target_model` names what the model covers.

### 5.2 — Damage against a stated target → the same module, wired into `builds/weapons.py`

Per damage type, per projectile, exactly as the wiki's `Damage/Calculation` describes:

```
inflicted(t) = clamp_min1( SD(t) × (1 + HM(faction, t)) × armour_damage_multiplier(AR_eff) )
```

* `HM` = the faction's vulnerability (+0.5) or resistance (−0.5), else 0; applied to shields and
  health alike. `AR_eff` = stated armour after the modelled corrosive reduction; `armour` factor
  applies only when the damage lands on health (never shields), never to Overguard.
* Overguard: neutral to every damage type except a ×1.5 Void vulnerability, no armour DR
  (`wiki.warframe.com/w/Overguard`).
* The full chain is traced per type and in total: base (Phase 1 trace) → build modifiers (Phase 1)
  → conditional modifiers (faction bonus, viral, applied riders) → target modifiers (HM) →
  mitigation (armour DR with the corrosive row) → **final supported damage result**
  (`result.target_damage`, plus `target_damage.<type>` traces).
* The path runs **only when the caller described a combat target** (`protection` or `armor` or
  `corrosive_stacks` stated). No target context → no block, and every Phase 1 number is
  byte-identical (pinned by the gate).
* Missing inputs refuse: no `protection` → unknown; no `armor` when the damage lands on health →
  unknown (`target.armor` named); an unusable armour value → unsupported. The engine never assumes
  an armour value and never picks a landing for the caller.

### 5.3 — First actually-applied conditional mod effect (the `condition_effect_unimplemented` path, now real)

* Chosen rider: the **On Kill stack rider on multishot** — Galvanized Chamber / Galvanized
  Diffusion / Galvanized Hell, whose own card text (DE export, via our ingest) is
  `On Kill: +30% Multishot for 20s. Stacks up to Nx.` It is not the easiest case: its value flows
  into per-shot damage and both DPS figures, so an applied rider that was wrong anywhere would move
  headline numbers.
* Pipeline: `context.buffs.on_kill` → condition state → rider value × effective stacks → merged
  into the stat's collected total with a provenance row → trace → the calculated result. All four
  Phase 4 states are reachable and pinned.
* Deliberately **not** enabled: every other conditional line in the corpus (the on-kill family's
  non-multishot riders, weak-point/aiming riders, per-status-type riders, set/Riven/Incarnon
  mechanics) — they keep refusing. A rider whose condition the caller **does** satisfy now refuses
  with `condition_effect_unimplemented` instead of the blanket `mechanic_unsupported`, because that
  is what is actually true of it.

### 5.4 — Simulator-free stack/uptime model → `builds/buffs.py` (new)

* **Instant / stated state**: `{"on_kill": {"stacks": 3}}` — three stacks right now.
* **Averaged / uptime state**: `{"on_kill": {"uptime": 0.65, "stacks": 5}}` — the caller explicitly
  assumes five stacks at 65% uptime. The engine never derives uptime, never derives stacks, and an
  averaged answer says so: condition row (`mode: averaged`, `assumption`), rider row, trace note,
  and `result.assumptions`.
* The two concepts never mix: `uptime` without `stacks` is `unknown` (the stack count cannot be
  invented); `uptime` outside 0..1 is `unknown`; `active: false` with stacks > 0 is `unknown`
  (contradiction); stacks above the mod's own cap are `unsupported` (stack replacement is a
  timeline). `{"active": true}` alone on a stacking buff is `unknown` with the stack count named as
  missing — never read as one stack.
* **Only riders the engine actually applies can be averaged.** A non-enabled rider refuses the same
  way in both modes.

### 5.5 — Second target/status interaction → corrosive armour reduction (`builds/statuses.py`)

* Different architecture from viral on purpose: corrosive does not multiply damage, it changes the
  **target's armour value**, which the 5.2 mitigation stage consumes. States: satisfied (1..10
  stated stacks), not_satisfied (0 stacks — a reported ×1), unknown (no stack count), unsupported
  (stacks above 10: the Emerald Archon Shard raises the cap and stack replacement is a timeline).
* Stated stacks only. Heat's 50% armour strip, Corrosive Projection and every other armour source
  stay out (named in the refusal corpus).

### 5.6 — Generalisation test → the Umbral set bonus (`builds/effects.py`, data table)

* A materially different mechanic: its condition is **intrinsic to the build** (how many Umbral mods
  are equipped), not to the target or the context. It scales the set members' own contributions.
* Source-pinned rule (`Umbral Vitality` / `Umbral Fiber` / `Umbral Intensify` pages): Vitality and
  Fiber scale their value ×1.30 with 2 pieces and ×1.80 with 3; Intensify ×1.25 / ×1.75. One piece
  is a stated no-bonus, not a refusal.
* Every other set keeps refusing by name, with the reason saying the Umbral set is the modelled one.
* It required no special-case plumbing: the collection stage gains a scaling pass over the effects
  it already gathered, driven by a data table — the abstraction held.

### Validation cleanup

* `orokin`, `exilus_unlocked` and `slots[].unlocked` are now **typed booleans**: `"yes"` is a
  structured `invalid_boolean` error, never `True`. The same rule was extended to every Phase 5
  field (enemy fields, buffs) and the gate's malformed corpus now covers truthy strings, nested
  junk, and the whole enemy/buff surface.

## 2. Hard boundaries (unchanged, restated)

No combat simulator, no rotations, no hidden assumptions, no guessed stacks/uptime/armour/health,
no "average enemy", no page maths, no silent zero for unsupported mechanics, no `unknown → false`,
no `unsupported → 0`, no network dependency in the maths. Not every conditional mod; not every
status; not every set/Riven/Incarnon/Helminth/Shard mechanic.

## 3. The Phase 5 gate

`design/_planner/phase5_gate.py` — the new checks plus `--falsify` with the brief's minimum break
list (unknown armour becoming 0; missing target type becoming a default; unknown condition becoming
false; unsupported effect contributing damage; uptime assumed without input; stack count invented;
mitigation calculated in the browser; malformed target/context crashing; truthy strings accepted as
booleans; target-aware calculations moving Phase 1 numbers with no target context; a formula
constant in `static/`). The Phase 4 gate (`conditions_gate.py`) is preserved and re-run unchanged;
the two are complementary, not replacements.

## 4. Deliverables

Implementation (`builds/enemies.py`, `builds/buffs.py`, `builds/statuses.py`, `builds/effects.py`,
`builds/weapons.py`, `builds/validation.py`, `builds/schema.py`, `static/planner.*`, `server.py`
where needed); tests (`tests/test_target_model.py`, `tests/test_buff_state.py`,
`tests/test_phase5_refusals.py`); the gate; `docs/build-planner-target-model.md` (sources,
provenance, assumptions, exceptions); updated `docs/build-planner.md`; this plan; the phase report;
an independent adversarial review; exact gate/test results; before/after worked examples; the
supported-mechanics list; the remaining refusal corpus; known limitations; Phase 6 candidates.

## 5. Deviations from this plan (written after delivery)

1. **`builds/factions.py` was added** (§1 lists `enemies.py` as the new module). The Damage 3.0
   finding made the faction vocabulary a table with per-page citations and its own selftest, and
   Phase 4's `conditions.target_faction` was extended to read it; a separate module kept the
   weapon engine from growing an enemy-shaped section.
2. **Pool sizes are carried, not absent.** The plan says `health`/`shields` are "not fields"; the
   implementation accepts them into the target block *only* so the refusal can be precise — they
   are consumed by nothing and reported as `context_unused` / `evaluation.unused`. Refusing a
   stated input by name beats ignoring the key, which would look like a typo.
3. **The target path's trigger is narrower than "protection or armor or corrosive_stacks".** A
   Phase 4 caller who states `protection` alone (viral's landing) must not be silently pulled into
   the Phase 5 path, so the target block runs on `armor`, or `corrosive_stacks`, or `protection`
   **together with** `target_faction`. A build that states a landing without a faction stays
   Phase 4's answer; with a faction, the armour becomes a live input and is required.
4. **`target.armour` (British spelling) is accepted as `armor`.** The page's labels are British;
   the wiki's ids are American. The alias is explicit, not a fuzzy match.
5. **Negative armour is `unknown`, not "unarmoured"** — an added branch the plan did not
   anticipate, found by the falsification pass.
6. **The gate carries 16 breaks, not the brief's 11.** The five extra are the seams the brief's
   list implies but does not name: a constant armour rule, over-cap corrosive clamping, the
   unsupported-rider leak, Phase 1 drifting with no context at all, and the negative-armour case.
   The falsification pass then found two *inert* breaks (a patched function the engine had
   aliased at import, and a patch at the wrong seam) — a gate that cannot bite is worse than no
   gate, so both were repaired before the final run.
