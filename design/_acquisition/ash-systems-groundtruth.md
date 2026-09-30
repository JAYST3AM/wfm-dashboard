# Ash Systems Blueprint — acquisition ground truth

Repo: `F:\VSC Projects\wfm-dashboard` (git HEAD `b5c6b7d`, `scripts/acquisition_hierarchy.py` untracked/new)
Written: 2026-09-30 14:57 AEST (system clock, `date` → `Wed, Sep 30, 2026  2:57:23 PM`)
Everything below is copied from real command output; nothing is inferred from memory.

Sources used

| source | file | shape |
| --- | --- | --- |
| DE's official drop tables (WFCD mirror) | `data/dropdata/missionRewards.json` | **single line** (0 newlines, 1,087,021 bytes) → cited by JSON path, not line number |
| DE's own game export — region/navigation data | `data/dropdata/export/ExportRegions.json` | pretty-printed, 14,203 newlines / 14,204 lines (no trailing newline) → cited by line |
| DE's own game export — English localisation | `data/dropdata/export/dict.en.json` | pretty-printed, 36,166 lines → cited by line |
| WARFRAME Wiki (live) | <https://wiki.warframe.com/w/Ash> (§Acquisition) and <https://wiki.warframe.com/w/The_Kuva_Wytch> | fetched with `web_extract`; plain curl gets the Cloudflare challenge |

## 0. Answers in one line

- **Ash Systems Blueprint** drops in exactly **4** drop-table rows, all `Venus` / `Skirmish` / railjack: `Bifrost Echo` 4.88% (flat pool), `Beacon Shield Ring` 4.88% (flat pool), `Luckless Expanse` rotation A 13.33%, `Falling Glory` rotation A 13.33%.
- The whole Ash family in the drop table is **12 rows**: Neuroptics 4 (Neptune), Chassis 4 (Pluto), Systems 4 (Venus), and **0 rows for `Ash Blueprint`** (the main blueprint is not a mission drop).
- All 12 nodes are **Railjack** nodes: `MT_RAILJACK`, `systemName …/Venus_SPACE|Neptune_SPACE|Pluto_SPACE` → **Venus Proxima / Neptune Proxima / Pluto Proxima**. The drop table's planet label (`Venus`/`Neptune`/`Pluto`) is *not* the region a player navigates to.
- The node whose export name key is `…/AshRJMissionName` is **`CrewBattleNode560` = "The Kuva Wytch"**, in **Uranus Proxima** (`…/Uranus_SPACE`). **The official drop table lists no Ash part under it** (0 rows, and 0 rows anywhere on Uranus).
- The wiki says the same thing the drop table says, per part and per Proxima, to the digit; it adds the mode names and the two main-blueprint sources (Market, The Circuit) that the drop table does not carry.
- The correct player-facing hierarchy is **Railjack → `<planet> Proxima` → `<node>` (`<mode>`)**, and it cannot be produced from the drop table alone: the drop table gives a bare planet label and the generic mode `Skirmish` for every one of these nodes.

## 1. Every `Ash Systems Blueprint` row in `data/dropdata/missionRewards.json`

Path in the file: `missionRewards["Venus"]["<node>"]["rewards"][<rotation>][i].itemName == "Ash Systems Blueprint"`.
Shape note: `rewards` is a dict keyed by rotation for most nodes, but a **flat list** for some railjack nodes (no rotation keys exist in the mirror) — those rows are printed here with `'rotation': None`.

Command (run from the repo root):

```bash
python - <<'PY'
import json
mr = json.load(open('data/dropdata/missionRewards.json', encoding='utf-8'))['missionRewards']
PARTS = ['Ash Blueprint', 'Ash Neuroptics Blueprint', 'Ash Chassis Blueprint', 'Ash Systems Blueprint']
out = {}
for part in PARTS:
    rows = []
    for planet, nodes in mr.items():
        for node, info in nodes.items():
            rw = info.get('rewards')
            if isinstance(rw, list):
                rw = {None: rw}
            for rot, items in (rw or {}).items():
                for it in items:
                    if it.get('itemName') == part:
                        rows.append({'planet': planet, 'node': node, 'gameMode': info.get('gameMode'),
                                     'isEvent': info.get('isEvent'), 'rotation': rot,
                                     'rarity': it.get('rarity'), 'chance': it.get('chance')})
    out[part] = rows
print('top-level keys:', list(json.load(open('data/dropdata/missionRewards.json', encoding='utf-8')).keys()))
print('total rows across the 4 Ash names:', sum(len(v) for v in out.values()))
print()
import pprint
pprint.pprint(out, width=120, sort_dicts=False)
PY
```

Real output (verbatim):

```
top-level keys: ['missionRewards']
total rows across the 4 Ash names: 12
```

The `Ash Systems Blueprint` rows as a python dict:

```python
Ash_systems_rows = [
    {'planet': 'Venus', 'node': 'Bifrost Echo',      'gameMode': 'Skirmish', 'isEvent': False, 'rotation': None, 'rarity': 'Rare',     'chance': 4.88},
    {'planet': 'Venus', 'node': 'Beacon Shield Ring', 'gameMode': 'Skirmish', 'isEvent': False, 'rotation': None, 'rarity': 'Rare',     'chance': 4.88},
    {'planet': 'Venus', 'node': 'Luckless Expanse',  'gameMode': 'Skirmish', 'isEvent': False, 'rotation': 'A',  'rarity': 'Uncommon', 'chance': 13.33},
    {'planet': 'Venus', 'node': 'Falling Glory',     'gameMode': 'Skirmish', 'isEvent': False, 'rotation': 'A',  'rarity': 'Uncommon', 'chance': 13.33},
]
# count = 4
```

Raw file excerpt for the two node shapes (the file itself is one line, so this is `json.dumps` of the two records):

```python
# rewards flat list  ->  'rotation': None
{'Venus': {'Bifrost Echo': {'gameMode': 'Skirmish', 'isEvent': False, 'rewards': [
    {'_id': '2d220168d8505314316354e586fe4c7e', 'itemName': '100 Endo',            'rarity': 'Uncommon', 'chance': 12.2},
    {'_id': '169a476645965b019e1db0d0734b569a', 'itemName': 'Ash Systems Blueprint','rarity': 'Rare',     'chance': 4.88},
    {'_id': '97cd2c3718ab7e43d7ae3c90df413903', 'itemName': 'Lith L8 Relic',       'rarity': 'Rare',     'chance': 2.44},
    # ... 15 rewards in total, no rotation keys
]}}}

# rewards dict keyed A/B/C  ->  'rotation': 'A'
{'Venus': {'Luckless Expanse': {'gameMode': 'Skirmish', 'isEvent': False, 'rewards': {
    'A': [{'_id': '169a476645965b019e1db0d0734b569a', 'itemName': 'Ash Systems Blueprint', 'rarity': 'Uncommon', 'chance': 13.33},
          # ... 3 more in A
          ],
    'B': [...],  # no Ash part in B or C
    'C': [...],
}}}}
```

Every one of the 4 rows carries `'gameMode': 'Skirmish'` and `'isEvent': False`; **the drop table never says which of Survival / Defense / Exterminate / Volatile a node is, and never says the planet label is a Proxima.**

## 2. The same for the rest of the family (`Ash Neuroptics`, `Ash Chassis`, `Ash Blueprint`)

Verbatim output of the same script (`pprint.pprint(out, width=120, sort_dicts=False)`), re-indented for readability:

```python
{
 'Ash Blueprint': [],
 'Ash Neuroptics Blueprint': [
     {'planet': 'Neptune', 'node': 'Arva Vector',      'gameMode': 'Skirmish', 'isEvent': False, 'rotation': 'A',  'rarity': 'Uncommon', 'chance': 12.5},
     {'planet': 'Neptune', 'node': 'Nu-Gua Mines',     'gameMode': 'Skirmish', 'isEvent': False, 'rotation': None, 'rarity': 'Rare',     'chance': 4.71},
     {'planet': 'Neptune', 'node': 'Enkidu Ice Drifts','gameMode': 'Skirmish', 'isEvent': False, 'rotation': 'A',  'rarity': 'Uncommon', 'chance': 12.5},
     {'planet': 'Neptune', 'node': 'Sovereign Grasp',  'gameMode': 'Skirmish', 'isEvent': False, 'rotation': None, 'rarity': 'Rare',     'chance': 4.71}],
 'Ash Chassis Blueprint': [
     {'planet': 'Pluto', 'node': 'Seven Sirens',   'gameMode': 'Skirmish', 'isEvent': False, 'rotation': None, 'rarity': 'Rare',     'chance': 4.82},
     {'planet': 'Pluto', 'node': 'Obol Crossing',  'gameMode': 'Skirmish', 'isEvent': False, 'rotation': 'A',  'rarity': 'Uncommon', 'chance': 13.33},
     {'planet': 'Pluto', 'node': "Fenton's Field", 'gameMode': 'Skirmish', 'isEvent': False, 'rotation': 'A',  'rarity': 'Uncommon', 'chance': 13.33},
     {'planet': 'Pluto', 'node': 'Profit Margin',  'gameMode': 'Skirmish', 'isEvent': False, 'rotation': None, 'rarity': 'Rare',     'chance': 4.82}],
 'Ash Systems Blueprint': [
     {'planet': 'Venus', 'node': 'Bifrost Echo',      'gameMode': 'Skirmish', 'isEvent': False, 'rotation': None, 'rarity': 'Rare',     'chance': 4.88},
     {'planet': 'Venus', 'node': 'Beacon Shield Ring', 'gameMode': 'Skirmish', 'isEvent': False, 'rotation': None, 'rarity': 'Rare',     'chance': 4.88},
     {'planet': 'Venus', 'node': 'Luckless Expanse',  'gameMode': 'Skirmish', 'isEvent': False, 'rotation': 'A',  'rarity': 'Uncommon', 'chance': 13.33},
     {'planet': 'Venus', 'node': 'Falling Glory',     'gameMode': 'Skirmish', 'isEvent': False, 'rotation': 'A',  'rarity': 'Uncommon', 'chance': 13.33}]
}
```

`Ash Blueprint` (the main blueprint) is genuinely absent — not a name mismatch:

```
$ grep -o '"Ash Blueprint"' data/dropdata/missionRewards.json | wc -l
0
```

Every item name in the file that matches `/ash/i`, for completeness (so the absence is not blamed on a spelling):

```
'Ash Chassis Blueprint'
'Ash Neuroptics Blueprint'
'Ash Systems Blueprint'
'Astral Slash'
'Clashing Forest'
'Gnashing Payara'
'Lashta-Vak'
'Lightning Dash'
'Meteor Crash'
'Zid-An Asheir'
```

The main blueprint is therefore **not obtainable as a mission reward**; its two real sources (Market purchase, The Circuit) are not in `missionRewards.json` at all — see §5. Prime parts live elsewhere (`data/dropdata/relics.json`), so their absence here is expected.

## 3. The game-export record for each of those nodes

`ExportRegions.json` → one entry per node; the display name and the region come from `dict.en.json`.
Matching note: the drop table writes **`Nu-Gua Mines`**, the export/dictionary writes **`Nu-gua Mines`** (lower-case `g`) — an exact-match lookup misses it, a case-insensitive one finds `CrewBattleNode516`.

Command (run from the repo root):

```bash
python - <<'PY'
import json, pprint
reg = json.load(open('data/dropdata/export/ExportRegions.json', encoding='utf-8'))
dct = json.load(open('data/dropdata/export/dict.en.json', encoding='utf-8'))
NODES = ['Bifrost Echo', 'Beacon Shield Ring', 'Luckless Expanse', 'Falling Glory',
         'Arva Vector', 'Nu-Gua Mines', 'Enkidu Ice Drifts', 'Sovereign Grasp',
         'Seven Sirens', 'Obol Crossing', "Fenton's Field", 'Profit Margin', 'The Kuva Wytch']
rec = {}
for want in NODES:
    for key, e in reg.items():
        if dct.get(e.get('name', '')).lower() == want.lower():
            rec[want] = {'region_key': key, 'node': dct.get(e['name']), 'node_name_key': e['name'],
                         'missionType': e.get('missionType'), 'missionNameKey': e.get('missionName'),
                         'mission_english': (dct.get(e.get('missionName')) or '').strip('$'),
                         'systemName': e.get('systemName'), 'system_english': dct.get(e.get('systemName')),
                         'nodeType': e.get('nodeType')}
pprint.pprint(rec, width=150, sort_dicts=False)
PY
```

Real output, one dict per node (verbatim values):

```python
{
 'Bifrost Echo':       {'region_key': 'CrewBattleNode503', 'node': 'Bifrost Echo',       'node_name_key': '/Lotus/Language/Locations/CrewBattleNode503',
                        'missionType': 'MT_RAILJACK', 'missionNameKey': '/Lotus/Language/Missions/MissionName_RailjackExterminate', 'mission_english': 'EXTERMINATE',
                        'systemName': '/Lotus/Language/Locations/Venus_SPACE',   'system_english': 'Venus Proxima',   'nodeType': 0},
 'Beacon Shield Ring': {'region_key': 'CrewBattleNode511', 'node': 'Beacon Shield Ring', 'node_name_key': '/Lotus/Language/Locations/CrewBattleNode511',
                        'missionType': 'MT_RAILJACK', 'missionNameKey': '/Lotus/Language/Missions/MissionName_RailjackVolatile', 'mission_english': 'VOLATILE',
                        'systemName': '/Lotus/Language/Locations/Venus_SPACE',   'system_english': 'Venus Proxima',   'nodeType': 0},
 'Luckless Expanse':   {'region_key': 'CrewBattleNode515', 'node': 'Luckless Expanse',   'node_name_key': '/Lotus/Language/Locations/CrewBattleNode515',
                        'missionType': 'MT_RAILJACK', 'missionNameKey': '/Lotus/Language/Missions/MissionName_RailjackSurvival', 'mission_english': 'SURVIVAL',
                        'systemName': '/Lotus/Language/Locations/Venus_SPACE',   'system_english': 'Venus Proxima',   'nodeType': 0},
 'Falling Glory':      {'region_key': 'CrewBattleNode514', 'node': 'Falling Glory',      'node_name_key': '/Lotus/Language/Locations/CrewBattleNode514',
                        'missionType': 'MT_RAILJACK', 'missionNameKey': '/Lotus/Language/Missions/MissionName_RailjackDefense', 'mission_english': 'DEFENSE',
                        'systemName': '/Lotus/Language/Locations/Venus_SPACE',   'system_english': 'Venus Proxima',   'nodeType': 0},

 'Arva Vector':        {'region_key': 'CrewBattleNode504', 'node': 'Arva Vector',        'node_name_key': '/Lotus/Language/Locations/CrewBattleNode504',
                        'missionType': 'MT_RAILJACK', 'missionNameKey': '/Lotus/Language/Missions/MissionName_RailjackDefense', 'mission_english': 'DEFENSE',
                        'systemName': '/Lotus/Language/Locations/Neptune_SPACE', 'system_english': 'Neptune Proxima', 'nodeType': 0},
 'Nu-Gua Mines':       {'region_key': 'CrewBattleNode516', 'node': 'Nu-gua Mines',       'node_name_key': '/Lotus/Language/Locations/CrewBattleNode516',
                        'missionType': 'MT_RAILJACK', 'missionNameKey': '/Lotus/Language/Missions/MissionName_RailjackExterminate', 'mission_english': 'EXTERMINATE',
                        'systemName': '/Lotus/Language/Locations/Neptune_SPACE', 'system_english': 'Neptune Proxima', 'nodeType': 0},
 'Enkidu Ice Drifts':  {'region_key': 'CrewBattleNode521', 'node': 'Enkidu Ice Drifts',  'node_name_key': '/Lotus/Language/Locations/CrewBattleNode521',
                        'missionType': 'MT_RAILJACK', 'missionNameKey': '/Lotus/Language/Missions/MissionName_RailjackSurvival', 'mission_english': 'SURVIVAL',
                        'systemName': '/Lotus/Language/Locations/Neptune_SPACE', 'system_english': 'Neptune Proxima', 'nodeType': 0},
 'Sovereign Grasp':    {'region_key': 'CrewBattleNode524', 'node': 'Sovereign Grasp',    'node_name_key': '/Lotus/Language/Locations/CrewBattleNode524',
                        'missionType': 'MT_RAILJACK', 'missionNameKey': '/Lotus/Language/Missions/MissionName_RailjackVolatile', 'mission_english': 'VOLATILE',
                        'systemName': '/Lotus/Language/Locations/Neptune_SPACE', 'system_english': 'Neptune Proxima', 'nodeType': 0},

 'Seven Sirens':       {'region_key': 'CrewBattleNode527', 'node': 'Seven Sirens',       'node_name_key': '/Lotus/Language/Locations/CrewBattleNode527',
                        'missionType': 'MT_RAILJACK', 'missionNameKey': '/Lotus/Language/Missions/MissionName_RailjackExterminate', 'mission_english': 'EXTERMINATE',
                        'systemName': '/Lotus/Language/Locations/Pluto_SPACE',   'system_english': 'Pluto Proxima',   'nodeType': 0},
 'Obol Crossing':      {'region_key': 'CrewBattleNode528', 'node': 'Obol Crossing',      'node_name_key': '/Lotus/Language/Locations/CrewBattleNode528',
                        'missionType': 'MT_RAILJACK', 'missionNameKey': '/Lotus/Language/Missions/MissionName_RailjackDefense', 'mission_english': 'DEFENSE',
                        'systemName': '/Lotus/Language/Locations/Pluto_SPACE',   'system_english': 'Pluto Proxima',   'nodeType': 0},
 "Fenton's Field":     {'region_key': 'CrewBattleNode531', 'node': "Fenton's Field",     'node_name_key': '/Lotus/Language/Locations/CrewBattleNode531',
                        'missionType': 'MT_RAILJACK', 'missionNameKey': '/Lotus/Language/Missions/MissionName_RailjackSurvival', 'mission_english': 'SURVIVAL',
                        'systemName': '/Lotus/Language/Locations/Pluto_SPACE',   'system_english': 'Pluto Proxima',   'nodeType': 0},
 'Profit Margin':      {'region_key': 'CrewBattleNode529', 'node': 'Profit Margin',      'node_name_key': '/Lotus/Language/Locations/CrewBattleNode529',
                        'missionType': 'MT_RAILJACK', 'missionNameKey': '/Lotus/Language/Missions/MissionName_RailjackVolatile', 'mission_english': 'VOLATILE',
                        'systemName': '/Lotus/Language/Locations/Pluto_SPACE',   'system_english': 'Pluto Proxima',   'nodeType': 0},
}
```

`nodeType` is `0` for every one of them; `missionType` is `MT_RAILJACK` for every one of them, so **the export's `missionType` alone cannot name the mission variant** — `missionName` (or `levelOverride`) is what carries Survival/Defense/Exterminate/Volatile:

```
ExportRegions.json:13371   "CrewBattleNode503": {
ExportRegions.json:13372       "name": "/Lotus/Language/Locations/CrewBattleNode503",
ExportRegions.json:13374       "systemName": "/Lotus/Language/Locations/Venus_SPACE",
ExportRegions.json:13375       "nodeType": 0,
ExportRegions.json:13377       "missionType": "MT_RAILJACK",
ExportRegions.json:13378       "missionName": "/Lotus/Language/Missions/MissionName_RailjackExterminate",
```

Line citations for the export records (file → line):

| node | `ExportRegions.json` | `dict.en.json` (node name) | `dict.en.json` (system) |
| --- | --- | --- | --- |
| Bifrost Echo | 13371 (`CrewBattleNode503`) | 21440 | 21692 (`…/Locations/Venus_SPACE` → `"Venus Proxima"`) |
| Beacon Shield Ring | 13261 (`CrewBattleNode511`) | 21442 | 21692 |
| Luckless Expanse | 13321 (`CrewBattleNode515`) | 21446 | 21692 |
| Falling Glory | 13346 (`CrewBattleNode514`) | 21445 | 21692 |
| Arva Vector | 13590 (`CrewBattleNode504`) | 21441 | 21589 (`…/Neptune_SPACE` → `"Neptune Proxima"`) |
| Nu-gua Mines | 13615 (`CrewBattleNode516`) | 21447 | 21589 |
| Enkidu Ice Drifts | 13692 (`CrewBattleNode521`) | 21448 | 21589 |
| Sovereign Grasp | 13717 (`CrewBattleNode524`) | 21450 | 21589 |
| Seven Sirens | 13769 (`CrewBattleNode527`) | 21453 | 21614 (`…/Pluto_SPACE` → `"Pluto Proxima"`) |
| Obol Crossing | 13794 (`CrewBattleNode528`) | 21454 | 21614 |
| Fenton's Field | 13819 (`CrewBattleNode531`) | 21456 | 21614 |
| Profit Margin | 13844 (`CrewBattleNode529`) | 21455 | 21614 |
| The Kuva Wytch | 14181 (`CrewBattleNode560`) | 21239 (different key path, see §4) | 21682 (`…/Uranus_SPACE` → `"Uranus Proxima"`) |

Mission-name English text (`dict.en.json`):

```
22420:    "/Lotus/Language/Missions/MissionName_RailjackDefense": "DEFENSE",
22421:    "/Lotus/Language/Missions/MissionName_RailjackExterminate": "EXTERMINATE",
22423:    "/Lotus/Language/Missions/MissionName_RailjackSpace": "SKIRMISH + ASSASSINATE",
22425:    "/Lotus/Language/Missions/MissionName_RailjackSurvival": "SURVIVAL",
22426:    "/Lotus/Language/Missions/MissionName_RailjackVolatile": "VOLATILE",
```

## 4. The dedicated Ash Railjack mission (`…/AshRJMissionName` → `CrewBattleNode560`)

Its export record, raw from the file:

```
ExportRegions.json:14181    "CrewBattleNode560": {
ExportRegions.json:14182        "name": "/Lotus/Language/JadeShadowsPart2Constellations/AshRJMissionName",
ExportRegions.json:14183        "systemIndex": 6,
ExportRegions.json:14184        "systemName": "/Lotus/Language/Locations/Uranus_SPACE",
ExportRegions.json:14185        "nodeType": 0,
ExportRegions.json:14187        "missionType": "MT_RAILJACK",
ExportRegions.json:14188        "missionName": "/Lotus/Language/Missions/MissionName_RailjackSpace",
ExportRegions.json:14189        "faction": "FC_CORPUS",
ExportRegions.json:14190        "minEnemyLevel": 65,
ExportRegions.json:14191        "maxEnemyLevel": 70,
ExportRegions.json:14193        "rewardManifests": [
ExportRegions.json:14194            "/Lotus/Types/Game/MissionDecks/JadeShadowsConstellationsRewards/JS2KuvaWytchRewards"
ExportRegions.json:14195        ],
ExportRegions.json:14196        "tileset": "GrineerRailjackSaturnTileset",
ExportRegions.json:14197        "levelOverride": "/Lotus/Levels/JadeShadowsPart2Mission/Proc/JS2MAshSpace",
ExportRegions.json:14198        "enemySpec": "/Lotus/Types/JadeShadowsPart2Mission/EnemySpecs/JadeShadowPart2EnemySpecsAshMission",
ExportRegions.json:14199        "missionReward": { "credits": 130000 },
ExportRegions.json:14202        "nextNodes": []
ExportRegions.json:14203    }
```

and its English text:

```
dict.en.json:21239    "/Lotus/Language/JadeShadowsPart2Constellations/AshRJMissionName": "The Kuva Wytch",
dict.en.json:21682    "/Lotus/Language/Locations/Uranus_SPACE": "Uranus Proxima",
dict.en.json:22423    "/Lotus/Language/Missions/MissionName_RailjackSpace": "SKIRMISH + ASSASSINATE",
```

As a python dict:

```python
Ash_rj_mission = {
    'region_key':     'CrewBattleNode560',                                   # ExportRegions.json:14181
    'node_name_key':  '/Lotus/Language/JadeShadowsPart2Constellations/AshRJMissionName',
    'node':           'The Kuva Wytch',                                      # dict.en.json:21239
    'systemName':     '/Lotus/Language/Locations/Uranus_SPACE',
    'system_english': 'Uranus Proxima',                                      # dict.en.json:21682
    'missionType':    'MT_RAILJACK',
    'mission_english':'SKIRMISH + ASSASSINATE',                              # dict.en.json:22423
    'nodeType':       0,
    'levelOverride':  '/Lotus/Levels/JadeShadowsPart2Mission/Proc/JS2MAshSpace',
    'rewardManifests':['/Lotus/Types/Game/MissionDecks/JadeShadowsConstellationsRewards/JS2KuvaWytchRewards'],
}
```

Whether the official drop table lists **any** Ash part under that node — real output:

```
drop table, Uranus / "The Kuva Wytch": 0 Ash entries; itemNames = ['Sirius & Orion Blueprint', 'Sirius & Orion Chassis Blueprint', 'Sirius & Orion Neuroptics Blueprint', 'Sirius & Orion Systems Blueprint', 'Pride Blueprint', 'Pride Blade Blueprint', 'Pride Handle Blueprint']
drop table, Uranus / "The Kuva Wytch (Extra)": ['Primary Compression', 'Arcane Sculptor', 'Secondary Cryogenic', 'Melee Assimilation']
Uranus rows whose itemName contains "Ash": []
```

**Plainly: the official drop table lists NO Ash part under `The Kuva Wytch`, and no Ash part anywhere on Uranus (0 rows).** Despite the internal name key saying "Ash RJ mission", the node's reward pool is Pride (blade/handle/blueprint) and Sirius & Orion (blueprint + 3 components), 14.29% each in a flat pool, plus an end-of-mission pool of four Archon-style mods at 25% each. The wiki's own node page agrees — <https://wiki.warframe.com/w/The_Kuva_Wytch> lists exactly those seven 14.29% Pride / Sirius & Orion rewards and the same four 25% extras, region "Uranus Proxima", mission type "Skirmish + Assassinate", "Internal Name `CrewBattleNode560`", introduced Update 43: Jade Shadows: Constellations (2026-06-17). Its sibling `CrewBattleNode561` is keyed `…/GarudaRJMissionName` → "Scoria's Angel" and drops Wrath + Sirius & Orion; neither of the two Ash/Garuda-named railjack nodes drops that frame's parts.

## 5. The wiki's own answer

URL: <https://wiki.warframe.com/w/Ash> — "Acquisition" section (the page transcludes <https://wiki.warframe.com/w/Ash/Main>; the repo's cache of that source page is `data/dropdata/wiki/ash_main__b70779ae.json`, fetched epoch `1790479035`). Fetched live with `web_extract`; plain curl gets the Cloudflare challenge.

Quoted verbatim (Acquisition prose):

> Ash's main blueprint can be purchased from the Market. Ash's component blueprints are obtained from Venus Proxima (Systems), Neptune Proxima (Neuroptics), and Pluto Proxima (Chassis) Survival, Defense, Exterminate, and Volatile missions.
>
> Alternatively, upon completion of The Duviri Paradox, Ash's main and component blueprints can be earned from The Circuit. By selecting him on the rotating week he is available, players can earn all his blueprints after reaching Tier 10 rewards.

Quoted verbatim (History section):

> - Prior to Update 29.10 (2021-03-19), Ash's components dropped from Manics.
> - Prior to Update 17.0 (2015-07-31), Ash's components dropped from Tyl Regor on Titania, Uranus.

The wiki's per-part table, verbatim chance cells:

```
Systems Blueprint  | Venus Proxima Defense / A    | 13.33%
Systems Blueprint  | Venus Proxima Volatile       |  4.88%
Systems Blueprint  | Venus Proxima Exterminate    |  4.88%
Systems Blueprint  | Venus Proxima Survival / A   | 13.33%
Neuroptics Blueprint | Neptune Proxima Defense / A | 12.50%
Neuroptics Blueprint | Neptune Proxima Survival / A| 12.50%
Neuroptics Blueprint | Neptune Proxima Exterminate |  4.71%
Neuroptics Blueprint | Neptune Proxima Volatile    |  4.71%
Chassis Blueprint  | Pluto Proxima Defense / A    | 13.33%
Chassis Blueprint  | Pluto Proxima Volatile       |  4.82%
Chassis Blueprint  | Pluto Proxima Survival / A   | 13.33%
Chassis Blueprint  | Pluto Proxima Exterminate    |  4.82%
```

**Does it agree with the drop table? Yes — exactly**, once the export names the mission variant the drop table leaves as `Skirmish`:

| part | Proxima (export) | mode (export `missionName`) | wiki % | drop-table node | drop-table % | agree |
| --- | --- | --- | --- | --- | --- | --- |
| Systems | Venus Proxima | DEFENSE | 13.33 | Falling Glory / A | 13.33 | ✅ |
| Systems | Venus Proxima | SURVIVAL | 13.33 | Luckless Expanse / A | 13.33 | ✅ |
| Systems | Venus Proxima | EXTERMINATE | 4.88 | Bifrost Echo (flat) | 4.88 | ✅ |
| Systems | Venus Proxima | VOLATILE | 4.88 | Beacon Shield Ring (flat) | 4.88 | ✅ |
| Neuroptics | Neptune Proxima | DEFENSE | 12.50 | Arva Vector / A | 12.5 | ✅ |
| Neuroptics | Neptune Proxima | SURVIVAL | 12.50 | Enkidu Ice Drifts / A | 12.5 | ✅ |
| Neuroptics | Neptune Proxima | EXTERMINATE | 4.71 | Nu-Gua Mines (flat) | 4.71 | ✅ |
| Neuroptics | Neptune Proxima | VOLATILE | 4.71 | Sovereign Grasp (flat) | 4.71 | ✅ |
| Chassis | Pluto Proxima | DEFENSE | 13.33 | Obol Crossing / A | 13.33 | ✅ |
| Chassis | Pluto Proxima | SURVIVAL | 13.33 | Fenton's Field / A | 13.33 | ✅ |
| Chassis | Pluto Proxima | EXTERMINATE | 4.82 | Seven Sirens (flat) | 4.82 | ✅ |
| Chassis | Pluto Proxima | VOLATILE | 4.82 | Profit Margin (flat) | 4.82 | ✅ |

Two things the wiki adds that the drop table does not carry: the main blueprint's sources (Market / The Circuit — 0 rows in the drop table) and the Proxima/region wording. Nothing in the wiki contradicts the drop table.

## 6. Verdict

The correct player-facing hierarchy for the Ash Systems Blueprint drop is **Railjack → Venus Proxima → `<node>` (`<mode>`)** — four cases, `Bifrost Echo` (Exterminate, 4.88%), `Beacon Shield Ring` (Volatile, 4.88%), `Luckless Expanse` (Survival, rotation A, 13.33%) and `Falling Glory` (Defense, rotation A, 13.33%); the family hierarchy is the same shape with **Neptune Proxima** for Neuroptics (`Arva Vector` Defense, `Enkidu Ice Drifts` Survival — both 12.5% A; `Nu-gua Mines` Exterminate, `Sovereign Grasp` Volatile — both 4.71% flat) and **Pluto Proxima** for Chassis (`Obol Crossing` Defense, `Fenton's Field` Survival — 13.33% A; `Seven Sirens` Exterminate, `Profit Margin` Volatile — 4.82% flat), with the main `Ash Blueprint` coming from the Market or, post-The Duviri Paradox, The Circuit (Tier 10 of his rotating week) rather than from any mission. **The drop table alone is not sufficient to state it**, for three reasons that each need the export or the wiki: (1) the drop table labels all 12 rows with the bare Star Chart planet (`Venus` / `Neptune` / `Pluto`) although none of the four Venus nodes exists on the Venus Star Chart — every one of them is a `MT_RAILJACK` region whose `systemName` resolves through `dict.en.json` to `Venus Proxima` / `Neptune Proxima` / `Pluto Proxima`; (2) the drop table's `gameMode` is the constant `Skirmish` for all 12 rows, so Survival / Defense / Exterminate / Volatile can only come from the export's `missionName` key (or the wiki), never from the drop table's label; (3) the main blueprint has no drop-table row at all, so the Market / Circuit paths exist only in the wiki. The wiki's numbers are identical to the drop table's, so nothing here is a chance-value dispute — the missing fact is the navigation hierarchy, and it must be joined in from `ExportRegions.json` + `dict.en.json`. The dedicated Ash-named railjack node (`CrewBattleNode560`, `…/AshRJMissionName` → "The Kuva Wytch", Uranus Proxima, Skirmish + Assassinate) is **not** an Ash source: the drop table lists 0 Ash parts there (and 0 on all of Uranus); its pool is Pride and Sirius & Orion (14.29% each) plus four 25% mods in an extra pool, and the wiki node page agrees, so it must not be surfaced as an Ash acquisition path.

## 7. Repro + gotchas found while doing this

- Reproduce §1/§2 with the heredoc in §1, §3/§4 with the heredoc in §3, all run from `F:\VSC Projects\wfm-dashboard`.
- `data/dropdata/missionRewards.json` is a **single line** — file:line citations are impossible for it; cite the JSON path (e.g. `missionRewards["Venus"]["Bifrost Echo"]["rewards"][10]`).
- Some railjack rows store `rewards` as a **flat list** instead of an A/B/C dict (six of the twelve Ash rows: Bifrost Echo, Beacon Shield Ring, Nu-Gua Mines, Sovereign Grasp, Seven Sirens, Profit Margin). A reader that assumes `rewards` is always a rotation dict will crash or silently drop those rows; the official wiki still calls these "A rotations".
- Case mismatch: drop table `Nu-Gua Mines` vs export/dictionary `Nu-gua Mines`. `scripts/acquisition_hierarchy.py` matches display names case-sensitively, so its own resolver fails this one node today:

  ```
  Neptune/Nu-Gua Mines   -> Neptune → Nu-Gua Mines   unresolved=['node not in the game export']
  # every other Ash node resolves, e.g.
  Venus/Falling Glory    -> Railjack → Venus Proxima → Falling Glory   unresolved=[]
  Pluto/Profit Margin    -> Railjack → Pluto Proxima → Profit Margin   unresolved=[]
  ```
- The drop-table planet label and the export system disagree by design (Venus vs Venus Proxima); `acquisition_hierarchy.resolve()` keeps the label as `drop_table_label` provenance and takes the system from the export.
