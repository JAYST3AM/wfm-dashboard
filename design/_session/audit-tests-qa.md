# Audit — test / QA / CI infrastructure (read-only)

Scope: what is needed to plan Trading Session coverage per `docs/trading-session-workflow.md` §13
(tests) and §14 (CI). Read-only pass: the only file written is this one (`git status --short` →
`?? design/_session/`).

Verified on `main` on this machine: **89 test files, 1742 tests collected**
(`python -m pytest tests -q --collect-only` → `1742 tests collected in 0.40s`).

---

## 1. What the docs bind us to

| Doc | Load-bearing constraints |
|---|---|
| `trading-session-workflow.md` §4 (L180–199) | Reconciliation presents evidence; never auto-create a trade from inference alone. |
| §5 (L207–229) | **One canonical trade-completion path**; idempotent; double-click/refresh/retry must not duplicate; stable local trade IDs. |
| §11 (L408–430) | Atomic JSON writes, previous data preserved on failure, stable IDs, idempotent confirm, never infer without asking, never delete history, pending **and session** survive refresh/restart, stale pending recoverable, dry-run/kill-switch behaviour intact, no automatic WFM listing. |
| §13 (L468–508) | 22 named test areas + browser gate on `#trade/session` at the existing viewport/theme matrix: no horizontal clipping, no console errors, no duplicate IDs, no broken legacy navigation. |
| §14 (L511–525) | CI must not need a real Warframe install, the AlecaFrame cache, personal data, credentials or a live whisper — fixtures/mocks only. |
| `navigation.md` (L34, L80–82) | Rail = 6 pills; Trade tabs are Orders (`#trade/orders`, first) · Sell (`#trade/sell`, fresh-load default) · Buy · History (`#history`) · Advanced. Alias table lives in **both** `app.js` `VIEW_ALIAS` and `shell.js` `ALIAS` — "keep the two in step". Legacy hashes must all resolve (L69–78). |
| `whisper.md` (L95–130) | `scripts/whisper.py` API (`message`/`copy`/`send`/`probe`/`log_last`), ledger `data/whisper_log.json` row shape, 2 s + 10/min gates, refusal reasons, atomic writes, 500-row cap. |

**`#trade/session` does not exist yet** — `grep -rn "trade/session\|trade-session\|startTrading"
static/ tests/ design/ server.py scripts/*.py` returns nothing.

---

## 2. tests/ inventory — 89 files by coverage area

**Trade history / ledger / sessions (11).** `test_server_payloads.py` (trade_log totals + newest-first
ordering via `trades_payload`), `test_plat_ledger.py` (platinum window math + `check_reconciliation`
— the closest existing thing to §4), `test_progress.py` (Today/session/day maths over
`plat_history+trade_log+session_stats+invdiff`), `test_session_stats.py` (session clustering by gap),
`test_item_history.py`, `test_price_history.py`, `test_sell_advisor.py`, `test_sell_timing.py`,
`test_report.py`, `test_digest.py`, `test_pushd.py`.

**Whisper / orders / buyers (7).** `test_whisper.py` (875 LOC — message wording, window selection,
`Ctrl+V`+`Enter` order, refusals, both rate gates on a fake clock, ledger contract → **§3's CONTACTED
state should ride on this**), `test_orders_api.py` (588 LOC — `scripts/orders.py` access layer plus
`GET /api/orders`, `/api/rank_values`, `POST /api/whisper`), `test_trade_orders_tab.py`,
`test_fetch_lanes.py` (**rank-lane reduction — rank-aware matching already has a home**),
`test_runqueue.py` (`plan_queue`/`buyers_for`/`queue_row` — **existing queue generation to reuse, §1**),
`test_wfm_session_policy.py`, `test_wfm_check_policy.py`.

**Inventory / owned / diff (18).** `test_invdiff.py` (**inventory delta detection already covered**:
`compare` added/removed/changed, `totals`, baseline snapshot, unpriced rows), `test_inventory_subviews.py`,
`test_inventory_sparkline.py`, `test_materials.py`, `test_materials_panel.py`, `test_saveio.py`,
`test_watch_save.py`, `test_collection_log.py`, `test_mastery.py`, `test_relics_panel.py`,
`test_relic_ev.py`, `test_riven_lister.py`, `test_rivens.py`, `test_mod_cards.py`, `test_cards_page.py`,
`test_cards_perf.py`, `test_collection_obtain_cards.py`, `test_obtain_index.py`.

**HTTP routes / server (16).** `test_server_payloads.py`, `test_config_api.py` (`GET` + write path of
`/api/config`, with a **repo-file-unchanged proof**), `test_orders_api.py`, `test_chat.py`,
`test_autosync.py`, `test_profiles.py`, `test_player_page.py`, `test_dojo_panel.py`,
`test_materials_panel.py`, `test_inventory_sparkline.py`, `test_redesign_ia.py`, `test_sync_status.py`,
`test_notify.py`, `test_notify_rules.py`, `test_setup_tools.py`, `test_refresh_guard.py`.

**Shell / IA / layout / copy / density / contrast (24).** Shell+IA: `test_app_shell.py`,
`test_ia_reachability.py`, `test_redesign_ia.py`, `test_settings_nav.py`, `test_drawer_analysis.py`,
`test_home_layout.py`, `test_trade_layout.py`, `test_ui_polish.py`, `test_app_bundle.py`.
Copy gates: `test_copy_diet.py` (source scan), `test_copy_rendered.py` (**reads
`design/_stage10/gate-raw.json`**), `test_copy_simplicity.py`, `test_terminology_live_not_live.py`.
Density gates: `test_density_views.py`, `test_density_pages.py`, `test_density_collection.py`,
`test_density_cards.py`, `test_trade_density.py`. Contrast/themes: `test_contrast_fixes.py`,
`test_themes.py`. Other: `test_item_page.py`, `test_settings_page.py`, `test_icons.py`,
`test_icon_cache.py`.

**Trader engines / offline scripts (16).** `test_auto.py`, `test_detector_v1.py`, `test_flipper.py`,
`test_hygiene.py`, `test_settings.py`, `test_meta_watcher.py`, `test_deal_scanner.py`, `test_ducats.py`,
`test_craft.py`, `test_sets.py`, `test_dojo_costs.py`, `test_player.py`, `test_watchlist.py`,
`test_import_aleca_stats.py`, `test_relic_dock.py`, `test_advanced_mode.py`.

---

## 3. `tests/conftest.py` — fixtures and helpers

131 lines, stdlib + pytest only. Its docstring is the house rule (L1–13):

> *"The public repo ships NO data/ folder (CI checks out a clean tree), so every test builds its own
> fixtures under tmp_path and points the script's path globals at them."* … *"never import
> scripts/trader/\* (private, gitignored - not on GitHub); never touch the network; never read or
> write the repo's real data/ directory; load scripts by file path (… a fresh module object per test
> keeps monkeypatched globals from leaking between tests)."*

`load_script` (conftest.py:29–50) is the workhorse — imports `scripts/<name>.py` or the repo-root
`server.py` as a **fresh** module under a unique name, applying `env` *before* exec:

```python
def load_script(name, monkeypatch=None, env=None):
    """Import scripts/<name>.py (or the repo-root server.py) as a fresh module object.
    ``env`` is applied BEFORE the module is exec'd, so module-level os.environ reads
    (price_history's PRICE_HISTORY_PATH / PRICE_MOVERS_PATH) are exercised for real."""
    ...
    modname = 'wfm_%s_%d' % (name, next(_seq))
    spec = importlib.util.spec_from_file_location(modname, path)
```

`server_mod` (conftest.py:75–85) is how `server.py` is loaded and how tmp state is injected:

```python
@pytest.fixture
def server_mod(tmp_path, monkeypatch, data_dir):
    """server.py imported without ever starting the HTTP server.
    DATA/ROOT are redirected into tmp_path so no repo data is read and no repo file
    is written; the handler class is never instantiated (no socket is opened)."""
    mod = load_script('server', monkeypatch=monkeypatch, env={'WFM_PORT': '0'})
    monkeypatch.setattr(mod, 'DATA', str(data_dir))
    monkeypatch.setattr(mod, 'ROOT', str(tmp_path))
    return mod
```

Also: `data_dir` (tmp_path/'data'), `write_json`/`read_json`, and the shell helpers `read_static`,
`shell_js`, `shell_css`, `shell_css_all`, `shell_decl` (regex-parses `<body data-shell="…"
data-shell-actions="…">`), `rail_rows` (parses `var RAIL = [ … ];` out of `static/shell.js`).

**JSON state is faked two ways.** (1) Written into the tmp `data_dir` the module reads —
`write_json(data_dir / 'trade_log.json', events)` (test_server_payloads.py:125). (2) The module's
path globals are monkeypatched — `monkeypatch.setattr(ob, 'DATA', str(tmp_path / 'orders_data'))`
(test_orders_api.py:313), `monkeypatch.setattr(hyg, 'OUT', str(data / 'hygiene_plan.json'))`
(test_hygiene.py:88); env redirection where supported: `monkeypatch.setenv('WFM_CONFIG', str(cfg))`
(test_config_api.py:40).

**Personal data guards.** `test_config_api.py:28` captures `REAL_HASH = sha(data/config.json)` at
import and re-asserts it at the end; `test_setup_tools.py:156` proves the generated
`static/collection_log.json` is not tracked.

---

## 4. How the server / app is exercised today

**There is no live-HTTP route test in `tests/` — no TestClient, no HTTP client, no handler
instantiation.** Routes are tested by calling the module-level payload builder directly:

```python
payload = server_mod.feature_payload('deals')                 # test_server_payloads.py:17
payload = server_mod.trades_payload()                          # test_server_payloads.py:127
p = api.orders_payload({'item': ['primed_continuity'], …})     # test_orders_api.py:321
body = api.dashcfg_payload()                                   # test_config_api.py:49
```

Route *wiring* is pinned by source-string assertions against `server.py` read as text
(test_orders_api.py:567–571):

```python
def test_the_new_routes_are_wired_and_the_old_ones_are_untouched():
    assert "if p == '/api/orders': return self._send(200, orders_payload(parse_qs(urlparse(self.path).query)))" in src
```

**The only real socket in the suite** — a stdlib server for `tools/supervise.ping`
(test_setup_tools.py:101–112):

```python
srv = http.server.HTTPServer(('127.0.0.1', 0), http.server.SimpleHTTPRequestHandler)
port = srv.server_address[1]
thread = threading.Thread(target=srv.serve_forever, daemon=True)
thread.start()
try:
    assert mod.ping('127.0.0.1', port, timeout=3) is True
finally:
    srv.shutdown(); srv.server_close()
```

Port `8787` is asserted present in the launcher (`test_setup_tools.py:80`: `assert '8787' in bat`),
never dialled. **Subprocess CLI pattern**: `subprocess.run([sys.executable, os.path.join(REPO,
'scripts', 'orders.py'), '--selftest'], capture_output=True, text=True, timeout=120, cwd=REPO)`
(test_orders_api.py:299–302). `test_hygiene.py:build_harness` copies the script plus `data/` into
`tmp_path/'harness'` and runs it with `cwd=root`, `PYTHONDONTWRITEBYTECODE=1` — the pattern for a full
CLI end-to-end without touching the repo.

---

## 5. Adding a test that proves a route is read-only (mutation test)

**No live-HTTP example exists.** The house pattern is *call the function, then prove the bytes did
not move*. The model is `tests/test_hygiene.py:127–146`:

```python
def test_plan_only_never_writes_state_or_plan(tmp_path, hyg, monkeypatch):
    """The planner is read-only apart from its own output file."""
    write_fixtures(tmp_path)
    data = tmp_path / 'data'
    before = {p: (data / p).read_bytes() for p in ('trader_state.json', 'trader_plan.json')}

    code, _ = run_cli(hyg, monkeypatch, tmp_path, ['--once', '--offline-window', '240'])

    assert code == 0
    after = {p: (data / p).read_bytes() for p in before}
    assert after == before
    assert sorted(os.listdir(data)) == ['hygiene_plan.json', 'trader_plan.json',
                                        'trader_state.json']
```

Its stronger sibling is the repo-file-hash proof in `tests/test_config_api.py:9–28` (`sha()` over the
real `data/config.json`, re-checked by the last test).

**Recommended shape for the session work**, three layers:
1. *Unit* — call the payload/transaction function on `server_mod` with a fixture `data_dir`; snapshot
   bytes before/after; assert `after == before` for read-only files and exactly one append for confirm.
   This layer runs on CI today.
2. *Route* — start the real handler: mirror `test_setup_tools.py:101–112` for lifecycle but with
   `('127.0.0.1', 0), server_mod.H` and `urllib.request.urlopen` on the returned port, then compare
   bytes. **UNVERIFIED — new machinery, no existing example to quote.**
3. *Wiring* — a source-string assertion that `do_GET` owns the session read route and `do_POST` owns
   only confirm/skip/hold, in the style of `test_orders_api.py:567`.

---

## 6. Browser QA gate

Harnesses (all `puppeteer-core`): `design/_audit/qa_{console,deadspace,flows,ids,nav,nav2,parity,shell,
shell2,widths}.js`, `design/_stage1/qa_shell.js`, `design/_stage2/qa_{ia,smoke}.js`,
`design/_stage3/qa_{chart,chips,empty,home}.js`, `design/_stage4/qa_trade.js`,
`design/_stage5/qa_inventory.js`, `design/_stage6/qa_{collection,stage6}.js`,
`design/_stage8/qa_{settings,settings_widths}.js`, `design/_stage9/probe_s9.js`,
`design/_gatefix/*.js`, and **the newest and only one with a runner: `design/_stage10/gate.js` +
`design/_stage10/gate.py`** (newest design commit touching it: `a45b6cc`). Each writes its own JSON
next to itself (`design/_audit/ids.json`, `design/_stage4/qa_trade.json`, …).

**No npm project in this repo** — `ls package.json node_modules` → nothing. The driver is resolved
from a sibling checkout or env (gate.js:32–42):

```js
let puppeteer = null, PUPPETEER_FROM = null;
for (const cand of [process.env.WFM_PUPPETEER, 'puppeteer-core', 'puppeteer',
                    'F:/VSC Projects/pb-bench/node_modules/puppeteer-core']) {
  if (!cand) continue;
  try { puppeteer = require(cand); PUPPETEER_FROM = cand; break; } catch (e) { /* next */ }
}
if (!puppeteer) { console.error('gate.js: no puppeteer-core found …'); process.exit(2); }
```

Older harnesses skip the fallback chain and hard-require the pb-bench path
(`design/_audit/qa_ids.js:7`) with `CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe'`
(qa_ids.js:9). Present here: node `v24.13.0`, that Chrome, `F:/VSC Projects/pb-bench/node_modules/
puppeteer-core/package.json`. Driver = **puppeteer (CDP) only; no Playwright anywhere in the repo.**

**They need a live app** (gate.js:44–45):
```js
const BASE = process.env.WFM_BASE || 'http://127.0.0.1:8787';
const CHROME = process.env.WFM_CHROME || 'C:/Program Files/Google/Chrome/Application/chrome.exe';
```
Port **8787**. **Exact commands for the newest gate:**
```bash
python server.py                      # app up on 8787 (start.bat / supervise.bat also do this)
python design/_stage10/gate.py        # copy-diet test + gate.js -> gate-report.md, exit 0/1
node   design/_stage10/gate.js        # browser half alone -> gate-raw.json
```
`gate.py` docstring (L6–10): *"1. runs the repo's own copy-diet test (tests/test_copy_diet.py) with
pytest; 2. runs design/_stage10/gate.js (puppeteer-core, the live app at http://127.0.0.1:8787);
3. merges both into design/_stage10/gate-report.md (timestamped) and gate-raw.json."* The gate is
**read-only on the app** (gate.js:11–13): *"It never POSTs and never clicks a control that writes
data (no rebuild plan/queue, no list/buy, no kill switch, no notify test, no settings save)."*

**The matrix §13 refers to** (gate.js:56–59):
```js
const VIEWPORTS = [[1920, 1080], [1536, 864], [1440, 900], [1366, 768], [1280, 800]];
/* 2 dark + 2 light, by index into static/theme.js WFM_THEMES */
const THEMES = [0, 2, 14, 28];                 /* Vor Orange, Kuva Crimson (dark) | Frost Light, Cephalon White (light) */
const THEME_DARK = 0, THEME_LIGHT = 14;        /* the dark/light pair compared for var escapes */
```
Route matrix (gate.js:60–67): `INDEX_VIEWS = ['home','inventory','trade','tools']`, `WORKSPACES`
(12 slugs), `SETTINGS_CATS` (6), `COLLECTION_SECTIONS` (3), `LEGACY_HASHES =
['more','market','player','mastery','history','trader']`. `fit` runs every index view at all five
viewports asserting `pageOverX/Y == 0` (gate.js:858–878).

**The exact template for `#trade/session` already exists** — the `#trade/orders` deep-link check
(gate.js:654–667, plus `INDEX_VIEWS.concat(['trade/orders'])` at :867 and :887):

```js
rec.state = '#trade/orders';
await page.goto(BASE + '/#trade/orders', { waitUntil: 'load', timeout: 45000 });
addCheck('load', 'the #trade/orders deep link opens the Orders tab itself', …);
```
Add `'trade/session'` to those two `concat` lists and clone the deep-link block.

Current gate state: `design/_stage10/gate-report.md` (2026-09-28 21:11) → **FAIL, 3 of 107 checks**
(themes 132 low-contrast over 60 scans; copy 53 offenders) — pre-existing, and they must be green
before a session gate reads as "no new noise". `gate-raw.json` **is committed** (`git ls-files`
confirms), which is why `test_copy_rendered.py` runs on CI instead of skipping.

---

## 7. Id baselines

| File | Shape | Consumer |
|---|---|---|
| `design/_stage1/ids_before.json` | dict per page (`index`, `collection`, `cards`, `settings`, `item`, `lookup`) → id list | `tests/test_ia_reachability.py:382,402` (nothing may disappear; a sanctioned-removal map carries `heroCard`/`heroMeta`/`homeSync`/`view-more`/`view-mastery` with reasons); `tests/test_inventory_subviews.py:59` |
| `design/_stage4/ids_before.json` | flat list of the **48** ids the `view-trade` surface carried pre-stage-4 | `design/_stage4/verify_ids.py` vs the rendered `design/_stage4/qa_trade.json`; mirrored as `TRADE_IDS` in `tests/test_trade_layout.py:36–48` |
| `design/_stage8/ids_before.json` | `{file, ids}` for `static/settings.html` | `design/_stage8/verify_ids.py` |

`gate.js` check 8 re-derives the stage-1 check in-browser (`ID_PAGES = ['index','collection','cards',
'settings','item','item-deeplink','lookup']`, gate.js:592) with a `SANCTIONED` map (gate.js:68–76).
**There is no automated duplicate-id gate in pytest** — `grep -rn "duplicate\|uniq(" tests/*.py` hits
only prose; §13's "no duplicate IDs" needs a new assertion (gate.js has none either).

---

## 8. CI today, and what a browser gate would need

`.github/workflows/tests.yml` — one job: `ubuntu-latest`, python `3.11`,
`python -m pip install --upgrade pip pytest cryptography`, a guard step that fails if `data/` exists
in the checkout (`if [ -d data ]; then echo "unexpected data/ directory in the checkout"; exit 1; fi`),
then `python -m pytest tests -q`. **Gates today: 1742 pytest tests + that guard.** No node, no Chrome,
no browser gate.

**What a CI browser/UI acceptance gate needs:**
1. `actions/setup-node` + chromium (`npx playwright install chromium` or a distro package). CI must
   not depend on `F:/VSC Projects/pb-bench`; either vendor a `package.json` with a `puppeteer-core`
   dep, or use the `WFM_PUPPETEER` env seam gate.js already provides.
2. **A fixture-mode server.** `server.py` has **no env override for `DATA`/`ROOT`** — module globals
   from `__file__` (`server.py:11–12`); only `WFM_PORT`/`WFM_HOST` are env-driven (L14, 22, 24).
   Tests monkeypatch `mod.DATA`/`mod.ROOT` (`conftest.py:83–84`). So CI needs either a ~15-line
   launcher (`import server; server.DATA = fixtures; ThreadingHTTPServer(('127.0.0.1', <port>),
   server.H).serve_forever()`) or a new `WFM_DATA` override in `server.py`. Both are unwritten.
3. **A fixture `data/` tree** committed under e.g. `design/_session/fixtures/data/`: synthetic
   `trade_log.json`, `plat_history.json`, `session_stats.json`, `invdiff.json`, `owned.json`,
   `prices.json`, `stats.json`, `orders_cache/<slug>.json`, `trader_plan.json`. Never
   `progress.json`, `collection_log.json`, `secrets.json`, or a real username (cf. §14).
4. **gate.js parity must be relaxed or re-parameterised** — check 4 compares rendered numbers against
   raw `data/*.json` (gate.js:518 `parityNum`). Cleanest: a `#trade/session` subset gate (load + fit +
   rail + ids + themes) that skips parity/copy on absent fixture keys.
5. **Mock the boundaries** (each already mocked in pytest, per §14): `whisper.copy`/`send`
   (test_orders_api.py:446–454 `quiet_whisper`), `orders.fetch_book` (test_orders_api.py:314),
   `urlopen` (test_orders_api.py:279), and `subprocess` — `server.py:1089+` shells out to
   `scripts/trader/*`, which are gitignored and must never run in CI.
6. **Budget it as its own workflow.** gate.py passes `timeout=1800` to the gate subprocess
   (`gate.py:36`); 34 page states × 5 viewports × 4 themes is not a fast job and 1800 s is the only
   measured signal (no CI run of it exists).

---

## 9. GAPS — the §13 list mapped to new tests

**NEW** = no equivalent; **EXTEND** = an existing file is the right home.

| # | §13 area | Status | File + fixture strategy |
|---|---|---|---|
| 1 | start trading session | NEW | `tests/test_trade_session_state.py` — `load_script` the session store, `monkeypatch.setattr(mod,'DATA',str(data_dir))`; assert the doc's schema and a stable `session_id` across two starts. |
| 2 | queue generation | EXTEND | `tests/test_runqueue.py` already covers `plan_queue`/`buyers_for`; add a session-queue test reusing the `_o(...)` order-fixture style from test_orders_api.py:46–91, asserting queue order = sell-recommendation order. |
| 3 | ranked item matching | EXTEND | `tests/test_fetch_lanes.py` + test_orders_api.py:135 (rank filter / lane rule); add "never pair rank-10 owned with a rank-0 buyer" (§2 L113). |
| 4 | whisper → CONTACTED | NEW | `tests/test_trade_session_state.py` — stub `scripts/whisper` like `quiet_whisper` (test_orders_api.py:446); assert the pending row carries slug, name, rank, qty, expected plat, buyer, ts, count/plat before (§3 L122–133). |
| 5 | persistence across reload | NEW | same file — write the store, re-`load_script` a fresh module over the same `data_dir`, assert identical pending + session. |
| 6 | inventory delta detection | EXISTS | `tests/test_invdiff.py` (`test_delta_against_previous_day_snapshot`, `test_removed_and_changed_rows_and_cap_flag`). Reuse. |
| 7 | platinum delta detection | EXISTS | `tests/test_plat_ledger.py` + `test_server_payloads.py::test_plat_history_deltas`. |
| 8 | exact reconciliation | NEW | `tests/test_trade_reconcile.py` — pure `(pending, owned_before/after, plat_before/after)` → verdict; fixture = the §4 worked example (3→2 copies, 1220→1294 plat, expect 1 sale @74p). |
| 9 | ambiguous reconciliation | NEW | same file — delta 1 but plat change ≠ expected 74p → evidence, not a created trade (§4 L193–199). |
| 10 | rejected reconciliation | NEW | same file — "Not this trade" leaves every state file byte-identical (`read_bytes()` compare, per test_hygiene.py:133). |
| 11 | manual completion | NEW | `tests/test_trade_confirm.py` — the manual path produces the same canonical record as the reconciled path (§5 L220–228). |
| 12 | confirmation | NEW | same file — one transaction updates history + ledger + session totals + sales count + queue. |
| 13 | trade ID idempotency | NEW | same file — confirm twice with the same `trade_id` → one appended event, stable id. |
| 14 | duplicate confirmation protection | NEW | same file — two ids for one piece of evidence, plus a double-click simulation → no duplicate. |
| 15 | history update | EXTEND | `tests/test_server_payloads.py` — add the post-confirm case in `test_trades_totals_and_reversed_events`'s fixture style. |
| 16 | ledger update | EXTEND | `tests/test_plat_ledger.py` — assert confirm writes the ledger shape `plat_ledger` already reads. |
| 17 | session totals | EXTEND | `tests/test_session_stats.py` / `test_progress.py` (`doc['today']['sessions'] == ['count','minutes','current']`) — add the live-session total contract (§6). |
| 18 | queue advances after completion | NEW | `tests/test_trade_confirm.py` — after confirm the queue index advances and the item is removed/reduced (§5 L216). |
| 19 | session resume after restart | NEW | `tests/test_trade_session_state.py` — fresh `load_script` over the same dir; session still active with the same start ts and remaining queue. |
| 20 | no mutation from read-only routes | NEW | byte-compare test in `tests/test_trade_session_state.py` (§5) **plus** a route-level variant starting `server_mod.H` on port 0 (test_setup_tools.py:101–112 lifecycle). |
| 21 | malformed/partial state files | NEW | `tests/test_trade_session_state.py` — a half-written `'{"session": {'` must not crash; follow `test_hygiene.py::test_state_file_half_written_still_plans_from_the_plan` and `test_settings_write_race_falls_back_to_defaults`. |
| 22 | no existing trade/history regression | EXTEND | `tests/test_server_payloads.py` + `tests/test_trade_layout.py` (`TRADE_IDS`); `test_ia_reachability.py` already enforces the stage-1 id snapshot. |
| — | browser gate on `#trade/session` | NEW | extend `design/_stage10/gate.js`: add `'trade/session'` to the `INDEX_VIEWS.concat([…])` lists at :867 and :887 + clone the deep-link block from :654–667; add a **duplicate-id** check (none exists today). |
| — | no broken legacy navigation | EXISTS | gate.js `LEGACY_HASHES` check (:730) + `test_ia_reachability.py` legacy-hash pins; verify `app.js` `VIEW_ALIAS` and `shell.js` `ALIAS` still agree after the new route. |

**Two structural gaps, stated plainly:**
- The pytest suite has **no live-HTTP route test**, so §13's "no mutation from read-only routes" has
  no precedent to copy — it is new machinery (§5).
- `tests/test_copy_rendered.py` validates the **committed** `design/_stage10/gate-raw.json`. New
  `#trade/session` copy is not checked by pytest until someone re-runs `python
  design/_stage10/gate.py` and commits the refreshed artifact. A CI session gate must not rest on this.

---

## 10. Marked UNVERIFIED

- Whether a live-HTTP in-pytest route test can be written flake-free on this Windows host — no precedent.
- Which fixture mode CI will use (launcher shim vs a new `WFM_DATA` override in `server.py`) — both unwritten.
- Whether gate.js parity can be subset cleanly against a fixture `data/` tree — not attempted.
- The real CI cost of gate.js; the 1800 s timeout in `gate.py:36` is the only signal, and no CI run exists.
- `design/_stage9/probe_s9.js` and `design/_gatefix/*.js` were inventoried by name only — not read in full.
