"""Home layout (Jay 2026-09-26; the action surface, 2026-09-28).

Stage 3 (Jay 2026-09-28): *"Home should answer 'What should I sell? How much? Who wants it? How
much have I made today?' - and nothing else."*  Five bands, in this order and nothing else:

  TODAY        one strip: earned today / sales today / trades left / platinum now.  Every value
               renders exactly once on Home - the old hero band and the six-cell KPI grid are
               merged into the strip, and credits, items, sessions, materials, the week roll-up
               and inventory value ride the strip's detail disclosure (one tap).
  NEXT ACTION  the one best item: name, price, demand, sold-48h, liquidity, copies, and the buyer
               (or, when the run queue names nobody, a link into Trade's buyer surface).
  ALERTS       only actionable alerts; the card hides itself and the band above widens.
  SELL QUEUE   the next few DIFFERENT items, one quick action each.
  RECENT       the last trade events + the small platinum chart.

Nothing that used to be on Home left the app: game news is Tools > Game news
(tests/test_ia_reachability.py pins the slug), the session roll-up is Trade > History > Sessions.
"""
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def read(path):
    with open(os.path.join(ROOT, path), encoding='utf-8') as fh:
        return fh.read()


def home_section():
    return read('static/index.html').split('id="view-home"', 1)[1].split('</section>', 1)[0]


def home_js_block():
    js = read('static/app.js')
    return js.split('/* ---------- home ----------', 1)[1].split('/* ---------- history ----------', 1)[0]


# ------------------------------------------------------------------ the five bands, in order

def test_home_is_the_five_bands_in_this_order_and_nothing_else():
    home = home_section()
    order = ['id="homeHead"', 'id="todayCard"', 'id="homeSellNext"', 'id="alertsCard"',
             'id="sellQueueCard"', 'id="recentCard"', 'id="chartCard"']
    marks = [home.index(frag) for frag in order]
    assert marks == sorted(marks), 'TODAY / NEXT ACTION / ALERTS / SELL QUEUE / RECENT, in order'
    # exactly these cards - the band list is the whole column
    assert re.findall(r'<div class="card[^"]*" id="([A-Za-z0-9_-]+)"', home) == \
        ['todayCard', 'homeSellNext', 'alertsCard', 'sellQueueCard', 'recentCard', 'chartCard']


def test_the_analytics_cards_are_gone_from_default_home():
    """Every id below was a duplicate of a value that now renders once (see the stage 3 notes):
    heroCard / heroMeta / homeSync were the hero band's copy of platinum + the sync state, kpiCard
    was the six-cell grid merged into the Today strip, and newsCard/newsList moved to Tools."""
    home = home_section()
    for dead in ('id="heroCard"', 'id="heroMeta"', 'id="homeSync"', 'id="kpiCard"',
                 'id="newsCard"', 'id="newsList"', 'class="h-cols"', 'class="h-col"'):
        assert dead not in home, dead


def test_the_strip_holds_every_number_once():
    js = home_js_block()
    assert 'function renderTodayStrip()' in js
    for label in ('Earned today', 'Sales today', 'Trades left', 'Platinum now'):
        assert js.count('>%s<' % label) == 1, label
    for ident in ('todayEarned', 'todaySales', 'todayTrades', 'platinumNow'):
        assert js.count('id="%s"' % ident) == 1, ident
    # the strip is the only place a day value renders: no second platinum or trades reading
    assert js.count('id="platinumNow"') == 1
    assert 'renderKpis' not in js and 'renderHomeHero' not in js


def test_the_band_order_is_the_markup_order():
    html = read('static/index.html')
    assert html.index('<!-- TODAY') < html.index('<!-- NEXT ACTION') < html.index('<!-- ALERTS')
    assert html.index('<!-- ALERTS') < html.index('<!-- SELL QUEUE') < html.index('<!-- RECENT')


def test_game_news_moved_to_tools_with_the_same_list_id():
    html = read('static/index.html')
    tools = html.split('id="view-tools"', 1)[1]
    assert 'id="tws-news"' in tools and 'data-tool="news"' in tools
    assert 'id="newsList"' in tools.split('id="tws-news"', 1)[1].split('</section>', 1)[0]
    assert 'href="#tools/news" data-tool="news"' in tools
    # the news renderer survives, now that the card lives in another section
    assert 'const NEWS_ROWS = 8;' in read('static/app.js')
    assert '(n.items || []).slice(0, NEWS_ROWS)' in read('static/app.js')


# ------------------------------------------------------------------ the strip's detail disclosure

def test_today_rows_are_label_and_value_with_detail_on_hover():
    js = read('static/home.js')
    assert "const l1 = add(row, 'div', 'h-l1')" in js
    assert "add(l1, 'span', 'h-name', label)" in js
    assert "const cell = add(l1, 'span', 'h-act')" in js
    assert "if (tip) row.setAttribute('title', clip(tip, 220))" in js


def test_today_detail_keeps_every_value_the_old_cards_showed():
    """The strip shows the day; everything the merged-away cards held is one tap below (or in a
    card's own hover) - credits, items, sessions, materials, the week roll-up, inventory value."""
    js = read('static/home.js')
    assert "get('/api/feature/progress')" in js
    assert 'renderTodayCells(d.progress)' in js and 'renderTodayDetail(today, d.progress)' in js
    assert "const UNKNOWN = '-'" in js                     # a null reading renders '-', not 0
    for field in ('plat_delta', 'credits_delta', 'items_added', 'items_removed',
                  'materials_gained', 'plat_this_week', 'trades_this_week', 'hours_this_week'):
        assert field in js, field
    assert 'noteFor(notes' in js                           # the store's own reason in the title=
    assert "'Credits'" in js and "'Inventory value'" in js and "'Materials'" in js


def test_today_lists_five_sessions_on_one_line_each():
    js = read('static/home.js')
    assert 'const SESSIONS_SHOWN = 5;' in js
    assert 'const sessionRow = (s) =>' in js
    assert "s.current ? ['live', 'upl'] : null" in js      # live marker for a running session
    assert 'rangeTxt(s.start_ts, s.end_ts)' in js          # short date/time range
    assert "add(row, 'span', 'h-num', sm ? dur(sm) : '')" in js


def test_today_stays_condensed():
    js = read('static/home.js')
    assert 'const MATERIALS_SHOWN = 3;' in js
    assert 'const SESSIONS_SHOWN = 5;' in js


def test_today_degrades_when_the_progress_store_is_missing():
    js = read('static/home.js')
    assert "'Not available yet'" in js


# ------------------------------------------------------------------ next action

def test_next_action_shows_price_demand_liquidity_and_copies():
    js = home_js_block()
    for frag in ('<div class="next-one">', '<div class="next-pr">', '<div class="next-facts">',
                 '<div class="nf-l">Demand</div>', '<div class="nf-l">Sold 48h</div>',
                 '<div class="nf-l">Liquidity</div>'):
        assert frag in js, frag
    assert "copies + (copies === 1 ? ' copy' : ' copies')" in js
    assert 'homeBuyers(r.slug)' in js, 'the buyer line reads the run queue payload Home already has'


def test_next_action_links_to_trade_when_no_buyer_is_known():
    """One link on the card, and it says what it opens: with a named buyer the head action opens
    Trade, with nobody named the head action IS the buyers surface (never a second CTA)."""
    js = home_js_block()
    html = read('static/index.html')
    assert "open.textContent = b ? 'Open Trade' : 'See buyers in Trade';" in js
    assert '<a class="home-open" href="#trade">' in html
    assert '>No buyer in the run queue<' in js, 'the footer states the gap instead of inventing one'


# ------------------------------------------------------------------ sell queue + alerts + recent

def test_the_sell_queue_lists_different_items_with_one_action_each():
    js = home_js_block()
    assert 'const QUEUE_ROWS = 5;' in js
    assert 'if (seenSlug[key]) return;' in js, 'a plan can carry one item twice - Home lists it once'
    assert "'\\u203a'" in js or 'hnext-chev' in js
    assert '<a class="hnext-row" href="#trade"' in js, 'every row is one quick action'
    assert '<span class="hnext-dm">Sold 48h</span>' in js and '<span class="hnext-pr">List at</span>' in js


def test_the_alerts_card_collapses_quietly_when_there_is_nothing_to_do():
    js = read('static/home.js')
    assert "main.classList.toggle('no-alerts', !alerts.length)" in js
    assert 'wrap.classList.add' in js and "'hidden'" in js
    assert 'buildAlerts(d)' in js
    assert 'Nothing is posted automatically' in js and "'Not live - plan only'" in js


def test_recent_lists_trade_events_and_the_optional_chart_is_untouched():
    js = read('static/home.js')
    assert 'const RECENT_EVENTS = 10;' in js
    assert "((d.trades && d.trades.events) || [])" in js
    css = read('static/home.css')
    assert 'no-alerts' in css, 'the empty-alert state widens the action band'


# ------------------------------------------------------------------ the window fit

def test_the_home_grid_fits_the_window_in_five_bands():
    css = read('static/home.css')
    assert 'grid-template-columns: repeat(3, minmax(0, 1fr));' in css
    assert 'grid-template-rows: auto auto minmax(0, auto) minmax(0, auto) minmax(112px, 1fr);' in css
    for band in ('#homeHead', '#todayCard', '#sellQueueCard'):
        assert 'body.shell-fit #homeMain > %s' % band in css, band
    assert 'body.shell-fit #homeMain > #homeSellNext { grid-column: 1 / span 2; }' in css
    assert 'body.shell-fit #homeMain > #alertsCard { grid-column: 3; }' in css
    assert 'body.shell-fit #homeMain > #recentCard { grid-column: 1 / span 2; }' in css
    assert 'body.shell-fit #homeMain > #chartCard { grid-column: 3; }' in css
    assert 'body.shell-fit #homeMain.no-alerts > #homeSellNext { grid-column: 1 / -1; }' in css
    # the long lists scroll inside their own card; the chart grows into its column
    assert 'flex: 1 1 auto; min-height: 0; overflow-y: auto; overscroll-behavior: contain;' in css
    assert 'body.shell-fit #view-home .chartwrap { flex: 1 1 auto; height: auto; min-height: 56px; margin: 4px 12px 0; }' in css


def test_the_strip_collapses_to_two_columns_on_narrow_windows():
    css = read('static/home.css')
    assert '@media (max-width: 1040px)' in css
    block = css.split('@media (max-width: 1040px)', 1)[1].split('}', 4)[0]
    assert 'grid-template-columns: repeat(2, minmax(0, 1fr));' in block


def test_home_reserves_no_rail_for_the_chat_dock():
    """The chat dock is chat.css's own collapsible column (stage 3): home.css must not mention it,
    or a closed dock would leave a dead gap where the rail used to be."""
    css = read('static/home.css')
    assert 'chatDock' not in css and 'chat-open' not in css and 'chat-docked' not in css
    assert 'position: sticky' not in css


# ------------------------------------------------------------------ chart axis honesty

def test_platinum_axis_never_shows_a_negative_tick():
    js = read('static/chart.js')
    assert 'y0 = Math.max(0, y0 - padY)' in js
    assert "for (var v = Math.ceil(S.y0 / step) * step; v <= S.y1; v += step)" in js  # gridlines start at y0 >= 0
    assert "niceStep" in js                                                          # round gridline steps


def test_long_spans_label_the_year():
    js = read('static/chart.js')
    assert "if (spanS <= 120 * 86400) return d.toLocaleDateString([], { month: 'short', day: 'numeric' });" in js
    assert "String(d.getFullYear()).slice(2)" in js


def test_axis_labels_are_readable_and_cannot_clip():
    js = read('static/chart.js')
    assert "Math.round(v).toLocaleString('en-AU')" in js           # 9,150p not 9150p
    assert "ctx.textAlign = i === 0 ? 'left' : (i === nT - 1 ? 'right' : 'center');" in js  # end ticks anchor inward


# ------------------------------------------------------------------ the honest default range

def test_the_chart_opens_on_a_clean_month_and_never_draws_through_a_gap():
    """Jay 2026-09-28: the widest range flattened the line (175 snapshots since May 2024 with
    month-long holes), so the Home card opens on 30d. Every range button (24h / 7d / 30d / All)
    still overrides it, a stored choice still wins, and the renderer breaks the line where the
    collected data has a real gap instead of drawing a straight line through the hole."""
    chart = read('static/chart.js')
    assert "range: '30d', style: 'area', palette: 'accent', gapS: 172800," in chart   # the Home default
    assert "var pref = prefStore(key, { style: opts.style || 'area'," in chart        # saved choice wins
    assert "range: opts.range || 'all' });" in chart
    assert 'var gapS = Number(opts.gapS) || 0;' in chart                              # opt-in, other charts unchanged
    assert 'var runs = (gapS > 0) ? splitRuns(ps, gapS) : [ps];' in chart             # the line stops at a gap
    assert 'var lp = ps[ps.length - 1]' in chart                                      # the end dot follows the last run


def test_the_home_chart_is_sized_by_its_box_not_by_a_stale_measurement():
    """Stage 3: the wrapper used to pass height: <whatever the wrap measured at init>, which
    outranked the live box forever - the canvas was drawn 717px tall inside a 271px card and only
    its top sliver showed. Sizing is left to sizeCanvas(), which reads the wrap at every draw."""
    chart = read('static/chart.js')
    assert 'height: c.parentElement' not in chart
    assert 'var h = Math.max(56, opts.height || (wrap ? wrap.clientHeight : 0) || 200);' in chart
