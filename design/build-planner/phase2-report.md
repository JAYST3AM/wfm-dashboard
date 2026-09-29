# Phase 2 — the planner page: what was built, what it refuses, what was checked

Phase 1 (committed as `128fc86`) is the engine: `builds/` answers *"what does this build
produce, and why is this number this number?"* — stdlib only, one entry point,
`api.compute(build, db)`, with a trace on every stat and a written refusal for every mechanic
it will not guess at.

Phase 2 is the page that drives it. Nothing in the page does Warframe maths: `server.py` joins
the ingested database to the engine and exposes it over `/api/planner/*`; `static/planner.*`
is a client of that, and where a number appears twice the gate checks the two agree.

| Piece | What it is |
|---|---|
| `static/planner.html` | The page: equipment head, toolbar, three columns, one popup (the picker) and one tooltip (the mod card). No duplicate chrome — the shell paints the header and rail. |
| `static/planner.css` | Layout and the Arsenal-toned panel style, 1280 → 1920 (and down to one column under 900). |
| `static/planner.js` | State + storage v1, the API client, the equipment picker, the toolbar (rank, Mastery, Catalyst, Exilus, Forma, configs, copy/clear), the slot grid, drag & drop, rank/polarity controls, capacity, validation, the before/after preview, keyboard. |
| `static/planner-library.js` | The mod library: search, class/polarity/support filters, sort, rows with badges, the mod detail card, click/drag install. |
| `static/planner-stats.js` | The "what does it produce" half: grouped stats with deltas, the damage split, the element composition, the trace panel, the refusals, and the **capacity detail** table (which slot was charged what, and under which rule). |
| `server.py` (`/api/planner/*`) | `meta`, `equipment/<key>`, `equipment?q=`, `library`, `compute`, `compare`, `preview`, `explain`, `unsupported`. POST bodies are the build itself; unknown planner routes 404 instead of falling through to a file. |
| `tests/test_planner_api.py` | The route contract, against a real socket and an ingested fixture database. |
| `tests/test_planner_page.py` | The page contract: the ids the modules need, the storage schema, the IA pins, the "engine owns the maths" rule. |
| `design/_planner/build_planner_gate.{js,py}` | The browser gate: 66 checks over the whole workflow, real Chrome, real server, screenshots, and a mechanical report. |

## The rules the page keeps

1. **The engine owns every number.** Every stat the page paints comes from `api.compute`.
   The gate reads the DOM, asks the API for the same build, and fails if they disagree —
   and separately pins three Phase 1 values (35 / 40.25 / 92.75 damage) so engine drift
   cannot hide behind agreement.
2. **Refusals are visible, never silent.** A mod that carries a mechanic the engine does not
   model says so on its library row (`2 not calculated`), on the installed mod in its slot
   (clicking opens the same card), and in the refusal list with the tick counts. Unsupported
   ≠ dropped: the stat panel names what it did not add.
3. **Capacity is explainable.** The capacity card names the total's parts (rank capacity,
   Catalyst ×2, the Mastery floor when it binds, Aura/Stance bonuses) and then, per filled
   slot, the raw drain → the charged drain and the rule (`matched`, `vacant`, `wrong
   polarity`, `no polarity`). Changing a polarity costs a Forma: the toolbar counts them and
   the table names each change.
4. **Nothing is faked.** No Forma is consumed, no owned-mod check, no recommendations, no
   market data. Configs A/B/C are real, separate builds and the storage schema is versioned
   (`wfm.planner.v1`); anything else in that key is discarded *and rewritten* at boot.
5. **Keyboard and mouse get the same tool.** `/` searches, `↑/↓` walk the results, `Enter`
   installs, `1–8` focus a slot, `a/s/e` the Aura/Stance/Exilus slots, `Del` clears, `Esc`
   steps back out.

## What the gate found (and the fixes it forced)

The gate was written before the page was finished, on purpose and it earned its keep:

* **Aura/Stance mods were misclassified by the validator** — the exporter's mod shape and the
  ingested shape classified differently, so an Aura became a normal mod the moment validation
  touched it. Fixed at the source in `builds/effects.slot_class()` (both shapes now classify
  identically) with a selftest that pins it.
* **A polarity change did not refresh the Forma count** — `renderResult()` never called
  `renderForma()`, so the toolbar lied until the next click.
* **A locked slot silently handed its drop to the grid**, which installed the mod into the
  first free slot instead of refusing. Locked slots now answer the drag themselves, mark
  themselves `data-drop="bad"`, and say why.
* **`dragover` re-rendered the grid**, which can cancel a native drag in Chrome. The body now
  carries the drag state and the grid is left alone until the drop.
* **A foreign `localStorage` payload was ignored but left sitting.** It is now discarded and
  rewritten at boot.
* **The search box was a keyboard dead end** — `↓` did nothing, so the library could not be
  driven without a mouse. `↓` now hands focus to the results with a row highlighted.

## Verification

* `python design/_planner/build_planner_gate.py` — the browser gate: **66 checks, 0 failed**
  (see `design/_planner/build-planner-report.md` for the run, the raw JSON for every value).
* `python -m pytest tests/ -q` — the whole suite, engine and page together.
* The engine's own selftests stand: `python builds/debug.py selftest` (122 checks) and the
  refusals registry (`python builds/debug.py unsupported`).

## Left deliberately undone (the brief's "do not build yet" list)

Auto-import from the game, owned-mod filtering, recommendations, market/price integration,
riven solving, and anything that would need an account. The page is offline-first, reads only
its own API, and stores nothing outside `localStorage`.

## The audit round (after `7d06d63`)

Two independent reads of the Phase 2 diff, then the fixes. **Codex Sol** (`gpt-5.6-sol`, read-only)
and **space-bunny** (`opencode-go/space-bunny-free` under `opencode`, deny rules on the home tree)
both came back with findings; space-bunny's verdict was FAIL on two of them.

**What the audits caught and the tree now answers:**

| Finding | Fix |
|---|---|
| `renderMrHint` computed `15 + floor(mr/2)` in the page — a second copy of `builds/capacity.py` rule | the hint prints the engine's `capacity.minimum_from_mastery` and says when it binds |
| A failed `/compute` rendered as "everything is calculated" with capacity 0 and "loading…" forever | a `.pl-error` banner, `data-planswer="no"`, every panel says "No answer from the engine."; the capacity readout prints `—` |
| Click/keyboard install used `modFitsSlot`, skipping the Exilus lock the drag path honoured | one `slotLegal()` for click, keyboard, auto-install and drag; the toolbar's live adapter switch is the only source |
| `/preview` and `/explain` raised `AttributeError` on a non-object body (valid JSON `[]`/`"x"`/`null`) | `_planner_payload()` + `try/except` on the planner POST block: a structured answer, never a 500 |
| `loadStorage` merged partially-valid v1 documents and int-coerced junk inside the engine route | `cleanV1()` validates every field and range; an unreadable payload is replaced whole and rewritten |
| Preview/picker fetches had no sequence token; a stale answer could paint over a newer one | `previewSeq` / `pickerSeq`; hiding the preview invalidates the in-flight one |
| The library could land for an item that was no longer selected | the answer carries the item it was asked for; the grid repaints when it lands |
| Restoring the stored equipment wiped the stored rank | the rank is kept when the equipment is the same and dropped when it changes |
| Choosing a polarity equal to the item's own (including "vacant") was priced as a Forma change | the entry is removed instead of written; the menu always offers "As shipped", vacant included |
| `role="button"` polarity dot was unreachable by keyboard; Escape dropped focus to `<body>` | `tabindex` + Enter/Space; the picker's Escape stops there and returns focus to `#plEquipBtn` |
| The stats panel found "free" capacity by subtracting, and printed per-slot charges without the raw figure | `capacity.drain.remaining` and `charged, was raw` — both engine numbers, nothing derived |
| The docs' route table listed `/library`, `/compare` and a `?slug=` that never shipped | the table now matches the shipped routes, and the audit briefs point at it |
| The page-guard test's no-math scan (by its author's own note) tolerated comparisons and a local floor formula | the MR-floor formula is gone and `mastery` is a watched quantity; the scan now trips on a re-derivation |

**Found while fixing the above** (the new gate check earned its keep): the engine's
`exilus_ok()` read only the exporter's `isExilus`/`isUtility` keys, but the ingester folds those
into `flags.exilus` — so the validator answered "Aerial Ace is not an Exilus mod" for every
Exilus mod while the library listed the very same rows as Exilus-capable. `exilus_ok()` now reads
both shapes, with a selftest and an engine test pinning it; before the fix no Exilus mod could be
slotted at all, and the page (correctly) showed the engine's refusal.

**Also landed in this round** (found by the same reading): the catalogue's shadow copies — the
WFCD data ships `/Beginner/`, `/Intermediate/` and `/Expert/` rows wearing real mods' names, some
of them numerically impossible. They are renamed to the game's own names ("Flawed Serration"),
flagged, kept out of the library behind a count, and never slotted as the real card; Conclave
(`/PvPMods/`) rows carry a badge. Verified against the wiki's own `Module:Mods/data`.
