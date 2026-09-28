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


def test_trades_left_only_shows_a_reading_that_covers_today():
    """The strip read SUMMARY.trades alone, so it printed '-' on every machine whose save does not
    carry TradesRemaining (the local one included). It now falls back to the limits reading - but
    only while that reading still describes TODAY's window: the allowance resets daily, so an
    older reading is not today's number and must stay '-' (screenshot review 2026-09-28: show it
    when the payload really carries it, never invent it)."""
    js = read('static/app.js')
    block = js.split('function tradesLeftReading()', 1)[1].split('function renderTodayStrip', 1)[0]
    assert 'if (s.trades !== null && s.trades !== undefined)' in block, 'the save is the first basis'
    assert 'const L = FEAT.limits || {};' in block
    assert "L.status === 'OK'" in block
    assert '(!L.reset_epoch || now < L.reset_epoch)' in block, 'an older window is not today'
    assert "return { v: null, tip: 'no reading for today: the allowance resets daily' + last };" in block
    assert 'last reading ' in block
    # the cell renders the reading or the dash - nothing else, and the why is one hover away
    assert 'id="todayTrades" title="${escHtml(tl.tip)}">${tl.v ?? ' in js


def test_the_first_run_banner_only_speaks_when_there_is_truly_no_data():
    """The banner read `!lastdata_mtime || !items`, so an EMPTY inventory table (items: 0) turned it
    on while a 1,022p balance, a sell queue, 471 history events and the price feed were all
    present (screenshot review, 2026-09-28). It may only render when every signal is absent -
    a fresh clone with no data/ at all."""
    js = read('static/app.js')
    block = js.split('function hasAnyData(s)', 1)[1].split('function renderFirstRun', 1)[0]
    for signal in ('s.lastdata_mtime', 's.prices_mtime', 's.items', 's.total_value',
                   's.by_cat', 'plat_hist'):
        assert signal in block, signal
    assert 'const empty = !hasAnyData(SUMMARY);' in js
    assert 'const empty = !s.lastdata_mtime || !s.items;' not in js, 'one empty field is not "no data"'
    # the banner still exists, still guarded, still points at the setup entry point
    assert 'function renderFirstRun' in js and "getElementById('firstRun')" in js
    assert 'setup.bat' in js and 'renderFirstRun();' in js


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


def test_next_action_is_the_one_primary_action_on_home():
    """Screenshot review 2026-09-28: NEXT ACTION had to be the one obvious thing. Its button is the
    page's only accent-filled control, the shell's Refresh drops to the quiet weight on the SPA
    (it was the loudest thing on the page), and the action card's three metric cells got real
    padding and a readable value size instead of hugging their dividers."""
    css = read('static/home.css')
    open_rule = css.split('#view-home .home-open {', 1)[1].split('}', 1)[0]
    assert 'background: linear-gradient(180deg, color-mix(in srgb, var(--accent) 92%, white 8%), var(--accent));' in open_rule
    assert 'box-shadow: 0 2px 10px color-mix(in srgb, var(--accent) 25%, transparent);' in open_rule
    assert 'body[data-shell="index"] header #refresh {' in css
    assert 'body[data-shell="index"] header #refresh::after { content: none; }' in css
    fact = css.split('#view-home .next-fact {', 1)[1].split('}', 1)[0]
    assert 'padding: 9px 16px 10px' in fact
    assert '#view-home .nf-v { margin-top: 4px; font-size: 15px;' in css
    assert '#view-home .nf-l { font-size: 10.5px;' in css


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


def test_recent_is_newest_first_and_a_note_never_reads_as_the_newest_trade():
    """Screenshot review 2026-09-28: "History tracking started" (a log note, Sep 25) sat above
    year-old sales and the card's line said "latest Sep 25", so the note read as the newest trade.
    The list is sorted newest-first itself (never trusting the payload's order) and a note renders
    as a note row - three columns, no qty/price cells - so the line under the title states the
    ordering and never prints a second copy of a row's own time."""
    js = read('static/home.js')
    assert '.sort((a, b) => (Number(b.ts) || 0) - (Number(a.ts) || 0))' in js
    assert "setMeta('recentMeta', ' · newest first · notes are not trades');" in js
    assert "const row = el('div', isNote ? 'h-ev h-note' : 'h-ev');" in js
    assert "if (isNote) {" in js
    css = read('static/home.css')
    assert '.h-ev.h-note { grid-template-columns: max-content minmax(0, 1fr) max-content; }' in css
    assert '.h-ev.h-note .badge { background: var(--panel2); }' in css


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

def test_the_chart_opens_on_the_last_week_and_never_draws_through_a_gap():
    """Jay 2026-09-28 (evening): 'fix the graph'. The 30d default on a history that only holds
    readings for the last three and a half days drew a three-day axis under a 30d pill, with the
    line glued to the floor. The card opens on 7d now - the window that holds the real movement -
    and a range pill promises its own span: with 30d selected the axis really is thirty days wide,
    the line shows where readings exist, a lone reading draws as a dot instead of vanishing, and
    the line still breaks at a real gap. The prefs key moved to v2 so ranges stored while the axis
    ignored them do not pin anyone to the old view."""
    chart = read('static/chart.js')
    assert "range: '7d', style: 'area', palette: 'accent', gapS: 172800," in chart    # the Home default
    assert "var LS_KEY = 'wfm_chart_v2';" in chart                                    # stored v1 choices retired
    assert 'if (win && win.span > 0) { x1 = win.end; x0 = win.end - win.span; }' in chart  # the axis honours the range
    assert 'winState = { span: span, end: t1 };' in chart                             # set only on a real clip
    assert 'ctx.arc(S.X(one.ts), S.Y(one.v), 2.4, 0, Math.PI * 2);' in chart          # lone readings draw
    assert "var pref = prefStore(key, { style: opts.style || 'area'," in chart        # saved choice wins
    assert "range: opts.range || 'all' });" in chart
    assert 'var gapS = Number(opts.gapS) || 0;' in chart                              # opt-in, other charts unchanged
    assert 'var runs = (gapS > 0) ? splitRuns(ps, gapS) : [ps];' in chart             # the line stops at a gap
    assert 'var lp = ps[ps.length - 1]' in chart                                      # the end dot follows the last run


def test_the_chart_footer_reports_the_window_it_is_showing():
    """The footer used to quote the whole history at every range ('182 readings · every 15 min'
    against a 7-day plot), which read as missing data. The chart reports its window through onView
    and the footer names it; the cadence lives in the tooltip, where it is true."""
    app = read('static/app.js')
    chart = read('static/chart.js')
    assert 'readings · from ${d(v.first_ts)}' in app          # names the window on screen
    assert 'readings · every 15 min' not in app               # the cadence claim is gone
    assert 'PlatChart.setViewHook(function (v) { window.__chartView = v; renderChartMeta(); });' in app
    assert "if (typeof opts.onView === 'function') {" in chart   # the chart reports its view
    assert 'sig !== lastSig' in chart                            # hover redraws do not chatter


def test_the_home_chart_is_sized_by_its_box_not_by_a_stale_measurement():
    """Stage 3: the wrapper used to pass height: <whatever the wrap measured at init>, which
    outranked the live box forever - the canvas was drawn 717px tall inside a 271px card and only
    its top sliver showed. Sizing is left to sizeCanvas(), which reads the wrap at every draw."""
    chart = read('static/chart.js')
    assert 'height: c.parentElement' not in chart
    assert 'var h = Math.max(56, opts.height || (wrap ? wrap.clientHeight : 0) || 200);' in chart
