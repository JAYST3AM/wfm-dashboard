# WFM Trader — Build Planner (engine)

A build planner that answers **"what does this build actually produce?"** for Warframe
equipment, and can always answer **"why is this number this number?"**

Phase 1 (this document) is the **calculation and data foundation**: a stdlib-only engine
under `builds/` that ingests authoritative data, validates a build, computes the stats
the arsenal shows, and *names every mechanic it refuses to fake*. No UI yet — the
intended consumer is the existing dashboard plus a future build-planner page.

## Running it

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

* **Starter mod copies share display names.** The catalog ships Beginner/Intermediate
  versions of several mods (Serration exists at max rank 3, 5 *and* 10). Rows carry a
  `variant` field and name lookups prefer the standard copy — otherwise "Serration"
  silently resolves to the 3-rank beginner mod.
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

## Roadmap (what Phase 1 deliberately leaves out)

* **Phase 2** — conditional/stacking effects (Galvanized, "On Kill"), set bonuses, status
  effect modelling (bleed/heat/viral), proc weighting, melee combo + heavy attacks +
  stances, Incarnon, exotic triggers, enemy armour and damage-type modifiers.
* **Phase 3** — per-ability formulas, augments, Helminth, Archon Shards, companion and
  squad buffs.
* **Later** — Rivens, primers, full fight simulation, and the UI page (the engine is
  scalar and side-effect free so the UI only has to render `result` and `traces`).
