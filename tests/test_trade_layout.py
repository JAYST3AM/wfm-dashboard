"""Trade view layout (Jay 2026-09-27: "really bad layout. needs to look clean and have proper
placement.") - re-targeted by stage 4 (2026-09-28: Sell / Buy / History + one Safety & advanced
layer).

Source-level pins for the placement the QA probes measure headlessly (design/_stage4/qa_trade.js,
the earlier trade_probe.js / trade_920.js). What these tests hold in place:

  * the plan table and the held-back panel share one row AND one height when the panel is open
    (both columns start on the same line and stop on the same line, each list scrolling inside
    its own half) - and the panel is now a CLOSED disclosure by default, so a collapsed panel
    reserves nothing and the plan table keeps the whole row;
  * the plan scroller wears the same .scrolly cue the clan dojo table got (soft bottom fade,
    toggled by markScrollers() only when the list really has more rows) so a half-visible row
    reads as "scroll for more";
  * the Notes column is the flexible one - a note is short by design and must read whole, only
    the advisor chip may ellipsize, and the cell keeps the whole line in its title;
  * one action per row: a recommended listing or an attention row carries the slug and opens the
    shared item drawer (the same wfmOpenItem the inventory rows use) - there is no per-row button;
  * the engine internals (kill switch / trade limit / notifications) are three EQUAL 1fr columns
    in the Advanced panel, the trade-limit numeral is the card's centrepiece, the kill switch has
    exactly ONE state element (the head chip) and ONE note field, and Notifications keeps its rows
    in an internal scroller with LABELS (never a raw engine status);
  * the run queue is a five-column table (item / price / status / buyer / message) with a sticky
    header, the status keeping its own column and colour chip, the message truncating with the
    full whisper in its title;
  * Listings needing attention stays a compact strip whose rows sit on the same left/right column
    edges as the plan table.

Nothing here removes a row, a column, an id or a button.
"""
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# every trade id the stage-1 snapshot carried (design/_stage4/ids_before.json), plus the three
# stage-4 additions. Reachability is the contract: each id is asserted somewhere in index.html.
# 2026-09-28: Jay added the Orders tab (its own tab, first in the strip) - tt-orders / tp-orders
# join this list here; nothing above was removed and the two new ids are also pinned in
# tests/test_trade_orders_tab.py.
TRADE_IDS = (
    'view-trade', 'tradeTabs', 'tt-orders', 'tt-sell', 'tt-buy', 'tt-history', 'tt-advanced',
    'tp-orders', 'tp-sell', 'tp-buy', 'tp-history', 'tp-advanced',
    'planMeta', 'btnPlan', 'btnCycle', 'planList', 'heldAcc', 'heldMeta', 'heldList',
    'attnMeta', 'btnWatch', 'attnList', 'hygieneAcc', 'hygieneMeta', 'btnHygiene', 'hygieneList',
    'flipsMeta', 'flipsList', 'wishMeta', 'wishList', 'histKpis', 'histMeta', 'hFilters',
    'tradeLog', 'sessMeta', 'sessList', 'timingMeta', 'timingList', 'ledgerMeta', 'ledgerList',
    'limMeta', 'limList', 'killMeta', 'btnKill', 'killNote', 'killList', 'notifyMeta', 'btnNotify',
    'notifyList', 'runqMeta', 'btnRunq', 'runqList', 'postMode',
)

# the ids the Advanced panel must contain (the internals + the safety pair)
ADVANCED_IDS = ('killMeta', 'btnKill', 'killNote', 'killList', 'limMeta', 'limList',
                'notifyMeta', 'btnNotify', 'notifyList', 'runqMeta', 'btnRunq', 'runqList',
                'hygieneAcc', 'hygieneMeta', 'btnHygiene', 'hygieneList')


def read(rel):
    with open(os.path.join(REPO, rel), encoding='utf-8') as fh:
        return fh.read()


def trade_section(html):
    return html.split('id="view-trade"', 1)[1].split('</section>', 1)[0]


def panel(html, pid, nxt):
    """one tab panel's markup: from its wrapper to the next panel's wrapper"""
    return trade_section(html).split('id="%s"' % pid, 1)[1].split('id="%s"' % nxt, 1)[0]


# ---------------------------------------------------------------- 1. the split: same lines, real panel

def test_the_plan_table_and_the_held_panel_share_the_row_height():
    css = read('static/style.css')
    assert ('.trade-split { display: grid; grid-template-columns: minmax(0, 1fr); grid-template-rows: '
            'minmax(0, 1.6fr) minmax(0, 1fr); gap: 2px 12px; align-items: stretch; }') in css, \
        'align-items: stretch - not start - or the short column floats beside the tall one'
    assert '.trade-split > * { min-width: 0; min-height: 0; }' in css
    block = css.split('@media (min-width: 1500px) {', 1)[1].split('\n}', 1)[0]
    assert '.trade-split { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); }' in block, \
        'one row, one height - both columns start and stop on the same line'
    assert '.trade-split { grid-template-rows: minmax(0, 1fr); }' in block
    # stage 4: the panel is a closed disclosure by default and a closed panel reserves NO half -
    # the plan table keeps the row until the panel is opened
    assert '.trade-split:has(> details.acc.sub:not([open])) { grid-template-rows: minmax(0, 1fr) auto; }' in css, \
        'a collapsed held panel is a strip, not a reserved half'
    assert ('.trade-split:has(> details.acc.sub:not([open])) { grid-template-columns: minmax(0, 1fr); '
            'grid-template-rows: minmax(0, 1fr) auto; }') in block, \
        'the >=1500px split drops back to one column while the panel is collapsed'


def test_the_held_panel_is_a_closed_disclosure_and_its_list_is_the_scroller():
    html = read('static/index.html')
    assert '<details class="acc sub" id="heldAcc">' in html, \
        'the panel is a 1-click disclosure (stage 4: no card dumps, no open attribute)'
    assert 'id="heldAcc" open' not in html
    css = read('static/style.css')
    assert '.trade-split > details.acc.sub { margin: 0; display: flex; flex-direction: column; }' in css
    assert '.trade-split > details.acc.sub > .picks { flex: 1 1 auto; overflow-y: auto; overscroll-behavior: contain; }' in css
    assert 'body.shell-fit #view-trade #heldAcc { overflow: hidden; }' in css, \
        'the panel itself does not scroll - the list inside it does'
    assert 'body.shell-fit #view-trade #heldList { flex: 1 1 auto; min-height: 0; overflow-y: auto; }' in css
    js = read('static/app.js')
    assert "heldAcc.addEventListener('toggle', () => markScrollers())" in js, \
        'collapsing the panel changes the plan column height'


def test_the_held_summary_sits_on_the_plan_header_line():
    css = read('static/style.css')
    assert '#view-trade .trade-split > details.acc.sub > summary { padding: 3px 12px; }' in css, \
        'the summary is as tall as the plan header row: both columns start their rows on one line'


def test_the_sell_panel_is_the_window_and_the_plan_list_is_its_scroller():
    """Stage 4 fit: the view is the tab row + the active panel; the plan card hugs its rows (a
    short plan must not leave a hole between the last row and the held-back strip) and gives the
    height back when the window is short - then #planList scrolls inside the card."""
    css = read('static/style.css')
    assert ('body.shell-fit #view-trade {\n'
            '    display: grid; grid-template-rows: auto minmax(200px, 1fr);\n  }') in css
    assert ('body.shell-fit #view-trade #tp-sell > .card:first-child {\n'
            '    flex: 0 1 auto; min-height: 0; display: flex; flex-direction: column;\n  }') in css
    assert 'body.shell-fit #view-trade #planList, body.shell-fit #view-trade #heldAcc {' in css
    assert 'body.shell-fit #view-trade #tp-sell .trade-split { flex: 1 1 auto; min-height: 0; }' in css


# ---------------------------------------------------------------- 2. the .scrolly cue on the scrollers

def test_the_trade_scrollers_wear_the_dojo_scrolly_cue():
    css = read('static/style.css')
    # the dojo recipe is untouched: the trade lists get the same declared rule
    assert '.tablewrap.scrolly {' in css
    assert ('#view-trade .picks.scrolly {\n'
            '  -webkit-mask-image: linear-gradient(to bottom, #000 calc(100% - 46px), transparent);\n'
            '  mask-image: linear-gradient(to bottom, #000 calc(100% - 46px), transparent);\n}') in css, \
        'the band is 46px (the dojo table keeps 30px): a 30px band on a 31px row read as a hard cut'
    # stage 4: the Advanced panel's lists carry the same class, so markScrollers() still describes
    # every trade list that scrolls (a list without class="picks" loses its fade silently)
    html = read('static/index.html')
    adv = trade_section(html).split('id="tp-advanced"', 1)[1]
    for lid in ('limList', 'killList', 'notifyList', 'runqList', 'hygieneList'):
        lst = adv.split('id="%s"' % lid, 1)[0].rsplit('<div', 1)[1]
        assert 'class="picks' in lst, lid


def test_mark_scrollers_toggles_the_trade_lists_too():
    js = read('static/app.js')
    block = js.split('function markScrollers()', 1)[1].split('\n}', 1)[0]
    assert "document.querySelectorAll('.tablewrap').forEach" in block, 'the dojo pass stays'
    # 2026-09-28: the Orders ladder joined this pass (Jay's Orders tab, its own scroller) - the
    # selector grew by one id, the behaviour and the cue test below are unchanged. The ladder's
    # own pin lives in tests/test_trade_orders_tab.py.
    assert "document.querySelectorAll('#view-trade .picks, #view-trade #ordValues').forEach" in block
    assert "(oy === 'auto' || oy === 'scroll') && el.scrollHeight > el.clientHeight + 2" in block, \
        'only a real scroller with more below gets the fade'
    for hook in ('markScrollers();', "if (v === 'trade') markScrollers();"):
        assert hook in js, hook
    assert 'renderRunQueue(); renderHygiene(); renderNotify(); markScrollers();' in js, \
        'a trade re-render re-marks the scrollers'
    assert 'new ResizeObserver(function () {' in js and '_scrollerRO.observe(document.body);' in js, \
        'the lists are re-marked once layout settles and on every reflow'


# ---------------------------------------------------------------- 3. the notes column budget

def test_the_notes_column_has_a_real_width_budget():
    css = read('static/style.css')
    block = css.split('@media (min-width: 901px) {', 1)[1].split('\n}', 1)[0]
    assert '22px minmax(168px, 1fr) 44px 62px 74px minmax(232px, 1.35fr); gap: 8px;' in block, \
        'the notes take the flexible share (>= 232px); the item column stops at 168px'
    # the note text never shrinks: the advisor chip takes the truncation, the cell keeps the title
    assert '#view-trade .prow .p-note { display: flex; gap: 6px; align-items: baseline; min-width: 0; }' in css
    assert '#view-trade .prow .p-note > .p-notxt { flex: 0 0 auto;' in css
    assert '#view-trade .prow .p-note > .advchip { flex: 0 1 auto; min-width: 0;' in css
    js = read('static/app.js')
    assert '<span class="p-notxt">${note}</span>${advNote(r.slug)}' in js
    # the visible note keeps whole facts up to the 8-word budget; the title carries all of it
    assert 'const note = fitSegments(noteFull, 8);' in js
    assert "const tip = escHtml(noteFull) + (bits ? escHtml(' · advisor: ' + bits) : '');" in js
    assert 'class="p-note" title="${tip}"' in js, 'the full note + advisor line rides the title'


# ---------------------------------------------------------------- 4. one action per row

def test_every_plan_row_and_every_attention_row_carries_the_one_row_action():
    """Stage 4: the only per-row affordance is the shared item drawer. No second button, no
    per-row POST - the row carries its slug and the whole row is the target."""
    js = read('static/app.js')
    assert "const act = r.slug ? ` data-slug=\"${escHtml(r.slug)}\" title=\"Open item\"` : '';" in js
    assert '<div class="prow"${act}>' in js
    assert 'class="heldline attnrow"${r.slug ?' in js
    assert "tradeView.addEventListener('click'" in js
    assert 'if (row && row.dataset.slug && window.wfmOpenItem) wfmOpenItem(row.dataset.slug);' in js
    assert "const tr = e.target.closest('tr.inv-row');" in js, 'same pattern as the inventory rows'
    css = read('static/style.css')
    assert '#view-trade .prow[data-slug], #view-trade .attnrow[data-slug] { cursor: pointer; }' in css
    # nothing engine-side competes with the plan on the Sell surface
    sell = panel(read('static/index.html'), 'tp-sell', 'tp-buy')
    for frag in ADVANCED_IDS:
        assert 'id="%s"' % frag not in sell, frag


# ---------------------------------------------------------------- 5. the Advanced panel

def test_the_advanced_panel_stacks_three_equal_cards_and_carries_the_internals():
    css = read('static/style.css')
    assert '.adv-cards { display: grid; grid-template-columns: minmax(0, 1fr); gap: 0 12px; align-items: stretch; }' in css
    assert '.adv-cards > .card { display: flex; flex-direction: column; min-width: 0; }' in css
    assert '.adv-cards > .card > .card-head { flex: 0 0 auto; }' in css
    block = css.split('@media (min-width: 1200px) {', 1)[1].split('\n}', 1)[0]
    assert '.adv-cards { grid-template-columns: repeat(3, minmax(0, 1fr)); }' in block, '1fr each, exactly three'
    html = read('static/index.html')
    adv = trade_section(html).split('id="tp-advanced"', 1)[1]
    three = adv.split('<div class="adv-cards">', 1)[1].split('Run queue - best buyers', 1)[0]
    for frag in ('id="killList"', 'id="limList"', 'id="notifyList"', 'id="btnKill"', 'id="btnNotify"'):
        assert frag in three, frag


def test_trade_limit_numeral_is_the_centrepiece():
    css = read('static/style.css')
    assert '#view-trade .lim-hero { display: grid; gap: 9px; padding: 14px 10px 12px; align-content: center; }' in css
    assert '#view-trade .lim-hero .lim-big { font-size: 34px; line-height: 1.05; }' in css
    assert '.adv-cards > .card > #limList { flex: 1 1 auto; display: grid; align-content: center; }' in css
    for frag in ('#view-trade .limbar {', '#view-trade .limbar > i {'):
        assert frag in css, frag
    js = read('static/app.js')
    assert 'class="limrow lim-hero"' in js and 'class="limbar" title="used ${used} of ${cap}"' in js


def test_kill_switch_has_one_state_element_and_one_note_field():
    html = read('static/index.html')
    css = read('static/style.css')
    js = read('static/app.js')
    assert html.count('id="killNote"') == 1, 'the note field exists once - renderKill must not clone it'
    assert 'id="killNote"' not in js, 'renderKill no longer injects a second note input'
    assert "meta.className = K.active ? 'chip kill-on' : 'chip';" in js, 'the head chip is the one state'
    assert "meta.textContent = K.active ? 'ARMED' : 'disarmed';" in js
    assert 'kill switch ${K.active' not in js and "'OFF'" not in js, 'no second disarmed/OFF anywhere'
    assert 'id="btnKill"' in html
    # the note field spans the card, not a 220px stub in the left half
    assert '#view-trade .noteinput { width: 100%; max-width: none;' in css
    assert '.adv-cards > .card > .picks.kill-input { flex: 0 0 auto; margin-top: auto; }' in css
    assert '.adv-cards > .card > #killList { flex: 0 0 auto;' in css


def test_notifications_rows_get_an_internal_scroller_and_a_label_map():
    css = read('static/style.css')
    assert '.adv-cards > .card > #notifyList { flex: 1 1 auto; min-height: 0; overflow-y: auto; overscroll-behavior: contain; }' in css
    js = read('static/app.js')
    # stage 4: the cell shows the label, never the raw engine status (dry_run is data, not copy)
    assert "const NLABEL = { sent: 'sent', dry_run: 'not live', held: 'not live', failed: 'failed' };" in js
    assert '${escHtml(NLABEL[r.status] || r.status)}' in js


# ---------------------------------------------------------------- 6. the run queue is a table

def test_the_run_queue_rows_are_five_fixed_columns():
    css = read('static/style.css')
    assert '.runrow { grid-template-columns: minmax(0, 1.5fr) 84px 104px minmax(0, 1.1fr) minmax(0, 1.6fr);' in css, \
        'item / price / status / buyer / message'
    assert '.runrow .r-price { text-align: right; font-family: var(--mono); font-variant-numeric: tabular-nums; }' in css
    assert '.runrow .r-name, .runrow .r-buyer { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }' in css
    assert '.runrow.runhead { position: sticky; top: 0;' in css, 'the header stays put while the queue scrolls'
    js = read('static/app.js')
    assert "'<div class=\"runrow runhead\"><span>Item</span><span class=\"r-price\">Price</span>'" in js
    for cell in ('class="r-name"', 'class="r-price"', 'class="r-status"', 'class="r-buyer"', 'class="runwhisper"'):
        assert cell in js, cell
    assert '<span class="chip act-${q.buyer_status}">${q.buyer_status}</span>' in js, 'the status colour chip stays'
    assert 'title="${escHtml(q.whisper)}"' in js, 'the full whisper rides the message cell title'


# ---------------------------------------------------------------- 7. the attention strip

def test_listings_needing_attention_stays_a_compact_aligned_strip():
    css = read('static/style.css')
    assert ('@media (min-width: 901px) {\n'
            '  #view-trade #attnList .attnrow { display: grid; grid-template-columns: minmax(0, 1fr) max-content; '
            'gap: 10px; align-items: baseline; }\n}') in css
    js = read('static/app.js')
    assert js.count('class="heldline attnrow"') == 2, 'both the undercut rows and the hygiene summary line'
    # the hygiene plan left the Sell card (its one-liner stays as the second attention row)
    html = read('static/index.html')
    sell = panel(html, 'tp-sell', 'tp-buy')
    assert 'id="hygieneList"' not in sell and 'id="hygieneAcc"' not in sell


# ---------------------------------------------------------------- 8. the tabs and the layer

def test_the_three_tabs_and_the_advanced_layer_are_wired_as_one_tablist():
    html = read('static/index.html')
    sec = trade_section(html)
    nav = sec.split('<nav id="tradeTabs"', 1)[1].split('</nav>', 1)[0]
    # 2026-09-28: the count moved 4 -> 5 because Jay asked for the Orders tab FIRST in the strip
    # (it is pinned in tests/test_trade_orders_tab.py). Nothing was dropped, Sell is still the
    # selected panel on load, and every other tab keeps its own exact button markup below.
    assert 'role="tablist"' in nav and nav.count('role="tab"') == 5
    assert ('id="tt-orders" data-tp="tp-orders" aria-selected="false" aria-controls="tp-orders">Orders</button>'
            in nav)
    assert 'id="tt-sell" data-tp="tp-sell" aria-selected="true" aria-controls="tp-sell">Sell</button>' in nav
    for tid, tp, label in (('tt-buy', 'tp-buy', 'Buy'), ('tt-history', 'tp-history', 'History'),
                           ('tt-advanced', 'tp-advanced', 'Advanced')):
        assert ('id="%s" data-tp="%s" aria-selected="false" aria-controls="%s">%s</button>'
                % (tid, tp, tp, label)) in nav, tid
    # one panel shows at a time: Sell is open, the other three ship hidden
    assert '<div id="tp-sell" class="tpanel" role="tabpanel" aria-labelledby="tt-sell">' in sec
    for pid, tid in (('tp-buy', 'tt-buy'), ('tp-history', 'tt-history'), ('tp-advanced', 'tt-advanced')):
        assert ('<div id="%s" class="tpanel hidden" role="tabpanel" aria-labelledby="%s">'
                % (pid, tid)) in sec, pid
    js = read('static/app.js')
    assert "document.querySelectorAll('#tradeTabs [role=\"tab\"]')" in js
    assert "document.querySelectorAll('#view-trade .tpanel').forEach" in js
    assert "document.querySelectorAll('#view-trade .tpanel').forEach(p2 => p2.classList.toggle('hidden', p2.id !== panelId));" in js
    assert "switchTradeTab(v === 'history' ? 'tp-history' : (sub ? 'tp-' + sub : 'tp-sell'));" in js, \
        '#trade/advanced deep-links the layer'


def test_the_advanced_layer_is_one_click_from_sell_and_holds_its_ids():
    html = read('static/index.html')
    adv = trade_section(html).split('id="tp-advanced"', 1)[1]
    for aid in ADVANCED_IDS:
        assert 'id="%s"' % aid in adv, aid
    # the safety pair is NOT inside the panel's one disclosure
    assert adv.count('<details') == 1, 'the only disclosure in the layer is the hygiene plan'
    assert adv.split('<details', 1)[1].split('</details>', 1)[0].count('id="hygieneList"') == 1
    assert 'id="killList"' in adv.split('<details', 1)[0], 'the kill switch is a plain card'
    assert 'id="limList"' in adv.split('<details', 1)[0], 'the trade limit is a plain card'
    # and it is one click: the tab button lives in the same tablist as Sell
    nav = trade_section(html).split('id="tradeTabs"', 1)[1].split('</nav>', 1)[0]
    assert 'id="tt-advanced"' in nav


def test_the_posting_badge_reads_the_real_config():
    """The chip may never claim live posting while dry_run is locked: it is rendered from
    /api/trader (settings.json + the plan's own dry_run), never hardcoded."""
    html = read('static/index.html')
    assert 'id="postMode"' in trade_section(html)
    assert 'Not live - nothing is posted' not in html, 'the chip is renderer-owned, not baked in'
    js = read('static/app.js')
    assert 'const dry = set.dry_run === true || plan.dry_run === true;' in js
    assert "pm.textContent = dry ? 'Not live - nothing is posted' : 'Live';" in js
    assert "pm.className = dry ? 'chip' : 'chip kill-on';" in js, 'live posting wears the warning colour'
    # the other two honest lines survive: hygiene says plan-only, the kill switch says Not live
    assert 'NOT LIVE - plan only' in js
    assert "<span class=\"dim small explain\">Not live</span>" in js


def test_card_headings_wrap_so_a_narrow_column_never_clips_its_title():
    """Stage 4 audit minor: the Notify heading clipped at 1200-1600px (content 514px inside a
    305-405px card) because [data-icon] hosts never wrap. The trade headings may wrap."""
    css = read('static/style.css')
    assert '#view-trade .card-title { white-space: normal; }' in css
    assert '#view-trade .card-title[data-icon] { white-space: normal; overflow-wrap: break-word; }' in css
    assert css.index('#view-trade .card-title[data-icon]') < css.index('@media (min-width: 1200px) {')


# ---------------------------------------------------------------- ids + controls that must survive

def test_every_trade_id_and_control_survives_the_layout_pass():
    """Reachability, not placement (stage 4): every id still exists in index.html, wherever on the
    Trade surface it now lives."""
    html = read('static/index.html')
    for tid in TRADE_IDS:
        assert 'id="%s"' % tid in html, tid
    # the sub-tabs keep their names and their role=tab wiring (Orders joined 2026-09-28, first)
    tabs = trade_section(html).split('</nav>', 1)[0]
    for frag in ('role="tab"', '>Orders<', '>Sell<', '>Buy<', '>History<', '>Advanced<'):
        assert frag in tabs, frag
