# WFM Trader — Build Planner

A build planner that answers **"what does this build actually produce?"** for Warframe
equipment, and can always answer **"why is this number this number?"**

Two pieces:

* **Phase 1 — the engine** (`builds/`): a stdlib-only calculation and data foundation that
  ingests authoritative data, validates a build, computes the stats the arsenal shows, and
  *names every mechanic it refuses to fake*.
* **Phase 2 — the planner page** (`static/planner.html` + `static/planner*.js`): the
  Arsenal-style interface that edits a build and displays what the engine returns. The page
  owns **no Warframe math** — it POSTs a build and renders `result`, `traces`, `validation`
  and the refusals, plus the server routes in `server.py` that join the database to the
  engine.

## The planner page

`/planner.html` is a first-class destination (7th rail entry, deep-linkable with
`?equip=<name|slug|uniqueName>&config=A|B|C`, same shell/theme/focus behaviour as the other
pages).

| Area | What it does |
|---|---|
| Head | equipment picker (search across the normalised DB, filter by kind), engine+database status, build JSON copy, clear config |
| Toolbar | item rank, Mastery rank (with the capacity floor it implies), Catalyst/Reactor, Exilus adapter, **Forma readout** (how many slots this config rewrites vs the item), Config A/B/C tabs + duplicate, live capacity (used / total / over-capacity bar) |
| Slot grid | 8 normal slots + aura/stance/exilus where the item has them, each showing the mod, its rank, the adjusted drain and the slot polarity; click a slot for rank + polarity controls |
| Mod library | search (name or effect text), filters for slot class, polarity, refusals and installed state, sorts, per-row name/polarity/drain/rank/flags, refusal counts; click installs into the focused slot, drag installs anywhere legal |
| Stat panel | grouped stats per equipment type with before/after against the unmodded baseline, "N values · M with a trace", click a stat for the engine's own trace |
| Damage + elements | the engine's damage split as a bar, the composition rows (which mods built which type), combined elements, DPS with its assumptions, crit/status notes |
| Capacity detail | how the total was built (rank, catalyst, Mastery floor, aura/stance bonus) and what each slot was charged, rule by rule |
| Validation | every error/warning the engine returned, with its own code, field and mod |
| Unsupported | refusals on the build and in the library, each naming the mechanic |

Interaction rules the page follows:

* **Drag and click are both first-class.** Drag a library row onto a slot (legal targets
  glow, illegal ones are refused visibly), drag an installed mod to another slot (move, or
  swap) or onto the library card to remove it. Keyboard: `/` focuses the library search,
  arrows + Enter install, `1`-`8` focus slots, `a`/`s`/`e` the aura/stance/exilus slots,
  `Delete` clears the focused slot, `Escape` lets go.
* **Before/after without commitment.** Hovering or dragging a mod asks the server
  `/api/planner/preview` for the hypothetical build and shows the deltas; nothing changes
  until the drop.
* **Everything is persisted locally** under one versioned key (`wfm.planner.v1`): equipment,
  all three configs (slots, ranks, polarities), catalyst, exilus, Mastery rank and the
  active config. A payload with an unknown version or shape is ignored and rewritten instead
  of half-applied.
* **Refusals are never hidden.** An installed mod with mechanics the engine does not model
  carries a "N not calculated" chip in its slot; clicking it opens the same card the library
  shows, listing which stats and why.

### The planner API

`server.py` exposes the engine under `/api/planner/*` (thin joins onto `builds/api.py` —
no math lives in the server):

| Route | Answers |
|---|---|
| `GET  /api/planner/meta` | engine version, database provenance + counts, supported triggers, kinds, polarities |
| `GET  /api/planner/equipment?q=&kind=&limit=` | equipment search, ranked (exact name first), one normalised row each |
| `GET  /api/planner/equipment/<key>` | one item: its row, its slot layout and its default polarities |
| `GET  /api/planner/mods?equipment=<key>&q=&shadowed=` | the mod rows that install on that item, each with drain, rank range, flags and refusal counts; `shadowed=1` also lists the catalog's shadow copies |
| `POST /api/planner/compute` | `{build}` → the full `api.compute` answer |
| `POST /api/planner/preview` | `{build, next}` → two real engine runs and the deltas; both sides are complete builds |
| `POST /api/planner/explain` | `{build, stat}` → the trace for one stat |
| `GET  /api/planner/unsupported` | the refusal registry |

Unknown `/api/planner/*` routes answer `404 {"ok": false, "error": "unknown planner route"}`
instead of falling through to static serving.

### Gates for the page

```bash
python design/_planner/build_planner_gate.py     # 20-step browser workflow (puppeteer-core)
python -m pytest tests/test_planner_api.py tests/test_planner_page.py -q
```

The browser gate drives the real page against the real server and the real database, and
compares every number it reads in the DOM against `/api/planner/compute` for the very same
build — so a page that invented a stat fails the gate. It also pins two Phase 1 values
(Braton Prime 35 base damage; Serration R10 → 92.75) so engine drift fails loudly, and
covers capacity, polarity/Forma, rank changes, element combinations by slot order, configs
A/B/C, reload persistence, a foreign storage payload, five viewport widths, the keyboard
path and all three drag flows. Report: `design/_planner/build-planner-report.md`, raw
numbers: `design/_planner/build-planner-raw.json`.

## Running the engine

```bash
python builds/ingest.py            # build data/build_data.json (once, or to refresh)
python builds/ingest.py --refresh-mods   # also re-fetch the WFCD mod catalog
python builds/ingest.py --no-fetch       # offline: read the local AlecaFrame mirror

python builds/debug.py summary                     # what the database holds
python builds/debug.py sources                     # where every number comes from
python builds/debug.py unsupported                 # what the engine refuses to compute
python builds/debug.py mod "Serration"             # a mod's parsed per-rank effects
python builds/debug.py equipment "Excalibur"       # a normalised equipment row
python builds/debug.py stat "Braton Prime" --mod Serration:10 --mod "Hellfire":5 \
        --mod "Cryo Rounds":5 --orokin --match-polarity
python builds/debug.py explain "Excalibur" --mod "Vitality":10 --stat health
python builds/debug.py explain "Braton Prime" --mod Serration:10 --stat damage --orokin
python builds/debug.py selftest                    # every module's wiki-value checks

python -m pytest tests/test_builds_engine.py -q    # the same checks, in CI
```

`data/build_data.json` is generated, not committed: a fresh clone runs the ingest once.
The debug surface accepts a mod by id, slug *or* name (`NAME:RANK`, `NAME:RANK@SLOT` for
aura/stance/exilus, `--match-polarity` to polarize each slot to its mod as a player
would with Forma).

## Architecture

| Module | Owns |
|---|---|
| `builds/schema.py` | The canonical vocabulary: equipment kinds, slot kinds, polarities, damage types, element combinations, stat ids, and the Warframe rank-up tables |
| `builds/effects.py` | WFCD stat strings → structured per-rank effect tables (which stat a line means, what it stacks as, and the refusal list) |
| `builds/capacity.py` | Mod capacity: rank capacity, Orokin doubling, Mastery minimum capacity, drain, polarity rules, aura/stance bonuses, Exilus |
| `builds/elements.py` | Elemental combination: mod-slot order, innate elements, the six combined types |
| `builds/weapons.py` | Weapon math: damage, crit tiers, status, multishot, fire rate, reload, DPS, faction multiplier, quantization |
| `builds/warframes.py` | Frame math: rank-scaled pools, armour, sprint speed, the four ability stats with caps and floors |
| `builds/validation.py` | Structured build validation (errors + warnings, never an exception) |
| `builds/unsupported.py` | The registry of mechanics the engine refuses to fake, with reasons and target phases |
| `builds/trace.py` | The trace primitives every stat returns: base, each modifier with its source/mod/rank, the final value |
| `builds/ingest.py` | Sources → `data/build_data.json` (normalisation, provenance, atomic write, `--selftest`) |
| `builds/data.py` | Loading + lookups (by id, slug, name; variant-aware) |
| `builds/api.py` | The one entry point: `compute(build)`, `explain(computed, stat)`, `compare(a, b)` |
| `builds/debug.py` | The developer surface listed above |

Design rules that the code follows throughout:

* **Identity is DE's `uniqueName`** — what the save file, the WFCD catalog and the local
  caches all join on. `slug` (warframe.market) rides along for market joins only.
* **Everything is a trace.** Every stat is returned as `{base, modifiers[], final}` so a
  UI can render "why" without re-deriving anything, and `api.compare` can diff two builds
  stat by stat with the delta.
* **Nothing is silently approximated.** A mechanic the engine cannot compute produces a
  marker `{"supported": false, "code": ..., "reason": ...}` and the registry
  (`unsupported.list_all()`) carries the same code with a phase. A test asserts that no
  refusal can ship unnamed.

## What Phase 1 computes

* **Capacity**: rank capacity, Orokin Reactor/Catalyst doubling, the Mastery minimum
  capacity (`15 + 1 per 2 MR`, `+1 per Legendary Rank` after 30 — the wiki's one worked
  example shows the floor undoubled by a supercharger, so this engine leaves it
  undoubled and flags `floored_by_mastery` when the floor decided the total), drain =
  base + rank, matching polarity (halved, rounded up), mismatched (+25%, rounded
  mathematically), vacant/universal/Umbra slots, aura & stance bonuses (matching doubled,
  mismatched 80%), Exilus slots, and per-slot traces of every adjustment.
* **Mods**: per-rank effect tables straight from the export (so partial ranks are exact,
  not interpolated), progression reporting (linear/non-linear), classification flags
  (Primed/Umbral/Galvanized/Augment/Aura/Stance/Exilus/set), compatibility, and
  slot-class validation.
* **Weapons**: physical + elemental damage in the wiki's order, element combination by mod
  placement with innate-element rules, critical chance/multiplier with multi-tier
  expectation above 100%, status chance and expected procs per shot (per projectile),
  multishot (deterministic + expected), fire rate, magazine, reload time, burst and
  sustained DPS for Auto/Semi/Held/Duplex triggers, the faction multiplier as a separate
  traced factor, and the game's 1/32 damage quantization on request.
* **Warframes**: rank-scaled Health/Shield/Energy, Armour, sprint speed, and the four
  ability stats — with the efficiency display cap (175%), the energy-cost floor (25%) and
  the documented rank-up exceptions (Inaros, Hildryn, Nidus, …).
* **Infrastructure**: calculation traces, structured validation, check-before/after
  comparison, data provenance, schema versioning, deterministic ingest.

## The database is reproducible

`python builds/ingest.py` writes one file, and running it again over unchanged sources
reproduces that file byte-for-byte: the document carries a `content_hash` over everything
except the fetch/generation timestamps, and when the hash matches the previous run the old
stamps are carried over instead of being refreshed. So two runs can be compared with
`md5sum data/build_data.json` (or `python builds/debug.py summary`), and a *changed* hash
means a real change in the data — a new mod, a moved number — not a new clock reading.

## What it refuses (and why that is the point)

`python builds/debug.py unsupported` prints the current list; the registry carries a
reason and target phase for each. Highlights:

* **Conditional effects** — Galvanized stacks, "On Kill"/"On Hit" riders, buff timers.
  A Galvanized mod's *unconditional* value is applied; the rider is refused by name.
* **Set bonuses** (Umbral/Augur/…), **Rivens**, **Incarnon evolutions**, **arcanes**.
* **Status effects themselves** — Viral stacks, Heat ticks, Slash bleeds, proc weighting.
* **Melee** — combo counter, heavy attacks, stance multipliers, Condition Overload.
* **Enemies** — armour, damage-type modifiers against health/shields/armour, armour strip.
* **Frames** — per-ability formulas, Helminth, Archon Shards, companion/squad buffs.
* **Exotic triggers** — Charge/Burst/Continuous effective fire rates (DPS is withheld
  rather than guessed).

On the current database (777 equipment rows, 1809 mods) 1071 mods carry at least one stat
the engine does not model and 416 carry conditional effects — those are *named* refusals
that travel with the build, not silent zeroes.

## Data sources

| Data | Source | Notes |
|---|---|---|
| Equipment stats, damage, crit/status, fire rate, polarities, mastery req | WFCD `warframe-items` (DE Public Export projection) | Rank-0 base values exactly as the export ships them; rank-30 values are derived by the engine from documented rank-up rules |
| Mod catalog + per-rank stat tables | WFCD `Mods.json` (the repo's `data/wfcd_mods_cache.json`, refreshed by `--refresh-mods`) | Same cache `scripts/mod_cards.py` uses |
| Market slug | warframe.market item list (`data/wfm_items_v2.json`, `gameRef → slug`) | Market joins only — never identity, never math |
| Formulas | WARFRAME Wiki: Damage, Damage/Calculation, Calculating Bonuses, Critical Hit, Status Effect, Multishot, Reload, Mods, Polarity, Aura, Warframes, Abilities | Every formula in the engines' docstrings names its page |

Two data traps this project hit and handles explicitly:

* **The catalog ships copies of real mods under their names.** Three kinds, handled three
  ways. The *Beginner* copy is a real in-game card (Serration at max rank 3): the ingester
  renames it to the wiki's own name ("Flawed Serration") and flags it `is_flawed`. The
  *Intermediate* and *Expert* rows are internal leftovers that exist in no player's
  inventory (a rank-10 "Hellfire" at +275%): they are flagged `shadowed` with
  `shadowed_by`, kept out of the library behind a count with a one-click reveal, badged
  "not in game" when revealed, and never slotted as the real card. Name lookups prefer the
  standard copy, so "Serration" always resolves to the rank-10 real mod. Grounded in the
  wiki's `Module:Mods/data` internal names, not guessed.
* **The AlecaFrame mirror is an older snapshot.** Compared against today's WFCD export,
  1794 of 1809 mod stat tables are identical; 11 differ in wording only (the mirror still
  says "On Headshot" where the current game says "On Weak Point Hit"), one augment was
  reworked (Gaseous Quake) and 4 mods are missing. It is used only as the offline
  fallback (`--no-fetch`), never as the primary source.
* **Two traps in the export's own fields.** `isAugment` flags 400 mods where only 217 are
  augment cards (it marks Adaptation, Agility Drift, … as augments) — this engine
  classifies an augment by the card's own "<Ability> Augment:" text and keeps the
  export's value as provenance (`augment_export`). And mod values are the *current* ones:
  Vitality and Steel Fiber are +100% today (they were +440% / +110% before Update 27.2),
  so any number remembered from an older build guide is wrong.

## The build representation

```json
{
  "config": "A",
  "equipment_id": "/Lotus/Weapons/Tenno/Rifle/BratonPrime",
  "equipment_rank": 30,
  "orokin": true,
  "forma_count": 2,
  "mastery_rank": 30,
  "slots": [
    {"kind": "normal", "index": 0, "polarity": "madurai",
     "mod": {"id": "/Lotus/Upgrades/Mods/Rifle/WeaponDamageAmountMod", "rank": 10}},
    {"kind": "aura", "polarity": "naramon", "mod": {"id": "…", "rank": 5}},
    {"kind": "stance", "polarity": "naramon", "mod": null},
    {"kind": "exilus", "polarity": null, "unlocked": true, "mod": null}
  ]
}
```

`api.compute(build, db)` returns:

```json
{
  "ok": true,
  "validation": {"ok": true, "errors": [], "warnings": []},
  "capacity": {"capacity": {...}, "drain": {"per_slot": [...], "total": 41, "remaining": 19}},
  "result": {"stats": {...}, "damage": {...}, "crit": {...}, "status": {...},
             "dps": {...}, "traces": {"health": {...}, "critical_chance": {...}}},
  "baseline": {"stats": {...}},
  "unsupported": [{"supported": false, "code": "incarnon", "reason": "…"}]
}
```

`baseline` is the same equipment with no mods, so a UI can render "before → after" for
every stat without a second call; `api.compare(build_a, build_b, db)` does it in one step
with deltas.

## Verification

The math is checked against values documented on the wiki, in two places:

```bash
python builds/debug.py selftest        # 122 checks across the six modules
python -m pytest tests/test_builds_engine.py -q
```

Examples of the pinned values: Serration R10 takes a 35-damage Braton Prime to 92.75;
Hellfire + Cryo Rounds produce 166.95 Blast; Point Strike R5 makes 12% → 30% crit; Vital
Sense R5 makes a ×2.0 crit multiplier ×4.4; Split Chamber R5 gives 1.9 multishot;
Serration's 14 drain costs 7 in a Madurai slot and 18 in a Naramon one; Excalibur is
370 Health at rank 30 and 740 with max Vitality (+100% Health — the export's
`isAugment` and pre-rework values are both traps this engine does not fall into); Inaros
is 2310 Health and Hildryn 1780 Shields at rank 30; Nidus is 775/450 with +15% Ability
Strength; efficiency above 175% still floors energy cost at 25%.

## Roadmap (what the engine deliberately leaves out)

* **Engine mechanics still refused by name** — conditional/stacking effects (Galvanized,
  "On Kill"), set bonuses, status effect modelling (bleed/heat/viral), proc weighting,
  melee combo + heavy attacks + stances, Incarnon, exotic triggers, enemy armour and
  damage-type modifiers. `python builds/debug.py unsupported` is the live list, and the
  planner page shows the same refusals on any build it displays.
* **Per-ability formulas** — augments, Helminth, Archon Shards, companion and squad buffs.
* **Later** — Rivens, primers, full fight simulation.
* **Planner UI, deliberately not in Phase 2** — auto-import of the player's own builds,
  community build scraping, "improve this build", upgrade recommendations, build popularity,
  market price integration, buy-missing-mod flows, badges, and AI-generated builds. The page
  compares builds and previews deltas already, which is the foundation those features need.
