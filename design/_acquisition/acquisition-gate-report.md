# Acquisition accuracy gate

```
python design/_acquisition/acquisition_gate.py --falsify
```

| check | result | detail |
| --- | --- | --- |
| `export/loaded` | PASS | regions: 354, regions named: 30 |
| `export/region-systems` | PASS | {"Venus": "Star Chart", "Venus Proxima": "Railjack", "Veil Proxima": "Railjack"} |
| `export/answer-comes-from-the-export` | PASS | with no export loaded the resolver still claims None |
| `ash/present` | PASS | the index carries Ash Systems Blueprint |
| `ash/railjack-system` | PASS | at least one row is a Railjack row: ['Railjack'] |
| `ash/falling-glory-row` | PASS | the Falling Glory row is indexed |
| `ash/hierarchy-fields` | PASS | {"system": "Railjack", "region": "Venus Proxima", "node": "Falling Glory"} |
| `ash/hierarchy-label` | PASS | Railjack → Venus Proxima → Falling Glory |
| `ash/rotation-kept` | PASS | A |
| `ash/chance-kept` | PASS | 13.33 |
| `ash/not-the-drop-table-planet` | PASS | region is 'Venus Proxima', the drop-table label is 'Venus' |
| `ash/provenance` | PASS | {"chance": "missionRewards.json (DE drop table)", "hierarchy": "game export: /Lotus/Language/Locations/Venus_SPACE", "node_match": "exact", "mode": "game export: MT_RAILJACK"} |
| `ash/rendered-on-the-page` | PASS | the collection store has the row |
| `ash/rendered-label` | PASS | Railjack → Venus Proxima → Falling Glory |
| `ash/rendered-detail` | PASS | Defense · rotation A · 13.33% |
| `ash/rendered-is-not-flat` | PASS | Railjack → Venus Proxima → Falling Glory |
| `railjack/never-flat` | PASS | 0 mixed-up row(s) of 601:  |
| `hierarchy/every-row` | PASS |  |
| `provenance/separate-from-display` | PASS | 0 rows without provenance:  |
| `unresolved/present` | PASS | no row in the whole index reports an unresolved part |
| `unresolved/keeps-the-verified-part` | PASS | 0 unresolved rows show nothing at all |
| `unresolved/never-invents-a-place` | PASS | [] |
| `variant/present` | PASS | no reward-table variant rows in the index |
| `variant/keeps-its-node` | PASS | 0 variant rows lost their hierarchy:  |
| `variant/names-the-table` | PASS | 0 variant rows do not say which table:  |
| `variant/tables-named-plainly` | PASS | ["bonus reward table", "railjack cache", "sabotage cache"] |
| `source/star chart` | PASS | Star Chart: Star Chart → Deimos → Hyf |
| `source/star chart-navigable` | PASS | {"planet": "Deimos", "node": "Hyf", "mode": "Defense", "rotation": "C", "chance": 22.56, "rarity": "Uncommon", "path": "Hyf/C", "system": "Star Chart", "region": "Deimos", "hierarchy": "Star Chart \u2192 Deimos \u2192 Hyf", "reward_source": "mission completion", "mode_verified": "Defense", "enemy_levels": "15-20", "mission_type": "MT_DEFENSE", "provenance": {"chance": "missionRewards.json (DE drop table)", "hierarchy": "game export: /Lotus/Language/InfestedMicroplanet/SolarMapDeimosName", "node_match": "exact", "mode": "game export: MT_DEFENSE"}} |
| `source/railjack` | PASS | Railjack: Railjack → Veil Proxima → Flexa |
| `source/railjack-navigable` | PASS | {"planet": "Veil Proxima", "node": "Flexa", "mode": "Skirmish", "rotation": null, "chance": 2.5, "rarity": "Rare", "path": "Flexa", "system": "Railjack", "region": "Veil Proxima", "hierarchy": "Railjack \u2192 Veil Proxima \u2192 Flexa", "reward_source": "mission completion", "mode_verified": "Skirmish", "enemy_levels": "80-90", "mission_type": "MT_RAILJACK", "provenance": {"chance": "missionRewards.json (DE drop table)", "hierarchy": "game export: /Lotus/Language/Locations/DeepSpace_SPACE", "node_match": "exact", "mode": "game export: MT_RAILJACK"}} |
| `source/duviri/circuit` | PASS | Duviri: Duviri → Endless: Tier 1 (Hard) |
| `source/duviri/circuit-navigable` | PASS | {"planet": "Duviri", "node": "Endless: Tier 1 (Hard)", "mode": "Hard", "rotation": null, "chance": 4.43, "rarity": "Rare", "path": "Endless: Tier 1 (Hard)", "system": "Duviri", "region": "Duviri", "hierarchy": "Duviri \u2192 Endless: Tier 1 (Hard)", "reward_source": "circuit reward", "unresolved": ["node not in the game export (may be retired or renamed)"], "provenance": {"chance": "missionRewards.json (DE drop table)", "hierarchy": "drop table label (Duviri)", "node_match": "exact"}} |
| `source/zariman` | PASS | Zariman Ten Zero: Zariman Ten Zero → Halako Perimeter |
| `source/zariman-navigable` | PASS | {"planet": "Zariman", "node": "Halako Perimeter", "mode": "Exterminate", "rotation": null, "chance": 15.56, "rarity": "Uncommon", "path": "Halako Perimeter", "system": "Zariman Ten Zero", "region": "Zariman Ten Zero", "hierarchy": "Zariman Ten Zero \u2192 Halako Perimeter", "reward_source": "mission completion", "mode_verified": "Exterminate", "enemy_levels": "50-55", "mission_type": "MT_EXTERMINATION", "provenance": {"chance": "missionRewards.json (DE drop table)", "hierarchy": "game export: /Lotus/Language/Zariman/ZarimanRegionName", "node_match": "exact", "mode": "game export: MT_EXTERMINATION"}} |
| `source/sanctuary` | PASS | Sanctuary Onslaught: Sanctuary Onslaught → Sanctuary → Sanctuary Onslaught |
| `source/sanctuary-navigable` | PASS | {"planet": "Sanctuary", "node": "Sanctuary Onslaught", "mode": "Sanctuary Onslaught", "rotation": "C", "chance": 9.09, "rarity": "Rare", "path": "Sanctuary Onslaught/C", "system": "Sanctuary Onslaught", "region": "Sanctuary", "hierarchy": "Sanctuary Onslaught \u2192 Sanctuary \u2192 Sanctuary Onslaught", "reward_source": "mission completion", "mode_verified": "Sanctuary Onslaught", "enemy_levels": "20-30", "mission_type": "MT_ENDLESS_EXTERMINATION", "provenance": {"chance": "missionRewards.json (DE drop table)", "hierarchy": "game export: /Lotus/Language/Locations/RelayStationSanctuary", "node_match": "exact", "mode": "game export: MT_ENDLESS_EXTERMINATION"}} |
| `source/hollvania` | PASS | Hollvania: Hollvania → Höllvania → Legacyte Harvest |
| `source/hollvania-navigable` | PASS | {"planet": "H\u00f6llvania", "node": "Legacyte Harvest", "mode": "Legacyte Harvest", "rotation": "C", "chance": 15.86, "rarity": "Uncommon", "path": "Legacyte Harvest/C", "system": "Hollvania", "region": "H\u00f6llvania", "hierarchy": "Hollvania \u2192 H\u00f6llvania \u2192 Legacyte Harvest", "reward_source": "mission completion", "mode_verified": "Legacyte Harvest", "enemy_levels": "65-70", "mission_type": "MT_ENDLESS_CAPTURE", "provenance": {"chance": "missionRewards.json (DE drop table)", "hierarchy": "game export: /Lotus/Language/1999/1999MapName", "node_match": "exact", "mode": "game export: MT_ENDLESS_CAPTURE"}} |
| `source/bounty (cetus)` | PASS | Cetus bounty: Plains of Eidolon (Earth) |
| `source/bounty (solaris)` | PASS | Solaris: Orb Vallis (Venus) |
| `source/bounty (deimos)` | PASS | Deimos: Cambion Drift (Deimos) |
| `source/bounty (hex)` | PASS | Hex: Höllvania |
| `source/vendor-shaped-sources-labelled` | PASS | vendor-shaped sources present: Key |
| `source/bounty-indexed` | PASS | no bounty-stage rows in the index |
| `source/bounty-keeps-its-level-band` | PASS | 0 of 1077 bounty rows have no level band:  |
| `source/bounty-keeps-its-stage` | PASS | 0 bounty rows dropped the stage:  |
| `source/key-indexed` | PASS | no key rows in the index |
| `source/key-names-the-key` | PASS | 0 key rows show only a rotation:  |
| `source/key-resolves-when-it-is-a-node` | PASS | 6 of 217 key rows resolved to a region |
| `source/objective-indexed` | PASS | no transient rows in the index |
| `source/objective-named` | PASS | 0 transient rows have no objective:  |
| `source/vendor-indexed` | PASS | 1717 vendor rows reach the index (the syndicates file used to contribute none) |
| `source/vendor-placed-or-marked` | PASS | 0 vendor rows claim nothing at all:  |
| `source/unverified-vendor-not-guessed` | PASS | 0 unverified vendors were given a system:  |
| `enemy/crewship-indexed` | PASS | no crewship drops in the index |
| `enemy/crewship-is-railjack` | PASS | 0 crewship drops claim no system:  |
| `mode/railjack-rows-present` | PASS | 601 Railjack rows |
| `mode/every-railjack-row-has-the-export-variant` | PASS | 0 Railjack rows carry no verified mission:  |
| `mode/the-export-word-replaces-the-table-word` | PASS | 564 Railjack rows carry a verified mission that differs from the drop table |
| `mode/ash-systems-missions-are-real-missions` | PASS | Falling Glory=Defense, Luckless Expanse=Survival, Beacon Shield Ring=Volatile, Bifrost Echo=Exterminate |
| `multi-source/kept-separate` | PASS | an item with two or more source kinds: ('Forma Blueprint', ['relics', 'missions', 'other']) |

**61 checks, 0 failed.**

## Falsification: does the gate catch breakage?

| deliberate break | what it would let through | caught | failed checks |
| --- | --- | --- | --- |
| `flatten-the-label` | the hierarchy collapses to the drop-table wording | yes | `ash/hierarchy-label`, `railjack/never-flat`, `hierarchy/every-row` |
| `trust-the-drop-table-label` | the first segment of the drop-table label becomes the region | yes | `ash/hierarchy-fields`, `ash/hierarchy-label`, `ash/not-the-drop-table-planet` |
| `keep-the-reward-table-suffix` | a '(Caches)'/'Extra' row stops matching its node | yes | `variant/present`, `mode/every-railjack-row-has-the-export-variant` |
