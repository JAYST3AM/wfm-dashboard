# Phase 5 report — the stated target model, applied conditions, and stated buff state

Status: **complete**, 2026-09-30. Phase 4 remains complete and verified
(`design/build-planner/phase4-report.md`); the Phase 1–4 contracts were treated as non-negotiable
and every Phase 4 surface is re-verified in the results below.

The one-line version: the engine now answers **"build + explicitly stated combat context → exact
result, or conditional result, or named refusal"** against a real enemy model, with one conditional
rider actually applied end to end and one new target-state mechanic — and it still refuses to guess
anything. It is not a combat simulator: no rotations, no proc rates, no assumed armour, no invented
stacks, no browser maths.

## 1. What shipped (milestone → code)

| Brief | What it became | Where |
|---|---|---|
| 5.1 enemy/target model | `target_faction` + `target` block (`protection`, `armor`, `corrosive_stacks`, `viral_stacks`), stated-only, four-state, source-pinned; `factions.py` carries the Damage 3.0 table with per-page citations | `builds/enemies.py`, `builds/factions.py`, `builds/conditions.py` |
| 5.2 damage against target | per type per projectile: faction modifier × armour mitigation, minimum-1 rule, Overguard/Void, shields immune to armour DR; full trace `target_damage` + `target_damage.<type>` (base → build → conditional → target → mitigation → final), every row with its wiki source | `builds/enemies.py` + wiring in `builds/weapons.py` |
| 5.3 first applied condition | the On-Kill multishot rider (Galvanized Chamber/Diffusion/Hell): stated state → contribution → stat total → trace → result, all four states reachable | `builds/buffs.py`, rider block in `builds/weapons.py` |
| 5.4 stack/uptime without simulation | instant (`{"stacks": N}`) vs averaged (`{"stacks": N, "uptime": f}`), never mixed; averaged answers carry their assumption in words in `result.assumptions`, the rider row and the trace note | `builds/buffs.py` |
| 5.5 second target mechanic | corrosive armour reduction (26% first proc, +6%/stack, 80% at 10) feeding the mitigation stage — a different architecture from viral | `builds/statuses.py` |
| 5.6 generalisation test | the Umbral set (Vitality/Fiber ×1.30 @2, ×1.80 @3; Intensify ×1.25/×1.75) as a data-driven scaling pass — no special-case plumbing | `builds/effects.py` |
| validation cleanup | `orokin`, `exilus_unlocked`, `slots[].unlocked` are typed booleans; `"yes"` → `invalid_boolean`; the same discipline covers every new field | `builds/validation.py`, `builds/api.py` |
| page | target card (faction, layer, armour, corrosive, on-kill stacks/uptime) that states inputs and prints the engine's target block, riders, assumptions and trace; zero maths | `static/planner.html`, `static/planner.js` |

Sources, revision ids, pinned values and the explicit non-claims: **`docs/build-planner-target-model.md`**.

## 2. Exact results (this machine, 2026-09-30)

Every run below was executed sequentially (nothing else touching the repo, the dev server or a
browser) on the frozen tree; the exact commands are in section 10.

| Run | Result |
|---|---|
| `python -m pytest tests -q` (full suite) | **0 failed** — 2150 passed / 5 skipped when no game window is open, 2148 passed / 3 failed (the whisper window check) while `Warframe.x64` runs; no other test ever failed (see the note under this table) |
| `pytest tests/test_target_model.py tests/test_buff_state.py tests/test_phase5_refusals.py` | **44 passed** (the new Phase 5 tests) |
| `python design/_planner/conditions_gate.py --falsify` (Phase 4) | **PASS — 27 checks, 0 failed; 11 of 11 breaks caught** (refusal preservation intact) |
| `python design/_planner/phase5_gate.py --falsify` (Phase 5) | **PASS — 32 checks, 0 failed; 16 of 16 deliberate breaks caught** |
| `python design/_planner/build_planner_gate.py` (browser/UI workflow) | **PASS — 121 checks, 0 failed** (includes 6 new Phase 5 target/buff/trace checks) |
| `python design/_stage10/gate.py` (release acceptance, live app) | **GATE PASS — 121 checks, 0 failed, 38 states driven** |
| `python builds/debug.py selftest` (module selftests) | green (`DEBUG_EXIT=0`) |
| `python design/_planner/phase5_examples.py` | the worked examples in section 3 |
| `python design/_planner/phase5_corpus_census.py` | the corpus census in section 5 |

Honest note on the earlier runs: three full-suite passes reported failures in
`tests/test_whisper.py`, and one reported `tests/test_meta_watcher.py`. Both were chased down:

* `tests/test_whisper.py` fails exactly while the game is open —
  `check('windows: EnumWindows really runs (no game here, nothing matched)',
  isinstance(windows(), list) and find_game() is None)` fails as soon as a Warframe window exists on
  the desktop (confirmed: `Warframe.x64` was running during the failing passes and not during the
  passing one). Verified failing identically at `HEAD cdcb837` in a clean worktree. It is a
  whisper-tool selftest about the game window, not a Phase 5 surface.
* `tests/test_meta_watcher.py` passed in isolation and in the sequential pass; its single failure
  happened while two other gates were driving browsers at the same time.

Every other test passes in every run: **2148–2150 passed, 0 failed, 5–6 skipped**, depending only
on those three window-dependent whisper checks.

## 3. Before/after worked examples (real payloads)

**A. The target path** — Braton Prime with Serration R10 (+165%), Phase 1 per-shot 92.75:

| stated context | Phase 1 numbers | damage vs target (per projectile) | evaluation |
|---|---|---|---|
| none | 92.75 / crit-expected 103.88 | *(no target block at all)* | deterministic |
| grineer / health / armour 300 | unchanged | **66.5481** | deterministic |
| grineer / health / armour 900 | unchanged | **45.6696** | deterministic |
| grineer / health / armour 900 + 4 corrosive procs | unchanged | **58.1018** (net armour 504; the corrosive row is a condition row with its formula and source) | deterministic |
| grineer / health, armour missing | unchanged | withheld | conditional, `target_damage` unknown, `target.armor` named |

The Phase 1 numbers are identical in every row: the target path adds a block, it does not
re-derive the build (pinned by the gate, and by a break that tries to move them).

**B. The applied rider** — add Galvanized Chamber R10 (+80% multishot, "On Kill: +30% for 20s, 5x"):

| stated buff state | multishot | damage per shot | rider row |
|---|---|---|---|
| *(none)* | 1.8 | 166.95 | `unknown`, nothing applied, `buffs.on_kill` named as missing |
| `{"stacks": 0}` | 1.8 | 166.95 | `not_satisfied` — a reported zero |
| `{"stacks": 3}` | **2.7** | **250.425** | `satisfied · instant · +90% multishot` |
| `{"stacks": 5, "uptime": 0.65}` | **2.775** | **257.3812** | `satisfied · averaged · +97.5% multishot`, with `assumption: averaged: 5 stacks at 65.0% uptime (stated by the caller)` |
| `{"uptime": 0.65}` (no stacks) | 1.8 | 166.95 | `unknown` — the engine does not invent the stack count to average |
| `{"stacks": 99}` (above the 5x cap) | 1.8 | 166.95 | `unsupported` — stack replacement is a timeline |

**C. The generalisation proof** — Excalibur (370 health), Umbral pieces:

| pieces | health |
|---|---|
| none | 370 |
| 1 (Vitality) | 740 (the mod's own +100%) |
| 2 (Vitality + Fiber) | **851** (Vitality's bonus ×1.30) |
| 3 (+ Intensify) | **1036** (×1.80) |

## 4. Supported mechanics (the whole list, deliberately short)

* **Target**: stated faction (15-faction Damage 3.0 vocabulary) → vulnerability/resistance per
  damage type; stated landing layer (health / armour-health / shields / overguard); stated net
  armour → damage reduction (`0.9·sqrt(AR/2700)`, `AR/(AR+300)` above 2700); the 1-damage minimum;
  Overguard's Void vulnerability and its immunity to armour DR.
* **Target state**: corrosive procs (armour reduction), viral procs (damage-to-health multiplier,
  Phase 4).
* **Build state**: `first_shot` (Phase 4), the On-Kill multishot rider from a stated instant or
  averaged buff state, the Umbral set scaling.
* **Faction damage mods** ("Bane of …") including the Corrupted/Narmer/Techrot exclusions, which
  is a *stated* rule, not an assumption.
* Everything else Phase 1 already did (mods, elemental combination, crit, status, multishot, fire
  rate, capacity, polarity, ranks) — unchanged.

## 5. The remaining refusal corpus (what is still refused, and how it is named)

On the current database (777 equipment rows, 1809 mods): **1011 mods carry an unmodelled stat, 426
carry conditional effects, 1025 carry at least one of the two** — every one of them a *named*
refusal that travels with the build (`context_unused`, `conditional_effect`, `mechanic_unsupported`,
`buff_stacks_above_cap`, `corrosive_stack_timeline`, `dps_trigger_type`, …).

**The conditional-effect census** (`design/_planner/phase5_corpus_census.py`, 430 conditional lines
on 426 mods) — what the phase actually applies, against what it refuses:

| line shape | lines | what happens |
|---|---|---|
| on-kill rider, stat + stacks understood | **3** | **applies** from a stated buff state — Galvanized Chamber / Diffusion / Hell, all multishot |
| on-kill rider, stat not applied conditionally | 3 | refused by name with the stat (`the rider moves reload_speed, which this phase does not apply conditionally`) |
| on-kill rider, no signed percentage / no stack clause | 15 | refused by name with the piece it lacks (e.g. `the rider moves fire_rate but carries no "Stacks up to Nx" clause`) |
| weak point / headshot (incl. `when Aiming`) | 28 | refused; the clause is named in the condition row |
| per-stack (`for every`, `stacks with`) | 8 | refused — a timeline |
| on hit / on reload / on status / on crit / on taking damage / on dodge | 34 | refused; the trigger is named |
| no recognised trigger word (utility card text, e.g. combo-timer resets, orb drops) | 329 | refused as conditional text (Phase 4 shape) |
| `on kill` in the sentence but not a stat rider (6 lines) | 6 | refused — no stat rider to apply (e.g. `On Kill with Secondary Weapon: Reset Melee Combo Timer`) |

The families that matter beyond the table:

* **Status effects** beyond viral amplification and corrosive armour reduction: bleed, heat,
  electric, gas, blast, magnetic, radiation, toxin, cold, impact/puncture/slash procs, proc
  weighting, status duration.
* **Armour sources other than corrosive**: Heat's strip, Corrosive Projection and other auras,
  Shattering Impact, Warframe abilities.
* **Sets** other than Umbral; **Rivens**; **Incarnon**; **Helminth**; **Archon Shards**; arcanes.
* **Frames**: per-ability formulas, augment scaling, companion/squad buffs.
* **Exotic triggers**: charge/burst/continuous effective fire rates (DPS withheld rather than
  guessed), melee combo/heavy/stance.
* **Enemy properties outside the model**: any unstated target state, pool sizes (`health`,
  `shields` — named as unused), health/armour *types* (they no longer exist as per-type tables),
  status immunity/resistance beyond `immune_to` on viral (Phase 4), enemy auras, shield regen.

## 6. Attacked by falsification

`design/_planner/phase5_gate.py --falsify` installs sixteen deliberate defects and requires the
checks to catch each one. All sixteen are caught:

unknown armour → 0 · missing armour → 0 (mitigation runs anyway) · missing layer defaulted to
health · unknown faction defaulted to grineer · unknown reported as not_satisfied · unmodelled
rider folded into the totals · unstated rider treated as one stack · uptime without stacks
inventing the cap · no state at all assumed as 50% uptime at max stacks · malformed target value
raising instead of answering · truthy strings accepted as booleans · over-cap corrosive clamped to
a number · the target path contaminating Phase 1 numbers · Phase 1 drifting with no context at all ·
a constant armour rule (no dependence on the stated armour) · an enemy formula constant living in
`static/`.

Two findings the falsification pass produced about the *gate itself*, both fixed and both worth
recording:

1. **An inert break proves nothing.** The first `unsupported-contributes` break patched
   `effects.collect_mod_effects`, but `builds/weapons.py` aliases that function at import
   (`collect_mod_effects = effects_mod.collect_mod_effects`), so the weapon engine never saw the
   patch and the break "passed" without touching the engine. The break now patches both seams —
   and the break that *is* inert is treated as a gate failure, not a green tick.
2. **A break must be pointed at the decision, not at a helper.** The over-cap corrosive break
   patched `corrosive_reduction` (the arithmetic), but the cap decision lives in
   `evaluate_corrosive`, so the patch was unreachable. Repointing it at the decision made the
   check bite.

## 7. Independent adversarial review

Four review passes ran against this phase with different mandates; none of them wrote the
implementation. Their full reports travel with this session's delegation messages; what follows is
what was verified in their own artifacts (probe scripts and raw outputs, kept under
`…/cache/scratch/wf5/review*`), and what was changed because of them.

**A. Engine falsification (12 adversarial probes + a crash reproduction + a seeded 400-case junk
fuzz).** Verdict: **the abstraction survived, the input hardening did not** — three malformed shapes
raised out of `api.compute` instead of answering:

| finding | what raised | where |
|---|---|---|
| `target.armor` as a 401-digit JSON integer | `OverflowError` | `enemies._as_number` (`float(value)`) |
| `buffs.on_kill.uptime` as a 401-digit integer | `OverflowError` | `buffs.evaluate_state` |
| `target.immune_to` as a number / a list with junk | `TypeError: not iterable` | `statuses.evaluate` |

All three are fixed in this phase (an unbounded JSON integer is not a number this model can
express; `immune_to` now goes through a typed helper that accepts a name or a list of names and
refuses anything else by value). They are pinned twice: `enemy/malformed-never-crashes` in the
Phase 5 gate, and `test_a_json_document_cannot_make_the_engine_raise` in the test suite. The same
review also confirmed — with probes, not by inspection — that no target default exists anywhere,
that an unapplied rider contributes nothing while its stated state is named unused, that a rider's
value comes from its own rank's table (never the max-rank row), and that strict mode withholds
rather than zeroes. Two ambiguities it flagged are now *named* instead of silently resolved: a
conflicting second spelling of a target field (`armor` + `armour`) appears in `context_ignored`,
and a non-name `immune_to` entry is quoted back in an `unknown` row.

**B. Source/provenance verification against the live wiki.** The reviewer re-fetched the raw
wikitext at every claimed revision (`Armor` 2814011, `Damage` 2812034, `Damage/Overview_Table`
2792179, `Damage/Corrosive_Damage` 2804597, `Damage/Calculation` 2804415, `Overguard` 2808615,
`Faction_Damage_Bonus` 2804854, the three Umbral pages) and diffed them against the current pages:
byte-identical, so the pins are current, not stale. It spot-checked faction rows and the
Bane-mod coverage rule, and reproduced the engine's published figures against the doc's §3 pins
(504.00000000000006 / 0.3888444419044716 / 0.6111555580955284; 92.75 / 103.88 / 995.5132). Any
residual discrepancy it reports is listed in the delegation message and in section 8.

**C. Page semantic-authority audit.** No Warframe maths in the page: the target card's inputs are
collected, validated for shape only, stored and posted; every figure printed comes from the
`/api/planner/compute` payload. The one note it raised (a decimal-only regex inside the page's own
storage validator, which the page's number inputs cannot produce but a hand-edited localStorage
could) is recorded in section 8 as a limitation of the page's storage sanitiser, not of the engine.

**D. Architecture review (six design questions).** Verdicts on record: the target state is carried
by the context with no leak into the weapon engine (SOUND); the target path's trigger rule, the
corrosive mechanic's different architecture (target armour, not a damage multiplier), and the
Umbral pass all survived scrutiny; the one structural critique accepted is that a *second* rider
needs a stat the engine already models **and** a source pin per rider, so "the next rider" is one
wiring entry plus provenance — not pure data. That is recorded in section 8, and it matches the
Phase 6 proposal 1.

The reviewers found nothing that required a design change; everything they broke was an input
boundary, and every boundary they broke is now pinned.

## 8. Honest known limitations

* **Only one conditional rider family is applied** (On-Kill multishot riders). The buff-state model
  is general (instant/averaged, any trigger key it knows), but each new rider needs (a) a stat the
  engine already models and (b) a source pin of its own — the architecture review's one accepted
  critique. So a new rider is one wiring entry plus provenance, not free.
* **The page's storage sanitiser is a shape check, not a type system.** A hand-edited or foreign
  `localStorage` value that is not a plain decimal string is dropped by the page's own validator
  (the engine would have refused it precisely); the page's number inputs cannot produce one.
* **The target model has no timeline.** Stack counts are states. Rotations, proc rates, stack
  replacement above a cap, and enemy actions are out of scope by design — which is why several
  mechanics refuse rather than approximate.
* **No pool maths.** "How many shots to kill" is not computed, because it needs a health pool and an
  exposure window the caller has not supplied.
* **Viral and corrosive are the only status mechanics**; both are single rules (no tick damage, no
  proc weighting).
* **Armour is the caller's number.** The engine applies the modelled reductions to it but does not
  derive it from a unit's rank/type, and does not model armour stripping other than corrosive.
* **The page's trace viewer is engine text.** There is no plotting, no comparison view for two
  targets, and the target card is one target at a time.
* **`target.health`/`target.shields` are refused as unused**, so a UI cannot yet show "shots to
  kill" even if a user wants it — deliberately, until the model can do it honestly.
* **Corpus wording drift.** Conditional lines are matched by pattern; a reworded card can fall back
  from "refused as a condition" to "refused as unmodelled text" (still refused, less precise). The
  registry coverage check runs over the whole corpus on every gate run, so it would be noticed.

## 9. Phase 6 candidates (in the order I would take them)

1. **Finish the On-Kill family**: the remaining Galvanized/Acolyte riders (crit chance/damage,
  status chance) share the exact shape the multishot rider already proves; each is a data-table row
  plus a pinned source. Also: an `active: true` + cap-stated form for single-stack riders.
2. **Target-state presets from the game's own data** (faction → armour/health/shield profiles per
   unit *class*, not per unit) — but only with an exported source, and as *stated* context the user
   picks, never a default.
3. **Heat as a second armour source** (Heat procs strip armour over time — needs the same
   stated-state treatment as corrosive, plus the wiki's strip rule).
4. **A "shots to kill" block** once the caller can state a pool size: it is one division away from
   what the engine already computes, and the refusal is already the honest gate for it.
5. **Comparison view for two targets** (same build, two stated enemies) — a UI feature the engine
   already supports by being callable twice.
6. **Set-bonus generalisation**: Augur/Gladiator/Vigorous-style sets, one pinned row at a time, now
   that the Umbral pass proved the shape.
7. **Riven conditions** — the last of the "materially different advanced mechanic" families, and the
   hardest: a Riven's stats are caller-supplied numbers, so the interesting part is refusing to
   invent them while still allowing the stated ones.

## 10. Files changed / how to re-run

Engine: `builds/enemies.py` (new), `builds/buffs.py` (new), `builds/factions.py` (new),
`builds/statuses.py`, `builds/conditions.py`, `builds/effects.py`, `builds/weapons.py`,
`builds/validation.py`, `builds/api.py`, `builds/warframes.py`. Page: `static/planner.html`,
`static/planner.js`. Tests: `tests/test_target_model.py`, `tests/test_buff_state.py`,
`tests/test_phase5_refusals.py`, plus updates to `tests/test_planner_api.py`,
`tests/test_condition_states.py`. Gates: `design/_planner/phase5_gate.py` (new),
`design/_planner/build_planner_gate.js` (extended). Docs: `docs/build-planner-target-model.md`
(new), `docs/build-planner.md`, `design/build-planner/phase5-plan.md`, this report. Data:
`data/build_data.json` re-ingested (1011 unmodelled / 426 conditional).

```bash
python builds/ingest.py                                   # the database the numbers above used
python -m pytest tests -q                                 # full regression suite
python design/_planner/conditions_gate.py --falsify        # Phase 4 refusal preservation
python design/_planner/phase5_gate.py --falsify            # Phase 5 target model + falsification
python design/_planner/build_planner_gate.py              # browser/UI workflow gate
python design/_stage10/gate.py                            # release acceptance gate (live app on :8787)
python design/_planner/phase5_examples.py                 # the worked examples in section 3
python design/_planner/phase5_corpus_census.py            # the census in section 5
```

Run the browser gates one at a time: they each boot a browser, and the whisper selftest (a plain
pytest) dislikes a busy desktop, so the final verification pass above was executed sequentially.
