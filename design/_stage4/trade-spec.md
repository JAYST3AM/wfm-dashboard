# Stage 4 — Trade rework implementation spec (`#view-trade`)

Source of truth: Jay's brief (Sell / Buy / History; Sell is the primary surface; engine internals
behind a Safety/Advanced layer; nothing removed; dry-run stays locked + honest; card dumps out).
Reads with `design/migration-map.md` §4/§5.6/§7/§8/§10 and `docs/redesign-ia.md` §1–§4.

**Grounding / versions read (2026-09-28 19:10–19:20).** Other agents were editing Home
(`index.html` mtime 19:00, `app.js` 18:34, `style.css` 19:01) while this spec was written. The
`#view-trade` section on disk (lines 191–302) is byte-identical to the stage-1 id snapshot
(`design/_stage1/ids_before.json`: 47 ids + the section id itself). Hashes at read time:
`index.html` `a4387541a7ec76822effd9410aaee753`, `app.js` `17dd70ced243febefd30a9607196b7ff`,
`style.css` `d29dc0f136f6f00666aae7441fdd2026`, `home.js` `feb989ce40130cddcd7f182fbf37be93`.
If a later Home pass renumbers things, trust the id names + renderer names here, not the line numbers.

Counts used below: **cards_mapped = 13** (12 `<div class="card">` blocks inside `#view-trade` +
the `#histKpis` strip). **pins_listed = 27** test functions that reference trade markup ids.

---

## 1. Card inventory — everything in `#view-trade` today

Payload plumbing: `load()` (app.js:894) fetches `/api/trader` → `TRADER` and 25
`/api/feature/<name>` payloads → `FEAT[name]`; renderers are called from `load()` (app.js:919, 933,
1036) — every renderer runs on every load regardless of which tab is visible (hidden panels are
`display:none`, not unrendered).

| # | Card / section | ids | Data shown (endpoint → renderer) | Tab today | Class |
|---|---|---|---|---|---|
| 0 | Tab nav `#tradeTabs` (role=tablist) | `tradeTabs`, `tt-sell`, `tt-buy`, `tt-history` (+ `data-tp`, `aria-controls`) | none — `switchTradeTab()` (app.js:99) + init click handler (app.js:1426 write `#trade/<sub>`) | chrome | chrome |
| 1 | Recommended listings | `planMeta`, `btnPlan`, `btnCycle`, `planList` | `/api/trader` → `plan.plan[]` (`trader_plan.json`): `name, qty, price, est_total, note/subtype, slug`; `planMeta` = `plan.generated` + `plan.mr`. Advisor chip per row from `/api/feature/advisor` (`FEAT.advisor.items[slug]` → `advBits/advNote`). `renderTrader()` (app.js:389–436) | Sell | **decision** |
| 2 | Not recommended right now (`<details id="heldAcc" open>`) | `heldAcc`, `heldMeta`, `heldList` | `/api/trader` → `plan.held_list[]` = `[name, reason]` pairs (15 today) | Sell | **decision** (why it skipped) |
| 3 | Listings needing attention | `attnMeta`, `btnWatch`, `attnList` | `/api/trader` → `undercuts.rows[]` (`order_id, slug, name, lane, my_price, floor, proposed, action, reason`; **0 rows today**) **plus** a hygiene one-liner pushed from `/api/feature/hygiene` `summary{hide,show,refresh,total}` + `rules.auto_hide_offline/offline_window_minutes` (19 today). `renderTrader()` | Sell | **decision** |
| 4 | Listings that haven't moved (`<details id="hygieneAcc">`, nested in card 3) | `hygieneAcc`, `hygieneMeta`, `btnHygiene`, `hygieneList` | `/api/feature/hygiene` (`hygiene_plan.json`): `actions[]` (`action: hide\|show\|refresh, order_id, item, lane, reason`), `summary`, `inputs.entries{live,pending}`, `mode`. `renderHygiene()` (app.js:463–482). Renders `<b>NOT LIVE - plan only</b>` | Sell | **engine internals** |
| 5 | Flip opportunities | `flipsMeta`, `flipsList` | `/api/feature/flips` (`flip_digest.json`): `name, kind, buy_at, sell_at, profit, margin_pct, sales_day, queue_ahead, score_raw`, capped 10. `renderFlips()` (app.js:1087–1104) | Buy | decision |
| 6 | Wishlist — what you're hunting | `wishMeta`, `wishList` | `/api/feature/wishlist`: `summary{budget_available, affordable_subset_cost, trades_needed, buy_now_count}`, `affordable_plan[]`, `wishlist[]` (BUY_NOW ≤6). `renderWish()` (app.js:1120–1139) | Buy | decision |
| 7 | History KPIs (strip, not a card) | `histKpis` | `/api/trades` → `totals{earned, spent, net, sales, purchases, items}`. `renderHistory()` (app.js:328–367) | History | decision |
| 8 | Trade history | `histMeta`, `hFilters`, `tradeLog` | `/api/trades` (`trade_log.json`, **471 events today**, no cap — renders every event). Filters `all/sale/purchase/other` via `hFilter` + `#hFilters button` handler (app.js:1439) | History | decision |
| 9 | Sessions | `sessMeta`, `sessList` | `/api/feature/sessions` (`session_stats.json`): `totals`, `sessions[]` filtered `events>0`, ≤8. `renderSessions()` (app.js:1053) | History | decision |
| 10 | Best time to sell | `timingMeta`, `timingList` | `/api/feature/timing` (`sell_timing.json`): `verdict, verdict_reason, sample, hours[], by_kind, next_window`. `renderTiming()` (app.js:484) | History | decision |
| 11 | Platinum ledger — in-game spend | `ledgerMeta`, `ledgerList` | `/api/feature/ledger` (`plat_ledger.json`): `totals{current_balance, in_game_spent_inferred_plat, trades_earned_plat, reading_days, gap_days}`, `days[]` (≤8 of 53), `self_check.reconciles`. `renderPlatLedger()` (app.js:581) | History | decision |
| 12 | Trade limit | `limMeta`, `limList` | `/api/feature/limits` (`trader_limits.json`): `trade_cap, trades_left, trades_used, reset_melbourne, seconds_until_reset, status, mr_label, account`. `renderLimits()` (app.js:1038) | none (below the tabs) | **engine internals** (the number also shows in the header `#chips` “Trades N/day left”) |
| 13 | Kill switch | `killMeta`, `btnKill`, `killNote`, `killList` | `/api/feature/killswitch` (`kill_switch.json` `active/note/ts`). `renderKill()` (app.js:1172) prints the `ARMED`/`disarmed` chip, the note+ts line and `<span class="dim small explain">Not live</span>` | none | **safety** (must stay) |
| 14 | Notifications — Discord / webhook | `notifyMeta`, `btnNotify`, `notifyList` | `/api/feature/notify` (`notify_outbox.json`): newest 6 rows `{ts,to,title,status}`. **Renders `status` raw — `dry_run` is a legal data value** (5 historical rows today). `renderNotify()` (app.js:568). `btnNotify` POSTs `/api/trader/notify` (“Send test ping”) | none | **engine internals** |
| 15 | Run queue — best buyers | `runqMeta`, `btnRunq`, `runqList` | `/api/feature/runqueue` (`run_queue.json`): `queue[]` `{slug,name,qty,my_price,buyer,buyer_status,buy_price,whisper,why}` capped 10 (8 today), `summary{ingame,online,offline}`. `renderRunQueue()` (app.js:439) | none | **engine internals** |

The four cards 12–15 sit in `<div class="trade-ops">` (12–14, 3-across ≥1200px) + the run-queue card
as a sibling (15). Comment at index.html:268 records the 2026-09-27 decision that internals stay
visible — **stage 4 supersedes that comment**; delete it with the rework.

---

## 2. Target layout

### Tab row
`#tradeTabs` = **Sell · Buy · History · Advanced** (4th button `id="tt-advanced"`
`data-tp="tp-advanced"` `aria-controls="tp-advanced"`). A tab = **one click from Sell**, deep-linkable
(`#trade/advanced` already works: `applyHash()` does `'tp-' + sub`, app.js:128). Keep every existing
`tt-*`/`tp-*` id and `role=tab`/`aria-selected` wiring; `switchTradeTab()` needs no logic change
(it enumerates `#tradeTabs [role="tab"]` and `#view-trade .tpanel`).

### Sell tab (`#tp-sell`) — decision surface, top to bottom
1. **Recommended listings card** — head: title, `#planMeta`, **new honest mode chip `#postMode`**
   (see below), actions `#btnPlan` (“Rebuild recommendations”) + `#btnCycle` (“Check the market
   now”). Body: `#planList` table, unchanged 6 columns (`# / Item / Qty / List at / Est / Notes`),
   `plan.plan` rows fully rendered (no cap — parity rule §5).
2. **Not recommended right now** — `#heldAcc` stays directly under the plan table, **`open` is
   removed** (collapsed by default; “card dumps as one long page are out”). Keep the
   `toggle → markScrollers()` listener (app.js:1431) and the `#heldList` scroller rules.
3. **Listings needing attention** — head: title, `#attnMeta`, `#btnWatch`. Body `#attnList`
   (undercut rows + the hygiene plain-language one-liner). `#hygieneAcc` **leaves** this card.
4. Nothing else on Sell.

**One action per row.** The only per-row affordance that exists in this app is the shared item
drawer: give every `#planList` row and every `#attnList` row `data-slug="<slug>"` (+
`title="Open item"`/existing title) and open `window.wfmOpenItem(slug)` on click — same pattern as
the inventory rows (`tr.inv-row` delegation, app.js:1641–1645, `data-slug` on app.js:746; drawer API
`window.wfmOpenItem`, drawer.js). Both payloads carry `slug` (`plan.plan[].slug`;
`watcher.py` undercut rows write `slug`, `action`, `proposed`). **Do not invent a second button per
row** — no clipboard helper and no per-row POST exists (`/api/trader/{plan,cycle,watch,hygiene,flip,runqueue,notify,settings}` + `POST /api/trades` are per-script, not per-row). The row’s own
text is “what the plan says”: `note`/`subtype` + `advNote(slug)` chip; undercut rows keep
`floor / my_price / proposed / reason` (optionally lead with `r.action` — it is in the payload and
currently unused).

**Honest mode chip (`#postMode`, new id, new element).** In `renderTrader()`:
`const dry = set.dry_run === true || plan.dry_run === true;` (precedent: home.js:361), then render
`Not live - nothing is posted` (dry) / `Live` (not dry), class `chip` (+ `kill-on`-style warning
colour when live). Copy must be ≤8 words (`tests/test_copy_diet.py`) and may never contain
“dry run” (`tests/test_terminology_live_not_live.py`). Data today: `trader_plan.json.dry_run =
true`, `scripts/trader/settings.json.dry_run = true`.

### Buy tab (`#tp-buy`)
Unchanged cards, same order: **Flip opportunities** (`#flipsMeta`/`#flipsList`) then **Wishlist**
(`#wishMeta`/`#wishList`). Nothing moves here; nothing engine-side lives here.

### History tab (`#tp-history`)
Unchanged: `#histKpis`, trade log (`#histMeta` + `#hFilters` + `#tradeLog`), sessions, best time to
sell, platinum ledger. **Decision (ledger): it stays in History** — it is user-facing spend history,
named “History” in `docs/redesign-ia.md` §Trade and it is not on the brief’s internals list. Listed
here as an explicit call so a later reviewer can flip it (moving it needs zero id changes). Note:
`#tradeLog` is uncapped (471 rows today) — the fit rules cap its height only. If it gets a cap,
define the parity check as `min(N, cap)`.

### Advanced tab (`#tp-advanced`) — “Safety & advanced”
One panel, stacked in this order (safety first, then internals; ids unchanged, **markup moves
verbatim**):
1. Kill switch (`killMeta`/`btnKill`/`killNote`/`killList`) — keeps its “Not live” line and the
   single ARMED/disarmed state element (do **not** add a second state surface anywhere; that is
   pinned by `test_kill_switch_has_one_state_element_and_one_note_field`).
2. Trade limit (`limMeta`/`limList`) — full numeral/bar/reset detail; the header `#chips` trader
   chip keeps the one-glance number.
3. Notifications (`notifyMeta`/`btnNotify`/`notifyList`) — webhook outbox + “Send test ping”.
   **Change the cell to a label map**: `sent → sent`, `dry_run/held → “not live”`, `failed →
   failed` (chip colours keep the `act-sent?` logic). Raw `dry_run` must not reach the eye.
4. Run queue (`runqMeta`/`btnRunq`/`runqList`) — the 5-column table stays 5 columns.
5. Hygiene plan (`hygieneAcc`/`hygieneMeta`/`btnHygiene`/`hygieneList`) — the `<details>` moved
   whole (it was already an accordion; it now lives in a tab that is itself 1 click away).
6. Where the posting gate lives: `#postMode` on Sell (0 clicks) + `renderHygiene`’s
   `NOT LIVE - plan only` line + `renderKill`’s `Not live` line (1 click). Settings keeps its own
   non-editable “Posting mode — Not live” pill (`static/settings.js:243`).

**≤1-click rule (pin it in the tests):** from `#trade` on Sell, `#tt-advanced` is one click and
`#tp-advanced` must contain `limList, killList, killNote, btnKill, notifyList, btnNotify, runqList,
btnRunq, hygieneList, hygieneMeta, btnHygiene, hygieneAcc`. No nested accordion around the kill
switch or the limit card; the only `<details>` in the layer is `#hygieneAcc`.

### CSS (style.css) — what the rework must re-author
- Delete/replace the dissolved strip: `.trade-ops` rules (style.css:647–654, 712) and the
  `body.shell-fit #view-trade > .trade-ops { grid-row: 3 }` (style.css:907) plus
  `> .card { grid-row: 4 }` (908) — with the ops cards gone from below the panels, a stale
  `grid-row: 4` child no longer exists and the fit grid must be simplified to the tab row + active
  panel (`body.shell-fit #view-trade { grid-template-rows: auto minmax(200px, 1fr) }` is the
  intent; the executor picks the exact fractions at 1920x1080).
- Keep `#planList/#heldAcc/#heldList/#attnList/#runqList` scroller rules and add equivalents for the
  Advanced panel’s lists (give the panel `overflow-y:auto` sections; `markScrollers()` only ever
  measures `.tablewrap` and `#view-trade .picks`, so every scroll container must keep `class="picks"`
  or `markScrollers()` must be extended in the same commit).
- The Advanced tab must keep the dense row recipe (`#view-trade .prow/.heldline/.limrow/.runrow`,
  `.trade-ops > .card > #limList/#killList/#notifyList` selectors become `#tp-advanced …`).

---

## 3. Handlers — renderer ↔ ids (app.js), and id status

| app.js function | ids it writes/reads | notes |
|---|---|---|
| `renderTrader()` (389) | `planMeta`, `planList`, `heldMeta`, `heldList`, `attnMeta`, `attnList` (all **unguarded**); then calls `renderRunQueue(); renderHygiene(); renderNotify(); markScrollers();` | add `#postMode` here |
| `renderRunQueue()` (439) | `runqMeta` (**guarded**, `if (!m) return`), `runqList` | guarded: drop the meta and the list goes silently blank |
| `renderHygiene()` (463) | `hygieneMeta` (**guarded**), `hygieneList` | prints the `NOT LIVE - plan only` line |
| `renderNotify()` (568) | `notifyList` (**guarded**), `notifyMeta` | status label map goes here |
| `renderTiming()` (484) | `timingMeta` (**guarded**), `timingList` | |
| `renderPlatLedger()` (581) | `ledgerMeta` (**guarded**), `ledgerList` | |
| `renderLimits()` (1038) | `limList`, `limMeta` (**unguarded**) | throws if `limMeta` is removed |
| `renderSessions()` (1053) | `sessMeta` (**unguarded**), `sessList` | |
| `renderFlips()` (1087) | `flipsMeta`, `flipsList` (**unguarded**) | |
| `renderWish()` (1120) | `wishMeta`, `wishList` (**unguarded**) | |
| `renderKill()` (1172) | `killList`, `killMeta`, `btnKill` (**unguarded**) | one state element: `meta.className/textContent`, `btn.textContent` Arm/Disarm, `iconRepaint(btn)` |
| `renderHistory()` (328) | `histKpis`, `histMeta`, `tradeLog` (**unguarded**) | `hFilter` + `#hFilters button` handler at 1439 |
| `bind()` block (1470–1475) | `btnPlan→/api/trader/plan`, `btnCycle→/api/trader/cycle`, `btnWatch→/api/trader/watch`, `btnRunq→/api/trader/runqueue`, `btnHygiene→/api/trader/hygiene`, `btnNotify→/api/trader/notify` (all via `traderAction(id, path, busy)`); `bind('btnKill')` (1477) reads `killNote.value` then POSTs `/api/trader/killswitch` | `bind()` silently no-ops on a missing id → a renamed button becomes a dead button with no error |
| init (1426–1432) | `#tradeTabs [role="tab"]` clicks (writes `#trade/<sub>`), `heldAcc` toggle → `markScrollers()` | |
| `markScrollers()` (836) | `#view-trade .picks` | |
| `showView()` (69) | `#view-trade`, `markScrollers()` when `v==='trade'` | |
| `applyHash()` (109) | `#trade`, `#history|#trader` aliases, `#trade/<sub>` → `tp-<sub>` | `#trade/advanced` needs no change |
| `renderPicks()` (268) | `sellPicks`, `picksMeta` — **not in this view** | leave alone |

**Must survive verbatim (48 ids; `design/_stage1/ids_before.json` + `style.css` + 6 test files key
off them):** `view-trade`, `tradeTabs`, `tt-sell`, `tt-buy`, `tt-history`, `tp-sell`, `tp-buy`,
`tp-history`, `planMeta`, `btnPlan`, `btnCycle`, `planList`, `heldAcc`, `heldMeta`, `heldList`,
`attnMeta`, `btnWatch`, `attnList`, `hygieneAcc`, `hygieneMeta`, `btnHygiene`, `hygieneList`,
`flipsMeta`, `flipsList`, `wishMeta`, `wishList`, `histKpis`, `histMeta`, `hFilters`, `tradeLog`,
`sessMeta`, `sessList`, `timingMeta`, `timingList`, `ledgerMeta`, `ledgerList`, `limMeta`, `limList`,
`killMeta`, `btnKill`, `killNote`, `killList`, `notifyMeta`, `btnNotify`, `notifyList`, `runqMeta`,
`btnRunq`, `runqList`. **Rename none of them** (6 test files + style.css + 15 unguarded
`getElementById` calls); the only new ids are additive: **`tt-advanced`, `tp-advanced`,
`postMode`**.

**Layout-only, free to change:** the `trade-ops` and `trade-split` wrappers and their classes,
`.tpanel`, `.plan-head/.prow/.heldline/.attnrow/.runrow/.runhead/.runwhisper/.limrow/.lim-hero/`
`.limbar/.limmeta/.noteinput/.killline`, the fit grid rows in `body.shell-fit #view-trade`, the
`data-icon` values, and the index.html:268/270 comment block. Any new wrapper must not capture ids
that style.css keys off.

---

## 4. Test pins (27 functions reference trade markup ids)

| File → pin | After the rework it must assert |
|---|---|
| `test_trade_layout.py::test_the_plan_table_and_the_held_panel_share_the_row_height` | new Sell grid still gives `#planList` and `#heldAcc` a shared, stretching row (rewrite the `.trade-split` strings or re-pin the new rules) |
| `::test_the_held_panel_is_open_and_its_list_is_the_scroller` | **superseded**: no `open` attribute; assert `close` by default is a 1-click disclosure, `toggle`→`markScrollers` still bound, `#heldList` is the scroller when open |
| `::test_the_held_summary_sits_on_the_plan_header_line` | keep (or re-pin the new layout); intent = summary is not a 36px stub |
| `::test_the_trade_scrollers_wear_the_dojo_scrolly_cue` | keep `#view-trade .picks.scrolly` recipe; add the Advanced panel’s lists to it |
| `::test_mark_scrollers_toggles_the_trade_lists_too` | keep; confirm the `#view-trade .picks` selector still describes every list (incl. the new panel) |
| `::test_the_notes_column_has_a_real_width_budget` | keep the plan-column budget + `p-notxt`/`advchip` rules (`advNote` must still ride the cell title) |
| `::test_the_three_ops_cards_are_equal_columns_stretched_to_one_height` | **superseded**: no `.trade-ops`; assert the Advanced panel stacks the three cards with equal-width ids present |
| `::test_trade_limit_numeral_is_the_centrepiece` | keep the `lim-hero`/`limbar` markup pin, re-scope the selectors to `#tp-advanced` |
| `::test_kill_switch_has_one_state_element_and_one_note_field` | keep verbatim (one `killNote`, one ARMED/disarmed text state, no second OFF) |
| `::test_notifications_rows_get_an_internal_scroller` | keep, re-scope to `#tp-advanced #notifyList ` |
| `::test_the_run_queue_rows_are_five_fixed_columns` | keep all five cells + sticky head + whisper title (table shape unchanged) |
| `::test_listings_needing_attention_stays_a_compact_aligned_strip` | keep (`attnList` 2-attnrow rule); the hygiene one-liner stays one of the two |
| `::test_every_trade_id_and_control_survives_the_layout_pass` | rewrite the search: `assert id="X" in html` for **all 47** (drop the “inside #view-trade” split — reachability, not placement) + keep the `Sell/Buy/History` tab-name checks |
| `test_trade_density.py::test_plan_and_held_back_share_a_row_from_1500px` | keep or re-pin the new Sell grid at ≥1500px |
| `::test_the_three_short_cards_go_three_across_from_1200px` | **superseded**: assert the Advanced panel lays the three cards out at ≥1200px (or drop) |
| `::test_kill_switch_run_queue_and_notifications_stay_plain_cards` | **re-target (the big one)**: replace “no safety control sits in a `<details>`” with reachability — `#tt-advanced` exists in `#tradeTabs`, one click shows `#tp-advanced`, and every id (`limList killList killNote btnKill notifyList btnNotify runqList btnRunq`) is inside it; kill switch + limit are **not** wrapped in `<details>` (only `#hygieneAcc` is) |
| `::test_plan_held_and_run_queue_rows_are_in_the_dense_budget` | keep the row budgets; keep `.runrow` 5 columns + phone whisper rule |
| `::test_the_notes_column_keeps_its_width_budget_and_the_plan_keeps_six_columns` | keep (6 plan columns, notes flexible) |
| `::test_card_heads_wrap_so_a_narrow_column_never_clips_a_button` | keep (`flex-wrap` in `#view-trade .card-head`) |
| `::test_phones_keep_the_single_column_layout` | keep the ≤560px blocks; add the Advanced panel to them |
| `::test_every_trade_id_and_control_is_still_on_the_page` | same rewrite as its twin: all ids present anywhere in `index.html` |
| `test_density_views.py::test_the_fit_block_comes_after_the_trade_density_block` | keep the ordering invariant, or move it after the new trade block and update the pin |
| `::test_trade_fills_the_window_without_losing_its_own_rules` | **rewrite the grid**: `body.shell-fit #view-trade` now = tab row + active panel; assert each long list (`#planList #heldList #attnList #tradeLog #sessList #timingList #ledgerList #runqList #flipsList #wishList`) scrolls inside its card |
| `::test_every_id_and_control_survives` (`view-trade` tuple) | keep the id tuple verbatim (it is the reachability contract) |
| `::test_the_filter_pills_and_buttons_stay_outside_the_scrollers` | keep: `#btnPlan`/`#btnCycle` in the Sell card head; `#btnKill`/`#killNote` somewhere on the page |
| `test_redesign_ia.py::test_index_has_four_view_sections_and_real_trade_tabs` | keep `tp-sell/tp-buy/tp-history` + `tradeTabs` + `role=tab`; add `tp-advanced`/`tt-advanced`; keep the `details class="acc` shell |
| `test_terminology_live_not_live.py::test_live_wording_survives_the_retired_trader_cards` | keep `'killMeta' in app.js`; add: `#postMode` renders `Not live` and no renderer prints a raw `dry_run` |

Also binding but not id-pins: `test_copy_diet.py` (every new string ≤8 words/90 chars/1 period),
`test_copy_simplicity.py` (BANNED explainer sentences), `test_terminology…::test_no_dry_run_wording_in_the_ui_scripts|pages`
(no “dry run” literal in any new copy — note the current `renderNotify` prints the *data* value
`dry_run`, which the label map must hide).

---

## 5. Risks + acceptance numbers

**Silently-breakable (in priority order).**
1. **Unguarded renderers.** `renderLimits/renderSessions/renderFlips/renderWish/renderKill/renderHistory/renderTrader`
   dereference ids without guards — dropping or renaming any of `limMeta`, `sessMeta`, `flipsMeta`,
   `wishMeta`, `killMeta/btnKill/killList`, `histKpis/histMeta/tradeLog`, `planMeta/planList/heldMeta/heldList/attnMeta/attnList`
   throws inside `load()` and kills every later render on the page. Guarded ones
   (`runqMeta/hygieneMeta/timingMeta/ledgerMeta`) are worse: they **return early and blank the list
   silently**. Rule: keep all 47 ids; if one must move, the renderer moves in the same commit.
2. **`bind()` no-ops on a missing id** → a moved/renamed button stops working with zero console
   output. Keep `btnPlan/btnCycle/btnWatch/btnRunq/btnHygiene/btnNotify/btnKill`.
3. **Fit grid drift.** `body.shell-fit #view-trade` is a 4-row grid (style.css:900–928) whose rows
   point at `#tradeTabs / .tpanel / .trade-ops / .card`. The ops strip leaves that position, so a
   stale `grid-row: 3|4` child silently breaks the window fit at ≥1200px (page scroll or clipped
   card) without any test failing — the current tests pin CSS *strings*, not the measured fit.
4. **`.picks` scroller cue.** `markScrollers()` only measures `.tablewrap` + `#view-trade .picks`;
   a new list without `class="picks"` loses its fade silently (`test_mark_scrollers…` pins the
   selector, not the result).
5. **Plan/payload keys.** `renderTrader` reads `plan.plan[].{slug,name,qty,price,est_total,note,subtype}`
   and `advBits(slug)` → `FEAT.advisor.items[slug]` — no key renames on the server side, no new
   fetch; the advisor chip must keep its `title` (reasons joined).
6. **Not Live honesty.** Three renderer strings carry it: `renderKill`’s `Not live`,
   `renderHygiene`’s `NOT LIVE - plan only`, and the new `#postMode`. Losing all three from Trade
   re-opens the terminology bug the tests exist for.
7. **Run-queue columns / trade-log size.** `.runrow` is 5 fixed columns with a phone rule
   (`.runwhisper { grid-column: 1/-1 }`); `#tradeLog` renders all 471 events (height-capped only).
8. **`data-icon` glyphs.** Static buttons carry `data-icon`; dynamically relabelled ones call
   `iconRepaint()`. New buttons need `data-icon` or they render label-only.

**Acceptance numbers a verifier must check (with today’s data).**
- **Fit:** `pageOverX = pageOverY = 0` and `#view-trade` `secOverX = 0` on **each of the 4 tabs**
  (Sell/Buy/History/Advanced) at five viewports — **1920x1080, 1600x900, 1440x900, 1366x768,
  1280x800** (all ≥1200px so the `shell-fit` regime applies) — plus `overX = 0` at **820x900**
  (the rail-fold measure the stage harness already takes); console errors 0.
- **Reachability:** from `#trade` (Sell default) `#tt-advanced` = 1 click → all 16 Advanced ids
  present and visible; `#killMeta` text ∈ {`ARMED`,`disarmed`}; arming via the UI flips it to
  `ARMED` and the note round-trips through `killNote` (restore `kill_switch.json` to its prior
  value in a `finally`).
- **Parity (row count = data row count):** `#planList` rows = `trader_plan.json.plan.length`
  = **20**; `#heldList` = `held_list.length` = **15**; `#runqList` = `min(queue.length,10)` = **8**;
  `#tradeLog` = events matching the active filter = **471** on `All`; `#attnList` =
  undercut rows + 1 hygiene line = **1** today (0 undercuts + 19 hide summary); `#flipsList` ≤10;
  `#ledgerList` = 1 summary + `min(days,8)` + 1 note = **10** (53 windows).
- **dry_run badge:** with `data/trader_plan.json.dry_run === true` **and**
  `scripts/trader/settings.json.dry_run === true` (both true today), `#postMode` reads `Not live`;
  `renderKill` still prints `Not live`; `renderHygiene` still prints `NOT LIVE - plan only`; **no
  surfaced string matches `/dry[ -]?run/i`** (test_terminology) and the notify chip shows a label
  (`not live`), never the raw `dry_run` status.
- **No id lost:** `design/_stage4/ids_before.json` (copy the `view-trade` block of
  `design/_stage1/ids_before.json`) → run the stage-4 headless probe → every id rendered, 0 missing,
  0 duplicates (reuse the `design/_stage2/verify_ids.py` pattern).
- **Tests:** `pytest tests/test_trade_layout.py tests/test_trade_density.py tests/test_density_views.py
  tests/test_redesign_ia.py tests/test_terminology_live_not_live.py tests/test_copy_diet.py
  tests/test_copy_simplicity.py tests/test_hygiene.py tests/test_runqueue.py tests/test_plat_ledger.py
  tests/test_notify.py tests/test_sell_advisor.py tests/test_sell_timing.py tests/test_flipper.py -q`
  green, with the four superseded pins re-targeted exactly as in §4 (split the byte-stable ones
  rather than deleting them; the migration map §7 requires reachability, not placement).

**Suggested execution order.** (1) app.js: `#postMode` + notify label map + `data-slug` row actions
+ `heldAcc` no longer `open`; (2) index.html: cut the ops strip into `#tp-advanced`, add
`tt-advanced`/`tp-advanced`, drop the stale comment; (3) style.css: re-author the Trade look/fit
block; (4) re-target the 4 superseded pins + extend the id lists; (5) run the trade QA probe + id
verify; write `design/_stage4/qa_trade.json` + screenshots alongside this file.
