# Trading Session — implementation map

Stage 1 deliverable for [`docs/trading-session-workflow.md`](../../docs/trading-session-workflow.md).
Written after a three-way read-only audit of the repo at `9718084` (plus the doc commit). The three
audit notes live beside this file:

- [`audit-backend.md`](audit-backend.md) — routes, datasets, helpers, duplication, data safety
- [`audit-frontend.md`](audit-frontend.md) — router, renderers, whisper wiring, ids/copy rules
- [`audit-tests-qa.md`](audit-tests-qa.md) — test patterns, gate harness, CI, §13 coverage map

The doc is the source of truth for *what* to build. This file is the map of *where* it goes, and it
records the reconciliation decisions where the repo has moved on since the doc was written.

## 1. Existing source of truth (reuse, do not duplicate)

| Dataset | Owner today | Served as |
|---|---|---|
| Sell recommendations | `scripts/sell_advisor.py:219 advise` over `scripts/report.py:96 build_rows` | `/api/report`, `/api/feature/advisor` |
| Next action / sell queue | **front end only** — `static/app.js:252-352` over `trader_plan.json` + advisor + `run_queue.json` | composed client-side |
| Live order book | `scripts/orders.py:167 snapshot` → `282 book`, 45 s cache | `/api/orders` |
| Rank ladder / rank values | `scripts/fetch_lanes.py:52 lane_summary`, re-exported `orders.py:317 values` | `/api/rank_values`, `#ordValues` |
| Owned ranks | `scripts/report.py:89 own_ranks_of` | `/api/report` |
| Safe-to-sell counts | `report.build_rows sellable_count` **and** `sell_advisor.advise sellable` (two numbers) | both |
| Inventory deltas | `scripts/invdiff.py:21 agg / 50 compare` (day-granular snapshots) | `/api/feature/invdiff` |
| Platinum balance | readings `data/plat_history.json` + `scripts/plat_ledger.py` ledger | `/api/plat_history`, `/api/feature/ledger` |
| Trade history | `data/trade_log.json` (471 events, **no ids**) — four writers, none atomic | `/api/trades` |
| Sessions (historical) | `scripts/session_stats.py:31/41` clusters `trade_log.json` by 45 min gaps | `/api/feature/sessions` |
| Today metrics | `scripts/progress.py:536 collect` (510 build_sessions, 407 step_walk) | `/api/feature/progress` |
| Whisper send | `scripts/whisper.py:780 send` (cooldown + 10/min, clipboard + Ctrl+V/Enter) | `POST /api/whisper` (`server.py:743`) |
| Whisper ledger | `data/whisper_log.json` (500 rows, atomic) — **no route reads it** | — |
| Buyers | `scripts/trader/runqueue.py:76 buyers_for` (private) → `data/run_queue.json`; also `orders._row:251` | `/api/trader`, `/api/orders` |
| Alerts / undercuts / stale | `trader_undercuts.json`, `hygiene_plan.json`, `nudges.json` | `/api/trader`, features |
| Account/profile scoping | `scripts/profiles.py:74-165 MANIFEST` | `/api/profiles` |

Rules that follow from that table:

- Home, Trade > Orders, the Session screen and item quick-look must all read the **same** order-book
  payload. No second book, no second ranking.
- Recommendations stay wherever they are computed; the session **queues the results**, it does not
  recompute prices.
- The private `scripts/trader/` tree is gitignored: public code may consume its **JSON outputs**
  (`trader_plan.json`, `run_queue.json`, `trader_limits.json`) and must never import it. Anything the
  tests must cover therefore lives in public modules.

## 2. New public module — `scripts/trade_session.py`

One module owns the session, the queue, the pending trades, the reconciliation proposal and the
canonical completion transaction. It is stdlib-only, side-effect free on import, and every function
takes injected payloads so `tests/` can drive it without a `data/` directory.

```
data/trade_session.json                       # gitignored (data/*), added to profiles.py MANIFEST
{
  "version": 1,
  "session": {
    "id": "s-20260929-0815-4f2a",             # stable for the life of the session
    "started_ts": 1790706000, "ended_ts": null, "account": "…",
    "cursor": 0,
    "plat_start": 1220,
    "queue": [ { "slug", "name", "rank", "qty", "price",
                 "buyer": {"user","status","reputation","qty","plat"} | null,
                 "why": {"safe_copies","buyers_online","sales_48h","median","week_pct"},
                 "state": "READY", "added_ts" } ],
    "totals": {"trades": 0, "earned_plat": 0, "skipped": 0, "held": 0},
    "done": []                                 # completed entries, newest first (audit trail)
  },
  "pending": [ { "id": "p-…", "session_id", "slug", "name", "rank", "qty",
                 "expected_plat", "buyer", "ts", "inv_before", "plat_before",
                 "state": "CONTACTED", "note" } ],
  "confirmed": ["t-…"],                        # ids already written, for idempotency
  "updated_ts": 0
}
```

States stay at the six the doc names: `READY`, `CONTACTED`, `POSSIBLE MATCH`, `COMPLETED`,
`SKIPPED`, `HELD`.

Writes are atomic (`tmp` + `os.replace`) and a corrupt file is kept aside, not overwritten.

## 3. Trade records gain a stable id

`trade_log.json` gets an `id` on every new event: `t-<epoch-ms>-<6 hex>` derived from the record
content, so a retry of the same trade produces the same id and the confirm path can refuse to append
twice. Existing 471 events keep working (no id = nothing to collide with); they are never rewritten.
New writer: `trade_session.append_event()` — atomic, id-aware. The three other writers
(`server.py:1112`, `scripts/log_trade.py:33`, `import_aleca_stats.py:104`) delegate to it so there is
one append path.

## 4. Reconciliation (spec §4)

Pure function, no writes:

```
propose(pending, inv_now, plat_now) -> [ { "verdict": "exact"|"ambiguous"|"none",
                                           "pending_id", "trade": {...}, "evidence": [str] } ]
```

- `inv_before` / `plat_before` are captured **when the whisper is sent** — that is the one snapshot
  the repo does not take today.
- exact: inventory fell by ≥ qty and platinum rose by exactly `expected_plat × qty`.
- ambiguous: inventory moved but platinum does not match, or platinum moved with nothing leaving
  inventory. The evidence lines say which, in player language.
- none: nothing changed yet.
- The engine never writes a trade. `trader/detector.py` (private, auto-confirming) is left alone; the
  public path only proposes.

## 5. One canonical confirm transaction (spec §5, §11)

`POST /api/session/confirm` → `trade_session.confirm(...)`: one atomic step that

1. resolves the stable trade id (supplied, or derived) and returns early if it is already in
   `confirmed` → double-click safe,
2. appends the event to `trade_log.json` through the id-aware atomic writer,
3. marks the pending trade `COMPLETED` (or completes a manual one),
4. updates session totals, sales count and `plat_start`-relative earnings,
5. removes/reduces that queue entry and advances the cursor,
6. returns the record; the server then refreshes derived stores (`refresh.py`, `invdiff.py`,
   `progress.py --once`) through the existing `sync_run` in a background thread, so Home Today,
   sessions, inventory and the ledger all follow from one action.

Read-only routes stay read-only: the session GET and the reconcile POST do not touch history. The
existing `GET /api/gamenews` mutation is out of scope for this work and is noted as a known wart.

## 6. Files to change

| File | Change |
|---|---|
| `scripts/trade_session.py` | **new** — session, queue, pending, reconcile, confirm, summary, Why? |
| `server.py` | session routes; `whisper_post` records CONTACTED on a successful send; `POST /api/trades` delegates to the id-aware writer; build-progress payload |
| `static/index.html`, `static/session.js`, `static/session.css` | **new** — `#trade/session` tab + panel; Start Trading on the Next-action card |
| `static/app.js` | router hook for `tp-session`, Start Trading wiring, buyer line reuse, no second book |
| `scripts/profiles.py` | add `trade_session.json` to the MANIFEST so it is account-scoped |
| `.gitignore` | nothing (already `data/*`) |
| `tests/test_trade_session_state.py`, `tests/test_trade_reconcile.py`, `tests/test_trade_confirm.py`, `tests/test_session_api.py` | **new** — the §13 list |
| `design/_stage10/gate.js` | `trade/session` in the route matrix + duplicate-id check |
| `.github/workflows/` | pytest keeps running; a UI gate job only if it can be proven locally first |

## 7. Stage order and what "done" means for each

1. **Stage 1 (this file)** — audits + map committed.
2. **Stage 2** — persisted session + queue, `GET /api/session`, start/end/focus/state routes, tests.
3. **Stage 3** — buyers + whisper → `CONTACTED`, session panel, Start Trading, Home wiring, tests.
4. **Stage 4** — before-snapshots + reconcile engine + `POST /api/session/reconcile`, tests.
5. **Stage 5** — canonical confirm transaction + idempotency + derived-store refresh, tests.
6. **Stage 6** — live session summary + recommendation Why?, tests.
7. **Stage 7** — truthful first-run build states (no invented percentages).
8. **Stage 8** — architecture cleanup only where the landed code justifies it.
9. **Stage 9** — full pytest + browser gate on `#trade/session` + report in `design/_session/report.md`.

Every stage ends with `python -m pytest tests -q` green and its own commit.
