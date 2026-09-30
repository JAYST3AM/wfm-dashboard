# Phase 4 — the conditional combat model

Status: **implemented and verified** (all six milestones). Written 2026-09-30 against
`design/build-planner/phase4-plan.md`, which was treated as the source of truth along with the
Phase 1–3 contracts.

The one-line version: the engine no longer treats *"I was not told"* as *"no bonus"*. Every
conditional thing ends in one of four states, the engine's refusals now say which state and why,
three real mechanics were added (two conditions and one status), and the gate that guards it has
been proven to catch eleven deliberate breaks.

---

## 1. What changed, by milestone

### 4.1 — Formalize condition states (`builds/conditions.py`, new)

`satisfied` / `not_satisfied` / `unknown` / `unsupported`, with a stated meaning for each:

| state | means | contributes |
|---|---|---|
| `satisfied` | the condition holds for this evaluation | the contribution may be applied |
| `not_satisfied` | known false | no — a *reported zero*, a result and not a default |
| `unknown` | resolvable in kind, but the context does not carry the input | no — withheld; the missing input is named |
| `unsupported` | the mechanic has no model at all | no — refused with its named reason |

* None of the four is `0`, `False`, `''`, `None` or a missing key. `result()` **raises** on a
  state outside the four (`ValueError`), and there is deliberately no `truthy()` anywhere in the
  module: a caller that wants a number must read the state and decide, which is what forces the
  refusal to surface.
* Missing input is `unknown` and names what it needs (`missing: ['target_faction']`), so it can
  never be read as "false". A build with a faction mod and no target stated is *valid* — no
  validation code, no warning — and its answer is *conditional*.
* The four states are disjoint from the validation vocabulary (`builds/validation.py`), and the
  gate pins that.

### 4.2 — Structured conditional refusals (`builds/effects.py`)

* All **426** conditional mods in the current database still refuse, with the same
  `conditional_effect` code every consumer already handles.
* Each refusal now carries a `condition` block: the clause it recognised
  (`on_kill`, `on_hit`, `on_reload`, `on_headshot`, `on_crit`, `on_slam`, `on_move`,
  `target_status`, `stacks`, `per_unit`, `per_event`, `state_clause`, `sequence_clause`, `timer`,
  `unspecified`), its state, its reason code, and — where the cleaned line parses to one — the
  canonical stat the rider would have moved. That last part is honest but thinner than it sounds:
  only 11 of the 430 stored conditional lines re-parse to a modelled stat (the conditional-only
  family) and the other 419 carry `stat: null`. An independent verification pass measured that and
  is quoted in `design/_planner/phase4-verification.md`; the state and the reason code are there
  for every one of the 426 mods.
* The four refusal *reasons* are all expressible and distinguishable:
  `condition_unknown`, `condition_not_satisfied`, `condition_effect_unimplemented`,
  `mechanic_unsupported`.
* **Not implemented, on purpose:** the other 426. This is a refusal model, not a combat model.

### 4.3 — The first condition source: `target_faction`

* `context.target_faction` → `satisfied` (the bonus applies, traced), `not_satisfied` (the wrong
  faction: a reported ×1), `unknown` (no faction stated: withheld, and *listed*), `unsupported`
  (a clause with no model — reachable through the same pipeline from the corpus classifier).
* The Phase 1 spelling `options.faction` still works and produces the identical answer; an
  explicit `context.target_faction` wins.
* **This uncovered a real defect.** The whole faction family ships as a *multiplier*
  (`x1.05 Damage to Grineer` … `x1.55`), not a percentage, so `MULTIPLIER_RE`-less parsing filed
  it as an unmodelled stat — which meant the engine's `faction_multiplier` could never leave
  `1.0`, and "faction damage" had been silently absent. 474 corpus lines now match the multiplier
  form and **421 of them become modelled faction stats** (`faction_corpus` 95, `faction_grineer`
  95, `faction_infested` 95, `faction_corrupted` 68, `faction_murmur` 68); the remaining 53 stay
  unmodelled and refused — railjack turret lines, `Max Shield Capacity` and friends. Bane of
  Grineer R5 against Grineer is now ×1.30, and the `notes` still say the multiplier is not part of
  the arsenal total (wiki). The Sacrificial set's plural ("x1.10 Damage to Sentients") is mapped to
  the same `faction_sentient` stat for the same reason: same faction, same separate multiplier.

### 4.4 — The first status mechanic: viral amplification (`builds/statuses.py`, new)

Exactly one piece of one status effect:

```
damage_to_health = modded_damage x [2 + (0.25 x (viral_stacks - 1))]
```

* Source: [wiki.warframe.com/w/Damage/Viral_Damage](https://wiki.warframe.com/w/Damage/Viral_Damage)
  (oldid 2805913, retrieved 2026-09-29). Documented inputs: `target.viral_stacks` (0–10) and
  `target.protection` (health / armour / shields / overguard). Documented output: the multiplier
  and the amplified damage, both traced, and never folded into a Phase 1 stat.
* Golden values: 1 → ×2.00 (+100%), 5 → ×3.00, 6 → ×3.25, 10 → ×4.25 (+325%, the wiki's cap).
* States: **satisfied** (procs on a target whose damage lands on health or health-under-armour);
  **not_satisfied** — a reported ×1 — for no procs, and for shields/overguard, which the wiki says
  the amplification does not reach; **unknown** for no stack count, no landing, or a non-integer
  count; **unsupported** for stacks above the cap (the wiki describes stack replacement over time,
  which is a combat timeline this engine does not model), an immune target (the Deimos special
  case), or a landing word it does not know. A refusal carries no `amplifier` key at all.

### 4.5 — Conditional damage evaluation

* `result.evaluation` names the mode (`stated_inputs` / `strict` / `hypothetical`) and the kind of
  answer: **deterministic** (every condition bearing on the numbers was satisfied by the stated
  inputs), **conditional** (something bearing on them is unresolved: the numbers are the
  stated-inputs answer, with the withheld contributions listed in `evaluation.withheld`), or
  **refused** (strict mode: the affected stats are withheld entirely and named in
  `evaluation.refused_stats`, with a registered `calculation_refused` marker in the registry).
* `result.conditions` carries every condition row; `api.compute` surfaces `conditions` and
  `evaluation` at the top level so the page reads them without walking into the engine result.
* `evaluation.unsupported_effects` counts the refused *mechanics* (from the registry's own marker
  map), so "what was evaluated" and "what could not be modelled" are two stated facts rather than
  one inferred from the other.
* **Phase 1/3 numbers do not move.** A context with no bearing on the build leaves every stat
  identical; an unresolved faction bonus leaves `burst_dps` exactly where the unmodded build had
  it, and the viral damage figures live in their own keys. `damage_on_first_shot` is the one
  behaviour that changed *on purpose*, and only when the new mechanic applies (below).

### 4.6 — The second mechanic, and the refusal-preservation gate

* `first_shot` — `damage on first shot in magazine`, chosen because its input comes from the
  *attack* rather than the target, which is what tests whether the abstraction generalises. Until
  Phase 4 that stat was collected and then silently ignored: it is now applied on shot 1 (Charged
  Chamber R3 → +40%: `modded_base_damage` 35 → 49), a reported zero on shot 3, and withheld when
  the shot number was never stated. No new ideas were needed — the same state space, the same
  `result()` shape, the same trace plumbing.
* **The gate: `design/_planner/conditions_gate.py`** — 27 checks, run against the real ingested
  database, plus `--falsify`, which installs eleven deliberate defects and requires each one to be
  caught. See §3 for the results.

### The one thing asked for that changed a page *and* an engine rule

The browser gate also found a persistence bug that had nothing to do with conditions: the planner
debounces its `localStorage` write, so any navigation inside that window silently dropped the
user's last edit (the gate's own clone step was lost exactly this way). Pending writes are now
flushed on `pagehide`/`beforeunload`/`visibilitychange`, and the Phase 4 target block is in the
document validator, so what a caller states survives a reload instead of being validated away.
An input's value is a string in the DOM and a number in the document: the page coerces counts on
the way in (the engine refuses `"6"` where it wants `6`, which is the correct behaviour and was
worth hitting).

`malformed input must not crash the engine` was not true when this phase started. The audit
(`design/_planner/phase4-audit-refusal-path.md` §4/§2) predicted two crash classes and both were
reproduced:

* a build that is not an object (`'x'`) → `AttributeError` out of `validation.resolve_equipment`;
* a rank of `1e400` or `'abc'` → `OverflowError`/`ValueError` out of `int()`, which the planner
  route turned into **HTTP 500**.

Both are fixed (`validation.as_build`, `validation.as_int` with `invalid_mastery_rank` as a peer of
`invalid_equipment_rank`), and all of those shapes are now in the gate's malformed corpus.

---

## 2. The contracts Phase 4 kept

* **The engine owns every calculated number.** The page gained *inputs* (a target group) and
  *rendering* (a Conditions card); it gained no formulas. The gate fails if a Phase 4 formula
  constant appears anywhere in `static/`.
* **Refusals are valid answers.** A conditional answer is `ok: true` with a `conditional` state —
  never `#plError`, never a fabricated number.
* **Validation/refusal codes survive API → UI.** `conditions` and `evaluation` ride at the top
  level of the answer; the page prints the engine's own state words and reason text.
* **Malformed input must not crash.** Covered by the gate's malformed corpus (contexts, options,
  builds, ranks) and by `tests/test_conditional_damage.py`.
* **No regression.** The full suite, the planner browser gate and the refusal gate are all run
  below.

---

## 3. Results (exact, from the runs on this machine)

```
python builds/ingest.py
  1809 mods (1014 carry stats we do not model, 426 carry conditional effects; the buckets overlap -
  415 mods are in both, because a conditional line that also fails to parse is counted in each, so
  1025 mods carry something the engine refuses: 599 only unmodelled, 11 only conditional)
  content hash fd1b15dd2e06bfee7587618a26e326fcd6fd536ea42ad8b56762e0fa8f41f7a7

python design/_planner/conditions_gate.py --falsify
  GATE PASS - 27 checks, 0 failed
  falsification: 11 of 11 breaks caught
  report: design/_planner/conditions-gate-report.md

python -m pytest tests/test_condition_states.py tests/test_conditional_damage.py \
                 tests/test_viral_status.py tests/test_builds_engine.py -q
  120 passed

python -m pytest tests/test_refusal_preservation.py -q
  5 passed

python design/_planner/build_planner_gate.py
  PASS - 115 checks, 0 failed (report: design/_planner/build-planner-report.md)

python design/_stage10/gate.py            GATE PASS - 0 of 121 checks failed, 38 page states driven
                                          (the trader app, run because the shared server and the
                                           planner page were touched)
python design/_session/workflow_gate.py   WORKFLOW PASS - 23 of 23 checks

python -m pytest tests -q
  2096 passed, 5 skipped in 138.93s
  (the phase's own four files together, in one command: 97 passed - the line that failed before F5
   fixed the leaked WFM_BUILD_DB environment variable)

GitHub Actions `tests` (ubuntu-latest, clean checkout, no `data/`):
  success - run 36662442760 on d5a1e70, every step green. The first green run on `main` in three
  days, because two pre-existing reds are fixed in the same revision (see "Two reds that were there
  before this phase").

The page contract, end to end (from the browser gate): nothing stated posts no context at all, a
stated faction and stack count survive a reload, the request carries exactly what was stated, and
viral stacks stated without a landing come back `unknown` (withheld `['viral']`, badge
"conditional · 1 condition").
```

The browser gate (115 checks) additionally proves the page contract end to end: nothing stated
posts no context at all, a stated faction and stack count survive a reload, the request carries
exactly what was stated, an unresolved input comes back withheld with no invented number, and the
Conditions card prints the engine's own words. Two more of its checks were updated rather than
weakened: the diagnostics strip is now four sections (validation, capacity, evaluation,
unsupported, in that order, each with its own badge).

The gate's checks, in order (27): state vocabulary pinned to exactly four words (and the four
condition refusals pinned by name); corpus count; every
conditional mod refuses with a state and a reason code; no conditional clause is ever applied;
every equippable conditional mod was actually checked; a conditional line never adds to the totals
measured stat by stat; an unresolved faction bonus is withheld with the numbers intact and
resolves when the target is stated; the viral mechanic produces the documented numbers, refuses
outside its domain and reaches all four states; unsupported inputs never produce numbers;
unmodelled stats are named; malformed input never crashes; every emitted refusal has a registry
row; strict mode withholds; a stated input with no model is refused by name while an input the engine
did use is not; the page carries no formula.

The six falsifications, and what caught each:

| deliberate break | caught by |
|---|---|
| `unknown` conditions report themselves as applied | `unknown/withheld`, `unknown/numbers-intact`, `malformed/never-crashes` |
| a fifth state `'false'` is added to the state space | `states/exactly-four`, `numbers/viral-states` |
| the text classifier claims a clause is satisfied | `refusal/never-applied` |
| the viral multiplier is replaced by a plausible-looking number | `numbers/viral-formula`, `numbers/viral-refuses` |
| a malformed context raises instead of degrading to `unknown` | `malformed/never-crashes` |
| a formula constant appears in the page | `page/no-maths` |
| a stated input the engine cannot use stops being reported | `context/stated-inputs-named` |

---

### Found in self-review, after the milestones were green

A stated input that no engine can use was silently dropped: a target context on a warframe build
came back as `context_supplied: true` and nothing else. That is the same failure the phase exists
to stop, one layer out, so it is now refused by name — the engine reports what it `consumed`, and
anything left over becomes a registered `context_unused` marker plus `evaluation.unused`, with the
page showing "not modelled here: target.immune_to". The gate's two new checks pin both halves of
that rule (an unused input is named; a used one is not), and the seventh falsification proves the
check bites.

## 4. Known limitations

* **The condition corpus is recognised, not modelled.** 426 mods carry conditional lines; the
  engine resolves conditions for two of them (`target_faction`, `first_shot`) plus the viral
  mechanic. Everything else refuses with a named clause and state.
* **Condition detection is marker-based and incomplete.** The audit found three families that
  dodged every marker (`stacks with`, `consecutive`, `for every`) and landed in the *unmodelled*
  bucket, where a refusal could not say it was conditional. Those markers were added (416 → 426
  conditional mods), but the vocabulary is still a heuristic: a novel phrasing will land as
  unmodelled rather than conditional. Both are refusals, so no number is faked — but the *reason*
  a reader sees would be the less precise one.
* **`strict` and `hypothetical` are API-only.** The page states inputs and renders states; it does
  not yet offer a mode switch, so the two evaluator modes are exercised by tests and the CLI.
* **A conditional *effect* is still `application`, not arithmetic.** `condition_effect_unimplemented`
  exists as a reason code, but no mod in the corpus reaches it yet: the clauses the classifier
  knows are all mechanics the engine cannot compute. It is the path a Phase 5 conditional mod
  would take.
* **`orokin`/`exilus_unlocked` remain truthiness-coerced.** `bool('yes')` is accepted without a
  warning (found by the audit, not a crash). Deliberately left alone this phase: it is a
  validation-strictness change, and Phase 4's mandate was crash-safety plus conditions.
* **Viral is one piece of one status.** Stacking *over time*, the 6-second window, Heat/Slash/
  Corrosive/Magnetic, enemy health-type modifiers and armour stripping are all still refused.

## Two reds that were there before this phase, and are not any more

CI on `main` had been failing since the Phase 3 commits (`b6cb0c3`, `829e2083`), for reasons that had
nothing to do with a code path — the runner has no ingested database, so

* `tests/test_player_import.py` raised `FileNotFoundError: no build database at
  .../data/build_data.json` in **5 tests and 17 errors**, and
* `tests/test_plat_ledger.py::test_main_writes_the_plat_ledger_contract` compared the ledger's
  `generated` stamp against `time.strftime` in the *runner's* zone while the writer stamps Melbourne
  time, so for ten hours of every UTC day the two dates differ by one and the assertion failed.

Both are fixed in this revision: the database-dependent tests skip when the ingest is absent and run
in full where it is (verified both ways — 2096 passed / 5 skipped locally, 21 passed vs 21 skipped in
the import module alone, and the runner green), and the ledger test compares against the writer's own
clock. This is not Phase 4 work; it is what "the tests pass" has to mean before a phase can claim it.

## 5. Deferred to Phase 5 (deliberately)

* A simulator-free **stack/uptime model** for conditional buffs (the honest version of
  "On Kill: +2.7% for 20s, stacks 5x"): expected uptime as an explicit, stated input rather than a
  guessed one.
* **Conditional effects that can actually be applied** — the `condition_effect_unimplemented`
  path: a clause whose state is known and whose effect the engine can compute (the first candidate
  is a weapon or frame stat rider with a stated context).
* **Enemy model** (armour, health types, damage-type modifiers) — the thing viral amplification
  currently stops short of, and the prerequisite for most status mechanics being useful.
* **Riven/set-bonus conditions**, Incarnon evolutions, Helminth, Archon Shards.
* **The remaining status mechanics**, one at a time, each with its own documented formula and
  refusal cases, as this phase did for viral.
* **A page mode switch** for `strict`/`hypothetical`, letting a reader ask "what would this be if
  the condition held?" without leaving the planner.
* **Validation strictness for coerced booleans** (`orokin: 'yes'`), with a warning code.
---

## Independent review: what it found, and what happened to each finding

The phase brief asked for an independent adversarial review after implementation, and for
falsification tests that prove the gates catch breakage. Both were run against this work, and both
changed it. Their reports are in the repo next to this one.

### `design/_planner/phase4-adversarial-review.md`

| finding | disposition |
| --- | --- |
| **F1 — `hypothetical` mode crashed the engine on a viral build** (`KeyError: amplifier`, reachable over HTTP and reported to the caller as a bad body) | **Fixed.** The viral row's number is read with `.get()` and a hypothetical evaluation applies nothing it was not given. The gate now carries a `hypothetical/never-invents` check, `{'hypothetical': True}` joined the malformed corpus, and `tests/test_conditional_damage.py` pins it. |
| **F2 — strict mode nulled `stats` but left the same numbers in `dps`, `damage` and the traces, so the page printed a refused figure** | **Fixed.** Refusing a stat now withholds it from every mirror (`MIRROR_PATHS`) and from its own trace, and the gate walks those paths (`strict/no-number-survives`) so the hole cannot reopen. |
| **F3 — a Warframe build's `evaluation` block was invented by `api.compute`, and the page called it unconditional** | **Fixed.** An engine that reports no evaluation gets `state: not_evaluated` and `engine_evaluated: false`; a weapon build sets the flag true. Pinned by `evaluation/engine-declared` and by a test. |
| **F5 — `tests/test_conditional_damage.py` leaked `WFM_BUILD_DB`, so the four new test files failed when run together** | **Fixed.** The env var is patched with `monkeypatch`, and the Results section above quotes the four-file line, which is what the report should have quoted. |
| **F6 — `import builds.validation` raised ImportError (order-dependent circular import)** | **Fixed.** `as_int` moved to `builds/coerce.py`, which both engines import; both import orders now work, verified directly. |
| **§6 — `states/reached` was a tautology; `states/exactly-four` had lost its teeth; `page/no-maths` samples four literals** | **Acted on.** `states/reached` became `states/reachable`, a table of four producers × the state each must reach, requiring all four states; the four-state check pins the exact reason-code set again, with `context_unused` named as the only extra; the page check still samples literals and the report says so rather than implying a proof. |
| **§6 — a missing `strict/no-number-survives` and a frame/`evaluation` check** | **Both added** (they are the checks F2 and F3 earned). |
| **§5 — the Conditions card never printed `unsupported_effects`; the damage-split bar re-added the parts** | **Acted on.** The badge carries the refused-mechanic count, and the bar's denominator is the engine's own `per_projectile_total`. |

The review also recorded what it *could not* break: the page performs no Warframe arithmetic (every
arithmetic site is formatting, a delta against the engine's baseline, or a share of a bar), no
harmless-looking silence remains on the compute path, and the plan's hard constraints (no
simulator, no inverse solver, no live game data, no recommendation engine, no 426-mod migration)
all hold on the delivered tree.

### `design/_planner/phase4-verification.md`

An independent pass over the report's own claims. Eight claims were checked against re-measurement;
the discrepancies it raised were all acted on, which is why some numbers in this file differ from
the first draft: the conditional corpus is 426 (not 416), the multiplier family is 421 modelled of
474 matched (not "474 parse"), the recovered rider stat is 11 of 430 lines (not "recovered by
re-parsing" for all), and the gate is 27 checks with 11 falsifications (it grew twice while being
reviewed). Its own crash-hunting found three malformed shapes the first corpus missed —
unhashable equipment and mod keys, and a mod rank of `10**1000` — all three now refused with a
validation error instead of reaching `int()` or the capacity arithmetic, and all three are in the
gate's corpus.
