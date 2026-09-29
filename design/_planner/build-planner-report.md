# Build planner — browser workflow gate (Phase 2)

*ran 2026-09-29T11:14:57.837Z · verdict **PASS** · 66 checks, 0 failed*

| field | value |
|---|---|
| repo | F:/VSC Projects/wfm-dashboard |
| commit | 128fc86  "The build planner asks what a build produces - and can always say why" |
| working tree | dirty (28 changed paths) |
| server | server.py booted as a module, WFM_DATA=C:\Users\jayde\AppData\Local\Temp\planner_gate_data_20njqslz |
| page | http://127.0.0.1:50541/planner.html |
| puppeteer | F:/VSC Projects/pb-bench/node_modules/puppeteer-core |
| chrome | C:/Program Files/Google/Chrome/Application/chrome.exe |
| raw numbers | build-planner-raw.json |
| screenshots | C:\Users\jayde\AppData\Local\Temp |

## Checks

|  | area | what was checked | expected | observed |
|---|---|---|---|---|
| ✅ | open | the page ships the planner shell and its empty first-run state | grid empty (awaiting a pick) or already rendered | 0 slot cards, pickerOpen=true |
| ✅ | open | the shell marks the planner destination (not the dashboard) | data-shell="planner" | data-shell="planner" |
| ✅ | open | the rail holds 7 destinations and something is current | 7 rail entries, one aria-current | 7 entries, active=true |
| ✅ | open | the page names the engine + database it reads | a status line naming the DB | "db 8c3f4101 · 1809 mods · 777 items" |
| ✅ | open | no id appears twice in the rendered page | 0 duplicate ids | 0 () |
| ✅ | select | the picker opens with the normalised DB searchable | popup open with rows | open=true rows=80 |
| ✅ | select | searching "braton prime" leaves exactly the rifle | 1 row: Braton Prime | Braton Prime Primary · RifleMR 8 · 35 dmg · 12% crit |
| ✅ | select | picking it draws the slot grid (8 normal slots + exilus) | 8 normal slots and an exilus slot | normal0,normal1,normal2,normal3,normal4,normal5,normal6,normal7,exilus |
| ✅ | select | the build now names that equipment | /Lotus/Weapons/Tenno/Rifle/BratonPrime | /Lotus/Weapons/Tenno/Rifle/BratonPrime |
| ✅ | select | the engine prices its base damage at the Phase 1 value | base_damage = 35 | base_damage = 35 |
| ✅ | catalyst | the Catalyst toggle reaches the engine | build.orokin = true | build.orokin = true |
| ✅ | catalyst | the capacity bar reads the engine total | ui 60 | ui 60 |
| ✅ | catalyst | the doubled capacity is what the rank supports (30 -> 60) | 60 | 60 |
| ✅ | add mod | clicking a library row installs it into the focused slot | slot 1 = Serration (the rifle damage mod) | {"id":"/Lotus/Upgrades/Mods/Rifle/WeaponDamageAmountMod","rank":10} \\| "Slot 1SerrationR1014✕" |
| ✅ | add mod | a vacant slot charges the mod's full drain (4 + 10 = 14) | ui == engine (14) | ui 14 |
| ✅ | add mod | the engine's damage with Serration R10 is the Phase 1 number | modded base = 92.75 | engine 92.75 |
| ✅ | add mod | the DOM shows that same number (the page invents nothing) | DOM contains 92.75 (from Modded base damage92.75+57.75) | Modded base damage92.75+57.75 |
| ✅ | polarity | the slot carries the new polarity into the engine | madurai | madurai |
| ✅ | polarity | a matched polarity halves the drain (14 -> 7) | ui == engine, < 14 | ui 7 engine 7 |
| ✅ | polarity | the Forma readout counts the changed slot | Forma >= 1, "1 slot changed" | 1 / 1 slot changed vs the item |
| ✅ | rank | rank 0 uses the mod's own rank-0 value (+15%, not zero) | modded base = 40.25 | engine 40.25 |
| ✅ | rank | rank 10 restores the Phase 1 number (92.75) | modded base = 92.75 | engine 92.75 |
| ✅ | elements | Heat + Toxin combine to Gas in the engine | gas present | {"impact":4.6375,"puncture":32.4625,"slash":55.65,"gas":306.075} |
| ✅ | elements | the DOM shows the same combination | gas in the composition | Impact 4.638 1.2%Puncture 32.463 8.1%Slash 55.65 14%Gas 306.075 76.7%Gas 306.075 ← Heat + Toxin · Hellfire R10 + Infected Clip R10burst 4280.707 (aver… |
| ✅ | elements | slot order decides the pair: Cold + Toxin is now Viral | viral present | {"impact":4.6375,"puncture":32.4625,"slash":55.65,"viral":236.5125} |
| ✅ | elements | the stat panel followed the swap (Viral, not Gas) | viral and no gas | Impact 4.638 1.4%Puncture 32.463 9.9%Slash 55.65 16.9%Viral 236.513 71.8%Viral 236.513 ← Cold + Toxin · Cryo Rounds R5 + Infected Clip R10burst 3534.0… |
| ✅ | capacity | used capacity in the DOM equals the engine's | ui == engine | ui 34 engine 34 |
| ✅ | capacity | the charge table names a rule for every filled slot | one priced row per installed mod (3) | 3 priced of 7 rows: ["Slot 1Serrationmatched7 (14)","Slot 2empty - charges nothing","Slot 3Cryo Roundsvacant11","Slot 4Infected Clipvacant16"] |
| ✅ | damage | every stat row the DOM shows traces to an engine value | 8+ stat rows | 24 rows |
| ✅ | damage | the panel groups weapon stats (no meaningless fields) | 2+ groups | ["Offence","Critical","Status","Cadence","Damage types","Other"] |
| ✅ | crit | Point Strike raises crit chance above the 12% base | > 12 | 45 |
| ✅ | crit | the DOM crit chance is that engine number | ui ~= engine (45) | Critical chance45%+33% |
| ✅ | trace | a stat opens the engine's own trace (base, each mod, final) | a trace with the base and the mod | Base damage (modded)Base35Serration R10+165%Final92.75 |
| ✅ | trace | the trace names the final value the stat row shows | a final total in the trace | Base damage (modded)Base35Serration R10+165%Final92.75 |
| ✅ | config | config B is its own build (active + empty) | config B, no mods | config B, 0 mods |
| ✅ | config | switching to B and back leaves A untouched | the same 4 mods, incl. the rifle damage mod | /Lotus/Upgrades/Mods/Rifle/Expert/WeaponCritChanceModExpert, /Lotus/Upgrades/Mods/Rifle/Expert/WeaponToxinDamageModExpert, /Lotus/Upgrades/Mods/Rifle/… |
| ✅ | config | A still holds its polarity + capacity | madurai slot, capacity 48 | polarity madurai, used 48 (was 48) |
| ✅ | duplicate | duplicate copies A into B and switches to it | B active with A's 4 mods | config B, /Lotus/Upgrades/Mods/Rifle/Expert/WeaponCritChanceModExpert, /Lotus/Upgrades/Mods/Rifle/Expert/WeaponToxinDamageModExpert, /Lotus/Upgrades/M… |
| ✅ | persistence | the planner store is versioned | version 1 | 1 |
| ✅ | persistence | a full reload restores equipment, mods, ranks and polarity | Braton Prime, Serration R10 in a madurai slot, 4 mods | /Lotus/Weapons/Tenno/Rifle/BratonPrime / {"kind":"normal","index":0,"polarity":"madurai","mod":{"id":"/Lotus/Upgrades/Mods/Rifle/WeaponDamageAmountMod… |
| ✅ | persistence | catalyst, exilus and mastery ride along | orokin true, same mastery | orokin true, mr 28 |
| ✅ | persistence | capacity after the reload is the engine's number again | ui == engine | ui 48 engine 48 |
| ✅ | persistence | the Forma readout survived too | >= 1 | 1 |
| ✅ | graceful | a v99 / foreign payload does not break the page | page boots at its defaults, no new page error | 0 slots in the grid, config A, new errors 0 |
| ✅ | graceful | the unreadable payload is discarded, not half-applied | the store is gone or rewritten as version 1 | {"version":1,"active":"A"} |
| ✅ | fit | no horizontal overflow at 1920x1080 | scrollWidth <= 1920 | scrollWidth 1920 |
| ✅ | fit | the three columns never overlap at 1920x1080 | 0 px overlap | 0 px |
| ✅ | fit | no horizontal overflow at 1536x864 | scrollWidth <= 1536 | scrollWidth 1536 |
| ✅ | fit | the three columns never overlap at 1536x864 | 0 px overlap | 0 px |
| ✅ | fit | no horizontal overflow at 1440x900 | scrollWidth <= 1440 | scrollWidth 1440 |
| ✅ | fit | the three columns never overlap at 1440x900 | 0 px overlap | 0 px |
| ✅ | fit | no horizontal overflow at 1366x768 | scrollWidth <= 1366 | scrollWidth 1366 |
| ✅ | fit | the three columns never overlap at 1366x768 | 0 px overlap | 0 px |
| ✅ | fit | no horizontal overflow at 1280x800 | scrollWidth <= 1280 | scrollWidth 1280 |
| ✅ | fit | the three columns never overlap at 1280x800 | 0 px overlap | 0 px |
| ✅ | keyboard | "/" reaches the library search | plLibSearch focused | plLibSearch |
| ✅ | keyboard | arrows + Enter install a mod without a mouse | 1+ mod installed | 1 mods |
| ✅ | keyboard | a digit focuses a slot (the inspector says which) | inspector shows Slot 1 | Slot 1 · Serrated RoundsR3 drain 2+3 → max 5Remove |
| ✅ | drag | a mod at a locked Exilus slot is refused - marked bad, nothing installed | data-drop="bad", mod count unchanged | mark bad, mods 1 -> 1 |
| ✅ | drag | a library row dropped on a slot installs it | marked "ok" and one more mod | mark ok, 1 -> 2 |
| ✅ | drag | slot -> slot moves the mod (marked "move") without losing or duplicating any | the mod is in slot 8, slot 1 empty, same count, target marked "move" | in slot 8: true, slot 1 empty: true, 2 -> 2, mark move |
| ✅ | drag | slot -> library removes the mod, and the panel offers the drop | panel marked "drop here to remove", one mod fewer | marked: true, removed 1 |
| ✅ | hygiene | no duplicate id after the whole drive | 0 duplicates | [] |
| ✅ | hygiene | no console error over the whole drive | 0 console errors | 0:  |
| ✅ | hygiene | no page error over the whole drive | 0 page errors | 0:  |
| ✅ | hygiene | no failed request outside the dev-server burst class | 0 failed requests | 0: [] |

## The engine facts this run used

The gate compares what the page shows against `/api/planner/compute` for the same
build JSON, and pins two Phase 1 numbers so engine drift fails loudly:

| step | values measured |
|---|---|
| config-a-intact | cap_used=48 |
| damage-crit | api_crit=45; api_damage=92.75 |
| drag | panel_mark=True |
| persistence | api_used_after=48 |

## Hygiene over the whole drive

| signal | count |
|---|---|
| console errors | 0 |
| page errors | 0 |
| failed requests (outside the dev-server burst class) | 0 |
| blocked-CDN requests | 0 |
| duplicate ids in the rendered page | 0 |

## How to re-run

```bash
cd "F:/VSC Projects/wfm-dashboard"
python design/_planner/build_planner_gate.py
```

The gate edits nothing on the app: it clicks, types and drops on the planner page,
reads localStorage, and reloads. The only writes are its own report, the raw JSON
and the screenshots.
