# WFM Trader — Trading Session WORKFLOW gate

**Run:** 2026-09-29 11:14:26 +1000  
**Drives:** `Whisper → CONTACTED → reconcile check → Confirm`, through the real UI at http://127.0.0.1:54876  
**Server:** `server.py` on the throwaway data dir `C:\Users\jayde\AppData\Local\Temp\wfm-workflow-gate-26gb6q5h\data` (never the repo's real `data/`)  
**Driver:** `design/_session/workflow_gate.js` (puppeteer-core F:/VSC Projects/pb-bench/node_modules/puppeteer-core, node v24.13.0)  
**Repo revision at run time:** `469392b`, working tree dirty: M design/_session/report.md; M scripts/trade_session.py; M tests/test_session_api.py; M tests/test_trade_reconcile.py; ?? design/_session/review-round-2.md; ?? design/_session/workflow-report.md; ?? design/_session/workflow_gate.js; ?? design/_session/workflow_gate.py  

## Verdict

**PASS — 22 of 22 workflow checks passed**.

## What it drove, and what it saw

The fixture (written into the throwaway dir by this launcher, and nothing else is in it):

| fact | value |
|---|---|
| queue item | `primed_continuity` (rank 0) |
| stack and price the loop lists | 3 copies at 48p (plan `per_trade`/`price`) |
| buyer the run queue names | `GateBuyer` (buy_price 48p) |
| stack before the sale (report.json) | 4 |
| stack after the sale (report.json) | 1 |
| platinum before → after | 1220 → 1364 (+144 = 3 × 48p) |
| account the payload must name | `GateAccount` (proof the server read the throwaway dir) |

| step | checks | failed |
|---|---|---|
| load | 3 | 0 |
| start | 2 | 0 |
| whisper | 4 | 0 |
| reconcile | 4 | 0 |
| confirm | 7 | 0 |
| hygiene | 2 | 0 |

### Every check, expected vs observed

Workflow checks (these decide the verdict) come first; labelled DIAGNOSTIC rows (see the section after) never decide it.

| step | check | kind | ok | expected | observed |
|---|---|---|---|---|---|
| load | the Session panel renders and paints from GET /api/session | workflow | yes | panel open, Start visible, the panel painted a state | panel_open=true start_hidden=false focus="No session open yet." |
| load | no console errors on the Session surface | workflow | yes | 0 console errors while the panel loaded | 0 console error(s) at load, 0 transient net-stack row(s) |
| load | no failed request outside the documented blocked-CDN class | workflow | yes | 0 failed requests | 0 failed (0 blocked-CDN excluded) |
| start | Start opened a real session with a queue | workflow | yes | a session with at least one queue row | session=s-20260929-1114-3538 queue_rows=1 (dom rows 1) |
| start | the focus card is on the seeded item and offers a buyer to whisper | workflow | yes | one buyer row with one Whisper button on the focus item | buyer="GateBuyer" whisper_btns=1 focus="Primed Continuity R0 3 copies 48p list lowest sell 70p highest buy 45p high ready Why this trade? Open live orders Mark " |
| whisper | the app reports the whisper as SENT (not merely copied) | workflow | yes | the row says "Sent to game" | row answer: "Sent to game" |
| whisper | the sent whisper opened a CONTACTED pending trade | workflow | yes | state=CONTACTED with an id | state=CONTACTED id=p-1790644468000-d815c0 slug=primed_continuity |
| whisper | the contact snapshotted the stack and the platinum it went out at | workflow | yes | copies=4 plat=1220 asked=48p x3 | copies=4 plat=1220 asked=48p x3 basis= buyer=GateBuyer |
| whisper | the pending trade is on screen (Waiting on a confirmation) | workflow | yes | at least one pending row | 1 row(s): "0s ago Primed Continuity R0 GateBuyer 3 @ 48p" |
| reconcile | the simulated game save landed in the throwaway data dir | workflow | yes | report sellable_count=1, plat=1364 | report=1 plat=1364 |
| reconcile | the check is an EXACT match on copies left and platinum arrived | workflow | yes | verdict=exact copies_left=3 platinum=+144 | verdict=exact copies_left=3 platinum=+144 asked=144 evidence=["copies left: 3","platinum: +144","asked: 144"] |
| reconcile | the check reached the screen and offers the Confirm click | workflow | yes | a check row with a Confirm button, from the panel the user is looking at | app-cadence (no interaction: the check rode the app's own refresh); rows=1 buttons=["Confirm"] card="sold Primed Continuity R0 GateBuyer 3 @ 48p each copies left: 3 platinum: +144 asked: 144 Confirm" |
| reconcile | the check writes nothing on its own (a proposal, never a trade) | workflow | yes | no trade_log.json before the Confirm click | trade_log.json absent |
| confirm | one trade was written to trade_log.json | workflow | yes | exactly one record for primed_continuity with an id | records=1 id=t-1790644468000-2976aa slug=primed_continuity qty=3 plat=48 total=144 source=session |
| confirm | the money recorded for the trade is what the check asked for | workflow | yes | total=144p (3 x 48p, the "asked: 144" the check showed) | total=144p |
| confirm | the record's plat is the price per copy, the shape confirm() documents | workflow | yes | plat=48p (the per-copy price the row showed: "3 @ 48p each") | plat=48p |
| confirm | the session credited exactly the money the trade paid | workflow | yes | earned_plat=144p (3 x 48p) | earned_plat=144p |
| confirm | the session counted the trade and closed the pending row | workflow | yes | summary.trades=1 and no pending trade left | trades=1 earned=144 pending=0 |
| confirm | the store shows the queue row and the pending row completed | workflow | yes | queue row COMPLETED, pending COMPLETED, the trade id in confirmed[] | queue=COMPLETED pending=COMPLETED confirmed=["t-1790644468000-2976aa"] |
| confirm | the screen shows one trade and no check left to confirm | workflow | yes | the meta line reads 1 trade; the Checks card offers nothing | meta="· 1 TRADE · 0 LEFT · STARTED 31S AGO" confirm_btns=[] focus="Session complete 1 trade +144pp earned 1m +144pp average highest sale Primed Continuity +144pp" |
| hygiene | every connection-level failure clears on a direct recheck | workflow | yes | each refused URL answers when asked again from node | 0 refusal(s), 0 cleared: [] |
| hygiene | no console error or failed request outside that class, over the whole drive | workflow | yes | 0 console errors, 0 failed requests | 0 console error(s), 0 failed request(s) |

Notes the driver attached to specific checks:

- **the app reports the whisper as SENT (not merely copied)** — ordWhisper prints "Sent to game" only for a response with sent=true
- **the check reached the screen and offers the Confirm click** — the server computed the proposal correctly either way (the check above), so this is about the panel showing it, not about the reconcile logic
- **the record's plat is the price per copy, the shape confirm() documents** — the draft propose() offers (trade_draft(plat=expected_plat x qty)) carries the sum in `plat`, and confirm() then multiplies it again into `total`; the comment above confirm() says "`plat` is the price per copy and `total` is the money for the trade ... one with `plat` holding the sum double counted 
- **every connection-level failure clears on a direct recheck** — the same rule design/_stage10/gate.js uses: a burst refused by the dev server is not a release failure, and saying so requires the recheck

## Evidence, read back

Each block is what the driver actually read — DOM text the panel painted, the app's own HTTP answers (fetched through the page, same origin), and the store files on disk.

### load

```json
{
 "meta": "",
 "focus": "No session open yet.",
 "queue": "Nothing to sell yet.",
 "pending": "Nothing waiting on a confirmation.",
 "checks": "Nothing to check yet.",
 "checks_meta": "",
 "pending_meta": "",
 "kpis": "",
 "start_hidden": false,
 "buyer_user": null,
 "whisper_btns": 0,
 "whisper_say": null,
 "pending_rows": 0,
 "check_rows": [],
 "confirm_btns": [],
 "queue_rows": 0,
 "panel_open": true,
 "hash": "#trade/session"
}
```

### start

```json
{
 "dom": {
  "meta": "\u00b7 0 TRADES \u00b7 1 LEFT \u00b7 STARTED 1S AGO",
  "focus": "Primed Continuity R0 3 copies 48p list lowest sell 70p highest buy 45p high ready Why this trade? Open live orders Mark sold GateBuyer 48p ingame Whisper",
  "queue": "ready Primed Continuity R0 3 x 48p Focus",
  "pending": "Nothing waiting on a confirmation.",
  "checks": "Nothing to check yet.",
  "checks_meta": "",
  "pending_meta": "",
  "kpis": "EARNED 0p TRADES 0 LEFT TODAY 6 QUEUE 1/1",
  "start_hidden": true,
  "buyer_user": "GateBuyer",
  "whisper_btns": 1,
  "whisper_say": "",
  "pending_rows": 0,
  "check_rows": [],
  "confirm_btns": [],
  "queue_rows": 1,
  "panel_open": true,
  "hash": "#trade/session"
 },
 "session": {
  "id": "s-20260929-1114-3538",
  "started_ts": 1790644467,
  "ended_ts": null,
  "account": "GateAccount",
  "cursor": 0,
  "plat_start": 1220,
  "queue": [
   {
    "slug": "primed_continuity",
    "name": "Primed Continuity",
    "rank": 0,
    "qty": 3,
    "price": 48,
    "cat": "mod",
    "buyer": {
     "user": "GateBuyer",
     "status": "ingame",
     "qty": 3,
     "plat": 48,
     "my_price": 48,
     "why": "seeded by workflow_gate.py",
     "summary": {
      "ingame": 1,
      "online": 0,
      "total": 1
     }
    },
    "why": {
     "safe_copies": 4,
     "sales_48h": 110,
     "buyers_online": 1,
     "buy_orders": 5,
     "lowest_sell": 70,
     "highest_buy": 45,
     "buyer_pays": 48,
     "rank_unverified": "queue row names no rank for this buyer"
    },
    "confidence": {
     "level": "high",
     "reasons": [
      "1 buyer live",
      "110 sales in 48h",
      "5 buy orders"
     ]
    },
    "source": "plan",
    "state": "READY",
    "added_ts": 1790644467
   }
  ],
  "done": [],
  "totals": {
   "trades": 0,
   "earned_plat": 0,
   "skipped": 0,
   "held": 0
  }
 },
 "queue": [
  {
   "slug": "primed_continuity",
   "rank": 0,
   "qty": 3,
   "price": 48,
   "state": "READY",
   "buyer": "GateBuyer"
  }
 ]
}
```

### whisper

```json
{
 "dom_whisper_say": "Sent to game",
 "dom_whisper_response": {
  "status": 200,
  "body": {
   "ok": true,
   "message": "Hi! I want to buy: \"primed_continuity (rank 0)\" for 48 platinum. (warframe.market)",
   "line": "/w GateBuyer Hi! I want to buy: \"primed_continuity (rank 0)\" for 48 platinum. (warframe.market)",
   "copied": true,
   "sent": true,
   "reason": "",
   "contact": {
    "id": "p-1790644468000-d815c0",
    "session_id": "s-20260929-1114-3538",
    "slug": "primed_continuity",
    "name": "Primed Continuity",
    "rank": 0,
    "qty": 3,
    "expected_plat": 48,
    "buyer": "GateBuyer",
    "kind": "buy",
    "ts": 1790644468,
    "state": "CONTACTED",
    "inv_before": 4,
    "plat_before": 1220,
    "inv_basis": null,
    "note": ""
   }
  }
 },
 "pending": [
  {
   "id": "p-1790644468000-d815c0",
   "session_id": "s-20260929-1114-3538",
   "slug": "primed_continuity",
   "name": "Primed Continuity",
   "rank": 0,
   "qty": 3,
   "expected_plat": 48,
   "buyer": "GateBuyer",
   "kind": "buy",
   "ts": 1790644468,
   "state": "CONTACTED",
   "inv_before": 4,
   "plat_before": 1220,
   "inv_basis": null,
   "note": ""
  }
 ],
 "queue_row_state": "READY",
 "session_after": {
  "id": "s-20260929-1114-3538",
  "started_ts": 1790644467,
  "ended_ts": null,
  "account": "GateAccount",
  "cursor": 0,
  "plat_start": 1220,
  "queue": [
   {
    "slug": "primed_continuity",
    "name": "Primed Continuity",
    "rank": 0,
    "qty": 3,
    "price": 48,
    "cat": "mod",
    "buyer": {
     "user": "GateBuyer",
     "status": "ingame",
     "qty": 3,
     "plat": 48,
     "my_price": 48,
     "why": "seeded by workflow_gate.py",
     "summary": {
      "ingame": 1,
      "online": 0,
      "total": 1
     }
    },
    "why": {
     "safe_copies": 4,
     "sales_48h": 110,
     "buyers_online": 1,
     "buy_orders": 5,
     "lowest_sell": 70,
     "highest_buy": 45,
     "buyer_pays": 48,
     "rank_unverified": "queue row names no rank for this buyer"
    },
    "confidence": {
     "level": "high",
     "reasons": [
      "1 buyer live",
      "110 sales in 48h",
      "5 buy orders"
     ]
    },
    "source": "plan",
    "state": "CONTACTED",
    "added_ts": 1790644467,
    "contacted_ts": 1790644468
   }
  ],
  "done": [],
  "totals": {
   "trades": 0,
   "earned_plat": 0,
   "skipped": 0,
   "held": 0
  }
 }
}
```

### reconcile

```json
{
 "save_written": {
  "report": {
   "sell_now": [
    {
     "slug": "primed_continuity",
     "name": "Primed Continuity",
     "cat": "mod",
     "lane_rank": 0,
     "sellable_count": 1,
     "wts": 70,
     "wtb": 45,
     "n_buy": 5,
     "vol48": 110,
     "lane_ask": 60
    }
   ]
  },
  "plat_history": [
   {
    "ts": 1790640868,
    "plat": 1220
   },
   {
    "ts": 1790644468,
    "plat": 1364
   }
  ]
 },
 "pending_before": {
  "id": "p-1790644468000-d815c0",
  "session_id": "s-20260929-1114-3538",
  "slug": "primed_continuity",
  "name": "Primed Continuity",
  "rank": 0,
  "qty": 3,
  "expected_plat": 48,
  "buyer": "GateBuyer",
  "kind": "buy",
  "ts": 1790644468,
  "state": "CONTACTED",
  "inv_before": 4,
  "plat_before": 1220,
  "inv_basis": null,
  "note": ""
 },
 "expected_delta": 144,
 "dom": {
  "checks": "sold Primed Continuity R0 GateBuyer 3 @ 48p each copies left: 3 platinum: +144 asked: 144 Confirm",
  "checks_meta": "\u00b7 1 TO CONFIRM",
  "check_rows": [
   "sold Primed Continuity R0 GateBuyer 3 @ 48p each copies left: 3 platinum: +144 asked: 144 Confirm"
  ],
  "confirm_btns": [
   "Confirm"
  ],
  "meta": "\u00b7 0 TRADES \u00b7 1 LEFT \u00b7 STARTED 30S AGO"
 },
 "proposal": {
  "verdict": "exact",
  "pending_id": "p-1790644468000-d815c0",
  "slug": "primed_continuity",
  "name": "Primed Continuity",
  "rank": 0,
  "qty": 3,
  "buyer": "GateBuyer",
  "age_s": 30,
  "expected_plat": 48,
  "total_plat": 144,
  "inv_before": 4,
  "inv_now": 1,
  "plat_before": 1220,
  "plat_now": 1364,
  "copies_left": 3,
  "plat_delta": 144,
  "evidence": [
   "copies left: 3",
   "platinum: +144",
   "asked: 144"
  ],
  "stale": false,
  "trade": {
   "kind": "sale",
   "slug": "primed_continuity",
   "item": "primed_continuity",
   "name": "Primed Continuity",
   "rank": 0,
   "qty": 3,
   "plat": 48,
   "total": 144,
   "user": "GateBuyer",
   "buyer": "GateBuyer",
   "source": "session",
   "session_id": "s-20260929-1114-3538",
   "pending_id": "p-1790644468000-d815c0",
   "ts": 1790644468,
   "id": "t-1790644468000-2976aa"
  }
 },
 "refresh_mode": "app-cadence (no interaction: the check rode the app's own refresh)",
 "panel_probe": {
  "feat_session_proposals": 1,
  "session_payload_proposals": 1,
  "session_payload_source": "static/session.js sessionPayload()",
  "checks_card_text": "sold\nPrimed Continuity R0\nGateBuyer\n3 @ 48p each\ncopies left: 3\nplatinum: +144\nasked: 144\nConfirm",
  "checks_meta_text": "\u00b7 1 TO CONFIRM"
 }
}
```

### confirm

```json
{
 "diagnostic": false,
 "dom": {
  "meta": "\u00b7 1 TRADE \u00b7 0 LEFT \u00b7 STARTED 31S AGO",
  "kpis": "EARNED +144p TRADES 1 LEFT TODAY 6 QUEUE 0/1",
  "focus": "Session complete 1 trade +144pp earned 1m +144pp average highest sale Primed Continuity +144pp",
  "checks": "Nothing to check yet.",
  "confirm_btns": []
 },
 "summary": {
  "id": "s-20260929-1114-3538",
  "active": true,
  "started_ts": 1790644467,
  "ended_ts": null,
  "seconds": 31,
  "trades": 1,
  "earned_plat": 144,
  "average_plat": 144,
  "skipped": 0,
  "held": 0,
  "queue_total": 1,
  "queue_remaining": 0,
  "completed_rows": 1,
  "plat_start": 1220,
  "best": {
   "id": "t-1790644468000-2976aa",
   "slug": "primed_continuity",
   "name": "Primed Continuity",
   "rank": 0,
   "qty": 3,
   "plat": 144,
   "buyer": "GateBuyer",
   "ts": 1790644498
  },
  "trades_left_today": 6,
  "trade_cap": 20,
  "plat_now": 1364,
  "complete": true
 },
 "trade_log": [
  {
   "kind": "sale",
   "slug": "primed_continuity",
   "item": "primed_continuity",
   "name": "Primed Continuity",
   "rank": 0,
   "qty": 3,
   "plat": 48,
   "total": 144,
   "user": "GateBuyer",
   "buyer": "GateBuyer",
   "source": "session",
   "session_id": "s-20260929-1114-3538",
   "pending_id": "p-1790644468000-d815c0",
   "ts": 1790644468,
   "id": "t-1790644468000-2976aa",
   "src": "session",
   "confirmed_ts": 1790644498
  }
 ],
 "store_queue_row_state": "COMPLETED",
 "store_pending_state": "COMPLETED",
 "store_confirmed": [
  "t-1790644468000-2976aa"
 ]
}
```

### Other things the drive showed (not part of the verdict)

Smaller inconsistencies the same run happened to produce. They are recorded because the drive saw them, and they are not asserted anywhere.

- **the exact line the session's buyer row whispered (kind "buy", the same kind the Orders tab sends for a buy-book row)**
  - where: scripts/whisper.py message() verbs, driven through ordWhisper; the gate does not judge the wording, it records it
  - saw: `/w GateBuyer Hi! I want to buy: "primed_continuity (rank 0)" for 48 platinum. (warframe.market)`
- **the end-of-session card prints a doubled platinum unit ("+432pp earned", "+432pp average")**
  - where: static/session.js sessionEndCard(): sessionPlat() already appends "p" and the card appends "p earned"
  - saw: `Session complete 1 trade +144pp earned 1m +144pp average highest sale Primed Continuity +144pp`
- **the session's done[] entry and the trade_log record use the same "plat" key for different things**
  - where: session done[0].plat=144 (the money for the trade) vs trade_log[0].plat=48 (the price per copy, with the money in trade_log[0].total=144)
  - saw: `same sale, one key, two readings - the session summary reads done[], anything summing the log reads total`

### Connection-level failures (the documented net-stack class, rechecked)

Chromium refusing a burst is not an application failure. The rule is the release gate's (`design/_stage10/gate.js`): a request only counts against the app if it failed in Chromium **and** still fails (or answers 4xx/5xx) when asked again from node. The rows are reported either way.

None: no request failed at the connection level during this run.

Blocked-CDN requests excluded (missing card/warframe art, counted, never hidden): 0

## Harness facts

| fact | value |
|---|---|
| server booted against the throwaway data dir | yes |
| whisper transport | stubbed (GATE_WHISPER=stubbed) |
| the queue the server BUILT from the throwaway payloads | primed_continuity |
| the session the driver started names the fixture account | `GateAccount` (plat_start=1220) |
| the CONTACTED snapshot the server took | id=p-1790644468000-d815c0 state=CONTACTED copies=4 plat=1220 asked=48p x3 |
| the trade the Confirm click wrote | {"kind": "sale", "slug": "primed_continuity", "item": "primed_continuity", "name": "Primed Continuity", "rank": 0, "qty": 3, "plat": 48, "total": 144, "user": "GateBuyer", "buyer": "GateBuyer", "source": "session", "sess |

Gate server stdout (the boot script proving which data dir it used):

```
GATE_DATA=C:\Users\jayde\AppData\Local\Temp\wfm-workflow-gate-26gb6q5h\data
GATE_ROOT=F:\VSC Projects\wfm-dashboard
GATE_WHISPER=stubbed
gate server on http://127.0.0.1:54876/
```

The repo's REAL `data/` files, before → after (informational only: the developer's own supervised app may write them at any time, so no claim is made from this):

| file | before | after | verdict |
|---|---|---|---|
| trade_session.json | absent | absent | same |
| trade_log.json | 132901 bytes @1790339727 | 132901 bytes @1790339727 | same |
| whisper_log.json | 2717 bytes @1790599272 | 2717 bytes @1790599272 | same |
| report.json | 103419 bytes @1790354374 | 103419 bytes @1790354374 | same |
| plat_history.json | 12790 bytes @1790642652 | 12790 bytes @1790642652 | same |
| trader_limits.json | 530 bytes @1790345450 | 530 bytes @1790345450 | same |
| sync_log.json | 3853 bytes @1790644347 | 3853 bytes @1790644347 | same |

## What this gate does NOT prove

- **The whisper transport.** `scripts/whisper.py` types the line into a running Warframe window. There is no game window in a gate run, and a gate must never send a real whisper to a real player, so the gate server replaces ONLY `whisper.send()` with a stub that reports `(True, R_SENT)`. The message/line/copy build, the `POST /api/whisper` route, the `sent → contact()` branch and everything after it are the real code, but the last centimetre — keystrokes into the game — is not exercised here.
- **The game's side of reconciliation.** The change a sale makes (one stack shorter, platinum higher) is written by the driver straight into the throwaway `report.json` / `plat_history.json` that `scripts/report.py` and `scripts/snapshot_plat.py` would normally write. The snapshot at contact, `propose()`, the check's evidence and the confirm are the real code.
- **The post-confirm pipeline.** The confirmation's background sync kick (`scripts/refresh.py` + `invdiff.py` + `progress.py`) is stubbed to a no-op: those scripts do not read `WFM_DATA` and would rewrite the developer's real `data/`. The confirmation transaction itself (trade_log entry, session totals, queue/pending state, cursor) is what is measured here, and it is unaffected. `tests/test_session_api.py` stubs the same function.
- **The auto-sync thread.** It is started the way the real server starts it, but `data/config.json` says `auto_refresh_seconds: 0`, so the server-side pipeline never runs during a gate run.
- **Nothing about the network.** The session loop takes no network path; the gate does not test warframe.market, prices or the order book.

---

Re-run, one command:

```
python design/_session/workflow_gate.py
```

It makes its own throwaway data dir, boots the dashboard against it on a free port, drives the browser, tears the server down and rewrites this file. `--keep` leaves the throwaway dir (and the driver's raw JSON) on disk for inspection.
