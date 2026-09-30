# WFM Build Planner — Phase 4 (Conditional Combat Model)

**Report for independent review. Prepared 2026-09-30.**

Repo: `JAYST3AM/wfm-dashboard` (private). Branch `main`, HEAD `16929ca`, working tree clean,
`main == origin/main`.

| commit | what |
| --- | --- |
| `b6cb0c3` | the Phase 4 plan this work implements (`design/build-planner/phase4-plan.md`), unchanged |
| `03d94c6` | **Phase 4: the conditional combat model — four states, structured refusals, three mechanics** |
| `5863297`, `d5a1e70` | two pre-existing CI reds on `main`, fixed (nothing to do with Phase 4; see §5) |
| `9ade643`, `5150665`, `16929ca` | report, count-overlap wording, the one flaky browser check explained |

CI (`GitHub Actions → tests`, ubuntu-latest, clean checkout with no `data/`): **success** on
`d5a1e70`, `9ade643`, `5150665`, `16929ca`. The two commits before those (`03d94c6`, `5863297`)
were red for the pre-existing reasons above.

---

## 1. The brief this had to satisfy

Phase 4's milestones, as given (abbreviated only in wording, not in requirement):

- **4.1 — Formalize condition states.** First-class `satisfied` / `not_satisfied` / `unknown` /
  `unsupported`, distinct from zero, false, missing input, or validation failure. Synthetic tests
  proving none of them silently becomes an unconditional modifier.
- **4.2 — Structured conditional refusals.** Existing conditional mods stay refused unless
  explicitly supported; replace generic refusals with structured reasons/state; do **not** migrate
  them all.
- **4.3 — First minimal condition source.** One condition resolvable entirely from build/evaluation
  context, path proved end to end: context → evaluation → state → effect → result/refusal, with all
  four states covered in tests.
- **4.4 — First status mechanic.** One small, precisely defined status mechanic, inputs/outputs
  documented, unknown input stays unknown, unsupported interactions refuse instead of approximating.
- **4.5 — Conditional damage evaluation.** An explicit evaluation context, distinguishing
  `deterministic` / `conditional` / `refused` results, with Phase 1/3 numbers unchanged when no
  conditional context is involved.
- **4.6 — Second mechanic + refusal audit.** A second mechanic different enough to test whether the
  abstraction generalises; if it needs hard-coded plumbing everywhere, stop and redesign. Plus a
  refusal-preservation regression gate.

Hard constraints: no combat simulator; no inverse build solver; no live/external game-data
dependency; no recommendation engine; do not migrate all the conditional mods; the browser/UI must
never perform Warframe calculations; never silently interpret unknown as false or zero; existing
Phase 1–3 behaviour must not regress.

Architectural rules to preserve: the engine owns every calculated number; refusals are valid
answers; validation/refusal codes survive through API → UI; malformed input must not crash the
engine; the page renders engine state, it does not infer game semantics.

Completion rule: *"Do not stop after merely making tests pass"* — falsification tests had to break
the new rules and prove the gates catch it, and Phase 4 could not be called complete unless all six
milestones were implemented **and** the refusal-preservation audit passed.

---

## 2. What was delivered, by milestone

### 4.1 — the four states are first-class (`builds/conditions.py`, 534 lines)

```
STATES          = ('satisfied', 'not_satisfied', 'unknown', 'unsupported')
STATE_CODES     = the state word itself is the code a consumer reads
CONDITION_REASON_CODES = ('condition_unknown', 'condition_not_satisfied',
                          'condition_effect_unimplemented', 'mechanic_unsupported')
REASON_CODES    = CONDITION_REASON_CODES + ('context_unused',)
NOT_A_STATE     = ('zero', 'false', 'missing_input', 'validation_failure')
```

A condition result is a dict, never a bare boolean:

```json
{"condition": "target_faction", "state": "satisfied", "code": null, "reason_code": null,
 "reason": null, "hypothetical": false, "inputs": {"mod_faction": "grineer"},
 "missing": null, "applied": true}
```

`unknown` and `unsupported` are **not** the same word and are never folded: `unknown` means "the
context did not say" (resolvable by stating an input), `unsupported` means "the engine has no model
for this, and no input would change that". A refusal can carry no value: where a mechanic would
produce a number, a refusal omits the key rather than setting it to `None` — asserted in
`builds/statuses.py`'s selftest (`'amplifier' not in refusal`).

### 4.2 — structured conditional refusals (`builds/effects.py`)

Every conditional line now refuses with `condition_id`, `state`, `reason_code` and the clause text,
instead of the old generic marker. The clause families are classified by
`conditions.classify_conditional_text`, and each family is refused with its **own** reason, not one
blanket code. Measured over the live database — 430 conditional lines across 426 mods:

| clause family | lines | refusal reason |
| --- | --- | --- |
| timer ("for 9s") | 157 | timed windows are not modelled (no combat timeline) |
| state_clause ("while aimed") | 137 | state clauses are not modelled |
| on_kill | 28 | on-kill stack behaviour is not modelled |
| per_unit ("for each") | 28 | per-unit scaling is not modelled |
| stacks ("stacks up to Nx") | 20 | stack accumulation over time is not modelled |
| sequence_clause ("after/upon") | 19 | sequence clauses are not modelled |
| target_status ("per Status Type") | 10 | per-status-on-target scaling is not modelled |
| on_reload / on_hit | 7 / 7 | trigger not modelled |
| unspecified | 6 | the engine cannot classify this clause yet |
| on_headshot / on_crit | 4 / 4 | trigger not modelled (no target model) |
| on_move / per_event | 2 / 1 | trigger not modelled |

**Nothing was migrated for its own sake**: the only conditional things that became calculable are
the two in §3 plus the status in §4; the other ~430 lines are refused by name.

### 4.3 + 4.5 — the first condition source and the evaluation context

Context is a dict the caller states; it is normalised (`normalise_context`) and never guessed:

```
CONTEXT_FIELDS = ('target_faction', ...)      # top level
TARGET_FIELDS  = ('faction', 'viral_stacks', 'protection', ...)   # under context['target']
ATTACK_FIELDS  = ('shot_index', ...)          # under context['attack']
```

Inputs the engine has **no model for** are named, not dropped: they come back as `context_unused`
in the evaluation block. The gate's case is a real one, not a synthetic build — a **Warframe** (an
engine with no target model) with a target faction and a stack count stated — and the assertion is
that those inputs come back named rather than disappearing behind a cheerful `context_supplied`.

Two evaluators exist, and only two:

| condition | resolved from | gates |
| --- | --- | --- |
| `target_faction` | `context.target_faction` | the faction-damage multiplier family (Bane of Grineer etc.) |
| `first_shot` | `context.attack.shot_index` | `damage_on_first_shot` mods |

Real payloads, on `Braton Prime` with `Bane Of Grineer` R5 + `Cryo Rounds` + `Infected Clip`
(the context shape below is exactly what the page posts — flat `target_faction`, nested `target`):

| what the caller states | `evaluation.state` | `target_faction` | faction mult | burst DPS | damage_to_health |
| --- | --- | --- | --- | --- | --- |
| nothing | `conditional` | `unknown` | ×1 | 1333.612 | withheld |
| `target_faction: grineer` | `conditional` | `satisfied` | ×1.55 | 2067.0986 | withheld |
| `target_faction: corpus` | `conditional` | `not_satisfied` | ×1 | 1333.612 | withheld |
| `grineer` + 6 viral stacks + health | `deterministic` | `satisfied` | ×1.55 | 2067.0986 | **403.8125** |
| `grineer` + 30 stacks (above the cap) | `conditional` | `satisfied` | ×1.55 | 2067.0986 | withheld |
| `grineer` + stacks, no landing stated | `conditional` | `satisfied` | ×1.55 | 2067.0986 | withheld |
| `strict: true`, nothing stated | **`refused`** | `unknown` | ×1 | **null** | null |
| `hypothetical: true`, nothing stated | `conditional` | `unknown` | ×1.55 | 2067.0986 | withheld |

Read the second and third rows together: stating **another** faction gives numbers *identical to
stating nothing* (×1, 1333.612) while the state says `not_satisfied` — the difference between "the
condition is false" and "we were not told" survives into the payload. `hypothetical` mode applies
the unresolved condition (×1.55) and labels itself `hypothetical: true` **while leaving the state
`unknown`** — the number is offered, the honesty is not traded for it.

`strict` is what the phase's "refusal is an answer" rule looks like in practice: the affected stats
(`damage_per_shot`, `damage_per_shot_expected_crit`, `burst_dps`, `sustained_dps`) come back `null`,
the affected mirrors (`result.dps.burst.value`, `result.dps.sustained.value`) come back `null` too,
and no trace retains a number for them. See §6 F2 — that last part was a real finding.

### 4.4 + 4.6 — the status mechanic, and the second mechanic

`builds/statuses.py` (258 lines) implements exactly one status, **Viral**, and nothing else:

```
damage_to_health = modded_damage × [2 + (0.25 × (viral_stacks − 1))]
source: https://wiki.warframe.com/w/Damage/Viral_Damage (oldid 2805913, retrieved 2026-09-29)
```

Golden values are pinned: 1 stack ×2.00, 2 ×2.25, 5 ×3.00, 6 ×3.25, 10 ×4.25 (the cap).
Outside the domain — 11+ stacks, fractional or negative or `None` or `True` or a string — it
produces **no value at all** rather than a clamped guess. A target with no stated landing
(`protection`) leaves the amplifier `unknown`; a landing the model does not cover is `unsupported`.
The check above shows the end-to-end figure: 124.25 per shot × 3.25 = **403.8125**, exactly the
engine's own arithmetic, never the page's.

The 4.6 question — *does the abstraction generalise, or does it need hard-coded plumbing?* — was
answered by building the **second** mechanic as the second evaluator (`first_shot`, resolved from
`context.attack.shot_index`, gating `damage_on_first_shot`): it went in through the same three
seams as the first (a context field, an evaluator, a stat→condition link), with no new plumbing in
the API, the page, or the refusal registry. **Redesign was not needed**; the seam held.

---

## 3. The refusal-preservation gate (`design/_planner/conditions_gate.py`)

A standalone gate (not a pytest file) that runs the engine over the **live** database and the whole
conditional corpus, then, in `--falsify` mode, monkey-patches the engine to break each rule and
checks the gate notices.

```
python design/_planner/conditions_gate.py --falsify
→ 27 checks, 0 failed.  falsification: 11 of 11 breaks caught.
```

The checks that carry the phase's guarantees:

- `states/exactly-four` — the state space is *literally* those four words, the reason-code set is
  pinned exactly, and the four are distinct from zero/false/missing/validation-failure.
- `states/reachable` — four producers × the state each must reach, requiring all four states.
- `refusal/structured` — every conditional mod refuses with a state **and** a reason code.
- `refusal/never-applied` — no conditional clause ever reaches a total.
- `refusal/checked-count` — every conditional mod this database can equip was actually exercised
  (no silent "we checked zero of them").
- `rider/never-in-totals` — a conditional rider never adds to the base stat it shares a line with.
- `unknown/withheld` + `unknown/numbers-intact` — an unresolved condition withholds, and *every*
  Phase 1 number is bit-identical to the no-mod baseline.
- `unknown/context-resolves` — and stating the input resolves it (the pipeline works, not just the
  refusal).
- `strict/no-number-survives` — a refused stat is withheld everywhere it is reported, mirrors and
  traces included.
- `hypothetical/never-invents` — hypothetical mode produces no number for an input it was not given.
- `evaluation/engine-declared` — a frame build reports `not_evaluated`; a weapon build reports that
  its engine evaluated (no borrowed vocabulary).
- `context/stated-inputs-named` + `context/used-inputs-not-flagged` — an input with no model is
  named (`context_unused`) and one the engine *did* use is not mislabelled.
- `numbers/viral-formula`, `numbers/viral-refuses`, `numbers/viral-states` — the documented formula,
  its domain, and all four states reachable through it.
- `malformed/never-crashes` — a corpus of junk (non-dict builds/options/contexts, ranks as
  strings/floats/infinities/NaN/`10**1000`, unhashable ids, junk slots) never raises.
- `registry/coverage`, `states/validation-codes-complete` — every emitted code has a registry entry
  and every emitted validation code is in `validation.CODES`.
- `page/no-maths` — no Phase 4 formula constant appears in the page (stated as a sample, not a
  proof, in the report).

Falsifications (each a deliberate break, with the gate required to catch it), the eleven the gate
ships with: a withheld condition starts contributing (`unknown-reporting-applied`); a boolean stands
in for a state (`fifth-state-false`); conditional text treated as satisfied
(`classifier-assumes-satisfied`); a stated input with no model silently ignored
(`stated-input-dropped`); a conditional rider folded into the totals (`rider-lands-in-totals`); an
unsupported stack count producing a multiplier (`viral-cap-approximated`); a refused stat keeping
its number in the mirrors (`refused-number-survives`); a hypothetical evaluation inventing an
amplifier (`hypothetical-invents`); an engine claiming it evaluated when it did not
(`evaluation-claimed`); a junk context crashing instead of answering unknown
(`malformed-context-raises`); a formula constant appearing in the page (`page-carries-formula`).
**11 breaks, 11 caught**, and each break is required to fail the *specific* check that owns it
(the report above lists which).

---

## 4. Regression coverage (the app, not just the engine)

| gate | result |
| --- | --- |
| `python -m pytest tests -q` (whole repo) | **2096 passed, 5 skipped** |
| four new Phase 4 test files (`test_condition_states.py`, `test_conditional_damage.py`, `test_viral_status.py`, `test_refusal_preservation.py`) | **130 passed** |
| `python design/_planner/conditions_gate.py --falsify` | **27 checks, 0 failed; 11/11 breaks caught** |
| `python design/_planner/build_planner_gate.py` (real browser against the live server; planner) | **PASS — 115 checks, 0 failed** |
| `python design/_stage10/gate.py` (the trader app, untouched by this phase) | **PASS — 121 checks, 0 failed, 38 page states driven** |
| `python design/_session/workflow_gate.py` (trading workflow) | **PASS — 23 of 23 checks** |
| CI `tests` workflow, clean checkout | **success** (see the head of this file) |

The planner browser gate gained Phase 4 checks: the target bar round-trips through a reload and is
posted exactly as stated, an unresolved input is withheld rather than assumed, and the evaluation
card's badge tracks the engine's state rather than the page's opinion.

---

## 5. Two CI reds that were already there

CI on `main` had been failing since the Phase 3 commits, for reasons unrelated to code correctness:
`tests/test_player_import.py` needs an ingested `data/` database that CI never builds (5 failures +
17 errors there), and `tests/test_plat_ledger.py` compared a generated timestamp against the UTC
runner's date, so it failed for ten hours a day, every day. Both are fixed in this revision (the db
fixture skips when there is no ingested database; the ledger compares against the writer's own
clock). That is why the first two commits in this revision are red and the last four are green.

---

## 6. Independent review, and what happened to each finding

Two agents were run against the finished work: an adversarial review instructed to *break* it, and
an independent verifier instructed to re-measure the report's claims with its own scripts rather
than trust the tests. Both reports are in the repo (`phase4-adversarial-review.md`,
`phase4-verification.md`). Everything below was acted on.

**F1 (HIGH) — `hypothetical` mode crashed on a viral build.** Clauses marked hypothetical
dereferenced an amplifier that an unknown viral row does not carry → `KeyError`, reachable over
HTTP and reported to the caller as a bad request body. *Fixed*: the value is read with `.get()` and
hypothetical mode applies nothing it was not given; the gate carries `hypothetical/never-invents`,
`{'hypothetical': True}` joined the malformed corpus, and a test pins it.

**F2 (HIGH, the reviewer's headline finding) — strict mode withheld the numbers in `stats` but left
the same figures live in `result.dps.*` and in the traces, and the page paints `result.dps`
directly.** So with Strict on, the evaluation card said "refused" next to a live burst figure in the
same view. *Fixed*: refusing a stat now withholds it from every documented mirror
(`MIRROR_PATHS`) and from its own trace, and the gate walks those paths
(`strict/no-number-survives`) so the hole cannot reopen. Re-proved after the fix on the real
database: `dps.burst.value` and `dps.sustained.value` null, all four refused stats null, no trace
finals.

**F3 (HIGH) — a Warframe build got an invented `evaluation` block**, so the page called a frame
build "unconditional" using the weapon engine's vocabulary. *Fixed*: an engine that reports no
evaluation gets `state: not_evaluated`, `engine_evaluated: false`; a weapon build sets it true.

**F5 — `tests/test_conditional_damage.py` leaked `WFM_BUILD_DB`**, so the four new test files failed
when run together. *Fixed* with `monkeypatch`, and the four-file line is what the report quotes.

**F6 — `import builds.validation` raised `ImportError`** (order-dependent circular import).
*Fixed*: `as_int` moved to `builds/coerce.py`, which both engines import; both import orders
verified.

**Review §6 — three weak gate checks.** `states/reached` was a tautology (it asked the engine's own
constant whether it was itself); `states/exactly-four` had lost its teeth; `page/no-maths` samples
literals. *Acted on*: the tautology became `states/reachable` (four producers × the state each must
reach); the four-state check pins the exact reason-code set again; the page check stays a sample and
the report now says so instead of implying a proof.

**Review §5 — the Conditions card never printed `unsupported_effects`; the damage-split bar
re-added the parts.** *Fixed*: the badge carries the refused-mechanic count, and the bar's
denominator is the engine's own `per_projectile_total`.

**Verification (26 claims re-measured, 8 discrepancies).** All eight were acted on, and they changed
the report's numbers rather than the code's behaviour: the conditional corpus is **426**, not 416;
the multiplier family is **421 modelled of 474 matched**, not "474 parse"; the recovered rider stat
is **11 of 430 lines**; the gate is **27 checks with 11 falsifications** (it grew twice while being
reviewed). Its malformed-input hunting found three shapes the first corpus missed — unhashable
equipment and mod keys, and a mod rank of `10**1000` — all three now refused with a validation error
instead of reaching `int()` or the capacity arithmetic.

**What the reviewer could not break** (their words, kept because it matters as much as the
findings): the page performs no Warframe arithmetic (every arithmetic site is formatting, a delta
against the engine's baseline, or a share of a bar); no conditional path reaches a number; no
harmless-looking silence remains on the compute path; and the brief's hard constraints (no
simulator, no inverse solver, no live game data, no recommendation engine, no 426-mod migration) all
hold on the delivered tree.

---

## 7. Known limitations (honest list)

1. **Two conditions and one status.** `target_faction`, `first_shot`, and viral's
   damage-to-health amplifier. Everything else in the conditional corpus (~430 lines) is refused by
   name, with a reason that says which family it belongs to.
2. **Timers, stacks and sequences are not modelled at all** — no combat timeline exists and none
   was added (a simulator is explicitly out of scope). "For 9s", "stacks up to Nx" and "on kill"
   clauses therefore stay `unsupported`, not `unknown`.
3. **No enemy model.** No armour, no health types, no damage-type resistances; the viral mechanic
   takes a `protection` string and refuses anything it does not cover, rather than approximating.
4. **`hypothetical` mode is a labelled what-if**, not a prediction: it applies unresolved
   conditions and keeps the state `unknown` next to the `hypothetical: true` flag.
5. **The corpus classifier is heuristic.** Six lines land in `unspecified` ("the engine cannot
   classify this clause yet") and are refused there rather than mis-filed — e.g. Blood Rush's
   "stacks with Combo Multiplier", which the old marker list would have called *unmodelled* rather
   than *conditional*. The refusal is still correct; the label is the honest part.
6. **`page/no-maths` samples formula constants** in the page, it does not prove their absence.
7. **A flaky browser check is documented, not hidden**: `current / cloning does not modify what the
   source said` failed once mid-revision (a cached snapshot from mid-edit code being compared against
   a fresh read) and passes on the runs either side. The check now prints which key moved.
8. **A missing engine database surfaces as a crash from the player reader**, not a named state, for
   the four reader tests that need the catalogue. In the app the database is always present; CI
   skips those tests. A named `engine_unavailable` state would be cleaner and is not in this phase.

---

## 8. Deferred to Phase 5 (deliberately)

- The remaining status mechanics (Heat, Corrosive, Slash, …) and the stacking-over-time model that
  makes them meaningful — that needs the combat timeline this phase refused to build.
- Enemy health types, armour and damage-type resistance; currently only viral's `protection` string
  is known to the engine.
- Clauses that need a target model: on-headshot, on-crit, per-status-on-target (Condition Overload
  and friends), per-unit and per-event scaling.
- A named state for "the engine's database is missing" (limitation 8).
- Any UI for choosing among evaluation modes beyond the target bar and the Strict toggle.

---

## 9. What to attack next (suggested)

1. **The state space itself**: try to make a state behave as a boolean or a number anywhere in
   engine → API → page. The gate tries this; a fresh pair of eyes should try harder.
2. **The refusal path for the ~430 unmigrated lines**: does every one of them carry a state *and* a
   reason code, and does any of them reach a total through a mirror (`dps`, `damage`, traces,
   `traces.<stat>.final`)?
3. **`hypothetical` and `strict` semantics**: is "applies it but labels it hypothetical" the right
   contract, and is `strict` withholding exactly the affected stats — no more, no less?
4. **The viral formula and its domain**: the wiki source is cited with an oldid; check the formula,
   the cap, and that a refusal never carries a value.
5. **Context normalisation**: try to make an input silently ignored, or a used input reported as
   unused; try junk shapes (nested, list, string, huge ints) at both the engine and the HTTP route.
6. **The page**: does it ever compute, infer, default, or round a Warframe number, or show a figure
   the engine refused?

---

## 10. Files to read, in this order

1. `design/build-planner/phase4-plan.md` — the plan (source of truth, unchanged by the work).
2. `design/build-planner/phase4-report.md` — the implementation report (this file is the review
   brief; that one is the full record).
3. `builds/conditions.py` — the four states, the reason codes, the two evaluators.
4. `builds/statuses.py` — the viral mechanic, its formula, its domain.
5. `builds/effects.py` — the conditional classifier and the structured refusal.
6. `builds/weapons.py` — where a condition meets a stat, and where a refusal withholds its mirrors.
7. `builds/api.py`, `server.py` — options → context threading, the evaluation block, the routes.
8. `design/_planner/conditions_gate.py` — the refusal-preservation gate and its falsifications.
9. `design/_planner/phase4-adversarial-review.md`, `phase4-verification.md` — the two independent
   reviews, including what could not be broken.
10. `static/planner.js`, `static/planner-stats.js` — the page: it states inputs and renders engine
    state; check that claim.
11. `docs/build-planner.md` — the user-facing documentation of all of the above.
12. `tests/test_condition_states.py`, `test_conditional_damage.py`, `test_viral_status.py`,
    `test_refusal_preservation.py` — the synthetic tests, including the ones that prove a refused
    modifier never becomes an unconditional one.
