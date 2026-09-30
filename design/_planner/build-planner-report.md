# Build planner — browser workflow gate (Phase 2)

*ran 2026-09-30T07:55:47.687Z · verdict **PASS** · 121 checks, 0 failed*

| field | value |
|---|---|
| repo | F:/VSC Projects/wfm-dashboard |
| commit | cdcb837  "Gate: the Orders state polls for its answer instead of racing it" |
| working tree | dirty (32 changed paths) |
| server | server.py booted as a module, WFM_DATA=C:\Users\jayde\AppData\Local\Temp\planner_gate_data_ck175s_g |
| page | http://127.0.0.1:58308/planner.html |
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
| ✅ | open | the page names the engine + database it reads | a status line naming the DB | "db ea904b31 · 1809 mods · 777 items" |
| ✅ | open | no id appears twice in the rendered page | 0 duplicate ids | 0 () |
| ✅ | select | the picker opens with the normalised DB searchable | popup open with rows | open=true rows=80 |
| ✅ | select | searching "braton prime" leaves exactly the rifle | 1 row: Braton Prime | Braton Prime Primary · RifleMR 8 · 35 dmg · 12% crit |
| ✅ | select | picking it draws the slot grid (8 normal slots + exilus) | 8 normal slots and an exilus slot | normal0,normal1,normal2,normal3,normal4,normal5,normal6,normal7,exilus |
| ✅ | select | the build now names that equipment | /Lotus/Weapons/Tenno/Rifle/BratonPrime | /Lotus/Weapons/Tenno/Rifle/BratonPrime |
| ✅ | select | the engine prices its base damage at the Phase 1 value | base_damage = 35 | base_damage = 35 |
| ✅ | library | one card per name - nothing the player could mix up | no duplicate names | [] of 256 |
| ✅ | library | starter copies wear the game's own name (Flawed ...) | at least one Flawed copy visible | flawed=40 |
| ✅ | library | the obsolete leftovers are counted, not silently dropped | hidden.shadowed > 0 with a reason | {"shadowed":39,"conclave":50,"reason":"not a plain PvE card: obsolete internal duplicates and Conclave-only mods"} |
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
| ✅ | elements | Heat + Toxin combine to Gas in the engine | gas present | {"impact":4.6375,"puncture":32.4625,"slash":55.65,"gas":166.95} |
| ✅ | elements | the DOM shows the same combination | gas in the composition | Impact 4.638 1.8%Puncture 32.463 12.5%Slash 55.65 21.4%Gas 166.95 64.3%Gas 166.95 ← Heat + Toxin · Hellfire R5 + Infected Clip R5burst 2787.437 (avera… |
| ✅ | elements | slot order decides the pair: Cold + Toxin is now Viral | viral present | {"impact":4.6375,"puncture":32.4625,"slash":55.65,"viral":166.95} |
| ✅ | elements | the stat panel followed the swap (Viral, not Gas) | viral and no gas | Impact 4.638 1.8%Puncture 32.463 12.5%Slash 55.65 21.4%Viral 166.95 64.3%Viral 166.95 ← Cold + Toxin · Cryo Rounds R5 + Infected Clip R5burst 2787.437… |
| ✅ | capacity | used capacity in the DOM equals the engine's | ui == engine | ui 29 engine 29 |
| ✅ | capacity | the charge table names a rule for every filled slot | one priced row per installed mod (3) | 3 priced of 7 rows: ["Slot 1Serrationmatched7, was 14","Slot 2empty - charges nothing","Slot 3Cryo Roundsvacant11","Slot 4Infected Clipvacant11"] |
| ✅ | damage | every stat row the DOM shows traces to an engine value | 8+ stat rows | 24 rows |
| ✅ | damage | the panel groups weapon stats (no meaningless fields) | 2+ groups | ["Offence","Critical","Status","Cadence","Damage types","Other"] |
| ✅ | crit | Point Strike raises crit chance above the 12% base | > 12 | 30 |
| ✅ | crit | the DOM crit chance is that engine number | ui ~= engine (30) | Critical chance30%+18% |
| ✅ | trace | a stat opens the engine's own trace (base, each mod, final) | a trace with the base and the mod | Base damage (modded)Base35Serration R10+165%Final92.75 |
| ✅ | trace | the trace names the final value the stat row shows | a final total in the trace | Base damage (modded)Base35Serration R10+165%Final92.75 |
| ✅ | config | config B is its own build (active + empty) | config B, no mods | config B, 0 mods |
| ✅ | config | switching to B and back leaves A untouched | the same 4 mods, incl. the rifle damage mod | /Lotus/Upgrades/Mods/Rifle/WeaponCritChanceMod, /Lotus/Upgrades/Mods/Rifle/WeaponDamageAmountMod, /Lotus/Upgrades/Mods/Rifle/WeaponFreezeDamageMod, /L… |
| ✅ | config | A still holds its polarity + capacity | madurai slot, capacity 38 | polarity madurai, used 38 (was 38) |
| ✅ | duplicate | duplicate copies A into B and switches to it | B active with A's 4 mods | config B, /Lotus/Upgrades/Mods/Rifle/WeaponCritChanceMod, /Lotus/Upgrades/Mods/Rifle/WeaponDamageAmountMod, /Lotus/Upgrades/Mods/Rifle/WeaponFreezeDam… |
| ✅ | persistence | the planner store is versioned | version 1 | 1 |
| ✅ | persistence | a full reload restores equipment, mods, ranks and polarity | Braton Prime, Serration R10 in a madurai slot, 4 mods | /Lotus/Weapons/Tenno/Rifle/BratonPrime / {"kind":"normal","index":0,"polarity":"madurai","mod":{"id":"/Lotus/Upgrades/Mods/Rifle/WeaponDamageAmountMod… |
| ✅ | persistence | catalyst, exilus and mastery ride along | orokin true, same mastery | orokin true, mr 28 |
| ✅ | persistence | capacity after the reload is the engine's number again | ui == engine | ui 38 engine 38 |
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
| ✅ | library | the hidden rows come back on request, each one flagged | more rows, all flagged shadowed | {"total":345,"shadowed":39,"named":["Ammo Drum","Arrow Mutation","Arrow Mutation"]} |
| ✅ | keyboard | "/" reaches the library search | plLibSearch focused | plLibSearch |
| ✅ | keyboard | arrows + Enter install a mod without a mouse | 1+ mod installed | 1 mods |
| ✅ | keyboard | a digit focuses a slot (the inspector says which) | inspector shows Slot 1 | Slot 1 · Serrated RoundsR3 drain 2+3 → max 5Remove |
| ✅ | drag | a mod at a locked Exilus slot is refused - marked bad, nothing installed | data-drop="bad", mod count unchanged | mark bad, mods 1 -> 1 |
| ✅ | drag | a library row dropped on a slot installs it | marked "ok" and one more mod | mark ok, 1 -> 2 |
| ✅ | drag | slot -> slot moves the mod (marked "move") without losing or duplicating any | the mod is in slot 8, slot 1 empty, same count, target marked "move" | in slot 8: true, slot 1 empty: true, 2 -> 2, mark move |
| ✅ | drag | slot -> library removes the mod, and the panel offers the drop | panel marked "drop here to remove", one mod fewer | marked: true, removed 1 |
| ✅ | engine-math | the toolbar capacity floor is the engine's own number | hint names the engine floor 0 and its binding state | capacity floor 0 |
| ✅ | legality | the Exilus switch decides: locked, the slot stays empty; unlocked and focused, the mod lands there | locked: Exilus slot empty; unlocked + focused: the mod is in the Exilus slot | {"locked":null,"unlocked":"/Lotus/Upgrades/Mods/Rifle/Event/Arbitration/JumpRefreshOnKillRifleMod","locked_mod":"Adhesive Blast","unlocked_mod":"Aeria… |
| ✅ | answer-contract | a real answer hides the error banner and says so | banner hidden, data-planswer=yes, a capacity figure | {"hidden":true,"answer":"yes","capUsed":"23","ok":true,"has_result":true,"error":null,"val_errors":[],"banner":""} |
| ✅ | answer-contract | an impossible build shows the engine's own reason, not a dead engine | the refusal code the engine sent appears in #plValidity | {"codes":["duplicate_mod"],"shown":"Adhesive Blast is installed in two slotscode · duplicate_mod · slots · /Lotus/Upgrades/Mod","banner":""} |
| ✅ | answer-contract | a refusal is not reported as a failure to answer | the refusal reached the page and the error banner stayed hidden | banner hidden: true, codes: duplicate_mod, banner: "" |
| ✅ | storage | a malformed v1 payload is replaced in full, not merged | the stored key is rewritten to a clean v1 document | {"version":1,"equipment_id":"/Lotus/Weapons/Tenno/Rifle/BratonPrime","equipment_rank":null,"orokin":false,"exilus_unlocked":false,"mastery_rank":28,"a… |
| ✅ | head-card | at 1920x1080 the selector sits in the head card and the dropdown hangs off it, unclipped | button inside the card; card not scrolled; dropdown 2-14px under the button, aligned, hit-… | {"btnInsideHead":true,"headContainsChildren":true,"headScrollTop":0,"headClearsBar":true,"popAnchored":true,"popUnclipped":true,"searchVisible":true,"… |
| ✅ | head-card | at 1536x864 the selector sits in the head card and the dropdown hangs off it, unclipped | button inside the card; card not scrolled; dropdown 2-14px under the button, aligned, hit-… | {"btnInsideHead":true,"headContainsChildren":true,"headScrollTop":0,"headClearsBar":true,"popAnchored":true,"popUnclipped":true,"searchVisible":true,"… |
| ✅ | head-card | at 1440x900 the selector sits in the head card and the dropdown hangs off it, unclipped | button inside the card; card not scrolled; dropdown 2-14px under the button, aligned, hit-… | {"btnInsideHead":true,"headContainsChildren":true,"headScrollTop":0,"headClearsBar":true,"popAnchored":true,"popUnclipped":true,"searchVisible":true,"… |
| ✅ | head-card | at 1366x768 the selector sits in the head card and the dropdown hangs off it, unclipped | button inside the card; card not scrolled; dropdown 2-14px under the button, aligned, hit-… | {"btnInsideHead":true,"headContainsChildren":true,"headScrollTop":0,"headClearsBar":true,"popAnchored":true,"popUnclipped":true,"searchVisible":true,"… |
| ✅ | head-card | at 1280x800 the selector sits in the head card and the dropdown hangs off it, unclipped | button inside the card; card not scrolled; dropdown 2-14px under the button, aligned, hit-… | {"btnInsideHead":true,"headContainsChildren":true,"headScrollTop":0,"headClearsBar":true,"popAnchored":true,"popUnclipped":true,"searchVisible":true,"… |
| ✅ | head-card | the head card holds its controls in a light theme too (white card) | the same invariants on the white card of a light palette | {"bg":"rgb(255, 255, 255)","m":{"btnInsideHead":true,"headContainsChildren":true,"headScrollTop":0,"headClearsBar":true,"popAnchored":true,"popUnclipp… |
| ✅ | picker | the first run invites the choice and hides the empty workspace | hero visible, workspace/controls/diagnostics not rendered, picker offered | {"noEquip":true,"heroShown":true,"workspaceHidden":true,"barHidden":true,"diagHidden":true,"pickerOpen":true} |
| ✅ | picker | a category click filters the list and keeps the picker open | picker still open, exactly one chip pressed, rows rendered, nothing scrolled out of the ca… | {"heroOpens":true,"category":{"open":true,"pressed":1,"rows":80,"headScrollTop":0,"foot":"80 shown of 121"}} |
| ✅ | picker | search still works after a category switch | the query filters the category list without closing the picker | {"open":true,"rows":2,"first":"Ash"} |
| ✅ | picker | a click outside and Escape both close the picker | outside click closes; reopen; Escape closes | {"closedOutside":true,"reopened":true,"closedEsc":true} |
| ✅ | picker | choosing an item closes the picker and loads the build | picker closed, slots rendered, workspace and diagnostics on, header names the item and its… | {"open":false,"name":"Ash","slots":10,"workspace":true,"diag":true,"chip":"Rank 30 / 30"} |
| ✅ | layout | the workspace keeps its regions, its selected slot and its active config | five regions sized, one focused slot (>=60px tiles), one selected config, diagnostics a fl… | {"focused":1,"config":1,"head":1682,"bar":1682,"slots":440,"lib":818,"stats":404,"diag":88,"slotHeight":68,"over":0} |
| ✅ | layout | the diagnostics strip expands and collapses, with a count on every heading | four collapsible sections in order (validation, capacity, evaluation, unsupported), closed… | {"count":4,"closedBefore":false,"afterOpen":true,"afterClose":false,"names":["validation","capacity","evaluation","unsupported"],"badges":["· clean","… |
| ✅ | details | hovering a row fills the docked pane, on screen and clear of the stats | pane holds the card, inside the viewport, no intersection with #plStats | {"top":948,"bottom":1080,"h":132,"tip":true,"text":"\n          \n          \n        Adaptatio","inView":true,"clearOfStats":true,"fixed":0} |
| ✅ | details | nothing in the workspace floats (no fixed-position surface) | the preview and the details are both docked; the old design had two fixed layers here | fixed layers: 0 |
| ✅ | details | the last row of the list still opens its details on screen, unclipped | no bottom-edge clipping at the end of the list | {"bottom":1080,"innerH":1080,"inView":true,"clearOfStats":true,"pageY":285} |
| ✅ | library | the polarity glyph has measurable space before the mod name | gap >= 6px between glyph and name, the glyph is a real square, the row stays compact | {"gap":9,"polW":15,"h":45,"name":"Abating Link"} |
| ✅ | loadout | a focused slot is visually distinguishable from an unfocused one | the focused tile carries its own border/shadow/background, not just a caret | {"focused":true,"differs":true,"on":{"border":"rgb(255, 138, 30)","shadow":"rgb(255, 138, 30) 0px 0px 0px 1px, color(srgb 1 0.541176 0.117647 / 0.18) … |
| ✅ | stats | the Why panel opens with a trace and the traced row highlighted | a default trace (damage for a weapon, health for a frame) with its stat row lit | {"view":true,"label":"· Health","lines":2,"pressed":1} |
| ✅ | scroll | the library scrolls on its own without moving the page or the stats | independent scrollers, no accidental parent scroll | {"pageSame":true,"statsSame":true,"listMoved":true} |
| ✅ | details | the docked details stay on screen and off the stats at all five sizes | five viewports: pane inside the viewport, no stats overlap, no page overflow, the workspac… | {"sizes":5,"bad":[]} |
| ✅ | target | a stated target survives a reload and is posted exactly as stated | nothing stated posts no context at all; a stated faction and stack count survive the reloa… | before=null after={"context":{"target_faction":"corpus","target":{"viral_stacks":6}}} |
| ✅ | target | an unresolved target input is withheld, not assumed | viral stacks stated without a landing = unknown (withheld); nothing stated = deterministic | before="deterministic" after={"mode":"stated_inputs","state":"conditional","context_supplied":true,"context_ignored":[],"withheld":["viral"],"assumpti… |
| ✅ | target | the target card posts exactly what was typed - faction, layer, armour, corrosive, on-kill state | grineer / health / armour 900 / corrosive 4 / 3 on-kill stacks and no uptime | {"target_faction":"grineer","target":{"protection":"health","armor":900,"corrosive_stacks":4},"buffs":{"on_kill":{"stacks":3}}} |
| ✅ | target | the card prints the engine's mitigated numbers, not its own | armour reduced in the head, the engine per-projectile/per-shot figures in the body, a why … | effective=504.00000000000006 out=vs Grineer · lands on health · armour 900 -> 504impact 1.604 · puncture 7.487 · slash 12.834per projectile 21.925 · p… |
| ✅ | target | the why button opens the engine's own target trace | the trace panel shows the engine target trace (its label, its source line, its final figur… | {"clicked":true,"text":"Damage vs the stated target (per projectile)Base35impact-0.146puncture-4.763slash-8.166Final21.925source: https://wiki.warfram… |
| ✅ | target | the on-kill rider applies the stated stacks and prints its own contribution | satisfied from 3 stated stacks, contribution printed as the payload states it | installed=1 rider=/Lotus/Upgrades/Mods/Rifle/WeaponFireIterationsSPMod {"mod":"/Lotus/Upgrades/Mods/Rifle/WeaponFireIterationsSPMod","mod_name":"Galva… |
| ✅ | target | an averaged on-kill state says so, on the stated stacks only | mode averaged, 0.65 uptime carried, the assumption printed next to the contribution | {"mod":"/Lotus/Upgrades/Mods/Rifle/WeaponFireIterationsSPMod","mod_name":"Galvanized Chamber","rank":10,"trigger":"on_kill","stat":"multishot","cap":5… |
| ✅ | target | clearing the armour withholds the number and prints the engine's own refusal | no target_damage, and the card prints the engine's unknown verdict naming the armour | td=null out=target damage: unknown - the damage lands on health, so the armour value is needed to compute the mitigation, and no armour was statedOn K… |
| ✅ | hygiene | no duplicate id after the whole drive | 0 duplicates | [] |
| ✅ | hygiene | no console error over the whole drive | 0 console errors | 0:  |
| ✅ | hygiene | no page error over the whole drive | 0 page errors | 0:  |
| ✅ | hygiene | no failed request outside the dev-server burst class | 0 failed requests | 0: [] |
| ✅ | current | the Current Loadout card lists every equipped category from the save | six rows: warframe, primary, secondary, melee, companion, companion weapon | WarframeGauss PrimeConfig A · Rank 30 \\| PrimaryBraton PrimeConfig A · Rank 30 \\| SecondaryKohmakConfig A · Rank 0 \\| MeleeRipkasConfig A · Rank unkno… |
| ✅ | current | the card names its source and whether that source is live | a freshness label, and - when the source cannot be shown to be live - the warning repeated | Last seen 16 hours ago /  |
| ✅ | current | the imported view is read-only: no editable field, only its own buttons | no input/textarea/contenteditable, and refresh/view/clone as the only affordances | editable=0 buttons=plCurrentRefresh,plCurrentView,plCurrentClone |
| ✅ | current | the card adds no floating surface (the workspace rule holds here too) | no position:fixed element inside #plCurrent | fixed layers: 0 |
| ✅ | current | the imported build shows its mods with the ranks the save records | Serration at rank 10, read from the copy the save points at | 1SerrationR10 |
| ✅ | current | the engine's verdict is on the card, unrounded and unreworded | the engine accepted the imported build: 1 mod read, build validates | Braton PrimeConfig A · Rank 301SerrationR10Capacity assumes no Catalyst or Exilus.Forma 1Catalyst unknownExilus unknown1 mods read0 with unmodelled ef… |
| ✅ | current | the drain the card shows is the drain the engine returns | the card prints the engine number, it does not re-derive it | {"engine_drain":14,"engine_damage":92.75,"shown_has_drain":true,"shown":"Braton PrimeConfig A · Rank 301SerrationR10Capacity assumes no Catalyst or Ex… |
| ✅ | current | the engine still prices the imported Serration R10 at the Phase 1 value | 92.75 | 92.75 |
| ✅ | current | cloning fills the planner with the imported build | the planner now holds the Braton Prime build, one mod in slot 1 | /Lotus/Weapons/Tenno/Rifle/BratonPrime slots=normal:0 header=Braton Prime |
| ✅ | current | cloning does not modify what the source said | the imported snapshot is byte-identical before and after the clone (freshness aside: it is… | identical |
| ✅ | current | the imported card survives a planner edit and a reload untouched | the planner keeps its own state; the imported view is read from the source each time | rows=6 equipment=/Lotus/Weapons/Tenno/Rifle/BratonPrime |
| ✅ | current | a broken source is a named, calm state - not an empty card | the card stays, explains itself, and offers no clone | Current Loadout Refresh The save could not be read: unexpected end of dataLooked for C:/somewhere/lastData.dat Clone as Config A Config B Config C Vie… |
| ✅ | current | a readable save imports as ok | ok | ok |
| ✅ | current | a truncated save reads as malformed, never as empty | malformed | malformed |
| ✅ | current | a save without a loadout says so | no_build_data | no_build_data |
| ✅ | current | a missing file names the path it looked for | missing | missing |

## The engine facts this run used

The gate compares what the page shows against `/api/planner/compute` for the same
build JSON, and pins two Phase 1 numbers so engine drift fails loudly:

| step | values measured |
|---|---|
| config-a-intact | cap_used=38 |
| damage-crit | api_crit=30; api_damage=92.75 |
| drag | panel_mark=True |
| persistence | api_used_after=38 |

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
