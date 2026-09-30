# Phase 4 audit — the refusal path, end to end

Scope: engine → API → server → page, plus malformed input and the honesty guarantees. Every claim
below is cited `file:line` and backed by a real request/response or test name captured against the
fixture database (`tests/test_builds_engine.py::FIXTURE_MODS`) at commit working tree 2026-09-30.
`tests/test_build_states.py` is the Trading Session's build-progress file, **not** the planner: it
does not touch this path (its `build_payload` is `server.build_payload()`, trading session).

---

## 1. Engine → API: how codes and markers reach the `compute_build` result dict

`builds/api.py::compute(build, db, options=None)` (63-111) is the single entry point; `builds/api.py:64`
docstring: *"Validate + calculate one build. Never raises for a bad build."* (contradicted — see §4.)

Two carriers reach the dict:

- **Validation codes** — `report = validation.validate_build(...)` (`api.py:70`), returned as
  `{'ok','errors','warnings'}` (`validation.py:243-244`). `error()` / `warning()` produce
  `{'code','message','severity',...extra}` (`validation.py:33-42`). Shape: `severity` is the string
  `'error'`/`'warning'`.
- **Unsupported markers** — engine markers come back inside `result['unsupported']`; API copies them
  and appends registry-known gaps:
  ```python
  unsupported = list((result or {}).get('unsupported') or [])      # api.py:92
  if result is not None:                                           # api.py:93
      missing = unsupported_mod.check_coverage(unsupported)        # api.py:94
      for code in missing: unsupported.append(unsupported_mod.marker(code))
  ```
  Marker shape: `{'supported': False, 'code', 'reason'}` plus `phase` and per-marker extras
  (`unsupported.py:180-188`; engines emit the same via `effects.py:449-453`).

**Result dict keys** (real probe, 6×Serration on Braton Prime):
```
['baseline','build','capacity','capacity_remaining','capacity_used','equipment','ok',
 'result','unsupported','unsupported_registry','validation']           # api.py:97-111
```
`ok = bool(result is not None)` (`api.py:98`). Gating: `result`/`baseline` are computed only when the
equipment resolves **and** `report['ok']` is true (`api.py:78-89`).

**Do codes survive a refusal?** Validation codes **yes**, unsupported markers **no**:
```python
# probe: 6×Serration (duplicate_mod ×5 + capacity_exceeded)
ok=False | result=None | baseline=None | capacity_used=84 | capacity_remaining=-24
error codes: ['duplicate_mod'×5, 'capacity_exceeded']   unsupported==[]      # api.py:92
```
`unsupported` reads `result`, and on refusal `result is None`, so it is always `[]` for a refused
build — even a build that also installs a conditional mod (`api.py:92-96`, `api.py:93` guard).
`capacity`/`capacity_used`/`capacity_remaining` **do** survive a refusal (they ride `report['capacity']`,
`api.py:91,104-106`). §6 must thread a new condition state alongside `validation`, not inside `result`.

---

## 2. API → server: the planner route

- Route: **`POST /api/planner/compute`** → `server.py:1965-1966`, calling
  `planner_compute(b)` (`server.py:1662-1673`), which calls `mods['api'].compute(build, db)` and adds
  `out['engine'] = {'schema_version', 'content_hash'}` (`server.py:1671-1672`).
- Request shape: a JSON object = the brief's build (see `builds/api.py:11-24`). Response: the §1 dict.
- Body reading (`server.py:1960-1963`): `json.loads(... or '{}')`; a parse failure →
  `400 {'ok': False, 'error': 'bad JSON body: ...'}`.
- Error handling for malformed *input* (`server.py:1964-1982`):
  ```python
  except (TypeError, ValueError, KeyError, AttributeError) as e:      # server.py:1975
      return self._send(400, {'ok': False, 'error': 'the engine could not read this body: %s' ...})
  except Exception as e:                                              # server.py:1979
      return self._send(500, {'ok': False, 'error': 'the planner crashed: %s' ...})
  ```
- Non-object JSON body: `planner_compute` guards `isinstance(build, dict)` → `200 {'ok': False,
  'error': 'build must be a JSON object'}` (`server.py:1667-1668`). Junk object `{}` →
  `200` with `validation.errors = [{'code':'unknown_equipment', 'field':'equipment_id', ...}]`.
- **Can a bad build 500? Yes.** Probe (real socket, raw bodies):
  ```
  equipment_rank 1e400 (inf) -> (500, 'the planner crashed: cannot convert float infinity to integer')
  mastery_rank 1e400 (inf)   -> (500, 'the planner crashed: cannot convert float infinity to integer')
  mastery_rank Infinity      -> (500, ...)
  equipment_rank NaN         -> (400, ... cannot convert float NaN to integer)   # ValueError, caught
  equipment_id dict/list     -> (400, ... unhashable type: 'dict'/'list')        # TypeError, caught
  ```
  `OverflowError` (float `inf` → `int()`) is not in the 1975 tuple, so it lands on the 1979 generic
  handler and becomes a **500**. `ValueError`/`TypeError` (NaN, str, unhashable) become 400s.
- Other POST planner routes: `/preview` (`server.py:1682-1697`), `/explain` (`server.py:1700-1718`),
  `/current/refresh` (1971), `/clone` (1973); unknown planner POST → `404 'unknown planner route'`
  (`server.py:1983`). GET planner routes: `server.py:1778-1789`.

---

## 3. Server → page: where warnings/errors/refusals are rendered

Answer state is set once in `recompute()` (`static/planner.js:497-529`):
```js
state.answer = out || null;                                  // planner.js:511
state.result = good ? out : null;                            // planner.js:512  (good = !!out.result)
state.error = (out && out.error) ? out.error                 // planner.js:514
  : (good || (out && out.validation) ? null : 'the engine did not answer');   // planner.js:515
```
| Element id | Where declared | Renderer | What it draws |
|---|---|---|---|
| `#plError` | `planner.html:29` (`hidden`) | `renderError()` `planner.js:1164-1174` | text from `state.error`; sets `data-planswer` on `<body>` (1173) |
| `#plCapNote` | `planner.html:105` | `renderCapacity()` `planner.js:1042-1043` | *"the engine refused this build - see Validation"* when `state.answer.validation` exists |
| `#plValidity` / `#plValidityMeta` | `planner.html:227` / `:225` (`#plValidityCard` :222) | `renderValidation()` `planner.js:1074-1119` | errors+warnings rows; each row prints the code |
| `#plUnsupported` / `#plUnsupportedMeta` | `planner.html:241` / `:239` (`#plUnsupportedCard` :236) | `renderUnsupported()` `planner.js:1121-1147` | `row.label||row.code` (1143) + `row.reason` (1144) |
| slot refusal chip | — | `planner.js:630-635` | `sup.unmodelled + sup.conditional` "not calculated" |

The code/reason print, verbatim (`planner.js:1111-1115`):
```js
el('span', { text: row.message || row.code }),
el('div', { class: 'pl-val-code',
  text: ['code', row.code, row.field,
    row.mod ? (modName(row.mod) || row.mod) : null].filter(Boolean).join(' · ') })
```
Preview prints codes too: `errors.map(function (e) { return e.code; }).join(', ')` (`planner.js:1007-1008`).
`planner-current.js:291`: `el('p', ..., text: e.code + ' · ' + (e.message || ''))`.

**Does the page derive game semantics?** Almost none — one place compares a code:
`var over = errors.some(function (e) { return e.code === 'capacity_exceeded'; });` (`planner.js:981`;
mirrored by `used > total` at 1052). Everything else is display: codes are echoed verbatim, counts
are `.length`, and the no-math scan (`tests/test_planner_page.py:265`) forbids page arithmetic on
`drain|capacity|mastery|...` (`test_planner_page.py:258-262`). `planner-stats.js:101-107` and
`planner-current.js:277-296` only count/label; neither interprets a code. Phase 4's new state must
arrive as engine text, not a code the page branches on.

---

## 4. Malformed / edge input: tests and the gap

Existing coverage (`file::test_name`):
- `tests/test_builds_engine.py::test_validation_codes` (173-190) — parametrised over
  `incompatible_mod_type`, **`duplicate_mod`** (175-176), **`rank_exceeds_max`** (177),
  `mod_slot_kind_mismatch`, **`unknown_mod`** (182), **`unknown_equipment`** (183),
  **`invalid_equipment_rank`** (185).
- `tests/test_builds_engine.py::` **drain over capacity** — `test_capacity_exceeded_is_a_validation_error`
  (193-199); **malformed build** — `test_a_bad_build_never_raises` (202-204, `{'equipment_id': None,
  'slots': 'nope'}`); `test_every_refusal_is_named_in_the_registry` (208-213) +
  `::test_registry_rows_explain_themselves` (216-219).
- `tests/test_planner_api.py::test_compute_never_raises_on_junk` (313-326) — `{}`, `{'slots': 'nope'}`,
  `{'equipment_id': 5, 'slots': [1,2]}`, `{'equipment_id': 'nope'}`; asserts status in `(200,400)` and
  no `'crashed'`/`'could not read this body'` text. Also `::test_compute_reports_capacity_overrun_as_a_validation_error`
  (296-302); `::test_compute_reports_refusals_instead_of_dropping_them` (305-310);
  `::test_preview_rejects_junk_bodies` (353-355); `::test_preview_shows_a_hypothetical_edit_that_does_not_fit`
  (344-350); `::test_a_post_with_a_broken_body_is_a_400_not_a_traceback` (375-380);
  `::test_a_planner_post_with_a_non_object_body_is_an_answer_not_a_traceback` (402-409);
  `::test_explain_survives_a_build_that_is_not_an_object` (433-436).

**Gap (reached exception, not asserted away).** `validate_build` coerces ranks with `int()`:
`mastery = int(build.get('mastery_rank') or 0)` (`validation.py:223`) and, via the capacity engine,
`rank = max_rank if equipment_rank is None else int(equipment_rank)` (`capacity.py:125`) and
`mr = max(0, int(mastery_rank or 0))` (`capacity.py:128`). These run **after** `validation.py:215-221`
already recorded an `invalid_equipment_rank` error for a non-int rank, so the error path still raises:
```
compute(wb(mastery_rank='abc'))   -> RAISED ValueError: invalid literal for int() with base 10: 'abc'
compute(wb(equipment_rank='x'))   -> RAISED ValueError: invalid literal for int() with base 10: 'x'
compute(wb(mastery_rank=[1]))     -> RAISED TypeError: int() argument must be ... not 'list'
```
No test covers a numeric-but-non-integer rank. Consequences across the wire: `str`/`NaN` → 400, but
`1e400`/`Infinity` (→ `float('inf')`) → **`OverflowError` → 500** (§2). So malformed input *can* reach
an exception, and one shape produces a 500. `orokin: 'yes'` is silently truthy (`bool('yes')`,
`api.py:168`) — accepted without a warning; also uncovered. Note the conditional-*marker* path
(`effects.py:420-424`) is fed by ingested `mod.effects`, never by request input, so malformed build
input cannot reach `collect_mod_effects` today — a new condition source (§6) is the first thing that
would put request data on that path, which is exactly where §4's coercion must be replaced by
structured validation.

---

## 5. The honesty guarantees, quoted

- **A refusal is an answer.** `api.py:64` *"Validate + calculate one build. Never raises for a bad
  build."*; `planner.js:509-510` *"A refusal is not a result to paint, but it is an answer: the
  engine's own validation ... is kept and shown by the Validation card."*; `planner-stats.js:102` *"a
  refusal carries no numeric result but is still an answer: read the whole thing"*.
- **`#plError` is only for failure to answer.** `design/build-planner/phase4-plan.md:96-97`: *"a
  refusal is an answer (engine validation codes survive a refusal; `#plError` is reserved for a real
  failure to answer)"*. `renderError()` hides the banner unless `state.error` is set (`planner.js:1167-1171`);
  `state.error` stays `null` whenever `out.validation` exists (`planner.js:515`).
- **Browser gate pins it.** `design/_planner/build_planner_gate.js:1036-1042` — *"a refusal is not
  reported as a failure to answer"* (asserts `banner_hidden === true` with the engine codes shown);
  the positive half at `:973-975`; live result in `build-planner-report.md:89,91`.
- **Audit contract:** `design/_planner/audit-brief.md:120-122` — a failed `/compute` must produce the
  `#plError` banner, `body[data-planswer="no"]`, `—` in capacity, and *"No answer from the engine."* in
  the panels — *"never 'Everything this build uses is calculated.' with painted zeros."*
- **The engine owns every number.** `planner.js:8` *"capacity, stats, traces, refusals, validation -
  arrives from /api/planner/*"*; enforced by the no-math scan `test_planner_page.py:265-287`.

---

## 6. Insertion points for Phase 4 (condition state + evaluation context)

Thread a four-state value `satisfied | not_satisfied | unknown | unsupported` and an explicit
evaluation context through, in this order:

1. **States as constants** — `builds/schema.py:107` (beside `SLOT_KINDS`) / `:117` (`EQUIP_KINDS`):
   add `CONDITION_STATES = ('satisfied','not_satisfied','unknown','unsupported')`.
2. **Condition source → marker** — `builds/effects.py::collect_mod_effects` (`:382-446`); today the
   flat `conditional_effect` marker is emitted at `:420-424` and `unmodelled` at `:425-433`. Emit a
   per-condition `{code, state, condition, effect, reason}` here instead. `unsupported_marker()`
   (`:449-453`) is the shared shape to extend.
3. **Registry** — `builds/unsupported.py::REGISTRY` (`:21-140`) and `MARKER_TO_KEY` (`:144-164`): add
   `condition_unknown`/`condition_not_satisfied`/`condition_unsatisfied_effect` keys; `marker()`
   (`:180-188`) should carry `state`; `check_coverage()` (`:221-232`) must keep asserting every code is
   named.
4. **Validation + context validation** — `builds/validation.py::error`/`warning` (`:33-42`) and
   `validate_build` (`:99-244`): replace the raising `int()` coercions (`:223`, `capacity.py:125,128`)
   with structured codes and validate the evaluation context here; a context field that cannot be read
   must become `unknown`, not an exception.
5. **API result assembly** — `builds/api.py::compute` (`:63`): add a `context=None` parameter and a new
   top-level `'conditions'`/`'context'` key in the return dict (`:97-111`). Keep it **outside** `result`
   so it survives a refusal like `validation`/`capacity` do (the §1 finding: `unsupported` is `[]` on
   refusal). Add a `conditions` block to `_compare_side` (`:152-159`) for preview.
6. **Server pass-through** — `server.py::planner_compute` (`:1662-1673`) and `planner_preview`
   (`:1682-1697`): accept and forward `context`; keep the 400/500 split at `:1975-1982` but ensure the
   new validators make `OverflowError` unreachable (else the generic 500 stays).
7. **Page** — `static/planner.js::renderValidation` (`:1074-1119`) and `renderUnsupported`
   (`:1121-1147`), driven by `state.answer` (`:511`) / `state.error` (`:514-515`); markup
   `#plValidityCard` (`planner.html:222`), `#plValidity` (`:227`), `#plUnsupportedCard` (`:236`),
   `#plUnsupported` (`:241`). Render `condition: <state> / effect: <state> / reason: <text>` verbatim
   (`phase4-plan.md:80-82`: *"the page ... must not decide that unknown 'probably means false'"*). Do
   **not** add a code branch; the only existing code comparison (`planner.js:981`) stays as-is.
8. **Tests** — extend `test_builds_engine.py` validation region (`:172-219`) with the four states and
   the `inf`/`NaN`/`str` rank cases; extend `test_planner_api.py` `test_compute_never_raises_on_junk`
   (`:313-326`) with the `1e400`/`Infinity` bodies that currently 500; the browser gate's
   `answer-contract` checks (`build_planner_gate.js:973-1042`) already pin the honesty half.
