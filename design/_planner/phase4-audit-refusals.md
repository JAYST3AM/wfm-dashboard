# Phase 4 audit — how conditional mods are detected and refused today

Status: audit of the working tree, `F:\VSC Projects\wfm-dashboard`, 2026-09-30. Scope:
`builds/effects.py`, `validation.py`, `api.py`, `unsupported.py`, `ingest.py`, `weapons.py` against
`data/build_data.json`. No file outside `design/_planner/` was modified. Every count below is real
`python` output. Note: the entry point is `builds/api.py:63 def compute(...)`, **not** `compute_build`
— only the docstring `builds/__init__.py:21` calls it that; there is no such symbol.

## 1. Where a conditional mod is detected

Detection is a pure string test in `builds/effects.py`, called twice per stat line.

* **Markers** — `effects.py:31-36` `HARD_MARKERS`: `'on kill','on hit','on reload','on headshot',
  'on status','on critical','on slam','on roll','on dodge','stacks up to','stack up to','per status',
  'per stack','for each','each time','when ','while ','after ','upon ','during '`.
* **Timer clause** — `effects.py:37` `SECONDS_RE = re.compile(r'\bfor \d+(?:\.\d+)?\s*s\b')`.
* **The function** — `effects.py:96-101 def is_conditional(text)`: prepends `' '`, lowercases,
  returns `True` if any marker is a substring, else `bool(SECONDS_RE.search(...))`.
* Call sites: `effects.py:164` (prose line, no number) and `:178` (numbered line), both inside
  **`effects.py:143-181 def parse_stat_line(line)`**.

Shape emitted by `parse_stat_line` (`effects.py:161-162`, updated `176-180`):

```python
{'text': str, 'stat': str|None, 'value': float|None, 'unit': 'percent'|'flat'|None,
 'modelled': bool, 'conditional': bool, 'scope': 'self'|'other', 'prefix': str, 'tail': str}
```

`is_conditional` emits no code; the codes are emitted one layer up, in
`effects.py:382-446 def collect_mod_effects(mod_slots)`:

* `effects.py:421-424` — `unsupported_marker('conditional_effect', ...)` →
  `{'supported': False, 'code': 'conditional_effect', 'reason': ..., 'mod': <id>, 'slot': <idx>, 'text': <raw line>}`.
* `effects.py:429-433` — `unsupported_marker('unmodelled_effect', ...)` with extra
  `stat` (collapsed signature), `example`, `ranks`.
* Also emitted here: `mod_rank_out_of_range` (`:403`), `set_bonus` (`:436`), `riven` (`:439`), and a
  Galvanized note (`:443-445`). `unsupported_marker` shape is `effects.py:449-453`.

**Key structural fact** (`effects.py:287-294`): on a conditional line the parser calls
`bucket_conditional(...)`, **and if the line is also `not modelled` it additionally buckets into
`unmodelled`** — then `continue`s. So one conditional line lands in *two* buckets and (see §2) is
emitted as *two* markers. `parse_mod_effects` returns `{'max_rank','per_rank','rank_table','units',
'categories','linear','unmodelled','unmodelled_examples','conditional','notes'}` (`effects.py:317-328`);
`'conditional'` is a **list of cleaned strings, not stat ids** (`effects.py:274-280`, `326`).

## 2. Refusal shapes at each boundary (real output)

All blocks below are from one `python` run against `data/build_data.json` (`api.compute`),
build = Braton Prime rank 30 + **Galvanized Chamber rank 10**, slot 0.

**(a) Effect-collection output** — `collect_mod_effects`, in `result['unsupported']`:

```json
[
 {"supported": false, "code": "conditional_effect",
  "reason": "Galvanized Chamber carries a conditional effect that Phase 1 does not model: On Kill: +30% Multishot for 20s. Stacks up to 5x.",
  "mod": "/Lotus/Upgrades/Mods/Rifle/WeaponFireIterationsSPMod", "slot": 0,
  "text": "On Kill: +30% Multishot for 20s. Stacks up to 5x."},
 {"supported": false, "code": "unmodelled_effect",
  "reason": "Galvanized Chamber carries a stat Phase 1 does not model: On Kill: +2.7% Multishot for 20s. Stacks up to 5x. (ranks 0-10)",
  "mod": "/Lotus/Upgrades/Mods/Rifle/WeaponFireIterationsSPMod", "slot": 0,
  "stat": "on kill: #% multishot for #s. stacks up to #x.",
  "example": "On Kill: +2.7% Multishot for 20s. Stacks up to 5x.", "ranks": [0,1,2,3,4,5,6,7,8,9,10]},
 {"supported": false, "code": "incarnon", "reason": "Incarnon evolution stats are not modelled",
  "equipment": "/Lotus/Weapons/Tenno/Rifle/BratonPrime"}
]
```

`result['notes']` = `["Galvanized Chamber is a Galvanized mod: only its unconditional values are applied"]`.
The **same line is refused twice** (conditional + unmodelled); the two texts differ only because
`conditional` keeps the highest-rank text and `unmodelled_examples` the lowest (`effects.py:280` vs `:272`).

**(b) Validation output** — `validation.validate_build` (`validation.py:99-244`):

```json
{"ok": true, "errors": [],
 "warnings": [{"code": "unmodelled_effects",
   "message": "Galvanized Chamber carries stats the engine does not model: on kill: #% multishot for #s. stacks up to #x.",
   "severity": "warning", "mod": "/Lotus/Upgrades/Mods/Rifle/WeaponFireIterationsSPMod"}]}
```

There is **no `conditional_*` validation code at all** — `validation.py:202-207` is the only place,
an `unmodelled_effects` warning driven off `effects['unmodelled']`. A *conditional-only* mod (its
conditional line is modelled, so it is not in `unmodelled`) yields **no warning**: installing **Parry**
(`+16% chance to open enemies to Finisher`, stat `finisher_chance_on_block`) gives `warnings: []`, so
that refusal is invisible to any consumer reading only `validation`.

**(c) api.py result shape** — `api.compute` return (`api.py:97-111`). Top-level keys: `ok, build,
equipment, validation, capacity, capacity_used, capacity_remaining, result, baseline, unsupported,
unsupported_registry`. `unsupported` = `result['unsupported']` merged with
`unsupported_mod.marker(code)` coverage stubs (`api.py:92-96`). For the Galvanized build
`computed['ok'] == true` and `result['stats']['multishot'] == 1.8` (base `1.0` + the **unconditional**
+80% at rank 10; the +30% "On Kill" stack is *not* added).

## 3. Counts, computed from the ingested data

```python
from builds import data
db = data.load(); mods = list(db['mods'].values())
cond = lambda r: bool((r.get('effects') or {}).get('conditional'))
un   = lambda r: bool((r.get('effects') or {}).get('unmodelled'))
print('total', len(mods), 'cond', sum(map(cond,mods)), 'unmod', sum(map(un,mods)),
      'fine', sum(1 for r in mods if not cond(r) and not un(r)))
```

Raw output (`python` on `data/build_data.json`, 1809 mods):

```
total_mods 1809
conditional (any) 416
unmodelled (any) 1071
both 405
conditional_only 11
unmodelled_only 666
neither_fine 727
refused_either 1082
num conditional lines per mod: {0: 1393, 1: 412, 2: 4}
num unmodelled shapes per mod: {0: 738, 1: 1020, 2: 45, 3: 4, 4: 1, 5: 1}
```

* **Conditional reason:** **416** mods carry ≥1 conditional line (`db['summary']['mods_with_conditional_effects'] == 416`, `ingest.py:391`);
  **11** are conditional-only; **405** also carry an unmodelled line, and in **all 405** the conditional
  line's own signature is the unmodelled entry (checked with `effects.stat_signature`).
* **Unmodelled reason:** raw **1071** (`ingest.py:389`), but **387** of those are only "unmodelled"
  because their conditional line was double-bucketed; genuinely unmodelled (a non-conditional
  unmodelled stat) = **684**. 1131 unmodelled shape-keys total, of which **409 are conditional signatures**.
* **Otherwise fine:** **727** (no conditional and no unmodelled entry); 34 still carry `flags.set`,
  0 a riven flag, 693 have neither set/riven/augment.
* Refused for either reason: **1082**.

**Split by `type`** (`Counter(r['type'])`, top rows):

| bucket | top types |
|---|---|
| conditional (416) | Warframe 143 · Companion 57 · Primary 51 · Focus Way 39 · Secondary 31 · Melee 23 · Shotgun 17 |
| unmodelled (1071) | Warframe 345 · Companion 139 · Primary 121 · Focus Way 105 · Melee 96 · Secondary 73 |
| otherwise fine (727) | Warframe 105 · Primary 103 · Secondary 95 · Shotgun 79 · Stance 78 · Melee 77 |

**Split by `compatName`** (top rows): conditional = `null 53, WARFRAME 34, Melee 22, Shotgun 18,
Pistol 17, ANY 13, Rifle 12, COMPANION 10`; unmodelled = `null 154, WARFRAME 90, Melee 67, Pistol 43,
Shotgun 39, Rifle 35, AURA 35`; fine = `WARFRAME 105, Pistol 95, Rifle 84, Shotgun 79, Melee 72,
null 69`. Conditional mods by flag: `augment 99, exilus 54, set 17, galvanized 12, aura 5, primed 1,
umbral 0, riven 0`.

**10 examples per bucket** (`name | uniqueName`):

*conditional (any)*: Accumulating Whipclaw | `/Lotus/Powersuits/Khora/KhoraCrackAugmentCard` · Acidic Spittle | `/Lotus/Types/Friendly/Pets/CreaturePets/CreaturePrecepts/InfestedPredatorSpitAcidPrecept` · Adaptation | `/Lotus/Upgrades/Mods/Nemesis/AvatarSentientArmourMod` · Adaptation | `/Lotus/Upgrades/Mods/Warframe/AvatarResistanceOnDamageMod` · Aegis Gale | `/Lotus/Powersuits/IronFrame/IronFrameEruptionAugmentCard` · Aerial Ace | `/Lotus/Upgrades/Mods/Rifle/Event/Arbitration/JumpRefreshOnKillRifleMod` · Aerial Bond | `/Lotus/Types/Sentinels/SentinelPrecepts/VoidBond/Copilot` · Aero Agility | `/Lotus/Upgrades/Mods/Sets/Hawk/HawkModB` · Aero Periphery | `/Lotus/Upgrades/Mods/Sets/Hawk/HawkModC` · Aero Vantage | `/Lotus/Upgrades/Mods/Sets/Hawk/HawkModA`

*unmodelled (any)*: Abating Link | `/Lotus/Powersuits/Trinity/LinkAugmentCard` · Abundant Mutation | `/Lotus/Powersuits/Infestation/InfestPassiveAugmentCard` · Acid Shells | `/Lotus/Upgrades/Mods/Shotgun/Event/ProjectNightwatch/SobekNightwatchMod` · Adhesive Blast | `/Lotus/Upgrades/Mods/Rifle/WeaponGrenadeStickyMod` · Adrenaline Boost | `/Lotus/Upgrades/Mods/PvPMods/Warframe/MoreEnergyLessHealthMod` · Affinity Spike | `/Lotus/Upgrades/Focus/Tactic/Residual/MeleeXpFocusUpgrade` · Amalgam Argonak Metal Auger | `/Lotus/Upgrades/Mods/DualSource/Rifle/ArgonakDaggerMod` · Amalgam Barrel Diffusion | `/Lotus/Upgrades/Mods/DualSource/Pistol/MultishotDodgeMod` · Amalgam Daikyu Target Acquired | `/Lotus/Upgrades/Mods/DualSource/Rifle/DaikyuKatanaMod` · Acidic Spittle | `/Lotus/Types/Friendly/Pets/CreaturePets/CreaturePrecepts/InfestedPredatorSpitAcidPrecept`

*otherwise fine*: Accelerated Blast | `/Lotus/Upgrades/Mods/Shotgun/DualStat/AcceleratedBlastMod` · Accelerated Deflection | `/Lotus/Upgrades/Mods/Sentinel/SentinelShieldRechargeRateMod` · Accelerated Isotope | `/Lotus/Upgrades/Mods/Pistol/DualStat/RadiationFireratePistolMod` · Adept Surge | `/Lotus/Upgrades/Mods/PvPMods/Warframe/MoreBulletJumpLessHealthMod` · Amalgam Serration | `/Lotus/Upgrades/Mods/DualSource/Rifle/SerratedRushMod` · Amanata Pressure | `/Lotus/Weapons/Tenno/Melee/Polearms/Naginata/ShrineMaidenNaginataAugment` · Amar's Anguish | `/Lotus/Upgrades/Mods/Sets/Amar/AmarExilusMod` · Amar's Contempt | `/Lotus/Upgrades/Mods/Sets/Amar/AmarMeleeMod` · Amar's Hatred | `/Lotus/Upgrades/Mods/Sets/Amar/AmarWarframeMod` · Amarsetmod | `/Lotus/Upgrades/Mods/Sets/Amar/AmarSetMod`

*conditional_only* (all 11): Aero Periphery, Air Recon, Broad Eye, Overview (all `-X% Zoom while Aim Gliding`, stat `aim_glide_zoom`), Flawed Parry, Parry ×3 (`finisher_chance_on_block`), Flawed Provoked, Provoked ×2 (`damage_bleedout`).

## 4. What is available at the point of refusal (milestone 4.2)

The refusal is raised inside the per-slot loop of `collect_mod_effects` (`effects.py:393-445`):

| variable | source | contents |
|---|---|---|
| `slot` | `effects.py:393` | `{'kind','index','polarity','mod','rank','unlocked'}` — from `api.engine_slots` (`api.py:49-51`) |
| `mod` | `effects.py:394` | the **full ingested mod row** (`ingest.py:242-266`): `id, name, base_name, variant, is_flawed, shadowed, slug, type, compat, class, targets, rarity, polarity, base_drain, max_rank, slot, exilus_ok, flags, conclave, augment_export, effects, source` |
| `name` | `effects.py:401` | `mod['name'] or mod['id']` |
| `rank` | `effects.py:397-399` | equipped rank, defaulting to `mod['max_rank']` |
| `eff` | `effects.py:400` | the whole `parse_mod_effects` dict (`rank_table, units, categories, linear, unmodelled, unmodelled_examples, conditional, notes, per_rank, max_rank`) |
| `text` | `effects.py:420` | **the parsed condition text, verbatim** — e.g. `"On Kill: +30% Multishot for 20s. Stacks up to 5x."` ✔ |
| `flags` | `effects.py:434` | `flags.set/riven/galvanized/augment/primed/umbral/exilus/aura/stance` (`effects.py:529-545`) |

So **yes**: parsed condition text ✔, full mod row (polarity, `base_drain`, `compat`, `type`, `class`,
`targets`, `slot`, `max_rank`, `rarity`, `flags`, `source`) ✔, equipped rank ✔,
`mod['effects']['linear']` for per-stat progression ✔. **Not available:**

* **The canonical stat id of a conditional line** — `'conditional'` is stored as cleaned strings
  (`effects.py:274-280`, `326`); the `stat_signature` key is dropped. The 11 conditional-only mods did
  parse a stat (e.g. `finisher_chance_on_block`), but the id is not carried into the emitted dict; a
  4.2 refusal would have to re-run `parse_stat_line(text)` (pure) to recover `stat`/`unit`/`value`.
* **Any evaluation context** — `compute`/`weapons.calculate` options are only
  `{faction, quantize, trigger_override}` (`api.py:85-87`, `weapons.py:76`); no target/status/attack
  context exists, so every 4.2 condition starts at `unknown` and must refuse.
* **A per-condition code** — only `conditional_effect`/`unmodelled_effect` exist;
  `unsupported.py:144-164` maps `conditional_effect → 'conditional_buffs'` (`unsupported.py:27-29`).
  The `galvanized_stacks` entry (`unsupported.py:22-26`) is **never emitted** — only the free-text note
  at `effects.py:443-445`.

## 5. Is any conditional mod applied as if unconditional? — **No.**

1. **By construction:** `parse_mod_effects` `continue`s on a conditional line before it can reach
   `rank_table` (`effects.py:287-294`); `collect_mod_effects` sums **only** `rank_table`
   (`effects.py:409-419`) and turns conditional entries into markers, never totals (`:420-424`).
   `weapons.py`, `warframes.py`, `capacity.py`, `elements.py`, `trace.py` **never read a `'conditional'`
   key** (grep: all `False`); the only consumer is `debug.py:92-95` (display).
2. **Corpus probe:** of **5131** modelled (non-conditional, applied) stat lines across all 1809 mods,
   **0** contain a soft condition cue (stacking / combo / aiming / on-hit / headshot / per-shot /
   consecutive / …), filtering `parse_stat_line(line)['conditional'] is False and ['modelled'] is True`.
3. **Behavioural check:** Braton Prime + Galvanized Chamber rank 10 → `multishot = 1.8` (`1.0 + 80%`
   unconditional only). Ack & Brunt + Blood Rush rank 10 → `critical_chance` stays **20** (base).

**Caveat for 4.2** — detection is marker-based and *incomplete*. `is_conditional` returns **False** for
real conditional lines that dodge every marker, e.g. `"+3.6% Critical Chance stacks with Combo
Multiplier"` (**Blood Rush**), `"On Consecutive throw (Max stacks 3): +16.7% Throw Damage"` (Power
Throw), `"Restore 50 Health for every 3 Status Effects."` (Bhisaj-Bal). These reach the *unmodelled*
bucket, not the *conditional* one — so today **Blood Rush is refused as "unmodelled stat", not as a
conditional** (confirmed: its `rank_table` and `conditional` are both empty, only `unmodelled` is set).
`'stacks with'`, `'consecutive'`, `'for every'` are absent from `HARD_MARKERS` (`effects.py:31-36`).
None of them reach the damage math, but any 4.2 structured refusal must not rely on `is_conditional`
alone to enumerate the condition corpus.
