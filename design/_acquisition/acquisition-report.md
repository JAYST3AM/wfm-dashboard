# Acquisition accuracy cleanup — report

Repo `JAYST3AM/wfm-dashboard`, branch `main`, commits **`030d258`** (the hierarchy) and **`cb7df22`**
(every source type's locating field), both pushed; tree clean. Scope kept to the brief: no new phase,
no Build Planner combat maths touched, no Phase 5 work, no unrelated pages redesigned.

## 1. Root cause of the vague locations

The pipeline read the **first segment of DE's own drop-table key** as the location.
`data/dropdata/missionRewards.json` groups a Railjack node under the planet it orbits —
`missionRewards["Venus"]["Falling Glory"]`, gameMode `Skirmish` — because that is how the table is
keyed. `scripts/obtain_index.py` took that label as the planet, and `scripts/collection_log.py`
joined it to the node:

```python
where = ' - '.join([mission.get('planet'), mission.get('node')])   # "Venus - Falling Glory"
```

Falling Glory is a **Railjack** node in **Venus Proxima**. There is no Falling Glory on the Venus
Star Chart, so the card was confident and useless.

Two aggravating facts the audit confirmed:

- **Six planet labels hide a Proxima.** Venus, Earth, Saturn, Uranus, Neptune and Pluto each carry
  both Star Chart nodes and Railjack nodes under one label; only the `gameMode` separates them
  (`Skirmish`/`Volatile`/`Orphix` are Railjack-only). `Venus` alone: 33 node keys, 32 Railjack/Skirmish.
- **The label is the only place signal in the file.** No field in the drop table names a proxima, so
  the hierarchy cannot be produced from the drop table at all — it has to come from the game's own
  region data.

## 2. Files changed

| file | change |
| --- | --- |
| `scripts/acquisition_hierarchy.py` | **new (≈470 lines)** — resolves a drop-table row to system / region / node from the game's own export; `--fetch`, `--report`, `--coverage`, `--selftest` (14 checks) |
| `scripts/obtain_index.py` | wired the resolver into the mission build; record schema 1 → 2; context-carrying reward walker; key-name resolution; `syndicates.json` pass; crewship placement; selftest 31 → **41 checks** |
| `scripts/collection_log.py` | stopped joining planet + node; renders the hierarchy, the named table (level band / stage / key / objective), the caveat and provenance; up to three distinct source kinds per item |
| `static/collection.js`, `static/collection.html` | the card row's caveat span plus its style |
| `design/_acquisition/acquisition_gate.py` | **new** — 57 checks, `--falsify` with three breaks |
| `tests/test_acquisition_hierarchy.py` | **new** — hermetic rules in CI; real-data cases, incl. the named regression |
| `docs/acquisition-and-drops.md` | **new** — what WFM trusts, in what order, the record, the rendered line per source type, the limitations |
| `README.md` | docs row points at the new doc |
| `design/_acquisition/acquisition-audit.md`, `ash-systems-groundtruth.md`, `acquisition-gate-report.md` | audit + ground truth + gate output (read-only research and gate runs) |

Not changed: anything under `builds/` (the planner engine), the planner page, the trading session,
the relic/mastery/world pages.

## 3. Source hierarchy used

1. **DE's official drop tables** (the WFCD mirror already cached in `data/dropdata/`) — the only
   source for drop **contents, rotation and chance**. A community estimate never replaces a chance.
2. **DE's own public export** (the calamity-inc mirror, cached to `data/dropdata/export/`) — the
   **navigation hierarchy**: 354 region entries with `missionType`, system key and node name, plus
   the English dictionary. This is what turns `Venus/Falling Glory` into
   `Railjack → Venus Proxima → Falling Glory`.
3. **The Warframe Wiki** — only to explain an acquisition the tables are silent on (quoted verbatim
   with its page URL) and the update an item arrived in. Never a chance.
4. **Curated hub labels (this repo)** — the export carries no region entry for an open-world
   landscape or a hub, so the two curated maps are explicit and documented: `HUB_SOURCES` (bounty
   tables → Plains of Eidolon / Orb Vallis / Cambrion Drift / Zariman / Albrecht's Laboratories /
   Höllvania) and `VENDOR_HUBS` (16 standing stores → relays / Cetus / Fortuna / Necralisk /
   Chrysalith). Two vendors are deliberately **not** labelled: Kahl's Garrison and Operational Supply.

Derived rather than typed: the mode → `missionType` table is **voted from the export** at build time
(`Survival → MT_SURVIVAL`, `Skirmish → MT_RAILJACK`, `Interception → MT_TERRITORY`, 12 rows; modes
the export does not carry get no entry). Railjack is decided by `missionType == MT_RAILJACK` and the
region by the system key (`/Lotus/Language/Locations/Venus_SPACE` → *Venus Proxima*, checked in the
dictionary, not hard-coded).

## 4. Before / after

| item | before | after |
| --- | --- | --- |
| **Ash Systems Blueprint** | `Venus - Falling Glory · Skirmish · Rotation A · 13.33%` | `Railjack → Venus Proxima → Falling Glory` · `Defense · rotation A · 13.33%` |
| `Seer Blueprint` | `Mercury - Tolstoj · Assassination · 38.72%` | `Star Chart → Mercury → Tolstoj` · `Assassination · 38.72%` |
| the three other Ash Systems rows | `Venus - Luckless Expanse/Beacon Shield Ring/Bifrost Echo · Skirmish` | `Survival · rotation A · 13.33%`, `Volatile · 4.88%` (flat pool), `Exterminate · 4.88%` (flat pool) — each in `Railjack → Venus Proxima` |
| `Gara Chassis Blueprint` | `Cetus bounty: A · 7.52% - Rare` | `Open World → Plains of Eidolon (Earth) → Cetus bounty` · `Level 5 - 15 Cetus Bounty · Stage 2, Stage 3 of 4, and Stage 3 of 5 · rotation A · 7.52% · Rare` |
| `Mesa Neuroptics Blueprint` | `Key: C · 38.72% - Common` | `Star Chart → Eris → Mutalist Alad V Assassinate` · `Mutalist Alad V Assassinate · rotation C · 38.72%`, access *Mutalist Alad V Assassinate required* |
| a Duviri tier table | `Duviri - Endless: Tier 1 (Hard)` | `Duviri → Endless: Tier 1 (Hard)` · `circuit reward`, with the node-unconfirmed note |
| `Forma Blueprint` (transient) | `Transient: transientRewards` | `Star Chart → Transient` · `Hallowed Flame Mission Caches` |
| **vendor rows** | *none — the file produced no rows at all* | `Open World → Necralisk (Deimos) → Entrati` · `Acquaintance · 5000 standing` (1503 items) |
| `Lavan Glazio Mk Iii` | `Enemy: Taro Crewship (Level 51 - 100)` | `Railjack → Enemy: Taro Crewship (Level 51 - 100)`, with *which Proxima this crewship patrols is not confirmed* |
| `Narin` (Zariman) | — | `Zariman Ten Zero → Everview Arc` · `Void Flood · rotation C · 8.33%` |

Ash ground truth, verified independently (`design/_acquisition/ash-systems-groundtruth.md`): the drop
table lists Ash Systems Blueprint in **exactly four** Railjack rows — Bifrost Echo 4.88%, Beacon
Shield Ring 4.88% (flat pools), Luckless Expanse rotation A 13.33% and Falling Glory rotation A
13.33% — and every Ash part node is `MT_RAILJACK` in Venus/Neptune/Pluto Proxima. The wiki agrees per
part and per Proxima to the digit. The dedicated Railjack node keyed `AshRJMissionName` is
`CrewBattleNode560` = **The Kuva Wytch** in Uranus Proxima, and the drop table lists **no** Ash part
under it — so nothing in this change claims the parts come from there.

## 5. Edge cases tested

Each source type, with a case that would pass a shallow test and fail a real one:

- **Star Chart** — `Seer Blueprint` → `Star Chart → Mercury → Tolstoj`; and the Conclave trap:
  `Cytherean` exists both as a Venus Interception node and a Conclave map, and the mode decides.
- **Railjack / Proxima** — `Falling Glory` → Venus Proxima; `Vesper Strait` (Beacon Shield Ring) →
  Venus Proxima; a Veil Proxima row; the six planet labels that hide a proxima.
- **Reward-table variants** — `Falling Glory (Caches)` and `Bifrost Echo (Extra)`: the suffix is
  stripped to the node, the variant is kept, and the reward source says *railjack cache* /
  *sabotage cache* / *bonus reward table* as appropriate.
- **Bounty** — the level band and stage survive (`Level 10 - 30 Cetus Bounty · Stage 1 · rotation A`);
  Profit-Taker rows keep their phase (`Level 40 - 60 PROFIT-TAKER - PHASE 3 · Subsequent Completions`).
- **Duviri / Circuit** — a node row (`Duviri → The Circuit`) and a tier table
  (`Endless: Tier 1 (Hard)`, flagged unconfirmed) both render, without the region repeating the system.
- **Vendor** — `NecraLoid (Loid), Clearance Modus`, 3500 standing → `Open World → Necralisk (Deimos)
  → NecraLoid`; a relay store → `Star Chart → Relays → Cephalon Simaris`; an unknown store is
  **marked** (*where this vendor trades is not confirmed*) and given no system.
- **Quest / special** — `Mesa Neuroptics Blueprint` resolves its key as a node
  (`Star Chart → Eris → Mutalist Alad V Assassinate`); `Höllvania` (`Solstice Square`), `Sanctuary
  Onslaught`, `Zariman Ten Zero` and `Dark Refractory, Deimos` (system left unconfirmed) each
  render their own system.
- **Multi-source** — an item with a mission, an enemy, a bounty and a vendor shows up to three
  distinct source kinds, each labelled; a flat-pool Railjack row keeps `rotation: null` rather than
  inventing a rotation.
- **Retired / renamed nodes** — 85 rows (`Eris/Cyath`, `Phobos/Opik`, `Venus/Vesper`, …) keep the
  verified system and region and say the node is unconfirmed; the case-insensitive match is recorded
  where DE's two datasets differ only by case (`Kala-Azar` vs `Kala-azar`).

## 6. Exact test results

```
python scripts/obtain_index.py --selftest
    selftest: 41 ok, 0 failed            (was 31; one or more per source type)

python scripts/acquisition_hierarchy.py --selftest
    selftest: 14 checks, 0 failed

python design/_acquisition/acquisition_gate.py --falsify
    GATE PASS - 57 checks, 0 failed
    falsification: 3 of 3 breaks caught
      break flatten-the-label            -> ash/hierarchy-label, railjack/never-flat, hierarchy/every-row
      break trust-the-drop-table-label   -> ash/hierarchy-fields, ash/hierarchy-label, ash/not-the-drop-table-planet
      break keep-the-reward-table-suffix -> variant/present

python scripts/acquisition_hierarchy.py --coverage
    435 rows place 435 | placed 346 | node unconfirmed 85 | system unconfirmed 4
    Railjack 118 · Star Chart 272 · Duviri 16 · Hollvania 11 · Conclave 7 · Zariman Ten Zero 5 ·
    Sanctuary Onslaught 2 · unconfirmed 4

python -m pytest tests -q
    2108 passed, 5 skipped in 140.84s
```

The gate's mission-variant checks are the second half of the same finding: the drop table labels
**every** Railjack row `Skirmish`, including the Survival and Defense nodes. The export names the real
mission, so the row carries it (`mode_verified`), the drop table's word stays as provenance, 79
Railjack rows differ between the two sources, and the four Ash Systems rows read
Defense / Survival / Volatile / Exterminate — matching the independent ground truth exactly.

Gate output: `design/_acquisition/acquisition-gate-report.md`. Independent audit:
`design/_acquisition/acquisition-audit.md` (350/435 node keys placed by its looser matcher — it
normalises diacritics and hyphens, this resolver matches exactly or case-insensitively; the four-row
difference is the looser rule, not a disagreement). Ash ground truth:
`design/_acquisition/ash-systems-groundtruth.md`, with the wiki fetch and the export line references.

## 7. Acquisition types that still cannot be resolved confidently

1. **Hubs and open worlds are curated.** The export carries no region entry for Cetus, Fortuna, the
   Necralisk, the Chrysalith or the Plains/Orb Vallis/Cambion Drift, so those names come from the two
   curated maps in `scripts/obtain_index.py` and are documented as curated.
2. **Two vendors are unplaced.** Kahl's Garrison and Operational Supply: the row says the location is
   unconfirmed.
3. **85 nodes are absent from the live export.** 47 Star Chart keys (+13 `(Caches)` twins), 8 Conclave
   maps and 17 reward-table names. Whether each is retired or renamed is unverified; a historical
   region list is not published by anyone.
4. **An enemy drop has no mission.** No cached file maps an enemy to the node that spawns it, so a
   boss or mission enemy shows its name and odds and says the place is unknown. Railjack crewships
   are the exception (the enemy type proves the system). 90 of the 206 blueprint items are crewship
   drops whose level band encodes the Proxima tier — decoding tier → region is not verified anywhere.
5. **A relic says which relic, not where the relic drops.** Era, relic name and vaulted status are
   carried; fissure/vault location data is in no cached file.
6. **The Perita Rebellion** (4 rows, `Dark Refractory, Deimos`) sits in the Tau region family; its
   navigation system is left unconfirmed rather than called the Star Chart.
7. **Event and limited-time status is not modelled.** The drop table flags `isEvent` (Plague Star,
   Ghoul bounties, Antivirus Bounty) and hides event difficulty behind `(Extra)`/`(Hard)`; neither is
   represented in a record.
8. **The wiki lane is prose.** Where the tables are silent the card quotes the wiki's own acquisition
   sentence; it is not turned into a structured location.
