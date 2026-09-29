# UX pass — WFM Trader, 2026-09-29

**Brief (Jay's prompt):** one-click Home → Trading Session, less decision friction, an unmistakable
next action (what to sell, for how much, who wants it, what next), better hierarchy/labels/empty
states, safety and history still reachable but out of the way — without redesigning for its own sake.

**Method:** the live UI first (headless Chrome shots of Home, Trade, Session, Orders and Tools at
1600×900, plus a DOM dump of headings, buttons, labels and empty states per surface), then the
smallest set of changes that answered the brief, each one re-using a producer and a class that
already existed. Both repo gates re-run afterwards.

## What changed, and why

### 1. The session's next action lives with the empty state

`#trade/session` with no session showed `No session open yet.` in a large empty card while the only
way to start sat up in the card header as a small quiet button. **Now:** an accent `Start trading`
button inside the empty state, with one line under it (`From the plan, one item at a time`), in a
`#sessionStartBox` that hides once a session exists — at which point the header keeps Next / Skip /
Hold / End. One action, where the eye already is.

`#sessionStart` kept its id and its place in the panel markup, so the read-only gate's check that the
panel ships the control and that it is visible on load still holds.

### 2. The two cards that say nothing now step aside

With no session, "Waiting on a confirmation" and "Checks" were two empty panels stacked under the
empty state, both saying a variant of nothing. They now hide while there is no session at all. A live
session (or a finished one) keeps them: there, "nothing waiting" is an answer, not an absence.

### 3. The suggested queue answers "who wants it" instead of "ready" twelve times

Before a session starts every row is `READY`, so the first column was one word repeated down the
list. It now carries the run-queue buyer for that row's lane, or an honest `no buyer` pill (a state
reads as a pill; a name stays a value). The buyer is matched by lane — `rank 6` and `rank 0` are two
listings of one mod, and a row never borrows another lane's buyer. One rule (`sessionAskedBy`) is
used by the panel, by the Home whisper row and by Home's head action, so the three can't disagree.

### 4. Home's Next action: one accent action, not three

The card was carrying `Open Trade` (accent, pointing at the plan surface), `Start trading` (quiet),
a prose line naming the buyer and the price, and then a whisper row naming the same buyer, the same
price, the same status and offering the same action. **Now:** the accent belongs to the loop action —
`Start trading` (which builds the queue and takes you to `#trade/session`), or `Open session` when one
is already running — and the head's doorway to the plan is a quiet pill. The duplicated prose line is
gone; the whisper row keeps the buyer, the price, the status and its button.

The 2026-09-28 rule it replaces was "one accent-filled control on Home, and it is the next action".
That rule still holds; the UX pass moved which control it is. Both it and the shell's Refresh weight
are re-pinned in `tests/test_home_layout.py` with the reason in the comment.

### 5. A lane-aware buyer on Home as well

Home's whisper row and head action picked the *first* run-queue buyer for the slug. With lanes, the
top row can be `rank 6` while only `rank 0` has a buyer — Home would have shown the wrong lane's
buyer, which is exactly what the session loop stopped doing last commit. Both now ask the same rule.

### 6. One alignment fix

`Today's detail` sat 12px in while the KPI strip's first cell starts at 14. It now lines up with the
strip it belongs to.

## Deliberately not changed

- **The Trade tab strip.** `Advanced` staying a real tab one click from Sell is a pinned
  reachability contract (`tests/test_trade_density.py`, stage-4 spec) — it is already rendered at the
  quiet weight, so it is reachable without competing with Session/Orders/Sell.
- **The header cluster** (search, Theme, Settings, Sync, Refresh, PNG). Every one of them is a
  control Jay reaches for daily, and the IA pins their ids; nothing here was crowding the action.
- **No new copy, no new panel, no new engine.** Six changes, all inside the existing producers and
  the existing class vocabulary (`.card`, `.picks`, `.chip`, `.sessrow`, `.ordrow`, `.btn`).

## Evidence

- `python -m pytest tests -q` — **1904 passed, 5 skipped** on Windows, after the last code edit.
- `python design/_stage10/gate.py` (read-only UI gate: rendered copy, fit at five viewports, console
  and network hygiene, id snapshots, four themes) — **PASS, 0 of 118 checks failed, 37 page states
  driven**.
- `python design/_session/workflow_gate.py` (write-capable: Start → Whisper → CONTACTED → check →
  Confirm in a real browser, on a throwaway store) — **PASS, 22 of 22**. The change it exercises most
  is #1: the gate's own check that the Session panel ships a visible `#sessionStart` still passes
  with the control moved into the empty state.
- Screenshots and the DOM facts behind every claim: the review shots live in the session scratch dir
  (`ux/home.png`, `ux/trade-session.png`, `ux/trade.png`, `ux/trade-orders.png`, `ux/tools.png`, plus
  `ux/facts.json`), captured with the puppeteer recipe `ux_shots.js` that ships beside them.

## What this does not prove

- The hierarchy judgements came from a model reading screenshots plus a DOM dump, not from Jay's eye.
  The machine-checked part is the fit sweep (no page over-scroll at any of the five viewports), the
  contrast/theme checks and the copy limits — all in the gates above.
- The workflow gate still drives one item through one happy path; it does not exercise the lane
  variants, which are covered in the suite (`tests/test_trade_round3.py`).
---

# Regression found after the pass, and fixed (2026-09-29, later)

**Reported:** `renderNextAction()` read `const b = sessionAskedBy(r) || who[0]`. The rule is
lane-aware, but the fallback was slug-wide, so when the top plan row's lane had no buyer and another
lane of the same item did, Home painted the wrong lane's buyer, its price and its Whisper button. The
guard looked defensive; it was the bug.

**Fixed:** Home's buyer comes from `sessionAskedBy(r)` and nothing else. The slug-wide helper
(`homeBuyers`) and the constant that fed its hover title (`RUNQ_WHOM`) are gone with it, and the
whisper row keeps asking the same rule — so even a future fallback cannot produce a button, only
text.

**Pinned in three layers** (`tests/test_lane_buyer.py`):

| layer | what runs | what it proves |
|---|---|---|
| the rule | `design/_session/lane_buyer_check.js` — node evaluates `sessionAskedBy` **from static/session.js itself** (brace-matched, not copied) and runs 10 cases | the rank-6 row with only a rank-0 buyer answers *nothing*; the same row with its own buyer answers it; rank 0 is a lane, not a missing one; an intact relic never takes the radiant buyer; an unlaned item never borrows a laned one |
| the call site | source pins in the same file | exactly one buyer lookup in Home, no `\|\|` fallback, no slug-wide helper left behind |
| the render | `design/_session/home_buyer_gate.py` — boots the real server on a throwaway store and drives the real Home page (8.5 s, 14 checks) | scenario A (rank-6 top row, only a rank-0 buyer): **no whisper button, no buyer name, head says "See buyers in Trade", the honest gap stated**, and the session panel agrees; scenario B (that lane's buyer exists): exactly one whisper button, the right name, head says "Open Trade", and the session panel names the same buyer |

**The gate was checked against the regression it exists for:** with the fallback temporarily restored,
the render gate fails **12 of 14** — `the head action says where to look instead` (saw `Open Trade`)
and `the honest gap is stated` (saw the start button where the no-buyer line belongs). The two
whisper-button checks still passed, which is worth stating plainly rather than claiming more: the
whisper row already asked the rule, so the fallback's damage was the card's text and its promise, not
a second send path. The check set catches it either way, and the suite fails if it comes back.

The Windows-only suite now runs 1908 passed / 5 skipped (the two node-dependent checks skip when node
is missing; the browser gate also needs Chrome and puppeteer-core). Both gates re-run after the fix:
stage-10 **PASS 118/118**, workflow **PASS 22/22**.
