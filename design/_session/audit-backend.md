# Backend audit — Trading Session workflow (READ-ONLY)

Repo `F:/VSC Projects/wfm-dashboard`, branch `main` @ `9718084` ("Docs: define end-to-end trading session workflow").
Spec: `docs/trading-session-workflow.md`. Conventions: `docs/navigation.md`, `docs/whisper.md`.
No file was modified by this audit. `scripts/trader/` is **gitignored** (unverified in CI — see §4.1).

## 1. Route inventory (`server.py`)

Handlers are two flat `if` chains: `do_GET` at `server.py:1041-1067`, `do_POST` at `server.py:1069-1215`.
There is no router/registry — every new session route is another `if p == '/api/...'` line in a 175-line method.

### GET (read-only by contract)

| Path | Line | Payload fn | Notes |
|---|---|---|---|
| `/` and any static path | 1043, 1067 | `_serve_file` | `.lstrip('/')` + `normpath`/`startswith(STATIC)` guard at 1031-1034 |
| `/api/summary` | 1044 | `summary_payload` 559 | MR, plat, trades left, value totals + `plat_hist` |
| `/api/items` | 1045 | `items_payload` 46 | owned rollup + price/rank lanes |
| `/api/catalog` | 1046 | `catalog_payload` 109 | slug/name/icon, in-memory cached |
| `/api/plat_history` | 1047 | `plat_history_payload` 129 | points + d24/d7 |
| `/api/trades` | 1048 | `trades_payload` 150 | **history + totals** |
| `/api/trader` | 1049 | `trader_payload` 549 | plan/state/settings/relist queue/undercuts |
| `/api/gamenews` | 1050 | `gamenews_payload` 540 | ⚠ **mutates** (below) |
| `/api/config` | 1051 | `dashcfg_payload` 438 | shells out `config.py --show/--schema` |
| `/api/sync` | 1052 | `sync_payload` 992 | auto-sync loop state |
| `/api/chat` | 1053 | `chat_payload` 948 | |
| `/api/trader/cfg` | 1054 | `cfg_payload` 404 | shells out `trader/settings.py --show` |
| `/api/profiles` | 1055 | `profiles_payload` 420 | shells out `profiles.py --list --json` |
| `/api/orders` | 1056 | `orders_payload` 635 | ⚠ **writes the order cache** |
| `/api/rank_values` | 1057 | `rank_values_payload` 677 | ⚠ **writes the order cache** |
| `/api/feature/<name>` | 1058-1065 | `feature_payload` 187 | 30 names in `FEATURES` 168-184 |
| `/api/report` | 1066 | raw `report.json` | |

**GETs that are not read-only (spec §11 "read-only routes": test "no mutation from read-only routes"):**

1. `/api/gamenews` → `gamenews_payload` → when the cache is older than `gamenews_cache_seconds` it calls
   `refresh_gamenews()` (492), which does **two network fetches** (forum RSS + Steam) and **writes
   `data/gamenews.json` non-atomically** (`server.py:533-537`: plain `open(...,'w')`). This is the one
   GET in the app that performs network I/O *and* a disk write on a normal page load.
2. `/api/orders` and `/api/rank_values` → `orderbook.snapshot()` → `orders.write_cache`
   (`scripts/orders.py:102-118`, atomic tmp+replace) writes `data/orders_cache/<slug>.json` on a
   cache miss. Benign (a cache, not account state), but it is a side effect on a GET and must be
   whitelisted explicitly in the "no mutation from read-only routes" test.
3. `GET /api/*` never lazily runs `sync_tick`; the only writes on the request path are the three above.

### POST (mutating)

| Path | Line | Effect |
|---|---|---|
| `/api/chat` | 1071 | `chat_post` 954 → atomic append `data/chat.json` (cap 300, 1.5 s gap) |
| `/api/whisper` | 1076 | `whisper_post` 743 → clipboard + keystrokes; ledger row via `whisper.send` |
| `/api/refresh` | 1087 | subprocess `refresh.py` then `snapshot_plat.py` |
| `/api/trades` | 1102 | **appends to `trade_log.json`** (see §5) |
| `/api/trader/plan` | 1116 | `trader/lister.py` subprocess |
| `/api/trader/cycle` | 1116 | `trader/detector.py --once` subprocess |
| `/api/trader/watch` | 1116 | `trader/watcher.py --once` subprocess |
| `/api/trader/hygiene` | 1133 | `trader/hygiene.py --once` |
| `/api/trader/flip` | 1133 | `trader/flipper.py --live` |
| `/api/trader/runqueue` | 1133 | `trader/runqueue.py` → `data/run_queue.json` |
| `/api/trader/notify` | 1149 | `notify.py --send` test ping |
| `/api/profiles` | 1157 | `profiles.py --create/--switch` (never called with `--apply` unless `body.apply`) |
| `/api/trader/settings` | 1179 | `trader/settings.py --set k=v` per pair |
| `/api/config` | 1195 | `dashcfg_set` 459 → `config.py --set` |
| `/api/trader/killswitch` | 1203 | atomic write `data/kill_switch.json` |

No route starts/reads a Trading Session, no route exposes pending/contacted trades, no route
confirms a trade, and no route reports inventory or platinum deltas for a *pending* trade.
`FEATURES` has `sessions` (`session_stats.json`, analytics), `invdiff`, `progress` — all historical.

## 2. Dataset → source of truth

| Dataset | Producer (file:line) | Persisted | Served by | Notes |
|---|---|---|---|---|
| Sell recommendations ("what should I sell") | `scripts/report.py:96 build_rows` (copy maths, floor/median/vol48) → `scripts/sell_advisor.py:219 advise` → `513 build_doc` | `report.json` (report.py:210), `sell_advisor.json` (sell_advisor.py:556 atomic_write 482) | `/api/report`, `/api/feature/advisor` (trimmed 207-210) | `advise` owns the rec vocabulary `list/burn_ducats/open_relic/assemble_set/finish_set/already_listed/keep/hold`, qty, price, `reasons[]`, `score` |
| Next action / Home metrics | **Front-end only**: `static/app.js:252-352` (`homePlan`, `homeDemand`, `renderNextAction`, `renderSellQueue`) reads `TRADER.plan.plan[0]` + advisor + run queue | none | `/api/trader`, `/api/feature/advisor`, `/api/feature/runqueue` | no server "next action" endpoint; Home picks plan row #1 |
| Today metrics (earned/sales/sessions) | `scripts/progress.py:536 collect` (`510 build_sessions`, `407 step_walk`, `463 count_items_gained`) | `progress.json` + `static/progress.json` (atomic_write 90) | `/api/feature/progress` | `today{trades,plat_delta,items_added,items_removed,materials_gained,sessions}` |
| Live order book | `scripts/orders.py:167 snapshot` → `282 book` / `265 counts` / `277 ranks` | `data/orders_cache/<slug>.json` (45 s TTL, `orders.py:43`) | `/api/orders` 635, `/api/rank_values` 677 | row shape `{platinum,quantity,rank,user,reputation,status,updated_ts}` (`orders.py:251 _row`) |
| Rank-aware pricing ladder | `scripts/fetch_lanes.py:52 lane_summary` (writer: `fetch_lanes.py`), re-exposed by `orders.values:317` | `price_lanes.json` → `items.<slug>.lanes.<rank>.{ask,bid,n_ask,n_bid,bid_low}` | `/api/rank_values` (orders first, lanes fallback 695-699), `/api/items` 89-101, `/api/feature/advisor` (`lane_rank` from `report.py:66 lane_price`) | rank the *save* proves owned comes from `report.py:89 own_ranks_of` (`mod_cards.json`) |
| Inventory counts / safe-to-sell | `report.py:96 build_rows` (`count`, `in_use_count`, `sellable_count`, `in_use_only` via `35 in_use_counts`); reservations/safe qty in `sell_advisor.advise` (`reserved`/`sellable`) | `report.json`, `sell_advisor.json` | `/api/report`, `/api/feature/advisor`, `/api/items` (owned `count` only — **no safe-to-sell**) | two different "sellable" notions coexist: `report.sellable_count` (minus equipped) vs `advisor.sellable` (minus equipped **and** reservations) |
| Inventory change detection | `scripts/invdiff.py:76 main` → `21 agg` / `50 compare` / `71 totals`; daily snapshots in `inventory_snapshots/owned_YYYY-MM-DD.json` | `invdiff.json` (130, non-atomic) | `/api/feature/invdiff` | per-day, not per-trade; no per-item timestamp |
| Platinum balance + ledger | readings: `scripts/snapshot_plat.py:15` (append/heartbeat 1800 s) and `scripts/import_aleca_stats.py`; ledger: `scripts/plat_ledger.py` (`156 balance_anchors`, `191 window_rows`, `218 check_reconciliation`) | `plat_history.json`, `plat_ledger.json` (jdump 84 atomic) | `/api/plat_history`, `/api/summary.plat`, `/api/feature/ledger` | `plat_history` write at `snapshot_plat.py:33` is **not atomic** |
| Trade history | writers: `/api/trades` (server 1102-1115), `scripts/log_trade.py:13`, `scripts/import_aleca_stats.py:104`, gitignored `scripts/trader/detector.py:626-628` | `trade_log.json` (471 events: 345 purchase / 122 sale / 4 note) | `/api/trades`, consumed by `progress`, `session_stats`, `plat_ledger`, `sell_timing`, `sell_advisor`, `item_history` | **no `id` field on any event** (0/471); imported rows carry `src` |
| Sessions / session stats | `scripts/session_stats.py:31 clusters` + `41 session` (45 min gap) → `session_stats.json`; `progress.py:510 build_sessions` re-derives the same clustering for Today | `session_stats.json` (129, non-atomic), `progress.json` | `/api/feature/sessions` (capped 12, 199-200), `/api/feature/progress` | **analytics over history** — nothing persisted about a *live* session |
| Pending whispers / contact state | `scripts/whisper.py:780 send` → `record` 744 → `append` 721 → `atomic_write` 687 (500-row cap) | `whisper_log.json` (12 rows) | **not served at all** — no route; `whisper.log_last` only used by CLI | the only per-contact record that exists, and the UI cannot read it |
| Alerts / undercuts / stale | `scripts/trader/watcher.py` → `trader_undercuts.json`; `trader/hygiene.py` → `hygiene_plan.json` (actions `hide`/`reprice`); `nudges.py` → `nudges.json`; `watchlist.py` → `watchlist.json` | those four files | `/api/trader` (undercuts), `/api/feature/{hygiene,nudges,watchlist}` | Home reads `hygiene` + `killswitch` (`home.js:519-524`) |
| Trader trade cap / limit | `scripts/trader/limits.py:98 run` (live save + `cap_for_mr` 52, `next_reset` 80) | `trader_limits.json` (`trade_cap/trades_left/trades_used/reset_melbourne`) | `/api/feature/limits` | |
| Player + buyer usernames/status | own account: `trader/limits.py:91 account_name` / `whisper.account:675` / `trader_state.json.account`; item alias: `scripts/player.py:173 read_alias` → `player.json.alias`; buyers: `scripts/trader/runqueue.py:76 buyers_for` (→ `run_queue.json`) and `orders._row:251` (→ `/api/orders`); chat stamp `server.chat_me:925` | `run_queue.json`, `trader_state.json`, `player.json`, `orders_cache/*` | `/api/feature/runqueue`, `/api/orders`, `/api/feature/player`, `/api/chat.me` | buyer `status` is `ingame/online/offline` from the WFM order's `user.status`; `runqueue` puts it in `buyer_status` |
| Player profile snapshot | `scripts/player.py:317 build_doc` → `save_json:341` (atomic) | `player.json` | `/api/feature/player` (`feature_payload` 396-401) | |

## 3. Reusable helpers (do not re-implement)

**Atomic JSON write**
- `scripts/plat_ledger.py:84 jdump(path, obj)` — mkdir + `.tmp` + `os.replace`.
- `scripts/config.py:283 _write_atomic(doc, p)` (newline-preserving), used by `339 apply_changes`.
- `scripts/sell_advisor.py:482 atomic_write(path, doc)`; `scripts/progress.py:90 atomic_write(path, doc)`.
- `scripts/player.py:341 save_json(path, obj)`; `scripts/whisper.py:687 atomic_write(path, doc)`.
- `scripts/watch_save.py:75 write_state(doc)` (same-dir `mkstemp` + replace + unlink-on-failure — the most careful pattern here).
- Inline: `server.py:888 sync_log_write`, `server.py:982-986 chat_post`, `server.py:1209-1211 killswitch`, `scripts/trader/detector.py:76 jdump`, `scripts/trader/runqueue.py:46 jdump`.
- **Missing (→ §6.1):** `trade_log.json` has no atomic writer anywhere.

**Config / limits loading**
- `scripts/config.py:388 read(p=None)`, `339 apply_changes(pairs, p=None)`, `257 validate(key, raw)`, `153 schema()`.
- Server mirrors: `server.py:826 sync_config_seconds()`, `438 dashcfg_payload()`, `459 dashcfg_set(pairs)`; startup read `server.py:18-27`.
- `scripts/trader/limits.py:22 read_live()`, `52 cap_for_mr(mr)`, `98 run()` → `trader_limits.json`.
- Trader engine settings: `scripts/trader/settings.py --show/--schema/--set` (shelled from `server.py:404 cfg_payload`).

**Price / rank lookup**
- `scripts/report.py:66 lane_price(lane_doc, rank) -> (ask, bid)|None` — the (None,None) rule: a slug *with* lanes but no orders at that rank must not fall back to the any-rank quote.
- `scripts/report.py:89 own_ranks_of(cards_doc) -> {slug: owned_rank}` (source `mod_cards.json`).
- `scripts/fetch_lanes.py:52 lane_summary(orders)`; re-exported as `scripts/orders.py:317 values(orders)`.
- `server.py:609 _rank_arg(raw)`, `623 _limit_arg(raw, cap=ORDERS_MAX)`.

**Order-book fetch / normalise**
- `scripts/orders.py:167 snapshot(slug, budget=TIMEOUT) -> {orders, fetched_ts, age_s, source:'live'|'cache'|None, error}` (45 s cache, 0.35 s spacing, 2 retries, stale-cache fallback).
- `scripts/orders.py:199 fetch(slug, budget) -> (orders, fetched_ts)`; `63 valid_slug(slug)`; `73 cache_path(slug)`.
- `scripts/orders.py:207 live(orders)` (visibility rule: `visible` **and** `quantity > 0`); `223 rank_of(order)` (missing → 0); `251 _row(order)` (buyer `user`, `reputation`, `status`, `updated_ts`); `265 counts`, `277 ranks`, `282 book(orders, rank=None, limit=40)`; `378 payload(...)`.
- **Do not use** `scripts/trader/lister.py:80 fetch_book(item_id)` for anything the UI reads (§4.1).

**Whisper send path (what actually talks to Warframe)**
- `scripts/whisper.py:780 send(text, item=None, price=None, kind=None, user=None) -> (sent: bool, reason: str)` — `find_game` 502 → `gate` 648 → `copy` 359 → `focus` 542 → `press_paste_and_enter` 582; one ledger row per call.
- `281 message(item, price, kind, rank=None)`, `297 line(user, item, price, kind, rank=None)`, `310 parse(text)`, `339 title_for(slug)`.
- `359 copy(text)`, `772 probe()`, `675 account()`, `744 record(...)`, `753 log_last(n, path=None)`, `687 atomic_write`.
- HTTP: `server.py:743 whisper_post(body) -> (status, payload)`; pre-checks `server.py:784-795` with module-level gates `WHISPER_GAP=2.0` / `WHISPER_PER_MIN=10` (`704-707`) — **a second, server-side rate limiter that duplicates `whisper.gate()`**.

**Inventory delta computation**
- `scripts/invdiff.py:21 agg(items)`, `50 compare(cur, prev, prices, cap)`, `71 totals(a, prices)`.
- Per-(slug,lane) baseline + drop test: `scripts/trader/detector.py:182 inventory_counts`, `240 inventory_snapshot`, `251 inventory_drop(prev, cur, slug, lane, qty) -> (ok, detail)`.
- Per-item count history: `scripts/item_history.py` (`data/item_history.json`, points + `sales`).
- `scripts/progress.py:463 count_items_gained(items_doc, a, b)`.

**Platinum delta computation**
- `server.py:129 plat_history_payload()` → `{points, now, d24, d7}`.
- `scripts/progress.py:407 step_walk(points, field)` / `428 value_before(timeline, ts)` → step attribution to a local day.
- `scripts/plat_ledger.py:117 norm_points`, `156 balance_anchors(readings, tz)`, `175 window_trades(events, lo, hi)`, `191 window_rows(...)`, `218 check_reconciliation(...)`.
- `scripts/session_stats.py:41 session(...)` → `plat_from/plat_to/plat_delta`.
- `scripts/trader/detector.py:295 classify(prev, cur, plat_delta, self_orders)` uses the same plat-delta idea against the live order snapshot.

**Trade logging**
- `scripts/log_trade.py:13 main(argv)` — CLI `kind name qty plat [total] [note]`, builds `{ts,kind,name,qty,plat,total,note}`.
- `scripts/import_aleca_stats.py:104` — idempotent by `src` (`af:<iso>:<item>`) / `ts`.
- `server.py:1102-1115` — POST body accepted verbatim for kinds `sale|purchase|listing|unlist|reprice|note`.
- (private) `scripts/trader/detector.py:546 cycle` → `626-628` appends confirmed sales with `order_id/signals/evidence`.

**Session bookkeeping**
- `scripts/session_stats.py:31 clusters(marks, gap)` / `41 session(win, events, points, prices)` / `89 main` — derives windows from trade+plat timestamps; nothing is stored.
- `scripts/progress.py:510 build_sessions(wins, events, points, items_doc, now, gap_s)` and `170 read_gap(data_dir)` (single source for the gap: `session_stats.json.gap_min`, fallback 45).
- `server.py:821 SYNC_STEPS` (`refresh.py`, `invdiff.py`, `progress.py --once`), `857 sync_tick`, `1004 autosync_loop`.

## 4. Duplication to avoid

### 4.1 There are TWO order-book clients, and the private one is used by the run queue
`scripts/orders.py:156 fetch_book` (slug, 6 s budget, 45 s cache, retries) vs
`scripts/trader/lister.py:80 fetch_book(item_id)` (raw `urlopen`, 40 s timeout, **no cache, no retries**),
imported by `scripts/trader/runqueue.py:29`. Consequence: Home's buyer line (`run_queue.json`,
written by the slower client) and Trade > Orders (`/api/orders`, fast client) can disagree on price,
rank lane and who is online. Spec §2 forbids exactly this. Both must resolve through `orders.snapshot`.

### 4.2 Buyer/status ranking is implemented twice
`scripts/trader/runqueue.py:76 buyers_for(book, lane, my_price, my_name)` (filters `plat >= my price`,
lane match, excludes self; sorts ingame→online→offline, then price desc, then rep) and
`scripts/orders.py:282 book` / `50 STATUS_RANK` (sorts price first, status only breaks ties, `book()`'s
`key()` at 306-310). Two different orderings mean "best buyer" on Home ≠ top row in Trade > Orders.

### 4.3 Rank-lane pricing is derived in three places
`scripts/report.py:66 lane_price` (authoritative), `server.py:89-101 items_payload` (reads
`price_lanes.json` + `mod_cards.json.owned_rank` directly), `server.py:692-699 rank_values_payload`
(prefers live `orders.values`, falls back to `price_lanes.json`). The independent
endpoint can serve a *different* lane for the same slug/rank than `/api/items`.

### 4.4 "Safe to sell" is computed twice and they disagree
`report.py:96 build_rows` → `sellable_count = count - in_use_count` vs
`sell_advisor.py:219 advise` → `sellable = spares - reserved` (keeper / collection / craft / set
reservations). The session screen must pick one and say which; `/api/items` exposes neither
(it serves raw `count`).

### 4.5 Platinum delta, four ways
`server.py:129 plat_history_payload` (d24/d7), `progress.py:407 step_walk` + `428 value_before`,
`session_stats.py:41 session` (per-window), `plat_ledger.py:191 window_rows` (per-anchor-day).
A "platinum before/after one trade" number must be defined once (recommended: the `step_walk`
attribution, since it already assigns a step to the local day of the point that first shows it).

### 4.6 Trade-log append, four writers, none atomic, none with an ID
`server.py:1102-1115` (read-modify-write, no tmp), `scripts/log_trade.py:30-33` (same),
`scripts/import_aleca_stats.py:104` (same), private `scripts/trader/detector.py:626-628`
(read-modify-write via `jdump`, still no lock). Any two concurrent appends lose a record.
All four must funnel through one `append_trade(event)` that assigns the stable ID.

### 4.7 Inventory-delta detection exists privately, and it auto-confirms
`scripts/trader/detector.py:546 cycle` already joins **orders + plat delta + inventory delta**
(`classify` 295 → `sale_signals` 350 → `all_signals_ok` 365 → `split_sales` 371) and writes
confirmed sales straight into `trade_log.json` — the opposite of spec §4/§11 ("never infer a
completed trade without asking"). It is also gitignored, so CI cannot see it. The reconciliation
engine must be one engine: reuse `inventory_drop`/`classify` semantics (3 signals, weak = evidence)
but surface the result as a *proposal*, never a write.

### 4.8 Rate limiting is layered twice on whispers
`whisper.gate()` (`whisper.py:648`, 2 s / 10 per minute, fake-clock testable) and the server's
own `_whisper_last`/`_whisper_minute` (`server.py:704-810`). Two counters mean a refusal reason can
change shape depending on the path (Orders tab vs any new session button).

### 4.9 Home "next action" is assembled in the browser
`static/app.js:252-352` merges plan + advisor + run queue client-side. A session engine computing
the same queue server-side would be a second source of truth unless Home is switched onto it.

## 5. Data safety

**How JSON gets written today**
- Atomic (tmp + `os.replace`): `config.py:283`, `plat_ledger.py:84`, `sell_advisor.py:482`,
  `progress.py:90`, `player.py:341`, `whisper.py:687`, `watch_save.py:75`, `orders.py:102`,
  `trader/detector.py:76`, `trader/runqueue.py`, `server.py:888` (sync log), `server.py:982` (chat),
  `server.py:1209` (kill switch).
- **Not atomic:** `trade_log.json` — `server.py:1112` (`json.dump(hist, open(path,'w'))`),
  `scripts/log_trade.py:33`, `scripts/import_aleca_stats.py:104`; `session_stats.json`
  (`session_stats.py:129`), `invdiff.json` (`invdiff.py:130`), `plat_history.json`
  (`snapshot_plat.py:33`), `report.json`/`report.md` (`report.py:210/234`), `gamenews.json`
  (`server.py:534`), `prices.json` (`fetch_prices.py:59/65`).
- **Backup on failure:** only `whisper.py:698 load()` (a corrupt ledger is moved to
  `.corrupt-<stamp>` before a fresh one starts) and `config.py:306 _refuse_if_corrupt`. Everything
  else treats a corrupt file as "empty" and will overwrite it on the next write — including
  `trade_log.json`, which is exactly the file spec §11 says must never be lost.
- Scheduled safety net: `scripts/backup.py` zips `data/*.json` to `data/backups/`, keeps 12
  (invoked by `profiles.py:489 pre_switch_backup`, not by the server).
- Profile isolation: `scripts/profiles.py:74-165 MANIFEST` is the contract for account-scoped files
  (`trade_log.json`, `plat_history.json`, `session_stats.json`, `invdiff.json`,
  `inventory_snapshots/`, `run_queue.json`, …). A new session/pending store **must be added to
  MANIFEST** or it will silently leak across accounts on `profiles.py --switch --apply`.

**Where a trade record is created now** (four places, see §4.6):
1. `POST /api/trades` — `server.py:1102-1115`; body validated only for `kind`; `ts` defaulted;
   no ID, no idempotency, no inventory/platinum/session update (the caller must do those separately).
2. `scripts/log_trade.py:13` — CLI, computes `total = qty * plat`.
3. `scripts/import_aleca_stats.py:104` — bulk import, idempotent by `src`/`ts`.
4. `scripts/trader/detector.py:626-628` — automatic, no user confirmation.

`data/trade_log.json` today: 471 events, keys `{ts,kind,name,qty,plat,total,note,src}`; **0 events
carry `id` or `order_id`**, so no existing record can be referenced idempotently.

## 6. Gaps for the loop

RECOMMEND → FIND BUYER → WHISPER → trade in Warframe → DETECT change → ASK USER → LOG → UPDATE → next.

1. **One atomic trade-log writer with stable IDs.** No `append_trade()`; four non-atomic writers
   (§4.6) and no `id` on 471/471 events. Spec §5/§11 need an ID + idempotency before anything else.
2. **Pending/contact state does not exist.** `whisper_post` (`server.py:743`) returns
   `{ok,message,line,copied,sent,reason}` and stores only a ledger row in `whisper_log.json`; it does
   not record slug/rank/qty/expected plat/buyer/inventory-before/plat-before, and no route exposes
   `whisper.log_last`. Spec §3 (READY/CONTACTED/POSSIBLE MATCH/COMPLETED/SKIPPED/HELD) has no store.
3. **No persisted live session.** `session_stats.json` is a recomputed historical roll-up
   (`session_stats.py:89-129`) and `progress.json.today.sessions` is derived too. There is nothing to
   resume after a refresh or a server restart, and no queue is persisted (the closest artefact,
   `run_queue.json`, is rewritten wholesale by `trader/runqueue.py`).
4. **No "before" snapshot tied to a contact.** `whisper.send` does not read inventory/platinum, and
   `whisper_post` does not either — the two numbers spec §3 wants do not exist at contact time.
   `invdiff.py` works at day granularity and `item_history.json` has no per-contact anchor.
5. **No reconciliation endpoint or engine in the public tree.** The only 3-signal implementation is
   gitignored (`trader/detector.py:295-377`) and it auto-writes the trade; there is no "propose
   trade from delta" API and no ambiguous-evidence payload shape (spec §4 "present the evidence").
6. **No confirm-transaction path.** Nothing updates trade log + plat ledger + session totals +
   queue + inventory-derived state together; `POST /api/trades` updates only the log, and
   `report.json` / `sell_advisor.json` / `invdiff.json` / `progress.json` are only refreshed when a
   pipeline step runs (`SYNC_STEPS`, `server.py:821`).
7. **Home / Trade > Orders / session have no shared buyer source.** Two order clients (§4.1) and two
   buyer rankings (§4.2); "best live buyer" is decided in `app.js` from `run_queue.json`, which the
   Session screen would have to duplicate.
8. **No queue/next-item server state.** Session advance ("move to the next best trade") has nothing
   to advance over; Home's queue is `trader_plan.json.plan` order (first row wins, `app.js:294`).
9. **Read-only routes are not clean.** `/api/gamenews` writes (and fetches) on GET
   (`server.py:533-537`); `/api/orders` and `/api/rank_values` write the order cache. Spec §13's
   "no mutation from read-only routes" test needs these three explicitly excluded or fixed.
10. **Profile scoping.** The MANIFEST (`profiles.py:74-165`) must gain the new session/pending file,
    or switching accounts carries trade state across accounts.
11. **CI has no browser/UI gate.** `.github/workflows/tests.yml` runs `python -m pytest tests -q`
    only (and asserts no `data/` in the checkout). The headless QA harnesses exist
    (`design/_stage2/qa_ia.js`, `_stage8`, `_stage9`) but nothing in CI runs them; spec §13/§14 want
    `#trade/session` covered. Also: no `design/_session/` directory existed before this audit.
12. **Trader engines are untracked.** `scripts/trader/` is in `.gitignore`; `git ls-files scripts/trader`
    is empty, and the CI comment says the private engines are never imported. Any new public code must
    not import `trader/*` (a test on a fresh checkout would fail), which rules out reusing
    `runqueue.buyers_for`, `lister.fetch_book`, `limits.read_live` and `detector.*` as-is.

## 7. Not verified / assumptions

- **UNVERIFIED (runtime):** I did not start the server, so route behaviour was read from source
  only; "GET mutates" is a source-level claim (the write sites are cited).
- **UNVERIFIED:** whether `orders_cache` writes on GET are considered acceptable by the intended
  "read-only" test definition.
- **UNVERIFIED:** real WFM API responses/shape drift (`orders.py` fixtures were not run against the
  network); no live whisper was attempted.
- **UNVERIFIED:** the exact contents of `design/_stage*/qa_*.js` gates (referenced in
  `docs/navigation.md:93-96`, not read here) — only that CI does not run them.
- Static-path guard at `server.py:1032-1033` uses `startswith(STATIC)` on a normalised path, which
  would also accept a sibling directory whose name begins with `static`. Loopback-only server, low
  impact; noted, not exploited.
