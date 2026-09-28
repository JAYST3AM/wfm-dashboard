# WFM Trader — frontend migration map (internal)

Source: Jay's restructure brief (2026-09-28). Base commit: `cae3bd3` (rail + Home clean pass 1).
Rule: complex backend, simple frontend. Nothing user-facing may become unreachable.
This file is the working map for the staged rebuild — update it as stages land.

---

## 1. Current user-facing destinations

| Where | What |
|---|---|
| `index.html` `#home` | Home (29 ids): hero, alerts, KPI strip, sell-next, chart, news, today, recent |
| `index.html` `#inventory` | Items table + tabs + tools (29 ids): totals, tbl, materials, dojo, invdiff |
| `index.html` `#trade` | 47 ids: tradeTabs (Sell/Buy/History) + 12 cards (plan, attention, hygiene, flips, wishlist, history, sessions, best-time, ledger, limit, kill, notify, run queue) |
| `index.html` `#mastery` | Mastery helper (12 ids): card, next, filters, categories |
| `index.html` `#player` | Player (11 ids): stats, syndicates, intrinsics, focus, market, clan |
| `index.html` `#more` | 12 tool lists (25 ids): deals, movers, trends, ducats, craft, relicEV, sets, nudges, watchlist, rivens, baro, meta + setup |
| `collection.html` | Collection grid + relics (`relicView`) + Cards subnav (28 ids) |
| `cards.html` | Full TCG/card workspace (20 ids) |
| `settings.html` | 5 setting cards, each save/list/status (36 ids) |
| `item.html` | Full item analysis: pick, chart, trades, stats (25 ids) |
| `lookup.html` | Stub — search moved (no ids) |

## 2. Major UI surfaces

Cards in each view as audited (see §1 ids). Item detail has TWO surfaces: the shared drawer
(`drawer.js`, quick) and `item.html` (deep). Trade holds both the sell workflow AND engine
internals. Settings is all-cards-at-once.

## 3. Duplicate information surfaces

- **Platinum**: hero + KPI strip + chart + footer.
- **Trades-left**: header chip + hero meta + KPI strip.
- **Credits**: hero meta + KPI strip (header chip already retired in clean pass 1).
- **Sync/refresh state**: page head ("Synced Nm ago") + header `#syncState` + footer line.
- **Shell chrome**: header/nav/theme/sound/search re-declared in 5 pages independently
  (`index`, `collection`, `cards`, `settings`, `item`) → layout drift.
- **Market surfaces**: Trade "Flip opportunities" vs Tools "Deals" vs "Movers"/"Demand trends".
- **Item detail**: drawer vs `item.html` (roles must be stated, not merged).

## 4. Misplaced features

| Feature | Today | Belongs |
|---|---|---|
| Mastery helper | own rail view | Collection |
| Player profile | own rail view | Tools → Player Profile |
| Clan Dojo (+rooms) | Inventory card | Tools |
| Inventory changes | permanent Inventory card | Inventory → history disclosure |
| Kill switch / Notify / Run queue / Trade limit / Hygiene internals | Trade cards, same visual weight as the sell list | Trade → Safety / Advanced |
| Cards | standalone primary page | Collection workspace (stays rich) |
| 12 analysis tools | one giant More page | Tools launcher → focused workspaces |

## 5. Features moving destination

1. `#mastery` markup + renderer → `collection.html` (tab: Mastery); ids `mh*` kept.
2. `#player` markup + renderer → Tools workspace "Player Profile"; ids `pc*` kept.
3. `#more` tools → Tools launcher (`Tools → Trading / Planning / Warframe` groups) with each
   tool opening its own focused workspace; list ids `dealsList…metaList` kept.
4. `dojo*` ids → Tools workspace "Dojo".
5. `invdiff` (Inventory changes) → disclosure inside Inventory.
6. Trade internals (`lim*`, `kill*`, `notify*`, `runq*`, `hygiene*`, `btnPlan/btnCycle` engine bits)
   → Trade → Safety/Advanced panel; still one tap from the Sell surface.
7. Chat rail → collapsible (keep local store + relay behaviour).
8. `lookup.html` stub → keep as redirect (it forwards to search) or fold into Tools.

## 6. Shell / header / nav duplication

Five pages define their own: header brand+chips, search box, sound button, theme button+panel
(+60-theme grid), settings link, sync state, refresh, mainnav, and inline `<style>`. Shared JS
already exists (`adv.js`, `sfx.js`, `theme.js`). Plan: one `shell.js` + `shell.css` renders the
chrome from a single source; pages declare `data-shell="<active>"` and provide content only.
Keep ids the shared scripts and app.js already use (`mainnav`, `chips`, `search`, `soundBtn`,
`themeBtn`, `themePanel`, `themeName`, `themeGrid`, `syncState`, `refresh`).

## 7. Tests pinning obsolete layout structure

`tests/test_density_views.py`, `test_mod_cards.py`, `test_player_page.py`, `test_redesign_ia.py`,
`test_trade_density.py`, `test_trade_layout.py`, `test_ui_polish.py` (7 files, of 76).
Per spec: re-target these to feature reachability (feature + destination + navigation + responsive
usability + safety behaviour), not card placement. Keep the fit/density measurements where they
still describe real constraints; update selectors as views move.

## 8. IDs / hooks to preserve (functional)

`mainnav`; shell: `chips`, `soundBtn`, `themeBtn`, `themePanel`, `themeName`, `themeGrid`,
`syncState`, `refresh`; search: `search`, `searchDrop`; draw: `drawer*` (drawer.js);
trade: `tradeTabs`, `tt-*`, `tp-*`, `plan*`, `held*`, `attn*`, `hygiene*`, `flips*`, `wish*`,
`hist*`, `sess*`, `best*`, `ledger*`, `lim*`, `kill*`, `notify*`, `runq*`, `btnPlan`, `btnCycle`,
`btnWatch`, `btnHygiene`; inventory: `tabs`, `totals`, `invQ`, `btnCols`, `tbl`, `rows`, `status`,
`mat*`, `dojo*`, `invDiff*`; mastery: `mh*`; player: `pc*`; tools lists: `*List`/`*Meta` (12);
home: `homeAlerts`, `kpis`, `sellNextList`, `platChart`, `newsList`, `homeToday`, `histList`;
collection: (collection.js ids); cards: (cards.js ids); settings: `h-*`, `btnSave-*`, `list-*`,
`status-*`; item: `ip*`; chat: `chatDock`, `chatRows`, `chatForm`, …; export: `btnExportPng`.

## 9. IDs / hooks that can change

Layout wrappers introduced by clean pass 1 (`homeHead`, `homeSub`, `homeDate`, `heroCard`,
`heroMeta`, `kpiCard`, `homeSellNext`, `sellNextMeta`, `alertsCard`, `chartCard`…) are free to be
reshaped for the Home simplification; their tests get rewritten in the same stage.
`view-more` → `view-tools` (label + id) once Tools lands, tests updated.

## 10. At-risk-of-unreachable (watch list)

1. The 12 More-page tools when More becomes a launcher — each needs a real workspace.
2. Trade engine internals once behind Safety/Advanced (must stay 1 tap from Sell).
3. `item.html` reachability from the drawer ("Open full analysis").
4. `cards.html` from Collection.
5. Mastery's filters/categories when ported.
6. Settings categories when shown one at a time (all 5 → 6 categories reachable).
7. `lookup.html` (stub) — keep a redirect.
8. Player's Market/Clan cards when Player moves under Tools.
9. Chat behaviour when collapsible (local store + relay + fit()).
10. PNG export + day-plan actions after the Trade rework.

---

## Staging (spec order)

| # | Stage | Owner now |
|---|---|---|
| 1 | Shared app shell (shell.js + shell.css) across all pages; functionality unchanged | **LANDED this wave** |
| 2 | Primary nav rebuild: Home/Trade/Inventory/Collection … Tools/Settings; Mastery→Collection; Player→Tools; More→Tools | next wave |
| 3 | Home simplification (today / next action / sell queue / alerts / recent; chat collapsible) | next wave |
| 4 | Trade rework (Sell/Buy/History) + Safety/Advanced panel | next wave |
| 5 | Inventory simplification (Items/Materials, column disclosure, dojo→Tools, history disclosure) | later |
| 6 | Collection consolidation (Collection/Relics/Mastery/Cards) | later |
| 7 | Tools workspaces | later |
| 8 | Settings navigation (one category at a time) | later |
| 9 | Drawer vs full analysis normalisation | later |
| 10 | Responsive + polish pass | last |

### Stage 1 landed (2026-09-28) — how the chrome works now

- `static/shell.js` (194 lines) is the one source of the chrome: it renders `<header>` (brand,
  `#chips`, `#search`/`#searchDrop`, `#soundBtn`, `#themeBtn` + `#themePanel`/`#themeName`/
  `#themeGrid`, the pager link, `#syncState`, `#refresh`, `#btnExportPng`) and the rail
  (`<aside class="side" aria-label="Primary"> > <nav class="mainnav sidenav" id="mainnav">` with the
  7 `.navpill`s, active + `aria-current="page"`). `window.wfmShell` exposes `PAGES`, `RAIL`, `mount`,
  `actions` and `mountedAt` for tests/QA.
- A page opts in with `<body data-shell="index|collection|cards|settings|item" data-shell-actions="…">`
  and one `<script src="/shell.js"></script>` (classic, not defer — it mounts during parse, before the
  page's own scripts look their hooks up). `data-shell-actions` is the honest per-page list of
  optional header actions: index `search syncState refresh png`, the other four none.
- `static/shell.css` (242 lines) holds the chrome rules moved out of `style.css` (953 lines left,
  was 1128). No colour literal in it — every colour is a `var(--…)` from the 60 themes.
- Per-page chrome markup is gone from index/collection/cards/settings/item (each keeps its content,
  scripts, `.mainnav.subnav` sub-nav inside `.shellcol`, and footer). `lookup.html` has no chrome.
- The theme panel wiring stayed where it was (app.js / settings.js / collection.js+cards.js via
  `wfmInitThemeUI`), each raising `window.wfmThemeUI`; `shell.js` completes the wiring for a page
  that has none — which is how item.html's previously inert Theme button now opens the panel.
- Regression guard: `tests/test_app_shell.py`; the pinned layout tests now read the shell registry
  (`conftest.rail_rows()`, `conftest.shell_decl()`).

Non-negotiables (spec): backend, user data, safety behaviour, dry_run / Not Live, kill switch,
calculations, rank-aware pricing, collection/relic/mastery/cards data, multi-account, themes,
global search, item drawer, deep analysis, relevant tests.
