# WFM Trader — Trading Session Workflow

You own the WFM Trader repo: `JAYST3AM/wfm-dashboard`.

## Goal

Turn the existing trading features into a cohesive end-to-end **Trading Session** workflow.

The app already has the pieces:
- Home recommendations / Next Action
- Trade > Sell recommendations
- Trade > Orders live order book
- rank-aware pricing
- inventory / safe-to-sell counts
- Warframe.market buyer/seller usernames
- Whisper button that can send the WFM message into Warframe
- platinum history
- inventory change detection
- trade history / ledger
- sessions
- alerts / undercuts / stale listings
- AlecaFrame save reading
- existing QA / test infrastructure

Do **not** build another disconnected tool.

The objective is to connect these systems into this loop:

**RECOMMEND → FIND BUYER → WHISPER → COMPLETE TRADE IN WARFRAME → DETECT INVENTORY/PLATINUM CHANGE → ASK USER TO CONFIRM → LOG TRADE → UPDATE PROFIT / SESSION / INVENTORY → MOVE TO NEXT BEST TRADE**

The app should start feeling like a Warframe trading workstation rather than a collection of dashboards.

---

## 1. Build Trading Session mode

Create a Trading Session workflow inside Trade.

Primary entry points:
- Home > Next Action
- Home > Sell Queue
- Trade > Sell
- optionally a prominent **Start Trading** action

Starting a session should create a queue from the existing sell recommendations.

Each active trade should have one focused surface showing:

### Item
- item name
- rank if applicable
- copies owned
- safe-to-sell quantity

### Price
- recommended sell price
- current lowest sell
- highest live buy order
- recent median / typical price if useful

### Buyer
- best currently relevant buyer
- username
- reputation
- status: ingame / online / offline
- quantity wanted
- offered platinum

### Action
- Whisper
- Open live orders
- Skip
- Hold
- Mark completed manually

Do not overwhelm this screen with analytics. Deep analytics already exist elsewhere.

The Trading Session screen exists to answer:

> What do I do right now?

---

## 2. Connect recommendations directly to live buyers

Home and Trade recommendations should no longer stop at:

> Sell X for 70p

Where live buyer data exists, show something like:

```text
Primed Continuity
Recommended: 74p
Best buyer: 71p
Status: In game

[Whisper buyer] [View orders]
```

Use the existing Orders / rank-lane infrastructure.

Do **not** duplicate order-book logic.

The same source of truth must power:
- Trade > Orders
- Trading Session
- Home buyer information
- item quick look where relevant

Ranked mods must remain rank-aware.

Never pair a rank-10 owned item with a rank-0 buyer/order by mistake.

---

## 3. Whisper → pending trade state

When the user successfully clicks Whisper from a Trading Session, mark that trade as something like:

**CONTACTED**

Store enough information locally to reconcile it later:
- item slug
- display name
- rank
- quantity
- expected platinum
- buyer username
- timestamp
- inventory count before
- platinum before if available

Do not automatically mark it sold just because a whisper was sent.

Possible states should stay simple, e.g.:
- READY
- CONTACTED
- POSSIBLE MATCH
- COMPLETED
- SKIPPED
- HELD

Avoid turning this into an enterprise state machine.

---

## 4. Automatic trade reconciliation

This is one of the most important pieces.

Use the data WFM Trader already reads from AlecaFrame / save snapshots.

Example:

```text
Before:
Primed Continuity rank 10 = 3 safe copies
Platinum = 1,220

After:
Primed Continuity rank 10 = 2
Platinum = 1,294
```

Likely result:
- 1 Primed Continuity sold
- +74 platinum

Then show a non-destructive confirmation:

```text
Looks like you sold Primed Continuity (Rank 10) for 74p.

[Confirm trade]
[Not this trade]
[Edit]
```

Never silently create the final trade record from inference alone.

The user gets final confirmation.

Matching should consider:
- expected item
- expected rank
- expected quantity
- inventory delta
- platinum delta
- timestamp proximity
- pending/contacted trades

If exact matching is not possible, present the evidence rather than guessing.

Example:

> Inventory decreased by 1 but platinum change does not match the expected 74p.

Let the user resolve it.

---

## 5. Confirm → update everything once

When the user confirms a detected/manual trade, one transaction/event should update all relevant local systems.

It should:
- append trade history
- update platinum ledger
- update session earnings
- update sales count
- clear/complete the pending trade
- remove or reduce that queue item
- update inventory-derived state
- update Home Today metrics
- update Recent activity
- update recommendation state
- advance the Trading Session to the next item

Do not have separate buttons that make the user manually update four places.

There must be one canonical trade-completion path.

Make it idempotent.

Double-clicking, refreshing or retrying must not duplicate a trade.

Give completed trades a stable local ID.

---

## 6. Session summary

Trading Session should maintain a simple live summary:

- Platinum earned
- Trades completed
- Session duration
- Trades remaining today
- Queue remaining

Optional but useful:
- average platinum / trade
- skipped / held count

At session end show something like:

```text
SESSION COMPLETE

6 trades
428p earned
1h 12m
71p average

Highest sale:
Primed Continuity — 105p
```

Do not turn this into another giant analytics dashboard.

---

## 7. Explain recommendations

Recommendations should gain a small progressive-disclosure **Why?** control.

Example:

```text
WHY THIS TRADE?
- 3 safe copies
- 11 sales in 48h
- 4 buyers online
- 74p recommended
- current median 72p
- price +8% this week
```

Use existing data wherever possible.

Do not invent fake precision.

If data is missing, omit that reason.

Optionally derive a simple recommendation confidence:
- High
- Medium
- Low

But only if the confidence can be explained from real factors.

Do not produce an unexplained magic score like `87/100`.

---

## 8. Home should become more actionable

Keep the simplified Home philosophy.

Home still answers:
- What should I sell?
- How much?
- Who wants it?
- How much have I made?

But the Next Action card should now be actionable.

Preferred shape:

```text
NEXT ACTION

Primed Continuity — Rank 10

Recommended       74p
Best live buyer   71p
Demand            High
Safe copies       3
Buyer             ExampleUser • In game

[Whisper buyer]
[Start trading]
[Details]
```

Do not add extra Home cards unless genuinely necessary.

---

## 9. First-run / data-build experience

The first setup can take a while.

Do not make the app appear dead during the initial build.

Expose build progress to the UI.

Something along the lines of:

```text
Setting up WFM Trader

✓ Inventory loaded
✓ Player data loaded
● Market prices        63%
● Collection           41%
○ Trading advice
○ Relic analysis
```

Usable parts of the application should become available as soon as their data exists.

Do not fake percentages if the scripts cannot report real progress.

If exact percentage is not available, use truthful states:
- Waiting
- Running
- Complete
- Failed

with useful detail.

---

## 10. Architecture pass

Before piling this workflow into `static/app.js`, inspect the current JS structure.

`app.js` is already very large.

Keep vanilla JS.

Do **not** introduce React/Vue/Svelte or a build framework.

But split responsibilities where sensible.

Potential structure:

```text
static/
  trade.js
  trade-session.js
  inventory.js
  tools.js
  api.js
  state.js
```

This exact structure is not mandatory.

Choose boundaries based on the actual code.

Requirements:
- don't rewrite working code for aesthetics
- don't create abstractions with no payoff
- don't break existing deep links
- don't duplicate API calls unnecessarily
- keep `shell.js` as the shared shell source
- keep existing drawer/full-analysis relationship

Also inspect `server.py`.

If the new workflow would make `server.py` substantially harder to maintain, extract logical route/service modules without turning the app into a framework project.

---

## 11. Data safety

This application deals with inventory and trade history.

Be conservative.

Requirements:
- atomic JSON writes
- preserve previous data on failure
- stable IDs for trade records
- idempotent confirmation
- never infer a completed trade without asking
- never delete trade history to resolve conflicts
- pending state must survive browser refresh/restart
- session should survive accidental refresh/restart
- stale pending trades should be recoverable

Keep the existing dry-run / trader safety behaviour intact.

Do not introduce automatic WFM listing/posting as part of this work.

Whispering a user is allowed because that functionality already exists.

---

## 12. UX rules

Follow the redesign direction already used in the app:
- decision first
- details second
- progressive disclosure
- short copy
- no repeated metrics
- no giant walls of cards
- one obvious primary action
- advanced engine details stay under Advanced
- no feature duplication

The Trading Session should be usable by somebody who does not understand the internal trader engine.

Use normal player language.

Prefer:

> Whisper buyer

instead of:

> Execute buyer contact action

Prefer:

> Looks like this trade completed

instead of:

> Inventory delta reconciliation candidate detected

---

## 13. Tests

This needs serious tests because it touches money/history/inventory state.

Add tests for at minimum:
- start trading session
- queue generation
- ranked item matching
- whisper → CONTACTED
- persistence across reload
- inventory delta detection
- platinum delta detection
- exact reconciliation
- ambiguous reconciliation
- rejected reconciliation
- manual completion
- confirmation
- trade ID idempotency
- duplicate confirmation protection
- history update
- ledger update
- session totals
- queue advances after completion
- session resume after restart
- no mutation from read-only routes
- malformed/partial state files
- no existing trade/history regression

Extend the browser QA gate to cover:

`#trade/session`

or whatever final route you choose.

Test at the existing viewport/theme matrix.

No horizontal clipping.
No console errors.
No duplicate IDs.
No broken legacy navigation.

---

## 14. CI

Inspect the existing GitHub Actions workflow.

If practical, add the browser/UI acceptance gate or a meaningful subset of it to CI.

Do not make CI depend on:
- a real Warframe install
- the user's AlecaFrame cache
- personal data
- credentials
- a live whisper into Warframe

Use fixtures/mocks for those boundaries.

---

## 15. Implementation order

Do this in stages.

### Stage 1
Audit current trade/recommendation/order/session/history/inventory architecture.

Write a short internal implementation map before changing code:
- existing source of truth for each dataset
- reusable components
- duplicated logic to avoid
- files to change
- data schema needed for pending/session state

### Stage 2
Implement persisted Trading Session + queue.

### Stage 3
Wire live buyers and Whisper into session/Home recommendations.

### Stage 4
Implement inventory/platinum reconciliation.

### Stage 5
Implement canonical Confirm Trade transaction.

### Stage 6
Session summary + recommendation Why?

### Stage 7
First-run build progress.

### Stage 8
Architecture cleanup only where justified by the landed implementation.

### Stage 9
Full regression / browser / theme / viewport / accessibility audit.

Commit coherent stages separately.

---

## Definition of done

I should be able to:

1. Open WFM Trader.
2. See my best thing to sell.
3. Click Start Trading.
4. See the first recommended item.
5. See a real buyer currently online/in game.
6. Click Whisper.
7. Complete the trade inside Warframe.
8. Return to WFM Trader.
9. See:

   > Looks like you sold X for Y platinum.

10. Click Confirm.
11. Have the app automatically:
    - log the trade
    - update profit
    - update today's earnings
    - update session stats
    - update inventory
    - move to the next trade
12. Repeat without manually jumping around the application.

That loop is the priority.

Do not spend this implementation round adding unrelated Tools, themes, card features, charts, game information or novelty features.

First inspect the actual current repository and reuse what is already there.

You own the implementation decisions.

Use agent swarm where useful for:
- architecture audit
- backend/session state
- reconciliation engine
- frontend workflow
- adversarial QA

But keep one agent responsible for final integration so separate agents do not build competing sources of truth.

When finished, report:
- what changed
- architecture decisions
- new persisted state/schema
- exact trading flow
- reconciliation rules
- tests added
- test/gate totals
- remaining weaknesses
- what you recommend building next
