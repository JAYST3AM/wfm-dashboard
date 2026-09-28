# Stage 4 - Trade: Sell / Buy / History + one Safety & advanced layer (landed)

Jay's brief: *"Trade should be Sell / Buy / History tabs. The sell decision should be the primary
surface. Everything that is engine internals - kill switch, notifications/webhook setup, run queue
internals, hygiene internals, trade limit details - moves behind a Trade Settings / Safety /
Advanced layer. Do not remove safety controls, keep them reachable. dry_run stays locked and
visible somewhere honest. Card dumps as one long page are out."*

Built against `design/_stage4/trade-spec.md`. Nothing was removed: every id, list and control the
app.js renderers reach for is still on the page - the engine internals are one click away.

## What moved where

| Card / control (ids) | Before (stage 3) | After (stage 4) |
|---|---|---|
| Recommended listings - `planMeta`, `planList` (20 rows: #, item, qty, list at, est, notes) | top of the page, above the ops strip | **Sell tab**, same card = the decision surface; every long list scrolls inside it |
| `postMode` (new chip: Not live / Live) | - | added to the Recommended listings card head, beside the counters |
| Not recommended right now - `heldAcc`, `heldMeta`, `heldList` (15) | under the plan table, `open` by default | Sell tab, directly under the plan table, **collapsed by default** (one-line strip: `Not recommended right now · 15`) |
| Listings needing attention - `attnList` (+ its `Check now` button) | Sell surface | Sell tab, below the plan card; a safety/net strip, not a scroller |
| Wishlist / flips - `flipsMeta`, `flipsList`, `wishMeta`, `wishList` | loose on the right of the page | **Buy tab** (same ids, same data, same subheads) |
| History - `kpis`, `histFilters`, `tradeLog`, `sessList`, `timingList`, `ledgerList` | loose down the page | **History tab** (same ids, same data) |
| Kill switch - `killMeta`, `btnKill`, `killNote`, `killList` | ops strip under the panels | **Advanced tab**, first band - a plain card (no disclosure over a safety control) |
| Trade limit - `limMeta`, `limList` | ops strip | Advanced tab, first band, plain card |
| Notifications / webhook - `notifyMeta`, `btnNotify`, `notifyList` | ops strip | Advanced tab, first band, plain card |
| Run queue - `runqMeta`, `btnRunq`, `runqList` | ops strip | Advanced tab, second card (5-column table) |
| Hygiene plan - `hygieneAcc`, `hygieneMeta`, `btnHygiene`, `hygieneList` | Sell surface (a `<details>` in the left column) | Advanced tab, last card - the layer's **only** disclosure |
| Tab row - `tradeTabs`, `tt-sell`, `tt-buy`, `tt-history` (+ new `tt-advanced` / `tp-advanced`) | 3 tabs: Sell / Buy / History | 4 tabs: Sell / **Buy** / History / **Advanced** (Sell is the default panel) |
| Ops-strip wrapper - `.trade-ops` (class, not an id) | full-width strip under the panels | dissolved; the same band is `.adv-cards` inside `#tp-advanced` (3-across >= 1200px) |

One click: `#tt-advanced` sits in `#tradeTabs` next to Sell, its panel is `#tp-advanced`
(`aria-controls`), and the Sell surface carries no engine card at all.

## Honesty of the live/not-live state

`#postMode` is rendered from the config the app already has - `dry_run` from `/api/settings` and
from the trade payload - never hardcoded. Verified by flipping the in-memory config (no fetch, no
write) and re-rendering:

| config | chip | class |
|---|---|---|
| `dry_run = true` (shipped) | `Not live - nothing is posted` | `chip` |
| `dry_run = false` (flipped in memory) | `Live` | `chip kill-on` |
| restored | `Not live - nothing is posted` | `chip` |

The kill switch keeps its own `DISARMED` / `ARMED` chip on the same page, and the notify rows say
`not live` where the outbox refused to send (the words `dry_run` never leak into the Advanced
layer: `raw_dry_run_in_adv=false`).

## Ids

- kept: all 48 ids of the stage-1 `view-trade` block (`design/_stage4/verify_ids.py` -> missing=0,
  dups=0). No id was renamed.
- added: `tt-advanced`, `tp-advanced` (the tab + its panel), `postMode` (the posting-mode chip).
- layout-only class renames: `.trade-ops` -> `.adv-cards` (classes carry no app.js contract).

## Tests

| file | tests now | what changed |
|---|---|---|
| `tests/test_trade_layout.py` | 19 | the ops-strip pins were split, not deleted: 3 tabs + one tablist; the Advanced layer one click from Sell and holding its ids; the sell surface carrying no engine ids; the plan card hugging its rows so `#planList` is the scroller; one action per plan/attention row (`data-slug` -> the shared drawer) |
| `tests/test_trade_density.py` | 8 | the 3-across pin now reads `.adv-cards` (same band, inside `#tp-advanced`); the displaced ops-strip layout pin became **reachability** (`#tt-advanced` in `#tradeTabs` -> `#tp-advanced` -> every internal id; kill/limit/notify are plain cards; the hygiene plan keeps the layer's only `<details>`) |
| `tests/test_density_views.py` | 15 | 2 trade pins re-targeted to `.adv-cards` / the tab-panel trade grid (no test removed) |
| `tests/test_ia_reachability.py` | 20 | +1: `test_the_trade_internals_are_one_click_from_the_sell_surface` (the file's own watch-list item) |

`python -m pytest tests -q` -> **1518 passed, 2 skipped** (HEAD was 1511 + 2; +7 new trade tests).

## Verified (headless Chrome, read-only clicks)

- `design/_stage4/qa_trade.js` (re-runnable, writes `qa_trade.json` + the four shots):
  - tabs: exactly **1** visible panel per tab; Sell is the default; 0 console errors.
  - parity vs raw data: plan **20/20** rows (`data/trader_plan.json`), held **15/15**, run queue
    **8/8**, notify outbox **5/5**, history log **471/471**, attention **1/1**; `dry_run` still
    `true` in the rendered chip.
  - fit: page over / horizontal overflow **0** on home, trade (all four tabs), inventory and tools
    at 1920x1080, 1536x864, 1366x768, 1280x800.
  - advanced layer clip measurement (heading content vs card box) at 1024 / 1200 / 1366 / 1600 /
    1920: `0/0` for every card - the 1200-1600px notify-heading clip from the audit is gone
    (the head wraps now instead of being cut by `overflow-x: hidden`).
  - every trade card: `scrollHeight == clientHeight` on all four tabs at all four viewports, i.e.
    no card is squeezed below its content (a short window shrinks the list, which scrolls).
- screenshots (1920x1080, `C:/Users/jayde/AppData/Local/Temp/shotkit/shots/`):
  `s4-trade-sell.png`, `s4-trade-buy.png`, `s4-trade-history.png`, `s4-trade-advanced.png`
  (+ `s4-trade-sell-held.png` with the held panel open), each read back with a vision pass and
  clean: no hole between the plan table and the held strip, 6 columns x 20 rows, the Not-live chip,
  the attention card; Advanced shows Kill switch / Trade limit / Notifications across one line with
  full single-line headings, the run queue, and the collapsed hygiene strip.

## Unfixed / notes

- The Platinum ledger's 40vh scroller shows a partial row at its boundary when scrolled to the top;
  it carries the `.scrolly` fade cue (as do all long trade lists), so the boundary reads as "more
  below" rather than a cut. Not a clip - `scrollHeight` fits the card.
- `Sync failed` in the header is the app's own data-sync state (no WFM credentials in this
  profile), not a layout issue.
- One transient `favicon.png ERR_CONNECTION_REFUSED` appeared in a single early probe run and never
  reproduced (favicon serves 200); the console is clean (0 errors) on every run since.
