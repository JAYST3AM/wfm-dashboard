# WFM Trader - release acceptance gate

**Run:** 2026-09-28 21:11:52  (2026-09-28T21:11:52.503818+10:00) -> live measurements finished 21:14:27  
**App:** http://127.0.0.1:8787   **Reported by:** design/_stage10/gate.py (gate.js + the repo copy-diet test)  
**Raw numbers:** design/_stage10/gate-raw.json  
**Server reachable:** True

## Verdict

**FAIL** - 3 of 107 checks failed, 34 page states driven, 0 blocked-CDN request(s) excluded.

### Failing checks (honest current state)

- **themes** - 4 themes (2 dark, 2 light): no unreadable text, no console error
  - expected: `0 low-contrast / 0 errors`
  - rendered: `132 low-contrast / 0 errors over 60 scans`
  - note: index/home Frost Light=9 \| index/home Cephalon White=9 \| index/inventory Frost Light=1 \| collection/relics Kuva Crimson=113
- **themes** - no text colour survives the dark->light switch untouched (var escapes)
  - expected: `0 unreadable escaped colours`
  - rendered: `1 colours identical in theme 0 (dark) and theme 14 (light), 1 of them unreadable`
  - note: index/home=1
- **copy** - rendered visible strings stay inside 8 words / 90 chars on every page
  - expected: `0 offenders`
  - rendered: `53 offenders`
  - note: 12 offenders start with "·" (data-driven status lines the source test cannot see) + 41 other offenders; examples: index/landing #home [11w 79c] Sign-in failed warframe.market is showing a Cloudflare browser check (http 403) \| index/landing #home [9w 54c] 19 planned listings are parked until posting goes live \| index/landing #home [15w 79c] WFM Trader · refreshed 21:11 · 471 history events · prices refresh every 15 min \| index/#inventory [4w 98c] data/inventory_snapshots/owned_2026-09-28.json · vs data/inventory_snapshots/owned_2026-09-27.json

## Checks by group

| group | checks | failed |
|---|---|---|
| rail | 29 | 0 |
| load | 36 | 0 |
| fit | 1 | 0 |
| themes | 2 | 2 |
| parity | 35 | 0 |
| copy | 1 | 1 |
| safety | 2 | 0 |
| ids | 1 | 0 |

## 1. Page load - console errors and failed requests

Targets: index (4 hash views + 12 tool workspaces + 6 legacy hashes), collection (3 sections), cards, settings (6 categories), item (bare + ?item= deep link), lookup.

| page | states driven | console errors | failed requests | blocked-CDN (excluded) |
|---|---|---|---|---|
| index | 21 | 0 | 0 | 0 |
| collection | 3 | 0 | 0 | 0 |
| cards | 1 | 0 | 0 | 0 |
| settings | 6 | 0 | 0 | 0 |
| item | 1 | 0 | 0 | 0 |
| item-deeplink | 1 | 0 | 0 | 0 |
| lookup | 1 | 0 | 0 | 0 |
| fit | - | 0 | 0 | - |
| themes | - | 17 | 17 | - |

Per-state rows: 34. States with an error or a failed request: 0.

Detail:

- themes error @index/tools: Failed to load resource: net::ERR_CONNECTION_REFUSED
- themes error @index/tools: Failed to load resource: net::ERR_CONNECTION_REFUSED
- themes error @index/tools: Failed to load resource: net::ERR_CONNECTION_REFUSED
- themes error @index/tools: Failed to load resource: net::ERR_CONNECTION_REFUSED
- themes error @index/tools: Failed to load resource: net::ERR_CONNECTION_REFUSED
- themes error @index/tools: Failed to load resource: net::ERR_CONNECTION_REFUSED
- themes error @index/tools: Failed to load resource: net::ERR_CONNECTION_REFUSED
- themes error @index/tools: Failed to load resource: net::ERR_CONNECTION_REFUSED
- themes error @index/tools: Failed to load resource: net::ERR_CONNECTION_REFUSED
- themes error @index/tools: Failed to load resource: net::ERR_CONNECTION_REFUSED
- themes failed request @index/tools: http://127.0.0.1:8787/colimg/Grendel.png (net::ERR_CONNECTION_REFUSED)
- themes failed request @index/tools: http://127.0.0.1:8787/colimg/GyrePrime.png (net::ERR_CONNECTION_REFUSED)
- themes failed request @index/tools: http://127.0.0.1:8787/colimg/Harrow.png (net::ERR_CONNECTION_REFUSED)
- themes failed request @index/tools: http://127.0.0.1:8787/colimg/HarrowPrime.png (net::ERR_CONNECTION_REFUSED)
- themes failed request @index/tools: http://127.0.0.1:8787/colimg/IronFrame.png (net::ERR_CONNECTION_REFUSED)
- themes failed request @index/tools: http://127.0.0.1:8787/colimg/HildrynPrime.png (net::ERR_CONNECTION_REFUSED)
- themes failed request @index/tools: http://127.0.0.1:8787/colimg/Hydroid.png (net::ERR_CONNECTION_REFUSED)
- themes failed request @index/tools: http://127.0.0.1:8787/colimg/HydroidPrime.png (net::ERR_CONNECTION_REFUSED)
- themes failed request @index/tools: http://127.0.0.1:8787/colimg/InarosPrime.png (net::ERR_CONNECTION_REFUSED)
- themes failed request @index/tools: http://127.0.0.1:8787/colimg/PaxDuviricus.png (net::ERR_CONNECTION_REFUSED)

## 2. Fit - pageOverX / pageOverY per index view

| viewport | home | inventory | trade | tools |
|---|---|---|---|---|
| 1920x1080 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| 1536x864 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| 1440x900 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| 1366x768 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| 1280x800 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |

Measurements: 20. Over the line (any overflow): 0.

## 3. Rail - 6 entries, one active, aria-current; legacy hashes

Rail checked on 28 page states; 0 with a problem.

| order | active | aria-current | the shell expects |
|---|---|---|---|
| home,trade,inventory,collection,tools,settings | home | home | home |
| home,trade,inventory,collection,tools,settings | inventory | inventory | inventory |
| home,trade,inventory,collection,tools,settings | trade | trade | trade |
| home,trade,inventory,collection,tools,settings | tools | tools | tools |
| home,trade,inventory,collection,tools,settings | collection | collection | collection |
| home,trade,inventory,collection,tools,settings | settings | settings | settings |
| home,trade,inventory,collection,tools,settings | (none) | (none) | (none) |

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
| Home Today > Trades left | /api/summary.trades (null -> em dash) | — (null) | — | yes |
| Inventory > rows rendered | /api/items length | 0 | 0 | yes |
| Inventory > "N stacks" in the totals bar | /api/items length | 0 | 0 | yes |
| Cards > total in the header chips | cards summary.cards | 1551 | 1551 | yes |
| Cards > owned in the header chips | cards summary.owned | 557 | 557 | yes |
| Cards > missing in the header chips | cards summary.missing | 994 | 994 | yes |
| Cards > dupes in the header chips | cards summary.dupes | 333 | 333 | yes |
| Cards > grid tiles on first paint | min(BATCH 180, cards payload) | 180 | 180 | yes |
| Cards > "Showing X / Y mods" | mod_cards.json cards.length | 1551 | 1551 | yes |
| Collection > Mastery mastered count | mastery.json summary.mastered | 317 | 317 | yes |
| Collection > Mastery tracked count | mastery.json summary.tracked | 834 | 834 | yes |
| Collection > Mastery rank | mastery.json mr.rank | 22 | 22 | yes |
| Collection > Relics owned count | relics_panel.json owned_total > 0 | 121 | 121 | yes |
| Collection > Relics store count | relics_panel.json relics.length | 805 | 805 | yes |
| Collection > Relics dropping now | relics_panel.json obtain.kind == drop | 34 | 34 | yes |

Parity rows: 35, mismatches: 0.

## 5. Copy diet

**Repo test** `C:\Users\jayde\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe -m pytest tests/test_copy_diet.py -q` -> rc 0 in 0.5s

```
.                                                                        [100%]
1 passed in 0.04s
```

**Rendered scan** (visible text nodes, >8 words or >90 chars): 53 offender(s) {"index": 25, "collection": 22, "settings": 1, "item-deeplink": 2, "lookup": 3}

Two classes, split by a stated rule: strings that **start with `·`** (a status/metadata line the app composes from live data) vs **everything else** (shipped prose plus data-composed sentences). Counts: **12 status/meta line(s)** and **41 other offender(s)**. `tests/test_copy_diet.py` only sees string literals in the source, so most of these can never show up there - that is why the repo test passes while this scan does not.

Offenders that do **not** start with `·` (the list a copy pass would work through):

| page | state | words | chars | string |
|---|---|---|---|---|
| index | landing #home | 11 | 79 | Sign-in failed warframe.market is showing a Cloudflare browser check (http 403) |
| index | landing #home | 9 | 54 | 19 planned listings are parked until posting goes live |
| index | landing #home | 15 | 79 | WFM Trader · refreshed 21:11 · 471 history events · prices refresh every 15 min |
| index | #inventory | 4 | 98 | data/inventory_snapshots/owned_2026-09-28.json · vs data/inventory_snapshots/owned_2026-09-27.json |
| index | #trade | 11 | 62 | advisor: demand fading · best 00:00, 10:00, 13:00 · 3 sellable |
| index | #trade | 11 | 42 | rank 0 · 1 more held · 1 in use 71→6/trade |
| index | #trade | 11 | 62 | advisor: demand steady · best 00:00, 10:00, 13:00 · 4 sellable |
| index | #trade | 9 | 54 | advisor: demand steady · best 00:00-03:00 · 1 sellable |
| index | #trade | 9 | 55 | advisor: demand fading · best 00:00-03:00 · 12 sellable |
| index | #trade | 11 | 63 | advisor: demand steady · best 00:00, 10:00, 13:00 · 54 sellable |
| index | #trade | 11 | 62 | advisor: demand steady · best 00:00, 10:00, 13:00 · 5 sellable |
| index | #trade | 11 | 62 | advisor: demand steady · best 00:00, 10:00, 13:00 · 3 sellable |
| index | #trade | 11 | 62 | advisor: demand fading · best 00:00, 10:00, 13:00 · 1 sellable |
| index | #trade | 14 | 65 | 19 hide · 0 reprice · 0 restore · auto-hide after 240 min offline |
| index | #tools/baro | 17 | 88 | NOT active -- next visit Fri 2026-10-02 13:00 UTC at Kronia Relay (Saturn) (in 7d 0h 8m) |
| index | #tools/baro | 42 | 281 | voidTrader.active is false and the worldstate API returned an EMPTY inventory -- stock is only published while Baro is present, so there is no preview to score. |
| collection | relics | 12 | 67 | Venus/Orb Vallis (Level 40 - 60 PROFIT-TAKER - PHASE 2), Rotation C |
| collection | relics | 12 | 67 | Venus/Orb Vallis (Level 40 - 60 PROFIT-TAKER - PHASE 1), Rotation C |
| collection | relics | 12 | 67 | Venus/Orb Vallis (Level 40 - 60 PROFIT-TAKER - PHASE 3), Rotation C |
| collection | relics | 9 | 52 | Earth/Cetus (Level 40 - 50 Ghoul Bounty), Rotation A |
| collection | relics | 9 | 52 | Earth/Cetus (Level 15 - 25 Ghoul Bounty), Rotation A |
| collection | mastery | 13 | 79 | The Itzal's main and component blueprints can be researched from the Tenno Lab… |
| collection | mastery | 12 | 80 | Karak Wraith was introduced during the Operation: Tubemen of Regor event, where… |
| collection | mastery | 12 | 80 | Component blueprints for the Bonewidow are available for 3,500 standing from th… |
| collection | mastery | 16 | 80 | The player must have completed the Howl of the Kubrow quest in order to have an… |
| collection | mastery | 13 | 80 | The Amesha's main and component blueprints can be researched from the Tenno Lab… |
| collection | mastery | 15 | 80 | The Bad Baby blueprint can be acquired by buying it from Roky with the Ventkids… |
| collection | mastery | 12 | 70 | The Bhaira blueprint can be earned by vanquishing a Sisters of Parvos. |
| collection | mastery | 11 | 80 | Vulpaphylas are acquired through Revivification with Son in the Necralisk, Deim… |
| collection | mastery | 15 | 80 | Djinn can be researched from the Bio Lab in the Dojo. Note that acquiring Djinn… |
| collection | mastery | 12 | 69 | The Dorma blueprint can be earned by vanquishing a Sisters of Parvos. |
| collection | mastery | 13 | 80 | The Elytron's main and component blueprints can be researched from the Tenno La… |
| collection | mastery | 12 | 80 | Excalibur Prime was only obtainable by upgrading a Warframe account to Founders… |
| collection | mastery | 14 | 80 | The blueprint can be acquired by completing the K-Drive Race "Dead Drop" on the… |
| collection | mastery | 13 | 79 | The Flatbelly blueprint can be acquired after reaching the Rank of Whozit with… |
| settings | accounts | 9 | 71 | Detected RoyalSpartanIIX · AlecaFrame lastUsername.txt · no profile yet |
| item-deeplink | landing | 14 | 70 | 16 points spanning 3.8 days · market snapshot · newest Sep 28 07:20 PM |
| item-deeplink | landing | 11 | 54 | keep 1 for collection; market 90p · R10 · median 85.5p |
| lookup | landing | 11 | 79 | Sign-in failed warframe.market is showing a Cloudflare browser check (http 403) |
| lookup | landing | 9 | 54 | 19 planned listings are parked until posting goes live |
| lookup | landing | 15 | 79 | WFM Trader · refreshed 21:12 · 471 history events · prices refresh every 15 min |

Status/metadata lines (data-driven; listed for completeness):

| page | state | words | chars | string |
|---|---|---|---|---|
| index | #tools/deals | 13 | 64 | · 389 live in 12h (88 spreads · 301 undercuts) · cursor 373/3888 |
| index | #tools/trends | 9 | 38 | · 2 spiking · 26 fading of 250 tracked |
| index | #tools/wl | 11 | 36 | · 1 buy hit · 0 sell hit · 2 waiting |
| index | #tools/ducats | 12 | 50 | · 58 sell (1227p) · 29 burn (2360 ducats) · 7 hold |
| index | #tools/craft | 9 | 28 | · 66 craft · 7 buy · 45 skip |
| index | #tools/relicev | 17 | 64 | · EV 3111p if opened vs 7935p sold · 38 open / 78 sell / 18 hold |
| index | #tools/sets | 18 | 75 | · 5 complete · 9 one away · 24 two away · 26 targets · 387p modelled profit |
| index | #tools/sets | 11 | 38 | · 5 ready · 9 one away · 10 part sales |
| index | #tools/meta | 12 | 50 | · post-patch 44.0.1 (0.73d) · 6 up · 6 down of 120 |
| collection | collection | 9 | 43 | · 56/120 collected · 64 missing · 120 shown |
| collection | collection | 19 | 106 | · item icons from the WFCD image CDN · floor prices from this PC's local WFM snapshot (data/prices.json) · |
| collection | relics | 10 | 45 | · 121/805 owned · 34 dropping now · 805 shown |

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
| rendered: trade plan header | · built 29h ago · MR 22 |
| rendered: home alerts | Could not sign in to the market siteSign-in failed warframe.market is showing a Cloudflare browser check (http 403)19 planned listings are parked until posting goes liveNot live - plan onlyNothing is posted automatically |

How the badge is derived (read live from `app.js`, not assumed): `dry = set.dry_run === true || plan.dry_run === true`, then the chip prints `Not live - nothing is posted` when dry. The two inputs are `scripts/trader/settings.json` and `data/trader_plan.json`; **`data/config.json` carries no `dry_run` key at all**, so it is not the gate for this badge. Both real inputs are `true` above, and the rendered copy is the Not-live wording - the badge cannot claim Live while posting is locked.

The gate never flips the kill switch, never posts, never saves settings.

## 7. Themes - 4 palettes (2 dark, 2 light) on every page

Thresholds: unreadable = text/background contrast below **2.2:1** (WCAG AA wants 4.5:1 for body text). Elements whose background is a gradient/image are counted as *unmeasured* rather than guessed; the page base colour is the theme's own `--bg`.

| theme | mode | page states | elements scanned | unreadable (<2.2:1) | colour outside the 10 palette entries | unmeasured (gradient bg) | errors |
|---|---|---|---|---|---|---|---|
| Vor Orange | dark | 15 | 2366 | 0 | 6811 | 192 | 0 |
| Kuva Crimson | dark | 15 | 2366 | 113 | 6811 | 192 | 0 |
| Frost Light | light | 15 | 2366 | 10 | 6811 | 192 | 0 |
| Cephalon White | light | 15 | 2366 | 9 | 6811 | 192 | 0 |

"Colour outside the palette" is informational: the semantic tones (`--up` green, `--down` red, warn red) are literals by design and are expected in that count. The check that fails on it is the cross-theme one below.

Low-contrast findings: 4 of 60 theme x page states.
- index/home Frost Light (light): 9 element(s), e.g. [{"text": "Sold", "cls": "badge sale", "tag": "span", "color": "rgb(74, 222, 128)", "cr": 1.74, "bg": "rgb(255,255,255)", "count": 9}]
- index/home Cephalon White (light): 9 element(s), e.g. [{"text": "Sold", "cls": "badge sale", "tag": "span", "color": "rgb(74, 222, 128)", "cr": 1.74, "bg": "rgb(255,255,255)", "count": 9}]
- index/inventory Frost Light (light): 1 element(s), e.g. [{"text": "Show advanced columns", "cls": "btn", "tag": "button", "color": "rgb(22, 32, 44)", "cr": 1.07, "bg": "rgb(33,22,26)", "count": 1}]
- collection/relics Kuva Crimson (dark): 113 element(s), e.g. [{"text": "I", "cls": "cl-rref", "tag": "span", "color": "rgb(127, 29, 29)", "cr": 1.85, "bg": "rgb(26,17,20)", "count": 113}]

Colours that did **not** change between the dark theme (0) and the light theme (14): 1 element(s) total, 1 of them unreadable.
- index/home: 1 unreadable, e.g. [{"text": "Sold", "cls": "badge sale", "tag": "span", "color": "rgb(74, 222, 128)", "cr_dark": 10.3, "cr_light": 1.74, "bg_dark": "rgb(20,23,29)", "bg_light": "rgb(255,255,255)", "low": true}]

## 8. Id union vs design/_stage1/ids_before.json

ids_before.json pages: index=172, collection=28, cards=20, settings=36, item=25, lookup=0

ids found live: index=6752, collection=803, cards=246, settings=1722, item=250, item-deeplink=251, lookup=422

**Missing: 0** 

Sanctioned removals/moves applied (5):
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
