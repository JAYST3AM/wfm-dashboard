# Phase 6 report — the mechanic registry, and the mechanics that proved it

Closed 2026-09-30. Phase 5 is the baseline (`design/build-planner/phase5-report.md`); the Phase 1–5
contracts are unchanged. The plan this executed is `design/build-planner/phase6-plan.md`.

Phase 6's goal was structural, not numerical. Phase 5's fourth adversarial review had found that a
mechanic's requirements lived in four unrelated places - trigger logic, consumed-context accounting,
the trace hook, the target/mitigation integration - and that forgetting one of them failed
*silently*: a stated field vanished, a factor went untraced, a refusal lost its blast radius. Phase 6
builds one declarative registry, migrates the existing mechanics onto it **with identical answers**,
then adds mechanics *through* it - including one that needed a stage the engine did not have (Heat's
armour transform).

## 1. Milestones

| # | Milestone | Delivered | Evidence |
|---|---|---|---|
| 6.1 | Declarative mechanic registry | `builds/mechanics.py` (registry + rule DSL + derived plumbing + validator), `builds/mechanics_table.py` (14 declarations), `python builds/debug.py mechanics` | `phase6_gate.py` checks 1–6, 15; §4 below |
| 6.2 | Migrate the Phase 4/5 mechanics | same answers; declarations moved, implementations stayed | `phase6_migration.py`: **48 cases, 0 diffs against `f1f2db3`** |
| 6.3 | Finish the safe rider family | `ENABLED_STATS` is the declaration (`multishot`, `critical_chance`, `critical_damage`, `status_chance`, `reload_speed`, `fire_rate`); single-stack cards (no "Stacks up to Nx") read as cap 1 | gate checks 'riders: …'; `tests/test_phase6_registry.py`; corpus census §6 |
| 6.4 | Heat armour strip through the registry | `statuses.evaluate_heat` / `heat_armour_transform` / `heat_trace_row` + one declaration; the transformer loop in `enemies.evaluate` is the registry's | examples §3; gate 'heat: …' checks |
| 6.5 | Target presets | **deferred, documented, refused by name**: this database has no enemy rows at all, so `target.preset` → `preset_unavailable` (never fabricated, never inferred) | §5; gate 'presets: …' checks |
| 6.6 | Pool damage / shots to kill | `result.pool` (+ `stats.shots_to_kill`, its trace and its assumptions); no pool → no key; wrong layer → `pool_landing_mismatch`; unresolved path → `pool_unresolved` | §3; gate 'pool: …' checks |
| — | Architecture invariant | `mechanics.register`/`_validate` refuse a half-declared mechanic at import, property by property | 16 malformed declarations in the gate, each refused |
| — | Trace integrity | generic composition checks (physical, elemental, faction, armour, corrosive, Heat, riders, pool); each transform's row carries its own step; `_ride_rows` refuses a rider filed under the wrong trace | gate 'composition: …' + 'trace: …' checks |
| — | Refusal blast radius | derived from `mechanics.withholds_for`; the Phase 5 fix is now a declaration, not a hand list | gate 'blast radius: …' checks + phase-5 tests |
| — | Input hardening | every new field typed and bounded; `api.compute` never raises from caller JSON | 20 malformed inputs in the gate + 12 in the tests |

## 2. The migration gate (6.2)

`design/_planner/phase6_migration.py` extracts the pre-migration engine (`git archive f1f2db3`), runs
the same probe corpus against both engines and the same database, and diffs the canonical payloads.

```
migration gate: 48 cases, 0 diff(s) against f1f2db3 - IDENTICAL
  (21 case(s) differ only by a declared Phase 6 field in evaluation.consumed)
```

The single allowance is deliberate and narrow: the target path now *asks the Heat question*, so
`target.heat_strip` appears in `evaluation.consumed` for cases that run the path - exactly what
happened when Phase 5 added `target.corrosive_stacks`. The gate drops only the Phase 6 field names,
reports which cases needed it, and fails on anything else (including any other key inside
`evaluation`). No pinned answer moved; two Phase 5 *tests* moved, both because the honest answer
changed on purpose and both with the reason recorded in the test:

* `test_the_target_block_reports_exactly_what_it_consumed` — a stated pool size is no longer "unused"
  (the pool result consumes it and produces a block); the test now asserts the block, not the silence.
* `test_a_rider_worded_for_another_stat_still_refuses` — split into `test_a_single_stack_rider_…`
  (the fixture card now rides the shared path with cap 1) and
  `test_a_rider_worded_for_an_unmodelled_stat_still_refuses` (a Zoom rider keeps its named refusal).

## 3. Worked examples (executed; `python design/_planner/phase6_examples.py`)

**Heat (`Damage/Heat_Damage`, oldid 2807948)** — Braton Prime + Serration R10, Grineer, lands on
health, armour 900:

| stated strip | condition row | armour effective |
|---|---|---|
| not stated | (no heat row) | 900.0 |
| 0 | `heat` not_satisfied (a reported zero) | 900.0 |
| 15% | `heat` satisfied | 765.0 |
| 50% | `heat` satisfied | 450.0 |
| 35% | `target_damage` **unsupported** (`heat_strip_value`) | withheld |

With corrosive 4 + heat 50: effective armour **252.0** = 900 × 0.56 × 0.5 (the wiki's multiplicative
form), and the trace carries each step separately: `Corrosive (4 stacks) -396.0`, `Heat strip (50%)
-252.0`, then the DR row.

**The pool** — Grineer, health 5000, armour 900, damage per shot 45.6696 (crit-expected 51.15):

```json
{"layer": "health", "pool": 5000.0, "damage_per_shot": 45.6696,
 "damage_per_shot_expected_crit": 51.15, "shots_required": 110, "expected_shots": 97.7517,
 "assumptions": ["shots_required assumes no critical hits (pool / damage per shot, rounded up)",
                 "expected_shots is pool / crit-expected damage per shot: an expectation, not a guarantee"]}
```

No pool → no block and no `pool` key; a shields pool with a health landing → `pool_landing_mismatch`;
a health pool with no resolved damage path → `pool_unresolved` and no number.

**The riders** — Kill Switch ("On Kill: +50% Reload Speed for 3s", no stack clause) with `stacks: 1`:
cap 1, per_stack 50.0, contribution 50.0, `reload_time` 2.15 → **1.4333**, and the reload trace row
carries `condition: on_kill, state: satisfied, stacks: 1`. Averaged state (stacks + 50% uptime) →
25.0 with the assumption printed. `stacks: 2` → `unsupported` ("above the 1x cap this mod
documents"). The enabled stats are the registry declaration:
`('multishot', 'critical_chance', 'critical_damage', 'status_chance', 'reload_speed', 'fire_rate')`.

**The preset gap** — `target.preset: 'level-100-heavy-gunner'` → the aggregate row is `unsupported`
with `preset_unavailable` and a reason naming the missing source; the Phase 1 numbers still answer
(92.75).

## 4. Verification (frozen tree)

| Suite | Result |
|---|---|
| `python -m pytest tests -q` | **2178 passed, 6 skipped, 3 failed** - all three in `tests/test_whisper.py`, which fail identically at HEAD and while the game window is open (environment-dependent, pre-existing) |
| `python design/_planner/phase6_gate.py` | **115 checks, 0 failed** |
| `python design/_planner/phase6_gate.py --falsify` | **18/18 breaks caught** |
| `python design/_planner/phase6_migration.py` | **48 cases, 0 diffs** against the Phase 5 tip |
| `python design/_planner/phase5_gate.py --falsify` | 37 checks, 0 failed, 16/16 breaks |
| `python design/_planner/conditions_gate.py --falsify` | 27 checks, 0 failed, 11/11 breaks |
| `python design/_stage10/gate.py` | **GATE PASS** (static + live puppeteer gate + report) |
| browser gate (`build_planner_gate.py`, incl. the new §21d) | **PASS - 127 checks, 0 failed** |

The 18 falsification breaks, each required to touch its decision path (a break that fails nothing is
a gate failure):

1. a mechanic declared without consumed fields passes validation → caught
2. a mechanic declared without a trace destination passes validation → caught
3. a mechanic without a trigger passes validation → caught
4. the Heat strip defaults from a missing input → caught
5. a trace row stops composing (Heat reports the wrong delta) → caught
6. the target block is allowed to withhold unrelated numbers → caught
7. a missing armour value erases the Phase 1 numbers → caught
8. a missing armour value erases the Viral answer → caught
9. a rider the engine cannot source contributes its stat → caught
10. a crit rider is routed into the multishot trace → caught (the declaration guard refuses)
11. a stated pool is answered when the landing cannot support it → caught
12. shots-to-kill uses a partially refused damage path → caught
13. a duplicate set member raises the set count → caught
14. a malformed pool size raises out of the engine → caught
15. a mechanic formula appears in `static/` → caught
16. the registry stops being the accounting source → caught
17. a mechanic is evaluated without its trigger being stated → caught
18. the pool block survives a strict withholding → caught

## 5. 6.5 target presets: the gap, documented

The database carries `equipment` (warframes/weapons/sentinels) and `mods`, and **no enemy rows at
all** - no `enemies` key, no per-unit level/armour/health profiles, and no enemy name anywhere in the
content. There is therefore no authoritative source in this project to join a preset to, and per the
brief the milestone is a documented deferral rather than a fabrication: the engine exposes
`target_preset` as a declared mechanic whose only behaviour is a **named refusal**
(`preset_unavailable`), and Phase 7 can revisit it if a sourced, versioned enemy export is added.
Selecting a preset is never inferred from build context, and no preset is ever substituted silently.

## 6. The conditional-rider corpus (what applies, what still refuses)

Executed census over the live database (1011 unmodelled / **426 mods carrying 430 conditional
lines**; `phase5_corpus_census.py`, re-derived independently by the corpus review in §8):

| class | count | mods |
|---|---|---|
| `On Kill:` lines **applied** | **7 lines / 7 mods** | multishot: Galvanized Chamber, Galvanized Diffusion, Galvanized Hell; reload speed (single stack): Kill Switch, Secondary Wind, Emergent Aftermath; fire rate (single stack): Gorgon Frenzy |
| refused: no signed percentage the engine can read | 5 | Aerial Ace, Momentary Pause, Momentary Recover, Momentary Recuperate, Relentless Assault |
| refused: an aiming clause the engine will not model | 3 | Bladed Rounds, Sharpened Bullets, Shrapnel Shot |
| refused: not a positive bonus (a debuff-shaped value) | 3 | Calculated Victory, Prize Kill, Vanquished Prey |
| refused: per-status-type scaling | 3 | Galvanized Aptitude, Galvanized Savvy, Galvanized Shot |
| refused: a compound stat the engine has no model for | 1 | Galvanized Acceleration (projectile speed + beam range) |

The wider kill-trigger family (34 lines beginning `On …Kill`: melee kills, headshot kills, weak-point
kills) refuses on the trigger, and the newly-enabled stats `critical_chance`, `critical_damage` and
`status_chance` have **no applied corpus rider** - their corpus candidates are all
`On Weak Point Kill:` / `On Melee Kill:` - so their destinations are exercised with engine-path
fixtures (all six declared destinations verified as traces the engine builds and prints). Every
refusal keeps its four-state vocabulary, its named stat or clause, and its provenance.

Note: `On Kill: +70% Zoom` (quoted in an earlier draft of this table) is not a corpus line - the
corpus's zoom lines are `-50% Zoom while Aim Gliding`, which refuse on the negative value.

## 7. Known limitations, and what is deferred

* **Presets** (above) — deferred with a named refusal.
* **Squad armour auras** (Corrosive Projection): the Heat formula composes with them on the wiki, but
  auras are a squad state this engine does not model; `squad_armour_auras` exists as a declaration so
  the term is named rather than dropped.
* **Heat's DoT and the strip's ramp timing**, **corrosive's stack timeline**, **proc durations**:
  timelines, refused by name.
* **Two-pool depletion** (shields then health, Overguard then health): one stated pool at a time.
* **Melee attack speed**: the fire-rate rider's declared destination is the `fire_rate` trace; melee
  builds trace `attack_speed` (the declaration documents the alias; no corpus card needs it today).
* **The rider enablement boundary**: a card whose clause the parser cannot read keeps a refusal, even
  when a human could read the intent. A *newly enabled* stat must also declare a trace destination:
  the validator refuses the declaration otherwise, so an untraced factor cannot be enabled silently.
* **Innate elemental damage has no per-type weapon trace** (review 2, F4): a weapon whose own damage
  includes an element (Zaws and friends) reports those per-type figures in `result.damage.composition`
  and the combined-element path, not in a `damage.<type>` trace; the composition block agrees with the
  per-type numbers (an 852-case coverage sweep found no disagreement), but the *trace* for the innate
  case is a Phase 7 candidate. The same sweep found one cosmetic artefact: an innate-composition
  weapon can report a −0.0002 rounding residue in a combined-element slot.
* **Pre-existing, not Phase 6**: `forma_count` is accepted and echoed without validation; the four
  Conclave rider mods are installable through the API and apply their (PvP) values when a caller
  states the state (the page hides them in its own bucket); a Gorgon-only mod installs on any
  primary (the compatibility field is coarse). All three are recorded for Phase 7 rather than
  changed in a phase that was about the registry.
* **The declaration's `trace` field is verified, not consulted by every site**: `mechanic.trace` is
  checked against the engine's trace keys at declaration time and the gate walks the destinations,
  while the *runtime* enforcement is the rider path (`_ride_rows` refuses a rider filed under a trace
  its declaration does not name). An earlier draft of this report and of `docs/build-planner.md`
  claimed the engine reads `trace_for()` everywhere; the reviews were right that it did not, and the
  claim is corrected here.

## 8. Independent review dispositions

Three independent agents reviewed the phase (registry architecture + refusal blast radius; trace
composability + malformed-input fuzzing; corpus audit + final adversarial pass). Each ran executed
counterexamples and wrote only under its own scratch directory. **Every finding is either fixed on
this tree (with the pinning test or gate check named), or deferred with a reason** (§7).

| # | Finding (reviewer) | Disposition | Pinned by |
|---|---|---|---|
| R1-F1 | strict-mode blast radius was a hand list in `weapons.py`; a blocked **pool** row wiped the Phase 1 and viral numbers; `pool_result`'s condition id never joined (`by_condition('pool')` was None) | **fixed**: the withholding is `mechanics.withholds_for(blocked)`; `condition_id='pool'`; the validator refuses duplicate condition ids and duplicate singleton stages | `check_review_fixes_hold` (gate), `test_a_pool_only_refusal_leaves_the_phase_one_numbers_alone` |
| R1-F2 / R3-F1 | a withheld per-shot figure survived inside `result.pool` (`MIRROR_PATHS` had no pool entry) and its trace final stayed live | **fixed**: the pool block is a mirror of the per-shot figures; the block and its trace are nulled with them | `test_a_withheld_per_shot_figure_takes_the_pool_block_with_it`, the new falsification break *"the pool block survives a strict withholding"* |
| R1-F3 / R3-F7 | the accounting's *reporting* side was a hand list, so a stated `target.overguard` (and on a Warframe build, `heat_strip`/`preset`) was dropped silently | **fixed**: `conditions.stated_fields` is derived from `TARGET_FIELDS`/`ATTACK_FIELDS`, which are derived from the registry | `test_every_stated_target_field_is_reported_even_when_unconsumed`, gate check *"a stated overguard value is reported"* |
| R1-F4 | `trace_for()` had no engine callers: the declared destination was documentation | **fixed where it decides behaviour**: `_ride_rows` consults the declaration and refuses a rider filed under a trace it does not name, a refused rider's note goes to the declared trace, and the validator rejects a destination the engine cannot build; the claim in the docs is corrected to say exactly that (§7) | gate check *"riders: rider traces match their declared destination"*, `test_a_refused_rider_says_so_on_the_trace_its_declaration_names` |
| R1-F5 | five declaration shapes passed validation (trace key that does not exist, family/stage that no dispatcher reaches, unresolvable `evaluate`, non-string properties, a second rider mechanic ignored by `rider_stats()`) | **fixed**: `TRACE_KEYS`, `STAGES_BY_FAMILY`, `SINGLETON_STAGES`, type checks, stat↔destination coverage, and `_declare_path` resolves the implementation (deferring only a genuinely mid-import module, then `verify_declarations()` finishes the check) | `test_the_validator_refuses_declarations_the_engine_could_never_reach` |
| R1-F6 | enabling a rider stat with no trace applied an untraced factor | **fixed**: the stat list and the destination list must agree at declaration time | same test (stat↔destination coverage) |
| R1-claim 4 | "unknown is never false / unsupported is never zero" | **no counterexample found**; the reviewer's probes are listed in its report | — |
| R2-F1 | a huge-but-finite pool (`1e308`) raised `OverflowError` out of `math.ceil` (HTTP 500) | **fixed**: a non-finite quotient is a named `pool_unresolved` refusal; finite ones answer | `test_a_huge_but_finite_pool_never_raises_and_answers_or_refuses_by_name`, gate check *"a non-finite-quotient pool answers or refuses by name"* |
| R2-F2 | a 400-digit mod rank raised `OverflowError` in `capacity.slot_drain` | **fixed**: ranks outside 0..10^6 are refused by value; the breakdown reports `invalid_rank` instead of raising | `test_a_rank_the_engine_cannot_drain_is_a_named_error_not_an_exception` |
| R2-F3 | strict + a pool refusal over-withheld (same root as R1-F1) | **fixed** (above) | gate + test as R1-F1 |
| R2-F4 | innate elemental per-type figures have no weapon-level trace; one −0.0002 residue | **deferred** with reason (§7); the 2,026-case coverage sweep found no *numeric* disagreement | §7 |
| R2-F5 | a reload rider's trace row dropped the "reload speed, time divides" cue | **fixed**: `_ride_rows` carries the row's own note *and* the unit cue | `test_a_single_stack_rider_is_cap_one_and_rides_the_same_path` (rider note), examples §3 |
| R2-F6 | the pool epsilon could under-deplete a pool just above a multiple | **fixed**: the ceiling is verified against the published per-shot figure instead of an absolute epsilon | composition check *'pool'* + `test_the_pool_block_divides_only_a_stated_pool` |
| R2-F7 | the hypothetical first-shot row carried no marker | **accepted as a limitation**: the row's `state: unknown` plus the payload's `hypothetical` flag are the two facts, and the engine applies the bonus only in that mode; recorded in §7 | — |
| R2-F8 | a non-finite caller value echoed as bare `Infinity`, which browser `JSON.parse` rejects | **fixed**: echoed inputs pass through `conditions.safe_input` | hardening checks |
| R2-F9 | `forma_count` accepted unvalidated | **deferred** (pre-existing, §7) | — |
| R3-F5 | the Umbral roster counted an *unknown* member while refusing its scaling (contract says distinct + legal + known) | **fixed**: an unknown member is not a piece | `test_an_unknown_umbral_member_does_not_count_toward_the_set` |
| R3-F6 | the averaged buff path ignored state fields the instant path names | **fixed**: both paths name unrecognised fields | `test_the_averaged_state_names_fields_it_does_not_read`, gate check |
| R3-F8 | the report's census table and three `docs/build-planner.md` bullets were stale/wrong | **fixed**: §6 above is the executed census and the docs bullets name the six enabled stats, the pool block and the Heat strip | this report, `docs/build-planner.md` |
| R3 obs. | Conclave mods installable at API level; a reported zero appears under `evaluation.withheld`; `rider_trace_row` dead code; Gorgon Frenzy compatibility is coarse; the reload rider's number is unreachable through `api.compute` | **three accepted** (pre-existing, §7); **`rider_trace_row` removed**; the reload-rider case is documented as unreachable rather than special-cased | §7 |

Two engine defects the *new gate itself* found while this phase was being built are also recorded
here because they were found by checks rather than by a reviewer: the state-support validator hole
(a mechanic supporting no state passed) and the unhashable landing layer (`POOL_LAYER.get(layer)`
raised on a list from caller JSON). Both are fixed, with the validator rule and the coercion covered
by the gate's own invariant checks.

## 9. Phase 7 candidates

1. **A sourced enemy-profile export → the presets milestone** (6.5), with per-field provenance and
   explicit opt-in.
2. **A stated status-type count mechanic** (per-status-type riders), which needs a "direct damage"
   definition the trace can carry.
3. **A timeline layer** (proc durations, the Heat ramp and DoT) — the one thing that would unlock the
   largest remaining refusal class, and the one thing that must never be a simulator.
4. **Melee/bow special cases** (attack speed aliasing, charge attacks) through the registry.
5. **The two-pool depletion block** (shields → health), still without regeneration or gating.

## 10. The frozen-tree run

Every suite was run sequentially on the final tree (`ALL DONE`, nine steps, all exit 0):

```
01 pytest        2178 passed, 6 skipped, 3 failed (whisper trio: pre-existing, environment)
02 selftest      builds/debug.py selftest - green
03 phase 4 gate  27 checks, 0 failed, 11/11 breaks
04 phase 5 gate  37 checks, 0 failed, 16/16 breaks
05 phase 6 gate  115 checks, 0 failed, 18/18 breaks
06 migration     48 cases, 0 diffs against the Phase 5 tip
07 examples      the worked examples in §3
08 browser gate  PASS, 127 checks, 0 failed
09 stage 10      GATE PASS
```

## 11. Commands

```bash
PY="C:/Users/jayde/AppData/Local/hermes/hermes-agent/venv/Scripts/python.exe"
"$PY" design/_planner/phase6_gate.py              # 108 checks
"$PY" design/_planner/phase6_gate.py --falsify    # 17 breaks
"$PY" design/_planner/phase6_migration.py         # 48 cases vs the Phase 5 tip
"$PY" design/_planner/phase6_examples.py          # the worked examples above
"$PY" design/_planner/phase5_gate.py --falsify
"$PY" design/_planner/conditions_gate.py --falsify
"$PY" design/_planner/build_planner_gate.py        # browser gate (sequential)
"$PY" design/_stage10/gate.py
"$PY" -m pytest tests -q
"$PY" builds/debug.py mechanics                    # the registry table
```
