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
