# Stage 3 — Trading Session front end (built, 2026-09-29)

What this stage added, and the decisions a later reader would otherwise have to re-derive. The
backend (`scripts/trade_session.py`, `server.py`) and `tests/test_trade_contact.py` belong to the
other workstream and were not touched here.

## What shipped

| Piece | File | Notes |
|---|---|---|
| Tab + panel | `static/index.html` | `tt-session` / `tp-session`, FIRST in the strip; `tp-sell` is still the one panel that ships visible |
| Renderer | `static/session.js` (new) | `renderSession()` owns the whole panel; loaded BEFORE `app.js` like `home.js`, because `load()` and the router both call it while `app.js` is still parsing |
| Styles | `static/session.css` (new) | scoped to `#tp-session`, layout only, no new colours |
| Shared wiring | `static/app.js` | +`'session'` in `load()`'s feature fan-out, +`renderSession()` beside `renderNextAction()`, +`if (panelId === 'tp-session') renderSession();` in `switchTradeTab` (read on open, never a timer), +`${sessionHomeAction()}` in the Next-action footer, `ordWhisper()` now returns sent/not-sent and takes `data-item` |
| Tests | `tests/test_trade_session_panel.py` (new) | tab/panel, route, no-own-fetch, no timer, no confirm control, copy diet, why-fact honesty |
| QA gate | `design/_stage10/gate.js` | `#trade/session` state (deep-link + placement checks), `trade/session` in the fit and theme matrices, and `snapIds()` — the duplicate-id rule the audit found unchecked everywhere |

## Decisions worth keeping

- **Session is first, Sell stays selected.** The loop is the primary job (doc §1) but the plan is
  still the decision surface, so only the strip order moved. Two pins state this on purpose:
  `tests/test_trade_layout.py` (`TRADE_IDS` + the tablist test, 5 → 6) and
  `tests/test_trade_orders_tab.py` (Orders is now the *second* button; the renamed test asserts
  Session < Orders < Sell instead of "Orders is first").
- **One send path.** A session row renders the book's own `.ordrow` / `.ordwsp` markup and calls the
  existing `ordWhisper(btn)`. It carries `data-item` because `ORD.slug` is the book's last-read slug,
  not the session row's item. The status-chip filter inside `ordWhisper` is now scoped to
  `#tp-orders`: it gates the book's rows, and a session row's buyer must not be silently refused by
  a filter the panel does not show.
- **No `POST /api/session/contact`.** A whisper that really sent is already recorded server-side as
  CONTACTED; the panel only re-reads afterwards. It shows the send answer in the row's `.ordres`,
  and carries it across the refresh it just triggered via `SESSION_SAY`.
- **Reconciliation is stage 5.** There is no confirm/reconcile route, so the panel ships no control
  that would call one: the hook is a comment in the markup where the Confirm control goes. Pending
  trades are shown (name, rank, qty, buyer, expected plat, how old) and marked `old` past the
  server's staleness window — never auto-resolved.
- **Start trading is Home's footer line**, not a seventh card (the Home band is pinned as exactly
  six). It stays at the quiet button weight; the card keeps its one accent action.

## Verified here, not by the gate

`python -m pytest tests -q` → **1793 passed, 5 skipped** (baseline 1780 + these 13, 0 failed).

Two probes were run outside pytest (both throwaway, in the agent scratch dir) and are worth
re-running if the panel is touched again:

1. `session_route_proof.js` — lifts the REAL `switchTradeTab()` out of `app.js` and drives it with
   the REAL `applyHash()` mapping against a stub DOM built from `index.html`: `#trade/session` →
   `tp-session`, shown alone, `renderSession()` called once; `#trade/nope` → the documented `tp-sell`
   fallback. PASS.
2. `session_render_probe.js` — loads the REAL `session.js` with the REAL helpers lifted from
   `app.js` against the REAL `/api/session` payloads (the live one built by the engine in an
   isolated copy of the store). Both states paint correctly: 12 suggestions + Start when no session
   is open, and with a session open a 4-KPI band, the focus card (name, R0, copies, price, a 7-span
   why line with the confidence reasons in the title), the book's whisper row for the buyer with
   `data-item` set, 6 queue rows and the honest pending empty line. PASS.

**Not run here:** the puppeteer gate (`node design/_stage10/gate.js`, needs the live app + Chrome).
It is the integration agent's job; the harness change is in, but the gate has not been executed
against this branch, so the fit/theme/console checks for `#trade/session` are still unproven.
