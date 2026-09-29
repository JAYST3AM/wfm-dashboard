# WFM Trader - release acceptance gate

**Run:** 2026-09-29 21:11:28  (2026-09-29T21:11:28.677070+10:00) -> live measurements finished 21:14:31  
**App:** http://127.0.0.1:8787   **Reported by:** design/_stage10/gate.py (gate.js + the repo copy-diet test)  
**Raw numbers:** design/_stage10/gate-raw.json  
**Server reachable:** True

## Verdict

**PASS** - 0 of 121 checks failed, 38 page states driven, 0 blocked-CDN request(s) excluded.

## Checks by group

| group | checks | failed |
|---|---|---|
| rail | 30 | 0 |
| load | 47 | 0 |
| fit | 1 | 0 |
| themes | 2 | 0 |
| parity | 36 | 0 |
| copy | 1 | 0 |
| safety | 2 | 0 |
| ids | 2 | 0 |

## 1. Page load - console errors and failed requests

Targets: index (4 hash views + 12 tool workspaces + 6 legacy hashes), collection (3 sections), cards, settings (6 categories), item (bare + ?item= deep link), lookup.

| page | states driven | console errors | failed requests | blocked-CDN (excluded) |
|---|---|---|---|---|
| index | 24 | 0 | 0 | 0 |
| collection | 3 | 0 | 0 | 0 |
| planner | 1 | 0 | 0 | 0 |
| cards | 1 | 0 | 0 | 0 |
| settings | 6 | 0 | 0 | 0 |
| item | 1 | 0 | 0 | 0 |
| item-deeplink | 1 | 0 | 0 | 0 |
| lookup | 1 | 0 | 0 | 0 |
| fit | - | 0 | 0 | - |
| themes | - | 0 | 0 | - |

Per-state rows: 38. States with an error or a failed request: 0.

## 2. Fit - pageOverX / pageOverY per index view

| viewport | home | inventory | trade | tools | trade/orders | trade/session |
|---|---|---|---|---|---|---|
| 1920x1080 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| 1536x864 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| 1440x900 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| 1366x768 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| 1280x800 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |

Measurements: 30. Over the line (any overflow): 0.

## 3. Rail - 6 entries, one active, aria-current; legacy hashes

Rail checked on 29 page states; 0 with a problem.

| order | active | aria-current | the shell expects |
|---|---|---|---|
| home,trade,inventory,collection,planner,tools,settings | home | home | home |
| home,trade,inventory,collection,planner,tools,settings | inventory | inventory | inventory |
| home,trade,inventory,collection,planner,tools,settings | trade | trade | trade |
| home,trade,inventory,collection,planner,tools,settings | tools | tools | tools |
| home,trade,inventory,collection,planner,tools,settings | collection | collection | collection |
| home,trade,inventory,collection,planner,tools,settings | planner | planner | planner |
| home,trade,inventory,collection,planner,tools,settings | settings | settings | settings |
| home,trade,inventory,collection,planner,tools,settings | (none) | (none) | (none) |

Legacy hashes (each loaded fresh, because three of them redirect the whole page):

| hash | landed on | showing | rail active | expectation | ok |
|---|---|---|---|---|---|
| #more | /#tools | view-tools | tools | path /, hash #tools, rail tools, one visible section | yes |
| #market | /#tools | view-tools | tools | path /, hash #tools, rail tools, one visible section | yes |
| #player | /#tools/player | view-tools | tools | path /, hash #tools/player, the player workspace open, rail tools | yes |
| #mastery | /collection.html#mastery | view-mastery | collection | path /collection.html, hash #mastery, rail collection | yes |
| #history | /#history | view-trade | trade | path /, hash kept, a visible section, rail trade | yes |
| #trader | /#trader | view-trade | trade | path /, hash kept, a visible section, rail trade | yes |

## 4. Data parity - expected vs rendered

| claim | source | expected | rendered | ok |
|---|---|---|---|---|
| Trade plan rows vs data/trader_plan.json | data/trader_plan.json plan[] | 20 | 20 | yes |
| Trade held rows vs data/trader_plan.json | data/trader_plan.json held_list[] | 15 | 15 | yes |
| Tools > Deals rows (#dealsList) | its own data/*.json store | 14 | 14 | yes |
| Tools > Movers & demand > Movers rows (#moversList) | its own data/*.json store | 8 | 8 | yes |
| Tools > Movers & demand > Trends rows (#trendsList) | its own data/*.json store | 12 | 12 | yes |
| Tools > Riven bands rows (#rivensList) | its own data/*.json store | 11 | 11 | yes |
| Tools > Watchlist rows (#wlList) | its own data/*.json store | 7 | 7 | yes |
| Tools > Ducats rows (#ducatsList) | its own data/*.json store | 16 | 16 | yes |
| Tools > Craft or buy rows (#craftList) | its own data/*.json store | 12 | 12 | yes |
| Tools > Relic EV rows (#relicsList) | its own data/*.json store | 12 | 12 | yes |
| Tools > Sets rows (#setsList) | its own data/*.json store | 12 | 12 | yes |
| Tools > Sets > Almost complete rows (#nudgesList) | its own data/*.json store | 10 | 10 | yes |
| Tools > Baro Ki'Teer rows (#baroList) | its own data/*.json store | 0 | 0 | yes |
| Tools > Patch meta rows (#metaList) | its own data/*.json store | 12 | 12 | yes |
| Tools > Game news rows (#newsList) | its own data/*.json store | 8 | 8 | yes |
| Tools > Buy > Flip opportunities rows (#flipsList) | its own data/*.json store | 10 | 10 | yes |
| Tools > Buy > Wishlist rows (#wishList) | its own data/*.json store | 8 | 8 | yes |
| Home Today > Platinum now | /api/plat_history.now (fallback /api/summary.plat) | 1022 | 1,022 | yes |
| Home Today > Earned today | progress.json today.plat_delta | 0 | +0p | yes |
| Home Today > Sales today | progress.json today.trades.sales | 0 | 0 | yes |
| Home Today > Trades left | /api/summary.trades (null -> em dash) | 22 | 22 | yes |
| Inventory > rows rendered (capped at 400) | /api/items length | 400 | 400 | yes |
| Inventory > "N stacks" in the totals bar | /api/items length | 876 | 876 | yes |
| Cards > total in the header chips | cards summary.cards | 1551 | 1551 | yes |
| Cards > owned in the header chips | cards summary.owned | 557 | 557 | yes |
| Cards > missing in the header chips | cards summary.missing | 994 | 994 | yes |
| Cards > dupes in the header chips | cards summary.dupes | 333 | 333 | yes |
| Cards > grid tiles on first paint | min(BATCH 180, cards payload) | 180 | 180 | yes |
| Cards > "Showing X / Y mods" | mod_cards.json cards.length | 1551 | 1551 | yes |
| Collection > Mastery mastered count | mastery.json summary.mastered | 319 | 319 | yes |
| Collection > Mastery tracked count | mastery.json summary.tracked | 834 | 834 | yes |
| Collection > Mastery rank | mastery.json mr.rank | 22 | 22 | yes |
| Collection > Relics owned count | relics_panel.json owned_total > 0 | 122 | 122 | yes |
| Collection > Relics store count | relics_panel.json relics.length | 805 | 805 | yes |
| Collection > Relics dropping now | relics_panel.json obtain.kind == drop | 34 | 34 | yes |

Parity rows: 35, mismatches: 0.

## 5. Copy diet

**Repo test** `C:\Users\jayde\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe -m pytest tests/test_copy_diet.py -q` -> rc 0 in 0.4s

```
.                                                                        [100%]
1 passed in 0.04s
```

**Rendered scan** (visible text nodes, >8 words or >90 chars): 0 offender(s) {}

Two classes, split by a stated rule: strings that **start with `·`** (a status/metadata line the app composes from live data) vs **everything else** (shipped prose plus data-composed sentences). Counts: **0 status/meta line(s)** and **0 other offender(s)**. `tests/test_copy_diet.py` only sees string literals in the source, so most of these can never show up there - that is why the repo test passes while this scan does not.

Offenders that do **not** start with `·` (the list a copy pass would work through):

none

Status/metadata lines (data-driven; listed for completeness):

none

## 6. Safety - the Live/Not-live gate and the kill switch (raw facts, nothing flipped)

| fact | value |
|---|---|
| data/config.json exists | True |
| data/config.json has a dry_run key | False |
| data/config.json key count | 23 |
| scripts/trader/settings.json dry_run | True |
| data/trader_plan.json dry_run | True |
| data/trader_plan.json generated | 2026-09-27T06:41:38.000Z |
| data/kill_switch.json exists / parses | True |
| kill switch active | False |
| kill switch note | '' |
| kill switch ts | 2026-09-25T13:02:47.000Z |
| rendered: settings status pill | Not live#st-pill dry |
| rendered: trade kill-switch chip | disarmed |
| rendered: trade kill-switch line | 9/25/2026, 23:02:47 Not live |
| rendered: trade plan header | · built 52h ago · MR 22 |
| rendered: home alerts | Could not sign in to the market siteCloudflare check (403)19 planned listings parkedNot live - plan onlyNothing is posted automatically |

How the badge is derived (read live from `app.js`, not assumed): `dry = set.dry_run === true || plan.dry_run === true`, then the chip prints `Not live - nothing is posted` when dry. The two inputs are `scripts/trader/settings.json` and `data/trader_plan.json`; **`data/config.json` carries no `dry_run` key at all**, so it is not the gate for this badge. Both real inputs are `true` above, and the rendered copy is the Not-live wording - the badge cannot claim Live while posting is locked.

The gate never flips the kill switch, never posts, never saves settings.

## 7. Themes - 4 palettes (2 dark, 2 light) on every page

Thresholds: unreadable = text/background contrast below **2.2:1** (WCAG AA wants 4.5:1 for body text). Elements whose background is a gradient/image are counted as *unmeasured* rather than guessed; the page base colour is the theme's own `--bg`.

| theme | mode | page states | elements scanned | unreadable (<2.2:1) | colour outside the 10 palette entries | unmeasured (gradient bg) | errors |
|---|---|---|---|---|---|---|---|
| Vor Orange | dark | 17 | 3201 | 0 | 9008 | 193 | 0 |
| Kuva Crimson | dark | 17 | 3202 | 0 | 9009 | 193 | 0 |
| Frost Light | light | 17 | 3202 | 0 | 9009 | 193 | 0 |
| Cephalon White | light | 17 | 3202 | 0 | 9009 | 193 | 0 |

"Colour outside the palette" is informational: the semantic tones (`--up` green, `--down` red, warn red) are literals by design and are expected in that count. The check that fails on it is the cross-theme one below.

Low-contrast findings: 0 of 68 theme x page states.

Colours that did **not** change between the dark theme (0) and the light theme (14): 0 element(s) total, 0 of them unreadable.

## 8. Id union vs design/_stage1/ids_before.json

ids_before.json pages: index=172, collection=28, cards=20, settings=36, item=25, lookup=0

ids found live: index=8316, collection=809, cards=248, settings=1734, item=252, item-deeplink=253, lookup=462, planner=296

**Missing: 0** 

Sanctioned removals/moves applied (6):
- btnExportPng (index) <- removed from the header 2026-09-29 (Jay: the export drew a stale, price-less report and a share action did not belong in the daily header; static/export.js stays dormant)
- homeSync (index) <- merged: sync state lives in the header #syncState + footer (stage 3)
- heroCard (index) <- merged into the Home Today strip (stage 3)
- heroMeta (index) <- merged into the Home Today strip (stage 3)
- kpiCard (index) <- merged into the Home Today strip #kpis (stage 3)
- view-more (index) <- renamed view-tools (stage 2)

## Checks the harness could not run

None: every check found the DOM and the store it needs. When a container is missing the gate says so explicitly (`NOT RUNNABLE: no #id`) and fails that check instead of skipping it silently.

---

Re-run: `python design/_stage10/gate.py` (needs the app served at http://127.0.0.1:8787). 
This file is rewritten on every run; gate-raw.json holds the full machine-readable numbers.
