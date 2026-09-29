# WFM Trader — Trading Session: round-2 report for outside review

**Revision under review:** `9d2a503` (branch `main`, `github.com/JAYST3AM/wfm-dashboard`, private)
**Previous revision reviewed:** `9cb77ec` — the package that returned the FIX verdict below
**Diff:** 19 files, +2400 / −101
**What this document is:** the answer to your seven findings, each with the cause as it actually
existed in the code, what changed, the evidence that it changed, and what is still not proven. Read it
against the code; every claim names a file, a test or a run.

---

## 1. The verdict being answered (quoted from the review)

> Verdict: FIX
>
> - Buyer source of truth is still duplicated. Session/Home use "run_queue.json"; Orders uses
>   "scripts/orders.py". Spec explicitly said one source.
> - Confirm isn't truly atomic. It writes "trade_log.json" first, then "trade_session.json". Crash
>   between them = sale logged, session/pending not advanced.
> - Trade records look inconsistent. Session confirm writes "plat" but existing analytics read
>   "total", so earnings/history can be wrong.
> - Reconciliation is too loose. "inventory drop >= qty" + "plat gain >= expected" counts as EXACT
>   even when extra items/plat moved; that should be ambiguous.
> - Rank safety isn't guaranteed. "run_queue" may have no rank, and the code still allows that buyer
>   onto a ranked queue item.
> - 118/118 browser gate doesn't prove the actual workflow. It's read-only and does not test Whisper →
>   CONTACTED → reconcile → Confirm.
> - CI on the pushed commit is currently red and pytest never ran because the checkout contains
>   "data/".
>
> Top fixes: 1. Make Confirm recoverable/transaction-safe. 2. Standardize trade schema ("plat",
> "total", qty) and test every downstream metric. 3. Make Session/Home use the same rank-aware
> order-book/buyer source as Orders.

Three of these were real bugs. Two were limitations the previous report called open. One (CI) was
worse than reported. One (rank safety) was real but the mechanism was not the one described. Working
through them turned up two further defects that no unit test could see.

---

## 2. Summary

| # | Finding | Verdict on the claim | Fix |
|---|---------|---------------------|-----|
| 1 | Buyer source duplicated | **Real** | run_queue now fetches through `scripts/orders.py`; the Session queue is rank-aware and evidence-honest |
| 2 | Confirm not atomic | **Real, and the worst of them** | Two-phase confirm + `recover()` on load |
| 3 | Trade record shape | **Real, and worse than reported** | Canonical `{plat (unit), total (money), qty, …}`; every downstream reader tested |
| 4 | EXACT too loose | **Real** | EXACT now requires the deltas to *match*; more movement ⇒ AMBIGUOUS |
| 5 | Rank safety not guaranteed | **Real, different mechanism** | `lane`/`rank` on every queue row; disagreement drops the buyer, absent evidence says so |
| 6 | Gate doesn't prove the workflow | **Real** | New write-capable workflow harness; it immediately found two more bugs |
| 7 | CI red; pytest never ran | **Real, pre-existing, and hiding a second failure** | data/ check fixed, then the 15 Windows-only tests that failed on Linux |

---

## 3. Finding 3 first, because it is the one that lost data

**The claim was right and the damage was worse than stated.** `server.trades_payload()`,
`scripts/session_stats.py` and `scripts/plat_ledger.py` all sum a field named `total`. A
session-confirmed sale wrote `plat` holding the *money*, and no `total` at all — so it did not merely
disagree with the app's history, it was **absent from every earnings figure in the app**. The old
record also had no `kind`, `name`, `user` or stable `id`, which is why `trade_log.json` held 471 events
and not one of them could be referenced.

The canonical record, written by `scripts/trade_session.py:confirm()`:

```python
# Canonical record shape, the one the whole repo already reads (see scripts/log_trade.py):
# `plat` is the price per copy and `total` is the money for the trade. server.trades_payload(),
# session_stats and plat_ledger all sum `total`, so a record that only carried `plat` vanished
# from every earnings figure, and one with `plat` holding the sum double counted it.
qty  = rec['qty']
unit = _int(rec.get('plat') if rec.get('plat') is not None else rec.get('price'))
money = _int(rec.get('total'))
if unit is None and money is not None:  unit  = int(round(float(money) / qty))
if money is None and unit is not None:  money = unit * qty
rec['plat'], rec['total'] = unit, money
```

Callers may send `plat` (unit), `price`, or `total`; both numbers are stored whichever way it arrives.

**Tested downstream, not just at the writer** (`tests/test_trade_confirm.py`,
`tests/test_session_api.py`): a 3 × 48p confirmation is asserted in
`plat_ledger.trade_totals()['earned']`, in `server.trades_payload()['totals']['earned']`, in the
session summary (`earned_plat`), and in the record itself as `plat=48, total=144`.

## 4. Finding 2: the transaction

Confirmed exactly as described: `confirm()` appended to `trade_log.json` and *then* saved
`trade_session.json`, so a crash in the window logged a sale the session never saw.

`confirm()` is two-phase now (the phase-1 intent is durable before the trade reaches the log):

```python
doc['confirming'] = {'id': rec['id'], 'rec': rec, 'ts': now}
save(data_dir, doc)                     # phase 1: the intent survives a crash
written, created = append_event(data_dir, rec)
if not created:
    doc = _finalise(data_dir, doc, written, rec, now)
    return {'ok': True, 'already': True, ...}, False
doc = _finalise(data_dir, doc, written, rec, now)   # phase 2, the same tail a replay uses
```

`load()` calls `recover()`, which asks one question — is the intent's trade id in the log?

- **yes** → the append landed: replay `_finalise()` (close the pending row, count the session, advance).
- **no** → the append never landed: drop the intent. The pending row was never touched, so the trade is
  still open and the user can confirm again.

`_finalise()` is one function used by both the live path and the replay, so they cannot drift, and it is
idempotent — a trade already in `confirmed` is skipped. Recovery also records what it did
(`recovered: {result: 'finished'|'rolled back'}`) rather than silently repairing. Both halves of the
window are covered by tests in `tests/test_trade_confirm.py`.

## 5. Finding 4: the check

`EXACT` had been "at least this much moved", so an unrelated sale in the same change could be claimed
as this one. Spec §4 asks for item + rank + qty + inventory delta + platinum delta to agree:

```python
elif left == qty and total and delta_plat == total:
    verdict, why = EXACT, ...
elif left >= qty and total and delta_plat >= total:
    verdict, why = AMBIGUOUS, _evidence(..., ('more moved than this trade', ...))
```

More movement than this trade asked for is evidence, not a claim — it is shown with the excess
("1 extra copy", "more moved than this trade"), and the user decides.

## 6. Findings 1 and 5: one buyer source, and the rank on it

The duplication was real: two order-book clients (`scripts/orders.py` in the app,
`scripts/trader/lister.py` in the private engine), two buyer rankers. The private engine now fetches
through the public client — one order book, one cache, one failure policy — keeping the
`fetch_book(item_id)` seam its offline tests patch. `scripts/trader/` is gitignored, so that half of
the fix lives on this machine and cannot be reviewed from the repo; what is reviewable is its contract,
`tests/test_runqueue.py`.

The rank problem had a different mechanism than described: buyers *were* selected per lane, but the
queue rows carried no rank at all, so the Session queue's rank guard could never fire —
`_rank_of()` had nothing to compare. Queue rows now carry `lane` and a derived `rank` (`None` for items
with no rank dimension), and the Session queue uses it:

```python
rq_rank = _rank_of(rq) if rq else None
if buyer and rq_rank is not None and rank is not None and rq_rank != rank:
    buyer = None                      # never pair a rank-10 stack with a rank-0 order
    mismatch = 'buyer is for rank %s' % rq_rank
...
elif buyer and rank is not None and rq_rank is None:
    why['rank_unverified'] = 'queue row names no rank for this buyer'
```

A disagreeing buyer is dropped and the row says why. When there is genuinely no rank evidence the buyer
is still shown — the run queue picks per lane — but the row states that it could not be checked rather
than implying it was. Four tests in `tests/test_trade_session_state.py` cover agreement, disagreement,
no-evidence, and an item with no rank dimension.

## 7. Finding 6: the gate, and the two bugs it found

Right: `design/_stage10` was a read-only acceptance gate — rendered copy, layout, console errors. It
could not prove the loop, and it never clicked anything.

There is now a second, deliberately different harness: `design/_session/workflow_gate.py` (one command,
exit 0/1) seeds a throwaway data directory, boots `server.py` against it with the game send stubbed,
runs `design/_session/workflow_gate.js` in headless Chrome, and asserts what actually changed on disk.
It drives: Start → the focus card's Whisper button → `/api/whisper` → the CONTACTED pending row → the
check raised by the app's own refresh cadence (no interaction, no timer) → the check's Confirm button →
`/api/session/confirm`, then reads the screen, `/api/session`, `trade_session.json` and
`trade_log.json` back.

**Verdict on the pushed revision: PASS, 22 of 22 checks**, with the trade landing as
`plat=48 / total=144`, `earned_plat=144`, the pending and queue rows COMPLETED, and no console errors
or failed requests over the whole drive. `design/_session/workflow-report.md` holds the full
expected/observed list.

**It found two real defects on its first runs, neither visible to a unit test:**

1. **The Checks card could never paint.** `sessionPayload()` in `static/session.js` is the view model
   every renderer reads as `P`, is hand-written from the payload, and never copied `proposals`,
   `needs_you` or `checks` across. The server answered EXACT with a ready draft and the panel rendered
   an empty card — §4's check and its Confirm button were unreachable in the shipped UI. The same gap
   hid the end-of-session card (`P.session.ended_ts` was not carried either). Both are carried now, and
   a test reads every `P.<key>` the renderers use out of `session.js` and fails if the mapping does not
   carry it; it caught `P.session` on its first run.
2. **The draft carried the sum where the unit belongs.** `propose()` passed `expected × qty` into
   `trade_draft()`, which stores `plat` as the per-copy price — so a 3 × 48p sale would have been
   recorded as 432p. Fixed, with two tests pinning `plat=48 / total=144`.

The read-only gate was re-run afterwards on the changed code: **PASS, 118 checks, 0 failed, 37 page
states** (`design/_stage10/gate-report.md`), so the panel changes did not regress the acceptance set.

## 8. Finding 7: CI

Worse than reported, and in two halves.

**Half one:** the workflow failed the build whenever a `data/` directory existed. `data/.gitkeep` has
been tracked since the first release, so that step failed on **every push** — the five failures before
the fix (`5965f2e`, `2bdc31e`, `a45b6cc`, `9718084`, `9cb77ec`) each died in 12–23 seconds with pytest
never reached. The check now looks for runtime *files* in `data/` and allows the tracked `.gitkeep`. With pytest finally able to start, three tests
failed on a clean checkout (`tests/test_terminology_live_not_live.py` reads `scripts/trader/*`, which is
private and absent from a clone); they are guarded by a skip, the way `tests/test_runqueue.py` already
handled the same situation.

**Half two, only visible once half one was fixed:** on the Linux runner, **15 tests failed** that pass
here — 11 in `tests/test_whisper.py` (`send()` refuses with `'windows only'` before it reaches any
seam, and those tests drive the Windows path with fakes without declaring it, while the file's own
docstring claims the logic is asserted on any platform) and 4 in `tests/test_refresh_guard.py` (the
pipeline built its AlecaFrame path with `os.path.expandvars(r'%LOCALAPPDATA%\AlecaFrame')`, and
`expandvars` only knows the `%NAME%` syntax on Windows, so the fake `%LOCALAPPDATA%` the test sets never
resolved). Both are fixed: the whisper tests declare Windows like the rest of their file, and the
refresh path reads the environment first, falling back to the old literal so Windows is unchanged.

**Evidence:** the failing run is `36507816492` (step 5 of 6 — the data/ check — success; step 6 —
pytest — failure, `15 failed, 1609 passed, 256 skipped`). The pushed revisions are green:
`36508522683` and `36509153377`, runner output `1624 passed, 256 skipped, 1 warning in 66.51s`.

## 9. Evidence ledger

| What | Result |
|---|---|
| Public suite, this machine (Windows) | `1875 passed, 5 skipped` |
| Public suite, fresh clone, same command CI runs | `1623 passed, 254 skipped, 0 failed` (pre-CI-fix revision) |
| Public suite, GitHub Actions (Linux, `9d2a503`) | `1624 passed, 256 skipped` — **success** |
| Release gate `design/_stage10/gate.py` | **PASS** — 118 checks, 0 failed, 37 page states |
| Workflow gate `design/_session/workflow_gate.py` | **PASS** — 22 of 22, trade `plat 48 / total 144`, pending + queue COMPLETED |
| Previous CI runs | five failures in 12–23s (dead at the data/ step, pytest never reached); then `d170149`, 75s — pytest ran and failed the 15 Windows-only tests |

## 10. What this does not prove (stated plainly)

- The whisper **transport** is stubbed in the workflow gate: `scripts/whisper.py` types into a running
  Warframe window, and a gate must never whisper a real player. `whisper.send()` is replaced with a stub
  returning success; `line()`, `copy()` (the real clipboard path), the `/api/whisper` route, the
  `sent → contact()` branch and everything after it are the real code. The last centimetre — keystrokes
  into the game — is not exercised.
- The game's side of reconciliation is synthesized: the driver writes the sale into the throwaway
  `report.json` / `plat_history.json` that `scripts/report.py` and `scripts/snapshot_plat.py` would
  normally write. `contact()`, `propose()`, the check's evidence and `confirm()` are unmodified.
- The post-confirm pipeline kick is stubbed to a no-op, because `refresh.py` / `invdiff.py` /
  `progress.py` do not read `WFM_DATA` and would rewrite the developer's real `data/`. The confirmation
  transaction is unaffected.
- Nothing about the network: the session loop takes no network path, so prices, the order book and
  warframe.market are not covered.
- The private `scripts/trader/` tree is not in the repo, so finding 1's fix is reviewable only through
  its contract test.
- A stale `run_queue.json` written by the old code has no `rank`, and those rows correctly fall back to
  `rank_unverified` until the producer next runs.

## 11. Where to attack next

1. `confirm()` + `recover()` + `_finalise()` in `scripts/trade_session.py` — is the phase ordering
   genuinely crash-safe, and is `_finalise()` really idempotent for every field it touches (session
   totals, `done`, cursor, pending row, queue row)?
2. The canonical record: are there readers that still expect the old shape (`price`, `buyer`, a missing
   `id`)? `scripts/log_trade.py`, `scripts/import_aleca_stats.py`, `scripts/plat_ledger.py`,
   `scripts/session_stats.py`, `server.trades_payload()`.
3. The workflow harness itself: is 22 checks the right coverage for the loop, and is any of them
   tautological? Does it assert anything that would pass even if the feature were broken?
4. `static/session.js`: the renderer now reads the proposals — does any other card silently drop a
   payload key the same way `sessionPayload()` did?
5. The rank rule: dropping a buyer whose lane disagrees is the safe direction, but is `_rank_of()`'s
   parse of `'rank 6'` / `'intact'` / `None` correct for every lane the plan produces?
