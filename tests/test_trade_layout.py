"""Trade view layout (Jay 2026-09-27): "really bad layout. needs to look clean and have proper
placement."

Source-level pins for the placement the QA probe measures headlessly (trade_probe.js +
trade_920.js). What was wrong and what these tests hold in place:

  * the plan table and the held-back panel share one row AND one height - both columns start on
    the same line and stop on the same line, each list scrolling inside its own half (before, the
    held panel was a closed 36px stub beside the table's lower half and the right column was dead
    space);
  * the plan scroller wears the same .scrolly cue the clan dojo table got (soft bottom fade,
    toggled by markScrollers() only when the list really has more rows) so a half-visible row
    reads as "scroll for more";
  * the Notes column is the flexible one again - a note is short by design and must read whole,
    only the advisor chip may ellipsize, and the cell keeps the whole line in its title;
  * Trade limit / Kill switch / Notifications are three EQUAL 1fr columns whose cards stretch to
    one height (same top, same bottom), the trade-limit numeral is the card's centrepiece, the
    kill switch has exactly ONE state element (the head chip) and ONE note field, and
    Notifications keeps its rows in an internal scroller;
  * the run queue is a five-column table (item / price / status / buyer / message) with a sticky
    header, the status keeping its own column and colour chip, the message truncating with the
    full whisper in its title;
  * Listings needing attention stays a compact strip whose rows sit on the same left/right column
    edges as the plan table.

Nothing here removes a row, a column, an id or a button.
"""
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(rel):
    with open(os.path.join(REPO, rel), encoding='utf-8') as fh:
        return fh.read()


# ---------------------------------------------------------------- 1. the split: same lines, real panel

def test_the_plan_table_and_the_held_panel_share_the_row_height():
    css = read('static/style.css')
    assert ('  .trade-split { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); }\n'
            '  .trade-split { grid-template-rows: minmax(0, 1fr); }') in css, 'one row, one height'
    assert '.trade-split { display: grid; grid-template-columns: minmax(0, 1fr); grid-template-rows: minmax(0, 1.6fr) minmax(0, 1fr);' in css
    assert '.trade-split { display: grid; grid-template-columns: minmax(0, 1fr); grid-template-rows: minmax(0, 1.6fr) minmax(0, 1fr); gap: 2px 12px; align-items: stretch; }' in css, \
        'align-items: stretch - not start - or the short column floats beside the tall one'
    assert '.trade-split > * { min-width: 0; min-height: 0; }' in css


def test_the_held_panel_is_open_and_its_list_is_the_scroller():
    html = read('static/index.html')
    assert '<details class="acc sub" id="heldAcc" open>' in html, 'the panel is not a stub you have to click'
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


# ---------------------------------------------------------------- 2. the .scrolly cue on the scrollers

def test_the_trade_scrollers_wear_the_dojo_scrolly_cue():
    css = read('static/style.css')
    # the dojo recipe is untouched: the trade lists get the same declared rule
    assert '.tablewrap.scrolly {' in css
    assert ('#view-trade .picks.scrolly {\n'
            '  -webkit-mask-image: linear-gradient(to bottom, #000 calc(100% - 46px), transparent);\n'
            '  mask-image: linear-gradient(to bottom, #000 calc(100% - 46px), transparent);\n}') in css, \
        'the band is 46px (the dojo table keeps 30px): a 30px band on a 31px row read as a hard cut'


def test_mark_scrollers_toggles_the_trade_lists_too():
    js = read('static/app.js')
    block = js.split('function markScrollers()', 1)[1].split('\n}', 1)[0]
    assert "document.querySelectorAll('.tablewrap').forEach" in block, 'the dojo pass stays'
    assert "document.querySelectorAll('#view-trade .picks').forEach" in block
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
    assert "const tip = escHtml(note) + (bits ? escHtml(' · advisor: ' + bits) : '');" in js
    assert 'class="p-note" title="${tip}"' in js, 'the full note + advisor line rides the title'


# ---------------------------------------------------------------- 4. the three cards: equal, aligned

def test_the_three_ops_cards_are_equal_columns_stretched_to_one_height():
    css = read('static/style.css')
    assert '.trade-ops { display: grid; grid-template-columns: minmax(0, 1fr); gap: 0 12px; align-items: stretch; }' in css
    assert '.trade-ops > .card { display: flex; flex-direction: column; min-width: 0; }' in css
    assert '.trade-ops > .card > .card-head { flex: 0 0 auto; }' in css
    block = css.split('@media (min-width: 1200px) {', 1)[1].split('\n}', 1)[0]
    assert '.trade-ops { grid-template-columns: repeat(3, minmax(0, 1fr)); }' in block, '1fr each, exactly three'


def test_trade_limit_numeral_is_the_centrepiece():
    css = read('static/style.css')
    assert '#view-trade .lim-hero { display: grid; gap: 9px; padding: 14px 10px 12px; align-content: center; }' in css
    assert '#view-trade .lim-hero .lim-big { font-size: 34px; line-height: 1.05; }' in css
    assert '.trade-ops > .card > #limList { flex: 1 1 auto; display: grid; align-content: center; }' in css
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
    assert '.trade-ops > .card > .picks.kill-input { flex: 0 0 auto; margin-top: auto; }' in css
    assert '.trade-ops > .card > #killList { flex: 0 0 auto;' in css


def test_notifications_rows_get_an_internal_scroller():
    css = read('static/style.css')
    assert '.trade-ops > .card > #notifyList { flex: 1 1 auto; overflow-y: auto; overscroll-behavior: contain; }' in css


# ---------------------------------------------------------------- 5. the run queue is a table

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


# ---------------------------------------------------------------- 6. the attention strip

def test_listings_needing_attention_stays_a_compact_aligned_strip():
    css = read('static/style.css')
    assert ('@media (min-width: 901px) {\n'
            '  #view-trade #attnList .attnrow { display: grid; grid-template-columns: minmax(0, 1fr) max-content; '
            'gap: 10px; align-items: baseline; }\n}') in css
    js = read('static/app.js')
    assert js.count('class="heldline attnrow"') == 2, 'both the undercut rows and the hygiene summary line'


# ---------------------------------------------------------------- ids + controls that must survive

def test_every_trade_id_and_control_survives_the_layout_pass():
    html = read('static/index.html')
    trade = html.split('id="view-trade"', 1)[1].split('</section>', 1)[0]
    for frag in ('id="planList"', 'id="heldList"', 'id="attnList"', 'id="hygieneList"', 'id="runqList"',
                 'id="killList"', 'id="notifyList"', 'id="limList"', 'id="planMeta"', 'id="heldMeta"',
                 'id="attnMeta"', 'id="hygieneMeta"', 'id="runqMeta"', 'id="killMeta"', 'id="notifyMeta"',
                 'id="limMeta"', 'id="btnPlan"', 'id="btnCycle"', 'id="btnWatch"', 'id="btnHygiene"',
                 'id="btnRunq"', 'id="btnKill"', 'id="btnNotify"', 'id="killNote"',
                 'id="tradeTabs"', 'id="tp-sell"', 'id="tp-buy"', 'id="tp-history"'):
        assert frag in trade, frag
    # the sub-tabs keep their names and their role=tab wiring
    tabs = trade.split('</nav>', 1)[0]
    for frag in ('role="tab"', '>Sell<', '>Buy<', '>History<'):
        assert frag in tabs, frag
