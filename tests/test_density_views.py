"""Fit the viewport on the five index views (Jay 2026-09-27): "everything needs to fit on this
screen, no matter the resolution for the user".

Source-level pins for the layout the QA probe measures headlessly (qa_fit_matrix.js): from 1200px
up the shell is one window tall and does not scroll - header + nav + the active view + the footer
fill 100vh - and each long list scrolls inside its own card, so the card head (title, meta, filter
pills) and the card footer stay put. Under 1200px nothing changes: the page scrolls as it always
did, one column, and the wide tables scroll inside their own .tablewrap.

Also pinned here: the dense row budget (<= 28px a row, the #view-trade recipe) in each of the five
views, the ids/controls other tests and the probe hook onto, and the one-visible-view rule that was
broken by the home/chat id-specificity clash (a hidden view must really be hidden).

Measured (qa_fit_matrix.js, docScroll vs window.innerHeight, 0 horizontal overflow, 0 console
errors at every width) - all six views FIT at 1920x1080, 1600x900, 1536x864, 1440x900, 1366x768 and
1280x800; under 1200px the page scrolls normally by design.
"""
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(rel):
    with open(os.path.join(REPO, rel), encoding='utf-8') as fh:
        return fh.read()


def media_blocks(css, query):
    return [b.split('\n}', 1)[0] for b in css.split('@media (%s) {' % query)[1:]]


# ------------------------------------------------------------------ the shell fits one window

def test_index_ships_the_fit_shell_class():
    html = read('static/index.html')
    assert '<body class="shell-fit" data-shell="index"' in html


def test_the_shell_is_one_window_tall_and_does_not_scroll():
    css = read('static/style.css')
    assert 'body.shell-fit { display: flex; flex-direction: column; height: 100vh; overflow: hidden; }' in css
    assert ('body.shell-fit > .shellbody { flex: 1 1 auto; min-height: 0; display: flex; align-items: stretch; }'
            in css)
    assert 'body.shell-fit .shellbody > main { flex: 1 1 auto; min-height: 0; padding: 12px 22px; }' in css
    assert ('body.shell-fit main > section:not(.hidden) {\n'
            '    height: 100%; min-height: 0; overflow-y: auto; overflow-x: hidden; overscroll-behavior: contain; scrollbar-gutter: stable;\n'
            '  }') in css


def test_a_hidden_view_is_really_hidden():
    """home.css/chat.css style #view-home.chat-docked (id + class) which outranks .hidden, so the
    home cards stayed on screen under every other view. One visible section, as showView() intends."""
    css = read('static/style.css')
    assert 'main > section.hidden { display: none !important; }' in css


def test_the_fit_rules_are_desktop_only():
    """Every fit rule sits in a min-width: 1200px block - phones and tablets keep the scrolling
    page (the phone blocks at 1040/900/560px are untouched)."""
    css = read('static/style.css')
    fit_start = css.index('/* ============ fit the viewport')
    fit = css[fit_start:]
    assert fit.strip().startswith('/* ============ fit the viewport')
    assert '@media (min-width: 1200px) {' in fit
    # nothing in the fit block may target a phone width
    assert '(max-width: 1199px)' not in fit and '(max-width: 900px)' not in fit
    assert '@media (max-width: 560px)' not in fit
    assert '@media (max-width: 1040px)' in read('static/home.css')


def test_the_fit_block_comes_after_the_trade_density_block():
    """test_trade_density splits on the FIRST min-width:1200/1500px block - the trade pins must
    keep pointing at the trade rules."""
    css = read('static/style.css')
    assert css.index('.trade-ops { display: grid; grid-template-columns: minmax(0, 1fr);') < \
        css.index('/* ============ fit the viewport')
    assert css.index('.trade-ops { grid-template-columns: repeat(3, minmax(0, 1fr)); }') < \
        css.index('body.shell-fit #view-player .p-cols { grid-template-columns: repeat(3, minmax(0, 1fr)); }')


# ------------------------------------------------------------------ each view is bounded + scrolls

def test_home_fills_the_left_column_beside_the_chat_rail():
    css = read('static/home.css')
    assert 'body.shell-fit #view-home.chat-docked {' in css
    assert 'grid-template-rows: minmax(0, 1fr); align-items: stretch;' in css      # the chat rail owns its own column
    assert 'body.shell-fit #view-home #homeMain {' in css
    # the clean pass order: header row, hero, the alert surface, the KPI grid, then sell next
    # beside the chart, then the three lists sharing the last band
    assert 'grid-template-rows: auto auto auto auto auto minmax(112px, 1fr);' in css
    for band in ('#homeHead', '#heroCard', '#alertsCard', '#kpiCard'):
        assert ('body.shell-fit #homeMain > %s' % band) in css, band
    assert 'body.shell-fit #homeMain > #homeSellNext { grid-column: 1; }' in css
    assert 'body.shell-fit #homeMain > #chartCard { grid-column: 2 / -1; }' in css
    # the alert cap is a safety net (three alerts fit whole); short windows use the tighter cap
    assert 'body.shell-fit #homeMain > #alertsCard { max-height: min(420px, 45vh); }' in css
    assert 'body.shell-fit #homeMain > #alertsCard { max-height: 17vh; }' in css
    assert 'body.shell-fit #homeMain > .h-cols {' in css
    assert 'grid-template-columns: repeat(3, minmax(0, 1fr)); grid-template-rows: minmax(0, 1fr);' in css
    assert 'body.shell-fit .h-cols > .h-col { display: contents; }' in css        # news / today / recent side by side
    for card, list in (('#newsCard', '#newsCard > .picks'), ('#todayCard', '#todayCard > .picks'),
                       ('#recentCard', '#recentCard > .picks'), ('#homeSellNext', '#homeSellNext > .picks')):
        assert card in css, card
        assert list in css, list
    # the lists scroll inside their cards; the chart keeps a readable, window-relative height
    assert 'flex: 1 1 auto; min-height: 0; overflow-y: auto; overscroll-behavior: contain;' in css
    assert 'body.shell-fit #view-home .chartwrap { height: clamp(84px, 10vh, 140px); margin: 4px 12px 0; }' in css


def test_inventory_keeps_the_table_and_gives_the_three_cards_their_own_band():
    css = read('static/style.css')
    html = read('static/index.html')
    assert 'body.shell-fit #view-inventory {\n    display: grid;' in css
    assert 'grid-template-rows: auto auto minmax(150px, 1fr) auto minmax(150px, 0.62fr);' in css
    assert 'body.shell-fit #view-inventory > .tablewrap { max-height: none; min-height: 0; }' in css
    assert 'body.shell-fit .inv-lower {\n    display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; min-height: 0;\n  }' in css
    assert 'body.shell-fit .inv-lower > .invpanels { display: contents; }' in css
    assert 'body.shell-fit .inv-lower .tablewrap { max-height: none; flex: 1 1 auto; min-height: 0; }' in css
    assert 'body.shell-fit .inv-lower #diffList { flex: 1 1 auto; min-height: 0; overflow-y: auto; }' in css
    # the Materials / Clan Dojo / Inventory changes cards share one band (one wrapper, cards first)
    band = html.split('<div class="inv-lower">', 1)[1]
    for frag in ('<div class="invpanels">', 'id="matCard"', 'id="dojoCard"', 'id="diffList"'):
        assert frag in band.split('</section>', 1)[0], frag


def test_mastery_queue_and_type_bars_share_the_row():
    css = read('static/style.css')
    assert 'body.shell-fit #view-mastery {\n    display: grid; grid-template-columns: minmax(0, 1.55fr) minmax(0, 1fr);' in css
    block = css.split('/* ================= MASTERY', 1)[1].split('/* ================= PLAYER', 1)[0]
    for frag in ('body.shell-fit #mhCard { grid-column: 1 / -1; grid-row: 1; }',
                 'body.shell-fit #mhNextCard { grid-column: 1; grid-row: 2; }',
                 'body.shell-fit #mhCatsCard { grid-column: 2; grid-row: 2; }',
                 'body.shell-fit #mhNext, body.shell-fit #mhCats {\n'
                 '    flex: 1 1 auto; min-height: 0; overflow-y: auto; overscroll-behavior: contain;\n  }'):
        assert frag in block, frag


def test_player_card_columns_and_the_syndicate_list_scroll():
    css = read('static/style.css')
    html = read('static/index.html')
    assert 'body.shell-fit #view-player .p-cols {\n    display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);' in css
    assert 'body.shell-fit #view-player #pcSyn { flex: 1 1 auto; min-height: 0; overflow-y: auto; }' in css
    assert 'body.shell-fit #view-player #pcTop { flex: 1 1 auto; min-height: 0; overflow-y: auto; }' in css
    assert 'body.shell-fit #view-player .p-col { min-height: 0; overflow-y: auto; overflow-x: hidden; }' in css
    band = html.split('<div class="p-cols">', 1)[1].split('</section>', 1)[0]
    assert band.count('class="p-col') == 3
    for frag in ('id="pcHead"', 'id="pcClan"', 'id="pcSyn"', 'id="pcInt"', 'id="pcFocus"', 'id="pcMarket"'):
        assert frag in band, frag
    assert band.count('class="card"') == 6, 'the six player cards are all still there'


def test_more_groups_become_bands_and_every_card_list_scrolls():
    css = read('static/style.css')
    assert 'body.shell-fit #view-more { display: flex; flex-direction: column; }' in css
    assert 'body.shell-fit #view-more details.acc[open]::details-content {' in css
    assert 'display: grid; grid-template-columns: repeat(2, minmax(0, 1fr));' in css
    assert ('body.shell-fit #view-more details.acc[open] > .card > div[id] {\n'
            '    flex: 1 1 auto; min-height: 0; overflow-y: auto; overscroll-behavior: contain;\n  }') in css
    wide = css.split('/* wide windows: the same bands go three across', 1)[1]
    assert 'body.shell-fit #view-more details.acc[open]::details-content {\n    grid-template-columns: repeat(3, minmax(0, 1fr));' in wide


def test_trade_fills_the_window_without_losing_its_own_rules():
    css = read('static/style.css')
    assert ('body.shell-fit #view-trade {\n'
            '    display: grid; grid-template-rows: auto minmax(200px, 1.7fr) auto minmax(140px, 0.8fr);\n  }') in css
    for frag in ('body.shell-fit #view-trade > .tpanel:not(.hidden) {',
                 'body.shell-fit #view-trade #planList, body.shell-fit #view-trade #heldAcc {',
                 'body.shell-fit #view-trade #runqList { flex: 1 1 auto; min-height: 0; overflow-y: auto; }'):
        assert frag in css, frag
    # the trade density values the other test pins must be untouched
    assert '#view-trade .prow { padding: 6px 5px; font-size: 12.5px; line-height: 1.45; }' in css
    assert '#view-trade .heldline { padding: 6px 5px; font-size: 12px; line-height: 1.45; gap: 10px; }' in css


# ------------------------------------------------------------------ the row budget (<= 28px)

def test_the_rows_keep_the_spaced_budget():
    """The fit pass bought room with 3px rows, which read as cramped once the lists scrolled
    inside their cards. Jay 2026-09-27: "can we get better spacing for the cards?" - the trade
    recipe moved to 6px padding / 1.45 line-height (.prow 31.1 / .heldline 30.4 / .mh-row 31.7 /
    .mh-cat 31.1 / .pc-syn 31.1 / .dealrow 31.1 / .srow 31.1 / .mrow 31.1, <= 34px a row).

    The home clean pass (2026-09-28) then took the home rows to 9px padding / 2px sub-line gap,
    measured at 1920x1080: .h-row 37.8 / .newsrow 36.7 / .h-ev 39.2 / .hnext 36.8, .h-alert 61.4
    (two lines), .h-sess 77.5 (a session roll-up), .kpi 58.3. The home column still fits the
    window at 1920/1536/1440/1366/1280 (pageOver 0, every long list scrolls inside its card)."""
    css = read('static/style.css') + read('static/home.css')
    for frag in ('.h-row {\n  display: grid; grid-template-columns: minmax(0, 1fr); gap: 2px;\n'
                 '  padding: 9px 6px; font-size: 12.5px;',
                 'align-items: baseline; padding: 9px 6px;',                      # .newsrow
                 'gap: 10px; align-items: center; padding: 9px 6px; font-size: 12.5px;',  # .h-ev
                 '.h-alert { padding: 10px 6px 10px 18px; position: relative;',
                 'body.shell-fit #view-more .mrow { padding: 6px 10px; font-size: 12.5px; line-height: 1.45; }',
                 '#mhNext .mh-row { padding: 6px 12px; font-size: 12.5px; line-height: 1.45; }',
                 '#mhCats .mh-cat { padding: 6px 12px; font-size: 12.5px; line-height: 1.45; }',
                 'body.shell-fit #view-player .pc-syn { padding: 6px 10px; font-size: 12.5px; line-height: 1.45; }',
                 'body.shell-fit #view-player .pc-frow { padding: 6px 10px; font-size: 12.5px; line-height: 1.45; }',
                 'body.shell-fit #view-more .dealrow, body.shell-fit #view-more .srow,',
                 'body.shell-fit #view-inventory .mrow { padding: 6px 10px; font-size: 12.5px; line-height: 1.45; }',
                 'body.shell-fit #view-inventory thead th { padding: 8px 10px; font-size: 11px; }'):
        assert frag in css, frag
    # the phone rows keep their own sizing (nothing in this pass touched the 560px block)


def test_card_chrome_is_the_shared_dense_recipe():
    css = read('static/style.css')
    assert ('#view-home .card-head, #view-inventory .card-head, #view-mastery .card-head,\n'
            '  #view-player .card-head, #view-more .card-head { padding: 8px 12px 5px; gap: 10px; '
            'flex-wrap: wrap; }') in css
    assert ('#view-home .picks, #view-inventory .picks, #view-mastery .picks,\n'
            '  #view-player .picks, #view-more .picks { padding: 6px 12px 10px; }') in css
    # the shared shell values other tests pin are untouched
    assert '.picks { padding: 10px 16px 14px; }' in css


# ------------------------------------------------------------------ ids + controls that must survive

def test_every_id_and_control_survives():
    html = read('static/index.html')
    for view, frags in (
        ('view-home', ('id="homeHead"', 'id="homeSync"', 'id="heroCard"', 'id="platinumNow"', 'id="heroMeta"',
                       'id="kpis"', 'id="kpiCard"', 'id="homeSellNext"', 'id="sellNextList"', 'id="sellNextMeta"',
                       'id="chartCard"', 'id="platChart"', 'id="ranges"', 'id="chartMeta"',
                       'id="alertsCard"', 'id="homeAlerts"', 'id="newsCard"', 'id="newsList"',
                       'id="todayCard"', 'id="homeToday"', 'id="recentCard"', 'id="homeRecent"')),
        ('view-inventory', ('id="tabs"', 'id="totals"', 'id="invQ"', 'id="btnCols"', 'id="tbl"', 'id="rows"',
                            'id="status"', 'id="matCard"', 'id="matQ"', 'id="matView"', 'id="matSort"',
                            'id="matTbl"', 'id="matRows"', 'id="matCap"', 'id="dojoCard"', 'id="dojoTier"',
                            'id="dojoTbl"', 'id="dojoRows"', 'id="dojoNote"', 'id="dojoRooms"', 'id="dojoSrc"',
                            'id="diffList"')),
        ('view-mastery', ('id="mhCard"', 'id="mhHead"', 'id="mhStats"', 'id="mhNextCard"', 'id="mhNext"',
                          'id="mhFilters"', 'id="mhCap"', 'id="mhCatsCard"', 'id="mhCats"')),
        ('view-player', ('id="pcHead"', 'id="pcStats"', 'id="pcTop"', 'id="pcClan"', 'id="pcSyn"',
                         'id="pcInt"', 'id="pcFocus"', 'id="pcMarket"')),
        ('view-more', ('id="dealsList"', 'id="moversList"', 'id="trendsList"', 'id="ducatsList"',
                       'id="craftList"', 'id="relicsList"', 'id="setsList"', 'id="nudgesList"',
                       'id="wlList"', 'id="rivensList"', 'id="baroList"', 'id="metaList"')),
        ('view-trade', ('id="planList"', 'id="heldList"', 'id="attnList"', 'id="hygieneList"', 'id="runqList"',
                        'id="killList"', 'id="notifyList"', 'id="limList"', 'id="btnPlan"', 'id="btnCycle"',
                        'id="btnWatch"', 'id="btnHygiene"', 'id="btnRunq"', 'id="btnKill"', 'id="btnNotify"',
                        'id="killNote"')),
    ):
        section = html.split('id="%s"' % view, 1)[1].split('</section>', 1)[0]
        for frag in frags:
            assert frag in section, (view, frag)


def test_the_filter_pills_and_buttons_stay_outside_the_scrollers():
    """The scrolling parts are the data lists - heads, filters and action buttons are fixed."""
    html = read('static/index.html')
    mastery = html.split('id="mhNextCard"', 1)[1].split('</section>', 1)[0]
    assert mastery.index('id="mhFilters"') < mastery.index('id="mhNext"'), 'filters sit in the card head'
    mat = html.split('id="matCard"', 1)[1].split('id="dojoCard"', 1)[0]
    assert mat.index('id="matQ"') < mat.index('id="matTbl"'), 'the materials toolbar stays above its table'
    trade = html.split('id="view-trade"', 1)[1].split('</section>', 1)[0]
    plan = trade.split('id="planList"', 1)[0]
    assert 'id="btnPlan"' in plan and 'id="btnCycle"' in plan
    assert 'id="btnKill"' in html and 'id="killNote"' in html
