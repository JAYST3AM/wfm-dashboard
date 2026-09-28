# WFM Trader — navigation & IA

What the front end's information architecture is, where each destination lives, and which files own
it. Written for anyone changing the UI (and for future-me). The stage-by-stage history and the
audit behind it live in [`design/migration-map.md`](../design/migration-map.md); this page describes
the **landed** state as of 2026-09-28.

The app is a local server with hash-routed views on one SPA page plus four standalone pages, so a
"destination" is either a hash on `/#…` or a real `.html` file.

## The rail — six destinations, two groups

Rendered by `static/shell.js` from the `RAIL` / `RAIL_GROUPS` registry; styled by `static/shell.css`.
Pages declare themselves with `<body data-shell="index|collection|cards|settings|item">` and hold no
chrome of their own.

| Pill | Goes to | Active when | Group |
|---|---|---|---|
| Home | `/#home` | the default hash | what you own and trade |
| Trade | `/#trade` | `#trade` | ↑ |
| Inventory | `/#inventory` | `#inventory` | ↑ |
| Collection | `/collection.html` | any `collection.html` section (relics/mastery included) | ↑ |
| Tools | `/#tools` | `#tools` and every `#tools/<slug>` | configure & reach for |
| Settings | `/settings.html` | `settings.html` | ↑ |

Mastery, Player and More are **not** pills any more. Mastery is a section of Collection, Player is a
Tools workspace, and More *is* the Tools launcher.

## Destinations

| Destination | URL | Contents |
|---|---|---|
| Home | `/#home` | Today strip (earned today, sales, trades left, platinum — detail one tap below), the single **Next action** item (name, price, demand, copies, best buyer), alerts, the sell queue, recent activity. Game news lives in Tools. |
| Trade | `/#trade` | Tabs **Orders** (`#trade/orders`, first in the strip) · **Sell** (`#trade/sell`, what a fresh load opens on) · **Buy** · **History** (`#history`) · **Advanced**, plus the run queue, the Safety kill switch and notifications below. Orders is the live book for one item: sell and buy rows with trader names, reputation and status, an ingame/online/offline filter (ingame+online on by default), the per-rank price ladder, and a Whisper button per row. |
| Inventory | `/#inventory` | Owned items table (default columns + **All columns**), Materials, Clan Dojo, inventory changes. |
| Collection | `/collection.html` | Sections **Collection** · **Relics** (`#relics`) · **Mastery** (`#mastery`), each deep-linkable, plus a link to the Cards page. |
| Cards | `/cards.html` | The full mod-card workspace. Reached from the Collection section row (and old `#cards` links). |
| Tools | `/#tools` | The launcher: three groups (Trading / Planning / Warframe) + the Setup/links card. Each tool opens one focused workspace, `#tools/<slug>`. |
| Settings | `/settings.html` | Six categories, one panel in the flow at a time: **General** (`#general`, the default) · **Trading** · **Appearance** · **Accounts** · **Notifications** · **Advanced**. An unknown/empty hash falls back to General. |
| Item analysis | `/item.html?item=<slug>` | The deep per-item page: picker, chart, trades, statistics. Also accepts `#item=<slug>` and the older `?slug=<slug>`. No parameter = the picker. |

### Tools workspaces

`app.js` holds `TOOL_SLUGS` (launcher order) and `showTool(slug)` shows exactly one; the markup is
`#toolsLauncher` + `#toolsWs` in `index.html`.

| Group | Workspace | Slug | List ids |
|---|---|---|---|
| Trading | Deals | `#tools/deals` | `dealsList` |
| Trading | Movers & demand | `#tools/trends` | `moversList`, `trendsList` |
| Trading | Riven bands | `#tools/rivens` | `rivensList` |
| Trading | Watchlist | `#tools/wl` | `wlList` |
| Planning | Ducats | `#tools/ducats` | `ducatsList` |
| Planning | Craft or buy | `#tools/craft` | `craftList` |
| Planning | Relic EV | `#tools/relicev` | `relicsList` |
| Planning | Sets | `#tools/sets` | `setsList`, `nudgesList` |
| Warframe | Baro Ki'Teer | `#tools/baro` | `baroList` |
| Warframe | Patch meta | `#tools/meta` | `metaList` |
| Warframe | Game news | `#tools/news` | `newsList` |
| Warframe | Player profile | `#tools/player` | `pc*` (the old Player view, one workspace) |

## Item detail — two surfaces, on purpose

| Surface | File | Role |
|---|---|---|
| Drawer (quick look) | `static/drawer.js` / `drawer.css` | Opened by the header search, an inventory row or a collection tile. Summary: recommended action, your copies, market tiles, mini graph, collapsed detail. Exactly one primary action: **Open full analysis ↗** → `/item.html?item=<slug>`. |
| Full analysis | `static/item.js` / `item.html` | The deep page: chart, trades, order book, statistics. Read-only (every request is a GET). |

## Legacy links (all still resolve)

| Old | Now |
|---|---|
| `#more`, `#market` | `#tools` |
| `#player` | `#tools/player` |
| `#mastery` | `/collection.html#mastery` |
| `#history`, `#trader` | `#trade` |
| `#collection`, `#cards` | `/collection.html`, `/cards.html` |
| `/lookup.html[?q=…]` | the header search (`/#search?q=…`) |

The alias table lives in `app.js` (`VIEW_ALIAS` + the explicit redirects in `applyHash()`) and is
mirrored in `shell.js`'s `ALIAS`, so the rail pre-marks the pill the router will show. Keep the two
in step.

## What keeps this honest

- `tests/test_app_shell.py` — one chrome source: fails if a page re-declares header/rail markup.
- `tests/test_ia_reachability.py` — rail order and groups, every Tools slug has a launcher entry *and*
  a workspace, the twelve old More-page list ids still render, Mastery is a Collection section with
  its ids, the legacy hashes resolve, nothing from the Stage 1 id snapshot disappeared.
- `tests/test_settings_nav.py` — the six Settings categories, one panel in the flow, deep links.
- `tests/test_drawer_analysis.py` — the drawer's single action and its slug wiring; the deep-link
  parsing order on `item.html`.
- Headless QA harnesses (need a running dashboard): `design/_stage2/qa_ia.js` (rail per page, all
  workspaces, legacy redirects, id union), `design/_stage8/qa_settings.js`,
  `design/_stage9/probe_s9.js`. Id baselines: `design/_stage1/ids_before.json` and the per-stage
  `ids_before.json` files.
