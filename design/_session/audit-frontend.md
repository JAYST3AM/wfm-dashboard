# Trading Session — front-end audit (read-only)

Repo: `F:/VSC Projects/wfm-dashboard` · branch `main` · audit date 2026-09-29
Scope: hash router, Home/Trade render surfaces, whisper wiring, state, id/copy conventions, extension
points for a persisted **Trading Session** (`#trade/session`) — per `docs/trading-session-workflow.md`
§1,2,3,6,7,8,12,15.
Method: source read only. No server started, no browser driven, no files changed except this one.
Line numbers are `static/app.js` unless another file is named.

---

## 1. VIEW / ROUTE MAP

One SPA (`index.html`) + four standalone pages. No modules, no build step: every `static/*.js` is a
classic script sharing globals (`app.js:1` `'use strict';`).

| Piece | Where | Notes |
|---|---|---|
| `const VIEWS = ['home','inventory','trade','tools']` | `app.js:57` | the only four hash views |
| `const VIEW_ALIAS = {...}` | `app.js:60-61` | `more/market/player → tools`, `history/trader → trade` |
| `const TOOL_SLUGS = [...]` | `app.js:66-67` | 13 slugs, launcher order; `''` = launcher |
| `function showView(v, sub)` | `app.js:69-91` | toggles `#view-<name>.hidden`, moves the rail's `.active` **and** `aria-current="page"` (71-83), redraws chart (84), `markScrollers()` on trade (85), re-runs `switchInvView` (88), delegates `showTool(sub)` (89), calls `window.wfmRenderHome()` (90) |
| `function showTool(slug)` | `app.js:95-107` | unknown slug → `''` (launcher); hides `#toolsLauncher`, toggles `#toolsWs [data-tool="<s>"]` by **data-tool, not id** (100-104); extra hooks per slug (105-106) |
| `function switchInvView(v)` | `app.js:111-126` | `#invViews [role=tab][data-v]`, remembers `wfm.invView` |
| `function switchTradeTab(panelId)` | `app.js:129-139` | `#tradeTabs [role=tab][data-tp]`; **unknown panel falls back to `tp-sell`** (133); toggles `#view-trade .tpanel` by id (135); `if (panelId === 'tp-orders') renderOrders()` (137) |
| `function applyHash()` | `app.js:141-164` | the router |
| `applyHash(); addEventListener('hashchange', applyHash)` | `app.js:1916-1917` | both entry points |

`applyHash()` in detail (`app.js:141-164`):
1. `raw = (location.hash || '#home').slice(1)` (142); split `?` then `/` → `[v, sub]` (143-144).
2. Hard redirects, `location.replace`: `collection`/`cards` → `/<v>.html` (145), `mastery` →
   `/collection.html#mastery` (149), `more`/`market` → `#tools` (150), `player` → `#tools/player` (151).
3. `search` → `showView('home')` + `globalSearchOpen(q)` (152-156).
4. `view = VIEW_ALIAS[v] || 'home'` (157) → `showView(view, sub)` (158).
5. Trade: `switchTradeTab(v === 'history' ? 'tp-history' : (sub ? 'tp-' + sub : 'tp-sell'))` (160).
6. Inventory: `switchInvView(sub || state.invView)` (163).

Why a page decides what to render: `showView()` unhides the section; each renderer then fills ids it
owns. Data-driven renderers are called from `load()` (`app.js:1347-1398`, called once at 2221 and on a
timer at 1057-1065), not from `applyHash()`; only Orders is lazy (`ordOpenFetch()` at 788-793, called
again from `load()` 1374 so a deep link landing before the plan finishes opening).

Ids are declared in `index.html` markup, not built by JS: `#view-home` (30), `#view-inventory` (103),
`#view-trade` (183), `#view-tools` (345). Sub-panels: `#tp-orders` (195), `#tp-sell` (232), `#tp-buy`
(258), `#tp-history` (269), `#tp-advanced` (300) — exactly one `.tpanel` ships visible (`tp-sell`).
Workspaces: `#toolsLauncher` (346) + `#toolsWs` (446) holding `<div class="tws hidden" id="tws-<slug>"
data-tool="<slug>">`; the Player workspace deliberately keeps the moved id `#view-player` (599).

Deep links that exist today: `#trade/orders`, `#trade/sell`, `#trade/buy`, `#trade/history`,
`#trade/advanced`, `#history`, `#inventory`, `#inventory/materials`, `#tools`, `#tools/<slug>`,
`#search?q=`, plus legacy `#more #market #player #mastery #trader`. `#trade/session` does **not** exist
(`grep trade/session static/app.js` → no hits) and today renders the **Sell** panel via the 133 fallback.

Rail: `static/shell.js` — `RAIL`/`RAIL_GROUPS` (67-78), `ALIAS` (85-87, must stay in step with
`VIEW_ALIAS`), `hashView()` (89-92) splits on `?` then `/` so `#trade/session` still marks the Trade
pill with no shell change needed. Chrome is one source: a page only declares
`<body data-shell="index" data-shell-actions="search syncState refresh png">` (`index.html:17`).

---

## 2. WHERE THE LOOP'S PIECES RENDER TODAY

### (a) Home Today strip + the single Next action card
* Today strip: `renderTodayStrip()` `app.js:233-243` → `#kpis` (4 `.kpi`: `#todayEarned`,
  `#todaySales`, `#todayTrades`, `#platinumNow`). Basis picked by `tradesLeftReading()` `app.js:218-231`
  (SUMMARY.trades first, else `FEAT.limits` only while it still covers today). The strip's *detail*
  rows (credits/items/sessions/materials/week) come from `home.js` `renderTodayDetail` (`home.js:240`)
  into `#homeToday` (markup `index.html:50`, inside `<details id="todayMore">`).
* Next action: `renderNextAction()` `app.js:291-340` → `#homeSellNext` / `#sellNextList`.
  Facts from `homeDemand()` (266-272) + `demandCell()` (274-283); buyer line from `homeBuyers(slug)`
  (286-289) reading `FEAT.runqueue.queue` — **no new fetch**. Copy for the head link is written at 317
  (`Open Trade` / `See buyers in Trade`). One CTA only: `<a class="home-open" href="#trade">`
  (`index.html:58`). Then it calls `renderSellQueue(rows)` (339).
* Alerts: `home.js` `buildAlerts()` (~380-442) + `renderAlerts()` (444-467) → `#alertsCard`/`#homeAlerts`,
  hides itself and sets `#homeMain.no-alerts` when empty.
* Recent: `home.js` `renderRecent()` (475-509) → `#homeRecent`/`#recentMeta`, `RECENT_EVENTS = 10`,
  sorts newest-first itself, notes render as notes. Driven by `window.wfmRenderHome` (512-536) which
  fetches `/api/trader,/api/trades,/api/feature/{progress,baro,killswitch,hygiene}`.
* `load()` calls the Home renderers: `renderTodayStrip()` 1372, `renderHomeHead(); renderNextAction();`
  1376, `wfmRenderHome()` 1377.

### (b) Trade > Sell recommendations
* Plan table: `renderTrader()` `app.js:558-619`, plan rows painted at 574-594 into `#planList`
  (markup `index.html:242`), from `TRADER.plan.plan` (`/api/trader`). Header `#planMeta`,
  gate chip `#postMode` (569-573, `Not live - nothing is posted` vs `Live`). Held-back list
  `#heldList`/`#heldMeta` (595-598, inside `<details id="heldAcc">` 243). Attention/undercuts
  `#attnList`/`#attnMeta` (599-619). Row click opens the drawer via one delegated listener at
  `app.js:1929-1933` (`[data-slug]` → `wfmOpenItem`).
* Recommendation prose/verbs: `advOf()` 379-382, `advTag()` 385-393, `advRec()` 394-407,
  `advBits()` 408-416, `advNote()` 418-421 — the "Why?" material (§7) already exists as
  `advisor.reasons` (used as a title at `app.js:445`).
* The retired duplicate: `renderPicks()` 423-462 (`#sellPicks`) is kept only for the export path.

### (c) The sell queue
* `renderSellQueue(rows)` `app.js:344-376` → `#sellQueueList` + `#sellQueueMeta` (markup
  `index.html:70-75`). Dedupes by slug (350-356), `QUEUE_ROWS = 5` (256), rows are
  `<a class="hnext-row" href="#trade">` (366) — every row's one action is *go to Trade*.
* Plan source: `homePlan()` 259-262 (`TRADER.plan.plan`), i.e. the same payload as (b).

### (d) Trade > Orders live book, rank ladder, per-row Whisper
* State: `const ORD = {...}` `app.js:672-673`; `ORD_STS` 674; `ORD_ST` 675 (server's own status order).
* Toolbar: `#ordQ` (200), `#ordRank` (201), `#ordStatus` chips (204-209), `#ordRefresh` (210).
* `renderOrders()` `app.js:862-902` — `ordPrefill()` 780-783 (opens on `ordTopSlug()` 774-777 = plan
  row 0), `AbortController` so one book at a time (877-883), GET `ordUrl()` 795-798
  (`/api/orders?item=<slug>&rank=<r>&limit=<ORD.limit>`).
* Painting: `ordHead()` 807-813 (`#ordItem`), `ordChips()` 699-715, `ordOpts()` 816-825,
  `ordLadder()` 828-842 (`#ordValues`, the per-rank table: Rank / Lowest sell / Highest buy / Sells /
  Buys — this is the rank-aware source of truth), `ordPaint()` 756-772 (`#ordSell` 221, `#ordBuy` 226,
  `#ordMeta`), `ordMetaText()` 733-752, `ordSort()` 719-724, `ordEmptyLine()` 726-731, `ordErr()` 800-805
  (`#ordErr`). Empty states use `EMPTY_ICON` (30).
* Row: `ordRow(o, kind)` `app.js:846-860` — `.ordrow[data-kind][data-st]` with `.ordp .ordq .ordr
  .orduser .ordrep .ordst` + `<button class="ordwsp" data-user data-price data-rank data-kind
  title="Send this whisper in game">Whisper</button>` + `<span class="ordres" aria-live="polite">`.
  **No per-row item/rank is on the wrapper** — the button carries `data-user/price/rank/kind` only.
* Wiring: `wireOrders()` `app.js:1979-2001` — one delegated click on `#tp-orders` → `.ordwsp` (1985-1988),
  Enter on `#ordQ` (1981), `#ordRank` change (1983), status chips re-paint only, never refetch (1990-2000).
  `bind('ordRefresh', () => renderOrders())` 1978.

### (e) Recent activity / history
* Trade > History: `renderHistory()` `app.js:493-532` → `#histKpis` (KPIs 496-502), `#histMeta` (503),
  `#tradeLog` (512-531) from `TRADES` (`/api/trades`). Filter chips `#hFilters` wired at 1940-1943
  (`hFilter` at 484). Balance column via `balAt()` 486-491.
* Same page: `renderSessions()` 1537-1551 (`.sessrow` per past session — the *existing* `sessions`
  feature, `/api/feature/sessions` → `data/session_stats.json`, mapped at `server.py:170`), `renderTiming()`
  933, `renderPlatLedger()` 1033, `renderNotify()` 1017.
* Home "Recent" is `home.js:475-509` (separate, reads `/api/trades` again).
* Auto-refresh of all of it: `syncAutoRefresh()` 1057-1065 (`setInterval(load, 30s → capped 60s)`),
  plus the server sync clock polled every 60 s (`SYNC_POLL_MS` 1077, `loadSyncState` 1102, `setInterval`
  2227). No interval anywhere on the order book — `tests/test_trade_orders_tab.py:159` asserts
  `setInterval`/`setTimeout` absent from the Orders block.

---

## 3. WHISPER WIRING

* Button → `ordWhisper(btn)` `app.js:907-931`, called only from the delegated listener at 1985-1988.
* Guards: refuses a detached button / hidden row (908-910).
* Request: `POST /api/whisper`, `Content-Type: application/json`, body
  `{ item, user, price: Number(btn.dataset.price)||0, kind: 'sell'|'buy', mode: 'send' }` and
  `rank` only when finite (912-916). So `mode` is hard-coded `'send'` here; the server also accepts
  `'copy'` (`server.py:743-812`).
* Server (`server.py:743-812`): validates item/user/kind/mode/price/rank (400 on bad input, never 500),
  local cooldown `WHISPER_GAP` → 429 with a `reason`, per-minute cap → 429, 503 if `whisper.py` is
  missing, else builds the line, copies it, and in send mode types it. Answer shape (811-812):
  `{ok, message, line, copied, sent, reason}`. Ledger row per call in `data/whisper_log.json`
  (`docs/whisper.md:95-110`).
* Feedback: the row's own `<span class="ordres" aria-live="polite">` — `app.js:925-930`: `Sent to game`
  (ok), `Copied - game not running` (ok), else the server reason verbatim, plus `.ordres.bad` for red
  (`style.css:856-858`). The button is disabled and reads `Sending` while in flight (917-918, restored 929).
  **There is no toast/notification component anywhere** — the only other feedback primitives are
  `sfx.play('done'|'warn')` (`sfx.js:9`, used at `app.js:2213-2214`) and `alert()` on Refresh failure.
* Where a `CONTACTED` state hooks in **without duplication**: `ordWhisper()` is the single funnel for
  every whisper click (one call site, 1987). On the success branch (`ok = true`, 925-926) the code
  already has everything §3 asks to persist except `slug` (it has `ORD.slug` at 912) and the
  pre-state — items, user, price, kind, rank. A POST from there (or a server-side side-effect inside
  `/api/whisper` when `mode === 'send'`) writes CONTACTED once, keyed by item+rank+buyer, without a
  second whisper path. Do **not** add a second button or a second fetch site; `tests/test_orders_api.py`
  / `test_whisper.py` pin the current contract.

---

## 4. STATE + PERSISTENCE

* No store, no framework, no event bus. Two globals:
  `let ITEMS, SUMMARY, PLAT, REPORT, TRADES, TRADER, GAMENEWS, FEAT = {}` (`app.js:12`) and
  `let state = {...}` (`app.js:13`, UI-only: tab/sort/q/invView/matView/dojoTier/player/cfg).
  Feature payloads are session-only under `FEAT['<name>']` (`load()` 1358-1368, 25 endpoints in one
  `Promise.all` + `/api/feature/itemhist` + `/api/feature/materials`). Order-book state is `ORD`
  (672). Catalog cache: `CATALOG`, `CATALOG_LOADING` (20).
* Full refresh = `load()` (`app.js:1347-1398`) re-fetching everything and re-running every renderer;
  called at boot (2221), on auto-refresh (1060), after `traderAction()` (1945-1955), after Refresh
  (2209-2217) and after the kill switch (2003-2012). `loadTrader()` (1892-1895) is a lazy single fetch.
* **What survives a reload today: nothing about trading state.** Only UI preferences in
  `localStorage`: `wfm.theme` (app.js:1900, theme.js), `wfm.themeFilter` (theme.js:121),
  `wfm.invView` (116, 2170), `wfm.matView` (2155/2161), `wfm.dojoTier` (2134/2141),
  `wfm.settings.advanced` (settings.js:542), `wfm.chat.open` (chat.js:28), and chart prefs under
  `wfm_chart_v2` (chart.js:19, 60-67). Pending trades, session totals and queue position are therefore
  **server-side JSON by necessity** (§11 of the workflow): `data/*.json` read through
  `/api/feature/<name>` (`server.py:170`, 183). Nothing in the front end may be the only home of
  session/pending state.

---

## 5. ID + COPY CONVENTIONS

Ids and copy rules are pinned by tests, so treat both as contracts.

* **Ids**: lowerCamelCase, no separators (`sellNextList`, `ordValues`, `planList`); panel ids are
  prefix-kebab (`tp-orders`, `tt-orders`, `tws-news`, `#view-<name>`); `data-v` / `data-tp` /
  `data-tool` / `data-st` / `data-slug` are the switch attributes. Exactly one `<div class="card…"
  id="…">` per band on Home (`test_home_layout.py:42-50` pins the exact six). Duplicate ids are a QA
  gate failure (`design/_stage10/gate.js` check 8 vs `design/_stage1/ids_before.json`; `design/_audit/qa_ids.js`).
* **Copy**: player language, 8 words / 90 chars max, ≤1 sentence-ending period per visible string
  (`tests/test_copy_diet.py` MAX_WORDS/MAX_CHARS/MAX_PERIODS, scanning quoted strings and text nodes);
  banned extended phrasings listed in `tests/test_copy_simplicity.py:20-36` (`= about `, `see Advanced`,
  `no standing buy orders`, …). `utils`: `escHtml` (1401), `pretty` (1402), `sbits` (1406,
  one `<span>` per fact), `fitSegments`/`clipWords` (1409/1418). Long explanation goes into a `title=`
  (budget 8 words), never a paragraph — `renderPicks` 445, `renderNextAction` 329-336, `renderTrader` 581.
* **Progressive disclosure**: `<details class="acc sub">` for in-card extras (`heldAcc` 243,
  `todayMore` 48); `.explain` is hidden by default and shown only with `<html data-adv="on">`
  (`style.css:452-453`, knob from `/api/config.values.advanced` via `adv.js`); the "extra columns"
  rows use `body.show-a .hide-a { display: table-cell }` (`style.css:381`, toggled at 2186-2192);
  engine internals live in the Trade **Advanced** tab (`#tp-advanced`, `index.html:300`).
* **Reachability**: `tests/test_ia_reachability.py` — rail is exactly six destinations in order
  (89-101), every `TOOL_SLUGS` slug has a launcher entry **and** a workspace (164-173), the twelve old
  More-page list ids still render (205-217), legacy hashes resolve, and **no id from
  `design/_stage1/ids_before.json` disappeared** (only sanctioned moves: `view-more → view-tools`,
  `heroCard/heroMeta/homeSync/kpiCard`, `view-mastery`; `gate.js` SANCTIONED list). `test_app_shell.py`
  forbids any page re-declaring chrome (`<header>`, `#mainnav`, `#themePanel`, `#themeGrid`).

---

## 6. EXTENSION POINTS for a persisted Trading Session

Slot-in order, cheapest first:

1. **Route** — add `session` to the trade tab vocabulary, not a new top-level view: extend
   `VIEW_ALIAS`/`applyHash()` so `#trade/session` maps to `tp-session` (`app.js:159-161` already does
   `'tp-' + sub`, so a new `<button id="tt-session" data-tp="tp-session">` + `<div id="tp-session"
   class="tpanel hidden" role="tabpanel" aria-labelledby="tt-session">` in `index.html` next to 185-232
   is enough — no router change needed at all, exactly like `#trade/orders`). `switchTradeTab`'s
   unknown-panel fallback (133) is what makes this fail-safe; keep `tp-sell` as the shipped default.
   Add a lazy open hook in `switchTradeTab` beside line 137 so the session panel reads on open, never
   on a timer.
2. **Panel body** — a new `<div id="tp-session">` in `index.html` + a renderer in a new
   `static/session.js` (loaded like `adv.js`/`export.js`, before/after `app.js` per dependency), called
   from `load()` (1388 block) and from the tab open. Keep `app.js` from growing further (§10).
3. **Start Trading entry** — Home's Next-action footer (`renderNextAction` 333-338) and the Sell plan
   card head (`index.html:236-239` actions row) already own the "one primary action" slot; add the
   `Start trading` control there rather than a new card (a seventh Home card breaks
   `test_home_layout.py:49`).
4. **Whisper → CONTACTED** — see §3: hook the existing `ordWhisper()` success branch (925-926) or the
   `/api/whisper` server side-effect; do not add a second whisper call site.
5. **Confirm/complete** — one canonical POST (e.g. `/api/session/confirm`) then `await load()` like
   `traderAction()` (1945-1955) so every renderer updates once. Reuse `.ordres`-style inline status +
   `sfx.play` for feedback, since there is no toast component (adding one is new surface, and it would
   need a copy-diet-clean string per message).

Reuse rather than rebuild:
* **Drawer / item quick look** — `window.wfmOpenItem(slug)` (`drawer.js:1035`), the single delegated
  Trade listener already calls it for `[data-slug]` (`app.js:1929-1933`); give session rows a
  `data-slug` and they get item look + the `Open full analysis ↗` link (`drawer.js:222`) for free.
* **Orders/rank lane** — `renderOrders()`, `ordLadder()`, `ordRow()`, `ordOpts()` and the status-filter
  chips are the source of truth; a session panel that needs "best buyer + price + status + rank" should
  read the same `/api/orders` answer (or a server-side projection of it), never a second book. §2 of
  the workflow ("do not duplicate order-book logic") is a direct instruction here.
* **Whisper row** — `.ordwsp` + `.ordres` markup and `ordWhisper()` behaviour (disabled-while-sending,
  aria-live, `.bad`), plus its CSS `style.css:852-858`.
* **Ladder/table recipe** — `ordLadder()`'s `<table class="ordtbl">` (834-841) and `sbits()` for
  label+value meta lines; `.sessrow` (1545-1550) is the existing one-line-per-session row shape.
* **Empty states** — `EMPTY_ICON` (30) + `<div class="empty">`; hidden-card pattern (`alertsCard`
  `home.js:450-457`).
* **Refresh** — `load()` (1347) is the one refresh; do not add a session-only fetch loop.
* **Feedback** — `sfx.play` (`sfx.js:9`) + an inline `aria-live` span. There is no toast to reuse.

---

## 7. RISKS

1. **`#trade/session` silently means Sell today.** `applyHash()` 160 → `switchTradeTab('tp-session')` →
   `133` falls back to `tp-sell`. Shipping the panel without the tab/panel id renders the Sell plan at
   `#trade/session` with no error — a confusing, test-invisible bug. Pin it in
   `tests/test_trade_orders_tab.py`-style assertions plus the browser gate.
2. **Exact-card-count tests on Home.** `test_home_layout.py:42-50` asserts the Home band ids are
   *exactly* `['todayCard','homeSellNext','alertsCard','sellQueueCard','recentCard','chartCard']` in
   order, and `test_density_views.py` pins `#homeMain`'s grid rows/columns (`body.shell-fit #homeMain >
   #homeSellNext { grid-column: 1 / span 2 }` etc.). Any new Home card **fails the suite**, not just a
   lint — extend Next action instead.
3. **Id-union baselines.** `design/_stage10/gate.js` check 8 and `design/_stage2/qa_ia.js` compare the
   rendered id union against `design/_stage1/ids_before.json`; ids may be *added* freely but renames
   must be added to the SANCTIONED map in `gate.js` or the gate reports a regression. `#trade/session`
   must also appear in the gate's route list, or the new route ships unmeasured (workflow §13/§14).
4. **Copy-diet failures are silent in source.** The gate's copy check counts *rendered* strings, so
   data-driven lines (e.g. `· 19 planned listings are parked…`, the current report's 53 offenders) are
   the realistic trap for new session copy: build status lines as one `<span>` per fact with `sbits()`
   and push detail into `title=`.
5. **Route/alias drift.** `VIEW_ALIAS` (`app.js:60`) and `shell.js` `ALIAS` (85) must stay in step, and
   `test_ia_reachability.py` pins the legacy-hash table; adding `session` to one and not the other makes
   the rail mark a different pill than the router shows. (`#trade/session` needs no change on either —
   `hashView()` splits on `/` — so prefer adding no alias at all.)
6. **No polling on the book.** `test_trade_orders_tab.py:159` asserts Orders contains no
   `setInterval`/`setTimeout`. A session panel that auto-polls buyers would break that class of
   assertion if added to the Orders block; put a session refresh on the existing `load()` cadence.
7. **State that is only in JS.** Nothing pending/session-shaped survives reload (§4) — the front end
   must not mark CONTACTED locally-only, or a refresh loses the reconciliation pairing (§11: "pending
   state must survive browser refresh/restart"). One POST per click, then `load()`.
8. **Whisper's own guards are the pacing.** Both the client path and `/api/whisper` (429 cooldown /
   per-minute cap, `server.py:785-792`) refuse; a session "next buyer" flow must surface the refusal
   reason verbatim (that is already the `ordWhisper` contract at 924-927) rather than retrying, and
   must never auto-send (`docs/whisper.md:47-62`; workflow §11 forbids automatic posting).
9. **Duplicate ids from copy-paste.** The session row would naturally want `.ordrow`/`.ordres`
   classes; reusing the *classes* is fine, reusing ids (`#ordSell`, `#ordValues`) is not — ids are
   unique across the page and the QA gate counts them.
10. **`EMPTY_ICON`/icon repaint.** Assigning `textContent` to a host carrying `data-icon` drops its
    glyph; `iconRepaint()` (`app.js:1964-1970`) must be called after any dynamic label swap (the
    existing convention, e.g. 1948, 2210).

---

## 8. Harness conventions (for the new route's QA)

* `design/_stage10/gate.js` (+ `gate.py`) is the release gate: puppeteer-core resolved from
  `WFM_PUPPETEER` / node_modules / `F:/VSC Projects/pb-bench/node_modules/puppeteer-core`, Chrome at
  `C:/Program Files/Google/Chrome/Application/chrome.exe`, live app on `http://127.0.0.1:8787`,
  viewports `1920x1080/1536x864/1440x900/1366x768/1280x800`, themes `[0,2,14,28]`, writes
  `gate-raw.json` + `gate-report.md`. It is READ-ONLY on the app — `#trade/session` is drivable as a
  hash, but a *Confirm* click must not be part of the gate unless the check is fixture-backed.
  Current verdict: **FAIL** (3/107: themes ×2, copy ×1) — pre-existing, reported honestly.
* `design/_stage2/qa_ia.js` walks the rail per page, every Tools workspace, legacy hashes, and the id
  union. `design/_audit/qa_{ids,nav,flows,deadspace,widths}.js` + their `.json` are the earlier audit
  harnesses; `tools/make_preview.py` is the README-tour/screenshot driver (also puppeteer-core).
* Id baselines: `design/_stage1/ids_before.json` (+ `_stage4`, `_stage8`), checked by
  `design/_stage1/verify_ids.py` and `design/_stage2/verify_ids.py`.

## 9. UNVERIFIED

* All of §7 is reasoned from source + tests; **no browser run, no server start, no test execution was
  performed** in this audit. The gate verdict quoted is from the committed `gate-report.md`
  (2026-09-28 21:11), not a fresh run.
* Whether `ORD.slug` is always the slug (not a typed query) when a session-style row whispers: `912`
  falls back to the raw `#ordQ` value, so a hand-typed query would persist a non-slug. Confirmed by
  reading only, not observed.
* `/api/feature/sessions` and `/api/feature/runqueue` payload shapes were read from their renderers
  (`renderSessions` 1537-1551, `homeBuyers` 286-289), not from the server handlers.
