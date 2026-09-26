# WFM Trader — frontend IA redesign

Audited 2026-09-26 by a 5-agent swarm (feature inventory, nav/tests, settings, language,
UI/a11y) against the then-current UI. Goal: **complex backend, simple frontend.** No backend
feature is deleted or made unreachable; only the default surface changes.

## 1. Primary navigation (5 items)

| Pill | Target | Contents |
|---|---|---|
| **Home** | `/#home` | "What should I do today?" actions (advisor-driven), platinum summary, alerts, recent activity, platinum chart, game updates |
| **Inventory** | `/#inventory` | Owned items, simple default columns, one shared item drawer |
| **Trade** | `/#trade` | Tabs: Sell · Buy · History · Advanced (collapsed) |
| **Collection** | `/collection.html` | Progress, sets, relics; sub-tab **Cards** (`/cards.html`) |
| **More** | `/#more` | Market tools in intent groups, Settings, links |

Lookup stops being a destination: the header search is the universal item lookup and opens the
shared drawer on any page. `/lookup.html` becomes a redirect stub to `/#search` (query preserved).

## 2. Feature placement (audit: 90 surfaces, 18 unreachable risks — all placed)

**Home** — Today block (advisor `recommendation='list'`, score-sorted, `List Y × Zp` dominant,
"Potential platinum" total, expandable to 30 rows), keep/set + ducats + open-relic one-liners,
alerts (listings needing attention, Baro, kill switch, Not live), recent trades + session,
existing KPI row + platinum chart + game updates. *Removed: the old "Top sell picks" card
(superseded by Today).*

**Inventory** — category tabs, totals, table with default columns `Item · Qty · Equipped ·
Safe to sell · Sell price · Value`; an "All columns" toggle reveals `Category · Ducats ·
Buyer offering · Profit gap · Sales / 48h · Typical price · Reserved`. Row click opens the
drawer. *Removed: the inline row drilldown (drawer replaces it).*

**Trade** — *Sell*: recommended listings (plan + rebuild/check buttons), not-recommended
collapsed, listings needing attention (undercuts + stale, plain wording), trade limit.
*Buy*: wishlist, flip opportunities. *History*: trade log + filters, sessions, sell timing,
platinum ledger, history KPIs. *Advanced (collapsed, second accordion)*: engine status,
detector output, run queue, flipper internals, listing hygiene (raw), raw outputs (last
action stdout/stderr), kill switch, notifications. All engine names survive here.

**Collection** — unchanged content; sub-tabs Collection | Cards; Cards keeps its 3D/full-art work.

**More** — *Make platinum*: deals, movers, demand trends (flips → Trade > Buy).
*Item decisions*: ducats vs sell, craft vs buy, relic EV, set completion, near-complete nudges.
*Tracking*: watchlist (wishlist → Trade > Buy). *Special markets*: rivens, Baro, post-patch meta.
Plus Settings + links (Collection, Cards).

## 3. Progressive disclosure (everywhere)

- Layer 1 — **what to do** (`List 2 × 55p`) dominates.
- Layer 2 — **why** (`You own 3 · 1 equipped · demand high`) small, inline.
- Layer 3 — **advanced** (order book, lanes, raw statistics, engine outputs) behind
  expandables/tooltips, never as default copy.

## 4. Language map (audit: 140 strings)

| Now | Default surface | Tooltip / advanced keeps |
|---|---|---|
| wts / lane ask | Sell price (your rank) | "lowest ask at your rank" |
| wtb / lane bid | Buyer offering | "top bid at your rank" |
| vol48 / 48h vol | Sales / 48h | vol48 |
| spread | Profit gap | spread |
| median | Typical price (context) | median |
| detector / run detector | (advanced) Detector | as-is |
| run queue — best buyers | (advanced) Run queue | as-is |
| listing hygiene | listings needing attention / "haven't moved in N days" | hygiene |
| buy plan — flipper | Flip opportunities / (advanced) Flipper | as-is |
| undercut watch | "Someone listed X Np below you" | undercut |
| held back | not recommended right now | held-back rows |
| engine settings, JSON file names, consumed_by, host/port | (nothing) | Advanced settings |
| dry_run | "Posting mode: Not live — nothing is posted to warframe.market until turned on" | — |

Precise trader terms remain reachable in hover tooltips and the Advanced sections.

## 5. Shared item drawer (new: `static/drawer.js` + `drawer.css`)

One component, opened from search, inventory rows, home actions, collection rows.
Ported from the retired lookup detail panel: name + chips, Layer-1 recommended action,
owned block (owned/equipped/reserved/safe to sell), market tiles, rank order book with
"your copy" highlight and list/bid action chips, estimate sentence, image zoom, wfm link.
Expandables: Market details · Collection & sets · Advanced. Dialog a11y: focus trap, Esc,
backdrop close, focus restore, scroll lock. `window.wfmOpenItem(slug|name)`.

## 6. Global search

Header search on the home app: matches owned items (`/api/items`) + the full WFM catalogue
(new tiny `GET /api/catalog` from the cached v2 dump) so unowned items resolve too. Results
open the drawer; owned rows carry an "owned" badge. `/#search?q=…` deep link; `/lookup.html`
redirects here. Keyboard `/` focuses it.

## 7. Accessibility / theming must-fixes (audit)

- `<nav aria-label>` + `aria-current="page"` on the active pill; nav wraps at narrow widths
  (fixes measured 382–437px overflow on index/settings).
- Theme panel moves into each page's `<header>` (it rendered off-screen on 4 pages);
  `aria-expanded`/`aria-controls` on the theme button, Esc closes.
- Tabs get `role=tablist/tab/tabpanel` + `aria-selected`; accordions `aria-expanded` +
  `role=region`; drawbg gets a focus trap; table gets caption/scope; status text gets
  `aria-live`.
- Colours only via theme vars on new surfaces; the cards inspect overlay keeps its
  deliberate fixed light-on-dark hexes.

## 8. Implementation map

`index.html` + `app.js` + `style.css` (views/tabs/accordions/search/labels) · `drawer.js/.css`
(new) · `home.js/.css` (new) · `collection.*` + `cards.*` (nav/sub-tabs/drawer hooks — audit
flagged: keep cards.html standalone so only nav tests re-point) · `settings.*` (grouped rewrite)
· `lookup.html` (stub) · `server.py` (+`/api/catalog`, remove nothing) · tests updated to the
5-pill contract.

## 9. Acceptance (spec §Deliverable)

Full test suite green; every primary nav destination loads; item search resolves owned and
unowned items into the drawer; ranked-mod pricing still shows lane data; advisor
recommendations still render on Home; light + dark themes pass; ≤430px viewport usable;
no backend feature unreachable (compare against the §2 placement table).
