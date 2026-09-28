"""Trade > Orders (Jay 2026-09-28): the live WFM order book gets its own tab, FIRST in the strip,
ahead of Sell, and the sell plan stays the panel the page opens on. Jay's addition the same day: an
ingame / online / offline status filter over both lists, client-side, with the per-status count on
each chip.

Why a new file: the tab, the panel, the status filter and the whisper flow are new surface, and
every pin here is new. The change had to touch two OLD pins, both with a comment saying why - the
tab count in tests/test_trade_layout.py (4 -> 5: Orders joined the strip; nothing was dropped) and
one docstring line in tests/test_ia_reachability.py (the Advanced tab is no longer the fourth).
Nothing else in an older test was touched.

What is held in place here:
  * the strip is Session / Orders / Sell / Buy / History / Advanced (the Trading Session took the
    first slot on 2026-09-29 - see tests/test_trade_session_panel.py), Orders still sits ahead of
    Sell, and Sell is still aria-selected="true" on load with #tp-sell the one panel that ships
    without .hidden - the selected panel is the decision surface, only the strip order changed;
  * #tp-orders sits before #tp-sell in the markup and carries every orders id (ordQ, ordItem,
    ordRank, ordStatus, ordStIngame, ordStOnline, ordStOffline, ordStAll, ordRefresh, ordMeta,
    ordValues, ordSell, ordBuy, ordErr) plus the two list heads - Selling (you would buy) and
    Buying (you would sell) - each with its own label row;
  * #trade/orders deep-links it through the existing sub-tab path (tp- + sub), and switchTradeTab
    opens the book (renderOrders) when that panel wins;
  * the book reads /api/orders with the contract params (item / rank / limit), it is fetched on
    tab open, on the rank picker and on Refresh only - no timer - and a new ask aborts the old one;
  * the status chips: ingame + online on, offline off, aria-pressed on every chip, the count in
    each label, All clears or restores the three, and a toggle repaints from ORD.data (ordPaint)
    with no refetch anywhere in the handler;
  * the two lists keep the server order - price (sell ascending, buy descending), then who can
    trade now, then the freshest listing, then the name - and the meta line names the statuses on
    and how many of the fetched rows are shown;
  * a filter that empties a list prints that list's own line (No ingame or online sellers), never a
    blank box; the ladder renders the values map (ask / bid / n_ask / n_bid), one row per rank;
  * one whisper per click posts {item, user, price, kind, rank, mode:'send'}, the kind coming from
    the list the row sits in, the button refuses a row the filter has hidden, and the answer line
    is written from the response: sent -> Sent to game, copied -> Copied - game not running,
    otherwise the server's own reason. A failed send can never print a claim of delivery.

WFM reading, as the panel's heads state it: a SELL order is someone selling (you would buy from
them), a BUY order is someone buying (you would sell to them).
"""
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ORDERS_IDS = ('ordCard', 'ordQ', 'ordItem', 'ordRank', 'ordRefresh', 'ordMeta', 'ordValues',
              'ordSell', 'ordBuy', 'ordErr')
CHIP_IDS = ('ordStIngame', 'ordStOnline', 'ordStOffline', 'ordStAll')

BANNER = '/* ---------- orders (Trade > Orders, the first tab) ----------'


def read(rel):
    with open(os.path.join(REPO, rel), encoding='utf-8') as fh:
        return fh.read()


INDEX = read('static/index.html')
APP_JS = read('static/app.js')
CSS = read('static/style.css')


def trade_section(html):
    return html.split('id="view-trade"', 1)[1].split('</section>', 1)[0]


def tab_strip(html):
    return trade_section(html).split('<nav id="tradeTabs"', 1)[1].split('</nav>', 1)[0]


def orders_panel(html):
    return trade_section(html).split('id="tp-orders"', 1)[1].split('id="tp-sell"', 1)[0]


def orders_js(js):
    """the orders block only: its banner comment up to the next renderer"""
    return js.split(BANNER, 1)[1].split('function renderTiming()', 1)[0]


# ------------------------------------------------------------------- 1. the strip and the selection


def test_orders_sits_ahead_of_sell_and_sell_is_still_the_panel_that_opens():
    # 2026-09-29 (stage 3): the Trading Session took the first slot in the strip, so Orders is the
    # second button now - what this pin still holds is that Orders comes FIRST of the two ordering
    # decisions the 2026-09-28 pass made (ahead of Sell) and that the selection never moved with it.
    nav = tab_strip(INDEX)
    assert nav.index('id="tt-session"') < nav.index('id="tt-orders"') < nav.index('id="tt-sell"'), \
        'Session, then Orders, then Sell'
    assert ('<button role="tab" id="tt-orders" data-tp="tp-orders" aria-selected="false" '
            'aria-controls="tp-orders">Orders</button>') in nav
    # the selection did not move with the order: the sell plan is still the decision surface
    assert ('id="tt-sell" data-tp="tp-sell" aria-selected="true" aria-controls="tp-sell">Sell</button>'
            ) in nav
    sec = trade_section(INDEX)
    assert '<div id="tp-sell" class="tpanel" role="tabpanel" aria-labelledby="tt-sell">' in sec
    assert ('<div id="tp-orders" class="tpanel hidden" role="tabpanel" aria-labelledby="tt-orders">'
            ) in sec
    assert sec.index('id="tp-orders"') < sec.index('id="tp-sell"'), 'the panel precedes Sell'
    assert sec.count('class="tpanel" role="tabpanel"') == 1, 'exactly one panel ships visible'


def test_the_strip_keeps_every_tab_it_had():
    nav = tab_strip(INDEX)
    # 2026-09-29 (stage 3): 5 -> 6 for the Trading Session tab (the loop is the primary job); every
    # tab below kept its own exact button markup, Sell keeps the selection, nothing was dropped.
    assert nav.count('role="tab"') == 6
    for tid, tp, sel in (('tt-session', 'tp-session', 'false'), ('tt-orders', 'tp-orders', 'false'),
                         ('tt-sell', 'tp-sell', 'true'),
                         ('tt-buy', 'tp-buy', 'false'), ('tt-history', 'tp-history', 'false'),
                         ('tt-advanced', 'tp-advanced', 'false')):
        assert ('id="%s" data-tp="%s" aria-selected="%s" aria-controls="%s"'
                % (tid, tp, sel, tp)) in nav, tid
    sec = trade_section(INDEX)
    for pid in ('tp-session', 'tp-orders', 'tp-sell', 'tp-buy', 'tp-history', 'tp-advanced'):
        assert 'id="%s"' % pid in sec, pid


# ------------------------------------------------------------------- 2. the panel and its ids


def test_every_orders_id_rides_the_orders_panel():
    op = orders_panel(INDEX)
    for oid in ORDERS_IDS + CHIP_IDS:
        assert 'id="%s"' % oid in op, oid
    assert 'id="ordStatus"' in op, 'the chips ride their own row in the toolbar'
    # the toolbar: the search box, the live slug label, the rank picker, the refresh button meta
    assert 'placeholder="Item slug"' in op and '<option value="all">All ranks</option>' in op
    assert 'Refresh orders' in op and 'data-icon="arrows-clockwise"' in op
    # one job per head, in the WFM direction, and each list keeps its own label row
    assert 'Selling <span class="dim">- you would buy</span>' in op
    assert 'Buying <span class="dim">- you would sell</span>' in op
    assert op.count('class="ordrow ordrowhead"') == 2
    assert '<span>Plat</span><span>Qty</span><span>Rank</span><span>User</span>' in op
    # ladder first, then the two lists side by side in one grid, each scrolling on its own
    assert op.index('id="ordValues"') < op.index('id="ordSell"') < op.index('id="ordBuy"')
    assert 'class="ordlists"' in op and 'class="ordvals"' in op
    assert op.count('class="picks ordscroll"') == 2


def test_the_deep_link_opens_the_orders_panel():
    # #trade/orders resolves through the same sub-tab path every other trade tab uses
    assert "switchTradeTab(v === 'history' ? 'tp-history' : (sub ? 'tp-' + sub : 'tp-sell'));" in APP_JS
    assert "if (panelId === 'tp-orders') renderOrders();" in APP_JS, \
        'the book reads when its panel wins the strip'
    assert "switchTradeTab(t.dataset.tp);" in APP_JS
    assert "history.replaceState(null, '', '#trade/' + t.dataset.tp.replace('tp-', ''));" in APP_JS
    # a cold deep link lands before the sell plan does: the first load finishes that same open
    # (one fetch, and only for a panel that is really on screen)
    js = orders_js(APP_JS)
    assert 'function ordOpenFetch()' in js and APP_JS.count('ordOpenFetch();') == 1
    assert "if (!q || !tp || tp.classList.contains('hidden')) return;" in js
    assert 'if (ORD.data || ORD.ctl || !q.value.trim()) return;' in js


# ------------------------------------------------------------------- 3. the read


def test_the_book_reads_the_contract_and_aborts_the_previous_read():
    js = orders_js(APP_JS)
    assert "'/api/orders?item='" in js and "'&rank='" in js and "'&limit='" in js
    assert 'encodeURIComponent(slug)' in js and 'encodeURIComponent(rank)' in js
    assert 'if (ORD.ctl) ORD.ctl.abort();' in js, 'one book at a time'
    assert 'AbortController' in js and "err.name === 'AbortError'" in js
    assert 'if (!got || ORD.ctl !== ctl) return;' in js, 'an aborted or older answer never paints'
    assert 'setInterval' not in js and 'setTimeout' not in js, 'no polling on the order book'
    # it fetches on tab open, on the picker and on Refresh - the three wiring points
    assert "bind('ordRefresh', () => renderOrders());" in APP_JS
    assert "if (e.key === 'Enter') { e.preventDefault(); renderOrders(); }" in APP_JS
    assert "rk.addEventListener('change', () => { ORD.rank = rk.value; renderOrders(); });" in APP_JS
    # the search box opens on the top sell-plan item (and only while the user has not typed one)
    assert 'const plan = ((TRADER || {}).plan || {}).plan || [];' in js
    assert 'function ordPrefill()' in js and APP_JS.count('ordPrefill();') == 2, \
        'defined, called from load() and from renderOrders()'


def test_the_answer_lands_in_the_panel_or_prints_the_server_error():
    js = orders_js(APP_JS)
    # the meta line is counts + age + source + the status filter + how many rows are shown
    assert "'· ' + (c.sell || 0) + ' sell', '· ' + (c.buy || 0) + ' buy'" in js
    assert 'typeof d.age_s' in js and "d.source === 'cache'" in js
    assert "bits.push('· ' + ordStLabel());" in js
    assert "bits.push('· ' + ORD.shown + ' of ' + ORD.total + ' shown');" in js
    assert 'ORD.slug = d.item || slug;' in js
    # error line: the server reason verbatim, empty lists and an empty ladder behind it
    assert "ordErr('Orders: ' + reason);" in js
    assert 'const reason = d.error || d.reason || (got.res ? ' in js
    assert 'No orders for this item' in js, 'the empty state ships inside the panel'


# ------------------------------------------------------------------- 4. the status filter


def test_the_status_chips_are_toggles_with_their_counts():
    op = orders_panel(INDEX)
    for cid, st, pressed in (('ordStIngame', 'ingame', 'true'), ('ordStOnline', 'online', 'true'),
                             ('ordStOffline', 'offline', 'false'), ('ordStAll', 'all', 'false')):
        assert ('id="%s" data-st="%s" aria-pressed="%s"' % (cid, st, pressed)) in op, cid
    assert op.count('class="mcd-btn"') == 4, 'the cards page chip recipe, one chip per status'
    assert 'role="group" aria-label="Filter by trader status"' in op
    js = orders_js(APP_JS)
    # the count rides the chip, exactly as the rarity chips carry theirs
    assert "b.innerHTML = escHtml(st) + '<span class=\"mcd-rank\">'" in js
    assert "b.setAttribute('aria-pressed', String(!!ORD.st[st]));" in js


def test_ingame_and_online_are_on_and_offline_is_off_by_default():
    js = orders_js(APP_JS)
    assert 'st: { ingame: true, online: true, offline: false }' in js
    assert "const ORD_STS = ['ingame', 'online', 'offline'];" in js
    assert "if (on.length === ORD_STS.length) return 'all statuses';" in js
    assert "if (!on.length) return 'no status';" in js


def test_toggling_a_chip_repaints_from_the_fetched_rows_and_never_refetches():
    js = orders_js(APP_JS)
    wire = APP_JS.split("const st = document.getElementById('ordStatus');", 1)[1].split('})();', 1)[0]
    assert 'ordChips(ORD.data); ordPaint();' in wire, 'repaint from the last answer'
    assert 'renderOrders' not in wire and 'fetch(' not in wire, 'a toggle never refetches'
    # All clears the three, and clears means restores when they are already all on
    assert "if (key === 'all') {" in wire
    assert 'const on = ordStOn().length === ORD_STS.length;' in wire
    assert 'ORD_STS.forEach(s => { ORD.st[s] = !on; });' in wire
    assert 'else ORD.st[key] = !ORD.st[key];' in wire
    # and the filter is the paint step, over the rows already fetched
    assert "const keep = o => !!ORD.st[String(o.status || 'offline')];" in js
    assert 'const sellAll = d.sell || [], buyAll = d.buy || [];' in js
    assert 'ORD.total = sellAll.length + buyAll.length;' in js


def test_a_filter_that_empties_a_list_prints_that_lists_own_line():
    js = orders_js(APP_JS)
    assert "if (!total) return 'No orders for this item';" in js
    assert "if (!on.length) return 'No status picked';" in js
    assert "return 'No ' + on.join(' or ') + ' ' + side;" in js
    assert "ordEmptyLine('sellers', sellAll.length)" in js
    assert "ordEmptyLine('buyers', buyAll.length)" in js


def test_the_server_order_is_kept_inside_the_status_filter():
    js = orders_js(APP_JS)
    # price first (sell ascending, buy descending), then who can trade now, then freshest, then name
    assert 'const ORD_ST = { ingame: 0, online: 1, offline: 2 };' in js
    assert '|| (ORD_ST[a.status] ?? 3) - (ORD_ST[b.status] ?? 3)' in js
    assert '|| (b.updated_ts || 0) - (a.updated_ts || 0)' in js
    assert '|| String(a.user || ' in js
    assert 'sort((a, b) => ordSort(a, b, false))' in js and 'sort((a, b) => ordSort(a, b, true))' in js
    assert 'ordPaint' in js, 'both lists are painted from ORD.data'


# ------------------------------------------------------------------- 5. the two lists and the ladder


def test_the_two_lists_are_read_in_opposite_directions():
    js = orders_js(APP_JS)
    # sell ascends, buy descends - the direction lives in the ordSort call, never in a second sort
    assert 'ordSort(a, b, false)' in js and 'ordSort(a, b, true)' in js
    assert "sell.map(o => ordRow(o, 'sell'))" in js and "buy.map(o => ordRow(o, 'buy'))" in js
    # one row: price, quantity, rank chip, the ingameName, reputation, the status dot, the button
    assert 'class="ordp"' in js and 'class="ordq dim"' in js and 'class="ordr chip"' in js
    assert 'class="orduser"' in js and 'class="ordrep num dim"' in js
    assert '<i class="orddot ${escHtml(st)}"></i>' in js
    assert '${escHtml(user)}' in js, 'the username is rendered as text, escaped'
    assert 'class="ordres" aria-live="polite"' in js, 'the answer prints under its own row'
    assert 'data-st="${escHtml(st)}"' in js, 'the row says which status it belongs to'


def test_the_whisper_click_is_not_stolen_by_the_drawer_delegation():
    # the trade view opens the shared drawer for any row carrying data-slug: the order rows
    # carry none, so clicking Whisper can never open the drawer instead of whispering
    assert 'data-slug' not in orders_js(APP_JS)


def test_the_ladder_renders_the_values_map_by_rank():
    js = orders_js(APP_JS)
    assert 'const vals = (d && d.values) || {};' in js
    for key in ('v.ask', 'v.bid', 'v.n_ask', 'v.n_bid'):
        assert key in js, key
    assert 'Lowest sell' in js and 'Highest buy' in js and 'Sells' in js and 'Buys' in js
    assert 'ordLadder(d)' in js, 'the ladder is re-rendered on every answer'
    assert 'class="ordtbl"' in js
    assert "const ordPrice = v => (v === null || v === undefined || v === '') ? '—' : v + 'p';" in js, \
        'a rank with no bid prints a dash, never a bare p'


# ------------------------------------------------------------------- 5. the whisper


def test_one_whisper_per_click_posts_the_contract_body():
    js = orders_js(APP_JS)
    assert "fetch('/api/whisper', { method: 'POST'," in js
    assert "kind: btn.dataset.kind === 'sell' ? 'sell' : 'buy', mode: 'send' }" in js, \
        'the kind follows the list the row sits in, and the mode is always send'
    # 2026-09-29 (stage 3): a SESSION row states its own item (data-item), because the book keeps its
    # last-read slug and that is not the session row's item. The book's own path is unchanged: its
    # buttons carry no data-item, so ORD.slug still decides for every row of the book.
    assert 'const item = btn.dataset.item || ORD.slug ||' in js
    assert 'user: btn.dataset.user || ' in js and 'price: Number(btn.dataset.price) || 0' in js
    assert 'if (isFinite(rk)) body.rank = rk;' in js
    assert 'data-kind="${escHtml(kind)}"' in js and 'data-user="${escHtml(user)}"' in js
    # one click, one send: the button is disabled while the answer is in flight
    assert "btn.disabled = true; btn.textContent = 'Sending';" in js
    assert "btn.disabled = false; btn.textContent = old;" in js
    assert "closest('.ordwsp')" in APP_JS and 'if (b && !b.disabled) ordWhisper(b);' in APP_JS


def test_a_hidden_row_may_never_whisper():
    js = orders_js(APP_JS)
    assert 'if (!row || !btn.isConnected) return false;' in js
    # 2026-09-29 (stage 3): the status chips filter the BOOK's rows. The session panel renders the
    # same .ordrow/.ordwsp markup, so the filter is scoped to #tp-orders - a session row carries its
    # buyer's own status and that buyer must never be silently refused by a filter it does not show.
    assert "if (row.closest('#tp-orders') && !ORD.st[row.dataset.st || '']) return false;" in js, \
        'the filter gates the book, not the session'


def test_a_failed_whisper_shows_the_server_reason_and_never_claims_a_send():
    js = orders_js(APP_JS)
    assert "let say = 'no answer from the server', ok = false;" in js
    # an error answer prints the reason the response carried (or the status), nothing invented
    assert "if (!j || j.ok === false) say = (j && (j.reason || j.error)) || ('HTTP ' + r.status);" in js
    # and the two confirmations are read off the response, sent before copied
    assert 0 <= js.index("if (!j || j.ok === false)") < js.index("say = 'Sent to game'") \
        < js.index("say = 'Copied - game not running'")
    assert "say = j.reason || 'Not sent - nothing confirmed';" in js
    assert "res.classList.toggle('bad', !ok)" in js, 'a failed send wears the error tone'
    assert "catch (err) { /* nothing came back: the row may not claim a send */ }" in js


# ------------------------------------------------------------------- 6. density, fit and scroll


def test_the_book_is_dense_and_keeps_its_own_scrollers():
    assert ('#tp-orders .ordrow { display: grid; grid-template-columns: 56px 34px 44px '
            'minmax(0, 1fr) 44px 76px max-content;') in CSS
    assert '#tp-orders .ordlists { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr));' in CSS
    assert '#tp-orders .ordscroll { padding: 2px 0 8px; max-height: 44vh; overflow-y: auto;' in CSS
    assert '#tp-orders .ordrowhead { color: var(--muted); font-size: 10.5px; padding: 2px 5px;' in CSS
    assert 'body.shell-fit #view-trade #tp-orders .ordlists { flex: 1 1 auto; min-height: 0; }' in CSS
    assert ('body.shell-fit #view-trade #tp-orders .ordscroll { flex: 1 1 auto; min-height: 0; '
            'max-height: none; }') in CSS
    assert 'body.shell-fit #view-trade #tp-orders .ordvals { max-height: max(232px, 27vh); }' in CSS, \
        'all 11 ranks fit at 1280x800'
    # the status dot reads the same three states the run queue chips use
    assert '#tp-orders .orddot.ingame { background: var(--up, #4ade80); }' in CSS
    assert '#tp-orders .orddot.online { background: var(--accent); }' in CSS
    # the ladder owns its header, and a ladder a short window still cuts shows the soft bottom cue
    assert '#tp-orders .ordtbl th { position: sticky; top: 0;' in CSS
    assert '#tp-orders .ordvals.scrolly {' in CSS
    assert "document.querySelectorAll('#view-trade .picks, #view-trade #ordValues')" in APP_JS
    # the status chips keep the cards page recipe
    assert '#tp-orders #ordStatus .mcd-btn {' in CSS and '#tp-orders #ordStatus .mcd-rank {' in CSS
    # a narrow window stacks the two lists instead of clipping them
    assert '#tp-orders .ordlists { grid-template-columns: minmax(0, 1fr); }' in CSS
