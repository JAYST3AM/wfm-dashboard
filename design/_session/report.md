# Trading Session — implementation report

Source of truth: `docs/trading-session-workflow.md` @ `9718084f50786cec3e73be52a7ead0997f725082`.
This report is the stage-9 deliverable: what shipped, what was decided, what the evidence is, what is
weak, and what is deliberately left for later.

## 1. Commits (each a coherent stage, in order)

| commit | stage | what it is |
|---|---|---|
| `c8628ae` | 1 | `design/_session/implementation-map.md` — what the repo already owns, where the loop plugs in |
| `28facdc` | 2 | `scripts/trade_session.py` (state, queue, lifecycle), `/api/session` + `/api/session/<action>`, `WFM_ROOT`/`WFM_DATA` overrides |
| `91266f2` | 3 | `#trade/session` tab + panel, `static/session.js`/`.css`, Home "Start trading", whisper → contact |
| `8532fd2` | 4+5 | reconciliation (`propose`, never writes) and the one atomic confirm path (`confirm`); `/api/trades` and `log_trade.py` moved onto it |
| `802287c` | 6 | session summary + end-of-session card, the Why? disclosure, the price facts, Home's Whisper buyer, focus-card action set (Open live orders, Mark sold) |
| `5636f48` | 7 | first-run build states (`/api/build`, `static/build.js`) — waiting/running/complete/failed, no invented percentages |
| `4deee12` | 8 | `import_aleca_stats.py` writes atomically and stamps ids like everything else |
| `9228853` | — | the count basis (`inv_of`), found by driving the live store rather than a fixture |
| `d333ae1` | 9 | the release gate run, and the one stale check it caught |

Stages 4 and 5 share one commit because the check is useless without the click that completes it, and
the panel renders both from the same payload — splitting them would have produced an unshippable
intermediate. Everything else is one stage per commit.

## 2. What the loop is now

1. **Plan → queue.** `scripts/trade_session.py build_queue()` ranks the advisor's sell candidates for
   the account: safe-to-sell quantity, live demand, rank correctness, platinum per click. Ranked,
   never guessed.
2. **Start.** Home's Next action or the panel's own Start opens a session in `data/trade_session.json`
   (one writer, atomic, corrupt files quarantined rather than overwritten). A double start returns the
   live session instead of replacing it.
3. **Work one item.** The focus card shows the item, the stack, the list price, the lowest live sell,
   the highest live buy, the buyer (or the honest gap) and a confidence level. Why this trade? is a
   disclosure with one fact per line, and it prints nothing for a fact the payload does not carry.
4. **Whisper.** The whisper goes out through the existing funnel (`server.py whisper_post` →
   `whisper.send`). Only a whisper that actually reached the game opens a CONTACTED pending trade,
   snapshotting the inventory count and platinum it went out at. Copied-but-not-sent is not a contact.
5. **Come back later.** The check rides the `/api/session` payload the panel already fetches — no
   second call, no timer. `propose()` answers EXACT / AMBIGUOUS / NOTHING / UNKNOWN from what the
   report says now versus the snapshot; it never writes a trade.
6. **Confirm.** One route (`/api/session/confirm`), one atomic idempotent transaction: append the
   trade with a stable id, close the pending row, move the cursor on, kick the derived stores. A
   second confirm of the same trade reports `already` and writes nothing. Mark sold is the same path
   with `source: 'manual'` — one route, two call sites, both a human saying it completed.
7. **Summary.** Earned, trades, trades left today, queue remaining, average, skipped/held, and at the
   end a card with duration and the highest sale.

## 3. Decisions worth defending

- **One state module.** `scripts/trade_session.py` owns every persisted loop field. `server.py` is
  thin adapters: read the payloads the app already produces, hand them in, save the result. No price,
  rank or buyer is recomputed in the route layer.
- **The panel is a pure render.** Reconciliation rides the payload instead of a second fetch; there is
  no timer in the panel and no fetch of its own. Every action is one POST followed by the app's own
  `load()`.
- **The loop proposes, the user confirms.** The private `trader/detector.py` auto-confirms; the public
  path deliberately does not, because the spec is explicit that nothing is inferred without asking.
- **One writer for `trade_log`.** The audit found four non-atomic writers and zero ids on 471 events.
  All public writers now go through `scripts/trade_session.py` (atomic, id-stamped), including
  `/api/trades`, `log_trade.py` and `import_aleca_stats.py`.
- **The count basis is explicit.** Where the report carries no row for the exact lane, a check counts
  the item's total across lanes and says `basis: item total` in its evidence rather than letting a
  total masquerade as a stack count.
- **`WFM_ROOT` / `WFM_DATA`.** Added so a live-server test or a CI gate can run without touching the
  real `data/`. This is what makes `tests/test_session_api.py` possible at all.
- **Build states are four words, not a percentage.** The scripts cannot report progress, so the app
  shows waiting / running / complete (with age) / failed (with the reason). A part that has landed
  stays complete even after a later pipeline failure.

## 4. Evidence

- **Full suite:** `python -m pytest tests -q` → **1861 passed, 5 skipped** (baseline at the doc commit:
  1780 passed, 5 skipped — 81 new tests, none failing).
- **Live route tests:** `tests/test_session_api.py` boots the real handler on an ephemeral port with
  `DATA`/`ROOT` redirected into tmp and drives `/api/session`, `/api/session/start|contact|reconcile|
  confirm` over a real socket with urllib. The repo had no live-HTTP route test before this work.
- **Release gate (stage 9):** `python design/_stage10/gate.py` → **GATE PASS — 118 checks, 0 failed,
  37 page states driven**, 0 console errors, 0 failed requests, 0 of 30 fit measurements over the line
  (1280x800 → 1920x1080 for home, inventory, trade, trade/orders, **trade/session**), 4 themes clean,
  0 duplicate ids, 0 ids missing against the stage-1 union. `design/_stage10/gate-report.md` is the
  merged artifact.
- **Live end-to-end (not a fixture):** the gate and the count-basis fix were both driven against the
  real app on `127.0.0.1:8787` with the real `data/`: a session started on the real plan (12 queue
  rows, real buyers `aleks_002`, `MrFail`, `NaYory`, `filnor9712`), two contacts opened, a check
  answered with real evidence, then the seeded store was deleted so the app is back to its normal
  no-session state.
- **Workflow gate (one command):** `python design/_session/workflow_gate.py` boots a throwaway data
  dir, drives the real UI through Whisper → CONTACTED → the reconcile check → Confirm, and rewrites
  `design/_session/workflow-report.md` with the verdict and the evidence it read back.

## 5. Weaknesses, honestly

- **Two order-book clients.** `orders.fetch_book` and the gitignored `trader/lister.fetch_book` are
  still separate implementations, as are the two buyer rankers and the three ways rank lanes are
  derived. They work and they are covered, so they were left alone: consolidating them is its own
  branch with its own regression pass, not a ride-along.
- **`trader/detector.py`** still auto-confirms from the private tree. The public path cannot see it,
  and it is gitignored, so it is documented here rather than touched.
- **The run queue carries no rank.** A buyer is matched to a row by item and price, so a
  rank-mismatched whisper cannot be detected from `run_queue.json` alone. The queue and the run queue
  are built from the same plan lanes today, so the exposure is theoretical — but it is real, and it is
  the one place where a wrong-looking suggestion would not be caught by the payload.
- **No packaging.** The app is still run from a checkout (`python server.py`); the spec's packaging
  section is untouched and remains its own piece of work.
- **The two browser probes the front-end unit wrote were throwaways.** They proved the route and the
  render, but they are not in the repo, so they are not repeatable from a clean checkout. The gate is
  the repeatable one and it now covers the same ground.

## 6. Environment note

The app Jay actually runs is supervised (`hermes/cache/scratch/wfm/supervisor.py`) and was serving
pre-session code until stage 9 — the supervisor respawned it on the new code during this work, so the
running app is current and `GET /api/session` answers live.
