# Phase 4 — adversarial review

**Audit window:** 2026-09-30 12:08–12:36 (AUS Eastern). **Verdict: the model is real and the
refusal machinery holds where I tried hardest to break it — the corpus never reaches a total, no
state is ever read as a boolean, and a 2,057-build sweep against `b6cb0c3` (Phase 3) found zero
moved numbers. But five things are broken, and two of them break the phase's own governing rule in
code that ships to the page:** a documented evaluation mode crashes the engine (`hypothetical` + a
viral build), strict mode nulls the stat and then hands the same number to the UI through
`result.dps` and the traces, the Warframe path gets an `evaluation` block that `api.compute`
*invents* (`state: deterministic`, `withheld: []`, `conditions: []`) while the engine has refused a
conditional effect, `import builds.validation` now raises `ImportError`, and the four new test files
fail when run together in the documented order. The headline number the report quotes (21 gate
checks) is also stale — the gate is 24 checks as of 12:35, it was red at 12:26 and again at 12:34,
and its own totals guard had never measured anything until a guard added during this audit exposed it
(§6).

**Two disclosures first, because this audit could not be done without them.**

1. **The tree changed underneath the audit, repeatedly.** `builds/conditions.py` was rewritten at
   12:25:35 and 12:27:03, `builds/unsupported.py` at 12:26:08, `design/_planner/conditions_gate.py`
   four times, `builds/api.py` and `builds/weapons.py` at 12:25. Everything below was **re-verified
   at 12:35:57–12:35:59** against this exact byte set (which is also the last state I observed, with the
   gate green again — see §6):

   ```
   $ sha256sum builds/weapons.py builds/api.py builds/warframes.py builds/statuses.py \
               builds/conditions.py builds/validation.py builds/capacity.py \
               static/planner-stats.js static/planner.js design/_planner/conditions_gate.py
   00585f3579e93bef291d6c7d7b22132cd40b9da25f3240a0a54c6364553dbc17 *builds/weapons.py
   7f4fbdda5e4e42ccbade276cf7b5a638a8b8c4ea6580c278a9b4f56a1618c2c4 *builds/api.py
   3861171a23acbddb882a7b98c07c8476ff549343def114986fb53ebd4425fef4 *builds/warframes.py
   60f2748c4c0ffca6af9c276cece17b388eeb23d6fee47acfa1933351dc14f565 *builds/statuses.py
   eb18a6e44ca2e6aa595c32e59b922cd3da66b3c81692c9ae20c6a827feb2df26 *builds/conditions.py
   8a8a87f21d0aa3e5d8af2b2c279072cbdead92a82d16c62f6973fa7fcbe0d366 *builds/validation.py
   d57b2a6065fa930d499089a7c970a77e187031fefc5c6457e962eca5a82ba41a *builds/capacity.py
   1629b8111b83a391bb093b76eae3b9087b3192e0d8bb00350bf5c9f66afc4f59 *static/planner-stats.js
   7ab710a21d98080c78e19e830cf8f475b9bb9b1eb0b59695757187f194b50ea8 *static/planner.js
   c970b6747980045cb5caae4578ae7d98107fce8fa1177805f66c0539ea0fb8f8 *design/_planner/conditions_gate.py
   ```
   A defect that is not in this list may have been fixed after it; a defect that is, was
   reproducible at 12:35:59. I have said which is which per finding, and where a claim was true at
   one moment and false a minute later I have said both (the gate itself went pass → fail → pass
   across 12:29, 12:34 and 12:35).
2. **Running the repo's own gate writes to the repo.** `python design/_planner/conditions_gate.py`
   rewrites `design/_planner/conditions-gate-report.md` (I ran it twice, as the task brief told me
   to, so that file's current contents are from my runs). I deliberately did **not** run
   `design/_planner/build_planner_gate.py`, because it rewrites `build-planner-report.md` and
   `build-planner-raw.json` as well and takes minutes; **its "115 checks, 0 failed" claim is
   therefore unverified by me**, and so is the report's §3 line for it. No other file was touched.

---

## 1. Silent-unconditional paths (a conditional or unmodelled effect reaching a number)

**Verdict: the totals are clean — this is the strongest part of the implementation — but the
payload the page reads is not.**

* **COULD NOT BREAK — `collect_mod_effects` never lets a conditional rider into `totals`.**
  `builds/effects.py:443-462` sends every conditional line to an `unsupported_marker` and never to
  `totals`; only `rank_table` entries (non-conditional, modelled) are summed at
  `builds/effects.py:432-442`. Evidence — I re-implemented the gate's own `rider/never-in-totals`
  attack independently, over the whole corpus:

  ```
  $ python - <<'PY'
  # every conditional mod whose rider names a canonical stat: equip it, sum its effects,
  # compare the total for that stat with the rank_table value the rider shares
  ...
  PY
  PASS  rider/never-in-totals   a conditional line never adds to the totals, measured stat by stat
  ```
  (from `python design/_planner/conditions_gate.py`, 12:35:57: `GATE PASS - 24 checks, 0 failed`;
  note the check's own history in §6 — it was measuring nothing before this audit window).

* **MEDIUM — the only modelled-but-conditional line family in the corpus is `damage_on_first_shot`,
  and it is now state-gated; but the *detector* that put it there is still word-based, and the
  report describes the residual risk backwards.** `builds/effects.py:110-115` (`is_conditional`)
  matches only `HARD_MARKERS` + `for Ns`. A line whose condition is phrased outside that list **and
  names a modelled stat** does not become "unmodelled" — it becomes an unconditional contribution.
  `damage_on_first_shot` was exactly that case (Phase 4 fixed that one in `builds/weapons.py:143-150`).
  A scan of the ingested corpus for modelled, non-conditional lines carrying a conditional word
  returns 25 lines over 3 mods, all of them the Charged Chamber family, all of them now covered:

  ```
  Charged Chamber              Sniper     damage_on_first_shot   +10% Damage on first shot in Magazine
  Primed Chamber               Sniper     damage_on_first_shot   +25% Damage on first shot in Magazine
  Primed Charged Chamber       Sniper     damage_on_first_shot   +10% Damage on first shot in Magazine
  3 distinct mod/stat pairs
  ```
  So today there is no second instance. The point stands for Phase 5: §4 of the report says a novel
  phrasing "will land as unmodelled rather than conditional" — for a phrasing that names a modelled
  stat that is false, and the failure mode is a silently applied bonus, not a refusal.
  *Smallest fix:* in `effects.parse_stat_line`, when a line contains any of
  `('first shot', 'on the next', 'at max', 'per ')` and parses to a modelled stat, mark it
  `conditional=True` unless an explicit `schema.UNCONDITIONAL_EXCEPTIONS` entry allows it — or add a
  gate check that every modelled `damage_on_first_shot`-style stat is behind a condition.

* **MEDIUM — the Warframe engine produces a refusal with no condition row, and `api.compute` then
  fabricates a `deterministic` evaluation on top of it.** `builds/warframes.py:184-192` returns
  `equipment/stats/traces/unsupported/notes` and **no `conditions` and no `evaluation`**.
  `builds/api.py:109-112` then substitutes a literal default:
  `{'mode': 'stated_inputs', 'state': 'deterministic', ... 'withheld': []}`. See §2 for the
  reproduction. This is the same finding as §2 F3, listed here because it is the one place a
  conditional mechanic is present in a payload with no state next to it.
  *Smallest fix:* give `warframes.calculate` the same two keys (an empty `conditions` list and an
  evaluation block whose `state` is `'conditional'`/`'refused'` whenever `unsupported` carries a
  `conditional_effect` marker), and delete the default in `api.compute` so a missing block is a
  loud `KeyError` in tests rather than an invented answer.

* **LOW — `evaluation.withheld` on the Warframe path is `[]` by construction, and on the weapon path
  `unsupported_effects` counts markers that are not mechanics.**
  `builds/weapons.py:502-503` counts every marker whose code is in `unsupported.MARKER_TO_KEY`,
  which includes `context_unused`, `innate_secondary_element`, `weapon_traits` and
  `calculation_refused` — not "the refused mechanics" as §4.5 of the report says.
  *Smallest fix:* count only `conditional_effect` + `unmodelled_effect`, or rename the key to
  `refusal_markers`.

* **LOW — `server.py:1488-1506` silently drops the conditional rider lines from the mod card text.**
  It builds `refused = {normalise(t) for t in effects['conditional']}` and filters those lines out of
  the card. The refusal itself survives (it is in `unsupported`), so no number is invented; but a mod
  whose only line is conditional renders as an empty card with no hint that anything was removed.
  *Smallest fix:* render `+ <n> line(s) refused — see Unsupported` instead of dropping them.

## 2. State integrity (can a state be read as a boolean/number, or two states folded?)

**HIGH — F1: `hypothetical` mode crashes the engine on a viral build (`builds/weapons.py:390`).**
`condition_applies()` (`builds/weapons.py:96-105`) returns `True` for a `hypothetical` row in state
`UNKNOWN`, which is correct; but the viral result's `amplifier` key **does not exist** when the
state is `UNKNOWN` (`builds/statuses.py:31-39`, `136-164` — "a refusal carries no number at all"),
and the branch below it dereferences it unconditionally:

```
$ python probe_all.py     # against the 12:33 byte set
--- F1: hypothetical mode on a viral build with no target state ---
   CRASH KeyError: 'amplifier'
   trace_mod.finish(t_viral, viral_row['amplifier']) | ~~~~~~~~~^^^^^^^^^^^^^ | KeyError: 'amplifier'
   same build, same mode, via planner_compute (the HTTP route):
   route raised KeyError: 'amplifier'
```
Build: Soma Prime + Cryo Rounds R5 + Infected Clip R5 (viral), `options={'hypothetical': True}`, no
context. Reachable over HTTP: `server.py:1662-1675` forwards the caller's `options` verbatim to
`api.compute`, and `server.py:2003-2006` turns the resulting `KeyError` into
**HTTP 400 `the engine could not read this body: 'amplifier'`** — the body was fine; the engine has a
bug, and the operator is told the opposite. It is not reachable from the page (nothing in
`static/planner.js` sends `hypothetical`), and it is not covered by anything:
`BAD_OPTIONS` (`conditions_gate.py:39`) has no `{'hypothetical': True}`, the one gate call that does
pass it (`conditions_gate.py:505`) uses an unmodded weapon with no viral damage, and
`tests/test_conditional_damage.py:144` exercises `hypothetical` only with a *faction* mod.
*Smallest fix:* in `weapons.py`, use `viral_row.get('amplifier')` and skip both stats and both
traces when it is `None` — and add `{'hypothetical': True}` to `BAD_OPTIONS` and to the malformed
corpus **with a viral build**.

**HIGH — F2: strict mode nulls the stats and then hands the same numbers to the page.** When a
strict evaluation refuses, `builds/weapons.py:481-487` sets `stats[key] = None` for the six refused
keys — but leaves `result.dps.*`, `result.damage.*` and `traces[*].final` untouched, and the page
reads `out.result.dps` directly (`static/planner-stats.js:397-407`):

```
$ python probe_all.py
--- F2: strict refusal nulls stats but leaves result.dps / traces ---
   evaluation.state: refused | refused_stats: ['damage_per_shot', 'damage_per_shot_expected_crit',
       'burst_dps', 'sustained_dps', 'damage_to_health', 'damage_to_health_expected_crit']
   stats.burst_dps=None stats.sustained_dps=None stats.damage_to_health=None
   result.dps.burst.value=806.4 result.dps.sustained.value=658.2857 traces.damage_to_health.final=109.2
```
So with the page's own Strict toggle on (`static/planner.js:497`), the stats table prints `—` for
Burst DPS, the Evaluation card prints `refused under strict evaluation: … burst_dps …`, and the
damage card underneath prints **`burst 806.4`**. That is a number the engine refused, on screen, in
the same view, in the same session. This is the finding I would fix first: it breaks the governing
rule directly.
*Smallest fix:* when a stat is added to `refused_stats`, set the same value to `None` everywhere it
is mirrored (`dps.burst.value`, `dps.sustained.value`, `damage.per_shot_total`,
`damage.modded_base_damage`, `traces[key].final`) — or gate every renderer on
`evaluation.refused_stats` and add a gate check (`strict/no-number-survives`) that walks the whole
payload for a refused stat's number.

**HIGH — F3: a Warframe build's top-level `evaluation`/`conditions` are invented by `api.compute`,
and the page then says "every number here is unconditional".**

```
$ python probe_all.py
--- F3: a Warframe build carrying a conditional mod ---
   frame: Ash + Accumulating Whipclaw
   top-level evaluation: {"mode": "stated_inputs", "state": "deterministic", "context_supplied": false,
                          "context_ignored": [], "withheld": [], "refused_stats": []}
   top-level conditions  : []
   conditional markers   : [('conditional_effect', 'sequence_clause', 'unsupported')]
```
Evidence chain: `builds/warframes.py:184-192` (no `conditions`/`evaluation`) →
`builds/api.py:109-112` (the literal default) → `builds/api.py:138` (`'conditions': []`) →
`static/planner.js:1297` hides the evaluation chip when the state is `deterministic` and
`static/planner.js:1321-1322` prints **"every number here is unconditional"**. The engine has, in the
same payload, refused a conditional effect. `unsupported_effects` is not even present as a key, so
`planner.js` has nothing to fall back on (it never reads it — see §5).
Note the weapon path *does* have the block; the frame path is the hole, and the frame path is the
one Phase 3's imported loadout uses.
*Smallest fix:* `warframes.calculate` returns `'conditions': []` and an `evaluation` whose `state`
is `'conditional'` when any `conditional_effect` marker is present, `'deterministic'` otherwise; and
make `api.compute` not default a missing block (see §1).

**MEDIUM — F4: `state: deterministic` and `withheld: ['target_faction']` in the same payload.**
`builds/weapons.py:499` defines `withheld` as *every* row `not condition_applies(r)`, which includes
`not_satisfied` — a *resolved* condition whose contribution is a reported zero, which the plan and
`builds/conditions.py:126-132` both say is an answer and not a hole:

```
$ python probe_all.py
--- F4: deterministic + withheld at the same time ---
   wrong faction stated     state=deterministic withheld=['target_faction'] conditions=[('target_faction', 'not_satisfied')]
   viral lands on shields   state=deterministic withheld=['viral']           conditions=[('viral', 'not_satisfied')]
```
The page prints the withheld list next to the state (~`planner.js:1299-1300`), so a reader is told
a resolved condition was withheld. And `tests/test_condition_states.py:135` pins
`withheld == ['target_faction']` for the `unknown` case only, so nothing catches the conflation.
*Smallest fix:* `'withheld': [r['condition'] for r in condition_rows if conditions.is_refusal(r)]`,
and add a gate check that `state == 'deterministic'` implies `withheld == []`.

**MEDIUM — two states are folded into one marker text and one refusal name.** `builds/weapons.py:477`
treats `UNKNOWN` and `UNSUPPORTED` identically for `refused_stats` and emits one
`calculation_refused` marker per blocked row; `unsupported.REGISTRY['conditional_calculations']`
(`builds/unsupported.py:136-141`) then describes both as "a condition this engine can resolve …
was not stated", which is wrong for an `unsupported` row (there is nothing to state).
*Smallest fix:* emit `calculation_refused` only for `unknown` rows and `mechanic_refused` (or reuse
`conditional_effect`) for `unsupported` rows.

**LOW — a state that is not one of the three named words is described as "holds here".**
`static/planner.js:1327-1332` chains `unknown / unsupported / not_satisfied` and falls through to
`'holds here'`. The raw state word is still printed verbatim on the row (`planner.js:1332`), so the
exposure is the tooltip only — but a future fifth state, or a typo, would be rendered as a satisfied
condition in the one place a hover is read.
*Smallest fix:* default the tooltip to `'state: ' + row.state` and only use the friendly strings for
the four known words.

**LOW — `builds/weapons.py:500-501` has the key `'consumed'` twice in one dict literal.**
Python keeps the last; `json.dumps` of the answer is unaffected. It is dead code in the exact block
the report points at as the new evaluation contract, and it is the kind of duplicate that hides a
real merge mistake.
*Smallest fix:* delete line 501.

**What I could NOT break here:** no state is compared with `== True`, `bool(state)`, or
`in (False, 0)` anywhere in `builds/`, `server.py` or `static/`. The only `bool(...)` near a state is
`builds/weapons.py:105` on `row.get('hypothetical')` (a boolean field, not a state).
`conditions.result` raises `ValueError` for anything outside the four words
(`builds/conditions.py:96-97`) and the four words are disjoint from the validation vocabulary — both
by direct test.

## 3. Regression (did any Phase 1–3 number move?)

**COULD NOT BREAK — a 2,057-build sweep against Phase 3 found zero moved numbers.** Phase 4 is
uncommitted, so `b6cb0c3` *is* Phase 3. I extracted it with `git archive HEAD` into a scratch tree,
pointed both trees at the same ingested database, and computed every equipment baseline plus every
mod equipped alone on equipment that can hold it, with no options at all (the "no conditional
context" case):

```
$ python sweep.py <head> sweep_head.json   # Phase 3 tree
wrote sweep_head.json 2057 entries
$ python sweep.py <worktree> sweep_now.json
wrote sweep_now.json 2057 entries
$ python - <<'PY'  # diff every stat key of every entry, plus the marker-code set
entries compared: 2057
ok-flag changes: 0
STAT VALUE CHANGES: 0
marker-code changes: 0
PY
```
The same sweep also shows no mod changed *class*: the set of `unsupported` marker codes per mod is
identical, so nothing moved from `unmodelled` to `modelled` (or the reverse) in the corpus.

**Corroboration:** the full suite is green on the delivered tree —
`python -m pytest tests -q` → `2093 passed, 5 skipped in 129.02s` (12:31) — which includes the Phase
1–3 pins in `tests/test_builds_engine.py` (`damage['per_projectile']['blast'] == 166.95`,
`health_ranked == 370`, …).

**HIGH (evidence, not arithmetic) — the report's claim of "5 passed" for
`tests/test_refusal_preservation.py` is only true in isolation; the four new test files fail when run
together in the documented order.** Reproduced three times, including at 12:33:24:

```
$ python -m pytest tests/test_condition_states.py tests/test_conditional_damage.py \
                 tests/test_viral_status.py tests/test_refusal_preservation.py -q
FAILED tests/test_refusal_preservation.py::test_the_gate_passes_on_this_engine
1 failed, 93 passed in 1.37s

$ python -m pytest tests/test_condition_states.py tests/test_conditional_damage.py \
                 tests/test_viral_status.py tests/test_builds_engine.py -q      # the report's own line
120 passed in 0.37s
```
The failure detail is `refusal/corpus-count - 1 mods carry conditional lines`, i.e. the gate ran
against a one-mod database while asserting `min_corpus=100`. Root cause, bisected:
`tests/test_conditional_damage.py:271` sets `os.environ['WFM_BUILD_DB'] = str(db_file)` (a
`tmp_path` fixture database) and never restores it; the session-scoped `real_db` fixture
(`tests/test_refusal_preservation.py:40-44`) then reads that env var and hands the tiny database to
the gate with `min_corpus=100` (`tests/test_refusal_preservation.py:61-67`). It is masked in the
full suite only because `tests/test_planner_api.py:80` happens to pop the variable on tearDown
before `test_refusal_preservation.py` runs alphabetically. So the deliverable's own evidence block
(`phase4-report.md:167-172`) quotes a file list that excludes the one file that fails.
*Smallest fix:* wrap `tests/test_conditional_damage.py:271` in `try/finally:
os.environ.pop('WFM_BUILD_DB', None)` (or use `monkeypatch.setenv`), and quote the honest four-file
line in the report.

**HIGH — `import builds.validation` raises `ImportError` (circular import), live at 12:35:48.**
`builds/capacity.py:33` does `from .validation import as_int as _as_int` while `builds/validation.py:30`
does `from . import capacity as capacity_mod`. Whichever is imported first, the second fails:

```
$ python -c "import builds.validation; print('validation OK')"
  File "F:\VSC Projects\wfm-dashboard\builds\capacity.py", line 33, in <module>
    from .validation import as_int as _as_int
ImportError: cannot import name 'as_int' from partially initialized module 'builds.validation'
             (most likely due to a circular import)
$ python -c "import builds.capacity; print('capacity OK')"      # the other order
capacity OK
$ python -c "import builds.api; print('api OK')"                 # api imports capacity first
api OK
```
It is latent today only because every caller (`api.py`, `server.py`, the gate) happens to import
`capacity` before `validation`; a test or script that reaches for `validation` first (the natural
thing to do when you are testing validation, and exactly what a new `tests/test_validation*.py`
would) dies at import. Introduced during this phase's edit window (`builds/capacity.py` mtime
12:32:34, `builds/validation.py` 12:33:26 — neither existed in this form in Phase 3).
*Smallest fix:* move `as_int` (and any other shared helper) into a leaf module both import, or have
`capacity.py` do the import lazily inside the function that needs it.

**MEDIUM — the report's regression claim cannot be reproduced against a Phase-3 database.** The
`faction_multiplier` change from §4.3 is a *parser* change (`x1.03 Damage to Corpus` →
`faction_corpus`, `builds/effects.py:28-34, 174-182`) and the database was re-ingested with the new
parser (`data/build_data.json`, `content_hash 850099e4…`, `generated_iso 2026-09-30T02:00:59Z`, with
`faction_corpus: [3.0, 5.0, 8.0, 10.0]` already baked in). That means `python builds/ingest.py` +
`python -m pytest tests -q` can no longer distinguish a parser change from an engine change, and the
"Phase 1 numbers do not move" property is only testable against a re-ingested database. Evidence that
the parser claim itself is true (and that the DB is the new parse):

```
HEAD  parse x1.03 Damage to Corpus -> {'stat': None, 'value': 1.03, 'unit': 'flat', 'modelled': False, 'prefix': 'x'}
NEW   parse x1.03 Damage to Corpus -> {'stat': 'faction_corpus', 'value': 3.0, 'unit': 'percent', 'modelled': True}
```
One wording correction while I am here: `builds/effects.py:31-33` and the report say this "meant the
engine's `faction_multiplier` could never leave `1.0`". Only the 474 multiplier-form lines were
unmodelled; the non-flawed Bane family was already parsed and already moved the multiplier.
*Smallest fix:* keep a frozen pre-Phase-4 copy of `data/build_data.json` under `design/_planner/`
and run the pins against it, or state in the report that the regression sweep was run against a
pinned older database.

## 4. The viral mechanic (`builds/statuses.py`)

**COULD NOT BREAK the formula, the source, or the number.** I re-fetched the cited page.

* `builds/statuses.py:17` quotes `Resultant Damage to Health=Modded Damage×[2+(0.25×(Number of Viral
  Stacks−1))]`; the live page (retrieved via the browser-side extractor, `oldid=2805913` in the
  footer, matching `builds/statuses.py:43`) says exactly that, with the qualifier *"Calculating
  resultant damage if at least one Viral proc is on target."* — which is what makes `stacks=0 → ×1.0`
  (`statuses.amplifier`, line 65-66) correct rather than an off-by-one.
* The prose quote in the docstring ("by **100%** for **6** seconds … add **25%** … up to **325%** in
  total after **10** stacks … only shields and overguards are not affected") matches the wiki word for
  word. `MAX_STACKS = 10`, `PER_STACK = 0.25`, `BASE_AMPLIFIER = 2.0` and
  `REACHES = ('health', 'armor')` / `DOES_NOT_REACH = ('shields', 'overguard')` all follow from it.
  The wiki's "some Deimos units being outright immune" is what `immune_to` refuses on
  (`statuses.py:81-91`).
* **No refusal carries an amplifier value.** Direct calls: `evaluate(ctx(viral_stacks=4))` (no
  landing), `evaluate(ctx(viral_stacks=12, protection='health'))` and the immune case all return a
  row with `'amplifier' not in row` — the tests at `tests/test_viral_status.py:99,118,126` assert it
  and I re-ran them. `not_satisfied` rows *do* carry `amplifier=1.0` (lines 120, 127), which is by
  design (a reported zero, not a refusal) and is what the wiki implies for shields.
* Every branch in `evaluate`/`_stacks_result` ends in one of the four states; the only branch that
  could produce a wrong number instead of a refusal is the dead `if mult is None` guard at
  `statuses.py:109-112` (unreachable because `_stacks_result` runs first) — that is a comment, not a
  hole: `amplifier()` returns `1.0` only for `0`, `2.0..4.25` for `1..10`, and `None` for
  `bool`, non-int, negative and `> 10`.

**LOW — `protection` is case/whitespace-folded but `stacks` is not, and the wording of the
`not_satisfied` result for a `0`-stack target on shields is chosen by branch order.**
`evaluate(ctx(viral_stacks=0, protection='shields'))` reports "the damage lands on shields …" (line
113 runs before line 121), which is the less useful of two true reasons. Cosmetic.

**LOW — the engine's output is "damage to health" but the base it multiplies is not restricted to
health.** `builds/weapons.py:395-396` computes `damage_to_health = per_shot * amp` where `per_shot`
is the full per-shot total of every damage type. The wiki's `Modded Damage` is the modded damage of
the hit, so this matches the wiki's formula as written, but the name promises something narrower
than the arithmetic does; the trace says so (`weapons.py:399-403`), which is why I rate this LOW.

## 5. The page (`static/planner*.js`, `static/planner.html`)

**HIGH — see F2: the page displays a number the engine refused** (`planner-stats.js:397-407` reading
`out.result.dps` after a strict refusal). **HIGH — see F3: the page asserts "every number here is
unconditional" for a Warframe build whose conditional effect the engine refused**
(`planner.js:1321-1322`).

**COULD NOT BREAK — the page computes no Warframe number.** I read every arithmetic site in all four
planner scripts. They are: number formatting/rounding (`planner.js:62-88`), a delta against the
engine's own `baseline` (`planner-stats.js:196-211`), and percentage shares for the damage-split bar
(`planner-stats.js:349, 360, 367`). No Phase 1/4 formula is restated; the four forbidden literals are
absent (gate `page/no-maths` PASS at 12:33). The gate's own purity check is weak, though (see §6).

**COULD NOT BREAK — the page invents no default for an unstated input.** `targetState()`
(`planner.js:476-482`) seeds `faction: ''`, `protection: ''`, `viral_stacks: null`, `shot: null`,
`strict: false`, and `optionsFor()` (`planner.js:484-499`) sends a field only when it is non-empty;
`statedNumber` (line 502-506) turns `''`/NaN into `null` and the caller omits it. The `Lands on`
select's first option is `<option value="">not stated</option>`
(`static/planner.html:210-217`), so nothing pre-selects `health` — the exact trap the plan warns
about. Verified by reading the DOM source as well as the JS.

**MEDIUM — the page's Conditions card does not read `evaluation.unsupported_effects` at all.**
`renderEvaluation` (`planner.js:1273-1346`) prints `mode`, `state`, `withheld`, `refused_stats`,
`context_ignored` and the condition rows; the one field the report §4.5 calls "two stated facts rather
than one inferred from the other" never reaches a surface. Combined with F3 this means the two
numbers that would have contradicted "every number here is unconditional" are both invisible.
*Smallest fix:* print `ev.unsupported_effects` in `planner.js:1291-1295`'s meta line.

**LOW — the page recomputes a total it was given.** `planner-stats.js:349` sums the per-type amounts
to size the split bar, while line 352 prints the engine's `damage.per_projectile_total` next to it.
They agree today; they are two independent sources for one number.
*Smallest fix:* use `Number(damage.per_projectile_total)` for the bar's denominator, or show the
engine's total as the sum's label.

**COULD NOT BREAK — every refusal code reaches a visible surface.** `renderUnsupported`
(`planner.js:1262-1267`) prints `row.label || row.code` and `row.reason` for every marker without
filtering, so `conditional_effect`, `unmodelled_effect`, `calculation_refused`,
`context_unused`, `innate_secondary_element`, … all land in the Unsupported card. The only code
that has no `label` prints as itself, which is still the engine's own word.

## 6. Gate quality (24 checks at 12:35 — the report says 21, then 23)

The gate is `design/_planner/conditions_gate.py`. It changed **three times during this audit**:
21 checks when the report was written, 23 by 12:29:19, 24 by 12:34:48 — and its verdict went
`PASS 23/0` (12:29:19) → `FAIL 24 checks, 2 failed` (12:34:48) → `PASS 24/0` (12:35:57). The report's
"21 checks" (line 111) is stale; its Results block (line 163) already says 23 and 7 falsifications.
`run_checks` calls eleven check functions plus the page check, for 23 rows at 12:35.

| # | check | would it fail if the thing it names were broken? |
|---|---|---|
| 1 | `states/exactly-four` | Yes for a fifth *state*. **Weakened during this audit:** it now pins
`conditions.CONDITION_REASON_CODES` (`builds/conditions.py:67`) and only asserts that set is a subset
of the live `REASON_CODES` (`conditions_gate.py:208`). At 12:26 the live `REASON_CODES` had gained a
fifth code and the check **failed**; it passes now because the pinned copy was introduced. A widened
live vocabulary can no longer fail it. |
| 2 | `states/vocabulary` | Yes, but only over the first 120 conditional mods and only for a state
that is not one of the four — every row in practice is `unsupported`, so it is a membership test on a
single value. |
| 3 | `states/reached` | **No — it is a tautology.** `bool(seen)` where `seen` collects `marker['state']`
from any sampled build; one `unsupported` row satisfies it. Its label ("the corpus actually exercises
the state space") is not what it tests. |
| 4 | `refusal/corpus-count` | Yes — it is the check that caught the env-var leak in §3. |
| 5 | `refusal/structured` | Yes (a refusal without a state/reason code). |
| 6 | `refusal/never-applied` | Partly — it reads `block['applied']`, so a defect that applied the
rider while leaving `applied` False would pass it; `rider/never-in-totals` is what actually catches
that. |
| 7 | `refusal/checked-count` | Yes. |
| 8 | `rider/never-in-totals` | Yes **now** — but it could not fail until this audit window. Both
the version shipped with the report and the rewritten one passed
`effects.collect_mod_effects` a **bare `{'id', 'rank'}`** slot instead of the ingested mod row
(`api.engine_slots`/`validation.resolve_mod` is what the engine uses), so `totals` was empty for
every mod and the comparison loop never ran. Direct measurement:

```
$ python - <<'PY'
row = <Galvanized Chamber>            # rank_table {'multishot': [7.3, ..., 80]}, max_rank 10
bare = [{'kind':'normal','index':0,'polarity':None,'mod':{'id':row['id'],'rank':10}}]
print("the gate's slot shape   -> totals:", effects.collect_mod_effects(bare)[0])
rrow, rrank, _ = validation.resolve_mod({'id': row['id'], 'rank': 10}, db)
print('the engine (resolve_mod) -> totals:', ...)
PY
the gate's slot shape   -> totals: {}
the engine (resolve_mod) -> totals: {'multishot': 80.0}
```
The author's own new guard `comparisons > 0` turned that into a red gate at 12:34:48
(`{'mods': 0, 'comparisons': 0, 'offenders': []}`) and the current version routes the build through
`api.engine_slots`, so it now measures. **The check that guards the phase's central invariant had
never measured a total, and the only reason we know is a guard added while I was auditing.** |
| 9-11 | `unknown/withheld`, `numbers-intact`, `context-resolves` | Yes; the strongest trio in the
file — `withheld == ['target_faction']` is an exact assertion, not an `in`. |
| 12-13 | `unsupported/viral-cap`, `viral-landing` | Yes for `stats.viral_amplifier`; they do **not**
look for a leaked amplifier anywhere else in the payload (the F2 class of hole). |
| 14 | `unsupported/unmodelled-named` | Yes, over a 25-mod sample. |
| 15-17 | `numbers/viral-formula`, `viral-refuses`, `viral-states` | Yes — real wiki pins. |
| 18 | `malformed/never-crashes` | Yes for its corpus, **and it is the check whose name is false**:
the corpus (`BAD_CONTEXTS`/`BAD_OPTIONS`, lines 35-39) contains no `{'hypothetical': True}` and the
one hypothetical call (line 505) has no viral damage, so F1 sails through it. |
| 19 | `registry/coverage` | Yes, over sampled builds only. |
| 20 | `strict/refused` | Yes that the stats are nulled — and it **stops there**, which is why F2
survives. |
| 21-22 | `context/stated-inputs-named`, `used-inputs-not-flagged` | Yes (both added mid-audit). |
| 23 | `page/no-maths` | Yes for exactly four literals (`FORBIDDEN_ON_PAGE`, line 33). A page that
computed `2 + 0.25 * (n - 1)`, or multiplied an engine stat by a hard-coded constant, passes. |

**The falsifications are honest** — `falsify()` reinstalls each break, runs the whole check set, and
requires a failure; the report's "7 of 7" is credible (the seventh is the poisoned page text, which
does not touch the engine). Two of the six engine breaks (`unknown-reporting-applied`,
`classifier-assumes-satisfied`) are caught by several checks at once, so the gate's coverage is
slightly overstated by its own table — not a defect.

**The two 12:34:48 failures were both empty-evidence failures, and one of them is instructive.**
`rider/never-in-totals` reported `{'mods': 0, 'comparisons': 0, 'offenders': []}` (row 8 above), and
the brand-new `states/validation-codes-complete` reported `unlisted=[]` — a check whose failure
detail contains no offending code, i.e. a check that failed on `bool(emitted)`, its own extraction
regex finding nothing, rather than on a real unlisted code. Re-running the same regex by hand over the
same two files at 12:35 found 20 codes, all of them in `validation.CODES` (22 entries), so the check
*pending its own plumbing* would pass. Both were green nine minutes later. The lesson for the phase,
not the codebase: a check that can fail for a reason that is not the thing it names makes the gate's
red/green verdict unreadable — which is precisely the property the plan says must never be lost.

**A check I think is MISSING, and the Phase 5 mistake it would catch.**
`strict/no-number-survives`: after `api.compute(..., {'strict': True})` refuses a stat, walk the
*entire* answer (`result.stats[stat] is None`, and no `result.dps.*.value`,
`result.damage.per_shot_total`, `traces[*].final`, or `conditions[*].amplifier` carries the refused
stat's value). Phase 5's stated next step is "a clause whose state is known and whose effect the
engine can compute" — the first applied conditional modifier. The moment a new stat joins
`refused_stats`, the payload has three more places to leak it (this is exactly F2, and no check
looks), and a phase that adds conditional *effects* is a phase that adds refused stats. Second
choice, for the same reason and the same phase: `frame/evaluation-block`, asserting that a Warframe
build carrying a `conditional_effect` marker has a non-empty `conditions` list or a non-`deterministic`
evaluation (F3).

## 7. Constraint check against the plan's HARD CONSTRAINTS

* **No combat simulator** — COULD NOT BREAK. No tick/rotation/probabilistic model exists;
  `builds/statuses.py` is one closed-form multiplier with the timeline explicitly refused
  (`statuses.py:157-163`, `statuses.py:36-39`). Nothing in the diff introduces a time axis.
* **No inverse solver** — COULD NOT BREAK. No search/optimisation code in `builds/`, `server.py` or
  the planner scripts; the only `preview` route computes two builds and diffs engine answers.
* **No live external game data** — COULD NOT BREAK on the compute path. `grep -n
  "urllib\|requests\|http://\|https://\|socket" builds/*.py` returns **nothing** outside
  `builds/ingest.py` (one fetch, by design), and `planner_compute` (`server.py:1678-1692`) only reads
  the local database.
* **No recommendation engine** — COULD NOT BREAK. `grep -rn "recommend\|farm this\|best build\|inverse"`
  over `builds/*.py` and the planner scripts returns nothing.
* **No migration of all 426 conditional mods** — HOLDS. `refusal/corpus-count` reports the corpus at
  426 and the gate asserts every one of them still refuses (`refusal/structured`,
  `refusal/never-applied`, `refusal/checked-count` all PASS).
* **The browser never performs Warframe calculations** — HOLDS for formulas (see §5); the purity
  check that guards it is literal-based and therefore weak.
* **Unknown never interpreted as false or zero** — HOLDS in the engine's arithmetic (a withheld
  contribution is never added, `weapons.py:153`, `424-425`; `unknown` and `unsupported` both block,
  `weapons.py:477`), and is **broken in the UI twice**: the fabricated `deterministic` block for
  Warframes with `withheld: []` and a hidden chip (F3), and strict mode's refused numbers painted
  from `result.dps` (F2).

---

## What I could not break

Attacks that failed, listed because they are as much the result as the findings:

1. **Getting a conditional rider into a total.** Not through `collect_mod_effects` (only
   `rank_table` entries are summed), not through `effect_rows`/`summed_percent` (neither touches the
   `conditional` list), not through `warframes.py`, not through `debug.py`/`capacity.py`. The gate's
   `rider/never-in-totals` and my own corpus scan agree.
2. **Moving a Phase 1–3 number with no conditional context.** 2,057 builds (every equipment
   baseline + every mod alone on compatible equipment, no options), Phase 3 tree vs delivered tree:
   **0 stat differences, 0 marker-code differences, 0 `ok`-flag differences.**
3. **Reading a state as a boolean, a number, `''`, `None` or a missing key.** `conditions.result`
   raises on anything outside the four words (tested against `True/False/0/1/''/None/[]`), and no
   consumer in `builds/`, `server.py` or `static/` compares a state to `True`, wraps one in `bool()`,
   or tests `if state:`. The only bool-ish read near a condition is `row.get('hypothetical')`.
4. **Making a refusal carry a number.** `statuses.evaluate` returns rows with **no `amplifier` key at
   all** for `unknown` and `unsupported` (not a `null` to be defaulted); `conditions.result` refuses
   to coerce; the viral refusal for `>10` stacks and for an unknown landing both leave
   `stats.viral_amplifier` absent.
5. **Getting a conditional mod to classify as `satisfied`.** `classify_conditional_text`
   (`conditions.py:374-393`) can only return `unsupported`, and the falsified version of it is caught
   by three checks.
6. **Getting the viral numbers wrong against the source.** The wiki (oldid 2805913, re-fetched)
   gives the same formula, the same +100%/25%/325%/10-stack cap, the same shields-and-overguard
   exclusion and the same Deimos immunity note as the code and the docstring; 1→×2.00, 5→×3.00,
   6→×3.25, 10→×4.25 all hold, and 0 stacks is ×1.0 because the wiki's formula is conditioned on "at
   least one Viral proc".
7. **Making the engine do maths the page should not.** No formula constant in any planner script and
   no per-stat reinterpretation: the page prints `row.state`, `row.reason_code` and the engine's own
   strings.
8. **A malformed context/options/build/rank crashing the engine.** The gate's corpus (strings,
   arrays, nested junk, `1e400`, `'abc'`, `NaN`, `3.5`, booleans, `None`) and the new
   `validation.as_build`/`as_int` really do hold — the one crash I found needs a *well-formed*,
   documented option (`hypothetical`) plus a legitimate build, which is why the malformed corpus
   never sees it.
9. **A live citation of a *stale* report claim about the gate.** I first read "21 checks, 0 failed";
   by 12:26 the same command returned `GATE FAIL - 21 checks, 1 failed`, and by 12:33
   `GATE PASS - 23 checks, 0 failed`. I could not make the *stale* number stick as a finding because
   the report was corrected mid-audit — the surviving version of that finding is the evidence line in
   §3 (the four-file pytest list that avoids the file that fails).
