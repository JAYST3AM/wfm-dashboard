# Audit brief — Phase 2, the build-planner page (read-only)

## 1. TASK GOAL

Phase 1 shipped the build-planner **engine** (`builds/`, committed `128fc86`): stdlib-only,
one entry point `api.compute(build, db)`, a trace on every stat, and a *named refusal* for every
mechanic it will not approximate.

Phase 2 adds the **page** that drives it, and nothing else in the app changed behaviour.

Acceptance criteria (from the Phase 2 brief):

1. **The engine owns every number.** The page must not do Warframe maths. Anything the page
   paints must come from `/api/planner/*`; where a number appears in the DOM it must equal the
   engine's answer for the same build.
2. **Refusals and validation are visible, never silent.** A mod with a mechanic the engine does
   not model must say so (library row, installed slot chip → detail card, refusal list).
   Impossible builds must show the engine's specific reasons, not a generic error.
3. **Capacity is explainable.** The capacity card names the total's parts (rank capacity,
   Catalyst ×2, Mastery floor when it binds, Aura/Stance) and, per filled slot, the raw drain →
   charged drain + rule (`matched` / `vacant` / `wrong polarity` / `no polarity`).
4. **The UI is a tool, not a form.** Drag & drop both ways (library→slot, slot→slot move/swap,
   slot→library remove), keyboard parity (`/` search, `↑↓`, `Enter`, `1–8`, `a/s/e`, `Del`,
   `Esc`), configs A/B/C with duplicate + clear, slot rank/polarity controls, before/after
   preview on hover/drag.
5. **State is versioned and fails gracefully.** `localStorage` key `wfm.planner.v1`; anything
   else must be discarded and rewritten, never half-applied.
6. **No invented features.** No Forma consumption, no owned-mod filtering, no recommendations,
   no market data, no auto-import.
7. **IA**: one new rail destination (Planner) between Collection and Tools; the shell still
   renders one active pill and one `aria-current` per page; no duplicate chrome on the page.
8. **Regression**: the existing suites and gates still pass (pytest, `design/_stage10/gate.py`,
   `design/_session/workflow_gate.py`); a new browser gate drives the planner workflow.

## 2. EXACT DIFF

Working tree at commit `<FILLED AT DISPATCH>` (`git show --stat <sha>` and `git show <sha>`
are the truth; this brief is a map, not a substitute):

| Path | What it is |
|---|---|
| `server.py` | the `/api/planner/*` routes (`meta`, `equipment?q=`, `equipment/<key>`, `mods`, `compute`, `preview`, `explain`, `unsupported` — the shipped table is `docs/build-planner.md`), `_qs()` query helper, POST-body parsing, planner 404s |
| `builds/api.py` | `_compare_side()` extracted so each side of `compare` carries stats + `capacity_used` |
| `builds/effects.py` | **bug fix**: `slot_class()` now classifies the exporter's mod shape and the ingested shape identically (an Aura was becoming a normal mod at validation time) + a selftest pinning it |
| `static/planner.html` / `.css` / `.js` | the page, its layout and its core (state + storage v1, API client, picker, toolbar, slot grid, drag & drop, rank/polarity, capacity, validation, preview, keyboard) |
| `static/planner-library.js` | mod library panel (search, filters, sort, rows, detail card, install) |
| `static/planner-stats.js` | stat panel (grouped stats + deltas, damage split, elements, traces, refusals, capacity detail) |
| `static/shell.js` | the `planner` page entry in PAGES + the rail gain one destination |
| `tools/build_icons.py`, `static/icons/phosphor.svg` | the `blueprint` icon the rail needs |
| `tests/test_planner_api.py` | route contract over a real socket + ingested fixture DB |
| `tests/test_planner_page.py` | page contract (ids the modules need, storage schema, IA pins) |
| `tests/test_ia_reachability.py`, `tests/test_redesign_ia.py`, `tests/test_ui_polish.py` | rail pins moved from six destinations to seven |
| `design/_planner/build_planner_gate.{js,py}` | the new browser gate (66 checks) + its report/raw JSON |
| `design/build-planner/phase2-ui-spec.md`, `phase2-report.md`, `docs/build-planner.md`, `docs/navigation.md`, `README.md`, `design/build-planner/README.md` | docs |

## 3. RELEVANT CONTEXT ONLY

* The engine's contract (do not re-derive it from the page): `builds/api.py` (`compute`,
  `compare`, `explain`, `preview`), `builds/validation.py` (error/warning codes),
  `builds/capacity.py` (`capacity` + `drain.per_slot[].rule`), `builds/unsupported.py`.
* The page's own contract: `design/build-planner/phase2-ui-spec.md`.
* The build shape the page POSTs is the same dict the engine's own CLI uses
  (`builds/debug.py`), so a client and the debug surface cannot drift.
* `data/build_data.json` is generated (`builds/ingest.py`) and already committed; the page only
  reads it through the API.

### Deliberate decisions — do NOT report these as bugs

* **No Forma is consumed.** The toolbar counts the slots changed vs the item's own polarities
  and says so; nothing is spent and nothing is written outside `localStorage`.
* **No owned-mod check, no recommendations, no market data, no auto-import** — the brief forbids
  them in this phase.
* **Refusals are counted, not resolved**: 1071 mods carry an unmodelled stat and 416 a
  conditional effect; the page names them instead of guessing.
* **`capture_screenshot`-style browser artefacts live in the OS temp dir, not the repo.**
* A few live-window tests (the whisper capture selftests that read Warframe's own window) fail
  only while Warframe itself is running on this machine — pre-existing, unrelated to this diff.

## 4. TEST EVIDENCE

* `python -m pytest tests/ -q` → see the report line below (this brief is dispatched with the
  current run attached).
* `python design/_planner/build_planner_gate.py` → 66 checks, 0 failed; report
  `design/_planner/build-planner-report.md`, raw numbers `design/_planner/build-planner-raw.json`.
* `python design/_stage10/gate.py` and `python design/_session/workflow_gate.py` → regression.

| input | expected output |
|---|---|
| `GET /api/planner/meta` | `{ok, content_hash, mods_total, equipment_total, engine, categories}` |
| `GET /api/planner/equipment/<uniqueName or slug>` | the equipment detail incl. `damage_total`, `damage` split, `polarities` |
| `GET /api/planner/equipment?q=braton` | normalised search rows (`uniqueName`, `name`, `kind`, `slot`, `damage_total`) |
| POST `/api/planner/compute` with the bare build | `{ok, validation:{errors,warnings}, capacity{capacity,drain.per_slot}, result{stats,damage,traces,…}, baseline, unsupported}`; unknown equipment → `ok:false, validation.errors[0].code == 'unknown_equipment'` |
| POST `/api/planner/preview` with `{build, next}` | the same shape as compute for the hypothetical build (`next` = `{kind,index,mod}`) |
| `POST /api/planner/explain` with `{build, stat}` | the trace rows for that stat |
| Braton Prime + Serration R10 | `result.stats.modded_base_damage == 92.75`, `capacity_used == 14` in a vacant slot, `7` with a Madurai polarity |
| Serration at rank 0 | `modded_base_damage == 40.25` (+15%, not zero) |

## What to do

Read the diff. Report findings in the format below, with file:line evidence, and say plainly if
there are none. Run only read-only commands; do not edit, commit or push.

```
SEVERITY:  CRITICAL / HIGH / MEDIUM / LOW (NITs labelled)
FILE/LINE:
ISSUE:
WHY IT MATTERS:
MINIMUM REQUIRED FIX:
```

No blocking findings → `PASS — ZERO BLOCKING FINDINGS` plus a compact summary.
