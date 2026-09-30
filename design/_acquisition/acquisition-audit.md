# Acquisition / drop-pipeline audit — read-only

**Report:** `design/_acquisition/acquisition-audit.md` (24 labels, 435 mission node keys, 13 non-mission source files).
**Nothing else was written or changed.** All numbers below were produced by read-only scripts over the files in the snapshot table.

## Snapshot audited (sha256, first 12)

| file | sha256 | note |
|---|---|---|
| `data/dropdata/missionRewards.json` | `992c80479af4` | 24 labels, 435 node keys (minified: the whole file is line 1, so rows are cited by JSON path) |
| `data/dropdata/export/ExportRegions.json` | `56baa9b44520` | 354 region entries, **all 354 have an English name** (0 skipped by `build_index`) |
| `data/dropdata/export/dict.en.json` | `ab82babcde2c` | 36 165 entries |
| `scripts/acquisition_hierarchy.py` | `57e7af2a3290` | **being edited during this audit** (hash changed 3×); behaviour quoted is this snapshot |
| `scripts/obtain_index.py` | `7d1e9dafd867` | `SCHEMA = 2` (obtain_index.py:91) |
| `scripts/collection_log.py` | `77af6804f259` | |
| `data/obtain_index.json` | `af7bd2e9faaf` | `generated 2026-09-30T04:58:01Z`, 3258 items |

Matcher rules used for every count below (stated, not inherited): a node key matches the export when the key, or the key minus a trailing ` (Caches)` / ` (Extra)`, equals an export display name exactly **or** case/diacritic/hyphen-insensitively (`NFKD`, drop combining marks, `-`/`_`/space → space, casefold). Placements resolved to `Venus/Falling Glory (Skirmish)` → `Railjack → Venus Proxima → Falling Glory` (verified: `python scripts/acquisition_hierarchy.py --report`).

**Headline:** 350 of 435 node keys (80.5%) place in the game's own export; **85 do not** — 17 are reward-table names, 8 are Conclave maps, 60 are nodes the live export no longer carries. The resolver assigns `Railjack` to 118 rows, `Star Chart` 272, `Conclave` 7, `Duviri` 16, `Hollvania` 11, `Zariman Ten Zero` 5, `Sanctuary Onslaught` 2, **`None` 4** (`--coverage`, snapshot 57e7af2a).

## §1 Every `planet` label in missionRewards.json

`placed/unplaced` = node keys matched / not matched by the rules above. "export region" is the English text of the export `systemName` of the label's nodes.

| # | label | nodes | placed/unplaced | what it is | export region text (systemName key leaf) |
|---|---|---|---|---|---|
| 1 | Mercury | 10 | 8/2 | Star Chart planet | Mercury (`/Locations/Mercury`) |
| 2 | Venus | 33 | 32/1 | **Star Chart planet + Venus Proxima merged** | Venus, Venus Proxima (`/Venus`, `/Venus_SPACE`) |
| 3 | Earth | 27 | 27/0 | **Star Chart planet + Earth Proxima merged** | Earth, Earth Proxima (`/Earth`, `/Earth_SPACE`) |
| 4 | Mars | 15 | 13/2 | Star Chart planet | Mars (`/Locations/Mars`) |
| 5 | Phobos | 16 | 9/7 | Star Chart planet (moon of Mars) | Phobos (`/Locations/Phobos`) |
| 6 | Deimos | 10 | 10/0 | Star Chart region (moon of Mars) | Deimos (`/InfestedMicroplanet/SolarMapDeimosName`) |
| 7 | Ceres | 16 | 12/4 | Star Chart planet | Ceres (`/Locations/Ceres`) |
| 8 | Jupiter | 15 | 15/0 | Star Chart planet | Jupiter (`/Locations/Jupiter`) |
| 9 | Europa | 16 | 9/7 | Star Chart planet (moon of Jupiter) | Europa (`/Locations/Europa`) |
| 10 | Saturn | 45 | 33/12 | **Star Chart planet + Saturn Proxima + Conclave merged** | Saturn, Saturn Proxima (`/Saturn`, `/Saturn_SPACE`) |
| 11 | Uranus | 24 | 16/8 | **Star Chart planet + Uranus Proxima merged** | Uranus, Uranus Proxima (`/Uranus`, `/Uranus_SPACE`) |
| 12 | Neptune | 35 | 33/2 | **Star Chart planet + Neptune Proxima + 1 Conclave map merged** | Neptune, Neptune Proxima |
| 13 | Pluto | 30 | 28/2 | **Star Chart planet + Pluto Proxima merged** | Pluto, Pluto Proxima |
| 14 | Sedna | 21 | 13/8 | Star Chart planet | Sedna (`/Locations/Sedna`) |
| 15 | Eris | 22 | 9/13 | Star Chart planet | Eris (`/Locations/Eris`) |
| 16 | Lua | 11 | 11/0 | **special-ish: Star Chart region (moon)** | Lua (`/Locations/Moon`) |
| 17 | Void | 15 | 15/0 | **special-ish: Star Chart region (Orokin Void)** | Void (`/Locations/Void`) |
| 18 | Kuva Fortress | 6 | 6/0 | **special-ish: Star Chart region (moving fortress)** | Kuva Fortress (`/Locations/Fortress`) |
| 19 | Veil Proxima | 30 | 30/0 | **Railjack proxima** | Veil Proxima (`/Locations/DeepSpace_SPACE`) |
| 20 | Duviri | 16 | 1/15 | **special: Duviri** | Duviri (`/Locations/Duviri`) |
| 21 | Höllvania | 11 | 9/2 | **special: 1999 hub** | Höllvania (`/1999/1999MapName`) |
| 22 | Zariman | 5 | 5/0 | **special: Zariman Ten Zero** | Zariman (`/Zariman/ZarimanRegionName`) |
| 23 | Sanctuary | 2 | 2/0 | **special: Sanctuary Onslaught** | Sanctuary (`/Locations/RelayStationSanctuary`) |
| 24 | Dark Refractory, Deimos | 4 | 4/0 | **special: Tau / Perita Rebellion** | Dark Refractory, Deimos (`/TauPrequel/TauPrequelFinal/TauRegion`) |

Classification counts: 15 plain Star Chart planets/moons + Lua/Void/Kuva Fortress as Star Chart regions (= 18 Star Chart labels); 1 Railjack label (`Veil Proxima`); 4 non-Star-Chart specials (`Duviri`, `Höllvania`, `Zariman`, `Sanctuary`) + `Dark Refractory, Deimos`; 6 planet labels that *hide* a proxima (Venus, Earth, Saturn, Uranus, Neptune, Pluto) — the drop table flattens `Venus Proxima` into `Venus`, so only the `gameMode` separates them.

## §2 Correct navigation for every label that is not a plain planet

All "region" names below are the export's own English `systemName` text (DE export + dictionary), so they are verified, not chosen. Wiki is used only where the export cannot say *how the player gets there*.

| label | correct navigation | region | source |
|---|---|---|---|
| Veil Proxima | **Railjack** → Veil Proxima | Veil Proxima | export: `systemName=/Locations/DeepSpace_SPACE`, `dict.en['/Lotus/Language/Locations/DeepSpace_SPACE']='Veil Proxima'`; entry point: Star Chart → Empyrean Proxima (top-right of Navigation) — <https://wiki.warframe.com/w/Star_Chart#Empyrean_Proxima> |
| Venus / Earth / Saturn / Uranus / Neptune / Pluto Skirmish+Proxima nodes | **Railjack** → `<planet> Proxima` | export `*_SPACE` text | export: `missionType=MT_RAILJACK` + `dict.en['/Lotus/Language/Locations/Venus_SPACE']='Venus Proxima'` (+ Earth/Saturn/Neptune/Pluto/Uranus `_SPACE`); proximas listed as Star Chart tabs — <https://wiki.warframe.com/w/Star_Chart#Empyrean_Proxima> |
| Duviri | **Duviri** (Dominus Thrax bust, upper-right of the Star Chart) | Duviri | export: `/Locations/Duviri` = "Duviri"; access — <https://wiki.warframe.com/w/Duviri> ("Duviri can be accessed through the Dominus Thrax bust icon on the upper right corner of the Star Chart") |
| Höllvania | **Hollvania** (Navigation → Pom-2 PC, after The Hex) | Höllvania | export: `/1999/1999MapName` = "Höllvania"; access — <https://wiki.warframe.com/w/Star_Chart#Pom-2_PC> ("a Pom-2 PC will be unlocked… to access Höllvania missions") |
| Zariman | **Zariman Ten Zero** (Star Chart region, after Angels of the Zariman) | Zariman (export alias → "Zariman Ten Zero") | export: `/Zariman/ZarimanRegionName` = "Zariman"; quest gate — <https://wiki.warframe.com/w/Zariman_Ten_Zero> |
| Sanctuary | **Sanctuary Onslaught** (Syndicate → World State Window, or any Relay → Cephalon Simaris) — **not** a Star Chart node | Sanctuary | export: `/Locations/RelayStationSanctuary` = "Sanctuary"; navigation — <https://wiki.warframe.com/w/Sanctuary_Onslaught> ("select 'Sanctuary Onslaught' in the Syndicate World State Window tab") |
| Dark Refractory, Deimos | **Dark Refractory** (sub-section of the Navigation console, after The Old Peace) | Dark Refractory, Deimos | export: `/TauPrequel/TauPrequelFinal/TauRegion` = "Dark Refractory, Deimos"; navigation — <https://wiki.warframe.com/w/Star_Chart#Dark_Refractory>. **This is the one label the current resolver cannot place** (`system=None`, `--coverage` `system_unknown=4`) because the region key is outside `STAR_CHART_KEY_PREFIXES` and absent from `SPECIAL_SYSTEMS` (acquisition_hierarchy.py:137-146). Proposed curated entry: `'Dark Refractory, Deimos' → ('Dark Refractory', 'Dark Refractory, Deimos')`. |
| Lua | Star Chart → Lua (moon) | Lua | export: `/Locations/Moon` = "Lua"; unlock — <https://wiki.warframe.com/w/Star_Chart> (§Origin System: "Lua, unlocked from the completing The Second Dream") |
| Void | Star Chart → Void (Orokin Void) | Void | export: `/Locations/Void` = "Void"; the Void is a Star Chart region — <https://wiki.warframe.com/w/Star_Chart> |
| Kuva Fortress | Star Chart → Kuva Fortress | Kuva Fortress | export: `/Locations/Fortress` = "Kuva Fortress"; unlock — <https://wiki.warframe.com/w/Star_Chart> ("Kuva Fortress, unlocked from the completion of The War Within") |
| Deimos | Star Chart → Deimos (Cambion Drift is the open world **inside** it) | Deimos | export: `missionType` is `MT_LANDSCAPE` only for Cambion Drift (`SolNode229`); the other 14 Deimos entries are normal mission nodes (`MT_SABOTAGE` Formido `SolNode710`, `MT_ASSASSINATION` Magnacidium `SolNode712`, …) |
| Sanctuary/Open-World hub names not in the export | **unverified** as region names: `Cetus`, `Fortuna`, `Necralisk`, `Sanctum Anatomica` appear as `nodeType 3` hub entries (`CetusHub4`, `SolarisUnitedHub1`, `DeimosHub`, `EntratiLabHub`), not as `systemName` regions — a card must say "hub of <region>", not treat them as systems. |

## §3 Node keys that do not match a node name in the export — 12 groups

Ranked by reason; examples are `<label>/<key>`. "Normalisation" is the proposed rule.

| # | group | count | examples | proposed normalisation |
|---|---|---|---|---|
| 1 | no suffix, exact export name | 237 | `Mercury/Apollodorus`, `Earth/Lith`, `Neptune/Laomedeia` | none needed |
| 2 | no suffix, **case/diacritic/hyphen variant** of an export name | 7 | `Neptune/Nu-Gua Mines`→`Nu-gua Mines`, `Eris/Kala-Azar`→`Kala-azar`, `Lua/StöFler`→`Stöfler`, `Veil Proxima/Lu-Yan`→`Lu-yan`, `Neptune/The Index: Endurance (Low Risk)`→`THE INDEX: ENDURANCE (LOW RISK)` | casefold + NFKD + `-/_`→space; record `match='case-insensitive'` and keep the drop-table spelling as provenance |
| 3 | ` (Caches)` suffix, base node in export | 56 | `Venus/Falling Glory (Caches)`, `Mercury/Terminus (Caches)`, `Eris/Naeglar (Caches)` | strip the suffix, keep the node, set `variant='caches'`, `reward_source='sabotage cache'` |
| 4 | ` (Caches)`, base is a case variant | 2 | `Neptune/Nu-Gua Mines (Caches)`, `Veil Proxima/Lu-Yan (Caches)` | as 2+3 |
| 5 | ` (Extra)` suffix, base node in export | 46 | `Venus/Bifrost Echo (Extra)`, `Saturn/Nodo Gap (Extra)`, `Neptune/Brom Cluster (Extra)` | strip, `variant='extra'`; keep the drop table's own `gameMode` for the mode word |
| 6 | ` (Extra)`, base is a case variant | 2 | `Neptune/Nu-Gua Mines (Extra)`, `Veil Proxima/Lu-Yan (Extra)` | as 2+5 |
| 7 | ` (Caches)` suffix, **base node absent from the export** | 13 | `Mercury/Neruda (Caches)`, `Saturn/Pallene (Caches)`, `Uranus/Portia (Caches)`, `Neptune/Thalassa (Caches)`, `Eris/Viver (Caches)` | strip the suffix and inherit group 12's treatment; never render the bare node as if verified |
| 8 | ` (Caches)` suffix, base is a **reward-table name** | 1 | `Höllvania/Antivirus Bounty (Caches)` | strip, then apply group 10 |
| 9 | ` (Extra)` suffix, base is a **Conclave map** | 4 | `Saturn/Lunaro Arena (Extra)`, `Saturn/Variant Cephalon Capture (Extra)`, `…Team Annihilation (Extra)`, `…Variant Annihilation (Extra)` | strip, then apply group 11 |
| 10 | no suffix, **reward-table name, not a node** | 16 | `Duviri/Endless: Tier 1`, `Duviri/Endless: Tier 3`, `Duviri/Endless: Repeated Rewards`, `Höllvania/Antivirus Bounty` | never place as a node: render as "The Circuit — endless tier reward" / "Höllvania bounty reward", `system` from the label, `node` left NULL, `reward_source='circuit reward'` |
| 11 | no suffix, **Conclave map absent from the export** | 4 | `Saturn/Lunaro Arena`, `Saturn/Variant Cephalon Capture`, `Saturn/Variant Team Annihilation`, `Saturn/Variant Annihilation` | `system='Conclave'`, `region='Conclave'`, note "retired PvP map"; never show a planet |
| 12 | no suffix, **node absent from the export** (retired or renamed — unverified which) | 47 | `Mercury/Caduceus`, `Venus/Vesper`, `Mars/Arcadia`, `Eris/Cyath`, `Phobos/Opik` | keep the export-verified system+region from the label, `node` = the drop-table spelling, `unresolved='node not in the game export (may be retired or renamed)'` |

Subtotals: **350 placed** (groups 1-6) · **85 unplaced** (groups 7-12: 13+1+4+16+4+47). Group 12 is 60 keys once its 13 `(Caches)` twins are added.

## §4 The non-mission source files

| file (rows) | hierarchy it carries today | what the player must be told | where that data is | what the index keeps now |
|---|---|---|---|---|
| `cetusBountyRewards.json` (10 bounties, 711 rows) | `bountyLevel` (e.g. "Level 5 - 15 Cetus Bounty", "Level 15 - 25 Ghoul Bounty", "Level 15 - 25 Plague Star"), rotation A/B/C, per-reward `stage` ("Stage 1", "Stage 2, Stage 3 of 4, and Stage 3 of 5", "Final Stage") | "Open World → Plains of Eidolon → Cetus bounty, Level 5-15, stage 2/3, rotation A" | the file's own `bountyLevel` + `stage`; region from export `Plains of Eidolon` (`SolNode228`, `MT_LANDSCAPE`) and hub `CetusHub4` | `source`, `detail`=rotation letter, `chance`, `rarity`, `hierarchy` "Open World → Plains of Eidolon (Earth) → Cetus bounty" (obtain_index.py:374-385) — **`stage` and `bountyLevel` are dropped** |
| `solarisBountyRewards.json` (11, 474) | `bountyLevel`: 7 × "Orb Vallis Bounty", 4 × "PROFIT-TAKER - PHASE 1..4" | "Open World → Orb Vallis → bounty" / "Profit-Taker, phase 3" | `bountyLevel`; export `Orb Vallis` (`SolNode129`, `MT_LANDSCAPE`), hub `SolarisUnitedHub1` | rotation letter only; no level band, no Profit-Taker phase |
| `deimosRewards.json` (12, 893) | `bountyLevel`: 6 × "Cambion Drift Bounty", 3 × "Isolation Vault", 3 × "Arcana Isolation Vault" | "Open World → Cambion Drift → Isolation Vault (level 30-40)" | `bountyLevel`; export `Cambion Drift` (`SolNode229`, `MT_LANDSCAPE`), hub `DeimosHub` | rotation letter only |
| `zarimanRewards.json` (5, 43) | `bountyLevel` "Level 50 - 55 Zariman Bounty" … 5 bands; rewards only in `C`, `stage="Final stage"` | "Zariman Ten Zero → Quinn's bounty, level 50-55, final stage" | `bountyLevel` + the export's Zariman regions (`Chrysalith`, `Halako Perimeter`, `Oro Works`, `Tuvul Commons`, `The Greenway`, `Everview Arc`) | 28 rows, rotation only |
| `entratiLabRewards.json` (5, 41) | `bountyLevel` "Level 55 - 60 Entrati Lab Bounty" … 5 bands, `stage="Final stage"` | "Deimos → Sanctum Anatomica / Albrecht's Laboratories bounty, level 55-60" | `bountyLevel`; export `Sanctum Anatomica` (`EntratiLabHub`), `Armatus`, `Cambire` | 30 rows, rotation only |
| `hexRewards.json` (7, 59) | `bountyLevel` "Level 55 - 60 WF1999 Bounty" … 7 bands, `stage="Final stage"` | "Höllvania → Pom-2 → Hex bounty (WF1999), level 55-60" | `bountyLevel`; export `/1999/1999MapName` = "Höllvania" | 49 rows, rotation only |
| `keyRewards.json` (36 keys, 668) | `keyName` on the table (24 distinct: "Recover The Orokin Archive", "Kullervo's Hold", "Archon Amar", "Operation: Orphix Venom", "Abyssal Beacon", …), rotations A/B/C | "Duviri → Kullervo's Hold, rotation C" — the key/quest/vault name is the whole answer | `keyName`; difficulty/location per key needs the wiki (e.g. <https://wiki.warframe.com/w/Kullervo%27s_Hold>) | **`keyName` is lost** (`walk_rewards` chains `('keyRewards','rewards','A')`, obtain_index.py:189-198), so rows render as "Key: C" |
| `transientRewards.json` (51, 744) | `objectiveName` on the table (51 distinct: "Arbitrations", "Void Storm (Earth)", "Deep Archimedea Silver Rewards", "Faceoff: Single Squad", "Nightmare Mode Rewards", …), rotation or none | "Arbitrations → rotation A" / "Void Storm → Earth Proxima" | `objectiveName` | **`objectiveName` is lost**; the row renders as "Transient: transientRewards" |
| `sortieRewards.json` (17) | nothing but item/rarity/chance (flat list, no rotation, no season) | "Star Chart → Sortie (3 missions, level 50-100)" | the file gives no place; the mode is a daily Star Chart modifier | `hierarchy="Star Chart → Sortie"`, `reward_source='sortie reward'` |
| `syndicates.json` (18 vendors, 1736 rows) | per row: `place` ("Ostron (Hok), Neutral", "Arbiters of Hexis, Maxim", "Cephalon Simaris"), `standing`, `cost`, `chance` | "Necraloid (standing) → Rank 2, 3 500 standing" | the file itself; the file's shape is `{syndicates:{vendor:[rows]}}` | **0 rows reach the index** — `walk_rewards` (obtain_index.py:189-198) yields nothing for that shape, so 275 kB of vendor data is silently dropped and no item has `reward_source='vendor'` |
| `relics.json` (3194 rows) | `tier` (Axi/Lith/Meso/Neo/Requiem/Vanguard), `relicName`, `state` (Intact/Exceptional/Flawless/Radiant), rewards | "Void Fissure → Axi A10 (Intact) → relic reward" — the player needs the *era* + how the relic itself drops | file carries tier/name/state; where the relic drops is not in this file (WFCD `Relics.json` carries `vaulted`) | `tier`, `relic`, `rarity`, `chance`, `vaulted`; **no fissure/era navigation text** |
| `enemyBlueprintTables.json` (107 enemies) | `enemyName` only ("H-09 Apex", "Techrot Scaart", "Tusk Thumper Doma") | "Höllvania → Assassinate: H-09 Tank → H-09 Apex" — the enemy must be tied to the mission that spawns it | not in this file: needs a node → enemy map (the export gives the node, e.g. `Assassinate: H-09 Tank`; the link is manual/wiki) | `enemy`, `chance`, `rarity` — **no place** |
| `blueprintLocations.json` (206 items) | `enemyName` carries a level band ("Taro Crewship (Level 51 - 100)", "Axio Gox (Level 71 - 100)"), plus `enemyItemDropChance`, `enemyBlueprintDropChance` | "Railjack → Pluto Proxima → crewships (level 71-100)" — 90 of the 206 items are Railjack-enemy drops and the band names the proxima tier | the level band in the file + export `MT_RAILJACK` regions per proxima | `enemy`, `chance`, `rarity` — **no place** |

## §5 One verified example per acquisition type (exact rows, exact strings)

1. **Normal Star Chart drop — `Seer Blueprint`.** `data/obtain_index.json#/items/["Seer Blueprint"]/missions/0` = `{planet:"Mercury", node:"Tolstoj", mode:"Assassination", chance:38.72, rarity:"Common", system:"Star Chart", region:"Mercury", hierarchy:"Star Chart → Mercury → Tolstoj", provenance.hierarchy:"game export: /Lotus/Language/Locations/Mercury"}` (source row: `missionRewards.json#missionRewards.Mercury.Tolstoj`). Card today: **"Star Chart → Mercury → Tolstoj" · "Assassination · 38.72%"**.
2. **Railjack/Proxima drop — `Ash Systems Blueprint`.** `…/missions/0` = `{planet:"Venus", node:"Falling Glory", mode:"Skirmish", rotation:"A", chance:13.33, system:"Railjack", region:"Venus Proxima", hierarchy:"Railjack → Venus Proxima → Falling Glory", provenance.hierarchy:"game export: /Lotus/Language/Locations/Venus_SPACE"}`; row 1 is `Luckless Expanse` (13.33%). Card today: **"Railjack → Venus Proxima → Falling Glory" · "Skirmish · rotation A · 13.33%"**. This is the original bug fixed — never "Venus - Falling Glory".
3. **Open-world bounty — `Gara Chassis Blueprint`.** `…/other/0` = `{source:"Cetus bounty", detail:"A", chance:7.52, rarity:"Rare", system:"Open World", region:"Plains of Eidolon (Earth)", hierarchy:"Open World → Plains of Eidolon (Earth) → Cetus bounty"}`; source row `cetusBountyRewards.json` = bounty `Level 5 - 15 Cetus Bounty`, rotation `A`, `stage:"Stage 2, Stage 3 of 4, and Stage 3 of 5"`, 7.52%. Card today: **"Cetus bounty: A" · "7.52% - Rare"** (the hierarchy is in the index but `build_item_obtain` renders only `source:detail` for `other` rows — collection_log.py:714-729). String it should show: **"Open World → Plains of Eidolon → Cetus bounty, Level 5-15, stage 2/3, rotation A · 7.52% Rare"**.
4. **Duviri / Circuit — `2,000 Credits Cache`.** `…/missions/0` = `{planet:"Duviri", node:"The Circuit", mode:"The Circuit", rotation:"A", chance:50, system:"Duviri", region:"Duviri", hierarchy:"Duviri → Duviri → The Circuit", reward_source:"circuit reward"}`. Card today: **"Duviri → Duviri → The Circuit" · "The Circuit · rotation A · 50%"** — region and node are the same word, so it should read **"Duviri → The Circuit (Undercroft), rotation A · 50%"**. The tier tables do not resolve: `Forma Blueprint` carries `node:"Endless: Tier 1 (Hard)"`, `hierarchy:"Duviri → Duviri → Endless: Tier 1 (Hard)"`, `unresolved:["node not in the game export (may be retired or renamed)"]` — it should be **"Duviri → The Circuit (Steel Path), tier 1 endless, 4.43%"**.
5. **Vendor (syndicate / standing store) — `Bonewidow`.** **No index row exists**: `obtain_index.json` has `0` rows with `source:"Syndicate"`/`reward_source:"vendor"` (syndicates.json contributes nothing, §4). The only vendor signal is the wiki pass: `…/acq = {kind:"wiki", title:"Bonewidow/Main", section:"Acquisition", text:"Component blueprints for the Bonewidow are available for 3,500 standing from the Necraloid Syndicate at Rank 2 - Clearance: Modus…"}`, card **"Wiki (Acquisition)"** + that sentence. Structured source to build it from: `syndicates.json#syndicates.NecraLoid[*]` (rows carry `item`, `place`, `standing`, `cost`) → string **"Necraloid Syndicate → Rank 2, 3 500 standing"**.
6. **Quest / special — `Mesa Neuroptics Blueprint`.** Its only row is `…/other/0 = {source:"Key", detail:"C", chance:38.72, rarity:"Common", hierarchy:"Key", provenance.hierarchy:"the drop table groups it under no region"}`; source row `keyRewards.json` = `keyName:"Mutalist Alad V Assassinate"`, rotation `C`, 38.72%. Card today: **"Key: C" · "38.72% - Common"** (the answer "which key" is missing). String it should show: **"Star Chart → Eris → Mutalist Alad V Assassinate (key required) → rotation C · 38.72%"**. (Same defect: `4X Kullervo's Bane` → `keyName:"Kullervo's Hold"`, 30%.)
7. **Two or more legitimate sources — `Quartakk Blueprint`.** `…/enemies/0 = {enemy:"Ghoul Auger Alpha", chance:100, rarity:"Common"}` (from `blueprintLocations.json`) and `…/other/0 = {source:"Cetus bounty", detail:"A", chance:4.85, system:"Open World", region:"Plains of Eidolon (Earth)"}`. Card today shows both: **"Enemy: Ghoul Auger Alpha" · "100% - Common"** and **"Cetus bounty: A" · "4.85% - Rare"**; the enemy lane should name the Plains ("Plain of Eidolon → Ghoul bounty/Plains enemy") and the bounty lane its level band. Bigger multi-source examples: `Forma Blueprint` (relics + missions + other), `Ayatan Amber Star` (relics + missions + other), `Exilus Weapon Adapter Blueprint` (relics + missions), `Riven Sliver` (relics + missions). **260 of 3258 items carry ≥2 source kinds.**

## §6 Acquisition types that still cannot be resolved confidently

1. **Syndicate / standing vendor stores** — `syndicates.json` is `{syndicates:{vendor:[rows]}}`; `walk_rewards` (obtain_index.py:189-198) yields 0 rows, so 1736 vendor rows (18 vendors) never reach the index and no item is marked `vendor`. Fix needs a shape-aware walker for that one file (the `place`/`standing`/`cost` fields are already there).
2. **Bounty level + stage** — `bountyLevel` and per-reward `stage` sit on the rows but are not carried into the index; today every bounty collapse to a rotation letter, which is not enough to find the reward.
3. **Key / quest name** — `keyName` (24 distinct keys) is on the container, not in `walk_rewards`' chain, so every "Key" row loses the one fact that matters ("which key").
4. **Transient objective** — `objectiveName` (51 objectives) lost the same way; rows render as the placeholder "Transient: transientRewards".
5. **Enemy → place** — `enemyBlueprintTables.json`/`blueprintLocations.json` name an enemy but no mission; there is no enemy→node map in any cached file (90 of the 206 blueprint items are Railjack crewship drops whose level band encodes the proxima, but nothing decodes it yet).
6. **Relic source** — the index says which relic yields a part, never where that relic drops or which era/fissure to pick; no cached file carries fissure data.
7. **Node keys absent from the live export (85)** — 47 Star Chart keys (+13 `(Caches)` twins) that DE's export no longer lists (`Eris/Cyath`, `Phobos/Opik`, `Venus/Vesper`, …), 8 Conclave maps and 17 reward-table names. Whether each is retired or renamed is **unverified**; the honest output is the export-verified region plus "node not in the game export".
8. **Event / limited-time status and non-node reward buckets** — the drop table flags `isEvent` (`Caduceus`, `Antivirus Bounty`, `Neruda (Caches)`, Plague Star/Ghoul bounties) and hides event difficulty behind `(Extra)`/`(Hard)`, but neither `isEvent` nor the event name is modelled anywhere, and `The Perita Rebellion` (Tau) keys sit outside every region family the resolver knows.

## §7 Reproducing these numbers

```
python scripts/acquisition_hierarchy.py --report     # 354 names / 354 records; Falling Glory -> Railjack → Venus Proxima → Falling Glory
python scripts/acquisition_hierarchy.py --coverage   # rows 435, placed 346, unconfirmed 85, system_unknown 4 (snapshot 57e7af2a)
python scripts/acquisition_hierarchy.py --selftest   # 14 checks, 0 failed
```
The 350/85 split in §1/§3 comes from the stated matcher over the snapshot hashes, not from `--coverage` (which self-filters export records whose `system` is `None`, dropping the 4 `Dark Refractory, Deimos` rows — the `system_unknown=4` in §2).
