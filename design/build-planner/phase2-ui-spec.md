# The build planner page — Phase 2 contract

Phase 1 shipped the engine (`builds/`, one entry point `api.compute(build, db)`, see
`docs/build-planner.md`). Phase 2 is the page that drives it: `static/planner.html` +
`planner.css` + three plain scripts, one new rail destination, and one workflow gate.

**The rule the page keeps: it owns no Warframe math.** Slots, mods, capacity, stats, traces,
refusals and validation all come from the API below, which calls the engine. The page's own
arithmetic is limited to formatting numbers the engine produced and diffing two engine
answers it was handed (both engines runs are real; see `/preview`).

## Routes (server.py)

| Route | Answers |
| --- | --- |
| `GET /api/planner/meta` | kinds + slot layouts + database identity + storage version |
| `GET /api/planner/equipment?q=&kind=&limit=` | equipment picker rows (name/slug substring, ranked) |
| `GET /api/planner/equipment/<id\|slug\|name>` | one equipment row + its slot layout |
| `GET /api/planner/mods?equipment=<key>` | every installable mod, library-row shape |
| `GET /api/planner/unsupported` | the refusal registry (`rows`, `marker_keys`) |
| `POST /api/planner/compute` | `{build}` → validation, capacity, stats, traces, refusals |
| `POST /api/planner/preview` | `{build, next}` → the diff a hover/drag shows |
| `POST /api/planner/explain` | `{build, stat}` → the rendered trace + which stats have one |

All of them answer 200 with `{ok: false, error}` for bad input — the page never sees a 500.
`GET` payloads: meta ~1 KB, equipment 1.5 KB, library ~200 KB (cached server-side per kind,
fetched once per equipment change and cached client-side).

### The build dict the page sends

```json
{"config": "A", "equipment_id": "/Lotus/Weapons/Tenno/Rifle/BratonPrime",
 "equipment_rank": 30, "orokin": true, "mastery_rank": 28, "exilus_unlocked": false,
 "slots": [{"kind": "normal", "index": 0, "polarity": "madurai",
            "mod": {"id": "/Lotus/Upgrades/Mods/Rifle/WeaponDamageAmountMod", "rank": 10}},
           {"kind": "aura", "index": null, "polarity": null, "mod": null}]}
```

* `kind` is `normal | aura | stance | exilus`; `index` is 0-7 for normal, `null` otherwise.
* `polarity` is the slot's polarity (`null` = vacant, `universal` = Aura Forma); the UI edits it.
* A slot with `"mod": null` is empty. `unlocked: true` on the exilus slot (or
  `exilus_unlocked` on the build) unlocks an Exilus Adapter slot.
* Slots are the only place mods live — there is no separate "equipped" list.

### Compute answer (what the panels read)

```
{ok, validation:{ok, errors[], warnings[]}, capacity:{capacity:{total,rank_capacity,
 doubled_capacity,orokin_doubled,minimum_from_mastery,floored_by_mastery,aura_bonus,stance_bonus},
 drain:{per_slot:[{kind,index,mod_name,raw_drain,adjusted_drain,adjustment,rule,polarity,
 mod_polarity}]}}, capacity_used,
 result:{stats:{...}, damage:{composition,modded_base_damage,per_projectile,...,burst_dps},
   traces:{<stat>:{label,base,unit,modifiers:[{source,mod_name,rank,value,unit,category}],final,
   notes[]}}},
 baseline:{stats,damage}, unsupported:[{marker,key,label,reason,...}], reason,
 engine:{schema_version,content_hash}}
```

Validation codes the UI labels (never invents): `capacity_exceeded`, `duplicate_mod`,
`unknown_mod`, `unknown_equipment`, `mod_slot_kind_mismatch`, `aura_in_normal_slot`,
`normal_in_aura_slot`, `stance_in_normal_slot`, `mod_not_exilus`, `exilus_not_unlocked`,
`invalid_rank`, `rank_exceeds_max`, `invalid_slot_index`, `duplicate_slot`,
`incompatible_mod_type`, `mastery_below_requirement`, `invalid_equipment_rank`,
`invalid_polarity`, `too_many_errors`.

## Page layout (1280×800 minimum, 1920 target)

```
┌ shell header (rail + search + theme, from shell.js) ──────────────────────────────┐
│ toolbar   [equipment picker] [rank ▾] [catalyst/reactor] [exilus] [MR ▾]   [A|B|C]│
├───────────────┬───────────────────────────────────────────────┬───────────────────┤
│ slot grid     │ mod library (search · filters · rows)         │ stat panel        │
│ + capacity    │                                               │ (groups, deltas,  │
│ + validation  │                                               │  traces, elements,│
│               │                                               │  refusals)        │
└───────────────┴───────────────────────────────────────────────┴───────────────────┘
```

* ids: `#planner #plEquip #plEquipBtn #plEquipSearch #plEquipList #plRank #plOrokin #plExilus
  #plMr #plConfigs #plGrid #plCap #plCapUsed #plCapTotal #plCapBar #plValidity #plLibrary
  #plLibSearch #plLibFilters #plLibList #plLibCount #plStats #plStatBody #plTraces #plTraceBody
  #plUnsupported #plUnsupportedList #plPreview #plStatus #plReset #plCopy`.
* classes: `pl-*` for page-specific pieces; `card btn btn.primary kpi mono dim small` and the
  theme vars (`--panel --panel2 --border --text --muted --accent --accent-dim --mono --r`) from
  `style.css` for everything else. No new colours, no inline `style=""`, no `!important`.
* slot grid: one `button.pl-slot[data-kind][data-index]` per slot, `data-state=empty|filled|blocked`,
  the mod name inside, drain in the corner, polarity dot, ✕ to clear, click to focus the slot,
  drag target for library rows. Keyboard: `1`-`8` focus slots, `Delete` clears, `Esc` closes panels.
* stat panel: one row per stat (`data-stat`), `#plStatBody` groups them (Offence / Crit / Status /
  Cadence / Survivability / Capacity), each row shows the engine's value + a delta chip against
  `baseline`; clicking a row opens its trace in the right rail (`#plTraces`).
* refusals: `#plUnsupported` lists the compute's `unsupported` markers with their `reason`;
  a library row with `support.unmodelled|conditional > 0` carries a small badge that points here.
* preview: hovering a library row (or dragging over a slot) fetches `/preview` and shows
  before → after chips for the affected stats plus a fit verdict (fits / over capacity /
  rejected with the engine's code). Never a client-side guess.

## Storage (planner storage v1)

One key: `wfm.planner.v1` (`meta.storage_version` tells the page when to migrate).

```json
{"version": 1, "equipment_id": "...", "equipment_rank": 30, "orokin": true,
 "exilus_unlocked": false, "mastery_rank": 28, "active_config": "A",
 "configs": {"A": {"slots": {"normal:0": {"id": "...", "rank": 10, "polarity": "madurai"}}},
             "B": {"slots": {}}, "C": {"slots": {}}},
 "library": {"q": "", "polarity": "", "slot": "", "sort": "name", "hide_refused": false,
            "hide_installed": false},
 "ui": {"configs": true, "traces": "damage"}}
```

Config state = slots (mods, ranks, polarities). Shared state = rank, catalyst/reactor, exilus,
mastery rank, equipment. An unknown `version` is ignored (fresh start), never migrated blindly.
The library fetch is keyed by equipment id and cached in memory (and `sessionStorage` for the
current equipment only — the payload is ~200 KB, so it is not written to `localStorage`).

## IA changes this ships

1. A **seventh rail destination** `planner` — `RAIL` gains `['planner', '/planner.html',
   'blueprint', 'Planner']` at the end of the first group, `RAIL_GROUPS` gains `'planner'`,
   `PAGES.planner = {sub: 'build planner', prefix: '/', active: 'planner', link: {href: '/',
   label: 'Dashboard', icon: 'arrow-left'}}` (shell.js).
2. `static/planner.html` is a page like collection.html: `data-shell="planner"`, its own CSS/JS.
3. `tests/test_ia_reachability.py` + `design/_stage10/gate.js` move from 6 rail entries to 7 and
   from 5 pages to 6 (this is the sanctioned adjustment the brief allows — nothing else about IA
   moves).
4. Deep links: `/planner.html?equip=<id|slug|name>&config=A|B|C` (id wins, name resolves through
   the API's search).

## Files

| File | Owns |
| --- | --- |
| `static/planner.html` | shell declaration, markup skeleton, script order |
| `static/planner.css` | the page's density layer (grid, library, stat panel, responsive) |
| `static/planner.js` | `WFMPlanner`: state + storage, API client, picker, toolbar, slot grid, drag/drop, capacity, validation, keyboard, deep links |
| `static/planner-library.js` | the library panel: search, filters, sort, rows, badges, detail, selection |
| `static/planner-stats.js` | stat panel + traces + elements + refusals + preview diff |
| `design/_planner/build_planner_gate.{js,py}` | the 15-step workflow gate that drives all of it |
| `tests/test_planner_page.py` | static contract tests for the page (ids, storage key, no-math) |

`WFMPlanner` (the only global the three scripts share):

```js
WFMPlanner = {
  state,                       // live storage-v1 object
  api: {meta(), equipment(q), item(key), mods(id), compute(build), preview(a, b), explain(build, stat)},
  build(),                     // -> the build dict for the active config (never computed in the page)
  result,                      // last compute answer
  setSlot(kind, index, mod, rank, polarity), clearSlot(kind, index), setPolarity(kind, index, p),
  setEquipment(id), setConfig(letter), setRank(n), setOrokin(b), setExilus(b), setMr(n),
  on(event, fn),               // 'result' | 'equipment' | 'library' | 'state'
  render(),                    // re-render panels after a state change (debounced compute)
  fmt: {num(v, unit), pct(v), signed(v, unit)},
  el(tag, attrs, children),    // tiny DOM helper (no innerHTML for anything from the API)
}
```

## Phase 2.5 layout note

The page keeps every id above and the storage contract unchanged; what moved is the composition.
The equipment header carries identity and rank only (the engine/database line lives in the footer),
the build controls are one row, the workspace is slots / library / stats, and validation, capacity
detail and not-calculated became a flat `<details>` strip (`#plDiag`, `.pl-dg`, closed by default,
each with a `.pl-dg-badge`). New ids: `#plHeadRank` (the rank chip), `#plEmpty` + `#plEmptyPick`
(the first-run hero). `body.pl-no-equip` is the first-run state and hides the controls, workspace
and diagnostics. The equipment popover's close-on-outside handler runs in the capture phase, and
category chips must update in place - rebuilding them detaches the clicked node and the handler
then reads the click as outside (that was the picker-closes-on-category bug).
