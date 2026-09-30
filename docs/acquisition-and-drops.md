# Where an item comes from

A drop answer is only useful if a player can travel to it. `Venus - Falling Glory · Skirmish ·
Rotation A · 13.33%` is not such an answer: Falling Glory is a **Railjack** node in **Venus
Proxima**, and there is no Falling Glory on the Venus Star Chart. The answer is
`Railjack → Venus Proxima → Falling Glory → Skirmish · rotation A · 13.33%`.

The rule this pipeline follows:

> Never flatten a game's location hierarchy just because the source dataset does.

The official drop table groups a Railjack node under the planet it orbits (`Venus/Falling Glory
(Skirmish)`), because that is how the table's own keys are built. Reading the first segment as the
location is what produces a confident, useless answer. The hierarchy is therefore resolved from the
game's own region data and stored structurally, not parsed out of a label at render time.

## What WFM trusts, in order

| source | what it is trusted for | where it is cached |
| --- | --- | --- |
| Digital Extremes drop tables (WFCD mirror of DE's data) | the drop **contents**, the rotation, and the **chance** — `missionRewards.json`, `relics.json`, `blueprintLocations.json`, the bounty/sortie/syndicate tables | `data/dropdata/` |
| Digital Extremes public export (calamity-inc mirror) | the **navigation hierarchy**: one entry per region with its `missionType`, its system key and its node name, plus the English dictionary for both | `data/dropdata/export/` |
| The Warframe Wiki | explaining an acquisition the drop tables are silent on, quoted verbatim with its page URL, and the update an item arrived in. Never a chance. | `data/dropdata/wiki/` |
| Curated hub labels (this repo) | the place an open-world reward table belongs to (Cetus → Plains of Eidolon, Solaris → Orb Vallis, Deimos → Cambion Drift, Hex → Höllvania). The export carries no region entry for an open-world landscape, so these are named by hand and listed in `scripts/obtain_index.py` (`HUB_SOURCES`). | — |

A community estimate never replaces an official chance. If the tables are silent, the record says
so; the wiki line is labelled as a wiki line.

## The pipeline

```
DE drop tables (cached)        DE export: ExportRegions.json + dict.en.json (cached)
        │                                        │
        ▼                                        ▼
scripts/obtain_index.py  ──────►  scripts/acquisition_hierarchy.py
   builds data/obtain_index.json   resolves node → system / region / node
        │                          (missionType decides Railjack; system key names the proxima)
        ▼
scripts/collection_log.py  →  static/collection_log.json  →  static/collection.js (the hover card)
```

The fix lives in the **earliest sensible layer**: `acquisition_hierarchy.py` resolves once, during
the build, and every consumer — the index, the collection store, the hover card — reads the
resolved fields. No page parses a location out of a label.

## The record

```json
{"planet": "Venus", "node": "Falling Glory", "mode": "Skirmish", "rotation": "A",
 "chance": 13.33, "rarity": "Uncommon", "path": "Venus/Falling Glory",
 "system": "Railjack", "region": "Venus Proxima",
 "hierarchy": "Railjack → Venus Proxima → Falling Glory",
 "reward_source": "mission completion",
 "provenance": {"chance": "missionRewards.json (DE drop table)",
                "hierarchy": "game export: /Lotus/Language/Locations/Venus_SPACE",
                "node_match": "exact"}}
```

- `planet` is the drop table's own label. It is **provenance**, never the location.
- `system` / `region` / `hierarchy` come from the game's export.
- `reward_source` says **how** an item comes out: mission completion, a Railjack or sabotage
  **cache**, a bonus reward table, a bounty stage, a vendor, an enemy drop, a relic reward.
- `variant` marks a reward-table variant of the same node (`Falling Glory (Caches)` is Falling Glory
  its cache table), so two tables are never merged into one row.
- `provenance` keeps the source identity separate from the display text, so a source refresh does
  not require a UI change. `node_match: case-insensitive` records that DE's two datasets spell a
  node differently (`Kala-Azar` vs `Kala-azar`).

## Navigation systems

| system | how it is decided | example |
| --- | --- | --- |
| Railjack | the export's `missionType` is `MT_RAILJACK`; the region is its system key (`Venus_SPACE`) | `Railjack → Venus Proxima → Falling Glory` |
| Star Chart | a region key under the Locations tree that is not one of the special families | `Star Chart → Mars → Tyana Pass` |
| Duviri | the Duviri region family | `Duviri → Endless: Tier 6` |
| Hollvania | the 1999 region family | `Hollvania → Höllvania → Solstice Square` |
| Zariman Ten Zero | the Zariman region family | `Zariman Ten Zero → Everview Arc` |
| Sanctuary Onslaught | the Sanctuary relay region | `Sanctuary Onslaught → Sanctuary → Sanctuary Onslaught` |
| Conclave | a PvP region (`MT_PVP`) | the Conclave map named after a Star Chart node |
| Open World | a bounty table with a curated hub label | `Open World → Plains of Eidolon (Earth) → Cetus bounty` |

The mode → `missionType` table is not hand-written: it is **voted from the export** at build time,
using only rows whose node is unambiguous and whose region matches the drop-table label
(`Survival → MT_SURVIVAL`, `Skirmish → MT_RAILJACK`, `Interception → MT_TERRITORY`). A mode the
export does not carry simply gets no entry, and matching falls back to the region check.

## Unknowns are marked, never guessed

Accuracy beats completeness. Four cases, each named in `unresolved` on the row:

| case | what the row shows |
| --- | --- |
| the node is not in the export (retired or renamed) | the system + region the drop-table label names, plus `node not in the game export (may be retired or renamed)` |
| the region exists but its system family is not one this module knows | the region text, with `navigation system not confirmed for this region` |
| the node name appears in more than one region | the best-scoring region, with the other candidates named |
| nothing at all is known | the drop-table label as it stands, with the reason |

A normal Star Chart planet is **never** inferred from a drop-table prefix.

## Numbers today

On the current data (435 drop-table mission rows): **346 nodes placed from the game's own export**,
**85 nodes named by the drop-table label and flagged unconfirmed**, and **4 rows whose navigation
system is not confirmed** (the Perita Rebellion tables). No row is left without a place at all.

## The regression, and how to check it

`scripts/obtain_index.py --selftest` checks the resolver's rules. `tests/test_acquisition_hierarchy.py`
holds the hermetic rules plus the real-data cases (which skip when the export is not cached, as on
CI). The end-to-end gate is:

```
python design/_acquisition/acquisition_gate.py --falsify
```

It reads the built index and the collection store and fails if a known Railjack node renders as its
drop-table planet, if a hierarchy loses its rotation or chance, if a source type renders without
enough to locate it, or if provenance disappears. `--falsify` then breaks the resolver three ways —
flattening the label, trusting the drop-table label as the region, and keeping the `(Caches)`/`(Extra)`
suffix — and requires the gate to catch each one. Ash Systems Blueprint is the named case: its row
must read `Railjack → Venus Proxima → Falling Glory` and must keep `rotation A` / `13.33%`.

## Known limitations

- **Retired and renamed nodes.** 85 rows name a node the game's current export does not list. They
  show the verified system and region and say the node itself is unconfirmed. Fixing them properly
  means a historical region list, which no official source publishes.
- **Open-world landscapes are labelled by hand.** The export has no region entry for the Plains of
  Eidolon or the Orb Vallis, so the four hub labels are curated in `HUB_SOURCES` rather than derived.
- **The Perita Rebellion** (4 rows) sits in a region family the export files under the Tau content;
  its navigation system is left unconfirmed rather than called the Star Chart.
- **Reward-table names on Duviri.** Several Duviri rows are reward tables rather than nodes
  (`Endless: Tier 1 (Hard)`); they are shown as the export names them, with the reward source
  saying they are circuit rewards.
- **The wiki line is prose.** Where the drop tables are silent, the card quotes the wiki's own
  acquisition sentence; it is not turned into a structured location.
