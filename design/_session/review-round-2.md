# Review round 2 — what an outside reviewer found, and what was done about it

An external review of the pushed package returned **FIX** with six findings. Each was checked against
the code before anything was changed; what follows is the finding, the verdict, the fix and the
evidence. Two of the six were already-known limitations, three were real bugs, and one was a
pre-existing CI failure that had been hiding the whole test suite.

## 1. "Buyer source of truth is still duplicated"

**Confirmed.** `scripts/trader/runqueue.py` (which writes `run_queue.json`, what the Session queue and
Home read) fetched its order books through the private `scripts/trader/lister.py`, while Trade >
Orders used the public `scripts/orders.py`. Two clients, two caches, two failure policies, one
upstream.

**Fixed** in the producer: `runqueue.fetch_book()` now goes through `scripts/orders.snapshot()` - the
shared client, which caches with a TTL and serves the stale cache when a live fetch fails - and only
falls back to the private lister when that module cannot be imported. The seam keeps its name and
arity (`fetch_book(item_id)`), because the offline tests patch exactly that name; the slug the shared
client needs comes from a module-level map the planner fills before fetching.

**Note:** `scripts/trader/` is gitignored, so this fix lives on Jay's machine, not in the pushed
tree. The public repo sees it only through the contract test.

## 2. "Confirm isn't truly atomic"

**Confirmed, and the most serious of the six.** `confirm()` appended to `trade_log.json` and then
saved `trade_session.json`: a crash between the two logged a sale the session never saw, leaving the
pending trade open and the earnings short.

**Fixed** with a two-phase write and a recovery path:

- `confirm()` now writes the **intent** (the record, with its id) into `trade_session.json` *before*
  the trade reaches `trade_log.json`.
- `load()` calls `recover()`, which asks one question: is the intent's id in the trade log? If yes,
  the finalisation is replayed (close the pending row, count the session, advance the cursor); if no,
  the intent is dropped and nothing is claimed. The pending row was never touched either way, so the
  trade is still open and can be confirmed again.
- The finalisation itself is now one function (`_finalise`) used by both the normal path and the
  replay, so the two cannot drift, and it is idempotent: a trade already in `confirmed` settles only
  the intent.

Tests: the intent is durable before the append (a failing append leaves the intent and no trade),
a post-append crash finishes itself, a pre-append crash rolls back, the replay never counts twice,
and a rollback leaves the pending row, queue and cursor untouched.

## 3. "Trade records look inconsistent — session writes `plat`, analytics read `total`"

**Confirmed, and worse than stated.** Everything downstream sums `total`: `server.trades_payload()`,
`scripts/session_stats.py` and `scripts/plat_ledger.py`. A session-confirmed sale wrote `plat` as the
money with no `total` at all, so it **vanished from every earnings figure in the app**.

**Fixed:** the stored record is the shape the rest of the repo already reads — `plat` is the price per
copy, `total` is the money for the trade, plus `qty`, `kind`, `name`, `ts`, a stable `id` and `src`.
Callers may send `plat` (unit), `price` or `total`; whichever arrives, both numbers are stored.
`trade_draft()` emits the same pair. The panel's manual "Mark sold" now sends the unit price and the
total explicitly.

**Tested downstream, not just at the writer:** a confirmed 3 × 48p sale is asserted to appear in
`plat_ledger.trade_totals()['earned']` and `server.trades_payload()['totals']['earned']` as 144.

## 4. "Reconciliation is too loose — extra items/platinum still counts as EXACT"

**Confirmed against the spec.** §4 says an exact match is item + rank + quantity + inventory delta +
platinum delta agreeing, and "if exact matching is not possible, present the evidence rather than
guessing".

**Fixed:** EXACT now requires `copies_left == qty` **and** `plat_delta == total`. Anything that moved
*more* than this trade is AMBIGUOUS with the excess shown explicitly ("more moved than this trade:
1 extra copy, +132p") — the same shape as the spec's own example of presenting evidence.

## 5. "Rank safety isn't guaranteed"

**Half confirmed.** The private producer *did* already select buyers per lane (`lane_match` requires
the buyer's order rank to equal the lane's), but the row it wrote carried no rank, so the Session
queue's rank guard could never fire and a ranked-lane sale showed a buyer nothing could verify.

**Fixed both sides:** the producer now writes `lane` and a derived `rank` on every queue row (`None`
for items with no rank dimension: `''` and `intact` lanes), and the Session queue uses it — a buyer
whose rank disagrees is dropped with `why.rank_mismatch`, and when the row truly carries no rank for a
ranked-lane sale the buyer is shown **with** `why.rank_unverified` rather than implying it was
checked. Items with no rank dimension never ask for rank evidence.

## 6. "The 118/118 gate doesn't prove the workflow"

**Confirmed, and it is the gate's own stated scope.** `design/_stage10/gate.js` is read-only on the
app: it drives every view, checks console errors, fit, themes, copy and ids, but it never whispers,
contacts, reconciles or confirms — so the loop's write path was proven only by the API tests, not by
the UI.

**Fixed** with a separate end-to-end workflow harness (`design/_session/workflow_gate.py` +
`workflow_gate.js`): it boots the dashboard against a throwaway data directory with the game send
stubbed, drives the real UI through Whisper → CONTACTED → the reconcile check → Confirm, and asserts
what actually changed on disk. It is a different promise from the read-only gate and is documented as
such. See `design/_session/workflow-report.md` for its run and its verdict.

### The harness earned its keep immediately: two bugs no unit test could see

The first run got through load → start → whisper → contact, then failed at Confirm, and the failure
was real:

- **The Checks card could never paint.** `sessionPayload()` — the view model every renderer in
  `static/session.js` reads as `P` — is hand-written from the feature payload and never copied
  `proposals`, `needs_you` or `checks` across. The server answered EXACT with a ready draft and the
  panel rendered an empty card, so §4's check and its Confirm button were unreachable in the shipped
  UI. The same gap hid the end-of-session card (`P.session.ended_ts` was not carried either). Both
  are carried now, and a test reads every `P.<key>` the renderers use straight out of `session.js`
  and fails when the mapping does not carry it — it caught `P.session` on its first run.
- **The draft carried the sum where the unit belongs.** `propose()` passed `expected × qty` into
  `trade_draft()`, which stores `plat` as the price per copy, so a 3 × 48p sale was recorded as
  432p — the exact class of error finding 3 was about, one layer up. `propose()` now passes the
  per-copy price, so the draft carries `plat=48` / `total=144`, and two tests pin it.

Neither could be caught by the API tests, which assert the server's answer, not what the panel does
with it.


## 7. "CI on the pushed commit is red and pytest never ran because the checkout contains data/"

**Confirmed, and it is pre-existing.** `data/.gitkeep` has been tracked since the initial release, and
the workflow failed the build whenever a `data/` directory existed — so that step failed on every
single push and **pytest never ran in CI at all**. GitHub Actions shows six consecutive failures at
~12 seconds each.

Fixed in two parts:

1. The workflow now checks for runtime **files** in `data/`, allowing the tracked `.gitkeep` that keeps
   the directory in the tree.
2. With pytest finally able to run, three tests turned out to fail on a clean checkout:
   `tests/test_terminology_live_not_live.py` reads `scripts/trader/*`, which is private and absent
   from any clean clone. Those three are now guarded by a skip, matching how `tests/test_runqueue.py`
   already handled the same situation.

**Verified the way CI runs it:** a fresh `git clone` of the commit, then `python -m pytest tests -q`
inside it. Before: `3 failed, 1612 passed, 251 skipped`. After: see the run recorded in the commit
message.

## What is still open (honestly)

- The private `scripts/trader/` tree is not in the repo, so finding 1's fix cannot be reviewed from
  the pushed tree — only its contract test.
- `run_queue.json` and the report are not regenerated by the tests; a stale `run_queue.json` written
  by the old code has no `rank` field, and the Session queue correctly falls back to
  `rank_unverified` for those rows until the producer next runs.
- The workflow harness drives the four write steps against a fixture store, not against the live
  game: the whisper send is stubbed, because sending a real in-game whisper is a user action and the
  spec forbids automating it.
