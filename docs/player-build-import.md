# Player build import — what WFM can actually prove

Phase 3 reads the player's **current in-game loadout** from local files only and imports it
read-only. This note is the audit that decided what is importable: every field below was verified
against the real save on this machine on 2026-09-29, not assumed from documentation.

The vocabulary is deliberately modest: **`observed`** means the save states the value (not that the
game's live state has been confirmed), **`derived`** means computed under the rule written next to
it, **`unknown`** means no local source can establish it. An absent field is never read as a zero.

**The rule for everything in this file: unknown is better than wrong.** A field is imported with a
provenance label (`observed` / `derived` / `unknown`), and a field this project cannot prove is
reported as unknown rather than defaulted — never `0`, never "max rank", never Config A.

## Sources inspected

| Source | What it is | Verdict |
| --- | --- | --- |
| `%LOCALAPPDATA%\AlecaFrame\lastData.dat` (648 KB) | The game's own save dump, AES-128-CBC encrypted, written by AlecaFrame. `scripts/saveio.py` decrypts it (fixed key/IV, no compression) and normalises `InventoryJson` to the classic flat shape. | **The Phase 3 source.** Carries the current loadout, every owned item, and every installed mod. |
| `%LOCALAPPDATA%\AlecaFrame\deltas.dat` | Incremental deltas since the last full write. | Not used: partial by construction, no loadout sections. |
| `%LOCALAPPDATA%\AlecaFrame\cachedData\**` | AlecaFrame's own item catalogues (WFCD data). | Used only to cross-check names; carries **no** player state and **no** XP/rank tables. |
| `data/lastData.dec.json` (repo) | The normalised save `scripts/refresh.py` writes for the inventory pipeline. | Available, but Phase 3 reads the save through the same `saveio` path so the snapshot is independent of when refresh last ran. |
| `data/owned.json`, `data/player.json` | WFM's derived inventory/account stores. | Historical inventory, not the current loadout; no config or mod-slot data. |
| EE.log / process memory | — | **Not used.** No process scraping, no privileges, nothing read that AlecaFrame does not already write. |

`data/*` is gitignored: the imported snapshot stays on this machine (see Privacy).

## Where the current loadout actually lives

The save has 182 sections. Two matter:

- **`LoadOutPresets`** — one preset per type: `NORMAL`, `SENTINEL`, `ARCHWING`, `NORMAL_PVP`,
  `LUNARO`, `GEAR`, `DATAKNIFE`, `KDRIVE`, `OPERATOR`, `OPERATOR_ADULT`, `DRIFTER`, `MECH`.
  Each preset is a list of entries; **the list has exactly one entry per type**, so
  `LoadOutPresets.NORMAL[0]` is the current loadout's only candidate. Keys inside a preset:
  `s` = suit, `l` = long gun (primary), `p` = pistol (secondary), `m` = melee, `h` = arch-gun;
  the sentinel preset uses `s` (companion), `l` (its weapon), `b` (second companion slot).
  Each entry is `{ItemId: {$oid}, mod: N, cus: N, hide?: bool}` — **`mod` is the active config
  index (0/1/2 = A/B/C)**, and `ItemId` joins to the owned item in `Suits` / `LongGuns` / `Pistols`
  / `Melee` / `Sentinels` / `SentinelWeapons` / `SpaceSuits` / `MechSuits`.
- **Owned items** — each entry is `{ItemType, Configs, XP, Polarized, Polarity, Features,
  UpgradeVer, ItemId}` where `ItemType` is the game path (e.g.
  `/Lotus/Powersuits/Runner/GaussPrime`). `Configs` is a **list of three configs** (A/B/C), each
  with an `Upgrades` array.

`CurrentLoadOutIds` looks like the active loadout but is **stale**: all eleven slots hold
placeholder oids (`5434404607c56f8c868d2b0f`, `000000000000000000000001`) that belong to no owned
item, and none of them appear in any preset. It is recorded as unusable and never read.

## Field-by-field: what is importable

### Verified (directly present in the save)

| Field | Where | Notes |
| --- | --- | --- |
| Equipment identity per category | preset entry `ItemId` → `Configs`-owning item's `ItemType` | Exact game path; joins the Phase 1 catalogue by `uniqueName`, no fuzzy matching. 775 of 777 owned items map; the two Archwing jetpacks are logged as unknown items. |
| Active config index | preset entry `mod` | 0/1/2. |
| All three configs | item `Configs[0..2]` | Each config is imported independently (Phase 3 §7: A/B/C is genuinely available). |
| Installed mods **in slot order** | `Configs[i].Upgrades[]` | The array index **is** the slot index — verified against the observed layouts (a Warframe's aura lands at 8, a melee's stance at 8, exilus at 9/8, arcanes at 10-11/9). Empty slots are blank entries; a config with no `Upgrades` key at all is "no mods installed", not a failure. |
| Mod identity | copy id (or bare path) → top-level `Upgrades[].ItemType` | `ItemType` is the same `uniqueName` namespace the engine uses. 875 installed-mod entries join; 21 entries are bare paths or copies missing from `Upgrades` and are imported with rank unknown. |
| **Installed mod rank** | `Upgrades[].UpgradeFingerprint` = `{"lvl": N}` | Exact, per installed copy. This is what Phase 4 will need. |
| Slot polarities | item `Polarity: [{Slot, Value}]` | Per slot, only the slots that have one. `AP_ATTACK`→madurai, `AP_DEFENSE`→vazarin, `AP_TACTIC`→naramon, `AP_POWER`→zenurik, `AP_UNIVERSAL`→universal. Unlisted slot = no polarity. |
| Source freshness | `lastData.dat` mtime + `LastInventorySync` | Drives "last seen N minutes ago". |

### Derived (deterministically, from verified data)

| Field | Rule | Why it is safe |
| --- | --- | --- |
| Forma count | item `Polarized` | The save's own counter of applied Forma. Slot-by-slot Forma *history* is **not** reconstructed from the final polarity map. |
| Equipment rank (only the max-rank case) | item `XP` ≥ 900,000 ⇒ rank = the catalogue's `max_rank`, but only for items whose `max_rank` ≤ 30 | 900,000 is the game's rank-30 requirement; XP is monotonic, so XP above it cannot be below rank 30. Items with a 40 cap (Kuva/Tenet/Necramech) are left unknown because their curve is not in any local file. Every other XP value is left unknown — **no rank is ever maxed or guessed**. |
| Current-preset identity | `LoadOutPresets.NORMAL[0]` | The list carries exactly one preset per type, so there is no other candidate. Recorded as derived because the save holds no explicit "active preset" index. |
| Category → engine slot mapping | index table below | Matches the engine's own slot vocabulary. |

### Unknown (not available from any local source)

| Field | Why |
| --- | --- |
| Catalyst / Reactor, Exilus adapter, any adapter unlock | Item `Features` is a bitmask (observed values 1, 3, 32, 33, 35, 547) whose bit semantics are **not documented in any file on this machine** — the extension's code does not decode it and no local table does either. The raw number is imported as `features_bitmask` (verified) and **never interpreted**. |
| Per-slot polarity history / which slot a Forma changed | Only the final polarity map and a total count exist. |
| Actual current equipment rank below max rank | No XP→rank curve is available locally. |
| Which preset is "active" for non-NORMAL types (archwing, mech, operator) | Only the single-preset-per-type argument applies; the same rule is used, recorded as derived. |
| Companion mod placement | The engine models companions as `normal` + `exilus`; the save's sentinel layout (8 mod slots plus precept slots) does not have a verified index mapping, so companion mods are imported as an **unordered set** with slot order unknown. |
| Arcanes (Warframe and weapon) | Not modelled by the Phase 1 engine; imported as unsupported entries with their identity, never as mods. |
| Archwing / Mech / K-Drive equipment | Not in the Phase 1 catalogue: reported as unknown items. |

## Slot index → engine slot (verified against the live save)

| Category | Save indices | Engine slot | Evidence |
| --- | --- | --- | --- |
| Warframe | 0-7 | `normal` | 12-entry configs, aura at 8 |
| Warframe | 8 | `aura` | `Energy Siphon` (an aura) at index 8 |
| Warframe | 9 | `exilus` | exilus mods at 9; blank when unused |
| Warframe | 10-11 | *unsupported (arcane)* | `CosmeticEnhancers/**` at 10-11 |
| Primary / Secondary | 0-7 | `normal` | 8 or 10 entries |
| Primary / Secondary | 8 | `exilus` | `Terminal Velocity` at index 8 of a 10-entry config |
| Primary / Secondary | 9 | *unsupported (arcane)* | `CosmeticEnhancers/Offensive/*` |
| Melee | 0-7 | `normal` | 9 or 11 entries |
| Melee | 8 | `stance` | stance mod at 8 |
| Melee | 9 | `exilus` | |
| Melee | 10 | *unsupported (arcane)* | |
| Sentinel / Sentinel weapon | 0-7 | *unordered* | no verified layout; listed, order unknown |

## What the import produces

`ImportedBuild` (see `builds/player_import.py`) carries, per category: `source`,
`source_timestamp`, `imported_timestamp`, `equipment` (slug + uniqueName), `equipment_rank`
(rank or null), `config` (the save's index or null = unknown), `configs` (each an ordered slot list
with `kind`, `index`, `mod`, `mod_rank`, `polarity`, or an explicit `unsupported` marker),
`forma_count`, `features_bitmask`, `provenance` (one label per field), `unknown_fields` (the names
of everything left unknown) and `unmapped` (any game identifier that did not resolve, kept verbatim
so it can be added later).

Cloning (`clone_to_planner`) translates only what is known into a planner storage document and
returns the same `unknown_fields` list, which the UI shows beside the clone button. The imported
snapshot is never mutated by the planner, and a re-import never overwrites an existing planner
config unless the user asks for it.

## Freshness and refresh

The snapshot records `source`, `source_timestamp` (save mtime), `imported_timestamp`, and a
`stale` flag (source older than 24 h). Refresh re-reads the save, updates the snapshot and leaves
planner clones untouched. No polling, no watch: the read happens on request and the parsed result
is cached in `data/current_loadout.json` (`WFM_PLAYER_SAVE` / `WFM_PLAYER_CACHE` override both
paths, which is how the tests and the browser gate run against fixtures).

## Privacy

Everything here is local player data. It is read from disk, cached under `data/` (gitignored) and
served on `127.0.0.1` only. The import performs no external API call and the app has no telemetry;
the application server binds loopback only. (Said precisely: nothing about an import leaves the
machine - not "the machine is provably airtight".) Shared-data collection is a later, opt-in phase and is
not implemented here.

## How it is wired

```
AlecaFrame/lastData.dat
        │  scripts/saveio.py             (decrypt; unchanged since Phase 1)
        ▼
scripts/player_loadout.py                (read, cache, name every failure mode)
        │  builds/player_import.py       (pure mapping: save + catalogue → snapshot / clone)
        ▼
server.py                                GET  /api/planner/current
                                         POST /api/planner/current/refresh
                                         POST /api/planner/clone   {category, config, mastery_rank}
        │
        ▼
static/planner-current.js                the Current Loadout card (read-only)
```

* **The reader never invents a state.** `load()` returns one of `ok`, `missing`, `locked`,
  `malformed`, `no_build_data`, each with a plain message and, where useful, the path it looked for.
  A damaged save never renders as an empty loadout.
* **The snapshot is server-side.** The page can read it and ask for a clone; it cannot write it.
  `clone_to_planner` deep-copies first, so a clone can never alias the snapshot.
* **The clone goes through the page's own validator.** `POST /api/planner/clone` returns a storage
  v1 document; the page puts it through `cleanV1` (accept-whole or reject-whole) and stores it with
  `WFMPlanner.adopt`. If the page rejected it, the card says so instead of half-applying it.
* **Unknown fields are left out, not filled in.** A clone carries no `orokin` and no
  `exilus_unlocked` when the source does not record them; the card lists them as unknown and the
  engine's answer is shown with the assumption stated on screen ("Capacity assumes no Catalyst or
  Exilus: neither is in the source."). A slot with no rank in the source keeps the field absent
  (the planner reads that as the mod's base value) and the count is reported.
* **A polarity the page cannot store is not written.** The storage vocabulary accepts
  madurai/naramon/vazarin/zenurik/umbral/penjaga/unairu only, so an `AP_UNIVERSAL` slot is counted
  and reported rather than smuggled in as junk.
* **The engine keeps the last word.** The card computes the imported build through the ordinary
  `/api/planner/compute` route and prints the engine's validation, refusals and drain verbatim. When
  a build overflows only because the source never recorded a Catalyst, the card asks the engine the
  other question too — "Fits with a Catalyst installed" / "Still short with a Catalyst ·
  <code>" — and labels it as the hypothesis it is.
* **Freshness is a claim about the source, not the import.** A save older than 24 h reads "Last seen
  N days ago · current loadout could not be verified as live" and the card repeats the warning,
  rather than presenting stale data as live.

The importer's own tests live in `tests/test_player_import.py` (fixtures in
`design/_planner/fixtures/`: a full synthetic save, an empty one, a truncated one — all ids checked
against the ingested catalogue when the fixtures are built). The browser gate's `current` section
drives the real card against the full fixture.
