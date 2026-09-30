# Phase 4 — independent verification of the refusal-preservation claims

Auditor: independent subagent (read-only). Target of audit: `design/build-planner/phase4-report.md`.
Date: 2026-09-30. Repo: `F:\VSC Projects\wfm-dashboard` at git HEAD `b6cb0c3` (dirty working tree).

**The revision audited is pinned by hash** (the working tree changed *during* this audit — see the
note below). Every number here was produced by my own scripts against the real ingested database
`data/build_data.json` (content hash `850099e418e3648c25d80e06d97b6c6f09f72800fb177848ea9f1ef35bb6c05e`),
which was **not** re-ingested — the hash recomputes identically from the existing file, so it is the
database the report describes.

```
eb18a6e44ca2e6aa595c32e59b922cd3da66b3c81692c9ae20c6a827feb2df26  builds/conditions.py
60f2748c4c0ffca6af9c276cece17b388eeb23d6fee47acfa1933351dc14f565  builds/statuses.py
00585f3579e93bef291d6c7d7b22132cd40b9da25f3240a0a54c6364553dbc17  builds/weapons.py
ef4df81cf5f6150535d12b43564148c3457716ff5564af3b8dbe111aa5a2256a  builds/effects.py
7f4fbdda5e4e42ccbade276cf7b5a638a8b8c4ea6580c278a9b4f56a1618c2c4  builds/api.py
9aea4dce5043db348ae1a6f0c5d71e57ecb2b9563a4bb311daeb42e157c09ecc  builds/validation.py
16e78dfb6368cff7985cb1618337c1473eb5af5672633dfd20e0fb5d4e2dc678  design/_planner/conditions_gate.py
b5543b6b8182c6097e11faaf0c348dd381003f401a29a1dc33415699969ec21c  design/build-planner/phase4-report.md
```

## A moving target (important)

While this audit ran, another process edited the implementation. Timestamps:

```
2026-09-30 12:25:07  builds/weapons.py            (evaluation gained "consumed"/"unused")
2026-09-30 12:26:25  tests/test_conditional_damage.py
2026-09-30 12:27:03  builds/conditions.py
2026-09-30 12:27:51  design/_planner/conditions_gate.py   (two context/* checks added)
2026-09-30 12:28:03  design/build-planner/phase4-report.md  (report rewritten: 21 -> 23 checks)
```

`phase4-report.md` was re-read at 12:29 and is the version quoted below. It now agrees with the tree
in §3 (23 checks, 7 of 7) **but not in §4.6** (still "21 checks", still "six deliberate breaks"). I
re-ran every check against the post-edit tree; all substantive results below are from that revision
(a re-hash at the end showed no further drift).

---

## Claims checked

How verified: my own scripts (`/…/scratch/p4v/claim15.py`, `claim1b.py`, `claim2.py`, `claim3.py`,
`claim4.py`, `claim4_http.py`, `claim4b.py`, `extra.py`, `bp_gate.py`, `bp_extra.py`) plus direct
`pytest`/gate invocations. "Counted myself" means I iterated the raw database, not a project test.

| # | claim (source) | how verified | command | observed | verdict |
|---|---|---|---|---|---|
| 1 | "1809 mods" (§3) | counted `len(db['mods'])` | `python claim15.py` | `total mods : 1809` | **VERIFIED** |
| 2 | "1016 carry stats we do not model" (§3) | counted rows with `effects.unmodelled` | `claim15.py` | `recount unmodelled : 1016` | **VERIFIED** |
| 3 | "426 carry conditional effects" (§3, §4.2) | counted rows with `effects.conditional` | `claim15.py` | `recount conditional : 426` | **VERIFIED** |
| 4 | content hash `850099e4…` (§3) | recomputed `ingest.content_hash(db)` | `claim15.py` | identical string | **VERIFIED** |
| 5 | "All 426 conditional mods still refuse, with the same `conditional_effect` code" (§4.2) | built every one on equipment that accepts it; every one returned a result carrying `conditional_effect` markers | `claim15.py`, `claim1b.py` | 426 conditional mods; 331 equippable, 95 of an absent kind; `api.compute returned no result: 0`; `mods with NO conditional mark : 0` | **VERIFIED** |
| 6 | each refusal carries `condition_id` + `state` + `reason_code` + a `condition` block (§4.2) | inspected every `conditional_effect` marker (430) | `claim1b.py` | `UNSTRUCTURED refusals : 0`; states seen `{'unsupported': 430}`, reasons `{'mechanic_unsupported': 430}` | **VERIFIED** |
| 7 | the four refusal reasons are all expressible (§4.2) | set-compared to the four names | `claim1b.py` | `REASON_CODES == {condition_unknown, condition_not_satisfied, condition_effect_unimplemented, mechanic_unsupported}` | **VERIFIED** |
| 8 | four states exactly; `result()` raises outside them; no `truthy()` function (§4.1) | read `conditions.STATES`; called `result('x','maybe',…)` | `extra.py` | `ValueError: condition state 'maybe' is not one of …`; `grep def truthy` → none (only prose) | **VERIFIED** |
| 9 | missing input → `unknown` with `missing: ['target_faction']` (§4.1) | ran a faction mod with no context | `claim2.py` | row `state=unknown … "missing":["target_faction"]` | **VERIFIED** |
| 10 | "the four states are disjoint from the validation vocabulary … and the gate pins that" (§4.1) | searched the gate + tests for a disjointness check | `extra.py` | sets are disjoint, but **no gate check references validation**; the pin is a `tests/test_condition_states.py` docstring | **DISCREPANCY (D8)** |
| 11 | "474 corpus lines now parse (x1.05 → +5%)" (§4.3) | counted multiplier-form lines and how many become modelled stats | `extra.py` | 474 multiplier-form lines; **421 modelled**, **53 still unmodelled** (incl. 22 `Damage to Sentients`) | **DISCREPANCY (D7)** |
| 12 | "Bane of Grineer R5 against Grineer is now ×1.30" (§4.3) | computed it | `claim2.py` | `faction_multiplier: 1.3` | **VERIFIED** |
| 13 | viral golden values 1→×2.00, 5→×3.00, 10→×4.25, 6→×3.25, +325% cap (§4.4) | called `statuses.amplifier`, cross-checked the wiki formula | `claim3.py` + wiki fetch | all golden values exactly match; wiki (oldid 2805913) confirms `[2+(0.25×(stacks−1))]`, "up to 325%" | **VERIFIED** |
| 14 | "A refusal carries no `amplifier` key at all" (§4.4) | inspected `statuses.evaluate` rows | `claim3.py` | unknown/unsupported: `amplifier_key_present=False`; not_satisfied: `1.0` (a reported zero) | **VERIFIED** |
| 15 | shields/overguard are not reached; health/armour are (wiki + §4.4) | wiki text + engine states | wiki fetch, `claim3.py` | wiki: "only shields and overguards are not affected"; engine: shields/overguard → `not_satisfied ×1` | **VERIFIED** |
| 16 | `damage_to_health = modded_damage x amplifier`, real viral build (§4.4, §4.5) | Cryo Rounds R5 + Infected Clip R5 on Soma Prime; viral per-projectile 21.6 | `claim3.py` | stacks 1/5/10 → `damage_to_health` 67.2 / 100.8 / 142.8 = `damage_per_shot` 33.6 × 2 / 3 / 4.25; `dth == dps*amp: True` | **VERIFIED** |
| 17 | Charged Chamber R3 → +40%: `modded_base_damage` 35 → 49 (§4.6) | R3 on Braton Prime (base 35) | `extra.py` | shot1 `49`, shot3 `35`, no-context `35` | **VERIFIED** |
| 18 | shot 3 = reported zero; no shot number = withheld (§4.6) | same run | `extra.py` | shot3 state `not_satisfied`; no ctx state `conditional` | **VERIFIED** |
| 19 | (a) no context leaves headline numbers identical to the no-mod baseline (§4.5) | compared `modded_base_damage/damage_per_shot/burst_dps/…` | `claim2.py` | `(a) headline == baseline headline: True {}` | **VERIFIED** |
| 20 | (b) matching faction applies the multiplier exactly (§4.3) | `context.target_faction='grineer'` | `claim2.py` | `faction_multiplier == 1.30`; `burst_dps == (a) burst_dps * 1.3` (ratio 1.3); base damage unchanged | **VERIFIED** |
| 21 | (c) a different faction leaves headline numbers identical to baseline (§4.5) | `context.target_faction='corpus'` | `claim2.py` | `(c) headline == baseline headline: True`; row `not_satisfied` | **VERIFIED** |
| 22 | (d) strict withholds the affected stats and names them (§4.5) | `{'strict': True}` | `claim2.py` | state `refused`; `refused_stats ['damage_per_shot','damage_per_shot_expected_crit','burst_dps','sustained_dps']`, all `None` | **VERIFIED** |
| 23 | (e) hypothetical applies but stays labelled conditional (§4.5) | `{'hypothetical': True}` | `claim2.py` | `faction_multiplier 1.3`, `burst_dps 374.4`, `mode=hypothetical`, `state=conditional`, row `hypothetical: true` | **VERIFIED** |
| 24 | "GATE PASS - 23 checks, 0 failed / falsification 7 of 7" (§3) | ran the gate | `python design/_planner/conditions_gate.py --falsify` | `GATE PASS - 23 checks, 0 failed` / `falsification: 7 of 7 breaks caught` | **VERIFIED** |
| 25 | §4.6 still says "21 checks" and intro/"§205" say "six" breaks | counted the gate's own rows and the falsification table | gate run + `conditions-gate-report.md` | gate is 23 checks; falsification table has **7** rows | **DISCREPANCY (D3)** |
| 26 | "116 passed" for the 4-file pytest subset (§3) | ran exactly the quoted command | `python -m pytest tests/test_condition_states.py tests/test_conditional_damage.py tests/test_viral_status.py tests/test_builds_engine.py -q` | `120 passed in 0.37s` (23+39+27+31) | **DISCREPANCY (D1)** |
| 27 | "5 passed" for `tests/test_refusal_preservation.py` (§3) | ran it | `python -m pytest tests/test_refusal_preservation.py -q` | `5 passed` | **VERIFIED** |
| 28 | full suite line (§3, printed as `FULL_SUITE_LINE`) | ran it | `python -m pytest tests -q` | `2093 passed, 5 skipped in 130.81s` — the report prints the literal placeholder `FULL_SUITE_LINE` | **DISCREPANCY (D2)** |
| 29 | "PASS - 115 checks, 0 failed" browser gate (§3) | booted the server and ran the gate's Node half with output redirected to scratch, plus the wrapper's 4 source-state checks | `python bp_gate.py` + `python bp_extra.py` | Node half `checks: 111, failed: 0` … `PASS`; source-state `4 passed`; 111+4 = 115 | **VERIFIED** |
| 30 | "Malformed input must not crash … Covered by the gate's malformed corpus (contexts, options, builds, ranks)" (§2) | fire a 90-case junk corpus at `api.compute` and the real route | `claim4.py`, `claim4_http.py` | `api.compute` **raises** on unhashable ids and a huge-int mod rank; the route returns **HTTP 500** for one | **DISCREPANCY (D4)** |
| 31 | the canonical stat a conditional line "would have moved (recovered by re-parsing the cleaned line)" (§4.2) | re-parsed all 430 conditional lines | `claim1b.py` | only **11** re-parse to a modelled stat; **419** return `stat=None` | **DISCREPANCY (D5)** |
| 32 | gate check "a conditional line never adds to the totals it shares with its base stat" guards the totals (§3, §4.6) | called the check directly and read its detail | `claim1b.py` | `rider/never-in-totals ok=True detail={'checked': 0, 'offenders': []}` — it compares nothing | **DISCREPANCY (D6)** |
| 33 | "`evaluation.unsupported_effects` counts the refused mechanics" (§4.5) | inspected payloads | `claim2.py`, `claim4b.py` | key present and changes with refusals (1 → 2 under strict) | **VERIFIED** |
| 34 | `conditions` + `evaluation` surface at the top level of `api.compute` (§4.5) | inspected the return dict | `claim2.py` | `r["conditions"]` and `r["evaluation"]` present for every case | **VERIFIED** |

Independent corroboration of the substantive refusal-preservation property (the one the vacuous
gate check was supposed to guard, D6): I recomputed every conditional mod's collected totals from
its raw per-rank lines and compared to `collect_mod_effects` output — **38 stat-buckets compared,
0 mismatches**, and separately `0` mismatches against the unconditional `rank_table`. There is no
case where a conditional rider reaches a total. The property holds; the *gate check named for it*
does not exercise it.

---

## Raw evidence (selected, pasted verbatim)

### the four states from the outside (`claim2.py`)
```
(a) no context      evaluation: {"mode":"stated_inputs","state":"conditional",…,"withheld":["target_faction"],…}
                    conditions: [{"condition":"target_faction","state":"unknown","reason_code":"condition_unknown",…}]
                    modded_base_damage 12 | damage_per_shot 12 | burst_dps 288.0
(b) faction grineer evaluation: {…,"state":"deterministic",…}   faction_multiplier 1.3  burst_dps 374.4
(c) faction corpus  conditions: [{"condition":"target_faction","state":"not_satisfied",…}]  burst_dps 288.0
(d) strict          evaluation: {"mode":"strict","state":"refused","refused_stats":["damage_per_shot",
                    "damage_per_shot_expected_crit","burst_dps","sustained_dps"],…}   burst_dps None
(e) hypothetical    evaluation: {"mode":"hypothetical","state":"conditional",…}  faction_multiplier 1.3  burst_dps 374.4
```

### malformed input (`claim4.py` + `claim4_http.py`)
```
api.compute RAISED: 4
    ('equip_id=dict', "TypeError: unhashable type: 'dict'")
    ('equip_id=list', "TypeError: unhashable type: 'list'")
    ('slot_mod_id=name-list', "TypeError: unhashable type: 'list'")
    ('mod_rank=bigint', 'OverflowError: int too large to convert to float')
route status 500  : 1     mod_rank=bigint  OverflowError
route status 400  : 3     equip_id=dict / equip_id=list / slot_mod_id=name-list
```
Real HTTP (server on a scratch port, raw bodies):
```
mod rank bigint              500   {"ok": false, "error": "the planner crashed: int too large to convert to float"}
equip_id dict                400   {"ok": false, "error": "the engine could not read this body: unhashable type: 'dict'"}
equipment_rank 1e400         200   {"ok": false, …}   (this one *is* fixed)
```
Traceback (huge-int mod rank):
```
File "builds/api.py", line 76, in compute   report = validation.validate_build(build or {}, db)
File "builds/validation.py", line 285, in validate_build   cap = capacity_mod.capacity_breakdown(
File "builds/capacity.py", line 215, in capacity_breakdown
    used_pct = 0 if not capacity_total else min(100, int(round(total_drain * 100.0 / capacity_total)))
OverflowError: int too large to convert to float
```
Silent numbers from malformed options (`claim4b.py`):
```
hypothetical='no' (string)   mode=hypothetical  state=conditional  faction_multiplier=1.3  burst_dps=374.4
strict='yes'/'no' (string)   mode=strict        state=refused
orokin="yes" / "no" / "false" all -> orokin_doubled=True, capacity_total=60  (documented limitation)
```

---

## Discrepancies

**D1 — §3 test count is wrong.** The report states `116 passed` for the four-file subset. Running
the exact command gives **`120 passed`** (23 + 39 + 27 + 31). `tests/test_conditional_damage.py`
was edited at 12:26, so the report's number is stale or was never re-measured after the edit.

**D2 — §3 full-suite line is an unfilled placeholder.** The report prints:
```
python -m pytest tests -q
  FULL_SUITE_LINE
```
`FULL_SUITE_LINE` is not a result; it is the literal template token the report generation left
behind. Measured: **`2093 passed, 5 skipped in 130.81s`**.

**D3 — the report contradicts itself on the gate.** §3 says "GATE PASS - 23 checks, 0 failed" and
"falsification: 7 of 7 breaks caught"; but line 111 (§4.6) still says "**21 checks**", the intro
(line 10) says the gate "has been proven to catch **six** deliberate breaks", and line 205 is
headed "The **six** falsifications" above a table with **seven** rows. The tree and the gate's own
report are 23 checks / 7 breaks. (The report was rewritten at 12:28 to the 23/7 numbers, but §4.6
and the intro were not updated with it.)

**D4 — "Malformed input must not crash" is still false at the engine and route boundaries.** §2
claims malformed input is "Covered by the gate's malformed corpus (contexts, options, builds,
ranks)". It is not:
* `api.compute({'equipment_id': {'a': 1}}, db)` → `TypeError: unhashable type: 'dict'`
  (`builds/validation.py:100`, `resolve_equipment` hashes the key without checking it);
  same for a list. A truthy unhashable value raises *inside* `compute`, whose docstring says it
  "Never raises for a bad build".
* a slot reference `{'mod': {'name': ['Serration']}}` → `TypeError: unhashable type: 'list'`
  (`builds/validation.py:125`, `resolve_mod`).
* a **huge-integer mod rank** (`10**1000`) → `OverflowError` at `builds/capacity.py:215`, which the
  planner route turns into **HTTP 500** (`server.py:2007-2010`). This is the *same crash class* the
  report says was fixed ("a rank of `1e400` … → HTTP 500 … Both are fixed"); the fix covers
  `equipment_rank`/`mastery_rank` (which now 200) but not a mod's own rank.
The gate's `BAD_CONTEXTS`/`BAD_OPTIONS`/malformed-build corpora contain none of these three shapes,
so "covered by the gate's malformed corpus" is not true for them. The route converts the two
unhashable shapes to 400s, so the wire-level impact is bounded, but the engine-level
"never raises" contract is broken.

**D5 — the "canonical stat" a conditional line would move is almost never recovered.** §4.2 says
each refusal carries "the canonical stat it would have moved (recovered by re-parsing the cleaned
line)". Re-parsing the stored conditional text yields a modelled stat for only **11 of 430** lines
(the conditional-only family: `aim_glide_zoom`, `finisher_chance_on_block`, `damage_bleedout`).
For the other **419** (`On Kill: +30% Multishot for 20s. Stacks up to 5x.` and everything like it)
`parse_stat_line` returns `stat=None`, and the marker stores `stat: null`/`value: null`. The claim
is true per-key but misleading in substance.

**D6 — the gate check that is supposed to prove "a conditional line never adds to the totals" is
inert.** `conditions_gate.py::check_nothing_conditional_reaches_the_totals` derives the stats to
compare from `effects.parse_stat_line(conditional_text)['stat']`. Because that is `None` for 419/430
lines (D5) and the 11 that do resolve have no `rank_table` to compare against, the check's
`checked` counter is **0** — it runs, passes, and compares nothing:
```
GATE CHECK rider/never-in-totals ok= True detail= {'checked': 0, 'offenders': []}
```
It never appears in any falsification break's failing-check list, consistent with being unable to
fail. The property it is *named* for is genuinely true (my independent recomputation: 0 mismatches
over all 426 conditional mods), but the check the report lists among the guards (§3, §4.6) does not
test it.

**D7 — "474 corpus lines now parse" overstates the faction fix.** 474 lines do match the multiplier
form, but only **421** become modelled stats (`faction_corpus` 95, `faction_grineer` 95,
`faction_infested` 95, `faction_corrupted` 68, `faction_murmur` 68). **53 remain unmodelled**,
including **22 `x# Damage to Sentients`** (the plural is not in `FACTION_TAIL`), 9 `Turret Damage vs
Corpus`, 4 `Max Shield Capacity`, etc. Those faction mods are still refused (so refusals are
preserved — this is *not* a safety problem), but the report reads as if the whole faction family now
parses, and the in-code comment in `effects.py` ("all of them faction damage") is also wrong.

**D8 — "the gate pins that" (states vs validation vocabulary) is not true.** §4.1 says the four
states are disjoint from the validation vocabulary "and the gate pins that". The gate never
references `validation`; the disjointness pin is a docstring/assertion in
`tests/test_condition_states.py` ("Validation codes are their own vocabulary: none of them is a
condition state"). Disjointness itself holds (overlap = ∅).

---

## Not verified

* **The two non-planner gates §3 now cites** — `python design/_stage10/gate.py` ("GATE PASS") and
  `python design/_session/workflow_gate.py` ("WORKFLOW PASS - 23 of 23 checks"). They are outside the
  Phase 4 refusal path and write reports into the repo; my mandate here was read-only, so I did not
  run them.
* **DOM-level rendering of the Conditions card / diagnostics strip.** I exercised the page only
  through the browser gate's own Node half (111 checks, 0 failed), not with independent DOM
  assertions; the "Conditions badge read …" strings in §3 come from the gate's own report, which I
  reproduced but did not re-derive by hand.
* **`python builds/ingest.py`.** I did not re-run the ingest (it writes the 5 MB database); I
  recomputed the counts and the content hash from the existing file and they match the report, which
  is equivalent evidence for these claims.
* **The falsification attribution in §3's table** (which *named* checks fail for each break) beyond
  the gate's own generated report: I confirm 7 of 7 breaks are caught and read the tool's failing-check
  lists, but did not independently re-derive each attribution.
* **Phase 1/3 regression of arbitrary unrelated builds.** The report's "Phase 1/3 numbers do not
  move" is verified only for the concrete cases above (faction mod, viral build, first-shot); I did
  not diff every imported loadout.

---

## Bottom line

26 of the report's distinct claims are reproduced exactly with my own numbers — including every
refusal-preservation guarantee that matters: the 426 conditional mods all still refuse with the
structured `condition_id`/`state`/`reason_code` block, no conditional rider reaches any total, the
faction mod leaves the headline numbers identical when unstated/wrong-faction and applies exactly
×1.30 when satisfied, strict withholds named stats, hypothetical applies while staying labelled, the
viral golden values and `damage_to_health = damage_per_shot × amplifier` are exact, and the gate
catches 7 of 7 deliberate breaks.

8 discrepancies were found. The load-bearing one is **D4**: the phase's "malformed input must not
crash" contract is still false at the engine boundary (unhashable ids raise `TypeError`; a
huge-integer mod rank still produces a real HTTP 500), and the gate corpus that §2 cites as its
coverage does not include those shapes. **D6** matters second: the gate check the report names as
guarding "a conditional line never adds to the totals" runs with `checked=0` and proves nothing —
the property itself is nevertheless true (independently recomputed: 0 mismatches). **D1/D2** are
stale/unfilled results in §3 (116→120; `FULL_SUITE_LINE`→`2093 passed, 5 skipped`). **D3** is an
internal contradiction (23/7 in §3 vs 21/"six" in §4.6 and the intro). **D5/D7/D8** are overstatements
about the stat-recovery, the 474 multiplier lines, and where the states-vs-validation pin lives.
