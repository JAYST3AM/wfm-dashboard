# UX pass 2 — WFM Trader, 2026-09-29 (second pass)

**Brief (Jay):** Git pull first. Make the trading path obvious and fast — Home → Session → buyer →
confirm. Simplify Trade navigation without removing features. Improve hierarchy, spacing, labels,
empty/loading states and action prominence. Keep advanced/safety/history reachable but out of the
primary flow. Do not redesign working parts for aesthetics.

**Method.** Reviewed the fresh-load screens again, then built the view the real store never shows:
`design/_session/`-style throwaway data, a booted server, a started session, a sent whisper and a
raised check — then looked at the panel mid-loop (`ux_live_review.py` + `ux_live.js`, scratch, not
committed). Everything below came out of that review. The mid-loop screen is where the friction was.

## What the review found

**1. The accent "Start trading" button survived the whole session.** A specificity bug, not a logic
bug: `renderSession()` called `classList.toggle('hidden', !!P.live)`, but `#tp-session .sess-start`
(id + class) outranks the bare `.hidden` class, so `display: none` lost to `display: flex`. The
loudest, only saturated control in the panel advertised *start* while a session was running and a
sale was waiting to be logged. Measured mid-loop before the fix: `start_visible: true`.

**2. The loop's only real action was the last thing on the page.** With a check raised, the panel
read Session → Queue → Waiting → Checks: the Confirm sat at y≈803, under two cards that describe
what already happened. Measured mid-loop: Checks card top 691, Confirm top 803.

**3. The focus card kept offering a first whisper.** After the whisper went out the buyer row still
said **Whisper**, identical to before the send — the answer to "did I send it?" was only in the queue
chip and the pending list.

## What changed

| # | Change | Why |
|---|---|---|
| 1 | `#tp-session .sess-start.hidden { display: none; }` in `session.css`, with the trap named in a comment | the Start control now actually steps aside the moment a session is live — one accent action per state, which was the whole point of the previous pass |
| 2 | The Checks card is re-parented to sit directly under the session card **when it has a proposal**, and returns to the end when nothing is waiting | a raised check is the loop's only action; it now leads the page instead of trailing it. Checks top **691 → 421**, Confirm **803 → 533** |
| 3 | An exact check's Confirm takes the accent weight and says the money: **Confirm 144p** (from the canonical `trade.total`); an ambiguous one keeps the quiet weight and "Looks right" | the click that ends the loop is not a quiet little button, and "Confirm" alone asked the user to re-read the row to find out what they were confirming. Ambiguous stays quiet on purpose: it is a judgement, not a confirmation |
| 4 | The focus card's buyer row says **Whisper again** (and carries `data-sent`) once the row's state is CONTACTED | the row's own state answers "did I send it?", and the second send is still one click — no capability removed |
| 5 | `#sessionQueueCard` id + `start_visible` in the workflow gate's snapshot | the queue card is the re-parent anchor, and the gate now reads **rendered visibility** of the start box rather than the class the renderer meant to add — the class check is what let bug 1 through |

## Deliberately not touched

The tab strip (Session / Orders / Sell / Buy / History / Advanced) — Session, Orders and Sell are
pinned in that order by the IA tests, Advanced is a pinned one-click safety surface, and the strip
already reads as one row with the primary four first. The header cluster (search, Theme, Settings,
Auto sync, Refresh, PNG) is dense but every control there is a deliberate one-click tool; moving it
would be redesign for its own sake. The duplicated item name across focus/queue/waiting/checks is the
loop's own shape — each card answers a different question about the same item, and the *action* is
what had to be singular.

## Evidence

* **Live mid-loop, before → after:** `start_visible` true → **false**; Checks card top 691 → **421**;
  Confirm top 803 → **533**; buyer row "Whisper" → **"Whisper again"**; Confirm label → **"Confirm 144p"**.
* **Suite:** 1912 passed, 5 skipped (was 1908 — the four new pins below).
* **Stage-10 gate:** PASS — 118 checks, 0 failed, 37 page states driven.
* **Workflow gate:** PASS — **23 of 23** (was 22; new check: *"the Start control steps aside once a
  session is live"*, plus the load check now asserts rendered visibility).

## New pins (`tests/test_trade_session_panel.py`)

* `test_the_start_box_really_hides_when_a_session_is_live` — the id-scoped hidden rule exists.
* `test_the_check_comes_up_when_it_is_the_only_action` — re-parented on a proposal, back to the end
  when nothing is waiting.
* `test_an_exact_check_is_the_one_accent_action_and_an_ambiguous_one_stays_quiet` — exactly one accent
  among the checks, the amount on the button, the judgement left quiet.
* `test_the_focus_card_says_when_it_already_whispered_this_buyer` — the CONTACTED row offers a second
  send with the word for it.
* The workflow gate's new mid-loop check is the rendered guard for the whole class of bug 1: a hidden
  state that a stronger selector silently cancelled.
