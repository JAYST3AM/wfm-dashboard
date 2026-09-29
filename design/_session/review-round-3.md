# Review round 3 — what the second outside review found, and what was done about it

The round-2 package came back **FIX** with four correctness gaps and nine counterexample tests. This is
the answer to each, in the order the review ranked them, with the cause as it existed in the code, the
fix, and the evidence. Nothing here is a plan: every claim names a file, a test or a run.

**Code revision for this report: `4688d3a`** (main) — the commit the reviewer should check out.
This file is the only thing added after it, so the code is byte-for-byte what was reviewed.

**Verdict being answered:** "Round 2 fixes several real defects and materially improves the workflow,
but four correctness gaps remain before this should be treated as fully closed."

---

## The short version

| # | Finding | Verdict on the claim | What changed |
|---|---------|---------------------|--------------|
| 1 | Confirm recovery improved but idempotency incomplete (capped `confirmed[]`; no lock against concurrent confirms) | **Real on both counts** | Unbounded `settled` id list as the idempotency key; `confirm()` serialised by a lock |
| 2 | New records canonical, but `append_event()` does not canonicalise and legacy records stay invisible | **Real** | `scripts/trade_schema.py` owns the shape; the writer boundary canonicalises or refuses; every reader sums through `money_of()` |
| 3 | Lane identity incomplete (`rank=None` conflates relic refinements; `_runqueue_of` picks the first buyer for a slug; unverified buyers stay actionable) | **Real, and wider than described** | One lane identity `(slug, lane)` through queue, buyer lookup, pending rows, inventory maps, the check and the tail |
| 4 | EXACT can still be claimed from whole-item evidence; no evidence-consumption rule across pending trades | **Real** | A narrowed lane with whole-item evidence is AMBIGUOUS; two pending trades on one lane can never both be EXACT |

Nine counterexample tests were asked for; all nine exist (`tests/test_trade_round3.py`,
`tests/test_trade_schema.py`) and the four behaviour changes they pinned are the fixes above.

---

## 1. Confirm: the capped list, and the thread

**The claim:** session-side idempotency depended on `confirmed[]`, which is trimmed, so a retry of an
evicted id could settle a second time; and the threaded server had no lock.

Both were real. `confirmed` is capped at 500 for the UI's benefit, and it was the only thing
`_finalise` consulted — a retry would have appended nothing (the id is already in `trade_log.json`,
which `append_event` checks) and then incremented the totals, closed the pending row and advanced the
cursor a second time.

**Fixed:** the idempotency key is now `settled`, a list of ids that is never trimmed, carried through
`normalise()`/`save()` like every other persisted field:

```python
def _settled(doc, tid):
    """Has this trade already been settled in the session? Never evicted, so a retry is safe."""
    ...checks `settled` and `confirmed`...
```

`_finalise()` consults `_settled()` and ends with `_mark_settled(doc, tid)`, so the two paths a trade
can arrive by (live, or replayed by `recover()`) both leave exactly one mark.

**Fixed (thread):** `confirm()` is now a thin wrapper around `_confirm()` under a module-level
`threading.RLock()`, so the read-modify-write is atomic for the whole transaction — not just for the
file write — and no caller can reach the unguarded body.

The lock is a `threading.RLock` inside the process that serves the dashboard, which is what the
review asked for: `ThreadingHTTPServer` was letting two clicks interleave. It does not cover two
separate server processes pointed at one data directory, and nothing in this repo does that.

**Tests:** `test_an_id_evicted_from_the_visible_list_cannot_settle_twice` empties `confirmed`, saves,
retries, and asserts the totals, `done` and the log are unchanged. `test_two_simultaneous_confirms_settle_exactly_once`
runs two real threads against one data dir and asserts one trade, one settlement, `trades == 1`,
`earned_plat == 144`, one `done` entry.

## 2. One record shape, at the writer

**The claim:** `append_event()` does not canonicalise, so any caller writing `{kind: sale, qty, plat}`
without `total` can still create a record the analytics cannot see; and legacy records stay invisible.

Both were real, and the first is the more dangerous: `append_event` is public and is the only writer of
`trade_log.json`.

**Fixed:** `scripts/trade_schema.py` now owns the record. `canonical(rec, source, now)` is the shape,
and it **refuses** rather than stores a sale with no price:

```python
if unit is None and money is None:
    raise ValueError('a %s needs a price: plat (per copy) or total (the money)' % out['kind'])
```

`confirm()` calls it, and so does `append_event()` — the writer boundary — while `POST /api/trades`
answers **400** with that message instead of a 500 (it was catching every exception as a server fault).

**Legacy compatibility:** `money_of(ev)` reads `total` when the record has it and `plat × qty` when it
does not (the pre-canonical shape, where `plat` was the price per copy — they coincide for one copy,
which is the historical case). Every reader that sums money now goes through it: `plat_ledger.trade_totals`
(including the covered-net line), `session_stats` gross/spent/best-sale, and `server.trades_payload()`.
Jay's own `trade_log.json` holds 471 events, 470 of them already carrying `total` and one a `note`, so
nothing had to be migrated — but a record written by an older shape is now counted instead of skipped.

**Tests:** `test_a_sale_written_without_its_money_gets_one`, `test_the_writer_refuses_a_sale_with_no_price_at_all`,
`test_the_ledger_still_counts_a_record_written_before_the_canonical_shape`,
`test_a_legacy_record_still_reads_as_money_through_the_session`, `test_the_trades_route_stores_the_money_a_sale_omits`,
`test_the_trades_route_refuses_a_sale_with_no_price`, plus the whole of `tests/test_trade_schema.py`.

## 3. Lane identity: `(slug, lane)`, everywhere

**The claim:** `_rank_of()` gives `rank=None` for non-numeric lanes; `_runqueue_of()` picks the first
buyer for a slug; and `rank_unverified` leaves the buyer actionable. The first two are worse than
described: `row_key(slug, rank)` was the identity used for queue dedupe, the inventory maps, the
pending rows, the check and the tail — so **two refinement lanes of one relic shared a key**. Intact
and Radiant versions of a relic have the same slug and no rank at all, so they collided everywhere:
the queue would show one and quietly drop the other, and a Radiant sale would close the Intact row.
Mod ranks collided with nothing, but the buyer lookup could not tell rank 0 from rank 6 of one item.

**Fixed:** the lane is the identity. `trade_schema` owns it —
`lane_of(row)` (the row's `lane`, else derived from `lane_rank`/`rank`), `norm_lane('rank 6') == 'r6'`,
`lane_key(slug, lane) == 'slug#r6'` (the spelling the stored state already used for a rank, so nothing
that resolves today stops resolving) and `key_of(row)`. Then:

- **queue rows** carry `lane`, are deduped on the lane key, and the two-lane case is pinned by
  `test_intact_and_radiant_relics_stay_distinct_end_to_end` and `test_two_ranks_of_one_item_never_share_a_buyer`;
- **buyers** are looked up per lane: `_runqueue_of(runqueue, slug, lane)` matches the lane, and
  `_runqueue_any()` exists only so a row can say *why* it has no buyer (another lane's order, or a row
  from an older producer that names no lane);
- **pending rows** carry `lane`, and `pending_id()` hashes it, so two lanes of one relic are two
  contacts rather than one update of the other;
- **inventory maps** (`inv_now_map`, `inv_basis_map`), the contact snapshot, the reconcile route and
  the panel all key on `key_of(row)`;
- **`_finalise()`** closes the pending row and the queue row by lane key, so a Radiant sale cannot
  complete an Intact row;
- **the panel** posts `lane` with a contact and with Skip/Hold, and `ordWhisper` forwards the button's
  `data-lane`, because the whisper is what opens the CONTACTED row.

**Rank safety, as the review asked:** an unverifiable buyer is no longer actionable. When a lane is
asked for and the run-queue row does not name one, the buyer is dropped and the row says
`rank_unverified`; when the row names a *different* lane, it says `rank_mismatch`. The old behaviour —
show the buyer with a caveat — is gone, and the test that used to pin it
(`test_a_buyer_with_no_rank_evidence_on_a_ranked_lane_says_so`) was rewritten to pin the new rule.
Rows with no lane dimension at all (the item itself) are unaffected: there is no rank to check.

## 4. The check cannot over-claim

**The claim:** a ranked trade could still become EXACT from whole-item evidence, and two pending trades
could both consume the same one movement.

Both were real. `inv_basis == 'item'` was only used to *label* the evidence, never to qualify the
verdict, and `propose()` looked at each pending row in isolation.

**Fixed:** two rules in the check, each with its own line of evidence:

```python
if verdict == EXACT and basis == 'item' and lane_is_narrowed(p.get('lane') or rank):
    verdict = AMBIGUOUS
    why = _evidence(('basis', 'the whole item, not this lane')) + why
if verdict == EXACT and watchers.get(key_of(p), 0) > 1:
    verdict = AMBIGUOUS
    why = _evidence(('same lane', '%d pending trades; one movement cannot be split' % ...)) + why
```

A *narrowed* lane is one that names less than the item — a mod rank or a relic refinement. It is not a
blanket rule against the item basis: the report carries one row per item, so a rank the report does not
name can only ever be counted from the whole item, and claiming EXACT from it is exactly the
over-claim the review described. The proposal is still shown, with its numbers and a Confirm button —
AMBIGUOUS is a proposal, not a refusal — the user just decides.

**Tests:** `test_a_narrow_lane_with_only_whole_item_evidence_is_ambiguous` (and its counterpart: an
unlaned row with no rank dimension may still be exact), `test_two_pending_trades_cannot_both_claim_one_movement`,
and the two session-level tests the rule changed (`test_a_lane_the_report_does_not_carry_still_gets_a_count`,
`test_the_check_says_when_it_counted_the_whole_item`) now assert AMBIGUOUS with the reason.

---

## The nine counterexample tests

| Test the review asked for | Test that now exists | Result |
|---|---|---|
| Evicted confirmed ID | `test_an_id_evicted_from_the_visible_list_cannot_settle_twice` | totals, `done` and the log unchanged on retry |
| Concurrent confirm | `test_two_simultaneous_confirms_settle_exactly_once` (two real threads) | one trade, one settlement |
| Writer normalisation | `test_a_sale_written_without_its_money_gets_one` + `test_the_trades_route_stores_the_money_a_sale_omits` | `total = 144` stored |
| Old-record compatibility | `test_a_legacy_record_still_reads_as_money_through_the_session`, `test_the_ledger_still_counts_a_record_written_before_the_canonical_shape`, `tests/test_trade_schema.py::test_a_record_without_a_total_still_reads_as_money` | 75p counted, not 15p |
| Same slug, two ranks | `test_two_ranks_of_one_item_never_share_a_buyer` | each row selects only its own buyer |
| Relic refinements | `test_intact_and_radiant_relics_stay_distinct_end_to_end`, `test_a_lane_rides_the_contact_route` | distinct through queue, contact, check and confirm |
| Unverified ranked buyer | `test_a_buyer_with_no_rank_evidence_on_a_ranked_lane_is_not_actionable` | no actionable buyer |
| Item-total fallback | `test_a_narrow_lane_with_only_whole_item_evidence_is_ambiguous` | AMBIGUOUS, with the reason |
| Shared evidence | `test_two_pending_trades_cannot_both_claim_one_movement` | neither is EXACT |

Two of these failed on their first run and the failures were real bugs in this round's own work, both
now fixed and pinned: a pending id that did not include the lane (two relic lanes collided in the
timestamp's second), and `norm_lane(0)` returning "no lane" because `0 or ''` is `''` — rank 0 is a
lane, and the check treated it as unlaned.

## Evidence: the suite, both gates, and the live files

- `python -m pytest tests -q` — **1898 passed, 5 skipped** on Windows.
- CI on the pushed revision, run `36528689054` — **completed success**, and the step conclusions
  show the test step itself ran: `1647 passed, 256 skipped` on the Linux runner (the skip count is
  the private-engine tests plus the Windows-only paths, not failures).
- `python design/_stage10/gate.py` (the read-only UI gate, against the running app) — **PASS, 0 of 118
  checks failed, 37 page states driven**.
- `python design/_session/workflow_gate.py` (the write-capable gate: Whisper -> CONTACTED -> check ->
  Confirm, in a headless browser, on a throwaway store) — **WORKFLOW PASS, 22 of 22 checks**. Its seed
  had to change with the fix: the run-queue row it seeds now names its lane, exactly as the real
  producer writes it, because a row that names no lane is deliberately not actionable any more. The
  first run after the change failed on a 45 s wait with no buyer row to click — the gate catching the
  fix it was written to test, then passing once the seed was honest about its lane.
- The live files: Jay's own `run_queue.json` predated the producer's lane field, so it was regenerated
  by `scripts/trader/runqueue.py` (read-only against the public order books; the previous file is kept
  in the session scratch dir). It now writes `lane` and `rank` on every row — relics as `intact`, mods
  as `rank 0` — and rebuilding the queue from the live `trader_plan.json` gives **two distinct
  `primed_continuity` rows (rank 0 and rank 6), each paired only with a buyer of its own lane**. Before
  this round those two rows shared one key and one of them did not exist.

## What is still not proven (stated plainly)

- The workflow browser gate still drives **one happy-path item**, stubs the whisper transport,
  synthesizes the game-side save change and no-ops the post-confirm pipeline kick. It does not exercise
  crash recovery, concurrency, lane variants or old records — those are covered in the suite, not in a
  browser.
- A `run_queue.json` written before lanes existed names no lane, and a ranked-lane row then shows no
  buyer (with `rank_unverified` as the reason) until the producer next runs. On this machine that is
  already regenerated; the general rule is that the row is a visible empty state asking for a rerun,
  never a silent pairing with the wrong lane's buyer.
- The private `scripts/trader/` engine is gitignored, so its half of the buyer work is only reviewable
  through `tests/test_runqueue.py`.
- `settled` grows with every confirmed trade and is deliberately never trimmed; a session store is small
  (an id is ~20 bytes), but it is a file that only ever gets longer, and that is a choice, not an
  oversight.
