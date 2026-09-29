# WFCD `warframe-items` — real JSON shapes for a build calculator

**Source of truth:** `github.com/WFCD/warframe-items`, raw files under `/data/json/` on `master`.
Everything in this file was **fetched and parsed on the machine on 2026-09-29 (AUS Eastern, UTC+10)**, not
written from memory. Commands used:

```bash
curl -s -o Warframes.json https://raw.githubusercontent.com/WFCD/warframe-items/master/data/json/Warframes.json
curl -s -o Primary.json   https://raw.githubusercontent.com/WFCD/warframe-items/master/data/json/Primary.json
curl -s -o Mods.json      https://raw.githubusercontent.com/WFCD/warframe-items/master/data/json/Mods.json
```

| File | Bytes | md5 | Top-level shape |
|---|---|---|---|
| `Warframes.json` | 354,015 | `e8930dff5ec98e8723e99fd67f861a0a` | **array** of 123 objects |
| `Primary.json` | 448,177 | `e333eebf0e1b222bfa03d4895168b125` | **array** of 197 objects |
| `Mods.json` | 5,761,696 | `71dc4cb24b272e9a532bcf91fabbb9ac` | **array** of 1,809 objects |

All three are **JSON arrays of item objects**, not objects keyed by id. Nothing is keyed; you must index by
`uniqueName` (or `name`, with the duplicate-name caveat in §3.4) yourself.

> ⚠️ **`Weapons.json` does not exist.** `curl -I …/data/json/Weapons.json` → **HTTP/1.1 404**. Rifles **and
> shotguns** both live in `Primary.json`; the rest of the directory (from `api.github.com/repos/WFCD/warframe-items/contents/data/json`) is
> `Arcanes, Arch-Gun, Arch-Melee, Archwing, Components, Enemy, Fish, Gear, Glyphs, Honoria, Melee, Misc,
> Mods, Node, Pets, Primary, Quests, Railjack, Relics, Resources, Secondary, SentinelWeapons, Sentinels,
> Sigils, Skins, Warframes, i18n`.

---

## 1. `Warframes.json` — where a frame's base stats live

### 1.1 Field names (verified)

`Excalibur`'s object has exactly these keys (123/123 frames share `uniqueName, name, health, shield, armor,
stamina, power, abilities, type, category, tradable, isPrime, masterable`):

```
uniqueName name health shield armor stamina power abilities type category tradable isPrime
masterable description codexSecret masteryReq sprintSpeed productCategory imageName wikiAvailable
conclave introduced polarities sprint wikiaUrl releaseDate passiveDescription buildPrice buildTime
skipBuildTimePrice buildQuantity consumeOnBuild components color sex aura marketCost vaulted
estimatedVaultDate vaultDate exalted bpCost exilusPolarity wikiaThumbnail drops excludeFromCodex
```

**The stat-carrying keys a calculator needs:**

| Concept | Key | Type | Example (`Excalibur` / `Mesa Prime`) |
|---|---|---|---|
| Health (rank 0 base) | `health` | int | `270` / `400` |
| Shield (rank 0 base) | `shield` | int | `270` / `180` |
| Armor | `armor` | int | `240` / `135` |
| **Energy pool** | **`power`** | int | `100` / `140` |
| Sprint speed (raw float) | `sprintSpeed` | float or int | `1` / `1.1` |
| Sprint speed (rounded) | `sprint` | same stat, coarser value | `1` / `1.1` |
| Stamina (legacy) | `stamina` | int | `3` / `3` |
| **Aura polarity** | **`aura`** | string (or array — see 1.3) | *absent* for Excalibur / `"madurai"` for Mesa Prime |
| Mod polarities | `polarities` | array of strings | `["vazarin","madurai"]` / `["naramon","naramon","vazarin","madurai"]` |
| Exilus slot polarity | `exilusPolarity` | string | present on only 10/123 frames |
| Rank requirement | `masteryReq` | int | `0` |
| Exalted weapons | `exalted` | array of `uniqueName` strings | present on 35/123 frames |

**Traps:**
- **Energy is `power`, not `energy`.** There is no `energy` key on a Warframe.
- `sprintSpeed` is the raw float, `sprint` the rounded UI value — they agree exactly (1.0, 1.1, …) on 110/123
  frames and differ only in float precision on 13 frames (`Atlas 0.9` vs `0.89999998`; `Frost/Rhino/Saryn/
  Sevagoth/Voruna/Grendel(/Prime) 0.95` vs `0.94999999`; `Follie 0.95` vs `0.94999999`; `Qorvex 0.9` vs
  `0.89999998`; `Xaku Prime 1.07` vs `1.0700001`). Use `sprintSpeed`; `Helminth` is the one entry with
  neither key.
- `polarities` is a **list with repeats** (Mesa Prime has `naramon` twice = two Naramon slots). Its length is
  the count of polarized mod slots, not a set of polarities.

### 1.2 Rank scaling — **the data is Rank 0, not Rank 30**

There are **no rank fields** on a Warframe object (no `rank`, `maxRank`, `healthAtRank30`, …). The values are
the game's **rank-0 base stats**, verified two ways:

1. **Cross-check against the wiki's rank-30 statements.** WFCD `Excalibur.shield = 270` and
   `Excalibur.health = 270`; the wiki states *"Excalibur has **240** base Armor and **370** base Shields at
   rank 30"* (<https://wiki.warframe.com/w/Armor>) and *"Excalibur's **Rank 30 Health** stat is **370**"*
   (<https://wiki.warframe.com/w/Warframes>). 270 = 370 − 100 ⇒ WFCD is one rank-up short of rank 30, i.e.
   rank 0.
2. **The wiki's rank rule fits exactly:** *"+10 Health capacity every 3 ranks… For a total of **+100 Health,
   +100 Shields and +50 Energy capacity at Rank 30**"* (<https://wiki.warframe.com/w/Warframes>).
   So `Excalibur` rank 30 = 270+100 health = **370**, 270+100 shield = **370**, 100+50 energy = **150**,
   armor unchanged at **240** (armor is rank-invariant except Nidus/Lavos/Kullervo).
   Per-frame exceptions to the +100/+100/+50 defaults are tabulated in `frame-stat-math.md` §3.5.

**Engine implication:** add the rank bonus **before** applying mod multipliers
(`(base + rankBonus) × (1 + Σ)`), which is exactly the wiki's Health formula
(`frame-stat-math.md` §3.1/§4).

### 1.3 `aura` — string, list, or absent

Census over all 123 entries:

```
naramon: 54   madurai: 39   vazarin: 17   absent: 8   "aura": 3   zenurik: 1   ('aura','vazarin'): 1
```

Absent on exactly: `Bonewidow, Excalibur, Helminth, Nekros, Nekros Prime, Sevagoth, Sevagoth Prime, Voidrig`
— and that absence is **meaningful, not a data gap**: the wiki's Excalibur page states *"Aura Polarity
**None**"* and *"He is the first of two Warframes with an unpolarized Aura slot, Nekros being the second"*
(<https://wiki.warframe.com/w/Excalibur>). So: **no `aura` key ⇒ unpolarized aura slot ⇒ no drain halving.**
One entry carries a *list* instead of a string, so type-check before use.

### 1.4 Real trimmed snippet (`Warframes.json` → Excalibur, and the head of Mesa Prime)

```json
{
 "uniqueName": "/Lotus/Powersuits/Excalibur/Excalibur",
 "name": "Excalibur",
 "description": "Excalibur epitomizes the warrior spirit. His master swordsmanship deals high damage. He is the embodiment of martial excellence.",
 "health": 270,
 "shield": 270,
 "armor": 240,
 "stamina": 3,
 "power": 100,
 "codexSecret": false,
 "masteryReq": 0,
 "sprintSpeed": 1,
 "passiveDescription": "Excalibur deals |DAMAGE|% increased damage and attacks |SPEED|% faster when wielding swords.",
 "exalted": ["/Lotus/Powersuits/Excalibur/DoomSword"],
 "abilities": [
  {"uniqueName": "/Lotus/Powersuits/Excalibur/Abilities/SlashDashNewAbility", "name": "Slash Dash", "imageName": "Power04.png"},
  {"uniqueName": "/Lotus/Powersuits/Excalibur/Abilities/RadialBlindAbility", "name": "Radial Blind", "imageName": "Power01.png"}
 ],
 "productCategory": "Suits",
 "components": [{"uniqueName": "/Lotus/Types/Recipes/WarframeRecipes/ExcaliburBlueprint", "itemCount": 1}],
 "type": "Warframe",
 "imageName": "Excalibur.png",
 "category": "Warframes",
 "tradable": false,
 "polarities": ["vazarin", "madurai"],
 "sex": "Male",
 "sprint": 1,
 "wikiaUrl": "https://wiki.warframe.com/w/Excalibur",
 "releaseDate": "2012-10-25",
 "isPrime": false,
 "masterable": true
}
```

```json
{
 "uniqueName": "/Lotus/Powersuits/Cowgirl/MesaPrime",
 "name": "Mesa Prime",
 "health": 400,
 "shield": 180,
 "armor": 135,
 "stamina": 3,
 "power": 140,
 "masteryReq": 0,
 "sprintSpeed": 1.1,
 "type": "Warframe",
 "category": "Warframes",
 "aura": "madurai",
 "polarities": ["naramon", "naramon", "vazarin", "madurai"],
 "isPrime": true,
 "masterable": true
}
```

---

## 2. Weapons — `Primary.json` (rifle **and** shotgun)

`Tigris Prime` (`type: "Shotgun"`) is in `Primary.json`, so the file covers both. 197 objects.

### 2.1 Field names (verified for both Soma Prime and Tigris Prime — identical key sets)

```
uniqueName name description imageName category type productCategory slot masteryReq tradable isPrime
masterable codexSecret damage damagePerShot totalDamage criticalChance criticalMultiplier procChance
fireRate magazineSize reloadTime multishot accuracy disposition omegaAttenuation trigger noise
polarities exilusPolarity tags vaulted vaultDate estimatedVaultDate buildPrice buildTime
skipBuildTimePrice buildQuantity consumeOnBuild components attacks introduced releaseDate
wikiAvailable wikiaThumbnail wikiaUrl
```

| Concept | Key | Soma Prime (rifle) | Tigris Prime (shotgun) |
|---|---|---|---|
| Damage per type | `damage` (object, §2.2) | `{total:12, impact:1.2, puncture:4.8000002, slash:6, …}` | `{total:195, impact:19.5, puncture:19.5, slash:156, …}` |
| Total damage | `totalDamage` | `12` | `195` |
| Damage, **positional** | `damagePerShot` (20-element array) | `[1.2, 4.8000002, 6, 0, 0, …]` | same shape |
| Crit chance | `criticalChance` (**decimal**) | `0.30000001` | `0.1` |
| Crit multiplier | `criticalMultiplier` | `3` | `2` |
| **Status chance** | **`procChance`** (decimal) | `0.10000002` | `0.11250001` |
| Fire rate | `fireRate` | `15.000001` | `2` |
| Magazine | `magazineSize` | `200` | `2` |
| Reload (s) | `reloadTime` | `3` | `1.8` |
| Multishot | `multishot` | `1` | `8` |
| Accuracy | `accuracy` | `28.571428` | `9.090909` |
| Riven disposition | `disposition` (int 1–5) | `3` | `3` |
| Riven attenuation | `omegaAttenuation` (float) | `1.1` | `0.94999999` |
| **Weapon polarities** | **`polarities`** (array of strings) | `["madurai","madurai"]` | `["madurai","naramon"]` |
| Exilus polarity | `exilusPolarity` | `"naramon"` | `"naramon"` |
| Loadout slot | `slot` | `1` | `1` |
| Kind | `type` | `"Rifle"` | `"Shotgun"` |
| Category | `category` | `"Primary"` | `"Primary"` |
| Trigger | `trigger` | `"Auto"` | `"Duplex"` |
| Noise | `noise` | `"Alarming"` | `"Alarming"` |
| Vault state | `vaulted` / `vaultDate` | `true` / `"2016-11-22"` | `true` |

### 2.2 The `damage` object — exact keys

Both weapons carry the same 21 keys, **always present even when zero** (so `damage.heat` is `0`, not missing):

```json
"damage": {
  "total": 195,
  "impact": 19.5, "puncture": 19.5, "slash": 156,
  "heat": 0, "cold": 0, "electricity": 0, "toxin": 0,
  "blast": 0, "radiation": 0, "gas": 0, "magnetic": 0, "viral": 0, "corrosive": 0,
  "void": 0, "tau": 0, "cinematic": 0,
  "shieldDrain": 0, "healthDrain": 0, "energyDrain": 0,
  "true": 0
}
```

Note `void`, `tau`, `cinematic` and the three `*Drain` pseudo-types are non-combat/placeholder types in live
data — do not sum them into total damage type counts without deciding what those mean. `total` is the sum of
the physical + elemental entries in this object (12 = 1.2 + 4.8 + 6 for Soma Prime).

### 2.3 `attacks[]` — a second, differently-shaped damage view (and a units trap)

```json
"attacks": [
  {
   "name": "Normal Attack",
   "speed": 2,
   "crit_chance": 10,
   "crit_mult": 2,
   "status_chance": 11.25,
   "shot_type": "Hit-Scan",
   "falloff": {"start": 10, "end": 20, "reduction": 0.4872},
   "damage": {"impact": 19.5, "slash": 156, "puncture": 19.5}
  }
]
```

⚠️ **Units differ between the top-level fields and `attacks[]`:** top-level `criticalChance` is `0.1`
(decimal), while `attacks[0].crit_chance` is `10` (**percent**). Same for `procChance` `0.11250001` vs
`status_chance` `11.25`. `attacks[].damage` also carries **only** impact/puncture/slash (no zero-filled
elemental keys) — for Soma Prime it even has a second element, `"Incarnon Form"`, with different stats.
Pick one representation; do not mix them.

### 2.4 Real trimmed snippet (`Primary.json` → Tigris Prime)

```json
{
 "name": "Tigris Prime",
 "uniqueName": "/Lotus/Weapons/Tenno/LongGuns/PrimeTigris/PrimeTigris",
 "damagePerShot": [19.5, 19.5, 156, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
 "totalDamage": 195,
 "criticalChance": 0.1,
 "criticalMultiplier": 2,
 "procChance": 0.11250001,
 "fireRate": 2,
 "masteryReq": 13,
 "productCategory": "LongGuns",
 "slot": 1,
 "accuracy": 9.090909,
 "omegaAttenuation": 0.94999999,
 "noise": "Alarming",
 "trigger": "Duplex",
 "magazineSize": 2,
 "reloadTime": 1.8,
 "multishot": 8,
 "type": "Shotgun",
 "damage": { "total": 195, "impact": 19.5, "puncture": 19.5, "slash": 156, "heat": 0, "cold": 0,
             "electricity": 0, "toxin": 0, "blast": 0, "radiation": 0, "gas": 0, "magnetic": 0,
             "viral": 0, "corrosive": 0, "void": 0, "tau": 0, "cinematic": 0, "shieldDrain": 0,
             "healthDrain": 0, "energyDrain": 0, "true": 0 },
 "category": "Primary",
 "polarities": ["madurai", "naramon"],
 "exilusPolarity": "naramon",
 "disposition": 3,
 "isPrime": true,
 "vaulted": true,
 "vaultDate": "2016-11-22",
 "masterable": true
}
```

---

## 3. `Mods.json` — including the field that **no longer exists**

1,809 mods, top-level **array**.

### 3.1 Key census (count of mods carrying each key — this is the whole schema in one table)

```
uniqueName 1809   name 1809   type 1809   imageName 1809   category 1809   tradable 1809
isPrime 1809   masterable 1809
polarity 1790   rarity 1790   codexSecret 1790   baseDrain 1790   fusionLimit 1790
wikiAvailable 1630   wikiaUrl 1630   transmutable 1630
introduced 1628   releaseDate 1628   levelStats 1625   wikiaThumbnail 1590   compatName 1586
drops 1399
isAugment 457   isUtility 195   excludeFromCodex 158   description 142
modSet 72   isExilus 37   numUpgradesInSet 19   stats 19   upgradeEntries 17
availableChallenges 7   modSetValues 5   buffSet 2
upgrades        0     ← DOES NOT EXIST
upgradeTypes    0     ← DOES NOT EXIST
```

### 3.2 ⚠️ `upgrades` / `upgradeTypes` are **gone** — there is no numeric effect array

Verified three ways on the live file:
- key census above: **0 of 1,809** mods have `upgrades` or `upgradeTypes`;
- literal grep of the raw file text: only `"upgradeEntries"` (17) and `"upgradeValues"` (241) appear — no
  `"upgrades"`, no `"upgradeTypes"`, no `"upgrade_type"`, no `"operation"`;
- same test against an older build tag (`v1.1275.2`, `v1.1253.2377`): also **0**. So this is not a
  regression in today's master; the numeric `upgrades` array this task expected is simply not in the file
  and has not been for a long time.

**What exists instead, for numeric effects, in order of usefulness:**

1. **`levelStats` — per-rank *display strings* (1,625 mods).** This is the only per-rank effect data for an
   ordinary mod, and the numbers must be **parsed out of the string**.
   Shape: an array with `fusionLimit + 1` entries (rank 0 … rank N), each `{"stats": [ …strings… ]}`.
2. **`upgradeEntries` — real numeric data, but only on 17 mods** (Riven mods and Railjack "Unfused
   Artifact" mods). Shape:
   ```json
   "upgradeEntries": [
     {"tag": "WeaponCritChanceMod", "prefixTag": "crita", "suffixTag": "cron",
      "upgradeValues": [{"value": 0.016666001, "locTag": "|val|% Critical Chance"}]}
   ]
   ```
   (values are decimals per rank-unit; Riven entries also use `baseDrain: -1812070400, fusionLimit: 592` as
   sentinels — never do arithmetic with those two numbers on Riven entries.)
3. **`stats` — mod-set effects, 19 mods**, free-text per rank, e.g. `"40% Energy spent on abilities is
   converted to Shields."`; `numUpgradesInSet` gives the count.
4. **`modSetValues` — 5 mods** (Umbral/Sacrificial set), a plain float array: `[0.25, 0.75]`.

**Engine implication:** to turn a mod into numeric modifiers, parse `levelStats[rank].stats[]` strings.
Grammar actually seen in the data: `±<number>% <Stat Name>` (e.g. `+165% Damage`, `+100% Critical Damage`,
`+90% Multishot`, `+100% Health`, `-60% Ability Duration`), sometimes several per rank, sometimes with
`\n`-escaped sub-sentences, conditionals, or colour tags (`+1% <DT_SENTIENT>Tau Resistance`). Parse as
`^(?P<sign>[+-])?(?P<value>\d+(?:\.\d+)?)% (?P<stat>.+)$` and keep the raw string as an escape hatch —
`galvanized`/arcane-style conditionals (e.g. Galvanized Aptitude rank 0:
`["+7.3% Status Chance", "On Kill:\\n+3.6% Direct Damage per Status Type affecting the target for 20s. Stacks up to 2x."]`)
will not parse cleanly and must be classified by hand or left unscored.

### 3.3 Three worked examples (damage / crit damage / multishot)

All three are the **non-Beginner, non-Expert** entries — see the duplicate-name warning next.

**Serration** (rifle base damage)
```json
{
 "uniqueName": "/Lotus/Upgrades/Mods/Rifle/WeaponDamageAmountMod",
 "name": "Serration",
 "polarity": "madurai",
 "rarity": "Uncommon",
 "baseDrain": 4,
 "fusionLimit": 10,
 "compatName": "Rifle",
 "type": "Primary Mod",
 "levelStats": [
  {"stats": ["+15% Damage"]}, {"stats": ["+30% Damage"]}, {"stats": ["+45% Damage"]},
  {"stats": ["+60% Damage"]}, {"stats": ["+75% Damage"]}, {"stats": ["+90% Damage"]},
  {"stats": ["+105% Damage"]}, {"stats": ["+120% Damage"]}, {"stats": ["+135% Damage"]},
  {"stats": ["+150% Damage"]}, {"stats": ["+165% Damage"]}
 ],
 "imageName": "RifleDamageAmountMod.jpg",
 "category": "Mods",
 "tradable": true
}
```
11 entries = `fusionLimit 10` + 1 ⇒ max rank `+165% Damage`. ✅ matches the in-game mod.

**Vital Sense** (rifle crit damage)
```json
{
 "uniqueName": "/Lotus/Upgrades/Mods/Rifle/WeaponCritDamageMod",
 "name": "Vital Sense",
 "polarity": "madurai",
 "rarity": "Rare",
 "baseDrain": 4,
 "fusionLimit": 5,
 "compatName": "Rifle",
 "type": "Primary Mod",
 "levelStats": [
  {"stats": ["+20% Critical Damage"]}, {"stats": ["+40% Critical Damage"]}, {"stats": ["+60% Critical Damage"]},
  {"stats": ["+80% Critical Damage"]}, {"stats": ["+100% Critical Damage"]}, {"stats": ["+120% Critical Damage"]}
 ],
 "category": "Mods"
}
```
6 entries = `fusionLimit 5` + 1 ⇒ max `+120% Critical Damage`. ✅

**Split Chamber** (rifle multishot)
```json
{
 "uniqueName": "/Lotus/Upgrades/Mods/Rifle/WeaponFireIterationsMod",
 "name": "Split Chamber",
 "polarity": "madurai",
 "rarity": "Rare",
 "baseDrain": 10,
 "fusionLimit": 5,
 "compatName": "Rifle",
 "type": "Primary Mod",
 "levelStats": [
  {"stats": ["+15% Multishot"]}, {"stats": ["+30% Multishot"]}, {"stats": ["+45% Multishot"]},
  {"stats": ["+60% Multishot"]}, {"stats": ["+75% Multishot"]}, {"stats": ["+90% Multishot"]}
 ],
 "category": "Mods"
}
```
6 entries ⇒ max `+90% Multishot`. ✅

Other verified `levelStats` shapes worth knowing (same parse):
```
Streamline        fl=5  baseDrain=4  polarity=naramon  ["+30% Ability Efficiency" at max]
Intensify         fl=5  baseDrain=6  polarity=madurai  ["+30% Ability Strength" at max]
Vitality          fl=10 baseDrain=2  polarity=vazarin  ["+100% Health" at max]
Redirection       fl=10 baseDrain=2  polarity=vazarin  ["+100% Shield Capacity" at max]
Steel Fiber       fl=10 baseDrain=4  polarity=vazarin  ["+100% Armor" at max]
Primed Continuity fl=10 baseDrain=4  polarity=madurai  ["+55% Ability Duration" at max]
Blind Rage        fl=10 baseDrain=6  polarity=madurai  multi-stat, positive + negative:
   rank0 {"stats": ["+9% Ability Strength", "-5% Ability Efficiency"]} … max ["+99% Ability Strength","-55% Ability Efficiency"]
Fleeting Expertise fl=5 baseDrain=6  polarity=naramon  ["+60% Ability Efficiency", "-60% Ability Duration"] at max
Umbral Intensify   fl=10 baseDrain=6 polarity=umbra    ["+4% Ability Strength", "+1% <DT_SENTIENT>Tau Resistance"] at rank 0
```

### 3.4 ⚠️ `name` is **not unique** — key on `uniqueName`

Three different mods are all named `Serration` (and three `Vital Sense`, three `Split Chamber`):

| `uniqueName` | baseDrain | fusionLimit | max effect |
|---|---|---|---|
| `/Lotus/Upgrades/Mods/Rifle/Beginner/WeaponDamageAmountModBeginner` | 2 | 3 | +40% Damage, `codexSecret: true` |
| `/Lotus/Upgrades/Mods/Rifle/Intermediate/WeaponDamageAmountModIntermediate` | 4 | 5 | +90% Damage |
| `/Lotus/Upgrades/Mods/Rifle/WeaponDamageAmountMod` | 4 | 10 | **+165% Damage** ← the real one |

A `name`-keyed lookup silently picks the Beginner variant (it appears first) and under-reports every mod
value. **Index by `uniqueName`.**

**What the ingester does about it** (found live while wiring the Phase 2 page, 2026-09-29 — the wiki's
`Module:Mods/data`, fetched `action=raw`, holds 1,635 `InternalName`s and settles all three cases):

| path segment | rows | on the wiki? | treatment |
|---|---|---|---|
| `/Beginner/` | 104 | 94 of 104 | renamed to the game's own name — **"Flawed Serration"**, `is_flawed` |
| `/Intermediate/` | 33 | **0 of 33** | `shadowed` — an internal row, no card in the game |
| `/Expert/` | 144 | 64 of 144 | the real Primed/Galvanized rows (Primed Blunderbuss) keep their names; the **75 that wear a plain mod's name** (a rank-10 "Hellfire", "Point Strike" at +275%) are `shadowed` |

`Flawed` copies are real, distinct mods (wiki: `Incompatible = Hellfire`) and keep their own row.
The 108 `shadowed` rows are hidden from the library by name, counted in `summary.mods_shadowed`, and
offered back with `?shadowed=1` — each flagged, none dropped in silence. Before this, three library
rows read "Hellfire" and the name-keyed pick landed on the rank-10 leftover: a PvE build silently got
a mod that does not exist in PvE.

### 3.5 Other fields the calculator will need

- `compatName` — the equip constraint, and **not** a clean enum: `"Rifle"`, `"WARFRAME"` (uppercase), a
  specific frame name (`"Trinity"`), item names, etc. Present on 1,586/1,809 mods.
- `type` — wider category: `"Primary Mod"`, `"Warframe Mod"`, `"Melee Mod"`, `"Mod Set Mod"`, `"Rifle Riven
  Mod"`, `"Railjack Mod"`, `"Arch-Gun Riven Mod"`, …
- `polarity` — lowercase string (`madurai`, `naramon`, `vazarin`, `zenurik`, `umbra`, `penjaga`, `aura`, …).
- `baseDrain` / `fusionLimit` — ints; drain at rank r is `baseDrain + r` (the doubling for a matching
  polarity is a UI/slot rule, **not** stored in the data).
- `isAugment` (457), `isUtility` (195), `isExilus` (37), `isPrime`, `tradable`, `excludeFromCodex`,
  `description` (142 — most mods have no description), `drops[]` (1,399) with
  `{location, type, chance, rarity}` where `chance` is a **percent number** (e.g. `1.47`, `0.09`).

---

## 4. Local cache cross-check — `data/wfcd_mods_cache.json`

The local cache is **not** a mirror of the raw file; it is a wrapper object with 7 keys:

```json
{
 "source_url": "https://raw.githubusercontent.com/WFCD/warframe-items/master/data/json/Mods.json",
 "fetched": 1790344055,
 "fetched_iso": "2026-09-25T13:47:35Z",
 "count": 1809,
 "raw_count": 1809,
 "fields": ["name","uniqueName","type","compatName","rarity","polarity","baseDrain","fusionLimit",
            "tradable","isPrime","isAugment","isExilus","isUtility","description","levelStats"],
 "mods": [ /* array of 1809 objects with only the fields above */ ]
}
```

- `count` == `raw_count` == 1809 == today's raw count, so the cache is not stale in *size*, but it is
  **filtered**: no `drops`, no `attacks`, no `modSetValues`, no `upgradeEntries`.
- The only effect data in the cache is the same `levelStats` display-string array as the raw file:
  ```json
  {"name": "Abating Link", "uniqueName": "/Lotus/Powersuits/Trinity/LinkAugmentCard",
   "type": "Warframe Mod", "compatName": "Trinity", "rarity": "Rare", "polarity": "zenurik",
   "baseDrain": 6, "fusionLimit": 3, "tradable": true, "isPrime": false, "isAugment": true,
   "levelStats": [
     {"stats": ["Link Augment: Reduces Armor Rating by 30% on enemies targeted by Link."]},
     {"stats": ["Link Augment: Reduces Armor Rating by 40% on enemies targeted by Link."]},
     {"stats": ["Link Augment: Reduces Armor Rating by 50% on enemies targeted by Link."]},
     {"stats": ["Link Augment: Reduces Armor Rating by 60% on enemies targeted by Link."]}
   ]}
  ```
  (verbatim entry from the cache, Abating Link; note the augment text is prose, not a parseable
  `±N% Stat` string).
- **So the cache does not close the gap** flagged in §3.2: whichever source the engine uses, mod numbers
  come from parsing `levelStats` strings, and the extra fields (`drops`, `modSetValues`, `upgradeEntries`)
  require the raw file.

---

## 5. Summary of shape facts the engine must code to

1. All three files are **arrays**, unkeyed. Index by `uniqueName`; never by `name` (duplicates, §3.4).
2. `Warframes.json` stats are **rank 0**; add the rank bonus (+100 HP / +100 shields / +50 energy by
   default, per-frame exceptions in `frame-stat-math.md` §3.5) **before** mod multipliers. Energy is `power`.
   `aura` absent = unpolarized; `polarities` is a list with repeats.
3. `Weapons.json` **404s** — rifles and shotguns are in `Primary.json`. Crit/status are **decimals** at the
   top level and **percent** inside `attacks[]`; `procChance` is the status chance key; `damage` is a
   zero-filled object, `damagePerShot` is a positional 20-element array.
4. `Mods.json` has **no `upgrades`/`upgradeTypes`** (verified 0/1809 and against older tags). Effect numbers
   only exist as `levelStats` display strings for normal mods, with real numerics confined to `upgradeEntries`
   on 17 Riven/Railjack mods, `stats` on 19 set mods, and `modSetValues` on 5 mods.
5. The local `wfcd_mods_cache.json` is a filtered wrapper (`mods[]`, 15 fields, source/fetch metadata), and
   carries the same string-only `levelStats` — it does not supply anything the raw file lacks.
