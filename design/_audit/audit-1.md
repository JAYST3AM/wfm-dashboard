# Audit 1 — shared app shell (`208cb31`) + navigation rebuild (`cc2f87e`)

Adversarial audit by an independent agent (not one of the builders). Date: 2026-09-28.
Target: what is **committed** and what **the app actually serves** at `http://127.0.0.1:8787`
(static/ is served live from `static/`, data from `data/`). Read-only: no repo writes, no writes to
app data, `dry_run` untouched, no click that mutates state (only theme/sound/localStorage toggles and
in-page navigation).

## Why some things are marked MID-EDIT

`git` was off-limits for this audit, so working-tree state was dated by mtime against the two commit
times (`208cb31` 18:25, `cc2f87e` 19:10):

* **As-committed:** `shell.js` (18:59), `shell.css` (18:46), `cards.html` (18:31), `cards.js`, `theme.js`,
  `sfx.js`, `icons.js`, `lookup.html`.
* **Edited after the commit (cannot be attributed to a landed stage):** `item.js` 19:16, `drawer.js` 19:17,
  `style.css` 19:19, `settings.html/js` 19:20, `item.html` 19:24, `chart.js` 19:27, `index.html` 19:28,
  `collection.html` 19:28, `home.js` 19:28, `collection.js` 19:30, `app.js` 19:31, `home.css` 19:31.

Everything below is measured on the served build; findings that touch a mid-edit file say so.

## Grade summary

| Grade | Count |
|---|---|
| BLOCKER | 0 |
| MAJOR | 1 |
| MINOR | 3 |
| NIT | 5 |

---

## Findings

### MAJOR

**M1 — `aria-current` goes stale on the SPA: after any in-app navigation the rail still announces the
view you *loaded* on (Home by default).** `shell.js` (committed) writes `aria-current="page"` while
mounting, from the hash at parse time (`shell.js:164`, `railHTML()`); nothing ever updates it again —
the only other writers of `aria-current` in the whole tree are `collection.js:768` and `settings.js:568`
(their own sub-navs), and `app.js` `showView()` toggles `.active` only.

Evidence (`design/_audit/nav2.json`), one clean load of `/?fresh=1#home` then real clicks:

| clicked | hash | pill with `.active` | pill with `aria-current` |
|---|---|---|---|
| Trade | `#trade` | trade | **home** |
| Inventory | `#inventory` | inventory | **home** |
| Tools | `#tools` | tools | **home** |
| Home | `#home` | home | home |
| launcher → Ducats | `#tools/ducats` | tools | **home** |

Same-document hash loads behave the same (`/?a=1#home` → `?a=1#trade` leaves aria on `home`);
a **real** document load of `/#trade` is correct (`aria=trade`) — i.e. the defect is the missing
update on hash routing, not the mount logic. `collection.html` / `cards.html` / `settings.html` are
correct because each is its own document (verified: `aria=collection|collection|settings`).
Impact: a screen-reader user on the main page is told "Home, current page" while viewing Trade,
Inventory, Tools or any of the 12 workspaces. The brief's own check list names aria-current, so this
fails a stated acceptance criterion.

### MINOR

**M2 — `/item.html` shows no current location: 0 of 6 rail pills active, no `aria-current`.**
`shell.js` gives the item page `active: ''` (line 57), so the rail renders 6 pills with none marked
(`design/_audit/shell.json` → index/collection/cards/settings all have exactly 1 active + 1 aria-current;
item has `active=[] aria=[]`). You arrive here from the drawer / "full analysis"; the only orientation
is the header's `← Inventory` link.

**M3 — Trade's Notify card clips its own heading between ~1150px and ~1900px (mid-edit file).**
`#notifyMeta` ("· 5 in outbox · 1 delivered (rest held)", itself correct — `notify_outbox.json` has 5
rows, 1 sent) sits in a card whose box is smaller than its content and clips (`overflow-x: hidden`):

| viewport | card width | content needs | clipped |
|---|---|---|---|
| 1024 | 774 | 772 | 0 |
| 1200 | 305 | 514 | **211 px** |
| 1500 | 405 | 514 | **109 px** |
| 1600 | 439 | 514 | **76 px** |
| 1920 | 545 | 543 | 0 |

`index.html` (19:28) and `style.css` (19:19) are both mid-edit, so this is not attributed to stage 1/2 —
but it is what the served app does at common widths. (`design/_audit/_dbg_notifyclip.js`)

**M4 — doc/guard drift between the landed stage-2 map and the served build (mid-edit).**
The map's slug table and §1 say "eleven focused workspaces"; the served app has **12**
(`index.html:384`, `app.js` `TOOL_SLUGS` include `news` → "Game news", renders "Game updates · v44.0.1 ·
checked 25m ago"). Both files are post-commit edits, so this is in-flight work landing without the map.
Related: the stage-2 claim "ids kept — `verify_ids.py` 0 missing vs `design/_stage1/ids_before.json`"
no longer holds on the served build. My independent union check (22 targets, `design/_audit/ids.json`)
finds the DOM missing **5 of 246** snapshot ids: `view-more` (renamed `view-tools`, sanctioned by map §9),
and `homeSync`, `heroCard`, `heroMeta`, `kpiCard` (Home wrappers; map §9 licenses reshaping them for the
Home simplification, stage 3 — `index.html`/`home.js`/`home.css` were edited minutes before this audit).
No *chrome* id was lost on any page (search/chips/sound/theme/mainnav all present).

### NIT

**N1 — `#history` / `#trader` never rewrite the hash** although `app.js` comments promise "the address
always names the surface that is showing" (`#more`, `#market`, `#player`, `#mastery` do rewrite).
Both land correctly (`#history` → Trade *History* tab, 33,249 chars; `#trader` → Trade *Sell*, 4,698 chars).
`app.js:113-119`.

**N2 — theme flash risk, not observable on this box.** The theme is applied by a body-end script while
`:root` ships the dark Vor Orange palette (`style.css:2`, `--bg:#0d0f13`), so on a slow first paint a
light-theme user (30 of the 60 themes are light) could see a dark frame. Measured: **0 wrong frames of
41** sampled per page, inline theme applied at 39–109 ms vs first paint 48–140 ms on all five pages
(`design/_audit/shell.json`). No page has a pre-paint (head) theme apply.

**N3 — dead space where nothing overflows.** Settings' panel is capped at 974 px → 92 / 192 / **512 px**
of unused viewport at 1500 / 1600 / 1920; `collection.html` at 1024 leaves a 179 px right gap (content
492 px wide); index views leave 22 px at every width. Numbers in `design/_audit/deadspace.json`.

**N4 — cards.html keeps its pre-existing blocked CDN art.** 3 requests to
`warframe.market/static/assets/items/images/en/*.png` fail `ERR_BLOCKED_BY_RESPONSE.NotSameOrigin`
(intermittent: 3 in the dedicated console run, 0 in the shell run). Pre-existing, documented in stage 1;
not counted as a defect.

**N5 — `/collection.html#cards` is not a section**: the Cards pill is a real page link (`/cards.html`),
so that hash silently shows the Collection section instead. Nothing blank, but an old-style link lands
on the wrong tab (`design/_audit/nav2.json`, subnav table).

---

## Verified clean (measured, not asserted)

1. **Content parity 12/12 — expected == rendered, every list** (`parity.py` + `qa_parity.js`, source of
   truth per list in `server.py:FEATURES`): deals 14/14, movers 8/8, trends 12/12, rivens 11/11 (8 veiled
   bands + 3 owned), watchlist 7/7 (3 entries + 4 candidates), ducats 16/16 (min(8,29 burn) + min(8,58 sell)),
   craft 12/12, relic EV 12/12, sets 12/12, nudges 10/10, meta 12/12, baro 0 rows → status line (correct:
   `trader.active=false`), player 11 `pc*` ids populated.
2. **The rendered numbers are the payload's numbers, not stale placeholders**: deals heading "389 live in
   12h (88 spreads · 301 undercuts)" == `deals.json counts`; ducats "58 sell (1227p) · 29 burn" == summary;
   sets "5 complete · 9 one away · 24 two away" == summary; meta "6 up / 6 down of 120"; trends "2 spiking ·
   26 fading of 250"; rivens "8 families · 3 owned"; nudges "5 ready · 9 one away"; relic EV "3111p vs 7935p";
   craft "66 craft · 7 buy · 45 skip"; baro status == `trader.status_text`; notify "5 in outbox · 1 delivered".
3. **Server-side transforms behave**: deals payload 60 of 389 rows (`deals_shown`), ducats 25+25 of 94 raw,
   sets drops the 163-row `sets` array, craft caps at 40 non-SKIP, meta 60 — the client renders from exactly
   that, and the count follows.
4. **Shell mounts exactly once, everywhere**: 22 targets (4 index views, 12 workspaces, collection ×3,
   cards, settings, item) → `header=1 .side=1 main=1 #mainnav=1`; `window.wfmShell.mounted=true` at
   `readyState=loading`; `data-shell-actions` is honest (index declares `search syncState refresh png` and
   has all four; the other four declare none and have none) — and no pre-stage-1 chrome id was lost on any
   page (snapshot comparison).
5. **Themes**: 60 = 30 dark + 30 light. 40 applications (8 themes × 5 pages, dark and light spread across
   the palette): body background equals the theme's `--bg` in **40/40**; header, rail pill and cards stay
   themed; **0** elements escaping the vars (0 white-bg-on-dark, 0 black-bg-on-light, 0 white-text-on-light,
   0 dark-text-on-dark); panel opens/closes on all 5 pages with 60 items and filters `All 60 / Dark 30 /
   Light 30`; `shell.css` holds **0 hex/rgb/hsl colour literals** and 42 `var(--…)` uses — the only
   literal colour tokens in it are 5 `color-mix(in srgb, black N%, transparent)` composites for box-shadows
   and the swatch-dot border (theme-independent by design), and 0 elements escaped the vars at runtime.
6. **Persistence across pages**: theme 14 (Frost Light) set through the real panel on index → carried to
   collection/cards/settings/item (`--bg #eef2f7`, `#themeName "Frost Light · light"`, `wfm.theme=14`,
   theme button wired on all five); sound muted the same way → `aria-pressed=false`, `btn icon muted`,
   `window.sfx.enabled=false`, `wfm_sound=off` on all five.
7. **Rail**: 6 entries in the committed order Home/Trade/Inventory/Collection + Tools/Settings, correct
   hrefs on every page (bare `#home…` on index, `/#home…` off it), exactly **1** active pill and **1**
   `aria-current` at load on every destination (`/#home`, `/#trade`, `/#inventory`, `/#tools`,
   `/#tools/<slug>`, `/collection.html`, `/cards.html`, `/settings.html`).
8. **Legacy hashes all resolve, none blank**: `#more`→`/#tools` (launcher, 640 chars), `#market`→`/#tools`,
   `#player`→`/#tools/player` (Player profile workspace, 1,198 chars), `#mastery`→`/collection.html#mastery`
   (mastery view visible, 4,744 chars), `#history`→Trade/History (33,249 chars), `#trader`→Trade/Sell.
9. **Back/forward sane**: `#trade → #inventory → #tools → #tools/deals`; back → `#tools` (launcher, nothing
   hidden), back → `#inventory`, forward → `#tools`; cross-page index → settings → back → `/#home` with
   `view-home` visible. No dead end, no blank view.
10. **Keyboard-only path works**: 11 Tabs on index reach the rail (search, sound, theme, settings, refresh,
    PNG, then the 6 pills); Enter on Tools opens `#tools`; one more Tab focuses the first launcher entry;
    Enter opens `#tools/deals` (workspace visible, heading "Deals", 868 chars). Rail pills show a 2px accent
    focus outline. On collection, 12 Tabs → Mastery pill → Enter → `#mastery` tab visible.
11. **Workspace chrome**: all 12 slugs render `role="region"` + `aria-label` + a unique `.tws-name` heading
    and an "All tools" back link; the launcher round-trip works (12 entries → Deals 14 rows → back → launcher);
    Collection → Cards pill → `/cards.html` → browser back → Collection.
12. **Stage-2's moved surfaces render**: Mastery tab `mhCats` 13 == payload `categories` 13, cap "showing 60
    of 517", `mhHead` "Mastery 22 → 23: 112,500 XP" == `mastery.json` mr; Player workspace `pc*` populated
    (`pcStats` 80 chars, `pcSyn` 511, `pcInt` 125, `pcFocus` 45, `pcMarket` 68, `pcClan` 100).
13. **Edge sizes 820/1024/1200/1500/1600/1920 × 11 targets**: horizontal overflow **0** everywhere
    (`scrollWidth == innerWidth`), elements escaping the viewport **0**, clipped pills **0**; rail folds to a
    full-width 820×55 bar at 820 and is a 206 px sidebar at ≥1024 (nav overflow 0 at every width).
14. **Console/network**: 0 console errors, 0 failed requests, 0 HTTP ≥400 on index (4 views + 6 workspaces),
    collection (3 sections), settings (2 categories), item and lookup. The only failures anywhere are the
    3 pre-existing blocked CDN images on cards (N4).
15. **Regression sweep of the old More page — nothing lost**: all 12 lists exist with data and each is one
    click from the launcher (deals→`#tools/deals`, movers+trends→`#tools/trends`, rivens, watchlist→`wl`,
    ducats, craft, relicEV, sets+nudges→`sets`, baro, meta), and the Setup strip is on the launcher
    (`#setupCard` 145 chars, `#foot` 79 chars) with 12 launcher entries in three groups.

---

## The three things most likely to embarrass us in front of a user

1. **A screen reader says you are on Home when you are anywhere on the main page** (M1) — `.active`
   follows the router, `aria-current` does not, on the page 90% of use happens on.
2. **Trade's Notify card heading is cut off (up to 211 px) at 1200–1600 px** (M3) — a visible truncation on
   a common laptop/external-monitor width, and my best guess is nobody has looked at Trade at 1200 px recently.
3. **`/item.html` gives no "you are here"** (M2): 0 of 6 rail pills marked — follow a drawer link and the
   nav stops telling you where you are. Runner-up: Settings throws away up to 512 px of a 1920 viewport (N3),
   and the served build already differs from the stage-2 map (12 workspaces, 5 snapshot ids gone; M4), which
   will read as breakage to the next reviewer who runs the stage-2 guard.

## Artifacts (all read-only probes; nothing else in the repo was touched)

| File | What it holds |
|---|---|
| `design/_audit/parity.py` / `parity.json` | raw→expected row counts per list (API + raw file) |
| `design/_audit/qa_parity.js` / `parity_dom.json` | rendered rows per list per slug, workspace names, console/net |
| `design/_audit/qa_shell.js` / `shell.json` | theme cycle (40 applications, escapes), flash frames, persistence |
| `design/_audit/qa_shell2.js` / `shell2.json` | theme panel contents, rail/sub hrefs, pill focus outline |
| `design/_audit/qa_console.js` / `console.json` | per-page console errors + failed requests with sources |
| `design/_audit/qa_nav.js` / `nav.json` | rail clicks, legacy hashes, back/forward, keyboard, headings |
| `design/_audit/qa_nav2.js` / `nav2.json` | aria-current truth table (hard loads vs clicks), collection sub-nav |
| `design/_audit/qa_widths.js` / `widths.json` | overflow / escapes / clipped pills per width |
| `design/_audit/qa_deadspace.js` / `deadspace.json` | dead space per page per width |
| `design/_audit/qa_ids.js` / `ids.json` | chrome-declaration audit + id union vs `_stage1/ids_before.json` |
| `design/_audit/qa_flows.js` / `flows.json` | tools round-trip, mastery parity, cards hop |
| `design/_audit/_dbg_aria.js`, `_dbg_trade.js`, `_dbg_notifyclip.js`, `_dbg_home.js` | the specific diagnoses above |
