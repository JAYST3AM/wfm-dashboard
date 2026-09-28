# Stage 3 - Home is the action surface (Jay 2026-09-28)

Stage 3 of the IA rework. Home answers four questions and nothing else:

> "What should I sell? How much? Who wants it? How much have I made today?"

## The five bands (this order, nothing else)

| band | id | what it holds |
| --- | --- | --- |
| TODAY | `#todayCard` (`#kpis` strip + `#todayMore` disclosure) | earned today · sales today · trades left · platinum now - each value once |
| NEXT ACTION | `#homeSellNext` | the one best item: name, price, demand, sold 48h, liquidity, copies, buyer (or the buyers link) |
| ALERTS | `#alertsCard` | only things that need a decision; hidden when there are none (the action band then widens) |
| SELL QUEUE | `#sellQueueCard` | the next 5 different items: item, price, demand, one quick action each |
| RECENT | `#recentCard` + `#chartCard` | the last 10 trade events + the small platinum chart |

At >=1200px Home fills the window as a 3-column, 5-row grid (`static/home.css`); below that it is one
scrolling column. The chat dock is a separate, collapsible column (`static/chat.css`).

## Where the merged-away values went (no unique data lost)

* credits, credits today, items added/removed, trades, sessions, materials, the week roll-up and
  inventory value -> the strip's **Today's detail** disclosure (`#homeToday`), one tap below.
* the session roll-up list -> Trade > History > Sessions (already existed).
* game news -> **Tools > Game news** (`#tws-news`, slug `news`), same card + list ids.
* the day's platinum start/end, the progress store's read time, the advisor's trend word and price
  move, the plan size -> hover titles on the values they belong to.

## Ids removed (4) - all duplicates, all reported

| id | reason | replacement |
| --- | --- | --- |
| `heroCard` | duplicate of the Today strip (`#kpis`) and `#chartCard` | strip cells + chart |
| `heroMeta` | duplicate of `#homeSub` (the page date line) | `#homeDate` in the header |
| `homeSync` | duplicate of `#syncState` (the header clock) + the footer line | header/footer |
| `kpiCard` | merged into the Today strip (`#kpis`) | `#kpis` |

Pinned in `tests/test_ia_reachability.py::test_no_id_from_the_stage1_snapshot_disappeared` with the
same reasons, so no other id can disappear silently. `#newsCard` / `#newsList` were **kept** - they
render in the new Tools workspace.

`tests/test_density_views.py::test_every_id_and_control_survives` had `homeSync`/`heroCard`/`kpiCard`/
`heroMeta`/`newsCard`/`newsList` in its view-home list; the list now names the surviving Home ids
(and `newsList`/`tws-news` moved to the tools list). Its `test_home_fills_the_left_column_beside_the_chat_rail`
became `test_home_fills_the_window_in_five_bands`.

## Duplication rules enforced on Home

* the header's `Trades .../day left` chip steps aside while Home is the active view
  (`static/style.css`: `body:has(#view-home:not(.hidden)) #chips .chip.warn { display: none; }`) -
  the strip owns that number on that page; other views keep the chip.
* one clock: the header carries the sync state, the footer the page refresh; nothing on the cards
  repeats either (`#todayCard`'s reading time is a hover).
* one date: `#homeDate` in the page header. The Today card repeats no date.
* one CTA per card: the Next action's head pill reads "Open Trade" when a buyer is named below and
  "See buyers in Trade" when the run queue names nobody (never two links to the same place).

## Chat dock

Collapsible, **closed by default**, one toggle (`#chatToggle`, in the home head), remembered per
browser (`localStorage['wfm.chat.open']`). Closed = no rail and no gap (the home grid is one column).
Open at >=1200px = a 340/360px column whose bottom edge meets the bottom of the view. Every feature
kept: local store, relay pull/post, profile stamp, the row whitelist. A closed dock does not poll.
The transcript is anchored to the bottom of the rail with the composer under it (Jay: "chat is too
far down" + "chat can go all the way down"), with a spacer (`#chatDock .chat-rows::before`) that
collapses once the history fills the rail, so scrolling stays sane.

## Also fixed in this pass

* `static/chart.js` `PlatChart.init` no longer passes `height: <wrap at init>` - that stale number
  outranked the live box forever (the canvas was 717px tall inside a 271px card, so only its top
  sliver showed: the "flat line with a sharp drop" Jay saw). Sizing now comes from `sizeCanvas()`,
  which reads the box at every draw.
* the Today strip's numbers are one size up and the earned cell only goes accent when it is a gain.
* the Sell queue gained its own column heads (Item / Sold 48h / List at) and a plural-safe copy line.

## Evidence

`design/_stage3/qa_home.js` (headless, read-only; never clicks a plan/queue action):

* fit: overX/overY/section overflow **0** on home, trade, inventory, tools and tools/news at
  1920x1080, 1536x864, 1366x768 - and with the chat dock open at the same three sizes.
* chat: closed by default (no `chat-open` class, dock `display: none`), toggle opens it
  (dock bottom == view bottom at all three sizes), reload remembers it, a second click closes it.
* the quiet-day state: alerts hidden -> the action band spans the row, nothing overflows.
* 0 console errors / page errors on index.

Screenshots (`C:/Users/jayde/AppData/Local/Temp/shotkit/shots/`): `s3-home-1920.png`,
`s3-home-1366.png`, `s3-chat-open-1920.png`, `s3-chat-closed-1920.png`, `s3-no-alerts-1920.png`,
`s3-today-detail-1920.png`, `s3-news-workspace-1920.png`, `s3-home-empty-1920.png`.

## Notes / open items

* the live data dir was mid-migration while this pass ran (one probe saw `items: 0`, `mr: null`,
  then full data again) - Home renders both states without overflow or console errors; the
  `#firstRun` card explains an empty inventory by design.
* `tests/test_density_cards.py` (6-10 failures) is the mod-cards page's own suite failing against
  `static/cards.css`, which was being edited by another agent during this pass - untouched here.
