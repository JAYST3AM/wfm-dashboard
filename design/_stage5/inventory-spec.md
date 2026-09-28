# Stage 5 — `#view-inventory` implementation spec

Executable spec for the Inventory rework. Nothing here is speculative: every id, function and CSS
rule below was read from the files on disk.

**State at read (index.html + app.js are being edited by the Home clean pass right now, so re-check
before editing):**

| file | sha256 (first 16) | mtime |
|---|---|---|
| `static/index.html` | `e051f87afed4ce8d` | 2026-09-28 19:00 |
| `static/app.js` | `a64252a4dd70871d` | 2026-09-28 18:34 |
| `static/style.css` | `a50f83d73ad97f5fd` | — |

`#view-inventory` is `static/index.html` lines 88–188 (comment on line 88, `<section id="view-inventory" class="hidden">` on line 89).

Jay's brief (verbatim intent): basic inventory info only, no explanations, no advanced clutter —
Items / Materials, advanced columns behind a progressive-disclosure control, changes not a permanent
card (button or drawer), Clan Dojo → Tools, the item drawer stays (it is not a destination).

---

## 1. Card inventory — what is in `#view-inventory` today

| # | Section / card | ids today | Filled by (payload → renderer) | Verdict |
|---|---|---|---|---|
| 1 | Section wrapper | `view-inventory` | `showView()` (`app.js:69`) toggles `.hidden`; `VIEWS = ['home','inventory','trade','tools']` (`app.js:58`) | **keep** (id verbatim) |
| 2 | Category pills `<nav id="tabs" class="tabs" aria-label="Item categories">` (line 90) | `tabs` | no fetch — `renderTabs()` (`app.js:657`) paints `CATS` (`app.js:22`: all / prime_part / prime_bp / relic / arcane / mod / other) and filters `ITEMS` via `state.tab` in `rowsFiltered()` (`app.js:664`) | **keep**, moves inside the Items subview (it is an items filter) |
| 3 | `.tablebar` (line 91, class only) | `totals` (92), `invQ` (93), `btnCols` (94) | `#totals` ← `renderTable()` (`app.js:765`); `#invQ` handler `app.js:1580` → `state.q`; `#btnCols` handler `app.js:1647-1653` → `document.body.classList.toggle('show-a')` | **keep** all three ids; `#btnCols` moves behind the new disclosure (see §2) |
| 4 | Items table `.tablewrap > table#tbl > tbody#rows` (96–119, `<caption>` line 98) | `tbl`, `rows` | `renderTable()` (`app.js:733`) from `ITEMS` = `GET /api/items` (`app.js:897`); Trend cell ← `state.itemhist` = `/api/feature/itemhist` (`app.js:910`); Equipped/Safe/Reserved ← `FEAT.advisor` = `/api/feature/advisor` via `advOf`/`advField`/`safeOf` (`app.js:224, 701, 706`) | **keep**; the 14-column head splits into basic + advanced (§2) |
| 5 | Status line `<div id="status" class="status">` (120) | `status` | `load()` (`app.js:935`) writes `prices updated … · checked …` from `/api/summary` (`lastdata_mtime`, `prices_mtime`) | **keep** (id snapshot + fit CSS). Duplicated by the footer/`#syncState` — out of scope for this stage |
| 6 | `.inv-lower` band wrapper (121, class only) + `.invpanels` (122, class only) | *(none)* | pure layout: `style.css:450` `.invpanels { display:grid; grid-template-columns: 1fr 1fr }`, `style.css:808-821` the fit band | **delete** both wrappers (classes are free; nothing in the id snapshot names them). Their CSS must be re-pointed, not dropped (§2/§6) |
| 7 | `<div class="card" id="matCard">` Materials (123–148) | `matCard`, `matMeta`, `matQ`, `matView`, `matSort`, `matTbl`, `matHead`, `matRows`, `matCap` | `state.materials` = `/api/feature/materials` (`app.js:913`); `matRowsFiltered()` (`app.js:781`) + `renderMaterials()` (`app.js:800`), `MAT_HEADS` (`app.js:776`), `MAT_CAP = 400` (`app.js:774`); handlers `app.js:1582-1590` (`#matQ`, `#matSort`) and `app.js:1622-1635` (`#matView` pills, `localStorage['wfm.matView']`) | **keep**, becomes the **Materials** subview (`#invMaterials`) |
| 8 | `<div class="card" id="dojoCard">` Clan Dojo (149–181) | `dojoCard`, `dojoTitle`, `dojoMeta`, `dojoTier`, `dojoTbl`, `dojoRows`, `dojoNote`, `dojoRooms`, `dojoRoomsMeta`, `dojoRoomsList`, `dojoSrc` | `state.materials.dojo` (same single `/api/feature/materials` fetch); `renderDojo()` (`app.js:847`), `paintDojoTier()` (`app.js:1598`), `dojoTierLabel()` (`app.js:1592`); handlers `app.js:1597-1618` (`#dojoTier`, `localStorage['wfm.dojoTier']`) | **move to Tools** as workspace slug `dojo` (§4) |
| 9 | Inventory changes `<div class="card">` (183–186, **no id on the card**) | `diffMeta` (184), `diffList` (185) | `FEAT.invdiff` = `/api/feature/invdiff` (`app.js:908`); `renderDiff()` (`app.js:1069`) | **move behind a disclosure** inside the Items subview (§2); never a permanent card |

Notes that must not be "fixed" on the way through:

- No id beginning `invDiff` exists in the code. Migration-map §8's `invDiff*` is loose naming; the
  real ids (and the stage-1 snapshot) are `diffMeta` + `diffList`.
- `CATS` has no `prime_set` pill, but `/api/items` rows do carry `cat: 'prime_set'` (3 rows today).
  Pre-existing; leave it.
- `<th>` click-to-sort is wired **globally** — `document.querySelectorAll('thead th')` (`app.js:1654`)
  with `if (!k) return;`. The Trend header carries no `data-k`. Any new table inside this view must
  keep `data-k` off its headers or it will hijack the items sort.
- The Drawer (`static/drawer.js`) is untouched by this stage. It is the item detail surface and
  exposes `window.wfmDrawer = { open, close, isOpen }` (`drawer.js:1025`) — the probe reads `isOpen()`.

---

## 2. Target layout

```
#view-inventory
├── nav#invViews            class="tabs" role="tablist"   ← Items | Materials   (NEW, free id)
├── div#invItems            role="tabpanel"  (no .hidden)
│   ├── nav#tabs            the 7 category pills (verbatim id/class)
│   ├── div.tablebar        #totals · #invQ · details#invAdv { summary "Columns" + button#btnCols }
│   ├── div.tablewrap > table#tbl > tbody#rows          (14 columns, 10 of them .hide-a)
│   ├── div#status
│   └── details#invDiff     class="acc sub"  summary "Inventory changes" + span#diffMeta
│       └── div.card#diffCard > div.picks#diffList
└── div#invMaterials        role="tabpanel" class="hidden"
    └── div.card#matCard    (moved whole, all 9 ids verbatim)
```

**Subviews.** `nav#invViews` uses the shipped `.tabs` / `.tab` recipe (same class contract as `#tabs`
and `#tradeTabs`). Markup:

```html
<nav id="invViews" class="tabs" role="tablist" aria-label="Inventory sections">
  <button class="tab active" role="tab" data-v="items" aria-selected="true">Items</button>
  <button class="tab" role="tab" data-v="materials" aria-selected="false">Materials</button>
</nav>
```

`switchInvView(v)` mirrors `switchTradeTab(panelId)` (`app.js:99`): clamp `v` to `['items','materials']`,
toggle `.hidden` on `#invItems` / `#invMaterials`, set `aria-selected`, remember in
`localStorage['wfm.invView']` (same pattern as `wfm.matView`), then call `markScrollers()`.
`state.invView` (default `'items'`) is added next to the other keys at `app.js:13`.
Optional deep link (recommended, one line): in `applyHash()` add
`if (v === 'inventory') switchInvView(sub || state.invView);` — `#inventory/materials` then works,
same mechanism as `#tools/<slug>`; bare `#inventory` still lands on Items.

**Tablebar.** Unchanged except the third control: `#totals`, `#invQ`, then

```html
<details class="acc sub" id="invAdv">
  <summary data-icon="columns">Columns</summary>
  <button class="btn" id="btnCols" aria-pressed="false" aria-controls="tbl"
          title="Show or hide the advanced columns" data-icon="columns">Show advanced columns</button>
</details>
```

- The disclosure control is **`details#invAdv`** (house pattern `details.acc.sub`, already used by
  `#heldAcc` and `#dojoRooms`); the switch inside it stays **`button#btnCols`** — same id, same
  handler (`app.js:1647`), same `body.show-a` contract. Only its label changes
  (`'Show advanced columns'` / `'Hide advanced columns'`, replacing `'All columns'` / `'Fewer columns'`)
  and it is no longer always on screen. Keep the `iconRepaint(btnCols)` call.
- The switch lives in `.tablebar`, so it never scrolls with the rows
  (`test_the_filter_pills_and_buttons_stay_outside_the_scrollers`).

**Items table columns** — 14 columns in the DOM, order frozen (header and cells are positional):

| # | Column | `data-k` | Class today | Band |
|---|---|---|---|---|
| 1 | Item | `name` | `.name` | **basic** |
| 2 | Qty | `count` | `.num` | **basic** |
| 3 | Sell price | `wts` | `.num` | **basic** |
| 4 | Trend (sparkline) | *(none)* | `.spark` | **advanced** — new `.hide-a` |
| 5 | Value | `value` | `.num v` | **basic** |
| 6 | Equipped | `equipped` | `.num` | **advanced** — new `.hide-a` |
| 7 | Safe to sell | `safe` | `.num` | **advanced** — new `.hide-a` |
| 8 | Category | `cat` | `.num hide-a` | advanced (already) |
| 9 | Ducats | `ducats` | `.num hide-a` | advanced (already) |
| 10 | Buyer offering | `wtb` | `.num hide-a` | advanced (already) |
| 11 | Profit gap | `spread` | `.num hide-a` | advanced (already) |
| 12 | Sales / 48h | `vol48` | `.num hide-a` | advanced (already) |
| 13 | Typical price | `median` | `.num hide-a` | advanced (already) |
| 14 | Reserved | `reserved` | `.num hide-a` | advanced (already) |

Mechanism is unchanged: `.hide-a { display: none; }` + `body.show-a .hide-a { display: table-cell; }`
(`style.css:369-370`). Adding `.hide-a` to a column means **both** the `<th>` in `index.html` and the
`<td>` in `renderTable()`'s template (`app.js:745-761`) — hide them in the same edit or the columns
misalign. `colspan="14"` in the empty state (`app.js:763`) stays 14 (cells are still in the DOM).
`advField()`/`safeOf()` keep feeding 6 and 7 from `FEAT.advisor` — hiding a column does not remove
the advisor read, and `state.sort` still accepts `equipped`/`safe`/`reserved`.

Recommended basic/advanced split (10 advanced): as tabled above. If a smaller basic set is wanted,
move Qty or Value into `.hide-a` the same way — never delete a `<td>`, the order is positional.

**Row anatomy** — unchanged and load-bearing: one `tr.inv-row[data-slug]` per stack, written by
`renderTable()`; the click handler is `document.getElementById('rows').addEventListener('click', …)`
(`app.js:1641-1645`) → `window.wfmOpenItem(tr.dataset.slug)`. Footer/chrome inside the row: the rank
chip `span.lane-tag` (rank-lane pricing) and `span.cat` in the Category cell.

**Where the two moved pieces land**

- Dojo → Tools workspace `dojo` (§4).
- `details#invDiff` at the bottom of **#invItems**, below `#status`: `<summary>Inventory changes
  <span class="dim small" id="diffMeta"></span></summary>` + `<div class="card" id="diffCard"><div
  class="picks" id="diffList"></div></div>`. `renderDiff()` is not touched — it reaches `#diffList`
  and `#diffMeta` by id, and works while collapsed exactly like `#dojoRooms` does today. The new
  `#diffCard` id is free (no snapshot claim). No `drawer.js` change.

---

## 3. Handlers + ids

| Part | Renderer / handler (all `static/app.js`) | ids the JS reaches for |
|---|---|---|
| Category pills | `renderTabs()` 657, `state.tab` in `rowsFiltered()` 664 | `tabs` (via `.tab[data-k]`) |
| Items rows + totals | `renderTable()` 733; load order 917 | `rows`, `totals` |
| Items filter | `app.js:1580` (`#invQ` → `state.q`) | `invQ` |
| Advanced-columns switch | `app.js:1647-1653` (`body.show-a`, `aria-pressed`, label swap, `iconRepaint`) | `btnCols` |
| Page status line | `load()` 935 | `status` |
| Materials table | `matRowsFiltered()` 781, `renderMaterials()` 800, `MAT_HEADS` 776, `MAT_CAP` 774 | `matMeta`, `matRows`, `matHead`, `matCap` |
| Materials tools | `app.js:1582-1590` (`matQ`, `matSort`), `app.js:1622-1635` (`matView` pills, `wfm.matView`) | `matQ`, `matSort`, `matView` |
| Dojo | `renderDojo()` 847, `paintDojoTier()` 1598 (called from `load()` 916 and the tier handler), `dojoTierLabel()` 1592, handlers 1597-1618 (`wfm.dojoTier`) | `dojoTitle`, `dojoMeta`, `dojoRows`, `dojoRooms`, `dojoRoomsMeta`, `dojoRoomsList`, `dojoSrc`, `dojoTier` |
| Inventory changes | `renderDiff()` 1069, called from `load()` 933 | `diffList`, `diffMeta` |
| Row → drawer | `app.js:1641-1645` | `rows` (delegated on `tr.inv-row[data-slug]`) |
| Scroller cue | `markScrollers()` 836 (all `.tablewrap` + `#view-trade .picks`); called 918 + resize/`ResizeObserver` 923-931 | — |

**Ids that must survive verbatim** — the 30 stage-1 snapshot ids in this view
(`design/_stage1/ids_before.json['index']`): `view-inventory`, `tabs`, `totals`, `invQ`, `btnCols`,
`tbl`, `rows`, `status`, `matCard`, `matMeta`, `matQ`, `matView`, `matSort`, `matTbl`, `matHead`,
`matRows`, `matCap`, `dojoCard`, `dojoTitle`, `dojoMeta`, `dojoTier`, `dojoTbl`, `dojoRows`,
`dojoNote`, `dojoRooms`, `dojoRoomsMeta`, `dojoRoomsList`, `dojoSrc`, `diffMeta`, `diffList`.
Pinned by `tests/test_density_views.py::test_every_id_and_control_survives` (22 of them),
`test_ia_reachability.py::test_no_id_from_the_stage1_snapshot_disappeared` (all 30) and
`design/_stage2/verify_ids.py`.

**Ids that are layout-only and free** — everything introduced by this stage: `invViews`, `invItems`,
`invMaterials`, `invAdv`, `diffCard` (and any `dojoBox`-style wrapper inside the new workspace). They
may be renamed as long as the test pins in §5 name them once. `tbl` is CSS-only (`getElementById('tbl')`
appears nowhere) but is still snapshot-pinned — keep it.

**Free classes** (no id, no snapshot): `.inv-lower`, `.invpanels` — both wrapper classes should go.
`matCard`'s inner classes (`mat-head`, `mat-tools`, `matview`, `matwrap`, `mat-cap`, `mat-row`,
`dobadge`…) and the dojo's (`dojowrap`, `dojo-note`, `dojo-src`, `dojo-row`, `rcosts`) stay as they are;
several are pinned by the materials/dojo panel tests.

---

## 4. Dojo move — `Clan Dojo` → Tools workspace slug `dojo`

1. **Slug registry**: `static/app.js:67` `TOOL_SLUGS = ['deals','trends','rivens','wl','ducats',
   'craft','relicev','sets','baro','meta','player']` → append `'dojo'` (last, matching launcher order).
2. **Launcher entry** in the `Warframe` group (`static/index.html`, after the `player` entry, before
   `</div>` of the third `.tl-group`, line ~377):
   ```html
   <a class="tool" href="#tools/dojo" data-tool="dojo">
     <span class="tool-name" data-icon="castle-turret">Clan Dojo</span>
     <span class="tool-sub">Build costs and shortages</span>
     <span class="chev" data-icon="caret-right" aria-hidden="true"></span>
   </a>
   ```
3. **Workspace wrapper** inside `#toolsWs`, after the `player` workspace, same shape as every other
   workspace (the `data-tool` attribute must sit on the wrapper tag — `test_ia_reachability.workspaces()`
   regexes the first `data-tool="([a-z]+)"` of each `<div class="tws hidden" id=…` chunk):
   ```html
   <div class="tws hidden" id="tws-dojo" data-tool="dojo" role="region" aria-label="Clan Dojo">
     <div class="tws-bar">
       <a class="tws-back" href="#tools" data-icon="arrow-left">All tools</a>
       <span class="tws-name">Clan Dojo</span>
     </div>
     <div class="tws-body cols-1">
       <!-- the whole #dojoCard block (index.html 149-181) moves here verbatim -->
     </div>
   </div>
   ```
4. **Ids travel with the markup** — all 11 `dojo*` ids are looked up by `document.getElementById`
   in `renderDojo()`/`paintDojoTier()`/the tier handler, so moving the markup needs **no renderer
   change**. `load()` already calls `paintDojoTier(); renderDojo()` on every page load (line 916-917),
   and `renderDojo()` returns early only when `#dojoRows` is absent. Do not rename the wrapper to
   `tws-dojo`'s twin `#view-player`-style id: unlike the player workspace (which kept `#view-player`),
   the dojo had no view wrapper, so `tws-dojo` is the honest new id.
5. **Router** — nothing to add: `showTool(slug)` (`app.js:85`) iterates `TOOL_SLUGS` by
   `[data-tool="<slug>"]` and `#tools/dojo` resolves through `applyHash()` → `showView('tools','dojo')`.
   Add one hook so the moved card's scroller cue is honest:
   `if (slug === 'dojo') markScrollers();` next to the existing `if (slug === 'player') renderPlayerPage();`.
   Optional legacy alias (mirrors `#player`): `if (v === 'dojo') { location.replace('#tools/dojo'); return; }`
   in `applyHash()` plus `dojo: 'tools'` in both `VIEW_ALIAS` (`app.js:60`) and shell.js's `ALIAS`
   table (`static/shell.js:74`) — the two tables are pinned in step.
6. **Player clan link**: `app.js:1294` currently renders
   `<a class="movedlink" href="#inventory">Dojo materials →</a>` in `renderPlayerPage()`'s clan card.
   Re-point it to `href="#tools/dojo"` (pinned by `tests/test_player_page.py:158`).
7. **CSS that must follow the card** (it is scoped to the inventory panels today):
   - `style.css:464` `.invpanels .tablewrap { max-height: 420px; }` → `#matCard .tablewrap { … }`
   - `style.css:466-467` `#dojoCard details.acc …` — keyed on `#dojoCard`, travels fine
   - `style.css:468` `.invpanels .dojowrap { max-height: 320px; }` → `#dojoCard .tablewrap { … }`
   - `style.css:446` `.invpanels .card-head { padding-bottom: 10px; }` →
     `#matCard .card-head, #dojoCard .card-head { … }`
   - `style.css:450-451` `.invpanels { … }` / `.invpanels > .card { margin-bottom: 0; }` → delete
   - `style.css:480-481` the `@media (max-width: 1040px) { .invpanels { … } }` single-column rule →
     delete (materials is one column now)
   - Fit block: add `body.shell-fit #tws-dojo > .tws-body > .card > .tablewrap { flex: 1 1 auto; min-height: 0; }`
     and `body.shell-fit #tws-dojo #dojoNote { flex: 0 0 auto; overflow: visible; }` — the generic
     `body.shell-fit .tws-body > .card > div[id]` rule (`style.css:884-886`) would otherwise make
     `#dojoNote` the scroller. `#dojoRooms` keeps a bounded height:
     `body.shell-fit #tws-dojo #dojoRooms { flex: 0 1 auto; min-height: 0; max-height: 45%; overflow-y: auto; }`
     (inherited from the deleted `.inv-lower #dojoRooms` rule).
   - `body.shell-fit .inv-lower {…}` / `… > .invpanels { display: contents; }` / `… .tablewrap` /
     `… #matCap, … .dojo-note, … .dojo-src` / `… details.acc > summary` (`style.css:808-821`) are
     deleted; the parts still needed move to the new parents (`#invMaterials`, `#invDiff`, `#tws-dojo`).
   - Shrink guards (`style.css:932-946`): replace `.inv-lower #matCap` → `#invMaterials #matCap`,
     `.inv-lower #dojoRooms` → `#tws-dojo #dojoRooms`, `.inv-lower #diffList` → `#invDiff #diffList`
     (plus `overflow-y: auto` on it), `.inv-lower .tablewrap { min-height: 56px; }` →
     `#invMaterials .tablewrap { min-height: 56px; }`.
8. **`tests/test_ia_reachability.py` update** (this is the reachability guard for the move):
   - `WORKSPACES` (line 40): append `('dojo', ['dojoCard'])` — or list the ids that must render, e.g.
     `['dojoTbl', 'dojoRows']`; whatever is chosen must exist inside the workspace block.
   - `GROUPS` (line 54): `'Warframe': ['baro', 'meta', 'player', 'dojo']`.
   - `test_the_launcher_groups_the_tools_trading_planning_warframe`: `launcher.count('class="tool"') == 11` → `12`.
   - `test_every_tool_slug_has_a_launcher_entry_and_a_workspace`: `assert slugs == SLUGS` still holds
     if `TOOL_SLUGS` order matches `WORKSPACES` order; the `data-tool="player"` count assertion (`== 2`)
     is unaffected; `INDEX.count('class="tws-back" href="#tools"') == len(SLUGS)` in
     `test_every_tool_list_id_is_still_rendered_by_its_workspace` becomes 12 automatically once the
     wrapper ships.
   - Add a positive assertion that the dojo left Inventory: `'id="dojoCard"' not in` the
     `id="view-inventory"`…`</section>` slice (today `test_materials_panel`/`test_dojo_panel` assert
     the opposite — see §5).
   - If the `#dojo` alias is added, `test_legacy_hashes_resolve_to_the_new_destinations` gains
     `"dojo: 'tools'"` (app.js + shell.js) and `"location.replace('#tools/dojo')"`.

---

## 5. Test pins referencing inventory markup

Every pytest test/assertion that reads inventory markup, plus the two QA probes. "After" = what it
must assert once stage 5 lands. `pins_listed = 37` rows.

| # | Test | Today | After |
|---|---|---|---|
| 1 | `test_density_views.py::test_inventory_keeps_the_table_and_gives_the_three_cards_their_own_band` | pins `body.shell-fit #view-inventory { grid-template-rows: auto auto minmax(150px,1fr) auto minmax(150px,0.62fr); }`, `> .tablewrap`, `.inv-lower {…}` + `.inv-lower > .invpanels { display: contents; }` + `.inv-lower #diffList`, and splits `index.html` on `<div class="inv-lower">` | re-pin the new grid: `body.shell-fit #view-inventory { display: grid; grid-template-rows: auto minmax(0, 1fr); }`, `#invItems`/`#invMaterials` as flex columns, `#invItems > .tablewrap { flex: 1 1 auto; min-height: 0; }`, `#invDiff #diffList { flex: 1 1 auto; min-height: 0; overflow-y: auto; }`; assert the Items band holds `id="matCard"`-free markup and `id="invDiff"`, and that `id="dojoCard"` is **not** in the view |
| 2 | `test_density_views.py::test_every_id_and_control_survives` | `'view-inventory'` tuple of 22 frags incl. `id="matCard"`, `id="dojoCard"`, `id="diffList"` | keep the 17 items+materials frags verbatim; drop `id="dojoCard"` (and the other `dojo*` frags in that tuple) from this tuple and assert them in a new Tools-workspace tuple |
| 3 | `test_density_views.py::test_the_rows_keep_the_spaced_budget` | `body.shell-fit #view-inventory .mrow { padding: 6px 10px; font-size: 12.5px; line-height: 1.45; }`, `#view-inventory thead th { padding: 8px 10px; font-size: 11px; }` | unchanged for the items table; the `.mrow` pin follows the dojo rooms block (`#tws-dojo .mrow`) |
| 4 | `test_density_views.py::test_card_chrome_is_the_shared_dense_recipe` | `#view-home .card-head, #view-inventory .card-head, #view-tools .card-head { padding: 8px 12px 5px; … }` + the `.picks` twin | unchanged (both views keep the recipe) |
| 5 | `test_density_views.py::test_the_filter_pills_and_buttons_stay_outside_the_scrollers` | `mat.index('id="matQ"') < mat.index('id="matTbl"')` on the `matCard`…`dojoCard` slice | split on `id="matCard"` → end of the materials panel (no dojo terminator); add `invItems.index('id="btnCols"') < invItems.index('id="tbl"')` and `invItems.index('id="invQ"') < invItems.index('id="tbl"')` |
| 6 | `test_density_views.py::test_the_tools_launcher_and_its_workspaces_share_the_fit_recipe` | pins `#view-tools .tws { flex: 1 1 auto; }` etc. | unchanged, plus the two `#tws-dojo` rules from §4.7 |
| 7 | `test_redesign_ia.py::test_inventory_columns_are_progressively_disclosed` | `.hide-a { display: none; }`, `body.show-a .hide-a`, `classList.toggle('show-a')` in app.js, `id="invQ"` in index.html | add: `id="invAdv"` present, `id="btnCols"` **inside** the `#invAdv` block, and `#btnCols` carries `aria-controls="tbl"` |
| 8 | `test_redesign_ia.py::test_index_has_four_view_sections_and_real_trade_tabs` | `id="view-inventory"` exists; `details class="acc` in index.html | unchanged (the new `#invAdv`/`#invDiff` details satisfy the second half) |
| 9 | `test_materials_panel.py::test_materials_card_is_in_the_inventory_view_beside_the_dojo_card` | `'<div class="invpanels">' in inv`, `inv.index('id="matCard"') < inv.index('id="dojoCard"')` | assert `id="matCard"` sits inside `id="invMaterials"` inside `id="view-inventory"`, and that `id="dojoCard"` is **not** in `inv_block()`; rename the test |
| 10 | `test_materials_panel.py::inv_block()` / `panels_block()` helpers (79-89) | `panels_block()` slices `<div class="invpanels">` → next `<div class="card">`; breaks the moment the row is deleted | `inv_block()` unchanged; `panels_block()` → the `id="matCard"`…`</div>` card block (or `html.index('id="matCard"')` to the end of `#invMaterials`) |
| 11 | `test_materials_panel.py::test_materials_table_headers_are_material_count_category` | 3 `<th>` in `#matTbl`, `>Material/Count/Category</th>` | unchanged |
| 12 | `test_materials_panel.py::test_search_and_sort_toggle_are_wired` | app.js strings for `state.matQ`, `state.matSort`, `matSort.textContent` | unchanged |
| 13 | `test_materials_panel.py::test_the_personal_dojo_swap_row_and_buttons` | `#matView` markup + `.matview` CSS + `#matView` before `#matSort` | unchanged (both live in `#matCard`'s head) |
| 14 | `test_materials_panel.py::test_personal_is_the_default_and_the_choice_is_remembered_in_localstorage` | `wfm.matView` lines | unchanged |
| 15 | `test_materials_panel.py::test_the_dojo_mode_swaps_the_headers_and_rows_in_place` | region between `MAT_HEADS` and `renderDojo()`; `panels_block()`'s `#matHead` static head | unchanged except the helper it borrows (row 10) |
| 16 | `test_materials_panel.py::test_the_payload_is_fetched_once_from_the_materials_endpoint` | `js.count("'/api/feature/materials'") == 1`, `'renderMaterials(); renderDojo();'` in app.js | unchanged — **one** fetch must stay one even with materials in its own subview and dojo in Tools |
| 17 | `test_dojo_panel.py::panels_block()` helper (87-91) | same `.invpanels` slice | re-point to the `#tws-dojo` workspace block (`html.split('id="tws-dojo"',1)[1].split('</section>',1)[0]`) |
| 18 | `test_dojo_panel.py::test_dojo_card_markup_and_headers` | 8 `dojo*` ids + 4 `<th>` inside `panels_block()` | same 8 ids/4 headers, now inside `#tws-dojo` |
| 19 | `test_dojo_panel.py::test_the_scope_is_a_title_tooltip_not_visible_copy` | `head.title = D.scope`, `js.count('D.scope') == 1`, `id="dojoTitle"` in the block | unchanged (scope of the block moves) |
| 20 | `test_dojo_panel.py::test_the_head_counts_shout_credits_and_shortages` | the `meta.textContent = …` / `shortN` / `TT` / `rowsSrc` strings | unchanged (renderer untouched) |
| 21 | `test_dojo_panel.py::test_shortages_sort_first_then_needed_desc` | the `rowsSrc.slice().sort(…)` string | unchanged |
| 22 | `test_dojo_panel.py::test_short_colour_rule_accent_above_zero_muted_ok_below` | `.v` / `.dim` CSS + the two span strings | unchanged |
| 23 | `test_dojo_panel.py::test_rooms_breakdown_is_collapsed_by_default_and_filled_by_js` | `<details class="acc sub" id="dojoRooms">` with no `open`, `<summary>Rooms`, `rooms.classList` add/remove | unchanged (the id and the details move whole) |
| 24 | `test_dojo_panel.py::test_the_source_url_is_a_short_link` | `class="movedlink" id="dojoSrc" href="https://wiki.warframe.com"` | unchanged |
| 25 | `test_dojo_panel.py::test_empty_state_hides_the_rooms_and_says_so` | the two app.js strings | unchanged |
| 26 | `test_dojo_panel.py::test_dojo_card_copy_is_short_and_its_one_explainer_is_wrapped` | `id="dojoNote"` + `.dojo-note dim small explain` + one wrapped explainer | unchanged |
| 27 | `test_inventory_sparkline.py::test_index_puts_the_trend_header_just_before_value` | global split on `<th data-k="value"` must end with `>Trend</th>` | unchanged — but note the split is global: no earlier table in index.html may gain a `data-k="value"` header |
| 28 | `test_inventory_sparkline.py::test_css_condenses_the_inventory_rows` | `.inv-row td { padding: … }`, `tr.inv-row{cursor:pointer}`, hover rule | unchanged |
| 29 | `test_ia_reachability.py::test_every_tool_slug_has_a_launcher_entry_and_a_workspace` | `slugs == SLUGS` (11), `data-tool="player"` count 2 | 12 slugs incl. `dojo`; `data-tool="dojo"` count 2 (launcher entry + wrapper) |
| 30 | `test_ia_reachability.py::test_the_launcher_groups_the_tools_trading_planning_warframe` | `GROUPS['Warframe'] == ['baro','meta','player']`, `launcher.count('class="tool"') == 11` | `['baro','meta','player','dojo']`, count 12; add `id="dojoCard"` not in the launcher block |
| 31 | `test_ia_reachability.py::test_every_tool_list_id_is_still_rendered_by_its_workspace` | per-slug list ids in the workspace block; `tws-back` count == len(SLUGS) | dojo's ids (`dojoTbl`/`dojoRows`) inside `#tws-dojo`; count 12 |
| 32 | `test_ia_reachability.py::test_no_id_from_the_stage1_snapshot_disappeared` | all 30 inventory ids still in static/* | unchanged (this is the guard that catches a lost `diffMeta`/`tbl`/`matHead`) |
| 33 | `test_ia_reachability.py::test_legacy_hashes_resolve_to_the_new_destinations` + `…cannot_land_blank` | alias pairs in app.js + shell.js | add `dojo: 'tools'` in both tables and `location.replace('#tools/dojo')` if the legacy hash ships |
| 34 | `test_player_page.py::test_the_clan_card_writes_the_name_through_the_config_route` | `'>Dojo materials →</a>' in block and 'href="#inventory"' in block` | `href="#tools/dojo"` (and `'#tools/dojo'` in app.js) |
| 35 | `design/_stage2/qa_ia.js` | `TOOLS = [deals … player]`, `TOOL_LIST_IDS` per slug | add `'dojo'` + its list ids; the click-through then covers 12 workspaces and asserts `onlyOne === 1`, `launcherHidden`, `pageOverY === 0` |
| 36 | `design/_stage2/qa_ia.js` fit loop + id union | `for (const v of ['home','trade','inventory','tools'])` at 1920×1080 and 1366×768 | same loop at the 5 sizes (1920×1080, 1536×864, 1440×900, 1366×768, 1280×800) and for **both** inventory subviews (click `#invViews .tab[data-v="materials"]` before measuring); the id union must still report `missing=0` |
| 37 | `design/_stage2/verify_ids.py` | `RENAMED = {'view-more': 'view-tools'}` | unchanged — no inventory rename is sanctioned, so a missing inventory id must fail the run |

No inventory-markup assertions exist in `test_app_shell.py`, `test_ui_polish.py` (rail only),
`test_mod_cards.py`, `test_trade_*`, `test_advanced_mode.py` or `test_copy_*` (checked): nothing else
needs touching.

---

## 6. Risks + acceptance numbers

**Risks**

1. **Column alignment.** Basic/advanced is pure CSS (`.hide-a` on both `<th>` and `<td>`). Editing the
   header without the `renderTable()` template (or vice versa) shifts every cell. Do them in one edit.
2. **`colspan`.** `renderTable()`'s empty state is `colspan="14"`; `test_inventory_sparkline` pins
   `'colspan="14"' in js and 'colspan="13"' not in js`. Keep 14 — cells stay in the DOM.
3. **Hidden-panel scroll cues.** `markScrollers()` (`.scrolly` on `.tablewrap`) measures `scrollHeight`;
   a hidden panel measures 0. `switchInvView()` and `showView('inventory')`/`showTool('dojo')` must call
   `markScrollers()`, or the soft bottom edge never appears until a resize.
4. **Slider/`.tablewrap` max-height.** The generic `.tablewrap { max-height: calc(100vh - 268px) }`
   (`style.css:204-206`) is what keeps the tables bounded below 1200px. Once `.invpanels`-scoped rules
   go, re-point them (`#matCard .tablewrap`, `#dojoCard .tablewrap`) or the moved tables lose their cap.
5. **Dojo in Tools vs the generic workspace rule.** `body.shell-fit .tws-body > .card > div[id]`
   (`style.css:884-886`) matches `#dojoNote` first; without the scoped rules in §4.7 the note becomes the
   scroller and the table stops scrolling.
6. **Two pill rows in a 1200px-wide window.** `#invViews` + `#tabs` cost ~2 rows of height in the fit
   grid; the items table must be `minmax(0, 1fr)` and the diff disclosure `auto`, or the page overflows.
7. **Global `thead th` sort.** `app.js:1654` binds every `thead th` on the page. New tables in this view
   (materials) already carry no `data-k` — keep it that way.
8. **Id snapshot.** `verify_ids.py` and `test_no_id_from_the_stage1_snapshot_disappeared` fail on any
   lost id: `tbl`, `status`, `matHead` and `diffMeta`/`diffList` are the easy ones to drop while
   restructuring. No rename is sanctioned for this view.
9. **`#tabs` is also a collection.js id** (`static/collection.js:208,747,787`) on a different page and
   `collection.css:171` styles `#tabs.hidden`. Don't repurpose `#tabs` for the new subview nav — that is
   what the new `#invViews` is for.
10. **Concurrent edits.** `index.html`/`app.js` are being changed for Home right now; re-read the
    inventory block before editing and re-run the id check afterwards.
11. **`prime_set`** rows (3 today) have no category pill — pre-existing, out of scope.

**Acceptance numbers (measured against the live server at 127.0.0.1:8787 and the files above)**

- **Fit = 0 at 5 sizes.** `#inventory`, both subviews: `pageOverX = 0` and `pageOverY = 0` (and
  `secOverX = 0`) at 1920×1080, 1536×864, 1440×900, 1366×768, 1280×800. Below 1200px the page scrolls
  as before.
- **Item rows = data rows.** `GET /api/items` returns **875** stacks today. Default (`All`, `state.tab='all'`)
  → `#totals` reads `875 stacks (showing 400)` and `#rows tr.inv-row` = **400** (the `slice(0, 400)` at
  `app.js:741`). Per-category counts must equal the data histogram: mod 561, relic 121, prime_part 64,
  other 57, arcane 42, prime_bp 27 (+ prime_set 3 only visible under All). `#tabs .tab` = **7**.
- **Materials unchanged.** `#matRows tr.mat-row` = **274** = `/api/feature/materials.count` = 274;
  `#matCap` empty (274 ≤ `MAT_CAP` 400); `#matMeta` = `· 274`; `state.matView='dojo'` → **25** rows
  (rows with `dojo:true`); `#matHead` still swaps to Material/Count/Category → Material/Needed/Owned/Short.
- **Dojo (now in Tools).** `#tools/dojo`: visible, `onlyOne === 1`, launcher hidden, `pageOverY = 0`;
  `#dojoRows tr.dojo-row` = **7** (`dojo.materials`), `#dojoRoomsList .mrow` = **9** (`dojo.rooms`),
  `#dojoTier` = **5** buttons (ghost…moon), `#dojoMeta` = `· ghost clan · 50,000 cr · N short`.
  Tool-switch: clicking a tier re-renders in place, `localStorage['wfm.dojoTier']` remembered.
- **Changes behind the disclosure.** Collapsed by default: `#invDiff` has no `open`, `#diffList` still
  holds the payload (`status:'ok'`, added 1, removed 0 today) and `#diffMeta` reads `· ok`. Expanding it
  renders identically to today's card.
- **Drawer still opens from rows.** Clicking any `tr.inv-row` (e.g. the first row) → `window.wfmDrawer.isOpen() === true`
  and the panel shows that row's `data-slug`. Works in both Items and Materials subviews after a switch
  (the delegated handler is on `#rows`, which never moves).
- **No server change.** Stage 5 touches `index.html`, `app.js`, `style.css` (+ `shell.js` only if the
  `#dojo` alias ships) — `server.py` and every `/api/*` payload are untouched, so all counts above are
  invariance checks, not new behaviour.
- **Reachability.** 0 console errors and 0 pageerrors on the inventory view; the Tools launcher lists
  **12** entries in 3 groups (Trading 4 / Planning 4 / Warframe 4) and `#tools/dojo` is reachable by
  click and by hash; the reworked `tests/test_ia_reachability.py` and `design/_stage2/verify_ids.py`
  both pass with `missing = 0`.
